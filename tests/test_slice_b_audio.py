"""this slice — "the sound of a place": the ROM-level audio surfaces.

Test surface, per CLAUDE.md rule 2 — rendered output, never a proxy. For
audio the rendered output is SPC-side hardware state and captured sound:

  * SPC RAM bytes (MemoryType.SpcRam) against the checked-in export blob —
    the boot contract / upload path.
  * S-DSP registers (MemoryType.SpcDspRegisters) — the per-room echo state,
    driven through the FULL A -> B -> A cycle, never a snapshot.
  * The SPC-side songTickCounter (ARAM $0003, u16 — audio-driver.asm:89 at
    the pin: third zeropage byte after zpTmpWord+zpTmp3) — persistence.
  * WAV captures — audibility, and the user-audible room difference.

The allocator-level surfaces (the spc/APUIO refusals) are
tests/test_spc_claim.py; the BytesClaim pin is tests/test_bytes_pin.py.

Input driving uses frame_step (deterministic, the mz_drive pattern); the
WAV captures use wall-clock run_frames because audio recording is
real-time by nature (the run-gate precedent).
"""
import json
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

SPC, WR, DSP = MemoryType.SpcRam, MemoryType.SnesWorkRam, MemoryType.SpcDspRegisters

ROM = SUPERFORGE / "build" / "room.sfc"
BLOB = (SUPERFORGE / "assets" / "audio" / "export" / "tad_audio_data.bin").read_bytes()
SYMS = {p["sym"]: p for p in json.loads(
    (SUPERFORGE / "build" / "rm" / "symbol_map.json").read_text())["globals"]}

# tad-audio.s .bss layout at the pin: Tad_flags +0, Tad_audioMode +1,
# TadPrivate_state +2 (the loader/driver state machine that gates the
# mailbox protocol).
TAD_STATE_ADDR = SYMS["ES_TAD_BSS"]["start"] + 2
STATE_PLAYING = 0x82                 # TadState::PLAYING (tad-audio.s:339)

# Generated export layout (assets/audio/export/tad_audio_data.asm):
# loader at blob+0 (116 B), driver at +116 (3218 B), data table at +3334 —
# 2 u24 entries + u16 footer, offsets measured from the SEGMENT start,
# which is 51 bytes of LoadAudioData code before the blob.
LOADER, DRIVER_OFF, DRIVER_SIZE, TABLE, CODE = 116, 116, 3218, 3334, 51
SONG_TICK = 0x0003                   # songTickCounter, driver zeropage

# The song's room-A echo header vs room_b_ambience's values
# (assets/audio/mml/slice_b_song.mml + sound-effects.txt).
ROOM_A = dict(evol=12, efb=24)
ROOM_B = dict(evol=70, efb=96)
EDL_CONST, ESA_CONST = 8, 0xC0       # 128 ms; $10000 - 8*2KB = $C000

# 'step' is instrument 3 in the project (tri_bass, square_lead, pluck, step)
STEP_SRCN = 3


def _u24(b, o):
    return b[o] | b[o + 1] << 8 | b[o + 2] << 16


def _rms(path):
    w = wave.open(str(path))
    n = w.getnframes()
    samples = struct.unpack(f"<{n * w.getnchannels()}h", w.readframes(n))
    w.close()
    assert samples, f"{path}: empty recording"
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _echo(r):
    d = r.read_bytes(DSP, 0, 128)
    return dict(evol_l=d[0x2C], evol_r=d[0x3C], efb=d[0x0D],
                edl=d[0x7D], esa=d[0x6D])


def _tick(r):
    b = r.read_bytes(SPC, SONG_TICK, 2)
    return b[0] | b[1] << 8


def _tad_state(r):
    return r.read_bytes(WR, TAD_STATE_ADDR, 1)[0]


def _press(r, btn):
    r.frame_step(3, **{btn: True})
    r.frame_step(3)


# The song loop is 8 bars of 4/4 at the default #Zenlen (whole note = 96
# ticks) = 768 ticks, and its last half-bar (ticks 720..767) is the composed
# all-channels rest — the reverb-tail window (assets/audio/mml/
# slice_b_song.mml; the bass already rests from tick ~696). Aligning both
# rooms' tail captures to the SAME musical window via the SPC-side tick
# counter is what makes the A/B comparison apples-to-apples: unaligned
# whole-mix RMS measured a 2% difference (musical phase swamps the echo),
# and a mod-384 alignment landed the two rooms on OPPOSITE halves of the
# loop — one mid-music, one resting (both found empirically here).
LOOP_TICKS, REST_ALIGN = 768, 716


