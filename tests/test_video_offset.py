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


def test_o7_per_column_under_mode_4_is_the_declaration_and_emits_all_three(tmp_path):
    """`per_column` IS mode 4's two-axis state, and it emits what it needs.

    Mode 4 fetches ONE word per column and bit 15 picks that word's axis, so a
    table can drive one column vertically and its neighbour horizontally —
    the one thing mode 4 does which mode 2 cannot. The emission is the whole
    reason the state needs a name of its own: `axis` picks which value mask is
    published and the two axes mask differently ($3FF against $3F8), so a
    mixed table has to publish BOTH masks and the bit that selects between
    them.

    NO WARNING. The composition used to read this declaration's own definition
    aloud on every build, which is a report of nothing.
    """
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "per_column"\nlayers = ["bg1"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    assert a.scenes["s"].video_offset["axis"] == "per_column"
    inc, _ = _emit(tmp_path, f, "m", "t")
    assert "ES_OPT_S_MASK = $03FF" in inc      # the V value field
    assert "ES_OPT_S_HMASK = $03F8" in inc     # ...and the H one
    assert "ES_OPT_S_VSEL = $8000" in inc      # ...and the bit that picks
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "means something different from modes 2" not in w


def test_o7_per_column_emits_exactly_what_both_did_under_mode_4(tmp_path):
    """THE MIGRATION IS A RENAME, not a change of meaning: `per_column` under
    mode 4 must publish the same field set `both` published there, or every
    rail that moves to it builds a different ROM.

    Asserted as an equality against the composition's own field dict rather
    than by re-typing three constants, so a field added to either arm later
    cannot pass this by being typed twice.
    """
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "per_column"\nlayers = ["bg1", "bg2"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    got = a.scenes["s"].video_offset["fields"]
    # ...and the reference: the same claim in the mode where `both` is legal
    # carries MASK + HMASK, and mode 4 adds VSEL.
    f2 = features(tmp_path / "ref",
                  m='[[claims.video]]\nmode = 2\n' + LAYERS,
                  t='[[claims.offset]]\naxis = "both"\nlayers = ["bg1", "bg2"]\n')
    b = allocate(SUB, f2, NO_STATE, one_scene(tmp_path / "ref", "m", "t"))
    ref = dict(b.scenes["s"].video_offset["fields"])
    ref["VSEL"] = 0x8000
    assert got == ref


def test_o7_both_under_mode_4_refuses(tmp_path):
    """The migration hazard, as a refusal. `both` is a column displaced on
    BOTH axes at once and mode 4 has no such state — one word is fetched and
    bit 15 picks. This used to be a WARNING, which could not stop a table
    moved from mode 2 to mode 4 keeping its declaration and changing its
    meaning."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "both"\nlayers = ["bg1"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "OFFSET-PER-TILE contention" in msg
    assert 'declares axis = "both"' in msg
    assert "bit 15 selects that word's axis" in msg
    assert 'declare axis = "per_column"' in msg


@pytest.mark.parametrize("mode", [2, 6])
def test_o7_per_column_outside_mode_4_refuses(tmp_path, mode):
    """The other arm. Modes 2 and 6 fetch a word for EACH axis, so every
    column gets both and bit 15 selects nothing — the choice `per_column`
    names does not exist there."""
    f = features(tmp_path,
                 m=f'[[claims.video]]\nmode = {mode}\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "per_column"\nlayers = ["bg1"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "OFFSET-PER-TILE contention" in msg
    assert 'declares axis = "per_column"' in msg
    assert "bit 15 is read in mode 4 alone" in msg


def test_o7_both_under_mode_2_is_the_other_meaning(tmp_path):
    """The neighbouring arm, and the reason there are two names: modes 2 and 6
    fetch a word for EACH axis, so `both` there is a column displaced on both
    at once. Legal, and no warning."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n' + LAYERS,
                 t='[[claims.offset]]\naxis = "both"\nlayers = ["bg1"]\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    assert a.scenes["s"].video_offset["axis"] == "both"
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "means something different" not in w


def test_a_fifth_axis_value_is_refused_at_parse(tmp_path):
    """Four states, named, and the parse error says what each means — so an
    author who reaches for a fifth reads the pair that already exists."""
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "z",
                '[[claims.offset]]\naxis = "either"\nlayers = ["bg1"]\n')
    assert "per_column" in str(e.value)
    assert "picked by bit 15" in str(e.value)


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


# -- O9: a CHR claim's DEPTH against the depth its mode renders it at -------

CHR8 = ('[[claims.vram]]\nname = "deep"\nkind = "chr"\n'
        'layers = ["bg1"]\ntiles = 4\ntile_bytes = 64\n')


def test_o9_a_4bpp_claim_under_a_mode_that_renders_it_8bpp(tmp_path):
    """THE GAP MODE 4 EXISTS TO FIND, and nothing in the tree could before.

    `MODE_BPP` was imported by the allocator for exactly one purpose —
    building the "(bg1 4bpp + bg2 4bpp)" text inside refusal MESSAGES — and
    was never checked against anything; `tile_bytes` was validated as one of
    16/32/64 and stopped there. So mode 4 (bg1 8bpp) beside a 32-byte BG1 CHR
    claim composed GREEN, while the PPU fetched 64 bytes a tile: every tile
    half of one and half of the next, and the back half of the set never
    reached. It stayed invisible because until mode 4 every composed mode
    rendered its layers at the depth the art happened to be.
    """
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 c='[[claims.vram]]\nname = "shallow"\nkind = "chr"\n'
                   'layers = ["bg1"]\ntiles = 4\ntile_bytes = 32\n')
    msg = _refuse(tmp_path, f, "m", "c")
    assert "CHR DEPTH contention" in msg
    assert "tile_bytes = 32 (4bpp)" in msg
    assert "bg1 at 8bpp, 64 bytes a tile" in msg
    assert "half of one tile and half of the next" in msg


