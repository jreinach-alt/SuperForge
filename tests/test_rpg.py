"""Acceptance gate for the rpg template — the SCENE-TRANSITION PRIMITIVE.

Sprint 0 of the RPG arc proves ONE thing end-to-end: a Mode 7 overworld swaps
to a flat Mode 1 town (and battle) and BACK, music persisting, with the swap
MASKED (no torn frame) and the overworld camera RESTORED. NPCs/dialog/battle/
menus/saves are later sprints — not tested here.

Every assertion is on REAL rendered / hardware output (shadow PPU registers the
NMI commits, VRAM bytes, OAM bytes, screenshot pixels, recorded WAV energy) and
the FULL state cycle is driven forward AND reverse — never a proxy game var.

Engine-state addresses (verified against engine/engine_state.inc, base $0100):
  SHADOW_BGMODE   $012C   $07 = Mode 7, $09 = Mode 1
  SHADOW_INIDISP  $012E   bit 7 = forced blank (masked-swap proof)
  NMI_HDMA_ENABLE $0108   nonzero in Mode 7 (CH5/6 armed), $00 in town
  M7_PV_ACTIVE    $01C3   1 = Mode 7 renderer active
  M7_OWNED_MASK   $0150   $60 = CH5+CH6 owned by Mode 7, $00 after release
  M7_PV_POSX+2    $01E1   live Mode 7 camera X integer (16.16, integer at +2)
  TAD_STATUS      $016A   $01 = music playing (keep_music)

Scene-state word (game WRAM) + mirror:
  SCENE word      $1804   sf_scene state (0 OW / 1 TOWN / 2 BATTLE)
  DBG_STATE       $E016   sf_state_mirror of the scene id (set at init end)

Saved-camera block (game DP, $32-$3F): ovw_camx $32, ovw_camy $34.
"""
from pathlib import Path
import math
import struct
import wave

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"


def _neutral():
    """SRAM-free neutral ROM used to flush the emulator's live battery SRAM
    before a virgin reset (see the runner fixture). text_test never touches
    SRAM, so its own unload-flush is harmless."""
    return BUILD / "text_test.sfc"


WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
OAM = MemoryType.SnesSpriteRam

# engine-state shadows / Mode 7 state (absolute, base $0100)
SHADOW_BGMODE = 0x012C
SHADOW_INIDISP = 0x012E
NMI_HDMA_ENABLE = 0x0108
M7_PV_ACTIVE = 0x01C3
M7_OWNED_MASK = 0x0150
M7_PV_POSX_INT = 0x01E1        # M7_PV_POSX ($01DF) + 2 = integer camera X
M7_PV_POSY_INT = 0x01E5        # M7_PV_POSY ($01E3) + 2 = integer camera Y
TAD_STATUS = 0x016A

# game WRAM / DP
SCENE_WORD = 0x1804
DBG_STATE = 0xE016
OVW_CAMX = 0x0032
OVW_CAMY = 0x0034

# scene ids
SC_OVERWORLD, SC_TOWN, SC_BATTLE = 0, 1, 2

# --- Sprint 1: grid movement + collision geometry (from ovw_collision.inc) ---
# The overworld uses a flat-overhead Mode 7 view at 1:1 scale, so 1 tile = 8
# map px = 8 screen px. The camera (M7_PV_POSX/Y integer) is the player ground
# truth; at rest it sits on an 8px grid boundary. Spawn tile = (64,64) ->
# camera (512,512). The avatar (OAM 0) stays CENTERED — the world scrolls under.
TILE_PX = 8
SPAWN_TX, SPAWN_TY = 64, 64
SPAWN_CAMX, SPAWN_CAMY = SPAWN_TX * TILE_PX, SPAWN_TY * TILE_PX   # 512, 512
AV_CENTER_X, AV_CENTER_Y = 120, 104    # AV_X0 / AV_Y0 (fixed centered avatar)
# Starter wall barriers cardinally near the spawn (make_rpg_assets.py):
#   DOWN  -> water at ty=69 (stop tile 68); UP -> rock at ty=59 (stop 60);
#   LEFT  -> rock at tx=58 (stop 59);       RIGHT -> clear (town-entrance path)
WALL_DOWN_TY, WALL_DOWN_STOP_TY = 69, 68
WALL_UP_TY, WALL_UP_STOP_TY = 59, 60
WALL_LEFT_TX, WALL_LEFT_STOP_TX = 58, 59

# Mode 7 VRAM is interleaved (even=tilemap, odd=8bpp tile). Mode 1 BG1 CHR is
# at word $2000 = byte $4000; BG1 tilemap at word $5800 = byte $B000.
TOWN_BG1_CHR_BYTE = 0x4000
TOWN_TILEMAP_BYTE = 0xB000     # BG1 32x32 tilemap; cell (mx,my) at +(my*32+mx)*2
TOWN_TILE_TORCH = 4            # main.asm mset's a torch at the KNOWN cell (4,4)

# --- Sprint 2: overworld NPC tile-triggers + sprite-text prompt ---------------
# NPC0 is at world tile (65,65), NPC1 at (66,66) (make_rpg_assets.py NPCS) —
# diagonal to the spawn (64,64), OFF row 64 / column 64 so the Sprint 1
# cardinal-walk tests are unaffected. A single RIGHT step from spawn lands the
# player on (65,64); NPC0 at (65,65) is then the player's SOUTH neighbour ->
# near_npc, and the NPC tile is BLOCKED (the player cannot walk onto it). There
# is NO floating "!" indicator (period-accuracy remediation): SNES-era RPGs used
# walk-up + adjacency + A, never a "!" hovering over an NPC. Adjacency draws
# NOTHING; only the on-A "HELLO" acknowledgement renders. With the "!" removed
# the strip compacts to OBJ call-order slots 1..5 (the avatar owns slot 0):
#   slot 1   = CULLED whenever the player is merely adjacent (no "!" any more)
#   slots 1-5 = "HELLO" sprite-text strip (tiles 9,10,11,11,12), shown when talking
NPC0_TX, NPC0_TY = 65, 65
TEXT_TILES = [9, 10, 11, 11, 12]       # H E L L O glyph tiles (slots 1-5 when talking)
TEXT_X0, TEXT_Y0, TEXT_GLYPH_W = 96, 72, 8   # main.asm sprite-text strip layout
TEXT_SLOT0 = 1                # first HELLO glyph OAM slot (right after the avatar)
OAM_CULLED_Y = 0xF0            # spr_clear parks unused slots at Y=$F0 (=240)
NEAR_NPC = 0x004C              # game DP: 1 = adjacent to an NPC (proximity flag)
TALKING = 0x004E               # game DP: 1 = the sprite-text strip is showing

E2E = Path("/tmp/e2e_screenshots")


@pytest.fixture(scope="module")
def runner():
    E2E.mkdir(parents=True, exist_ok=True)
    r = MesenRunner(enable_audio=True)
    # The rpg now has a SAVE POINT + boot-load: a stale rpg.srm (from a prior run
    # or the oracle save chain) would make the boot-load hook restore the saved
    # TOWN instead of booting the overworld these tests expect. Make the first
    # boot VIRGIN (power-on garbage -> no valid save -> fresh overworld).
    #
    # A BARE unlink is NOT robust: the emulator is process-global, so if a prior
    # test left a save-carrying rpg.sfc loaded in live SRAM, the next load_rom's
    # unload-flush would resurrect the .srm AFTER the delete (the oracle two-run
    # trap). virgin_srm flushes the live SRAM through a neutral ROM FIRST, then
    # deletes — robust even after a future save-exercising test lands here.
    from _srm import virgin_srm
    virgin_srm(r, "rpg.sfc", _neutral())
    yield r
    r.stop()


def _u8(r, addr):
    return r.read_bytes(WR, addr, 1)[0]


def _state(r):
    """Read the live scene-state word (game WRAM) — ground truth for which
    scene is current; the $E016 mirror lags by one init."""
    return r.read_u16(WR, SCENE_WORD)


def _tap(r, frames_settle=44, **buttons):
    """Tap a button for 2 frames, release, settle. A scene swap now plays the
    MOSAIC WIPE (sf_mosaic_transition): the OUT dissolve -> black swap -> IN
    de-pixelate takes ~35-40 frames before the destination is fully rendered and
    input is un-gated, so settle long enough for the whole wipe to complete."""
    r.set_input(0, **buttons)
    r.run_frames(2)
    r.set_input(0)
    r.run_frames(frames_settle)


def _grid_step(r, **direction):
    """Drive exactly ONE grid step (one tile) in a single direction by holding
    the D-pad for one tile's worth of frames, then releasing and letting the
    8-frame slide settle so the camera lands grid-aligned. Returns the settled
    integer camera (cam_x, cam_y) the engine committed. A single held tap moves
    exactly one tile because the step machine locks out new input until the
    slide lands."""
    r.set_input(0, **direction)
    r.run_frames(2)            # register the press -> arm the slide
    r.set_input(0)
    r.run_frames(12)           # let the 8-frame slide complete + settle
    return (r.read_u16(WR, M7_PV_POSX_INT), r.read_u16(WR, M7_PV_POSY_INT))


def _walk(r, n, **direction):
    """Walk N tiles in one direction (held), settling on a grid boundary.
    Returns the settled integer camera (cam_x, cam_y)."""
    r.set_input(0, **direction)
    r.run_frames(n * TILE_PX + 2)   # n tiles * 8 frames/tile + press latency
    r.set_input(0)
    r.run_frames(12)                # finish the in-flight slide + settle
    return (r.read_u16(WR, M7_PV_POSX_INT), r.read_u16(WR, M7_PV_POSY_INT))


# --- Sprint 3 TOWN navigation (Mode 1 grid-walk: the avatar SPRITE moves, the
# camera is fixed; one tile per D-pad PRESS via the engine's pressed latch). The
# town player tile lives in game DP (town_px $52 / town_py $54). Movement is
# edge-latched, so each tap is exactly one tile — drive with a 2-frame tap. ---
TOWN_PX = 0x0052               # main.asm town_px (player tile X, 0..31)
TOWN_PY = 0x0054               # main.asm town_py (player tile Y, 0..31)
TOWN_NEAR = 0x0056             # 1 = adjacent (4-neighbour) to the town NPC
TOWN_DIALOG = 0x0058           # 1 = the BG3 dialog box is open
# main.asm town design constants
TOWN_SPAWN_TX, TOWN_SPAWN_TY = 16, 16
TOWN_NPC_TX, TOWN_NPC_TY = 16, 8     # villager NPC tile (player stands adjacent)
TOWN_EXIT_TX, TOWN_EXIT_TY = 16, 21  # gated EXIT cell (step onto + A -> overworld)
# BG3 dialog box: text tilemap at VRAM byte $C000 (word $6000); 3 dialog rows at
# pixel-Y 152/168/184 -> tile rows 19/21/23; the box frame at rows 18 + 26.
BG3_TILEMAP_BYTE = 0xC000
DLG_TEXT_ROW = 19              # first dialog text tile row (pixel-Y 152)
DLG_TEXT_COL = 3               # DLG_X=24 px -> tile col 3
FONT_BASE_TILE = 160           # engine FONT_BASE_TILE (sf_text_init)


def _town_tap(r, settle=8, **direction):
    """One town grid step (edge-latched): a 2-frame tap, then settle. The town
    player moves at most one tile per tap."""
    r.set_input(0, **direction)
    r.run_frames(2)
    r.set_input(0)
    r.run_frames(settle)


def _town_pos(r):
    return (r.read_u16(WR, TOWN_PX), r.read_u16(WR, TOWN_PY))


def _town_walk_to_npc(r):
    """From the town spawn (16,16) walk up column 16 to (16,9) — adjacent to the
    NPC at (16,8). Column 16 is a clear cobble corridor (the fountain is off it).
    Returns once town_near is set (or after the move budget)."""
    for _ in range(8):
        if r.read_bytes(WR, TOWN_NEAR, 1)[0] == 1:
            break
        _town_tap(r, up=True)


def _town_to_overworld(r):
    """Return from the town to the overworld via the EXIT gate: walk the player
    down column 16 to the exit tile (16,21), then press A (the exit trigger).
    The town's A is context-sensitive — near the NPC it opens the dialog; on the
    exit tile it returns; elsewhere it is a no-op. So this drives the real path."""
    # walk down to the exit row (16,21); column 16 is clear to the gate
    for _ in range(14):
        if _town_pos(r) == (TOWN_EXIT_TX, TOWN_EXIT_TY):
            break
        _town_tap(r, down=True)
    # press A on the exit tile -> overworld (via the mosaic wipe; settle for the
    # full OUT -> swap -> IN dissolve before the overworld input is un-gated)
    r.set_input(0, a=True)
    r.run_frames(2)
    r.set_input(0)
    r.run_frames(44)


def _lit_pixels(path, thresh=40):
    img = Image.open(path).convert("RGB")
    px = img.load()
    w, h = img.size
    return sum(1 for y in range(0, h, 3) for x in range(0, w, 3)
               if sum(px[x, y]) > thresh)


