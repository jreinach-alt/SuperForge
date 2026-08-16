#!/usr/bin/env python3
"""gen_room_assets.py — deterministic BG1 (room) + BG2 (decor) assets.

Emits (byte-identical on re-run, pure integer math):
  bg1_chr.bin  16 tiles x 32 B 4bpp — floor, grout, wall
  bg1_map.bin  32x32 BG1 tilemap words, little-endian
  bg1_pal.bin  16 BGR555 words — CGRAM 32..47 (BG 4bpp palette 2)
  bg2_chr.bin  16 tiles x 32 B 4bpp — one decor motif, rest blank
  bg2_map.bin  32x32 BG2 tilemap words, little-endian
  bg2_pal.bin  16 BGR555 words — CGRAM 48..63 (BG 4bpp palette 3)

Division of labour: BG1 is the room the lantern DIMS (colour-math subtract
outside the window); BG2 is the decor the lantern CLIPS (W12SEL + TMW, so it
is absent outside the window entirely). Two different window mechanisms on
one set of bounds, which is what makes the cross-layer assertion possible —
a single-layer VRAM read cannot tell "BG2 uploaded correctly" from "BG2
visible where it must not be".

BG1 USES NO PALETTE INDEX 0. Index 0 is transparent for a BG layer, so a 0
pixel would punch through to the backdrop and read as a hole in the floor.
BG2 is the opposite: index 0 is the whole point, since the decor must let
BG1 show through everywhere it is not drawn.

DECOR IS ON A REGULAR GRID BY DESIGN. The tests need cells whose screen
position they can compute rather than read back, so a decor tile sits at
every interior cell with col % DECOR_CX == 2 and row % DECOR_CY == 1.
"""
import sys
from pathlib import Path

T = 8                                   # tile side, px
MAP_W = MAP_H = 32                      # 32x32 tilemap
VIS_ROWS = 28                           # 224 px / 8 — the visible rows
BG1_PAL_NUM = 2                         # CGRAM 32..47
BG2_PAL_NUM = 3                         # CGRAM 48..63
DECOR_CX, DECOR_CY = 5, 4               # decor grid period, in cells

# ---- BG1 palette (indices 1..6; 0 is the unusable transparent slot) -------
FLOOR_D, FLOOR_L, GROUT, WALL, WALL_HI, WALL_LO = 1, 2, 3, 4, 5, 6
BG1_COLORS = {
    0: (0, 0, 0),                       # transparent slot: written black
    FLOOR_D: (9, 8, 7),                 # floor, dark stone
    FLOOR_L: (13, 12, 10),              # floor, light stone
    GROUT:   (5, 5, 5),                 # grout line between flagstones
    WALL:    (7, 6, 9),                 # wall face
    WALL_HI: (11, 10, 14),              # wall highlight
    WALL_LO: (3, 3, 4),                 # wall shadow
}
# ---- BG2 palette (index 0 MUST stay transparent) -------------------------
DEC_CORE, DEC_EDGE = 1, 2
BG2_COLORS = {
    0: (0, 0, 0),                       # transparent — never rendered
    DEC_CORE: (12, 31, 31),             # bright cyan: unlike any BG1 colour
    DEC_EDGE: (4, 18, 20),              # its darker rim
}

# tile ids
TL_FLOOR_A, TL_FLOOR_B, TL_WALL, TL_WALL_TOP = 0, 1, 2, 3
TL_BLANK, TL_DECOR = 0, 1


def bgr(r: int, g: int, b: int) -> int:
    assert 0 <= r < 32 and 0 <= g < 32 and 0 <= b < 32, (r, g, b)
    return (b << 10) | (g << 5) | r


def encode_4bpp(pixels: list[int], *, allow_zero: bool, label: str) -> bytes:
    """64 palette indices (row-major) -> one 32-B SNES 4bpp tile.

    Rejects an out-of-range index instead of masking it. Silent bitwise
    quantisation in an asset encoder is a documented trap in this project's
    history (index 5 silently becoming index 1, with no diagnostic and a
    visually plausible result), so the encoder refuses rather than guesses.
    """
    assert len(pixels) == 64, len(pixels)
    lo = 0 if allow_zero else 1
    bad = {p for p in pixels if not lo <= p <= 15}
    assert not bad, (
        f"{label}: palette indices {sorted(bad)} outside {lo}..15 "
        f"(0 is transparent and would show the layer beneath)")
    out = bytearray()
    for lo_plane in (0, 2):
        for y in range(T):
            row = pixels[y * T:(y + 1) * T]
            for plane in (lo_plane, lo_plane + 1):
                byte = 0
                for x, p in enumerate(row):
                    byte |= ((p >> plane) & 1) << (7 - x)
                out.append(byte)
    return bytes(out)


