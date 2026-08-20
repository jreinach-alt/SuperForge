"""boss_saucer — the SCALING boss and the first `m7_track` consumer.

Every case drives the lockstep Machine (pure function of rom md5, power-on
seed, input script; every read from a parked exact frame) and asserts on
OUTPUT regions — screenshot pixels, OAM bytes, CGRAM words, S-DSP registers,
SPC RAM, and the readable matrix shadow (M7A-D are write-only PORTS; the DP
shadow is the one readable copy of what the floor renders with). WRAM state
reads appear only to SEQUENCE a drive (find the frame a state begins); every
claim a test's name makes is asserted on a rendered surface.

The colour predicates are EXACT: the generator authors every palette, Mesen
expands BGR555 as (v << 3) | (v >> 2) per channel, and `_rt` reproduces that
round-trip. `test_the_colour_predicates_are_disjoint` proves the four
populations cannot count each other, which is what makes the pixel counts
attributable to the feature under test (the population rule).
"""
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "vendor")
from machine import Machine, MemoryType  # noqa: E402

sys.path.insert(0, "tools")
import gen_saucer_assets as GA  # noqa: E402  (the palette author — one source)
import gen_saucer_tracks as GT  # noqa: E402  (the track math — one source)

ROM = "build/boss_saucer.sfc"
MAP = json.loads(Path("build/sau/symbol_map.json").read_text())


