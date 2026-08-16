"""meteor_event — the Mode-1 <-> Mode-7 cutscene and its BG->OBJ capture.

Every case drives the lockstep Machine (a pure function of rom md5, power-on
seed and input script; every read from a parked exact frame) and asserts on
OUTPUT regions — screenshot pixels, OAM bytes, the readable matrix shadow —
never a proxy variable. WRAM state reads appear only to SEQUENCE the drive
(find the frame a beat begins); every claim a test's name makes is asserted on
a rendered surface or on the hardware table the feature writes.

The colour predicates are EXACT: gen_meteor_assets.py authors every palette,
Mesen expands BGR555 as (v << 3) | (v >> 2) per channel, and `_rt` reproduces
that round-trip — so "a captured-ground pixel" means the one authored green and
cannot count the meteor, the glow or the backdrop by accident (the population rule:
the counted population is the feature's).
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, "vendor")
from machine import Machine, MemoryType  # noqa: E402

sys.path.insert(0, "tools")
import gen_meteor_assets as GA  # noqa: E402  (the palette author — one source)
import gen_meteor_tracks as GT  # noqa: E402  (the track math — one source)

ROM = "build/meteor_event.sfc"
MAP = json.loads(Path("build/met/symbol_map.json").read_text())


def _sym(name, scene=None):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


ST = _sym("US_G_STATE")["start"]
TIMER = _sym("US_G_TIMER")["start"]
WORLDX = _sym("US_G_WORLDX")["start"]
GLOW = _sym("US_G_GLOW")["start"]
M7AFF = _sym("ES_M7AFF")["start"]
O_PLAYER = _sym("ES_O_PLAYER")["start"]
O_METEOR = _sym("ES_O_METEOR")["start"]
O_CAPTURE = _sym("ES_O_CAPTURE")["start"]
O_CAPTURE_N = _sym("ES_O_CAPTURE")["size"]
O_PAD = _sym("ES_O_HI_PAD")["start"]
O_PAD_N = _sym("ES_O_HI_PAD")["size"]
SLOT_END = O_PAD + O_PAD_N

# meteor.inc's state indices and pacing, mirrored. A drift here breaks
# SEQUENCING, not an assertion — the state reads only find the frame a beat
# starts on, and every claim is asserted on a rendered surface.
PLAY, FREEZE, CAPTURE, SCENE, RESTORE = 0, 1, 2, 3, 4
FREEZE_HOLD = 40
SPRITE_END = GT.SPRITE_END          # 72 — one source with the generator
SCN_END = GT.SCN_END                # 180
PARK_Y = 240
T_BLOCK, T_PLAYER = 64, 66
T_ROCK = (0, 4, 8)
T_FIERY = (68, 70, 72)
MET_PRIO, MET_HFLIP, MET_VFLIP = 3 << 4, 1 << 6, 1 << 7   # meteor.inc's

# --- the picture -------------------------------------------------------------
# Mesen hands back 256x239. The active 224 scanlines start at PNG row 7, so a
# BG1 line L running VOFS = -1 is PNG row L + 7 and an OBJ at OAM y Y starts on
# PNG row Y + 7 (the OBJ +1 scanline rule). test_brawler.py:135-144 states the
# same three constants for the same harness; the boot test below re-verifies
# both of the two this rail uses rather than trusting them.
BG1_ROW0 = 7
OBJ_ROW0 = 7
FRAME_W = 256


def _rt(rgb):
    """Author RGB -> the RGB Mesen renders (BGR555 truncate + expand)."""
    return tuple(((v >> 3) << 3) | (v >> 3 >> 2) for v in rgb)


GREEN = _rt(GA.GREEN)                       # the ground/platform, BG *and* OBJ
PLAYER_COLOURS = {_rt(GA.PLAYER_LT), _rt(GA.PLAYER_DK)}
NIGHT = _rt(GA.NIGHT)
EMBER_COLOURS = {_rt(GA.EMBER_RIM), _rt(GA.EMBER_MID), _rt(GA.EMBER_CORE)}
ROCK_COLOURS = {_rt(GA.ROCK_DK), _rt(GA.ROCK_MD), _rt(GA.ROCK_LT),
                _rt(GA.CRATER), _rt(GA.CHAR)}
METEOR_COLOURS = EMBER_COLOURS | ROCK_COLOURS

# the level's geometry, in PNG rows — derived from meteor.inc's tile rows
GND_Y0, GND_Y1 = 24 * 8 + BG1_ROW0, 28 * 8 + BG1_ROW0        # rows 199..230
PLAT_B_Y0, PLAT_B_Y1 = 14 * 8 + BG1_ROW0, 16 * 8 + BG1_ROW0  # rows 119..134
PLAT_A_Y0, PLAT_A_Y1 = 18 * 8 + BG1_ROW0, 20 * 8 + BG1_ROW0  # rows 151..166

# A strip of pure sky the glow washes and NOTHING else reaches: left of the
# meteor's whole slide path, below both platforms, above the ground band. The
# The population rule — the counted population must be the feature's, and every
# pixel here is backdrop until colour math adds to it.
SKY_X0, SKY_X1 = 0, 80
SKY_Y0, SKY_Y1 = 160 + BG1_ROW0, 190 + BG1_ROW0


# =============================================================================
# helpers
# =============================================================================
def _img(m, tmp_path, name):
    from PIL import Image
    p = tmp_path / name
    m.screenshot(str(p))
    return Image.open(p).convert("RGB")


def _flat(img):
    return list(img.getdata())


def _region(img, x0, y0, x1, y1):
    px = img.load()
    return [px[x, y] for y in range(y0, y1) for x in range(x0, x1)]


def _count(seq, colours):
    if isinstance(colours, tuple):
        return sum(1 for p in seq if p == colours)
    return sum(1 for p in seq if p in colours)


def _centroid(img, colours):
    px = img.load()
    sx = sy = n = 0
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            if px[x, y] in colours:
                sx += x
                sy += y
                n += 1
    return (sx / n, sy / n, n) if n else (None, None, 0)


def _u16(m, addr):
    b = m.read_bytes(MemoryType.SnesWorkRam, addr, 2)
    return b[0] | (b[1] << 8)


def _shadow_matrix(m):
    """(M7A, M7B, M7C, M7D) as signed words. M7A-D are WRITE-ONLY ports; this
    DP shadow is the one readable copy of what the plane renders with, and the
    NMI hook commits exactly these eight bytes."""
    b = m.read_bytes(MemoryType.SnesWorkRam, M7AFF, 8)
    return struct.unpack("<hhhh", b)


def _oam(m):
    return m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)


def _live(oam, lo, hi):
    return [s for s in range(lo, hi) if oam[s * 4 + 1] != PARK_Y]


def _walk_to_event(m, limit=400):
    """Hold RIGHT until the trigger fires. Returns the walk frame count."""
    for i in range(limit):
        m.advance(1, pad1={"right": True})
        if _u16(m, ST) != PLAY:
            return i
    raise AssertionError("the trigger never fired in %d walk frames" % limit)


def _park_at(m, state, timer, limit=600):
    for _ in range(limit):
        if _u16(m, ST) == state and _u16(m, TIMER) == timer:
            return
        m.advance(1)
    raise AssertionError("never reached state=%d timer=%d" % (state, timer))


def _reach(m, state, limit=600):
    for _ in range(limit):
        if _u16(m, ST) == state:
            return
        m.advance(1)
    raise AssertionError("never reached state=%d" % state)


# =============================================================================
# the Mode-1 slice
# =============================================================================
def test_boots_into_the_mode1_level_the_picture_shows_ground_platforms_player(
        tmp_path):
    """The rendered frame IS the assertion: a full-width green ground band on
    the rows met_bg painted, two platform blocks on theirs, and the player
    above the ground — all in the authored colours, at the authored rows.
    Also re-verifies the two PNG row offsets the rest of the module uses."""
    with Machine(ROM) as m:
        m.advance(40)
        img = _img(m, tmp_path, "boot.png")
    assert img.size == (FRAME_W, 239), img.size

    # the ground band: every pixel of rows 199..230 is the authored green
    ground = _region(img, 0, GND_Y0, FRAME_W, GND_Y1)
    assert _count(ground, GREEN) == len(ground) == FRAME_W * 32, \
        _count(ground, GREEN)
    # ...and the row above it is not (so the band's TOP edge is where met_bg
    # painted it, which is what pins BG1_ROW0)
    assert _count(_region(img, 0, GND_Y0 - 1, FRAME_W, GND_Y0), GREEN) == 0

    # the two platforms: 4 cells x 2 rows = 32 x 16 px of green each
    for y0, y1 in ((PLAT_B_Y0, PLAT_B_Y1), (PLAT_A_Y0, PLAT_A_Y1)):
        row = _region(img, 0, y0, FRAME_W, y1)
        assert _count(row, GREEN) == 32 * 16, (y0, _count(row, GREEN))

    # the player: present, above the ground band, at its fixed screen column
    cx, cy, n = _centroid(img, PLAYER_COLOURS)
    assert n > 100, n
    assert 96 <= cx <= 96 + 16, cx
    assert 176 + OBJ_ROW0 <= cy <= 176 + 16 + OBJ_ROW0, cy


def test_holding_right_scrolls_the_world_under_a_fixed_screen_player(tmp_path):
    """Both states of the one input axis this rail has, tied to the PICTURE:
    with RIGHT held the platforms move LEFT on screen while the player does
    not move at all; released, nothing moves. Driving the pad and reading the
    rendered result is what catches a reversed mapping that a "worldx went up,
    OAM x went up" chain cannot."""
    with Machine(ROM) as m:
        m.advance(40)
        a = _img(m, tmp_path, "w0.png")
        # 100 frames of walk. The camera is clamped at 0 until the player has
        # covered its own fixed screen x (96 px, 48 frames at 2 px/frame), so a
        # shorter hold measures the clamp rather than the scroll.
        m.advance(100, pad1={"right": True})
        m.advance(2)                        # the scroll's one-frame
        b = _img(m, tmp_path, "w1.png")     #   presentation lag, settled
        m.advance(60)                       # RELEASED — the idle arm
        c = _img(m, tmp_path, "w2.png")

    # the world moved LEFT under the pad (platform B's centroid decreases)
    def plat_x(img):
        px = img.load()
        xs = [x for y in range(PLAT_B_Y0, PLAT_B_Y1)
              for x in range(FRAME_W) if px[x, y] == GREEN]
        return sum(xs) / len(xs)

    assert plat_x(b) < plat_x(a) - 80, (plat_x(a), plat_x(b))
    # ...and stopped dead when the pad was released
    assert plat_x(c) == plat_x(b), (plat_x(b), plat_x(c))
    # the player never moved: it is the WORLD that scrolls (identical pixels)
    for img in (b, c):
        assert _centroid(img, PLAYER_COLOURS)[:2] == \
            _centroid(a, PLAYER_COLOURS)[:2]


