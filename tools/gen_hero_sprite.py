#!/usr/bin/env python3
"""gen_hero_sprite.py — deterministic room-hero OBJ assets.

Emits (byte-identical on re-run, pure integer math):
  hero_chr.bin  1024 B — 32 tiles x 32 B 4bpp: a 16-tile-wide OBJ grid row
                pair with the 16x16 hero in tiles 0, 1, 16, 17 (the PPU
                reads 16x16 sprites at N, N+1, N+16, N+17), the
                visit-pip in tile 2 (an 8x8 lamp dot for room_logic's
                hud_pips row — rides the same blob + hero_up upload, so
                the byte count and the DMA are unchanged), rest empty
  hero_pal.bin  32 B — 16 BGR555 words, OBJ palette 0 (index 0 transparent)

The hero is the lantern-bearer: a small hooded figure holding a light. He is
deliberately the brightest thing in the room and he is deliberately NOT dimmed
by the window — CGADSUB's OBJ bit is clear, and colour math on OBJ applies
only to palettes 4-7 anyway (SnesPpu.cpp:962), while this is palette 0.
"""
import sys
from pathlib import Path

T = 8
SPRITE = 16                             # 16x16
GRID_W = 16                             # OBJ tiles per VRAM grid row
TILES = 32                              # one grid row pair

TRN, CLOAK, CLOAK_HI, SKIN, LAMP, GLOW, BOOT = 0, 1, 2, 3, 4, 5, 6
PALETTE = {
    TRN:      (0, 0, 0),
    CLOAK:    (6, 5, 14),               # deep indigo cloak
    CLOAK_HI: (11, 10, 22),             # its lit side
    SKIN:     (22, 18, 16),
    LAMP:     (31, 31, 20),             # the lantern flame
    GLOW:     (31, 24, 6),              # its warm halo
    BOOT:     (4, 4, 6),
}

# 16 rows x 16 cols. '.'=transparent  c=cloak  C=cloak-lit  s=skin
# l=lamp  g=glow  b=boot
ART = [
    "................",
    ".....cccc.......",
    "....cCCCCc......",
    "....cCssCc..gg..",
    "....cCssCc.gllg.",
    "....cCCCCc.gllg.",
    "...cCCCCCCc.gg..",
    "...cCCCCCCcg....",
    "..cCCCCCCCCc....",
    "..cCCCCCCCCc....",
    "..cCCCCCCCCc....",
    "..cCCCCCCCCc....",
    "...cCCCCCCc.....",
    "...cCCCCCCc.....",
    "...bb....bb.....",
    "...bb....bb.....",
]
GLYPH = {".": TRN, "c": CLOAK, "C": CLOAK_HI, "s": SKIN,
         "l": LAMP, "g": GLOW, "b": BOOT}

# The visit pip (tile 2): a little lamp dot in the hero's own flame colours.
# Deliberately NOT pure white — the caption tests count exact-$7FFF pixels
# and the pips sit near the caption band.
PIP_ART = [
    "........",
    "...gg...",
    "..gllg..",
    ".gllllg.",
    ".gllllg.",
    "..gllg..",
    "...gg...",
    "...bb...",
]


def bgr(r: int, g: int, b: int) -> int:
    assert 0 <= r < 32 and 0 <= g < 32 and 0 <= b < 32, (r, g, b)
    return (b << 10) | (g << 5) | r


def encode_4bpp(pixels: list[int], label: str) -> bytes:
    """64 palette indices -> one 32-B SNES 4bpp tile. Refuses, never masks."""
    assert len(pixels) == 64, len(pixels)
    bad = {p for p in pixels if not 0 <= p <= 15}
    assert not bad, f"{label}: palette indices {sorted(bad)} outside 0..15"
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


def hero_pixels() -> list[list[int]]:
    assert len(ART) == SPRITE, len(ART)
    for i, r in enumerate(ART):
        assert len(r) == SPRITE, (i, len(r))
    grid = [[GLYPH[ch] for ch in row] for row in ART]
    # split 16x16 into the four 8x8 quadrants the PPU reads
    quads = []
    for qy in (0, 1):
        for qx in (0, 1):
            px = []
            for y in range(T):
                for x in range(T):
                    px.append(grid[qy * T + y][qx * T + x])
            quads.append(px)
    return quads                        # TL, TR, BL, BR


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_hero_sprite.py <outdir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tl, tr, bl, br = hero_pixels()
    blank = encode_4bpp([TRN] * 64, "blank")
    tiles = [blank] * TILES
    # PPU 16x16 read order: N, N+1 (top row), N+GRID_W, N+GRID_W+1 (bottom)
    tiles[0] = encode_4bpp(tl, "hero TL")
    tiles[1] = encode_4bpp(tr, "hero TR")
    tiles[GRID_W] = encode_4bpp(bl, "hero BL")
    tiles[GRID_W + 1] = encode_4bpp(br, "hero BR")
    assert len(PIP_ART) == T and all(len(r) == T for r in PIP_ART)
    tiles[2] = encode_4bpp([GLYPH[ch] for row in PIP_ART for ch in row],
                           "visit pip")
    (out / "hero_chr.bin").write_bytes(b"".join(tiles))
    pal = bytearray()
    for i in range(16):
        pal += bgr(*PALETTE.get(i, (0, 0, 0))).to_bytes(2, "little")
    (out / "hero_pal.bin").write_bytes(bytes(pal))
    print(f"gen_hero_sprite: {TILES} tiles (hero at 0,1,{GRID_W},"
          f"{GRID_W + 1}), 16 colours -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
