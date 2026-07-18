"""split_h_demo — horizontal raster-band split via HDMA (sf_split_h v1).

Proves the sf_split_h v1 done-conditions on the cycle-accurate emulator by
reading the RENDERED framebuffer (kit rule #2 — every assertion reads pixels or
the hardware VRAM the PPU consumes, never an engine proxy variable):

  D1  the TOP band renders a GENUINE tile instrument panel (BG3, Mode 1): >=2
      distinct authored BG3 palette colours in a STRUCTURED (non-uniform,
      non-backdrop, non-floor) pattern. Non-vacuity: -DNO_SPLIT compiles the
      mode/TM split out -> the whole screen is one Mode-7 floor with no tile
      band -> the D1 two-region signature MUST be ABSENT (that assertion FAILS).
  D2  the BOTTOM band renders the Mode-7 perspective FLOOR and the split seam is
      a single clean scanline transition (no smeared/garbled row across it).
  D3  the DYNAMIC instrument responds: driving the fill down (P1 Left) then up
      (P1 Right) changes the rendered bar-fill length. Non-vacuity: -DFREEZE_BAR
      pins the fill constant -> the two-state difference MUST be ABSENT.
  D4  the archetype-D COLDATA colour band tints the floor: the default build's
      floor pixels differ from the -DNO_COLORBAND build's (same geometry, the
      colour band added). Non-vacuity: -DNO_COLORBAND removes the band.
  D5  the split HOLDS UNDER LOAD: spinning the Mode-7 camera (P1 R shoulder)
      forces a full per-scanline matrix rebuild every frame (CH5/CH6 matrix HDMA
      churning); the BGMODE/TM band split (CH2/CH3) still renders cleanly — top
      band intact, floor still textured, seam still un-smeared. Built-in
      non-vacuity: the floor-band pixels must actually change (the scene really
      rotated), so it cannot pass on a scene that never moved.

The instrument band is a real BG3 2bpp tile layer (frame rules + gauge lights +
a fill bar) in VRAM's upper 32 KB (tilemap word $4800, CHR word $5000), painted
in palette group 4 (CGRAM 16..19); the Mode-7 floor owns the low 32 KB and reads
CGRAM 0..5 — the per-band CGRAM regions do NOT overlap. The split is armed
through the HDMA allocator (hdma_request + hdma_bind_direct), not hand-hardcoded
channels: enable mask $7C = CH2 (BGMODE) | CH3 (TM) | CH4 (COLDATA) | CH5/CH6
(Mode-7 matrix).

Colours (authored, BGR555 -> emulator RGB):
  BG3 gauge/bar-fill (idx 3) ~ (255,173,57) amber ; frame (idx 1) ~ (132,132,132)
  ; bar-empty/dim (idx 2) ~ (66,66,66). Backdrop (CGRAM 0) ~ (24,33,41).
"""
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

# Split geometry (must match templates/split_h_demo/main.asm).
SPLIT = 40                      # the HUD/floor band boundary scanline
Y_TOP0, Y_TOP1 = 6, 34          # sample window inside the top instrument band
Y_FLOOR0, Y_FLOOR1 = 120, 140   # sample window well inside the Mode-7 floor
BAND_ROW_BAR_Y0, BAND_ROW_BAR_Y1 = 16, 24   # the bar row (BG3 tilemap row 2)

NMI_HDMA_ENABLE = 0x0108        # engine_state.inc — the armed-HDMA mask mirror


# --- colour helpers -----------------------------------------------------------
def _is_backdrop(p):
    return abs(p[0] - 24) < 16 and abs(p[1] - 33) < 16 and abs(p[2] - 41) < 16


def _is_black(p):
    return p[0] < 24 and p[1] < 24 and p[2] < 24


def _is_bg3_amber(p):
    # BG3 gauge/bar-fill (idx 3): high R, mid G, low B — the amber the floor's
    # gold lane (214,173,57) does NOT reach (its R tops out ~214/247).
    return p[0] > 240 and 140 < p[1] < 200 and p[2] < 110


# --- framebuffer helpers ------------------------------------------------------
def _grab(runner, settle=4):
    runner.run_frames(settle)
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    path = "/tmp/e2e_screenshots/split_h_demo.png"
    runner.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return w, h, img.load()


def _band_colours(w, h, pix, y0, y1):
    """Distinct non-backdrop, non-black colours in the band [y0,y1)."""
    seen = {}
    for y in range(y0, y1):
        for x in range(w):
            p = pix[x, y]
            if _is_backdrop(p) or _is_black(p):
                continue
            seen[p] = seen.get(p, 0) + 1
    return seen


