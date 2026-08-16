"""platformer_stream — the level on screen, and the player walking on it.

The rail's subject is a side-view level four screens wide AND tall, streamed
over a 64x64 BG1 ring. Three milestones are asserted here: the ring the level
is rendered through, the PLAYER that walks, jumps and falls over it, and the
STREAMER that slides the ring under the follow camera on both axes.

WHAT THE STREAMING CASES ASSERT, and where the line is. `pfs_stream`'s own
MECHANISM is proven on its own probe (`tests/test_pfs_stream.py`, which drives
the camera directly and has no picture around it). What is proven HERE is the
RAIL'S WIRING of it — the init, the arm in sync with the spawn camera, the
per-frame set_cam + tick after the follow camera has settled, and the VBlank
drain in the scene manager's hook — by driving the PLAYER and reading the ring
the hardware actually fetches from.

EVERY FULL-WINDOW ASSERTION IS A STOPPED-CAMERA CLAIM. While the camera moves
the ring trails it by the staging + VBlank-drain lag BY DESIGN, so each leg
below finishes its motion and settles before it asks. (The one case that reads
a moving frame, `test_the_picture_is_the_level`, reads the camera the picture
was RENDERED with — one frame back — rather than the one the tick has since
produced.)

The player's own cases are immune to the ring by construction: collision reads
col_map's ROM blob in WORLD space and the sprite is OAM, so neither touches
it.

WHAT EVERY TEST HERE READS — the rendered output region, never a proxy
variable (CLAUDE.md rule 2):

  * the BG1 tilemap's VRAM words, all 4,096 of them;
  * the BG1 CHR page's VRAM bytes;
  * CGRAM words 0..15, which are the palette AND the backdrop slot;
  * the screenshot's pixels.

THE RING ORACLE IS REBUILT HERE, from `pfs_flat_row.bin`, with the four-page
placement recomputed from the PPU's own addressing:

    VRAM(col,row) = base + (col >= 32 ? $400 : 0) + (row >= 32 ? $800 : 0)
                         + (row & 31) * 32 + (col & 31)

and the position wrap `slot = world & 63` restated rather than imported. A
sequentially-built oracle would agree with a sequentially-built fill and both
would be wrong in the same way — which is the exact failure a Mode 7 streamer
in this engine's history shipped. The camera words are read only to say WHICH
world window to compare against; the assertion is always the VRAM-versus-blob
comparison, so a camera word that lied would make it FAIL rather than pass.

AND THE PICTURE IS CHECKED AGAINST THE SAME LEVEL, cell by cell. A VRAM-only
assertion cannot see a scroll register that is off by a pixel, a tilemap base
the PPU is not actually fetching from, or a size bit that makes the hardware
read a 32x32 window out of a 64x64 claim — all three would leave the VRAM
bytes perfectly correct. `test_the_picture_is_the_level` is what closes that,
and it is not hypothetical: it is red against the one-line BG1VOFS offset this
milestone found and fixed.

NO WALL CLOCK. Every capture lands on an ABSOLUTE emulated frame via
`boot_to_frame` — `boot_rom(frames=N)` lands on ">= N", and this module's
assertions are pixel-exact.
"""
import os
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "platformer_stream.sfc"
ASSETS = BUILD / "assets"
# One expression on purpose: conftest resolves the map a module reads at
# COLLECTION time from exactly this shape, and refuses a module whose map it
# cannot see.
_JMAP = json.loads((SUPERFORGE / "build" / "pfs" / "symbol_map.json").read_text())

V, C, W = (MemoryType.SnesVideoRam, MemoryType.SnesCgRam,
           MemoryType.SnesWorkRam)


def _sym(name, scene="play"):
    """Addresses are ASKED FOR, never hardcoded — this reads the same map the
    ROM was assembled against, so an allocator move breaks the test loudly
    instead of silently reading the wrong bytes."""
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


# VRAM symbols are WORD addresses (the allocator's convention, and VMADD's);
# MesenRunner reads VRAM by BYTE, so every read below doubles. Written as the
# doubling rather than as a second constant so the two cannot drift.
V_MAP = _sym("ES_V_PFS_MAP")["start"]        # word address of the ring
V_CHR = _sym("ES_V_PFS_CHR_V")["start"]      # word address of the CHR page
C_PAL = _sym("ES_C_PFS_PAL_C")["start"]      # CGRAM word index (0: backdrop)
DP_CAM = _sym("ES_PFS_CAM")["start"]         # DP, and DP is low WRAM

# The world's own geometry, from the generator's emitted .inc rather than
# transcribed — one author for the numbers the ROM and the oracle share.
_WORLD = {}
for _line in (ASSETS / "pfs_world.inc").read_text().splitlines() \
        if (ASSETS / "pfs_world.inc").exists() else []:
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = (t.strip() for t in _line.split("=", 1))
        _v = _v.split(";")[0].strip()
        if _v.isdigit():
            _WORLD[_k] = int(_v)

DP_PLAYER = _sym("ES_PFS_PLAYER")["start"]   # DP, and DP is low WRAM
V_HERO = _sym("ES_V_PFS_HERO_V")["start"]    # word address of the OBJ page
C_HERO = _sym("ES_C_PFS_HERO_PAL_C")["start"]  # CGRAM word index of OBJ pal 0
O_HERO = _sym("ES_O_PFS_HERO")["start"]      # the hero's OAM slot

RING = 64                       # the ring is 64x64 tiles
PAGE = 32                       # ...built from four 32x32 hardware pages
# Tiles of resident window kept BEHIND the camera. `pfs_stream`'s PFS_BACK,
# restated here rather than imported, because the whole point of the oracle is
# that it does not share arithmetic with the code under test.
#
# THE RAIL'S SCROLL CONVENTION DOES NOT DEPEND ON IT, which is why the enter
# needed no counterpart change: the ring is POSITION-WRAPPED (world tile c
# lives at slot c & 63), so BG1HOFS/BG1VOFS name a WORLD pixel and the
# hardware's own 512-px tilemap wrap lands the visible window on the right
# slots for any BACK. What BACK has to satisfy is a containment, not an
# alignment — the visible 33x29 tiles must be inside [cam - BACK, cam - BACK +
# 63] — and `test_the_resident_window_covers_what_the_scroll_registers_show`
# is the assertion on it.
BACK = 16
SCREEN_W, SCREEN_H = 256, 224
# The screenshot is 256x239; the ACTIVE PICTURE is rows 7..230 (224 lines).
ACTIVE_TOP = 7

# TWO ABSOLUTE FRAMES, and each is measured rather than guessed.
#
#   FALL_FRAME — the fade-in ramp is complete (level 15 by frame 18) and the
#     camera is still inside the window scene enter filled, so the PICTURE is
#     the level. The player is mid-fall at terminal velocity, which is why the
#     camera is NOT tile-aligned here and the picture oracle is per PIXEL.
#   REST_FRAME — gravity has carried the player the ~5 screens from the shaft
#     mouth to the bedrock floor and the state has settled (measured: the first
#     frame with grounded=1, vy=0 and py at the floor is 217).
#
# Both are absolute: `boot_to_frame` free-runs the boot and STEPS the last
# frames, so every host photographs the same frame (docs/45 §4 — `boot_rom`
# lands on ">= N", and these assertions are pixel- and byte-exact).
FALL_FRAME = 40
REST_FRAME = 240


