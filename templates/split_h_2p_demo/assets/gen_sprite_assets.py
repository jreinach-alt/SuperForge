#!/usr/bin/env python3
"""gen_sprite_assets.py — sprite-stress assets for the 2-player rail (SPRITES=N).

Emits (all deterministic, seeded; provenance manifest references this script):

  sp_sincos.bin    256 x (cos s8.8 word, sin s8.8 word) unit-rotation LUT with
                   magnitudes CLAMPED to +-255 so both bytes fit the 8-bit
                   hardware-multiply operands ($4202/$4203) after sign split.
                   Convention-proven against the rail's move256.bin entry h =
                   round(-512*sin, -512*cos) (asserted entry-by-entry below,
                   +-3 slack for the clamp) — the LUT shares the pose tables'
                   angle convention BY CONSTRUCTION.
  sp_vk.bin        256-byte inverse LUT d -> band-local row k, where d = -v
                   (px in front of the pivot) and g(k) = (112-k)*S8.8(k)/256
                   is the world-forward distance the floor samples at row k
                   (monotonic). $FF = cull (behind pivot / beyond horizon).
                   The S(k) ramp is IMPORTED from tools/gen_pose_tables.py
                   (the same bytes the floor streams) — never re-derived.
  sp_recip_lo.bin  112 x low byte of recip(k) = round(65536 / S8.8(k))
  sp_recip_hi.bin  112 x high byte (0/1; recip is 9 bits, 171..410) —
                   sxoff = (|u|*recip_lo)>>8 (+|u| if hi) via ONE HW multiply.
  sp_tier_lut.bin  112-byte row->tier LUT WITH the symmetric seam margins
                   folded in ($FF for k<9 or k>95). The RUNTIME cull no longer
                   reads this (it moved to a PER-BAND check in sp_project_band —
                   each band guards only its seam-facing edge so the true-screen
                   edge slides off); this file now only marks the k in [9,95]
                   CORE-visible band for the asset generator's own d_lo/d_hi
                   world-depth window.
  sp_tier_nocull.bin  the FULL ladder (every k 0..111 maps to a tier) — the
                   runtime SIZE source for BOTH bands (read after the recip),
                   and the -DSP_CULLOFF seam-bleed control (cull disabled).
  sp_chr.bin       64 OBJ tiles (2 KB, 4bpp): five CHARACTER-TOKEN size
                   variants (was: solid discs) — three 16x16 (names 0/2/4,
                   heights 10/12/14 px) and two 32x32 (names 8/12, heights
                   18/22 px). Each token is a round head fused onto a tapered
                   torso (one contiguous colour-1 silhouette), centred in the
                   tile the same way the discs were, and its HEIGHT equals the
                   retired disc's diameter so the apparent-size ladder is
                   unchanged (only the pixels differ — far tokens smaller). The
                   32x32 variants own FULL 4x4 tile blocks (empty quadrant tiles
                   committed as explicit zeros — the phantom-quadrant lesson: a
                   32x32 OBJ fetches all 16 names, padded here so no neighbour
                   CHR leaks in). Colour index 1 only; OBJ palette 0 entry 1 =
                   white (AI followers), palette 1 entry 1 = magenta (player
                   markers) — both disjoint from the floor checker's green/red
                   space.
  sp_world_main.bin 128 x (wx u16, wy u16): entity 0/1 = the player start
                   positions (the ROM re-syncs them from POS1/POS2 every
                   frame); 2..127 = AI followers seeded ASYMMETRICALLY around
                   their waypoint loops (the near-symmetric trial world was
                   geometry-fragile for wrong-math controls — this one is
                   scattered by a seeded RNG, no symmetry).
  sp_way.bin       8 waypoint loops x 4 waypoints x (x u16, y u16) = 128 B.
                   Follower i runs loop (i-2)&7 starting at waypoint
                   ((i-2)>>3)&3. Legs are long vs the turning radius
                   (speed 1.0 px/f, +-1 heading step/f -> R ~= 41 px) so the
                   pursuit-orbit trap cannot bind; the EXACT integer AI model
                   is simulated below and every follower must advance >= 3
                   waypoints within the frame bound (build-time guarantee).
  sp_world_vis.bin 128 x (wx,wy) ALL visible (and tier-valid) in both bands at
                   the pinned instrument geometry (P1=P2=(512,512), h=64 via
                   SAME_ORIGIN+SP_PIN): every sprite takes the FULL projection
                   path — the worst-case cycle-instrument world.
  sp_world_far.bin 128 x (wx,wy) ALL Chebyshev-culled (|dy|>176 from both
                   cameras) — the pre-cull-cost instrument world.
  sp_world_tier.bin 128 x (wx,wy) for the tier/overflow stills (pinned
                   SAME_ORIGIN h=64): a distance LADDER spanning every tier's
                   k range (lanes offset in u to avoid overlap) + a CLUSTER
                   sharing ONE 32x32-tier row (the OBJ/sliver-overflow
                   forensics target) + far-parked padding.

Every placement assert runs through the same integer PROJECTION MIRROR the
tests use (mirrors the ASM bit-exactly). The mirror is never a test oracle —
tests read the rendered framebuffer; the mirror only picks sample points.
"""
import math
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[2]
sys.path.insert(0, str(KIT / "tools"))
from gen_pose_tables import scale_ramp  # noqa: E402  (the floor's own ramp)

