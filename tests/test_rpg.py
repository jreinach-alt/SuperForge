"""rpg — the town-and-overworld rail, and the `dialog` feature it debuts.

Lockstep-native: `Machine` only, no MesenRunner,
no wall-clock surface, every read taken from a parked exact frame and every
capture landed on an absolute one.

WHAT THIS RAIL IS FOR, and therefore what these tests must prove. `dialog` is
the new engine feature, and its claim is not "text appears" — `bg_text` already
does text. Its claim is **an OPAQUE window over a RUNNING scene that closes back
to the scene it covered**, and that decomposes into three separate things the
machine either does or does not do:

  OPACITY — no scene pixel shows through inside the panel. Proven on SCREENSHOT
  PIXELS inside the frame, against the panel palette this feature uploaded, and
  against the town's own cobble colours taken from the SAME RUN before the panel
  opened. A VRAM-only assertion cannot see this: the tilemap can be perfect and
  the layer still composite underneath (that class of defect).

  THE FLOW — open, page, page, close, and REOPEN. The reopen is the half that
  catches a panel which restores itself into an unusable state, and it is driven
  here rather than assumed.

  THE RESTORE — "the scene behind the box comes back" is a claim about PIXELS,
  not about a variable reading zero (the spec / spec-mechanism trap). So
  the closed frame is compared to the pre-open frame over the panel's own
  rectangle, and it must be identical there.

The rail's other halves are proven on their own output regions: the split-band
sky against the backdrop CGRAM word, grid collision against the SCREEN (a
rejected press must leave the picture untouched, in BOTH blocked directions),
the swap against the picture on the far side of it in BOTH directions, and the
save against SRAM bytes plus the OAM the restored tile puts on screen after a
power cycle.
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
ROM = BUILD / "rpg.sfc"
ASSETS = BUILD / "assets"
# One expression, the shape conftest resolves a module's map from at COLLECTION
# time (it refuses a module whose map it cannot see).
_JMAP = json.loads((SUPERFORGE / "build" / "rpg" / "symbol_map.json").read_text())

W, V, C, O, S = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
                 MemoryType.SnesCgRam, MemoryType.SnesSpriteRam,
                 MemoryType.SnesSaveRam)


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map")


# --- emitted geometry, never narrated ---------------------------------------
HOT = _sym("ES_RPG_HOT")["start"]           # WRAM (DP mirror) byte address
SM_CTL = _sym("ES_SM_CTL")["start"]
VISITS = _sym("US_VISITS")["start"]
V_TEXT_MAP = _sym("ES_V_TEXT_MAP", "town")["start"]     # VRAM word address
V_TEXT_CHR = _sym("ES_V_TEXT_CHR", "town")["start"]
V_TOWN_MAP = _sym("ES_V_TOWN_MAP", "town")["start"]     # BG1 town tilemap word base
V_DLG_CHR = _sym("ES_V_DLG_CHR", "town")["start"]
C_DLG = _sym("ES_C_DLG_PAL", "town")["start"]           # CGRAM word index
C_FLOOR = _sym("ES_C_FLOOR_PAL", "overworld")["start"]
DLG_CTL = _sym("ES_DLG_CTL", "town")["start"]
SRAM = _sym("ES_S_SAVE_SLOTS")["start"]
M7ORG = _sym("ES_M7ORG", "overworld")["start"]  # the Mode 7 camera origin the
                                                #   NMI commits to the PPU

# --- the rail's own constants (game/rpg/main.asm + scenes/town.asm) ---------
SCENE_OVERWORLD, SCENE_TOWN = 0, 1
SB_LINES = 44                       # the band seam: sky above, Mode 7 below
SPAWN_TX, SPAWN_TY = 64, 78
TOWN_NPC = (12, 10)
TOWN_SAVE = (20, 16)
TOWN_EXIT = (16, 24)
TOWN_BARRELS = ((8, 9), (24, 9))    # the two plaza props (were decorative torches)
TT_TORCH, TT_BARREL, TT_TORCH_LIT = 5, 9, 10    # gen_rpg_assets.py town tile ids
DLG_COL, DLG_ROW, DLG_W, DLG_H = 2, 18, 28, 9
NPC_PAGES = 3

BOOT = 120                          # the absolute frame every read lands on
TILE_PX = 8                         # one overworld tile, in world PIXELS — the
                                    #   distance a step arms. How many frames
                                    #   that takes is the region's answer (8
                                    #   walking plus 1 deciding on NTSC), which
                                    #   is why the walk helper below stops on
                                    #   the CAMERA TILE and never on a count.
WORLD_PX = 1024                     # the 128x128-tile torus


# --- driving -----------------------------------------------------------------
# A DETERMINISTIC CART, on purpose. Mesen persists battery SRAM to a .srm
# beside the ROM, so a module that saves in one test hands the NEXT test a
# valid slot — and this rail's boot load then restores a DIFFERENT town tile,
# which moves every walk that follows. That is a real cross-test coupling and
# it was observed here before it was written down: the virgin-cart test read
# (20,17) because the save-point test had run first.
#
# So every boot states the cart it wants. VIRGIN_SRAM is not zeros: virgin
# battery RAM is power-on GARBAGE on real hardware and `save`'s whole gate is
# that garbage is REJECTED by magic + version + length + CRC. Zeros would be a
# gentler input than the machine really sees.
VIRGIN_SRAM = bytes((i * 37 + 91) & 0xFF for i in range(64))


def _machine(cart=VIRGIN_SRAM):
    """A parked Machine at the absolute boot frame, with a stated cart."""
    m = Machine(str(ROM))
    m.write_bytes(S, SRAM, cart)
    m.advance(BOOT)
    return m


def _press(m, **buttons):
    """One edge: a frame with the button down, then two with it up.

    The town reads ES_INP_PRESS, so a HELD button is one press. Three frames
    is the smallest window that is unambiguously one edge on both scenes.
    """
    m.advance(1, pad1=buttons)
    m.advance(2)


def _hold(m, frames, **buttons):
    m.advance(frames, pad1=buttons)


def _scene(m):
    return m.read_byte(W, SM_CTL)


def _cam(m):
    return m.read_u16(W, HOT + 0), m.read_u16(W, HOT + 2)


def _town_tile(m):
    return m.read_u16(W, HOT + 4), m.read_u16(W, HOT + 6)


def _dlg(m):
    b = m.read_bytes(W, DLG_CTL, 4)
    return {"state": b[0], "dirty": b[1], "page": b[2], "pages": b[3]}


def _cell(m, col, row):
    """One BG3 tilemap cell, read back out of VRAM as a 16-bit tile word."""
    a = (V_TEXT_MAP + row * 32 + col) * 2
    b = m.read_bytes(V, a, 2)
    return b[0] | (b[1] << 8)


def _town_cell(m, col, row):
    """One BG1 TOWN tilemap cell — the destination region the tile upload
    produces — as its tile-id low byte. This is the drawn-and-blocking tile:
    rpg_town collision reads the SAME ROM bytes the PPU draws (rpg_town.asm)."""
    a = (V_TOWN_MAP + row * 32 + col) * 2
    b = m.read_bytes(V, a, 2)
    return (b[0] | (b[1] << 8)) & 0xFF


def _cgram_rgb(m, word_index):
    """One CGRAM word as the RGB888 the renderer produces.

    The 5->8 bit expansion is `(v << 3) | (v >> 2)`, not `v << 3`: the low
    three bits repeat the high three so full-scale 31 maps to 255 rather than
    248. Measured against the emulator's own output before it was written down
    — the naive shift is off by up to 7 per channel and turns every
    pixel-against-palette assertion into a false red."""
    b = m.read_bytes(C, word_index * 2, 2)
    w = b[0] | (b[1] << 8)
    return tuple(((v << 3) | (v >> 2))
                 for v in ((w & 31), ((w >> 5) & 31), ((w >> 10) & 31)))


def _shot(m, tmp_path, name):
    p = tmp_path / f"{name}.png"
    m.screenshot(str(p))
    return Image.open(p).convert("RGB")


def _yoff(img):
    """Screenshot row 0 is NOT display line 0.

    Mesen captures the 239-line overscan frame, so a 224-line picture is
    centred inside it with (239 - 224) // 2 = 7 lines above. Derived from the
    image the run actually produced rather than pinned, because a capture that
    is already 224 lines needs no offset and a pinned 7 would then be wrong.
    Measured the hard way first: an un-offset scan of the panel rectangle
    reported 2,864 'town pixels inside the panel' that were simply the town
    ABOVE it."""
    return max(0, (img.size[1] - 224) // 2)


def _box(img, x0, y0, x1, y1):
    """Pixels of a rectangle given in DISPLAY coordinates."""
    dy = _yoff(img)
    return [img.getpixel((x, y + dy))
            for y in range(y0, y1) for x in range(x0, x1)]


def _cell_px(img, col, row):
    """One 8x8 tilemap cell's pixels, INSET one pixel on every side.

    The inset is not squeamishness, it is a measured allowance. A BG layer's
    vertical scroll has a one-line ambiguity at VOFS = 0 (screen line N shows
    layer line N + 1), so a cell-aligned scan can read one line of its
    NEIGHBOUR. Measured on this rail: the panel's top border line lands one
    screenshot row above where DLG_ROW * 8 predicts, and an un-inset scan of
    the panel's first row therefore reported the town's last row as 'showing
    through'. Six by six still covers 56% of every cell and cannot borrow from
    the next one."""
    return set(_box(img, col * 8 + 1, row * 8 + 1, col * 8 + 7, row * 8 + 7))


def _m7(m):
    """The Mode 7 camera origin the NMI commits to M7X/M7Y every VBlank — the
    point the floor is drawn FROM. Used to DRIVE to a stated sub-tile offset;
    every assertion below reads pixels."""
    return m.read_u16(W, M7ORG + 0), m.read_u16(W, M7ORG + 2)


def _slide_px(m, direction, px, limit=40):
    """Hold `direction` until the camera has travelled exactly `px` pixels from
    where it started, then stop. Bounded in EMULATED frames, never wall time.

    The stop condition is the camera's own position, not a frame count, and
    that is the point of it: a step is a DISTANCE now, so 'four pixels into the
    tile' is a thing a test can ask for on either machine, where 'four frames
    in' is not."""
    axis = 1 if direction in ("up", "down") else 0
    sign = -1 if direction in ("up", "left") else 1
    target = (_m7(m)[axis] + sign * px) % WORLD_PX
    for _ in range(limit):
        if _m7(m)[axis] == target:
            return
        m.advance(1, pad1={direction: True})
    raise AssertionError(
        f"the camera never reached {target} ({px} px {direction}) in {limit} "
        f"frames — it is at {_m7(m)[axis]}")


