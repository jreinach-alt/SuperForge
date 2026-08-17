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
    """The arena clamp, asserted as the world stopping — not as the pose.

    Adversarial input — holding a direction into a wall forever — must stop the
    fighters, not wrap them. Reading the clamped DP word would be the proxy;
    what a player sees is that the world stops moving. So: hold LEFT on both
    pads well past the arena width and require two stills a second apart to
    agree about where everything IS.

    THE INTERVAL IS THE IDLE CYCLE, AND IT IS DERIVED, not chosen. This case
    was written as whole-frame pixel equality across a flat 60 frames, while
    the fighters had exactly one pose to stand in. They now breathe, so two
    stills 60 apart differ by ~120 pixels of *animation* over a world that is
    frozen solid — a true statement about the rail, failing a case whose name
    is about the clamp.

    The fix is not to weaken the assertion but to land it where the poses
    coincide: an idle cycle is `len * rate` frames, and both of those ship in
    `sv_anim_meta.bin` beside the frames they bound. Reading them keeps the
    strongest possible claim — every pixel identical — and keeps it correct if
    the animation is ever retimed. Loosening it to "the columns their colour
    occupies are identical" was tried first and is measurably weaker: the two
    idle poses differ in silhouette by one column, so the loose form has to
    tolerate exactly the kind of one-pixel drift a clamp bug produces.
    """
    meta = (BUILD / "assets" / "sv_anim_meta.bin").read_bytes()
    idle_len, idle_rate = meta[0], meta[1]          # table 0 = idle
    period = idle_len * idle_rate
    assert period > 1, ("the idle table is a single held pose, so this case is "
                        "no longer landing on a cycle — re-derive the interval")

    runner.boot_to_frame(str(ROM), 120)
    # P2's pad is latched once and PERSISTS: `frame_step` re-latches only the
    # port it is given, so pad 1 keeps holding LEFT for every step below.
    runner.set_input(1, left=True)
    # 240 EMULATED frames of held LEFT, then one idle cycle between the two
    # stills. `frame_step` carries the pad state per frame, so the hold is
    # exact and the interval is the animation's own period rather than however
    # many frames the host managed. Under the run_frames(240) this replaces, a
    # loaded box could deliver far fewer than the (232-24)/2 frames the clamp
    # needs and the two stills would differ because the fighters were STILL
    # WALKING.
    runner.frame_step(240, left=True)
    a = tmp_path / "wall_a.png"
    runner.take_screenshot(str(a))
    # ...AND THE SHOT ITSELF COSTS ONE EMULATED FRAME. A picture pair meant to
    # sit N frames apart is N-1 advances plus the shot (the harness states it,
    # and tests/test_wait_primitives.py pins it). Stepping the full period puts
    # the two stills 49 frames apart on a 48-frame cycle, which lands them on
    # different idle steps — a one-frame error that reads as a clamp failure.
    runner.frame_step(period - 1, left=True)
    b = tmp_path / "wall_b.png"
    runner.take_screenshot(str(b))
    runner.set_input(1)
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    diff = [(x, y) for y in range(ia.height) for x in range(ia.width)
            if ia.getpixel((x, y)) != ib.getpixel((x, y))]
    assert not diff, (
        f"{len(diff)} pixel(s) still changing after 240 frames of held LEFT, "
        f"across a whole {period}-frame idle cycle — the arena clamp is not "
        f"holding; first at {diff[:5]}")

    # ...and the case is not passing over an empty stage: a fighter must be
    # in the picture for its stillness to mean anything.
    band = range(KNIGHT_Y - 4, KNIGHT_Y + 36)
    assert any(ia.getpixel((x, y)) == RED_TEAM
               for x in range(SCREEN_W) for y in band), \
        "no fighter pixels in the sprite band at all — this case is " \
        "asserting over nothing"


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