LINES = 112
PIVOT = 112                     # y-term zero at band-local 112 (VOFS model)
RAMP = scale_ramp(LINES, 1.5, 0.625)          # s8.8 ints, index = band-local k
SEED = 20260703
WORLD_DIAM = 14                 # world-space disc diameter (px) for tiering

# tier ladder: (apparent-diameter upper bound px, chr name, half px, 32-class)
TIERS = [
    (12.5, 0, 8, False),        # tier 0: 16x16 disc r5.0   (k ~ [9,26])
    (15.0, 2, 8, False),        # tier 1: 16x16 disc r6.0   (k ~ [27,48])
    (17.5, 4, 8, False),        # tier 2: 16x16 disc r7.0   (k ~ [49,69])
    (19.5, 8, 16, True),        # tier 3: 32x32 disc r9.0   (k ~ [70,86])
    (1e9, 12, 16, True),        # tier 4: 32x32 disc r11.0  (k ~ [87,95])
]
MARGIN16 = (9, 103)             # measured seam-margin datum (trial, 16x16)
MARGIN32 = (17, 95)             # scaled for the 32x32 box
# The seam cull is now PER-BAND (in sp_project_band): each band guards only the
# edge that faces the k=111/112 seam, and lets its true-SCREEN edge slide off.
# Band 1's bottom is the seam -> cull band-local k > SEAM_HI; band 2's top is
# the seam -> cull band-local k < SEAM_LO. (Tiers are k-segregated, so these
# flat cutoffs ARE the per-tier margins: only 32x32 rows reach SEAM_HI, only
# 16x16 rows reach SEAM_LO.)
SEAM_LO = MARGIN16[0]           # 9  — band-2 top-seam cutoff (16x16 rows)
SEAM_HI = MARGIN32[1]           # 95 — band-1 bottom-seam cutoff (32x32 rows)


def g(k: int) -> float:
    """World-forward distance (px) sampled at band-local row k."""
    return (PIVOT - k) * RAMP[k] / 256.0


# --- sp_sincos.bin (clamped for the 8-bit multiply core) ---------------------
sincos = bytearray()
for h in range(256):
    a = 2.0 * math.pi * h / 256.0
    c = max(-255, min(255, round(256.0 * math.cos(a))))
    s = max(-255, min(255, round(256.0 * math.sin(a))))
    sincos += struct.pack("<hh", c, s)
move = (HERE / "move256.bin").read_bytes()
for h in range(256):
    mx, my = struct.unpack_from("<hh", move, h * 4)
    c, s = struct.unpack_from("<hh", sincos, h * 4)
    assert abs(mx - round(-2 * s)) <= 3, (h, mx, s)
    assert abs(my - round(-2 * c)) <= 3, (h, my, c)
(HERE / "sp_sincos.bin").write_bytes(sincos)