def _capture_rest_tail(r, path):
    for _ in range(800):
        if REST_ALIGN <= (_tick(r) % LOOP_TICKS) < REST_ALIGN + 4:
            break
        r.frame_step(2)
    else:
        pytest.fail("never aligned to the song's rest window")
    r.debug_resume()
    r.start_audio_recording(str(path))
    # WALL-CLOCK: ok — audio carve-out (AGENTS.md): the RMS this returns
    # is computed off a WAV, which only accumulates while real time runs.
    r.run_frames(26)                         # ~24 ticks: the rest half-bar
    r.stop_audio_recording()
    return _rms(path)


def _wait_playing(r, max_steps=80):
    for _ in range(max_steps):
        if _tad_state(r) == STATE_PLAYING:
            return
        r.frame_step(10)
    pytest.fail(f"song never reached PLAYING (state={_tad_state(r):#04x})")


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    """Drive boot -> title -> room A -> room B -> room A once; snapshot every
    stage. One journey, many assertions — the transitions are wall-clock
    expensive and the stages are causally ordered anyway."""
    assert ROM.exists(), f"{ROM} not built — run `make room` first"
    tmp = tmp_path_factory.mktemp("slice_b_wav")
    r = MesenRunner(enable_audio=True)
    j = {"stages": {}}

    def snap(name):
        j["stages"][name] = dict(echo=_echo(r), tick=_tick(r),
                                 state=_tad_state(r))

    # The BOOT is not part of the audio carve-out — nothing is recording
    # yet, so it gets an emulated-frame budget like every other boot.
    r.boot_rom(str(ROM), frames=120)
    _wait_playing(r)
    snap("title")
    j["spc_after_boot"] = r.read_bytes(SPC, 0, 0x8000)

    _press(r, "start")                       # title -> room A
    r.frame_step(60)                         # fade + enter + fade-in
    snap("room_a")
    # WAV capture needs FREE-RUNNING emulation — frame_step leaves the
    # machine parked, and a parked machine records silence (found the hard
    # way; debug_resume is the documented hand-off).
    r.debug_resume()
    r.start_audio_recording(str(tmp / "room_a.wav"))
    # WALL-CLOCK: ok — audio carve-out: this IS the recording window.
    r.run_frames(180)
    r.stop_audio_recording()
    j["wav_a"] = tmp / "room_a.wav"
    j["rest_a"] = _capture_rest_tail(r, tmp / "rest_a.wav")

    # walk east to the wall, sampling the SFX channels for the footstep
    sfx_hits = 0
    for _ in range(80):
        r.frame_step(1, right=True)
        d = r.read_bytes(DSP, 0, 128)
        for v in (6, 7):                     # TAD's 2 SFX channels
            if d[v * 0x10 + 4] == STEP_SRCN and d[v * 0x10 + 8] > 0:
                sfx_hits += 1                # VxSRCN == step && VxENVX > 0
                break
    j["footstep_frames"] = sfx_hits
    # Wall silence: by frame 56 of the walk the hero is pinned
    # against the east wall (spawn x=120, wall at RM_HI_X=232, 2 px/frame),
    # so the walk loop's tail is already motionless. KEEP HOLDING right —
    # an unbroken hold, so no press edge fires the door — and count the same
    # voice-6/7 step signature: rm_move's clamp comparison means pushing a
    # wall is not motion, and the footstep must stay silent.
    wall_hits = 0
    for _ in range(20):
        r.frame_step(1, right=True)
        d = r.read_bytes(DSP, 0, 128)
        for v in (6, 7):
            if d[v * 0x10 + 4] == STEP_SRCN and d[v * 0x10 + 8] > 0:
                wall_hits += 1
                break
    j["wall_hits"] = wall_hits
    r.frame_step(3)
    _press(r, "right")                       # east door -> room B
    r.frame_step(70)
    snap("room_b")
    r.frame_step(30)                         # separate instants, same room
    j["tick_b_late"] = _tick(r)
    r.debug_resume()
    r.start_audio_recording(str(tmp / "room_b.wav"))
    # WALL-CLOCK: ok — audio carve-out: this IS the recording window.
    r.run_frames(180)
    r.stop_audio_recording()
    j["wav_b"] = tmp / "room_b.wav"
    j["rest_b"] = _capture_rest_tail(r, tmp / "rest_b.wav")

    # Return west: the cavern SPAWNS one step from the west wall (x=10,
    # wall at 8), so a single fresh LEFT press both reaches the wall and
    # fires the door edge in the same tick — a long held walk here is a
    # trap: its FIRST frame fires the door, and the remaining frames walk
    # in room A instead (found by a falsification pass, which caught
    # exactly that drive-geometry rot making a later leg vacuous).
    r.frame_step(3)
    _press(r, "left")                        # west door -> room A
    r.frame_step(70)
    snap("room_a_again")

    # the exact case: leave for the title
    # FROM THE CAVERN — the wet room — and the title must reset to the dry
    # boot baseline rather than inherit the cavern's echo. Returning from
    # room A would pass even without the fix (A is already dry), so the leg
    # re-enters the cavern first. 115 held frames reach the east wall from
    # ANY room-A position (8 + 230 and 120 + 230 both clamp to 232), so
    # this leg cannot silently under-walk; the room_b_revisit snapshot is
    # the wet PRECONDITION asserted first — if the drive ever
    # fails to reach the cavern again, the test fails loudly on the
    # precondition instead of passing vacuously on an already-dry title.
    r.frame_step(115, right=True)            # east wall from anywhere
    r.frame_step(3)
    _press(r, "right")                       # -> room B
    r.frame_step(70)
    snap("room_b_revisit")
    _press(r, "start")                       # cavern -> title
    r.frame_step(60)
    snap("title_return")

    r.stop()
    return j


