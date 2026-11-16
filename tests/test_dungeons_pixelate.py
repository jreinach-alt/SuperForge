"""SuperForge Dungeons — the actor pixelate stage, on SYNTHETIC data frames.

runtime: ~6 s — pure numpy (import-dominated), no Blender, no ROM.

The stage is ported from sf-gt (tools/dungeons/art/pixelate_actor.py header).
Blender is not needed to pin its contract: a data frame is just three
channels (R sun, G material id, B open sky), so these tests paint one by hand
and assert each rule of docs/dungeons/13 §4 on the indexed output.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "dungeons", "art"))
import pixelate_actor as P  # noqa: E402

SS, MARGIN, BOX = 4, 4, (16, 16)
CANVAS = BOX[0] + 2 * MARGIN                      # sprite pixels per side


@pytest.fixture(scope="module")
def fam():
    return P.load_family("hero")


def blank():
    return np.zeros((CANVAS * SS, CANVAS * SS, 3), np.uint8)


def paint(raw, sx, sy, w, h, mat, sun=200, sky=128):
    """Fill sprite-pixel rect (sx, sy, w, h) — in canvas coords — with one material."""
    raw[sy * SS:(sy + h) * SS, sx * SS:(sx + w) * SS] = (sun, mat, sky)


def test_ramp_step_follows_brightness(fam):
    raw = blank()
    paint(raw, 6, 6, 4, 4, mat=2, sun=20, sky=0)      # dark cloak  -> step 1
    paint(raw, 14, 6, 4, 4, mat=2, sun=250, sky=255)  # sunlit cloak -> step 5
    img, model, _ = P.quantise(raw, SS, fam)
    assert img[7, 7] == 1 and img[7, 15] == 5


def test_small_feature_wins_by_vote(fam):
    # one sprite pixel: 6 of 16 samples are the eye, 10 are cloak. Unweighted,
    # cloak wins; the eye's vote of 1.8 (6 * 1.8 = 10.8 > 10) keeps it.
    raw = blank()
    paint(raw, 8, 8, 1, 1, mat=2)
    raw[8 * SS:8 * SS + 2, 8 * SS:8 * SS + 3] = (200, 8, 128)   # 6 eye samples
    img, _, _ = P.quantise(raw, SS, fam)
    assert img[8, 8] == 14


def test_outline_ring_and_shadow(fam):
    raw = blank()
    paint(raw, 9, 6, 4, 8, mat=2)                      # the body
    paint(raw, 8, 14, 6, 2, mat=P.MAT_SHADOW)          # shadow under it
    img, model, shadow = P.quantise(raw, SS, fam)
    out = P.finish(img, model, shadow, fam)
    assert out[5, 10] == fam.outline                   # above the head: ring
    assert out[15, 8] == fam.shadow                    # shadow pixel
    assert set(np.unique(out[model])) <= set(range(1, 6))


def test_only_role_indices_are_emitted(fam):
    raw = blank()
    for i, m in enumerate((2, 3, 4, 5, 6, 7, 8)):
        paint(raw, 5 + i, 8, 1, 4, mat=m, sun=40 * i + 10)
    out = P.pixelate(raw, SS, fam, MARGIN, BOX, "roles")
    allowed = {0, fam.outline} | set(range(1, 15))
    assert set(np.unique(out)) <= allowed


def test_despeckle_folds_a_lone_step(fam):
    img = np.full((5, 5), 3, np.uint8)
    img[2, 2] = 4
    assert P.despeckle(img, fam)[2, 2] == 3


def test_model_outside_the_box_is_an_error_not_a_crop(fam):
    raw = blank()
    paint(raw, 1, 8, 6, 4, mat=2)                      # spills left of the margin
    with pytest.raises(ValueError, match="outside the 16x16 box"):
        P.pixelate(raw, SS, fam, MARGIN, BOX, "spill")


def test_foot_row_and_shimmer(fam):
    raw = blank()
    paint(raw, 9, 6, 4, 10, mat=2)                     # rows 6..15 canvas -> 2..11 box
    a = P.pixelate(raw, SS, fam, MARGIN, BOX, "a")
    assert P.foot_row(a, fam.outline) == 11
    assert P.shimmer(a, a) == 0


def test_roles_table_is_validated(tmp_path):
    bad = tmp_path / "roles.toml"
    bad.write_text('[family.x]\noutline = 15\nshadow = 15\ncover = 0.5\n'
                   '[[family.x.role]]\nname = "c"\nmaterial = 2\nkind = "ramp"\n'
                   'lo = 1\nhi = 5\nthresholds = [0.5]\nvote = 1.0\n')
    with pytest.raises(ValueError, match="need 4 thresholds"):
        P.load_family("x", bad)
