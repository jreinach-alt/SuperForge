"""Dual-running CI / agreement gate (spec B.6, Brick 5).

The transition-safety net before Brick 7 retires the bespoke per-template gates:
for each B.6 proof row, the EXISTING bespoke gate AND the oracle manifest must
AGREE on the good ROM — both pass. As long as both run green here, retiring a
bespoke gate (Brick 7) provably loses no coverage; if they ever diverge, this
gate catches it before the bespoke side is removed.

Kept light: each row runs ONE representative bespoke gate function (the cheap
boot/render gate, not the slow win-bot) against a shared runner, and runs the
oracle on the matching cheap scenario. The expensive bot row (breaker reach_win)
and the full FAIL-side discrimination live in test_oracle_faults.py /
test_oracles.py respectively; this module only proves agreement, not coverage.

Skips cleanly when build/*.sfc is absent.
"""

import importlib.util
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import load_manifest, verify, _delete_srm

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
TEMPLATES = ROOT / "templates"
TESTS_DIR = Path(__file__).resolve().parent


pytestmark = pytest.mark.skipif(
    not (BUILD / "breaker.sfc").exists(),
    reason="ROMs not built (dryrun_split.sh + make breaker racer sprite_game + make testroms)",
)


def _import(modname, filename):
    path = TESTS_DIR / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gate_passed(fn, *args):
    """Run a bespoke gate function; return True if it passes (no assertion)."""
    try:
        fn(*args)
        return True
    except AssertionError:
        return False


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# --- representative bespoke gate per B.6 row --------------------------------
# (probe row label, manifest path, ROM basename, oracle scenario to verify,
#  bespoke-module file, bespoke gate function name, needs_srm_reset)
_ROWS = [
    ("row1 sprite_game", TEMPLATES / "sprite_game" / "oracle.json",
     "sprite_game.sfc", "boots_both_sprites",
     "test_sprite_game.py", "test_boots_both_sprites_visible", False),
    ("row2 breaker boot", TEMPLATES / "breaker" / "oracle.json",
     "breaker.sfc", "boots_field_rendered",
     "test_breaker.py", "test_boots_field_rendered", False),
    ("row4 racer", TEMPLATES / "racer" / "oracle.json",
     "racer.sfc", "boots_kart_and_floor",
     "test_racer.py", "test_racer_drives_and_steers", False),
    # row4b: the H-1 discriminator itself (steer_rotates_floor / axis_branch /
    # screenshot_axis_diff) gets a bespoke<->oracle agreement check. The cheap
    # row4 above only exercises boots_kart_and_floor, so before this row a
    # regression in the frame-deterministic axis_branch baseline would NOT trip
    # dual-run (audit-1 LOW-1). The bespoke counterpart is the same
    # test_racer_drives_and_steers gate, which contains its own steer-rotation
    # assertion — so the two paths agree that steering rotates the floor.
    ("row4b racer steer", TEMPLATES / "racer" / "oracle.json",
     "racer.sfc", "steer_rotates_floor",
     "test_racer.py", "test_racer_drives_and_steers", False),
    ("row5 save", TESTS_DIR / "save_test.oracle.json",
     "save_test.sfc", "battery_persists_across_power_cycle",
     "test_save.py", None, True),  # save's gate is fixture-driven; see below
]


@pytest.mark.parametrize(
    "label,manifest_path,rom_basename,scenario,gate_file,gate_fn,needs_srm",
    _ROWS,
    ids=[r[0].replace(" ", "_") for r in _ROWS],
)
def test_bespoke_and_oracle_agree(
    label, manifest_path, rom_basename, scenario, gate_file, gate_fn, needs_srm,
    runner,
):
    if not manifest_path.exists():
        pytest.skip(f"{manifest_path.name} not present")
    if not (BUILD / rom_basename).exists():
        pytest.skip(f"{rom_basename} not built")

    if needs_srm:
        _delete_srm(str(BUILD / rom_basename))

    # --- oracle side ---
    m = load_manifest(manifest_path)
    oracle_pass = verify(m, runner, rom_dir=BUILD, only={scenario}).passed

    # --- bespoke side ---
    if gate_fn is not None:
        mod = _import(f"_dual_{Path(gate_file).stem}", gate_file)
        bespoke_pass = _gate_passed(getattr(mod, gate_fn), runner)
    else:
        # save: the bespoke gate is fixture-driven (two boots in one process).
        # Reproduce its core SRAM-persistence check inline so we don't depend on
        # pytest fixture machinery: virgin boot writes "SF" + payload, a power
        # cycle restores it byte-identically.
        _delete_srm(str(BUILD / rom_basename))
        rom = str(BUILD / rom_basename)
        from infrastructure.test_harness.mesen_runner import MemoryType
        runner.load_rom(rom, run_seconds=1.5)
        runner.load_rom(rom, run_seconds=1.5)  # power cycle
        sram = bytes(runner.read_bytes(MemoryType.SnesSaveRam, 0, 16))
        bespoke_pass = sram[0:2] == b"SF" and list(sram[8:11]) == [3, 10, 17]

    assert oracle_pass == bespoke_pass == True, (
        f"{label}: dual-run DISAGREEMENT — oracle={oracle_pass}, "
        f"bespoke={bespoke_pass} (both must pass on the good ROM)"
    )


def test_dual_run_covers_each_b6_row():
    """Sanity: the dual-run table names the distinct B.6 templates."""
    templates = {r[2].replace(".sfc", "") for r in _ROWS}
    assert {"sprite_game", "breaker", "racer", "save_test"} <= templates