def _walk_ow(m, direction, tiles, limit=40):
    """Hold a direction until the camera has committed `tiles` steps, then let
    the last slide land. Bounded in EMULATED frames, never wall time, and the
    stop condition is the camera tile rather than a frame count — the slide is
    TILE_PX pixels long and the frames that takes is the region's answer."""
    axis = 1 if direction in ("up", "down") else 0
    sign = -1 if direction in ("up", "left") else 1
    target = _cam(m)[axis] + sign * tiles
    for _ in range(limit):
        if _cam(m)[axis] == target:
            break
        m.advance(1, pad1={direction: True})
    else:
        raise AssertionError(f"camera never reached {target} walking {direction}")
    m.advance(TILE_PX + 2)                  # let the final slide land
    return _cam(m)


def _to_town(m):
    """Walk the four tiles north into the gate and ride the wipe.

    The gate BLOCKS and carries F_TOWN, so the avatar stops at it and the
    callback raises the swap at peak black. 40 frames covers four 8-frame
    slides with slack; 110 more covers the 20-frame OUT ramp, the blank frame
    and the 15-frame IN ramp.
    """
    _hold(m, 40, up=True)
    m.advance(110)


def _walk_town(m, dx=0, dy=0):
    for _ in range(abs(dx)):
        _press(m, right=(dx > 0), left=(dx < 0))
    for _ in range(abs(dy)):
        _press(m, down=(dy > 0), up=(dy < 0))


