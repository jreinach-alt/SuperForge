#!/usr/bin/env python3
"""m7_oshoot assets — the arena plane, its collision, and the cast.

Emits nine blobs into an output dir:

    mo_map.bin        32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    mo_tilemap.bin    16,384 B  the SAME tile ids, packed, for col_map
    mo_flags.bin         256 B  tile id -> solid, derived from the tilemap
    mo_pal.bin            20 B  ten BGR555 floor colours, index 0 = backdrop
                                (nine authored + reserve_backdrop's duplicate)
    mo_hero_chr.bin      576 B  18-tile OBJ grid, content at {0,1,16,17}
    mo_hero_pal.bin       32 B  16 BGR555 words (OBJ palette 0)
    mo_enemy_chr.bin     576 B
    mo_enemy_pal.bin      32 B  (OBJ palette 1)
    mo_bullet_pal.bin     32 B  (OBJ palette 2 — the bullet REUSES the enemy CHR)

EVERYTHING IS AUTHORED. Nothing is read from a pack and nothing is converted
out of a source `.bin`, which is deliberate: a converter between a source asset
and this output would trigger the asset-import rule (ground-truth
against a render it did not produce), and the cheapest way to discharge that
obligation is not to incur it. `mode7_explore` took the same route.
What the rail DOES fix is its BEHAVIOUR — the arena's shape parameters, the
spawn cell, the wall predicate's structure.

THE ONE PREDICATE. `is_wall(tx, ty)` is the single source of truth for both
what is PAINTED and what BLOCKS — "what you see is what blocks you", because
the art and the collision come out of one function. The usual way to reach
that is to emit a separate 16 KB terrain array beside the map. Here the flag
table is
DERIVED from the rendered tilemap and the derivation is asserted, so the two
cannot drift even in principle: a tile id that is solid at one cell and floor at
another is a build error naming both cells.

THE COLOUR BANDS ARE ASSERTED, not hoped for. The rail's tests identify a
bullet and a chaser by their RENDERED COLOUR, through two predicates:
"yellow" (r>150, g>150, b<90) and "red" (r>150, g<90, b<90). Those
predicates are only meaningful if no floor, wall or hero colour also satisfies
them, so `assert_colour_bands()` checks every emitted colour against both and
fails the build if one strays. A test whose predicate is proven at build time is
a different thing from a test whose predicate happens to hold today.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

WORLD_T = 128                    # world side, tiles — the full Mode 7 plane
TILE_PX = 8
MAP_BYTES = WORLD_T * WORLD_T    # 16,384: one byte per world tile
BLOB_BYTES = 2 * MAP_BYTES       # 32,768: the interleaved VRAM image

# =============================================================================
# The arena's parameters, and its spawn cell.
# =============================================================================
# An OPEN square arena rather than a maze: a run-and-gun needs room to circle,
# and the wave ring spawns chasers at +/-120 px around the player, which has to
# land on floor rather than in the void.
ARENA_LO = 4                     # the playable square is tiles [LO, HI)
ARENA_HI = 124
WALL_RING = 3                    # thickness of the wall band inside that square

# A regular LATTICE of 3x3 pillar blocks. They are what makes the rotation
# READ: an empty checkerboard turns into a moire, whereas pillars sliding
# around the pivot are unambiguous motion. They are also cover.
PILLAR_PITCH = 6                 # tiles between lattice points
PILLAR_HALF = 1                  # half-extent -> a 3x3 solid block
PILLAR_PHASE = 4                 # lattice origin, so the lattice misses centre
PILLAR_CLEAR = 8                 # tiles around spawn kept clear (an open start)

SPAWN_TX = 64                    # the arena centre. MUST match MO_SPAWN_TX in
SPAWN_TY = 64                    #   game/m7_oshoot/m7_oshoot.inc

# =============================================================================
# Colours (RGB). Nine authored; the emitted palette is TEN words, because
# reserve_backdrop evicts whatever landed at index 0 and re-appends it.
# =============================================================================
# Cool floor, warm walls, warmer-and-lighter pillars — three bands a player can
# read at a glance while the whole plane spins. Every one of them is checked
# against the two OBJ colour predicates by assert_colour_bands().
FLOOR_A = (40, 44, 60)           # checker dark  -> reserved to CGRAM index 0
FLOOR_B = (70, 78, 104)          # checker light (the motion cue)
FLOOR_M = (54, 60, 82)           # sparse diagonal seam
WALL = (176, 96, 64)             # the ring's body
WALL_LT = (216, 144, 104)        # ring face highlight (relief under rotation)
WALL_MO = (128, 72, 48)          # ring mortar
PILLAR = (144, 84, 56)           # pillar body — darker than the ring, so cover
PILLAR_LT = (192, 120, 84)       #   reads as nearer than the boundary
PILLAR_MO = (104, 60, 40)

FLOOR_COLOURS = (FLOOR_A, FLOOR_B, FLOOR_M, WALL, WALL_LT, WALL_MO,
                 PILLAR, PILLAR_LT, PILLAR_MO)


def on_pillar(tx: int, ty: int) -> bool:
    """A lattice pillar cell, outside the spawn clearing."""
    if abs(tx - SPAWN_TX) <= PILLAR_CLEAR and abs(ty - SPAWN_TY) <= PILLAR_CLEAR:
        return False
    mx = (tx - PILLAR_PHASE) % PILLAR_PITCH
    my = (ty - PILLAR_PHASE) % PILLAR_PITCH
    near_x = mx <= PILLAR_HALF or mx >= PILLAR_PITCH - PILLAR_HALF
    near_y = my <= PILLAR_HALF or my >= PILLAR_PITCH - PILLAR_HALF
    return near_x and near_y


def is_wall(tx: int, ty: int) -> bool:
    """THE predicate: solid outside the arena, in its wall ring, or on a pillar.

    This is the only thing in the build that decides solidity. `tile_color`
    calls it to paint, `flag_table` derives the collision byte from what it
    painted, and `assert_flags_equivalent` proves the derivation."""
    if tx < ARENA_LO or ty < ARENA_LO or tx >= ARENA_HI or ty >= ARENA_HI:
        return True
    if (tx < ARENA_LO + WALL_RING or ty < ARENA_LO + WALL_RING
            or tx >= ARENA_HI - WALL_RING or ty >= ARENA_HI - WALL_RING):
        return True
    return on_pillar(tx, ty)


def is_pillar_art(tx: int, ty: int) -> bool:
    """Solid AND inside the arena proper -> paint it as a pillar, not the ring.
    Purely cosmetic; `is_wall` already answered the question that matters."""
    inside = (ARENA_LO + WALL_RING <= tx < ARENA_HI - WALL_RING
              and ARENA_LO + WALL_RING <= ty < ARENA_HI - WALL_RING)
    return inside and on_pillar(tx, ty)


def tile_color(tx: int, ty: int):
    """The whole-tile colour at a world tile. Every tile is one flat colour, so
    the dedup below collapses the 16,384-tile plane to one tile per distinct
    colour — which is why the tileset is nine tiles and not nine thousand."""
    seam = ((tx + ty) & 3) == 0                    # sparse diagonal mortar
    if is_wall(tx, ty):
        if is_pillar_art(tx, ty):
            if seam:
                return PILLAR_MO
            return PILLAR_LT if not (tx & 1) or not (ty & 1) else PILLAR
        if seam:
            return WALL_MO
        return WALL_LT if not (tx & 1) or not (ty & 1) else WALL
    if seam:
        return FLOOR_M
    return FLOOR_B if ((tx >> 1) ^ (ty >> 1)) & 1 else FLOOR_A


def terrain() -> bytes:
    """The 128x128 solidity array, row-major [ty*128+tx], 1 = solid.

    NOT A SHIPPED ARTEFACT — it is the reference `flag_table` is checked
    against, with the tile-dedup converter taken out of the way."""
    out = bytearray(MAP_BYTES)
    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            out[ty * WORLD_T + tx] = 1 if is_wall(tx, ty) else 0
    return bytes(out)


# =============================================================================
# The Mode 7 converter
# =============================================================================

def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """8-bit RGB -> the hardware's 0bbbbbgggggrrrrr word. Truncating (>> 3)."""
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def convert_map() -> tuple[bytes, bytes, bytes]:
    """Tile-dedup the plane. Returns (tile_data, tilemap, palette).

    Scan order is row-major over tiles, and BOTH the palette and the tileset are
    indexed by first appearance in it. That is not a detail — it is the whole of
    why the emitted ids are what they are, and reordering changes every byte
    downstream. `tile_data` is padded to the full 256 tiles because the
    interleave wants one CHR byte per tilemap byte."""
    color_map: dict[tuple[int, int, int], int] = {}
    palette_rgb: list[tuple[int, int, int]] = []
    unique: dict[tuple[int, ...], int] = {}
    tile_pixels: list[list[int]] = []
    tilemap: list[int] = []

    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            color = tile_color(tx, ty)
            if color not in color_map:
                color_map[color] = len(palette_rgb)
                palette_rgb.append(color)
            indices = [color_map[color]] * (TILE_PX * TILE_PX)
            key = tuple(indices)
            if key not in unique:
                unique[key] = len(unique)
                tile_pixels.append(indices)
            tilemap.append(unique[key])

    if len(palette_rgb) > len(FLOOR_COLOURS):
        raise ValueError(f"{len(palette_rgb)} colours; the mo_pal claim is "
                         f"{len(FLOOR_COLOURS)}")

    tile_data = bytearray()
    for tile in tile_pixels:
        tile_data.extend(tile)
    tile_data.extend(bytes(MAP_BYTES - len(tile_data)))   # pad to 256 tiles

    palette = bytearray()
    for i in range(256):
        bgr = rgb_to_bgr555(*palette_rgb[i]) if i < len(palette_rgb) else 0
        palette += struct.pack("<H", bgr)
    return bytes(tile_data), bytes(tilemap), bytes(palette)


