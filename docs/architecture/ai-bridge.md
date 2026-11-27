# AI Bridge: agents, permissions and the AI Workspace

Decision: [ADR 0007](../adr/0007-ai-bridge.md). Threats: [threat model for automation](../security/threat-model-ai.md). What works with which tool: [compatibility matrix](../ai/compatibility.md). How to connect an agent: [guide](../ai/connect-an-agent.md).

## Components

| Component (brief) | Where | State (S4) |
|---|---|---|
| Nulavio AI Bridge (MCP server) | `ai/mcp.py`, `nulavio ai serve` | Done: stdio, dual-era (2025 `initialize` and 2026-07-28 `_meta`), tools only |
| Agent Registry | `ai/registry.py`, `$XDG_STATE_HOME/nulavio/ai/agents.json` (0600) | Done: id, client, autonomy, grants, site list, workspace kind, token hash, revocation |
| Agent Session Manager | one bridge process = one session id; session-bound grants; client evidence | Sessions end with the process ("for this session" = for this task in stdio); explicit task handles later |
| Permission & Autonomy Manager (Policy Decision Point) | `ai/policy.py`, `registry.decide` | Done: presets, grants (forever / minutes / session), site list, stop switch, revocation, pause; "ask" in the browser (KDE dialog as fallback) |
| Browser Automation Controller | `ai/tools.py` | Done: 11 tools with per-call checks |
| Gecko Adapter | `ai/bidi.py`, `ai/websocket.py`, `ai/workspace.py` | Done: WebDriver BiDi over a local WebSocket; AI Workspace launch with protections on |
| Profile Access Coordinator | `ai/workspace.ProfileTarget`, `tools.Bridge` (engines per profile, tab owners), `registry.set_profiles/set_routes` | Done (S8): given profiles, routes per agent, refusal of locked or open profiles |
| Activity & Audit Manager | `ai/audit.py`, `nulavio ai audit`, Settings → AI & Automation | Done: metadata only, 30-day retention, clear; shown in Settings |
| Compatibility Adapters | — | A13 (raw BiDi mode; Playwright/CDP only where feasible) |

## Trust boundaries and flow

```mermaid
flowchart LR
  subgraph User["User account (same Unix user)"]
    Agent["Agent process<br/>(Claude Code, Codex, …)"] -- "stdin/stdout JSON-RPC (MCP)" --> Bridge["nulavio ai serve<br/>MCP server + PDP"]
    Bridge -- "re-read on every call" --> Reg[("agents.json<br/>grants, STOP")]
    Bridge -- "metadata only" --> Audit[("audit.jsonl")]
    Bridge -- "WebDriver BiDi<br/>ws://127.0.0.1:random" --> WS["AI Workspace engine<br/>(own profile per agent)"]
    Bridge -. "ask" .-> Dialog["kdialog prompt<br/>(outside the browser)"]
    You["You: nulavio ai grant / revoke / stop<br/>(Shell UI in S7)"] --> Reg
  end
  WS -- "HTTPS (Safe Browsing, ETP, HTTPS-Only on)" --> Web((Web))
```

