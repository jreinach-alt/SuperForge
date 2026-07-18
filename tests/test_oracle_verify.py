"""Brick 3 verify for the oracle drive engine + verify() orchestrator.

Reproduces proof-plan rows 1 (sprite_game), 2 (breaker), and 4 (racer): each
template's manifest PASSES on the good ROM, and the harness FAILS — naming the
same output region the bespoke gate would — when the asserted condition is not
met. Row-3/5 (bot + SRAM) drives are Brick 4; the breaker bot scenario here is
expected to report "not implemented yet".

Fault model: Brick 3 demonstrates the engine's discrimination by faulting the
*expectation* (the dot is asserted at the wrong preset, the floor is asserted to
move impossibly far, the brick palette is asserted to a wrong color). ROM-level
fault injection (skip a brick, freeze steering) is the Brick 5 proof-plan job.

Requires ROMs built into asm_repo_staging/build/ (dryrun_split.sh + make).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import load_manifest, verify

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle"


def _have(name):
    return (BUILD / name).exists()


pytestmark = pytest.mark.skipif(
    not _have("breaker.sfc"),
    reason="ROMs not built (run dryrun_split.sh + make breaker racer sprite_game)",
)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _fail_evidence(verdict):
    """Flatten evidence strings from all failing scenarios."""
    return " | ".join(e for s in verdict.scenarios if not s.ok for e in s.evidence)


# === Row 2: breaker (settle render + axis_sweep paddle) =====================

def test_row2_breaker_passes(runner):
    m = load_manifest(FIXTURES / "valid_breaker.json")
    v = verify(m, runner, rom_dir=BUILD,
               only={"boots_field_rendered", "paddle_both_directions"})
    assert v.passed, _fail_evidence(v)
    assert {s.name for s in v.scenarios} == {"boots_field_rendered",
                                             "paddle_both_directions"}


def test_row2_bot_unregistered_policy_fails(runner):
    # The bot drive runs only if its policy is registered (Brick 4). An
    # unknown policy fails cleanly — order-independent of whatever bots other
    # test modules have registered in this process.
    m = load_manifest(FIXTURES / "valid_breaker.json")
    rw = next(s for s in m.scenarios if s.name == "reach_win")
    rw.drive.params["policy"] = "__nonexistent_bot__"
    v = verify(m, runner, rom_dir=BUILD, only={"reach_win"})
    assert not v.passed
    assert "not registered" in _fail_evidence(v)


def test_row2_fault_corrupt_brick_palette_fails_on_cgram(runner):
    m = load_manifest(FIXTURES / "valid_breaker.json")
    # fault the expectation: assert the wall-grey palette entry is some other color
    boots = next(s for s in m.scenarios if s.name == "boots_field_rendered")
    cg = next(a for a in boots.asserts if a.kind == "cgram_palette")
    cg.params["colors"] = {"1": "0x1234"}
    v = verify(m, runner, rom_dir=BUILD, only={"boots_field_rendered"})
    assert not v.passed
    ev = _fail_evidence(v)
    assert "cgram_palette: FAIL" in ev and "[CGRAM" in ev


# === Row 1: sprite_game (settle + 4-dir axis_sweep + script catch) ==========

def test_row1_sprite_game_passes(runner):
    if not _have("sprite_game.sfc"):
        pytest.skip("sprite_game.sfc not built")
    m = load_manifest(FIXTURES / "sprite_game.json")
    v = verify(m, runner, rom_dir=BUILD)
    assert v.passed, _fail_evidence(v)
    assert len(v.scenarios) == 3 and all(s.ok for s in v.scenarios)


def test_row1_fault_break_dot_relocate_fails_on_oam(runner):
    if not _have("sprite_game.sfc"):
        pytest.skip("sprite_game.sfc not built")
    m = load_manifest(FIXTURES / "sprite_game.json")
    # fault: a broken dot-relocate would leave the dot at preset 0, not (60,60)
    catch = next(s for s in m.scenarios if s.name == "catch_relocates_dot")
    catch.asserts[0].params.update({"x": 200, "y": 60})  # preset 0 (unmoved)
    v = verify(m, runner, rom_dir=BUILD, only={"catch_relocates_dot"})
    assert not v.passed
    ev = _fail_evidence(v)
    assert "oam_entry: FAIL" in ev and "[OAM" in ev


# === Row 4: racer (hold accel + sequential axis_sweep steer w/ screenshots) ==

def test_row4_racer_passes(runner):
    if not _have("racer.sfc"):
        pytest.skip("racer.sfc not built")
    m = load_manifest(FIXTURES / "racer.json")
    v = verify(m, runner, rom_dir=BUILD)
    assert v.passed, _fail_evidence(v)
    assert len(v.scenarios) == 3 and all(s.ok for s in v.scenarios)


def test_row4_fault_freeze_steering_fails_on_screenshot(runner):
    if not _have("racer.sfc"):
        pytest.skip("racer.sfc not built")
    m = load_manifest(FIXTURES / "racer.json")
    # fault: frozen steering wouldn't rotate the floor — demand an impossible 200%
    steer = next(s for s in m.scenarios if s.name == "steer_rotates_floor")
    for a in steer.asserts:
        a.params["min_frac"] = 2.0
    v = verify(m, runner, rom_dir=BUILD, only={"steer_rotates_floor"})
    assert not v.passed
    ev = _fail_evidence(v)
    assert "screenshot_changed: FAIL" in ev and "[screenshot]" in ev


# === continue_from_previous (audit-1 finding E) =============================
# B.3 contract: verify() reloads the ROM per scenario UNLESS a scenario sets
# continue_from_previous, in which case it reuses the prior scenario's loaded
# runner/ROM state. The most direct verification is to count actual reloads:
# spy on runner.load_rom and assert it fires ONCE for two continue-chained
# scenarios vs TWICE without the flag — reading the real reload count, not a
# proxy for it.

class _LoadCountingRunner:
    """Wraps a real MesenRunner, counting load_rom calls; everything else
    delegates. Lets us read the *actual* reload count verify() drives."""

    def __init__(self, inner):
        self._inner = inner
        self.load_count = 0

    def load_rom(self, *args, **kwargs):
        self.load_count += 1
        return self._inner.load_rom(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _two_boot_scenarios(m):
    """Return a manifest with two cheap boot-only scenarios (settle + a single
    real-output assert each) — the boot magic check is a real region read."""
    boots = next(s for s in m.scenarios if s.name == "boots_field_rendered")
    sc1 = replace(boots, name="step_one")
    sc2 = replace(boots, name="step_two")
    return replace(m, scenarios=[sc1, sc2])


def test_continue_from_previous_skips_reload(runner):
    # Without the flag: each scenario reloads -> 2 loads.
    m = _two_boot_scenarios(load_manifest(FIXTURES / "valid_breaker.json"))
    spy_fresh = _LoadCountingRunner(runner)
    v_fresh = verify(m, spy_fresh, rom_dir=BUILD)
    assert v_fresh.passed, _fail_evidence(v_fresh)
    assert spy_fresh.load_count == 2, (
        f"expected 2 reloads without continue_from_previous, "
        f"got {spy_fresh.load_count}")

    # With scenario 2 continued: only scenario 1 reloads -> 1 load.
    m2 = load_manifest(FIXTURES / "valid_breaker.json")
    m2 = _two_boot_scenarios(m2)
    m2.scenarios[1] = replace(m2.scenarios[1], continue_from_previous=True)
    spy_cont = _LoadCountingRunner(runner)
    v_cont = verify(m2, spy_cont, rom_dir=BUILD)
    assert v_cont.passed, _fail_evidence(v_cont)
    assert spy_cont.load_count == 1, (
        f"expected 1 reload with continue_from_previous on scenario 2, "
        f"got {spy_cont.load_count}")
