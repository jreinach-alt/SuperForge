"""shmup — the vertical shooter, end to end on the emulator.

THE TEST SURFACE IS THE RENDERED OUTPUT, EVERYWHERE (CLAUDE.md rule 2).
"A fighter is on screen" is asserted as *the OAM entry bytes the PPU reads*,
not as "the pool's alive word is 1" — for POOL specifically that distinction
is the whole point, because "the array says alive" is exactly the proxy
assertion this repo has been burned by. "The field drifts down" is asserted as
*screenshot pixels moving down the screen*, not as "BG1VOFS decreased". "GAME
OVER is showing" is asserted as *the glyph tiles sitting in BG3's tilemap*.
Where a DP word appears it is either NAVIGATION (getting the machine into the
state under test) or it is asserted BESIDE the output region it explains —
never instead of it. The one exception is scene_mgr's ES_SM_CTL, used to know
which scene is live; that is an engine fact and never the thing a test claims.

The case list is the rail's own done-condition block, written to be
emulator-verifiable, plus two more this module adds: POOL, and the source-art
ground truth.

STATE-CYCLE COVERAGE, not snapshots (AGENTS.md "Test discipline"): the module
drives title -> play -> movement in ALL FOUR directions and both clamps ->
fire -> a bullet's whole life -> a fighter's whole life -> a kill -> a burst's
whole four-frame arc -> damage -> respawn -> GAME OVER -> title -> a fresh
round. A rail tested only on its opening frame ships its endings broken.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "shmup.sfc"
_JMAP = json.loads((SUPERFORGE / "build" / "sh" / "symbol_map.json").read_text())


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — the allocator moved it?")


# Addresses are ASKED FOR, never hardcoded: this file reads the same map the
# ROM was assembled against, so a re-pack moves the test with the code.
SM_CTL = _sym("ES_SM_CTL")["start"]
SHM_MAP = _sym("ES_V_SHM_MAP", "play")["start"]          # VRAM WORD address
BAR_MAP = _sym("ES_V_BAR_MAP", "play")["start"]
TXT_MAP = _sym("ES_V_TEXT_MAP", "play")["start"]
TITLE_TXT_MAP = _sym("ES_V_TEXT_MAP", "title")["start"]
POOLS = _sym("ES_SHM_POOLS", "play")["start"]            # WRAM ($7E) offset
O_SHIP = _sym("ES_O_SHIP", "play")["start"]
O_BULLETS = _sym("ES_O_BULLETS", "play")["start"]
O_FOES = _sym("ES_O_FOES", "play")["start"]
O_BURSTS = _sym("ES_O_BURSTS", "play")["start"]
C_SHIP_PAL = _sym("ES_C_SHIP_PAL", "play")["start"]
C_FOE_PAL = _sym("ES_C_FOE_PAL", "play")["start"]
C_BURST_PAL = _sym("ES_C_BURST_PAL", "play")["start"]
C_SHM_PAL = _sym("ES_C_SHM_PAL", "play")["start"]
DP = {k: _sym("US_" + k.upper(), "play")["start"]
      for k in ("px", "py", "score", "lives", "gover", "hurt", "blink",
                "spawn_t", "aframe")}

SCENE_TITLE, SCENE_PLAY = 0, 1
W, V, O, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesSpriteRam, MemoryType.SnesCgRam)

# --- the rail's declared shape (game/shmup/shmup.inc) -----------------------
# Restated here as an ORACLE, deliberately independent of the ROM: these are
# the numbers the rail promises, and the tests check the machine against them
# rather than against whatever the machine happens to hold.
SHIP_SPEED, SHIP_MIN_X, SHIP_MAX_X = 2, 8, 224
SHIP_MIN_Y, SHIP_MAX_Y = 32, 200
SHIP_SPAWN_X, SHIP_SPAWN_Y = 120, 176
BULLET_SPEED, BULLET_TOP, BULLET_DX, BULLET_DY = 4, 16, 4, 8
FOE_SPEED, FOE_SPAWN_Y, FOE_GONE_Y = 1, 24, 208
SPAWN_PERIOD, START_LIVES, BURST_LIFE = 48, 3, 16
PARK_Y = 240
BUL_N, FOE_N, BUR_N = 7, 4, 4
# pool layout: base within the claim, then the field offsets
P_BUL, P_FOE, P_BUR = 0, 48, 96
F_ALIVE, F_X, F_Y, F_T = 0, 16, 32, 48
# OBJ tiles on the 16-wide grid
T_SHIP, T_FOE, T_BURST, T_BULLET = 0, 4, 8, 32
# the field
MAP_W, MAP_H, PLANET_SIDE, PLANET_BASE = 32, 32, 4, 1
BAR_TILE, BAR_ROWS = 65, 3
STAMP_X = (2, 20, 11, 26, 4, 17, 24, 9, 19, 6)
STAMP_Y = (1, 3, 6, 9, 12, 15, 19, 22, 26, 29)
STAMP_PL = (0, 16, 32, 48, 16, 0, 32, 48, 16, 32)
HUD_ROW, HUD_SCORE_C, HUD_SCORED_C = 1, 2, 8
HUD_LIVES_C, HUD_LIVESD_C = 18, 24
MSG_ROW0, MSG_ROW1, MSG_COL, MSG_W = 12, 14, 10, 11
BLINK_WINDOW = 10        # frames to cover one blink on/off cycle


# --- the SOURCE-ART oracle --------------------------------------------------
# Importing the generator rather than restating its numbers is deliberate, and
# it goes one step further than breaker's: the generator's own input is the
# PACK'S ORIGINAL PNGs, which nothing in this repo produced. So the chain
# `vendor/art/*.png -> generator -> ROM -> PPU -> screenshot` is checked end to
# end against something external, and cannot pass by agreeing with itself.
# That is the asset-import rule discharged at its root rather than by
# re-rendering our own output.
sys.path.insert(0, str(SUPERFORGE / "tools"))
import gen_shmup_assets as _GEN                                    # noqa: E402


def _snes8(c):
    """5-bit channel -> the 8-bit value the renderer produces.

    BIT REPLICATION, `(c << 3) | (c >> 2)`, not `round(c * 255/31)` — the
    difference is a count or two at low values and breaker's suite found it
    the honest way.
    """
    return (c << 3) | (c >> 2)


def _rgb5(word):
    return (word & 31), ((word >> 5) & 31), ((word >> 10) & 31)


# =============================================================================
# harness
# =============================================================================

def _tile(r, row, col, base):
    """One BG tilemap cell, as a tile id — the PPU's own input."""
    b = r.read_bytes(V, (base + row * 32 + col) * 2, 2)
    return (b[0] | b[1] << 8) & 0x3FF


