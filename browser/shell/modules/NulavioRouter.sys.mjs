/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Smart Profile Routing: the decision engine (docs/adr/0003-nulavio-profiles-and-routing.md).

   Pure functions: no state, no I/O, no network. Given a URL and the user's
   rules, say whether it stays in this profile, opens in another one, or asks.
   Rules are only ever created by the user; nothing here infers one.

   Precedence: explicit choice > exact host rule > registrable-domain rule >
   profile policy (M4a: stay) > stay. Hosts are compared in their ASCII form
   (IDN to punycode, lower case, no trailing dot); the registrable domain comes
   from the engine's Public Suffix List. IP addresses match host rules only. */

/** Rules (JSON array), shared by every profile of the group. */
export const RULES_PREF = "nulavio.routing.rules";
/** Global switch, shared by every profile of the group (default on; no rules means no effect). */
export const ENABLED_PREF = "nulavio.routing.enabled";
/** Marks a command line sent by routing or by an explicit choice: it is never routed again. */
export const ROUTED_FLAG = "nulavio-routed";
/** Opt-in, shared by the group: rules also apply to links clicked in pages (M5). Default off. */
export const IN_PAGE_PREF = "nulavio.routing.inPage";

export const MATCHES = Object.freeze(["host", "domain"]);
export const ACTIONS = Object.freeze(["open-in", "ask", "stay"]);
export const MAX_RULES = 500;
const ROUTABLE_SCHEMES = new Set(["http", "https"]);
const URL_FLAGS = new Set(["url", "new-tab", "new-window"]);

export class RoutingError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "RoutingError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new RoutingError(code, message);
}

function isIPLiteral(host) {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(":");
}

function toURI(input) {
  if (input instanceof Ci.nsIURI) {
    return input;
  }
  let text = String(input ?? "").trim();
  if (!text || text.length > 2048 || /[\s\u0000-\u001f\u007f]/.test(text)) {
    fail("invalid-site");
  }
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    text = `https://${text}`; // a bare host typed by the user
  }
  try {
    return Services.io.newURI(text);
  } catch {
    fail("invalid-site");
  }
  return null;
}

/**
 * The host as rules see it.
 *
 * @param {string|nsIURI} input - A URL, or a host typed by the user.
 * @returns {{host: string, registrable: ?string, isIP: boolean, display: string}}
 */
export function normalizeHost(input) {
  const uri = toURI(input);
  let host;
  try {
    host = uri.asciiHost.toLowerCase().replace(/\.+$/, "");
  } catch {
    fail("invalid-site");
  }
  if (!host) {
    fail("invalid-site");
  }
  const isIP = isIPLiteral(host);
  let registrable = null;
  if (!isIP) {
    try {
      registrable = Services.eTLD.getBaseDomainFromHost(host);
    } catch {
      registrable = null; // a public suffix itself, "localhost", or a single label
    }
  }
  let display = host;
  try {
    display = Services.io.newURI(`https://${host}/`).displayHost;
  } catch {}
  return { host, registrable, isIP, display };
}

/**
 * Check and normalise a rule the user is creating.
 *
 * @param {object} input
 * @param {string} input.site - URL or host.
 * @param {"host"|"domain"} input.match - This exact host, or its whole registrable domain.
 * @param {"open-in"|"ask"|"stay"} input.action
 * @param {?number} input.profileId - Target profile (open-in, ask).
 * @returns {{match, value, action, profileId}}
 */
export function validateRule({ site, match, action, profileId = null }) {
  if (!MATCHES.includes(match)) {
    fail("invalid-match");
  }
  if (!ACTIONS.includes(action)) {
    fail("invalid-action");
  }
  const { host, registrable, isIP } = normalizeHost(site);
  let value = host;
  if (match === "domain") {
    if (isIP || !registrable) {
      fail("no-domain"); // IP addresses, localhost and public suffixes need a host rule
    }
    value = registrable;
  }
  if (action !== "stay" && !(Number.isInteger(profileId) && profileId > 0)) {
    fail("invalid-profile");
  }
  return { match, value, action, profileId: action === "stay" ? null : profileId };
}

/** Rules from the stored JSON; malformed entries are dropped, never guessed. */
export function parseRules(text) {
  let list;
  try {
    list = JSON.parse(text || "[]");
  } catch {
    return [];
  }
  if (!Array.isArray(list)) {
    return [];
  }
  const rules = [];
  for (const r of list.slice(0, MAX_RULES)) {
    if (
      r &&
      typeof r.id === "string" &&
      MATCHES.includes(r.match) &&
      typeof r.value === "string" &&
      /^[a-z0-9.:_-]{1,253}$/.test(r.value) &&
      ACTIONS.includes(r.action) &&
      (r.action === "stay" || (Number.isInteger(r.profileId) && r.profileId > 0))
    ) {
      rules.push({ id: r.id, match: r.match, value: r.value, action: r.action, profileId: r.profileId ?? null });
    }
  }
  return rules;
}

