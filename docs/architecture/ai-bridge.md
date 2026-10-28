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
| AB2 Bridge ↔ engine | BiDi commands | Loopback only, random port, engine rejects `Origin` and foreign `Host` | Any same-user process can connect to the port while the workspace runs |
| AB3 Web page ↔ agent | Page text, element names, screenshots | Marked as untrusted in every result; content never reaches the PDP; tools cannot change policy | The model may still be misled into misusing what it is allowed to do |
| AB4 Agent workspace ↔ user profiles | Cookies, history, storage | Separate engine profile per agent; real profiles not reachable in S4 | — |

## Limits of each autonomy level

What each level can and cannot technically do, beyond the preset table in ADR 0007:

| Level | Can | Cannot (technical limit, not a hidden rule) |
|---|---|---|
| Restricted | Read pages, open public http(s) addresses, take screenshots in its own workspace | Act on pages without a yes in the dialog; reach the local network; run scripts |
| Assisted | Click and type; with a yes: submit, files, signed-in sessions, purchases | Run scripts, reach the local network, see other profiles |
| Autonomous | Complete multi-step tasks, submit forms, use files and signed-in sessions without asking | Purchases and account changes, scripts, local network, other profiles: ask until granted; cookies/storage: blocked until granted; raw automation: only through its own opt-in |
| Full control | Everything except raw automation, without asking: actions on pages, purchases and payments, account changes, private tabs, the profiles in its list, scripts | Raw automation and privileged pages (a separate per-agent opt-in with its own warning, [ADR 0007 amendment of 2026-10-28](../adr/0007-ai-bridge.md#amendment-2026-10-28-raw-automation-leaves-full-control-ux1-d-ux4)); open a **locked** profile (needs the Vault key, never a permission); stop pages from doing what pages do; restrict what the agent process itself does outside the bridge |

## Integration points

- **Engine**: no patch. The bridge uses the engine's standard BiDi endpoint. Normal profiles keep refusing remote-control flags.
- **Launcher**: `nulavio ai` subcommands, `paths` (state, data), `engine.find_engine`/`launch_env`, the baseline prefs.
- **Shell (S7)**: Settings → AI & Automation reads and writes the same registry through the launcher; the activity indicator reads the audit.
- **Profiles and routing (S8)**: agent rules in Smart Profile Routing ("Codex opens localhost in Development"); access to a real profile is a separate grant per profile, and an unlock always comes from the user.

## UX evolution plan (Horizon)

Onboarding in three decisions: choose agent → choose autonomy → connect and finish (a test call proves it works). Everything else lives under Settings → AI & Automation.

| Screen (brief) | Slice | Notes |
|---|---|---|
| AI & Automation (overview), Connected Agents, Connect New Agent | **S7 done** | Settings section; the configuration is shown and copied, never written by Nulavio |
| Agent Detected | **S8 done** | Claude Code / Codex found with version; the exact command and the file it changes; run after the click |
| Choose Autonomy Level, Custom Permissions | **S7 done** | The four levels with one-line consequences; capability rows with allow/ask/block and duration |
| Full Control Warning | **S7 done; UX1** | The Shell's own text (`aiFullControlBody`: what turns on, and that raw automation is not included), never the tools' English; critical dialog variant with the agent's name; Cancel / Authorize full control (danger), Cancel focused |
| Raw automation opt-in | **UX1** | A switch per agent ("Automação bruta"), outside the capability list and every level; its own critical warning (`aiRawBody`); off again without a prompt |
| Agent Permission Request | **S7 done; UX1** | `ai/request.html`: agent and level, action, risk callout (critical / warning / info), site, where the agent acts (its Área de IA or your profile), expiry as a clock time; Deny (filled primary, first, focused) / Allow once (secondary) / Allow until the agent disconnects (quiet); never in an AI Workspace |
| Authorized Profiles, Authorized Websites | **S7/S8 done** | Per-agent profiles and routes; site list |
| Agent Activity, Automation History | **S7 done** | From the audit, last 30 days, clearable; per-agent filter later |
| Active Agent Sessions | **S8 done** | "Connected now" per agent from connect/disconnect events |
| Background Automation | S7 | Explicit grant with duration |
| Revoke Agent Access, Emergency Stop, Pause | **S7 done; UX1** | Revoke confirmed; stop as a switch, and while it is on a warning callout at the top of the section with "Retomar"; pause/resume per agent; level badges "Nível: …" (Controle total warning-tinted with an icon, Autônomo warning outline, Pausado/Revogado neutral with an icon) |
| Agent Connection Error | S8 | Plain reasons: unknown token, revoked, engine missing (today in the agent's MCP log) |

Activity indicator: the AI Workspace window shows the engine's own remote-control marks (robot icon, striped toolbar) and a Nulavio bar the user cannot close (UX1). It names the agent, its level and where it acts: "Área de IA de <agente> · Nível: …", or "<agente> está usando o seu perfil <nome>" in one of the user's profiles (pref `nulavio.ai.target`). It has "Parar agente", which pauses that agent. When the endpoint is handed over (`nulavio-raw.json` in the workspace's profile), a critical bar replaces it until the window closes: "Automação bruta: o Nulavio não verifica nem registra o que acontece nesta janela". The root attribute `nulavio-state` (`ai`, `ai-profile`, `raw`) is there for the window theme. Resume, revoke and the emergency stop live in the user's own Settings, where the agent cannot click them; "Parar agente" can only stop.
