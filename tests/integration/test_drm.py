"""Protected media plays in the Nulavio build once DRM is on (#222).

No account and no network: ClearKey, the engine's built-in key system, plays a
local stream encrypted with a key made for the test, through Encrypted Media
Extensions and Media Source Extensions, the path a streaming service takes. It
shows that Nulavio's prefs and sandbox leave that path working. DRM stays off in
a new profile (ADR 0002): the test checks first that no page gets Widevine and
none is installed while it is off, then turns it on as a person does in Settings.

The fixtures in tests/fixtures/eme/ are three seconds of a test pattern (VP9)
and of a tone (Opus), fragmented MP4, encrypted with CENC (AES-CTR):

    ffmpeg -f lavfi -i testsrc=size=96x64:rate=15:duration=3 -c:v libvpx-vp9 -b:v 60k -g 15 -pix_fmt yuv420p -an \\
        -encryption_scheme cenc-aes-ctr -encryption_key <KEY> -encryption_kid <KID> \\
        -movflags frag_keyframe+empty_moov+default_base_moof clearkey-vp9.mp4
    ffmpeg -f lavfi -i sine=frequency=440:duration=3 -c:a libopus -b:a 24k (same encryption and flags) clearkey-opus.mp4

with KEY and KID below (artificial, test-only).
"""