def floor_tile(base: int) -> list[int]:
    """A flagstone: `base` field with a grout line on two edges."""
    px = []
    for y in range(T):
        for x in range(T):
            px.append(GROUT if (x == 0 or y == 0) else base)
    return px


def wall_tile(top: bool) -> list[int]:
    """Wall block. `top` adds a lit cap row so the border reads as masonry."""
    px = []
    for y in range(T):
        for x in range(T):
            if top and y < 2:
                c = WALL_HI
            elif y == T - 1 or x == T - 1:
                c = WALL_LO
            else:
                c = WALL
            px.append(c)
    return px


def decor_tile() -> list[int]:
    """A 6x6 diamond, centred, on a transparent field."""
    px = []
    for y in range(T):
        for x in range(T):
            d = abs(x - 3) + abs(y - 3)         # L1 distance -> diamond
            px.append(DEC_CORE if d <= 1 else DEC_EDGE if d <= 3 else 0)
    return px


def bg1_tiles() -> list[bytes]:
    art = [floor_tile(FLOOR_D), floor_tile(FLOOR_L),
           wall_tile(False), wall_tile(True)]
    blank = [FLOOR_D] * 64                       # spare slots: never mapped
    art += [blank] * (16 - len(art))
    return [encode_4bpp(p, allow_zero=False, label=f"bg1 tile {i}")
            for i, p in enumerate(art)]


def bg2_tiles() -> list[bytes]:
    art = [[0] * 64, decor_tile()]
    art += [[0] * 64] * (16 - len(art))
    return [encode_4bpp(p, allow_zero=True, label=f"bg2 tile {i}")
            for i, p in enumerate(art)]


def is_wall(col: int, row: int) -> bool:
    """The room's border: one cell thick, around the VISIBLE area."""
    return col == 0 or col == MAP_W - 1 or row == 0 or row == VIS_ROWS - 1


def has_decor(col: int, row: int) -> bool:
    return (not is_wall(col, row) and row < VIS_ROWS
            and col % DECOR_CX == 2 and row % DECOR_CY == 1)


# BG map entry bit 13 = the tile's priority bit. BG2 needs it and BG1 must
# not have it, and that is not a style choice — it is what makes the decor
# visible at all. Mode 1's layer order (Mesen2 SnesPpu.cpp:792-804,
# RenderTilemap<layer, bpp, normalPrio, highPrio>) is:
#     BG1 normal 6, high 9   BG2 normal 5, high 8   BG3 normal 1, high 11
#     OBJ 2 / 4 / 7 / 10 by the sprite's own priority field
# and the PPU keeps the pixel with the HIGHER number. So BG2 at normal
# priority (5) loses to BG1's opaque floor (6) everywhere, and the decor
# renders behind the room — invisible, with correct VRAM and a correct
# window. Bit 13 moves BG2 to 8: above BG1's floor, still below the hero
# (10) and the caption (11), which is exactly the stack we want.
BG1_PRIO = 0                            # floor/walls: the bottom layer
BG2_PRIO = 1 << 13                      # decor: above the floor


def tilemap(pal: int, prio: int, pick) -> bytes:
    """32x32 words: priority in bit 13, ppp in bits 10-12, tile id in 0-9."""
    out = bytearray()
    attr = (pal << 10) | prio
    for row in range(MAP_H):
        for col in range(MAP_W):
            word = attr | pick(col, row)
            out += word.to_bytes(2, "little")
    return bytes(out)


def bg1_pick(col: int, row: int) -> int:
    if row >= VIS_ROWS:
        return TL_FLOOR_A                        # off-screen rows: anything
    if is_wall(col, row):
        return TL_WALL_TOP if row == 0 else TL_WALL
    return TL_FLOOR_A if (col + row) & 1 else TL_FLOOR_B


def bg2_pick(col: int, row: int) -> int:
    return TL_DECOR if has_decor(col, row) else TL_BLANK


def palette(colors: dict) -> bytes:
    out = bytearray()
    for i in range(16):
        out += bgr(*colors.get(i, (0, 0, 0))).to_bytes(2, "little")
    return bytes(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_room_assets.py <outdir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "bg1_chr.bin").write_bytes(b"".join(bg1_tiles()))
    (out / "bg2_chr.bin").write_bytes(b"".join(bg2_tiles()))
    (out / "bg1_map.bin").write_bytes(tilemap(BG1_PAL_NUM, BG1_PRIO, bg1_pick))
    (out / "bg2_map.bin").write_bytes(tilemap(BG2_PAL_NUM, BG2_PRIO, bg2_pick))
    (out / "bg1_pal.bin").write_bytes(palette(BG1_COLORS))
    (out / "bg2_pal.bin").write_bytes(palette(BG2_COLORS))
    n = sum(1 for r in range(MAP_H) for c in range(MAP_W) if has_decor(c, r))
    print(f"gen_room_assets: 16+16 tiles, 2 maps, 2 palettes, "
          f"{n} decor cells -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
