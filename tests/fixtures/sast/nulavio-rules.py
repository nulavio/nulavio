# ruff: noqa
# Test cases for ci/sast/nulavio-rules.yml (Python rules); never imported or run.
# A line annotated "ruleid" must match the rule named, a line annotated "ok" must not.
#   scripts/security/scan.sh opengrep-rules
# ruff is off for this file: it holds, on purpose, what ruff's S rules also reject.

import asyncio
import http.client
import os
import ssl
import subprocess
import urllib.request

# --- nulavio-py-shell-command

# ruleid: nulavio-py-shell-command
subprocess.run(f"tar -xf {archive}", shell=True, check=True)
# ruleid: nulavio-py-shell-command
subprocess.check_output("uname -a", shell=True)
# ruleid: nulavio-py-shell-command
os.system("rm -rf " + target)
# ruleid: nulavio-py-shell-command
os.popen("ls")
# ruleid: nulavio-py-shell-command
subprocess.getoutput("id")
# ruleid: nulavio-py-shell-command
asyncio.create_subprocess_shell(command)
# ok: nulavio-py-shell-command
subprocess.run(["tar", "-xf", archive], check=True)
# ok: nulavio-py-shell-command
subprocess.run(["tar", "-xf", archive], shell=False, check=True)

# --- nulavio-py-cleartext-request

# ruleid: nulavio-py-cleartext-request
urllib.request.urlopen("http://archive.mozilla.org/pub/firefox/releases/")
# ruleid: nulavio-py-cleartext-request
urllib.request.Request("http://example.org/api/" + path)
# ruleid: nulavio-py-cleartext-request
http.client.HTTPConnection("example.org", 80)
# ok: nulavio-py-cleartext-request
urllib.request.urlopen("https://archive.mozilla.org/pub/firefox/releases/")
# ok: nulavio-py-cleartext-request
urllib.request.urlopen("http://127.0.0.1:8080/status")
# ok: nulavio-py-cleartext-request
urllib.request.Request("http://localhost/" + path)
# ok: nulavio-py-cleartext-request
http.client.HTTPConnection("127.0.0.1", port)

# --- nulavio-py-tls-verification-off

# ruleid: nulavio-py-tls-verification-off
context = ssl._create_unverified_context()
# ruleid: nulavio-py-tls-verification-off
context.check_hostname = False
# ruleid: nulavio-py-tls-verification-off
context.verify_mode = ssl.CERT_NONE
# ruleid: nulavio-py-tls-verification-off
context = ssl.SSLContext()
# ruleid: nulavio-py-tls-verification-off
context = ssl.SSLContext(ssl.PROTOCOL_TLS)
# ruleid: nulavio-py-tls-verification-off
context.minimum_version = ssl.TLSVersion.TLSv1
# ruleid: nulavio-py-tls-verification-off
os.environ["PYTHONHTTPSVERIFY"] = "0"
# ok: nulavio-py-tls-verification-off
context = ssl.create_default_context()
# ok: nulavio-py-tls-verification-off
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
# ok: nulavio-py-tls-verification-off
context.minimum_version = ssl.TLSVersion.TLSv1_2

# --- nulavio-py-secret-in-argv

# ruleid: nulavio-py-secret-in-argv
subprocess.run(["gocryptfs", "-init", cipher_dir, passphrase], check=True)
# ruleid: nulavio-py-secret-in-argv
subprocess.run(["tool", "--key", self.api_key], check=True)
# ruleid: nulavio-py-secret-in-argv
subprocess.run(["tool", f"-token={token}"], check=True)
# ruleid: nulavio-py-secret-in-argv
subprocess.check_call(["tool", "-password=" + value])
# ruleid: nulavio-py-secret-in-argv
os.execvp("tool", ["tool", vault_secret])
# ok: nulavio-py-secret-in-argv
subprocess.run(["gocryptfs", "-init", "-passfile", "/dev/stdin", cipher_dir], input=passphrase, check=True)
# ok: nulavio-py-secret-in-argv
subprocess.run(["gpg", "--passphrase-file", passphrase_file, "--sign", path], check=True)
# ok: nulavio-py-secret-in-argv
subprocess.run(["tool", "--token-path", token_path], check=True)
# ok: nulavio-py-secret-in-argv
os.execvp("tool", ["tool", "--read-key-from-stdin"])

# --- nulavio-py-engine-sandbox-env

# ruleid: nulavio-py-engine-sandbox-env
env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
# ruleid: nulavio-py-engine-sandbox-env
env.setdefault("MOZ_ALLOW_DOWNGRADE", "1")
# ruleid: nulavio-py-engine-sandbox-env
os.putenv("MOZ_MARIONETTE", "1")
# ruleid: nulavio-py-engine-sandbox-env
launch = {"HOME": home, "MOZ_REMOTE_SETTINGS_DEVTOOLS": "1"}
# ok: nulavio-py-engine-sandbox-env
env["MOZ_APP_REMOTINGNAME"] = "nulavio"
# ok: nulavio-py-engine-sandbox-env
launch = {"HOME": home, "MOZ_NO_REMOTE": "1"}
