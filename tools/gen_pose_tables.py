#!/usr/bin/env python3
"""gen_pose_tables.py — superforge: per-scanline Mode-7 pose tables (ROM LUTs).

The split_h_2p_demo technique — LUT plus PPU offload makes Mode 7 perspective
near-free — solved for microzero's
geometry: for each of 64 headings, a band-local per-scanline table pair

  AB blob: LINES x [A_lo, A_hi, B_lo, B_hi]   (INDIRECT HDMA -> M7A/M7B)
  CD blob: LINES x [C_lo, C_hi, D_lo, D_hi]   (INDIRECT HDMA -> M7C/M7D)

A = S(k)*cos, B = S(k)*sin, C = -S(k)*sin, D = S(k)*cos (8.8 signed), with
S(k) = K/(k + k0) the true-perspective hyperbola solved through
(scale_far at k=0, scale_near at k=LINES-1) — the same shape the reference scene's
runtime rebuild approximates, precomputed exactly at build time.

STRIDE: each pose padded to 1024 B (LINES*4 <= 1024), so 32 poses fill one
32 KB window exactly and the runtime pointer math is pure shifts:
  ptr  = window_base + (h & 31) * 1024
  bank = blob_base_bank + (h >> 5)
64 poses -> 2 windows per blob, 128 KB total for AB+CD.

Deterministic: pure math.cos/round from the arguments — byte-identical on
re-run.

Usage: gen_pose_tables.py --lines 180 --scale-far 436 --scale-near 77 OUTDIR
"""
import argparse
import math
import sys
from pathlib import Path

POSES = 64
STRIDE = 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, required=True)
    ap.add_argument("--scale-far", type=int, required=True)
    ap.add_argument("--scale-near", type=int, required=True)
    ap.add_argument("out")
    a = ap.parse_args()
    L, sf, sn = a.lines, a.scale_far, a.scale_near
    assert L * 4 <= STRIDE, (L, STRIDE)
    # S(k) = K/(k+k0): sf = K/k0, sn = K/(k0+L-1)
    k0 = sn * (L - 1) / (sf - sn)
    K = sf * k0
    scales = [round(K / (k + k0)) for k in range(L)]
    assert scales[0] == sf and scales[-1] == sn, (scales[0], scales[-1])

    def s16(v: int) -> bytes:
        return int(v).to_bytes(2, "little", signed=True)

    ab = bytearray()
    cd = bytearray()
    for h in range(POSES):
        th = 2 * math.pi * h / POSES
        c, s = math.cos(th), math.sin(th)
        pa = bytearray()
        pc = bytearray()
        for k in range(L):
            S = scales[k]
            A = round(S * c)
            B = round(S * s)
            pa += s16(A) + s16(B)
            pc += s16(-B) + s16(A)          # C = -S sin, D = S cos
        pa += bytes(STRIDE - len(pa))
        pc += bytes(STRIDE - len(pc))
        ab += pa
        cd += pc
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "poses_ab.bin").write_bytes(ab)
    (out / "poses_cd.bin").write_bytes(cd)
    print(f"poses: {POSES} x {L} lines, stride {STRIDE} -> "
          f"{len(ab)} B ab + {len(cd)} B cd")
    return 0


if __name__ == "__main__":
    sys.exit(main())