def _to_npc(m):
    """(16,20) -> (12,11): four left, nine up. Stops one south of the torch."""
    _walk_town(m, dx=-4)
    _walk_town(m, dy=-9)


@pytest.fixture(scope="module")
def rom_built():
    if not ROM.exists():
        pytest.fail(f"{ROM} is missing — run `make rpg` first")
    return ROM


# =============================================================================
# The overworld: the picture, and the collision that shapes the walk
# =============================================================================
def test_boot_renders_a_sky_band_over_a_mode7_floor(rom_built, tmp_path):
    """The split IS the sky: above the seam the backdrop shows, below it the
    floor does. Asserted on SCREEN PIXELS against the CGRAM word rpg_floor's
    palette claim owns, not against a register nobody can read back."""
    with _machine() as m:
        assert _scene(m) == SCENE_OVERWORLD
        img = _shot(m, tmp_path, "boot")
        sky = _cgram_rgb(m, C_FLOOR)        # word 0 of the floor palette
        above = _box(img, 8, 8, 248, SB_LINES - 8)
        assert set(above) == {sky}, (
            "every pixel above the band seam must be the backdrop — "
            f"found {len(set(above))} distinct colours")
        below = _box(img, 8, SB_LINES + 40, 248, 200)
        assert sky not in set(below), (
            "the floor band must not be showing the backdrop — the Mode 7 "
            "plane is not rendering")
        assert len(set(below)) >= 4, "the floor is a flat wash, not a world"


def test_a_blocked_press_leaves_the_picture_untouched_both_ways(rom_built,
                                                                tmp_path):
    """Collision's user-visible claim is that the WORLD DOES NOT MOVE. Proven
    on the frame, in BOTH blocked directions — a pond west of spawn and a tree
    east of it — because a one-axis test locks one axis and ships the other."""
    with _machine() as m:
        base = _shot(m, tmp_path, "before_block")
        for tag, btn in (("east", "right"), ("west", "left")):
            _hold(m, TILE_PX * 3, **{btn: True})
            m.advance(4)
            after = _shot(m, tmp_path, f"blocked_{tag}")
            assert list(after.tobytes()) == list(base.tobytes()), (
                f"pressing {btn} into a blocked tile moved the picture")
            assert _cam(m) == (SPAWN_TX, SPAWN_TY)


def test_a_walkable_press_moves_the_world_and_comes_back(rom_built, tmp_path):
    """Forward AND reverse. Walking north changes the picture; walking the same
    distance south restores the camera tile and the picture with it."""
    with _machine() as m:
        home = _shot(m, tmp_path, "home")
        _walk_ow(m, "up", 2)
        assert _cam(m) == (SPAWN_TX, SPAWN_TY - 2)
        moved = _shot(m, tmp_path, "moved")
        assert list(moved.tobytes()) != list(home.tobytes()), (
            "the camera advanced two tiles and the screen did not change")
        _walk_ow(m, "down", 2)
        assert _cam(m) == (SPAWN_TX, SPAWN_TY)
        back = _shot(m, tmp_path, "back")
        assert list(back.tobytes()) == list(home.tobytes()), (
            "the return walk did not restore the picture — the reverse "
            "direction is broken while the forward one works")


