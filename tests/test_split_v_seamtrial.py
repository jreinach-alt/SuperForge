"""split_v_seamtrial — the seamless vertical split, asserted as a picture.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(ROM).advance(N)`, which
lands on the ABSOLUTE frame N by construction — which is the entire reason this
rail exists as a separate thing from `split_v_fight`.

WHAT THIS RAIL IS, AND THEREFORE WHAT THESE CASES HAVE TO PROVE. One stage,
two cameras at `mid ± spread`, an always-on PPU window 1 at the screen centre,
and a bevelled BG3 bar revealed only inside a second window band of half-width
`hw = spread >> 4`. Its source  states its own claim in its header:

    the window split is a SINGLE-PIXEL boundary with no inherent gap, so if the
    two camera views are IDENTICAL the ever-present split is invisible.
    Separation is therefore NOT a state you toggle — it is a continuous
    divergence.

That is a claim about PIXELS, and `spread` sweeps a triangle with no input, so
every frame of it is a determined state. `split_v_fight` had to ship five `-D`
variant ROMs to freeze that variable for a race-free proof
(tools/build_split_v_variants.sh's header says so); this module needs none —
`advance(N)` is the freeze.

THE ORACLE, and why it is not a tautology. Nine of the fifteen cases compare
the hardware framebuffer against a WHOLE-FRAME re-render built here: the
terrain ladder, the height map and the four colours are re-derived IN THIS FILE
from the source rail's own `main.asm` (its `hmap` table, its `sf_bg_color`
block and its `@row`/`@col` tile-selection ladder), the 4bpp tile decode is
written out longhand, and the window band is applied from the geometry rather
than from anything the ROM says. It shares NO code with
tools/gen_seamtrial_assets.py, so a generator bug and an ASM bug cannot agree
with each other here. It reproduces hardware to 0 differing pixels of 57,344 —
which is what makes the merge claim assertable as identity rather than as
similarity.

TWO HARNESS FACTS THIS MODULE IS BUILT ON, both measured on this ROM:

  * THE CAPTURE IS 239 LINES (the overscan frame) and the picture proper
    occupies rows 7..230. BG row R lands on screenshot row R + 6, so BG row 0
    is never displayed — the ordinary SNES BGnVOFS off-by-one, arriving as a
    property of the harness rather than of the rail. The spec records the
    same trap one rail over.
  * THE PICTURE AT FRAME N SHOWS THE SPREAD PUBLISHED BY THE TICK AT FRAME
    N-1. `sv_vblank` commits the cameras and the band in the VBlank that
    follows the tick, so `advance(N)` parks on a frame drawn from N sweeps.
    `spread_after(N)` below is that model, and `test_frame_to_spread_model`
    proves the model against the picture instead of asserting it.

WHAT IS NOT ASSERTED HERE, deliberately: nothing reads a script-side or WRAM-side
`spread`. The DP cell exists and would make several of these cases one line
long; it is exactly the proxy variable CLAUDE.md rule 2 forbids, because it
reads correct on a ROM whose window recipe is broken.
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
ROM = BUILD / "split_v_seamtrial.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "svs" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="trial"):
    pool = (MAP["scenes"][scene]["placements"] if scene else MAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_STAGE_CHR = _sym("ES_V_STAGE_CHR")["start"]     # VRAM words
V_STAGE_MAP = _sym("ES_V_STAGE_MAP")["start"]
V_BEVEL_CHR = _sym("ES_V_BEVEL_CHR")["start"]
V_BEVEL_MAP = _sym("ES_V_BEVEL_MAP")["start"]
C_STAGE_PAL = _sym("ES_C_STAGE_PAL")["start"]     # CGRAM word index
C_BEVEL_PAL = _sym("ES_C_BEVEL_PAL")["start"]


# --- the rail's geometry (game/split_v_seamtrial/seamtrial.inc, re-derived) --
MID_CAM = 96
SPREAD_MAX = 48
SPR_STEP = 0x00C0                 # 0.75 px/frame in 8.8
SEAM = 128                        # the split column: fixed, only cameras move

# --- the stage (the SOURCE rail's main.asm, re-derived; see the docstring) ---
HMAP = [18, 18, 17, 16, 15, 13, 11, 9, 8, 8, 9, 11, 13, 15, 16, 17,
        17, 16, 15, 14, 14, 15, 16, 17, 17, 16, 15, 15, 16, 17, 18, 18]
GND_DIRT = 24
MTN_LO, MTN_HI = 6, 13


def _rgb(bgr555):
    """SNES BGR555 -> the 8-bit RGB Mesen writes into a PNG: c<<3 | c>>2."""
    def ch(c):
        return (c << 3) | (c >> 2)
    return (ch(bgr555 & 31), ch((bgr555 >> 5) & 31), ch((bgr555 >> 10) & 31))


SKY_W, GRASS_W, MTN_W, DIRT_W = 0x7F54, 0x02E0, 0x4A52, 0x1194
GRASS_D_W, MTN_D_W, DIRT_D_W = 0x01C0, 0x318C, 0x08CD
STAGE_PAL_W = [SKY_W, SKY_W, GRASS_W, MTN_W, DIRT_W,
               GRASS_D_W, MTN_D_W, DIRT_D_W]
STAGE_PAL = [_rgb(w) for w in STAGE_PAL_W]
SKY = STAGE_PAL[1]

# The bevel: defect 6's MEASURED tones, the ones the reference's own published
# render shows. Same three split_v_fight ships — the trial and the rail it
# graduated into must draw the same bar or this is not the same mechanism.
BEVEL_PAL_W = [0x0000, 0x18C6, 0x4E73, 0x7FFF]
BEVEL_PAL = [_rgb(w) for w in BEVEL_PAL_W]
BEVEL_TONES = set(BEVEL_PAL[1:])
# Tile columns of the ONE bevel tile split_v_bg tiles BG3 with. This is the
# source's two-tile bar (`$FFFE` x8 | `$C03F` x8 at map cols 15/16, BG3HOFS 0)
# re-indexed onto `x & 7` — see tools/gen_seamtrial_assets.py's docstring.
BEVEL_COLS = [2, 2, 1, 1, 3, 3, 3, 2]

# --- the harness facts (docstring) ------------------------------------------
YOFF = 6                          # screenshot row = BG row + 6
ROW_TOP, ROW_BOT = 7, 231         # the picture occupies rows [7, 231)


def _tile_id(col, row):
    """The source's selection ladder (main.asm:169-193) plus this port's two
    authored refinements: the top non-sky row of a non-rock column is the
    grass-over-dirt surface tile, and odd columns take the dithered variant."""
    h = HMAP[col & 31]
    if row < h:
        return 1
    if MTN_LO <= (col & 31) < MTN_HI and row < GND_DIRT:
        return 6 if col & 1 else 3
    if row >= GND_DIRT:
        return 7 if col & 1 else 4
    if row == h:
        return 8
    return 5 if col & 1 else 2


def _tiles():
    def solid(v):
        return [[v] * 8 for _ in range(8)]

    def checker(a, b):
        return [[a if (x + y) & 1 == 0 else b for x in range(8)]
                for y in range(8)]

    return [solid(0), solid(1), solid(2), solid(3), solid(4),
            checker(2, 5), checker(3, 6), checker(4, 7),
            [[2 if y < 2 else 4] * 8 for y in range(8)]]


TILES = _tiles()


# --- the sweep, restated here against scenes/trial.asm ---------------------
def spread_after(n):
    """The integer `spread` published after N calls of `sweep`. The picture at
    absolute frame N is drawn from exactly this (see the docstring's second
    harness fact)."""
    f, closing = 0, False
    for _ in range(n):
        if not closing:
            cand = f + SPR_STEP
            if (cand >> 8) >= SPREAD_MAX:
                f, closing = SPREAD_MAX << 8, True
            else:
                f = cand
        else:
            if f >= SPR_STEP:
                f -= SPR_STEP
            else:
                f, closing = 0, False
    return f >> 8


def cams(spread):
    """cam A (left half) and cam B (right half). Mod 256 because the stage map
    is 256 px periodic, which is what makes split_v_bg's byte camera correct."""
    return (MID_CAM - spread) & 0xFF, (MID_CAM + spread) & 0xFF


