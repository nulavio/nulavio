"""UX7 motion rules, read from the style sheets: what moves waits for "no preference", its time and curve
come from the motion tokens, reduced motion takes the time out without cancelling delayed reveals,
and security cues never move."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEETS = [
    ROOT / "browser" / "shell" / "shared" / f"{name}.css" for name in ("components", "pages", "accessibility", "window-band")
] + [
    ROOT / "browser" / "branding" / "nulavio" / "content" / "theme" / "horizon.css",
    ROOT / "browser" / "startpage" / "startpage.css",
]
MOTION = ("animation", "transition", "animation-duration", "transition-duration", "animation-name")
NO_PREFERENCE = "prefers-reduced-motion: no-preference"
# Animations of 0 s that reveal something after a delay: they show, they do not move.
REVEALS = ("nv-reveal-fallback", "nv-skeleton-in")


def declarations(sheet: Path) -> list[tuple[list[str], str, str]]:
    """(enclosing preludes, property, value) for every declaration, comments removed."""
    text = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
    stack: list[str] = []
    buf = ""
    out = []

    def flush(chunk: str) -> None:
        if ":" in chunk and stack:
            prop, _, value = chunk.partition(":")
            out.append((list(stack), prop.strip(), value.strip()))

    for ch in text:
        if ch == "{":
            stack.append(buf.strip())
            buf = ""
        elif ch == "}":
            if buf.strip():
                flush(buf.strip())
            buf = ""
            if stack:
                stack.pop()
        elif ch == ";":
            flush(buf.strip())
            buf = ""
        else:
            buf += ch
    return out


def motion() -> list[tuple[str, list[str], str, str]]:
    return [(sheet.name, stack, prop, value) for sheet in SHEETS for stack, prop, value in declarations(sheet) if prop in MOTION]


def still(value: str) -> bool:
    """`none`, a 0 s reveal, or a zero time: nothing on screen moves."""
    value = value.replace("!important", "").strip()
    return value in ("none", "0s", "0ms") or (any(name in value for name in REVEALS) and " 0s " in f" {value} ")


class MotionSheetTest(unittest.TestCase):
    def test_the_scan_sees_the_known_motion(self):
        found = {(sheet, prop) for sheet, _, prop, _ in motion()}
        for expected in (("components.css", "transition"), ("pages.css", "animation"), ("horizon.css", "animation")):
            self.assertIn(expected, found)

    def test_every_movement_waits_for_no_preference(self):
        for sheet, stack, prop, value in motion():
            if prop == "animation-name" or still(value):
                continue
            with self.subTest(sheet=sheet, rule=stack[-1][:80], prop=prop):
                self.assertTrue(any(NO_PREFERENCE in prelude for prelude in stack), value)

    def test_durations_and_curves_come_from_tokens(self):
        for sheet, stack, prop, value in motion():
            if still(value) or prop == "animation-name":
                continue
            with self.subTest(sheet=sheet, rule=stack[-1][:80]):
                bare = re.sub(r"var\(--nv-motion-(duration|easing)-[\w-]+\)", "", value)
                bare = re.sub(r"(?<![\d.])0m?s\b", "", bare)  # an explicit zero delay moves nothing
                self.assertNotRegex(bare, r"\d+(\.\d+)?m?s\b", f"a time outside the tokens: {value}")
                self.assertNotIn("cubic-bezier", bare, f"a curve outside the tokens: {value}")
                self.assertNotRegex(bare, r"\bease(-in|-out|-in-out)?\b", f"a curve outside the tokens: {value}")

    def test_reduce_guard_zeroes_time_but_keeps_delayed_reveals(self):
        guard = [
            (prop, value)
            for _, stack, prop, value in [(s.name, *d) for s in SHEETS[2:3] for d in declarations(s)]
            if any("prefers-reduced-motion: reduce" in p for p in stack)
        ]
        props = dict(guard)
        self.assertEqual(props.get("animation-duration"), "0s !important")
        self.assertEqual(props.get("animation-iteration-count"), "1 !important")
        self.assertEqual(props.get("transition-duration"), "0s !important")
        self.assertEqual(props.get("transition-delay"), "0s !important")
        self.assertNotIn("animation", props, "animation: none would cancel the delayed reveals")
        self.assertNotIn("animation-delay", props)

    def test_security_and_reduced_durations_are_zero(self):
        tokens = json.loads((ROOT / "docs" / "brand" / "tokens.json").read_text(encoding="utf-8"))
        self.assertEqual(tokens["motion"]["reduced"]["duration"]["$value"], "0ms")
        self.assertEqual(tokens["security"]["duration"]["$value"], "0ms")
        self.assertEqual(tokens["motion"]["duration"]["spin"]["$value"], "900ms")


if __name__ == "__main__":
    unittest.main()