# -- boot contract: the upload path, destination-region bytes ----------------

def test_boot_contract_spc_upload(journey):
    spc = journey["spc_after_boot"]
    # Loader and driver are byte-faithful apart from their own RUNTIME state
    # (the loader's spinlock byte, the driver's current-song patches) —
    # measured at 2 bytes each; tolerate 4 so an upstream point-fix does not
    # false-fail, while a wrong/corrupt upload (hundreds of diffs) still does.
    ldr = sum(1 for i in range(LOADER)
              if spc[0x200 + i] != BLOB[i])
    drv = sum(1 for i in range(DRIVER_SIZE)
              if spc[0x274 + i] != BLOB[DRIVER_OFF + i])
    assert ldr <= 4, f"loader image diverges in {ldr}/116 bytes"
    assert drv <= 4, f"driver image diverges in {drv}/{DRIVER_SIZE} bytes"
    # Common audio data (samples, SFX sequence data, instruments) must be EXACT —
    # it is never self-modified, and it is the region the echo buffer would
    # chew if the exclusivity story were wrong.
    t0, t1 = _u24(BLOB, TABLE), _u24(BLOB, TABLE + 3)
    cd = BLOB[t0 - CODE:t1 - CODE]
    assert spc[0x10E8:0x10E8 + len(cd)] == cd, \
        "common audio data at $10E8 does not match the export blob"


# -- reverb: the full room cycle, DSP registers ------------------------------

def test_reverb_cycle_a_b_a(journey):
    a = journey["stages"]["room_a"]["echo"]
    b = journey["stages"]["room_b"]["echo"]
    a2 = journey["stages"]["room_a_again"]["echo"]
    for side in ("evol_l", "evol_r"):
        assert a[side] == ROOM_A["evol"], f"room A {side}={a[side]}"
        assert b[side] == ROOM_B["evol"], f"room B {side}={b[side]}"
        assert a2[side] == ROOM_A["evol"], f"room A(return) {side}={a2[side]}"
    assert a["efb"] == ROOM_A["efb"] and b["efb"] == ROOM_B["efb"] \
        and a2["efb"] == ROOM_A["efb"]


def test_echo_buffer_constant_across_rooms(journey):
    # The delay/buffer must NEVER move (constant-EDL design: the pin's
    # compiler refuses set_echo_delay in SFX, and a stable buffer removes
    # the \\edl glitch class) — ESA/EDL identical at every stage.
    for name, s in journey["stages"].items():
        assert s["echo"]["edl"] == EDL_CONST, f"{name}: EDL {s['echo']['edl']}"
        assert s["echo"]["esa"] == ESA_CONST, f"{name}: ESA {s['echo']['esa']:#x}"


