"""Run-gate for sf_dialog (opaque dialog panel macros).

Asserts on RENDERED output, never a proxy variable (kit rigor rule
"Indirect-Evidence Tests Are Worse Than No Tests"):

  - VRAM: the box CHR (nine-patch tile 1, the TL corner) is uploaded to the
    BG3 CHR base region byte-for-byte from sf_dialog_chr — the DESTINATION
    region read (the asset-upload-path rule).
  - Screenshot, full open->close STATE CYCLE (the state-cycle-coverage rule):
      * before open : the panel region of the screen is the BG1 wall color
        (green) — no panel.
      * after open  : the panel BODY is the opaque panel-body color (NOT the
        wall color) AND a border ring is present (layer-occlusion / opacity
        verified on the composited frame, not a single-layer byte read) AND
        the message text contributes non-body pixels inside the panel.
      * after close : the panel region is the wall color again (scene fully
        restored).

Feature under test: sf_dialog_open / sf_dialog_close opaque BG3 panel.
Output regions read: SnesVideoRam (BG3 CHR), screenshot pixels (composited).
State cycle exercised: closed -> open -> closed (A opens, B closes).

ROM contract (tests/dialog_test.asm): green BG1 wall fill; A press opens a
24x7 panel at cell (4,18) + prints "HELLO ADVENTURER"; B press closes it.
$7E:E010 = heartbeat, $7E:E012 = panel-open flag (supplemental only).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
SHOTS = Path("/tmp/e2e_screenshots")

# Panel geometry mirrors the ROM (cells); cell*8 = pixel.
PANEL_COL, PANEL_ROW, PANEL_W, PANEL_H = 4, 18, 24, 7
# Box CHR lands at BG3 CHR base word $2000 + SF_DLG_TILE_BASE(144) * 8 words.
BOX_TILE1_WORD = 0x2000 + 144 * 8

# sf_dialog_chr tile +0 (TL corner) first 16 bytes (the generated, verified
# 2bpp bytes — this is the independent ground truth for the upload).
TL_CORNER = bytes([
    0x00, 0xFF, 0x7F, 0x80, 0x7F, 0x80, 0x7F, 0x80,
    0x7F, 0x80, 0x7F, 0x80, 0x7F, 0x80, 0x7F, 0x80,
])


def _is_green(px):
    r, g, b = px
    return g > 150 and r < 100 and b < 100


def _is_wall(px):
    return _is_green(px)


def _vert_offset(img):
    """Mesen screenshots include top overscan rows (e.g. 239 tall vs 224
    active). Detect the first row of the green wall field along a column that
    is wall everywhere it's not the panel, so cell->pixel math is overscan-
    robust. Returns the screen-pixel y=0 offset within the image."""
    col = 8  # left edge, above/left of the panel — wall (or HUD) here
    for y in range(img.size[1]):
        # first non-black row from the top is screen y≈0 (the wall/HUD start)
        r, g, b = img.getpixel((col, y))
        if r + g + b > 60:
            return y
    return 0


def _panel_present(img, yoff):
    """True iff a panel is rendered: the EXPECTED panel-body center cell (a
    cell with no text) is NOT the wall color. Uses cell coords + the overscan
    offset — a direct rendered-frame probe, robust to the green demo text
    (which only occupies the text band) because the probe is a body cell."""
    # probe the panel body one cell inside the top-left corner (a fill cell,
    # never a text cell — text is at rows row+2..row+3, cols col+2..)
    px = (PANEL_COL + 1) * 8 + 4
    py = yoff + (PANEL_ROW + 1) * 8 + 4
    return not _is_wall(img.getpixel((px, py)))


def _panel_extent(img, yoff):
    """Measure the rendered panel width/height by scanning the body bands that
    avoid the text row: scan a horizontal line through a fill row (row+1) for
    the non-wall run, and a vertical line through a fill col (col+1, left of
    the text) for the non-wall run. Returns (w_px, h_px)."""
    # horizontal extent at body row row+1 (a fill row, no text)
    hy = yoff + (PANEL_ROW + 1) * 8 + 4
    xs = [x for x in range(img.size[0]) if not _is_wall(img.getpixel((x, hy)))]
    w_px = (max(xs) - min(xs)) if xs else 0
    # vertical extent at body col col+1 (left fill column, left of the text
    # which starts at col+2) — avoids the green glyph pixels entirely
    vx = (PANEL_COL + 1) * 8 + 2
    ys = [y for y in range(img.size[1]) if not _is_wall(img.getpixel((vx, y)))]
    # the wall field spans the whole column except the panel; take the longest
    # contiguous non-wall run as the panel height
    h_px = 0
    run = 0
    for y in range(img.size[1]):
        if not _is_wall(img.getpixel((vx, y))):
            run += 1
            h_px = max(h_px, run)
        else:
            run = 0
    return (w_px, h_px)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _shot(runner, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _press(runner, **btn):
    runner.set_input(0, **btn)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(8)


def _panel_body_pixels(img, yoff):
    """A grid of pixels at the EXPECTED interior of the panel (cell coords +
    overscan offset), EXCLUDING the 2-cell text band where glyph pixels
    legitimately differ from the body. Used to assert wall-color before/after
    (panel absent) and opacity after open."""
    x0 = (PANEL_COL + 1) * 8 + 2
    x1 = (PANEL_COL + PANEL_W - 1) * 8 - 2
    text_y0 = yoff + (PANEL_ROW + 2) * 8
    text_y1 = yoff + (PANEL_ROW + 4) * 8
    y0 = yoff + (PANEL_ROW + 1) * 8 + 2
    y1 = yoff + (PANEL_ROW + PANEL_H - 1) * 8 - 2
    pts = []
    for x in range(x0, x1, 6):
        for y in range(y0, y1, 4):
            if text_y0 <= y < text_y1:
                continue
            pts.append(img.getpixel((x, y)))
    return pts


def test_box_chr_uploaded_to_vram(runner):
    """DESTINATION-region byte test: the TL-corner box tile reached BG3 CHR."""
    rom = BUILD / "dialog_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(5)
    got = runner.read_bytes(VR, BOX_TILE1_WORD * 2, 16)
    assert bytes(got) == TL_CORNER, (
        f"box CHR not uploaded to BG3 CHR base: {got.hex()} != {TL_CORNER.hex()}"
    )


def test_dialog_open_close_cycle(runner):
    """Full state cycle on the composited frame: closed -> open -> closed."""
    rom = BUILD / "dialog_test.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    # --- BEFORE open: panel region is the wall color (no panel) ---
    before = _shot(runner, "dialog_before.png")
    yoff = _vert_offset(before)
    assert not _panel_present(before, yoff), "panel visible before open"
    body_before = _panel_body_pixels(before, yoff)
    wall_frac = sum(_is_wall(p) for p in body_before) / len(body_before)
    assert wall_frac > 0.8, (
        f"panel region not the wall color before open ({wall_frac:.2f} wall)"
    )

    # --- OPEN (A edge) ---
    _press(runner, a=True)
    assert runner.read_u16(WR, 0xE012) == 1, "open flag not set"
    after = _shot(runner, "dialog_open.png")
    yoff = _vert_offset(after)

    # a panel is rendered (the body center cell is no longer wall) at roughly
    # the expected size — measured on the composited frame
    assert _panel_present(after, yoff), "panel not rendered after open"
    w_px, h_px = _panel_extent(after, yoff)
    assert w_px > (PANEL_W - 4) * 8, f"panel too narrow: {w_px}px"
    assert h_px > (PANEL_H - 2) * 8, f"panel too short: {h_px}px"

    # opacity: almost no wall (green) pixels show through inside the panel body
    body_after = _panel_body_pixels(after, yoff)
    wall_after = sum(_is_wall(p) for p in body_after) / len(body_after)
    assert wall_after < 0.10, (
        f"panel not opaque — wall shows through ({wall_after:.2f} wall inside)"
    )
    # a distinct body fill color (blue-ish: more blue than red/green) dominates
    blueish = sum(1 for (r, g, b) in body_after if b > r and b > 60)
    assert blueish > 0.5 * len(body_after), (
        f"panel body fill color absent ({blueish}/{len(body_after)} blue-ish)"
    )
    # border ring: the nine-patch draws a light frame line along the panel
    # perimeter, distinct from the dark body interior. Scan the panel's LEFT
    # border column (leftmost pixel of the left-edge cells) down the panel
    # height; it must contain the light border color (not body, not wall). This
    # proves the box is FRAMED (a plain fill rect would have no border line).
    bx_left = PANEL_COL * 8           # leftmost pixel column of the panel
    y_top = yoff + PANEL_ROW * 8
    y_bot = yoff + (PANEL_ROW + PANEL_H) * 8
    def _is_border(p):
        r, g, b = p
        return (not _is_wall(p)) and (r + g + b) > 360  # light frame line
    left_border = sum(_is_border(after.getpixel((bx_left, y)))
                      for y in range(y_top, y_bot))
    assert left_border >= PANEL_H - 1, (
        f"panel left border not rendered ({left_border} light px over "
        f"{PANEL_H} cells)"
    )
    # and the top border row carries the light line too (a 3px band absorbs the
    # 1px overscan-offset ambiguity: count columns where ANY of the top 3 rows
    # of the panel is the border color).
    top_y = yoff + PANEL_ROW * 8
    top_border = sum(
        any(_is_border(after.getpixel((x, top_y + dy))) for dy in (-1, 0, 1))
        for x in range(PANEL_COL * 8, (PANEL_COL + PANEL_W) * 8)
    )
    assert top_border >= PANEL_W - 1, (
        f"panel top border not rendered ({top_border} light px)"
    )
    # text: the message contributes bright glyph pixels in the panel text row
    text_y = yoff + (PANEL_ROW + 2) * 8 + 3
    text_row = [after.getpixel((x, text_y))
                for x in range((PANEL_COL + 2) * 8, (PANEL_COL + PANEL_W - 2) * 8)]
    glyph_px = sum(1 for (r, g, b) in text_row if (r + g + b) > 300)
    assert glyph_px > 8, f"dialog text not visible inside panel ({glyph_px} px)"

    # --- CLOSE (B edge): scene fully restored ---
    _press(runner, b=True)
    assert runner.read_u16(WR, 0xE012) == 0, "close flag not cleared"
    closed = _shot(runner, "dialog_closed.png")
    yoff = _vert_offset(closed)
    assert not _panel_present(closed, yoff), "panel still visible after close"
    body_closed = _panel_body_pixels(closed, yoff)
    wall_closed = sum(_is_wall(p) for p in body_closed) / len(body_closed)
    assert wall_closed > 0.8, (
        f"scene not restored after close ({wall_closed:.2f} wall)"
    )
