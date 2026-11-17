/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Web services used on a click for translation (#156). Page summaries (#154) were built and moved to After 1.0 by the
   maintainer's decision of 2026-11-17 (#453): the assistant already summarises a page.

   Translation stays on the device by default (the engine's own, unchanged). A web service is used only after the person adds it, only from a menu item that names it, and
   only on that click: the item opens the service's address, built here from a template, in a new tab. Nothing is
   fetched to build it and nothing is sent before the click. Private windows do not offer them unless the person
   turns that on.

   Every address Nulavio knows for these services is in this file (SERVICES), with where it was read and when. A
   person's own service is a template validated like a search template: https only, a host, no user name or
   password, and exactly the placeholders that kind of service takes. Nulavio has no partnership with any of them;
   they are listed by name, in alphabetical order, none preselected. Services' own extensions are not bundled. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
});

export const PREF_TRANSLATE = "nulavio.services.translate"; // JSON: the services added, in the order added
export const PREF_LANGUAGE = "nulavio.services.translate.language"; // "" follows the browser's language
export const PREF_PRIVATE = "nulavio.services.private"; // offered in private windows too
const MAX_TEMPLATE = 2048;
const MAX_TEXT = 5000; // a selection longer than this is cut: an address carries it
const MAX_ADDED = 12;

/* The services Nulavio knows by name. `selection` takes {text}, `page` takes {url}, both take {lang}. `account`: the service needs one. `instance`: the person types the address of their own (Nulavio
   never picks a public one, the rule of SearXNG). Read 2026-11-16:
   - DeepL, Kagi Translate: Kagi's public bang list, kagisearch/bangs at af28e0bd, data/bangs.json ("deepl", "kt"); Kagi Translate's `to` parameter and page path from
     help.kagi.com/kagi/translate/url-parameters.html.
   - Google Translate: its own address form (`sl`, `tl`, `text`, `op`; `/translate?u=` for a page).
   - LibreTranslate: its web page reads `source` and `target` from the query and the text from the fragment `#q=`,
     which is never sent to the server (LibreTranslate/LibreTranslate main, libretranslate/templates/app.js.template). */
export const SERVICES = Object.freeze({
  deepl: Object.freeze({
    name: "DeepL",
    selection: "https://www.deepl.com/translator#xx/{lang}/{text}",
    lang: "region",
  }),
  google: Object.freeze({
    name: "Google Translate",
    selection: "https://translate.google.com/?sl=auto&tl={lang}&text={text}&op=translate",
    page: "https://translate.google.com/translate?sl=auto&tl={lang}&u={url}",
    lang: "base",
  }),
  "kagi-translate": Object.freeze({
    name: "Kagi Translate",
    selection: "https://translate.kagi.com/?from=auto&to={lang}&text={text}",
    page: "https://translate.kagi.com/{url}?to={lang}",
    lang: "base",
    account: true,
  }),
  libretranslate: Object.freeze({
    name: "LibreTranslate",
    instance: "{base}?source=auto&target={lang}#q={text}",
    lang: "base",
  }),
});

/** The target languages offered besides the browser's own (BCP 47). */
export const LANGUAGES = Object.freeze(["pt-BR", "en-US", "es", "fr", "de", "it", "ja", "zh-CN"]);

export class ServicesError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "ServicesError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new ServicesError(code, message);
}

const PLACEHOLDERS = /\{(text|url|lang|base)\}/g;

/**
 * A service address typed by the person, for one kind: "selection" ({text}, optional {lang}) or "page" ({url},
 * optional {lang}). https only, a host, no user name or password, nothing else in braces.
 */
