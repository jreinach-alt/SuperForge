"""The measured flake: a read whose only placement in time is a wall sleep.

Free-running, so what `read_bytes` returns is a function of host load. The
same shape captured 58% stale frames under 6 CPU burners.
"""


def test_free_run_read(runner):
    runner.boot_rom("build/toy.sfc", frames=60)
    runner.run_frames(30)
    return runner.read_bytes(0, 0x1000, 16)


def test_parked_read_is_fine(runner):
    runner.boot_rom("build/toy.sfc", frames=60)
    runner.run_frames(30)
    runner.debug_break()
    return runner.read_bytes(0, 0x1000, 16)


def test_a_path_read_is_not_an_emulator_read(runner, tmp_path):
    runner.run_frames(30)
    return (tmp_path / "shot.png").read_bytes()
