"""mill's one cue, on the chip that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

ONE CUE, AND THE RESTRAINT IS THE POINT. The lift's ARRIVAL, at hall.asm's
`@arrived`, which runs the scene switch two instructions later — so the tick
that reaches it is the last one that scene gets and the cue is an edge with no
latch. Every other candidate on this rail (boarding, the car leaving the floor,
a footstep on the deck) is read off a LEVEL that `mil_obj` republishes every
frame, and each would want its own `prev` word in state.toml. Adding four
latches to sound a machine hall is a content decision this pass did not make;
one cue on the one existing edge is.

WHAT THAT MAKES TESTABLE, and it is more than "a bell played". The whole ride
before the arrival — the lobby, the boarding, the climb, every frame of shaft
sliding past — must be EXACTLY silent, because the one cue is at the far end
of it. That is a bar of zero across hundreds of frames rather than a fraction,
and it is what catches the cue being moved to the boarding or the departure,
both of which are levels and both of which are where an author would reach
first.

DRIVEN THROUGH `Machine`, like the rest of this rail's tests: the deterministic
lockstep wrapper, one frame per `advance`, every step waiting on a CONDITION
read out of the machine rather than on a count of frames. The ride's length,
the door's travel and the fade are all the rail's own tuning and a count would
go stale the first time any of them moved.
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM = BUILD / "mill.sfc"
ASSETS = BUILD / "assets"

sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine, MemoryType                          # noqa: E402

W = MemoryType.SnesWorkRam
DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)
BELL = 4                        # instrument order in slice_b.terrificaudio

_JMAP = json.loads((BUILD / "mil" / "symbol_map.json").read_text())


def _dp(name):
    """Addresses are ASKED FOR, never hardcoded — the same map the ROM was
    assembled against, so an allocator move breaks this loudly."""
    for scene in ("lobby", "hall"):
        for p in _JMAP["scenes"][scene]["placements"]:
            if p["sym"] == name:
                return p["start"]
    for p in _JMAP["globals"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _art(key):
    """One equate out of the GENERATED build/assets/mil_art.inc — a copy of a
    rail constant living here as a literal goes stale the moment the geometry
    changes, and the module keeps passing."""
    for line in (ASSETS / "mil_art.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == key:
            v = rest.split(";")[0].strip()
            return int(v[1:], 16) if v.startswith("$") else int(v)
    raise KeyError(key)


DP_SM = _dp("ES_SM_CTL")
DP_DOOR = _dp("ES_MIL_DOOR")
DP_PX = _dp("ES_MIL_PX")
DP_CAR = _dp("ES_MIL_CAR")
DP_ARRIVE = _dp("ES_MIL_ARRIVE")

SMIL_LIFT_COL = _art("SMIL_LIFT_COL")
DOOR_TRAVEL = _art("SMIL_DOOR_TRAVEL")

BOOT = 60
SCENE_LOBBY, SCENE_HALL = 0, 1
JOY_UP, JOY_LEFT, JOY_RIGHT = {"up": True}, {"left": True}, {"right": True}


class _Ride:
    """The rail's own drive, sampling the DSP on every advanced frame.

    Every wait below is on a CONDITION and every one samples, so no frame a
    cue could sound on falls in a gap between the route's steps.
    """

    def __init__(self, m):
        self.m = m
        self.rows = []

    def step(self, n=1, pad=None):
        for _ in range(n):
            self.m.advance(1, pad1=pad)
            d = self.m.read_bytes(DSP, 0, 128)
            self.rows.append(
                [(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])

    def u16(self, addr):
        return self.m.read_u16(W, addr)

    def scene(self):
        return self.u16(DP_SM) & 0xFF

    def until(self, pred, limit, pad=None, what=""):
        for _ in range(limit):
            if pred():
                return
            self.step(pad=pad)
        pytest.fail(f"{what} never happened in {limit} frames")

    def to_hall(self):
        """The boot lobby, through one boarding, into the hall."""
        self.step(BOOT)
        self.until(lambda: self.u16(DP_DOOR + 2) >= DOOR_TRAVEL,
                   600, JOY_RIGHT, "the far bay opening")
        self.step(3, JOY_UP)
        self.until(lambda: self.scene() == SCENE_HALL, 600,
                   what="the hall arriving")

    def board_and_ride(self):
        """From standing in the hall, get on the lift and start the climb."""
        self.until(lambda: self.m.read_bytes(W, DP_SM + 2, 1)[0] == 0, 400,
                   what="the hall finishing its arrival")
        self.until(lambda: self.u16(DP_PX) >= SMIL_LIFT_COL * 8, 400,
                   JOY_RIGHT, "the walk onto the car")
        self.until(lambda: self.u16(DP_PX) <= SMIL_LIFT_COL * 8, 400,
                   JOY_LEFT, "settling on the car")
        self.step(4, JOY_UP)
        self.until(lambda: self.u16(DP_CAR) > 0, 240,
                   what="the lift starting after UP")


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


@pytest.fixture(scope="module")
def ridden():
    """Ride the lift all the way to the other bay.

    Returns `(rows, at_arrival, arrived, ended_in)` — the whole sample stream,
    the index the lift reached the other bay at, the arrival flag READ AT THAT
    EDGE, and the scene the ride left the machine in. Everything before
    `at_arrival` is the long silent stretch the one cue sits at the end of.
    """
    assert ROM.exists(), f"{ROM} missing — run `make mill` first"
    with Machine(str(ROM)) as m:
        d = _Ride(m)
        d.to_hall()
        d.board_and_ride()
        d.until(lambda: d.u16(DP_ARRIVE) == 1, 1200,
                what="the lift reaching the other bay")
        # READ THE FLAG AT THE EDGE, not after the tail. `@arrived` sets
        # ES_MIL_ARRIVE and switches the scene in the same breath, and the
        # lobby CONSUMES the flag on the way in — so a read taken ninety
        # frames later finds 0 and says the ride never happened. The scene id
        # is the durable corroboration and is checked beside it.
        arrived = d.u16(DP_ARRIVE)
        at_arrival = len(d.rows)
        d.step(90)                      # ...and the arrival's own tail
        ended_in = d.scene()
    return d.rows, at_arrival, arrived, ended_in


def test_the_ride_actually_completed(ridden):
    """Non-vacuity, on the rail's own word rather than the cue.

    `ES_MIL_ARRIVE` is written 1 in the same `@arrived` arm the chime sits in,
    two instructions apart, so a drive that never got there fails HERE naming
    the ride instead of failing the audibility case and reading as a defect in
    the sound.
    """
    _, _, arrived, ended_in = ridden
    assert (arrived, ended_in) == (1, SCENE_LOBBY), (
        f"the ride ended with ES_MIL_ARRIVE = {arrived} in scene {ended_in} "
        f"(wanted 1 in {SCENE_LOBBY}) — the lift never reached the other bay, "
        f"so the cue cases below would be measuring a ride that did not "
        f"finish")


def test_the_arrival_is_audible(ridden):
    """`chime` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, at_arrival, _, _ = ridden
    assert _live(rows[at_arrival:], BELL) > 0, (
        "no bell voice sounded on an SFX channel in the frames after the lift "
        "reached the other bay — the arrival cue never reached the chip")


