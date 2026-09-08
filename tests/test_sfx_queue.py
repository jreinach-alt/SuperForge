"""The SFX request queue: does a cue survive a same-frame collision?

THE DEFECT IT EXISTS FOR. TAD's ca65 API holds ONE pending effect and keeps
the LOWER id when a second arrives in the same frame (tad-audio.s:1293). The
rest die before the DRIVER sees them — and the driver is the part with the
good policy (audio-driver.asm:1175-1250): dedup onto the channel already
playing an effect, free channel first, and when both are busy evict by
`sfx_remainingTicks`, the effect with least left to lose. Dropping CPU-side
starves that and substitutes "lower id wins".

THE COLLISION IS FORCED, NOT AWAITED. boss_saucer's tick calls player_fire
before beam_update, so a shot queues `laser` (id 6) and the beam's ignition
queues `beam_fire` (id 3) on the same frame; 3 takes the slot. Waiting for
that to happen by luck is a flaky test, so the drive READS GAME STATE and
times the input: US_BEAM_STATE == TELE with US_BEAM_TIMER == 1 means the beam
ignites next frame, and US_FIRE_TIMER == 0 means A will spawn a shot on it.
Same "drive from the observed state" discipline as the room tests.

TEST SURFACE. Two independent readings, deliberately:
  * the S-DSP voices — PER VOICE, not "any voice sounding". A second cue keying
    on the OTHER SFX channel while the first still rings leaves an any-voice
    boolean high, so the onset is invisible. That mistake produced a false
    "a cue was still lost" reading while this was being built.
  * the queue's own counters at ES_SFX_QUEUE — delivered / dropped-full /
    dropped-stale. These exist so the policy is OBSERVABLE at all: before the
    queue, a lost cue left no trace anywhere.
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

WR, DSP = MemoryType.SnesWorkRam, MemoryType.SpcDspRegisters
ROM = SUPERFORGE / "build" / "boss_saucer.sfc"

_SYMS = {p["sym"]: p for p in json.loads(
    (SUPERFORGE / "build" / "sau" / "symbol_map.json").read_text())["globals"]}
Q = _SYMS["ES_SFX_QUEUE"]["start"]          # asked for, never transcribed
Q_CNT, Q_DFULL, Q_DSTALE, Q_DELIV = Q + 13, Q + 14, Q + 15, Q + 16

# arena.asm's scene-scoped words and saucer.inc's constants.
BEAM_STATE, BEAM_TIMER, FIRE_TIMER = 0x3F, 0x41, 0x49
TELE, FIRE_GAP = 1, 8
SAW = 5                                     # instrument order: laser + beam_fire
SFX_VOICES = (6, 7)


@pytest.fixture(scope="module")
def boot_state():
    """The ring's 17 bytes a few frames after power-on, before any cue."""
    assert ROM.exists(), f"{ROM} not built — run `make boss_saucer` first"
    r = MesenRunner()
    r.boot_rom(str(ROM), frames=8)
    b = r.read_bytes(WR, Q, 17)
    r.stop()
    return b


def test_the_ring_boots_empty(boot_state):
    """POWER-ON FIDELITY, on a ring rather than a framebuffer.

    The harness boots ROMs with RANDOM RAM on purpose (CLAUDE.md rule 5), so
    every one of these 17 bytes is garbage until `sf_sfx_reset` runs. An
    unreset count makes the pump drain entries that were never queued and the
    enqueue path reject real ones as "full", from the very first frame.

    Four bytes are asserted rather than one so a lucky seed cannot pass this:
    a garbage count, head or counter would have to land on a valid empty state
    in all of them at once. boss_saucer queues nothing during boot, so the
    healthy reading is exactly zero — measured, not assumed.
    """
    head, cnt, dfull, dstale, deliv = (boot_state[12], boot_state[13],
                                       boot_state[14], boot_state[15],
                                       boot_state[16])
    assert cnt == 0, f"the ring boots holding {cnt} entr(y|ies) of garbage"
    assert head < 4, f"head boots at {head}, outside the 4-entry ring"
    assert (dfull, dstale, deliv) == (0, 0, 0), (
        f"the counters boot dirty: full={dfull} stale={dstale} deliv={deliv}")