def _map_words(r, base):
    raw = r.read_bytes(V, base * 2, 1024 * 2)
    return [(raw[i * 2] | raw[i * 2 + 1] << 8) for i in range(1024)]


def _text(r, row, col, n, base=None):
    """BG3 cells decoded back to ASCII. bg_text's mapping is glyph = ascii-$20
    and glyph n IS tile n, so this inverts the renderer exactly."""
    base = TXT_MAP if base is None else base
    raw = r.read_bytes(V, (base + row * 32 + col) * 2, n * 2)
    return "".join(chr(((raw[i * 2] | raw[i * 2 + 1] << 8) & 0x3FF) + 0x20)
                   for i in range(n))


def _oam(r, slot):
    """One OAM entry as (x_low, y, tile, attr) — the bytes the PPU reads."""
    return tuple(r.read_bytes(O, slot * 4, 4))


def _oam_all(r):
    """The whole OAM low table in ONE read, as 128 (x, y, tile, attr) tuples.

    A per-slot read is a round trip into the emulator, and a test that
    inspects sixteen slots on every frame of a few hundred pays it sixteen
    times over. The suite is emulator-bound, so the reads — not the frames —
    are what a sweep like that actually costs.
    """
    raw = r.read_bytes(O, 0, 512)
    return [tuple(raw[i * 4:i * 4 + 4]) for i in range(128)]


def _oam_settled(r, slot):
    """One OAM entry, after letting this tick's shadow reach hardware.

    HARDWARE OAM TRAILS THE GAME BY EXACTLY ONE FRAME, and it is the harness
    that makes it so: `frame_step` parks before the frame's VBlank, so the OAM
    GP-DMA that commits what the tick just wrote has not run yet. Measured,
    not assumed — with a direction held, OAM's x reads `px - SHIP_SPEED`.

    A test comparing OAM against a DP value (or against a position the game
    set THIS frame) steps one frame first. A test comparing OAM to OAM does
    not need to, which is why this is a separate helper and not the default.
    """
    r.frame_step(1)
    return _oam(r, slot)


def _clamp_to(r, index, want, sign, budget=500, **held):
    """Hold a direction until the ship parks against its clamp, checking every
    step that it never got PAST it.

    Two things make the naive "hold 120 frames, then read" version wrong, and
    both are real behaviour rather than flake: the ship BLINKS through its
    i-frames (so a bare read is a coin flip between the position and the
    parking row), and a fighter can ram it mid-hold and respawn it at the
    centre (so a fixed hold is not guaranteed to end at the edge). Retrying
    also makes the assertion STRONGER — "never past the clamp, on any frame"
    instead of "at the clamp on one chosen frame".

    `sign` is +1 when `want` is a maximum and -1 when it is a minimum.
    """
    for _ in range(budget):
        e = _oam(r, O_SHIP)
        if e[1] != PARK_Y:
            assert (e[index] - want) * sign <= 0, \
                f"the ship reached {e[index]}, past its clamp at {want}"
            if e[index] == want:
                return e
        r.frame_step(1, **held)
    raise AssertionError(f"the ship never reached its clamp at {want}")


