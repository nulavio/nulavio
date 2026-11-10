// The waitlist of nulavio.net: the only code of the site that runs on a server. Cloudflare
// Pages calls it for /api/* only (_routes.json); every other path is a static file and never
// reaches it. No page loads this file: the site still has no client-side script.
//
// POST /api/waitlist, from the forms of the landing and of /lista/ and /en/waitlist/:
//   email, lang (pt-BR | en), platform (optional), action (join | leave), hp (must stay empty)
//
// It keeps the address, the language, the platform and the time in the D1 database bound as
// WAITLIST, and nothing else: no IP address, no user agent. Joining twice, or leaving with an
// address that is not on the list, answers exactly like the first time, so the form does not
// tell anyone who is on the list. The answer is always a redirect to the waitlist page, whose
// fragment chooses the message (#ok, #left, #invalid, #unavailable).

const PAGES = { "pt-BR": "/lista/", en: "/en/waitlist/" };
const PLATFORMS = new Set(["", "fedora", "ubuntu", "arch", "linux-other", "windows", "macos"]);
const MAX_BODY = 2048; // bytes; the form sends well under 400
const EMAIL = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

// NOCASE: the address is kept as typed, and A@b.example and a@b.example are one sign-up.
const SCHEMA =
  "CREATE TABLE IF NOT EXISTS waitlist (email TEXT PRIMARY KEY COLLATE NOCASE, lang TEXT NOT NULL, platform TEXT NOT NULL, joined TEXT NOT NULL)";
// A second sign-up keeps the first date (the place in line) and a platform already given.
const JOIN =
  "INSERT INTO waitlist (email, lang, platform, joined) VALUES (?1, ?2, ?3, ?4) ON CONFLICT (email) DO UPDATE SET lang = excluded.lang, platform = CASE WHEN excluded.platform = '' THEN waitlist.platform ELSE excluded.platform END";
const LEAVE = "DELETE FROM waitlist WHERE email = ?1";

// _headers does not apply to what a function answers, so the answers carry their own.
const HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};

function redirect(lang, state) {
  return new Response(null, { status: 303, headers: { ...HEADERS, Location: `${PAGES[lang]}#${state}` } });
}

function refuse(status, text, extra = {}) {
  return new Response(text, { status, headers: { ...HEADERS, "Content-Type": "text/plain; charset=utf-8", ...extra } });
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

async function waitlist(request, env) {
  if (request.method !== "POST") return refuse(405, "POST only\n", { Allow: "POST" });
  // Browsers say where a form was sent from. Another site's form is refused; a client that
  // does not send the header (an older browser) is let through.
  const site = request.headers.get("Sec-Fetch-Site");
  if (site && site !== "same-origin") return refuse(403, "Cross-site requests are refused\n");
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/x-www-form-urlencoded")) {
    return refuse(415, "Send the form as application/x-www-form-urlencoded\n");
  }
  const body = await readBody(request);
  if (body === null) return refuse(413, "Too large\n");

  const form = new URLSearchParams(body);
  const lang = Object.hasOwn(PAGES, form.get("lang")) ? form.get("lang") : "pt-BR";
  const leaving = form.get("action") === "leave";
  // A filled honeypot is a bot: answer as if it had worked, keep nothing.
  if (form.get("hp")) return redirect(lang, leaving ? "left" : "ok");

  const email = (form.get("email") ?? "").trim();
  if (email.length > 254 || !EMAIL.test(email)) return redirect(lang, "invalid");
  const platform = PLATFORMS.has(form.get("platform") ?? "") ? (form.get("platform") ?? "") : "";

  const db = env.WAITLIST;
  if (!db) return redirect(lang, "unavailable");
  try {
    if (leaving) {
      await db.batch([db.prepare(SCHEMA), db.prepare(LEAVE).bind(email)]);
      return redirect(lang, "left");
    }
    const joined = new Date().toISOString().slice(0, 19) + "Z";
    await db.batch([db.prepare(SCHEMA), db.prepare(JOIN).bind(email, lang, platform, joined)]);
    return redirect(lang, "ok");
  } catch {
    return redirect(lang, "unavailable");
  }
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname === "/api/waitlist") return waitlist(request, env);
    // _routes.json sends only /api/* here. Should that ever stop holding, the pages are still served.
    return env.ASSETS ? env.ASSETS.fetch(request) : refuse(404, "Not found\n");
  },
};
