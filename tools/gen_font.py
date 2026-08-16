#!/usr/bin/env python3
"""gen_font.py — superforge: GNU-Unifont .hex -> raw SNES 2bpp font binary.

Reads the standard `.hex` glyph format and emits a raw 1536-byte `.bin` for
`.incbin` rather than a ca65 `.byte` block. 96 glyphs
($20-$7F), 16 bytes each, rows interleaved BP0/BP1 with both planes equal so
glyph pixels land on color 3 of the selected BG palette. Missing codepoints
become blank tiles. Deterministic: byte-identical output from the same input.

Usage: gen_font.py vendor/fonts/unscii-8.hex out/font_2bpp.bin
"""
import sys
from pathlib import Path

LO, HI = 0x20, 0x7F                 # 96 tiles


def parse_hex(path: Path) -> dict[int, list[int]]:
    glyphs: dict[int, list[int]] = {}
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        code, _, data = ln.partition(":")
        cp = int(code, 16)
        rows = [int(data[i:i + 2], 16) for i in range(0, len(data), 2)]
        if len(rows) != 8:
            raise SystemExit(f"glyph ${cp:04X}: {len(rows)} rows, want 8")
        glyphs[cp] = rows
    return glyphs


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    glyphs = parse_hex(Path(sys.argv[1]))
    out = bytearray()
    for cp in range(LO, HI + 1):
        for row in glyphs.get(cp, [0] * 8):
            out += bytes((row, row))    # BP0 == BP1 -> pixel color 3
    assert len(out) == 96 * 16
    dst = Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    print(f"font: {len(out)} B -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
