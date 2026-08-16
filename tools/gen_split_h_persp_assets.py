#!/usr/bin/env python3
"""gen_split_h_persp_assets.py — the split_h_persp_demo rail's art, as .bin blobs.

Emits into $(BUILD)/assets (deterministic, byte-identical on re-run):

    shp_map.bin        32,768 B  the interleaved Mode 7 VRAM blob — the
                                 warm/cool checker world (128x128 tilemap in
                                 the even bytes, four solid 8bpp CHR tiles in
                                 the odd)
    shp_pal.bin            10 B  five BGR555 words, CGRAM indices 0..4
    shp_poseA_ab.bin   28,672 B  camera A's ROTATION set: 64 headings x a
    shp_poseA_cd.bin   28,672 B  band-local 112-line [A,B] / [C,D] pose,
                                 448 B each, s8.8 LE, in heading order
    shp_poseB_ab.bin    3,584 B  camera B's ZOOM set: 8 near-scale poses of
    shp_poseB_cd.bin    3,584 B  the same shape, in zoom-index order

THE TWO POSE SETS ARE THE RAIL, and the fact that there are TWO of them —
indexed by DIFFERENT parameters — is the point. When a table replaces a
runtime solve, the question that decides whether it really supplies the
feature is *what the table is indexed by*: `sh2_rom`'s set is indexed by
HEADING at one fixed perspective, and this rail's camera B animates its SCALE.
So camera A reads a heading-indexed set (`shp_poseA_*`) and camera B a
zoom-indexed one (`shp_poseB_*`), and neither is a re-parameterisation of the
other. Both are
band-local: index 0 is the BAND's first scanline, which is what lets band 2
re-start its 112-line table at scanline 112 with one HDMA index entry.

THE PERSPECTIVE RAMP, and its two parameter sets. A per-scanline Mode 7 floor
is a hyperbola in the band-local row k:

    S(k) = K / (k + k0)          k0 = (N-1)*s_near / (s_far - s_near)
                                 K  = s_far * k0

which passes through S(0) = s_far at the band's top and S(N-1) = s_near at its
bottom. This is the same closed form `tools/gen_pose_tables.py` uses, derived
here from the endpoints rather than imported. The parameters: camera A takes
`A_S0 = 320` / `A_S1 = 96`, camera B `B_S0 = 512`. Camera B's eight-pose zoom
loop steps its near-scale, so the poses walk BOTH ends of its ramp with index
0 pinned exactly onto camera A's pair — see ZOOM_STEPS below for why that
pinning is a test instrument and not a coincidence.

Rotation, at heading h of 64 (camera A's angle drifts every frame):

    A = round(S(k) cos t)   B = -round(S(k) sin t)   C = -B   D = A
    t = 2*pi*h/64

`C = -B, D = A` is the relation the vendored pose tables satisfy (recorded in
vendor/art/split_h_2p/README.md), and it is what makes a rotation FREE: the
per-band origin already zeroes the matrix term at the band's bottom-centre, so
the pose rotates about that point with no new origin math.

SELF-CONTAINED BY REQUIREMENT. `make bare-check` runs from a clone with
nothing but this tree on disk, so this file imports nothing and names no path
outside the repo. What it DOES read is `vendor/art/`, and reads it as a REFUSAL
ORACLE:

  * the 32,768-byte world is compared byte-for-byte against
    `vendor/art/split_h_2p/ref_checker_map.bin` — this rail and
    `split_h_2p_demo` want byte-identical checker maps
    (md5 3862ea7ca2e418846c273a5b47e392b0, measured
    2026-08-07), so the file this rail needs was already vendored. See
    vendor/art/split_h_persp/README.md.
  * the five palette words are parsed out of
    `vendor/art/split_h_persp/ref_palette.inc`, which is this rail's own
    (its colours differ from split_h_2p_demo's).

An ABSENT oracle is a refusal, not a warning, here as on the sh2
generator: a gate that passes when its evidence is missing is not a gate.

WHAT THE ORACLES ACTUALLY PROVE, because they are what the rendered tests read:

  * THE WARM/COOL RED SPLIT. The stripe term puts a COOL stripe (R = 0)
    centred on world X 512 and a WARM one (R > 0) centred on world X 768 — the
    two cameras' positions. Band 1 therefore carries no red and band 2 does,
    and that separation IS the rail's per-band position oracle. The palette
    check asserts the separation on top of the byte match, so a re-theme that
    softened it fails here before it reaches a screenshot.
  * THE CHECKER GEOMETRY. BLOCK = 4 world tiles is a 32-px world square; the
    on-screen period is 32*256/S(k) px, which is what makes the two bands'
    trapezoids measurable without a landmark to alias against.

The POSE sets have no reference oracle and none is claimed: there is no
committed table to compare them to, because a runtime solve leaves no table
behind. They are gated by CONSTRUCTION instead — the
emit-time asserts below check the ramp's endpoints, the `C = -B, D = A`
relation, the s16 range and the zoom set's index-0 pinning — and by the
rendered picture, which `tests/test_split_h_persp_demo.py` predicts pixel for
pixel from these very bytes through Mesen's own Mode 7 transform.

Run:
    python3 tools/gen_split_h_persp_assets.py build/assets
"""
from __future__ import annotations

