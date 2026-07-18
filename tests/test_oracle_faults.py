"""FAIL-side proof of the oracle loop (spec B.6, Brick 5; audit-1 MED-A).

Bricks 3-4 validated the harness against faulted *expectations* — mutating the
value a manifest asserts. That cannot prove a too-loose expectation can't pass on
a broken ROM. This module closes MED-A: it injects a *genuine ROM fault* (a
single opcode/operand byte flip, located by a unique signature — see
infrastructure/test_harness/oracle_faults.py) and proves each re-expressed gate
both:

  * FAILS on the faulted ROM, with the failing assert naming the documented
    hardware region (the discrimination proof), AND
  * PASSES on the good ROM (the positive control — so the test proves the
    *manifest discriminates*, not merely "always fails").

Two halves:
  1. Pure-Python unit tests of fault_inject (no emulator): each probe is a
     unique-signature single patch (two for the racer); rebuild-drift and
     missing/duplicate signatures raise FaultError.
  2. ROM-backed B.6 proof: build good ROM -> fault_inject -> write the patched
     bytes under the manifest's basename in a temp rom_dir -> verify() -> assert
     the verdict FAILS and the failing region matches the registry.

Requires ROMs built into asm_repo_staging/build/ (dryrun_split.sh + make breaker
racer sprite_game + make testroms). ROM-backed tests skip cleanly when absent.
"""

import importlib.util
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import (
    load_manifest, register_bot, verify,
)
from infrastructure.test_harness.oracle_faults import (
    PROBES, fault_inject, probe_region, FaultError,
)

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
TEMPLATES = ROOT / "templates"
TESTS_DIR = Path(__file__).resolve().parent


# =============================================================================
# Part 1 — fault_inject unit tests (no emulator)
# =============================================================================

def _rom_for(probe_name):
    """The built good ROM a probe targets, by its registry `rom` basename."""
    return BUILD / (PROBES[probe_name].rom + ".sfc")


def test_unknown_probe_raises():
    with pytest.raises(FaultError):
        fault_inject(b"\x00" * 16, "no_such_probe")
    with pytest.raises(FaultError):
        probe_region("no_such_probe")


def test_every_probe_documents_a_real_output_region():
    """A FAIL-side proof can only name OAM/CGRAM/VRAM/screenshot/SRAM."""
    real = {"oam", "cgram", "vram", "screenshot", "sram"}
    for name, p in PROBES.items():
        assert p.region in real, f"{name}: region '{p.region}' is not a real output"


@pytest.mark.parametrize("probe_name", sorted(PROBES))
def test_missing_signature_raises(probe_name):
    """A buffer without the signature fails loudly (rebuild-drift guard)."""
    with pytest.raises(FaultError):
        fault_inject(b"\xAA" * 4096, probe_name)


@pytest.mark.parametrize("probe_name", sorted(PROBES))
def test_probe_is_unique_single_patch_on_real_rom(probe_name):
    """Against the actual built ROM: each probe's signature occurs exactly once,
    the byte at the patch offset equals the documented original, and fault_inject
    changes exactly N bytes (1 per patch; 2 for racer_freeze_steer)."""
    rom = _rom_for(probe_name)
    if not rom.exists():
        pytest.skip(f"{rom.name} not built")
    data = rom.read_bytes()
    p = PROBES[probe_name]

    for patch in p.patches:
        first = data.find(patch.signature)
        assert first >= 0, f"{probe_name}: signature absent"
        assert data.find(patch.signature, first + 1) < 0, \
            f"{probe_name}: signature is NOT unique"
        assert data[first + patch.offset] == patch.orig, \
            f"{probe_name}: orig byte drifted"

    out = fault_inject(data, probe_name)
    changed = [i for i, (a, b) in enumerate(zip(data, out)) if a != b]
    assert len(changed) == len(p.patches), \
        f"{probe_name}: changed {len(changed)} bytes, expected {len(p.patches)}"
    assert len(out) == len(data)


@pytest.mark.parametrize("probe_name", sorted(PROBES))
def test_drift_guard_rejects_already_patched_rom(probe_name):
    """Applying the same fault twice must fail (the orig byte no longer matches),
    proving the guard catches rebuild drift / double-application."""
    rom = _rom_for(probe_name)
    if not rom.exists():
        pytest.skip(f"{rom.name} not built")
    once = fault_inject(rom.read_bytes(), probe_name)
    with pytest.raises(FaultError):
        fault_inject(once, probe_name)


# =============================================================================
# Part 2 — ROM-backed B.6 FAIL-side proof
# =============================================================================

pytestmark = pytest.mark.skipif(
    not (BUILD / "breaker.sfc").exists(),
    reason="ROMs not built (dryrun_split.sh + make breaker racer sprite_game + make testroms)",
)


# Register the breaker win-bot by file path (dependency points test -> harness).

