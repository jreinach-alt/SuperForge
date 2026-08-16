"""split_h_2p_demo — the SWARM, the two pads and the CADENCE.

`test_split_h_2p_demo` proves `m7_persp_project` against a world-FIXED cast.
This module makes the cast live — two entities whose world position IS a
camera's and 22 AI waypoint followers — puts both cameras on a pad, and
measures the frame. This
module asserts all of it against what the machine produced: hardware OAM, VRAM,
CGRAM, the framebuffer, and the two frame counters whose lockstep is the
cadence gate.

THE ONE CORRECTNESS QUESTION IS STILL THE INVERSE. The projection is R(-theta).
Feed the FORWARD pairing and the cast still moves, still stays on screen and
still looks like a plausible crowd — it simply stops standing on the world tile
the floor draws under it. So the headline test is not "there are sprites in
sensible places": it is that the texel the FLOOR samples under an entity's
anchor is that entity's own world position, measured through the pixel-exact
Mode 7 oracle in `test_split_h_2p_demo`, over a PAD-DRIVEN turn.

WHY EVERY MEASUREMENT HERE DRIVES THE PADS, and it is not for realism. The
shipping ROM is the SP_INPUT build: with nothing held the cameras stand
still at the seeded state, and at that state the checker world is FOUR-FOLD
AMBIGUOUS to `_recover` — headings 0 and 128 at (512, 512) reproduce the frame
equally well, and the recovery refuses rather than picking one. Driving is what
makes the state legible, and it is also the only way "pad 1 moves camera 1 and
not camera 2" can be a claim at all.

THE PHASE, MEASURED RATHER THAN ASSUMED — and it is one step deeper than the
camera's. At the park point of a frame the scene tick has already run, so WRAM
holds the state the NEXT VBlank will stamp and project while hardware OAM still
holds the previous one. The camera handles that with an invertible one-step
rewind of the DP drive; the AI is NOT invertible (waypoints, turning, the one-frame
pause), so instead the entity table is read FIRST, ONE released frame is
stepped, and only then are OAM and the picture read — which puts all three on
the same state. `test_hardware_oam_is_the_projection_slot_for_slot` is what
proves that ordering: it compares every OAM field against the mirror fed by
that table, and a one-frame phase error moves an entity a world pixel, which at
close range is several screen pixels of x.

AND HARDWARE OAM IS STILL READ BEFORE THE SHOT. `take_screenshot` advances the
emulated frame even on a parked core; 2b measured that reading OAM after it
instead puts every slot 2-3 px out.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tools"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from machine import Machine, MemoryType  # noqa: E402

# The sibling module, imported for its ORACLE — `_texel`/`_recover`/`_shot` and
# the pose set they stand on. Importing it is importing a surface that is
# itself under test in its own module (44 cases), not importing the thing under
# test here: everything below reads OAM, VRAM, CGRAM or pixels.
import test_split_h_2p_demo as D  # noqa: E402

# The asset generator, for the projection MIRROR and the tables. It refuses to
# emit anything that disagrees with the vendored blobs, so this is a gated
# rebuild rather than a copy of the ROM's arithmetic.
import gen_split_h_2p_assets as G  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_h_2p_demo.sfc"
FORWARD = BUILD / "sh2_sp_forward.sfc"
TIEROFF = BUILD / "sh2_sp_tieroff.sfc"
CULLOFF = BUILD / "sh2_sp_culloff.sfc"
ASSETS = BUILD / "assets"
# One expression, the shape conftest resolves a module's map from at COLLECTION
# time (it refuses a module whose map it cannot see).
_JMAP = json.loads((SUPERFORGE / "build" / "sh2" / "symbol_map.json").read_text())

W, V, C, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesCgRam, MemoryType.SnesSpriteRam)


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map")


V_OBJ = _sym("ES_V_OBJ_CHR", "split")["start"]          # word address
C_B1 = _sym("ES_C_BAND1_PAL", "split")["start"]         # CGRAM word index
C_B2 = _sym("ES_C_BAND2_PAL", "split")["start"]
OAM_AT = _sym("ES_O_SHO_CAST", "split")["start"]        # first claimed sprite
OAM_N = _sym("ES_O_SHO_CAST", "split")["size"]          # sprites claimed

# --- the swarm's own state, in WRAM -----------------------------------------
# The entity table and the control block are sh2_swarm's OUTPUT REGION, not a
# mirror of it: swm_ai writes these words and nothing else does, and sh2_obj
# reads them to draw. The count is also WRITTEN here by the cadence sweep,
# which is the whole reason it lives in WRAM rather than DP.
SWM_ENTS = _sym("ES_SWM_ENTS", "split")["start"]
SWM_CTL = _sym("ES_SWM_CTL", "split")["start"]
SM_FRAME = _sym("ES_SM_FRAME")["start"]                 # scene_mgr's VBlank count
SWM_ENT_BYTES = 8
SWM_MAX = _sym("ES_SWM_ENTS", "split")["size"] // SWM_ENT_BYTES
SWM_N_SHIP = 24                                         # the shipping SPRITES=24
SWM_PLAYERS = 2

# --- the geometry, from the features' own declarations ----------------------
SEAM, LINES = D.SEAM, D.LINES
BAND_TOP = (0, SEAM)
PARK_Y = 0xF0
# sh2_obj.asm's two marker colours, as 5-bit tuples. Asserted against CGRAM
# below, so this is the spec and CGRAM is the thing checked against it.
COL_B1, COL_B2 = 0x7FFF, 0x7C1F
# The projection's own bound, MEASURED over the complete camera cycle with the
# shipped marker blob: every visible marker's anchor samples a texel within
# FOUR world px of the marker (half a tile, which is the depth quantisation of
# the sp_vk row inverse). The FORWARD control's separation is a wandering
# quantity and its median is a SAMPLE median, not a constant: measured at 114
# here, at 106 in tools/build_split_h_2p_variants.sh's comment and at 80 by
# a later review over six samples. All three clear FORWARD_MIN by a wide margin,
# which is why the test asserts a FLOOR rather than a figure.
TEXEL_TOL = 4
FORWARD_MIN = 32
# Two-frame steps of the AI test's driven run. MEASURED, not picked: the
# waypoint-arrival share is 18 of 22 at 120 steps, 21 at 180 and all 22 at 220
#. 240 is the measured all-22 point with margin, ~4 s of runtime.
RUN_STEPS = 240

# --- the projection mirror, and the tables it reads -------------------------
_RAMP = G.scale_ramp()
_RLO, _RHI = G.recip_luts(_RAMP)
TABS = (G.sincos_lut(), G.vk_lut(_RAMP),
        [_RLO[k] | (_RHI[k] << 8) for k in range(G.LINES)], G.tier_ladder(_RAMP))
SEEDS = (ASSETS / "sh2_ents.bin").read_bytes()
WAY = [struct.unpack_from("<HH", (ASSETS / "sh2_way.bin").read_bytes(), i * 4)
       for i in range((ASSETS / "sh2_way.bin").stat().st_size // 4)]
# sh2_obj.asm's two ladder tables, which the OAM entry carries directly.
TIER_TILE = (0, 2, 4, 8, 12)
TIER_HALF = (8, 8, 8, 16, 16)


def _entities(runner, n=SWM_N_SHIP):
    """The live entity table, from WRAM — sh2_swarm's OUTPUT REGION.

    Returns [(x, y, heading, wp, fracx, fracy)]. These words are written by
    `swm_ai` and `swm_players` and read by `obj_band`; nothing mirrors them.
    """
    raw = runner.read_bytes(W, SWM_ENTS, n * SWM_ENT_BYTES)
    out = []
    for i in range(n):
        x, y, hwp, frc = struct.unpack_from("<HHHH", raw, i * SWM_ENT_BYTES)
        out.append((x, y, hwp & 0xFF, hwp >> 8, frc & 0xFF, frc >> 8))
    return out


def _ctl(runner):
    """(live count, the main loop's frame counter) — sh2_swarm's control block."""
    raw = runner.read_bytes(W, SWM_CTL, 4)
    return raw[0] | (raw[1] << 8), raw[2] | (raw[3] << 8)


def _vblanks(runner):
    """scene_mgr's own VBlank counter — incremented by EVERY NMI, armed or not,
    so it advances at the PPU's rate whatever the CPU is doing. That is exactly
    what makes it the other half of the cadence gate."""
    raw = runner.read_bytes(W, SM_FRAME, 2)
    return raw[0] | (raw[1] << 8)


def _set_n(runner, n):
    runner.write_bytes(W, SWM_CTL, bytes([n & 0xFF, n >> 8]))


def _step(runner, n=1, p1=None, p2=None):
    """Advance n frames with BOTH pads in a STATED state.

    Under the Machine substrate the stated-state discipline is structural:
    `advance` latches BOTH pads' full controller state on every call — a
    button not named is released, on both pads, always — so the leak the
    legacy version worked around ("pad 2 does nothing" passing while pad 2
    was still held from three calls ago) has no expression here.
    """
    runner.advance(n, pad1=p1, pad2=p2)


def _expect(ents, cam, heads, **flags):
    """The cast the projector should have produced, in OAM SLOT ORDER.

    Band 1's survivors first, then band 2's, each in entity order — which is
    exactly what slot compaction produces, so the ORDER is part of the claim
    rather than a convenience.
    """
    out = []
    for band in (0, 1):
        for i, e in enumerate(ents):
            pr = G.sp_project(TABS, e[0], e[1], cam[band][0], cam[band][1],
                              heads[band], BAND_TOP[band], **flags)
            if pr:
                out.append((band, i, pr[0], pr[1], pr[2]))
    return out


def _oam(runner):
    """Hardware OAM, as (x9, y, tile, attr, big) per sprite — the OUTPUT."""
    raw = runner.read_bytes(O, 0, 544)
    out = []
    for j in range(128):
        hi = (raw[512 + j // 4] >> ((j % 4) * 2)) & 3
        out.append((raw[j * 4] | ((hi & 1) << 8), raw[j * 4 + 1],
                    raw[j * 4 + 2], raw[j * 4 + 3], bool(hi & 2)))
    return out


def _sample(runner, tmp_path, tag, p1=None, p2=None, n=SWM_N_SHIP):
    """One driven frame, then the state and the picture that go with it.

    THE ORDER IS THE PHASE (see the module docstring):

      1. drive one frame with the stated pads;
      2. read the ENTITY TABLE — at this park it holds the state the next
         VBlank will project;
      3. step ONE RELEASED frame, so that state is committed and the cameras do
         not move again;
      4. read hardware OAM (before the shot, which advances a frame);
      5. read the CAMERAS from DP — `advanced=False`, because step 3 released
         the pads and cam_input therefore stepped nothing;
      6. take the picture and RECOVER both cameras from its FLOOR PIXELS,
         seeded from DP within +/-8 px.

    The returned camera state is the recovered one, not DP's: DP is the seed
    for the search window and nothing more, which is what keeps the projector's
    own bookkeeping off both sides of every comparison below.
    """
    _step(runner, 1, p1, p2)
    ents = _entities(runner, n)
    _step(runner, 1)
    oam = _oam(runner)
    seed, _heads = D._state(runner, advanced=False)
    px = D._shot(runner, tmp_path, tag)
    rec = [D._recover(px, b, list(seed)[b]) for b in (0, 1)]
    return (ents, oam, px, [rec[0][1], rec[1][1]], [rec[0][0], rec[1][0]])


# THE DRIVE every measurement in this module uses, both holding
# B. The senses are not arbitrary and they were MEASURED rather than picked.
#
# A camera driving forward while its heading steps one pose per frame walks a
# CIRCLE, and which circle depends on the SENSE — reverse the turn and the
# camera orbits a centre mirrored about its start. The swarm's seed rings and
# its waypoint loops are laid on the orbit centres of the AUTONOMOUS senses
# (h1 +1, h2 -1), so driving with those senses retraces the arc the world was
# built around and driving against them wanders off it. Measured: with the pads
# reversed, band 2 saw FOUR distinct entities across 180 samples; with them
# matched it sees a real cast. A gallery clip that holds plain `left` and
# `right` is answering for a different world, not this one.
P1_TURN = {"right": True, "b": True}
P2_TURN = {"left": True, "b": True}


def _sample_oam(runner, p1=None, p2=None, n=SWM_N_SHIP):
    """The same phase as `_sample`, without the picture.

    Same ordering — drive, read the entity table, step ONE released frame, read
    hardware OAM — but the cameras come from DP rather than from a pixel
    recovery, which makes a sample cheap enough to run a hundred of.

    THAT IS NOT A SOFTENING. DP holds the game's DECISION (where it put the
    cameras); hardware OAM is the MECHANISM'S OUTPUT. Comparing one against the
    other is exactly the split `render_matches_the_hardware_oracle` is built
    on, and its header records why: feeding the projector's own answers back in
    would put the thing under test on both sides. The pixel recovery exists for
    the claims where the FLOOR is the subject — the texel placement — and it is
    used there.
    """
    _step(runner, 1, p1, p2)
    ents = _entities(runner, n)
    _step(runner, 1)
    oam = _oam(runner)
    cam, heads = D._state(runner, advanced=False)
    return ents, oam, [list(c) for c in cam], heads


def _unstick(runner, tmp_path):
    """Drive both cameras off the seeded state, which is AMBIGUOUS.

    At (512, 512) heading 0 the checker world reproduces the frame at headings
    0 and 128 alike, and `_recover` refuses an ambiguous frame rather than
    picking one — correctly, since a recovery that cannot discriminate cannot
    measure anything. The degeneracy is the world's four-fold symmetry meeting
    a camera parked on its axis at a cardinal heading, so the cure is to get
    off both: TWENTY frames of the measurement's own drive puts camera 1 at
    heading ~20 and camera 2 at ~108, forty world pixels off the axis.
    A PRECONDITION of the measurements below, not part of any claim, so it is
    asserted here once: after it, both bands must recover uniquely.
    """
    _step(runner, 20, P1_TURN, P2_TURN)
    _step(runner, 1)
    seed, _h = D._state(runner, advanced=False)
    px = D._shot(runner, tmp_path, "unstick")
    for b in (0, 1):
        D._recover(px, b, list(seed)[b])            # raises if not unique


def _wrapd(a, b):
    return min((a - b) & (D.WORLD_PX - 1), (b - a) & (D.WORLD_PX - 1))


def _used(oam):
    """The compacted run: slots from the claim's base until the first park."""
    n = 0
    while n < OAM_N and oam[OAM_AT + n][1] != PARK_Y:
        n += 1
    return n


