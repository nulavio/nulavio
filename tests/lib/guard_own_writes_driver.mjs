// Runs the Shell's start for the engine's fingerprinting set (#654: applyAccessibility in
// browser/shell/modules/NulavioFingerprinting.sys.mjs, from its watch()) against a stand-in for the engine's prefs,
// then the Guard's own comparison (compareSnapshots, and withoutOwnValues in browser/shell/modules/NulavioGuard.sys.mjs)
// between the record of the last start (its prefs, and the set it kept as Nulavio's own) and the prefs after it.
// Prints, as JSON, for each case: the set after the start, what the module told the Guard, and the findings with and
// without what the record and the module say is Nulavio's own. Used by
// tests/unit/test_fingerprinting_shell.py; the real engine is exercised by tests/integration/test_guard.py (07).
//
//     node tests/lib/guard_own_writes_driver.mjs <NulavioGuard module> <NulavioFingerprinting module>

import { pathToFileURL } from "node:url";

const OVERRIDES = "privacy.fingerprintingProtection.overrides";
const WRITTEN = "nulavio.fingerprinting.overridesWritten";
const SHARE = "nulavio.fingerprinting.shareAccessibility";
const ACCESSIBILITY = "+CSSPrefersReducedMotion,+CSSPrefersContrast,+CSSPrefersReducedTransparency";
// The build's default of this start, and an earlier build's, which had one entry fewer.
const DEFAULT = `+CanvasRandomization,+WebGLRenderInfo,${ACCESSIBILITY},+JSDateTimeUTC`;
const CURRENT = "+CanvasRandomization,+WebGLRenderInfo,+JSDateTimeUTC"; // what the module makes of it
const EARLIER = "+CanvasRandomization,+JSDateTimeUTC";

// -- stand-ins for what the engine gives the modules ---------------------------------------------------

let user = new Map(); // the profile's own values
const defaults = new Map([[OVERRIDES, DEFAULT]]);
const read = (name, fallback) => (user.has(name) ? user.get(name) : defaults.has(name) ? defaults.get(name) : fallback);

globalThis.Services = {
  prefs: {
    prefIsLocked: () => false,
    prefHasUserValue: name => user.has(name),
    getBoolPref: read,
    getIntPref: read,
    getStringPref: read,
    setBoolPref: (name, value) => user.set(name, Boolean(value)),
    setStringPref: (name, value) => user.set(name, String(value)),
    clearUserPref: name => user.delete(name),
    getDefaultBranch: () => ({ getStringPref: (name, fallback) => (defaults.has(name) ? defaults.get(name) : fallback) }),
    addObserver: () => {},
    removeObserver: () => {},
  },
  obs: { addObserver: () => {}, removeObserver: () => {} },
  perms: { ALLOW_ACTION: 1, getAllByTypes: () => [] },
  wm: { getEnumerator: () => [] },
  tm: { dispatchToMainThread: () => {} },
};

// What the fingerprinting module tells the Guard, recorded and passed on to the real one.
const told = [];
let guard = null;
const fakes = {
  NulavioGuard: {
    ownPrefValue(name, value) {
      told.push({ name, value });
      guard.NulavioGuard.ownPrefValue(name, value); // the real one takes it
    },
  },
};
globalThis.ChromeUtils = {
  defineESModuleGetters(lazy, modules) {
    for (const name of Object.keys(modules)) {
      if (name in fakes) {
        Object.defineProperty(lazy, name, { get: () => fakes[name] });
      }
    }
  },
};

guard = await import(pathToFileURL(process.argv[2]).href);
const { NulavioFingerprinting } = await import(pathToFileURL(process.argv[3]).href);
const Guard = guard.NulavioGuard.constructor;

/** The prefs the Guard's record keeps of these: the profile's own values only (NulavioGuard's #prefs). */
function recorded(values) {
  return Object.fromEntries(Object.entries(values).filter(([name, value]) => name !== WRITTEN && value !== null));
}

/** One start: the profile as the last session left it (`profile`), the Guard's record of that session (`record`, its
    prefs) and the value it kept as Nulavio's own (`owned`, what the module told it at that start). */
function start(profile, record = profile, owned = {}) {
  user = new Map(Object.entries(profile).filter(([, value]) => value !== null));
  told.length = 0;
  NulavioFingerprinting.unwatch();
  NulavioFingerprinting.watch();
  const now = Object.fromEntries([SHARE, OVERRIDES].map(name => [name, user.has(name) ? user.get(name) : null]));
  const findings = guard.compareSnapshots({ prefs: recorded(record) }, { prefs: recorded(now) });
  // What the module holds as its own at this start: its last word, as the real Guard keeps it.
  const last = told.at(-1);
  const ownNow = last && last.value !== null ? { [last.name]: last.value } : {};
  const kept = Guard.withoutOwnValues(findings, owned, ownNow);
  const brief = list => list.map(f => [f.key, f.before, f.after]);
  return { set: now[OVERRIDES], written: user.get(WRITTEN) ?? null, told: told.map(t => t.value), findings: brief(findings), reported: brief(kept) };
}