def palette_used(palette: bytes) -> int:
    """How many CGRAM entries are live: index 0 always, then the highest
    non-zero word."""
    return max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1


def reserve_backdrop(tile_data: bytes, palette: bytes) -> tuple[bytes, bytes]:
    """Force CGRAM index 0 to FLOOR_A.

    CGRAM word 0 is the Mode 7 BACKDROP — the colour the PPU shows wherever the
    plane does not cover the screen. World tile (0,0) is outside the arena, so
    the first colour scanned is a WALL tone; leaving it there paints the screen
    edges brick wherever the rotated plane falls short. The evicted colour is
    appended as a fresh duplicate so no pixel that referenced it changes."""
    want = rgb_to_bgr555(*FLOOR_A)
    idx0 = struct.unpack_from("<H", palette, 0)[0]
    if idx0 == want:
        return tile_data, palette
    free = palette_used(palette)
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free * 2, idx0)
    struct.pack_into("<H", pal, 0, want)
    return bytes(td), bytes(pal)


def interleave(tilemap: bytes, tile_data: bytes) -> bytes:
    """[map[0], chr[0], map[1], chr[1], ...] — the 32,768 B Mode 7 VRAM blob.

    Mode 7 VRAM is read as words whose LOW byte is the tilemap entry and whose
    HIGH byte is the CHR pixel, so interleaving at build time makes the upload
    one DMA instead of a CPU loop or a strided pair."""
    if len(tilemap) != MAP_BYTES or len(tile_data) != MAP_BYTES:
        raise ValueError(f"want {MAP_BYTES} B each, got "
                         f"{len(tilemap)} and {len(tile_data)}")
    out = bytearray(BLOB_BYTES)
    out[0::2] = tilemap
    out[1::2] = tile_data
    return bytes(out)


