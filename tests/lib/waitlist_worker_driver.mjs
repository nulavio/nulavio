// Runs site/_worker.js (the waitlist of nulavio.net) against a recording stand-in for the D1
// database and prints, as JSON, what it answered and which statements it sent. Used by
// tests/unit/test_site.py, which replays the statements in SQLite (D1 is SQLite).
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

function post(fields, { headers = {}, method = "POST", path = "/api/waitlist", body } = {}) {
  return new Request(`https://nulavio.net${path}`, {
    method,
    headers: method === "POST" ? { "Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin", ...headers } : headers,
    body: method === "POST" ? (body ?? new URLSearchParams(fields).toString()) : undefined,
  });
}

const cases = {
  join: [post({ email: "Ana@Example.org", lang: "pt-BR", platform: "fedora", hp: "" })],
  join_again_other_case: [post({ email: "ana@example.org", lang: "en", platform: "" })],
  join_unknown_platform: [post({ email: "bruno@example.org", lang: "en", platform: "'; DROP TABLE waitlist; --" })],
  leave: [post({ email: "ANA@example.org", lang: "en", action: "leave" })],
  leave_absent: [post({ email: "nobody@example.org", lang: "pt-BR", action: "leave" })],
  invalid_email: [post({ email: "not an address", lang: "en" })],
  no_dot_in_domain: [post({ email: "ana@localhost", lang: "pt-BR" })],
  too_long_email: [post({ email: `${"a".repeat(250)}@example.org`, lang: "pt-BR" })],
  honeypot: [post({ email: "bot@example.org", lang: "en", hp: "https://spam.example" })],
  unknown_lang: [post({ email: "carla@example.org", lang: "../../evil" })],
  cross_site: [post({ email: "ana@example.org", lang: "en" }, { headers: { "Sec-Fetch-Site": "cross-site" } })],
  no_fetch_metadata: [post({ email: "dora@example.org", lang: "en" }, { headers: { "Sec-Fetch-Site": "" } })],
  wrong_content_type: [post({}, { headers: { "Content-Type": "application/json" }, body: '{"email":"ana@example.org"}' })],
  too_large: [post({}, { body: `email=ana@example.org&pad=${"x".repeat(4096)}` })],
  get: [post({}, { method: "GET" })],
  no_database: [post({ email: "ana@example.org", lang: "en" }), {}],
  database_down: [post({ email: "ana@example.org", lang: "pt-BR" }), { WAITLIST: recorder({ failing: true }) }],
  other_api_path: [post({}, { method: "GET", path: "/api/other" }), { ASSETS: { fetch: async () => new Response("the 404 page", { status: 404 }) } }],
};

const database = recorder();
const results = {};
for (const [name, [request, env]] of Object.entries(cases)) {
  const before = database.statements.length;
  // An empty header value means "this client does not send it".
  if (request.headers.get("Sec-Fetch-Site") === "") request.headers.delete("Sec-Fetch-Site");
  const response = await worker.fetch(request, env ?? { WAITLIST: database });
  results[name] = {
    status: response.status,
    location: response.headers.get("Location"),
    headers: Object.fromEntries(response.headers),
    body: await response.text(),
    statements: env ? [] : database.statements.slice(before),
  };
}
console.log(JSON.stringify(results));
