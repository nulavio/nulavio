#!/usr/bin/env python3
"""Capture the figures of nulavio.net from the real Nulavio build (spec §6).

    NULAVIO_ENGINE=/path/to/nulavio/nulavio \\
        python3 -I scripts/site/capture_site.py [--locales pt-BR en-US] [--only window,bands,guard]

That is both steps on one machine. They are two because the release test container, where the site's
recordings are made and whose fonts are fixed, has no Pillow and only a copy of the checkout:

1. capture (needs the engine): ``tests/integration/capture_site_shots.py``, run by name where the
   integration tests run, writes the window screenshots as they came and ``captures.json`` (crops in CSS
   px, what the DOM said) to ``<artifacts>/site-shots/``;
2. compose (needs Pillow and git, no engine): ``python3 -I scripts/site/capture_site.py compose <dir>``
   cuts and encodes them into the tree and writes the manifest. It stamps this checkout's commit: run it
   on the commit the build's Shell was packed from.

Every scene runs on tests/lib/harness.GeckoProfileSession: a throwaway HOME,
registered engine profiles, headless, never a user profile. The cast is the one of the
site's recordings (scripts/site/record_site.py): the first profile "Pessoal"/"Personal" has no
password and the protected profile is "Bancos"/"Banking". The figures:

* C1 ``window``: the main window of the protected profile "Bancos"/"Banking"
  (the banking template) created and unlocked through the Shell's own Vault API on
  a real gocryptfs volume, three local sample pages served by this script on
  127.0.0.1, Lateral layout. Left out if the Vault is not available here, and the
  manifest says so.
* C2 ``bands``: element crops of ``#nulavio-band``: the plain first profile,
  the protected profile, a temporary profile made by the build's own
  ``nulavio-tools temporary api``, and a private window. The AI Workspace
  state needs a live bridge session and is not captured. Each state also has a
  ``strip`` crop for the landing: the cues it shows with the same space around them,
  the band's row without the dashed edge some states add, and one width for the states of a language and theme.
* C3 ``guard``: the Guard review document after part of
  tests/integration/test_guard.py::test_02 (proxy in prefs.js, malware
  protection off in user.js, a native-messaging manifest pointing to
  /usr/bin/true and a throwaway test CA), at 800 and 390 CSS px.

Captures stay in the history for good: nothing is rewritten to remove them. Each release measures
the media in the history against ADR 0013's budget (250 MB, docs/adr/0013-repository-layout.md).

The only DOM change is removing the window's ``remotecontrol`` attribute
(the striped address bar and robot icon the engine shows under automation).
Every transcript in the manifest is read from the DOM at capture time.

Outputs: lossless WebP in site/assets/shots/, PNG masters in
docs/design/screenshots/site/, and site/assets/shots/manifest.json.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import datetime as dt
import hashlib
import html
import http.server
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tests" / "lib")]

import harness  # noqa: E402

SHOTS = ROOT / "site" / "assets" / "shots"
MASTERS = ROOT / "docs" / "design" / "screenshots" / "site"
THEMES = {"light": 0, "dark": 1}
SCALE = 2
WINDOW_CROP = {"x": 0, "y": 0, "w": 600, "h": 420}  # CSS px of the 900x640 window
SEALS = {"private": "nv-band-private", "temporary": "nv-band-temporary"}
STRIP_PAD = 8  # CSS px to the left and right of the cues of a strip crop
STRIP_WINDOW = (900, 640)  # as the window of the corner crop: the band has a row to itself
NOT_ATTEMPTED = ["band-agent (C2e): needs a live AI Bridge session", "assistant (C4): not attempted"]
RAW = "site-shots"  # under the artifacts directory: what the capture step leaves for compose
DOM_CHANGES = ["removed the remotecontrol attribute from the browser window's root element (automation cue)"]

SHELL = "ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/{0}.sys.mjs')"
PROFILES = SHELL.format("NulavioProfiles") + ".NulavioProfiles"
VAULT = SHELL.format("NulavioVault")
LAYOUT = SHELL.format("NulavioLayout") + ".NulavioLayout"
GUARD = SHELL.format("NulavioGuard") + ".NulavioGuard"

TEXT = {
    "pt-BR": {
        "first": "Pessoal",
        "bank": "Bancos",
        "lang": "pt_BR.UTF-8",
        "pages": [
            ("/extrato", "Extrato do mês"),
            ("/contas", "Contas a pagar"),
            ("/reserva", "Reserva"),
        ],
        "rows_head": ("Dia", "Lançamento", "Valor"),
        "rows": [
            ("02", "Aluguel", "− R$ 1.850,00"),
            ("05", "Salário", "+ R$ 6.200,00"),
            ("08", "Conta de luz", "− R$ 214,30"),
            ("10", "Escola", "− R$ 980,00"),
            ("15", "Mercado", "− R$ 642,75"),
            ("20", "Internet", "− R$ 119,90"),
        ],
        "rows_h2": "Lançamentos",
        "rows_lead": "Conta de exemplo · novembro",
        "on_screen": "Na tela: ",
        "and": " e ",
    },
    "en-US": {
        "first": "Personal",
        "bank": "Banking",
        "lang": "en_US.UTF-8",
        "pages": [
            ("/statement", "Monthly statement"),
            ("/bills", "Bills to pay"),
            ("/savings", "Savings"),
        ],
        "rows_head": ("Day", "Entry", "Amount"),
        "rows": [
            ("02", "Rent", "− $1,850.00"),
            ("05", "Salary", "+ $6,200.00"),
            ("08", "Electricity", "− $214.30"),
            ("10", "School", "− $980.00"),
            ("15", "Groceries", "− $642.75"),
            ("20", "Internet", "− $119.90"),
        ],
        "rows_h2": "Entries",
        "rows_lead": "Sample account · November",
        "on_screen": "On screen: ",
        "and": " and ",
    },
}

# Visible cues of the band, in order, as a reader sees them (read from the DOM, never typed here).
BAND_CUES = """(() => {
  const row = document.querySelector('#nulavio-band .nv-band-row');
  if (!row) return null;
  const shown = e => e && !e.hidden && e.checkVisibility() && e.getBoundingClientRect().width > 0;
  const cues = [];
  for (const e of row.querySelectorAll('button, .nv-band-seal, .nv-band-header')) {
    if (!shown(e) || cues.some(c => c.node.contains(e))) continue;
    let text = e.textContent.trim();
    if (e.classList.contains('nv-band-identity')) {
      text = [e.querySelector('.nv-band-flag')?.textContent.trim(), e.querySelector('.nv-band-name')?.textContent.trim()]
        .filter(Boolean).join(' ');
    }
    if (text) cues.push({node: e, kind: e.className, text});
  }
  const rect = e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  const pick = sel => { const e = row.querySelector(sel); return shown(e) ? rect(e) : null; };
  const band = document.getElementById('nulavio-band');
  return {cues: cues.map(c => ({kind: c.kind, text: c.text, rect: rect(c.node)})), band: rect(band),
    identity: pick('.nv-band-identity'), protection: pick('.nv-band-protection'), seals: pick('.nv-band-seals'),
    data: {...row.dataset}};
})()"""


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["ok"]


# -- fixtures -----------------------------------------------------------------------------


def fixture_page(locale: str, path: str) -> bytes | None:
    t = TEXT[locale]
    titles = dict(t["pages"])
    if path not in titles:
        return None
    title = titles[path]
    if path == t["pages"][0][0]:
        cells = lambda row, tag: "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in row)  # noqa: E731
        rows = "".join(f"<tr>{cells(r, 'td')}</tr>" for r in t["rows"])
        body = (
            f"<h1>{title}</h1><p class=meta>{t['rows_lead']}</p><h2>{t['rows_h2']}</h2>"
            f"<table><thead><tr>{cells(t['rows_head'], 'th')}</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        body = f"<h1>{title}</h1>"
    css = (
        ":root{color-scheme:light dark;font-family:'Noto Sans',Cantarell,system-ui,sans-serif}"
        "body{max-width:38rem;margin:3rem auto;padding:0 1.5rem;line-height:1.55;"
        "background:Canvas;color:CanvasText}"
        "h1{font-size:1.75rem;margin:0 0 .25rem}.meta{color:GrayText;margin:0 0 1.5rem}"
        "h2{font-size:1.1rem;margin:0 0 .5rem}table{border-collapse:collapse;font-variant-numeric:tabular-nums}"
        "th,td{text-align:left;padding:.45rem 1.5rem .45rem 0;border-bottom:1px solid color-mix(in srgb,GrayText 35%,Canvas)}"
        "th{font-size:.8rem;color:GrayText;font-weight:600}td:last-child,th:last-child{text-align:right;padding-right:0}"
    )
    doc = f'<!doctype html><html lang="{locale}"><meta charset=utf-8><title>{title}</title><style>{css}</style>{body}'
    return doc.encode()


class Fixtures:
    """Sample pages on 127.0.0.1 with original text (no third-party names, no favicons)."""

    def __init__(self, locale: str):
        outer = self
        self.locale = locale

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = fixture_page(outer.locale, self.path.partition("?")[0])
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

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# -- sessions -----------------------------------------------------------------------------


def capture_prefs(locale: str) -> dict:
    return {
        "layout.css.devPixelsPerPx": str(SCALE),
        "intl.locale.requested": locale,
        "ui.systemUsesDarkTheme": 0,
        "browser.sessionstore.resume_from_crash": False,
    }


def add_prefs(profile_dir: Path, prefs: dict) -> None:
    lines = [f'user_pref("{k}", {harness.Session._js(v)});' for k, v in prefs.items()]
    with open(Path(profile_dir) / "user.js", "a", encoding="utf-8") as handle:
        handle.write("// capture_site.py overlay (disposable profile only)\n" + "\n".join(lines) + "\n")


class CaptureSession(harness.GeckoProfileSession):
    """GeckoProfileSession with the capture prefs (scale, locale) in each disposable profile."""

    def __init__(self, locale: str, name: str):
        super().__init__(name=name)
        self.locale = locale
        self.env["LANG"] = TEXT[locale]["lang"]
        self.prefs = capture_prefs(locale)

    def enable_marionette(self, profile_dir: Path) -> None:  # called by start() on the first profile
        harness.GeckoProfileSession.enable_marionette(profile_dir)
        add_prefs(profile_dir, self.prefs)


def window_png(m) -> bytes:
    m.set_context("chrome")
    m.execute("document.documentElement.removeAttribute('remotecontrol');")
    time.sleep(0.2)
    data = m.send("WebDriver:TakeScreenshot", {"full": False})["value"]
    return base64.b64decode(data)


def set_theme(m, theme: str) -> None:
    m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [THEMES[theme]])
    time.sleep(0.8)


def show_pages(m, fixtures: Fixtures, locale: str) -> None:
    """Three local tabs, the first selected; every other tab (the new tab, Shell pages) closed."""
    urls = [fixtures.url(p) for p, _ in TEXT[locale]["pages"]]
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
        [urls],
    )
    time.sleep(1.0)


def lateral(m) -> None:
    applied = chrome_async(m, f"return await {LAYOUT}.apply(window, 'lateral');")
    if "error" in (applied or {}):
        raise RuntimeError(f"layout: {applied}")
    m.chrome("SidebarController.hide?.();")
    time.sleep(0.5)


def dismiss_bars(m) -> None:
    m.chrome("gNotificationBox.removeAllNotifications?.(true);")


def band_state(m) -> dict:
    return m.chrome(f"return {BAND_CUES};")


def transcript_of(state: dict) -> str:
    return " · ".join(c["text"] for c in state["cues"])


# -- image output -------------------------------------------------------------------------


def png_size(png: bytes) -> tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", png[16:24])


class Output:
    """What the capture step leaves: each screenshot as it came, and what to cut from it (in CSS px)."""

    def __init__(self, raw: Path):
        self.raw = raw
        self.entries: list[dict] = []
        self.figures: dict = {}
        raw.mkdir(parents=True, exist_ok=True)

    def save(self, png: bytes, name: str, crop_css: dict | None, meta: dict, strip: dict | None = None) -> None:
        file = hashlib.sha256(png).hexdigest()[:20] + ".png"  # one screenshot is cut several times
        if not (self.raw / file).exists():
            (self.raw / file).write_bytes(png)
        entry = {"name": name, "raw": file, "crop_css": crop_css, "strip": strip, "meta": meta,
                 "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}  # fmt: skip
        self.entries = [e for e in self.entries if e["name"] != name] + [entry]
        print(f"  {name}", flush=True)

    def figure(self, key: str, locale: str, **fields) -> None:
        self.figures.setdefault(key, {})[locale] = fields


def union(*rects) -> dict:
    rects = [r for r in rects if r]
    x0, y0 = min(r["x"] for r in rects), min(r["y"] for r in rects)
    x1, y1 = max(r["x"] + r["w"] for r in rects), max(r["y"] + r["h"] for r in rects)
    pad = 4
    return {"x": max(0, x0 - pad), "y": max(0, y0 - pad), "w": x1 - x0 + 2 * pad, "h": y1 - y0 + 2 * pad}


def capture_band(out: Output, m, state_key: str, locale: str, meta: dict, width: int = 1280, height: int = 800) -> str:
    """C2: #nulavio-band in this window, both themes, full band and the narrow crop."""
    m.set_context("chrome")
    m.send("WebDriver:SetWindowRect", {"width": width, "height": height})
    time.sleep(0.8)
    transcript = None
    for theme in THEMES:
        set_theme(m, theme)
        state = band_state(m)
        if state is None:
            raise RuntimeError("no band in this window")
        transcript = transcript_of(state)
        png = window_png(m)
        base = {**meta, "figure": "fig-2", "state": state_key, "locale": locale, "theme": theme,
                "viewport_css": [width, height], "transcript": transcript, "band_data": state["data"]}  # fmt: skip
        out.save(png, f"band-{state_key}-{locale}-{theme}", state["band"], base)
        # Narrow variants (<48rem) are crops of the same shot: the identity and protection cues, and, where
        # the state has a seal at the row's far end, that seal as a second crop (never composited).
        out.save(png, f"band-{state_key}-crop-{locale}-{theme}", union(state["identity"], state["protection"]), base)
        seal = SEALS.get(state_key)
        if seal:
            rect = next((c["rect"] for c in state["cues"] if seal in c["kind"].split()), None)
            if rect is None:
                raise RuntimeError(f"no visible {seal} in the band")
            out.save(png, f"band-{state_key}-seal-{locale}-{theme}", union(rect), base)
    # The landing's strip, from a narrower window: there the band has a row to itself in every state, so the
    # states share its height. Compose gives the states of one language and theme one width; `cues` is what
    # must be inside the cut and `align` the side of the band they are on.
    m.send("WebDriver:SetWindowRect", {"width": STRIP_WINDOW[0], "height": STRIP_WINDOW[1]})
    time.sleep(0.8)
    for theme in THEMES:
        set_theme(m, theme)
        state = band_state(m)
        size = m.chrome("return [innerWidth, innerHeight];")
        seal = SEALS.get(state_key)
        cues = [state["identity"], state["protection"]]
        if seal:  # the seal sits at the far end of the row
            cues = [c["rect"] for c in state["cues"] if seal in c["kind"].split()]
        if not cues or not all(cues):
            raise RuntimeError("the band does not show what its strip is cut around")
        base = {**meta, "figure": "fig-2", "state": state_key, "locale": locale, "theme": theme,
                "viewport_css": size, "transcript": transcript_of(state), "band_data": state["data"]}  # fmt: skip
        out.save(window_png(m), f"band-{state_key}-strip-{locale}-{theme}", None, base,
                 strip={"cues": cues, "band": state["band"], "align": "end" if seal else "start"})  # fmt: skip
    set_theme(m, "light")
    out.figure(f"band-{state_key}", locale, transcript=transcript, port=meta.get("port"))
    return transcript