import argparse
import math
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAP_ORACLE = REPO / "vendor" / "art" / "split_h_2p" / "ref_checker_map.bin"
PAL_ORACLE = REPO / "vendor" / "art" / "split_h_persp" / "ref_palette.inc"

# --- the world ---------------------------------------------------------------
# 128x128 tiles is the Mode 7 plane's fixed size; BLOCK is
# the checker square in tiles; STRIPE is the warm/cool period in tiles; PHASE
# offsets it so a COOL stripe centres on world tile 64 (world X 512).
MAP_T = 128
TILE_PX = 8
BLOCK = 4
STRIPE = 32
PHASE = 16
TILE_BYTES = TILE_PX * TILE_PX          # 8bpp: one byte per pixel

# --- the split ---------------------------------------------------------------
# SEAM: the top band is scanlines [0, 112) and
# the bottom [112, 224). Both bands are their OWN complete 112-line frustum —
# band-local, sh2_cam's shape — which is why one number describes both.
SEAM = 112
LINES = 224
BAND_ROWS = SEAM

# --- the two cameras' perspective parameters ---------------------------------
A_S0 = 320                              # camera A far scale (band top),  8.8
A_S1 = 96                               # camera A near scale (band bottom)
HEADINGS = 64                           # camera A's rotation set

# Camera B's ZOOM LOOP: eight poses stepping BOTH ends of its ramp, so band 2
# visibly dollies. Index 0 is pinned EXACTLY onto camera A's pair, which makes
# driving the zoom to its floor a runtime NON-VACUITY CONTROL: band 2's matrix
# collapses onto band 1's inside the shipping binary, so the "two distinct
# cameras" period claim must die there — while the per-band POSITION claim
# survives, because the world positions are untouched by the zoom axis. The
# alternative is a pair of purpose-built control binaries, one per half; here
# both halves fail independently at runtime inside the shipping ROM.
# B_S0 = 512 is index 6.
ZOOM_POSES = 8
ZOOM_STEPS = [(A_S0 + 32 * i, A_S1 - 8 * i) for i in range(ZOOM_POSES)]

POSE_BYTES = BAND_ROWS * 4              # 448 B per band-local pose


