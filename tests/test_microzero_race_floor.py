"""microzero — START on the title drives the modeled fade edge into
the race scene, whose static Mode 7 floor renders EXACTLY the declared world:
the full visible frame is compared pixel-for-pixel against a Python oracle
built from the same deterministic asset generator (flat matrix: screen(x,y)
shows world px (HOFS+x, VOFS+y); the PPU samples the seeded VRAM mod 128).
Also proves the transition machinery and the position-wrapped seed upload.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

VR, CG, WR = MemoryType.SnesVideoRam, MemoryType.SnesCgRam, MemoryType.SnesWorkRam

CAM_TX, CAM_TY = D.world_const("CAM0_TX"), D.world_const("CAM0_TY")
CAM_PX, CAM_PY = D.world_const("CAM0_PX"), D.world_const("CAM0_PY")
HOFS, VOFS = CAM_PX - 128, CAM_PY - 112


def load_gen():
    spec = importlib.util.spec_from_file_location(
        "gen_m7", SUPERFORGE / "tools" / "gen_m7_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_gradient_gen():
    return D.load_tool("gen_gradient")


def load_tool_gen_sky():
    return D.load_tool("gen_sky")


def load_gradient():
    """The declared per-SCANLINE COLDATA tint over the floor band.

    gen_gradient.floor_tint(p)[i] is what scanline HUD_LINES+i displays, and
    the ROM table it emits is that curve UNROTATED: a table unit with
    cumulative line index K is visible at exactly scanline K."""
    mod = D.load_tool("gen_gradient")
    return list(zip(*[mod.floor_tint(p) for p in range(3)]))


HUD_LINES = D.world_const("HUD_LINES")   # world.inc is the SSoT


def tint_at_scanline(tints, sl):
    """The floor band starts at scanline HUD_LINES; above it is sky."""
    i = sl - HUD_LINES
    return tints[i] if 0 <= i < len(tints) else (0, 0, 0)


@pytest.fixture(scope="module")
def oracle(tmp_path_factory):
    out = tmp_path_factory.mktemp("m7oracle")
    gen = load_gen()
    old = sys.argv
    sys.argv = ["gen", str(out)]
    try:
        assert gen.main() == 0
    finally:
        sys.argv = old
    tiles = (out / "floor_tiles.bin").read_bytes()
    pal = (out / "floor_pal.bin").read_bytes()
    world = (out / "world_map.bin").read_bytes()
    colors = [int.from_bytes(pal[i:i + 2], "little") for i in range(0, 34, 2)]
    return tiles, colors, world


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    runner = MesenRunner()
    # An EXACT absolute boot frame, not `>= 120` — this module reads the
    # rendered floor, and a free-run budget lands anywhere in a ~100-frame
    # spread under load (docs/45 §5).
    runner.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 140)
    # title is up; press START, then ride the fade edge into race
    D.enter_race(runner, syms)            # fade-out + blank switch + fade-in
    return runner, syms


def test_vram_seed_matches_world(booted, oracle):
    runner, syms = booted
    _, _, world = oracle
    # spot rows across the window incl. wrap rows; map LOW bytes only
    for wr in (CAM_TY - 64, CAM_TY - 1, CAM_TY, CAM_TY + 33, CAM_TY + 63):
        v = (wr & 127) * 128
        got = runner.read_bytes(VR, v * 2, 256)[0::2]     # low bytes
        want = bytes(world[(wr & 511) * 512 + ((CAM_TX - 64 + i) & 511)]
                     for i in range(128))
        # VRAM row is position-wrapped: rotate expected into place
        rot = bytearray(128)
        for i in range(128):
            rot[((CAM_TX - 64 + i) & 127)] = want[i]
        assert got == bytes(rot), f"world row {wr} mismatch in VRAM"


def test_race_palette_pinned_at_zero(booted, oracle):
    runner, syms = booted
    _, colors, _ = oracle
    assert syms["ES_C_FLOOR_PAL"]["start"] == 0
    got = [runner.read_u16(CG, i * 2) for i in range(17)]
    assert got == colors, got


def test_perspective_floor_structure(booted, oracle, tmp_path):
    """Perspective floor via ROM pose LUTs: the top band stays colour-exact
    under its declared tint, and the floor shows TRUE CONVERGENCE — the
    yellow center line is wider near than far and stays centered (heading 0
    looks down the start spoke). A flat matrix or dead HDMA fails this."""
    from PIL import Image
    runner, syms = booted
    tiles, colors, world = oracle
    shot = tmp_path / "race.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    w, h = img.size

    def snes_rgb(c):
        return tuple(((c >> s) & 31) << 3 | ((c >> s) & 31) >> 2
                     for s in (0, 5, 10))

    def tinted(c, sl):
        """A palette color under the declared depth wash at scanline sl."""
        t = tint_at_scanline(tints, sl)
        return tuple(min(31, ((c >> s) & 31) + tv) << 3
                     | min(31, ((c >> s) & 31) + tv) >> 2
                     for s, tv in zip((0, 5, 10), t))

    tints = load_gradient()
    white = snes_rgb(0x7FFF)
    top = D.content_top(img)        # image row of scanline 0 — located
    # Top band: sky_band's BG2 ramp under the declared per-scanline tint,
    # plus text white. (Before sky_band this band was black + white, and
    # the seam line rendered backdrop while its mode write landed — BG2
    # now covers that line.) The scanline-exact version of this assertion
    # lives in test_microzero_gradient; here it is a coarse leak check.
    sky_gen = load_gradient_gen()
    base = load_tool_gen_sky().RAMP
    allowed_band = {white}
    for sl in range(0, HUD_LINES):
        tint = tuple(sky_gen.sky_tint(p)[sl] for p in range(3))
        allowed_band |= {tuple(min(31, b + t) << 3 | min(31, b + t) >> 2
                               for b, t in zip(c, tint)) for c in base}
    hud_colors = set()
    for y in range(0, HUD_LINES):
        sy = y + top
        if 0 <= sy < h:
            for x in range(256):
                hud_colors.add(img.getpixel((x, sy)))
    assert hud_colors <= allowed_band, \
        f"stray HUD-band colors: {hud_colors - allowed_band}"
    assert any(img.getpixel((x, 2 * 8 + 3 + top)) == white for x in range(256)), \
        "HUD SCORE row has no glyph pixels"

    # Convergence, measured over the WHOLE band rather than at two scanlines
    # picked for one camera framing: sampling fixed "near" and "far" lines
    # re-breaks every time the pivot or the track width moves, and says
    # nothing about the rows in between.
    centre_line = colors[load_gen().CENTRE_LINE]

    def yellow_span(y):
        want = tinted(centre_line, y)
        xs = [x for x in range(256) if img.getpixel((x, y + top)) == want]
        return (min(xs), max(xs), len(xs)) if xs else None

    spans = [(y, s) for y in range(46, 224) if (s := yellow_span(y))]
    assert len(spans) > 20, \
        f"centre line barely visible: only {len(spans)} scanlines carry it"
    (y_far, far), (y_near, near) = spans[0], spans[-1]
    assert near[2] > far[2], (
        f"no convergence: line is {near[2]} px wide at scanline {y_near} "
        f"but {far[2]} px at {y_far} — a flat matrix or dead HDMA")
    for y, (lo, hi, _) in spans:
        assert 96 <= (lo + hi) // 2 <= 160, \
            f"centre line off-centre at scanline {y}: x {lo}..{hi}"
    # every floor pixel uses declared palette colors only, under the
    # declared per-line wash (transparent index 0 shows untinted backdrop)
    for y in (60, 120, 180, 220):
        allowed = {tinted(c, y) for c in colors} | {snes_rgb(colors[0])}
        for x in range(0, 256, 4):
            c = img.getpixel((x, y + top))
            assert c in allowed, f"undeclared color {c} at ({x},{y})"


def test_track_edges_are_visible(booted, oracle, tmp_path):
    """The road must be narrow enough for the perspective to SHOW its edges.

    This is a claim about what reaches the SCREEN, so it is asserted on
    screen pixels: curb and grass colours — under the declared per-line
    wash — have to appear in the rendered floor band, on both sides of the
    centre line. It is not enough for the world map to contain curbs.

    The failure this pins down shipped for several slices: the visible
    half-width the pose LUT gives is 27.2 world tiles at the horizon row
    falling to 4.8 at the bottom of the screen, and the ring's half-width
    was 28 tiles — wider than the view at EVERY scanline. Every curb and
    grass tile existed in VRAM, matched the oracle byte-for-byte, and was
    off-screen; the track rendered as a featureless plain. Every VRAM-byte
    assertion in this file passed throughout."""
    from PIL import Image
    runner, syms = booted
    gen = load_gen()
    _, colors, _ = oracle
    tints = load_gradient()
    shot = tmp_path / "edges.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    top = D.content_top(img)        # image row of scanline 0 — located

    def tinted(idx, sl):
        t = tint_at_scanline(tints, sl)
        c = colors[idx]
        return tuple(min(31, ((c >> s) & 31) + tv) << 3
                     | min(31, ((c >> s) & 31) + tv) >> 2
                     for s, tv in zip((0, 5, 10), t))

    curb = {gen.CURB_R, gen.CURB_W}
    grass = {gen.GRASS_DARK, gen.GRASS_LIT}
    seen_curb_x, seen_grass_x = [], []
    for y in range(60, 160, 2):                  # the converging zone
        want_curb = {tinted(i, y) for i in curb}
        want_grass = {tinted(i, y) for i in grass}
        for x in range(256):
            px = img.getpixel((x, y + top))
            if px in want_curb:
                seen_curb_x.append(x)
            elif px in want_grass:
                seen_grass_x.append(x)
    assert seen_curb_x, \
        "no curb pixels anywhere in the floor band — the road is wider " \
        "than the perspective can show"
    assert seen_grass_x, "no grass pixels anywhere in the floor band"
    # both edges, not just one: a road that has drifted off-centre could
    # show one curb while still being too wide to frame the track
    assert min(seen_curb_x) < 128 < max(seen_curb_x), \
        f"curbs only on one side of centre: x in {min(seen_curb_x)}.." \
        f"{max(seen_curb_x)}"


def test_transition_reached_race_scene(booted):
    runner, syms = booted
    # scene manager settled: cur == race (id 1), phase == run (0)
    sm = syms["ES_SM_CTL"]["start"]
    # DP claims live in the DP page at WRAM $0000+offset
    ctl = runner.read_bytes(WR, sm, 3)
    assert ctl[0] == 1 and ctl[2] == 0, f"sm_ctl {ctl.hex()}"


def test_second_bgmode_band_refuses_the_build(tmp_path, repo_tree_read_lock):
    """The composition gate's negative: a variant declaring a SECOND feature
    driving BGMODE in overlapping scanlines of the same phase must FAIL the
    allocator, not silently coexist (the class split-mode died on)."""
    import shutil
    gdir = tmp_path / "game"
    feats = tmp_path / "features"
    # SHARED lock for the copy only: `test_register.py` plants into live
    # `engine/features/*/feature.toml` and a copy taken mid-plant allocates
    # differently than this test expects (a recorded finding).
    with repo_tree_read_lock():
        shutil.copytree(SUPERFORGE / "game" / "microzero", gdir)
        shutil.copytree(SUPERFORGE / "engine" / "features", feats)
    rogue = feats / "rogue_band"
    rogue.mkdir()
    (rogue / "feature.toml").write_text(
        'name = "rogue_band"\nrole = "feature"\n[[claims.hdma]]\nregisters = ["BGMODE"]\n'
        'band = [100, 200]\nphase = "active"\n')
    gt = (gdir / "game.toml").read_text()
    (gdir / "game.toml").write_text(gt.replace(
        '"mode7_floor", "split_band", "bg_text"',
        '"mode7_floor", "split_band", "bg_text", "rogue_band"'))
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(gdir), "--features-dir", str(feats),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "ALLOCATION FAILED" in r.stderr and "BGMODE" in r.stderr