def band(spread):
    """The divider band [lo, hi] inclusive, or None while merged. hw ramps from
    zero, so at merge the window is written INVERTED (left 1, right 0) and the
    PPU treats it as inactive — no band at all, not a 1px sliver."""
    hw = spread >> 4
    return None if hw == 0 else (SEAM - hw, SEAM + hw)


def render(spread):
    """The whole frame, independently. Returns {(x, y): rgb} over the picture
    rows only."""
    cam_l, cam_r = cams(spread)
    bnd = band(spread)
    out = {}
    for sy in range(ROW_TOP, ROW_BOT):
        bg_row = sy - YOFF
        trow, py = (bg_row >> 3) & 31, bg_row & 7
        for sx in range(256):
            if bnd and bnd[0] <= sx <= bnd[1]:
                out[(sx, sy)] = BEVEL_PAL[BEVEL_COLS[sx & 7]]
                continue
            wx = ((cam_l if sx < SEAM else cam_r) + sx) & 0xFF
            out[(sx, sy)] = STAGE_PAL[TILES[_tile_id(wx >> 3, trow)][py][wx & 7]]
    return out


# --- capture -----------------------------------------------------------------
_SHOTS = {}


def shot(frame, seed=None, tmp_path_factory=None):
    """The framebuffer at ABSOLUTE frame `frame`, as a pixel accessor. Cached:
    every case that names the same frame photographs the same emulated frame,
    which is the property `advance` buys and `run_seconds` never could."""
    key = (frame, seed)
    if key not in _SHOTS:
        out = BUILD / "shots" / f"svs_f{frame:04d}_{seed or 0}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        kw = {} if seed is None else {"seed": seed}
        with Machine(str(ROM), **kw) as m:
            m.advance(frame)
            m.screenshot(str(out))
        _SHOTS[key] = Image.open(out).convert("RGB").load()
    return _SHOTS[key]