# -- scenes -------------------------------------------------------------------------------


def scene_first_profile(out: Output, locale: str, fixtures: Fixtures, meta: dict) -> None:
    """The plain first profile (no password) and a private window from it: C2a, C2d."""
    s = CaptureSession(locale, TEXT[locale]["first"])
    try:
        m = s.start()
        time.sleep(2)
        lateral(m)
        dismiss_bars(m)
        show_pages(m, fixtures, locale)
        capture_band(out, m, "personal", locale, {**meta, "port": fixtures.port, "profile": "first (plain)"})
        before = set(m.window_handles())
        m.chrome("OpenBrowserWindow({private: true});")
        if not harness.wait_until(lambda: set(m.window_handles()) - before, 15):
            raise RuntimeError("no private window")
        private = (set(m.window_handles()) - before).pop()
        m.switch_to(private)
        harness.wait_until(lambda: m.chrome("return !!document.querySelector('#nulavio-band .nv-band-row');"), 15)
        m.navigate(fixtures.url(TEXT[locale]["pages"][2][0]))
        time.sleep(1)
        if m.chrome("return document.querySelector('#nulavio-band .nv-band-row').dataset.private;") != "true":
            raise RuntimeError("the band does not say this window is private")
        capture_band(out, m, "private", locale, {**meta, "port": fixtures.port, "profile": "first (plain), private window"})
    finally:
        s.cleanup()


