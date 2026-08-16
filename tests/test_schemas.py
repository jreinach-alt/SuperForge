"""Schema loaders: the toy fixtures parse; malformed declarations fail legibly."""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from schemas import (SchemaError, load_feature, load_manifest, load_state,
                     load_substrate)

SUB = SUPERFORGE / "allocator" / "substrate.toml"
TOY = SUPERFORGE / "engine" / "toy"


@pytest.fixture(scope="module")
def substrate():
    return load_substrate(SUB)


def test_substrate_loads(substrate):
    assert substrate.vram_words == 0x8000
    assert substrate.mode7_region_words == 0x4000
    assert substrate.dp_bytes == 256
    assert substrate.channel_count == 8
    assert substrate.mc_per_frame == 357368
    if substrate.vblank_usable_bytes is None:             # pre-measurement
        assert substrate.vblank_budget == substrate.vblank_start_pin == 5500
    else:                                                 # deliverable 6 pinned
        assert substrate.vblank_budget == substrate.vblank_usable_bytes
        assert 4000 <= substrate.vblank_usable_bytes <= 6479
        assert substrate.cpu_worst_frame_mc is not None
        assert substrate.cpu_worst_frame_mc < substrate.mc_per_frame


def test_toy_features_load(substrate):
    a = load_feature(TOY / "feat_a" / "feature.toml", substrate)
    assert [c.kind for c in a.vram] == ["tilemap", "chr"]
    assert a.vram[0].words == 0x400 and a.vram[1].words == 0x1000
    assert a.dp[0].bytes == 4 and a.init_zero == ("feat_a_pos",)
    b = load_feature(TOY / "feat_b" / "feature.toml", substrate)
    assert b.vram[0].words == 96 * 16 // 2                # tiles -> words
    assert b.dp[0].bytes == 2


def test_toy_state_and_manifest_load():
    st = load_state(TOY / "state.toml")
    assert {v.name for v in st.global_vars} == {"score", "lives"}
    scene = st.scene_vars[""]
    assert {v.name: v.place for v in scene} == {
        "player_x": "dp", "player_y": "dp", "scratch": "wram"}
    assert next(v for v in scene if v.name == "scratch").size == 16
    m = load_manifest(TOY / "game.toml")
    assert m.scenes[0].id == "toy"
    assert m.scenes[0].features == ("feat_a", "feat_b")


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_unknown_key_rejected(tmp_path, substrate):
    p = _write(tmp_path, "feat_x/feature.toml",
               'name = "feat_x"\nrole = "feature"\n[claims.vram]\nkind = "tilemap"\nwrds = 0x400\n')
    with pytest.raises(SchemaError, match="unknown key 'wrds'"):
        load_feature(p, substrate)


def test_feature_dir_mismatch_rejected(tmp_path, substrate):
    p = _write(tmp_path, "wrong_dir/feature.toml", 'name = "feat_x"\nrole = "feature"\n')
    with pytest.raises(SchemaError, match="must match its directory"):
        load_feature(p, substrate)


def test_mode7_claim_takes_no_size(tmp_path, substrate):
    p = _write(tmp_path, "m7/feature.toml",
               'name = "m7"\nrole = "feature"\n[claims.vram]\nkind = "mode7"\nwords = 0x400\n')
    with pytest.raises(SchemaError, match="whole interleaved"):
        load_feature(p, substrate)
    p2 = _write(tmp_path, "m7b/feature.toml", 'name = "m7b"\nrole = "feature"\n[claims.vram]\nkind = "mode7"\n')
    f = load_feature(p2, substrate)
    assert f.vram[0].words == substrate.mode7_region_words


def test_init_zero_must_reference_declared_claims(tmp_path, substrate):
    p = _write(tmp_path, "feat_z/feature.toml",
               'name = "feat_z"\nrole = "feature"\n[claims.dp]\nbytes = 2\n[init]\nzero = ["ghost"]\n')
    with pytest.raises(SchemaError, match="unknown dp/wram claims.*ghost"):
        load_feature(p, substrate)