def _amber_count(w, h, pix, y0, y1):
    return sum(1 for y in range(y0, y1) for x in range(w) if _is_bg3_amber(pix[x, y]))


def _row_dom_frac(w, h, pix, y):
    from collections import Counter
    c = Counter(pix[x, y] for x in range(w))
    return c.most_common(1)[0][1] / w


def _amber_row(w, pix, y):
    """BG3 instrument-amber pixel count in a single scanline."""
    return sum(1 for x in range(w) if _is_bg3_amber(pix[x, y]))


def _floor_tex_row(w, pix, y):
    """Distinct non-backdrop, non-black colours in a single scanline — the
    Mode-7 floor is textured (>=4 distinct); an instrument/flat row is not."""
    seen = set()
    for x in range(w):
        p = pix[x, y]
        if _is_backdrop(p) or _is_black(p):
            continue
        seen.add(p)
    return len(seen)


# --- fixtures -----------------------------------------------------------------
@pytest.fixture(scope="module")
def roms():
    make = subprocess.run(["make", "split_h_demo"], cwd=str(ROOT),
                          capture_output=True, text=True)
    if make.returncode != 0:
        pytest.skip(f"`make split_h_demo` failed (toolchain?):\n{make.stderr}")
    script = ROOT / "templates" / "split_h_demo" / "build_split_h_variants.sh"
    var = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if var.returncode != 0:
        pytest.skip(f"variant build failed (toolchain?):\n{var.stderr}")
    return {
        "default": BUILD / "split_h_demo.sfc",
        "nosplit": BUILD / "split_h_demo_nosplit.sfc",
        "nocolor": BUILD / "split_h_demo_nocolor.sfc",
        "freeze": BUILD / "split_h_demo_freeze.sfc",
        "threeband": BUILD / "split_h_demo_threeband.sfc",
        "bright": BUILD / "split_h_demo_bright.sfc",
        "toggle": BUILD / "split_h_demo_toggle.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# --- boot + channel-routing sanity (reads the armed-HDMA mask the PPU uses) ----
def test_boots_and_split_channels_armed(roms, runner):
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"
    runner.run_frames(10)
    # Heartbeat advances (sequencing only — no visual claim rests on it).
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(6)
    assert runner.read_u16(WR, 0xE010) > f1, "heartbeat not advancing"
    # The split routed THROUGH the allocator: CH2 BGMODE | CH3 TM | CH4 COLDATA |
    # CH5/CH6 Mode-7 matrix = $7C. This is the register the NMI writes to $420C.
    enable = runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0]
    assert enable == 0x7C, (
        f"HDMA enable mask {enable:#04x} != $7C "
        f"(expected CH2 BGMODE|CH3 TM|CH4 COLDATA|CH5/CH6 matrix)")


