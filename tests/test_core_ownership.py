"""Who owns the process-global Mesen core, and who is allowed to unload it.

THE FAILURE THIS FILE EXISTS FOR, measured on `main` at 93999d06c411:

    FAILED tests/test_split_h_2p_sprites.py::
           test_every_marker_stands_on_the_world_texel_it_is_drawn_over
    MachineError: RunFramesSync(1) failed: no ROM running

— reproduced deterministically by running gw0's module order from
`make gates XDIST=2` in one process. The victim names itself and had nothing
to do with it. The chain:

  1. `tests/test_wait_primitives.py::booted` is a module-scoped `MesenRunner`
     yield-fixture whose teardown calls `runner.stop()` — the teardown
     AGENTS.md prescribes, done correctly.
  2. `stop()` issues `Stop(0)`, which leaves the core with NO ROM, and leaves
     `_initialized` True — so the call is repeatable, and `__del__` repeats it.
  3. That module's three `pytest.raises(TimeoutError) as e` blocks retain the
     runner through the exceptions' tracebacks (frame <-> traceback is a
     reference cycle), so the module boundary does NOT free it.
  4. The CYCLIC collector frees it later, at whatever allocation point it
     lands on — for that packing, inside `test_split_h_2p_sprites.py`.
  5. `__del__` -> `stop()` -> a second `Stop(0)`, on a core that by then
     belongs to a live lockstep `Machine`. The ROM is gone; the Machine's
     next `advance()` gets rc -1.

conftest's parked-core guard cannot see it, twice over: it asks at MODULE
BOUNDARIES and the damage is mid-module, and it asks `IsExecutionStopped()`,
which a `Stop(0)`ed core answers False — its own comment records that as
deliberately not a finding, because that is what ordinary teardown looks like.

THE FIX these tests pin is `mesen_runner._claim_core()`: every successful load
on either interface takes a ticket, and `stop()` refuses to touch a core whose
ticket has moved on. The shape is the one `Machine` already had for
Machine-vs-Machine ("superseded by a later load"), extended to the other
interface.

Test surface (CLAUDE.md rule 2): the output read is the CORE'S OWN state —
`mesen_runner.core_has_rom()` is `Emulator::IsRunning()`, i.e.
`_console != nullptr`, and the Machine's VRAM bytes and PPU frame counter are
read back across the collection. No handle's bookkeeping flag is asserted on,
which is the point: the bug IS a handle's bookkeeping disagreeing with the
core.
"""
import gc
import sys
import weakref
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

import mesen_runner                                    # noqa: E402
from machine import MachineError, Machine, MemoryType  # noqa: E402
from mesen_runner import MesenRunner                   # noqa: E402

# The cheapest ROM in the tree, and a `make test` prerequisite. Nothing here
# is about what the ROM does — only about whether the core still has one.
ROM = str(SUPERFORGE / "build" / "toy.sfc")

# VRAM offset 0 is a hardware region ORIGIN, the one address that cannot move
# when the allocator repacks (tools/map_lint.py states the carve-out).
VRAM_ORIGIN = 0


def _loaded_runner() -> MesenRunner:
    """A runner that has really loaded a ROM, booted in EMULATED frames."""
    runner = MesenRunner()
    runner.boot_rom(ROM, frames=2)
    return runner


def test_the_owning_runner_still_stops_the_core():
    """The other arm: the guard must not be a constant "never stop"."""
    runner = _loaded_runner()
    assert mesen_runner.core_has_rom(), "boot_rom left no ROM in the core"
    assert runner._core_gen == mesen_runner._core_generation()

    runner.stop()

    assert not mesen_runner.core_has_rom(), (
        "an owning runner's stop() must still reach the core — if this is "
        "True the ownership guard has disarmed stop() outright")


def test_a_superseded_runner_leaves_the_core_alone():
    """The guard's claim, stated directly and asked of the core."""
    runner = _loaded_runner()

    with Machine(ROM) as m:                 # the Machine takes the ticket
        m.advance(1)
        assert runner._core_gen != mesen_runner._core_generation()
        runner.stop()                       # superseded: must be inert
        assert mesen_runner.core_has_rom(), (
            "a superseded runner's stop() unloaded the Machine's ROM")
        m.advance(1)                        # and the Machine still drives it


def test_a_cycle_retained_runner_cannot_unload_a_live_machines_rom():
    """The measured failure, end to end and deterministic.

    The reference cycle here stands in for the `pytest.raises` tracebacks
    that produced it in the wild: what matters is only that refcounting
    cannot free the runner, so the collector is what runs `__del__`, at a
    point the runner's own module no longer controls.
    """
    runner = _loaded_runner()
    runner.stop()                           # the blessed teardown, done right
    alive = weakref.ref(runner)
    cycle = [runner]
    cycle.append(cycle)                     # refcounting cannot free this
    del runner

    with Machine(ROM) as m:
        m.advance(30)
        assert alive() is not None, (
            "the runner was freed by refcount — this test would then prove "
            "nothing about the collector's timing")
        frame = m.ppu_frame_count()
        vram = m.read_bytes(MemoryType.SnesVideoRam, VRAM_ORIGIN, 64)

        del cycle
        gc.collect()                        # __del__ -> stop() runs HERE
        assert alive() is None, "the cycle was not collected; nothing was proved"

        m.advance(1)                        # this is where the red landed
        assert m.ppu_frame_count() == frame + 1
        assert m.read_bytes(MemoryType.SnesVideoRam, VRAM_ORIGIN, 64) == vram


def test_a_machine_whose_ticket_moved_says_so_instead_of_reading_on():
    """The same question asked in the other direction.

    `Machine._current` only tracks Machine-vs-Machine. A `MesenRunner` load
    under a live Machine replaces the ROM without disturbing it, and every
    read from that handle would then describe the runner's cartridge — the
    silent version of this bug. The ticket makes it a named error.

    The ticket is moved here directly rather than by driving a real
    `MesenRunner.load_rom` under the live Machine. That path does reach this
    guard (measured), but it also wedges the runner — a Machine holds the
    core parked, so the runner's new ROM loads and then does not run, and
    `boot_rom` spends the stall guard's 30 s saying so. That is the runner
    side's own loud failure and a different subject; what is asserted here
    is that the Machine refuses to keep reading once the ticket has moved.
    `_claim_core()` is not a stand-in for a load, it is what a load calls —
    and `test_the_owning_runner_still_stops_the_core` pins that a real load
    is what moves it.
    """
    m = Machine(ROM)
    m.advance(1)

    mesen_runner._claim_core()              # what any other load would do

    with pytest.raises(MachineError) as excinfo:
        m.advance(1)
    assert "MesenRunner loaded a ROM" in str(excinfo.value)

    m.close()                               # teardown never consults the ticket
