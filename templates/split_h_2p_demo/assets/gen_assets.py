#!/usr/bin/env python3
"""gen_assets.py — first-party assets for the 2-player split-screen rail.

Emits (all deterministic; provenance manifest references this script):

  checker_map.bin   the shared warm/cool-stripe Mode-7 world (same design as
                    split_h_persp_demo: a coarse green checker whose RED channel
                    encodes WORLD-X stripe position — the framebuffer signal for
                    "the two cameras look at different places").
  poses1_ab.bin /   the fixed-angle (--angles 1) pose pair the rail streams by
  poses1_cd.bin     default (448 B each: 112 lines x 4 B).
  pose_rot45_ab.bin/ one pose sliced from the PREFERRED 64-angle shipping set
  pose_rot45_cd.bin  (angle index 8 = 45 degrees) — the -DRETARGET smoke pose
                     that proves a non-trivial heading streams correctly.
  poses64_ab.bin /  the 64-angle single-bank set (28,672 B each — one exact
  poses64_cd.bin    32KB LoROM bank per blob) — the POSES=64 rotate A/B build
                    streams these from dedicated banks (BANK2/BANK3,
                    per-channel indirect data banks).
  poses256_ab.bin / the 256-angle ROTATE-DEFAULT set (114,688 B each = 4 bank
  poses256_cd.bin   slices of 28,672 B; pose (64k+j) at slice k offset j*448).
                    1.40625°/pose = ONE pose step PER FRAME at the demo turn
                    rate — the rotation-smoothness DoD (owner feedback
                    2026-07-02). The POSES=256 build .incbin's the slices into
                    BANK2..BANK5 (AB) / BANK6..BANK9 (CD) and stamps each
                    band's indirect data banks ($43x7) per frame.
  move64.bin /      N x (dx s16, dy s16) forward-vector LUTs in 8.8 FIXED
  move256.bin       POINT: entry h = round(2*256*(-sin, -cos)(2*pi*h/N)) —
                    world "forward" for heading h at a CONSTANT 2.0 px/frame
                    (screen-up from the band pivot maps to world (-sin,-cos)
                    under the pose rotation). 8.8 + per-axis fractional
                    accumulators in the rail kill the speed pulse and
                    direction staircase that integer velocities produced
                    (the translation-jerk owner feedback, 2026-07-02).
                    move256 gives the exact forward direction at every one of
                    the 256 headings — indexed by h directly.

The pose tables come from tools/gen_pose_tables.py (the granularity tool:
--angles {1,32,64,128,256,512}; 256 is the rotate default, 64 the single-bank
option; 512 is tool-supported as the slow-turn measurement escape hatch and
is NOT committed here).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
TOOL = HERE.parent.parent.parent / "tools" / "gen_pose_tables.py"

MAP_W = 128
TILE_WORDS = 64
BLOCK = 4       # 4x4 world tiles per checker square -> 32x32-px world period
STRIPE = 32     # 32 world tiles per colour stripe -> 256-px world stripe period
PHASE = 16      # +16-tile phase: COOL stripe centred on world X 512 (camera 1),
                # WARM stripe centred on world X 768 (camera 2's start)

LINES = 112
POSE_BYTES = LINES * 4
ROT45_INDEX = 8         # 64-angle set: index 8 = 2*pi*8/64 = 45 degrees


def build_map() -> bytes:
    tilemap = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            parity = ((row // BLOCK) ^ (col // BLOCK)) & 1
            warm = ((col + PHASE) // STRIPE) & 1
            tilemap[row * MAP_W + col] = parity + (2 if warm else 0)
    chr_bytes = bytearray(MAP_W * MAP_W)
    for k in range(4):      # tile k = solid palette index k+1
        chr_bytes[k * TILE_WORDS:(k + 1) * TILE_WORDS] = bytes([k + 1]) * TILE_WORDS
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


def main() -> None:
    data = build_map()
    assert len(data) == 0x8000, len(data)
    (HERE / "checker_map.bin").write_bytes(data)
    print(f"checker_map.bin: {len(data)} bytes")

    # Fixed-angle pose pair (the rail's default stream).
    subprocess.run([sys.executable, str(TOOL), "--angles", "1",
                    "--out-prefix", "poses1", "--out-dir", str(HERE)], check=True)

    # The 64-angle single-bank set (streamed by the POSES=64 rotate A/B build
    # from BANK2/BANK3) + the 45-degree smoke pose sliced from it for
    # -DRETARGET (which stays inside the 64KB default image).
    subprocess.run([sys.executable, str(TOOL), "--angles", "64",
                    "--out-prefix", "poses64", "--out-dir", str(HERE)], check=True)
    for chan in ("ab", "cd"):
        blob = (HERE / f"poses64_{chan}.bin").read_bytes()
        lo = ROT45_INDEX * POSE_BYTES
        (HERE / f"pose_rot45_{chan}.bin").write_bytes(blob[lo:lo + POSE_BYTES])
        print(f"pose_rot45_{chan}.bin: {POSE_BYTES} bytes (64-set index {ROT45_INDEX})")

    # The 256-angle ROTATE-DEFAULT set (4 bank slices per blob; the POSES=256
    # build's step-per-frame smoothness set).
    subprocess.run([sys.executable, str(TOOL), "--angles", "256",
                    "--out-prefix", "poses256", "--out-dir", str(HERE)], check=True)

    # Forward-vector LUTs: heading h -> round(2*256*(-sin, -cos)) as two s16
    # words in 8.8 fixed point (constant 2.0 px/frame magnitude at every
    # heading; the rail accumulates fractions per axis).
    emit_move_lut(64)
    emit_move_lut(256)


def emit_move_lut(n: int) -> None:
    """move<n>.bin: entry h = round(2*256*(-sin, -cos)(2*pi*h/n)), s16 pairs."""
    import math
    import struct
    move = bytearray()
    for h in range(n):
        a = 2.0 * math.pi * h / n
        move += struct.pack("<hh", round(-512.0 * math.sin(a)),
                            round(-512.0 * math.cos(a)))
    (HERE / f"move{n}.bin").write_bytes(move)
    print(f"move{n}.bin: {len(move)} bytes ({n} forward vectors, 8.8)")


if __name__ == "__main__":
    main()
