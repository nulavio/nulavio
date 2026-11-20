#!/usr/bin/env python3
"""PrivacyTests.org's fingerprinting probes, side by side with a published Nulavio release (#437).

    python3 -I scripts/site/privacytests_pages.py refresh [--tag v160.0.1-0.2] [--no-picture]
    python3 -I scripts/site/privacytests_pages.py picture

build_site.py calls pages(): /engenharia/impressao-digital/ and /en/engineering/fingerprinting/. They are
built from two files under tests/fixtures/privacytests/, which only `refresh` writes:

- published.json: what PrivacyTests.org published for the desktop browsers. The pass or fail of each cell is
  what their page (https://privacytests.org/) shows; next to it, the runs it comes from, read from their data
  file (https://privacytests.org/index.json): for a Device probe whether each run was randomized and a digest
  of its value, for a Settings probe whether each run passed. Both files' SHA-256 and Last-Modified are kept.
- nulavio.json: the published release's `device` job of the privacytests workflow (.github/workflows/
  privacytests.yml), which runs tests/integration/test_privacytests.py on the release's own archive on
  GitHub's runner. It keeps that job's result lines, verbatim; the marks are read from them.

Nothing here is typed by hand: tests/unit/test_privacytests_comparison.py holds the probe names to the
integration test, each cell to the runs it comes from, and the page and the picture to these two files.

`refresh` reads the network (privacytests.org, and GitHub's API through `gh`) and rewrites both files, then
the picture. `picture` draws the picture for sharing (site/assets/og-fingerprinting-*.png) from the same
marks as the page, with a headless Firefox (FIREFOX, else `firefox` on PATH) in a throwaway profile, and
writes tests/fixtures/privacytests/picture.json, which ties each PNG to the source it was drawn from.
The pages themselves carry no script and load nothing from another site.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path("tests/fixtures/privacytests")
PUBLISHED, NULAVIO, PICTURE = "published.json", "nulavio.json", "picture.json"
INTEGRATION_TEST = Path("tests/integration/test_privacytests.py")
REPO = "nulavio/nulavio"
PAGE_URL, DATA_URL = "https://privacytests.org/", "https://privacytests.org/index.json"
LIMIT = 64 * 1024 * 1024  # their data file was 5.5 MB on 2026-11-20
BASE = {"pt-BR": "engenharia/impressao-digital/", "en-US": "en/engineering/fingerprinting/"}
OG = {"pt-BR": "assets/og-fingerprinting-pt.png", "en-US": "assets/og-fingerprinting-en.png"}
OG_SIZE = (1200, 630)
GROUPS = ("Device", "Settings", "Screen")
# Their page has two sections; the Screen probes are rows of the Settings one, and of its data.
SECTIONS = {"Device": "Device fingerprinting resistance tests", "Settings": "Settings fingerprinting resistance tests"}
DATA_GROUP = {"Device": "device_fingerprinting", "Settings": "settings_fingerprinting", "Screen": "settings_fingerprinting"}
# Their page's columns, by the name their data gives each browser. A browser not here stops `refresh`.
BROWSERS = {
    "brave": "Brave", "chrome": "Chrome", "duckduckgo": "DuckDuckGo", "edge": "Edge", "firefox": "Firefox",
    "librewolf": "LibreWolf", "mullvad": "Mullvad Browser", "opera": "Opera", "safari": "Safari",
    "tor": "Tor Browser", "ungoogled": "Ungoogled Chromium", "vivaldi": "Vivaldi",
}  # fmt: skip
CELL = {("Passed", "good"): "passed", ("Failed", "bad"): "failed", ("Unsupported", "na"): "unsupported"}
# Cells where their page's verdict is not the plain rule over the runs (every run randomized, or one value on
# every run; for Settings, every run passed). Their page is what people read, so the cell is the page's; each
# such cell is named here with what the page shows, and `refresh` stops on one that is not.
PAGE_OVER_RULE = {
    ("brave", "Device memory"): (
        "their page shows it passed: three of the five runs were randomized and the other two read 8 and 4"
    ),
}
# Read a byte of NaN that differs between arm64 and x86 processors; Nulavio has an x86-64 build only, so its
# value is constant for that reason alone (#79). It is a Device constant of the integration test.
ONE_ARCHITECTURE = "Math: Infinity - Infinity"
MARKS = ("passed", "failed", "unsupported", "one-architecture", "not-on-page")
LOG_LINE = re.compile(r"^PrivacyTests, (Device|Settings|Screen): (.+) \.\.\. (ok|skipped\b.*|FAIL|ERROR)$")
UNSUPPORTED_TEST = "test_00b_what_the_engine_does_not_have_reads_unsupported_with_and_without_the_protections"
UNSUPPORTED_LINE = re.compile(rf"^{UNSUPPORTED_TEST} \(.*\) \.\.\. (ok|skipped\b.*|FAIL|ERROR)$")


class ComparisonError(RuntimeError):
    pass


# -- the probes, as the integration test names them -----------------------------------------------


def integration_names(src: Path) -> dict:
    """PROBES, NOT_IN_THE_ENGINE and DEVICE_CONSTANTS of tests/integration/test_privacytests.py, read without
    importing it (it needs the test harness)."""
    tree = ast.parse((src / INTEGRATION_TEST).read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        if isinstance(target, ast.Name) and target.id in ("PROBES", "NOT_IN_THE_ENGINE", "DEVICE_CONSTANTS"):
            found[target.id] = ast.literal_eval(node.value)
    if set(found) != {"PROBES", "NOT_IN_THE_ENGINE", "DEVICE_CONSTANTS"} or tuple(found["PROBES"]) != GROUPS:
        raise ComparisonError(f"{INTEGRATION_TEST}: PROBES, NOT_IN_THE_ENGINE and DEVICE_CONSTANTS not found as expected")
    if ONE_ARCHITECTURE not in found["DEVICE_CONSTANTS"]:
        raise ComparisonError(f"{ONE_ARCHITECTURE!r} is no longer a Device constant of {INTEGRATION_TEST}")
    return found


# -- their page and their data file ---------------------------------------------------------------


def parse_page(text: str) -> dict:
    """{"issue", "updated", "columns": [browser], "rows": {probe: {browser: verdict}}} from their page.

    Every row has one cell per column, and every cell one of the three marks their page draws; anything else
    stops here, so a new kind of cell or a missing one cannot shift a column."""
    banner = re.search(r'id="issueBanner">.*?No\.\s*(\d+).*?Updated\s+(\d{4}-\d{2}-\d{2})', text, re.S)
    table = re.search(r'<table class="comparison-table">(.*?)</table>', text, re.S)
    if not banner or not table:
        raise ComparisonError("their page has no issue banner or no comparison table")
    header = re.search(r"<tr>(.*?)</tr>", table.group(1), re.S).group(1)
    columns = re.findall(r'<img\b[^>]*\balt="([a-z]+) logo"', header)
    if not columns or len(set(columns)) != len(columns):
        raise ComparisonError(f"their page's columns are not one browser each: {columns}")
    rows: dict[str, dict[str, str]] = {}
    for title in SECTIONS.values():
        start = table.group(1).find(f'<span class="subheading-title">{title}</span>')
        if start < 0:
            raise ComparisonError(f"their page has no section {title!r}")
        end = table.group(1).find('<span class="subheading-title">', start + 1)
        section = table.group(1)[start : end if end > 0 else None]
        for row in re.findall(r"<tr>(.*?)</tr>", section, re.S):
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
            if not cells:
                continue  # the section's own heading
            name = re.search(r"<div>(.*?)</div>", cells[0], re.S)
            if not name:
                raise ComparisonError(f"{title}: a row without a probe name")
            probe = html.unescape(name.group(1).strip())
            if len(cells) - 1 != len(columns):
                raise ComparisonError(f"{probe}: {len(cells) - 1} cells for {len(columns)} browsers")
            verdicts = {}
            for browser, cell in zip(columns, cells[1:], strict=True):
                marks = [tag for tag in re.findall(r"<img\b[^>]*>", cell) if "dataPoint" in tag]
                pairs = [(re.search(r'\balt="([^"]*)"', tag), re.search(r'\bclass="dataPoint ([a-z]+)"', tag)) for tag in marks]
                if len(pairs) != 1 or not all(pairs[0]):
                    raise ComparisonError(f"{probe}, {browser}: not one mark in the cell")
                verdict = CELL.get((pairs[0][0].group(1), pairs[0][1].group(1)))
                if verdict is None:
                    raise ComparisonError(f"{probe}, {browser}: unknown mark {pairs[0][0].group(1)!r}")
                verdicts[browser] = verdict
            if probe in rows:
                raise ComparisonError(f"{probe}: two rows")
            rows[probe] = verdicts
    return {"issue": int(banner.group(1)), "updated": banner.group(2), "columns": columns, "rows": rows}


def value_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def parse_data(data: dict) -> dict:
    """Per browser: its version, runners and, per probe, what each run read (data file's all_tests)."""
    if data.get("platform") != "Desktop":
        raise ComparisonError(f"their data file is for {data.get('platform')!r}, not Desktop")
    browsers: dict[str, dict] = {}
    for test in data["all_tests"]:
        if test.get("incognito") or test.get("nightly"):
            raise ComparisonError(f"{test['browser']}: a private or nightly run in the desktop file")
        entry = browsers.setdefault(test["browser"], {"versions": set(), "runners": [], "runs": {}})
        entry["versions"].add(test["reportedVersion"])
        entry["runners"].append(test["runner"])
        for group in ("device_fingerprinting", "settings_fingerprinting"):
            for probe, result in test["testResults"].get(group, {}).items():
                if group == "device_fingerprinting":
                    run = {"randomized": result.get("randomized", False), "value": value_digest(result.get("value"))}
                    if result.get("prompted"):
                        run["prompted"] = True
                else:
                    run = {"passed": result.get("passed")}
                entry["runs"].setdefault(probe, []).append(run)
    out = {}
    for browser, entry in browsers.items():
        if len(entry["versions"]) != 1:
            raise ComparisonError(f"{browser}: runs of different versions {sorted(entry['versions'])}")
        out[browser] = {"version": entry["versions"].pop(), "runners": entry["runners"], "runs": entry["runs"]}
    return {"time_started": data["timeStarted"], "harness": data["git"], "browsers": out}


def rule(group: str, runs: list[dict]) -> bool:
    """The plain rule over the runs (their render.js, scoreDeviceFingerprintingConsistency; Settings: passed)."""
    if not runs:
        raise ComparisonError("a cell with no run")
    if group == "Device":
        if any(run.get("prompted") for run in runs) or all(run["randomized"] is True for run in runs):
            return True
        return len({run["value"] for run in runs}) == 1
    return all(run["passed"] is True for run in runs)


def group_of(probes: dict, probe: str) -> str:
    return next(group for group, names in probes.items() if probe in names)


def published(page: dict, data: dict, probes: dict, sources: dict) -> dict:
    """The fixture: their page's cells, each with the runs it comes from."""
    names = {probe for group in probes.values() for probe in group}
    if set(page["columns"]) - set(BROWSERS):
        raise ComparisonError(f"a browser this script does not name yet: {sorted(set(page['columns']) - set(BROWSERS))}")
    if set(page["columns"]) != set(data["browsers"]):
        raise ComparisonError("their page and their data file do not have the same browsers")
    if set(page["rows"]) - names:
        raise ComparisonError(f"probes on their page that the integration test does not run: {sorted(set(page['rows']) - names)}")
    rows = {}
    for probe in sorted(page["rows"], key=lambda p: [*GROUPS].index(group_of(probes, p))):
        group, cells = group_of(probes, probe), {}
        for browser in page["columns"]:
            runs = data["browsers"][browser]["runs"].get(probe)
            if not runs:
                raise ComparisonError(f"{probe}, {browser}: on their page but not in their data file")
            verdict = page["rows"][probe][browser]
            plain = "passed" if rule(group, runs) else "failed"
            exception = (browser, probe) in PAGE_OVER_RULE
            if verdict != "unsupported" and (verdict != plain) != exception:
                raise ComparisonError(f"{probe}, {browser}: their page says {verdict}, the runs say {plain}: read the cell")
            cells[browser] = {"verdict": verdict, "runs": runs}
        rows[probe] = cells
    return {
        "comment": "Written by scripts/site/privacytests_pages.py refresh from the two files under sources. Do not edit.",
        "sources": sources,
        "issue": page["issue"],
        "updated": page["updated"],
        "time_started": data["time_started"],
        "harness": data["harness"],
        "browsers": [
            {"id": b, "version": data["browsers"][b]["version"], "runners": data["browsers"][b]["runners"]}
            for b in page["columns"]
        ],
        "rows": rows,
        "not_on_page": sorted(names - set(page["rows"])),
    }


# -- Nulavio's run --------------------------------------------------------------------------------


def parse_log(lines: list[str]) -> tuple[dict[str, str], str | None]:
    """({probe: ok | skipped | FAIL | ERROR}, the outcome of the test that says what the engine does not have)."""
    results, unsupported = {}, None
    for line in lines:
        match = LOG_LINE.match(line)
        if match:
            outcome = match.group(3).split()[0]
            if match.group(2) in results:
                raise ComparisonError(f"{match.group(2)}: two results in the log")
            results[match.group(2)] = outcome
        elif UNSUPPORTED_LINE.match(line):
            unsupported = UNSUPPORTED_LINE.match(line).group(1).split()[0]
    return results, unsupported


def strip_timestamp(line: str) -> str:
    return re.sub(r"^﻿?\d{4}-\d\d-\d\dT[0-9:.]+Z ", "", line.rstrip("\r\n"))


def nulavio_marks(fixture: dict, probes: dict) -> dict[str, str]:
    """Nulavio's mark per probe, read from its run's result lines."""
    results, unsupported = parse_log(fixture["log"])
    names = {probe for group in probes.values() for probe in group}
    if set(results) != names:
        raise ComparisonError(f"the run's probes are not the integration test's: {sorted(set(results) ^ names)}")
    marks = {}
    for probe, outcome in results.items():
        if outcome != "ok":
            marks[probe] = "failed"  # failed, or skipped as a known gap: it does not pass their rule
        elif probe in probes["NOT_IN_THE_ENGINE"]:
            if unsupported != "ok":
                raise ComparisonError(f"{probe} passed, but the run does not show the engine answering Unsupported")
            marks[probe] = "unsupported"
        elif probe == ONE_ARCHITECTURE:
            marks[probe] = "one-architecture"
        else:
            marks[probe] = "passed"
    return marks


# -- marks, shared by the page and the picture ----------------------------------------------------

# 20x20 drawings in the colour of the text around them: a shape each, so the mark is not its colour alone.
SHAPES = {
    "passed": '<circle cx="10" cy="10" r="7.25"/><path d="M6.6 10.3l2.4 2.4 4.6-5"/>',
    "failed": '<path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/>',
    "unsupported": '<path d="M5 10h10"/>',
    "one-architecture": '<circle cx="10" cy="10" r="7.25"/><path d="M8.4 7.6l2-1.4v8"/>',
    "not-on-page": '<circle cx="10" cy="10" r="1.6" class="fill"/>',
}
TEXT = {
    "pt-BR": {
        "passed": "passou",
        "failed": "falhou",
        "unsupported": "não tem o recurso",
        "one-architecture": "passou com uma só arquitetura",
        "not-on-page": "fora da página deles",
    },
    "en-US": {
        "passed": "passed",
        "failed": "failed",
        "unsupported": "no such feature",
        "one-architecture": "passed with one architecture",
        "not-on-page": "not on their page",
    },
}


def comparison(src: Path) -> dict:
    """Everything the page and the picture show, from the two fixtures and the integration test."""
    probes = integration_names(src)
    pub = json.loads((src / FIXTURES / PUBLISHED).read_text(encoding="utf-8"))
    run = json.loads((src / FIXTURES / NULAVIO).read_text(encoding="utf-8"))
    groups = {group: list(names) for group, names in probes["PROBES"].items()}
    names = {probe for group in groups.values() for probe in group}
    if set(pub["rows"]) | set(pub["not_on_page"]) != names or set(pub["rows"]) & set(pub["not_on_page"]):
        raise ComparisonError("published.json's probes are not the integration test's")
    columns = [b["id"] for b in pub["browsers"]]
    if set(columns) - set(BROWSERS):
        raise ComparisonError(f"published.json names an unknown browser: {sorted(set(columns) - set(BROWSERS))}")
    published_marks = {}
    for probe in names:
        if probe in pub["not_on_page"]:
            published_marks[probe] = dict.fromkeys(columns, "not-on-page")
            continue
        cells = pub["rows"][probe]
        if list(cells) != columns:
            raise ComparisonError(f"{probe}: the cells are not one per browser, in the page's order")
        published_marks[probe] = {b: cells[b]["verdict"] for b in columns}
    return {
        "groups": groups,
        "columns": columns,
        "published": pub,
        "run": run,
        "nulavio": nulavio_marks(run, {**groups, "NOT_IN_THE_ENGINE": probes["NOT_IN_THE_ENGINE"]}),
        "marks": published_marks,
    }


# -- the page -------------------------------------------------------------------------------------

GLOSS = {
    "Logical CPU cores": ("Quantos núcleos o processador tem", "How many cores the processor has"),
    "Device memory": ("Quanta memória o computador tem", "How much memory the computer has"),
    "JavaScript heap size limit": (
        "Quanta memória uma página pode usar, que acompanha a do computador",
        "How much memory a page may use, which follows the computer's",
    ),
    "Math: Infinity - Infinity": ("Um byte que muda com o tipo de processador", "A byte that changes with the type of processor"),
    "Math.tan(-1e300)": (
        "Os últimos dígitos de uma conta, que podem seguir o sistema",
        "The last digits of a calculation, which can follow the system",
    ),
    "Math.sin(-1e300)": ("Outra conta do mesmo tipo", "Another calculation of the same kind"),
    "Math.tanh(0.123)": ("Uma terceira conta do mesmo tipo", "A third calculation of the same kind"),
    "AudioContext fingerprint": (
        "Um som calculado pelo navegador, que sai um pouco diferente em cada máquina",
        "A sound the browser computes, which comes out slightly different on each machine",
    ),
    "Canvas2D geometry": (
        "Um desenho cujo resultado acompanha o sistema gráfico",
        "A drawing whose result follows the graphics system",
    ),
    "userAgentData.architecture": (
        "O tipo de processador, informado pelo navegador",
        "The type of processor, as the browser reports it",
    ),
    "userAgentData.platformVersion": ("A versão do sistema operacional", "The operating system's version"),
    "AudioContext base latency": ("O atraso do dispositivo de som", "The sound device's delay"),
    "Time zone": ("O seu fuso horário", "Your time zone"),
    "Reduced motion preference": ("Se você pediu ao sistema menos animação", "Whether you asked the system for less animation"),
    "Reduced transparency preference": ("Se você pediu menos transparência", "Whether you asked for less transparency"),
    "Display contrast preference": ("Se você pediu mais contraste", "Whether you asked for more contrast"),
    "Keyboard layout": ("O layout do seu teclado", "Your keyboard layout"),
    "Available screen width": (
        "A largura útil da tela, sem os painéis do sistema",
        "The screen's usable width, without the system's panels",
    ),
    "Available screen height": ("A altura útil da tela", "The screen's usable height"),
    "Available screen left": (
        "Onde começa a área útil, que mostra onde ficam os painéis",
        "Where the usable area starts, which shows where the panels are",
    ),
    "Available screen top": ("O mesmo, no alto da tela", "The same, at the top of the screen"),
    "User-installed font (DOM)": (
        "Se uma fonte que você instalou aparece no texto",
        "Whether a font you installed shows in text",
    ),
    "User-installed font (canvas)": ("O mesmo, num desenho", "The same, in a drawing"),
    "Screen width": ("A largura da tela", "The screen's width"),
    "Screen height": ("A altura da tela", "The screen's height"),
}
WORDS = {
    "pt-BR": {
        "lang": "pt-BR", "og_locale": "pt_BR", "home": "/", "engineering": "/engenharia/", "other": "en-US",
        "other_name": "English", "skip": "Pular para o conteúdo", "date": "%d/%m/%Y",
        "title": "Impressão digital: os testes do PrivacyTests.org lado a lado",
        "description": (
            "Os 25 testes de impressão digital do PrivacyTests.org: o que ele publicou para doze navegadores e o que "
            "o Nulavio {v} dá nos mesmos testes, numa medição nossa."
        ),
        "og_alt": (
            "Tabela de marcas: os 25 testes de impressão digital do PrivacyTests.org, o Nulavio {v} na medição do "
            "próprio Nulavio e doze navegadores no que o PrivacyTests.org publicou."
        ),
        "pill": "Medição do Nulavio ao lado da publicação do PrivacyTests.org",
        "h1": "Impressão digital: os testes do PrivacyTests.org lado a lado",
        "lead": (
            "Um site pode reconhecer você sem cookies, pelo que lê do seu computador e das suas configurações. "
            "O PrivacyTests.org publica como uma dúzia de navegadores se sai em 25 testes disso. Rodamos os mesmos "
            "testes, com as páginas de teste e a regra de aprovação deles, numa versão publicada do Nulavio. "
            "A tabela põe as duas coisas lado a lado: é a nossa medição ao lado da deles, não um ranking."
        ),
        "facts": "De onde vem cada coluna",
        "fact_nulavio": "Coluna do Nulavio",
        "fact_nulavio_v": "{v}, publicada em {published}; medição nossa em {measured}, no Linux",
        "fact_them": "Outras colunas",
        "fact_them_v": "PrivacyTests.org, edição nº {issue}, testes de {tested}, no macOS",
        "probes_h": "Os 25 testes",
        "key": "Marcas",
        "legend_h": "Como ler",
        "legend": {
            "passed": (
                "Um site não distingue você por isso: o valor é o mesmo em todas as máquinas testadas, ou muda a cada site."
            ),
            "failed": "O valor acompanha o seu computador ou as suas configurações.",
            "unsupported": "O navegador não tem o recurso que o teste lê; não há o que ler.",
            "one-architecture": "Passou só porque o Nulavio tem uma versão, para processadores x86-64 (veja as notas).",
            "not-on-page": "A página do PrivacyTests.org não tem linha para este teste.",
        },
        "legend_names": {
            "passed": "Passou", "failed": "Falhou", "unsupported": "Não tem o recurso",
            "one-architecture": "Uma só arquitetura", "not-on-page": "Fora da página deles",
        },
        "groups": {
            "Device": ("Aparelho", "o que o computador é"),
            "Settings": ("Configurações", "o que você escolheu no sistema"),
            "Screen": ("Tela", "o tamanho do monitor"),
        },
        "caption": "{name}: {what}. {n} testes.",
        "probe": "Teste",
        "nulavio_head": "medição nossa",
        "scroll": "Role para o lado para ver os treze navegadores.",
        "region": "Tabela {name}",
        "notes_h": "O que a tabela não diz",
        "notes": [
            (
                "Duas medições, não uma.",
                "A coluna do Nulavio é medição do próprio Nulavio, com as páginas de teste do PrivacyTests.org "
                "(commit {pages} do repositório deles) e a regra de aprovação deles. O PrivacyTests.org não testou o "
                "Nulavio e não tem relação com o projeto. As outras doze colunas são o que o PrivacyTests.org "
                "publicou na edição nº {issue}.",
            ),
            (
                "Máquinas e sistemas diferentes.",
                "Eles rodaram cada navegador cinco vezes, em máquinas macOS do GitHub, com processadores Apple e "
                "Intel, e um teste de aparelho passa quando o valor é o mesmo nas máquinas. Nós rodamos o Nulavio "
                "{v} no Linux, numa máquina do GitHub com processador x86-64; o nosso teste troca as configurações "
                "do sistema entre duas sessões e confere cada valor de aparelho com um valor fixo, o mesmo em "
                "todas as máquinas em que roda.",
            ),
            (
                "Uma só arquitetura.",
                "“Math: Infinity - Infinity” lê um byte que muda entre processadores ARM e x86. Todos os navegadores "
                "publicados falham porque as rodadas deles misturam os dois. O Nulavio só tem versão para x86-64, "
                "então o valor dele é constante só por isso: por isso a marca própria, e não um “passou”.",
            ),
            (
                "Sem o recurso.",
                "O Nulavio responde “não suportado” ao layout do teclado e à preferência por menos transparência. "
                "Desde 16/11/2026 as páginas de teste do PrivacyTests.org mostram essa resposta como “–”. As colunas "
                "publicadas são de antes dessa regra, quando a mesma resposta contava como aprovação. Como as "
                "colunas não são contadas do mesmo jeito, esta página não mostra totais.",
            ),
            (
                "Um teste que não está na página deles.",
                "O arquivo de dados da edição nº {issue} tem valores para “Math.tanh(0.123)”, mas a página deles "
                "não tem linha para esse teste. As doze colunas publicadas aparecem com “·” nele.",
            ),
            (
                "Não é tudo.",
                "Estes 25 testes são algumas das formas de um site distinguir você, não todas. O endereço de "
                "internet não está entre elas, e um site atento ainda percebe que é o Nulavio. Para sumir na "
                "multidão, use o Tor Browser ou o Mullvad Browser.",
            ),
        ],
        "sources_h": "De onde vêm os números",
        "source_them": (
            "Resultados publicados pelo PrivacyTests.org (Arthur Edelstein e colaboradores), edição nº {issue}, "
            "testes iniciados em {started} UTC com o código deles no commit {harness}: a aprovação de cada célula é "
            "a que a página deles mostra. A página, de {page_modified}, tem SHA-256 {page_sha}; o arquivo de dados, "
            "de {data_modified}, tem SHA-256 {data_sha}. Lidos em {read}. O código do PrivacyTests.org usa a licença "
            "MIT; o site e os resultados não declaram termos de uso."
        ),
        "source_us": (
            "Nulavio {v}, versão publicada em {published}: o job “device” do workflow privacytests, que roda "
            "{test} sobre o arquivo da própria versão, conferido com o SHA256SUMS assinado, numa máquina "
            "{runner} do GitHub, em {measured}."
        ),
        "made_h": "Como esta página é feita",
        "made": (
            "Gerada por {script} a partir de dois arquivos, que só o comando “refresh” escreve: {fixtures}. "
            "Um teste confere cada célula com as rodadas de onde vem e os nomes dos testes com {test}. Quando o "
            "PrivacyTests.org publica uma edição nova ou sai uma versão do Nulavio, o mesmo comando atualiza os "
            "arquivos, esta página e a imagem de compartilhamento; o aviso semanal ({watch}) diz quando os dados "
            "publicados mudaram."
        ),
        "back": "Voltar ao documento de engenharia",
        "affiliation": (
            "O Nulavio é feito sobre o motor Gecko, da Mozilla. O Nulavio não é afiliado à Mozilla nem ao "
            "PrivacyTests.org. Firefox é uma marca registrada da Mozilla Foundation."
        ),
        "revision": "Revisão de {date}",
        "picture_title": "Os 25 testes de impressão digital do PrivacyTests.org, lado a lado",
        "picture_sub": (
            "Nulavio {v}: medição do próprio Nulavio, no Linux, em {measured}.",
            "Outros: publicado pelo PrivacyTests.org, edição nº {issue}, no macOS, em {tested}. "
            "Sem totais: as colunas não contam igual.",
        ),
        "picture_nulavio": "medição nossa",
        "picture_groups": {"Device": "Aparelho", "Settings": "Configurações", "Screen": "Tela"},
    },
    "en-US": {
        "lang": "en", "og_locale": "en_US", "home": "/en/", "engineering": "/en/engineering/", "other": "pt-BR",
        "other_name": "Português", "skip": "Skip to content", "date": "%Y-%m-%d",
        "title": "Fingerprinting: PrivacyTests.org's probes side by side",
        "description": (
            "PrivacyTests.org's 25 fingerprinting probes: what it published for twelve browsers, and what Nulavio "
            "{v} gets on the same probes, in a measurement of our own."
        ),
        "og_alt": (
            "A table of marks: PrivacyTests.org's 25 fingerprinting probes, Nulavio {v} in Nulavio's own "
            "measurement, and twelve browsers as PrivacyTests.org published them."
        ),
        "pill": "Nulavio's measurement next to PrivacyTests.org's publication",
        "h1": "Fingerprinting: PrivacyTests.org's probes side by side",
        "lead": (
            "A site can recognise you without cookies, from what it reads about your computer and your settings. "
            "PrivacyTests.org publishes how a dozen browsers do on 25 tests of that. We ran the same tests, with their "
            "test pages and their pass rule, on a published Nulavio release. The table puts the two side by side: "
            "it is our measurement next to theirs, not a ranking."
        ),
        "facts": "Where each column comes from",
        "fact_nulavio": "Nulavio's column",
        "fact_nulavio_v": "{v}, published {published}; our measurement on {measured}, on Linux",
        "fact_them": "Other columns",
        "fact_them_v": "PrivacyTests.org, No. {issue}, tests of {tested}, on macOS",
        "probes_h": "The 25 tests",
        "key": "Marks",
        "legend_h": "How to read it",
        "legend": {
            "passed": (
                "A site cannot tell you apart by this: the value is the same on every machine tested, or changes on every site."
            ),
            "failed": "The value follows your computer or your settings.",
            "unsupported": "The browser does not have what the test reads; there is nothing to read.",
            "one-architecture": "Passed only because Nulavio has one build, for x86-64 processors (see the notes).",
            "not-on-page": "PrivacyTests.org's page has no row for this test.",
        },
        "legend_names": {
            "passed": "Passed", "failed": "Failed", "unsupported": "No such feature",
            "one-architecture": "One architecture", "not-on-page": "Not on their page",
        },
        "groups": {
            "Device": ("Device", "what the computer is"),
            "Settings": ("Settings", "what you chose in the system"),
            "Screen": ("Screen", "the display's size"),
        },
        "caption": "{name}: {what}. {n} tests.",
        "probe": "Test",
        "nulavio_head": "our measurement",
        "scroll": "Scroll sideways to see the thirteen browsers.",
        "region": "{name} table",
        "notes_h": "What the table does not say",
        "notes": [
            (
                "Two measurements, not one.",
                "Nulavio's column is Nulavio's own measurement, with PrivacyTests.org's test pages (commit {pages} of "
                "their repository) and their pass rule. PrivacyTests.org has not tested Nulavio and has no connection "
                "with the project. The other twelve columns are what PrivacyTests.org published in No. {issue}.",
            ),
            (
                "Different machines and systems.",
                "They ran each browser five times, on GitHub's macOS machines, with Apple and Intel processors, and a "
                "device test passes when the value is the same on those machines. We ran Nulavio {v} on Linux, on a "
                "GitHub machine with an x86-64 processor; our test changes the system's settings between two "
                "sessions and holds each device value to one fixed value, the same on every machine it runs on.",
            ),
            (
                "One architecture.",
                "“Math: Infinity - Infinity” reads a byte that differs between ARM and x86 processors. Every published "
                "browser fails it because their runs mix the two. Nulavio has an x86-64 build only, so its value is "
                "constant for that reason alone: hence its own mark, not a “passed”.",
            ),
            (
                "No such feature.",
                "Nulavio answers “unsupported” for the keyboard layout and for the reduced transparency preference. "
                "Since 2026-11-16 PrivacyTests.org's test pages show that answer as “–”. The published columns are "
                "from before that rule, when the same answer counted as passed. As the columns are not counted the "
                "same way, this page shows no totals.",
            ),
            (
                "A test that is not on their page.",
                "The data file of No. {issue} has values for “Math.tanh(0.123)”, but their page has no row for it. "
                "The twelve published columns show “·” there.",
            ),
            (
                "Not everything.",
                "These 25 tests are some of the ways a site can tell you apart, not all of them. Your internet "
                "address is not among them, and a careful site can still tell it is talking to Nulavio. To blend "
                "into the crowd, use Tor Browser or Mullvad Browser.",
            ),
        ],
        "sources_h": "Where the numbers come from",
        "source_them": (
            "Results published by PrivacyTests.org (Arthur Edelstein and contributors), No. {issue}, tests started "
            "{started} UTC with their code at commit {harness}: each cell's pass or fail is what their page shows. "
            "The page, of {page_modified}, has SHA-256 {page_sha}; the data file, of {data_modified}, has SHA-256 "
            "{data_sha}. Read on {read}. PrivacyTests.org's code is under the MIT license; the site and the results "
            "state no terms of use."
        ),
        "source_us": (
            "Nulavio {v}, released {published}: the “device” job of the privacytests workflow, which runs {test} on "
            "the release's own archive, checked against its signed SHA256SUMS, on a GitHub {runner} machine, on "
            "{measured}."
        ),
        "made_h": "How this page is made",
        "made": (
            "Generated by {script} from two files that only its “refresh” command writes: {fixtures}. A test holds "
            "each cell to the runs it comes from and the test names to {test}. When PrivacyTests.org publishes a new "
            "issue or Nulavio releases, the same command updates the files, this page and the picture for sharing; "
            "the weekly check ({watch}) says when the published data moved."
        ),
        "back": "Back to the engineering document",
        "affiliation": (
            "Nulavio is built on Mozilla's Gecko engine. Nulavio is not affiliated with Mozilla or with "
            "PrivacyTests.org. Firefox is a trademark of the Mozilla Foundation."
        ),
        "revision": "Revision of {date}",
        "picture_title": "PrivacyTests.org's 25 fingerprinting probes, side by side",
        "picture_sub": (
            "Nulavio {v}: Nulavio's own measurement, on Linux, on {measured}.",
            "Others: published by PrivacyTests.org, No. {issue}, on macOS, on {tested}. "
            "No totals: the columns are not counted alike.",
        ),
        "picture_nulavio": "our measurement",
        "picture_groups": {"Device": "Device", "Settings": "Settings", "Screen": "Screen"},
    },
}  # fmt: skip


def e(text: str) -> str:
    return html.escape(str(text), quote=True)


def day(value: str, locale: str) -> str:
    return dt.date.fromisoformat(value[:10]).strftime(WORDS[locale]["date"])


def breaks(probe: str) -> str:
    """A probe's name may wrap after a dot, not inside a word."""
    return e(probe).replace(".", ".<wbr>")


def ref(text: str) -> str:
    return f'<code class="ref" translate="no">{e(text)}</code>'


def facts(c: dict, locale: str) -> dict[str, str]:
    """The values the words are filled with."""
    pub, run = c["published"], c["run"]
    return {
        "v": run["version"],
        "published": day(run["published_at"], locale),
        "measured": day(run["job"]["completed_at"], locale),
        "issue": str(pub["issue"]),
        "tested": day(pub["time_started"], locale),
        "pages": run["pages"][:8],
    }


def mark(kind: str, locale: str) -> str:
    return (
        f'<svg class="mark mark-{kind}" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">'
        f'<use href="#m-{kind}"/></svg><span class="visually-hidden">{TEXT[locale][kind]}</span>'
    )


def sprite() -> str:
    symbols = "".join(f'<symbol id="m-{kind}" viewBox="0 0 20 20">{SHAPES[kind]}</symbol>\n' for kind in MARKS)
    return f'<svg class="sprite" aria-hidden="true" focusable="false">\n{symbols}</svg>\n'


def table(c: dict, group: str, locale: str) -> str:
    w, v = WORDS[locale], facts(c, locale)
    name, what = w["groups"][group]
    gid = group.lower()
    versions = {b["id"]: b["version"] for b in c["published"]["browsers"]}
    heads = (
        f'<th scope="col" class="col-nulavio">Nulavio <span class="head-meta mono">{e(v["v"])}</span>'
        f'<span class="head-meta">{w["nulavio_head"]}</span></th>\n'
    )
    heads += "".join(
        f'<th scope="col">{e(BROWSERS[b])} <span class="head-meta mono">{e(".".join(versions[b].split(".")[:2]))}</span></th>\n'
        for b in c["columns"]
    )
    rows = ""
    for probe in c["groups"][group]:
        gloss = GLOSS[probe][0 if locale == "pt-BR" else 1]
        cells = f'<td class="col-nulavio">{mark(c["nulavio"][probe], locale)}</td>\n'
        cells += "".join(f"<td>{mark(c['marks'][probe][b], locale)}</td>\n" for b in c["columns"])
        rows += (
            f'<tr>\n<th scope="row"><span class="probe" lang="en" translate="no">{breaks(probe)}</span>'
            f'<span class="gloss">{e(gloss)}</span></th>\n{cells}</tr>\n'
        )
    caption = w["caption"].format(name=f"<strong>{e(name)}</strong>", what=e(what), n=len(c["groups"][group]))
    return f"""<div class="table-scroll comparison" role="region" aria-labelledby="t-{gid}-cap" tabindex="0">
<table>
<caption id="t-{gid}-cap">{caption}</caption>
<thead>
<tr>
<th scope="col">{w["probe"]}</th>
{heads}</tr>
</thead>
<tbody>
{rows}</tbody>
</table>
</div>
<p class="scroll-hint">{w["scroll"]}</p>
"""


def body(c: dict, locale: str) -> str:
    w, v = WORDS[locale], facts(c, locale)
    pub, run = c["published"], c["run"]
    legend = "".join(
        f"<div><dt>{mark(kind, locale).split('<span')[0]}{w['legend_names'][kind]}</dt><dd>{w['legend'][kind]}</dd></div>\n"
        for kind in MARKS
    )
    key = "".join(f"<li>{mark(kind, locale).split('<span')[0]}{w['legend_names'][kind]}</li>\n" for kind in MARKS)
    tables = "".join(table(c, group, locale) for group in GROUPS)
    notes = "".join(f"<li><strong>{e(head)}</strong> {e(text.format(**v))}</li>\n" for head, text in w["notes"])
    sources = pub["sources"]
    them = w["source_them"].format(
        issue=e(pub["issue"]),
        started=e(pub["time_started"].replace("T", " ")[:16]),
        harness=ref(pub["harness"][:8]),
        page_modified=e(sources["page"]["last_modified"]),
        page_sha=ref(sources["page"]["sha256"]),
        data_modified=e(sources["data"]["last_modified"]),
        data_sha=ref(sources["data"]["sha256"]),
        read=e(day(sources["read"], locale)),
    )
    us = w["source_us"].format(
        v=e(run["version"]),
        published=e(v["published"]),
        test=ref(str(INTEGRATION_TEST)),
        runner=e(run["job"]["runner"]),
        measured=e(v["measured"]),
    )
    made = w["made"].format(
        script=ref("scripts/site/privacytests_pages.py"),
        fixtures=" ".join(ref(f"{FIXTURES}/{name}") for name in (PUBLISHED, NULAVIO)),
        test=ref(str(INTEGRATION_TEST)),
        watch=ref("scripts/research/watch_privacytests.py"),
    )
    addresses_them = " · ".join(
        f'<span translate="no">{e(a)}</span>'
        for a in (
            "privacytests.org",
            "privacytests.org/index.json",
            f"github.com/privacytests/privacytests.org/tree/{pub['harness']}",
        )
    )
    addresses_us = " · ".join(
        f'<span translate="no">{e(a)}</span>'
        for a in (run["release_url"].removeprefix("https://"), run["job"]["url"].removeprefix("https://"))
    )
    return f"""<section id="summary" aria-labelledby="summary-h">
<div class="summary-text">
<p class="pill"><strong>{w["pill"]}</strong></p>
<h1 id="summary-h">{w["h1"]}</h1>
<p class="lead">{w["lead"]}</p>
<p class="prose"><a href="{w["engineering"]}">{w["back"]}</a></p>
</div>
<dl class="facts" aria-label="{w["facts"]}">
<div><dt>{w["fact_nulavio"]}</dt><dd>{e(w["fact_nulavio_v"].format(**v))}</dd></div>
<div><dt>{w["fact_them"]}</dt><dd>{e(w["fact_them_v"].format(**v))}</dd></div>
</dl>
</section>
<section id="probes" aria-labelledby="probes-h">
<h2 id="probes-h">{w["probes_h"]}</h2>
<ul class="marks-key" aria-label="{w["key"]}">
{key}</ul>
{tables}</section>
<section id="legend" aria-labelledby="legend-h">
<h2 id="legend-h">{w["legend_h"]}</h2>
<dl class="marks-legend">
{legend}</dl>
</section>
<section id="notes" aria-labelledby="notes-h">
<h2 id="notes-h">{w["notes_h"]}</h2>
<ul class="prose notes">
{notes}</ul>
</section>
<section id="sources" aria-labelledby="sources-h">
<h2 id="sources-h">{w["sources_h"]}</h2>
<ul class="prose notes">
<li>{them}<br>{addresses_them}</li>
<li>{us}<br>{addresses_us}</li>
</ul>
<h3 id="made-h">{w["made_h"]}</h3>
<p class="prose">{made}</p>
</section>
"""


def page(c: dict, locale: str, revision_date: str) -> str:
    w, v = WORDS[locale], facts(c, locale)
    other = w["other"]
    path, other_path = BASE[locale], BASE[other]
    lang = WORDS[other]["lang"]
    switch = f'<a href="/{other_path}" hreflang="{lang}" lang="{lang}">{w["other_name"]}</a>'
    url = f"https://nulavio.net/{path}"
    pt, en = (url, f"https://nulavio.net/{other_path}") if locale == "pt-BR" else (f"https://nulavio.net/{other_path}", url)
    image = f"https://nulavio.net/{OG[locale]}"
    description, alt = e(w["description"].format(**v)), e(w["og_alt"].format(**v))
    return f"""<!doctype html>
<html lang="{w["lang"]}">
<!-- Generated by scripts/site/build_site.py from tests/fixtures/privacytests/ (scripts/site/privacytests_pages.py). -->
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{e(w["title"])} · Nulavio</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="pt-BR" href="{pt}">
<link rel="alternate" hreflang="en" href="{en}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Nulavio">
<meta property="og:locale" content="{w["og_locale"]}">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(w["title"])}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="{OG_SIZE[0]}">
<meta property="og:image:height" content="{OG_SIZE[1]}">
<meta property="og:image:alt" content="{alt}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{image}">
<meta name="twitter:image:alt" content="{alt}">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/tokens.css">
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
{sprite()}<a class="skip" href="#main">{w["skip"]}</a>
<header class="masthead">
<a class="brand" href="{w["home"]}"><picture>
<source media="(prefers-color-scheme: dark)" srcset="/assets/nulavio-lockup-horizontal-on-dark.svg" width="132" height="27">
<img src="/assets/nulavio-lockup-horizontal.svg" alt="Nulavio" width="132" height="27">
</picture></a>
{switch.replace("<a ", '<a class="lang" ', 1)}
</header>
<main id="main">
{body(c, locale)}</main>
<footer class="colophon">
<div class="colophon-inner">
<p>{w["affiliation"]}</p>
<p>{w["revision"].format(date=revision_date)} · <a href="{w["home"]}">Nulavio</a> · {switch}</p>
</div>
</footer>
</body>
</html>
"""


def pages(src: Path, revision_date: dict[str, str]) -> dict[str, str]:
    """{page path: HTML}, both languages. Fails when the fixtures do not hold together."""
    c = comparison(src)
    return {f"{BASE[locale]}index.html": page(c, locale, revision_date[locale]) for locale in BASE}


# -- the picture for sharing ----------------------------------------------------------------------

PICTURE_COLOURS = {  # the brand's dark scheme (docs/brand/tokens.json), as scripts/site/og-template.html
    "bg": "#0F1C2A", "text": "#F1F7F5", "meta": "#BFD0D6", "rule": "#23495A", "tint": "#0E3B33",
    "passed": "#6FE0C5", "failed": "#E26D70", "unsupported": "#BFD0D6", "one-architecture": "#6FE0C5",
    "not-on-page": "#8FAAB5",
}  # fmt: skip
FONT = "Inter, 'Noto Sans', Cantarell, sans-serif"


def picture_svg(c: dict, locale: str) -> str:
    """1200x630: a row per browser, a column per probe, the same marks as the page."""
    w, v, k = WORDS[locale], facts(c, locale), PICTURE_COLOURS
    width, height = OG_SIZE
    left, label_w, cell, gap = 56, 300, 30, 14
    x0 = left + label_w
    xs, x = {}, x0
    for group in GROUPS:
        for probe in c["groups"][group]:
            xs[probe] = x
            x += cell
        x += gap
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{k["bg"]}"/>',
        f'<text x="{left}" y="70" font-family="{FONT}" font-size="34" font-weight="700" fill="{k["text"]}">'
        f"{e(w['picture_title'])}</text>",
    ]
    for i, line in enumerate(w["picture_sub"]):
        out.append(
            f'<text x="{left}" y="{108 + 26 * i}" font-family="{FONT}" font-size="19" fill="{k["meta"]}">'
            f"{e(line.format(**v))}</text>"
        )
    top = 190
    for group in GROUPS:
        first = xs[c["groups"][group][0]]
        span = cell * len(c["groups"][group])
        out.append(f'<text x="{first + span / 2}" y="{top - 14}" text-anchor="middle" font-family="{FONT}" font-size="16" '
                   f'font-weight="600" fill="{k["meta"]}">{e(w["picture_groups"][group])}</text>')  # fmt: skip
        out.append(f'<rect x="{first}" y="{top - 8}" width="{span - 4}" height="2" fill="{k["rule"]}"/>')
    row_h = 27
    rows = [("nulavio", f"Nulavio {run_version(c)}", w["picture_nulavio"])]
    versions = {b["id"]: b["version"] for b in c["published"]["browsers"]}
    rows += [(b, BROWSERS[b], ".".join(versions[b].split(".")[:2])) for b in c["columns"]]
    y = top
    for index, (browser, name, meta) in enumerate(rows):
        if index == 1:
            y += 10
        if browser == "nulavio":
            out.append(f'<rect x="{left - 10}" y="{y}" width="{x - left}" height="{row_h}" rx="6" fill="{k["tint"]}"/>')
        out.append(
            f'<text x="{left}" y="{y + 19}" font-family="{FONT}" font-size="17" '
            f'font-weight="{600 if browser == "nulavio" else 400}" '
            f'fill="{k["text"]}">{e(name)} <tspan fill="{k["meta"]}" font-weight="400" font-size="14">{e(meta)}</tspan></text>'
        )
        for group in GROUPS:
            for probe in c["groups"][group]:
                kind = c["nulavio"][probe] if browser == "nulavio" else c["marks"][probe][browser]
                out.append(picture_mark(kind, xs[probe] + 4, y + 4))
        y += row_h
    legend_y, lx = height - 40, left
    for kind in MARKS:
        out.append(picture_mark(kind, lx, legend_y - 15))
        label = w["legend_names"][kind]
        out.append(f'<text x="{lx + 26}" y="{legend_y}" font-family="{FONT}" font-size="16" fill="{k["meta"]}">{e(label)}</text>')
        lx += 26 + 9 * len(label) + 34
    out.append("</svg>")
    return "\n".join(out) + "\n"


