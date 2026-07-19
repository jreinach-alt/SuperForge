#!/usr/bin/env python3
"""make_vehicle.py — first-party kart sprite for the racer template.

Hand-authored 16x16 pixel art (rear view: helmet, body, rear tires) upscaled
2x to a 32x32 OBJ frame and encoded to SNES 4bpp planar CHR, laid out on the
hardware's 16-tile VRAM rows (an NxN sprite reads each lower tile row at +16
tile numbers — same blob contract as tools/png2snes.py sprite mode). Sized
for OBSEL size pair 3 (16x16 small / 32x32 large):

    tiles 0-3   (+16/+32/+48 rows)   frame 0 — straight        (32x32 large)
    tiles 4-7   (+16/+32/+48 rows)   frame 1 — lean (H-flip it for the
                                     other steer direction)
    tile  8 (+16 row)                HUD speed-bar tick, lit — an 8x14
                                     outlined bar segment in a 16x16-small
                                     slot (top + bottom subtiles)
    tile  10 (+16 row)               HUD speed-bar tick, dim

Output (committed): vehicle.inc — vehicle_chr (2048-byte blob, 4 VRAM rows),
vehicle_pal (16 BGR555 words, OBJ palette), frame/tile constants.

Regenerate:  python3 templates/racer/assets/make_vehicle.py
(no imports beyond the stdlib; deterministic output)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

# palette index -> RGB (index 0 = transparent, never rendered)
PALETTE = {
    0: (0, 0, 0),
    1: (24, 24, 32),        # outline
    2: (200, 32, 32),       # body red
    3: (255, 96, 48),       # body highlight / lit tick / exhaust glow
    4: (40, 40, 48),        # tires / dim tick
    5: (240, 240, 240),     # helmet white
    6: (128, 16, 24),       # body shadow (lower hull)
    7: (96, 96, 108),       # tire highlight (tread shine)
    8: (72, 120, 208),      # helmet visor blue
}

# 16x16 kart, rear view ('.' = transparent, digits = palette index).
# Shaded + outlined: highlight cowl up top, shadowed hull below, visor band
# on the helmet, tread shine on the outer tire columns, twin exhaust glow.
FRAME0 = [
    "................",
    "......1111......",
    ".....155551.....",
    ".....188881.....",
    "....11555511....",
    "...1233333321...",
    "..123333333321..",
    "1741233333321471",
    "1741223333221471",
    "1741222222221471",
    "1441122222211441",
    "1441166666611441",
    ".11116666661111.",
    "...1131331311...",
    "................",
    "................",
]

# HUD speed-bar tick, 8x14 visible (top subtile + bottom subtile of the
# 16x16-small OAM slot): outlined block, bright fill when lit. Adjacent
# ticks at 8 px spacing join into one segmented, outlined bar.
TICK_LIT_TOP = [
    "11111111",
    "13333331",
    "13333331",
    "13333331",
    "13333331",
    "13333331",
    "13333331",
    "13333331",
]
TICK_LIT_BOT = [
    "13333331",
    "13333331",
    "13333331",
    "13333331",
    "13333331",
    "11111111",
    "........",
    "........",
]
TICK_DIM_TOP = [r.replace("3", "4") for r in TICK_LIT_TOP]
TICK_DIM_BOT = [r.replace("3", "4") for r in TICK_LIT_BOT]


def lean_frame(rows: list[str]) -> list[str]:
    """Banking frame: the upper body (helmet + cowl) slides 1px toward the
    turn while the tires stay planted — cheap but reads as a lean."""
    return [r[1:] + "." if y <= 6 else r for y, r in enumerate(rows)]


def upscale2x(rows: list[str]) -> list[str]:
    """16x16 art -> 32x32 (nearest neighbor; keeps the chunky pixel look)."""
    out = []
    for r in rows:
        wide = "".join(ch * 2 for ch in r)
        out += [wide, wide]
    return out


def encode_tile_4bpp(rows: list[str], ox: int, oy: int) -> bytes:
    """One 8x8 tile at (ox, oy) of a character grid -> 32 bytes SNES 4bpp
    planar: rows 0-7 of [plane0, plane1], then rows 0-7 of [plane2, plane3]."""
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            ch = rows[oy + y][ox + x]
            v = 0 if ch == "." else int(ch)
            assert 0 <= v <= 15
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def bgr555(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def main() -> None:
    for art in (FRAME0,):
        assert len(art) == 16 and all(len(r) == 16 for r in art)
    frame0 = upscale2x(FRAME0)
    frame1 = upscale2x(lean_frame(FRAME0))

    # 64-tile blob (4 VRAM rows x 16 tiles x 32 bytes)
    tiles = [bytes(32)] * 64
    for base, art in ((0, frame0), (4, frame1)):
        for ty in range(4):                              # 32x32 = 4x4 subtiles
            for tx in range(4):
                tiles[base + ty * 16 + tx] = encode_tile_4bpp(art, tx * 8, ty * 8)
    # HUD ticks: top subtile at the OAM tile number, bottom subtile one VRAM
    # row below (+16) — the 16x16-small sprite reads both, giving the 8x14
    # outlined bar segment. Tile numbers 8/10 are unchanged for the template.
    tiles[8] = encode_tile_4bpp(TICK_LIT_TOP, 0, 0)
    tiles[8 + 16] = encode_tile_4bpp(TICK_LIT_BOT, 0, 0)
    tiles[10] = encode_tile_4bpp(TICK_DIM_TOP, 0, 0)
    tiles[10 + 16] = encode_tile_4bpp(TICK_DIM_BOT, 0, 0)
    blob = b"".join(tiles)
    assert len(blob) == 2048

    lines = [
        "; =============================================================================",
        "; vehicle.inc — racer kart OBJ CHR + palette (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: python3 templates/racer/assets/make_vehicle.py",
        "; 2 frames @ 32x32 (straight, lean) + 2 HUD ticks, 4 VRAM tile rows.",
        "; LOAD CONTRACT: upload vehicle_chr at a 16-aligned OBJ tile index; a",
        "; frame's OAM tile = base + vehicle_f<N> (lower rows read at +16/+32/+48).",
        "; Sized for OBSEL size pair 3: 16x16 small / 32x32 large.",
        "; =============================================================================",
        "",
        "vehicle_f0       = $00      ; straight (32x32, OAM size = large)",
        "vehicle_f1       = $04      ; lean (H-flip for the other direction)",
        "VEHICLE_TICK_LIT = $08      ; HUD tick, lit (8x14 outlined bar segment)",
        "VEHICLE_TICK_DIM = $0A      ; HUD tick, dim",
        f"vehicle_chr_bytes = {len(blob)}",
        "",
        "vehicle_chr:",
    ]
    for off in range(0, len(blob), 16):
        chunk = ", ".join(f"${b:02X}" for b in blob[off:off + 16])
        lines.append(f"    .byte {chunk}")
    lines += ["", "vehicle_pal:"]
    for i in range(16):
        word = bgr555(PALETTE[i]) if i in PALETTE else 0
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines.append("")
    (HERE / "vehicle.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'vehicle.inc'}")


if __name__ == "__main__":
    main()