def test_the_slide_walks_the_floor_across_the_tile_and_lands_on_the_grid(
        rom_built, tmp_path):
    """A step is a DISTANCE: `rpg_hot`'s step byte holds the PIXELS REMAINING
    to the destination tile and the walk lays down the whole pixels the
    region's timebase publishes. This is the property that redefinition has to
    keep true, and it is a claim about the floor, so it is read on the FLOOR.

    THE SCREEN IS THE ONLY PLACE IT SHOWS. The overworld avatar is pinned at
    the affine pivot — the world moves under it — so there is no OAM byte and
    no VRAM byte that carries the slide. What moves is the Mode 7 camera
    origin the NMI commits, and what that produces is pixels.

    Three arms, and the middle one is the one that matters:
      - MID-TILE the floor is somewhere ELSE than at either end. A stepper
        that snapped to the grid would render one of the two endpoints here,
        and this is what catches it;
      - the LANDING renders exactly the picture the camera-anchored walk
        settles on one tile north, so the slide's distance is the tile's, to
        the pixel;
      - and the landing is at REST: a further frame changes nothing.

    TWO FRAME COSTS ARE COUNTED RATHER THAN WORKED AROUND. A capture spends
    an emulated frame (`Machine.take_screenshot`), and the PPU renders the
    camera origin the NMI committed on the PREVIOUS VBlank — so the picture
    always trails the WRAM origin by one frame. Driving to seven of the
    tile's eight pixels therefore RENDERS six, which is mid-tile either way;
    the capture's own frame lays the eighth; and one further frame is what
    carries the landed origin into the picture.
    """
    with _machine() as m:
        home = _shot(m, tmp_path, "slide_home")
        _slide_px(m, "up", TILE_PX - 1)     # the origin at 7 of 8; the PPU at 6
        mid = _shot(m, tmp_path, "slide_mid")   # ...its frame lays the eighth
        m.advance(1)                        # the landed origin reaches the PPU
        landed = _shot(m, tmp_path, "slide_landed")
        still = _shot(m, tmp_path, "slide_still")
        assert _cam(m) == (SPAWN_TX, SPAWN_TY - 1)
    with _machine() as m2:
        _walk_ow(m2, "up", 1)
        settled = _shot(m2, tmp_path, "slide_settled")

    def b(im):
        return list(im.tobytes())

    assert b(mid) != b(home), (
        "mid-slide the floor is still the spawn picture — the walk is not "
        "animating across the tile")
    assert b(mid) != b(landed), (
        "mid-slide and the landing render the same floor — the slide is "
        "snapping to the grid instead of walking across it")
    assert b(landed) != b(home)
    assert b(landed) == b(still), (
        "the floor moved after the slide landed — the walk overran its tile")
    assert b(landed) == b(settled), (
        "the landed slide is not the same picture as the settled camera one "
        "tile north — the step's distance and the grid disagree")


# =============================================================================
# The swap, both ways
# =============================================================================
def test_the_gate_wipes_into_the_town_and_the_gate_wipes_back(rom_built,
                                                              tmp_path):
    with _machine() as m:
        ow = _shot(m, tmp_path, "ow_before")
        _to_town(m)
        assert _scene(m) == SCENE_TOWN
        town = _shot(m, tmp_path, "town")
        assert list(town.tobytes()) != list(ow.tobytes())
        # the Mode 1 room has no sky band: the top rows are the room, not the
        # backdrop-only band the Mode 7 scene shows
        assert len(set(_box(town, 8, 8, 248, SB_LINES - 8))) > 1
        # ...and back out through the south gate at (16,24). Walking ONTO the
        # gate arms the wipe — NO A — matching the entry mechanic and the
        # villager's "WALK ONTO IT". (The focused case below proves A is inert
        # for the exit; here the round trip just exercises both wipe
        # directions.)
        _walk_town(m, dy=4)
        assert _town_tile(m) == TOWN_EXIT
        m.advance(130)                  # ride OUT + blank + IN, no A pressed
        assert _scene(m) == SCENE_OVERWORLD
        again = _shot(m, tmp_path, "ow_after")
        assert set(_box(again, 8, 8, 248, SB_LINES - 8)) == set(
            _box(ow, 8, 8, 248, SB_LINES - 8)), (
            "the return did not restore the Mode 7 sky band")


# =============================================================================
# The town plaza layout
# =============================================================================
def test_holding_a_direction_walks_tile_by_tile_and_a_tap_moves_one(rom_built):
    """The town HOLDS to walk, rather than needing a tap per tile. The bug
    this closes was that holding did nothing past the first tile; the fix is an
    auto-repeat throttle over the same try_step machine.

    Three arms, driven as full input cycles and asserted on the avatar's OAM —
    what the player SEES — not a WRAM proxy:
      - a SINGLE TAP moves exactly ONE tile (a tap is never throttled),
      - a HELD direction walks MANY tiles tile-by-tile (the bug it fixes), and
      - a dialog open FREEZES a HELD walk (the dialog_is_open gate) — the
        existing freeze test drives taps; this drives a hold."""
    # --- a single tap: exactly one tile, OAM lands on tile*8 ---
    with _machine() as m:
        _to_town(m)
        assert tuple(m.read_bytes(O, 0, 2)) == (16 * 8, 20 * 8)   # spawn
        _press(m, right=True)
        m.advance(1)                             # let the OAM park
        assert tuple(m.read_bytes(O, 0, 2)) == (17 * 8, 20 * 8), (
            "a single tap did not move exactly one tile")
    # --- a HELD direction: many tiles, tile-aligned, OAM tracks the tile ---
    with _machine() as m:
        _to_town(m)
        m.advance(40, pad1={"right": True})      # hold RIGHT across the plaza
        m.advance(2)                             # let the last step's OAM park
        held = tuple(m.read_bytes(O, 0, 2))
        tx, ty = _town_tile(m)
        assert tx - 16 >= 4, (
            f"holding RIGHT moved only {tx - 16} tile(s) — the walk stalls past "
            "tile 1, the pilot bug")
        assert held == (tx * 8, ty * 8), (
            f"the avatar's OAM {held} is not on its tile {(tx, ty)} * 8")
        assert ty == 20, "the held walk drifted off its row"
    # --- a dialog open FREEZES a held walk ---
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        _press(m, a=True)
        m.advance(3)
        assert _dlg(m)["state"] == 1
        frozen = m.read_bytes(O, 0, 2)
        m.advance(20, pad1={"right": True})      # HOLD right with the panel open
        assert m.read_bytes(O, 0, 2) == frozen, (
            "a held direction moved the avatar while the dialog was open")


