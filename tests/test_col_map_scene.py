"""col_map in the live scene — behavioural and composition tests.

Split from test_col_map.py deliberately: MesenRunner is a process-global
singleton and two concurrently-live runners reach into each other's session.
Keeping the probe ROM and microzero in separate modules means pytest only ever
has one module-scoped runner alive at a time.

test_col_map.py drives the ISOLATED kernel over chosen coordinates. This file
drives the SHIPPED integration: cm_tick queries the live camera every frame,
and these tests read that result under real motion, real wrap, and alongside
features that share nothing with it.
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
RACE = 1                         # scene id, as tests/mz_drive uses
FLAG_DRIVABLE = 1 << 0
FLAG_TRACK = 1 << 1


@pytest.fixture(scope="module")
def booted():
    """One runner for the module — MesenRunner is a process-global singleton
    and two live runners reach into each other's session."""
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    world = (SUPERFORGE / "build" / "assets" / "world_map.bin").read_bytes()
    gen = D.load_tool("gen_m7_assets")
    runner = MesenRunner()
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    runner.debug_break()
    D.enter_race(runner, syms)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, world, gen
    runner.debug_resume()
    runner.stop()


def _cm(syms):
    return syms["ES_CM_HOT"]["start"]


# The octagon band constants, hand-derived — the same arithmetic
# test_col_map.py's T2 uses, and for the same reason: it must not be sourced
# from the generator, or the semantics stop being independently checked.
# test_col_map.py::test_t2b guards them against the map moving.
CENTER_T = 256
OCT_IN, OCT_OUT = 188, 212
INV_SQRT2_Q14 = 11585            # 2**14 / sqrt(2), the norm's diagonal term


# =============================================================================
# T4 / T5 — behavioural: the live consumer under real motion.
# =============================================================================

def test_t4_the_live_consumer_tracks_the_camera_every_frame(booted):
    """cm_tick's output, sampled every frame across a real drive.

    Reads CM_FLAG and ES_M7ORG together each frame and checks them against
    each other — so this catches a stale result, a one-frame-late result, or
    a result computed from the wrong origin, none of which T1 can see because
    T1 supplies the coordinates itself.
    """
    runner, syms, world, gen = booted
    flags = D.load_tool("gen_col_flags").col_flags()
    W, m7, cm = gen.WORLD_T, syms["ES_M7ORG"]["start"], _cm(syms)

    D.enter_race(runner, syms)
    runner.debug_break()
    seen, bad = set(), []
    for i in range(120):
        runner.frame_step(1, b=True)
        px, py = runner.read_u16(WR, m7 + 0), runner.read_u16(WR, m7 + 2)
        flag = runner.read_bytes(WR, cm + 4, 1)[0]
        tx, ty = (px >> 3) & 511, (py >> 3) & 511
        want = flags[world[ty * W + tx]]
        seen.add(flag)
        if flag != want:
            bad.append(f"  frame {i}: cam=({px},{py}) tile=({tx},{ty}) "
                       f"got={flag} want={want}")
    assert not bad, ("the live query disagrees with the camera it read:\n" +
                     "\n".join(bad[:5]))
    assert len(seen) > 1, (
        f"every frame returned the same flag {seen} — the drive never left "
        f"the surface it started on, so this proved nothing about tracking")


def test_t5_the_flag_transitions_at_the_road_edge_in_both_directions(booted):
    """Drive off the course and back on: TRACK -> grass -> TRACK.

    AGENTS.md's state-cycle rule — a test that only walks one direction locks
    that direction and ships the other broken. Read from CM_FLAG under real
    motion, with the boundary crossing corroborated by the camera position
    against T2's hand-derived bands.
    """
    runner, syms, world, gen = booted
    m7, cm = syms["ES_M7ORG"]["start"], _cm(syms)

    D.enter_race(runner, syms)
    runner.debug_break()

    trace = []
    for _ in range(200):
        runner.frame_step(1, b=True)
        px, py = runner.read_u16(WR, m7 + 0), runner.read_u16(WR, m7 + 2)
        trace.append((px, py, runner.read_bytes(WR, cm + 4, 1)[0]))

    flags = [f for _, _, f in trace]
    on = [i for i, f in enumerate(flags) if f & FLAG_TRACK]
    off = [i for i, f in enumerate(flags) if not (f & FLAG_TRACK)]
    assert on and off, (
        f"the drive never crossed the course edge (flags seen: {set(flags)}) — "
        f"there is no transition to assert")

    # both directions really happened: an on->off edge AND an off->on edge
    edges = [(flags[i - 1] & FLAG_TRACK, flags[i] & FLAG_TRACK)
             for i in range(1, len(flags))
             if bool(flags[i - 1] & FLAG_TRACK) != bool(flags[i] & FLAG_TRACK)]
    assert any(a and not b for a, b in edges), "no TRACK -> grass transition"
    assert any(not a and b for a, b in edges), "no grass -> TRACK transition"

    # every crossing agrees with the hand-derived bands (T2's arithmetic,
    # applied to the positions the ROM actually reported)
    for px, py, f in trace:
        dx, dy = (px >> 3) - CENTER_T, (py >> 3) - CENTER_T
        d = max(abs(dx), abs(dy), (abs(dx) + abs(dy)) * INV_SQRT2_Q14 >> 14)
        want_track = OCT_IN <= d <= OCT_OUT
        assert bool(f & FLAG_TRACK) == want_track, (
            f"cam=({px},{py}) octagon distance {d}: TRACK bit is "
            f"{bool(f & FLAG_TRACK)}, bands say {want_track}")