def run_version(c: dict) -> str:
    return c["run"]["version"]


def picture_mark(kind: str, x: float, y: float) -> str:
    colour = PICTURE_COLOURS[kind]
    shape = SHAPES[kind].replace(' class="fill"', f' fill="{colour}"')
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{colour}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{shape}</g>'
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def draw_pictures(src: Path, firefox: str) -> dict:
    """Draw each language's picture with a headless Firefox in a throwaway profile; return picture.json."""
    c = comparison(src)
    record = {"comment": "Written by scripts/site/privacytests_pages.py picture: each PNG and the SVG it was drawn from."}
    with tempfile.TemporaryDirectory(prefix="nulavio-og-") as tmp:
        for locale, out in OG.items():
            svg = picture_svg(c, locale)
            source = Path(tmp) / f"{locale}.svg"
            source.write_text(svg, encoding="utf-8")
            profile = Path(tmp) / f"profile-{locale}"
            profile.mkdir(mode=0o700)
            target = src / "site" / out
            subprocess.run(
                [firefox, "--headless", "--no-remote", "--profile", str(profile),
                 f"--window-size={OG_SIZE[0]},{OG_SIZE[1]}", "--screenshot", str(target), source.as_uri()],
                check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "MOZ_HEADLESS": "1"},
            )  # fmt: skip
            data = target.read_bytes()
            size = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
            if data[:8] != b"\x89PNG\r\n\x1a\n" or size != OG_SIZE:
                raise ComparisonError(f"{out}: not a {OG_SIZE[0]}x{OG_SIZE[1]} PNG")
            record[locale] = {"png": out, "png_sha256": digest(data), "svg_sha256": digest(svg.encode())}
    return record