def hw_state(frame):
    """VRAM + CGRAM at a parked absolute frame, for the upload-destination
    cases. Read at the park, so it describes the same frame `shot` captures."""
    with Machine(str(ROM)) as m:
        m.advance(frame)
        return {
            "stage_chr": m.read_bytes(V, V_STAGE_CHR * 2, 9 * 32),
            "stage_map": m.read_bytes(V, V_STAGE_MAP * 2, 0x400 * 2),
            "bevel_chr": m.read_bytes(V, V_BEVEL_CHR * 2, 64),
            "bevel_map": m.read_bytes(V, V_BEVEL_MAP * 2, 0x400 * 2),
            "cgram": m.read_bytes(C, 0, 64),
        }


def diff(frame, spread):
    """Pixels where hardware and the oracle disagree."""
    px = shot(frame)
    return [(k, v, px[k]) for k, v in render(spread).items() if px[k] != v]


def silhouette(px):
    """The sky/terrain boundary per screen column, as a BG row. This is what a
    human reads the split off, so it is what the camera-recovery cases use."""
    out = []
    for x in range(256):
        top = None
        for y in range(ROW_TOP, ROW_BOT):
            if px[x, y] != SKY:
                top = y - YOFF
                break
        out.append(top)
    return out


def fit_cam(sil, lo, hi):
    """The camera whose silhouette best explains columns [lo, hi). Brute force
    over all 256, so a wrong answer cannot hide behind a nearby right one."""
    scored = sorted(((sum(1 for x in range(lo, hi)
                          if sil[x] == HMAP[((c + x) >> 3) & 31] * 8), c)
                     for c in range(256)), reverse=True)
    return scored[0][1], scored[0][0], hi - lo


# --- the frames these cases are about ---------------------------------------
# Derived from spread_after(), then PROVEN against the picture by
# test_frame_to_spread_model. Nothing below hardcodes a spread it did not
# derive.
F_MERGE = 127        # spread 0 — the halves are one picture
F_SPLIT = 64         # spread 48 — full divergence, the widest bar (hw 3)
F_RAMP = 20          # spread 15 — opening, hw 0: parted halves, NO bar yet
F_MID_OPEN = 40      # spread 30, opening  (hw 1)
F_MID_CLOSE = 100    # spread ~20, CLOSING — the other direction
F_MERGE_2 = 128      # the merge holds for two frames before it reopens


@pytest.fixture(scope="module", autouse=True)
def _rom_exists():
    assert ROM.exists(), f"{ROM} missing — run `make split_v_seamtrial`"


