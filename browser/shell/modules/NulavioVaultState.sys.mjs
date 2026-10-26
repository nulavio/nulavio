/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Is a profile encrypted, and is it locked? (ADR 0006, S5)

   An encrypted profile directory P has its Vault beside it, in P.vault/,
   and is a gocryptfs mount point. While locked, P is an empty read-only
   directory; once unlocked, the volume shows .nulavio-vault/state.json.
   The browser only reads these two facts: it never holds keys, and an
   unlock always goes through the user (the launcher today, the Shell UI in S6). */

export const PLAIN = "plain";
export const LOCKED = "locked";
export const UNLOCKED = "unlocked";

export async function profileLockState(path) {
  if (!path) {
    return PLAIN;
  }
  const vault = PathUtils.join(PathUtils.parent(path), `${PathUtils.filename(path)}.vault`, "vault.json");
  if (!(await IOUtils.exists(vault))) {
    return PLAIN;
  }
  const state = PathUtils.join(path, ".nulavio-vault", "state.json");
  return (await IOUtils.exists(state)) ? UNLOCKED : LOCKED;
}