def _sym(name, scene="arena"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


ST = _sym("US_B_STATE")["start"]
TIMER = _sym("US_B_TIMER")["start"]
HEADING = _sym("US_B_HEADING")["start"]
BHP = _sym("US_B_HP")["start"]
PHP = _sym("US_P_HP")["start"]
PX = _sym("US_P_X")["start"]
PIF = _sym("US_P_IFRAME")["start"]
RESULT = _sym("US_B_RESULT")["start"]
LG_STATE = _sym("US_LUNGE_STATE")["start"]
LG_TIMER = _sym("US_LUNGE_TIMER")["start"]
BM_STATE = _sym("US_BEAM_STATE")["start"]
BEAM_X = _sym("US_BEAM_X")["start"]
M7AFF = _sym("ES_M7AFF", scene=None)["start"]
FADE = _sym("ES_FADE_CTL", scene=None)["start"]     # +0 level 0..15, +1 dir
TAD_STATE = _sym("ES_TAD_BSS", scene=None)["start"] + 2   # TadPrivate_state

# the saucer.inc indices (constants, mirrored — a drift breaks SEQUENCING, not
# an assertion, and the state reads themselves are sequencing only)
REVEAL, HOLD, FIGHT, DEATH, LOSE, RES_ST, RESET = 1, 2, 3, 4, 5, 6, 7
LG_FAR, LG_APPR, LG_NEAR, LG_RETR = 0, 1, 2, 3
BM_OFF, BM_TELE, BM_FIRE = 0, 1, 2

T_SHOT, T_PIP_LIT, T_PIP_DIM, T_BEAM = 5, 6, 7, 8
T_CARDBG = 11
T_BEAM_TELE, T_BEAM_FLARE = 12, 13
T_STAR_FAR, T_STAR_NEAR = GA.T_STAR_FAR, GA.T_STAR_NEAR
PARK_Y = 240
O_BEAM, O_HUD, O_SHOTS, O_EXH, O_CARDS, O_PAD = 1, 17, 25, 29, 30, 54
# The star band is read from the EMITTED MAP, not mirrored: the slot numbers
# above are sequencing constants that a drift would only mis-sequence, but a
# star test that read the wrong slots would report on the card band and pass.
O_STARS = _sym("ES_O_STARS")["start"]
STAR_N = _sym("ES_O_STARS")["size"]
STAR_FAR_N = STAR_N // 2                       # saucer.inc: the first half
STAR_PAL = _sym("ES_C_STAR_PAL")["start"]      # CGRAM word 144, OBJ palette 1
# the OAM attr the draw writes: palette 1, priority 0 — the one OBJ priority
# Mode 7 puts BELOW BG1 (Mesen2 SnesPpu::RenderMode7 maps 0..3 to 2/4/6/7
# against BG1's 3), which is what makes the saucer occlude a star
STAR_ATTR = (1 << 1) | (0 << 4)
# saucer.inc's beam vocabulary: the walk starts on the emitter (the Mode 7
# pivot, shown at the screen centre) and steps SEGS times toward the latched
# column, delta * MUL/256 per step.
BEAM_SEGS, BEAM_X0, BEAM_Y0, BEAM_PITCH, BEAM_MUL = 16, 124, 108, 5, 17
SPAWN_X = 120                                  # SAU_PLAYER_X0

# The disc's own geometry, straight out of the generator's predicate
# (`tile_color`: `r > 22.0` is sky), so the rendered diameter below is an
# ORACLE over the envelope rather than a remembered number: a Mode 7 scale
# maps screen->texel, so the disc covers DISC_MAP_PX * 256 / scale screen px.
DISC_MAP_PX = 2 * 22.0 * 8


def _disc_px(scale):
    return DISC_MAP_PX * 256 / scale

# tad-audio.s at the pin: TadState::PLAYING; the SPC-side songTickCounter is
# the driver's third zeropage byte (tests/test_slice_b_audio.py's derivation).
TAD_PLAYING = 0x82
SONG_TICK = 0x0003
# the song header's room-A echo vs the room_b_ambience SFX this rail fires when
# the beam ignites (assets/audio/sound-effects.txt)
ECHO_REST = (12, 12, 24)                       # evol_l, evol_r, efb
ECHO_BEAM = (70, 70, 96)


def _rt(rgb):
    """Author RGB -> the RGB Mesen renders (BGR555 truncate + expand)."""
    return tuple(((v >> 3) << 3) | (v >> 3 >> 2) for v in rgb)


FACE_COLOURS = {_rt(c) for c in (
    GA.HULL_EDGE, GA.HULL_DK, GA.HULL_MD, GA.HULL_LT, GA.RIM_LT,
    GA.LAMP_ON, GA.LAMP_DIM, GA.DOME_DK, GA.DOME_MD, GA.DOME_LT,
    GA.EMIT_DK, GA.EMIT_LT)}
SKY_COLOURS = {_rt(GA.SKY_DARK)}
# The star field's own tones, and it has its own OBJ PALETTE so that this set
# can be exact: a pixel of one of these three colours is a star sprite and
# cannot be anything else on this rail. That is what makes a star pixel COUNT
# mean something — see `test_the_colour_predicates_are_disjoint`.
STAR_COLOURS = {_rt(GA.STAR_COLOURS[i]) for i in (1, 2, 3)}
# The ventral emitter disc at the pivot — a SCALE PROBE. Whole-face pixel
# counts saturate on the lunge (measured: the apex renders 56,437 face pixels
# of 57,344 and 20 frames into the climb it is still 56,708, so the total
# cannot order two poses once the saucer covers the screen). The emitter is
# 3.4 tiles of radius at the centre of the plane, so it is always fully on
# screen, its area is monotone in 1/scale over the whole ramp, and at the apex
# it is still two orders of magnitude short of the screen.
EMITTER_COLOURS = {_rt(GA.EMIT_DK), _rt(GA.EMIT_LT)}
# hull tones only: the gunship's tail pixels and its thruster flame are the
# exhaust tones, deliberately excluded so a "the ship moved" centroid measures
# the HULL and cannot be dragged by a flame that pulses on its own clock
SHIP_COLOURS = {_rt(GA.SPRITE_COLOURS[i]) for i in (1, 2, 3, 4)}
FLASH_COLOUR = _rt(GA.SPRITE_COLOURS[12])
BEAM_COLOURS = {_rt(GA.SPRITE_COLOURS[5]), _rt(GA.SPRITE_COLOURS[6])}
BOLT_COLOUR = _rt(GA.SPRITE_COLOURS[7])
GLYPH_COLOUR = _rt(GA.SPRITE_COLOURS[15])


def _pixels(m, path):
    from PIL import Image
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _count(img, colours):
    return sum(1 for px in img.getdata() if px in colours)


def _centroid(img, colours):
    sx = sy = n = 0
    w = img.width
    for i, px in enumerate(img.getdata()):
        if px in colours:
            sx += i % w
            sy += i // w
            n += 1
    return (sx / n, sy / n, n) if n else (None, None, 0)


def _span(img, colours):
    """Widest horizontal extent of `colours` anywhere in the frame."""
    w = img.width
    xs = [i % w for i, px in enumerate(img.getdata()) if px in colours]
    return (max(xs) - min(xs) + 1) if xs else 0


def _bbox(img, colours):
    w = img.width
    pts = [(i % w, i // w) for i, px in enumerate(img.getdata())
           if px in colours]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# The star faces' AUTHORED lit-pixel counts, read off the generator's own art
# rather than written out: 9 for the near twinkle, 5 for the far cross. They
# are the whole non-scaling assertion — a star that grew with the matrix would
# render more than its cell holds.
STAR_LIT_FAR = sum(r.count("3") for r in GA.STAR_FAR)
STAR_LIT_NEAR = sum(r.count("1") + r.count("2") for r in GA.STAR_NEAR)


def _star_boxes(oam):
    """(index, x, y) of every star slot, straight off the OAM shadow."""
    return [(i, _entry(oam, O_STARS + i)[0], _entry(oam, O_STARS + i)[1])
            for i in range(STAR_N)]


def _sprite_extents(oam, skip):
    """(x0, x1, rows) of every OAM sprite that renders in the picture, minus
    one slot. Sizes come from the hi table's SIZE bit, x from its X9 bit — the
    same two fields the PPU reads."""
    out = []
    for s in range(128):
        if s == skip:
            continue
        x, y = oam[s * 4], oam[s * 4 + 1]
        hi = (oam[512 + (s >> 2)] >> ((s & 3) * 2)) & 3
        size = 16 if (hi & 2) else 8
        xx = x | ((hi & 1) << 8)
        if xx >= 256:
            xx -= 512
        rows = {r for r in ((y + i) & 0xFF for i in range(size)) if r < 224}
        if rows:
            out.append((xx, xx + size - 1, rows))
    return out


def _sprite_pixels(oam):
    """Every picture pixel some OAM cell covers, from the same three fields
    the PPU reads (x + X9, y with its 256-row wrap, the SIZE bit)."""
    out = set()
    for (x0, x1, rows) in _sprite_extents(oam, None):
        for r in rows:
            for c in range(x0, x1 + 1):
                if 0 <= c < 256:
                    out.add((c, r))
    return out


def _clean_star_boxes(oam):
    """The star slots whose own 8x8 cell nothing else can be inside: wholly
    within the picture, and touched by no other sprite's box. What is left is
    a cell whose lit pixels can ONLY be that star's own tile, which is what
    makes an exact pixel count mean 'this star rendered at its authored size'.
    Occlusion by the plane is filtered separately, on the pixels."""
    out = []
    for (i, x, y) in _star_boxes(oam):
        if y + 7 >= 224 or x + 7 > 255:
            continue
        rows = {(y + r) & 0xFF for r in range(8)}
        if any(not rows.isdisjoint(r2) and not (x + 7 < x0 or x > x1)
               for (x0, x1, r2) in _sprite_extents(oam, O_STARS + i)):
            continue
        out.append((i, x, y))
    return out


def _picture(img):
    """The 224 PICTURE rows as flat per-row lists of RGB tuples. Decoded once
    per frame — the whole-frame predicates below are set arithmetic over this,
    not per-pixel calls into PIL."""
    from frame_geometry import png_row
    data = list(img.getdata())
    w = img.width
    return [data[png_row(r) * w:png_row(r) * w + w] for r in range(224)]


def _box_count(pic, x, y, colours):
    return sum(1 for r in range(8) for c in range(8)
               if 0 <= x + c < 256 and (y + r) & 0xFF < 224
               and pic[(y + r) & 0xFF][x + c] in colours)


def _colour_pixels(pic, colours):
    """{(col, picture row)} of every pixel in `colours`."""
    return {(c, r) for r, row in enumerate(pic)
            for c, p in enumerate(row) if p in colours}


def _disc_rows(pic):
    """Per picture row, the inclusive column span of the RENDERED disc. The
    plane's only non-backdrop tones are the twelve face colours and the disc
    is convex, so min..max face column on a row IS the disc on that row — the
    sprites drawn over it sit inside that span and cannot widen it."""
    out = {}
    for r, row in enumerate(pic):
        cols = [c for c, p in enumerate(row) if p in FACE_COLOURS]
        if cols:
            out[r] = (min(cols), max(cols))
    return out


def _rd16(m, off):
    b = m.read_bytes(MemoryType.SnesWorkRam, off, 2)
    return b[0] | (b[1] << 8)


def _scale(m):
    """The live matrix scale, from the readable shadow: M7A/M7B are
    (cos, sin) * scale >> 8, so their magnitude IS the scale."""
    a, b, _, _ = _shadow(m)
    return round((a * a + b * b) ** 0.5)


def _shadow(m):
    b = bytes(m.read_bytes(MemoryType.SnesWorkRam, M7AFF, 8))
    return struct.unpack_from("<hhhh", b, 0)


def _echo(m):
    d = m.read_bytes(MemoryType.SpcDspRegisters, 0, 128)
    return (d[0x2C], d[0x3C], d[0x0D])


def _song_tick(m):
    b = m.read_bytes(MemoryType.SpcRam, SONG_TICK, 2)
    return b[0] | (b[1] << 8)


def _oam(m):
    return m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)


def _entry(oam, slot):
    """(x_low, y, tile, attr) of one OAM slot."""
    o = slot * 4
    return oam[o], oam[o + 1], oam[o + 2], oam[o + 3]


def _run_until(m, off, want, max_frames, pad=None, step=2):
    """Advance in small steps until WRAM word `off` is (in) `want`. Sequencing
    only — never an assertion surface."""
    wants = want if isinstance(want, tuple) else (want,)
    for _ in range(max_frames // step):
        m.advance(step, pad1=pad or {})
        if _rd16(m, off) in wants:
            return
    raise AssertionError(f"{off:#x} never reached {want} in {max_frames} "
                         f"frames (at {_rd16(m, off)})")


class _Kill:
    """The drive that WINS the fight: hold A under the saucer, dodge each
    latched column once, come back to the lane.

    Holding A on the spawn lane is no longer enough on its own, and that is a
    consequence of the re-pitched envelope rather than a tuning accident: the
    saucer's hitbox is its RENDERED disc now (a 224 px box would delete bolts
    in open star field), so a bolt only connects from under the saucer, while
    a beam that lands still costs a heart. Measured standing still on this
    binary: the gunship dies with the saucer on 35 hp.

    THE DODGE DIRECTION IS LATCHED ON THE BEAM'S RISING EDGE. A per-frame
    "move away from the column" rule oscillates about it at 3 px/frame and
    never leaves — measured, the ship jittered 120..123 through three whole
    beams and lost.
    """

    def __init__(self):
        self.dodge = None
        self.prev = 0

    def pad(self, m):
        bm, px, bx = _rd16(m, BM_STATE), _rd16(m, PX), _rd16(m, BEAM_X)
        if bm and not self.prev:
            self.dodge = "right" if bx < 128 else "left"
        self.prev = bm
        if bm:
            if abs(px + 4 - bx) < 28:
                return {"a": True, self.dodge: True}
            return {"a": True}
        self.dodge = None
        if px < SPAWN_X - 2:
            return {"a": True, "right": True}
        if px > SPAWN_X + 2:
            return {"a": True, "left": True}
        return {"a": True}


def _kill_until(m, off, want, max_frames=4000):
    """Advance under the winning drive until WRAM word `off` reads `want`.
    Sequencing only."""
    k = _Kill()
    for _ in range(max_frames):
        m.advance(1, pad1=k.pad(m))
        if _rd16(m, off) == want:
            return k
    raise AssertionError(f"{off:#x} never reached {want} under the kill drive "
                         f"(at {_rd16(m, off)})")


@pytest.fixture(scope="module", autouse=True)
def _built():
    assert Path(ROM).exists(), "run `make boss_saucer` first"


# =============================================================================
# The predicates themselves — what makes every pixel count attributable
# =============================================================================
def test_the_colour_predicates_are_disjoint():
    """The population rule's precondition: no rendered tone belongs to two of the
    populations these tests count, so 'face pixels' cannot silently be sky,
    hull, beam or glyph pixels."""
    groups = {"face": FACE_COLOURS, "sky": SKY_COLOURS, "ship": SHIP_COLOURS,
              "beam": BEAM_COLOURS, "bolt": {BOLT_COLOUR},
              "glyph": {GLYPH_COLOUR}, "flash": {FLASH_COLOUR},
              "star": STAR_COLOURS}
    names = sorted(groups)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not (groups[a] & groups[b]), (a, b, groups[a] & groups[b])


# =============================================================================
# The reveal — the inherited the scale ramp beat
# =============================================================================
def test_the_reveal_grows_the_saucer_on_screen(tmp_path):
    """Screenshot pixels at three parked frames INSIDE the ramp: the saucer's
    rendered area STRICTLY grows, and the far pose is a fraction of the last.
    All three land in REVEAL at full brightness, so the chain measures the
    RAMP alone — not the fade-in and not HOLD, where the ring renders full
    size whatever the reveal did. Measured on the healthy build (per-frame
    ES_FADE_CTL + state/timer trace): the fade-in reads level 15 / dir idle
    from the T=19 park on, and the last in-REVEAL park is T=63 (timer 1).
    Each screenshot costs one emulated frame (machine.py), so the advances
    below park at T=22, 42, 63; the two guards are sequencing, the pixels are
    the assertion.

    THE SPAN IS AN ORACLE, not a remembered number. The disc's map radius is
    the generator's own predicate (22.0 tiles) and a Mode 7 scale maps
    screen->texel, so at the live shadow's scale the rendered diameter must be
    DISC_MAP_PX * 256 / scale. That ties the picture to the schedule at both
    ends: move the envelope OR the art and it fires."""
    with Machine(ROM) as m:
        m.advance(22)                         # 3 parks past fade-done
        fade = tuple(m.read_bytes(MemoryType.SnesWorkRam, FADE, 2))
        assert fade == (15, 0), \
            f"early park not at full brightness (fade level/dir {fade})"
        img = _pixels(m, tmp_path / "e.png")
        early, e_span, e_scale = (_count(img, FACE_COLOURS),
                                  _span(img, FACE_COLOURS), _scale(m))
        m.advance(19)                         # mid ramp
        mid = _count(_pixels(m, tmp_path / "m.png"), FACE_COLOURS)
        m.advance(20)                         # the LAST park still in REVEAL
        st, timer = _rd16(m, ST), _rd16(m, TIMER)
        assert (st, timer) == (REVEAL, 1), \
            f"rest park drifted out of the ramp (state {st}, timer {timer})"
        img = _pixels(m, tmp_path / "r.png")
        rest, r_span, r_scale = (_count(img, FACE_COLOURS),
                                 _span(img, FACE_COLOURS), _scale(m))
    assert 0 < early < mid < rest, (early, mid, rest)
    assert early * 1.4 < rest, f"far pose {early} not far vs rest {rest}"
    for span, scale, tag in ((e_span, e_scale, "far"), (r_span, r_scale, "rest")):
        assert abs(span - _disc_px(scale)) <= 3, \
            f"the {tag} pose renders {span} px of disc, not the "\
            f"{_disc_px(scale):.1f} px its scale {scale} calls for"


def test_the_reveal_matrix_matches_the_baked_track_every_frame():
    """Whole-state oracle: across the whole ramp the readable shadow equals
    the generator's math for that frame's entry, uniform-scale identity
    included (D == A, C == -B)."""
    reveal = GT.build_reveal()
    with Machine(ROM) as m:
        m.advance(4)
        mismatches = []
        st = None
        for _ in range(70):
            m.advance(1)
            st, timer = _rd16(m, ST), _rd16(m, TIMER)
            if st != REVEAL:
                break
            # the tick applies idx = FRAMES+1-t then decrements t, so at a
            # park idx = FRAMES - timer
            idx = GT.REVEAL_FRAMES - timer
            a, b, c, d = _shadow(m)
            want = reveal[idx]
            if (a, b) != want or d != a or c != -b:
                mismatches.append((idx, (a, b, c, d), want))
        assert st == HOLD, "the ramp never completed"
        assert not mismatches, mismatches[:4]


def test_the_hold_spins_the_ring_at_rest_scale(tmp_path):
    """HOLD is the one state on this rail that rotates. Two claims, both
    needed: the shadow equals ring[heading] at every parked HOLD frame (so
    the ring blob really is what renders), and across the hold the picture
    MOVES while the saucer's rendered area stays put — rotation, not scale.
    Either half alone passes on a bug: 'same area' passes on a frozen frame,
    'pixels moved' passes on a scale drift."""
    ring = GT.build_ring()
    with Machine(ROM) as m:
        _run_until(m, ST, HOLD, 200)
        m.advance(1)
        img1 = _pixels(m, tmp_path / "h0.png")
        checked = 0
        for _ in range(12):
            m.advance(2)
            if _rd16(m, ST) != HOLD:
                break
            h = _rd16(m, HEADING) & 0xFF
            a, b, c, d = _shadow(m)
            assert (a, b) == ring[h], (h, (a, b), ring[h])
            assert d == a and c == -b
            checked += 1
        img2 = _pixels(m, tmp_path / "h1.png")
    assert checked >= 8, f"HOLD ended before the ring was sampled ({checked})"
    n1, n2 = _count(img1, FACE_COLOURS), _count(img2, FACE_COLOURS)
    span = _span(img1, FACE_COLOURS)
    assert abs(span - _disc_px(GT.INIT_SCALE)) <= 3, \
        f"HOLD renders {span} px of disc, not the rest scale's "\
        f"{_disc_px(GT.INIT_SCALE):.1f}"
    assert abs(n1 - n2) < n1 * 0.10, (n1, n2)
    moved = sum(1 for p, q in zip(img1.getdata(), img2.getdata()) if p != q)
    assert moved > 2000, f"only {moved} pixels changed across the hold spin"


# =============================================================================
# The LUNGE — this rail's headline, on both the pixels and the matrix
# =============================================================================
def test_the_lunge_grows_then_shrinks_the_saucer(tmp_path):
    """The whole dive cycle on rendered pixels, BOTH directions and the rest:
    FAR (rest) -> APPROACH (the saucer grows) -> NEAR (the apex) -> RETREAT
    (it shrinks back) -> FAR (rest again). A test that photographed only the
    approach would lock the dive and ship the climb broken.

    MEASURED ON THE WHOLE FACE, and the debut's reason for using the emitter
    instead is now GONE: the emitter probe existed because the face count
    saturated once the saucer covered the screen (the apex rendered 56,437
    face pixels of 57,344 and could not order two poses). The re-pitched
    envelope's largest pose is a 141 px disc — 15k of 57k — so the face is
    both unsaturated and the far bigger, steadier probe. It is also the
    probe the emitter can no longer be: the beam now fires FROM the emitter,
    so a flare cell sits on top of it for every frame of the apex.

    THE RATIO IS TWO-SIDED AND DERIVED. Area goes as 1/scale^2, so the
    apex/far ratio must land near (INIT/NEAR)^2 = 2.0. A one-sided ">" would
    pass on a dive that overshot to the debut's screen-filling apex, which is
    the defect this rail was re-pitched to remove.

    The final `home` check is what makes this a CYCLE rather than two ramps —
    the pose the dive left from is the pose the climb returns to."""
    def face(m, name):
        img = _pixels(m, tmp_path / name)
        n = _count(img, FACE_COLOURS)
        assert n < 25000, f"the face probe saturated at {n} px"
        return n, _span(img, FACE_COLOURS)

    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, LG_STATE, LG_FAR, 200)
        m.advance(1)
        far, far_span = face(m, "far.png")
        _run_until(m, LG_STATE, LG_APPR, 200)
        m.advance(10)
        mid_in, _ = face(m, "in.png")
        _run_until(m, LG_STATE, LG_NEAR, 200)
        m.advance(2)
        apex, apex_span = face(m, "apex.png")
        _run_until(m, LG_STATE, LG_RETR, 300)
        m.advance(20)
        mid_out, _ = face(m, "out.png")
        # ...and the climb's LAST frame, which is the only sample that can
        # tell a climb from a second dive. Measured: bind the DIVE blob to the
        # climb (`make falsify`'s lunge-climb-binds-the-dive) and the ordering
        # above STILL holds — a dive replayed is monotone too, and `home` is
        # taken after the FAR transition, which re-applies the rest pose
        # either way. Only the end of the climb separates them.
        for _ in range(60):
            if _rd16(m, LG_STATE) != LG_RETR or _rd16(m, LG_TIMER) <= 2:
                break
            m.advance(1)
        climb_end, _ = face(m, "climb_end.png")
        _run_until(m, LG_STATE, LG_FAR, 300)
        m.advance(2)
        home, _ = face(m, "home.png")
    assert far < mid_in < apex, ("the dive did not grow", far, mid_in, apex)
    assert apex > mid_out > far, ("the climb did not shrink", apex, mid_out, far)
    want = (GT.INIT_SCALE / GT.NEAR_SCALE) ** 2
    assert want * 0.85 < apex / far < want * 1.15, \
        f"the dive grew the face {apex / far:.2f}x, not the {want:.2f}x its " \
        f"own scale schedule ({GT.INIT_SCALE} -> {GT.NEAR_SCALE}) calls for"
    for span, scale, tag in ((far_span, GT.INIT_SCALE, "rest"),
                             (apex_span, GT.NEAR_SCALE, "apex")):
        assert abs(span - _disc_px(scale)) <= 3, \
            f"the {tag} pose renders {span} px of disc, not the " \
            f"{_disc_px(scale):.1f} px scale {scale} calls for"
    assert abs(climb_end - far) < far * 0.15, \
        f"the climb did not END at the rest pose ({far} vs {climb_end})"
    assert abs(home - far) < far * 0.06, \
        f"the cycle did not return to the rest pose ({far} -> {home})"


def test_the_saucer_stays_inside_the_screen_and_never_magnifies(tmp_path):
    """THE RE-PITCHED ENVELOPE, asserted on the rendered picture across a whole
    fight. The debut's lunge apex ran the matrix to scale 160 — a 563 px disc
    on a 256 px screen, magnifying every texel 1.6x, which is what made the
    apex read as a pixelated square instead of a saucer. Three bounds, each
    one a thing a viewer can see, sampled every other frame through a complete
    FAR -> APPROACH -> NEAR -> RETREAT cycle:

      * NEVER MAGNIFIED. scale >= 256 means at most one screen pixel per
        texel. Read off the matrix shadow, which is what the floor renders
        with.
      * NEVER WIDER THAN 144 px. The gunship's hull top is row 184 and the
        saucer is centred on row 112, so a disc past 144 px swallows it and
        the beam has nothing to cross.
      * STILL A ZOOM. The widest sample must be at least 1.3x the narrowest —
        compressing the range is the point, deleting it is not.

    And the two ends must match the two scales the generator schedules, to
    within 3 px, so this cannot pass on an envelope that merely stayed inside
    the bounds by accident."""
    spans, scales = [], []
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, LG_STATE, LG_FAR, 200)
        for i in range(70):
            m.advance(2)
            if _rd16(m, ST) != FIGHT:
                break
            img = _pixels(m, tmp_path / f"c{i}.png")
            spans.append(_span(img, FACE_COLOURS))
            scales.append(_scale(m))
    assert len(spans) > 40, f"only {len(spans)} frames sampled"
    assert min(scales) >= 256, \
        f"the matrix magnified the plane (scale {min(scales)} < 256): that is " \
        f"the texel mush the debut's apex rendered"
    assert max(spans) <= 144, \
        f"the saucer reached {max(spans)} px of disc — past the gunship's row"
    assert max(spans) >= min(spans) * 1.3, \
        f"the lunge stopped reading as a zoom ({min(spans)} -> {max(spans)})"
    assert abs(min(scales) - GT.NEAR_SCALE) <= 1 and \
        abs(max(scales) - GT.INIT_SCALE) <= 1, \
        f"the fight's scale range {min(scales)}..{max(scales)} is not the " \
        f"schedule's {GT.NEAR_SCALE}..{GT.INIT_SCALE}"
    for span, scale in ((max(spans), GT.NEAR_SCALE), (min(spans), GT.INIT_SCALE)):
        assert abs(span - _disc_px(scale)) <= 3, (span, scale, _disc_px(scale))