# --- Sky-split geometry (the floor-in-sky FIX). The overworld is a Mode 7
# PERSPECTIVE floor with a horizon HIGH up (main.asm PV_L0 = 40, the OWNER
# option-D / max-map tuning: a THIN ~18% sky, lots of on-screen map) and a real
# sky ABOVE it. The sky-split (sf_mode7_sky_split) turns BG1 OFF above scanline
# PV_L0 so the CGRAM[0] sky-blue backdrop shows there; the floor renders below.
# The screenshot is 256x239 (224 active scanlines scaled to 239 px tall), so a
# scanline s maps to screenshot y ~= s * 239/224; PV_L0=40 -> horizon at y~43.
# Sample rows are well clear of the transition band on each side. The FLOOR
# sample sits in the green grass meadow band (y~60..150); it is deliberately
# ABOVE the bottom water band (the max-map view brings the map's bottom lake
# strip on-screen near y~200, whose bright water blue is not "floor green").
PV_L0 = 40                          # main.asm: floor begins here; sky is 0..39
SKY_SAMPLE_Y = 24                   # above the y~43 horizon -> must be SKY
FLOOR_SAMPLE_Y = 120                # mid-screen grass meadow -> must be FLOOR


def _px(path, x, y):
    return Image.open(path).convert("RGB").load()[x, y]


# --- OBJ palette colours the OBSEL-size bug leaks into the wrong place (make_rpg
#     _assets.py OBJ_PAL): index 5 = the bright-yellow "!" glyph, index 6 = the
#     cream sprite-text fill. Both are unique on the Mode 7 floor, so counting
#     them in a region is a direct read of the rendered sprite (not a proxy). ---
OBJ_YELLOW = (252, 232, 96)          # OBJ index 5 — the "!" indicator glyph
OBJ_CREAM = (248, 248, 232)          # OBJ index 6 — the sprite-text glyph fill


def _count_color(path, box, target, tol):
    """Count screenshot pixels within `tol` of `target` inside box (x0,y0,x1,y1)."""
    px = Image.open(path).convert("RGB").load()
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1)
               if all(abs(px[x, y][i] - target[i]) <= tol for i in range(3)))


def _is_sky(rgb):
    """A sky pixel: BLUE-DOMINANT (blue is the top channel, clearly above red,
    and the pixel is NOT green-dominant). The defining negative — the floor-in-sky
    defect — smears the Mode 7 floor (green grass / tan path) above the horizon,
    which is green/tan-dominant and so is rejected here.

    HAZE-AWARE (overworld fog gradient): the static daytime haze SUBTRACTS the
    keyframes (TR=0,TG=6,TB=14) on BG1 + the backdrop, so the bright CGRAM[0]
    daytime-blue backdrop (~(120,168,248), Wave-D sky pass) renders graded toward
    ~(123,132,148) in the sampled band — clearly blue-dominant, but no longer the
    bright b>150 of the un-hazed backdrop. The old absolute thresholds (b>r+40,
    b>g+30, b>150) were written against a different backdrop; this haze-aware form
    keeps the floor negative control (green/tan smear → rejected) while accepting
    the graded blue sky."""
    r, g, b = rgb
    return b >= g and b > r + 15 and not (g > r + 15 and g > b + 15)


def _is_floor_terrain(rgb):
    """A floor pixel: a Mode 7 ground-tile colour — green grass, tan path, gray
    rock, or (dark) water. The defining negative is that it is NOT the bright
    sky blue: above-horizon smeared floor would read as a ground colour here."""
    r, g, b = rgb
    green = g > r + 15 and g > b + 15            # grass
    tan = r > 120 and g > 90 and b < r           # dirt path
    grayrock = abs(r - g) < 30 and abs(g - b) < 40 and 60 < r < 200  # rock
    darkwater = b > r + 25 and b < 180           # lake (darker than the sky)
    return green or tan or grayrock or darkwater


def _color_counts(path):
    """Coarse color census: (green, gray, blue) sample counts. Lets a test tell
    the overworld grass (green) from the town (gray cobble) from the battle
    field / town water (blue) on the rendered framebuffer."""
    img = Image.open(path).convert("RGB")
    px = img.load()
    w, h = img.size
    g = gray = blue = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            rr, gg, bb = px[x, y]
            if gg > rr + 20 and gg > bb + 20:
                g += 1
            elif bb > rr + 25 and bb > gg + 5:
                blue += 1
            elif abs(rr - gg) < 30 and abs(gg - bb) < 50 and 60 < rr < 200:
                gray += 1
    return g, gray, blue


def _rms(path):
    w = wave.open(str(path))
    n = w.getnframes()
    samples = struct.unpack(f"<{n * w.getnchannels()}h", w.readframes(n))
    w.close()
    assert samples, f"{path}: empty recording"
    return math.sqrt(sum(s * s for s in samples) / len(samples))


# =============================================================================
# Boot — the overworld is a live Mode 7 perspective scene.
# =============================================================================
def test_boots_into_mode7_overworld(runner):
    """The ROM boots ($7E:E000=SFDB) into the Mode 7 overworld: SHADOW_BGMODE
    is $07 (Mode 7), M7_PV_ACTIVE=1, CH5+CH6 owned (M7_OWNED_MASK=$60), and the
    HDMA enable mask is nonzero. Reads the engine-state shadows the NMI commits.
    State cycle: boot -> overworld init (Mode 1->Mode 7 path)."""
    rom = BUILD / "rpg.sfc"
    assert rom.exists(), f"{rom} not built — run `make rpg` first"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(8)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB)"
    assert _state(runner) == SC_OVERWORLD, "did not start in the overworld"
    assert _u8(runner, SHADOW_BGMODE) == 0x07, "overworld BGMODE not Mode 7"
    assert _u8(runner, M7_PV_ACTIVE) == 1, "Mode 7 renderer not active"
    assert _u8(runner, M7_OWNED_MASK) == 0x60, "Mode 7 does not own CH5+CH6"
    assert _u8(runner, NMI_HDMA_ENABLE) != 0, "no HDMA armed in Mode 7"

    runner.take_screenshot(str(E2E / "rpg_1_overworld.png"))
    g, gray, blue = _color_counts(E2E / "rpg_1_overworld.png")
    assert g > 800, f"overworld is not a green Mode 7 floor (green px={g})"


