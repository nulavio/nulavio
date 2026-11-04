/* Small DOM helpers for Shell pages. Elements are built with textContent and
   attributes, never innerHTML, so engine names, URLs and profile names coming
   from settings cannot inject markup. */

import { AVATAR_GLYPHS, SPECIAL_GLYPHS, profileGlyph, profileInitial } from "../modules/NulavioAvatars.sys.mjs";
import { t } from "./i18n.js";

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) {
      continue;
    }
    if (key === "class") {
      el.className = value;
    } else if (key === "text") {
      el.textContent = value;
    } else if (key === "dataset") {
      Object.assign(el.dataset, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2), value);
    } else {
      el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) {
      el.append(child instanceof Node ? child : String(child));
    }
  }
  return el;
}

/** User-facing text for an error code sent by the Shell's privileged modules. */
export function errorText(error) {
  const code = String(error?.message ?? error).replace(/[^a-z_-]/gi, "").replaceAll("-", "_");
  return (code && browser.i18n.getMessage(`err_${code}`)) || t("err_unexpected");
}

/** Replace a container's content while keeping keyboard focus on the "same" control. */
export function rerender(container, build) {
  const key = document.activeElement?.closest?.("[data-focus-key]")?.dataset.focusKey;
  const open = new Set([...container.querySelectorAll("details[open][data-open-key]")].map(d => d.dataset.openKey));
  // What the person changed but did not save yet, in an open form (a name, an icon, a colour): an
  // unrelated update (another window, another profile) redraws the list and must not throw it away.
  const edits = [];
  for (const field of container.querySelectorAll("details[open][data-open-key] [data-focus-key]")) {
    if (field.type === "radio" || field.type === "checkbox") {
      if (field.checked !== field.defaultChecked) {
        edits.push([field.dataset.focusKey, "checked", field.checked]);
      }
    } else if (field.localName === "input" && field.type !== "submit" && field.value !== field.defaultValue) {
      edits.push([field.dataset.focusKey, "value", field.value]);
    }
  }
  container.replaceChildren(...[build()].flat());
  for (const details of container.querySelectorAll("details[data-open-key]")) {
    details.open = open.has(details.dataset.openKey);
  }
  for (const [focusKey, property, value] of edits) {
    const field = container.querySelector(`details[open] [data-focus-key="${CSS.escape(focusKey)}"]`);
    if (field) {
      field[property] = value;
    }
  }
  if (edits.length) {
    for (const grid of container.querySelectorAll("details[open] .swatches--glyphs")) {
      const color = grid.closest("form")?.querySelector('input[name="color"]:checked')?.value;
      if (color) {
        tintAvatars(grid, color);
      }
    }
  }
  if (key) {
    container.querySelector(`[data-focus-key="${CSS.escape(key)}"]`)?.focus();
  }
}

export function initial(name) {
  return ([...String(name ?? "").trim()][0] ?? "?").toLocaleUpperCase();
}

const SVG_NS = "http://www.w3.org/2000/svg";
const IDENTITY_NAMES = new Set(["lima", "sky", "violet", "coral", "sand", "slate"]);

/** A solid glyph (modules/NulavioAvatars.sys.mjs) as an inline SVG in the current colour. */
export function glyph(d, className = "chip__glyph") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "currentColor");
  path.setAttribute("fill-rule", "evenodd");
  svg.append(path);
  return svg;
}

/** A profile's identity chip (Calmaria): a soft tile in its colour with its solid glyph, or its
    initial; never colour alone, and never a "?" (that sign means "unknown" elsewhere). */
export function chip(profile, size = "md") {
  const kind = profile.temporary ? " chip--temporary" : "";
  const el = h("span", { class: `chip chip--${size}${kind}`, "aria-hidden": "true" });
  const color = IDENTITY_NAMES.has(profile.color) ? profile.color : "slate";
  el.style.setProperty("--chip", `var(--nv-color-identity-${color})`);
  el.style.setProperty("--tile", `var(--nv-color-identityTile-${color})`);
  el.style.setProperty("--glyph", `var(--nv-color-identityGlyph-${color})`);
  const d = profileGlyph(profile);
  const letter = d ? null : profileInitial(profile.name);
  if (letter) {
    el.textContent = letter;
  } else {
    el.append(glyph(d ?? SPECIAL_GLYPHS.person));
  }
  return el;
}
/** The icon choice (Calmaria): a radio grid of glyph tiles. Only the chosen one wears the profile's
    colour (set with tintAvatars when the colour changes), so the grid stays quiet and the choice is
    shown by colour, a ring and the label together. `name` draws an icon this build cannot draw with the
    profile's initial, as its chip does. */