def _oam_hi(r, slot):
    """The sprite's 2 bits of the hi table: bit 0 = X9, bit 1 = size."""
    byte = r.read_bytes(O, 512 + slot // 4, 1)[0]
    return (byte >> (slot % 4) * 2) & 3


def _cgram(r, base, n):
    raw = r.read_bytes(C, base * 2, n * 2)
    return [(raw[i * 2] | raw[i * 2 + 1] << 8) for i in range(n)]


def _dp(r, name):
    return r.read_u16(W, DP[name])


def _pool(r, base, slot, field=F_ALIVE):
    """A pool word. NAVIGATION ONLY — never the thing a test claims. Every
    assertion about an actor reads its OAM entry instead."""
    return r.read_u16(W, POOLS + base + field + slot * 2)


def _scene(r):
    return r.read_bytes(W, SM_CTL, 3)[0]


def _phase(r):
    return r.read_bytes(W, SM_CTL, 3)[2]


def _settle(r, want_scene, budget=300):
    """Advance until scene_mgr has landed on `want_scene` and stopped fading."""
    for _ in range(budget):
        if _scene(r) == want_scene and _phase(r) == 0:
            return
        r.frame_step(1)
    raise AssertionError(f"scene {want_scene} never went live (phase machine "
                         f"stuck at scene {_scene(r)} phase {_phase(r)})")


def _press_start(r):
    r.frame_step(2, start=True)
    r.frame_step(1)


def _goto_play(r):
    """Navigation, not assertion: leave the machine in a fresh play scene."""
    if _scene(r) != SCENE_TITLE:
        _press_start(r)
        _settle(r, SCENE_TITLE)
    _press_start(r)
    _settle(r, SCENE_PLAY)


def _shot(r, tmp_path, name):
    """A render, with the image row that IS scanline 0.

    Same letterbox anchor microzero's gradient suite established: the border is
    black and the 224-line content span has no black row inside it, so the
    first non-black row is scanline 0.
    """
    path = tmp_path / f"{name}.png"
    # settle_frames=0: a capture must not advance the machine, or a test that
    # measures motion BETWEEN two shots measures its own instrumentation too
    # (this cost a red: 18 px "in 16 frames", the extra two being one settle
    # frame at each end).
    r.take_screenshot(str(path), settle_frames=0)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    top = next(y for y in range(h)
               if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w)))
    return img, top


def _wait_for_foe(r, budget=200):
    """Navigation: run until a fighter is on screen. Returns its OAM slot."""
    for _ in range(budget):
        r.frame_step(1)
        oam = _oam_all(r)
        for k in range(FOE_N):
            if oam[O_FOES + k][1] != PARK_Y:
                return k
    raise AssertionError("no fighter appeared in the OAM within budget")


def _steer_to(r, target_x, budget=200, **held):
    """Navigation: walk the ship to a column, then hold `held` for a frame."""
    for _ in range(budget):
        px = _dp(r, "px")
        if abs(px - target_x) < SHIP_SPEED:
            break
        r.frame_step(1, right=(px < target_x), left=(px > target_x), **held)
    return _dp(r, "px")


@pytest.fixture(scope="module")
def r():
    assert ROM.exists(), f"{ROM} missing — run `make shmup`"
    run = MesenRunner()
    run.boot_rom(str(ROM), frames=90)
    run.debug_break()            # deterministic frame-stepping from here on
    yield run
    run.stop()


# =============================================================================
# 1. it boots, and the world is really there
#    done-condition: "boots; terrain + ship render"
# =============================================================================

def test_title_boots_and_renders_its_own_text(r):
    assert _scene(r) == SCENE_TITLE, "the boot scene is the title"
    _settle(r, SCENE_TITLE)
    assert _text(r, 8, 10, 13, TITLE_TXT_MAP) == "ASTRO BARRAGE"
    assert _text(r, 14, 10, 11, TITLE_TXT_MAP) == "PRESS START"


def test_title_parks_every_sprite(r):
    """Power-on + teardown contract. The title composes no OBJ feature at all,
    so anything visible in OAM here is either boot garbage (rule 5) or a
    sprite the play scene's exit failed to re-park."""
    _settle(r, SCENE_TITLE)
    for slot in range(O_SHIP, O_BURSTS + BUR_N):
        assert _oam(r, slot)[1] == PARK_Y, f"OAM slot {slot} is on screen"


def test_the_planet_field_is_the_declared_field(r):
    """The BG1 tilemap in VRAM, cell for cell, against the declared stamp
    geometry — not a spot check and not a hash of the ROM's own output.

    The oracle is built here from the three stamp tables and the generator's
    own page layout (planet p's cell (row, col) is tile 1 + p*16 + row*4 +
    col), so a stamp that landed at the wrong origin, a planet block read from
    the wrong base, or a wrap done with the wrong mask all fail.
    """
    _goto_play(r)
    m = [w & 0x3FF for w in _map_words(r, SHM_MAP)]

    want = [0] * (MAP_W * MAP_H)
    for sx, sy, pl in zip(STAMP_X, STAMP_Y, STAMP_PL):
        for cell in range(PLANET_SIDE * PLANET_SIDE):
            row, col = divmod(cell, PLANET_SIDE)
            dst = (((sy + row) % MAP_H) * MAP_W) + ((sx + col) % MAP_W)
            want[dst] = PLANET_BASE + pl + cell
    assert m == want, "the planet field is not the declared field"

    # ...and the field really is a field: ten distinct 4x4 blocks, nothing
    # blank where a stamp claims a cell, nothing stamped where none does.
    assert sum(1 for t in m if t) == len(STAMP_X) * PLANET_SIDE * PLANET_SIDE


def test_the_hud_band_is_three_rows_and_nothing_else(r):
    """BG2's whole tilemap: the band the HUD sits on, and transparency
    everywhere else. A band that filled the layer would hide the entire planet
    field behind it — the layer-occlusion failure this project has a
    lessons-learned entry about, which no BG1-only assertion can see."""
    _goto_play(r)
    m = _map_words(r, BAR_MAP)
    for row in range(MAP_H):
        for col in range(MAP_W):
            got = m[row * MAP_W + col]
            if row < BAR_ROWS:
                assert got & 0x3FF == BAR_TILE, f"band cell ({row},{col})"
                assert got & (1 << 13), f"band cell ({row},{col}) lost priority"
            else:
                assert got & 0x3FF == 0, f"cell ({row},{col}) is not transparent"