def test_o9_accepts_the_depth_the_mode_actually_renders(tmp_path):
    """The negative arm. A refusal that fired on the right composition too
    would say nothing about depth — it would say the check runs."""
    f = features(tmp_path, m='[[claims.video]]\nmode = 4\n' + LAYERS, c=CHR8)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "c"))
    assert a.scenes["s"].video_offset["checks"] >= 1


def test_o9_the_same_claim_is_wrong_one_mode_over(tmp_path):
    """THE DEPTH IS A PROPERTY OF THE MODE, NOT OF THE CLAIM, which is the
    whole reason this is a join and not a field validation. The 8bpp claim
    that mode 4 requires is the one mode 2 refuses."""
    f = features(tmp_path, m='[[claims.video]]\nmode = 2\n' + LAYERS, c=CHR8)
    msg = _refuse(tmp_path, f, "m", "c")
    assert "tile_bytes = 64 (8bpp)" in msg
    assert "bg1 at 4bpp, 32 bytes a tile" in msg


def test_o9_chr_for_a_layer_the_mode_never_draws(tmp_path):
    """The O6 shape, one claim class over: tiles uploaded for a layer no pass
    fetches. Mode 6 renders BG1 alone."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 6\n'
                   '[[claims.screen]]\nlayer = "bg1"\non = "main"\n',
                 c='[[claims.vram]]\nname = "orphan"\nkind = "chr"\n'
                   'layers = ["bg2"]\ntiles = 4\ntile_bytes = 32\n')
    msg = _refuse(tmp_path, f, "m", "c")
    assert "holds tiles for bg2" in msg
    assert "never calls RenderTilemap for bg2" in msg


def test_o9_obj_is_4bpp_in_every_mode_and_needs_no_mode(tmp_path):
    """THE ONE ARM THAT HOLDS WITHOUT A VIDEO CLAIM AT ALL. A sprite's depth
    is not a property of the mode: SnesPpu.cpp:770 fetches sprite pixels
    through GetTilePixelColor<4> with the depth written into the template
    argument, so a 64-byte OBJ tile is wrong in all eight modes and there is
    no mode to check it against."""
    f = features(tmp_path,
                 c='[[claims.vram]]\nname = "sprites"\nkind = "chr"\n'
                   'obj = true\ntiles = 4\ntile_bytes = 64\n')
    msg = _refuse(tmp_path, f, "c")
    assert "OBJ is 4bpp in EVERY video mode" in msg
    assert "GetTilePixelColor<4>" in msg


def test_o9_warns_about_the_claims_it_cannot_reach(tmp_path):
    """THE RATCHET'S FIRST RUNG. `layers` is optional, so this check cannot
    refuse what it cannot see — and a check that silently reaches nothing is
    the failure mode the width lint's contract pass was built to avoid. A
    scene that declares a mode and carries a sized BG CHR claim without
    `layers` is NAMED in the report."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n' + LAYERS,
                 c='[[claims.vram]]\nname = "unjoined"\nkind = "chr"\n'
                   'tiles = 4\ntile_bytes = 32\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "c"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "chr unjoined" in w and "names no `layers`" in w
    assert "is NOT checked against mode 2" in w