def scene_protected(out: Output, locale: str, fixtures: Fixtures, meta: dict) -> bool:
    """C1 and C2b: a protected profile on a real gocryptfs volume, unlocked, in its own instance."""
    t = TEXT[locale]
    s = CaptureSession(locale, t["first"])
    try:
        m = s.start()
        time.sleep(2)
        caps = chrome_async(m, f"return await {VAULT}.NulavioVault.capabilities();")
        if not (caps.get("storage") and caps.get("sodium")):
            print(f"  Vault unavailable here: {caps}", flush=True)
            return False
        body = f"""
          const V = {VAULT};
          const SPS = ChromeUtils.importESModule('resource:///modules/profiles/SelectableProfileService.sys.mjs').SelectableProfileService;
          const {{id}} = await V.NulavioVault.createProtected(
            {{name: args[1], templateId: 'banking', keyring: false, password: args[0]}});
          const path = (await SPS.getProfile(id)).path;
          await V.vaultHelper({{op: 'unlock', path, method: 'password', secret: args[0]}});
          return {{id, path}};
        """
        made = chrome_async(m, body, ["synthetic capture password, throwaway volume", t["bank"]])
        path = Path(made["path"])
        harness.GeckoProfileSession.enable_marionette(path)
        add_prefs(path, s.prefs)
        launched = chrome_async(m, f"return {PROFILES}.switchTo(args[0]);", [made["id"]])
        if launched != {"action": "launched"}:
            raise RuntimeError(f"switchTo: {launched}")
        child = harness.GeckoProfileSession.connect(path)
        try:
            if not harness.wait_until(lambda: t["bank"] in transcript_of(band_state(child) or {"cues": []}), 20):
                raise RuntimeError("the protected profile's band did not appear")
            time.sleep(2)
            lateral(child)
            dismiss_bars(child)
            show_pages(child, fixtures, locale)
            child.set_context("chrome")
            child.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
            time.sleep(1)
            for theme in THEMES:
                set_theme(child, theme)
                state = band_state(child)
                screen = child.chrome(
                    "return {tabs: gBrowser.visibleTabs.map(t => t.label), selected: gBrowser.selectedTab.label,"
                    " address: gURLBar.inputField.value, size: [innerWidth, innerHeight]};"
                )
                band = [c["text"] for c in state["cues"]]
                tabs = [f"«{x}»" for x in screen["tabs"]]
                tab_list = ", ".join(tabs[:-1]) + t["and"] + tabs[-1] if len(tabs) > 1 else tabs[0]
                band_list = t["and"].join(f"«{x}»" for x in band)
                if locale == "pt-BR":
                    transcript = f"Na tela: faixa {band_list}; abas {tab_list}; endereço «{screen['address']}»."
                else:
                    transcript = f"On screen: band {band_list}; tabs {tab_list}; address «{screen['address']}»."
                png = window_png(child)
                base = {**meta, "figure": "fig-1", "state": "protected-unlocked", "locale": locale, "theme": theme,
                        "viewport_css": screen["size"], "port": fixtures.port, "transcript": transcript,
                        "band_data": state["data"], "profile": "protected (gocryptfs volume, unlocked by password)"}  # fmt: skip
                out.save(png, f"window-{locale}-{theme}", None, base)
            # The narrow variant (<48rem) is a crop of a smaller window, so the sample page sits next to the
            # tab list: band, address bar, tabs and the page's title all fit in the crop the alt text describes.
            child.send("WebDriver:SetWindowRect", {"width": 900, "height": 640})
            time.sleep(1)
            for theme in THEMES:
                set_theme(child, theme)
                size = child.chrome("return [innerWidth, innerHeight];")
                base = {**base, "theme": theme, "viewport_css": size}
                out.save(window_png(child), f"window-crop-{locale}-{theme}", WINDOW_CROP, base)
            set_theme(child, "light")
            out.figure("fig-1", locale, transcript=transcript, port=fixtures.port, state="protected-unlocked")
            capture_band(out, child, "protected", locale, {**meta, "port": fixtures.port, "profile": "protected, unlocked"})
        finally:
            child.quit()
        return True
    finally:
        s.cleanup()


