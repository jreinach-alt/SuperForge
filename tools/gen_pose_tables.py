#!/usr/bin/env python3
"""gen_pose_tables.py — Mode-7 per-scanline camera pose-table generator.

Emits the ROM-resident matrix band tables the 2-player split-screen rail
(`split_h_2p_demo`) streams via INDIRECT-mode HDMA: for each heading angle,
a band-local per-scanline table pair

  AB blob: LINES x [A_lo, A_hi, B_lo, B_hi]   (DMAP $43 -> M7A $211B / M7B $211C)
  CD blob: LINES x [C_lo, C_hi, D_lo, D_hi]   (DMAP $43 -> M7C $211D / M7D $211E)

with A = S(k)*cos(a), B = S(k)*sin(a), C = -S(k)*sin(a), D = S(k)*cos(a)
(8.8 signed fixed point; k = band-local scanline). S(k) is a TRUE-perspective
hyperbolic ramp S(k) = K / (k + k0), solved from the geometry pair
(--scale-far at k=0, --scale-near at k=LINES-1). The tables are BAND-LOCAL:
index 0 == the band's first scanline; the HDMA index-table entry for a band
points at `blob_base + angle*LINES*4`.

GRANULARITY: --angles {1,32,64,128,256,512} poses per full turn (owner ruling
2026-07-02: 64 was the one-bank sweet spot; the rotation-smoothness follow-up
made 256 the rotate default — 1.40625°/pose = one pose step PER FRAME at the
demo turn rate; 512 is the slow-turn measurement escape hatch).
Bank budget: LINES=112 -> 448 B/pose/blob; 64 poses = 28,672 B/blob — each
blob fits ONE 32KB LoROM bank. Sets ABOVE 64 poses stay one contiguous blob
but are BANK-SLICEABLE by construction: 64 poses per 28,672-B slice, pose
(64k + j) at slice k offset j*448, so a consumer .incbin's slice k
(`offset k*28672, 28672`) into its own bank and addresses pose h as
ptr = $8000 + (h & 63)*448, bank = base_bank + (h >> 6). 128 poses = 2
slices/blob, 256 = 4, 512 = 8 (the tool emits a single blob and PRINTS the
slice count; the budget itself is asserted by tests/test_gen_pose_tables.py,
not here).

Determinism: pure integer/`math` output from the arguments — byte-identical
on re-run (provenance manifest entries reference this script + args).

Usage (what the demo's assets script runs):
  gen_pose_tables.py --angles 1  --out-prefix poses1   [geometry args]
  gen_pose_tables.py --angles 64 --out-prefix poses64  [geometry args]
"""
import argparse
import math
import struct
import sys
from pathlib import Path

LINES_DEFAULT = 112
BANK_BYTES = 32 * 1024
SLICE_POSES = 64                # poses per LoROM bank slice (64 x 448 = 28,672 B)


def scale_ramp(lines: int, s_far: float, s_near: float) -> list[int]:
    """True-perspective hyperbolic ramp, 8.8 fixed point per scanline.

    S(k) = K / (k + k0) with S(0) = s_far, S(lines-1) = s_near.
    (s_far > s_near: the top of the band samples MORE world per pixel —
    smaller on-screen features — receding toward the band's horizon.)
    """
    if not (s_far > s_near > 0):
        raise SystemExit("geometry: need scale-far > scale-near > 0")
    k0 = (lines - 1) * s_near / (s_far - s_near)
    big_k = s_far * k0
    ramp = []
    for k in range(lines):
        s = big_k / (k + k0)
        fx = round(s * 256.0)
        if not (1 <= fx <= 0x7FFF):
            raise SystemExit(f"geometry: scale at line {k} out of s8.8 range ({fx})")
        ramp.append(fx)
    return ramp


def pose_blobs(ramp: list[int], angle_rad: float) -> tuple[bytes, bytes]:
    """One pose's band-local AB and CD byte tables for a heading angle."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    ab = bytearray()
    cd = bytearray()
    for fx in ramp:
        a = round(fx * c)
        b = round(fx * s)
        ab += struct.pack("<hh", a, b)      # A, B  (s8.8, little-endian)
        cd += struct.pack("<hh", -b, a)     # C = -B, D = A (rotation matrix)
    return bytes(ab), bytes(cd)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--angles", type=int, default=64,
                   choices=(1, 32, 64, 128, 256, 512),
                   help="poses per full turn (1 = fixed angle 0; 256 = the "
                        "rotate-default step-per-frame set; 64 = single-bank)")
    p.add_argument("--lines", type=int, default=LINES_DEFAULT,
                   help="band height in scanlines (default 112)")
    p.add_argument("--scale-far", type=float, default=1.5,
                   help="8.8 scale at the band's top line (default 1.5)")
    p.add_argument("--scale-near", type=float, default=0.625,
                   help="8.8 scale at the band's bottom line (default 0.625)")
    p.add_argument("--out-prefix", default=None,
                   help="output blob prefix (default poses<angles>)")
    p.add_argument("--out-dir", default=".", help="output directory")
    args = p.parse_args()

    prefix = args.out_prefix or f"poses{args.angles}"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ramp = scale_ramp(args.lines, args.scale_far, args.scale_near)
    ab_all = bytearray()
    cd_all = bytearray()
    for i in range(args.angles):
        ab, cd = pose_blobs(ramp, 2.0 * math.pi * i / args.angles)
        ab_all += ab
        cd_all += cd

    pose_bytes = args.lines * 4
    slice_bytes = SLICE_POSES * pose_bytes
    if args.angles > SLICE_POSES and slice_bytes > BANK_BYTES:
        raise SystemExit(f"slice model broken: {SLICE_POSES} poses x "
                         f"{pose_bytes} B = {slice_bytes} B > one 32KB bank")
    for name, blob in ((f"{prefix}_ab.bin", ab_all), (f"{prefix}_cd.bin", cd_all)):
        path = out_dir / name
        path.write_bytes(blob)
        slices = (len(blob) + slice_bytes - 1) // slice_bytes
        fit = ("fits 1 LoROM bank" if slices == 1
               else f"needs {slices} bank slices of {slice_bytes} B")
        print(f"{name}: {len(blob)} bytes ({args.angles} poses x {pose_bytes} B) — {fit}")

    # Self-checks (the tooling tests re-assert these from the emitted bytes):
    # angle 0 is the pure ramp (B = C = 0); each pose is a rotation (C = -B, D = A).
    assert ab_all[2:4] == b"\x00\x00", "angle-0 pose must have B == 0"
    assert cd_all[0:2] == b"\x00\x00", "angle-0 pose must have C == 0"


if __name__ == "__main__":
    sys.exit(main())
