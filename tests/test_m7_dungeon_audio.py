"""m7_dungeon's two cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

TWO CUES, AND THEY ARE THE TWO SHAPES THIS TREE KEEPS MEETING:

  * `thud` on the knockback, which is ALREADY one-shot and needed no latch:
    contact is a state — the hero and a slime overlap for as long as the touch
    lasts — and the GRACE window `do_contact` arms is what turns it into an
    event. The cue sits inside that guard, so the mechanism that stops a
    single touch counting twice stops it sounding twice for free.
  * `chime` at the goal, which is NOT. `do_win_card`'s own header calls the
    card "an OVERLAY, not a state machine ... Reaching the goal draws it;
    leaving stops drawing it" — right for a picture and wrong for a sound,
    because the window test runs every frame and the hero may stand still on
    the tile. `onwin` in state.toml is the edge, set where the test first
    passes and cleared in the same routine's @off arm.

THE GAME'S OWN COUNTERS ARE THE DRIVES' CHECK. `US_HITS` for the first and the
hero's position for the second, so a rotted drive fails naming the game state
rather than going quiet on a cue and reading as a defect in the audio.
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

ROM = SUPERFORGE / "build" / "m7_dungeon.sfc"
_JMAP = json.loads((SUPERFORGE / "build" / "m7dg" / "symbol_map.json").read_text())


def _sym(name, scene="dungeon"):
    """Addresses are ASKED FOR, never hardcoded — the same map the ROM was
    assembled against, so an allocator move breaks this loudly."""
    for p in _JMAP["scenes"][scene]["placements"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(name)


DP_HEADING = _sym("US_HEADING")
DP_SPEED = _sym("US_SPEED")     # signed 8.8
DP_HITS = _sym("US_HITS")
DP_POSX = _sym("US_POSX")       # 16.16: +2 is the integer px
DP_POSY = _sym("US_POSY")
DP_ONWIN = _sym("US_ONWIN")

HUNT_FRAMES = 900
IDLE_AFTER_WIN = 300

NORTH, WEST, SOUTH, EAST = 0, 64, 128, 192
# The maze route from the spawn cell to the goal cell, heading by heading —
# the same sequence `test_m7_dungeon.py::_ROUTE` walks, restated here from the
# same four heading constants rather than imported from a test module.
ROUTE = (NORTH, EAST, SOUTH, EAST, SOUTH)


class _Drive:
    """One frame at a time, sampling the DSP on every one of them.

    The route below loops inside `_turn` and `_push`; if only the outer route
    sampled, the frames a cue actually sounds on could fall in a gap and the
    count would be of the sampling, not of the sound.
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

    def u16(self, addr):
        return int.from_bytes(self.r.read_bytes(W, addr, 2), "little")

    def pos(self):
        return (self.u16(DP_POSX + 2), self.u16(DP_POSY + 2))

    def turn(self, target, limit=400):
        for _ in range(limit):
            h = self.u16(DP_HEADING)
            if h == target:
                return
            d = (target - h) & 255
            self.step(left=(d <= 128), right=(d > 128))
        pytest.fail(f"the heading never reached {target}")

    def push(self, frames=400, stuck_limit=15):
        last, stuck = self.pos(), 0
        for _ in range(frames):
            self.step(b=True)
            p = self.pos()
            stuck = stuck + 1 if p == last else 0
            last = p
            if stuck >= stuck_limit:
                return

    def rest(self, limit=80):
        for _ in range(limit):
            if self.u16(DP_SPEED) == 0:
                return
            self.step()


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def _boot():
    assert ROM.exists(), f"{ROM} missing — run `make m7_dungeon` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(ROM), frames=300)
    return r


@pytest.fixture(scope="module")
def hit():
    """Leave the spawn sanctuary, stand in a slime's corridor, take a hit.

    The spawn tile is a sanctuary and the knockback teleports the hero back to
    it, so getting hit takes driving: east off the spawn far enough to be
    hittable, then wait for the pacing slime's beat to come round.
    """
    r = _boot()
    d = _Drive(r)
    try:
        d.turn(EAST)
        d.step(24, b=True)          # off the sanctuary, not out of the corridor
        d.rest()
        at = len(d.rows)
        h0 = d.u16(DP_HITS)
        for _ in range(HUNT_FRAMES):
            d.step()
            if d.u16(DP_HITS) != h0:
                break
        hits = d.u16(DP_HITS)
        after = len(d.rows)
        d.step(240)                 # ...and well past the grace window
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failure above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return d.rows, at, after, h0, hits


