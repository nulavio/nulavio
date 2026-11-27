#!/usr/bin/env python3
"""Record short scenes of the real Nulavio build for nulavio.net and the promotion pieces (#173, #176).

One pipeline, two steps, because the release test container has the engine's libraries but no image
tools, and the host has the image tools but must not run the engine outside the shared test slot:

1. **capture** (needs the build; runs where the integration tests run). Each scene drives a throwaway
   profile of tests/lib/harness.GeckoProfileSession through Marionette, as the integration tests do,
   and writes the window's own pixels (WebDriver:TakeScreenshot of the browser window) as PNG frames,
   plus ``timeline.json``: when each frame is shown, where the scripted cursor is, the clicks, the
   captions and a transcript read from the DOM. Standard library only. It is started by name through
   the integration runner, which runs it in the release test container (FUSE for the Vault):

       NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS=<dir> \\
           scripts/release/run_integration.sh <install>/nulavio record_site_scenes.py

2. **compose** (no engine): draws the cursor and the click ripples on the frames, then encodes each
   scene as a muted VP9 WebM, an H.264 MP4, an animated WebP loop and a WebP poster, with WebVTT
   captions and a manifest (hashes, build, every edit; for each recording, when and with which script it
   was captured and which checkout composed it). Everything is made in a private temporary directory
   (TMPDIR) and copied to the output only when every scene encoded and every check passed, the manifest
   last. Needs Pillow and ffmpeg on the host (Fedora: python3-pillow, ffmpeg-free), the tools
   capture_site.py and the media fixtures already use.

       python3 -I scripts/site/record_site.py compose <dir>/recordings [--out docs/design/recordings/2026-11]

``scripts/site/record_site.sh <install>/nulavio`` runs both. Rerunning it records the same scenes
from the same script; the files differ byte for byte (frame timing and encoder versions), so the
manifest holds the hashes of the files that were committed, as the screenshots' manifest does.

What a recording changes, all listed in the manifest: the window's ``remotecontrol`` attribute is
removed (the striped address bar of automation); the cursor is drawn afterwards, because a headless
window has no pointer, so hover states are not shown; the time a new instance takes to start is cut
(a cut between windows says so); typing is shown at a fixed pace, one frame per key really typed.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import datetime as dt
import hashlib
import html
import http.server
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCENES = ("profile-opens", "link-routed", "protected-unlocks")
LOCALES = ("pt-BR", "en-US")
WINDOW_CSS = (1280, 800)
SCALE = 1.5
FPS = 30
TAIL = 0.6  # seconds added after the last hold
LOOP_MAX = 5.0  # an image that moves by itself stops within 5 s (WCAG 2.2.2), so the loop plays once
CAPTION_CPS = 20  # a caption is on screen long enough to be read: at most this many characters a second
CLICK_LENGTH = 0.45  # seconds a click's ripple lasts
TYPE_STEP = 0.075  # seconds per typed key in the video
MOVE = 0.75  # seconds for a cursor move
OUT = ROOT / "docs" / "design" / "recordings" / "2026-11"

DOM_CHANGES = ["removed the remotecontrol attribute from each browser window's root element (automation cue)"]
EDITS = [
    "cursor and click ripples drawn on the frames afterwards (a headless window has no pointer; hover states are not shown)",
    "typing shown at a fixed pace of one frame per key, each key really typed into the field",
    "while a new instance starts, nothing is recorded: the video cuts to its window once it is up",
    f"the last frame is held for {TAIL} s at the end",
]

# -- pure helpers (tests/unit/test_record_site.py) ----------------------------------------------


def ease(u: float) -> float:
    """Ease-in-out (cubic) on 0..1: the cursor starts and stops softly and never overshoots."""
    u = min(1.0, max(0.0, u))
    return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def cursor_at(keys: list[dict], t: float) -> tuple[float, float] | None:
    """The cursor at video time t: eased between consecutive keyframes, hidden after a ``None`` key."""
    if not keys or t < keys[0]["t"]:
        return None
    index = max(i for i, k in enumerate(keys) if k["t"] <= t)
    here = keys[index]
    if here["xy"] is None:
        return None
    following = keys[index + 1] if index + 1 < len(keys) else None
    if following is None or following["xy"] is None or following["t"] <= here["t"]:
        return tuple(here["xy"])
    u = ease((t - here["t"]) / (following["t"] - here["t"]))
    (x0, y0), (x1, y1) = here["xy"], following["xy"]
    return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)


def frame_at(frames: list[dict], t: float) -> str:
    """The captured frame shown at video time t: the last one taken at or before t."""
    shown = [f for f in frames if f["t"] <= t]
    return (shown[-1] if shown else frames[0])["file"]


def ripples_at(clicks: list[dict], t: float, length: float = CLICK_LENGTH) -> list[tuple[float, float, float]]:
    """Clicks still showing at t, with how far each ripple has run (0..1)."""
    return [(c["xy"][0], c["xy"][1], (t - c["t"]) / length) for c in clicks if 0 <= t - c["t"] < length]


def duration_of(timeline: dict) -> float:
    """The scene's length: up to its last hold (`end`), its last frame or cursor move, plus the tail."""
    times = [f["t"] for f in timeline["frames"]] + [k["t"] for k in timeline["cursor"]] + [timeline.get("end", 0.0)]
    return round(max(times) + TAIL, 3)


def frame_count(timeline: dict, fps: int) -> int:
    """Frames of the encoded video: the scene's length rounded up to a whole frame, so the last hold is never cut.
    The video lasts ``frame_count / fps`` seconds; the manifest and the last caption use that, not the timeline's end."""
    return math.ceil(duration_of(timeline) * fps - 1e-6)