def test_bad_state_type_rejected(tmp_path):
    p = _write(tmp_path, "state.toml", '[global]\nscore = "q16"\n')
    with pytest.raises(SchemaError, match="unknown type 'q16'"):
        load_state(p)


def test_dp_buffer_rejected(tmp_path):
    p = _write(tmp_path, "state.toml", '[scene]\nbig = "u8[64]@dp"\n')
    with pytest.raises(SchemaError, match="hot scalars"):
        load_state(p)


def test_custom_type_size(tmp_path):
    p = _write(tmp_path, "state.toml",
               '[types]\nEnemySlot = 16\n[scene]\nenemies = "EnemySlot[8]"\n')
    st = load_state(p)
    assert st.scene_vars[""][0].size == 128


def test_edge_to_unknown_scene_rejected(tmp_path):
    p = _write(tmp_path, "game.toml",
               '[[scene]]\nid = "a"\nfeatures = []\n'
               '[[edge]]\nfrom = "a"\nto = "b"\nstyle = "fade"\n')
    with pytest.raises(SchemaError, match="scene 'b' not declared"):
        load_manifest(p)


def test_edge_with_unknown_style_rejected(tmp_path):
    """the spec: `style` selects a runtime path, so a typo has to STOP the
    build rather than silently fall through to the fade machine — which is
    what it did while the field was consumed only by a report string. The
    three names are the enum's, and the failure names them back."""
    def man(style):
        return _write(tmp_path, f"{style}/game.toml",
                      '[[scene]]\nid = "a"\nfeatures = []\n'
                      '[[scene]]\nid = "b"\nfeatures = []\n'
                      f'[[edge]]\nfrom = "a"\nto = "b"\nstyle = "{style}"\n')

    for ok in ("fade", "cut", "mosaic"):
        assert load_manifest(man(ok)).edges[0].style == ok
    with pytest.raises(SchemaError, match="unknown style 'dissolve'"):
        load_manifest(man("dissolve"))
    # ...and the near-miss that matters most: a capitalised or pluralised
    # spelling of a REAL style is the shape a typo actually takes, and it must
    # refuse rather than being read as its lowercase neighbour.
    with pytest.raises(SchemaError, match="unknown style 'Cut'"):
        load_manifest(man("Cut"))


def test_dma_transfers_validation(tmp_path, substrate):
    # default: bytes>0 implies one transfer; bytes=0 implies zero
    p = _write(tmp_path, "d1/feature.toml",
               'name = "d1"\nrole = "feature"\n[claims.dma]\nvblank_bytes_per_frame = 544\n')
    assert load_feature(p, substrate).vblank_transfers_per_frame == 1
    p = _write(tmp_path, "d2/feature.toml", 'name = "d2"\nrole = "feature"\n')
    assert load_feature(p, substrate).vblank_transfers_per_frame == 0
    # explicit multi-transfer claim carries through
    p = _write(tmp_path, "d3/feature.toml",
               'name = "d3"\nrole = "feature"\n[claims.dma]\nvblank_bytes_per_frame = 1536\n'
               'vblank_transfers_per_frame = 12\n')
    assert load_feature(p, substrate).vblank_transfers_per_frame == 12
    # transfers without bytes / zero transfers with bytes are both nonsense
    p = _write(tmp_path, "d4/feature.toml",
               'name = "d4"\nrole = "feature"\n[claims.dma]\nvblank_transfers_per_frame = 2\n')
    with pytest.raises(SchemaError, match="without vblank_bytes_per_frame"):
        load_feature(p, substrate)
    p = _write(tmp_path, "d5/feature.toml",
               'name = "d5"\nrole = "feature"\n[claims.dma]\nvblank_bytes_per_frame = 64\n'
               'vblank_transfers_per_frame = 0\n')
    with pytest.raises(SchemaError, match="needs vblank_transfers_per_frame"):
        load_feature(p, substrate)