def test_the_town_avatar_is_never_drawn_between_tiles(rom_built):
    """The town has NO sub-tile pixel state — `draw_actors` writes tile*8 and
    nothing else — and the timebase's published step is SHARED with the
    overworld, where the same number is spent in PIXELS. So the thing worth
    proving is that no pixel value can reach this renderer: across a long held
    walk, on EVERY frame, the drawn position is on the grid.

    Read on the OAM — the sprite table the PPU draws from — and not on the
    tile index behind it, because the index is exactly the variable that
    cannot be wrong here. A leak would show up between the index and the
    pixels, which is the one place the index cannot see.

    BOTH DIRECTIONS, and that is not symmetry for its own sake: the throttle
    now CARRIES its overshoot between tiles, so a walk that reverses re-enters
    the arithmetic mid-count where a one-way walk never does.
    """
    with _machine() as m:
        _to_town(m)
        seen = set()
        for direction in ("right", "left", "right"):
            for _ in range(40):
                m.advance(1, pad1={direction: True})
                seen.add(tuple(m.read_bytes(O, 0, 2)))
    off = sorted(p for p in seen if p[0] % 8 or p[1] % 8)
    assert not off, (
        f"the town avatar was drawn off the tile grid at {off} — a pixel term "
        "has leaked into a renderer that has none")
    xs = sorted({p[0] for p in seen})
    assert len(xs) >= 4, (
        f"the avatar only occupied {len(xs)} column(s) ({xs}) — the held walk "
        "did not run, so this proved nothing")
    assert {p[1] for p in seen} == {20 * 8}, (
        "the horizontal walk drifted off its row")


def test_saving_flares_the_save_torch_then_restores_it(rom_built):
    """With the save torch now unique, the save is discoverable,
    and the panel's 'THE TORCH FLARES ONCE' is made HONEST by a real flare — a
    VBlank tile swap on the save-torch cell (20,16). Read on the BG1 tilemap IN
    VRAM (the destination town_flare_commit writes from the NMI), driven as a
    full cycle: the normal torch -> the LIT torch while flaring -> the normal
    torch restored after the window. The save panel opening is the
    discoverability half."""
    with _machine() as m:
        _to_town(m)
        _walk_town(m, dx=4)                  # (16,20) -> (20,20)
        _walk_town(m, dy=-3)                 # (20,20) -> (20,17), one S of the torch
        assert _town_tile(m) == (20, 17)
        assert _town_cell(m, *TOWN_SAVE) == TT_TORCH, "the save torch is not a torch pre-save"
        _press(m, a=True)                    # SAVE at the torch
        m.advance(3)
        assert _dlg(m)["state"] == 1, "the save panel did not open — not discoverable"
        assert _town_cell(m, *TOWN_SAVE) == TT_TORCH_LIT, (
            "the save torch did not flare — the panel's 'FLARES ONCE' is a lie")
        m.advance(30)                        # ride out the flare window
        assert _town_cell(m, *TOWN_SAVE) == TT_TORCH, (
            "the flare did not restore the save torch tile")


def test_walking_onto_the_south_gate_wipes_out_without_an_a_press(rom_built):
    """The exit fires on WALKING ONTO the gate (16,24) — the villager's
    'WALK ONTO IT' instruction and the entry mechanic — and A no longer takes
    the gate (the A-press exit path is removed).

    Driven so the STEP is provably the trigger, not A. 'A while ON the gate' is
    not a reachable state to test in isolation: the gate is a walkable tile, so
    stepping onto it arms the wipe the same frame (being on the gate <=> the
    wipe is armed), and a saved game only ever restores near the save point. So
    the removal is proven two ways instead: (a) A pressed one tile NORTH of the
    gate does nothing — the scene and the avatar's tile are unchanged — and
    (b) the final STEP onto the gate, with NO A, is what lands the swap in the
    overworld. Asserted on the scene id the swap writes and the avatar's tile."""
    with _machine() as m:
        _to_town(m)
        _walk_town(m, dy=3)                  # (16,20) -> (16,23), one N of the gate
        assert _town_tile(m) == (16, 23)
        assert _scene(m) == SCENE_TOWN
        _press(m, a=True)                    # A off the gate: inert for the exit
        m.advance(6)
        assert _scene(m) == SCENE_TOWN, "A triggered the exit — the path is not removed"
        assert _town_tile(m) == (16, 23), "A moved the avatar"
        _walk_town(m, dy=1)                  # STEP onto the gate (16,24) — NO A
        assert _town_tile(m) == TOWN_EXIT
        m.advance(130)                       # ride OUT + blank + IN
        assert _scene(m) == SCENE_OVERWORLD, "walking onto the gate did not wipe out"



def test_the_plaza_decor_is_barrels_not_torches(rom_built):
    """The two DECORATIVE torches at (8,9)/(24,9) are a blocking
    BARREL prop, so the SAVE torch (20,16) is the plaza's only torch and the
    save point reads as unique. The NPC-post torch (12,10) stays — the villager
    sprite sits on it.

    Read on the BG1 town tilemap IN VRAM — the destination region the CHR/map
    upload produces — not a source byte and not a proxy variable. And the barrel must
    BLOCK the walk: a step onto it leaves the avatar's tile AND its OAM
    untouched, the user-visible half of 'it is a solid prop'."""
    with _machine() as m:
        _to_town(m)
        for (c, r) in TOWN_BARRELS:
            t = _town_cell(m, c, r)
            assert t == TT_BARREL, f"({c},{r}) is tile {t}, not the barrel"
            assert t != TT_TORCH, f"({c},{r}) is still a torch"
        assert _town_cell(m, *TOWN_SAVE) == TT_TORCH, (
            "the save torch (20,16) is no longer a torch — it must stay one")
        assert _town_cell(m, *TOWN_NPC) == TT_TORCH, (
            "the NPC-post torch (12,10) changed — it must stay a torch")
        # the barrel BLOCKS. Walk to (8,10), the cell below the left barrel, and
        # a step up must not move the avatar — proven on the OAM the town draws.
        _walk_town(m, dx=-8)                 # (16,20) -> (8,20)
        _walk_town(m, dy=-10)                # (8,20)  -> (8,10)
        assert _town_tile(m) == (8, 10)
        oam_before = m.read_bytes(O, 0, 2)
        _walk_town(m, dy=-1)                 # attempt to step ONTO the barrel (8,9)
        assert _town_tile(m) == (8, 10), "the barrel did not block the step"
        assert m.read_bytes(O, 0, 2) == oam_before, (
            "the avatar's OAM moved into the barrel cell")


