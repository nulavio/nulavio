/* Small DOM helpers for Shell pages. Elements are built with textContent and
   attributes, never innerHTML, so engine names, URLs and profile names coming
   from settings cannot inject markup. */

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
  container.replaceChildren(...[build()].flat());
  for (const details of container.querySelectorAll("details[data-open-key]")) {
    details.open = open.has(details.dataset.openKey);
  }
  if (key) {
    container.querySelector(`[data-focus-key="${CSS.escape(key)}"]`)?.focus();
  }
}

export function initial(name) {
  return ([...String(name ?? "").trim()][0] ?? "?").toLocaleUpperCase();
}

const avatarURLs = new Map();

/** The engine's profile icon, coloured with the identity "on" token, as a data: URL. */
export function avatarURL(avatar) {
  if (!browser.nulavioProfiles || !avatar) {
    return Promise.resolve(null);
  }
  if (!avatarURLs.has(avatar)) {
    const ink = getComputedStyle(document.documentElement).getPropertyValue("--nv-color-identity-on").trim();
    avatarURLs.set(
      avatar,
      browser.nulavioProfiles
        .avatarSvg(avatar, ink)
        .then(svg => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`)
        .catch(() => null)
    );
  }
  return avatarURLs.get(avatar);
}

/** A profile's identity chip: its colour plus its icon (or initial while the icon loads). */
export function chip(profile, size = "md") {
  const kind = profile.temporary ? " chip--temporary" : "";
  const el = h("span", { class: `chip chip--${size}${kind}`, "aria-hidden": "true", text: initial(profile.name) });
  el.style.setProperty("--chip", `var(--nv-color-identity-${profile.color})`);
  avatarURL(profile.avatar).then(url => {
    if (url) {
      el.replaceChildren(h("img", { src: url, alt: "" }));
    }
  });
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
// 24 px line icons (1.75 px stroke, currentColor). State is never carried by an icon alone: words go next to it.
const ICONS = {
  critical: "M8.3 2.5h7.4l5.8 5.8v7.4l-5.8 5.8H8.3l-5.8-5.8V8.3z M12 7.5v5.5 M12 16.5v.5",
  warning: "M12 3 2 21h20z M12 10v5 M12 18v.5",
  info: "M12 21.5a9.5 9.5 0 1 0 0-19a9.5 9.5 0 0 0 0 19z M12 11v6 M12 7.5v.5",
  pause: "M9 5v14 M15 5v14",
  revoked: "M12 21.5a9.5 9.5 0 1 0 0-19a9.5 9.5 0 0 0 0 19z M5.3 5.3l13.4 13.4",
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
        class: critical ? "dialog dialog--critical" : "dialog",
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

/** Announce a short result in the page's live region. Do not repeat a hint the page already shows. */
export function announce(text, level = "ok") {
  const status = document.getElementById("status");
  if (status) {
    status.dataset.level = STATUS_LEVELS.has(level) ? level : "info";
    status.textContent = text;
  }
}

/** Where a temporary profile is kept, in the words the UI may use (never "memory only" if swap on disk is active). */
export function temporaryStorageText(state) {
  if (!state?.inMemory) {
    return t("profilesTemporaryDisk");
  }
  return t(state.swapOnDisk ? "profilesTemporarySwap" : "profilesTemporaryMemory");
}
