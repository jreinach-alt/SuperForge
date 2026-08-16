"""The emulated-frame wait primitives, pinned against the ROM's own clock.

TEST SURFACE (AGENTS.md "when you finish", item 2).

  Feature under test: `wait_frames`, `wait_until`, `run_to_break(max_frames=)`
  and `boot_rom` in `vendor/mesen_runner.py` — the primitives that replaced
  the suite's wall-clock waits.

  Output region read: **the ROM's own per-frame counter in WRAM**
  (`ES_SM_FRAME`, bumped once per NMI by the running game), and for the
  breakpoint case the CPU's write to a known address.

  Oracle: **`frame_step`** — the deterministic path the flake investigation
  found does NOT flake, because it already counts in emulated frames. So
  "wait_frames(N) advances the game by what frame_step(N) advances it by" is
  a claim against an independently-trusted instrument.

  Deliberately NOT asserted against `ppu_frame_count()`: that is these
  primitives' own INPUT. A primitive checked against its input is a
  tautology — the exact shape of indirect-evidence test CLAUDE.md rule 2
  forbids, and the reason the old wall-clock waits went unexamined for so
  long.

  State cycles driven: boot -> free-running wait -> a wait whose predicate
  flips -> a wait whose predicate NEVER flips (budget exhaustion) -> the same
  budget at BOTH emulator speeds (the property that makes these
  host-load-proof) -> parked (the documented hazard) -> resumed. Both
  outcomes of every primitive, not only the happy one.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR = MemoryType.SnesWorkRam
ROM = SUPERFORGE / "build" / "microzero.sfc"

# A budget of N emulated frames is honoured to within ONE frame, and that is
# not slack — it is where the measurement is taken from. Both endpoints of
# "how many ROM frames did that budget cover" are read on a RUNNING machine:
# the ROM's own counter and the PPU counter are two separate reads of two
# moving values, so which side of a frame boundary each lands on is not
# fixed. CI has read 29 for a 30-frame budget in two different tests.
#
# The discriminator for "is this budget counted in frames or in wall time"
# is never the floor — it is that the SAME budget covers the SAME number of
# frames at emulator speeds 4x apart. A wall budget differs by tens.
FRAME_SAMPLING_SLOP = 1


def budget_floor(max_frames: int) -> int:
    return max_frames - FRAME_SAMPLING_SLOP


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in jmap["globals"]}
    runner = MesenRunner()
    runner.boot_rom(str(ROM))
    yield runner, syms["ES_SM_FRAME"]["start"]
    runner.stop()


def _rom_frame(runner, addr):
    """The GAME's own frame counter — the output region, not our input."""
    return runner.read_u16(WR, addr)


def _advance(runner, addr, n):
    """How far the ROM's counter moves over n frames, measured with the
    deterministic instrument. This is the oracle every wait is checked
    against.

    BOTH endpoints are read while PARKED. Reading the first one on a
    free-running machine costs the measurement a frame or two of slop — the
    ROM keeps going between the read and the park — and the oracle then
    reports 30, 31 or 32 for the same 30 steps, which is not much of an
    oracle. Parked, it is exact.
    """
    with runner.frame_stepping():
        before = _rom_frame(runner, addr)
        runner.frame_step(n)
        after = _rom_frame(runner, addr)
    return (after - before) % 65536


# --------------------------------------------------------------------------
# wait_frames
# --------------------------------------------------------------------------

def test_wait_frames_advances_the_rom_as_far_as_frame_step_does(booted):
    """The headline contract, against the deterministic oracle.

    A 1 ms poll can overshoot the target by a fraction of a frame, so the
    band is [n, n+3] rather than exact — the guarantee is AT LEAST n, and
    the ceiling is there so a wait that quietly ran long still fails.
    """
    runner, addr = booted
    oracle = _advance(runner, addr, 30)
    assert oracle == 30, (
        f"fixture assumption: ES_SM_FRAME advances once per frame, so 30 "
        f"frame_steps must move it exactly 30, not {oracle}")

    before = _rom_frame(runner, addr)
    got = runner.wait_frames(30)
    moved = (_rom_frame(runner, addr) - before) % 65536
    # +/-2 because these two endpoints ARE read free-running (that is the
    # mode wait_frames serves), so the ROM moves a little around each read.
    assert abs(moved - oracle) <= 2, (
        f"wait_frames(30) moved the ROM {moved} frames where frame_step(30) "
        f"— the deterministic instrument — moves it {oracle}")
    assert got >= 30, f"reported {got} elapsed frames for a 30-frame wait"


