#!/usr/bin/env python3
"""gen_chamber_assets.py — the mode7_chamber rail's blobs (the four-effect rail).

Six files, all deterministic integer/trig math — byte-identical on re-run:

  m7c_map.bin    32,768 B  the interleaved Mode 7 image: 16,384 tilemap bytes
                           in the EVEN positions and 16,384 B of 8bpp CHR in
                           the ODD ones, exactly as the PPU reads the region.
  m7c_pal.bin        12 B  six BGR555 words, CGRAM index order 0..5.
  bow_a.bin       3,456 B  MB_BOWS x MB_LINES x 2 B — the per-scanline M7A
                           column, one table per BOW STEP.
  persp_d.bin       384 B  MB_LINES x 2 B — the per-scanline M7D column.
  m7c_vign.bin      672 B  3 x 224 COLDATA bytes (plane_select | intensity),
                           R then G then B: the depth vignette.

AND IT IS A GATE, not only a build step. Every byte of the first two is
checked against the committed reference output under vendor/art/mode7_chamber/, and
the step-(MB_BOWS-1) bow is checked against the vendored captured barrel curve.
An absent oracle is a REFUSAL, not a skip — a gate that passes when its
evidence is missing is not a gate. Nothing outside this tree is read at build
time; the oracles are vendored.

THE ART IS RE-DERIVED, NOT CONVERTED. The floor is procedural first-party
placeholder art: every 8x8 tile is a SOLID colour chosen by a three-line rule
over the 128x128 tile grid. So this generator runs that rule rather than
parsing a PNG, and the oracle proves the two agree.

Usage: gen_chamber_assets.py OUTDIR
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORACLE = REPO / "vendor" / "art" / "mode7_chamber"

# =============================================================================
# The floor — the design rule
# =============================================================================
MAP_T = 128                 # world side, in tiles (the Mode 7 playfield)
TILE_PX = 8
BLOCK = 2                   # ashlar block size in TILES (16 px blocks)
RIB_PITCH = 8               # a full-width rib every RIB_PITCH tiles (64 px)

# The cool-grey stone palette, RGB888.
STONE_A = (44, 46, 54)      # ashlar block dark   -> ALSO CGRAM word 0 (backdrop)
STONE_B = (92, 96, 110)     # ashlar block light
MORTAR = (24, 25, 30)       # mortar line between blocks
RIB = (170, 150, 90)        # rib body (warm brass) — the MOTION CUE
RIB_HI = (236, 214, 150)    # rib top-edge highlight

# CGRAM layout, and it is NOT first-appearance order — see the oracle README.
# make_chamber.py's reserve_backdrop pins word 0 to the dark stone and remaps
# every pixel that had landed on index 0 (the rib highlight, because it is the
# image's first row) to a freshly appended duplicate. So: word 4 duplicates
# word 0, the ashlar dark draws with index 4, the highlight with index 5, and
# NO pixel anywhere uses index 0.
PAL_RGB = [STONE_A, RIB, MORTAR, STONE_B, STONE_A, RIB_HI]
IDX_RIB_HI, IDX_RIB, IDX_MORTAR, IDX_STONE_B, IDX_STONE_A = 5, 1, 2, 3, 4

# Tile ids, in the order the deduplicator met them scanning tile-rows: the rib
# highlight row is ty=0, the rib body ty=1, mortar ty=2, then the two ashlar
# tones on ty=3.
TILE_OF_INDEX = {IDX_RIB_HI: 0, IDX_RIB: 1, IDX_MORTAR: 2,
                 IDX_STONE_B: 3, IDX_STONE_A: 4}
CHR_TILES = 256             # the CHR half of the region: 256 tiles x 64 B
# The unused CHR tiles read as index 5, not 0 — reserve_backdrop's remap ran
# over the whole padded block. Reproduced rather than "cleaned up".
CHR_PAD = IDX_RIB_HI


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def tile_index(tx: int, ty: int) -> int:
    """The palette index of tile (tx, ty). Three lines, and they are the art."""
    m = ty % RIB_PITCH
    if m == 0:
        return IDX_RIB_HI
    if m == 1:
        return IDX_RIB
    if (tx % BLOCK == 0) or (ty % BLOCK == 0):
        return IDX_MORTAR
    return IDX_STONE_B if ((tx // BLOCK) ^ (ty // BLOCK)) & 1 else IDX_STONE_A


def build_map() -> bytes:
    tilemap = bytearray(MAP_T * MAP_T)
    for ty in range(MAP_T):
        for tx in range(MAP_T):
            tilemap[ty * MAP_T + tx] = TILE_OF_INDEX[tile_index(tx, ty)]
    chr_ = bytearray([CHR_PAD]) * (CHR_TILES * 64)
    for idx, tid in TILE_OF_INDEX.items():
        chr_[tid * 64:(tid + 1) * 64] = bytes([idx]) * 64
    blob = bytearray(2 * MAP_T * MAP_T)
    blob[0::2] = tilemap
    blob[1::2] = chr_
    return bytes(blob)


def build_palette() -> bytes:
    out = bytearray()
    for rgb in PAL_RGB:
        out += rgb_to_bgr555(*rgb).to_bytes(2, "little")
    return bytes(out)


# =============================================================================
# m7_barrel's two matrix columns
# =============================================================================
MB_SEAM = 32                # the mode split: Mode 1 above, Mode 7 from here
MB_LINES = 224 - MB_SEAM    # 192 floor scanlines
MB_BOWS = 9                 # bow steps 0..8
MB_BOW_UNIT = 16            # 8.8 amplitude per step: step 8 = 128 = the
                            # captured $0180 peak; step 0 = flat
MB_FLAT = 256               # 1.0 in 8.8 — the un-bowed horizontal scale

# The perspective hyperbola's endpoints — the scene's declared near/far scales
# (320 and 64), DOUBLED, and the doubling is a MEASUREMENT rather than a taste
# call.
#
# A runtime solve does not take those two numbers alone: it also carries a
# vertical-squash knob ("make the rows narrow") applied on top of them, and a
# baked hyperbola has no such knob. Taking 320/64 literally produced a floor
# with 3-4 visible rib rows where the reference render has 6+ — i.e. a chamber
# magnified about 2x too far in the near field.
#
# The factor was fixed against a REFERENCE RENDER, not against a re-rendering
# of this generator's own output (the asset-import rule): a reference
# build of this scene was run under MesenRunner, its rib rows measured at
# picture rows [34, 40, 49, 60, 76, 140], and these endpoints predict
# [35, 42, 50, 61, 77, 100, 141]. tests/test_mode7_chamber.py's
# reference-gated case re-runs that comparison.
MB_SCALE_FAR = 640          # at the horizon scanline
MB_SCALE_NEAR = 128         # at the bottom scanline


def bow_column(step: int) -> list[int]:
    """M7A per floor scanline for one bow STEP: a symmetric raised cosine.

    amp * (1 - cos(2*pi*k/L)) / 2 added to 1.0, so both edges sit at exactly
    1.0 and the mid-band bulges. Step 0 gives amp 0 — a FLAT column, i.e. no
    barrel at all, which is the runtime non-vacuity control.
    """
    amp = step * MB_BOW_UNIT
    return [MB_FLAT + round(amp * (1 - math.cos(2 * math.pi * k / MB_LINES)) / 2)
            for k in range(MB_LINES)]


def persp_column() -> list[int]:
    """M7D per floor scanline: S(k) = K/(k+k0) through (far at k=0, near at
    k=L-1) — the same hyperbola tools/gen_pose_tables.py solves, at this
    rail's endpoints."""
    L, sf, sn = MB_LINES, MB_SCALE_FAR, MB_SCALE_NEAR
    k0 = sn * (L - 1) / (sf - sn)
    K = sf * k0
    col = [round(K / (k + k0)) for k in range(L)]
    assert col[0] == sf and col[-1] == sn, (col[0], col[-1])
    return col


