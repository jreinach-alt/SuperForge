"""split_v_fight — the seamless vertical dual-camera split, on the emulator.

THE TEST SURFACE IS THE RENDERED OUTPUT (CLAUDE.md rule 2). "The view is
merged" is asserted as *the framebuffer being pixel-identical to a no-split
reference*, not as "spread == 0" — the spread word is the mechanism, and a
test that reads it would pass while the window recipe was wrong. "The fighters
swapped sides" is asserted as *which team colour occupies which half of the
screenshot*, backed by the OAM bytes the PPU actually reads. "The divider
exists" is asserted as *its authored tones appearing in a column that is empty
at merge*.

WHY THE -D VARIANTS. The headline claim is a pixel-identity between two ROMs.
Capturing that from the interactive build would mean sampling two running
emulators at the same instant and hoping the ease had settled in both — a race
that passes most of the time, which is worse than no test. The static builds
(tools/build_split_v_variants.sh) freeze the swept variable, so the comparison
has nothing to race against. This is the same reason the reference build has its own
-DHOLD builds.

GROUND TRUTH IS THE REFERENCE ROM, NOT OUR OWN RENDER. The asset-import rule
(CLAUDE.md) requires an INDEPENDENT rendering to check a converter against;
re-rendering our own output would agree with our own bugs. Where a reference
tree is on disk this module builds ITS split_v_fight and compares against what
that hardware render actually produces. Where it is not (a bare CI
runner) those cases skip loudly rather than silently weakening.
"""
import os
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_v_fight.sfc"
# Written as one expression on purpose: tests/conftest.py resolves the map a
# module reads AT COLLECTION TIME from exactly this shape, and the freshness
# guard refuses a module whose map it cannot see.
_JMAP = json.loads((SUPERFORGE / "build" / "sv" / "symbol_map.json").read_text())

VARIANTS = ("sv_hold_merge", "sv_hold_split", "sv_nowin", "sv_cross",
            "sv_autodemo")


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — the allocator moved it?")


# Addresses are ASKED FOR, never hardcoded: this file reads the same map the
# ROM was assembled against, so a re-pack moves the test with the code.
V_STAGE_MAP = _sym("ES_V_STAGE_MAP", "fight")["start"]
V_STAGE_CHR = _sym("ES_V_STAGE_CHR", "fight")["start"]
V_BEVEL_CHR = _sym("ES_V_BEVEL_CHR", "fight")["start"]
V_OBJ_CHR = _sym("ES_V_OBJ_CHR", "fight")["start"]
C_STAGE_PAL = _sym("ES_C_STAGE_PAL", "fight")["start"]
C_BEVEL_PAL = _sym("ES_C_BEVEL_PAL", "fight")["start"]
C_KNIGHT_R = _sym("ES_C_KNIGHT_PAL_R", "fight")["start"]
C_KNIGHT_B = _sym("ES_C_KNIGHT_PAL_B", "fight")["start"]
O_F1 = _sym("ES_O_FIGHTER1", "fight")["start"]
O_F2 = _sym("ES_O_FIGHTER2", "fight")["start"]

W, V, O, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesSpriteRam, MemoryType.SnesCgRam)

# --- the rail's declared shape (game/split_v_fight/split_v.inc) -------------
# Restated here as an ORACLE, deliberately independent of the ROM: these are
# the numbers the rail promises, and the tests check the machine against them
# rather than against whatever the machine happens to hold.
ARENA_MID, ARENA_LO, ARENA_HI = 128, 24, 232
WALK_SPD, MERGE_DX, SPREAD_MAX = 2, 128, 48
CENTRE = 128                 # the seam: fixed, the cameras move
FLOOR_ROW = 22               # tilemap row of the grass surface
SURFACE_TOP = FLOOR_ROW * 8  # 176
KNIGHT_BOTTOM = 28           # generator-derived; NOT the 32 box height
KNIGHT_Y = SURFACE_TOP - KNIGHT_BOTTOM - 1   # 147: the PPU draws one line below

# The two team colours, as the PPU emits them (BGR555 -> the emulator's RGB).
RED_TEAM = (165, 41, 41)
BLUE_TEAM = (41, 41, 165)

