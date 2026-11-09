/* One template for the security moments (UX4, audit SB-24): unlocking, pairing a phone, a
   look-alike site, a program download, the Guard review and an agent's request all open with the
   same context line, the Nulavio mark and what kind of moment this is, and, where the page is about
   this profile, its name and state in words. The window's band names the page as well; only the
   browser can draw that one, so a web page that copies this line still cannot copy the band.

   Markup: <header class="moment__context" data-kind="unlock" data-profile="current"></header>
   data-profile="current" adds this profile (pages about another profile show it themselves). */

import { t } from "./i18n.js";
import { chip, h, icon, stateBadge } from "./ui.js";

// The same names the band gives these pages (NulavioWindow SURFACES), so both always agree.
const KINDS = {
  unlock: "bandSurfaceUnlock",
  phone: "bandSurfacePhone",
  lookalike: "bandSurfacePassword",
  download: "bandSurfaceDownload",
  guard: "bandSurfaceGuard",
  request: "bandSurfacePermission",
  routing: "bandSurfaceRouting",
  methods: "bandSurfaceMethods",
  create: "vaultCreateTitle",
};

async function here() {
  const summary = await browser.nulavioProfiles?.here?.().catch(() => null);
  if (!summary) {
    return [];
  }
  const states = browser.extension.inIncognitoContext
    ? ["private"]
    : summary.temporary
      ? ["temporary"]
      : summary.protection === "unlocked"
        ? ["protected"]
        : [];
  return [
    h("span", { class: "moment__profile" }, chip(summary, "sm"), h("span", { text: summary.temporary ? t("profilesTemporary") : summary.name })),
    ...states.map(stateBadge),
  ];
}

/* The page's own warning decides the severity shown in the line: a critical callout is
   "Crítico" with the octagon, a warning callout "Atenção" with the triangle, anything else none.
   Pages keep their detailed callout; the line puts the level in the same place on every page. */
function severityOf(card) {
  const callout = card.querySelector(".callout:not([hidden])");
  return callout?.classList.contains("callout--critical") ? "critical" : callout?.classList.contains("callout--warning") ? "warning" : null;
}

function showSeverity(header, card) {
  const level = severityOf(card);
  let mark = header.querySelector(":scope > .moment__severity");
  if ((mark?.dataset.level ?? null) === level) {
    return;
  }
  mark?.remove();
  if (level) {
    mark = h("span", { class: "moment__severity", dataset: { level } }, icon(level, "moment__severity-icon"), h("span", { text: t(level === "critical" ? "momentCritical" : "momentWarning") }));
    header.append(mark);
  }
}

/* SB-19: a page that failed or cannot work here offers "Tentar de novo" (it reads its state again)
   in the states it lists in data-retry, where trying again can help (a missing tool, a failed
   helper), never where it cannot (a download that does not exist); a page that waits more than
   400 ms says so (pages.css shows header[data-loading] only after that). */

function state() {
  return document.body.dataset.state ?? document.documentElement.dataset.state ?? "";
}

function offerRetry(header, card) {
  let retry = card.querySelector(":scope > .moment__retry");
  // A page with no data-retry, or with no state yet, lists nothing: "" is not a state to retry.
  const current = state();
  const wanted = current !== "" && (header.dataset.retry ?? "").split(/\s+/).includes(current);
  if (wanted && !retry) {
    const button = h("button", { class: "button button--secondary", type: "button", text: t("momentRetry") });
    button.addEventListener("click", () => location.reload());
    retry = h("div", { class: "actions moment__retry" }, button);
    const status = card.querySelector(":scope > .status, :scope > .result");
    if (status) {
      status.after(retry);
    } else {
      card.append(retry);
    }
  } else if (!wanted && retry) {
    retry.remove();
  }
}

export async function momentContext(root = document) {
  const header = root.querySelector(".moment__context");
  if (!header) {
    return;
  }
  const card = header.parentElement;
  const kind = KINDS[header.dataset.kind] ?? null;
  header.dataset.loading = t("momentLoading");
  header.replaceChildren(
    icon("mark", "moment__mark"),
    h("span", { class: "moment__kind", text: kind ? `Nulavio · ${t(kind)}` : "Nulavio" }),
    ...(header.dataset.profile === "current" ? await here() : [])
  );
  const update = () => {
    showSeverity(header, card);
    offerRetry(header, card);
  };
  update();
  new MutationObserver(update).observe(card, { subtree: true, attributes: true, attributeFilter: ["class", "hidden"] });
  const pageState = new MutationObserver(update);
  pageState.observe(document.body, { attributes: true, attributeFilter: ["data-state"] });
  pageState.observe(document.documentElement, { attributes: true, attributeFilter: ["data-state"] });
}

momentContext();