# ---------------------------------------------------------------------------
# THE FIGHT — the round, the swing, the jump and the bars, driven end to end
# ---------------------------------------------------------------------------
# These use the LOCKSTEP `Machine` rather than the module's MesenRunner, for
# one reason: a two-player fight needs BOTH pads, and `Machine.advance` latches
# both by construction while `set_input` on a parked runner is silently
# ineffective (mesen_runner.set_input's own second trap). Mixing the two
# harnesses in one module is the shape test_seam_irq_trial already ships.
from machine import Machine  # noqa: E402
from frame_geometry import PICTURE_TOP, png_row  # noqa: E402

# The rail's declared fight shape, restated as an ORACLE — deliberately
# independent of the ROM, exactly like the geometry block at the top.
HP_MAX = 4
COUNT_STEP, COUNT_BEATS = 32, 4
COUNT_LEN = COUNT_STEP * COUNT_BEATS
R_COUNT, R_LIVE, R_KO = 0, 1, 2
ST_IDLE, ST_WALK, ST_JUMP, ST_ATK, ST_HIT, ST_KO = range(6)
SWING_LEN, SWING_FIRST, SWING_LAST = 20, 7, 14

O_LIFE = _sym("ES_O_LIFE", "fight")["start"]
O_COUNT = _sym("ES_O_COUNT", "fight")["start"]
O_BLADE = _sym("ES_O_BLADE", "fight")["start"]


def _dp(name):
    """A scene DP word's WorkRam offset. Asked for, never hardcoded."""
    return _sym(name, "fight")["start"]


def _u16(m, name, pair=0):
    b = m.read_bytes(W, _dp(name) + pair, 2)
    return b[0] | (b[1] << 8)


def _oam_tiles(m, first, count):
    """The TILE byte of `count` OAM entries from slot `first`.

    OAM is the region the PPU reads to build the picture, so a tile byte here
    is the sprite the hardware will fetch — not a program variable that ought
    to imply it.
    """
    raw = m.read_bytes(O, first * 4, count * 4)
    return [raw[i * 4 + 2] for i in range(count)]


def _oam_y(m, slot):
    return m.read_bytes(O, slot * 4 + 1, 1)[0]


