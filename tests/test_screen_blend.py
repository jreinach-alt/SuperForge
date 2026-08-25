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


# -- the refusal set (R1-R5): message content is the deliverable ------------

def alloc(tmp_path, feats, *names):
    return allocate(SUB, feats, NO_STATE, one_scene(tmp_path, *names))


def test_r1_same_layer_two_features_refuses_even_agreeing(tmp_path):
    """R1 — ownership, not the value, is the resource: two features that
    AGREE on bg2 -> sub still refuse."""
    feats = features(
        tmp_path,
        lake='[[claims.screen]]\nlayer = "bg2"\non = "sub"\n',
        mist='[[claims.screen]]\nlayer = "bg2"\non = "sub"\n')
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "lake", "mist")
    msg = str(e.value)
    assert "lake" in msg and "mist" in msg           # both claiming features
    assert "one owner" in msg and "ownership" in msg.lower()
    assert "even though they agree" in msg           # same-value still refuses
    assert "TM/TS hold one enable bit per layer" in msg  # the mechanism


def test_r2_global_field_disagreement_refuses_and_agreement_composes(tmp_path):
    """R2, both arms in one test (the toy-bad polarity in pytest form): the
    accepted control differs from the refused arm by ONE field (`half`), so
    a toothless check cannot pass both."""
    base = ('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
            '[[claims.screen]]\nlayer = "bg2"\non = "sub"\n')
    tint = ('[[claims.blend]]\nop = "add"\nhalf = true\nsource = "sub"\n'
            'math = ["bg1"]\n')
    glow_ok = ('[[claims.blend]]\nop = "add"\nhalf = true\nsource = "sub"\n'
               'math = ["backdrop"]\n')
    glow_bad = ('[[claims.blend]]\nop = "add"\nhalf = false\nsource = "sub"\n'
                'math = ["backdrop"]\n')

    # control arm: identical global fields, disjoint math -> composes
    feats = features(tmp_path / "ok", world=base, tint=tint, glow=glow_ok)
    a = alloc(tmp_path / "ok", feats, "world", "tint", "glow")
    sb = a.scenes["s"].screen_blend
    assert sb is not None and sb["blends"] == 2

    # refusal arm: one global field differs
    feats = features(tmp_path / "bad", world=base, tint=tint, glow=glow_bad)
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path / "bad", feats, "world", "tint", "glow")
    msg = str(e.value)
    assert "tint" in msg and "glow" in msg
    assert "half" in msg and "ONE color-math unit" in msg
    assert "bit 6 one halve" in msg                  # the mechanism


def test_r3_same_math_layer_in_two_blend_claims_refuses(tmp_path):
    feats = features(
        tmp_path,
        world=('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
               '[[claims.screen]]\nlayer = "bg2"\non = "sub"\n'),
        tint=('[[claims.blend]]\nop = "add"\nsource = "sub"\n'
              'math = ["bg1"]\n'),
        glow=('[[claims.blend]]\nop = "add"\nsource = "sub"\n'
              'math = ["bg1"]\n'))
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "world", "tint", "glow")
    msg = str(e.value)
    assert "tint" in msg and "glow" in msg and "'bg1'" in msg
    assert "one enable bit per layer" in msg         # the mechanism


def test_r4_sub_source_with_no_sub_layer_refuses(tmp_path):
    feats = features(
        tmp_path,
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        wash=('[[claims.blend]]\nop = "add"\nsource = "sub"\n'
              'math = ["bg1"]\n'))
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "world", "wash")
    msg = str(e.value)
    assert "wash" in msg and 'source = "sub"' in msg
    assert "FIXED COLOR" in msg and "disables halving" in msg   # mechanism
    assert "declaration that lies" in msg


def test_r5_math_layer_not_main_designated_refuses(tmp_path):
    """R5 — bg3 gated into math while designated only to the sub screen."""
    feats = features(
        tmp_path,
        world=('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
               '[[claims.screen]]\nlayer = "bg3"\non = "sub"\n'),
        wash=('[[claims.blend]]\nop = "add"\nsource = "sub"\n'
              'math = ["bg3"]\n'))
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "world", "wash")
    msg = str(e.value)
    assert "wash" in msg and "'bg3'" in msg
    assert "MAIN" in msg and "inert" in msg          # the mechanism


def test_r5_backdrop_is_exempt_and_r4_fixed_needs_no_sub(tmp_path):
    """The two deliberate NON-refusals beside R4/R5: backdrop needs no
    designation, and a fixed-source blend needs no sub screen — so a
    blend-only scene (fixed-color wash over the backdrop) composes."""
    feats = features(
        tmp_path,
        wash=('[[claims.blend]]\nop = "sub"\nsource = "fixed"\n'
              'math = ["backdrop"]\n'))
    a = alloc(tmp_path, feats, "wash")
    sb = a.scenes["s"].screen_blend
    assert sb is not None and sb["designations"] == 0


# -- composition values (derived independently from the bit layout) ---------

def test_two_feature_scene_composes_the_four_values(tmp_path):
    """TM/TS from designations, CGWSEL/CGADSUB from the blend. Expected
    values derived here from the Mesen2-verified layout, not from the code
    under test:
      TM: bg1(bit0) + obj(bit4)              = $11
      TS: bg2(bit1)                          = $02
      CGADSUB: half(bit6) + backdrop(bit5) + bg1(bit0), op=add(bit7=0) = $61
      CGWSEL: source=sub(bit1), clip=never prevent=never, direct 0     = $02
    """
    feats = features(tmp_path, shore=SHORE, water=WATER)
    a = alloc(tmp_path, feats, "shore", "water")
    sb = a.scenes["s"].screen_blend
    assert sb["tm"] == (1 << 0) | (1 << 4) == 0x11
    assert sb["ts"] == (1 << 1) == 0x02
    assert sb["cgadsub"] == (1 << 6) | (1 << 5) | (1 << 0) == 0x61
    assert sb["cgwsel"] == (1 << 1) == 0x02
    assert sb["registers"] == ("TM", "TS", "CGWSEL", "CGADSUB")


def test_screen_claims_without_blend_compose_the_off_state(tmp_path):
    """No blend claims: CGWSEL/CGADSUB compose the explicit OFF state the
    boot reset establishes — prevent=always(3)<<4 = $30, CGADSUB $00 — and
    the synthesized claim owns only TM/TS, so a raw CGWSEL claim stays
    expressible in a designation-only scene."""
    feats = features(
        tmp_path,
        world=('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
               '[[claims.screen]]\nlayer = "obj"\non = "both"\n'))
    a = alloc(tmp_path, feats, "world")
    sb = a.scenes["s"].screen_blend
    assert sb["tm"] == (1 << 0) | (1 << 4) == 0x11
    assert sb["ts"] == (1 << 4) == 0x10              # obj on "both"
    assert (sb["cgwsel"], sb["cgadsub"]) == (0x30, 0x00)
    assert sb["registers"] == ("TM", "TS")


def test_scene_without_vocabulary_composes_nothing(tmp_path):
    feats = features(tmp_path, plain='[[claims.dp]]\nbytes = 2\n')
    a = alloc(tmp_path, feats, "plain")
    assert a.scenes["s"].screen_blend is None
    assert all(not _is_vocab(who) for _, who in a.scenes["s"].regs)


def _is_vocab(who):
    return who.startswith("screen/blend")