def test_the_drive_actually_took_a_hit(hit):
    """Non-vacuity, on the game's counter rather than the cue."""
    _, _, _, h0, hits = hit
    assert hits == h0 + 1, (
        f"US_HITS went {h0} -> {hits} in {HUNT_FRAMES} frames — no contact "
        f"landed (or more than one did), so the cue cases below would be "
        f"measuring a hero nothing touched")


def test_the_knockback_is_audible(hit):
    """`thud` is voiced by step (assets/audio/sound-effects.txt)."""
    rows, at, after, _, _ = hit
    assert _live(rows[at:after + 30], STEP) > 0, (
        "no step voice sounded on an SFX channel across the contact — the "
        "knockback cue never reached the chip")


def test_nothing_thuds_before_the_contact(hit):
    """The approach is EXACTLY silent, and the bar is zero.

    `do_contact` runs its overlap test every frame; what makes the hit an
    event is the GRACE window, and the cue sits inside that guard. A cue moved
    above the guard — outside the `beq` that skips a hero still in grace, or
    up beside the overlap test itself — would sound through every frame of the
    touch, and the audibility case above would not notice. Driving out of the
    sanctuary and standing takes hundreds of frames in which the hero is not
    being hit, so this is decidable rather than a fraction.
    """
    rows, at, _, _, _ = hit
    live = _live(rows[:at], STEP)
    assert live == 0, (
        f"the step voice sounds on {live} of the {at} frames BEFORE any "
        f"contact — the knockback cue is not inside the grace guard")


@pytest.fixture(scope="module")
def won():
    """Walk the maze route to the goal, then STAND ON IT for `IDLE_AFTER_WIN`.

    The standing is the case. `do_win_card` re-tests the window every frame and
    the hero is free to stay, so a cue on the test rather than on `onwin`'s
    0 -> 1 edge would ring for as long as he does.
    """
    r = _boot()
    d = _Drive(r)
    try:
        for h in ROUTE:
            d.rest()
            d.turn(h)
            d.push()
        at = len(d.rows)
        d.step(IDLE_AFTER_WIN)      # stand on the goal, hands off the pad
        end, onwin = d.pos(), d.u16(DP_ONWIN)
    finally:
        r.stop()
    return d.rows, at, end, onwin


def test_the_route_reached_the_goal(won):
    """Non-vacuity: the chime cases mean nothing off the goal cell."""
    _, _, end, onwin = won
    assert onwin == 1, (
        f"the route ended at {end} with US_ONWIN = {onwin} — the hero is not "
        f"standing inside the goal window, so nothing below is measuring an "
        f"arrival")


def test_reaching_the_goal_is_audible(won):
    """`chime` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, _, _, _ = won
    assert _live(rows, BELL) > 0, (
        "no bell voice ever sounded on an SFX channel across a route that "
        "ends on the goal — the goal cue never reached the chip")


def test_standing_on_the_goal_does_not_re_chime(won):
    """The sharpest of the four, and the only one with a bar of zero.

    The hero is left standing on the goal with the pad released for
    `IDLE_AFTER_WIN` frames — over four seconds — while `do_win_card` re-tests
    the window and redraws the banner on every one of them. The card is a
    state and SHOULD keep drawing; the chime is an arrival and must not keep
    sounding. `onwin` is the whole difference: planted (its `bne` replaced by
    a nop) this is the only case in the module that reds, with the other five
    — the knockback pair, the route check and the audibility case — all still
    green.
    """
    rows, at, _, _ = won
    tail = rows[at + 90:]
    assert len(tail) >= 200, "the idle tail is too short to decide silence"
    live = _live(tail, BELL)
    assert live == 0, (
        f"the bell voice is still sounding on {live} of {len(tail)} frames "
        f"more than a second after the goal was reached, with the pad "
        f"released — the goal cue is on `do_win_card`'s window TEST rather "
        f"than on US_ONWIN's 0 -> 1 edge")
