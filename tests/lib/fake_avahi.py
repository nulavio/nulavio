"""A stand-in for `busctl` talking to Avahi (NULAVIO_BUSCTL), so browser tests find the test phone
without announcing anything on the real network. NV_FAKE_AVAHI is a JSON file {name: [host, port]}
that tests/lib/phone_link_ref.py fills in."""

FAKE_BUSCTL = """#!{python} -I
import json, os, sys
args = sys.argv[1:]
if "GetVersionString" in args:
    print(json.dumps({{"type": "s", "data": ["avahi (test stand-in)"]}}))
    sys.exit(0)
if "ResolveService" in args:
    name = args[args.index("iisssiu") + 3]
    try:
        names = json.load(open(os.environ["NV_FAKE_AVAHI"]))
    except (OSError, ValueError, KeyError):
        names = {{}}
    if name not in names:
        sys.exit(1)
    host, port = names[name]
    data = [2, 0, name, "_nulavio-nv1._tcp", "local", "phone.local", 0, host, port, [], 13]
    print(json.dumps({{"type": "iissssisqaayu", "data": data}}))
    sys.exit(0)
sys.exit(1)
"""
