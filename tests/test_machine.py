"""The Machine substrate's own test surface.

What is under test here is the LOCKSTEP HARNESS, not a game — so the output
regions are the machine's own observables: the PPU's frame counter and
scanline (the clock every exactness claim is against), the four volatile
memory regions at the power-on park and after driven runs (the seed claim),
WRAM after divergent pad scripts (the input-latch claim), and the PNG bytes
of parked captures (the capture claim). Every claim is exercised as a cycle
— multiple advances, multiple loads, both equal and differing controls — and
the two headline proofs are the ones the spec demands verbatim:

  * SYNCHRONY (§1): >= 300 synchronous advances under >= 3x CPU
    oversubscription, every one landing on exactly the requested frame at
    the canonical scanline, none returning early, none hanging. The legacy
    lost-wakeup/overshoot machinery this replaces was probabilistic; this
    loop is the demonstration that the guarded arm makes it structural.
  * SEED DETERMINISM (§2): same seed -> bit-identical WRAM/VRAM/CGRAM/OAM
    across fresh loads, at power-on AND after a driven run; different seed
    -> differing power-on bytes (the sensitivity control that proves the
    comparison could fail).

Wall-clock note (docs/45): the burners are subprocess ORCHESTRATION (spawned
and killed by PID), not a timing surface; nothing here waits on host time or
calibrates a verdict against it. The machine is parked at every read.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MachineError, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "microzero.sfc"

W, V, C, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesCgRam, MemoryType.SnesSpriteRam)

# One drive script used by every replay comparison below, long enough to
# cross state (microzero's car accelerates and steers under right+B).
DRIVE = ((60, {"right": True, "b": True}), (30, {"b": True}), (12, None))


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"make microzero failed rc={r.returncode}:\n{r.stdout}\n{r.stderr}")
    yield


@pytest.fixture(autouse=True)
def hand_back_the_core():
    """Whatever machines a test builds, the module may not leak a park."""
    yield
    Machine.close_current()


def _drive(m):
    for frames, pad1 in DRIVE:
        m.advance(frames, pad1=pad1)
    return m


def _regions(m):
    return {mt: m.read_bytes(mt, 0, m.get_memory_size(mt))
            for mt in (W, V, C, O)}


# ---------------------------------------------------------------------------
# exactness
# ---------------------------------------------------------------------------
def test_advance_lands_on_the_exact_frame_every_time():
    """The counter the machine itself keeps, after every advance size that
    exercises both the bulk phase and the exact-walk phase (1 crosses
    neither, 2 walks only, 17 chunks + walks, 90 chunks repeatedly)."""
    m = Machine(ROM)
    assert m.ppu_frame_count() == 0, "LoadRomParked must land at frame 0"
    expected = 0
    for n in (1, 2, 17, 90, 3, 16, 1):
        m.advance(n)
        expected += n
        assert m.ppu_frame_count() == expected, (
            f"advance({n}) landed on {m.ppu_frame_count()}, wanted {expected}")


def test_a_superseded_machine_refuses_instead_of_lying():
    """Two machines in one process share one core; the older handle must
    raise, not silently read the newer machine's state."""
    a = Machine(ROM)
    a.advance(5)
    b = Machine(ROM)
    with pytest.raises(MachineError, match="superseded"):
        a.advance(1)
    with pytest.raises(MachineError, match="superseded"):
        a.read_bytes(W, 0, 4)
    b.advance(3)
    assert b.ppu_frame_count() == 3


# ---------------------------------------------------------------------------
# seed determinism
# ---------------------------------------------------------------------------
def test_same_seed_is_bit_identical_across_loads_and_a_driven_run(tmp_path):
    """WRAM/VRAM/CGRAM/OAM, whole regions, at the power-on park AND after
    the drive script — two fresh loads of the same seed."""
    m1 = Machine(ROM, seed=0xC0FFEE)
    poweron1 = _regions(m1)
    after1 = _regions(_drive(m1))
    shot1 = Path(m1.take_screenshot(tmp_path / "s1.png")).read_bytes()

    m2 = Machine(ROM, seed=0xC0FFEE)
    poweron2 = _regions(m2)
    after2 = _regions(_drive(m2))
    shot2 = Path(m2.take_screenshot(tmp_path / "s2.png")).read_bytes()

    for mt in (W, V, C, O):
        assert poweron1[mt] == poweron2[mt], (
            f"{mt!r}: same-seed POWER-ON bytes differ — the seed is not "
            f"reaching the randomizer")
        assert after1[mt] == after2[mt], (
            f"{mt!r}: same-seed post-drive bytes differ — the trajectory is "
            f"not a pure function of the triple")
    assert shot1 == shot2, "same-seed parked captures differ byte-for-byte"


def test_a_different_seed_draws_different_poweron_ram():
    """The sensitivity control: the comparison above must be able to fail.
    Compared at the power-on park, before the ROM's init overwrites the
    randomized regions."""
    a = Machine(ROM, seed=1).read_bytes(W, 0, 0x8000)
    b = Machine(ROM, seed=2).read_bytes(W, 0, 0x8000)
    assert a != b, (
        "seeds 1 and 2 drew identical power-on WRAM — the seed knob is "
        "inert and every 'same seed matches' pass above is vacuous")