def test_the_lunge_matrix_matches_the_baked_ramps_every_frame():
    """Whole-state oracle over a WHOLE lunge cycle: at every parked frame the
    shadow equals the entry the state's own cursor selects out of the blob
    the state binds — appr[0] while FAR, appr[idx] on the dive, appr's LAST
    entry while NEAR (the apex is held, not re-ramped), retr[idx] on the
    climb — with D == A and C == -B throughout. The fight's angle is 0 by
    construction, so every one of these is a pure scale entry."""
    appr, retr = GT.build_appr(), GT.build_retr()
    N = GT.LUNGE_FRAMES
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, LG_STATE, LG_FAR, 200)
        seen = {LG_FAR: 0, LG_APPR: 0, LG_NEAR: 0, LG_RETR: 0}
        bad = []
        for _ in range(260):
            m.advance(1)
            if _rd16(m, ST) != FIGHT:
                break
            lg, lt = _rd16(m, LG_STATE), _rd16(m, LG_TIMER)
            a, b, c, d = _shadow(m)
            if lg == LG_FAR:
                want = appr[0]
            elif lg == LG_APPR:
                want = appr[N - lt]          # the cursor's complement, parked
            elif lg == LG_NEAR:
                want = appr[N]
            else:
                want = retr[N - lt]
            seen[lg] += 1
            if (a, b) != want or d != a or c != -b:
                bad.append((lg, lt, (a, b, c, d), want))
        assert not bad, bad[:4]
    assert all(v > 0 for v in seen.values()), \
        f"the sweep did not cover every lunge sub-state: {seen}"
    assert seen[LG_APPR] > 30 and seen[LG_RETR] > 30, seen


