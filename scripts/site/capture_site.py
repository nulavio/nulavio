#!/usr/bin/env python3
"""Capture the figures of nulavio.net from the real Nulavio build (spec §6).

    NULAVIO_ENGINE=/path/to/nulavio/nulavio \\
        python3 -I scripts/site/capture_site.py [--locales pt-BR en-US] [--only window,bands,guard]

Every scene runs on tests/lib/harness.GeckoProfileSession: a throwaway HOME,
registered engine profiles, headless, never a user profile. The figures:

* C1 ``window``: the main window of a protected profile "Trabalho"/"Work"
  (briefcase, sky) created and unlocked through the Shell's own Vault API on
  a real gocryptfs volume, three local sample pages served by this script on
  127.0.0.1, Lateral layout. Falls back to the plain first profile if the
  Vault is not available here, and the manifest says so.
* C2 ``bands``: element crops of ``#nulavio-band``: the plain first profile,
  the protected profile, a temporary profile made by the build's own
  ``nulavio-tools temporary api``, and a private window. The AI Workspace
  state needs a live bridge session and is not captured.
* C3 ``guard``: the Guard review document after part of
  tests/integration/test_guard.py::test_02 (proxy in prefs.js, malware
  protection off in user.js, a native-messaging manifest pointing to
  /usr/bin/true and a throwaway test CA), at 800 and 390 CSS px.

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
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tests" / "lib")]

import harness  # noqa: E402
from PIL import Image  # noqa: E402

SHOTS = ROOT / "site" / "assets" / "shots"
MASTERS = ROOT / "docs" / "design" / "screenshots" / "site"
THEMES = {"light": 0, "dark": 1}
SCALE = 2
WINDOW_CROP = {"x": 0, "y": 0, "w": 600, "h": 420}  # CSS px of the 900x640 window
SEALS = {"private": "nv-band-private", "temporary": "nv-band-temporary"}
DOM_CHANGES = ["removed the remotecontrol attribute from the browser window's root element (automation cue)"]

SHELL = "ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/{0}.sys.mjs')"
PROFILES = SHELL.format("NulavioProfiles") + ".NulavioProfiles"
VAULT = SHELL.format("NulavioVault")
LAYOUT = SHELL.format("NulavioLayout") + ".NulavioLayout"
GUARD = SHELL.format("NulavioGuard") + ".NulavioGuard"

TEXT = {
    "pt-BR": {
        "first": "Pessoal",
        "work": "Trabalho",
        "lang": "pt_BR.UTF-8",
        "pages": [
            ("/notas", "Notas da reunião"),
            ("/horas", "Planilha de horas"),
            ("/documentacao", "Documentação"),
        ],
        "notes": [
            "Revisar o cronograma do segundo trimestre com a equipe.",
            "Mover a entrega do relatório para quinta-feira.",
            "Marcar a próxima conversa com o suporte para a semana que vem.",
        ],
        "notes_h2": "Decisões",
        "notes_lead": "Reunião semanal · 30 minutos · 4 pessoas",
        "on_screen": "Na tela: ",
        "and": " e ",
    },
    "en-US": {
        "first": "Personal",
        "work": "Work",
        "lang": "en_US.UTF-8",
        "pages": [
            ("/notes", "Meeting notes"),
            ("/timesheet", "Timesheet"),
            ("/documentation", "Documentation"),
        ],
        "notes": [
            "Review the second-quarter schedule with the team.",
            "Move the report delivery to Thursday.",
            "Book the next call with support for next week.",
        ],
        "notes_h2": "Decisions",
        "notes_lead": "Weekly meeting · 30 minutes · 4 people",
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
        items = "".join(f"<li>{html.escape(n)}</li>" for n in t["notes"])
        body = f"<h1>{title}</h1><p class=meta>{t['notes_lead']}</p><h2>{t['notes_h2']}</h2><ul>{items}</ul>"
    else:
        body = f"<h1>{title}</h1>"
    css = (
        ":root{color-scheme:light dark;font-family:'Noto Sans',Cantarell,system-ui,sans-serif}"
        "body{max-width:38rem;margin:3rem auto;padding:0 1.5rem;line-height:1.55;"
        "background:Canvas;color:CanvasText}"
        "h1{font-size:1.75rem;margin:0 0 .25rem}.meta{color:GrayText;margin:0 0 1.5rem}"
        "li{margin:.4rem 0}"
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


class Output:
    def __init__(self, args: list[str]):
        self.files: list[dict] = []
        self.args = args
        self.figures: dict = {}
        SHOTS.mkdir(parents=True, exist_ok=True)
        MASTERS.mkdir(parents=True, exist_ok=True)

    def save(self, png: bytes, name: str, crop_css: dict | None, meta: dict) -> dict:
        image = Image.open(io.BytesIO(png)).convert("RGB")
        if crop_css:
            box = tuple(
                round(v * SCALE)
                for v in (crop_css["x"], crop_css["y"], crop_css["x"] + crop_css["w"], crop_css["y"] + crop_css["h"])
            )
            image = image.crop(box)
        master = io.BytesIO()
        image.save(master, "PNG", optimize=True)
        (MASTERS / f"{name}.png").write_bytes(master.getvalue())
        webp = io.BytesIO()
        image.save(webp, "WEBP", lossless=True, quality=100, method=6)
        data = webp.getvalue()
        (SHOTS / f"{name}.webp").write_bytes(data)
        entry = {
            "file": f"{name}.webp",
            "master": f"docs/design/screenshots/site/{name}.png",
            **meta,
            "scale": SCALE,
            "crop_css": crop_css,
            "width": image.width,
            "height": image.height,
            "dom_changes": DOM_CHANGES,
            "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        self.files = [f for f in self.files if f["file"] != entry["file"]] + [entry]
        print(f"  {entry['file']} {image.width}x{image.height} {len(data) // 1024} KiB", flush=True)
        return entry

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
          const {{id}} = await V.NulavioVault.createProtected({{name: args[1], avatar: 'briefcase', color: 'sky', password: args[0]}});
          const path = (await SPS.getProfile(id)).path;
          await V.vaultHelper({{op: 'unlock', path, method: 'password', secret: args[0]}});
          return {{id, path}};
        """
        made = chrome_async(m, body, ["synthetic capture password, throwaway volume", t["work"]])
        path = Path(made["path"])
        harness.GeckoProfileSession.enable_marionette(path)
        add_prefs(path, s.prefs)
        launched = chrome_async(m, f"return {PROFILES}.switchTo(args[0]);", [made["id"]])
        if launched != {"action": "launched"}:
            raise RuntimeError(f"switchTo: {launched}")
        child = harness.GeckoProfileSession.connect(path)
        try:
            if not harness.wait_until(lambda: t["work"] in transcript_of(band_state(child) or {"cues": []}), 20):
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
            capture_band(out, child, "work", locale, {**meta, "port": fixtures.port, "profile": "protected, unlocked"})
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
            capture_band(out, m, "temporary", locale, {**meta, "port": fixtures.port, "profile": "temporary (nulavio-tools temporary api)"})
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
            image = Image.open(io.BytesIO(png))
            crop = {"x": 0, "y": 0, "w": image.width / SCALE, "h": min(image.height / SCALE, page["bottom"] + 8)}
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


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def build_info(engine_path: Path) -> dict:
    ini = configparser.ConfigParser()
    ini.read(engine_path.parent / "application.ini")
    return {"buildid": ini["App"]["BuildID"], "version": ini["App"]["Version"], "vendor": ini["App"]["Vendor"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locales", nargs="+", default=["pt-BR", "en-US"], choices=sorted(TEXT))
    parser.add_argument("--only", default="window,bands,guard", help="comma list of: window, bands, guard")
    args = parser.parse_args()
    engine = harness.nulavio_engine()
    if engine is None:
        print("needs the Nulavio build (NULAVIO_ENGINE)", file=sys.stderr)
        return 2
    info = build_info(Path(engine.path))
    only = set(args.only.split(","))
    argv = ["--locales", *args.locales, "--only", args.only]
    out = Output(argv)
    manifest_path = SHOTS / "manifest.json"
    if manifest_path.exists():  # keep figures not captured in this run
        old = json.loads(manifest_path.read_text())
        out.files, out.figures = old.get("files", []), old.get("figures", {})
    meta = {
        "commit": git("rev-parse", "--short=7", "HEAD"),
        # Read before anything is written: the captures themselves dirty site/assets/shots.
        "worktree_clean": not git("status", "--porcelain"),
        "buildid": info["buildid"],
        "firefox": info["version"],
        "script": "scripts/site/capture_site.py",
        "args": argv,
        "harness": "tests/lib/harness.GeckoProfileSession (throwaway HOME, headless)",
    }
    left_out: list[str] = []

    def write_manifest() -> None:
        manifest = {
            "schema": 1,
            "commit": meta["commit"],
            "worktree_clean": meta["worktree_clean"],
            "buildid": info["buildid"],
            "firefox": info["version"],
            "script": meta["script"],
            "args": argv,
            "dom_changes": DOM_CHANGES,
            "not_captured": ["band-agent (C2e): needs a live AI Bridge session", "assistant (C4): not attempted", *left_out],
            "figures": out.figures,
            "files": sorted(out.files, key=lambda f: f["file"]),
        }
        text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        for private in (str(Path.home()), os.environ.get("USER", ""), os.uname().nodename):
            if private and private in text:
                raise SystemExit(f"manifest would contain a personal value ({private!r}); not written")
        manifest_path.write_text(text, encoding="utf-8")

    def run(label: str, scene, *scene_args) -> None:
        try:
            if scene(*scene_args) is False:
                left_out.append(f"{label}: not available in this environment")
        except Exception as e:  # a figure that cannot be made real is left out, never faked
            left_out.append(f"{label}: {type(e).__name__}: {e}")
            print(f"  {label} left out: {e}", flush=True)
        write_manifest()  # progress is saved after every scene

    for locale in args.locales:
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
    print(f"{len(out.files)} files; left out: {left_out}")
    return 1 if left_out else 0


if __name__ == "__main__":
    raise SystemExit(main())