def test_the_hud_prints_its_labels_and_counters(r):
    _goto_play(r)
    assert _text(r, HUD_ROW, HUD_SCORE_C, 5) == "SCORE"
    assert _text(r, HUD_ROW, HUD_LIVES_C, 5) == "LIVES"
    assert _text(r, HUD_ROW, HUD_SCORED_C, 4) == "0000"
    assert _text(r, HUD_ROW, HUD_LIVESD_C, 1) == str(START_LIVES)


def test_the_ship_and_the_field_render_the_source_art(r, tmp_path):
    """The composited picture, against the ORIGINAL PACK PNGs.

    This is the asset ground truth. Every colour the frame
    shows for a planet or the ship must be one the generator derived from
    `vendor/art/spaceship_pack/*.png` — art nothing in this repo authored — so
    a converter that quantized wrongly, an upload that landed in the wrong
    CGRAM range, or a tilemap pointing at the wrong page all fail here even
    though each of them leaves a self-consistent ROM.
    """
    _goto_play(r)
    img, top = _shot(r, tmp_path, "field")

    # CGRAM first: the destination region, byte for byte against the blobs the
    # ROM links (sub-rule 3 — an upload path needs a destination-region test).
    for base, name in ((C_SHM_PAL, "shm_bg_pal.bin"),
                       (C_SHIP_PAL, "shm_ship_pal.bin"),
                       (C_FOE_PAL, "shm_foe_pal.bin"),
                       (C_BURST_PAL, "shm_burst_pal.bin")):
        blob = (SUPERFORGE / "build" / "assets" / name).read_bytes()
        want = [(blob[i * 2] | blob[i * 2 + 1] << 8) for i in range(16)]
        assert _cgram(r, base, 16) == want, f"{name} is not in CGRAM"

    # ...and the CHR the ROM links is what the generator makes of the PNGs —
    # re-derived here from vendor/art rather than trusted from build/assets.
    bg_chr, bg_pal = _GEN.build_bg()
    assets = SUPERFORGE / "build" / "assets"
    assert bg_chr == (assets / "shm_bg_chr.bin").read_bytes()
    assert bg_pal == (assets / "shm_bg_pal.bin").read_bytes()

    # Now the frame. Every pixel of a planet's bounding box is either the
    # backdrop or a colour from the BG palette the pack produced.
    allowed = {tuple(_snes8(c) for c in _rgb5(w))
               for w in _cgram(r, C_SHM_PAL, 16)}
    allowed.add(tuple(_snes8(c) for c in _rgb5(_cgram(r, 0, 1)[0])))
    seen = set()
    for y in range(BAR_ROWS * 8 + 8, 200):
        for x in range(0, 256, 3):
            seen.add(img.getpixel((x, top + y)))
    stray = seen - allowed
    # the sprites are the only other thing on screen; drop their palettes
    for base in (C_SHIP_PAL, C_FOE_PAL, C_BURST_PAL):
        stray -= {tuple(_snes8(c) for c in _rgb5(w))
                  for w in _cgram(r, base, 16)}
    assert not stray, f"the frame shows colours from no declared palette: {stray}"

    # ...and it is not a flat screen: the planets are actually drawn.
    assert len(seen) >= 8, "the field renders too few distinct colours to be art"


# =============================================================================
# 2. the world moves, and the ship does
#    done-condition: "terrain autoscrolls DOWN; ship moves in all four
#    directions, clamped"
# =============================================================================

def test_the_field_drifts_down_on_screen(r, tmp_path):
    """THE DIRECTION, ON PIXELS. BG1VOFS names where the VIEWPORT sits, so
    "the register decreased" is the mechanism and "the planets come toward the
    player" is the invariant — and they point opposite ways, which is how the
    first pass of shm_drift shipped an `inc` and flew the field upward.

    So this reads the rendered frame: pick the column with the most non-sky
    pixels, and measure how far ITS WHOLE PATTERN slid down over sixteen
    frames. It must be exactly the sixteen pixels one-per-frame promises.

    HOW IT MEASURES, and why not the obvious way. The first version tracked
    the column's TOPMOST non-sky pixel and asserted it gained 16. That is a
    proxy, and it is only equal to "the field moved 16" while nothing new
    enters the column from above — which is a property of the phase the shot
    happens to catch, not of the rail. It broke exactly there: a bare-check
    run (2026-08-05, full suite under xdist) reported "the field moved -35 px
    in 16 frames" with before=75 and after=40 — 40 being the first row of the
    search window, i.e. something now covered the top of the column and the
    estimator locked onto it instead of the planet it had been following.
    Nothing was wrong with the rail; the estimator was wrong.

    So match the PATTERN instead: build the column's non-sky profile in both
    shots and find the downward shift that lines them up best. An object
    entering the top perturbs a few rows of a 120-row profile and cannot move
    the argmax — measured: a planted 40 px intruder inside the compared window
    still resolves to 16 (score 85/120, and 16 is still the best d). The
    argmax is also unambiguous rather than nearly-tied: on a clean pair d=16
    scores 120/120 with the runners-up at 117.
    """
    _goto_play(r)
    img, top = _shot(r, tmp_path, "drift0")
    sky = img.getpixel((252, top + 120))

    col = max(range(0, 256, 4),
              key=lambda c: sum(1 for y in range(40, 200)
                                if img.getpixel((c, top + y)) != sky))

    def profile(im, t, lo, hi):
        return [im.getpixel((col, t + y)) != sky for y in range(lo, hi)]

    before = profile(img, top, 40, 160)
    assert any(before), "no planet found to track in the chosen column"

    r.frame_step(16)
    img2, top2 = _shot(r, tmp_path, "drift16")
    # The window in shot 2 runs to 200 so every candidate shift 0..32 has a
    # full 120 rows of shot 1 to compare against — an argmax taken over
    # differently-sized overlaps would favour the small ones.
    after = profile(img2, top2, 40, 200)

    scores = {d: sum(1 for i in range(120) if before[i] == after[i + d])
              for d in range(33)}
    moved = max(scores, key=lambda d: scores[d])
    assert moved == 16, (
        f"the field moved {moved} px in 16 frames; the rail promises +16 "
        f"(DOWN, 1 px/frame). profile match scores, best first: "
        f"{sorted(scores.items(), key=lambda kv: -kv[1])[:5]}")