export function validateServiceTemplate(raw, kind) {
  const takes = { selection: "text", page: "url" }[kind] ?? fail("invalid-kind");
  if (typeof raw !== "string") {
    fail("invalid-url");
  }
  const template = raw.trim().replaceAll("%s", `{${takes}}`);
  if (!template || template.length > MAX_TEMPLATE || /[\s\u0000-\u001f\u007f]/.test(template)) {
    fail("invalid-url");
  }
  const used = [...template.matchAll(PLACEHOLDERS)].map(m => m[1]);
  if (!used.includes(takes)) {
    fail(takes === "text" ? "missing-text" : "missing-url");
  }
  if (used.some(name => name !== takes && name !== "lang")) {
    fail("bad-placeholder");
  }
  if (/[{}]/.test(template.replace(PLACEHOLDERS, ""))) {
    fail("bad-placeholder");
  }
  let url;
  try {
    url = new URL(template.replace(PLACEHOLDERS, "x"));
  } catch {
    fail("invalid-url");
  }
  if (url.username || url.password) {
    fail("credentials-in-url");
  }
  if (url.protocol !== "https:" || !url.hostname) {
    fail("service-needs-https");
  }
  if (!/^https:\/\/[^/?#{]+[/?#]/.test(`${template}/`)) {
    fail("invalid-url"); // the host itself is never built from the page
  }
  return template;
}

/** A LibreTranslate instance the person names: an https address with no query or fragment. */
export function validateInstance(raw) {
  if (typeof raw !== "string") {
    fail("invalid-url");
  }
  let url;
  try {
    url = new URL(raw.trim());
  } catch {
    fail("invalid-url");
  }
  if (url.username || url.password) {
    fail("credentials-in-url");
  }
  if (url.protocol !== "https:" || !url.hostname) {
    fail("service-needs-https");
  }
  if (url.search || url.hash) {
    fail("invalid-url");
  }
  url.pathname = url.pathname.replace(/\/?$/, "/");
  return url.href;
}

function normalizeName(raw) {
  const name = String(raw ?? "").trim().replace(/\s+/g, " ");
  if (!name || name.length > 60 || /[\u0000-\u001f\u007f]/.test(name)) {
    fail("invalid-name");
  }
  return name;
}

/**
 * Why a page's address may not go to a web service that fetches it, or null when it may: only public http(s)
 * addresses. Not `localhost`, not a loopback, private or link-local address, not `.local`, `.internal`, `.lan`,
 * `.home.arpa`, and not a host without a dot (an intranet name).
 */
export function refusedAddress(spec) {
  let url;
  try {
    url = new URL(spec);
  } catch {
    return "not-web";
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return "not-web";
  }
  if (url.username || url.password) {
    return "private-address";
  }
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase().replace(/\.$/, "");
  if (host === "localhost" || host.endsWith(".localhost")) {
    return "private-address";
  }
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return privateV4(a, b, Number(v4[3])) ? "private-address" : null;
  }
  if (host.includes(":")) {
    // IPv6: loopback, unspecified, unique local (fc00::/7), link-local (fe80::/10), old site-local (fec0::/10),
    // multicast (ff00::/8), documentation (2001:db8::/32), benchmarking (2001:2::/48), and every form that carries
    // an IPv4 address (mapped ::ffff:0:0/96, compatible ::/96, NAT64 64:ff9b::/96, 6to4 2002::/16, Teredo
    // 2001::/32): refused whole, since a service that fetches it may reach the address inside. The address is in
    // the URL parser's form (lower case, no leading zeros, the longest run of zeros as "::").
    if (host === "::1" || host === "::" || /^f[cdf]/.test(host) || /^fe[89a-f]/.test(host) || host.startsWith("::") ||
        host.startsWith("64:ff9b:") || host.startsWith("2002:") || /^2001:(db8|0|):/.test(host) || /^2001:2:(0)?:/.test(host)) {
      return "private-address";
    }
    return null;
  }
  if (!host.includes(".") || /\.(local|localdomain|internal|lan|home|box|router|intranet|corp|home\.arpa|arpa|onion|test|invalid|example)$/.test(host)) {
    return "private-address";
  }
  return null;
}

/** IPv4 addresses that are not on the public Internet: this-network, private, shared (CGNAT), loopback,
    link-local, IETF protocol assignments, documentation, benchmarking, multicast and reserved. */
function privateV4(a, b, c) {
  return (
    a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) || (a === 192 && b === 0 && (c === 0 || c === 2)) || (a === 198 && (b === 18 || b === 19)) ||
    (a === 198 && b === 51 && c === 100) || (a === 203 && b === 0 && c === 113)
  );
}

/** The target language for a service, from a BCP 47 tag: "region" keeps pt-BR and en-US, "base" takes "pt". */
function languageFor(tag, style) {
  const [base, region] = String(tag).split("-");
  if (style === "region" && (base === "pt" || base === "en") && region) {
    return `${base}-${region.toUpperCase()}`;
  }
  if (base === "zh" && region) {
    return `zh-${region.toUpperCase()}`;
  }
  return base.toLowerCase();
}

/** A page's or link's address as a service may get it: without its fragment, which never goes to the page's own
    server and may hold what the site keeps on this side (a decryption key, an access token). */
