"""The parked-recording guard in vendor/mesen_runner.py.

start_audio_recording() on a PARKED machine (debug_break/frame_step) used to
record silence — the emulation thread is stopped, so the WAV fills with
nothing. It bit three separate tests in one change. The guard raises instead,
naming the fix (debug_resume() first), and consults the emulator's own
IsExecutionStopped() rather than the _frame_stepping flag, because the flag
reads stale-True on a free-running machine after a timed-out run_to_break (the
friction log "DX pass (2026-07-30)").

Test surface (CLAUDE.md rule 2): the output regions read are the raised
RuntimeError, the recorder state (is_recording_audio) plus the ABSENCE of a
WAV file in the parked case, and the WAV file's sample frames on disk in the
resumed case — never a proxy variable. State cycle driven, on the real
emulator (no mocks): free-run -> parked (debug_break) -> refused -> resumed
(debug_resume) -> recording -> stopped -> non-empty WAV; plus the documented
stale-flag state (_frame_stepping True while free-running), which must NOT
refuse.

Each test establishes its own park/run precondition, so the file survives
single-test selection.
"""
import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner  # noqa: E402

ROM = SUPERFORGE / "build" / "toy.sfc"


@pytest.fixture(scope="module")
def runner():
    # Build the cheapest ROM ourselves so the file runs standalone. MAKEFLAGS
    # cleared per the test_make_gates.py pattern — under `make test` this is
    # a recursive make and must not inherit the outer invocation's flags.
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    r = subprocess.run(["make", "toy"], cwd=SUPERFORGE, capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"make toy failed:\n{r.stdout}\n{r.stderr}"

    # Wall-clock waits are DELIBERATE in this module and stay.
    # It is an audio runner, so MesenRunner keeps it throttled to 60 fps —
    # wall and emulated time coincide by construction — and what the
    # assertions read is a real-time WAV. Same carve-out as
    # tests/test_slice_b_audio.py:17-19.
    rn = MesenRunner(enable_audio=True)
    # WALL-CLOCK: ok — audio carve-out (AGENTS.md). An enable_audio runner
    # is throttled to 60 fps, so wall and emulated time coincide by
    # construction, and this module's whole subject is a real-time WAV.
    rn.load_rom(str(ROM), run_seconds=1.0)
    yield rn
    try:
        rn.debug_resume()          # never hand a parked machine to stop()
    finally:
        rn.stop()


def _wav_frames(path):
    w = wave.open(str(path))
    try:
        return w.getnframes()
    finally:
        w.close()


def test_parked_recording_raises_naming_the_fix(runner, tmp_path):
    """Parked machine -> the guard refuses BEFORE the recorder starts.

    The error must name debug_resume() — the message is the fix's
    documentation at the moment of the mistake.
    """
    wav = tmp_path / "parked.wav"
    runner.debug_break()
    with pytest.raises(RuntimeError, match="debug_resume"):
        runner.start_audio_recording(str(wav))
    # Refused means refused: no recorder running, no file on disk. (The old
    # behaviour started a recorder that captured silence until the eventual
    # resume — a WAV that exists but lies.)
    assert not runner.is_recording_audio(), \
        "guard raised but the recorder is running — it refused too late"
    assert not wav.exists(), \
        "guard raised but a WAV file was created — it refused too late"


def test_resumed_recording_captures_samples(runner, tmp_path):
    """debug_resume() -> recording starts cleanly and captures real frames.

    The positive half of the guard's contract: the refusal is specific to
    the parked state, and the documented fix actually yields a non-empty
    capture.
    """
    wav = tmp_path / "resumed.wav"
    runner.debug_break()                   # own precondition: start parked
    runner.debug_resume()                  # the fix the error names
    runner.start_audio_recording(str(wav))
    assert runner.is_recording_audio()
    # WALL-CLOCK: ok — audio carve-out: the assertion counts WAV sample
    # frames, which only exist while real time passes on a throttled core.
    runner.run_frames(30)                  # ~0.5 s of free-running audio
    runner.stop_audio_recording()
    assert wav.exists(), "recording stopped but no WAV on disk"
    frames = _wav_frames(wav)
    assert frames > 0, (
        "recording started on a free-running machine but the WAV holds zero "
        "sample frames — the silence bug in a new coat")


def test_stale_parked_flag_does_not_refuse(runner, tmp_path):
    """The DX-pass trap replayed: _frame_stepping stale-True while the
    machine free-runs (a timed-out run_to_break leaves exactly this state).

    A guard that trusted the flag would refuse this legitimate recording;
    the ground-truth guard (IsExecutionStopped) must let it through and
    capture frames. Planting the private flag is the idiom the shipped tests
    use for this.
    """
    runner.debug_resume()                  # ensure genuinely free-running
    assert not runner._lib.IsExecutionStopped(), \
        "precondition: machine should be free-running here"
    wav = tmp_path / "staleflag.wav"
    runner._frame_stepping = True          # the stale state, planted
    try:
        runner.start_audio_recording(str(wav))
        # WALL-CLOCK: ok — audio carve-out, same as above: a WAV is a
        # recording of real time.
        runner.run_frames(15)
        runner.stop_audio_recording()
    finally:
        runner._frame_stepping = False     # restore the truthful flag
    assert _wav_frames(wav) > 0, (
        "stale-flag recording captured nothing — either the guard consulted "
        "the flag, or recording broke")
