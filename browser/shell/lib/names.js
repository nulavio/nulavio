/* Profile template names (message keys) and unique-name helper, shared by
   the toolbar selector and the settings page. */

export const TEMPLATE_NAMES = Object.freeze({
  personal: "templatePersonal",
  work: "templateWork",
  banking: "templateBanking",
  research: "templateResearch",
});

/** A name not used yet: "Work", then "Work 2", "Work 3"... (case-insensitive). */
export function freeName(base, taken) {
  const lower = new Set(taken.map(n => n.toLocaleLowerCase()));
  if (!lower.has(base.toLocaleLowerCase())) {
    return base;
  }
  for (let n = 2; ; n++) {
    const candidate = `${base} ${n}`;
    if (!lower.has(candidate.toLocaleLowerCase())) {
      return candidate;
    }
  }
}