def build_map() -> bytes:
    """The interleaved Mode 7 blob: tilemap even bytes, 8bpp CHR odd bytes."""
    tilemap = bytearray(MAP_T * MAP_T)
    for row in range(MAP_T):
        for col in range(MAP_T):
            parity = ((row // BLOCK) ^ (col // BLOCK)) & 1
            warm = ((col + PHASE) // STRIPE) & 1
            tilemap[row * MAP_T + col] = parity + (2 if warm else 0)
    chr_bytes = bytearray(MAP_T * MAP_T)
    # tile k = solid palette index k+1: 0->cool dark, 1->cool light,
    # 2->warm dark, 3->warm light.
    for k in range(4):
        chr_bytes[k * TILE_BYTES:(k + 1) * TILE_BYTES] = bytes([k + 1]) * TILE_BYTES
    out = bytearray(2 * MAP_T * MAP_T)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


def parse_palette(text: str) -> list[int]:
    """The five BGR555 words, in CGRAM index order, out of the oracle .inc."""
    words = [int(m, 16) for m in re.findall(r"^\s*COLOR_\w+\s*=\s*\$([0-9A-Fa-f]{4})",
                                            text, re.M)]
    if len(words) != 5:
        sys.exit(f"palette oracle: expected 5 COLOR_* equates, parsed {len(words)}")
    return words


def scale_ramp(s_far: int, s_near: int) -> list[int]:
    """S(k) for k in 0..BAND_ROWS-1 — the hyperbolic per-scanline floor ramp."""
    n = BAND_ROWS - 1
    k0 = n * s_near / (s_far - s_near)
    kk = s_far * k0
    return [int(round(kk / (k + k0))) for k in range(BAND_ROWS)]


def pose(s_far: int, s_near: int, heading: int, headings: int) -> tuple[bytes, bytes]:
    """One band-local pose: its 448-byte [A,B] table and its [C,D] partner."""
    t = 2.0 * math.pi * heading / headings
    cos_t, sin_t = math.cos(t), math.sin(t)
    ab, cd = bytearray(), bytearray()
    for s in scale_ramp(s_far, s_near):
        a = int(round(s * cos_t))
        b = -int(round(s * sin_t))
        ab += struct.pack("<hh", a, b)
        cd += struct.pack("<hh", -b, a)          # C = -B, D = A
    return bytes(ab), bytes(cd)


def build_poses() -> dict[str, bytes]:
    """Camera A's heading set and camera B's zoom set, both band-local."""
    a_ab, a_cd = bytearray(), bytearray()
    for h in range(HEADINGS):
        ab, cd = pose(A_S0, A_S1, h, HEADINGS)
        a_ab += ab
        a_cd += cd
    b_ab, b_cd = bytearray(), bytearray()
    for s_far, s_near in ZOOM_STEPS:
        ab, cd = pose(s_far, s_near, 0, HEADINGS)   # camera B never rotates
        b_ab += ab
        b_cd += cd
    return {"shp_poseA_ab.bin": bytes(a_ab), "shp_poseA_cd.bin": bytes(a_cd),
            "shp_poseB_ab.bin": bytes(b_ab), "shp_poseB_cd.bin": bytes(b_cd)}


def check_poses(blobs: dict[str, bytes], pal: list[int]) -> None:
    """Emit-time gates. Nothing here is a re-run of the code above."""
    # sizes, from the model rather than from the bytes
    assert len(blobs["shp_poseA_ab.bin"]) == HEADINGS * POSE_BYTES
    assert len(blobs["shp_poseA_cd.bin"]) == HEADINGS * POSE_BYTES
    assert len(blobs["shp_poseB_ab.bin"]) == ZOOM_POSES * POSE_BYTES
    assert len(blobs["shp_poseB_cd.bin"]) == ZOOM_POSES * POSE_BYTES
    # a slice must fit ONE LoROM window so `ptr = base + i*448` never carries
    if HEADINGS * POSE_BYTES > 0x8000:
        sys.exit("shp_poseA: heading set exceeds one LoROM window")

    def word(buf: bytes, off: int) -> int:
        return struct.unpack_from("<h", buf, off)[0]

    # camera A, heading 0: the ramp's ENDPOINTS are the declared scales
    if word(blobs["shp_poseA_ab.bin"], 0) != A_S0:
        sys.exit(f"shp_poseA row 0 is {word(blobs['shp_poseA_ab.bin'], 0)}, want {A_S0}")
    last = (BAND_ROWS - 1) * 4
    if word(blobs["shp_poseA_ab.bin"], last) != A_S1:
        sys.exit(f"shp_poseA row {BAND_ROWS - 1} is "
                 f"{word(blobs['shp_poseA_ab.bin'], last)}, want {A_S1}")
    # the ramp is MONOTONE DECREASING — a floor that recedes
    prev = 1 << 30
    for k in range(BAND_ROWS):
        s = word(blobs["shp_poseA_ab.bin"], k * 4)
        if s > prev:
            sys.exit(f"shp_poseA ramp is not monotone at row {k}")
        prev = s
    # camera B index 0 is camera A's pose EXACTLY (the collapse control)
    if blobs["shp_poseB_ab.bin"][:POSE_BYTES] != blobs["shp_poseA_ab.bin"][:POSE_BYTES]:
        sys.exit("shp_poseB index 0 is not camera A's heading-0 pose")
    if blobs["shp_poseB_cd.bin"][:POSE_BYTES] != blobs["shp_poseA_cd.bin"][:POSE_BYTES]:
        sys.exit("shp_poseB index 0 CD is not camera A's heading-0 pose")
    # ...and index 7 is a MEASURABLY different trapezoid
    if word(blobs["shp_poseB_ab.bin"], (ZOOM_POSES - 1) * POSE_BYTES) <= A_S0:
        sys.exit("shp_poseB's last zoom pose does not steepen the ramp")
    # C = -B and D = A, everywhere, in both sets
    for name in ("A", "B"):
        ab, cd = blobs[f"shp_pose{name}_ab.bin"], blobs[f"shp_pose{name}_cd.bin"]
        for off in range(0, len(ab), 4):
            if word(cd, off) != -word(ab, off + 2) or word(cd, off + 2) != word(ab, off):
                sys.exit(f"shp_pose{name}: C = -B / D = A violated at byte {off}")
    # the rotation is REAL: heading 16 of 64 is a quarter turn, so A ~ 0
    quarter = (HEADINGS // 4) * POSE_BYTES
    if abs(word(blobs["shp_poseA_ab.bin"], quarter)) > 1:
        sys.exit("shp_poseA quarter-turn heading does not zero A")
    # the palette's RED SEPARATION — the per-band position oracle
    red = [w & 31 for w in pal]
    if red[1] or red[2]:
        sys.exit(f"palette: the COOL pair must have red 0, got {red[1:3]}")
    if red[3] <= 0 or red[4] <= 0:
        sys.exit(f"palette: the WARM pair must carry red, got {red[3:5]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()

    for oracle in (MAP_ORACLE, PAL_ORACLE):
        if not oracle.is_file():
            sys.exit(f"ORACLE ABSENT: {oracle} — refusing to emit "
                     f"(a gate that passes without its evidence is not a gate)")

    world = build_map()
    want = MAP_ORACLE.read_bytes()
    if world != want:
        sys.exit(f"MAP DISAGREES WITH THE ORACLE ({MAP_ORACLE.name}): "
                 f"{sum(a != b for a, b in zip(world, want))} of {len(want)} bytes differ")

    pal = parse_palette(PAL_ORACLE.read_text())
    pal_bytes = b"".join(struct.pack("<H", w) for w in pal)

    blobs = {"shp_map.bin": world, "shp_pal.bin": pal_bytes}
    blobs.update(build_poses())
    check_poses(blobs, pal)

    args.outdir.mkdir(parents=True, exist_ok=True)
    for name, data in blobs.items():
        (args.outdir / name).write_bytes(data)
        print(f"  {name:20s} {len(data):7d} B")
    print(f"gen_split_h_persp_assets OK: map + palette match the oracle; "
          f"{HEADINGS} headings + {ZOOM_POSES} zoom poses emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
