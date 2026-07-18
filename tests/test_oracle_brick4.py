"""Brick 4 verify: bot drive, power_cycle + SRAM asserts, and determinism.

Reproduces proof-plan rows 3 (breaker win via the closed-loop bot) and 5
(battery SRAM persists across a power cycle), and exercises the determinism
re-run ("script twice -> byte-identical").

The breaker win-bot (tests/_breaker_bot.py) is loaded by file path and
registered via oracle.register_bot — the harness never imports the bot itself
(dependency points test -> harness). Requires ROMs built into
asm_repo_staging/build/ (dryrun_split.sh + make breaker sprite_game save_test).
"""

import importlib.util
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness.oracle import load_manifest, register_bot, verify

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle"
TESTS_DIR = Path(__file__).resolve().parent


def _have(name):
    return (BUILD / name).exists()


pytestmark = pytest.mark.skipif(
    not _have("breaker.sfc"),
    reason="ROMs not built (dryrun_split.sh + make breaker sprite_game save_test)",
)


# --- load + register the breaker win-bot by file path (portable) ------------

def _load_breaker_bot():
    path = TESTS_DIR / "_breaker_bot.py"
    spec = importlib.util.spec_from_file_location("_oracle_breaker_bot", path)
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
            runner.frame_step(3)  # let the final NMI commit the brick-clear DMA
    return won


register_bot("breaker_winbot", _breaker_winbot)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _fail_evidence(verdict):
    return " | ".join(e for s in verdict.scenarios if not s.ok for e in s.evidence)


# === Row 3: breaker win via the closed-loop bot =============================

def test_row3_breaker_win_bot(runner):
    m = load_manifest(FIXTURES / "valid_breaker.json")
    v = verify(m, runner, rom_dir=BUILD, only={"reach_win"})
    assert v.passed, _fail_evidence(v)
    # the scenario asserts on real output: bricks gone in VRAM + "YOU WIN!" BG3
    sc = v.scenarios[0]
    kinds = {a.kind for a in sc.asserts}
    assert {"state_is", "vram_tilemap_count", "bg3_text"} <= kinds


# === Row 5: SRAM persistence across a power cycle ============================

def test_row5_save_persists_across_power_cycle(runner):
    if not _have("save_test.sfc"):
        pytest.skip("save_test.sfc not built")
    m = load_manifest(FIXTURES / "save.json")
    v = verify(m, runner, rom_dir=BUILD)
    assert v.passed, _fail_evidence(v)
    # the verdict's evidence shows the independent CRC cross-check passed
    ev = " ".join(e for s in v.scenarios for e in s.evidence)
    assert "crc16: ok" in ev


def test_row5_fault_flipped_byte_fails_on_sram(runner):
    if not _have("save_test.sfc"):
        pytest.skip("save_test.sfc not built")
    m = load_manifest(FIXTURES / "save.json")
    sc = m.scenarios[0]
    payload = next(a for a in sc.asserts
                   if a.kind == "sram_bytes" and "bytes" in a.params)
    payload.params["bytes"][0] ^= 0xFF  # flip a saved byte's expectation
    v = verify(m, runner, rom_dir=BUILD)
    assert not v.passed
    ev = _fail_evidence(v)
    assert "sram_bytes: FAIL" in ev and "[SRAM" in ev


# === Determinism: same script twice -> byte-identical hardware state ========

def test_determinism_script_twice_byte_identical(runner):
    if not _have("sprite_game.sfc"):
        pytest.skip("sprite_game.sfc not built")
    m = load_manifest(FIXTURES / "sprite_game.json")
    v = verify(m, runner, rom_dir=BUILD,
               only={"catch_relocates_dot"}, determinism=True)
    assert v.passed, _fail_evidence(v)
    assert v.determinism_ok is True