def test_the_freeze_gates_input_the_rendered_frame_does_not_move(tmp_path):
    """The gate is the absence of a call, so the proof has to be that the
    PICTURE stops: RIGHT stays held across the whole freeze and consecutive
    frames are pixel-identical. A worldx read would prove nothing about what
    the player sees, and the reference ships a -DNO_FREEZE control precisely
    because that assertion is easy to make vacuous."""
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _park_at(m, FREEZE, 4)
        shots = []
        for k in range(4):
            # the pad stays DOWN for every one of these frames
            m.advance(1, pad1={"right": True})
            shots.append(_flat(_img(m, tmp_path, f"fz{k}.png")))
        # the screenshot itself costs one frame with the pad released; the
        # captures above bracket it, so any movement at all would show
        for k in range(1, 4):
            assert shots[k] == shots[0], \
                f"frame {k} of the freeze differs in " \
                f"{sum(1 for a, b in zip(shots[0], shots[k]) if a != b)} px"


# =============================================================================
# THE CAPTURE
# =============================================================================
def test_the_capture_hands_the_ground_from_bg_to_obj_pixel_exactly(tmp_path):
    """The rail's crux, as an equality on the whole frame.

    ST_CAPTURE emits an OBJ block at every visible platform cell and then, one
    frame later, drops BG1 from TM. If the blocks really land on the pixels the
    BG tiles occupied — same geometry AND same palette entry — the frame the
    background disappears is INDISTINGUISHABLE from the frame before it. So the
    assertion is zero differing pixels across the handover, over the whole
    61,184-pixel frame, not a spot check on a region.
    """
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _park_at(m, FREEZE, FREEZE_HOLD - 1)     # the last frame with the BG
        seq = [_flat(_img(m, tmp_path, f"cap{k}.png")) for k in range(5)]
    for k in range(1, 5):
        diff = sum(1 for a, b in zip(seq[0], seq[k]) if a != b)
        assert diff == 0, f"frame {k} of the handover differs in {diff} px"
    # non-vacuity: the reference frame really does hold the level's green
    assert _count(seq[0], GREEN) > 7000, _count(seq[0], GREEN)


