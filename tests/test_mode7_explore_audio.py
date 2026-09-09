"""mode7_explore's two cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

THE CHEAPEST CUES IN THE TREE, and the reason is that this rail had already
done the hard part for a different consumer. `maze` and `camera_follow` walk in
free pixels and had to DECLARE a stride latch to have an edge at all; here the
avatar slides cell to cell and `m7x_logic` publishes US_LANDED, one frame wide,
cleared at the top of every mxl_tick. So both cues hang off an edge that
already existed and neither rail-side word was added.

TWO CUES, TWO DIFFERENT CLAIMS:

  * `footstep` on every arrival. The cadence case is what proves it is the
    ARRIVAL and not the walk: the pad is HELD to travel and a slide takes
    several frames, so a cue read off US_STEP_ACTIVE — the level next to the
    edge, one token away — sounds through all of them.
  * `chime` at the doorway, which is one-shot for a stronger reason than a
    latch: it is reached only from that same landing test, on the ONE world
    tile carrying TERR_TOWN_ENTER, and the dissolve that follows freezes the
    avatar for twenty frames.

THE CAMERA TILE IS THE DRIVE'S OWN CHECK. Both fixtures assert the avatar
actually travelled, so a rotted route fails naming the position rather than
going quiet on a cue and reading as a defect in the audio.
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
W = MemoryType.SnesWorkRam
SFX_VOICES = (6, 7)
STEP, BELL = 3, 4               # instrument order in slice_b.terrificaudio

ROM = SUPERFORGE / "build" / "mode7_explore.sfc"
ASSETS = SUPERFORGE / "build" / "assets"
_JMAP = json.loads((SUPERFORGE / "build" / "m7x" / "symbol_map.json").read_text())


def _sym(name, scene="overworld"):
    """Addresses are ASKED FOR, never hardcoded — the same map the ROM was
    assembled against, so an allocator move breaks this loudly rather than
    silently reading the wrong bytes."""
    for p in _JMAP["scenes"][scene]["placements"]:
        if p["sym"] == name:
            return p
    raise KeyError(name)


DP_CAM_PX = _sym("US_CAM_PX")["start"]
DP_CAM_PY = _sym("US_CAM_PY")["start"]

# The world's geometry from the GENERATOR'S emitted .inc rather than
# transcribed — one author for the numbers the ROM and this drive share.
_WORLD = {}
for _line in (ASSETS / "m7x_world.inc").read_text().splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = (t.strip() for t in _line.split("=", 1))
        _v = _v.split(";")[0].strip()
        if _v.isdigit():
            _WORLD[_k] = int(_v)

WALK_FRAMES = 600
IDLE_FRAMES = 300


class _Drive:
    """One frame at a time, sampling the DSP on every one of them.

    The walk helper below loops until the camera reaches a tile; if only the
    outer route sampled, the frames a cue actually sounds on could fall in a
    gap and the count would be of the sampling, not of the sound.
    """

    def __init__(self, runner):
        self.r = runner
        self.rows = []

    def step(self, n=1, **pad):
        for _ in range(n):
            self.r.frame_step(1, **pad)
            d = self.r.read_bytes(DSP, 0, 128)
            self.rows.append(
                [(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])

    def tile(self):
        return (self.r.read_u16(W, DP_CAM_PX) // 8,
                self.r.read_u16(W, DP_CAM_PY) // 8)

    def walk_to(self, target, **pad):
        """Hold a direction until the camera reaches `target`, then come to REST.

        Bounded in EMULATED frames on a parked core, so host load cannot change
        what this does. The trailing steps release the pad and let the
        in-flight slide land: a step is atomic and only complete at rest.
        """
        for _ in range(1200):
            if self.tile() == target:
                break
            self.step(**pad)
        else:
            pytest.fail(f"never reached tile {target}; stopped at {self.tile()}")
        self.step(12)
        return self.tile()


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def _boot():
    assert ROM.exists(), f"{ROM} missing — run `make mode7_explore` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(ROM), frames=300)
    return r


@pytest.fixture(scope="module")
def walked():
    """Hold LEFT for a long stretch, then stand still for `IDLE_FRAMES`.

    Two measurements out of one boot, and the second is the sharper: a rail
    that sounds while the pad is held will also sound while it is not if the
    cue is on the wrong word, and "exactly silent at rest" is decidable where
    a walking fraction is a judgement.
    """
    r = _boot()
    d = _Drive(r)
    try:
        start = d.tile()
        d.step(WALK_FRAMES, left=True)
        walking = len(d.rows)
        moved = d.tile()
        d.step(IDLE_FRAMES)
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failure above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return d.rows, walking, start, moved


def test_the_walk_actually_travelled(walked):
    """Non-vacuity, on the game state rather than the cue."""
    _, _, start, moved = walked
    assert moved[0] < start[0] - 4, (
        f"the camera went {start} -> {moved} in {WALK_FRAMES} frames of held "
        f"LEFT — the drive did not walk, so the cue cases below would be "
        f"measuring an avatar standing still")


def test_walking_is_audible(walked):
    """`footstep` is voiced by step (assets/audio/sound-effects.txt)."""
    rows, walking, _, _ = walked
    assert _live(rows[:walking], STEP) > 0, (
        "no step voice ever sounded on an SFX channel while walking — the "
        "footstep cue never reached the chip")


def test_the_footstep_is_the_arrival_and_not_the_slide(walked):
    """US_LANDED, not US_STEP_ACTIVE — one token apart, and audible.

    The pad is held for the whole walk and a slide occupies several frames, so
    a cue on the level rather than the edge sounds through nearly all of them.
    Planted (US_LANDED swapped for US_STEP_ACTIVE, one identifier) this is the
    only case in the module that reds — the audibility case, the idle-silence
    case and both doorway cases stay green, because the defect is a CADENCE
    and nothing else here measures one. The footstep's own decay sets the
    ceiling for a correct rail; the bar sits between the two by a wide margin.
    """
    rows, walking, _, _ = walked
    frac = _live(rows[:walking], STEP) / walking
    assert frac < 0.55, (
        f"the step voice is live on {frac:.0%} of walking frames — the cue is "
        f"reading US_STEP_ACTIVE (the slide, a level) rather than US_LANDED "
        f"(the arrival, an edge)")


def test_standing_still_is_exactly_silent(walked):
    """The decidable half, and the bar is zero.

    Nothing else on this rail can queue an effect, the pad is released, and
    `mxl_tick` clears US_LANDED at the top of every frame — so an idle stretch
    that sounds at all means the cue is hanging off something that is true
    while the avatar is at rest.
    """
    rows, walking, _, _ = walked
    tail = rows[walking + 60:]
    assert len(tail) >= 200, "the idle tail is too short to decide silence"
    live = _live(tail, STEP)
    assert live == 0, (
        f"the step voice sounds on {live} of {len(tail)} frames with the pad "
        f"released and the avatar at rest — the footstep is not on US_LANDED")


@pytest.fixture(scope="module")
def doorway():
    """Walk the generator's own forced-grass approach onto the one enterable
    house, then hold through the dissolve.

    West along the spawn row to the house column, then north up the approach —
    the same route `test_mode7_explore.py` walks, rebuilt here from the same
    emitted constants rather than imported from a test module.

    Returns `(rows, at)`: the whole sample stream and the index the landing
    step began at, so the DISSOLVE can be sliced off it. The dissolve is the
    case: twenty frames in which the avatar cannot move and nothing may chime
    a second time.
    """
    r = _boot()
    d = _Drive(r)
    house = (_WORLD["M7X_DEMO_HOUSE_TX"], _WORLD["M7X_DEMO_HOUSE_TY"])
    try:
        d.walk_to((house[0], _WORLD["M7X_SPAWN_TY"]), left=True)
        d.walk_to((house[0], house[1] + 1), up=True)
        at = len(d.rows)
        d.step(1, up=True)          # the step that lands ON the house
        d.step(60)                  # ...the wipe, and well past it
        landed = d.tile()
    finally:
        r.stop()
    return d.rows, at, landed, house


def test_the_route_reached_the_house(doorway):
    """Non-vacuity: the chime cases below mean nothing off the trigger tile."""
    _, _, landed, house = doorway
    assert landed == house, (
        f"the route ended on tile {landed}, not the enterable house {house} — "
        f"the world geometry moved under this drive, so nothing below is "
        f"measuring a doorway")


def test_the_doorway_is_audible(doorway):
    """`chime` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, at, _, _ = doorway
    assert _live(rows[at:], BELL) > 0, (
        "no bell voice ever sounded on an SFX channel across the landing on "
        "the house — the doorway cue never reached the chip")


def test_the_doorway_chimes_once(doorway):
    """And the approach does NOT chime, which is the half a bare audibility
    case cannot see.

    Every step of the walk up to the doorstep runs the same landing test the
    doorway cue hangs off; only the last one is on the tile carrying
    TERR_TOWN_ENTER. A cue moved out of `check_town_entry` and up beside the
    footstep would still pass the case above and would ring on every step of
    the route. So the approach is asserted EXACTLY silent on bell, and the bar
    is zero rather than a fraction.
    """
    rows, at, _, _ = doorway
    approach = _live(rows[:at], BELL)
    assert approach == 0, (
        f"the bell voice sounds on {approach} of the {at} frames BEFORE the "
        f"house is reached — the doorway cue is firing on every landing, not "
        f"on the one tile carrying TERR_TOWN_ENTER")
