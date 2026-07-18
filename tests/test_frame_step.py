"""Determinism gate for the frame-stepped input harness.

Feature under test: MesenRunner.debug_break / frame_step / debug_resume —
deterministic frame-stepped input (the wall-clock set_input + run_frames
replacement). Driven against the breaker ROM, whose paddle moves an exact
3 px/frame under a held direction and whose ball is a deterministic
billiard once launched.

Test surface (real output, never a proxy):
  - OAM bytes (paddle sprites slots 0-2, ball slot 3) read per frame
  - WRAM debug mirrors $7E:E010..E017 read per frame (supplement)
  - the emulator's own PPU frame counter (step-exactness ground truth)

State cycles exercised: boot -> WAIT -> launch (A) -> PLAY with a
left/right steering script (ball bouncing, paddle both directions,
press AND release); park -> step -> resume -> free-run hand-off.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

PADDLE_SPEED = 3        # px/frame, templates/breaker/main.asm PADDLE_SPEED
FRAME_COUNTER = 0x010C  # engine WRAM frame counter (NMI-incremented)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = BUILD / "breaker.sfc"
    assert p.exists(), f"{p} not built — run `make breaker` first"
    return str(p)


# Scripted per-frame input: idle -> launch -> alternating steering. Every
# frame's full controller state is explicit — this IS the determinism
# contract (frame i always carries exactly this input).
def _script():
    seq = [{}] * 5                              # settle in WAIT
    seq += [dict(a=True)]                       # launch
    seq += [{}] * 4
    for i in range(110):                        # steer while the ball flies
        phase = (i // 15) % 3
        seq.append(dict(right=True) if phase == 0
                   else dict(left=True) if phase == 1 else {})
    return seq


def _scripted_trace(r):
    """Boot the ROM fresh and replay the script, capturing per-frame bytes."""
    r.load_rom(_rom(), run_seconds=0.5)
    trace = []
    with r.frame_stepping():
        for buttons in _script():
            r.frame_step(1, **buttons)
            oam = r.read_bytes(OAM, 0, 16)      # paddle x3 + ball entries
            dbg = r.read_bytes(WR, 0xE010, 8)   # score/balls/bricks/state
            trace.append(bytes(oam) + bytes(dbg))
    return trace


def test_identical_script_gives_byte_identical_traces(runner):
    """Two independent load_rom runs of the same scripted input must
    produce byte-identical per-frame OAM + debug-mirror traces."""
    t1 = _scripted_trace(runner)
    t2 = _scripted_trace(runner)
    assert len(t1) == len(t2) == len(_script())
    for i, (a, b) in enumerate(zip(t1, t2)):
        assert a == b, (
            f"trace diverged at frame {i}:\n  run1: {a.hex(' ')}\n"
            f"  run2: {b.hex(' ')}"
        )
    # the trace must capture real dynamics, not a frozen screen: the ball
    # (OAM slot 3: bytes 12=x, 13=y) visits many positions after launch
    ball_ys = {fr[13] for fr in t1}
    assert len(ball_ys) > 10, f"ball y only visited {sorted(ball_ys)} — static trace"
    # and the steering moved the paddle through a real range both ways
    pad_xs = [fr[0] for fr in t1]
    assert max(pad_xs) - min(pad_xs) > 40, "paddle barely moved under script"


def test_held_direction_advances_exact_per_frame_delta(runner):
    """A held direction must advance the paddle EXACTLY PADDLE_SPEED px on
    every stepped frame (proves the per-frame input latch, not 'roughly
    moved'). Exercises press AND release, both directions."""
    runner.load_rom(_rom(), run_seconds=0.5)
    with runner.frame_stepping():
        runner.frame_step(2, right=True)        # latch settle (1-2 frames)
        xs = []
        for _ in range(10):
            runner.frame_step(1, right=True)
            xs.append(runner.read_bytes(OAM, 0, 1)[0])
        deltas = [b - a for a, b in zip(xs, xs[1:])]
        assert deltas == [PADDLE_SPEED] * 9, f"right deltas {deltas}"

        runner.frame_step(2)                    # release + settle
        for _ in range(3):
            runner.frame_step(1)
            x = runner.read_bytes(OAM, 0, 1)[0]
            assert x == xs[-1] + PADDLE_SPEED or x == xs[-1], \
                "paddle moved with no input held"
        rest = runner.read_bytes(OAM, 0, 1)[0]
        runner.frame_step(1)
        assert runner.read_bytes(OAM, 0, 1)[0] == rest, \
            "paddle still moving after release settled"

        runner.frame_step(2, left=True)         # latch settle
        xs = []
        for _ in range(10):
            runner.frame_step(1, left=True)
            xs.append(runner.read_bytes(OAM, 0, 1)[0])
        deltas = [b - a for a, b in zip(xs, xs[1:])]
        assert deltas == [-PADDLE_SPEED] * 9, f"left deltas {deltas}"


def test_frame_step_count_is_exact(runner):
    """frame_step(n) advances the emulator's PPU frame counter by exactly
    n — for n = 1, a batch, and repeated single steps."""
    runner.load_rom(_rom(), run_seconds=0.5)
    with runner.frame_stepping():
        for n in (1, 7, 60):
            f0 = runner.ppu_frame_count()
            runner.frame_step(n)
            assert runner.ppu_frame_count() - f0 == n
        f0 = runner.ppu_frame_count()
        for _ in range(30):
            runner.frame_step(1)
        assert runner.ppu_frame_count() - f0 == 30
        # the ROM's own NMI frame counter agrees (WRAM, engine-side)
        c0 = runner.read_u16(WR, FRAME_COUNTER)
        runner.frame_step(10)
        assert runner.read_u16(WR, FRAME_COUNTER) - c0 == 10


def test_mixing_paradigm_safety_after_resume(runner):
    """After debug_resume(), the classic wall-clock paradigm (set_input +
    run_frames) must still work on the same runner — the emulator is
    demonstrably free-running and input still lands."""
    runner.load_rom(_rom(), run_seconds=0.5)
    runner.debug_break()
    runner.frame_step(5, right=True)
    runner.debug_resume()

    # free-running again: frames advance with NO stepping involved
    f0 = runner.ppu_frame_count()
    runner.run_frames(15)
    assert runner.ppu_frame_count() - f0 >= 5, \
        "emulator not free-running after debug_resume"

    # wall-clock input still works: paddle moves left under set_input
    x0 = runner.read_bytes(OAM, 0, 1)[0]
    runner.set_input(0, left=True)
    runner.run_frames(20)
    runner.set_input(0)
    runner.run_frames(2)
    x1 = runner.read_bytes(OAM, 0, 1)[0]
    assert x0 - x1 > 25, f"wall-clock input dead after resume ({x0}->{x1})"

    # and the engine frame counter keeps ticking on the wall clock
    c0 = runner.read_u16(WR, FRAME_COUNTER)
    runner.run_frames(10)
    assert runner.read_u16(WR, FRAME_COUNTER) > c0
