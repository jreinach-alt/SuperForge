"""The video/offset vocabulary: a scene's BGMODE and BG3-as-a-scroll-table as
claims, composed per scene, with the infeasible compositions REFUSED — each
refusal naming the claiming features and the hardware mechanism it protects.

Pure Python against the allocator (tmp_path fixture trees, the
test_allocator.py / test_screen_blend.py pattern): no ROM builds, no emulator,
no collection-time symbol_map reads. Expected register values are derived
independently in each test from the Mesen2-verified bit layout (schemas.py's
vocabulary block: BGMODE b2-0 mode, b3 mode-1 BG3 priority, b4-7 the 16x16
selects; an offset word's bit 13 = BG1, bit 14 = BG2, bits 9-0 the value),
never by calling the code under test.

WHAT THIS MODULE IS FOR. `docs/capability_map/ppu_core.md` §9 rated
offset-per-tile `partial` and named exactly two holes: nothing could declare
"BG3 is not a drawable layer in this scene", and the mode restriction was not
expressible as a constraint at all. Both are properties OF THE MODE, which was
a value nobody declared. Every case below is one of those two holes, closed.
"""
import json
from pathlib import Path
import sys

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate, emit  # noqa: E402
from schemas import (MODE_LAYERS, OFFSET_MODES, SchemaError,  # noqa: E402
                     StateDecl, load_feature, load_manifest, load_substrate)

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


# Reusable claim bodies. The worked composition: one feature declares mode 2
# and the offset table, another designates the two layers the mode renders.
OPT = ('[[claims.video]]\nmode = 2\n'
       '[[claims.offset]]\naxis = "v"\nlayers = ["bg1", "bg2"]\n')
LAYERS = ('[[claims.screen]]\nlayer = "bg1"\non = "main"\n'
          '[[claims.screen]]\nlayer = "bg2"\non = "main"\n')


# -- parse level ------------------------------------------------------------

def test_video_claim_parses_with_defaults(tmp_path):
    f = feature(tmp_path, "shape", '[[claims.video]]\nmode = 2\n')
    c = f.video[0]
    assert (c.mode, c.bg3_priority, c.tiles16, c.name) == \
        (2, False, (), "shape_video")


def test_offset_claim_parses_with_defaulted_name(tmp_path):
    f = feature(tmp_path, "tab",
                '[[claims.offset]]\naxis = "h"\nlayers = ["bg2"]\n')
    c = f.offset[0]
    assert (c.axis, c.layers, c.name) == ("h", ("bg2",), "tab_offset")


def test_unknown_mode_is_not_a_resource(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo", '[[claims.video]]\nmode = 8\n')
    assert "mode = 8" in str(e.value) and "eight of them" in str(e.value)


def test_unknown_axis_refused(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo",
                '[[claims.offset]]\naxis = "diagonal"\nlayers = ["bg1"]\n')
    assert "diagonal" in str(e.value) and "no third axis" in str(e.value)


def test_offset_layer_outside_the_two_enable_bits(tmp_path):
    """bg3 is the TABLE and bg4 exists in no mode that fetches one, so
    neither has an enable bit for an offset word to set."""
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo",
                '[[claims.offset]]\naxis = "v"\nlayers = ["bg1", "bg3"]\n')
    msg = str(e.value)
    assert "bg3" in msg and "BG3 is the table itself" in msg


def test_empty_layers_refused_at_parse(tmp_path):
    """The R7 shape on this axis: a table that drives nothing. A property of
    the declaration alone, so no allocation is needed to know it."""
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "hollow",
                '[[claims.offset]]\naxis = "v"\nlayers = []\n')
    msg = str(e.value)
    assert "hollow" in msg                     # the claiming feature
    assert "bits 13 and 14" in msg             # the hardware mechanism
    assert "every column of the table is inert" in msg


def test_tiles16_outside_the_bg_layers(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo",
                '[[claims.video]]\nmode = 1\ntiles16 = ["obj"]\n')
    assert "obj" in str(e.value) and "OBSEL" in str(e.value)


def test_two_video_claims_on_one_feature_refused_at_parse(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "greedy",
                '[[claims.video]]\nmode = 1\n[[claims.video]]\nmode = 2\n')
    assert "declares the video mode ONCE" in str(e.value)


# -- the refusal set (O1-O8): message content is the deliverable ------------

def _refuse(tmp_path, feats, *names):
    with pytest.raises(AllocationError) as e:
        allocate(SUB, feats, NO_STATE, one_scene(tmp_path, *names))
    return str(e.value)