def test_the_capture_fills_exactly_the_declared_oam_claim(tmp_path):
    """The capture's OAM cost is otherwise "bounded by nothing declared".
    Here it is met_obj's `capture` claim, and this asserts both halves on the
    hardware OAM table — that the emitted set is the expected 36 blocks (so the
    40-slot bound is not silently truncating a larger one), and that NOTHING
    outside the claim is live (so the scan cannot have walked into a table this
    rail does not own)."""
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _park_at(m, CAPTURE, 4)
        oam = _oam(m)

    blocks = _live(oam, O_CAPTURE, O_CAPTURE + O_CAPTURE_N)
    assert len(blocks) == 36, len(blocks)
    # the live blocks are a PREFIX of the claim, and every one carries the
    # capture tile — a stray write into the range would show as either
    assert blocks == list(range(O_CAPTURE, O_CAPTURE + 36)), blocks
    for s in blocks:
        assert oam[s * 4 + 2] == T_BLOCK, (s, oam[s * 4 + 2])
    # the tail of the claim, the pad slots, and the whole rest of the table
    for s in range(O_CAPTURE + 36, 128):
        assert oam[s * 4 + 1] == PARK_Y, (s, oam[s * 4 + 1])
    # the player kept slot 0 through the pass
    assert oam[O_PLAYER * 4 + 2] == T_PLAYER
    assert oam[O_PLAYER * 4 + 1] != PARK_Y
    # the meteor slot is not live yet — the other scene owns it
    assert oam[O_METEOR * 4 + 1] == PARK_Y


