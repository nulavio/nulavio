"""The release scripts' own protections, checked by running the scripts (#223).

The independent review of #214 removed these protections one at a time and every unit
test still passed, because the tests read the scripts' text. Here each script runs for
real, with stand-ins first on PATH where the real thing needs a container, the network
or a key: a `podman` that writes the APT indexes a container would (or replays an apt
answer), a `curl` and a `sleep` for check_published.sh, the stand-in `aws` of
test_openpgp_sign (the role KMS plays, with a throwaway gpg key), and, beside it, a
`python3` that runs the real openpgp_sign.py and then spoils what it wrote. That
`python3` is on the signer's PATH only (sign_apt_repo.sh puts NULAVIO_TEST_AWS_DIR/bin
first for the signer alone), so every check the script makes after signing runs with
the real tools.

Mutations each test below must catch (rerun them after a change to the scripts):

sign_apt_repo.sh
  1. `gpgv ... "$dists/InRelease" ... || { ...; exit 1; }` -> `|| true`
  2. the `cmp -s "$tmp/signed" "$dists/Release" || ...` line deleted
  3. the `[[ -z $(ls -A "$out") ]] || ...` line deleted
  4. the host-side check of pool and index (`python3 -I - ... <<'PY' || ...`) -> `|| true`
  5. the apt check before upload (`podman run ... :/repo:ro ... || { ...; exit 1; }`) -> `|| true`
  6. `gpgv ... "$dists/Release.gpg" "$dists/Release" ... || ...` -> `|| true`
publish_release.sh
  7. `[[ -n $(field debs) ]] || { ...; exit 2; }` deleted
check_published.sh
  8. `if matches "$name" "$got"; then` -> `if [[ -n $got ]]; then` (any output accepted)
  9. in matches(), the dnf case loosened to `[[ $2 == "$expected"* ]]`
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RELEASE))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

from test_openpgp_sign import FAKE_AWS, secret_numbers, spki  # noqa: E402
from verify_firefox_release import SIGNING_SUBKEYS  # noqa: E402

PYTHON = sys.executable
IMAGE = "registry.example.invalid/ubuntu:26.10@sha256:" + "0" * 64
VERSION = "160.0-0.4"
DEB_NAME = f"nulavio_{VERSION}_amd64.deb"

# Writes what the container steps of the release scripts would, or answers for them.
PODMAN = textwrap.dedent(
    """\
    import hashlib, json, os, sys
    from pathlib import Path
    args = sys.argv[1:]
    mode = os.environ.get("STUB_PODMAN", "")
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write(json.dumps(["podman", *args]) + "\\n")
    mounts = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-v"]
    if any(m.endswith(":/repo:ro") for m in mounts):  # sign_apt_repo.sh: apt update and download
        sys.exit(1 if mode == "apt-refuses" else 0)
    repo = next((m.rsplit(":", 1)[0] for m in mounts if m.endswith(":/repo")), None)
    if repo:  # sign_apt_repo.sh: apt-ftparchive
        out = Path(repo)
        if mode == "extra-package":
            (out / "pool/main/n/nulavio/nulavio_160.0-0.3_amd64.deb").write_bytes(b"an older one")
        entries = []
        for deb in sorted((out / "pool").rglob("*.deb")):
            _, version, arch = deb.name[: -len(".deb")].split("_")
            sha = "0" * 64 if mode == "wrong-hash" else hashlib.sha256(deb.read_bytes()).hexdigest()
            entries.append(f"Package: nulavio\\nVersion: {version}\\nArchitecture: {arch}\\n"
                           f"Filename: pool/main/n/nulavio/{deb.name}\\nSHA256: {sha}\\n")
        index = out / "dists/stable/main/binary-amd64"
        index.mkdir(parents=True)
        (index / "Packages").write_text("\\n".join(entries))
        (out / "dists/stable/Release").write_text("Origin: Nulavio\\nLabel: Nulavio\\nSuite: stable\\n"
                                                  "Codename: stable\\nArchitectures: amd64\\nComponents: main\\n")
        sys.exit(0)
    if any(arg.startswith("REPO_FILE=") for arg in args):  # check_published.sh: dnf install
        print(os.environ.get("STUB_DNF", ""))
        sys.exit(0)
    if any(m.endswith(":/nulavio.sources:ro") for m in mounts):  # check_published.sh: apt install
        print(os.environ.get("STUB_APT", ""))
        sys.exit(0)
    sys.exit(3)
    """
)

# On the signer's PATH only: runs the real openpgp_sign.py, then spoils what STUB_SIGNER says.
SIGNER = textwrap.dedent(
    """\
    import os, subprocess, sys, tempfile
    args = sys.argv[1:]
    mode = os.environ.get("STUB_SIGNER", "")
    clearsign = "--clearsign" in args
    output = args[args.index("-o") + 1]
    if (mode == "inrelease-other-text" and clearsign) or (mode == "release-gpg-other-text" and not clearsign):
        other = tempfile.NamedTemporaryFile(delete=False, suffix=".Release")
        other.write(open(args[-1], "rb").read() + b"Date: a different day\\n")
        other.close()
        args[-1] = other.name
    done = subprocess.run([sys.executable, *args])
    if done.returncode == 0 and mode == "inrelease-bad-signature" and clearsign:
        text = open(output).read()
        open(output, "w").write(text.replace("Suite: stable", "Suite: stabla", 1))
    sys.exit(done.returncode)
    """
)


def script(path: Path, body: str) -> None:
    path.write_text(f"#!{PYTHON} -I\n{body}" if not body.startswith("#!") else body)
    path.chmod(0o755)


class Stubs:
    """A temporary directory with stand-ins first on PATH and a log of the podman calls."""

    def __init__(self, prefix: str):
        self.tmp = Path(tempfile.mkdtemp(prefix=prefix))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        script(self.bin / "podman", PODMAN)
        script(self.bin / "sleep", "#!/bin/sh\nexit 0\n")
        # Never the real AWS CLI: a script that reaches for KMS outside the signer's stand-in stops here.
        script(self.bin / "aws", '#!/bin/sh\necho "aws $*" >>"$STUB_LOG"\necho "no AWS in these tests" >&2\nexit 1\n')
        self.log = self.tmp / "calls.log"
        self.log.touch()

    def env(self, **extra: str) -> dict[str, str]:
        return {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "STUB_LOG": str(self.log), **extra}

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "needs gpg and gpgv")
class SignAptRepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stubs = Stubs("nulavio-apt-protections-")
        tmp = cls.stubs.tmp
        home = tmp / "gnupg"
        home.mkdir(mode=0o700)
        gpg = ["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
        subprocess.run([*gpg, "--quick-gen-key", "Throwaway <release@example.invalid>", "rsa2048", "sign", "never"],
                       capture_output=True, check=True)  # fmt: skip
        listing = subprocess.run([*gpg, "--with-colons", "--list-keys"], capture_output=True, text=True, check=True).stdout
        cls.fpr = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        (tmp / "key.asc").write_bytes(subprocess.run([*gpg, "--armor", "--export"], capture_output=True, check=True).stdout)
        n, e, d = secret_numbers(subprocess.run([*gpg, "--export-secret-keys"], capture_output=True, check=True).stdout)
        subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"], capture_output=True, check=False)
        (tmp / "kms.json").write_text(json.dumps({"n": n, "d": d, "spki": base64.b64encode(spki(n, e)).decode()}))
        aws = tmp / "aws" / "bin"
        aws.mkdir(parents=True)
        script(aws / "aws", f"#!{PYTHON} -I\n{FAKE_AWS.split(chr(10), 1)[1]}")
        script(aws / "python3", SIGNER)
        cls.packages = tmp / "packages"
        cls.packages.mkdir()
        (cls.packages / DEB_NAME).write_bytes(b"a .deb, as far as these checks go")

    @classmethod
    def tearDownClass(cls):
        cls.stubs.close()

    def run_script(self, name: str, *, empty: bool = True, **modes: str) -> tuple[subprocess.CompletedProcess, Path]:
        out = self.stubs.tmp / name
        out.mkdir()
        if not empty:
            (out / "left-from-before").write_text("x")
        env = self.stubs.env(
            NULAVIO_APT_IMAGE=IMAGE, NULAVIO_KMS_KEY_ID="alias/test", NULAVIO_PUBLIC_KEY=str(self.stubs.tmp / "key.asc"),
            NULAVIO_TEST_AWS_DIR=str(self.stubs.tmp / "aws"), FAKE_KMS_KEY=str(self.stubs.tmp / "kms.json"),
            FAKE_KMS_LOG=str(self.stubs.tmp / "kms.log"), **modes,
        )  # fmt: skip
        env.pop("NULAVIO_RELEASE_MANIFEST", None)
        run = subprocess.run(["bash", str(RELEASE / "sign_apt_repo.sh"), str(self.packages), str(out), self.fpr],
                             env=env, capture_output=True, text=True, check=False)  # fmt: skip
        return run, out

    def refused(self, run: subprocess.CompletedProcess, code: int, message: str) -> None:
        self.assertEqual(run.returncode, code, run.stdout + run.stderr)
        self.assertIn(f"sign_apt_repo: {message}", run.stderr)
        self.assertNotIn("signed APT repository in", run.stdout)

    def test_the_stand_ins_give_a_repository_that_verifies(self):
        # The control: with nothing spoilt, the same set-up signs and every check passes.
        run, out = self.run_script("good")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("signed APT repository in", run.stdout)
        dists = out / "dists" / "stable"
        self.assertTrue((dists / "InRelease").is_file() and (dists / "Release.gpg").is_file())

    def test_an_inrelease_that_does_not_verify_is_refused(self):  # mutation 1
        run, _ = self.run_script("bad-inrelease", STUB_SIGNER="inrelease-bad-signature")
        self.refused(run, 1, "InRelease does not verify")

    def test_an_inrelease_signed_over_other_text_is_refused(self):  # mutation 2
        run, _ = self.run_script("other-inrelease", STUB_SIGNER="inrelease-other-text")
        self.refused(run, 1, "InRelease does not carry Release as it is")

    def test_a_release_gpg_that_does_not_verify_is_refused(self):  # mutation 6
        run, _ = self.run_script("bad-release-gpg", STUB_SIGNER="release-gpg-other-text")
        self.refused(run, 1, "Release.gpg does not verify")

    def test_an_output_directory_that_is_not_empty_is_refused_and_left_alone(self):  # mutation 3
        run, out = self.run_script("not-empty", empty=False)
        self.refused(run, 2, f"{out} is not empty")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["left-from-before"])

    def test_an_index_or_pool_that_is_not_exactly_the_packages_given_is_refused_before_signing(self):  # mutation 4
        for mode in ("wrong-hash", "extra-package"):
            with self.subTest(mode=mode):
                run, out = self.run_script(f"index-{mode}", STUB_PODMAN=mode)
                self.refused(run, 1, "the repository does not hold exactly the packages given")
                self.assertFalse((out / "dists" / "stable" / "InRelease").exists())

    def test_a_repository_apt_refuses_is_not_passed_on(self):  # mutation 5
        run, _ = self.run_script("apt-refuses", STUB_PODMAN="apt-refuses")
        self.refused(run, 1, "apt refuses the signed repository")


class PublishReleaseTest(unittest.TestCase):
    """publish_release.sh refuses a rehearsal without its .deb before it signs or stages anything."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nulavio-publish-protections-"))
        self.repo = self.tmp / "repo"
        for part in ("scripts/release", "scripts/upstream", "ci/containers"):
            shutil.copytree(ROOT / part, self.repo / part, ignore=shutil.ignore_patterns("__pycache__"))
        (self.repo / "site" / "keys").mkdir(parents=True)
        shutil.copy(ROOT / "site" / "keys" / "nulavio-packages.asc", self.repo / "site" / "keys")
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.tmp / "origin.git")], check=True)
        subprocess.run([*git, "remote", "add", "origin", str(self.tmp / "origin.git")], check=True)
        subprocess.run([*git, "push", "-q", "origin", "main"], check=True)
        self.base = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.stubs = Stubs("nulavio-publish-stubs-")

    def tearDown(self):
        self.stubs.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rehearsal(self, name: str, with_deb: bool) -> Path:
        out = self.tmp / name
        files = [f"packages/x86_64/nulavio-{VERSION}.fc44.x86_64.rpm"] + ([f"packages/{DEB_NAME}"] if with_deb else [])
        for file in files:
            for path, body in ((out / file, file.encode()), (out / f"{file}.cdx.json", b"{}")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
        source = "b" * 64
        manifest = {
            "firefox": VERSION.split("-")[0], "source_sha256": source, "signing_subkey": min(SIGNING_SUBKEYS),
            "engine_json": {"firefox": VERSION.split("-")[0], "source_sha256": source},
            "nulavio_base_commit": self.base, "worktree_diff_sha256": hashlib.sha256(b"").hexdigest(), "untracked": [],
            "packages": [{"file": f, "sha256": digest(out / f)} for f in files],
            "sboms": [{"file": f"{f}.cdx.json", "sha256": digest(out / f"{f}.cdx.json")} for f in files],
            "rehearsal": "ok",
        }  # fmt: skip
        (out / "manifest.json").write_text(json.dumps(manifest))
        return out

    def publish(self, out: Path) -> subprocess.CompletedProcess:
        public = self.repo / "site" / "keys" / "nulavio-packages.asc"
        key = subprocess.run(["gpg", "--quiet", "--with-colons", "--show-keys", str(public)],
                             capture_output=True, text=True, check=True).stdout  # fmt: skip
        fpr = next(line.split(":")[9] for line in key.splitlines() if line.startswith("fpr:"))
        env = self.stubs.env(NULAVIO_KMS_KEY_ID="alias/test", NULAVIO_PUBLISH_REF="origin/main", GNUPGHOME=str(self.tmp))
        command = [self.repo / "scripts/release/publish_release.sh", out, fpr, self.tmp / f"{out.name}-stage"]
        return subprocess.run(["bash", *map(str, command)], env=env, capture_output=True, text=True, check=False)

    @unittest.skipUnless(shutil.which("gpg"), "needs gpg")
    def test_a_rehearsal_without_its_deb_is_refused_before_anything_is_staged(self):  # mutation 7
        run = self.publish(self.rehearsal("no-deb", with_deb=False))
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("publish_release: the rehearsal has no .deb", run.stderr)
        self.assertFalse((self.tmp / "no-deb-stage").exists())
        self.assertEqual(self.stubs.log.read_text(), "", "nothing was signed or built")
        # The control: the same rehearsal with its .deb gets past that point, to the staging directory
        # (and stops later, at the stand-in aws, which signs nothing).
        run = self.publish(self.rehearsal("with-deb", with_deb=True))
        self.assertNotIn("has no .deb", run.stderr)
        self.assertTrue((self.tmp / "with-deb-stage" / "github").is_dir(), run.stderr)
        self.assertNotEqual(run.returncode, 0)


class CheckPublishedTest(unittest.TestCase):
    """check_published.sh passes only when both repositories install exactly the released version."""

    @classmethod
    def setUpClass(cls):
        cls.stubs = Stubs("nulavio-published-protections-")
        script(cls.stubs.bin / "curl", textwrap.dedent(f"""\
            #!{PYTHON} -I
            import os, shutil, sys
            target = sys.argv[sys.argv.index("-o") + 1]
            mode = os.environ.get("STUB_CURL", "")
            if mode == "fails":
                sys.exit(22)
            shutil.copy({str(ROOT / "site" / "apt" / "nulavio.sources")!r}, target)
            if mode == "changed":
                open(target, "a").write("Trusted: yes\\n")
            """))  # fmt: skip

    @classmethod
    def tearDownClass(cls):
        cls.stubs.close()

    def check(self, dnf: str, apt: str, curl: str = "") -> subprocess.CompletedProcess:
        env = self.stubs.env(STUB_DNF=dnf, STUB_APT=apt, STUB_CURL=curl)
        return subprocess.run(["bash", str(RELEASE / "check_published.sh"), VERSION], env=env, capture_output=True,
                              text=True, check=False)  # fmt: skip

    def test_both_repositories_installing_the_release_pass(self):
        run = self.check(f"{VERSION}.fc44", VERSION)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"dnf (https://nulavio.net/rpm/nulavio.repo) installed nulavio {VERSION}.fc44", run.stdout)
        self.assertIn(f"APT (https://nulavio.net/apt/nulavio.sources) installed nulavio {VERSION}", run.stdout)

    def test_anything_but_the_released_version_fails(self):  # mutations 8 and 9
        cases = {
            "dnf, an older release": ("160.0-0.3.fc44", VERSION, "dnf"),
            "dnf, a longer release": ("160.0-0.41.fc44", VERSION, "dnf"),
            "dnf, an error message": ("dnf refused or failed", VERSION, "dnf"),
            "dnf, nothing": ("", VERSION, "dnf"),
            "APT, an older release": (f"{VERSION}.fc44", "160.0-0.3", "APT"),
            "APT, the RPM's form": (f"{VERSION}.fc44", f"{VERSION}.fc44", "APT"),
            "APT, an error message": (f"{VERSION}.fc44", "apt install failed", "APT"),
        }
        for case, (dnf, apt, failing) in cases.items():
            with self.subTest(case):
                run = self.check(dnf, apt)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f"check_published: the published {failing} ", run.stderr)
                self.assertIn(f"does not install {VERSION}", run.stderr)

    def test_a_published_source_file_that_is_not_the_reviewed_one_fails(self):
        for mode in ("changed", "fails"):
            with self.subTest(mode=mode):
                run = self.check(f"{VERSION}.fc44", VERSION, curl=mode)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn("the published APT", run.stderr)


if __name__ == "__main__":
    unittest.main()
