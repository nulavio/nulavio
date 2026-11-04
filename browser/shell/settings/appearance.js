/* Settings > Aparência (UX6): window density, accent and "Mais contraste". Each change saves at
   once and says so next to its control; the state is read again from the module, so changes made
   elsewhere (another window, about:preferences for density) show here too. */

import { t } from "../lib/i18n.js";
import { announce, errorText, settleRadioChanges } from "../lib/ui.js";

export async function setUpAppearance() {
  const api = browser.nulavioPersonalise;
  const density = document.getElementById("appearance-density");
  const accent = document.getElementById("appearance-accent");
  const contrast = document.getElementById("more-contrast");
  const system = document.getElementById("more-contrast-system");
  const locked = document.getElementById("appearance-locked");
  document.getElementById("appearance").hidden = false; // the section exists only with the API

  const render = state => {
    for (const radio of density.querySelectorAll('input[name="density"]')) {
      radio.checked = radio.value === state.density;
      radio.disabled = state.locked.density;
    }
    for (const radio of accent.querySelectorAll('input[name="accent"]')) {
      radio.checked = radio.value === state.accent;
      radio.disabled = state.locked.accent;
    }
    // When the system already asks for high contrast (or forces its colours), the switch shows
    // that it is in effect and why, instead of a switch that changes nothing.
    const bySystem = state.system.moreContrast || state.system.forcedColors;
    contrast.checked = state.moreContrast || bySystem;
    contrast.disabled = bySystem || state.locked.moreContrast;
    system.hidden = !bySystem;
    locked.hidden = !Object.values(state.locked).some(Boolean);
  };
  const refresh = async () => render(await api.state());
  const save = async (change, control) => {
    try {
      render(await change());
      announce(t("doneSaved"), "ok", { control });
    } catch (e) {
      announce(errorText(e), "error", { control });
      await refresh().catch(() => {});
    }
  };

  settleRadioChanges(density, event => save(() => api.setDensity(event.target.value), event.target));
  settleRadioChanges(accent, event => save(() => api.setAccent(event.target.value), event.target));
  contrast.addEventListener("change", event => save(() => api.setMoreContrast(event.target.checked), event.target));
  api.onChanged.addListener(() => refresh().catch(() => {}));
  await refresh();
}
