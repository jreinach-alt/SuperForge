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


# -- R6 + coexistence: two vocabularies, one port ---------------------------

RAW_TM = ('[[claims.reg]]\nregisters = ["BGMODE", "TM"]\n'
          'scene_writes = ["BGMODE", "TM"]\n')


def test_r6_raw_tm_flips_a_composing_scene_and_the_control_arm_holds(tmp_path):
    """Coexistence + R6 aliveness, both arms over one raw-TM feature (the
    toy-bad polarity): the raw-TM scene with NO vocabulary claims allocates
    exactly as before — the synthesized claim does not exist — and adding
    ONE screen claim to the same scene flips it to the vocabulary-mixing
    refusal naming both sides and the fix."""
    # control arm: raw claim alone -> composes, no synthesized claim
    feats = features(tmp_path / "ok", floor=RAW_TM)
    a = alloc(tmp_path / "ok", feats, "floor")
    assert a.scenes["s"].screen_blend is None
    assert [c.name for c, _ in a.scenes["s"].regs] == ["floor_reg"]

    # refusal arm: one screen claim beside it
    feats = features(tmp_path / "bad", floor=RAW_TM,
                     sky='[[claims.screen]]\nlayer = "bg2"\non = "sub"\n')
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path / "bad", feats, "floor", "sky")
    msg = str(e.value)
    assert "floor_reg" in msg and "engine:floor" in msg   # the raw claimant
    assert "screen_blend" in msg and "engine:sky" in msg  # the vocabulary side
    assert "TM" in msg
    assert "two vocabularies, one write-only port" in msg
    assert "[[claims.screen]]" in msg                     # the fix, named


def test_r6_raw_cgwsel_against_blend_claims(tmp_path):
    feats = features(
        tmp_path,
        iris=('[[claims.reg]]\nregisters = ["CGWSEL"]\n'
              'scene_writes = ["CGWSEL"]\n'),
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        wash=('[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
              'math = ["bg1"]\n'))
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "iris", "world", "wash")
    msg = str(e.value)
    assert "iris_reg" in msg and "screen_blend" in msg
    assert "CGWSEL" in msg and "[[claims.blend]]" in msg


