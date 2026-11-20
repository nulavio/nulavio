"""nulavio.net's fingerprinting comparison is generated from published data, never typed in (#437).

The page (/engenharia/impressao-digital/, /en/engineering/fingerprinting/) and the picture for sharing come from
tests/fixtures/privacytests/published.json (PrivacyTests.org's page and data file) and nulavio.json (a published
release's privacytests run), through scripts/site/privacytests_pages.py.
"""

from __future__ import annotations

import ast
import html
import copy
import hashlib
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "site"))

import privacytests_pages as pt  # noqa: E402

FIXTURES = ROOT / pt.FIXTURES
DATES = {"pt-BR": "20/11/2026", "en-US": "2026-11-20"}


def integration_constants() -> dict:
    tree = ast.parse((ROOT / pt.INTEGRATION_TEST).read_text(encoding="utf-8"))
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()
        and node.targets[0].id in ("PROBES", "NOT_IN_THE_ENGINE", "DEVICE_CONSTANTS")
    }  # fmt: skip


class Rows(HTMLParser):
    """The comparison tables as rows of (probe, [mark per column]) and their column headers."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.tables, self.row, self.cell, self.head, self.in_probe = [], None, None, None, False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.tables.append({"heads": [], "rows": []})
        elif tag == "tr":
            self.row = {"probe": "", "marks": []}
        elif tag == "th" and attrs.get("scope") == "col":
            self.head = ""
        elif tag == "span" and attrs.get("class") == "probe":
            self.in_probe = True
        elif tag == "svg" and self.row is not None and "mark" in (attrs.get("class") or "").split():
            kinds = [c.removeprefix("mark-") for c in attrs["class"].split() if c.startswith("mark-")]
            self.row["marks"].append(kinds[0])

    def handle_endtag(self, tag):
        if tag == "span" and self.in_probe:
            self.in_probe = False
        elif tag == "th" and self.head is not None:
            self.tables[-1]["heads"].append(self.head.split()[0] if self.head.split() else "")
            self.head = None
        elif tag == "tr" and self.row is not None:
            if self.row["probe"]:
                self.tables[-1]["rows"].append((self.row["probe"], self.row["marks"]))
            self.row = None

    def handle_data(self, data):
        if self.in_probe:
            self.row["probe"] += data
        if self.head is not None:
            self.head += data


class ComparisonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = pt.comparison(ROOT)
        cls.published = json.loads((FIXTURES / pt.PUBLISHED).read_text(encoding="utf-8"))
        cls.release = json.loads((FIXTURES / pt.NULAVIO).read_text(encoding="utf-8"))
        cls.constants = integration_constants()
        cls.pages = pt.pages(ROOT, DATES)

    # -- the probes ---------------------------------------------------------------------------

    def test_the_probes_are_the_integration_tests_in_its_order(self):
        self.assertEqual({g: tuple(p) for g, p in self.c["groups"].items()}, self.constants["PROBES"])
        every = {p for group in self.constants["PROBES"].values() for p in group}
        self.assertEqual(len(every), 25)
        self.assertEqual(set(pt.GLOSS), every, "every probe has a plain-words line in both languages")
        self.assertEqual(set(self.published["rows"]) | set(self.published["not_on_page"]), every)
        self.assertIn(pt.ONE_ARCHITECTURE, self.constants["DEVICE_CONSTANTS"])

    # -- PrivacyTests.org's columns ------------------------------------------------------------

    def test_the_sources_are_named_with_their_digest_and_date(self):
        for kind in ("page", "data"):
            source = self.published["sources"][kind]
            with self.subTest(kind=kind):
                self.assertTrue(source["url"].startswith("https://privacytests.org/"))
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(source["last_modified"], r"GMT$")
                self.assertGreater(source["bytes"], 0)
        self.assertRegex(self.published["sources"]["read"], r"^\d{4}-\d\d-\d\d$")
        self.assertRegex(self.published["harness"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(self.published["issue"], int)

    def test_every_cell_is_one_per_browser_in_the_pages_order(self):
        columns = [b["id"] for b in self.published["browsers"]]
        self.assertEqual(len(columns), len(set(columns)))
        self.assertLessEqual(set(columns), set(pt.BROWSERS))
        for probe, cells in self.published["rows"].items():
            with self.subTest(probe=probe):
                self.assertEqual(list(cells), columns)
                for cell in cells.values():
                    self.assertIn(cell["verdict"], ("passed", "failed", "unsupported"))

    def test_every_cell_follows_the_runs_it_comes_from(self):
        """A verdict typed in by hand disagrees with the runs read from their data file. Their page's own
        verdict wins only in the cells PAGE_OVER_RULE names, and each of those is still such a cell."""
        groups = self.constants["PROBES"]
        differ = set()
        for probe, cells in self.published["rows"].items():
            group = pt.group_of(groups, probe)
            for browser, cell in cells.items():
                if cell["verdict"] == "unsupported":
                    continue
                if cell["verdict"] != ("passed" if pt.rule(group, cell["runs"]) else "failed"):
                    differ.add((browser, probe))
        self.assertEqual(differ, set(pt.PAGE_OVER_RULE))

    def test_a_cell_typed_in_by_hand_stops_the_build(self):
        fixture = copy.deepcopy(self.published)
        cell = fixture["rows"]["Logical CPU cores"]["chrome"]
        cell["verdict"] = "passed" if cell["verdict"] == "failed" else "failed"
        page = {
            "issue": fixture["issue"],
            "updated": fixture["updated"],
            "columns": [b["id"] for b in fixture["browsers"]],
            "rows": {p: {b: c["verdict"] for b, c in cells.items()} for p, cells in fixture["rows"].items()},
        }
        data = {
            "time_started": fixture["time_started"],
            "harness": fixture["harness"],
            "browsers": {
                b["id"]: {
                    "version": b["version"],
                    "runners": b["runners"],
                    "runs": {p: cells[b["id"]]["runs"] for p, cells in fixture["rows"].items()},
                }
                for b in fixture["browsers"]
            },
        }  # fmt: skip
        with self.assertRaisesRegex(pt.ComparisonError, "Logical CPU cores, chrome"):
            pt.published(page, data, self.constants["PROBES"], fixture["sources"])
        cell["verdict"] = "passed" if cell["verdict"] == "failed" else "failed"
        page["rows"]["Logical CPU cores"]["chrome"] = cell["verdict"]
        rebuilt = pt.published(page, data, self.constants["PROBES"], fixture["sources"])
        self.assertEqual(rebuilt["rows"], self.published["rows"], "the fixture is what refresh makes of its sources")

    def test_their_page_is_read_cell_by_cell(self):
        def page(cells: str, columns=("brave", "tor")) -> str:
            logos = "".join(f'<th><img class="browser-logo-image" alt="{c} logo" src=""></th>' for c in columns)
            rows = (
                '<tr><th colspan="3"><span class="subheading-title">{t}</span></th></tr>'
                '<tr><td class="tooltipParent"><div>{p}</div></td>{cells}</tr>'
            )
            device = rows.format(t=pt.SECTIONS["Device"], p="Device memory", cells=cells)
            settings = rows.format(t=pt.SECTIONS["Settings"], p="Time zone", cells=cells)
            return (
                '<div class="banner" id="issueBanner"><div>No. 107</div><div>Updated 2026-12-01</div></div>'
                f'<table class="comparison-table"><tbody><tr>{logos}</tr>{device}{settings}</tbody></table>'
            )

        good = '<td><img alt="Passed" src="" class="dataPoint good"></td>'
        na = '<td><img alt="Unsupported" src="" class="dataPoint na"></td>'
        read = pt.parse_page(page(good + na))
        self.assertEqual((read["issue"], read["updated"], read["columns"]), (107, "2026-12-01", ["brave", "tor"]))
        self.assertEqual(read["rows"]["Device memory"], {"brave": "passed", "tor": "unsupported"})
        for cells, error in (
            (good, "1 cells for 2 browsers"),  # a missing cell would shift every column after it
            (good + "<td>–</td>", "not one mark"),
            (good + '<td><img alt="Partly" src="" class="dataPoint half"></td>', "unknown mark"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(pt.ComparisonError, error):
                pt.parse_page(page(cells))
        with self.assertRaisesRegex(pt.ComparisonError, "one browser each"):
            pt.parse_page(page(good + good, columns=("brave", "brave")))

    def test_their_data_file_is_one_version_per_browser_and_no_private_mode(self):
        def run(version, **flags):
            return {"browser": "brave", "reportedVersion": version, "runner": "macos-26", "testResults": {}, **flags}

        data = {"platform": "Desktop", "timeStarted": "t", "git": "g"}
        self.assertEqual(pt.parse_data({**data, "all_tests": [run("1"), run("1")]})["browsers"]["brave"]["version"], "1")
        with self.assertRaisesRegex(pt.ComparisonError, "different versions"):
            pt.parse_data({**data, "all_tests": [run("1"), run("2")]})
        with self.assertRaisesRegex(pt.ComparisonError, "private or nightly"):
            pt.parse_data({**data, "all_tests": [run("1", incognito=True)]})

    # -- Nulavio's column ----------------------------------------------------------------------

    def test_nulavios_column_is_a_published_releases_device_job(self):
        self.assertEqual(self.release["version"], self.release["tag"].removeprefix("v"))
        self.assertRegex(self.release["version"], r"^[0-9]+(\.[0-9]+)+-[0-9.]+$")
        self.assertEqual(self.release["run"]["event"], "release")
        self.assertEqual(self.release["job"]["conclusion"], "success")
        self.assertTrue(self.release["job"]["name"].startswith("the Device probes"))
        self.assertRegex(self.release["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(self.release["pages"], r"^[0-9a-f]{40}$")
        self.assertTrue(self.release["release_url"].endswith(f"/releases/tag/{self.release['tag']}"))
        self.assertTrue(self.release["job"]["url"].startswith(self.release["run"]["url"]))
        results, unsupported = pt.parse_log(self.release["log"])
        self.assertEqual(len(results), 25)
        self.assertEqual(unsupported, "ok")

    def test_nulavios_marks_come_from_the_result_lines(self):
        marks = self.c["nulavio"]
        self.assertEqual({p for p, m in marks.items() if m == "unsupported"}, self.constants["NOT_IN_THE_ENGINE"])
        self.assertEqual([p for p, m in marks.items() if m == "one-architecture"], [pt.ONE_ARCHITECTURE])
        probes = {**self.constants["PROBES"], "NOT_IN_THE_ENGINE": self.constants["NOT_IN_THE_ENGINE"]}
        lines = [line.replace("Time zone ... ok", "Time zone ... skipped 'known gap'") for line in self.release["log"]]
        self.assertEqual(pt.nulavio_marks({"log": lines}, probes)["Time zone"], "failed")
        lines = [line.replace("Device memory ... ok", "Device memory ... FAIL") for line in self.release["log"]]
        self.assertEqual(pt.nulavio_marks({"log": lines}, probes)["Device memory"], "failed")
        # "No such feature" needs the run to show the engine answering Unsupported, with and without protections.
        lines = [line.replace(") ... ok", ") ... FAIL") if line.startswith("test_00b") else line for line in self.release["log"]]
        with self.assertRaisesRegex(pt.ComparisonError, "Unsupported"):
            pt.nulavio_marks({"log": lines}, probes)
        with self.assertRaisesRegex(pt.ComparisonError, "not the integration test's"):
            pt.nulavio_marks({"log": self.release["log"][:-1]}, probes)

    # -- the page ------------------------------------------------------------------------------

    def test_the_page_shows_the_fixtures_cell_by_cell(self):
        for locale, base in pt.BASE.items():
            rows = Rows(self.pages[f"{base}index.html"])
            with self.subTest(locale=locale):
                self.assertEqual(len(rows.tables), len(pt.GROUPS))
                for group, found in zip(pt.GROUPS, rows.tables, strict=True):
                    self.assertEqual(found["heads"][1:], ["Nulavio", *(pt.BROWSERS[b].split()[0] for b in self.c["columns"])])
                    expected = [
                        (p, [self.c["nulavio"][p], *(self.c["marks"][p][b] for b in self.c["columns"])])
                        for p in self.c["groups"][group]
                    ]
                    self.assertEqual(found["rows"], expected)

    def test_no_comparison_page_is_kept_in_site(self):
        for base in pt.BASE.values():
            self.assertFalse((ROOT / "site" / base).exists(), "the page is generated at build time, not kept by hand")

    def test_the_page_says_whose_measurement_each_column_is_and_draws_no_totals(self):
        for locale, base in pt.BASE.items():
            text = re.sub(r"<[^>]+>", " ", self.pages[f"{base}index.html"])
            with self.subTest(locale=locale):
                self.assertIn(f"Nulavio {self.release['version']}", text)
                self.assertNotRegex(text, r"\b\d+\s*(of|de|/)\s*25\b", "no totals: the columns are not counted alike")
                self.assertNotRegex(text, r"(?i)\b(best|melhor|rank(ed|ing)? (first|1)|primeiro lugar)\b")
                self.assertIn("privacytests.org/index.json", text)
                self.assertIn(self.release["job"]["url"].removeprefix("https://"), text)
                self.assertIn(self.published["sources"]["data"]["sha256"], text)
        en = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.pages["en/engineering/fingerprinting/index.html"])))
        for words in (
            "PrivacyTests.org has not tested Nulavio",
            "Nulavio has an x86-64 build only",
            "this page shows no totals",
            "their page has no row for it",
            "on GitHub's macOS machines",
            "not a ranking",
        ):
            self.assertIn(words, en)
        pt_page = html.unescape(
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.pages["engenharia/impressao-digital/index.html"]))
        )
        for words in (
            "O PrivacyTests.org não testou o Nulavio",
            "O Nulavio só tem versão para x86-64",
            "esta página não mostra totais",
            "a página deles não tem linha para esse teste",
            "em máquinas macOS do GitHub",
            "não um ranking",
        ):
            self.assertIn(words, pt_page)

    def test_both_languages_say_the_same_things(self):
        for key in ("legend", "legend_names", "groups"):
            self.assertEqual(set(pt.WORDS["pt-BR"][key]), set(pt.WORDS["en-US"][key]))
        self.assertEqual(len(pt.WORDS["pt-BR"]["notes"]), len(pt.WORDS["en-US"]["notes"]))
        self.assertEqual(set(pt.WORDS["pt-BR"]), set(pt.WORDS["en-US"]))
        self.assertEqual(set(pt.TEXT["pt-BR"]), set(pt.MARKS))
        self.assertEqual(set(pt.SHAPES), set(pt.MARKS))

    # -- the picture for sharing ---------------------------------------------------------------

    def test_the_picture_is_drawn_from_the_same_marks(self):
        record = json.loads((FIXTURES / pt.PICTURE).read_text(encoding="utf-8"))
        for locale, path in pt.OG.items():
            svg = pt.picture_svg(self.c, locale)
            png = (ROOT / "site" / path).read_bytes()
            with self.subTest(locale=locale):
                self.assertEqual(record[locale]["svg_sha256"], hashlib.sha256(svg.encode()).hexdigest(), "draw it again: picture")
                self.assertEqual(record[locale]["png_sha256"], hashlib.sha256(png).hexdigest())
                self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual((int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")), pt.OG_SIZE)
                self.assertIn(f"Nulavio {self.release['version']}", svg)
                self.assertIn(str(self.published["issue"]), svg)
                self.assertNotIn("<image", svg, "no logos")
                self.assertEqual(svg.count("<g transform"), 13 * 25 + len(pt.MARKS), "a mark per cell and the legend's")
                page = self.pages[f"{pt.BASE[locale]}index.html"]
                self.assertIn(f'<meta property="og:image" content="https://nulavio.net/{path}">', page)


if __name__ == "__main__":
    unittest.main()
