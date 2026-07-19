#!/usr/bin/env python3
"""make_hero.py — the m7_dungeon hero OBJ, PROCEDURALLY generated (no pack).

Gallery-polish: the rail is a top-down rotating-floor crawler (the hero sits
screen-centred while the world spins under them), so the hero must read from
ABOVE-BEHIND — head + shoulders + a feet hint, NOT a side profile. This authors
that hero from scratch as a 16x16 index grid: a top-down KNIGHT — crested helm,
broad pauldrons, a ridged backplate, greaves + sabatons — so it honours the
Wave-D knight while fixing the perspective (the old asset was a side-view pack
sprite in a top-down world). stdlib-only; deterministic; no third-party source, so
the provenance regen is just this script.

The palette is deliberately BRIGHT + DESATURATED steel/bone (max-min small) so it
stays distinct from the cool flagstone floor, the warm brick walls, the warm slime
enemy, and the gold goal — the Wave-D colour-band discrimination the rail's tests
rely on (the hero reads grey/steel, never warm). Rendered tones (SNES 5-bit
expansion): mid steel (156,148,148) + bone (239,231,222) are the body; a near-black
cool outline + a mid-dark shade give depth.

Emits hero.inc in the shape main.asm consumes (HERO_TILE / hero_chr / HERO_CHR_BYTES
/ hero_pal / HERO_PAL_COUNT) — the 18-tile OBJ upload where a 16x16 sprite is the
PPU quad {0,1,16,17} and tiles 2..15 are zero-filled, so the ROM's CHR/pal load
path is unchanged.

Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_hero.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# OBJ palette 0 — steel knight, bright + desaturated (stays out of every warm/cool
# terrain band). index: 0 transparent, 1 outline, 2 steel body, 3 bone highlight,
# 4 plate shade.
PAL = [
    (0, 0, 0),          # 0 transparent
    (49, 49, 66),       # 1 dark cool outline / seams / boot soles
    (156, 148, 148),    # 2 mid steel — armour body
    (239, 231, 222),    # 3 bone highlight — top-lit crest / pauldrons
    (99, 99, 123),      # 4 mid-dark cool shade — plate shade / folds
]


def _row(off: int, pat: str) -> str:
    """A 16-wide index row: `pat` (hex digits) placed at column `off`, 0-padded."""
    s = "0" * off + pat
    s = s + "0" * (16 - len(s))
    assert len(s) == 16, (off, pat, len(s))
    return s


# 16x16 top-down knight (above-behind). Mid steel meets the floor directly at the
# sides (contrast is enough); the dark brow line under the helm reads as a visor.
HERO_ROWS = [
    _row(0,  ""),                 # 0
    _row(6,  "3333"),             # 1  helm crown, top-lit
    _row(5,  "223322"),           # 2  helm dome: bright crest, mid sides
    _row(5,  "223322"),           # 3  helm: crest ridge continues
    _row(5,  "222222"),           # 4  helm mid body
    _row(5,  "111111"),           # 5  visor / brow line — helm front edge
    _row(2,  "133333333331"),     # 6  PAULDRONS widest, bright armour tops
    _row(1,  "13222222222231"),   # 7  pauldron mass, bright outer caps
    _row(3,  "1222332221"),       # 8  backplate top, centre ridge begins
    _row(4,  "12433421"),         # 9  backplate: bright ridge, shaded flanks
    _row(4,  "12233221"),         # 10 backplate mid
    _row(5,  "123321"),           # 11 waist (narrower)
    _row(5,  "122221"),           # 12 tassets / lower plate
    _row(5,  "120021"),           # 13 greaves split (gap = two legs)
    _row(5,  "120021"),           # 14 greaves
    _row(5,  "110011"),           # 15 sabatons (boots)
]


def bgr555(rgb) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def encode_tile_4bpp(rows, ox: int, oy: int) -> bytes:
    """8x8 sub-grid at (ox,oy) of `rows` -> 32 bytes SNES 4bpp planar."""
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = int(rows[oy + y][ox + x], 16)
            assert 0 <= v <= 15, v
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def build_chr(rows) -> bytes:
    """18-tile OBJ blob: TL/TR/BL/BR at PPU-quad indices 0/1/16/17, rest zero (the
    16x16 upload main.asm's sf_load_obj_chr expects)."""
    tiles = [bytes(32)] * 18
    tiles[0] = encode_tile_4bpp(rows, 0, 0)    # TL
    tiles[1] = encode_tile_4bpp(rows, 8, 0)    # TR
    tiles[16] = encode_tile_4bpp(rows, 0, 8)   # BL
    tiles[17] = encode_tile_4bpp(rows, 8, 8)   # BR
    return b"".join(tiles)


def build_inc() -> str:
    assert len(HERO_ROWS) == 16 and all(len(r) == 16 for r in HERO_ROWS)
    blob = build_chr(HERO_ROWS)
    lines = [
        "; hero.inc — GENERATED (make_hero.py); DO NOT EDIT BY HAND.",
        "; Procedural top-down KNIGHT (above-behind): crested helm, pauldrons, greaves.",
        "; Bright desaturated steel/bone — stays out of the warm/cool terrain bands.",
        "; original kit art (no pack source); CC0.",
        "HERO_TILE = 0",
        "hero_chr:",
    ]
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    lines.append(f"HERO_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("hero_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("HERO_PAL_COUNT = 16")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (HERE / "hero.inc").write_text(build_inc())
    print("wrote hero.inc (procedural top-down knight)")


if __name__ == "__main__":
    main()
