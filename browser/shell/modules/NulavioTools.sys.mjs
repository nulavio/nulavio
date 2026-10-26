/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The Nulavio tools shipped next to the engine (nulavio-tools/bin/nulavio).
   The Shell asks them for things the browser should not do itself (Vault
   cryptography, the AI Bridge registry): an argument list without secrets,
   one JSON request on stdin, one JSON answer on stdout. Never a shell. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  Subprocess: "resource://gre/modules/Subprocess.sys.mjs",
});

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