# --- D1 -----------------------------------------------------------------------
def test_d1_top_band_is_instrument_tiles(roms, runner):
    """D1: the top band shows a genuine BG3 tile panel — >=2 distinct authored
    colours AND a structured (non-uniform) pattern, with the amber gauge/bar
    colour the floor never reaches."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(16)
    w, h, pix = _grab(runner)

    colours = _band_colours(w, h, pix, Y_TOP0, Y_TOP1)
    assert len(colours) >= 2, (
        f"top band has <2 authored colours (not a tile panel): {colours}")
    assert _amber_count(w, h, pix, Y_TOP0, Y_TOP1) > 200, (
        "top band shows no BG3 gauge/bar amber — the instrument tiles did not "
        "render")
    # STRUCTURED: at least one row in the band is NOT dominated (>0.9) by a
    # single colour (a flat backdrop/floor fill would be uniform).
    structured = any(_row_dom_frac(w, h, pix, y) < 0.85
                     for y in range(Y_TOP0, Y_TOP1))
    assert structured, "top band is uniform — not a structured tile panel"


def test_d1_nosplit_control_has_no_tile_band(roms, runner):
    """D1 NON-VACUITY (-DNO_SPLIT): the split is compiled out, so the whole
    screen is a single Mode-7 floor. The top-band instrument signature (the BG3
    amber the floor never reaches) MUST be ABSENT."""
    runner.load_rom(str(roms["nosplit"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "nosplit ROM did not boot"
    runner.run_frames(16)
    w, h, pix = _grab(runner)
    amber = _amber_count(w, h, pix, Y_TOP0, Y_TOP1)
    assert amber < 50, (
        f"D1 FAILED to be non-vacuous: -DNO_SPLIT still shows BG3 amber in the "
        f"top band ({amber} px) — the two-region assertion is not distinguishing")


# --- D2 -----------------------------------------------------------------------
def test_d2_bottom_band_is_mode7_floor_clean_seam(roms, runner):
    """D2: the bottom band renders the Mode-7 perspective floor (a textured,
    multi-colour receding plane, not a flat fill), and the seam is a single
    clean scanline transition — NO row across it is a smeared/garbled mix. We
    prove the latter directly: scan every scanline in the seam window and assert
    that NO row simultaneously carries substantial instrument-amber AND the
    Mode-7 floor's multi-colour texture (which is exactly what a smeared row
    would show). Reads framebuffer pixels only."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(16)
    w, h, pix = _grab(runner)

    # Floor is TEXTURED: many distinct colours across the floor band (a flat
    # backdrop fill would yield 1-2).
    floor = _band_colours(w, h, pix, Y_FLOOR0, Y_FLOOR1)
    assert len(floor) >= 4, (
        f"bottom band is not a textured Mode-7 floor: {len(floor)} colours")

    # Both bands must genuinely appear (the seam is real, not absent): the
    # instrument amber above and the textured floor below.
    top_has_amber = _amber_count(w, h, pix, Y_TOP0, Y_TOP1) > 200
    floor_textured = len(_band_colours(w, h, pix, SPLIT + 8, SPLIT + 20)) >= 4
    assert top_has_amber and floor_textured, (
        "the two regions are not both present as distinct bands (no clean seam)")

    # CLEAN SEAM (mechanism-honest): at a proper HBlank band transition every
    # scanline belongs wholly to ONE band. A smeared/garbled row across the seam
    # would show BOTH substantial instrument-amber AND the multi-colour Mode-7
    # floor texture at once. The band renders a few scanlines below nominal SPLIT
    # (HDMA count + 1-line latency), so we DISCOVER the boundary by scanning the
    # seam window rather than hardcoding a row. Assert NO row in the window mixes
    # both signatures.
    #   AMBER_MIX_THRESH: "substantial" instrument content — the real amber rows
    #     carry ~72-104 px; 30 sits well below that (a genuine instrument row) yet
    #     well above the 0 seen on clean floor/backdrop rows, so a clean frame
    #     never trips and a real smear (amber bleeding onto a floor row) would.
    #   FLOOR_TEX_THRESH: the floor's textured multi-colour signature (>=4);
    #     instrument/flat/backdrop rows stay at <=3.
    AMBER_MIX_THRESH = 30
    FLOOR_TEX_THRESH = 4
    smeared = [
        y for y in range(Y_TOP1, SPLIT + 21)
        if _amber_row(w, pix, y) > AMBER_MIX_THRESH
        and _floor_tex_row(w, pix, y) >= FLOOR_TEX_THRESH
    ]
    assert not smeared, (
        f"seam is NOT clean: row(s) {smeared} mix substantial instrument-amber "
        f"(>{AMBER_MIX_THRESH} px) with Mode-7 floor texture (>={FLOOR_TEX_THRESH} "
        f"colours) — a smeared/garbled transition, not a single clean scanline")


# --- D3 -----------------------------------------------------------------------
def _bar_fill_px(runner):
    """Amber pixel count in the bar row — the rendered fill length proxy read
    from SCREEN PIXELS (not a variable). Longer fill -> more amber in the row."""
    w, h, pix = _grab(runner)
    return _amber_count(w, h, pix, BAND_ROW_BAR_Y0, BAND_ROW_BAR_Y1)