def test_hdma_band_parsing(tmp_path, substrate):
    p = _write(tmp_path, "sp/feature.toml",
               'name = "sp"\nrole = "feature"\n[claims.hdma]\nregisters = ["BGMODE"]\nband = [112, 224]\n')
    f = load_feature(p, substrate)
    assert f.hdma[0].band == (112, 224) and f.hdma[0].phase == "active"
    bad = _write(tmp_path, "sp2/feature.toml",
                 'name = "sp2"\nrole = "feature"\n[claims.hdma]\nregisters = ["BGMODE"]\nband = [224, 112]\n')
    with pytest.raises(SchemaError, match="band must be"):
        load_feature(bad, substrate)



def test_unknown_hdma_register_name_refuses_the_build(tmp_path, substrate):
    """a typo'd register used to silently opt a claim out of the
    exclusivity check rather than failing — a claim on "VMDATA_L" would
    collide with nothing. Names are checked against REGISTER_FOOTPRINT, which
    is now also the only source of a claim's port and BBAD byte, so an
    unknown name cannot resolve to silicon at all: the typo is a build error."""
    p = _write(tmp_path, "typo/feature.toml",
               'name = "typo"\nrole = "feature"\n[[claims.hdma]]\nname = "oops"\n'
               'registers = ["VMDATA_L"]\nband = "scene"\n'
               'phase = "active"\nchannels = 1\n')
    with pytest.raises(SchemaError, match="unknown register name"):
        load_feature(p, substrate)


def test_known_hdma_register_names_are_accepted(tmp_path, substrate):
    """The guard must not reject the names the engine actually uses.

    Two registers on one channel means a write-twice transfer mode, so the
    claim declares `mode = 3` — this is mode7_persp's real m7ab shape.
    """
    p = _write(tmp_path, "ok/feature.toml",
               'name = "ok"\nrole = "feature"\n[[claims.hdma]]\nname = "fine"\n'
               'registers = ["M7A", "M7B"]\nband = "scene"\nmode = 3\n'
               'phase = "active"\nchannels = 1\n')
    assert load_feature(p, substrate).name == "ok"


def test_mode_span_must_match_the_declared_registers(tmp_path, substrate):
    """The (BBAD, mode) -> port-span half of the spec

    One BBAD byte plus a transfer mode is a port SPAN, not one port: mode 3
    from BBAD $1B drives M7A *and* M7C's neighbour M7B. So a mode-3 claim
    that names only M7A is UNDER-DECLARING its footprint — the second port
    would be driven by the ROM while being invisible to every contention
    check, which is exactly the declaration-vs-reality gap. It must refuse.
    """
    under = _write(tmp_path, "under/feature.toml",
                   'name = "under"\nrole = "feature"\n[[claims.hdma]]\nname = "half"\n'
                   'registers = ["M7A"]\nmode = 3\nband = "scene"\n')
    with pytest.raises(SchemaError, match="drives 2 consecutive port"):
        load_feature(under, substrate)


def test_multi_register_claim_must_name_consecutive_ports(tmp_path, substrate):
    """A write-twice transfer drives ports BBAD and BBAD+1 — the silicon has
    no way to skip. Naming a non-adjacent pair describes a transfer the
    hardware cannot perform, so the declaration is wrong, not merely odd."""
    gappy = _write(tmp_path, "gappy/feature.toml",
                   'name = "gappy"\nrole = "feature"\n[[claims.hdma]]\nname = "jump"\n'
                   'registers = ["M7A", "M7D"]\nmode = 3\nband = "scene"\n')
    with pytest.raises(SchemaError, match="CONSECUTIVE ports"):
        load_feature(gappy, substrate)