def s16(v: int) -> bytes:
    return int(v).to_bytes(2, "little", signed=True)


# =============================================================================
# The vignette — rgb_gradient's three static COLDATA plane tables
# =============================================================================
GRAD_LINES = 224            # rgb_gradient.asm's GRAD_LINES
PLANE = (0x20, 0x40, 0x80)  # COLDATA plane-select bits (R, G, B)

# The vignette, as (line count, 5-bit intensity) — the same profile the
# vendored `ref_chamber_tables.inc` encodes as [count, $E0|v] HDMA pairs. Dark at the top,
# brightest through the middle 84 lines, dark again at the bottom.
VIGN_RUNS = [(36, 0), (8, 2), (4, 3), (8, 4), (10, 5), (12, 6), (18, 7),
             (84, 8), (10, 7), (8, 6), (6, 5), (6, 4), (6, 3), (1, 1)]


def vignette_intensity() -> list[int]:
    out: list[int] = []
    for n, v in VIGN_RUNS:
        out += [v] * n
    # The vendored table covers 217 scanlines and lets the register HOLD its last
    # value through the rest of the frame. rgb_gradient's tables span all 224
    # by declaration, so the hold is written out.
    out += [out[-1]] * (GRAD_LINES - len(out))
    assert len(out) == GRAD_LINES, len(out)
    return out


