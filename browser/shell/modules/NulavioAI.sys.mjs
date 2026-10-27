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
   requests, because the agent drives that window; it shows who does. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  stateDir: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
});

const SHELL_ID = "shell@nulavio.net";
const WORKSPACE_PREF = "nulavio.ai.workspace";
const POLL_MS = 1500;
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

class AI {
  #timer = null;
  #shown = new Set();

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
    const allowed = ["autonomy", "grant", "clear-grant", "domains", "profiles", "routes", "pause", "revoke", "remove", "rotate-token"];
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
    win.openTrustedLinkIn(policy.getURL(page), "tab");
    win.focus();
  }

  /** In an AI Workspace: say plainly who drives this window, in every browser window. */
  // -- Nulavio Assistant (A12): a model the user chose, through the Nulavio tools ------------------
  // The tools hold the API key (system keyring) and talk to the provider; the browser sends them
  // the question and, only when the user ticked it, the visible text of the current page.

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

  assistantState() {
    return this.#assistant({ op: "state" });
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

  /** The page the user would share: the selected tab of `win` (address and title only). */
  assistantPage(win) {
    const browser = win?.gBrowser?.selectedBrowser;
    const url = browser?.currentURI?.spec ?? "";
    return /^https?:/.test(url) ? { url, title: browser.contentTitle || url } : null;
  }

  /** Ask; `includePage`: the user ticked "include this page", so its visible text goes along. */
  async assistantAsk(question, includePage, win) {
    let page = null;
    if (includePage) {
      const browser = win?.gBrowser?.selectedBrowser;
      if (!this.assistantPage(win)) {
        fail("no-page");
      }
      // The engine's own extractor (visible text, as reader-like features use); no script in the page.
      const extracted = await browser.browsingContext.currentWindowGlobal.getActor("PageExtractor").getText({});
      page = { url: browser.currentURI.spec, title: browser.contentTitle, text: String(extracted?.text ?? "") };
    }
    return this.#assistant({ op: "ask", question: String(question), page }, 180000);
  }

  /** A task in the assistant's AI Workspace, under its agent permissions. */
  assistantTask(task) {
    return this.#assistant({ op: "task", task: String(task) }, 600000);
  }

  async markWorkspace(text) {
    if (!(await this.workspaceAgent())) {
      return;
    }
    const mark = win => {
      const box = win.gNotificationBox;
      if (!box || box.getNotificationWithValue("nulavio-ai-workspace")) {
        return;
      }
      box.appendNotification("nulavio-ai-workspace", { label: text, priority: box.PRIORITY_INFO_HIGH }, []);
    };
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      mark(win);
    }
    Services.obs.addObserver(subject => mark(subject), "browser-delayed-startup-finished");
  }
}

export const NulavioAI = new AI();