# =============================================================================
# T6 — the init contract.
# =============================================================================

def test_t6_no_byte_of_cm_hot_is_ever_read_before_it_is_written(booted):
    """col_map's init contract IS write-before-read, and this is its gate.

    col_map declares no `[init] zero`. Its feature.toml takes the second form
    docs/09 §4.5 allows — write-before-read by construction — and spells out
    the per-call ordering that makes it true. That choice is deliberate and it
    puts the whole contract on this test: nothing else in the build proves it,
    because `[init] zero` emits comments rather than code anyway.

    Mechanism, stated exactly because it bounds what this can see: Mesen's
    per-address counters, classified `WriteCounter == 0 and ReadCounter > 0`
    (vendor/mesen_runner.py:2196-2200). That is a FINAL-STATE test. It catches
    a byte read while never written at all — the class that returns power-on
    garbage on hardware. It does NOT catch a byte read early and written later
    in the same run. Zeroing the block at scene enter would set WriteCounter
    on all ten bytes and leave this test unable to fail, which is the third
    reason the declaration was deleted rather than implemented.

    Falsified by P10-scratch-store-dropped (tools/falsify_col_map.py): remove
    the `sta z:CM_T1` at col_map.asm:71 and the kernel adds a never-written
    scratch word — this goes red naming those bytes.

    The runner was loaded with detection armed from power-on and the whole
    module has been driving the ROM, so this covers every path the other tests
    exercised, not just a boot.
    """
    runner, syms, _, _ = booted
    cm = _cm(syms)
    size = syms["ES_CM_HOT"]["size"]
    assert size == 10, f"cm_hot is {size} B; this test's range needs updating"

    reads = runner.get_uninitialized_reads()
    ours = sorted(a for a in reads.get(MemoryType.SnesWorkRam, [])
                  if cm <= a < cm + size)
    assert not ours, (
        f"cm_hot bytes read before ever being written: "
        f"{[hex(a) for a in ours]} (block at {hex(cm)}..{hex(cm + size - 1)}) — "
        f"on hardware those reads return power-on garbage")


# =============================================================================
# T7 / T8 — composition.
# =============================================================================