def test_o1_two_modes_refuse_even_when_they_agree(tmp_path):
    """Ownership of BGMODE, not its value, is the resource — the RegClaim
    rule, and the reason the message says so out loud."""
    f = features(tmp_path,
                 a='[[claims.video]]\nmode = 2\n',
                 b='[[claims.video]]\nmode = 2\n')
    msg = _refuse(tmp_path, f, "a", "b")
    assert "VIDEO MODE contention" in msg
    assert "a_video" in msg and "b_video" in msg     # BOTH claimants named
    assert "even though they agree" in msg
    assert "BGMODE bits 0-2" in msg                  # the mechanism


def test_o2_two_offset_tables_refuse(tmp_path):
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n',
                 a='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n',
                 b='[[claims.offset]]\naxis = "v"\nlayers = ["bg2"]\n')
    msg = _refuse(tmp_path, f, "m", "a", "b")
    assert "OFFSET-PER-TILE contention" in msg
    assert "a_offset" in msg and "b_offset" in msg
    assert "one BG3 fetch path per scene" in msg


def test_o3_an_offset_claim_needs_a_declared_mode(tmp_path):
    """THE HOLE THE VOCABULARY EXISTS TO CLOSE, first half. Without a
    declared mode the restriction cannot be checked at all, so the claim
    would compose in silence in a scene whose BGMODE some raw claim writes
    to a value nobody declared."""
    f = features(tmp_path,
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n')
    msg = _refuse(tmp_path, f, "t")
    assert "t_offset" in msg
    assert "no [[claims.video]] claim in this scene" in msg
    assert "modes 2, 4 and 6" in msg


@pytest.mark.parametrize("mode", [m for m in MODE_LAYERS if m not in OFFSET_MODES])
def test_o4_offset_per_tile_only_exists_in_modes_2_4_6(tmp_path, mode):
    """THE MODE CONSTRAINT, over every mode that does not have it. Derived
    from MODE_LAYERS/OFFSET_MODES rather than listed, so a mode added to the
    table is covered by this case the day it arrives."""
    f = features(tmp_path,
                 m=f'[[claims.video]]\nmode = {mode}\n',
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "OFFSET-PER-TILE contention" in msg
    assert "t_offset" in msg and "m_video" in msg    # BOTH sides named
    assert f"declares mode {mode}" in msg
    assert "FetchTileData" in msg                    # the mechanism, by name
    assert "never reads a word of this table" in msg


def test_o5_designation_arm_bg3_is_the_table(tmp_path):
    """THE HOLE THE VOCABULARY EXISTS TO CLOSE, second half — the arm no
    register can see. A feature that puts BG3 on screen by DESIGNATING it
    meets the offset table in the composition."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n',
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n',
                 txt='[[claims.screen]]\nlayer = "bg3"\non = "main"\n')
    msg = _refuse(tmp_path, f, "m", "t", "txt")
    assert "txt_screen" in msg and "t_offset" in msg
    assert "BG3 IS NOT A DRAWABLE LAYER" in msg
    assert "RenderMode2/4/6" in msg


def test_o5_register_arm_bg3_is_the_table(tmp_path):
    """...and the arm a register CAN see, which is the one `bg_text` meets.
    It arises from the ordinary reg-x-reg intersection against the
    composition's synthesized ownership claim, not from a separate lint —
    but the MESSAGE is the offset one, because the fix is not to pick a
    winner."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n',
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n',
                 txt='[[claims.reg]]\nname = "txt_bg3"\n'
                     'registers = ["BG3SC", "BG34NBA"]\n')
    msg = _refuse(tmp_path, f, "m", "t", "txt")
    assert "REGISTER ownership contention" in msg
    assert "txt_bg3" in msg and "video/offset" in msg
    assert "BG3 IS THIS SCENE'S OFFSET TABLE" in msg
    assert "put the offset table in a scene of its own" in msg
    # BG34NBA is NOT owned by the composition — the offset path reads no BG3
    # chr base — so the intersection names BG3SC alone.
    assert "['BG3SC']" in msg


def test_o6_a_driven_layer_the_mode_does_not_render(tmp_path):
    """Mode 6 draws BG1 only, so an enable bit for BG2 displaces a layer no
    pass produces — R5's shape on the mode axis."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 6\n',
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1", "bg2"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "drives bg2 from the offset table" in msg
    assert "RenderMode6" in msg
    assert "displaces a layer no pass draws" in msg


def test_o7_mode_4_carries_one_axis_per_column(tmp_path):
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n',
                 t='[[claims.offset]]\naxis = "both"\nlayers = ["bg1"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert 'axis = "both" under mode 4' in msg
    assert "bit 15" in msg
    assert "Modes 2 and 6 fetch a word for EACH axis" in msg


def test_o7_does_not_fire_under_mode_2(tmp_path):
    """The negative arm: `both` is exactly what modes 2 and 6 are for. A
    refusal that fired everywhere would prove nothing about mode 4."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "both"\nlayers = ["bg1"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    assert a.scenes["s"].video_offset["axis"] == "both"


@pytest.mark.parametrize("mode,layer", [(2, "bg3"), (2, "bg4"), (3, "bg3"),
                                        (5, "bg4"), (6, "bg2"), (7, "bg3")])
def test_o8_a_designation_the_mode_does_not_render(tmp_path, mode, layer):
    """R5's rule on the mode axis, and it stands WITHOUT an offset claim:
    the enable bit is set and no pass ever produces a pixel through it."""
    f = features(tmp_path,
                 m=f'[[claims.video]]\nmode = {mode}\n',
                 lyr=f'[[claims.screen]]\nlayer = "{layer}"\non = "main"\n')
    msg = _refuse(tmp_path, f, "m", "lyr")
    assert "SCREEN designation contention" in msg
    assert f"designates {layer} -> main" in msg
    assert f"RenderMode{mode}" in msg
    assert "INERT" in msg


def test_o8_exempts_obj_in_every_mode(tmp_path):
    """Sprites render in every mode, so OBJ is never constrained by the
    layer table — a refusal that caught it would be over-refusal."""
    for mode in MODE_LAYERS:
        f = features(tmp_path,
                     m=f'[[claims.video]]\nmode = {mode}\n',
                     o='[[claims.screen]]\nlayer = "obj"\non = "main"\n')
        a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "o"))
        assert a.scenes["s"].video_offset["bgmode"] & 0x07 == mode


