#!/usr/bin/env python3
"""Pre-build a Nulavio security update as soon as Mozilla stages or publishes a Firefox release.

Run by the systemd user timer in contrib/systemd/ (every 30 minutes, opt-in) or by hand:

    python3 -I scripts/release/autobuild.py [--notify] [--dry-run] [--no-build] [--retry]
        [--build-on-battery] [--min-free-gib 30] [--repo DIR] [--ref main] [--work DIR]
        [--state FILE] [--prune]

Each run takes a lock (flock; a second run exits 0 at once), asks
scripts/release/watch_upstream.py (signatures verified) what Mozilla has staged
or published, and lets decide() choose what to do. To build, it creates a
separate git worktree of the local `main` under the work directory (no fetch or
pull: only code already in the clone runs), pins the release there with
bump_engine.py (which verifies Mozilla's signature again), and runs
rehearse_release.sh in it while inhibiting sleep. It refuses to build on battery,
with less than 30 GiB free, without the Google Safe Browsing key (the file
build_nulavio.sh reads), or while another build or rehearsal is running. Once
Mozilla has published the release and its signed digest equals the one built, it
says READY TO SIGN; a different digest means a rebuild.

It never builds without a successful signature verification, never commits,
pushes, signs or publishes: the diff waits in the worktree for review.
Notifications (--notify) go to the desktop (notify-send or D-Bus) and always to
the journal; each one is sent once.

Exit status: 0 nothing to do, waiting, or built ahead of publication; 10 ready to
sign now; 1 the build or its tests failed; 2 release data unavailable;
3 a signature did not verify (nothing is built); 4 a precondition is missing
(power, disk, Safe Browsing key, another build running). Output: one JSON object.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_upstream  # noqa: E402

EXIT_READY = 10
UNAVAILABLE_NOTICE_AFTER = _dt.timedelta(hours=6)
MAX_NOTIFIED = 200
DEFAULT_MIN_FREE_GIB = 30.0


@dataclasses.dataclass(frozen=True)
class Options:
    build_on_battery: bool = False
    min_free_gib: float = DEFAULT_MIN_FREE_GIB
    no_build: bool = False
    retry: bool = False


@dataclasses.dataclass(frozen=True)
class Facts:
    """The machine, as measured just before deciding."""

    ac_power: bool | None  # None: unknown (systemd-ac-power missing)
    free_gib: float
    sb_key: str  # "ok", "missing", or "not-private"
    sb_key_path: str
    work: str
    busy: tuple[int, ...] = ()  # processes of another build or rehearsal (they share the source tree)


@dataclasses.dataclass(frozen=True)
class Notice:
    key: str  # sent once per key
    urgency: str  # "critical" or "normal"
    title: str
    body: str


@dataclasses.dataclass(frozen=True)
class Decision:
    action: str  # idle, wait, build, would-build, ready, blocked, failed-before, stop, unavailable
    version: str | None
    reason: str
    exit_code: int
    digest: str | None = None
    shipped: bool = False
    notices: tuple[Notice, ...] = ()


# --- the decision (pure) -----------------------------------------------------------


def _when(stamp: str | None) -> str:
    return watch_upstream._when(stamp) if stamp else "?"


def _clock(target: dict) -> str:
    if not target.get("target"):
        return f"target {target['target_hours']} h and deadline {target['deadline_hours']} h start when Mozilla publishes"
    return (
        f"target {_when(target['target'])} ({target['target_hours']} h), "
        f"deadline {_when(target['deadline'])} ({target['deadline_hours']} h)"
    )


def target_notices(target: dict) -> list[Notice]:
    """What the user hears about a release, independent of any build."""
    version = target["version"]
    urgency = f"{target['urgency'].upper()} ({'; '.join(target['reasons'])})"
    notices = []
    if target["phase"] == "staged" and target.get("verified") is True:
        notices.append(
            Notice(
                f"staged:{version}",
                "normal",
                f"Firefox {version} staged by Mozilla",
                f"Signature verified. {urgency}. {_clock(target)}.",
            )
        )
    if target["phase"] == "shipped":
        level = "critical" if target["urgency"] == "urgent" else "normal"
        notices.append(
            Notice(
                f"shipped:{version}:{target['urgency']}", level, f"Firefox {version} released: {urgency}", f"{_clock(target)}."
            )
        )
    if target.get("itw") == "yes":
        notices.append(
            Notice(
                f"itw:{version}",
                "critical",
                f"Firefox {version}: exploited in the wild",
                "Mozilla reports attacks. " + _clock(target),
            )
        )
    if target.get("target_missed") and not target.get("overdue"):
        notices.append(Notice(f"missed:{version}", "critical", f"Firefox {version}: target missed", _clock(target) + "."))
    if target.get("overdue"):
        notices.append(
            Notice(f"overdue:{version}", "critical", f"Firefox {version}: Nulavio update OVERDUE", _clock(target) + ".")
        )
    return notices


def blockers(facts: Facts, options: Options) -> list[tuple[str, str]]:
    """(kind, explanation) for each missing precondition; the kind keeps notifications from repeating."""
    found = []
    if facts.busy:
        found.append(("busy", f"another Nulavio build or rehearsal is running (pid {', '.join(map(str, facts.busy))})"))
    if facts.ac_power is False and not options.build_on_battery:
        found.append(("battery", "on battery (plug in, or --build-on-battery)"))
    if facts.ac_power is None and not options.build_on_battery:
        found.append(("power", "power source unknown (systemd-ac-power missing)"))
    if facts.free_gib < options.min_free_gib:
        found.append(("disk", f"only {facts.free_gib:.0f} GiB free for {facts.work} (needs {options.min_free_gib:.0f})"))
    if facts.sb_key == "missing":
        found.append(("key", f"Google Safe Browsing key missing at {facts.sb_key_path} (docs/architecture/build.md)"))
    elif facts.sb_key != "ok":
        found.append(("key", f"Google Safe Browsing key {facts.sb_key_path} must be private (chmod 600)"))
    return found


def _built(record: dict | None, digest: str) -> bool:
    return bool(record) and record.get("source_sha256") == digest and record.get("phase") in ("built", "ready-to-sign")


def decide(state: dict, report: dict, facts: Facts, options: Options, now: _dt.datetime) -> Decision:
    """What to do this run. Never "build" unless the signature of that exact digest verified."""
    notices: list[Notice] = []
    if report.get("exit_code") == 2 or report.get("state") == "unavailable":
        problem = (report.get("errors") or ["release data unavailable"])[0]
        since = state.get("unavailable_since") or watch_upstream._stamp(now)
        if now - _dt.datetime.fromisoformat(since.replace("Z", "+00:00")) >= UNAVAILABLE_NOTICE_AFTER:
            notices.append(
                Notice(
                    f"unavailable:{since}", "normal", "Firefox release data unavailable", f"No verdict since {since}: {problem}"
                )
            )
        return Decision("unavailable", None, problem, 2, notices=tuple(notices))
    targets = report.get("targets") or []
    for target in targets:
        notices += target_notices(target)
    if report.get("verification_failed"):
        bad = [t["version"] for t in targets if t.get("verified") is False]
        if report.get("pinned", {}).get("verified") is False:
            bad.append(report["pinned"]["firefox"] + " (pinned)")
        what = ", ".join(bad) or "a release"
        notices.append(
            Notice(
                f"verify-failed:{what}",
                "critical",
                "Firefox signature verification FAILED",
                f"Firefox {what}: Mozilla's signed checksums did not verify against the pinned key (a key rotation, an upload "
                "in progress, or tampering). Nothing will be built.",
            )
        )
        return Decision("stop", None, f"signature verification failed for {what}", 3, notices=tuple(notices))

    def newest(phase: str) -> list[dict]:
        ready = [t for t in targets if t.get("phase") == phase and t.get("verified") is True and t.get("source_sha256")]
        return sorted(ready, key=lambda t: watch_upstream.version_key(t["version"]))[-1:]

    builds = state.get("builds") or {}
    order = newest("shipped") + newest("staged")  # the release whose clock runs first, then a pre-build
    if not order:
        if targets:
            return Decision("wait", None, "newer release seen but its signature is not verified yet", 0, notices=tuple(notices))
        return Decision("idle", None, "up to date", 0, notices=tuple(notices))
    for target in order:
        version, digest, shipped = target["version"], target["source_sha256"], target["phase"] == "shipped"
        record = builds.get(version)
        if _built(record, digest):
            if not shipped:
                if target is order[-1]:
                    reason = "built from the staged release; waiting for Mozilla to publish it"
                    return Decision("wait", version, reason, 0, digest, False, tuple(notices))
                continue
            if record["phase"] == "ready-to-sign":
                continue  # done; look at a newer staged release
            body = f"Built and tested from Mozilla's signed source ({digest[:12]}…). {_clock(target)}."
            notices.append(
                Notice(f"ready:{version}:{digest}", "critical", f"READY TO SIGN: Nulavio with Firefox {version}", body)
            )
            return Decision("ready", version, "the published release matches the build", EXIT_READY, digest, True, tuple(notices))
        if record and record.get("phase") == "failed" and record.get("source_sha256") == digest and not options.retry:
            reason = f"the build failed at {record.get('failed_step') or '?'} (log {record.get('log')}); run with --retry"
            return Decision("failed-before", version, reason, 1, digest, shipped, tuple(notices))
        changed = bool(record) and record.get("source_sha256") not in (None, digest)
        reason = (
            "rebuild: Mozilla's signed digest changed"
            if changed
            else ("build" if shipped else "pre-build from the staged release")
        )
        if options.no_build:
            return Decision("would-build", version, f"{reason} (--no-build)", 0, digest, shipped, tuple(notices))
        missing = blockers(facts, options)
        if missing:
            text = "; ".join(why for _, why in missing)
            key = f"blocked:{version}:{','.join(kind for kind, _ in missing)}"
            notices.append(Notice(key, "normal", f"Security build for Firefox {version} is waiting", text))
            return Decision("blocked", version, text, 4, digest, shipped, tuple(notices))
        return Decision("build", version, reason, 0, digest, shipped, tuple(notices))
    last = order[-1]
    return Decision(
        "idle", last["version"], "ready to sign; nothing newer to build", 0, last["source_sha256"], True, tuple(notices)
    )


# --- the machine --------------------------------------------------------------------


def safebrowsing_key(env: dict) -> Path:
    """The same file scripts/build/build_nulavio.sh reads."""
    if env.get("NULAVIO_SAFEBROWSING_KEYFILE"):
        return Path(env["NULAVIO_SAFEBROWSING_KEYFILE"])
    config = Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", "~")).expanduser() / ".config")
    return config / "nulavio-build" / "google-safebrowsing.key"


def key_state(path: Path) -> str:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return "missing"
    if not os.access(path, os.R_OK):
        return "missing"
    return "ok" if mode in (0o600, 0o400) else "not-private"


def free_gib(path: Path) -> float:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1 << 30)


BUILD_SCRIPTS = ("scripts/build/build_nulavio.sh", "scripts/release/rehearse_release.sh")


def running_builds(proc: Path = Path("/proc")) -> list[int]:
    """Processes running build_nulavio.sh or rehearse_release.sh (a manual build uses the same source tree)."""
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(argument.decode(errors="replace").endswith(BUILD_SCRIPTS) for argument in arguments):
            found.append(int(entry.name))
    return sorted(found)


def _gvariant(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return '"' + cleaned.replace("\\", "\\\\").replace('"', '\\"') + '"'


def desktop_notify(notice: Notice, *, run=subprocess.run, which=shutil.which) -> None:
    """notify-send, else the freedesktop D-Bus service, else only the journal."""
    title = f"Nulavio: {notice.title}"
    print(f"nulavio-autobuild: [{notice.urgency}] {title}: {notice.body}", file=sys.stderr)
    try:
        if which("notify-send"):
            run(["notify-send", "--app-name=Nulavio", f"--urgency={notice.urgency}", title, notice.body], check=False, timeout=15)
        elif which("gdbus"):
            level = 2 if notice.urgency == "critical" else 1
            method = ["--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify"]
            arguments = [
                '"Nulavio"',
                "0",
                '""',
                _gvariant(title),
                _gvariant(notice.body),
                "[]",
                f"{{'urgency': <byte {level}>}}",
                "0",
            ]
            run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications", *method, *arguments],
                check=False,
                timeout=15,
                capture_output=True,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"nulavio-autobuild: desktop notification failed: {exc}", file=sys.stderr)


class Failure(Exception):
    def __init__(self, code: int, message: str, step: str | None = None):
        super().__init__(message)
        self.code, self.step = code, step


class Autobuild:
    """One run: watch, decide, act. Everything that touches the machine is injectable for tests."""

    def __init__(
        self,
        *,
        repo: Path,
        work: Path,
        state_path: Path,
        options: Options,
        ref: str = "main",
        notify: bool = False,
        dry_run: bool = False,
        run=subprocess.run,
        which=shutil.which,
        notifier=desktop_notify,
        watch=None,
        env: dict | None = None,
        clock=None,
        running=None,
    ):
        self.repo, self.work, self.state_path, self.options, self.ref = repo, work, state_path, options, ref
        self.notify, self.dry_run = notify, dry_run
        self.run, self.which, self.notifier = run, which, notifier
        self.env = dict(os.environ if env is None else env)
        self.clock = clock or (lambda: _dt.datetime.now(_dt.UTC))
        self.watch = watch or self._watch
        self.running = running or running_builds

    def _watch(self, now: _dt.datetime) -> dict:
        cache = None if self.dry_run else self.state_path.with_name("upstream-cache.json")
        engine = self.repo / "browser" / "build" / "engine.json"
        return watch_upstream.evaluate(engine=engine, src=watch_upstream.Network(), now=now, verify=True, state=cache)

    # -- facts and state --

    def facts(self) -> Facts:
        ac: bool | None = None
        if self.which("systemd-ac-power"):
            ac = self.run(["systemd-ac-power"], check=False).returncode == 0
        key = safebrowsing_key(self.env)
        return Facts(ac, free_gib(self.work), key_state(key), str(key), str(self.work), tuple(self.running()))

    def load_state(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("builds", {})
        state.setdefault("notified", [])
        return state

    def save_state(self, state: dict) -> None:
        if self.dry_run:
            return
        state["notified"] = state["notified"][-MAX_NOTIFIED:]
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = self.state_path.with_name(self.state_path.name + ".part")
        partial.write_text(json.dumps(state, indent=2), encoding="utf-8")
        partial.replace(self.state_path)

    def tell(self, state: dict, notices) -> None:
        for notice in notices:
            if notice.key in state["notified"]:
                continue
            if not self.dry_run:
                state["notified"].append(notice.key)
                if self.notify:
                    self.notifier(notice)
                else:
                    print(f"nulavio-autobuild: [{notice.urgency}] {notice.title}: {notice.body}", file=sys.stderr)

    # -- the build --

    def git(self, *args: str, cwd: Path | None = None) -> str:
        result = self.run(["git", "-C", str(cwd or self.repo), *args], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise Failure(1, f"git {' '.join(args)} failed: {(result.stderr or '').strip()[:300]}", "worktree")
        return result.stdout

    def build(self, version: str, digest: str, now: _dt.datetime, record: dict) -> None:
        """Worktree, verified bump, rehearsal, manifest check. Fills `record`; raises Failure."""
        if not watch_upstream.RELEASE_RE.match(version):
            raise Failure(1, f"refusing to build {version!r}")
        tree = self.work / "worktrees" / f"firefox-{version}"
        out = self.work / "rehearsal" / version
        logs = self.work / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"autobuild-{version}-{now.strftime('%Y%m%dT%H%M%SZ')}.log"
        record.update(worktree=str(tree), out=str(out), log=str(log))
        if tree.exists():
            self.git("worktree", "remove", "--force", str(tree))
        self.git("worktree", "prune")
        self.git("worktree", "add", "--detach", str(tree), self.ref)
        record["base_commit"] = self.git("rev-parse", "HEAD", cwd=tree).strip()
        bump = self.run(
            [sys.executable, "-I", str(tree / "scripts" / "release" / "bump_engine.py"), version, "--allow-staged", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if bump.returncode == 5:
            raise Failure(3, f"bump_engine.py: signature verification FAILED for {version}", "bump")
        if bump.returncode == 7:
            raise Failure(2, f"bump_engine.py could not reach Mozilla to verify {version}", "bump")
        if bump.returncode != 0:
            raise Failure(1, f"bump_engine.py exited {bump.returncode}: {(bump.stderr or '').strip()[:300]}", "bump")
        try:
            pinned = json.loads(bump.stdout)
        except ValueError as exc:
            raise Failure(1, f"bump_engine.py printed no JSON: {exc}", "bump") from exc
        if pinned.get("source_sha256") != digest:
            raise Failure(
                3, f"Mozilla's signed digest for {version} changed during the run ({pinned.get('source_sha256')})", "bump"
            )
        if out.exists():
            shutil.rmtree(out)
        env = {k: v for k, v in self.env.items() if k != "NULAVIO_ALLOW_NO_SAFEBROWSING_KEY"}  # release builds only
        command = [str(tree / "scripts" / "release" / "rehearse_release.sh"), version, str(out)]
        if self.which("systemd-inhibit"):
            command = [
                "systemd-inhibit",
                "--what=sleep",
                "--who=Nulavio",
                "--why=Nulavio security build",
                "--mode=block",
                *command,
            ]
        with open(log, "w", encoding="utf-8") as handle:
            status = self.run(command, check=False, stdout=handle, stderr=subprocess.STDOUT, env=env, cwd=str(tree)).returncode
        if status != 0:
            raise Failure(1, f"rehearsal failed (exit {status}); log {log}", failed_step(out / "rehearsal.md"))
        manifest = out / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Failure(1, f"no readable manifest.json after the rehearsal: {exc}", "manifest") from exc
        if data.get("firefox") != version or data.get("source_sha256") != digest or data.get("rehearsal") != "ok":
            raise Failure(1, "manifest.json does not match the verified release", "manifest")
        record.update(phase="built", manifest=str(manifest), report=str(out / "rehearsal.md"))

    # -- one run --

    def once(self) -> tuple[dict, int]:
        now = self.clock()
        state = self.load_state()
        report = self.watch(now)
        if report.get("exit_code") == 2:
            state.setdefault("unavailable_since", None)
            state["unavailable_since"] = state["unavailable_since"] or watch_upstream._stamp(now)
        else:
            state["unavailable_since"] = None
        facts = self.facts()
        decision = decide(state, report, facts, self.options, now)
        result = {
            "action": decision.action,
            "version": decision.version,
            "reason": decision.reason,
            "source_sha256": decision.digest,
            "watch_state": report.get("state"),
            "notices": [n.title for n in decision.notices if n.key not in state["notified"]],
        }
        self.tell(state, decision.notices)
        code = decision.exit_code
        record = state["builds"].get(decision.version or "", {})
        if decision.action == "ready" and not self.dry_run:
            record.update(phase="ready-to-sign", ready_at=watch_upstream._stamp(now))
        elif decision.action == "build" and not self.dry_run:
            version, digest = decision.version, decision.digest
            self.tell(state, [Notice(f"building:{version}:{digest}", "normal", f"Building Firefox {version}", decision.reason)])
            record = {"phase": "building", "source_sha256": digest, "started_at": watch_upstream._stamp(now)}
            state["builds"][version] = record
            self.save_state(state)
            code = self._build_and_report(state, decision, record, now)
            if record["phase"] == "failed":
                result["reason"] = record["error"]
        result.update(
            phase=record.get("phase", decision.action), **{k: record.get(k) for k in ("worktree", "report", "manifest", "log")}
        )
        self.save_state(state)
        return result, code

    def _build_and_report(self, state: dict, decision: Decision, record: dict, now: _dt.datetime) -> int:
        version, digest = decision.version, decision.digest
        try:
            try:
                self.build(version, digest, now, record)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:  # not "building" forever: a failure
                raise Failure(1, f"autobuild error: {exc.__class__.__name__}: {exc}", "autobuild") from exc
        except Failure as exc:
            record["finished_at"] = watch_upstream._stamp(self.clock())
            if exc.code == 2:  # could not reach Mozilla: try again next run
                state["builds"].pop(version, None)
                record.update(phase="interrupted", error=str(exc))
                return 2
            text = f"{exc} (step {exc.step or '?'})"
            record.update(phase="failed", failed_step=exc.step, error=text)
            title = f"Build of Firefox {version} FAILED"
            self.tell(state, [Notice(f"failed:{version}:{digest}:{exc.step}", "critical", title, text)])
            return exc.code
        record["finished_at"] = watch_upstream._stamp(self.clock())
        if decision.shipped:
            record.update(phase="ready-to-sign", ready_at=record["finished_at"])
            body = f"Built and tested ({digest[:12]}…); worktree {record['worktree']}."
            self.tell(
                state, [Notice(f"ready:{version}:{digest}", "critical", f"READY TO SIGN: Nulavio with Firefox {version}", body)]
            )
            return EXIT_READY
        body = f"Built from the staged release; ready to sign once Mozilla publishes. Worktree {record['worktree']}."
        self.tell(state, [Notice(f"built:{version}:{digest}", "normal", f"Firefox {version} pre-built", body)])
        return 0

    def prune(self, pinned: str) -> list[str]:
        """Remove this tool's worktrees and rehearsal outputs for releases older than `pinned` (never the build tree)."""
        removed, key = [], watch_upstream.version_key
        for kind in ("worktrees", "rehearsal"):
            for path in sorted((self.work / kind).glob("*")):
                version = path.name.removeprefix("firefox-")
                older = watch_upstream.RELEASE_RE.match(version) and key(version) < key(pinned)
                if not older:
                    continue
                if not self.dry_run:
                    if kind == "worktrees":
                        self.git("worktree", "remove", "--force", str(path))
                    else:
                        shutil.rmtree(path)
                removed.append(str(path))
        return removed


