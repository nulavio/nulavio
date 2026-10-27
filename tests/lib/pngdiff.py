"""Minimal PNG decoding and a coarse visual difference, standard library only.

Enough for 8-bit RGB/RGBA screenshots from the engine: it decodes the rows,
samples every `step`-th pixel and reports the mean absolute difference of
grey levels (0 = identical, 255 = opposite), plus the share of sampled pixels
that differ by more than a threshold.
"""

from __future__ import annotations

import struct
import zlib


def decode(data: bytes) -> tuple[int, int, int, list[bytes]]:
    """(width, height, bytes per pixel, rows) of an 8-bit RGB or RGBA PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, width, height, kind = 8, b"", 0, 0, 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        if chunk == b"IHDR":
            width, height, depth, kind = struct.unpack(">IIBB", body[:10])
            if depth != 8 or kind not in (2, 6):
                raise ValueError("only 8-bit RGB/RGBA")
        elif chunk == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    bpp = 4 if kind == 6 else 3
    stride = width * bpp
    rows: list[bytes] = []
    previous = bytearray(stride)
    i = 0
    for _ in range(height):
        kind_filter = raw[i]
        line = bytearray(raw[i + 1 : i + 1 + stride])
        i += 1 + stride
        if kind_filter == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif kind_filter == 2:
            for x in range(stride):
                line[x] = (line[x] + previous[x]) & 255
        elif kind_filter == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + previous[x]) >> 1)) & 255
        elif kind_filter == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = previous[x]
                c = previous[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        previous = line
    return width, height, bpp, rows


def difference(first: bytes, second: bytes, step: int = 6, threshold: int = 40) -> dict:
    """Mean grey-level difference and share of clearly different samples between two screenshots."""
    w1, h1, b1, rows1 = decode(first)
    w2, h2, b2, rows2 = decode(second)
    width, height = min(w1, w2), min(h1, h2)
    total = changed = samples = 0
    for y in range(0, height, step):
        r1, r2 = rows1[y], rows2[y]
        for x in range(0, width, step):
            g1 = (r1[x * b1] * 3 + r1[x * b1 + 1] * 6 + r1[x * b1 + 2]) // 10
            g2 = (r2[x * b2] * 3 + r2[x * b2 + 1] * 6 + r2[x * b2 + 2]) // 10
            d = abs(g1 - g2)
            total += d
            changed += d > threshold
            samples += 1
    return {"mean": round(total / max(samples, 1), 2), "changed": round(changed / max(samples, 1), 3)}
