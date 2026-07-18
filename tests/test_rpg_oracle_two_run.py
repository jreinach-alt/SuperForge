"""Two-run SRAM-isolation regression guard for the rpg oracle (H1).

This is the minimal reproduction of the SRAM-contamination defect audit-1
found (docs/audit/r3-rpg-template-audit-1.md, deliverable 2): the rpg oracle's
last scenario (save_persists_after_power_cycle, a power_cycle that
continues_from_previous a save) leaves a VALID town save sitting in the
process-global emulator's LIVE battery SRAM. On a SECOND oracle run in the same
process, scenario 0/1 use fresh_sram to reset to a virgin overworld — but a BARE
unlink of the .srm is defeated by the unload-flush trap: the next load_rom
unloads the still-loaded save-carrying rpg ROM, re-flushing its live SRAM to
disk AFTER the delete, resurrecting the save → the ROM boots into the TOWN and
the overworld-sky / state==overworld asserts FAIL.

The fix (oracle._virgin_srm + the rpg fixture's virgin_srm) flushes the live
SRAM through a NEUTRAL ROM before deleting, so the reset is robust. This test
proves it: run the rpg oracle TWICE on one runner and assert BOTH pass.

Against the OLD bare-unlink oracle, run 2 fails (boots_into_..._overworld and
corrupt_save_falls_back_to_fresh_overworld both FAIL — the floor pixel is town
gray and state==town). Against the fixed oracle, run 2 is byte-for-byte as clean
as run 1. This guard is the proof the bare unlink lacked.

Test surface: the rpg oracle's own real-output-region asserts (rendered
framebuffer pixels + state mirror + OAM + SRAM bytes — see the manifest). The
state cycle exercised is the cross-run one: run 1 ends with a save in live SRAM
(power_cycle scenario), run 2 must re-virgin from that contaminated state. This
is exactly the "state-cycle coverage" discipline (CLAUDE.md, Sprint D-9) applied
to the across-run axis the single-run oracle never walked.

Skips cleanly when build/rpg.sfc + the neutral ROM are absent.
"""

from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import load_manifest, verify

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
TEMPLATES = ROOT / "templates"
RPG_MANIFEST = TEMPLATES / "rpg" / "oracle.json"


pytestmark = pytest.mark.skipif(
    not (BUILD / "rpg.sfc").exists() or not (BUILD / "text_test.sfc").exists()
    or not RPG_MANIFEST.exists(),
    reason="rpg.sfc / text_test.sfc / rpg oracle not built "
           "(dryrun_split.sh + make rpg + make testroms)",
)


def _evidence(verdict):
    lines = [f"oracle '{verdict.template}' FAILED:"]
    for sc in verdict.scenarios:
        mark = "ok" if sc.ok else "FAIL"
        lines.append(f"  scenario '{sc.name}': {mark}")
        if not sc.ok:
            lines.extend(f"    - {e}" for e in sc.evidence)
    return "\n".join(lines)


def test_rpg_oracle_passes_twice_on_one_runner():
    """Run the full rpg oracle TWICE on a single process-global runner. Run 1
    ends with a valid town save in LIVE SRAM (the power_cycle scenario); run 2
    must re-virgin past that contaminated live SRAM and pass identically. A bare
    unlink resurrects the save via the unload-flush and fails run 2 — this guard
    is the regression that catches it."""
    manifest = load_manifest(RPG_MANIFEST)
    runner = MesenRunner()
    try:
        run1 = verify(manifest, runner, rom_dir=BUILD)
        # run1 leaves the rpg ROM loaded with a valid save banked in live SRAM
        # (scenario save_persists_after_power_cycle). The SECOND run is the trap.
        run2 = verify(manifest, runner, rom_dir=BUILD)
    finally:
        runner.stop()

    assert run1.passed, "rpg oracle run 1 failed:\n" + _evidence(run1)
    # The contamination defect manifests ONLY on run 2 — this is the load-bearing
    # assertion. If it fails with boots/corrupt scenarios booting TOWN, the
    # fresh_sram reset was defeated by the unload-flush (H1 regressed).
    assert run2.passed, (
        "rpg oracle run 2 failed — SRAM isolation regressed; a save from run 1's "
        "power_cycle leaked into run 2's virgin boot:\n" + _evidence(run2)
    )
