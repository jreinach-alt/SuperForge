"""The Mode 7 static-affine matrix table.

The claim this file has to hold up is not "the generator ran" but "the table is
bit-identical to the arithmetic the reference's `m7_dungeon` performs at runtime". So
the oracle here is the reference's ACTUAL path -- a 512-entry half-step sine table
indexed `angle*2`, cosine a quarter period along at `(angle*2 + 128) & $1FE`,
each coefficient then passed through `(v * scale) >> 8` with scale = $0100 --
reconstructed independently from its documented rule rather than from the
generator under test. Two implementations of the same claim; agreement means
something.
"""
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "tools" / "gen_m7_affine_lut.py"
HEADINGS = 256


@pytest.fixture(scope="module")
def lut(tmp_path_factory):
    out = tmp_path_factory.mktemp("m7aff")
    subprocess.run([sys.executable, str(GEN), str(out)], check=True)
    blob = (out / "m7_affine_lut.bin").read_bytes()
    assert len(blob) == 2048, len(blob)

    def s16(lo, hi):
        v = lo | (hi << 8)
        return v - 65536 if v >= 32768 else v

    return [
        tuple(s16(blob[a * 8 + i * 2], blob[a * 8 + i * 2 + 1]) for i in range(4))
        for a in range(HEADINGS)
    ]


# --- the independent oracle: the reference's runtime path, rebuilt from its rule ----

def _reference_sin_lut():
    """512 entries, `sin_lut[i] = round(sin(i*pi/256) * 256)` -- the rule stated
    at the head of the reference `mode7_sin_lut.inc`, which its shipped table
    was verified to satisfy at all 512 entries."""
    return [round(math.sin(i * math.pi / 256) * 256) for i in range(512)]


def _reference_matrix(a, sin_lut, scale=0x0100):
    """What `sf_boss_matrix scale, angle` computes, step for step:
    sincos() reads sin at `angle*2` and cos at `(angle*2 + 128) & $1FE`;
    smul16 then forms the s32 product and the code takes bytes 1-2 = >>8."""
    si = (a * 2) & 0x1FF
    ci = ((a * 2) + 128) & 0x1FE
    sina, cosa = sin_lut[si], sin_lut[ci]
    m7a = (cosa * scale) >> 8
    m7b = (sina * scale) >> 8
    return m7a, m7b, -m7b, m7a


def test_matches_ref_runtime_path_at_every_heading(lut):
    """The headline: bit-identical to the source rail's own arithmetic, for
    every input it can be given. Not 'close enough' -- equal."""
    sin_lut = _reference_sin_lut()
    bad = [(a, lut[a], _reference_matrix(a, sin_lut))
           for a in range(HEADINGS) if lut[a] != _reference_matrix(a, sin_lut)]
    assert not bad, f"{len(bad)} headings differ, first: {bad[:3]}"


def test_is_a_rotation_matrix(lut):
    """Uniform scale means D == A and C == -B. This is what makes the inverse
    the transpose, which is what the sprite projection relies on -- if it ever
    stops holding, the projection silently rotates sprites the wrong way."""
    for a, (m7a, m7b, m7c, m7d) in enumerate(lut):
        assert m7d == m7a, f"heading {a}: D != A"
        assert m7c == -m7b, f"heading {a}: C != -B"


def test_cardinal_headings_are_exact(lut):
    """Hand-derived, touching neither the generator nor the oracle above:
    at rest the matrix must be exactly identity, and a quarter turn must be
    exactly the 90-degree rotation. A scale or sign regression shows here."""
    assert lut[0] == (256, 0, 0, 256)
    assert lut[64] == (0, 256, -256, 0)
    assert lut[128] == (-256, 0, 0, -256)
    assert lut[192] == (0, -256, 256, 0)


def test_every_entry_fits_signed_16_bit(lut):
    for a, row in enumerate(lut):
        for v in row:
            assert -32768 <= v <= 32767, (a, v)
            assert -256 <= v <= 256, (a, v)


def test_deterministic(tmp_path):
    """Re-running must be byte-identical -- the build depends on it, and a
    recorded ROM md5 is only meaningful if every input is reproducible."""
    a, b = tmp_path / "a", tmp_path / "b"
    subprocess.run([sys.executable, str(GEN), str(a)], check=True)
    subprocess.run([sys.executable, str(GEN), str(b)], check=True)
    assert (a / "m7_affine_lut.bin").read_bytes() == (b / "m7_affine_lut.bin").read_bytes()
