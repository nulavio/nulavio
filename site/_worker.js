// The waitlist of nulavio.net: the only code of the site that runs on a server. Cloudflare
// Pages calls it for /api/* and for the two link pages only (_routes.json); every other path
// is a static file and never reaches it. No page loads this file: the site still has no
// client-side script.
//
// POST /api/waitlist, from the forms of the landing and of /lista/ and /en/waitlist/:
//   email, lang (pt-BR | en), platform (optional), hp (must stay empty)
// The answer is a redirect to the link page of that language with a new key in its address
// (/lista/link/?k=…, /en/waitlist/link/?k=…). The key is the proof that a sign-up is yours:
// knowing an address is not. Only its SHA-256 is kept, and only for an address that was not
// on the list: signing up an address again changes nothing about its entry and hands out a
// key that opens nothing, so nobody gets a key to an entry that exists. The answer is the
// same either way (status, headers, body, and one write to the database whatever was found),
// so the form does not tell anyone who is on the list.
//
// GET /lista/link/?k=…  the static page of that path, the same for every key (the list is
//                       not looked at: the page says nothing about an entry).
// POST (the page's own form, which has no action and so posts to its own address): deletes
//                       the entry that key belongs to, if any, and answers the same either way.
//
// It keeps the address, the language, the platform and the time in the D1 database bound as
// WAITLIST, plus the hash of the key, and nothing else about anyone: no IP address, no user
// agent (waitlist_pulse holds one random number, see PULSE). Every
// other answer is a redirect to the waitlist page, whose fragment chooses the message
// (#left, #invalid, #unavailable, #nolink) or the section (#leave).

const PAGES = { "pt-BR": "/lista/", en: "/en/waitlist/" };
const LINKS = { "pt-BR": "/lista/link/", en: "/en/waitlist/link/" };
const PLATFORMS = new Set(["", "fedora", "ubuntu", "arch", "linux-other", "windows", "macos"]);
const MAX_BODY = 2048; // bytes; the form sends well under 400
const EMAIL = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;
const KEY = /^[A-Za-z0-9_-]{43}$/; // 32 random bytes, base64url

// NOCASE: the address is kept as typed, and A@b.example and a@b.example are one sign-up.
const SCHEMA =
  "CREATE TABLE IF NOT EXISTS waitlist (email TEXT PRIMARY KEY COLLATE NOCASE, lang TEXT NOT NULL, platform TEXT NOT NULL, joined TEXT NOT NULL)";
// A table of its own, so that a list made before links existed needs no migration; its
// entries have no row here, and so no link opens them.
const SCHEMA_LINKS = "CREATE TABLE IF NOT EXISTS waitlist_links (email TEXT PRIMARY KEY COLLATE NOCASE, link TEXT NOT NULL)";
// Runs before JOIN, in the same batch (one transaction): the hash is recorded only when the
// address is not on the list yet. OR REPLACE: a row left behind by an entry removed by hand.
const LINK =
  "INSERT OR REPLACE INTO waitlist_links (email, link) SELECT ?1, ?2 WHERE NOT EXISTS (SELECT 1 FROM waitlist WHERE email = ?1)";
// A second sign-up changes nothing: not the date (the place in line), not the language, not the platform.
const JOIN = "INSERT INTO waitlist (email, lang, platform, joined) VALUES (?1, ?2, ?3, ?4) ON CONFLICT (email) DO NOTHING";
const LEAVE = "DELETE FROM waitlist WHERE email IN (SELECT email FROM waitlist_links WHERE link = ?1)";
const UNLINK = "DELETE FROM waitlist_links WHERE link = ?1";
// One row that every sign-up and every leaving rewrites with a new random number, whatever
// else they found to do. Without it a request that changes nothing answers measurably sooner
// than one that does, which tells an address on the list from one that is not.
const SCHEMA_PULSE = "CREATE TABLE IF NOT EXISTS waitlist_pulse (id INTEGER PRIMARY KEY CHECK (id = 1), n TEXT NOT NULL)";
const PULSE = "INSERT OR REPLACE INTO waitlist_pulse (id, n) VALUES (1, ?1)";

// _headers does not apply to what a function answers, so the answers carry their own.
const HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};
// The link page is a page of the site: the headers of _headers (tests compare them), never
// stored and never indexed, since its address is a key.
const PAGE_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy":
    "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Strict-Transport-Security": "max-age=15552000; includeSubDomains",
  "X-Robots-Tag": "noindex",
  "Content-Type": "text/html; charset=utf-8",
};

function redirect(lang, state) {
  return new Response(null, { status: 303, headers: { ...HEADERS, Location: `${PAGES[lang]}#${state}` } });
}

function linked(lang, key) {
  return new Response(null, { status: 303, headers: { ...HEADERS, Location: `${LINKS[lang]}?k=${key}` } });
}