def test_the_ship_moves_in_all_four_directions_and_clamps(r):
    """OAM bytes, not US_PX. Drives every direction AND both ends of both
    axes: a test that only walks one way locks that way and ships the other
    broken (AGENTS.md test discipline)."""
    _goto_play(r)
    home = _oam(r, O_SHIP)
    assert home[0] == SHIP_SPAWN_X and home[1] == SHIP_SPAWN_Y

    # Each direction moves at the declared speed. The window is a frame wide
    # because the FIRST frame of a held button is the one input_read turns
    # into `cur`, so a 10-frame hold buys 9 or 10 steps depending on where
    # frame_step's park lands relative to the read.
    def moved(before, after, n):
        assert abs(after - before) in (n * SHIP_SPEED, (n - 1) * SHIP_SPEED), \
            f"moved {abs(after - before)} px in {n} frames at speed {SHIP_SPEED}"

    x0 = _oam(r, O_SHIP)[0]
    r.frame_step(10, right=True)
    x1 = _oam_settled(r, O_SHIP)[0]
    assert x1 > x0, "right does not move the ship right"
    moved(x0, x1, 11)
    r.frame_step(10, left=True)
    x2 = _oam_settled(r, O_SHIP)[0]
    assert x2 < x1, "left does not move the ship left"
    y0 = _oam(r, O_SHIP)[1]
    r.frame_step(10, up=True)
    y1 = _oam_settled(r, O_SHIP)[1]
    assert y1 < y0, "up does not move the ship up"
    moved(y0, y1, 11)
    r.frame_step(10, down=True)
    assert _oam_settled(r, O_SHIP)[1] > y1, "down does not move the ship down"

    # the four clamps: hold each direction until the ship parks against it,
    # and check on EVERY frame of the hold that it never went past
    _clamp_to(r, 0, SHIP_MAX_X, +1, right=True)
    _clamp_to(r, 0, SHIP_MIN_X, -1, left=True)
    _clamp_to(r, 1, SHIP_MIN_Y, -1, up=True)
    _clamp_to(r, 1, SHIP_MAX_Y, +1, down=True)
    # ...and X9 stays clear the whole time: every clamp keeps x under 256
    assert _oam_hi(r, O_SHIP) == 2, "the ship must be LARGE with X9 clear"


def test_the_ships_engine_plume_animates(r):
    """The OAM TILE the PPU fetches, cycling — and the two frames it names are
    genuinely different CHR, which a tile-index-only assertion could not tell
    from a two-entry table pointing at the same art twice."""
    _goto_play(r)
    tiles = set()
    for _ in range(24):
        r.frame_step(1)
        tiles.add(_oam(r, O_SHIP)[2])
    assert tiles == {T_SHIP, T_SHIP + 2}, f"the plume does not cycle: {tiles}"

    chr_blob = (SUPERFORGE / "build" / "assets" / "shm_obj_chr.bin").read_bytes()

    def frame_bytes(t):
        return b"".join(chr_blob[i * 32:(i + 1) * 32]
                        for i in (t, t + 1, 16 + t, 16 + t + 1))
    assert frame_bytes(T_SHIP) != frame_bytes(T_SHIP + 2), \
        "the two animation frames are the same art"


# =============================================================================
# 3. firing
#    done-condition: "A spawns a bullet that travels up and dies at the top"
# =============================================================================