def test_wait_frames_zero_is_a_no_op(booted):
    runner, addr = booted
    assert runner.wait_frames(0) == 0


def test_wait_frames_rejects_a_negative_count(booted):
    runner, _ = booted
    with pytest.raises(ValueError):
        runner.wait_frames(-1)


# --------------------------------------------------------------------------
# wait_until
# --------------------------------------------------------------------------

def test_wait_until_returns_the_frame_the_predicate_flipped_on(booted):
    """The return value is a determinism handle, so it has to be true."""
    runner, addr = booted
    target = (_rom_frame(runner, addr) + 20) % 65536
    n = runner.wait_until(lambda: _rom_frame(runner, addr) == target,
                          max_frames=120, what="ROM frame counter")
    # +/-1 at the bottom: the base read and the polls are all taken on a
    # free-running machine, so the ROM counter can tick between reading the
    # base and starting to count PPU frames.
    assert 18 <= n <= 23, f"predicate flipped after {n} frames, expected ~20"


def test_wait_until_budget_holds_its_frame_count_at_any_emulator_speed(booted):
    """THE property the whole conversion rests on.

    The flake mechanism is one variable: emulated frames per WALL second. On
    an idle box it is ~60 (or ~280 with the throttle lifted); under host load
    it falls, and a wall-bounded budget then covers proportionally fewer
    emulated frames — which is how a green test goes red with nothing wrong
    in the ROM. Measured on this box, room.sfc free-running: 280 fps idle,
    ~210 under 4 CPU burners, ~100 under 8, ~55 under 16.

    Rather than reproduce that by hammering the host — slow, and it would
    make this test a bad neighbour under xdist — the variable is moved
    DIRECTLY, by running the same budget at both emulator speeds. Same
    mechanism, isolated, deterministic, and about a second.

    A wall budget would cover ~4x different amounts of ROM time across these
    two runs. A frame budget must cover the same. The precondition assert
    keeps it from passing vacuously: if the two speeds did not actually
    differ, the comparison proves nothing and it says so.
    """
    runner, addr = booted

    def spend_budget_at(max_speed: bool):
        runner._free_run_max_speed = max_speed
        runner._apply_free_run_speed()
        runner.wait_frames(5)                     # let the new speed settle
        before = _rom_frame(runner, addr)
        t0 = time.time()
        with pytest.raises(TimeoutError):
            runner.wait_until(lambda: False, max_frames=30, what="never")
        return (_rom_frame(runner, addr) - before) % 65536, time.time() - t0

    try:
        fast_frames, fast_wall = spend_budget_at(True)
        slow_frames, slow_wall = spend_budget_at(False)
    finally:
        runner._free_run_max_speed = True
        runner._apply_free_run_speed()

    assert slow_wall > fast_wall * 2, (
        f"the two emulator speeds did not actually differ ({fast_wall:.3f}s "
        f"vs {slow_wall:.3f}s for the same 30-frame budget) — the condition "
        f"never bit, so this comparison proves nothing")
    floor = budget_floor(30)
    assert fast_frames >= floor and slow_frames >= floor, (
        f"budget cut short: {fast_frames} frames fast, {slow_frames} slow — "
        f"more than the one frame of sampling slop under the 30 asked for")
    assert abs(slow_frames - fast_frames) <= 3, (
        f"the same budget covered {fast_frames} ROM frames at "
        f"{30 / fast_wall:.0f} fps but {slow_frames} at {30 / slow_wall:.0f} "
        f"fps — it is still being counted in wall time, which IS the flake "
        f"mechanism")


def test_the_wav_carve_out_keeps_audio_runners_at_real_time():
    """L2's one seam, asserted rather than assumed.

    Free-running at ~4x is harmless for every wait in this harness because
    they all count emulated frames — except a WAV capture, which is a
    recording of REAL time. Audio runners therefore keep the 60 fps throttle
    (tests/test_slice_b_audio.py:17-19, the run-gate precedent).
    """
    assert MesenRunner(enable_audio=True)._free_run_max_speed is False
    assert MesenRunner()._free_run_max_speed is True


def test_wait_until_timeout_message_reports_emulated_frames(booted):
    runner, _ = booted
    with pytest.raises(TimeoutError) as e:
        runner.wait_until(lambda: False, max_frames=5, what="a thing")
    msg = str(e.value)
    assert "a thing" in msg and "EMULATED frames" in msg, msg
    assert "5" in msg, msg