function refuse(status, text, extra = {}) {
  return new Response(text, { status, headers: { ...HEADERS, "Content-Type": "text/plain; charset=utf-8", ...extra } });
}

function newKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

// What is kept of a key. The key has 256 random bits, so a plain hash is enough.
async function digest(key) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key));
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

// The body, or null when it is larger than MAX_BODY (read in pieces, so a large one is never held).
async function readBody(request) {
  if (Number(request.headers.get("Content-Length") ?? 0) > MAX_BODY) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return new Blob(chunks).text();
}

// The fields of a posted form, or the answer that refuses it.
async function posted(request) {
  // Browsers say where a form was sent from. Another site's form is refused; a client that
  // does not send the header (an older browser) is let through.
  const site = request.headers.get("Sec-Fetch-Site");
  if (site && site !== "same-origin") return refuse(403, "Cross-site requests are refused\n");
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/x-www-form-urlencoded")) {
    return refuse(415, "Send the form as application/x-www-form-urlencoded\n");
  }
  const body = await readBody(request);
  if (body === null) return refuse(413, "Too large\n");
  return new URLSearchParams(body);
}

async function waitlist(request, env) {
  if (request.method !== "POST") return refuse(405, "POST only\n", { Allow: "POST" });
  const form = await posted(request);
  if (form instanceof Response) return form;

  const lang = Object.hasOwn(PAGES, form.get("lang")) ? form.get("lang") : "pt-BR";
  // Leaving by address is gone (it asked for no proof): the page says how to leave.
  if (form.get("action") === "leave") return redirect(lang, "leave");
  // A filled honeypot is a bot: answer as if it had worked, keep nothing.
  if (form.get("hp")) return linked(lang, newKey());

  const email = (form.get("email") ?? "").trim();
  if (email.length > 254 || !EMAIL.test(email)) return redirect(lang, "invalid");
  const platform = PLATFORMS.has(form.get("platform") ?? "") ? (form.get("platform") ?? "") : "";

  const db = env.WAITLIST;
  if (!db) return redirect(lang, "unavailable");
  try {
    const key = newKey();
    const joined = new Date().toISOString().slice(0, 19) + "Z";
    await db.batch([
      db.prepare(SCHEMA),
      db.prepare(SCHEMA_LINKS),
      db.prepare(SCHEMA_PULSE),
      db.prepare(LINK).bind(email, await digest(key)),
      db.prepare(JOIN).bind(email, lang, platform, joined),
      db.prepare(PULSE).bind(newKey()),
    ]);
    return linked(lang, key);
  } catch {
    return redirect(lang, "unavailable");
  }
}

async function link(request, env, url, lang) {
  const key = url.searchParams.get("k") ?? "";
  if (request.method === "GET" || request.method === "HEAD") {
    if (!KEY.test(key)) return redirect(lang, "nolink");
    // The static page of this path, asked for without the key: it is the same for everyone.
    let page = null;
    try {
      page = await env.ASSETS.fetch(new Request(new URL(url.pathname, url), { method: request.method }));
    } catch {
      // no static files, or they failed: answered below
    }
    if (!page?.ok) return refuse(503, "This page could not be loaded. Its address is still your link: try again later.\n");
    return new Response(page.body, { status: 200, headers: PAGE_HEADERS });
  }
  if (request.method !== "POST") return refuse(405, "GET or POST\n", { Allow: "GET, HEAD, POST" });
  const form = await posted(request);
  if (form instanceof Response) return form;
  if (!KEY.test(key)) return redirect(lang, "nolink");

  const db = env.WAITLIST;
  if (!db) return redirect(lang, "unavailable");
  try {
    const hash = await digest(key);
    await db.batch([
      db.prepare(SCHEMA),
      db.prepare(SCHEMA_LINKS),
      db.prepare(SCHEMA_PULSE),
      db.prepare(LEAVE).bind(hash),
      db.prepare(UNLINK).bind(hash),
      db.prepare(PULSE).bind(newKey()),
    ]);
    return redirect(lang, "left");
  } catch {
    return redirect(lang, "unavailable");
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/waitlist") return waitlist(request, env);
    for (const [lang, path] of Object.entries(LINKS)) {
      if (url.pathname === path) return link(request, env, url, lang);
      // The same path without its last slash (a rule of _routes.json matches both): sent to the
      // page's own address here, so that a key never goes to the static files.
      if (`${url.pathname}/` === path) {
        const key = url.searchParams.get("k") ?? "";
        return new Response(null, { status: 308, headers: { ...HEADERS, Location: KEY.test(key) ? `${path}?k=${key}` : path } });
      }
    }
    // _routes.json sends only /api/* and the link pages here. Should that ever stop holding, the pages are still served.
    return env.ASSETS ? env.ASSETS.fetch(request) : refuse(404, "Not found\n");
  },
};