SCREEN_W, SCREEN_H = 256, 224


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module", autouse=True)
def variants_built():
    """The -D variants are not a make target, so build them here.

    They depend on the emitted map and the assets, so `make split_v_fight`
    must have run first — which the suite's own build step does.
    """
    if not ROM.exists():
        pytest.skip("build/split_v_fight.sfc missing — run `make split_v_fight`")
    subprocess.run(["bash", "tools/build_split_v_variants.sh"],
                   cwd=SUPERFORGE, check=True, capture_output=True)
    missing = [v for v in VARIANTS if not (BUILD / f"{v}.sfc").exists()]
    assert not missing, f"variant build produced nothing for {missing}"


#: The absolute emulated frame every still in this module is photographed
#: at. It replaces a 4.0 s wall budget, which bought a host-load-dependent
#: number of frames (~240 idle, fewer under contention, and `load_rom`'s own
#: docstring records the rate degrading with run length). Every assertion
#: below compares PIXELS, so the frame has to be the same frame on every
#: host — see MesenRunner.boot_to_frame.
SHOT_FRAME = 240


def _shot(runner, name, out, frame=SHOT_FRAME):
    runner.boot_to_frame(str(BUILD / f"{name}.sfc"), frame)
    p = Path(out)
    runner.take_screenshot(str(p))
    return Image.open(p).convert("RGB")


def _dominant(img, x0, x1, y0, y1, n=6):
    return [c for c, _ in Counter(
        img.getpixel((x, y)) for x in range(x0, x1) for y in range(y0, y1)
    ).most_common(n)]


# ---------------------------------------------------------------------------
# THE HEADLINE CLAIM: a merged split view IS a no-split view
# ---------------------------------------------------------------------------

def test_merged_view_is_pixel_identical_to_the_no_split_reference(runner, tmp_path):
    """The rail's whole thesis, and the only assertion that can prove it.

    sv_hold_merge runs the FULL split machinery — window 1 armed, both cameras
    live, BG2 clipped to the right half — with the fighters close enough that
    the divergence eases to zero. sv_nowin runs one camera with window masking
    off and BG3 off the main screen. If the seam were even one pixel wrong, or
    either camera off by one, or the divider not fully ramped out, these two
    frames would differ.

    A `spread == 0` assertion would pass with all three of those broken.
    """
    merged = _shot(runner, "sv_hold_merge", tmp_path / "merge.png")
    ref = _shot(runner, "sv_nowin", tmp_path / "nowin.png")
    diff = [(x, y) for y in range(SCREEN_H) for x in range(SCREEN_W)
            if merged.getpixel((x, y)) != ref.getpixel((x, y))]
    assert not diff, (
        f"{len(diff)} pixel(s) differ between the merged split and the "
        f"no-split reference; first at {diff[:5]} — the seam is visible")


def test_the_reference_is_not_trivially_equal_to_everything(runner, tmp_path):
    """The positive control for the test above.

    A comparison that passes because both frames are (say) uniformly black
    would prove nothing. The SPLIT state must differ from the same reference,
    and differ in the middle of the screen where the divider lives.
    """
    split = _shot(runner, "sv_hold_split", tmp_path / "split.png")
    ref = _shot(runner, "sv_nowin", tmp_path / "nowin2.png")
    diff = [(x, y) for y in range(SCREEN_H) for x in range(SCREEN_W)
            if split.getpixel((x, y)) != ref.getpixel((x, y))]
    assert diff, "the split state is identical to the no-split reference too — " \
                 "the merge test above is comparing a constant, not a verdict"
    xs = [x for x, _ in diff]
    assert min(xs) < CENTRE < max(xs), (
        "the split differs from the reference, but only on one side of the "
        f"seam (x range {min(xs)}..{max(xs)}) — that is not a split")


# ---------------------------------------------------------------------------
# THE DIVIDER: present when split, GONE when merged
# ---------------------------------------------------------------------------

def test_the_divider_occupies_the_seam_when_split(runner, tmp_path):
    """Read the seam column out of the rendered frame.

    The bar is BG3 revealed inside window 2. Asserting on WH2/WH3 would be the
    proxy: the band can be perfectly programmed and show nothing if W34SEL's
    polarity is inverted or BG3 is behind the floor.
    """
    split = _shot(runner, "sv_hold_split", tmp_path / "split_bar.png")
    ref = _shot(runner, "sv_nowin", tmp_path / "nowin3.png")
    # a column at the seam, over the SKY rows where the floor cannot explain it
    seam = [split.getpixel((CENTRE, y)) for y in range(40, 160)]
    plain = [ref.getpixel((CENTRE, y)) for y in range(40, 160)]
    assert len(set(seam)) >= 1 and seam != plain, (
        "the seam column is identical to the no-split reference — no divider "
        "is being drawn")
    # ...and it is a VERTICAL bar: the same tone runs the height of the sky
    assert len(set(seam)) <= 3, (
        f"the seam column is not a solid bar ({len(set(seam))} distinct tones) "
        "— window 2 is probably not clipping BG3 to a band")