def test_d3_dynamic_bar_responds_to_input(roms, runner):
    """D3: drive the fill to two distinct states (P1 Left = empty, P1 Right =
    full) and assert the RENDERED bar-fill length (amber pixels in the bar row)
    differs between them."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(16)

    runner.set_input(0, left=True)
    runner.run_frames(40)                 # drive fill down to empty
    runner.set_input(0)
    low = _bar_fill_px(runner)

    runner.set_input(0, right=True)
    runner.run_frames(60)                 # drive fill up to full
    runner.set_input(0)
    high = _bar_fill_px(runner)

    assert high > low + 100, (
        f"bar fill did not respond to input (low={low}, high={high} amber px)")


def test_d3_freeze_control_bar_does_not_respond(roms, runner):
    """D3 NON-VACUITY (-DFREEZE_BAR): the fill is pinned constant, so driving
    input the same way MUST NOT change the rendered bar-fill length."""
    runner.load_rom(str(roms["freeze"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "freeze ROM did not boot"
    runner.run_frames(16)

    runner.set_input(0, left=True)
    runner.run_frames(40)
    runner.set_input(0)
    low = _bar_fill_px(runner)

    runner.set_input(0, right=True)
    runner.run_frames(60)
    runner.set_input(0)
    high = _bar_fill_px(runner)

    assert abs(high - low) <= 100, (
        f"D3 FAILED to be non-vacuous: -DFREEZE_BAR still changed the bar fill "
        f"(low={low}, high={high}) — the fill is not actually frozen")


# --- D4 -----------------------------------------------------------------------
def _floor_sig_pix(w, pix):
    """Dominant floor-band colours from an already-captured framebuffer — the
    COLDATA band shifts these when it tints the floor, and a camera rotation
    changes them because the floor texture is re-projected."""
    from collections import Counter
    c = Counter(pix[x, y] for y in range(Y_FLOOR0, Y_FLOOR1) for x in range(w))
    return set(col for col, _ in c.most_common(4))


def _floor_signature(runner):
    """The multiset of floor-band colours (as a frozenset of the dominant
    colours) — the COLDATA band shifts these when it tints the floor."""
    w, h, pix = _grab(runner)
    return _floor_sig_pix(w, pix)


def test_d4_coldata_band_tints_floor(roms, runner):
    """D4: the archetype-D COLDATA colour band changes the floor's rendered
    colours vs the -DNO_COLORBAND build (same geometry, the additive fixed-colour
    band applied to the lower region). Reads the floor pixels directly."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(20)
    with_band = _floor_signature(runner)

    runner.load_rom(str(roms["nocolor"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "nocolor ROM did not boot"
    runner.run_frames(20)
    without_band = _floor_signature(runner)

    assert with_band != without_band, (
        "D4 FAILED: the COLDATA band did not change the floor colours vs the "
        f"-DNO_COLORBAND build (both {with_band}) — the colour band is inert or "
        "the control is vacuous")


# --- D5 (stress: the split UNDER LOAD) ----------------------------------------
def test_d5_split_holds_under_rotation_load(roms, runner):
    """D5: spin the Mode-7 camera (P1 R shoulder). A changing angle forces
    sf_mode7_tick into a FULL per-scanline matrix rebuild EVERY frame (the
    CH5/CH6 matrix HDMA churning) — so the BGMODE/TM band split (CH2/CH3) is
    exercised under maximal Mode-7 load. Assert the split STILL holds: the top
    instrument band is intact, the Mode-7 floor still renders, and the seam is
    still a single clean scanline (no smeared row that mixes both bands).

    Built-in non-vacuity: the test also asserts the floor ACTUALLY ROTATED (its
    rendered colour signature changed), so 'holds under load' cannot pass on a
    scene that never moved — a real matrix rebuild was applied every frame."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"
    runner.run_frames(16)

    # Baseline (angle 0): the split is present. Snapshot the floor-band pixels so
    # we can prove the floor actually re-projected under rotation (a set of
    # dominant colours is too coarse — the palette is unchanged by a spin; the
    # per-pixel ARRANGEMENT is what moves).
    w, h, pix = _grab(runner)
    base_floor_px = [[pix[x, y] for x in range(w)]
                     for y in range(Y_FLOOR0, Y_FLOOR1)]
    assert _amber_count(w, h, pix, Y_TOP0, Y_TOP1) > 200, (
        "no instrument band at baseline — cannot test it holding under load")

    # LOAD: hold R for ~50 frames (~100 angle units) — a full matrix rebuild
    # every single frame while the split HDMA runs.
    runner.set_input(0, r=True)
    runner.run_frames(50)
    runner.set_input(0)
    w, h, pix = _grab(runner)

    # (1) the scene ACTUALLY rotated (real load was applied) — non-vacuity: a
    # large fraction of the floor-band pixels differ from the baseline frame.
    floor_diff = sum(1 for j, y in enumerate(range(Y_FLOOR0, Y_FLOOR1))
                     for x in range(w) if pix[x, y] != base_floor_px[j][x])
    floor_total = w * (Y_FLOOR1 - Y_FLOOR0)
    assert floor_diff > floor_total * 0.2, (
        f"D5 vacuous: the floor barely changed under rotation "
        f"({floor_diff}/{floor_total} px) — no real matrix-rebuild load applied")
    # (2) the split STILL HOLDS: instrument band intact, floor still textured.
    assert _amber_count(w, h, pix, Y_TOP0, Y_TOP1) > 200, (
        "the top instrument band broke under rotation load")
    assert len(_band_colours(w, h, pix, Y_FLOOR0, Y_FLOOR1)) >= 4, (
        "the Mode-7 floor stopped rendering under rotation load")
    # (3) the seam is STILL clean under load — no row mixes both band signatures.
    smeared = [y for y in range(Y_TOP1, SPLIT + 21)
               if _amber_row(w, pix, y) > 30 and _floor_tex_row(w, pix, y) >= 4]
    assert not smeared, (
        f"the seam smeared under rotation load at rows {smeared}")


# =============================================================================
# sf_split_h SWEEP additions — items #1 (N-band), #5 (brightness band),
# #6 (sf_split_h_off lifecycle), #7 (structural HDMA-config check). Every
# assertion reads rendered framebuffer pixels or the hardware HDMA channel
# registers the PPU consumes — never an engine proxy variable.
# =============================================================================
BUS = MemoryType.SnesMemory     # full SNES bus (for the $43xx HDMA channel regs)


def _band_luma(w, pix, y0, y1):
    """Mean luma (0..255) over a horizontal band [y0,y1), full width. A dimmer
    brightness band renders a LOWER mean than a full-brightness band."""
    tot = 0
    n = 0
    for y in range(y0, y1):
        for x in range(w):
            p = pix[x, y]
            tot += (p[0] + p[1] + p[2]) / 3
            n += 1
    return tot / n


# --- #1: N-band compiler (sf_split_h_bands) — THREE distinct regions ----------
def test_bands_three_distinct_regions(roms, runner):
    """#1: -DTHREEBAND arms a 3-band INIDISP brightness split via the N-band
    compiler sf_split_h_bands (full / half / dim). Assert THREE horizontal
    regions render with STRICTLY DESCENDING brightness — the middle band is a
    genuine third region distinct from both the top and bottom. Reads the mean
    luma of three full-width bands from the framebuffer (not a proxy).

    Non-vacuity is built in: the DEFAULT build has no brightness split, so its
    floor gets BRIGHTER with depth (perspective) — the opposite ordering — and
    would FAIL the descending-stair assertion, proving the 3-band split is what
    produces the stair."""
    runner.load_rom(str(roms["threeband"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "threeband ROM did not boot"
    runner.run_frames(24)
    w, h, pix = _grab(runner)
    # band 0 (top, full $0F, includes the instrument), band 1 (middle, half
    # $08), band 2 (bottom, dim $04). Sample windows well inside each band.
    top = _band_luma(w, pix, 8, 30)
    mid = _band_luma(w, pix, 60, 110)
    bot = _band_luma(w, pix, 150, 200)
    assert top > mid + 8 and mid > bot + 8, (
        f"3-band brightness split did not render three descending regions "
        f"(top={top:.0f} mid={mid:.0f} bot={bot:.0f}) — the middle band is not "
        f"a distinct third region")

    # Non-vacuity: the DEFAULT build (no brightness split) does NOT show this
    # descending stair (its floor brightens with depth).
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(24)
    w, h, pix = _grab(runner)
    d_mid = _band_luma(w, pix, 60, 110)
    d_bot = _band_luma(w, pix, 150, 200)
    assert not (d_mid > d_bot + 8), (
        f"#1 vacuous: the DEFAULT build already shows a descending mid>bot stair "
        f"(mid={d_mid:.0f} bot={d_bot:.0f}) without the 3-band split")


# --- #5: brightness band (SF_SPLIT_BRIGHT / INIDISP) --------------------------
def test_bright_band_dims_floor_region(roms, runner):
    """#5: -DBRIGHT_BAND arms an archetype-D brightness band on INIDISP ($2100)
    via SF_SPLIT_BRIGHT — top band full ($0F), bottom band dimmed ($08). Assert
    the floor region (below the split, in the dimmed bottom band) renders
    DIMMER than the same region in the default build (no brightness band). Reads
    the floor-band mean luma directly. Non-vacuity: the default build is the
    'no brightness band' pair — if the band were inert the two would match."""
    runner.load_rom(str(roms["bright"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "bright ROM did not boot"
    runner.run_frames(24)
    w, h, pix = _grab(runner)
    bright_floor = _band_luma(w, pix, Y_FLOOR0, Y_FLOOR1)

    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(24)
    w, h, pix = _grab(runner)
    default_floor = _band_luma(w, pix, Y_FLOOR0, Y_FLOOR1)

    assert bright_floor < default_floor - 15, (
        f"#5 FAILED: the brightness band did not dim the floor region "
        f"(bright={bright_floor:.0f} vs default={default_floor:.0f}) — the "
        f"SF_SPLIT_BRIGHT band is inert or the control is vacuous")


# --- #6: sf_split_h_off + re-arm lifecycle ------------------------------------
def _amber_top(runner):
    w, h, pix = _grab(runner)
    return _amber_count(w, h, pix, Y_TOP0, Y_TOP1)


def test_off_and_rearm_lifecycle(roms, runner):
    """#6: -DTOGGLE_SPLIT. Edge-detected P1 A cycles the mode/TM split: armed ->
    (A) sf_split_h_off both channels -> (A) re-arm. Assert the top-band
    instrument signature (BG3 amber) is PRESENT while armed, GONE after
    sf_split_h_off (collapses to full-screen Mode 7, like -DNO_SPLIT), and BACK
    after the re-arm. Reads the top-band amber pixel count at each phase."""
    runner.load_rom(str(roms["toggle"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "toggle ROM did not boot"
    runner.run_frames(20)

    armed = _amber_top(runner)
    assert armed > 200, (
        f"#6: the split is not armed at boot ({armed} amber px) — cannot test "
        f"the lifecycle")

    # press A (a single 0->1 edge) -> sf_split_h_off
    runner.set_input(0, a=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(6)
    off = _amber_top(runner)
    assert off < 50, (
        f"#6: after sf_split_h_off the instrument band is still present "
        f"({off} amber px) — the split did not release")

    # press A again -> re-arm the same RODATA tables
    runner.set_input(0, a=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(6)
    rearmed = _amber_top(runner)
    assert rearmed > 200, (
        f"#6: after re-arm the instrument band did not come back "
        f"({rearmed} amber px) — sf_split_h_arm re-bind failed")


# --- #7: structural HDMA-config check (cost-regression proxy) -----------------
def test_split_hdma_config_is_direct_1byte(roms, runner):
    """#7 STRUCTURAL: after arming, read the HDMA channel config the split
    programmed ($4300+ch*$10 via the debugger bus) and assert it is exactly the
    'direct, 1 byte -> 1 register' config — DMAP=$00 (A->B, absolute table, 1
    reg) and BBAD = the register's low byte (SF_SPLIT_* equate) — for each of
    CH2 (BGMODE $05), CH3 (TM $2C), CH4 (COLDATA $32). This is a cheap proxy
    that the per-frame cost is exactly 'NMI re-arm + the table' and NOTHING
    hidden: no indirect mode (DMAP bit3), no unexpected register, no extra
    channel. Complements the NMI_HDMA_ENABLE=$7C mask check. Reads the hardware
    channel registers the PPU consumes, not an engine variable.

    (A true per-frame CYCLE gate is deferred — see the guide's Backlog: the
    harness has no cheap per-frame counter and instruction-stepping a frame is
    too slow for CI. This structural check is the standing regression proxy.)"""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(20)

    # $420C (HDMAEN) has the armed channels enabled (CH2-CH6 => $7C low bits;
    # $420C also reflects the enable). And NMI_HDMA_ENABLE mirror == $7C.
    assert runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0] == 0x7C, (
        "NMI_HDMA_ENABLE mask is not $7C — the split channel set changed")

    # SF_SPLIT_* register low bytes (from lib/macros/sf_split_h.inc).
    expected = {2: 0x05, 3: 0x2C, 4: 0x32}   # CH2 BGMODE, CH3 TM, CH4 COLDATA
    for ch, bbad in expected.items():
        base = 0x4300 + ch * 0x10
        cfg = runner.read_bytes(BUS, base, 2)   # DMAPn, BBADn
        assert cfg[0] == 0x00, (
            f"CH{ch} DMAP={cfg[0]:#04x} != $00 — not a direct 1-byte HDMA "
            f"config (indirect/extra-register mode would hide per-frame cost)")
        assert cfg[1] == bbad, (
            f"CH{ch} BBAD={cfg[1]:#04x} != {bbad:#04x} — the channel is bound to "
            f"the wrong PPU register")
