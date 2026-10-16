"""railshooter's two cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

TWO CUES, TWO SHAPES, AND NEITHER TOUCHES `rs_logic`:

  * `laser` on the trigger. `rs_shot_cue` reads ES_INP_PRESS's A bit — the
    EXACT word `rs_fire` bails on, one instruction below it — so the cue and
    the shot cannot disagree about whether a trigger was pulled, and the edge
    is the `input` feature's to publish rather than anything this rail has to
    latch. Holding A must therefore fire once.
  * `explosion` on a KILL, which is `score`'s change. The counter is this
    rail's own declared word that `rs_logic` fills, so the cue is the game's
    to make; but a score is a LEVEL and only its step is the event.

TWO SAMPLES, AND THAT IS WHAT MAKES THE TWO CUES SEPARABLE AT ALL. `laser` is
voiced by `saw` and `explosion` by `step` (assets/audio/sound-effects.txt), so
SRCN tells a shot from a kill even when they land together. `explosion` is
declared `both`, which per that file's FLAGS section means it may take EITHER
sfx channel — so it can OVERLAP the laser rather than replace it. The ring
still hands one id to the driver per frame, so on a frame that both fires and
kills the second arrives on the next one; that is why the kill case reads a
WINDOW rather than a single frame.

THE GAME'S OWN COUNTER IS THE DRIVES' CHECK — `score` for the kills, so a
rotted drive fails naming the game state rather than going quiet on a cue.
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
STEP, SAW = 3, 5                # instrument order in slice_b.terrificaudio

ROM = SUPERFORGE / "build" / "railshooter.sfc"
_JMAP = json.loads((SUPERFORGE / "build" / "rs" / "symbol_map.json").read_text())


def _sym(name, scene="rail"):
    """Addresses are ASKED FOR, never hardcoded — the same map the ROM was
    assembled against, so an allocator move breaks this loudly."""
    for p in _JMAP["scenes"][scene]["placements"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(name)


DP_SCORE = _sym("US_SCORE")
O = MemoryType.SnesSpriteRam

# The OAM windows this rail emits into, and the hazard tiles, restated from the
# same source `test_railshooter.py` reads them from rather than imported from a
# test module. The AIMING LOOP below needs them because it flies the reticle
# from what is ON SCREEN — which is the pilot's own loop, and the only drive
# that actually kills anything.
RET_SLOT = 0
HAZ_SLOT0, HAZ_N = 3, 4
T_HAZ = (192, 196, 164, 166)    # tier 0 (nearest) .. tier 3 (farthest)
LARGE_TILES = T_HAZ[:2]

SHOTS = 20
PERIOD = 30                     # frames per trigger cycle...
HOLD = 20                       # ...of which this many hold A down
IDLE_FRAMES = 300
AIM_FRAMES = 200                # per acquisition, before giving up on it


class _Drive:
    """One frame at a time, sampling the DSP on every one of them."""

    def __init__(self, runner):
        self.r = runner
        self.rows = []

    def step(self, n=1, **pad):
        for _ in range(n):
            self.r.frame_step(1, **pad)
            d = self.r.read_bytes(DSP, 0, 128)
            self.rows.append(
                [(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])

    def score(self):
        return int.from_bytes(self.r.read_bytes(W, DP_SCORE, 2), "little")

    # ---- the picture, which is what the aiming loop steers from -----------
    def oam(self):
        return self.r.read_bytes(O, 0, 544)

    @staticmethod
    def _entry(oam, slot):
        x, y, tile, attr = oam[slot * 4:slot * 4 + 4]
        pair = (oam[512 + (slot >> 2)] >> ((slot & 3) * 2)) & 3
        return x, y, tile, attr, pair & 1, (pair >> 1) & 1

    @classmethod
    def _x9(cls, oam, slot):
        """The sprite's full NINE-bit screen x as a SIGNED offset. The ninth
        bit lives in the hi table; reading the low byte alone puts a sprite
        hanging off the left edge on the RIGHT of the screen."""
        e = cls._entry(oam, slot)
        v = e[0] + 256 * e[4]
        return v - 512 if v >= 256 else v

    @classmethod
    def _target(cls, oam):
        """The nearest hazard ON SCREEN — lowest tier, which is also the
        lowest slot the depth-sorted emit gave it."""
        live = [(s, cls._x9(oam, s)) + tuple(cls._entry(oam, s)[1:3])
                for s in range(HAZ_SLOT0, HAZ_SLOT0 + HAZ_N)
                if cls._entry(oam, s)[2] != 0]
        return min(live, key=lambda h: T_HAZ.index(h[3])) if live else None

    def aim_and_fire(self, budget=AIM_FRAMES):
        """Fly the reticle onto the nearest hazard, then pull the trigger.

        THE PILOT'S LOOP, driven from RENDERED positions rather than world
        state — which is the point: it walks the d-pad -> world aim ->
        projection -> screen path end to end, so a reversed axis cannot pass.
        Ported from `test_railshooter.py::_steer_onto_target`, and it is what
        makes this module's kill cases mean anything: a drive that only fires
        straight ahead scores nothing at all, which is exactly what the
        non-vacuity case caught the first time round.
        """
        for _ in range(budget):
            oam = self.oam()
            tgt = self._target(oam)
            if tgt is None:
                self.step()
                continue
            _, tx, ty, tile = tgt
            half = 16 if tile in LARGE_TILES else 8
            rcx = self._x9(oam, RET_SLOT) + 8
            rcy = self._entry(oam, RET_SLOT)[1] + 8
            pad = {}
            if tx + half - rcx > 4:
                pad["right"] = True
            elif rcx - (tx + half) > 4:
                pad["left"] = True
            if ty + half - rcy > 4:
                pad["down"] = True
            elif rcy - (ty + half) > 4:
                pad["up"] = True
            if not pad:
                self.step(a=True)       # ON TARGET: the rising edge is the shot
                self.step()             # ...and the release, so the next press
                return True             #    is a real edge and not a hold
            self.step(**pad)
        return False


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


@pytest.fixture(scope="module")
def fired():
    """TWO drives out of one boot, because the two cues want different things.

    First `SHOTS` AIMED shots — the pilot's loop, which is the only drive that
    kills anything and so the only one the explosion cases can mean something
    under. Then a stretch that HOLDS A for most of each cycle without aiming,
    which is what the trigger's cadence case needs: 20 of every 30 frames have
    A down, so a cue read off the held state has two thirds of it to sound in
    while the correct one has a handful of instants. Then the idle tail with
    the trigger released, where neither cue may sound at all.
    """
    assert ROM.exists(), f"{ROM} missing — run `make railshooter` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(ROM), frames=300)
    d = _Drive(r)
    try:
        before = d.score()
        for _ in range(SHOTS):
            if not d.aim_and_fire():
                break
        after = d.score()
        aimed = len(d.rows)
        for i in range(SHOTS * PERIOD):
            d.step(a=(i % PERIOD < HOLD))
        firing = len(d.rows)
        d.step(IDLE_FRAMES)
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failure above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return d.rows, aimed, firing, before, after


def test_the_drive_actually_killed_something(fired):
    """Non-vacuity for the KILL cue, and it is the counter rather than the cue.

    Twenty aimed-ahead shots down a field the rail keeps spawning into should
    connect at least once; a drive that scores nothing would leave the kill
    cases below vacuously green whatever the ASM does.
    """
    _, _, _, before, after = fired
    assert after > before, (
        f"the score went {before} -> {after} across {SHOTS} shots — nothing "
        f"died, so the kill cases below would be measuring a field the pilot "
        f"never hit")


def test_the_trigger_is_audible(fired):
    """`laser` is voiced by saw (assets/audio/sound-effects.txt)."""
    rows, aimed, firing, _, _ = fired
    assert _live(rows[:firing], SAW) > 0, (
        "no saw voice ever sounded on an SFX channel across twenty trigger "
        "pulls — the shot cue never reached the chip")


def test_a_kill_is_audible(fired):
    """`explosion` is voiced by step (assets/audio/sound-effects.txt)."""
    rows, aimed, _, _, _ = fired
    assert _live(rows[:aimed], STEP) > 0, (
        "no step voice sounded on an SFX channel across the AIMED drive, "
        "which is the one that scores — the kill cue never reached the chip")


def test_the_shot_is_the_press_and_not_the_hold(fired):
    """A is DOWN for two thirds of this drive and the laser must not be.

    `rs_shot_cue` reads ES_INP_PRESS, which is also what `rs_fire` bails on;
    the mistake the rail invites is reading ES_INP_CUR, one token away, which
    sounds a laser on every held frame while the gun still fires once. Both
    pass the audibility case above and BOTH KILL CASES TOO — planted, this is
    the only case in the module that reds. That is what it is for.
    """
    rows, aimed, firing, _, _ = fired
    held = rows[aimed:firing]
    frac = _live(held, SAW) / len(held)
    assert frac < 0.35, (
        f"the saw voice is live on {frac:.0%} of the HELD drive's frames, "
        f"which holds A for {HOLD}/{PERIOD} of each cycle — the shot cue is "
        f"reading the HELD state (ES_INP_CUR) rather than the press edge")


def test_a_released_trigger_is_exactly_silent(fired):
    """The decidable half, and the bar is zero.

    With A released for `IDLE_FRAMES` the pilot fires nothing, so nothing can
    die either: neither cue may sound. This is what catches a laser hung off
    the frame rather than the trigger, and a kill cue hung off the SCORE's
    value rather than its change — the latter would ring for the whole tail,
    because the score stays where the drive left it.
    """
    rows, aimed, firing, _, _ = fired
    tail = rows[firing + 60:]
    assert len(tail) >= 200, "the idle tail is too short to decide silence"
    saw, step = _live(tail, SAW), _live(tail, STEP)
    assert (saw, step) == (0, 0), (
        f"with the trigger released, the saw voice sounds on {saw} of "
        f"{len(tail)} frames and the step voice on {step} — a laser on "
        f"anything but the press edge, or a kill cue on the SCORE's VALUE "
        f"rather than on `US_SCOREPREV`'s comparison against it")