def test_wait_until_frames_at_flip_repeat_across_boots(booted):
    """Acceptance §3.2: a converted wait reports the same frames-at-flip run
    to run — a determinism handle a caller can log and diff.

    THE TOLERANCE IS ONE FRAME, and the reason is worth stating rather than
    padding away. Both endpoints here are sampled on a FREE-RUNNING machine:
    the base read of the ROM counter and the PPU counter snapshot are two
    separate reads of a moving target, so which side of a frame boundary
    each lands on is not fixed. Measured idle, this repeats exactly (three
    boots of the room's scene round-trip gave [0, 23, 23, 23] three times);
    measured under three xdist workers on a 4-core box it gave [39, 39, 40].
    One frame of quantisation, not one frame of wall-clock coupling — and
    the distinction is testable, which is what the band below is for.

    A wall-coupled wait cannot pass this: it would cover a number of frames
    proportional to the host's spare capacity, so the spread would be tens
    of frames, not one. The absolute band is the other half — a wait that
    was uniformly wrong would sail through a spread check alone.

    The instrument that IS exact to the frame is `frame_step`, which is why
    every measurement in this repo anchors on it (AGENTS.md "deterministic
    captures use frame-step, not wall-clock").
    """
    runner, addr = booted
    counts = []
    for _ in range(3):
        runner.boot_rom(str(ROM), frames=90)
        start = _rom_frame(runner, addr)
        counts.append(runner.wait_until(
            lambda: (_rom_frame(runner, addr) - start) % 65536 >= 40,
            max_frames=200, what="40 ROM frames"))
    assert max(counts) - min(counts) <= 1, (
        f"frames-at-flip spread {counts} across identical runs — more than "
        f"the one frame of free-running sampling quantisation, so the wait "
        f"is coupled to something outside the emulator")
    assert all(38 <= c <= 44 for c in counts), (
        f"40 ROM frames took {counts} emulated frames — consistent, but not "
        f"the right number, so the wait is uniformly wrong rather than noisy")


# --------------------------------------------------------------------------
# the hazard: a parked runner
# --------------------------------------------------------------------------

def test_a_parked_runner_is_named_by_the_stall_guard(booted):
    """A parked emulator does not advance, so a frame-counted wait can never
    finish. The old wall-clock `run_frames` slept and returned, leaving the
    caller reading a frozen machine as though time had passed; this says so.
    """
    runner, _ = booted
    runner.debug_break()
    try:
        with pytest.raises(TimeoutError) as e:
            runner.wait_frames(5, stall_s=0.4)
        assert "PARKED" in str(e.value), str(e.value)
    finally:
        runner.debug_resume()
    runner.wait_frames(2)                 # and it works again once resumed


# --------------------------------------------------------------------------
# run_to_break(max_frames=)
# --------------------------------------------------------------------------

def test_run_to_break_still_catches_a_write_under_a_frame_budget(booted):
    """The positive half: a budget must not break the normal path."""
    runner, addr = booted
    wram_bank = 0x7E0000
    with runner.breakpoints(
            [(MemoryType.SnesMemory, wram_bank + addr, "write")]):
        assert runner.run_to_break(max_frames=60) is True, (
            "the per-frame counter's own write was not caught in 60 frames")