def test_t7_col_map_and_vwf_are_correct_across_the_same_window(booted):
    """VWF shares nothing with col_map: no claim, no channel, no register.

    The live risk is col_map's phb/pha/plb pair. Dropping the restoring `plb`
    leaves DB on a chunk bank; the falsification showed that does not merely
    corrupt a neighbour, it takes the whole ROM down — PC out at $4abe with
    the scene control block reading garbage after 40 frames.

    THIS TEST WAS REWRITTEN BECAUSE NOTHING COULD FIRE IT. a later review
    established that P6's red comes from `mz_drive.py:84` inside
    `D.enter_race` — the ROM is dead before any assertion here runs. Probing
    further, the remediation could not fire ANY of the three old levels:

      * six different out-of-claim stores from col_map into vwf's DP pen block
        ($3E, $40, $41, $42, $43, $47) — all GREEN, because `any(chr_bytes)`
        cannot tell "rendering" from "stale bytes left over from earlier",
        which is the very hole the old docstring named and did not close;
      * the bank-term drop (P1's edit) — GREEN, because the old single-frame
        sample lands at tile (456,154), out in the grass, where 96% of the
        world's wrong answers are also grass. T8 was fixed for exactly this
        disease in this change; T7 still had it.

    So both feature halves are now asserted ACROSS THE WINDOW rather than at
    one frame, which is what gives them power (docs/09 §4.5: for a
    composition, assert both features' outputs). Measured over the 40 frames:
    the camera visits 37 distinct tiles across chunks 2, 3 and 4 with flags
    {0, 3}, and VWF's CHR strip takes 3 distinct states with ink growing
    56 -> 68 bytes. Both reproduce run to run.

    Falsified: P12-t7-bank-term-dropped fires level 3; P13-t7-stomps-vwf-pen
    fires level 2. Level 1 (scene liveness) still has no plant of its own —
    the only defect that kills the ROM kills it upstream in `enter_race` — so
    it is a regression tripwire, not a discriminating assertion, and this
    docstring says so rather than implying otherwise.
    """
    runner, syms, world, gen = booted
    flags = D.load_tool("gen_col_flags").col_flags()
    W, m7, cm = gen.WORLD_T, syms["ES_M7ORG"]["start"], _cm(syms)
    VR = MemoryType.SnesVideoRam

    # VWF's strips are a sub-range of text_chr's page, derived the way vwf.asm
    # derives it (VWF_TILE0 = font bytes / 16 per 2bpp tile, 8 words per tile)
    # from emitted symbols only.
    tile0 = syms["ES_R_FONT_BIN"]["size"] // 16
    base = syms["ES_V_TEXT_CHR"]["start"] + tile0 * 8

    D.enter_race(runner, syms)
    runner.debug_break()

    strip_states, mism, tiles = set(), [], set()
    for i in range(40):
        runner.frame_step(1, b=True)
        chr_bytes = runner.read_bytes(VR, base * 2, 256)
        strip_states.add(bytes(chr_bytes))
        px, py = runner.read_u16(WR, m7 + 0), runner.read_u16(WR, m7 + 2)
        tx, ty = (px >> 3) & 511, (py >> 3) & 511
        tiles.add((tx, ty))
        flag = runner.read_bytes(WR, cm + 4, 1)[0]
        if flag != flags[world[ty * W + tx]]:
            mism.append(f"  frame {i}: cam=({px},{py}) tile=({tx},{ty}) "
                        f"got={flag} want={flags[world[ty * W + tx]]}")

    # 1. the scene machine survived col_map running every frame. A tripwire,
    #    not a discriminating assertion — see the docstring.
    assert D.scene_now(runner, syms) == (RACE, 0), (
        f"the scene machine is no longer settled in race "
        f"({D.scene_now(runner, syms)}) — col_map disturbed something it "
        f"shares nothing with")
    pc = runner.snes_state_snapshot().cpu_pc
    assert 0x8000 <= pc <= 0xFFFF, (
        f"CPU PC is ${pc:04X}, outside LoROM's $8000-$FFFF — the ROM is "
        f"executing garbage")

    # 2. VWF is ACTIVELY rendering, not merely non-empty. The state count is
    #    what distinguishes a live reveal from a frozen strip that still holds
    #    an earlier message's ink.
    # NB: `any(strip_states)` would be VACUOUS — strip_states is a set of
    # bytes OBJECTS, and a non-empty set of objects is always truthy. The
    # predecessor `any(chr_bytes)` (over raw bytes) was not. Reach inside.
    assert any(any(s) for s in strip_states), (
        "VWF's CHR strip is entirely zero while a dialog is revealing — "
        "col_map may have corrupted the upload")
    assert len(strip_states) > 1, (
        f"VWF's CHR strip never changed across 40 frames of a revealing "
        f"dialog ({len(strip_states)} distinct state) — it is frozen, and a "
        f"frozen strip full of stale ink passes a non-zero check")

    # 3. and col_map's answer is right on EVERY frame of that same window,
    #    not just the last one.
    assert len(tiles) > 1, (
        f"the camera never moved during the window (tiles: {tiles}) — the "
        f"check below would be a single sample again")
    assert not mism, (
        f"col_map wrong while VWF is live, on {len(mism)}/40 frames:\n" +
        "\n".join(mism[:5]))


