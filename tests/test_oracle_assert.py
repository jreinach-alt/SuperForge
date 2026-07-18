"""Brick 2 verify for the oracle assert engine.

Points each implemented assert kind at the committed-good breaker.sfc at boot
and confirms the values match the breaker gate's hard-coded expectations
(proof-plan row 2, boot-only). Each assert is also exercised with a deliberately
wrong expectation to prove it can FAIL — a pass-only test would be
indirect-evidence about the assert itself.

Requires the ROMs to be built first:
    cd <materialized kit> && make breaker racer   (or run tools/dryrun_split.sh)
then copy build/*.sfc into asm_repo_staging/build/. The test skips if absent so
CI/others can gate it behind a build step.

Test surface: feature under test is the assert engine; the output regions read
are VRAM tilemap bytes, CGRAM palette bytes, and OAM entry bytes of a real
booted ROM — never a proxy variable.
"""

from pathlib import Path

import pytest

from dataclasses import replace

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import (
    REGION_OF_ASSERT,
    REAL_OUTPUT_REGIONS,
    Assert,
    boot_check,
    evaluate_assert,
    load_manifest,
)

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle"

pytestmark = pytest.mark.skipif(
    not (BUILD / "breaker.sfc").exists(),
    reason="build/breaker.sfc not built (run dryrun_split.sh + make breaker)",
)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def breaker_manifest():
    return load_manifest(FIXTURES / "valid_breaker.json")


def _boot(runner, manifest):
    runner.load_rom(str(BUILD / Path(manifest.rom).name), run_seconds=0.5)


# --- boot precondition ------------------------------------------------------

def test_boot_magic(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    assert boot_check(runner, breaker_manifest).ok


# --- the boot scenario's asserts all pass on the good ROM -------------------

def test_boot_scenario_asserts_pass(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    scenario = breaker_manifest.scenarios[0]
    assert scenario.name == "boots_field_rendered"
    for a in scenario.asserts:
        res = evaluate_assert(runner, a, breaker_manifest)
        assert res.ok, f"{a.kind} should pass on good ROM: {res.detail}"
        # every boot assert reads a real output region, not a proxy
        assert res.region_read


# --- each assert kind can also FAIL (not pass-only) -------------------------

def test_vram_tilemap_count_detects_wrong_count(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    a = Assert("vram_tilemap_count", {
        "base": "0xB000", "row_stride": 64, "rows": [5, 6, 7, 8, 9, 10],
        "cols": "1..31", "tile_in": [2, 3, 4, 5], "expect_count": 179,  # wrong
    })
    res = evaluate_assert(runner, a, breaker_manifest)
    assert not res.ok and "180" in res.detail


def test_cgram_palette_detects_wrong_color(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    a = Assert("cgram_palette", {"palette": 0, "colors": {"1": "0x1234"}})
    res = evaluate_assert(runner, a, breaker_manifest)
    assert not res.ok and "entry 1" in res.detail


def test_oam_entry_detects_wrong_field(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    a = Assert("oam_entry", {"slot": 3, "tile": 99})  # ball tile is 1
    res = evaluate_assert(runner, a, breaker_manifest)
    assert not res.ok and "tile" in res.detail


def test_state_is_reads_state_byte(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    ok_res = evaluate_assert(runner, Assert("state_is", {"value": "wait"}),
                             breaker_manifest)
    assert ok_res.ok, ok_res.detail
    bad_res = evaluate_assert(runner, Assert("state_is", {"value": "win"}),
                              breaker_manifest)
    assert not bad_res.ok


# --- deferred kinds report cleanly, not crash -------------------------------

def test_deferred_kind_reports_not_implemented(runner, breaker_manifest):
    _boot(runner, breaker_manifest)
    # screenshot_text is still unimplemented (lands in a later brick).
    res = evaluate_assert(runner, Assert("screenshot_text", {"text": "HI"}),
                          breaker_manifest)
    assert not res.ok and "not implemented yet" in res.detail


# --- a second ROM boots and passes its magic --------------------------------

def test_racer_boots(runner):
    racer = load_manifest(FIXTURES / "valid_breaker.json")  # reuse boot block
    racer.rom = "build/racer.sfc"
    if not (BUILD / "racer.sfc").exists():
        pytest.skip("racer.sfc not built")
    runner.load_rom(str(BUILD / "racer.sfc"), run_seconds=0.5)
    assert boot_check(runner, racer).ok


# --- heartbeat_advances (audit-1 finding D) ---------------------------------
# The breaker manifest declares boot.heartbeat_addr=0x010C. The assert reads
# that 16-bit WRAM counter, runs N frames, reads again, and requires a strict
# advance. It is a liveness PROXY (region 'wram'), so it can never satisfy an
# outcome scenario — verified below — but it must genuinely read the running
# counter (output region: WRAM[heartbeat_addr]), not a downstream proxy of it.

def test_heartbeat_classified_as_proxy_not_real_output():
    # Anti-indirect-evidence invariant: heartbeat_advances stays a wram proxy.
    assert REGION_OF_ASSERT["heartbeat_advances"] == "wram"
    assert "wram" not in REAL_OUTPUT_REGIONS


def test_heartbeat_advances_on_running_rom(runner, breaker_manifest):
    # PASS: the live boot heartbeat counter strictly advances over frames.
    _boot(runner, breaker_manifest)
    res = evaluate_assert(runner, Assert("heartbeat_advances", {"frames": 10}),
                          breaker_manifest)
    assert res.ok, res.detail
    assert res.region_read == f"WRAM[{hex(breaker_manifest.boot.heartbeat_addr)}]"


def test_heartbeat_advances_fails_on_static_address(runner, breaker_manifest):
    # FAIL (discriminating): point the heartbeat at a static WRAM address that
    # does not tick (the boot magic at 0xE000 — written once at init, then
    # constant). A real liveness assert must NOT pass on a frozen counter.
    static_boot = replace(breaker_manifest.boot,
                          heartbeat_addr=breaker_manifest.boot.magic_addr)
    static_manifest = replace(breaker_manifest, boot=static_boot)
    _boot(runner, static_manifest)
    res = evaluate_assert(runner, Assert("heartbeat_advances", {"frames": 10}),
                          static_manifest)
    assert not res.ok and "stalled" in res.detail