from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eme"
KID = bytes.fromhex("6e756c6176696f2d636c6561726b6579")  # "nulavio-clearkey"
KEY = bytes.fromhex("6e756c6176696f2d746573742d6b6579")  # "nulavio-test-key"
STREAMS = {
    "video": ("clearkey-vp9.mp4", 'video/mp4; codecs="vp09.00.10.08"'),
    "audio": ("clearkey-opus.mp4", 'audio/mp4; codecs="opus"'),
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class EmeServer(harness.FixtureServer):
    def route(self, raw: str):
        path = raw.partition("?")[0]
        if path.startswith("/eme/") and Path(path).name in {name for name, _ in STREAMS.values()}:
            return (FIXTURES / Path(path).name).read_bytes(), "video/mp4", {}
        return super().route(raw)


# Plays one stream through MSE + EME with ClearKey; resolves with what the page saw.
PLAY = """
const [url, type, kind, license, kid] = arguments;
const done = arguments[arguments.length - 1];
(async () => {
  const media = document.createElement(kind);
  media.muted = true;
  document.body.append(media);
  const errors = [];
  media.addEventListener("error", () => errors.push(`media ${media.error?.code}: ${media.error?.message}`));
  const config = [{ initDataTypes: ["cenc", "keyids"],
                    [kind === "video" ? "videoCapabilities" : "audioCapabilities"]: [{ contentType: type }] }];
  const access = await navigator.requestMediaKeySystemAccess("org.w3.clearkey", config);
  const keys = await access.createMediaKeys();
  await media.setMediaKeys(keys);
  // The fixtures carry no pssh box (ffmpeg writes none), so no "encrypted" event comes: the session asks for
  // the key by its id ("keyids" init data, which ClearKey takes) before the media is appended.
  let licensed = false, encrypted = 0;
  media.addEventListener("encrypted", () => encrypted++);
  const session = keys.createSession();
  const answered = new Promise(resolve => session.addEventListener("message", () => {
    session.update(new TextEncoder().encode(license)).then(() => { licensed = true; resolve(); },
                                                           e => { errors.push(`update: ${e}`); resolve(); });
  }, { once: true }));
  await session.generateRequest("keyids", new TextEncoder().encode(JSON.stringify({ kids: [kid] })));
  await answered;
  const source = new MediaSource();
  media.src = URL.createObjectURL(source);
  const step = (what, promise) => Promise.race([promise, new Promise((_, no) => setTimeout(() => no(what), 8000))]);
  await step("sourceopen", new Promise(r => source.addEventListener("sourceopen", r, { once: true })));
  const buffer = source.addSourceBuffer(type);
  buffer.appendBuffer(await (await fetch(url)).arrayBuffer());
  await step("updateend", new Promise(r => buffer.addEventListener("updateend", r, { once: true })));
  source.endOfStream();
  // Not awaited: play() settles only once playback starts, which an unusable key would hold off for ever.
  media.play().catch(e => errors.push(`play: ${e}`));
  const started = Date.now();
  while (Date.now() - started < 12000 && !media.ended && media.currentTime < 1.5 && !errors.length) {
    await new Promise(r => setTimeout(r, 100));
  }
  const frames = kind === "video" ? media.getVideoPlaybackQuality().totalVideoFrames : null;
  return { licensed, encrypted, currentTime: media.currentTime, readyState: media.readyState, frames, errors,
           keySystem: access.keySystem };
})().then(done, e => done({ error: String(e) }));
"""

# Whether a page gets a key system: [ClearKey, Widevine].
ACCESS = """
const done = arguments[arguments.length - 1];
const ask = system => navigator.requestMediaKeySystemAccess(system,
  [{ initDataTypes: ["cenc"], videoCapabilities: [{ contentType: 'video/mp4; codecs="vp09.00.10.08"' }] }])
  .then(() => "granted", e => e.name);
Promise.all([ask("org.w3.clearkey"), ask("com.widevine.alpha")]).then(done, e => done(String(e)));
"""

# The engine's notification bar on a tab whose page asked for DRM while it is off, and the checkbox in Settings.
DRM_BAR = """
const n = gBrowser.getNotificationBox(gBrowser.selectedBrowser).getNotificationWithValue("drmContentDisabled");
if (!n) return null;
const label = b => b.label || b.textContent.trim() || b.getAttribute("aria-label") || "";
return { text: n.messageText?.textContent ?? "", buttons: [...n.buttonContainer.querySelectorAll("button")].map(label) };
"""
DRM_SETTING = """
const box = document.getElementById("playDRMContent");
// The page's navigation entry for that pane, never the pane itself (which carries the same category).
const named = '[view="paneTabsBrowsing"], [value="paneTabsBrowsing"], [data-category="paneTabsBrowsing"]';
const nav = [...document.querySelectorAll(named)]
  .find(e => e.localName !== "setting-pane" && !e.closest("setting-pane, .pane-container"));
if (!box) return null;
const entry = nav ? `${nav.localName}:${nav.checkVisibility()}` : null;
return { shown: box.checkVisibility(), label: box.label, checked: box.checked, nav: entry };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class ProtectedMediaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = EmeServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.license = '{"keys":[{"kty":"oct","kid":"' + b64url(KID) + '","k":"' + b64url(KEY) + '"}],"type":"temporary"}'

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def test_01_off_in_a_new_profile_no_closed_module_for_pages(self):
        """DRM off: no page gets Widevine, and none is installed. ClearKey, the engine's own open key system,
        downloads nothing and the engine leaves it to pages either way (measured: granted with DRM off)."""
        self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('media.eme.enabled');"))
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('media.gmp-widevinecdm.version', '');"), "")
        self.m.navigate(self.server.url("/page/eme-off"))
        clearkey, widevine = self.m.execute_async(ACCESS)
        print(f"DRM off: clearkey {clearkey}, widevine {widevine}", file=sys.stderr)
        self.assertNotEqual(widevine, "granted", "a page reached Widevine with DRM off")

    def test_02_on_a_clearkey_stream_plays(self):
        # As "Play DRM-controlled content" in Settings does.
        self.m.chrome("Services.prefs.setBoolPref('media.eme.enabled', true);")
        try:
            for kind, (name, mime) in STREAMS.items():
                with self.subTest(kind=kind):
                    self.m.navigate(self.server.url(f"/page/eme-{kind}"))
                    result = self.m.execute_async(PLAY, [self.server.url(f"/eme/{name}"), mime, kind, self.license, b64url(KID)])
                    print(f"{kind}: {result}", file=sys.stderr)
                    self.assertNotIn("error", result, result)
                    self.assertEqual(result["errors"], [], result)
                    self.assertTrue(result["licensed"], f"the key was never given to the CDM: {result}")
                    self.assertGreaterEqual(result["currentTime"], 1.0, f"the stream did not play: {result}")
                    if kind == "video":
                        self.assertGreater(result["frames"], 0, f"no frame was decoded: {result}")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('media.eme.enabled');")

    def test_02b_with_a_wrong_key_nothing_plays(self):
        """The control: the fixtures are really encrypted, so a key that is not theirs plays nothing."""
        wrong = '{"keys":[{"kty":"oct","kid":"' + b64url(KID) + '","k":"' + b64url(bytes(16)) + '"}],"type":"temporary"}'
        self.m.chrome("Services.prefs.setBoolPref('media.eme.enabled', true);")
        try:
            name, mime = STREAMS["video"]
            self.m.navigate(self.server.url("/page/eme-wrong-key"))
            result = self.m.execute_async(PLAY, [self.server.url(f"/eme/{name}"), mime, "video", wrong, b64url(KID)])
            print(f"wrong key: {result}", file=sys.stderr)
            self.assertLess(result.get("currentTime", 0), 1.0, f"a stream played with a wrong key: {result}")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('media.eme.enabled');")

    def test_03_clearing_a_sites_data_removes_what_its_key_system_stored(self):
        """A persistent licence is stored with the profile, by site. "Clear cookies and site data" for that site
        (SiteDataManager.remove, what Settings and the site panel call) removes it."""
        self.m.chrome("Services.prefs.setBoolPref('media.eme.enabled', true);")
        # ClearKey keeps a licence only with the engine's test switch; Widevine's are kept the same way, per site.
        self.m.chrome("Services.prefs.setBoolPref('media.clearkey.persistent-license.enabled', true);")
        persistent = self.license.replace('"temporary"', '"persistent-license"')
        try:
            self.m.navigate(self.server.url("/page/eme-store"))
            stored = self.m.execute_async(STORE, [persistent, b64url(KID)])
            self.assertNotIn("error", stored, stored)
            files = lambda: self.m.chrome(GMP_FILES)  # noqa: E731
            self.assertTrue(harness.wait_until(lambda: files(), 15), "nothing was stored for the licence")
            before = files()
            print(f"stored: {stored}, files: {before}", file=sys.stderr)
            self.m.set_context("chrome")
            try:
                cleared = self.m.execute_async(
                    "const done = arguments[arguments.length - 1];"
                    "const { SiteDataManager } = ChromeUtils.importESModule('resource:///modules/SiteDataManager.sys.mjs');"
                    "SiteDataManager.remove('127.0.0.1').then(() => done(true), e => done(String(e)));"
                )
            finally:
                self.m.set_context("content")
            self.assertEqual(cleared, True)
            gone = harness.wait_until(lambda: not files(), 15)
            self.assertTrue(gone, f"left after clearing the site's data: {files()}")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('media.clearkey.persistent-license.enabled');")
            self.m.chrome("Services.prefs.clearUserPref('media.eme.enabled');")

    def test_05_with_drm_off_a_page_that_asks_gets_the_engines_bar_and_settings_has_the_switch(self):
        """#222, item 5: the two ways a person turns DRM on are reachable in Nulavio. A page that asks for Widevine with
        DRM off gets the engine's notification bar with its button; Settings has the engine's own checkbox, which is
        the pref. In the profile's language (pt-BR in this suite)."""
        self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('media.eme.enabled');"))
        self.m.navigate(self.server.url("/page/eme-asks"))
        self.m.execute_async(ACCESS)
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(DRM_BAR), 10), "no notification bar for a page that asks for DRM"
        )

        # The bar's words arrive after the bar (the engine translates them in a second step), the button's last.
        def worded():
            bar = self.m.chrome(DRM_BAR) or {"text": "", "buttons": []}
            return bar["text"].strip() and any(label.strip() for label in bar["buttons"])

        harness.wait_until(worded, 10)
        shown = self.m.chrome(DRM_BAR)
        print(f"bar: {shown}", file=sys.stderr)
        self.assertTrue(shown["text"].strip() and any(label.strip() for label in shown["buttons"]), shown)
        self.m.navigate("about:preferences#tabsBrowsing")  # Firefox 160 keeps it under "Tabs and browsing"
        self.assertTrue(
            harness.wait_until(lambda: (self.m.execute(DRM_SETTING) or {}).get("shown"), 10), self.m.execute(DRM_SETTING)
        )
        state = self.m.execute(DRM_SETTING)
        print(f"settings: {state}", file=sys.stderr)
        self.assertTrue(state["label"].strip(), state)
        self.assertTrue(str(state["nav"]).endswith(":true"), f"the settings page lists no way to that pane: {state}")
        self.assertFalse(state["checked"])
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('media.eme.enabled');")
        self.m.execute("document.getElementById('playDRMContent').click();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return Services.prefs.getBoolPref('media.eme.enabled');"), 5))

    def long_async(self, script: str, args: list, seconds: int):
        """An async script that may take minutes (a download): the script and socket timeouts raised for it alone."""
        timeouts = self.m.send("WebDriver:GetTimeouts")
        before = timeouts.get("value", timeouts)["script"]
        self.m.send("WebDriver:SetTimeouts", {"script": seconds * 1000})
        socket_timeout = self.m.timeout
        self.m._sock.settimeout(seconds + 30)
        try:
            return self.m.execute_async(script, args)
        finally:
            self.m._sock.settimeout(socket_timeout)
            self.m.send("WebDriver:SetTimeouts", {"script": before})

    @unittest.skipUnless(
        os.environ.get("NULAVIO_NETWORK_TESTS") == "1", "downloads Widevine and plays from Google (NULAVIO_NETWORK_TESTS=1)"
    )
    def test_04_with_drm_on_widevine_installs_and_a_public_test_stream_plays(self):
        """#222, item 2: DRM turned on as Settings does, the engine installs Widevine from Mozilla's list, and the
        Shaka Player demo's Widevine stream ("Angel One", H.264 in fragmented MP4, Google's test licence server) plays
        past its clear start with a licence, and stops there without one."""
        self.m.chrome("Services.prefs.setBoolPref('media.eme.enabled', true);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('media.eme.enabled');")
        self.m.set_context("chrome")
        try:
            installed = self.long_async(INSTALL_WIDEVINE, [], 300)
        finally:
            self.m.set_context("content")
        print(f"Widevine: {installed}", file=sys.stderr)
        self.assertNotIn("error", installed, installed)
        version = lambda: self.m.chrome("return Services.prefs.getStringPref('media.gmp-widevinecdm.version', '');")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: version(), 120), "Widevine was not installed")
        codec = 'video/mp4; codecs="avc1.42c01e"'
        # The control: the stream's first seconds are not encrypted (the packager's "clear lead"), so playing them
        # proves nothing about Widevine. Without a licence the film plays that start and then waits for a key.
        self.m.navigate(self.server.url("/page/eme-widevine"))
        without = self.long_async(WIDEVINE_PLAY, [WIDEVINE_STREAM, codec, WIDEVINE_LICENCE, False, WIDEVINE_PAST_CLEAR], 120)
        print(f"Widevine {version()}, no licence: {without}", file=sys.stderr)
        self.assertNotIn("error", without, without)
        self.assertFalse(without["licensed"])
        self.assertTrue(without["waitedForKey"], f"the stream never waited for a key: is it encrypted? {without}")
        self.assertLess(without["currentTime"], WIDEVINE_PAST_CLEAR, f"the stream played without a licence: {without}")

        self.m.navigate(self.server.url("/page/eme-widevine"))
        result = self.long_async(WIDEVINE_PLAY, [WIDEVINE_STREAM, codec, WIDEVINE_LICENCE, True, WIDEVINE_PAST_CLEAR], 180)
        print(f"Widevine {version()}: {result}", file=sys.stderr)
        self.assertNotIn("error", result, result)
        self.assertEqual(result["keySystem"], "com.widevine.alpha")
        self.assertEqual(result["errors"], [], result)
        self.assertTrue(result["licensed"], f"no licence reached the CDM: {result}")
        self.assertGreaterEqual(result["currentTime"], WIDEVINE_PAST_CLEAR, f"the encrypted part did not play: {result}")
        self.assertGreater(result["frames"], without["frames"], result)


