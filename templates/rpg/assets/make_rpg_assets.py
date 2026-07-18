#!/usr/bin/env python3
"""make_rpg_assets.py — first-party art for the rpg template (Sprints 0-1).

Authors TWO visually-distinct worlds, both ORIGINAL (clean-room):

  1. OVERWORLD (Mode 7): a 1024x1024 designed overhead world on the 128x128
     tile grid — a green meadow cross-hatched by tan paths, with WATER lakes
     and MOUNTAIN ranges (both BLOCKED terrain) and one TOWN-ENTRANCE landmark
     tile (the trigger Sprint 3 will use for the town transition). Converted
     through the kit's Mode 7 pipeline to the native interleaved VRAM blob
     (even bytes = tilemap, odd bytes = 8bpp tile pixels). Loaded by
     `sf_mode7_load_map ovw_map, #$8000`.

     Sprint 1 also emits a PARALLEL COLLISION TABLE (`ovw_collision.inc`): a
     128x128 = 16384-byte terrain-type array, one byte per tile, keyed
     IDENTICALLY to the authoring function so collision is determined by
     terrain SEMANTICS (the same code that picks the pixel color), NOT by
     reading VRAM back at runtime. The movement code indexes it by
     (ty*128 + tx) and rejects steps onto blocked tiles.

  2. TOWN / BATTLE (Mode 1): a small hand-authored 4bpp tileset (cobble floor,
     brick wall, water, a torch accent) + a 16-color BG palette + an avatar
     OBJ tile + an OBJ palette. Deliberately a FLAT brick-and-cobble look so a
     screenshot reads instantly different from the Mode 7 grass floor.

     Sprint 3: these tiles build a DESIGNED, DENSE town (a fully-cobbled plaza
     framed by brick walls, two buildings, a central fountain, torches, a
     villager NPC, and a gated south EXIT). The town LAYOUT is authored in
     `build_town_map` (templates/rpg/main.asm) — it mset's every cell from this
     tileset; collision reads the resulting shadow BG1 tilemap (the SSoT). Only
     the TILESET + palettes live here; the room shape is in the ASM template.

Both are flat-color per 8x8 tile so the Mode 7 converter dedups hard (well
under 256 tiles / 256 colors). ZERO commercial names anywhere.

Outputs (committed; regenerate only when changing the art):
    ovw.png            authored Mode 7 source image (1024x1024)
    ovw_map.bin        32,768-byte interleaved Mode 7 VRAM blob
    ovw_palette.inc    ca65 CGRAM data: ovw_pal + OVW_PAL_COUNT
    ovw_collision.inc  ca65 128x128 terrain table + TERR_* / spawn constants
    town_assets.inc    ca65 4bpp Mode 1 CHR + BG palette + avatar + OBJ palette

Regenerate (from a kit root that has toolchain/, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py
Deterministic output: same script, same bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# =============================================================================
# OVERWORLD (Mode 7) — designed world: meadow + paths + water + mountains + town
# =============================================================================
# CGRAM index 0 is the Mode 7 backdrop — and under a PERSPECTIVE floor it is the
# colour the per-scanline sky-split (sf_mode7_sky_split) reveals ABOVE the
# horizon, where BG1 is turned off. So index 0 MUST be a SKY colour, not the
# floor green: a perspective Mode 7 floor without a sky-split smears the ground
# tilemap upward past the horizon (the rejected "floor-in-sky" defect). The
# grass that the converter would have placed at index 0 is relocated to a free
# opaque slot by reserve_sky_backdrop (so the meadow keeps its green on the
# floor below the horizon). Mirrors the racer's make_track.py sky reservation.
SKY_HORIZON_LT = (96, 156, 224)  # sky near the horizon (lighter) -> CGRAM 0 base
SKY_ZENITH_DK = (24, 56, 152)    # sky at the top (deeper blue) -> gradient target
GRASS_DK = (30, 92, 40)         # meadow base (floor tile colour, relocated)
GRASS_LT = (52, 130, 58)        # meadow highlight (checker)
PATH_TAN = (176, 150, 96)       # dirt path
PATH_DK = (132, 110, 66)        # path shadow edge
WATER_DK = (24, 58, 140)        # lake deep   (BLOCKED)
WATER_LT = (44, 92, 184)        # lake shallow / ripple (BLOCKED)
MTN_DK = (96, 84, 78)           # mountain rock (BLOCKED)
MTN_LT = (150, 138, 128)        # mountain lit  (BLOCKED)
TOWN_RF = (208, 72, 56)         # town-entrance roof (LANDMARK, walkable trigger)
TOWN_WL = (224, 196, 150)       # town-entrance wall
NPC_BODY = (212, 96, 196)       # NPC signpost / villager tile (a bright magenta
                                #   so it reads instantly apart from the meadow
                                #   green / tan path / blue water — the player
                                #   walks UP TO it and presses A to interact)

# --- terrain type ids (parallel collision table) ---
TERR_GRASS = 0                  # walkable
TERR_PATH = 1                   # walkable
TERR_WATER = 2                  # BLOCKED
TERR_MOUNTAIN = 3               # BLOCKED
TERR_TOWN = 4                   # walkable LANDMARK (town-entrance trigger)
TERR_NPC = 5                    # BLOCKED (adjacent-blocking) INTERACTABLE NPC.
                                #   Solid like a wall so the player stops on the
                                #   adjacent tile; the proximity check looks for
                                #   an NPC in a cardinal neighbour and the A
                                #   button while adjacent triggers the prompt.
BLOCKED_TERRAINS = {TERR_WATER, TERR_MOUNTAIN, TERR_NPC}

# Player spawns on a path intersection near the map center, clear of obstacles.
SPAWN_TX = 64
SPAWN_TY = 64

# Town-entrance landmark: a 2x2 block of roof/wall tiles. Placed a few tiles
# off the spawn along the central path so the player can walk onto it; the
# block itself is walkable (TERR_TOWN) — it is the Sprint 3 transition trigger.
TOWN_TX = 76                    # town landmark top-left tile X
TOWN_TY = 64                    # town landmark top-left tile Y

# --- overworld NPCs (Sprint 2) — FIXED tile-trigger interaction points, NOT
#     free-roaming projected sprites (that needs the fragile Mode 7 inverse
#     transform Phase 13 disabled). Each NPC is one BLOCKED tile baked into the
#     Mode 7 map; the player walks up to it and the adjacency check + A button
#     fire the sprite-text prompt.
#
#     Placement is DIAGONAL to the spawn (64,64) — deliberately OFF row 64 and
#     OFF column 64 — so the Sprint 1 cardinal-walk tests (which walk straight
#     lines right/left along row 64 and up/down along column 64) are unaffected
#     by the new blocking tiles, while a single cardinal step from the spawn
#     still lands the player ADJACENT to an NPC:
#       NPC0 (65,65): SE-diagonal of spawn — adjacent after one step RIGHT (then
#                     its SOUTH neighbour) or one step DOWN (then its EAST one).
#       NPC1 (66,66): one tile further SE — a second approach for the test.
NPCS = [(65, 65), (66, 66)]     # (tx, ty) world tiles of the NPC signposts

# Disc-shaped lakes + ridge-line mountain ranges placed AWAY from the spawn and
# the spawn's outbound paths so the player is never boxed in. (cx, cy, r).
LAKES = [(40, 44, 7), (92, 90, 8), (30, 96, 6)]
# Mountain ridges as thick line segments (x0,y0,x1,y1,half-width).
RIDGES = [(96, 30, 110, 50, 3), (20, 20, 40, 26, 2), (84, 108, 104, 116, 3)]

# Starter obstacles: short BLOCKED barriers placed a few tiles cardinally from
# the spawn (64,64) in three directions, so a "walk into a wall" test reaches a
# boundary quickly from multiple approaches. They are explicit tile sets (not
# discs) so they can hug the spawn without boxing it in. The EAST direction is
# left fully clear — that's the town-entrance approach (spawn -> town at 76,64).
#   - SOUTH barrier: a pond 5 tiles below spawn (rows 69..71, x 58..70)
#   - NORTH barrier: a rock ridge 5 tiles above spawn (rows 58..59, x 58..70)
#   - WEST barrier:  a rock wall 6 tiles left of spawn (col 57..58, y 60..68)
# Wider/deeper than one tile so each barrier fills a readable band of the
# screen for the rendered-output census tests (a 1-tile strip is < 40 px).
STARTER_WATER = {(x, y) for x in range(58, 71) for y in range(69, 72)}
STARTER_ROCK = ({(x, y) for x in range(58, 71) for y in range(58, 60)} |
                {(x, y) for x in range(57, 59) for y in range(60, 69)})


def _on_disc(tx, ty, cx, cy, r):
    dx, dy = tx - cx, ty - cy
    return dx * dx + dy * dy <= r * r


def _near_segment(tx, ty, x0, y0, x1, y1, hw):
    # distance from point to segment; blocked if within hw tiles.
    vx, vy = x1 - x0, y1 - y0
    wx, wy = tx - x0, ty - y0
    seg2 = vx * vx + vy * vy
    if seg2 == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg2))
    px, py = x0 + t * vx, y0 + t * vy
    dx, dy = tx - px, ty - py
    return (dx * dx + dy * dy) <= (hw + 0.5) ** 2


def ovw_terrain(tx: int, ty: int) -> int:
    """Terrain type id for overworld tile (tx, ty). SINGLE SOURCE OF TRUTH for
    both the rendered color (ovw_color) and the collision table — so what the
    player SEES blocked is what the movement code rejects."""
    # overworld NPCs — one BLOCKED interactable tile each (checked first so a
    # signpost is never overwritten by the path/grass it sits on)
    if (tx, ty) in NPCS:
        return TERR_NPC
    # town-entrance landmark (2x2 block) — walkable trigger
    if TOWN_TX <= tx < TOWN_TX + 2 and TOWN_TY <= ty < TOWN_TY + 2:
        return TERR_TOWN
    # starter obstacles near the spawn (cardinally reachable for the wall test)
    if (tx, ty) in STARTER_WATER:
        return TERR_WATER
    if (tx, ty) in STARTER_ROCK:
        return TERR_MOUNTAIN
    # mountains (ridge lines) — blocked
    for seg in RIDGES:
        if _near_segment(tx, ty, *seg):
            return TERR_MOUNTAIN
    # water (lakes) — blocked
    for (cx, cy, r) in LAKES:
        if _on_disc(tx, ty, cx, cy, r):
            return TERR_WATER
    # tan path grid: vertical paths every 24 tiles, horizontal every 20 tiles
    on_vpath = (tx % 24) in (11, 12)
    on_hpath = (ty % 20) in (9, 10)
    if on_vpath or on_hpath:
        return TERR_PATH
    return TERR_GRASS


def ovw_color(tx: int, ty: int):
    """Flat color for overworld tile (tx, ty) — derived from the terrain id so
    visuals and collision can never drift."""
    terr = ovw_terrain(tx, ty)
    if terr == TERR_NPC:
        return NPC_BODY             # bright magenta signpost (reads apart from terrain)
    if terr == TERR_TOWN:
        # roof on the top row of the 2x2, wall on the bottom
        return TOWN_RF if (ty - TOWN_TY) == 0 else TOWN_WL
    if terr == TERR_MOUNTAIN:
        return MTN_LT if (tx ^ ty) & 1 else MTN_DK
    if terr == TERR_WATER:
        return WATER_LT if (tx ^ ty) & 1 else WATER_DK
    if terr == TERR_PATH:
        edge = (tx % 24) in (11,) or (ty % 20) in (9,)
        return PATH_TAN if edge else PATH_DK
    # meadow checker for a Mode 7 motion cue
    return GRASS_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else GRASS_DK


def build_ovw_png(path: Path) -> None:
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    for ty in range(128):
        for tx in range(128):
            c = ovw_color(tx, ty)
            for py in range(8):
                for pxi in range(8):
                    px[tx * 8 + pxi, ty * 8 + py] = c
    img.save(path)
    print(f"wrote {path}")


def reserve_sky_backdrop(tile_data: bytes, palette: bytes):
    """Force CGRAM index 0 = SKY (the Mode 7 backdrop slot the sky-split reveals
    above the horizon). Relocate whatever the converter put at index 0 (the
    meadow grass) to a free opaque slot so the floor keeps its green, and write
    the sky colour into index 0. Mirrors the racer's make_track.py sky
    reservation (which reserves index 0 as sky blue for arm_sky_split)."""
    import struct
    from toolchain.mode7_assets import rgb_to_bgr555

    sky_word = rgb_to_bgr555(*SKY_HORIZON_LT)
    idx0_word = struct.unpack_from("<H", palette, 0)[0]
    if idx0_word == sky_word:
        return tile_data, palette
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    free_slot = used
    if free_slot >= 256:
        raise ValueError("no free CGRAM slot to relocate the index-0 color")
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free_slot
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free_slot * 2, idx0_word)
    struct.pack_into("<H", pal, 0, sky_word)
    return bytes(td), bytes(pal)


def emit_ovw():
    from toolchain.mode7_map_converter import convert_map_png
    from toolchain.mode7_assets import interleave_mode7_data

    png = HERE / "ovw.png"
    build_ovw_png(png)
    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_sky_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "ovw_map.bin").write_bytes(blob)
    print(f"wrote {HERE / 'ovw_map.bin'} ({len(blob)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; =============================================================================",
        "; ovw_palette.inc — overworld (Mode 7) CGRAM data (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py",
        "; (companion blob: ovw_map.bin, the interleaved Mode 7 VRAM image)",
        "; CGRAM index 0 = SKY backdrop (revealed above the horizon by the",
        "; per-scanline sky-split where BG1 is off; floor grass is relocated).",
        "; =============================================================================",
        "",
        "ovw_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines += ["", f"OVW_PAL_COUNT = {used}", ""]
    (HERE / "ovw_palette.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'ovw_palette.inc'} ({used} colors)")


def emit_collision():
    """Emit the parallel 128x128 collision/terrain table, keyed identically to
    ovw_terrain. One byte per tile, row-major (index = ty*128 + tx). The
    movement code indexes it by the destination tile and rejects steps onto a
    blocked terrain id. Emitted as a flat .byte blob (16384 bytes) plus the
    terrain-id + spawn + town-trigger equates the ASM movement code needs."""
    table = bytearray(128 * 128)
    counts = {}
    for ty in range(128):
        for tx in range(128):
            terr = ovw_terrain(tx, ty)
            table[ty * 128 + tx] = terr
            counts[terr] = counts.get(terr, 0) + 1
    # sanity: the spawn tile and its 4 cardinal neighbours must be walkable so
    # the player is never spawned boxed-in (the test relies on it).
    for (dx, dy) in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
        assert ovw_terrain(SPAWN_TX + dx, SPAWN_TY + dy) not in BLOCKED_TERRAINS, \
            f"spawn neighbour ({SPAWN_TX+dx},{SPAWN_TY+dy}) is blocked"

    lines = [
        "; =============================================================================",
        "; ovw_collision.inc — overworld terrain/collision table (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py",
        "; 128x128 = 16384 bytes, one terrain-id byte per tile, row-major:",
        ";   ovw_collision[ty*128 + tx] = terrain id.",
        "; The overworld movement code indexes this by the DESTINATION tile and",
        "; rejects a step when the id is a BLOCKED terrain (water/mountain). This",
        "; is a PARALLEL table — collision never reads VRAM back per frame.",
        ";",
        f"; terrain census: {dict(sorted(counts.items()))}",
        "; =============================================================================",
        "",
        "; --- terrain id constants (must match make_rpg_assets.py) ---",
        f"TERR_GRASS    = {TERR_GRASS}",
        f"TERR_PATH     = {TERR_PATH}",
        f"TERR_WATER    = {TERR_WATER}    ; BLOCKED",
        f"TERR_MOUNTAIN = {TERR_MOUNTAIN}    ; BLOCKED",
        f"TERR_TOWN     = {TERR_TOWN}    ; walkable LANDMARK (town-entrance trigger)",
        f"TERR_NPC      = {TERR_NPC}    ; BLOCKED + INTERACTABLE (NPC signpost)",
        "; ids in [TERR_BLOCKED_MIN, TERR_BLOCKED_MAX] are impassable as a CONTIGUOUS",
        "; range (water/mountain). TERR_NPC is ALSO impassable but lives OUTSIDE that",
        "; range (above TERR_TOWN, which must stay walkable) — the movement code",
        "; rejects it with a SEPARATE equality check so the range never swallows TOWN.",
        f"TERR_BLOCKED_MIN = {TERR_WATER}",
        f"TERR_BLOCKED_MAX = {TERR_MOUNTAIN}",
        "",
        "; --- spawn tile + town-entrance trigger tile (top-left of the 2x2) ---",
        f"OVW_SPAWN_TX = {SPAWN_TX}",
        f"OVW_SPAWN_TY = {SPAWN_TY}",
        f"OVW_TOWN_TX  = {TOWN_TX}",
        f"OVW_TOWN_TY  = {TOWN_TY}",
        "",
        "; --- overworld NPC tiles (Sprint 2 tile-triggers). Each is one BLOCKED",
        ";     interactable tile; the player stands adjacent and presses A. The",
        ";     proximity check scans the 4 cardinal neighbours for TERR_NPC. ---",
        f"OVW_NPC_COUNT = {len(NPCS)}",
    ] + [
        f"OVW_NPC{i}_TX = {tx}\nOVW_NPC{i}_TY = {ty}"
        for i, (tx, ty) in enumerate(NPCS)
    ] + [
        "",
        "; --- the 16384-byte terrain table ---",
        "ovw_collision:",
    ]
    for ty in range(128):
        row = table[ty * 128:(ty + 1) * 128]
        # 16 bytes per source line for readability
        for off in range(0, 128, 16):
            chunk = ", ".join(str(b) for b in row[off:off + 16])
            lines.append(f"    .byte {chunk}")
    lines += ["", "OVW_COLLISION_BYTES = 16384", ""]
    (HERE / "ovw_collision.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'ovw_collision.inc'} (census {dict(sorted(counts.items()))})")


# =============================================================================
# TOWN / BATTLE (Mode 1) — hand-authored 4bpp tileset + palettes + avatar
# =============================================================================
# Mode 1 BG palette 0 (16 colors). Index 0 is transparent (backdrop shows
# through). The town uses indices 1..7; battle reuses the same CHR but the
# main.asm picks a different backdrop color (mset a distinct tile) so the two
# Mode-1 scenes read apart.
TOWN_BG_PAL = [
    (0, 0, 0),            # 0 transparent
    (96, 96, 112),       # 1 cobble mid
    (64, 64, 80),        # 2 cobble shadow
    (140, 140, 156),     # 3 cobble light
    (150, 70, 50),       # 4 brick
    (96, 44, 32),        # 5 brick shadow
    (40, 90, 170),       # 6 water
    (255, 200, 80),      # 7 torch / accent
    (24, 40, 28),        # 8 dark-green battle backdrop fill
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

# OBJ palette 0 (16 colors) for the avatar — a small hero figure. Indices 5/6
# are the Sprint-2 sprite-text colours: a bright yellow indicator + a cream-white
# glyph fill, both far brighter than the meadow floor so a screenshot pixel test
# inside a prompt sprite is unambiguous against the green background.
OBJ_PAL = [
    (0, 0, 0),           # 0 transparent
    (240, 220, 180),     # 1 skin
    (40, 60, 200),       # 2 tunic blue
    (180, 40, 40),       # 3 cape red
    (30, 30, 40),        # 4 outline / boots
    (252, 232, 96),      # 5 prompt indicator (bright yellow "!")
    (248, 248, 232),     # 6 sprite-text glyph fill (cream white)
    (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

# 8x8 tiles as palette-index grids (rows of 8). Tile 0 must stay all-zero
# (transparent) for the engine's empty cell. Tiles 1..4 are the Mode 1 tileset;
# tile 5 is the avatar sprite (OBJ).
COBBLE = [
    [1, 1, 3, 1, 1, 1, 2, 1],
    [1, 2, 1, 1, 3, 1, 1, 1],
    [3, 1, 1, 2, 1, 1, 1, 3],
    [1, 1, 1, 1, 1, 1, 2, 1],
    [1, 3, 1, 1, 1, 3, 1, 1],
    [2, 1, 1, 3, 1, 1, 1, 1],
    [1, 1, 2, 1, 1, 1, 3, 1],
    [1, 1, 1, 1, 2, 1, 1, 1],
]
BRICK = [
    [4, 4, 4, 5, 4, 4, 4, 5],
    [4, 4, 4, 5, 4, 4, 4, 5],
    [5, 5, 5, 5, 5, 5, 5, 5],
    [4, 5, 4, 4, 4, 5, 4, 4],
    [4, 5, 4, 4, 4, 5, 4, 4],
    [5, 5, 5, 5, 5, 5, 5, 5],
    [4, 4, 4, 5, 4, 4, 4, 5],
    [4, 4, 4, 5, 4, 4, 4, 5],
]
WATER = [
    [6, 6, 6, 6, 6, 6, 6, 6],
    [6, 3, 6, 6, 6, 6, 3, 6],
    [6, 6, 6, 3, 6, 6, 6, 6],
    [6, 6, 6, 6, 6, 6, 6, 6],
    [6, 6, 3, 6, 6, 3, 6, 6],
    [6, 6, 6, 6, 6, 6, 6, 6],
    [6, 3, 6, 6, 6, 6, 6, 3],
    [6, 6, 6, 6, 6, 6, 6, 6],
]
TORCH = [
    [0, 0, 0, 7, 7, 0, 0, 0],
    [0, 0, 7, 7, 7, 7, 0, 0],
    [0, 0, 7, 7, 7, 7, 0, 0],
    [0, 0, 0, 7, 7, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
]
# avatar: a tiny hero — blue tunic, red cape, skin face, dark outline
AVATAR = [
    [0, 0, 4, 4, 4, 0, 0, 0],
    [0, 4, 1, 1, 1, 4, 0, 0],
    [0, 4, 1, 1, 1, 4, 0, 0],
    [0, 3, 2, 2, 2, 3, 0, 0],
    [3, 3, 2, 2, 2, 3, 3, 0],
    [0, 4, 2, 2, 2, 4, 0, 0],
    [0, 0, 4, 0, 4, 0, 0, 0],
    [0, 0, 4, 0, 4, 0, 0, 0],
]

# --- Sprint 2 sprite-text glyphs (OBJ 8x8 tiles) ---
# The overworld has NO BG3 (Mode 7 owns BG1+OBJ only), so the NPC prompt is
# rendered with OBJ sprites, mirroring Phase 13's sprite-HUD glyph approach.
# Index 5 = bright-yellow indicator; index 6 = cream glyph fill. A small fresh
# uppercase font (only the letters the prompt strip needs) + a "!" indicator.
# Authored as flat-fill block letters so a screenshot pixel inside any lit glyph
# cell is the bright OBJ colour against the dark floor — an unambiguous test
# surface (CLAUDE.md "Indirect-Evidence Tests": read the rendered pixel, not a
# proxy flag). Tiles 6 and 7 stay EMPTY (the 16x16 avatar at base tile 5 reads
# {5,6,21,22}; tile 6 must not carry glyph pixels or the avatar would smear).
EMPTY8 = [[0] * 8 for _ in range(8)]
IND = [                              # "!" prompt indicator (yellow, index 5)
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
    [0, 0, 0, 5, 5, 0, 0, 0],
]
GLYPH_H = [                          # 'H' (cream glyph fill, index 6)
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
]
GLYPH_E = [                          # 'E'
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 6, 6, 6, 0, 0],
    [0, 6, 6, 6, 6, 6, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
]
GLYPH_L = [                          # 'L'
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 0, 0, 0, 0, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
]
GLYPH_O = [                          # 'O'
    [0, 0, 6, 6, 6, 6, 0, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 0, 0, 6, 6, 0],
    [0, 6, 6, 6, 6, 6, 6, 0],
    [0, 0, 6, 6, 6, 6, 0, 0],
]


# NOTE (GAP-4): a dead BG2 dialog-box CHR (the BOX_* tile patterns + a box_chr
# emission + BOX_OFF_*/BOX_*_COLOR constants) used to live here. The live
# template moved dialog to the sf_dialog macro (a turnkey OPAQUE BG3 nine-patch,
# see sf_dialog.inc), which emits its own box CHR — main.asm references none of
# the BOX_* symbols. The dead generator code + its stale town_assets.inc section
# were removed so a cold-start adapter reading this generator isn't misled into
# thinking a hand-rolled BG2 box is part of the asset contract.


def encode_2bpp(tile):
    """Encode an 8x8 index grid (0..3) to SNES 2bpp planar (16 bytes) — the same
    format the engine font uses (bitplanes 0,1 interleaved per row)."""
    out = bytearray()
    for row in tile:
        b0 = b1 = 0
        for x, idx in enumerate(row):
            assert 0 <= idx <= 3, f"index {idx} out of 2bpp range"
            bit = 7 - x
            b0 |= ((idx >> 0) & 1) << bit
            b1 |= ((idx >> 1) & 1) << bit
        out.append(b0)
        out.append(b1)
    return bytes(out)


def encode_4bpp(tile):
    """Encode an 8x8 index grid (0..15) to SNES 4bpp planar (32 bytes).
    4bpp = 4 bitplanes; bitplanes 0,1 interleaved per row (16 bytes), then
    bitplanes 2,3 interleaved per row (16 bytes)."""
    out = bytearray()
    # planes 0 & 1, row-interleaved
    for row in tile:
        b0 = b1 = 0
        for x, idx in enumerate(row):
            assert 0 <= idx <= 15, f"index {idx} out of 4bpp range"
            bit = 7 - x
            b0 |= ((idx >> 0) & 1) << bit
            b1 |= ((idx >> 1) & 1) << bit
        out.append(b0)
        out.append(b1)
    # planes 2 & 3, row-interleaved
    for row in tile:
        b2 = b3 = 0
        for x, idx in enumerate(row):
            bit = 7 - x
            b2 |= ((idx >> 2) & 1) << bit
            b3 |= ((idx >> 3) & 1) << bit
        out.append(b2)
        out.append(b3)
    return bytes(out)


def rgb15(r, g, b):
    return (b >> 3) << 10 | (g >> 3) << 5 | (r >> 3)


def emit_town():
    # CHR: tile 0 = empty (transparent), tiles 1..4 = town tileset, tile 5 =
    # avatar. Each tile is 32 bytes (4bpp).
    # Tiles 6 and 7 are EMPTY: the 16x16 avatar at base tile 5 reads the PPU's
    # fixed {5,6,21,22} quad, so tile 6 must stay transparent. The Sprint-2 OBJ
    # sprite-text glyphs then start at tile 8 (clear of {5,6,21,22}).
    EMPTY = [[0] * 8 for _ in range(8)]
    chr_tiles = [EMPTY, COBBLE, BRICK, WATER, TORCH, AVATAR,
                 EMPTY, EMPTY,                  # tiles 6,7 (avatar 16x16 quad)
                 IND, GLYPH_H, GLYPH_E, GLYPH_L, GLYPH_O]  # tiles 8..12
    chr_bytes = b"".join(encode_4bpp(t) for t in chr_tiles)

    def pal_words(pal):
        return [rgb15(*c) for c in pal]

    lines = [
        "; =============================================================================",
        "; town_assets.inc — Mode 1 town/battle CHR + palettes (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py",
        "; 4bpp BG CHR (tiles 0..5): 0=empty 1=cobble 2=brick 3=water 4=torch 5=avatar",
        "; town_bg_pal = 16-color BG palette 0; obj_pal = 16-color OBJ palette 0.",
        "; =============================================================================",
        "",
        "; --- BG/avatar CHR blob (6 tiles x 32 bytes = 192 bytes, 4bpp) ---",
        "town_chr:",
    ]
    for ti, t in enumerate(chr_tiles):
        enc = encode_4bpp(t)
        lines.append(f"    ; tile {ti}")
        for off in range(0, 32, 8):
            row = ", ".join(f"${enc[off + k]:02X}" for k in range(8))
            lines.append(f"    .byte {row}")
    lines += [
        f"TOWN_CHR_BYTES = {len(chr_bytes)}",
        "",
        "; tile-index constants (avatar is OBJ tile 5)",
        "TOWN_TILE_EMPTY  = 0",
        "TOWN_TILE_COBBLE = 1",
        "TOWN_TILE_BRICK  = 2",
        "TOWN_TILE_WATER  = 3",
        "TOWN_TILE_TORCH  = 4",
        "AVATAR_TILE      = 5",
        "; --- Sprint 2 OBJ sprite-text glyphs (tiles 8..12; 6/7 reserved empty",
        ";     for the avatar's 16x16 PPU quad). The prompt strip word is HELLO.",
        "PROMPT_TILE_IND  = 8    ; '!' indicator (shown only when adjacent to NPC)",
        "GLYPH_TILE_H     = 9",
        "GLYPH_TILE_E     = 10",
        "GLYPH_TILE_L     = 11",
        "GLYPH_TILE_O     = 12",
        "",
        "; --- BG palette 0 (16 colors, BGR15) ---",
        "town_bg_pal:",
    ]
    for w in pal_words(TOWN_BG_PAL):
        lines.append(f"    .word ${w:04X}")
    lines += [
        "TOWN_BG_PAL_COUNT = 1",
        "",
        "; --- OBJ palette 0 (16 colors, BGR15) — avatar ---",
        "obj_pal:",
    ]
    for w in pal_words(OBJ_PAL):
        lines.append(f"    .word ${w:04X}")

    # NOTE (GAP-4): a dead BG2 dialog-box CHR section used to be emitted here
    # (box_chr + BOX_OFF_*/BOX_*_COLOR). The live template uses the sf_dialog
    # macro's own opaque BG3 nine-patch; main.asm references none of those
    # symbols, so the dead emission was removed.
    lines += ["", ""]
    (HERE / "town_assets.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'town_assets.inc'} ({len(chr_bytes)} CHR bytes)")


def main():
    try:
        import toolchain.mode7_map_converter  # noqa: F401
    except ImportError:
        sys.exit("toolchain/ not importable — run from the kit root with "
                 "PYTHONPATH=. (see the header)")
    emit_ovw()
    emit_collision()
    emit_town()


if __name__ == "__main__":
    main()
