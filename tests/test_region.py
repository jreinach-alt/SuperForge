"""region + tick_scale — proven from BOOTED ROMs under both console regions.

WHAT IS UNDER TEST, and where each case reads its evidence.

  * `engine/features/region` publishes `ES_RGN_PAL` from `$213F` bit 4. The
    flag is this feature's OUTPUT REGION — the whole of what it produces — so
    reading that word out of a running machine is reading the output, not a
    proxy for it. It is read under BOTH `SF_REGION` settings, from the same
    image, because a flag that is only ever checked on one machine is a
    constant.
  * `engine/features/tick_scale` publishes a per-frame whole-unit step. On
    NTSC it must be the authored constant on EVERY frame — that is the
    reversibility property, and it is what makes the NTSC picture unmovable.
    On PAL it must alternate around the measured frame ratio.
  * The property a PLAYER would notice is neither of those words: it is that
    the walk cycle runs at the same speed per REAL SECOND on both machines.
    That case reads the KNIGHT'S OAM TILE BYTE — the sprite table the PPU
    actually draws from — and counts the frames on which the drawn tile
    changes. `tools/rate_oracle.py` uses the same observable for the same
    reason (docs/96 §2.3).

THE NON-VACUITY CONTROL IS IN THE SAME RUN. `US_BLINK` is `brawler`'s
free-running per-frame heartbeat and it is deliberately NOT scaled — this
sprint compensates rates, not every frame-coupled site. So the same probe that
reads the walk cycle at parity reads the heartbeat at 5/6, from the same
machine over the same window. Without that, "the rates match" is satisfied by
an instrument that cannot see a difference at all.

REAL TIME, NOT FRAMES. A frame-indexed window hands PAL 50 samples where NTSC
got 60 and every rate then reads 5/6 because the HARNESS ran it 5/6 as long.
`tests/region_probe.py` advances until the MASTER CLOCK says the requested real
seconds have passed; the number of frames that takes is an output, never an
input. That trap is real and it is measured: docs/96 §2.4 records an observable
that read PARITY on a rail running 17% slow.

ONE PROCESS PER REGION, because `mesen_runner._apply_region` runs once per
process — `tools/pal_probe.py`'s precedent, followed rather than reinvented.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
PROBE = SUPERFORGE / "tests" / "region_probe.py"

# The frame ratio the timebase scales by, from the same two measurements
# `engine/features/tick_scale/tick_scale.asm` derives it from:
#   NTSC 21,477,270 / 357,368 = 60.09879 fps
#   PAL  21,281,370 / 425,568 = 50.00714 fps
FRAME_RATIO = 60.09879 / 50.00714          # 1.2018039
UNCOMPENSATED = 1.0 / FRAME_RATIO          # 0.83208 — what a rail reads today

SCR_SPEED = 2                              # game/scroller/scroller.inc


def _probe(region: str, spec: dict) -> dict:
    rom = SUPERFORGE / spec["rom"]
    if not rom.exists():
        pytest.fail(f"{rom} is not built — see AGENTS.md's BUILD-FIRST block")
    r = subprocess.run(
        [sys.executable, str(PROBE), json.dumps(spec)],
        capture_output=True, text=True, cwd=str(SUPERFORGE), timeout=900,
        env=dict(**{k: v for k, v in __import__("os").environ.items()},
                 SF_REGION=region))
    line = next((x for x in r.stdout.splitlines() if x.startswith("SFRGN ")),
                None)
    if line is None:
        pytest.fail(f"{region} probe failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(line[len("SFRGN "):])


SCROLLER_SPEC = dict(
    rom="build/scroller.sfc", map="build/scr/symbol_map.json", scene="world",
    warm_s=1.0, seconds=3.0, pad={"right": True},
    words=[["ES_RGN_PAL", 2], ["US_TS_STEP", 2], ["US_FRAMES", 2]])

BRAWLER_SPEC = dict(
    rom="build/brawler.sfc", map="build/br/symbol_map.json", scene="fight",
    warm_s=4.0, seconds=8.0, pad={"left": True},
    words=[["ES_RGN_PAL", 2], ["US_BLINK", 2], ["US_TSP", 2], ["US_TSA", 2],
           ["US_HP", 2], ["US_GAMEOVER", 2]],
    oam=[["ES_O_KNIGHTS", 2]])


@pytest.fixture(scope="module")
def scr():
    return {r: _probe(r, SCROLLER_SPEC) for r in ("ntsc", "pal")}


@pytest.fixture(scope="module")
def brw():
    return {r: _probe(r, BRAWLER_SPEC) for r in ("ntsc", "pal")}


# ===========================================================================
# region — the flag, from a booted ROM, under both settings
# ===========================================================================

def test_the_region_flag_is_clear_on_ntsc_and_set_on_pal(scr):
    """ONE IMAGE, TWO MACHINES. The same `scroller.sfc` reads 0 on one and 1
    on the other — which is the whole claim of R0 and the reason a build-time
    region switch is not needed."""
    assert scr["ntsc"]["rom_md5"] == scr["pal"]["rom_md5"], (
        "the two regions were run against different images — the claim is "
        "about ONE cart")
    assert set(scr["ntsc"]["words"]["ES_RGN_PAL"]) == {0}
    assert set(scr["pal"]["words"]["ES_RGN_PAL"]) == {1}


def test_the_flag_is_stable_for_the_whole_run(scr):
    """It is latched once at boot, not re-read per frame, so it may not flicker.

    THE LIMIT, STATED — this case does NOT prove the read is a MASK, and no
    other case in this module does either. The flag is latched ONCE, so a wrong
    latch is stably wrong: stability and correctness are independent here.
    Measured rather than argued — a planted `cmp #(RGN_PAL_BIT | 3)` / `bne` in
    place of `and` / `beq` passes EVERY case in this file
    (`docs/audit/region_r0_review.md` §4.2). An earlier version of this
    docstring claimed bit 7 toggling was "exactly what a compare-against-$13
    would have picked up". It is not.

    Why nothing here can settle it, from the emulator's own source: `$213F` is
    `oddFrame<<7 | locationLatched<<6 | (Ppu2OpenBus & $20) | PAL<<4 | $03`
    (`/tmp/Mesen2/Core/SNES/SnesPpu.cpp`, `case 0x213F`). A compare against the
    whole byte is right by coincidence exactly while bits 7, 6 and 5 are clear
    at the read instant — and this harness boots deterministically into frame 0
    with nothing latched and no prior PPU2 read, so all three always are. Bit 7
    is the only one that moves unaided, and it moves at END of frame, after the
    boot read has already happened.

    Settling it needs an instrument this repo does not have: a boot on the
    other field parity (`vendor/mesen_runner.py` binds no console `Reset`), a
    second emulator, or hardware. Until one exists the mask is established by
    READING THE FILE — `and #RGN_PAL_BIT`, `RGN_PAL_BIT = 1 << 4`, in
    `engine/features/region/region.asm` — which is the primary source for what
    our own code does, and is NOT evidence about the machine.

    What this case does prove stands on its own: once latched the flag does not
    move again, on either machine, for the whole window."""
    for region in ("ntsc", "pal"):
        series = scr[region]["words"]["ES_RGN_PAL"]
        assert len(set(series)) == 1, (
            f"{region}: the region flag moved during the run: "
            f"{sorted(set(series))}")


def test_the_probe_really_ran_two_different_machines(scr):
    """The instrument's own liveness check. If SF_REGION had not taken, both
    children would report the same frame period and every ratio below would be
    a statement about nothing."""
    assert scr["ntsc"]["fps"] == pytest.approx(60.0988, abs=0.01)
    assert scr["pal"]["fps"] == pytest.approx(50.0072, abs=0.01)


def test_region_is_opt_in_and_a_rail_that_does_not_compose_it_has_no_flag():
    """The reversibility property, read off the allocator's own output.

    docs/95 §7 rejected R0-b (read $213F unconditionally in `init.inc`) because
    a DECLARED feature must leave every non-composing rail with no claim, no
    symbol and no boot call — that is what makes composing it reversible.

    THE WITNESS RAIL MOVED ONCE, deliberately. This case first held
    `microzero` up as the non-composer, back when its pinned md5 was the
    R0-era control (docs/94 §4.2 as then written). The owner then ruled the
    engine's requirements include region awareness, the flagship converted,
    and the pin moved with it (docs/98 §3) — so the old witness now composes
    the feature and CORRECTLY carries the flag. The durable witness is
    `split_v_seamtrial`: exempt BY DESIGN, with the reason stated in its own
    game.toml ("region parity is not this rail's subject" — its sweep is
    frame-indexed on purpose, and its tests are absolute-frame picture
    claims). If THIS rail ever grows a region claim, either the exemption was
    deliberately revisited (update the witness and its reason here) or
    something really is allocating the flag unconditionally."""
    svs = json.loads((BUILD / "svs" / "symbol_map.json").read_text())
    syms = {p["sym"] for p in svs["globals"]}
    for scene in svs["scenes"].values():
        syms |= {p["sym"] for p in scene["placements"]}
    assert "ES_RGN_PAL" not in syms, (
        "split_v_seamtrial has a region claim — it is exempt by design and "
        "does not compose the feature, so either the exemption was revisited "
        "(move this witness deliberately) or something is allocating the "
        "flag unconditionally")

    scr_map = json.loads((BUILD / "scr" / "symbol_map.json").read_text())
    assert "ES_RGN_PAL" in {p["sym"] for p in scr_map["globals"]}


# ===========================================================================
# tick_scale — the published step
# ===========================================================================

def test_ntsc_publishes_the_authored_constant_on_every_frame(scr):
    """THE REVERSIBILITY PROPERTY, IN THE MACHINE. Not "close to 2 on average"
    — exactly SCR_SPEED on every single frame, which is why the NTSC picture
    cannot move however the PAL arm is tuned."""
    steps = scr["ntsc"]["words"]["US_TS_STEP"]
    assert len(steps) > 100
    assert set(steps) == {SCR_SPEED}, sorted(set(steps))


def test_pal_publishes_a_two_valued_step_that_averages_the_frame_ratio(scr):
    """The accumulator, visible directly: whole units only, alternating either
    side of 2.4036, and summing over the window to the scaled distance.

    An INTEGER scale is what this replaces and it has no correct answer here —
    docs/96 §4.4 measured round-to-nearest at 0.83208 (it changes nothing) and
    round-up at 1.24812. Both are excluded by the bounds below."""
    steps = scr["pal"]["words"]["US_TS_STEP"]
    assert len(steps) > 100
    assert set(steps) == {SCR_SPEED, SCR_SPEED + 1}, sorted(set(steps))
    mean = sum(steps) / len(steps)
    assert mean / SCR_SPEED == pytest.approx(FRAME_RATIO, rel=0.01), (
        f"PAL mean step {mean} / {SCR_SPEED} = {mean / SCR_SPEED:.6f}, "
        f"wanted {FRAME_RATIO:.6f}")


def test_the_scaled_step_is_what_moves_the_camera_further_per_pal_frame(scr):
    """The two-valued step is not decoration: the frame counter proves the
    tick still runs ONCE per frame, so the extra distance can only come from
    the step itself. (`lump`'s refuted alternative runs the tick twice on one
    frame in five — this is what rules that shape out by observation.)"""
    for region in ("ntsc", "pal"):
        f = scr[region]["words"]["US_FRAMES"]
        deltas = {f[i] - f[i - 1] for i in range(1, len(f))}
        assert deltas == {1}, (
            f"{region}: US_FRAMES advanced by {sorted(deltas)} — the tick is "
            f"not running exactly once per frame")


# ===========================================================================
# The player-visible property: the walk cycle, read out of OAM
# ===========================================================================

def _tile_changes_per_second(rec):
    t = rec["oam"]["ES_O_KNIGHTS+2"]
    return sum(1 for i in range(1, len(t)) if t[i] != t[i - 1]) / rec["real_s"]


def _blink_per_second(rec):
    b = rec["words"]["US_BLINK"]
    return (b[-1] - b[0]) / rec["real_s"]


def test_the_guard_held_so_the_window_means_something(brw):
    """A rail that dies mid-window averages a live half with a frozen half and
    reports a ratio that is about nothing. `rate_oracle`'s guard idea, made an
    assertion: the knight must be alive and not KO'd for the whole run, in
    BOTH regions — and the compensated PAL arm is exactly where that could
    newly fail, because the fight's dynamics change with the walk speed."""
    for region in ("ntsc", "pal"):
        assert set(brw[region]["words"]["US_GAMEOVER"]) == {0}
        assert set(brw[region]["words"]["US_HP"]) == {2}


