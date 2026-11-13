#!/usr/bin/env python3
"""Assemble the static nulavio.net site (site/) with the brand tokens and logo.

    python3 -I scripts/site/build_site.py --out dist/site
    python3 -I scripts/site/build_site.py --release [--commit <sha>] --out dist/site

The output is plain files for Cloudflare Pages (direct upload): no build
tool, no JavaScript in the pages, no third-party resources. The pages are the
landing (index.html, en/index.html; landing.css), the waitlist pages (lista/,
en/waitlist/, and the link page under each) and the engineering document
(engenharia/, en/engineering/; site.css). site/_worker.js is not a page script:
Cloudflare runs it for /api/* and the two link pages only (site/_routes.json),
to store waitlist sign-ups and to remove one for whoever holds its link.

The pages carry placeholders that this script stamps (landing spec §2.3, §9):
{{commit}}, {{date_pt}}, {{date_en}}, {{firefox}} (browser/build/engine.json),
{{patches}} (browser/patches/series), {{ubo}} (browser/distribution/
extensions.lock.json), {{defaults}} (the annotated defaults of browser/config/
prefs/baseline.js), {{buildid}} and, per figure, {{onscreen:<id>}},
{{port:<id>}} and {{wh:<file>}} from site/assets/shots/manifest.json (written
by scripts/site/capture_site.py), and the two text excerpts {{e1}} (the real
output of ``prefs explain``) and {{e2}} (the header lines of site/_headers).
{{shot:<file>}} is the commit a capture was taken at and {{origin}} the
commit(s) the numbers, excerpts and captures come from; outside --release
they say so when the tree had changes or the build predates the commit.
The build fails if a ``{{`` is left.

The download pages (baixar/, en/download/) describe a published release:
{{release_version}}, {{key_fpr}}, {{repo_file}} and {{key_url}} come from
packaging/release.json. Until it names a version and a key fingerprint and
site/keys/nulavio-packages.asc holds that key, the pages are left out of the
site, so nothing offers a download that does not exist. The same holds for
Ubuntu: what sits between <!--apt:on--> and <!--/apt:on--> is kept, with
{{sources_file}}, only once release.json names the APT source file (the first
release published with the APT repository sets it); until then the
<!--apt:off--> blocks are kept instead.

By default the site is built from the working tree (unit tests run on a
shared, possibly dirty tree). ``--release`` is how the published site is
built: it refuses a dirty tree, extracts ``--commit`` with ``git archive``
and builds from that copy only; the captures' manifest must name that
commit. Evidence mode (spec §2.2): only ``text`` (paths are references, not
links) is implemented while the repository is private.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import html
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = {
    "assets/tokens.css": Path("browser/startpage/tokens.css"),
    "assets/nulavio-symbol.svg": Path("docs/brand/assets/logo/nulavio-symbol.svg"),
    "assets/nulavio-symbol-dark-on-light.svg": Path("docs/brand/assets/logo/nulavio-symbol-dark-on-light.svg"),
    "assets/nulavio-lockup-horizontal.svg": Path("docs/brand/assets/logo/nulavio-lockup-horizontal.svg"),
    "assets/nulavio-lockup-horizontal-on-dark.svg": Path("docs/brand/assets/logo/nulavio-lockup-horizontal-on-dark.svg"),
    "assets/favicon.svg": Path("docs/brand/assets/favicon/favicon.svg"),
    "favicon.ico": Path("docs/brand/assets/favicon/favicon.ico"),
}
# Page -> capture locale (manifest figures are per locale).
PAGES = {
    "index.html": "pt-BR",
    "en/index.html": "en-US",
    "lista/index.html": "pt-BR",
    "en/waitlist/index.html": "en-US",
    "lista/link/index.html": "pt-BR",
    "en/waitlist/link/index.html": "en-US",
    "engenharia/index.html": "pt-BR",
    "en/engineering/index.html": "en-US",
    "404.html": None,
}
STYLESHEETS = ("site.css", "landing.css")  # served from /assets/
DOWNLOAD_PAGES = {"baixar/index.html": "pt-BR", "en/download/index.html": "en-US"}
PUBLIC_KEY = Path("site/keys/nulavio-packages.asc")
REPO_FILE = Path("site/rpm/nulavio.repo")
SOURCES_FILE = Path("site/apt/nulavio.sources")
APT_BLOCK = re.compile(r"<!--apt:(on|off)-->(.*?)<!--/apt:\1-->\n?", re.S)
E1_CATEGORIES = ("tracking", "https")
SCALE = 2  # captures are taken at devPixelsPerPx=2; width/height attributes are CSS px
# Notes appended to a commit outside --release, so a development build never passes for a release.
NOTES = {
    "pt-BR": {"dirty": "árvore com alterações", "older": "build anterior ao commit",
              "numbers": "números e trechos", "shots": "capturas", "and": " e ", "then": " e do commit "},
    "en-US": {"dirty": "tree with changes", "older": "build older than the commit",
              "numbers": "numbers and excerpts", "shots": "captures", "and": " and ", "then": " and commit "},
}  # fmt: skip
REF = re.compile(r'(<code class="ref"[^>]*>)([^<]*)(</code>)')


class BuildError(RuntimeError):
    pass


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


# -- values stamped into the pages --------------------------------------------------------


def patch_count(src: Path) -> int:
    lines = (src / "browser" / "patches" / "series").read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))


def ublock_version(src: Path) -> str:
    lock = json.loads((src / "browser" / "distribution" / "extensions.lock.json").read_text(encoding="utf-8"))
    return next(e["version"] for e in lock["extensions"] if e["key"] == "ublock-origin")


def default_count(src: Path) -> int:
    """The defaults Nulavio changes and documents: each has a @why and a @tradeoff (tests/unit/test_prefs_and_guard.py)."""
    lines = (src / "browser" / "config" / "prefs" / "baseline.js").read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.startswith("user_pref("))


def firefox_version(src: Path) -> str:
    return json.loads((src / "browser" / "build" / "engine.json").read_text(encoding="utf-8"))["firefox"]


def prefs_explain(src: Path, category: str) -> str:
    """The launcher's own output, run exactly as bin/nulavio runs it (python3 -I, launcher on sys.path)."""
    result = subprocess.run(
        [
            "python3", "-I", "-B", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from nulavio_launcher.cli import main; sys.exit(main(sys.argv[2:]))",
            str(src / "launcher"), "prefs", "explain", "--category", category,
        ],
        capture_output=True, text=True, timeout=60, cwd=src,
    )  # fmt: skip
    if result.returncode != 0 or not result.stdout.strip():
        raise BuildError(f"prefs explain --category {category} failed: {result.stderr[-400:]}")
    return result.stdout.rstrip("\n")