def test_a_press_spawns_one_bullet_that_climbs_and_expires(r):
    """A bullet's WHOLE life, in OAM: appear at the muzzle, climb at the
    declared speed, and be parked again once it passes the HUD band."""
    _goto_play(r)
    r.frame_step(4)
    parked = [s for s in range(O_BULLETS, O_BULLETS + BUL_N)
              if _oam(r, s)[1] == PARK_Y]
    assert len(parked) == BUL_N, "a round does not start with an empty magazine"

    px, py = _dp(r, "px"), _dp(r, "py")
    r.frame_step(2, a=True)
    r.frame_step(1)
    live = [s for s in range(O_BULLETS, O_BULLETS + BUL_N)
            if _oam(r, s)[1] != PARK_Y]
    assert len(live) == 1, f"one press must fire exactly one bullet, got {live}"
    slot = live[0]
    e = _oam(r, slot)
    assert e[2] == T_BULLET, "the bullet is not the bullet tile"
    assert _oam_hi(r, slot) == 0, "the bullet must be SMALL with X9 clear"
    assert e[0] == (px + BULLET_DX) & 0xFF, "the muzzle is off-centre"

    y0 = _oam(r, slot)[1]
    r.frame_step(5)
    y1 = _oam(r, slot)[1]
    assert y0 - y1 == 5 * BULLET_SPEED, \
        f"the bullet climbs {(y0 - y1) / 5} px/frame, not {BULLET_SPEED}"

    for _ in range(80):
        r.frame_step(1)
        if _oam(r, slot)[1] == PARK_Y:
            break
    else:
        raise AssertionError("the bullet never expired at the top")


def test_the_magazine_is_seven_and_a_full_pool_swallows_the_press(r):
    """POOL's capacity, asserted on the OAM SLOTS THE POOL OWNS — not on its
    alive array. Seven presses put seven bullets on screen; the eighth has
    nowhere to go and nothing else moves."""
    _goto_play(r)
    _steer_to(r, 120)
    # From the BOTTOM of the playfield, and one frame per shot: a bullet needs
    # (SHIP_MAX_Y - BULLET_DY - BULLET_TOP) / BULLET_SPEED frames to reach the
    # top, and the magazine only holds seven AT ONCE — fire slowly enough, or
    # from high enough, and the first has expired before the seventh exists.
    _clamp_to(r, 1, SHIP_MAX_Y, +1, down=True)
    for _ in range(BUL_N + 3):
        r.frame_step(1, a=True)
        r.frame_step(1)
    live = [s for s in range(O_BULLETS, O_BULLETS + BUL_N)
            if _oam(r, s)[1] != PARK_Y]
    assert len(live) == BUL_N, \
        f"the magazine should cap at {BUL_N} on screen, got {len(live)}"
    # ...and nothing spilled into a neighbouring feature's slots
    assert _oam(r, O_SHIP)[1] != PARK_Y, "the ship slot was overwritten"
    for s in range(O_FOES, O_FOES + FOE_N):
        assert _oam(r, s)[2] in (T_FOE, T_FOE + 2), \
            "a bullet was drawn into a fighter's slot"


# =============================================================================
# 4. the enemy
#    done-condition: "ghosts spawn, descend, die to bullets; SCORE counts up"
# =============================================================================

def test_fighters_spawn_descend_and_leave(r):
    """A fighter's whole life in OAM: it appears at the spawn row, descends at
    the declared speed, and is parked again once it passes the bottom."""
    _goto_play(r)
    k = _wait_for_foe(r)
    slot = O_FOES + k
    assert _oam(r, slot)[1] <= FOE_SPAWN_Y + FOE_SPEED, "spawned too low"
    assert _oam(r, slot)[2] in (T_FOE, T_FOE + 2), "not the fighter's art"
    assert _oam_hi(r, slot) & 2, "a fighter must be a LARGE sprite"

    y0 = _oam(r, slot)[1]
    r.frame_step(20)
    y1 = _oam(r, slot)[1]
    assert y1 - y0 == 20 * FOE_SPEED, \
        f"the fighter falls {(y1 - y0) / 20} px/frame, not {FOE_SPEED}"

    for _ in range(FOE_GONE_Y + 40):
        r.frame_step(1)
        if _oam(r, slot)[1] == PARK_Y:
            break
    else:
        raise AssertionError("the fighter never left at the bottom")


def test_a_bullet_kills_a_fighter_scores_and_bursts(r):
    """The kill, entirely in OAM and BG3: the fighter's slot parks, a BURST
    slot lights up at the kill site with the explosion's art, and the printed
    SCORE goes up. Reading the pool's alive words instead would pass while
    every one of those three renders wrong."""
    _goto_play(r)
    k = _wait_for_foe(r)
    slot = O_FOES + k
    before_score = _text(r, HUD_ROW, HUD_SCORED_C, 4)
    fx = _oam(r, slot)[0]
    _steer_to(r, fx - 2)

    for _ in range(90):
        if _oam(r, slot)[1] == PARK_Y:
            break
        r.frame_step(2, a=True)
        r.frame_step(2)
    else:
        raise AssertionError("the fighter survived a magazine at point blank")

    # a burst is on screen, at the kill site, drawn from the explosion sheet
    r.frame_step(1)
    bursts = [s for s in range(O_BURSTS, O_BURSTS + BUR_N)
              if _oam(r, s)[1] != PARK_Y]
    assert bursts, "a kill left no explosion"
    b = _oam(r, bursts[0])
    assert b[2] in (T_BURST, T_BURST + 2, T_BURST + 4, T_BURST + 6), \
        f"the burst's tile {b[2]} is not one of the explosion's four frames"
    assert (b[3] >> 1) & 7 == 2, "the burst must use OBJ palette 2"
    assert _oam_hi(r, bursts[0]) & 2, "a burst must be a LARGE sprite"

    # and the HUD says so
    for _ in range(8):
        r.frame_step(1)
    assert _text(r, HUD_ROW, HUD_SCORED_C, 4) != before_score, \
        "a kill did not reach the printed SCORE"
    assert _text(r, HUD_ROW, HUD_SCORED_C, 4).isdigit(), \
        "the BCD score printed a non-decimal glyph"


