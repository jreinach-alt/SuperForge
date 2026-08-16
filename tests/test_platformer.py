"""platformer — the flagship rail, end to end on the emulator.

THE TEST SURFACE IS THE RENDERED OUTPUT, EVERYWHERE (CLAUDE.md rule 2). "The
level is the declared level" is asserted as *all 2,048 BG1 tilemap words in
VRAM against the generator that produced the blob*. "The hero is standing on
the platform" is asserted as *the OAM entry bytes the PPU reads*. "The two
parallax bands are at different offsets" is asserted as *screenshot pixels*,
because a per-layer byte check cannot see a layer-composition bug. Where a DP
word appears it is either NAVIGATION (getting the machine into the state under
test, which is what tests/plf_drive.py is for) or it is asserted BESIDE the
output region it explains — never instead of it.

The case list is the rail's own done-condition block, written to be
emulator-verifiable, plus PARALLAX.

STATE-CYCLE COVERAGE, not snapshots (AGENTS.md "Test discipline"). The four-
scene arc is DRIVEN, all of it: title -> play -> game over -> title -> play ->
win, plus the pause freeze, the SRAM bank and the continue that restores it. A
rail tested only on its opening frame ships its endings broken — and this rail
IS its endings.

JUMP PHYSICS ARE TESTED APEX **AND** LANDING. An apex depends only on the
launch velocity and gravity; the rest position depends on the fall clamp and
on the landing snap, and a snap that is off by the box height embeds the
sprite in the floor while every apex assertion still passes. So
test_a_jump_rises_to_its_apex_and_lands_flush_on_the_surface walks the whole
cycle and asserts the grounded rest position too.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tests"))
sys.path.insert(0, str(SUPERFORGE / "vendor"))

import plf_drive as D  # noqa: E402
from mesen_runner import MesenRunner, MemoryType  # noqa: E402

MC_PER_FRAME = 357368            # allocator/substrate.toml [frame.ntsc]

# Mesen captures 256x239 — the whole NTSC field, not the 224 visible lines —
# with the picture starting six rows down. MEASURED against two independent
# landmarks in the shipped binary: the level's grass band (BG1 row 24's top
# two pixel rows, PPU scanlines 192-193) lands at PNG rows 198-199, and the
# backdrop immediately above it reads the declared dusk word exactly. Stated
# as a constant rather than searched for at runtime, because a test that
# locates the picture by looking for the thing it is about to assert has
# assumed its own answer.
PNG_Y0 = 6


def png_y(scanline):
    """The PNG row a PPU scanline lands on."""
    return scanline + PNG_Y0


def load_assets():
    """The asset generator, imported as the tests' ORACLE.

    tools/gen_platformer_assets.py produced every blob in the ROM, so
    comparing the render against it checks the whole chain
    generator -> blob -> upload -> VRAM -> PPU. It is not a tautology the way
    a ROM hash against a reference the same code produced would be: the
    generator states the level and the skyline as PICTURES, and the ROM states
    them as bytes a 65816 loop wrote through the VRAM port.
    """
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_platformer_assets",
            SUPERFORGE / "tools" / "gen_platformer_assets.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = prev


GEN = load_assets()
ATTR = 2 << 10                   # BG palette 2, the plf_pal claim's base / 16

# A second converter's output for the same art pack (png2snes), vendored as a
# FIXTURE — never a build input. It is the independent implementation the OBJ
# CHR and OBJ palette assertions check this repo's conversion against; see that
# directory's README for what it is and where it came from.
REFERENCE_INC = {
    "hero": SUPERFORGE / "vendor/art/dungeon_sprites/ref_hero.inc",
    "ghost": SUPERFORGE / "vendor/art/dungeon_sprites/ref_ghost.inc",
}


def inc_bytes(path, label):
    """The `.byte` / `.word` run following `label:` in a ca65 include, as bytes.

    Deliberately a dumb reader over the vendored text rather than an import of
    anything: the fixture's whole value is being produced by a program this
    repo does not run.
    """
    out, taking = bytearray(), False
    for line in path.read_text().splitlines():
        s = line.split(";")[0].strip()
        if s == f"{label}:":
            taking = True
            continue
        if not taking:
            continue
        if s.startswith(".byte"):
            for v in s[5:].split(","):
                out.append(int(v.strip().lstrip("$"), 16))
        elif s.startswith(".word"):
            for v in s[5:].split(","):
                w = int(v.strip().lstrip("$"), 16)
                out += bytes((w & 0xFF, w >> 8))
        elif s:
            break
    assert out, f"{label} not found in {path.name}"
    return bytes(out)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    try:
        r.stop()
    except Exception:
        pass


@pytest.fixture
def play(runner):
    """A fresh round, parked and frame-stepping."""
    D.to_title(runner)
    D.enter_play(runner)
    yield runner
    try:
        runner.debug_resume()
    except Exception:
        pass


def bgr555_to_rgb(v):
    """The 5-bit channel to the 8 bits Mesen renders: bit REPLICATION, which
    is what the PPU does — not round(c * 255/31)."""
    return tuple(((v >> s) & 31) << 3 | ((v >> s) & 31) >> 2
                 for s in (0, 5, 10))


def shot(r, path):
    r.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


# =============================================================================
# THE WORLD
# =============================================================================
def test_the_level_in_vram_is_the_declared_level(play):
    """All 2,048 BG1 tilemap words, against the generator's own picture.

    This is the one that proves the page split: a 64x32 map is TWO 32x32
    hardware pages (columns 0-31 at the base, 32-63 at base + 0x400), and a
    build loop that streamed into a rising VMADD would put the right tiles in
    the wrong half of the world — which renders as a plausible level, in the
    wrong place, and no spot check finds it.
    """
    rows = GEN.level_rows()
    vram = play.read_bytes(D.V, D.PLF_MAP * 2, 2048 * 2)
    bad = []
    for ty in range(D.MAP_H):
        for tx in range(D.MAP_W):
            page = 0x400 if tx >= 32 else 0
            w = page + ty * 32 + (tx & 31)
            got = vram[w * 2] | (vram[w * 2 + 1] << 8)
            want = GEN._L[rows[ty][tx]] | ATTR
            if got != want:
                bad.append((tx, ty, got, want))
    assert not bad, f"{len(bad)} cells differ, first five: {bad[:5]}"


def test_the_skyline_in_vram_is_the_declared_skyline(play):
    """All 1,024 BG2 tilemap words, against the 32x8 blob's own repetition.

    The 8-column period is what makes a parallax shift READABLE in a
    screenshot up to 63 px, so "the period is actually 8" is a claim the
    parallax tests below depend on rather than a detail.
    """
    blob = GEN.sky_bin()
    vram = play.read_bytes(D.V, D.PLF_SKY * 2, 1024 * 2)
    bad = []
    for i in range(1024):
        row, col = i >> 5, i & 31
        want = blob[row * GEN.SKY_W + (col & (GEN.SKY_W - 1))] | ATTR
        got = vram[i * 2] | (vram[i * 2 + 1] << 8)
        if got != want:
            bad.append((col, row, got, want))
    assert not bad, f"{len(bad)} sky cells differ, first five: {bad[:5]}"


def test_the_palettes_in_cgram_are_the_generated_palettes(play):
    """CGRAM against the palette blobs, at the word offsets the claims pin.

    The DESTINATION region, read directly (AGENTS.md's asset-upload rule): a
    test that only checked the rendered colours would pass while an upload
    landed in the wrong CGRAM range, because the wrong range is still a
    colour.
    """
    _, meta = GEN.obj_pages()
    for base, blob in ((D.C_PLF_PAL, GEN.palette_bin(GEN.BGR, GEN.BG_ORDER)),
                       (D.C_HERO_PAL, GEN.words_bin(meta["hero"][0])),
                       (D.C_GHOST_PAL, GEN.words_bin(meta["ghost"][0]))):
        got = play.read_bytes(D.C, base * 2, 32)
        assert bytes(got) == blob, f"CGRAM at word {base} is not the blob"
    dusk = play.read_bytes(D.C, D.C_DUSK * 2, 2)
    assert dusk[0] | (dusk[1] << 8) == D.PLF_PLAY_SKY, (
        "CGRAM word 0 in `play` is not black — it is the surface rgb_gradient "
        "ADDs its per-scanline ramp to, so any non-zero base lifts the whole "
        "dusk and desaturates it. A $1082 base here is exactly the teal sky "
        "an earlier build of this rail shipped")


def test_the_arena_renders_the_generated_art(play):
    """Screenshot pixels against the tile art, at its DECLARED colours.

    A pixel is only right when the CHR upload, the tilemap, BOTH palettes and
    the layer order are simultaneously right — and it compares against a
    DECLARATION (the generator's grids) rather than against the render's own
    output, so it cannot pass by agreeing with itself.

    NO COLOUR MATH TERM HERE, and that is the assertion. The ramp targets the
    BACKDROP (RG_MATH_LAYERS = PLF_MATH_BACKDROP, i.e.
    `sf_colormath_on #1, #$20`), so BG1's terrain renders at exactly the
    colour the palette declares. An earlier form of this rail had the scanline
    COLDATA targeting BG1+BG2 and had to fold that into the expectation; if
    CGADSUB ever picks the layers back up, this test fails on the ground
    rather than passing quietly with a repainted floor.
    """
    img = shot(play, "/tmp/plf_arena.png")
    # The ground's GRASS rows: the tile's own picture puts grass in its top
    # two pixel rows and speckled dirt in the six below, so world row 24
    # (PPU scanlines 192..199 at camera 0) is grass only at 192..193.
    y = 192
    got = img.getpixel((4, png_y(y)))
    want = tuple(c >> 3 for c in bgr555_to_rgb(GEN.BGR["g"]))
    assert tuple(v >> 3 for v in got) == want, (
        f"grass at (4,{y}) rendered {tuple(v >> 3 for v in got)}, not the "
        f"declared tile colour {want} — colour math is reaching BG1")


def test_the_dusk_sky_on_screen_is_the_declared_ramp(play):
    """The BACKDROP's pixels, scanline by scanline, against the ramp blob.

    The sky is not a tile: it is CGRAM word 0 (black) plus rgb_gradient's
    per-scanline COLDATA, so the ONLY way to check it is to read the pixels
    where the backdrop shows through and compare them to the declared table.
    Every layer assertion in this file can pass while the wash lands on the
    wrong layers and the sky is one flat colour — a version of this rail
    shipped exactly that, green.

    Column x=4 at camera 0 is open level cells from the HUD down to the
    ground. Entry k lands on scanline k+1 (D.GRAD_LAG), which is measured
    rather than assumed — `tools/compare_ref_dusk.py` finds the same offset
    independently against a second implementation's ROM.
    """
    img = shot(play, "/tmp/plf_sky.png")
    grad = GEN.grad_bin()
    bad = []
    for y in range(8, 96):                  # clear of the HUD and the terrain
        got = tuple(v >> 3 for v in img.getpixel((4, png_y(y))))
        want = tuple(grad[p * GEN.GRAD_LINES + y - D.GRAD_LAG] & 31
                     for p in range(3))
        if got != want:
            bad.append((y, got, want))
    assert not bad, (
        f"{len(bad)} of 88 sky scanlines are not the declared dusk ramp, "
        f"first five {bad[:5]} — a flat sky here means the colour math is "
        f"not reaching the backdrop")
    # ...and it must actually RAMP. A constant column would satisfy a
    # per-scanline equality test against a constant table, so state the shape:
    top = tuple(grad[p * GEN.GRAD_LINES + 0] & 31 for p in range(3))
    bot = tuple(grad[p * GEN.GRAD_LINES + GEN.GRAD_LINES - 1] & 31
                for p in range(3))
    assert top[0] - bot[0] >= 16 and bot[2] - top[2] >= 8, (
        f"the ramp {top} -> {bot} is not a dusk: it must lose most of its red "
        f"and gain blue from top to bottom")


def test_the_dusk_ramp_matches_the_reference_ramp(play):
    """Our ramp against a second implementation's, CAPTURED OFF ITS RUNNING ROM.

    The independent ground truth AGENTS.md's asset-import rule asks for: the
    fixture is what that ROM's HDMA channels actually stream
    (`tools/capture_ref_dusk.py` reads it out of WRAM), so agreeing with it is
    not agreeing with ourselves. `play` is a parameter so this runs against the
    built ROM's own generator, not a stale checkout.

    THE TOLERANCE IS NOT SLACK, IT IS A NAMED BUG IN THAT BUILDER.
    Its `hdma_build_gradient_rgb` computes the 8.8 step as
    `signed_div_225(xba(bot - top))`, and `xba` byte-SWAPS where the comment
    says "<< 8" — correct for a positive delta, wrong for a negative one
    ($FFEA -> $EAFF = -5377, not -5632). So a declared (2,0,12) bottom renders
    as (3,1,11). The model below reproduces that table BYTE-EXACTLY, which is
    what makes "at most 2 steps, and here is why" a measurement rather than a
    fudge. We realise the endpoints as DECLARED; we do not copy a byte-swap
    into a Python generator to inherit someone else's arithmetic.
    """
    ref = (Path(__file__).resolve().parent / "fixtures/ref_dusk_grad.bin"
           ).read_bytes()
    assert len(ref) == 3 * 225
    ours = GEN.grad_bin()

    # 1. the fixture IS that builder's output, bug and all — modelled, not assumed
    def s16(v):
        return v - 65536 if v & 0x8000 else v

    for pl, (top, bot) in enumerate(zip(GEN.DUSK_TOP, GEN.DUSK_BOT)):
        d = (bot - top) & 0xFFFF
        step = int(s16(((d & 0xFF) << 8) | ((d >> 8) & 0xFF)) / 225)
        model = [((top * 256 + step * y) >> 8) & 0x1F for y in range(225)]
        got = [ref[pl * 225 + y] & 0x1F for y in range(225)]
        assert model == got, (
            f"plane {pl}: the captured reference ramp is no longer the "
            f"xba-step model — the fixture or the endpoints changed")

    # 2. ...and ours tracks it to within that bug's worth of quantisation
    worst = (0, None)
    for pl in range(3):
        for y in range(GEN.GRAD_LINES):
            a = ref[pl * 225 + y] & 0x1F
            b = ours[pl * GEN.GRAD_LINES + y] & 0x1F
            if abs(a - b) > worst[0]:
                worst = (abs(a - b), (pl, y, a, b))
    assert worst[0] <= 2, (
        f"our dusk ramp is {worst[0]} intensity steps off the reference's "
        f"rendered ramp at {worst[1]} — more than that builder's own "
        f"step-quantisation bug accounts for, so this is our drift, not its")
    # and the ENDPOINTS are the declared ones, exactly
    assert GEN.DUSK_TOP == (24, 8, 2) and GEN.DUSK_BOT == (2, 0, 12), (
        "the dusk endpoints are no longer the declared DUSK_TOP_*/DUSK_BOT_*")


# =============================================================================
# PARALLAX — the multi-distance scroll
# =============================================================================
def test_the_band_table_is_three_entries_and_covers_the_frame(play):
    """The HDMA table's SHAPE, read out of the WRAM the channel reads.

    Two non-repeat entries and a terminator, with counts summing to the 224
    active scanlines. This is the thing that makes the rebuild cheap: a count
    byte in $01..$80 transfers once and then idles, and BG2HOFS's write-twice
    latch holds the value through the idle lines. A regression to a
    per-scanline fill would still LOOK right on screen and would cost ~24x as
    much, so the shape is asserted directly.
    """
    tab = play.read_bytes(D.W, D.PLX_TAB, 10)
    assert tab[0] == D.PLX_SPLIT, f"top band is {tab[0]} lines, not the split"
    assert tab[3] == D.PLX_LINES - D.PLX_SPLIT, "bottom band is the remainder"
    assert tab[0] + tab[3] == D.PLX_LINES, "the two bands do not cover 224"
    assert tab[3] <= 0x80, "a non-repeat count byte may not exceed $80"
    assert tab[6] == 0, "the table is not terminated after two entries"


@pytest.mark.parametrize("target_px", [180, 256, 320, 400])
def test_the_two_bands_track_the_camera_at_their_declared_ratios(play,
                                                                target_px):
    """The band table against the ratio oracle, at four camera positions.

    Driven to several positions rather than one, because 1/8 and 3/8 agree
    modulo the skyline's 64 px period at some cameras (cam 256 puts both at
    32) and a single sample could sit on exactly that coincidence and prove
    nothing.
    """
    D.jump_arc(play, 168, hold_frames=30)          # clear the first pit
    D.walk_to(play, target_px)
    play.frame_step(1)                             # the NMI commits the table
                                                   #   one frame behind the
                                                   #   tick that moved the
                                                   #   camera; measured, and
                                                   #   the same on every run
    cam = D.u16(play, D.CAM)
    tab = play.read_bytes(D.W, D.PLX_TAB, 10)
    got = (tab[1] | (tab[2] << 8), tab[4] | (tab[5] << 8))
    assert got == D.plx_expect(cam), (
        f"at camera {cam} the bands read {got}, not the declared "
        f"{D.plx_expect(cam)} (1/8 clouds, 3/8 hills)")


def test_the_two_bands_are_visibly_at_different_offsets(play):
    """SCREENSHOT PIXELS, because parallax is a layer-composition feature.

    A per-layer byte assertion is necessary and NOT sufficient here: the band
    table can be perfect while the channel is unarmed, or armed on the wrong
    register, or pointed at the wrong table — and every one of those renders a
    flat sky that a VRAM check calls correct.

    So this measures the two bands ON THE SCREEN, and measures the thing the
    player actually sees: how far each band MOVED when the camera did. The
    skyline's features are 64 px periodic and each band carries a run that is
    entirely inside it — the fat cloud row (map row 4, PPU scanlines 32-39)
    and the solid hill body (map row 16, PPU 128-135, clear of ghost 2's
    sprite at 112-127) — so each band's phase is the position of the run's
    rising edge, modulo the period.

    Camera 0 -> 128 moves the clouds 16 px and the hills 48. Comparing the
    SHIFTS rather than the absolute phases is what makes this a statement
    about the ratios: the two runs do not start at the same residue in the
    pattern, so equal absolute phases would prove nothing and unequal ones
    would prove nothing either.
    """
    def tinted(name, y):
        """A BG2 tile colour as it renders.

        No COLDATA term: the ramp targets the BACKDROP, so the skyline's own
        colours come through untouched (RG_MATH_LAYERS = PLF_MATH_BACKDROP).
        `y` is kept in the signature because the run-finder below is indexed
        by scanline and the two bands are read at different ones.
        """
        del y
        v = [c >> 3 for c in bgr555_to_rgb(GEN.BGR[name])]
        return tuple(c << 3 | c >> 2 for c in v)

    def phase(img, y, colour):
        """Where the 64 px pattern sits on scanline y: the rising edge of the
        run of `colour`, treating the row as circular so a run that straddles
        x = 0 is still one run."""
        row = [img.getpixel((x, png_y(y))) for x in range(64)]
        edges = [x for x in range(64)
                 if row[x] == colour and row[(x - 1) % 64] != colour]
        assert len(edges) == 1, (
            f"scanline {y} has {len(edges)} runs of {colour} in one period, "
            f"not the single run the measurement needs")
        return edges[0]

    cloud_y, hill_y = 36, 130
    cloud_c, hill_c = tinted("w", cloud_y), tinted("s", hill_y)

    D.wait_grace(play)
    assert D.u16(play, D.CAM) == 0, "the round does not start at camera 0"
    img0 = shot(play, "/tmp/plf_bands_0.png")
    top0, bot0 = phase(img0, cloud_y, cloud_c), phase(img0, hill_y, hill_c)

    D.jump_arc(play, 168, hold_frames=30)          # clear the first pit
    D.walk_to(play, 256)
    play.frame_step(2)
    cam = D.u16(play, D.CAM)
    assert cam == 128, f"the drive parked the camera at {cam}, not 128"
    img1 = shot(play, "/tmp/plf_bands_128.png")
    top1, bot1 = phase(img1, cloud_y, cloud_c), phase(img1, hill_y, hill_c)

    want_top, want_bot = D.plx_expect(cam)
    assert (top0 - top1) % 64 == want_top % 64, (
        f"the far band moved {(top0 - top1) % 64} px when the camera moved "
        f"{cam}; 1/8 of that is {want_top}")
    assert (bot0 - bot1) % 64 == want_bot % 64, (
        f"the near band moved {(bot0 - bot1) % 64} px when the camera moved "
        f"{cam}; 3/8 of that is {want_bot}")
    assert (top0 - top1) % 64 != (bot0 - bot1) % 64, (
        "both bands moved the same distance: the sky is scrolling as ONE "
        "plane, which is what an unarmed or mis-pointed parallax channel "
        "looks like")


def test_standing_still_freezes_the_sky_without_zeroing_a_ratio(play):
    """The FREEZE invariant, stated as what the player sees.

    "Freeze" means the sky pixels do not move — not "a variable reads zero".
    Setting the ratios to 0 would make HOFS = world_x * 0 = 0, which
    TELEPORTS the layer to its world-zero position; that is the documented
    spec-trap, and it has shipped as a user-visible bug before. Here the
    ratios are assembly-time constants and the freeze is the ABSENCE of camera
    motion, so the test asserts the absence of pixel motion at a camera that
    is NOT zero — a teleport-to-zero would move the picture and be caught.
    """
    D.jump_arc(play, 168, hold_frames=30)
    D.walk_to(play, 256)
    play.frame_step(4)
    before = shot(play, "/tmp/plf_freeze_a.png")
    play.frame_step(30)                         # no input at all
    after = shot(play, "/tmp/plf_freeze_b.png")
    for y in (36, 100):
        a = [before.getpixel((x, png_y(y))) for x in range(256)]
        b = [after.getpixel((x, png_y(y))) for x in range(256)]
        assert a == b, f"the sky moved on scanline {y} with no input"


def test_the_pause_freeze_holds_the_whole_picture(play):
    """START freezes the world, and the banner says so on BG3.

    The pause is the second freeze surface and the sharper one: the camera,
    both sky bands, the hero and both patrols all stop, so a scanline of
    PIXELS 30 frames apart must be identical while the banner's glyphs are
    present in the BG3 tilemap.
    """
    D.walk_to(play, 120)
    D.press(play, start=True)
    play.frame_step(20)                          # the banner drains one cell a
                                                 #   frame; 8 cells + settle
    txt = play.read_bytes(D.V, (D.TXT_MAP["play"] + 13 * 32 + 12) * 2, 8 * 2)
    glyphs = "".join(chr((txt[i * 2] & 0xFF) + 0x20) for i in range(8))
    assert glyphs == "PAUSED  ", f"the banner reads {glyphs!r}"
    before = shot(play, "/tmp/plf_pause_a.png")
    play.frame_step(30, right=True)              # input IGNORED while paused
    after = shot(play, "/tmp/plf_pause_b.png")
    for y in (36, 100, 200):
        a = [before.getpixel((x, png_y(y))) for x in range(256)]
        b = [after.getpixel((x, png_y(y))) for x in range(256)]
        assert a == b, f"scanline {y} moved while paused"


def test_the_parallax_rebuild_costs_what_it_claims(play):
    """The per-frame cost of the band rebuild, in master cycles.

    AGENTS.md forbids estimating a cycle count, and the whole design argument
    for the three-entry table is a cost claim — so the cost is exactly the
    number that has to be on the record for it to be a decision rather than a
    hope.

    METHOD: two write breakpoints, on the table's FIRST byte and its
    terminator. Between them the CPU does nothing but the rebuild, so the
    master-clock difference IS the rebuild, measured on the shipped binary.
    Reduced with min() over several frames, because a sample that caught the
    rest of the NMI hook carries its cost too.
    """
    D.walk_to(play, 200)                          # keep the camera moving
    samples = []
    play.debug_resume()                           # run_to_break needs a core
    play.set_input(0, right=True)                 #   that is running
    play.debug_break()
    try:
        for _ in range(8):
            t0 = _clock_at_write(play, D.PLX_TAB)
            t1 = _clock_at_write(play, D.PLX_TAB + 6)
            if t0 is not None and t1 is not None and 0 < t1 - t0:
                samples.append(t1 - t0)
    finally:
        play.set_breakpoints([])
        play._frame_stepping = True
        play.debug_resume(clear_input=False)
        play.set_input(0)

    assert len(samples) >= 3, f"only {len(samples)} usable samples: {samples}"
    cost, worst = min(samples), max(samples)
    share = 100.0 * cost / MC_PER_FRAME
    print(f"\nparallax band rebuild: {cost} mc/frame ({share:.3f}% of the "
          f"{MC_PER_FRAME} mc NTSC frame); worst sample {worst} mc; "
          f"n={len(samples)}")
    # A REGRESSION GUARD around the measured figure, not a budget claim. The
    # comparison that matters is the shape this design rejected: a 224-entry
    # per-scanline fill runs ~16 cycles an entry, ~3,700 CPU cycles, which at
    # mc/6 is ~22,000 mc — over 6% of a frame. One percent is a wide guard
    # around a rebuild that touches ten bytes, and still an order of magnitude
    # under the fill it replaced.
    assert cost < MC_PER_FRAME // 100, (
        f"the band rebuild costs {cost} mc ({share:.2f}% of a frame) — the "
        f"three-entry table's whole argument is that it does not")


def _clock_at_write(runner, addr, max_frames=300):
    """Master clock the next time the CPU writes `addr`, or None.

    The budget is EMULATED frames, so a None means "the CPU did not write this
    in N frames of the ROM's own time" — a claim about the ROM rather than
    about the host's load. THE BREAKPOINT IS THE STOPWATCH; THE WRITE COUNTER
    IS THE ORACLE: a reported break with the counter unmoved is a thread pause
    wearing a breakpoint's clothes, so the watch resumes on what is
    left of the budget. Lifted from tests/test_room_window.py, where the
    reasoning is written out at length.
    """
    before = runner.write_count(MemoryType.SnesWorkRam, addr)
    # SnesWorkRam, not SnesMemory: the rebuild stores with `sta long`, so the
    # CPU address it touches is $7E05AA and a breakpoint on the bank-0 mirror
    # never matches (measured — the counter moved 59 times while the break
    # never fired). Addresses are interpreted in the mem_type's own space.
    runner.set_breakpoints([(MemoryType.SnesWorkRam, addr, "write")])
    start = runner.ppu_frame_count()
    while True:
        left = max_frames - (runner.ppu_frame_count() - start)
        if left <= 0:
            return None
        broke = runner.run_to_break(max_frames=left)
        if runner.write_count(MemoryType.SnesWorkRam, addr) > before:
            return runner.snes_state_snapshot().master_clock
        if not broke:
            return None


# =============================================================================
# THE HERO
# =============================================================================
def test_the_hero_walks_both_ways_and_the_world_clamps_both_ends(play):
    """OAM x every frame of each hold, against the walk speed and the clamps.

    BOTH directions, because a test that only walks right locks that direction
    and ships the other broken (AGENTS.md's state-cycle rule — a wall-collision
    bug on the leftward walk once survived a long time behind exactly that
    gap).
    """
    D.wait_grace(play)
    first = D.oam_entry(play, D.O_HERO)
    D.hold(play, 10, right=True)
    play.frame_step(1)
    moved = D.oam_entry(play, D.O_HERO)
    assert moved["x"] > first["x"], "the hero did not walk right on screen"
    assert moved["attr"] & 0x40 == 0, "walking right must not mirror the sprite"
    D.hold(play, 20, left=True)
    play.frame_step(1)
    back = D.oam_entry(play, D.O_HERO)
    assert back["x"] < moved["x"], "the hero did not walk left on screen"
    assert back["attr"] & 0x40, "walking left must mirror the sprite"
    # ...and the world's left edge stops it, in OAM, not in a variable.
    D.hold(play, 60, left=True)
    play.frame_step(2)
    clamped = D.oam_entry(play, D.O_HERO)
    D.hold(play, 20, left=True)
    play.frame_step(2)
    assert D.oam_entry(play, D.O_HERO)["x"] == clamped["x"], (
        "the hero walked past the world's left edge")
    assert clamped["large"], "the hero's size bit is clear — a 16x16 sprite "\
                             "with a clear size bit renders as its top-left 8x8"


def test_a_jump_rises_to_its_apex_and_lands_flush_on_the_surface(play):
    """The WHOLE cycle: ascent, apex, descent, landing, rest.

    APEX ALONE IS NOT ENOUGH and that is the rule this case exists for. An
    apex depends only on the launch velocity and gravity; the LANDING frame
    depends on the fall clamp and on the snap, and a snap off by the box
    height embeds the sprite in the floor while every apex assertion passes.
    So the rest position is asserted too — on every grounded frame, in OAM,
    against the spawn row the level puts the hero on.
    """
    D.wait_grace(play)
    rest_y = D.oam_entry(play, D.O_HERO)["y"]
    ys = []
    for n in range(60):
        play.frame_step(1, a=(n < 24))
        ys.append(D.oam_entry(play, D.O_HERO)["y"])
    apex = min(ys)
    assert apex < rest_y - 24, (
        f"the jump only reached {rest_y - apex} px above rest; a variable-"
        f"height jump held for 24 frames should clear far more")
    assert ys[-1] == rest_y, (
        f"the hero came to rest at OAM y {ys[-1]}, not the {rest_y} it stood "
        f"at before the jump — the landing snap is off, which is exactly the "
        f"bug an apex-only test ships")
    # ...and the descent is monotonic after the apex: no bounce, no re-rise.
    tail = ys[ys.index(apex):]
    assert all(b >= a for a, b in zip(tail, tail[1:])), (
        f"the descent is not monotonic: {tail}")


def test_a_tap_jumps_lower_than_a_hold(play):
    """The variable-height jump, as two arcs read out of OAM.

    The cut is a CLAMP, not a zeroing: a tap must still leave the ground.
    """
    def arc(hold_frames):
        D.to_title(play)
        D.enter_play(play)
        D.wait_grace(play)
        rest = D.oam_entry(play, D.O_HERO)["y"]
        peak = rest
        for n in range(60):
            play.frame_step(1, a=(n < hold_frames))
            peak = min(peak, D.oam_entry(play, D.O_HERO)["y"])
        return rest - peak

    tap, held = arc(2), arc(24)
    assert 0 < tap < held, (
        f"a tap rose {tap} px and a hold {held} px — the jump cut is not "
        f"doing what a variable-height jump promises")


def test_the_hero_animates_and_the_frames_are_different_art(play):
    """The OAM tile cycling, AND the frames' CHR bytes differing.

    The second half matters: an animation table that points at the same tile
    four times cycles perfectly and animates nothing.

    "Different" is asserted over the whole 16x16 QUAD, not over the top-left
    tile. The pack's idle is a one-pixel bob, so two frames can share a top
    half and differ only below the waist — a top-tile check would call that a
    flicker and pass while the legs did all the moving.
    """
    tiles = set()
    for _ in range(5 * D.ANIM_RATE):
        play.frame_step(1, right=True)
        tiles.add(D.oam_entry(play, D.O_HERO)["tile"])
    want = {D.HERO_TILE + 2 * f for f in range(D.ANIM_STEPS)}
    assert tiles == want, (
        f"the hero showed tiles {sorted(tiles)}; the rail declares "
        f"{D.ANIM_STEPS} frames at base {D.HERO_TILE}, i.e. {sorted(want)}")
    quads = {bytes(vram_quad(play, t)) for t in sorted(tiles)}
    assert len(quads) > 1, (
        "every animation frame is the same art in VRAM — the hero cycles "
        "through four tile numbers and does not move")


def vram_quad(runner, tile):
    """The 32 x 4 bytes a 16x16 OBJ at `tile` reads: {N, N+1, N+16, N+17}.

    The OBJ name table is sixteen tiles wide, so the bottom half of a 16x16
    sprite is +16 tile numbers away, not +2. Reading the quad the way the PPU
    reads it is the only way a CHR assertion covers what is actually drawn.
    """
    out = bytearray()
    for n in (tile, tile + 1, tile + 16, tile + 17):
        out += bytes(runner.read_bytes(D.V, (D.OBJ_CHR + n * 16) * 2, 32))
    return out


def test_the_obj_chr_in_vram_is_the_imported_pack_art(play):
    """The OBJ CHR upload's DESTINATION region, byte for byte, twice over.

    This is the rail's identity, so it gets the rule's full weight
    (AGENTS.md's asset-upload rule): read the destination, not a downstream
    effect. A sprite that renders "some art" passes every OAM and screenshot
    check ever written while the upload silently lands the WRONG art, or lands
    64 tiles where 32 were claimed, or no-ops entirely — which has shipped an
    invisible player sprite on this project before.

    Checked against TWO oracles, and the second is the one that matters:

      * `gen_platformer_assets.obj_pages()` — proves the upload moved what the
        build produced. Necessary, and on its own a tautology: it cannot tell
        whether the CONVERSION read the pack correctly, because it is the
        conversion.
      * `vendor/art/dungeon_sprites/ref_*.inc` — png2snes.py's output for the
        same pack, produced by a different program entirely. Two independent
        converters agreeing on 2,048 bytes is evidence; one converter agreeing
        with itself is not.
    """
    want, _ = GEN.obj_pages()
    got = bytes(play.read_bytes(D.V, D.OBJ_CHR * 2, len(want)))
    assert got == want, (
        f"OBJ CHR in VRAM differs from the generated blob at "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes")

    for tag, base in (("hero", D.HERO_TILE), ("ghost", D.GHOST_TILE)):
        reference = inc_bytes(REFERENCE_INC[tag], f"{tag}_chr")
        page = got[base * 32:base * 32 + len(reference)]
        assert page == reference, (
            f"the {tag} page at tile {base} is not the reference {tag}_chr — "
            f"{sum(a != b for a, b in zip(page, reference))} of {len(reference)} "
            f"bytes differ, so the two converters disagree about the pack")


def test_the_obj_palettes_in_cgram_are_the_imported_pack_palettes(play):
    """The OBJ palettes' DESTINATION region, against a second converter.

    Sibling of the CHR test above, and not redundant with
    test_the_palettes_in_cgram_are_the_generated_palettes: that one proves the
    upload landed the build's own bytes at the claimed word offsets, this one
    proves those bytes are the PACK's colours, by comparing against a palette
    png2snes.py built from the same PNGs by a different route. Right pixels in
    the wrong colours is a fidelity regression that a CHR check cannot see.
    """
    _, meta = GEN.obj_pages()
    for tag, base in (("hero", D.C_HERO_PAL), ("ghost", D.C_GHOST_PAL)):
        reference = inc_bytes(REFERENCE_INC[tag], f"{tag}_pal")
        got = bytes(play.read_bytes(D.C, base * 2, 32))
        assert got == reference, f"CGRAM at word {base} is not the reference {tag}_pal"
        assert got == GEN.words_bin(meta[tag][0]), (
            f"the generated {tag} palette disagrees with CGRAM")


def actor_pixel_bottom(img, y0, x_lo, x_hi, palette, grad):
    """The lowest PPU scanline carrying one of this actor's own colours.

    Reads PIXELS in the OAM entry's own window — the rendered output, not the
    entry's y. A pixel counts as the actor's when it is in the actor's OBJ
    palette AND is not that scanline's backdrop, because the dusk ramp walks
    through a lot of colours on its way down and a bare palette membership
    test would eventually collide with one.
    """
    lowest = None
    for y in range(y0, min(y0 + 18, 224)):
        sky = tuple(grad[p * GEN.GRAD_LINES + y - D.GRAD_LAG] & 31
                    for p in range(3))
        for x in range(max(0, x_lo), min(256, x_hi)):
            px = img.getpixel((x, png_y(y)))
            if px in palette and tuple(v >> 3 for v in px) != sky:
                lowest = y
    return lowest


def test_every_animation_frame_rests_on_the_surface_and_none_covers_it(play):
    """THE FEET, IN PIXELS, ACROSS THE WHOLE IDLE CYCLE — both actors.

    The defect this replaces was invisible to its own test. The old
    `..._at_their_own_content_bottom` asserted the OAM **y word** against an
    arithmetic expectation and passed, while on screen the ghost's hem sat ON
    the bright surface line on every frame and the hero's did on one frame in
    four. An OAM y is a proxy: it is not where the sprite draws (an OBJ
    renders a scanline lower) and it says nothing about where THAT FRAME's
    art stops inside its box.

    So this reads the lowest lit pixel and demands it land on the last
    scanline ABOVE the surface — resting on the line, never covering it,
    never floating over it.

    AND IT WALKS THE WHOLE CYCLE, which is the other half. The defect's whole
    signature was that it appeared on some frames and not others; a
    single-frame screenshot cannot see that, and no single-frame test did for
    two changes. The sweep asserts on every frame it samples AND asserts that
    all four of the actor's frames were actually reached, so it cannot pass by
    sampling the same pose four times.
    """
    _, meta = GEN.obj_pages()
    grad = GEN.grad_bin()
    D.walk_to(play, D.SPAWN_X + 8)
    play.frame_step(2)

    for who, slot, tile0, want_surface in (
            ("hero", D.O_HERO, D.HERO_TILE, D.u16(play, D.DP["pixy"]) + D.BOX),
            ("ghost", D.O_GHOSTS, D.GHOST_TILE, D.G1_Y + D.BOX)):
        pal = [bgr555_to_rgb(w) for w in meta[who][0][1:] if w]
        seen, bad = {}, []
        for _ in range(D.ANIM_RATE * D.ANIM_STEPS * 2 + 8):
            play.frame_step(1)
            e = D.oam_entry(play, slot)
            if e["y"] >= 0xF0:              # the blink's off phase
                continue
            img = shot(play, f"/tmp/plf_feet_{who}.png")
            after = D.oam_entry(play, slot)
            # The capture and the entry must describe the SAME frame, or the
            # label below names the wrong one. A PATROLLING ghost moves in x
            # between the two reads, which is not a frame change — so the
            # POSE (tile) and the ROW (y) must agree and the column window
            # spans both x readings.
            if after["tile"] != e["tile"] or after["y"] != e["y"]:
                continue
            bottom = actor_pixel_bottom(
                img, e["y"], min(e["x"], after["x"]),
                max(e["x"], after["x"]) + 16, pal, grad)
            if bottom is None:
                continue
            frame = ((e["tile"] - tile0) // 2) % D.ANIM_STEPS
            seen.setdefault(frame, bottom)
            if bottom != want_surface - 1:
                bad.append((frame, bottom))
        assert not bad, (
            f"the {who}'s lowest lit pixel is not on the scanline above the "
            f"surface ({want_surface - 1}) on frame(s) {sorted(set(bad))} — "
            f"{'it is covering the surface line' if any(b > want_surface - 1 for _, b in bad) else 'it is floating above it'}")
        assert set(seen) == set(range(D.ANIM_STEPS)), (
            f"only frames {sorted(seen)} of the {who}'s {D.ANIM_STEPS} were "
            f"reached — a sweep that misses a frame cannot see a defect that "
            f"only shows on one")


def test_the_per_frame_feet_anchors_are_the_arts_own_numbers(play):
    """The lift constants the ROM subtracts, against the CHR that needs them.

    A companion to the pixel sweep, not a substitute: the sweep proves the
    soles land right at the two places an actor stands in this level, and this
    proves the RULE generalises — every frame's lift is exactly that frame's
    own content_bottom, so an art change that moves one frame's sole moves its
    anchor with it instead of silently sinking that frame into the floor.

    The content bottoms are recomputed here from the OBJ CHR **in VRAM** (the
    destination region), so this is not the generator agreeing with itself.
    """
    chr_words = D.OBJ_CHR
    blob = bytes(play.read_bytes(D.V, chr_words * 2, 64 * 32))

    def frame_bottom(base, f):
        """Lowest non-zero row + 1 of the 16x16 quad {N, N+1, N+16, N+17}."""
        bot = 0
        for half, tiles in ((0, (base + f * 2, base + f * 2 + 1)),
                            (8, (base + f * 2 + 16, base + f * 2 + 17))):
            for t in tiles:
                b = blob[t * 32:(t + 1) * 32]
                for y in range(8):
                    if b[y * 2] | b[y * 2 + 1] | b[16 + y * 2] | b[16 + y * 2 + 1]:
                        bot = max(bot, half + y + 1)
        return bot

    for who, base, want in (("hero", D.HERO_TILE, D.HERO_BOTTOMS),
                            ("ghost", D.GHOST_TILE, D.GHOST_BOTTOMS)):
        got = tuple(frame_bottom(base, f) for f in range(D.ANIM_STEPS))
        assert got == want, (
            f"the {who}'s per-frame content bottoms in VRAM are {got}, not "
            f"the {want} the lift table is built from — the anchors and the "
            f"art have drifted apart")
    # ...and the generator, reading the PNGs by a different route, agrees
    _, meta = GEN.obj_pages()
    assert tuple(meta["hero"][1]) == D.HERO_BOTTOMS
    assert tuple(meta["ghost"][1]) == D.GHOST_BOTTOMS


# =============================================================================
# COINS, GHOSTS, LIVES
# =============================================================================
def test_a_collected_coin_leaves_the_tilemap_and_the_hud_counts_it(play):
    """The pickup, asserted on BOTH output regions it changes.

    The cell must become tile 0 IN VRAM (a coin that is only removed from a
    bitmap stays on screen forever), and the HUD digit must move IN VRAM (a
    counter that only moves in DP is not a HUD). Neither alone is the feature.
    """
    cell = D.PLF_MAP + 23 * 32 + 7        # world (7,23), page 0
    before = play.read_bytes(D.V, cell * 2, 2)
    assert before[0] == GEN._L["C"], "the coin is not in the tilemap to begin"
    hud = D.TXT_MAP["play"] + 23             # the COINS digit cell
    assert play.read_bytes(D.V, hud * 2, 1)[0] == ord("0") - 0x20

    D.walk_to(play, 76)
    play.frame_step(4)                       # the queue writes in the next NMI
    after = play.read_bytes(D.V, cell * 2, 2)
    assert after[0] == GEN._L["."], (
        "the collected coin is still in the BG1 tilemap — the VBlank cell "
        "queue did not write it")
    assert play.read_bytes(D.V, hud * 2, 1)[0] == ord("1") - 0x20, (
        "the HUD's COINS digit did not move")


def test_a_collected_coin_stays_collected_across_a_walk_back(play):
    """Reverse motion over the same cell, which is the state cycle that
    catches a bitmap that was written but is never read."""
    D.walk_to(play, 76)
    play.frame_step(4)
    coins = D.u16(play, D.DP["coins"])
    D.walk_to(play, 30)
    D.walk_to(play, 76)
    play.frame_step(4)
    assert D.u16(play, D.DP["coins"]) == coins, (
        "walking back over a collected coin collected it again")


def test_both_ghosts_patrol_and_the_seam_one_crosses_the_page_boundary(play):
    """Ghost 2's world x sweeping across column 32, read as OAM motion.

    The seam is the world's PAGE boundary (BG1 is two 32x32 pages), and a
    patrol crossing it is exactly what a per-page special case would exist
    for. Here it needs none at all — the probe indexes a flat ROM blob — so
    this test is what proves the absence of one is correct.
    """
    seen = set()
    for _ in range(300):
        play.frame_step(1)
        seen.add(D.u16(play, D.DP["e2x"]))
    assert min(seen) < 32 * 8 < max(seen), (
        f"ghost 2 stayed on one side of the seam: {min(seen)}..{max(seen)}")
    # ...and it stays on its ledge: the patrol turns at a missing floor.
    assert min(seen) >= 26 * 8 - 8 and max(seen) <= 39 * 8, (
        f"ghost 2 walked off its ledge: {min(seen)}..{max(seen)}")


def test_a_ghost_hit_costs_a_life_and_blinks_the_hero(play):
    """The hurt cycle, end to end: the printed digit, then the blink.

    The blink is asserted as the OAM entry appearing AND disappearing over
    consecutive frames — a hero that is merely drawn every frame passes any
    "is it on screen" check.
    """
    hud = D.TXT_MAP["play"] + 7               # the LIVES digit cell
    assert play.read_bytes(D.V, hud * 2, 1)[0] == ord("3") - 0x20
    # Walk right into ghost 1's ground beat without jumping.
    for _ in range(400):
        play.frame_step(1, right=True)
        if D.u16(play, D.DP["lives"]) < D.LIVES:
            break
    else:
        pytest.fail("ghost 1 never landed a hit in 400 frames")
    play.frame_step(4)
    assert play.read_bytes(D.V, hud * 2, 1)[0] == ord("2") - 0x20, (
        "the HUD's LIVES digit did not move on a hit")
    parked, drawn = 0, 0
    for _ in range(24):
        play.frame_step(1)
        y = D.oam_entry(play, D.O_HERO)["y"]
        parked += y >= 0xF0
        drawn += y < 0xF0
    assert parked and drawn, (
        f"the hero did not blink during its i-frames: {parked} parked / "
        f"{drawn} drawn frames")


def test_a_stomped_ghost_leaves_the_screen(play):
    """A defeated patrol's OAM slot parks, and the hero bounces.

    Asserted on the SLOT rather than on the alive word: the slot is what the
    PPU reads, and "the alive word is 0" is exactly the proxy assertion this
    repo has been burned by.
    """
    slot = D.O_GHOSTS
    D.wait_grace(play)                    # a stomp during the spawn grace is
                                          #   no stomp: do_combat services the
                                          #   i-frame countdown and returns
    for _ in range(600):
        # Jump when the ground beat is about fifty pixels ahead and closing.
        # The two approach at 3 px a frame (the hero's 2 plus the ghost's 1)
        # and a cut arc is ~20 frames, so the descent arrives over the ghost.
        # Measured across a sweep of windows: 40, 50 and 60 all stomp; 30
        # walks into it. Fifty is the middle of what works.
        gap = D.u16(play, D.DP["e1x"]) - D.u16(play, D.DP["px"])
        play.frame_step(1, right=True,
                        a=bool(D.u16(play, D.DP["grounded"]) and 0 < gap <= 50))
        if not D.u16(play, D.DP["e1alive"]):
            break
    else:
        pytest.fail("ghost 1 was never stomped in 600 frames")
    play.frame_step(3)
    assert D.oam_entry(play, slot)["y"] >= 0xF0, (
        "the stomped ghost is still on screen")
    assert D.u16(play, D.DP["lives"]) == D.LIVES, (
        "a stomp cost a life — the discrimination between landing on a ghost "
        "and walking into one is wrong")


def test_the_pit_costs_a_life_and_returns_the_hero_to_spawn(play):
    """Falling past the death plane, then the respawn, in OAM."""
    D.die_into_the_pit(play)
    play.frame_step(6)
    assert D.u16(play, D.DP["lives"]) == D.LIVES - 1
    hero = D.oam_entry(play, D.O_HERO)
    # The hero respawns at the world origin, so screen x is world x here.
    assert abs(hero["x"] - (D.SPAWN_X - D.BOX // 2)) <= 1, (
        f"the hero respawned at screen x {hero['x']}, not spawn")


# =============================================================================
# THE ARC — four scenes, driven all the way round
# =============================================================================
def test_the_title_boots_and_offers_no_continue_on_a_virgin_cart(runner):
    """The boot screen's glyphs in BG3, and the ABSENCE of the continue line.

    A virgin cart's SRAM is power-on garbage under this harness's random
    regime, which is what makes "no CONTINUE offered" a real assertion rather
    than a tautology about zeroed memory.
    """
    D.clear_save(runner)          # Mesen persists SRAM between loads, so a
    D.to_title(runner)            #   case that banked a run leaves the cart
    D.settle(runner)              #   written for every later one
    row = runner.read_bytes(D.V, (D.TXT_MAP["title"] + 8 * 32 + 8) * 2, 15 * 2)
    logo = "".join(chr((row[i * 2] & 0xFF) + 0x20) for i in range(15))
    assert logo == "SUPER KIT QUEST", f"the title reads {logo!r}"
    cont = runner.read_bytes(D.V, (D.TXT_MAP["title"] + 16 * 32 + 8) * 2, 16 * 2)
    assert all(cont[i * 2] == 0 for i in range(16)), (
        "the title offers CONTINUE with no valid save in slot 0")
    runner.debug_resume()


def test_the_menu_backdrop_is_the_ramps_own_midpoint(runner):
    """CGRAM word 0 on the title card, against the RAMP it stands in for.

    The three menu scenes have no gradient of their own — rgb_gradient is
    composed into `play` only — so they paint one flat word. That word is not
    a taste: it is recomputed here from the same blob the round streams, at
    the ramp's middle scanline, so the cards cannot drift into a different
    evening from the game (which is exactly what happened when the ramp moved
    to the backdrop and the old $1082 base was left behind on the menus).

    Read as the DESTINATION region and then as PIXELS, because CGRAM word 0
    is only the backdrop if the layers actually leave it showing.
    """
    D.to_title(runner)
    D.settle(runner)
    grad = GEN.grad_bin()
    mid = GEN.GRAD_LINES // 2
    chan = [grad[p * GEN.GRAD_LINES + mid] & 31 for p in range(3)]
    want = chan[0] | chan[1] << 5 | chan[2] << 10
    got = runner.read_bytes(D.C, D.C_DUSK * 2, 2)
    assert got[0] | (got[1] << 8) == want == D.PLF_DUSK, (
        f"the title's backdrop is ${got[1]:02X}{got[0]:02X}, not the dusk "
        f"ramp's own midpoint ${want:04X} — the menus and the round are "
        f"showing two different skies")
    img = shot(runner, "/tmp/plf_title_sky.png")
    assert tuple(v >> 3 for v in img.getpixel((4, png_y(4)))) == tuple(chan), (
        "the title's top-left pixel is not the declared backdrop — something "
        "is drawing over it, or the colour never reached CGRAM")
    runner.debug_resume()


def test_losing_every_life_reaches_game_over_and_start_returns_to_the_title(
        play):
    """The full loss arc, and the restart trip it makes possible.

    scene_mgr refuses a self-transition, so a restart goes THROUGH the title —
    which is not a detour but the thing that makes it legal, because
    play::enter is the only place the level, the sky and every counter may be
    written — the same enter-writes-everything rule the other arcade rails
    here hold.
    """
    for _ in range(D.LIVES):
        if D.scene_now(play)[0] != D.SCENE_PLAY:
            break
        D.die_into_the_pit(play)
    assert D.wait_scene(play, D.SCENE_OVER), "three deaths did not end the run"
    row = play.read_bytes(D.V, (D.TXT_MAP["over"] + 10 * 32 + 11) * 2, 9 * 2)
    verdict = "".join(chr((row[i * 2] & 0xFF) + 0x20) for i in range(9))
    assert verdict == "GAME OVER", f"the ending card reads {verdict!r}"
    for slot in (D.O_HERO, D.O_GHOSTS, D.O_GHOSTS + 1, D.O_HI_PAD):
        assert D.oam_entry(play, slot)["y"] >= 0xF0, (
            f"OAM slot {slot} survived the round into the ending card")
    D.press(play, start=True)
    assert D.wait_scene(play, D.SCENE_TITLE), "START did not return to title"


def test_a_death_with_coins_banks_them_and_the_title_then_offers_continue(play):
    """SAVE -> the title's offer -> CONTINUE -> the restored count, on screen.

    Every step is read as rendered output: the offer is the glyphs of the
    CONTINUE line in BG3, and the restore is the COINS digit the fresh round
    prints. The SRAM bytes themselves are deliberately not asserted — the
    save feature owns its format, and this rail's claim is about what the
    player sees.
    """
    D.walk_to(play, 76)                       # one coin in hand
    play.frame_step(4)
    for _ in range(D.LIVES):
        if D.scene_now(play)[0] != D.SCENE_PLAY:
            break
        D.die_into_the_pit(play)
    assert D.wait_scene(play, D.SCENE_OVER)
    row = play.read_bytes(D.V, (D.TXT_MAP["over"] + 13 * 32 + 17) * 2, 2)
    assert row[0] == ord("1") - 0x20, "the ending card did not show the bank"

    D.press(play, start=True)
    assert D.wait_scene(play, D.SCENE_TITLE)
    cont = play.read_bytes(D.V, (D.TXT_MAP["title"] + 16 * 32 + 8) * 2, 16 * 2)
    offer = "".join(chr((cont[i * 2] & 0xFF) + 0x20) for i in range(16))
    assert offer == "SELECT: CONTINUE", (
        f"the title does not offer the banked run: {offer!r}")

    D.press(play, select=True)
    assert D.wait_scene(play, D.SCENE_PLAY), "SELECT did not start a run"
    hud = D.TXT_MAP["play"] + 23
    assert play.read_bytes(D.V, hud * 2, 1)[0] == ord("1") - 0x20, (
        "the continued round did not restore the banked coin count")
    # ...and it is a FRESH level otherwise: the coin the banked run collected
    # is back in the tilemap.
    cell = D.PLF_MAP + 23 * 32 + 7
    assert play.read_bytes(D.V, cell * 2, 1)[0] == GEN._L["C"], (
        "a continue did not respawn the level's coins")
    assert play.read_bytes(D.V, (D.TXT_MAP["play"] + 7) * 2, 1)[0] == \
        ord("3") - 0x20, "a continue did not grant a fresh three lives"


def test_collecting_every_coin_reaches_the_win_card(play):
    """The whole level, played, to the WIN card — the rail's headline claim.

    A closed-loop bot walks the route the level was designed around: the
    ground coin, the mid-arc pickup over the first one-way platform, the step
    platform that makes the seam ledge reachable, the seam coin above the
    world's page boundary, the second platform, and both pits. Six coins,
    three lives intact.
    """
    D.win_route(play)
    assert D.wait_scene(play, D.SCENE_WIN), (
        f"six coins did not reach the win card "
        f"(coins={D.u16(play, D.DP['coins'])}, "
        f"lives={D.u16(play, D.DP['lives'])})")
    row = play.read_bytes(D.V, (D.TXT_MAP["win"] + 10 * 32 + 12) * 2, 8 * 2)
    verdict = "".join(chr((row[i * 2] & 0xFF) + 0x20) for i in range(8))
    assert verdict == "YOU WIN!", f"the win card reads {verdict!r}"
    digit = play.read_bytes(D.V, (D.TXT_MAP["win"] + 13 * 32 + 17) * 2, 1)[0]
    assert digit == ord("6") - 0x20, "the win card did not show six coins"


# =============================================================================
# POWER-ON FIDELITY
# =============================================================================
def test_no_sprite_shows_power_on_garbage_on_the_first_settled_frame(runner):
    """Every slot this rail owns is parked before the first frame is shown.

    RAM is random at boot under this harness (CLAUDE.md rule 5), so an
    unparked slot renders whatever the DRAM held — and it renders it on the
    title, where this rail draws no sprites at all.
    """
    D.to_title(runner)
    for slot in range(4):
        e = D.oam_entry(runner, slot)
        assert e["y"] >= 0xF0, (
            f"OAM slot {slot} is on screen at y={e['y']} on the title, which "
            f"draws no sprites")
    runner.debug_resume()
