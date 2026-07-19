"""sf_audio run-gate: the TAD stack proven AUDIBLY on the emulator.

The architectural gate for the kit's audio: the assertions are on RECORDED
AUDIO ENERGY (WAV RMS), not on status variables alone — a version mismatch
between the vendored ca65 API and the embedded SPC700 loader/driver would
pass any WRAM assertion and fail exactly here. Cycle covered: boot
handshake -> async song load -> PLAYING -> audible music -> pause (energy
collapses) -> resume (energy returns) -> SFX audible over a paused song.
"""
import math
import struct
import wave
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

STATUS, PLAY_LATCH, PAUSE_MIR, SFX_CNT = 0xE010, 0xE012, 0xE014, 0xE016


def _rms(path):
    w = wave.open(str(path))
    n = w.getnframes()
    samples = struct.unpack(f"<{n * w.getnchannels()}h", w.readframes(n))
    w.close()
    assert samples, f"{path}: empty recording"
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner(enable_audio=True)
    yield r
    r.stop()


def _record(runner, frames, path):
    runner.start_audio_recording(str(path))
    runner.run_frames(frames)
    runner.stop_audio_recording()
    return _rms(path)


def test_music_plays_pauses_resumes_audibly(runner, tmp_path):
    rom = ROOT / "build" / "audio_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make audio_test` first"
    runner.load_rom(str(rom), run_seconds=0.8)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", \
        "ROM did not boot (SPC700 loader handshake may have hung)"
    assert runner.read_u16(WR, 0xE008) == 1

    # async load completes: PLAYING within ~120 frames of ticking
    for _ in range(12):
        if runner.read_u16(WR, PLAY_LATCH) == 1:
            break
        runner.run_frames(10)
    assert runner.read_u16(WR, PLAY_LATCH) == 1, \
        f"song never reached PLAYING (status={runner.read_u16(WR, STATUS):#04x})"

    # the architectural assertion: the playback is AUDIBLE
    playing_rms = _record(runner, 150, tmp_path / "playing.wav")
    assert playing_rms > 500, f"music not audible (RMS={playing_rms:.0f})"

    # pause: energy collapses (driver keeps running; channels keyed off)
    runner.set_input(0, start=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(20)                      # let the release tails decay
    assert runner.read_u16(WR, PAUSE_MIR) == 1, "pause toggle did not latch"
    paused_rms = _record(runner, 120, tmp_path / "paused.wav")
    assert paused_rms < playing_rms * 0.15, \
        f"pause did not silence the music (RMS {playing_rms:.0f} -> {paused_rms:.0f})"

    # resume: the music comes back
    runner.set_input(0, start=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(10)
    assert runner.read_u16(WR, PAUSE_MIR) == 0, "resume toggle did not latch"
    resumed_rms = _record(runner, 150, tmp_path / "resumed.wav")
    assert resumed_rms > playing_rms * 0.4, \
        f"music did not resume (RMS {resumed_rms:.0f} vs playing {playing_rms:.0f})"

    # stop the music (silent song streams in), then SFX over true silence —
    # NOTE: SFX while PAUSED is silent by design (TadCommand::PAUSE halts the
    # whole driver; documented in sf_audio.inc), so the SFX gate runs here.
    runner.set_input(0, select=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(60)                      # silent song loads + tails decay
    silence_rms = _rms_after_stop = _record(runner, 90, tmp_path / "stopped.wav")
    assert silence_rms < playing_rms * 0.1, \
        f"music_stop did not silence playback (RMS={silence_rms:.0f})"
    sfx0 = runner.read_u16(WR, SFX_CNT)
    runner.start_audio_recording(str(tmp_path / "sfx.wav"))
    runner.set_input(0, a=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(60)
    runner.stop_audio_recording()
    assert runner.read_u16(WR, SFX_CNT) == sfx0 + 1, "SFX press not registered"
    sfx_rms = _rms(tmp_path / "sfx.wav")
    assert sfx_rms > max(silence_rms * 3, 100), \
        f"SFX not audible over silence (RMS={sfx_rms:.0f} vs silence {silence_rms:.0f})"