def test_the_lobby_the_boarding_and_the_climb_are_exactly_silent(ridden):
    """The whole ride up to the arrival, at a bar of zero.

    This is what one cue at one edge buys: everything before it is decidable
    rather than a fraction. The cue an author would reach for first is the
    BOARDING or the car LEAVING the floor, and both are levels `mil_obj`
    republishes every frame — either would sound through the hundreds of
    frames this asserts silent, while leaving the audibility case above
    perfectly green. The window is the whole ride: lobby, the walk, the
    boarding and every frame of shaft sliding past — 335 frames, and a cue
    planted on the scene tick's own top sounds on 169 of them.

    THE FIRST PLANT TRIED HERE PASSED, and the reason is worth carrying: it
    put the cue inside the `bne` that guards `mil_lift_call`, an arm reached
    only while ES_MIL_BOARD is 0. The drive is in the LOBBY for most of that
    window and steps onto the car almost at once, so the planted line barely
    ran. The ROM's md5 moved and the plant still proved nothing — a moved md5
    says the ROM changed, never that the drive reached the change.
    """
    rows, at_arrival, _, _ = ridden
    assert at_arrival >= 250, (
        f"only {at_arrival} frames of lobby, boarding, hall and climb before "
        f"the arrival — too short to decide silence")
    live = _live(rows[:at_arrival], BELL)
    assert live == 0, (
        f"the bell voice sounds on {live} of the {at_arrival} frames BEFORE "
        f"the lift arrives — the cue is not at `@arrived`, it is on something "
        f"the rail republishes while the player is still walking the deck or "
        f"riding up")