export function avatarPicker({ avatars, selected, color, name = "", focusKey = null }) {
  const choices = selected && !avatars.includes(selected) ? [selected, ...avatars] : avatars;
  const grid = h(
    "fieldset",
    { class: "swatches swatches--glyphs" },
    h("legend", { class: "field__label", text: t("profilesIconLabel") }),
    choices.map(avatar => {
      const label = browser.i18n.getMessage(`avatar_${avatar.replaceAll("-", "_")}`) || t("profilesIconCurrent");
      const d = AVATAR_GLYPHS[avatar];
      return h(
        "label",
        { class: "swatch swatch--glyph", title: label },
        h("input", {
          type: "radio",
          name: "avatar",
          value: avatar,
          checked: avatar === selected,
          "data-focus-key": focusKey ? `${focusKey}-${avatar}` : null,
        }),
        h("span", { class: "swatch__tile", "aria-hidden": "true" }, d ? glyph(d, "swatch__glyph") : profileInitial(name) ?? glyph(SPECIAL_GLYPHS.person, "swatch__glyph")),
        h("span", { class: "visually-hidden", text: label })
      );
    })
  );
  tintAvatars(grid, color);
  return grid;
}

/** Give the icon grid the tile and glyph of the colour chosen next to it. */
export function tintAvatars(grid, color) {
  const name = IDENTITY_NAMES.has(color) ? color : "slate";
  grid.style.setProperty("--tile", `var(--nv-color-identityTile-${name})`);
  grid.style.setProperty("--glyph", `var(--nv-color-identityGlyph-${name})`);
}

// 24 px line icons (1.75 px stroke, currentColor). State is never carried by an icon alone: words go next to it.
const ICONS = {
  critical: "M8.3 2.5h7.4l5.8 5.8v7.4l-5.8 5.8H8.3l-5.8-5.8V8.3z M12 7.5v5.5 M12 16.5v.5",
  warning: "M12 3 2 21h20z M12 10v5 M12 18v.5",
  info: "M12 21.5a9.5 9.5 0 1 0 0-19a9.5 9.5 0 0 0 0 19z M12 11v6 M12 7.5v.5",
  pause: "M9 5v14 M15 5v14",
  revoked: "M12 21.5a9.5 9.5 0 1 0 0-19a9.5 9.5 0 0 0 0 19z M5.3 5.3l13.4 13.4",
  lock: "M7.5 11V8a4.5 4.5 0 0 1 9 0v3 M5.5 11h13v9.5h-13z",
  unlocked: "M7.5 11V8a4.5 4.5 0 0 1 8.7-1.6 M5.5 11h13v9.5h-13z",
  temporary: "M7.2 3.6h9.6 M7.2 20.4h9.6 M8.4 3.6v3.1L12 12l3.6-5.3V3.6 M8.4 20.4v-3.1L12 12l3.6 5.3v3.1",
  agent: "M6 8.5h12v10.5H6z M12 4.5v4 M9.5 15.5h5 M9.5 12v.5 M14.5 12v.5",
  private: "M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z M9.5 12a2.5 2.5 0 1 0 5 0a2.5 2.5 0 0 0-5 0 M4 4l16 16",
  // The Nulavio route mark (shared/nulavio-symbol-mono.svg at 24 px), for the security moments' context line
  mark: "M6.75 10.9V3.75l10.5 16.5V3.75 M6.75 19.1v.05",
};

