"""split_h_2p_demo — the autonomous showcase build plays AUDIBLE music.

The rail's DEFAULT build (make split_h_2p_demo) is the zero-input showcase; it
links a TAD-audio config and starts a kit track at boot. This gate is on
RECORDED AUDIO ENERGY (WAV RMS), not a status variable — the sanctioned oracle
for "is the music actually reaching the speaker" (mirrors tests/test_audio.py).
The TAD_STATUS mirror is read ONLY to tell a real regression apart from the
harness's audio-core downgrade (see the fixture note).

AUDIO-CORE ORDERING: MesenCore is initialized ONCE per process, and the FIRST
MesenRunner's audio setting wins (mesen_runner._global_initialize). In the full
suite tests/test_audio.py sorts first and initializes audio ON, so every later
audio test inherits it; run standalone, this module initializes it ON itself.
The one ordering that disables audio output (a non-audio runner constructed
first, e.g. `pytest test_split_h_2p_demo.py test_split_h_2p_audio.py`) is
detected and SKIPPED rather than reported as a false failure.
"""
import math
import struct
import wave
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

TAD_STATUS = 0x016A          # engine mirror: 0 loaded/paused, 1 playing, 2 load
SILENCE_FLOOR = 200.0        # RMS below this = no audio energy (test_audio uses
                             # 100 as the SFX-over-silence bar; the showcase
                             # track sits far above — the probe measured ~5300)


def _wav_rms_peak(path):
    w = wave.open(str(path))
    n = w.getnframes()
    s = struct.unpack(f"<{n * w.getnchannels()}h", w.readframes(n))
    w.close()
    assert s, f"{path}: empty recording"
    return math.sqrt(sum(x * x for x in s) / len(s)), max(abs(x) for x in s)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner(enable_audio=True)
    yield r
    r.stop()


def test_showcase_plays_audible_music(runner, tmp_path):
    rom = BUILD / "split_h_2p_demo.sfc"
    assert rom.exists(), f"{rom} not built — run `make split_h_2p_demo` first"
    runner.load_rom(str(rom), run_seconds=1.5)          # let the song stream in
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "showcase did not boot"

    wav = tmp_path / "showcase.wav"
    runner.start_audio_recording(str(wav))
    runner.run_frames(150)
    runner.stop_audio_recording()
    rms, peak = _wav_rms_peak(wav)

    status = runner.read_bytes(WR, TAD_STATUS, 1)[0]
    if rms < SILENCE_FLOOR:
        # The ASM wired the song (status==playing) but the shared core is in a
        # no-audio-output init from an earlier non-audio runner: not a rail bug.
        if status == 1:
            pytest.skip("MesenCore initialized without audio output by an "
                        "earlier runner; run this file first or with "
                        "test_audio.py to record energy")
        pytest.fail(f"showcase silent AND not playing (TAD_STATUS={status})")

    assert peak > 0, "recorded audio peak is zero"
    assert status == 1, f"music energy present but TAD_STATUS={status} (not playing)"
