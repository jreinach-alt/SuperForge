"""boss — the scale-ramping static-affine rail.

Every case drives the lockstep Machine (pure function of rom md5, power-on
seed, input script; every read from a parked exact frame) and asserts on
OUTPUT regions — screenshot pixels, OAM bytes, CGRAM words, the readable
matrix shadow — never a proxy variable. WRAM state reads appear only to
SEQUENCE the drive (find the frame a state begins); every claim a test's
name makes is asserted on a rendered surface.

The colour predicates are EXACT: the generators author every palette, Mesen
expands BGR555 as (v << 3) | (v >> 2) per channel, and `_rt` reproduces that
round-trip, so "a face pixel" means one of the eleven face tones and cannot
count the HUD, the cast or the backdrop by accident (the population rule — the
counted population is the feature's).
"""
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "vendor")
from machine import Machine, MemoryType  # noqa: E402

sys.path.insert(0, "tools")
import gen_boss_assets as GA  # noqa: E402  (the palette author — one source)
import gen_boss_tracks as GT  # noqa: E402  (the track math — one source)

ROM = "build/boss.sfc"
MAP = json.loads(Path("build/bs/symbol_map.json").read_text())


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
PIF = _sym("US_P_IFRAME")["start"]
RESULT = _sym("US_B_RESULT")["start"]
M7AFF = _sym("ES_M7AFF", scene=None)["start"]
FADE = _sym("ES_FADE_CTL", scene=None)["start"]   # +0 level 0..15, +1 dir
OAM_SLOT0 = 0                     # OAM is its own address space, slot*4

# the boss.inc state indices (constants, mirrored — a drift breaks sequencing,
# not an assertion, and the state reads themselves are sequencing only)
REVEAL, HOLD, FIGHT, DEATH, LOSE, RES_ST, RESET, DYING = 1, 2, 3, 4, 5, 6, 7, 8

T_ORB, T_SHOT, T_PIP_LIT, T_PIP_DIM = 4, 5, 6, 7
PARK_Y = 240


def _rt(rgb):
    """Author RGB -> the RGB Mesen renders (BGR555 truncate + expand)."""
    return tuple(((v >> 3) << 3) | (v >> 3 >> 2) for v in rgb)


FACE_COLOURS = {_rt(c) for c in (
    GA.OBSID_DK, GA.OBSID_MD, GA.OBSID_LT, GA.HORN_DK, GA.HORN_LT,
    GA.EMBER, GA.EMBER_DIM, GA.JAW_DK, GA.FANG, GA.SIGIL, GA.SIGIL_DIM)}
SHIP_COLOURS = {_rt(c) for c in (GA.SPRITE_COLOURS[1], GA.SPRITE_COLOURS[2],
                                 GA.SPRITE_COLOURS[3])}
BOLT_COLOUR = _rt(GA.SPRITE_COLOURS[7])
ORB_COLOURS = {_rt(GA.SPRITE_COLOURS[5]), _rt(GA.SPRITE_COLOURS[6])}


def _pixels(m, path):
    from PIL import Image
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _count(img, colours):
    n = 0
    for px in img.getdata():
        if px in colours:
            n += 1
    return n


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


def _shadow_ab(m):
    b = m.read_bytes(MemoryType.SnesWorkRam, M7AFF, 8)
    a = struct.unpack_from("<h", bytes(b), 0)[0]
    bb = struct.unpack_from("<h", bytes(b), 2)[0]
    c = struct.unpack_from("<h", bytes(b), 4)[0]
    d = struct.unpack_from("<h", bytes(b), 6)[0]
    return a, bb, c, d


