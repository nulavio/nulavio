"""`nulavio run --confined`: the real engine inside bubblewrap (docs/security/phase5-spikes.md).

Checked from inside the browser (chrome code): files outside the profile and
Downloads are not there, the profile is writable, /dev is bubblewrap's own,
and the engine's own content sandbox is as strong as without confinement; from outside: every content
process runs under seccomp, and a running profile is not reopened "confined"
through the running instance. With the Downloads and data folders reached
through symlinks, the confined browser uses the real profile and a download
lands in the real folder (#711).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "launcher"))
import harness

from nulavio_launcher import confine

ROOT = Path(__file__).resolve().parents[2]


def bwrap_works() -> bool:
    try:
        confine.check()
        return True
    except confine.ConfineError:
        return False


def descendants(pid: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            children.setdefault(parent, []).append(int(entry.name))
    found, todo = [], [pid]
    while todo:
        current = todo.pop()
        found.append(current)
        todo += children.get(current, [])
    return found


@unittest.skipUnless(harness.engine_available() and bwrap_works(), "needs a Gecko engine and a working bubblewrap")
class ConfinedRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.Session(profile="confined", run_args=("--confined",))
        cls.secret = cls.session.tmp / "outside-the-profile.txt"
        cls.secret.write_text("artificial, never a real secret\n")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def chrome_async(self, body: str, args=()):
        script = "const done = arguments[arguments.length - 1];"
        script += "(async () => {" + body + "})().then(done, e => done({error: String(e)}));"
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(script, list(args))
        finally:
            self.m.set_context("content")

    def test_01_started_inside_bubblewrap(self):
        command = Path(f"/proc/{self.session.process.pid}/cmdline").read_bytes().split(b"\0")
        self.assertTrue(command[0].decode().endswith("bwrap"), command[:2])

    def test_02_the_browser_sees_only_its_profile_and_downloads(self):
        # The session bus and the user's service manager, where the host has them, are not there inside.
        runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        session = [str(Path(runtime) / n) for n in ("bus", "systemd") if runtime and (Path(runtime) / n).exists()]
        seen = self.chrome_async(
            "const [secret, repo, profile, downloads, session] = arguments;"
            "const reachable = [];"
            "for (const path of session) { if (await IOUtils.exists(path)) reachable.push(path); }"
            "return {secret: await IOUtils.exists(secret), repo: await IOUtils.exists(repo),"
            " profileWritable: await IOUtils.writeUTF8(profile, 'x').then(() => true, () => false),"
            " downloads: await IOUtils.exists(downloads), session: reachable};",
            [str(self.secret), str(ROOT / "README.md"), str(self.session.profile_dir / "confined-probe.txt"),
             str(confine.download_dir()), session],
        )  # fmt: skip
        repo_in_home = ROOT.resolve().is_relative_to(Path.home().resolve())
        expected = {"secret": False, "repo": not repo_in_home, "profileWritable": True, "downloads": True, "session": []}
        self.assertEqual(seen, expected)

    def test_02b_dev_is_bubblewraps_own_with_the_gpu_and_cameras(self):
        # No input devices, terminals of the session or other hardware inside; the GPU and cameras when present.
        seen = self.chrome_async(
            "return {dev: (await IOUtils.getChildren('/dev')).map(p => PathUtils.filename(p)),"
            " pts: (await IOUtils.getChildren('/dev/pts')).map(p => PathUtils.filename(p))};"
        )
        own = {"console", "core", "fd", "full", "null", "ptmx", "pts", "random", "shm", "stderr", "stdin", "stdout",
               "tty", "urandom", "zero"}  # fmt: skip
        self.assertLessEqual(set(seen["dev"]), own | {p.name for p in confine.device_nodes()}, seen["dev"])
        self.assertEqual(seen["pts"], ["ptmx"])

    def test_03_the_engine_sandbox_is_unchanged(self):
        sandbox = self.chrome_async(
            'const {Troubleshoot} = ChromeUtils.importESModule("resource://gre/modules/Troubleshoot.sys.mjs");'
            "const s = (await Troubleshoot.snapshot()).sandbox;"
            "return {level: s.contentSandboxLevel, effective: s.effectiveContentSandboxLevel,"
            " userns: s.hasUserNamespaces, seccomp: s.hasSeccompBPF};"
        )
        self.assertEqual(sandbox["effective"], sandbox["level"], sandbox)
        self.assertTrue(sandbox["seccomp"])
        self.m.navigate("data:text/html,<p id=x>ok</p>")
        self.assertEqual(self.m.execute("return document.getElementById('x').textContent;"), "ok")

        def seccomp_of_content_processes() -> list[str]:
            found = []
            for pid in descendants(self.session.process.pid):
                try:
                    status = Path(f"/proc/{pid}/status").read_text()
                    argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                except OSError:
                    continue
                # Web content processes; with the engine's fork server their arguments become one string ending in "tab".
                line = b" ".join(a for a in argv if a)
                if b"-contentproc" in line and line.endswith(b" tab"):
                    found.append(re.search(r"Seccomp:\s+(\d)", status).group(1))
            return found

        # A process the engine has just started applies its filter while it starts up, so one snapshot
        # in which every web content process is filtered is required; one running unfiltered never passes.
        samples: list[list[str]] = []

        def all_filtered() -> bool:
            samples.append(seccomp_of_content_processes())
            return bool(samples[-1]) and set(samples[-1]) == {"2"}

        self.assertTrue(harness.wait_until(all_filtered, timeout=30), f"seccomp modes seen: {samples[-3:]}")

    def test_04_an_open_profile_is_not_reopened_confined(self):
        # (--allow-weakened: the test's own Marionette prefs are a Guard finding, checked before this.)
        result = self.session.nulavio("run", "--confined", "--dry-run", "--allow-weakened", "--profile", "confined", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("already open", result.stderr)


@unittest.skipUnless(harness.engine_available() and bwrap_works(), "needs a Gecko engine and a working bubblewrap")
class ConfinedThroughLinksTest(unittest.TestCase):
    """~/Downloads and ~/.local/share as links to another disk (#711): both links are in the hidden home folder."""

    @classmethod
    def setUpClass(cls):
        cls.session = session = harness.Session(profile="confined-links", run_args=("--confined",))
        cls.disk, cls.user = session.tmp / "disk", session.tmp / "user"
        (cls.disk / "share").mkdir(parents=True)
        (cls.disk / "Downloads").mkdir()
        (cls.user / ".local").mkdir(parents=True)
        (cls.user / "Downloads").symlink_to(cls.disk / "Downloads")
        (cls.user / ".local/share").symlink_to(cls.disk / "share")
        if session.home.exists():  # the harness's seeded cache
            shutil.move(session.home, cls.disk / "share/nulavio")
        session.home = cls.user / ".local/share/nulavio"  # the data folder, reached through the link
        session.env.update(HOME=str(cls.user), NULAVIO_HOME=str(session.home))
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            session.env.pop(name, None)  # the engine finds the Downloads folder from this home's settings
        cls.m = session.start()  # the Marionette port file is read from the real profile

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def test_01_the_real_profile_is_used(self):
        self.m.set_context("chrome")
        try:
            seen = self.m.execute(
                "const profile = Services.dirsvc.get('ProfD', Ci.nsIFile).path;"
                "return IOUtils.writeUTF8(PathUtils.join(profile, 'linked-probe.txt'), 'x').then(() => profile);"
            )
        finally:
            self.m.set_context("content")
        self.assertEqual(seen, str(self.session.profile_dir))
        self.assertTrue((self.disk / "share/nulavio/data/profiles/confined-links/linked-probe.txt").is_file())

    def test_02_a_download_lands_in_the_real_downloads_folder(self):
        script = (
            "const done = arguments[arguments.length - 1];"
            "(async () => {"
            'const {Downloads} = ChromeUtils.importESModule("resource://gre/modules/Downloads.sys.mjs");'
            "const dir = await Downloads.getSystemDownloadsDirectory();"
            "const target = PathUtils.join(dir, 'confined-download.txt');"
            "const download = await Downloads.createDownload({source: 'data:text/plain,confined', target});"
            "await download.start();"
            "return dir;"
            "})().then(done, e => done({error: String(e)}));"
        )
        self.m.set_context("chrome")
        try:
            folder = self.m.execute_async(script, [])
        finally:
            self.m.set_context("content")
        self.assertEqual(folder, str(self.user / "Downloads"))
        self.assertEqual((self.disk / "Downloads/confined-download.txt").read_text(), "confined")


if __name__ == "__main__":
    unittest.main()
