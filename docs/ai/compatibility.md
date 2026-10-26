# AI and automation compatibility matrix

Checked on 2026-10-26 on Fedora 44 KDE (Wayland), engine Gecko 158.0.1 (Nulavio build, Track B) and distribution Firefox 158.0.1 (Track A). Each cell says what is **documented** by the project, **implemented** in Nulavio, and **tested** here. Labels: SUPPORTED (tested end to end), PARTIAL (works with stated gaps), EXPERIMENTAL, UNSUPPORTED, UNTESTED.

## Ways to drive the browser

| Path | Documented | In Nulavio | Tested here | Label | Notes |
|---|---|---|---|---|---|
| **Nulavio MCP** (`nulavio ai serve`, stdio) | [ADR 0007](../adr/0007-ai-bridge.md) | Yes: 11 tools, policy per call, audit | 40 unit + 13 engine tests on both engines; real Claude Code | **SUPPORTED** | Protocol 2026-07-28 (modern) and 2025-11-25 / 2025-06-18 / 2025-03-26 (legacy `initialize`) |
| WebDriver BiDi (engine Remote Agent) | [Firefox remote docs](https://firefox-source-docs.mozilla.org/remote/) | Used internally by the bridge | Yes, through the bridge | SUPPORTED (internal) | Exposing it to agents directly ("raw automation") is A13: it bypasses per-call policy and must be enabled explicitly |
| Marionette (WebDriver classic) | [Firefox remote docs](https://firefox-source-docs.mozilla.org/remote/) | Test harness only | Yes (test suites) | UNSUPPORTED for agents | Can run privileged (chrome) scripts; never offered to agents |
| Mozilla firefox-devtools-mcp | [README](https://github.com/mozilla/firefox-devtools-mcp) | No | No | UNTESTED | Node.js; Selenium/WebDriver BiDi; launches or attaches to Firefox. Its default `basic` preset includes `evaluate_script`. Would run outside Nulavio's policy and audit; if a user points it at an AI Workspace, Safe Browsing and other protections depend on that tool's prefs |
| Chrome DevTools Protocol (CDP) | [Removed in Firefox 141](https://fxdx.dev/cdp-retirement-in-firefox/) | No | — | UNSUPPORTED | Not in the engine anymore; WebDriver BiDi is the replacement |
| Playwright | [Browsers page](https://playwright.dev/docs/browsers): "doesn't work with the branded version of Firefox since it relies on patches" | No | No | UNSUPPORTED (Gecko) | Playwright ships its own patched Firefox; it cannot drive Nulavio. Chrome-only integrations are not made compatible by MCP |
| Puppeteer | [Firefox via WebDriver BiDi since Puppeteer 23](https://hacks.mozilla.org/2024/08/puppeteer-support-for-firefox/) | No | No | UNTESTED | Would work against an engine started with the Remote Agent (raw mode, A13) |
| Selenium | WebDriver BiDi and classic via geckodriver; [CDP for Firefox removed in 4.29](https://www.selenium.dev/blog/2025/remove-cdp-firefox/) | No | No | UNTESTED | Same as Puppeteer |

## MCP clients

| Client | Version | Documented config | Tested | Label | Notes |
|---|---|---|---|---|---|
| Claude Code | 2.1.308 | [MCP docs](https://code.claude.com/docs/en/mcp): `--mcp-config`, `.mcp.json`, `claude mcp add` | **Yes**: `claude -p --model haiku --mcp-config … --strict-mcp-config --restricted --no-session-persistence`. The agent opened the fixture, read the code word, typed and submitted the form (server saw `/agent-result?q=hello`), `evaluate` was denied by policy, and it reported the page's injected instruction instead of following it. 20 s, US$ 0.003 | **SUPPORTED** | Legacy `initialize` handshake; tools appear as `mcp__nulavio__*`; permission at the client: `--allowedTools mcp__nulavio` |
| Codex CLI | 0.164.0 | [MCP docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli): `[mcp_servers.<name>]`, `codex mcp add`, `-c` overrides | Attempted with `codex exec --ephemeral --ignore-user-config -c mcp_servers.nulavio…`; the run stopped before any tool call: the ChatGPT account had hit its usage limit | UNTESTED (blocked by quota) | Opt-in test ready: `NULAVIO_AGENT_TESTS=1` `tests/integration/test_ai_agents_real.py` |
| Claude Desktop | — | MCP via its config file | No (not installed) | UNTESTED | |
| Codex Desktop | — | — | No (not installed) | UNTESTED | |
| Other MCP clients | — | Standard stdio | Python test client (legacy and 2026-07-28 modern) | SUPPORTED (protocol) | `server/discover`, `_meta`, `UnsupportedProtocolVersion` (-32022) |

## Features through the Nulavio MCP

| Feature | Tool | Label | Notes |
|---|---|---|---|
| List, open, close tabs | `tabs_list`, `tab_new`, `tab_close` | SUPPORTED | Tab ids are BiDi browsing-context ids |
| Navigation and waiting | `navigate` (waits for `complete`); `click`/`type` wait for a navigation they start | SUPPORTED | Uses `browsingContext.navigationStarted`/`load` events |
| Read page text | `page_read` | SUPPORTED | `innerText`, size-limited, marked untrusted |
| DOM / accessibility snapshot | `page_snapshot` | PARTIAL | Interactive elements with role and name computed from the DOM (labels, ARIA, text), not the platform accessibility tree. Password values never returned |
| Screenshots | `screenshot` | SUPPORTED | Viewport PNG |
| Click, type, submit | `click`, `type` | SUPPORTED | Real input events (`input.performActions`); submit and link clicks checked against their capabilities |
| JavaScript | `evaluate` | SUPPORTED (when granted) | Blocked below Full control unless granted |
| Upload, download | — | UNSUPPORTED (S7) | Capability `files` reserved |
| Network, console, debugging | — | UNSUPPORTED (A13) | Capabilities reserved |
| Windows management, long tasks, task cancellation | — | PARTIAL | Each call can be cancelled (`notifications/cancelled`); task handles in S7 |
| Several agents at once | — | SUPPORTED | One workspace per agent; tested with two agents concurrently |
| Real profiles (Personal, Work, …) | — | UNSUPPORTED (S8) | |

## Platforms

| Platform | Label | Notes |
|---|---|---|
| Fedora 44 KDE (Wayland), Nulavio build | SUPPORTED | All tests above |
| Fedora / Ubuntu with distribution Firefox (Track A) | SUPPORTED | Engine tests pass on distribution Firefox 158.0.1 here; CI runs them in Fedora and Ubuntu containers |
| Windows | UNTESTED | stdio works the same; workspace launch, paths and the approval prompt need a Windows port |
