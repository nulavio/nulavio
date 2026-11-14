"""Calls work with Nulavio's prefs: the WebRTC baseline, no account and no network (#221).

A local page gets a camera and a microphone (the engine's fake devices, a test-only pref; the site's
permission given as a person gives it), connects two RTCPeerConnections to each other on this
computer, and audio and video flow between them. Asking to share the screen shows the engine's
prompt (nothing is shared without it). Nulavio's own WebRTC pref, `media.peerconnection.ice.
default_address_only` (only the default route's address offered to peers), is on while this runs:
the test pins that it keeps calls working, and reports which candidate types were gathered.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PAGE = (
    "<!doctype html><title>webrtc</title>"
    "<button id=share type=button>Share</button><p id=state>idle</p>"
    "<script>"
    "document.getElementById('share').addEventListener('click', () => {"
    " window.shared = navigator.mediaDevices.getDisplayMedia({video: true})"
    "  .then(s => { s.getTracks().forEach(t => t.stop()); return 'granted'; }, e => e.name);"
    "});"
    "</script>"
)


class WebrtcServer(harness.FixtureServer):
    def route(self, raw: str):
        if raw.partition("?")[0] == "/webrtc":
            return PAGE.encode(), "text/html; charset=utf-8", {}
        return super().route(raw)


# Two peer connections on this computer, the first sending the camera and microphone to the second.
CALL = """
const done = arguments[arguments.length - 1];
(async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  const a = new RTCPeerConnection(), b = new RTCPeerConnection();
  const types = new Set();
  a.addEventListener("icecandidate", e => {
    if (e.candidate) {
      if (e.candidate.type) types.add(e.candidate.type);
      b.addIceCandidate(e.candidate);
    }
  });
  b.addEventListener("icecandidate", e => { if (e.candidate) { a.addIceCandidate(e.candidate); } });
  stream.getTracks().forEach(track => a.addTrack(track, stream));
  const received = new Promise(resolve => b.addEventListener("track", e => resolve(e.track.kind)));
  await a.setLocalDescription(await a.createOffer());
  await b.setRemoteDescription(a.localDescription);
  await b.setLocalDescription(await b.createAnswer());
  await a.setRemoteDescription(b.localDescription);
  const until = async (test, ms) => {
    const end = Date.now() + ms;
    while (!test() && Date.now() < end) await new Promise(r => setTimeout(r, 100));
    return test();
  };
  await until(() => a.connectionState === "connected" && b.connectionState === "connected", 15000);
  await received;
  await new Promise(r => setTimeout(r, 3000));  // let media flow
  const inbound = {};
  (await b.getStats()).forEach(s => {
    if (s.type === "inbound-rtp") {
      inbound[s.kind] = { packets: s.packetsReceived, bytes: s.bytesReceived, frames: s.framesDecoded ?? null };
    }
  });
  const out = { a: a.connectionState, b: b.connectionState, inbound, candidates: [...types].sort(),
                tracks: stream.getTracks().map(t => t.kind).sort() };
  stream.getTracks().forEach(t => t.stop());
  a.close(); b.close();
  return out;
})().then(done, e => done({ error: String(e) }));
"""

PROMPT = """
const b = gBrowser.selectedBrowser;
const n = PopupNotifications.getNotification("webRTC-shareDevices", b);
return n ? { shown: true, id: n.id } : { shown: false };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class WebrtcBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = WebrtcServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def test_01_nulavios_webrtc_pref_is_on(self):
        on = self.m.chrome("return Services.prefs.getBoolPref('media.peerconnection.ice.default_address_only');")
        self.assertTrue(on)
        self.assertTrue(self.m.chrome("return Services.prefs.getBoolPref('media.peerconnection.enabled');"))

    def test_02_a_call_on_this_computer_carries_audio_and_video(self):
        # The engine's fake camera and microphone (test-only); the site's permission as a person gives it.
        self.m.chrome("Services.prefs.setBoolPref('media.navigator.streams.fake', true);")
        self.m.chrome(
            "const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(arguments[0]);"
            "for (const kind of ['camera', 'microphone']) Services.perms.addFromPrincipal(p, kind, Services.perms.ALLOW_ACTION);",
            [self.server.url("/").rstrip("/")],
        )
        try:
            self.m.navigate(self.server.url("/webrtc"))
            result = self.m.execute_async(CALL)
            print(f"call: {result}", file=sys.stderr)
            self.assertNotIn("error", result, result)
            self.assertEqual((result["a"], result["b"]), ("connected", "connected"), result)
            self.assertEqual(result["tracks"], ["audio", "video"])
            for kind in ("audio", "video"):
                self.assertGreater(
                    result["inbound"].get(kind, {}).get("packets", 0), 0, f"no {kind} reached the other side: {result}"
                )
            self.assertGreater(result["inbound"]["video"]["frames"] or 0, 0, f"no video frame decoded: {result}")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('media.navigator.streams.fake');")
            self.m.chrome("Services.perms.removeAll();")

    def test_03_sharing_the_screen_asks_first(self):
        self.m.navigate(self.server.url("/webrtc"))
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#share")})  # a real click: user activation
        shown = harness.wait_until(lambda: self.m.chrome(PROMPT)["shown"], 10)
        self.assertTrue(shown, "no prompt before sharing the screen")
        # "Não permitir": the prompt's first secondary action, as a person's click on it.
        self.m.chrome(
            "const n = PopupNotifications.getNotification('webRTC-shareDevices', gBrowser.selectedBrowser);"
            "n.secondaryActions[0].callback({});"
        )
        answer = self.m.execute_async(
            "const done = arguments[arguments.length - 1];"
            "Promise.race([window.shared, new Promise(r => setTimeout(() => r('pending'), 10000))])"
            ".then(done, e => done(String(e)));"
        )
        print(f"screen: {answer}", file=sys.stderr)
        self.assertNotIn(answer, ("granted", "pending"), "the screen was shared, or the page was never answered")


if __name__ == "__main__":
    unittest.main()