# =============================================================================
# 1. THE HEADLINE: at zero divergence the ever-present seam is invisible
# =============================================================================
def test_merged_frame_is_one_continuous_picture():
    """The whole claim, as identity rather than as similarity: at spread 0 every
    one of the 57,344 picture pixels equals a SINGLE-camera render at cam 96 —
    including the seven columns the divider would occupy. A merged split view
    IS a no-split view."""
    bad = diff(F_MERGE, 0)
    assert bad == [], f"{len(bad)} px differ from a single-camera view: {bad[:5]}"


def test_split_frame_differs_from_a_single_camera_view_on_BOTH_sides():
    """The positive control the identity case needs, and it is not optional: an
    identity test passes trivially against a constant. At full divergence the
    same single-camera oracle must FAIL, and fail on both sides of the seam, so
    the merged match above cannot be an artefact of comparing sky to sky."""
    px = shot(F_SPLIT)
    one_cam = render(0)
    left = sum(1 for (x, y), v in one_cam.items() if x < SEAM and px[x, y] != v)
    right = sum(1 for (x, y), v in one_cam.items() if x >= SEAM and px[x, y] != v)
    assert left > 2000, f"left half only differs in {left} px — is it split at all?"
    assert right > 2000, f"right half only differs in {right} px"


def test_merged_seam_columns_show_terrain_not_a_masked_gap():
    """The band's EMPTY case, read where it can be read. At merge split_v_bg
    writes window 2 inverted (left 1, right 0) so the PPU deactivates it; if it
    instead wrote a 1px sliver, or left BG1/BG2 masked, the seam columns would
    fall through to the CGRAM-0 backdrop. Asserted in the GROUND rows, because
    the backdrop here is sky-coloured on purpose and a masked sky pixel is
    indistinguishable from a sky pixel."""
    px = shot(F_MERGE)
    exp = render(0)
    for x in range(SEAM - 4, SEAM + 5):
        # The ground rows OF THIS COLUMN: the terrain's height varies per
        # column, so a row list taken from one column would ask a neighbour
        # about sky.
        ground = [y for y in range(ROW_TOP, ROW_BOT) if exp[(x, y)] != SKY]
        assert len(ground) > 40, f"column {x} has no ground — the oracle is wrong"
        for y in ground:
            assert px[x, y] == exp[(x, y)], (
                f"seam px ({x},{y}) is {px[x, y]}, expected terrain {exp[(x, y)]}")
            assert px[x, y] != SKY, f"({x},{y}) fell through to the backdrop"


def test_merged_frame_carries_no_divider_pixel_anywhere():
    """Zero width means zero pixels. The three bevel tones appear nowhere in the
    stage palette, so their absence over the WHOLE frame is decidable — and
    their presence at full split is the same assertion's other arm."""
    merged, split = shot(F_MERGE), shot(F_SPLIT)
    n_merged = sum(1 for y in range(ROW_TOP, ROW_BOT) for x in range(256)
                   if merged[x, y] in BEVEL_TONES)
    n_split = sum(1 for y in range(ROW_TOP, ROW_BOT) for x in range(256)
                  if split[x, y] in BEVEL_TONES)
    assert n_merged == 0, f"{n_merged} bevel px while merged — the bar has width"
    assert n_split == 7 * (ROW_BOT - ROW_TOP), (
        f"{n_split} bevel px at full split, expected a 7px full-height bar")


# =============================================================================
# 2. THE DIVIDER: it ramps out of nothing, in the source's own cross-section
# =============================================================================
def test_divider_width_ramps_from_zero():
    """hw = spread >> 4, so the bar is 0, 3, 5 and 7 px at spreads 0, 16, 32 and
    48. Measured off the picture at four frames whose spreads the model gives —
    the ramp is the property that stops the split stealing screen width at
    merge."""
    seen = {}
    for frame in (F_MERGE, F_RAMP, F_MID_OPEN, F_MID_CLOSE, F_SPLIT):
        px, s = shot(frame), spread_after(frame)
        w = sum(1 for x in range(256) if px[x, 100] in BEVEL_TONES
                or px[x, 200] in BEVEL_TONES)
        seen[s] = w
        assert w == (0 if s >> 4 == 0 else 2 * (s >> 4) + 1), (
            f"frame {frame} spread {s}: bar is {w}px, expected {2 * (s >> 4) + 1}")
    assert 0 in seen and max(seen.values()) == 7, seen


