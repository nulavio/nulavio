"""#249 spike prototype: the assistant panel on the side opposite the vertical tabs.

The patch under study adds, at the end of SidebarController.setPosition's ordering loop, two `style.order`
assignments that move #sidebar-splitter and #sidebar-box past #tabbrowser-tabbox. This probe applies the same
assignments from chrome (and re-applies them when the engine re-orders), then captures the window today and with the
panel opposite, and measures where each box is.

    NULAVIO_ENGINE=<dev>/nulavio/nulavio python3 -I probe249.py <checkout> <out-dir> <locale>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

checkout, out, locale = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(checkout / "tests" / "lib"))
sys.path.insert(0, str(checkout / "tests" / "integration"))
import harness  # noqa: E402

out.mkdir(parents=True, exist_ok=True)
LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
SIDEBAR = "shell_nulavio_net-sidebar-action"

# What the patch does, from chrome: reorder, mark the root, and keep it when setPosition runs again.
OPPOSITE = """
const on = arguments[0];
const apply = () => {
  const browser = document.getElementById('browser');
  const start = SidebarController._positionStart;
  [...browser.children].forEach((node, i, children) => { node.style.order = start ? i + 1 : children.length - i; });
  if (on) {
    const last = browser.children.length + 1;
    SidebarController._splitter.style.order = start ? last - 1 : 1;
    SidebarController._box.style.order = start ? last : 0;
  }
  document.documentElement.toggleAttribute('nulavio-panel-opposite', on);
};
window.__nv249?.disconnect();
apply();
if (on) {
  window.__nv249 = new MutationObserver(() => { if (SidebarController._box.style.order !== String(SidebarController._positionStart ? document.getElementById('browser').children.length + 1 : 0)) apply(); });
  window.__nv249.observe(SidebarController._box, { attributes: true, attributeFilter: ['style'] });
}
return true;
"""

MEASURE = """
const r = id => { const e = document.getElementById(id); if (!e || e.hidden) return null;
  const b = e.getBoundingClientRect(); return b.width ? [Math.round(b.left), Math.round(b.width)] : null; };
const panel = gBrowser.selectedBrowser.getBoundingClientRect();
return { launcher: r('sidebar-container'), box: r('sidebar-box'), splitter: r('sidebar-splitter'),
  tabbox: r('tabbrowser-tabbox'), page: [Math.round(panel.left), Math.round(panel.width)],
  current: SidebarController.currentID, positionend: document.documentElement.hasAttribute('sidebar-positionend'),
  window: [window.outerWidth, window.outerHeight] };