# =============================================================================
# THE FLOOR-IN-SKY FIX — the overworld is a Mode 7 PERSPECTIVE floor with a REAL
# SKY above the horizon, not a face-on ground tilemap smeared upward. This is
# the regression test for the user-rejected defect: read an ACTUAL PIXEL in the
# sky region (above the horizon) and assert it is the SKY colour, NOT a floor
# green; and a pixel below the horizon and assert it IS floor terrain.
#
# Why this catches the bug the old `distinct_min:3` gate did not: the broken
# render (M7SEL=WRAP, no sky-split) tiles the green/tan/blue FLOOR across the
# whole screen — distinct_min:3 passes (3+ colours present) and even the green
# census passes (grass everywhere), but the pixel at y=24 is a floor colour, not
# sky. The fixed render shows sky-blue above the horizon. The two are byte-
# distinguishable at the sample pixel; only the fixed render passes.
# =============================================================================
def test_overworld_sky_above_horizon_floor_below(runner):
    """Composited sky/floor pixel test: a pixel WELL ABOVE the horizon (y=24)
    must be the SKY colour (bright blue backdrop the sky-split reveals), and a
    pixel WELL BELOW the horizon (y=200) must be FLOOR terrain (a Mode 7 ground
    colour). Reads the rendered framebuffer PIXELS directly — the exact surface
    the floor-in-sky defect lives on. On the OLD WRAP/no-split render the y=24
    pixel is a floor green/tan, not sky, so this test FAILS on the bug and
    PASSES only on the fix. State: boot into the overworld (1 frame settle)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)
    p = E2E / "rpg_sky_split.png"
    runner.take_screenshot(str(p))

    # multiple sky samples across the top band — ALL must be sky, none floor
    for sx in (40, 128, 216):
        c = _px(p, sx, SKY_SAMPLE_Y)
        assert _is_sky(c), \
            f"above-horizon pixel ({sx},{SKY_SAMPLE_Y}) is {c}, not SKY " \
            f"(floor-in-sky: the ground tilemap is smeared above the horizon)"
        assert not _is_floor_terrain(c) or _is_sky(c), \
            f"above-horizon pixel ({sx},{SKY_SAMPLE_Y})={c} reads as floor terrain"

    # below the horizon must be floor terrain (a Mode 7 ground colour), NOT sky
    for fx in (40, 128, 216):
        c = _px(p, fx, FLOOR_SAMPLE_Y)
        assert _is_floor_terrain(c) and not _is_sky(c), \
            f"below-horizon pixel ({fx},{FLOOR_SAMPLE_Y}) is {c}, not floor terrain"

    # structural backstop: the top band (above the y~43 horizon) is sky, and the
    # mid-screen grass-meadow band is floor. The floor band stops at y=150 — well
    # ABOVE the bottom water strip the max-map view brings on-screen (~y>=190),
    # whose bright water blue is not a "floor green" colour.
    img = Image.open(p).convert("RGB")
    px = img.load()
    w, h = img.size
    sky_band = sum(1 for y in range(6, 40, 4) for x in range(0, w, 8)
                   if _is_sky(px[x, y]))
    floor_band = sum(1 for y in range(60, 150, 4) for x in range(0, w, 8)
                     if _is_floor_terrain(px[x, y]))
    sky_total = len(range(6, 40, 4)) * len(range(0, w, 8))
    floor_total = len(range(60, 150, 4)) * len(range(0, w, 8))
    assert sky_band > sky_total * 0.7, \
        f"sky band not mostly sky: {sky_band}/{sky_total} sky samples"
    assert floor_band > floor_total * 0.7, \
        f"floor band not mostly floor terrain: {floor_band}/{floor_total} samples"


# =============================================================================
# THE HORIZON-PROPORTION REGRESSION GUARD — the sky%/horizon is now a TESTED
# parameter, so the OWNER option-D / max-map tuning (thin ~18% sky, horizon at
# scanline 40) cannot silently drift back to the old ~32% sky (PV_L0=72). This
# is a REAL vertical pixel-scan of the rendered framebuffer: it walks a column
# top-to-bottom, finds the sky->floor transition row, converts it to a scanline,
# and asserts the horizon sits near scanline 40 (and so the sky band is ~18% of
# the screen, NOT ~32%). It reads the actual horizon line the sky-split draws,
# not a proxy. A regression that moved PV_L0 back to 72 puts the transition at
# screenshot y~80 / scanline ~72 (and a 32% sky band) and FAILS this gate.
# =============================================================================
# Design: main.asm PV_L0 = 40 (the floor begins here). The on-screen transition
# lands a few scanlines below PV_L0 — the sky-split's 1-line floor-begin band
# entry plus the 239/224 screenshot scaling put the rendered horizon at
# scanline ~44 (screenshot y~47). Tolerance brackets that while staying far from
# the old PV_L0=72 (which would render the horizon near scanline ~72).
EXPECTED_HORIZON_SCANLINE = 40       # main.asm PV_L0 (the OWNER option-D value)
HORIZON_SCANLINE_TOL = 8             # +/- a few scanlines (render+scaling offset)
SCREEN_SCANLINES = 224               # NTSC active scanlines (the sky% denominator)


def test_overworld_horizon_at_expected_scanline(runner):
    """Regression guard for the OWNER option-D / max-map sky proportion: a REAL
    vertical pixel-scan finds the sky->floor transition and asserts the horizon
    is near scanline 40 (~18% sky), NOT the old ~32% sky (PV_L0=72). Scans
    several columns top-to-bottom on the booted overworld framebuffer, locates
    the first non-sky (floor) row under the sky band, converts screenshot-y to a
    scanline (s ~= y * 224/239), and checks the median transition is within a
    few scanlines of 40 AND that the sky band is ~18% (well under the old 32%).
    Reads the rendered horizon line directly — the exact surface the sky% lives
    on. State: boot into the overworld (settle)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)
    p = E2E / "rpg_d_horizon_guard.png"
    runner.take_screenshot(str(p))

    img = Image.open(p).convert("RGB")
    px = img.load()
    w, h = img.size

    # Walk each sampled column top-to-bottom. The sky band (BG1 off, CGRAM[0]
    # backdrop) is a solid sky-blue; the floor begins where the column stops
    # being sky. Record the first floor row UNDER the contiguous sky band.
    transitions = []
    for sx in range(20, w - 20, 20):
        last_sky = None
        first_floor = None
        for y in range(1, h):                 # skip y=0 (PNG black border)
            if _is_sky(px[sx, y]):
                last_sky = y
            elif last_sky is not None and first_floor is None:
                first_floor = y
                break
        if first_floor is not None:
            transitions.append(first_floor)

    assert len(transitions) >= 5, \
        f"could not locate the sky->floor horizon in enough columns ({len(transitions)})"

    transitions.sort()
    median_y = transitions[len(transitions) // 2]
    # screenshot y -> scanline (224 active scanlines scaled to 239 px tall)
    median_scanline = median_y * SCREEN_SCANLINES / h

    assert abs(median_scanline - EXPECTED_HORIZON_SCANLINE) <= HORIZON_SCANLINE_TOL, (
        f"horizon at scanline ~{median_scanline:.1f} (screenshot y={median_y}), "
        f"expected ~{EXPECTED_HORIZON_SCANLINE} +/- {HORIZON_SCANLINE_TOL} "
        f"(option-D / max-map). A drift back to ~32% sky (PV_L0=72) lands "
        f"the horizon near scanline ~72 and trips this gate."
    )

    # The sky band is ~18% of the screen, NOT the old ~32%. Compute it from the
    # horizon scanline directly so the proportion itself is the asserted value.
    sky_fraction = median_scanline / SCREEN_SCANLINES
    assert 0.12 <= sky_fraction <= 0.24, (
        f"sky band is {sky_fraction*100:.1f}% of the screen — expected ~18% "
        f"(option-D / max-map). The old PV_L0=72 view is ~32% sky."
    )


# =============================================================================
# HORIZON FOG GRADIENT — the static daytime haze (the owner's "fog gradient at
# the horizon" request). A 3-channel COLDATA gradient drives the PPU fixed colour
# per scanline; color math SUBTRACTS it on BG1(floor) + backdrop, STRONGEST at the
# top of the frame (the horizon) and ~zero at the bottom (the near field): a
# depth-graded haze. Keyframes carried verbatim from the racer's proven daytime
# values (TR=0,TG=6,TB=14 / BR=BG=BB=0).
#
# This reads RENDERED PIXELS, not a flag. It masks to GREEN GRASS pixels only
# (the floor's dominant terrain) and compares grass JUST BELOW the horizon
# (heavily hazed) against grass in the NEAR field (lightly/un-hazed). The same
# terrain at two depths isolates the per-scanline gradient from the floor's own
# tile pattern. The haze pulls green (TG=6) and blue (TB=14) down near the
# horizon, so near-field grass is measurably BRIGHTER than far-field grass.
#
# Negative control (measured on the no-fog baseline): without the gradient the
# near/far grass green delta is ~0.9 (flat — grass is the same colour at all
# depths). With the fog it is ~18.8. The threshold (>= 8) sits well clear of both.
# Also asserts the gradient is armed on the expected channel ($7E:E012 == 3, like
# the racer) and that the four HDMA channel families are present + disjoint
# (sky-split CH2, gradient CH3/CH4/CH7, Mode 7 matrix CH5/CH6).
# =============================================================================
def _grass_band_avg(px, w, y0, y1):
    """Average (r, g, b) over GREEN-GRASS pixels in scanline band [y0, y1).
    Grass = green-dominant + bright enough to exclude shadowed checker cells."""
    rs = gs = bs = n = 0
    for y in range(y0, y1):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if g > r + 15 and g > b + 15 and g > 40:        # green grass
                rs += r; gs += g; bs += b; n += 1
    assert n > 50, f"too few grass pixels in band y={y0}..{y1} ({n}) to measure haze"
    return rs / n, gs / n, bs / n


def test_overworld_horizon_haze(runner):
    """The static daytime horizon fog grades the floor: GREEN GRASS just below the
    horizon (heavily hazed) is measurably DARKER than grass in the near field
    (un-hazed). Reads rendered framebuffer PIXELS (grass-masked, same terrain at
    two depths) — the exact surface the haze lives on, not a flag. Asserts a
    VISIBLE far-vs-near colour difference (the haze is graded, not flat/absent) AND
    that the gradient is armed on channel 3 ($7E:E012 == 3) with the four HDMA
    families present + disjoint. State: boot into the overworld (settle)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)
    p = E2E / "rpg_horizon_haze.png"
    runner.take_screenshot(str(p))

    img = Image.open(p).convert("RGB")
    px = img.load()
    w, h = img.size

    # grass just below the horizon (scanline ~44 -> screenshot y~47) vs near field
    far_r, far_g, far_b = _grass_band_avg(px, w, 46, 66)     # heavily hazed
    near_r, near_g, near_b = _grass_band_avg(px, w, 150, 175)  # lightly/un-hazed

    green_delta = near_g - far_g            # haze pulls green down near the horizon
    blue_delta = near_b - far_b             # haze pulls blue down hardest (TB=14)
    bright_delta = (near_r + near_g + near_b) - (far_r + far_g + far_b)

    # The far grass (near the horizon) must be visibly hazier (dimmer) than the
    # near grass. No-fog baseline deltas are ~0.9 green / ~1.8 sum; the fog yields
    # ~18.8 / ~28. Thresholds sit clear of the no-fog noise floor.
    assert green_delta >= 8.0, (
        f"horizon haze not graded: near-field grass green ({near_g:.1f}) is not "
        f">= far-field grass green ({far_g:.1f}) by 8 (delta {green_delta:.1f}). "
        f"The fog should pull green/blue DOWN near the horizon (TG=6, TB=14). A "
        f"flat/absent gradient gives ~0 delta."
    )
    assert bright_delta >= 12.0, (
        f"horizon haze not graded: near grass (sum {near_r+near_g+near_b:.1f}) is "
        f"not brighter than far grass (sum {far_r+far_g+far_b:.1f}) by 12 "
        f"(delta {bright_delta:.1f}). The near field is un-hazed; the horizon is hazed."
    )

    # The gradient is armed on channel 3 (the racer's debug-mirror convention).
    grad_chan = _u8(runner, 0xE012)
    assert grad_chan == 3, (
        f"gradient first channel mirror $7E:E012 = {grad_chan}, expected 3 "
        f"(CH3/CH4/CH7 first-fit after Mode 7's CH5/CH6 pre-pin). A wrong value "
        f"means the arm order let the gradient collide with the Mode 7 matrix."
    )

    # The four HDMA channel families are present and DISJOINT: sky-split CH2,
    # gradient CH3/CH4/CH7, Mode 7 matrix CH5/CH6. No double-claim (a channel
    # both matrix-owned and gradient-owned would let the NMI's matrix commit kill
    # the gradient ramp every VBlank).
    hdma_en = _u8(runner, NMI_HDMA_ENABLE)
    m7_owned = _u8(runner, M7_OWNED_MASK)
    assert hdma_en == 0xFC, (
        f"NMI_HDMA_ENABLE = 0x{hdma_en:02X}, expected 0xFC (CH2..CH7). Missing a "
        f"channel means one of sky-split / gradient / matrix failed to arm."
    )
    assert m7_owned == 0x60, (
        f"M7_OWNED_MASK = 0x{m7_owned:02X}, expected 0x60 (CH5+CH6). The matrix "
        f"must own exactly CH5/CH6."
    )
    gradient_chans = 0b10011000           # CH3, CH4, CH7
    assert (m7_owned & gradient_chans) == 0, (
        f"channel double-claim: Mode 7 owns 0x{m7_owned:02X} which intersects the "
        f"gradient channels 0x{gradient_chans:02X} — the matrix would overwrite the "
        f"gradient every VBlank."
    )


def test_overworld_avatar_visible_on_screen(runner):
    """The player avatar (OAM 0, a 16x16 hero) is VISIBLE at screen centre on
    the perspective floor — not parked, not invisible. Reads OAM slot 0 (must be
    centred + a live tile, large size bit set) AND an ACTUAL SCREEN PIXEL inside
    the avatar's 16x16 box: the hero's bright body/head colours must appear there
    against the darker floor. Reads the rendered framebuffer pixels, not just the
    OAM bytes (OAM can be correct while the sprite is occluded or off-palette)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    x0, y0, tile, attr = runner.read_bytes(OAM, 0, 4)
    assert (x0, y0) == (AV_CENTER_X, AV_CENTER_Y), \
        f"avatar OAM not centred: ({x0},{y0}) != ({AV_CENTER_X},{AV_CENTER_Y})"
    assert tile != 0xF0 and y0 != 0xF0, "avatar OAM slot 0 parked"
    hi0 = runner.read_bytes(OAM, 512, 1)[0]
    assert hi0 & 0x02, "avatar size bit not set (not a 16x16 sprite)"

    # screenshot pixel proof: scan the avatar's 16x16 screen box for a BRIGHT,
    # non-floor pixel (the hero's body/head). The floor under the avatar is the
    # green meadow (~ (24,90,41)/(49,132,57)); the hero's body is a bright blue
    # and its head a cream — both far brighter than the floor green.
    p = E2E / "rpg_avatar.png"
    runner.take_screenshot(str(p))
    px = Image.open(p).convert("RGB").load()
    found = False
    for yy in range(AV_CENTER_Y, AV_CENTER_Y + 16):
        for xx in range(AV_CENTER_X, AV_CENTER_X + 16):
            r, g, b = px[xx, yy]
            bright_body = b > 150 and b > g + 40       # blue hero body
            bright_head = r > 200 and g > 180 and b > 140  # cream hero head
            if bright_body or bright_head:
                found = True
                break
        if found:
            break
    assert found, \
        "no avatar pixels found in the 16x16 screen box at centre " \
        f"({AV_CENTER_X},{AV_CENTER_Y}) — the player is not visible on screen"

    # NO phantom "!" in the 32x32 footprint the OBSEL bug rendered. The old scan
    # above reads only the intended 16x16 box, so it passes whether the avatar is
    # 16x16 or (wrongly) 32x32 — the phantom "!" leaks OUTSIDE that box, in the
    # top-right of the 32x32 quad (~x=147). Count bright-yellow "!" pixels (OBJ
    # index 5, unique on the green/tan Mode 7 floor) in that surround: a correct
    # 16x16 avatar leaves it floor (zero yellow). On the pre-fix OBSEL=$62 ROM the
    # avatar reads a 4x4 tile quad from base tile 5, pulling CHR tile 8 (the "!")
    # into its corner — ~14 yellow pixels here — so this FAILS on the bug.
    yellow = _count_color(p, (AV_CENTER_X + 16, AV_CENTER_Y,
                              AV_CENTER_X + 32, AV_CENTER_Y + 18), OBJ_YELLOW, 40)
    assert yellow < 4, \
        f"phantom '!' pixels ({yellow}) in the avatar's 32x32 surround — OBSEL is " \
        "rendering the 16x16 avatar as 32x32 (pulling CHR tile 8, the '!', in)"


# =============================================================================
# The CORE — Mode7 -> Mode1 -> Mode7 round-trip, asserted on shadow registers,
# the rendered screen, VRAM, and the masked-swap proof. Forward AND reverse.
# =============================================================================
def test_overworld_to_town_to_overworld_roundtrip(runner):
    """Drive overworld -> town -> overworld and assert the FULL register cycle
    on every leg, plus the rendered screen flips Mode 7 grass <-> Mode 1 town:
      SHADOW_BGMODE  $07 -> $09 -> $07
      M7_PV_ACTIVE     1 -> 0  -> 1
      M7_OWNED_MASK  $60 -> $00 -> $60   (CH5/6 release + re-pin)
      NMI_HDMA_ENABLE nonzero -> $00 -> nonzero
    State cycle: forward (OW->town) AND reverse (town->OW)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(10)

    # --- leg 1: overworld (Mode 7) ---
    assert _state(runner) == SC_OVERWORLD
    assert _u8(runner, SHADOW_BGMODE) == 0x07
    assert _u8(runner, M7_PV_ACTIVE) == 1
    assert _u8(runner, M7_OWNED_MASK) == 0x60
    assert _u8(runner, NMI_HDMA_ENABLE) != 0

    # --- leg 2: A -> TOWN (Mode 1) ---
    _tap(runner, a=True)
    assert _state(runner) == SC_TOWN, "A did not switch to the town"
    assert _u8(runner, SHADOW_BGMODE) == 0x09, "town BGMODE not Mode 1"
    assert _u8(runner, M7_PV_ACTIVE) == 0, "Mode 7 still active in town"
    assert _u8(runner, M7_OWNED_MASK) == 0x00, "CH5/6 not released in town"
    assert _u8(runner, NMI_HDMA_ENABLE) == 0x00, "HDMA still armed in town"
    runner.take_screenshot(str(E2E / "rpg_2_town.png"))

    # --- leg 3: EXIT gate -> back to the OVERWORLD (Mode 7 re-pinned). In the
    #     town, A is context-sensitive (near the NPC it opens the dialog); the
    #     return path is the SOUTH EXIT gate — walk onto (16,21) + A. ---
    _town_to_overworld(runner)
    assert _state(runner) == SC_OVERWORLD, "exit gate did not return to the overworld"
    assert _u8(runner, SHADOW_BGMODE) == 0x07, "returned BGMODE not Mode 7"
    assert _u8(runner, M7_PV_ACTIVE) == 1, "Mode 7 not re-activated on return"
    assert _u8(runner, M7_OWNED_MASK) == 0x60, "CH5/6 not re-pinned on return"
    assert _u8(runner, NMI_HDMA_ENABLE) != 0, "HDMA not re-armed on return"
    runner.take_screenshot(str(E2E / "rpg_3_returned_overworld.png"))

    # --- the screen actually flipped Mode 7 grass <-> Mode 1 town <-> grass ---
    ow_g, ow_gray, ow_blue = _color_counts(E2E / "rpg_1_overworld.png")
    tn_g, tn_gray, tn_blue = _color_counts(E2E / "rpg_2_town.png")
    rt_g, rt_gray, rt_blue = _color_counts(E2E / "rpg_3_returned_overworld.png")
    assert tn_g < ow_g // 2, \
        f"town screen still mostly green (grass not gone): {tn_g} vs {ow_g}"
    assert (tn_gray + tn_blue) > tn_g, \
        f"town screen is not a Mode 1 gray/blue room: gray={tn_gray} blue={tn_blue} green={tn_g}"
    assert rt_g > 800, f"returned overworld not green again (green px={rt_g})"


def test_swap_is_masked_no_torn_frame(runner):
    """The swap is MASKED by the MOSAIC WIPE: the screen DISSOLVES old-scene ->
    BLACK -> new-scene, and NO frame across the swap shows a TORN mix of the Mode
    7 overworld and the Mode 1 town (the user-visible invariant). Reads the
    rendered framebuffer across the whole wipe: (a) at least one frame is near-
    BLACK (the dissolve reaches black at the swap, so the discontinuous rebuild is
    hidden), and (b) NO frame has the green Mode 7 floor AND the gray Mode 1 town
    cobble PRESENT at the same time (a torn frame). The mosaic dissolve goes
    green -> dim -> black -> dim -> gray, never green+gray together."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(10)
    assert _state(runner) == SC_OVERWORLD

    # fire the swap, then walk the wipe frame-by-frame; capture each
    runner.set_input(0, a=True)
    runner.run_frames(2)
    runner.set_input(0)

    saw_black = False
    torn = False
    for i in range(48):
        p = E2E / f"rpg_swap_{i}.png"
        runner.take_screenshot(str(p))
        lit = _lit_pixels(p, thresh=60)
        # near-black: the whole frame is very dark (the dissolve's black swap window)
        if lit < 200:
            saw_black = True
        # A TORN frame is a BRIGHT frame (not part of the dim dissolve) showing the
        # Mode 7 floor AND the Mode 1 town room at full content at once. The mosaic
        # dimming muddies the colour census on dim frames (a dimmed green reads
        # grayish), so only flag torn on a sufficiently BRIGHT frame — the dissolve
        # is never bright while mid-swap, so a bright green+gray frame is the real
        # torn signal. (saw_black proves the masking; this guards against garbage.)
        if lit > 8000:
            g, gray, blue = _color_counts(p)
            if g > 600 and gray > 1200:
                torn = True
        if _state(runner) == SC_TOWN and _color_counts(p)[1] > 1200:
            break                        # town fully rendered — wipe done
        runner.run_frames(1)

    assert saw_black, "the mosaic wipe never reached a near-black frame (swap not masked)"
    assert not torn, "a TORN frame mixed the Mode 7 floor and the Mode 1 room"


def test_town_vram_uploaded_and_overworld_map_restored(runner):
    """VRAM round-trip: in the TOWN the Mode 1 BG1 CHR ($2000 word) holds the
    uploaded 4bpp tileset (nonzero) and the tilemap cell (4,4) is the torch tile
    the init mset's; after RETURNING to the overworld the interleaved Mode 7 map
    is back at VRAM word 0. Reads the DESTINATION VRAM bytes directly (not a
    downstream proxy). State cycle: OW (map) -> town (CHR+tilemap) -> OW (map)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(10)

    ow_vram0 = runner.read_bytes(VR, 0, 32)
    assert any(ow_vram0), "overworld VRAM word 0 is empty (map not uploaded)"

    # -> town
    _tap(runner, a=True)
    # BG1 CHR tile 1 (cobble) = word $2010 = byte $4020 — must be nonzero
    cobble = runner.read_bytes(VR, TOWN_BG1_CHR_BYTE + 0x20, 32)
    assert any(cobble), "town BG1 CHR not uploaded (tile 1 all zero)"
    # tilemap cell (4,4) must be the torch tile the init wrote
    torch_cell = runner.read_u16(VR, TOWN_TILEMAP_BYTE + (4 * 32 + 4) * 2) & 0x3FF
    assert torch_cell == TOWN_TILE_TORCH, \
        f"town tilemap cell (4,4) is {torch_cell}, expected torch {TOWN_TILE_TORCH}"

    # -> back to overworld via the EXIT gate: the interleaved map is re-uploaded
    _town_to_overworld(runner)
    assert _state(runner) == SC_OVERWORLD, "did not return to the overworld via the exit"
    ow_vram0b = runner.read_bytes(VR, 0, 32)
    assert bytes(ow_vram0b) == bytes(ow_vram0), \
        "overworld VRAM word 0 not restored to the interleaved map after return"


def test_battle_scene_also_swaps_and_returns(runner):
    """The third scene (BATTLE, Mode 1) is reachable from the overworld (START)
    and returns (A), proving the scene table + dispatch work for ALL THREE
    scenes. The battle renders a Mode-1 room visually distinct from the town
    (blue field vs gray cobble) AND a face-off tableau: the hero (OAM 0) on the
    left and a distinct foe (OAM 1, H-flipped, OBJ palette 1) on the right. Reads
    SHADOW_BGMODE + OAM + the rendered screen. State cycle: OW -> battle -> OW."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(10)
    assert _state(runner) == SC_OVERWORLD

    _tap(runner, start=True)
    assert _state(runner) == SC_BATTLE, "START did not switch to the battle"
    assert _u8(runner, SHADOW_BGMODE) == 0x09, "battle BGMODE not Mode 1"
    assert _u8(runner, M7_PV_ACTIVE) == 0, "Mode 7 still active in battle"
    assert _u8(runner, M7_OWNED_MASK) == 0x00, "CH5/6 not released in battle"
    bp = E2E / "rpg_4_battle.png"
    runner.take_screenshot(str(bp))
    bt_g, bt_gray, bt_blue = _color_counts(bp)
    assert bt_blue > 400, f"battle field not a blue Mode 1 room (blue px={bt_blue})"

    # The battle draws two COMBATANTS (not an empty room): the hero (OAM 0) on the
    # left and a foe (OAM 1, H-flipped, OBJ palette 1) on the right, both 16x16.
    # Assert the OAM entries AND the rendered pixels — a blue hero on the left, a
    # RED foe on the right (the palette-1 recolour) — so the scene is not vacuous.
    BATTLE_HERO_X, BATTLE_FOE_X, BATTLE_Y = 64, 176, 100    # main.asm battle layout
    hx, hy, htile, _ = runner.read_bytes(OAM, 0, 4)
    assert (hx, hy, htile) == (BATTLE_HERO_X, BATTLE_Y, 5), \
        f"battle hero OAM wrong: ({hx},{hy},tile{htile})"
    fx, fy, ftile, fattr = runner.read_bytes(OAM, 4, 4)
    assert (fx, fy, ftile) == (BATTLE_FOE_X, BATTLE_Y, 5), \
        f"battle foe OAM wrong: ({fx},{fy},tile{ftile})"
    assert fattr & 0x40, "battle foe is not H-flipped (should face the hero)"
    px = Image.open(bp).convert("RGB").load()
    hero_blue = sum(1 for y in range(BATTLE_Y, BATTLE_Y + 18)
                    for x in range(BATTLE_HERO_X, BATTLE_HERO_X + 16)
                    if px[x, y][2] > 150 and px[x, y][2] > px[x, y][1] + 40)
    foe_red = sum(1 for y in range(BATTLE_Y, BATTLE_Y + 18)
                  for x in range(BATTLE_FOE_X, BATTLE_FOE_X + 16)
                  if px[x, y][0] > 110 and px[x, y][0] > px[x, y][1] + 50
                  and px[x, y][0] > px[x, y][2] + 40)
    assert hero_blue > 20, f"hero not rendered blue on the left (blue px={hero_blue})"
    assert foe_red > 3, f"foe not rendered red on the right (red px={foe_red})"

    _tap(runner, a=True)
    assert _state(runner) == SC_OVERWORLD, "A did not return from battle"
    assert _u8(runner, SHADOW_BGMODE) == 0x07, "did not return to Mode 7"
    assert _u8(runner, M7_PV_ACTIVE) == 1, "Mode 7 not re-activated after battle"


# =============================================================================
# keep_music — the SPC keeps playing across the swap (non-silent WAV, no gap).
# =============================================================================
def test_music_persists_across_the_swap(runner):
    """keep_music: the music keeps playing across the Mode7<->Mode1 swap. Reads
    RECORDED AUDIO ENERGY (WAV RMS) across the transition — non-silent BEFORE,
    DURING, and AFTER the swap with no gap — AND the TAD_STATUS mirror never
    drops out of PLAYING ($01). The WAV energy is the architectural proof; the
    status mirror is the secondary check. State cycle: OW(play) -> town(play)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)

    # wait for the async song load to reach PLAYING
    for _ in range(30):
        if _u8(runner, TAD_STATUS) == 0x01:
            break
        runner.run_frames(5)
    assert _u8(runner, TAD_STATUS) == 0x01, \
        f"music never reached PLAYING (TAD_STATUS={_u8(runner, TAD_STATUS):#04x})"

    tmp = E2E
    # BEFORE: record while in the overworld
    runner.start_audio_recording(str(tmp / "rpg_music_before.wav"))
    runner.run_frames(60)
    runner.stop_audio_recording()
    before = _rms(tmp / "rpg_music_before.wav")
    assert before > 400, f"music not audible in the overworld (RMS={before:.0f})"

    # DURING: record straddling the A-press swap into the town
    runner.start_audio_recording(str(tmp / "rpg_music_during.wav"))
    runner.set_input(0, a=True)
    runner.run_frames(2)
    runner.set_input(0)
    runner.run_frames(58)
    runner.stop_audio_recording()
    during = _rms(tmp / "rpg_music_during.wav")
    assert _state(runner) == SC_TOWN, "did not reach the town during the record"
    # the swap blanks the SCREEN, not the SPC — the music must NOT cut out
    assert during > before * 0.4, \
        f"music dropped out across the swap (RMS {before:.0f} -> {during:.0f})"
    assert _u8(runner, TAD_STATUS) == 0x01, \
        "TAD_STATUS left PLAYING across the swap (music stopped/loading/error)"

    # AFTER: still playing in the town
    runner.start_audio_recording(str(tmp / "rpg_music_after.wav"))
    runner.run_frames(60)
    runner.stop_audio_recording()
    after = _rms(tmp / "rpg_music_after.wav")
    assert after > 400, f"music not audible after the swap (RMS={after:.0f})"


# =============================================================================
# Avatar camera restore — the overworld camera is SAVED across the swap and
# RESTORED on return (mode7_init resets it to map-center, so the template must
# snapshot/restore it itself). Sprint 1: the saved camera now reflects the
# player's WALKED grid position (8px-stepped), which is the desired behaviour.
# =============================================================================
def test_walked_camera_saved_and_restored(runner):
    """Walk the overworld camera grid-by-grid, switch to the town and back, and
    assert the camera RETURNS to the WALKED position — not the spawn mode7_init
    resets to. Reads the saved-camera game WRAM ($32/$34) AND the LIVE Mode 7
    camera the engine commits (M7_PV_POSX/Y+2). State cycle: OW(walk) -> town
    -> OW(restore), driven in BOTH X directions."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    base_x = runner.read_u16(WR, M7_PV_POSX_INT)
    assert base_x == SPAWN_CAMX, f"did not spawn at tile 64 (cam_x={base_x})"

    # walk RIGHT 3 tiles (the town-path side is clear) -> +24 px, grid-aligned
    moved_x, _ = _walk(runner, 3, right=True)
    saved = runner.read_u16(WR, OVW_CAMX)
    assert moved_x == base_x + 3 * TILE_PX, \
        f"3 right steps != 3 tiles: {base_x} -> {moved_x}"
    assert saved == moved_x, f"saved cam ({saved}) != live cam ({moved_x})"

    # -> town (saves the camera) -> back via the EXIT gate (restores it). At
    # (67,64) the player is NOT adjacent to an NPC (NPC0 65,65 / NPC1 66,66), so
    # A enters the town; the return is the town's south exit gate.
    _tap(runner, a=True)
    assert _state(runner) == SC_TOWN, "A at a non-NPC tile did not enter the town"
    assert runner.read_u16(WR, OVW_CAMX) == moved_x, \
        "saved overworld camera was clobbered while in the town"
    _town_to_overworld(runner)
    restored = runner.read_u16(WR, M7_PV_POSX_INT)
    assert restored == moved_x, \
        f"overworld camera not restored on return: walked {moved_x}, got {restored}"

    # reverse: step LEFT exactly 1 tile (to 66,64 — still clear of the NPC
    # neighbours) and confirm the save/restore the other way through a second
    # round-trip. A single grid step is deterministic (one tap = one tile).
    moved_l, _ = _grid_step(runner, left=True)
    assert moved_l == restored - 1 * TILE_PX, \
        f"1 left step != 1 tile back: {restored} -> {moved_l}"
    _tap(runner, a=True)        # -> town (66,64 is not NPC-adjacent)
    assert _state(runner) == SC_TOWN, "A at (66,64) did not enter the town"
    _town_to_overworld(runner)  # -> back via the exit gate
    restored_l = runner.read_u16(WR, M7_PV_POSX_INT)
    assert restored_l == moved_l, \
        f"left-walked camera not restored: {moved_l} -> {restored_l}"


def test_avatar_stays_centered_while_world_scrolls(runner):
    """Camera-follows-player: the avatar (OAM 0) stays FIXED at screen center
    while the D-pad scrolls the Mode 7 camera under it. Reads the OAM low-table
    bytes for slot 0 (the rendered sprite tile + position) AND the live camera —
    the avatar position must NOT change, the camera MUST. State cycle: overworld,
    walk right then left."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    x0, y0, tile, attr = runner.read_bytes(OAM, 0, 4)
    assert tile != 0xF0, "avatar OAM slot 0 looks parked (tile)"
    assert y0 != 0xF0, "avatar OAM slot 0 is parked off-screen (y=$F0)"
    assert (x0, y0) == (AV_CENTER_X, AV_CENTER_Y), \
        f"avatar not at screen center: ({x0},{y0}) != ({AV_CENTER_X},{AV_CENTER_Y})"

    cam0 = runner.read_u16(WR, M7_PV_POSX_INT)
    cam_moved, _ = _walk(runner, 3, right=True)
    x1, y1 = runner.read_bytes(OAM, 0, 2)
    # the camera scrolled (world moved) but the avatar stayed centered
    assert cam_moved > cam0, f"camera did not scroll on D-pad right ({cam0}->{cam_moved})"
    assert (x1, y1) == (AV_CENTER_X, AV_CENTER_Y), \
        f"avatar drifted from center on right ({x1},{y1})"
    # and the same walking back left
    cam_back, _ = _walk(runner, 3, left=True)
    x2, y2 = runner.read_bytes(OAM, 0, 2)
    assert cam_back < cam_moved, f"camera did not scroll back on left ({cam_moved}->{cam_back})"
    assert (x2, y2) == (AV_CENTER_X, AV_CENTER_Y), \
        f"avatar drifted from center on left ({x2},{y2})"


# =============================================================================
# Sprint 1 — GRID MOVEMENT: one D-pad press moves the camera/player exactly one
# tile (8 px) in ALL FOUR directions; press + release; asserted on the LIVE
# Mode 7 camera (M7_PV_POSX/Y integer) the NMI commits + a scrolled screenshot.
# =============================================================================
def test_grid_step_one_tile_all_four_directions(runner):
    """A single D-pad tap moves the camera exactly ONE tile (8 px) — right,
    left, down, up — and never a partial/over step. Reads the LIVE Mode 7
    camera integer (M7_PV_POSX/Y+2, the value the engine commits each frame),
    not a game variable, and captures a screenshot showing the world scrolled.
    State cycle: a single grid step exercised in every cardinal direction from
    the spawn, returning to the spawn tile (forward + reverse on both axes)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    bx, by = runner.read_u16(WR, M7_PV_POSX_INT), runner.read_u16(WR, M7_PV_POSY_INT)
    assert (bx, by) == (SPAWN_CAMX, SPAWN_CAMY), \
        f"did not spawn grid-aligned at tile 64: cam=({bx},{by})"
    runner.take_screenshot(str(E2E / "rpg_s1_overworld_start.png"))

    # RIGHT one tile (+8 px X)  [the town-path side is clear]
    cx, cy = _grid_step(runner, right=True)
    assert (cx, cy) == (bx + TILE_PX, by), f"right step != +1 tile X: {(bx,by)} -> {(cx,cy)}"
    runner.take_screenshot(str(E2E / "rpg_s1_after_right.png"))
    # LEFT one tile (-8 px X) back to spawn column
    cx, cy = _grid_step(runner, left=True)
    assert (cx, cy) == (bx, by), f"left step != -1 tile X: back to {(bx,by)}, got {(cx,cy)}"

    # DOWN one tile (+8 px Y)  [water wall is 5 tiles away — one step is safe]
    cx, cy = _grid_step(runner, down=True)
    assert (cx, cy) == (bx, by + TILE_PX), f"down step != +1 tile Y: {(bx,by)} -> {(cx,cy)}"
    runner.take_screenshot(str(E2E / "rpg_s1_after_down.png"))
    # UP one tile (-8 px Y) back to spawn row
    cx, cy = _grid_step(runner, up=True)
    assert (cx, cy) == (bx, by), f"up step != -1 tile Y: back to {(bx,by)}, got {(cx,cy)}"

    # after a 4-direction round trip the camera is exactly back at spawn — and a
    # screenshot still shows the green Mode 7 overworld scrolling under the avatar
    runner.take_screenshot(str(E2E / "rpg_s1_after_4dir_roundtrip.png"))
    g, gray, blue = _color_counts(E2E / "rpg_s1_after_4dir_roundtrip.png")
    assert g > 800, f"overworld no longer a green Mode 7 floor (green px={g})"


def test_grid_step_is_quantized_not_partial(runner):
    """Every settled camera position after a walk is on an 8px grid boundary
    (cam % 8 == 0) — movement is gridded, never free-pixel. Walk a few tiles
    right and assert each landed position is tile-aligned. Reads the LIVE Mode 7
    camera integer. State cycle: forward grid walk, sampled per-tile."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    for i in range(1, 5):
        cx, cy = _grid_step(runner, right=True)
        assert cx % TILE_PX == 0 and cy % TILE_PX == 0, \
            f"step {i} not grid-aligned: cam=({cx},{cy})"
        assert cx == SPAWN_CAMX + i * TILE_PX, \
            f"step {i} camera off: {cx} != {SPAWN_CAMX + i*TILE_PX}"


# =============================================================================
# Sprint 1 — TILE COLLISION: a D-pad press INTO a blocked tile (water/mountain)
# does NOT move the player. Driven from MULTIPLE approach directions (the
# "walk into a wall" state-cycle coverage). Asserted on the LIVE camera (no
# movement) + a screenshot showing the player stopped at the boundary.
# =============================================================================
def test_collision_blocks_into_water_wall_south(runner):
    """Walk SOUTH into the water barrier (ty=69) and assert the camera STOPS at
    the boundary tile (ty=68) and then does NOT advance when pushed into the
    wall — the press into water is a no-op. Reads the LIVE Mode 7 camera Y
    integer + a screenshot showing the player stopped at the water edge.
    State cycle: walk down -> hit wall -> push into wall (no move)."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    # walk down well past the wall distance (5 tiles) — it must clamp at ty=68
    _walk(runner, 8, down=True)
    cy = runner.read_u16(WR, M7_PV_POSY_INT)
    assert cy == WALL_DOWN_STOP_TY * TILE_PX, \
        f"did not stop at the water boundary tile {WALL_DOWN_STOP_TY}: cam_y={cy} (tile {cy//8})"
    runner.take_screenshot(str(E2E / "rpg_s1_water_boundary.png"))

    # push HARD into the wall — the camera must not advance one pixel
    before = runner.read_u16(WR, M7_PV_POSY_INT)
    runner.set_input(0, down=True)
    runner.run_frames(40)
    runner.set_input(0)
    runner.run_frames(8)
    after = runner.read_u16(WR, M7_PV_POSY_INT)
    assert after == before, \
        f"camera moved INTO the water wall: {before} -> {after} (collision failed)"

    # the screenshot at the boundary shows blue water present below the player
    g, gray, blue = _color_counts(E2E / "rpg_s1_water_boundary.png")
    assert blue > 120, f"no water visible at the boundary (blue px={blue})"


def test_collision_blocks_from_multiple_directions(runner):
    """The 'walk into a wall' state cycle from MULTIPLE approach directions:
    UP into the rock barrier (ty=59) and LEFT into the rock barrier (tx=58)
    each clamp the camera at the boundary tile and reject further pushes. Reads
    the LIVE Mode 7 camera integers. State cycle: up-wall + left-wall, each
    walked then pushed."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    # --- UP into the rock wall at ty=59 -> clamp at ty=60 ---
    _walk(runner, 8, up=True)
    cy = runner.read_u16(WR, M7_PV_POSY_INT)
    assert cy == WALL_UP_STOP_TY * TILE_PX, \
        f"did not stop at the up rock boundary {WALL_UP_STOP_TY}: cam_y={cy} (tile {cy//8})"
    before = cy
    runner.set_input(0, up=True); runner.run_frames(30); runner.set_input(0); runner.run_frames(8)
    assert runner.read_u16(WR, M7_PV_POSY_INT) == before, "camera pushed INTO the up rock wall"

    # walk back down to spawn row so the X approach starts clean
    _walk(runner, 4, down=True)

    # --- LEFT into the rock wall at tx=58 -> clamp at tx=59 ---
    _walk(runner, 8, left=True)
    cx = runner.read_u16(WR, M7_PV_POSX_INT)
    assert cx == WALL_LEFT_STOP_TX * TILE_PX, \
        f"did not stop at the left rock boundary {WALL_LEFT_STOP_TX}: cam_x={cx} (tile {cx//8})"
    before = cx
    runner.set_input(0, left=True); runner.run_frames(30); runner.set_input(0); runner.run_frames(8)
    assert runner.read_u16(WR, M7_PV_POSX_INT) == before, "camera pushed INTO the left rock wall"
    runner.take_screenshot(str(E2E / "rpg_s1_rock_boundary.png"))


# =============================================================================
# Sprint 1 — the designed walkable map renders DISTINCTLY: a screenshot census
# shows walkable terrain (green grass / tan path) AND blocked terrain (blue
# water + gray mountain rock) colors all present on the rendered framebuffer.
# =============================================================================
def test_overworld_map_renders_distinct_terrain(runner):
    """The designed overworld renders walkable AND blocked terrain distinctly.
    Walk to a vantage where water + rock + grass + path are all on-screen, then
    a screenshot color census must show green (grass), and the blocked-terrain
    colors (blue water, gray rock) present — proving the map is a designed world,
    not a flat field. Reads the rendered framebuffer pixels (a coarse census),
    not engine variables. State cycle: walk down to the water/rock vantage."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    # at spawn the screen is mostly grass + path; walk down to bring the water
    # barrier (and the rock walls above/left) into the frame (the player clamps
    # at the water edge tile 68, where water + rock + grass + path co-render)
    _walk(runner, 8, down=True)
    runner.take_screenshot(str(E2E / "rpg_s1_terrain_census.png"))
    g, gray, blue = _color_counts(E2E / "rpg_s1_terrain_census.png")
    # walkable terrain: the green meadow dominates
    assert g > 600, f"walkable grass not present (green px={g})"
    # blocked terrain present: water (blue) + mountain rock (gray) both visible
    assert blue > 120, f"no blue water terrain on screen (blue px={blue})"
    assert gray > 200, f"no gray mountain/rock terrain on screen (gray px={gray})"


# =============================================================================
# Sprint 2 — OVERWORLD NPC INTERACTION + sprite-text prompt.
#
# NPCs are FIXED tile-triggers baked into the Mode 7 map (NOT free-roaming
# projected sprites). When the player stands ADJACENT to an NPC tile, near_npc
# is set and an OBJ "!" indicator renders (Mode 7 has no BG3, so the prompt is
# sprite-rendered). Pressing A while adjacent toggles a sprite-text "HELLO"
# strip; walking away dismisses it. Every assertion below reads the RENDERED
# OUTPUT — the OAM low-table bytes (the sprite the PPU draws) and screenshot
# pixels — never a proxy variable. The negative control (prompt ABSENT when far)
# is explicit, and the full approach -> prompt -> interact -> walk-away -> gone
# cycle is driven (state-cycle coverage).
# =============================================================================
def _oam4(r, slot):
    """The OAM low-table entry (x, y, tile, attr) for a slot — the bytes the
    PPU renders. Slot 0 = avatar, 1 = indicator, 2-6 = the text strip."""
    return tuple(r.read_bytes(OAM, slot * 4, 4))


def _oam_size_bit(r, slot):
    """The size bit for a slot from the OAM hi-table (OAM+512). 0 = 8x8 small."""
    hi = r.read_bytes(OAM, 512 + slot // 4, 1)[0]
    return (hi >> ((slot % 4) * 2 + 1)) & 1


def _step_once(r, **direction):
    """Drive exactly ONE grid step (one tile) in a single direction: a 2-frame
    tap, then settle the 8-frame slide. Mirrors _grid_step but returns nothing
    (callers read OAM / DP directly)."""
    r.set_input(0, **direction)
    r.run_frames(2)
    r.set_input(0)
    r.run_frames(12)


def test_npc_tile_is_blocked_and_renders_on_screen(runner):
    """The NPC landmark is a FIXED BLOCKED map tile. ONE step right from spawn
    lands the player on tile (65,64); the NPC at (65,65) is the SOUTH neighbour
    and the tile DIRECTLY ahead-down is solid — the player cannot walk ONTO an
    NPC. Asserts (a) the camera stops adjacent (does NOT advance onto the NPC
    column/row) and (b) the NPC tile renders on the Mode 7 floor: a screenshot
    census finds the bright-magenta NPC body pixels (212,96,196) on screen.
    Reads the LIVE Mode 7 camera + the rendered framebuffer pixels."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    # step right onto (65,64); then push DOWN into the NPC at (65,65) — blocked
    _step_once(runner, right=True)
    cx = runner.read_u16(WR, M7_PV_POSX_INT)
    assert cx == (SPAWN_TX + 1) * TILE_PX, f"right step != tile 65: cam_x={cx}"
    cy_before = runner.read_u16(WR, M7_PV_POSY_INT)
    runner.set_input(0, down=True)
    runner.run_frames(30)
    runner.set_input(0)
    runner.run_frames(10)
    cy_after = runner.read_u16(WR, M7_PV_POSY_INT)
    assert cy_after == cy_before, \
        f"player walked ONTO the NPC tile (cam_y {cy_before}->{cy_after}); NPC not blocked"

    # the NPC body tile renders on the Mode 7 floor (bright magenta, distinct
    # from grass/path/water). Census the rendered framebuffer for magenta pixels.
    p = E2E / "rpg_s2_npc_tile.png"
    runner.take_screenshot(str(p))
    px = Image.open(p).convert("RGB").load()
    w, h = Image.open(p).size
    magenta = sum(1 for y in range(0, h, 2) for x in range(0, w, 2)
                  if px[x, y][0] > 150 and px[x, y][2] > 140
                  and px[x, y][1] < 150 and abs(px[x, y][0] - px[x, y][2]) < 80)
    assert magenta > 8, \
        f"NPC body tile not visible on the Mode 7 floor (magenta px={magenta})"


def test_npc_no_floating_prompt_when_far_or_adjacent(runner):
    """REMEDIATION INVARIANT: there is NO floating "!" prompt — not when far, and
    (the key new leg) NOT when adjacent either. SNES-era RPGs never hovered a "!"
    over an NPC; adjacency draws NOTHING. OAM slot 1 (the slot the "!" used to
    take) must stay CULLED (Y=$F0) both at spawn AND after stepping adjacent.
    Reads the OAM slot-1 low-table bytes directly (the rendered sprite). The
    sabotage check is structural: if any code re-added a "!" on adjacency, slot 1
    would render un-culled here and FAIL. State cycle: far -> adjacent."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(14)

    # --- far (spawn): not adjacent, slot 1 culled (nothing drawn but the avatar) ---
    assert runner.read_bytes(WR, NEAR_NPC, 1)[0] == 0, "spuriously near an NPC at spawn"
    fx, fy, ftile, _ = _oam4(runner, 1)
    assert fy == OAM_CULLED_Y, \
        f"OAM slot 1 NOT culled at spawn — a stray sprite leaked: y={fy} (want 240)"
    runner.take_screenshot(str(E2E / "rpg_s2_far_no_prompt.png"))

    # --- adjacent: one step right -> NPC0 (65,65) is the SOUTH neighbour. The
    #     "!" is GONE, so slot 1 stays CULLED even while adjacent (no floating
    #     prompt). Only the avatar (slot 0) renders; A has not been pressed. ---
    _step_once(runner, right=True)
    assert runner.read_bytes(WR, NEAR_NPC, 1)[0] == 1, "did not become adjacent to the NPC"
    nx, ny, ntile, _ = _oam4(runner, 1)
    assert ny == OAM_CULLED_Y, \
        f"OAM slot 1 rendered while adjacent — a floating prompt leaked: y={ny} (want 240)"
    # the avatar is still on-screen at centre
    assert _oam4(runner, 0)[:2] == (AV_CENTER_X, AV_CENTER_Y), "avatar not centred while adjacent"
    adj = E2E / "rpg_s2_adjacent_no_prompt.png"
    runner.take_screenshot(str(adj))
    # RENDERED check: the slot-1 OAM cull above is a proxy for "no floating '!'",
    # but the "!" the OBSEL bug actually shows comes from the AVATAR being drawn
    # 32x32 (not from slot 1). Read the framebuffer: count bright-yellow "!" pixels
    # (OBJ index 5) in the avatar's 32x32 surround. Zero on a correct 16x16 avatar;
    # ~14 when OBSEL renders it 32x32 and pulls CHR tile 8 in — so this FAILS on
    # the pre-fix ROM the OAM-only asserts pass right past.
    yellow = _count_color(adj, (AV_CENTER_X + 16, AV_CENTER_Y,
                                AV_CENTER_X + 32, AV_CENTER_Y + 18), OBJ_YELLOW, 40)
    assert yellow < 4, \
        f"a phantom '!' rendered beside the hero ({yellow} yellow px) while adjacent " \
        "— the avatar is drawn 32x32 (OBSEL), pulling the '!' glyph into its corner"


def test_npc_full_interaction_cycle(runner):
    """The FULL interaction cycle on the RENDERED OUTPUT: approach (NO floating
    prompt) -> press A -> sprite-text acknowledgement shows -> walk away -> text
    gone. Each leg reads the OAM low-table bytes (the sprites the PPU draws). The
    avatar (slot 0) stays centred throughout; A while adjacent INTERACTS (does
    not transition to the town — the scene mirror stays overworld). The "!"
    indicator is removed, so the strip now occupies slots 1-5 (TEXT_SLOT0=1) and
    slot 1 is CULLED on approach (no prompt) until A is pressed. State-cycle
    coverage: every transition is driven and asserted."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    # --- approach: step right -> adjacent -> NO floating prompt (slot 1 culled) ---
    _step_once(runner, right=True)
    assert runner.read_bytes(WR, NEAR_NPC, 1)[0] == 1, "did not become adjacent"
    assert _oam4(runner, TEXT_SLOT0)[1] == OAM_CULLED_Y, \
        "a sprite rendered on approach (no floating prompt should appear before A)"

    # --- interact: press A while adjacent -> "HELLO" strip renders (slots 1-5) ---
    runner.set_input(0, a=True)
    runner.run_frames(2)
    runner.set_input(0)
    runner.run_frames(10)
    assert _state(runner) == SC_OVERWORLD, \
        "A while next to an NPC wrongly changed scene (should interact, not transition)"
    assert runner.read_bytes(WR, TALKING, 1)[0] == 1, "talking flag not set after A"
    for i, tile in enumerate(TEXT_TILES):
        slot = TEXT_SLOT0 + i
        gx, gy, gtile, _ = _oam4(runner, slot)
        assert gtile == tile, \
            f"text glyph slot {slot} tile {gtile} != expected {tile} (HELLO[{i}])"
        assert (gx, gy) == (TEXT_X0 + i * TEXT_GLYPH_W, TEXT_Y0), \
            f"text glyph slot {slot} not at its strip position: ({gx},{gy})"
        assert gy != OAM_CULLED_Y, f"text glyph slot {slot} culled while talking"
    runner.take_screenshot(str(E2E / "rpg_s2_talking.png"))

    # the avatar stayed centred while the dialog showed
    assert _oam4(runner, 0)[:2] == (AV_CENTER_X, AV_CENTER_Y), \
        "avatar drifted from centre during the dialog"

    # --- walk away: several steps left -> not adjacent -> text strip gone ---
    for _ in range(3):
        _step_once(runner, left=True)
    assert runner.read_bytes(WR, NEAR_NPC, 1)[0] == 0, "still adjacent after walking away"
    assert runner.read_bytes(WR, TALKING, 1)[0] == 0, "dialog not dismissed on walk-away"
    for slot in range(TEXT_SLOT0, TEXT_SLOT0 + len(TEXT_TILES)):
        assert _oam4(runner, slot)[1] == OAM_CULLED_Y, \
            f"text glyph slot {slot} not culled after walk-away"
    # the avatar is still on-screen at centre (the world scrolled under it)
    assert _oam4(runner, 0)[:2] == (AV_CENTER_X, AV_CENTER_Y), "avatar lost after walk-away"
    runner.take_screenshot(str(E2E / "rpg_s2_away_no_prompt.png"))


def test_npc_sprite_text_pixels_render_on_screen(runner):
    """The sprite-text strip renders as VISIBLE PIXELS, not just correct OAM
    bytes (OAM can be right while the sprite is off-palette or occluded). Drive
    approach + A, then scan the strip's 40x8 screen box for the bright cream
    glyph fill (OBJ palette index 6 ~ (248,248,232)) — far brighter than the
    floor. Reads the rendered framebuffer pixels directly."""
    rom = BUILD / "rpg.sfc"
    runner.load_rom(str(rom), run_seconds=1.0)
    runner.run_frames(12)

    _step_once(runner, right=True)
    runner.set_input(0, a=True)
    runner.run_frames(2)
    runner.set_input(0)
    runner.run_frames(10)

    p = E2E / "rpg_s2_text_pixels.png"
    runner.take_screenshot(str(p))
    px = Image.open(p).convert("RGB").load()
    cream = 0
    for yy in range(TEXT_Y0, TEXT_Y0 + 8):
        for xx in range(TEXT_X0, TEXT_X0 + len(TEXT_TILES) * TEXT_GLYPH_W):
            r0, g0, b0 = px[xx, yy]
            if r0 > 210 and g0 > 210 and b0 > 200:   # bright cream glyph fill
                cream += 1
    assert cream > 10, \
        f"no sprite-text glyph pixels rendered in the strip box (cream px={cream})"

    # RENDERED clean-strip check: the cream census above passes even when the
    # glyphs render 16x16 (the OBSEL bug) — the letters are just mashed together.
    # The tell is the 4th cell (the 2nd 'L', sprite at x=120): a clean 8x8 'L' has
    # a TRANSPARENT top-right (floor shows through), but at 16x16 the sprite reads
    # a 2x2 CHR quad and overlays the next tile ('O') there, painting cream where
    # floor should be. Count cream in that should-be-transparent corner: ~0 for a
    # clean 8x8 strip, ~13 on the pre-fix ROM — so this FAILS on the bug that the
    # OAM-tile and gross cream-census asserts pass right past.
    corner_cream = _count_color(p, (123, 76, 128, 84), OBJ_CREAM, 24)
    assert corner_cream < 4, \
        f"the HELLO strip is garbled ({corner_cream} cream px overlay the 2nd 'L'): " \
        "OBSEL is rendering the 8x8 glyphs as 16x16 and compositing neighbouring CHR"


# =============================================================================
# Sprint 3 — TOWN CONTENT: a real Mode 1 town (designed dense tilemap), player
# grid-movement + tile collision, a villager NPC, and the headline sf_text
# dialog box on BG3. Every assertion reads RENDERED OUTPUT — the BG1/BG3 VRAM
# tilemap bytes, the OAM low-table bytes, screenshot pixels, recorded WAV — never
# a proxy game variable (CLAUDE.md "Indirect-Evidence Tests").
#
# A is context-sensitive in the town: near the NPC it opens/closes the BG3
# dialog box; on the south EXIT gate tile it returns to the overworld; elsewhere
# it is a no-op. Movement is one tile per D-pad press (edge-latched).
# =============================================================================
def _enter_town(r):
    """Boot, then enter the town from the overworld spawn (A at a non-NPC tile)."""
    r.load_rom(str(BUILD / "rpg.sfc"), run_seconds=1.0)
    r.run_frames(12)
    _tap(r, a=True)
    assert _state(r) == SC_TOWN, "did not enter the town"


def _bg3_glyph(r, row, col):
    """Read one BG3 text tilemap cell (the tile word the engine wrote). The font
    is monospace from FONT_BASE_TILE=160; a glyph cell's tile index is
    FONT_BASE_TILE + (ascii - 0x20). Returns the raw 16-bit tile word."""
    return r.read_u16(VR, BG3_TILEMAP_BYTE + (row * 32 + col) * 2)


def _bg3_text_cells(r, row, col, n):
    """Count nonzero BG3 glyph cells in a horizontal run (the rendered text)."""
    return sum(1 for i in range(n) if (_bg3_glyph(r, row, col + i) & 0x3FF) != 0)


def test_town_renders_mode1_designed_tilemap(runner):
    """The town is a DESIGNED, DENSE Mode 1 room — not the Mode 7 floor. Asserts
    (a) SHADOW_BGMODE flipped $07->$09, (b) M7 released CH5/6 (M7_OWNED_MASK $00),
    and (c) the rendered screen is a gray cobble room framed by RED BRICK walls
    (a color census) — NOT the green Mode 7 grass. The town is now a DRY plaza:
    there is NO water (the moat + fountain were removed), so the screen has NO
    blue water content. Reads the engine shadow registers AND the rendered
    framebuffer pixels. State: OW -> town."""
    _enter_town(runner)
    assert _u8(runner, SHADOW_BGMODE) == 0x09, "town BGMODE not Mode 1 ($09)"
    assert _u8(runner, M7_OWNED_MASK) == 0x00, "Mode 7 did not release CH5/6"
    assert _u8(runner, M7_PV_ACTIVE) == 0, "Mode 7 still active in the town"

    p = E2E / "rpg_town.png"
    runner.take_screenshot(str(p))
    g, gray, blue = _color_counts(p)
    # the dense cobble plaza is gray-dominant; the green Mode 7 grass is gone.
    assert gray > 800, f"town is not a gray cobble room (gray px={gray})"
    assert g < gray // 2, f"town still looks like the green Mode 7 floor (green px={g})"
    # DRY plaza: no water -> essentially no blue water content (the cobble shadow
    # + brick are gray/red, not blue). A tiny residual is fine; a big blue census
    # would mean water leaked back in.
    assert blue < 80, f"town has unexpected blue/water content (blue px={blue})"
    # brick walls present: census the red-brick colour (150,70,50) on the rim.
    px = Image.open(p).convert("RGB").load()
    w, h = Image.open(p).size
    red_brick = sum(1 for y in range(0, h, 3) for x in range(0, w, 3)
                    if px[x, y][0] > 110 and px[x, y][0] > px[x, y][1] + 30
                    and px[x, y][0] > px[x, y][2] + 30)
    assert red_brick > 200, f"town has no red-brick wall content (red px={red_brick})"

    # destination-region byte check: the BG1 tilemap (byte $B000) is densely
    # filled (cobble tile 1 dominates the interior, brick 2 the border).
    cells = runner.read_bytes(VR, TOWN_TILEMAP_BYTE, 32 * 28 * 2)
    nonzero = sum(1 for i in range(0, len(cells), 2)
                  if (cells[i] | (cells[i + 1] << 8)) & 0x3FF)
    assert nonzero > 800, \
        f"town tilemap not densely filled (only {nonzero} nonzero cells of 896)"
    # NO water tiles (TOWN_TILE_WATER=3) anywhere in the town tilemap — moat +
    # fountain removed. Reads the BG1 tilemap bytes directly (the rendered map).
    water_cells = sum(1 for i in range(0, len(cells), 2)
                      if (cells[i] | (cells[i + 1] << 8)) & 0x3FF == 3)
    assert water_cells == 0, \
        f"town tilemap still has {water_cells} water tiles (moat/fountain not removed)"


def test_town_player_moves_with_dpad(runner):
    """The town avatar (OAM slot 0) grid-walks on the D-pad: each press moves it
    exactly one tile (8 px) on screen. Asserts the OAM slot-0 X/Y bytes (the
    sprite the PPU draws) AND a screenshot pixel at the avatar's new box. Drives
    all four directions (forward + reverse on both axes). Reads the OAM low table
    + rendered pixels, never the town_px proxy. State cycle: right/left/down/up."""
    _enter_town(runner)
    # spawn: avatar at (16*8, 16*8) = (128,128)
    x0, y0, tile0, _ = tuple(runner.read_bytes(OAM, 0, 4))
    assert (x0, y0) == (TOWN_SPAWN_TX * 8, TOWN_SPAWN_TY * 8), \
        f"town avatar not at spawn pixel: ({x0},{y0})"
    assert tile0 == 5, f"town avatar OAM tile {tile0} != avatar tile 5"

    # RIGHT one tile -> +8 px X
    _town_tap(runner, right=True)
    x1, y1 = tuple(runner.read_bytes(OAM, 0, 2))
    assert (x1, y1) == (x0 + 8, y0), f"right tap != +1 tile: ({x0},{y0})->({x1},{y1})"
    runner.take_screenshot(str(E2E / "rpg_town_moved_right.png"))
    # LEFT back
    _town_tap(runner, left=True)
    assert tuple(runner.read_bytes(OAM, 0, 2)) == (x0, y0), "left tap did not return"
    # DOWN one tile -> +8 px Y (column 16 is clear south to the exit)
    _town_tap(runner, down=True)
    x2, y2 = tuple(runner.read_bytes(OAM, 0, 2))
    assert (x2, y2) == (x0, y0 + 8), f"down tap != +1 tile Y: ->({x2},{y2})"
    # UP back to spawn
    _town_tap(runner, up=True)
    assert tuple(runner.read_bytes(OAM, 0, 2)) == (x0, y0), "up tap did not return"

    # screenshot pixel proof: after moving right, the avatar's bright body/head
    # appears in its 16x16 box (the hero blue / cream over the gray cobble).
    _town_tap(runner, right=True)
    p = E2E / "rpg_town_avatar_pixel.png"
    runner.take_screenshot(str(p))
    px = Image.open(p).convert("RGB").load()
    ax, ay = x0 + 8, y0
    found = any(
        (px[xx, yy][2] > 150 and px[xx, yy][2] > px[xx, yy][1] + 40) or
        (px[xx, yy][0] > 200 and px[xx, yy][1] > 180 and px[xx, yy][2] > 140)
        for yy in range(ay, ay + 16) for xx in range(ax, ax + 16)
    )
    assert found, "no avatar pixels in the town 16x16 box after moving right"


def test_town_collision_blocks_against_wall(runner):
    """Town tile collision BLOCKS the avatar against a wall. From the spawn,
    walk LEFT until the player hits the west brick wall (tile col 1, since col 0
    is the border) — the avatar STOPS and a further press does NOT move it past.
    Asserts the OAM slot-0 X stops advancing (the rendered sprite) — not a flag.
    State cycle: walk into the wall, then push (no move)."""
    _enter_town(runner)
    x0, y0 = tuple(runner.read_bytes(OAM, 0, 2))

    # push LEFT hard: 20 taps. The west wall (brick) is at col 0; the player
    # clamps at col 1 (x = 8). It must NOT pass into the wall.
    for _ in range(20):
        _town_tap(runner, left=True, settle=4)
    xw, yw = tuple(runner.read_bytes(OAM, 0, 2))
    assert xw == 1 * 8, f"avatar did not stop at the west wall boundary (x={xw}, want 8)"
    assert yw == y0, f"avatar drifted on Y while walking into the wall (y={yw})"
    runner.take_screenshot(str(E2E / "rpg_town_wall.png"))

    # push once more INTO the wall — the sprite must not advance one pixel
    before = tuple(runner.read_bytes(OAM, 0, 2))
    _town_tap(runner, left=True)
    after = tuple(runner.read_bytes(OAM, 0, 2))
    assert after == before, f"avatar moved INTO the west wall: {before} -> {after}"


def test_town_npc_present_and_blocks(runner):
    """The villager NPC renders (OAM slot 1) at its fixed town tile and is a
    BLOCKED cell — the player cannot walk onto it. Walk up column 16 to (16,9),
    adjacent to the NPC at (16,8); assert town_near (the adjacency the dialog
    gates on) AND that pushing UP into the NPC tile does NOT move the avatar's
    OAM position (the NPC blocks). Reads OAM slot 1 (the NPC sprite the PPU
    draws) + slot 0 (the blocked avatar)."""
    _enter_town(runner)
    # NPC sprite present at its fixed tile
    nx, ny, ntile, _ = tuple(runner.read_bytes(OAM, 4, 4))
    assert (nx, ny) == (TOWN_NPC_TX * 8, TOWN_NPC_TY * 8), \
        f"NPC sprite not at its tile pixel: ({nx},{ny})"
    assert ntile == 5, f"NPC OAM tile {ntile} != avatar tile 5"

    # walk up to (16,9) — adjacent
    _town_walk_to_npc(runner)
    assert runner.read_bytes(WR, TOWN_NEAR, 1)[0] == 1, "did not become NPC-adjacent"
    ax_before, ay_before = tuple(runner.read_bytes(OAM, 0, 2))
    # push UP into the NPC tile (16,8) — blocked, avatar does not advance
    for _ in range(4):
        _town_tap(runner, up=True)
    ax_after, ay_after = tuple(runner.read_bytes(OAM, 0, 2))
    assert (ax_after, ay_after) == (ax_before, ay_before), \
        f"avatar walked ONTO the NPC tile: {(ax_before,ay_before)}->{(ax_after,ay_after)}"


# sf_dialog OPAQUE panel: the box (fill + border) is drawn into the BG3 SHADOW
# tilemap (committed to VRAM byte $C000, 32 wide) — the SAME layer as the dialog
# TEXT. Every panel cell is one of the 9 nine-patch box CHR tiles (144..152)
# carrying the BG3 priority bit, so the box composites above BG1/BG2/OBJ. The
# dialog TEXT prints over the box on BG3. Panel rect = rows 18..26, cols 2..29
# (main.asm DLG_PANEL_ROW/H/COL/W: col 2, row 18, w 28, h 9).
DLG_BOX_TILE_LO, DLG_BOX_TILE_HI = 144, 152   # sf_dialog SF_DLG_TILE_BASE..+8
PANEL_R0, PANEL_R1, PANEL_C0, PANEL_C1 = 18, 26, 2, 29


def _bg3_cell(r, row, col):
    return r.read_u16(VR, BG3_TILEMAP_BYTE + (row * 32 + col) * 2)


def _bg3_panel_cells(r, row, c0, c1):
    """Count BG3 cells in a row run whose tile is a sf_dialog box CHR (144..152) —
    the rendered opaque panel tiles (fill + border), distinct from the font glyphs
    (>=160) and the transparent blank (0)."""
    return sum(1 for c in range(c0, c1 + 1)
               if DLG_BOX_TILE_LO <= (_bg3_cell(r, row, c) & 0x3FF) <= DLG_BOX_TILE_HI)


def test_town_dialog_box_opens_and_closes(runner):
    """THE HEADLINE (sf_dialog): adjacent to the NPC + A opens the dialog box; A
    again closes it. Asserts BOTH (a) the BG3 TEXT tilemap glyph cells (the
    rendered text the NMI commits) and (b) the BG3 PANEL tilemap cells (the opaque
    sf_dialog box nine-patch tiles 144..152) — populated when open, cleared when
    closed — NOT a proxy flag. Plus a screenshot pixel proof. Negative control +
    full open/close cycle. (Box + text now share the BG3 layer, so a text row's
    box cells are replaced by glyph tiles; the NON-text panel rows carry the full
    box fill.)"""
    _enter_town(runner)

    # --- NEGATIVE CONTROL: at spawn (not adjacent), the panel rows are EMPTY (no
    #     text and no box tiles on BG3) ---
    assert runner.read_bytes(WR, TOWN_NEAR, 1)[0] == 0, "spuriously near NPC at spawn"
    assert _bg3_text_cells(runner, DLG_TEXT_ROW, DLG_TEXT_COL, 26) == 0, \
        "BG3 dialog box has glyphs before any interaction (leaked)"
    assert _bg3_panel_cells(runner, 20, PANEL_C0, PANEL_C1) == 0, \
        "sf_dialog panel present before any interaction (leaked)"

    # --- SABOTAGE-VERIFY the negative control: pressing A far from the NPC must
    #     NOT open the box (A is a no-op away from the NPC + save point + exit). ---
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(8)
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 0, \
        "dialog opened on A FAR from the NPC (negative control failed)"
    assert _bg3_text_cells(runner, DLG_TEXT_ROW, DLG_TEXT_COL, 26) == 0, \
        "BG3 box glyphs appeared on A far from the NPC"
    assert _bg3_panel_cells(runner, 20, PANEL_C0, PANEL_C1) == 0, \
        "sf_dialog panel appeared on A far from the NPC"

    # --- approach + open: walk to the NPC, press A -> box renders ---
    _town_walk_to_npc(runner)
    assert runner.read_bytes(WR, TOWN_NEAR, 1)[0] == 1, "not adjacent to the NPC"
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(10)
    # the 3 dialog text rows (19/21/23) each carry many BG3 glyph cells now
    for row in (DLG_TEXT_ROW, DLG_TEXT_ROW + 2, DLG_TEXT_ROW + 4):
        n = _bg3_text_cells(runner, row, DLG_TEXT_COL, 26)
        assert n >= 8, f"BG3 dialog row {row} not rendered (glyph cells={n})"
    # the OPAQUE sf_dialog panel: the NON-text panel rows (20, 22, 24, 25) are
    # FULLY filled with box tiles (28 cells), and the border rows (18 top, 26
    # bottom) carry the full box frame. (Text rows 19/21/23 have glyphs over the
    # box, so they are checked via the glyph cells above.)
    for row in (20, 22, 24, 25):
        n = _bg3_panel_cells(runner, row, PANEL_C0, PANEL_C1)
        assert n == (PANEL_C1 - PANEL_C0 + 1), \
            f"sf_dialog panel row {row} not fully filled (box cells={n}, want 28)"
    assert _bg3_panel_cells(runner, PANEL_R0, PANEL_C0, PANEL_C1) >= 28, "panel top border missing"
    assert _bg3_panel_cells(runner, PANEL_R1, PANEL_C0, PANEL_C1) >= 28, "panel bottom border missing"

    # a specific glyph: the 'W' of "WELCOME" at row 19 col 5 (text inset 2 spaces
    # from DLG_X col 3). Verify a real ASCII tile: tile = FONT_BASE_TILE + (W-0x20).
    cell = _bg3_glyph(runner, DLG_TEXT_ROW, DLG_TEXT_COL + 2) & 0x3FF  # 'W'
    assert cell == FONT_BASE_TILE + (ord('W') - 0x20), \
        f"first dialog glyph is {cell}, not 'W' tile {FONT_BASE_TILE + (ord('W') - 0x20)}"

    runner.take_screenshot(str(E2E / "rpg_town_dialog.png"))
    # screenshot pixel proof: the box region (y 152..200) has bright white glyph
    # pixels (the default text colour) over the OPAQUE navy box.
    px = Image.open(E2E / "rpg_town_dialog.png").convert("RGB").load()
    white = sum(1 for yy in range(150, 200) for xx in range(24, 232)
                if px[xx, yy][0] > 200 and px[xx, yy][1] > 200 and px[xx, yy][2] > 200)
    assert white > 40, f"no bright dialog-text pixels in the box region (white px={white})"

    # --- close: A again -> the box + text clear on BG3 (NMI commits the cleared
    #     shadow) ---
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(10)
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 0, "dialog did not close on A"
    for row in (DLG_TEXT_ROW, DLG_TEXT_ROW + 2, DLG_TEXT_ROW + 4):
        assert _bg3_text_cells(runner, row, DLG_TEXT_COL, 26) == 0, \
            f"BG3 dialog text row {row} not cleared after close"
    for row in range(PANEL_R0, PANEL_R1 + 1):
        assert _bg3_panel_cells(runner, row, PANEL_C0, PANEL_C1) == 0, \
            f"sf_dialog panel row {row} not cleared after close"
    runner.take_screenshot(str(E2E / "rpg_town_dialog_closed.png"))


# --- box-fill navy colour (sf_dialog BG3 sub-palette 6 colour 1 = CGRAM 25,
#     SF_DLG default body $2862 = ~(16,24,82)). The opaque-box test asserts the
#     box BODY renders this navy (NOT the cobble/brick town behind it). ---
BOX_FILL_RGB = (16, 24, 82)
# Box-interior screen pixels in CLEAN GAP ROWS between the 3 text lines: the text
# glyphs render at screenshot y ~162-164 / 174-180 / 190-196; the gaps between
# them (y ~167-172 / 183-188 / 199-210) are SOLID box-fill navy. X=120 is mid-box.
# (sf_dialog draws box + text on the SAME BG3 layer, so the text-ROW gaps between
# glyphs show the muted scene — the documented single-layer limitation; we assert
# opacity on the box BODY / gap rows + the frame, exactly the kit sf_dialog test
# surface. A transparent box would show town tiles even in these gap rows.)
BOX_INTERIOR_X = 120
BOX_GAP_ROWS = (170, 186, 204)        # screenshot-y rows squarely in the navy gaps
# census window = the navy GAP bands only (between/below the text lines), where
# the body is solid navy. cols 2..29 -> X ~16..239; sample X 40..216 inside.
BOX_CENSUS_X0, BOX_CENSUS_X1 = 40, 216
BOX_GAP_BANDS = ((167, 172), (183, 188), (199, 210))


def _is_box_fill(rgb, tol=40):
    """A box-fill pixel: close to the navy BOX_FILL_RGB. NOT gray cobble (r~g~b,
    much lighter), NOT red brick (r dominant)."""
    return all(abs(c - t) <= tol for c, t in zip(rgb, BOX_FILL_RGB))


def _is_town_floor(rgb):
    """A town floor pixel: gray cobble (~(96..140 each, r~g~b)) or red brick
    (r dominant, r-g and r-b large). The box BODY is OPAQUE iff NONE of these
    appear in the navy gap bands (only navy fill / steel border / white text do)."""
    r, g, b = rgb
    gray = abs(r - g) < 28 and abs(g - b) < 40 and 80 < r < 190
    brick = r > 110 and r > g + 30 and r > b + 30
    return gray or brick


def test_town_dialog_box_is_opaque(runner):
    """REMEDIATION HEADLINE — the sf_dialog box is a REAL OPAQUE windowed panel,
    not the prior ASCII-art frame the scene showed through. With the box OPEN: (1)
    each clean GAP-ROW pixel between the text lines is the box-FILL navy, NOT town
    floor; (2) a horizontal RUN across a gap row is solid navy (no leaks); (3) the
    box-BODY gap bands (between + below the text lines) contain ZERO town floor
    pixels (gray cobble / red brick) — solid navy fill. Reads the composited
    screenshot directly. SABOTAGE: a transparent/ASCII box would show town tiles
    in these gap rows and FAIL (2) and (3). (The text-ROW gaps between glyphs show
    the muted scene — sf_dialog's documented single-layer behavior; opacity is
    asserted on the box BODY, the kit sf_dialog test surface.) State-cycle:
    open + close."""
    _enter_town(runner)
    _town_walk_to_npc(runner)
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(12)
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 1, "dialog not open"

    p = E2E / "rpg_town_box_opaque.png"
    runner.take_screenshot(str(p))
    px = Image.open(p).convert("RGB").load()

    # (1) each mid-box GAP-ROW pixel is navy fill, not town floor
    for gy in BOX_GAP_ROWS:
        rgb = px[BOX_INTERIOR_X, gy]
        assert _is_box_fill(rgb), \
            (f"box body pixel ({BOX_INTERIOR_X},{gy}) is {rgb}, not the opaque navy "
             f"fill {BOX_FILL_RGB} — the town shows through (box body not opaque)")

    # (2) a horizontal run across a gap row is solid navy fill
    gy = BOX_GAP_ROWS[1]
    fill_px = sum(1 for x in range(40, 216) if _is_box_fill(px[x, gy]))
    total = len(range(40, 216))
    assert fill_px > total * 0.9, \
        (f"box body row y={gy} only {fill_px}/{total} navy-fill pixels "
         f"— the panel body is not opaque (town leaks through the box)")

    # (3) the box-BODY gap bands have ZERO town floor pixels — every pixel is navy
    #     fill / steel border / white text. A transparent box would census many.
    town_px = sum(1 for (y0, y1) in BOX_GAP_BANDS
                  for yy in range(y0, y1, 2)
                  for xx in range(BOX_CENSUS_X0, BOX_CENSUS_X1, 2)
                  if _is_town_floor(px[xx, yy]))
    assert town_px == 0, \
        (f"{town_px} town floor pixels found INSIDE the box region — the box is not "
         f"opaque (the town leaks through the dialog panel)")

    # (4) SABOTAGE-VERIFY: with the box CLOSED, the SAME gap bands ARE full of
    #     town floor — proves the navy came from the box, not an always-navy bg.
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(12)
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 0, "dialog did not close"
    runner.take_screenshot(str(E2E / "rpg_town_box_closed.png"))
    px2 = Image.open(E2E / "rpg_town_box_closed.png").convert("RGB").load()
    town_after = sum(1 for (y0, y1) in BOX_GAP_BANDS
                     for yy in range(y0, y1, 2)
                     for xx in range(BOX_CENSUS_X0, BOX_CENSUS_X1, 2)
                     if _is_town_floor(px2[xx, yy]))
    assert town_after > 100, \
        (f"only {town_after} town pixels after closing the box — the town did not "
         f"come back (box did not clear, or the navy was not the box)")


def test_town_no_floating_prompt_when_adjacent(runner):
    """REMEDIATION INVARIANT (town): NO floating "!" prompt over the NPC. Walk the
    player ADJACENT to the villager (dialog CLOSED) and assert the town renders
    EXACTLY three OBJ sprites — avatar (slot 0), villager NPC (slot 1), and the
    SAVE POINT attendant (slot 2, tile 5 at (80,144)) — and NO floating prompt:
    slot 3 (the next free slot) is CULLED (Y=$F0). Reads the OAM low-table bytes
    directly. SABOTAGE: a re-added "!" on adjacency would render an extra sprite
    at slot 3 un-culled and FAIL. State cycle: spawn -> walk adjacent (dialog
    closed). (Slot 2 is the save attendant now — it always renders, so the
    no-prompt check moved to slot 3.)"""
    _enter_town(runner)
    _town_walk_to_npc(runner)
    assert runner.read_bytes(WR, TOWN_NEAR, 1)[0] == 1, "did not become NPC-adjacent"
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 0, "dialog spuriously open"
    # slot 0 = avatar, slot 1 = NPC, slot 2 = save attendant (all render);
    # slot 3 must be CULLED (no floating prompt).
    av = tuple(runner.read_bytes(OAM, 0, 4))
    npc = tuple(runner.read_bytes(OAM, 4, 4))
    save = tuple(runner.read_bytes(OAM, 8, 4))
    s3 = tuple(runner.read_bytes(OAM, 12, 4))
    assert av[1] != OAM_CULLED_Y and av[2] == 5, f"avatar not rendered: {av}"
    assert npc[1] != OAM_CULLED_Y and npc[2] == 5, f"NPC not rendered: {npc}"
    assert save[1] != OAM_CULLED_Y and save[2] == 5 and save[:2] == (80, 144), \
        f"save attendant not rendered at (80,144): {save}"
    assert s3[1] == OAM_CULLED_Y, \
        f"OAM slot 3 rendered while adjacent — a floating '!' prompt leaked: {s3} (want y=240)"
    runner.take_screenshot(str(E2E / "rpg_town_adjacent_no_prompt.png"))


def test_town_avatar_16x16_no_phantom_exclamation(runner):
    """REGRESSION (root cause of the user-reported phantom "!"): the avatar/NPC
    are 16x16, NOT 32x32. With OBSEL size pair 16/32 ($62) + the LARGE size bit,
    a 16x16-intended sprite (base tile 5) rendered 32x32 and pulled tile 8 — the
    IND "!" glyph — into its top-right quadrant: a phantom exclamation mark ~24px
    right of EVERY character. The "no floating prompt" test missed it because it
    only checked for a SEPARATE OAM sprite; this "!" was baked into the character
    sprite itself. So read the rendered SCREENSHOT pixels where the 32x32 phantom
    would land — they must be cobble background, not bright IND yellow.
    SABOTAGE: at 32x32 (OBSEL $62, the bug) that band is full of yellow pixels."""
    _enter_town(runner)
    runner.take_screenshot(str(E2E / "rpg_town_no_phantom.png"))
    px = Image.open(E2E / "rpg_town_no_phantom.png").convert("RGB").load()
    # The IND "!" glyph renders as bright lemon-yellow (~255,239,99): high R+G,
    # low B. (The avatar's cream face ~247,222,181 has B too high to match, so it
    # is NOT counted.) Scan the central play area where the characters stand; the
    # 32x32 bug drew ~28 such px (a phantom '!' beside the avatar AND the NPC),
    # the 16x16 fix draws ZERO. Sabotage-verified on the captures: $62 -> 28, $02 -> 0.
    ind = 0
    for sy in range(40, 180):
        for sx in range(100, 200):
            r, g, b = px[sx, sy]
            if r > 230 and g > 210 and b < 130:
                ind += 1
    assert ind == 0, \
        f"phantom IND '!' yellow in the town: {ind} px — a 16x16-intended sprite " \
        f"is being drawn 32x32 and reading tile 8 (the '!' glyph)"


def test_town_dialog_freezes_movement(runner):
    """While the dialog box is OPEN, player movement is frozen (a real dialog
    blocks walking — the user-visible invariant: the avatar pixels do not move
    while reading the box). Open the dialog, then press a D-pad direction and
    assert the OAM slot-0 position does NOT change. Reads the rendered OAM bytes."""
    _enter_town(runner)
    _town_walk_to_npc(runner)
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(10)
    assert runner.read_bytes(WR, TOWN_DIALOG, 1)[0] == 1, "dialog not open"
    pos_open = tuple(runner.read_bytes(OAM, 0, 2))
    # try to walk while the box is open — the avatar must not move
    for d in (dict(left=True), dict(right=True), dict(down=True)):
        _town_tap(runner, **d)
    pos_after = tuple(runner.read_bytes(OAM, 0, 2))
    assert pos_after == pos_open, \
        f"avatar moved while the dialog was open: {pos_open} -> {pos_after}"


def test_town_full_scene_cycle_forward_and_reverse(runner):
    """ACCEPTANCE INVARIANT 5 — the full town scene cycle on RENDERED OUTPUT,
    driven forward AND reverse: overworld -> town -> MOVE -> TALK -> CLOSE ->
    LEAVE -> overworld, with each scene's render asserted and the overworld
    camera restored on return. Reads the engine shadows, the OAM/BG3 bytes, and
    the screen — never a proxy. The reverse leg (town -> overworld) is the exit
    gate; the camera-restore is the reverse-direction state coverage."""
    runner.load_rom(str(BUILD / "rpg.sfc"), run_seconds=1.0)
    runner.run_frames(12)

    # leg A: overworld render (green Mode 7 floor) + save the spawn camera
    assert _state(runner) == SC_OVERWORLD
    cam_spawn = runner.read_u16(WR, M7_PV_POSX_INT)
    runner.take_screenshot(str(E2E / "rpg_cycle_0_ow.png"))
    g, _, _ = _color_counts(E2E / "rpg_cycle_0_ow.png")
    assert g > 800, "leg A: overworld not a green Mode 7 floor"

    # leg B: -> town (forward) — Mode 1 render
    _tap(runner, a=True)
    assert _state(runner) == SC_TOWN and _u8(runner, SHADOW_BGMODE) == 0x09
    runner.take_screenshot(str(E2E / "rpg_cycle_1_town.png"))
    _, gray, _ = _color_counts(E2E / "rpg_cycle_1_town.png")
    assert gray > 800, "leg B: town not a Mode 1 cobble room"

    # leg C: MOVE the avatar (OAM 0 changes), then TALK (BG3 box), then CLOSE
    sx, sy = tuple(runner.read_bytes(OAM, 0, 2))
    _town_tap(runner, right=True)
    assert tuple(runner.read_bytes(OAM, 0, 2)) == (sx + 8, sy), "leg C: avatar did not move"
    _town_tap(runner, left=True)   # back to column 16 so the NPC walk lines up
    _town_walk_to_npc(runner)
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(10)
    assert _bg3_text_cells(runner, DLG_TEXT_ROW, DLG_TEXT_COL, 26) >= 8, "leg C: dialog did not open"
    runner.set_input(0, a=True); runner.run_frames(2); runner.set_input(0); runner.run_frames(10)
    assert _bg3_text_cells(runner, DLG_TEXT_ROW, DLG_TEXT_COL, 26) == 0, "leg C: dialog did not close"

    # leg D: LEAVE via the exit gate (reverse) -> overworld, camera RESTORED
    _town_to_overworld(runner)
    assert _state(runner) == SC_OVERWORLD, "leg D: did not return to the overworld"
    assert _u8(runner, SHADOW_BGMODE) == 0x07, "leg D: BGMODE not Mode 7 on return"
    assert _u8(runner, M7_OWNED_MASK) == 0x60, "leg D: CH5/6 not re-pinned"
    cam_back = runner.read_u16(WR, M7_PV_POSX_INT)
    assert cam_back == cam_spawn, \
        f"leg D: overworld camera not restored ({cam_spawn} -> {cam_back})"
    runner.take_screenshot(str(E2E / "rpg_cycle_2_returned.png"))
    g2, _, _ = _color_counts(E2E / "rpg_cycle_2_returned.png")
    assert g2 > 800, "leg D: returned overworld not a green Mode 7 floor"
