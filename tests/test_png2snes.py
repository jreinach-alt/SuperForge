"""png2snes round-trip + validation gates.

Two layers, per the discipline (tests assert on real output, never a proxy):

  Unit (no emulator): the committed .inc fixtures regenerate byte-identically
  from the CC0 zips (drift guard between tool and committed artifacts); the
  AI-art pack REJECTS with the prescribed validation-first error; oversize
  content rejects with the right suggestion; the OBJ VRAM-grid layout is
  verified against an independently-authored synthetic image (quadrant tiles
  land at base+0/+1/+16/+17 — the hardware +16-row lesson).

  Emulator (round-trip): the converted art renders on hardware and the
  SCREENSHOT PIXELS match a PIL render of the SOURCE PNGs (BGR15-quantized,
  small shift search for the OBJ/BG line-offset quirks). The reference is
  derived from the source by an independent path — the 4bpp encoding, VRAM
  layout, palette grouping, and load macros are all under test.
"""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FIX = ROOT / "tests" / "fixtures" / "png2snes"
ART = ROOT / "examples" / "itch_cc0"
TOOL = ROOT / "tools" / "png2snes.py"
WR = MemoryType.SnesWorkRam

ZIPS = {
    "dungeon": "dungeonSprites_v1.0.zip",
    "camelot": "camelot_ [version 1.0].zip",
    "seasons": "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip",
    "ai": "SNES_overworld_RPG_character_sprite_top-down_persp.zip",
}


@pytest.fixture(scope="module")
def art(tmp_path_factory):
    """Extract the CC0 packs once. Skips if the zips aren't present."""
    if not ART.is_dir():
        pytest.skip(f"{ART} not present (art packs not materialized)")
    root = tmp_path_factory.mktemp("itch_cc0")
    out = {}
    for key, name in ZIPS.items():
        z = ART / name
        if not z.exists():
            pytest.skip(f"{z} missing")
        d = root / key
        with zipfile.ZipFile(z) as zf:
            zf.extractall(d)
        out[key] = d
    return out


def run_tool(*args):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True)


def strip_cmd(text):
    """Drop the '; cmd:' provenance line (paths differ across machines)."""
    return "\n".join(l for l in text.splitlines() if not l.startswith("; cmd:"))


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# ---------------------------------------------------------------------------
# unit: committed fixtures regenerate byte-identically (tool<->artifact drift)
# ---------------------------------------------------------------------------