def test_divider_cross_section_is_the_source_rails_bar():
    """The bar is not "a grey line": it is the source's bevel, transcribed. Its
    two tiles (`$FFFE` | `$C03F` at BG3 map cols 15/16) re-index onto `x & 7`,
    so the seven visible columns must read light, light, mid, mid, mid, dark,
    dark. Asserted on rows in sky, grass AND dirt so it is the bar's whole
    height, not one lucky scanline."""
    px = shot(F_SPLIT)
    lo, hi = band(48)
    want = [BEVEL_PAL[BEVEL_COLS[x & 7]] for x in range(lo, hi + 1)]
    assert want == [BEVEL_PAL[3], BEVEL_PAL[3], BEVEL_PAL[2], BEVEL_PAL[2],
                    BEVEL_PAL[2], BEVEL_PAL[1], BEVEL_PAL[1]], want
    for y in (30, 100, 150, 200, 228):
        got = [px[x, y] for x in range(lo, hi + 1)]
        assert got == want, f"row {y}: {got}"
        assert px[lo - 1, y] not in BEVEL_TONES, f"bar bleeds left at row {y}"
        assert px[hi + 1, y] not in BEVEL_TONES, f"bar bleeds right at row {y}"


def test_divider_is_full_height():
    """Window 2 is a COLUMN, not a box: the bar must reach every picture row.
    A BG3 tilemap that only covered part of the screen, or a W12SEL missing its
    win2 term on BG1/BG2, would leave the bar stopping at the horizon — the
    exact failure the spec's sv_window_arm header warns about."""
    px = shot(F_SPLIT)
    for y in range(ROW_TOP, ROW_BOT):
        assert px[SEAM, y] in BEVEL_TONES, f"no bar pixel at row {y}"


# =============================================================================
# 3. STATE-CYCLE COVERAGE: the sweep opens AND closes AND re-merges
# =============================================================================
def test_frame_to_spread_model_matches_the_picture():
    """The model this module's frame choices rest on, PROVEN rather than
    assumed: at six frames spanning both sweep directions, the cameras recovered
    from the drawn silhouette must be exactly (96 - s, 96 + s) for the modelled
    s. A model that drifted would make every frame-indexed case below a
    statement about the wrong state."""
    for frame in (F_RAMP, F_MID_OPEN, F_SPLIT, F_MID_CLOSE, F_MERGE, F_MERGE_2):
        s = spread_after(frame)
        sil = silhouette(shot(frame))
        got_l, hit_l, n_l = fit_cam(sil, 0, SEAM - 8)
        got_r, hit_r, n_r = fit_cam(sil, SEAM + 8, 256)
        exp_l, exp_r = cams(s)
        assert (got_l, got_r) == (exp_l, exp_r), (
            f"frame {frame}: drawn cams ({got_l},{got_r}), model says "
            f"({exp_l},{exp_r}) for spread {s}")
        assert hit_l == n_l and hit_r == n_r, "the fit is not exact"


def test_the_sweep_separates_then_merges_then_separates_again():
    """State-cycle coverage on the time axis (the repo's founding rule): one
    boot, sampled across a full 129-frame period, must show the divergence
    RISE, FALL, reach exactly zero, and rise again. A single sample — or a
    sweep tested only while opening — passes on a ROM whose triangle never
    turns around, which is precisely the defect this rail shipped once."""
    with Machine(str(ROM)) as m:
        widths = []
        for f in range(1, 200):
            m.advance(1)
            if f % 4:
                continue
            out = BUILD / "shots" / f"svs_cycle_{f:04d}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            m.screenshot(str(out))
            px = Image.open(out).convert("RGB").load()
            widths.append(sum(1 for x in range(256)
                              if px[x, 200] in BEVEL_TONES))
    peak = widths.index(max(widths))
    trough = widths.index(min(widths[peak:]), peak)
    assert max(widths) == 7, f"never fully split: {widths}"
    assert min(widths[peak:]) == 0, f"never re-merged: {widths}"
    assert widths[:peak + 1] == sorted(widths[:peak + 1]), "opening not monotone"
    assert widths[peak:trough + 1] == sorted(widths[peak:trough + 1],
                                             reverse=True), "closing not monotone"
    assert max(widths[trough:]) > 0, "never re-opened after the merge"