def build_map() -> tuple[bytes, bytes, bytes]:
    """(interleaved 32,768 B blob, packed tilemap, used-colours-only palette)."""
    tile_data, tilemap, palette = convert_map()
    tile_data, palette = reserve_backdrop(tile_data, palette)
    return interleave(tilemap, tile_data), tilemap, \
        palette[:palette_used(palette) * 2]


# =============================================================================
# The collision flag table, and the assert that makes it safe
# =============================================================================

class TileFlagConflict(ValueError):
    """A tile id is solid at one world cell and floor at another."""


def flag_table(tilemap: bytes, terr: bytes) -> bytes:
    """tile id -> 1 (solid) / 0 (floor), 256 bytes.

    THE ASSERT IS THE POINT. Collapsing 16,384 cells to 256 ids is only sound
    because solidity happens to be a function of tile id — the art dedup never
    merged a wall tile and a floor tile. Nothing guarantees that stays true: a
    re-theme that gave a seam floor tile and a seam wall tile the same flat
    colour would merge them, and then ONE flag has to answer for both, shipping
    either a wall you can walk through or a patch of floor you cannot.

    So the conflict is refused here, loudly, naming the tile and a world cell of
    each kind — rather than discovered by a player."""
    flags = bytearray(256)
    seen: dict[int, tuple[int, int, int]] = {}
    for cell, tid in enumerate(tilemap):
        solid = terr[cell]
        if tid in seen:
            was, wx, wy = seen[tid]
            if was != solid:
                raise TileFlagConflict(
                    f"tile id {tid} is solid={was} at world ({wx},{wy}) and "
                    f"solid={solid} at ({cell % WORLD_T},{cell // WORLD_T}) — "
                    f"the art dedup merged a wall tile with a floor tile")
            continue
        seen[tid] = (solid, cell % WORLD_T, cell // WORLD_T)
        flags[tid] = solid
    return bytes(flags)


def assert_flags_equivalent(flags: bytes, tilemap: bytes, terr: bytes) -> None:
    """Every world cell answers the same through the table as through the
    predicate. This is the whole "what you see is what blocks you" invariant,
    checked rather than asserted in prose."""
    for cell, tid in enumerate(tilemap):
        if flags[tid] != terr[cell]:
            raise TileFlagConflict(
                f"cell ({cell % WORLD_T},{cell // WORLD_T}) reads "
                f"{flags[tid]} through tile {tid} but the predicate says "
                f"{terr[cell]}")


# =============================================================================
# The cast — two 16x16 plan-view sprites and three OBJ palettes
# =============================================================================
# TWO sheets, THREE palettes. The bullet draws with the ENEMY CHR under its own
# bright palette, which is the reference rail's own decision
# and is what makes a bullet identifiable
# by COLOUR in the rendered frame — the thing its oracle actually asserts.

import math                                                     # noqa: E402

OBJ_GRID_TILES = 18       # 16x16 sprite = the PPU quad {0, 1, 16, 17}
OBJ_TILE_BYTES = 32       # 8x8 4bpp planar

# Hero — CYAN, the reference rail's colour, and cool-bright: it shares no band
# with the cool-DARK floor, the warm walls, the red chaser or the yellow bolt.
HERO_PAL = [
    (0, 0, 0),           # 0 transparent
    (16, 64, 72),        # 1 dark cool outline
    (64, 200, 216),      # 2 body — the cyan anchor
    (176, 248, 255),     # 3 highlight — the forward nose, top-lit
    (32, 120, 136),      # 4 interior shade
]

# Chaser — RED, and deliberately inside the oracle's red predicate
# (r > 150, g < 90, b < 90) on its body and shade, so a red pixel count is
# chaser-specific. The highlight sits just outside BOTH predicates on purpose:
# a specular that also read as "yellow" would make a chaser count as a bullet.
ENEMY_PAL = [
    (0, 0, 0),           # 0 transparent
    (56, 20, 20),        # 1 dark outline rim
    (208, 40, 40),       # 2 body — the red anchor
    (152, 28, 28),       # 3 interior shade (also red-band)
    (255, 150, 120),     # 4 glossy highlight — in NEITHER band
]

# Bolt — YELLOW, inside the oracle's yellow predicate (r > 150, g > 150,
# b < 90) on its core only. Three tones, core to rim.
BULLET_PAL = [
    (0, 0, 0),           # 0 transparent
    (255, 230, 40),      # 1 bright yellow — the bolt core
    (220, 120, 20),      # 2 orange rim — in NEITHER band
    (255, 255, 210),     # 3 white hot — b = 210, so not "yellow" by predicate
    (255, 230, 40),      # 4 the bolt again, so the shared CHR's index 4
                         #     (the chaser's highlight) stays part of the bolt
]

# Score — GREEN, a fourth band nothing else in this rail occupies, and it exists
# so the three predicates above keep meaning what they say. Digits drawn in the
# bolt's yellow would make "how many yellow pixels" stop being "how much bolt is
# on screen" and would silently weaken three shipped cases; a band of its own
# costs 16 CGRAM words at 176 and keeps every one of them exact.
#
# Index 1 is a near-black OUTLINE, and it is not decoration: the HUD sits over a
# textured Mode 7 floor that rotates under it, so a glyph with no rim would be
# legible against the dark checker and invisible against a lit wall face. The
# outline is generated (an 8-neighbour dilation of the glyph), so it cannot drift
# from the shape it surrounds.
SCORE_PAL = [
    (0, 0, 0),           # 0 transparent
    (8, 24, 8),          # 1 outline — the rim that makes a digit readable on any
                         #     floor colour underneath it
    (72, 248, 96),       # 2 body — the green anchor
    (176, 255, 184),     # 3 pale green, unused by the glyphs; present so the
                         #     palette is a full band rather than two entries
]

_N = 16                  # sprite side, px
_CX = _CY = 7.5          # centre of a 16-px span


def _is_yellow(rgb) -> bool:
    r, g, b = rgb
    return r > 150 and g > 150 and b < 90


def _is_red(rgb) -> bool:
    r, g, b = rgb
    return r > 150 and g < 90 and b < 90


def _rendered(rgb):
    """The RGB the PPU actually puts on screen: 5-bit truncation, then the
    (v << 3) | (v >> 2) expansion back to eight.

    The yellow and red predicates above run on SOURCE tuples and get away with
    it because their margins are enormous. The cyan one below does not have that
    luxury — the hero's darkest qualifying colour and the floor's brightest
    non-qualifying one are 33 apart before truncation — so it is checked against
    what renders rather than what was authored. MEASURED, not assumed: source
    (64,200,216) renders as (66,206,222) in a captured frame, which is exactly
    this function."""
    return tuple(((c >> 3) << 3) | ((c >> 3) >> 2) for c in rgb)


def _is_cyan(rgb) -> bool:
    """The HERO band, and the predicate the blink cue is counted with.

    The hit cue is the hero's own sprite flickering, so a test has to be able to
    say "the hero is on screen this frame" from pixels alone. Ordering rather
    than thresholds on all three channels: the hero is the only cool-bright
    thing in the palette, and b >= g > r separates him from a floor that is
    either cool-DARK (the checker) or warm (the ring and pillars) without
    depending on a hand-placed cut between two nearby numbers."""
    r, g, b = _rendered(rgb)
    return b >= g > r and b >= 120


def _is_green(rgb) -> bool:
    """The SCORE band — the predicate the HUD is counted with.

    Same contract as the three above and proved the same way below: "how many
    green pixels does this frame have" IS "how much score readout is on screen",
    with no coordinate arithmetic. Checked on the RENDERED value for the same
    reason the cyan one is — the digits are small, so a handful of pixels decides
    a case and a 5-bit truncation must not move any of them across the line."""
    r, g, b = _rendered(rgb)
    return g > 150 and r < 130 and b < 130


def assert_colour_bands() -> None:
    """The rendered-colour predicates the tests use must be UNAMBIGUOUS.

    "at least N yellow pixels rendered" only proves a bullet drew if nothing
    else on screen is yellow. So: no floor colour and no hero colour may satisfy
    either predicate; no chaser colour may satisfy "yellow"; and no bolt colour
    may satisfy "red". Checked here so the test's predicate is a build-time
    fact rather than an inspection that was true once."""
    for rgb in FLOOR_COLOURS:
        assert not _is_yellow(rgb) and not _is_red(rgb), f"floor {rgb}"
    for rgb in HERO_PAL:
        assert not _is_yellow(rgb) and not _is_red(rgb), f"hero {rgb}"
    for rgb in ENEMY_PAL:
        assert not _is_yellow(rgb), f"chaser {rgb} reads as a bolt"
    for rgb in BULLET_PAL:
        assert not _is_red(rgb), f"bolt {rgb} reads as a chaser"
    assert any(_is_red(c) for c in ENEMY_PAL), "no chaser colour is red-band"
    assert any(_is_yellow(c) for c in BULLET_PAL), "no bolt colour is yellow-band"
    # THE HERO BAND, which the hit-cue test counts the blink with. Same contract
    # as the two above: "the hero is drawn this frame" is only readable from a
    # pixel count if nothing else on screen can produce one.
    for rgb in FLOOR_COLOURS:
        assert not _is_cyan(rgb), f"floor {rgb} reads as the hero"
    for rgb in ENEMY_PAL:
        assert not _is_cyan(rgb), f"chaser {rgb} reads as the hero"
    for rgb in BULLET_PAL:
        assert not _is_cyan(rgb), f"bolt {rgb} reads as the hero"
    assert sum(_is_cyan(c) for c in HERO_PAL) >= 2, (
        "fewer than two hero colours are cyan-band — the blink cue would be "
        "counted off a single palette entry, and a one-pixel run would decide it")
    # THE SCORE BAND. Fourth and last: the HUD digits and the death flash both
    # draw in it, so a green pixel count has to be theirs alone — and, in the
    # other direction, no score colour may fall into any of the three bands
    # already in service, or the HUD would be counted as a bolt or as the hero.
    for rgb in FLOOR_COLOURS:
        assert not _is_green(rgb), f"floor {rgb} reads as the score"
    for name, pal in (("hero", HERO_PAL), ("chaser", ENEMY_PAL),
                      ("bolt", BULLET_PAL)):
        for rgb in pal:
            assert not _is_green(rgb), f"{name} {rgb} reads as the score"
    for rgb in SCORE_PAL:
        assert not _is_yellow(rgb), f"score {rgb} reads as a bolt"
        assert not _is_red(rgb), f"score {rgb} reads as a chaser"
        assert not _is_cyan(rgb), f"score {rgb} reads as the hero"
    assert any(_is_green(c) for c in SCORE_PAL), "no score colour is green-band"


def assert_floor_and_obj_palettes_are_disjoint() -> None:
    """No BGR555 word may appear in BOTH the floor palette and an OBJ one.

    This is not tidiness — it is what lets a test SEPARATE THE FLOOR FROM THE
    CAST in a rendered frame with no coordinate arithmetic at all: a pixel
    belongs to the floor iff its colour is one of the floor's, full stop. The
    rail's "the floor holds still" and "the floor stops when you hit a wall"
    cases are floor-only claims, and the chasers move every frame whatever the
    floor does, so without a mask those cases would be answering "did any pixel
    change". The alternative mask — OAM boxes projected into the framebuffer —
    needs a screen-origin offset that is Mesen's overscan convention rather than
    anything this repo declares, and a wrong one silently under-masks.

    Truncation to 5 bits per channel is done FIRST, because two RGB triples that
    differ only in the low three bits are the same colour on this hardware and
    would collide on screen while looking distinct in the source."""
    floor = {rgb_to_bgr555(*c) for c in FLOOR_COLOURS}
    for name, pal in (("hero", HERO_PAL), ("chaser", ENEMY_PAL),
                      ("bolt", BULLET_PAL), ("score", SCORE_PAL)):
        for rgb in pal[1:]:                 # index 0 is transparent, never drawn
            w = rgb_to_bgr555(*rgb)
            assert w not in floor, (
                f"{name} colour {rgb} is also a floor colour on the hardware "
                f"(BGR555 ${w:04X}) — the floor/cast separation the tests rely "
                f"on would silently under-mask")


def hero_grid() -> list[list[int]]:
    """Plan-view gunner: a concentric body with ONE forward nose.

    The nose is the only break in the radial symmetry and it is deliberate: the
    floor rotates so the facing reads "up", and a hero with a visible front is
    what makes that legible. Nothing bright goes low and symmetric — two pips
    read as EYES, and eyes imply a tilted camera on a plan view."""
    g = [[0] * _N for _ in range(_N)]
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= 2.6:
                g[y][x] = 3
            elif d <= 4.3:
                g[y][x] = 2
            elif d <= 5.4:
                g[y][x] = 4
            elif d <= 6.4:
                g[y][x] = 2
            elif d <= 7.0:
                g[y][x] = 1
    # The NOSE, tapering to a tip at row 0 — the forward cue.
    for ry, (x0, x1) in {0: (7, 8), 1: (6, 9), 2: (6, 9)}.items():
        for x in range(x0, x1 + 1):
            g[ry][x] = 3
    g[2][5] = 1
    g[2][10] = 1
    # The two side pods, at the widest point — they read as the guns.
    for px0, px1 in ((1, 2), (13, 14)):
        for x in range(px0, px1 + 1):
            for y in (7, 8):
                g[y][x] = 3
    return g


def enemy_grid() -> list[list[int]]:
    """Plan-view chaser: a concentric blob with one glossy cap.

    ALSO THE BULLET. Under BULLET_PAL the same shape is a bolt, which is why
    it is a compact disc rather than a silhouette with limbs: it has to read at
    two sizes of meaning, not two sizes of pixel."""
    g = [[0] * _N for _ in range(_N)]
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= 5.5:
                g[y][x] = 2
            elif d <= 6.1:
                g[y][x] = 3
            elif d <= 6.9:
                g[y][x] = 1
    # The specular cap. ONE connected shape — two dots would read as a face.
    for ry, x0, x1 in ((3, 7, 8), (4, 6, 9), (5, 7, 8)):
        for x in range(x0, x1 + 1):
            if g[ry][x] == 2:
                g[ry][x] = 4
    return g


# A 5x5 digit set. Five by five rather than a taller face because the glyph has
# to carry a generated 1 px outline on every side and still fit an 8x8 tile: the
# body occupies x=1..5, y=1..5 and the dilation reaches x=0..6, y=0..6, one row
# and column clear of the tile edge. All ten are pairwise distinct at this size —
# the pairs that usually collide (3/8, 6/8, 0/8) differ in at least four cells.
_DIGIT_ROWS = {
    0: ("01110", "10001", "10001", "10001", "01110"),
    1: ("00100", "01100", "00100", "00100", "01110"),
    2: ("11110", "00001", "01110", "10000", "11111"),
    3: ("11110", "00001", "01110", "00001", "11110"),
    4: ("10010", "10010", "11111", "00010", "00010"),
    5: ("11111", "10000", "11110", "00001", "11110"),
    6: ("01110", "10000", "11110", "10001", "01110"),
    7: ("11111", "00010", "00100", "01000", "01000"),
    8: ("01110", "10001", "01110", "10001", "01110"),
    9: ("01110", "10001", "01111", "00001", "01110"),
}

DIGIT_TILE0 = 2          # digit d lands at sheet tile DIGIT_TILE0 + d. MUST match
                         #   MO_DIGIT_TILE in game/m7_oshoot/m7_oshoot.inc


def digit_grid(d: int) -> list[list[int]]:
    """One 8x8 HUD digit: body in SCORE_PAL index 2, generated rim in index 1.

    THE RIM IS DILATED, NOT DRAWN. Every cell within one step (including
    diagonals) of a body cell that is not itself body becomes outline, so the rim
    cannot drift from the shape it surrounds when a glyph is edited. It is what
    makes a digit readable over BOTH the dark checker and a lit wall face, on a
    floor that rotates underneath the HUD every frame."""
    g = [[0] * 8 for _ in range(8)]
    rows = _DIGIT_ROWS[d]
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            if ch == "1":
                g[ry + 1][rx + 1] = 2
    for y in range(8):
        for x in range(8):
            if g[y][x] != 0:
                continue
            near = any(0 <= y + dy < 8 and 0 <= x + dx < 8
                       and g[y + dy][x + dx] == 2
                       for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            if near:
                g[y][x] = 1
    return g


def encode_tile_4bpp(grid, ox: int, oy: int) -> bytes:
    """The 8x8 sub-grid at (ox,oy) -> 32 B SNES 4bpp planar.

    Planes 0,1 interleave by row in the first 16 bytes; planes 2,3 in the
    second 16. Bit 7 of each byte is the LEFTMOST pixel."""
    out = bytearray(OBJ_TILE_BYTES)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = grid[oy + y][ox + x]
            assert 0 <= v <= 15, v
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def obj_chr(grid, with_digits: bool = False) -> bytes:
    """A 16x16 sprite on the OBJ grid: 18 tiles, content at 0/1/16/17.

    The PPU reads a 16x16 sprite as {N, N+1, N+16, N+17} — the lower row is
    +16 tile numbers away, NOT +2, because OBJ CHR is a 16-tile-wide sheet.
    That is hardware, so the 14 tiles between the two rows are padding by
    necessity: laid out any other way, the bottom half of the sprite is
    whatever tiles happen to sit at +2.

    `with_digits` SPENDS TEN OF THOSE PADDING TILES on the HUD's digit set
    (2..11), which is why the score readout needs no CHR claim, no second blob
    and no second upload: the bytes ride the sheet that is already going to OBJ
    VRAM at scene enter, and the blob's size does not change. The digits are 8x8
    and the actors are 16x16 in the same sheet because OBSEL size pair 0 is
    (8x8 / 16x16) and mo_put sets the per-slot LARGE bit for actors only — a
    digit's OAM entry simply leaves it clear."""
    tiles = [bytes(OBJ_TILE_BYTES)] * OBJ_GRID_TILES
    tiles[0] = encode_tile_4bpp(grid, 0, 0)      # TL
    tiles[1] = encode_tile_4bpp(grid, 8, 0)      # TR
    tiles[16] = encode_tile_4bpp(grid, 0, 8)     # BL
    tiles[17] = encode_tile_4bpp(grid, 8, 8)     # BR
    if with_digits:
        for d in range(10):
            slot = DIGIT_TILE0 + d
            assert slot not in (0, 1, 16, 17), (
                f"digit {d} would land on tile {slot}, which the 16x16 sprite "
                f"quad {{0,1,16,17}} owns")
            assert tiles[slot] == bytes(OBJ_TILE_BYTES), (
                f"digit {d} would overwrite non-pad tile {slot}")
            tiles[slot] = encode_tile_4bpp(digit_grid(d), 0, 0)
    return b"".join(tiles)


def obj_pal(colors) -> bytes:
    """16 BGR555 words, zero-padded. A 4bpp OBJ palette is 16 entries whether
    or not the art uses them, and CGRAM is written as a block."""
    pal = bytearray()
    for rgb in colors:
        pal += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(pal) + bytes(2 * (16 - len(colors)))


# =============================================================================

def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    assert_colour_bands()
    assert_floor_and_obj_palettes_are_disjoint()

    terr = terrain()
    blob, tilemap, palette = build_map()
    flags = flag_table(tilemap, terr)
    assert_flags_equivalent(flags, tilemap, terr)

    if is_wall(SPAWN_TX, SPAWN_TY):
        raise ValueError(f"spawn tile ({SPAWN_TX},{SPAWN_TY}) is solid")

    files = {
        "mo_map.bin": blob,
        "mo_tilemap.bin": tilemap,
        "mo_flags.bin": flags,
        "mo_pal.bin": palette,
        "mo_hero_chr.bin": obj_chr(hero_grid(), with_digits=True),
        "mo_hero_pal.bin": obj_pal(HERO_PAL),
        "mo_enemy_chr.bin": obj_chr(enemy_grid()),
        "mo_enemy_pal.bin": obj_pal(ENEMY_PAL),
        "mo_bullet_pal.bin": obj_pal(BULLET_PAL),
        "mo_score_pal.bin": obj_pal(SCORE_PAL),
    }
    # EVERY SIZE IS THE `mo_rom` CLAIM IT FILLS. A rom claim reserves a fixed
    # window and `make rom-unbacked` proves an .incbin backs it — but nothing
    # downstream notices a blob that came out SHORTER than its claim, and a
    # tenth floor colour or a re-themed palette would do exactly that silently.
    # So the sizes are pinned here, beside the code that decides them.
    expect = {
        "mo_map.bin": 32768, "mo_tilemap.bin": 16384, "mo_flags.bin": 256,
        "mo_pal.bin": 20, "mo_hero_chr.bin": 576, "mo_hero_pal.bin": 32,
        "mo_enemy_chr.bin": 576, "mo_enemy_pal.bin": 32,
        "mo_bullet_pal.bin": 32, "mo_score_pal.bin": 32,
    }
    for name, data in files.items():
        if len(data) != expect[name]:
            raise ValueError(f"{name}: {len(data)} B, but the mo_rom claim is "
                             f"{expect[name]} B — move the claim or the art")
        (out / name).write_bytes(data)

    solid = sum(terr)
    print(f"m7_oshoot assets -> {out}")
    print(f"  plane {len(blob)} B, tilemap {len(tilemap)} B, "
          f"{len(palette) // 2} colours, {max(tilemap) + 1} tiles")
    print(f"  arena [{ARENA_LO},{ARENA_HI}) ring {WALL_RING}; "
          f"{solid}/{MAP_BYTES} cells solid "
          f"({100 * solid / MAP_BYTES:.1f}%); spawn ({SPAWN_TX},{SPAWN_TY}) "
          f"px ({SPAWN_TX * 8 + 4},{SPAWN_TY * 8 + 4}) floor")


if __name__ == "__main__":
    main()
