"""A module with no wall-clock coupling at all — the control arm.

Everything here waits in EMULATED frames or reads a parked core.
"""


def test_reads_a_parked_core(runner):
    runner.boot_rom("build/toy.sfc", frames=120)
    with runner.frame_stepping():
        runner.frame_step(4)
        assert runner.read_bytes(0, 0x0000, 4) == b"SFOK"


def test_waits_in_emulated_frames(runner):
    runner.boot_rom("build/toy.sfc", frames=90)
    runner.wait_frames(30)
    runner.wait_until(lambda: True, max_frames=60)
    runner.debug_break()
    runner.take_screenshot("/tmp/x.png")