def test_run_to_break_false_is_a_claim_about_the_rom_not_the_host(booted):
    """The negative half, and the reason `max_frames` exists: a False has to
    mean "the CPU did not write this in N frames of the ROM's time".

    THE DEAD ADDRESS IS MEASURED, not assumed. Microzero's highest
    ever-written WRAM byte is $00DD9 — taken from the debugger's per-address
    write counters after a full boot + race drive + 500 frames, not from
    reading the allocator's map, because the map does not know about the
    stack. WRAM offset $1F000 (CPU $7F:F000) is 126 KB past it. The
    precondition assert below keeps that a claim rather than a hope.

    Run at both emulator speeds, the same way the wait_until budget test
    does: a wall deadline would return False after wildly different amounts
    of ROM time at 60 fps and at 280; a frame budget must spend the same 30
    either way. MEASURED inside the breakpoint block here: 175 emulated fps
    against 58, a 3x separation, and 31 ROM frames against 30.

    (An earlier version induced the slow side with a Python burner THREAD.
    That perturbs run_to_break's own polling loop through the GIL rather
    than perturbing the emulator, and it made the breakpoint report a hit on
    an address nothing writes. Moving the emulator's speed moves the
    variable under test; starving the poller moves the instrument. That hit
    was the SPURIOUS BREAK, diagnosed eight commits later, and
    gated out below; the burner was not what made it possible, only what
    made it likely.)
    """
    runner, addr = booted
    DEAD_WRAM = 0x1F000                  # WRAM offset — measured never written
    dead = 0x7E0000 + DEAD_WRAM          # the same byte, as a CPU address

    def wrote_within(max_frames):
        """Did the CPU write $7F:F000 inside `max_frames` emulated frames?

        THE BREAKPOINT IS THE STOPWATCH; THE WRITE COUNTER IS THE ORACLE —
        the same pairing as tests/test_room_window.py::_clock_at_write, and
        required for the same reason. `run_to_break` returning True is not
        proof that a breakpoint matched: its test is "execution is stopped
        AND the master clock moved", and Mesen's `IsExecutionStopped()` is
        `_executionStopped || _emu->IsThreadPaused()`, whose second term
        covers the EmulatorLock / DebugBreakHelper pauses that briefly halt a
        free-running core. `_settle_at_break` then Steps the machine to a
        real stop and hands back a break nothing produced — measured at ~2.6%
        of idle reps on the room's iris table.

        A negative assertion on a bare `run_to_break` therefore reds with
        nothing wrong, which is exactly what this test USED to be: it asserted
        `hit is False` ungated, and it had already been seen reporting "a hit
        on an address nothing writes" at an earlier commit. So the
        question "did a write happen" goes to `write_count`, the memory
        system's own tally for the byte, and a reported break with the counter
        unmoved resumes the watch on what is left of the EMULATED budget —
        which also keeps the frame-count assertions below measuring a full 30
        frames rather than however far the spurious stop got.

        `DEAD_WRAM` is a WorkRam offset and bank-agnostic; `dead` is the
        SnesMemory CPU address the breakpoint names. Here they are the same
        byte deliberately: $7F:F000 is the high mirror, so the counter cannot
        miss a long-addressed store the breakpoint would.
        """
        before = runner.write_count(WR, DEAD_WRAM)
        start = runner.ppu_frame_count()
        with runner.breakpoints([(MemoryType.SnesMemory, dead, "write")]):
            # `breakpoints()` lifts MaximumSpeed on entry
            # (vendor/mesen_runner.py:2112), which OVERRIDES this runner's
            # speed policy for the whole block — so without this line the
            # "60 fps" half of the comparison below is not at 60 fps and the
            # discriminator is comparing two fast runs. MEASURED inside the
            # block: 239 fps against 174, a 1.4x separation where the test
            # claims ~4x. Re-applying the policy restores it to 175 against
            # 58 (a real 3x) and costs the slow half ~0.3 s. The non-vacuity
            # assert below is what keeps this honest if the override ever
            # comes back.
            runner._apply_free_run_speed()
            while True:
                left = max_frames - (runner.ppu_frame_count() - start)
                if left <= 0:
                    return False
                broke = runner.run_to_break(max_frames=left)
                if runner.write_count(WR, DEAD_WRAM) > before:
                    return True
                if not broke:
                    return False
                # Stopped, byte untouched: a thread pause wearing a
                # breakpoint's clothes. Spend the rest of the budget.

    def spend_at(max_speed: bool):
        runner._free_run_max_speed = max_speed
        runner._apply_free_run_speed()
        runner.wait_frames(5)
        before = _rom_frame(runner, addr)
        t0 = time.time()
        hit = wrote_within(30)
        return (hit, (_rom_frame(runner, addr) - before) % 65536,
                time.time() - t0)

    try:
        fast_hit, fast_frames, fast_wall = spend_at(True)
        slow_hit, slow_frames, slow_wall = spend_at(False)
    finally:
        runner._free_run_max_speed = True
        runner._apply_free_run_speed()

    # NON-VACUITY, the same guard the wait_until budget test carries. Without
    # it this test cannot tell "the budget is counted in frames" from "both
    # runs happened to go the same speed", and it in fact could not: the
    # breakpoints-block speed override above went unnoticed here for the whole
    # change precisely because nothing asserted the two speeds differed.
    assert slow_wall > fast_wall * 2, (
        f"the two emulator speeds did not actually differ ({fast_wall:.3f}s "
        f"vs {slow_wall:.3f}s for the same 30-frame budget) — the frame-count "
        f"comparison below proves nothing")

    assert fast_hit is False and slow_hit is False, (
        f"the write COUNTER for $7F:F000 moved (fast={fast_hit}, "
        f"slow={slow_hit}) — microzero's highest written WRAM byte measured "
        f"$00DD9, 126 KB below this one, so the ROM changed. This is not the "
        f"spurious break: the counter is the memory system's tally at the "
        f"store, so a break with nothing behind it cannot reach here")
    floor = budget_floor(30)
    assert fast_frames >= floor and slow_frames >= floor, (
        f"the frame budget returned False after {fast_frames} ROM frames "
        f"fast / {slow_frames} slow — more than the one frame of sampling "
        f"slop under 30, so a wall deadline is still in the path and a False "
        f"could mean 'the host was busy' instead of 'the ROM did not write'")
    assert abs(fast_frames - slow_frames) <= 3, (
        f"the same budget covered {fast_frames} ROM frames at "
        f"{fast_frames / fast_wall:.0f} fps but {slow_frames} at "
        f"{slow_frames / slow_wall:.0f} fps — it is not being counted in "
        f"frames")


