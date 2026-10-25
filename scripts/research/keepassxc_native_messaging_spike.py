#!/usr/bin/env python3
"""Spike: KeePassXC-Browser <-> KeePassXC over native messaging, end to end.

Runs INSIDE the disposable container defined by
ci/containers/fedora-itest.Containerfile (KeePassXC, Xvfb and xdotool are
installed there, never on the host):

    podman build -t localhost/nulavio-itest:f44 -f ci/containers/fedora-itest.Containerfile ci/containers
    podman run --rm -v "$PWD":/src:ro,Z localhost/nulavio-itest:f44 \
        sh -c 'cp -r /src ~/nulavio && cd ~/nulavio && python3 -I scripts/research/keepassxc_native_messaging_spike.py'

Steps:
 1. throwaway KeePassXC database with one fixture login for a local page;
 2. native-messaging manifest identical to what KeePassXC writes for Firefox;
 3. KeePassXC on a virtual X server (Xvfb), database unlocked via --pw-stdin;
 4. a Nulavio profile created by the launcher with provider "keepassxc" and
    the pinned official KeePassXC-Browser extension;
 5. popup state before association, association dialog answered by xdotool
    (simulating the user clicking "Save and allow access"), popup state after;
 6. autofill of the fixture login page.

Only throwaway data is used. The report is printed as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import harness  # noqa: E402

DB_PASSWORD = "nulavio-spike-db-only"  # throwaway database, never a real secret  # noqa: S105
ENTRY_USER = "alice.fixture"
ENTRY_PASSWORD = "Fixture-Only-9b1d"  # noqa: S105
EXT_ID = "keepassxc-browser@keepassxc.org"

EXT_INFO = """
const {ExtensionParent} = ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");
const ext = ExtensionParent.GlobalManager.getExtension(arguments[0]);
if (!ext) return null;
const m = ext.manifest;
const action = m.action || m.browser_action || {};
const options = (m.options_ui && m.options_ui.page) || m.options_page || null;
return {popup: action.default_popup ? ext.baseURI.resolve(action.default_popup) : null,
        options: options ? ext.baseURI.resolve(options) : null, version: ext.version};