def test_r6_is_asymmetric_raw_cgwsel_composes_beside_screen_only(tmp_path):
    """The deliberate coexistence seam: the synthesized claim owns TM/TS
    only where screen claims exist and CGWSEL/CGADSUB only where blend
    claims do — so a raw CGWSEL claim (e.g. a direct-color scene) composes
    beside designations, and a raw TM claim composes beside a
    backdrop-only blend."""
    feats = features(
        tmp_path / "a",
        dc=('[[claims.reg]]\nregisters = ["CGWSEL"]\n'
            'scene_writes = ["CGWSEL"]\n'),
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n')
    a = alloc(tmp_path / "a", feats, "dc", "world")
    assert a.scenes["s"].screen_blend["registers"] == ("TM", "TS")

    feats = features(
        tmp_path / "b", floor=RAW_TM,
        wash=('[[claims.blend]]\nop = "sub"\nsource = "fixed"\n'
              'math = ["backdrop"]\n'))
    b = alloc(tmp_path / "b", feats, "floor", "wash")
    assert b.scenes["s"].screen_blend["registers"] == ("CGWSEL", "CGADSUB")


def test_vocab_against_active_hdma_on_tm_refuses_with_its_own_hint(tmp_path):
    """The stated limit made loud: the vocabulary has no per-scanline story,
    so composing screen claims against an active-phase HDMA TM rewrite
    refuses, and the hint names the raw seed shape rather than advising a
    `seed` the synthesized claim cannot carry."""
    feats = features(
        tmp_path,
        sky='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        bands=('[[claims.hdma]]\nregisters = ["TM"]\nphase = "active"\n'))
    with pytest.raises(AllocationError) as e:
        alloc(tmp_path, feats, "sky", "bands")
    msg = str(e.value)
    assert "screen_blend" in msg and "bands" in msg
    assert "no per-scanline story" in msg


# -- emission: per-scene symbols, values derived once ------------------------

def test_emission_writes_the_four_symbols_with_contributors(tmp_path):
    feats = features(tmp_path, shore=SHORE, water=WATER)
    a = alloc(tmp_path, feats, "shore", "water")
    emit(a, tmp_path / "out")
    inc = (tmp_path / "out" / "engine_state_s.inc").read_text()
    assert "ES_SCR_S_TM = $11" in inc
    assert "ES_SCR_S_TS = $02" in inc
    assert "ES_SCR_S_CGWSEL = $02" in inc
    assert "ES_SCR_S_CGADSUB = $61" in inc
    # each line's comment names the contributing features and fields
    tm_line = next(l for l in inc.splitlines() if l.startswith("ES_SCR_S_TM"))
    assert "bg1<-engine:shore" in tm_line and "obj<-engine:shore" in tm_line
    ad_line = next(l for l in inc.splitlines()
                   if l.startswith("ES_SCR_S_CGADSUB"))
    assert "op=add" in ad_line and "half" in ad_line
    assert "bg1<-engine:water" in ad_line and "backdrop<-engine:water" in ad_line
    # the globals file carries none of it (per-scene symbols, per-scene file)
    ginc = (tmp_path / "out" / "engine_state_globals.inc").read_text()
    assert "ES_SCR_" not in ginc
    # machine-readable copy in the symbol map, the edges precedent
    jmap = json.loads((tmp_path / "out" / "symbol_map.json").read_text())
    sb = jmap["scenes"]["s"]["screen_blend"]
    assert (sb["tm"], sb["ts"], sb["cgwsel"], sb["cgadsub"]) \
        == (0x11, 0x02, 0x02, 0x61)
    assert sb["features"] == ["engine:shore", "engine:water"]
    # and the synthesized claim entered the scene's reg union with consent
    vocab = [r for r in jmap["scenes"]["s"]["reg"]
             if r["name"] == "screen_blend"]
    assert len(vocab) == 1
    assert vocab[0]["registers"] == ["TM", "TS", "CGWSEL", "CGADSUB"]
    assert vocab[0]["scene_writes"] == ["TM", "TS", "CGWSEL", "CGADSUB"]


def defined_syms(inc: str) -> set[str]:
    """Symbol NAMES the include actually defines — non-comment `NAME = ...`
    lines only, so a commented placeholder that mentions a name does not
    read as a definition."""
    out = set()
    for line in inc.splitlines():
        line = line.strip()
        if line.startswith(";") or "=" not in line:
            continue
        out.add(line.split("=", 1)[0].strip())
    return out


def test_emission_absence_and_no_vocabulary_scene(tmp_path):
    """A scene with no vocabulary claims emits nothing and its map carries
    no screen_blend key — pre-vocabulary maps stay byte-identical."""
    feats = features(
        tmp_path,
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        plain='[[claims.dp]]\nbytes = 2\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "on"\nfeatures = ["world"]\n'
                   '[[scene]]\nid = "off"\nfeatures = ["plain"]\n'
                   '[[edge]]\nfrom = "on"\nto = "off"\nstyle = "cut"\n')
    a = allocate(SUB, feats, NO_STATE, man)
    emit(a, tmp_path / "out")
    inc_off = (tmp_path / "out" / "engine_state_off.inc").read_text()
    assert "ES_SCR_" not in inc_off
    jmap = json.loads((tmp_path / "out" / "symbol_map.json").read_text())
    assert "screen_blend" in jmap["scenes"]["on"]
    assert "screen_blend" not in jmap["scenes"]["off"]


def test_emission_publishes_only_the_owned_half_both_directions(tmp_path):
    """A symbol is published only for a port the composition OWNS.

    Ownership is per-half, so both directions have to hold: a screen-only
    scene defines TM/TS and NOT CGWSEL/CGADSUB, and a blend-only scene the
    reverse. Emitting all four regardless would state a value for a port a
    raw claimant owns and programs — and where that claimant opened the port
    with `scene_writes`, the writer-side gate would take a scene write of
    the allocator's value over the owner's.

    The off VALUES survive in the report and the map (asserted here): what
    is withheld is a symbol to write an unowned port from.
    """
    # screen-only, beside a feature that owns and programs CGWSEL
    feats = features(
        tmp_path / "scr",
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        dc=('[[claims.reg]]\nregisters = ["CGWSEL"]\n'
            'scene_writes = ["CGWSEL"]\n'))
    a = alloc(tmp_path / "scr", feats, "world", "dc")
    emit(a, tmp_path / "scr" / "out")
    inc = (tmp_path / "scr" / "out" / "engine_state_s.inc").read_text()
    syms = defined_syms(inc)
    assert {"ES_SCR_S_TM", "ES_SCR_S_TS"} <= syms
    assert "ES_SCR_S_CGWSEL" not in syms and "ES_SCR_S_CGADSUB" not in syms
    assert "no [[claims.blend]] in this scene" in inc      # and it says why
    jmap = json.loads(
        (tmp_path / "scr" / "out" / "symbol_map.json").read_text())
    sb = jmap["scenes"]["s"]["screen_blend"]
    assert sb["registers"] == ["TM", "TS"]                 # what it owns
    assert (sb["cgwsel"], sb["cgadsub"]) == (0x30, 0x00)   # the value survives
    rep = (tmp_path / "scr" / "out" / "allocation_report.txt").read_text()
    assert "CGWSEL=$30 CGADSUB=$00 (owns TM,TS)" in rep

    # blend-only, beside a feature that owns and programs TM
    feats = features(
        tmp_path / "bl", floor=RAW_TM,
        wash=('[[claims.blend]]\nop = "sub"\nsource = "fixed"\n'
              'math = ["backdrop"]\n'))
    b = alloc(tmp_path / "bl", feats, "floor", "wash")
    emit(b, tmp_path / "bl" / "out")
    inc = (tmp_path / "bl" / "out" / "engine_state_s.inc").read_text()
    syms = defined_syms(inc)
    assert {"ES_SCR_S_CGWSEL", "ES_SCR_S_CGADSUB"} <= syms
    assert "ES_SCR_S_TM" not in syms and "ES_SCR_S_TS" not in syms
    assert "no [[claims.screen]] in this scene" in inc
    jmap = json.loads(
        (tmp_path / "bl" / "out" / "symbol_map.json").read_text())
    sb = jmap["scenes"]["s"]["screen_blend"]
    assert sb["registers"] == ["CGWSEL", "CGADSUB"]
    assert (sb["tm"], sb["ts"]) == (0x00, 0x00)


def test_unowned_port_write_no_longer_has_a_symbol_to_write_from(tmp_path):
    """The same property end-to-end, through the writer-side gate.

    The raw CGWSEL owner opens its port with `scene_writes` — its ordinary
    shape — so `no_literals` ACCEPTS a scene write of $2130 in this scene
    (asserted, so the test cannot pass by the gate refusing for an unrelated
    reason). What stops the scene writing the allocator's un-owned value is
    that there is no `ES_SCR_S_CGWSEL` to write it from: the emitted include
    defines the symbol for the port the composition owns and not for this
    one.
    """
    import no_literals as NL
    g = tmp_path / "game" / "g"
    (g / "scenes").mkdir(parents=True)
    feats = {n: feature(tmp_path, n, b) for n, b in {
        "world": '[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        "dc": ('[[claims.reg]]\nregisters = ["CGWSEL"]\n'
               'scene_writes = ["CGWSEL"]\n')}.items()}
    (g / "game.toml").write_text(
        '[[scene]]\nid = "s"\nfeatures = ["world", "dc"]\n')
    a = allocate(SUB, feats, NO_STATE, load_manifest(g / "game.toml"))
    out = tmp_path / "build"
    emit(a, out)
    asm = g / "scenes" / "s.asm"
    asm.write_text(".a8\nlda #ES_SCR_S_TM\nsta a:$212C\nsta a:$2130\n")
    rc = NL.main(["--map", str(out / "symbol_map.json"),
                  "--partial-files", str(asm)])
    assert rc == 0                                   # the gate consents
    inc = (out / "engine_state_s.inc").read_text()
    assert "ES_SCR_S_CGWSEL" not in defined_syms(inc)  # no value to write


# -- warnings: the allocation report carries them ---------------------------

def test_report_carries_the_obj_palette_note_and_layer_owner_cross_check(
        tmp_path):
    feats = features(
        tmp_path,
        world=('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
               '[[claims.screen]]\nlayer = "obj"\non = "both"\n'
               '[[claims.screen]]\nlayer = "bg2"\non = "sub"\n'),
        wash=('[[claims.blend]]\nop = "add"\nsource = "sub"\n'
              'math = ["bg1", "obj"]\n'),
        floor=('[[claims.reg]]\nregisters = ["BG1SC"]\n'
               'scene_writes = ["BG1SC"]\n'))
    a = alloc(tmp_path, feats, "world", "wash", "floor")
    emit(a, tmp_path / "out")
    rep = (tmp_path / "out" / "allocation_report.txt").read_text()
    assert "SCREEN/BLEND" in rep
    # the OBJ-palette note (palettes 4-7 participate; 0-3 opt out)
    assert "WARNING: OBJ in math: only sprite palettes 4-7 participate" in rep
    # the OBJ-as-source note
    assert "WARNING: OBJ designated to the sub screen" in rep
    # the layer-owner cross-check names designator and owner
    assert ("WARNING: bg1 is designated by world_screen (engine:world) "
            "but its BG1SC is claimed by floor_reg (engine:floor)") in rep


BLENDER = ('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
           '[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
           'math = ["bg1"]\n')
# The same shape composing the OFF state deliberately: prevent = "always" is
# what ppu_reset writes at boot ($30), so this destination disarms the
# blender on enter.
DISARMER = ('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
            '[[claims.blend]]\nop = "add"\nsource = "fixed"\n'
            'math = ["backdrop"]\nprevent = "always"\n')


def _two_scene_game(tmp_path, feats, a_feats, b_feats):
    man = manifest(tmp_path,
                   '[[scene]]\nid = "a"\nfeatures = ['
                   + ", ".join(f'"{n}"' for n in a_feats) + ']\n'
                   '[[scene]]\nid = "b"\nfeatures = ['
                   + ", ".join(f'"{n}"' for n in b_feats) + ']\n'
                   '[[edge]]\nfrom = "a"\nto = "b"\nstyle = "cut"\n')
    return allocate(SUB, feats, NO_STATE, man)


def test_blend_persists_into_a_successor_that_establishes_nothing(tmp_path):
    """The composed state is per scene and nothing carries it across an
    edge: a successor composing no blend half, with no raw CGWSEL/CGADSUB
    owner, writes neither port and INHERITS the blender scene 'a' armed.
    A warning naming both scenes, the edge and the remedy — not a refusal,
    because holding a blend across a transition can be deliberate."""
    feats = features(tmp_path, glow=BLENDER,
                     plain='[[claims.dp]]\nbytes = 2\n')
    a = _two_scene_game(tmp_path, feats, ["glow"], ["plain"])
    assert a.blend_edges_checked == 1              # the edge WAS examined
    assert len(a.blend_edge_warnings) == 1
    w = a.blend_edge_warnings[0]
    assert "transition a->b" in w
    assert "scene 'a' composes a blend" in w
    assert "scene 'b' composes no [[claims.blend]]" in w
    assert "PERSISTS" in w
    assert "disarms at scene exit" in w            # the remedy, named
    emit(a, tmp_path / "out")
    rep = (tmp_path / "out" / "allocation_report.txt").read_text()
    assert "SCREEN/BLEND transition hygiene: 1 edge(s)" in rep
    assert "WARNING: transition a->b" in rep


def test_edge_is_quiet_when_the_destination_composes_the_off_state(tmp_path):
    """The control arm, and the remedy the warning names: a destination
    that composes its own blend half establishes CGWSEL/CGADSUB on enter,
    so nothing persists and the edge is quiet — while still being COUNTED
    as examined, so a silenced check does not read like an absent one."""
    feats = features(tmp_path, glow=BLENDER, calm=DISARMER)
    a = _two_scene_game(tmp_path, feats, ["glow"], ["calm"])
    assert a.blend_edges_checked == 1              # examined, not skipped
    assert a.blend_edge_warnings == []
    # and the destination really does compose the boot OFF state ($30/$00)
    assert (a.scenes["b"].screen_blend["cgwsel"],
            a.scenes["b"].screen_blend["cgadsub"]) == (0x30, 0x20)


def test_edge_is_quiet_when_a_raw_claimant_owns_the_blend_ports(tmp_path):
    """The other remedy: the destination leaves CGWSEL/CGADSUB to a raw
    [[claims.reg]] owner (the disarm-at-exit shape), so a claimant is
    answerable for the ports there and the edge is quiet."""
    feats = features(
        tmp_path, glow=BLENDER,
        iris=('[[claims.reg]]\nregisters = ["CGWSEL", "CGADSUB"]\n'
              'scene_writes = ["CGWSEL", "CGADSUB"]\n'))
    a = _two_scene_game(tmp_path, feats, ["glow"], ["iris"])
    assert a.blend_edges_checked == 1
    assert a.blend_edge_warnings == []


def test_edge_out_of_a_screen_only_scene_is_not_a_candidate(tmp_path):
    """A source that arms no blender has nothing to persist, so its edges
    are not in the population at all — the denominator says so."""
    feats = features(
        tmp_path,
        world='[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
        plain='[[claims.dp]]\nbytes = 2\n')
    a = _two_scene_game(tmp_path, feats, ["world"], ["plain"])
    assert a.blend_edges_checked == 0
    assert a.blend_edge_warnings == []


def test_no_warnings_for_a_clean_composition(tmp_path):
    """The warnings' control arm: the worked two-feature scene produces no
    warning lines, so a warning pass that fired unconditionally would fail
    here."""
    feats = features(tmp_path, shore=SHORE, water=WATER)
    a = alloc(tmp_path, feats, "shore", "water")
    assert a.scenes["s"].screen_blend["warnings"] == []


# -- the CLI census line: zero reads as "nothing composed", not silence -----

def test_cli_census_line_both_states(tmp_path):
    """Both arms of the summary census: a composing game prints the counts,
    a vocabulary-free game prints 'nothing composed' — never silence."""
    import subprocess
    for n, b in {"shore": SHORE, "water": WATER,
                 "plain": '[[claims.dp]]\nbytes = 2\n'}.items():
        feature(tmp_path, n, b)

    def run_game(gdir, features_list):
        g = tmp_path / gdir
        g.mkdir()
        (g / "game.toml").write_text(
            '[[scene]]\nid = "s"\nfeatures = ['
            + ", ".join(f'"{x}"' for x in features_list) + ']\n')
        return subprocess.run(
            [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
             "--game", str(g), "--features-dir", str(tmp_path),
             "--out", str(g / "out")], capture_output=True, text=True)

    r = run_game("g_on", ["shore", "water"])
    assert r.returncode == 0, r.stderr
    assert ("screen/blend: 3 designation(s), 1 blend claim(s) composed "
            "across 1 scene(s)") in r.stdout
    assert "refusal check(s) evaluated" in r.stdout
    # the two counts that keep a silenced check from reading as an absent
    # one: this one-scene game declares no edges and warns about nothing
    assert "0 transition edge(s) examined, 0 warning(s) in the report" \
        in r.stdout

    r = run_game("g_off", ["plain"])
    assert r.returncode == 0, r.stderr
    assert "screen/blend: nothing composed" in r.stdout


# -- the no_literals integration: scene writes of the four ports ------------

SCENE_ASM = """\
.a8
lda #ES_SCR_S_TM
sta a:$212C
lda #ES_SCR_S_TS
sta a:$212D
lda #ES_SCR_S_CGWSEL
sta a:$2130
lda #ES_SCR_S_CGADSUB
sta a:$2131
"""


def _game_tree(tmp_path, feats_bodies, scene_features):
    """A fixture game at tmp/game/g (the tier shape reg_context keys on),
    allocated and emitted; returns (map path, scene asm path)."""
    g = tmp_path / "game" / "g"
    (g / "scenes").mkdir(parents=True)
    feats = {n: feature(tmp_path, n, b) for n, b in feats_bodies.items()}
    (g / "game.toml").write_text(
        '[[scene]]\nid = "s"\nfeatures = ['
        + ", ".join(f'"{n}"' for n in scene_features) + ']\n')
    man = load_manifest(g / "game.toml")
    a = allocate(SUB, feats, NO_STATE, man)
    out = tmp_path / "build"
    emit(a, out)
    asm = g / "scenes" / "s.asm"
    asm.write_text(SCENE_ASM)
    return out / "symbol_map.json", asm


def test_reg_gate_accepts_the_four_writes_under_a_vocabulary_composition(
        tmp_path, capsys):
    """Both arms of the writer-side integration in one test: the SAME four
    port writes pass where the scene composes the vocabulary (the
    synthesized claim opened the ports via scene_writes) and refuse where it
    does not — so an acceptance that ignored the claim set entirely would
    fail the second arm."""
    import no_literals as NL

    map_ok, asm_ok = _game_tree(
        tmp_path / "ok", {"shore": SHORE, "water": WATER},
        ["shore", "water"])
    rc = NL.main(["--map", str(map_ok), "--partial-files", str(asm_ok)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "scene-union" in out.out                  # the tier that checked it

    map_bad, asm_bad = _game_tree(
        tmp_path / "bad", {"plain": '[[claims.dp]]\nbytes = 2\n'}, ["plain"])
    rc = NL.main(["--map", str(map_bad), "--partial-files", str(asm_bad)])
    out = capsys.readouterr()
    assert rc == 1
    assert "$212C" in out.err and "scene 's'" in out.err
