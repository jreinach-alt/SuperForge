#!/usr/bin/env python3
"""Placeholder art for the OBJ viewer probe: 8 numbered 32x32 4bpp frames.

Original, trivial test blocks — each frame is a bordered box with its own
accent colour, a diagonal stripe, a 3x3 corner tick at top-left (so a
flipped or mis-tiled frame is visible at a glance) and its frame number as
a large digit. The probe renders them at true scale so candidate sprite art
can be judged in-ROM by swapping the two blobs at build time
(PROBE_OBJVIEW_CHR= / PROBE_OBJVIEW_PAL=, see the Makefile's probe-objview
comment); these committed placeholders are what a bare checkout builds.

Deterministic: a pure function of this file, so a regen is byte-identical.
The committed copies live in vendor/probes/probe_objview/assets/ — regen
with `python3 tools/gen_objview_assets.py vendor/probes/probe_objview/assets`.

Layout contract (the probe's asm mirrors it): OBJ CHR is a 16-tile-wide
grid; a 32x32 sprite reads tiles {N, N+1..N+3, N+16..} — so frame i's
top-left tile is (i // 4) * 64 + (i % 4) * 4, and the whole ladder is 128
tiles = 4096 bytes. The palette blob is 16 BGR555 words (OBJ palette 0);
index 0 is the hardware-transparent slot.
"""
import sys
from pathlib import Path

FRAMES, SIDE = 8, 32                 # 8 frames of 32x32
GRID_W = 16                          # OBJ CHR is 16 tiles wide, hardware-fixed

# 5x7 digit bitmaps, hand-drawn, one string row per pixel row.
DIGITS = [
    ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],  # 0
    ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],  # 1
    ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],  # 2
    ["01110", "10001", "00001", "00110", "00001", "10001", "01110"],  # 3
    ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],  # 4
    ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],  # 5
    ["01110", "10000", "11110", "10001", "10001", "10001", "01110"],  # 6
    ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],  # 7
]

# BGR555 palette: 0 transparent, 1 dark outline, 2 fill, 3..10 per-frame
# accents, 11 texture, 12 white, 13 stripe, 14/15 spare mids.
PALETTE = [0x0000, 0x0842, 0x2D6B, 0x001F, 0x03E0, 0x7C00, 0x03FF,
           0x7C1F, 0x7FE0, 0x0210, 0x421F, 0x39CE, 0x7FFF, 0x1084,
           0x2108, 0x5AD6]


def frame_pixels(i: int) -> list[list[int]]:
    """One 32x32 frame as palette indices."""
    acc = 3 + i
    px = [[2] * SIDE for _ in range(SIDE)]
    for y in range(SIDE):
        for x in range(SIDE):
            if x < 2 or y < 2 or x >= SIDE - 2 or y >= SIDE - 2:
                px[y][x] = acc                       # 2px accent border
            elif (x + y) % 8 == 0:
                px[y][x] = 13                        # diagonal stripes
    for y in range(2, 5):                            # top-left tick: catches
        for x in range(2, 5):                        # flips and mis-tiling
            px[y][x] = 12
    ox, oy = (SIDE - 5 * 3) // 2, (SIDE - 7 * 3) // 2
    for r, row in enumerate(DIGITS[i]):              # the digit, 3x scale,
        for c, bit in enumerate(row):                # with a 1px dark drop
            if bit == "1":
                for dy in range(3):
                    for dx in range(3):
                        px[oy + r * 3 + dy + 1][ox + c * 3 + dx + 1] = 1
                        px[oy + r * 3 + dy][ox + c * 3 + dx] = 12
    return px


def encode_tile_4bpp(px, tx, ty) -> bytes:
    """SNES 4bpp: rows of planes 0+1 interleaved, then rows of planes 2+3."""
    lo, hi = bytearray(), bytearray()
    for r in range(8):
        p = [px[ty * 8 + r][tx * 8 + c] for c in range(8)]
        for planes, buf in (((0, 1), lo), ((2, 3), hi)):
            for pl in planes:
                buf.append(sum(((v >> pl) & 1) << (7 - c)
                               for c, v in enumerate(p)))
    return bytes(lo + hi)


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tiles = {}                                       # grid index -> 32 bytes
    for i in range(FRAMES):
        px = frame_pixels(i)
        base_row, base_col = (i // 4) * 4, (i % 4) * 4
        for ty in range(4):
            for tx in range(4):
                grid = (base_row + ty) * GRID_W + (base_col + tx)
                tiles[grid] = encode_tile_4bpp(px, tx, ty)
    n = max(tiles) + 1
    chr_data = b"".join(tiles.get(t, bytes(32)) for t in range(n))
    (out / "objview_chr.bin").write_bytes(chr_data)
    (out / "objview_pal.bin").write_bytes(
        b"".join(w.to_bytes(2, "little") for w in PALETTE))
    print(f"objview assets: {len(chr_data)} B chr ({n} tiles), "
          f"{2 * len(PALETTE)} B pal -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
