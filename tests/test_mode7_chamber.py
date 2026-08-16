"""mode7_chamber — four per-scanline effects over one Mode 7 plane, in pixels.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a stated pad held for a
stated number of frames, so the whole trajectory is a pure function of the
replay triple.

WHAT THIS RAIL IS:

    C1  the floor BOWS — per-scanline M7A varies top -> mid -> bottom
    C2  the floor UNDULATES — the texture travels up and down, with NO
        rotation matrix (the angle is held constant)
    C3  a Mode 1 band sits above the Mode 7 floor, clean, no smear
    C4  the vignette — the mid band is brighter than the top and the bottom
    C5  it boots and the heartbeat advances

All five are named cases below. C5 is the one that invites a proxy — a frame
counter mirrored into WRAM — and it is deliberately NOT written that way: this
module never reads a program variable, and "it booted" is carried by every
other case having a picture to read at all.

THE HEADLINE PROOF IS A PER-ROW PREDICTION OF THE BOW. The ashlar floor's
horizontal period is two tiles = 16 world px, and a scanline's M7A is exactly
how many world pixels the 256-px screen row spans: `A/256 * 256 = A`. So the
number of colour CHANGES across a rendered row is `A/8`, and
`test_the_floor_bows_row_by_row_as_the_declared_m7a_column_says` asserts that
for EVERY patterned floor row against the generator's own column. That one
assertion carries C1 quantitatively rather than as "the middle looks
different", and it fails on a wrong bow, a flat bow, a reversed bow, an
off-by-one index table and a bow read from the wrong ROM bank.

THE BOW STEP IS NEVER READ AS A VARIABLE. `m7_barrel` keeps it in DP and a
test could read it in one call — which is exactly the proxy-variable move rule
2 forbids, because the whole question is whether a step reaches M7A through a
ROM column and an HDMA index table. Every drive case here reads PIXELS; the
one table case reads the WRAM the DMA controller itself fetches.

FRAME ACCOUNTING. A pad held through `advance(N)` reaches the picture after
the main loop's tick steps the axis, the NEXT VBlank's hook re-points the
index table, and the frame after that renders it. Every drive below holds its
pad from BOOT for the whole advance, so the axis has long since reached its
clamp and the lag is not on the assertion path.
"""
import os
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from frame_geometry import PICTURE_LINES, REAL_Y_BIAS, png_row   # noqa: E402
from machine import Machine, MemoryType                          # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "mode7_chamber.sfc"
MAP = json.loads((BUILD / "m7c" / "symbol_map.json").read_text())
ASSETS = BUILD / "assets"

# The generator is imported as the ORACLE for what the ROM should be showing —
# the same module the build ran, so the declared bow column, the perspective
# column and the vignette intensities are read from one place rather than
# re-typed here. It is not a re-implementation: it IS the producer.
_spec = importlib.util.spec_from_file_location(
    "chamber_gen", SUPERFORGE / "tools" / "gen_chamber_assets.py")
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)

SEAM = GEN.MB_SEAM                      # game/mode7_chamber/world.inc MB_SEAM
BOW_MAX = GEN.MB_BOWS - 1
MORTAR5 = 3                             # the mortar colour's 5-bit channel