def test_the_divider_is_ABSENT_at_merge(runner, tmp_path):
    """The ramp-to-zero half, and the one that makes the split seamless.

    hw = spread >> 4, and at hw == 0 the band is written INVERTED (left 1,
    right 0) so the PPU treats window 2 as inactive. Get that wrong — clamp hw
    to a minimum of 1, say — and the divider becomes a permanent 3px scar down
    the middle of a merged view. This is the assertion that catches it.
    """
    merged = _shot(runner, "sv_hold_merge", tmp_path / "merge_bar.png")
    seam = [merged.getpixel((CENTRE, y)) for y in range(40, 160)]
    sky = [merged.getpixel((CENTRE - 40, y)) for y in range(40, 160)]
    assert seam == sky, (
        "the seam column differs from plain sky in the MERGED view — the "
        "divider band did not ramp out, so the merge is not seamless")


# ---------------------------------------------------------------------------
# THE FIGHTERS: which team is in which half, and where their feet land
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variant,left,right", [
    ("sv_hold_split", RED_TEAM, BLUE_TEAM),
    ("sv_cross", BLUE_TEAM, RED_TEAM),
])
def test_the_split_follows_a_side_swap(runner, tmp_path, variant, left, right):
    """Read the TEAM COLOUR out of each half of the frame.

    The crossed build reaches its state by arithmetic through the same code
    path as the uncrossed one (a negative hold), so this exercises the real
    swap rather than a special case built for the test. Asserting on the
    `crossed` word instead would pass while both fighters drew on the same
    side, which is the bug a side-swap actually ships.
    """
    img = _shot(runner, variant, tmp_path / f"{variant}.png")
    lo = _dominant(img, 56, 80, 166, 182)
    ro = _dominant(img, 184, 208, 166, 182)
    assert left in lo, f"{variant}: left half {lo} does not contain {left}"
    assert right in ro, f"{variant}: right half {ro} does not contain {right}"
    assert right not in lo and left not in ro, (
        f"{variant}: both team colours appear in the same half — the fighters "
        "are not being drawn against their own cameras")


def test_both_fighters_are_on_screen_at_full_split(runner):
    """The regression for the wrap bug that hid the LEFT fighter.

    screen x was computed as (world - cam - half) & $1FF, so a wrapped camera
    carried the wrap into bit 8 — which the OBJ hardware reads as X9 and places
    the sprite past the right edge. The frame still looked plausible: one
    fighter, correctly drawn. This asserts on the OAM bytes the PPU reads, so
    an off-screen sprite cannot hide behind a nice-looking screenshot.
    """
    runner.boot_rom(str(BUILD / "sv_hold_split.sfc"), frames=SHOT_FRAME)
    oam = runner.read_bytes(O, 0, 8)
    hi = runner.read_bytes(O, 512, 1)[0]
    for slot, base in ((O_F1, 0), (O_F2, 4)):
        x, y = oam[base], oam[base + 1]
        x9 = (hi >> (slot * 2)) & 1
        size = (hi >> (slot * 2 + 1)) & 1
        assert x9 == 0, (
            f"slot {slot}: X9 set (x = {x + 256}) — the sprite is off the "
            "right edge; the camera wrap leaked into bit 8")
        assert 0 <= x <= SCREEN_W - 32, f"slot {slot}: x={x} is not fully on screen"
        assert y == KNIGHT_Y, f"slot {slot}: y={y}, expected {KNIGHT_Y}"
        assert size == 1, f"slot {slot}: size bit clear — not a 32x32 sprite"


