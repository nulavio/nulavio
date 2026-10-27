"""Nulavio's KRunner plugin (Nulavio Connect P1): a D-Bus runner, started by the session bus on demand.

KRunner (Alt+Space) asks it for matches as the user types:

* an address ("example.org", "https://example.org/x") -> "Open … in Nulavio";
* "nulavio <words>" -> "Search … in Nulavio".

Running a match opens it in Nulavio like a link from any other app, so Smart
Profile Routing decides the profile (docs/adr/0003). Only http(s) addresses;
an argument list, never a shell. Needs Python's GLib bindings (python3-gobject),
used only here. Leaves after five idle minutes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse

from .connect_p1 import KRUNNER_SERVICE

INTERFACE = """<node><interface name="org.kde.krunner1">
  <method name="Actions"><arg type="a(sss)" direction="out"/></method>
  <method name="Match"><arg name="query" type="s" direction="in"/><arg type="a(sssida{sv})" direction="out"/></method>
  <method name="Run"><arg name="matchId" type="s" direction="in"/><arg name="actionId" type="s" direction="in"/></method>
  <method name="Teardown"/>
</interface></node>"""
EXACT, POSSIBLE = 100, 30  # KRunner match types
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}(:\d{1,5})?(/\S*)?$", re.I)
IDLE_SECONDS = 300


def matches(query: str) -> list[tuple]:
    text = query.strip()
    if text.lower().startswith("nulavio ") and len(text) > 8:
        words = text[8:].strip()[:500]
        return [(f"search:{words}", f"Search “{words}” in Nulavio", "nulavio", POSSIBLE, 0.8, {})]
    parts = urllib.parse.urlsplit(text)
    if parts.scheme in ("http", "https") and parts.hostname and " " not in text:
        return [(f"open:{text}", f"Open {text} in Nulavio", "nulavio", EXACT, 0.9, {})]
    if HOST_RE.match(text):
        return [(f"open:https://{text}", f"Open https://{text} in Nulavio", "nulavio", POSSIBLE, 0.7, {})]
    return []


def command(match_id: str) -> list[str] | None:
    kind, _, value = match_id.partition(":")
    browser = os.environ.get("NULAVIO_KRUNNER_COMMAND") or shutil.which("nulavio") or ""
    if not browser:
        return None
    if kind == "open":
        parts = urllib.parse.urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or any(c.isspace() for c in value):
            return None
        return [browser, value]
    if kind == "search" and value and len(value) <= 500:
        return [browser, "--search", value]
    return None


def serve() -> int:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    loop = GLib.MainLoop()
    node = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
    idle = {"source": 0}

    def rearm():
        if idle["source"]:
            GLib.source_remove(idle["source"])
        idle["source"] = GLib.timeout_add_seconds(IDLE_SECONDS, lambda: (loop.quit(), False)[1])

    def on_call(_conn, _sender, _path, _iface, method, params, invocation):
        rearm()
        if method == "Actions":
            invocation.return_value(GLib.Variant("(a(sss))", ([],)))
        elif method == "Match":
            (query,) = params.unpack()
            out = [(i, t, icon, kind, rel, {}) for i, t, icon, kind, rel, _ in matches(query)]
            invocation.return_value(GLib.Variant("(a(sssida{sv}))", (out,)))
        elif method == "Run":
            match_id, _action = params.unpack()
            args = command(match_id)
            if args:
                subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)  # fmt: skip
            invocation.return_value(None)
        else:  # Teardown
            invocation.return_value(None)

    def on_bus(conn, _name):
        conn.register_object("/runner", node.interfaces[0], on_call, None, None)

    Gio.bus_own_name(Gio.BusType.SESSION, KRUNNER_SERVICE, Gio.BusNameOwnerFlags.NONE, on_bus, None, lambda *_: loop.quit())
    rearm()
    loop.run()
    return 0
