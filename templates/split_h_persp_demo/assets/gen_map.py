#!/usr/bin/env python3
"""gen_map.py — first-party Mode-7 world for the perspective C-horiz rail.

Emits the interleaved Mode-7 VRAM blob (even bytes = 128x128 tilemap, odd bytes =
8bpp tile pixels) for ONE flat top-down world shared by both perspective cameras.

TWO overlaid signals, deliberately ORTHOGONAL so each rail test reads its own:

  1. A coarse CHECKER (period signal). BLOCK x BLOCK world tiles per checker
     square (BLOCK=4 -> a 32x32-px world period). Two shades alternate; the two
     perspective cameras (different horizon / scale) compress the checker
     differently, so the on-screen texel PERIOD at a fixed column differs
     measurably between the bands. Read via luminance transitions.

  2. A coarse WORLD-POSITION COLOUR field (position signal, NEW for camera-pos).
     The map is split into vertical STRIPES by world column: "cool" stripes use
     blue/green checker shades (palette idx 1/2 — the original colours, no red),
     "warm" stripes use RED checker shades (palette idx 3/4). The stripe a camera
     views depends ONLY on its WORLD X position, so a camera panned to a different
     world centre samples a different-coloured stripe. Read via the RED channel —
     which is ~0 in the cool stripes, so it does NOT perturb the (green+blue)
     luminance/period signal the pre-existing tests use.

  Stripe layout (STRIPE=32 world tiles = 256 world px), phase-shifted by +16 tiles
  so a COOL stripe is centred on world tile 64 (world X 512 = camera A's default
  posx): tiles [48,80) cool, [80,112) warm, [16,48) warm, ... A camera panned
  +256 world px (from world X 512 to 768 = tile 96) lands dead-centre in the warm
  (red) stripe -> band-2 turns red. That is the framebuffer proof of an
  independent world POSITION (not merely a different zoom of the same spot).

Two solid tiles per shade-pair (8bpp: each pixel byte = the palette index):
  tile0 = idx1 (cool dark)   tile1 = idx2 (cool light)
  tile2 = idx3 (warm dark)   tile3 = idx4 (warm light)

First-party, deterministic, mechanism-only (no game references).
"""
from pathlib import Path

MAP_W = 128
TILE_WORDS = 64
BLOCK = 4       # 4x4 world tiles per checker square -> 32x32-px world period
STRIPE = 32     # 32 world tiles per colour stripe -> 256-px world stripe period
PHASE = 16      # +16-tile phase so a COOL stripe is centred on world tile 64


def build() -> bytes:
    tilemap = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            parity = ((row // BLOCK) ^ (col // BLOCK)) & 1
            warm = ((col + PHASE) // STRIPE) & 1        # 1 = red stripe
            tilemap[row * MAP_W + col] = parity + (2 if warm else 0)
    chr_bytes = bytearray(MAP_W * MAP_W)
    # tile k = solid palette index (k+1): tile0->1, tile1->2, tile2->3, tile3->4.
    for k in range(4):
        chr_bytes[k * TILE_WORDS:(k + 1) * TILE_WORDS] = bytes([k + 1]) * TILE_WORDS
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


if __name__ == "__main__":
    data = build()
    assert len(data) == 0x8000, len(data)
    target = Path(__file__).parent / "checker_map.bin"
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")