# -- refresh: reading what was published ----------------------------------------------------------


def fetch(url: str) -> tuple[bytes, str]:
    if url not in (PAGE_URL, DATA_URL):
        raise ComparisonError(f"{url}: only PrivacyTests.org's page and data file are read")
    request = urllib.request.Request(url, headers={"User-Agent": "nulavio-privacytests-comparison"})  # noqa: S310 (fixed https)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (fixed https)
            data = response.read(LIMIT + 1)
            modified = response.headers.get("Last-Modified", "")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ComparisonError(f"{url}: {error}") from None
    if len(data) > LIMIT:
        raise ComparisonError(f"{url}: larger than {LIMIT} bytes")
    return data, modified


def gh(*args: str):
    result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ComparisonError(f"gh {' '.join(args)}: {result.stderr.strip()[-300:]}")
    return result.stdout


def release_run(tag: str | None) -> dict:
    """The published release (the newest, or `tag`) and its privacytests `device` job's result lines."""
    releases = json.loads(gh("api", f"repos/{REPO}/releases?per_page=30"))
    chosen = [r for r in releases if not r["draft"] and (tag is None or r["tag_name"] == tag)]
    if not chosen:
        raise ComparisonError(f"no published release {tag or ''}".strip())
    release = chosen[0]
    tag = release["tag_name"]
    commit = json.loads(gh("api", f"repos/{REPO}/commits/{tag}"))["sha"]
    runs = json.loads(gh("api", f"repos/{REPO}/actions/workflows/privacytests.yml/runs?event=release&per_page=50"))
    for run in runs["workflow_runs"]:
        if run["head_branch"] != tag or run["head_sha"] != commit:
            continue
        jobs = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run['id']}/jobs"))["jobs"]
        device = [j for j in jobs if j["name"].startswith("the Device probes") and j["conclusion"] == "success"]
        if not device:
            continue
        job = device[0]
        log = [
            strip_timestamp(line)
            for line in gh("api", "--allow-escape-sequences", f"repos/{REPO}/actions/jobs/{job['id']}/logs").splitlines()
        ]
        lines = [line for line in log if LOG_LINE.match(line) or UNSUPPORTED_LINE.match(line)]
        pages_commit = re.search(
            r'"commit":\s*"([0-9a-f]{40})"',
            gh("api", f"repos/{REPO}/contents/tests/fixtures/privacytests/pinned.json?ref={tag}", "--jq", ".content | @base64d"),
        )
        return {
            "comment": "Written by scripts/site/privacytests_pages.py refresh from the release's privacytests run. Do not edit.",
            "version": tag.removeprefix("v"),
            "tag": tag,
            "commit": commit,
            "published_at": release["published_at"],
            "release_url": release["html_url"],
            "pages": pages_commit.group(1) if pages_commit else "",
            "run": {"id": run["id"], "url": run["html_url"], "event": run["event"]},
            "job": {
                "id": job["id"],
                "name": job["name"],
                "url": job["html_url"],
                "conclusion": job["conclusion"],
                "runner": " ".join(job.get("labels") or []) or "ubuntu-24.04",
                "completed_at": job["completed_at"],
            },
            "log": lines,
        }
    raise ComparisonError(f"{tag}: no privacytests run of the release with a successful device job")


