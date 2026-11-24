#!/usr/bin/env python3
"""What the per-site audio noise costs a page that renders sound offline (#79, ADR 0019).

    NULAVIO_ENGINE=<build>/nulavio/nulavio python3 -I scripts/perf/audio_noise_cost.py [--seconds 10 60] [--runs 15] [--worklet]

In one session of the build, a page on a local site renders stereo sound at 44.1 kHz with an OfflineAudioContext
(an oscillator through a compressor, a different pitch each time) and times startRendering() until its buffer
is returned. Each length is measured with the build's default protections and again with the audio noise alone
turned off (the engine's set with -AudioRandomization), in turns, so a machine that slows down slows both. The
noise is one pass over the returned samples, on the page's main thread, after the rendering.

--worklet (#406, engine patch 0016) puts an AudioWorklet in the graph that reads the same sound as two channels.
Its inputs get the noise on the rendering thread, one block of 128 samples at a time, so the difference is then
that pass and the returned buffer's together; compare it with a run without the flag. The table's last line says
how many channels the worklet read.

Prints a table of medians. The page's clock is the engine's protected one (1 ms steps).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import harness  # noqa: E402

OVERRIDES = "privacy.fingerprintingProtection.overrides"
TARGET = "AudioRandomization"
RENDER = """
const done = arguments[arguments.length - 1];
const [seconds, pitch, worklet] = arguments;
(async () => {
  const context = new window.OfflineAudioContext(2, 44100 * seconds, 44100);
  const oscillator = context.createOscillator();
  oscillator.type = "triangle";
  oscillator.frequency.value = pitch;
  const compressor = context.createDynamicsCompressor();
  oscillator.connect(compressor);
  compressor.connect(context.destination);
  let channels = null;
  if (worklet) {
    const code = "registerProcessor('reader', class extends AudioWorkletProcessor {" +
      " process(inputs) { let sum = 0; for (const channel of inputs[0]) sum += channel[0]; this.sum = sum;" +
      " if (inputs[0].length && !this.told) { this.told = true; this.port.postMessage(inputs[0].length); } return true; } });";
    const blob = new window.Blob([code], { type: "text/javascript" });
    await context.audioWorklet.addModule(window.URL.createObjectURL(blob));
    // Two channels whatever the sound has: the compressor passes on one for one oscillator.
    const options = { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2] };
    Object.assign(options, { channelCount: 2, channelCountMode: "explicit" });
    const node = new window.AudioWorkletNode(context, "reader", options);
    channels = new Promise(resolve => { node.port.onmessage = event => resolve(event.data); });
    compressor.connect(node);
    node.connect(context.destination);
  }
  oscillator.start(0);
  const before = window.performance.now();
  const buffer = await context.startRendering();
  const took = window.performance.now() - before;
  const read = channels && (await Promise.race([channels, new Promise(resolve => window.setTimeout(resolve, 5000, 0))]));
  return { ms: took, length: buffer.length, channels: read };
})().then(done, error => done({ error: String(error) }));
"""
KNOWN = f"""
const {{ RFPHelper }} = ChromeUtils.importESModule("resource://gre/modules/RFPHelper.sys.mjs");
return "{TARGET}" in RFPHelper.getTargets();
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=int, nargs="+", default=[10, 60], help="lengths of sound to render")
    parser.add_argument("--runs", type=int, default=15, help="renderings per length and side")
    parser.add_argument("--worklet", action="store_true", help="an AudioWorklet in the graph reads its inputs (patch 0016)")
    args = parser.parse_args(argv)
    if not os.environ.get("NULAVIO_ENGINE"):
        parser.error("NULAVIO_ENGINE names the build to measure")
    with harness.FixtureServer() as server:
        session = harness.GeckoProfileSession(name="Pessoal")
        try:
            m = session.start()
            strict = "return Services.prefs.getStringPref('browser.contentblocking.category') === 'strict';"
            if not harness.wait_until(lambda: m.chrome(strict), 30):
                raise SystemExit("the profile never reached the Strict category")
            if not m.chrome(KNOWN):
                raise SystemExit(f"this engine has no {TARGET} target (patch 0012): nothing to measure")
            default = m.chrome(f"return Services.prefs.getDefaultBranch('').getStringPref('{OVERRIDES}');")
            sides = {"with the noise": None, "without": f"{default},-{TARGET}"}
            times: dict[tuple[int, str], list[float]] = {}
            read: set[int | None] = set()
            pitch = 440
            for seconds in args.seconds:
                for _ in range(args.runs):
                    pitch += 1
                    for side, value in sides.items():
                        if value is None:
                            m.chrome(f"Services.prefs.clearUserPref('{OVERRIDES}');")
                        else:
                            m.chrome(f"Services.prefs.setStringPref('{OVERRIDES}', arguments[0]);", [value])
                        m.navigate(server.url(f"/page/audio-{pitch}-{len(side)}"))  # a new page: it reads the set as it is now
                        m.set_context("content")
                        result = m.execute_async(RENDER, [seconds, pitch, args.worklet])
                        if "error" in result:
                            raise SystemExit(f"rendering failed: {result['error']}")
                        times.setdefault((seconds, side), []).append(result["ms"])
                        read.add(result.get("channels"))
        finally:
            session.cleanup()
    print(f"{'sound':>8}  {'samples':>11}  {'with the noise':>15}  {'without':>9}  {'difference':>11}")
    for seconds in args.seconds:
        on = statistics.median(times[(seconds, "with the noise")])
        off = statistics.median(times[(seconds, "without")])
        print(f"{seconds:>6} s  {2 * 44100 * seconds:>11,}  {on:>12.0f} ms  {off:>6.0f} ms  {on - off:>+8.0f} ms")
    graph = "an oscillator through a compressor"
    if args.worklet:
        graph += f", read by a worklet too (channels read: {sorted(read, key=str)})"
    print(f"{graph}; medians of {args.runs} renderings a side; the page's clock moves in 1 ms steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