def test_a_burst_plays_all_four_frames_then_leaves(r):
    """The burst's WHOLE arc — every frame index, in order, then parked. A
    snapshot at spawn would pass while frames 1..3 never rendered."""
    _goto_play(r)
    k = _wait_for_foe(r)
    slot = O_FOES + k
    _steer_to(r, _oam(r, slot)[0] - 2)
    for _ in range(90):
        if _oam(r, slot)[1] == PARK_Y:
            break
        r.frame_step(2, a=True)
        r.frame_step(2)
    bursts = [s for s in range(O_BURSTS, O_BURSTS + BUR_N)
              if _oam(r, s)[1] != PARK_Y]
    assert bursts, "no burst to watch"
    b = bursts[0]
    seen, parked = [], False
    for _ in range(BURST_LIFE + 6):
        e = _oam(r, b)
        if e[1] == PARK_Y:
            parked = True
            break
        if not seen or seen[-1] != e[2]:
            seen.append(e[2])
        r.frame_step(1)
    assert parked, "the burst never freed its slot"
    assert seen == [T_BURST, T_BURST + 2, T_BURST + 4, T_BURST + 6], \
        f"the explosion's frames did not walk 0..3 in order: {seen}"


# =============================================================================
# 5. damage and the end
#    done-condition: "a ghost touching the ship costs a life (blink +
#    respawn); 0 lives = GAME OVER"
# =============================================================================

def _ram_a_fighter(r, budget=1200):
    """Navigation: steer into the nearest live fighter until LIVES changes.

    The ship stays LOW rather than climbing to meet them, which is not a
    preference — it is the only thing that works. A fighter descends at
    1 px/frame and the ship crosses at 2 px/frame, so intercepting needs the
    fighter to have most of the playfield still to fall; parked at
    SHIP_MIN_Y the overlap window is the ~24 frames before it falls past the
    ship's own 16 px, and the ship usually cannot cross in time. Measured:
    holding `up` here turned a reliable hit into three red tests.

    The per-frame cost is three emulator round trips (one bulk OAM read plus
    two DP words), down from ten — the reads were the expense, not the
    frames.
    """
    lives = _dp(r, "lives")
    for _ in range(budget):
        oam = _oam_all(r)
        tgt = next((oam[O_FOES + k][0] for k in range(FOE_N)
                    if oam[O_FOES + k][1] != PARK_Y), None)
        if tgt is None:
            r.frame_step(1)
        else:
            px = _dp(r, "px")
            r.frame_step(1, right=(px < tgt), left=(px > tgt))
        if _dp(r, "lives") != lives:
            return True
    return False


def test_a_collision_costs_a_life_blinks_and_respawns(r):
    _goto_play(r)
    before = _text(r, HUD_ROW, HUD_LIVESD_C, 1)
    assert _ram_a_fighter(r), "never managed to collide with a fighter"

    # the ship is back at spawn, in OAM (one frame for the shadow to land)
    e = _oam_settled(r, O_SHIP)
    assert (e[0], e[1]) in ((SHIP_SPAWN_X, SHIP_SPAWN_Y), (0, PARK_Y)), \
        f"the ship did not respawn at its spawn point: {e}"

    # ...it blinks: over the i-frames the ship's OAM Y is sometimes parked and
    # sometimes not. Neither alone is the invariant — "it flickers" is.
    states = set()
    for _ in range(24):
        r.frame_step(1)
        states.add(_oam(r, O_SHIP)[1] == PARK_Y)
    assert states == {True, False}, "the ship does not blink through i-frames"

    # ...and the printed counter went down
    for _ in range(6):
        r.frame_step(1)
    after = _text(r, HUD_ROW, HUD_LIVESD_C, 1)
    assert int(after) == int(before) - 1, \
        f"the printed LIVES went {before} -> {after}"


def test_zero_lives_is_game_over_and_freezes_the_world(r, tmp_path):
    _goto_play(r)
    for _ in range(START_LIVES):
        if _dp(r, "gover"):
            break
        _ram_a_fighter(r)
    assert _dp(r, "gover") == 1, "never reached GAME OVER"

    # the verdict, on BG3, one cell per frame — give the queue its 22 frames
    r.frame_step(40)
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W) == " GAME OVER "
    assert _text(r, MSG_ROW1, MSG_COL, MSG_W) == "PRESS START"
    assert _text(r, HUD_ROW, HUD_LIVESD_C, 1) == "0"

    # THE FREEZE IS A USER-VISIBLE INVARIANT: pixels stop moving. Asserted on
    # the rendered frame rather than on "the update was skipped", because the
    # thing the player sees is the field standing still.
    img_a, top_a = _shot(r, tmp_path, "frozen_a")
    r.frame_step(20)
    img_b, top_b = _shot(r, tmp_path, "frozen_b")
    row = top_a + 120
    strip_a = [img_a.getpixel((x, row)) for x in range(0, 256, 2)]
    strip_b = [img_b.getpixel((x, top_b + 120)) for x in range(0, 256, 2)]
    assert strip_a == strip_b, "the field is still drifting on the GAME OVER screen"


