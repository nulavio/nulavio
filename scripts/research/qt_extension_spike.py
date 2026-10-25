#!/usr/bin/env python3
"""Phase 0 feasibility spike: Chrome MV3 extensions inside Qt WebEngine.

Loads unpacked Chrome Web Store extensions into QWebEngineExtensionManager
(Qt >= 6.10) and records what actually works:

  * whether the extension loads, and the reported error;
  * whether it exposes an action popup URL;
  * which `chrome.*` namespaces exist inside the popup page;
  * whether content scripts touch a local login form.

Usage (each CRX must live in its own directory; see docs/research):

    python3 -I scripts/research/qt_extension_spike.py \
        --out /tmp/nulavio-spike/qt-report.json \
        /tmp/nulavio-spike/crx/proton-pass/ext.crx ...

The spike never enters credentials or contacts a vault. It is evidence for
docs/adr/0001-engine-selection.md, not product code.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

LOGIN_FORM = b"""<!doctype html><html><head><title>spike login</title></head>
<body><form action="/submit" method="post">
<label>Email <input type="email" name="email" autocomplete="username"></label>
<label>Password <input type="password" name="password" autocomplete="current-password"></label>
<button type="submit">Sign in</button></form></body></html>"""

PROBE_JS = r"""
(() => {
  const out = {};
  try {
    out.namespaces = (typeof chrome === 'object' && chrome) ? Object.keys(chrome).sort() : [];
    out.connectNative = typeof (chrome && chrome.runtime && chrome.runtime.connectNative);
    out.runtimeId = chrome && chrome.runtime ? chrome.runtime.id : null;
    out.bodyText = (document.body ? document.body.innerText : '').slice(0, 300);
  } catch (e) { out.error = String(e); }
  return JSON.stringify(out);
})()
"""

CONTENT_PROBE_JS = r"""
(() => JSON.stringify({
  // Count elements and shadow hosts that were not part of the fixture page.
  elements: document.querySelectorAll('*').length,
  customElements: [...document.querySelectorAll('*')]
      .filter(e => e.tagName.includes('-') || e.shadowRoot)
      .map(e => e.tagName.toLowerCase()).slice(0, 20),
  inputAttrs: [...document.querySelectorAll('input')].map(i =>
      [...i.attributes].map(a => a.name).filter(n => !['type','name','autocomplete'].includes(n)))
}))()
"""


def crx_to_dir(crx: Path, dest: Path) -> Path:
    """Strip a CRX2/CRX3 header and unzip the payload into ``dest``."""
    data = crx.read_bytes()
    if data[:4] != b"Cr24":
        raise ValueError(f"{crx}: not a CRX file")
    version = struct.unpack("<I", data[4:8])[0]
    if version == 3:
        header_len = struct.unpack("<I", data[8:12])[0]
        offset = 12 + header_len
    elif version == 2:
        pk_len, sig_len = struct.unpack("<II", data[8:16])
        offset = 16 + pk_len + sig_len
    else:
        raise ValueError(f"{crx}: unsupported CRX version {version}")
    zpath = dest.with_suffix(".zip")
    zpath.write_bytes(data[offset:])
    with zipfile.ZipFile(zpath) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"unsafe path in archive: {member}")
        zf.extractall(dest)
    return dest


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(LOGIN_FORM)

    def log_message(self, *_args):
        pass


class Spike:
    def __init__(self, app: QApplication, ext_dirs: list[Path], workdir: Path, port: int, enable: bool = True):
        self.app = app
        self.enable = enable
        self.queue = list(ext_dirs)
        self.results: list[dict] = []
        self.port = port
        # Parent the profile to the app and keep every page referenced: Qt
        # aborts if a profile is released while pages that use it still exist.
        self.profile = QWebEngineProfile("nulavio-qt-spike", app)
        self.pages: list[QWebEnginePage] = []
        self.profile.setPersistentStoragePath(str(workdir / "storage"))
        self.profile.setCachePath(str(workdir / "cache"))
        self.manager = self.profile.extensionManager()
        self.manager.loadFinished.connect(self.on_loaded)
        self.page: QWebEnginePage | None = None
        self.current: dict = {}

    def start(self):
        self.next()

    def next(self):
        if not self.queue:
            for page in self.pages:
                page.deleteLater()
            QTimer.singleShot(500, self.app.quit)
            return
        path = self.queue.pop(0)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8-sig"))
        self.current = {
            "dir": str(path),
            "name": manifest.get("name"),
            "version": manifest.get("version"),
            "manifest_version": manifest.get("manifest_version"),
            "permissions": manifest.get("permissions", []),
            "optional_permissions": manifest.get("optional_permissions", []),
        }
        self.manager.loadExtension(str(path))
        QTimer.singleShot(20000, self.timeout_guard(path))

    def timeout_guard(self, path):
        def _guard():
            if self.current.get("dir") == str(path) and "loaded" not in self.current:
                self.current["loaded"] = False
                self.current["error"] = "timeout waiting for loadFinished"
                self.finish()

        return _guard

    def on_loaded(self, info):
        self.current.update(
            loaded=info.isLoaded(),
            enabled_initially=info.isEnabled(),
            error=info.error(),
            id=info.id(),
            popup=info.actionPopupUrl().toString(),
        )
        # Finding (Qt 6.11.2 / PySide6): calling setExtensionEnabled() with the
        # info object *inside* the loadFinished handler segfaults in
        # libQt6WebEngineCore. Defer and re-fetch the info from the manager.
        ext_id = info.id()
        popup = QUrl(info.actionPopupUrl())
        if not self.enable:
            # Load-only mode: record what the manager reports and move on.
            self.finish()
            return
        QTimer.singleShot(0, lambda: self.enable_then_probe(ext_id, popup))

    def enable_then_probe(self, ext_id: str, popup: QUrl):
        for ext in self.manager.extensions():
            if ext.id() == ext_id and ext.isLoaded():
                self.manager.setExtensionEnabled(ext, True)
        self.current["enabled_after_request"] = any(e.id() == ext_id and e.isEnabled() for e in self.manager.extensions())
        if popup.isValid() and not popup.isEmpty():
            self.open(popup, self.after_popup)
        else:
            self.open(QUrl(f"http://127.0.0.1:{self.port}/login"), self.after_login)

    def open(self, url: QUrl, cb):
        self.page = QWebEnginePage(self.profile)
        self.pages.append(self.page)
        self.page.loadFinished.connect(lambda ok: QTimer.singleShot(4000, lambda: cb(ok)))
        self.page.load(url)

    def after_popup(self, ok):
        self.current["popup_load_ok"] = ok

        def got(result):
            try:
                self.current["popup_probe"] = json.loads(result) if result else None
            except (TypeError, ValueError):
                self.current["popup_probe"] = {"raw": str(result)}
            self.open(QUrl(f"http://127.0.0.1:{self.port}/login"), self.after_login)

        self.page.runJavaScript(PROBE_JS, 0, got)

    def after_login(self, ok):
        self.current["login_page_ok"] = ok

        def got(result):
            try:
                self.current["content_probe"] = json.loads(result) if result else None
            except (TypeError, ValueError):
                self.current["content_probe"] = {"raw": str(result)}
            self.finish()

        self.page.runJavaScript(CONTENT_PROBE_JS, 0, got)

    def finish(self):
        self.results.append(self.current)
        self.current = {}
        QTimer.singleShot(0, self.next)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("crx", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--load-only",
        action="store_true",
        help="do not call setExtensionEnabled() (crashes on Qt 6.11.2, see ADR 0001)",
    )
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="nulavio-qt-spike-"))
    ext_dirs = []
    for crx in args.crx:
        dest = workdir / "ext" / crx.parent.name
        dest.mkdir(parents=True)
        ext_dirs.append(crx_to_dir(crx, dest))

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = QApplication(sys.argv)
    spike = Spike(app, ext_dirs, workdir, server.server_address[1], enable=not args.load_only)
    QTimer.singleShot(0, spike.start)
    app.exec()
    server.shutdown()
    shutil.rmtree(workdir, ignore_errors=True)  # unpacked third-party code + profile

    from PySide6 import __version__ as pyside_version

    report = {
        "qt_webengine_user_agent": QWebEngineProfile.defaultProfile().httpUserAgent(),
        "pyside6": pyside_version,
        "results": spike.results,
    }
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
