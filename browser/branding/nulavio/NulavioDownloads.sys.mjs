/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow E inside the engine's downloads panel (patch 0007): a finished
   download that can run programs is not opened from the panel. Its default
   action shows it in its folder, "Open" and "Always open similar files" are
   unavailable, and its status line says why. The Shell's warning page
   (browser/shell/warning/) still explains the risk when it completes.

   The list is the Shell's (browser/shell/lib/risky.js), copied here because
   this module loads before the Shell; tests/unit/test_shell.py keeps the two
   equal. Matching is by file name only. */

const RISKY_EXTENSIONS = Object.freeze([
  ".appimage",
  ".sh",
  ".bash",
  ".run",
  ".desktop",
  ".deb",
  ".rpm",
  ".flatpak",
  ".flatpakref",
  ".snap",
  ".jar",
]);

const LABELS = {
  en: "Program file: open it only from its folder, if you trust where it came from",
  pt: "Arquivo de programa: abra só pela pasta, se confiar na origem",
};

export const NulavioDownloads = {
  isProgram(download) {
    try {
      const name = String(download?.target?.path ?? "").split("/").pop().toLowerCase();
      return RISKY_EXTENSIONS.some(ext => name.endsWith(ext) && name.length > ext.length);
    } catch (e) {
      console.error("Nulavio downloads", e);
      return false;
    }
  },

  statusLabel() {
    return Services.locale.appLocaleAsBCP47.startsWith("pt") ? LABELS.pt : LABELS.en;
  },
};
