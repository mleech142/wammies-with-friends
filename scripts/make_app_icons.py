"""
Draws the app's home-screen icons (static/img/icons): an orange cube, the dice in the header, on the app's dark
background, at the sizes phones ask for. Standard library only (zlib PNGs, 4x4 supersampled).

Run: python scripts/make_app_icons.py
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'src' / 'combat_sim' / 'static' / 'img' / 'icons'
BACKGROUND = (0x23, 0x23, 0x1a)  # --bg-primary
TOP = (0xf2, 0x9a, 0x62)  # The accent, lit
LEFT = (0xe8, 0x72, 0x2f)  # --accent
RIGHT = (0xb5, 0x55, 0x1f)  # The accent, shaded
SIZES = {'icon-192.png': 192, 'icon-512.png': 512, 'apple-touch-icon.png': 180}
CUBE = 0.30  # The cube's radius as a share of the icon: inside the middle 80% that maskable icons keep


def faces(size):
    """The cube's three faces as polygons in pixels: top, left, right."""
    cx, cy, r = size / 2, size / 2, size * CUBE
    corner = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in (-90, -30, 30, 90, 150, 210)]
    top, upper_right, lower_right, bottom, lower_left, upper_left = corner
    centre = (cx, cy)
    return [([top, upper_right, centre, upper_left], TOP),
            ([upper_left, centre, bottom, lower_left], LEFT),
            ([centre, upper_right, lower_right, bottom], RIGHT)]


def inside(polygon, x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def pixels(size, samples=4):
    shapes = faces(size)
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            total = [0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    x, y = px + (sx + 0.5) / samples, py + (sy + 0.5) / samples
                    colour = next((c for poly, c in shapes if inside(poly, x, y)), BACKGROUND)
                    for i in range(3):
                        total[i] += colour[i]
            row += bytes(round(t / samples ** 2) for t in total)
        rows.append(bytes(row))
    return rows


def png(rows, size):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\x00' + row for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        (OUT / name).write_bytes(png(pixels(size), size))
        print('wrote', OUT / name)


if __name__ == '__main__':
    main()