function stay(reason, rule = null) {
  return { action: "stay", profileId: null, ruleId: rule?.id ?? null, reason };
}

/**
 * Where a navigation should happen.
 *
 * @param {object} input
 * @param {string} input.url
 * @param {Array} input.rules - parseRules() output.
 * @param {boolean} [input.enabled=true]
 * @param {?number} [input.currentProfileId] - This instance's profile, when known.
 * @param {boolean} [input.isPrivate=false] - Private windows never switch (M4a).
 * @param {?number} [input.explicitProfileId] - The user's explicit choice for this navigation.
 * @returns {{action: "stay"|"open-in"|"ask", profileId: ?number, ruleId: ?string, reason: string}}
 */
export function decide({ url, rules, enabled = true, currentProfileId = null, isPrivate = false, explicitProfileId = null }) {
  if (!enabled) {
    return stay("disabled");
  }
  let uri;
  try {
    uri = Services.io.newURI(url);
  } catch {
    return stay("invalid-url");
  }
  if (!ROUTABLE_SCHEMES.has(uri.scheme)) {
    return stay("scheme"); // javascript:, data:, blob:, file:, about:, moz-extension: ... never move
  }
  if (Number.isInteger(explicitProfileId)) {
    return explicitProfileId === currentProfileId
      ? stay("explicit")
      : { action: "open-in", profileId: explicitProfileId, ruleId: null, reason: "explicit" };
  }
  if (isPrivate) {
    return stay("private");
  }
  let target;
  try {
    target = normalizeHost(uri);
  } catch {
    return stay("no-host");
  }
  const rule =
    rules.find(r => r.match === "host" && r.value === target.host) ??
    (target.registrable ? rules.find(r => r.match === "domain" && r.value === target.registrable) : undefined);
  if (!rule) {
    return stay("no-rule"); // the profile policy for M4a is to stay
  }
  if (rule.action === "stay") {
    return stay("rule", rule);
  }
  if (rule.profileId === currentProfileId) {
    return stay("already-here", rule);
  }
  return { action: rule.action, profileId: rule.profileId, ruleId: rule.id, reason: rule.match };
}

/**
 * Whether a navigation that a web page started may be routed at all (M5,
 * docs/security/routing-m5-review.md). Takes the engine's facts about the load;
 * returns null when rules may apply, otherwise why it always loads here.
 *
 * @param {object} facts
 * @param {boolean} facts.isPrivate
 * @param {string} facts.method - The request method.
 * @param {boolean} facts.isFormSubmission
 * @param {boolean} facts.isMetaRefresh
 * @param {boolean} facts.userGesture - The page had a valid user gesture when it navigated.
 * @param {boolean} facts.topLevel - The load replaces a top-level page (a tab), not a frame.
 * @param {boolean} facts.fromTopPage - Started by the top-level page itself, not by a frame in it.
 * @param {boolean} facts.hasOpener - The target is a pop-up its opener can still script.
 * @param {boolean} facts.sameSite - Source page and target share a registrable domain (or host).
 * @returns {?string}
 */
export function pageNavigationRefusal(facts) {
  if (facts.isPrivate) {
    return "private";
  }
  if (facts.method !== "GET") {
    return "method";
  }
  if (facts.isFormSubmission) {
    return "form";
  }
  if (facts.isMetaRefresh || !facts.userGesture) {
    return "no-gesture";
  }
  if (!facts.topLevel || !facts.fromTopPage) {
    return "frame";
  }
  if (facts.hasOpener) {
    return "opener";
  }
  if (facts.sameSite) {
    return "same-site";
  }
  return null;
}

/** The registrable domain of a URL, or its host where there is none (IP addresses, localhost). */
export function siteOf(input) {
  const { host, registrable } = normalizeHost(input);
  return registrable ?? host;
}

/**
 * Which arguments of a command line are URLs that routing may move.
 *
 * Only plain forms are routed: bare URLs, `-url`, `-new-tab` and
 * `-new-window`. Any other flag (private windows, search, kiosk,
 * screenshots, files, ...) means the whole command line is left alone.
 *
 * @param {string[]} args
 * @returns {{supported: boolean, items: Array<{start: number, end: number, value: string}>}}
 */
export function parseCommandLine(args) {
  const items = [];
  for (let i = 0; i < args.length; i++) {
    const arg = String(args[i]);
    if (arg.startsWith("-")) {
      const flag = arg.replace(/^-{1,2}/, "").toLowerCase();
      if (URL_FLAGS.has(flag) && i + 1 < args.length && !String(args[i + 1]).startsWith("-")) {
        items.push({ start: i, end: i + 1, value: String(args[i + 1]) });
        i++;
        continue;
      }
      return { supported: false, items: [] };
    }
    items.push({ start: i, end: i, value: arg });
  }
  return { supported: true, items };
}