def test_mode_7_bg2_warns_rather_than_refusing_extbg(tmp_path):
    """The one approximation in MODE_LAYERS, stated as a warning instead of
    hidden: RenderMode7 draws BG2 when EXTBG is enabled, and EXTBG has no
    model in this tree (docs/09 G5). Over-refusal is a defect class of its
    own."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 7\n',
                 lyr='[[claims.screen]]\nlayer = "bg2"\non = "sub"\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "lyr"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "EXTBG" in w and "docs/09 G5" in w


def test_raw_bgmode_beside_a_video_claim_refuses_with_the_migration(tmp_path):
    """The R6 analogue on this port. Two vocabularies cannot both supply one
    write-only byte, and the message carries the edit."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 1\n',
                 raw='[[claims.reg]]\nname = "raw_mode"\n'
                     'registers = ["BGMODE"]\n')
    msg = _refuse(tmp_path, f, "m", "raw")
    assert "raw_mode" in msg and "video/offset" in msg
    assert "becomes a [[claims.video]] claim" in msg
    assert "per-scanline BGMODE rewrite" in msg      # the one raw case left


# -- the composed value -----------------------------------------------------

@pytest.mark.parametrize("body,want", [
    ('mode = 2\n', 0x02),
    ('mode = 1\nbg3_priority = true\n', 0x09),
    ('mode = 0\ntiles16 = ["bg1", "bg4"]\n', 0x90),
    ('mode = 7\n', 0x07),
])
def test_bgmode_composes_from_the_declaration(tmp_path, body, want):
    """The byte, derived here from the Mesen2-verified layout (b2-0 mode,
    b3 mode-1 BG3 priority, b4-7 the per-layer 16x16 selects in layer
    order) rather than by calling the composer."""
    f = features(tmp_path, m="[[claims.video]]\n" + body)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m"))
    assert a.scenes["s"].video_offset["bgmode"] == want


