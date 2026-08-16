"""scroll_run — the page-seam world, asserted against what was drawn.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(90)`,
which lands on the ABSOLUTE frame 90 by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own done-conditions:

    - boots; camera clamped at 0 (left edge); player at rest on the floor
    - running right scrolls the camera once past screen-center, revealing
      right-page content; camera clamps at 256 at the right edge
    - the seam platform (cols 30..34) is land-on-able; pillars block
    - touching the goal pillar (world x ~480..487) -> GOAL text + freeze

Those are the test surface, plus the spec row 9's reason the rail is in
the sweep at all: THE PAGE SEAM — 512 px of world on two 256 px hardware
pages, with collision that stays correct across the boundary. In SuperForge the
collision half is correct BY CONSTRUCTION (col_map probes the world blob in
world coordinates; there is no page in its coordinate space), so the seam
lives in exactly one place — sr_bg's two-page display build — and the
state-cycle rule lands here hardest: the seam is CROSSED forward AND
backward AND rested exactly ON, on both the physics surface (hardware OAM
against a whole-game oracle) and the display surface (the seam columns' VRAM
words on both pages, and the drawn strip's pixel continuity across the
boundary). A seam walked one way ships the other broken — the repo's
founding streaming lesson.

THE ORACLE. Every driven case compares hardware OAM (x, y) per frame against
an independent Python re-implementation of the whole game tick — input edge,
horizontal move + world clamp + box probe, the grounded-gated fixed jump,
The reference integrator INCLUDING its one-way arms (the goal tile carries the
kit's platform bit), the goal probe, the camera follow and the world -
camera subtraction. The level itself is REBUILT in-module from the level
header's prose facts (shared code with the generator: none), so a generator
bug and an ASM bug cannot agree with each other here.

FRAME ACCOUNTING (measured on this ROM, matching camera_follow/jumper's
convention): the pad latched by `advance` is polled at every boundary, so
WRAM state after advance(N, pad) reflects N ticks; hardware OAM is ONE
commit behind (advance(5, right) from px 16 reads OAM 24 with WRAM 26; one
released settle frame closes the gap). The oracle comparison therefore reads
OAM after each single-frame advance and compares against the PREVIOUS
tick's staged position. OAM is read at the park BEFORE any screenshot — a
parked OAM read and the NEXT shot describe the same committed frame, while
a read AFTER a shot is one commit ahead.

THE PERIODIC-BG TRAP (the review lesson, aimed at this rail): the floor
rows are UNIFORM grey for all 64 columns, so any displacement correlation on
a floor window is degenerate — a solid strip shifted 2 px is byte-identical.
No case below recovers camera motion by correlation. Where the camera's
position matters, it is asserted through world->screen PIXEL PREDICTIONS at
content edges the level makes unique (the pillar/platform/goal boundaries),
through OAM against the oracle, and through byte-identity claims only on
windows that contain a non-uniform feature edge.
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
ROM = BUILD / "scroll_run.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "sr" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="run"):
    pool = (MAP["scenes"][scene]["placements"] if scene else MAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_SR_CHR")["start"]            # BG CHR page, VRAM words
V_MAP = _sym("ES_V_SR_MAP")["start"]            # 64x32 tilemap base (page 0)
V_OBJ = _sym("ES_V_SR_OBJ_CHR")["start"]        # OBJ CHR page, VRAM words
V_TXT_MAP = _sym("ES_V_TEXT_MAP")["start"]      # BG3 text tilemap base
C_PAL = _sym("ES_C_SR_PAL")["start"]            # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_SR_OBJ_PAL")["start"]        # OBJ palette 0, CGRAM words
C_TXT = _sym("ES_C_TEXT_PAL")["start"]          # BG3 palette 7 (words 28..31)

_DP = {p["sym"]: p["start"]
       for p in MAP["scenes"]["run"]["placements"] if p["class"] == "dp"}
DP_PX, DP_STATE = _DP["US_PX"], _DP["US_STATE"]
OAM_SHADOW = _sym("ES_OAM_SHADOW", scene=None)["start"]

# --- the rail's geometry (game/scroll_run/scroll_run.inc, re-derived) --------
PAGE_WORDS = 0x400                      # one 32x32 hardware page
WORLD_COLS, WORLD_ROWS = 64, 32         # tiles (rows 28..31 pad)
LEVEL_ROWS = 28
SEAM_COL = 32                           # world tile column of the page seam
SEAM_X = SEAM_COL * 8                   # world pixel x of the seam (256)
SPEED = 2                               # run px/frame
GRAVITY, MAX_FALL, JUMP_VEL = 0x40, 0x400, 0x480    # 8.8 (sf_physics defaults)
WORLD_W = 512
PLAYER_MAX_X = WORLD_W - 8              # 504
CAM_MAX = WORLD_W - 256                 # 256
HALF_W = 128
SPAWN_X, SPAWN_Y = 16, 200
GOAL_ROW, GOAL_COL = 12, 14             # BG3 cell of the GOAL print
TXT_ATTR = (7 << 10) | (1 << 13)

# --- the picture -------------------------------------------------------------
# Mesen hands back a 256x239 frame; the active 224 scanlines start at PNG row
# 7 (the sibling rails' measured constant, the spec, re-pinned here by
# test_boot_frame: the floor's top boundary at world y 208 must sit at PNG
# row 215, and the sprite with OAM Y 200 must occupy rows 207..214).
PIC_Y0, PIC_H, PIC_W = 7, 224, 256

# BGR555 -> the 8-bit RGB Mesen emits ((v << 3) | (v >> 2) per channel).
def _rgb(bgr):
    r, g, b = bgr & 31, (bgr >> 5) & 31, (bgr >> 10) & 31
    return tuple((v << 3) | (v >> 2) for v in (r, g, b))


GREY = _rgb(0x39CE)                     # terrain — the reference's BG_GREY
GOLD = _rgb(0x035F)                     # goal pillar — BG_GOLD
RED = _rgb(0x001F)                      # the runner — OBJ_RED
WHITE = _rgb(0x7FFF)                    # the GOAL text ink
BLACK = (0, 0, 0)

BOOT = 90                               # an absolute frame, well past the fade


# =============================================================================
# The level, REBUILT from the level's own bounds (main.asm:16-19) —
# deliberately a different expression from the generator's .repeat transcription
# =============================================================================
def tile_at(col, row):
    if not (0 <= col < WORLD_COLS and 0 <= row < WORLD_ROWS):
        raise IndexError((col, row))
    if row >= LEVEL_ROWS:
        return 0                        # pad rows (never shown; probed as 0)
    if row in (26, 27):
        return 2                        # the floor
    if col in (0, 63):
        return 2                        # the world borders
    if col == 14 and 22 <= row <= 25:
        return 2                        # the short pillar
    if col == 44 and 20 <= row <= 25:
        return 2                        # the tall pillar
    if row == 22 and (24 <= col <= 27 or 38 <= col <= 41):
        return 2                        # the two low platforms
    if row == 20 and 30 <= col <= 34:
        return 2                        # THE SEAM PLATFORM (crosses col 32)
    if col == 60 and 24 <= row <= 25:
        return 3                        # the gold goal pillar
    return 0


FLAGS = {0: 0, 2: 0x01, 3: 0x02}        # tile id -> flag byte (sr_flags)


def flag_at(px, py):
    """col_map's own totality: mask, never bound."""
    return FLAGS[tile_at((px >> 3) & (WORLD_COLS - 1),
                         (py >> 3) & (WORLD_ROWS - 1))]