# --- sp_vk.bin (d -> k, nearest row over the FULL window — no interior
#     tolerance culls: those punch dead zones in the far field) ---------------
vk = bytearray(256)
for d in range(256):
    if d < 1 or d > 168:                 # outside [g(111)~0.6 .. g(0)=168]
        vk[d] = 0xFF
        continue
    vk[d] = min(range(LINES), key=lambda k: abs(g(k) - d))
assert vk[0] == 0xFF and vk[200] == 0xFF
assert vk[1] in (110, 111) and vk[168] == 0
(HERE / "sp_vk.bin").write_bytes(vk)

# --- sp_recip_lo/hi.bin -------------------------------------------------------
recip = [round(65536 / fx) for fx in RAMP]
assert all(171 <= r <= 410 for r in recip), (min(recip), max(recip))
(HERE / "sp_recip_lo.bin").write_bytes(bytes(r & 0xFF for r in recip))
(HERE / "sp_recip_hi.bin").write_bytes(bytes(r >> 8 for r in recip))

# --- tier LUTs ----------------------------------------------------------------
def raw_tier(k: int) -> int:
    d_px = WORLD_DIAM * 256.0 / RAMP[k]
    for t, (ub, _n, _h, _c) in enumerate(TIERS):
        if d_px < ub:
            return t
    return len(TIERS) - 1


tier_lut = bytearray(LINES)
tier_nocull = bytearray(LINES)
for k in range(LINES):
    t = raw_tier(k)
    tier_nocull[k] = t
    lo, hi = MARGIN32 if TIERS[t][3] else MARGIN16
    tier_lut[k] = t if lo <= k <= hi else 0xFF

# ladder sanity: monotonic non-decreasing, every tier occupies a contiguous
# non-empty visible range, no tier index skipped inside the visible window
ts = [tier_nocull[k] for k in range(LINES)]
assert ts == sorted(ts), "tier ladder not monotonic in k"
vis_ranges = {}
for k in range(LINES):
    if tier_lut[k] != 0xFF:
        vis_ranges.setdefault(tier_lut[k], []).append(k)
assert sorted(vis_ranges) == [0, 1, 2, 3, 4], f"missing tiers: {sorted(vis_ranges)}"
for t, ks in vis_ranges.items():
    assert ks == list(range(ks[0], ks[-1] + 1)), f"tier {t} range not contiguous"
BOUNDARIES = [min(ks) for t, ks in sorted(vis_ranges.items())]
(HERE / "sp_tier_lut.bin").write_bytes(tier_lut)
(HERE / "sp_tier_nocull.bin").write_bytes(tier_nocull)

# --- projection mirror (bit-exact vs the ASM core; tests keep their own copy
#     that reads these committed bins) -----------------------------------------
def project(wx, wy, px, py, h, band_top, forward=False, nocull=False):
    """Integer-exact mirror of sp_project_band. (sx, sy, tier) or None."""
    c, s = struct.unpack_from("<hh", sincos, (h & 255) * 4)
    if forward:
        s = -s
    dx = ((wx - px + 512) & 1023) - 512
    dy = ((wy - py + 512) & 1023) - 512
    adx, mdx = (-dx, True) if dx < 0 else (dx, False)
    ady, mdy = (-dy, True) if dy < 0 else (dy, False)
    if adx > 176 or ady > 176:
        return None                      # Chebyshev pre-cull
    ac, mc = (-c, True) if c < 0 else (c, False)
    asn, ms = (-s, True) if s < 0 else (s, False)
    # v = dx*s + dy*c  (per-term: (mag*mag + 128) >> 8, sign = xor of masks)
    t1 = (adx * asn + 128) >> 8
    t2 = (ady * ac + 128) >> 8
    v = (-t1 if mdx ^ ms else t1) + (-t2 if mdy ^ mc else t2)
    if v >= 0:
        return None
    d = -v
    if d > 255 or vk[d] == 0xFF:
        return None
    k = vk[d]
    tier = tier_nocull[k]                 # full ladder — valid at every row
    if not nocull:
        # per-band SEAM-margin cull (matches sp_project_band + the test mirror):
        # band 1 (band_top=0) guards its BOTTOM/seam edge; band 2 its TOP/seam
        # edge. The other (true-screen) edge slides off.
        if band_top == 0:
            if k > SEAM_HI:
                return None
        elif k < SEAM_LO:
            return None
    # u = dx*c - dy*s
    t1 = (adx * ac + 128) >> 8
    t2 = (ady * asn + 128) >> 8
    u = (-t1 if mdx ^ mc else t1) + (-t2 if mdy ^ (not ms) else t2)
    au = -u if u < 0 else u
    if au >= 256:
        return None
    r = recip[k]
    sxoff = ((au * (r & 0xFF)) >> 8) + (au if r >> 8 else 0)
    if sxoff >= 160:
        return None
    sx = 128 - sxoff if u < 0 else 128 + sxoff
    return sx, band_top + k, tier