# #222, item 2: Widevine from the engine's own list (what turning DRM on starts), installed now instead of at the
# next periodic check. Resolves with what was installed.
INSTALL_WIDEVINE = """
const done = arguments[arguments.length - 1];
(async () => {
  const { GMPInstallManager } = ChromeUtils.importESModule("resource://gre/modules/GMPInstallManager.sys.mjs");
  const manager = new GMPInstallManager();
  const found = await manager.checkForAddons();
  const widevine = (found.addons ?? []).find(addon => addon.id === "gmp-widevinecdm");
  if (!widevine) return { error: `not in the list: ${(found.addons ?? []).map(a => a.id)}` };
  await manager.installAddon(widevine);
  return { version: widevine.version };
})().then(done, e => done({ error: String(e) }));
"""
# The Shaka Player demo's public Widevine assets and licence server (no account): "Angel One", 144p H.264 in
# fragmented MP4 (the CDM decodes it itself), its first part.
WIDEVINE_STREAM = "https://storage.googleapis.com/shaka-demo-assets/angel-one-widevine/v-0144p-0100k-libx264.mp4"
WIDEVINE_LICENCE = "https://cwip-shaka-proxy.appspot.com/no_auth"
# Seconds of the film that must play: past its clear start (measured: without a licence it stops at 7.8 s).
WIDEVINE_PAST_CLEAR = 12
WIDEVINE_PLAY = """
const [url, type, licence, answer, until] = arguments;
const done = arguments[arguments.length - 1];
(async () => {
  const media = document.createElement("video");
  media.muted = true;
  document.body.append(media);
  const errors = [];
  media.addEventListener("error", () => errors.push(`media ${media.error?.code}: ${media.error?.message}`));
  const access = await navigator.requestMediaKeySystemAccess("com.widevine.alpha",
    [{ initDataTypes: ["cenc"], videoCapabilities: [{ contentType: type }] }]);
  const keys = await access.createMediaKeys();
  await media.setMediaKeys(keys);
  let licensed = false;
  let waitedForKey = false;
  media.addEventListener("waitingforkey", () => { waitedForKey = true; });
  // The stream carries its key id: the engine says "encrypted", and the licence comes from the server.
  media.addEventListener("encrypted", event => {
    const session = keys.createSession();
    session.addEventListener("message", async message => {
      if (!answer) return;  // the control: the CDM's request is never sent, so it gets no key
      let status = "no answer";
      try {
        const answer = await fetch(licence, { method: "POST", body: message.message });
        status = `${answer.status} ${answer.headers.get("content-type")}`;
        await session.update(await answer.arrayBuffer());
        licensed = true;
      } catch (e) {
        errors.push(`licence (${message.messageType}, ${status}): ${e.name}: ${e.message}`);
      }
    });
    session.generateRequest(event.initDataType, event.initData).catch(e => errors.push(`request: ${e}`));
  }, { once: true });
  const source = new MediaSource();
  media.src = URL.createObjectURL(source);
  await new Promise(r => source.addEventListener("sourceopen", r, { once: true }));
  const buffer = source.addSourceBuffer(type);
  // The first 400 kB (about half a minute at 144p): enough to play, not the whole film.
  buffer.appendBuffer(await (await fetch(url, { headers: { Range: "bytes=0-399999" } })).arrayBuffer());
  await new Promise(r => buffer.addEventListener("updateend", r, { once: true }));
  media.play().catch(e => errors.push(`play: ${e}`));
  // Until it has played `until` seconds, or stopped moving for eight (waiting for a key), or 90 s.
  const started = Date.now();
  let last = -1, moved = Date.now();
  while (Date.now() - started < 90000 && media.currentTime < until && !errors.length) {
    if (media.currentTime !== last) { last = media.currentTime; moved = Date.now(); }
    else if (Date.now() - moved > 8000) break;
    await new Promise(r => setTimeout(r, 200));
  }
  return { licensed, waitedForKey, currentTime: media.currentTime, readyState: media.readyState,
           frames: media.getVideoPlaybackQuality().totalVideoFrames, errors, keySystem: access.keySystem };
})().then(done, e => done({ error: String(e) }));
"""

