#!/usr/bin/env python3
"""gen_hud_assets.py — deterministic hud_game OBJ assets.

Emits (byte-identical on re-run, pure integer math):
  hud_obj_chr.bin   32 B — ONE 8x8 4bpp tile, every pixel colour index 1
  hud_obj_pal.bin   32 B — 16 BGR555 words, OBJ palette 0 (index 0 transparent,
                    index 1 the player's red)

WHY IT IS A SOLID SQUARE, and why that is not a placeholder. This rail's
subject is the TEXT HUD — the digits, the labels, the VWF layout. The player
is a marker for the HUD to read out, so it is exactly eight rows of `$FF,$00`
followed by eight of `$00,$00`: bitplane 0 all ones, bitplanes 1-3 all zero,
an 8x8 block of colour index 1, with `OBJ_RED = $001F` in that index. Anything
more detailed would be a second subject competing with the one being taught.
(The 32 B are DERIVED from the pixel description below rather than pasted as a
byte table, and `test_hud_game.py` asserts the ROM's OBJ CHR against the same
literal bytes, so encoder and art have to agree.)
"""
import sys
from pathlib import Path

T = 8                                   # tile edge
TRN, BODY = 0, 1
# BGR555 5-bit components. BODY is OBJ_RED = $001F: red 31, green 0, blue 0.
PALETTE = {TRN: (0, 0, 0), BODY: (31, 0, 0)}

# The player: a solid 8x8 block of colour index 1.
ART = ["XXXXXXXX"] * T
GLYPH = {".": TRN, "X": BODY}


def bgr(r: int, g: int, b: int) -> int:
    return (b << 10) | (g << 5) | r


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


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)

    assert len(ART) == T and all(len(r) == T for r in ART)
    tile = encode_4bpp([GLYPH[ch] for row in ART for ch in row], "player")
    (out / "hud_obj_chr.bin").write_bytes(tile)

    pal = bytearray()
    for i in range(16):
        pal += bgr(*PALETTE.get(i, (0, 0, 0))).to_bytes(2, "little")
    (out / "hud_obj_pal.bin").write_bytes(bytes(pal))

    print(f"gen_hud_assets: 1 tile ({len(tile)} B) + 16 colours -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
