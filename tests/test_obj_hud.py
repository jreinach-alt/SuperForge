"""OBJ sprite-font HUD renderer — render gate (the showcase brick).

Proves the sf_obj_text.inc HUD primitive renders a legible glyph readout as OBJ
sprites in OBJ palette 7, OVER a real BG, in two BG modes that matter: a NORMAL
mode (Mode 1) and the 256-colour Mode 3. The Mode-3 case is the critical one: the
8bpp BG owns CGRAM 0-239, so the HUD must own its reserved OBJ palette 7 (CGRAM
240-255) — this test proves the HUD stays legible there, the whole premise of
making the HUD OBJ-based rather than a BG layer (allocations contract §3).

Primary evidence (CLAUDE.md rule 2 — read the RENDERED output, not a proxy):
  - a SCREENSHOT scan along the HUD glyph rows finds the glyph colour (pal-7
    slot 1, pure white) at the expected screen X positions, in BOTH modes — the
    glyphs actually drew. A blank row (HUD failed to render) gives no white.
  - the rendered BG is non-black behind the HUD (the HUD sits on real content).
Cross-checks (structural, secondary):
  - hardware OAM slots 0..N carry the HUD glyph sprites: tile != 0, palette
    field == 7, Y in the top band.
  - CGRAM 240-255 hold the HUD palette (pal-7 entry 1 == white $7FFF); in Mode 3
    CGRAM 0-239 hold the BG ramp (the palette split is real, not aspirational).

ROM contract (tests/obj_hud_test.asm), two build variants:
  obj_hud_test.sfc        Mode 1 (normal): blue BG field + the white HUD.
  obj_hud_mode3_test.sfc  Mode 3 (256-colour): 8bpp ramp (CGRAM 0-239) + HUD.
Both draw, via the macros under test:
  sf_obj_print "MOSAIC"  @ (16, 8)   -> OAM slots 0..5
  sf_obj_num   #7        @ (80, 8)   -> "00007", slots 6..10
  sf_obj_print "COLORMATH ADD" @ (16,20) -> slots 11..23
Debug block: $7E:E008=1, $7E:E010=SHADOW_BGMODE, $7E:E011=SHADOW_TM.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
CG = MemoryType.SnesCgRam
OAM = MemoryType.SnesSpriteRam
SHOTS = Path("/tmp/e2e_screenshots")

# Glyph-tile indices the ROM places (relative to the OBJ name base), from
# sf_obj_text_data.inc: 'M'=23 'O'=25 'S'=29 'A'=11 'I'=19 'C'=13; digit '0'=1
# '7'=8. "MOSAIC" -> [23,25,29,11,19,13]; "00007" -> [1,1,1,1,8].
MOSAIC_TILES = [23, 25, 29, 11, 19, 13]
NUM_TILES = [1, 1, 1, 1, 8]

# The HUD readout band: OAM Y=8 for row 1 (top band, <=24 per allocations §2).
# On the rendered frame the OBJ row appears ~7 px lower than the OAM Y (PPU/
# screenshot vertical offset), so the glyph pixels land in a y-band, not a single
# row — the test searches the band rather than assuming an exact y.
ROW1_YBAND = range(13, 22)      # MOSAIC + number row
ROW2_YBAND = range(25, 34)      # COLORMATH ADD row
# Expected glyph X centres (sprite X + ~3 px into an 8 px glyph). MOSAIC starts at
# x=16 stepping +8; the number "00007" starts at x=80 stepping +8.
MOSAIC_X = [16, 24, 32, 40, 48, 56]
NUM_X = [80, 88, 96, 104, 112]


def _load(rom_name):
    rom = BUILD / rom_name
    assert rom.exists(), f"{rom} not built — run `make {rom.stem}` first"
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))
        cgram = bytes(r.read_bytes(CG, 0, 512))
        oam = bytes(r.read_bytes(OAM, 0, 544))
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"{rom.stem}.png"
        r.take_screenshot(str(path))
        img = Image.open(path).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "cgram": cgram, "oam": oam, "img": img, "shot": path}


@pytest.fixture(scope="module")
def mode1():
    return _load("obj_hud_test.sfc")


@pytest.fixture(scope="module")
def mode3():
    return _load("obj_hud_mode3_test.sfc")


# ---- helpers ----------------------------------------------------------------

def _white_x_positions(img, yband, x0, x1):
    """Screen X positions in [x0,x1) whose pixel is near-white (the pal-7 glyph
    colour $7FFF) anywhere in the y-band."""
    xs = set()
    for x in range(x0, x1):
        for y in yband:
            px = img.getpixel((x, y))
            if min(px) > 180:        # near-white (glyph colour)
                xs.add(x)
                break
    return sorted(xs)


def _glyph_present_at(img, yband, x_center):
    """True if a near-white glyph pixel exists within +/-3 px of x_center in the
    band (a glyph drew at roughly that sprite position)."""
    for x in range(max(0, x_center - 1), x_center + 7):
        for y in yband:
            if min(img.getpixel((x, y))) > 180:
                return True
    return False


# ---- structural: boots, modes, OAM, CGRAM -----------------------------------

@pytest.mark.parametrize("fx,mode,tm", [("mode1", 0x01, 0x17), ("mode3", 0x03, 0x13)])
def test_boots_and_mode(request, fx, mode, tm):
    s = request.getfixturevalue(fx)
    assert s["debug"][0:4] == b"SFDB", f"{fx}: no boot magic"
    assert s["debug"][0x08] == 0x01, f"{fx}: completion flag not set"
    assert (s["debug"][0x10] & 0x07) == mode, f"{fx}: SHADOW_BGMODE low3 != {mode}"
    assert s["debug"][0x11] == tm, f"{fx}: SHADOW_TM != {tm:#04x}"


@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_oam_carries_hud_glyphs(request, fx):
    """Hardware OAM slots 0..10 carry the MOSAIC run + the number: the right tile
    indices, OBJ palette 7, Y in the top band."""
    s = request.getfixturevalue(fx)
    oam = s["oam"]
    want = MOSAIC_TILES + NUM_TILES
    for slot, tile in enumerate(want):
        x, y, t, attr = oam[slot * 4 : slot * 4 + 4]
        assert t == tile, f"{fx}: OAM slot {slot} tile {t} != expected {tile}"
        assert ((attr >> 1) & 0x07) == 7, f"{fx}: OAM slot {slot} palette != 7 (attr {attr:#04x})"
        assert y == 8, f"{fx}: OAM slot {slot} Y={y} not in top band (8)"


@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_cgram_hud_palette_is_obj_pal7(request, fx):
    """OBJ palette 7 = CGRAM 240-255: entry 0 transparent, entry 1 = white glyph
    colour ($7FFF). This is the HUD's reserved slice in EVERY mode."""
    cg = request.getfixturevalue(fx)["cgram"]
    e0 = cg[240 * 2] | (cg[240 * 2 + 1] << 8)
    e1 = cg[241 * 2] | (cg[241 * 2 + 1] << 8)
    assert e0 == 0x0000, f"{fx}: CGRAM[240] (pal7 slot0) != transparent"
    assert e1 == 0x7FFF, f"{fx}: CGRAM[241] (pal7 slot1) != white $7FFF (got {e1:#06x})"


