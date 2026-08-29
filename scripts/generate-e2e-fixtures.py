from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def fixture_png(index: int, width: int = 360, height: int = 640) -> bytes:
    palettes = [
        ((20, 105, 180), (70, 190, 220)),
        ((25, 135, 84), (120, 205, 115)),
        ((150, 70, 35), (235, 165, 70)),
        ((92, 55, 155), (195, 115, 210)),
        ((165, 45, 80), (245, 125, 145)),
    ]
    top, bottom = palettes[index - 1]
    rows: list[bytes] = []
    for y in range(height):
        blend = y / max(1, height - 1)
        base = tuple(
            round(top[channel] * (1 - blend) + bottom[channel] * blend)
            for channel in range(3)
        )
        row = bytearray([0])
        for x in range(width):
            stripe = 28 if ((x // 45) + (y // 80) + index) % 2 == 0 else 0
            row.extend(min(255, value + stripe) for value in base)
        rows.append(bytes(row))
    raw = b"".join(rows)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        signature
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def main() -> None:
    folder = Path("storage/assets/vinhomes-green-paradise")
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(1, 6):
        (folder / f"fixture-{index:02d}.png").write_bytes(fixture_png(index))


if __name__ == "__main__":
    main()
