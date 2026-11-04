/* Profile template names (message keys) and unique-name helper, shared by
   the toolbar selector and the settings page. */

export const TEMPLATE_NAMES = Object.freeze({
  personal: "templatePersonal",
  work: "templateWork",
  banking: "templateBanking",
  research: "templateResearch",
  sensitive: "templateSensitive",
});

/** The message that says what a template does, where it is chosen: "Sites sensíveis" also changes
    settings, the others only fill the fields (audit 2026-11 FR-02). No template: what they all do. */
export function templateHintKey(id) {
  return !id ? "profilesTemplatesNoteAll" : id === "sensitive" ? "profilesSensitiveShort" : "profilesTemplatesNote";
}

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