const out = { current: CURRENT };
const ownCurrent = { [OVERRIDES]: CURRENT };
// A build whose default changed: the set the module wrote at the last start, which the record kept as Nulavio's, is
// written again from the new default.
out.ownUpdate = start({ [SHARE]: true, [OVERRIDES]: EARLIER, [WRITTEN]: EARLIER }, undefined, { [OVERRIDES]: EARLIER });
// The same build again: the set is the same, nothing is written.
out.sameBuild = start({ [SHARE]: true, [OVERRIDES]: CURRENT, [WRITTEN]: CURRENT }, undefined, ownCurrent);
// A set put in the closed profile, which the module leaves as it is (the person's own, as far as it can tell).
out.outsidePlain = start({ [SHARE]: true, [OVERRIDES]: "+CanvasRandomization", [WRITTEN]: CURRENT }, {
  [SHARE]: true,
  [OVERRIDES]: CURRENT,
}, ownCurrent);
// A set put in the closed profile that the module then writes again, without the accessibility entry in it.
out.outsideStripped = start({ [SHARE]: true, [OVERRIDES]: "+CanvasRandomization,+CSSPrefersContrast", [WRITTEN]: CURRENT }, {
  [SHARE]: true,
  [OVERRIDES]: CURRENT,
}, ownCurrent);
// A set and the module's memory of it both forged in the closed profile, with a build whose default changed, and a
// record that did not keep the earlier set as Nulavio's: the module takes the set for its own and writes the build's.
out.forgedWritten = start({ [SHARE]: true, [OVERRIDES]: "+JSDateTimeUTC", [WRITTEN]: "+JSDateTimeUTC" }, {
  [SHARE]: true,
  [OVERRIDES]: EARLIER,
});
// The same forgery on a profile whose record kept the earlier set as Nulavio's: the module writes the build's set over
// the forged one and its memory, so nothing of the forgery is left, and what changed since the record is Nulavio's
// own update (the same set and memory as ownUpdate).
out.forgedOverwritten = start({ [SHARE]: true, [OVERRIDES]: "+JSDateTimeUTC", [WRITTEN]: "+JSDateTimeUTC" }, {
  [SHARE]: true,
  [OVERRIDES]: EARLIER,
}, { [OVERRIDES]: EARLIER });
// A set of the person's own, in the record, and only the module's memory forged in the closed profile to name it
// (OpenCodeReview on #825): the module takes the set for its own and writes the build's set over it. The record never
// held that set as the module's, so the change is still reported.
out.forgedMemoryOnly = start({ [SHARE]: true, [OVERRIDES]: "+CanvasRandomization", [WRITTEN]: "+CanvasRandomization" }, {
  [SHARE]: true,
  [OVERRIDES]: "+CanvasRandomization",
});
// The setting turned on in the closed profile: the module writes a set where there was none.
out.shareOutside = start({ [SHARE]: true }, {});
// The setting off: nothing is written or told at a start.
out.shareOff = start({ [OVERRIDES]: EARLIER, [WRITTEN]: EARLIER }, undefined, { [OVERRIDES]: EARLIER });
// The Guard's filter alone: from exactly the record's own value to exactly the one held now, and only for that setting.
const finding = { id: `pref-changed:${OVERRIDES}`, kind: "pref-changed", key: OVERRIDES, before: EARLIER, after: CURRENT };
const was = { [OVERRIDES]: EARLIER };
out.filter = {
  same: Guard.withoutOwnValues([finding], was, ownCurrent).length,
  otherBefore: Guard.withoutOwnValues([{ ...finding, before: "+JSDateTimeUTC" }], was, ownCurrent).length,
  otherAfter: Guard.withoutOwnValues([{ ...finding, after: "+JSDateTimeUTC" }], was, ownCurrent).length,
  notOwnedThen: Guard.withoutOwnValues([finding], {}, ownCurrent).length,
  notOwnedNow: Guard.withoutOwnValues([finding], was, {}).length,
  otherName: Guard.withoutOwnValues([{ ...finding, key: "network.proxy.type", id: "pref-changed:network.proxy.type" }], was, ownCurrent).length,
  otherKind: Guard.withoutOwnValues([{ ...finding, kind: "userjs-changed" }], was, ownCurrent).length,
  none: Guard.withoutOwnValues([finding]).length,
};
// What the record's field may hold: plain values by name, nothing else (a record is read from the profile).
out.ownedValues = [
  Guard.ownedValues({ [OVERRIDES]: CURRENT, a: 1, b: true, c: null, d: {}, e: [] }),
  Guard.ownedValues([CURRENT]),
  Guard.ownedValues("x"),
  Guard.ownedValues(null),
];
console.log(JSON.stringify(out));