def test_o9_yields_to_the_register_arm_when_both_would_fire(tmp_path):
    """ORDER AS MESSAGE QUALITY, pinned — because a reshuffle would silently
    swap a good refusal for a worse one and every case would stay green.

    A text feature composed into an offset-mode scene trips both: O9 sees CHR
    for a layer mode 2 does not render, and the register arm sees two features
    contending for BG3SC. O9's sentence is the shallower half — an author who
    hears it first fixes it by dropping `layers`, which silences a check
    instead of moving the feature. The register arm names BG3 as the scene's
    offset table and names both claimants, which is the hazard AND the choice.

    So the chr check runs after check_reg_ownership, and this asserts which
    one an author actually hears.
    """
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n'
                   '[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n' + LAYERS,
                 t='[[claims.vram]]\nname = "glyphs"\nkind = "chr"\n'
                   'layers = ["bg3"]\ntiles = 8\ntile_bytes = 16\n'
                   '[[claims.reg]]\nname = "text_bg3"\nregisters = ["BG3SC"]\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "REGISTER ownership contention" in msg
    assert "BG3 IS THIS SCENE'S OFFSET TABLE" in msg
    assert "CHR DEPTH contention" not in msg


def test_o9_still_fires_where_no_register_collision_exists(tmp_path):
    """The other half of the ordering: yielding is not disarming. The same CHR
    claim without the BG3SC claim beside it has nothing else to catch it."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 2\n'
                   '[[claims.offset]]\naxis = "v"\nlayers = ["bg1"]\n' + LAYERS,
                 t='[[claims.vram]]\nname = "glyphs"\nkind = "chr"\n'
                   'layers = ["bg3"]\ntiles = 8\ntile_bytes = 16\n')
    msg = _refuse(tmp_path, f, "m", "t")
    assert "CHR DEPTH contention" in msg
    assert "holds tiles for bg3" in msg


def test_o9_a_words_sized_claim_declares_no_depth(tmp_path):
    """A STATED LIMIT, not an oversight. `words` is the escape hatch for a
    claim whose shape is a hardware WINDOW rather than a tile count — a whole
    OBJ name table, the Mode 7 region — and such a claim declares no bytes per
    tile for this check to read. It is neither refused nor warned about."""
    f = features(tmp_path,
                 m='[[claims.video]]\nmode = 4\n' + LAYERS,
                 c='[[claims.vram]]\nname = "window"\nkind = "chr"\n'
                   'obj = true\nwords = 0x1000\n')
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "c"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "window" not in w


def test_o9_layers_is_a_chr_property(tmp_path):
    with pytest.raises(SchemaError, match="`layers` is a CHR property"):
        feature(tmp_path, "bad",
                '[[claims.vram]]\nname = "m"\nkind = "tilemap"\n'
                'words = 0x400\nlayers = ["bg1"]\n')


def test_o9_obj_is_not_a_layer_a_chr_claim_can_name(tmp_path):
    with pytest.raises(SchemaError, match="OBJ is not among them"):
        feature(tmp_path, "bad",
                '[[claims.vram]]\nname = "c"\nkind = "chr"\n'
                'tiles = 4\nlayers = ["obj"]\n')


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


# -- O10: bands — the offset table read in ROWS, per scanline ---------------
# `[[claims.offset_bands]]` is a claim of the SCENE's use of the table: the
# composition synthesizes its own active-phase HDMA claim on BG3VOFS, marks
# its BG3VOFS ownership `seed`, and emits the band count and the row stride.

M4 = '[[claims.video]]\nmode = 4\n' + LAYERS
TAB = '[[claims.offset]]\naxis = "per_column"\nlayers = ["bg1", "bg2"]\n'
BANDS = '[[claims.offset_bands]]\nrows = 3\n'


def test_bands_parse_with_a_default_name_and_a_row_range(tmp_path):
    f = feature(tmp_path, "z", BANDS)
    assert f.offset_bands[0].name == "z_bands"
    assert f.offset_bands[0].rows == 3
    for rows in (1, 33):
        with pytest.raises(SchemaError) as e:
            feature(tmp_path, f"r{rows}", f'[[claims.offset_bands]]\nrows = {rows}\n')
        assert "BG3VOFS >> 3" in str(e.value)


def test_o10_bands_need_a_table_in_the_scene(tmp_path):
    f = features(tmp_path, m=M4, b=BANDS)
    msg = _refuse(tmp_path, f, "m", "b")
    assert "OFFSET BANDS" in msg and "b_bands" in msg
    assert "no [[claims.offset]] holds this scene" in msg


def test_o10_two_band_sets_refuse(tmp_path):
    f = features(tmp_path, m=M4, t=TAB, a=BANDS, b=BANDS)
    msg = _refuse(tmp_path, f, "m", "t", "a", "b")
    assert "OFFSET BANDS contention" in msg
    assert "a_bands" in msg and "b_bands" in msg


def test_bands_synthesize_the_row_selecting_channel_and_emit_it(tmp_path):
    """The composition owns the per-scanline BG3VOFS write: a channel is
    assigned, its DMAP/BBAD derive from the port, and the scene's include
    carries the band count and the row stride beside it."""
    f = features(tmp_path, m=M4, t=TAB, b=BANDS)
    inc, jm = _emit(tmp_path, f, "m", "t", "b")
    assert "ES_OPT_S_BANDS = $0003" in inc
    assert "ES_OPT_S_ROW_VOFS = $0008" in inc
    assert "ES_H_B_BANDS_ROWSEL_CH = " in inc
    assert "ES_H_B_BANDS_ROWSEL_BBAD = $12" in inc      # BG3VOFS = $2112
    assert "ES_H_B_BANDS_ROWSEL_DMAP = $02" in inc      # write-twice
    assert "SEED it overrides from line 0" in inc
    vo = jm["scenes"]["s"]["video_offset"]
    assert vo["bands"] == 3 and vo["rowsel"] == "b_bands_rowsel"
    chans = [c for c in jm["scenes"]["s"]["channels"]
             if c["name"] == "b_bands_rowsel"]
    assert chans and chans[0]["phase"] == "active"
    assert chans[0]["registers"] == ["BG3VOFS"]


def test_o10_a_foreign_active_channel_on_bg3vofs_meets_the_rowsel_claim(tmp_path):
    """The seed does NOT open the port to another channel: with bands the
    foreign claim collides with the synthesized one in assign_channels."""
    f = features(tmp_path, m=M4, t=TAB, b=BANDS,
                 x='[[claims.hdma]]\nregisters = ["BG3VOFS"]\nmode = 2\n')
    msg = _refuse(tmp_path, f, "m", "t", "b", "x")
    assert "HDMA register contention" in msg
    assert "b_bands_rowsel" in msg and "x_hdma" in msg


def test_a_foreign_active_channel_on_bg3vofs_without_bands_still_refuses(tmp_path):
    """...and without bands there is no seed, so the raw shape keeps refusing
    on O5's register arm — the vocabulary's own consent is not a channel's."""
    f = features(tmp_path, m=M4, t=TAB,
                 x='[[claims.hdma]]\nregisters = ["BG3VOFS"]\nmode = 2\n')
    msg = _refuse(tmp_path, f, "m", "t", "x")
    assert "x_hdma" in msg and "BG3VOFS" in msg