# =============================================================================
# The oracle: the whole game tick, independently re-implemented
# =============================================================================
class Oracle:
    """One instance = one run of the game from the spawn. step(pad) is one
    tick; the staged draw position is (scrx, pyi) after the step."""

    def __init__(self):
        # The BOOT REST: the state after Machine(rom).advance(90) — not the
        # enter's raw spawn. The enter writes grounded = 0 (the reference's own
        # init) and the first falling tick's ground probe lands it; by frame
        # 90 the runner has long been standing, so the oracle starts there.
        self.px = SPAWN_X
        self.pyf = SPAWN_Y << 8
        self.vy = 0                     # u16 two's complement
        self.grounded = 1
        self.state = 0
        self.prev = frozenset()
        self.cam = 0
        self.scrx = SPAWN_X
        self.pyi = SPAWN_Y

    # -- probes ---------------------------------------------------------------
    @staticmethod
    def _solid_box(x, y):
        return any(flag_at(cx, cy) & 1
                   for cx in (x, x + 7) for cy in (y, y + 7))

    @staticmethod
    def _plat_edge(x, yrow):
        return any(flag_at(cx, yrow) & 2 for cx in (x, x + 7))

    # -- one frame ------------------------------------------------------------
    def step(self, pad=frozenset()):
        pad = frozenset(pad)
        press = pad - self.prev
        self.prev = pad
        if self.state == 0:
            self.pyi = self.pyf >> 8
            self._horizontal(pad)
            if "a" in press and self.grounded:
                self.vy = (0x10000 - JUMP_VEL) & 0xFFFF
                self.grounded = 0
            self._physics()
            self.pyi = self.pyf >> 8
            if flag_at(self.px + 4, self.pyi + 4) & 2:
                self.state = 1
        # the draw path runs in BOTH states (won: camera holds, runner drawn)
        self.cam = min(max(self.px - HALF_W, 0), CAM_MAX)
        self.scrx = (self.px - self.cam) & 0xFFFF
        return self

    def _horizontal(self, pad):
        newx = self.px
        if "right" in pad:
            newx += SPEED
        if "left" in pad:
            newx -= SPEED
        newx = min(max(newx, 0), PLAYER_MAX_X)      # sf_clamp0 (signed-aware)
        if not self._solid_box(newx, self.pyi):
            self.px = newx

    def _physics(self):
        if self.vy & 0x8000:                        # rising
            self.grounded = 0
            self.vy = (self.vy + GRAVITY) & 0xFFFF
            tent = (self.pyf + self.vy) & 0xFFFF
            by = tent >> 8
            if self._solid_box(self.px, by):
                self.pyf = (((by & ~7) + 8) << 8) & 0xFFFF   # head bump
                self.vy = 0
            else:
                self.pyf = tent
            return
        # falling arm: stable ground probe first
        cur = self.pyf >> 8
        if self._solid_box(self.px, cur + 1):
            self.vy = 0
            self.grounded = 1
            self.pyf &= 0xFF00
            return
        # one-way stand: resting EXACTLY on a bit-1 top (pixel-aligned only)
        if (cur & 7) == 0 and self._plat_edge(self.px, cur + 8):
            self.vy = 0
            self.grounded = 1
            self.pyf &= 0xFF00
            return
        # integrate, terminal-clamped
        self.vy = min(self.vy + GRAVITY, MAX_FALL)
        tent = (self.pyf + self.vy) & 0xFFFF
        by = tent >> 8
        if self._solid_box(self.px, by):
            self.pyf = ((((by + 7) & ~7) - 8) << 8) & 0xFFFF  # landing snap
            self.vy = 0
            self.grounded = 1
            return
        # one-way: land only when CROSSING a bit-1 top from above
        yb = by + 7
        topy = yb & ~7
        if (cur + 8) <= topy and self._plat_edge(self.px, yb):
            self.pyf = ((topy - 8) << 8) & 0xFFFF
            self.vy = 0
            self.grounded = 1
            return
        self.pyf = tent
        self.grounded = 0