function withoutFragment(spec) {
  const url = new URL(spec);
  url.hash = "";
  return url.href;
}

function fill(template, values) {
  return template.replace(PLACEHOLDERS, (_, name) => (name === "base" ? values.base : encodeURIComponent(values[name] ?? "")));
}

class NulavioServicesClass {
  #listeners = new Set();
  #observing = false;

  // -- what the profile has ------------------------------------------------

  #readJSON(pref, fallback) {
    try {
      const raw = Services.prefs.getStringPref(pref, "");
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  /** The translation services added, each checked again on reading: a hand-edited entry that fails is dropped. */
  translators() {
    const added = this.#readJSON(PREF_TRANSLATE, []);
    const result = [];
    for (const entry of Array.isArray(added) ? added.slice(0, MAX_ADDED) : []) {
      try {
        result.push(this.#describe(entry));
      } catch {
        // not a service this module would have written
      }
    }
    return result;
  }

  #describe(entry) {
    if (typeof entry?.key === "string" && Object.hasOwn(SERVICES, entry.key)) {
      const service = SERVICES[entry.key];
      if (service.instance) {
        const base = validateInstance(entry.base);
        return { id: `${entry.key}:${base}`, key: entry.key, name: `${service.name} (${new URL(base).host})`, base,
                 selection: service.instance.replace("{base}", () => base), page: null, lang: service.lang, account: false };
      }
      if (!service.selection && !service.page) {
        fail("invalid-service");
      }
      return { id: entry.key, key: entry.key, name: service.name, selection: service.selection ?? null,
               page: service.page ?? null, lang: service.lang, account: Boolean(service.account) };
    }
    if (entry?.key === "custom") {
      const name = normalizeName(entry.name);
      const selection = entry.selection ? validateServiceTemplate(entry.selection, "selection") : null;
      const page = entry.page ? validateServiceTemplate(entry.page, "page") : null;
      if (!selection && !page) {
        fail("invalid-service");
      }
      return { id: `custom:${name}`, key: "custom", name, selection, page, lang: "region", account: false };
    }
    return fail("invalid-service");
  }

  /** The language translations go to: the setting, or the browser's own language. */
  language() {
    const chosen = Services.prefs.getStringPref(PREF_LANGUAGE, "");
    return LANGUAGES.includes(chosen) ? chosen : Services.locale.appLocaleAsBCP47;
  }

  state() {
    return {
      translators: this.translators(),
      language: Services.prefs.getStringPref(PREF_LANGUAGE, ""),
      browserLanguage: Services.locale.appLocaleAsBCP47,
      languages: [...LANGUAGES],
      privateToo: Services.prefs.getBoolPref(PREF_PRIVATE, false),
      known: Object.entries(SERVICES)
        .map(([key, s]) => ({ key, name: s.name, selection: Boolean(s.selection || s.instance), page: Boolean(s.page),
                              instance: Boolean(s.instance), account: Boolean(s.account) }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    };
  }

  // -- changing it -----------------------------------------------------------

  #writeTranslators(entries) {
    Services.prefs.setStringPref(PREF_TRANSLATE, JSON.stringify(entries));
  }

  /** Add a translation service: a known one by key, a LibreTranslate instance with its address, or one's own. */
  addTranslator({ key, base, name, selection, page } = {}) {
    let entry;
    if (key === "custom") {
      entry = { key, name, ...(selection ? { selection } : {}), ...(page ? { page } : {}) };
    } else if (typeof key === "string" && Object.hasOwn(SERVICES, key) && (SERVICES[key].selection || SERVICES[key].page)) {
      entry = { key };
    } else if (key === "libretranslate") {
      entry = { key, base };
    } else {
      fail("unknown-service");
    }
    const described = this.#describe(entry); // validates
    if (described.key === "custom") {
      entry = { key: "custom", name: described.name, ...(described.selection ? { selection: described.selection } : {}),
                ...(described.page ? { page: described.page } : {}) };
    } else if (described.base) {
      entry = { key: described.key, base: described.base };
    }
    const entries = this.#readJSON(PREF_TRANSLATE, []).filter(each => {
      try {
        return this.#describe(each).id !== described.id;
      } catch {
        return false;
      }
    });
    if (entries.length >= MAX_ADDED) {
      fail("too-many");
    }
    this.#writeTranslators([...entries, entry]);
    return described.id;
  }

