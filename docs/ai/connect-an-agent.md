# Connect an AI agent to Nulavio

The agent gets its own browser profile (the AI Workspace) and only the permissions you choose. Nulavio prints the configuration for you to add, or, after you approve the exact command, asks the agent's own tool to add it. Nulavio never edits another program's files itself.

## 1. Register the agent

In the browser: **Settings → Assistant and AI → Agents, permissions and activity → Connect an agent** (agent, autonomy, connect). If Claude Code or Codex is installed, Nulavio shows the exact command of that tool that adds Nulavio to its settings and runs it when you click; otherwise copy the configuration. From a terminal: `nulavio ai add …` then `nulavio ai connect <agent>`, or:

```sh
nulavio ai add "Claude Code" --client claude-code --autonomy assisted
nulavio ai add "Codex" --client codex --autonomy autonomous --site example.org
```

Autonomy levels (`nulavio ai capabilities` shows the full table):

| Level | In one line |
|---|---|
| `restricted` | Reads and moves around; asks before clicking or typing |
| `assisted` | Clicks and types; asks before submitting, files, sign-ins and purchases |
| `autonomous` | Completes tasks without asking; purchases, account changes, scripts and the local network still ask |
| `full-control` | Everything you select, without asking. Needs `--accept-full-control` after reading the warning |

Options: `--site DOMAIN` (repeatable) limits the agent to those sites; `--disposable` deletes the workspace when the agent disconnects; `--headless` runs without a window.

The command prints the configuration. It holds no secret: it points to the agent's key file in Nulavio (`~/.local/state/nulavio/ai/tokens/`, readable only by you).

## 2. Add the configuration to the agent

**Claude Code**: save the printed JSON as a file and start Claude Code with it, or merge it into your project's `.mcp.json`:

```sh
claude --mcp-config ~/nulavio-claude.json
```

Allow the tools in Claude Code when it asks, or with `--allowedTools mcp__nulavio`. Claude Code's own permission is the first gate; Nulavio's is the second, and it is the one that knows your grants.

**Codex CLI**: add the printed TOML to `~/.codex/config.toml`, or pass the same keys for one run with `codex -c mcp_servers.nulavio.command=…`.

## 3. Change permissions any time

```sh
nulavio ai agents                                   # who is connected, with what
nulavio ai grant ag-1234 submit_forms allow          # stop asking for this
nulavio ai grant ag-1234 execute_js allow --minutes 30
nulavio ai grant ag-1234 navigate block
nulavio ai autonomy ag-1234 restricted
nulavio ai revoke ag-1234                            # next call refused, workspace closed
nulavio ai stop                                      # emergency stop for every agent
nulavio ai resume
nulavio ai audit --agent ag-1234                     # what it did (no page content, no typed text)
```

Changes apply to the agent's next call. When a permission is set to "ask", your Nulavio window shows the request (never the agent's own workspace window); if Nulavio is closed, a KDE dialog asks; without a way to ask, the answer is no. Pause, revoke, permissions and the emergency stop are also in Settings → AI & Automation.

Files: downloads are saved only when the agent may use files, into `~/.local/share/nulavio/ai/workspaces/<agent>/downloads/`; for uploads, put the files the agent may send into `.../<agent>/uploads/`.

## What this does and does not protect

- The agent works in its own profile. Your Personal, Work or Banking profiles are reachable only if you give them to that agent (Settings → Assistant and AI → Agents, permissions and activity → its permissions), only while they are closed in your windows, and never while they are locked.
- Safe Browsing, HTTPS-Only, tracking protection and the pop-up blocker stay on in the AI Workspace.
- The local network and this computer (`localhost`, router pages, `file:`) are off unless you allow `local_resources`.
- A CLI agent runs with your user's rights. Outside Nulavio's tools it can do whatever you can do in a terminal, including reading its key file. Use its own sandbox options if you want to limit that.
- Within what you allowed, a misled or compromised agent can act without asking. Revoke or stop it at any time.
