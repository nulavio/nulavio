/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The Nulavio tools shipped next to the engine (nulavio-tools/bin/nulavio).
   The Shell asks them for things the browser should not do itself (Vault
   cryptography, the AI Bridge registry): an argument list without secrets,
   one JSON request on stdin, one JSON answer on stdout. Never a shell.

   callToolStream (the assistant, UX5-C1/C2): the same process and arguments, a request with
   "stream": true, and one JSON event per line on stdout until exactly one terminal line
   ({type: "done"} or {type: "error"}). stdin stays open until then; closing it, or SIGTERM
   (cancel), asks the tools to stop, and they answer done {cancelled: true, sent}. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  Subprocess: "resource://gre/modules/Subprocess.sys.mjs",
  setTimeout: "resource://gre/modules/Timer.sys.mjs",
  clearTimeout: "resource://gre/modules/Timer.sys.mjs",
});
const setTimeout = (fn, ms) => lazy.setTimeout(fn, ms);
const clearTimeout = id => lazy.clearTimeout(id);

export class ToolError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "ToolError";
    this.code = code;
  }
}

export function toolPath() {
  const gre = Services.dirsvc.get("GreD", Ci.nsIFile).path;
  return PathUtils.join(gre, "nulavio-tools", "bin", "nulavio");
}

/** Run `nulavio <args>` with `request` as JSON on stdin; resolves to the JSON answer or throws its error code. */
export async function callTool(args, request, timeoutMs = 90000) {
  const tool = toolPath();
  if (!(await IOUtils.exists(tool))) {
    throw new ToolError("tools-missing");
  }
  const proc = await lazy.Subprocess.call({ command: tool, arguments: args, stderr: "pipe" });
  const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  timer.initWithCallback(() => proc.kill(), timeoutMs, Ci.nsITimer.TYPE_ONE_SHOT);
  try {
    await proc.stdin.write(JSON.stringify(request));
    await proc.stdin.close();
    const drain = async pipe => {
      let text = "";
      let chunk;
      while ((chunk = await pipe.readString())) {
        text += chunk;
      }
      return text;
    };
    const [stdout] = await Promise.all([drain(proc.stdout), drain(proc.stderr)]);
    await proc.wait();
    let answer;
    try {
      answer = JSON.parse(stdout);
    } catch {
      throw new ToolError("helper-failed");
    }
    if (answer?.error) {
      throw new ToolError(String(answer.error));
    }
    return answer;
  } finally {
    timer.cancel();
  }
}

const MAX_LINE = 1024 * 1024;

/** Run `nulavio <args>` in stream mode. `onEvent(event)` gets every line before the terminal one;
    `result` resolves to the terminal line ({type: "done"|"error", …}) or rejects with a ToolError:
    helper-failed (no terminal line, or a line that is not JSON or is too long: fail closed),
    timeout (no line for `idleMs`, or longer than `totalMs` in all). `cancel(graceMs)` sends SIGTERM,
    then SIGKILL after `graceMs`; `holdIdle(untilMs)` lets the idle timer wait until then (a person
    answering a permission request). */
export function callToolStream(args, request, { onEvent = () => {}, idleMs = 150000, totalMs = 600000 } = {}) {
  let proc = null;
  let finished = false;
  let cancelGrace = null;
  let idleTimer = null;
  let totalTimer = null;
  let holdUntil = 0;
  let fail;
  const failed = new Promise((_resolve, reject) => {
    fail = code => {
      if (!finished) {
        finished = true;
        reject(new ToolError(code));
        proc?.kill(0);
      }
    };
  });
  const armIdle = () => {
    clearTimeout(idleTimer);
    const wait = Math.max(idleMs, holdUntil - Date.now());
    idleTimer = setTimeout(() => (Date.now() < holdUntil ? armIdle() : fail("timeout")), wait);
  };
  const run = (async () => {
    const tool = toolPath();
    if (!(await IOUtils.exists(tool))) {
      throw new ToolError("tools-missing");
    }
    proc = await lazy.Subprocess.call({ command: tool, arguments: args, stderr: "pipe" });
    if (cancelGrace !== null) {
      proc.kill(cancelGrace); // cancelled while the process was starting
    }
    totalTimer = setTimeout(() => fail("timeout"), totalMs);
    armIdle();
    (async () => {
      while (await proc.stderr.readString()) {
        // drained, never shown: the tools' diagnostics are not for the page
      }
    })().catch(() => {});
    await proc.stdin.write(JSON.stringify({ ...request, stream: true }) + "\n");
    let rest = "";
    let chunk;
    while ((chunk = await proc.stdout.readString())) {
      rest += chunk;
      let at;
      while ((at = rest.indexOf("\n")) !== -1) {
        const line = rest.slice(0, at);
        rest = rest.slice(at + 1);
        let event;
        if (line.length > MAX_LINE) {
          throw new ToolError("helper-failed");
        }
        try {
          event = JSON.parse(line);
        } catch {
          throw new ToolError("helper-failed");
        }
        if (typeof event?.type !== "string") {
          throw new ToolError("helper-failed");
        }
        armIdle();
        if (event.type === "done" || event.type === "error") {
          await proc.stdin.close().catch(() => {});
          await proc.wait();
          return event;
        }
        onEvent(event);
      }
      if (rest.length > MAX_LINE) {
        throw new ToolError("helper-failed");
      }
    }
    await proc.wait();
    throw new ToolError("helper-failed"); // ended without a terminal line (killed, or crashed)
  })();
  const result = Promise.race([run, failed]).then(
    event => {
      finished = true;
      return event;
    },
    e => {
      finished = true;
      proc?.kill(0);
      throw e?.code ? e : new ToolError("helper-failed");
    }
  );
  result
    .finally(() => {
      clearTimeout(idleTimer);
      clearTimeout(totalTimer);
    })
    .catch(() => {});
  return {
    result,
    cancel(graceMs = 2000) {
      if (finished) {
        return;
      }
      cancelGrace = graceMs;
      proc?.kill(graceMs);
    },
    holdIdle(untilMs) {
      holdUntil = Math.max(holdUntil, untilMs);
      armIdle();
    },
  };
}

/** Nulavio's state directory, as the launcher computes it (NULAVIO_HOME, else XDG_STATE_HOME, else ~/.local/state). */
export function stateDir() {
  const home = Services.env.get("NULAVIO_HOME");
  if (home && home.startsWith("/")) {
    return PathUtils.join(home, "state");
  }
  const xdg = Services.env.get("XDG_STATE_HOME");
  const base = xdg && xdg.startsWith("/") ? xdg : PathUtils.join(Services.dirsvc.get("Home", Ci.nsIFile).path, ".local", "state");
  return PathUtils.join(base, "nulavio");
}
