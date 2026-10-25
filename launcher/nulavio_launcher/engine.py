"""Locate the Gecko engine and build a safe command line for it.

Track A (preview) runs the distribution-packaged, unmodified Firefox. The
launcher never forwards arbitrary engine flags: only a validated URL and a
fixed set of options, so remote-control or debugging switches cannot be
smuggled in through a desktop file or a crafted link.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

# Oldest engine major version the preview is tested against. Raise it when a
# new ESR becomes the floor (docs/architecture/update-policy.md).
MIN_ENGINE_MAJOR = 140
APP_ID = "nulavio-preview"
ALLOWED_URL_SCHEMES = {"http", "https", "file"}
FORBIDDEN_FLAGS = {
    "--marionette",
    "-marionette",
    "--remote-debugging-port",
    "--remote-allow-system-access",
    "--start-debugger-server",
    "-start-debugger-server",
    "--jsconsole",
    "--jsdebugger",
    "--headless",
}


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class Engine:
    path: Path
    version: str
    vendor: str

    @property
    def major(self) -> int:
        match = re.match(r"(\d+)", self.version)
        return int(match.group(1)) if match else 0

    @property
    def label(self) -> str:
        return f"{self.vendor} {self.version}"


# Real engine binaries, checked before $PATH. Distribution wrappers (e.g.
# Fedora's /usr/bin/firefox shell script) are bypassed on purpose: they write
# langpack links into the user's own Firefox config dir, force
# MOZ_APP_REMOTINGNAME=org.mozilla.firefox and set MOZ_ALLOW_DOWNGRADE=1,
# which disables the engine's profile-downgrade protection.
KNOWN_BINARIES = (
    Path("/usr/lib64/firefox/firefox"),  # Fedora RPM
    Path("/usr/lib/firefox/firefox"),  # Mozilla APT repository (.deb), Debian
    Path("/opt/firefox/firefox"),
)


def _is_script(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _candidates() -> list[Path]:
    explicit = os.environ.get("NULAVIO_ENGINE")
    if explicit:
        return [Path(explicit)]
    found = [p for p in KNOWN_BINARIES if p.exists()]
    on_path = shutil.which("firefox")
    if on_path:
        found.append(Path(on_path))
    return found


def find_engine() -> Engine:
    candidates = _candidates()
    if not candidates:
        raise EngineError("no Gecko engine found: install the distribution 'firefox' package or set NULAVIO_ENGINE")
    path = None
    for candidate in candidates:
        resolved = candidate.resolve()
        if "/snap/" in str(resolved):
            raise EngineError(
                "the Snap Firefox cannot read profiles under hidden directories such as ~/.local/share; "
                "install Firefox from the Mozilla APT repository or set NULAVIO_ENGINE"
            )
        if resolved.exists() and not _is_script(resolved):
            path = resolved
            break
    if path is None:
        path = candidates[0].resolve()
    if not os.access(path, os.X_OK):
        raise EngineError(f"engine is not executable: {path}")
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "MOZ_HEADLESS": "1"},
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EngineError(f"could not query engine version: {exc}") from exc
    vendor, version = parse_version_output(result.stdout)
    return Engine(path=path, version=version, vendor=vendor)


# `<engine> --version` prints "<Vendor> <Name> <Version>". Track A runs
# Mozilla's Firefox; Track B builds print "Nulavio Nulavio <version>".
_VERSION_RE = re.compile(r"^(?P<product>Mozilla Firefox|Nulavio(?: Nulavio)?) (?P<version>\d+[\w.]*)\s*$", re.M)


def parse_version_output(text: str) -> tuple[str, str]:
    match = _VERSION_RE.search(text)
    if not match:
        raise EngineError(f"unrecognised engine version output: {text.strip()[:120]!r}")
    product = "Nulavio" if match.group("product").startswith("Nulavio") else match.group("product")
    return product, match.group("version")


def check_supported(engine: Engine) -> None:
    if engine.major < MIN_ENGINE_MAJOR:
        raise EngineError(f"{engine.label} is older than the supported floor ({MIN_ENGINE_MAJOR}); update the engine package")


def validate_url(url: str) -> str:
    if url.startswith("-"):
        raise EngineError("URL must not start with '-'")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise EngineError(f"only {', '.join(sorted(ALLOWED_URL_SCHEMES))} URLs can be opened from the launcher")
    if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
        raise EngineError("URL has no host")
    if any(ch in url for ch in "\r\n\x00"):
        raise EngineError("URL contains control characters")
    return url


def build_command(engine: Engine, profile_dir: Path, url: str | None = None, private: bool = False) -> list[str]:
    command = [
        str(engine.path),
        "--profile",
        str(profile_dir),
        # Wayland app_id / X11 WM_CLASS so the desktop shows the Nulavio entry.
        "--name",
        APP_ID,
        "--class",
        APP_ID,
    ]
    if private:
        command.append("--private-window")
        if url:
            command.append(validate_url(url))
    elif url:
        command.append(validate_url(url))
    leaked = FORBIDDEN_FLAGS.intersection(command)
    if leaked:
        raise EngineError(f"forbidden engine flags: {sorted(leaked)}")
    return command


def launch_env() -> dict[str, str]:
    """Environment for the engine: inherit the session, drop risky knobs.

    Removes variables that disable engine sandboxes (MOZ_DISABLE_*SANDBOX*),
    relax sandbox behaviour (MOZ_SANDBOX_*), enable remote control, or skip
    the profile-downgrade check. Sets the remoting name (Wayland app_id) so
    the desktop associates windows with nulavio-preview.desktop.
    """
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if (
            (upper.startswith("MOZ_") and "SANDBOX" in upper)
            or upper.startswith(("MOZ_MARIONETTE", "MOZ_REMOTE"))
            or upper in {"MOZ_HEADLESS", "MOZ_ALLOW_DOWNGRADE"}
        ):
            env.pop(key)
    env["MOZ_APP_REMOTINGNAME"] = APP_ID
    return env


def langpack(engine: Engine, locale: str) -> Path | None:
    """Distribution-provided, Mozilla-signed language pack matching the engine."""
    if not re.fullmatch(r"[a-z]{2,3}(-[A-Z]{2})?", locale):
        return None
    candidate = engine.path.parent / "langpacks" / f"langpack-{locale}@firefox.mozilla.org.xpi"
    return candidate if candidate.is_file() else None