# =============================================================================
# The STAR FIELD — sparse, on OBJ, and moving with the fight
# =============================================================================
# The field used to be PLANE TEXTURE: a hash scatter baked into the Mode 7
# world tile grid. That put it on the one layer this rail RAMPS, so the sky
# zoomed with the saucer through all four scale ramps. These four cases assert
# what moving it to OBJ bought, on the rendered surfaces: it is sparse, it is
# under the plane, its rendered size is INVARIANT across a lunge, and it moves
# at a rate the ROM's own state picks.
def test_the_star_field_is_sparse_and_sits_under_the_plane(tmp_path):
    """Two properties one frame can carry, and both are about the picture.

    SPARSE, by a stated measure: 24 sprites, and the whole field lights fewer
    than 200 of the picture's 57,344 pixels — under 0.35%. The field it
    replaced painted ~420 star TILES into the visible window at rest scale
    (the generator's old two-density predicate over the ~9,600 sky tiles the
    Mode 7 window sampled), which is why 'much sparser' is a count and not an
    adjective. The floor is there so a field that failed to draw at all cannot
    read as 'sparse'.

    UNDER THE PLANE: no star pixel falls inside the disc's rendered span, on
    any of the sampled frames. That is the OAM-priority-0 choice made visible
    — priority 0 is the one OBJ priority Mode 7 puts below BG1 — and it is the
    difference between a field the saucer eclipses and a field that freckles
    its hull. It works only because the sky is CGRAM index 0 and a Mode 7
    pixel of 0 is transparent, so the plane is a hole everywhere but the disc.
    """
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        k = _Kill()
        seen = []
        for shot in range(6):
            for _ in range(11):
                m.advance(1, pad1=k.pad(m))
            oam = _oam(m)
            pic = _picture(_pixels(m, tmp_path / f"s{shot}.png"))
            star_px = _colour_pixels(pic, STAR_COLOURS)
            spans = _disc_rows(pic)
            eclipsed = sum(1 for (c, r) in star_px
                           if r in spans and spans[r][0] <= c <= spans[r][1])
            # every lit star pixel is inside some star slot's declared cell:
            # the field is where OAM says it is, not painted anywhere else
            cells = {(x + c, (y + r) & 0xFF)
                     for (_, x, y) in _star_boxes(oam)
                     for r in range(8) for c in range(8)}
            stray = len(star_px - cells)
            # ...and the PLANE's sky is one flat tone: every pixel that is
            # neither inside the disc's span nor inside some sprite's cell is
            # the backdrop, exactly. This is the clause that fires the day
            # anyone paints a star field back into the world tile grid — the
            # field's own tones live in an OBJ palette, so a plane-painted one
            # would be a new colour that no population here counts.
            covered = _sprite_pixels(oam)
            open_sky = set()
            for r, row in enumerate(pic):
                lo, hi = spans.get(r, (256, -1))
                open_sky.update(p for c, p in enumerate(row)
                                if not (lo <= c <= hi) and (c, r) not in covered)
            seen.append((len(star_px), eclipsed, stray, open_sky))
        oam = _oam(m)
    backdrop = _rt(GA.SKY_DARK)
    for i, (lit, eclipsed, stray, open_sky) in enumerate(seen):
        assert open_sky == {backdrop}, \
            f"frame {i}: the open sky is not one flat tone ({sorted(open_sky)})"
        assert 60 <= lit < 200, \
            f"frame {i}: the field lights {lit} px — sparse is 60..199"
        assert eclipsed == 0, \
            f"frame {i}: {eclipsed} star px render INSIDE the saucer's disc"
        assert stray == 0, \
            f"frame {i}: {stray} star px outside every star's OAM cell"
    # ...and the slots themselves carry the declared tiles, palette and size
    for i in range(STAR_N):
        x, y, tile, attr = _entry(oam, O_STARS + i)
        want = T_STAR_FAR if i < STAR_FAR_N else T_STAR_NEAR
        assert tile == want, f"star {i} draws tile {tile}, want {want}"
        assert attr == STAR_ATTR, \
            f"star {i} attr {attr:#04x}: want palette 1 + priority 0 " \
            f"({STAR_ATTR:#04x}) — anything else renders it over the plane"
        field = (oam[512 + ((O_STARS + i) >> 2)] >> (((O_STARS + i) & 3) * 2)) & 3
        assert field == 0, f"star {i} hi field {field}: want small, X9 clear"