def test_the_captured_ground_survives_the_swap_into_mode7(tmp_path):
    """The capture exists to outlive the mode swap. The Mode-1 BG is gone, the
    Mode-7 plane is up — and the SAME green pixels are still on the SAME rows,
    now composited over the meteor scene. Asserted on the picture, and paired
    with a cross-layer check that the plane really is behind them."""
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _park_at(m, CAPTURE, 4)
        before = _img(m, tmp_path, "pre_swap.png")
        _reach(m, SCENE)
        # sampled INSIDE the Mode-7 phase and BEFORE the glow starts (m < 20):
        # the plane is up and its authored colours are still exactly authored,
        # which is what makes the "the scene really changed" half specific
        _park_at(m, SCENE, SPRITE_END + 10)
        after = _img(m, tmp_path, "post_swap.png")

    g_before = _region(before, 0, GND_Y0, FRAME_W, GND_Y1)
    g_after = _region(after, 0, GND_Y0, FRAME_W, GND_Y1)
    assert _count(g_before, GREEN) == FRAME_W * 32
    assert g_after == g_before, \
        "the captured ground did not survive the swap: %d px differ" % \
        sum(1 for a, b in zip(g_before, g_after) if a != b)
    # both platforms too, and the player
    for y0, y1 in ((PLAT_B_Y0, PLAT_B_Y1), (PLAT_A_Y0, PLAT_A_Y1)):
        assert _count(_region(after, 0, y0, FRAME_W, y1), GREEN) == 32 * 16
    assert _centroid(after, PLAYER_COLOURS)[2] > 100
    # ...and the scene really did change: the Mode 7 plane's own colours are on
    # screen, which they never are in the Mode-1 level
    assert _count(_flat(after), METEOR_COLOURS) > 200, \
        _count(_flat(after), METEOR_COLOURS)
    assert _count(_flat(before), METEOR_COLOURS) == 0