def test_start_restarts_through_the_title_with_a_fresh_round(r):
    """The restart trip. Asserted on what the player sees
    at the far end: a clear verdict area, a full LIVES counter, a zeroed
    SCORE, and every pool slot back off screen."""
    _goto_play(r)
    for _ in range(START_LIVES):
        if _dp(r, "gover"):
            break
        _ram_a_fighter(r)
    assert _dp(r, "gover") == 1, "never reached GAME OVER"

    _press_start(r)
    _settle(r, SCENE_TITLE)
    assert _text(r, 8, 10, 13, TITLE_TXT_MAP) == "ASTRO BARRAGE"
    _press_start(r)
    _settle(r, SCENE_PLAY)

    assert _text(r, HUD_ROW, HUD_SCORED_C, 4) == "0000"
    assert _text(r, HUD_ROW, HUD_LIVESD_C, 1) == str(START_LIVES)
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W) == " " * MSG_W, \
        "the GAME OVER banner survived the restart"
    for s in list(range(O_BULLETS, O_BULLETS + BUL_N)) + \
            list(range(O_FOES, O_FOES + FOE_N)) + \
            list(range(O_BURSTS, O_BURSTS + BUR_N)):
        assert _oam(r, s)[1] == PARK_Y, f"OAM slot {s} survived the restart"
    assert _oam(r, O_SHIP)[:2] == (SHIP_SPAWN_X, SHIP_SPAWN_Y)
    # ...and the field was rebuilt, not inherited
    assert _tile(r, STAMP_Y[0], STAMP_X[0], SHM_MAP) == PLANET_BASE + STAMP_PL[0]


# =============================================================================
# 6. POOL — the mechanism a later sweep debuts
# =============================================================================

def test_every_pool_slot_owns_its_oam_slot_for_the_whole_round(r):
    """THE STABLE-SLOT CONTRACT, which is the property every other test here
    leans on. Pool slot k must always be OAM slot k — never compacted, never
    reordered — so the assertion is that across a busy stretch of play, each
    OAM slot only ever holds art belonging to ITS pool.

    This is the POOL test that is not a proxy: it reads the OAM entries the
    pool owns, not the alive array that describes them."""
    _goto_play(r)
    ship, bullets, foes, bursts = set(), set(), set(), set()
    for i in range(240):
        if i % 6 == 0:
            r.frame_step(2, a=True, right=(i % 12 == 0), left=(i % 12 == 6))
        else:
            r.frame_step(1)
        oam = _oam_all(r)                      # one read, sixteen slots
        ship.add(oam[O_SHIP][2])
        bullets.update(oam[O_BULLETS + k][2] for k in range(BUL_N))
        foes.update(oam[O_FOES + k][2] for k in range(FOE_N))
        bursts.update(oam[O_BURSTS + k][2] for k in range(BUR_N))
    assert ship <= {T_SHIP, T_SHIP + 2}, f"the ship slot held {ship}"
    assert bullets == {T_BULLET}, f"a bullet slot held {bullets}"
    assert foes <= {T_FOE, T_FOE + 2}, f"a fighter slot held {foes}"
    assert bursts <= {T_BURST, T_BURST + 2, T_BURST + 4, T_BURST + 6}, \
        f"a burst slot held {bursts}"


def test_the_hi_table_is_rebuilt_whole_every_frame(r):
    """The four hi-table bytes this feature owns: SIZE per actor class and X9
    derived from x, for all sixteen slots at once. A stale X9 renders a sprite
    256 px away — the failure this project has a lessons-learned entry about —
    and it is only invisible while nothing crosses x=256."""
    _goto_play(r)
    r.frame_step(4)
    for k in range(BUL_N):
        assert _oam_hi(r, O_BULLETS + k) & 2 == 0, "a bullet must be SMALL"
    assert _oam_hi(r, O_SHIP) & 2, "the ship must be LARGE"
    for k in range(FOE_N):
        assert _oam_hi(r, O_FOES + k) & 2, "a fighter must be LARGE"
    for k in range(BUR_N):
        assert _oam_hi(r, O_BURSTS + k) & 2, "a burst must be LARGE"

    # X9 tracks x, and it tracks it DOWN as well as up: park the ship at the
    # right clamp (x = 224, bit 8 clear) and confirm nothing latched.
    _clamp_to(r, 0, SHIP_MAX_X, +1, right=True)
    assert _oam_hi(r, O_SHIP) & 1 == 0, "X9 set for a sprite at x=224"

    # ...and the two bytes belonging to the bullets never acquire size bits,
    # which is what the four-whole-bytes rebuild exists to guarantee.
    byte1 = r.read_bytes(O, 512 + (O_BULLETS + 3) // 4, 1)[0]
    assert byte1 & 0xAA == 0, "a bullet-only hi byte grew a size bit"


def test_the_pools_are_defined_before_their_first_reader(r):
    """Power-on fidelity (rule 5). shm_pool_init writes every alive word of
    every pool in the scene's enter, so the first frame the player sees has an
    empty magazine and no fighters — asserted where the player would see it,
    in OAM, on the very first settled frame of a round."""
    _goto_play(r)
    for s in list(range(O_BULLETS, O_BULLETS + BUL_N)) + \
            list(range(O_FOES, O_FOES + FOE_N)) + \
            list(range(O_BURSTS, O_BURSTS + BUR_N)):
        assert _oam(r, s)[1] == PARK_Y, \
            f"OAM slot {s} is live on the first frame of a round"