def scene_temporary(out: Output, locale: str, fixtures: Fixtures, meta: dict) -> None:
    """C2c: a temporary profile made by the build's own tools, started as its own instance."""
    s = CaptureSession(locale, TEXT[locale]["first"])
    engine = None
    try:
        s.start()
        tools = Path(s.engine.path).parent / "nulavio-tools" / "bin" / "nulavio"
        made = subprocess.run(
            [str(tools), "temporary", "api"], input=json.dumps({"op": "create"}), env=s.env,
            capture_output=True, text=True, timeout=60, check=True,
        )  # fmt: skip
        path = Path(json.loads(made.stdout)["path"])
        harness.GeckoProfileSession.enable_marionette(path)
        add_prefs(path, s.prefs)
        engine = subprocess.Popen(
            [str(s.engine.path), "--profile", str(path)], env=s.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )  # fmt: skip
        m = harness.GeckoProfileSession.connect(path, engine)
        try:
            harness.wait_until(lambda: m.chrome("return !!document.querySelector('#nulavio-band .nv-band-row');"), 20)
            time.sleep(2)
            if m.chrome("return document.querySelector('#nulavio-band .nv-band-row').dataset.temporary;") != "true":
                raise RuntimeError("the band does not say this profile is temporary")
            lateral(m)
            dismiss_bars(m)
            show_pages(m, fixtures, locale)
            capture_band(
                out, m, "temporary", locale, {**meta, "port": fixtures.port, "profile": "temporary (nulavio-tools temporary api)"}
            )
        finally:
            m.quit()
    finally:
        if engine is not None:
            try:
                engine.wait(timeout=30)
            except subprocess.TimeoutExpired:
                engine.kill()
        s.cleanup()