# =============================================================================
# THE SCALE-RAMP TRACK
# =============================================================================
def test_the_matrix_track_matches_the_generator_at_every_frame(tmp_path):
    """The WHOLE declared matrix state against the generator's arithmetic, at
    every frame of both phases — the identity halves (D == A, C == -B) included,
    because those are what a dropped negate turns into a shear that still looks
    like "a rotating meteor" at some headings.

    M7A-M7D are write-only ports; ES_M7AFF is the one readable copy, and it is
    exactly the eight bytes the NMI hook commits, so this reads what the plane
    renders with. The cursor is checked too: the sprite phase must hold entry 0
    and the Mode-7 phase must walk 0..107 in lockstep with the scene clock."""
    grow = GT.build_grow()
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _reach(m, SCENE)
        checked = 0
        while _u16(m, ST) == SCENE:
            t = _u16(m, TIMER)
            # the tick APPLIES for its own timer then increments, so the pose
            # standing at a park with timer t is the entry for t - 1
            prev = max(t - 1, 0)
            idx = 0 if prev < SPRITE_END else prev - SPRITE_END
            a, b, c, d = _shadow_matrix(m)
            assert (a, b) == grow[idx], (t, idx, (a, b), grow[idx])
            assert d == a, (t, d, a)                     # uniform scale
            assert c == -b, (t, c, b)                    # the post-shift negate
            checked += 1
            m.advance(1)
    assert checked >= SCN_END, checked


def test_the_track_blob_in_rom_carries_the_declared_entries(tmp_path):
    """The blob-format pin: the bytes at met_grow's allocated ROM address are
    the track m7t_apply clamps against. Half of this is independent of the
    generator — the count header and the crossover pose are recomputed against the
    the declared constants — so a regenerated-but-wrong blob is still caught."""
    rom = Path(ROM).read_bytes()
    p = _sym("ES_R_MET_GROW")
    blob = rom[p["start"]:p["start"] + p["size"]]
    n = struct.unpack("<H", blob[:2])[0]
    assert n == GT.M7_LEN + 1 == 109, n
    assert p["size"] == 2 + n * 4 == 438, (p["size"], n)
    # entry 0 IS the crossover pose, rebuilt from the declared constants
    # (angle 0, scale $0E00) rather than from the generator's blob writer
    a0, b0 = struct.unpack("<hh", blob[2:6])
    assert (a0, b0) == (GT.MET_SCALE_CROSS, 0), (a0, b0)
    # and the whole blob is what the generator emits
    assert blob == GT.blob(GT.build_grow())


