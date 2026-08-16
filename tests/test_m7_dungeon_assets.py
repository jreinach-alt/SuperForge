"""m7_dungeon asset pipeline — checked against vendored reference blobs.

No emulator here: this is the BUILD-TIME half. Every artifact is compared to
bytes produced by `make_dungeon.py` /
`mode7_map_converter.py` / `make_{hero,enemy,win}.py` — a different program, on
a different run, vendored under `vendor/art/m7_dungeon/`.

That is what keeps this file out of the tautology CLAUDE.md rule 2 warns about.
`tools/gen_m7_dungeon_assets.py` is a self-contained re-implementation that
shares no code with those programs (it cannot: CI runs from a bare runner with
no sibling checkout), so agreement across 32,768 + 16,384 bytes is evidence
rather than an echo. A test that re-derived the expectation from the generator
would be checking the generator against itself.

The flag table is the one artifact with no counterpart on the reference side —
it is this repo's 64x-smaller replacement for the terrain array — so it is
checked two ways instead: proved equivalent to the vendored terrain at all
16,384 world cells, and its conflict guard is FALSIFIED by feeding it a
conflict and watching it fire.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
GEN = SUPERFORGE / "tools" / "gen_m7_dungeon_assets.py"
VENDOR = SUPERFORGE / "vendor" / "art" / "m7_dungeon"

sys.path.insert(0, str(SUPERFORGE / "tools"))
import gen_m7_dungeon_assets as G                              # noqa: E402

CELLS = 128 * 128


def run_gen(outdir: Path):
    """Run the generator as the build runs it, and return {name: bytes}.

    Through the CLI rather than by import, because the CLI is what the Makefile
    invokes and its oracle checks are a build GATE — if they ever stopped
    refusing, this call would still be the thing that noticed."""
    r = subprocess.run([sys.executable, str(GEN), str(outdir)],
                       capture_output=True, text=True)
    assert r.returncode == 0, \
        f"gen_m7_dungeon_assets failed:\n{r.stdout}\n{r.stderr}"
    return {p.name: p.read_bytes() for p in sorted(outdir.glob("m7dg_*.bin"))}


@pytest.fixture(scope="module")
def blobs(tmp_path_factory):
    return run_gen(tmp_path_factory.mktemp("m7dg"))


def inc(name, label):
    """A vendored ca65 `.inc` label's data, via the generator's dumb reader.

    The parser is shared; the BYTES are not, and the bytes are the oracle.
    (Contrast the palette check below, which re-parses the .inc here rather
    than through the generator, because there the parse is the claim.)"""
    b = G.inc_bytes(name, label)
    assert b is not None, f"vendored fixture {name} is missing"
    return b


# ---------------------------------------------------------------------------
# The two oracles
# ---------------------------------------------------------------------------

def test_map_blob_identical_to_ref(blobs):
    """The 32,768 B interleaved Mode 7 blob, byte for byte.

    This single comparison covers the whole floor pipeline at once: the maze
    predicate, the checker phasing, the seam diagonal, the goal region, the
    tile-dedup ORDER, the palette insertion order, the reserve_backdrop remap
    and the interleave. Any one of them off by a step moves bytes."""
    got = blobs["m7dg_map.bin"]
    ref = (VENDOR / "ref_dungeon_map.bin").read_bytes()
    assert len(got) == 32768
    assert got == ref, f"{sum(a != b for a, b in zip(got, ref))} bytes differ"


def test_terrain_intermediate_identical_to_ref():
    """The 16,384 B terrain array — generated, compared, NOT shipped.

    This is the check that isolates `is_wall()`. The map blob above would also
    fail if the predicate were wrong, but it would fail if the converter were
    wrong too; this one has no converter in it, so a red here says "the
    predicate" and a red there alone says "the converter"."""
    got = G.terrain()
    ref = (VENDOR / "ref_dungeon_terrain.bin").read_bytes()
    assert len(got) == 16384
    assert got == ref, f"{sum(a != b for a, b in zip(got, ref))} bytes differ"


def test_terrain_array_is_not_emitted(blobs):
    """...and it stays an intermediate — the per-CELL classification is never
    a shipped artefact, so there is no second answer to the wall question that
    someone could edit out of step with the first.

    `m7dg_tilemap.bin` arrived later, and it is NOT a counter-example: it is
    the same 16,384 tile ids the map blob already carries, written contiguously
    because `col_map` indexes `ty * W + tx` and cannot stride an interleaved
    one. Two copies of one array, byte-identical by an assert in the generator
    — see the test below — rather than two arrays that could disagree. The
    terrain array is the thing that could disagree, and it is still absent.
    """
    assert not any("terrain" in name for name in blobs), sorted(blobs)
    assert sorted(blobs) == [
        "m7dg_enemy_chr.bin", "m7dg_enemy_pal.bin", "m7dg_flags.bin",
        "m7dg_hero_chr.bin", "m7dg_hero_pal.bin", "m7dg_map.bin",
        "m7dg_pal.bin", "m7dg_tilemap.bin", "m7dg_win_chr.bin",
        "m7dg_win_pal.bin"]


