#!/usr/bin/env python3
"""gen_split_h_2p_assets.py — the split_h_2p_demo rail's art, as .bin blobs.

Emits into $(BUILD)/assets (deterministic, byte-identical on re-run):

    sh2_map.bin       32,768 B  interleaved Mode 7 VRAM blob — the warm/cool
                                checker world (tilemap in the even bytes,
                                four solid 8bpp CHR tiles in the odd)
    sh2_pal.bin           10 B  five BGR555 words, CGRAM indices 0..4
    sh2_pose1_ab.bin     448 B  fixed-angle per-scanline [A,B] table
    sh2_pose1_cd.bin     448 B  ...and its [C,D] partner (C = -B, D = A)
    sh2_pose256_ab_sK.bin        the 256-heading set, sliced into FOUR 28,672 B
    sh2_pose256_cd_sK.bin        bank slices each (K = 0..3): pose (64K + j)
                          × 4    at slice K, offset j*448. The rotation
                                streams these — a slice is exactly 64 poses so
                                the runtime address is
                                ptr = slice_base + (h & 63)*448,
                                bank = base_bank + (h >> 6).
    sh2_move256.bin    1,024 B  256 forward vectors, (dx, dy) s16 in 8.8:
                                entry h = round(2*256*(-sin, -cos)(2πh/256)) —
                                a CONSTANT 2.0 px/frame at every heading.

The SPRITE PROJECTOR is the same geometry, inverted:

    sh2_sp_sincos.bin  1,024 B  256 x (cos, sin) s8.8, magnitudes CLAMPED to
                                255 so both operands fit the 8x8 hardware
                                multiply after the sign/magnitude split.
    sh2_sp_vk.bin        256 B  the BUILD-TIME INVERSE of the floor ramp:
                                d -> band-local row k, where d is the forward
                                distance in world px and g(k) = (112-k)*S(k)/256
                                is what the floor samples at row k. $FF = cull.
                                This is the whole reason the projector needs no
                                divide: the floor's own ramp is inverted once,
                                offline, into a 256-entry table.
    sh2_sp_recip_lo.bin  112 B  low byte of recip(k) = round(65536 / S8.8(k))
    sh2_sp_recip_hi.bin  112 B  ...and its 9th bit (recip is 171..410), so
                                sxoff = (|u|*recip_lo)>>8 (+|u| if hi) is ONE
                                8x8 multiply rather than a 16x16 divide.
    sh2_sp_tier.bin      112 B  row -> size tier (0..4), the FULL ladder.
    sh2_sp_chr.bin     2,048 B  64 OBJ tiles (4bpp): five character-token size
                                variants — three 16x16 (names 0/2/4) and two
                                32x32 (names 8/12), colour index 1 only, the
                                32x32 pair padded to full 4x4 name blocks so a
                                32x32 OBJ's sixteen name fetches all land
                                inside the set.
    sh2_ents.bin         512 B  the SWARM: 64 entity records of eight
                                bytes — +0 x u16, +2 y u16, +4 (wp<<8 | heading),
                                +6 (fracy<<8 | fracx) — copied wholesale into
                                the entity table at scene enter. Entities 0/1
                                are the two PLAYERS (their x/y is overwritten
                                from the cameras every frame); 2.. are AI
                                waypoint followers. The live count is 24 and
                                lives in WRAM, poke-able 1..64, which is how
                                the cadence sweep walks the curve.
    sh2_way.bin          128 B  8 waypoint loops x 4 targets, (x, y) u16. The
                                AI's whole world model.
                                NEITHER is a reference blob and neither has an
                                oracle: they are this rail's own scenario,
                                authored against this rail's own world, so
                                they are gated by SIMULATION instead (see
                                swarm_world) — the exact 256-state camera cycle
                                is walked with the AI running, and the coverage
                                the tests depend on is asserted at emit time.

SELF-CONTAINED BY REQUIREMENT. The build runs from a bare checkout with
nothing but this tree on disk, so this file imports nothing and names no path
outside the repo. Every algorithm the vendored oracle's own README states is
re-derived here from that description, and `tools/gen_pose_tables.py` is the
one in-tree module it shares.

...which is what makes `vendor/art/split_h_2p/` a real oracle rather than an
echo: those blobs came out of a different program on a different run, and this
generator REFUSES to write anything that disagrees with them — or anything at
all if they are ABSENT, which is a refusal too (a gate that passes when its
evidence is missing is not a gate). See that directory's README for
the provenance and the exact arguments, and `tests/test_split_h_2p_assets.py`
for both directions asserted.

THE TWO THINGS THE ORACLE ACTUALLY PROVES, because they are the two the rail's
tests read off the framebuffer:

  * THE WARM/COOL RED SPLIT. The checker's stripe term puts a COOL stripe
    (R=0) centred on world X 512 and a WARM one (R=31) centred on world X 768 —
    the two cameras' start positions. Band 2 therefore carries red and band 1
    does not, and that separation IS the rail's per-band position oracle. It is
    deliberately maximal; a re-theme that softened it would break the test
    surface, and this gate would catch the byte change first.
  * THE PERSPECTIVE RAMP. `S(k) = K/(k+k0)` through (1.5 at line 0, 0.625 at
    line 111), times 256 — the 8.8 scale the PPU multiplies each scanline's
    world step by. Its ends are 384 and 160; getting k0 or the rounding wrong
    changes hundreds of bytes and the floor's horizon with them.
  * THE 256-HEADING SET AND ITS SLICING. The whole subject of this rail is that
    each band streams its OWN heading, and the runtime address arithmetic
    (`(h & 63)*448` inside a slice, `h >> 6` selecting the bank) is only valid
    if the blob really is 256 contiguous 448-byte poses in heading order. A
    byte-identical match against the committed 114,688-byte reference blobs is
    what proves the ordering, the per-pose stride and the rotation relation
    (C = -B, D = A) all at once — and the slices this emits are cut FROM the
    matched blob, so the cut is checked against the whole rather than
    separately.

Run:
    python3 tools/gen_split_h_2p_assets.py build/assets
"""
from __future__ import annotations

import argparse
import math
import random
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "vendor" / "art" / "split_h_2p"

# --- the world ---------------------------------------------------------------
# 128x128 tiles is the Mode 7
# plane's fixed size; BLOCK is the checker square in tiles; STRIPE is the
# warm/cool period in tiles; PHASE offsets it so a COOL stripe centres on world
# X 512 and a WARM one on 768.
MAP_W = 128
TILE_WORDS = 64                  # bytes of 8bpp CHR in one 8x8 tile
BLOCK = 4
STRIPE = 32
PHASE = 16
TILE_PX = 8                      # a Mode 7 tile is 8x8 texels
WORLD_PX = MAP_W * TILE_PX       # 1024 — the plane's wrap period