def excerpt_e1(src: Path) -> str:
    blocks = [f"$ bin/nulavio prefs explain --category {c}\n{prefs_explain(src, c)}" for c in E1_CATEGORIES]
    return "\n".join(blocks)


def header_lines(src: Path) -> list[str]:
    """The header lines of site/_headers: no comments, no blank lines, no path patterns."""
    out = []
    for line in (src / "site" / "_headers").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and line[:1].isspace():
            out.append(line.strip())
    return out


def armored_fingerprint(path: Path) -> str | None:
    """The primary key fingerprint of an armored public key, read with gpg (no keyring is touched)."""
    with tempfile.TemporaryDirectory(prefix="nulavio-site-gpg-") as home:
        try:
            result = subprocess.run(
                ["gpg", "--homedir", home, "--quiet", "--with-colons", "--show-keys", str(path)],
                capture_output=True, text=True, timeout=30,
            )  # fmt: skip
        except FileNotFoundError:
            raise BuildError("gpg is needed to check the release key behind the download pages") from None
    fprs = [line.split(":")[9] for line in result.stdout.splitlines() if line.startswith("fpr:")]
    return fprs[0] if result.returncode == 0 and fprs else None


def release_values(src: Path) -> dict[str, str] | None:
    """Values for the download pages, or None while no release is published (the pages are then left out)."""
    release = json.loads((src / "packaging" / "release.json").read_text(encoding="utf-8"))
    version, fpr = release.get("version", ""), release.get("key_fingerprint", "").replace(" ", "").upper()
    if not (version and fpr):
        return None
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)+-[0-9.]+", version):
        raise BuildError(f"packaging/release.json: version {version!r} is not <firefox>-<release> (as in the tag)")
    key = src / PUBLIC_KEY
    if not key.is_file():
        raise BuildError(f"packaging/release.json names a key but {PUBLIC_KEY} is missing")
    if armored_fingerprint(key) != fpr:
        raise BuildError(f"{PUBLIC_KEY} is not the key {fpr} that packaging/release.json names")
    # The .repo file turns dnf's signature checks on: it is served from this tree, never from the
    # package bucket, where whoever can upload packages could also turn the checks off.
    if release["repo_file"] != f"https://nulavio.net/{REPO_FILE.relative_to('site')}":
        raise BuildError(f"packaging/release.json: repo_file must be the site's own {REPO_FILE}")
    repo_lines = (src / REPO_FILE).read_text(encoding="utf-8").splitlines() if (src / REPO_FILE).is_file() else []
    if not {"gpgcheck=1", "repo_gpgcheck=1", f"gpgkey={release['key_url']}"} <= set(repo_lines):
        raise BuildError(f"{REPO_FILE} must have gpgcheck=1, repo_gpgcheck=1 and gpgkey={release['key_url']}")
    values = {
        "release_version": version,
        "key_fpr": " ".join(fpr[i : i + 4] for i in range(0, len(fpr), 4)),
        "repo_file": release["repo_file"],
        "key_url": release["key_url"],
        "apt": "off",
    }
    if "apt_sources" in release:
        # Like the .repo file: the source file decides whether apt checks signatures, so it is
        # the site's own, and the key in it is the one the pages show.
        if release["apt_sources"] != f"https://nulavio.net/{SOURCES_FILE.relative_to('site')}":
            raise BuildError(f"packaging/release.json: apt_sources must be the site's own {SOURCES_FILE}")
        if sources_key(src / SOURCES_FILE) != key.read_text(encoding="ascii").strip("\n").split("\n"):
            raise BuildError(f"{SOURCES_FILE} must carry {PUBLIC_KEY} as its Signed-By key")
        values.update(apt="on", sources_file=release["apt_sources"])
    return values