/** A decorative icon (hidden from assistive technology), built without markup strings. */
export function icon(name, className = "icon") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.dataset.icon = name;
  const path = document.createElementNS(SVG_NS, "path");
  for (const [key, value] of Object.entries({
    d: ICONS[name] ?? ICONS.critical,
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.75",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  })) {
    path.setAttribute(key, value);
  }
  svg.append(path);
  return svg;
}

/* One look for a profile's state on every Shell page (audit SPA-02): a glyph and the word,
   never colour alone. The word is the accessible text. */
const PROFILE_STATES = {
  protected: ["unlocked", "vaultProtectedBadge"],
  locked: ["lock", "profilesLocked"],
  temporary: ["temporary", "profilesTemporaryShort"],
  workspace: ["agent", "stateAiWorkspace"],
  private: ["private", "statePrivateWindow"],
};

export function stateBadge(state) {
  const [glyph, key] = PROFILE_STATES[state];
  return h("span", { class: "badge badge--security", dataset: { state } }, icon(glyph, "badge__icon"), h("span", { text: t(key) }));
}

/** The states a profile record shows, in a fixed order. */
export function profileStates(profile) {
  return [
    profile.temporary ? "temporary" : null,
    profile.locked ? "locked" : profile.encrypted ? "protected" : null,
  ].filter(Boolean);
}

/** "Bloquear agora" for this browser's own protected profile (UX4): it closes every window of
    the profile, so it asks first, with Cancel as the focused primary. Returns the announcement. */
export async function lockCurrentProfile(name) {
  const ok = await confirmDialog({
    title: t("vaultLockCurrentTitle", [name]),
    body: t("vaultLockCurrentBody"),
    confirm: t("vaultLockCurrentConfirm"),
    danger: true,
  });
  if (!ok) {
    return null;
  }
  const { quit } = await browser.nulavioVault.lockCurrent();
  return quit ? t("vaultLockCurrentClosing") : t("vaultLockCurrentKept");
}

/** Ask for confirmation with a native modal <dialog>. Resolves true when confirmed.
    `critical`: a consent that raises what an agent may do (full control, raw automation): a critical
    icon in the title, the body in primary text, announced as an alert dialog.
    Critical/destructive confirmations keep Cancel focused, first and visually primary. */
export function confirmDialog({ title, body, confirm, danger = false, critical = false }) {
  return new Promise(resolve => {
    const warning = danger || critical;
    const dialog = h(
      "dialog",
      {
        // UX7: a destructive confirmation has its own class, so it never moves (components.css).
        class: critical ? "dialog dialog--critical" : danger ? "dialog dialog--danger" : "dialog",
        role: critical ? "alertdialog" : null,
        "aria-labelledby": "dialog-title",
        "aria-describedby": body ? "dialog-body" : null,
      },
      h(
        "form",
        { method: "dialog", class: "dialog__form" },
        h("h2", { class: "dialog__title", id: "dialog-title" }, critical ? icon("critical", "dialog__icon") : null, h("span", { text: title })),
        body ? h("p", { class: critical ? "dialog__body dialog__body--strong" : "dialog__body", id: "dialog-body", text: body }) : null,
        h(
          "div",
          { class: "actions actions--end" },
          h("button", { class: `button ${warning ? "button--primary" : "button--secondary"}`, value: "cancel", autofocus: true, text: t("confirmCancel") }),
          h("button", { class: `button ${warning ? "button--danger" : "button--primary"}`, value: "confirm", text: confirm })
        )
      )
    );
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm");
      dialog.remove();
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}

/* Levels of the status line (shell.css draws each with a mark and words, never colour alone):
   info (no mark: instructions), progress (a neutral spinner, still under reduced motion), ok (✓, only
   for a result that happened), warn (⚠, degraded or needs attention), error (critical style and icon). */
const STATUS_LEVELS = new Set(["info", "progress", "ok", "warn", "error"]);

/** The words that name a control: its own label (without the hint under it), or its button text. */
export function controlName(control) {
  const own = control.getAttribute("aria-label");
  if (own) {
    return own.trim();
  }
  const label = control.labels?.[0];
  if (label) {
    const named = [".field__label", ":scope > span > span:not(.hint)", ":scope > span > strong", ":scope > span:not(.hint)"]
      .map(selector => label.querySelector(selector))
      .find(Boolean);
    return [...(named ?? label).childNodes]
      .filter(node => !node.classList?.contains("inline-status"))
      .map(node => node.textContent)
      .join("")
      .trim();
  }
  return control.textContent.trim();
}

/* UX4 (SPA-06): on a page whose status line has data-inline-anchor, a result of what the
   person just did is shown next to the control that still has the keyboard (an aria-hidden
   mark that does not change the control's name) and spoken once, with the control's name.
   Errors also stay in the status line, shown at the bottom of the page. */
const INLINE_MS = 4000;
let toastTimer = null;

function inlineHost(control) {
  if (!control || control === document.body || !control.closest?.("main")) {
    return null;
  }
  const field = control.closest(".field");
  if (field) {
    return field.querySelector(".field__label") ?? field;
  }
  return control.closest(".check, .inline-form") ?? control;
}

function showInline(host, text, level) {
  const after = host.matches("button, a, input, select");
  let mark = after ? host.nextElementSibling : host.querySelector(":scope > .inline-status");
  if (!mark?.classList.contains("inline-status")) {
    mark = h("span", { class: "inline-status", "aria-hidden": "true" });
    if (after) {
      host.after(mark);
    } else {
      host.append(mark);
    }
  }
  mark.dataset.level = level;
  mark.textContent = text;
  clearTimeout(mark.timer);
  mark.timer = setTimeout(() => mark.remove(), INLINE_MS);
}

/** The control a result belongs to: the one given, or the same control after a re-render. */
function stillThere(control) {
  if (!control || control.isConnected) {
    return control;
  }
  const key = control.dataset?.focusKey;
  return key ? document.querySelector(`[data-focus-key="${CSS.escape(key)}"]`) : null;
}

/** Announce a short result in the page's live region. Do not repeat a hint the page already shows.
    `control`: the control that started the action, read before it awaited anything (the person may
    have moved on since; review F13). Without it, the focused control; null: no control (a
    background read), so the result goes to the status line only. */
export function announce(text, level = "ok", { control } = {}) {
  const status = document.getElementById("status");
  if (!status) {
    return;
  }
  const kind = STATUS_LEVELS.has(level) ? level : "info";
  control = control === undefined ? document.activeElement : stillThere(control);
  const host = status.hasAttribute("data-inline-anchor") && ["ok", "warn", "error"].includes(kind) ? inlineHost(control) : null;
  status.dataset.level = kind;
  if (host) {
    const name = controlName(control);
    status.textContent = name ? t("statusNamed", [name, text]) : text;
    showInline(host, text, kind);
  } else {
    status.textContent = text;
  }
  // Shown at the bottom only when it is not already next to the control (errors always are).
  status.toggleAttribute("data-inline", Boolean(host) && kind !== "error");
  if (status.hasAttribute("data-inline-anchor")) {
    clearTimeout(toastTimer);
    if (kind !== "progress") {
      toastTimer = setTimeout(() => {
        status.textContent = "";
      }, kind === "error" ? 3 * INLINE_MS : INLINE_MS);
    }
  }
}

/** Where a temporary profile is kept, in the words the UI may use (never "memory only" if swap on disk is active). */
export function temporaryStorageText(state) {
  if (!state?.inMemory) {
    return t("profilesTemporaryDisk");
  }
  return t(state.swapOnDisk ? "profilesTemporarySwap" : "profilesTemporaryMemory");
}

// Layout radios (QA B-8): arrow keys move through a radio group natively and fire "change" on
// every step. A change made from the keyboard calls `apply` once the person pauses, so each
// step does not rearrange the whole window; a pointer change calls it at once.
// `pending()` is true while a keyboard change waits; `flush()` runs it now.
export function settleRadioChanges(group, apply, delay = 500) {
  const KEYS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", " "];
  let keyAt = -Infinity;
  let timer = null;
  let waiting = null;
  const run = () => {
    clearTimeout(timer);
    timer = null;
    const event = waiting;
    waiting = null;
    return event ? apply(event) : Promise.resolve();
  };
  group.addEventListener("keydown", event => {
    if (KEYS.includes(event.key)) keyAt = performance.now();
  });
  group.addEventListener("change", event => {
    clearTimeout(timer);
    waiting = event;
    if (performance.now() - keyAt < 250) {
      timer = setTimeout(run, delay);
    } else {
      run();
    }
  });
  return { pending: () => waiting !== null, flush: run };
}