# --- the pose tables ---------------------------------------------------------
# gen_pose_tables.py's defaults, which is what `--angles 1` was run at.
LINES = 112                      # scanlines per band
SCALE_FAR = 1.5                  # 8.8 scale at the band's top line
SCALE_NEAR = 0.625               # ...and at its bottom line
POSE_BYTES = LINES * 4

# --- the 256-heading rotation set --------------------------------------------
# gen_pose_tables.py's slice model, which is what makes the ROM's pointer math
# work: SLICE_POSES poses per LoROM bank slice, pose (64k + j) at slice k
# offset j*448. 64 x 448 = 28,672 B, so a slice fits one 32 KB window with room
# to spare for the small claims that pack in beside it.
POSES = 256
SLICE_POSES = 64
SLICE_BYTES = SLICE_POSES * POSE_BYTES
SLICES = POSES // SLICE_POSES

# 8.8 forward speed: 2.0 world px/frame at every heading (2 * 256).
MOVE_SCALE = 512.0

# The five CGRAM words, in index order. Parsed from the vendored oracle when it
# is present (see palette()); these are the fallback for a tree without it.
PAL_NAMES = ("COLOR_BACKDROP", "COLOR_COOL_DARK", "COLOR_COOL_LIGHT",
             "COLOR_WARM_DARK", "COLOR_WARM_LIGHT")
PAL_FALLBACK = (0x5400, 0x0DA0, 0x1340, 0x00DF, 0x023F)


