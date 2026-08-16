"""scroller — the BG pipeline alone, asserted against what the machine drew.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)`, which
lands on the ABSOLUTE frame N by construction rather than on ">= N" — so the
picture cases photograph the same frame on every host, and `boot_to_frame`'s
job is done by the substrate instead of by a helper.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own done-conditions:

    - boots
    - the BG renders a green checkerboard AND a red sprite is visible on top
    - each d-pad direction scrolls the BG the right way (the scroll shadows AND
      the on-screen pattern), while the sprite holds its screen position

Those are the test surface, plus the spec's reason this rail is in the
sweep at all — *"the BG pipeline alone — the sanity rail for `room_bg` outside
the `room` game."*

THE SCROLL IS RECOVERED FROM PIXELS, NOT READ FROM A VARIABLE. `_recover_shift`
searches for the displacement that makes the scrolled frame equal the reference
frame — so "the BG scrolled right by 6 px" is a statement about the drawn
picture, and a camera word that lied would make it FAIL rather than pass. The
obvious alternative (assert `ES_SCR_CAM` grew) is the proxy-variable shape
CLAUDE.md rule 2 exists to refuse: that word advances whether or not the NMI
commit, BG1SC, BG12NBA, the CHR upload or the built map are right.

STATE CYCLES, BOTH DIRECTIONS AND IDLE. The repo's own documented test smell is
a camera driven one way only, which locks that direction and ships the other
broken. So: all four directions; an out-and-back that must restore the frame
byte-for-byte; an idle stretch that must not move; opposite directions held
together; and a drive past the 256 px world wrap.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "scroller.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "scr" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam

# --- the allocator's answers, read from the emitted map ----------------------
# Addresses are ASKED FOR, never hardcoded — this reads the same map the ROM was
# assembled against, so an allocator move breaks these loudly instead of
# silently reading the wrong bytes. (`_sym`'s shape is test_split_h_2p_demo's.)
def _sym(name, scene="world"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_SCR_CHR")["start"]           # BG CHR page, VRAM words
V_MAP = _sym("ES_V_SCR_MAP")["start"]           # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_SCR_OBJ_CHR")["start"]       # OBJ CHR page, VRAM words
C_PAL = _sym("ES_C_SCR_PAL")["start"]           # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_SCR_OBJ_PAL")["start"]       # OBJ palette 0, CGRAM words

MAP_DIM = 32                            # 32x32 cells
WORLD_PX = MAP_DIM * 8                  # 256 px on each axis; the camera wraps
SPEED = 2                               # game/scroller/scroller.inc

# --- the picture, MEASURED ---------------------------------------------------
# Mesen hands back a 256x239 SNES frame: 224 active scanlines with a blank band
# above and below. Measured on this ROM at boot — rows 0..6 and 231..238 are
# uniformly black and carry no picture, so the active window is rows 7..230 and
# `PIC_Y0 = 7` converts a world/OAM y into a PNG row.
#
# BOTH CONVERSIONS WERE MEASURED THE SAME WAY AND AGREE, which is what makes
# the constant trustworthy rather than fitted: at cam (0, 0) the checkerboard's
# first green row (world y 8) lands at PNG row 15, and the sprite whose OAM Y
# is 100 occupies PNG rows 107..114. Both give +7.
PIC_Y0, PIC_H, PIC_W = 7, 224, 256

GREEN = (0, 255, 0)                     # CGRAM word 1 = $03E0
RED = (255, 0, 0)                       # OBJ CGRAM word 129 = $001F
BLACK = (0, 0, 0)                       # word 0: the backdrop

BOOT = 90                               # an absolute frame, well past the fade

# A BG-only sampling window: inside the picture, clear of the sprite's 8x8 box
# at (120..127, 107..114) by a wide margin on both axes.
BG_YS = range(20, 100)
BG_XS = range(20, 100)


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle.

    Each case builds its own Machine (the core is a process-global singleton, so
    a new Machine supersedes the old handle) and this teardown resumes the core
    at module end — the module-boundary contract `tests/conftest.py` enforces.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make scroller` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------

def _pixels(machine, name):
    """The frame as a flat RGB list. Costs one emulated frame (pads released)."""
    path = machine.take_screenshot(str(BUILD / "shots" / f"scroller_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _recover_shift(ref, moved, axis, ys=BG_YS, xs=BG_XS, span=7):
    """Every displacement s for which `moved` IS `ref` shifted by s.

    The picture is what is compared — no engine word is consulted. Returns
    every s in [-span, span] that reproduces the whole sampled window exactly.

    THE DEFAULT SPAN IS 7 BECAUSE THE PATTERN HAS A PERIOD. A checkerboard of
    8 px cells repeats every 16 px, so s is only ever recoverable modulo 16 and
    a window 16 or more wide returns the whole alias class (measured: at a true
    +6 a span of 12 returns `[-10, 6]`). +-7 is the widest window that can hold
    at most one member of a class, which is what makes a single-valued answer a
    real measurement rather than a lucky pick. Callers therefore keep the
    expected displacement inside +-7.

    Positive s means the pattern moved LEFT/UP on screen (the camera advanced
    right/down), because `moved(x) == ref(x + s)`.
    """
    out = []
    for s in range(-span, span + 1):
        if axis == "x":
            ok = all(_at(ref, (x + s) % PIC_W, y) == _at(moved, x, y)
                     for y in ys for x in xs)
        else:
            ok = all(_at(ref, x, (y - PIC_Y0 + s) % PIC_H + PIC_Y0)
                     == _at(moved, x, y)
                     for y in ys for x in xs)
        if ok:
            out.append(s)
    return out


def _expected_cell(col, row):
    """The checkerboard rule the enter-time build loop implements."""
    return (col ^ row) & 1


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================
# A pipeline that silently no-ops is the failure these catch. Asserting only on
# the rendered colours would not: the picture is drawn from CHR + tilemap +
# palette together, and several partial failures render something plausible.

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base, against scr_bg_chr.bin.

    Both tiles, including the EMPTY one. Tile 0 is all-zero and would look
    identical if the upload never happened and power-on VRAM chanced to be
    clear — which is exactly why it is uploaded explicitly (rule 5) and why
    this reads the whole claim rather than the tile that shows a colour.
    """
    want = (ASSETS / "scr_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"the BG character block at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed OBJ CHR base, against scr_obj_chr.bin."""
    want = (ASSETS / "scr_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_both_palettes_are_the_destinations_of_their_blobs(fresh):
    """CGRAM at both claimed bases, against the two palette blobs.

    THE WHOLE 16 WORDS EACH, not just the colour that shows. The BG claim
    starts at word 0, so this also asserts the BACKDROP the checkerboard's
    other cell renders as — the one CGRAM word this rail's picture depends on
    that no tile's pixels ever reference.
    """
    for label, base, blob in (("bg", C_PAL, "scr_bg_pal.bin"),
                              ("obj", C_OBJ, "scr_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_tilemap_is_the_checkerboard_the_enter_loop_built(fresh):
    """All 1,024 tilemap words in VRAM, each against (col ^ row) & 1.

    THE MAP IS THE ONE THING THIS RAIL HAS NO BLOB FOR — it is built at scene
    enter by scroller_bg's loop — so there is nothing to compare it to except
    the rule itself. Every cell is checked rather than a corner sample: the
    loop's whole subtlety is the row-boundary `eor`, and an off-by-one there
    leaves 31 of 32 rows correct.
    """
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    bad = []
    for row in range(MAP_DIM):
        for col in range(MAP_DIM):
            i = (row * MAP_DIM + col) * 2
            word = raw[i] | (raw[i + 1] << 8)
            if word != _expected_cell(col, row):
                bad.append((col, row, word))
    assert not bad, (
        f"{len(bad)} of {MAP_DIM * MAP_DIM} tilemap cells are not "
        f"(col ^ row) & 1; first 8: {bad[:8]}")


# =============================================================================
# 2. THE PICTURE — the composited result
# =============================================================================

def test_boot_frame_is_a_green_checkerboard_with_a_red_sprite_on_top(fresh):
    """The rail's headline done-condition, read off the drawn frame.

    Three claims in one picture, and the third is the one a per-layer byte
    assertion cannot make: the sprite is composited OVER the BG. Its 64 red
    pixels are a solid 8x8 block, so no BG cell shows through it — which is
    what "on top" means and what a VRAM-only test would miss entirely.
    """
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    greens = pic.count(GREEN)
    reds = pic.count(RED)
    assert greens > PIC_W * PIC_H // 4, (
        f"only {greens} green pixels — the checkerboard is not on screen")
    assert reds == 64, f"expected a solid 8x8 red sprite, got {reds} red pixels"
    assert greens + reds + pic.count(BLACK) == PIC_W * PIC_H, (
        "the picture holds colours other than the backdrop, the checkerboard "
        "and the sprite")

    xs = [x for x in range(PIC_W) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
          if _at(px, x, y) == RED]
    ys = [y for y in range(PIC_Y0, PIC_Y0 + PIC_H) for x in range(PIC_W)
          if _at(px, x, y) == RED]
    assert (min(xs), max(xs)) == (120, 127), "sprite x is not screen 120..127"
    assert (min(ys), max(ys)) == (107, 114), "sprite y is not screen 107..114"


def test_world_origin_lands_at_the_top_left_of_the_picture(fresh):
    """cam (0, 0) puts world cell (0, 0) at the first active scanline.

    THIS IS WHAT THE `dec` IN scr_bg_nmi_commit BUYS, and it is asserted here
    rather than trusted from pfs_bg's measurement. Scanline N shows tilemap
    line VOFS + N and the first active scanline is 1, so VOFS = cam_y would put
    world line 1 at the top. Drop the `dec` and every horizontal cell boundary
    below moves up exactly one pixel — the first green row would start at PNG
    row 14 instead of 15 — and this case fails.

    The x axis needs no correction and is asserted alongside it, so a future
    "fix" that applied the same offset to both would also fail.
    """
    px = _pixels(fresh, "origin")
    # Cell (0,0) is EMPTY -> backdrop; cell (1,0) is SOLID -> green.
    for x in range(0, 8):
        assert _at(px, x, PIC_Y0) == BLACK, f"world (x={x}, y=0) is not backdrop"
    for x in range(8, 16):
        assert _at(px, x, PIC_Y0) == GREEN, f"world (x={x}, y=0) is not green"
    # Column 0 down the first two cell rows: black 0..7, green 8..15.
    for y in range(0, 8):
        assert _at(px, 0, PIC_Y0 + y) == BLACK, f"world (x=0, y={y}) not backdrop"
    for y in range(8, 16):
        assert _at(px, 0, PIC_Y0 + y) == GREEN, f"world (x=0, y={y}) not green"


# =============================================================================
# 3. THE SCROLL — every direction, and the reverse, and idle
# =============================================================================
# The shift is recovered from the picture in every case below. N frames of a
# held direction move the drawn world by (N - 1) * SPEED px: the pad is latched
# at the park and polled at each frame boundary, and the camera the tick
# advances reaches BG1HOFS/BG1VOFS on the NEXT VBlank, so the last frame's step
# is not yet on screen when the capture is taken. MEASURED across all four
# directions at N = 2, 3 and 5 before it was written down here.

DIRS = [
    ("right", {"right": True}, "x", +1),
    ("left", {"left": True}, "x", -1),
    ("down", {"down": True}, "y", +1),
    ("up", {"up": True}, "y", -1),
]


@pytest.mark.parametrize("name,pad,axis,sign", DIRS)
def test_each_direction_scrolls_the_drawn_world_the_right_way(boot, name, pad,
                                                              axis, sign):
    """All four directions, each against the picture it actually produced.

    N = 4 puts the displacement at 6 px — inside the checkerboard's 16 px
    period, so `_recover_shift` returns exactly one answer and the sign is a
    real claim rather than a symmetry.
    """
    n = 4
    want = sign * (n - 1) * SPEED
    m = boot()
    ref = _pixels(m, f"ref_{name}")
    m.advance(n, pad1=pad)
    moved = _pixels(m, f"moved_{name}")
    got = _recover_shift(ref, moved, axis)
    detail = got or "NO displacement reproduces it — the BG did not scroll"
    assert got == [want], (
        f"holding {name} for {n} frames should displace the drawn world by "
        f"{want} px on {axis}; the picture says {detail}")


@pytest.mark.parametrize("name,pad,axis,sign", DIRS)
def test_scrolling_out_and_back_restores_the_frame_exactly(boot, name, pad,
                                                           axis, sign):
    """The REVERSE half of every state cycle, asserted as pixel identity.

    Drive 20 frames one way, 20 frames back, and the drawn frame must be what
    it was — not "close", not "a shift that recovers", identical. This is the
    direction the repo's documented smell ships broken, and it is deliberately
    phase-proof: it makes no assumption about which frame a step lands on,
    because both legs carry the same lag and it cancels.
    """
    back = {"right": "left", "left": "right", "down": "up", "up": "down"}[name]
    m = boot()
    before = _pixels(m, f"rt_before_{name}")
    m.advance(20, pad1=pad)
    m.advance(20, pad1={back: True})
    # ONE RELEASED FRAME so the last step reaches the screen. The camera is back
    # at its start the instant the final tick runs, but the picture is always
    # one commit behind it — the NMI publishes the camera the NEXT VBlank — so
    # without this the frame under test is the one 2 px short of home, and the
    # case would fail against a rail that is behaving perfectly. That lag is the
    # same one the direction cases above measure as (N - 1) * SPEED; it is a
    # property of when the picture is photographed, not of the scrolling.
    m.advance(1)
    after = _pixels(m, f"rt_after_{name}")
    assert after == before, (
        f"20 frames {name} then 20 frames {back} did not restore the frame — "
        f"{sum(a != b for a, b in zip(before, after))} pixels differ")


def test_idle_holds_the_picture_still(boot):
    """The THIRD state: nothing held. 60 frames must change nothing.

    A rail whose camera drifted, or whose NMI commit republished a stale or
    uninitialised shadow, would move here with no input at all — and both of
    the cycle tests above would still pass, because both drive.
    """
    m = boot()
    a = _pixels(m, "idle_a")
    m.advance(60)
    b = _pixels(m, "idle_b")
    assert a == b, (
        f"the picture moved over 60 idle frames — {sum(x != y for x, y in zip(a, b))}"
        f" pixels differ")


def test_opposite_directions_cancel(boot):
    """Left+Right and Up+Down held together net to zero.

    The source applies both deltas rather than branching between them, so this
    is a claim about the arithmetic and not about a priority rule. It also
    pins the one input combination a four-way `beq` chain gets wrong.
    """
    m = boot()
    a = _pixels(m, "cancel_a")
    m.advance(30, pad1={"left": True, "right": True, "up": True, "down": True})
    b = _pixels(m, "cancel_b")
    assert a == b, (
        f"holding all four directions moved the world — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


def test_the_camera_wraps_past_the_world_edge(boot):
    """Drive a full world width and the picture must come back to itself.

    The map is 32x32 cells = 256 px and the scroll latch keeps 10 bits, so the
    world is a torus — which is why this build carries no clamp, faithfully to a
    source that bounds its camera nowhere. 129 frames at 2 px is 256 px of
    committed motion under the (N-1) lag, i.e. exactly one lap.

    A clamp added "for safety" would fail here: the picture would stop moving
    before the lap completed and land somewhere else.
    """
    m = boot()
    a = _pixels(m, "wrap_a")
    m.advance(WORLD_PX // SPEED + 1, pad1={"right": True})
    b = _pixels(m, "wrap_b")
    assert b == a, (
        f"a full {WORLD_PX} px lap did not return the picture — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


# =============================================================================
# 4. THE SPRITE — it holds, and that is half the rail
# =============================================================================

def test_sprite_holds_screen_position_while_the_world_moves(boot):
    """The compositing claim, over a full four-direction drive.

    Read as OAM bytes AND as red pixels, because they fail differently: a
    dropped OAM commit leaves the hardware entry stale but correct-looking,
    while a stale X9 bit or an OBSEL clobber moves the drawn sprite with OAM
    unchanged. The rail's point is that the sprite does not move while
    everything behind it does, so both surfaces have to say so.
    """
    m = boot()
    entry0 = bytes(m.read_bytes(O, 0, 4))
    px0 = _pixels(m, "hold_0")
    for pad in ({"right": True}, {"down": True}, {"left": True}, {"up": True}):
        m.advance(15, pad1=pad)
        assert bytes(m.read_bytes(O, 0, 4)) == entry0, (
            f"OAM entry 0 changed while holding {list(pad)[0]}: "
            f"{bytes(m.read_bytes(O, 0, 4)).hex()} != {entry0.hex()}")
    px1 = _pixels(m, "hold_1")
    for px, tag in ((px0, "start"), (px1, "end")):
        reds = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
                for x in range(PIC_W) if _at(px, x, y) == RED]
        assert len(reds) == 64, f"{tag}: {len(reds)} red pixels, expected 64"
        assert min(x for x, _ in reds) == 120 and max(x for x, _ in reds) == 127
        assert min(y for _, y in reds) == 107 and max(y for _, y in reds) == 114
    assert bytes(m.read_bytes(O, 0, 4)) == entry0


def test_the_sprite_is_restaged_every_frame_not_written_once(boot):
    """The SHADOW's write counter, which is the only place the re-stage shows.

    scroller_obj rewrites the entry into the WRAM shadow every tick, and
    oam_sprites' `oam_nmi_dma` commits the whole shadow to hardware OAM every
    armed VBlank. A port that wrote the sprite once at enter renders an
    IDENTICAL picture and would pass every other case in this file, so the
    mechanism needs asserting where it is actually distinguishable.

    IT IS NOT DISTINGUISHABLE IN HARDWARE OAM, and this test asserted that
    first. Reading `writes(SnesSpriteRam, 0)` counts the blanket per-frame
    DMA, which runs whether or not `scr_obj_draw` was called — planting the
    call away left all 20 cases GREEN. That is precisely the indirect-evidence
    shape CLAUDE.md rule 2 names: a counter that "should" reflect the feature
    and in fact reflects its neighbour. The shadow byte is the feature's own
    output region, and the same plant turns this red.
    """
    shadow = _sym("ES_OAM_SHADOW", scene=None)["start"]
    m = boot()
    before = m.writes(MemoryType.SnesWorkRam, shadow)
    m.advance(30)
    after = m.writes(MemoryType.SnesWorkRam, shadow)
    assert after - before >= 30, (
        f"the OAM shadow's first byte was written {after - before} times over "
        f"30 frames — the sprite is staged once, not re-staged per frame")


# =============================================================================
# 5. WHY THIS RAIL IS IN THE SWEEP — the spec row 2
# =============================================================================

def test_the_bg_pipeline_works_outside_the_room_game(fresh):
    """The `room_bg` keystone pattern, instantiated in a game that is not `room`.

    The spec puts this rail in the sweep as *"the BG pipeline alone — the
    sanity rail for `room_bg` outside the `room` game."* `room_bg` itself is not
    composable here (it `depends` on `room_rom`, resolves six of that blob's
    symbols by name, and the allocator refuses it beside another BG feature on
    register contention — both messages are transcribed in
    `game/scroller/game.toml`). So what is under test is the PATTERN, and this
    case asserts its four stages landed AT THE ADDRESSES THE ALLOCATOR CHOSE
    FOR THIS GAME — every base below comes out of `build/scr/symbol_map.json`,
    not out of a constant anyone typed:

      1. CHR reached the claimed VRAM page
      2. the palette reached the claimed CGRAM words
      3. the tilemap reached the claimed VRAM page
      4. BG1SC/BG12NBA were programmed from the emitted encodings — which this
         cannot read back (they are write-only ports), but which the PICTURE
         proves: the PPU can only draw this checkerboard if it is fetching the
         map and the CHR from the two bases (1) and (3) just verified.

    And the fifth thing, the one `room_bg` structurally cannot have: SCROLL.
    That feature pins BG1HOFS/BG1VOFS at zero for the room's life with the
    comment *"the room is one screen and does not scroll"*. Here both axes are
    live, which the four direction cases above assert against the drawn frame.
    """
    # (1) + (3): the two BG VRAM pages are distinct, both claimed, both filled.
    assert V_CHR != V_MAP, "the CHR and tilemap claims aliased onto one page"
    chr_want = (ASSETS / "scr_bg_chr.bin").read_bytes()
    assert bytes(fresh.read_bytes(V, V_CHR * 2, len(chr_want))) == chr_want
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    assert any(raw), "the claimed tilemap page is empty"

    # (2): the palette, at the claimed base, including the backdrop word.
    pal_want = (ASSETS / "scr_bg_pal.bin").read_bytes()
    assert bytes(fresh.read_bytes(C, C_PAL * 2, len(pal_want))) == pal_want

    # THE BG AND OBJ PAGES DO NOT OVERLAP. A single-layer read cannot catch an
    # aliased claim — both regions would hold "the right bytes" while one
    # overwrote the other — so the disjointness is asserted directly.
    bg = range(V_CHR, V_CHR + _sym("ES_V_SCR_CHR")["size"])
    obj = range(V_OBJ, V_OBJ + _sym("ES_V_SCR_OBJ_CHR")["size"])
    tmap = range(V_MAP, V_MAP + _sym("ES_V_SCR_MAP")["size"])
    for a, b, an, bn in ((bg, obj, "bg chr", "obj chr"),
                         (bg, tmap, "bg chr", "tilemap"),
                         (obj, tmap, "obj chr", "tilemap")):
        assert not (set(a) & set(b)), f"{an} and {bn} claims overlap in VRAM"

    # (4): the picture. If BG1SC or BG12NBA held anything but the emitted
    # encodings, the PPU would fetch from the wrong page and this would not be
    # a checkerboard of exactly these two colours.
    px = _pixels(fresh, "outside_room")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    assert pic.count(GREEN) > PIC_W * PIC_H // 4
    assert pic.count(GREEN) + pic.count(BLACK) + pic.count(RED) == len(pic)
