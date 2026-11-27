#!/usr/bin/env python3
"""Cut the landing's still pictures of the recorded scenes from the frames of the same capture (#173).

    python3 -I scripts/site/scene_stills.py <recordings dir>

``<recordings dir>`` is what the capture step of scripts/site/record_site.py wrote (one directory for each
scene and language, with ``timeline.json`` and the frames as PNG). A recording's own poster is its last
frame, the whole window made small: its band cannot be read on the page, and the scene whose title is the
password prompt showed the window after it. So, for each recording in ``site/assets/clips/manifest.json``:

* ``<scene>-<locale>-still.webp`` and ``-still-narrow.webp``: the frame that shows what the scene's title
  says, cut towards the top left of the window so that the band is read without help (the narrow one is a
  smaller cut for a phone). For ``protected-unlocks`` that frame is the unlock page with the password typed
  (the timeline's ``highlight``), cut around the page's card;
* ``<scene>-<locale>-detail.webp``: the band of the window the scene ends in, at the capture's own scale.

Nothing is drawn or put together: a still is one rectangle of one frame, without the cursor the videos get
afterwards. The frames are not in the repository, so ``stills.json`` says which frame of which recording
each still is, at what time of the video it is on screen, and its rectangle; the script refuses frames whose
timeline is not the capture the manifest describes (its time and the recording script's blob).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CLIPS = ROOT / "site" / "assets" / "clips"
BUDGET = 150_000  # a still is part of the page's first view of a scene
WINDOW = {"wide": (0, 0, 800, 500), "narrow": (0, 0, 448, 280)}  # x, y, w, h in CSS px of the 1280x800 window
DETAIL = (0, 0, 384, 44)  # the band, which shares its row with the start of the toolbar
DETAIL_OWN_ROW = (0, 0, 384, 27)  # where a long cue gives the band a row to itself
CUTS = {
    "profile-opens": {"frame": "poster", **WINDOW},
    "link-routed": {"frame": "poster", **WINDOW, "detail": DETAIL_OWN_ROW},
    # The unlock page's card is centred in the window: the wide cut keeps the window's title above it (the
    # page tells the reader to check it), the narrow one is the card from the profile's name to the button.
    "protected-unlocks": {"frame": "highlight", "wide": (225, 0, 800, 500), "narrow": (452, 234, 448, 272)},
}


def frame_at(timeline: dict, t: float) -> dict:
    """The frame on screen at ``t``: the last one captured at or before it."""
    return max((f for f in timeline["frames"] if f["t"] <= t), key=lambda f: f["t"])


def cut(frame: Path, box: tuple, scale: float, lossless: bool) -> tuple[bytes, tuple[int, int]]:
    x, y, w, h = box
    image = Image.open(frame).convert("RGB").crop(tuple(round(v * scale) for v in (x, y, x + w, y + h)))
    out = io.BytesIO()
    if lossless:
        image.save(out, "WEBP", lossless=True, quality=100, method=6)
    else:
        image.save(out, "WEBP", quality=84, method=6)
    return out.getvalue(), image.size


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    frames_root = Path(argv[0])
    manifest = json.loads((CLIPS / "manifest.json").read_text(encoding="utf-8"))
    stills: dict[str, dict] = {}
    written: dict[str, bytes] = {}
    for key, clip in manifest["recordings"].items():
        src = frames_root / key
        timeline = json.loads((src / "timeline.json").read_text(encoding="utf-8"))
        same = (timeline["captured"], timeline["script_blob"]) == (clip["capture"]["utc"], clip["capture"]["script_blob"])
        if not same or timeline["buildid"] != clip["capture"]["buildid"]:
            raise SystemExit(f"{key}: these frames are not the capture the manifest describes")
        spec = CUTS[clip["scene"]]
        last = next(f for f in timeline["frames"] if f["file"] == timeline["poster"])
        shown = last if spec["frame"] == "poster" else frame_at(timeline, timeline[spec["frame"]])
        for suffix, frame, box, lossless in (
            ("still", shown, spec["wide"], False),
            ("still-narrow", shown, spec["narrow"], False),
            ("detail", last, spec.get("detail", DETAIL), True),
        ):
            name = f"{key}-{suffix}.webp"
            data, size = cut(src / frame["file"], box, timeline["scale"], lossless)
            if len(data) > BUDGET:
                raise SystemExit(f"{name}: {len(data)} bytes, over the budget of {BUDGET}")
            written[name] = data
            stills[name] = {
                "recording": key,
                "frame": frame["file"],
                "t": frame["t"],
                "crop_css": dict(zip("xywh", box, strict=True)),
                "scale": timeline["scale"],
                "px": list(size),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    record = {
        "schema": 1,
        "script": "scripts/site/scene_stills.py",
        "source": "frames of the captures that manifest.json describes (same capture time, build and recording script),"
        " as captured: before the cursor and the click ripples are drawn",
        "edits": ["one rectangle of one frame; nothing drawn, nothing put together"],
        "encoders": {"still": "Pillow WebP q84", "detail": "Pillow WebP lossless"},
        "budget_bytes_per_file": BUDGET,
        "stills": stills,
    }
    for name, data in written.items():
        (CLIPS / name).write_bytes(data)
    (CLIPS / "stills.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(written)} stills, {sum(map(len, written.values())) // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