"""


def chrome_async(m, script, args=()):
    m.set_context("chrome")
    try:
        return m.execute_async(
            "const done = arguments[arguments.length - 1]; (async () => {" + script + "})().then("
            "v => done({ok: v}), e => done({error: String(e)}));",
            list(args),
        )
    finally:
        m.set_context("content")


def shot(m, name):
    m.set_context("chrome")
    try:
        (out / f"{name}.png").write_bytes(m.screenshot_png())
    finally:
        m.set_context("content")


session = harness.GeckoProfileSession(name="Pessoal")
results = []
try:
    m = session.start()
    if locale != "pt-BR":
        m.chrome("Services.locale.requestedLocales = [arguments[0]];", [locale])
        m = session.restart()
    print("locale", m.chrome("return Services.locale.appLocaleAsBCP47;"), flush=True)
    server = harness.FixtureServer()
    server.__enter__()
    m.navigate(server.url("/long-page"))  # a page with text, so the page area is not blank
    for preset in ("lateral", "focus", "top"):
        print(chrome_async(m, f"return {LAYOUT}.apply(window, arguments[0]);", [preset]).get("error", ""), flush=True)
        time.sleep(1)
        print(chrome_async(m, f"await SidebarController.show(arguments[0]); return SidebarController.currentID;", [SIDEBAR]), flush=True)
        sizes = ((1366, 768), (1440, 900)) if preset == "lateral" else ((1366, 768),)
        for width, height in sizes:
            m.send("WebDriver:SetWindowRect", {"width": width, "height": height})
            time.sleep(1)
            for dark in (0, 1) if preset == "lateral" else (0,):
                m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                for opposite in (False, True):
                    m.chrome(OPPOSITE, [opposite])
                    time.sleep(1.5)
                    name = f"{locale}-{preset}-{width}x{height}-{'dark' if dark else 'light'}-{'opposite' if opposite else 'today'}"
                    shot(m, name)
                    results.append({"name": name, **m.chrome(MEASURE)})
                    print(results[-1], flush=True)
    # The engine's own panel on the assistant's side, and Imersivo, at 1366 light, lateral.
    chrome_async(m, f"return {LAYOUT}.apply(window, 'lateral');")
    m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
    m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")
    m.chrome(OPPOSITE, [True])
    chrome_async(m, "await SidebarController.show('viewBookmarksSidebar'); return SidebarController.currentID;")
    time.sleep(1.5)
    shot(m, f"{locale}-lateral-bookmarks-opposite")
    results.append({"name": "bookmarks-opposite", **m.chrome(MEASURE)})
    chrome_async(m, "await SidebarController.show(arguments[0]); return 1;", [SIDEBAR])
    # The position pref flips: does the panel follow to the other side of the (now right-hand) tabs?
    m.chrome("Services.prefs.setBoolPref('sidebar.position_start', false);")
    time.sleep(1.5)
    shot(m, f"{locale}-lateral-positionend-opposite")
    results.append({"name": "positionend-opposite", **m.chrome(MEASURE)})
    m.chrome("Services.prefs.setBoolPref('sidebar.position_start', true);")
    time.sleep(1)
    said = chrome_async(m, f"return {LAYOUT}.setImmersive(true);")
    print("immersive", said, flush=True)
    time.sleep(2)
    shot(m, f"{locale}-immersive-opposite")
    results.append({"name": "immersive-opposite", **m.chrome(MEASURE)})
finally:
        m.set_context("content")


def shot(m, name):
    m.set_context("chrome")
    try:
        (out / f"{name}.png").write_bytes(m.screenshot_png())
    finally:
        m.set_context("content")


session = harness.GeckoProfileSession(name="Pessoal")
results = []
try:
    m = session.start()
    if locale != "pt-BR":
        m.chrome("Services.locale.requestedLocales = [arguments[0]];", [locale])
        m = session.restart()
    print("locale", m.chrome("return Services.locale.appLocaleAsBCP47;"), flush=True)
    server = harness.FixtureServer()
    server.__enter__()
    m.navigate(server.url("/long-page"))  # a page with text, so the page area is not blank
    for preset in ("lateral", "focus", "top"):
        print(chrome_async(m, f"return {LAYOUT}.apply(window, arguments[0]);", [preset]).get("error", ""), flush=True)
        time.sleep(1)
        print(chrome_async(m, f"await SidebarController.show(arguments[0]); return SidebarController.currentID;", [SIDEBAR]), flush=True)
        sizes = ((1366, 768), (1440, 900)) if preset == "lateral" else ((1366, 768),)
        for width, height in sizes:
            m.send("WebDriver:SetWindowRect", {"width": width, "height": height})
            time.sleep(1)
            for dark in (0, 1) if preset == "lateral" else (0,):
                m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                for opposite in (False, True):
                    m.chrome(OPPOSITE, [opposite])
                    time.sleep(1.5)
                    name = f"{locale}-{preset}-{width}x{height}-{'dark' if dark else 'light'}-{'opposite' if opposite else 'today'}"
                    shot(m, name)
                    results.append({"name": name, **m.chrome(MEASURE)})
                    print(results[-1], flush=True)
    # The engine's own panel on the assistant's side, and Imersivo, at 1366 light, lateral.
    chrome_async(m, f"return {LAYOUT}.apply(window, 'lateral');")
    m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
    m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")
    m.chrome(OPPOSITE, [True])
    chrome_async(m, "await SidebarController.show('viewBookmarksSidebar'); return SidebarController.currentID;")
    time.sleep(1.5)
    shot(m, f"{locale}-lateral-bookmarks-opposite")
    results.append({"name": "bookmarks-opposite", **m.chrome(MEASURE)})
    chrome_async(m, "await SidebarController.show(arguments[0]); return 1;", [SIDEBAR])
    # The position pref flips: does the panel follow to the other side of the (now right-hand) tabs?
    m.chrome("Services.prefs.setBoolPref('sidebar.position_start', false);")
    time.sleep(1.5)
    shot(m, f"{locale}-lateral-positionend-opposite")
    results.append({"name": "positionend-opposite", **m.chrome(MEASURE)})
    m.chrome("Services.prefs.setBoolPref('sidebar.position_start', true);")
    time.sleep(1)
    said = chrome_async(m, f"return {LAYOUT}.setImmersive(true);")
    print("immersive", said, flush=True)
    time.sleep(2)
    shot(m, f"{locale}-immersive-opposite")
    results.append({"name": "immersive-opposite", **m.chrome(MEASURE)})
    # Resize by the splitter: drag it 80 px toward the page and read the box's width.
    before = m.chrome(MEASURE)
    m.chrome(
        "const s = SidebarController._splitter.getBoundingClientRect(); const x = s.left + s.width / 2, y = s.top + 200;"
        "const u = window.windowUtils; u.sendMouseEvent('mousedown', x, y, 0, 1, 0);"
        "u.sendMouseEvent('mousemove', x - 40, y, 0, 0, 0); u.sendMouseEvent('mousemove', x - 80, y, 0, 0, 0);"
        "u.sendMouseEvent('mouseup', x - 80, y, 0, 1, 0); return true;"
    )
    time.sleep(1)
    results.append({"name": "splitter-drag", "before": before, "after": m.chrome(MEASURE)})
    print(results[-1], flush=True)
finally:
    (out / f"measure-{locale}.json").write_text(json.dumps(results, indent=1))
    session.cleanup()
print("done")
