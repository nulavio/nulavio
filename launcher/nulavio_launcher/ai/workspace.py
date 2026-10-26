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


class WorkspaceError(RuntimeError):
    pass


def workspaces_root() -> Path:
    return paths.data_home() / "ai" / "workspaces"


class Workspace:
    def __init__(self, agent_id: str, *, disposable: bool = False, headless: bool = False, engine=None):
        self.agent_id = agent_id
        self.disposable = disposable
        self.headless = headless
        self.engine = engine
        self.process: subprocess.Popen | None = None
        self.bidi: Bidi | None = None
        if disposable:
            self.dir = Path(tempfile.mkdtemp(prefix="nulavio-ai-"))
        else:
            self.dir = paths.ensure_private_dir(workspaces_root() / agent_id)
        self.profile_dir = self.dir / "profile"

    def _write_prefs(self) -> None:
        paths.ensure_private_dir(self.profile_dir)
        merged = {p.name: p.value for p in profile.baseline_prefs()}
        merged["browser.startup.homepage"] = "about:blank"  # the start page belongs to user profiles
        merged.update(WORKSPACE_PREFS)
        unresolved = [k for k, v in merged.items() if isinstance(v, str) and "@" in v]
        for key in unresolved:
            del merged[key]
        paths.write_private_file(
            self.profile_dir / "user.js", prefs.render(list(merged.items()), "Nulavio AI Workspace (generated)")
        )

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
        self.process = subprocess.Popen(
            self.command(), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, preexec_fn=lambda: os.umask(0o077),
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
            self.bidi = Bidi(port)
            self.bidi.command("session.subscribe", {"events": ["browsingContext.navigationStarted", "browsingContext.load"]})
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
        if self.disposable:
            shutil.rmtree(self.dir, ignore_errors=True)
