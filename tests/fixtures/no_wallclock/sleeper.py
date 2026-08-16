"""Every wall-clock shape, unoverridden. One finding per rule."""
import time


def test_sleeps(runner):
    time.sleep(0.5)


def test_run_frames(runner):
    runner.run_frames(30)


def test_run_seconds(runner):
    runner.load_rom("build/toy.sfc", run_seconds=2.0)


def test_timeout_s(runner):
    runner.run_to_break(timeout_s=30.0)