@pytest.fixture(scope="module")
def collision():
    """Force ONE same-frame collision and record both surfaces across it."""
    assert ROM.exists(), f"{ROM} not built — run `make boss_saucer` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(ROM), frames=200)
    u16 = lambda a: int.from_bytes(r.read_bytes(WR, a, 2), "little")   # noqa: E731
    u8 = lambda a: r.read_bytes(WR, a, 1)[0]                           # noqa: E731
    ctrs = lambda: dict(cnt=u8(Q_CNT), deliv=u8(Q_DELIV),              # noqa: E731
                        dfull=u8(Q_DFULL), dstale=u8(Q_DSTALE))

    out = {"aligned": False}
    for _ in range(2500):
        r.frame_step(1)
        if (u16(BEAM_STATE) == TELE and u16(BEAM_TIMER) == 1
                and u16(FIRE_TIMER) == 0):
            out["before"] = ctrs()
            r.frame_step(1, a=True)              # the ignition AND a shot
            out["spawned"] = u16(FIRE_TIMER) == FIRE_GAP
            onsets, prev, evol = 0, {v: False for v in SFX_VOICES}, []
            for _ in range(20):
                r.frame_step(1)
                d = r.read_bytes(DSP, 0, 128)
                for v in SFX_VOICES:
                    cur = d[v * 0x10 + 8] > 0 and d[v * 0x10 + 4] == SAW
                    if cur and not prev[v]:
                        onsets += 1
                    prev[v] = cur
                evol.append(d[0x2C])
            out.update(aligned=True, onsets=onsets, evol_max=max(evol),
                       after=ctrs())
            break
    r.stop()
    assert out["aligned"], (
        "never reached a frame where the beam ignites AND a shot spawns — the "
        "drive geometry has rotted, and every case below would pass vacuously")
    return out


def test_the_collision_actually_happened(collision):
    """The precondition, asserted first so nothing below can pass vacuously."""
    assert collision["spawned"], "no bullet spawned on the ignition frame"
    assert collision["evol_max"] >= 70, (
        "beam_fire never executed — EVOL stayed dry, so the beam cue did not "
        "reach the driver and this is not the collision case at all")


def test_both_cues_reach_the_driver(collision):
    """The headline: a real bullet is no longer silent.

    Before the queue this read 1 — the laser was discarded unseen while the
    bullet flew, hit and killed. The queue holds it and delivers it on a later
    frame, so both cues sound.
    """
    d = collision["after"]["deliv"] - collision["before"]["deliv"]
    assert d >= 2, (
        f"only {d} cue(s) delivered across the collision — the second was "
        f"dropped before the driver saw it")


def test_both_cues_are_audible(collision):
    """...and the DSP agrees, independently of the queue's own bookkeeping.

    Per voice, because a second cue keying on the other SFX channel while the
    first still rings leaves an any-voice boolean high.
    """
    assert collision["onsets"] >= 2, (
        f"{collision['onsets']} saw onset(s) on the SFX channels — the second "
        f"cue never sounded even if the queue believes it was delivered")


def test_nothing_was_lost_to_overflow_or_age(collision):
    """A two-deep burst must cost nothing: the ring holds four and ages at 3.

    This is the case that would catch a ring sized or aged too tightly — the
    counters make the loss visible where nothing could see it before.
    """
    full = collision["after"]["dfull"] - collision["before"]["dfull"]
    stale = collision["after"]["dstale"] - collision["before"]["dstale"]
    assert full == 0, f"{full} cue(s) dropped for a full ring on a 2-deep burst"
    assert stale == 0, f"{stale} cue(s) aged out on a 2-deep burst"


def test_the_ring_drains(collision):
    """It must not leak: everything queued is gone by the end of the window."""
    assert collision["after"]["cnt"] == 0, (
        f"{collision['after']['cnt']} entr(y|ies) still held 20 frames after "
        f"the burst — the pump is not draining")