def test_rule5_poweron_ram_is_random_not_zeroed():
    """Seeding must not quietly become zero-init (rule 5). At the power-on
    park nothing has run: WRAM must hold non-uniform garbage."""
    m = Machine(ROM)
    w = m.read_bytes(W, 0, 0x8000)
    assert len(set(w)) > 64, (
        f"power-on WRAM holds only {len(set(w))} distinct byte values — "
        f"that is a fill pattern, not randomized DRAM")


# ---------------------------------------------------------------------------
# input latch
# ---------------------------------------------------------------------------
def _enter_race(m):
    """Machine-side twin of mz_drive.enter_race: press START on the title,
    then wait for arrival in the race scene by READING the scene manager's
    control block (the scene_mgr's own output region), bounded in emulated
    frames. microzero boots to a TITLE scene — a pad held before this point
    lands only in the joypad mirror, which is how this module's first draft
    proved 'the latch works' against a game that was not listening yet."""
    import json
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    ctl = syms["ES_SM_CTL"]["start"]
    m.advance(120)
    m.advance(2, pad1={"start": True})
    RACE = 1
    m.run_until(lambda mm: tuple(mm.read_bytes(W, ctl, 3)[::2]) == (RACE, 0),
                max_frames=600, what="race scene settled")
    return m


def test_input_reaches_the_game_and_replays_identically():
    """Same seed, same pads -> identical WRAM after a driven race. Same
    seed, coasting -> the GAME state diverges well beyond the 2-byte joypad
    mirror (the control that proves the latch is driving the game, not just
    landing in the pad register)."""
    def race_drive(m):
        _enter_race(m)
        m.advance(60, pad1={"b": True})               # accelerate
        m.advance(30, pad1={"right": True, "b": True})  # steer
        return m.read_bytes(W, 0, 0x10000)

    a = race_drive(Machine(ROM))
    b = race_drive(Machine(ROM))
    assert a == b, "identically-driven same-seed machines diverged"

    c = _enter_race(Machine(ROM))
    c.advance(90)                                     # coast, pads released
    coast = c.read_bytes(W, 0, 0x10000)
    diff = sum(1 for x, y in zip(a, coast) if x != y)
    assert diff > 8, (
        f"a driven race and a coasting race differ in only {diff} WRAM "
        f"byte(s) — that is the joypad mirror at most, so the latch is not "
        f"reaching the game and the replay equality above is vacuous")


# ---------------------------------------------------------------------------
# captures
# ---------------------------------------------------------------------------
def test_a_capture_costs_exactly_one_frame_and_is_the_parked_picture(tmp_path):
    """The legacy one-frame contract, kept; the frame choice, now exact."""
    m = _drive(Machine(ROM))
    before = m.ppu_frame_count()
    p = m.take_screenshot(tmp_path / "cap.png")
    assert m.ppu_frame_count() == before + 1, (
        f"capture cost {m.ppu_frame_count() - before} frames, contract is 1")
    assert Path(p).stat().st_size > 0


# ---------------------------------------------------------------------------
# synchrony under load
# ---------------------------------------------------------------------------
def test_advance_is_synchronous_under_3x_oversubscription():
    """>= 300 reps, >= 3x CPU oversubscription: every advance returns only
    when its frames are emulated (exact landing verified inside advance()
    against the PPU counter, re-verified here), and none hangs (the loop
    completes). The burner count is 3x nproc; per the spec load is only
    comparable through measured fps, so the emulated rate is printed for
    the record rather than asserted."""
    import os
    import time
    nproc = os.cpu_count() or 4
    burners = [subprocess.Popen([sys.executable, "-c", "while True: pass"])
               for _ in range(3 * nproc)]
    try:
        m = Machine(ROM)
        # A mixed schedule so both the bulk phase and the walk phase run
        # under contention. The frame TOTAL is DERIVED from the schedule
        # (REPS/SCHEDULE below, reported by the print at the end) and is
        # deliberately not narrated beside it: this comment shipped reading
        # "300 advances, 522 frames" against a schedule that totals 1,704
        # — CLAUDE.md's "a comment is secondary, not
        # evidence", caught in this file. A number a reader must trust is a
        # number that drifts; this one is now computed.
        REPS = 300
        SCHEDULE = [(1, 1, 2, 17)[i % 4] if i % 25 else 16 for i in range(REPS)]
        t0 = time.monotonic()
        expected = 0
        for i, n in enumerate(SCHEDULE):
            m.advance(n, pad1={"right": True, "b": True} if i % 2 else None)
            expected += n
            assert m.ppu_frame_count() == expected, (
                f"rep {i}: advance({n}) landed on {m.ppu_frame_count()}, "
                f"wanted {expected} — an early return under load")
        dt = time.monotonic() - t0
        print(f"\n  synchrony stress: {REPS} advances / {expected} frames under "
              f"{3 * nproc} burners on {nproc} cores in {dt:.1f}s "
              f"({expected / dt:.0f} emulated fps)")
    finally:
        for b in burners:
            b.kill()
        for b in burners:
            b.wait()