| Boundary | Crosses | Protection | Limit |
|---|---|---|---|
| AB1 Agent ↔ bridge | Tool calls and results | Token per agent (in its MCP config); schema validation; policy per call; no policy tools | Same-user processes can read the token and the policy file |
| AB2 Bridge ↔ engine | BiDi commands; the places on this computer and the local network the agent may reach now, which the Shell reads before it shows a page from a local address (#243) | Loopback only, random port, engine rejects `Origin` and foreign `Host`; the places are in a file in the Bridge's private state folder (0600, written atomically) whose path is in the engine's environment, and the Shell takes anything it cannot read as one as no place; in a Nulavio engine the Bridge uses the engine only once the Shell's check is on | Any same-user process can connect to the port while the workspace runs, and rewrite that file, as it can the policy (AB1) |
| AB3 Web page ↔ agent | Page text, element names, screenshots | Marked as untrusted in every result; content never reaches the PDP; tools cannot change policy | The model may still be misled into misusing what it is allowed to do |
| AB4 Agent workspace ↔ user profiles | Cookies, history, storage | Separate engine profile per agent; real profiles not reachable in S4 | — |

## Limits of each autonomy level

What each level can and cannot technically do, beyond the preset table in ADR 0007:

| Level | Can | Cannot (technical limit, not a hidden rule) |
|---|---|---|
| Restricted | Read pages, open public http(s) addresses, take screenshots in its own workspace | Act on pages without a yes in the dialog; reach the local network; run scripts |
| Assisted | Click and type; with a yes: submit forms, files, signed-in sessions | Run scripts, reach the local network, work in two places at once (a profile beside its AI Workspace, or two profiles) |
| Autonomous | Complete multi-step tasks, submit forms, use files and signed-in sessions without asking | Tell a form or a click that pays or changes an account from any other: no tool does, at any level (AI-T13, R88). Local network, two places at once (a profile beside its AI Workspace, or two profiles; one profile on its list alone asks nothing): ask until granted; scripts: ask, and run only once cookies/storage is granted too (while it is blocked, a script is refused before anything is asked, #725); cookies/storage: blocked until granted; the browser's internal pages: never (raw automation was removed, #463) |
| Full control | Everything without asking: actions on pages (forms that pay or change an account included), cookies and storage, the local network, the profiles in its list, scripts | The browser's internal pages (offered to no agent since raw automation was removed, [ADR 0007 amendment of 2026-11-17](../adr/0007-ai-bridge.md#amendment-2026-11-17-raw-automation-is-removed-453)); open a **locked** profile (needs the Vault key, never a permission); stop pages from doing what pages do; restrict what the agent process itself does outside the bridge |

Every capability Settings and `nulavio ai capabilities` offer is checked by a tool before it acts. Until 2026-11-25 they also offered `transactions` (purchases and payments), `account_settings`, `private_tabs`, `network` (network inspection) and `background`, which no tool checked: no tool opens a private tab or shows network traffic, nothing asked before work in the background, and a purchase or an account change is a click or a form, which `interact` and `submit_forms` govern (#714). They are no longer offered; a grant for one that a registry still holds stays in the file and counts for nothing (`policy.RETIRED_CAPABILITIES`).

A call is not asked a question that can only end in a refusal, except in the cases at the end of this paragraph. Before its first question, the Bridge looks at what the call will ask next, in that order. That is entering a tab of one of the user's profiles (its signed-in session for the site, and `multiple_profiles` while another place is open), the tool's own permission, what the address needs (`local_resources`, the signed-in session in a profile), a script's `cookies_storage`, a form sent with Enter (`type` with `submit`), and then, for a click, typing or an upload, what the page will make it need (#736). That is a form the page tried to send after an earlier action and still holds (`submit_forms`, and nothing after it, since settling that form ends the call), or else what the element decides. A held form counts where the tool settles it: typing first refuses a field that takes no text, an element that is gone and its own newline, and an upload a file that is not there, each leaving the form held for the next call; and a form counted in a page the tab moved to meanwhile stays held, the move said after the question. What the element decides is: for a click on a submit button `submit_forms`, and for a link what going to its address needs (as `navigate` asks it); for typing, `submit_forms` for a newline in a single-line field. The element and the held forms are read in the forms guard's sandbox, where the page's scripts do not reach, so the page sees nothing of it before its forms are held; only when nothing before them is refused and what the tab's address needs (`local_resources`, the signed-in session for the site a profile's tab is at) is allowed with no question left, so in a profile's tab only once the profile's questions are answered. A link to an address agents never go to or to an internal page, and a field that takes no text, are refused there too when a question would come before them. A look that fails (the element gone, the page not answering within 5 seconds for all of the look's reads together, or a link's host looked up on this computer only after them) adds nothing: the call says so, or checks it, after its question, as before. The first one blocked for the agent there, or an address outside its sites, refuses the call through the same decision point, with nothing asked (#725, #730). Reading where a profile's tab is enters nothing, so an address agents never act on is refused there before any question too, as in the AI Workspace (#508). Each one is looked up for the site and place its own question would name, so nothing an answer could allow is refused. That look never asks and never stores an answer: a block that ended since (a grant until a time) is asked about in the call's own order, after what comes before it. A new tab for a site whose route names a profile no longer given to the agent is refused there too. A form held from an earlier action that is refused there is dropped, as it is when the refusal comes after the question, so the next call does not find it again; one refused with Enter (`type` with `submit`), before the page is read, stays held for the next click, typing or upload, which drops it the same way. The host of a tab outside the agent's sites is not looked up on this computer before that refusal: the tab's engine may use another resolver (encrypted DNS in a profile). Nor is the host of a profile's tab, or of where `navigate` takes it, before the profile's questions are answered: until then only what the address says itself counts for the local network (`localhost`, an IP address, `.local`), so a name that only its DNS answer makes local is refused after those questions, as before #730. Before any question, a call is judged where the tab is when it comes, on the element as it is then, with the agent's choices as they are then. A question waits on the person, and the tab can move meanwhile, so one rule holds after every question: before the next one and before acting, the Bridge reads where the tab is again, classifies that address again (an address agents never act on, Reader View or the source viewer, the local network, its host looked up again) and checks what it needs there, until a look asks nothing more. Reading the page and looking a host up on this computer take time too (#764). A read whose result the call acts on (the forms the page holds, the element, the link it leads to) counts only when the tab is still on the site the call was judged at, as `still_at` checks it: one taken from a page the tab moved to meanwhile is dropped before anything else is read or set up there, and the move is said. A form held from an earlier action and counted in a page the tab moved to on its own is not asked about, sent or dropped there: it stays held. Before each question, before and after each lookup that decides what the call asks or does (which does not watch the cancel), and after the tab's address is read again before acting (`still_at`, which then reads the address once more, so that the last read before acting is the tab's address), the call is checked again for a cancel and for a stop, a pause, a revocation or a new key: a cancelled or ended call asks, looks up and does nothing more, and the activity record names the address the next check would have named. A request is not written for a call called off before the approver looks, or cancelled or stopped while it reads the registry; one cancelled or stopped while it is written is removed, and no one is told of it. A pause or a revocation while it is written, and a window that picks the request up before it is removed, are not caught yet (#838). Nor is a host looked up only to say where a tab is (the error of a move in `still_at`; what `navigate`, `tab_new`, click, type, upload and `dialog` say about where the tab ended; `tabs_list`): no check follows that lookup, and nothing is done after it but that error or result (#843). A move to another page of the same site is not told apart: questions and grants are for a site. After the profile's questions the tab may have moved to another of the agent's sites, as before #730. After a later question about the tab (the tool's own permission, what its address needs, a script's `cookies_storage`, Enter's `submit_forms`, a submit button's before its link, the link's own) it must still be on that site. A tab that was at an address before the question and is still there is not taken for one that moved (`tab_close` of a tab in Reader View). `type` with `submit` asks about sending forms only then, and `tab_close` does not close a tab that moved while `navigate` was asked. An upload in a profile's tab, or in an AI Workspace started without uploads, fails before anything is asked. In a profile's tab the agent thus learns why its call is refused (an address agents never act on, a blocked permission) before the profile's questions are answered, where `tabs_list` says only that the tab needs a permission. The refusal names no host or path, and an address outside its sites is one `tabs_list` already marks. Two cases still ask first. In a profile's tab, and wherever what the tab's address needs is still to be asked, those questions come before a refusal that the element or a held form decides, since nothing is read of that page before they are answered. And what an action turns out to do, and where it lands, is known only once it is done. That is a form the page sends from its own handler (after a click, typing, an upload or the answer to a dialog) once it has tried, and the address a navigation, a redirect or a click ends at once the tab is there. Each is asked about or refused then, as before (for a form, the result says the action was done and the form was not sent). So is an element the page changes while a question is open: after the question the tool reads it again and asks or refuses what it needs then.

## Assistant stream contract (UX5)

`nulavio ai assistant` keeps its one-request, one-answer contract for every caller. The assistant's panel uses stream mode for Ask and Task. Stream mode uses the same process per call, the same arguments and the same pipe; there is no socket, helper or permission.

| Direction | What | Notes |
|---|---|---|
| Browser → tools | One JSON request line with `"stream": true` | stdin stays open until the terminal line; its end means "cancel" |
| Tools → browser | `start {recipient, model, chars}` | The size the panel showed; `chars` is null for a Task (known afterwards) |
| | `sending {turn}` | Just before each request goes; from then on it "may have arrived" |
| | `delta {text}` | Ask only; gathered for about 50 ms or 256 characters |
| | `step {index, tool, state, capability, reason, origin, ms}` | Task only; `started`, then `ok`, `denied`, `error` or `cancelled`; never the tool's output |
| | `approval {id, capability, expires}` | A permission request the run waits for; the module shows it once (panel card or request tab) |
| | Exactly one `done {…, cancelled, sent}` or `error {code, sent, retryAfter?, status?}` | `sent`: whether a request may have reached the provider |

Cancel paths:
- **The browser.** `callToolStream(...).cancel(grace)` sends SIGTERM, then SIGKILL after 2 s (Ask) or 20 s (Task).
- **The tools.** On the first SIGTERM they ignore further ones and raise `Cancelled`, a BaseException, so no `except Exception` swallows it. A watcher thread turns the end of stdin into SIGTERM.
- **The cleanup.** Removing the request files, closing the AI Workspace and ending the session's answers are never cut. Once the answer is in, or the workspace is closing, a stop waits, and the panel says the answer arrived first.
- **Lines.** SIGTERM is blocked while a line is written, so no half line reaches the browser.

The browser reader fails closed. It refuses a line that is not JSON or is over 1 MiB, and an end without a terminal line (`helper-failed`, or `task-unfinished` for a Task). An idle limit of 150 s per line is held while a permission request waits; the caps are 10 min (Ask) and 30 min (Task).

Session markers (UX5-I2): while `nulavio ai serve` runs, `<state>/ai/sessions/<session>.json` (0600) names the agent, its client and the serving pid; it is removed at the end. The band reads these files and checks `/proc/<pid>`, so it never starts a process, and a marker left by a killed process is ignored.

## Integration points

- **Engine**: no patch. The bridge uses the engine's standard BiDi endpoint. Normal profiles keep refusing remote-control flags.
- **Launcher**: `nulavio ai` subcommands, `paths` (state, data), `engine.find_engine`/`launch_env`, the baseline prefs. Installed tools use the engine of their own install (`engine.bundled_engine`), and a workspace refuses an engine that is not the Nulavio build (`engine.require_nulavio`), except under the test harness in a source checkout.
- **Shell (S7)**: Settings → AI & Automation reads and writes the same registry through the launcher; the activity indicator reads the audit.
- **Profiles and routing (S8)**: agent rules in Smart Profile Routing ("Codex opens localhost in Development"); access to a real profile is a separate grant per profile, and an unlock always comes from the user.

## UX evolution plan (Horizon)

Onboarding in three decisions: choose agent → choose autonomy → connect and finish (a test call proves it works). Everything else lives under Settings → AI & Automation.

| Screen (brief) | Slice | Notes |
|---|---|---|
| AI & Automation (overview), Connected Agents, Connect New Agent | **S7 done** | Settings section; the configuration is shown and copied, never written by Nulavio |
| Agent Detected | **S8 done** | Claude Code / Codex found with version; the exact command and the file it changes; run after the click |
| Choose Autonomy Level, Custom Permissions | **S7 done** | The four levels with one-line consequences; capability rows with allow/ask/block and duration |
| Full Control Warning | **S7 done; UX1** | The Shell's own text (`aiFullControlBody`: what turns on, and that the browser's internal pages are not included), never the tools' English; critical dialog variant with the agent's name; Cancel / Authorize full control (danger), Cancel focused |
| Raw automation opt-in | **Removed (#463)** | The switch is gone. An agent whose record still has the opt-in from an earlier version gets one notice in its row (`aiRawRemoved`), until the person acknowledges it (`forget-raw-automation`); the opt-in grants nothing meanwhile |
| Agent Permission Request | **S7 done; UX1** | `ai/request.html`: agent and level, action, risk callout (critical / warning / info), site, where the agent acts (its Área de IA or your profile), expiry as a clock time; Deny (filled primary, first, focused) / Allow once (secondary) / Allow until the agent disconnects (quiet); never in an AI Workspace. "Once" is for the call; "until the agent disconnects" is for the site and the place shown (`registry.grant_session` keeps those pairs), never the capability elsewhere |
| Authorized Profiles, Authorized Websites | **S7/S8 done** | Per-agent profiles and routes; site list |
| Agent Activity, Automation History | **S7 done** | From the audit, last 30 days, clearable; per-agent filter later |
| Active Agent Sessions | **S8 done** | "Connected now" per agent from connect/disconnect events |
| Background Automation | S7 | Explicit grant with duration |
| Revoke Agent Access, Emergency Stop, Pause | **S7 done; UX1** | Revoke confirmed; stop as a switch, and while it is on a warning callout at the top of the section with "Retomar"; pause/resume per agent; level badges "Nível: …" (Controle total warning-tinted with an icon, Autônomo warning outline, Pausado/Revogado neutral with an icon) |
| Agent Connection Error | S8 | Plain reasons: unknown token, revoked, engine missing (today in the agent's MCP log) |

Activity indicator: the AI Workspace window shows the engine's own remote-control marks (robot icon, striped toolbar) and a Nulavio bar the user cannot close (UX1). It names the agent, its level and where it acts: "Área de IA de <agente> · Nível: …", or "<agente> está usando o seu perfil <nome>" in one of the user's profiles (pref `nulavio.ai.target`). It has "Parar agente", which pauses that agent. The raw-automation bar and state went with raw automation (#463). The root attribute `nulavio-state` (`ai`, `ai-profile`) is there for the window theme. Resume, revoke and the emergency stop live in the user's own Settings, where the agent cannot click them; "Parar agente" can only stop.