# --------------------------------------------------------------------------
# boot_rom
# --------------------------------------------------------------------------

def test_boot_rom_gives_the_rom_the_frames_it_asked_for(booted):
    runner, addr = booted
    runner.boot_rom(str(ROM), frames=60)
    got = _rom_frame(runner, addr)
    # The ROM's counter starts a frame or two after power-on (reset vector,
    # WRAM clear, asset DMA all run before the first NMI), so it trails the
    # PPU's frame count by that boot offset. The band allows the offset and
    # the poll overshoot; what it refuses is a boot that bought a materially
    # different number of frames than it asked for.
    assert 55 <= got <= 66, f"boot budget landed on ROM frame {got}"


def test_boot_rom_stops_at_a_power_on_safe_ready_predicate(booted):
    """The predicate form ends the boot as soon as the ROM says it is up,
    instead of always paying the full budget.

    The predicate is the toy's four-byte SFOK signature, and that choice is
    the point: RAM is RANDOM at power-on (CLAUDE.md rule 5), so a predicate
    like "this counter is past 10" reads uninitialised garbage on frame 0
    and can be true before the ROM has run at all. Written that way first,
    this returned 0 — the boot was skipped entirely and every later read
    would have been of power-on noise. A signature cannot do that.
    """
    runner, _ = booted
    toy = SUPERFORGE / "build" / "toy.sfc"
    r = subprocess.run(["make", "toy"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make toy failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "symbol_map.json").read_text())
    scratch = next(p["start"] for p in jmap["scenes"]["toy"]["placements"]
                   if p["sym"] == "US_SCRATCH")
    try:
        n = runner.boot_rom(
            str(toy), frames=200,
            ready=lambda: runner.read_bytes(WR, scratch, 4) == b"SFOK",
            ready_what="the toy's SFOK signature")
        # n == 0 is a legitimate — and the best — answer: the toy plants its
        # signature during init, so it is already up the first time we look.
        # What matters is that the predicate form did NOT pay the 200-frame
        # budget, and that the thing it waited for is genuinely there.
        assert n < 60, f"SFOK only appeared at frame {n} of a 200 budget"
        assert runner.read_bytes(WR, scratch, 4) == b"SFOK"

        # ...and the budget still applies, so a ready that never comes is a
        # bounded, named failure rather than a hang.
        with pytest.raises(TimeoutError) as e:
            runner.boot_rom(str(toy), frames=10, ready=lambda: False,
                            ready_what="a signature the toy never writes")
        assert "EMULATED frames" in str(e.value), str(e.value)
    finally:
        runner.boot_rom(str(ROM), frames=90)   # leave microzero for the module


# --------------------------------------------------------------------------
# the capture primitive: content-of-now, under any host load
# --------------------------------------------------------------------------
#
# Feature under test: take_screenshot's frame-synchronous guarantee.
# Output region read: the PNG's pixels, against an ORACLE read out of WRAM —
# the room's fade level (ES_FADE_CTL), which drives INIDISP brightness and so
# has a known, arithmetic relationship to what every pixel must be. Never
# against the capture machinery itself.
# Perturbation: the EMULATOR's speed, which is the variable that decides
# whether the PPU skips rendering (SnesPpu.cpp:491) — not host burners, which
# would move the instrument and make a bad neighbour under xdist.
# State cycle driven: a full fade-in, sampled every frame from black to full
# brightness, at both emulator speeds.

ROOM_ROM = SUPERFORGE / "build" / "room.sfc"
FADE_CTL = 47                    # ES_FADE_CTL: level(0..15), dir — build/rm map


