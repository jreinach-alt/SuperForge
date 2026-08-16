"""The allocator: valid maps for good declarations, legible build-stopping
failures for colliding / over-budget ones, and the lifetime model (globals
subtracted everywhere, scene claims reused across scenes)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate, emit  # noqa: E402
from schemas import (StateDecl, load_feature, load_manifest, load_state,  # noqa: E402
                     load_substrate)

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
TOY = SUPERFORGE / "engine" / "toy"


# -- fixture helpers -------------------------------------------------------

def feature(tmp_path, name, body=""):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "feature"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, text):
    p = tmp_path / "game.toml"
    p.write_text(text)
    return load_manifest(p)


def state(tmp_path, text):
    p = tmp_path / "state.toml"
    p.write_text(text)
    return load_state(p)


NO_STATE = StateDecl((), {})


def load_toy():
    feats = {}
    for fp in sorted(TOY.glob("*/feature.toml")):
        f = load_feature(fp, SUB)
        feats[f.name] = f
    return feats, load_state(TOY / "state.toml"), load_manifest(TOY / "game.toml")


# -- the good toy ----------------------------------------------------------

def test_good_toy_allocates_non_overlapping(tmp_path):
    feats, st, man = load_toy()
    alloc = allocate(SUB, feats, st, man)
    sm = alloc.scenes["toy"]
    # independent overlap re-check (do not trust the module's own verify)
    for cls in ("dp", "wram", "vram", "cgram"):
        ps = sorted([p for p in [*alloc.globals_map, *sm.placements] if p.cls == cls],
                    key=lambda p: p.start)
        for a, b in zip(ps, ps[1:]):
            assert a.end <= b.start, f"{cls}: {a.name} overlaps {b.name}"
    # alignment facts from the substrate
    by_name = {p.name: p for p in sm.placements}
    assert by_name["feat_a_map"].start % SUB.tilemap_align_words == 0
    assert by_name["feat_a_chr"].start % SUB.chr_align_words == 0
    assert by_name["feat_b_font"].start % SUB.chr_align_words == 0
    # user state landed where declared
    assert by_name["player_x"].cls == "dp" and by_name["scratch"].cls == "wram"
    # emission produces the four artifacts (globals split from scene files)
    files = emit(alloc, tmp_path)
    names = {f.name for f in files}
    assert names == {"engine_state_globals.inc", "engine_state_toy.inc",
                     "allocation_report.txt", "symbol_map.json"}
    inc = (tmp_path / "engine_state_toy.inc").read_text()
    assert "ES_V_FEAT_A_MAP" in inc and "US_PLAYER_X" in inc
    ginc = (tmp_path / "engine_state_globals.inc").read_text()
    # globals (incl. global user state) live ONLY in the globals file
    assert "US_SCORE" in ginc and "SYS_STACK_TOP" in ginc
    assert "US_SCORE" not in inc and "SYS_STACK_TOP" not in inc
    jmap = json.loads((tmp_path / "symbol_map.json").read_text())
    assert jmap["spaces"]["io_allowed"] == [[0x2100, 0x21FF], [0x4200, 0x43FF]]


def test_cli_good_toy_exit_zero(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(TOY), "--out", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "engine_state_toy.inc").exists()


# -- collisions must stop the build ---------------------------------------

def test_pinned_vram_overlap_fails_legibly(tmp_path):
    a = feature(tmp_path, "pin_a",
                '[[claims.vram]]\nkind = "tilemap"\nwords = 0x400\nat = 0x1000\n')
    b = feature(tmp_path, "pin_b",
                '[[claims.vram]]\nkind = "tilemap"\nwords = 0x400\nat = 0x1000\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["pin_a", "pin_b"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"pin_a": a, "pin_b": b}, NO_STATE, man)
    msg = str(e.value)
    assert "VRAM overlap" in msg and "pin_" in msg and "$1000" in msg


def test_vram_over_budget_fails_with_shortfall(tmp_path):
    a = feature(tmp_path, "big_a", '[[claims.vram]]\nkind = "chr"\nwords = 0x4000\n')
    b = feature(tmp_path, "big_b", '[[claims.vram]]\nkind = "chr"\nwords = 0x4000\n')
    c = feature(tmp_path, "big_c", '[[claims.vram]]\nkind = "tilemap"\nwords = 0x400\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["big_a", "big_b", "big_c"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"big_a": a, "big_b": b, "big_c": c}, NO_STATE, man)
    msg = str(e.value)
    assert "VRAM over budget in scene 's'" in msg
    assert "exceeds 32768" in msg and "big_a" in msg


def test_dp_over_budget_exact_shortfall_and_complete_blame(tmp_path):
    """F3 (the audit's repro): 180 + 100 B across TWO features must report
    the true 24 B shortfall and blame BOTH claims — not '-156 B' with the
    placed claim missing."""
    a = feature(tmp_path, "dp_hog", '[[claims.dp]]\nbytes = 180\n')
    b = feature(tmp_path, "dp_hog2", '[[claims.dp]]\nbytes = 100\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["dp_hog", "dp_hog2"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"dp_hog": a, "dp_hog2": b}, NO_STATE, man)
    msg = str(e.value)
    assert "DP over budget in scene 's' by 24 B" in msg    # exact arithmetic
    assert "dp_hog_dp(180)" in msg and "dp_hog2_dp(100)" in msg  # full blame
    assert "exceeds 256" in msg


def test_wram_over_budget_exact_shortfall_and_complete_blame(tmp_path):
    """F3, WRAM flavor: 0x18000 + 0x8000 = 131072 B against the usable
    131072-512 (system low reserve) = 130560 B -> shortfall exactly 512."""
    a = feature(tmp_path, "buf_hog", '[[claims.wram]]\nbytes = 0x18000\n')
    b = feature(tmp_path, "buf_hog2", '[[claims.wram]]\nbytes = 0x8000\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["buf_hog", "buf_hog2"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"buf_hog": a, "buf_hog2": b}, NO_STATE, man)
    msg = str(e.value)
    assert "WRAM over budget in scene 's' by 512 B" in msg
    assert "buf_hog_wram(98304)" in msg and "buf_hog2_wram(32768)" in msg
    assert "exceeds 130560" in msg


def test_user_state_dp_over_budget_arithmetic(tmp_path):
    """F3, user-state path: engine DP + BOTH scene state vars in the blame,
    shortfall exact (200 + 30 + 30 = 260 vs 256 -> 4 B)."""
    a = feature(tmp_path, "eng", '[[claims.dp]]\nbytes = 200\n')
    st = state(tmp_path, '[scene]\nbig1 = "u8[30]@dp"\nbig2 = "u8[30]@dp"\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["eng"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"eng": a}, st, man)
    msg = str(e.value)
    assert "DP over budget in scene 's' by 4 B" in msg
    assert "eng_dp(200)" in msg and "big1(30)" in msg and "big2(30)" in msg


def test_vblank_over_budget(tmp_path):
    half = SUB.vblank_budget // 2 + 100       # two of these exceed the budget
    a = feature(tmp_path, "stream_x",
                f'[claims.dma]\nvblank_bytes_per_frame = {half}\n')
    b = feature(tmp_path, "stream_y",
                f'[claims.dma]\nvblank_bytes_per_frame = {half}\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["stream_x", "stream_y"]\n')
    with pytest.raises(AllocationError,
                       match=f"VBLANK-DMA over budget.*exceeds {SUB.vblank_budget}"):
        allocate(SUB, {"stream_x": a, "stream_y": b}, NO_STATE, man)


def test_hdma_pinned_channel_contention(tmp_path):
    a = feature(tmp_path, "grad",
                '[[claims.hdma]]\nregisters = ["COLDATA"]\nchannel = 3\n')
    b = feature(tmp_path, "split",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nchannel = 3\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["grad", "split"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"grad": a, "split": b}, NO_STATE, man)
    msg = str(e.value)
    assert "HDMA channel contention" in msg and "ch3" in msg


def test_hdma_register_contention_channel_shuffle_cannot_fix(tmp_path):
    a = feature(tmp_path, "split_a",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [0, 224]\n')
    b = feature(tmp_path, "split_b",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [100, 200]\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["split_a", "split_b"]\n')
    with pytest.raises(AllocationError, match="HDMA register contention.*BGMODE"):
        allocate(SUB, {"split_a": a, "split_b": b}, NO_STATE, man)


def test_hdma_register_contention_across_scopes(tmp_path):
    """F2: a GLOBAL claim and a SCENE claim driving the same register in
    overlapping bands of the same phase must fail — different channel
    numbers do not make PPU register writes compatible (the audit's
    silent-composition repro: BGMODE on ch0+ch1 allocated OK)."""
    g = feature(tmp_path, "g_split",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [0, 224]\n')
    s = feature(tmp_path, "s_split",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [100, 200]\n')
    man = manifest(tmp_path,
                   'globals = ["g_split"]\n'
                   '[[scene]]\nid = "s"\nfeatures = ["s_split"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"g_split": g, "s_split": s}, NO_STATE, man)
    msg = str(e.value)
    assert "HDMA register contention" in msg and "BGMODE" in msg
    assert "g_split" in msg and "s_split" in msg      # both claims named
    assert "100-200" in msg                           # the overlapping band


def test_hdma_cross_scope_disjoint_band_or_phase_still_passes(tmp_path):
    """The F2 fix must not over-reach: cross-scope same-register claims in
    DISJOINT bands, or in different phases, are legal compositions."""
    g = feature(tmp_path, "g_top",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [0, 100]\n')
    s = feature(tmp_path, "s_bot",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [100, 200]\n')
    man = manifest(tmp_path,
                   'globals = ["g_top"]\n'
                   '[[scene]]\nid = "s"\nfeatures = ["s_bot"]\n')
    alloc = allocate(SUB, {"g_top": g, "s_bot": s}, NO_STATE, man)
    assert len(alloc.scenes["s"].channels) == 1       # disjoint bands: OK

    g2 = feature(tmp_path, "g_act",
                 '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [0, 224]\n')
    s2 = feature(tmp_path, "s_vb",
                 '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = [0, 224]\n'
                 'phase = "vblank"\n')
    man2 = manifest(tmp_path,
                    'globals = ["g_act"]\n'
                    '[[scene]]\nid = "s"\nfeatures = ["s_vb"]\n')
    alloc2 = allocate(SUB, {"g_act": g2, "s_vb": s2}, NO_STATE, man2)
    assert len(alloc2.scenes["s"].channels) == 1      # phase-disjoint: OK


def test_vblank_claims_may_share_a_register(tmp_path):
    """Register exclusivity is an ACTIVE-display phenomenon. VBlank claims
    are queue entries the NMI hook fires one after another (mode7_stream
    already drives 16 back-to-back VMDATAL transfers through one claim), so
    two of them driving VMDATAL compose — refusing that was a false negative
    that blocked streaming plus any second VBlank VRAM upload. They still
    take a channel each, and verify() must agree with the solver."""
    from allocate import verify
    a = feature(tmp_path, "streamer",
                '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n'
                'phase = "vblank"\n'
                '[claims.dma]\nvblank_bytes_per_frame = 2048\n'
                'vblank_transfers_per_frame = 16\n')
    b = feature(tmp_path, "hud_upload",
                '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n'
                'phase = "vblank"\n'
                '[claims.dma]\nvblank_bytes_per_frame = 64\n'
                'vblank_transfers_per_frame = 1\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["streamer", "hud_upload"]\n')
    alloc = allocate(SUB, {"streamer": a, "hud_upload": b}, NO_STATE, man)
    chans = alloc.scenes["s"].channels
    assert len(chans) == 2
    assert len({c.channel for c in chans}) == 2, "each claim still owns a channel"
    verify(alloc)                                    # solver and checker agree


def test_vblank_shared_register_still_pays_the_measured_budget(tmp_path):
    """...and the teeth that DO govern vblank composition still bite: the
    byte + per-transfer arm cost. Same two same-register claims, sized past
    the measured budget, must refuse."""
    a = feature(tmp_path, "streamer",
                '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n'
                'phase = "vblank"\n'
                '[claims.dma]\nvblank_bytes_per_frame = 4096\n'
                'vblank_transfers_per_frame = 8\n')
    b = feature(tmp_path, "hud_upload",
                '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n'
                'phase = "vblank"\n'
                '[claims.dma]\nvblank_bytes_per_frame = 2048\n'
                'vblank_transfers_per_frame = 8\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["streamer", "hud_upload"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"streamer": a, "hud_upload": b}, NO_STATE, man)
    msg = str(e.value)
    assert "VBLANK-DMA over budget" in msg
    assert "streamer(4096)" in msg and "hud_upload(2048)" in msg  # both blamed
    assert "arm_overhead(16 transfers x 128 B)(1920)" in msg      # measured pin


def test_vblank_register_sharing_does_not_leak_into_the_active_phase(tmp_path):
    """The exemption must be exactly one phase wide. The same shape of
    declaration in the ACTIVE phase — in-scene AND cross-scope — still
    refuses, and a vblank claim never excuses an active pair."""
    act_a = feature(tmp_path, "act_a",
                    '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n')
    act_b = feature(tmp_path, "act_b",
                    '[[claims.hdma]]\nregisters = ["VMDATAL"]\nband = [0, 224]\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["act_a", "act_b"]\n')
    with pytest.raises(AllocationError, match="HDMA register contention.*VMDATAL"):
        allocate(SUB, {"act_a": act_a, "act_b": act_b}, NO_STATE, man)

    # cross-scope (F2) in the active phase: still refused
    g = feature(tmp_path, "g_act",
                '[[claims.hdma]]\nregisters = ["COLDATA_R"]\nband = [0, 224]\n')
    s = feature(tmp_path, "s_act",
                '[[claims.hdma]]\nregisters = ["COLDATA_R"]\nband = [40, 200]\n')
    man2 = manifest(tmp_path,
                    'globals = ["g_act"]\n'
                    '[[scene]]\nid = "s"\nfeatures = ["s_act"]\n')
    with pytest.raises(AllocationError, match="HDMA register contention"):
        allocate(SUB, {"g_act": g, "s_act": s}, NO_STATE, man2)


def test_verify_allows_shared_registers_only_in_the_vblank_phase():
    """verify() is the independent checker; hand it both unions directly so
    its rule is pinned without going through the solver."""
    from allocate import GLOBAL, Allocation, ChannelAssign, SceneMap, verify
    def union(phase):
        sm = SceneMap(scene="s")
        sm.channels = [ChannelAssign("s_q", 1, ("VMDATAL",), (0, 224),
                                     phase, "s", "engine:s_up")]
        gch = [ChannelAssign("g_q", 0, ("VMDATAL",), (0, 224),
                             phase, GLOBAL, "engine:g_up")]
        return Allocation(SUB, [], gch, {"s": sm}, [])
    verify(union("vblank"))                          # serialised: legal
    with pytest.raises(AssertionError, match="register contention.*VMDATAL"):
        verify(union("active"))                      # concurrent: refused


def test_verify_catches_cross_scope_register_conflict():
    """Belt-and-suspenders is independent of the solver: hand verify() a
    hand-built global+scene union with a register conflict and it must
    throw even though no channel is double-booked."""
    from allocate import GLOBAL, Allocation, ChannelAssign, SceneMap, verify
    sm = SceneMap(scene="s")
    sm.channels = [ChannelAssign("s_split_hdma", 1, ("BGMODE",), (100, 200),
                                 "active", "s", "engine:s_split")]
    gch = [ChannelAssign("g_split_hdma", 0, ("BGMODE",), (0, 224),
                         "active", GLOBAL, "engine:g_split")]
    alloc = Allocation(SUB, [], gch, {"s": sm}, [])
    with pytest.raises(AssertionError, match="register contention.*BGMODE"):
        verify(alloc)


# Distinct REAL register names, for tests that just need N non-colliding
# claims. They used to be synthetic ("R0", "R1", ...); register names are now
# validated against a known list, because a typo'd name silently opts a claim
# out of contention. Using real ones keeps the fixtures honest
# about what a claim can name.
DISTINCT_REGS = ("BGMODE", "TM", "TS", "TMW", "TSW", "MOSAIC", "OBSEL",
                 "SETINI", "M7SEL", "W12SEL", "W34SEL", "WOBJSEL")


# -- sub-register footprints --

def test_whole_port_claim_collides_with_a_plane_claim(tmp_path):
    """The hole a later review reproduced: COLDATA vs COLDATA_R.

    Under name equality these two strings differ, so a whole-port claim and a
    plane claim on the SAME silicon ($2132) allocated cleanly
    a rogue COLDATA claim into the race scene and it was ACCEPTED. Footprint
    intersection has to refuse it, in both orders.
    """
    whole = feature(tmp_path, "cd_whole",
                    '[[claims.hdma]]\nregisters = ["COLDATA"]\nband = [0, 224]\n')
    plane = feature(tmp_path, "cd_plane",
                    '[[claims.hdma]]\nregisters = ["COLDATA_R"]\nband = [0, 224]\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["cd_whole", "cd_plane"]\n')
    with pytest.raises(AllocationError, match="COLDATA.*2132"):
        allocate(SUB, {"cd_whole": whole, "cd_plane": plane}, NO_STATE, man)

    man2 = manifest(tmp_path,
                    '[[scene]]\nid = "s"\nfeatures = ["cd_plane", "cd_whole"]\n')
    with pytest.raises(AllocationError, match="COLDATA.*2132"):
        allocate(SUB, {"cd_whole": whole, "cd_plane": plane}, NO_STATE, man2)


def test_distinct_planes_of_one_port_still_compose(tmp_path):
    """The other half: the model must not over-refuse.

    rgb_gradient ships three claims on $2132 — one per plane — and they are
    genuinely independent because each write selects its plane in the DATA
    byte. Disjoint masks must allocate, or the new check breaks a shipping
    composition to close a hole.
    """
    r = feature(tmp_path, "g_r",
                '[[claims.hdma]]\nregisters = ["COLDATA_R"]\nband = [0, 224]\n')
    g = feature(tmp_path, "g_g",
                '[[claims.hdma]]\nregisters = ["COLDATA_G"]\nband = [0, 224]\n')
    b = feature(tmp_path, "g_b",
                '[[claims.hdma]]\nregisters = ["COLDATA_B"]\nband = [0, 224]\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["g_r", "g_g", "g_b"]\n')
    alloc = allocate(SUB, {"g_r": r, "g_g": g, "g_b": b}, NO_STATE, man)
    chans = {c.name: c.channel for c in alloc.scenes["s"].channels}
    assert len(set(chans.values())) == 3, f"planes must get distinct channels: {chans}"


def test_plane_collision_is_caught_across_scopes_too(tmp_path):
    """The cross-scope pre-pass (F2) shares the footprint model, so a global
    plane claim and a scene whole-port claim must also refuse."""
    g = feature(tmp_path, "gg_plane",
                '[[claims.hdma]]\nregisters = ["COLDATA_B"]\nband = [0, 224]\n')
    s = feature(tmp_path, "ss_whole",
                '[[claims.hdma]]\nregisters = ["COLDATA"]\nband = [100, 200]\n')
    man = manifest(tmp_path,
                   'globals = ["gg_plane"]\n'
                   '[[scene]]\nid = "s"\nfeatures = ["ss_whole"]\n')
    with pytest.raises(AllocationError, match="COLDATA.*2132"):
        allocate(SUB, {"gg_plane": g, "ss_whole": s}, NO_STATE, man)


def test_hdma_pool_exhaustion(tmp_path):
    feats, names = {}, []
    for i in range(9):
        n = f"fx{i}"
        feats[n] = feature(tmp_path, n, f'[[claims.hdma]]\nregisters = ["{DISTINCT_REGS[i]}"]\n')
        names.append(n)
    man = manifest(tmp_path,
                   f'[[scene]]\nid = "s"\nfeatures = {names!r}\n'.replace("'", '"'))
    with pytest.raises(AllocationError, match="HDMA channels over capacity"):
        allocate(SUB, feats, NO_STATE, man)


def test_channels_reusable_across_disjoint_bands_and_phases(tmp_path):
    """The axis split-mode died on: disjoint bands share a channel; VBlank
    GP-DMA and active-display HDMA time-share one channel (CH0)."""
    feats, names = {}, []
    for i in range(8):
        n = f"band{i}"
        feats[n] = feature(
            tmp_path, n,
            f'[[claims.hdma]]\nregisters = ["{DISTINCT_REGS[i]}"]\n'
            f'band = [0, 224]\n')
        names.append(n)
    # 8 whole-frame active claims fill the pool; a 9th fits only because its
    # band is disjoint... it isn't — so instead prove reuse explicitly:
    feats["top"] = feature(tmp_path, "top",
                           '[[claims.hdma]]\nregisters = ["TM"]\nband = [0, 112]\n')
    feats["bottom"] = feature(tmp_path, "bottom",
                              '[[claims.hdma]]\nregisters = ["TMW"]\nband = [112, 224]\n')
    feats["vb"] = feature(tmp_path, "vb",
                          '[[claims.hdma]]\nregisters = ["OAMDATA"]\nphase = "vblank"\n')
    man = manifest(
        tmp_path,
        '[[scene]]\nid = "s"\nfeatures = ["top", "bottom", "vb"]\n')
    alloc = allocate(SUB, {k: feats[k] for k in ("top", "bottom", "vb")},
                     NO_STATE, man)
    chans = {c.name: c.channel for c in alloc.scenes["s"].channels}
    assert chans["top_hdma"] == chans["bottom_hdma"] == 0  # disjoint bands share ch0
    assert chans["vb_hdma"] == 0                           # phase-disjoint shares too


def test_mode7_displaces_obj_chr(tmp_path):
    m7 = feature(tmp_path, "m7", '[[claims.vram]]\nkind = "mode7"\n')
    spr = feature(tmp_path, "spr",
                  '[[claims.vram]]\nkind = "chr"\nwords = 0x1000\nobj = true\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["m7", "spr"]\n')
    alloc = allocate(SUB, {"m7": m7, "spr": spr}, NO_STATE, man)
    by_name = {p.name: p for p in alloc.scenes["s"].placements}
    assert by_name["m7_mode7"].start == 0
    assert by_name["spr_chr"].start >= SUB.mode7_obj_chr_floor_word
    assert by_name["spr_chr"].start % SUB.obj_chr_align_words == 0


def test_wram_dma_source_never_straddles_bank(tmp_path):
    filler = feature(tmp_path, "filler", '[[claims.wram]]\nbytes = 0xFA00\n')
    src = feature(tmp_path, "src",
                  '[[claims.wram]]\nbytes = 0x1000\ndma_source = true\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["filler", "src"]\n')
    alloc = allocate(SUB, {"filler": filler, "src": src}, NO_STATE, man)
    p = next(p for p in alloc.scenes["s"].placements if p.name == "src_wram")
    assert p.start // SUB.wram_bank_bytes == (p.end - 1) // SUB.wram_bank_bytes, \
        f"dma_source claim straddles the WRAM bank: [{p.start:#x}..{p.end:#x})"


# -- lifetimes -------------------------------------------------------------

def test_globals_reserved_in_every_scene_and_scene_memory_reused(tmp_path):
    aud = feature(tmp_path, "audio", '[[claims.wram]]\nbytes = 256\n'
                                     '[[claims.dp]]\nbytes = 8\n')
    lvl1 = feature(tmp_path, "lvl1", '[[claims.wram]]\nname = "enemies1"\nbytes = 64\n')
    lvl2 = feature(tmp_path, "lvl2", '[[claims.wram]]\nname = "enemies2"\nbytes = 64\n')
    man = manifest(tmp_path,
                   'globals = ["audio"]\n'
                   '[[scene]]\nid = "one"\nfeatures = ["lvl1"]\n'
                   '[[scene]]\nid = "two"\nfeatures = ["lvl2"]\n'
                   '[[edge]]\nfrom = "one"\nto = "two"\nstyle = "fade"\n')
    alloc = allocate(SUB, {"audio": aud, "lvl1": lvl1, "lvl2": lvl2}, NO_STATE, man)
    g = {p.name: p for p in alloc.globals_map}
    one = {p.name: p for p in alloc.scenes["one"].placements}
    two = {p.name: p for p in alloc.scenes["two"].placements}
    # globals sit below scene claims and never collide with them
    assert g["audio_wram"].end <= min(one["enemies1"].start, two["enemies2"].start)
    # the lifetime dividend: scene-scoped memory is REUSED across scenes
    assert one["enemies1"].start == two["enemies2"].start


def test_vblank_arm_cost_charged_per_extra_transfer(tmp_path):
    """F9 multi-queue model: bytes alone fit, bytes + arm overhead do not.
    Uses the pinned substrate arm cost (drift-guarded by make measure)."""
    assert SUB.vblank_arm_cost > 0, "substrate arm_cost not pinned"
    room = SUB.vblank_budget - 152        # fits alone, breaks with 2 extra arms
    ok = feature(tmp_path, "one_xfer",
                 f'[claims.dma]\nvblank_bytes_per_frame = {room}\n')
    man1 = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["one_xfer"]\n')
    alloc = allocate(SUB, {"one_xfer": ok}, NO_STATE, man1)
    assert alloc.scenes["s"].vblank_transfers == 1    # defaulted from bytes>0

    many = feature(tmp_path, "many_xfer",
                   f'[claims.dma]\nvblank_bytes_per_frame = {room}\n'
                   f'vblank_transfers_per_frame = 3\n')
    man2 = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["many_xfer"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"many_xfer": many}, NO_STATE, man2)
    msg = str(e.value)
    assert "VBLANK-DMA over budget" in msg and "by 104 B" in msg
    assert "arm_overhead(3 transfers x 128 B)(256)" in msg


def test_emit_splits_globals_from_scoped_scene_files(tmp_path):
    aud = feature(tmp_path, "audio", '[[claims.wram]]\nbytes = 256\n'
                                     '[init]\nzero = ["audio_wram"]\n')
    txt = feature(tmp_path, "txt",
                  '[[claims.vram]]\nname = "font"\nkind = "chr"\n'
                  'tiles = 96\ntile_bytes = 16\n')
    man = manifest(tmp_path,
                   'globals = ["audio"]\n'
                   '[[scene]]\nid = "one"\nfeatures = ["txt"]\n'
                   '[[scene]]\nid = "two"\nfeatures = ["txt"]\n')
    alloc = allocate(SUB, {"audio": aud, "txt": txt}, NO_STATE, man)
    files = emit(alloc, tmp_path / "out")
    assert {f.name for f in files} == {
        "engine_state_globals.inc", "engine_state_one.inc",
        "engine_state_two.inc", "allocation_report.txt", "symbol_map.json"}
    g = (tmp_path / "out" / "engine_state_globals.inc").read_text()
    one = (tmp_path / "out" / "engine_state_one.inc").read_text()
    two = (tmp_path / "out" / "engine_state_two.inc").read_text()
    # globals + system symbols + the BOOT init contract: globals file only
    assert "ES_AUDIO_WRAM" in g and "SYS_STACK_TOP" in g and "once at boot" in g
    for s in (one, two):
        assert "ES_AUDIO_WRAM" not in s and "SYS_STACK_TOP" not in s
    # the same feature in two scenes emits the same symbol NAME in both scene
    # files — the reason multi-scene ROMs wrap scene includes in .scope
    assert "ES_V_FONT" in one and "ES_V_FONT" in two


def test_scene_state_via_subtables_and_global_state_survives(tmp_path):
    st = state(tmp_path,
               '[global]\nscore = "u16"\n'
               '[scene.one]\np = "u16@dp"\n[scene.two]\nq = "u16@dp"\n')
    a = feature(tmp_path, "a", "")
    man = manifest(tmp_path,
                   '[[scene]]\nid = "one"\nfeatures = ["a"]\n'
                   '[[scene]]\nid = "two"\nfeatures = ["a"]\n')
    alloc = allocate(SUB, {"a": a}, st, man)
    assert any(p.name == "score" for p in alloc.globals_map)
    p1 = next(p for p in alloc.scenes["one"].placements if p.name == "p")
    q2 = next(p for p in alloc.scenes["two"].placements if p.name == "q")
    assert p1.start == q2.start        # scene DP reused across scenes


def test_flat_scene_state_rejected_for_multiscene(tmp_path):
    st = state(tmp_path, '[scene]\np = "u16"\n')
    a = feature(tmp_path, "a", "")
    man = manifest(tmp_path,
                   '[[scene]]\nid = "one"\nfeatures = ["a"]\n'
                   '[[scene]]\nid = "two"\nfeatures = ["a"]\n')
    with pytest.raises(AllocationError, match="single-scene"):
        allocate(SUB, {"a": a}, st, man)


def test_dependency_resolution_and_cycle(tmp_path):
    base = feature(tmp_path, "text_mono", '[[claims.vram]]\nkind = "chr"\nwords = 0x300\n')
    vwf = feature(tmp_path, "text_vwf",
                  'depends = ["text_mono"]\n[[claims.wram]]\nbytes = 384\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["text_vwf"]\n')
    alloc = allocate(SUB, {"text_mono": base, "text_vwf": vwf}, NO_STATE, man)
    names = {p.name for p in alloc.scenes["s"].placements}
    assert "text_mono_chr" in names and "text_vwf_wram" in names
    x = feature(tmp_path, "x", 'depends = ["y"]\n')
    y = feature(tmp_path, "y", 'depends = ["x"]\n')
    man2 = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["x"]\n')
    with pytest.raises(AllocationError, match="dependency cycle"):
        allocate(SUB, {"x": x, "y": y}, NO_STATE, man2)


def test_transition_budget_enforced(tmp_path):
    heavy = feature(tmp_path, "heavy", '[[claims.vram]]\nkind = "chr"\nwords = 0x2000\n')
    lite = feature(tmp_path, "lite", "")
    man = manifest(tmp_path,
                   '[[scene]]\nid = "one"\nfeatures = ["lite"]\n'
                   '[[scene]]\nid = "two"\nfeatures = ["heavy"]\n'
                   '[[edge]]\nfrom = "one"\nto = "two"\nstyle = "fade"\n'
                   'budget_bytes = 1000\n')
    with pytest.raises(AllocationError, match="transition one->two.*over by"):
        allocate(SUB, {"heavy": heavy, "lite": lite}, NO_STATE, man)


def test_rom_claims_never_land_in_code_windows(tmp_path):
    small = feature(tmp_path, "asset", '[[claims.rom]]\nbytes = 1536\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["asset"]\n')
    alloc = allocate(SUB, {"asset": small}, NO_STATE, man)
    p = next(p for p in alloc.scenes["s"].placements if p.cls == "rom")
    assert p.start >= SUB.rom_code_windows * SUB.rom_window_bytes, \
        f"claim landed in a linker code window: {p.start:#x}"


def test_rom_dma_source_window_rule(tmp_path):
    big = feature(tmp_path, "worldmap",
                  '[[claims.rom]]\nbytes = 0x40000\n')     # 256 KB, not tiled
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["worldmap"]\n')
    with pytest.raises(AllocationError, match="exceeds the 32768 B LoROM DMA window"):
        allocate(SUB, {"worldmap": big}, NO_STATE, man)
    tiled = feature(tmp_path, "worldmap2",
                    '[[claims.rom]]\nbytes = 0x40000\nbank_tiled = true\n')
    man2 = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["worldmap2"]\n')
    alloc = allocate(SUB, {"worldmap2": tiled}, NO_STATE, man2)
    chunks = [p for p in alloc.scenes["s"].placements if p.cls == "rom"]
    assert len(chunks) == 8                       # 256 KB / 32 KB windows
    for p in chunks:
        assert p.start // SUB.rom_window_bytes == (p.end - 1) // SUB.rom_window_bytes


# -- bank_tiled ADJACENCY --------------------------------------------------
#
# `bank_tiled` used to promise only "every chunk fits one bank window". Three
# call sites read chunk i out of bank BASE+i off ONE window base anyway —
# mode7_stream's MVN stub table and stream_stage_col, mode7_floor's seed
# upload, col_map's `bank = T0_BANK + (ty >> log2(rpc))` — and nothing checked
# it. `place_rom` first-fit each chunk INDEPENDENTLY, rescanning from window 0,
# so a short tail chunk could land behind its own predecessors
#.
#
# All three cases below packed NON-consecutively before the run-placement
# branch landed, measured on the real function: [1,2,4], [2,3,1] (tail at
# offset $0100), and a two-blob shape needing no pin at all. Today's tree
# cannot catch a regression here — every tiled blob in it is a whole multiple
# of the window and was already consecutive, which is exactly why the
# invariant went unasserted for so long. These are the shapes that bite.

def _tiled_chunks(alloc, scene, name):
    ps = [p for p in alloc.scenes[scene].placements
          if p.cls == "rom" and p.name.startswith(f"{name}_t")]
    ps.sort(key=lambda p: int(p.name.rsplit("_t", 1)[1]))
    assert ps, f"no chunk placements for {name}"
    return ps


def _assert_run(chunks, who):
    win = SUB.rom_window_bytes
    banks = [p.start // win for p in chunks]
    offs = {p.start % win for p in chunks}
    assert banks == list(range(banks[0], banks[0] + len(banks))), \
        f"{who}: chunk banks are not consecutive: {banks}"
    assert offs == {0}, \
        f"{who}: chunks are not all at window offset 0: {sorted(offs)}"


def test_bank_tiled_chunks_skip_a_pinned_window_as_a_run(tmp_path):
    """A pin ABOVE the blob must not split it. Was [1,2,4]."""
    blob = feature(tmp_path, "blob",
                   '[[claims.rom]]\nbytes = 98304\nbank_tiled = true\n')
    pin = feature(tmp_path, "pin", '[[claims.rom]]\nbytes = 256\nwindow = 3\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["blob", "pin"]\n')
    alloc = allocate(SUB, {"blob": blob, "pin": pin}, NO_STATE, man)
    _assert_run(_tiled_chunks(alloc, "s", "blob_rom"), "blob behind a window-3 pin")


def test_ragged_bank_tiled_tail_does_not_backfill_behind_its_run(tmp_path):
    """The short tail chunk must not first-fit into an earlier partial window.

    Was [2,3,1] with the tail at offset $0100 — so this shape broke BOTH
    halves of the invariant: the bank order AND the shared window base that
    M7S_WORLD_WIN / CM_WORLD_BLOB is.
    """
    blob = feature(tmp_path, "blob",
                   '[[claims.rom]]\nbytes = 66560\nbank_tiled = true\n')
    pin = feature(tmp_path, "pin", '[[claims.rom]]\nbytes = 256\nwindow = 1\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["blob", "pin"]\n')
    alloc = allocate(SUB, {"blob": blob, "pin": pin}, NO_STATE, man)
    _assert_run(_tiled_chunks(alloc, "s", "blob_rom"), "ragged blob behind a pin")


def test_two_ragged_bank_tiled_blobs_pack_as_runs_with_no_pin(tmp_path):
    """The case that needs NO pin and no unusual declaration — just two tiled
    blobs whose byte counts are not multiples of the window. Each one's tail
    left a partial window the OTHER's chunks first-fit into."""
    a = feature(tmp_path, "aa_blob",
                '[[claims.rom]]\nbytes = 33792\nbank_tiled = true\n')
    b = feature(tmp_path, "bb_blob",
                '[[claims.rom]]\nbytes = 34816\nbank_tiled = true\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "s"\nfeatures = ["aa_blob", "bb_blob"]\n')
    alloc = allocate(SUB, {"aa_blob": a, "bb_blob": b}, NO_STATE, man)
    _assert_run(_tiled_chunks(alloc, "s", "aa_blob_rom"), "aa_blob")
    _assert_run(_tiled_chunks(alloc, "s", "bb_blob_rom"), "bb_blob")
    # ...and the two runs must not overlap each other
    win = SUB.rom_window_bytes
    banks_a = {p.start // win for p in _tiled_chunks(alloc, "s", "aa_blob_rom")}
    banks_b = {p.start // win for p in _tiled_chunks(alloc, "s", "bb_blob_rom")}
    assert not (banks_a & banks_b), f"runs overlap: {banks_a} vs {banks_b}"


# -- the ROM window PIN ----------------------------------------------------
#
# `RomClaim.window` (a later sweep) reserves a claim's LoROM window because something
# outside the allocator already fixed it there — vendor/rom/lorom_512k.cfg maps
# AUDIO_DATA0 to ROM1 by name, so `tad_export` physically IS window 1. It
# shipped with no tests at all: a schema field, a placement
# pass and four refusal paths, exercised only by tad_rom's own happy path.
#
# These are the "prove it fails on a real violation" cases AGENTS.md asks for.
# The first is the one that matters most — WITHOUT it a pin that silently did
# nothing would still leave every rail green, because largest-first happens to
# agree with the pin in today's tree.

def _win(p):
    return p.start // SUB.rom_window_bytes


def test_rom_pin_binds_against_largest_first(tmp_path):
    """The pin CHANGES the placement — the same pair, packed both ways.

    Names are chosen so the free pass's `(-bytes, name)` tie-break would put
    the big claim in window 1 and the small one in window 2. Pinning the small
    one to window 1 must invert that; if the field were decorative both halves
    would agree and this test is the only thing that would notice.
    """
    big = feature(tmp_path, "aa_big", '[[claims.rom]]\nbytes = 32768\n')
    small = feature(tmp_path, "zz_small", '[[claims.rom]]\nbytes = 8450\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["aa_big", "zz_small"]\n')
    free = {p.name: _win(p) for p in
            allocate(SUB, {"aa_big": big, "zz_small": small}, NO_STATE, man
                     ).scenes["s"].placements if p.cls == "rom"}
    assert free == {"aa_big_rom": 1, "zz_small_rom": 2}

    pinned = feature(tmp_path, "zz_small2",
                     '[[claims.rom]]\nbytes = 8450\nwindow = 1\n')
    big2 = feature(tmp_path, "aa_big2", '[[claims.rom]]\nbytes = 32768\n')
    man2 = manifest(tmp_path,
                    '[[scene]]\nid = "s"\nfeatures = ["aa_big2", "zz_small2"]\n')
    got = {p.name: _win(p) for p in
           allocate(SUB, {"aa_big2": big2, "zz_small2": pinned}, NO_STATE, man2
                    ).scenes["s"].placements if p.cls == "rom"}
    assert got == {"zz_small2_rom": 1, "aa_big2_rom": 2}, \
        "the pin did not move the placement — window= is not load-bearing"


def test_rom_pin_shares_its_window_with_free_claims(tmp_path):
    """A partial-window pin reserves its BYTES, not the whole window.

    `tad_export` is 8,450 B in a 32 KB window; a small free blob may follow it
    there. Asserted so a future "a pin owns its window" simplification cannot
    land silently.
    """
    pin = feature(tmp_path, "pinned", '[[claims.rom]]\nbytes = 1024\nwindow = 1\n')
    fill = feature(tmp_path, "filler", '[[claims.rom]]\nbytes = 4096\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["pinned", "filler"]\n')
    got = {p.name: (_win(p), p.start % SUB.rom_window_bytes) for p in
           allocate(SUB, {"pinned": pin, "filler": fill}, NO_STATE, man
                    ).scenes["s"].placements if p.cls == "rom"}
    assert got == {"pinned_rom": (1, 0), "filler_rom": (1, 1024)}


def test_rom_pin_refuses_a_claim_that_cannot_fit_one_window(tmp_path):
    """A pin names ONE window, so a multi-window claim cannot take one."""
    tiled = feature(tmp_path, "tiled_pin",
                    '[[claims.rom]]\nbytes = 65536\nbank_tiled = true\nwindow = 2\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["tiled_pin"]\n')
    with pytest.raises(AllocationError, match="a pin names ONE window"):
        allocate(SUB, {"tiled_pin": tiled}, NO_STATE, man)
    over = feature(tmp_path, "big_pin",
                   '[[claims.rom]]\nbytes = 32769\nwindow = 2\n')
    man2 = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["big_pin"]\n')
    with pytest.raises(AllocationError, match="a pin names ONE window"):
        allocate(SUB, {"big_pin": over}, NO_STATE, man2)


def test_rom_pin_refuses_a_linker_code_window(tmp_path):
    """Window 0 is CODE+RODATA's; the linker put it there, not the allocator."""
    code = feature(tmp_path, "code_pin", '[[claims.rom]]\nbytes = 512\nwindow = 0\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["code_pin"]\n')
    with pytest.raises(AllocationError, match="belongs to the linker"):
        allocate(SUB, {"code_pin": code}, NO_STATE, man)


def test_rom_pin_refuses_two_claims_on_one_window(tmp_path):
    """Two pins, one window, 32,768 B each — the second cannot have it."""
    a = feature(tmp_path, "pin_a", '[[claims.rom]]\nbytes = 32768\nwindow = 1\n')
    b = feature(tmp_path, "pin_b", '[[claims.rom]]\nbytes = 32768\nwindow = 1\n')
    man = manifest(tmp_path, '[[scene]]\nid = "s"\nfeatures = ["pin_a", "pin_b"]\n')
    with pytest.raises(AllocationError, match="has no room for 32768 B"):
        allocate(SUB, {"pin_a": a, "pin_b": b}, NO_STATE, man)


def test_rom_pin_is_a_premise_ACROSS_scopes_not_within_one_pass(tmp_path):
    """The finding, the regression this hoist exists for.

    `place_rom` runs once for globals and again per scene over one shared
    window list. With the pinned pass inside it, a scene-scoped pin lost
    window 1 to a GLOBAL free claim placed in the earlier call and reported
    "another claim reached it first" — a pin that is a preference, exactly what
    `RomClaim.window`'s docstring says it is not. Both directions asserted, and
    the free claim must be displaced rather than the pin refused.
    """
    gfree = feature(tmp_path, "g_free", '[[claims.rom]]\nbytes = 32768\n')
    spin = feature(tmp_path, "s_pin", '[[claims.rom]]\nbytes = 8450\nwindow = 1\n')
    man = manifest(tmp_path,
                   'globals = ["g_free"]\n'
                   '[[scene]]\nid = "s"\nfeatures = ["s_pin"]\n')
    alloc = allocate(SUB, {"g_free": gfree, "s_pin": spin}, NO_STATE, man)
    got = {p.name: _win(p) for p in
           [*alloc.globals_map, *alloc.scenes["s"].placements] if p.cls == "rom"}
    assert got == {"s_pin_rom": 1, "g_free_rom": 2}, \
        "a scene-scoped pin lost its window to a global free claim"

    # ...and scene B's pin against scene A's free claim, the other ordering.
    afree = feature(tmp_path, "a_free", '[[claims.rom]]\nbytes = 32768\n')
    bpin = feature(tmp_path, "b_pin", '[[claims.rom]]\nbytes = 8450\nwindow = 1\n')
    man2 = manifest(tmp_path,
                    '[[scene]]\nid = "a"\nfeatures = ["a_free"]\n'
                    '[[scene]]\nid = "b"\nfeatures = ["b_pin"]\n')
    alloc2 = allocate(SUB, {"a_free": afree, "b_pin": bpin}, NO_STATE, man2)
    got2 = {p.name: _win(p) for p in
            [*alloc2.scenes["a"].placements, *alloc2.scenes["b"].placements]
            if p.cls == "rom"}
    assert got2 == {"b_pin_rom": 1, "a_free_rom": 2}


def test_rom_pin_refuses_a_negative_window_in_the_allocator_too(tmp_path):
    """The schema refuses `window = -1` first (test_schemas), but the internal
    API is reachable without it — so the placement pass keeps its own guard,
    and it must NOT be the misleading code-window message."""
    sys.path.insert(0, str(SUPERFORGE / "allocator"))
    from allocate import FreeList, reserve_pinned_rom              # noqa: E402
    from schemas import RomClaim                                   # noqa: E402
    with pytest.raises(AllocationError, match="must be non-negative"):
        reserve_pinned_rom([(RomClaim(name="neg", bytes=512, window=-1),
                             "engine:neg", "s")],
                           [FreeList(0, 0)], SUB)


def test_cli_collision_exits_nonzero(tmp_path):
    (tmp_path / "pin_a").mkdir()
    (tmp_path / "pin_a" / "feature.toml").write_text(
        'name = "pin_a"\nrole = "feature"\n[[claims.vram]]\nkind = "tilemap"\nwords = 0x400\nat = 0x1000\n')
    (tmp_path / "pin_b").mkdir()
    (tmp_path / "pin_b" / "feature.toml").write_text(
        'name = "pin_b"\nrole = "feature"\n[[claims.vram]]\nkind = "tilemap"\nwords = 0x400\nat = 0x1000\n')
    (tmp_path / "game.toml").write_text(
        '[[scene]]\nid = "s"\nfeatures = ["pin_a", "pin_b"]\n')
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(tmp_path), "--out", str(tmp_path / "out")],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "ALLOCATION FAILED" in r.stderr and "VRAM overlap" in r.stderr
    assert not (tmp_path / "out" / "engine_state_s.inc").exists()
    assert not (tmp_path / "out" / "engine_state_globals.inc").exists()