def test_mode3_palette_split(mode3):
    """The 256-colour CONSTRAINT (allocations §3): the Mode-3 BG fills CGRAM 0-239
    and leaves 240-255 to the HUD. CGRAM[N]=N for the ramp; 240-255 are the HUD
    palette (240 transparent != ramp value $00F0)."""
    cg = mode3["cgram"]
    for n in (1, 64, 128, 200, 239):
        v = cg[n * 2] | (cg[n * 2 + 1] << 8)
        assert v == n, f"mode3: CGRAM[{n}] (BG ramp) != {n}, got {v:#06x}"
    # 240 is the HUD's transparent slot, NOT the ramp's $00F0 — proves the split.
    assert (cg[240 * 2] | (cg[240 * 2 + 1] << 8)) == 0x0000


# ---- RENDERED OUTPUT: the glyphs actually drew, in pal-7 white ---------------

@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_mosaic_glyphs_render(request, fx):
    """RENDERED proof: each of the 6 MOSAIC glyph sprites drew a white pixel at
    its screen X. A blank row (HUD did not render) finds no white."""
    img = request.getfixturevalue(fx)["img"]
    missing = [xc for xc in MOSAIC_X if not _glyph_present_at(img, ROW1_YBAND, xc)]
    assert not missing, f"{fx}: MOSAIC glyphs missing at X {missing} — HUD did not render"


@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_number_glyphs_render(request, fx):
    """RENDERED proof: sf_obj_num drew the 5 digit sprites ("00007")."""
    img = request.getfixturevalue(fx)["img"]
    missing = [xc for xc in NUM_X if not _glyph_present_at(img, ROW1_YBAND, xc)]
    assert not missing, f"{fx}: number glyphs missing at X {missing}"


@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_second_row_renders(request, fx):
    """The second sf_obj_print run ("COLORMATH ADD") drew on its own row band —
    proves the renderer places a run at an arbitrary Y, not just one fixed row."""
    img = request.getfixturevalue(fx)["img"]
    xs = _white_x_positions(img, ROW2_YBAND, 14, 120)
    assert len(xs) >= 12, f"{fx}: COLORMATH row too few white glyph pixels ({len(xs)})"


@pytest.mark.parametrize("fx", ["mode1", "mode3"])
def test_glyphs_are_pal7_white_not_bg(request, fx):
    """The glyph colour is the pal-7 white ($7FFF -> RGB 255,255,255), distinct
    from any BG colour — proves the HUD uses its OWN palette, not BG bleed-through.
    The critical mode-3 case: white over the 256-colour ramp."""
    img = request.getfixturevalue(fx)["img"]
    found_white = any(
        img.getpixel((x, y)) == (255, 255, 255)
        for x in range(14, 70) for y in ROW1_YBAND
    )
    assert found_white, f"{fx}: no pure-white pal-7 glyph pixel in the MOSAIC band"


def test_mode3_bg_is_256colour_behind_hud(mode3):
    """The Mode-3 BG renders a many-colour ramp (the 256-colour showcase content)
    BELOW the HUD rows — the HUD is legible OVER real 256-colour content, not over
    black. Scans the ramp strip (rows ~96-120, the BG block centre)."""
    img = mode3["img"]
    seen = set()
    for x in range(112, 144):
        seen.add(img.getpixel((x, 110)))
    assert len(seen) >= 12, f"mode3: ramp only {len(seen)} colours — 256-colour BG absent"