  removeTranslator(id) {
    const entries = this.#readJSON(PREF_TRANSLATE, []);
    const kept = entries.filter(each => {
      try {
        return this.#describe(each).id !== id;
      } catch {
        return false;
      }
    });
    if (kept.length === entries.length) {
      fail("not-found");
    }
    this.#writeTranslators(kept);
  }

  setLanguage(tag) {
    if (tag !== "" && !LANGUAGES.includes(tag)) {
      fail("unknown-language");
    }
    Services.prefs.setStringPref(PREF_LANGUAGE, tag);
  }

  setPrivateToo(on) {
    Services.prefs.setBoolPref(PREF_PRIVATE, Boolean(on));
  }

  // -- the menus -------------------------------------------------------------

  /**
   * The items the page and selection menus offer now, for the background page to create: one per service and use,
   * named after the service. `sends` says what leaves the browser on the click.
   */
  menu() {
    const items = [];
    for (const t of this.translators()) {
      if (t.selection) {
        items.push({ id: `translate-selection|${t.id}`, use: "translate-selection", name: t.name, contexts: ["selection"], sends: "text" });
      }
      if (t.page) {
        items.push({ id: `translate-page|${t.id}`, use: "translate-page", name: t.name, contexts: ["page"], sends: "url" });
      }
    }
    return items;
  }

  /**
   * Whether an item may be used now, and why not: in a private window only when the person allowed it, and an
   * address a service would fetch only when it is public. `target` is what the click would send: the page's address,
   * or nothing for a selection.
   */
  check(itemId, { target = null, isPrivate = false } = {}) {
    const item = this.menu().find(each => each.id === itemId);
    if (!item) {
      return { usable: false, reason: "not-found" };
    }
    if (isPrivate && !Services.prefs.getBoolPref(PREF_PRIVATE, false)) {
      return { usable: false, reason: "off-in-private", hidden: true };
    }
    if (item.sends === "url") {
      const reason = refusedAddress(String(target ?? ""));
      if (reason) {
        return { usable: false, reason };
      }
    }
    return { usable: true, reason: null };
  }

  /**
   * The address an item opens for what was clicked on. Nothing is fetched here. `text`: the selection; `target`: the
   * page's address.
   */
  build(itemId, { text = "", target = "", isPrivate = false } = {}) {
    const verdict = this.check(itemId, { target, isPrivate });
    if (!verdict.usable) {
      fail(verdict.reason);
    }
    if (target) {
      target = withoutFragment(target); // checked public above, so a URL
    }
    const [use, id] = itemId.split("|");
    const lang = this.language();
    if (use === "translate-selection" || use === "translate-page") {
      const t = this.translators().find(each => each.id === id) ?? fail("not-found");
      const value = use === "translate-selection" ? { text: String(text).slice(0, MAX_TEXT).replace(/[\uD800-\uDBFF]$/, "").toWellFormed() } : { url: target };
      if (use === "translate-selection" && !value.text.trim()) {
        fail("nothing-selected");
      }
      // Kagi Translate's page path takes the address itself (its documented example is "/example.com"), not one
      // encoded value: the scheme is left out, the fragment was removed above, and the page's own "?" is encoded so
      // the query stays in the path. Other characters go as the page's address has them.
      const template = use === "translate-selection" ? t.selection : t.page;
      const address = t.key === "kagi-translate" && use === "translate-page"
        ? template
            .replace("{url}", () => target.replace(/^https?:\/\//, "").replace(/[?]/g, c => encodeURIComponent(c)))
            .replace("{lang}", () => encodeURIComponent(languageFor(lang, t.lang)))
        : fill(template, { ...value, lang: languageFor(lang, t.lang), base: t.base });
      return { open: address };
    }
    return fail("not-found");
  }

  /** Whether `browser` (a tab's) is private: the menus ask it on every click. */
  isPrivate(browser) {
    return lazy.PrivateBrowsingUtils.isBrowserPrivate(browser);
  }

  // -- change notifications --------------------------------------------------

  #observe() {
    if (this.#observing) {
      return;
    }
    this.#observing = true;
    for (const pref of [PREF_TRANSLATE, PREF_LANGUAGE, PREF_PRIVATE]) {
      Services.prefs.addObserver(pref, this);
    }
  }

  observe() {
    for (const listener of this.#listeners) {
      try {
        listener();
      } catch (e) {
        console.error(e);
      }
    }
  }

  subscribe(listener) {
    this.#observe();
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]);
}

export const NulavioServices = new NulavioServicesClass();
