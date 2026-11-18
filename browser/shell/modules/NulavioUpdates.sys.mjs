/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio's automatic updates (#241), from the browser's side. The packages carry a timer that updates
   the nulavio package and does nothing until /etc/nulavio/automatic-updates exists
   (packaging/linux/updates/). This module reads whether that file is there (no privileges) and asks
   pkexec to run the packages' helper with "on" or "off": polkit then asks for the administrator's
   password. It never runs anything as root by itself, never contacts a server, and runs nothing
   unless the person asked for it. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  Subprocess: "resource://gre/modules/Subprocess.sys.mjs",
});

export const FLAG = "/etc/nulavio/automatic-updates";
export const HELPER = "/usr/libexec/nulavio/automatic-updates";
const PKEXEC = "/usr/bin/pkexec";
// Where the RPM (lib64) and the .deb (lib) install the engine: only those installs carry the timer.
const PACKAGED = Object.freeze(["/usr/lib64/nulavio", "/usr/lib/nulavio"]);

export class UpdatesError extends Error {
  constructor(code) {
    super(code);
    this.name = "UpdatesError";
    this.code = code;
  }
}

function fail(code) {
  throw new UpdatesError(code);
}

async function drain(pipe) {
  let text = "";
  let chunk;
  while ((chunk = await pipe.readString())) {
    text += chunk;
  }
  return text;
}

export const NulavioUpdates = {
  /**
   * `available`: this browser was installed from Nulavio's RPM or .deb, which carry the timer and the helper.
   * `on`: the timer's file is there. `canAsk`: pkexec is there to ask for the administrator's password.
   * `command`: what to run in a terminal instead, when it is not.
   */
  async state() {
    const gre = Services.dirsvc.get("GreD", Ci.nsIFile).path;
    const [helper, pkexec, on] = await Promise.all([IOUtils.exists(HELPER), IOUtils.exists(PKEXEC), IOUtils.exists(FLAG)]);
    const available = PACKAGED.includes(gre) && helper;
    return { available, on: available && on, canAsk: available && pkexec, command: `sudo ${HELPER} on` };
  },

  /**
   * Turn automatic updates on or off through pkexec (the administrator's password, every time). Errors:
   * `not-packaged`, `no-polkit` (pkexec is missing, or no polkit agent could ask: the command is the way),
   * `cancelled` (the person closed the password prompt), `failed`. Resolves to the new state.
   */
  async set(on) {
    const before = await this.state();
    if (!before.available) {
      fail("not-packaged");
    }
    if (!before.canAsk) {
      fail("no-polkit");
    }
    const proc = await lazy.Subprocess.call({
      command: PKEXEC,
      arguments: [HELPER, on ? "on" : "off"],
      stderr: "pipe",
    });
    await proc.stdin.close();
    await Promise.all([drain(proc.stdout), drain(proc.stderr)]);
    const { exitCode } = await proc.wait();
    // pkexec: 126 when the person dismissed the prompt or the password was wrong, 127 when it could not
    // ask at all (no polkit agent in the session) or was not allowed.
    if (exitCode === 126) {
      fail("cancelled");
    }
    if (exitCode === 127) {
      fail("no-polkit");
    }
    const after = await this.state();
    if (exitCode !== 0 || after.on !== Boolean(on)) {
      fail("failed");
    }
    return after;
  },
};