def _run_until_state(m, want, max_frames, pad=None, step=2):
    """Advance in small steps until US_B_STATE is (in) `want`. Sequencing
    only — never an assertion surface."""
    wants = want if isinstance(want, tuple) else (want,)
    for _ in range(max_frames // step):
        m.advance(step, pad1=pad or {})
        if _rd16(m, ST) in wants:
            return
    raise AssertionError(f"state {want} not reached in {max_frames} frames "
                         f"(at {_rd16(m, ST)})")


@pytest.fixture(scope="module", autouse=True)
def _built():
    assert Path(ROM).exists(), "run `make boss` first"


# =============================================================================
# The reveal — the scale-ramp headline: the boss visibly grows in
# =============================================================================
def test_the_reveal_grows_the_boss_on_screen(tmp_path):
    """Screenshot pixels at three parked frames INSIDE the ramp: the face's
    rendered area STRICTLY grows, and the far pose is a fraction of the
    last-park pose. All three captures land in REVEAL at full brightness, so
    the chain measures the RAMP alone — not the fade-in and not HOLD, where
    the ring renders full size whatever the reveal did. Measured on the
    healthy build (per-frame ES_FADE_CTL + state/timer trace): the fade-in
    reads level 15 / dir idle from the T=15 park on, and the last in-REVEAL
    park is T=59 (timer 1; the T=60 park is already HOLD). Each screenshot
    costs one emulated frame (machine.py take_screenshot), so the advances
    below park at T=18, 38, 59; the two guards are sequencing, the pixels
    the assertion. This is the case the reversed-track and frozen-cursor
    plants must flip — measured planted: reversed INVERTS the chain
    (20859 > 9874 > 5556), frozen FLATTENS it (5154 all three parks)."""
    with Machine(ROM) as m:
        m.advance(18)                         # park T=18: early ramp,
                                              #   3 parks past fade-done
        fade = tuple(m.read_bytes(MemoryType.SnesWorkRam, FADE, 2))
        assert fade == (15, 0), \
            f"early park not at full brightness (fade level/dir {fade})"
        early = _count(_pixels(m, tmp_path / "e.png"), FACE_COLOURS)
        m.advance(19)                         # park T=38: mid ramp
        mid = _count(_pixels(m, tmp_path / "m.png"), FACE_COLOURS)
        m.advance(20)                         # park T=59: the LAST park
                                              #   still inside REVEAL
        st, timer = _rd16(m, ST), _rd16(m, TIMER)
        assert (st, timer) == (REVEAL, 1), \
            f"rest park drifted out of the ramp (state {st}, timer {timer})"
        rest = _count(_pixels(m, tmp_path / "r.png"), FACE_COLOURS)
    assert 0 < early < mid < rest, (early, mid, rest)
    assert early * 3 < rest, f"far pose {early} not far vs rest {rest}"


def test_the_reveal_matrix_matches_the_baked_track_every_frame():
    """Whole-state oracle (skill rule 6): across the whole ramp the readable
    shadow — the ONLY readable copy of what the floor renders with, M7A-D
    being write-only ports — equals the generator's math for that frame's
    entry, uniform-scale identity included (D == A, C == -B)."""
    reveal = GT.build_reveal()
    with Machine(ROM) as m:
        m.advance(4)
        mismatches = []
        for _ in range(70):
            m.advance(1)
            st, timer = _rd16(m, ST), _rd16(m, TIMER)
            if st != REVEAL:
                break
            # the tick applies idx = FRAMES+1-t then decrements t, so at
            # a park idx = FRAMES - timer; timer==FRAMES is the pre-tick
            # pose battle_init applied (entry 0)
            idx = GT.REVEAL_FRAMES - timer
            a, b, c, d = _shadow_ab(m)
            want = reveal[idx]
            if (a, b) != want or d != a or c != -b:
                mismatches.append((idx, (a, b, c, d), want))
        assert st == HOLD, "the ramp never completed"
        assert not mismatches, mismatches[:4]


# =============================================================================
# The fight — free rotation at the rest scale (the ring)
# =============================================================================
def test_the_fight_spins_the_face_at_full_size(tmp_path):
    """Two parked frames of the fight: the face's rendered area stays put
    (scale fixed) while the picture itself moves substantially (rotation).
    Either half alone passes on a bug: 'same area' passes on a frozen frame,
    'pixels moved' passes on a scale drift."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        img1 = _pixels(m, tmp_path / "a.png")
        m.advance(16)
        img2 = _pixels(m, tmp_path / "b.png")
    n1, n2 = _count(img1, FACE_COLOURS), _count(img2, FACE_COLOURS)
    assert n1 > 8000, f"face not dominating the fight frame ({n1})"
    assert abs(n1 - n2) < n1 * 0.15, (n1, n2)
    moved = sum(1 for p, q in zip(img1.getdata(), img2.getdata()) if p != q)
    assert moved > 4000, f"only {moved} pixels changed across 16 fight frames"


def test_the_fight_matrix_tracks_the_ring_oracle():
    """Each parked fight frame: shadow == ring[heading] by the generator's
    own math. The heading read sequences WHICH entry; the assertion surface
    is the matrix the floor renders with."""
    ring = GT.build_ring()
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        for _ in range(12):
            m.advance(3)
            h = _rd16(m, HEADING) & 0xFF
            a, b, c, d = _shadow_ab(m)
            assert (a, b) == ring[h], (h, (a, b), ring[h])
            assert d == a and c == -b


# =============================================================================
# Input -> the visible result, both directions and the idle
# =============================================================================
def test_the_ship_strafes_both_directions_on_screen(tmp_path):
    """Pad to pixels, end to end: LEFT moves the ship's rendered centroid
    left, RIGHT moves it right, no input holds it still. Catches a
    self-consistent-but-reversed mapping a WRAM assertion cannot."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        m.advance(1)
        x0, _, n0 = _centroid(_pixels(m, tmp_path / "0.png"), SHIP_COLOURS)
        assert n0 > 40, f"ship not on screen ({n0} px)"
        m.advance(12, pad1={"left": True})
        m.advance(1)
        x1, _, n1 = _centroid(_pixels(m, tmp_path / "1.png"), SHIP_COLOURS)
        assert n1 > 40
        assert x1 < x0 - 20, f"LEFT did not move the ship left ({x0}->{x1})"
        m.advance(12, pad1={"right": True})
        m.advance(12, pad1={"right": True})
        m.advance(1)
        x2, _, n2 = _centroid(_pixels(m, tmp_path / "2.png"), SHIP_COLOURS)
        assert x2 > x1 + 20, f"RIGHT did not move the ship right ({x1}->{x2})"
        m.advance(10)                          # idle: nothing held
        m.advance(1)
        x3, _, _ = _centroid(_pixels(m, tmp_path / "3.png"), SHIP_COLOURS)
        assert abs(x3 - x2) < 6, f"idle drifted the ship ({x2}->{x3})"


# =============================================================================
# The rain, the bolts, the HUD — combat's rendered surfaces
# =============================================================================
def test_the_rain_falls_toward_the_ship(tmp_path):
    """Orange orb pixels appear during the fight and their centroid DESCENDS
    across parked frames — the rain is real and moving the right way."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        ys = []
        for i in range(14):
            m.advance(6)
            img = _pixels(m, tmp_path / f"r{i}.png")
            w = img.width
            rows = [j // w for j, px in enumerate(img.getdata())
                    if px in ORB_COLOURS]
            if len(rows) >= 12:
                ys.append(max(rows))          # the leading edge
        assert len(ys) >= 3, "no orb ever rendered during the fight window"
        assert ys[-1] > ys[0] + 30, f"the rain did not descend: {ys}"


def test_a_hit_flashes_the_ship_and_costs_a_heart(tmp_path):
    """Stand still under the column: on contact p_hp drops (state) AND the
    rendered ship blinks — OAM slot 0's tile byte alternates to the flash
    frame on the blink phase, and a screenshot inside the window shows the
    flash-white tone. OAM + pixels are the output; p_hp sequences."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        hp0 = _rd16(m, PHP)
        for _ in range(120):
            m.advance(2)
            if _rd16(m, PHP) < hp0:
                break
        assert _rd16(m, PHP) == hp0 - 1, "the rain never connected"
        tiles = set()
        flash_seen = 0
        for i in range(10):
            m.advance(1)
            if _rd16(m, PIF) == 0:
                break
            tiles.add(m.read_bytes(MemoryType.SnesSpriteRam, 2, 1)[0])
            img = _pixels(m, tmp_path / f"flash{i}.png")
            if _count(img, {_rt(GA.SPRITE_COLOURS[12])}) > 20:
                flash_seen += 1
        assert 2 in tiles, f"flash tile never staged (tiles {tiles})"
        assert flash_seen >= 1, "the white flash frame never rendered"


def test_holding_a_fires_bolts_that_climb_the_screen(tmp_path):
    """Cyan bolt pixels appear above the ship and their centroid CLIMBS
    frame to frame; boss HP falls as they land. The bolt colour predicate
    rejects the ship's hull tones by construction."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        hp0 = _rd16(m, BHP)
        ys = []
        for i in range(10):
            m.advance(3, pad1={"a": True, "left": True})
            _, y, n = _centroid(_pixels(m, tmp_path / f"b{i}.png"),
                                {BOLT_COLOUR})
            if n >= 6:
                ys.append(y)
        assert len(ys) >= 3, "no bolt ever rendered while A was held"
        assert min(ys) < ys[0], f"bolts never climbed: {ys}"
        for _ in range(30):
            m.advance(6, pad1={"a": True, "left": True})
            if _rd16(m, BHP) < hp0:
                break
        assert _rd16(m, BHP) < hp0, "landed bolts never cost the boss HP"


def test_the_hud_pips_dim_exactly_at_the_hp_thresholds():
    """The eight HUD OAM entries (slots 9-16) show lit-vs-dim tiles matching
    ceil-count(hp / 30) at every sampled fight frame — the rendered HUD is a
    function of HP, read from the OAM bytes it is drawn through."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        checked = 0
        for _ in range(80):
            m.advance(9, pad1={"a": True, "left": True})
            if _rd16(m, ST) != FIGHT:
                break
            hp_before = _rd16(m, BHP)
            m.advance(1, pad1={"left": True})  # settle: OAM lags one advance
            hp = _rd16(m, BHP)
            if hp != hp_before:
                continue                       # a landing raced the sample
            oam = m.read_bytes(MemoryType.SnesSpriteRam, 9 * 4, 8 * 4)
            tiles = [oam[i * 4 + 2] for i in range(8)]
            want_lit = sum(1 for i in range(8) if hp > i * 30)
            lit = sum(1 for t in tiles if t == T_PIP_LIT)
            dim = sum(1 for t in tiles if t == T_PIP_DIM)
            assert lit + dim == 8, f"HUD slots hold foreign tiles: {tiles}"
            assert lit == want_lit, (hp, tiles)
            checked += 1
        assert checked > 20, "the fight ended before the HUD was exercised"


# =============================================================================
# The whole win cycle: fight -> DYING capture -> recede -> result -> loop
# =============================================================================
def test_the_win_cycle_recede_and_loop(tmp_path):
    """The full forward cycle on rendered surfaces: the kill dims every pip
    (OAM), the recede SHRINKS the face across parked frames (pixels), the
    win result holds BRIGHT, and the loop re-arms the reveal — the boss is
    small again with full HP. One drive, every beat asserted."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        pad = {"a": True, "left": True}
        _run_until_state(m, (DYING, DEATH), 3000, pad=pad, step=6)
        _run_until_state(m, DEATH, 100)       # the capture is bounded at 64
        n_start = _count(_pixels(m, tmp_path / "d0.png"), FACE_COLOURS)
        oam = m.read_bytes(MemoryType.SnesSpriteRam, 9 * 4, 8 * 4)
        assert all(oam[i * 4 + 2] == T_PIP_DIM for i in range(8)), \
            "a dead boss still shows lit pips"
        m.advance(30)
        n_mid = _count(_pixels(m, tmp_path / "d1.png"), FACE_COLOURS)
        m.advance(28)
        n_end = _count(_pixels(m, tmp_path / "d2.png"), FACE_COLOURS)
        assert n_start > n_mid > n_end > 0, (n_start, n_mid, n_end)
        assert n_end * 2 < n_start, "the recede barely shrank the face"
        _run_until_state(m, RES_ST, 40)
        assert _rd16(m, RESULT) == 1
        img = _pixels(m, tmp_path / "win.png")
        assert _count(img, FACE_COLOURS) > 0, "the win card faded to black"
        _run_until_state(m, RESET, 200)
        _run_until_state(m, REVEAL, 100)
        assert _rd16(m, BHP) == 240, "the loop did not re-arm the battle"
        m.advance(22)                         # the fade-in's 15 steps, done
        n_again = _count(_pixels(m, tmp_path / "loop.png"), FACE_COLOURS)
        assert 0 < n_again < n_start, \
            f"the re-revealed boss is not small again ({n_again} vs {n_start})"


def test_the_dying_capture_is_smaller_than_one_frames_spin(tmp_path):
    """The dying capture's whole point, held to account on both surfaces. Pass 1
    (no captures — Machine.screenshot itself costs one emulated frame,
    machine.py:600, so a capture inside a per-frame scan halves the sample
    rate): during DYING the heading walks +4 mod 256 EVERY frame; the final
    correction to the death track's start is < 4; the shadow at the first
    DEATH park is EXACTLY ring[0] == death[0]. Pass 2 replays the identical
    deterministic drive (same ROM, same seed, same per-frame pads — pads are
    inert after the kill, when player_move stops running) and photographs
    the two parks whose renders straddle the seam commit: the face's area
    may not jump more than the ramp's own per-frame change. (The area bound
    is SCALE-sensitive only — an angle snap at constant scale would not move
    it; angle continuity across the seam is pass 1's shadow asserts, with
    pixel-reachability supplied by the fight test's pixels-moved half.)"""
    ring = GT.build_ring()
    script = []

    def adv(m, n, pad=None):
        m.advance(n, pad1=pad or {})
        script.append((n, pad))

    pad = {"a": True, "left": True}
    with Machine(ROM) as m:
        for _ in range(100):
            adv(m, 2)
            if _rd16(m, ST) == FIGHT:
                break
        assert _rd16(m, ST) == FIGHT
        for _ in range(500):
            adv(m, 6, pad)
            if _rd16(m, BHP) <= 15:
                break
        assert _rd16(m, BHP) <= 15, "the kill never got close"
        seq = []
        for _ in range(400):
            adv(m, 1, pad)
            st = _rd16(m, ST)
            if st == DYING:
                seq.append(_rd16(m, HEADING))
            elif st == DEATH:
                break
        assert _rd16(m, ST) == DEATH, "the capture never handed over"
        assert len(seq) >= 1, "DYING was never observed at a park"
        for a, b in zip(seq, seq[1:]):
            assert (b - a) & 0xFF == 4, f"DYING spin not +4/frame: {seq}"
        # the capture tick STEPS +4 first and then snaps the remainder, so
        # the correction the ASM applies is measured from seq[-1] + 4
        assert (0 - (seq[-1] + 4)) & 0xFF < 4, \
            f"handover correction >= one frame's spin ({seq[-1]})"
        a, b, c, d = _shadow_ab(m)
        assert (a, b) == tuple(ring[0]) == (0x180, 0), (a, b)
        assert d == a and c == -b

    # ---- pass 2: the rendered seam, on the replayed drive ------------------
    with Machine(ROM) as m2:
        for n, padv in script:
            m2.advance(n, pad1=padv or {})
        assert _rd16(m2, ST) == DEATH, "the replay diverged from pass 1"
        n_last_dying = _count(_pixels(m2, tmp_path / "s0.png"), FACE_COLOURS)
        n_first_death = _count(_pixels(m2, tmp_path / "s1.png"), FACE_COLOURS)
    assert abs(n_first_death - n_last_dying) < max(600, n_last_dying * 0.08), \
        (n_last_dying, n_first_death)


# =============================================================================
# The lose path — deterministic without input, and rendered as a fade
# =============================================================================
def test_the_lose_path_fades_out_without_input(tmp_path):
    """No input: the centre-column rain wears the stationary ship down (the
    the deterministic LOSE path); LOSE arms the fade and the RESULT
    frame renders BLACK — the lose card IS the darkness, asserted on pixels;
    then the loop re-reveals."""
    with Machine(ROM) as m:
        _run_until_state(m, LOSE, 900, step=6)
        assert _rd16(m, PHP) == 0
        _run_until_state(m, RES_ST, 120)
        assert _rd16(m, RESULT) == 2
        m.advance(20)                          # fade (15 steps) fully out
        img = _pixels(m, tmp_path / "lose.png")
        assert _count(img, FACE_COLOURS) == 0, "the lose card is not dark"
        assert _count(img, SHIP_COLOURS) == 0
        _run_until_state(m, REVEAL, 250)
        m.advance(24)                         # the fade-in's 15 steps, done
        assert _count(_pixels(m, tmp_path / "again.png"), FACE_COLOURS) > 0, \
            "the loop never faded back into a reveal"


# =============================================================================
# The stable slot map and the palettes — the claims, on hardware
# =============================================================================
def test_oam_slot_identities_hold_mid_fight():
    """The reference's stable-slot contract on the OAM bytes: slot 0 is the
    ship (16x16 LARGE bit set, its X9 clear), 1-8 are orbs or parked, 9-16
    are pips, 17-20 are bolts or parked, 21-23 parked; the hi-table SIZE bit
    is set for exactly slot 0."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        m.advance(40, pad1={"a": True})       # some bolts + some rain live
        oam = m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)
    assert oam[2] in (0, 2), f"slot 0 tile {oam[2]} is not a ship frame"
    assert oam[1] != PARK_Y, "the ship is parked mid-fight"
    for s in range(1, 9):
        tile, y = oam[s * 4 + 2], oam[s * 4 + 1]
        assert tile == T_ORB or y == PARK_Y, (s, tile, y)
    for s in range(9, 17):
        assert oam[s * 4 + 2] in (T_PIP_LIT, T_PIP_DIM), (s, oam[s * 4 + 2])
    for s in range(17, 21):
        tile, y = oam[s * 4 + 2], oam[s * 4 + 1]
        assert tile == T_SHOT or y == PARK_Y, (s, tile, y)
    for s in range(21, 24):
        assert oam[s * 4 + 1] == PARK_Y, f"pad slot {s} not parked"
    hi = oam[512:512 + 6]
    for s in range(24):
        field = (hi[s // 4] >> ((s % 4) * 2)) & 3
        if s == 0:
            assert field == 2, f"ship slot missing the LARGE bit ({field})"
        else:
            assert field in (0,), f"slot {s} hi field {field} (want 0)"


def test_the_palettes_land_where_the_claims_say():
    """CGRAM words 0..15 == bs_pal.bin and 128..143 == bs_sprite_pal.bin —
    the destination region byte-for-byte against the authored source
    (sub-rule 3: upload paths read the DESTINATION)."""
    floor = Path("build/assets/bs_pal.bin").read_bytes()
    spr = Path("build/assets/bs_sprite_pal.bin").read_bytes()
    with Machine(ROM) as m:
        m.advance(6)
        cg = m.read_bytes(MemoryType.SnesCgRam, 0, 512)
    assert bytes(cg[0:32]) == floor, "floor palette not at CGRAM 0"
    assert bytes(cg[256:288]) == spr, "sprite palette not at OBJ palette 0"


# =============================================================================
# The blobs themselves — the generator's contract, regression-locked
# =============================================================================
def test_the_track_blobs_hold_their_format_and_their_seams():
    """Pure-source check of the shipped bytes: count headers, entry counts,
    the two seams, and the ring's identity against the generator formula.
    (The emulator half of this contract is the two oracle tests above.)"""
    for name, want_n in (("bs_ring", 256), ("bs_reveal", 61),
                         ("bs_death", 61)):
        blob = Path(f"build/assets/{name}.bin").read_bytes()
        n = struct.unpack_from("<H", blob, 0)[0]
        assert n == want_n and len(blob) == 2 + 4 * n, (name, n, len(blob))

    def entries(name):
        blob = Path(f"build/assets/{name}.bin").read_bytes()
        n = struct.unpack_from("<H", blob, 0)[0]
        return [struct.unpack_from("<hh", blob, 2 + 4 * i) for i in range(n)]

    ring, reveal, death = (entries(n) for n in
                           ("bs_ring", "bs_reveal", "bs_death"))
    assert reveal[60] == ring[60], "the reveal->hold seam drifted"
    assert death[0] == ring[0] == (0x180, 0), "the dying->death seam drifted"
    assert ring == [tuple(e) for e in GT.build_ring()]
    assert reveal[0] == (0x500, 0), "the pre-reveal pose is not far+unrotated"

def test_shot_slots_recycle_between_flights():
    """The pool lifecycle on the OAM bytes: across a window of held-A fight
    frames, every shot slot's y is either PARKED (exactly 240) or inside the
    flight corridor (spawn 176 down to the cull at 16, sampled mid-step), and
    at least one slot is OBSERVED going live -> parked (a recycle actually
    happened). A shot whose kill is dropped wraps the whole 16-bit y space
    and renders through the 177..239 band no healthy frame can show — the
    band IS the assertion, which is what makes this test able to see a
    leaked pool while the win cycle (which a leak merely accelerates —
    an unfreed shot re-deals its damage every frame it crosses the box)
    cannot."""
    with Machine(ROM) as m:
        _run_until_state(m, FIGHT, 200)
        was_live = [False] * 4
        recycled = False
        for _ in range(50):
            m.advance(2, pad1={"a": True, "left": True})
            oam = m.read_bytes(MemoryType.SnesSpriteRam, 17 * 4, 4 * 4)
            for s in range(4):
                y = oam[s * 4 + 1]
                live = y != PARK_Y
                assert (not live) or (10 <= y <= 176), \
                    f"shot slot {17 + s} at y={y}: outside the flight " \
                    f"corridor and not parked — a leaked or wrapped slot"
                if was_live[s] and not live:
                    recycled = True
                was_live[s] = live
        assert recycled, "no shot slot was ever seen returning to the pool"
