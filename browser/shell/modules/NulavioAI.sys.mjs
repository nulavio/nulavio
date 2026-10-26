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

  workspaceAgent() {
    return Services.prefs.getStringPref(WORKSPACE_PREF, "");
  }

  overview() {
    return api({ op: "overview" });
  }

  add({ name, client, autonomy, domains = [], disposable = false, acceptFullControl = false }) {
    return api({ op: "add", name, client, autonomy, domains, disposable, acceptFullControl });
  }

  change(id, op, details = {}) {
    const allowed = ["autonomy", "grant", "clear-grant", "domains", "pause", "revoke", "remove", "rotate-token"];
    if (!allowed.includes(op)) {
      fail("bad-request");
    }
    return api({ ...details, op, agent: agentId(id) });
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
    if (this.workspaceAgent()) {
      fail("workspace"); // never from the window an agent drives
    }
    if (!ID_RE.test(String(id)) || !ANSWERS.has(answer)) {
      fail("bad-request");
    }
    return api({ op: "answer", id, answer });
  }

  /** Watch for permission requests (idempotent). Not in an AI Workspace. */
  watch() {
    if (this.#timer || this.workspaceAgent()) {
      return;
    }
    this.#timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#timer.initWithCallback(() => this.#poll().catch(console.error), POLL_MS, Ci.nsITimer.TYPE_REPEATING_SLACK);
  }

  async #poll() {
    if (this.workspaceAgent()) {
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
  async markWorkspace(text) {
    if (!this.workspaceAgent()) {
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