def test_the_sprite_phase_speck_sweeps_in_and_grows_then_hands_over(tmp_path):
    """(A) and (B) of the locked design, on OAM and on the picture: the meteor
    sprite walks the frame ladder small-to-large, its screen position sweeps
    down and right, the ember pixels on screen grow with it, and at the
    crossover the sprite is PARKED — with its size bit cleared, which is not
    cosmetic (a 32x32 parked at y 240 wraps its bottom half onto screen rows
    0..15).

    AND THE FLIP CYCLE, which is the sprite phase's whole rotation: OBJ cannot
    rotate, so the reference reorients the meteor through {normal, H, V, H+V} every
    MET_FLIP_PERIOD frames "so the off-centre craters reorient frame-to-frame"
    (main.asm:160-164) and ships -DNO_TUMBLE as the control that compiles it
    out. The OAM ATTRIBUTE byte is where that lands, so it is what this asserts:
    priority 3 with the two flip bits walking 0x30 -> 0x70 -> 0xb0 -> 0xf0. The
    four sample frames sit one per 7-frame bucket and away from the boundaries,
    so the one-frame OAM presentation lag cannot move any of them into a
    neighbouring bucket."""
    seen = []
    flips = []
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _reach(m, SCENE)
        for t in (4, 11, 18, 25):
            _park_at(m, SCENE, t)
            flips.append(_oam(m)[O_METEOR * 4 + 3])
        for t in (30, 40, 66):
            _park_at(m, SCENE, t)
            oam = _oam(m)
            img = _img(m, tmp_path, f"spr{t}.png")
            hi = oam[512 + O_METEOR // 4]
            size = (hi >> ((O_METEOR & 3) * 2 + 1)) & 1
            seen.append((oam[O_METEOR * 4 + 2], oam[O_METEOR * 4 + 0],
                         oam[O_METEOR * 4 + 1], size,
                         _count(_flat(img), EMBER_COLOURS)))
        _park_at(m, SCENE, SPRITE_END + 8)
        oam = _oam(m)
        img = _img(m, tmp_path, "cross.png")

    tiles = [s[0] for s in seen]
    assert tiles[0] in T_FIERY and tiles[-1] in T_ROCK, tiles
    assert seen[0][3] == 0 and seen[-1][3] == 1, [s[3] for s in seen]  # size
    xs, ys = [s[1] for s in seen], [s[2] for s in seen]
    assert xs[0] < xs[1] < xs[2], xs          # sweeping right...
    assert ys[0] < ys[1] < ys[2], ys          # ...and down
    embers = [s[4] for s in seen]
    assert embers[0] < embers[1] < embers[2], embers   # and growing on SCREEN

    # the flip cycle: priority 3 held, both flip bits walking their four steps
    assert flips == [MET_PRIO, MET_PRIO | MET_HFLIP,
                     MET_PRIO | MET_VFLIP,
                     MET_PRIO | MET_HFLIP | MET_VFLIP], [hex(f) for f in flips]

    # the crossover: parked, and parked SAFELY (size bit cleared)
    assert oam[O_METEOR * 4 + 1] == PARK_Y
    hi = oam[512 + O_METEOR // 4]
    assert (hi >> ((O_METEOR & 3) * 2 + 1)) & 1 == 0, hex(hi)
    # nothing of the sprite is left on the top rows the wrap would have used
    assert _count(_region(img, 0, 0, FRAME_W, 16 + OBJ_ROW0),
                  METEOR_COLOURS) == 0


def test_the_mode7_meteor_grows_in_place_and_slides_off_the_bottom_right(
        tmp_path):
    """(C): the plane's meteor gets BIGGER on screen while its centre moves
    down and right. Both halves are read off the picture — the meteor's own
    authored colours, counted and located — because "the scale word fell" is
    the mechanism, not the effect.

    Sampled in the PRE-GLOW window (m < MET_GLOW_START = 20), which is the
    window the reference tuned its ramp rate for and says so: "a brisk ramp so the
    meteor visibly grows in the pre-glow window ... A faster ramp also gives the
    GROW test a clean real-vs-NO_SCALE separation before the glow rises and
    pollutes the meteor-texel count" (main.asm:173-177). Once colour math is on,
    the plane's pixels are no longer the authored colours and an exact-colour
    population would collapse — measured, 1220 -> 138."""
    samples = []
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _reach(m, SCENE)
        for t in (SPRITE_END + 2, SPRITE_END + 10, SPRITE_END + 18):
            _park_at(m, SCENE, t)
            img = _img(m, tmp_path, f"m7_{t}.png")
            cx, cy, n = _centroid(img, METEOR_COLOURS)
            samples.append((t, cx, cy, n))

    ns = [s[3] for s in samples]
    assert ns[0] < ns[1] < ns[2], ns                    # it GROWS
    assert samples[0][1] < samples[1][1] < samples[2][1], \
        [s[1] for s in samples]                         # ...moving right
    assert samples[0][2] < samples[1][2] < samples[2][2], \
        [s[2] for s in samples]                         # ...and down


def test_the_glow_rises_and_recedes_over_the_sky_band(tmp_path):
    """The colour-math half, on the picture, in a strip of pure sky the meteor
    never crosses (the population rule): red appears where there was none, peaks, and
    is gone again before the cutscene ends — on the reference's own schedule, and
    in RED rather than whatever plane the payload happens to select.

    THE NAME DELIBERATELY DOES NOT SAY "without staining the sprites", and the
    ground/player assertions below are NOT the OBJ-exclusion guard.
    Mesen2 `Core/SNES/SnesPpu.cpp:962` gates an OBJ pixel's colour math on
    `(_state.ColorMathEnabled & 0x10) && _spritePalette[x] > 3` — colour math
    reaches OBJ only from palettes 4..7, and this rail's whole cast is OBJ
    palette 0 — so CGADSUB bit 4 is unreachable on this composition and NO
    assertion can distinguish its two values. Measured through the harness: a
    plant setting it moved the artifact md5 and changed no pixel. What the two
    population checks below really are is a COMPOSITION guard: they hold the
    captured ground and the player to their exact authored colours through the
    peak, which would catch the glow reaching them by any route — including the
    day someone moves the cast to an OBJ palette above 3 and the bit starts to
    matter."""
    marks = {}
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _reach(m, SCENE)
        for label, t in (("before", SPRITE_END + 10), ("peak", SPRITE_END + 48),
                         ("after", SCN_END - 3)):
            _park_at(m, SCENE, t)
            img = _img(m, tmp_path, f"glow_{label}.png")
            sky = _region(img, SKY_X0, SKY_Y0, SKY_X1, SKY_Y1)
            marks[label] = (
                sum(1 for p in sky if p[0] > 40 and p[0] > p[1] + 24
                    and p[0] > p[2] + 24),
                _count(_region(img, 0, GND_Y0, FRAME_W, GND_Y1), GREEN),
                _centroid(img, PLAYER_COLOURS)[2],
            )
    n_sky = len(range(SKY_Y0, SKY_Y1)) * (SKY_X1 - SKY_X0)
    assert marks["before"][0] == 0, marks["before"]
    assert marks["peak"][0] == n_sky, (marks["peak"], n_sky)
    assert marks["after"][0] == 0, marks["after"]
    # the COMPOSITION guard (not the OBJ-exclusion guard — see the docstring):
    # the exact authored green survives the peak, whole, and so does the
    # player's pixel count
    for label in ("before", "peak", "after"):
        assert marks[label][1] == FRAME_W * 32, (label, marks[label])
        assert marks[label][2] == marks["before"][2], (label, marks[label])


def test_the_swap_back_restores_the_level_and_releases_control(tmp_path):
    """The cycle closes: the Mode-1 level is back on screen with the captured
    OBJ ground DROPPED (so the green is BG again, not sprites), the pad moves
    the player once more, and the one-shot guard holds — walking on past the
    trigger does not fire the event a second time."""
    with Machine(ROM) as m:
        m.advance(30)
        _walk_to_event(m)
        _reach(m, SCENE)
        _reach(m, RESTORE)
        _reach(m, PLAY)
        # Settle after the swap. The return edge declares `style = "cut"`
        #, so this is no longer waiting out a 15-frame fade-in —
        # the picture is back one frame after the blank. Kept at 40 because
        # nothing moves without input, so the frame photographed is the same
        # one either way, and shortening it would only make the constant
        # look load-bearing when it is not.
        m.advance(40)
        back = _img(m, tmp_path, "restored.png")
        oam_back = _oam(m)
        x0 = _centroid(back, PLAYER_COLOURS)[0]
        # A SHORT walk, and read platform A. The BG1 tilemap is 32 columns and
        # WRAPS every 256 px, so a long walk from the trigger camera (144) puts
        # a platform back on screen further RIGHT than it started — a real
        # property of the level, not of the scroll. Twenty frames is 40 px, well
        # inside one wrap for this platform.
        m.advance(20, pad1={"right": True})
        m.advance(2)                             # the scroll's presentation lag
        moved = _img(m, tmp_path, "walked.png")
        m.advance(40)                            # RELEASED — the idle arm
        idle = _img(m, tmp_path, "idle.png")
        st_after = _u16(m, ST)
        oam_after = _oam(m)

    # the level renders again, ground band whole
    assert _count(_region(back, 0, GND_Y0, FRAME_W, GND_Y1), GREEN) == \
        FRAME_W * 32
    # ...and the captured blocks are GONE from OAM — the green on screen is the
    # BG's again, which is the difference between "restored" and "still frozen"
    assert _live(oam_back, O_CAPTURE, O_CAPTURE + O_CAPTURE_N) == []
    assert oam_back[O_METEOR * 4 + 1] == PARK_Y
    # control is released: the world scrolls under the pad again, and stops
    # again when it is let go
    def plat_a_x(img):
        px = img.load()
        xs = [x for y in range(PLAT_A_Y0, PLAT_A_Y1)
              for x in range(FRAME_W) if px[x, y] == GREEN]
        return sum(xs) / len(xs) if xs else None
    assert plat_a_x(moved) < plat_a_x(back) - 30, \
        (plat_a_x(back), plat_a_x(moved))
    assert plat_a_x(idle) == plat_a_x(moved), (plat_a_x(moved), plat_a_x(idle))
    assert _centroid(moved, PLAYER_COLOURS)[0] == x0     # still pinned
    # the one-shot guard: still in PLAY, still no captured sprites
    assert st_after == PLAY, st_after
    assert _live(oam_after, O_CAPTURE, O_CAPTURE + O_CAPTURE_N) == []
