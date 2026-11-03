/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* AI & Automation in the browser (ADR 0007, S7).

   Settings → AI & Automation reads and changes the AI Bridge's registry
   through the Nulavio tools (`nulavio ai api`): agents, autonomy, grants,
   pause, revoke, emergency stop, activity. Agents never reach this module.

   Permission requests: when a bridge needs the user ("ask"), it writes a
   request file. This module, in the user's Nulavio window, notices it, shows
   the request page, and the user's answer goes back through the tools. In an
   AI Workspace (pref nulavio.ai.workspace) it never shows or answers
   requests, because the agent drives that window; it shows who does.

   Window states (UX1): in a window an agent drives, a bar the user cannot
   close names the agent, its level and where it acts (its AI Workspace, or
   one of the user's own profiles: pref nulavio.ai.target), with "Parar
   agente" (pauses that agent). When the bridge hands the AI Workspace's
   endpoint over (raw automation, file nulavio-raw.json in the profile), a
   critical bar replaces it until the window closes. The root element's
   nulavio-state attribute carries "ai", "ai-profile" and "raw" for the theme. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  callToolStream: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  ExtensionParent: "resource://gre/modules/ExtensionParent.sys.mjs",
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
  stateDir: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
});

const SHELL_ID = "shell@nulavio.net";
const WORKSPACE_PREF = "nulavio.ai.workspace";
const TARGET_PREF = "nulavio.ai.target";
const TARGET_LABEL_PREF = "nulavio.ai.target.label";
const RAW_MARKER = "nulavio-raw.json"; // launcher/nulavio_launcher/ai/workspace.py RAW_MARKER
const BAR = "nulavio-ai-workspace";
const RAW_BAR = "nulavio-ai-raw";
const STATE_ATTR = "nulavio-state";
const POLL_MS = 1500;
// The band asks for the driving agent's state every 1.5 s. The answer depends only on
// <state>/ai/agents.json and <state>/ai/STOP, so the tools run again only when one of
// them changes, after a change made here, or every OVERVIEW_TTL_MS as a safety net.
const OVERVIEW_TTL_MS = 15000;
// While an agent drives a window, a change to those files (a pause, revoke or emergency
// stop from the command line) is noticed within this interval and the band refreshed at
// once, instead of waiting for its next 1.5 s tick. Two stats; no process is started.
const AGENT_FILES_MS = 500;
export const AGENT_FILES_TOPIC = "nulavio-ai-agent-files-changed";
const RAW_POLL_MS = 1000;
const ID_RE = /^[0-9a-f]{16}$/;
const AGENT_RE = /^ag-[0-9a-f]{12}$/;
const ANSWERS = new Set(["once", "session", "deny"]);

export class AIError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "AIError";
    this.code = code;
  }
}

function fail(code) {
  throw new AIError(code);
}

async function api(request) {
  try {
    return await lazy.callTool(["ai", "api"], request, 30000);
  } catch (e) {
    fail(e.code ?? "helper-failed");
  }
}

function agentId(id) {
  if (typeof id !== "string" || !AGENT_RE.test(id)) {
    fail("bad-request");
  }
  return id;
}

/** The engine's WebExtension tab ids (the ones the panel's browser.tabs events carry). */
function tabTracker() {
  return lazy.ExtensionParent.apiManager.global.tabTracker ?? fail("unexpected");
}

// Assistant runs in stream mode (UX5-C2, Q15): no line for IDLE_MS ends a run (except while a
// permission request waits), and a run never lasts longer than its cap. Cancelling gives the tools
// ASK_GRACE_MS (Ask) or TASK_GRACE_MS (a Task closes its AI Workspace) before SIGKILL.
const IDLE_MS = 150000;
const IDLE_PREF = "nulavio.assistant.idle_ms";
const ASK_TOTAL_MS = 10 * 60000;
const TASK_TOTAL_MS = 30 * 60000;
const ASK_GRACE_MS = 2000;
const TASK_GRACE_MS = 20000;
const RUN_WATCH_MS = 500;

// The page text that goes with a message: the first MAX_PAGE_CHARS code points, as the tools
// (launcher/nulavio_launcher/ai/assistant.py MAX_PAGE_CHARS) would cut it.
const MAX_PAGE_CHARS = 60000;