def _hud_tile(slot_index):
    """HUD sheet slot -> its first tile, mirroring the generator's layout."""
    return (slot_index // 8) * 32 + (slot_index % 8) * 2


T_LIFE_FULL, T_LIFE_EMPTY = _hud_tile(0), _hud_tile(1)
T_D3, T_D2, T_D1 = _hud_tile(2), _hud_tile(3), _hud_tile(4)
T_FIGHT = [_hud_tile(i) for i in range(5, 10)]      # F I G H T


def _anim_tile(state, step=0):
    """The tile the anim blob names for a state's step, from the SHIPPED blob.

    Read out of `sv_anim.bin` rather than recomputed: the test then asserts
    that the PPU is fetching the frame the animation table names, which is the
    claim, instead of asserting the table against a second copy of itself.
    """
    blob = (BUILD / "assets" / "sv_anim.bin").read_bytes()
    return blob[state * 4 + step]


def test_the_round_counts_3_2_1_FIGHT_and_only_then_goes_live():
    """The whole countdown cycle, out of OAM and off the screen.

    DRIVEN AS A CYCLE, NOT SAMPLED. A snapshot at one beat passes on a ROM
    whose count sticks on "3" forever, or one that goes live while the banner
    is still up. This walks every frame of the count, records which glyph the
    PPU was pointed at, and requires the four beats IN ORDER followed by a
    live round with nothing left on the count's slots.

    The digits are read as OAM tile bytes (the sprite the hardware fetches)
    and the FIGHT beat is confirmed in the rendered PICTURE too, because five
    correctly-addressed sprites parked off-screen would satisfy OAM alone.
    """
    seen, live_at = [], None
    with Machine(str(ROM)) as m:
        m.advance(20)                       # past the fade, into the count
        for frame in range(COUNT_LEN + 40):
            m.advance(1)
            tiles = _oam_tiles(m, O_COUNT, 5)
            ys = [_oam_y(m, O_COUNT + i) for i in range(5)]
            shown = [t for t, y in zip(tiles, ys) if y < SCREEN_H]
            if shown and (not seen or seen[-1] != shown):
                seen.append(list(shown))
            if _u16(m, "US_RSTATE") == R_LIVE and live_at is None:
                live_at = frame
                break
        assert live_at is not None, "the round never went live"
        # ...and the banner comes down with it. TWO settle frames, because the
        # tick STAGES the OAM shadow and the next VBlank commits it: on the
        # frame the round word flips, hardware OAM still holds the count
        # (Machine.advance's stated one-frame presentation lag). Asserting on
        # the flip frame reads the previous picture, which is a harness fact,
        # not a defect.
        m.advance(2)
        assert all(_oam_y(m, O_COUNT + i) >= SCREEN_H for i in range(5)), \
            "the count's sprites are still on screen after the round went live"

    assert seen == [[T_D3], [T_D2], [T_D1], T_FIGHT], (
        f"the count did not run 3, 2, 1, FIGHT in order: {seen}")


def test_the_FIGHT_banner_is_actually_ON_SCREEN(tmp_path):
    """The other half of the case above: the banner is drawn, not just addressed.

    Five sprites can carry the right tiles, the right palette and the right
    name-table bit and still be invisible — parked, behind a layer, or clipped
    by the window this whole rail is built out of. So this reads PIXELS: the
    banner's own bright glyph colour has to appear across the width the five
    letters span, and NOT appear once the round is live.
    """
    glyph = (247, 214, 206)                 # OBJ palette 0's brightest entry
    band = range(png_row(84), png_row(84) + 16)   # the banner's own 16 rows
    x0, x1 = CENTRE - 40, CENTRE + 40
    with Machine(str(ROM)) as m:
        m.advance(20)
        m.run_until(lambda mm: _oam_tiles(mm, O_COUNT, 5) == T_FIGHT,
                    max_frames=COUNT_LEN + 60, what="the FIGHT beat")
        m.advance(2)                        # the OAM presentation lag
        m.screenshot(str(tmp_path / "fight.png"))
        during = Image.open(tmp_path / "fight.png").convert("RGB")
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                    max_frames=COUNT_LEN + 60, what="the round going live")
        m.advance(2)
        m.screenshot(str(tmp_path / "live.png"))
        after = Image.open(tmp_path / "live.png").convert("RGB")

    hits = [(x, y) for y in band for x in range(x0, x1)
            if during.getpixel((x, y)) == glyph]
    assert len(hits) > 60, (
        f"only {len(hits)} banner pixels in the picture at the FIGHT beat — "
        "the letters are addressed but not drawn")
    spread = max(x for x, _ in hits) - min(x for x, _ in hits)
    assert spread > 56, (
        f"the banner's lit pixels span only {spread}px — one letter is "
        "drawing over the others rather than five sitting side by side")
    assert not [(x, y) for y in band for x in range(x0, x1)
                if after.getpixel((x, y)) == glyph], \
        "the banner is still on screen after the round went live"


def test_a_swing_runs_startup_active_recovery_and_lands_exactly_one_hit():
    """The swing's whole cycle, and the latch that makes it one strike.

    Every frame of one swing is walked, and three things are required in
    order: the attacker's OAM tile is the ATTACK table's frame while the swing
    runs; the defender's tile becomes the pack's own `hit` frame on exactly
    one frame boundary; and the defender's life falls by EXACTLY ONE across
    the whole swing — the active window is eight frames long, so a missing
    latch would take eight segments and there are only four.
    """
    with Machine(str(ROM)) as m:
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                    max_frames=COUNT_LEN + 90, what="the round going live")
        m.advance(14, pad1={"right": True})     # close to inside reach
        before = _u16(m, "US_HP", 2)
        assert before == HP_MAX, "the defender did not start on a full bar"

        atk_frames, hit_frames = 0, 0
        m.advance(1, pad1={"a": True})
        for _ in range(30):
            m.advance(1)
            if _oam_tiles(m, O_F1, 1)[0] == _anim_tile(ST_ATK):
                atk_frames += 1
            if _oam_tiles(m, O_F2, 1)[0] == _anim_tile(ST_HIT):
                hit_frames += 1
        after = _u16(m, "US_HP", 2)

    assert atk_frames >= 4, (
        f"the attacker held the attack pose for only {atk_frames} frames — "
        "the swing has no startup/active/recovery to speak of")
    assert hit_frames >= 4, (
        f"the defender showed the pack's hit frame for only {hit_frames} "
        "frames — the reaction is not being played")
    assert after == before - 1, (
        f"one swing took {before - after} life segments, not 1 — the "
        "one-hit-per-swing latch is not holding across the active window")


