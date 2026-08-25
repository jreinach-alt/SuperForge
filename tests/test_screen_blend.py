"""The screen/blend vocabulary: layer-to-screen designations and color-math
programming as claims, composed per scene, with the infeasible compositions
REFUSED — each refusal naming the claiming features and the hardware
mechanism it protects.

Pure Python against the allocator (tmp_path fixture trees, the
test_allocator.py pattern): no ROM builds, no emulator, no collection-time
symbol_map reads. Expected register values are derived independently in each
test from the Mesen2-verified bit layout (schemas.py's vocabulary block:
TM/TS bit = layer index, CGADSUB b7 sub / b6 half / b5-0 math enables,
CGWSEL b7-6 clip / b5-4 prevent / b1 source), never by calling the code
under test.
"""
import json
from pathlib import Path
import sys

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate, emit  # noqa: E402
from schemas import (SchemaError, StateDecl, load_feature,  # noqa: E402
                     load_manifest, load_substrate)

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
NO_STATE = StateDecl((), {})


# -- fixture helpers (the test_allocator.py pattern) ------------------------

def feature(tmp_path, name, body=""):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "feature"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, text):
    p = tmp_path / "game.toml"
    p.write_text(text)
    return load_manifest(p)


def features(tmp_path, **bodies):
    return {n: feature(tmp_path, n, b) for n, b in bodies.items()}


def one_scene(tmp_path, *names):
    return manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ['
                    + ", ".join(f'"{n}"' for n in names) + ']\n')


# Reusable claim bodies. The worked composition of the value tests: one
# feature designates bg1+obj to main, another designates bg2 to sub and
# declares the blend over bg1+backdrop.
SHORE = ('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
         '[[claims.screen]]\nlayer = "obj"\non = "main"\n')
WATER = ('[[claims.screen]]\nlayer = "bg2"\non = "sub"\n'
         '[[claims.blend]]\nop = "add"\nhalf = true\nsource = "sub"\n'
         'math = ["bg1", "backdrop"]\n')


# -- parse level ------------------------------------------------------------

def test_screen_claim_parses_with_defaulted_name(tmp_path):
    f = feature(tmp_path, "sky",
                '[[claims.screen]]\nlayer = "bg2"\non = "sub"\n')
    assert len(f.screen) == 1
    c = f.screen[0]
    assert (c.layer, c.on, c.name) == ("bg2", "sub", "sky_screen")


def test_blend_claim_parses_with_defaults(tmp_path):
    f = feature(tmp_path, "wash",
                '[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
                'math = ["backdrop"]\n')
    c = f.blend[0]
    assert c.op == "add" and c.source == "fixed"
    assert c.math == ("backdrop",)
    assert c.half is False and c.clip == "never" and c.prevent == "never"


def test_unknown_layer_is_not_a_resource(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo",
                '[[claims.screen]]\nlayer = "bg5"\non = "main"\n')
    assert "bg5" in str(e.value) and "typo is not a resource" in str(e.value)


def test_unknown_math_layer_is_not_a_resource(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo",
                '[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
                'math = ["bg1", "bg9"]\n')
    assert "bg9" in str(e.value) and "typo is not a resource" in str(e.value)


def test_bad_window_mode_refused(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "clipper",
                '[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
                'math = ["backdrop"]\nclip = "sometimes"\n')
    assert "sometimes" in str(e.value) and "window modes" in str(e.value)


def test_r7_empty_math_refuses_naming_feature_and_mechanism(tmp_path):
    """R7 — a blender blending nothing, refused at parse (a property of the
    declaration alone, the scene_writes-subset precedent)."""
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "hollow",
                '[[claims.blend]]\nop = "add"\nsource = "fixed"\nmath = []\n')
    msg = str(e.value)
    assert "hollow" in msg                       # the claiming feature
    assert "CGADSUB bits 0-5" in msg             # the hardware mechanism
    assert "blend nothing" in msg
