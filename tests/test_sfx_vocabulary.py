"""The SFX vocabulary, on the hardware that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
a sound effect the rendered output is the S-DSP VOICE:

  * `VxSRCN` says WHICH sample is keyed — the instrument identifies the effect,
    because the queue byte is consumed and reset inside the same frame
    (tad-audio.s:993, `sty Tad_sfxQueue_sfx` / `sty Tad_sfxQueue_pan`) and is
    therefore unreadable at any frame boundary. A test that watched the queue
    would watch $FF forever and pass on a rail that plays nothing.
  * `VxENVX > 0` says the voice is actually SOUNDING. This is the assertion
    that would have caught the sprint's own worst defect: five effects opened
    with a DECREASE-mode GAIN (`E<rate>`), which falls from the envelope's
    current level, and key-on leaves that at zero. They compiled, they queued,
    they keyed on, and ENVX stayed 0 forever. Every "is it audible" case here
    exists because that shipped silently once.
  * `VxVOL_L` / `VxVOL_R` are where PANNING is visible, and they are also how
    the second defect was found: TAD's default audio mode is MONO
    (tad-audio.inc:123), and in mono the driver collapses every channel to
    centre. Before that was fixed, every voice on every rail — music
    included — read VOL_L == VOL_R.

TAD's two SFX channels are DSP voices 6 and 7 (music channels G/H, ducked
while an effect plays), which is the same pair tests/test_slice_b_audio.py
samples for the footstep.

Instrument -> SRCN is the project file's instrument ORDER
(assets/audio/slice_b.terrificaudio): tri_bass 0, square_lead 1, pluck 2,
step 3, bell 4, saw 5. New instruments were APPENDED so these indices are
stable.

Driving is `frame_step` throughout — emulated frames, no host clock. The one
WAV capture carries the audio carve-out with its reason.
"""
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)

TRI_BASS, SQUARE_LEAD, PLUCK, STEP, BELL, SAW = range(6)
NAMES = {TRI_BASS: "tri_bass", SQUARE_LEAD: "square_lead", PLUCK: "pluck",
         STEP: "step", BELL: "bell", SAW: "saw"}


def _voices(r):
    """Every SOUNDING SFX voice this instant, as (srcn, vol_l, vol_r)."""
    d = r.read_bytes(DSP, 0, 128)
    out = []
    for v in SFX_VOICES:
        if d[v * 0x10 + 8] > 0:                      # VxENVX: actually sounding
            out.append((d[v * 0x10 + 4], d[v * 0x10 + 0], d[v * 0x10 + 1]))
    return out


def _collect(r, frames, drive):
    """Drive `frames` emulated frames; return observations and ONSET counts.

    Two cadence signatures come back, and WHICH ONE IS DIAGNOSTIC DEPENDS ON
    THE EFFECT — a distinction this module learned from its own falsification
    run rather than by reasoning:

      onsets     frames where a voice starts sounding that was silent before.
                 Good for a SHORT effect that finishes between firings: an
                 edge-latched cue onsets once per crossing, a per-frame one
                 onsets constantly.
      live       frames where the voice is sounding at all, as a fraction.
                 Good for an effect long enough to still be ringing when it is
                 re-queued. These are one-channel + INTERRUPTIBLE, so a repeat
                 RESTARTS the voice instead of keying a new one — it never goes
                 silent, so ONSETS DO NOT RISE and can even fall. Measured on
                 the rpg footstep: healthy 71 onsets / 19% live, and with the
                 cue moved into the per-frame walk path 44 onsets / 84% live.
                 An onset bound would have called that defect healthy, and did.
    """
    seen, onsets, live, prev = {}, {}, {}, set()
    for i in range(frames):
        drive(r, i)
        sounding = _voices(r)
        cur = {srcn for srcn, _, _ in sounding}
        for srcn, vl, vr in sounding:
            seen.setdefault(srcn, set()).add((vl, vr))
        for srcn in cur:
            live[srcn] = live.get(srcn, 0) + 1
        for srcn in cur - prev:
            onsets[srcn] = onsets.get(srcn, 0) + 1
        prev = cur
    return seen, onsets, {k: v / frames for k, v in live.items()}


def _rms(path):
    w = wave.open(str(path))
    n, ch = w.getnframes(), w.getnchannels()
    s = struct.unpack(f"<{n * ch}h", w.readframes(n))
    w.close()
    assert s, f"{path}: empty recording"
    return math.sqrt(sum(v * v for v in s) / len(s))


def _rom(name):
    p = SUPERFORGE / "build" / f"{name}.sfc"
    assert p.exists(), f"{p} not built — run `make {name}` first"
    return str(p)


# =============================================================================
# shmup — the panned rail: a laser that stays centred, kills that do not
# =============================================================================