@pytest.fixture(scope="module")
def runner():
    """The module's hand-back contract, not a shared driving handle: each
    boot below builds a fresh Machine (the core is still a process-global
    singleton — a new Machine supersedes the old handle), and this fixture's
    teardown resumes the core at module end, which is the module-boundary
    contract conftest enforces. Yields the ROM booter so the control-build
    tests can boot their variant with the same shape the fixtures use."""
    def boot(rom_path, frames):
        return Machine(str(rom_path)).advance(frames)
    yield boot
    Machine.close_current()


@pytest.fixture
def fresh(runner):
    return runner(ROM, 90)


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================
def test_the_obj_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claim's base against sh2_sp_chr.bin.

    The DESTINATION region, read directly. A test that only asserted "the
    markers render" would pass with half the block uploaded — the tokens are
    colour index 1 in plane 0 and a missing plane would look identical.
    """
    want = (ASSETS / "sh2_sp_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_the_obj_palettes_are_the_two_band_signatures(fresh):
    """CGRAM 128..159: entry 1 of each palette, and every other word ZERO.

    The whole claim is asserted, not just the drawn entry. sh2_obj writes all
    thirty-two words because CGRAM powers on random and a claimed word nobody
    writes is a region whose contents nobody chose (rule 5) — so "the rest are
    zero" is the contract, and reading only entry 1 would let it rot.

    The two colours are also what makes the seam tests below readable as
    pixels: which camera drew a sprite is in its palette.
    """
    raw = bytes(fresh.read_bytes(C, C_B1 * 2, 32 * 2))
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    assert words[1] == COL_B1, f"band 1's marker colour is ${words[1]:04X}"
    assert words[C_B2 - C_B1 + 1] == COL_B2, "band 2's marker colour is wrong"
    zeros = [i for i, w in enumerate(words)
             if i not in (1, C_B2 - C_B1 + 1) and w != 0]
    assert not zeros, (
        f"CGRAM words {zeros} of the two OBJ palette claims are non-zero — "
        f"obj_arm did not write the whole claim")


# =============================================================================
# 2. THE HEADLINE — a marker stands on its own world texel
# =============================================================================


def _assert_oam_is(oam, exp, where):
    """Hardware OAM, field for field, against the mirror — in SLOT ORDER.

    Extracted so `_texel_errors` can run it on EVERY sample. The
    texel test feeds the floor oracle the MIRROR's screen anchors, and until
    this ran per sample those anchors were tied to hardware OAM on exactly one
    driven frame elsewhere in the module — so "the marker STANDS ON it" was
    proven positionally once and asserted six times. This makes the two the same
    numbers on the frame under measurement, which is what the name claims.

    x (nine bits, X9 out of the hi table), y, CHR name, the SIZE bit and the OBJ
    palette that carries the band — not just position.
    """
    n = _used(oam)
    assert n == len(exp), (
        f"{where}: hardware OAM holds {n} sprites, the projection mirror says "
        f"{len(exp)}")
    for slot, (band, mi, sx, sy, tier) in enumerate(exp):
        half = TIER_HALF[tier]
        got = oam[OAM_AT + slot]
        want = ((sx - half) & 0x1FF, (sy - half) & 0xFF, TIER_TILE[tier],
                half == 16)
        assert (got[0], got[1], got[2], got[4]) == want, (
            f"{where}: slot {slot} (band {band}, entity {mi}) is "
            f"x={got[0]} y={got[1]} tile={got[2]} big={got[4]}, expected "
            f"x={want[0]} y={want[1]} tile={want[2]} big={want[3]}")
        # the palette IS the band signature (attr bits 3:1)
        assert (got[3] >> 1) & 7 == band, (
            f"{where}: slot {slot} came from band {band} but carries OBJ "
            f"palette {(got[3] >> 1) & 7}")


def _texel_errors(runner, tmp_path, tag, samples=4, forward=False):
    """Per drawn entity, how far the FLOOR's texel under its anchor is from that
    entity's own world position. Returns (max, median, n, entities seen).

    The anchors fed to the oracle are the mirror's, and `_assert_oam_is` ties
    them to HARDWARE OAM on every one of these samples — see its header.
    """
    errs, seen = [], set()
    _unstick(runner, tmp_path)
    for i in range(samples):
        ents, oam, _px, cam, heads = _sample(runner, tmp_path, f"{tag}{i}",
                                             P1_TURN, P2_TURN)
        exp = _expect(ents, cam, heads, forward=forward)
        assert exp, f"{tag}{i}: nothing is visible — nothing to measure"
        if not forward:
            # ...not on the FORWARD control: its whole point is that the
            # projector and this mirror agree with each other while both
            # stand on the wrong texel, so the slot-for-slot comparison is
            # not the claim there — the texel distance below is.
            _assert_oam_is(oam, exp, f"{tag}{i}")
        assert _used(oam) == len(exp), (
            f"{tag}{i}: hardware OAM holds {_used(oam)} sprites, the "
            f"projection mirror says {len(exp)}")
        for band, mi, sx, sy, _tier in exp:
            top, bot = D.BANDS[band]
            tx, ty = D._texel(sx, sy, top, bot, cam[band][0], cam[band][1],
                              heads[band])
            wx, wy = ents[mi][0], ents[mi][1]
            errs.append(max(_wrapd(tx, wx), _wrapd(ty, wy)))
            seen.add(mi)
    errs.sort()
    return max(errs), errs[len(errs) // 2], len(errs), seen


def test_every_marker_stands_on_the_world_texel_it_is_drawn_over(fresh,
                                                                 tmp_path):
    """THE PROJECTION IS THE INVERSE — asserted against the FLOOR, not itself.

    For each entity the projector placed, the sibling module's pixel-exact
    Mode 7 oracle is asked which world texel the PPU samples at that anchor. That
    texel must be the entity's own world position. The oracle reproduces this
    rail's frames at 57,344 of 57,344 pixels and shares no arithmetic with the
    projector, so this closes the loop through two independent derivations of
    the same geometry.

    THE CAMERA STATE COMES OUT OF THE PIXELS (`_recover`, 256 candidate poses
    against a 448-point grid, exactly one fit) and THE ENTITY POSITIONS COME
    OUT OF THE TABLE THE AI WROTE. Feeding the projector's own answers back
    into the oracle would put the thing under test on both sides — the trap
    that was measured when a sabotaged M7X made a table-fed oracle agree with
    the sabotage.

    DRIVEN, over a turn on both pads, so this is a state cycle rather than a
    lucky pose — and with the swarm moving, so an entity's position is a
    different world point at every sample.

    "IT IS DRAWN OVER" IS HARDWARE OAM'S, on every sample. The
    anchors handed to the oracle are the mirror's `sx/sy`, and `_texel_errors`
    now runs `_assert_oam_is` on each of the six samples, so the mirror's
    anchors ARE the bytes the PPU read on the frame being measured. Before this
    they were tied to hardware field-for-field on one driven sample elsewhere in
    the module, which made the name true once and asserted six times.
    """
    worst, med, n, _seen = _texel_errors(fresh, tmp_path, "tex", samples=6)
    assert n >= 24, f"only {n} placements measured across the run"
    assert worst <= TEXEL_TOL, (
        f"an entity's anchor samples a texel {worst} world px from the entity "
        f"(median {med} over {n}); the sp_vk row inverse quantises to at most "
        f"{TEXEL_TOL} px, so this is the projection being wrong, not rounding")


def test_the_live_count_is_twenty_four_and_the_whole_table_is_projected(fresh):
    """The count the rail SHIPS, and the fact that the draw honours it.

    Four claims, each about a different way this could be quietly smaller than
    it says:

    1. `SWM_N` reads 24 out of WRAM. That is the number the measurement's
       headroom rule is about, so it is asserted rather than assumed.
    2. On every one of 140 driven samples, hardware OAM equals the mirror run
       over ALL TWENTY-FOUR records. A projector that dropped the tail of the
       loop — an off-by-one on the count, a stale SWM_N, a band pass that ran
       the players only — disagrees on the first sample it happens.
    3. Entities from the END of the table are drawn, not just a prefix, and a
       real share of the whole cast is drawn at some point.
    4. Poking the count DOWN to 8 makes the draw follow: OAM then equals the
       mirror over the first eight records and no further. That is what proves
       the count is LIVE — read every frame — rather than a constant the loop
       agreed with by coincidence.

    THE TWO PLAYERS SELF-CULL IN THEIR OWN BAND, and that is a design claim
    rather than an observation. `swm_players` copies each camera's position
    into its own entity every frame, so in that camera's OWN band the point is
    exactly the camera: camera-frame v is 0, at the pivot row, and
    `mpp_project`'s `v >= 0` cull drops it before any multiply. That is WHY
    there is no per-band special case anywhere in sh2_obj, and asserting the
    marker never appears in its own band is what makes "no special case"
    evidence instead of a design note.
    """
    n_live, _beat = _ctl(fresh)
    assert n_live == SWM_N_SHIP, (
        f"the live entity count is {n_live}, not the {SWM_N_SHIP} the rail "
        f"ships and the measurement's headroom rule is about")
    seen = {0: set(), 1: set()}
    # BOTH TURN SENSES, on both pads. A run that only ever held one
    # direction sweeps one arc of each camera's orbit and would make the
    # coverage below a statement about that arc.
    for leg, (p1, p2) in enumerate((("right", "left"), ("left", "right"))):
        for i in range(90):
            ents, oam, cam, heads = _sample_oam(
                fresh, {p1: True, "b": True}, {p2: True, "b": True})
            exp = _expect(ents, cam, heads)
            assert _used(oam) == len(exp), (
                f"leg {leg} sample {i}: hardware OAM holds {_used(oam)}, "
                f"the mirror over all {SWM_N_SHIP} records says "
                f"{len(exp)}")
            for band, mi, _sx, _sy, _tier in exp:
                seen[band].add(mi)
    # ...and the same, with the count poked down: the draw must follow it.
    _set_n(fresh, 8)
    for i in range(6):
        ents, oam, cam, heads = _sample_oam(fresh, P1_TURN, P2_TURN, n=8)
        exp = _expect(ents, cam, heads)
        assert _used(oam) == len(exp), (
            f"poked sample {i}: the count is 8 but hardware OAM holds "
            f"{_used(oam)} against the mirror's {len(exp)} over the first "
            f"eight records — the loop is not reading SWM_N")
    _set_n(fresh, SWM_N_SHIP)

    drawn = seen[0] | seen[1]
    assert len(drawn) >= 16, (
        f"only {len(drawn)} of the {SWM_N_SHIP} entities were ever drawn "
        f"across the run ({sorted(drawn)}) — too few for the per-entity claims "
        f"in this module to be about a swarm")
    tail = {i for i in drawn if i >= SWM_N_SHIP - 6}
    assert len(tail) >= 3, (
        f"only {sorted(tail)} of the last six records were ever drawn — a loop "
        f"that stopped short would look like this")
    assert 0 not in seen[0], (
        "player 1's own marker was drawn in BAND 1 — it sits exactly at that "
        "camera, so v = 0 and the projector's v >= 0 cull must drop it; if it "
        "draws, the cull is not what places it")
    assert 1 not in seen[1], "player 2's own marker was drawn in BAND 2"
    for band in (0, 1):
        assert len(seen[band]) >= SWM_N_SHIP // 3, (
            f"band {band} only ever drew {len(seen[band])} distinct entities "
            f"of {SWM_N_SHIP} — too few for the per-band claims in this "
            f"module to be measuring two casts")


def test_the_forward_control_slides_the_cast_off_its_texels(runner, tmp_path):
    """THE CONTROL. `SH2_SP_FORWARD` negates sin -> R(theta), the FORWARD floor
    matrix, which is the mistake that survives a casual look.

    Both halves are asserted, because either alone would be worthless: the
    control must still DRAW a cast (a build where nothing renders would pass a
    "the markers are wrong" test trivially), and its markers must be far from
    the texels they stand on. Measured over the same driven walk.
    """
    runner = runner(FORWARD, 90)
    worst, med, n, _seen = _texel_errors(runner, tmp_path, "fwd", samples=4,
                                         forward=True)
    assert n >= 16, f"the FORWARD control drew only {n} markers — vacuous"
    assert med >= FORWARD_MIN, (
        f"the FORWARD control's markers are a median of {med} world px from "
        f"their texels (worst {worst}) — that is not far enough from the "
        f"shipping build's {TEXEL_TOL} px for the placement test to be "
        f"measuring the inverse rather than 'a plausible crowd'")


# =============================================================================
# 3. OAM — the slot-for-slot output, the compaction, and the watermark
# =============================================================================
def test_hardware_oam_is_the_projection_slot_for_slot(fresh, tmp_path):
    """Every field of every used entry, against the mirror.

    x (nine bits, X9 out of the hi table), y, CHR name and the SIZE bit — not
    just position. A ladder that placed markers correctly and gave them all one
    box would pass a position-only test and look wrong on screen. The comparison
    itself is `_assert_oam_is`, shared with `_texel_errors` since a later review so
    that the texel claim runs it per sample; this test is the one that NAMES it,
    and the one that proves the PHASE below.

    THE X9 BIT IS PART OF THE CLAIM, not a detail: an entity straddling the
    left edge of a view has a negative screen x every frame on this rail, and a
    stale or missing X9 puts it 256 px away on the right.

    THIS IS ALSO THE TEST THAT PROVES THE PHASE. The mirror is fed the entity
    table read one frame before OAM (see `_sample`); if that ordering were
    wrong the entities would be a frame of AI motion out — one world pixel,
    which near the bottom of a band is several screen pixels of x, and every
    comparison below would fail.
    """
    _unstick(fresh, tmp_path)
    ents, oam, _px, cam, heads = _sample(fresh, tmp_path, "oam",
                                         P1_TURN, P2_TURN)
    exp = _expect(ents, cam, heads)
    assert exp, "nothing is visible on this frame"
    _assert_oam_is(oam, exp, f"cam {cam} headings {heads}")


def test_the_visible_slots_are_compacted_and_the_tail_is_parked(fresh,
                                                                tmp_path):
    """Consecutive slots, a parked tail, AND a frame where the count FALLS.

    The shrink path is the half an only-ever-growing cast ships broken: a
    watermark that never has to walk backwards is a watermark nobody tested.
    The swarm is gated on the visible count rising and falling in BOTH regimes
    — driven and with the cameras static — by `swarm_world` in the generator,
    so a run of stepped frames is guaranteed to contain a drop, and this fails
    if it does not rather than passing quietly on a run that happened to grow.

    The tail is asserted PARKED to the end of the claim, so a shrink that left
    a ghost behind is caught where it happens rather than as a stray sprite in
    a screenshot somebody looks at later.
    """
    counts = []
    _unstick(fresh, tmp_path)
    for i in range(12):
        ents, oam, _px, cam, heads = _sample(fresh, tmp_path, f"cmp{i}",
                                             P1_TURN, P2_TURN)
        n = _used(oam)
        counts.append(n)
        assert n == len(_expect(ents, cam, heads))
        for slot in range(n, OAM_N):
            assert oam[OAM_AT + slot][1] == PARK_Y, (
                f"sample {i}: slot {slot} is past the compacted run of "
                f"{n} but is not parked (y={oam[OAM_AT + slot][1]}) — a "
                f"ghost from an earlier frame")
    assert any(b < a for a, b in zip(counts, counts[1:])), (
        f"the visible count never fell across {counts} — the watermark's "
        f"SHRINK path was not exercised, so this proves only the easy half")
    assert any(b > a for a, b in zip(counts, counts[1:])), (
        f"the visible count never rose across {counts}")


def test_the_two_bands_project_independently(fresh, tmp_path):
    """Two cameras, two casts — over a driven turn, not one frame.

    Both bands' entries come from the same 24 world points, so "the two bands
    show different sprites" is a claim about the two CAMERAS. The bands are
    told apart by their OBJ palette, which is what the slot-order assertion
    above and the seam assertion below both stand on.
    """
    seen = []
    _unstick(fresh, tmp_path)
    for i in range(4):
        _ents, oam, _px, _cam, _heads = _sample(fresh, tmp_path, f"ind{i}",
                                                P1_TURN, P2_TURN)
        n = _used(oam)
        b1 = [e[:2] for e in oam[OAM_AT:OAM_AT + n] if (e[3] >> 1) & 7 == 0]
        b2 = [e[:2] for e in oam[OAM_AT:OAM_AT + n] if (e[3] >> 1) & 7 == 1]
        assert b1, f"sample {i}: band 1 drew nothing"
        assert b2, f"sample {i}: band 2 drew nothing"
        assert b1 != b2, (
            f"sample {i}: the two bands produced identical entries {b1} — "
            f"one camera cannot be two")
        seen.append((tuple(b1), tuple(b2)))
    assert len({s[0] for s in seen}) > 1, "band 1's cast never changed"
    assert len({s[1] for s in seen}) > 1, "band 2's cast never changed"


# =============================================================================
# 4. THE SIZE LADDER — apparent size tracks depth
# =============================================================================
def _tiers_seen(runner, samples=8):
    """(band-local row, CHR name, big) for every marker drawn across a run.

    HARDWARE OAM ONLY — no recovery and no screenshot. The claim here is a
    relation WITHIN each entry (its row against its name and box), so the
    camera state is not an input to it and pulling one in would add a
    dependency the assertion does not need.
    """
    out = []
    for _i in range(samples):
        oam = _oam(runner)
        for slot in range(_used(oam)):
            _x9, y, tile, attr, big = oam[OAM_AT + slot]
            band = (attr >> 1) & 7
            half = 16 if big else 8
            out.append((((y + half) & 0xFF) - BAND_TOP[band], tile, big))
        # DRIVEN, because the shipping build's cameras only move when a pad
        # says so: a run of released frames would sample one camera state
        # over and over and the ladder would barely be under test.
        _step(runner, 2, P1_TURN, P2_TURN)
    return out


def test_the_size_ladder_tracks_depth(fresh):
    """A marker's CHR name and box size are the ladder's function of its ROW.

    Read out of hardware OAM: the entry's y (plus its half box) gives the
    band-local row the projector chose, and the ladder table says which name
    and which size that row must carry. Asserted for every drawn marker across
    an eight-frame run, and the run must reach at least four of the five rungs
    — a ladder only one step of which is ever used is not a ladder.
    """
    seen = _tiers_seen(fresh, samples=16)
    assert seen, "no markers drawn across the run"
    names = set()
    for row, tile, big in seen:
        k = max(0, min(G.LINES - 1, row))
        tier = TABS[3][k]
        assert tile == TIER_TILE[tier], (
            f"a marker at band-local row {row} carries CHR name {tile}; the "
            f"ladder says tier {tier} -> name {TIER_TILE[tier]}")
        assert big == (TIER_HALF[tier] == 16), (
            f"a marker at band-local row {row} has big={big}, tier {tier}")
        names.add(tile)
    assert len(names) >= 4, (
        f"the run only ever drew CHR names {sorted(names)} — fewer than four "
        f"of the ladder's five rungs, so 'far markers are smaller' is barely "
        f"under test")


def test_the_tieroff_control_flattens_the_ladder(runner):
    """THE CONTROL. `SH2_SP_TIEROFF` pins every marker to the middle tier.

    One CHR name, one box size, at every depth — which is what makes the
    ladder test above a measurement rather than a description of a table.
    """
    runner = runner(TIEROFF, 90)
    seen = _tiers_seen(runner, samples=8)
    assert seen, "the TIEROFF control drew nothing — vacuous"
    names = {tile for _row, tile, _big in seen}
    assert names == {TIER_TILE[2]}, (
        f"the TIEROFF control still varies the CHR name ({sorted(names)}) — "
        f"it is not flattening the ladder")
    assert not any(big for _row, _tile, big in seen), (
        "the TIEROFF control still emits 32x32 boxes")


# =============================================================================
# 5. THE SEAM — one camera's cast must not draw inside the other's view
# =============================================================================
def _seam_bleed(px):
    """Marker pixels on the WRONG side of the seam, per band colour."""
    b1 = D._rgb5(COL_B1)
    b2 = D._rgb5(COL_B2)
    below = sum(1 for sy in range(SEAM, LINES) for sx in range(256)
                if tuple(v >> 3 for v in px[sx, sy]) == b1)
    above = sum(1 for sy in range(SEAM) for sx in range(256)
                if tuple(v >> 3 for v in px[sx, sy]) == b2)
    return below, above


def test_no_bands_markers_draw_inside_the_other_bands_view(fresh, tmp_path):
    """PIXELS, not rows. No white below the seam, no magenta above it.

    The two bands are two CAMERAS over one world, so a band-1 marker drawn at
    screen row 120 is not a clipping artefact — it is one camera's sprite
    standing inside another camera's picture. The per-band seam guard in
    `mpp_project` is what stops it, and the two palettes are what make the
    failure legible in the framebuffer rather than only in slot bookkeeping.

    Eight stepped frames, because a marker only enters the guard's dead zone
    for part of the turn — the marker world is gated on that happening in at
    least an eighth of the 256 states, so a run of this length meets it.
    """
    total = 0
    _unstick(fresh, tmp_path)
    for i in range(8):
        _ents, oam, px, _cam, _heads = _sample(fresh, tmp_path, f"seam{i}",
                                               P1_TURN, P2_TURN)
        total += _used(oam)
        below, above = _seam_bleed(px)
        assert below == 0 and above == 0, (
            f"sample {i}: {below} band-1 (white) pixels below the seam and "
            f"{above} band-2 (magenta) pixels above it")
    assert total >= 20, (
        f"only {total} markers were drawn across the run — too few for 'no "
        f"marker crossed the seam' to mean anything")


def test_the_culloff_control_bleeds_markers_across_the_seam(runner, tmp_path):
    """THE CONTROL. `SH2_SP_CULLOFF` removes both per-band seam guards.

    The dead zones are narrow — a marker is inside one for part of a turn, not
    all of it — so this walks a run and requires the bleed to appear at least
    once. Without this build, "no marker crossed the seam" would also be true
    of a rail that never placed a marker near it.
    """
    runner = runner(CULLOFF, 90)
    bled = 0
    for i in range(24):
        px = D._shot(runner, tmp_path, f"bleed{i}")
        below, above = _seam_bleed(px)
        bled += below + above
        _step(runner, 2, P1_TURN, P2_TURN)
    assert bled > 0, (
        "the CULLOFF control never drew a marker across the seam in 24 frames "
        "— the seam assertion above is not measuring the guards")


# =============================================================================
# 6. THE SWARM — the AI moves, turns, and reaches its waypoints
# =============================================================================
def test_the_followers_move_and_turn_and_reach_their_waypoints(fresh):
    """PER FOLLOWER, over a run: it travelled, it CHANGED DIRECTION, and the
    waypoint index advanced for a real share of the cast.

    THE OUTPUT REGION IS THE ENTITY TABLE, which is what `swm_ai` produces and
    what `obj_band` reads to draw — not a proxy for it. The table is tied to
    the picture elsewhere in this module: `_expect` runs the mirror over these
    exact records on every sample and hardware OAM is asserted equal to it, and
    the texel test then puts each drawn entity on the world tile the FLOOR
    draws under it. So "the table moved" is the AI's own output and "the screen
    followed" is already proven beside it.

    TURNING IS ASSERTED SEPARATELY FROM MOVING, and that is the point. A cast
    that drifts one way ships the steer broken: every follower would travel,
    every position would change, and the cross product could be returning a
    constant. So the heading byte must take at least two values AND the
    per-frame displacement DIRECTION must change — the second because a heading
    word that moved while the move step ignored it would satisfy the first.

    THE WAYPOINT ADVANCE is the third: EVERY follower's `wp` field must move on
    within the run, or the Chebyshev arrival test never fires and the loop is
    one target forever.

    ALL 22, not "a real share". This asserted `>= 4 of 22` under a
    name that reads as all of them, which is the narrow-assertion-under-a-broad-
    name shape CLAUDE.md rule 2 is about: a test name is a contract. The run was
    the reason (120 iterations reached 18), so the run is the fix — MEASURED at
    120 -> 18, 180 -> 21, 220 -> 22, and it is driven for 240, which costs about
    four seconds. The asset generator's own simulation proves 22 of 22 over four
    laps at build time; this is that property on hardware.
    """
    first = _entities(fresh)
    heads = [{e[2]} for e in first]
    dirs = [set() for _ in first]
    wps = [{e[3]} for e in first]
    prev = first
    for _i in range(RUN_STEPS):
        _step(fresh, 2, P1_TURN, P2_TURN)
        now = _entities(fresh)
        for k, (a, b) in enumerate(zip(prev, now)):
            heads[k].add(b[2])
            wps[k].add(b[3])
            dx = ((b[0] - a[0] + D.WORLD_PX // 2) & (D.WORLD_PX - 1)) \
                - D.WORLD_PX // 2
            dy = ((b[1] - a[1] + D.WORLD_PX // 2) & (D.WORLD_PX - 1)) \
                - D.WORLD_PX // 2
            if dx or dy:
                dirs[k].add(((dx > 0) - (dx < 0), (dy > 0) - (dy < 0)))
        prev = now
    # THE PLAYERS ARE NOT STEERED, THEY ARE COPIED, and this is the other
    # half of swm_players: entities 0 and 1 must BE the two cameras.
    #
    # READ RIGHT AFTER THE DRIVE, deliberately. On the legacy substrate
    # this had to sit inside the frame_stepping block — read after it and
    # `debug_resume` had already let the core FREE-RUN while Python ran the
    # per-follower assertions, so DP was some unrelated later frame's, 2 px
    # off, load-sensitive by construction; it cost a full-suite red to
    # find, having passed every single-module run. Under lockstep the core
    # CANNOT free-run between statements, so the hazard is inexpressible —
    # the placement is kept because it is where the claim reads naturally.
    cam, _h = D._state(fresh, advanced=False)
    for b in (0, 1):
        assert (prev[b][0], prev[b][1]) == tuple(cam[b]), (
            f"entity {b} is at ({prev[b][0]}, {prev[b][1]}) but camera "
            f"{b + 1} is at {tuple(cam[b])} — swm_players is not mirroring "
            f"it")

    for k in range(SWM_PLAYERS, SWM_N_SHIP):
        a, b = first[k], prev[k]
        moved = max(_wrapd(a[0], b[0]), _wrapd(a[1], b[1]))
        assert moved > 0, (
            f"follower {k} is still at ({a[0]}, {a[1]}) after the run — a cast "
            f"that stands still is not an AI")
        assert len(heads[k]) > 1, (
            f"follower {k} held heading {a[2]} for the whole run — it never "
            f"turned, so the steering cross product is not steering it")
        assert len(dirs[k]) > 1, (
            f"follower {k} only ever displaced in direction {dirs[k]} — its "
            f"heading word moved but the step did not follow it, which is the "
            f"half a heading-only assertion would miss")
    advanced = [k for k in range(SWM_PLAYERS, SWM_N_SHIP) if len(wps[k]) > 1]
    assert len(advanced) == SWM_N_SHIP - SWM_PLAYERS, (
        f"only {len(advanced)} of the {SWM_N_SHIP - SWM_PLAYERS} followers "
        f"advanced a waypoint in {2 * RUN_STEPS} driven frames — "
        f"{sorted(set(range(SWM_PLAYERS, SWM_N_SHIP)) - set(advanced))} never "
        f"arrived, so the Chebyshev arrival test is not firing for them and "
        f"their loop is one target forever")


# =============================================================================
# 7. THE TWO PADS — each drives its own camera and ONLY its own
# =============================================================================
def _both_cameras(runner, tmp_path, tag):
    """Both bands' (heading, position), recovered from the FLOOR PIXELS.

    Taken with the pads RELEASED for the frame before the shot, so the picture
    and the state cannot be a frame apart — `take_screenshot` advances the
    emulated frame, and a held button would move the camera inside that
    advance.
    """
    _step(runner, 1)
    seed, _h = D._state(runner, advanced=False)
    px = D._shot(runner, tmp_path, tag)
    return [D._recover(px, b, list(seed)[b]) for b in (0, 1)]


def _turn_delta(after, before):
    """Signed pose steps from `before` to `after`, in (-128, 128]."""
    return ((after - before + 128) & 255) - 128


@pytest.mark.parametrize("pad", [0, 1])
def test_one_pad_drives_its_own_camera_and_leaves_the_other_untouched(
        fresh, tmp_path, pad):
    """RIGHT, LEFT and B on ONE pad, with every band read out of the PIXELS.

    Three claims per press, and the third is the one this rail's name is about:

      * the commanded camera's HEADING moves in the commanded SENSE (Right is
        +1 pose per frame held, Left is -1), or its POSITION advances for B;
      * nothing else about the commanded camera moves — B must not rotate and
        a turn must not translate;
      * THE OTHER CAMERA IS BIT-IDENTICAL. Heading and position both, recovered
        from its own half of the framebuffer, which is what makes "pad 2 does
        nothing to camera 1" a measurement rather than an absence of evidence.

    BOTH DIRECTIONS ARE PRESSED. A test that only ever held Right would lock
    one sense and ship the other broken — and on this rail that is not
    hypothetical: the autonomous senses are +1 and -1, so a build that ignored
    the pad entirely and stepped autonomously would pass a Right-only test on
    camera 1 and a Left-only test on camera 2.

    `_step` latches BOTH pads on every frame, so "the other pad is released" is
    stated rather than left at whatever it last held.
    """
    other = 1 - pad
    _unstick(fresh, tmp_path)
    for press, want in (({"right": True}, +1), ({"left": True}, -1),
                        ({"b": True}, 0)):
        tag = f"pad{pad}{''.join(press)}"
        before = _both_cameras(fresh, tmp_path, tag + "a")
        _step(fresh, 6, press if pad == 0 else None,
              press if pad == 1 else None)
        after = _both_cameras(fresh, tmp_path, tag + "b")

        turned = _turn_delta(after[pad][0], before[pad][0])
        moved = max(_wrapd(after[pad][1][i], before[pad][1][i])
                    for i in (0, 1))
        if want:
            assert turned * want >= 4, (
                f"pad {pad + 1} held {list(press)[0]} for 6 frames and "
                f"camera {pad + 1}'s heading moved {turned} poses; it must "
                f"step {want} per frame held")
            assert moved == 0, (
                f"pad {pad + 1}'s {list(press)[0]} also TRANSLATED camera "
                f"{pad + 1} by {moved} px — a turn is not a drive")
        else:
            assert turned == 0, (
                f"pad {pad + 1}'s B ROTATED camera {pad + 1} by {turned} "
                f"poses — a drive is not a turn")
            assert moved >= 6, (
                f"pad {pad + 1} held B for 6 frames and camera {pad + 1} "
                f"moved {moved} px; the drive is 2.0 px/frame")

        assert after[other] == before[other], (
            f"pad {pad + 1} held {list(press)[0]} and camera {other + 1} "
            f"went from {before[other]} to {after[other]} — the pads are "
            f"crossed, or one of them drives both cameras")


# =============================================================================
# 8. THE CADENCE GATE — the loop and the NMI, in lockstep, in situ
# =============================================================================
def _cadence(runner, frames, p1=None, p2=None):
    """(loop beat delta, VBlank delta) per stepped frame."""
    out = []
    _beat0 = _ctl(runner)[1]
    _f0 = _vblanks(runner)
    for _i in range(frames):
        _step(runner, 1, p1, p2)
        beat, frame = _ctl(runner)[1], _vblanks(runner)
        out.append(((beat - _beat0) & 0xFFFF, (frame - _f0) & 0xFFFF))
        _beat0, _f0 = beat, frame
    return out


def test_the_loop_and_the_nmi_advance_in_lockstep_at_the_shipped_count(fresh):
    """+1 AND +1, every stepped frame, at N = 24 — the rail's own cadence gate.

    THIS IS WHY THE SHIPPED COUNT IS 24. `tools/measure_sh2_swarm.py` says the
    tick costs 76.6% of a frame there and 102% at 32; that is a measurement of
    the WORK. This is the OBSERVATION that the work fits: `swm_beat` increments
    once per pass through the scene tick and `sm_nmi_core` increments
    ES_SM_FRAME on every NMI whether the frame was armed or not, so the two
    advance together exactly while the tick finishes inside its frame and the
    loop counter falls behind the moment it does not.

    IN SITU, on the SHIPPING ROM, under the drive the showcase actually uses —
    not on a probe and not at rest, because the cost depends on how much of the
    swarm is on screen.
    """
    _step(fresh, 4, P1_TURN, P2_TURN)
    pairs = _cadence(fresh, 40, P1_TURN, P2_TURN)
    bad = [(i, p) for i, p in enumerate(pairs) if p != (1, 1)]
    assert not bad, (
        f"the loop and the NMI are not in +1/+1 lockstep at N={SWM_N_SHIP}: "
        f"{bad[:6]} (loop delta, VBlank delta) — the tick is overrunning its "
        f"frame, which is exactly what the shipped count is chosen to avoid")


def test_the_cadence_gate_breaks_when_the_count_is_poked_past_the_cliff(fresh):
    """THE NON-VACUITY DIRECTION. Poke the live count up and the gate must FAIL.

    A gate that cannot be made to fail is not a gate, and this one is cheap to
    falsify because the count is a WRAM word the draw and the AI both ask every
    frame — the same handle `tools/measure_sh2_swarm.py` sweeps and the same one
    that walks the count 1..128. The measurement puts the whole tick at 102% of
    a frame by N=32 and 196% at 64, so at 64 the loop cannot keep up and the
    beat must fall behind the VBlank count.

    THEN IT MUST RECOVER. Restoring 24 and finding lockstep again is what
    separates "the count is what breaks it" from "something wedged".
    """
    _step(fresh, 4, P1_TURN, P2_TURN)
    _set_n(fresh, SWM_MAX)
    _step(fresh, 4, P1_TURN, P2_TURN)
    broken = _cadence(fresh, 20, P1_TURN, P2_TURN)
    _set_n(fresh, SWM_N_SHIP)
    _step(fresh, 6, P1_TURN, P2_TURN)
    healed = _cadence(fresh, 20, P1_TURN, P2_TURN)
    assert any(p != (1, 1) for p in broken), (
        f"at N={SWM_MAX} the loop still kept +1/+1 lockstep with the NMI "
        f"({broken[:6]}) — either the poke is not reaching the count or the "
        f"gate cannot fail, and a gate that cannot fail proves nothing")
    assert all(p == (1, 1) for p in healed), (
        f"lockstep did not come back at N={SWM_N_SHIP} ({healed[:6]}) — so the "
        f"break above was not the count")


# =============================================================================
# 9. THE FLOOR, WITH THE WHOLE CAST UP — the 2b speckle regression
# =============================================================================
def test_the_floor_is_still_the_hardware_oracle_with_the_swarm_running(fresh,
                                                                      tmp_path):
    """EVERY non-sprite pixel, against the sibling module's pixel-exact Mode 7
    oracle, over a driven run with 24 entities and their AI in the frame.

    PIXELS, NOT BYTES, and that is the whole reason this test exists. Putting
    the projection in the VBlank hook once made the floor SPECKLE from about a
    third of the way down — while VRAM matched `sh2_map.bin` at 0 mismatched
    bytes of 32,768, the WRAM index tables were intact and the scene_mgr
    channel shadow was intact. The mechanism is `sm_nmi_core`'s post-hook MVN
    of the 128-byte channel shadow into $4300: overrun VBlank and it lands
    during ACTIVE DISPLAY and rewrites every channel's running HDMA state
    mid-frame. Every byte reads back correct and the picture is wrong, so only
    a framebuffer assertion can see it.

    This build puts six times that work in the tick — 24 entities plus an AI —
    and this is the standing check that it stayed out of the hook.
    """
    checked = 0
    _unstick(fresh, tmp_path)
    for i in range(3):
        _step(fresh, 2, P1_TURN, P2_TURN)
        _step(fresh, 1)
        seed, _h = D._state(fresh, advanced=False)
        px = D._shot(fresh, tmp_path, f"floor{i}")
        rec = [D._recover(px, b, list(seed)[b]) for b in (0, 1)]
        cam = [rec[0][1], rec[1][1]]
        heads = [rec[0][0], rec[1][0]]
        for sy in range(D.ACTIVE_H):
            for sx in range(256):
                got = tuple(v >> 3 for v in px[sx, sy])
                if got in D.MARKER_COLORS:
                    continue
                want = D._predict(sx, sy, cam, heads)
                assert got == want, (
                    f"sample {i}: the plane at ({sx}, {sy}) is {got}, the "
                    f"Mode 7 oracle says {want} — the floor is not the map "
                    f"with the swarm running")
                checked += 1
    assert checked >= 3 * 256 * D.ACTIVE_H * 9 // 10, (
        f"only {checked} plane pixels were checked across the run — too many "
        f"were under a sprite for this to be a statement about the floor")
