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
PARK_Y = 240
O_BEAM, O_HUD, O_SHOTS, O_EXH, O_CARDS, O_PAD = 1, 17, 25, 29, 30, 54
BEAM_SEGS, BEAM_Y0, BEAM_PITCH = 16, 56, 8

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
SKY_COLOURS = {_rt(c) for c in (GA.SKY_DARK, GA.STAR, GA.STAR_DIM)}
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


def _rd16(m, off):
    b = m.read_bytes(MemoryType.SnesWorkRam, off, 2)
    return b[0] | (b[1] << 8)


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
              "glyph": {GLYPH_COLOUR}, "flash": {FLASH_COLOUR}}
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
    the assertion."""
    with Machine(ROM) as m:
        m.advance(22)                         # 3 parks past fade-done
        fade = tuple(m.read_bytes(MemoryType.SnesWorkRam, FADE, 2))
        assert fade == (15, 0), \
            f"early park not at full brightness (fade level/dir {fade})"
        early = _count(_pixels(m, tmp_path / "e.png"), FACE_COLOURS)
        m.advance(19)                         # mid ramp
        mid = _count(_pixels(m, tmp_path / "m.png"), FACE_COLOURS)
        m.advance(20)                         # the LAST park still in REVEAL
        st, timer = _rd16(m, ST), _rd16(m, TIMER)
        assert (st, timer) == (REVEAL, 1), \
            f"rest park drifted out of the ramp (state {st}, timer {timer})"
        rest = _count(_pixels(m, tmp_path / "r.png"), FACE_COLOURS)
    assert 0 < early < mid < rest, (early, mid, rest)
    assert early * 3 < rest, f"far pose {early} not far vs rest {rest}"


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
    assert n1 > 20000, f"the saucer is not at rest size in HOLD ({n1})"
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

    Measured on the emitter probe, not the whole face, for the reason
    EMITTER_COLOURS records: the face count saturates at the apex and cannot
    order two poses there. The final `home` check is what makes this a CYCLE
    rather than two ramps — the pose the dive left from is the pose the climb
    returns to."""
    def emit(m, name):
        n = _count(_pixels(m, tmp_path / name), EMITTER_COLOURS)
        assert n < 30000, f"the emitter probe saturated at {n} px"
        return n

    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, LG_STATE, LG_FAR, 200)
        m.advance(1)
        far = emit(m, "far.png")
        _run_until(m, LG_STATE, LG_APPR, 200)
        m.advance(20)
        mid_in = emit(m, "in.png")
        _run_until(m, LG_STATE, LG_NEAR, 200)
        m.advance(2)
        apex = emit(m, "apex.png")
        _run_until(m, LG_STATE, LG_RETR, 300)
        m.advance(20)
        mid_out = emit(m, "out.png")
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
        climb_end = emit(m, "climb_end.png")
        _run_until(m, LG_STATE, LG_FAR, 300)
        m.advance(2)
        home = emit(m, "home.png")
    assert far < mid_in < apex, ("the dive did not grow", far, mid_in, apex)
    assert apex > mid_out > far, ("the climb did not shrink", apex, mid_out, far)
    assert apex > far * 2, f"the dive barely grew the saucer ({far} -> {apex})"
    assert abs(climb_end - far) < far * 0.15, \
        f"the climb did not END at the rest pose ({far} vs {climb_end})"
    assert abs(home - far) < far * 0.06, \
        f"the cycle did not return to the rest pose ({far} -> {home})"


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
# The BEAM — the attack that replaced the boss rail's orb rain
# =============================================================================
def test_the_beam_renders_a_seamless_column_locked_to_the_player(tmp_path):
    """OAM slots 1-16 and the screenshot, through the beam's WHOLE cycle.
    OFF: every segment parked. TELEGRAPH: only the even segments render, at a
    16 px pitch — the sparse 'charging' read. FIRE: all sixteen render at the
    8 px pitch from BEAM_Y0, every one at the SAME x, and that x is the
    player's body centre (p_x + 4) as latched when the dive reached its apex.

    THE PLAYER IS DRIVEN OFF THE SPAWN LANE BEFORE THE LATCH, and that is
    load-bearing rather than incidental: a beam whose column is a FIXED
    constant is indistinguishable from a latched one while the player has
    never moved, and `make falsify`'s `beam-column-not-locked` plant proved
    that against this test's first version (it reached the artifact and this
    case stayed green). Holding LEFT through the approach puts the latch at
    the clamp lane, so the assertion below is about a column that FOLLOWED."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, BM_STATE, BM_OFF, 200)
        oam = _oam(m)
        assert all(_entry(oam, O_BEAM + i)[1] == PARK_Y
                   for i in range(BEAM_SEGS)), "a beam segment is on screen while OFF"

        # strafe to the left clamp so the apex cannot latch the spawn lane
        _run_until(m, BM_STATE, BM_TELE, 400, pad={"left": True}, step=1)
        m.advance(1, pad1={"left": True})
        assert _rd16(m, PX) < 120, "(sequencing) the ship never left the lane"
        oam = _oam(m)
        drawn = [i for i in range(BEAM_SEGS)
                 if _entry(oam, O_BEAM + i)[1] != PARK_Y]
        assert drawn == list(range(0, BEAM_SEGS, 2)), \
            f"the telegraph is not the sparse every-other read: {drawn}"
        for i in drawn:
            assert _entry(oam, O_BEAM + i)[1] == BEAM_Y0 + i * BEAM_PITCH

        _run_until(m, BM_STATE, BM_FIRE, 200, step=1)
        m.advance(1)
        oam = _oam(m)
        px, bx = _rd16(m, PX), _rd16(m, BEAM_X)
        assert bx == px + 4, f"the column is not the body centre ({bx} vs {px})"
        assert bx != 120 + 4, \
            "the column sits on the SPAWN lane after the ship left it — " \
            "a fixed column, not a latched one"
        for i in range(BEAM_SEGS):
            x, y, tile, _ = _entry(oam, O_BEAM + i)
            assert tile == T_BEAM, (i, tile)
            assert y == BEAM_Y0 + i * BEAM_PITCH, (i, y)
            assert x == bx & 0xFF, (i, x, bx)
        img = _pixels(m, tmp_path / "beam.png")
    w = img.width
    cols = {j % w for j, p in enumerate(img.getdata()) if p in BEAM_COLOURS}
    assert cols, "the beam tone never rendered"
    assert min(cols) >= bx - 1 and max(cols) <= bx + 8, \
        f"beam pixels outside the locked column {bx}: {sorted(cols)}"


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
            m.advance(3, pad1={"a": True, "left": True})
            _, y, n = _centroid(_pixels(m, tmp_path / f"b{i}.png"),
                                {BOLT_COLOUR})
            if n >= 6:
                ys.append(y)
        assert len(ys) >= 3, "no bolt ever rendered while A was held"
        assert min(ys) < ys[0], f"bolts never climbed: {ys}"
        for _ in range(40):
            m.advance(6, pad1={"a": True, "left": True})
            lit = sum(1 for s in range(8)
                      if _entry(_oam(m), O_HUD + s)[2] == T_PIP_LIT)
            if lit < 8:
                break
    assert lit < 8, "landed bolts never dimmed a rendered HUD pip"


def test_the_hud_pips_dim_exactly_at_the_hp_thresholds():
    """The eight HUD OAM entries (slots 17-24) show lit-vs-dim tiles matching
    count(hp > i * 30) at every sampled fight frame — the rendered HUD is a
    function of HP, read from the OAM bytes it is drawn through."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        checked = 0
        for _ in range(80):
            m.advance(9, pad1={"a": True, "left": True})
            if _rd16(m, ST) != FIGHT:
                break
            hp_before = _rd16(m, BHP)
            m.advance(1, pad1={"left": True})   # settle: OAM lags one advance
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
            m.advance(2, pad1={"a": True, "left": True})
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
    pad = {"a": True, "left": True}
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        for _ in range(600):
            m.advance(1, pad1=pad)
            if _rd16(m, BHP) == 0:
                break
        assert _rd16(m, BHP) == 0, "the kill never landed"
        climb = []
        for _ in range(80):
            m.advance(1, pad1=pad)
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
        assert (a, b) == tuple(death[0]) == (0x180, 0), (a, b)
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
    pad = {"a": True, "left": True}
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        _run_until(m, ST, DEATH, 3000, pad=pad, step=4)
        n_start = _count(_pixels(m, tmp_path / "d0.png"), FACE_COLOURS)
        oam = _oam(m)
        assert all(_entry(oam, O_HUD + s)[2] == T_PIP_DIM for s in range(8)), \
            "a dead saucer still shows lit pips"
        m.advance(28)
        n_mid = _count(_pixels(m, tmp_path / "d1.png"), FACE_COLOURS)
        m.advance(28)
        n_end = _count(_pixels(m, tmp_path / "d2.png"), FACE_COLOURS)
        assert n_start > n_mid > n_end > 0, (n_start, n_mid, n_end)
        assert n_end * 2 < n_start, "the recede barely shrank the saucer"
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
    or parked (no card during the fight), 54-55 parked for the ROM's life; the
    hi-table SIZE bit is set for exactly slot 0, and all fourteen hi bytes are
    owned."""
    with Machine(ROM) as m:
        _run_until(m, ST, FIGHT, 300)
        m.advance(40, pad1={"a": True})        # bolts live, a lunge under way
        oam = _oam(m)
    assert _entry(oam, 0)[2] in (0, 2), f"slot 0 tile {oam[2]} is not a ship frame"
    assert _entry(oam, 0)[1] != PARK_Y, "the gunship is parked mid-fight"
    for s in range(O_BEAM, O_BEAM + BEAM_SEGS):
        tile, y = _entry(oam, s)[2], _entry(oam, s)[1]
        assert tile == T_BEAM or y == PARK_Y, (s, tile, y)
    for s in range(O_HUD, O_HUD + 8):
        assert _entry(oam, s)[2] in (T_PIP_LIT, T_PIP_DIM), (s, _entry(oam, s))
    for s in range(O_SHOTS, O_SHOTS + 4):
        tile, y = _entry(oam, s)[2], _entry(oam, s)[1]
        assert tile == T_SHOT or y == PARK_Y, (s, tile, y)
    assert _entry(oam, O_EXH)[2] in (9, 10), "the thruster flame is not drawn"
    for s in range(O_CARDS, O_PAD + 2):
        assert _entry(oam, s)[1] == PARK_Y, f"slot {s} is drawn during the fight"
    hi = oam[512:512 + 14]
    for s in range(O_PAD + 2):
        field = (hi[s // 4] >> ((s % 4) * 2)) & 3
        if s == 0:
            assert field == 2, f"the gunship slot is missing the LARGE bit ({field})"
        else:
            assert field == 0, f"slot {s} hi field {field} (want 0)"


def test_the_palettes_land_where_the_claims_say():
    """CGRAM words 0..15 == sau_pal.bin and 128..143 == sau_sprite_pal.bin —
    the destination region byte-for-byte against the authored source (the
    asset-upload sub-rule: read the DESTINATION, not a downstream consumer)."""
    floor = Path("build/assets/sau_pal.bin").read_bytes()
    spr = Path("build/assets/sau_sprite_pal.bin").read_bytes()
    with Machine(ROM) as m:
        m.advance(6)
        cg = m.read_bytes(MemoryType.SnesCgRam, 0, 512)
    assert bytes(cg[0:32]) == floor, "floor palette not at CGRAM 0"
    assert bytes(cg[256:288]) == spr, "sprite palette not at OBJ palette 0"


def test_the_track_blobs_hold_their_format_and_their_seams():
    """Pure-source check of the shipped bytes: count headers, entry counts,
    the FOUR handovers the state machine performs, and the ring against the
    generator formula. (The emulator half of this contract is the three
    matrix oracles above.)"""
    want = {"sau_ring": 256, "sau_reveal": 61, "sau_appr": 46,
            "sau_retr": 46, "sau_death": 61}
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
    assert appr[0] == ring[0] == (0x180, 0), "the hold->fight seam drifted"
    assert retr[0] == appr[N], "the near->retreat seam drifted"
    assert retr[N] == appr[0], "the retreat->far seam drifted"
    assert death[0] == ring[0], "the fight->death seam drifted"
    assert ring == [tuple(e) for e in GT.build_ring()]
    assert reveal[0] == (0x500, 0), "the pre-reveal pose is not far+unrotated"
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