"""


def run(cmd: list[str], stdin: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, timeout=60, check=False)


class DialogWatcher(threading.Thread):
    """Records every KeePassXC window and answers browser-integration dialogs."""

    def __init__(self, env: dict):
        super().__init__(daemon=True)
        self.env = env
        self.seen: dict[str, str] = {}
        self.actions: list[str] = []
        self.stop = threading.Event()

    def windows(self) -> dict[str, str]:
        out = run(["xdotool", "search", "--onlyvisible", "--name", "."], env=self.env).stdout.split()
        names = {}
        for wid in out:
            names[wid] = run(["xdotool", "getwindowname", wid], env=self.env).stdout.strip()
        return names

    def run(self) -> None:
        while not self.stop.is_set():
            for wid, name in self.windows().items():
                if wid in self.seen:
                    continue
                self.seen[wid] = name
                lowered = name.lower()
                if "association" in lowered or "associate" in lowered:
                    time.sleep(0.8)
                    run(["xdotool", "windowfocus", "--sync", wid], env=self.env)
                    run(["xdotool", "type", "--window", wid, "--delay", "40", "nulavio-spike"], env=self.env)
                    run(["xdotool", "key", "--window", wid, "Return"], env=self.env)
                    self.actions.append(f"association dialog '{name}': named key and confirmed")
                elif "access" in lowered or "request" in lowered:
                    time.sleep(0.8)
                    run(["xdotool", "windowfocus", "--sync", wid], env=self.env)
                    run(["xdotool", "key", "--window", wid, "Return"], env=self.env)
                    self.actions.append(f"access dialog '{name}': pressed default button")
            time.sleep(0.4)


def popup_state(m, url: str, label: str, artifacts: Path) -> dict:
    handle = m.new_tab()
    m.switch_to(handle)
    m.navigate(url)
    time.sleep(3)
    state = m.execute(
        "return {text: (document.body.innerText || '').trim().slice(0, 400),"
        " buttons: [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null)"
        ".map(b => ({id: b.id, text: b.innerText.trim()}))};"
    )
    (artifacts / f"keepassxc-popup-{label}.png").write_bytes(m.screenshot_png())
    return {"handle": handle, **state}


def find_sockets(roots: list[Path]) -> list[Path]:
    found = []
    for root in roots:
        if root.is_dir():
            found += [p for p in root.rglob("*BrowserServer*") if p.is_socket()]
    return sorted(set(found))


def can_connect(path: Path) -> bool:
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        try:
            sock.connect(str(path))
            return True
        except OSError:
            return False


def diagnostics(runtime: Path, work: Path) -> dict:
    """What the proxy needs: KeePassXC's socket, a running proxy, and their messages (no secrets)."""
    sockets = find_sockets([runtime, Path(tempfile.gettempdir())])
    proxies = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if b"keepassxc-proxy" in (entry / "cmdline").read_bytes():
                    proxies.append(int(entry.name))
            except OSError:
                continue

    def tail(path: Path, pattern: str = "") -> list[str]:
        if not path.exists():
            return []
        lines = path.read_text(errors="replace").splitlines()
        if pattern:
            lines = [line for line in lines if any(k in line.lower() for k in pattern.split("|"))]
        return [line[:200] for line in lines[-15:]]

    return {
        "xdg_runtime_dir": os.environ.get("XDG_RUNTIME_DIR"),
        "sockets": {str(s): can_connect(s) for s in sockets},
        "proxy_pids": proxies,
        "keepassxc_log": tail(work / "keepassxc.log"),
        "engine_log": tail(work / "engine.log", "keepassxc|proxy|native|qlocalsocket|qstandardpaths"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts", type=Path, default=Path(tempfile.gettempdir()) / "kpx-artifacts")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    report: dict = {"steps": {}}
    work = Path(tempfile.mkdtemp(prefix="nulavio-kpx-"))
    # A desktop session always has XDG_RUNTIME_DIR (KeePassXC puts its browser
    # socket there). Containers usually do not; give KeePassXC and the browser
    # (hence keepassxc-proxy) the same private one so both resolve one path.
    report["xdg_runtime_dir_preset"] = "XDG_RUNTIME_DIR" in os.environ
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.mkdtemp(prefix="nulavio-xdg-runtime-"))
    runtime.chmod(0o700)
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    os.environ["NULAVIO_TEST_ENGINE_LOG"] = str(work / "engine.log")
    procs: list[subprocess.Popen] = []
    session = None
    watcher = None
    with harness.FixtureServer() as server:
        try:
            login_url = server.url("/login")
            # 1. throwaway database
            db = work / "spike.kdbx"
            created = run(["keepassxc-cli", "db-create", "-p", str(db)], stdin=f"{DB_PASSWORD}\n{DB_PASSWORD}\n")
            added = run(
                ["keepassxc-cli", "add", "-u", ENTRY_USER, "--url", f"http://127.0.0.1:{server.port}", "-p", str(db), "Fixture"],
                stdin=f"{DB_PASSWORD}\n{ENTRY_PASSWORD}\n",
            )
            report["steps"]["database"] = {"created": created.returncode == 0, "entry_added": added.returncode == 0}

            # 2. native messaging manifest (same content KeePassXC writes for Firefox)
            manifest_dir = Path.home() / ".mozilla" / "native-messaging-hosts"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "name": "org.keepassxc.keepassxc_browser",
                "description": "KeePassXC integration with native messaging support",
                "path": shutil.which("keepassxc-proxy"),
                "type": "stdio",
                "allowed_extensions": [EXT_ID],
            }
            (manifest_dir / "org.keepassxc.keepassxc_browser.json").write_text(json.dumps(manifest, indent=2))
            report["steps"]["manifest"] = manifest

            # 3. KeePassXC on Xvfb
            env = {**os.environ, "DISPLAY": ":99", "QT_QPA_PLATFORM": "xcb"}
            procs.append(
                subprocess.Popen(
                    ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            time.sleep(1.5)
            config = work / "keepassxc.ini"
            config.write_text(
                "[General]\nConfigVersion=2\n[Browser]\nEnabled=true\n[GUI]\nCheckForUpdates=false\nCheckForUpdatesNextCheck=0\n"
            )
            with open(work / "keepassxc.log", "w") as kpx_log:  # the child keeps its own descriptor
                kpx = subprocess.Popen(
                    ["keepassxc", "--config", str(config), "--pw-stdin", str(db)],
                    stdin=subprocess.PIPE,
                    stdout=kpx_log,
                    stderr=kpx_log,
                    env=env,
                    text=True,
                )
            kpx.stdin.write(DB_PASSWORD + "\n")
            kpx.stdin.close()
            procs.append(kpx)
            watcher = DialogWatcher(env)
            main_window = harness.wait_until(lambda: any("KeePassXC" in n for n in watcher.windows().values()), timeout=30)
            report["steps"]["keepassxc_running"] = bool(main_window)
            # The browser server is up once its socket accepts connections. Starting the
            # browser earlier lets the extension's first key exchange fail on slow runners.
            ready = harness.wait_until(lambda: any(can_connect(s) for s in find_sockets([runtime])), timeout=30)
            report["steps"]["browser_socket_ready"] = bool(ready)
            watcher.start()

            # 4. Nulavio profile with provider keepassxc + official extension (pinned)
            session = harness.Session(profile="kpx", setup_args=("--provider", "keepassxc", "--install-provider-extension"))
            m = session.start()
            info = harness.wait_until(lambda: m.chrome(EXT_INFO, [EXT_ID]), timeout=20)
            report["steps"]["extension"] = info

            # 5. popup before, connect + associate, popup after
            # If the extension's first attempt raced KeePassXC's startup, the popup shows
            # "Cannot connect" with a Reload button: press it, as a user would.
            reloads = 0
            while True:
                before = popup_state(m, info["popup"], "before", args.artifacts)
                connect = next((b for b in before["buttons"] if "connect" in b["text"].lower()), None)
                reload_button = next((b for b in before["buttons"] if b["id"] == "reload-status-button"), None)
                if connect or "is connected" in before["text"] or not reload_button or reloads >= 4:
                    break
                m.execute("document.getElementById(arguments[0]).click();", [reload_button["id"]])
                reloads += 1
                time.sleep(4)
                m.send("WebDriver:CloseWindow")
                m.switch_to(m.window_handles()[0])
            report["steps"]["popup_reloads"] = reloads
            report["steps"]["popup_before_association"] = {k: before[k] for k in ("text", "buttons")}
            report["diagnostics_before_association"] = diagnostics(runtime, work)
            if connect:
                m.execute("document.getElementById(arguments[0]).click();", [connect["id"]])
                time.sleep(6)
            m.send("WebDriver:CloseWindow")
            m.switch_to(m.window_handles()[0])
            after = popup_state(m, info["popup"], "after", args.artifacts)
            report["steps"]["popup_after_association"] = {k: after[k] for k in ("text", "buttons")}
            m.send("WebDriver:CloseWindow")
            m.switch_to(m.window_handles()[0])

            # 6. autofill on the fixture page (enable "auto-fill single entry" in the extension's own options)
            if info.get("options"):
                m.navigate(info["options"])
                time.sleep(2)
                toggled = m.execute(
                    "const el = [...document.querySelectorAll('input[type=checkbox]')]"
                    ".find(i => /autoFillSingleEntry|autoFillSingle/i.test(i.id + ' ' + (i.name || '')));"
                    "if (!el) return null; if (!el.checked) el.click(); return el.id;"
                )
                report["steps"]["autofill_single_entry_option"] = toggled
                time.sleep(1)
            m.navigate(login_url)
            filled = harness.wait_until(
                lambda: (lambda v: v if v and v.get("user") else None)(
                    m.execute(
                        "return {user: document.getElementById('username').value,"
                        " pass: document.getElementById('password').value};"
                    )
                ),
                timeout=30,
                interval=1.0,
            )
            report["steps"]["autofill"] = {
                "username_filled": bool(filled) and filled["user"] == ENTRY_USER,
                "password_filled": bool(filled) and filled["pass"] == ENTRY_PASSWORD,
            }
            (args.artifacts / "keepassxc-autofill.png").write_bytes(m.screenshot_png())
        finally:
            if watcher is not None:
                watcher.stop.set()
                report["keepassxc_windows_seen"] = sorted(set(watcher.seen.values()))
                report["dialog_actions"] = watcher.actions
            if session is not None:
                session.cleanup()
            for proc in reversed(procs):
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if "autofill" not in report["steps"] or not all(report["steps"]["autofill"].values()):
                report["diagnostics_at_end"] = diagnostics(runtime, work)
            shutil.rmtree(work, ignore_errors=True)
            if not report["xdg_runtime_dir_preset"]:
                shutil.rmtree(runtime, ignore_errors=True)
    (args.artifacts / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    ok = report["steps"].get("autofill", {})
    return 0 if ok.get("username_filled") and ok.get("password_filled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