def test_the_star_field_does_not_scale_when_the_matrix_ramps(tmp_path):
    """THE HEADLINE, and the one assertion a plane-painted field cannot pass.

    Two parks in one lunge — the FAR dwell and the apex — and between them the
    matrix scale falls 900 -> 637, which the disc's rendered span confirms
    against the generator's own predicate (`_disc_px`), so this is a claim
    about a pose that demonstrably changed. Across that ramp every star cell
    that nothing else touches renders EXACTLY its tile's authored lit-pixel
    count: 5 for a far cross, 9 for a near twinkle. A star painted into the
    plane would render 1.41x wider at the apex and blow the count.

    Three lunges, both ends of each, so the case cannot pass on one lucky
    pose; and a floor on how many cells qualified, so a frame where the disc
    swallowed the field cannot read as a pass."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        k = _Kill()
        poses = []
        for cycle in range(3):
            for want, tag, settle in ((LG_FAR, "far", 5), (LG_NEAR, "apex", 3)):
                while _rd16(m, LG_STATE) != want:
                    m.advance(1, pad1=k.pad(m))
                for _ in range(settle):
                    m.advance(1, pad1=k.pad(m))
                oam = _oam(m)
                pic = _picture(_pixels(m, tmp_path / f"{tag}{cycle}.png"))
                spans = _disc_rows(pic)
                span = max(hi - lo + 1 for lo, hi in spans.values())
                clean = []
                for (i, x, y) in _clean_star_boxes(oam):
                    if _box_count(pic, x, y, FACE_COLOURS):
                        continue                   # the disc is over this cell
                    clean.append((i, _box_count(pic, x, y, STAR_COLOURS),
                                  STAR_LIT_FAR if i < STAR_FAR_N
                                  else STAR_LIT_NEAR))
                # the OTHER half of "did not scale": no star pixel anywhere in
                # the picture is outside a star's 8x8 cell. A star drawn any
                # bigger — by the matrix, by the SIZE bit, by anything — spills
                # here even where the count inside the cell is unchanged.
                cells = {(x + c, (y + r) & 0xFF)
                         for (_, x, y) in _star_boxes(oam)
                         for r in range(8) for c in range(8)}
                spill = len(_colour_pixels(pic, STAR_COLOURS) - cells)
                poses.append((cycle, tag, _scale(m), span, spill, clean))
    for (cycle, tag, scale, span, spill, clean) in poses:
        assert spill == 0, \
            f"{tag}{cycle} (scale {scale}): {spill} star px outside every " \
            f"star's own 8x8 cell — the field grew with the matrix"
        assert abs(span - _disc_px(scale)) <= 3, \
            f"{tag}{cycle}: the disc renders {span} px at scale {scale}, not " \
            f"the {_disc_px(scale):.1f} px the matrix calls for"
        assert len(clean) >= 6, \
            f"{tag}{cycle}: only {len(clean)} star cells were unobstructed — " \
            f"too few to prove anything"
        bad = [(i, lit, want) for (i, lit, want) in clean if lit != want]
        assert not bad, \
            f"{tag}{cycle} (scale {scale}): star cells rendered the wrong " \
            f"number of lit pixels {bad} — a star's footprint tracked the matrix"
    far = {(c, s) for (c, t, s, _, _, _) in poses if t == "far"}
    apex = {(c, s) for (c, t, s, _, _, _) in poses if t == "apex"}
    assert len({s for _, s in far}) == 1 and len({s for _, s in apex}) == 1, \
        (far, apex)
    assert next(iter(far))[1] > next(iter(apex))[1], \
        "the two parks did not straddle a scale change at all"


def test_the_star_field_drifts_and_the_fight_sets_its_tempo():
    """MOTION, read off the OAM y bytes the PPU places the stars by, and keyed
    to the ROM's own state rather than to a frame counter.

    The near band's drift is CALM outside the fight and quickens once inside
    it, once per HP third — the same escalation the FAR dwell already encodes
    (SAU_FAR_P0/P1/P2), made visible in the sky. The far band takes half of
    whatever the near band gets, which is the parallax that separates the two
    depths. Measured over 60-frame windows, with the phase asserted unchanged
    at both ends so a window cannot straddle a step.

    The absolute floor matters as much as the ordering: the calm band must
    clear 6 px per 60 frames (7.5 px/s) or the drift is invisible in a 20 fps
    clip, which is the same as not having one."""
    def travel(m, k, n=60):
        a = _oam(m)
        y0 = (_entry(a, O_STARS)[1], _entry(a, O_STARS + STAR_FAR_N)[1])
        ph0 = _rd16(m, _sym("US_B_PHASE")["start"])
        for _ in range(n):
            m.advance(1, pad1=k.pad(m) if k else {})
        a = _oam(m)
        y1 = (_entry(a, O_STARS)[1], _entry(a, O_STARS + STAR_FAR_N)[1])
        return ((y1[0] - y0[0]) & 0xFF, (y1[1] - y0[1]) & 0xFF,
                ph0, _rd16(m, _sym("US_B_PHASE")["start"]))
    with Machine(ROM) as m:
        _run_until(m, ST, HOLD, 200)
        calm_far, calm_near, _, _ = travel(m, None)
        assert _rd16(m, ST) in (HOLD, FIGHT)
        _run_until(m, ST, FIGHT, 300)
        k = _Kill()
        rates = {}
        for want in (0, 1, 2):
            while _rd16(m, _sym("US_B_PHASE")["start"]) != want:
                m.advance(1, pad1=k.pad(m))
            f, n, p0, p1 = travel(m, k)
            assert p0 == p1 == want, f"the phase-{want} window straddled a step"
            assert _rd16(m, ST) == FIGHT, "the fight ended inside the window"
            rates[want] = (f, n)
    assert calm_near >= 6, \
        f"the calm sky drifts {calm_near} px per 60 frames — a viewer cannot " \
        f"see that in a clip"
    assert calm_near < rates[0][1] < rates[1][1] < rates[2][1], \
        f"the fight does not quicken the sky (calm {calm_near}, " \
        f"phases {[rates[p][1] for p in (0, 1, 2)]})"
    for tag, (f, n) in [("calm", (calm_far, calm_near))] + \
            [(f"phase{p}", rates[p]) for p in (0, 1, 2)]:
        assert abs(2 * f - n) <= 2, \
            f"{tag}: the far band moved {f} px against the near band's {n} — " \
            f"the two depths are not parallaxed"


def test_the_star_field_parallaxes_against_the_strafe_both_ways():
    """The one honest source of SIDEWAYS motion on a rail whose camera does not
    travel: the gunship is the viewpoint, so its strafe slides the field the
    other way. Driven through the whole cycle — left to the wall, right to the
    far wall, then held still — because a test that only walks one direction
    locks that direction and ships the other broken.

    Read on the OAM x bytes, and on BOTH bands: the near band's slide is twice
    the far band's, the same 2:1 the drift has."""
    def xs(m):
        a = _oam(m)
        return (_entry(a, O_STARS)[0], _entry(a, O_STARS + STAR_FAR_N)[0])
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        m.advance(4)
        px0 = _rd16(m, PX)
        home = xs(m)
        m.advance(60, pad1={"left": True})       # into the left wall
        left_px, left = _rd16(m, PX), xs(m)
        m.advance(90, pad1={"right": True})      # ...and across to the right
        right_px, right = _rd16(m, PX), xs(m)
        idle = xs(m)
        m.advance(20)                            # nothing held: no slide
        idle2 = xs(m)
    assert left_px < px0 < right_px, (left_px, px0, right_px)
    assert left[0] > home[0] and left[1] > home[1], \
        f"strafing LEFT did not slide the field right ({home} -> {left})"
    assert right[0] < home[0] and right[1] < home[1], \
        f"strafing RIGHT did not slide the field left ({home} -> {right})"
    far_swing = left[0] - right[0]
    near_swing = left[1] - right[1]
    assert abs(2 * far_swing - near_swing) <= 2, \
        f"the bands are not parallaxed: far swung {far_swing}, near {near_swing}"
    assert idle == idle2, \
        f"the field slid sideways with nothing held ({idle} -> {idle2})"


# =============================================================================
# The BEAM — the attack that replaced the boss rail's orb rain
# =============================================================================
def _walk(beam_x):
    """The sixteen cell positions the ASM's walk produces, re-derived here from
    saucer.inc's constants: an 8.8 x accumulator seeded on the emitter and
    stepped by (beam_x - X0) * MUL, and a whole-pixel y cursor stepped by
    PITCH. Two's complement, 16 bits, exactly as the 65816 does it."""
    step = ((beam_x - BEAM_X0) * BEAM_MUL) & 0xFFFF
    acc = (BEAM_X0 << 8) & 0xFFFF
    out = []
    for i in range(BEAM_SEGS):
        out.append(((acc >> 8) & 0xFF, BEAM_Y0 + i * BEAM_PITCH))
        acc = (acc + step) & 0xFFFF
    return out


def test_the_beam_lances_from_the_saucers_emitter_to_the_locked_column(tmp_path):
    """THE OWNER-REPORTED DEFECT, and the invariant that fixes it. The debut
    stacked sixteen cells straight down from row 56 at the player's x, so the
    beam touched the saucer only by coincidence and read as a flat line
    somebody had left on the screen. The beam now WALKS from the saucer's
    ventral emitter to the latched column.

    THE EMITTER IS THE MODE 7 PIVOT and `m7a_set_center` shows the pivot at
    the screen centre, so the matrix changes how BIG the emitter renders and
    never WHERE. This case reads that back off the PICTURE: at every sample the
    first cell's 8x8 footprint must sit inside the emitter disc as RENDERED —
    a bbox measured from the screenshot in the emitter's own two tones, which
    at rest is only 15 px across, so an origin four pixels out fails.

    AND IT IS SAMPLED AT DIFFERENT SCALES, which is why the telegraph was
    moved into the dive. Four telegraph frames spread across the approach plus
    a firing frame at the apex give five poses; the case REQUIRES the rendered
    emitter to have grown across them (the non-vacuity guard), so "the beam
    coincides with the emitter" cannot pass by both of them standing still.

    The other three claims: the drawn cells are exactly the walk saucer.inc
    describes (an oracle, not a remembered list); the last one lands on the
    latched column, which is NOT the spawn lane because the drive strafes to
    the clamp before the latch (`make falsify`'s `beam-column-not-locked`
    plant is what proved that necessary); and every rendered beam pixel lies
    within a cell's width of the straight line between the two ends — the
    picture-level statement that this is a lance from the saucer to the ship
    and not a bar somewhere else."""
    from frame_geometry import png_row

    def sample(m, name):
        # every WRAM/OAM read happens BEFORE the screenshot: `_pixels` costs
        # one emulated frame, and the beam's phase can flip inside it — read
        # after, and the OAM is one state behind the flag it is checked against
        oam = _oam(m)
        cells = [(_entry(oam, O_BEAM + i)[0], _entry(oam, O_BEAM + i)[1],
                  _entry(oam, O_BEAM + i)[2]) for i in range(BEAM_SEGS)]
        state, bx, scale = _rd16(m, BM_STATE), _rd16(m, BEAM_X), _scale(m)
        img = _pixels(m, tmp_path / name)
        return dict(state=state, bx=bx,
                    scale=scale, cells=cells,
                    emit=_bbox(img, EMITTER_COLOURS),
                    beam=[(i % img.width, i // img.width)
                          for i, px in enumerate(img.getdata())
                          if px in BEAM_COLOURS])

    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, BM_STATE, BM_OFF, 200)
        oam = _oam(m)
        assert all(_entry(oam, O_BEAM + i)[1] == PARK_Y
                   for i in range(BEAM_SEGS)), \
            "a beam cell is on screen while OFF"

        # strafe to the left clamp so the latch cannot be the spawn lane
        _run_until(m, BM_STATE, BM_TELE, 500, pad={"left": True}, step=1)
        assert _rd16(m, PX) < 120, "(sequencing) the ship never left the lane"
        shots = []
        for k in range(4):
            m.advance(1 if k == 0 else 6, pad1={"left": True})
            if _rd16(m, BM_STATE) != BM_TELE:
                break
            shots.append(sample(m, f"tele{k}.png"))
        _run_until(m, BM_STATE, BM_FIRE, 200, step=1)
        m.advance(2)
        shots.append(sample(m, "fire.png"))

    assert len(shots) >= 4, f"only {len(shots)} beam frames sampled"
    for k, sh in enumerate(shots):
        bx, cells = sh["bx"], sh["cells"]
        assert bx != SPAWN_X + 4, \
            "the column sits on the SPAWN lane after the ship left it — " \
            "a fixed column, not a latched one"
        want = _walk(bx)
        drawn = [i for i in range(BEAM_SEGS) if cells[i][1] != PARK_Y]
        if sh["state"] == BM_TELE:
            assert drawn == list(range(0, BEAM_SEGS, 2)), \
                f"frame {k} telegraph is not the sparse every-other read: {drawn}"
            assert all(cells[i][2] == T_BEAM_TELE for i in drawn), \
                f"frame {k} telegraph is not drawn with the sight cell"
        else:
            assert drawn == list(range(BEAM_SEGS)), \
                f"frame {k} fire left cells parked: {drawn}"
            assert cells[0][2] == T_BEAM_FLARE and \
                cells[BEAM_SEGS - 1][2] == T_BEAM_FLARE, \
                "the muzzle and impact bursts are missing"
            assert all(cells[i][2] == T_BEAM for i in range(1, BEAM_SEGS - 1))
        for i in drawn:
            assert (cells[i][0], cells[i][1]) == want[i], \
                f"frame {k} cell {i} at {cells[i][:2]}, the walk says {want[i]}"
        # the two ends: the emitter, and the latched column
        assert (cells[0][0], cells[0][1]) == (BEAM_X0, BEAM_Y0)
        assert abs(want[BEAM_SEGS - 1][0] - bx) <= 2, \
            f"frame {k} the lance ends at x={want[BEAM_SEGS - 1][0]}, not on " \
            f"the latched column {bx}"
        # ...and the first cell is INSIDE the emitter as rendered
        ex0, ey0, ex1, ey1 = sh["emit"]
        assert ex0 <= BEAM_X0 and BEAM_X0 + 7 <= ex1, \
            f"frame {k}: the lance starts at x {BEAM_X0}..{BEAM_X0 + 7}, " \
            f"outside the rendered emitter's {ex0}..{ex1}"
        assert ey0 <= png_row(BEAM_Y0) and png_row(BEAM_Y0) + 7 <= ey1, \
            f"frame {k}: the lance starts at rows {png_row(BEAM_Y0)}.." \
            f"{png_row(BEAM_Y0) + 7}, outside the rendered emitter's {ey0}..{ey1}"
        # every rendered beam pixel is on the line between the two ends
        assert sh["beam"], f"frame {k} rendered no beam pixels at all"
        ax, ay = BEAM_X0 + 4, png_row(BEAM_Y0) + 4
        bxx, byy = want[BEAM_SEGS - 1][0] + 4, png_row(want[BEAM_SEGS - 1][1]) + 4
        dx, dy = bxx - ax, byy - ay
        norm = (dx * dx + dy * dy) ** 0.5
        far = max(abs((px - ax) * dy - (py - ay) * dx) / norm
                  for px, py in sh["beam"])
        assert far <= 6, \
            f"frame {k}: a beam pixel sits {far:.1f} px off the emitter->column " \
            f"line — the lance is not straight between its two ends"

    scales = [sh["scale"] for sh in shots]
    widths = [sh["emit"][2] - sh["emit"][0] for sh in shots]
    # the telegraph is armed with TELE_F - 1 frames of the dive left, so by
    # construction it spans appr[LUNGE_FRAMES + 1 - TELE_F] .. the apex
    appr_scales = [a for a, _ in GT.build_appr()]
    designed = appr_scales[GT.LUNGE_FRAMES + 1 - 24] / GT.NEAR_SCALE
    assert designed > 1.15, \
        f"the telegraph no longer spans a scale range ({designed:.3f}x): the " \
        f"multi-scale claim below has nothing to stand on"
    assert len(set(scales)) >= 4, \
        f"the beam was photographed at fewer than four poses: {scales}"
    assert max(scales) >= min(scales) * 1.15, \
        f"these samples span {max(scales) / min(scales):.3f}x of scale, not " \
        f"the telegraph's designed {designed:.3f}x: {scales}"
    assert widths[-1] > widths[0], \
        f"the rendered emitter never grew across the dive ({widths}) — the " \
        f"multi-scale claim would be vacuous"


