"""platformer_stream — the level generator, against ground truth this repo did
not produce.

`tools/gen_platformer_stream_assets.py` derives its blobs independently — the
same `--tall --seasons` level pipeline written out here, because a reference
tree is read-only and never a build dependency, so the code travels rather
than the import. Correctness is then a byte comparison, and the only
comparison worth making is against something this build did not author.

TWO ORACLES, and only one of them is a tautology risk:

  * THE COMMITTED REFERENCE FIXTURES (`tests/fixtures/platformer_stream/*.bin`)
    are the files a second implementation's ROM `.incbin`s, and therefore the
    source of its published gallery render. A byte match says our level IS
    that level.
    That is the asset-import rule satisfied properly: an auditor's
    Python re-rendering of the same source data would agree with a buggy
    converter by sharing its bugs, and these bytes were produced by a different
    program on a different run.
  * DETERMINISM is checked separately and is NOT reference-gated, because it is a
    property of our generator alone: two runs into different directories must
    produce identical bytes. It catches dict-ordering and set-iteration drift
    that a single run cannot see, and it is the half of the coverage that
    survives on a bare runner.

THE REFERENCE GATE IS A KNOWN COVERAGE HOLE, stated rather than hidden: the
byte-identity cases skip on every CI runner and inside `make bare-check`, for
the same reason `test_split_v_fight.py`'s three do — a reference tree must not
become a build dependency. AGENTS.md's test-discipline section names this and names
the fix (vendor the oracle with provenance). It is not taken here: these are
64 KB of level, and the generator's whole point is that they are regenerable.

NO EMULATOR, NO WALL CLOCK. Every case here is bytes on disk.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ASSETS = BUILD / "assets"
GEN = SUPERFORGE / "tools" / "gen_platformer_stream_assets.py"

# An OPTIONAL external reference tree, named by `SF_REFERENCE_TREE`. Absent
# on every CI runner and inside bare-check, which is the property those runs
# exist to prove.
# Unset on an ordinary runner, which is why the cases below SKIP rather
# than fail: they are ground-truth checks against a second, independent
# implementation, and there is nothing to check against when none is on
# disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE = _REFERENCE_TREE
FIXTURES = REFERENCE / "tests" / "fixtures" / "platformer_stream"

# our blob -> the reference's committed fixture, and the claim size each must be.
PAIRS = [
    ("pfs_flat.bin", "level_flat.bin", 32768),
    ("pfs_flat_row.bin", "level_flat_row.bin", 32768),
    ("pfs_col.bin", "level_collision.bin", 16384),
]

_reference_gate = pytest.mark.skipif(
    not FIXTURES.exists(),
    reason=f"reference fixtures absent ({FIXTURES}) — read-only, never a "
           f"build dependency; these cases are the ground truth they supply")


def _ours(name):
    p = ASSETS / name
    if not p.exists():
        pytest.fail(f"{p} missing — run `make pfs-assets` first")
    return p.read_bytes()


@pytest.mark.parametrize("ours,theirs,size", PAIRS)
@_reference_gate
def test_level_blob_is_byte_identical_to_ref(ours, theirs, size):
    """Our level IS the reference level, byte for byte.

    Reads the generator's OUTPUT FILE against a fixture produced by a different
    program. A mismatch means this build drifted; a length mismatch alone would
    mean the world's geometry moved, so both are asserted and the byte compare
    reports the first differing offset rather than a bare `!=`.
    """
    mine, reference = _ours(ours), (FIXTURES / theirs).read_bytes()
    assert len(mine) == size, f"{ours} is {len(mine)} B, claim says {size}"
    assert len(reference) == size, f"{theirs} is {len(reference)} B, expected {size}"
    if mine != reference:
        off = next(i for i in range(size) if mine[i] != reference[i])
        diffs = sum(1 for i in range(size) if mine[i] != reference[i])
        pytest.fail(
            f"{ours} differs from the reference {theirs}: {diffs} byte(s), first at "
            f"offset {off} (ours {mine[off]:#04x}, reference {reference[off]:#04x})")


@_reference_gate
def test_vendored_level_chr_is_byte_identical_to_ref():
    """The vendored CHR is the reference CHR, unaltered.

    It is COPIED rather than generated — quantized from a Four Seasons tileset
    image neither generator holds — so the only thing to assert is that the
    copy is faithful and that the staging step did not truncate or pad it. The
    staged `pfs_chr.bin` under build/assets is what the ROM `.incbin`s, so it
    is what is read here, not the vendored file it came from.
    """
    assert _ours("pfs_chr.bin") == (FIXTURES / "level_chr.bin").read_bytes()


def test_generator_is_deterministic(tmp_path):
    """Two runs, different directories, identical bytes — every emitted file.

    Not reference-gated: this is a property of OUR generator, and it is the half
    of this module's coverage that survives on a bare runner. A dict or set
    iteration order leaking into the level layout would show up here and
    nowhere else in a single-run build.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        subprocess.run([sys.executable, str(GEN), str(d)], check=True)
    names = sorted(p.name for p in a.iterdir())
    assert names, "the generator emitted nothing"
    for n in names:
        assert (a / n).read_bytes() == (b / n).read_bytes(), \
            f"{n} differs between two runs of the same generator"


def test_staged_blob_sizes_match_their_rom_claims():
    """Every staged file is exactly the size its `pfs_rom` claim reserves.

    The allocator reserves the claim's `bytes`; the `.incbin` fills whatever
    the file holds. A short file leaves the tail of a reserved window as
    whatever the linker's fill left there and a long one overruns into the
    next claim's asserted address — the second stops the build, the FIRST does
    not, so it is asserted here.
    """
    expect = {"pfs_flat.bin": 32768, "pfs_flat_row.bin": 32768,
              "pfs_col.bin": 16384, "pfs_flags.bin": 256, "pfs_grad.bin": 672,
              "pfs_chr.bin": 800, "pfs_pal.bin": 32,
              "pfs_hero_chr.bin": 1024, "pfs_hero_pal.bin": 32}
    for name, size in expect.items():
        assert len(_ours(name)) == size, f"{name} is not {size} B"
