#!/usr/bin/env python3
"""gen_platformer_stream_assets.py — the rail's level blobs.

Emits, byte-identically on every run (pure integer math, no image input):

  pfs_flat.bin      32768 B  COLUMN-major tilemap: col N's 128 words at N*256
  pfs_flat_row.bin  32768 B  ROW-major tilemap:    row M's 128 words at M*256
  pfs_col.bin       16384 B  world-space collision, 1 byte/tile row-major
  pfs_flags.bin       256 B  col_map's tile-id -> flag LUT (see below)
  pfs_grad.bin        672 B  the dusk-sky COLDATA ramp (rgb_gradient's blob)
  pfs_world.inc              the geometry constants the rail assembles against

THE LEVEL LAYOUT'S CORRECTNESS IS A BYTE COMPARISON.
`author_level_seasons` below states a `--tall --seasons` level pipeline
directly, so the algorithm travels rather than an import. It is proven the only
way that can be proven: `tests/test_platformer_stream_assets.py`
asserts these three blobs are byte-identical to the committed reference
fixtures under `tests/fixtures/platformer_stream/`, which are the bytes the
published gallery render was built from. That is
ground truth this repo did not produce (the asset-import rule).

WHAT IS *NOT* GENERATED HERE, and why. The CHR (800 B, 25 tiles) and the
16-word palette derive from a Four Seasons tileset image that is in neither
reference. They are VENDORED instead — `vendor/art/platformer_stream/` with its
provenance README — following `vendor/art/m7_dungeon/ref_dungeon_map.bin`.
Generating them would require inventing art and would break the byte-identity
that makes the level check meaningful.
"""
import sys
from pathlib import Path

# --- world geometry (--tall: 128x128 tiles = 1024x1024 px) ------------------
W_TILES = 128
H_TILES = 128
W_META = W_TILES // 2                    # 64 metatile cells
H_META = H_TILES // 2

# --- metatile catalogue -----------------------------------------------------
# id -> (name, solid, [TL, TR, BL, BR] 8x8 tile ids). The quad table is NOT
# re-derived from a tileset image: it is the mapping the committed reference
# fixtures were built against, so it has to be stated, not inferred.
METATILES = [
    ("AIR",        False, (0,  0,  0,  0)),
    ("GROUND",     True,  (1,  2,  3,  4)),
    ("GROUND_TOP", True,  (5,  6,  7,  8)),
    ("PLATFORM",   True,  (9,  10, 11, 12)),
    ("DIRT",       True,  (13, 14, 15, 16)),
    ("BUSH",       False, (17, 18, 19, 20)),
    ("CRATE",      True,  (21, 22, 23, 24)),
]
AIR_ID = 0
ID = {name: i for i, (name, _s, _q) in enumerate(METATILES)}

# --- the seasons level's design constants -----------------------------------
SPAWN_META_X = 17        # metatile col the player spawns over (in the shaft)
SHAFT_X0     = 15        # shaft left metatile col (inclusive)
SHAFT_X1     = 19        # shaft right metatile col (inclusive)
SHAFT_TOP    = 8         # shaft mouth: metatile row of the launch ledge top
FLOOR_OFFSET = 4         # bedrock floor top row = H_META - this
WALL_META_X  = 40        # metatile col of the deliberate floor WALL pillar