# --- the world blob ----------------------------------------------------------
def tilemap() -> bytes:
    """128x128 tile ids: checker parity, plus 2 inside a warm stripe.

    Ids 0..3 index CGRAM 1..4 (the CHR below is what adds the +1), so the four
    ids are cool-dark, cool-light, warm-dark, warm-light.
    """
    tm = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            parity = ((row // BLOCK) ^ (col // BLOCK)) & 1
            warm = ((col + PHASE) // STRIPE) & 1
            tm[row * MAP_W + col] = parity + (2 if warm else 0)
    return bytes(tm)


def chr_bytes() -> bytes:
    """Four SOLID 8bpp tiles; tile k is 64 bytes of palette index k+1.

    Index 0 is skipped deliberately: in Mode 7 an 8bpp pixel value is an
    ABSOLUTE CGRAM index and index 0 is also the backdrop slot, so a tile of
    zeros would render as backdrop rather than as floor. The rest of the 16 KB
    is left zero — the tilemap only ever names ids 0..3.
    """
    ch = bytearray(MAP_W * MAP_W)
    for k in range(4):
        ch[k * TILE_WORDS:(k + 1) * TILE_WORDS] = bytes([k + 1]) * TILE_WORDS
    return bytes(ch)


def world_blob() -> bytes:
    """The interleave the PPU actually reads: tilemap even, CHR odd.

    This layout is what lets the whole plane upload as ONE mode-1 DMA — B, B+1
    alternating is $2118, $2119, which is the interleave.
    """
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap()
    out[1::2] = chr_bytes()
    return bytes(out)


# --- the pose tables ---------------------------------------------------------
def scale_ramp() -> list[int]:
    """True-perspective hyperbolic ramp, 8.8 fixed point per scanline.

    S(k) = K/(k + k0) with S(0) = SCALE_FAR, S(LINES-1) = SCALE_NEAR. The top
    of the band samples MORE world per pixel (smaller features, receding toward
    the horizon), so scale_far > scale_near.
    """
    k0 = (LINES - 1) * SCALE_NEAR / (SCALE_FAR - SCALE_NEAR)
    big_k = SCALE_FAR * k0
    ramp = []
    for k in range(LINES):
        fx = round(big_k / (k + k0) * 256.0)
        if not (1 <= fx <= 0x7FFF):
            raise SystemExit(f"gen_split_h_2p_assets: scale at line {k} out "
                             f"of s8.8 range ({fx})")
        ramp.append(fx)
    return ramp


def pose_blobs(angle_rad: float) -> tuple[bytes, bytes]:
    """One heading's band-local AB and CD tables. C = -B and D = A: the matrix
    is a rotation times a per-line scale, so the pair is fully determined by
    (A, B) and the tests assert exactly that relation."""
    ramp = scale_ramp()
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    ab = bytearray()
    cd = bytearray()
    for fx in ramp:
        a = round(fx * c)
        b = round(fx * s)
        ab += struct.pack("<hh", a, b)
        cd += struct.pack("<hh", -b, a)
    return bytes(ab), bytes(cd)


def pose_set(n: int) -> tuple[bytes, bytes]:
    """The whole n-heading set, poses concatenated in HEADING ORDER.

    Heading h is `2*pi*h/n`, and pose h therefore occupies bytes
    `[h*POSE_BYTES, (h+1)*POSE_BYTES)` of each blob. That contiguity is not a
    convenience: it IS the runtime address arithmetic, so the ordering is what
    the oracle comparison in main() proves.
    """
    ab = bytearray()
    cd = bytearray()
    for h in range(n):
        a, c = pose_blobs(2.0 * math.pi * h / n)
        ab += a
        cd += c
    return bytes(ab), bytes(cd)


def slice_of(blob: bytes, k: int) -> bytes:
    """Bank slice k of a pose blob: SLICE_POSES poses, 28,672 B.

    Cut from the blob the oracle already matched, so the cut is checked against
    the whole rather than being a second unverified derivation. Pose (64k + j)
    lands at offset j*448 of slice k — which is exactly what the ROM's
    `ptr = slice_base + (h & 63)*448`, `bank = base + (h >> 6)` addresses.
    """
    lo = k * SLICE_BYTES
    piece = blob[lo:lo + SLICE_BYTES]
    if len(piece) != SLICE_BYTES:
        raise SystemExit(f"gen_split_h_2p_assets: slice {k} is {len(piece)} B, "
                         f"must be {SLICE_BYTES}")
    return piece


# --- the forward-vector LUT --------------------------------------------------
def move_lut(n: int) -> bytes:
    """n forward vectors, (dx, dy) as two s16 words in 8.8 fixed point.

    `entry h = round(2*256*(-sin, -cos)(2*pi*h/n))`: screen-up from the band's
    bottom-centre pivot maps to world (-sin, -cos) under the pose rotation, and
    the 2*256 scale is a CONSTANT 2.0 px/frame at EVERY heading. The rail keeps
    a per-axis 8.8 fractional accumulator, which is what removes the speed
    pulse and the direction staircase an integer velocity produces.
    """
    out = bytearray()
    for h in range(n):
        a = 2.0 * math.pi * h / n
        out += struct.pack("<hh", round(-MOVE_SCALE * math.sin(a)),
                           round(-MOVE_SCALE * math.cos(a)))
    return bytes(out)


# --- the palette -------------------------------------------------------------
def palette(notes: list) -> bytes:
    """Five BGR555 words, little-endian, CGRAM indices 0..4.

    Read from the vendored `.inc` so the shipped bytes and the oracle cannot
    drift apart silently. PAL_FALLBACK is the value under test, not a
    substitute for the oracle: an absent `.inc` is a REFUSAL like every other
    absent reference (see missing_oracle).
    """
    words = list(PAL_FALLBACK)
    src = VENDOR / "ref_palette.inc"
    if not src.is_file():
        raise missing_oracle(src.name)
    text = src.read_text()
    parsed = []
    for name in PAL_NAMES:
        m = re.search(rf"^{name}\s*=\s*\$([0-9A-Fa-f]{{1,4}})\s*(;.*)?$",
                      text, re.MULTILINE)
        if m is None:
            raise SystemExit(f"gen_split_h_2p_assets: {src.name} has no "
                             f"{name} equate")
        parsed.append(int(m.group(1), 16))
    if parsed != words:
        raise SystemExit(
            "gen_split_h_2p_assets: the palette disagrees with "
            f"{src.name} — got {[hex(w) for w in words]}, oracle "
            f"{[hex(w) for w in parsed]}. This generator and the oracle "
            "cannot both be right; do not re-vendor to make this go away.")
    notes.append(f"palette: byte-identical to {src.name} (5 words)")
    # The rail's own invariant, asserted rather than assumed: the two cool
    # colours carry NO red and the two warm ones carry the maximum. This is the
    # per-band position oracle every framebuffer test in the suite reads.
    for idx in (1, 2):
        if (words[idx] & 0x1F) != 0:
            raise SystemExit(f"gen_split_h_2p_assets: cool colour {idx} has "
                             f"red {words[idx] & 0x1F}, must be 0 — it is the "
                             f"per-band position oracle")
    for idx in (3, 4):
        if (words[idx] & 0x1F) != 31:
            raise SystemExit(f"gen_split_h_2p_assets: warm colour {idx} has "
                             f"red {words[idx] & 0x1F}, must be 31 — it is the "
                             f"per-band position oracle")
    return b"".join(struct.pack("<H", w) for w in words)


# =============================================================================
# The sprite projector's tables, and the cast they place
# =============================================================================
# Everything below is the INVERSE of the floor above, and it is built from the
# SAME `scale_ramp()` — never a second copy of it. That sharing is the point:
# the floor draws row k at world-forward distance g(k), and sp_vk is exactly
# that function inverted, so a change to SCALE_FAR/SCALE_NEAR moves the floor
# and the sprites together or the oracle refuses both.

SP_PIVOT = LINES                 # the y-term zero: band-local row 112
SP_CLAMP = 255                   # sincos magnitude clamp — the 8x8 operand
SP_WORLD_DIAM = 14               # a marker's world-space diameter, in px
SP_CHEB = 176                    # the pre-cull's Chebyshev half-window

# (apparent-diameter upper bound in px, CHR name, half box px, 32x32?)
SP_TIERS = ((12.5, 0, 8, False), (15.0, 2, 8, False), (17.5, 4, 8, False),
            (19.5, 8, 16, True), (1e9, 12, 16, True))
SP_SEAM_LO = 9                   # band 2 culls k < this  (its TOP is the seam)
SP_SEAM_HI = 95                  # band 1 culls k > this  (its BOTTOM is)
SP_XOFF_MAX = 160                # |sx - 128| past which even a 32x32 is gone

SP_TILE_BYTES = 32               # one 8x8 4bpp tile
SP_CHR_TILES = 64                # the whole name block the OBJ base sees


def sp_g(ramp: list[int], k: int) -> float:
    """The world-forward distance the floor samples at band-local row k."""
    return (SP_PIVOT - k) * ramp[k] / 256.0


def sincos_lut() -> bytes:
    """256 x (cos, sin) s8.8, CLAMPED to +-SP_CLAMP.

    The clamp is not cosmetic: it is what makes the projector's dot products
    8x8 rather than 16x16. A magnitude of exactly 256 would not fit $4203, and
    one entry per quadrant would be 256 without it.
    """
    out = bytearray()
    for h in range(POSES):
        a = 2.0 * math.pi * h / POSES
        c = max(-SP_CLAMP, min(SP_CLAMP, round(256.0 * math.cos(a))))
        s = max(-SP_CLAMP, min(SP_CLAMP, round(256.0 * math.sin(a))))
        out += struct.pack("<hh", c, s)
    return bytes(out)


def vk_lut(ramp: list[int]) -> bytes:
    """d (world px in front of the pivot) -> band-local row k, or $FF.

    The window is [1, g(0)] — beyond the horizon there is no row, and at or
    behind the pivot the camera sees nothing. Ties go to the LOWEST k, which is
    `min`'s own rule and is what the oracle blob was built with.
    """
    out = bytearray(1 << 8)
    top = int(sp_g(ramp, 0))
    for d in range(1 << 8):
        if d < 1 or d > top:
            out[d] = 0xFF
        else:
            out[d] = min(range(LINES), key=lambda k: abs(sp_g(ramp, k) - d))
    return bytes(out)


def recip_luts(ramp: list[int]) -> tuple[bytes, bytes]:
    """recip(k) = round(65536 / S8.8(k)), split into low byte and 9th bit."""
    r = [round((1 << 16) / fx) for fx in ramp]
    if not all(0 <= v < (1 << 9) for v in r):
        raise SystemExit(f"gen_split_h_2p_assets: recip out of 9-bit range "
                         f"({min(r)}..{max(r)}) — the >>8 + carry core assumes "
                         f"it fits nine bits")
    return bytes(v & 0xFF for v in r), bytes(v >> 8 for v in r)


def tier_ladder(ramp: list[int]) -> bytes:
    """row -> size tier: the apparent diameter of an SP_WORLD_DIAM marker.

    A world disc of diameter D at a row whose 8.8 scale is S(k) covers
    D*256/S(k) screen px, so the ladder is a pure function of the ramp — the
    same ramp the floor streams. Monotonic non-decreasing in k by construction,
    asserted below because the runtime reads it as a ladder.
    """
    out = bytearray(LINES)
    for k in range(LINES):
        px = SP_WORLD_DIAM * 256.0 / ramp[k]
        out[k] = next((t for t, (ub, *_r) in enumerate(SP_TIERS) if px < ub),
                      len(SP_TIERS) - 1)
    if list(out) != sorted(out):
        raise SystemExit("gen_split_h_2p_assets: the tier ladder is not "
                         "monotonic in k — a nearer row must never be smaller")
    if set(out) != set(range(len(SP_TIERS))):
        raise SystemExit(f"gen_split_h_2p_assets: the tier ladder uses "
                         f"{sorted(set(out))}, not every tier — a step nobody "
                         f"reaches is a rung the size test cannot see")
    return bytes(out)


def draw_token(size: int, height: float) -> list[list[int]]:
    """A top-down character token of pixel HEIGHT `height`, centred in a
    size x size tile: a round head fused onto a tapered torso, one
    vertically-contiguous colour-1 silhouette. Height carries the size ladder —
    a far marker is a smaller token, which is the whole visual claim of the
    tier step."""
    img = [[0] * size for _ in range(size)]
    cc = (size - 1) / 2.0
    top = cc - height / 2.0
    bot = cc + height / 2.0
    r_head = 0.205 * height
    head_cy = top + r_head
    sh_top = head_cy + r_head * 0.55
    w_sh = 0.33 * height
    w_ba = 0.20 * height
    for y in range(size):
        for x in range(size):
            dxx = x - cc
            if dxx * dxx + (y - head_cy) ** 2 <= r_head * r_head:
                img[y][x] = 1                       # the head disc
                continue
            if sh_top <= y <= bot:                  # tapered torso
                t = (y - sh_top) / max(1e-6, (bot - sh_top))
                hw = w_sh + (w_ba - w_sh) * t
                if y > bot - hw:                    # rounded base
                    dy = y - (bot - hw)
                    hw = math.sqrt(max(0.0, hw * hw - dy * dy))
                if abs(dxx) <= hw:
                    img[y][x] = 1
    return img


def sprite_chr() -> bytes:
    """The 64-name OBJ block: five token sizes, plane 0 only (colour 1).

    A 16x16 OBJ reads {N, N+1, N+16, N+17} and a 32x32 reads the whole 4x4
    block from N — the +16 row step is hardware, which is why the names are
    0/2/4 for the small trio and 8/12 for the large pair, and why the 32x32
    variants' empty quadrant tiles are committed as EXPLICIT zeros rather than
    left to whatever neighbours the block.
    """
    out = bytearray(SP_CHR_TILES * SP_TILE_BYTES)

    def blit(img, name0):
        size = len(img)
        for ty in range(size // 8):
            for tx in range(size // 8):
                tile = name0 + ty * 16 + tx
                if tile >= SP_CHR_TILES:
                    raise SystemExit(f"gen_split_h_2p_assets: token at name "
                                     f"{name0} reaches name {tile}, outside "
                                     f"the {SP_CHR_TILES}-name block")
                for row in range(8):
                    p0 = 0
                    for col in range(8):
                        p0 = (p0 << 1) | img[ty * 8 + row][tx * 8 + col]
                    out[tile * SP_TILE_BYTES + row * 2] = p0
    for (_ub, name, half, big), height in zip(SP_TIERS,
                                              (10.0, 12.0, 14.0, 18.0, 22.0)):
        blit(draw_token(32 if big else 16, height), name)
        if height > 2 * half:
            raise SystemExit(f"gen_split_h_2p_assets: token height {height} "
                             f"exceeds the {2 * half}px box of name {name}")
    return bytes(out)


# --- the projection mirror ---------------------------------------------------
# A bit-exact integer mirror of m7_persp_project.asm. It is NOT a test oracle —
# the tests read OAM and the framebuffer — it exists so this generator can
# PROVE the cast it emits actually exercises what the tests will look for.
def sp_project(tabs, wx, wy, px, py, h, band_top, *, forward=False,
               nocull=False, tieroff=False):
    """(sx, sy, tier, k) or None. The cull ORDER here is the ASM's order."""
    sincos, vk, recip, tier = tabs
    c, s = struct.unpack_from("<hh", sincos, (h & (POSES - 1)) * 4)
    if forward:
        s = -s                                      # the FORWARD control
    dx = ((wx - px + 512) & 1023) - 512
    dy = ((wy - py + 512) & 1023) - 512
    adx, mdx = (-dx, True) if dx < 0 else (dx, False)
    ady, mdy = (-dy, True) if dy < 0 else (dy, False)
    if adx > SP_CHEB or ady > SP_CHEB:
        return None                                 # Chebyshev, no multiplies
    ac, mc = (-c, True) if c < 0 else (c, False)
    asn, ms = (-s, True) if s < 0 else (s, False)
    t1 = (adx * asn + 128) >> 8                     # v = dx*sin + dy*cos
    t2 = (ady * ac + 128) >> 8
    v = (-t1 if mdx ^ ms else t1) + (-t2 if mdy ^ mc else t2)
    if v >= 0:
        return None                                 # at or behind the pivot
    d = -v
    if d >= (1 << 8) or vk[d] == 0xFF:
        return None
    k = vk[d]
    if not nocull:                                  # the per-band SEAM guard
        if band_top == 0:
            if k > SP_SEAM_HI:
                return None
        elif k < SP_SEAM_LO:
            return None
    t1 = (adx * ac + 128) >> 8                      # u = dx*cos - dy*sin
    t2 = (ady * asn + 128) >> 8
    u = (-t1 if mdx ^ mc else t1) + (-t2 if mdy ^ (not ms) else t2)
    au = -u if u < 0 else u
    if au >= (1 << 8):
        return None
    r = recip[k]
    sxoff = ((au * (r & 0xFF)) >> 8) + (au if r >> 8 else 0)
    if sxoff >= SP_XOFF_MAX:
        return None
    sx = 128 - sxoff if u < 0 else 128 + sxoff
    return sx, band_top + k, (2 if tieroff else tier[k]), k


# --- the camera cycle, walked exactly ----------------------------------------
# The rail's state is EXACTLY PERIODIC with period POSES: h1 steps +1 and h2
# steps -1 each frame, and the move LUT's entries for h and h+128 are exact
# negatives, so one full turn returns both fraction accumulators AND both
# positions to their seeds. That is what makes "walk all 256 states" a complete
# enumeration rather than a sample, and it is asserted rather than assumed.
CAM1_0 = (WORLD_PX // 2, WORLD_PX // 2)             # split.asm's seeds
CAM2_0 = (CAM1_0[0] + STRIPE * TILE_PX, CAM1_0[1])
H1_0, H2_0 = 0, POSES // 2


def camera_states(move: bytes):
    """Every distinct ((h1,p1),(h2,p2)) the ROM renders, in frame order."""
    def step(pos, frac, vel):
        acc = (frac + vel) & 0xFFFF                 # the 8.8 accumulator
        hi = acc >> 8
        return ((pos + (hi - 256 if hi >= 128 else hi)) & (WORLD_PX - 1),
                acc & 0xFF)

    h1, h2 = H1_0, H2_0
    p1, p2, f1, f2 = list(CAM1_0), list(CAM2_0), [0, 0], [0, 0]
    out = [((h1, tuple(p1)), (h2, tuple(p2)))]
    for _t in range(POSES):
        h1 = (h1 + 1) & (POSES - 1)
        h2 = (h2 - 1) & (POSES - 1)
        for i in (0, 1):
            v1, v2 = (struct.unpack_from("<hh", move, h1 * 4)[i],
                      struct.unpack_from("<hh", move, h2 * 4)[i])
            p1[i], f1[i] = step(p1[i], f1[i], v1)
            p2[i], f2[i] = step(p2[i], f2[i], v2)
        out.append(((h1, tuple(p1)), (h2, tuple(p2))))
    if out[-1] != out[0]:
        raise SystemExit(f"gen_split_h_2p_assets: the camera cycle is not "
                         f"{POSES}-periodic ({out[0]} -> {out[-1]}); the "
                         f"marker coverage below would be a sample, not a "
                         f"proof")
    return out[:-1]


# --- the swarm ---------------------------------------------------------------
# WHY RINGS, AND WHY THESE RINGS. Each camera, when it is DRIVING, walks a
# circle: it advances 2 px/frame while its heading steps one pose/frame, so its
# path closes after POSES frames with circumference POSES * 2 px — radius ~81.5
# — and its forward direction is tangential to that circle. So for a point on a
# ring of radius R about the ORBIT CENTRE, at orbit-phase alpha ahead of the
# camera,
#
#     forward distance d = R sin(alpha)        lateral u = R cos(alpha) - 81.5
#
# independent of where the camera is on its orbit. A point on such a ring
# therefore sweeps the WHOLE depth range once per turn — every size tier, the
# near seam guard and the far one — and a ring of them enters and leaves the
# view continuously, which is what makes the visible count RISE AND FALL (the
# OAM watermark's shrink path) instead of only growing.
#
# The projector's cast was world-FIXED on those rings. The swarm's entities START
# there and then WALK, so the rings are the seed geometry and the WAYPOINT
# LOOPS are laid on the same two orbit centres for the same reason — a follower
# circling one camera's orbit centre keeps sweeping that camera's depth range
# instead of wandering off the plane.
#
# The radii are jittered by a seeded RNG so no two entities share a (d, u)
# curve: a perfectly regular ring is a symmetry, and a near-symmetric world
# makes the wrong-math controls hard to tell apart from the right ones.
SP_MARKERS_PER_RING = 10
SP_RING_R = 160                  # sweeps d 0..160: every tier, both seams
SP_RING_JITTER = 22
SP_NEAR_PER_RING = 2
SP_NEAR_R = 34                   # parked in band 1's k>95 dead zone much of
SP_NEAR_JITTER = 6               #   the turn — the CULLOFF control's target
SP_SEED = 20260805

# --- the entity table and the AI's world model -------------------------------
# SWM_MAX is the TABLE's capacity, not the cast: the live count lives in WRAM
# and ships at SWM_N. The capacity is larger on purpose — the cadence sweep
# pokes the count and walks 1..SWM_MAX to find where the +1/+1 loop-vs-NMI
# lockstep breaks, and a gate that cannot be made to fail is not a gate.
#
# EVERY RECORD IS SEEDED FROM ROM, all SWM_MAX of them, even though only SWM_N
# are ticked: power-on WRAM is random (rule 5) and the sweep pokes the count
# UPWARD, so a record the shipping build never reads is one the sweep does.
SWM_MAX = 64
SWM_N = 24                       # the shipped live count
SWM_ENT_BYTES = 8
SWM_PLAYERS = 2                  # entities 0/1 mirror the two cameras
SWM_LOOPS = 8
SWM_WAYPOINTS = 4
SWM_REACH = 24                   # Chebyshev radius that counts as "arrived"
SWM_WAY_R = (150, 118)           # the two loop radii, alternating per loop
SWM_LAPS = 4                     # camera cycles the coverage gate walks
SWM_ENTS_BYTES = SWM_MAX * SWM_ENT_BYTES
SWM_WAY_BYTES = SWM_LOOPS * SWM_WAYPOINTS * 4


def _ring(centre, radius, n, phase, jitter, rng):
    out = []
    for i in range(n):
        a = phase + 2.0 * math.pi * i / n
        r = radius + rng.uniform(-jitter, jitter)
        out.append((int(round(centre[0] + r * math.cos(a))) & (WORLD_PX - 1),
                    int(round(centre[1] + r * math.sin(a))) & (WORLD_PX - 1)))
    return out


def _orbit_centres(states):
    """The two cameras' orbit centres, from the walked cycle itself."""
    out = []
    for b in (0, 1):
        xs = [s[b][1][0] for s in states]
        ys = [s[b][1][1] for s in states]
        out.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    return out


def way_loops(centres):
    """SWM_LOOPS x SWM_WAYPOINTS targets — the AI's entire world model.

    Loop j circles orbit centre (j & 1) at one of two radii, its four targets a
    quarter-turn apart and the whole loop rotated by j so no two loops overlay.
    Laid on the ORBIT CENTRES rather than anywhere on the plane, because that is
    what keeps a follower inside a camera's depth window instead of wandering
    off it — see the ring argument above.
    """
    out = []
    for j in range(SWM_LOOPS):
        c = centres[j & 1]
        r = SWM_WAY_R[(j >> 1) & 1]
        for w in range(SWM_WAYPOINTS):
            a = (j * 2.0 * math.pi / SWM_LOOPS
                 + w * 2.0 * math.pi / SWM_WAYPOINTS)
            out.append((int(round(c[0] + r * math.cos(a))) & (WORLD_PX - 1),
                        int(round(c[1] + r * math.sin(a))) & (WORLD_PX - 1)))
    return out


def entity_seeds(centres, states):
    """SWM_MAX records: two players, then followers on the four rings."""
    rng = random.Random(SP_SEED)
    o1, o2 = centres
    pos = (_ring(o1, SP_RING_R, SP_MARKERS_PER_RING, 0.3, SP_RING_JITTER, rng)
           + _ring(o2, SP_RING_R, SP_MARKERS_PER_RING, 1.1, SP_RING_JITTER, rng)
           + _ring(o1, SP_NEAR_R, SP_NEAR_PER_RING, 0.7, SP_NEAR_JITTER, rng)
           + _ring(o2, SP_NEAR_R, SP_NEAR_PER_RING, 2.0, SP_NEAR_JITTER, rng))
    # ...and enough more to fill the table for the sweep, on two wider rings.
    need = SWM_MAX - SWM_PLAYERS - len(pos)
    pos += _ring(o1, SP_RING_R + 46, (need + 1) // 2, 0.05, SP_RING_JITTER, rng)
    pos += _ring(o2, SP_RING_R + 46, need // 2, 0.95, SP_RING_JITTER, rng)
    ents = [{"x": states[0][b][1][0], "y": states[0][b][1][1],
             "h": states[0][b][0], "wp": 0, "fx": 0, "fy": 0}
            for b in range(SWM_PLAYERS)]
    for i, (x, y) in enumerate(pos):
        # A deterministic spread of start headings, so the AI's TURN is visible
        # from frame 1 rather than after every follower has agreed on a course.
        ents.append({"x": x, "y": y, "h": (i * 37) & (POSES - 1), "wp": 0,
                     "fx": 0, "fy": 0})
    if len(ents) != SWM_MAX:
        raise SystemExit(f"gen_split_h_2p_assets: {len(ents)} entity seeds, "
                         f"must be {SWM_MAX}")
    return ents


def pack_ents(ents) -> bytes:
    return b"".join(struct.pack("<HHHH", e["x"] & (WORLD_PX - 1),
                                e["y"] & (WORLD_PX - 1),
                                ((e["wp"] & 3) << 8) | (e["h"] & 0xFF),
                                ((e["fy"] & 0xFF) << 8) | (e["fx"] & 0xFF))
                    for e in ents)


# --- the AI, mirrored bit-for-bit from sh2_swarm.asm -------------------------
# Not a test oracle (the tests read OAM and the framebuffer) — it exists so
# this generator can PROVE the world it emits exercises what the tests look
# for, and so the ASM has a written statement of the model to be checked
# against. Every operation below is the ASM's: 10-bit wrap residues, arithmetic
# >>3 magnitudes so the cross product's two terms fit an 8x8 hardware multiply,
# and the same 8.8 accumulators the camera drive uses at HALF speed.
def _s10(raw):
    return raw - WORLD_PX if raw >= WORLD_PX // 2 else raw


def _step88(pos, frac, vel):
    acc = (frac + vel) & 0xFFFF
    hi = acc >> 8
    return ((pos + (hi - 256 if hi >= 128 else hi)) & (WORLD_PX - 1), acc & 0xFF)


def ai_tick(ents, way, move, n):
    """One frame of the followers. Entities 0..SWM_PLAYERS-1 are not touched."""
    for i in range(SWM_PLAYERS, n):
        e = ents[i]
        loop = (i - SWM_PLAYERS) & (SWM_LOOPS - 1)
        tx, ty = way[loop * SWM_WAYPOINTS + e["wp"]]
        rdx = (tx - e["x"]) & (WORLD_PX - 1)
        rdy = (ty - e["y"]) & (WORLD_PX - 1)
        near = ((rdx < SWM_REACH or rdx > WORLD_PX - SWM_REACH)
                and (rdy < SWM_REACH or rdy > WORLD_PX - SWM_REACH))
        if near:
            e["wp"] = (e["wp"] + 1) & (SWM_WAYPOINTS - 1)
            e["hit"] = e.get("hit", 0) + 1
            continue                                   # the one-frame pause
        dx, dy = _s10(rdx) >> 3, _s10(rdy) >> 3
        vx, vy = struct.unpack_from("<hh", move, e["h"] * 4)
        fx, fy = vx >> 3, vy >> 3
        cross = fx * dy - fy * dx
        if cross < 0:
            e["h"] = (e["h"] + 1) & (POSES - 1)
        elif cross > 0:
            e["h"] = (e["h"] - 1) & (POSES - 1)
        elif fx * dx + fy * dy < 0:
            e["h"] = (e["h"] + 1) & (POSES - 1)        # the 180-degree tie
        vx, vy = struct.unpack_from("<hh", move, e["h"] * 4)
        e["x"], e["fx"] = _step88(e["x"], e["fx"], vx >> 1)
        e["y"], e["fy"] = _step88(e["y"], e["fy"], vy >> 1)


def _run(tabs, ents, way, move, cams, n):
    """Walk `cams` with the AI running; return the per-frame visible counts,
    the tiers reached, the seam dead-zone occupancy and the peak."""
    per_state, tiers, dead = [], set(), [0, 0]
    for (h1, p1), (h2, p2) in cams:
        for b, p in enumerate((p1, p2)):
            ents[b]["x"], ents[b]["y"] = p[0], p[1]
        counts = []
        for band, (p, h, top) in enumerate(((p1, h1, 0), (p2, h2, LINES))):
            vis = 0
            hit = 0
            for e in ents[:n]:
                q = sp_project(tabs, e["x"], e["y"], p[0], p[1], h, top)
                if q:
                    vis += 1
                    tiers.add(q[2])
                else:
                    q = sp_project(tabs, e["x"], e["y"], p[0], p[1], h, top,
                                   nocull=True)
                    if q and (q[3] > SP_SEAM_HI if top == 0
                              else q[3] < SP_SEAM_LO):
                        hit = 1
            counts.append(vis)
            dead[band] += hit
        per_state.append(tuple(counts))
        ai_tick(ents, way, move, n)
    return per_state, tiers, dead


def swarm_world(tabs, states, move, oam_slots, notes):
    """The entity seeds and the waypoint loops, plus the proof they cover 2c.

    NO REFERENCE ORACLE — the waypoint loops are authored against THIS rail's
    world, so there is nothing to compare them to and a byte check against
    someone else's scenario would be meaningless rather than reassuring. The
    gate here is a SIMULATION over the
    complete 256-state camera cycle with the AI running, and the properties
    asserted are exactly the ones the test module's claims stand on. A world
    that stopped exercising one of them would make a test vacuous silently,
    which is the failure this repo files as indirect evidence.
    """
    centres = _orbit_centres(states)
    way = way_loops(centres)
    seeds = entity_seeds(centres, states)

    # (a) THE AUTOCAM CYCLE — both cameras rotating and driving, which is the
    #     `-D SH2_AUTOCAM` build the motion tests read.
    # FOUR LAPS of the cycle, not one. The camera state is exactly POSES-
    # periodic but the AI is NOT — a follower moves 1 px/frame and its loop is
    # ~940 px around, so one lap is not long enough for every follower to reach
    # even its first waypoint. The coverage statistics below are therefore over
    # a run long enough for the wp advance to be exercised by all of them,
    # rather than over a window that happens to end before it fires.
    ents = [dict(e) for e in seeds]
    per_state, tiers, dead = _run(tabs, ents, way, move, states * SWM_LAPS,
                                  SWM_N)
    moved = sum(1 for a, b in zip(seeds[SWM_PLAYERS:SWM_N], ents[SWM_PLAYERS:])
                if (a["x"], a["y"]) != (b["x"], b["y"]))
    turned = sum(1 for a, b in zip(seeds[SWM_PLAYERS:SWM_N], ents[SWM_PLAYERS:])
                 if a["h"] != b["h"])
    hits = sum(1 for e in ents[SWM_PLAYERS:SWM_N] if e.get("hit"))

    # (b) THE STATIC CAMERAS — the SHIPPING build with no pad touched, where
    #     the only thing that moves is the AI. Every claim the test module
    #     makes about a driven cast has to survive here too, because this is
    #     what a run with the pads released renders.
    stat = [states[0]] * (len(states) * SWM_LAPS)
    sents = [dict(e) for e in seeds]
    s_state, s_tiers, s_dead = _run(tabs, sents, way, move, stat, SWM_N)

    n1 = [a for a, _b in per_state]
    n2 = [b for _a, b in per_state]
    tot = [a + b for a, b in per_state]
    s1 = [a for a, _b in s_state]
    s2 = [b for _a, b in s_state]
    peak = max(max(tot), max(a + b for a, b in s_state))
    checks = (
        (min(n1) >= 1 and min(n2) >= 1,
         f"a band empties on the driven cycle (band 1 min {min(n1)}, band 2 "
         f"min {min(n2)}) — the placement tests would be vacuous there"),
        (min(s1) >= 1 and min(s2) >= 1,
         f"a band empties with the cameras STATIC (band 1 min {min(s1)}, "
         f"band 2 min {min(s2)}) — that is what the shipping build renders "
         f"with no pad touched"),
        (max(n1) > min(n1) and max(n2) > min(n2),
         "the driven visible count never changes — the OAM watermark's SHRINK "
         "path would never be exercised"),
        (max(s1) > min(s1) and max(s2) > min(s2),
         "the STATIC visible count never changes — with the pads released the "
         "watermark's shrink path would never run"),
        (tiers == set(range(len(SP_TIERS))),
         f"the cast reaches tiers {sorted(tiers)}, not all {len(SP_TIERS)} — "
         f"the size ladder would be partly untested"),
        (dead[0] >= POSES // 8 and dead[1] >= POSES // 8,
         f"the seam dead zones are occupied in only {dead} of {POSES} states — "
         f"the CULLOFF control would rarely have anything to bleed"),
        (moved == SWM_N - SWM_PLAYERS,
         f"only {moved} of {SWM_N - SWM_PLAYERS} followers moved over the "
         f"run — a cast that stands still is not an AI"),
        (turned == SWM_N - SWM_PLAYERS,
         f"only {turned} of {SWM_N - SWM_PLAYERS} followers CHANGED HEADING "
         f"over the cycle — a cast that drifts one way ships the turn broken"),
        (hits == SWM_N - SWM_PLAYERS,
         f"only {hits} of {SWM_N - SWM_PLAYERS} followers reached a waypoint "
         f"within {POSES * SWM_LAPS} frames — the loops are "
         f"unreachable, so the wp "
         f"advance is dead code"),
        (peak <= oam_slots,
         f"peak {peak} concurrent sprites exceeds the {oam_slots}-slot OAM "
         f"claim, so markers would be DROPPED at the shipped count"),
    )
    for ok, why in checks:
        if not ok:
            raise SystemExit(f"gen_split_h_2p_assets: swarm coverage — {why}")

    notes.append(f"swarm: {SWM_MAX} seeded, {SWM_N} live; driven cycle band1 "
                 f"{min(n1)}..{max(n1)} band2 {min(n2)}..{max(n2)}, static "
                 f"band1 {min(s1)}..{max(s1)} band2 {min(s2)}..{max(s2)}; "
                 f"peak {peak} of {oam_slots} slots; tiers {sorted(tiers)}; "
                 f"seam dead zones {dead}/{POSES} driven {s_dead}/{POSES} "
                 f"static; all {moved} followers moved, {turned} turned, "
                 f"{hits} reached a waypoint")
    return pack_ents(seeds), b"".join(struct.pack("<HH", x, y) for x, y in way)


# --- the gate ----------------------------------------------------------------
def vendored(name: str) -> bytes | None:
    path = VENDOR / name
    return path.read_bytes() if path.is_file() else None


def missing_oracle(ref_name: str) -> SystemExit:
    """The refusal for an ABSENT reference.

    This used to print "NO ORACLE … UNVERIFIED" and emit the blobs anyway,
    exit 0. That is the `grad_tabs` shape (docs/37): a gate that passes when
    its evidence is missing, and it is worst precisely here, because this
    gate's entire purpose is closing the CI coverage hole that
    `test_split_v_fight.py`'s three oracle-gated skips leave — asset ground
    truth that never runs on a bare runner. A soft absence direction means
    deleting the oracle silently restores the hole it was vendored to close.

    The files are committed to this repo; absence is a broken checkout or a
    deletion, not a supported configuration. Fail closed.
    """
    return SystemExit(
        f"gen_split_h_2p_assets: NO ORACLE — {VENDOR / ref_name} is absent. "
        f"These blobs are the committed reference output, vendored so this rail's "
        f"asset ground truth runs on a bare CI runner; the generator will not "
        f"emit UNVERIFIED art in their place. Restore vendor/art/split_h_2p/ "
        f"(see its README) — do not delete the oracle to make a mismatch go "
        f"away.")


def check_oracle(name: str, got: bytes, ref_name: str, notes: list) -> None:
    """Refuse to emit anything that disagrees with the reference blob — or that
    has no reference blob to disagree with.

    This is a build gate, not a test convenience. The generator shares no code
    with the program that made the reference, so a mismatch means one of the
    two is wrong and neither has authority — stop and look, do not ship."""
    ref = vendored(ref_name)
    if ref is None:
        raise missing_oracle(ref_name)
    if got != ref:
        diff = sum(a != b for a, b in zip(got, ref))
        raise SystemExit(
            f"gen_split_h_2p_assets: {name} disagrees with "
            f"{ref_name} — {diff} of {max(len(got), len(ref))} bytes differ "
            f"(lengths {len(got)} vs {len(ref)}). This generator and the "
            f"oracle cannot both be right; do not re-vendor to make this go "
            f"away.")
    notes.append(f"{name}: byte-identical to {ref_name} ({len(ref)} B)")


def write(path: Path, blob: bytes, made: list) -> None:
    path.write_bytes(blob)
    made.append(f"{path.name} ({len(blob)} B)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", help="directory to write the .bin blobs into")
    # The OAM budget the swarm must fit inside, passed from the Makefile out of
    # sh2_obj's OWN claim rather than restated here — a peak the claim cannot
    # hold has to fail at emit time, and the claim is the only authority on how
    # many slots there are.
    ap.add_argument("--oam-slots", type=int, default=32,
                    help="sh2_obj's sho_cast OAM claim, in sprites")
    args = ap.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    made: list[str] = []
    notes: list[str] = []

    blob = world_blob()
    if len(blob) != 0x8000:
        raise SystemExit(f"gen_split_h_2p_assets: world blob is {len(blob)} B, "
                         f"must be exactly one 32 KB LoROM window")
    check_oracle("world blob", blob, "ref_checker_map.bin", notes)
    write(out / "sh2_map.bin", blob, made)

    ab, cd = pose_blobs(0.0)
    if len(ab) != POSE_BYTES or len(cd) != POSE_BYTES:
        raise SystemExit("gen_split_h_2p_assets: pose blob length is wrong")
    # Angle 0 is the pure ramp: B and C are zero everywhere, so a rotation that
    # leaked into the "fixed heading" set would show here before the oracle.
    if any(ab[i:i + 2] != b"\x00\x00" for i in range(2, POSE_BYTES, 4)):
        raise SystemExit("gen_split_h_2p_assets: angle-0 pose has B != 0")
    if any(cd[i:i + 2] != b"\x00\x00" for i in range(0, POSE_BYTES, 4)):
        raise SystemExit("gen_split_h_2p_assets: angle-0 pose has C != 0")
    check_oracle("pose AB", ab, "ref_poses1_ab.bin", notes)
    check_oracle("pose CD", cd, "ref_poses1_cd.bin", notes)
    write(out / "sh2_pose1_ab.bin", ab, made)
    write(out / "sh2_pose1_cd.bin", cd, made)

    # --- the 256-heading rotation set, and its four bank slices -------------
    # The WHOLE blob is what the oracle checks, because the ordering and the
    # 448-byte stride ARE the ROM's address arithmetic; the slices are then cut
    # from the matched bytes so the cut cannot introduce a drift the oracle
    # never saw.
    ab256, cd256 = pose_set(POSES)
    if len(ab256) != POSES * POSE_BYTES or len(cd256) != POSES * POSE_BYTES:
        raise SystemExit("gen_split_h_2p_assets: 256-pose blob length is wrong")
    # Heading 0 of the set IS the fixed-angle pose — the two derivations meet
    # here, so a ramp change that slipped past one would have to slip past both.
    if ab256[:POSE_BYTES] != ab or cd256[:POSE_BYTES] != cd:
        raise SystemExit("gen_split_h_2p_assets: heading 0 of the 256-set is "
                         "not the fixed-angle pose — the two sets disagree")
    check_oracle("pose256 AB", ab256, "ref_poses256_ab.bin", notes)
    check_oracle("pose256 CD", cd256, "ref_poses256_cd.bin", notes)
    for k in range(SLICES):
        write(out / f"sh2_pose256_ab_s{k}.bin", slice_of(ab256, k), made)
        write(out / f"sh2_pose256_cd_s{k}.bin", slice_of(cd256, k), made)

    # --- the forward-vector LUT ---------------------------------------------
    mv = move_lut(POSES)
    if len(mv) != POSES * 4:
        raise SystemExit("gen_split_h_2p_assets: move LUT length is wrong")
    # The rail's own drive invariant, asserted where it is created: heading 0
    # is straight up-screen, which is world -y with NO x component. A sign flip
    # or a sin/cos swap here would send both cameras sideways and every
    # framebuffer motion assertion downstream would be measuring the wrong axis.
    if struct.unpack("<hh", mv[0:4]) != (0, -int(MOVE_SCALE)):
        raise SystemExit(f"gen_split_h_2p_assets: move[0] is "
                         f"{struct.unpack('<hh', mv[0:4])}, must be "
                         f"(0, {-int(MOVE_SCALE)}) — heading 0 is world -y")
    check_oracle("move256", mv, "ref_move256.bin", notes)
    write(out / "sh2_move256.bin", mv, made)

    write(out / "sh2_pal.bin", palette(notes), made)

    # --- the projector's tables, gated the same way -------------------------
    # Every one of these is a function of the SAME scale_ramp() the floor
    # streams, so the oracle comparison proves the two sides agree — a ramp
    # change would move the floor and the inverse together or refuse both.
    ramp = scale_ramp()
    sincos = sincos_lut()
    check_oracle("sprite sincos", sincos, "ref_sp_sincos.bin", notes)
    write(out / "sh2_sp_sincos.bin", sincos, made)

    vk = vk_lut(ramp)
    # The window's ends, asserted where they are made: d = 0 is the pivot
    # itself (no row) and the far end is g(0) = the horizon.
    if vk[0] != 0xFF or vk[int(sp_g(ramp, 0)) + 1] != 0xFF:
        raise SystemExit("gen_split_h_2p_assets: sp_vk does not cull outside "
                         "[1, g(0)] — the projector would index a row for a "
                         "distance the floor never draws")
    check_oracle("sprite vk", vk, "ref_sp_vk.bin", notes)
    write(out / "sh2_sp_vk.bin", vk, made)

    rlo, rhi = recip_luts(ramp)
    check_oracle("sprite recip lo", rlo, "ref_sp_recip_lo.bin", notes)
    check_oracle("sprite recip hi", rhi, "ref_sp_recip_hi.bin", notes)
    write(out / "sh2_sp_recip_lo.bin", rlo, made)
    write(out / "sh2_sp_recip_hi.bin", rhi, made)

    tier = tier_ladder(ramp)
    check_oracle("sprite tier ladder", tier, "ref_sp_tier_nocull.bin", notes)
    write(out / "sh2_sp_tier.bin", tier, made)

    chr_blob = sprite_chr()
    check_oracle("sprite chr", chr_blob, "ref_sp_chr.bin", notes)
    write(out / "sh2_sp_chr.bin", chr_blob, made)

    # --- the swarm: no oracle, a SIMULATION instead -------------------------
    tabs = (sincos, vk, [rlo[k] | (rhi[k] << 8) for k in range(LINES)], tier)
    ents, way = swarm_world(tabs, camera_states(mv), mv, args.oam_slots, notes)
    if len(ents) != SWM_ENTS_BYTES or len(way) != SWM_WAY_BYTES:
        raise SystemExit(f"gen_split_h_2p_assets: swarm blob lengths are "
                         f"{len(ents)}/{len(way)}, must be {SWM_ENTS_BYTES}/"
                         f"{SWM_WAY_BYTES}")
    write(out / "sh2_ents.bin", ents, made)
    write(out / "sh2_way.bin", way, made)

    print("gen_split_h_2p_assets: " + ", ".join(made))
    for n in notes:
        print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