def test_both_halves_track_their_own_camera_while_closing():
    """The reverse direction, on the picture. Walking only one way locks one
    direction and ships the other broken; the closing phase is where camA and
    camB must CONVERGE, and a rail that derived one camera from the other's
    sign would pass every opening frame and fail here."""
    for frame in (F_MID_CLOSE, F_MID_CLOSE + 8, F_MID_CLOSE + 16):
        s = spread_after(frame)
        assert spread_after(frame) < spread_after(frame - 4), "not closing"
        bad = diff(frame, s)
        assert bad == [], f"frame {frame} (spread {s}): {len(bad)} px differ"


# =============================================================================
# 4. THE UPLOADS: destination regions, read where the DMA put them
# =============================================================================
def test_stage_chr_and_map_landed_in_vram():
    """CLAUDE.md's asset-upload rule: read the DESTINATION region byte for byte.
    A test that only checks the drawn result can pass while the upload silently
    no-ops — this rail shipped exactly that once (correct OAM pointing at
    never-uploaded CHR, rendering power-on noise)."""
    hw = hw_state(F_SPLIT)
    assert hw["stage_chr"] == (ASSETS / "svs_stage_chr.bin").read_bytes()
    assert hw["stage_map"] == (ASSETS / "svs_stage_map.bin").read_bytes()


def test_bevel_chr_landed_and_its_map_is_uniform():
    """The bar's SHAPE comes from window 2, not from the tilemap: BG3 is drawn
    everywhere and shown only inside the band. So the whole 1024-word map must
    be the one bevel entry — and that entry must carry PALETTE 2 in bits 10-12.
    A bare tile number selects palette 0, the STAGE's colours; the bar still
    renders, in muddy stage tones, and every "the divider is present"
    assertion still passes."""
    hw = hw_state(F_SPLIT)
    assert hw["bevel_chr"] == (ASSETS / "svs_bevel_chr.bin").read_bytes()
    want = (2 << 10).to_bytes(2, "little")
    assert hw["bevel_map"] == want * 0x400, hw["bevel_map"][:8]


def test_cgram_holds_the_stage_and_bevel_palettes_where_they_were_claimed():
    """Both palettes, at the CGRAM words the allocator emitted. The bevel's four
    live INSIDE BG palette 0's sixteen (BG3 is 2bpp in Mode 1, so its palette 2
    IS words 8..11) — which is why split_v_bg claims 8 + 4 rather than 16, and
    why an upload that overran would be invisible until the bar changed
    colour."""
    cg = hw_state(F_SPLIT)["cgram"]

    def word(i):
        return cg[i * 2] | (cg[i * 2 + 1] << 8)

    for i, w in enumerate(STAGE_PAL_W):
        assert word(C_STAGE_PAL + i) == w, f"stage CGRAM word {C_STAGE_PAL + i}"
    for i, w in enumerate(BEVEL_PAL_W):
        assert word(C_BEVEL_PAL + i) == w, f"bevel CGRAM word {C_BEVEL_PAL + i}"


# =============================================================================
# 5. POWER-ON FIDELITY: nothing uninitialised reaches the picture
# =============================================================================
def test_the_picture_is_the_same_under_a_different_power_on_ram():
    """Rule 5, asserted on the OUTPUT. WRAM, VRAM, CGRAM and OAM are random at
    boot; this rail composes no sprite feature, so its TM leaves OBJ off the
    main screen and its enter writes every cell it reads. Two boots with
    different power-on seeds must therefore photograph the SAME frame — a rail
    that displayed one uninitialised byte would differ here and nowhere else."""
    a, b = shot(F_SPLIT), shot(F_SPLIT, seed=0x5EA11)
    bad = [(x, y) for y in range(ROW_TOP, ROW_BOT) for x in range(256)
           if a[x, y] != b[x, y]]
    assert bad == [], f"{len(bad)} px depend on power-on RAM: {bad[:5]}"


def test_the_merged_frame_is_the_same_under_a_different_power_on_ram():
    """The merge is the frame the rail's headline claim is made on, so it gets
    the seed check of its own rather than inheriting the split's."""
    a, b = shot(F_MERGE), shot(F_MERGE, seed=0x5EA11)
    bad = [(x, y) for y in range(ROW_TOP, ROW_BOT) for x in range(256)
           if a[x, y] != b[x, y]]
    assert bad == [], f"{len(bad)} px depend on power-on RAM: {bad[:5]}"