def run_lockstep(m, oracle, script, tag=""):
    """Drive ROM and oracle together, one frame at a time; hardware OAM (the
    output region) must equal the oracle's PREVIOUS tick's staged position on
    every frame (the one-commit presentation lag, measured in the header)."""
    frame = 0
    for frames, pad in script:
        for _ in range(frames):
            before = (oracle.scrx, oracle.pyi)
            m.advance(1, pad1={k: True for k in pad})
            oracle.step(pad)
            frame += 1
            got = tuple(m.read_bytes(O, 0, 2))
            assert got == before, (
                f"{tag} frame {frame}: hardware OAM {got} != oracle "
                f"{before} (px={oracle.px} pyf={oracle.pyf:#06x} "
                f"vy={oracle.vy:#06x} grounded={oracle.grounded})")
    return frame


def settle(m, oracle, frames=1):
    run_lockstep(m, oracle, [(frames, frozenset())], "settle")


# =============================================================================
# fixtures + helpers
# =============================================================================
@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make scroll_run` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


def _pixels(machine, name):
    path = machine.take_screenshot(str(BUILD / "shots" / f"sr_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _tilemap_words(m):
    raw = bytes(m.read_bytes(V, V_MAP * 2, 2 * PAGE_WORDS * 2))
    return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]


def _goal_cells(m):
    base = (V_TXT_MAP + GOAL_ROW * 32 + GOAL_COL) * 2
    raw = bytes(m.read_bytes(V, base, 8))
    return [raw[i] | (raw[i + 1] << 8) for i in range(0, 8, 2)]


GOAL_WORDS = [(ord(ch) - ord(' ')) | TXT_ATTR for ch in "GOAL"]
EMPTY_CELLS = [TXT_ATTR] * 4            # text_clear_map fills attr | space(0)


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base vs sr_bg_chr.bin — all four tiles,
    including the two EMPTY ones (rule 5: uploaded explicitly, so the whole
    claim is read, not just the tiles that show a colour)."""
    want = (ASSETS / "sr_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"the BG character block at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "sr_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_all_three_palettes_reach_their_claimed_words(fresh):
    """CGRAM at all three claimed bases: BG group 0 and OBJ palette 0 against
    their blobs; BG3 palette 7 against the enter code's four authored words —
    including word 31, the glyph ink, which the first cut of this build left to
    the power-on RNG (GOAL rendered green under the default seed until the
    whole claim was written — the rule-5 catch recorded in scenes/run.asm)."""
    for label, base, blob in (("bg", C_PAL, "sr_bg_pal.bin"),
                              ("obj", C_OBJ, "sr_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")
    raw = bytes(fresh.read_bytes(C, C_TXT * 2, 8))
    got = [raw[i] | (raw[i + 1] << 8) for i in range(0, 8, 2)]
    assert got == [0x0000, 0x2952, 0x56B5, 0x7FFF], (
        f"BG3 palette words 28..31 are {[hex(w) for w in got]} — the text "
        f"claim is not fully authored (word 31 is the glyph ink)")


def test_tilemap_both_pages_are_the_level_split_at_the_seam(fresh):
    """All 2,048 tilemap words vs the level RE-DERIVED in-module: page 0 word
    r*32+c must be tile_at(c, r), page 1 word 0x400+r*32+c must be
    tile_at(c + 32, r) — the display transform whose whole content is the
    seam split. Every cell, both pages, because a page-offset bug leaves one
    page perfect and the other silently showing the wrong half of the world."""
    words = _tilemap_words(fresh)
    bad = []
    for row in range(WORLD_ROWS):
        for col in range(WORLD_COLS):
            page, pcol = divmod(col, 32)
            got = words[page * PAGE_WORDS + row * 32 + pcol]
            if got != tile_at(col, row):
                bad.append((col, row, got))
    assert not bad, (
        f"{len(bad)} of 2048 tilemap cells disagree with the level; "
        f"first 8: {bad[:8]}")


def test_the_seam_columns_hold_the_platform_on_both_pages(fresh):
    """THE NAMED SEAM ASSERTION (the brief's own demand): the seam platform
    (row 20, world cols 30..34) must put tile 2 in page 0's LAST columns
    (30, 31) and page 1's FIRST columns (32, 33, 34), with the air cells
    either side (29, 35) empty on their respective pages — the five words
    that make one platform out of two hardware pages. Plus the same fact
    where every world row crosses: the floor rows and the borders."""
    words = _tilemap_words(fresh)

    def w(col, row):
        page, pcol = divmod(col, 32)
        return words[page * PAGE_WORDS + row * 32 + pcol]

    # the seam platform, cell by cell, across the boundary
    assert w(29, 20) == 0, "world col 29 row 20 should be air (page 0)"
    assert w(30, 20) == 2 and w(31, 20) == 2, (
        "the seam platform's page-0 half (cols 30..31) is missing")
    assert w(32, 20) == 2 and w(33, 20) == 2 and w(34, 20) == 2, (
        "the seam platform's page-1 half (cols 32..34) is missing")
    assert w(35, 20) == 0, "world col 35 row 20 should be air (page 1)"
    # the floor crosses the seam on both rows
    for row in (26, 27):
        assert w(31, row) == 2 and w(32, row) == 2, (
            f"the floor row {row} does not cross the seam")
    # the borders: page 0's first column, page 1's last
    assert w(0, 10) == 2 and w(63, 10) == 2, "world border columns missing"


# =============================================================================
# 2. THE PICTURE — the composited boot frame (done-condition 1)
# =============================================================================

def test_boot_frame_left_clamp_player_at_rest(fresh):
    """Camera clamped at 0, player at rest on the floor — asserted on BOTH
    surfaces at once, with an EXACT census: 100 visible solid cells x 64 px
    of grey (counted from the re-derived level over world cols 0..31), a
    solid 64-px red sprite at screen (16..23, PNG 207..214), everything else
    backdrop. The sprite row also pins PIC_Y0; the floor's top boundary at
    PNG row 215 and the left border's right edge at x 8 pin the VOFS -1 and
    HOFS-exact conventions against the drawn world."""
    assert tuple(fresh.read_bytes(O, 0, 2)) == (SPAWN_X, SPAWN_Y), (
        "OAM entry 0 is not the spawn rest position")
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    want_grey = 64 * sum(
        1 for c in range(32) for r in range(LEVEL_ROWS) if tile_at(c, r) == 2)
    n_grey, n_red = pic.count(GREY), pic.count(RED)
    n_black = pic.count(BLACK)
    assert n_red == 64, f"expected the solid 8x8 red runner, got {n_red} red px"
    assert n_grey == want_grey, (
        f"{n_grey} grey pixels on screen, expected exactly {want_grey} "
        f"(= the level's visible solid cells at cam 0)")
    assert n_grey + n_red + n_black == PIC_W * PIC_H, (
        "the boot picture holds colours other than backdrop/terrain/runner")
    reds = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
            for x in range(PIC_W) if _at(px, x, y) == RED]
    xs, ys = [p[0] for p in reds], [p[1] for p in reds]
    assert (min(xs), max(xs), min(ys), max(ys)) == (16, 23, 207, 214), (
        f"runner bbox ({min(xs)}..{max(xs)}, {min(ys)}..{max(ys)}) is not "
        f"the spawn (16..23, 207..214)")
    # world-origin conventions, against drawn content edges:
    assert _at(px, 100, 214) == BLACK and _at(px, 100, 215) == GREY, (
        "the floor's top boundary is not at PNG row 215 — VOFS -1 dropped?")
    assert _at(px, 7, 100) == GREY and _at(px, 8, 100) == BLACK, (
        "the left border's right edge is not at x 8 — HOFS not exact?")


def test_boot_idle_holds_the_picture_still(boot):
    """The idle state: 60 frames of nothing must change nothing."""
    m = boot()
    a = _pixels(m, "idle_a")
    m.advance(60)
    b = _pixels(m, "idle_b")
    assert a == b, (
        f"the picture moved over 60 idle frames — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


# =============================================================================
# 3. THE ORACLE DRIVES — walk, wall, jump (done-condition 3's "pillars block")
# =============================================================================

def test_walk_to_the_first_pillar_wall_stops_the_run(boot):
    """60 frames of held right from the spawn: the runner walks 16 -> 104 and
    wall-stops against the short pillar (world col 14 at x 112) — hardware
    OAM equal to the oracle on EVERY frame, and the rest position exact: the
    camera is still left-clamped here (px < 128), so screen x IS world x."""
    m, o = boot(), Oracle()
    run_lockstep(m, o, [(60, {"right"})], "wall")
    settle(m, o)
    assert o.px == 104, "oracle sanity: the pillar stop is world x 104"
    assert tuple(m.read_bytes(O, 0, 2)) == (104, 200), (
        "the runner did not wall-stop against the pillar at (104, 200)")


def test_the_fixed_jump_arc_and_its_fixed_height(boot):
    """The whole stationary jump on hardware OAM vs the oracle, frame by
    frame: take-off, ascent, apex EXACTLY 39 px above rest (y 161), descent,
    the landing frame, the grounded tail back at EXACTLY the rest y. Then the
    rail's FIXED-HEIGHT property (the README's contrast with the platformer's
    hold-for-higher jump): a 1-frame tap and a 30-frame hold must produce the
    IDENTICAL 51-frame OAM trace — one edge-gated take-off, no cut, no
    auto-rejump on the held landing."""
    m, o = boot(), Oracle()
    tap_trace = []
    for i in range(51):
        pad = {"a"} if i == 0 else frozenset()
        before = (o.scrx, o.pyi)
        m.advance(1, pad1={k: True for k in pad})
        o.step(pad)
        got = tuple(m.read_bytes(O, 0, 2))
        assert got == before, (
            f"tap frame {i}: OAM {got} != oracle {before} "
            f"(pyf={o.pyf:#06x} vy={o.vy:#06x})")
        tap_trace.append(got)
    ys = [p[1] for p in tap_trace]
    assert min(ys) == 161, f"apex {min(ys)} != 161 (39 px above rest 200)"
    assert ys[-1] == 200 and o.grounded == 1, "did not land back at rest"
    assert ys[-5:] == [200] * 5, "the rest tail is not stable"
    # fixed height: hold A for 30 frames — the trace must be identical
    m2 = boot()
    hold_trace = []
    for i in range(51):
        m2.advance(1, pad1={"a": True} if i < 30 else None)
        hold_trace.append(tuple(m2.read_bytes(O, 0, 2)))
    assert hold_trace == tap_trace, (
        "holding A changed the arc — the jump is not fixed-height (or a "
        "held press re-fired: the edge gate is broken)")


# =============================================================================
# 4. THE SEAM — crossed forward, crossed backward, rested exactly ON
# =============================================================================
# The route to the seam neighbourhood: stall-jump over the short pillar
# (the reference bot's own recovery move), then run the open floor. Everything
# below is oracle-locked per frame, so a phantom wall AT the seam — the
# classic wrong-page probe failure — diverges loudly at the exact frame.

def _script_to_seam_area():
    """Spawn -> past the pillar -> px 240: right + a timed jump at the wall."""
    return [(44, {"right"}),            # walk 16 -> 104, wall-stop
            (1, {"a", "right"}),        # take off against the pillar face
            (40, {"right"}),            # clear it (the box slides free once
                                        #   its rows clear the pillar), land
            (37, {"right"})]            # ... run the floor to px 240


def test_the_seam_is_crossed_forward_and_backward_on_the_floor(boot):
    """Forward: run px 240 -> 280 across the seam at 256; every frame the box
    (px..px+7) spans tiles on both hardware pages while OAM tracks the oracle
    exactly — mid-tracking, so scrx is PINNED at 128 while the WORLD slides:
    the sprite surface proves the physics never hitched, and the equality
    itself is what rules out the phantom seam wall. Backward: the same
    crossing in reverse, back past 240. Then out-and-back byte-identity: the
    frame at the end equals a fresh drive to the same world position."""
    m, o = boot(), Oracle()
    run_lockstep(m, o, [*_script_to_seam_area()], "approach")
    settle(m, o)
    assert o.px == 240 and o.grounded == 1, (
        f"route sanity: expected rest at px 240, oracle at {o.px}")
    # forward across the seam (240 -> 280): 20 held frames
    run_lockstep(m, o, [(20, {"right"})], "seam-fwd")
    assert o.px == 280, "oracle sanity: crossed to 280"
    # backward across it (280 -> 240)
    run_lockstep(m, o, [(20, {"left"})], "seam-back")
    settle(m, o)
    assert o.px == 240, "oracle sanity: back at 240"
    assert tuple(m.read_bytes(O, 0, 2)) == (o.scrx, o.pyi) == (128, 200), (
        "after the out-and-back the runner is not centred at rest")


def test_resting_exactly_on_the_seam_holds_still(boot):
    """Rest ON the seam: walk to px 252 — the box spans 252..259, world
    pixels on BOTH pages — release everything and idle 30 frames. The
    position must hold (OAM byte-stable at the oracle's rest) and the
    PICTURE must hold with it: the drawn frame is byte-identical across the
    idle, and the seam platform's strip above the runner (row 20, world x
    240..279 -> screen 116..155 at cam 124) is one CONTINUOUS grey run with
    air at both ends — the seam invisible in the composited output."""
    m, o = boot(), Oracle()
    run_lockstep(m, o, [*_script_to_seam_area(), (6, {"right"})], "to-252")
    settle(m, o)
    assert o.px == 252 and o.cam == 124, (
        f"route sanity: expected the straddle rest at px 252 cam 124, "
        f"oracle at {o.px} cam {o.cam}")
    assert tuple(m.read_bytes(O, 0, 2)) == (128, 200)
    a = _pixels(m, "seam_rest_a")
    run_lockstep(m, o, [(30, frozenset())], "seam-idle")
    b = _pixels(m, "seam_rest_b")
    assert a == b, "the picture moved while resting on the seam"
    # the seam platform strip, drawn continuous across the page boundary:
    # world y 160..167 -> PNG rows 167..174; the seam itself at screen 132
    for y in (167 + PIC_Y0 - 7, 174 + PIC_Y0 - 7):
        pass  # (rows computed below; loop kept explicit for the reader)
    row = 160 + PIC_Y0  # world y 160 at cam_y 0 -> PNG row 167
    for x in range(116, 156):
        assert _at(b, x, row) == GREY, (
            f"seam platform pixel at screen x {x} is not grey — the drawn "
            f"strip breaks at the page boundary (seam at screen 132)")
    assert _at(b, 115, row) == BLACK and _at(b, 156, row) == BLACK, (
        "the seam platform strip does not end in air on both sides")


def test_the_seam_platform_is_landed_on_and_walked_off(boot):
    """Done-condition 3's first half, driven as the full state cycle: jump
    from the floor onto the low platform (24..27), from there onto THE SEAM
    PLATFORM, come to rest EXACTLY straddling the seam (px 252: box pixels
    252..259 = world columns 31 AND 32, rest y 152), idle on it, then walk
    off its left edge and fall back to the floor — landing, rest-on, and
    leave, all oracle-locked per frame. The resting stand probes BOTH pages
    every frame (left corner col 31, right corner col 32): a probe that
    lost either page drops the runner mid-idle and diverges loudly.

    The scripts are oracle-derived (searched in pure Python over the same
    integrator, then frozen here); the ROM must reproduce the searched
    trajectory exactly, landing frames included."""
    m, o = boot(), Oracle()
    run_lockstep(m, o, [*_script_to_seam_area()], "approach")
    # walk BACK under the seam platform to the 24..27 takeoff — the reverse
    # walk is more seam traffic, deliberately
    run_lockstep(m, o, [(35, {"left"})], "back-to-170")
    settle(m, o)
    assert o.px == 170 and o.grounded == 1, "route sanity: takeoff at 170"
    # leg 1: onto the low platform (rest y 168 at px 192)
    run_lockstep(m, o, [(1, {"a", "right"}), (13, {"right"})], "hop-up")
    run_lockstep(m, o, [(40, frozenset())], "hop-coast")
    assert (o.px, o.pyi, o.grounded) == (192, 168, 1), (
        f"route sanity: expected rest ON platform 24..27 at (192, 168), "
        f"oracle at ({o.px}, {o.pyi}) grounded={o.grounded}")
    assert tuple(m.read_bytes(O, 0, 2)) == (o.scrx, 168)
    # leg 2: from the platform to THE SEAM PLATFORM, landing at px 252 —
    # the straddle itself is the landing target
    run_lockstep(m, o, [(8, {"right"})], "to-edge-208")
    run_lockstep(m, o, [(1, {"a", "right"}), (21, {"right"})], "seam-jump")
    run_lockstep(m, o, [(30, frozenset())], "seam-coast")
    assert (o.px, o.pyi, o.grounded) == (252, 152, 1), (
        f"route sanity: expected rest ON the seam platform straddling the "
        f"seam at (252, 152), oracle ({o.px}, {o.pyi}) gr={o.grounded}")
    rest = tuple(m.read_bytes(O, 0, 2))
    assert rest == (o.scrx, 152) == (128, 152), (
        "the runner is not resting on the seam platform at screen centre")
    run_lockstep(m, o, [(20, frozenset())], "seam-plat-idle")
    assert tuple(m.read_bytes(O, 0, 2)) == rest, (
        "the runner did not HOLD its rest straddling the seam — the "
        "standing probe lost a page")
    # leg 3: walk off the LEFT edge (support ends once px + 7 < 240) and
    # fall to the floor — the reverse exit
    run_lockstep(m, o, [(14, {"left"})], "walk-off")
    run_lockstep(m, o, [(40, frozenset())], "fall-coast")
    settle(m, o)
    assert (o.px, o.pyi, o.grounded) == (224, 200, 1), (
        f"route sanity: expected the floor after the walk-off, oracle at "
        f"({o.px}, {o.pyi})")
    assert tuple(m.read_bytes(O, 0, 2)) == (o.scrx, 200)


# =============================================================================
# 5. THE CAMERA — the three regimes on drawn content (done-condition 2)
# =============================================================================

def _script_to_plat3841():
    """Seam rest (252) -> the 38..41 platform (rest 168 at px 302):
    oracle-searched takeoff at 258, right held 22 frames of the arc."""
    return [(3, {"right"}), (1, {"a", "right"}), (21, {"right"}),
            (40, frozenset())]


def _script_pillar_jump():
    """38..41 platform edge (330) -> over the tall pillar -> floor at 418."""
    return [(6, {"a", "right"}), (38, {"right"})]


def test_camera_regimes_left_clamp_tracking_right_clamp(boot):
    """The world -> screen mapping at drawn content edges, at three exact
    camera states — no correlation anywhere (the floor is uniform; every
    check is a PREDICTED pixel at a level feature's boundary the re-derived
    level names):

      LEFT CLAMP (boot, cam 0): the short pillar (world x 112..119) drawn
      at screen 112..119 — its left edge exactly at 112.
      TRACKING (rest at px 252, cam 124): the tall pillar (world 352) at
      screen 228; the seam platform's left edge (world 240) at 116 — the
      camera value read off two independent drawn features.
      RIGHT CLAMP (the won frame at the goal, cam 256 — the reference's own
      test surface for this condition): the goal pillar (world 480) at
      screen 224 in GOLD, the world border (world 504) at 248, the tall
      pillar at 96, and OAM at world - 256.
    """
    m, o = boot(), Oracle()
    px0 = _pixels(m, "cam_left")
    row = 200 + PIC_Y0                  # a pillar-body world row
    assert _at(px0, 111, row) == BLACK and _at(px0, 112, row) == GREY, (
        "left clamp: the short pillar's left edge is not at screen 112")
    # drive to the seam rest (cam 124, tracking)
    run_lockstep(m, o, [*_script_to_seam_area(), (6, {"right"})], "to-252")
    settle(m, o)
    assert o.cam == 124
    px1 = _pixels(m, "cam_track")
    prow = 180 + PIC_Y0                 # tall pillar body (rows 20..25)
    assert _at(px1, 227, prow) == BLACK and _at(px1, 228, prow) == GREY, (
        "tracking at cam 124: the tall pillar's left edge is not at 228")
    assert _at(px1, 115, 160 + PIC_Y0) == BLACK \
        and _at(px1, 116, 160 + PIC_Y0) == GREY, (
        "tracking at cam 124: the seam platform's left edge is not at 116")
    # the screenshot cost one released frame each; the oracle absorbed them
    # inside run_lockstep/settle only — re-sync with one explicit step
    o.step(frozenset())                 # the cam_track shot's released frame
    # take the reference route: 38..41 platform, over the pillar, then run
    # right into the goal — the WIN is the right-clamp state (cam 256)
    run_lockstep(m, o, [*_script_to_plat3841()], "plat-route")
    assert (o.px, o.pyi, o.grounded) == (302, 168, 1), (
        f"route sanity: expected the 38..41 platform at (302, 168), oracle "
        f"({o.px}, {o.pyi})")
    run_lockstep(m, o, [(14, {"right"})], "plat-edge")
    assert o.px == 330
    run_lockstep(m, o, [*_script_pillar_jump()], "pillar-jump")
    settle(m, o)
    assert (o.px, o.pyi, o.grounded, o.state) == (418, 200, 1, 0), (
        f"route sanity: expected the floor past the pillar at 418, oracle "
        f"({o.px}, {o.pyi}, state {o.state})")
    run_lockstep(m, o, [(30, {"right"})], "run-to-goal")
    assert o.state == 1 and o.cam == CAM_MAX, (
        f"route sanity: the run into the goal must win right-clamped, "
        f"oracle state {o.state} cam {o.cam}")
    settle(m, o)
    assert tuple(m.read_bytes(O, 0, 2)) == (o.px - CAM_MAX, 200), (
        "right clamp: OAM is not at world - 256")
    px2 = _pixels(m, "cam_right")
    grow = 196 + PIC_Y0                 # goal pillar body rows (192..207)
    assert _at(px2, 223, grow) == BLACK and _at(px2, 224, grow) == GOLD, (
        "right clamp: the goal pillar's left edge is not at 224 in gold")
    assert _at(px2, 247, 100 + PIC_Y0) == BLACK \
        and _at(px2, 248, 100 + PIC_Y0) == GREY, (
        "right clamp: the world border is not at screen 248..255")
    assert _at(px2, 95, prow) == BLACK and _at(px2, 96, prow) == GREY, (
        "right clamp: the tall pillar is not at screen 96..103")


# =============================================================================
# 6. THE GOAL — the run, the win, the freeze (done-condition 4)
# =============================================================================

def _bot_run_to_goal(m):
    """The reference's own closed-loop bot (tests/test_scroll_run.py in the
    under lockstep: navigation reads WRAM/OAM, one
    frame per iteration; every ASSERTION in the tests that use this stays on
    output regions. Deterministic: the trajectory is a pure function of the
    replay triple."""
    def wx():
        return m.read_u16(W, DP_PX)

    def st():
        return m.read_u16(W, DP_STATE)

    def y_():
        return m.read_bytes(O, 0, 2)[1]

    def coast(hold_right):
        for _ in range(60):
            m.advance(1, pad1={"right": hold_right})
            if st() == 1 or (y_() in (168, 200)):
                break

    last, stall = wx(), 0
    for i in range(1200):
        if st() == 1:
            return True
        x, y = wx(), y_()
        if y == 200 and 330 <= x <= 356:
            while wx() > 252:
                m.advance(1, pad1={"left": True})
            while wx() < 258:
                m.advance(1, pad1={"right": True})
            m.advance(6, pad1={"right": True, "a": True})
            coast(hold_right=True)
            continue
        if y == 168 and x >= 324:
            m.advance(6, pad1={"right": True, "a": True})
            coast(hold_right=True)
            continue
        stall = stall + 1 if x == last else 0
        last = x
        m.advance(1, pad1={"right": True, "a": stall > 4})
    return False


def test_the_goal_ends_the_game_prints_GOAL_and_freezes(boot):
    """The whole level, spawn to goal, then the three win outputs:

    - the four BG3 tilemap cells at (14..17, 12) hold exactly G,O,A,L with
      the palette-7 attr — read from VRAM, and staged EXACTLY ONCE: the
      cells' write counters move by one for the win and by zero across 60
      more frames (the queue is not re-staged by the frozen tick);
    - the composited frame shows the white text, the gold pillar and the
      right-clamped world (the border at screen 248..255);
    - the FREEZE is 'pixels do not move': 40 frames of held left + A after
      the win leave the whole frame byte-identical (the user-visible
      invariant, not a variable).
    """
    m = boot()
    cell0 = (V_TXT_MAP + GOAL_ROW * 32 + GOAL_COL) * 2
    before_writes = m.writes(V, cell0)
    assert _goal_cells(m) == EMPTY_CELLS, "GOAL cells not empty before the win"
    assert _bot_run_to_goal(m), "the bot never reached the goal"
    m.advance(2)                        # let the staged run commit
    assert _goal_cells(m) == GOAL_WORDS, (
        f"the GOAL cells read {_goal_cells(m)}, expected G,O,A,L with the "
        f"palette-7 attr")
    assert m.writes(V, cell0) == before_writes + 1, (
        "the GOAL run was written more than once (or never)")
    px = _pixels(m, "goal")
    n_white = sum(1 for p in px if p == WHITE)
    n_gold = sum(1 for p in px if p == GOLD)
    assert n_white > 30, f"only {n_white} white px — GOAL text not rendered"
    # the pillar is 8x16 = 128 px; the runner rests against it at world 476
    # (screen 220..227), covering its 224..227 columns on the 200..207 rows:
    # 128 - 32 = 96 gold pixels, exactly.
    assert n_gold == 96, f"{n_gold} gold px — the goal pillar (128 px minus "\
        f"the runner's 32-px overlap) is not on screen as drawn"
    assert _at(px, 248, 100 + PIC_Y0) == GREY, (
        "the camera is not right-clamped at the win (border not at 248)")
    # the freeze: input changes nothing on screen
    frozen = _pixels(m, "frozen_a")
    oam = bytes(m.read_bytes(O, 0, 4))
    m.advance(40, pad1={"left": True, "a": True})
    assert bytes(m.read_bytes(O, 0, 4)) == oam, "OAM moved after the win"
    after = _pixels(m, "frozen_b")
    assert frozen == after, (
        f"{sum(a != b for a, b in zip(frozen, after))} pixels moved under "
        f"held input after the win — input is not frozen")
    assert m.writes(V, cell0) == before_writes + 1, (
        "the frozen tick re-staged the GOAL run")


def test_the_goal_top_is_a_one_way_platform_and_the_win_works_backwards(boot):
    """The one-way arms, driven on their one live tile — and the win from
    the REVERSE direction (every other case approaches the goal leftward):

    a) jump onto the GOAL PILLAR'S TOP and rest there (the goal tile's flag
       $02 is the reference's platform bit: the box bottom CROSSES the pillar top
       from above and the ow arm lands it; rest y = 184) — WITHOUT winning:
       the centre probe sits a row above the goal tiles, so the GOAL cells
       must stay empty while standing on it, held by the pixel-aligned
       ow-stand probe frame after frame;
    b) walk off its right side into the floor slot between goal and border
       (the pillar is transparent from the side on the way past — bit 1
       never blocks walking);
    c) walk back LEFT into the pillar's side: the box overlaps the non-solid
       tile, the centre enters it, and the win fires from the right.
    All oracle-locked per frame, both landings included."""
    m, o = boot(), Oracle()
    run_lockstep(m, o, [*_script_to_seam_area(), (6, {"right"}),
                        (1, frozenset()),
                        *_script_to_plat3841(), (14, {"right"}),
                        *_script_pillar_jump()], "to-418")
    settle(m, o)
    assert (o.px, o.pyi, o.state) == (418, 200, 0), (
        f"route sanity: expected the floor at 418 unwon, oracle "
        f"({o.px}, {o.pyi}, state {o.state})")
    # walk to the takeoff at 462 (centre stays left of the goal column)
    run_lockstep(m, o, [(22, {"right"})], "align-462")
    settle(m, o)
    assert o.px == 462
    # the oracle-searched hop: right held 10 frames of the arc lands the box
    # ON the pillar top at px 482 via the one-way CROSSING arm
    run_lockstep(m, o, [(1, {"a", "right"}), (9, {"right"})], "goal-jump")
    run_lockstep(m, o, [(40, frozenset())], "goal-coast")
    assert (o.px, o.pyi, o.grounded, o.state) == (482, 184, 1, 0), (
        f"route sanity: expected rest ON the goal top at (482, 184) unwon, "
        f"oracle ({o.px}, {o.pyi}, gr {o.grounded}, state {o.state})")
    assert tuple(m.read_bytes(O, 0, 2)) == (o.scrx, 184), (
        "the runner is not standing on the goal pillar's top")
    assert _goal_cells(m) == EMPTY_CELLS, (
        "standing ON the goal pillar's top won the game — the centre probe "
        "reached a goal tile it must not")
    run_lockstep(m, o, [(15, frozenset())], "goal-top-idle")
    assert tuple(m.read_bytes(O, 0, 2)) == (o.scrx, 184), (
        "the one-way stand did not hold — the pixel-aligned bit-1 probe "
        "lost the goal top")
    # walk off the right side into the slot (the border stops the box at 496)
    run_lockstep(m, o, [(9, {"right"})], "walk-off-right")
    run_lockstep(m, o, [(30, frozenset())], "slot-coast")
    settle(m, o)
    assert (o.px, o.pyi, o.state) == (496, 200, 0), (
        f"route sanity: expected the floor slot at 496 unwon, oracle "
        f"({o.px}, {o.pyi}, state {o.state})")
    assert _goal_cells(m) == EMPTY_CELLS, "falling past the side won the game"
    # the reverse win: walk LEFT into the pillar
    run_lockstep(m, o, [(10, {"left"})], "win-from-right")
    assert o.state == 1, "oracle sanity: the leftward walk-in must win"
    m.advance(2)
    assert _goal_cells(m) == GOAL_WORDS, (
        "walking into the goal pillar from the RIGHT did not print GOAL")


# =============================================================================
# 7. THE STAGING MECHANISM — the shadow, not hardware OAM
# =============================================================================

def test_the_runner_is_restaged_every_frame_not_written_once(boot):
    """The OAM SHADOW's write counter — the feature's own output region.
    Hardware OAM is the wrong surface for this claim: oam_nmi_dma commits
    the whole shadow every armed VBlank whether or not sr_obj_draw ran (the
    scroller port's falsification finding). The shadow byte distinguishes
    them: an idle run must still restage every frame, exactly as the
    source's per-frame spr_clear + spr does."""
    m = boot()
    before = m.writes(W, OAM_SHADOW)
    m.advance(30)
    after = m.writes(W, OAM_SHADOW)
    assert after - before >= 30, (
        f"the OAM shadow's first byte was written {after - before} times "
        f"over 30 frames — the runner is staged once, not per frame")
