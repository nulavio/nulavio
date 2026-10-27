"""A stand-in for secret-tool (Secret Service CLI), for tests: items kept in the JSON file NV_FAKE_KEYRING.

Write FAKE_SECRET_TOOL.format(python=sys.executable) to an executable file and point
NULAVIO_SECRET_TOOL at it. Only artificial secrets are ever stored.
"""

FAKE_SECRET_TOOL = """#!{python} -I
import json, os, sys
store = os.environ["NV_FAKE_KEYRING"]
items = json.load(open(store)) if os.path.exists(store) else []
cmd, rest = sys.argv[1], sys.argv[2:]
if cmd == "store":
    rest = rest[1:]
attrs = dict(zip(rest[::2], rest[1::2]))
if cmd == "store":
    items = [i for i in items if i["attrs"] != attrs] + [{{"attrs": attrs, "secret": sys.stdin.read()}}]
elif cmd == "lookup":
    match = [i for i in items if i["attrs"] == attrs]
    if not match:
        sys.exit(1)
    sys.stdout.write(match[0]["secret"])
elif cmd == "clear":
    items = [i for i in items if i["attrs"] != attrs]
open(store, "w").write(json.dumps(items))
"""
