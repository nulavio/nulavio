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
