// Runs site/_worker.js (the waitlist of nulavio.net) against a recording stand-in for the D1
// database and for the static files, and prints, as JSON, what it answered and which
// statements it sent. Used by tests/unit/test_site.py, which replays the statements in SQLite
// (D1 is SQLite).
//
//     node tests/lib/waitlist_worker_driver.mjs site/_worker.js

import { pathToFileURL } from "node:url";

const worker = (await import(pathToFileURL(process.argv[2]).href)).default;

function recorder({ failing = false } = {}) {
  const statements = [];
  const prepare = (sql) => ({ sql, args: [], bind: (...args) => ({ sql, args }) });
  return {
    statements,
    prepare,
    async batch(batch) {
      if (failing) throw new Error("D1 is down");
      for (const { sql, args } of batch) statements.push({ sql, args });
      return batch.map(() => ({ success: true }));
    },
  };
}

// The static files: the two link pages, and what was asked of them.
const asked = [];
const assets = {
  async fetch(request) {
    asked.push(`${request.method} ${request.url}`);
    const page = { "/lista/link/": "the link page, pt-BR", "/en/waitlist/link/": "the link page, en" }[new URL(request.url).pathname];
    return page ? new Response(request.method === "HEAD" ? null : page, { status: 200 }) : new Response("the 404 page", { status: 404 });
  },
};

function send(fields, { headers = {}, method = "POST", path = "/api/waitlist", body } = {}) {
  const posts = method !== "GET" && method !== "HEAD";
  return new Request(`https://nulavio.net${path}`, {
    method,
    headers: posts ? { "Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin", ...headers } : headers,
    body: posts ? (body ?? new URLSearchParams(fields).toString()) : undefined,
  });
}
const get = (path, method = "GET") => send({}, { method, path });
const unknown = `/en/waitlist/link/?k=${"A".repeat(43)}`; // well formed, nobody's

// name -> [request, env], or a function of the earlier results that returns them (a link comes from a sign-up's answer).
const cases = {
  join: [send({ email: "Ana@Example.org", lang: "pt-BR", platform: "fedora", hp: "" })],
  join_again_other_case: [send({ email: "ana@example.org", lang: "en", platform: "ubuntu" })],
  join_unknown_platform: [send({ email: "bruno@example.org", lang: "en", platform: "'; DROP TABLE waitlist; --" })],
  link_page: (r) => [get(r.join.location)],
  link_page_head: (r) => [get(r.join.location, "HEAD")],
  link_page_en: [get(unknown)],
  link_page_short_key: [get("/lista/link/?k=abc")],
  link_page_no_key: [get("/en/waitlist/link/")],
  link_page_no_files: (r) => [get(r.join.location), { WAITLIST: recorder() }],
  leave_by_address: [send({ email: "ANA@example.org", lang: "en", action: "leave" })],
  leave_with_the_second_link: (r) => [send({ hp: "" }, { path: r.join_again_other_case.location })],
  leave_unknown_link: [send({ hp: "" }, { path: unknown })],
  leave: (r) => [send({ hp: "" }, { path: r.join.location })],
  leave_short_key: [send({}, { path: "/lista/link/?k=abc" })],
  leave_honeypot: (r) => [send({ hp: "x" }, { path: r.join_unknown_platform.location })],
  leave_cross_site: (r) => [send({}, { path: r.join_unknown_platform.location, headers: { "Sec-Fetch-Site": "cross-site" } })],
  leave_wrong_content_type: (r) => [send({}, { path: r.join_unknown_platform.location, headers: { "Content-Type": "text/plain" }, body: "x" })],
  leave_too_large: (r) => [send({}, { path: r.join_unknown_platform.location, body: `pad=${"x".repeat(4096)}` })],
  leave_put: (r) => [send({}, { path: r.join_unknown_platform.location, method: "PUT" })],
  leave_no_database: (r) => [send({}, { path: r.join_unknown_platform.location }), { ASSETS: assets }],
  leave_database_down: (r) => [send({}, { path: r.join_unknown_platform.location }), { WAITLIST: recorder({ failing: true }) }],
  invalid_email: [send({ email: "not an address", lang: "en" })],
  no_dot_in_domain: [send({ email: "ana@localhost", lang: "pt-BR" })],
  too_long_email: [send({ email: `${"a".repeat(250)}@example.org`, lang: "pt-BR" })],
  honeypot: [send({ email: "bot@example.org", lang: "en", hp: "https://spam.example" })],
  unknown_lang: [send({ email: "carla@example.org", lang: "../../evil" })],
  cross_site: [send({ email: "ana@example.org", lang: "en" }, { headers: { "Sec-Fetch-Site": "cross-site" } })],
  no_fetch_metadata: [send({ email: "dora@example.org", lang: "en" }, { headers: { "Sec-Fetch-Site": "" } })],
  wrong_content_type: [send({}, { headers: { "Content-Type": "application/json" }, body: '{"email":"ana@example.org"}' })],
  too_large: [send({}, { body: `email=ana@example.org&pad=${"x".repeat(4096)}` })],
  get: [get("/api/waitlist")],
  no_database: [send({ email: "ana@example.org", lang: "en" }), {}],
  database_down: [send({ email: "ana@example.org", lang: "pt-BR" }), { WAITLIST: recorder({ failing: true }) }],
  other_api_path: [get("/api/other")],
};

const database = recorder();
const results = {};
for (const [name, made] of Object.entries(cases)) {
  const [request, env] = typeof made === "function" ? made(results) : made;
  const before = [database.statements.length, asked.length];
  // An empty header value means "this client does not send it".
  if (request.headers.get("Sec-Fetch-Site") === "") request.headers.delete("Sec-Fetch-Site");
  const response = await worker.fetch(request, env ?? { WAITLIST: database, ASSETS: assets });
  results[name] = {
    status: response.status,
    location: response.headers.get("Location"),
    headers: Object.fromEntries(response.headers),
    body: await response.text(),
    statements: env ? [] : database.statements.slice(before[0]),
    files: asked.slice(before[1]),
  };
}
console.log(JSON.stringify(results));
