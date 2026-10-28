"""Ask an installed Nulavio which system Mozilla directory it reads (patch 0006).

Runs inside the package check containers, as an unprivileged user: a throwaway
profile with Marionette on a random port (test only), one chrome-context read,
quit. Prints the native-messaging system directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])  # tests/lib (marionette.py), mounted read-only
from marionette import Marionette

profile = Path(tempfile.mkdtemp(prefix="nulavio-probe-"))
(profile / "user.js").write_text('user_pref("marionette.port", 0);\nuser_pref("remote.prefs.recommended", false);\n')
engine = subprocess.Popen(
    ["nulavio", "--headless", "--marionette", "--profile", str(profile), "about:blank"],
    # Chrome context for this probe (Firefox 159+ reads only the variable), in the package check container.
    env={**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"},  # nosemgrep: nulavio-py-engine-sandbox-env -- throwaway profile
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
port_file = profile / "MarionetteActivePort"
deadline = time.monotonic() + 90
while not (port_file.exists() and port_file.read_text().strip()):
    if engine.poll() is not None or time.monotonic() > deadline:
        sys.exit("engine did not start")
    time.sleep(0.3)
client = Marionette(int(port_file.read_text().strip())).connect()
client.new_session()
print(client.chrome('return Services.dirsvc.get("XRESysNativeManifests", Ci.nsIFile).path;'))
client.quit()
engine.wait(timeout=30)
