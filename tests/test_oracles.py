"""Parametrized oracle harness — Brick 5 of the generalized verification loop
(spec: docs/snes_homebrew_oracle_loop_spec.md §B.3, §B.7).

This is the single test module that replaces the per-template run-gates'
*structure*: it discovers every ``oracle.json`` manifest shipped next to a
template (or, for test-ROM-backed gates like save/SRAM, as a
``<rom>.oracle.json`` sibling), loads + validates it (the anti-indirect-evidence
validator runs at load time), then drives the ROM through the generic harness
and asserts the verdict passed. The per-template asserts live in the manifests
themselves — closed-vocabulary, real-output-region reads only.

Bots are GAME-SPECIFIC and stay bespoke (spec B.2): the breaker win-bot is
loaded by file path and registered via ``oracle.register_bot`` — the harness
never imports the bot itself (Brick 4 contract: the dependency points
test -> harness, never the reverse). The loader idiom mirrors
``tests/test_oracle_brick4.py``.

Requires ROMs built into ``build/`` (dryrun_split.sh + make breaker racer
sprite_game + make testroms). Each manifest's scenarios skip cleanly when its
ROM is absent, matching the existing oracle tests' skip guard.
"""

import importlib.util
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner
from infrastructure.test_harness import oracle
from infrastructure.test_harness.oracle import load_manifest, verify

# The kit/staging root that owns templates/ + tests/ + build/. This module
# lives at <root>/tests/test_oracles.py, so the root is its parent's parent.
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
TESTS_DIR = Path(__file__).resolve().parent


# --- register the game-specific bots the manifests reference ----------------
# Loaded by file path so the harness carries no bot dependency (Brick 4).

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


oracle.register_bot("breaker_winbot", _breaker_winbot)


# --- discover the shipped manifests -----------------------------------------
# discover() infers its root from oracle.py's location, which differs between
# the staging tree (parent repo) and the materialized kit; pass our own root so
# it resolves templates/ + tests/ relative to THIS repo regardless of cwd.

_MANIFESTS = oracle.discover(root=ROOT)


def _manifest_id(path: Path) -> str:
    # templates/breaker/oracle.json -> breaker ; tests/save_test.oracle.json -> save_test
    if path.name == "oracle.json":
        return path.parent.name
    return path.name[: -len(".oracle.json")] if path.name.endswith(".oracle.json") \
        else path.stem


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.mark.skipif(not _MANIFESTS, reason="no oracle.json manifests discovered")
@pytest.mark.parametrize("manifest_path", _MANIFESTS, ids=_manifest_id)
def test_oracle_manifest(manifest_path, runner):
    manifest = load_manifest(manifest_path)            # validates at load time

    rom = BUILD / Path(manifest.rom).name
    if not rom.exists():
        pytest.skip(f"{rom.name} not built — run dryrun_split.sh + make")

    verdict = verify(manifest, runner, rom_dir=BUILD)

    if not verdict.passed:
        lines = [f"oracle '{verdict.template}' FAILED:"]
        for sc in verdict.scenarios:
            mark = "ok" if sc.ok else "FAIL"
            lines.append(f"  scenario '{sc.name}': {mark}")
            if not sc.ok:
                lines.extend(f"    - {e}" for e in sc.evidence)
        pytest.fail("\n".join(lines))


def test_discover_finds_the_template_manifests():
    """discover() picks up every template oracle + the save sibling."""
    ids = {_manifest_id(p) for p in _MANIFESTS}
    assert {"breaker", "racer", "sprite_game", "save_test"} <= ids, \
        f"discover() missed manifests; found {sorted(ids)}"
