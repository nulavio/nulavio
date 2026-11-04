/* Nulavio Guard review: changes made to this profile outside the browser
   since it last ran. Each one is undone or kept by the user's click; nothing
   happens on its own. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText, h } from "../lib/ui.js";

const guard = browser.nulavioGuard;

const UNDO_LABELS = {
  "extension-added": "guardUndoExtension",
  "extension-changed": "guardUndoExtension",
  "pref-changed": "guardUndoPref",
  "root-added": "guardUndoRoot",
  "module-added": "guardUndoModule",
  "search-changed": "guardUndoSearch",
};
const REVEALABLE = new Set(["host-added", "host-changed", "userjs-added", "userjs-changed"]);

/* Most consequential first: what can read your traffic or run code, then where your data goes. */
const ORDER = [
  "root-added", "module-added", "extension-added", "extension-changed", "host-added", "host-changed",
  "pref-changed", "search-changed", "policies-changed", "userjs-added", "userjs-changed", "extension-removed",
];
const rank = f => (ORDER.includes(f.kind) ? ORDER.indexOf(f.kind) : ORDER.length);

function value(v) {
  if (v === null || v === undefined || v === "") {
    return t("guardValueDefault");
  }
  return String(v);
}

function describe(f) {
  switch (f.kind) {
    case "extension-added":
      return {
        title: t("guardExtensionAdded", [f.after.name]),
        detail: `${f.key} · ${f.after.version}`,
        why: t(f.after.active ? "guardExtensionWhy" : "guardExtensionWhyOff"),
      };
    case "extension-changed":
      return {
        title: t("guardExtensionChanged", [f.after.name]),
        detail: `${f.key} · ${f.before.version} → ${f.after.version}${!f.before.active && f.after.active ? ` · ${t("guardTurnedOn")}` : ""}`,
        why: t("guardExtensionChangedWhy"),
      };
    case "extension-removed":
      return { title: t("guardExtensionRemoved", [f.before.name]), detail: f.key, why: t("guardExtensionRemovedWhy") };
    case "pref-changed":
      return { title: t("guardPrefChanged"), detail: `${f.key}: ${value(f.before)} → ${value(f.after)}`, why: t("guardPrefWhy") };
    case "root-added":
      return { title: t("guardRootAdded"), detail: `${f.after.subject}\nSHA-256 ${f.key}`, why: t("guardRootWhy") };
    case "module-added":
      return { title: t("guardModuleAdded", [f.key]), detail: f.after.library, why: t("guardModuleWhy") };
    case "host-added":
    case "host-changed":
      return {
        title: t(f.kind === "host-added" ? "guardHostAdded" : "guardHostChanged", [f.after.name]),
        detail: `${f.after.program ?? "?"}\n${f.key}`,
        why: t("guardHostWhy"),
      };
    case "policies-changed":
      return { title: t("guardPolicies"), detail: (f.after?.names ?? []).join(", ") || t("guardValueDefault"), why: t("guardPoliciesWhy") };
    case "userjs-added":
    case "userjs-changed":
      return { title: t(f.kind === "userjs-added" ? "guardUserJsAdded" : "guardUserJsChanged"), detail: "user.js", why: t("guardUserJsWhy") };
    case "search-changed":
      return {
        title: t("guardSearchChanged"),
        detail: `${value(f.before?.default)} → ${value(f.after?.default)}`,
        why: t("guardSearchWhy"),
      };
    default:
      return { title: f.kind, detail: f.key, why: "" };
  }
}

async function act(action, finding) {
  try {
    if (action === "reveal") {
      await guard.reveal(finding.id);
      return;
    }
    const left = await guard.resolve(finding.id, action);
    render(left);
    const said = t(action === "undo" ? "guardUndone" : "guardKept");
    announce(left.length ? said : `${said} ${t("guardAllReviewed")}`); // the last one: the review is over
  } catch (e) {
    announce(errorText(e), "error");
  }
}

function item(f) {
  const { title, detail, why } = describe(f);
  const buttons = [];
  if (f.undoable) {
    buttons.push(h("button", { class: "button button--primary", type: "button", dataset: { action: "undo" }, text: t(UNDO_LABELS[f.kind]) }));
  }
  if (REVEALABLE.has(f.kind)) {
    buttons.push(h("button", { class: "button button--secondary", type: "button", dataset: { action: "reveal" }, text: t("guardReveal") }));
  }
  buttons.push(
    h("button", {
      class: "button button--secondary",
      type: "button",
      dataset: { action: "keep" },
      text: t(f.kind === "extension-removed" || f.kind === "policies-changed" ? "guardUnderstood" : "guardKeep"),
    })
  );
  for (const button of buttons) {
    button.addEventListener("click", () => act(button.dataset.action, f));
  }
  return h(
    "li",
    { class: "card stack stack--tight", dataset: { findingId: f.id, kind: f.kind } },
    h("h2", { class: "card__title", text: title }),
    h("p", { class: "mono finding__detail", text: detail }),
    why ? h("p", { class: "hint", text: why }) : null,
    h("div", { class: "actions" }, ...buttons)
  );
}

let reviewing = false; // findings were shown: an empty list now means the last one was just resolved

function render(findings) {
  const list = document.getElementById("findings");
  list.replaceChildren(...[...findings].sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id)).map(item));
  list.removeAttribute("aria-busy");
  document.getElementById("empty").hidden = findings.length > 0;
  document.body.dataset.state = findings.length ? "review" : "empty";
  document.body.dataset.count = String(findings.length);
  if (!findings.length) {
    guard.hideBar().catch(() => {});
    // The page says what it is now: nothing to review (audit 2026-11 GUARD-01).
    document.title = t("guardEmptyTitle");
    document.getElementById("headline").textContent = t("guardEmptyTitle");
    document.getElementById("intro").textContent = t("guardIntroEmpty");
    // Why there is nothing, when there is a reason (audit 2026-11 GUARD-02); else "as Nulavio last saw it".
    guard.check().then(result => {
      const key = result?.state === "first" ? "guardFirst"
        : result?.reason === "temporary" ? "guardSkippedTemporary"
          : result?.reason === "ai-workspace" ? "guardSkippedWorkspace" : null;
      if (key && !reviewing) {
        document.querySelector("#empty .hint").textContent = t(key);
      }
    }).catch(() => {});
    if (reviewing) {
      document.getElementById("close").focus();
    }
  }
  reviewing = findings.length > 0;
}

document.getElementById("close").addEventListener("click", async () => {
  const tab = await browser.tabs.getCurrent();
  const siblings = await browser.tabs.query({ windowId: tab.windowId });
  return siblings.length > 1 ? browser.tabs.remove(tab.id) : browser.tabs.update(tab.id, { url: "about:newtab" });
});

localize();
guard
  .findings()
  .then(render)
  .catch(e => {
    document.body.dataset.state = "error";
    document.getElementById("findings").removeAttribute("aria-busy"); // nothing is loading any more (SB-19)
    announce(errorText(e), "error");
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
    document.querySelector("#findings button")?.focus();
  });
