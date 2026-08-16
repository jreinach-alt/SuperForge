"""col_map — world-space tile collision, on hardware.

col_map has no rendered output: its result is a value. CLAUDE.md rule 2 does
not weaken here, it re-points — **the feature's declared outputs ARE the output
region**, read from the emulator. What it forbids is asserting the
returned flag against a table the test computed the way the feature does.

col_map declares TWO outputs (col_map.asm:42): "A8 = the flag byte, and CM_FLAG
holds it". The two modules cover one each, deliberately:

  THIS module reads the returned **A**. `query_batch` steps a frame and reads
     `US_ACC` (:130), which is where the probe's arm-3 parks the accumulator
     the moment `col_map_at` returns (probe_colmap.asm:110-113). Nothing here
     reads CM_FLAG.

  tests/test_col_map_scene.py reads **CM_FLAG** (`ES_CM_HOT+4`) out of WRAM,
     under the live scene.

Neither is a proxy — a proxy would be some other variable that ought to move
when the flag does. These are the two things the feature says it produces.
(This paragraph replaces a claim that this module read the DP result byte; it
does not, and in the one file whose design is about honest test surfaces the
surface has to be described correctly.)

**The T1/T2 split is the whole design of this file, and it is load-bearing:**

  T1 tests the ADDRESSING — bank tiling, row offset, tile index — against a
     Python oracle built from `gen_m7_assets.world_map()`. That shares the
     map's *definition* with the feature and never its *lookup*: Python list
     indexing versus 65816 cross-bank arithmetic. It cannot catch a wrong flag
     VALUE, because the flag table is derived from the same generator.

  T2 tests the SEMANTICS against coordinates hand-derived from the octagon's
     band arithmetic — OCT_IN, OCT_OUT, CURB_T — touching neither
     `world_map()` nor `col_flags()`. It cannot catch a wrong ADDRESS, because
     it only visits ten of them.

Neither is sufficient alone. Together they have no shared path with the
feature. **If a T2 coordinate ever disagrees, do NOT re-source the expectation
from the generator** — that silently collapses T2 into T1 and the file stops
testing semantics at all. Either the arithmetic below is wrong (fix it, and
show the work) or the feature is wrong.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam

# The flag bits, DECLARED in engine/features/col_map_rom/feature.toml.
FLAG_DRIVABLE = 1 << 0
FLAG_TRACK = 1 << 1


@pytest.fixture(scope="module")
def probe():
    """The isolated kernel: probe_colmap.sfc, which .includes the SHIPPED
    col_map.asm rather than a copy of it.

    T1-T3 drive this rather than microzero, and the reason is a measured one.
    The first cut of these tests probed coordinates by writing microzero's
    ES_M7ORG — but that word is also consumed by rl_lap (sector/checkpoint/lap
    detection) and stream_tick (the leading-edge ring). Teleporting it 512
    times drove the lap machine through spurious sector transitions and walked
    the scene machine clean out of `race` mid-test; 60/512 coordinates came
    back stale because the race tick had stopped running. The lookup was
    correct the whole time. Probing shared game state is not isolation, and
    the isolated ROM is the honest place for a coordinate sweep.

    Loaded with the uninit detector armed from power-on, so T9 (below) can see
    every read this module's whole sweep performs. It used plain `load_rom`,
    which inits the debugger AFTER the run and leaves the per-address history
    incomplete (vendor/mesen_runner.py:108-111) — which is why the probe shipped
    reading two never-written bytes without the suite noticing.
    """
    r = subprocess.run(["make", "probe-colmap"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make probe-colmap failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads(
        (SUPERFORGE / "build" / "colmap_map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p["start"] for p in
            jmap["scenes"]["probe"]["placements"] + jmap["globals"]}
    world = (SUPERFORGE / "build" / "assets" / "world_map.bin").read_bytes()
    gen = D.load_tool("gen_m7_assets")
    runner = MesenRunner()
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "probe_colmap.sfc"), frames=60)
    runner.debug_break()
    yield runner, syms, world, gen
    runner.stop()


# --- driving the feature directly -------------------------------------------

def query_batch(probe, coords):
    """Ask the isolated kernel about each coordinate; return (px, py, flag).

    cmd 3 writes the coordinate into CM_PX/CM_PY and runs the SHIPPED
    col_map_at, leaving the flag in `acc`. Nothing else in the ROM touches
    those bytes, so a sweep cannot perturb what it is measuring.
    """
    runner, syms, _, _ = probe
    out = []
    for px, py in coords:
        s0 = runner.read_u16(WR, syms["US_SEQ"])
        runner.write_bytes(WR, syms["US_PARAM"],
                           int(px & 0xFFFF).to_bytes(2, "little"))
        runner.write_bytes(WR, syms["US_PARAM2"],
                           int(py & 0xFFFF).to_bytes(2, "little"))
        runner.write_bytes(WR, syms["US_CMD"], bytes([3]))
        # frame_step, not a poll loop: reads do not advance emulation, so a
        # tight host-side poll spins through 2000 iterations in microseconds
        # while the machine has moved nowhere. One frame is ~29k CPU cycles
        # against the arm's ~200 — and it is deterministic, which a sleep is
        # not (AGENTS.md: frame-step for measurement, wall-clock for
        # interactive only).
        runner.frame_step(1)
        assert runner.read_u16(WR, syms["US_SEQ"]) != s0, (
            f"the probe did not complete a command for ({px},{py})")
        out.append((px, py, runner.read_u16(WR, syms["US_ACC"]) & 0xFF))
    return out


# =============================================================================
# T1 — ADDRESSING. Oracle: the map's definition, never its lookup.
# =============================================================================

def test_t1_col_map_matches_the_world_blob_across_every_chunk_bank(probe):
    """Every chunk bank, both axes, 512 scattered coordinates.

    The oracle indexes `world_map()` in Python; the feature does bank tiling
    and 16-bit offset arithmetic in 65816. Shared: the map's definition.
    NOT shared: the lookup, which is what col_map implements.

    The stride is coprime with 4096 on both axes, so the walk visits a fresh
    row and a fresh chunk bank essentially every step — a walk that stayed in
    one 32 KB window would test one eighth of the addressing.
    """
    runner, syms, world, gen = probe
    W = gen.WORLD_T
    flags = D.load_tool("gen_col_flags").col_flags()

    coords, px, py = [], 0, 0
    for _ in range(512):
        coords.append((px, py))
        px = (px + 2053) & 4095
        py = (py + 761) & 4095

    banks_hit = set()
    bad = []
    for gx, gy, got in query_batch(probe, coords):
        tx, ty = (gx >> 3) & 511, (gy >> 3) & 511
        banks_hit.add(ty >> 6)
        want = flags[world[ty * W + tx]]
        if got != want:
            bad.append((gx, gy, tx, ty, ty >> 6, got, want))

    assert banks_hit == set(range(8)), (
        f"the walk only reached chunk banks {sorted(banks_hit)} — it must span "
        f"all 8 or it is not testing the bank tiling")
    assert not bad, (
        f"{len(bad)}/512 coordinates disagree with the world blob; first 5:\n" +
        "\n".join(f"  px=({gx},{gy}) tile=({tx},{ty}) chunk={c} "
                  f"got={g} want={w}" for gx, gy, tx, ty, c, g, w in bad[:5]))


# =============================================================================
# T2 — SEMANTICS. Oracle: hand-derived octagon arithmetic. Touches neither
# world_map() nor col_flags(). Do not re-source these from the generator.
# =============================================================================
#
# The course is a band of the regular-octagon norm around the world centre.
# Along the DUE-EAST ray (dy = 0) the norm is simply dx, which is what makes
# these ten points derivable by hand:
#
#     OCT_MID    = 200      centre-line apothem, tiles
#     OCT_HALF_W = 12       half road width
#     OCT_IN     = 188      = OCT_MID - OCT_HALF_W
#     OCT_OUT    = 212      = OCT_MID + OCT_HALF_W
#     CURB_T     = 2        kerb thickness
#
#     road  d in [OCT_IN + CURB_T, OCT_OUT - CURB_T] = [190, 210]  DRIVABLE|TRACK
#     kerb  d in [188, 189] and [211, 212]                         TRACK only
#     grass everything else                                        neither
#
# World centre tile is 256; world pixel of tile t is t*8 + 4 (world.inc's CAM0
# uses exactly that convention).
CENTER_T = 256
_EAST = [  # (dx from centre, expected flag byte, why)
    (0,   0,                          "world centre, d=0, deep inside"),
    (187, 0,                          "d=187 < OCT_IN=188, still grass"),
    (188, FLAG_TRACK,                 "d=188 == OCT_IN, inner kerb starts"),
    (189, FLAG_TRACK,                 "d=189, inner kerb"),
    (190, FLAG_TRACK | FLAG_DRIVABLE, "d=190 == OCT_IN+CURB_T, road starts"),
    (200, FLAG_TRACK | FLAG_DRIVABLE, "d=200 == OCT_MID, the centre line"),
    (210, FLAG_TRACK | FLAG_DRIVABLE, "d=210 == OCT_OUT-CURB_T, road ends"),
    (211, FLAG_TRACK,                 "d=211, outer kerb"),
    (212, FLAG_TRACK,                 "d=212 == OCT_OUT, outer kerb ends"),
    (213, 0,                          "d=213 > OCT_OUT=212, grass again"),
]


def test_t2_col_map_flags_the_octagon_bands_at_hand_derived_boundaries(probe):
    """Ten points across grass -> kerb -> road -> kerb -> grass, on the
    due-east ray where the octagon norm is just dx.

    Every expectation above is arithmetic from the band constants. Nothing
    here reads world_map() or col_flags(); if this test and T1 could both be
    satisfied by the same wrong table, it would not be doing its job.
    """
    coords = [((CENTER_T + dx) * 8 + 4, CENTER_T * 8 + 4) for dx, _, _ in _EAST]
    got = query_batch(probe, coords)

    bad = []
    for (dx, want, why), (px, py, flag) in zip(_EAST, got):
        if flag != want:
            bad.append(f"  dx={dx:>3} ({why}): got {flag}, want {want}")
    assert not bad, (
        "hand-derived octagon boundaries disagree with the ROM.\n"
        "DO NOT fix this by re-deriving from the generator — that collapses "
        "T2 into T1. Either the band arithmetic in this file is wrong, or "
        "col_map is.\n" + "\n".join(bad))


def test_t2b_the_band_constants_this_file_hardcodes_still_match_the_generator(probe):
    """A guard, not an oracle.

    T2's whole value is that it does NOT consult the generator — so if the
    octagon ever moves, T2 goes red for a reason that looks like a col_map
    bug. This test exists to make that failure legible: it says "the map
    changed, T2's arithmetic needs updating", and it is the ONLY place in
    this file allowed to compare against gen_m7_assets' geometry.
    """
    _, _, _, gen = probe
    assert (gen.CENTER_T, gen.OCT_IN, gen.OCT_OUT, gen.CURB_T, gen.OCT_MID) == \
        (CENTER_T, 188, 212, 2, 200), (
            "the octagon moved; T2's hand-derived bands must be re-derived "
            "BY HAND from the new constants, not sourced from the generator")


# =============================================================================
# T3 — the coordinate contract: totality over the u16 input space.
# =============================================================================

def test_t3_col_map_is_total_over_the_u16_input_space(probe):
    """`f(x, y) == f(x + 4096k, y + 4096m)` for every k, m in range.

    A property, not a table — there is no oracle to share. This is the
    contract's teeth: out-of-bounds does not exist because the masks make
    every u16 name a real tile, so a caller that never wrapped still gets the
    right answer instead of a sentinel it might forget to check.
    """
    base = [(2052, 2052), (3652, 2052), (0, 0), (4095, 4095), (1500, 3000)]
    coords, groups = [], []
    for bx, by in base:
        g = [(bx, by), (bx + 4096, by), (bx, by + 4096), (bx + 4096, by + 4096),
             (bx + 8192, by + 12288)]
        g = [(x & 0xFFFF, y & 0xFFFF) for x, y in g]
        groups.append(g)
        coords.extend(g)

    res = {(px, py): f for px, py, f in query_batch(probe, coords)}
    for g in groups:
        vals = {res[c] for c in g}
        assert len(vals) == 1, (
            f"the torus identity broke: {[(c, res[c]) for c in g]} — every "
            f"one of these names the same tile")


def test_t3b_the_extreme_u16_inputs_return_a_real_tile_not_a_sentinel(probe):
    """0 and 65535 on each axis. A bounds-checking implementation would
    return a sentinel here; a total one returns whatever tile the wrap names,
    which must equal the wrapped coordinate's own answer."""
    _, _, world, gen = probe
    flags = D.load_tool("gen_col_flags").col_flags()
    W = gen.WORLD_T
    extremes = [(0, 0), (65535, 0), (0, 65535), (65535, 65535), (65535, 2052)]
    for px, py, flag in query_batch(probe, extremes):
        tx, ty = (px >> 3) & 511, (py >> 3) & 511
        assert flag == flags[world[ty * W + tx]], (
            f"px=({px},{py}) wrapped to tile ({tx},{ty}) but returned {flag} — "
            f"a sentinel, or the mask is not total")