def test_the_fighters_feet_sit_ON_the_grass(runner, tmp_path):
    """The foot anchor, read as PIXELS rather than as the OAM y.

    The art's content bottom is 28, not the 32 box height. Anchoring to the box
    would hang both fighters four pixels above the surface — the reference's
    floating-feet defect, which a y-register assertion cannot see because the
    OAM y would be exactly what the code intended.

    THE SURFACE IS FOUND, NOT COMPUTED. Mesen captures 239 lines (the overscan
    frame), not the 224-line active area, so a screen row derived from
    `tilemap_row * 8` is off by the capture's own offset — which is a property
    of the harness, not of the ROM. Deriving the surface from the frame keeps
    the assertion about the thing it claims: the feet rest on the ground,
    wherever the ground turns out to be drawn.
    """
    img = _shot(runner, "sv_hold_split", tmp_path / "feet.png")
    x0, x1 = 56, 80                     # the left fighter's column band

    # THE GROUND TOP IS WHERE THE SKY STOPS, not where a known ground tone
    # starts. Two earlier shapes of this check were wrong in opposite ways: a
    # tone list sampled across the full screen width picked up the DIVIDER, so
    # a bevel palette change moved the answer; a tone list sampled deep at the
    # bottom of the frame saw only DIRT, and so skipped the grass lip and
    # blades above it and reported a 4px gap under a sprite that was resting
    # correctly. "No sky in this column" needs no tone list at all.
    # ...and the scan starts BELOW the first sky row, because Mesen's 239-line
    # capture has black overscan borders at the top: row 0 contains no sky
    # either, and a naive first-no-sky scan answers 0.
    sky = Counter(img.getpixel((x, 60)) for x in range(x0, x1)).most_common(1)[0][0]
    first_sky = next((y for y in range(img.height)
                      if any(img.getpixel((x, y)) == sky for x in range(x0, x1))),
                     None)
    assert first_sky is not None, "no sky in the column band at all"
    top = next((y for y in range(first_sky, img.height)
                if all(img.getpixel((x, y)) != sky for x in range(x0, x1))),
               None)
    assert top is not None, "the column band never stops being sky"

    reds = [y for y in range(img.height)
            if any(img.getpixel((x, y)) == RED_TEAM for x in range(x0, x1))]
    assert reds, "no fighter pixels in the left column band"
    assert reds[-1] < top, (
        f"fighter pixels reach row {reds[-1]}, at or below the ground top "
        f"({top}) — the sprite is embedded in the floor")
    assert top - reds[-1] <= 2, (
        f"the fighter's lowest pixel is row {reds[-1]} but the ground starts "
        f"at {top} — a {top - reds[-1] - 1}px gap; the sprite is floating")


# ---------------------------------------------------------------------------
# THE ASSET CHAIN, ground-truthed against something we did not produce
# ---------------------------------------------------------------------------

# An OPTIONAL external reference tree, named by `SF_REFERENCE_TREE`.
# Unset on an ordinary runner, which is why the cases below SKIP rather
# than fail: they are ground-truth checks against a second, independent
# implementation, and there is nothing to check against when none is on
# disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE = _REFERENCE_TREE
_needs_reference_tree = pytest.mark.skipif(
    not (REFERENCE / "templates" / "split_v_fight" / "assets" / "knight.inc").exists(),
    reason="the reference tree is not on disk (bare runner); asset ground-truth "
           "cannot be checked against an independent rendering here")


@_needs_reference_tree
def test_the_knight_trace_matches_the_reference_conversion():
    """The converter, against a blob THIS repo did not produce.

    Byte-identity to the reference's knight.inc is not a tautology here: that blob was
    produced by png2snes, a different implementation, and this port is a
    separate reading of the same PNG. It is exactly the check that caught the
    --anchor bug — png2snes passes an already-boxed frame through untouched
    ("keep author's framing", cmd_sprite:372-376), so the `--anchor bottom` in
    knight.inc's recorded command line is INERT. Applying it anyway produced a
    sprite with the right palette, the right byte count, and the art 4px low.
    """
    import re
    inc = (REFERENCE / "templates" / "split_v_fight" / "assets" / "knight.inc").read_text()
    body = re.split(r"\n[A-Za-z_][A-Za-z0-9_]*:", inc.split("knight_chr:")[1])[0]
    reference = bytes(int(m, 16) for m in re.findall(r"\$([0-9A-Fa-f]{2})", body))
    ours = (BUILD / "assets" / "sv_knight_chr.bin").read_bytes()
    assert ours == reference, (
        "the fighter CHR differs from the reference's own conversion of the same "
        "source PNG — the trace has drifted (check the box/anchor guard)")