def test_strafing_out_of_the_telegraph_dodges_the_beam(tmp_path):
    """The rail's central gameplay claim, driven on the pad and asserted on
    the RENDER, both arms. The dive latches the column onto wherever the ship
    is; the telegraph is the window to leave it. ARM A (hold the latched
    lane): the ship's hit-flash frame appears in OAM slot 0 and the
    flash-white tone appears on screen. ARM B (strafe out, same drive up to
    the latch): neither ever does. p_hp only sequences — the assertion is
    what the player SEES.

    Both arms drive to the LEFT CLAMP before the latch, for the reason the
    lock test's docstring gives: on the spawn lane a fixed column and a
    latched one are the same picture, so the two arms would not depend on
    the latch at all."""
    def _run(dodge):
        flash_tiles, flash_px = set(), 0
        with Machine(ROM) as m:
            _run_until(m, ST, FIGHT, 300)
            # the column is latched onto the clamp lane, not the spawn lane
            _run_until(m, BM_STATE, BM_TELE, 500, pad={"left": True}, step=1)
            pad = {"right": True} if dodge else {"left": True}
            hp0 = _rd16(m, PHP)
            for i in range(70):
                m.advance(1, pad1=pad)
                flash_tiles.add(_oam(m)[2])
                if _rd16(m, PIF):
                    img = _pixels(m, tmp_path / f"f{int(dodge)}_{i}.png")
                    flash_px = max(flash_px, _count(img, {FLASH_COLOUR}))
                if _rd16(m, BM_STATE) == BM_OFF and i > 24:
                    break
            return hp0, _rd16(m, PHP), flash_tiles, flash_px

    hp0, hp_hit, tiles_hit, px_hit = _run(dodge=False)
    assert 2 in tiles_hit, f"standing in the column never flashed the ship {tiles_hit}"
    assert px_hit > 20, "the white flash frame never rendered"
    assert hp_hit == hp0 - 1, "(sequencing) the idle arm did not take a hit"

    hp0, hp_dodge, tiles_dodge, px_dodge = _run(dodge=True)
    assert tiles_dodge == {0}, \
        f"strafing out still flashed the ship (OAM slot 0 tiles {tiles_dodge})"
    assert px_dodge == 0, "the dodge arm still rendered a hit flash"
    assert hp_dodge == hp0, "(sequencing) the dodge arm lost a heart"


# =============================================================================
# Input -> the visible result, both directions and the idle
# =============================================================================
def test_the_gunship_strafes_both_directions_on_screen(tmp_path):
    """Pad to pixels, end to end: LEFT moves the hull's rendered centroid
    left, RIGHT moves it right, no input holds it still. Catches a
    self-consistent-but-reversed mapping a WRAM assertion cannot."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        m.advance(1)
        x0, _, n0 = _centroid(_pixels(m, tmp_path / "0.png"), SHIP_COLOURS)
        assert n0 > 40, f"the gunship is not on screen ({n0} px)"
        m.advance(12, pad1={"left": True})
        m.advance(1)
        x1, _, n1 = _centroid(_pixels(m, tmp_path / "1.png"), SHIP_COLOURS)
        assert n1 > 40
        assert x1 < x0 - 20, f"LEFT did not move the ship left ({x0}->{x1})"
        m.advance(12, pad1={"right": True})
        m.advance(12, pad1={"right": True})
        m.advance(1)
        x2, _, _ = _centroid(_pixels(m, tmp_path / "2.png"), SHIP_COLOURS)
        assert x2 > x1 + 20, f"RIGHT did not move the ship right ({x1}->{x2})"
        m.advance(10)                          # idle: nothing held
        m.advance(1)
        x3, _, _ = _centroid(_pixels(m, tmp_path / "3.png"), SHIP_COLOURS)
        assert abs(x3 - x2) < 6, f"idle drifted the ship ({x2}->{x3})"


def test_holding_a_fires_bolts_that_climb_and_cost_the_saucer_hp(tmp_path):
    """Cyan bolt pixels appear above the ship and their centroid CLIMBS frame
    to frame; the saucer's HP falls as they land, and the fall is visible on
    the rendered HUD (a lit pip becomes a dim one). The bolt predicate rejects
    the hull tones by construction."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        lit0 = sum(1 for s in range(8)
                   if _entry(_oam(m), O_HUD + s)[2] == T_PIP_LIT)
        assert lit0 == 8, f"the fight did not start on a full HUD ({lit0})"
        ys = []
        for i in range(10):
            m.advance(3, pad1={"a": True})
            _, y, n = _centroid(_pixels(m, tmp_path / f"b{i}.png"),
                                {BOLT_COLOUR})
            if n >= 6:
                ys.append(y)
        assert len(ys) >= 3, "no bolt ever rendered while A was held"
        assert min(ys) < ys[0], f"bolts never climbed: {ys}"
        for _ in range(40):
            m.advance(6, pad1={"a": True})
            lit = sum(1 for s in range(8)
                      if _entry(_oam(m), O_HUD + s)[2] == T_PIP_LIT)
            if lit < 8:
                break
    assert lit < 8, "landed bolts never dimmed a rendered HUD pip"