def author_level_seasons(w_meta=W_META, h_meta=H_META):
    """The playable Four Seasons level. Deterministic and structural: the tile
    at (x, y) encodes level design, not a position id.

    The geometry is chosen so ordinary play drives BOTH streaming axes without
    scripted input — a deep open fall-shaft drops the player ~5 screens under
    gravity (the down axis), and a clean bedrock runway spans the full width
    (the across axis, forward and reverse).
    """
    W, H = w_meta, h_meta
    g = [[AIR_ID] * W for _ in range(H)]

    def in_shaft(x):
        return SHAFT_X0 <= x <= SHAFT_X1

    # --- bedrock floor along the bottom, with pits --------------------------
    # Pits stay OUT of the spawn->wall runway (cols 17..46) so the eastbound
    # run is a clean walk to the wall-collision pillar.
    floor_top = H - FLOOR_OFFSET                 # row 60
    floor_pits = {(6, 8), (52, 54)}

    def in_floor_pit(x):
        return any(a <= x <= b for (a, b) in floor_pits)

    for x in range(W):
        if in_floor_pit(x):
            continue
        g[floor_top][x] = ID["GROUND_TOP"]
        for y in range(floor_top + 1, H):
            g[y][x] = ID["GROUND"]

    # --- left high plateau (the spawn region) + launch ledge -----------------
    plateau_row = SHAFT_TOP                      # row 8
    for x in range(2, SHAFT_X0):                 # cols 2..14, stops at the shaft
        g[plateau_row][x] = ID["GROUND_TOP"]
        for d in (1, 2, 3):
            g[plateau_row + d][x] = ID["DIRT"]

    # --- stacked terraces (solid ledges w/ dirt faces) ----------------------
    # Spread across the FULL vertical extent so the fall reveals new content at
    # every depth band; kept out of the shaft columns so the fall stays clear.
    terraces = [
        (6, 34, 12), (5, 50, 10),
        (14, 24, 10), (13, 44, 14),
        (20, 6, 8), (22, 28, 12), (21, 48, 12),
        (28, 22, 12), (30, 40, 14), (29, 54, 8),
        (36, 4, 10), (38, 26, 12), (37, 48, 14),
        (44, 22, 14), (46, 40, 16),
        (52, 6, 16), (54, 36, 18),
    ]
    for (ry, tx, ln) in terraces:
        if ry >= floor_top:
            continue
        for x in range(tx, min(tx + ln, W)):
            if in_shaft(x):
                continue
            g[ry][x] = ID["GROUND_TOP"]
            for d in (1, 2):
                if ry + d < floor_top and g[ry + d][x] == AIR_ID:
                    g[ry + d][x] = ID["DIRT"]

    # --- floating wood platforms (jump targets) at many heights -------------
    platforms = [
        (8, 4, 12), (28, 4, 6), (44, 3, 10), (54, 4, 16),
        (10, 3, 24), (38, 4, 20), (50, 3, 26),
        (24, 4, 33), (42, 3, 40), (8, 4, 41),
        (32, 4, 48), (52, 3, 50), (22, 4, 55),
    ]
    for (tx, ln, ry) in platforms:
        if ry < 1 or ry >= floor_top:
            continue
        for x in range(tx, min(tx + ln, W)):
            if in_shaft(x):
                continue
            if g[ry][x] == AIR_ID:
                g[ry][x] = ID["PLATFORM"]

    # --- crates as landmarks on TERRACE surfaces only -----------------------
    # Never on the bedrock floor: a floor-resting crate is a solid wall that
    # would block the ground-level run end to end, and the horizontal
    # streaming proof needs that runway clear.
    for (ry, tx, ln) in terraces:
        cx = tx + ln // 2
        if in_shaft(cx):
            continue
        if ry - 1 >= 0 and g[ry][cx] != AIR_ID and g[ry - 1][cx] == AIR_ID:
            g[ry - 1][cx] = ID["CRATE"]
    if g[plateau_row][6] != AIR_ID and g[plateau_row - 1][6] == AIR_ID:
        g[plateau_row - 1][6] = ID["CRATE"]

    # --- ONE deliberate solid WALL rising from the floor --------------------
    # A 3-tall ground pillar far east of spawn, past the 64-col ring, so a
    # player running RIGHT along the clean runway hits a real wall and stops
    # flush — and reaching it also requires the column streamer to have
    # brought in new content.
    for d in range(1, 4):
        g[floor_top - d][WALL_META_X] = ID["GROUND"]

    # --- bush decoration on the floor surface -------------------------------
    for dx in range(3, W, 6):
        if in_shaft(dx) or in_floor_pit(dx) or dx == WALL_META_X:
            continue
        if g[floor_top][dx] != AIR_ID and g[floor_top - 1][dx] == AIR_ID:
            g[floor_top - 1][dx] = ID["BUSH"]

    # --- the designed climb chain: a climbable way back UP ------------------
    # The shaft carries the player DOWN by gravity; the level is two-way, so a
    # player at the bottom can climb back up under its own jumps. A monotonic
    # staircase of treads, each +2 metatile rows (32 px) up and +STEP_DX cols
    # RIGHT, non-overlapping horizontally so no tread sits above another's
    # column — zero head-bump risk. Measured on hardware: a held-direction
    # jump rises 39 px and drifts ~34 px by apex, so a 32 px step is sailed
    # over reliably.
    climb_x0 = 21
    step_dx = 3
    n_steps = 6
    climb_x1 = climb_x0 + step_dx * n_steps - 1        # = 38, clear of the wall
    climb_top_row = floor_top - 2 - 2 * (n_steps - 1)  # = 48

    # (1) clear the corridor of prior floating furniture, down ONLY to the
    #     tread band — never the floor row, so the runway stays walkable.
    for y in range(climb_top_row - 1, floor_top):
        for x in range(climb_x0, climb_x1 + 1):
            if in_shaft(x) or x == WALL_META_X:
                continue
            g[y][x] = AIR_ID

    # (2) lay the staircase from the floor up, west to east. The BASE tread is
    #     a FLOATING wood platform with no dirt face, so it does not wall the
    #     floor runway; the player walks under it and jumps up onto it.
    climb_cells = []
    cr = floor_top - 2
    cx = climb_x0
    for i in range(n_steps):
        kind = "beam" if i == 0 else "ledge"
        for x in range(cx, cx + step_dx):
            if climb_x0 <= x <= climb_x1 and not in_shaft(x) and x != WALL_META_X:
                climb_cells.append((cr, x, kind))
        cx += step_dx
        cr -= 2
    for (ry, x, kind) in climb_cells:
        if kind == "beam":
            g[ry][x] = ID["PLATFORM"]
        else:
            g[ry][x] = ID["GROUND_TOP"]
            if ry + 1 < floor_top and g[ry + 1][x] == AIR_ID:
                g[ry + 1][x] = ID["DIRT"]

    return g