# =============================================================================
# `dialog` — the debut. Opacity, the flow, and the restore.
# =============================================================================
def test_the_panel_is_opaque_over_the_running_scene(rom_built, tmp_path):
    """THE OPACITY CONTRACT, on pixels, over exactly the cells it covers.

    The contract `dialog` states is *no scene pixel shows through a cell the
    NINE-PATCH owns* — the frame and the body fill. Those cells are opaque CHR
    by construction (gen_dialog_assets.py asserts every pixel of all nine tiles
    is index >= 1) and this is the check that they composite that way over a
    live scene, which a VRAM-only assertion structurally cannot see.

    THE THREE TEXT ROWS ARE DELIBERATELY EXCLUDED, and that exclusion is a
    stated limit rather than a gap in the test: a printed glyph is `bg_text`'s
    2bpp CHR, whose entire background is index 0 — TRANSPARENT by hardware —
    so the running scene shows through 57-69% of each text row as a full-width
    band, not just slivers between strokes (measured). `dialog/feature.toml`
    records the same limit with a fix sketched. Asserting opacity there would
    be asserting something the feature does not claim.
    """
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        text_rows = {DLG_ROW + 1, DLG_ROW + 3, DLG_ROW + 5}
        before = _shot(m, tmp_path, "pre_open")
        _press(m, a=True)
        m.advance(3)
        assert _dlg(m)["state"] == 1
        img = _shot(m, tmp_path, "open")
        panel = {_cgram_rgb(m, C_DLG + i) for i in range(4)}
        town_was = set()
        seen = set()
        for row in range(DLG_ROW, DLG_ROW + DLG_H):
            cols = ((DLG_COL, DLG_COL + DLG_W - 1) if row in text_rows
                    else range(DLG_COL, DLG_COL + DLG_W))
            for col in cols:
                seen |= _cell_px(img, col, row)
                town_was |= _cell_px(before, col, row)
        assert seen <= panel, (
            "a pixel of a nine-patch cell is not a panel colour — the scene is "
            f"showing through: {sorted(seen - panel)}")
        assert town_was - panel, (
            "the town was already panel-coloured there, so this proves nothing")


def test_the_panel_text_renders_in_the_text_palette(rom_built, tmp_path):
    """The other half of the row the opacity test excludes: the glyphs are
    really on screen, in bg_text's palette, over the panel's own body."""
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        _press(m, a=True)
        m.advance(3)
        img = _shot(m, tmp_path, "text")
        row = DLG_ROW + 1
        px = set(_box(img, (DLG_COL + 1) * 8, row * 8,
                      (DLG_COL + DLG_W - 1) * 8, row * 8 + 8))
        ink = {_cgram_rgb(m, 28 + i) for i in range(1, 4)}
        assert px & ink, "no glyph ink on the panel's first text row"
        body = _cgram_rgb(m, C_DLG + 1)
        assert body in px, "the panel body is not behind the text"