def loop_frames(span: tuple[float, float], fps: int, loop_fps: int = 10) -> tuple[list[int], int]:
    """The video frames the short loop shows and how long each stays, in ms: about `loop_fps` a second, and never
    more than LOOP_MAX seconds in all, whatever the frame rate."""
    step = max(1, round(fps / loop_fps))
    frame_ms = round(1000 * step / fps)
    indices = list(range(round(span[0] * fps), round(span[1] * fps), step))
    return indices[: int(LOOP_MAX * 1000) // frame_ms], frame_ms


def webp_animation(data: bytes) -> tuple[int, int]:
    """(loop count, total ms) of an animated WebP, read from the file's ANIM and ANMF chunks. A loop count of 0 means
    forever; 1 means it plays once and stops."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP")
    loops, total, at = None, 0, 12
    while at + 8 <= len(data):
        kind, size = data[at : at + 4], int.from_bytes(data[at + 4 : at + 8], "little")
        if kind == b"ANIM":
            loops = int.from_bytes(data[at + 12 : at + 14], "little")
        elif kind == b"ANMF":
            total += int.from_bytes(data[at + 20 : at + 23], "little")
        at += 8 + size + (size & 1)
    if loops is None:
        raise ValueError("not an animated WebP")
    return loops, total


def fast_cues(captions: list[dict], end: float, cps: float = CAPTION_CPS) -> list[str]:
    """The captions that leave the screen too soon to be read: more than `cps` characters a second."""
    fast = []
    for i, cue in enumerate(captions):
        shown = (captions[i + 1]["t"] if i + 1 < len(captions) else end) - cue["t"]
        if shown <= 0 or len(cue["text"]) / shown > cps:
            fast.append(f"{len(cue['text'])} characters in {shown:.2f} s: {cue['text']}")
    return fast


FRAME_NAME = re.compile(r"\d{4}\.png")


def check_timeline(timeline: dict) -> None:
    """A timeline is the capture's output, read on the host: its scene and language name the files compose writes
    and its frame names are opened, so they must be the ones this script itself writes."""
    if timeline.get("schema") != 1:
        raise ValueError(f"unknown timeline schema {timeline.get('schema')!r}")
    if timeline.get("scene") not in SCENES or timeline.get("locale") not in LOCALES:
        raise ValueError(f"unknown scene or language: {timeline.get('scene')!r}, {timeline.get('locale')!r}")
    names = [f["file"] for f in timeline["frames"]] + [timeline["poster"]]
    if not timeline["frames"] or not all(isinstance(n, str) and FRAME_NAME.fullmatch(n) for n in names):
        raise ValueError("frame names must be NNNN.png")


def personal_values(text: str, seen: list[str], home: str, user: str, host: str) -> list[str]:
    """Values of this machine that a manifest must not hold. The home directory is looked for in the whole manifest
    (`text`); the user and host names are short words that the manifest's own fixed text can contain (`en` in
    `en-US`, `fedora` in the container's name), so they are looked for as whole words, and only in `seen`: what the
    capture read from the screen. A host with no name of its own (`localhost`) is not a personal value."""
    found = [home] if home and home != "/" and home in text else []
    for name in (user, host):
        if not name or name in ("localhost", "localhost.localdomain"):
            continue
        word = re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])")
        if any(word.search(s) for s in seen):
            found.append(name)
    return found


def vtt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def webvtt(captions: list[dict], end: float) -> str:
    """WebVTT for the scene's captions: each one lasts until the next starts, the last until the end."""
    lines = ["WEBVTT", ""]
    for i, cue in enumerate(captions):
        stop = captions[i + 1]["t"] if i + 1 < len(captions) else end
        lines += [str(i + 1), f"{vtt_time(cue['t'])} --> {vtt_time(stop)}", cue["text"].replace("-->", "→"), ""]
    return "\n".join(lines)


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


# -- capture: the recorder -----------------------------------------------------------------------


class Recorder:
    """Frames of one scene on a video clock. Frames are taken from whichever window is on screen."""

    def __init__(self, out: Path, scene: str, locale: str):
        self.dir = out / f"{scene}-{locale}"
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.scene, self.locale = scene, locale
        self.t = 0.0
        self.frames: list[dict] = []
        self.keys: list[dict] = []
        self.clicks: list[dict] = []
        self.captions: list[dict] = []
        self.cuts: list[dict] = []
        self.xy: tuple[float, float] | None = None
        self.size: tuple[int, int] | None = None
        self.scale: float | None = None
        self.poster: str | None = None
        self.highlight_t: float | None = None
        self.notes: list[str] = []

    def shot(self, m, poster: bool = False) -> str:
        m.set_context("chrome")
        try:
            m.execute("document.documentElement.removeAttribute('remotecontrol');")
            data = base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"])
            inner = m.execute("return innerWidth;")
        finally:
            m.set_context("content")
        size = png_size(data)
        if self.size is None:
            self.size = size
        elif size != self.size:
            raise RuntimeError(f"frame size changed from {self.size} to {size}: the windows must have one size")
        self.scale = size[0] / inner
        name = f"{len(self.frames):04d}.png"
        (self.dir / name).write_bytes(data)
        self.frames.append({"t": round(self.t, 3), "file": name})
        if poster:
            self.poster = name
        return name

    def hold(self, seconds: float) -> None:
        self.t += seconds

    def watch(self, m, seconds: float, until=None, after: float = 0.6) -> None:
        """Frames at the real pace for `seconds`, or until `until()` holds and `after` more seconds have passed."""
        start, t0, met = time.monotonic(), self.t, None
        while True:
            self.t = t0 + (time.monotonic() - start)
            self.shot(m)
            now = time.monotonic() - start
            if until is not None and met is None and until():
                met = now
            if (met is not None and now - met >= after) or now >= seconds:
                break
        self.t = t0 + (time.monotonic() - start)
        if until is not None and met is None:
            raise RuntimeError(f"{self.scene}: the state the scene waits for did not come in {seconds} s")

    def move(self, xy: tuple[float, float], seconds: float = MOVE) -> None:
        start = self.xy or (xy[0] - 160 * (self.scale or 1), xy[1] + 90 * (self.scale or 1))
        self.keys.append({"t": round(self.t, 3), "xy": list(start)})
        self.t += seconds
        self.keys.append({"t": round(self.t, 3), "xy": list(xy)})
        self.xy = xy

    def hide_cursor(self) -> None:
        self.keys.append({"t": round(self.t, 3), "xy": None})
        self.xy = None

    def click(self) -> None:
        self.clicks.append({"t": round(self.t, 3), "xy": list(self.xy)})
        self.t += 0.12

    def highlight(self) -> None:
        """Where the short loop starts: the 5 s that tell the scene."""
        self.highlight_t = round(self.t, 3)

    def caption(self, text: str) -> None:
        self.captions.append({"t": round(self.t, 3), "text": text})

    def cut(self, to: str, waited: float) -> None:
        """A cut to another window; `waited` is the real time that was not recorded."""
        self.hide_cursor()
        self.cuts.append({"t": round(self.t, 3), "to": to, "real_seconds_cut": round(waited, 1)})

    def save(self, transcript: str, meta: dict) -> None:
        fast = fast_cues(self.captions, self.t + TAIL)
        if fast:
            raise RuntimeError(f"{self.scene}: captions shown too briefly to read ({CAPTION_CPS} characters a second): {fast}")
        timeline = {
            "schema": 1,
            "scene": self.scene,
            "locale": self.locale,
            "size": list(self.size),
            "scale": round(self.scale, 3),
            "end": round(self.t, 3),
            "frames": self.frames,
            "cursor": self.keys,
            "clicks": self.clicks,
            "captions": self.captions,
            "cuts": self.cuts,
            "poster": self.poster or self.frames[-1]["file"],
            "highlight": self.highlight_t,
            "transcript": transcript,
            "notes": self.notes,
            **meta,
        }
        (self.dir / "timeline.json").write_text(json.dumps(timeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# -- capture: fixtures, sessions, windows --------------------------------------------------------

# The fixture pages, as text: `/path | site | title | lead` starts a page; `## heading` starts a block, whose lines are
# `- item` (a list) or `cell | cell` (a table, its first row the header). Everyday content with areas instead of
# people, and no third-party name, address, contact or account number.
PAGES = {
    "pt-BR": """
/receitas | Caderno de receitas | Receitas da semana | Sopa de abóbora, arroz de forno e salada de grão-de-bico.
## Cardápio
Dia | Almoço | Jantar
Segunda | Arroz de forno com legumes | Sopa de abóbora
Terça | Salada de grão-de-bico | Omelete de ervas
Quarta | Macarrão ao molho de tomate | Sopa de abóbora
Quinta | Feijão, arroz e couve | Torta de legumes
Sexta | Peixe assado com batatas | Pizza caseira
## Lista de compras
- Abóbora, cenoura e cebola
- Grão-de-bico e arroz
- Tomate, ervas frescas e limão
- Ovos, queijo e farinha

/viagem | Planos | Roteiro de viagem | Três dias na serra: trilha no sábado, feira no domingo.
## Programação
Dia | Manhã | Tarde
Sexta | Estrada e chegada | Passeio pelo centro
Sábado | Trilha da cachoeira | Descanso e leitura
Domingo | Feira de produtores | Volta para casa
## O que levar
- Casaco e bota de trilha
- Garrafa de água e lanche
- Protetor solar e chapéu

/intranet | Intranet | Intranet da equipe | Pauta da reunião de segunda e as entregas do mês.
## Reunião de segunda, 10h
- Revisão das entregas da semana passada
- Prioridades do suporte
- Novo fluxo de aprovação de compras
- Férias e escala de plantão
## Entregas do mês
Entrega | Área | Prazo | Situação
Relatório trimestral | Financeiro | dia 12 | Em revisão
Novo manual de atendimento | Suporte | dia 18 | Em andamento
Inventário de equipamentos | Operações | dia 25 | A iniciar
Pesquisa de satisfação | Atendimento | dia 29 | Em andamento

/chamados | Suporte | Chamados abertos | Quatro pedidos de suporte aguardam resposta.
## Aguardando resposta
Nº | Assunto | Área | Aberto há | Prioridade
1042 | Impressora do 2º andar não imprime | Infraestrutura | 2 horas | Alta
1041 | Acesso à pasta de contratos | Acessos | 5 horas | Média
1039 | Troca de monitor | Equipamentos | 1 dia | Baixa
1036 | Lentidão na planilha de estoque | Sistemas | 2 dias | Média
## Resolvidos esta semana
- 1035 · Senha da rede de visitantes atualizada
- 1033 · Novo notebook configurado para o financeiro
- 1030 · Agenda compartilhada da sala de reunião

/extrato | Minha conta | Extrato do mês | Contas da casa, a escola e a reserva para a viagem.
## Lançamentos
Dia | Descrição | Valor
02 | Aluguel | − R$ 1.850,00
05 | Salário | + R$ 6.200,00
08 | Conta de luz | − R$ 214,30
10 | Escola | − R$ 980,00
15 | Mercado | − R$ 642,75
20 | Internet | − R$ 119,90
28 | Reserva para a viagem | − R$ 500,00
## Resumo
- Entradas: R$ 6.200,00
- Saídas: R$ 4.306,95
- Saldo do mês: R$ 1.893,05
""",
    "en-US": """
/recipes | Recipe notebook | Recipes for the week | Pumpkin soup, baked rice and a chickpea salad.
## Menu
Day | Lunch | Dinner
Monday | Baked rice with vegetables | Pumpkin soup
Tuesday | Chickpea salad | Herb omelette
Wednesday | Pasta with tomato sauce | Pumpkin soup
Thursday | Beans, rice and greens | Vegetable pie
Friday | Baked fish with potatoes | Homemade pizza
## Shopping list
- Pumpkin, carrots and onions
- Chickpeas and rice
- Tomatoes, fresh herbs and lemons
- Eggs, cheese and flour

/trip | Plans | Trip plan | Three days in the hills: a hike on Saturday, the market on Sunday.
## Schedule
Day | Morning | Afternoon
Friday | The drive up | A walk around the centre
Saturday | The waterfall trail | Rest and reading
Sunday | The farmers' market | The drive home
## What to pack
- A coat and hiking boots
- A water bottle and snacks
- Sunscreen and a hat

/intranet | Intranet | Team intranet | Monday's meeting agenda and this month's deliveries.
## Monday's meeting, 10 am
- Review of last week's deliveries
- Support priorities
- The new purchase approval flow
- Holidays and the on-call rota
## This month's deliveries
Delivery | Area | Due | Status
Quarterly report | Finance | the 12th | In review
New service handbook | Support | the 18th | In progress
Equipment inventory | Operations | the 25th | Not started
Satisfaction survey | Customer care | the 29th | In progress

/tickets | Support | Open tickets | Four support requests are waiting for an answer.
## Waiting for an answer
No. | Subject | Area | Open for | Priority
1042 | The 2nd floor printer does not print | Infrastructure | 2 hours | High
1041 | Access to the contracts folder | Access | 5 hours | Medium
1039 | Monitor replacement | Equipment | 1 day | Low
1036 | The stock spreadsheet is slow | Systems | 2 days | Medium
## Solved this week
- 1035 · Guest network password updated
- 1033 · New laptop set up for finance
- 1030 · Shared calendar for the meeting room

/statement | My account | This month's statement | Household bills, school fees and the savings for the trip.
## Entries
Day | Description | Amount
02 | Rent | − $1,850.00
05 | Salary | + $6,200.00
08 | Electricity | − $214.30
10 | School fees | − $980.00
15 | Groceries | − $642.75
20 | Internet | − $119.90
28 | Savings for the trip | − $500.00
## Summary
- In: $6,200.00
- Out: $4,306.95
- Balance for the month: $1,893.05
""",
}


def parse_pages(source: str) -> dict[str, tuple]:
    """The pages of one language: path -> (site, title, lead, [(heading, rows)]), a row a string (a list's item) or a
    tuple of cells (a table's row)."""
    pages: dict[str, tuple] = {}
    blocks: list = []
    for line in filter(None, (raw.strip() for raw in source.splitlines())):
        if line.startswith("/"):
            path, site, title, lead = line.split(" | ")
            blocks = []
            pages[path] = (site, title, lead, blocks)
        elif line.startswith("## "):
            blocks.append((line[3:], []))
        elif line.startswith("- "):
            blocks[-1][1].append(line[2:])
        else:
            blocks[-1][1].append(tuple(line.split(" | ")))
    return pages


TEXT = {
    "pt-BR": {
        "lang": "pt_BR.UTF-8",
        "first": "Pessoal",
        "work": "Trabalho",
        "bank": "Bancos",
        "engine": "Busca local de teste",
        "pages": parse_pages(PAGES["pt-BR"]),
        "cap": {
            "profile-opens": [
                "Em Configurações › Perfis, cada parte da vida tem o seu perfil.",
                "«{work}» abre numa janela só dele, com cor e nome próprios.",
                "Histórico, logins e cookies do «{work}» ficam separados dos do «{first}».",
            ],
            "link-routed": [
                "Uma regra manda a intranet do trabalho para o «{work}».",
                "No perfil «{first}», digita-se o endereço dela.",
                "O link abre na janela do «{work}», e a faixa diz que foi a sua regra.",
            ],
            "protected-unlocks": [
                "O perfil «{bank}» é protegido: os seus dados ficam cifrados no disco.",
                "Para abri-lo, a senha do perfil.",
                "Desbloqueado, ele abre na sua própria janela.",
            ],
        },
    },
    "en-US": {
        "lang": "en_US.UTF-8",
        "first": "Personal",
        "work": "Work",
        "bank": "Banking",
        "engine": "Local test search",
        "pages": parse_pages(PAGES["en-US"]),
        "cap": {
            "profile-opens": [
                "In Settings › Profiles, each part of life has a profile of its own.",
                "“{work}” opens in its own window, with its own colour and name.",
                "“{work}” keeps its history, logins and cookies apart from “{first}”.",
            ],
            "link-routed": [
                "A rule sends the work intranet to the “{work}” profile.",
                "In the “{first}” profile, its address is typed.",
                "The link opens in the “{work}” window, and the band says the rule did it.",
            ],
            "protected-unlocks": [
                "The “{bank}” profile is protected: its data is encrypted on disk.",
                "To open it, the profile's password.",
                "Once unlocked, it opens in a window of its own.",
            ],
        },
    },
}
PERSONAL_PAGES = {"pt-BR": ["/receitas", "/viagem"], "en-US": ["/recipes", "/trip"]}
WORK_PAGES = {"pt-BR": ["/chamados"], "en-US": ["/tickets"]}
BANK_PAGES = {"pt-BR": ["/extrato"], "en-US": ["/statement"]}
# A new window's own first page (the new tab) names the profile's search engine with no alternatives beside it; the
# scenes never show a third-party service that way (#173), so a window that opens gets a fixture page first.
NEW_WINDOW_NOTE = "the new window's tab was opened by the script before its first frame (its new tab page names a search engine)"
PASSWORD = "artificial pass 173"  # noqa: S105 -- a throwaway volume in a throwaway home
SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const V = ChromeUtils.importESModule("{SHELL}/NulavioVault.sys.mjs").NulavioVault;'
    f'const L = ChromeUtils.importESModule("{SHELL}/NulavioLayout.sys.mjs").NulavioLayout;'
    f'const S = ChromeUtils.importESModule("{SHELL}/NulavioSearch.sys.mjs").NulavioSearch;'
    'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
    ".SelectableProfileService;"
)
BAND = (
    "const row = document.querySelector('#nulavio-band .nv-band-row'); if (!row) return null;"
    "const shown = e => e && !e.hidden && e.checkVisibility() && e.getBoundingClientRect().width > 0;"
    "const out = [];"
    "for (const e of row.querySelectorAll('button, .nv-band-seal, .nv-band-header')) {"
    " if (!shown(e) || out.some(o => o.contains(e))) continue; out.push(e); }"
    "return out.map(e => e.textContent.trim().replace(/\\s+/g, ' ')).filter(Boolean);"
)


def chrome_async(m, body: str, *args):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        f"(async () => {{ {PRELUDE} {body} }})().then(v => done({{ok: v ?? null}}), e => done({{error: e?.code ?? String(e)}}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["ok"]


def fixture_page(locale: str, path: str) -> bytes | None:
    page = TEXT[locale]["pages"].get(path)
    if page is None:
        return None
    e = html.escape
    site, title, lead, blocks = page
    line = "color-mix(in srgb,CanvasText 14%,Canvas)"
    css = (
        ":root{color-scheme:light dark;font-family:'Noto Sans',Cantarell,system-ui,sans-serif}"
        "body{margin:0;line-height:1.5;background:Canvas;color:CanvasText}"
        f"header{{padding:.7rem 2rem;font-weight:600;border-bottom:1px solid {line};"
        "background:color-mix(in srgb,CanvasText 4%,Canvas)}"
        "main{max-width:46rem;margin:2rem auto;padding:0 2rem}"
        "h1{font-size:1.75rem;margin:0 0 .25rem}h2{font-size:1.05rem;margin:1.75rem 0 .5rem}"
        "p{margin:0;color:color-mix(in srgb,CanvasText 72%,Canvas)}"
        "table{width:100%;border-collapse:collapse;font-size:.95rem}"
        f"th,td{{text-align:left;padding:.5rem .75rem;border-bottom:1px solid {line}}}"
        "th{font-size:.8rem;color:color-mix(in srgb,CanvasText 72%,Canvas)}"
        "ul{margin:0;padding-left:1.25rem}li{margin:.3rem 0}"
    )
    body = []
    for heading, rows in blocks:
        body.append(f"<h2>{e(heading)}</h2>")
        if isinstance(rows[0], str):  # a list
            body.append("<ul>" + "".join(f"<li>{e(item)}</li>" for item in rows) + "</ul>")
        else:  # a table, its first row the header
            head = "".join(f"<th>{e(cell)}</th>" for cell in rows[0])
            rest = "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in rows[1:])
            body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rest}</tbody></table>")
    return (
        f'<!doctype html><html lang="{locale}"><meta charset=utf-8><title>{e(title)}</title><style>{css}</style>'
        f"<header>{e(site)}</header><main><h1>{e(title)}</h1><p>{e(lead)}</p>{''.join(body)}</main>"
    ).encode()


class Fixtures:
    """Sample pages with original text on loopback: everyday content (a menu, a trip, a team's deliveries, support
    tickets, a month's entries) with areas instead of people and no third-party name, address, contact or account
    number; no favicon, nothing loaded from anywhere. Counts requests."""

    def __init__(self, locale: str):
        outer, self.hits = self, []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.partition("?")[0]
                outer.hits.append(path)
                body = fixture_page(locale, path)
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def recording_prefs(locale: str) -> dict:
    return {
        "layout.css.devPixelsPerPx": str(SCALE),
        "intl.locale.requested": locale,
        "ui.systemUsesDarkTheme": 0,
        "browser.sessionstore.resume_from_crash": False,
    }


def add_prefs(harness, profile_dir: Path, prefs: dict) -> None:
    lines = [f'user_pref("{k}", {harness.Session._js(v)});' for k, v in prefs.items()]
    with open(Path(profile_dir) / "user.js", "a", encoding="utf-8") as handle:
        handle.write("// record_site.py overlay (disposable profile only)\n" + "\n".join(lines) + "\n")


def prepare_profile(harness, path: Path, locale: str) -> None:
    """Marionette and the recording prefs in a profile the browser itself will start."""
    harness.GeckoProfileSession.enable_marionette(path)
    add_prefs(harness, path, recording_prefs(locale))


def window_ready(m, pages: list[str]) -> None:
    """One window at the recording size, Lateral, no bars, showing `pages` (the first selected)."""
    m.set_context("chrome")
    try:
        m.send("WebDriver:SetWindowRect", {"width": WINDOW_CSS[0], "height": WINDOW_CSS[1]})
    finally:
        m.set_context("content")
    chrome_async(m, "return await L.apply(window, 'lateral');")
    m.chrome("SidebarController.hide?.(); gNotificationBox.removeAllNotifications?.(true);")
    if pages:
        chrome_async(
            m,
            """
          const old = [...gBrowser.tabs];
          const tabs = args[0].map(u => gBrowser.addTrustedTab(u));
          gBrowser.selectedTab = tabs[0];
          for (const t of old) gBrowser.removeTab(t);
          await Promise.all(tabs.map(t => new Promise(resolve => {
            const check = () => (t.linkedBrowser.currentURI.spec.startsWith('http') && !t.hasAttribute('busy'))
              ? resolve() : setTimeout(check, 100);
            check();
          })));
          gBrowser.selectedBrowser.focus();
          gURLBar.blur();
        """,
            pages,
        )
    time.sleep(1.0)
    follow_selected_tab(m)


def follow_selected_tab(m) -> None:
    """Point the driver's content context at the window's selected tab (tabs were replaced under it)."""
    want = m.chrome("return gBrowser.selectedBrowser.currentURI.spec;")
    for handle in m.window_handles():
        m.switch_to(handle)
        try:
            if m.current_url() == want:
                return
        except Exception:  # noqa: S112 -- a tab that is going away
            continue
    raise RuntimeError(f"no driver handle for the selected tab {want}")


def band(m) -> list[str]:
    return m.chrome(BAND) or []


def chrome_point(m, element_js: str) -> tuple[float, float]:
    """Centre of a chrome element, in the frame's device pixels."""
    r = m.chrome(f"const e = {element_js}; const r = e.getBoundingClientRect();"
                 "return [r.x + r.width / 2, r.y + r.height / 2, devicePixelRatio];")  # fmt: skip
    return (r[0] * r[2], r[1] * r[2])


PREFS_DOC = "const d = gBrowser.selectedBrowser.contentDocument;"


def prefs_point(m, element_js: str) -> tuple[float, float]:
    """Centre of an element of the Settings page (a parent-process page, read through the chrome), in device pixels."""
    r = m.chrome(PREFS_DOC + f"const e = {element_js};"
                 "const r = e.getBoundingClientRect(); const o = gBrowser.selectedBrowser.getBoundingClientRect();"
                 "return [o.x + r.x + r.width / 2, o.y + r.y + r.height / 2, devicePixelRatio];")  # fmt: skip
    return (r[0] * r[2], r[1] * r[2])


def content_point(m, element_js: str) -> tuple[float, float]:
    """Centre of an element of the selected tab's page, in the frame's device pixels."""
    inner = m.execute(f"const e = {element_js}; e.scrollIntoView({{block: 'center'}}); const r = e.getBoundingClientRect();"
                      "return [r.x + r.width / 2, r.y + r.height / 2];")  # fmt: skip
    outer = m.chrome("const r = gBrowser.selectedBrowser.getBoundingClientRect(); return [r.x, r.y, devicePixelRatio];")
    return ((outer[0] + inner[0]) * outer[2], (outer[1] + inner[1]) * outer[2])


def type_into_urlbar(rec: Recorder, m, text: str) -> None:
    """Trusted keys into the address bar (nsITextInputProcessor, as Firefox's own tests type), a frame per key."""
    m.chrome("gURLBar.focus(); gURLBar.select();")
    key = (
        "const tip = Cc['@mozilla.org/text-input-processor;1'].createInstance(Ci.nsITextInputProcessor);"
        "if (!tip.beginInputTransactionForTests(window)) throw new Error('no input transaction');"
        "const ch = arguments[0];"
        "const e = ch === '\\n' ? new KeyboardEvent('', {key: 'Enter', code: 'Enter', keyCode: 13})"
        " : new KeyboardEvent('', {key: ch});"
        "tip.keydown(e); tip.keyup(e);"
    )
    for ch in text:
        m.chrome(key, [ch])
        rec.shot(m)
        rec.hold(TYPE_STEP)
    m.chrome(key, ["\n"])


def local_search_engine(m, locale: str, fx: Fixtures) -> None:
    """The profile's search engine set to a local test engine on loopback. The address bar shows the default engine's
    icon and offers to search with it while an address is typed; with a real provider that would show one third-party
    service alone (#173), so the scene uses a fixture engine, as test_search does."""
    name = TEXT[locale]["engine"]
    added = chrome_async(m, "return S.addCustom({name: args[0], url: args[1]});", name, fx.url("/search?q=%s"))
    chrome_async(m, "await S.setDefault(args[0]);", added)


def type_into_field(rec: Recorder, m, element: str, text: str) -> None:
    """Real keys into a page's field (WebDriver:ElementSendKeys), one at a time, a frame per key."""
    for ch in text:
        m.send("WebDriver:ElementSendKeys", {"id": element, "text": ch})
        rec.shot(m)
        rec.hold(TYPE_STEP)


def build_info(engine_path: Path) -> dict:
    ini = configparser.ConfigParser()
    ini.read(engine_path.parent / "application.ini")
    return {"buildid": ini["App"]["BuildID"], "firefox": ini["App"]["Version"]}


def wait(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise RuntimeError(f"timed out: {what}")


# -- capture: scenes -----------------------------------------------------------------------------


class Scenes:
    """The scenes, each on its own throwaway session. `harness` is tests/lib/harness (passed in, so this file imports
    nothing of the engine's side when compose runs on the host)."""

    def __init__(self, harness, out: Path):
        self.h = harness
        self.out = out
        if out.exists():  # before anything can fail: an earlier run's timelines are never composed with this run's
            shutil.rmtree(out)
        out.mkdir(parents=True)
        engine = harness.nulavio_engine()
        if engine is None:
            raise RuntimeError("recording needs the Nulavio build (NULAVIO_ENGINE)")
        # What the capture knows about its own source: the engine's build and this script, as git names the file
        # (`git log --find-object=<id>` finds the commits that have it). The tree is copied into the container without
        # git's data, so no commit is claimed here; compose records the checkout that composed, under that name.
        script = Path(__file__).read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(script) + script, usedforsecurity=False).hexdigest()
        self.meta = {
            **build_info(Path(engine.path)),
            "script": "scripts/site/record_site.py",
            "script_blob": blob,
            "dom_changes": DOM_CHANGES,
        }

    def session(self, locale: str):
        h = self.h
        prefs = recording_prefs(locale)

        class RecordingSession(h.GeckoProfileSession):
            def enable_marionette(self, profile_dir: Path) -> None:  # called by start() for the first profile
                h.GeckoProfileSession.enable_marionette(profile_dir)
                add_prefs(h, profile_dir, prefs)

        s = RecordingSession(name=TEXT[locale]["first"])
        s.env["LANG"] = TEXT[locale]["lang"]
        return s

    def connect(self, s, path: Path):
        wait(lambda: s.processes_for(path), 90, f"an instance of {path.name}")
        return self.h.GeckoProfileSession.connect(path, timeout=90)

    def record(self, scene: str, locale: str) -> Path:
        rec = Recorder(self.out, scene, locale)  # first: if it cannot write, nothing has been started yet
        fixtures = Fixtures(locale)
        s, others = None, []
        try:
            s = self.session(locale)
            transcript = getattr(self, scene.replace("-", "_"))(rec, s, fixtures, locale, others)
            now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec.save(transcript, {**self.meta, "captured": now, "window_css": list(WINDOW_CSS)})
            return rec.dir
        finally:
            for client in others:
                try:
                    client.quit()
                except Exception:  # noqa: S110 -- the session's cleanup ends what is left
                    pass
            if s is not None:
                for vault in s.tmp.rglob("*.vault"):
                    # Lazily, as the Vault's tests detach a throwaway volume: an instance that never connected can
                    # still hold the mount busy, and cleanup() ends it only afterwards.
                    mountpoint = vault.with_name(vault.name[: -len(".vault")])
                    subprocess.run(["fusermount3", "-u", "-z", str(mountpoint)], capture_output=True, check=False)
                for dirpath, _d, _f in os.walk(s.tmp):
                    os.chmod(dirpath, 0o700)
                s.cleanup()
            fixtures.close()

    def caps(self, locale: str, scene: str) -> list[str]:
        t = TEXT[locale]
        return [c.format(first=t["first"], work=t["work"], bank=t["bank"]) for c in t["cap"][scene]]

    def open_profiles_pane(self, m) -> None:
        """Settings at its Profiles pane in the selected tab, as Settings › Profiles shows it, scrolled so that the list
        of profiles ends at the bottom: the new profile's search choice below it names providers, and a crop of that
        list would show some of them and not the others (#173)."""
        m.navigate("about:preferences#nulavioProfiles")
        wait(
            lambda: m.chrome(PREFS_DOC + "return !!d?.querySelector('#nulavio-profile-list moz-box-item.nulavio-profile');"),
            30,
            "the profiles pane",
        )
        time.sleep(0.8)
        m.chrome(PREFS_DOC + "d.getElementById('nulavio-profile-new-template').scrollIntoView({block: 'end'});")
        time.sleep(0.3)

    @staticmethod
    def row_button(name: str, action: str) -> str:
        """The button of a profile's row in Settings › Profiles (an expression over `d`)."""
        return (
            "[...d.querySelectorAll('#nulavio-profile-list moz-box-item.nulavio-profile')]"
            f".find(r => r.label === {json.dumps(name)})?.querySelector(\"moz-button[data-action='{action}']\")"
        )

    def press(self, m, button: str) -> None:
        """A click on a Settings control, as tests/lib/settings_page drives them."""
        if not m.chrome(PREFS_DOC + f"const b = {button}; if (!b) return false; b.click(); return true;"):
            raise RuntimeError(f"no such control: {button}")

    def profile_opens(self, rec: Recorder, s, fx: Fixtures, locale: str, others: list) -> str:
        t, cap = TEXT[locale], self.caps(locale, "profile-opens")
        m = s.start()
        time.sleep(2)
        work = chrome_async(m, "return P.create({templateId: 'work', name: args[0]});", t["work"])
        path = Path(chrome_async(m, "return (await SPS.getProfile(args[0])).path;", work))
        prepare_profile(self.h, path, locale)
        window_ready(m, [fx.url(p) for p in PERSONAL_PAGES[locale]])
        self.open_profiles_pane(m)  # the selected tab becomes Settings
        row = self.row_button(t["work"], "open")
        button = prefs_point(m, row)  # scrolls the row into view before the first frame
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(1.8)
        rec.highlight()
        rec.move(button)
        rec.shot(m)
        rec.click()
        self.press(m, row)
        rec.watch(m, 1.2)
        started = time.monotonic()  # nothing is recorded from here to the cut
        child = self.connect(s, path)
        others.append(child)
        wait(lambda: t["work"] in " ".join(band(child)), 30, "the work profile's band")
        window_ready(child, [fx.url(p) for p in WORK_PAGES[locale]])
        rec.notes.append("the work profile was created by the script (NulavioProfiles.create, template work) before the scene")
        rec.notes.append(NEW_WINDOW_NOTE)
        rec.cut(t["work"], time.monotonic() - started)
        rec.caption(cap[1])
        rec.shot(child, poster=True)
        rec.hold(3.4)
        rec.caption(cap[2])
        rec.shot(child)
        rec.hold(3.4)
        cues = band(child)
        if locale == "pt-BR":
            return (f"Na tela: Configurações › Perfis, com «{t['first']}» e «{t['work']}»; clique em Abrir no «{t['work']}»;"
                    f" a janela do «{t['work']}» abre, com a faixa «{' · '.join(cues)}».")  # fmt: skip
        return (f"On screen: Settings › Profiles, with “{t['first']}” and “{t['work']}”; a click on Open for “{t['work']}”;"
                f" the “{t['work']}” window opens, its band reading “{' · '.join(cues)}”.")  # fmt: skip

    def link_routed(self, rec: Recorder, s, fx: Fixtures, locale: str, others: list) -> str:
        t, cap = TEXT[locale], self.caps(locale, "link-routed")
        m = s.start()
        time.sleep(2)
        work = chrome_async(m, "return P.create({templateId: 'work', name: args[0]});", t["work"])
        path = Path(chrome_async(m, "return (await SPS.getProfile(args[0])).path;", work))
        prepare_profile(self.h, path, locale)
        chrome_async(m, "return R.addRule({site: 'localhost', match: 'host', action: 'open-in', profileId: args[0]});", work)
        chrome_async(m, "return P.switchTo(args[0]);", work)  # the work profile is already open, as on a working day
        child = self.connect(s, path)
        others.append(child)
        wait(lambda: t["work"] in " ".join(band(child)), 30, "the work profile's band")
        window_ready(child, [fx.url(p) for p in WORK_PAGES[locale]])
        time.sleep(1.5)  # its profile service reads the group's rules
        window_ready(m, [fx.url(p) for p in PERSONAL_PAGES[locale]])
        local_search_engine(m, locale, fx)
        target = fx.url("/intranet", host="localhost")  # typed in full: a bare host:port is not always read as an address
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(2.2)  # the time to read the first caption comes before the highlight, so the short loop loses none
        rec.move(chrome_point(m, "gURLBar.inputField"))
        rec.click()
        rec.shot(m)
        rec.highlight()
        rec.caption(cap[1])
        type_into_urlbar(rec, m, target)
        rec.watch(m, 1.0)
        started = time.monotonic()  # nothing is recorded from here to the cut
        tabs = "return gBrowser.tabs.map(t => t.linkedBrowser.currentURI.spec);"
        wait(lambda: any(u.endswith("/intranet") for u in child.chrome(tabs)), 30, "the link in the work profile")
        if any(u.endswith("/intranet") for u in m.chrome(tabs)):
            raise RuntimeError("the link was loaded in the personal profile too")
        select = (
            "const t = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.endsWith('/intranet')); gBrowser.selectedTab = t;"
        )
        child.chrome(select)
        notice = (
            "const n = document.querySelector('#nulavio-band-widget .nv-band-route');"
            "return n && !n.hidden ? n.textContent.trim() : null;"
        )
        said = wait(lambda: child.chrome(notice), 15, "the band's note that the rule opened it")
        wait(lambda: not child.chrome("return gBrowser.selectedTab.hasAttribute('busy');"), 15, "the routed page loaded")
        time.sleep(0.8)  # the tab's own loading animation is over before the frame the poster is made from
        if fx.hits.count("/intranet") != 1:
            raise RuntimeError(f"the routed page was requested {fx.hits.count('/intranet')} times")
        rec.cut(t["work"], time.monotonic() - started)
        rec.caption(cap[2])
        rec.shot(child, poster=True)
        rec.hold(1.2)
        rec.move(chrome_point(child, "document.querySelector('#nulavio-band-widget .nv-band-route')"), 0.9)
        rec.shot(child)
        rec.hold(2.6)
        rec.notes.append("the work profile was created by the script (NulavioProfiles.create, template work) before the scene")
        rec.notes.append("the routing rule (localhost opens in the work profile) was added by the script before the scene")
        rec.notes.append("the personal profile's search engine was set by the script to a local test engine on loopback")
        rec.notes.append("the work profile was started by the script before the scene")
        if locale == "pt-BR":
            return (f"Na tela: no perfil «{t['first']}», o endereço «{target}» é digitado; ele abre na janela do"
                    f" «{t['work']}», cuja faixa diz «{said}».")  # fmt: skip
        return (f"On screen: in the “{t['first']}” profile, the address “{target}” is typed; it opens in the"
                f" “{t['work']}” window, whose band says “{said}”.")  # fmt: skip

    def protected_unlocks(self, rec: Recorder, s, fx: Fixtures, locale: str, others: list) -> str:
        t, cap = TEXT[locale], self.caps(locale, "protected-unlocks")
        m = s.start()
        time.sleep(2)
        caps = chrome_async(m, "return await V.capabilities();")
        if not (caps.get("storage") and caps.get("sodium")):
            raise RuntimeError(f"the Vault is not available here: {caps}")
        made = chrome_async(m, "return V.createProtected(args[0]);",
                            {"name": t["bank"], "templateId": "banking", "keyring": False, "password": PASSWORD})  # fmt: skip
        bank = made["id"]
        path = Path(chrome_async(m, "return (await SPS.getProfile(args[0])).path;", bank))
        # Its prefs (Marionette, the recording's scale and language) live inside the encrypted volume: written while it
        # is open, then it is locked again, so the scene starts from a locked profile, as a person finds it.
        locked = "return (await P.list()).profiles.find(p => p.id === args[0]).locked;"
        if chrome_async(m, locked, bank):
            chrome_async(m, f"const VM = ChromeUtils.importESModule('{SHELL}/NulavioVault.sys.mjs');"
                         "return VM.vaultHelper({op: 'unlock', path: args[0], method: 'password', secret: args[1]});",
                         str(path), PASSWORD)  # fmt: skip
        prepare_profile(self.h, path, locale)
        chrome_async(m, "return V.lock(args[0]);", bank)
        wait(lambda: chrome_async(m, locked, bank), 30, "the protected profile locked again")
        window_ready(m, [fx.url(p) for p in PERSONAL_PAGES[locale]])
        self.open_profiles_pane(m)
        row = self.row_button(t["bank"], "unlock")
        wait(lambda: m.chrome(PREFS_DOC + f"return !!({row});"), 20, "the Unlock button")
        button = prefs_point(m, row)  # scrolls the row into view before the first frame
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(2.2)
        rec.move(button)
        rec.shot(m)
        rec.click()
        before = set(m.window_handles())
        self.press(m, row)
        page = wait(lambda: set(m.window_handles()) - before, 20, "the unlock page's tab").pop()
        m.switch_to(page)
        wait(lambda: m.execute("return document.documentElement?.dataset.ready === 'true' && document.body.dataset.state;")
             == "idle", 30, "the unlock page")  # fmt: skip
        m.chrome("const t = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec.includes('vault/unlock.html'));"
                 "gBrowser.selectedTab = t;")  # fmt: skip
        rec.watch(m, 0.8)
        rec.caption(cap[1])
        field = m.find_element("#password")
        rec.move(content_point(m, "document.getElementById('password')"))
        rec.click()
        type_into_field(rec, m, field, PASSWORD)
        rec.highlight()
        rec.move(content_point(m, "document.querySelector('#password-form button[type=submit]')"), 0.6)
        rec.click()
        m.send("WebDriver:ElementClick", {"id": m.find_element("#password-form button[type=submit]")})
        # State and message in one read: the page closes its tab after success, and a second read could miss it.
        state = "return [document.body?.dataset.state ?? null, document.getElementById('status')?.textContent.trim() ?? ''];"
        seen = {}

        def unlocked() -> bool:
            try:
                now, message = m.execute(state)
            except Exception:  # the page closes its tab after success
                return True
            seen.setdefault(now, message)
            return now == "unlocked"

        rec.watch(m, 25, until=unlocked, after=0.8)
        started = time.monotonic()
        child = self.connect(s, path)
        others.append(child)
        wait(lambda: t["bank"] in " ".join(band(child)), 30, "the protected profile's band")
        window_ready(child, [fx.url(p) for p in BANK_PAGES[locale]])
        rec.notes.append(
            "the protected profile was created by the script (NulavioVault.createProtected, an artificial password), then"
            " unlocked and locked again once to write its recording prefs inside its volume"
        )
        rec.notes.append(NEW_WINDOW_NOTE)
        rec.cut(t["bank"], time.monotonic() - started)
        rec.caption(cap[2])
        rec.shot(child, poster=True)
        rec.hold(3.0)
        cues = band(child)
        said = seen.get("unlocked")  # quoted only if the page was read while it said so (it closes itself)
        if locale == "pt-BR":
            says = f" ela diz «{said}»;" if said else ""
            return (f"Na tela: Configurações › Perfis, com «{t['bank']}» bloqueado; clique em Desbloquear; a página de"
                    f" desbloqueio pede a senha, que é digitada;{says} a janela do «{t['bank']}» abre, com a"
                    f" faixa «{' · '.join(cues)}».")  # fmt: skip
        says = f" it says “{said}”;" if said else ""
        return (f"On screen: Settings › Profiles, with “{t['bank']}” locked; a click on Unlock; the unlock page asks for the"
                f" password, which is typed;{says} the “{t['bank']}” window opens, its band reading"
                f" “{' · '.join(cues)}”.")  # fmt: skip


# -- compose (host) ------------------------------------------------------------------------------


def draw_cursor(draw, xy: tuple[float, float], scale: float) -> None:
    """An arrow pointer drawn here (no third-party art): white with a dark edge, its tip at xy."""
    x, y = xy
    shape = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.5), (9.6, 18.4), (6.9, 12.2), (12.4, 12.2)]
    points = [(x + px * scale, y + py * scale) for px, py in shape]
    draw.polygon(points, fill=(255, 255, 255, 255), outline=(17, 24, 39, 255), width=max(1, round(1.4 * scale)))