def test_a_jump_rises_peaks_falls_lands_and_comes_to_REST():
    """Ascent, apex, descent, landing, rest — read as the sprite's OAM y.

    An apex-only assertion is the house's own recorded trap: it ships a broken
    landing, because the apex depends only on the launch speed while the
    landing depends on the integration ever reaching exactly zero. So this
    requires the whole arc AND that the fighter comes to rest on the floor
    line it left — and on the same COLUMN, which is the rail's own promise
    that a hop is a commitment rather than a free reposition.
    """
    with Machine(str(ROM)) as m:
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                    max_frames=COUNT_LEN + 90, what="the round going live")
        ground_y = _oam_y(m, O_F1)
        ground_x = m.read_bytes(O, O_F1 * 4, 1)[0]
        ys = []
        m.advance(1, pad1={"b": True})
        for _ in range(60):
            m.advance(1)
            ys.append(_oam_y(m, O_F1))
        rest_y = _oam_y(m, O_F1)
        rest_x = m.read_bytes(O, O_F1 * 4, 1)[0]
        airborne_tile = None
        m.advance(1, pad1={"b": True})
        m.advance(6)
        airborne_tile = _oam_tiles(m, O_F1, 1)[0]

    apex = min(ys)                                   # smaller y = higher up
    assert apex < ground_y - 24, (
        f"the jump's apex reached OAM y {apex} against a floor line of "
        f"{ground_y} — that is not a jump, it is a step")
    top = ys.index(apex)
    assert all(ys[i] <= ys[i - 1] for i in range(1, top + 1)), \
        f"the ascent is not monotonic: {ys[:top + 1]}"
    assert all(ys[i] >= ys[i - 1] for i in range(top + 1, ys.index(ground_y, top))), \
        f"the descent is not monotonic: {ys[top:]}"
    assert rest_y == ground_y, (
        f"the fighter came to rest at OAM y {rest_y}, not the floor line "
        f"{ground_y} — the landing does not reach zero height")
    assert ys[-5:] == [ground_y] * 5, \
        f"the fighter is still moving vertically at rest: {ys[-8:]}"
    assert rest_x == ground_x, (
        f"the fighter landed at screen x {rest_x} having left from "
        f"{ground_x} — a jump is not supposed to reposition it")
    assert airborne_tile == _anim_tile(ST_JUMP), (
        "the airborne fighter is not drawn with the jump frame")


def test_jumping_over_a_swing_takes_no_damage():
    """The vertical gate — the thing that makes the jump a DEFENCE.

    Both directions, because a gate that refuses everything and one that
    refuses nothing are both constants: the same swing at the same distance
    must MISS a fighter in the air and LAND on the same fighter standing.
    Asserted on the defender's life, which is what the player reads off the
    bar.
    """
    def one_round(dodge):
        with Machine(str(ROM)) as m:
            m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                        max_frames=COUNT_LEN + 90, what="the round going live")
            m.advance(14, pad1={"right": True})
            before = _u16(m, "US_HP", 2)
            if dodge:
                # P2 leaves the ground first, then P1 swings into the space
                # where P2 was. Both pads, latched together.
                m.advance(1, pad2={"b": True})
                m.advance(8)
            m.advance(1, pad1={"a": True})
            m.advance(24)
            return before, _u16(m, "US_HP", 2)

    grounded_before, grounded_after = one_round(dodge=False)
    assert grounded_after == grounded_before - 1, (
        "the control arm did not connect, so the dodge arm below proves "
        "nothing about the gate")
    dodged_before, dodged_after = one_round(dodge=True)
    assert dodged_after == dodged_before, (
        f"the swing took {dodged_before - dodged_after} segment(s) off a "
        "fighter that was in the air — the vertical gate is not gating")


