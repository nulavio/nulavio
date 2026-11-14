"""The project's agent skills stay discoverable, listed and pointed at files that exist."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
AREAS = ("browser", "launcher", "android", "site", "tests", "scripts/release")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
CODE = re.compile(r"`([^`]+)`")
# A repository path inside a code span; one with a glob or a placeholder is not checked.
REPO_PATH = re.compile(r"(?<![\w./~>-])((?:\.github|\.agents|scripts|tests|browser|docs|ci|site)/[\w./-]+)(?![\w*{<./-])")


# In an area's AGENTS.md, a code span naming a file: a path (with a slash) or a file name.
NAMED_FILE = re.compile(r"^@?((?:[\w.-]+/)+[\w.-]*|[\w-][\w.-]*\.(?:py|sh|md|json|js|mjs|yml|yaml|css|html|xml|kts|lockfile))$")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True)  # fmt: skip
    return [name for name in out.stdout.decode().split("\0") if name]


def skill_dirs() -> list[Path]:
    return sorted(path for path in SKILLS.iterdir() if path.is_dir())


def frontmatter(skill: Path) -> dict[str, str]:
    match = FRONTMATTER.match((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert match, f"{skill.name}: SKILL.md starts without front matter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class AgentSkillsTests(unittest.TestCase):
    def test_every_skill_has_a_name_matching_its_directory_and_a_description(self):
        self.assertTrue(skill_dirs())
        for skill in skill_dirs():
            with self.subTest(skill=skill.name):
                fields = frontmatter(skill)
                self.assertEqual(fields.get("name"), skill.name)
                self.assertRegex(skill.name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(fields.get("description"))
                self.assertLessEqual(len(fields["description"]), 1024)

    def test_agents_md_lists_every_skill_and_nothing_else(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"\(\.agents/skills/([^/)]+)/SKILL\.md\)", agents))
        self.assertEqual(listed, {skill.name for skill in skill_dirs()})

    def test_links_and_quoted_paths_resolve(self):
        for skill in skill_dirs():
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if target.startswith(("https://", "http://")):
                    continue
                with self.subTest(skill=skill.name, link=target):
                    self.assertTrue((skill / target).resolve().exists())
            for path in (path for span in CODE.findall(text) for path in REPO_PATH.findall(span)):
                with self.subTest(skill=skill.name, path=path):
                    self.assertTrue((ROOT / path.rstrip(".")).exists())


class AreaInstructionsTests(unittest.TestCase):
    """The per-area AGENTS.md files (#179) exist, are listed at the root, load in Claude Code, and
    name only documents, files, tests and checks that exist."""

    def test_each_area_has_its_file_listed_at_the_root_and_a_claude_md_importing_it(self):
        root = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"\]\(((?:[\w-]+/)+)AGENTS\.md\)", root))
        self.assertEqual(listed, {f"{area}/" for area in AREAS})
        found = {name.rpartition("/")[0] for name in tracked_files() if name.endswith("/AGENTS.md")}
        self.assertEqual(found, set(AREAS))
        for area in AREAS:
            with self.subTest(area=area):
                # Claude Code loads a nested CLAUDE.md, not a nested AGENTS.md (checked 2026-11-14).
                self.assertEqual((ROOT / area / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_links_files_and_tests_named_in_an_area_file_exist(self):
        files = tracked_files()
        for area in AREAS:
            text = (ROOT / area / "AGENTS.md").read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if not target.startswith(("https://", "http://")):
                    with self.subTest(area=area, link=target):
                        self.assertTrue((ROOT / area / target).resolve().exists())
            for span in CODE.findall(text):
                for token in span.split():
                    token = token.rstrip(".,:;)")
                    match = NAMED_FILE.match(token)
                    if not match or any(mark in token for mark in "*…<>={}") or token.startswith("dist/"):
                        continue  # a glob, a placeholder or a generated file
                    raw = match.group(1)
                    name = raw.rstrip("/")
                    with self.subTest(area=area, name=name):
                        if "/" in raw:  # from the area, from the root, or the end of a tracked path
                            exists = (ROOT / area / name).exists() or (ROOT / name).exists()
                            exists = exists or any(f == name or f.endswith("/" + name) or f.startswith(name + "/")
                                                   or f"/{name}/" in f"/{f}" for f in files)  # fmt: skip
                        else:  # a file name: some tracked file has it
                            exists = any(f.rpartition("/")[2] == name for f in files)
                        self.assertTrue(exists, f"{area}/AGENTS.md names {name}, which does not exist")