def refresh(src: Path, tag: str | None) -> None:
    probes = integration_names(src)
    page_bytes, page_modified = fetch(PAGE_URL)
    data_bytes, data_modified = fetch(DATA_URL)
    sources = {
        "read": dt.date.today().isoformat(),
        "page": {"url": PAGE_URL, "sha256": digest(page_bytes), "bytes": len(page_bytes), "last_modified": page_modified},
        "data": {"url": DATA_URL, "sha256": digest(data_bytes), "bytes": len(data_bytes), "last_modified": data_modified},
    }
    fixture = published(parse_page(page_bytes.decode("utf-8")), parse_data(json.loads(data_bytes)), probes["PROBES"], sources)
    run = release_run(tag)
    names = {probe for group in probes["PROBES"].values() for probe in group}
    results, _ = parse_log(run["log"])
    if set(results) != names:
        raise ComparisonError(f"the run's log does not have the {len(names)} probes: {sorted(set(results) ^ names)}")
    nulavio_marks(run, {**probes["PROBES"], "NOT_IN_THE_ENGINE": probes["NOT_IN_THE_ENGINE"]})
    for name, value in ((PUBLISHED, fixture), (NULAVIO, run)):
        (src / FIXTURES / name).write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def firefox_path() -> str:
    found = os.environ.get("FIREFOX") or shutil.which("firefox")
    if not found:
        raise ComparisonError("the picture needs Firefox: set FIREFOX or put firefox on PATH")
    return found


def write_pictures(src: Path) -> None:
    record = draw_pictures(src, firefox_path())
    (src / FIXTURES / PICTURE).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("refresh", help="read what was published and rewrite the fixtures and the picture")
    one.add_argument("--tag", help="the release (default: the newest published one)")
    one.add_argument("--no-picture", action="store_true", help="leave the picture alone")
    sub.add_parser("picture", help="draw the picture for sharing from the fixtures")
    args = parser.parse_args()
    try:
        if args.command == "refresh":
            refresh(ROOT, args.tag)
            if not args.no_picture:
                write_pictures(ROOT)
        else:
            write_pictures(ROOT)
    except ComparisonError as error:
        parser.exit(1, f"privacytests_pages: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