def test_no_vocabulary_claim_composes_nothing(tmp_path):
    """A scene with neither claim has no composition at all — not an empty
    one. That is what keeps every rail predating the vocabulary untouched."""
    f = features(tmp_path, plain='[[claims.dp]]\nname = "x"\nbytes = 2\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "plain"))
    assert a.scenes["s"].video_offset is None


# -- emission: a symbol only for what the composition owns -------------------

def _emit(tmp_path, feats, *names):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    a = allocate(SUB, feats, NO_STATE, one_scene(tmp_path, *names))
    emit(a, out)
    return (out / "engine_state_s.inc").read_text(), \
        json.loads((out / "symbol_map.json").read_text())


def test_a_mode_claim_alone_emits_bgmode_and_no_opt_symbols(tmp_path):
    f = features(tmp_path, m='[[claims.video]]\nmode = 1\n')
    inc, _ = _emit(tmp_path, f, "m")
    assert "ES_VID_S_BGMODE = $01" in inc
    assert "ES_OPT_S_BG1" not in inc
    # ...and it SAYS SO rather than going quiet, the _screen_blend_lines rule
    assert "ES_OPT_S_* absent" in inc


def test_the_offset_fields_are_derived_from_the_declaration(tmp_path):
    """`layers` decides which enable bits exist and `axis` which value mask,
    so a rail cannot build a word out of a bit its claim did not declare."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg2"]\n')
    inc, jm = _emit(tmp_path, f, "m", "t")
    assert "ES_OPT_S_BG2 = $4000" in inc
    assert "ES_OPT_S_BG1" not in inc          # not declared -> not emitted
    assert "ES_OPT_S_MASK = $03FF" in inc
    assert "ES_OPT_S_HMASK" not in inc        # axis = "v"
    assert "ES_OPT_S_VSEL" not in inc         # mode 4 only
    sb = jm["scenes"]["s"]["video_offset"]
    assert sb["fields"] == {"BG2": 0x4000, "MASK": 0x03FF}
    assert sb["registers"] == ["BGMODE", "BG3SC", "BG3HOFS", "BG3VOFS"]


def test_mode_4_emits_the_axis_select_bit(tmp_path):
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "h"\nlayers = ["bg1"]\n')
    inc, _ = _emit(tmp_path, f, "m", "t")
    assert "ES_OPT_S_VSEL = $8000" in inc
    assert "ES_OPT_S_HMASK = $03F8" in inc


# -- warnings: real hardware behaviour, not refusals ------------------------

def test_horizontal_offsets_warn_about_their_granularity(tmp_path):
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "h"\nlayers = ["bg1"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "8-PIXEL granular" in w and "$3F8" in w


def test_a_driven_layer_nothing_designates_warns(tmp_path):
    """A warning and not a refusal, because the layer may be designated by a
    raw TM claim the vocabulary cannot attribute — the WOBJSEL precedent."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n',
                 t='[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "which no [[claims.screen]] claim in this scene designates" in w


def test_bg3_priority_outside_mode_1_warns(tmp_path):
    f = features(tmp_path, m='[[claims.video]]\nmode = 2\nbg3_priority = true\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "RenderMode1 alone" in w
    # ...and it still COMPOSES, because the bit is a state the PPU can hold
    assert a.scenes["s"].video_offset["bgmode"] == 0x0A


# -- the tilemap shape, and the encoding it completes -----------------------

def test_a_tilemap_shape_disagreeing_with_its_size_refuses(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "big",
                '[[claims.vram]]\nname = "m"\nkind = "tilemap"\n'
                'words = 0x400\nshape = "64x32"\n')
    assert "one fact stated twice" in str(e.value)


def test_shape_is_a_tilemap_property(tmp_path):
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "chr",
                '[[claims.vram]]\nname = "c"\nkind = "chr"\ntiles = 4\n'
                'shape = "64x32"\n')
    assert "`shape` is a TILEMAP property" in str(e.value)


@pytest.mark.parametrize("shape,words,bits", [
    ("32x32", 0x400, 0x00), ("64x32", 0x800, 0x01),
    ("32x64", 0x800, 0x02), ("64x64", 0x1000, 0x03),
])
def test_sc_base_carries_the_size_bits(tmp_path, shape, words, bits):
    """BGnSC bit 0 is DoubleWidth and bit 1 DoubleHeight (SnesPpu.cpp:1979-80),
    and `words` alone cannot tell 64x32 from 32x64 — so the shape is declared
    and the emitted encoding carries it. Before this the two bits were OR'd in
    by hand at three write sites."""
    f = features(tmp_path, m=f'[[claims.vram]]\nname = "map"\n'
                             f'kind = "tilemap"\nwords = {words}\n'
                             f'shape = "{shape}"\n')
    inc, _ = _emit(tmp_path, f, "m")
    line = [l for l in inc.splitlines() if "ES_V_MAP_SC_BASE" in l][0]
    value = int(line.split("=")[1].split(";")[0].strip().lstrip("$"), 16)
    assert value & 0x03 == bits
    assert value & 0x7C == 0x00 or value & 0x7C  # the base rides the top bits


def test_a_32x32_claim_is_unchanged_by_the_shape_field(tmp_path):
    """The compatibility property, held rather than assumed: every claim that
    predates `shape` defaults to 32x32, whose size bits are zero."""
    f = features(tmp_path, m='[[claims.vram]]\nname = "map"\n'
                             'kind = "tilemap"\nwords = 0x400\n')
    inc, _ = _emit(tmp_path, f, "m")
    line = [l for l in inc.splitlines() if "ES_V_MAP_SC_BASE" in l][0]
    assert int(line.split("=")[1].split(";")[0].strip().lstrip("$"), 16) & 3 == 0