def test_the_life_bar_empties_a_segment_at_a_time_and_the_round_resets():
    """Full bar -> damage -> KO -> a fresh round, read off the BAR itself.

    The output region is the eight life sprites' tile bytes: which of them
    the PPU fetches as the full segment and which as the spent one IS the bar
    the player reads. A test on the HP word would pass with the bar frozen.

    THE RESET IS PART OF THE CYCLE. A rail that empties a bar and stops has
    shipped half a fighting game — and the clip loops on the round start, so
    the second round has to be the first round.
    """
    p2_bar = lambda mm: _oam_tiles(mm, O_LIFE + HP_MAX, HP_MAX)
    full = [T_LIFE_FULL] * HP_MAX
    with Machine(str(ROM)) as m:
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                    max_frames=COUNT_LEN + 90, what="the round going live")
        assert p2_bar(m) == full, f"P2's bar did not open full: {p2_bar(m)}"
        assert _oam_tiles(m, O_LIFE, HP_MAX) == full, "P1's bar did not open full"

        # DRIVEN LIKE A PLAYER, NOT ON A SCHEDULE. Each landed hit knocks the
        # defender back, so a fixed "walk 14, swing" cadence closes the gap on
        # the first three and misses the fourth — which it did, and which is
        # the rail working rather than the test. So: close, swing, and if the
        # BAR did not move, close again. The loop condition is read off the
        # bar itself, which is also the assertion surface.
        spent = lambda bar: sum(1 for t in bar if t == T_LIFE_EMPTY)
        states = [list(p2_bar(m))]
        for want in range(1, HP_MAX + 1):
            for _ in range(12):
                m.advance(6, pad1={"right": True})
                m.advance(1, pad1={"a": True})
                m.advance(30)
                if spent(p2_bar(m)) >= want:
                    break
            else:
                raise AssertionError(
                    f"could not land hit {want} of {HP_MAX} in 12 attempts; "
                    f"the bar reads {p2_bar(m)}")
            states.append(list(p2_bar(m)))

        assert states == [
            [T_LIFE_FULL] * 4,
            [T_LIFE_FULL] * 3 + [T_LIFE_EMPTY],
            [T_LIFE_FULL] * 2 + [T_LIFE_EMPTY] * 2,
            [T_LIFE_FULL] + [T_LIFE_EMPTY] * 3,
            [T_LIFE_EMPTY] * 4,
        ], f"the bar did not empty one segment at a time: {states}"

        assert _u16(m, "US_RSTATE") == R_KO, "an empty bar did not end the round"
        assert _oam_tiles(m, O_F2, 1)[0] == _anim_tile(ST_KO), \
            "the KO'd fighter is not drawn with the pack's death frame"

        # ...and round two is round one again.
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_COUNT,
                    max_frames=300, what="the next round's countdown")
        m.advance(2)                    # the OAM presentation lag, again: on
                                        # the flip frame the shadow the PPU is
                                        # showing was staged before the reset
        assert p2_bar(m) == full, "the new round did not restore P2's bar"
        assert _oam_tiles(m, O_LIFE, HP_MAX) == full, \
            "the new round did not restore P1's bar"
        assert _oam_tiles(m, O_COUNT, 5)[0] == T_D3, \
            "the new round's count did not start at 3"