def test_the_hud_pips_dim_exactly_at_the_hp_thresholds():
    """The eight HUD OAM entries (slots 17-24) show lit-vs-dim tiles matching
    count(hp > i * 30) at every sampled fight frame — the rendered HUD is a
    function of HP, read from the OAM bytes it is drawn through.

    THE DRIVE IS THE WINNING ONE: the saucer's hitbox is its RENDERED disc
    now, so a bolt only lands from under it, and a beam that lands costs a
    heart — standing still under the saucer holding A ends the fight in a LOSE
    less than four hundred frames in, before the HUD has been sampled."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        k = _Kill()
        checked = 0
        for _ in range(120):
            for _ in range(3):
                m.advance(1, pad1=k.pad(m))
            if _rd16(m, ST) != FIGHT:
                break
            hp_before = _rd16(m, BHP)
            m.advance(1)                        # settle: OAM lags one advance
            hp = _rd16(m, BHP)
            if hp != hp_before:
                continue                        # a landing raced the sample
            oam = _oam(m)
            tiles = [_entry(oam, O_HUD + s)[2] for s in range(8)]
            want_lit = sum(1 for i in range(8) if hp > i * 30)
            lit = sum(1 for t in tiles if t == T_PIP_LIT)
            dim = sum(1 for t in tiles if t == T_PIP_DIM)
            assert lit + dim == 8, f"HUD slots hold foreign tiles: {tiles}"
            assert lit == want_lit, (hp, tiles)
            checked += 1
        assert checked > 20, "the fight ended before the HUD was exercised"


def test_shot_slots_recycle_between_flights():
    """The pool lifecycle on the OAM bytes: across a window of held-A fight
    frames every shot slot's y is either PARKED (exactly 240) or inside the
    flight corridor (spawn 176 up to the cull at 16), and at least one slot is
    OBSERVED going live -> parked. A shot whose kill is dropped wraps the
    whole 16-bit y space and renders through the 177..239 band no healthy
    frame can show — the band IS the assertion."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        was_live = [False] * 4
        recycled = False
        for _ in range(50):
            m.advance(2, pad1={"a": True})
            oam = _oam(m)
            for s in range(4):
                y = _entry(oam, O_SHOTS + s)[1]
                live = y != PARK_Y
                assert (not live) or (10 <= y <= 176), \
                    f"shot slot {O_SHOTS + s} at y={y}: outside the flight " \
                    f"corridor and not parked — a leaked or wrapped slot"
                if was_live[s] and not live:
                    recycled = True
                was_live[s] = live
        assert recycled, "no shot slot was ever seen returning to the pool"


# =============================================================================
# The kill: the break-off, the recede, the card, the loop
# =============================================================================
def test_the_kill_climbs_the_lunge_home_before_the_recede(tmp_path):
    """The break-off held to account on the matrix the floor renders with. A baked
    track is absolute, so the recede can only start at its own entry 0; the
    kill therefore steers the lunge home first. Asserted: from the frame the
    saucer's HP reaches 0, M7A climbs MONOTONICALLY (the saucer pulls away)
    for a bounded number of frames, and the first DEATH park is EXACTLY
    death[0] == ring[0] == appr[0], identity halves included. The rendered
    half: the face area at the last fight park and the first death park differ
    by less than one ramp step's worth, so the handover cannot be a pop."""
    ring, death, appr = GT.build_ring(), GT.build_death(), GT.build_appr()
    assert death[0] == ring[0] == appr[0], "the generator's own seam moved"
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        k = _Kill()
        for _ in range(3000):
            m.advance(1, pad1=k.pad(m))
            if _rd16(m, BHP) == 0:
                break
        assert _rd16(m, BHP) == 0, "the kill never landed"
        climb = []
        for _ in range(80):
            m.advance(1, pad1=k.pad(m))
            climb.append((_rd16(m, ST), _shadow(m)[0]))
            if climb[-1][0] == DEATH:
                break
        assert climb[-1][0] == DEATH, f"never handed over in {len(climb)} frames"
        assert len(climb) <= GT.LUNGE_FRAMES + 1, \
            f"the break-off ran {len(climb)} frames, past its bound"
        a_seq = [a for _, a in climb]
        assert all(y >= x for x, y in zip(a_seq, a_seq[1:])), \
            f"M7A did not climb monotonically home: {a_seq}"
        a, b, c, d = _shadow(m)
        assert (a, b) == tuple(death[0]) == (GT.INIT_SCALE, 0), (a, b)
        assert d == a and c == -b
        last_fight = _count(_pixels(m, tmp_path / "seam0.png"), FACE_COLOURS)
        m.advance(1)
        first_death = _count(_pixels(m, tmp_path / "seam1.png"), FACE_COLOURS)
    assert abs(first_death - last_fight) < max(700, last_fight * 0.08), \
        (last_fight, first_death)


def test_the_win_cycle_recede_card_and_loop(tmp_path):
    """The full forward cycle on rendered surfaces: the kill dims every pip
    (OAM), the recede SHRINKS the face across parked frames (pixels), the
    VICTORY word renders as glyph sprites over a STILL-VISIBLE arena
    (the invariant is dim-not-black, not any one dimming mechanism), and the loop
    re-arms — the saucer small again with full HP."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _kill_until(m, ST, DEATH)
        n_start = _count(_pixels(m, tmp_path / "d0.png"), FACE_COLOURS)
        oam = _oam(m)
        assert all(_entry(oam, O_HUD + s)[2] == T_PIP_DIM for s in range(8)), \
            "a dead saucer still shows lit pips"
        m.advance(28)
        n_mid = _count(_pixels(m, tmp_path / "d1.png"), FACE_COLOURS)
        m.advance(28)
        n_end = _count(_pixels(m, tmp_path / "d2.png"), FACE_COLOURS)
        assert n_start > n_mid > n_end > 0, (n_start, n_mid, n_end)
        # the recede runs INIT -> INIT + 56 * REVEAL_STEP over these 56 frames,
        # and area goes as 1/scale^2, so the shrink is derived rather than
        # remembered
        want = ((GT.INIT_SCALE + 56 * GT.REVEAL_STEP) / GT.INIT_SCALE) ** 2
        assert n_start / n_end > want * 0.85, \
            f"the recede shrank the saucer {n_start / n_end:.2f}x, not the " \
            f"{want:.2f}x its own schedule calls for"
        _run_until(m, ST, RES_ST, 60)
        assert _rd16(m, RESULT) == 1
        m.advance(2)
        oam = _oam(m)
        word = [_entry(oam, O_CARDS + i)[2] for i in range(7)]
        assert word == [GA.GLYPH_TILE[ch] for ch in "VICTORY"], word
        assert all(_entry(oam, O_CARDS + i)[1] == 100 for i in range(7))
        assert all(_entry(oam, O_CARDS + 7 + i)[2] == T_CARDBG
                   for i in range(2 * 8)), "the banner is not behind the word"
        img = _pixels(m, tmp_path / "win.png")
        assert _count(img, {GLYPH_COLOUR}) > 40, "the VICTORY word is not lit"
        assert _count(img, FACE_COLOURS) > 500, \
            "the win card is not over a still-visible arena"
        _run_until(m, ST, RESET, 200)
        _run_until(m, ST, REVEAL, 120)
        assert _rd16(m, BHP) == 240, "the loop did not re-arm the battle"
        m.advance(22)                          # the fade-in's 15 steps, done
        n_again = _count(_pixels(m, tmp_path / "loop.png"), FACE_COLOURS)
    assert 0 < n_again < n_start, \
        f"the re-revealed saucer is not small again ({n_again} vs {n_start})"


def test_the_lose_path_shows_the_defeat_card_over_a_live_arena(tmp_path):
    """No input at all: the locked beam wears the stationary gunship down (the
    the deterministic LOSE path), and the RESULT frame renders the DEFEAT
    word as glyph sprites over an arena that is STILL THERE. That is the
    the stated invariant for its dim-not-black hold — the mechanism
    differs, the thing a player sees does not. The word's first
    glyph also disambiguates the outcome from the win card's, exactly as the
    the oracle uses it."""
    with Machine(ROM) as m:
        _run_until(m, ST, LOSE, 900, step=4)
        assert _rd16(m, PHP) == 0
        _run_until(m, ST, RES_ST, 120)
        assert _rd16(m, RESULT) == 2
        m.advance(2)
        oam = _oam(m)
        word = [_entry(oam, O_CARDS + i)[2] for i in range(6)]
        assert word == [GA.GLYPH_TILE[ch] for ch in "DEFEAT"], word
        assert word[0] != GA.GLYPH_TILE["V"], "the outcome is not disambiguated"
        img = _pixels(m, tmp_path / "lose.png")
        assert _count(img, {GLYPH_COLOUR}) > 30, "the DEFEAT word is not lit"
        assert _count(img, FACE_COLOURS) > 500, \
            "the defeat card is not over a still-visible arena"
        assert _count(img, SHIP_COLOURS) == 0, \
            "the gunship is still drawn on the result card"
        _run_until(m, ST, REVEAL, 300)
        m.advance(24)
        assert _count(_pixels(m, tmp_path / "again.png"), FACE_COLOURS) > 0, \
            "the loop never faded back into a reveal"


# =============================================================================
# Pause, the slot map, the palettes, the blobs
# =============================================================================
def test_start_freezes_the_fight_and_releases_it(tmp_path):
    """START's rising edge freezes the battle and a second press releases it.
    Asserted on both rendered surfaces the freeze claims: the saucer's matrix
    (the readable shadow) does not change, and the gunship's rendered centroid
    does not move EVEN WITH RIGHT HELD — a paused fight ignores the pad. Then
    the release is asserted the same way, so a test cannot pass on a ROM that
    simply never unfreezes.

    The freeze is taken during the APPROACH deliberately: that is the one
    sub-state whose matrix changes EVERY frame, so "the shadow did not move"
    is a claim about a stopped animation rather than about the FAR dwell,
    where a healthy ROM holds one pose anyway (measured: pausing in FAR made
    the release half of this test unfalsifiable)."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, LG_STATE, LG_APPR, 200, step=1)
        m.advance(1)
        m.advance(1, pad1={"start": True})     # the rising edge
        m.advance(1)
        frozen_shadow = _shadow(m)
        x0, _, n0 = _centroid(_pixels(m, tmp_path / "p0.png"), SHIP_COLOURS)
        assert n0 > 40
        m.advance(30, pad1={"right": True})
        m.advance(1)
        assert _shadow(m) == frozen_shadow, "the matrix advanced while paused"
        x1, _, _ = _centroid(_pixels(m, tmp_path / "p1.png"), SHIP_COLOURS)
        assert x1 == x0, f"the gunship moved while paused ({x0} -> {x1})"
        m.advance(1, pad1={"start": True})     # release
        m.advance(30, pad1={"right": True})
        m.advance(1)
        assert _shadow(m) != frozen_shadow, "the matrix stayed frozen after release"
        x2, _, _ = _centroid(_pixels(m, tmp_path / "p2.png"), SHIP_COLOURS)
    assert x2 > x1 + 20, f"the gunship did not move after release ({x1}->{x2})"


