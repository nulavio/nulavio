/* Profile template names (message keys), the unique-name helper and the way a name that is not
   Nulavio's own goes into a sentence, shared by the toolbar selector, the settings page and the
   new tab. */

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

// The Unicode formatting characters that change the direction of the text around them: the embeddings and
// overrides (U+202A-U+202E), the isolates (U+2066-U+2069) and the marks (U+200E, U+200F, U+061C).
const BIDI_CONTROLS = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;
// The paragraph separators (U+000A, U+000D, U+001C-U+001E, U+0085, U+2029): one ends the paragraph, and with it the
// isolate, so the rest of the name would sit outside it. Nulavio Search refuses the C0 controls in a name, but not
// U+0085, and an engine added outside Settings (from a page's OpenSearch description) skips that check.
const PARAGRAPH_SEPARATORS = /[\n\r\u001c-\u001e\u0085\u2029]/g;

/** A name that is not Nulavio's own, ready to be put into a sentence (#796): a search engine names itself (an
    OpenSearch description or an add-on), so the name may hold direction controls that would reorder the words
    around it. They are removed, a paragraph separator becomes a space, and the name is isolated (U+2068 FIRST
    STRONG ISOLATE ... U+2069 POP DIRECTIONAL ISOLATE): it keeps its own direction and the sentence keeps its order.
    Plain text, so it works where no element can be used (a message bar, a placeholder, an aria-label). */
export function inSentence(name) {
  return `\u2068${String(name ?? "").replace(BIDI_CONTROLS, "").replace(PARAGRAPH_SEPARATORS, " ")}\u2069`;
}

/** An engine in a sentence (#828): its name as `inSentence` gives it and, for an engine that is not one of Nulavio's
    curated providers, the host its searches go to (`withHost(name, host)` fills the locale's "name (host)"). An engine
    names itself, so two engines can have names that read the same while they send searches to different hosts; the
    chooser rows say that host already (`chooseEngineHost`, #694), and a sentence that names the engine says it too.
    `curated` holds the curated providers' keys; `quoted` puts the name, and only the name, in quotes (a name may hold
    ", ": review of #772). */
export function engineInSentence(engine, { curated, withHost, quoted = false }) {
  const name = quoted ? `“${inSentence(engine?.name)}”` : inSentence(engine?.name);
  return engine?.host && !curated.has(engine.provider) ? withHost(name, String(engine.host)) : name;
}
