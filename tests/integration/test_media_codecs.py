"""Sound in MP4 plays in the Nulavio build (#377).

The engine has its own decoders for Opus, Vorbis, FLAC, VP8, VP9 and AV1. For AAC, the audio most video sites
send, and for any audio inside an MP4 file, it loads the system's codec library (libavcodec) at run time. On a
system without that library those streams do not play, and nothing says why: the first 160.0-0.6 release run
stopped on it. Nulavio's packages recommend the library and `nulavio doctor` names it when it is missing; this
test holds that the place the release is tested in has it and that the build plays through it.

The fixture, tests/fixtures/media/sine-aac.mp4, is three seconds of a 440 Hz tone, AAC-LC, mono, made with:

    ffmpeg -f lavfi -i sine=frequency=440:duration=3 -c:a aac -b:a 32k -ac 1 -map_metadata -1 \\
        -fflags +bitexact -flags:a +bitexact -movflags +faststart sine-aac.mp4

No network. Nulavio build only: pull requests test distribution Firefox, whose image is not what Nulavio's
packages install into.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "media" / "sine-aac.mp4"
AAC = 'audio/mp4; codecs="mp4a.40.2"'
MISSING = (
    "the system's codec library (libavcodec) is missing or the engine could not load it: "
    "`nulavio doctor` says what to install (Fedora: libavcodec-free; Debian and Ubuntu: libavcodec-extra)"
)


class MediaServer(harness.FixtureServer):
    def route(self, raw: str):
        if raw.partition("?")[0] == "/media/sine-aac.mp4":
            return FIXTURE.read_bytes(), "audio/mp4", {}
        return super().route(raw)


# Plays the file in an <audio> element, muted, and resolves with what the page saw after two seconds of it.
PLAY = """
const [url, type] = arguments;
const done = arguments[arguments.length - 1];
(async () => {
  const media = document.createElement("audio");
  media.muted = true;
  document.body.append(media);
  const errors = [];
  media.addEventListener("error", () => errors.push(`media ${media.error?.code}: ${media.error?.message}`));
  const can = media.canPlayType(type);
  media.src = url;
  await media.play().catch(error => errors.push(String(error)));
  const until = Date.now() + 20000;
  while (!errors.length && media.currentTime < 2 && Date.now() < until) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  // The decoded sound itself: a tone, so the samples are not all zero.
  let peak = null;
  try {
    const data = await (await fetch(url)).arrayBuffer();
    const decoded = await new window.OfflineAudioContext(1, 44100, 44100).decodeAudioData(data);
    peak = decoded.getChannelData(0).reduce((most, sample) => Math.max(most, Math.abs(sample)), 0);
  } catch (error) {
    errors.push(`decodeAudioData: ${error}`);
  }
  return { can, errors, currentTime: media.currentTime, duration: media.duration, peak };
})().then(done, error => done({ error: String(error) }));
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build, where its packages install it (NULAVIO_ENGINE)")
class MediaCodecsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MediaServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def test_01_an_aac_stream_in_mp4_plays(self):
        self.m.navigate(self.server.url("/page/media"))
        result = self.m.execute_async(PLAY, [self.server.url("/media/sine-aac.mp4"), AAC])
        print(f"AAC in MP4: {result}", file=sys.stderr)
        self.assertNotIn("error", result, result)
        self.assertEqual(result["can"], "probably", f"{MISSING}. The page was told: {result}")
        self.assertEqual(result["errors"], [], f"{MISSING}. {result}")
        self.assertGreaterEqual(result["currentTime"], 2.0, f"the stream did not play: {result}")
        self.assertAlmostEqual(result["duration"], 3.0, delta=0.2)
        self.assertGreater(result["peak"], 0.05, f"the decoded sound is silence: {result}")


if __name__ == "__main__":
    unittest.main()
