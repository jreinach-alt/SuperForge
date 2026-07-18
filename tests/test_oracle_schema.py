"""Brick 1 unit tests for the oracle manifest schema, loader, and validator.

Pure-Python — no emulator. Verifies (a) a well-formed manifest parses into the
typed dataclasses with addresses/values decoded, and (b) the load-time
discipline rejects exactly the manifests it should:

  * unknown drive/assert kinds (closed vocabulary)
  * a scenario with no assertions
  * an OUTCOME scenario asserting only on proxy/WRAM regions  (the load-bearing
    anti-indirect-evidence rule — a win cannot be proven by a state var alone)
  * state_is with no [state] block / a value outside state.values
  * duplicate scenario names

and that single-axis movement coverage produces a (non-fatal) warning.

Test surface: the feature under test is the manifest validator itself; the
"output region" each test reads is the ManifestError / warnings list it
produces. No ROM is driven at this brick.
"""

import json
from pathlib import Path

import pytest

from infrastructure.test_harness.oracle import (
    Manifest,
    ManifestError,
    load_manifest,
    parse_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle"


# --- helpers: minimal valid building blocks ---------------------------------

def _base(**overrides):
    """A minimal valid manifest dict; override pieces per test."""
    d = {
        "schema_version": 1,
        "template": "t",
        "rom": "build/t.sfc",
        "state": {
            "addr": "0xE016",
            "values": {"wait": 0, "play": 1, "over": 2, "win": 3},
            "win": "win",
            "lose": "over",
        },
        "scenario": [
            {
                "name": "renders",
                "drive": {"kind": "settle", "frames": 10},
                "assert": [{"kind": "oam_entry", "slot": 0, "x": 100}],
            }
        ],
    }
    d.update(overrides)
    return d


# --- happy path -------------------------------------------------------------

def test_valid_breaker_fixture_parses():
    m = load_manifest(FIXTURES / "valid_breaker.json")
    assert isinstance(m, Manifest)
    assert m.template == "breaker"
    assert m.rom == "build/breaker.sfc"
    # hex strings decode to ints
    assert m.boot.magic_addr == 0xE000
    assert m.boot.heartbeat_addr == 0x010C
    assert m.boot.magic == b"SFDB"
    assert m.state is not None
    assert m.state.addr == 0xE016
    assert m.state.values["win"] == 3
    assert m.state.win == "win"
    assert [s.name for s in m.scenarios] == [
        "boots_field_rendered", "paddle_both_directions", "reach_win"
    ]
    # the win scenario carries real-output asserts, so it is accepted
    win = m.scenarios[-1]
    assert any(a.region == "vram" for a in win.asserts)
    # axis_sweep covers both directions -> no axis-coverage warning
    assert not any("axis coverage" in w for w in m.warnings)


def test_template_defaults_from_path(tmp_path):
    # Both template AND rom default from a canonical templates/<X>/oracle.json
    # home (GAP-1 path-pinning): drop both fields and they derive from the dir.
    d = _base()
    del d["template"]
    del d["rom"]
    p = tmp_path / "duck" / "oracle.json"
    p.parent.mkdir()
    p.write_text(json.dumps(d))
    m = load_manifest(p)
    assert m.template == "duck"
    assert m.rom == "build/duck.sfc"


# --- GAP-1: path-pinned identity (copied-oracle false-green guard) ----------
# The cold-start trap: copy templates/rpg/oracle.json -> templates/starstation/
# WITHOUT re-pointing its "rom":"build/rpg.sfc"/"template":"rpg". The auto-
# discovery harness would then drive the SOURCE rom, PASS, and never test the
# new template — a silent false-green. These guards prove the loader now rejects
# that mismatch LOUDLY at load time, before any ROM runs.

def _write_canonical(tmp_path, template_dir, **overrides):
    """Write a templates/<template_dir>/oracle.json under tmp_path and return it."""
    d = _base(**overrides)
    p = tmp_path / "templates" / template_dir / "oracle.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(d))
    return p


def test_stale_rom_field_is_rejected_loudly(tmp_path):
    # The exact cold-start trap: a starstation oracle still pointing at the rpg ROM.
    p = _write_canonical(tmp_path, "starstation",
                         template="starstation", rom="build/rpg.sfc")
    with pytest.raises(ManifestError) as ei:
        load_manifest(p)
    msg = str(ei.value)
    assert "build/rpg.sfc" in msg          # names the wrong ROM
    assert "build/starstation.sfc" in msg  # names what it should be
    assert "RE-POINTED" in msg             # tells the adapter what to do


def test_stale_template_field_is_rejected_loudly(tmp_path):
    # template still says "rpg" inside a starstation/ dir.
    p = _write_canonical(tmp_path, "starstation",
                         template="rpg", rom="build/starstation.sfc")
    with pytest.raises(ManifestError) as ei:
        load_manifest(p)
    msg = str(ei.value)
    assert "'rpg'" in msg and "starstation" in msg
    assert "RE-POINTED" in msg


def test_fully_stale_copy_is_rejected_loudly(tmp_path):
    # A verbatim copy (BOTH fields stale) — the literal copy-and-forget case.
    p = _write_canonical(tmp_path, "starstation",
                         template="rpg", rom="build/rpg.sfc")
    with pytest.raises(ManifestError):
        load_manifest(p)


def test_matching_fields_still_load(tmp_path):
    # The corrected oracle (re-pointed) loads cleanly — the guard only fires on
    # a mismatch, never on a correctly-pointed manifest.
    p = _write_canonical(tmp_path, "starstation",
                         template="starstation", rom="build/starstation.sfc")
    m = load_manifest(p)
    assert m.template == "starstation"
    assert m.rom == "build/starstation.sfc"


def test_test_sibling_oracle_identity_is_pinned(tmp_path):
    # The tests/<Y>.oracle.json home pins identity too (e.g. save_test).
    d = _base(template="save_test", rom="build/wrong.sfc")
    p = tmp_path / "tests" / "save_test.oracle.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(d))
    with pytest.raises(ManifestError) as ei:
        load_manifest(p)
    assert "build/wrong.sfc" in str(ei.value)
    assert "build/save_test.sfc" in str(ei.value)


# --- closed vocabulary ------------------------------------------------------

def test_unknown_assert_kind_rejected():
    d = _base()
    d["scenario"][0]["assert"] = [{"kind": "read_wram_var", "addr": "0x10"}]
    with pytest.raises(ManifestError, match="unknown assert kind"):
        parse_manifest(d)


def test_unknown_drive_kind_rejected():
    d = _base()
    d["scenario"][0]["drive"] = {"kind": "teleport"}
    with pytest.raises(ManifestError, match="unknown drive kind"):
        parse_manifest(d)


# --- structural rules -------------------------------------------------------

def test_scenario_with_no_asserts_rejected():
    d = _base()
    d["scenario"][0]["assert"] = []
    with pytest.raises(ManifestError, match="no assertions"):
        parse_manifest(d)


def test_duplicate_scenario_names_rejected():
    d = _base()
    d["scenario"].append(dict(d["scenario"][0]))
    with pytest.raises(ManifestError, match="duplicate scenario name"):
        parse_manifest(d)


def test_empty_scenario_list_rejected():
    d = _base(scenario=[])
    with pytest.raises(ManifestError, match="non-empty 'scenario'"):
        parse_manifest(d)


def test_unsupported_schema_version_rejected():
    d = _base(schema_version=99)
    with pytest.raises(ManifestError, match="schema_version"):
        parse_manifest(d)


# --- the anti-indirect-evidence discipline (load-bearing) -------------------

def test_outcome_scenario_with_only_state_is_rejected():
    """A win scenario proven solely by the state variable is tautological."""
    d = _base()
    d["scenario"][0] = {
        "name": "reach_win",
        "drive": {"kind": "script", "frames": [{"buttons": ["a"]}]},
        "assert": [{"kind": "state_is", "value": "win"}],
    }
    with pytest.raises(ManifestError, match="indirect-evidence"):
        parse_manifest(d)


def test_bot_outcome_with_only_proxy_asserts_rejected():
    """A bot/search scenario is outcome-class by its drive kind alone."""
    d = _base()
    d["scenario"][0] = {
        "name": "auto_win",
        "drive": {"kind": "bot", "policy": "p"},
        "assert": [{"kind": "heartbeat_advances", "addr": "0x010C"}],
    }
    with pytest.raises(ManifestError, match="outcome scenario"):
        parse_manifest(d)


def test_outcome_scenario_with_real_region_accepted():
    """state_is win + a VRAM read is the correct, accepted shape."""
    d = _base()
    d["scenario"][0] = {
        "name": "reach_win",
        "drive": {"kind": "bot", "policy": "p"},
        "assert": [
            {"kind": "state_is", "value": "win"},
            {"kind": "vram_tilemap_count", "base": "0xB000", "expect_count": 0},
        ],
    }
    m = parse_manifest(d)
    assert m.scenarios[0].name == "reach_win"


def test_non_outcome_proxy_only_scenario_allowed():
    """A boot/heartbeat sanity scenario (not win/lose) may be WRAM-only."""
    d = _base()
    d["scenario"][0] = {
        "name": "is_alive",
        "drive": {"kind": "settle", "frames": 10},
        "assert": [{"kind": "heartbeat_advances", "addr": "0x010C"}],
    }
    m = parse_manifest(d)  # must not raise
    assert not m.warnings


# --- state references -------------------------------------------------------

def test_state_is_without_state_block_rejected():
    d = _base()
    del d["state"]
    d["scenario"][0]["assert"] = [{"kind": "state_is", "value": "win"}]
    with pytest.raises(ManifestError, match="no \\[state\\] block"):
        parse_manifest(d)


def test_state_is_unknown_value_rejected():
    d = _base()
    d["scenario"][0]["assert"] = [
        {"kind": "state_is", "value": "victory"},
        {"kind": "oam_entry", "slot": 0},
    ]
    with pytest.raises(ManifestError, match="not one of state.values"):
        parse_manifest(d)


def test_state_win_label_must_exist():
    d = _base()
    d["state"]["win"] = "nonexistent"
    with pytest.raises(ManifestError, match="state.win"):
        parse_manifest(d)


# --- soft rule: both-directions coverage ------------------------------------

def test_single_axis_hold_warns_not_fatal():
    d = _base()
    d["scenario"][0] = {
        "name": "move_right",
        "drive": {"kind": "hold", "buttons": ["right"], "frames": 20},
        "assert": [{"kind": "oam_delta", "slot": 0, "field": "x", "min": 10}],
    }
    m = parse_manifest(d)  # must not raise
    assert any("axis coverage" in w and "right" in w for w in m.warnings)


def test_both_directions_no_warning():
    d = _base()
    d["scenario"] = [
        {"name": "r", "drive": {"kind": "hold", "buttons": ["right"], "frames": 5},
         "assert": [{"kind": "oam_entry", "slot": 0}]},
        {"name": "l", "drive": {"kind": "hold", "buttons": ["left"], "frames": 5},
         "assert": [{"kind": "oam_entry", "slot": 0}]},
    ]
    m = parse_manifest(d)
    assert not any("axis coverage" in w for w in m.warnings)


# --- loader IO --------------------------------------------------------------

def test_missing_file_raises_manifest_error():
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(FIXTURES / "does_not_exist.json")


def test_malformed_json_raises_manifest_error():
    with pytest.raises(ManifestError, match="invalid JSON"):
        load_manifest(FIXTURES / "malformed.json")