def scene_guard(out: Output, locale: str, meta: dict, theme: str) -> None:
    """C3: the Guard review document after changes made while the profile was closed.

    Each theme gets its own session started in that theme: switching the system theme while the page
    is open leaves its secondary buttons with the light background (seen on 2026-11-04), which is not
    what someone who uses the dark theme sees."""
    s = CaptureSession(locale, TEXT[locale]["first"])
    s.prefs["ui.systemUsesDarkTheme"] = THEMES[theme]
    try:
        m = s.start()
        record = s.profile_dir / "nulavio-guard.json"
        if not harness.wait_until(record.exists, timeout=30):
            raise RuntimeError("no Guard record")
        s.stop()
        with open(s.profile_dir / "prefs.js", "a", encoding="utf-8") as prefs_js:
            prefs_js.write('user_pref("network.proxy.type", 1);\nuser_pref("network.proxy.http", "127.0.0.1");\n')
        with open(s.profile_dir / "user.js", "a", encoding="utf-8") as user_js:
            user_js.write('user_pref("browser.safebrowsing.malware.enabled", false);\n')
        hosts = Path(s.env["HOME"]) / ".mozilla" / "native-messaging-hosts"
        hosts.mkdir(parents=True, exist_ok=True)
        manifest = {"name": "net.nulavio.guard_test", "description": "test", "path": "/usr/bin/true",
                    "type": "stdio", "allowed_extensions": ["x@y"]}  # fmt: skip
        (hosts / "net.nulavio.guard_test.json").write_text(json.dumps(manifest))
        if shutil.which("certutil") and shutil.which("openssl"):
            ca = s.tmp / "ca"
            ca.mkdir()
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "2",
                 "-subj", "/CN=Nulavio Guard Test CA", "-keyout", str(ca / "key.pem"), "-out", str(ca / "ca.pem")],
                check=True, capture_output=True,
            )  # fmt: skip
            subprocess.run(
                ["certutil", "-A", "-d", f"sql:{s.profile_dir}", "-n", "Nulavio Guard Test CA", "-t", "C,,",
                 "-i", str(ca / "ca.pem")], stdin=subprocess.DEVNULL, check=True, capture_output=True,
            )  # fmt: skip
            (ca / "key.pem").unlink()
        m = s.restart()
        bar = "const n = gNotificationBox.getNotificationWithValue('nulavio-guard'); return n ? n.messageText.textContent : '';"
        if not harness.wait_until(lambda: "Nulavio Guard" in m.chrome(bar), timeout=30):
            raise RuntimeError("no Guard bar")
        shell = m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        m.navigate(shell + "guard/review.html")
        if not harness.wait_until(lambda: m.execute("return document.documentElement.dataset.ready === 'true';"), 15):
            raise RuntimeError("review page not ready")
        m.chrome("gNotificationBox.getNotificationWithValue('nulavio-guard')?.close();")
        for target, label in ((800, "800"), (390, "narrow")):
            for _ in range(4):  # size the window so the document's viewport is `target` CSS px, or as close as it goes
                inner = m.execute("return document.documentElement.clientWidth;")
                if inner == target:
                    break
                rect = m.send("WebDriver:GetWindowRect")
                rect = rect.get("value", rect)
                m.send("WebDriver:SetWindowRect", {"width": rect["width"] + target - inner, "height": 900})
                time.sleep(0.6)
            dark = m.execute("return matchMedia('(prefers-color-scheme: dark)').matches;")
            if dark != (theme == "dark"):
                raise RuntimeError(f"the review page does not follow the {theme} theme")
            page = m.execute(
                "const cards = [...document.querySelectorAll('#findings > li')];"
                "const last = cards.at(-1).getBoundingClientRect();"
                "return {title: document.getElementById('headline').textContent.trim(),"
                " cards: cards.map(li => li.querySelector('h2').textContent.trim()),"
                " bottom: last.bottom + scrollY, width: document.documentElement.clientWidth,"
                " details: document.querySelector('details.why').open};"
            )
            if page["details"]:
                raise RuntimeError("the limits section is open")
            png = m.screenshot_png(full=True)
            px_w, px_h = png_size(png)
            crop = {"x": 0, "y": 0, "w": px_w / SCALE, "h": min(px_h / SCALE, page["bottom"] + 8)}
            cards = ", ".join(f"«{c}»" for c in page["cards"])
            if locale == "pt-BR":
                transcript = f"Na tela: «{page['title']}», com um cartão para cada mudança: {cards}."
            else:
                transcript = f"On screen: «{page['title']}», with a card for each change: {cards}."
            base = {**meta, "figure": "fig-5", "state": "guard-review", "locale": locale, "theme": theme,
                    "viewport_css": [page["width"], 900], "transcript": transcript, "port": None,
                    "capture": "document (content), not the window; session started in this theme"}  # fmt: skip
            out.save(png, f"guard-review-{locale}-{label}-{theme}", crop, base)
        out.figure("fig-5", locale, transcript=transcript, port=None, cards=page["cards"])
    finally:
        s.cleanup()