def test_packed_tilemap_is_the_blob_s_own_even_bytes(blobs):
    """The packed tile-id map `col_map` reads IS the map that is drawn.

    The whole point of shipping a second copy rather than a second array: the
    ids that paint the wall and the ids that block you are one thing, so a
    re-theme cannot move the picture without moving the collision with it. If
    these ever differ, the rail renders one dungeon and is played in another —
    which presents as a physics bug for a long time before anyone suspects the
    asset pipeline.
    """
    packed = blobs["m7dg_tilemap.bin"]
    blob = blobs["m7dg_map.bin"]
    assert len(packed) == 16384
    assert packed == blob[0::2], (
        f"{sum(a != b for a, b in zip(packed, blob[0::2]))} tile ids differ "
        f"between the packed map and the interleaved blob's even bytes")


def test_the_flag_table_answers_for_every_packed_id(blobs):
    """flags[tilemap[cell]] == is_wall(cell) at all 16,384 world cells.

    The indirection's ONE hazard, checked against the geometric predicate
    rather than against the generator's own flag derivation: a tile id that is
    solid at one world cell and floor at another would make the flag table
    unable to answer, and a dedup that collapsed a wall tile and a floor tile
    is exactly how that arrives. The generator asserts this too — this is the
    independent statement of it, from the SHIPPED bytes.
    """
    packed, flags = blobs["m7dg_tilemap.bin"], blobs["m7dg_flags.bin"]
    assert len(flags) == 256, "one entry per id a one-byte map can hold"
    bad = [(c % 128, c // 128) for c, tid in enumerate(packed)
           if bool(flags[tid]) != G.is_wall(c % 128, c // 128)]
    assert not bad, (
        f"{len(bad)} world cells where the shipped flag table disagrees with "
        f"is_wall, first at {bad[0]}")


def test_palette_identical_to_ref(blobs):
    """The 9 CGRAM words, against the vendored `dungeon_palette.inc`."""
    got = blobs["m7dg_pal.bin"]
    ref = inc("ref_dungeon_palette.inc", "dungeon_pal")
    assert len(got) == 18, "9 colours x 2 bytes"
    assert got == ref


@pytest.mark.parametrize("stem,incfile,label,size", [
    ("hero", "ref_hero.inc", "hero_chr", 576),
    ("enemy", "ref_enemy.inc", "enemy_chr", 576),
])
def test_sprite_chr_identical_to_ref(blobs, stem, incfile, label, size):
    got = blobs[f"m7dg_{stem}_chr.bin"]
    assert len(got) == size, "18 tiles x 32 B, the OBJ grid"
    assert got == inc(incfile, label)


@pytest.mark.parametrize("stem,incfile,label", [
    ("hero", "ref_hero.inc", "hero_pal"),
    ("enemy", "ref_enemy.inc", "enemy_pal"),
    ("win", "ref_win.inc", "win_pal"),
])
def test_sprite_palette_identical_to_ref(blobs, stem, incfile, label):
    got = blobs[f"m7dg_{stem}_pal.bin"]
    assert len(got) == 32, "16 words, a full 4bpp OBJ palette"
    assert got == inc(incfile, label)


def test_win_card_content_identical_and_padding_zero(blobs):
    """The win card's shape mismatch, checked on content.

    The reference emits two tight 64-byte row blobs; this repo emits the uniform
    18-tile grid. So the quad {0,1,16,17} is compared against top‖bot AND the
    14 tiles between them are required to be zero. Checking only the quad
    would pass a blob with garbage in the padding, which the PPU never reads
    for THIS sprite but a neighbouring OBJ tile index certainly would."""
    got = blobs["m7dg_win_chr.bin"]
    assert len(got) == 576
    quad = got[:64] + got[16 * 32:18 * 32]
    assert quad == inc("ref_win.inc", "win_chr_top") \
        + inc("ref_win.inc", "win_chr_bot")
    assert got[2 * 32:16 * 32] == bytes(14 * 32), "padding tiles 2..15"


def test_obj_grid_places_the_lower_row_at_plus_16(blobs):
    """The PPU reads a 16x16 sprite as {N, N+1, N+16, N+17} — the lower row is
    +16 tile numbers away, not +2, because OBJ CHR is a 16-tile-wide sheet.
    A blob laid out consecutively assembles and links and renders its bottom
    half from whatever tiles happen to sit at +2."""
    for stem in ("hero", "enemy", "win"):
        chr_blob = blobs[f"m7dg_{stem}_chr.bin"]
        assert chr_blob[2 * 32:16 * 32] == bytes(14 * 32), \
            f"{stem}: tiles 2..15 must be padding, not the lower sprite row"
        assert chr_blob[16 * 32:18 * 32] != bytes(64), \
            f"{stem}: tiles 16,17 are the lower row and must hold pixels"


# ---------------------------------------------------------------------------
# The flag table, its equivalence, and its guard
# ---------------------------------------------------------------------------

def test_flag_table_equivalent_at_every_world_cell(blobs):
    """flags[tilemap[cell]] == terrain[cell], all 16,384 of them.

    This is the whole justification for shipping 256 bytes instead of 16,384:
    not "it should be the same function", but the same answer at every
    coordinate a query can reach."""
    flags = blobs["m7dg_flags.bin"]
    assert len(flags) == 256
    tilemap = blobs["m7dg_map.bin"][0::2]          # even bytes of the blob
    terr = (VENDOR / "ref_dungeon_terrain.bin").read_bytes()
    assert len(tilemap) == len(terr) == CELLS

    bad = [c for c in range(CELLS) if flags[tilemap[c]] != terr[c]]
    assert not bad, (
        f"{len(bad)} cells disagree, first at world tile "
        f"({bad[0] % 128},{bad[0] // 128})")


def test_flag_table_matches_the_measured_partition(blobs):
    """The measured shape the spec records: 8 ids, solid [0,1,2].

    Pinned deliberately. If a future art change repartitions these, the map
    blob test will still pass (the art is allowed to change) and this one will
    fail — which is the prompt to re-read the guard's reasoning rather than to
    edit the number."""
    flags = blobs["m7dg_flags.bin"]
    tilemap = blobs["m7dg_map.bin"][0::2]
    used = sorted(set(tilemap))
    assert used == [0, 1, 2, 3, 4, 5, 6, 7]
    assert [t for t in used if flags[t]] == [0, 1, 2]
    assert [t for t in used if not flags[t]] == [3, 4, 5, 6, 7]
    assert all(flags[t] == 0 for t in range(256) if t not in used), \
        "unused tile ids default to floor"


def test_conflict_guard_fires_on_a_conflicting_map():
    """FALSIFY THE GUARD. A guard nobody has watched fail is not a guard.

    Synthesised the way the real hazard would arrive: a re-theme whose dedup
    collapses a wall tile and a floor tile into ONE art tile, leaving one flag
    to answer for both. Here that is forged by pointing a solid world cell at
    a floor cell's tile id."""
    terr = G.terrain()
    tilemap = bytearray(G.build_map()[1])

    floor_cell = next(c for c in range(CELLS) if terr[c] == 0)
    solid_cell = next(c for c in range(CELLS) if terr[c] == 1)
    victim = tilemap[floor_cell]
    tilemap[solid_cell] = victim

    with pytest.raises(G.TileFlagConflict) as e:
        G.flag_table(bytes(tilemap), terr)

    msg = str(e.value)
    assert f"tile id {victim}" in msg, "the guard must name the offending id"
    assert f"({floor_cell % 128},{floor_cell // 128})" in msg, \
        "the guard must name a floor world cell"
    assert f"({solid_cell % 128},{solid_cell // 128})" in msg, \
        "the guard must name a solid world cell"
    assert "16,384" in msg or "16384" in msg, \
        "the guard must name the way out (ship the full terrain array)"


def test_conflict_guard_does_not_fire_on_the_real_map():
    """The control arm. Without it the falsification above is satisfied by a
    guard that refuses everything, which is not a guard either."""
    tilemap = G.build_map()[1]
    flags = G.flag_table(tilemap, G.terrain())
    assert any(flags), "a table of all zeroes would pass every check above"


def test_equivalence_assert_catches_a_corrupted_table():
    """The second half of the same discipline: `assert_flags_equivalent` is
    load-bearing, so watch IT fail too."""
    tilemap = G.build_map()[1]
    terr = G.terrain()
    flags = bytearray(G.flag_table(tilemap, terr))
    flags[0] ^= 1                                  # tile 0 is solid; call it floor
    with pytest.raises(AssertionError, match="world tile"):
        G.assert_flags_equivalent(bytes(flags), tilemap, terr)


# ---------------------------------------------------------------------------
# The backdrop reservation
# ---------------------------------------------------------------------------

def test_cgram_index_0_is_floor_a(blobs):
    """CGRAM word 0 is the Mode 7 BACKDROP — what the PPU shows wherever the
    plane does not cover the screen. It must be the dark flagstone, or the
    floor shows through as brick at the plane edges.

    The expected word is computed here from the RGB literal, not taken from the
    generator's converter, so this checks the conversion as well as the slot."""
    r, g, b = (32, 40, 64)                         # FLOOR_A, re-declared
    want = ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)
    pal = blobs["m7dg_pal.bin"]
    assert int.from_bytes(pal[0:2], "little") == want == 0x20A4


def test_backdrop_reservation_actually_moved_something(blobs):
    """...and the check above is not vacuous.

    Scanning starts at world tile (0,0), which is wall mortar — so index 0 is
    NOT naturally FLOOR_A and `reserve_backdrop` has real work to do. This
    asserts it did it and did it losslessly: the evicted colour is appended at
    the tail, so no pixel that referenced it changed appearance."""
    pal = blobs["m7dg_pal.bin"]
    words = [int.from_bytes(pal[i:i + 2], "little") for i in range(0, len(pal), 2)]

    r, g, b = (104, 64, 44)                        # WALL_MO, the tile at (0,0)
    evicted = ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)
    assert evicted == 0x150D
    assert words[-1] == evicted, "the evicted colour must survive at the tail"
    assert words[0] != evicted, "index 0 must no longer be the wall mortar"
    assert words.count(words[0]) == 2, \
        "FLOOR_A appears twice: at its natural index and at the backdrop slot"


# ---------------------------------------------------------------------------
# Determinism, and the isolation the CI runner depends on
# ---------------------------------------------------------------------------

def test_generation_is_deterministic(tmp_path):
    """Two runs, byte-identical. The blobs are committed to nothing and rebuilt
    on every CI run, so any nondeterminism here shows up as a phantom diff in
    a rail's ROM md5 rather than as a failure with a name."""
    a = run_gen(tmp_path / "a")
    b = run_gen(tmp_path / "b")
    assert sorted(a) == sorted(b)
    for name in a:
        assert a[name] == b[name], f"{name} differs between two runs"


def test_generator_is_self_contained():
    """No reference-tree import, no path that reaches outside this repo.

    CI runs from a bare runner and this generator is on the build path, so its
    isolation is a property the build depends on rather than a nicety. Stated
    as a test because the failure mode is invisible on a dev box where the
    a reference tree IS on disk — it would pass locally and red only in CI.

    Checked over the AST, not the text, so the distinction CLAUDE.md draws
    survives: a `../` in a build file is a bug, a `../` in PROSE is a stale
    citation. This generator's docstrings may name a file and the path it has
    inside another tree, which is how a citation is supposed to read; what must
    not exist is an import or a string the code acts on."""
    import ast

    tree = ast.parse(GEN.read_text())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "argparse", "math", "struct", "sys",
                        "pathlib", "PIL"}, \
        f"the generator imports {sorted(imported)} — nothing may come from outside this repo"

    # Docstrings are prose; every OTHER string literal is something the code
    # acts on, and none of them may name a path outside this repo.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d is not None:
                docstrings.add(d)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value not in docstrings:
            # `"../"` and not `".."` — the MAZE rows are strings full of dots
            # and they are data, not paths. The thing being refused is a path
            # that climbs out of the repo, which is what CLAUDE.md names.
            for banned in ("SuperForge", "../", "toolchain"):
                assert banned not in node.value, (
                    f"line {node.lineno}: the string {node.value!r} names "
                    f"{banned!r} — the generator must not reach outside SuperForge")


