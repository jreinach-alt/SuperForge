"""The split_h_2p asset gate, asserted in BOTH directions.

`tools/gen_split_h_2p_assets.py` rebuilds the checker world, the perspective
ramp and the palette from their stated rules, and REFUSES to emit anything that
disagrees with the blobs vendored under `vendor/art/split_h_2p/`. That refusal
is the one asset check in this rail that is not a tautology: those blobs came
out of a different program on a different run, so agreement across
32,768 + 448 + 448 + 114,688 + 114,688 + 1,024 bytes means the rebuild
reproduced the checker parity, the stripe phase, the warm/cool split, the CHR
ordering, the interleave, the hyperbolic ramp constants, the rounding, the
s8.8 packing — and the 256-heading ORDER and 448-byte STRIDE that the ROM's
runtime pose address is computed from.

NOTHING ASSERTED THE GATE ITSELF UNTIL NOW. The rail's
own module named it — `test_map_blob_is_the_generator_and_the_generator_is_
gated` — and asserted only the first clause: gut `check_oracle`'s body and that
test stayed green. Worse, the gate was SOFT in the absence direction: remove
`vendor/art/split_h_2p/` and the generator emitted every blob, printed
"NO ORACLE … UNVERIFIED" and exited 0 (the `grad_tabs` shape, docs/37 — a gate
that passes when its evidence is missing), while the Makefile prerequisite is a
`$(wildcard …)` so the dependency evaporated with the files.

That mattered here more than anywhere: this gate exists to close the CI
coverage hole `AGENTS.md` names beside `test_split_v_fight.py`'s three
reference-gated skips — asset ground truth that never runs on a bare runner. A
soft absence direction silently restores the hole.

THE VENDOR DIRECTORY IS NEVER TOUCHED. Every absence/perturbation case points
the generator's `VENDOR` at a `tmp_path` instead, so these tests hold under any
`-n` and cannot corrupt the tree the way a move-it-aside test would (see
conftest's repo-tree lock for what that costs when two modules overlap).

Runs on a bare runner: the reference blobs are committed to this repo, and
nothing here builds a ROM or boots the emulator.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tools"))

import gen_split_h_2p_assets as gen  # noqa: E402

VENDOR = SUPERFORGE / "vendor" / "art" / "split_h_2p"


def _set256():
    """Memoised — the 256-heading set is 28,672 rounds and six cases want it."""
    if not _SET256:
        _SET256.extend(gen.pose_set(gen.POSES))
    return _SET256


_SET256: list = []

# (reference file, the generator call that must agree with it, its label)
BLOBS = (
    ("ref_checker_map.bin", lambda: gen.world_blob(), "world blob"),
    ("ref_poses1_ab.bin", lambda: gen.pose_blobs(0.0)[0], "pose AB"),
    ("ref_poses1_cd.bin", lambda: gen.pose_blobs(0.0)[1], "pose CD"),
    ("ref_poses256_ab.bin", lambda: _set256()[0], "pose256 AB"),
    ("ref_poses256_cd.bin", lambda: _set256()[1], "pose256 CD"),
    ("ref_move256.bin", lambda: gen.move_lut(gen.POSES), "move256"),
)


# =============================================================================
# 1. THE ORACLE IS PRESENT — the gate has something to check
# =============================================================================
def test_every_vendored_reference_exists_and_is_the_declared_size():
    """The seven artefacts the README documents, at the sizes it documents.

    Absence is the failure this module exists for, so it is asserted first and
    directly rather than inferred from a later comparison passing.
    """
    want = {"ref_checker_map.bin": 32768, "ref_poses1_ab.bin": 448,
            "ref_poses1_cd.bin": 448,
            "ref_poses256_ab.bin": 114688, "ref_poses256_cd.bin": 114688,
            "ref_move256.bin": 1024}
    for name, size in want.items():
        p = VENDOR / name
        assert p.is_file(), f"{p} is absent — the asset oracle is gone"
        assert p.stat().st_size == size, f"{name} is {p.stat().st_size} B, want {size}"
    inc = VENDOR / "ref_palette.inc"
    assert inc.is_file(), f"{inc} is absent — the palette oracle is gone"
    for name in gen.PAL_NAMES:
        assert name in inc.read_text(), f"{inc.name} has no {name} equate"


# =============================================================================
# 2. THE GENERATOR AGREES WITH IT — the claim the gate makes
# =============================================================================
@pytest.mark.parametrize("ref_name,produce,label", BLOBS,
                         ids=[b[0] for b in BLOBS])
def test_the_generator_reproduces_ref_byte_for_byte(ref_name, produce, label):
    """The rebuild, against a blob this repo did not produce."""
    ref = (VENDOR / ref_name).read_bytes()
    got = produce()
    assert got == ref, (
        f"{label} disagrees with {ref_name}: "
        f"{sum(a != b for a, b in zip(got, ref))} of {len(ref)} bytes")


def test_the_palette_equates_match_the_reference():
    """Parsed from the `.inc`, not assumed — PAL_FALLBACK is under test."""
    notes = []
    assert len(gen.palette(notes)) == 10
    assert notes == ["palette: byte-identical to ref_palette.inc (5 words)"]


# =============================================================================
# 3. THE GATE IS ARMED — it REFUSES, and this is the half that was missing
# =============================================================================
@pytest.mark.parametrize("ref_name,produce,label", BLOBS,
                         ids=[b[0] for b in BLOBS])
def test_a_perturbed_reference_is_refused(tmp_path, monkeypatch, ref_name,
                                          produce, label):
    """One flipped byte in the reference must stop the build.

    The whole vendor dir is copied into tmp_path and `VENDOR` is pointed at the
    copy, so the real oracle is never written to.
    """
    shutil.copytree(VENDOR, tmp_path / "art")
    ref = bytearray((tmp_path / "art" / ref_name).read_bytes())
    ref[len(ref) // 2] ^= 0xFF
    (tmp_path / "art" / ref_name).write_bytes(ref)
    monkeypatch.setattr(gen, "VENDOR", tmp_path / "art")
    # Matched on the stable half of the message: the refusal must NAME the
    # blob that disagreed. How the generator words the rest is its business.
    with pytest.raises(SystemExit, match=f"{label} disagrees with"):
        gen.check_oracle(label, produce(), ref_name, [])


def test_a_drifted_generator_is_refused(tmp_path, monkeypatch):
    """The other direction: the reference blob is right and the generator drifted.

    `SCALE_NEAR` 0.625 -> 0.6251 moves three bytes of the ramp — the smallest
    perturbation of a geometry constant that reaches the blob at all.
    """
    monkeypatch.setattr(gen, "SCALE_NEAR", 0.6251)
    ab, _ = gen.pose_blobs(0.0)
    with pytest.raises(SystemExit, match="pose AB disagrees with"):
        gen.check_oracle("pose AB", ab, "ref_poses1_ab.bin", [])


@pytest.mark.parametrize("ref_name,label", [(b[0], b[2]) for b in BLOBS],
                         ids=[b[0] for b in BLOBS])
def test_an_ABSENT_reference_is_refused(tmp_path, monkeypatch, ref_name, label):
    """a later review — the direction that used to print a note and exit 0."""
    monkeypatch.setattr(gen, "VENDOR", tmp_path / "gone")
    with pytest.raises(SystemExit, match="NO ORACLE"):
        gen.check_oracle(label, b"whatever", ref_name, [])


def test_an_absent_palette_oracle_is_refused(tmp_path, monkeypatch):
    """The palette took the same soft path — a fallback with a printed note."""
    monkeypatch.setattr(gen, "VENDOR", tmp_path / "gone")
    with pytest.raises(SystemExit, match="NO ORACLE"):
        gen.palette([])


def test_the_generator_EXITS_NONZERO_with_no_oracle(tmp_path, monkeypatch):
    """End to end, through `main`, because that is what the Makefile runs.

    A unit-level refusal is not the claim; the claim is that the BUILD stops.
    Asserted on the process exit status and on the output directory staying
    empty — the old behaviour wrote every blob before exiting 0.
    """
    out = tmp_path / "assets"
    monkeypatch.setattr(gen, "VENDOR", tmp_path / "gone")
    with pytest.raises(SystemExit) as e:
        gen.main([str(out)])
    assert e.value.code != 0, "an absent oracle did not stop the build"
    assert not list(out.glob("*.bin")), "UNVERIFIED blobs were written anyway"


def test_the_generator_exits_zero_and_writes_every_blob_normally(tmp_path):
    """The control. Without it every refusal above could be a broken generator.

    A subprocess, so the exit status is the real one the Makefile sees. The
    EXACT set is asserted, not a subset: a slice that stopped being emitted
    would otherwise show up only as a link error three steps later.
    """
    out = tmp_path / "assets"
    r = subprocess.run([sys.executable, "tools/gen_split_h_2p_assets.py", str(out)],
                       cwd=SUPERFORGE, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    want = ["sh2_map.bin", "sh2_move256.bin", "sh2_pal.bin",
            "sh2_pose1_ab.bin", "sh2_pose1_cd.bin",
            # the projector's tables and the character block
            "sh2_sp_sincos.bin", "sh2_sp_vk.bin", "sh2_sp_recip_lo.bin",
            "sh2_sp_recip_hi.bin", "sh2_sp_tier.bin", "sh2_sp_chr.bin",
            # the swarm's seeds and the AI's world model
            "sh2_ents.bin", "sh2_way.bin"]
    want += [f"sh2_pose256_{c}_s{k}.bin"
             for c in ("ab", "cd") for k in range(gen.SLICES)]
    assert sorted(p.name for p in out.glob("*.bin")) == sorted(want)
    assert "byte-identical to ref_checker_map.bin" in r.stdout


# =============================================================================
# 3b. THE SWARM GATE IS ARMED TOO
# =============================================================================
# `swarm_world` is the SUBSTITUTE for an oracle that does not exist: there is
# no vendored waypoint blob to check the swarm's world against, so it is gated
# by SIMULATION instead — ten properties over four laps of the complete
# 256-state camera cycle, in the driven AND the static regime, refusing at
# asset time.
#
# Every vendored-blob gate beside it has refusal tests; this one had NONE for a
# long time, and it is the gate carrying the most weight, because it is the
# only evidence the swarm's world exercises the properties the 18 sprite tests
# stand on. A gate
# nobody has tried to break is a gate nobody has checked is armed
# (AGENTS.md's anti-patterns, "trusting a green test you have not tried to
# break").
#
# Each case below perturbs the world in ONE way and names the check that must
# refuse it — five different checks of the ten, so a single disarmed comparison
# cannot pass the whole set.
def _swarm_inputs():
    """The three arguments `main` builds for `swarm_world`, built the same way.

    Cheap enough to do per test (~0.3 s for the whole simulation), so nothing is
    cached across cases and one case cannot perturb another.
    """
    ramp = gen.scale_ramp()
    rlo, rhi = gen.recip_luts(ramp)
    tabs = (gen.sincos_lut(), gen.vk_lut(ramp),
            [rlo[k] | (rhi[k] << 8) for k in range(gen.LINES)],
            gen.tier_ladder(ramp))
    mv = gen.move_lut(gen.POSES)
    return tabs, gen.camera_states(mv), mv


def _p_frozen(mp, tabs, oam):
    """The AI stops running: nothing moves when the cameras are parked."""
    mp.setattr(gen, "ai_tick", lambda *a, **k: None)
    return tabs, oam


def _p_far(mp, tabs, oam):
    """The seed rings are pushed outside the projector's depth window."""
    mp.setattr(gen, "SP_RING_R", 400)
    mp.setattr(gen, "SP_NEAR_R", 400)
    return tabs, oam