# -- persistence: the song survives both transitions -------------------------

def test_song_persists_across_transitions(journey):
    st = journey["stages"]
    order = ["title", "room_a", "room_b", "room_a_again"]
    # Never re-enters a loader state at any sampled stage...
    for name in order:
        assert st[name]["state"] == STATE_PLAYING, \
            f"{name}: TadPrivate_state={st[name]['state']:#04x} != PLAYING"
    # ...and the SPC-side song position advances monotonically through the
    # whole journey (a reload would restart the counter near zero).
    ticks = [st[n]["tick"] for n in order]
    assert all(b > a for a, b in zip(ticks, ticks[1:])), \
        f"songTickCounter not monotonic across stages: {ticks}"
    assert journey["tick_b_late"] > st["room_b"]["tick"]


# -- audibility: captured sound, and the rooms audibly differ ----------------

def test_music_audible_in_both_rooms(journey):
    rms_a, rms_b = _rms(journey["wav_a"]), _rms(journey["wav_b"])
    assert rms_a > 500, f"room A not audible (RMS={rms_a:.0f})"
    assert rms_b > 500, f"room B not audible (RMS={rms_b:.0f})"


def test_rooms_audibly_differ(journey):
    # The user-audible invariant: when the music rests, the cavern RINGS and
    # the room does not. Both captures are tick-aligned to the same composed
    # rest half-bar, so the only difference between them is the echo state —
    # EVOL 70/EFB 96 regenerating a 128 ms tail vs 12/24 dying fast. The
    # margin sits far below the observed ratio (calibrated at introduction)
    # so capture-start jitter cannot flip the verdict.
    rest_a, rest_b = journey["rest_a"], journey["rest_b"]
    assert rest_b > rest_a * 1.8, \
        f"cavern tail does not ring: rest RMS A={rest_a:.0f} B={rest_b:.0f}"


# -- the footstep: an ordinary SFX under music ------------------

def test_footstep_plays_while_walking(journey):
    # Sampled per-frame during the walk east: a TAD SFX channel (6 or 7)
    # must show the step instrument keyed with a live envelope — the SFX
    # surface is the DSP voice, not a queue variable.
    assert journey["footstep_frames"] >= 3, \
        f"step instrument never live on an SFX channel " \
        f"({journey['footstep_frames']} frames)"


def test_footstep_silent_pinned_at_wall(journey):
    # The other half of the footstep invariant: the step fires
    # on REAL MOTION only. Holding right while pinned against the east wall
    # moves nothing (rm_move's clamp comparison eats the input), so across
    # 20 held frames the step instrument must never voice on an SFX channel.
    # Same surface as the walking test: DSP voices, not a queue variable.
    assert journey["wall_hits"] == 0, \
        f"step instrument voiced {journey['wall_hits']} frame(s) while " \
        f"pinned at the wall — footstep must fire on real motion only"


# -- the title resets to the boot baseline (fixed on review) ----------

def test_title_resets_acoustics_after_cavern(journey):
    # PRECONDITION first: the revisit leg really reached the wet cavern —
    # without this, a drive-geometry slip leaves the journey in dry room A
    # and the title assertion passes without exercising the fix at all
    # (exactly what the falsification pass caught in this test's first
    # version). A vacuous pass is now a loud precondition failure.
    b = journey["stages"]["room_b_revisit"]["echo"]
    assert b["evol_l"] == ROOM_B["evol"] and b["efb"] == ROOM_B["efb"], \
        f"revisit leg never reached the wet cavern (echo={b}) — drive bug"
    # The invariant: exiting the WET room to the title must not leak the
    # cavern's echo under the menu — title enter queues the dry ambience.
    t = journey["stages"]["title_return"]["echo"]
    for side in ("evol_l", "evol_r"):
        assert t[side] == ROOM_A["evol"], \
            f"title inherited the cavern: {side}={t[side]}"
    assert t["efb"] == ROOM_A["efb"], f"title inherited the cavern: efb={t['efb']}"
    assert journey["stages"]["title_return"]["state"] == STATE_PLAYING
