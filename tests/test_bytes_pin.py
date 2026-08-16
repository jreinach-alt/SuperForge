"""BytesClaim.at — pinned dp/wram placement (this slice, G1 Option A).

Why the field exists: a vendored unit whose CPU-side variables are laid out
by the LINKER (TAD's ca65 `.bss`/`.zeropage` — 16 B + 2 B) needs the
allocator to own the addresses anyway, or the region is invisible to every
collision check (this engine paid twice for exactly that: its hand-managed
TAD_BSS window was double-booked once and collided with VWF scratch once).
The pin puts the range inside the allocator's arbitration; the game cfg's
memory window carries the same value and an lderror assert in the feature's
wrapper refuses the build if the two ever disagree.

Test surface: the allocator's verdict + diagnostic + placement/symbol
values — these are allocator tests; the ROM-level surface is this slice's.
The refusal tests double as the falsification pass: each gate is shown
failing on a real violation, not assumed.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate, emit  # noqa: E402
from schemas import SchemaError, StateDecl, load_feature, load_manifest, \
    load_substrate  # noqa: E402

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
NO_STATE = StateDecl((), {})


def feature(tmp_path, name, body="", role="fixture"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "{role}"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, scenes, globals_=()):
    lines = []
    if globals_:
        lines.append("globals = [" + ", ".join(f'"{n}"' for n in globals_) + "]")
    for sid, feats in scenes:
        lines.append(f'[[scene]]\nid = "{sid}"\nfeatures = ['
                     + ", ".join(f'"{n}"' for n in feats) + "]")
    p = tmp_path / "game.toml"
    p.write_text("\n".join(lines) + "\n")
    return load_manifest(p)


def compose(tmp_path, feats, scenes, globals_=()):
    reg = {f.name: f for f in feats}
    return allocate(SUB, reg, NO_STATE, manifest(tmp_path, scenes, globals_))


# -- schema ------------------------------------------------------------------

def test_at_accepted_on_wram_and_dp(tmp_path):
    f = feature(tmp_path, "aud",
                '[[claims.wram]]\nname = "tad_bss"\nbytes = 16\nat = 0x1F00\n'
                '[[claims.dp]]\nname = "tad_zp"\nbytes = 2\nat = 0xF0\n')
    assert f.wram[0].at == 0x1F00
    assert f.dp[0].at == 0xF0


def test_negative_at_refused(tmp_path):
    with pytest.raises(SchemaError, match="at must be non-negative"):
        feature(tmp_path, "bad",
                '[[claims.wram]]\nname = "x"\nbytes = 4\nat = -1\n')


def test_unpinned_claims_unchanged(tmp_path):
    f = feature(tmp_path, "plain", '[[claims.wram]]\nname = "x"\nbytes = 4\n')
    assert f.wram[0].at is None


# -- placement ---------------------------------------------------------------

def test_pin_places_exactly_there(tmp_path):
    a = feature(tmp_path, "aud",
                '[[claims.wram]]\nname = "tad_bss"\nbytes = 16\nat = 0x1F00\n'
                '[[claims.dp]]\nname = "tad_zp"\nbytes = 2\nat = 0xF0\n')
    alloc = compose(tmp_path, [a], [("s", [])], globals_=["aud"])
    got = {p.name: p for p in alloc.globals_map}
    assert got["tad_bss"].start == 0x1F00 and got["tad_bss"].end == 0x1F10
    assert got["tad_zp"].start == 0xF0 and got["tad_zp"].end == 0xF2


def test_pin_survives_bigger_packed_claims(tmp_path):
    # Packing is largest-first; the pin must not be displaced by a larger
    # packed claim, and the packed claim must flow around the carved range.
    a = feature(tmp_path, "aud",
                '[[claims.wram]]\nname = "pin"\nbytes = 16\nat = 0x0300\n')
    b = feature(tmp_path, "big",
                '[[claims.wram]]\nname = "blob"\nbytes = 1024\n')
    alloc = compose(tmp_path, [a, b], [("s", [])], globals_=["aud", "big"])
    got = {p.name: p for p in alloc.globals_map}
    assert got["pin"].start == 0x0300
    blob = got["blob"]
    assert not (blob.start < 0x0310 and 0x0300 < blob.end), \
        f"packed claim overlaps the pin: [{blob.start:#x}..{blob.end:#x})"


def test_overlapping_pins_refuse_with_the_pin_named(tmp_path):
    a = feature(tmp_path, "one",
                '[[claims.wram]]\nname = "pa"\nbytes = 16\nat = 0x1F00\n')
    b = feature(tmp_path, "two",
                '[[claims.wram]]\nname = "pb"\nbytes = 16\nat = 0x1F08\n')
    with pytest.raises(AllocationError, match=r"pb.*not free|not free.*pb"):
        compose(tmp_path, [a, b], [("s", [])], globals_=["one", "two"])


def test_pin_inside_system_reserved_low_refuses(tmp_path):
    a = feature(tmp_path, "low",
                '[[claims.wram]]\nname = "p"\nbytes = 16\nat = 0x0100\n')
    with pytest.raises(AllocationError, match="not free"):
        compose(tmp_path, [a], [("s", [])], globals_=["low"])


def test_pinned_dma_source_may_not_cross_wram_bank(tmp_path):
    a = feature(tmp_path, "x",
                '[[claims.wram]]\nname = "p"\nbytes = 16\nat = 0xFFF8\n'
                'dma_source = true\n')
    with pytest.raises(AllocationError, match="crosses"):
        compose(tmp_path, [a], [("s", [])], globals_=["x"])


def test_scene_scoped_pin_collides_with_global(tmp_path):
    # The scene freelist is a copy of the global one, so a scene pin landing
    # on a GLOBAL claim's range must refuse — same-arbiter property.
    g = feature(tmp_path, "g",
                '[[claims.wram]]\nname = "gp"\nbytes = 16\nat = 0x1F00\n')
    s = feature(tmp_path, "s1",
                '[[claims.wram]]\nname = "sp"\nbytes = 8\nat = 0x1F04\n')
    with pytest.raises(AllocationError, match="not free"):
        compose(tmp_path, [g, s], [("s", ["s1"])], globals_=["g"])


def test_emitted_symbol_carries_the_pin(tmp_path):
    a = feature(tmp_path, "aud",
                '[[claims.wram]]\nname = "tad_bss"\nbytes = 16\nat = 0x1F00\n')
    alloc = compose(tmp_path, [a], [("s", [])], globals_=["aud"])
    out = tmp_path / "out"
    emit(alloc, out)
    inc = (out / "engine_state_globals.inc").read_text()
    assert any("ES_TAD_BSS" in ln and "1F00" in ln for ln in inc.splitlines()), \
        "ES_TAD_BSS symbol does not carry the pinned address"