def test_dma_init_claim_declares_channel_and_target(tmp_path, substrate):
    """claims.dma_init: the enter-time GP-DMA class. Four features used to
    drive B-bus ports through a hard-coded channel 0 with a hand-written BBAD
    byte and no claim at all; this is the declaration that makes both visible.
    """
    p = _write(tmp_path, "up/feature.toml",
               'name = "up"\nrole = "feature"\n[[claims.dma_init]]\nname = "chr_up"\n'
               'channel = 0\nregisters = ["VMDATAL", "VMDATAH"]\nmode = 1\n')
    decl = load_feature(p, substrate)
    (claim,) = decl.dma_init
    assert claim.channel == 0
    assert claim.bbad == 0x18, "BBAD must come from the declared register"
    assert claim.dmap == 0x01, "direct, mode 1"


def test_dma_init_rejects_an_out_of_range_channel(tmp_path, substrate):
    p = _write(tmp_path, "oob/feature.toml",
               'name = "oob"\nrole = "feature"\n[[claims.dma_init]]\nname = "nope"\n'
               f'channel = {substrate.channel_count}\nregisters = ["VMDATAL"]\n')
    with pytest.raises(SchemaError, match="out of range"):
        load_feature(p, substrate)


def test_window_logic_register_names_resolve_to_their_ports(tmp_path, substrate):
    """`WBGLOG`/`WOBJLOG` — the two names the design notes record as missing.

    Added by the this slice change. A name in `REGISTER_FOOTPRINT` that nothing
    claims is an ASSERTION, not a fact, so this exercises the entry rather
    than trusting it: the pair must resolve to $212A/$212B, be seen as a
    consecutive ascending span by `_parse_mode`, and produce BBAD $2A.

    this slice's own lantern does NOT depend on these — `ProcessMaskWindow`
    ignores `MaskLogic` entirely when only one window is active
    (SnesPpu.cpp:1466-1482), and the room uses window 1 alone. The names are
    here so a two-window feature can declare the combine; this test is what
    keeps the claim honest until one does.
    """
    p = _write(tmp_path, "wlog/feature.toml",
               'name = "wlog"\nrole = "feature"\n[[claims.hdma]]\nname = "wlog"\n'
               'registers = ["WBGLOG", "WOBJLOG"]\nmode = 1\nband = "scene"\n'
               'phase = "active"\nchannels = 1\n')
    (claim,) = load_feature(p, substrate).hdma
    assert claim.registers == ("WBGLOG", "WOBJLOG")
    assert claim.bbad == 0x2A, "BBAD must come from the declared register"


def test_window_logic_pair_must_still_be_ordered(tmp_path, substrate):
    """The consecutive-ascending rule is not relaxed for the new names."""
    p = _write(tmp_path, "wrev/feature.toml",
               'name = "wrev"\nrole = "feature"\n[[claims.hdma]]\nname = "wrev"\n'
               'registers = ["WOBJLOG", "WBGLOG"]\nmode = 1\nband = "scene"\n')
    with pytest.raises(SchemaError, match="CONSECUTIVE ports"):
        load_feature(p, substrate)


# --------------------------------------------------------------------------
# sram — the twelfth claim class (C2, the spec + the spec)
# --------------------------------------------------------------------------

def test_substrate_has_the_sram_table(substrate):
    """The C2 blocker the spec recorded first: no [sram] table to pack against."""
    assert substrate.sram_bytes == 0x8000, \
        "the cap is one bank window ($70:0000-$7FFF, the spec)"
    assert substrate.sram_bank == 0x70


def test_sram_claim_accepted_spelling(tmp_path, substrate):
    """`[[claims.sram]]` parses as a BytesClaim: bytes + optional name/at.

    The 'schemas.py rejects the key' blocker, closed: the exact
    spelling the save feature ships with must load, land on FeatureDecl.sram,
    and join claim_names() so the duplicate-name check sees it.
    """
    p = _write(tmp_path, "sv/feature.toml",
               'name = "sv"\nrole = "feature"\n'
               '[[claims.sram]]\nname = "save_slots"\nbytes = 64\n')
    decl = load_feature(p, substrate)
    (claim,) = decl.sram
    assert claim.name == "save_slots" and claim.bytes == 64
    assert claim.at is None and claim.dma_source is False
    assert "save_slots" in decl.claim_names()


