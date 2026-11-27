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
   captions and a manifest (hashes, build, commit, every edit). Needs Pillow and ffmpeg on the host
   (Fedora: python3-pillow, ffmpeg-free), the tools capture_site.py and the media fixtures already use.

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
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCENES = ("profile-opens", "link-routed", "protected-unlocks")
LOCALES = ("pt-BR", "en-US")
WINDOW_CSS = (1280, 800)
SCALE = 1.5
FPS = 30
TAIL = 1.2  # seconds the last frame stays before a loop starts again
CLICK_LENGTH = 0.45  # seconds a click's ripple lasts
TYPE_STEP = 0.075  # seconds per typed key in the video
MOVE = 0.75  # seconds for a cursor move
OUT = ROOT / "docs" / "design" / "recordings" / "2026-11"

DOM_CHANGES = ["removed the remotecontrol attribute from each browser window's root element (automation cue)"]
EDITS = [
    "cursor and click ripples drawn on the frames afterwards (a headless window has no pointer; hover states are not shown)",
    "typing shown at a fixed pace of one frame per key, each key really typed into the field",
    "while a new instance starts, nothing is recorded: the video cuts to its window once it is up",
    "the last frame is held before the loop starts again",
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
    times = [f["t"] for f in timeline["frames"]] + [k["t"] for k in timeline["cursor"]]
    return round(max(times) + TAIL, 3)


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

    def caption(self, text: str) -> None:
        self.captions.append({"t": round(self.t, 3), "text": text})

    def cut(self, to: str, waited: float) -> None:
        """A cut to another window; `waited` is the real time that was not recorded."""
        self.hide_cursor()
        self.cuts.append({"t": round(self.t, 3), "to": to, "real_seconds_cut": round(waited, 1)})

    def save(self, transcript: str, meta: dict) -> None:
        timeline = {
            "schema": 1,
            "scene": self.scene,
            "locale": self.locale,
            "size": list(self.size),
            "scale": round(self.scale, 3),
            "frames": self.frames,
            "cursor": self.keys,
            "clicks": self.clicks,
            "captions": self.captions,
            "cuts": self.cuts,
            "poster": self.poster or self.frames[-1]["file"],
            "transcript": transcript,
            "notes": self.notes,
            **meta,
        }
        (self.dir / "timeline.json").write_text(json.dumps(timeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# -- capture: fixtures, sessions, windows --------------------------------------------------------

TEXT = {
    "pt-BR": {
        "lang": "pt_BR.UTF-8",
        "first": "Pessoal",
        "work": "Trabalho",
        "bank": "Bancos",
        "pages": {
            "/receitas": ("Receitas da semana", "Sopa de abóbora, arroz de forno e salada de grão-de-bico."),
            "/viagem": ("Roteiro de viagem", "Três dias na serra: trilha no sábado, feira no domingo."),
            "/intranet": ("Intranet da equipe", "Pauta da reunião de segunda e as entregas do mês."),
            "/chamados": ("Chamados abertos", "Quatro pedidos de suporte aguardam resposta."),
        },
        "cap": {
            "profile-opens": [
                "Em Configurações › Perfis, cada parte da vida tem o seu perfil.",
                "Abrir «{work}» abre uma janela só dele, com a sua própria cor e o seu nome.",
                "Histórico, logins e cookies do «{work}» ficam separados dos do «{first}».",
            ],
            "link-routed": [
                "No perfil «{first}», digita-se o endereço da intranet do trabalho.",
                "Uma regra manda esse site para o perfil «{work}».",
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
        "pages": {
            "/recipes": ("Recipes for the week", "Pumpkin soup, baked rice and a chickpea salad."),
            "/trip": ("Trip plan", "Three days in the hills: a hike on Saturday, the market on Sunday."),
            "/intranet": ("Team intranet", "Monday's meeting agenda and this month's deliveries."),
            "/tickets": ("Open tickets", "Four support requests are waiting for an answer."),
        },
        "cap": {
            "profile-opens": [
                "In Settings › Profiles, each part of life has a profile of its own.",
                "Opening “{work}” opens a window of its own, with its own colour and name.",
                "“{work}” keeps its history, logins and cookies apart from “{first}”.",
            ],
            "link-routed": [
                "In the “{first}” profile, the work intranet's address is typed.",
                "A rule sends that site to the “{work}” profile.",
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
PASSWORD = "artificial pass 173"  # noqa: S105 -- a throwaway volume in a throwaway home
SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const V = ChromeUtils.importESModule("{SHELL}/NulavioVault.sys.mjs").NulavioVault;'
    f'const L = ChromeUtils.importESModule("{SHELL}/NulavioLayout.sys.mjs").NulavioLayout;'
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
    title, lead = (html.escape(s) for s in page)
    css = (
        ":root{color-scheme:light dark;font-family:'Noto Sans',Cantarell,system-ui,sans-serif}"
        "body{max-width:38rem;margin:3rem auto;padding:0 1.5rem;line-height:1.55;background:Canvas;color:CanvasText}"
        "h1{font-size:1.75rem;margin:0 0 .5rem}"
    )
    return (
        f'<!doctype html><html lang="{locale}"><meta charset=utf-8><title>{title}</title><style>{css}</style>'
        f"<h1>{title}</h1><p>{lead}</p>"
    ).encode()


class Fixtures:
    """Sample pages with original text on loopback (no third-party names, no favicons); counts requests."""

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
    r = m.chrome(PREFS_DOC + f"const e = {element_js}; e.scrollIntoView({{block: 'center'}});"
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
        engine = harness.nulavio_engine()
        if engine is None:
            raise RuntimeError("recording needs the Nulavio build (NULAVIO_ENGINE)")
        self.meta = {**build_info(Path(engine.path)), "script": "scripts/site/record_site.py", "dom_changes": DOM_CHANGES}

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
        fixtures = Fixtures(locale)
        s = self.session(locale)
        rec = Recorder(self.out, scene, locale)
        others: list = []
        try:
            transcript = getattr(self, scene.replace("-", "_"))(rec, s, fixtures, locale, others)
            rec.save(transcript, {**self.meta, "window_css": list(WINDOW_CSS)})
            return rec.dir
        finally:
            for client in others:
                try:
                    client.quit()
                except Exception:  # noqa: S110 -- the session's cleanup ends what is left
                    pass
            for vault in s.tmp.rglob("*.vault"):
                mountpoint = vault.with_name(vault.name[: -len(".vault")])
                subprocess.run(["fusermount3", "-u", str(mountpoint)], capture_output=True, check=False)
            for dirpath, _d, _f in os.walk(s.tmp):
                os.chmod(dirpath, 0o700)
            s.cleanup()
            fixtures.close()

    def caps(self, locale: str, scene: str) -> list[str]:
        t = TEXT[locale]
        return [c.format(first=t["first"], work=t["work"], bank=t["bank"]) for c in t["cap"][scene]]

    def open_profiles_pane(self, m) -> None:
        """Settings at its Profiles pane in the selected tab, as Settings › Profiles shows it."""
        m.navigate("about:preferences#nulavioProfiles")
        wait(
            lambda: m.chrome(PREFS_DOC + "return !!d?.querySelector('#nulavio-profile-list moz-box-item.nulavio-profile');"),
            30,
            "the profiles pane",
        )
        time.sleep(0.8)

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
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(1.4)
        row = self.row_button(t["work"], "open")
        rec.move(prefs_point(m, row))
        rec.shot(m)
        rec.click()
        self.press(m, row)
        started = time.monotonic()
        rec.watch(m, 1.2)
        child = self.connect(s, path)
        others.append(child)
        wait(lambda: t["work"] in " ".join(band(child)), 30, "the work profile's band")
        window_ready(child, [fx.url(p) for p in WORK_PAGES[locale]])
        rec.cut(t["work"], time.monotonic() - started)
        rec.caption(cap[1])
        rec.shot(child, poster=True)
        rec.hold(2.4)
        rec.caption(cap[2])
        rec.shot(child)
        rec.hold(2.6)
        cues = band(child)
        rec.notes.append("the work window's tab was opened by the script before its first frame")
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
        target = fx.url("/intranet", host="localhost")  # typed in full: a bare host:port is not always read as an address
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(0.8)
        rec.move(chrome_point(m, "gURLBar.inputField"))
        rec.click()
        rec.shot(m)
        type_into_urlbar(rec, m, target)
        rec.caption(cap[1])
        started = time.monotonic()
        rec.watch(m, 1.0)
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
        if fx.hits.count("/intranet") != 1:
            raise RuntimeError(f"the routed page was requested {fx.hits.count('/intranet')} times")
        rec.cut(t["work"], time.monotonic() - started)
        rec.caption(cap[2])
        rec.shot(child, poster=True)
        rec.hold(1.2)
        rec.move(chrome_point(child, "document.querySelector('#nulavio-band-widget .nv-band-route')"), 0.9)
        rec.shot(child)
        rec.hold(2.6)
        rec.notes.append("the routing rule (localhost opens in the work profile) was added by the script before the scene")
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
        listed = chrome_async(m, "return (await P.list()).profiles.find(p => p.id === args[0]);", bank)
        if not listed.get("locked"):
            chrome_async(m, "return V.lock(args[0]);", bank)
            wait(lambda: chrome_async(m, "return (await P.list()).profiles.find(p => p.id === args[0]).locked;", bank), 30,
                 "the protected profile locked")  # fmt: skip
        window_ready(m, [fx.url(p) for p in PERSONAL_PAGES[locale]])
        self.open_profiles_pane(m)
        row = self.row_button(t["bank"], "unlock")
        wait(lambda: m.chrome(PREFS_DOC + f"return !!({row});"), 20, "the Unlock button")
        rec.caption(cap[0])
        rec.shot(m)
        rec.hold(1.6)
        rec.move(prefs_point(m, row))
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
        rec.move(content_point(m, "document.querySelector('#password-form button[type=submit]')"), 0.6)
        rec.click()
        m.send("WebDriver:ElementClick", {"id": m.find_element("#password-form button[type=submit]")})
        state = "return document.body?.dataset.state ?? null;"
        status = "return document.getElementById('status')?.textContent.trim() ?? '';"
        seen = {}

        def unlocked() -> bool:
            try:
                now = m.execute(state)
            except Exception:  # the page closes its tab after success
                return True
            seen.setdefault(now, m.execute(status))
            return now == "unlocked"

        rec.watch(m, 25, until=unlocked, after=0.8)
        started = time.monotonic()
        child = self.connect(s, path)
        others.append(child)
        wait(lambda: t["bank"] in " ".join(band(child)), 30, "the protected profile's band")
        window_ready(child, [])
        rec.cut(t["bank"], time.monotonic() - started)
        rec.caption(cap[2])
        rec.shot(child, poster=True)
        rec.hold(3.0)
        cues = band(child)
        said = seen.get("unlocked", "")
        if locale == "pt-BR":
            return (f"Na tela: Configurações › Perfis, com «{t['bank']}» bloqueado; clique em Desbloquear; a página de"
                    f" desbloqueio pede a senha, que é digitada; ela diz «{said}»; a janela do «{t['bank']}» abre, com a"
                    f" faixa «{' · '.join(cues)}».")  # fmt: skip
        return (f"On screen: Settings › Profiles, with “{t['bank']}” locked; a click on Unlock; the unlock page asks for the"
                f" password, which is typed; it says “{said}”; the “{t['bank']}” window opens, its band reading"
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


def compose_frames(src: Path, timeline: dict, work: Path, width: int, fps: int) -> tuple[int, int, int, float]:
    from PIL import Image, ImageDraw

    end = duration_of(timeline)
    count = round(end * fps)
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
    return size[0], size[1], count, end


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


def loop_webp(work: Path, count: int, fps: int, out: Path, width: int, loop_fps: int = 10) -> Path:
    """The loop for <picture> (reduced motion gets the poster instead): animated WebP at a lower rate and size."""
    from PIL import Image

    step = max(1, round(fps / loop_fps))
    images = []
    for i in range(0, count, step):
        image = Image.open(work / f"{i:05d}.png")
        images.append(image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS))
    images[0].save(out, "WEBP", save_all=True, append_images=images[1:], duration=round(1000 * step / fps), loop=0,
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
    if not shutil.which("ffmpeg"):
        print("compose needs ffmpeg (Fedora: ffmpeg-free)", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"recordings": {}}
    meta = {"commit": git("rev-parse", "--short=7", "HEAD"), "worktree_clean": not git("status", "--porcelain")}
    over = []
    for timeline_path in sorted(frames_root.glob("*/timeline.json")):
        src = timeline_path.parent
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        key = f"{timeline['scene']}-{timeline['locale']}"
        base = out / key
        w, h, count, end = compose_frames(src, timeline, src / "composed", width, fps)
        files = encode(src / "composed", fps, base)
        files.append(loop_webp(src / "composed", count, fps, base.with_name(f"{key}-loop.webp"), loop_width))
        files.append(poster_webp(src, timeline["poster"], base.with_name(f"{key}-poster.webp"), width))
        vtt = base.with_suffix(".vtt")
        vtt.write_text(webvtt(timeline["captions"], end), encoding="utf-8")
        files.append(vtt)
        shutil.rmtree(src / "composed")
        described = [describe(f) for f in files]
        over += [f"{d['file']} ({d['bytes']} bytes)" for d in described if d["bytes"] > budget]
        manifest["recordings"][key] = {
            "scene": timeline["scene"],
            "locale": timeline["locale"],
            "duration_s": end,
            "video_px": [w, h],
            "fps": fps,
            "captured_px": timeline["size"],
            "scale": timeline["scale"],
            "window_css": timeline["window_css"],
            "frames_captured": len(timeline["frames"]),
            "cuts": timeline["cuts"],
            "transcript": timeline["transcript"],
            "captions": timeline["captions"],
            "notes": timeline["notes"],
            "buildid": timeline["buildid"],
            "firefox": timeline["firefox"],
            "files": described,
        }
        print(f"  {key}: {end:.1f} s, " + ", ".join(f"{d['file']} {d['bytes'] // 1024} KiB" for d in described), flush=True)
    manifest.update(
        {
            "schema": 1,
            "script": "scripts/site/record_site.py",
            "harness": "tests/lib/harness.GeckoProfileSession (throwaway HOME, headless), in ci/containers/fedora-release-itest",
            "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **meta,
            "dom_changes": DOM_CHANGES,
            "edits": EDITS,
            "encoders": {
                "webm": "libvpx-vp9 crf 36",
                "mp4": "libopenh264 700k",
                "loop": "Pillow WebP q60, 10 fps",
                "audio": "none",
            },
            "budget_bytes_per_file": budget,
        }
    )
    manifest["recordings"] = dict(sorted(manifest["recordings"].items()))
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    for private in (str(Path.home()), os.environ.get("USER", ""), os.uname().nodename):
        if private and private in text:
            raise SystemExit(f"manifest would contain a personal value ({private!r}); not written")
    manifest_path.write_text(text, encoding="utf-8")
    if over:
        print(f"over the budget of {budget} bytes: {', '.join(over)}", file=sys.stderr)
        return 1
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