def _load_breaker_bot():
    path = TESTS_DIR / "_breaker_bot.py"
    spec = importlib.util.spec_from_file_location("_oracle_faults_breaker_bot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _breaker_winbot(runner, manifest, drive):
    mod = _load_breaker_bot()
    bot = mod.WinBot(runner)
    with runner.frame_stepping():
        won = bot.run(frame_cap=int(drive.params.get("frame_cap", 40000)),
                      wall_cap=float(drive.params.get("wall_cap", 400.0)))
        if won:
            runner.frame_step(3)
    return won


register_bot("breaker_winbot", _breaker_winbot)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# Each row: (probe, manifest path, ROM basename, scenario the fault breaks,
#            documented region the FAIL must name).
_PROOF_ROWS = [
    ("sprite_game_break_relocate", TEMPLATES / "sprite_game" / "oracle.json",
     "sprite_game.sfc", "catch_relocates_dot", "oam"),
    ("breaker_corrupt_brick_palette", TEMPLATES / "breaker" / "oracle.json",
     "breaker.sfc", "boots_field_rendered", "cgram"),
    ("breaker_skip_final_brick", TEMPLATES / "breaker" / "oracle.json",
     "breaker.sfc", "reach_win", "vram"),
    ("racer_freeze_steer", TEMPLATES / "racer" / "oracle.json",
     "racer.sfc", "steer_rotates_floor", "screenshot"),
    ("save_flip_byte", TESTS_DIR / "save_test.oracle.json",
     "save_test.sfc", "battery_persists_across_power_cycle", "sram"),
]


def _faulted_rom(tmp_path, probe_name, rom_basename, *, distinct=False):
    """Write the faulted ROM and return (rom_dir, faulted_basename).

    Normally the faulted ROM keeps the manifest's basename so verify(rom_dir=...)
    resolves manifest.rom.name to it. For the SRAM row we instead give it a
    DISTINCT basename: oracle._srm_path keys the battery file on the ROM stem, so
    a same-named faulted ROM shares Saves/<stem>.srm with the good run — and the
    still-loaded good ROM flushes its (correct) battery on the next load_rom,
    silently reseeding the faulted run and masking the off-by-one fault. A
    distinct stem gives the faulted run its own .srm. (Paper cut: .srm basename
    collision, Brick 5.)
    """
    good = (BUILD / rom_basename).read_bytes()
    bad = fault_inject(good, probe_name)
    d = tmp_path / probe_name
    d.mkdir()
    out_basename = rom_basename
    if distinct:
        out_basename = Path(rom_basename).stem + "_faulted" + Path(rom_basename).suffix
    (d / out_basename).write_bytes(bad)
    return d, out_basename


def _shorten_reach_win(manifest):
    """The skip-final-brick fault makes the win unreachable; cap the bot tight so
    the negative case is fast instead of running the full 400s wall_cap."""
    for sc in manifest.scenarios:
        if sc.drive.kind == "bot":
            sc.drive.params["frame_cap"] = 4000
            sc.drive.params["wall_cap"] = 60.0


@pytest.mark.parametrize(
    "probe_name,manifest_path,rom_basename,scenario,region",
    _PROOF_ROWS,
    ids=[r[0] for r in _PROOF_ROWS],
)
def test_fault_fails_naming_region(
    probe_name, manifest_path, rom_basename, scenario, region, runner, tmp_path
):
    if not manifest_path.exists():
        pytest.skip(f"{manifest_path.name} not present")
    if not (BUILD / rom_basename).exists():
        pytest.skip(f"{rom_basename} not built")

    from infrastructure.test_harness.oracle import _delete_srm
    is_save = rom_basename == "save_test.sfc"

    # --- positive control: the good ROM PASSES the scenario -----------------
    good_m = load_manifest(manifest_path)
    if is_save:
        _delete_srm(str(BUILD / rom_basename))  # virgin battery for the good run
    good_verdict = verify(good_m, runner, rom_dir=BUILD, only={scenario})
    assert good_verdict.passed, (
        f"positive control: good {rom_basename} should PASS '{scenario}', "
        f"got:\n" + "\n".join(
            e for sc in good_verdict.scenarios for e in sc.evidence)
    )

    # --- discrimination: the faulted ROM FAILS, naming the right region -----
    # SRAM row uses a distinct basename so it doesn't share the good run's .srm.
    faulted_dir, faulted_basename = _faulted_rom(
        tmp_path, probe_name, rom_basename, distinct=is_save)
    bad_m = load_manifest(manifest_path)
    bad_m.rom = str(Path(bad_m.rom).with_name(faulted_basename))
    if probe_name == "breaker_skip_final_brick":
        _shorten_reach_win(bad_m)
    if is_save:
        _delete_srm(str(faulted_dir / faulted_basename))  # virgin faulted battery

    bad_verdict = verify(bad_m, runner, rom_dir=faulted_dir, only={scenario})
    assert not bad_verdict.passed, (
        f"faulted {rom_basename} should FAIL '{scenario}' "
        f"({probe_region(probe_name)} corrupted) but PASSED — manifest too loose"
    )

    # The failing assert(s) must include one that read the documented region.
    failing_regions = {
        r.region_read.split("[")[0].split()[0].lower()
        for sc in bad_verdict.scenarios for r in sc.asserts if not r.ok
    }
    # region_read strings look like "OAM slot 1" / "CGRAM pal 0" / "VRAM[0x..]"
    # / "SRAM[0x..]" / "screenshot"; normalize to the region word.
    assert region in failing_regions, (
        f"{probe_name}: expected a FAIL naming region '{region}', "
        f"got failing regions {sorted(failing_regions)}\n"
        + "\n".join(e for sc in bad_verdict.scenarios for e in sc.evidence)
    )