def failed_step(report: Path) -> str | None:
    """The step rehearse_release.sh marked as failed in rehearsal.md."""
    try:
        match = re.search(r"^\| ([\w-]+) \| [^|]* \| failed", report.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    return match.group(1) if match else None


def acquire(lock_path: Path):
    """An exclusive flock, or None when another run holds it."""
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(lock_path, "a")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def default_paths(env: dict) -> tuple[Path, Path, Path]:
    home = Path(env.get("HOME") or Path.home())
    state = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state") / "nulavio" / "autobuild.json"
    build = Path(env.get("NULAVIO_BUILD_DIR") or Path(env.get("XDG_CACHE_HOME") or home / ".cache") / "nulavio-build")
    runtime = Path(env["XDG_RUNTIME_DIR"]) if env.get("XDG_RUNTIME_DIR") else state.parent
    return state, build / "autobuild", runtime / "nulavio-autobuild.lock"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notify", action="store_true", help="desktop notifications (always also on stderr)")
    parser.add_argument("--dry-run", action="store_true", help="decide and print; change nothing, notify nobody")
    parser.add_argument("--no-build", action="store_true", help="detect and notify only")
    parser.add_argument("--retry", action="store_true", help="build again a release whose build failed")
    parser.add_argument("--build-on-battery", action="store_true")
    parser.add_argument("--min-free-gib", type=float, default=DEFAULT_MIN_FREE_GIB)
    parser.add_argument("--repo", type=Path, default=HERE.parents[1], help="the local clone (default: this one)")
    parser.add_argument("--ref", default="main", help="local ref to build from (never fetched)")
    parser.add_argument("--work", type=Path, help="work directory (default: $NULAVIO_BUILD_DIR/autobuild)")
    parser.add_argument("--state", type=Path, help="state file (default: $XDG_STATE_HOME/nulavio/autobuild.json)")
    parser.add_argument("--prune", action="store_true", help="remove this tool's worktrees and outputs of older releases")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", args.ref) or args.ref.startswith("-"):
        parser.error("--ref must be a plain local ref such as main")
    state_path, work, lock_path = default_paths(dict(os.environ))
    options = Options(args.build_on_battery, args.min_free_gib, args.no_build, args.retry)
    runner = Autobuild(
        repo=args.repo.resolve(),
        work=(args.work or work).resolve(),
        state_path=args.state or state_path,
        options=options,
        ref=args.ref,
        notify=args.notify,
        dry_run=args.dry_run,
    )
    lock = acquire(lock_path)
    if lock is None:
        print(json.dumps({"action": "skipped", "reason": "another autobuild run holds the lock"}))
        return 0
    try:
        if args.prune:
            pinned, _ = watch_upstream.load_engine(runner.repo / "browser" / "build" / "engine.json")
            print(json.dumps({"action": "prune", "removed": runner.prune(pinned)}))
            return 0
        result, code = runner.once()
    finally:
        lock.close()
    print(json.dumps({**result, "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