def test_the_panel_writes_the_nine_patch_into_the_bg3_tilemap(rom_built):
    """The DESTINATION region, byte for byte: the frame's corners and edges are
    the nine-patch tiles at the index the reach arithmetic implies, and the
    interior is fill. `dialog`'s page is addressed at (page - BG3 base) / 8, so
    this also proves the reach the build asserts actually holds at run time."""
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        _press(m, a=True)
        m.advance(3)
        tile0 = (V_DLG_CHR - V_TEXT_CHR) // 8
        assert 0 < tile0 < 1024, "the panel page is outside BG3's tile reach"
        attr = tile0 | ((C_DLG // 4) << 10) | (1 << 13)
        r0, r1 = DLG_ROW, DLG_ROW + DLG_H - 1
        c0, c1 = DLG_COL, DLG_COL + DLG_W - 1
        assert _cell(m, c0, r0) == attr | 0, "top-left is not the TL patch"
        assert _cell(m, c1, r0) == attr | 2, "top-right is not the TR patch"
        assert _cell(m, c0, r1) == attr | 6, "bottom-left is not the BL patch"
        assert _cell(m, c1, r1) == attr | 8, "bottom-right is not the BR patch"
        assert _cell(m, c0 + 1, r0) == attr | 1
        assert _cell(m, c0, r0 + 2) == attr | 3
        assert _cell(m, c1, r0 + 2) == attr | 5
        assert _cell(m, c0 + 1, r1) == attr | 7
        assert _cell(m, c0 + 1, r0 + 2) == attr | 4, "interior is not fill"


def test_the_text_flows_page_by_page_and_the_last_page_closes_it(rom_built,
                                                                 tmp_path):
    """THE STATE CYCLE, driven whole: open -> page 2 -> page 3 -> closed. Each
    page is asserted on the RENDERED text row, not on the page counter — the
    counter is exactly the proxy variable the discipline forbids."""
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        rows = []
        _press(m, a=True)
        m.advance(3)
        for page in range(NPC_PAGES):
            assert _dlg(m)["state"] == 1, f"panel closed early on page {page}"
            assert _dlg(m)["page"] == page
            rows.append(bytes(m.read_bytes(
                V, (V_TEXT_MAP + (DLG_ROW + 1) * 32 + DLG_COL + 1) * 2, 52)))
            if page < NPC_PAGES - 1:
                _press(m, a=True)
                m.advance(3)
        assert len(set(rows)) == NPC_PAGES, (
            "two pages rendered the same first line — the page table index "
            "is not advancing")
        _press(m, a=True)          # the page after the last one CLOSES it
        m.advance(3)
        assert _dlg(m)["state"] == 0


def test_closing_restores_the_scene_behind_the_box_and_it_reopens(rom_built,
                                                                  tmp_path):
    """The user-visible invariant, stated as pixels: what was behind the box
    comes back. Then REOPEN — the half that catches a panel which restores
    itself into an unusable state."""
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        rect = (DLG_COL * 8, DLG_ROW * 8,
                (DLG_COL + DLG_W) * 8, (DLG_ROW + DLG_H) * 8)
        before = _box(_shot(m, tmp_path, "r_before"), *rect)
        _press(m, a=True)
        m.advance(3)
        opened = _box(_shot(m, tmp_path, "r_open"), *rect)
        assert opened != before
        for _ in range(NPC_PAGES):
            _press(m, a=True)
            m.advance(3)
        assert _dlg(m)["state"] == 0
        after = _box(_shot(m, tmp_path, "r_closed"), *rect)
        assert after == before, (
            "the scene behind the box did not come back — 'freeze' means the "
            "pixels return, not that a variable reads zero")
        blank = _cell(m, DLG_COL, DLG_ROW)
        assert blank == ((7 << 10) | (1 << 13)), (
            "the closed panel left a non-blank cell in bg_text's tilemap")
        # ---- REOPEN ------------------------------------------------------
        _press(m, a=True)
        m.advance(3)
        assert _dlg(m)["state"] == 1 and _dlg(m)["page"] == 0
        again = _box(_shot(m, tmp_path, "r_reopen"), *rect)
        assert again == opened, (
            "the second open does not render what the first one did")


def test_the_open_panel_freezes_the_walk(rom_built):
    """A real dialog blocks the walk, and the freeze is released on close —
    both halves, because a freeze that never lifts also passes a one-way test.
    Asserted on the avatar's OAM position, which is what the player sees."""
    with _machine() as m:
        _to_town(m)
        _to_npc(m)
        home = m.read_bytes(O, 0, 2)
        _press(m, a=True)
        m.advance(3)
        _walk_town(m, dx=1)
        _walk_town(m, dy=1)
        assert m.read_bytes(O, 0, 2) == home, "the avatar moved with the panel open"
        for _ in range(NPC_PAGES):
            _press(m, a=True)
            m.advance(3)
        _walk_town(m, dy=1)
        assert m.read_bytes(O, 0, 2) != home, (
            "the walk is still frozen after the panel closed")


# =============================================================================
# The battery: SRAM bytes, then a power cycle
# =============================================================================
def test_the_save_point_writes_a_verifiable_slot(rom_built):
    """The save feature's own output region is SRAM, and virgin SRAM is
    power-on GARBAGE under the random regime — so the assertion is that the
    header appears where there was noise, not that some byte is zero."""
    with _machine() as m:
        _to_town(m)
        _walk_town(m, dx=4)
        _walk_town(m, dy=-3)
        assert _town_tile(m) == (20, 17)
        _press(m, a=True)
        m.advance(4)
        slot = m.read_bytes(S, SRAM, 16)
        assert slot[0:2] == b"SF", "no save header in slot 0"
        assert slot[2] == 1 and slot[4] | (slot[5] << 8) == 6
        assert slot[8] | (slot[9] << 8) == 20         # town tile x
        assert slot[10] | (slot[11] << 8) == 17       # town tile y
        assert slot[12] | (slot[13] << 8) == 1        # visits


def test_a_power_cycle_restores_the_saved_tile_and_it_renders_there(rom_built,
                                                                    tmp_path):
    """THE ROUND TRIP. A second power-on with the same SRAM must put the avatar
    on the SAVED tile, and the proof is the OAM the town renders — not the
    restored variable, which is exactly the proxy the discipline forbids."""
    with _machine() as m:
        _to_town(m)
        _walk_town(m, dx=4)
        _walk_town(m, dy=-3)
        _press(m, a=True)
        m.advance(4)
        saved = bytes(m.read_bytes(S, SRAM, 32))
    with _machine(saved) as m2:          # the cart, carried across the cycle
        assert _town_tile(m2) == (20, 17), "the boot load did not restore"
        _to_town(m2)
        assert _scene(m2) == SCENE_TOWN
        x, y = m2.read_bytes(O, 0, 2)
        assert (x, y) == (20 * 8, 17 * 8), (
            f"the avatar rendered at OAM ({x},{y}), not at the saved tile")


def test_a_virgin_cart_starts_at_the_default_town_tile(rom_built):
    """The other arm of the same gate: garbage SRAM must be REJECTED, and the
    rejection is visible as the default spawn rather than a plausible tile
    read out of noise.

    The docstring says VISIBLE, so the assertion is the OAM the town renders
    the avatar into — its sibling above already gets this right, and asserting
    only the WRAM tile here would be the proxy the discipline forbids."""
    with _machine() as m:
        assert _town_tile(m) == (16, 20)
        assert m.read_u16(W, VISITS) == 0
        _to_town(m)
        assert _scene(m) == SCENE_TOWN
        x, y = m.read_bytes(O, 0, 2)
        assert (x, y) == (16 * 8, 20 * 8), (
            f"the avatar rendered at OAM ({x},{y}), not at the default spawn")


# =============================================================================
# The music: SPC-side hardware state, across the swap
# =============================================================================
# The rail composes `audio` + `tad_rom` and pays 32,768 B of ROM and an
# exclusive APUIO claim for them, and the rail's done-condition is
# "Music plays throughout and survives every scene swap". Both halves are
# driven here, because a declaration that nothing drives is the one class the
# allocator structurally cannot catch — it proves claims do not COLLIDE, not
# that a claimed resource is USED. This rail shipped silent through a whole
# change with 13 green tests, none of which looked.
#
# TEST SURFACE, per CLAUDE.md rule 2: for audio the rendered output is
# SPC-side HARDWARE state — the S-DSP register file, and the driver's own
# song-position counter in SPC RAM. Both live on the audio co-processor and
# are written by the SPC executing the uploaded driver, so neither is a
# CPU-side proxy. TadPrivate_state (WRAM) is corroboration only, never the
# load-bearing assertion; it is the one reading here that IS CPU-side.
MVOL_L, MVOL_R, FLG = 0x0C, 0x1C, 0x6C   # S-DSP register file offsets
EVOL_L, EFB = 0x2C, 0x0D
SONG_TICK = 0x0003                  # songTickCounter, driver zeropage (u16)
STATE_PLAYING = 0x82                # TadState::PLAYING (vendor/tad tad-audio.s)
SONG_EVOL, SONG_EFB = 12, 24        # the song's own #EchoVolume / #EchoFeedback
TAD_STATE = _sym("ES_TAD_BSS")["start"] + 2   # +2 = TadPrivate_state


def _tick(m):
    b = m.read_bytes(MemoryType.SpcRam, SONG_TICK, 2)
    return b[0] | (b[1] << 8)


def _dsp(m):
    return m.read_bytes(MemoryType.SpcDspRegisters, 0, 128)


def test_the_rail_actually_plays_music(rom_built):
    """The S-DSP has been PROGRAMMED and the song is running on the SPC.

    Under the random power-on regime an un-driven DSP holds garbage — which is
    exactly how the silence was caught: this rail read MVOL $97/$B9 FLG $38
    before the driver was wired. So the assertion is that the master volume is
    at the driver's value and FLG's mute/reset bits are CLEAR, and that the
    SPC's own song-position counter ADVANCES between two parked frames."""
    with _machine() as m:
        m.advance(240)
        d = _dsp(m)
        assert d[MVOL_L] == 0x7F and d[MVOL_R] == 0x7F, (
            f"S-DSP master volume is {d[MVOL_L]:#04x}/{d[MVOL_R]:#04x}, not the "
            "driver's $7F/$7F — nothing programmed the DSP")
        assert d[FLG] & 0xE0 == 0, (
            f"S-DSP FLG={d[FLG]:#04x}: reset/mute/echo-write-disable not clear")
        # The song's OWN echo header reached the chip — this is slice_b_song
        # playing, not merely a driver sitting idle at its defaults.
        assert (d[EVOL_L], d[EFB]) == (SONG_EVOL, SONG_EFB), (
            f"echo header is {d[EVOL_L]}/{d[EFB]}, not the song's "
            f"{SONG_EVOL}/{SONG_EFB}")
        t0 = _tick(m)
        m.advance(60)
        assert _tick(m) > t0, (
            f"songTickCounter parked at {t0} — the SPC is not advancing the song")
        assert m.read_byte(W, TAD_STATE) == STATE_PLAYING


def test_the_song_survives_the_swap_both_ways(rom_built):
    """PERSISTENCE — and it is the ABSENCE of a second Tad_LoadSong that
    provides it, so the way to prove it is that the SPC never restarts.

    The counter is free-running across the song's own loop, so a reload is
    visible as a RESTART near zero rather than as a stall. Sampled either side
    of both wipes, it must only ever go up, and the driver must never re-enter
    a loader state."""
    with _machine() as m:
        m.advance(120)
        ticks = [("overworld", _tick(m), m.read_byte(W, TAD_STATE))]
        _to_town(m)
        assert _scene(m) == SCENE_TOWN
        ticks.append(("town", _tick(m), m.read_byte(W, TAD_STATE)))
        # ...and back out through the south gate at (16,24), the other
        # direction — walking ONTO the gate arms the wipe (no A), as the
        # round-trip test above drives it.
        _walk_town(m, dy=4)
        assert _town_tile(m) == TOWN_EXIT
        m.advance(130)
        assert _scene(m) == SCENE_OVERWORLD, "never wiped back to the overworld"
        ticks.append(("overworld_again", _tick(m), m.read_byte(W, TAD_STATE)))

        seq = [t for _, t, _ in ticks]
        assert all(b > a for a, b in zip(seq, seq[1:])), (
            f"songTickCounter not monotonic across the swaps: {ticks} — a "
            "restart near zero means something re-loaded the song")
        for name, _, st in ticks:
            assert st == STATE_PLAYING, (
                f"{name}: TadPrivate_state={st:#04x} != PLAYING")
        # The DSP is still live on the far side of both wipes.
        d = _dsp(m)
        assert d[MVOL_L] == 0x7F and d[FLG] & 0xE0 == 0