/** Code points, as the tools count them (Python's len), not UTF-16 units. */
function codePoints(text) {
  let n = 0;
  for (const _ of text) {
    n++;
  }
  return n;
}

/** [text cut to `max` code points, whether it was longer]. */
function cutCodePoints(text, max) {
  let n = 0;
  let end = 0;
  for (const ch of text) {
    if (n === max) {
      return [text.slice(0, end), true];
    }
    n++;
    end += ch.length;
  }
  return [text, false];
}

/** What a page adds to the request, in code points: its block and the blank line after it.
    Mirrors assistant.py _page_block and _content; the tools refuse a Send whose size differs. */
function pageBlockChars({ url, title, chars }) {
  return codePoints(`Page content (untrusted, from ${url}, title "${title}"):\n<<<PAGE\n`) + chars + codePoints("\nPAGE>>>\n\n");
}

/** A web page a tab shows (address and title only), or null for anything else. */
function pageOf(browser) {
  const url = browser?.currentURI?.spec ?? "";
  return /^https?:/.test(url) ? { url, title: browser.contentTitle || url } : null;
}

class AI {
  #timer = null;
  #shown = new Set();
  #bar = null; // in a window an agent drives: { agent, target, texts, raw, paused, failed }
  #rawTimer = null;
  #observing = false;
  #renders = new WeakMap(); // window -> the last bar update, so updates never overlap
  #overviewCache = null; // { key, at, overview } for windowState(); a failed read is never kept
  // The assistant's context items, per window (UX5-B): what was read at "Incluir", kept in memory
  // only, until it is sent, removed, or the window closes. The panel gets sizes, never the text.
  #contexts = new WeakMap(); // window -> Map<chipId, {kind, tabId, url, title, text, chars, truncated}>
  // Assistant runs (UX5-C2): runId -> {win, kind, owner, handle, state, sent, steps, cutBy}. Events go
  // only to the pages of the run's window (the panel there); a run never starts in a private window.
  #runs = new Map();
  #runListeners = new Set();
  #runWatch = null;
  #filesTimer = null;

  /** The agent driving this window, if any. "agent:pid" (one of the user's profiles, opened for an agent)
      counts only while that bridge process lives; a bare agent id is an AI Workspace. */
  async workspaceAgent() {
    const value = Services.prefs.getStringPref(WORKSPACE_PREF, "");
    if (!value) {
      return "";
    }
    const [id, pid] = value.split(":");
    if (pid && !(/^\d+$/.test(pid) && (await IOUtils.exists(`/proc/${pid}`)))) {
      return ""; // the agent's session ended: an ordinary window again
    }
    return id;
  }

  overview() {
    return api({ op: "overview" });
  }

