/* Settings > Atalhos (UX6, D7): Nulavio's commands with their current keys. "Mudar…" opens the
   engine's extension shortcuts view, which checks the key against the system, the browser's own
   keys and other extensions; "Restaurar" puts the default back. Nothing is captured here. */

import { t } from "../lib/i18n.js";
import { keyElements } from "../lib/keys.js";
import { announce, errorText, h, rerender } from "../lib/ui.js";

export async function setUpShortcuts() {
  const commands = browser.commands;
  if (!commands?.getAll) {
    return;
  }
  const section = document.getElementById("shortcuts");
  const list = document.getElementById("shortcut-list");
  const defaults = browser.runtime.getManifest().commands ?? {};
  section.hidden = false;

  const row = command => {
    const name = command.description || command.name;
    const fallback = defaults[command.name]?.suggested_key?.default ?? "";
    const change = h("button", {
      class: "button button--secondary",
      type: "button",
      text: t("shortcutsChange"),
      "aria-label": t("shortcutsChangeName", [name]),
      "data-focus-key": `change-${command.name}`,
    });
    change.addEventListener("click", () => commands.openShortcutSettings().catch(e => announce(errorText(e), "error")));
    const reset = command.shortcut !== fallback
      ? h("button", {
          class: "button button--quiet",
          type: "button",
          text: t("shortcutsReset"),
          "aria-label": t("shortcutsResetName", [name]),
          "data-focus-key": `reset-${command.name}`,
        })
      : null;
    reset?.addEventListener("click", async () => {
      try {
        await commands.reset(command.name);
        // Firefox 159's reset fires no commands.onChanged: the background renames the profile button.
        browser.runtime.sendMessage({ type: "commands-reset" }).catch(() => {});
        // "Restaurar" goes away with the default key: the keyboard stays in the row, on "Mudar…".
        change.focus();
        await render();
        const still = list.querySelector(`[data-focus-key="change-${CSS.escape(command.name)}"]`);
        still?.focus();
        announce(t("shortcutsResetDone", [fallback || t("shortcutsNone")]), "ok", { control: still ?? undefined });
      } catch (e) {
        announce(errorText(e), "error");
      }
    });
    return h(
      "li",
      { class: "row", dataset: { command: command.name } },
      h(
        "div",
        { class: "row__main" },
        h("p", { class: "row__title", text: name }),
        h("p", { class: "row__meta keys-line" }, ...(command.shortcut ? keyElements(command.shortcut) : [t("shortcutsNone")]))
      ),
      h("div", { class: "row__end" }, change, reset)
    );
  };
  const render = async () => {
    const all = await commands.getAll();
    rerender(list, () => all.map(row));
  };
  document.getElementById("shortcuts-browser").addEventListener("click", () =>
    browser.nulavioPersonalise.openKeyboardShortcuts().catch(e => announce(errorText(e), "error"))
  );
  // A key changed in the engine's view shows when the person comes back here.
  window.addEventListener("focus", () => render().catch(() => {}));
  await render();
}