@_needs_reference_tree
def test_the_stage_palette_is_the_packs_own_ramp():
    """The stage palette is DERIVED from the Four Seasons Platformer Tileset
    (Rotting Pixels) — this rail's NON-CC0 pack, under that author's own
    permissive grant; see NOTICE. It must land in the band-safe order the
    authored tiles assume. The generator asserts this at build time; this
    checks the bytes that actually reached the ROM's blob, which is the other
    end of the same chain.

    CGRAM word 0 is excluded deliberately: it is the BACKDROP, overridden to
    the sky colour, and is not part of the pack's ramp.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gen_sv", SUPERFORGE / "tools" / "gen_split_v_assets.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    blob = (BUILD / "assets" / "sv_stage_pal.bin").read_bytes()
    words = [blob[i] | (blob[i + 1] << 8) for i in range(0, 16, 2)]
    assert words[0] == gen.SKY_BGR15, "CGRAM word 0 is not the sky backdrop"
    assert words[1:8] == gen.EXPECTED_STAGE_PAL[1:8], (
        f"the stage ramp drifted from the pack's band-safe order: {words[1:8]}")


def test_the_uploaded_palettes_are_the_blobs_byte_for_byte(runner):
    """The DESTINATION region, read back off the hardware.

    A generator-only check proves the bytes were produced; it says nothing
    about whether they were uploaded. A later sweep shipped with the `[sprites]` toml
    section silently unrecognised and an invisible player for exactly this
    reason. So: read CGRAM out of the PPU and compare to the blobs.
    """
    runner.boot_rom(str(ROM), frames=180)
    for name, at, blob in (
        ("stage", C_STAGE_PAL, "sv_stage_pal.bin"),
        ("bevel", C_BEVEL_PAL, "sv_bevel_pal.bin"),
        ("knight red", C_KNIGHT_R, "sv_knight_pal_r.bin"),
        ("knight blue", C_KNIGHT_B, "sv_knight_pal_b.bin"),
    ):
        src = (BUILD / "assets" / blob).read_bytes()
        n = {"stage": 16, "bevel": 8}.get(name, 32)   # only the claimed words
        got = runner.read_bytes(C, at * 2, n)
        assert got == src[:n], (
            f"{name} palette in CGRAM does not match its blob — uploaded "
            f"wrong or not at all\n  cgram: {got.hex()}\n  blob : {src[:n].hex()}")


def test_the_fighter_CHR_actually_reached_OBJ_VRAM(runner):
    """The other destination-region check, and the one whose absence rendered
    COLOUR NOISE on first boot: OBJ VRAM is random at power-on, and OAM
    pointing at it is a perfectly valid sprite made of garbage.
    """
    runner.boot_rom(str(ROM), frames=180)
    src = (BUILD / "assets" / "sv_knight_chr.bin").read_bytes()
    got = runner.read_bytes(V, V_OBJ_CHR * 2, len(src))
    assert got == src, "the fighter CHR in OBJ VRAM does not match its blob"


# ---------------------------------------------------------------------------
# STATE-CYCLE COVERAGE: the whole separate / merge / swap arc, not a snapshot
# ---------------------------------------------------------------------------

def test_the_autodemo_walks_the_WHOLE_cycle(runner, tmp_path):
    """A rail tested only on its opening frame ships its endings broken.

    The autodemo marches the fighters wall to wall THROUGH each other, so one
    boot plays separate -> merge -> cross -> separate-on-the-other-side. This
    samples that arc and requires every phase to actually occur: a merged frame
    (no divider), a split frame (divider present), and a frame in which the
    team colours have swapped halves relative to the start.

    Sampling one frame would pass on a ROM whose divider never retracts, or
    whose fighters never cross — both of which look fine in a still.
    """
    # An absolute start frame plus an exact 12-frame step per sample means
    # this walks the SAME 40 instants of the demo on every host. Under the
    # 2 s + run_frames(12) it replaces, each sample landed wherever the host
    # had got to — and the arc assertions below ("a merged frame occurred",
    # "the fighters swapped sides") are exactly the shape that passes or
    # fails on which instants were sampled.
    runner.boot_to_frame(str(BUILD / "sv_autodemo.sfc"), 120)
    seen_merged = seen_split = False
    orders = set()
    for i in range(40):
        runner.frame_step(12)
        p = tmp_path / f"demo_{i:02d}.png"
        runner.take_screenshot(str(p))
        img = Image.open(p).convert("RGB")
        sky = img.getpixel((CENTRE - 48, 60))
        seam = [img.getpixel((CENTRE, y)) for y in range(50, 120)]
        if all(c == sky for c in seam):
            seen_merged = True
        elif any(c != sky for c in seam):
            seen_split = True
        left = _dominant(img, 8, SCREEN_W // 2 - 8, 150, 190, n=8)
        right = _dominant(img, SCREEN_W // 2 + 8, SCREEN_W - 8, 150, 190, n=8)
        if RED_TEAM in left and BLUE_TEAM in right:
            orders.add("red_left")
        if BLUE_TEAM in left and RED_TEAM in right:
            orders.add("blue_left")

    assert seen_merged, "the autodemo never reached a MERGED frame — the " \
                        "divider never retracts"
    assert seen_split, "the autodemo never reached a SPLIT frame"
    assert orders == {"red_left", "blue_left"}, (
        f"the fighters never swapped sides over the whole demo: saw {orders} "
        "— a crossover that does not follow through is the bug this rail is "
        "for")


def test_walking_into_a_wall_STOPS(runner, tmp_path):
    """The arena clamp, asserted as the picture going still.

    Adversarial input — holding a direction into a wall forever — must stop the
    fighters, not wrap them. Reading the clamped DP word would be the proxy;
    what a player sees is that the world stops moving. So: hold LEFT on both
    pads well past the arena width and require two frames a second apart to be
    identical.
    """
    runner.boot_to_frame(str(ROM), 120)
    # P2's pad is latched once and PERSISTS: `frame_step` re-latches only the
    # port it is given, so pad 1 keeps holding LEFT for every step below.
    runner.set_input(1, left=True)
    # 240 EMULATED frames of held LEFT, then 60 more between the two stills.
    # `frame_step` carries the pad state per frame, so the hold is exact and
    # "a second apart" means 60 frames apart rather than however many the
    # host managed. Under the run_frames(240) this replaces, a loaded box
    # could deliver far fewer than the (232-24)/2 frames the clamp needs and
    # the two stills would differ because the fighters were STILL WALKING.
    runner.frame_step(240, left=True)
    a = tmp_path / "wall_a.png"
    runner.take_screenshot(str(a))
    runner.frame_step(60, left=True)
    b = tmp_path / "wall_b.png"
    runner.take_screenshot(str(b))
    runner.set_input(1)
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    diff = [(x, y) for y in range(ia.height) for x in range(ia.width)
            if ia.getpixel((x, y)) != ib.getpixel((x, y))]
    assert not diff, (
        f"{len(diff)} pixel(s) still changing after 240 frames of held LEFT — "
        "the arena clamp is not holding")


# ---------------------------------------------------------------------------
# THE SOURCE RAIL'S PUBLISHED GIF as an oracle for the divider
# ---------------------------------------------------------------------------

REFERENCE_GIF = REFERENCE / "docs" / "screenshots" / "gifs" / "split_v_fight.gif"
_needs_gif = pytest.mark.skipif(
    not REFERENCE_GIF.exists(),
    reason="the reference's published GIF is not on disk (bare runner)")


@_needs_gif
def test_the_divider_tones_match_the_SOURCE_RAILS_published_render(runner, tmp_path):
    """The bevel, against the reference's own showcase GIF.

    This is the strongest oracle available for the divider: a rendering of the
    same rail, produced by a different codebase, published before this port
    existed. It cannot agree with our bugs.

    It earned its place. The bevel shipped twice wrong and both stills looked
    fine — first drawing in the STAGE's palette (a bare tilemap entry selects
    2bpp palette 0, not the bevel's claim at CGRAM 8..11), then with a warm
    brown shadow taken from a value quoted in the reference's source that turned out
    to describe a band-safety PROBE rather than the bevel. Every
    "divider is present" assertion passed throughout. Only comparing the
    rendered TONES against an independent render caught either.
    """
    from PIL import ImageSequence

    def tones(img, sky):
        return {c for c in (img.getpixel((x, y))
                            for x in range(118, 138) for y in range(40, 150))
                if c != sky}

    ref_frames = [f.convert("RGB").copy()
                  for f in ImageSequence.Iterator(Image.open(REFERENCE_GIF))]
    ref = set()
    for f in ref_frames:
        ref |= tones(f, f.getpixel((CENTRE - 56, 60)))

    ours = _shot(runner, "sv_hold_split", tmp_path / "bevel.png")
    got = tones(ours, ours.getpixel((CENTRE - 56, 60)))

    # The GIF is palette-quantised, so compare the DOMINANT bevel tones rather
    # than demanding set equality against every antialiasing artefact in it.
    for tone in ((156, 156, 156), (255, 255, 255), (49, 49, 49)):
        assert tone in ref, f"{tone} is not in the reference's own render — oracle drift"
        assert tone in got, (
            f"the divider is missing the reference's {tone}; ours renders {sorted(got)}"
            " — the bevel is using the wrong palette or the wrong tones")