@pytest.fixture(scope="module")
def shmup(tmp_path_factory):
    """One boot, two drives: ship pinned LEFT, then pinned RIGHT.

    The kills therefore happen on opposite sides of the screen, which is what
    makes "the explosion is panned to the fighter that died" falsifiable in
    both directions rather than merely "not centred".
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("shmup"), frames=180)
    r.frame_step(3, start=True)                      # title -> play
    r.frame_step(3)
    r.frame_step(90)                                 # fade + enter

    def fire_left(rr, i):
        rr.frame_step(1, a=(i % 6 < 3), left=True)

    def fire_right(rr, i):
        rr.frame_step(1, a=(i % 6 < 3), right=True)

    left_seen, _, _ = _collect(r, 700, fire_left)
    right_seen, _, _ = _collect(r, 700, fire_right)

    tmp = tmp_path_factory.mktemp("sfx_wav")
    wav = tmp / "shmup.wav"
    r.debug_resume()
    r.start_audio_recording(str(wav))
    # WALL-CLOCK: ok — audio carve-out: this IS the recording window. A WAV
    # only accumulates while real time runs, so the RMS below cannot be
    # obtained by stepping emulated frames.
    r.run_frames(120)
    r.stop_audio_recording()
    r.stop()
    return {"left": left_seen, "right": right_seen, "wav": wav}


def test_laser_is_audible(shmup):
    # The gun uses `saw`. Audible means a KEYED voice with a live envelope —
    # the exact reading that was 0 while five effects decayed from silence.
    assert SAW in shmup["left"], \
        f"the laser never voiced; SFX channels carried {shmup['left'].keys()}"


def test_explosion_is_audible(shmup):
    assert STEP in shmup["left"], "no kill ever voiced an explosion"


def test_explosion_pans_to_the_fighter_that_died(shmup):
    # The claim is POSITIONAL, so a single off-centre reading will not do: the
    # same drive pinned to opposite sides must move the balance the other way.
    left = [(l, r) for l, r in shmup["left"][STEP] if l != r]
    right = [(l, r) for l, r in shmup["right"][STEP] if l != r]
    assert left, f"kills on the left were all centred: {shmup['left'][STEP]}"
    assert right, f"kills on the right were all centred: {shmup['right'][STEP]}"
    assert any(l > r for l, r in left), \
        f"ship pinned LEFT never produced a left-weighted explosion: {left}"
    assert any(r > l for l, r in right), \
        f"ship pinned RIGHT never produced a right-weighted explosion: {right}"


def test_unpanned_cue_stays_centred(shmup):
    # The other half of the panning claim, and the one that keeps it honest: a
    # cue queued through the CENTRED entry point must not drift. The laser is
    # queued with Tad_QueueSoundEffect while the explosion beside it is
    # panned, so this also proves the two paths are actually different.
    for side in ("left", "right"):
        for vl, vr in shmup[side][SAW]:
            assert vl == vr, f"the laser is not centred on the {side} drive: " \
                             f"VOL_L={vl} VOL_R={vr}"


def test_rail_is_audible_at_all(shmup):
    assert _rms(shmup["wav"]) > 500, "the shmup records near-silence"


# =============================================================================
# racer — the edge-vs-condition invariant
# =============================================================================

@pytest.fixture(scope="module")
def racer():
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("racer"), frames=200)

    def drive(rr, i):
        # accelerate throughout and swerve off the road four times, so the
        # kart spends long RUNS off the surface rather than clipping it
        rr.frame_step(1, a=True, b=True,
                      left=(200 <= i < 340) or (600 <= i < 740),
                      right=(400 <= i < 540) or (800 <= i < 940),
                      start=(i in (150, 155)))

    seen, onsets, _ = _collect(r, 1000, drive)
    r.stop()
    return {"seen": seen, "onsets": onsets}


def test_skid_is_audible(racer):
    assert STEP in racer["seen"], \
        "the racer never voiced a skid — leaving the road is silent"


def test_pause_confirm_is_audible(racer):
    assert PLUCK in racer["seen"], "START produced no confirm"


def test_skid_fires_on_the_CROSSING_not_every_frame(racer):
    # THE INVARIANT THE LATCH EXISTS FOR. rc_offroad bleeds speed every frame
    # the kart is on grass. Cue the CONDITION and the effect re-keys ~60 times
    # a second and reads as a stutter; cue the EDGE and it onsets once per
    # crossing. The drive above leaves the road four times over 1000 frames
    # and spends hundreds of frames out there, so a condition-triggered cue
    # cannot come in under this bound and an edge-triggered one cannot miss it.
    n = racer["onsets"].get(STEP, 0)
    assert n >= 1, "the skid never onset at all"
    assert n <= 12, \
        f"the skid onset {n} times in 1000 frames — that is the CONDITION " \
        f"firing per frame, not the crossing"


# =============================================================================
# rpg — a footstep whose cadence is the walk's, not the frame's
# =============================================================================

@pytest.fixture(scope="module")
def rpg():
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("rpg"), frames=200)

    def walk(rr, i):
        rr.frame_step(1, right=(i % 200 < 60), down=(60 <= i % 200 < 110),
                      left=(110 <= i % 200 < 160), up=(160 <= i % 200 < 190))

    seen, _, live = _collect(r, 700, walk)
    r.stop()
    return {"seen": seen, "live": live}


def test_rpg_walk_is_audible(rpg):
    assert STEP in rpg["seen"], "the rpg avatar walks in silence"


def test_rpg_footstep_is_one_per_tile_not_one_per_frame(rpg):
    # The cue sits on the tile COMMIT, which arms a slide that read_step waits
    # on, so the footstep rings for a fraction of the walk rather than through
    # it. Asserted as LIVE FRACTION, not onsets: the effect is one-channel and
    # interruptible, so a per-frame cue restarts a voice that is already
    # sounding and the onset count FALLS (measured: 71 healthy, 44 with the
    # cue in the per-frame walk path). The falsification harness caught an
    # onset bound here calling that defect healthy.
    #
    # The bound sits between the two measured states with room on both sides:
    # 19% healthy, 84% with the cue moved into walk_tick's spend path.
    f = rpg["live"].get(STEP, 0.0)
    assert f > 0.0, "the footstep never sounded at all"
    assert f < 0.45, \
        f"the step voice is live on {f:.0%} of walking frames — the cadence " \
        f"is the frame's, not the tile's"