# A persistent-license session: created, given its key, closed (what stays is on disk).
STORE = """
const [license, kid] = arguments;
const done = arguments[arguments.length - 1];
(async () => {
  const access = await navigator.requestMediaKeySystemAccess("org.w3.clearkey", [{ initDataTypes: ["keyids"],
    persistentState: "required", sessionTypes: ["persistent-license"],
    videoCapabilities: [{ contentType: 'video/mp4; codecs="vp09.00.10.08"' }] }]);
  const keys = await access.createMediaKeys();
  const session = keys.createSession("persistent-license");
  const answered = new Promise((resolve, reject) => session.addEventListener("message",
    () => session.update(new TextEncoder().encode(license)).then(resolve, reject), { once: true }));
  await session.generateRequest("keyids", new TextEncoder().encode(JSON.stringify({ kids: [kid] })));
  await answered;
  const id = session.sessionId;
  await session.close();
  return { sessionId: id };
})().then(done, e => done({ error: String(e) }));
"""

# Files under the profile's media-plugin storage (gmp*), relative to the profile.
GMP_FILES = """
const profile = Services.dirsvc.get("ProfD", Ci.nsIFile);
const out = [];
const walk = (dir, rel) => {
  for (const entry of dir.directoryEntries) {
    const path = rel ? `${rel}/${entry.leafName}` : entry.leafName;
    if (entry.isDirectory()) { walk(entry, path); } else { out.push(path); }
  }
};
for (const entry of profile.directoryEntries) {
  if (entry.leafName.startsWith("gmp") && entry.isDirectory()) { walk(entry, entry.leafName); }
}
return out.filter(path => path.includes("storage") || path.includes("clearkey"));
"""

if __name__ == "__main__":
    unittest.main()