def test_regen_hero16_fixture(art, tmp_path):
    src = art["dungeon"] / "dungeonSprites_v1.0" / "fHero_" / "idle_"
    out = tmp_path / "hero16.inc"
    r = run_tool("sprite", str(src), "--size", "16", "--name", "hero",
                 "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert strip_cmd(out.read_text()) == strip_cmd((FIX / "hero16.inc").read_text()), \
        "committed hero16.inc does not match a fresh conversion — regenerate it"


def test_regen_arthur32_fixture(art, tmp_path):
    src = art["camelot"] / "camelot_ [version 1.0]" / "arthurPendragon_.png"
    out = tmp_path / "arthur32.inc"
    r = run_tool("sprite", str(src), "--frame", "32x32", "--size", "32",
                 "--frames", "0-7", "--name", "arthur", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert strip_cmd(out.read_text()) == strip_cmd((FIX / "arthur32.inc").read_text())


def test_regen_terrain_bg_fixture(art, tmp_path):
    src = (art["seasons"] / "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels"
           / "four-seasons-tileset.png")
    out = tmp_path / "terrain_bg.inc"
    r = run_tool("bg", str(src), "--region", "0,0,64,48", "--name", "terrain",
                 "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert strip_cmd(out.read_text()) == strip_cmd((FIX / "terrain_bg.inc").read_text())


def test_regen_arthur_anim_fixture(art, tmp_path):
    """audit-1 (S2) F-1: the --anims fixture regenerates byte-identically."""
    src = art["camelot"] / "camelot_ [version 1.0]" / "arthurPendragon_.png"
    out = tmp_path / "arthur_anim.inc"
    r = run_tool("sprite", str(src), "--frame", "32x32", "--size", "32",
                 "--anims", "idle:0-3,run:8-11+16-19,hit:48-51",
                 "--name", "arthur", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert strip_cmd(out.read_text()) == strip_cmd(
        (FIX / "arthur_anim.inc").read_text())


def test_regen_brick_meta_fixture(tmp_path, tmp_path_factory):
    """audit-1 (S2) F-1: the --meta fixture regenerates byte-identically."""
    z = ART / "Four_Seasons_Platformer_Sprites.zip"
    if not z.exists():
        pytest.skip(f"{z} missing")
    d = tmp_path_factory.mktemp("fs")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    src = d / "Sprites [Enemies]" / "Brickhead" / "Brickhead_1" / "Attack"
    out = tmp_path / "brick_meta.inc"
    r = run_tool("sprite", str(src), "--meta", "--frames", "0-3",
                 "--name", "brick", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert strip_cmd(out.read_text()) == strip_cmd(
        (FIX / "brick_meta.inc").read_text())


def test_regen_brawler_assets(art, tmp_path):
    """audit-1 (S2) F-1: the brawler's committed assets regenerate cleanly."""
    cam = art["camelot"] / "camelot_ [version 1.0]"
    tdir = ROOT / "templates" / "brawler" / "assets"
    cases = [
        ("arthurPendragon_.png", "idle:0-3,run:8-11+16-19,hit:48-51",
         "arthur", "arthur.inc"),
        ("mordred_.png", "idle:8-11,run:16-19+24-27", "mordred", "mordred.inc"),
    ]
    for png, anims, name, fname in cases:
        out = tmp_path / fname
        r = run_tool("sprite", str(cam / png), "--frame", "32x32", "--size", "32",
                     "--anims", anims, "--name", name, "--out", str(out))
        assert r.returncode == 0, r.stderr
        assert strip_cmd(out.read_text()) == strip_cmd((tdir / fname).read_text()), \
            f"{fname} drifted from a fresh conversion"


# ---------------------------------------------------------------------------
# unit: validation-first errors
# ---------------------------------------------------------------------------

def test_ai_pack_rejects_with_actionable_error(art, tmp_path):
    """The canonical REJECT fixture: AI-generated 92x92 38-color 'pixel art'."""
    src = art["ai"] / "rotations" / "south.png"
    r = run_tool("sprite", str(src), "--name", "x", "--out", str(tmp_path / "x.inc"))
    assert r.returncode == 2
    err = r.stderr
    assert "REJECT" in err
    assert "38" in err and "15" in err, "error must quantify the color budget"
    assert "not hardware-scale pixel art" in err.lower() or \
           "not look like hardware-scale" in err.lower()
    assert "Options:" in err, "error must suggest fixes"
    assert "--auto-fix" in err
    assert not (tmp_path / "x.inc").exists(), "REJECT must not write output"


def test_oversize_content_rejects_with_size_suggestion(art, tmp_path):
    """knight jump frames have 17px-tall content — too big for a 16x16 box."""
    src = art["dungeon"] / "dungeonSprites_v1.0" / "knight_" / "jump_"
    r = run_tool("sprite", str(src), "--size", "16", "--name", "k",
                 "--out", str(tmp_path / "k.inc"))
    assert r.returncode == 2
    assert "REJECT" in r.stderr and "--size 32" in r.stderr
    assert "17" in r.stderr, "error must name the offending content size"


def test_full_tileset_groups_into_8_palettes(art, tmp_path):
    """The dissection's hard case: 525 tiles, greedy needs 9 palettes; the
    converter's best-fit + merge grouping must fit the hardware's 8."""
    src = (art["seasons"] / "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels"
           / "four-seasons-tileset.png")
    out = tmp_path / "full.inc"
    r = run_tool("bg", str(src), "--name", "full", "--out", str(out))
    assert r.returncode == 0, f"full tileset should fit 8 palettes:\n{r.stderr}"
    text = out.read_text()
    assert "full_pal_count = 8" in text or any(
        f"full_pal_count = {n}" in text for n in range(1, 9))


def test_region_out_of_bounds_rejects(art, tmp_path):
    """audit-1 F-3: an off-the-edge --region must reject, not convert blank."""
    src = (art["seasons"] / "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels"
           / "four-seasons-tileset.png")
    r = run_tool("bg", str(src), "--region", "160,240,64,48", "--name", "x",
                 "--out", str(tmp_path / "x.inc"))
    assert r.returncode == 2
    assert "past the image edge" in r.stderr and "176x256" in r.stderr


def test_multiframe_autofix_shares_one_palette(tmp_path):
    """audit-1 F-1: --auto-fix on a multi-frame set whose UNION exceeds 15
    colors must quantize to ONE shared palette (not crash in the encoder)."""
    src = tmp_path / "frames"
    src.mkdir()
    for f in range(3):                       # 3 frames x 8 colors = 24 union
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        for i in range(8):
            c = (f * 80 + i * 9, 255 - f * 60 - i * 7, (f * 37 + i * 23) % 255, 255)
            for y in range(2):
                for x in range(16):
                    img.putpixel((x, i * 2 + y), c)
        img.save(src / f"frame_{f}.png")
    out = tmp_path / "af.inc"
    r = run_tool("sprite", str(src), "--size", "16", "--name", "af",
                 "--out", str(out), "--auto-fix")
    assert r.returncode == 0, f"auto-fix crashed:\n{r.stderr}"
    assert "[auto-fix]" in r.stderr and "preview" in r.stderr
    text = out.read_text()
    pal_colors = int(next(l for l in text.splitlines()
                          if l.startswith("af_pal_colors")).split("=")[1])
    assert pal_colors <= 16, "shared auto-fix palette still over budget"
    assert (tmp_path / "af.preview.png").exists(), "auto-fix must write a preview"


def test_frame_files_sort_naturally(tmp_path):
    """audit-1 F-2: frame_10 must follow frame_9 (natural sort), or every
    >=10-frame animation's table plays out of order."""
    src = tmp_path / "anim"
    src.mkdir()
    n = 12
    for f in range(n):                       # brightness encodes frame order
        img = Image.new("RGBA", (8, 8), (f * 20 + 8,) * 3 + (255,))
        img.save(src / f"frame_{f}.png")
    out = tmp_path / "ns.inc"
    r = run_tool("sprite", str(src), "--size", "8", "--name", "ns", "--out", str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text()
    blob = parse_chr_blob(text, "ns_chr")
    # palette is luminance-sorted, so frame f (brightness rank f) must encode
    # as uniform index f+1 in tile f — any sort shuffle breaks the sequence
    for f in range(n):
        vals = {v for row in decode_4bpp_tile(blob, f) for v in row}
        assert vals == {f + 1}, (
            f"tile {f} holds palette indices {vals}, expected {{{f + 1}}} — "
            "frame files are not in natural order")


def test_anims_spec_rejects_are_actionable(art, tmp_path):
    """audit-1 (S2) F-3/F-4: --anims malformed/reversed/out-of-range specs."""
    src = art["camelot"] / "camelot_ [version 1.0]" / "arthurPendragon_.png"
    base = ["sprite", str(src), "--frame", "32x32", "--size", "32",
            "--name", "x", "--out", str(tmp_path / "x.inc"), "--anims"]
    r = run_tool(*base, "idle")                      # no colon
    assert r.returncode == 2 and "name:A-B" in r.stderr
    r = run_tool(*base, "idle:3-0")                  # reversed
    assert r.returncode == 2 and "reversed range" in r.stderr \
        and "0-3" in r.stderr
    r = run_tool(*base, "idle:60-99")                # out of bounds
    assert r.returncode == 2 and "out of bounds" in r.stderr \
        and "64" in r.stderr


def test_meta_rejects_oversize_content(tmp_path):
    """audit-1 (S2) F-4: --meta content beyond the 64x64 box rejects."""
    img = Image.new("RGBA", (96, 96), (200, 40, 40, 255))
    src = tmp_path / "huge.png"
    img.save(src)
    r = run_tool("sprite", str(src), "--meta", "--name", "x",
                 "--out", str(tmp_path / "x.inc"))
    assert r.returncode == 2
    assert "REJECT" in r.stderr and "64x64" in r.stderr and "96x96" in r.stderr


# ---------------------------------------------------------------------------
# unit: OBJ VRAM-grid ground truth (independent synthetic image)
# ---------------------------------------------------------------------------

def decode_4bpp_tile(blob, tile_idx):
    """Independent 4bpp planar decoder (test-side ground truth)."""
    t = blob[tile_idx * 32:(tile_idx + 1) * 32]
    rows = []
    for y in range(8):
        b0, b1 = t[y * 2], t[y * 2 + 1]
        b2, b3 = t[16 + y * 2], t[16 + y * 2 + 1]
        row = []
        for x in range(8):
            bit = 7 - x
            row.append(((b0 >> bit) & 1) | (((b1 >> bit) & 1) << 1)
                       | (((b2 >> bit) & 1) << 2) | (((b3 >> bit) & 1) << 3))
        rows.append(row)
    return rows


def parse_chr_blob(inc_text, label):
    lines = inc_text.splitlines()
    i = next(n for n, l in enumerate(lines) if l.strip() == f"{label}:")
    blob = bytearray()
    for l in lines[i + 1:]:
        l = l.strip()
        if not l.startswith(".byte"):
            break
        blob.extend(int(v.strip().lstrip("$"), 16) for v in l[5:].split(","))
    return bytes(blob)


def test_16x16_quadrants_land_on_vram_grid(tmp_path):
    """A 16x16 frame's four 8x8 quadrants must land at tiles base+0, +1,
    +16, +17 — the hardware's +16-row layout, independently authored here."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    quads = {(0, 0): (255, 0, 0), (8, 0): (0, 255, 0),
             (0, 8): (0, 0, 255), (8, 8): (255, 255, 0)}
    for (qx, qy), c in quads.items():
        for y in range(8):
            for x in range(8):
                img.putpixel((qx + x, qy + y), c + (255,))
    src = tmp_path / "quad.png"
    img.save(src)
    out = tmp_path / "quad.inc"
    r = run_tool("sprite", str(src), "--size", "16", "--name", "q", "--out", str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text()
    blob = parse_chr_blob(text, "q_chr")
    assert len(blob) == 2 * 16 * 32, "one 16x16 frame occupies 2 VRAM rows"
    # each quadrant tile must be a uniform nonzero index; all four distinct
    got = {}
    for pos, tile in (((0, 0), 0), ((8, 0), 1), ((0, 8), 16), ((8, 8), 17)):
        rows = decode_4bpp_tile(blob, tile)
        vals = {v for row in rows for v in row}
        assert len(vals) == 1 and 0 not in vals, \
            f"tile {tile} should be one uniform color, got indices {vals}"
        got[pos] = vals.pop()
    assert len(set(got.values())) == 4, "quadrants must keep distinct colors"
    # the in-between tiles of row 0 (2..15) must be empty padding
    for tile in (2, 5, 15, 18):
        rows = decode_4bpp_tile(blob, tile)
        assert all(v == 0 for row in rows for v in row), f"tile {tile} not padding"


# ---------------------------------------------------------------------------
# emulator round-trips: converted art renders pixel-faithful to the source
# ---------------------------------------------------------------------------

def bgr15_quantize(rgb):
    """The display value after 15-bit quantization (5-bit channel -> 8-bit)."""
    return tuple(((v >> 3) << 3) | (v >> 5) for v in rgb)


def render_reference_sprite(img, size, anchor="center"):
    """Independent re-render of a source frame: content re-centered into the
    OBJ box, opaque pixels BGR15-quantized; returns (size x size RGBA)."""
    if img.size != (size, size):
        a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bbox = a.getbbox()
        content = img.crop(bbox)
        cw, ch = content.size
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ox = (size - cw) // 2
        oy = (size - ch) if anchor == "bottom" else (size - ch) // 2
        out.paste(content, (ox, oy))
        img = out
    q = Image.new("RGBA", img.size)
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            p = img.getpixel((x, y))
            q.putpixel((x, y), bgr15_quantize(p[:3]) + (255,) if p[3] >= 128
                       else (0, 0, 0, 0))
    return q


def best_shift_match(shot, ref, sx, sy, tol=14):
    """Compare a screenshot region at (sx,sy) against an RGBA reference,
    over a small global shift search: Mesen screenshots are 256x239 with a
    few border lines on top (~+6 measured), plus the hardware's OBJ/BG
    one-line offsets. Returns the best opaque-pixel match ratio — a layout/
    palette/encode bug fails catastrophically at every shift, so the search
    cannot mask one."""
    best = 0.0
    w, h = ref.size
    for dy in range(-2, 9):
        for dx in range(-2, 3):
            total = match = 0
            for y in range(h):
                for x in range(w):
                    rp = ref.getpixel((x, y))
                    if rp[3] < 128:
                        continue
                    total += 1
                    px, py = sx + x + dx, sy + y + dy
                    if not (0 <= px < shot.size[0] and 0 <= py < shot.size[1]):
                        continue
                    sp = shot.getpixel((px, py))
                    if all(abs(sp[i] - rp[i]) <= tol for i in range(3)):
                        match += 1
            if total and match / total > best:
                best = match / total
    return best


def _shot(runner, rom, path="/tmp/_png2snes_shot.png"):
    p = BUILD / rom
    assert p.exists(), f"{p} not built — run `make {rom.split('.')[0]}`"
    runner.load_rom(str(p), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "ROM did not boot"
    assert runner.read_u16(WR, 0xE008) == 1, "ROM did not reach the frame loop"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB")


def test_sprite_roundtrip_on_emulator(art, runner):
    """hero (16x16, re-centered P-mode frames) and arthur (32x32 RGBA sheet)
    both render pixel-faithful to their SOURCE PNGs."""
    shot = _shot(runner, "png2snes_sprite_test.sfc")
    hero_src = load = Image.open(
        art["dungeon"] / "dungeonSprites_v1.0" / "fHero_" / "idle_" / "lIdle_0.png"
    ).convert("RGBA")
    hero_ref = render_reference_sprite(hero_src, 16)
    ratio = best_shift_match(shot, hero_ref, 60, 80)
    assert ratio >= 0.99, f"hero sprite mismatch vs source render ({ratio:.0%})"

    arthur_sheet = Image.open(
        art["camelot"] / "camelot_ [version 1.0]" / "arthurPendragon_.png"
    ).convert("RGBA")
    arthur_ref = render_reference_sprite(arthur_sheet.crop((0, 0, 32, 32)), 32)
    ratio = best_shift_match(shot, arthur_ref, 120, 80)
    assert ratio >= 0.99, f"arthur sprite mismatch vs source render ({ratio:.0%})"


def test_bg_roundtrip_on_emulator(art, runner):
    """The converted Four Seasons patch renders pixel-faithful to the source
    region — palette grouping, dedupe, map words, and loaders all correct."""
    shot = _shot(runner, "png2snes_bg_test.sfc")
    src = Image.open(
        art["seasons"] / "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels"
        / "four-seasons-tileset.png"
    ).convert("RGBA").crop((0, 0, 64, 48))
    ref = Image.new("RGBA", src.size)
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            p = src.getpixel((x, y))
            ref.putpixel((x, y), bgr15_quantize(p[:3]) + (255,) if p[3] >= 128
                         else (0, 0, 0, 0))
    ratio = best_shift_match(shot, ref, 32, 32)
    assert ratio >= 0.99, f"BG patch mismatch vs source render ({ratio:.0%})"