def test_t9_the_probe_reads_no_byte_of_its_own_state_before_writing_it(probe):
    """T6's sibling, for the probe ROM. LAST in the file on purpose.

    The counters are cumulative from power-on, so in file order this covers
    every path T1-T3b exercised — 500+ queries, both arms of the wrap, the
    extreme u16 inputs — not just a boot.

    It ALSO drives one query of its own, and that is not redundant: run in
    isolation (`pytest ...::test_t9`) the fixture only boots, `@arm_one` never
    executes, and the test would pass while blind. Found by falsification —
    plant P11 was STILL GREEN through the tool and RED in module order, which
    is the same "the assertion never ran" trap the tool exists to catch. A gate
    whose teeth depend on its neighbours running first is a gate with a
    condition nobody wrote down.

    It exists because the probe shipped with exactly this defect: `MAIN` zeroed
    cmd/mark/param/seq/acc but not `param2`, which `@arm_one` reads on every
    cmd-3 query, and the fixture's old `load_rom` path inits the debugger AFTER
    the run, so nothing in the suite could see it. Measured
    before the fix: `$7E0204`/`$7E0205` flagged. After: zero.

    Note the host's `write_bytes` pokes do NOT count as writes for these
    counters — measured, and it is what makes this test possible at all:
    `query_batch` writes US_PARAM2 before every query, and the ROM reading it
    is still classified uninitialised.

    Scoped to the regions the probe DECLARES — its control block (state.toml)
    and ES_CM_HOT — rather than all of WRAM. The whole-WRAM run measures clean
    today, but a stack byte or an unclaimed scratch drifting into it would make
    this fail for a reason that is not the probe's contract.
    """
    runner, syms, _, _ = probe
    query_batch(probe, [(2052, 2052)])   # exercise cmd 3 / @arm_one standalone
    jmap = json.loads(
        (SUPERFORGE / "build" / "colmap_map" / "symbol_map.json").read_text())
    declared = [(p["sym"], p["start"], p["size"]) for p in
                jmap["scenes"]["probe"]["placements"] + jmap["globals"]
                if p["sym"].startswith("US_") or p["sym"] == "ES_CM_HOT"]
    assert declared, "no probe state claims in the symbol map — wrong scene key?"

    reads = set(runner.get_uninitialized_reads().get(MemoryType.SnesWorkRam, []))
    bad = [f"  {sym}+{a - start} (${a:04X})"
           for sym, start, size in declared
           for a in sorted(reads) if start <= a < start + size]
    assert not bad, (
        "the probe read bytes of its own declared state before ever writing "
        "them; on hardware those are power-on garbage:\n" + "\n".join(bad))