@pytest.fixture(scope="module")
def runner():
    """One runner for the module; each case names the ABSOLUTE frame it reads.

    The ROM is re-booted per frame rather than shared, because this rail's
    state moves every frame — the player falls the whole first ~3.5 seconds —
    so a single boot point cannot serve both the picture cases and the physics
    cases. `_boot` hands the core back to free-running first, which is the
    module-boundary contract `tests/conftest.py` enforces.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make platformer_stream` first")
    r = MesenRunner()
    yield r
    r.stop()               # resumes the core first: the module-boundary contract


def _boot(runner, frame):
    """Land PARKED on an exact absolute emulated frame."""
    runner.debug_resume()
    runner.boot_to_frame(str(ROM), frame)
    return runner


def _boot_picture(runner, frame):
    """Land on `frame` and return the camera THE PICTURE WAS RENDERED WITH.

    THE ONE-FRAME LAG, measured rather than assumed. The tick runs during
    active display and writes `pfs_cam`; the NMI at the END of that frame
    commits BG1HOFS/BG1VOFS from it; so the picture of frame F is drawn with
    the camera frame F-1's tick produced. Reading DP at F and comparing the
    screen against it is wrong by exactly one frame of camera motion — 4 px at
    terminal fall, which is half a tile and reads as a misaligned layer.

    So the camera is read at F-1 and the shot taken at F. (This only bites
    while the camera MOVES; the at-rest cases are immune, which is the same
    stopped-camera precondition `assert_window_exact` states for streaming.)
    """
    _boot(runner, frame - 1)
    cam = _cam(runner)
    runner.frame_step(1)
    return cam


def _blob(name):
    p = ASSETS / name
    if not p.exists():
        pytest.fail(f"{p} missing — run `make pfs-assets` first")
    return p.read_bytes()


def _cam(runner):
    """The camera the ring was filled around, in world pixels.

    Read to SELECT the oracle window, never asserted as the feature's output —
    a wrong value here makes every comparison below fail, which is the correct
    direction for a selector.
    """
    return runner.read_u16(W, DP_CAM), runner.read_u16(W, DP_CAM + 2)


def _player(runner):
    """(px, py) — the player's committed WORLD position, in pixels.

    Read as a SELECTOR and as the input to the ROM-collision-table oracle, the
    way `_cam` is: nothing here asserts it directly. What the tests assert is
    the rendered OAM entry the draw derives from it, and the collision-table
    verdict at the world column it names. A wrong value makes those FAIL.
    """
    return (runner.read_u16(W, DP_PLAYER), runner.read_u16(W, DP_PLAYER + 2))


def _spawn_window():
    """The world-pixel camera the ENTER-time ring arm was built around.

    The scene centres the spawn in a 256x224 screen with the clamp inactive
    (play.asm asserts that at assembly time), so this is derived from the
    generator's own emitted geometry rather than transcribed — it is the pair
    `enter` hands to BOTH `pfs_arm` and `pfs_stream_set_cam`, which is what
    makes the scroll and the ring agree on frame 0.
    """
    return (_WORLD["PFS_SPAWN_X"] - SCREEN_W // 2,
            _WORLD["PFS_SPAWN_Y"] - SCREEN_H // 2)


def _resident_window(cam):
    """The world tile corner the ring holds for a camera at world pixel `cam`.

    The streamer keeps BACK tiles behind the camera on each axis, so the ring
    holds [tx-BACK .. tx-BACK+63] x [ty-BACK .. ty-BACK+63], every world tile
    at slot (col & 63, row & 63). Both are mod-128 world coordinates: the
    world is a torus on both axes and a camera near an edge names tiles from
    the far side, which the ring holds legitimately and the screen never
    shows.
    """
    return (cam[0] // 8 - BACK, cam[1] // 8 - BACK)


def _ring_mismatches(runner, cam):
    """Every one of the 4,096 ring slots against the authored level.

    Output region: VRAM words [ES_V_PFS_MAP .. +$1000), read whole. Oracle:
    `pfs_flat_row.bin`, indexed by WORLD tile and placed by the PPU's own
    four-page formula with `slot = world & 63` — restated in `_slot_word_addr`
    rather than imported, because an oracle that shares the arithmetic under
    test proves nothing.

    The camera is a SELECTOR here, never the assertion: it says which world
    window to compare against, and a camera word that lied would make every
    comparison FAIL rather than pass.
    """
    tx0, ty0 = _resident_window(cam)
    rowmajor = _blob("pfs_flat_row.bin")
    vram = runner.read_bytes(V, V_MAP * 2, RING * RING * 2)
    bad = []
    for dr in range(RING):
        for dc in range(RING):
            col, row = tx0 + dc, ty0 + dr
            i = (_slot_word_addr(col % RING, row % RING) - V_MAP) * 2
            got = vram[i] | (vram[i + 1] << 8)
            want = _world_tile(rowmajor, col, row)
            if got != want:
                bad.append((col % 128, row % 128, col % RING, row % RING,
                            got, want))
    return bad


def _assert_ring_exact(runner, tag, settle=3):
    """THE STREAMING INVARIANT — and it is a STOPPED-camera claim.

    Only meaningful at rest: while the camera moves, VRAM trails it by the
    staging + VBlank-drain lag by design. Every caller finishes its leg first;
    the settle is the same drain grace `tests/test_pfs_stream.py` takes for the
    probe's ring.
    """
    runner.frame_step(settle)
    cam = _cam(runner)
    bad = _ring_mismatches(runner, cam)
    assert not bad, (
        f"{tag}: cam={cam} (tile {cam[0] // 8},{cam[1] // 8}) — {len(bad)} of "
        f"{RING * RING} ring slots disagree with the authored level; first 5 "
        f"(world col,row / slot col,row / got, want): {bad[:5]}")
    return cam


def _shot(runner, tmp_path, name="pfs.png"):
    """The ACTIVE 256x224 picture, as an RGB pixel accessor."""
    path = tmp_path / name
    runner.take_screenshot(str(path))
    im = Image.open(path).convert("RGB").crop(
        (0, ACTIVE_TOP, SCREEN_W, ACTIVE_TOP + SCREEN_H))
    return im.load(), im


def _to5(v):
    """One 8-bit channel back to the 5 bits the PPU actually holds.

    Mesen expands a 5-bit channel as `(v << 3) | (v >> 2)`, which is a
    bijection onto the 32 values it produces — so this is exact, not a
    nearest-match, and a colour that is not on the lattice raises.
    """
    for i in range(32):
        if (i << 3) | (i >> 2) == v:
            return i
    raise AssertionError(f"{v} is not a 5-bit PPU channel expansion")


def _sky5(runner, y):
    """The backdrop colour scanline `y` MUST render, in 5-bit channels.

    Derived from the two things that produce it and nothing else: CGRAM word 0
    (the hardware backdrop, read from the DESTINATION region) plus the ROM
    gradient blob's per-scanline COLDATA byte for that line, added and clamped
    the way the PPU's fixed-colour add does. `pfs_grad.bin` is three 224-byte
    planes and each byte carries its plane-select bit in the top three, which
    is why the intensity is masked out of it.

    THE SCANLINE-TO-TABLE MAPPING IS MEASURED, not assumed (rgb_gradient.asm
    says outright that it depends on HDMA init timing): scanline y takes table
    byte y, verified over every sky scanline of the at-rest frame.
    """
    grad = _blob("pfs_grad.bin")
    lines = len(grad) // 3
    back = runner.read_bytes(C, 0, 2)
    w = back[0] | (back[1] << 8)
    base = (w & 31, (w >> 5) & 31, (w >> 10) & 31)
    ramp = tuple(grad[p * lines + y] & 31 for p in range(3))
    return tuple(min(31, base[i] + ramp[i]) for i in range(3))


def _oam(runner, slot=0):
    """One OAM entry as (x, y, tile, attr, x9, size) — the RENDERED sprite."""
    lo = runner.read_bytes(MemoryType.SnesSpriteRam, slot * 4, 4)
    hi = runner.read_bytes(MemoryType.SnesSpriteRam, 512 + slot // 4, 1)[0]
    field = (hi >> ((slot % 4) * 2)) & 3
    return lo[0], lo[1], lo[2], lo[3], field & 1, (field >> 1) & 1


def _hero_rect(runner):
    """The screen rectangle OAM slot 0 covers, from the OAM bytes themselves.

    The rows are MEASURED, not taken from the OBJ's nominal +1 presentation
    offset: against this ROM's own render the 16x16 picture's first lit row is
    the OAM y itself, so the rectangle is y .. y+16 — one row wider than either
    convention alone, because an exclusion that is a row short leaks hero
    pixels into a sky assertion (it did, at (127..137, 145)) and an exclusion
    that is a row long only costs coverage of sky.
    """
    x, y, _t, _a, x9, _sz = _oam(runner)
    sx = x + (x9 << 8)
    if sx > 255:
        sx -= 512
    return sx, y, sx + 15, y + 16


def _in_rect(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _col_solid(collision, col, row):
    """The authored world-space collision byte, from the ROM blob."""
    return collision[(row % _WORLD["PFS_WORLD_H_TILES"])
                     * _WORLD["PFS_WORLD_W_TILES"]
                     + (col % _WORLD["PFS_WORLD_W_TILES"])]


def _world_tile(rowmajor, col, row):
    """The authored tilemap WORD at world tile (col, row).

    The world is a 128x128 torus in both axes and `pfs_flat_row.bin` is
    row-major with a 256-byte stride, which is what `PFS_ROW_BYTES` records.
    """
    wc = col % _WORLD["PFS_WORLD_W_TILES"]
    wr = row % _WORLD["PFS_WORLD_H_TILES"]
    off = wr * _WORLD["PFS_ROW_BYTES"] + wc * 2
    return rowmajor[off] | (rowmajor[off + 1] << 8)


def _slot_word_addr(slot_col, slot_row):
    """The PPU's own addressing of a 64x64 tilemap: four 32x32 pages.

    Restated here against the hardware's formula rather than imported out of the
    ROM's arithmetic — an oracle that shares the code under test proves
    nothing.
    """
    return (V_MAP
            + (0x400 if slot_col >= PAGE else 0)
            + (0x800 if slot_row >= PAGE else 0)
            + (slot_row % PAGE) * PAGE + (slot_col % PAGE))


def test_rom_is_a_512kb_cart():
    """The claim set packs into 16 LoROM windows and the linker filled them."""
    assert ROM.stat().st_size == 524288


def test_the_ring_holds_the_authored_level(runner):
    """All 4,096 BG1 tilemap words are the level, at their position-wrapped
    slots — at rest, after gravity has streamed the ring five screens down.

    Output region: VRAM words [ES_V_PFS_MAP .. +$1000), read whole.

    THE POSITION WRAP IS THE ASSERTION. A producer that wrote slots
    sequentially from the camera's corner would produce a tilemap that looks
    plausible in isolation and tears the instant the ring slides. That is a
    recorded Mode 7 defect, not a hypothetical one.

    AT REST, NOT MID-FALL, and the change is not a weakening: the full-window
    claim is a stopped-camera claim (`_assert_ring_exact`), and the at-rest
    camera is 97 tile rows below the one the enter armed. So every ring row
    here was STREAMED rather than armed, which is a strictly larger claim than
    the milestone-1 version of this case made against a static fill.
    """
    _boot(runner, REST_FRAME)
    _assert_ring_exact(runner, "at rest on the bedrock floor")


def test_the_resident_window_covers_what_the_scroll_registers_show(runner):
    """The visible 33x29 tiles are inside the window the ring actually holds.

    THE CONTAINMENT `PFS_BACK` HAS TO SATISFY, asserted rather than reasoned
    about. BG1HOFS/BG1VOFS name a WORLD pixel (`pfs_bg_nmi_commit`), the ring
    is position-wrapped, and the PPU's 512-px tilemap wrap does the rest — so
    the scroll convention is independent of BACK. What is NOT independent of
    it is whether the tiles the beam fetches are resident: with BACK = 16 the
    ring runs [cam-16 .. cam+47] and the screen needs [cam .. cam+32]
    horizontally and [cam .. cam+28] vertically.

    Read at the two ends of the arc — the armed spawn window and the at-rest
    one — and the margin is reported so a future BACK that shaved it to zero
    fails here instead of tearing one column at a time on screen.
    """
    for frame, tag in ((FALL_FRAME, "mid-fall"), (REST_FRAME, "at rest")):
        cam = _boot_picture(runner, frame)
        tx0, ty0 = _resident_window(cam)
        cx, cy = cam[0] // 8, cam[1] // 8
        assert tx0 <= cx and cx + SCREEN_W // 8 <= tx0 + RING - 1, (
            f"{tag}: the visible columns [{cx}..{cx + SCREEN_W // 8}] are not "
            f"inside the resident ring [{tx0}..{tx0 + RING - 1}]")
        assert ty0 <= cy and cy + SCREEN_H // 8 <= ty0 + RING - 1, (
            f"{tag}: the visible rows [{cy}..{cy + SCREEN_H // 8}] are not "
            f"inside the resident ring [{ty0}..{ty0 + RING - 1}]")


def test_the_chr_page_reaches_vram(runner):
    """The 25 Four Seasons tiles are in VRAM, byte for byte.

    Output region: the DESTINATION — VRAM bytes at the `pfs_chr_v` claim —
    compared to the source blob. Asserted directly because an upload that
    silently no-ops is invisible to every downstream check that happens to
    exercise only tiles it did reach (AGENTS.md test-surface sub-rule 3 — a
    `[sprites]` section once went unrecognised for a long time precisely
    because no test ever read the destination).
    """
    _boot(runner, FALL_FRAME)
    chr_blob = _blob("pfs_chr.bin")
    got = runner.read_bytes(V, V_CHR * 2, len(chr_blob))
    assert got == chr_blob, "the BG1 CHR page is not the blob that was uploaded"


def test_the_palette_and_the_backdrop_reach_cgram(runner):
    """CGRAM words 0..15 are the level palette — INCLUDING word 0.

    Word 0 is the BG's colour 0 and the hardware BACKDROP at once, which is why
    `pfs_bg` claims it outright rather than composing the `backdrop` feature.
    Reading the destination region covers both meanings in one assertion: a
    palette upload that started at word 1 "to leave the backdrop alone" would
    shift every colour by one and still render a picture.
    """
    _boot(runner, FALL_FRAME)
    pal = _blob("pfs_pal.bin")
    got = runner.read_bytes(C, C_PAL * 2, len(pal))
    assert got[2:] == pal[2:], "CGRAM does not hold the uploaded palette"
    # ...and word 0 is the one word that is NOT the blob's. The blob is
    # the level palette and its word 0 is $0000, because for a BG tile
    # colour 0 is TRANSPARENT — while the same physical word is the hardware
    # BACKDROP, which this rail's sky is built on. The scene overwrites it
    # with SKY_DUSK after the upload; `test_the_backdrop_word_is_the_dusk_sky_
    # not_the_blobs_transparent_zero` is the assertion on the value itself.
    assert (got[0] | (got[1] << 8)) != 0, (
        "CGRAM word 0 is $0000 — the backdrop was left as the palette blob's "
        "transparent colour and the dusk sky renders over black")


def test_the_picture_is_the_level(runner, tmp_path):
    """Every screen PIXEL is the level, or is the declared sky.

    THE COMPOSITED CHECK, and it is not redundant with the VRAM one. Three
    defects leave the tilemap bytes perfectly correct and the picture wrong:
    a scroll register off by a pixel, a BG1SC base the PPU is not fetching
    from, and a size bit that makes the hardware read a 32x32 window out of a
    64x64 claim. This case is RED against the first of those — the one-line
    BG1VOFS offset the foundation milestone found, where `VOFS = cam_y` puts
    world line cam_y + 1 at the top of the screen (scanline N shows line
    VOFS + N).

    PER PIXEL, NOT PER CELL, AND THAT IS THE GENERALISATION THIS MILESTONE
    OWED. The camera is no longer parked on a tile boundary — the player falls
    at 4 px/frame, so `cam_y` is never a multiple of 8 at terminal velocity —
    and the cell-grid form this case used to take asserted its own
    tile-alignment precondition. The oracle is now the sub-tile one its
    docstring already named: for each screen pixel, take the world pixel the
    camera geometry says is there, ask the level blob for its tile, and

      * an AIR tile (id 0, whose CHR is all-zero) must render the BACKDROP —
        and the backdrop is not black any more, it is CGRAM word 0 plus this
        scanline's gradient byte, so the assertion is the EXACT colour the two
        declared sources produce rather than "not lit";
      * a solid tile must carry at least one pixel that is NOT that backdrop
        colour, which is the other direction — a picture that were uniformly
        sky would pass the first clause alone.

    The hero is excluded by the rectangle its OWN OAM entry names (an OBJ
    renders at OAM y + 1), so the exclusion cannot drift from where the
    hardware drew it.
    """
    cam = _boot_picture(runner, FALL_FRAME)
    wrong_sky, dark_solid = _picture_mismatches(runner, tmp_path, cam)
    assert not wrong_sky, (
        f"{len(wrong_sky)} screen pixel(s) the level calls AIR do not carry "
        f"the declared backdrop+gradient colour; first (x, y, got, want): "
        f"{wrong_sky[0]} — the layer is misaligned, the PPU is fetching a "
        f"different window than the ring holds, or the sky is not the ramp")
    assert not dark_solid, (
        f"{len(dark_solid)} world tile(s) the level calls solid rendered "
        f"nothing but sky; first world (col, row) {dark_solid[0]}")


def _picture_mismatches(runner, tmp_path, cam, name="pfs.png"):
    """The composited check, as a helper: (wrong_sky, dark_solid).

    Factored out of `test_the_picture_is_the_level` so a DRIVEN stop can be
    checked the same way the boot frame is. A per-layer VRAM assertion cannot
    see a scroll register off by a pixel, a BG1SC base the PPU is not fetching
    from, or a size bit that reads a 32x32 window out of a 64x64 claim; this
    is what closes all three, and it stays a per-PIXEL oracle because the
    camera is not tile-aligned at an arbitrary stop either.
    """
    cam_x, cam_y = cam
    rowmajor = _blob("pfs_flat_row.bin")
    px, _im = _shot(runner, tmp_path, name)
    hero = _hero_rect(runner)
    sky = [_sky5(runner, y) for y in range(SCREEN_H)]

    wrong_sky, dark_solid = [], []
    lit_in_tile = {}
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            if _in_rect(hero, x, y):
                continue
            wx, wy = cam_x + x, cam_y + y
            tid = _world_tile(rowmajor, wx // 8, wy // 8) & 0x3FF
            got = tuple(_to5(c) for c in px[x, y])
            if tid == 0:
                if got != sky[y]:
                    wrong_sky.append((x, y, got, sky[y]))
            else:
                key = (wx // 8, wy // 8)
                lit_in_tile[key] = lit_in_tile.get(key, False) or got != sky[y]
    # A TILE THE HERO TOUCHES CANNOT BE JUDGED, and dropping the pixel while
    # keeping the tile was the bug this clause fixes. Many of the level's tiles
    # are mostly transparent — tile 18, the grass tuft, lights only three rows
    # of its bottom-left corner — so when the hero stands on one, every lit
    # pixel it has is behind the sprite and the surviving pixels are correctly
    # backdrop. Judging that tile "rendered nothing but sky" is a false
    # positive about the LEVEL caused by the SPRITE, which is exactly what the
    # hero exclusion exists to prevent; it has to exclude the whole tile, not
    # the covered pixels.
    hero_tiles = {((cam_x + x) // 8, (cam_y + y) // 8)
                  for y in range(SCREEN_H) for x in range(SCREEN_W)
                  if _in_rect(hero, x, y)}
    for key, lit in sorted(lit_in_tile.items()):
        if not lit and key not in hero_tiles:
            dark_solid.append(key)
    return wrong_sky, dark_solid


# =============================================================================
# THE STREAMER, AS THE RAIL WIRES IT — every direction the arc can reach
# =============================================================================
# A test that only walks one way locks that way and ships the other broken
# (AGENTS.md's state-cycle rule), so the legs below drive the camera FORWARD
# and BACKWARD on both axes and then stand still. What each one reads is the
# ring's own VRAM words against the authored level, plus — once — the
# composited picture, because a per-layer byte check cannot see a scroll
# register the PPU is fetching a different window with.
#
# THE FOUR DIRECTIONS, and how the level's own geometry supplies them:
#
#   down   gravity. The spawn is airborne in the mouth of the shaft and the
#          fall carries the camera 97 tile rows to the bedrock floor — more
#          than the ring's 64, so EVERY ring row at rest was streamed.
#   east   held Right along the bedrock until the pillar at world column 80
#          stops the player flush (cam_x 144 -> 504, 45 tile columns).
#   west   held Left back past the spawn to the lip of the bottomless shaft
#          at world column 18 (cam_x 504 -> 16, 61 tile columns).
#   up     the STAIRCASE east of the spawn — four ledges at world rows 116,
#          112, 108 and 104. Climbing it is the only way the camera rises and
#          STAYS risen: the follow camera's bottom clamp pins cam_y at 800
#          everywhere on the bedrock floor, so a jump from the floor (apex
#          py 921, clamp floor py 912) moves it by nothing at all. Four
#          climbed ledges take cam_y 800 -> 687, fourteen tile rows up.
#
# The horizontal sweep is 61 of the ring's 64 columns rather than a full lap,
# because the level's own walls bound where the player can stand — 45 columns
# east of the spawn and 16 west of it. It DOES cross the wrap in both slot
# senses: the resident window straddles ring slot 63 -> 0 throughout, and
# world column 64 (slot 0) enters as a leading edge on the way east and again
# on the way back. A full 64-column lap is not reachable by walking and is
# covered on the mechanism's own probe (`test_pfs_stream.py::test_t6`), which
# drives the camera directly.

def test_the_ring_streams_east_and_back_west(runner, tmp_path):
    """Held Right slides the ring east; held Left slides it back.

    Feature: `pfs_stream`'s horizontal axis, as the rail drives it —
    `pfs_stream_set_cam` + `pfs_stream_tick` from `play::tick` after
    `pl_camera` has settled, drained by `pfs_stream_nmi_dispatch` in
    `sm_nmi_hook`.

    Output region: the BG1 tilemap's VRAM words, all 4,096, against the
    authored level at each STOP — plus the composited screenshot at the
    eastern stop, which is where a scroll/ring disagreement would show and a
    byte check would not.

    State cycle: rest -> east to the pillar -> rest -> west to the shaft lip
    -> rest. The reverse leg is the point: the streamer's `@tx_step_back` arm
    stages the window's FIRST column where the forward arm stages its last,
    and a rail that only ever ran east would ship it untested.
    """
    _boot(runner, REST_FRAME)
    start = _assert_ring_exact(runner, "at rest, before the run east")

    for _ in range(260):                 # 2 px/frame, until the pillar stops it
        runner.frame_step(1, right=True)
    east = _assert_ring_exact(runner, "stopped flush against the east pillar")
    assert east[0] > start[0] + 300, (
        f"the run east moved the camera from {start[0]} to {east[0]} — the "
        f"follow camera is not carrying the player")

    wrong_sky, dark_solid = _picture_mismatches(runner, tmp_path, east,
                                                "east_stop.png")
    assert not wrong_sky, (
        f"at the eastern stop {len(wrong_sky)} screen pixel(s) the level "
        f"calls AIR do not carry the declared backdrop+gradient colour; "
        f"first (x, y, got, want): {wrong_sky[0]}")
    assert not dark_solid, (
        f"at the eastern stop {len(dark_solid)} world tile(s) the level calls "
        f"solid rendered nothing but sky; first (col, row) {dark_solid[0]}")

    for _ in range(244):                 # back west, stopping short of the pit
        runner.frame_step(1, left=True)
    west = _assert_ring_exact(runner, "stopped at the lip of the shaft")
    assert west[0] < start[0], (
        f"the walk west ended at camera x {west[0]}, no further west than the "
        f"rest position {start[0]} — the reverse leg never ran")


def test_the_ring_streams_up_the_staircase_and_back_down(runner):
    """Climbing raises the camera and the ring follows it UP; falling undoes
    it.

    Feature: `pfs_stream`'s vertical axis in BOTH senses. The boot arc already
    supplies the forward one — gravity streams 97 rows down before frame 240 —
    so this case exists for the REVERSE one, `@ty_step_back`, which nothing
    else in this rail can reach.

    Output region: the 4,096 BG1 tilemap words against the authored level at
    each stop.

    State cycle: rest on the bedrock -> four climbed ledges (cam_y 800 -> 687)
    -> walk back west off the staircase and fall -> rest again. Both ends are
    stopped cameras; the assertion in the middle is the one that would go red
    if the streamer only knew how to walk its window forward.
    """
    _boot(runner, REST_FRAME)
    floor = _assert_ring_exact(runner, "at rest, before the climb")

    for _ in range(10):                  # line up short of the first ledge
        runner.frame_step(1, right=True)
    for _ledge in range(4):
        # Held A for 34 of 40 frames is the full arc plus the landing: the
        # jump is grounded-gated with a variable-height cut, so a shorter hold
        # tops out below the next ledge and the climb stalls.
        for i in range(40):
            runner.frame_step(1, right=True, a=(i < 34))
    top = _assert_ring_exact(runner, "at rest on the fourth ledge")
    assert top[1] < floor[1] - 64, (
        f"the climb only raised the camera from {floor[1]} to {top[1]} — "
        f"fewer than eight tile rows, so the reverse arm was barely exercised")

    for _ in range(120):                 # off the staircase, and fall back
        runner.frame_step(1, left=True)
    back = _assert_ring_exact(runner, "back at rest on the bedrock floor")
    assert back[1] == floor[1], (
        f"the descent settled at camera y {back[1]}, not back at the bedrock "
        f"floor's {floor[1]}")


def test_a_stopped_camera_holds_the_ring(runner):
    """Idle is a state too: nothing moves, and nothing decays.

    Feature: the streamer's no-op path — `pfs_stream_tick` finds LAST equal to
    CAM on both axes, stages nothing, and `pfs_stream_nmi_dispatch` finds both
    counts zero and drains nothing.

    Output region: the 4,096 BG1 tilemap words, read twice 90 frames apart and
    required to be BYTE-IDENTICAL, plus the authored-level comparison at both
    reads. A drain that fired on an empty slot table, or a tick that staged a
    zero-delta line into slot 0 every frame, would leave the second read
    different from the first while every moving case still passed.
    """
    _boot(runner, REST_FRAME)
    _assert_ring_exact(runner, "at rest, first read")
    before = runner.read_bytes(V, V_MAP * 2, RING * RING * 2)
    runner.frame_step(90)                # 1.5 s of standing still
    after = runner.read_bytes(V, V_MAP * 2, RING * RING * 2)
    assert after == before, (
        "the ring changed over 90 idle frames — something is streaming with "
        "no camera motion to stream for")
    _assert_ring_exact(runner, "at rest, after 90 idle frames")


# =============================================================================
# THE PLAYER — every assertion below reads OAM, VRAM, CGRAM or the picture
# =============================================================================
# The hero's art, its palette, and the arc it runs. None of these touches the
# ring: collision reads col_map's ROM blob in WORLD space and the sprite is an
# OAM entry, so the streamer cannot make any of them pass or fail.

def test_the_hero_chr_reaches_its_obj_page(runner):
    """The 32 OBJ tiles are in VRAM, byte for byte.

    Output region: the DESTINATION — VRAM bytes at the `pfs_hero_v` claim —
    compared to the source blob. Asserted directly because an upload that
    silently no-ops is invisible to every downstream check that happens not to
    exercise the tiles it missed. That is not hypothetical: a later sweep's
    `[sprites]` toml section went unrecognised for a long time, the sprite
    tiles and palette were never uploaded, the player was invisible, and no
    test in the chain ever read the destination region (AGENTS.md test-surface
    sub-rule 3).
    """
    _boot(runner, FALL_FRAME)
    blob = _blob("pfs_hero_chr.bin")
    got = runner.read_bytes(V, V_HERO * 2, len(blob))
    assert got == blob, "the OBJ CHR page is not the blob that was uploaded"


def test_the_hero_palette_reaches_obj_palette_zero(runner):
    """CGRAM 128..143 is the hero's palette — the OTHER half of sub-rule 3.

    OBJ palette 0 begins at CGRAM word 128 by hardware contract, which is what
    the `pfs_hero_pal_c` claim pins. Read from the destination so a palette
    upload that started at the BG's words instead would fail here rather than
    silently recolouring the level.
    """
    _boot(runner, FALL_FRAME)
    blob = _blob("pfs_hero_pal.bin")
    got = runner.read_bytes(C, C_HERO * 2, len(blob))
    assert got == blob, "OBJ palette 0 does not hold the uploaded palette"


def test_the_backdrop_word_is_the_dusk_sky_not_the_blobs_transparent_zero(runner):
    """CGRAM word 0 is SKY_DUSK, not the palette blob's $0000.

    ONE WORD, AND IT IS THE LARGEST REGION OF THE PICTURE. `pfs_bg`'s
    feature.toml and `game.toml` both declared this from the first milestone
    and nothing actually wrote it: the vendored `pfs_pal.bin` is the level
    palette, whose word 0 is $0000 because for a BG tile colour 0 is
    TRANSPARENT and that byte was never the sky. The gradient then rendered
    over black instead of over dusk — measured against the reference render,
    our scanline 2 read 5-bit (24, 8, 2) where the reference reads
    (31, 10, 13), short by exactly this backdrop.

    Reads the destination region (CGRAM word 0), which is also the hardware
    BACKDROP slot — one word, two meanings, one owner.
    """
    _boot(runner, FALL_FRAME)
    w = runner.read_bytes(C, 0, 2)
    assert (w[0] | (w[1] << 8)) == (11 << 10) | (3 << 5) | 8, (
        "CGRAM word 0 is not SKY_DUSK — the sky is the ramp over black")


def test_the_dusk_ramp_is_on_screen_and_it_ramps(runner, tmp_path):
    """Every sky pixel is the declared ramp over the declared backdrop, EXACTLY.

    Output region: the screenshot, in the 5-bit space the PPU actually holds
    (Mesen's 8-bit expansion is a bijection, so `_to5` is exact and NOT a
    tolerance). The oracle is `pfs_grad.bin` plus CGRAM word 0 — the two
    declared sources — never the picture's own average.

    Which pixels are sky comes from VRAM: a screen cell whose resident tilemap
    word is tile 0 has all-zero CHR, so it shows the backdrop. Reading the RING
    rather than the level blob is deliberate — this case is about the COLOUR
    pipeline (three indirect HDMA channels into COLDATA, colour math adding the
    fixed colour to the backdrop only), and it must stay true whatever the ring
    happens to hold.

    BOTH DIRECTIONS. A flat fill would satisfy "every sky pixel matches the
    table" only if the table were flat, so the ends are asserted to DIFFER too
    — which is what proves three channels are streaming a ramp rather than one
    value being latched.
    """
    _boot(runner, REST_FRAME)
    cam_x, cam_y = _cam(runner)
    vram = runner.read_bytes(V, V_MAP * 2, RING * RING * 2)
    px, _im = _shot(runner, tmp_path, "sky.png")
    hero = _hero_rect(runner)

    def ring_tile(col, row):
        addr = _slot_word_addr(col % RING, row % RING)
        i = (addr - V_MAP) * 2
        return (vram[i] | (vram[i + 1] << 8)) & 0x3FF

    bad, checked = [], 0
    for y in range(SCREEN_H):
        want = _sky5(runner, y)
        for x in range(SCREEN_W):
            if _in_rect(hero, x, y):
                continue
            wx, wy = cam_x + x, cam_y + y
            if ring_tile(wx // 8, wy // 8) != 0:
                continue
            checked += 1
            got = tuple(_to5(c) for c in px[x, y])
            if got != want:
                bad.append((x, y, got, want))
    assert checked > SCREEN_W * 32, (
        f"only {checked} sky pixels were reachable at this frame — the case "
        f"is not exercising the ramp")
    assert not bad, (
        f"{len(bad)} of {checked} sky pixel(s) are not the declared "
        f"backdrop+gradient colour; first (x, y, got5, want5): {bad[0]}")
    assert _sky5(runner, 0) != _sky5(runner, SCREEN_H - 1), (
        "the gradient's two ends are the same colour — this is a flat fill, "
        "not a ramp")


def test_gravity_lands_the_player_where_the_reference_pins_it(runner):
    """OAM slot 0 rests at (124, 145) — a second implementation's published pin.

    GROUND TRUTH FROM OUTSIDE THIS TREE, and the assertion that settled what
    `py` means. A published `oracle.json` for this scene pins the sprite at
    screen (124, 145) after a no-input settle, and 124 is the follow camera's
    centre. That number is produced by a program sharing no code with this
    repo, so agreeing with it is not a tautology.

    It also decides an ambiguity no amount of reading comments settles: with
    the camera clamped at the world bottom (`world_h - 224 = 800`) and the draw at
    `py - cam_y - 15`, y = 145 means py = 960 — the bedrock floor's TOP row.
    `py` is the FEET CONTACT LINE. Had it been the box top the sprite would
    rest at 137.

    Output region: the OAM entry bytes, plus the hi-table field (X9 and the
    16x16 size bit), cross-checked against the ROM collision blob.
    """
    _boot(runner, REST_FRAME)
    x, y, _tile, attr, x9, size = _oam(runner, O_HERO)
    assert (x, y) == (124, 145), (
        f"OAM slot 0 rests at ({x}, {y}); the reference oracle pins (124, 145)")
    assert x9 == 0, "X9 is set at a screen-centre sprite"
    assert size == 1, "the hi-table size bit is clear — a 16x16 hero would "\
                      "render as its top-left 8x8 quarter"
    assert attr & 0x30 == 0x30, "the hero is not at OBJ priority 3"

    # ...and the same rest, checked against the AUTHORED world rather than
    # against itself: the row under the contact line must be solid and the
    # body's own rows must not be.
    collision = _blob("pfs_col.bin")
    _px, py = _player(runner)
    assert py == 145 + 800 + 15, "the OAM pin and the committed py disagree"
    col = _px // 8
    assert _col_solid(collision, col, py // 8), (
        f"world tile ({col}, {py // 8}) under the contact line is not solid")
    assert not _col_solid(collision, col, (py - 1) // 8), (
        f"world tile ({col}, {(py - 1) // 8}) — the box's own bottom row — is "
        f"solid; the player is standing INSIDE the floor")


def test_the_landing_is_a_rest_and_it_stays_one(runner):
    """The descent ends, and then nothing moves — no bounce, no sink, no jitter.

    THE STATE CYCLE'S TAIL, driven frame by frame rather than snapshotted. An
    apex-only or arrival-only assertion passes while the landing frame embeds
    the sprite in the floor or leaves it oscillating a pixel; that is a
    recorded defect this project has already paid for (spotted by
    a user in seconds), and the fix was to read the position on EVERY frame of
    the cycle.

    Output region: OAM slot 0's y byte, once per emulated frame across the
    last ~50 frames of the fall and the 40 that follow it.
    """
    _boot(runner, REST_FRAME - 60)
    ys = []
    for _ in range(100):
        runner.frame_step(1)
        ys.append(_oam(runner, O_HERO)[1])
    assert ys[-1] == 145, f"the settled sprite is at y {ys[-1]}, not 145"
    tail = ys[-40:]
    assert set(tail) == {145}, (
        f"the last 40 frames after landing are not still: {sorted(set(tail))}")
    assert max(ys) == 145, (
        f"the sprite reached y {max(ys)} — below its resting line, i.e. it "
        f"sank into the floor before settling")


def test_a_held_jump_runs_the_whole_arc_and_comes_back_to_rest(runner):
    """Ascent, apex, descent, landing, rest — every frame of it, from OAM.

    Output region: OAM slot 0's y byte per emulated frame. The camera is
    clamped at the world bottom for the whole arc, so screen y moves exactly
    as world y does and the sprite's own bytes carry the arc.

    Five claims, and the last two are the ones a snapshot cannot make:
      * it leaves the ground (y decreases at all),
      * the apex clears 30 px, which is the full arc rather than a tap,
      * the ascent is monotonic and so is the descent (no mid-air stutter),
      * it LANDS — and the landed value is within one pixel of where it
        started, so an arc does not walk the player into or out of the floor,
      * and it then holds EXACTLY still.
    """
    _boot(runner, REST_FRAME)
    start = _oam(runner, O_HERO)[1]
    ys = []
    for _ in range(70):
        runner.frame_step(1, a=True)
        ys.append(_oam(runner, O_HERO)[1])
    apex = min(ys)
    top = ys.index(apex)
    assert start - apex >= 30, (
        f"a held jump only cleared {start - apex} px (apex y {apex} from "
        f"{start}) — that is a tap, not the full arc")
    assert ys[:top + 1] == sorted(ys[:top + 1], reverse=True), (
        "the ascent is not monotonic — the arc stutters on the way up")
    assert ys[top:] == sorted(ys[top:]), (
        "the descent is not monotonic — the arc stutters on the way down")
    assert abs(ys[-1] - start) <= 1, (
        f"the jump landed at y {ys[-1]} having started at {start} — the arc "
        f"moved the resting line")
    assert set(ys[-15:]) == {ys[-1]}, (
        f"the last 15 frames after landing are not still: "
        f"{sorted(set(ys[-15:]))}")


def test_a_tap_hops_and_a_hold_clears_the_arc(runner):
    """The variable-height jump: releasing early caps the ascent.

    `pl_jump`'s cut arm runs on every frame A is NOT held, so a one-frame
    press must reach a visibly lower apex than a sustained hold. Without the
    cut the two are identical and this is the only case that can tell them
    apart — a jump test that only holds A passes with the cut deleted.

    Output region: OAM slot 0's y byte per frame, for both drives.
    """
    _boot(runner, REST_FRAME)
    start = _oam(runner, O_HERO)[1]
    runner.frame_step(1, a=True)          # press...
    tap = [_oam(runner, O_HERO)[1]]
    for _ in range(60):                   # ...and release immediately
        runner.frame_step(1)
        tap.append(_oam(runner, O_HERO)[1])
    tap_rise = start - min(tap)
    assert set(tap[-10:]) == {tap[-1]}, "the tap hop never settled"

    _boot(runner, REST_FRAME)
    hold = []
    for _ in range(70):
        runner.frame_step(1, a=True)
        hold.append(_oam(runner, O_HERO)[1])
    hold_rise = start - min(hold)
    assert 0 < tap_rise < hold_rise / 2, (
        f"a tap rose {tap_rise} px and a hold {hold_rise} px — the ascent cap "
        f"is not capping (or the tap did not leave the ground)")


def test_idle_is_the_only_thing_that_moves_at_rest(runner):
    """With no input the hero animates in place and nothing else changes.

    THE IDLE ARM of the state cycle, and it matters twice over: it is what the
    published render's at-rest frames show moving (frames 29 and 31 of the
    gallery gif differ in 314 pixels, every one of them inside the hero), and
    a rail whose sprite froze would still pass every position assertion above.

    Output region: OAM slot 0's tile id and position bytes, once per frame over
    two full four-step cycles (8 frames per step).
    """
    _boot(runner, REST_FRAME)
    tiles, poss = [], set()
    for _ in range(64):
        runner.frame_step(1)
        x, y, tile, _a, _x9, _s = _oam(runner, O_HERO)
        tiles.append(tile)
        poss.add((x, y))
    assert poss == {(124, 145)}, f"the resting sprite moved: {sorted(poss)}"
    assert sorted(set(tiles)) == [0, 2, 4, 6], (
        f"the idle cycle used tiles {sorted(set(tiles))}; a 16x16 four-frame "
        f"sheet occupies {{0, 2, 4, 6}} (each frame reads N, N+1, N+16, N+17)")
    runs = [len(list(g)) for _k, g in __import__("itertools").groupby(tiles)]
    assert set(runs[1:-1]) == {8}, (
        f"the animation steps every {sorted(set(runs[1:-1]))} frames, not 8")


def test_walking_east_stops_flush_against_the_wall_pillar(runner):
    """Held Right runs the player east and the pillar stops it FLUSH.

    FLUSH is the assertion, not "stopped": the box's leading column must be the
    last AIR column and the next one must be SOLID, both read from the ROM
    collision blob at the world column the run actually committed. A player
    pushed back out of the wall, or one embedded a pixel into it, fails here
    while a bare "it stopped moving" would pass either way.

    The rendered half is asserted alongside: OAM slot 0 stays at the follow
    camera's centre for the whole run, which is what says the CAMERA carried
    the player east rather than the player being left behind at the world edge
    — the exact defect the published oracle scenario was written against.
    """
    _boot(runner, REST_FRAME)
    collision = _blob("pfs_col.bin")
    start_x, _py = _player(runner)
    centres = set()
    prev = None
    for _ in range(400):
        runner.frame_step(1, right=True)
        centres.add(_oam(runner, O_HERO)[0])
        cur = _player(runner)[0]
        if cur == prev:
            break
        prev = cur
    px, py = _player(runner)
    assert px > start_x + 300, (
        f"the run only carried the player from {start_x} to {px}")
    assert centres == {124}, (
        f"OAM slot 0 left the follow-camera centre during the run: "
        f"{sorted(centres)}")

    lead = (px + 7) // 8                 # the box's leading tile column
    body = [(py - 8) // 8, (py - 1) // 8]
    for row in body:
        assert not _col_solid(collision, lead, row), (
            f"the box's own leading column {lead} is SOLID at row {row} — the "
            f"player stopped INSIDE the wall")
    assert any(_col_solid(collision, lead + 1, row) for row in body), (
        f"world column {lead + 1} is not solid at rows {body} — the player "
        f"stopped short of the pillar, or stopped for some other reason")


def test_walking_west_scrolls_the_level_and_mirrors_the_sprite(runner, tmp_path):
    """Held Left is a real second direction, not the first one negated.

    A test that only walks one way locks that way and ships the other broken
    (AGENTS.md's state-cycle rule). This drives the reverse arm and reads three
    rendered consequences: the sprite's H-flip attribute bit, its staying on
    the follow centre, and the PICTURE changing — the level scrolling under a
    stationary sprite is the whole point of a follow camera, and a frozen
    camera would leave two identical screenshots.

    The walk is bounded to stay on the bedrock floor: the level opens a
    bottomless shaft in it a few tiles west of the spawn, and falling into that
    is a different arm — the scene has no respawn for it.
    """
    _boot(runner, REST_FRAME)
    before_px, _ = _shot(runner, tmp_path, "west0.png")
    before = [[before_px[x, y] for x in range(0, SCREEN_W, 4)]
              for y in range(0, SCREEN_H, 4)]
    start_x = _player(runner)[0]
    y0 = _oam(runner, O_HERO)[1]
    centres, attrs, ys = set(), set(), set()
    for i in range(56):                  # 56 * 2 px = 112 px, short of the pit
        runner.frame_step(1, left=True)
        x, y, _t, a, _x9, _s = _oam(runner, O_HERO)
        if i < 2:
            continue                     # `frame_step` latches the pad at the
                                         # park, so the WRAM effect lands in
                                         # this step and the OAM one in the
                                         # next — a documented, constant lag
                                         # (mesen_runner.frame_step), not slop
        centres.add(x)
        attrs.add(a & 0x40)
        ys.add(y)
    after_px, _ = _shot(runner, tmp_path, "west1.png")
    after = [[after_px[x, y] for x in range(0, SCREEN_W, 4)]
             for y in range(0, SCREEN_H, 4)]

    assert _player(runner)[0] == start_x - 112, (
        "held Left did not carry the player 2 px/frame")
    assert attrs == {0x40}, (
        "the sprite's H-flip bit is not set while walking west")
    assert centres == {124}, (
        f"OAM slot 0 left the follow-camera centre walking west: "
        f"{sorted(centres)}")
    assert ys == {y0}, (
        f"the player did not stay on the floor walking west: {sorted(ys)}")
    assert before != after, (
        "the picture is identical before and after a 112 px walk west — the "
        "camera is not scrolling the level")


# =============================================================================
# THE PUBLISHED RENDER — an oracle this repo did not produce
# =============================================================================
ORACLE = SUPERFORGE / "vendor" / "art" / "platformer_stream" / \
    "ref_at_rest_frame.png"
# An OPTIONAL external tree holding a second, independent implementation of
# this scene, named by `SF_REFERENCE_TREE`. It is read-only and never a build
# dependency — absent on every bare runner and inside `make bare-check`, which
# is the property those runs exist to prove — so the cases below SKIP rather
# than fail when nothing is configured.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE_GIF = _REFERENCE_TREE / "docs" / "screenshots" / "gifs" / \
    "platformer_stream.gif"
ORACLE_GIF_FRAME = 30
# Scanlines our BG1 sits BELOW the reference render's, and it is this rail's
# deliberate correction rather than slack: `pfs_bg_nmi_commit` writes
# BG1VOFS = cam_y - 1 because PPU scanline N shows tilemap line VOFS + N and
# the first ACTIVE scanline is 1. The published frame carries the uncorrected
# form, which
# is visible in the artifact itself — its bottom scanline renders the world's
# wrapped row 0 (sky) where the level has bedrock. The case below proves that
# from the level bytes before using this constant.
SHIFT = 1


def _level_colours():
    """The 12 non-transparent colours the level's CHR is drawn in.

    Read from the palette blob and expanded the way the PPU does, so a pixel
    can be classified as LEVEL or as SKY without asking the picture what it
    thinks. These twelve survive the gallery gif's own palette exactly (checked
    below); the ~224-shade dusk ramp does not, which is the whole reason this
    case compares tiles and the case above compares sky.
    """
    pal = _blob("pfs_pal.bin")
    out = set()
    for i in range(1, 16):
        w = pal[i * 2] | (pal[i * 2 + 1] << 8)
        if w:
            out.add(tuple(((w >> s) & 31) << 3 | ((w >> s) & 31) >> 2
                          for s in (0, 5, 10)))
    return out


def test_the_vendored_oracle_frame_is_the_published_gif_frame():
    """The vendored PNG is frame 30 of the published gallery gif, byte for byte.

    REFERENCE-GATED ON PURPOSE, and it is the half that makes the vendoring
    honest: the case below runs everywhere against a PNG in this tree, and this
    one — on a box that has the reference tree — proves that PNG is the frame
    it claims to be rather than something this repo drew. Without it the
    vendored oracle is only as trustworthy as whoever copied it.
    """
    if not REFERENCE_GIF.exists():
        pytest.skip(f"SF_REFERENCE_TREE is unset or holds no gif "
                    f"({REFERENCE_GIF}) — optional, never a build dependency; "
                    f"the vendored PNG under test is in the tree and the case "
                    f"below runs without it")
    im = Image.open(REFERENCE_GIF)
    im.seek(ORACLE_GIF_FRAME)
    want = im.convert("RGB").crop(
        (0, ACTIVE_TOP, SCREEN_W, ACTIVE_TOP + SCREEN_H))
    got = Image.open(ORACLE).convert("RGB")
    assert got.size == want.size == (SCREEN_W, SCREEN_H)
    assert got.tobytes() == want.tobytes(), (
        "the vendored oracle frame is not gif frame "
        f"{ORACLE_GIF_FRAME}'s active picture")


def test_the_at_rest_level_render_matches_the_published_frame(runner, tmp_path):
    """Our at-rest picture IS the reference render, pixel for pixel, on every
    level pixel.

    THE ORACLE THAT IS NOT A TAUTOLOGY. `ref_at_rest_frame.png` is a
    hardware render by a program sharing no code with this repo, at the same
    moment in the same arc: the player settled on the bedrock floor with the
    camera clamped at the world bottom. Agreement covers the level data, the
    CHR, the palette, the 64x64 ring's four-page addressing, both scroll
    registers and the camera's bottom clamp in one assertion.

    WHY IT COMPARES ONLY THE LEVEL PIXELS, and why that is not a weakening.
    The gallery gif is a 256-colour GIF and frame 30 holds FIFTY distinct
    colours; the dusk ramp alone is 224 scanlines of independently varying
    R/G/B. So the sky in that file is a quantization of the real render — ours
    differs from it by up to one 5-bit step, measured. A pixel-exact sky
    comparison is therefore unattainable against this artifact and a tolerance
    would be a fudge dressed as rigour. The twelve LEVEL colours survive the
    gif's palette exactly (asserted here), so the level half stays pixel-exact
    with no tolerance at all — and the sky half is asserted EXACTLY against the
    ROM's own declared sources by
    `test_the_dusk_ramp_is_on_screen_and_it_ramps`, which is a stronger oracle
    for that region than a quantized picture could be.

    THE STREAMER'S GATE ON THIS CASE IS GONE, and its going is the milestone.
    Through the foundation milestones the ring held the ONE window scene enter
    filled while the at-rest camera sat five screens below it, so this case
    skipped with a self-clearing reason that named exactly that. It now runs,
    because the ring slides: the at-rest window is 97 tile rows below the
    armed one and every row of it was streamed there.

    ONE SCANLINE OF REGISTRATION, AND IT IS OURS ON PURPOSE — the one thing
    that changed in this case when the gate cleared, stated here rather than
    absorbed by a tolerance. Our BG1 sits exactly ONE SCANLINE LOWER than the
    reference render: our screen row y+1 carries the level pixels its row y
    does, with ZERO mismatches in 21,966 compared pixels at that registration
    and ~10,000 at any other, including zero. `SHIFT` below is that offset, and
    `test_the_one_scanline_offset_belongs_to_the_reference_not_to_us` is the
    separate case that proves WHICH side is right rather than assuming it. In
    short: `pfs_bg_nmi_commit`'s `dec` corrects an off-by-one the published
    frame still carries, so requiring the two frames to agree at offset zero
    would be requiring us to reproduce a defect.

    Everything else about the comparison is untouched: no tolerance, every
    level pixel, the hero excluded by the rectangle its own OAM entry names.
    """
    cam = _boot_picture(runner, REST_FRAME)
    ty0 = _resident_window(cam)[1]
    assert ty0 <= cam[1] // 8 and cam[1] // 8 + SCREEN_H // 8 <= ty0 + RING, (
        f"the at-rest camera is at tile row {cam[1] // 8} and the resident "
        f"ring holds [{ty0}..{ty0 + RING - 1}] — the streamer did not carry "
        f"the window down with the camera, so this comparison would be "
        f"against tiles that are not in VRAM")

    want = Image.open(ORACLE).convert("RGB").load()
    got, _im = _shot(runner, tmp_path, "at_rest.png")
    hero = _hero_rect(runner)
    level = _level_colours()

    def diff(shift):
        n, wrong = 0, []
        for y in range(SCREEN_H - shift):
            for x in range(SCREEN_W):
                if _in_rect(hero, x, y + shift):
                    continue
                a, b = want[x, y], got[x, y + shift]
                if a not in level and b not in level:
                    continue             # sky on both sides: see the docstring
                n += 1
                if a != b:
                    wrong.append((x, y, b, a))
        return n, wrong

    compared, bad = diff(SHIFT)
    assert compared > 15000, (
        f"only {compared} level pixels were compared — the oracle or the "
        f"render is not the at-rest frame")
    assert not bad, (
        f"{len(bad)} of {compared} level pixel(s) differ from the reference "
        f"render at the declared {SHIFT}-scanline registration; "
        f"first (x, y, ours, reference): {bad[0]}")
    # ...and the registration is EXACT, not a window a drifting layer could
    # slide inside: at offset 0 the two frames must genuinely disagree. Without
    # this the shift above would quietly absorb a future BG1VOFS regression.
    _n, unshifted = diff(0)
    assert unshifted, (
        "our frame matches the reference render at offset 0 as well as at "
        f"{SHIFT} — the registration constant is now hiding rather than "
        f"stating a difference, so it should be removed")


def test_the_one_scanline_offset_belongs_to_the_reference_not_to_us(
        runner, tmp_path):
    """WHICH render is right about the bottom scanline — derived, not assumed.

    The case above compares at a one-scanline offset. That is only honest if
    the offset is the OTHER render's defect rather than ours, so this derives
    the answer from the level's own bytes instead of from either picture's
    authority.

    THE DERIVATION. The camera is clamped at the world bottom, cam_y = 1024 -
    224 = 800, so the LAST visible scanline must show world line 800 + 223 =
    1023 — inside world tile row 127, which the authored level fills with
    bedrock. A render whose bottom scanline shows SKY there is showing world
    line 1024, i.e. row 0 wrapped through the ring, which is the classic
    `VOFS = cam_y` off-by-one (`pfs_bg_nmi_commit`'s header states the
    mechanism: PPU scanline N shows tilemap line VOFS + N and the first ACTIVE
    scanline is 1, so a naive VOFS puts world line cam_y + 1 at the top).

    Output regions: our bottom screen scanline's pixels, the vendored oracle's
    bottom scanline's pixels, and the level blob that says which of the two
    the hardware owes. The corroborating half is that the HDMA SKY is NOT
    shifted — both frames' first sky scanline is identical — so the difference
    is in the BG layer, not in how the two files were cropped.
    """
    cam = _boot_picture(runner, REST_FRAME)
    assert cam[1] == _WORLD["PFS_WORLD_H_PX"] - SCREEN_H, (
        f"this derivation assumes the bottom clamp; camera y is {cam[1]}")
    rowmajor = _blob("pfs_flat_row.bin")
    bottom = cam[1] + SCREEN_H - 1
    assert _world_tile(rowmajor, 0, bottom // 8) & 0x3FF, (
        "world tile row 127 is AIR in the level blob — the bedrock premise "
        "this derivation rests on is wrong")

    got, _im = _shot(runner, tmp_path, "at_rest_bottom.png")
    want = Image.open(ORACLE).convert("RGB").load()
    level = _level_colours()
    # The bedrock spans the whole visible width, so most of the bottom line
    # must be level colours — not all of it, because the brick tile's own
    # bottom row carries transparent gap pixels that render the backdrop
    # (measured: 192 brick / 64 gap).
    ours = sum(1 for x in range(SCREEN_W)
               if got[x, SCREEN_H - 1] in level)
    theirs = {want[x, SCREEN_H - 1] for x in range(SCREEN_W)}
    assert ours > SCREEN_W // 2, (
        f"only {ours} of {SCREEN_W} pixels on OUR bottom scanline are level "
        f"colours — world line {bottom} is bedrock, so OUR BG1VOFS is the one "
        f"off by a scanline and the registration constant must not be used")
    assert len(theirs) == 1 and not (theirs & level), (
        f"REFERENCE's bottom scanline holds {theirs}, which is not one uniform "
        f"non-level colour — its render does reach world line {bottom} after "
        f"all, so the one-scanline difference is not the off-by-one claimed "
        f"here and the registration constant is unjustified")