# --- sp_chr.bin (64 tiles, full 4x4 blocks for the 32x32 variants) ------------
# The five size variants are CHARACTER TOKENS (was: plain discs) — a round head
# fused onto a shoulders-wide tapered torso, one vertically-contiguous colour-1
# silhouette per tile, CENTRED in the tile exactly as the discs were (cc =
# (size-1)/2) so the projection/OAM placement is unchanged. The APPARENT-SIZE
# ladder is preserved by keeping each token's HEIGHT equal to the retired disc's
# diameter (10/12/14/18/22 px), so "far characters render smaller" still holds;
# the token is narrower than tall, so the rendered WIDTH is a NEW measured datum
# (the test's tier-extent oracle is retuned to the measured per-tier W and H).
# Clean-room procedural art in the spirit of the CC0 top-down RPG character packs
# (analogStudios_ dungeonSprites_ / camelot_, CC0; examples/itch_cc0/LICENSES.md)
# — NO pack pixels are vendored or derived; this is a generated silhouette.
def draw_character(size, h):
    """A top-down character token of pixel-height h, centred in a size x size
    tile: a round head over a shoulders-wide tapered torso, fused into ONE
    vertically-contiguous silhouette (colour index 1 only). h is set to the
    tier's apparent diameter so the size ladder reads the same as the discs'."""
    img = [[0] * size for _ in range(size)]
    cc = (size - 1) / 2.0
    top = cc - h / 2.0
    bot = cc + h / 2.0
    r_head = 0.205 * h                       # head radius
    head_cy = top + r_head
    sh_top = head_cy + r_head * 0.55         # shoulders begin just under the head
    w_sh = 0.33 * h                          # shoulder half-width (widest row)
    w_ba = 0.20 * h                          # base half-width
    for y in range(size):
        for x in range(size):
            dxx = x - cc
            if dxx * dxx + (y - head_cy) ** 2 <= r_head * r_head:
                img[y][x] = 1                # head disc
                continue
            if sh_top <= y <= bot:           # tapered torso, rounded base
                t = (y - sh_top) / max(1e-6, (bot - sh_top))
                hw = w_sh + (w_ba - w_sh) * t
                if y > bot - hw:
                    dy = y - (bot - hw)
                    hw = math.sqrt(max(0.0, hw * hw - dy * dy))
                if abs(dxx) <= hw:
                    img[y][x] = 1
    return img