def _sym(name, scene="chamber"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _expand5(v: int) -> int:
    """Mesen's 5-bit -> 8-bit channel expansion: v<<3 | v>>2. Measured against
    the rendered mortar rows, not assumed."""
    return (v << 3) | (v >> 2)


# =============================================================================
# fixtures — one picture per (frame, pad), captured once
# =============================================================================
def _shot(tmp_path, frame, pad=None, name="f"):
    with Machine(str(ROM)) as m:
        m.advance(frame, pad1=pad) if pad else m.advance(frame)
        out = m.screenshot(str(tmp_path / f"{name}.png"))
    return Image.open(out).convert("RGB").load()


@pytest.fixture(scope="module")
def boot(tmp_path_factory):
    """Frame 120, no input: the shipping picture at the FULL bow."""
    return _shot(tmp_path_factory.mktemp("m7c"), 120, name="boot")


@pytest.fixture(scope="module")
def flat(tmp_path_factory):
    """Frame 120 with Down held from boot: the bow clamped to step 0 — the
    runtime NON-VACUITY CONTROL, inside the shipping binary. Same absolute
    frame as `boot`, so the roll has reached the same world row and the only
    difference in the picture is the M7A column."""
    return _shot(tmp_path_factory.mktemp("m7c"), 120, {"down": True}, "flat")


def _transitions(px, picture_row: int) -> int:
    y = png_row(picture_row)
    return sum(1 for x in range(1, 256) if px[x, y] != px[x - 1, y])


def _uniform_colour(px, picture_row: int):
    y = png_row(picture_row)
    row = {px[x, y] for x in range(256)}
    return row.pop() if len(row) == 1 else None


# =============================================================================
# C1 — the floor BOWS
# =============================================================================
def test_the_floor_bows_row_by_row_as_the_declared_m7a_column_says(boot):
    """The rendered horizontal period of EVERY patterned floor row equals the
    bow column the generator baked, row for row.

    The arithmetic, and why the number is exact rather than a proxy: a Mode 7
    scanline maps screen X to world X as `VX = A*(SX-128) + M7X` with A in 8.8,
    so a 256-px row spans exactly `A` world pixels. The ashlar checker's
    horizontal period is BLOCK*TILE_PX = 16 world px and each period contributes
    two colour changes, so a row shows `A/8` changes. Nothing about that
    depends on where the roll has got to.
    """
    col = GEN.bow_column(BOW_MAX)
    checked = 0
    for pic in range(SEAM, PICTURE_LINES):
        t = _transitions(boot, pic)
        if t == 0:
            continue                    # a mortar or rib row: one colour, no period
        pred = round(col[pic - SEAM] / 8)
        assert abs(t - pred) <= 1, (
            f"picture row {pic}: {t} colour changes, the declared bow column "
            f"says A={col[pic - SEAM]} i.e. {pred}")
        checked += 1
    assert checked >= 60, f"only {checked} patterned rows — the floor is not showing"


def test_the_bow_is_a_bulge_and_not_a_ramp(boot):
    """C1's SHAPE, stated independently of the column: the middle of the floor
    band shows a strictly wider world span than either edge.

    Population attributed (the population rule): only patterned rows are counted, and
    the three groups are disjoint thirds of the floor band, so no row
    contributes to two of them."""
    band = [(pic, _transitions(boot, pic)) for pic in range(SEAM, PICTURE_LINES)]
    band = [(p, t) for p, t in band if t > 0]
    third = (PICTURE_LINES - SEAM) // 3
    top = max(t for p, t in band if p < SEAM + third)
    mid = max(t for p, t in band if SEAM + third <= p < SEAM + 2 * third)
    bot = max(t for p, t in band if p >= SEAM + 2 * third)
    assert mid > top and mid > bot, (
        f"the bow is not a bulge: top {top}, mid {mid}, bottom {bot}")


def test_holding_down_flattens_the_bow_and_holding_up_restores_it(tmp_path, flat):
    """The pad axis, driven to BOTH clamps and read in pixels.

    Down to the floor gives a column that is 1.0 on every scanline — every
    patterned row shows the SAME period, which is what "no barrel" means. Up
    from there restores the full bow. Neither direction is inferred from the
    other: each is its own picture.
    """
    counts = {_transitions(flat, pic) for pic in range(SEAM, PICTURE_LINES)}
    counts.discard(0)
    assert len(counts) == 1, (
        f"bow step 0 should give ONE horizontal period on every floor row; "
        f"got {sorted(counts)}")
    flat_period = counts.pop()
    assert abs(flat_period - round(GEN.MB_FLAT / 8)) <= 1

    # ...and back up. Down for 60 frames pins the axis at 0; Up for the next 60
    # walks it back to the clamp at BOW_MAX (9 steps, one per frame held).
    with Machine(str(ROM)) as m:
        m.advance(60, pad1={"down": True})
        m.advance(60, pad1={"up": True})
        out = m.screenshot(str(tmp_path / "restored.png"))
    px = Image.open(out).convert("RGB").load()
    restored = {_transitions(px, pic) for pic in range(SEAM, PICTURE_LINES)}
    restored.discard(0)
    assert len(restored) > 1, "holding Up did not restore a varying bow"
    assert max(restored) > flat_period + 8, (
        f"holding Up restored only {max(restored)} against a flat {flat_period}")


def test_the_bow_step_reaches_the_hdma_index_table_the_dma_controller_fetches(
        tmp_path):
    """The A column's index table is WRAM the DMA controller reads every frame,
    so it is an output region rather than a program variable.

    Three pointers per table, and all three must move together: the head-skip
    unit's, the first span's, and the second span's (which is +127 units).

    BOTH CLAMPS, and the Up one is not the same statement as the Down one. The
    rail boots at the full bow (`scenes/chamber.asm:43-45`), so holding Up asks
    whether the axis STAYS at its maximum: `mb_input` without its `cmp
    #MB_BOW_MAX` would `inc` once per frame and `mb_point` would multiply that
    by the 384-byte stride, so 600 frames of Up would point the A channel some
    230 KB past `bow_a` — through `persp_d` and out of the claim entirely. The
    Down clamp is driven the same way, 60 frames where 8 suffice.
    """
    idx = _sym("ES_MB_IDX")["start"]            # WRAM offset
    bow_base = _sym("ES_R_BOW_A", scene=None)["start"] & 0xFFFF | 0x8000
    stride = (PICTURE_LINES - SEAM) * 2

    def ptrs(pad, frames):
        with Machine(str(ROM)) as m:
            m.advance(frames, pad1=pad) if pad else m.advance(frames)
            b = m.read_bytes(MemoryType.SnesWorkRam, idx, 10)
        return (b[1] | b[2] << 8, b[4] | b[5] << 8, b[7] | b[8] << 8)

    full = ptrs(None, 60)
    zero = ptrs({"down": True}, 60)
    up = ptrs({"up": True}, 600)
    assert full == (bow_base + BOW_MAX * stride, bow_base + BOW_MAX * stride,
                    bow_base + BOW_MAX * stride + 127 * 2), full
    assert zero == (bow_base, bow_base, bow_base + 127 * 2), zero
    assert up == full, (
        f"600 frames of Up left the A pointers at {up}, not at the full bow "
        f"{full} — the Up clamp ran off the end of bow_a")


# =============================================================================
# C2 — the floor UNDULATES: forward, reverse, and the dead stop
# =============================================================================
def _best_shift(a, b, pic0, pic1, rng=28):
    """The vertical offset that best maps picture band [pic0, pic1) of `a` onto
    `b`. Negative = the floor content moved UP the screen."""
    def sig(px, y):
        return [sum(px[x, y]) for x in range(0, 256, 4)]
    best = None
    for s in range(-rng, rng + 1):
        tot = n = 0
        for pic in range(pic0, pic1):
            if not (0 <= pic + s < PICTURE_LINES):
                continue
            u, v = sig(a, png_row(pic)), sig(b, png_row(pic + s))
            tot += sum(abs(p - q) for p, q in zip(u, v))
            n += len(u)
        if n and (best is None or tot / n < best[1]):
            best = (s, tot / n)
    return best


# The roll's own leg cycle, MEASURED on this ROM by tracing the state machine
#: a forward leg of three surges runs to frame ~1595, a 30-frame
# dead stop follows, and the reverse leg runs from ~1625. These are absolute
# frames of a deterministic machine, not sampled guesses.
FRAME_FORWARD = 300
FRAME_HOLD = 1610
FRAME_REVERSE = 2000


@pytest.mark.parametrize("frame,sign,what", [
    (FRAME_FORWARD, -1, "forward"),
    (FRAME_REVERSE, +1, "reverse"),
])
def test_the_floor_rolls_both_ways(tmp_path, frame, sign, what):
    """The whole state cycle's two moving arms, read as MOTION of the rendered
    floor rather than as a position variable.

    One direction alone would lock that direction and ship the other broken —
    which is the exact failure the state-cycle rule exists for."""
    with Machine(str(ROM)) as m:
        m.advance(frame)
        a = Image.open(m.screenshot(str(tmp_path / f"{what}_a.png")))
        m.advance(4)
        b = Image.open(m.screenshot(str(tmp_path / f"{what}_b.png")))
    pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
    for lo, hi in ((SEAM + 8, SEAM + 58), (SEAM + 88, SEAM + 138)):
        shift, _ = _best_shift(pa, pb, lo, hi)
        assert shift != 0, f"{what}: the floor did not move in rows {lo}..{hi}"
        assert (shift > 0) == (sign > 0), (
            f"{what}: rows {lo}..{hi} moved {shift:+d}, expected sign {sign:+d}")


def test_the_dead_stop_between_legs_is_a_true_freeze(tmp_path):
    """The cycle's IDLE arm. `HOLDING` means the pixels do not move — not that
    a velocity word reads zero. Ten frames
    inside the hold must be bit-identical."""
    with Machine(str(ROM)) as m:
        m.advance(FRAME_HOLD)
        a = Image.open(m.screenshot(str(tmp_path / "hold_a.png")))
        m.advance(10)
        b = Image.open(m.screenshot(str(tmp_path / "hold_b.png")))
    pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
    diff = sum(1 for pic in range(PICTURE_LINES) for x in range(256)
               if pa[x, png_row(pic)] != pb[x, png_row(pic)])
    assert diff == 0, f"{diff} pixels moved during the dead stop"


def test_the_roll_is_a_scroll_and_not_a_rotation(boot):
    """C2's "NO rotation matrix" half, as a claim about the PICTURE.

    With the angle held constant M7B and M7C are zero on every line, so
    `VY = D*(SY-224) + M7Y` does not depend on screen X: one scanline samples
    exactly ONE world tile row. The rendered consequence is checkable without
    reading a register — a tile row that is a single flat colour (mortar, rib
    body, rib highlight) renders as a FULL-WIDTH uniform band, and its colour
    is that palette entry plus the line's own fixed-colour addend.

    Under any non-zero heading, C is non-zero, VY varies along the row, and a
    256-px row crosses tile-row boundaries: those bands would slant and stop
    being uniform. So "many full-width uniform rows, each exactly a declared
    flat colour plus its declared vignette" is the no-shear claim, measured.

    (A per-row edge-alignment check would be WRONG here and was tried first:
    two floor rows have DIFFERENT M7A, so their mortar edges land at different
    x — that is the barrel doing its job, not a rotation.)
    """
    vign = GEN.vignette_intensity()
    flats = {name: tuple((c >> 3) for c in rgb) for name, rgb in
             (("mortar", GEN.MORTAR), ("rib", GEN.RIB), ("rib_hi", GEN.RIB_HI))}
    uniform = 0
    for pic in range(SEAM, PICTURE_LINES):
        c = _uniform_colour(boot, pic)
        if c is None:
            continue
        v = vign[pic]
        want = {name: tuple(_expand5(min(31, ch + v)) for ch in base)
                for name, base in flats.items()}
        assert c in want.values(), (
            f"picture row {pic} is uniform {c}, which is none of the three flat "
            f"tile colours under intensity {v} ({want}) — the plane is shearing")
        uniform += 1
    assert uniform >= 60, (
        f"only {uniform} full-width uniform floor rows; a non-rotating plane "
        f"should show one per flat tile row")


# =============================================================================
# C3 — a Mode 1 band above the Mode 7 floor
# =============================================================================
def test_a_clean_mode_1_band_sits_above_the_mode_7_floor(boot):
    """A LAYER-COMPOSITION claim, so it is read off the composited picture and
    not off BGMODE/TM bytes: every picture row above the seam is a single
    colour (the plane's own CGRAM word 0 under an intensity-0 vignette), and
    the first row at the seam carries floor content.

    "Clean, no smear" is the single-colour part: a split that lands late leaves
    Mode 7 pixels in the band, and one that lands early leaves a backdrop row
    inside the floor."""
    pal = (ASSETS / "m7c_pal.bin").read_bytes()
    w0 = pal[0] | pal[1] << 8
    want = (_expand5(w0 & 31), _expand5((w0 >> 5) & 31), _expand5((w0 >> 10) & 31))
    for pic in range(SEAM):
        c = _uniform_colour(boot, pic)
        assert c == want, (
            f"picture row {pic} is {c}, not the plane's backdrop {want} — the "
            f"Mode 1 band is not clean")
    assert _uniform_colour(boot, SEAM) != want or _transitions(boot, SEAM) > 0, \
        "the seam row shows the backdrop — the split lands late"
    floor = {_uniform_colour(boot, pic) for pic in range(SEAM, SEAM + 8)}
    assert floor != {want}, "the first floor rows are still the backdrop"


# =============================================================================
# C4 — the vignette
# =============================================================================
def test_the_vignette_matches_the_declared_intensity_line_for_line(boot):
    """The strongest available read of the COLDATA ramp: a floor row that is
    entirely MORTAR renders one flat colour, and that colour IS the mortar
    palette entry plus the line's fixed-colour addend. So every uniform grey
    floor row reports the vignette's 5-bit intensity for its own scanline.

    This is the whole ramp, not "the middle is brighter": one comparison per
    uniform row against the table the ROM was built from."""
    vign = GEN.vignette_intensity()
    checked = 0
    for pic in range(SEAM, PICTURE_LINES):
        c = _uniform_colour(boot, pic)
        if c is None or not (c[0] == c[1] == c[2]):
            continue                    # a rib row (coloured) or a patterned row
        want = _expand5(MORTAR5 + vign[pic])
        assert c[0] == want, (
            f"picture row {pic}: mortar renders {c[0]}, declared intensity "
            f"{vign[pic]} says {want}")
        checked += 1
    assert checked >= 20, f"only {checked} uniform mortar rows sampled"


def test_the_middle_of_the_frame_is_brighter_than_the_top_and_the_bottom(boot):
    """C4 at its coarsest, over the whole picture rather than per row."""
    def lum(a, b):
        return sum(sum(boot[x, png_row(pic)]) for pic in range(a, b)
                   for x in range(0, 256, 2)) / ((b - a) * 128)
    top, mid, bot = lum(SEAM, SEAM + 48), lum(96, 144), lum(176, 224)
    assert mid > top and mid > bot, f"top {top:.0f} mid {mid:.0f} bottom {bot:.0f}"


# =============================================================================
# The plane itself — destination-region byte tests
# =============================================================================
def test_the_mode_7_region_holds_the_chamber_plane_byte_for_byte():
    """The upload's DESTINATION, read back. A test that only asserted on what
    the floor looks like could pass while the DMA landed a neighbouring blob —
    the failure mode `make rom-unbacked` exists for, one layer down."""
    want = (ASSETS / "m7c_map.bin").read_bytes()
    with Machine(str(ROM)) as m:
        m.advance(60)
        got = m.read_bytes(MemoryType.SnesVideoRam, 0, len(want))
    assert got == want, (
        f"Mode 7 VRAM differs from m7c_map.bin: "
        f"{sum(1 for a, b in zip(got, want) if a != b)} of {len(want)} bytes")


def test_cgram_holds_the_six_absolute_chamber_colours():
    want = (ASSETS / "m7c_pal.bin").read_bytes()
    base = _sym("ES_C_CHAMBER_PAL")["start"]
    assert base == 0, "Mode 7 pins the palette at CGRAM word 0 by hardware contract"
    with Machine(str(ROM)) as m:
        m.advance(60)
        got = m.read_bytes(MemoryType.SnesCgRam, base * 2, len(want))
    assert got == want


def test_the_perspective_column_recedes_monotonically():
    """A GENERATOR INVARIANT, and nothing more — it reads the emitted table,
    not the ROM. Kept because the endpoints and the monotonicity are worth
    pinning at their source, but it is NOT the D column's proof: a linear ramp
    between the same two endpoints satisfies every line below.

    The D column's proof that a ROM produced it is the case beneath this one,
    which reads the picture.
    """
    col = GEN.persp_column()
    assert col[0] == GEN.MB_SCALE_FAR and col[-1] == GEN.MB_SCALE_NEAR
    assert all(a >= b for a, b in zip(col, col[1:])), "the hyperbola is not monotone"


# The floor's tile-row classes repeat with the rib pitch, and the repeat is the
# ruler this measures against: tools/gen_chamber_assets.py::tile_index makes
# world tile row ty%8==0 the rib highlight, ty%8==1 the rib body, the remaining
# EVEN rows full-width mortar, and the remaining odd rows the ashlar checker —
# the only patterned ones. So a floor scanline's class says which world row it
# sampled, to within the 8-px tile.
RIB_PITCH_PX = GEN.RIB_PITCH * GEN.TILE_PX          # 64 world px per rib


def _tile_row_class(ty: int) -> str:
    m = ty % GEN.RIB_PITCH
    if m == 0:
        return "rib_hi"
    if m == 1:
        return "rib"
    return "mortar" if ty % GEN.BLOCK == 0 else "ashlar"


def _observed_classes(px, vign) -> dict:
    """What the PICTURE shows on each floor row. A row of more than one colour
    is the ashlar checker; a uniform one is whichever flat tile colour it
    matches under its own scanline's vignette addend."""
    flats = {name: tuple((c >> 3) for c in rgb) for name, rgb in
             (("mortar", GEN.MORTAR), ("rib", GEN.RIB), ("rib_hi", GEN.RIB_HI))}
    out = {}
    for pic in range(SEAM, PICTURE_LINES):
        c = _uniform_colour(px, pic)
        if c is None:
            out[pic] = "ashlar"
            continue
        v = vign[pic]
        out[pic] = next((name for name, base in flats.items()
                         if tuple(_expand5(min(31, ch + v)) for ch in base) == c),
                        f"unclassifiable{c}")
    return out


def _predicted_classes(col, phase: int) -> dict:
    """What a D column says each floor row samples.

    With B and C zero, Mode 7 maps a whole scanline to ONE world row:
    `VY = (D(SY) * (SY - CY)) >> 8 + M7Y`. `roll_commit`
    (engine/features/m7c_roll/m7c_roll.asm) pins `M7VOFS = M7Y - CH_LINES`, so
    CY is the picture's bottom scanline and the roll's position enters ONLY as
    the additive M7Y — which is why one phase covers it, and why it is taken
    modulo the rib pitch rather than fitted freely.
    """
    out = {}
    for pic in range(SEAM, PICTURE_LINES):
        sy = pic + REAL_Y_BIAS                  # realY is Mesen's _scanline
        world_y = (col[pic - SEAM] * (sy - PICTURE_LINES)) // 256 + phase
        out[pic] = _tile_row_class((world_y // GEN.TILE_PX) % GEN.MAP_T)
    return out


def _best_phase(col, obs):
    """Agreement at the best roll phase — the single free parameter."""
    return max((sum(1 for pic, cls in _predicted_classes(col, ph).items()
                    if cls == obs[pic]), ph)
               for ph in range(RIB_PITCH_PX))


def test_the_rendered_recession_follows_the_declared_perspective_column(boot):
    """THE D COLUMN, READ OFF THE PICTURE — and with no external tree needed.

    The case above pins the emitted table; this one asks whether the ROM's
    second HDMA channel actually streamed it into M7D. Every one of the 192
    floor scanlines is predicted: the declared D value for that row says which
    world tile row the scanline samples, and the four tile classes render as
    four distinguishable things (two brass rows, a grey mortar row, or a
    patterned ashlar row). One free parameter — where the roll has got to,
    which is additive and only matters modulo the 64-px rib pitch.

    WHY IT IS NOT SELF-REFERENTIAL: the prediction comes from the generator,
    the observation comes from the screenshot, and the control below proves the
    agreement is about the hyperbola's SHAPE rather than about its endpoints.
    A straight ramp from MB_SCALE_FAR to MB_SCALE_NEAR — same first row, same
    last row, still monotone, so indistinguishable to the case above — misses
    well over half the floor.
    """
    obs = _observed_classes(boot, GEN.vignette_intensity())
    rows = PICTURE_LINES - SEAM
    bad = [f"{pic}:{cls}" for pic, cls in obs.items() if cls.startswith("un")]
    assert not bad, f"floor rows matching no declared tile colour: {bad[:8]}"

    hits, phase = _best_phase(GEN.persp_column(), obs)
    assert hits >= rows - 6, (
        f"the declared perspective column predicts only {hits} of {rows} floor "
        f"rows (best phase {phase}) — the rendered recession is not the one "
        f"persp_d.bin declares")

    far, near, last = GEN.MB_SCALE_FAR, GEN.MB_SCALE_NEAR, rows - 1
    ramp = [round(far + (near - far) * k / last) for k in range(rows)]
    ramp_hits, _ = _best_phase(ramp, obs)
    assert hits > ramp_hits + 60, (
        f"a LINEAR column between the same endpoints scores {ramp_hits} of "
        f"{rows} against the hyperbola's {hits} — the assertion is not "
        f"distinguishing the recession's shape")


# =============================================================================
# Reference ground truth — skip-if-absent, so a bare runner stays green
# =============================================================================
# An OPTIONAL external tree holding a second, independent implementation of
# this scene, named by `SF_REFERENCE_TREE`. It is read-only and never a build
# dependency: the variable is unset on an ordinary runner, which is why the
# cases below SKIP rather than fail. There is simply nothing to cross-check
# against when no such tree is on disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE = _REFERENCE_TREE
_CHAMBER = REFERENCE / "templates" / "mode7_chamber"
_needs_reference_tree = pytest.mark.skipif(
    not (_CHAMBER / "assets" / "chamber_map.bin").exists(),
    reason="SF_REFERENCE_TREE is unset or holds no chamber assets — an "
           "optional read-only tree, never a build dependency")


@_needs_reference_tree
def test_the_vendored_oracle_still_matches_the_reference():
    """The oracle under vendor/art/ is a COPY of the reference tree's asset,
    and a copy can drift from its original. This is the only case here that
    can see that."""
    for vendored, source in (
            ("ref_chamber_map.bin", "chamber_map.bin"),
            ("ref_chamber_palette.inc", "chamber_palette.inc"),
            ("ref_chamber_tables.inc", "chamber_tables.inc")):
        a = (SUPERFORGE / "vendor" / "art" / "mode7_chamber" / vendored).read_bytes()
        b = (_CHAMBER / "assets" / source).read_bytes()
        assert hashlib.md5(a).hexdigest() == hashlib.md5(b).hexdigest(), vendored


@_needs_reference_tree
def test_the_rendered_recession_matches_the_ref_rom(tmp_path):
    """The asset-import rule's real form (CLAUDE.md): ground-truth against a
    second implementation's RENDER, never against a re-rendering of our own
    converter's output. The reference tree's chamber is assembled READ-ONLY
    into tmp_path (ca65 and ld65 only read; nothing is written back into that
    tree) and run under the same lockstep harness at the same absolute frame.

    The claim is the RECESSION — the sequence of gaps between rib rows down
    the floor — because that is what the perspective endpoints were tuned
    against. The two rolls are independent implementations of the same LFSR
    model, so their world positions agree to a few pixels rather than exactly,
    and comparing gaps rather than absolute rows is what makes the assertion
    about the perspective instead of about that residue.
    """
    obj, sfc = tmp_path / "ref.o", tmp_path / "ref.sfc"
    subprocess.run(
        ["ca65", "--cpu", "65816",
         "-I", "infrastructure/rom_template", "-I", "lib/macros", "-I", "engine",
         "-I", "templates/mode7_chamber/assets",
         "templates/mode7_chamber/main.asm", "-o", str(obj)],
        cwd=REFERENCE, check=True)
    subprocess.run(
        ["ld65", "-C", "infrastructure/rom_template/lorom_64k.cfg",
         str(obj), "-o", str(sfc)], cwd=REFERENCE, check=True)

    def ribs(px):
        lum = [(pic, sum(sum(px[x, png_row(pic)]) for x in range(0, 256, 4)) / 64)
               for pic in range(PICTURE_LINES)]
        peaks = []
        for i in range(2, len(lum) - 2):
            pic, v = lum[i]
            if pic < SEAM + 1:
                continue
            w = [r[1] for r in lum[max(0, i - 10):i + 10]]
            if (v >= lum[i - 2][1] and v >= lum[i + 2][1]
                    and v > (sum(w) / len(w)) * 1.20):
                if not peaks or pic - peaks[-1] > 3:
                    peaks.append(pic)
        return peaks

    shots = {}
    for label, path in (("ref", sfc), ("ours", ROM)):
        with Machine(str(path)) as m:
            m.advance(120)
            shots[label] = Image.open(
                m.screenshot(str(tmp_path / f"{label}.png"))).convert("RGB").load()
    r1, r2 = ribs(shots["ref"]), ribs(shots["ours"])
    g1 = [b - a for a, b in zip(r1, r1[1:])][:4]
    g2 = [b - a for a, b in zip(r2, r2[1:])][:4]
    assert len(g1) >= 4 and len(g2) >= 4, (r1, r2)
    for a, b in zip(g1, g2):
        assert abs(a - b) <= 2, (
            f"the recession disagrees with the source ROM: the reference gaps {g1}, "
            f"superforge gaps {g2} (rib rows {r1} vs {r2})")
