"""The project's agent skills stay discoverable, listed and pointed at files that exist."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
CODE = re.compile(r"`([^`]+)`")
# A repository path inside a code span; one with a glob or a placeholder is not checked.
REPO_PATH = re.compile(r"(?<![\w./~>-])((?:\.github|\.agents|scripts|tests|browser|docs|ci|site)/[\w./-]+)(?![\w*{<./-])")


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