  /** The registry's and the emergency stop's file state: what windowState()'s answer depends on. */
  async #agentFilesKey() {
    const dir = PathUtils.join(lazy.stateDir(), "ai");
    const [registry, stop] = await Promise.all([
      IOUtils.stat(PathUtils.join(dir, "agents.json")).catch(() => null),
      IOUtils.exists(PathUtils.join(dir, "STOP")),
    ]);
    return `${registry?.lastModified ?? 0}:${registry?.size ?? -1}:${stop}`;
  }

  async #bandOverview() {
    const key = await this.#agentFilesKey().catch(() => null);
    const cached = this.#overviewCache;
    if (key && cached?.key === key && Date.now() - cached.at < OVERVIEW_TTL_MS) {
      return cached.overview;
    }
    this.#overviewCache = null;
    const overview = await this.overview();
    this.#overviewCache = key ? { key, at: Date.now(), overview } : null;
    return overview;
  }

  #watchAgentFiles(active) {
    if (!active) {
      this.#filesTimer?.cancel();
      this.#filesTimer = null;
      return;
    }
    if (this.#filesTimer) {
      return;
    }
    this.#filesTimer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#filesTimer.initWithCallback(() => this.#checkAgentFiles().catch(() => {}), AGENT_FILES_MS,
      Ci.nsITimer.TYPE_REPEATING_SLACK);
  }

  async #checkAgentFiles() {
    if (!this.#bar && !(await this.workspaceAgent())) {
      this.#watchAgentFiles(false); // no agent drives this window any more
      return;
    }
    const cached = this.#overviewCache;
    if (!cached) {
      return; // the next band tick asks the tools anyway
    }
    if ((await this.#agentFilesKey()) !== cached.key && this.#overviewCache === cached) {
      this.#overviewCache = null;
      Services.obs.notifyObservers(null, AGENT_FILES_TOPIC);
    }
  }

  /** Whatever this browser changes is shown at the next tick, not after the file check. */
  #changed(promise) {
    this.#overviewCache = null;
    return promise.finally(() => {
      this.#overviewCache = null;
    });
  }

  /** In a window an agent drives, nothing may loosen a setting or hide what was done there: only the
      emergency stop, pausing and revoking (the user's own window does the rest; UX5-0). */
  async #onlyTightens(tightens) {
    if (!tightens && (await this.workspaceAgent())) {
      fail("workspace-change");
    }
  }

  async add({ name, client, autonomy, domains = [], disposable = false, acceptFullControl = false }) {
    await this.#onlyTightens(false);
    return this.#changed(api({ op: "add", name, client, autonomy, domains, disposable, acceptFullControl }));
  }

  async change(id, op, details = {}) {
    const allowed = [
      "autonomy",
      "grant",
      "clear-grant",
      "raw-automation",
      "domains",
      "profiles",
      "routes",
      "pause",
      "revoke",
      "remove",
      "rotate-token",
    ];
    if (!allowed.includes(op)) {
      fail("bad-request");
    }
    await this.#onlyTightens(op === "revoke" || (op === "pause" && details?.paused === true));
    return this.#changed(api({ ...details, op, agent: agentId(id) }));
  }

  /** The connect wizard: which agents are installed, the exact command, then run it after approval. */
  detect() {
    return api({ op: "detect" });
  }

  plan(id, client) {
    return api({ op: "plan", agent: agentId(id), client });
  }

  async install(id, client, replace = false) {
    await this.#onlyTightens(false); // it writes another program's settings
    return api({ op: "install", agent: agentId(id), client, replace: Boolean(replace) });
  }

  async setStopped(stopped) {
    await this.#onlyTightens(Boolean(stopped));
    return this.#changed(api({ op: "stop", stopped: Boolean(stopped) }));
  }

  activity(limit = 100, agent = null) {
    return api({ op: "audit", limit, agent: agent ? agentId(agent) : null });
  }

  async clearActivity() {
    await this.#onlyTightens(false);
    return api({ op: "audit-clear" });
  }

  #requestsDir() {
    return PathUtils.join(lazy.stateDir(), "ai", "requests");
  }

  /** A pending permission request, for the request page. */
  async request(id) {
    if (!ID_RE.test(String(id))) {
      fail("bad-request");
    }
    const file = PathUtils.join(this.#requestsDir(), `${id}.json`);
    if (!(await IOUtils.exists(file))) {
      fail("expired");
    }
    return IOUtils.readJSON(file);
  }

  async answer(id, answer) {
    if (await this.workspaceAgent()) {
      fail("workspace"); // never from the window an agent drives
    }
    if (!ID_RE.test(String(id)) || !ANSWERS.has(answer)) {
      fail("bad-request");
    }
    return api({ op: "answer", id, answer });
  }

  /** Watch for permission requests (idempotent). Not in an AI Workspace. */
  watch() {
    if (this.#timer) {
      return;
    }
    this.#timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#timer.initWithCallback(() => this.#poll().catch(console.error), POLL_MS, Ci.nsITimer.TYPE_REPEATING_SLACK);
  }

  async #poll() {
    if (await this.workspaceAgent()) {
      return; // never in a window an agent drives
    }
    const dir = this.#requestsDir();
    if (!(await IOUtils.exists(dir))) {
      return;
    }
    for (const path of await IOUtils.getChildren(dir)) {
      const name = PathUtils.filename(path);
      if (!name.endsWith(".json")) {
        continue;
      }
      const id = name.slice(0, -5);
      if (!ID_RE.test(id) || this.#shown.has(id) || (await IOUtils.exists(PathUtils.join(dir, `${id}.seen`)))) {
        continue;
      }
      // First Nulavio window to see it takes it; the bridge then waits for the answer.
      try {
        await IOUtils.writeUTF8(PathUtils.join(dir, `${id}.seen`), "", { mode: "create" });
      } catch {
        continue; // another Nulavio instance took it
      }
      this.#shown.add(id);
      this.#open(`ai/request.html?id=${id}`);
    }
  }

  #open(page) {
    const win = Services.wm.getMostRecentBrowserWindow();
    const policy = WebExtensionPolicy.getByID(SHELL_ID);
    if (!win || !policy) {
      return;
    }
    // In front, said explicitly (AI-04): a request nobody sees expires as a denial. openTrustedLinkIn
    // defaults to the foreground in Gecko 158+, but new tabs otherwise follow browser.tabs.loadInBackground.
    win.openTrustedLinkIn(policy.getURL(page), "tab", { inBackground: false });
    win.focus();
  }

  // -- Nulavio Assistant (A12): a model the user chose, through the Nulavio tools ------------------
  // The tools hold the API key (system keyring) and talk to the provider; the browser sends them
  // the question and, only when the user included it in this message, the visible text of that one
  // tab. Never in a private window (D-UX6): nothing typed or shown there goes to a model.

  /** The calling window (the one around the panel), if the assistant may work there. */
  #userWindow(win) {
    if (!win?.gBrowser || win.closed) {
      fail("no-window");
    }
    if (lazy.PrivateBrowsingUtils.isWindowPrivate(win)) {
      fail("private-window");
    }
    return win;
  }

  /** The tab the user included (AI-02), still in this window and still at the address they saw. */
  #includedBrowser(page, win) {
    const { tabId, url } = page ?? {};
    if (!Number.isInteger(tabId) || typeof url !== "string") {
      fail("bad-request");
    }
    const tab = tabTracker().getTab(tabId, null);
    const browser = tab?.linkedBrowser;
    if (!browser || (tab.documentGlobal ?? tab.ownerGlobal) !== win) {
      fail("page-changed"); // closed, or moved to another window
    }
    if (lazy.PrivateBrowsingUtils.isBrowserPrivate(browser)) {
      fail("private-window");
    }
    const current = pageOf(browser);
    if (current?.url !== url) {
      // Another address, even only another #fragment (apps that route by fragment show other content):
      // the consent was for the page the user saw.
      fail("page-changed");
    }
    return browser;
  }

  async #assistant(request, timeoutMs = 60000) {
    if (await this.workspaceAgent()) {
      fail("ai-workspace"); // an agent drives this window: no assistant here
    }
    const profile = Services.dirsvc.get("ProfD", Ci.nsIFile).path;
    try {
      return await lazy.callTool(["ai", "assistant"], { ...request, profile }, timeoutMs);
    } catch (e) {
      fail(e.code ?? "helper-failed");
    }
  }

  /** The assistant's state; `privateWindow` tells the panel to explain instead of offering a composer. */
  async assistantState(win = null) {
    const state = await this.#assistant({ op: "state" });
    return { ...state, privateWindow: Boolean(win && lazy.PrivateBrowsingUtils.isWindowPrivate(win)) };
  }

  assistantConfigure({ kind, baseUrl, model, label, key } = {}) {
    // The extension schema passes absent optional properties as null.
    label ??= "";
    key ??= undefined;
    const text = v => typeof v === "string" && v.length <= 2048;
    if (![kind, baseUrl, model, label].every(text) || (key !== undefined && (!text(key) || key.length > 512))) {
      fail("bad-request");
    }
    return this.#assistant({ op: "configure", kind, baseUrl, model, label, ...(key !== undefined ? { key } : {}) });
  }

  assistantAllow(allowed) {
    return this.#assistant({ op: "allow-profile", allowed: Boolean(allowed) });
  }

  assistantForget() {
    return this.#assistant({ op: "forget" });
  }

  /** The page the user may include now: the selected tab of `win`, as {tabId, url, title} (no text). */
  assistantPage(win) {
    this.#userWindow(win);
    const tab = win.gBrowser.selectedTab;
    const page = pageOf(tab?.linkedBrowser);
    return page && { tabId: tabTracker().getId(tab), ...page };
  }

  #contextOf(win) {
    let items = this.#contexts.get(win);
    if (!items) {
      items = new Map();
      this.#contexts.set(win, items);
    }
    return items;
  }

  static #chipView(chipId, item) {
    const { kind, tabId, url, title, chars, truncated } = item;
    return { chipId, kind, tabId, url, title, host: URL.parse(url)?.host ?? "", chars, truncated, blockChars: pageBlockChars(item) };
  }

  /** "Incluir esta página": read the visible text of the tab the user named, now, and keep it for the
      next message (the size shown is what goes: Q4). A later Send sends this copy, not the page then. */
  async assistantInclude(source, win) {
    this.#userWindow(win);
    if (await this.workspaceAgent()) {
      fail("ai-workspace");
    }
    if (source?.kind !== "page") {
      fail("bad-request");
    }
    const browser = this.#includedBrowser(source, win);
    // The engine's own extractor (visible text, as reader-like features use); no script in the page.
    const extracted = await browser.browsingContext.currentWindowGlobal
      .getActor("PageExtractor")
      .getText({ sufficientLength: MAX_PAGE_CHARS + 1 });
    this.#includedBrowser(source, win); // it navigated while being read: refuse rather than keep another page
    const [text, truncated] = cutCodePoints(String(extracted?.text ?? ""), MAX_PAGE_CHARS);
    const items = this.#contextOf(win);
    for (const [id, item] of items) {
      if (item.kind === "page") {
        items.delete(id); // one page per message: the new one replaces it
      }
    }
    const chipId = Services.uuid.generateUUID().toString().slice(1, -1);
    const item = { kind: "page", tabId: source.tabId, url: source.url, title: browser.contentTitle || source.url, text, chars: codePoints(text), truncated };
    items.set(chipId, item);
    return AI.#chipView(chipId, item);
  }

  assistantRemove(chipId, win) {
    this.#contextOf(this.#userWindow(win)).delete(String(chipId));
  }

  /** The items waiting for this window's next message (the panel shows them again when it reopens). */
  assistantChips(win) {
    return [...this.#contextOf(this.#userWindow(win))].map(([id, item]) => AI.#chipView(id, item));
  }

  /** The tools' request for an Ask: the included items (each page only while its tab still shows that
      address) and what the panel showed. The items leave the window's context: consent is per message. */
  #askRequest(question, options, win) {
    const { chips = [], expected = null } = options ?? {};
    if (!expected || typeof expected.recipient !== "string" || !Number.isInteger(expected.chars)) {
      fail("bad-request");
    }
    const items = this.#contextOf(win);
    const used = (chips ?? []).map(id => items.get(String(id)) ?? fail("page-changed"));
    for (const id of chips ?? []) {
      items.delete(String(id)); // consent is per message: the items go with this one only
    }
    for (const item of used) {
      this.#includedBrowser(item, win); // that tab went elsewhere or closed: nothing is sent
    }
    const page = used.find(item => item.kind === "page");
    const sent = page ? { url: page.url, title: page.title, text: page.text } : null;
    return { op: "ask", question: String(question), page: sent, expected };
  }

  /** Ask, answered in one piece. `chips`: the items the user included in this message. `expected`: where
      the panel said it goes and its size; the tools refuse the request if either is no longer true. The
      selected tab at Send is never read. The panel streams instead (assistantStart). */
  async assistantAsk(question, options, win) {
    this.#userWindow(win);
    if (await this.workspaceAgent()) {
      fail("ai-workspace");
    }
    return this.#assistant(this.#askRequest(question, options, win), 180000);
  }

  // -- runs in stream mode (UX5-C2) ----------------------------------------------------------------

  subscribeAssistant(listener) {
    this.#runListeners.add(listener);
    return () => this.#runListeners.delete(listener);
  }

  #emit(run, event) {
    for (const listener of this.#runListeners) {
      try {
        listener(run.win, event);
      } catch (e) {
        console.error(e);
      }
    }
  }

  /** Start an Ask or a Task whose events reach this window's panel (onAssistantEvent): start, sending,
      delta, step, approval, then exactly one done or error. `owner`: the page that started it; an Ask
      ends with it (Q18), a Task goes on and the panel finds it again with assistantRuns. */
  async assistantStart(kind, details, win, owner = null) {
    this.#userWindow(win);
    if (await this.workspaceAgent()) {
      fail("ai-workspace");
    }
    let request;
    if (kind === "ask") {
      request = this.#askRequest(details?.question ?? "", details, win);
    } else if (kind === "task") {
      request = { op: "task", task: String(details?.task ?? ""), expected: details?.expected ?? null };
    } else {
      fail("bad-request");
    }
    request.profile = Services.dirsvc.get("ProfD", Ci.nsIFile).path;
    const runId = Services.uuid.generateUUID().toString().slice(1, -1);
    const run = { win, kind, owner, state: "running", sent: false, steps: [], cutBy: null };
    this.#runs.set(runId, run);
    run.handle = lazy.callToolStream(["ai", "assistant"], request, {
      onEvent: event => this.#onRunEvent(runId, run, event),
      // The idle limit can be shortened for tests (never under 1 s); nothing else reads this pref.
      idleMs: Math.max(1000, Services.prefs.getIntPref(IDLE_PREF, IDLE_MS)),
      totalMs: kind === "ask" ? ASK_TOTAL_MS : TASK_TOTAL_MS,
    });
    run.handle.result.then(
      terminal => this.#finishRun(runId, run, terminal),
      e => this.#finishRun(runId, run, { type: "error", code: e?.code ?? "helper-failed" })
    );
    win.addEventListener("unload", () => this.#cancelRun(run), { once: true }); // the window closed
    this.#watchRuns();
    return { runId };
  }

  #onRunEvent(runId, run, event) {
    if (event.type === "sending") {
      run.sent = true;
    } else if (event.type === "step" && event.state !== "started") {
      run.steps.push({ tool: event.tool, error: event.state !== "ok" });
    } else if (event.type === "approval") {
      // Someone has to answer: the idle limit waits until the request expires (Q15).
      const expires = Date.parse(event.expires);
      if (Number.isFinite(expires)) {
        run.handle.holdIdle(expires + 10000);
      }
    }
    this.#emit(run, { ...event, runId });
  }

  #finishRun(runId, run, terminal) {
    this.#runs.delete(runId);
    run.state = "done";
    let event = { ...terminal, runId };
    if (run.cancelling && terminal.type === "error" && terminal.code === "helper-failed") {
      // Cancelled and ended hard (SIGKILL) before saying so: it may have reached the provider.
      event = { type: "done", runId, cancelled: true, sent: true, steps: run.steps };
    } else if (run.kind === "task" && terminal.type === "error" && terminal.code === "helper-failed") {
      event = { ...event, code: "task-unfinished" }; // the run may have acted already
    }
    if (run.cutBy) {
      event.cutBy = run.cutBy; // the emergency stop, a pause or a revocation ended it
    }
    this.#emit(run, event);
    if (!this.#runs.size) {
      this.#runWatch?.cancel();
      this.#runWatch = null;
    }
  }

  #cancelRun(run, cutBy = null) {
    if (run.state !== "running") {
      return;
    }
    run.state = "cancelling";
    run.cancelling = true;
    run.cutBy ??= cutBy;
    run.handle.cancel(run.kind === "ask" ? ASK_GRACE_MS : TASK_GRACE_MS);
  }

  /** "Parar" or Esc in the panel: only for a run of the calling window. */
  assistantCancel(runId, win) {
    const run = this.#runs.get(String(runId));
    if (run && run.win !== win) {
      fail("bad-request");
    }
    if (run) {
      this.#cancelRun(run);
    }
    return { state: run ? run.state : "done" };
  }

  /** This window's runs (a Task goes on when the panel closes; the panel shows it again). */
  assistantRuns(win) {
    this.#userWindow(win);
    return [...this.#runs]
      .filter(([, run]) => run.win === win)
      .map(([runId, run]) => ({ runId, kind: run.kind, state: run.state, sent: run.sent, steps: run.steps }));
  }

  /** The page that started an Ask went away (the panel closed): its Asks stop (Q18). */
  assistantOwnerClosed(owner) {
    for (const run of this.#runs.values()) {
      if (run.owner === owner && run.kind === "ask") {
        this.#cancelRun(run);
      }
    }
  }

  /** While runs go on, the emergency stop, a pause or a revocation of the assistant cuts them at once
      (Q19, D-UX5): two file reads every RUN_WATCH_MS, no process. */
  #watchRuns() {
    if (this.#runWatch) {
      return;
    }
    this.#runWatch = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#runWatch.initWithCallback(() => this.#checkRuns().catch(() => {}), RUN_WATCH_MS, Ci.nsITimer.TYPE_REPEATING_SLACK);
  }

  async #checkRuns() {
    if (!this.#runs.size) {
      return;
    }
    const dir = PathUtils.join(lazy.stateDir(), "ai");
    let cutBy = null;
    if (await IOUtils.exists(PathUtils.join(dir, "STOP"))) {
      cutBy = "emergency-stop";
    } else {
      const config = await IOUtils.readJSON(PathUtils.join(dir, "assistant.json")).catch(() => null);
      const registry = await IOUtils.readJSON(PathUtils.join(dir, "agents.json")).catch(() => null);
      const agent = config?.agent ? registry?.agents?.[config.agent] : null;
      if (config?.agent && registry && (!agent || agent.revoked)) {
        cutBy = "assistant-revoked";
      } else if (agent?.paused) {
        cutBy = "assistant-paused";
      }
    }
    if (cutBy) {
      for (const run of this.#runs.values()) {
        this.#cancelRun(run, cutBy);
      }
    }
  }

  /** A task in the assistant's AI Workspace, under its agent permissions; never from a private window. */
  async assistantTask(task, expected, win) {
    this.#userWindow(win);
    try {
      return await this.#assistant({ op: "task", task: String(task), expected: expected ?? null }, 600000);
    } catch (e) {
      if (e?.code === "helper-failed") {
        fail("task-unfinished"); // no answer in time (or the tools ended): the run may have acted already
      }
      throw e;
    }
  }

  /** Where the agent driving this window acts: its AI Workspace, or one of the user's own profiles (by name). */
  workspaceTarget() {
    // Without the pref (an older launcher), "agent:pid" is only ever written into one of the user's profiles.
    const legacy = Services.prefs.getStringPref(WORKSPACE_PREF, "").includes(":") ? "profile" : "workspace";
    const kind = Services.prefs.getStringPref(TARGET_PREF, legacy) === "profile" ? "profile" : "workspace";
    return { kind, profile: kind === "profile" ? Services.prefs.getStringPref(TARGET_LABEL_PREF, "") : null };
  }

  /** Synchronous warning snapshot so a slow identity lookup cannot delay a raw warning. */
  windowWarning() {
    const bar = this.#bar;
    return bar ? { id: bar.agent, target: { ...bar.target }, raw: bar.raw, paused: bar.paused, failed: bar.failed } : null;
  }

  /** Read-only Farol snapshot. Raw is the same session latch as the non-dismissible
      bar, never inferred from a CSS attribute. Failure is explicit: consumers keep
      the last identity/level and warning instead of interpreting it as an idle window. */
  async windowState() {
    const warning = this.windowWarning();
    const id = warning?.id || await this.workspaceAgent();
    this.#watchAgentFiles(Boolean(id));
    if (!id) {
      return null;
    }
    const state = {
      id, target: warning?.target ?? this.workspaceTarget(), raw: warning?.raw ?? false,
      paused: warning?.paused ?? false, failed: warning?.failed ?? false,
    };
    try {
      const overview = await this.#bandOverview();
      const agent = overview.agents.find(a => a.id === id);
      return { ...state, name: agent?.name ?? id, autonomy: agent?.autonomy ?? null,
        paused: agent ? Boolean(agent.paused) : state.paused, revoked: Boolean(agent?.revoked),
        stopped: overview.stopped, unavailable: !agent };
    } catch {
      return { ...state, name: id, autonomy: null, unavailable: true };
    }
  }

  /** In a window an agent drives: say plainly who drives it, at which level and where, in every browser
      window, in a bar that cannot be closed, with "Parar agente". The texts come from the Shell's locales:
      text (normal), rawText, pausedText, failedText, stopLabel. */
  async markWorkspace(texts = {}) {
    const agent = await this.workspaceAgent();
    if (!agent) {
      return;
    }
    const target = this.workspaceTarget();
    const previous = this.#bar;
    this.#bar = { agent, target, texts: { ...texts }, raw: previous?.raw ?? false, paused: false, failed: false };
    this.#renderAll();
    if (!this.#observing) {
      this.#observing = true;
      Services.obs.addObserver(subject => this.#render(subject), "browser-delayed-startup-finished");
    }
    if (target.kind === "workspace") {
      this.#watchRaw(); // raw automation is only ever offered for an AI Workspace
    }
  }

  #renderAll() {
    Services.obs.notifyObservers(null, "nulavio-ai-window-changed");
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      this.#render(win);
    }
  }

  #render(win) {
    const next = (this.#renders.get(win) ?? Promise.resolve()).then(() => this.#paint(win)).catch(console.error);
    this.#renders.set(win, next);
    return next;
  }

  async #paint(win) {
    const bar = this.#bar;
    const box = win?.gNotificationBox;
    if (!bar || !box || win.closed) {
      return;
    }
    const root = win.document.documentElement;
    const tokens = new Set((root.getAttribute(STATE_ATTR) ?? "").split(/\s+/).filter(Boolean));
    tokens.add("ai");
    tokens[bar.target.kind === "profile" ? "add" : "delete"]("ai-profile");
    tokens[bar.raw ? "add" : "delete"]("raw");
    root.setAttribute(STATE_ATTR, [...tokens].join(" "));

    const { texts } = bar;
    const label = bar.failed ? texts.failedText : bar.paused ? texts.pausedText : bar.raw ? texts.rawText : texts.text;
    for (const value of [BAR, RAW_BAR]) {
      const old = box.getNotificationWithValue(value);
      if (old) {
        box.removeNotification(old, true);
      }
    }
    const priority = bar.raw
      ? box.PRIORITY_CRITICAL_HIGH
      : bar.target.kind === "profile"
        ? box.PRIORITY_WARNING_HIGH // the user's own profile, with their signed-in sessions
        : box.PRIORITY_INFO_HIGH;
    const buttons = bar.paused ? [] : [{ label: texts.stopLabel, callback: () => (this.#stopAgent(), true) }];
    // dismissable = false: closing the bar would leave the window looking like the user's own.
    await box.appendNotification(bar.raw ? RAW_BAR : BAR, { label: String(label ?? ""), priority }, buttons, false, false);
  }

  /** "Parar agente": pauses this window's agent (resume only from the user's own Settings). Clicking it can only
      stop the agent, so it is safe in the window the agent drives. */
  async #stopAgent() {
    const bar = this.#bar;
    if (!bar || bar.paused) {
      return;
    }
    try {
      await api({ op: "pause", agent: agentId(bar.agent), paused: true });
      bar.paused = true;
      bar.failed = false;
    } catch (e) {
      console.error(e);
      bar.failed = true;
    }
    this.#renderAll();
  }

  /** Raw automation: the bridge writes RAW_MARKER into this profile when it hands the endpoint over. Once seen
      (for this agent, from a live bridge), the window stays in that state until it closes. */
  #watchRaw() {
    if (this.#rawTimer || this.#bar?.raw) {
      return;
    }
    const file = PathUtils.join(Services.dirsvc.get("ProfD", Ci.nsIFile).path, RAW_MARKER);
    this.#rawTimer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#rawTimer.initWithCallback(() => this.#checkRaw(file).catch(console.error), RAW_POLL_MS, Ci.nsITimer.TYPE_REPEATING_SLACK);
  }

  async #checkRaw(file) {
    const bar = this.#bar;
    if (!bar || bar.raw || !(await IOUtils.exists(file))) {
      return;
    }
    let marker = null;
    try {
      marker = await IOUtils.readJSON(file);
    } catch {
      return; // being written
    }
    const pid = String(marker?.pid ?? "");
    if (marker?.agent !== bar.agent || !/^\d+$/.test(pid) || !(await IOUtils.exists(`/proc/${pid}`))) {
      return; // another agent's, or left by a bridge that is gone
    }
    bar.raw = true; // latched: removing the file does not take the state away
    this.#rawTimer?.cancel();
    this.#rawTimer = null;
    this.#renderAll();
  }
}

export const NulavioAI = new AI();
