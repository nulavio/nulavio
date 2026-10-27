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

/** Ask for confirmation with a native modal <dialog>. Resolves true when confirmed. */
export function confirmDialog({ title, body, confirm, danger = false }) {
  return new Promise(resolve => {
    const dialog = h(
      "dialog",
      { class: "dialog", "aria-labelledby": "dialog-title" },
      h(
        "form",
        { method: "dialog", class: "dialog__form" },
        h("h2", { class: "dialog__title", id: "dialog-title", text: title }),
        body ? h("p", { class: "dialog__body", text: body }) : null,
        h(
          "div",
          { class: "actions actions--end" },
          h("button", { class: "button button--secondary", value: "cancel", autofocus: true, text: t("confirmCancel") }),
          h("button", { class: `button ${danger ? "button--danger" : "button--primary"}`, value: "confirm", text: confirm })
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

/** Announce a short result in the page's live region. */
export function announce(text, level = "ok") {
  const status = document.getElementById("status");
  if (status) {
    status.dataset.level = level;
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
