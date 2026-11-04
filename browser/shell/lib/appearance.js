/* Appearance options on Nulavio's own pages (UX6): the accent and "Mais contraste" become
   attributes on <html> (data-accent, data-contrast), which shared/tokens.css turns into colours.
   Loaded first by every Shell page; a page without the privileged API keeps the defaults.
   Only looks: nothing here reads or changes what a page does. */

const api = globalThis.browser?.nulavioPersonalise;

function paint(state) {
  const root = document.documentElement;
  root.dataset.accent = state.accent;
  // The system's own high-contrast request counts too: Shell pages may not see that media query
  // (fingerprinting resistance hides it from extension pages), so the module reads it for them.
  root.dataset.contrast = state.moreContrast || state.system.moreContrast ? "more" : "standard";
}

function refresh() {
  return api.state().then(paint, () => {});
}

export const appearanceReady = api
  ? refresh().then(() => {
      try {
        api.onChanged.addListener(refresh);
      } catch {
        // A page that unloads while starting.
      }
    })
  : Promise.resolve();
