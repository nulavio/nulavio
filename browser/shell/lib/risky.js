/* Download types that can run programs with the user's permissions.
   Source of truth for flow E (docs/brand/ux-flows.md). Matching is by file
   name only: the extension cannot look inside archives. */

export const RISKY_EXTENSIONS = Object.freeze([
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

export function isRiskyFilename(path) {
  if (typeof path !== "string" || !path) {
    return false;
  }
  const name = path.split("/").pop().toLowerCase();
  return RISKY_EXTENSIONS.some(ext => name.endsWith(ext) && name.length > ext.length);
}