def expand_to_bg_tiles(meta_grid, palette_group=0):
    """Metatile grid -> 8x8 BG tile grid. Returns (tile_words, solid), both
    row-major. A tilemap word is tile_id | pal<<10; the rail authors palette
    group 0, so the word IS the tile id."""
    pal = (palette_group & 0x07) << 10
    tile_words = [[0] * W_TILES for _ in range(H_TILES)]
    solid = [[0] * W_TILES for _ in range(H_TILES)]
    for my in range(H_META):
        for mx in range(W_META):
            mid = meta_grid[my][mx]
            is_solid, (tl, tr, bl, br) = METATILES[mid][1], METATILES[mid][2]
            for (dx, dy, bgid) in ((0, 0, tl), (1, 0, tr), (0, 1, bl), (1, 1, br)):
                tile_words[my * 2 + dy][mx * 2 + dx] = bgid | pal
                solid[my * 2 + dy][mx * 2 + dx] = 1 if is_solid else 0
    return tile_words, solid


def flat_column_major(tile_words):
    """Col N's H_TILES words contiguously, little-endian, at off = N*256."""
    out = bytearray()
    for col in range(W_TILES):
        for row in range(H_TILES):
            w = tile_words[row][col] & 0xFFFF
            out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def flat_row_major(tile_words):
    """Row M's W_TILES words contiguously, little-endian, at off = M*256."""
    out = bytearray()
    for row in range(H_TILES):
        for col in range(W_TILES):
            w = tile_words[row][col] & 0xFFFF
            out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def collision_row_major(solid):
    """One byte per tile, row-major: $01 solid / $00 air. This is col_map's
    blob, indexed by WORLD tile coordinate — so collision is independent of
    which 64x64 window happens to be streamed in."""
    out = bytearray()
    for row in range(H_TILES):
        for col in range(W_TILES):
            out.append(0x01 if solid[row][col] else 0x00)
    return bytes(out)


