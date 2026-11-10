"""A minimal TrueType font built in memory, for tests that need a font nobody has installed.

``build("Family Name")`` returns the bytes of a valid .ttf with one drawn glyph, mapped to the
letter "m" and two units wide per em, so text measured in this family differs from any fallback.
Standard library only (the repository has no font files and no font tools).
"""

from __future__ import annotations

import struct


def _table_checksum(data: bytes) -> int:
    padded = data + b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF


def _name_table(family: str) -> bytes:
    records = {1: family, 2: "Regular", 3: f"{family} test fixture", 4: family, 6: family.replace(" ", "")}
    strings = b""
    entries = b""
    for name_id, text in sorted(records.items()):
        encoded = text.encode("utf-16-be")
        entries += struct.pack(">6H", 3, 1, 0x409, name_id, len(encoded), len(strings))
        strings += encoded
    return struct.pack(">3H", 0, len(records), 6 + 12 * len(records)) + entries + strings


def build(family: str) -> bytes:
    glyph = struct.pack(">h4h", 1, 50, 0, 900, 700)  # one contour and its bounding box
    glyph += struct.pack(">HH", 3, 0)  # last point of the contour; no instructions
    glyph += bytes([1, 1, 1, 1])  # four on-curve points, coordinates as 16-bit deltas
    glyph += struct.pack(">4h", 50, 850, 0, -850) + struct.pack(">4h", 0, 0, 700, 0)
    tables = {
        b"OS/2": struct.pack(
            ">H3h" + "10h" + "h" + "10s" + "4I" + "4s" + "3H" + "3h" + "2H" + "2I" + "2h" + "3H",
            3, 1250, 400, 5,
            *([0] * 10), 0, b"\0" * 10, 1, 0, 0, 0, b"NULA", 0x40, 0x6D, 0x6D,
            800, -200, 0, 800, 200, 1, 0, 500, 700, 0, 32, 0,
        ),
        b"cmap": struct.pack(">2H", 0, 1) + struct.pack(">2HI", 3, 1, 12)
        + struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0)
        + struct.pack(">2H", 0x6D, 0xFFFF) + struct.pack(">H", 0)
        + struct.pack(">2H", 0x6D, 0xFFFF) + struct.pack(">2H", (1 - 0x6D) & 0xFFFF, 1) + struct.pack(">2H", 0, 0),
        b"glyf": glyph,
        b"head": struct.pack(
            ">2I2IHH2q4hHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0x0003, 1000, 0, 0, 0, 0, 900, 700, 0, 8, 2, 0, 0
        ),
        b"hhea": struct.pack(">I3hH3h3h4hhH", 0x00010000, 800, -200, 0, 2000, 0, 0, 900, 1, 0, 0, 0, 0, 0, 0, 0, 2),
        b"hmtx": struct.pack(">HhHh", 500, 0, 2000, 50),
        b"loca": struct.pack(">3H", 0, 0, len(glyph) // 2),
        b"maxp": struct.pack(">I14H", 0x00010000, 2, 4, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0),
        b"name": _name_table(family),
        b"post": struct.pack(">2I2h5I", 0x00030000, 0, -100, 50, 0, 0, 0, 0, 0),
    }  # fmt: skip
    count = len(tables)
    entry_selector = count.bit_length() - 1
    search_range = 16 << entry_selector
    header = struct.pack(">I4H", 0x00010000, count, search_range, entry_selector, count * 16 - search_range)
    offset = len(header) + 16 * count
    directory = b""
    body = b""
    for tag, data in sorted(tables.items()):
        directory += struct.pack(">4s3I", tag, _table_checksum(data), offset, len(data))
        padded = data + b"\0" * (-len(data) % 4)
        body += padded
        offset += len(padded)
    return header + directory + body