def build_vignette() -> bytes:
    v = vignette_intensity()
    out = bytearray()
    for plane in PLANE:
        out += bytes(plane | i for i in v)
    return bytes(out)


# =============================================================================
# The oracle gate
# =============================================================================
def _read_oracle(name: str) -> bytes:
    p = ORACLE / name
    if not p.exists():
        sys.exit(f"gen_chamber_assets: ORACLE MISSING: {p}\n"
                 f"  This generator is a gate; it refuses to emit without its "
                 f"reference bytes. See vendor/art/mode7_chamber/README.md.")
    return p.read_bytes()


def _oracle_palette() -> bytes:
    text = _read_oracle("ref_chamber_palette.inc").decode()
    words = [int(m, 16) for m in re.findall(r"\.word\s+\$([0-9A-Fa-f]{4})", text)]
    if not words:
        sys.exit("gen_chamber_assets: palette oracle parsed to zero words")
    out = bytearray()
    for w in words:
        out += w.to_bytes(2, "little")
    return bytes(out)


def _oracle_barrel() -> list[int]:
    text = _read_oracle("ref_chamber_tables.inc").decode()
    body = text.split("chamber_barrel:", 1)[1].split("chamber_vignette:", 1)[0]
    # `.word` LINES only. A bare 4-hex scan would also swallow the $2132 in the
    # vignette section's own comment — which is exactly what it did on the
    # first run, reporting a 193-entry "curve".
    words: list[int] = []
    for line in body.splitlines():
        if not line.strip().startswith(".word"):
            continue
        words += [int(m, 16)
                  for m in re.findall(r"\$([0-9A-Fa-f]{4})", line.split(";")[0])]
    return words


def _diff(a: bytes, b: bytes) -> str:
    if len(a) != len(b):
        return f"length {len(a)} != oracle {len(b)}"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"first difference at byte {i}: {x:#04x} != oracle {y:#04x}"
    return "identical"


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit("usage: gen_chamber_assets.py OUTDIR")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    m7c_map = build_map()
    m7c_pal = build_palette()

    # ---- the gate: this procedural derivation vs the committed reference bytes
    ref_map = _read_oracle("ref_chamber_map.bin")
    if m7c_map != ref_map:
        sys.exit(f"gen_chamber_assets: MAP disagrees with the reference oracle — "
                 f"{_diff(m7c_map, ref_map)}")
    ref_pal = _oracle_palette()
    if m7c_pal != ref_pal:
        sys.exit(f"gen_chamber_assets: PALETTE disagrees with the reference "
                 f"oracle — {_diff(m7c_pal, ref_pal)}")

    bows = [bow_column(s) for s in range(MB_BOWS)]
    ref_bow = _oracle_barrel()
    if bows[MB_BOWS - 1] != ref_bow:
        n = min(len(ref_bow), len(bows[-1]))
        where = next((i for i in range(n) if bows[-1][i] != ref_bow[i]), n)
        sys.exit(f"gen_chamber_assets: the step-{MB_BOWS - 1} bow disagrees "
                 f"with the captured barrel curve at index {where} "
                 f"(len {len(bows[-1])} vs oracle {len(ref_bow)})")
    # Step 0 is the CONTROL: it must be flat, or the runtime non-vacuity check
    # the rail ships is not one.
    assert set(bows[0]) == {MB_FLAT}, "bow step 0 must be flat"

    persp = persp_column()

    bow_blob = b"".join(s16(v) for col in bows for v in col)
    persp_blob = b"".join(s16(v) for v in persp)
    vign_blob = build_vignette()

    (out / "m7c_map.bin").write_bytes(m7c_map)
    (out / "m7c_pal.bin").write_bytes(m7c_pal)
    (out / "bow_a.bin").write_bytes(bow_blob)
    (out / "persp_d.bin").write_bytes(persp_blob)
    (out / "m7c_vign.bin").write_bytes(vign_blob)

    print(f"chamber: map {len(m7c_map)} B + pal {len(m7c_pal)} B "
          f"(both == reference oracle), bow {MB_BOWS}x{MB_LINES} = "
          f"{len(bow_blob)} B (step {MB_BOWS - 1} == captured curve), "
          f"persp {len(persp_blob)} B, vignette {len(vign_blob)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