def draw_ripple(draw, x: float, y: float, u: float, scale: float) -> None:
    radius = (6 + 18 * u) * scale
    alpha = round(150 * (1 - u))
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius), outline=(13, 148, 136, alpha), width=max(2, round(2.5 * scale))
    )


def compose_frames(src: Path, timeline: dict, work: Path, width: int, fps: int) -> tuple[int, int, int]:
    from PIL import Image, ImageDraw

    count = frame_count(timeline, fps)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    w0, h0 = timeline["size"]
    size = (width, round(h0 * width / w0 / 2) * 2)
    scale = timeline["scale"]
    cache: dict[str, Image.Image] = {}
    for i in range(count):
        t = i / fps
        name = frame_at(timeline["frames"], t)
        if name not in cache:
            cache.clear()
            cache[name] = Image.open(src / name).convert("RGBA")
        frame = cache[name].copy()
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x, y, u in ripples_at(timeline["clicks"], t):
            draw_ripple(draw, x, y, u, scale)
        xy = cursor_at(timeline["cursor"], t)
        if xy is not None:
            draw_cursor(draw, xy, scale)
        frame = Image.alpha_composite(frame, overlay).convert("RGB").resize(size, Image.Resampling.LANCZOS)
        frame.save(work / f"{i:05d}.png", compress_level=1)
    return size[0], size[1], count


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def encode(work: Path, fps: int, out_base: Path) -> list[Path]:
    """Muted video: no audio track at all, no metadata, the same frames in VP9 WebM and H.264 MP4."""
    frames = ["-framerate", str(fps), "-i", str(work / "%05d.png")]
    common = ["-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1", "-pix_fmt", "yuv420p", "-fflags", "+bitexact"]
    webm, mp4 = out_base.with_suffix(".webm"), out_base.with_suffix(".mp4")
    ffmpeg(*frames, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-row-mt", "1", "-deadline", "good",
           "-cpu-used", "2", "-g", str(fps * 4), *common, str(webm))  # fmt: skip
    ffmpeg(*frames, "-c:v", "libopenh264", "-b:v", "700k", "-maxrate", "1200k", "-g", str(fps * 4), *common,
           "-movflags", "+faststart", str(mp4))  # fmt: skip
    return [webm, mp4]