def test_the_blade_sweeps_and_is_the_PACKS_OWN_STEEL(tmp_path):
    """The weapon: its frames advance, it is drawn, and it is the pack's art.

    THE ATTACK IS A BODY POSE PLUS A BLADE. The camelot character sheets carry
    no attack row — the pack's design is that the WEAPON carries the swing, and
    excalibur_.png ships it as its own 32x32 frames. So there are three
    separate things to prove and a tile byte alone proves only the first:

      * the blade ADVANCES through its frames across one swing, rather than
        holding the frame the first tile happened to be;
      * its steel is ON SCREEN during the active window, in pixels, and gone
        again once the swing ends;
      * those pixels are the PACK'S colours — read out of excalibur_.png
        itself, converted the way CGRAM would hold them, so an "it renders
        something" pass cannot come from the knight's palette or from noise.
    """
    from PIL import Image as _Image
    sheet = _Image.open(SUPERFORGE / "vendor" / "art" / "camelot" /
                        "excalibur_.png").convert("RGBA")
    raw = sheet.tobytes()
    pack = {tuple(raw[i:i + 3]) for i in range(0, len(raw), 4)
            if raw[i + 3] >= 128}
    # 5-bit quantisation is what CGRAM stores; the expansion back is BIT
    # REPLICATION, not a shift (tests/test_breaker.py's recorded arithmetic).
    snes = {tuple(((c >> 3) << 3) | (c >> 5) for c in rgb) for rgb in pack}

    with Machine(str(ROM)) as m:
        m.run_until(lambda mm: _u16(mm, "US_RSTATE") == R_LIVE,
                    max_frames=COUNT_LEN + 90, what="the round going live")
        m.advance(1, pad1={"a": True})
        tiles = []
        for _ in range(10):
            m.advance(2)
            tiles.append(_oam_tiles(m, O_BLADE, 1)[0])
        # ...and the PICTURE is taken inside the ACTIVE window, which is where
        # the arc frame is and where a player reads the swing. Taken after the
        # tile sweep above it lands past the end of the swing, on a blade that
        # has correctly already been put away.
        m.advance(1, pad1={"a": True})
        m.run_until(lambda mm: _u16(mm, "US_SWG") <= SWING_LAST,
                    max_frames=30, what="the swing's active window")
        m.advance(2)
        m.screenshot(str(tmp_path / "mid.png"))
        during = Image.open(tmp_path / "mid.png").convert("RGB")
        m.run_until(lambda mm: _u16(mm, "US_SWG") == 0,
                    max_frames=60, what="the swing ending")
        m.advance(3)
        m.screenshot(str(tmp_path / "after.png"))
        after = Image.open(tmp_path / "after.png").convert("RGB")
        parked = _oam_y(m, O_BLADE)

    assert len(set(tiles)) >= 3, (
        f"the blade held {len(set(tiles))} distinct frame(s) across a whole "
        f"swing: {tiles} — it is a static sprite, not a sweep")
    assert parked >= SCREEN_H, (
        f"the blade is still at y {parked} after the swing ended — it should "
        "be parked off the display")

    band = range(png_row(120), png_row(180))
    lit = [(x, y) for y in band for x in range(SCREEN_W)
           if during.getpixel((x, y)) in snes]
    assert len(lit) > 120, (
        f"only {len(lit)} pixels of the pack's own blade palette are on screen "
        "mid-swing — the weapon is addressed but not drawn")
    # THE WHOLE PICTURE, not the fighters' band, and that width is the point.
    # OAM y wraps mod 256, so a 32-tall sprite parked at the 16-tall constant
    # (240) pokes sixteen of its rows back onto scanlines 0..15 — two swords
    # sitting at the TOP of the screen for the entire clip, with an OAM entry
    # that is exactly what the code intended and a band-restricted sweep that
    # passes. It shipped that way for one recording and was caught by looking
    # at the render.
    still = [(x, y) for y in range(during.height) for x in range(SCREEN_W)
             if after.getpixel((x, y)) in snes]
    assert not still, (
        f"{len(still)} blade pixels survive after the swing ended (against "
        f"{len(lit)} during, in the fighters' band alone), at rows "
        f"{sorted({y for _, y in still})[:6]} — the blade is not being put "
        f"away, or is parked where OAM's mod-256 y wraps it back on screen")