def test_oam_slot_identities_hold_mid_fight():
    """The reference's stable-slot contract on the OAM bytes: slot 0 is the
    gunship (16x16 LARGE bit set), 1-16 are beam segments or parked, 17-24 are
    pips, 25-28 are bolts or parked, 29 is the thruster, 30-53 are card cells
    or parked (no card during the fight), 54-55 parked for the ROM's life,
    56-79 are the star field and are NEVER parked; the hi-table SIZE bit is
    set for exactly slot 0, and all twenty hi bytes are owned."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        m.advance(40, pad1={"a": True})        # bolts live, a lunge under way
        oam = _oam(m)
    assert _entry(oam, 0)[2] in (0, 2), f"slot 0 tile {oam[2]} is not a ship frame"
    assert _entry(oam, 0)[1] != PARK_Y, "the gunship is parked mid-fight"
    for s in range(O_BEAM, O_BEAM + BEAM_SEGS):
        tile, y = _entry(oam, s)[2], _entry(oam, s)[1]
        assert tile in (T_BEAM, T_BEAM_TELE, T_BEAM_FLARE) or y == PARK_Y, \
            (s, tile, y)
    for s in range(O_HUD, O_HUD + 8):
        assert _entry(oam, s)[2] in (T_PIP_LIT, T_PIP_DIM), (s, _entry(oam, s))
    for s in range(O_SHOTS, O_SHOTS + 4):
        tile, y = _entry(oam, s)[2], _entry(oam, s)[1]
        assert tile == T_SHOT or y == PARK_Y, (s, tile, y)
    assert _entry(oam, O_EXH)[2] in (9, 10), "the thruster flame is not drawn"
    for s in range(O_CARDS, O_PAD + 2):
        assert _entry(oam, s)[1] == PARK_Y, f"slot {s} is drawn during the fight"
    for i in range(STAR_N):
        tile, y = _entry(oam, O_STARS + i)[2], _entry(oam, O_STARS + i)[1]
        assert tile == (T_STAR_FAR if i < STAR_FAR_N else T_STAR_NEAR), \
            (O_STARS + i, tile)
        assert y != PARK_Y, f"star slot {O_STARS + i} is parked mid-fight"
    n_hi = (O_STARS + STAR_N) // 4
    hi = oam[512:512 + n_hi]
    for s in range(O_STARS + STAR_N):
        field = (hi[s // 4] >> ((s % 4) * 2)) & 3
        if s == 0:
            assert field == 2, f"the gunship slot is missing the LARGE bit ({field})"
        else:
            assert field == 0, f"slot {s} hi field {field} (want 0)"


def test_the_palettes_land_where_the_claims_say():
    """CGRAM words 0..15 == sau_pal.bin and 128..159 == sau_sprite_pal.bin —
    the destination region byte-for-byte against the authored source (the
    asset-upload sub-rule: read the DESTINATION, not a downstream consumer).

    The sprite blob is 32 words now, not 16: it carries BOTH OBJ palettes, the
    cast's at 128 and the star field's at 144, and one enter-time loop uploads
    them because the two claims are pinned contiguous. A read of only the
    first sixteen would pass on a ROM that never uploaded the star tones —
    which renders the field in whatever CGRAM 144.. held at power-on."""
    floor = Path("build/assets/sau_pal.bin").read_bytes()
    spr = Path("build/assets/sau_sprite_pal.bin").read_bytes()
    assert len(spr) == 64, f"the sprite palette blob is {len(spr)} B, not both"
    with Machine(ROM) as m:
        m.advance(6)
        cg = m.read_bytes(MemoryType.SnesCgRam, 0, 512)
    assert bytes(cg[0:32]) == floor, "floor palette not at CGRAM 0"
    assert bytes(cg[256:320]) == spr, \
        "the two OBJ palettes are not both at CGRAM 128.."
    assert 2 * STAR_PAL == 288, "the star palette moved off CGRAM word 144"


def test_the_track_blobs_hold_their_format_and_their_seams():
    """Pure-source check of the shipped bytes: count headers, entry counts,
    the FOUR handovers the state machine performs, and the ring against the
    generator formula. (The emulator half of this contract is the three
    matrix oracles above.)"""
    want = {"sau_ring": 256, "sau_reveal": 61,
            "sau_appr": GT.LUNGE_FRAMES + 1, "sau_retr": GT.LUNGE_FRAMES + 1,
            "sau_death": 61}
    ent = {}
    for name, n_want in want.items():
        blob = Path(f"build/assets/{name}.bin").read_bytes()
        n = struct.unpack_from("<H", blob, 0)[0]
        assert n == n_want and len(blob) == 2 + 4 * n, (name, n, len(blob))
        ent[name] = [struct.unpack_from("<hh", blob, 2 + 4 * i)
                     for i in range(n)]
    ring, reveal = ent["sau_ring"], ent["sau_reveal"]
    appr, retr, death = ent["sau_appr"], ent["sau_retr"], ent["sau_death"]
    N = GT.LUNGE_FRAMES
    assert reveal[60] == ring[60], "the reveal->hold seam drifted"
    assert appr[0] == ring[0] == (GT.INIT_SCALE, 0), \
        "the hold->fight seam drifted"
    assert retr[0] == appr[N], "the near->retreat seam drifted"
    assert retr[N] == appr[0], "the retreat->far seam drifted"
    assert death[0] == ring[0], "the fight->death seam drifted"
    assert ring == [tuple(e) for e in GT.build_ring()]
    assert reveal[0] == (GT.REVEAL_SCALE, 0), \
        "the pre-reveal pose is not far+unrotated"
    # ...and the recede lands back on it, so the loop closes on ONE size
    assert GT.INIT_SCALE + GT.REVEAL_STEP * GT.REVEAL_FRAMES == GT.REVEAL_SCALE
    assert appr[::-1] != retr, \
        "the two lunge ramps became reverses — one blob would do"


# =============================================================================
# The audio — the tail's one composing rail, on SPC-side hardware state
# =============================================================================
def test_the_theme_plays_and_the_beam_swells_the_arena_echo():
    """Audio's rendered output is SPC-side hardware state. Three claims, one
    drive: the TAD driver reaches PLAYING; the SPC's own songTickCounter
    ADVANCES between two parked frames (the theme is running, not merely
    loaded); and the S-DSP echo registers walk the FULL cycle the rail
    composes — rest -> the beam ignites and the arena rings -> the beam ends
    and it settles back. A snapshot of any one of those passes on a driver
    that queued nothing."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        assert m.read_bytes(MemoryType.SnesWorkRam, TAD_STATE, 1)[0] == \
            TAD_PLAYING, "the TAD driver never reached PLAYING"
        t0 = _song_tick(m)
        m.advance(30)
        t1 = _song_tick(m)
        assert t1 > t0, f"the song tick did not advance ({t0} -> {t1})"
        assert _echo(m) == ECHO_REST, f"the arena's rest echo is {_echo(m)}"
        _run_until(m, BM_STATE, BM_FIRE, 500, step=1)
        m.advance(4)
        assert _echo(m) == ECHO_BEAM, \
            f"the beam did not swell the echo ({_echo(m)})"
        _run_until(m, BM_STATE, BM_OFF, 120, step=1)
        m.advance(6)
        assert _echo(m) == ECHO_REST, \
            f"the echo did not settle back after the beam ({_echo(m)})"


def test_the_boot_title_shows_the_controls_then_clears(tmp_path):
    """The reference added its title card because a reviewer played three loops
    without discovering A = fire. Both rows render as glyph sprites in the
    card band before the fight and the whole band is parked once the fight
    starts — asserted on the OAM tiles and on the lit glyph pixels."""
    with Machine(ROM) as m:
        m.advance(30)
        oam = _oam(m)
        row1 = [_entry(oam, O_CARDS + i)[2] for i in range(10)]
        row2 = [_entry(oam, O_CARDS + 10 + i)[2] for i in range(11)]
        assert row1 == [GA.GLYPH_TILE[c] for c in "SAUCERDOWN"], row1
        assert row2 == [GA.GLYPH_TILE[c] for c in "<>MOVEAFIRE"], row2
        assert all(_entry(oam, O_CARDS + i)[1] == 30 for i in range(10))
        assert all(_entry(oam, O_CARDS + 10 + i)[1] == 42 for i in range(11))
        lit = _count(_pixels(m, tmp_path / "title.png"), {GLYPH_COLOUR})
        assert lit > 60, f"the title glyphs are not on screen ({lit} px)"
        _run_until(m, ST, FIGHT, 300)
        m.advance(2)
        oam = _oam(m)
        assert all(_entry(oam, O_CARDS + i)[1] == PARK_Y
                   for i in range(24)), "the title survived into the fight"
        gone = _count(_pixels(m, tmp_path / "nofight.png"), {GLYPH_COLOUR})
    assert gone == 0, f"glyph pixels still on screen during the fight ({gone})"
