#!/usr/bin/env python3
"""Supervise a bounded Podman build; lease expiry also stops children after supervisor loss.

Called by build_nulavio.sh. --inside is the container entry point, never a host build.
Logs, telemetry, heartbeat and the exact container id remain in --control.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

GIB = 1024**3
HERE = Path(__file__).resolve().parent


@dataclasses.dataclass
class Config:
    memory_gib: int = 16
    jobs: int = 2
    cargo_jobs: int = 1
    cpus: int = 2
    min_available_gib: float = 4
    psi_limit: float = 10
    psi_seconds: float = 30
    interval: float = 5
    lease_seconds: float = 30

    @classmethod
    def from_env(cls, env):
        config = cls(
            memory_gib=int(env.get("NULAVIO_BUILD_MEMORY_GIB", "16")),
            jobs=int(env.get("MOZ_PARALLEL_BUILD", "2")),
            min_available_gib=float(env.get("NULAVIO_BUILD_MIN_AVAILABLE_GIB", "4")),
            psi_limit=float(env.get("NULAVIO_BUILD_PSI_LIMIT", "10")),
            psi_seconds=float(env.get("NULAVIO_BUILD_PSI_SECONDS", "30")),
        )
        if not 1 <= config.memory_gib <= 16 or config.jobs not in (1, 2) or env.get("CARGO_BUILD_JOBS", "1") != "1":
            raise ValueError("build budget: at most 16 GiB, MOZ_PARALLEL_BUILD=1 or 2, CARGO_BUILD_JOBS=1")
        if not 1 <= config.min_available_gib <= 16 or not 0 < config.psi_limit <= 100 or not 0 < config.psi_seconds <= 300:
            raise ValueError("invalid memory/PSI thresholds")
        return config


class PressurePolicy:
    def __init__(self, *, min_available, psi_limit, psi_seconds):
        self.min_available, self.psi_limit, self.psi_seconds = min_available, psi_limit, psi_seconds
        self.since = None

    def reason(self, now, available, psi):
        if available < self.min_available:
            return f"available memory below reserve ({available / GIB:.2f} GiB)"
        if psi > self.psi_limit:
            if self.since is None:
                self.since = now
            if now - self.since >= self.psi_seconds:
                return f"memory pressure full avg10 > {self.psi_limit}% for {self.psi_seconds}s"
        else:
            self.since = None
        return None


def retry_jobs(config, previous):
    if previous.get("oom") or previous.get("memory_failure"):
        if previous.get("jobs") == 1:
            raise ValueError("previous memory failure at one job; inspect logs before another attempt")
        return 1
    return min(config.jobs, previous.get("jobs", config.jobs))


def atomic_json(path, data):
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps(data) + "\n")
    partial.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def host_sample():
    mem = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()}
    full = next(line for line in Path("/proc/pressure/memory").read_text().splitlines() if line.startswith("full "))
    psi = float(dict(field.split("=") for field in full.split()[1:])["avg10"])
    cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    return {"available": mem["MemAvailable"], "swap_used": mem["SwapTotal"] - mem["SwapFree"], "psi_full_avg10": psi, "cpu": cpu}


def cpu_percent(before, after):
    delta = [b - a for a, b in zip(before, after, strict=True)]
    total = sum(delta)
    if not total:
        return 0, 0
    return round(100 * (delta[2] + delta[5] + delta[6]) / total, 2), round(100 * delta[4] / total, 2)


def call(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=25)


def preflight(config):
    sample = host_sample()
    if sample["available"] < config.min_available_gib * GIB or sample["psi_full_avg10"] > config.psi_limit:
        raise ValueError(f"host lacks build headroom: {sample}")
    running = call("podman", "ps", "--format", "{{.Names}}").stdout.splitlines()
    if any(name.startswith("nulavio-build-") for name in running):
        raise ValueError("another Nulavio build container is active; do not overlap builds")


def terminate(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        except ProcessLookupError:
            process.wait(timeout=10)


def stop_container(cid):
    try:
        call("podman", "stop", "--time", "10", cid, check=False)
    except (OSError, subprocess.SubprocessError):
        call("podman", "kill", cid, check=False)


def inside(control, config, command):
    """Fail closed before exec, and guard the entire workload even without the host client."""
    root = Path("/sys/fs/cgroup")
    expected = {"memory.max": config.memory_gib * GIB, "memory.swap.max": 0, "memory.oom.group": 1, "pids.max": 512}
    actual = {key: int((root / key).read_text()) for key in expected}
    quota, period = (root / "cpu.max").read_text().split()
    if actual != expected or quota == "max" or int(quota) / int(period) > config.cpus:
        raise ValueError(f"cgroup limits not applied: {actual}, cpu={quota}/{period}")
    atomic_json(control / "limits.json", {**actual, "cpu.max": [int(quota), int(period)], "config": dataclasses.asdict(config)})
    process = subprocess.Popen(command, start_new_session=True)
    signal_reason = []
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda signum, _frame: signal_reason.append(f"signal {signum}"))
    reason = None
    try:
        while process.poll() is None:
            events = {
                key: int(value) for key, value in (line.split() for line in (root / "memory.events").read_text().splitlines())
            }
            processes = []
            for path in Path("/proc").glob("[0-9]*/comm"):
                try:
                    name = path.read_text().strip()
                    if name in ("rustc", "cargo", "clang", "clang++", "cc1", "cc1plus", "gmake", "make", "ninja", "ld.lld"):
                        entry = {"pid": int(path.parent.name), "name": name}
                        if name in ("cargo", "make", "gmake", "ninja"):
                            entry["argv"] = (path.parent / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                        processes.append(entry)
                except (OSError, ValueError):
                    continue
            atomic_json(
                control / "inside.json",
                {
                    "time": time.time(),
                    "memory_current": int((root / "memory.current").read_text()),
                    "events": events,
                    "processes": processes,
                },
            )
            if time.time() - (control / "heartbeat").stat().st_mtime > config.lease_seconds:
                reason = "supervisor heartbeat expired"
            elif sum(p["name"] == "rustc" for p in processes) > 1:
                reason = "more than one simultaneous rustc"
            elif events.get("oom", 0):
                reason = "cgroup OOM event"
            elif signal_reason:
                reason = signal_reason[0]
            if reason:
                print(f"build guard: {reason}", flush=True)
                atomic_json(control / "inside-stop.json", {"reason": reason, "oom": bool(events.get("oom", 0))})
                terminate(process)
                return 75
            time.sleep(1)
        return process.returncode
    finally:
        terminate(process)


def supervise(control, config, options):
    control.mkdir(parents=True, exist_ok=False)
    (control / "heartbeat").touch()
    atomic_json(control / "config.json", dataclasses.asdict(config))
    name = f"nulavio-build-{os.getpid()}-{int(time.time())}"
    flags = [
        "--name",
        name,
        "--init",
        "--memory",
        f"{config.memory_gib}g",
        "--memory-swap",
        f"{config.memory_gib}g",
        "--cpus",
        str(config.cpus),
        "--pids-limit",
        "512",
        "--cgroup-conf=memory.oom.group=1",
        "--restart=no",
        "--timeout=86400",
        "-v",
        f"{HERE}:/nulavio-build:ro,Z",
        "-v",
        f"{control}:/nulavio-control:Z",
        "-e",
        f"MOZ_PARALLEL_BUILD={config.jobs}",
        "-e",
        "CARGO_BUILD_JOBS=1",
        "-e",
        "CMAKE_BUILD_PARALLEL_LEVEL=1",
        "-e",
        f"MAKEFLAGS=-j{config.jobs}",
        "-e",
        "RAYON_NUM_THREADS=1",
        "-e",
        "OMP_NUM_THREADS=1",
        "-e",
        "OPENBLAS_NUM_THREADS=1",
        "-e",
        "NUM_JOBS=1",
        "-e",
        "NINJAFLAGS=-j1",
        "-e",
        f"NULAVIO_BUILD_MEMORY_GIB={config.memory_gib}",
        "--entrypoint",
        "python3",
    ]
    # options contains mounts, environment, image, then the original command.
    image_index = options.index("--")
    mounts, command = options[:image_index], options[image_index + 1 :]
    image = mounts.pop()
    cid = call(
        "podman",
        "create",
        *flags,
        *mounts,
        image,
        "-B",
        "-I",
        "/nulavio-build/build_guard.py",
        "--inside",
        "--control",
        "/nulavio-control",
        "--",
        *command,
    ).stdout.strip()
    (control / "container-id").write_text(cid + "\n")
    process = None
    reason, oom = None, False
    signals = []
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda signum, _frame: signals.append(f"signal {signum}"))
    policy = PressurePolicy(
        min_available=config.min_available_gib * GIB, psi_limit=config.psi_limit, psi_seconds=config.psi_seconds
    )
    previous_cpu = host_sample()["cpu"]
    try:
        with (control / "build.log").open("w") as log, (control / "telemetry.jsonl").open("w") as telemetry:
            process = subprocess.Popen(
                ["podman", "start", "--attach", cid], stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            print(f"build guard: container={cid} logs={control}", flush=True)
            while process.poll() is None:
                sample = host_sample()
                current_cpu = sample.pop("cpu")
                sample["kernel_pct"], sample["iowait_pct"] = cpu_percent(previous_cpu, current_cpu)
                previous_cpu = current_cpu
                sample["time"] = datetime.datetime.now(datetime.UTC).isoformat()
                sample["container"] = read_json(control / "inside.json")
                telemetry.write(json.dumps(sample) + "\n")
                telemetry.flush()
                reason = signals[0] if signals else policy.reason(time.monotonic(), sample["available"], sample["psi_full_avg10"])
                if sample["container"].get("events", {}).get("oom", 0):
                    reason, oom = "cgroup OOM event", True
                if reason:
                    # stop also targets descendants; never kill by executable name.
                    stop_container(cid)
                    break
                (control / "heartbeat").touch()
                time.sleep(config.interval)
            process.wait(timeout=20)
            state = json.loads(call("podman", "inspect", cid).stdout)[0]["State"]
            inner_stop = read_json(control / "inside-stop.json")
            oom = oom or state.get("OOMKilled", False) or inner_stop.get("oom", False)
            reason = reason or inner_stop.get("reason") or ("cgroup OOM event" if oom else None)
            code = 75 if reason else int(state["ExitCode"])
            result = {
                "exit_code": code,
                "reason": reason,
                "oom": oom,
                "jobs": config.jobs,
                "container": cid,
                "memory_failure": oom or bool(reason and ("memory" in reason or "pressure" in reason)),
            }
            atomic_json(control / "result.json", result)
            atomic_json(control.parent / "last-result.json", result)
            print(f"build guard: {json.dumps(result)}", flush=True)
            return code
    finally:
        # Record failures even if the attached client/inspect fails. Never retry an
        # unclassified supervisor failure automatically with the same configuration.
        if not (control / "result.json").exists():
            state, inner_stop = {}, read_json(control / "inside-stop.json")
            try:
                state = json.loads(call("podman", "inspect", cid).stdout)[0]["State"]
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            oom = oom or state.get("OOMKilled", False) or inner_stop.get("oom", False)
            result = {
                "exit_code": 75,
                "reason": reason or inner_stop.get("reason") or str(sys.exception()),
                "oom": oom,
                "memory_failure": True,
                "jobs": config.jobs,
                "container": cid,
            }
            atomic_json(control / "result.json", result)
            atomic_json(control.parent / "last-result.json", result)
        try:
            stop_container(cid)
        finally:
            if process:
                terminate(process)
            call("podman", "rm", cid, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("options", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    config = Config.from_env(os.environ)
    options = args.options[1:] if args.options[:1] == ["--"] else args.options
    if args.inside:
        return inside(args.control, config, options)
    # One lock across worktrees, versions and cache directories (not a system setting).
    lock_dir = Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache"))) / f"nulavio-build-{os.getuid()}"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    with (lock_dir / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(config)
        if args.check:
            print("build guard: host headroom and no overlapping build: OK")
            return 0
        config.jobs = retry_jobs(config, read_json(args.control.parent / "last-result.json"))
        return supervise(args.control, config, options)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"build guard: refusing/stopping build: {exc}", file=sys.stderr)
        sys.exit(75)