def _p_flat_tier(mp, tabs, oam):
    """The size ladder collapses onto one rung — `sh2_sp_tieroff` in Python."""
    return (tabs[0], tabs[1], tabs[2], bytes([2]) * len(tabs[3])), oam


def _p_one_radius(mp, tabs, oam):
    """Both waypoint loops collapse onto their orbit centre."""
    mp.setattr(gen, "SWM_WAY_R", (0, 0))
    return tabs, oam


def _p_no_slots(mp, tabs, oam):
    """`sh2_obj`'s OAM claim shrinks below the cast's peak."""
    return tabs, 1


SWARM_PERTURBATIONS = (
    ("ai_frozen", _p_frozen, "the STATIC visible count never changes"),
    ("rings_out_of_range", _p_far, "a band empties on the driven cycle"),
    ("flat_tier_ladder", _p_flat_tier, r"the cast reaches tiers \[2\], not all"),
    ("waypoints_on_the_centre", _p_one_radius, "followers CHANGED HEADING"),
    ("oam_claim_too_small", _p_no_slots, "exceeds the 1-slot OAM claim"),
)


@pytest.mark.parametrize("perturb,match",
                         [(p, m) for _n, p, m in SWARM_PERTURBATIONS],
                         ids=[n for n, _p, _m in SWARM_PERTURBATIONS])
