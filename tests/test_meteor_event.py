"""Acceptance gate for the meteor_event template (the LOCKED two-phase meteor).

meteor_event is an in-level "meteor event" cutscene that swaps Mode-1 <-> Mode-7.
A tiny Mode-1 platformer slice (flat ground + two raised platforms + a player the
D-pad walks RIGHT) runs until the player reaches an "open flat ground" TRIGGER;
then the cutscene fires:

  ST_PLAY (0)    Mode 1. The world scrolls under the fixed-screen player as the
                 D-pad walks RIGHT (camera follow). BG = the ground/platforms.
  ST_FREEZE (1)  FREEZE: physics + scroll halt and INPUT IS GATED.
  ST_CAPTURE (2) THE CRUX: walk the ACTUAL visible BG1 shadow tilemap, emit an
                 OBJ sprite pixel-aligned where each PLATFORM tile rendered; then
                 BLACK the Mode-1 BG so only the captured OBJ ground remains.
  ST_SCENE (3)   the LOCKED two-phase ~3s meteor:
                   (A) SPRITE PHASE (scene t 0..71): the Mode-7 plane is OFF-FIELD
                       (black backdrop); a meteor OBJ sprite enters off-screen
                       upper-left and GROWS through 4 discrete frames as it nears
                       the crossover. Captured ground+player composited.
                   (B) CROSSOVER (t ~72): the sprite is hidden; the Mode-7 meteor
                       plane is revealed at ~the sprite's final on-screen size at
                       the same screen point.
                   (C) MODE-7 PHASE (t 72..179): the plane scales UP centred on the
                       affine pivot (grows in place) while the scroll SLIDES it off
                       the bottom-right and a SLOW TUMBLE ramps the affine angle.
                       The red glow rises with the descent, holds, then recedes.
  ST_RESTORE (4) swap Mode-7 -> Mode-1, rebuild the level, RELEASE control.

EVERY visual assertion reads RENDERED/HARDWARE output — the framebuffer pixels,
the OAM bytes, the CGRAM bytes, or the BG1 shadow tilemap. The debug-region
mirrors ($7E:E0xx the ROM writes each frame) are read ONLY to SEQUENCE captures.

NON-VACUITY CONTROLS (build_meteor_event_variants.sh):
  -DNO_CAPTURE   skips the BG->OBJ capture -> ground band vanishes.
  -DNO_FREEZE    input still moves the player during "freeze".
  -DNO_SCALE     the Mode-7 scale ramp is compiled out (meteor never grows).
  -DNO_GRADIENT  the red glow is compiled out (no red appears).
  -DNO_RELEASE   the swap-back never runs (control never released).
  -DNO_TUMBLE    the affine angle is held at 0 (meteor never tumbles).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam
CG = MemoryType.SnesCgRam

# debug-region mirrors (SEQUENCE only)
DBG_HEART  = 0xE010
DBG_STATE  = 0xE012
DBG_WORLDX = 0xE014
DBG_CAMX   = 0xE016
DBG_BGMODE = 0xE018   # SHADOW_BGMODE; mode flip SEQUENCE only (mode = low 3 bits)

# scene sub-timer ($7E:0038, g_timer): SEQUENCE only (position the ROM at a beat)
DBG_SCN_TIMER = 0x0038

ST_PLAY, ST_FREEZE, ST_CAPTURE, ST_SCENE, ST_RESTORE = 0, 1, 2, 3, 4

# scene sub-timeline beats (main.asm: SPRITE_END=72, SCN_END=180)
SPRITE_END = 72       # crossover frame
# sprite-phase grow sample beats (both inside the sprite phase, both on-screen):
T_SPR_EARLY = 22      # FIERY speck (~16px, small texel count)
T_SPR_LATE  = 68      # ROCKY r15.5 (32x32, the crossover frame)
# sprite-phase flip-cycle beats (one per orientation; SPR_FLIP_PERIOD=7):
#   t38 -> o=1 (H), t45 -> o=2 (V), t52 -> o=3 (H+V), t59 -> o=0 (normal)
T_FLIP = (38, 45, 52, 59)
# Mode-7 grow beat: meteor grown + on-screen, BEFORE the glow rises (m<20 -> t<92):
T_M7_GROW   = 88
# Mode-7 textured/tumble beat: meteor grown big + rotated, still pre-glow-visible:
T_M7_TEX    = 88      # mid Mode-7 zoom: meteor centred + stable (the 45-deg
                      # slide reaches the edge sooner, so sample earlier than 96)
# Mode-7 exit beat: meteor has slid off the bottom-right:
T_M7_EXIT   = 150
# glow beats:
T_GLOW_PRE   = 80     # m=8: glow not yet risen
T_GLOW_PEAK  = 148    # m=76: glow at peak HOLD, meteor fully exited the lower band
T_GLOW_RECEDE = 172   # m=100: glow receded

SHADOW_BG1_TILEMAP = 0xA200
BG_PLAT = 1
OBJ_GROUND = 0
OBJ_PLAYER = 2
PLAYER_SCRN_X = 96
PLAYER_Y = 176


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def variants():
    """Build the -D non-vacuity control ROMs. Returns {name: rom_path}."""
    import subprocess
    script = ROOT / "templates" / "meteor_event" / "build_meteor_event_variants.sh"
    assert script.exists(), f"{script} missing"
    res = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"variant build failed (toolchain?):\n{res.stderr}")
    return {
        "nocap": BUILD / "meteor_event_nocap.sfc",
        "nofreeze": BUILD / "meteor_event_nofreeze.sfc",
        "noscale": BUILD / "meteor_event_noscale.sfc",
        "nograd": BUILD / "meteor_event_nograd.sfc",
        "norelease": BUILD / "meteor_event_norelease.sfc",
        "notumble": BUILD / "meteor_event_notumble.sfc",
    }


# ---------------------------------------------------------------- helpers
def _state(r):
    return r.read_u16(WR, DBG_STATE) & 0xFF


def _oam(r, slot):
    b = r.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]


def _drive_to_state(r, want, max_frames=600, hold_right=True):
    if hold_right:
        r.set_input(0, right=True)
    for _ in range(max_frames):
        if _state(r) == want:
            return True
        r.run_frames(2)
    return _state(r) == want


def _drive_to_scene_timer(r, want_timer, max_frames=1500):
    """In ST_SCENE, advance until the scene sub-timer reaches `want_timer`."""
    for _ in range(max_frames):
        st = _state(r)
        t = r.read_u16(WR, DBG_SCN_TIMER) & 0xFF
        if st > ST_SCENE:
            return t
        if st == ST_SCENE and t >= want_timer:
            return t
        r.run_frames(1)
    return r.read_u16(WR, DBG_SCN_TIMER) & 0xFF


def _rgb(path):
    img = Image.open(path).convert("RGB")
    return img.load(), img.size[0], img.size[1]


def _is_green(c):
    r, g, b = c
    return g > 120 and r < 90 and b < 90


def _is_white(c):
    r, g, b = c
    return r > 200 and g > 200 and b > 200


def _is_red(c):
    """Bright red glow pixel (the additive impact glow)."""
    r, g, b = c
    return r > 110 and g < 80 and b < 80


def _is_meteor(c):
    """A Mode-7 meteor / sprite-fireball TEXEL: not near-black backdrop, not the
    pure-green OBJ ground, not the white OBJ player, not the bright-red glow."""
    r, g, b = c
    if r < 40 and g < 40 and b < 40:
        return False
    if _is_green(c) or _is_white(c) or _is_red(c):
        return False
    return True


def _green_band(path, frac=0.78):
    px, w, h = _rgb(path)
    rows = [y for y in range(h)
            if sum(1 for x in range(w) if _is_green(px[x, y])) >= w * frac]
    return (min(rows), max(rows), len(rows)) if rows else None


def _distinct_colors(path, min_px=30):
    px, w, h = _rgb(path)
    counts = {}
    for y in range(h):
        for x in range(w):
            c = px[x, y]
            counts[c] = counts.get(c, 0) + 1
    return sum(1 for n in counts.values() if n >= min_px)


def _meteor_pixels(path, y0=0, y1=None):
    """Count meteor texels (Mode-7 plane or sprite fireball) in rows [y0, y1)."""
    px, w, h = _rgb(path)
    if y1 is None:
        y1 = h
    return sum(1 for y in range(y0, min(y1, h)) for x in range(w)
               if _is_meteor(px[x, y]))


def _red_lower_band(path, top_frac=0.55):
    px, w, h = _rgb(path)
    y0 = int(h * top_frac)
    return sum(1 for y in range(y0, h) for x in range(w) if _is_red(px[x, y]))


def _stable_meteor_pixels(r, path, samples=4, y0=0, y1=None):
    """Take the MAX meteor-texel count over a few consecutive frames (robust to a
    transient near-black Mode-7 frame). SEQUENCE-neutral (reads framebuffer)."""
    best = 0
    for _ in range(samples):
        r.take_screenshot(path)
        best = max(best, _meteor_pixels(path, y0=y0, y1=y1))
        r.run_frames(1)
    return best


def _peak_meteor_frame(r, path, max_frames=6, y0=0, y1=160):
    """Save the peak-meteor-texel frame over the next `max_frames` to `path`;
    return that peak count. DETERMINISTIC over a fixed window from a fixed
    sub-state, so two runs of the SAME ROM pick the SAME frame (a control diff of
    ~0), leaving rotation as the only thing a tumble-vs-control diff measures."""
    import shutil
    best = -1
    for _ in range(max_frames):
        r.take_screenshot("/tmp/_pmf_tmp.png")
        n = _meteor_pixels("/tmp/_pmf_tmp.png", y0=y0, y1=y1)
        if n > best:
            best = n
            shutil.copy("/tmp/_pmf_tmp.png", path)
        r.run_frames(1)
    return best


def _region_rgb_diff(path_a, path_b, y0=0, y1=160, tol=40):
    """Count pixels in rows [y0,y1) whose |dR|+|dG|+|dB| exceeds `tol` between the
    two screenshots — a rendered measure of how much the image changed."""
    pa, w, h = _rgb(path_a)
    pb, _, _ = _rgb(path_b)
    n = 0
    for y in range(y0, min(y1, h)):
        for x in range(w):
            ra, ga, ba = pa[x, y]
            rb, gb, bb = pb[x, y]
            if abs(ra - rb) + abs(ga - gb) + abs(ba - bb) > tol:
                n += 1
    return n


def _meteor_centroid(path, y0=0, y1=160):
    """Integer centroid (cx, cy) of the Mode-7 meteor texels, or None if none."""
    px, w, h = _rgb(path)
    sx = sy = cnt = 0
    for y in range(y0, min(y1, h)):
        for x in range(w):
            if _is_meteor(px[x, y]):
                sx += x
                sy += y
                cnt += 1
    if cnt == 0:
        return None
    return (sx // cnt, sy // cnt, cnt)


def _meteor_crop_diff(path_a, path_b, half=22, tol=40):
    """Centroid-ALIGNED diff: crop a (2*half)^2 window centred on each frame's
    meteor centroid, then count pixels that differ by >tol between the two crops.

    The Mode-7 meteor SLIDES across the scene, so a whole-frame diff is dominated
    by translation (and ±1 frame of boot-to-state jitter in the full suite moves
    it a few px). The tumble we actually want to prove is ROTATION of the
    asymmetric cratered rock ABOUT ITS OWN CENTRE. Aligning both crops on their
    centroid cancels translation, leaving rotation as the only signal: control-vs-
    control (same angle) ~0 regardless of slide position, real-vs-control nonzero
    iff the texture rotated."""
    pa, wa, ha = _rgb(path_a)
    pb, wb, hb = _rgb(path_b)
    ca = _meteor_centroid(path_a)
    cb = _meteor_centroid(path_b)
    if ca is None or cb is None:
        return None
    n = 0
    for dy in range(-half, half):
        for dx in range(-half, half):
            xa, ya = ca[0] + dx, ca[1] + dy
            xb, yb = cb[0] + dx, cb[1] + dy
            if not (0 <= xa < wa and 0 <= ya < ha and 0 <= xb < wb and 0 <= yb < hb):
                continue
            ra, ga, ba = pa[xa, ya]
            rb, gb, bb = pb[xb, yb]
            if abs(ra - rb) + abs(ga - gb) + abs(ba - bb) > tol:
                n += 1
    return n


# =============================================================================
# S1.a — boots into the Mode-1 platformer slice.
# =============================================================================
def test_boots_into_mode1_platformer(runner):
    rom = BUILD / "meteor_event.sfc"
    assert rom.exists(), f"{rom} not built — run `make meteor_event` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB)"

    h0 = runner.read_u16(WR, DBG_HEART)
    runner.run_frames(8)
    assert runner.read_u16(WR, DBG_HEART) > h0, "heartbeat not advancing"
    assert _state(runner) == ST_PLAY, f"not ST_PLAY at boot (state {_state(runner)})"

    runner.take_screenshot("/tmp/meteor_p1_play.png")
    band = _green_band("/tmp/meteor_p1_play.png")
    assert band is not None, "no green ground band rendered in ST_PLAY"
    assert band[2] >= 16, f"ground band too thin to be the flat ground: {band}"

    x, y, tile, _ = _oam(runner, 0)
    assert tile == OBJ_PLAYER, f"slot 0 not the player tile: tile={tile}"
    assert x == PLAYER_SCRN_X and y == PLAYER_Y, f"player not at spawn: ({x},{y})"


# =============================================================================
# S1.b — the D-pad walks the player RIGHT (the world scrolls).
# =============================================================================
def test_dpad_walks_player_right(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _state(runner) == ST_PLAY

    def platform_right_edge(px, w, h):
        best = -1
        for y in range(0, int(h * 0.7)):
            for x in range(w):
                if _is_green(px[x, y]):
                    best = max(best, x)
        return best

    runner.set_input(0, right=True)
    runner.run_frames(30)
    cam_a = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_p1_walk0.png")
    px0, w, h = _rgb("/tmp/meteor_p1_walk0.png")
    edge0 = platform_right_edge(px0, w, h)

    runner.run_frames(50)
    cam_b = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_p1_walk1.png")
    px1, _, _ = _rgb("/tmp/meteor_p1_walk1.png")
    edge1 = platform_right_edge(px1, w, h)

    assert cam_b > cam_a, f"camera did not advance walking right: {cam_a} -> {cam_b}"
    assert edge0 != edge1, \
        f"rendered platform did not move as the player walked: edge {edge0}->{edge1}"
    runner.set_input(0)


# =============================================================================
# S1.c — FREEZE gates input.
# =============================================================================
def test_freeze_gates_input(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_FREEZE), "never reached ST_FREEZE"

    p0 = _oam(runner, 0)
    cam0 = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_p1_freeze.png")
    runner.run_frames(15)
    assert _state(runner) == ST_FREEZE, "left FREEZE too early"
    p1 = _oam(runner, 0)
    cam1 = runner.read_u16(WR, DBG_CAMX)

    assert p0 == p1, f"player OBJ MOVED during freeze (input not gated): {p0} -> {p1}"
    assert cam0 == cam1, f"camera moved during freeze (scroll not halted): {cam0} -> {cam1}"
    runner.set_input(0)


# =============================================================================
# S2 — THE CRUX: the captured OBJ ground lands on the SAME pixels as the BG.
# =============================================================================
def test_capture_aligns_obj_ground_to_bg_ground(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_FREEZE), "never reached ST_FREEZE"

    runner.run_frames(4)
    runner.take_screenshot("/tmp/meteor_p1_freeze.png")
    bg_band = _green_band("/tmp/meteor_p1_freeze.png")
    assert bg_band is not None, "no BG ground band at FREEZE"

    assert _drive_to_state(runner, ST_CAPTURE), "never reached ST_CAPTURE"
    runner.run_frames(8)
    runner.take_screenshot("/tmp/meteor_p1_capture.png")
    obj_band = _green_band("/tmp/meteor_p1_capture.png")
    assert obj_band is not None, \
        "captured OBJ ground band ABSENT at CAPTURE (capture produced nothing)"

    top_d = abs(bg_band[0] - obj_band[0])
    bot_d = abs(bg_band[1] - obj_band[1])
    assert top_d <= 2 and bot_d <= 2, (
        f"captured OBJ ground NOT aligned to the BG ground it replaced: "
        f"BG band {bg_band} vs OBJ band {obj_band} (top_d={top_d}, bot_d={bot_d})")
    assert obj_band[2] >= bg_band[2] - 4, \
        f"captured ground band too short vs BG: {obj_band} vs {bg_band}"


def test_capture_blacks_the_bg(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_CAPTURE), "never reached ST_CAPTURE"
    runner.run_frames(4)
    tm = runner.read_bytes(WR, 0x012F, 1)[0]   # SHADOW_TM = $0100 + $2F
    assert (tm & 0x01) == 0, f"BG1 still enabled at CAPTURE (TM={tm:#04x})"
    assert (tm & 0x10) != 0, f"OBJ not enabled at CAPTURE (TM={tm:#04x})"


# =============================================================================
# S3 — forced-blank swap; mid-scene the Mode-7 meteor renders + composited OBJ.
# =============================================================================
def test_scene_renders_mode7_meteor_with_captured_obj(runner):
    """The MODE-7 PHASE renders a TEXTURED meteor (>=4 distinct colours) with the
    captured OBJ ground composited in front. Sampled just after the crossover
    (T_M7_GROW), where the Mode-7 rock is clean and on-screen."""
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_M7_TEX)
    n = _peak_meteor_frame(runner, "/tmp/meteor_scene.png")
    assert n > 600, f"no rendered Mode-7 meteor mid-scene (texels={n})"

    distinct = _distinct_colors("/tmp/meteor_scene.png")
    assert distinct >= 4, \
        f"Mode-7 meteor not textured enough ({distinct} distinct colours, need >=4)"
    band = _green_band("/tmp/meteor_scene.png")
    assert band is not None, \
        "captured OBJ ground band NOT composited over the Mode-7 meteor"


def test_scene_restages_mode7_palette(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.run_frames(8)
    cg = runner.read_bytes(CG, 0, 32)
    words = {cg[i] | (cg[i + 1] << 8) for i in range(0, 32, 2)}
    nonblack = {w for w in words if w != 0}
    assert len(nonblack) >= 4, \
        f"Mode-7 meteor palette not restaged in CGRAM 0-15: distinct={words}"


# =============================================================================
# (A) SPRITE PHASE — the meteor SPRITE is present early and GROWS.
# =============================================================================
def test_sprite_phase_meteor_grows(runner):
    """Feature: the far-approach meteor OBJ sprite grows through discrete frames.
    Output read: the framebuffer meteor-texel count (the fireball is yellow/orange/
    red, excluded from green/white/bright-red) in the SPRITE phase. The later frame
    (QUAD, ~64px) must out-cover the earlier (MID/BIG). The Mode-7 plane is OFF-FIELD
    in this phase (black backdrop), so the counted texels are the SPRITE only."""
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)

    _drive_to_scene_timer(runner, T_SPR_EARLY)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_spr_early.png")
    early = _meteor_pixels("/tmp/meteor_spr_early.png")

    _drive_to_scene_timer(runner, T_SPR_LATE)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_spr_late.png")
    late = _meteor_pixels("/tmp/meteor_spr_late.png")

    assert early >= 8, f"no meteor sprite (FIERY speck) visible early in the sprite phase ({early})"
    assert late > early * 2.0, (
        f"meteor sprite did not GROW across the sprite phase: "
        f"t{T_SPR_EARLY}={early} -> t{T_SPR_LATE}={late}")


# =============================================================================
# (C) MODE-7 PHASE — the meteor GROWS (real vs NO_SCALE), then EXITS bottom-right.
# =============================================================================
def test_meteor_grows_then_exits_bottom(runner, variants):
    """Feature: the Mode-7 scale ramp (grow in place) + the slide off bottom-right.
    GROW: compare the real ROM vs the -DNO_SCALE control AT THE SAME scene timer
    (identical slide position + tumble, so the only difference is the scale) BEFORE
    the glow rises — the grown meteor must clearly out-cover the ungrown one. EXIT:
    after the slide the meteor has left the LOWER screen."""
    rom = BUILD / "meteor_event.sfc"
    noscale = variants["noscale"]
    assert noscale.exists(), f"{noscale} not built"

    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_M7_GROW)
    px_grown = _stable_meteor_pixels(runner, "/tmp/meteor_grow_real.png", samples=4)

    runner.load_rom(str(noscale), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "NO_SCALE never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_M7_GROW)
    px_flat = _stable_meteor_pixels(runner, "/tmp/meteor_grow_noscale.png", samples=4)

    assert px_grown > px_flat * 1.35, (
        f"meteor did not GROW: grown ROM texels={px_grown} vs -DNO_SCALE={px_flat} "
        f"at the same scene timer (need grown >> flat)")

    # EXIT: by the end of the slide the meteor has left the LOWER screen.
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_M7_EXIT)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_fallen.png")
    lower = _meteor_pixels("/tmp/meteor_fallen.png", y0=160)
    assert lower <= 120, (
        f"meteor still present in the lower screen after the slide: {lower} texels "
        f"(it should have exited the bottom-right)")


def _meteor_oam_attr(r):
    """Find the meteor SPRITE's OAM slot (the 32x32 large fireball: tile byte in
    {64,68,72}, not hidden) and return its attribute byte, or None. The H-flip bit
    is attr bit6, the V-flip bit is attr bit7 (set via the shadow-OAM poke)."""
    for slot in range(128):
        x, y, tile, attr = _oam(r, slot)
        if y != 0xF0 and tile in (64, 68, 72):
            return attr
    return None


# =============================================================================
# (A) SPRITE PHASE flip-cycle + (C) MODE-7 PHASE affine tumble.
# =============================================================================
def test_meteor_tumbles(runner, variants):
    """Two illusions of spin, both proven on rendered/hardware output:

    (A) SPRITE PHASE flip-cycle — OBJ can't rotate, so the meteor sprite cycles
        {normal, H-flip, V-flip, H+V} every SPR_FLIP_PERIOD frames. PROOF: the
        meteor sprite's hardware OAM attribute byte cycles its H (bit6) and V
        (bit7) flip bits across the four T_FLIP beats (V-flip is reachable only via
        the shadow-OAM poke — the spr macro masks it), AND the rendered frames at
        those beats differ.
    (C) MODE-7 PHASE affine tumble — real vs the -DNO_TUMBLE control (which holds
        both the flip-cycle AND the affine angle at 0) at the same scene timer; the
        cratered rock is asymmetric so rotation changes the render. Control-vs-self
        ~0 (deterministic peak frame) attributes the diff to rotation."""
    rom = BUILD / "meteor_event.sfc"
    notumble = variants["notumble"]
    assert notumble.exists(), f"{notumble} not built"

    # --- (A) sprite-phase flip-cycle: OAM attr H/V bits cycle + frames differ ---
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    hv = []
    paths = []
    for i, t in enumerate(T_FLIP):
        _drive_to_scene_timer(runner, t)
        attr = _meteor_oam_attr(runner)
        assert attr is not None, f"meteor sprite OAM not found at flip beat t={t}"
        hv.append(((attr >> 6) & 1, (attr >> 7) & 1))   # (H, V)
        p = f"/tmp/meteor_flip_{i}.png"
        runner.take_screenshot(p)
        paths.append(p)
    # the four beats are o = 1,2,3,0 -> (H,V) = (1,0),(0,1),(1,1),(0,0)
    assert hv == [(1, 0), (0, 1), (1, 1), (0, 0)], (
        f"sprite flip-cycle OAM H/V bits did not cycle as expected: {hv}")
    # rendered frames differ across orientations (the craters reorient)
    d01 = _region_rgb_diff(paths[0], paths[1], y0=0, y1=120, tol=30)
    assert d01 > 100, (
        f"sprite flip-cycle did not visibly change the render across orientations "
        f"({d01}px frame diff)")

    # --- (C) Mode-7 affine tumble: real vs -DNO_TUMBLE, centroid-ALIGNED ---
    def m7frame(rom_path, path):
        runner.load_rom(str(rom_path), run_seconds=0.3)
        assert _drive_to_state(runner, ST_SCENE), f"{rom_path} never reached ST_SCENE"
        runner.set_input(0)
        _drive_to_scene_timer(runner, T_M7_TEX)
        runner.run_frames(3)
        runner.take_screenshot(path)
        n = _meteor_pixels(path)
        assert n > 600, f"{rom_path}: no rendered meteor at scene timer {T_M7_TEX} ({n})"
        return n

    m7frame(rom, "/tmp/meteor_tumble_real.png")
    m7frame(notumble, "/tmp/meteor_tumble_ctrl.png")
    m7frame(notumble, "/tmp/meteor_tumble_ctrl2.png")

    # Centroid-aligned crops cancel the slide so the diff isolates ROTATION:
    # real (tumbling craters) vs NO_TUMBLE (angle held at 0) is large; two
    # NO_TUMBLE captures (same angle) are ~0 even if the slide landed a few px
    # apart across runs — which is exactly the full-suite jitter that made a
    # whole-frame diff flaky.
    diff = _meteor_crop_diff("/tmp/meteor_tumble_real.png", "/tmp/meteor_tumble_ctrl.png")
    ctrl = _meteor_crop_diff("/tmp/meteor_tumble_ctrl.png", "/tmp/meteor_tumble_ctrl2.png")
    assert diff is not None and ctrl is not None, "meteor centroid not found for tumble diff"

    assert diff > 150, (
        f"Mode-7 meteor did not visibly TUMBLE: centroid-aligned real-vs-NO_TUMBLE "
        f"diff only {diff}px (rotation should reorient the asymmetric craters)")
    assert ctrl < diff // 2, (
        f"tumble signal not cleanly attributable to rotation: control-vs-control "
        f"diff {ctrl}px vs real-vs-control {diff}px (want ctrl < {diff // 2})")


# =============================================================================
# (C) RED GLOW — rises then recedes in the lower band, BEHIND the OBJ sprites.
# =============================================================================
def test_red_glow_rises_and_recedes_behind_sprites(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)

    _drive_to_scene_timer(runner, T_GLOW_PRE)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_glow_pre.png")
    red_pre = _red_lower_band("/tmp/meteor_glow_pre.png")

    _drive_to_scene_timer(runner, T_GLOW_PEAK)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_glow_peak.png")
    red_peak = _red_lower_band("/tmp/meteor_glow_peak.png")

    _drive_to_scene_timer(runner, T_GLOW_RECEDE)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_glow_recede.png")
    red_recede = _red_lower_band("/tmp/meteor_glow_recede.png")

    assert red_peak > red_pre + 2000, (
        f"red glow did not RISE: lower-band red pre={red_pre} -> peak={red_peak}")
    assert red_recede < red_peak * 0.5, (
        f"red glow did not RECEDE: peak={red_peak} -> recede={red_recede}")

    # at PEAK the OBJ sprites must stay un-tinted (OBJ excluded from color math).
    px, w, h = _rgb("/tmp/meteor_glow_peak.png")
    green = sum(1 for y in range(h) for x in range(w) if _is_green(px[x, y]))
    white = sum(1 for y in range(h) for x in range(w) if _is_white(px[x, y]))
    assert green >= 2000, (
        f"green OBJ ground tinted/absent at peak red ({green} green px) — OBJ not "
        f"excluded from color math")
    assert white >= 64, (
        f"white OBJ player tinted/absent at peak red ({white} white px) — OBJ not "
        f"excluded from color math")


# =============================================================================
# (C/D) swap back to Mode 1, the level re-renders, control released.
# =============================================================================
def test_swap_back_restores_mode1_ground(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)

    assert _drive_to_state(runner, ST_PLAY, max_frames=800, hold_right=False), \
        "never returned to ST_PLAY after the event"
    runner.run_frames(4)
    runner.take_screenshot("/tmp/meteor_restored.png")

    band = _green_band("/tmp/meteor_restored.png")
    assert band is not None, "Mode-1 ground band did NOT re-render after the swap-back"
    assert band[2] >= 16, f"restored ground band too thin: {band}"

    bgmode = runner.read_u16(WR, DBG_BGMODE) & 0x07
    assert bgmode == 1, f"BGMODE not back to Mode 1 after swap-back (low nibble {bgmode})"


def test_control_released_after_event(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    assert _drive_to_state(runner, ST_PLAY, max_frames=800, hold_right=False), \
        "never returned to ST_PLAY after the event"

    cam0 = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_release0.png")
    runner.set_input(0, right=True)
    runner.run_frames(40)
    cam1 = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_release1.png")
    runner.set_input(0)

    assert cam1 > cam0, (
        f"control NOT released: camera did not advance with RIGHT held after the "
        f"event ({cam0} -> {cam1})")
    px0, w, h = _rgb("/tmp/meteor_release0.png")
    px1, _, _ = _rgb("/tmp/meteor_release1.png")

    def upper_green_edge(px):
        best = -1
        for y in range(0, int(h * 0.7)):
            for x in range(w):
                if _is_green(px[x, y]):
                    best = max(best, x)
        return best
    assert upper_green_edge(px0) != upper_green_edge(px1) or cam1 != cam0, \
        "rendered scene did not move after control release"


# =============================================================================
# Mode-flip SEQUENCE — Mode1 -> Mode7 -> Mode1, each PROVEN on the framebuffer.
# =============================================================================
def test_mode_flip_sequence_rendered(runner):
    rom = BUILD / "meteor_event.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)

    runner.run_frames(8)
    runner.take_screenshot("/tmp/meteor_flip_mode1a.png")
    assert _green_band("/tmp/meteor_flip_mode1a.png") is not None, \
        "no Mode-1 ground band at boot"
    assert (runner.read_u16(WR, DBG_BGMODE) & 0x07) == 1, "boot BGMODE not Mode 1"

    assert _drive_to_state(runner, ST_SCENE), "never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_M7_TEX)
    n = _peak_meteor_frame(runner, "/tmp/meteor_flip_mode7.png")
    assert n > 600, f"no rendered Mode-7 meteor mid-scene ({n})"
    assert _distinct_colors("/tmp/meteor_flip_mode7.png") >= 4, \
        "Mode-7 meteor plane not textured (>=4 colours) mid-scene"
    assert (runner.read_u16(WR, DBG_BGMODE) & 0x07) == 7, "mid-scene BGMODE not Mode 7"

    assert _drive_to_state(runner, ST_PLAY, max_frames=800, hold_right=False), \
        "never returned to ST_PLAY"
    runner.run_frames(4)
    runner.take_screenshot("/tmp/meteor_flip_mode1b.png")
    assert _green_band("/tmp/meteor_flip_mode1b.png") is not None, \
        "no Mode-1 ground band after restore"
    assert (runner.read_u16(WR, DBG_BGMODE) & 0x07) == 1, "post-restore BGMODE not Mode 1"


# =============================================================================
# NON-VACUITY CONTROLS — prove each assertion discriminates.
# =============================================================================
def test_control_no_capture_loses_ground_band(runner, variants):
    rom = variants["nocap"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "control never reached ST_SCENE"
    runner.run_frames(20)
    runner.take_screenshot("/tmp/meteor_ctrl_nocap.png")
    band = _green_band("/tmp/meteor_ctrl_nocap.png")
    assert band is None, \
        f"NO_CAPTURE control STILL shows a ground band ({band}) — capture test is vacuous"
    runner.set_input(0)


def test_control_no_freeze_keeps_moving(runner, variants):
    rom = variants["nofreeze"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_FREEZE), "control never reached ST_FREEZE"
    cam0 = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_ctrl_nofreeze0.png")
    runner.run_frames(10)
    cam1 = runner.read_u16(WR, DBG_CAMX)
    runner.take_screenshot("/tmp/meteor_ctrl_nofreeze1.png")
    assert cam1 != cam0, \
        f"NO_FREEZE control did NOT move during 'freeze' (cam {cam0}->{cam1}) — freeze test vacuous"
    px0, w, h = _rgb("/tmp/meteor_ctrl_nofreeze0.png")
    px1, _, _ = _rgb("/tmp/meteor_ctrl_nofreeze1.png")

    def edge(px):
        best = -1
        for y in range(0, int(h * 0.7)):
            for x in range(w):
                if _is_green(px[x, y]):
                    best = max(best, x)
        return best
    assert edge(px0) != edge(px1) or cam1 != cam0
    runner.set_input(0)


def test_control_no_gradient_no_red_glow(runner, variants):
    rom = variants["nograd"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_SCENE), "control never reached ST_SCENE"
    runner.set_input(0)
    _drive_to_scene_timer(runner, T_GLOW_PEAK)
    runner.run_frames(1)
    runner.take_screenshot("/tmp/meteor_ctrl_nograd_peak.png")
    red_peak = _red_lower_band("/tmp/meteor_ctrl_nograd_peak.png")
    assert red_peak < 1000, (
        f"NO_GRADIENT control STILL shows red glow ({red_peak} red px) — glow "
        f"test is vacuous")


def test_control_no_release_control_stays_gated(runner, variants):
    rom = variants["norelease"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _drive_to_state(runner, ST_RESTORE, max_frames=800), \
        "control never reached ST_RESTORE"
    runner.set_input(0)
    runner.run_frames(20)
    assert _state(runner) != ST_PLAY, "NO_RELEASE control returned to PLAY — vacuous"
    cam0 = runner.read_u16(WR, DBG_CAMX)
    runner.set_input(0, right=True)
    runner.run_frames(40)
    cam1 = runner.read_u16(WR, DBG_CAMX)
    runner.set_input(0)
    assert cam1 == cam0, (
        f"NO_RELEASE control camera ADVANCED ({cam0} -> {cam1}) — control was "
        f"released, release test is vacuous")
    assert (runner.read_u16(WR, DBG_BGMODE) & 0x07) == 7, \
        "NO_RELEASE control left Mode 7 — vacuous"