def test_generator_refuses_to_emit_a_blob_that_disagrees(tmp_path):
    """The generator's own oracle check is a BUILD GATE, so falsify it.

    A stale or wrong reference must stop the build, not be silently
    overwritten by whatever the generator happens to produce today."""
    fake_vendor = tmp_path / "vendor" / "art" / "m7_dungeon"
    fake_vendor.mkdir(parents=True)
    for p in VENDOR.iterdir():
        if p.is_file():
            (fake_vendor / p.name).write_bytes(p.read_bytes())
    ref = fake_vendor / "ref_dungeon_map.bin"
    corrupt = bytearray(ref.read_bytes())
    corrupt[1234] ^= 0xFF
    ref.write_bytes(bytes(corrupt))

    shim = tmp_path / "gen_shim.py"
    shim.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(GEN.parent)!r})\n"
        "import gen_m7_dungeon_assets as G\n"
        f"G.VENDOR = pathlib.Path({str(fake_vendor)!r})\n"
        "sys.exit(G.main(sys.argv[1:]))\n")
    r = subprocess.run([sys.executable, str(shim), str(tmp_path / "out")],
                       capture_output=True, text=True)
    assert r.returncode != 0, "a disagreeing reference must stop the build"
    # Matched on the stable half of the refusal: it must NAME the disagreement.
    assert "disagrees with" in (r.stdout + r.stderr)
    assert not (tmp_path / "out" / "m7dg_map.bin").exists(), \
        "nothing may be written once the oracle has failed"
