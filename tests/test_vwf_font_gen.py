"""VWF font pipeline — the two artifacts the compositor reads, verified against
the SOURCE face rather than against the generator's own output.

Independence matters here: a test that re-read `vwf_widths.bin` and checked it
against what `gen_vwf_font.py` computed would be a tautology (CLAUDE.md rule 2 /
AGENTS.md test discipline). So every expectation below is re-derived in this file
by parsing `vendor/fonts/unscii-8.hex` with its own extent code, and the two
face-anchored cases are pixel measurements of the face itself.

Scope: this file covers the BUILD-TIME half only. The rendered half — do these
advances actually place ink at those pixel columns in VRAM — is the renderer's
test surface and reads VRAM CHR bytes on hardware.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
FACE = SUPERFORGE / "vendor" / "fonts" / "unscii-8.hex"
GEN = SUPERFORGE / "tools" / "gen_vwf_font.py"
LO, HI = 0x20, 0x7F
N = HI - LO + 1
ROWS = 8


def source_glyphs() -> dict[int, list[int]]:
    """Parse the face independently of the generator."""
    out = {}
    for ln in FACE.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        code, _, data = ln.partition(":")
        out[int(code, 16)] = [int(data[i:i + 2], 16) for i in range(0, len(data), 2)]
    return out


def source_extent(rows: list[int]):
    mask = 0
    for r in rows:
        mask |= r
    if mask == 0:
        return None
    cols = [c for c in range(8) if mask & (0x80 >> c)]
    return cols[0], cols[-1]


def gen(outdir: Path, letterspacing: int = 1):
    r = subprocess.run([sys.executable, str(GEN), str(FACE), str(outdir),
                        "--letterspacing", str(letterspacing)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"gen_vwf_font failed:\n{r.stdout}\n{r.stderr}"
    return ((outdir / "vwf_glyphs.bin").read_bytes(),
            (outdir / "vwf_widths.bin").read_bytes())


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    return gen(tmp_path_factory.mktemp("vwf1"))


def test_artifact_sizes_match_the_claim_sizes(artifacts):
    """768 B + 96 B are the numbers the rom claims declare."""
    masks, widths = artifacts
    assert len(masks) == N * ROWS == 768
    assert len(widths) == N == 96


def test_every_glyph_is_left_aligned(artifacts):
    """The bearing-stripping pass: column 0 of every non-blank glyph is inked.

    This is the property that makes a pen position mean "the next glyph's ink
    starts here". Without it the renderer inherits the face's variable bearing.
    """
    masks, _ = artifacts
    src = source_glyphs()
    for i, cp in enumerate(range(LO, HI + 1)):
        rows = masks[i * ROWS:(i + 1) * ROWS]
        if source_extent(src.get(cp, [0] * ROWS)) is None:
            assert not any(rows), f"${cp:04X} ({chr(cp)!r}) blank in source but inked after strip"
            continue
        assert any(r & 0x80 for r in rows), (
            f"${cp:04X} ({chr(cp)!r}) not left-aligned: no row has column 0 inked "
            f"— rows {[f'{r:08b}' for r in rows]}")


def test_stripping_preserves_every_ink_pixel(artifacts):
    """Shifting left must not push ink off the edge — same popcount, row for row."""
    masks, _ = artifacts
    src = source_glyphs()
    for i, cp in enumerate(range(LO, HI + 1)):
        got = masks[i * ROWS:(i + 1) * ROWS]
        want_rows = src.get(cp, [0] * ROWS)
        for r, (g, w) in enumerate(zip(got, want_rows)):
            assert bin(g).count("1") == bin(w).count("1"), (
                f"${cp:04X} ({chr(cp)!r}) row {r}: {w:08b} -> {g:08b} lost or "
                f"gained ink")


def test_advances_equal_independently_measured_ink_plus_letterspacing(artifacts):
    """The width table, recomputed over the face by this file's own extent code."""
    _, widths = artifacts
    src = source_glyphs()
    for i, cp in enumerate(range(LO, HI + 1)):
        e = source_extent(src.get(cp, [0] * ROWS))
        want = (2 if e is None else e[1] - e[0] + 1) + 1      # SPACE_INK / ink, +1 px
        assert widths[i] == want, (
            f"${cp:04X} ({chr(cp)!r}): advance {widths[i]}, independently "
            f"measured ink+1 = {want}")


def test_no_advance_exceeds_a_tile_plus_one(artifacts):
    """The dirty-span bound: ink <= 8 px is what makes one glyph dirty <= 2 tiles.

    floor((7 + ink - 1) / 8) + 1 == 2 for ink <= 8. An ink of 9 would make it 3
    and silently break the declared vblank byte figure.
    """
    _, widths = artifacts
    assert max(widths) <= 9, f"widest advance {max(widths)} — ink exceeds 8 px"
    assert min(widths) >= 1


def test_face_anchored_extremes(artifacts):
    """Pixel measurements of unscii-8 itself — the end-to-end anchor.

    Face-anchored on purpose: these are the strings the renderer's
    proportional-advance test uses, and they are the pair that a broken
    (fixed-width) renderer cannot reproduce. Re-measure on a face swap.
    """
    _, widths = artifacts
    adv = {chr(cp): widths[cp - LO] for cp in range(LO, HI + 1)}
    assert adv["i"] == 6 and adv["m"] == 8, (adv["i"], adv["m"])
    assert adv["."] == 3 and adv["X"] == 9, (adv["."], adv["X"])
    assert sum(adv[c] for c in "iiii") == 24
    assert sum(adv[c] for c in "mmmm") == 32     # 8 px = one whole tile apart


def test_letterspacing_shifts_widths_and_leaves_masks_untouched(tmp_path):
    """The G3 knob: spacing is a generator argument, not a renderer constant."""
    m1, w1 = gen(tmp_path / "ls1", letterspacing=1)
    m0, w0 = gen(tmp_path / "ls0", letterspacing=0)
    assert m1 == m0, "letterspacing must not change glyph masks"
    assert all(a - b == 1 for a, b in zip(w1, w0)), "spacing delta not uniform"


def test_output_is_deterministic(tmp_path):
    """Same input, byte-identical output — the .incbin + .assert contract."""
    assert gen(tmp_path / "a") == gen(tmp_path / "b")
