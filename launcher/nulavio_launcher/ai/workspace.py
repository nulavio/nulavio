"""AI Workspace: an isolated engine profile that one agent drives through WebDriver BiDi.

This is the only place where Nulavio starts the engine's remote agent. Normal
profiles keep refusing remote-control flags (engine.FORBIDDEN_FLAGS). The
workspace has its own cookies, history, downloads and storage, one per agent,
and can be disposable (deleted when the bridge exits).

Protections stay on: sandboxes are untouched (engine.launch_env), and the
remote agent's "recommended preferences" are switched off because they
disable Safe Browsing, updates and the pop-up blocker for test automation.
The endpoint listens on 127.0.0.1 on a random port; the engine refuses
WebSocket upgrades that carry an Origin header (web pages) or a foreign Host.

What the Shell in these windows reads (NulavioAI.sys.mjs): the prefs
`nulavio.ai.workspace` (which agent drives the window) and `nulavio.ai.target`
("workspace", or "profile" with `nulavio.ai.target.label` for one of the user's
own profiles), and the file RAW_MARKER in the profile while the BiDi endpoint is
handed over (raw automation), so the window can say so.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .. import engine as engine_mod
from .. import paths, prefs, profile
from .bidi import Bidi

APP_ID = "nulavio-ai-workspace"
# The same value as the nulavio.ai.workspace pref, in the engine's environment: nothing in the
# browser (about:config included) can change it, so the window's lock does not rest on a pref
# an agent with raw automation could reset (audit A6). browser/shell/modules/NulavioAI.sys.mjs.
WORKSPACE_ENV = "NULAVIO_AI_WORKSPACE"
# Written into the AI Workspace's profile when raw_automation hands the endpoint over, removed when
# the workspace starts or stops: {"agent", "pid" (the bridge), "since"}. A cue for the window only;
# the bridge's own state (Bridge.raw) and its watcher are what end the workspace.
RAW_MARKER = "nulavio-raw.json"
WORKSPACE_PREFS: dict[str, object] = {
    # Keep Safe Browsing, updates, the pop-up blocker and the rest of the
    # baseline: never apply the remote agent's test-automation preferences.
    "remote.prefs.recommended": False,
    # Mozilla's official builds show a Terms of Use modal on first run that blocks new tabs.
    # The engine's own automation prefs skip it; it is a notice, not a protection, so keep only this one.
    "termsofuse.bypassNotification": True,
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "browser.aboutwelcome.enabled": False,
}


EVENTS = [
    "browsingContext.navigationStarted", "browsingContext.load",
    "browsingContext.userPromptOpened", "browsingContext.userPromptClosed",
    "browsingContext.downloadWillBegin", "browsingContext.downloadEnd",
]  # fmt: skip


class WorkspaceError(RuntimeError):
    pass


def workspaces_root() -> Path:
    return paths.data_home() / "ai" / "workspaces"


class Workspace:
    def __init__(self, agent_id: str, *, disposable: bool = False, headless: bool = False, engine=None,
                 uploads: bool = False):  # fmt: skip
        self.agent_id = agent_id
        self.uploads = uploads
        self.disposable = disposable
        self.headless = headless
        self.engine = engine
        self.process: subprocess.Popen | None = None
        self.port: int | None = None  # the engine's WebDriver BiDi port (loopback)
        self.bidi: Bidi | None = None
        if disposable:
            self.dir = Path(tempfile.mkdtemp(prefix="nulavio-ai-"))
        else:
            self.dir = paths.ensure_private_dir(workspaces_root() / agent_id)
        self.profile_dir = self.dir / "profile"
        # Downloads land here (only when the agent may use files); uploads come only from here,
        # where the user puts the files an agent may send.
        self.downloads_dir = self.dir / "downloads"
        self.uploads_dir = self.dir / "uploads"
        for folder in (self.downloads_dir, self.uploads_dir):
            folder.mkdir(mode=0o700, exist_ok=True)

    def marker(self) -> str:
        """Which agent drives this window (nulavio.ai.workspace and WORKSPACE_ENV)."""
        return self.agent_id

    def _write_prefs(self) -> None:
        paths.ensure_private_dir(self.profile_dir)
        merged = {p.name: p.value for p in profile.baseline_prefs()}
        merged["browser.startup.homepage"] = "about:blank"  # the start page belongs to user profiles
        merged.update(WORKSPACE_PREFS)
        # Tells Nulavio's own pages in this window that an agent drives it: they show who, and never
        # answer permission requests here (the agent could click them).
        merged["nulavio.ai.workspace"] = self.marker()
        merged["nulavio.ai.target"] = "workspace"
        if self.uploads:
            # Only for agents that may use files. The content sandbox stays on; page processes may
            # also *read* this one folder, where the user puts files meant for upload, and turn a
            # path into a File (what a file field needs). Nothing else becomes readable.
            merged["security.sandbox.content.read_path_whitelist"] = str(self.uploads_dir) + "/"
            merged["dom.file.createInChild"] = True
        unresolved = [k for k, v in merged.items() if isinstance(v, str) and "@" in v]
        for key in unresolved:
            del merged[key]
        paths.write_private_file(
            self.profile_dir / "user.js", prefs.render(list(merged.items()), "Nulavio AI Workspace (generated)")
        )
        (self.profile_dir / RAW_MARKER).unlink(missing_ok=True)  # left by a bridge that did not end cleanly

    def mark_raw(self) -> None:
        """The endpoint was handed over: the window shows the raw-automation state from now until it closes."""
        since = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        paths.write_private_file(self.profile_dir / RAW_MARKER,
                                 json.dumps({"agent": self.agent_id, "pid": os.getpid(), "since": since}))  # fmt: skip

    def command(self) -> list[str]:
        command = [
            str(self.engine.path), "--profile", str(self.profile_dir), "--no-remote",
            "--remote-debugging-port=0", "--name", APP_ID, "--class", APP_ID,
        ]  # fmt: skip
        if self.headless:
            command.append("--headless")
        return command

    def start(self, timeout: float = 60.0) -> Bidi:
        if self.bidi is not None:
            return self.bidi
        if self.engine is None:
            self.engine = engine_mod.find_engine()
            engine_mod.check_supported(self.engine)
        self._write_prefs()
        port_file = self.profile_dir / "WebDriverBiDiServer.json"
        port_file.unlink(missing_ok=True)
        env = engine_mod.launch_env()  # sandboxes stay on; no MOZ_* debugging knobs
        env["MOZ_APP_REMOTINGNAME"] = APP_ID
        env[WORKSPACE_ENV] = self.marker()
        self.process = subprocess.Popen(
            [*die_with_parent(), *self.command()], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=lambda: os.umask(0o077),
        )  # fmt: skip
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise WorkspaceError(f"engine exited with {self.process.returncode}")
            try:
                port = int(json.loads(port_file.read_text())["ws_port"])
            except (OSError, ValueError, KeyError):
                time.sleep(0.2)
                continue
            self.port = port
            self.bidi = Bidi(port)
            self.bidi.command("session.subscribe", {"events": EVENTS})
            return self.bidi
        self.stop()
        raise WorkspaceError("the engine's automation endpoint did not start")

    def stop(self) -> None:
        if self.bidi is not None:
            with contextlib.suppress(Exception):  # shutting down anyway
                self.bidi.command("browser.close", {}, timeout=5)
            self.bidi.ws.close()
            self.bidi = None
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
            self.process = None
        with contextlib.suppress(OSError):
            (self.profile_dir / RAW_MARKER).unlink(missing_ok=True)
        if self.disposable:
            shutil.rmtree(self.dir, ignore_errors=True)


def die_with_parent() -> list[str]:
    """A prefix that ends the engine if the bridge dies without closing it (killed, crashed).

    An engine left running would keep its automation endpoint open, and in a
    user's profile also the temporary automation lines. `setpriv --pdeathsig`
    (util-linux) sets the kernel's parent-death signal and then runs the engine
    in its place. The bridge starts engines from its long-lived tool thread, so
    the signal comes when the bridge process ends, not before.
    """
    setpriv = shutil.which("setpriv", path="/usr/bin:/bin")
    return [setpriv, "--pdeathsig", "TERM", "--"] if setpriv else []


TEMPORARY = "// nulavio-ai-temporary"


class TargetError(WorkspaceError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


class ProfileTarget(Workspace):
    """One of the user's own profiles, which the user authorised this agent to use (ADR 0007, S8).

    It opens in its own engine instance only while it is not open elsewhere and
    not locked: an agent never gets a profile's keys, and never takes over a
    window the user is using. Temporary lines go into its user.js (no
    remote-agent test preferences; this window is driven by an agent, and it is
    the user's profile by this name) and are removed when the agent's session
    ends.
    """

    def __init__(self, agent_id: str, label: str, path: Path, *, downloads_dir: Path, headless: bool = False, engine=None):
        self.agent_id = agent_id
        self.label = label
        self.uploads = False
        self.disposable = False
        self.headless = headless
        self.engine = engine
        self.process = None
        self.bidi = None
        self.dir = Path(path)
        self.profile_dir = Path(path)
        self.downloads_dir = downloads_dir
        self.uploads_dir = None

    def check(self) -> None:
        from ..profile import Profile
        from ..vault.storage import Container

        if not self.profile_dir.is_dir():
            raise TargetError("profile-missing", self.label)
        box = Container(self.profile_dir)
        if box.vault_path.exists() and not box.mounted():
            raise TargetError("profile-locked", self.label)
        if Profile(name=self.label, path=self.profile_dir).running_pid():
            raise TargetError("profile-in-use", self.label)

    def marker(self) -> str:
        return f"{self.agent_id}:{os.getpid()}"  # counts only while this bridge process lives

    def _write_prefs(self) -> None:
        user_js = self.profile_dir / "user.js"
        self._remove_temporary()
        lines = [
            f'user_pref("remote.prefs.recommended", false); {TEMPORARY}',
            f'user_pref("nulavio.ai.workspace", "{self.marker()}"); {TEMPORARY}',
            # The window says that an agent uses *this* profile of the user's, not an AI Workspace.
            f'user_pref("nulavio.ai.target", "profile"); {TEMPORARY}',
            f"{prefs.format_pref('nulavio.ai.target.label', self.label)} {TEMPORARY}",
        ]
        existing = user_js.read_text(encoding="utf-8") if user_js.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        paths.write_private_file(user_js, existing + "\n".join(lines) + "\n")

    def _remove_temporary(self) -> None:
        user_js = self.profile_dir / "user.js"
        if not user_js.exists():
            return
        kept = [line for line in user_js.read_text(encoding="utf-8").splitlines() if TEMPORARY not in line]
        if kept:
            paths.write_private_file(user_js, "\n".join(kept) + "\n")
        else:
            user_js.unlink()

    def start(self, timeout: float = 60.0) -> Bidi:
        if self.bidi is None:
            self.check()
        return super().start(timeout)

    def stop(self) -> None:
        super().stop()
        self._remove_temporary()
