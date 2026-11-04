/* Nulavio's keyboard commands as the engine has them now (UX6): read from commands.getAll(), so a
   key the person changed in the engine's extension shortcuts view shows everywhere it is named. */

import { h } from "./ui.js";

/** {command name: shortcut} ("" when the command has no key). */
export async function nulavioKeys() {
  const out = {};
  for (const command of (await browser.commands?.getAll?.().catch(() => [])) ?? []) {
    out[command.name] = command.shortcut ?? "";
  }
  return out;
}

/** "Ctrl+Alt+F" as <kbd> elements; nothing for an empty shortcut. */
export function keyElements(shortcut) {
  return shortcut ? shortcut.split("+").flatMap((part, i) => [i ? " " : null, h("kbd", { text: part })]).filter(Boolean) : [];
}