def test_a_degenerate_swarm_world_is_refused(monkeypatch, perturb, match):
    """The refusal direction, five checks of the ten, one perturbation each."""
    tabs, states, mv = _swarm_inputs()
    tabs, oam = perturb(monkeypatch, tabs, 32)
    with pytest.raises(SystemExit) as e:
        gen.swarm_world(tabs, states, mv, oam, [])
    msg = str(e.value)
    assert "swarm coverage" in msg, f"refused, but not as a coverage gate: {msg}"
    assert re.search(match, msg), (
        f"the gate refused on the wrong check: wanted /{match}/, got {msg}")


def test_the_swarm_gate_ACCEPTS_the_shipped_world():
    """The control. Without it every refusal above could be a broken simulation.

    Also the one place the emitted note — which the design notes quote as the
    world's coverage statement — is asserted rather than printed: the blob
    lengths are the claims' own, and the ten properties are named in it.
    """
    tabs, states, mv = _swarm_inputs()
    notes = []
    ents, way = gen.swarm_world(tabs, states, mv, 32, notes)
    assert len(ents) == gen.SWM_ENTS_BYTES and len(way) == gen.SWM_WAY_BYTES
    assert len(notes) == 1
    note = notes[0]
    for want in (f"{gen.SWM_MAX} seeded, {gen.SWM_N} live", "tiers [0, 1, 2, 3, 4]",
                 f"all {gen.SWM_N - gen.SWM_PLAYERS} followers moved",
                 f"{gen.SWM_N - gen.SWM_PLAYERS} turned",
                 f"{gen.SWM_N - gen.SWM_PLAYERS} reached a waypoint"):
        assert want in note, f"the swarm note does not state {want!r}: {note}"