def test_sram_claim_at_pin_parses(tmp_path, substrate):
    """Manual layout-stability pins ride the BytesClaim.at."""
    p = _write(tmp_path, "svp/feature.toml",
               'name = "svp"\nrole = "feature"\n'
               '[[claims.sram]]\nname = "pinned"\nbytes = 32\nat = 0x100\n')
    (claim,) = load_feature(p, substrate).sram
    assert claim.at == 0x100


def test_sram_claim_rejects_dma_source(tmp_path, substrate):
    """No dma_source on sram — the key
    is UNKNOWN on this class, same as on dp, so a declaration cannot even
    state the thing the class deliberately does not model."""
    p = _write(tmp_path, "svd/feature.toml",
               'name = "svd"\nrole = "feature"\n'
               '[[claims.sram]]\nbytes = 64\ndma_source = true\n')
    with pytest.raises(SchemaError, match="unknown key 'dma_source'"):
        load_feature(p, substrate)


def test_sram_claim_unknown_key_still_rejected(tmp_path, substrate):
    """Adding the class must not loosen the strict-table rule around it."""
    p = _write(tmp_path, "svt/feature.toml",
               'name = "svt"\nrole = "feature"\n'
               '[[claims.sram]]\nbites = 64\n')
    with pytest.raises(SchemaError, match="unknown key 'bites'"):
        load_feature(p, substrate)


def test_init_zero_cannot_name_an_sram_claim(tmp_path, substrate):
    """An init-zeroed save is not a save. The [init] zero
    vocabulary is dp/wram names only, so naming the sram claim refuses —
    this is the structural enforcement the class comment cites, exercised."""
    p = _write(tmp_path, "svz/feature.toml",
               'name = "svz"\nrole = "feature"\n'
               '[[claims.sram]]\nname = "slots"\nbytes = 64\n'
               '[init]\nzero = ["slots"]\n')
    with pytest.raises(SchemaError, match="unknown dp/wram claims.*slots"):
        load_feature(p, substrate)


# -- the ROM window pin ------

def test_rom_window_pin_loads_as_an_int(tmp_path, substrate):
    """The happy path — `window = 1` reaches the claim, and an unpinned claim
    stays None rather than defaulting to a window."""
    p = _write(tmp_path, "pinned/feature.toml",
               'name = "pinned"\nrole = "blob"\n'
               '[[claims.rom]]\nname = "a"\nbytes = 8450\nwindow = 1\n'
               '[[claims.rom]]\nname = "b"\nbytes = 512\n')
    a, b = load_feature(p, substrate).rom
    assert (a.window, b.window) == (1, None)


def test_rom_window_pin_rejects_a_non_int(tmp_path, substrate):
    """The strict-table type check again, asserted here because this pin
    decides a HARDWARE placement and a silently-coerced `"1"` would not."""
    p = _write(tmp_path, "badtype/feature.toml",
               'name = "badtype"\nrole = "blob"\n'
               '[[claims.rom]]\nbytes = 8450\nwindow = "one"\n')
    with pytest.raises(SchemaError, match="key 'window' must be"):
        load_feature(p, substrate)


def test_rom_window_pin_rejects_a_negative_window(tmp_path, substrate):
    """`window = -1` used to reach the allocator and be refused
    as "belongs to the linker (CODE+RODATA occupy windows 0..0)" — true of 0,
    silent about -1. Refused here, where the typo is."""
    p = _write(tmp_path, "negwin/feature.toml",
               'name = "negwin"\nrole = "blob"\n'
               '[[claims.rom]]\nbytes = 512\nwindow = -1\n')
    with pytest.raises(SchemaError, match="must be non-negative"):
        load_feature(p, substrate)