def test_t8_col_map_and_mode7_stream_agree_on_the_same_world_row(booted):
    """Cooperation on a shared read-only resource.

    Both features read the same ROM blob by the same bank tiling through
    completely different code — col_map one byte at a time, mode7_stream in
    128-byte DMA slices. Disagreement means one of them indexes wrong.

    The camera is brought to a stop first: while it moves, VRAM trails it by
    the staging + VBlank-drain lag BY DESIGN (AGENTS.md).
    """
    runner, syms, world, gen = booted
    flags = D.load_tool("gen_col_flags").col_flags()
    W, m7, cm = gen.WORLD_T, syms["ES_M7ORG"]["start"], _cm(syms)
    VR = MemoryType.SnesVideoRam

    D.enter_race(runner, syms)
    runner.debug_break()

    # Come to rest somewhere the point-check has SOME power. Not "by
    # construction" — that claim was wrong, and here is the measurement.
    #
    # A col_map-vs-VRAM check at one tile is nearly powerless unconditioned:
    # a one-tile offset changes the answer at only 1.694% of tiles (P7,
    # measured over all 262,144), because neighbours almost always share a
    # flag. Plants P7 and P8 both sailed through the earlier version of this
    # test for exactly that reason. Parking beside a differing 4-neighbour
    # helps a lot and is still a coin flip that loses two times in three:
    # of the 9,072 tiles satisfying `neighbours_differ` (3.461% of the world),
    # P7 changes the flag at 3,224 — 35.5%; P8 at 3,200 — 35.3%. Making it
    # certain would mean conditioning on the OFFSET'S OWN axis, which a
    # 4-neighbour predicate does not do, and which the test cannot do anyway
    # because it does not know which axis a hypothetical defect moved.
    #
    # So the parking is corroboration, not the teeth. THE TEETH ARE THE
    # 120x120 WINDOW COMPARISON below, which is a whole-region check and is
    # where addressing defects actually die. P7 and P8 are aimed at T1, whose
    # contract is the addressing sweep. If no differing-neighbour rest
    # position turns up, say so loudly rather than pass a check with no teeth.
    def neighbours_differ(tx, ty):
        here = flags[world[ty * W + tx]]
        return any(flags[world[((ty + dy) & 511) * W + ((tx + dx) & 511)]] != here
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    # Short nudges, not long dashes: each burst moves the camera a few tiles,
    # so the search walks tile-by-tile instead of leaping across the ring and
    # hoping to land well. Long dashes failed here for real — this test passed
    # alone and failed in module order, because it inherited the previous
    # test's end position and its 8 long attempts never came to rest near an
    # edge (last tile (456,17), out in the grass).
    # Turn 90 degrees off the current heading first. Without this the search
    # cannot succeed on the east straight: the car drives ALONG the road at
    # tile column 456 (= centre 256 + OCT_MID 200), where every 4-neighbour is
    # also road, so no rest position there discriminates. Observed for real —
    # the nudge search walked (456,17) -> (456,311), all of it on-road.
    D.steer_to(runner, syms, (D.heading(runner, syms) + 16) & 63)

    tx = ty = None
    for attempt in range(60):
        for _ in range(4):
            runner.frame_step(1, b=True)
        D.coast_to_stop(runner, syms)     # parked throughout: it frame_steps too
        runner.frame_step(4)
        px, py = runner.read_u16(WR, m7 + 0), runner.read_u16(WR, m7 + 2)
        tx, ty = (px >> 3) & 511, (py >> 3) & 511
        if neighbours_differ(tx, ty):
            break
    else:
        raise AssertionError(
            f"never came to rest beside a flag boundary in 60 nudges (last "
            f"tile ({tx},{ty})) — the point-check below would have 1.7% power "
            f"instead of 35%, so failing loudly beats passing weakly")

    flag = runner.read_bytes(WR, cm + 4, 1)[0]
    assert flag == flags[world[ty * W + tx]], (
        f"col_map disagrees with the blob at rest: cam=({px},{py})")

    # What the streamer put in VRAM, over a WINDOW rather than one tile.
    vram = runner.read_bytes(VR, 0, 128 * 128 * 2)
    mism = []
    for wy in range(ty - 60, ty + 60):
        for wx in range(tx - 60, tx + 60):
            wxm, wym = wx & 511, wy & 511
            got = vram[(((wym & 127) * 128) + (wxm & 127)) * 2]
            want = world[wym * W + wxm]
            if got != want:
                mism.append((wxm, wym, got, want))
    assert not mism, (
        f"{len(mism)} tiles of the streamed window disagree with the world "
        f"blob col_map reads; first 5: {mism[:5]}")

    # and col_map's flag describes the tile actually on screen under the
    # camera — asserted at a boundary-adjacent tile, so an off-by-one shows.
    vram_tile = vram[(((ty & 127) * 128) + (tx & 127)) * 2]
    assert flag == flags[vram_tile], (
        f"col_map's flag {flag} does not describe the tile on screen under "
        f"the camera (VRAM tile id {vram_tile} at ({tx},{ty}))")
