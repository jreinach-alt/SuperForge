"""H3 (the C2 delivery): `OamClaim.at` — pinned OAM slot ranges.

OAM index order IS sprite-vs-sprite priority (lowest index in front), so a
claim's position in the table is user-visible render order — and before this
field, front-of-table position was an ACCIDENT of the (-sprites, name)
packing sort. The pin makes it a declaration: this slice's HUD pips pin
`at = 0` so they render over both heroes by contract, not by luck.

Scope discipline: this is the SMALLEST honest H3 extension (the
BytesClaim.at precedent). The full priority/size-class vocabulary the spec
H3 describes is deliberately not built here.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate  # noqa: E402
from schemas import SchemaError, StateDecl, load_feature, load_manifest, \
    load_substrate  # noqa: E402

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
NO_STATE = StateDecl((), {})


def feature(tmp_path, name, body=""):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "feature"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, text):
    p = tmp_path / "game.toml"
    p.write_text(text)
    return load_manifest(p)


def oam_of(alloc, scene):
    return {p.name: (p.start, p.size)
            for p in [*alloc.globals_map, *alloc.scenes[scene].placements]
            if p.cls == "oam"}


def test_pinned_range_is_honored_and_packing_flows_around_it(tmp_path):
    """The this slice shape: hud pins slots 0..7, the heroes pack behind."""
    hud = feature(tmp_path, "hud",
                  '[[claims.oam]]\nname = "pips"\nsprites = 8\nat = 0\n')
    heroes = feature(tmp_path, "heroes",
                     '[[claims.oam]]\nname = "hero"\nsprites = 1\n'
                     '[[claims.oam]]\nname = "hero2"\nsprites = 1\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["hud", "heroes"]\n')
    alloc = allocate(SUB, {"hud": hud, "heroes": heroes}, NO_STATE, man)
    got = oam_of(alloc, "s")
    assert got["pips"] == (0, 8), "the pin was displaced"
    assert got["hero"] == (8, 1) and got["hero2"] == (9, 1), \
        "packed claims must flow around the carved pin"


def test_a_mid_table_pin_carves_a_hole_packing_respects(tmp_path):
    big = feature(tmp_path, "big", '[[claims.oam]]\nname = "wall"\nsprites = 4\nat = 2\n')
    small = feature(tmp_path, "small", '[[claims.oam]]\nname = "spr"\nsprites = 4\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["big", "small"]\n')
    got = oam_of(allocate(SUB, {"big": big, "small": small}, NO_STATE, man), "s")
    assert got["wall"] == (2, 4)
    assert got["spr"] == (6, 4), "first fit AFTER the carved range (hole 0..2 too small)"


def test_overlapping_pins_refuse_with_the_pin_named(tmp_path):
    a = feature(tmp_path, "a", '[[claims.oam]]\nname = "front"\nsprites = 8\nat = 0\n')
    b = feature(tmp_path, "b", '[[claims.oam]]\nname = "also_front"\nsprites = 4\nat = 4\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["a", "b"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"a": a, "b": b}, NO_STATE, man)
    msg = str(e.value)
    assert "OAM claim 'also_front'" in msg and "pinned slot range 4..8" in msg, msg


def test_pin_against_a_global_claim_refuses_across_scopes(tmp_path):
    """The scene free list forks the globals', so a scene pin landing on a
    global claim's slots is caught by the same carve."""
    g = feature(tmp_path, "g", '[[claims.oam]]\nname = "gspr"\nsprites = 2\nat = 0\n')
    s = feature(tmp_path, "s", '[[claims.oam]]\nname = "sspr"\nsprites = 2\nat = 1\n')
    man = manifest(tmp_path,
                   'globals = ["g"]\n[[scene]]\nid = "x"\nfeatures = ["s"]\n')
    with pytest.raises(AllocationError, match="sspr"):
        allocate(SUB, {"g": g, "s": s}, NO_STATE, man)


def test_pin_past_the_sprite_table_refuses(tmp_path):
    a = feature(tmp_path, "a",
                f'[[claims.oam]]\nname = "oob"\nsprites = 4\nat = {SUB.oam_sprites - 2}\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["a"]\n')
    with pytest.raises(AllocationError, match="oob"):
        allocate(SUB, {"a": a}, NO_STATE, man)


def test_no_pins_means_the_old_packing_exactly(tmp_path):
    """Existing compositions must be byte-identical: with no `at` anywhere,
    the (-sprites, name) sort and first-fit produce the same table the
    pre-pin algorithm did. (The whole-ROM proof is the pinned microzero md5;
    this is the unit-level statement of why it holds.)"""
    a = feature(tmp_path, "a",
                '[[claims.oam]]\nname = "car"\nsprites = 4\n'
                '[[claims.oam]]\nname = "aaa"\nsprites = 1\n')
    b = feature(tmp_path, "b", '[[claims.oam]]\nname = "dust"\nsprites = 4\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["a", "b"]\n')
    got = oam_of(allocate(SUB, {"a": a, "b": b}, NO_STATE, man), "s")
    assert got == {"car": (0, 4), "dust": (4, 4), "aaa": (8, 1)}


def test_negative_at_is_a_schema_error(tmp_path):
    d = tmp_path / "neg"
    d.mkdir()
    (d / "feature.toml").write_text(
        'name = "neg"\nrole = "feature"\n[[claims.oam]]\nsprites = 1\nat = -1\n')
    with pytest.raises(SchemaError, match="at must be non-negative"):
        load_feature(d / "feature.toml", SUB)
