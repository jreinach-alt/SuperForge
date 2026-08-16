#!/usr/bin/env python3
"""gen_sprite_game_assets.py — deterministic sprite_game OBJ assets.

Emits (byte-identical on re-run, pure integer math):
  sprg_obj_chr.bin   32 B — ONE 8x8 4bpp tile, every pixel colour index 1
  sprg_obj_pal.bin   64 B — 32 BGR555 words: OBJ palette 0 (index 1 = the
                     player's red) then OBJ palette 1 (index 1 = the dot's
                     yellow)

ONE TILE, TWO PALETTES — and that is the rail, not an economy. The red player
AND the yellow dot are the same `sprite_tile` (eight rows of `$FF,$00` then
eight of `$00,$00` — bitplane 0 all ones, planes 1-3 empty, i.e. an 8x8 block
of colour index 1), coloured apart purely by OAM palette select:
`OBJ_RED = $001F` into OBJ palette 0, `OBJ_YELLOW = $03FF` into OBJ
palette 1. Two independently-coloured sprites over one tile is the whole
lesson. The bytes are DERIVED here from the pixel description rather than
pasted as a byte table, and `test_sprite_game.py` asserts the ROM's OBJ CHR
against the same literal `sprite_tile` bytes and both palettes' index 1
against the colour equates.
"""
import sys
from pathlib import Path

T = 8                                   # tile edge
TRN, BODY = 0, 1
# OBJ_RED = $001F (red 31), OBJ_YELLOW = $03FF
# (red 31 + green 31). 15-bit BGR: %0bbbbbgggggrrrrr.
OBJ_RED = (0 << 10) | (0 << 5) | 31
OBJ_YELLOW = (0 << 10) | (31 << 5) | 31
assert OBJ_RED == 0x001F and OBJ_YELLOW == 0x03FF

# The shared actor tile: a solid 8x8 block of colour index 1.
ART = ["XXXXXXXX"] * T
GLYPH = {".": TRN, "X": BODY}


def encode_4bpp(pixels, label: str) -> bytes:
    """64 palette indices (row-major) -> 32 B SNES 4bpp tile.

    No masking anywhere: an index outside 0..15 is a REFUSAL, not a silently
    quantised pixel — a masked index is a different colour on screen and no
    error anywhere.
    """
    assert len(pixels) == T * T, f"{label}: {len(pixels)} pixels, want {T * T}"
    bad = sorted({p for p in pixels if not 0 <= p <= 15})
    assert not bad, f"{label}: palette indices {bad} do not fit 4bpp"
    lo = bytearray()                    # bitplanes 0+1, interleaved per row
    hi = bytearray()                    # bitplanes 2+3
    for y in range(T):
        row = pixels[y * T:(y + 1) * T]
        planes = []
        for bit in range(4):
            planes.append(sum(((px >> bit) & 1) << (7 - x)
                              for x, px in enumerate(row)))
        lo += bytes((planes[0], planes[1]))
        hi += bytes((planes[2], planes[3]))
    return bytes(lo + hi)


def palette(index1: int) -> bytes:
    """16 BGR555 words: index 0 transparent black, index 1 the actor colour."""
    words = [0x0000] * 16
    words[1] = index1
    return b"".join(w.to_bytes(2, "little") for w in words)


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)

    assert len(ART) == T and all(len(r) == T for r in ART)
    tile = encode_4bpp([GLYPH[ch] for row in ART for ch in row], "actor")
    (out / "sprg_obj_chr.bin").write_bytes(tile)

    (out / "sprg_obj_pal.bin").write_bytes(palette(OBJ_RED)
                                           + palette(OBJ_YELLOW))

    print(f"gen_sprite_game_assets: 1 tile ({len(tile)} B) + 2 palettes "
          f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
