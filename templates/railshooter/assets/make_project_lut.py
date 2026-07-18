#!/usr/bin/env python3
"""make_project_lut.py — bake the rail-shooter pseudo-3D projection LUT.

The rail shooter places approaching obstacles on a fake-3D ground plane. The
SNES Mode 7 grid is only the visual BACKDROP; the obstacles ride their OWN
pinhole (1/z) projection, fully decoupled from the Mode 7 affine matrix. This
is exactly how the classic forward shooters faked depth (Jake Gordon's
racing-game canon, Lou's Pseudo-3D page): the camera is a pinhole at height
CAM_H above the ground, and a point at forward depth z projects to

    screen_y(z) = clamp( HORIZON_Y + (CAM_H*256)/z , HORIZON_Y, Y_BOTTOM )
    scale(z)    = (FOCAL*256)/z                 (.8 fixed perspective factor)
    screen_x    = 128 + ((lateral_offset * scale) >> 8)

There is NO matrix inversion and NO ROM/HDMA readback — the table is pure
arithmetic from the tuning constants below. The Mode 7 floor's affine matrix
gives only ~14 world-px of forward depth, far too shallow for a multi-frame
approach; the pinhole model gives an arbitrary forward range (Z_NEAR..Z_FAR)
so an obstacle descends smoothly from the horizon to the bottom of the screen
across dozens of frames.

The depth axis is z in WORLD PIXELS ahead of the camera (no 256x scaling —
the caller carries z directly). The table is bucketed by z (power-of-two
bucket step PROJ_Q so the asm `>>` index still works); each entry is
(scanline_byte, scale_word).

`engine/mode7_project.asm` consumes it: input depth z -> outputs PROJ_SX,
PROJ_SY, PROJ_TIER, PROJ_CULLED. The generator is deterministic (no emulator,
no ROM) and ASSERTS that screen_y is monotone in z before emitting.

Run (from a materialized kit root):
    cd /tmp/kit
    PYTHONPATH=. python3 templates/railshooter/assets/make_project_lut.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# kit root = .../templates/railshooter/assets -> up 3
KIT_ROOT = HERE.parent.parent.parent

# =============================================================================
# TUNING CONSTANTS (must match templates/railshooter/main.asm)
# =============================================================================
# These are the pinhole-camera parameters. Tune them until the approach looks
# right, then keep main.asm's mirror constants in sync (they're cross-checked
# at build time only by visual inspection — keep them identical).
HORIZON_Y = 56      # horizon scanline (matches the floor's PV_L0 so obstacles
                    # emerge at the grid horizon)
Y_BOTTOM = 223      # lowest usable scanline (obstacle centre clamps here)
CAM_H = 17          # camera height: sets how fast things drop. At z=Z_NEAR an
                    # obstacle centre sits at HORIZON_Y + CAM_H*256/Z_NEAR.
FOCAL = 44          # lateral focal length: sets the lane fan-out across the
                    # screen width. screen_x = 128 + lateral*FOCAL*256/z/256.
Z_NEAR = 16         # recycle/pass threshold (world px). Below this the object
                    # is "at the camera" and recycles. Low enough that an
                    # obstacle reaches the bottom of the screen (y -> 223) in
                    # the largest tier before recycling.
Z_FAR = 640         # spawn depth (world px) — the far edge of the rail.

# --- LUT shape: bucket the z axis by a power of two so the asm index is a >>.
PROJ_Q = 8          # world-px per bucket
PROJ_N = (Z_FAR // PROJ_Q) + 1     # bucket count covering 0..Z_FAR

# --- size tiers by z (nearer = bigger). 4 tiers (0..3), each owning a visible
# on-screen band. tier 0 = nearest/biggest (32x32 full) .. tier 3 =
# farthest/smallest (16x16 tiny). Thresholds spread across [Z_NEAR, Z_FAR].
# Picked so each tier occupies a distinct scanline band (verified below):
#   z <  80 -> tier 0 (32x32 full)   screen_y > ~104 (large, low)
#   z < 160 -> tier 1 (32x32 medium) screen_y ~ 82..104
#   z < 360 -> tier 2 (16x16 full)   screen_y ~ 67..82
#   z >=360 -> tier 3 (16x16 tiny)   screen_y ~ 62..67 (near horizon)
TIER_T0 = 80
TIER_T1 = 160
TIER_T2 = 360


def screen_y(z: int) -> int:
    if z < 1:
        z = 1
    y = HORIZON_Y + (CAM_H * 256) // z
    return min(Y_BOTTOM, max(HORIZON_Y, y))


def scale_of(z: int) -> int:
    if z < 1:
        z = 1
    return min((FOCAL * 256) // z, 0xFFFF)


def main() -> None:
    assert PROJ_Q & (PROJ_Q - 1) == 0, "PROJ_Q must be a power of two"
    assert TIER_T0 < TIER_T1 < TIER_T2 < Z_FAR, "tier thresholds must ascend"
    assert Z_NEAR < TIER_T0, "Z_NEAR must be below the nearest tier threshold"

    # --- build the z-bucketed table: entry k covers depth z = k*PROJ_Q ---
    # Use the bucket midpoint (k*Q + Q/2) so the sampled depth is representative
    # of the whole bucket rather than its left edge.
    table = []   # (scanline_byte, scale_word, z_sample)
    for k in range(PROJ_N):
        z = k * PROJ_Q + PROJ_Q // 2
        z = max(z, 1)
        table.append((screen_y(z) & 0xFF, scale_of(z) & 0xFFFF, z))

    # --- VALIDATE: screen_y must be monotone NON-INCREASING in z (nearer = ---
    # lower on screen = larger y). Pure pinhole math guarantees this; assert it
    # so a bad constant edit fails loudly (nonzero exit), never a silent pass.
    ys = [screen_y(k * PROJ_Q + PROJ_Q // 2) for k in range(1, PROJ_N)]
    assert all(ys[i] >= ys[i + 1] for i in range(len(ys) - 1)), \
        "screen_y(z) is not monotone in z — projection unsound"

    # --- report the tier bands (for the visual-tuning loop) ---
    print(f"PROJ_N={PROJ_N} buckets, Z range [0,{Z_FAR}], PROJ_Q={PROJ_Q}")
    print(f"pinhole: HORIZON_Y={HORIZON_Y} CAM_H={CAM_H} FOCAL={FOCAL} "
          f"Z_NEAR={Z_NEAR} Z_FAR={Z_FAR}")
    bands = {0: [], 1: [], 2: [], 3: []}
    for k in range(PROJ_N):
        z = k * PROJ_Q + PROJ_Q // 2
        tier = 0 if z < TIER_T0 else 1 if z < TIER_T1 else 2 if z < TIER_T2 else 3
        bands[tier].append(screen_y(z))
    for t in range(4):
        if bands[t]:
            print(f"  tier {t}: z-band -> screen_y [{min(bands[t])},{max(bands[t])}]")

    # --- sample table (visual check of the descent shape) ---
    print("\nsample (z -> screen_y, scale, sx@off=+48 lateral):")
    for z in [Z_NEAR, 32, 48, 64, 96, 128, 192, 256, 384, 512, Z_FAR]:
        sc = scale_of(z)
        sx = 128 + ((48 * sc) >> 8)
        print(f"  z={z:>4}  sy={screen_y(z):>3}  scale={sc:>5}  sx={sx:>4}")

    # --- emit mode7_project.inc ---
    lines = [
        "; =============================================================================",
        "; mode7_project.inc — rail-shooter pseudo-3D projection LUT (GENERATED)",
        "; =============================================================================",
        "; Pinhole (1/z) projection table, decoupled from the Mode 7 affine matrix.",
        "; The Mode 7 grid is the visual backdrop only; obstacles ride this projection.",
        "; Consumed by engine/mode7_project.asm. PURE ARITHMETIC from the pinhole",
        "; constants — no ROM/HDMA readback. Regenerate:",
        ";   PYTHONPATH=. python3 templates/railshooter/assets/make_project_lut.py",
        ";",
        "; DEPTH AXIS = z in WORLD PIXELS ahead of the camera (caller carries z",
        "; directly; no 256x scaling). The caller buckets z by >> PROJ_Q_LOG2.",
        ";",
        f"; pinhole params: HORIZON_Y={HORIZON_Y} CAM_H={CAM_H} FOCAL={FOCAL} "
        f"Z_NEAR={Z_NEAR} Z_FAR={Z_FAR}",
        "; projection:",
        ";   screen_y(z) = clamp(HORIZON_Y + CAM_H*256/z, HORIZON_Y, 223)",
        ";   scale(z)    = FOCAL*256/z          (.8 perspective factor)",
        ";   screen_x    = 128 + ((obj_x-cam_x) * scale) >> 8",
        f"; z range covered: 0..{(PROJ_N - 1) * PROJ_Q} in steps of {PROJ_Q} world px.",
        "; =============================================================================",
        "",
        f"PROJ_Q       = {PROJ_Q}        ; world-px per bucket",
        f"PROJ_Q_LOG2  = {PROJ_Q.bit_length() - 1}        ; log2(PROJ_Q) — bucket = z >> this",
        f"PROJ_N       = {PROJ_N}       ; bucket count",
        f"PROJ_DMAX    = {(PROJ_N - 1) * PROJ_Q}      ; max projectable depth z (world px)",
        "",
        "; size-tier z thresholds (nearer = bigger; tier 0 largest .. 3 smallest)",
        f"PROJ_TIER_T0 = {TIER_T0}",
        f"PROJ_TIER_T1 = {TIER_T1}",
        f"PROJ_TIER_T2 = {TIER_T2}",
        "",
        "; --- scanline byte per z bucket (screen_y the object's centre sits on) ---",
        "proj_scanline:",
    ]
    for row_start in range(0, PROJ_N, 16):
        chunk = table[row_start:row_start + 16]
        lines.append("    .byte " + ", ".join(f"{e[0]}" for e in chunk))
    lines += ["", "; --- scale word per z bucket (.8 perspective factor = FOCAL*256/z) ---",
              "proj_xscale:"]
    for row_start in range(0, PROJ_N, 8):
        chunk = table[row_start:row_start + 8]
        lines.append("    .word " + ", ".join(f"${e[1]:04X}" for e in chunk))
    lines.append("")

    out = HERE / "mode7_project.inc"
    out.write_text("\n".join(lines))
    print(f"\nwrote {out} ({PROJ_N} buckets)")


if __name__ == "__main__":
    main()