def test_a_raw_cpu_writer_of_bg3vofs_beside_bands_still_refuses(tmp_path):
    """A seed exempts an HDMA overrider only; a second CPU establisher of the
    port is still O5's register arm."""
    f = features(tmp_path, m=M4, t=TAB, b=BANDS,
                 x='[[claims.reg]]\nregisters = ["BG3VOFS"]\n')
    msg = _refuse(tmp_path, f, "m", "t", "b", "x")
    assert "x_reg" in msg and "BG3VOFS" in msg


# -- O11: 16x16 tiles meeting the offset table ------------------------------
# The one interaction between the two halves of this vocabulary. It is not
# symmetric between the axes, and the asymmetry was READ in SnesPpu.cpp and
# then MEASURED on a 16x16 probe build of `mill`:
#
#   horizontal, 8 in the word:  30/31 screen columns rendered as the
#       "entry moves, half-select does not" model predicts (even columns as
#       though the word were 0, odd ones as though it were 16); 0 of the 14
#       genuinely displaced columns matched a coherent model
#   vertical, 8 in the word:    27/27 columns across six scanlines matched
#       the per-column displaced vScroll, 0/27 the layer's own
#
# So a horizontal displacement of a 16x16 layer REFUSES where the composition
# can prove the layer takes horizontal words, and WARNS where the axis is a
# per-word bit in a blob it cannot read.

