"""Legitimate exceptions, each carrying its reason."""
import time


def test_audio_is_a_recording_of_real_time(runner):
    # WALL-CLOCK: ok — an audio runner is throttled to 60 fps, so wall and
    # emulated time coincide, and what the assertion reads is a real-time WAV.
    runner.run_frames(30)


def test_filesystem_mtime(tmp_path):
    time.sleep(0.01)   # WALL-CLOCK: ok — mtime granularity, not the emulator
    (tmp_path / "a").write_text("x")