def col_map_flags():
    """col_map reads blob[ty*W + tx] as a TILE ID and returns CM_FLAGS[id].
    Our blob already holds the answer (0 air / 1 solid), so the LUT is the
    near-identity that turns it into col_map's flag vocabulary. Writing it out
    rather than special-casing col_map keeps the reuse literally zero-change.
    """
    t = bytearray(256)
    t[1] = 0x01                       # PFS_FLAG_SOLID
    return bytes(t)


# --- the dusk sky -----------------------------------------------------------
# rgb_gradient streams three static ROM tables into COLDATA ($2132), one byte
# per scanline per plane, plane_select | intensity (R=$20, G=$40, B=$80).
# The identical ramp can be built at RUNTIME from six endpoints via
# sf_gradient_rgb, and it is static — no phase — so a
# standing-still frame is byte-identical either way, which is exactly this feature's
# shape — so the interpolation bakes into ROM and the per-frame cost is zero.
GRAD_LINES = 224
DUSK_TOP = (24, 8, 2)                 # warm orange at the top of the ramp
DUSK_BOT = (2, 0, 12)                 # deep blue-purple at the bottom


def dusk_tables():
    out = bytearray()
    for plane_sel, top, bot in ((0x20, DUSK_TOP[0], DUSK_BOT[0]),
                                (0x40, DUSK_TOP[1], DUSK_BOT[1]),
                                (0x80, DUSK_TOP[2], DUSK_BOT[2])):
        for line in range(GRAD_LINES):
            # linear top->bottom, integer, rounded half-up at the midpoint
            v = top + ((bot - top) * line * 2 + GRAD_LINES) // (2 * GRAD_LINES)
            out.append(plane_sel | max(0, min(31, v)))
    return bytes(out)


def emit_inc(path, tile_words):
    """The geometry the rail assembles against. Emitted rather than hand-kept
    so the ASM cannot disagree with the blobs it reads."""
    spawn_x = SPAWN_META_X * 16                     # world px, box left
    lines = [
        "; pfs_world.inc — AUTO-GENERATED by tools/gen_platformer_stream_assets.py",
        "; DO NOT EDIT BY HAND.",
        "",
        "PFS_WORLD_W_TILES = {}".format(W_TILES),
        "PFS_WORLD_H_TILES = {}".format(H_TILES),
        "PFS_WORLD_W_LOG2  = 7",
        "PFS_WORLD_H_LOG2  = 7",
        "PFS_COL_BYTES     = {}".format(H_TILES * 2),
        "PFS_ROW_BYTES     = {}".format(W_TILES * 2),
        "PFS_WORLD_W_PX    = {}".format(W_TILES * 8),
        "PFS_WORLD_H_PX    = {}".format(H_TILES * 8),
        "",
        "; the spawn: in the mouth of the open fall-shaft (metatile cols"
        " {}..{}), so".format(SHAFT_X0, SHAFT_X1),
        "; gravity alone carries the player ~5 screens down to the bedrock"
        " floor and the",
        "; down-axis streaming proof needs no scripted input.",
        "PFS_SPAWN_X       = {}".format(spawn_x),
        "PFS_SPAWN_Y       = 136",
        "",
        "; the deliberate wall pillar the eastbound run stops flush against",
        "PFS_WALL_TILE_X   = {}".format(WALL_META_X * 2),
        "",
        "PFS_FLAG_SOLID    = $01",
        "",
    ]
    path.write_text("\n".join(lines))


def main(argv):
    if len(argv) != 2:
        print("usage: gen_platformer_stream_assets.py <outdir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)

    meta = author_level_seasons()
    tile_words, solid = expand_to_bg_tiles(meta)

    (out / "pfs_flat.bin").write_bytes(flat_column_major(tile_words))
    (out / "pfs_flat_row.bin").write_bytes(flat_row_major(tile_words))
    (out / "pfs_col.bin").write_bytes(collision_row_major(solid))
    (out / "pfs_flags.bin").write_bytes(col_map_flags())
    (out / "pfs_grad.bin").write_bytes(dusk_tables())
    emit_inc(out / "pfs_world.inc", tile_words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