def test_the_walk_cycle_runs_at_the_same_rate_per_real_second(brw):
    """THE CASE THIS FEATURE EXISTS FOR, and it reads OAM.

    The knight's tile byte is the sprite table the PPU draws from, so counting
    the frames on which the DRAWN tile changes measures the walk cycle where a
    player perceives it. Uncompensated this reads 0.828 (docs/96 §2.5); the
    band below excludes that by more than five times its own width."""
    n, p = _tile_changes_per_second(brw["ntsc"]), _tile_changes_per_second(brw["pal"])
    assert n > 5.0, f"the NTSC walk cycle barely ran ({n:.3f}/s)"
    ratio = p / n
    assert ratio == pytest.approx(1.0, abs=0.03), (
        f"walk cycle ntsc {n:.4f}/s pal {p:.4f}/s ratio {ratio:.5f} — "
        f"uncompensated would read {UNCOMPENSATED:.5f}")


def test_the_unscaled_heartbeat_in_the_same_run_still_reads_five_sixths(brw):
    """THE NON-VACUITY CONTROL, and an honest statement of scope.

    `US_BLINK` advances once per FRAME and this sprint did not scale it — the
    185-site retune is not in scope, and what was compensated on this rail is
    its three RATES (the two walk speeds and the animation clock). So the same
    probe that reads the walk cycle at parity reads the heartbeat at 5/6, over
    the same window on the same machine. If this case ever reads parity too,
    the instrument has stopped being able to see a difference and every number
    above is worthless."""
    n, p = _blink_per_second(brw["ntsc"]), _blink_per_second(brw["pal"])
    ratio = p / n
    assert ratio == pytest.approx(UNCOMPENSATED, abs=0.01), (
        f"the unscaled frame heartbeat read {ratio:.5f}; it must still be "
        f"~{UNCOMPENSATED:.5f}, or this module cannot see a rate difference")


def test_both_of_brawlers_scaled_rates_behave_like_the_scroller_camera(brw):
    """The walk step and the ANIMATION CLOCK, per region.

    The clock is the interesting one: docs/95 §5.2 classifies a small-integer
    frame divider as having "no correct x5/6, only a rounding policy". This
    feature does not scale the divider at all — it scales what the clock
    ADVANCES BY, so the divider stays the integer its table authored."""
    assert set(brw["ntsc"]["words"]["US_TSP"]) == {2}      # BR_WALK_SPEED
    assert set(brw["ntsc"]["words"]["US_TSA"]) == {1}      # one anim unit
    assert set(brw["pal"]["words"]["US_TSP"]) == {2, 3}
    assert set(brw["pal"]["words"]["US_TSA"]) == {1, 2}
    tsa = brw["pal"]["words"]["US_TSA"]
    assert sum(tsa) / len(tsa) == pytest.approx(FRAME_RATIO, rel=0.02)
