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

export async function momentContext(root = document) {
  const header = root.querySelector(".moment__context");
  if (!header) {
    return;
  }
  const kind = KINDS[header.dataset.kind] ?? null;
  header.replaceChildren(
    icon("mark", "moment__mark"),
    h("span", { class: "moment__kind", text: kind ? `Nulavio · ${t(kind)}` : "Nulavio" }),
    ...(header.dataset.profile === "current" ? await here() : [])
  );
}

momentContext();