def sources_key(path: Path) -> list[str]:
    """The armored key in a deb822 source file's Signed-By field (continuation lines, "." for blank)."""
    lines = path.read_text(encoding="ascii").splitlines() if path.is_file() else []
    if "Signed-By:" not in lines:
        return []
    key = []
    for line in lines[lines.index("Signed-By:") + 1 :]:
        if not line.startswith(" "):
            break
        key.append("" if line == " ." else line[1:])
    return key


def choose_apt_blocks(text: str, apt: str) -> str:
    """Keep the <!--apt:on--> or the <!--apt:off--> blocks of a download page, as release.json says."""

    def keep(match: re.Match) -> str:
        if match.group(1) != apt:
            return ""
        body = match.group(2)
        return body[1:] if body.startswith("\n") else body  # a block on lines of its own leaves no blank line

    return APT_BLOCK.sub(keep, text)


def commit_date(src_commit: str) -> dt.date:
    return dt.date.fromisoformat(git("log", "-1", "--format=%cs", src_commit))


@functools.cache
def commit_time(src_commit: str) -> dt.datetime:
    return dt.datetime.fromisoformat(git("log", "-1", "--format=%cI", src_commit))


def build_time(buildid: str) -> dt.datetime:
    """A Gecko BuildID is the UTC time the build was packaged."""
    return dt.datetime.strptime(buildid, "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC)


def shot_notes(entry: dict, manifest: dict) -> list[str]:
    """What keeps a capture from being a release capture: a changed tree, or a build older than the commit."""
    notes = []
    if not entry.get("worktree_clean", manifest.get("worktree_clean", False)):
        notes.append("dirty")
    try:
        if build_time(entry["buildid"]) < commit_time(entry["commit"]):
            notes.append("older")
    except (subprocess.CalledProcessError, ValueError):
        notes.append("older")  # the commit or the build time cannot be read: do not vouch for it
    return notes


def load_manifest(src: Path) -> dict:
    path = src / "site" / "assets" / "shots" / "manifest.json"
    if not path.exists():
        return {"files": [], "figures": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def stamps(src: Path, commit: str, manifest: dict) -> dict[str, str]:
    date = commit_date(commit)
    buildids = {f["buildid"] for f in manifest["files"]}
    if len(buildids) > 1:
        raise BuildError(f"the captures come from different builds: {sorted(buildids)}")
    values = {
        "commit": git("rev-parse", "--short=7", commit),
        "date_pt": date.strftime("%d/%m/%Y"),
        "date_en": date.isoformat(),
        "firefox": firefox_version(src),
        "patches": str(patch_count(src)),
        "ubo": ublock_version(src),
        "defaults": str(default_count(src)),
        "buildid": next(iter(buildids)) if buildids else "",
        "e1": html.escape(excerpt_e1(src), quote=False),
        "e2": html.escape("\n".join(header_lines(src)), quote=False),
    }
    return {k: v for k, v in values.items() if v}


def describe(commit: str, notes: list[str], locale: str, what: str | None = None) -> str:
    words = NOTES[locale]
    parts = ([words[what]] if what else []) + [words[n] for n in dict.fromkeys(notes)]
    return f"{commit} ({'; '.join(parts)})" if parts else commit


def origin(values: dict[str, str], manifest: dict, locale: str) -> str:
    """The commit(s) behind the page: one commit when the tree and every capture agree, else each named."""
    source, source_notes = values["commit"], (["dirty"] if values.get("source_dirty") else [])
    shots: dict[str, list[str]] = {}
    for entry in manifest["files"]:
        shots.setdefault(entry["commit"], []).extend(shot_notes(entry, manifest))
    if not shots or set(shots) == {source}:
        return describe(source, source_notes + shots.get(source, []), locale)
    words = NOTES[locale]
    commits = words["and"].join(sorted(shots))
    notes = [n for c in sorted(shots) for n in shots[c]]
    return describe(source, source_notes, locale, "numbers") + words["then"] + describe(commits, notes, locale, "shots")


def break_points(text: str) -> str:
    """Paths and test names break after a / or _, not in the middle of a word."""
    return REF.sub(lambda m: m.group(1) + re.sub(r"([/_])", r"\1<wbr>", m.group(2)) + m.group(3), text)


def stamp_page(text: str, values: dict[str, str], manifest: dict, locale: str | None, page: str) -> str:
    files = {f["file"]: f for f in manifest["files"]}

    def figure(key: str) -> dict:
        try:
            return manifest["figures"][key][locale]
        except KeyError:
            raise BuildError(f"{page}: no capture for {key} ({locale}) in the manifest") from None

    def replace(match: re.Match) -> str:
        name, _, arg = match.group(1).partition(":")
        if name == "onscreen":
            return html.escape(figure(arg)["transcript"], quote=False)
        if name == "port":
            return str(figure(arg)["port"])
        if name == "wh":
            entry = files.get(arg)
            if entry is None:
                raise BuildError(f"{page}: {arg} is not in the manifest")
            return f'width="{round(entry["width"] / SCALE)}" height="{round(entry["height"] / SCALE)}"'
        if name == "shot":
            entry = files.get(arg)
            if entry is None:
                raise BuildError(f"{page}: {arg} is not in the manifest")
            return describe(entry["commit"], shot_notes(entry, manifest), locale)
        if name == "origin":
            return origin(values, manifest, locale)
        if name in values:
            return values[name]
        return match.group(0)

    return keep_addresses(break_points(re.sub(r"\{\{([a-z_0-9]+(?::[A-Za-z0-9_.-]+)?)\}\}", replace, text)), page)


# Cloudflare, which serves the site, can rewrite every address in a page ("email obfuscation") and add a
# script to put them back. The site's own policy allows no script, so the security contact showed as
# "[email protected]" and the page stopped matching the build (verify_live.py). These comments are
# Cloudflare's own way for a page to opt out, so the pages do not depend on how the zone is set.
EMAIL_OFF = ("<!--email_off-->", "<!--/email_off-->")


def keep_addresses(text: str, page: str) -> str:
    if text.count("<body>") != 1 or text.count("</body>") != 1:
        raise BuildError(f"{page}: expected exactly one <body> and one </body>")
    return text.replace("<body>", f"<body>\n{EMAIL_OFF[0]}").replace("</body>", f"{EMAIL_OFF[1]}\n</body>")


# -- build --------------------------------------------------------------------------------


class Discovery(HTMLParser):
    """Read discovery directives from the rendered head, including future noindex pages."""

    def __init__(self, text: str):
        super().__init__()
        self.canonicals: list[str] = []
        self.alternates: list[dict[str, str]] = []
        self.noindex = False
        self.feed(text.partition("</head>")[0])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").lower() == "robots":
            self.noindex |= bool({"noindex", "none"} & set(re.split(r"[\s,]+", attrs.get("content", "").lower())))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs["href"])
        if tag == "link" and attrs.get("rel") == "alternate" and "hreflang" in attrs:
            self.alternates.append(attrs)


def write_sitemap(out: Path, pages: dict) -> None:
    """Only indexable, self-canonical HTML that this build actually publishes."""
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    xhtml = "http://www.w3.org/1999/xhtml"
    ET.register_namespace("", namespace)
    ET.register_namespace("xhtml", xhtml)
    root = ET.Element(f"{{{namespace}}}urlset")
    entries = []
    for page in pages:
        discovery = Discovery((out / page).read_text(encoding="utf-8"))
        if discovery.noindex or not discovery.canonicals:
            continue
        url = "https://nulavio.net/" + page.removesuffix("index.html")
        if discovery.canonicals != [url]:
            raise BuildError(f"{page}: sitemap requires exactly one self-canonical URL ({url})")
        entries.append((url, discovery))
    published = {url for url, _ in entries}
    for url, discovery in sorted(entries, key=lambda entry: entry[0]):
        node = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(node, f"{{{namespace}}}loc").text = url
        for alternate in discovery.alternates:
            if alternate["href"] not in published:
                raise BuildError(f"{url}: alternate is not an indexable published page: {alternate['href']}")
            ET.SubElement(node, f"{{{xhtml}}}link", alternate)
    # No fabricated lastmod: a build date is not the date each page's content changed.
    ET.indent(root)
    ET.ElementTree(root).write(out / "sitemap.xml", encoding="utf-8", xml_declaration=True)


def release_tree(commit: str, into: Path) -> Path:
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise BuildError("--release refuses a dirty tree: commit or set aside the changes first")
    archive = into / "src.tar"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "-o", str(archive), commit], check=True)
    src = into / "src"
    src.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(src, filter="data")
    archive.unlink()
    return src