# -- main ---------------------------------------------------------------------------------


def build_info(engine_path: Path) -> dict:
    ini = configparser.ConfigParser()
    ini.read(engine_path.parent / "application.ini")
    return {"buildid": ini["App"]["BuildID"], "version": ini["App"]["Version"], "vendor": ini["App"]["Vendor"]}


def capture(raw: Path, locales: list[str], only: set[str]) -> int:
    """Step 1: run the scenes, leave the screenshots and ``captures.json`` in ``raw``. No Pillow, no git."""
    engine = harness.nulavio_engine()
    if engine is None:
        print("needs the Nulavio build (NULAVIO_ENGINE)", file=sys.stderr)
        return 2
    info = build_info(Path(engine.path))
    if raw.exists():
        shutil.rmtree(raw)  # compose never finds a screenshot of an earlier run
    out = Output(raw)
    argv = ["--locales", *locales, "--only", ",".join(sorted(only))]
    where = ", in ci/containers/fedora-release-itest" if Path("/run/.containerenv").exists() else ""
    meta = {"harness": f"tests/lib/harness.GeckoProfileSession (throwaway HOME, headless){where}"}
    left_out: list[str] = []

    def run(label: str, scene, *scene_args) -> None:
        try:
            if scene(*scene_args) is False:
                left_out.append(f"{label}: not available in this environment")
        except Exception as e:  # a figure that cannot be made real is left out, never faked
            left_out.append(f"{label}: {type(e).__name__}: {e}")
            print(f"  {label} left out: {e}", flush=True)
        record = {"schema": 1, "harness": meta["harness"], "buildid": info["buildid"], "firefox": info["version"],
                  "args": argv, "scale": SCALE,
                  "dom_changes": DOM_CHANGES, "left_out": left_out, "figures": out.figures, "entries": out.entries}  # fmt: skip
        (raw / "captures.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    for locale in locales:
        print(f"[{locale}]", flush=True)
        fixtures = Fixtures(locale)
        try:
            if "bands" in only:
                run(f"bands {locale}", scene_first_profile, out, locale, fixtures, meta)
                run(f"band-temporary {locale}", scene_temporary, out, locale, fixtures, meta)
            if "window" in only:
                run(f"fig-1 {locale}", scene_protected, out, locale, fixtures, meta)
            if "guard" in only:
                for theme in THEMES:
                    run(f"fig-5 {locale} {theme}", scene_guard, out, locale, meta, theme)
        finally:
            fixtures.close()
    print(f"{len(out.entries)} cuts; left out: {left_out}")
    return 1 if left_out else 0


# -- compose (host) -----------------------------------------------------------------------


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def strip_boxes(entries: list[dict]) -> dict[str, dict]:
    """The strip crops, in CSS px: the states of one language and theme get one width and the band's height."""
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        if e.get("strip"):
            groups.setdefault((e["meta"]["locale"], e["meta"]["theme"]), []).append(e)
    boxes = {}
    for key, group in groups.items():
        spans = {
            e["name"]: (min(c["x"] for c in e["strip"]["cues"]), max(c["x"] + c["w"] for c in e["strip"]["cues"])) for e in group
        }
        # A temporary or private band adds a dashed lower edge (1.5 px) to the same row: every strip is cut at
        # the row's height, the lowest band's, and the cues must lie inside it.
        height = min(e["strip"]["band"]["h"] for e in group)
        low = [e["name"] for e in group if max(c["y"] + c["h"] for c in e["strip"]["cues"]) > height]
        if low:
            raise SystemExit(f"{key}: cues below the band's common height of {height} px in {low}; the strips are not cut")
        width = max(right - left for left, right in spans.values()) + 2 * STRIP_PAD
        for e in group:
            (left, right), band = spans[e["name"]], e["strip"]["band"]
            x = left - STRIP_PAD if e["strip"]["align"] == "start" else right + STRIP_PAD - width
            # Where the band's own edge is nearer than the pad, the cut stops at the edge: it never leaves the band.
            x = min(max(band["x"], x), band["x"] + band["w"] - width)
            boxes[e["name"]] = {"x": x, "y": band["y"], "w": width, "h": height}
    return boxes


def compose(raw: Path) -> int:
    """Step 2: cut and encode what the capture left, into the tree, and write the manifest."""
    from PIL import Image  # here, not at the top: the capture step runs where Pillow is not installed

    record = json.loads((raw / "captures.json").read_text(encoding="utf-8"))
    scale = record["scale"]
    commit, clean = git("rev-parse", "--short=7", "HEAD"), not git("status", "--porcelain")
    manifest_path = SHOTS / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    names = {e["name"] + ".webp" for e in record["entries"]}
    kept = [f for f in old.get("files", []) if f["file"] not in names]
    if kept and old.get("buildid") != record["buildid"]:
        # The manifest names one build for every capture, and the pages print it.
        raise SystemExit(f"this run leaves {len(kept)} captures of build {old.get('buildid')} in place: capture the whole set")
    strips = strip_boxes(record["entries"])
    SHOTS.mkdir(parents=True, exist_ok=True)
    MASTERS.mkdir(parents=True, exist_ok=True)
    files = []
    for e in record["entries"]:
        image = Image.open(raw / e["raw"]).convert("RGB")
        crop = strips.get(e["name"], e["crop_css"])
        if crop:
            image = image.crop(
                tuple(round(v * scale) for v in (crop["x"], crop["y"], crop["x"] + crop["w"], crop["y"] + crop["h"]))
            )
        name = e["name"]
        image.save(MASTERS / f"{name}.png", "PNG", optimize=True)
        webp = io.BytesIO()
        image.save(webp, "WEBP", lossless=True, quality=100, method=6)
        data = webp.getvalue()
        (SHOTS / f"{name}.webp").write_bytes(data)
        files.append({
            "file": f"{name}.webp",
            "master": f"docs/design/screenshots/site/{name}.png",
            "commit": commit,
            "worktree_clean": clean,
            "buildid": record["buildid"],
            "firefox": record["firefox"],
            "script": "scripts/site/capture_site.py",
            "args": record["args"],
            **e["meta"],
            "scale": scale,
            "crop_css": crop,
            "width": image.width,
            "height": image.height,
            "dom_changes": record["dom_changes"],
            "date": e["date"],
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })  # fmt: skip
        print(f"  {name}.webp {image.width}x{image.height} {len(data) // 1024} KiB", flush=True)
    manifest = {
        "schema": 1,
        "commit": commit,
        "worktree_clean": clean,
        "buildid": record["buildid"],
        "firefox": record["firefox"],
        "script": "scripts/site/capture_site.py",
        "args": record["args"],
        "harness": record["harness"],
        "dom_changes": record["dom_changes"],
        "not_captured": [*NOT_ATTEMPTED, *record["left_out"]],
        "figures": {**old.get("figures", {}), **record["figures"]} if kept else record["figures"],
        "files": sorted(kept + files, key=lambda f: f["file"]),
    }
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    for private in (str(Path.home()), os.environ.get("USER", ""), os.uname().nodename):
        if private and private in text:
            raise SystemExit(f"manifest would contain a personal value ({private!r}); not written")
    manifest_path.write_text(text, encoding="utf-8")
    listed = {f["file"] for f in manifest["files"]}
    for stale in sorted(SHOTS.glob("*.webp")):  # a capture the set no longer has (a renamed state) is not served
        if stale.name not in listed:
            stale.unlink()
            (MASTERS / f"{stale.stem}.png").unlink(missing_ok=True)
            print(f"  removed {stale.name}", flush=True)
    print(f"{len(files)} files; left out: {record['left_out']}")
    return 1 if record["left_out"] else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["compose"]:
        parser = argparse.ArgumentParser(prog="capture_site.py compose", description="Cut and encode a capture into the tree.")
        parser.add_argument("raw", type=Path, help="the site-shots/ directory the capture wrote")
        return compose(parser.parse_args(argv[1:]).raw)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locales", nargs="+", default=["pt-BR", "en-US"], choices=sorted(TEXT))
    parser.add_argument("--only", default="window,bands,guard", help="comma list of: window, bands, guard")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="nulavio-shots-") as tmp:
        status = capture(Path(tmp) / RAW, args.locales, set(args.only.split(",")))
        if status == 2:
            return 2
        return compose(Path(tmp) / RAW) or status


if __name__ == "__main__":
    raise SystemExit(main())