def _t16(mode, axis, tiles16, layers='["bg1"]'):
    return (f'[[claims.video]]\nmode = {mode}\ntiles16 = {tiles16}\n',
            f'[[claims.offset]]\naxis = "{axis}"\nlayers = {layers}\n')


@pytest.mark.parametrize("mode,axis", [(2, "h"), (2, "both"), (4, "h"),
                                       (6, "h")])
def test_o11_a_horizontally_driven_layer_may_not_be_16x16(tmp_path, mode, axis):
    """`h` is every word and `both` is every column, so in both the
    composition KNOWS the layer is displaced horizontally."""
    m, t = _t16(mode, axis, '["bg1"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    msg = _refuse(tmp_path, f, "m", "t")
    assert "VIDEO/OFFSET contention" in msg
    assert "declares 16x16 tiles for bg1" in msg
    assert "config.HScroll" in msg           # the mechanism, by name
    assert "draws the wrong half" in msg


def test_o11_names_the_layer_and_not_its_neighbour(tmp_path):
    """The refusal is per LAYER: a table driving bg1 and bg2 beside a
    `tiles16` that names only bg2 must name bg2 — a message that named the
    claim and not the layer would send the author to the wrong end."""
    m, t = _t16(2, "h", '["bg2"]', layers='["bg1", "bg2"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    msg = _refuse(tmp_path, f, "m", "t")
    assert "16x16 tiles for bg2" in msg
    assert "16x16 tiles for bg1" not in msg


def test_o11_a_vertically_driven_16x16_layer_composes(tmp_path):
    """THE ASYMMETRY, and it is the reason this is not a blanket refusal: the
    vertical half-select comes from the DISPLACED tileData.VScroll, so a
    vertically displaced 16x16 column is coherent. Measured 27/27."""
    m, t = _t16(2, "v", '["bg1"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    assert a.scenes["s"].video_offset["tiles16"] == ["bg1"]
    assert a.scenes["s"].video_offset["bgmode"] == 2 | 0x10   # BGMODE bit 4


def test_o11_a_vertically_driven_16x16_layer_still_warns_about_the_pair(tmp_path):
    """...and warns about the OTHER constraint, which the composition also
    cannot check: two adjacent columns share one tilemap entry but keep their
    own rows, so a pair must carry the same displacement or tear."""
    m, t = _t16(2, "v", '["bg1"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "SHARE one tilemap entry" in w
    assert "tears down the middle" in w
    assert "incoherent" not in w             # no horizontal word is possible


def test_o11_per_column_warns_rather_than_refusing(tmp_path):
    """Mode 4's axis is bit 15 of each WORD — data in a blob, which the
    composition cannot read. It cannot prove the 16x16 layer takes a
    horizontal word, so it names both conditions and composes."""
    m, t = _t16(4, "per_column", '["bg1"]', layers='["bg1", "bg2"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "cannot read a word" in w
    assert "renders as 0 on an even screen column and 16 on an odd one" in w
    assert "tears down the middle" in w


def test_o11_does_not_fire_on_a_layer_the_table_does_not_drive(tmp_path):
    """16x16 on bg1 beside a table that drives bg2 only is two claims that do
    not meet — no refusal and no warning, or the warning means nothing."""
    m, t = _t16(2, "h", '["bg1"]', layers='["bg2"]')
    f = features(tmp_path, m=m + LAYERS, t=t)
    a = allocate(SUB, f, NO_STATE, one_scene(tmp_path, "m", "t"))
    w = " ".join(a.scenes["s"].video_offset["warnings"])
    assert "16x16" not in w
