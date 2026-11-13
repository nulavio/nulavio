/* One settings page (ADR 0008): every "Configurações" link of a Shell page opens about:preferences
   at the pane that holds what it names. A page cannot link to about:preferences itself, so the
   link keeps an address of the old page as its href (what opens if the bridge is missing) and
   the click goes through the Shell's own API. */

/** Open the settings page at `where` (a pane, or a section of the old page); `replace` uses this tab. */
export async function openSettings(where = "", { replace = false } = {}) {
  await browser.nulavioPersonalise.openSettings(where, replace);
}

/** Wire every `<a data-settings="…">` under `root`: "" is the page's first pane. */
export function wireSettingsLinks(root = document) {
  if (!browser.nulavioPersonalise?.openSettings) {
    return;
  }
  for (const link of root.querySelectorAll("a[data-settings]")) {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
        return; // a new tab or window was asked for: the plain address answers that
      }
      event.preventDefault();
      openSettings(link.dataset.settings, { replace: link.dataset.settingsReplace === "true" }).catch(() => {
        location.assign(link.href);
      });
    });
  }
}
