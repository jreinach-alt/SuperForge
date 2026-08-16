"""C1 — SPC RAM occupancy, the eleventh claim class.

The headline is the REFUSAL, and specifically the CROSS-SCENE one: two
features declaring `[[claims.spc]]` in DIFFERENT scenes must stop the build.
The class is PROGRAM-wide — the occupant's driver is initialised once per
power-on and its Audio-RAM upload persists across scene transitions, so
scene separation composes nothing. A per-scene union check (the reg class's
shape) would PASS exactly that composition; test_refusal_is_program_wide
locks the difference.

On test surface: these are allocator tests, so the output region IS the
allocator's verdict + diagnostic text + the symbol_map record, not a proxy
for them. The ROM-level half of C1's contract arrives with this slice (the
audio feature), whose surface is SPC RAM bytes / DSP registers / WAV
capture per the spec
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate, emit  # noqa: E402
from schemas import (B_BUS_REGISTERS, REGISTER_FOOTPRINT, WHOLE,  # noqa: E402
                     SchemaError, StateDecl, load_feature, load_manifest,
                     load_substrate)

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
NO_STATE = StateDecl((), {})


def feature(tmp_path, name, body="", role="fixture"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "{role}"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, scenes, globals_=()):
    """A game.toml with explicit scenes: [(scene_id, [feature names]), ...]."""
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


SPC = '[[claims.spc]]\nname = "aram"\n'


# -- schema: the vocabulary teaches itself -----------------------------------

def test_spc_claim_accepted_spelling(tmp_path):
    f = feature(tmp_path, "aud", SPC)
    assert len(f.spc) == 1
    assert f.spc[0].name == "aram"


def test_spc_claim_default_name(tmp_path):
    f = feature(tmp_path, "aud", "[[claims.spc]]\n")
    assert f.spc[0].name == "aud_spc"


def test_spc_size_field_refused(tmp_path):
    """The claim is presence-only BY DESIGN — a `bytes` key must not parse.

    A size field would be the start of a parallel model of the occupant's
    interior packing; the strict table is what keeps the class
    the boundary it was scoped to be.
    """
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "aud", '[[claims.spc]]\nbytes = 4096\n')
    msg = str(e.value)
    assert "unknown key 'bytes'" in msg
    assert "[[claims.spc]]" in msg


def test_two_spc_entries_in_one_feature_refused(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "aud", SPC + SPC)
    assert "ONCE" in str(e.value)


def test_spc_name_participates_in_duplicate_claim_check(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "aud",
                '[[claims.wram]]\nname = "aram"\nbytes = 16\n' + SPC)
    assert "duplicate claim names" in str(e.value)


# -- the headline: occupancy is exclusive ------------------------------------

def test_refusal_two_features_one_scene(tmp_path):
    a = feature(tmp_path, "aud_a", SPC)
    b = feature(tmp_path, "aud_b", '[[claims.spc]]\nname = "aram_b"\n')
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [a, b], [("s", ["aud_a", "aud_b"])])
    msg = str(e.value)
    assert "SPC RAM occupancy contention" in msg
    assert "aud_a" in msg and "aud_b" in msg


def test_refusal_is_program_wide(tmp_path):
    """THE acceptance test.

    aud_a lives only in scene s1, aud_b only in scene s2 — no scene contains
    both. Every per-scene check in the allocator composes this pair; the spc
    class must refuse it anyway, because the occupant's upload persists
    across transitions (Tad_Init is once-per-power-on). If this test can
    pass with a per-scene union implementation, the class has not solved
    its problem.
    """
    a = feature(tmp_path, "aud_a", SPC)
    b = feature(tmp_path, "aud_b", '[[claims.spc]]\nname = "aram_b"\n')
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [a, b], [("s1", ["aud_a"]), ("s2", ["aud_b"])])
    msg = str(e.value)
    assert "aud_a" in msg and "aud_b" in msg
    assert "scene 's1'" in msg and "scene 's2'" in msg
    assert "PROGRAM-wide" in msg


def test_refusal_global_vs_scene(tmp_path):
    """The cross-scope hole (F2's shape): a global occupant and a scene one."""
    a = feature(tmp_path, "aud_a", SPC)
    b = feature(tmp_path, "aud_b", '[[claims.spc]]\nname = "aram_b"\n')
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [a, b], [("s", ["aud_b"])], globals_=["aud_a"])
    msg = str(e.value)
    assert "globals" in msg and "scene 's'" in msg


def test_single_owner_across_scenes_allocates(tmp_path):
    """One feature occupying in every scene is ONE occupant, not N."""
    a = feature(tmp_path, "aud", SPC)
    alloc = compose(tmp_path, [a], [("s1", ["aud"]), ("s2", ["aud"])])
    assert alloc.spc_owner == ("aud", "aram", ["scene 's1'", "scene 's2'"])


def test_no_spc_claim_means_no_owner(tmp_path):
    a = feature(tmp_path, "quiet", '[[claims.wram]]\nname = "buf"\nbytes = 16\n')
    alloc = compose(tmp_path, [a], [("s", ["quiet"])])
    assert alloc.spc_owner is None


def test_symbol_map_records_the_owner(tmp_path):
    """The machine-readable record a future writer-side gate consumes —
    the reg-class precedent (no symbol emitted, ownership in the map)."""
    a = feature(tmp_path, "aud", SPC)
    alloc = compose(tmp_path, [a], [("s", ["aud"])], globals_=[])
    out = tmp_path / "out"
    out.mkdir()
    emit(alloc, out)
    jmap = json.loads((out / "symbol_map.json").read_text())
    assert jmap["spc_owner"] == {"feature": "aud", "claim": "aram",
                                 "declared_in": ["scene 's'"]}
    assert jmap["spaces"]["spc_bytes"] == 0x10000


# -- the mailbox: APUIO through the shipped reg machinery --------------------

def test_apuio_is_one_whole_port_name():
    """The ALU convention applied to $2140-43: one name, one resource, and it
    derives B-bus membership from its address (so hdma/dma_init may target
    it while claims.reg owns it)."""
    assert REGISTER_FOOTPRINT["APUIO"] == (0x2140, WHOLE)
    assert "APUIO" in B_BUS_REGISTERS


def test_apuio_reg_contention_refuses(tmp_path):
    """Two S-CPU mailbox drivers is the tad-audio.inc:49 violation, made a
    build failure by the existing C4 pass once the name exists."""
    a = feature(tmp_path, "aud", '[[claims.reg]]\nregisters = ["APUIO"]\n')
    b = feature(tmp_path, "hacker", '[[claims.reg]]\nregisters = ["APUIO"]\n')
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [a, b], [("s", ["aud", "hacker"])])
    msg = str(e.value)
    assert "APUIO" in msg and "aud" in msg and "hacker" in msg


def test_apuio_transfer_vs_reg_owner_refuses(tmp_path):
    """A DMA upload path targeting the mailbox against a CPU owner — the
    reg-x-transfer check, reached through the new name. (A dma_init to
    APUIO is legal B-bus vocabulary on its own; it is the composition with
    a CPU owner that refuses.)"""
    a = feature(tmp_path, "aud", '[[claims.reg]]\nregisters = ["APUIO"]\n')
    b = feature(tmp_path, "uploader",
                '[[claims.dma_init]]\nchannel = 0\nregisters = ["APUIO"]\n'
                'mode = 0\n')
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [a, b], [("s", ["aud", "uploader"])])
    msg = str(e.value)
    assert "APUIO" in msg and "claims.dma_init" in msg