chr_bytes = bytearray(64 * 32)           # names 0..63, all-zero = explicit pad
def blit(img, name0):
    size = len(img)
    for ty in range(size // 8):
        for tx in range(size // 8):
            tile = name0 + ty * 16 + tx
            for row in range(8):
                p0 = 0
                for col in range(8):
                    p0 = (p0 << 1) | img[ty * 8 + row][tx * 8 + col]
                chr_bytes[tile * 32 + row * 2] = p0     # plane 0 only (colour 1)


# tier heights == the retired disc diameters (10/12/14/18/22) so the apparent-
# size ladder is byte-for-byte the same tier→size story (only the pixels differ).
blit(draw_character(16, 10.0), 0)
blit(draw_character(16, 12.0), 2)
blit(draw_character(16, 14.0), 4)
blit(draw_character(32, 18.0), 8)
blit(draw_character(32, 22.0), 12)
# phantom-quadrant pad assert: every name a 32x32 OBJ at 8/12 fetches exists
# inside the 64-name set (rows 0..3 of the name grid — no out-of-set fetch).
for base in (8, 12):
    for ty in range(4):
        for tx in range(4):
            assert base + ty * 16 + tx < 64
(HERE / "sp_chr.bin").write_bytes(chr_bytes)

# --- waypoint loops + main (asymmetric) world ---------------------------------
rng = random.Random(SEED)
loops = []
CENTRES = [(200, 190), (760, 150), (430, 460), (890, 520),
           (600, 610), (620, 750), (840, 400), (940, 900)]
for cx, cy in CENTRES:
    pts = []
    base = rng.uniform(0, 2 * math.pi)
    for j in range(4):
        a = base + j * (math.pi / 2) + rng.uniform(-0.35, 0.35)
        rad = rng.uniform(150, 215)
        pts.append((int(cx + rad * math.cos(a)) & 1023,
                    int(cy + rad * math.sin(a)) & 1023))
    loops.append(pts)
(HERE / "sp_way.bin").write_bytes(
    b"".join(struct.pack("<HH", x, y) for pts in loops for x, y in pts))

world = [(512, 512), (768, 512)]         # players (re-synced from POS1/2)
for i in range(2, 128):
    loop = loops[(i - 2) & 7]
    wp = ((i - 2) >> 3) & 3
    px, py = loop[(wp - 1) & 3]          # start near the PREVIOUS waypoint
    world.append(((px + rng.randint(-28, 28)) & 1023,
                  (py + rng.randint(-28, 28)) & 1023))
(HERE / "sp_world_main.bin").write_bytes(
    b"".join(struct.pack("<HH", x, y) for x, y in world))

# --- EXACT integer AI-model simulation (the build-time bounded-arrival proof;
#     the ASM implements this bit-for-bit) -------------------------------------
def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x >= 0x8000 else x


def ai_sim(n_followers=126, frames=2500, need_wp=3):
    ents = []
    for i in range(2, 2 + n_followers):
        x, y = world[i]
        ents.append(dict(x=x, y=y, h=0, wp=((i - 2) >> 3) & 3, fx=0, fy=0,
                         loop=(i - 2) & 7, hops=0))
    for _f in range(frames):
        for e in ents:
            tx, ty = loops[e["loop"]][e["wp"]]
            dx = ((tx - e["x"] + 512) & 1023) - 512
            dy = ((ty - e["y"] + 512) & 1023) - 512
            if max(abs(dx), abs(dy)) < 24:
                e["wp"] = (e["wp"] + 1) & 3
                e["hops"] += 1
                continue                  # 1-frame pause at each waypoint
            fx, fy = struct.unpack_from("<hh", move, e["h"] * 4)
            # steering sense: fwd(h) = (-sin, -cos) rotates NEGATIVE-cross-ward
            # as h increases, so cross(fwd, to_target) < 0 -> h += 1
            cross = (fx >> 3) * (dy >> 3) - (fy >> 3) * (dx >> 3)
            if cross < 0:
                e["h"] = (e["h"] + 1) & 255
            elif cross > 0:
                e["h"] = (e["h"] - 1) & 255
            else:
                dot = (fx >> 3) * (dx >> 3) + (fy >> 3) * (dy >> 3)
                if dot < 0:
                    e["h"] = (e["h"] + 1) & 255   # 180-degree tie-break
            vx, vy = struct.unpack_from("<hh", move, e["h"] * 4)
            for ax, vv in (("x", vx >> 1), ("y", vy >> 1)):   # HALF speed
                sacc = e["f" + ax] + vv
                e[ax] = (e[ax] + (sacc >> 8)) & 1023
                e["f" + ax] = sacc & 0xFF
        if all(e["hops"] >= need_wp for e in ents):
            return _f + 1
    bad = [i for i, e in enumerate(ents) if e["hops"] < need_wp]
    raise AssertionError(f"AI sim: followers {bad[:8]} did not reach "
                         f"{need_wp} waypoints in {frames} frames")


AI_BOUND = ai_sim()
print(f"AI sim: all 126 followers reached >=3 waypoints by frame {AI_BOUND}")

# --- instrument worlds ---------------------------------------------------------
# all-visible: pin P=(512,512) h=64 -> v ~= dx (need dx=-d), u ~= -dy.
# Keep every entry tier-valid: k in [9,95] <-> d in [ceil(g(95)), floor(g(9))].
d_lo = next(d for d in range(1, 200) if vk[d] != 0xFF and tier_lut[vk[d]] != 0xFF)
d_hi = max(d for d in range(1, 200) if vk[d] != 0xFF and tier_lut[vk[d]] != 0xFF)
vis = []
for i in range(128):
    d = d_lo + ((i * 7919) % (d_hi - d_lo + 1))
    uu = ((i * 37) % 100) - 50
    vis.append(((512 - d) & 1023, (512 - uu) & 1023))
for wx, wy in vis:
    p = project(wx, wy, 512, 512, 64, 0)
    assert p is not None, (wx, wy)
(HERE / "sp_world_vis.bin").write_bytes(
    b"".join(struct.pack("<HH", x, y) for x, y in vis))

# all-Chebyshev-culled from BOTH cameras: y band around 0 (|dy|>=300 from 512)
far = [((i * 61) & 1023, (i * 13) % 40) for i in range(128)]
for wx, wy in far:
    for px in (512, 768):
        dy = ((wy - 512 + 512) & 1023) - 512
        assert abs(dy) > 176, (wx, wy)
        assert project(wx, wy, px, 512, 64, 0) is None
(HERE / "sp_world_far.bin").write_bytes(
    b"".join(struct.pack("<HH", x, y) for x, y in far))

# tier ladder + overflow cluster (pin P=(512,512) h=64, SAME_ORIGIN)
tier_world = []
for i in range(24):                       # ladder: one entry per ~4 d-steps
    d = d_lo + round(i * (d_hi - d_lo) / 23.0)
    uu = (-1 if i & 1 else 1) * (30 + 25 * (i % 3))     # staggered lanes
    tier_world.append(((512 - d) & 1023, (512 - uu) & 1023))
    assert project(*tier_world[-1], 512, 512, 64, 0) is not None, (i, d)
# the ladder must SAMPLE every tier (frame the boundary rows)
lad_tiers = {project(x, y, 512, 512, 64, 0)[2] for x, y in tier_world}
assert lad_tiers == {0, 1, 2, 3, 4}, f"ladder misses tiers: {lad_tiers}"
# overflow cluster: 36 sprites sharing ONE 32x32-tier row (tier-3 midpoint)
t3_ks = vis_ranges[3]
k_row = t3_ks[len(t3_ks) // 2]
d_row = next(d for d in range(1, 200) if vk[d] == k_row)
CLUSTER_N = 36
for j in range(CLUSTER_N):
    uu = -140 + j * 8
    tier_world.append(((512 - d_row) & 1023, (512 - uu) & 1023))
    p = project(*tier_world[-1], 512, 512, 64, 0)
    if p is not None:                     # edge entries may x-cull; most live
        assert p[1] == k_row and p[2] == 3, (j, p)
n_row = sum(project(x, y, 512, 512, 64, 0) is not None
            for x, y in tier_world[24:])
assert n_row >= 30, f"overflow cluster too small on-screen: {n_row}"
# --- seam-margin probes (entries 60..65): sprites whose rows fall INSIDE the
# margin dead zones — the DEFAULT build must cull them (no white near the
# seam); -DSP_CULLOFF renders them and their boxes cross the band edges.
def find_probe(zone, uu, band_top):
    """A world point that DEFAULT-culls at the given band's SEAM but
    nocull-projects into the dead-zone BAND-LOCAL row range — scanned through
    the REAL projection mirror (the clamped-sin rounding shifts far-field d, so
    geometric d is not the row picker). The high-k dead zones live at band 1's
    bottom seam; the low-k zone at band 2's top seam (with SAME_ORIGIN the row
    k is identical in both bands, so the probe world point is band-invariant)."""
    for d in range(1, 200):
        wpt = ((512 - d) & 1023, (512 - uu) & 1023)
        if project(*wpt, 512, 512, 64, band_top) is not None:
            continue
        pn = project(*wpt, 512, 512, 64, band_top, nocull=True)
        if pn is not None and zone[0] <= pn[1] - band_top <= zone[1]:
            return wpt, pn
    return None, None


probes = []
probe_ks = []
for zone, uu, bt in (((105, 110), -24, 0), ((96, 104), 0, 0), ((1, 7), 24, 112)):
    wpt, pn = find_probe(zone, uu, bt)
    assert wpt is not None, f"no probe found for dead zone {zone}"
    probes.append((wpt, pn))
    probe_ks.append(pn[1] - bt)          # band-local dead-zone row
PROBE_START = len(tier_world)
for wpt, _pn in probes:
    tier_world.append(wpt)
while len(tier_world) < 128:              # far-parked padding (Chebyshev cull)
    tier_world.append((len(tier_world) * 5 & 1023, 8))
(HERE / "sp_world_tier.bin").write_bytes(
    b"".join(struct.pack("<HH", x, y) for x, y in tier_world))
print("seam probes: entries", PROBE_START, "..", PROBE_START + 2,
      "at band-local rows", probe_ks)

# --- glue-proof pin pairs on the MAIN world: report visibility + control
#     discriminability so the build defines are known-good ---------------------
def expected(world_pts, p1, h1, p2, h2, forward=False):
    out = {0: [], 1: []}
    for i, (wx, wy) in enumerate(world_pts):
        p = project(wx, wy, *p1, h1, 0, forward)
        if p:
            out[0].append((i, p[0], p[1]))
        p = project(wx, wy, *p2, h2, 112, forward)
        if p:
            out[1].append((i, p[0], p[1]))
    return out


def interior(band, sx, sy):
    lo, hi = (14, 98) if band == 0 else (126, 210)
    return 20 <= sx <= 235 and lo <= sy <= hi


# search each band's heading space for dense cones, then pair + verify the
# forward-control discriminability (deterministic: pure function of the world)
def band_score(h, p, top):
    exp = {}
    n = 0
    for i, (wx, wy) in enumerate(world):
        pt = project(wx, wy, *p, h, top)
        if pt and interior(1 if top else 0, pt[0], pt[1]):
            n += 1
    return n


cands1 = sorted(range(256), key=lambda h: -band_score(h, (512, 512), 0))[:48]
cands2 = sorted(range(256), key=lambda h: -band_score(h, (768, 512), 112))[:48]
PIN_PAIRS = []
for h1 in cands1:
    for h2 in cands2:
        if len(PIN_PAIRS) >= 3:
            break
        if any(abs(((h1 - a + 128) & 255) - 128) < 20 or
               abs(((h2 - b + 128) & 255) - 128) < 20 for a, b in PIN_PAIRS):
            continue          # DISTINCT headings per band across the three pins
        exp = expected(world, (512, 512), h1, (768, 512), h2)
        n1 = sum(interior(0, sx, sy) for _i, sx, sy in exp[0])
        n2 = sum(interior(1, sx, sy) for _i, sx, sy in exp[1])
        if n1 < 4 or n2 < 4:
            continue
        fwd = expected(world, (512, 512), h1, (768, 512), h2, forward=True)
        fwd_pts = [(sx, sy) for b in (0, 1) for _i, sx, sy in fwd[b]]
        disc = 0
        for b in (0, 1):
            for _i, sx, sy in exp[b]:
                if interior(b, sx, sy) and not any(
                        abs(fx - sx) < 18 and abs(fy - sy) < 18
                        for fx, fy in fwd_pts):
                    disc += 1
        if disc < 4:
            continue
        PIN_PAIRS.append((h1, h2))
        print(f"pin ({h1:3d},{h2:3d}): band1 {n1} interior, band2 {n2}, "
              f"forward-control discriminating {disc}")
assert len(PIN_PAIRS) >= 3, f"only {len(PIN_PAIRS)} viable pin pairs found"
print("PIN_PAIRS (hardcode as -DSP_H1/-DSP_H2 in the variant script):",
      PIN_PAIRS[:3])

print("tier boundaries (first k of tiers 0..4):", BOUNDARIES)
print("tier-3 overflow row: band-local k =", k_row, "d =", d_row,
      f"({n_row} cluster sprites on-screen)")
print("sp assets OK:", ", ".join(p.name for p in sorted(HERE.glob("sp_*"))))
