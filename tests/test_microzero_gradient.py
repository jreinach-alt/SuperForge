"""microzero — the rgb_gradient depth wash, built entirely through
the allocator: three COLDATA channels stream the STATIC ROM tables
(tools/gen_gradient.py) and color math ADDs the per-line fixed color to the
Mode-7 floor. The rendered rows are compared EXACTLY against the declared
tables (road-grey pixels recover the tint bit-for-bit, row by row); the HUD
band proves the math does not leak; the allocation report carries the 7-channel
composition; a rogue second claim on an already-owned COLDATA plane refuses
the build. Boot-path uninit detection covers the race transition (the
gradient adds zero RAM state — ROM tables only).
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

VR, CG, WR = MemoryType.SnesVideoRam, MemoryType.SnesCgRam, MemoryType.SnesWorkRam

HUD_LINES = D.world_const("HUD_LINES")   # world.inc is the SSoT


def load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, SUPERFORGE / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _road_rgb5():
    """The road surface colour, straight from the asset generator — the
    oracle SSoT. Re-declaring it here as a literal is how a palette change
    silently desynchronises the tint oracle from the ROM."""
    m = load_tool("gen_m7_assets")
    c = m.palette()[m.ROAD]
    return (c & 31, (c >> 5) & 31, (c >> 10) & 31)


ROAD = _road_rgb5()


def snes_rgb(rgb5):
    return tuple((v << 3) | (v >> 2) for v in rgb5)


def add_clamp(base5, tint5):
    return tuple(min(31, b + t) for b, t in zip(base5, tint5))


@pytest.fixture(scope="module")
def declared():
    """The declared FLOOR tint: per-band-row (R, G, B) 5-bit triples.

    Scanline values, and since a later review the ROM table is these values
    UNROTATED — unit K is visible at scanline K (gen_gradient.channel_values)."""
    g = load_tool("gen_gradient")
    tints = list(zip(*[g.floor_tint(p) for p in range(3)]))
    assert len(tints) == 224 - HUD_LINES
    # the blob the build embeds must BE the declared table (plane bits + ramp)
    blob = g.tables()
    assert blob == bytes(
        plane | v for i, plane in enumerate(g.PLANE)
        for v in g.channel_values(i))
    return tints


@pytest.fixture(scope="module")
def declared_sky():
    """The declared SKY tint, per scanline of the top band."""
    g = load_tool("gen_gradient")
    tints = list(zip(*[g.sky_tint(p) for p in range(3)]))
    assert len(tints) == HUD_LINES
    return tints


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    runner = MesenRunner()

    # LAND ON AN EXACT FRAME, because this module's assertions are
    # screenshot-pixel assertions and the picture depends on WHERE THE TRACK
    # IS. The near rows of this render sit on the black/white start-finish
    # checker (see test_fog_compresses_luminance_with_distance's docstring),
    # so scanline 223 carries white on some landings and not others:
    # test_both_edge_scanlines_carry_their_declared_tint failed with "stray
    # {(255, 255, 255)}" 2 runs in 6 under 10 spinners on 4 cores while
    # passing every time on an idle box. The gradient was never wrong; the
    # frame was a different frame.
    #
    # `boot_to_frame` is that fix, generalised out of this fixture — it
    # free-runs most of the boot (fast, and the slop there is harmless) and
    # steps the last stretch parked (exact). Its docstring carries the
    # measurement.
    runner.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 140,
                         uninit_detection=True)

    D.enter_race(runner, syms)            # fade-out + blank switch + fade-in
    yield runner, jmap
    runner.stop()


@pytest.fixture(scope="module")
def race_shot(booted, tmp_path_factory):
    """The race render + the image row that IS scanline 0.

    Every assertion below then indexes by absolute scanline (image row
    top + S), which is the same coordinate the declared tables are written
    in. Returning "the first floor row" instead was an off-by-one waiting
    to happen — and did happen, the moment the sky covered the seam line
    and moved that landmark by one."""
    from PIL import Image
    runner, _ = booted
    shot = tmp_path_factory.mktemp("grad") / "race.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    # The letterbox border is black; the content span is the 224 visible
    # scanlines. The FIRST NON-BLACK ROW IS SCANLINE 0 — there is no black
    # line inside the content span.
    #
    # This anchor was previously "first non-black row MINUS one", on the
    # belief that scanline 0 rendered black. A later review measured the frame:
    # 224 non-black rows (image rows 7..230) and zero black rows between
    # them. The anchor was pointing at the letterbox border, so every
    # scanline-indexed assertion in this file sampled S-1 — which exactly
    # cancelled the gradient generator's (also wrong) rotate-by-one and left
    # the whole suite green, self-consistent, and one line off ground truth.
    # That is this codebase's own worst-defect class, recurring: a designed
    # pattern agreeing with itself instead of with the hardware.
    #
    # Two earlier landmarks were also invalidated, each by a rendering
    # improvement: (a) "the last all-black row", removed when sky_band's BG2
    # covered the seam line; (b) "the first row whose colours are not the sky
    # band's", removed when the fog made the floor's first rows the same
    # colour as the sky's last. Hence anchoring on the letterbox, which is a
    # property of the harness rather than of the picture.
    return img, D.content_top(img)


def floor_palette(runner):
    return [tuple((c & 31, (c >> 5) & 31, (c >> 10) & 31))
            for c in (runner.read_u16(CG, i * 2) for i in range(17))]


# How many sampled rows must recover the tint from road pixels before the
# start-line checker fills the near view. Not a fixed row number: which row
# the checker reaches depends on the camera pivot and the track width, so a
# hardcoded cut-off silently re-breaks whenever the framing moves. The rows
# that DO carry road are found below; this is the floor on how many of them
# there must be for the recovery to be a real measurement.
MIN_ROAD_ROWS = 8


def test_rowwise_tints_match_declared_table(booted, race_shot, declared):
    """Every sampled floor row renders EXACTLY base+tint for its scanline.
    On the rows where the fog does not saturate, the road surface recovers
    the declared tint bit-for-bit and the untinted road colour is ABSENT
    while the tint is nonzero. Every pixel of every sampled row is
    a declared tinted color (or the untinted backdrop showing through
    transparent index-0 pixels — color math targets BG1 only, by design).
    The checker zone's white/black is tint-saturated/transparent, so the
    tail rows' data walk is witnessed by the ROM access counters instead
    (test_hdma_walks_the_whole_blob)."""
    runner, _ = booted
    img, top = race_shot
    pal = floor_palette(runner)
    w, _ = img.size
    # The tint is only RECOVERABLE from road pixels where the add does not
    # saturate. Near the horizon the fog deliberately DOES saturate — that
    # is what fog is — so those rows are excluded here and asserted instead
    # by test_horizon_fog_saturates_the_far_rows. Rows are selected by the
    # declared table, not by what rendered, so the exclusion cannot quietly
    # swallow a row that should have matched.
    def recoverable(tint):
        return all(b + t <= 31 for b, t in zip(ROAD, tint))

    assert not recoverable(max(declared, key=sum)), \
        "the fog no longer saturates at the horizon — is the haze still on?"
    assert recoverable(declared[-1]), \
        "even the nearest row clamps — the fog covers the whole floor"
    recovered, expected = [], []
    # the player car composites over the floor rows at the pivot line; OBJ
    # palettes 0-3 are exempt from color math by hardware, so its colors
    # render RAW (layer-composition-aware oracle, the layer-composition lesson)
    car_pal = (SUPERFORGE / "build" / "assets" / "car_pal.bin").read_bytes()
    car_colors = {snes_rgb(((c := int.from_bytes(car_pal[i:i + 2], "little"))
                            & 31, (c >> 5) & 31, (c >> 10) & 31))
                  for i in range(2, len(car_pal), 2)}
    # Scanline HUD_LINES IS the first floor line: the TM table's unit 44 is
    # $11 and unit K is visible at scanline K, so sampling starts there.
    # (This loop used to skip i = 0, justified by a comment stating the
    # pre-F2 model — the same refuted belief F2 removed, surviving inside
    # the file F2 rewrote. Removing the skip costs nothing and gains the
    # seam line's coverage; a later review.)
    for i in range(0, 180, 6):
        y = top + HUD_LINES + i
        tint = declared[i]
        allowed = {snes_rgb(add_clamp(b, tint)) for b in pal}
        allowed.add(snes_rgb(pal[0]))     # transparent -> untinted backdrop
        allowed |= car_colors
        row = [img.getpixel((x, y)) for x in range(w)]
        stray = set(row) - allowed
        assert not stray, f"gradient row {i}: undeclared colors {stray}"
        if not recoverable(tint):
            continue                      # fog zone: saturated by design
        tinted_road = snes_rgb(add_clamp(ROAD, tint))
        if tinted_road not in row:
            continue                      # checker/curb zone: no road pixels
        if tint != (0, 0, 0):
            assert snes_rgb(ROAD) not in row, \
                f"gradient row {i}: UNTINTED road present — math dead"
        recovered.append(tuple(
            (c >> 3) - b for c, b in zip(tinted_road, ROAD)))
        expected.append(tint)
    assert len(recovered) >= MIN_ROAD_ROWS, (
        f"only {len(recovered)} sampled rows carried road pixels — the tint "
        f"recovery is not measuring anything")
    assert recovered == expected, "row-wise tint sequence != declared table"
    # The ramp must actually VARY across the sampled zone — a stuck value is
    # a dead data pointer masquerading as "tint present". Stated as the
    # shape the haze claims to have rather than as a distinct-value count:
    # a count is a proxy that a legitimate change to the ramp's amplitude
    # breaks (and that a wrong-but-varying table would pass).
    assert all(a >= b for a, b in zip(recovered, recovered[1:])), \
        f"haze does not fade monotonically toward the camera: {recovered}"
    assert recovered[0] != recovered[-1], \
        f"haze never changes across the sampled zone: {recovered[0]}"


def test_hdma_walks_the_whole_blob(booted):
    """The bus-level witness for the full table walk — head entry, both
    repeat entries, and the terminator: every byte of the gradient
    blob is READ from ROM by the streaming channels each frame (Mesen's
    per-address access counters, armed from power-on by the boot fixture).
    A dead tail pointer or a mis-sized repeat count leaves its byte range
    unread and fails here even where the pixels are tint-insensitive."""
    runner, jmap = booted
    placements = {p["sym"]: p for p in jmap["scenes"]["race"]["placements"]}
    grad = placements["ES_R_GRAD_TABS"]
    rom_off = grad["start"]              # rom-class start = flat ROM offset
    counts = runner.get_access_counts(MemoryType.SnesPrgRom)
    unread = [i for i in range(grad["size"])
              if counts[rom_off + i].ReadCounter == 0]
    assert not unread, \
        f"gradient blob bytes never fetched by HDMA (offsets {unread[:12]}...)"


def test_sky_band_renders_the_declared_gradient(race_shot, declared_sky):
    """The sky band is the declared curve, on screen, scanline by scanline.

    Every scanline of the band must render sky_band's BG2 ramp colours with
    THAT scanline's declared COLDATA tint added — so this fails if the ramp
    is stale, if the tint is stuck (a degenerate HDMA repeat entry holds
    table byte 0 for the whole band and every colour is still 'declared'),
    if the table is off by one, or if colour math stopped reaching BG2.

    Scanline 0 is excluded and asserted separately below: it is a measured,
    documented artifact of the band architecture, not sky."""
    img, top = race_shot
    base = load_tool("gen_sky").RAMP
    white = snes_rgb((31, 31, 31))
    for sl in range(1, HUD_LINES):
        tint = declared_sky[sl]
        want = {snes_rgb(add_clamp(c, tint)) for c in base}
        row = {img.getpixel((x, top + sl)) for x in range(img.size[0])}
        stray = row - want - {white}
        assert not stray, \
            f"sky scanline {sl}: undeclared colours {stray} (declared " \
            f"base+{tint} = {sorted(want)})"
        assert row & want, f"sky scanline {sl}: no declared sky colour at all"
    # the gradient must actually MOVE across the band — a stuck table byte
    # renders 'declared' colours on every line and would pass the loop above
    assert declared_sky[1] != declared_sky[HUD_LINES - 1], \
        "declared sky curve is flat"
    first = {img.getpixel((x, top + 1)) for x in range(img.size[0])}
    last = {img.getpixel((x, top + HUD_LINES - 1)) for x in range(img.size[0])}
    assert not (first - {white}) & (last - {white}), \
        "top and bottom of the sky render the same colours — tint is stuck"


FOG_CONTRAST_RATIO = 2.5         # measured 4.5x; asserted with margin


def test_horizon_fog_saturates_the_far_rows(race_shot, declared):
    """THE fog claim, measured on screen: distance destroys contrast.

    Fog is not "a tint near the horizon" — it is the far rows converging on
    one colour, so the track dissolves into the haze instead of staying
    crisp all the way to the vanishing point. The measurement is the
    luminance SPREAD across a row: additive colour math toward a bright
    fixed colour compresses everything toward it, so a far row's lightest
    and darkest pixels must be much closer together than a near row's.

    Counting distinct colours per row was tried first and rejected — it is
    content-dependent, not fog-dependent: the near rows here sit on the
    black/white start-finish checker and show only two colours, which would
    have read as MORE fog up close."""
    img, top = race_shot

    def spread(sl):
        px = [img.getpixel((x, top + sl)) for x in range(img.size[0])]
        lum = [0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in px]
        return max(lum) - min(lum)

    far = [spread(s) for s in range(HUD_LINES + 1, HUD_LINES + 27)]
    near = [spread(s) for s in range(150, 221)]
    far_mean, near_mean = sum(far) / len(far), sum(near) / len(near)
    assert near_mean > FOG_CONTRAST_RATIO * far_mean, (
        f"no fog: near-field contrast {near_mean:.0f} is only "
        f"{near_mean / max(far_mean, 1e-9):.1f}x the far-field's "
        f"{far_mean:.0f} (want > {FOG_CONTRAST_RATIO}x)")
    # and the haze the far rows converge on is the DECLARED one: at the
    # horizon the tint saturates the road, so those pixels must be at or
    # above what the declared haze puts them at
    horizon_tint = declared[1]
    assert min(horizon_tint) > 20, (
        f"the declared horizon tint {horizon_tint} is too weak to fog "
        f"anything — the test above would pass on geometry alone")


def test_both_edge_scanlines_carry_their_declared_tint(booted, race_shot,
                                                       declared_sky, declared):
    """The two scanlines a table-alignment error lands on FIRST.

    Replaces test_scanline_zero_is_the_known_black_line, which asserted that
    scanline 0 was black. It was a tautology: the fixture defined scanline 0
    as "the row before the first non-black one", so the assertion could only
    ever pass, and it pinned a letterbox border row. The artifact it claimed
    to protect does not exist.

    Three samples, each pinning a different failure:

    * scanline 0 — the sky's first tint. A one-line slip is caught here,
      because tint(0) and tint(1) differ.
    * scanline 223 — the floor's last tint. This one detects the WRAP
      (a rotated table brings the bright sky-top value onto the bottom
      line, which is the bug that shipped) but NOT a small shift: the floor
      curve is flat at zero for the last 79 scanlines, so a slip of up to
      78 lines is invisible here. A later review A2 caught the original docstring
      claiming otherwise.
    * scanline LAST_MOVING — the last line where the floor curve still
      changes. This is where a small shift IS visible, and it is derived
      from the curve rather than hardcoded, so it follows the fog shape."""
    img, top = race_shot
    base_sky = load_tool("gen_sky").RAMP
    white = snes_rgb((31, 31, 31))

    want_top = {snes_rgb(add_clamp(c, declared_sky[0])) for c in base_sky}
    got_top = {img.getpixel((x, top)) for x in range(img.size[0])}
    assert got_top <= want_top | {white}, (
        f"scanline 0 does not carry the sky's first tint {declared_sky[0]}: "
        f"got {got_top - want_top - {white}}, want a subset of {want_top}")

    # The bottom line's tint is the floor curve's last entry — zero, i.e.
    # the floor renders UNTINTED there. tint(0) showing up here is the
    # rotation bug's signature.
    pal = floor_palette(booted[0])
    want_bot = {snes_rgb(add_clamp(c, declared[-1])) for c in pal}
    stray_bot = {img.getpixel((x, top + 223))
                 for x in range(img.size[0])} - want_bot
    sky_top = tuple(load_tool("gen_gradient").scanline_tint(p)[0]
                    for p in range(3))
    assert not stray_bot, (
        f"scanline 223 does not carry the floor's last tint {declared[-1]}: "
        f"stray {stray_bot}. tint(0) = {sky_top} appearing here is the "
        f"signature of a rotated table.")

    # The last band row whose tint differs from its predecessor — past it the
    # fog curve is flat and a shift cannot be seen. Derived, so it tracks the
    # curve's shape instead of freezing today's fog into a constant.
    moving = max(i for i in range(1, len(declared))
                 if declared[i] != declared[i - 1])
    sl = HUD_LINES + moving
    want_mid = {snes_rgb(add_clamp(c, declared[moving])) for c in pal}
    stray_mid = {img.getpixel((x, top + sl))
                 for x in range(img.size[0])} - want_mid
    assert not stray_mid, (
        f"scanline {sl} — the last line where the floor curve still moves — "
        f"does not carry tint {declared[moving]}: stray {stray_mid}. This is "
        f"the sample a SMALL alignment shift shows up in; the bottom-line "
        f"pin above cannot see one.")


def test_hud_text_stays_untinted(race_shot, declared_sky):
    """Leak control: colour math reaches BG2 (the sky) but must NOT reach
    BG3 (the HUD text). The glyphs stay EXACT white on every scanline of
    the band, even where the sky under them is tinted hard toward orange.

    This is the assertion that would catch CGADSUB being widened to $07 or
    $17 — a change that still renders a perfectly plausible sky."""
    img, top = race_shot
    white = snes_rgb((31, 31, 31))
    base = load_tool("gen_sky").RAMP
    glyph_rows = 0
    for sl in range(1, HUD_LINES):
        row = {img.getpixel((x, top + sl)) for x in range(img.size[0])}
        sky_here = {snes_rgb(add_clamp(c, declared_sky[sl])) for c in base}
        if white in row:
            glyph_rows += 1
        # anything that is neither exact white nor a declared sky colour is
        # either tinted text or an undeclared colour
        assert row <= sky_here | {white}, \
            f"band scanline {sl}: text or sky tinted wrong — " \
            f"{row - sky_here - {white}}"
    assert glyph_rows > 4, \
        f"HUD text vanished (white on only {glyph_rows} scanlines)"


def test_channels_and_blob_in_the_map(booted):
    """The composition is declared reality: 7 active channels in the report
    (the shipping composition), three distinct COLDATA plane channels, and the
    grad_tabs ROM claim sized to the generated blob."""
    _, jmap = booted
    report = (SUPERFORGE / "build" / "mz" / "allocation_report.txt").read_text()
    assert "CHANNELS (7/8 used)" in report
    chans = dict(re.findall(r"ch(\d)\s+col([rgb])\s+COLDATA_", report))
    assert sorted(chans.values()) == ["b", "g", "r"], report
    assert len(set(chans.keys())) == 3
    placements = {p["sym"]: p for p in jmap["scenes"]["race"]["placements"]}
    grad = placements["ES_R_GRAD_TABS"]
    # size from the generator, not a literal: the claim and the blob must
    # agree with the tool that produces it
    assert grad["size"] == 3 * load_tool("gen_gradient").TOTAL_LINES
    blob = (SUPERFORGE / "build" / "assets" / "gradient_tabs.bin").read_bytes()
    assert len(blob) == grad["size"]


def test_shipped_blob_honours_the_coldata_plane_partition(booted):
    """Every byte of the shipped table sets ITS plane's bit and no other's.

    The allocator lets colr/colg/colb share $2132 because COLDATA_R/_G/_B are
    declared as disjoint plane masks — the sub-register partition D6 permits
    "only where that partition is real in hardware, or the mask lies". Whether
    it is real is a property of the DATA in the ROM tables, and nothing checked
    the data: a byte with a foreign
    plane bit set would have one channel writing another channel's plane, and
    the three-way sharing proof would be about a partition the ROM does not
    keep. Read from the built artifact, not from the generator, so a hand-edited
    or stale blob fails too.
    """
    g = load_tool("gen_gradient")
    blob = (SUPERFORGE / "build" / "assets" / "gradient_tabs.bin").read_bytes()
    lines = g.TOTAL_LINES
    assert len(blob) == 3 * lines
    for idx, plane in enumerate(g.PLANE):
        seg = blob[idx * lines:(idx + 1) * lines]
        foreign = [(i, b) for i, b in enumerate(seg)
                   if (b & 0xE0) != plane]
        assert not foreign, (
            f"plane {idx} (select ${plane:02X}) has {len(foreign)} byte(s) "
            f"whose plane bits are not exactly ${plane:02X}; first at scanline "
            f"{foreign[0][0]} = ${foreign[0][1]:02X}")


def test_race_boot_path_no_uninitialized_reads(booted):
    """The full title->race path under the power-on detector: contract init
    only, no blanket clears — and the gradient feature adds zero RAM state
    (static ROM tables), so the transition must stay clean."""
    runner, _ = booted
    # 30 frames of the race, PARKED — the `booted` fixture debug_break()s and
    # never resumes, so this module's runner is stopped for its whole life.
    # This used to be run_frames(30), a wall sleep beside a machine that does
    # not advance: the test asserted over ZERO further frames and passed on a
    # frozen emulator. frame_step is the parked-mode way to advance exactly
    # 30, and the claim in the docstring is now actually made.
    runner.frame_step(30)
    runner.assert_no_uninitialized_reads()


def test_rogue_coldata_plane_refuses_the_build(tmp_path, repo_tree_read_lock):
    """The gradient's composition negative: a second feature claiming an
    already-owned COLDATA plane in overlapping scanlines must FAIL the
    allocator — the planes are sub-registers with one owner each."""
    import shutil
    gdir = tmp_path / "game"
    feats = tmp_path / "features"
    # SHARED lock for the copy only: `test_register.py` plants into live
    # `engine/features/*/feature.toml` and a copy taken mid-plant allocates
    # differently than this test expects (a recorded finding).
    with repo_tree_read_lock():
        shutil.copytree(SUPERFORGE / "game" / "microzero", gdir)
        shutil.copytree(SUPERFORGE / "engine" / "features", feats)
    rogue = feats / "rogue_fog"
    rogue.mkdir()
    (rogue / "feature.toml").write_text(
        'name = "rogue_fog"\nrole = "feature"\n[[claims.hdma]]\nregisters = ["COLDATA_B"]\n'
        'band = [100, 200]\nphase = "active"\n')
    gt = (gdir / "game.toml").read_text()
    (gdir / "game.toml").write_text(gt.replace(
        '"rgb_gradient"', '"rgb_gradient", "rogue_fog"'))
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(gdir), "--features-dir", str(feats),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "ALLOCATION FAILED" in r.stderr and "COLDATA_B" in r.stderr