# =============================================================================
# 4. THE SLICING — the cut the ROM's address arithmetic depends on
# =============================================================================
def test_each_slice_is_the_matching_window_of_the_matched_blob(tmp_path):
    """Slice k, byte for byte, is `blob[k*28672 : (k+1)*28672]`.

    Cut from the blob the oracle already matched — so this asserts the CUT, and
    the oracle above asserts the bytes. Together they are what makes
    `ptr = slice_base + (h & 63)*448`, `bank = base + (h >> 6)` a fact about
    the shipped ROM rather than a claim in a comment.
    """
    out = tmp_path / "assets"
    subprocess.run([sys.executable, "tools/gen_split_h_2p_assets.py", str(out)],
                   cwd=SUPERFORGE, check=True, capture_output=True)
    for chan, ref in (("ab", "ref_poses256_ab.bin"),
                      ("cd", "ref_poses256_cd.bin")):
        blob = (VENDOR / ref).read_bytes()
        for k in range(gen.SLICES):
            got = (out / f"sh2_pose256_{chan}_s{k}.bin").read_bytes()
            lo = k * gen.SLICE_BYTES
            assert got == blob[lo:lo + gen.SLICE_BYTES], (
                f"slice {chan} s{k} is not bytes [{lo}, {lo + gen.SLICE_BYTES}) "
                f"of {ref}")


def test_pose_h_lands_where_the_rom_addresses_it(tmp_path):
    """For EVERY heading 0..255: the slice/offset the ROM computes holds pose h.

    The address arithmetic re-run in Python against the emitted slices, so a
    stride, a slice size or an ordering change is caught at the asset layer
    rather than as a smeared floor eight steps downstream.
    """
    out = tmp_path / "assets"
    subprocess.run([sys.executable, "tools/gen_split_h_2p_assets.py", str(out)],
                   cwd=SUPERFORGE, check=True, capture_output=True)
    ab, cd = _set256()
    slices = {(c, k): (out / f"sh2_pose256_{c}_s{k}.bin").read_bytes()
              for c in ("ab", "cd") for k in range(gen.SLICES)}
    for h in range(gen.POSES):
        want_ab, want_cd = gen.pose_blobs(2.0 * gen.math.pi * h / gen.POSES)
        assert want_ab == ab[h * gen.POSE_BYTES:(h + 1) * gen.POSE_BYTES]
        off = (h & 63) * gen.POSE_BYTES
        assert slices[("ab", h >> 6)][off:off + gen.POSE_BYTES] == want_ab, (
            f"heading {h} is not at slice {h >> 6} offset {off} of the AB set")
        assert slices[("cd", h >> 6)][off:off + gen.POSE_BYTES] == want_cd, (
            f"heading {h} is not at slice {h >> 6} offset {off} of the CD set")
        assert want_cd == cd[h * gen.POSE_BYTES:(h + 1) * gen.POSE_BYTES]


def test_the_move_lut_is_a_constant_speed_circle(tmp_path):
    """Every entry has magnitude 2.0 px/frame (8.8), and h=0 is world -y.

    The rail's motion tests measure DISPLACEMENT off the framebuffer; if the
    LUT's magnitude varied with heading, "the camera drives forward" would be
    a claim whose rate depended on where it was pointing. Asserted where the
    LUT is made, in the units the ROM consumes.
    """
    mv = gen.move_lut(gen.POSES)
    import struct
    for h in range(gen.POSES):
        dx, dy = struct.unpack("<hh", mv[h * 4:(h + 1) * 4])
        mag = (dx * dx + dy * dy) ** 0.5
        assert abs(mag - gen.MOVE_SCALE) < 1.0, (
            f"heading {h} has |v| = {mag:.2f}, not {gen.MOVE_SCALE}")
    assert struct.unpack("<hh", mv[0:4]) == (0, -int(gen.MOVE_SCALE))
    # A quarter turn is world +x: 256/4 = heading 64 -> (-sin, -cos)(pi/2).
    assert struct.unpack("<hh", mv[64 * 4:65 * 4]) == (-int(gen.MOVE_SCALE), 0)
