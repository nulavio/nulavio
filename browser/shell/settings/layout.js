/* Explicit choices only. The native state is authoritative, including changes
   made in other windows and in Gecko's sidebar controls. */

import { t } from "../lib/i18n.js";
import { errorText, settleRadioChanges } from "../lib/ui.js";

export async function setUpLayout() {
  const api = browser.nulavioLayout;
  const section = document.getElementById("layout");
  const group = document.getElementById("layout-choices");
  const radios = [...group.querySelectorAll('input[name="layout"]')];
  const current = document.getElementById("layout-current");
  const error = document.getElementById("layout-error");
  const retry = document.getElementById("layout-retry");
  // QA M-2: the first-run choice is also kept here, so it never stays pending out of reach
  // (for example after the new tab is handed back to another page).
  const pending = document.getElementById("layout-pending");
  const keep = document.getElementById("layout-keep");
  let revision = 0;
  let busy = false;
  let closed = false;
  let listening = false;
  let keyboard = null;

  // Immersive (ADR 0009): one switch, read from the profile and written through the layout module.
  const immersive = document.getElementById("immersive");
  const immersiveError = document.getElementById("immersive-error");
  const showImmersive = state => {
    immersive.checked = state.on;
    immersive.disabled = state.locked;
  };
  const readImmersive = () => api.immersive().then(showImmersive, () => {});
  immersive.addEventListener("change", async () => {
    immersiveError.textContent = "";
    try {
      showImmersive(await api.setImmersive(immersive.checked));
    } catch (e) {
      immersiveError.textContent = errorText(e);
      await readImmersive();
    }
  });
  // The key (Ctrl+Alt+I) may have changed it while this tab was in the background.
  document.addEventListener("visibilitychange", () => document.hidden || readImmersive());
  readImmersive();

  const showUnavailable = err => {
    current.textContent = t("layoutUnavailable");
    error.textContent = errorText(err);
    for (const radio of radios) radio.disabled = true;
    pending.hidden = keep.hidden = true;
    retry.hidden = false;
  };
  const render = state => {
    section.dataset.preset = state.preset;
    current.textContent = !state.available ? t("layoutUnavailable") : state.locked ? t("layoutLocked")
      : t(`layoutCurrent_${state.preset}`);
    for (const radio of radios) {
      radio.checked = radio.value === state.preset;
      radio.disabled = busy || !state.available || state.locked;
    }
    pending.hidden = keep.hidden = !state.choicePending;
    keep.textContent = ["lateral", "top", "focus"].includes(state.preset)
      ? t(`layoutChoiceKeep_${state.preset}`) : t("layoutChoiceDone");
    keep.disabled = busy;
  };
  const refresh = async () => {
    if (closed || busy || keyboard?.pending()) return;
    const request = ++revision;
    try {
      const state = await api.state();
      if (closed || busy || keyboard?.pending() || request !== revision) return;
      render(state);
      retry.hidden = true;
    } catch (e) {
      if (closed || busy || request !== revision) return;
      showUnavailable(e);
    }
  };
  const listen = () => {
    if (listening) return true;
    try {
      api.onChanged.addListener(refresh);
      listening = true;
      return true;
    } catch (e) {
      showUnavailable(e);
      return false;
    }
  };
  section.hidden = false;
  window.addEventListener("pagehide", () => {
    closed = true;
    revision++;
    if (listening) {
      try {
        api.onChanged.removeListener(refresh);
      } catch {
        // Context already tearing down.
      }
      listening = false;
    }
  });
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    closed = false;
    group.setAttribute("aria-busy", String(busy));
    if (listen()) refresh();
  });
  group.addEventListener("change", event => {
    if (radios.includes(event.target)) revision++;
  });
  keyboard = settleRadioChanges(group, async event => {
    const chosen = radios.find(radio => radio.checked);
    if (busy || !radios.includes(event.target) || !chosen) return;
    busy = true;
    revision++;
    group.setAttribute("aria-busy", "true");
    error.textContent = "";
    const focused = document.activeElement;
    for (const radio of radios) radio.disabled = true;
    keep.disabled = true;
    current.textContent = t("layoutApplying");
    try {
      await api.apply(chosen.value);
    } catch (e) {
      if (!closed) error.textContent = errorText(e);
    } finally {
      busy = false;
      if (!closed) {
        group.setAttribute("aria-busy", "false");
        await refresh();
        if (radios.includes(focused) && document.activeElement === document.body && !focused.disabled) focused.focus();
      }
    }
  });
  keep.addEventListener("click", async () => {
    if (keyboard?.pending()) await keyboard.flush();
    if (busy) return;
    busy = true;
    revision++;
    error.textContent = "";
    keep.disabled = true;
    const hadFocus = document.activeElement === keep;
    try {
      await api.dismissChoice();
    } catch (e) {
      if (!closed) error.textContent = errorText(e);
    } finally {
      busy = false;
      if (!closed) {
        await refresh();
        // The button hides once the choice is kept; keep focus inside the section.
        if (hadFocus && keep.hidden) radios.find(r => r.checked && !r.disabled)?.focus();
      }
    }
  });
  retry.addEventListener("click", () => {
    error.textContent = "";
    if (listen()) refresh();
  });
  if (listen()) await refresh();
}
