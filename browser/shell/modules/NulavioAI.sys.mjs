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

  add({ name, client, autonomy, domains = [], disposable = false, acceptFullControl = false }) {
    return api({ op: "add", name, client, autonomy, domains, disposable, acceptFullControl });
  }

  change(id, op, details = {}) {
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
    return api({ ...details, op, agent: agentId(id) });
  }

  /** The connect wizard: which agents are installed, the exact command, then run it after approval. */
  detect() {
    return api({ op: "detect" });
  }

  plan(id, client) {
    return api({ op: "plan", agent: agentId(id), client });
  }

  install(id, client, replace = false) {
    return api({ op: "install", agent: agentId(id), client, replace: Boolean(replace) });
  }

  setStopped(stopped) {
    return api({ op: "stop", stopped: Boolean(stopped) });
  }

  activity(limit = 100, agent = null) {
    return api({ op: "audit", limit, agent: agent ? agentId(agent) : null });
  }

  clearActivity() {
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

  /** Ask. `page` is null, or the {tabId, url} the user included in this message: that tab's visible
      text goes along only while it still shows that address. The selected tab at Send is never read. */
  async assistantAsk(question, page, win) {
    this.#userWindow(win);
    if (await this.workspaceAgent()) {
      fail("ai-workspace");
    }
    let sent = null;
    if (page) {
      const browser = this.#includedBrowser(page, win);
      // The engine's own extractor (visible text, as reader-like features use); no script in the page.
      const extracted = await browser.browsingContext.currentWindowGlobal.getActor("PageExtractor").getText({});
      this.#includedBrowser(page, win); // it navigated while being read: refuse rather than send another page
      sent = { url: browser.currentURI.spec, title: browser.contentTitle, text: String(extracted?.text ?? "") };
    }
    return this.#assistant({ op: "ask", question: String(question), page: sent }, 180000);
  }

  /** A task in the assistant's AI Workspace, under its agent permissions; never from a private window. */
  async assistantTask(task, win) {
    this.#userWindow(win);
    try {
      return await this.#assistant({ op: "task", task: String(task) }, 600000);
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