def build(out: Path, *, release: bool = False, commit: str = "HEAD", evidence: str = "text") -> list[str]:
    if evidence != "text":
        raise BuildError(f"evidence mode {evidence!r} is not implemented; the repository is private (spec §2.2)")
    with tempfile.TemporaryDirectory(prefix="nulavio-site-") as tmp:
        src = release_tree(commit, Path(tmp)) if release else ROOT
        manifest = load_manifest(src)
        if release and manifest["files"]:
            wanted = git("rev-parse", "--short=7", commit)
            found = {f["commit"] for f in manifest["files"]}
            if found != {wanted}:
                raise BuildError(f"the captures were taken at {sorted(found)}, not at {wanted}: capture again")
            unfit = sorted(f["file"] for f in manifest["files"] if shot_notes(f, manifest))
            if unfit:
                raise BuildError(f"captures from a changed tree or a build older than {wanted}: {unfit[:3]}…; capture again")
        values = stamps(src, commit, manifest)
        values["source_dirty"] = "" if release else git("status", "--porcelain", "--untracked-files=normal")
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(src / "site", out)
        (out / "assets").mkdir(exist_ok=True)
        for sheet in STYLESHEETS:
            shutil.move(out / sheet, out / "assets" / sheet)
        for relative, source in ASSETS.items():
            shutil.copyfile(src / source, out / relative)
        released = release_values(src)
        pages = dict(PAGES)
        if released is None:
            for page in DOWNLOAD_PAGES:
                (out / page).unlink()
                if not any((out / page).parent.iterdir()):
                    (out / page).parent.rmdir()
        else:
            pages.update(DOWNLOAD_PAGES)
        for page, locale in pages.items():
            path = out / page
            page_values = {**values, **released} if page in DOWNLOAD_PAGES else values
            text = path.read_text(encoding="utf-8")
            if page in DOWNLOAD_PAGES:
                text = choose_apt_blocks(text, released["apt"])
            elif "<!--apt:" in text:
                raise BuildError(f"{page}: apt blocks belong on the download pages only")
            text = stamp_page(text, page_values, manifest, locale, page)
            if "{{" in text:
                left = sorted(set(re.findall(r"\{\{[^}]*\}\}", text)))
                raise BuildError(f"{page}: placeholders left: {left}")
            path.write_text(text, encoding="utf-8")
        write_sitemap(out, pages)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "site")
    parser.add_argument("--release", action="store_true", help="refuse a dirty tree and build from git archive of --commit")
    parser.add_argument("--commit", default="HEAD", help="commit to stamp (and, with --release, to build from)")
    parser.add_argument("--evidence", default="text", choices=["text"], help="how references appear (spec §2.2)")
    args = parser.parse_args()
    try:
        files = build(args.out, release=args.release, commit=args.commit, evidence=args.evidence)
    except BuildError as e:
        parser.exit(1, f"build_site: {e}\n")
    print(f"{len(files)} files in {args.out}:", ", ".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
