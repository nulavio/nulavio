/* Test cases for ci/sast/nulavio-rules.yml (JavaScript rules); never loaded.
   A line annotated "ruleid" must match the rule named, a line annotated "ok" must not.
     scripts/security/scan.sh opengrep-rules */

// --- nulavio-js-html-sink

// ruleid: nulavio-js-html-sink
row.innerHTML = `<b>${profileName}</b>`;
// ruleid: nulavio-js-html-sink
list.innerHTML += item;
// ruleid: nulavio-js-html-sink
panel.insertAdjacentHTML("beforeend", markup);
// ruleid: nulavio-js-html-sink
frame.srcdoc = page;
// ruleid: nulavio-js-html-sink
document.write(text);
// ruleid: nulavio-js-html-sink
link.setAttribute("onclick", handler);
// ruleid: nulavio-js-html-sink
node.setHTMLUnsafe(markup);
// ok: nulavio-js-html-sink
row.textContent = profileName;
// ok: nulavio-js-html-sink
list.replaceChildren();
// ok: nulavio-js-html-sink
link.setAttribute("href", url);

// --- nulavio-js-dynamic-code

// ruleid: nulavio-js-dynamic-code
eval(source);
// ruleid: nulavio-js-dynamic-code
const run = new Function("a", body);
// ruleid: nulavio-js-dynamic-code
setTimeout("refresh()", 100);
// ruleid: nulavio-js-dynamic-code
Services.scriptloader.loadSubScript(url, scope);
// ruleid: nulavio-js-dynamic-code
const mod = ChromeUtils.importESModule(moduleUrl);
// ruleid: nulavio-js-dynamic-code
const lazy = ChromeUtils.importESModule(`resource://nulavio/${name}.sys.mjs`);
// ok: nulavio-js-dynamic-code
const { NulavioRouting } = ChromeUtils.importESModule("resource://nulavio/NulavioRouting.sys.mjs");
// ok: nulavio-js-dynamic-code
setTimeout(refresh, 100);

// --- nulavio-js-weakening-pref

// ruleid: nulavio-js-weakening-pref
user_pref("security.sandbox.content.level", 2);
// ruleid: nulavio-js-weakening-pref
pref("marionette.port", 2828);
// ruleid: nulavio-js-weakening-pref
Services.prefs.setStringPref("services.settings.server", serverUrl);
// ruleid: nulavio-js-weakening-pref
Services.prefs.clearUserPref("remote.enabled");
// ruleid: nulavio-js-weakening-pref
user_pref("xpinstall.signatures.required", false);
// ruleid: nulavio-js-weakening-pref
pref("browser.safebrowsing.malware.enabled", false, sticky);
// ruleid: nulavio-js-weakening-pref
Services.prefs.getDefaultBranch("").setBoolPref("fission.autostart", false);
// ruleid: nulavio-js-weakening-pref
pref("devtools.chrome.enabled", true);
// ruleid: nulavio-js-weakening-pref
lockPref("extensions.experiments.enabled", true);
// ruleid: nulavio-js-weakening-pref
user_pref("security.tls.version.min", 1);
// ruleid: nulavio-js-weakening-pref
Services.prefs.setIntPref("security.cert_pinning.enforcement_level", 0);
// ruleid: nulavio-js-weakening-pref
user_pref("devtools.debugger.prompt-connection", false);
// ok: nulavio-js-weakening-pref
user_pref("xpinstall.signatures.required", true);
// ok: nulavio-js-weakening-pref
pref("devtools.debugger.prompt-connection", true, sticky);
// ok: nulavio-js-weakening-pref
pref("devtools.chrome.enabled", false, sticky);
// ok: nulavio-js-weakening-pref
pref("devtools.debugger.remote-enabled", false, sticky);
// ok: nulavio-js-weakening-pref
user_pref("security.tls.version.min", 3);
// ok: nulavio-js-weakening-pref
Services.prefs.setIntPref("security.cert_pinning.enforcement_level", 2);
// ok: nulavio-js-weakening-pref
pref("browser.safebrowsing.downloads.remote.enabled", false);
// ok: nulavio-js-weakening-pref
Services.prefs.getBoolPref("security.sandbox.content.level");

// --- nulavio-js-cleartext-request

// ruleid: nulavio-js-cleartext-request
fetch("http://example.org/v1/models");
// ruleid: nulavio-js-cleartext-request
const socket = new WebSocket("ws://example.org/link");
// ruleid: nulavio-js-cleartext-request
request.open("GET", "http://example.org/");
// ok: nulavio-js-cleartext-request
fetch("https://example.org/v1/models");
// ok: nulavio-js-cleartext-request
fetch("http://127.0.0.1:11434/api/tags");
// ok: nulavio-js-cleartext-request
const local = new WebSocket("ws://localhost:8765/");