def _fade_walk(runner):
    """Drive a title->room->title fade and yield (wram_level, png_peak) per
    frame. png_peak is the brightest channel value anywhere on screen, which
    INIDISP scales linearly with the fade level."""
    import test_room_window as T
    from PIL import Image
    import tempfile as _tf

    T.enter_room(runner, respawn=True)
    runner.set_input(0, start=True)
    runner.wait_frames(4)
    runner.set_input(0)
    rows = []
    with _tf.TemporaryDirectory() as d:
        for i in range(14):
            level = runner.read_bytes(WR, FADE_CTL, 2)[0]
            shot = f"{d}/f{i}.png"
            runner.take_screenshot(shot)
            img = Image.open(shot).convert("RGB")
            peak = max(max(img.getpixel((x, y)))
                       for y in range(20, 200, 4) for x in range(0, 256, 8))
            rows.append((level, peak))
            runner.wait_frames(1)
    return rows


@pytest.fixture(scope="module")
def room_runner():
    r = subprocess.run(["make", "room"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make room failed:\n{r.stdout}\n{r.stderr}"
    runner = MesenRunner()
    runner.boot_rom(str(ROOM_ROM))
    yield runner
    runner.stop()


@pytest.mark.parametrize("max_speed", [True, False], ids=["free-run", "60fps"])
def test_a_capture_shows_the_frame_that_was_current_when_it_was_taken(
        room_runner, max_speed):
    """THE capture invariant, checked against emulated state per frame.

    A fade steps the whole screen's brightness by one notch per frame, so
    "the picture is a frame behind" is directly visible as a peak that
    repeats or goes backwards. This walks the fade and requires the PNG to
    track the level in WRAM, at BOTH emulator speeds.

    Free-run is not a stress variant here, it is the failing case: unthrottled,
    Mesen's PPU skips rendering any frame under 10 ms after the last rendered
    one, so the composite went stale by several EMULATED frames and which
    frames survived was a wall-clock decision. Measured before the fix, at
    max speed, the same walk gave repeats and reversals —
    (3, 66), (0, 66), (2, 0) — and ended (15, 231) with the fade already done.
    That last pair is a CI run's red: the title's white one notch
    dim.

    THIS TEST IS NOT THE PRIMARY GATE, AND THE HONEST NUMBER IS 3 IN 10.
    Restore `DisableFrameSkipping = False` and this test reds in about one
    sabotaged run in three, measured over 10 — not the "both
    sabotage runs did exactly that" the comment below used to imply off a
    sample of two. The reason is in the mechanism: `_skipRender` needs the wall
    gap since the last rendered frame to be UNDER 10 ms, and this walk's own
    per-iteration cost (a PNG write plus a 1440-pixel PIL scan) usually exceeds
    that, so the sabotage often cannot express itself. Buying determinism
    would mean dropping the PNG-and-scan, which is the output region this test
    exists to read — a worse test for a better number, so it is not done.

    **`test_the_process_renders_every_frame` is the reliable detector** — it
    fired on 10 of 10 sabotaged runs, because it asserts on the config rather
    than on a race. Keep it. It looks redundant beside this one and is not:
    delete it and the only thing left guarding a process-wide render guarantee
    is a check that notices two times in three.
    """
    room_runner._free_run_max_speed = max_speed
    room_runner._apply_free_run_speed()
    try:
        rows = _fade_walk(room_runner)
    finally:
        room_runner._free_run_max_speed = True
        room_runner._apply_free_run_speed()
    levels = [lv for lv, _ in rows]
    peaks = [pk for _, pk in rows]
    # A SPAN, not a peak. Every capture costs exactly one emulated frame at
    # both speeds, but each also costs WALL time (a PNG write plus a PIL
    # scan), and a free-running core turns that wall time into extra emulated
    # frames while a throttled one does not — so 14 samples legitimately cover
    # different amounts of the fade at the two speeds. What the checks below
    # need is simply a wide sweep of levels to compare against.
    assert max(levels) - min(levels) >= 10, (
        f"the walk did not sweep enough of the fade to be meaningful: "
        f"levels {levels}")

    # THE DISCRIMINATOR IS A REVERSAL, not a repeat. INIDISP scales the
    # palette linearly and the result is rounded to 8 bits, so two adjacent
    # LOW levels can legitimately round to the same peak — CI walked 1 -> 2
    # and both read 16, which is quantisation, not staleness. What a stale
    # composite cannot do is move the peak BACKWARDS while the fade moves
    # forwards, and that is what a stale composite has been observed doing:
    # level 0 -> 2 with peak 66 -> 0 before the fix; level 1 -> 3 with peak
    # 33 -> 16 with frame skipping deliberately restored; level 1 -> 2 with
    # peak 66 -> 0 in the audit's re-run. When the sabotage expresses itself
    # at all (~3 runs in 10 — see the docstring) this is the check that
    # catches it.
    for i in range(1, len(rows)):
        (l0, p0), (l1, p1) = rows[i - 1], rows[i]
        if l1 == l0:
            continue
        ok = (p1 >= p0) if l1 > l0 else (p1 <= p0)
        assert ok, (
            f"frame {i}: the fade level went {l0}->{l1} but the captured "
            f"peak went {p0}->{p1} — the PNG is showing an OLDER frame than "
            f"the one that was current when it was taken. Full walk: {rows}")

    # ...and the walk must actually track the fade, so a frozen composite
    # cannot pass the no-reversal check by never moving at all. Stated as a
    # SPAN rather than an absolute ceiling: the two speeds cover different
    # amounts of the fade in 14 samples (free-run reaches level 15, throttled
    # ends around 14, because each capture costs wall time the free-running
    # core spends on frames), so pinning max(peaks) to 255 fails the honest
    # 60 fps case. A frozen composite has span 0 either way.
    assert max(peaks) - min(peaks) >= 150, (
        f"the captured peaks spanned only {max(peaks) - min(peaks)} "
        f"({min(peaks)}..{max(peaks)}) while the fade level covered "
        f"{min(levels)}..{max(levels)} — the composite is not following the "
        f"emulated state. Full walk: {rows}")


def _raw_composite(runner, path) -> bytes:
    """Copy the composite with NO emulated-frame advance.

    `take_screenshot` deliberately spends a frame; this reads the buffer as it
    stands, which is what "has the composite settled" has to ask.
    """
    import shutil
    ss = os.path.join(runner._home_dir, "Screenshots")
    before = set(os.listdir(ss)) if os.path.isdir(ss) else set()
    runner._lib.TakeScreenshot()
    for _ in range(400):
        # WALL-CLOCK: ok — polling the FILESYSTEM for Mesen's PNG, and
        # deliberately with no emulated-frame advance: this helper's whole
        # job is to read the composite WITHOUT moving the machine.
        time.sleep(0.001)
        if os.path.isdir(ss):
            new = set(os.listdir(ss)) - before
            if new:
                shutil.move(os.path.join(ss, sorted(new)[0]), path)
                return Path(path).read_bytes()
    raise AssertionError("TakeScreenshot produced no file")


def test_a_free_run_capture_is_taken_from_a_stopped_machine(
        room_runner, tmp_path):
    """The STRUCTURAL half of the capture invariant — the reliable detector.

    THE MECHANISM. `TakeScreenshot` copies `BaseVideoFilter::_outputBuffer`
    (`BaseVideoFilter.cpp:166-180`). Nothing on the calling thread fills it:
    `SnesPpu::SendFrame` reaches `VideoDecoder::UpdateFrame`, which for live
    play (`sync=false`, `SnesPpu.cpp:1522`) only sets `_frameChanged` and
    signals `_waitForFrame`; the pixels are written afterwards by
    `DecodeThread`. And `SnesPpu.cpp:479` bumps the PPU frame counter BEFORE
    calling `SendFrame`, so `wait_frames(1)` returns before the frame has even
    been submitted. Capturing there photographs the previous frame whenever the
    decode thread has not been scheduled yet — a wall-clock question, and the
    whole of the `XDIST=2` flake this test pair exists to catch.

    WHY STRUCTURAL. Its behavioural sibling above catches this at 16 runs in 20
    under 6 CPU burners and at essentially 0 in 20 on an idle box: it needs the
    host to be busy before the bug can express itself, exactly like the
    frame-skipping pair below. This one asserts the property that makes the
    race impossible — the machine is STOPPED while the composite is read, so it
    cannot submit a newer frame and the buffer converges instead of racing —
    and it holds on an idle box. Delete it and the only guard left on a
    guarantee the whole suite's visual assertions rest on is a check that
    needs a loaded CI machine to notice.

    Reads the OUTPUT region (the composited PNG's bytes), not a flag that
    should imply it.
    """
    room_runner.debug_resume()                  # order-independent precondition
    assert not room_runner._frame_stepping
    lib = room_runner._frame_step_lib()

    latched = room_runner._park_for_capture()
    try:
        assert lib.IsExecutionStopped(), (
            "the capture path left the emulator RUNNING: the composite it is "
            "about to copy is whatever the decode thread last finished, which "
            "is a host-load question, not a frame the caller named")
        assert room_runner.ppu_frame_count() == latched + 1, (
            f"the park landed {room_runner.ppu_frame_count() - latched} frames "
            f"past the latch, wanted 1 — the composite is converging on a "
            f"different frame than the caller's")

        # Parked, so at most ONE frame is in flight and the buffer can change
        # at most once. Two reads that agree across a real gap are a settled
        # composite; two that differ are the decode landing late, which is the
        # bug this park exists to make impossible.
        first = _raw_composite(room_runner, str(tmp_path / "a.png"))
        # A REAL-TIME gap IS the assertion. The machine is STOPPED, so
        # emulated time cannot pass at all; what is under test is whether
        # the video decoder still changes the buffer while it does not.
        # WALL-CLOCK: ok — the real-time gap is the thing being asserted
        time.sleep(0.05)
        second = _raw_composite(room_runner, str(tmp_path / "b.png"))
        assert first == second, (
            "the composite changed while the emulator was STOPPED — the "
            "capture is still racing the video decoder")
    finally:
        room_runner.debug_resume(clear_input=False)


def test_a_capture_hands_the_machine_back_running_and_still_holding(
        room_runner, tmp_path):
    """The park is the caller's business only if it leaks. It must not.

    A free-run capture parks; the two things a caller would notice if that
    were done carelessly are a machine handed back frozen, and an input
    override dropped by `debug_resume`'s default `clear_input=True`. Both are
    read from output regions: the emulator's own frame counter for "running",
    and the hero's OAM position for "still holding Right".
    """
    import test_room_window as T

    room_runner.debug_resume()
    T.enter_room(room_runner, respawn=True)
    room_runner.set_input(0, right=True)
    try:
        room_runner.wait_frames(10)
        before = T.hero_centre(room_runner)[0]
        room_runner.take_screenshot(str(tmp_path / "held.png"))
        assert not room_runner._frame_stepping, (
            "take_screenshot left the runner in frame-stepping mode")
        mark = room_runner.ppu_frame_count()
        room_runner.wait_frames(10)
        assert room_runner.ppu_frame_count() > mark, (
            "the machine did not resume after the capture")
        after = T.hero_centre(room_runner)[0]
    finally:
        room_runner.set_input(0)
    assert after > before, (
        f"the hero stopped walking across the capture ({before} -> {after}): "
        f"the park dropped the held input override")


def test_the_process_renders_every_frame():
    """The structural half: a capture must RENDER the frame it photographs.

    No amount of settling in a test can compensate for a frame the emulator
    never re-rendered, so this is a process-wide setting rather than a
    per-capture dance. Asserted on the config the harness applies, which is
    the thing that decides it.

    AND IT IS THE PAIR'S RELIABLE HALF, which is why it must not be pruned as
    redundant. Restoring `DisableFrameSkipping = False` reds this test 10 times
    in 10; it reds the behavioural sibling above about 3 times in 10, because
    that one needs a race to express itself and its own PNG-plus-PIL cost
    usually keeps the race from happening. Behavioural coverage
    is what proves the guarantee is real; structural coverage is what notices
    when it is switched off.

    THE SCOPE IS THE MEASURED PART, and the honest record is that the cheaper
    alternative was tried and did not hold. Process-wide costs ~11% (CI run
    30712937845: `make test` 6:55 against 6:20, whole run 8:24 against 7:34)
    and is GREEN. Suppressing it per-capture by restoring the throttle is
    cheaper and locally green, but its CI run (87c1a91 / 30714563668) went
    red. A third route — toggling the same flag per capture through
    SetSnesConfig — re-applies the whole SNES config mid-run, disturbs
    controller state, and took four input-lockstep tests in
    test_microzero_turning down with it.
    """
    import mesen_runner as MR
    assert MR._make_base_snes_config().DisableFrameSkipping is True, (
        "frame skipping is back on: SnesPpu.cpp:491 drops rendered frames "
        "whenever the core is unthrottled, and every screenshot assertion in "
        "the suite becomes host-load-dependent")


def test_a_capture_spends_exactly_one_emulated_frame(room_runner):
    """The advance is ONE frame, and that count is load-bearing in both
    directions.

    Zero cannot work: the composite holds the PREVIOUS completed frame, so a
    capture with no advance photographs the frame before the caller's. Two is
    too many for a parked caller driving frames one at a time — doing it
    unconditionally moved the VWF row tests' "blank" reference two frames into
    the row's own render and four differential assertions read ink starting
    6 px late.
    """
    import tempfile as _tf
    with room_runner.frame_stepping():
        before = room_runner.ppu_frame_count()
        with _tf.TemporaryDirectory() as d:
            room_runner.take_screenshot(f"{d}/parked.png")
        after = room_runner.ppu_frame_count()
    assert after - before == 1, (
        f"a capture advanced {after - before} emulated frames, expected "
        f"exactly 1")