def loop_window(timeline: dict, end: float) -> tuple[float, float]:
    """The part of the scene the short loop shows: from its highlight, at most LOOP_MAX seconds."""
    start = timeline.get("highlight")
    if start is None:
        start = max(0.0, end - LOOP_MAX)
    return start, min(end, start + LOOP_MAX)


def loop_webp(work: Path, span: tuple[float, float], fps: int, out: Path, width: int, loop_fps: int = 10) -> Path:
    """The short loop for <picture> (reduced motion gets the poster instead): animated WebP at a lower rate and size,
    played once (loop=1), so it stops by itself within LOOP_MAX seconds."""
    from PIL import Image

    indices, frame_ms = loop_frames(span, fps, loop_fps)
    images = []
    for i in indices:
        image = Image.open(work / f"{i:05d}.png")
        images.append(image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS))
    images[0].save(out, "WEBP", save_all=True, append_images=images[1:], duration=frame_ms, loop=1,
                   quality=60, method=6, minimize_size=True)  # fmt: skip
    return out


def poster_webp(src: Path, name: str, out: Path, width: int) -> Path:
    from PIL import Image

    image = Image.open(src / name).convert("RGB")
    image = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
    image.save(out, "WEBP", quality=82, method=6)
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def describe(path: Path) -> dict:
    data = path.read_bytes()
    return {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def compose(frames_root: Path, out: Path, width: int, loop_width: int, fps: int, budget: int) -> int:
    """Every scene under `frames_root`, made in a private temporary directory and copied to `out` only when all of
    them encoded and every check passed (sizes, the loop's length read from its file, captions that can be read, no
    personal value), the manifest last. A failed run leaves `out` as it was. Recordings of `out` that this run does
    not make stay in its manifest; the size budget is checked for them too."""
    timelines = sorted(frames_root.glob("*/timeline.json"))
    if not timelines:
        print(f"compose: no <scene>-<language>/timeline.json under {frames_root}: pass the recordings/ directory the"
              " capture wrote", file=sys.stderr)  # fmt: skip
        return 2
    if not shutil.which("ffmpeg"):
        print("compose needs ffmpeg (Fedora: ffmpeg-free)", file=sys.stderr)
        return 2
    manifest_path = out / "manifest.json"
    # Only the recordings are carried over from a manifest that is already there; the rest is written anew.
    recordings = json.loads(manifest_path.read_text(encoding="utf-8"))["recordings"] if manifest_path.exists() else {}
    composed = {
        "utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git("rev-parse", "--short=7", "HEAD"),
        "worktree_clean": not git("status", "--porcelain"),
    }
    problems = []
    with tempfile.TemporaryDirectory(prefix="nulavio-compose-") as tmp:
        stage, work = Path(tmp) / "out", Path(tmp) / "frames"
        stage.mkdir()
        for timeline_path in timelines:
            src = timeline_path.parent
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            check_timeline(timeline)
            key = f"{timeline['scene']}-{timeline['locale']}"
            base = stage / key
            w, h, count = compose_frames(src, timeline, work, width, fps)
            end = count / fps  # the encoded video's length
            files = encode(work, fps, base)
            span = loop_window(timeline, end)
            loop = loop_webp(work, span, fps, base.with_name(f"{key}-loop.webp"), loop_width)
            loops, loop_ms = webp_animation(loop.read_bytes())
            if loops != 1 or loop_ms > LOOP_MAX * 1000:
                problems.append(
                    f"{loop.name} plays {loops or 'endless'} time(s) for {loop_ms} ms: a loop plays once, {LOOP_MAX} s at most"
                )
            files.append(loop)
            files.append(poster_webp(src, timeline["poster"], base.with_name(f"{key}-poster.webp"), width))
            vtt = base.with_suffix(".vtt")
            vtt.write_text(webvtt(timeline["captions"], end), encoding="utf-8")
            files.append(vtt)
            problems += [
                f"{vtt.name}: more than {CAPTION_CPS} characters a second ({cue})" for cue in fast_cues(timeline["captions"], end)
            ]
            shutil.rmtree(work)
            described = [describe(f) for f in files]
            recordings[key] = {
                "scene": timeline["scene"],
                "locale": timeline["locale"],
                "duration_s": round(end, 3),
                "video_px": [w, h],
                "fps": fps,
                "captured_px": timeline["size"],
                "scale": timeline["scale"],
                "window_css": timeline["window_css"],
                "frames_captured": len(timeline["frames"]),
                "loop_s": [round(span[0], 3), round(span[1], 3)],
                "loop_ms": loop_ms,
                "cuts": timeline["cuts"],
                "transcript": timeline["transcript"],
                "captions": timeline["captions"],
                "notes": timeline["notes"],
                # The capture says when it ran, on which engine build and with which script (git's id of the file):
                # it runs on a copy of the tree without git's data, so it cannot name a commit. `composed` is the
                # checkout that drew and encoded these files, which may be a later one.
                "capture": {
                    "utc": timeline.get("captured"),
                    "buildid": timeline["buildid"],
                    "firefox": timeline["firefox"],
                    "script_blob": timeline.get("script_blob"),
                },
                "composed": composed,
                "files": described,
            }
            print(f"  {key}: {end:.1f} s, " + ", ".join(f"{d['file']} {d['bytes'] // 1024} KiB" for d in described), flush=True)
        manifest = {
            "schema": 1,
            "script": "scripts/site/record_site.py",
            "harness": "tests/lib/harness.GeckoProfileSession (throwaway HOME, headless), in ci/containers/fedora-release-itest",
            "dom_changes": DOM_CHANGES,
            "edits": EDITS,
            "encoders": {
                "webm": "libvpx-vp9 crf 36",
                "mp4": "libopenh264 700k",
                "loop": "Pillow WebP q60, 10 fps, at most 5 s, played once",
                "audio": "none",
            },
            "budget_bytes_per_file": budget,
            "recordings": dict(sorted(recordings.items())),
        }
        problems += [
            f"{f['file']} is {f['bytes']} bytes, over the budget of {budget}"
            for recording in manifest["recordings"].values()  # the ones kept from an earlier run too
            for f in recording["files"]
            if f["bytes"] > budget
        ]
        text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        seen = [recording["transcript"] for recording in manifest["recordings"].values()]
        private = personal_values(text, seen, str(Path.home()), os.environ.get("USER", ""), os.uname().nodename)
        problems += [f"the manifest would contain a personal value ({value!r})" for value in private]
        if problems:
            print("compose: nothing written to " + str(out) + ":\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        out.mkdir(parents=True, exist_ok=True)
        for staged in sorted(stage.iterdir()):
            shutil.copyfile(staged, out / staged.name)
        manifest_path.write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compose", help="cursor, encoding, captions and manifest from captured frames (host, no engine)")
    c.add_argument("frames", type=Path, help="the recordings/ directory the capture wrote")
    c.add_argument("--out", type=Path, default=OUT)
    c.add_argument("--width", type=int, default=1280, help="video width in pixels")
    c.add_argument("--loop-width", type=int, default=800, help="animated WebP width in pixels")
    c.add_argument("--fps", type=int, default=FPS)
    c.add_argument("--budget", type=int, default=2_000_000, help="largest file allowed, in bytes")
    args = parser.parse_args(argv)
    return compose(args.frames, args.out, args.width, args.loop_width, args.fps, args.budget)


if __name__ == "__main__":
    sys.exit(main())
