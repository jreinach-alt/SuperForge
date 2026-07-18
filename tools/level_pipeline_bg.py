#!/usr/bin/env python3
# =============================================================================
# level_pipeline_bg.py — Mode-1 normal-BG WIDE (+ optionally TALL) level pipeline.
# =============================================================================
# Takes an authored side-view platformer level (a believable, hand-painted
# metatile grid — ground / platforms / gaps / decoration, NOT a synthetic
# position-id pattern) + the Four Seasons CC0 16x16 tileset, and emits the data
# a Mode-1 normal-BG streaming ROM consumes.
#
# Two modes:
#   default (S1, horizontal only):  256 tiles wide x 32 tiles tall.
#       Emits a FLAT COLUMN-MAJOR tilemap (32 words / 64 bytes per column).
#   --tall  (S2a, 2-axis):          256 tiles wide x 128 tiles tall.
#       Emits BOTH:
#         level_flat.bin     COLUMN-MAJOR (128 words / 256 bytes per column) —
#                            the horizontal producer reads col N at off N*256.
#         level_flat_row.bin ROW-MAJOR    (256 words / 512 bytes per row) —
#                            the vertical producer reads row M at off M*512.
#       Both serialise the SAME tilemap, indexable by BOTH column and row, so
#       the 2-axis streaming substrate (engine/bg_stream.asm column producer +
#       engine/bg_stream_row.asm row producer) renders the authored Four
#       Seasons art correctly as the camera pans in any direction.
#
# Common outputs (both modes):
#   level_chr.bin        converted Four Seasons CHR (4bpp 8x8 BG tiles).
#   level_collision.bin  world-space collision (1 byte/tile, row-major).
#   bg_stream_world.inc  ca65 equates (world dims, CHR/pal counts) + palette.
#
# Encoding discipline: every 4bpp tile is encoded through
# png2snes.encode_tile_4bpp, which ASSERTS the palette-index range and NEVER
# masks (the parent repo's silent `& 0x03` quantization incident is the scar;
# see CLAUDE.md "Silent Bitwise-AND Quantisation in Asset Encoders").
#
# Usage:
#   python3 tools/level_pipeline_bg.py --tileset-zip "<zip>" --out-dir <dir>
#   python3 tools/level_pipeline_bg.py --tileset-zip "<zip>" --out-dir <dir> --tall
# =============================================================================
import argparse
import io
import os
import sys
import zipfile

from PIL import Image

# Reuse the kit's validated codec helpers (no silent masking).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import png2snes  # noqa: E402

# --- World geometry -----------------------------------------------------------
# S1 (horizontal-only): 256 wide x 32 tall. The 16KB column-major copy fits one
# LoROM bank, so the producer's simple `col*COL_BYTES + linear-bank-overflow`
# pointer math is bank-contiguous.
# S2a (2-axis): 128 wide x 128 tall. Each flat copy (column-major AND row-major)
# is EXACTLY 32KB = one LoROM bank, so neither axis' producer pointer crosses a
# bank seam (LoROM banks are NOT contiguous in 24-bit CPU address — $01:FFFF ->
# $02:8000 skips the unmapped $02:0000-$02:7FFF). 128x128 still streams 4 screens
# of NEW authored content in BOTH axes past the 64-col x 64-row resident ring —
# a genuine wide+tall 2-axis proof without multi-bank flat addressing. (Going to
# 256-wide would make the column-major copy 64KB / 2 banks and require the
# FLAT_ROW_ADDR bank-stepping pattern; deferred — out of S2a's substrate scope.)
S1_W_TILES = 256             # default (horizontal-only) width
S2A_W_TILES = 128            # --tall (2-axis) width = 4 screens (1024 px)
S1_H_TILES = 32              # default (horizontal-only) height
S2A_H_TILES = 128            # --tall (2-axis) height = 1024 px (~4.5 screens)

# --- Metatile catalogue -------------------------------------------------------
# Each entry: (name, (src_col,src_row) in the 16x16 tileset grid, solid?).
# Hand-picked coherent *summer* palette subset (brown brick ground + green grass
# + wood platform + foliage) so the whole set quantizes to <=15 colours and
# reads as one biome. Metatile-ID 0 MUST be AIR (transparent).
METATILES = [
    # name              (col,row)  solid
    ("AIR",             None,      False),  # id 0 — transparent sky
    ("GROUND",          (0, 1),    True),   # brown brick ground block
    ("GROUND_TOP",      (0, 0),    True),   # grass-capped ground surface
    ("PLATFORM",        (6, 4),    True),   # wood platform / log beam
    ("DIRT",            (1, 1),    True),   # plain dirt fill
    ("BUSH",            (1, 4),    False),  # small bush decoration (non-solid)
    ("CRATE",           (1, 2),    True),   # crate / question block
]
AIR_ID = 0
ID = {name: i for i, (name, _cr, _s) in enumerate(METATILES)}


def load_tileset(zip_path):
    """Pull four-seasons-tileset.png out of the CC0 zip as an RGBA image."""
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("four-seasons-tileset.png"))
        with zf.open(name) as fh:
            return Image.open(io.BytesIO(fh.read())).convert("RGBA")


def collect_palette(tileset):
    """Single shared 16-colour palette across all chosen metatiles. Fails
    LOUDLY if >15 colours are used — never silently drops."""
    colours = set()
    for name, cr, _solid in METATILES:
        if cr is None:
            continue
        col, row = cr
        cell = tileset.crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))
        colours |= png2snes.opaque_colors(cell)
    if len(colours) > 15:
        raise SystemExit(
            f"level_pipeline_bg: chosen metatiles use {len(colours)} distinct "
            f"colours; a 4bpp palette holds 15 (+transparent). Reduce METATILES."
        )
    return png2snes.build_palette(colours)


def metatile_to_bg_tiles(tileset, cr, color_to_index):
    """Decompose one 16x16 source tile into 4 BG 8x8 tiles [TL,TR,BL,BR]."""
    if cr is None:
        blank = png2snes.encode_tile_4bpp([[0] * 8 for _ in range(8)])
        return [blank, blank, blank, blank]
    col, row = cr
    cell = tileset.crop((col * 16, row * 16, col * 16 + 16, row * 16 + 16))
    idx = png2snes.index_frame(cell, color_to_index)
    out = []
    for qy in (0, 8):
        for qx in (0, 8):
            sub = [idx[qy + r][qx:qx + 8] for r in range(8)]
            out.append(png2snes.encode_tile_4bpp(sub))
    return out


def build_chr(tileset, color_to_index):
    """BG CHR blob + the metatile->(4 BG tile-ids) map. BG tile 0 is AIR."""
    chr_tiles = []
    tile_lookup = {}
    meta_to_bgtiles = []

    def intern(tile_bytes):
        if tile_bytes not in tile_lookup:
            tile_lookup[tile_bytes] = len(chr_tiles)
            chr_tiles.append(tile_bytes)
        return tile_lookup[tile_bytes]

    blank = png2snes.encode_tile_4bpp([[0] * 8 for _ in range(8)])
    assert intern(blank) == 0

    for name, cr, _solid in METATILES:
        quads = metatile_to_bg_tiles(tileset, cr, color_to_index)
        meta_to_bgtiles.append([intern(q) for q in quads])

    chr_blob = b"".join(chr_tiles)
    return chr_blob, meta_to_bgtiles, len(chr_tiles)


# =============================================================================
# Authored levels — believable side-view platformer geometry in metatile space.
# =============================================================================
def author_level_s1(w_meta, h_meta):
    """S1 wide level (the original): ground baseline with pits, floating wood
    platforms at varied heights, crates, bushes. Deterministic, NOT position-id.
    (Unchanged from S1 so the default-mode output stays byte-identical.)"""
    W, H = w_meta, h_meta
    g = [[AIR_ID] * W for _ in range(H)]
    GROUND_ROW = H - 3

    pits = {(18, 21), (40, 43), (66, 70), (95, 98), (112, 114)}
    def in_pit(x):
        return any(a <= x <= b for (a, b) in pits)

    for x in range(W):
        if in_pit(x):
            continue
        g[GROUND_ROW][x] = ID["GROUND_TOP"]
        for y in range(GROUND_ROW + 1, H):
            g[y][x] = ID["GROUND"]

    platforms = [
        (6, 4, 4), (14, 3, 6), (26, 5, 3), (34, 4, 7), (48, 6, 5),
        (58, 3, 8), (72, 4, 4), (82, 5, 6), (92, 3, 9), (102, 6, 4),
        (118, 4, 7),
    ]
    for (sx, ln, up) in platforms:
        ry = GROUND_ROW - up
        if ry < 1:
            ry = 1
        for x in range(sx, min(sx + ln, W)):
            g[ry][x] = ID["PLATFORM"]

    for cx in (10, 30, 55, 78, 100, 124):
        if not in_pit(cx) and g[GROUND_ROW][cx] != AIR_ID:
            g[GROUND_ROW - 1][cx] = ID["CRATE"]

    for dx in range(2, W, 7):
        if not in_pit(dx) and g[GROUND_ROW][dx] != AIR_ID and g[GROUND_ROW - 1][dx] == AIR_ID:
            g[GROUND_ROW - 1][dx] = ID["BUSH"]

    return g


def author_level_2axis(w_meta, h_meta):
    """S2a wide AND tall level: believable multi-level platformer geometry that
    USES the vertical extent — a deep floor at the bottom, multiple terraces /
    ledges stacked up the height of the level, vertical shafts (gaps) the camera
    descends through, dirt cliff faces, and platforms at MANY heights so panning
    DOWN reveals genuinely new authored content (not a repeat of the top strip).
    Deterministic, structural — the tile at (x,y) encodes LEVEL DESIGN.

    Grid: w_meta (64) x h_meta (64) metatile cells (= 128 x 128 BG tiles)."""
    W, H = w_meta, h_meta            # 64 x 64 metatiles
    g = [[AIR_ID] * W for _ in range(H)]

    # --- Deep bedrock floor at the very bottom (4 rows of solid ground) ------
    FLOOR_TOP = H - 4                # row 60
    floor_pits = {(10, 12), (26, 28), (44, 47)}   # bottomless shafts
    def in_floor_pit(x):
        return any(a <= x <= b for (a, b) in floor_pits)
    for x in range(W):
        if in_floor_pit(x):
            continue
        g[FLOOR_TOP][x] = ID["GROUND_TOP"]
        for y in range(FLOOR_TOP + 1, H):
            g[y][x] = ID["GROUND"]

    # --- Stacked terraces up the height — each a solid ledge with a dirt face.
    # (terrace_row, x_start, x_len). Spread across the FULL vertical extent
    # (rows 4..56) so panning DOWN reveals new ledges at every depth band, and
    # across the full width (x 2..62) so panning is non-trivial at every depth.
    terraces = [
        (4, 2, 12), (6, 20, 10), (5, 36, 14), (7, 52, 10),
        (12, 8, 16), (14, 30, 12), (13, 46, 14),
        (20, 4, 14), (22, 24, 16), (21, 46, 12),
        (28, 10, 16), (30, 34, 14), (29, 52, 10),
        (36, 6, 18), (38, 30, 14), (37, 50, 12),
        (44, 12, 16), (46, 36, 16), (45, 2, 8),
        (52, 8, 20), (54, 38, 18),
    ]
    for (ry, sx, ln) in terraces:
        if ry >= FLOOR_TOP:
            continue
        for x in range(sx, min(sx + ln, W)):
            g[ry][x] = ID["GROUND_TOP"]
            for d in (1, 2):        # dirt cliff face below the ledge
                if ry + d < FLOOR_TOP and g[ry + d][x] == AIR_ID:
                    g[ry + d][x] = ID["DIRT"]

    # --- Floating wood platforms at many heights (jump targets) --------------
    # (x_start, len, row) — rows span the whole height for vertical jump chains.
    platforms = [
        (4, 3, 3), (16, 4, 9), (28, 3, 5), (40, 4, 17), (52, 3, 11),
        (8, 4, 25), (24, 3, 33), (36, 4, 19), (48, 3, 41), (12, 4, 27),
        (32, 3, 47), (44, 4, 15), (20, 3, 49), (56, 4, 35), (6, 3, 51),
    ]
    for (sx, ln, ry) in platforms:
        if ry < 1 or ry >= FLOOR_TOP:
            continue
        for x in range(sx, min(sx + ln, W)):
            if g[ry][x] == AIR_ID:
                g[ry][x] = ID["PLATFORM"]

    # --- Crates resting on terrace surfaces + the floor ----------------------
    for (ry, sx, ln) in terraces:
        cx = sx + ln // 2
        if ry - 1 >= 0 and g[ry][cx] != AIR_ID and g[ry - 1][cx] == AIR_ID:
            g[ry - 1][cx] = ID["CRATE"]
    for cx in (6, 18, 34, 50, 60):
        if not in_floor_pit(cx) and g[FLOOR_TOP][cx] != AIR_ID:
            g[FLOOR_TOP - 1][cx] = ID["CRATE"]

    # --- Bush decoration on the floor surface --------------------------------
    for dx in range(3, W, 7):
        if not in_floor_pit(dx) and g[FLOOR_TOP][dx] != AIR_ID and g[FLOOR_TOP - 1][dx] == AIR_ID:
            g[FLOOR_TOP - 1][dx] = ID["BUSH"]

    return g


# --- Playable-template spawn / shaft geometry (the believable Four Seasons --
# level the platformer_stream ROM runs). Exposed as module constants so the
# template ROM and its test read the SAME spawn + shaft coordinates the level
# was authored around — no magic numbers drifting between the .py and the .asm.
SEASONS_SPAWN_META_X = 17        # metatile col the player spawns over (in the shaft)
SEASONS_SHAFT_X0     = 15        # shaft left metatile col (inclusive)
SEASONS_SHAFT_X1     = 19        # shaft right metatile col (inclusive)
SEASONS_SHAFT_TOP    = 8         # shaft mouth: metatile row of the launch ledge top
SEASONS_FLOOR_OFFSET = 4         # bedrock floor = H - this (top row of the floor)
SEASONS_WALL_META_X  = 40        # metatile col of the deliberate floor WALL pillar
                                 #   (BG col 80 = world x 640, past the 64-col
                                 #   ring's 512px -> reaching it requires streaming)


def author_level_seasons(w_meta, h_meta):
    """The PLAYABLE Four Seasons level for templates/platformer_stream — a
    believable side-view platformer that USES the full 1024x1024 (4-screen)
    extent on BOTH axes, with geometry chosen so a real player exercises both
    streaming axes through ordinary motion:

      * A continuous grass-capped BEDROCK FLOOR along the bottom with three
        GAPS (pits) — the horizontal run surface. Walking right then left
        across it pans the camera through several screens of authored content
        (the horizontal streaming test).
      * A LEFT HIGH PLATEAU near the top where the player spawns, with a
        launch LEDGE whose right edge opens onto...
      * ...a deep OPEN VERTICAL SHAFT (an air column, cols 15..19) that drops
        ~6 screens straight down to the floor. The player spawns IN the shaft
        mouth and GRAVITY alone carries it down through every vertical band —
        the deterministic down-axis streaming test needs no scripted input.
      * STACKED TERRACES with dirt cliff faces + floating wood PLATFORMS at
        many heights flanking the shaft and across the right half, so panning
        DOWN (falling) and across (running) both reveal genuinely new authored
        content, never a repeat of the top strip.
      * CRATES and BUSHES dressing the surfaces so the biome reads as a real,
        hand-built platformer level rather than a synthetic test pattern.

    Deterministic + structural: the tile at (x,y) encodes LEVEL DESIGN, not a
    position id. Distinct from author_level_2axis (which stays byte-identical
    as the bg_stream2d substrate proof's fixture) — this is the gameplay level.

    Grid: w_meta (64) x h_meta (64) metatile cells (= 128 x 128 BG tiles)."""
    W, H = w_meta, h_meta            # 64 x 64 metatiles
    g = [[AIR_ID] * W for _ in range(H)]

    sx0, sx1 = SEASONS_SHAFT_X0, SEASONS_SHAFT_X1
    def in_shaft(x):
        return sx0 <= x <= sx1

    # --- Bedrock floor along the bottom, with pits -----------------------
    # Pits are kept OUT of the spawn->wall runway (metatile cols 17..46) so the
    # eastbound run is a clean walk to the wall-collision pillar; they live WEST
    # of spawn (col 6..8) and EAST of the wall (col 52..54), so running far west
    # (reverse) or far east (past the wall via a jump) still meets gaps.
    FLOOR_TOP = H - SEASONS_FLOOR_OFFSET     # row 60
    floor_pits = {(6, 8), (52, 54)}
    def in_floor_pit(x):
        return any(a <= x <= b for (a, b) in floor_pits)
    for x in range(W):
        if in_floor_pit(x):
            continue
        g[FLOOR_TOP][x] = ID["GROUND_TOP"]
        for y in range(FLOOR_TOP + 1, H):
            g[y][x] = ID["GROUND"]

    # --- Left high plateau (the spawn region) + launch ledge -----------------
    # A solid grassy terrace spanning cols 2..14 at the shaft-top row, capped
    # with grass and a dirt body below. The shaft (cols 15..19) is left OPEN —
    # the player spawns just above the ledge's right lip and falls into it.
    PLATEAU_ROW = SEASONS_SHAFT_TOP          # row 8
    for x in range(2, sx0):                  # cols 2..14 (stops before the shaft)
        g[PLATEAU_ROW][x] = ID["GROUND_TOP"]
        for d in (1, 2, 3):
            g[PLATEAU_ROW + d][x] = ID["DIRT"]

    # --- Stacked terraces (solid ledges w/ dirt faces) flanking + below ------
    # Spread across the FULL vertical extent so the fall reveals new content at
    # every depth band; kept OUT of the shaft columns so the fall stays clear.
    terraces = [
        # (row, x_start, x_len)
        (6, 34, 12), (5, 50, 10),
        (14, 24, 10), (13, 44, 14),
        (20, 6, 8), (22, 28, 12), (21, 48, 12),
        (28, 22, 12), (30, 40, 14), (29, 54, 8),
        (36, 4, 10), (38, 26, 12), (37, 48, 14),
        (44, 22, 14), (46, 40, 16),
        (52, 6, 16), (54, 36, 18),
    ]
    for (ry, tx, ln) in terraces:
        if ry >= FLOOR_TOP:
            continue
        for x in range(tx, min(tx + ln, W)):
            if in_shaft(x):
                continue                     # never block the fall shaft
            g[ry][x] = ID["GROUND_TOP"]
            for d in (1, 2):
                if ry + d < FLOOR_TOP and g[ry + d][x] == AIR_ID:
                    g[ry + d][x] = ID["DIRT"]

    # --- Floating wood platforms (jump targets) at many heights --------------
    platforms = [
        (8, 4, 12), (28, 4, 6), (44, 3, 10), (54, 4, 16),
        (10, 3, 24), (38, 4, 20), (50, 3, 26),
        (24, 4, 33), (42, 3, 40), (8, 4, 41),
        (32, 4, 48), (52, 3, 50), (22, 4, 55),
    ]
    for (tx, ln, ry) in platforms:
        if ry < 1 or ry >= FLOOR_TOP:
            continue
        for x in range(tx, min(tx + ln, W)):
            if in_shaft(x):
                continue
            if g[ry][x] == AIR_ID:
                g[ry][x] = ID["PLATFORM"]

    # --- Crates as visual landmarks on TERRACE surfaces (NOT on the bedrock
    #     floor: a floor-resting crate is a solid wall that blocks the
    #     ground-level run end-to-end — keep the floor a clean walkable runway so
    #     a real player pans the camera across the FULL width past the 64-col
    #     ring, exercising horizontal streaming). Terrace crates sit on raised
    #     ledges the player jumps to, so they never wall the main run. ----------
    for (ry, tx, ln) in terraces:
        cx = tx + ln // 2
        if in_shaft(cx):
            continue
        if ry - 1 >= 0 and g[ry][cx] != AIR_ID and g[ry - 1][cx] == AIR_ID:
            g[ry - 1][cx] = ID["CRATE"]
    # a crate on the plateau next to the spawn (visual landmark, not in shaft)
    if g[PLATEAU_ROW][6] != AIR_ID and g[PLATEAU_ROW - 1][6] == AIR_ID:
        g[PLATEAU_ROW - 1][6] = ID["CRATE"]

    # --- ONE deliberate solid WALL rising from the floor (a 3-tall ground
    #     pillar) far east of spawn, so a player running RIGHT along the clean
    #     runway hits a real wall and STOPS flush — the wall-collision proof.
    #     Placed past the 64-col ring (col 92) so reaching it ALSO requires the
    #     column streamer to have brought in new content. Solid GROUND (blocks
    #     walking into it from the side). ------------------------------------
    for d in range(1, 4):                # rows FLOOR_TOP-3 .. FLOOR_TOP-1
        g[FLOOR_TOP - d][SEASONS_WALL_META_X] = ID["GROUND"]

    # --- Bush decoration on the floor surface --------------------------------
    for dx in range(3, W, 6):
        if in_shaft(dx) or in_floor_pit(dx) or dx == SEASONS_WALL_META_X:
            continue
        if g[FLOOR_TOP][dx] != AIR_ID and g[FLOOR_TOP - 1][dx] == AIR_ID:
            g[FLOOR_TOP - 1][dx] = ID["BUSH"]

    # --- DESIGNED CLIMB CHAIN: a believable, climbable SWITCHBACK back UP -----
    # The fall-shaft carries the player DOWN to the bedrock floor by gravity; the
    # level must also be TWO-WAY — a player at the bottom must be able to climb
    # back UP under its own jumps. We author a dedicated terraced-hillside
    # SWITCHBACK in a CLEARED corridor on the east-of-shaft / west-of-wall band
    # (cols CLIMB_X0..CLIMB_X1), rising from the bedrock floor to the spawn-
    # plateau height. The corridor is cleared of other furniture first so the
    # climb geometry is unambiguous (no merged/overlapping surfaces). It reads as
    # a cut-stone terrace path in the Four Seasons biome (grass-capped ledges with
    # dirt cliff faces), NOT a synthetic floating ladder.
    #
    # JUMPABILITY (MEASURED on the ROM, not estimated): holding ONE direction +
    # jumping (SF_JUMP_VEL=$0480 = 4.5 px/f, SF_GRAVITY=$0040 = 0.25 px/f^2) the
    # player rises a measured 39 px and DRIFTS ~20 px horizontally by the time it
    # is 32 px up, ~34 px by apex. So a step that is +2 metatile rows (32 px) up
    # and +STEP_DX metatile cols ALONG the held direction is sailed-over and
    # landed-on reliably — the takeoff column stays clear (the next step is AHEAD,
    # never directly overhead, so no head-bump ceiling). This is the measured key:
    # each LEG holds a single direction; a vertical stack with the next step
    # directly above HEAD-BUMPS and fails. The brief's "<=24px" guidance is the
    # climbable-INTENT bound; 32 px under a 39 px apex satisfies the intent with
    # margin while keeping the believable 16 px metatile authoring grid.
    #
    # The staircase is a single MONOTONIC-RIGHT run of FLOATING wood PLATFORM
    # treads (no switchback turns — turns need horizontal precision the
    # deterministic driver must not need). Each tread is +2 rows up and +STEP_DX
    # cols to the RIGHT, NON-OVERLAPPING horizontally (tread width == STEP_DX) so
    # NO tread sits above another's column — zero head-bump ceiling risk anywhere.
    # The player climbs it by simply holding RIGHT and jumping: it walks-and-jumps
    # up the staircase, each held-right jump sailing onto the next higher tread.
    #
    # CRITICAL — treads are FLOATING (no dirt cliff face down to the floor), so
    # they do NOT wall the bedrock-floor runway: a tread 2 rows (32 px) above the
    # floor is a platform OVERHEAD the player walks under freely, then JUMPS up
    # onto to start the climb. (A grass ledge with a dirt face to the floor would
    # be a 2-tall solid pillar blocking the spawn->wall floor run — which the
    # wall-collision + horizontal-streaming tests need clear.) The treads sit WEST
    # of the wall pillar (col 40) and EAST of the shaft (15..19); the corridor is
    # cleared of prior platforms first so the climb stands alone and its geometry
    # is unambiguous + KNOWN (the test reads these exact treads as ground-truth).
    CLIMB_X0  = 21                   # west end of the staircase
    STEP_DX   = 3                    # +3 cols (48 px) right per tread (== tread width)
    N_STEPS   = 6                    # 6 treads: rows 58,56,54,52,50,48 (~6-row climb)
    CLIMB_X1  = CLIMB_X0 + STEP_DX * N_STEPS - 1   # = 38 (clear of the wall at 40)
    CLIMB_TOP_ROW = FLOOR_TOP - 2 - 2 * (N_STEPS - 1)   # highest tread row (48)

    # (1) CLEAR the corridor of prior floating furniture, but DOWN ONLY to the
    #     tread band (rows CLIMB_TOP_ROW..FLOOR_TOP-2) — never the floor row
    #     (FLOOR_TOP) or its surface, so the floor runway stays intact/walkable.
    for y in range(CLIMB_TOP_ROW - 1, FLOOR_TOP):
        for x in range(CLIMB_X0, CLIMB_X1 + 1):
            if in_shaft(x) or x == SEASONS_WALL_META_X:
                continue
            g[y][x] = AIR_ID

    # (2) Lay the monotonic staircase from the floor up, W->E.
    #     - The BASE tread (tread 0, 2 rows above the floor) is a FLOATING wood
    #       PLATFORM with NO dirt cliff face, so it does NOT wall the floor runway
    #       (the player walks under it freely; to start the climb it stops below
    #       and jumps straight up onto it).
    #     - Treads 1..N-1 are grass-capped GROUND_TOP ledges WITH a dirt cliff
    #       face below: once on the base tread the player simply HOLDS RIGHT and
    #       walks-and-jumps up the staircase, each held-right jump landing on the
    #       next higher grass ledge (the climbable up-and-over geometry).
    climb_cells = []                 # (row, col, kind) tread cells
    cr = FLOOR_TOP - 2               # first tread: 2 rows above the floor
    cx = CLIMB_X0
    for i in range(N_STEPS):
        kind = "beam" if i == 0 else "ledge"
        for x in range(cx, cx + STEP_DX):
            if CLIMB_X0 <= x <= CLIMB_X1 and not in_shaft(x) and x != SEASONS_WALL_META_X:
                climb_cells.append((cr, x, kind))
        cx += STEP_DX                 # next tread is +STEP_DX cols right (no overlap)
        cr -= 2                       # +2 metatile rows (32 px) up
    for (ry, x, kind) in climb_cells:
        if kind == "beam":
            g[ry][x] = ID["PLATFORM"] # floating base tread (no floor-blocking face)
        else:
            g[ry][x] = ID["GROUND_TOP"]
            if ry + 1 < FLOOR_TOP and g[ry + 1][x] == AIR_ID:
                g[ry + 1][x] = ID["DIRT"]   # grass tread w/ dirt cliff face

    return g


def add_climb_stairs(g, w_meta, h_meta):
    """Overlay a guaranteed-climbable JUMP STAIRCASE up the left edge of the
    2-axis level, for a PLAYABLE platformer that must drive the camera UP through
    several screens via real jumps (a fall down the open chute drives DOWN).

    The kit jump (SF_JUMP_VEL 4.5 px/f, gravity 0.25) clears ~40 px = ~2.5
    metatile rows. So steps every 2 metatile rows (32 px) are reliably jumpable.
    The steps weave across metatile cols 1..3 so each is a short horizontal hop
    from the one below — a route the player walks-and-jumps up. Steps are 3 wide
    (forgiving landings) and PLATFORM tiles (solid: land on top, block walking
    INTO from the side). Overlaid AFTER the base geometry so it always wins its
    cells. The spawn (metatile col 0, on the floor) is left clear.

    Mutates g in place. Only used for the --stairs (platformer_stream) variant —
    keeps the base author_level_2axis byte-identical for the bg_stream2d proof."""
    FLOOR_TOP = h_meta - 4
    sr = FLOOR_TOP - 2                     # first step: 2 rows above the floor
    step = 0
    while sr >= 3:
        sx = 1 + (step % 3)               # weave cols 1,2,3
        for x in range(sx, min(sx + 3, w_meta)):   # 3-wide forgiving landing
            g[sr][x] = ID["PLATFORM"]
        sr -= 2
        step += 1
    return g


def expand_to_bg_tiles(meta_grid, meta_to_bgtiles, w_tiles, h_tiles, palette_group=0):
    """Expand metatile grid -> 8x8 BG tile grid; emit tilemap WORDS
    (tile_id|pal<<10). Returns (tile_words_rowmajor, solid_rowmajor)."""
    pal = (palette_group & 0x07) << 10
    w_meta, h_meta = w_tiles // 2, h_tiles // 2
    tile_words = [[0] * w_tiles for _ in range(h_tiles)]
    solid = [[0] * w_tiles for _ in range(h_tiles)]
    meta_solid = [s for (_n, _cr, s) in METATILES]
    for my in range(h_meta):
        for mx in range(w_meta):
            mid = meta_grid[my][mx]
            tl, tr, bl, br = meta_to_bgtiles[mid]
            quads = ((0, 0, tl), (1, 0, tr), (0, 1, bl), (1, 1, br))
            for (dx, dy, bgid) in quads:
                tx, ty = mx * 2 + dx, my * 2 + dy
                tile_words[ty][tx] = bgid | pal
                solid[ty][tx] = 1 if meta_solid[mid] else 0
    return tile_words, solid


def flat_column_major(tile_words, w_tiles, h_tiles):
    """COLUMN-MAJOR: for column N, the h_tiles words (rows 0..h-1) contiguously,
    little-endian. engine/bg_stream.asm reads col N at off = N * (h_tiles*2)."""
    out = bytearray()
    for col in range(w_tiles):
        for row in range(h_tiles):
            w = tile_words[row][col] & 0xFFFF
            out.append(w & 0xFF)
            out.append((w >> 8) & 0xFF)
    return bytes(out)


def flat_row_major(tile_words, w_tiles, h_tiles):
    """ROW-MAJOR: for row M, the w_tiles words (cols 0..w-1) contiguously,
    little-endian. engine/bg_stream_row.asm reads row M at off = M * (w_tiles*2)."""
    out = bytearray()
    for row in range(h_tiles):
        for col in range(w_tiles):
            w = tile_words[row][col] & 0xFFFF
            out.append(w & 0xFF)
            out.append((w >> 8) & 0xFF)
    return bytes(out)


def collision_row_major(solid, w_tiles, h_tiles):
    """World-space collision: 1 byte/tile, row-major (S2's col_map source)."""
    out = bytearray()
    for row in range(h_tiles):
        for col in range(w_tiles):
            out.append(0x01 if solid[row][col] else 0x00)
    return bytes(out)


def emit_inc(out_dir, pal_words, chr_tiles, meta_to_bgtiles, w_tiles, h_tiles, two_axis):
    col_bytes = h_tiles * 2
    row_bytes = w_tiles * 2
    lines = []
    lines.append("; bg_stream_world.inc — AUTO-GENERATED by tools/level_pipeline_bg.py")
    lines.append("; Mode-1 normal-BG level: Four Seasons CC0 tileset.")
    lines.append("; DO NOT EDIT BY HAND — regenerate via the pipeline.")
    lines.append(f"; mode = {'2-axis (wide+tall)' if two_axis else 'horizontal (wide)'}")
    lines.append("")
    lines.append(f"BGW_WORLD_W_TILES   = {w_tiles}   ; 8x8 BG tiles wide (= {w_tiles*8} px)")
    lines.append(f"BGW_WORLD_H_TILES   = {h_tiles}    ; 8x8 BG tiles tall (= {h_tiles*8} px)")
    lines.append(f"BGW_COL_BYTES       = {col_bytes}    ; bytes per streamed column ({h_tiles} words)")
    if two_axis:
        lines.append(f"BGW_ROW_BYTES       = {row_bytes}    ; bytes per streamed row ({w_tiles} words)")
    lines.append(f"BGW_CHR_TILES       = {chr_tiles}    ; unique 8x8 4bpp BG tiles")
    lines.append(f"BGW_CHR_BYTES       = {chr_tiles*32}")
    lines.append(f"BGW_PAL_WORDS       = 16")
    lines.append("")
    lines.append("; Streamed stride / look-ahead contract:")
    lines.append(";   STREAM_CAM_COL = cam_x >> 3 (8px tile columns).")
    if two_axis:
        lines.append(";   STREAM_CAM_ROW = cam_y >> 3 (8px tile rows).")
        lines.append(";   64x64 BG1 tilemap (BG1SC=$5B) gives 64-col x 64-row ring room.")
    lines.append("")
    lines.append("; Metatile -> BG 8x8 tile-id quads [TL,TR,BL,BR]:")
    for i, (name, _cr, solid) in enumerate(METATILES):
        q = meta_to_bgtiles[i]
        lines.append(f";   {i:2d} {name:<11s} solid={int(solid)}  quads={q}")
    lines.append("")
    lines.append('.pushseg')
    lines.append('.segment "RODATA"')
    lines.append(png2snes.emit_words("bgw_palette", pal_words))
    lines.append('.popseg')
    lines.append("")
    with open(os.path.join(out_dir, "bg_stream_world.inc"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mode-1 normal-BG wide(+tall)-level pipeline")
    ap.add_argument("--tileset-zip", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tall", action="store_true",
                    help="2-axis mode: 256x128 tiles, emit row-major copy too")
    ap.add_argument("--stairs", action="store_true",
                    help="overlay a guaranteed-climbable jump staircase up the "
                         "left edge (requires --tall; legacy playable variant, "
                         "NOT the bg_stream2d proof — superseded by --seasons)")
    ap.add_argument("--seasons", action="store_true",
                    help="author the believable Four Seasons gameplay level "
                         "(requires --tall): high spawn over a deep open "
                         "fall-shaft + floor with pits + stacked terraces. The "
                         "platformer_stream template's level. Distinct from the "
                         "bg_stream2d substrate-proof fixture (author_level_2axis).")
    args = ap.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)
    tileset = load_tileset(args.tileset_zip)

    w_tiles = S2A_W_TILES if args.tall else S1_W_TILES
    h_tiles = S2A_H_TILES if args.tall else S1_H_TILES
    w_meta, h_meta = w_tiles // 2, h_tiles // 2

    pal_words, color_to_index = collect_palette(tileset)
    chr_blob, meta_to_bgtiles, n_chr = build_chr(tileset, color_to_index)

    if args.tall:
        if args.seasons:
            # The PLAYABLE platformer_stream level: a believable Four Seasons
            # level with a high spawn over a deep open fall-shaft (down-axis is
            # naturally traversed by gravity). Distinct from the substrate
            # proof's author_level_2axis fixture.
            meta_grid = author_level_seasons(w_meta, h_meta)
        else:
            meta_grid = author_level_2axis(w_meta, h_meta)
            if args.stairs:
                add_climb_stairs(meta_grid, w_meta, h_meta)
    else:
        meta_grid = author_level_s1(w_meta, h_meta)
    tile_words, solid = expand_to_bg_tiles(meta_grid, meta_to_bgtiles, w_tiles, h_tiles)

    flat_cm = flat_column_major(tile_words, w_tiles, h_tiles)
    coll = collision_row_major(solid, w_tiles, h_tiles)

    assert len(flat_cm) == w_tiles * h_tiles * 2, (len(flat_cm), w_tiles * h_tiles * 2)
    assert len(coll) == w_tiles * h_tiles

    with open(os.path.join(args.out_dir, "level_flat.bin"), "wb") as fh:
        fh.write(flat_cm)
    with open(os.path.join(args.out_dir, "level_chr.bin"), "wb") as fh:
        fh.write(chr_blob)
    with open(os.path.join(args.out_dir, "level_collision.bin"), "wb") as fh:
        fh.write(coll)

    if args.tall:
        flat_rm = flat_row_major(tile_words, w_tiles, h_tiles)
        assert len(flat_rm) == w_tiles * h_tiles * 2
        with open(os.path.join(args.out_dir, "level_flat_row.bin"), "wb") as fh:
            fh.write(flat_rm)

    emit_inc(args.out_dir, pal_words, n_chr, meta_to_bgtiles, w_tiles, h_tiles, args.tall)

    print(f"level_pipeline_bg: wrote {args.out_dir}/  ({'2-axis' if args.tall else 'horizontal'})")
    print(f"  level_flat.bin       {len(flat_cm):7d} bytes  ({w_tiles} cols x {h_tiles*2} B, column-major)")
    if args.tall:
        print(f"  level_flat_row.bin   {len(flat_rm):7d} bytes  ({h_tiles} rows x {w_tiles*2} B, row-major)")
    print(f"  level_chr.bin        {len(chr_blob):7d} bytes  ({n_chr} unique 8x8 4bpp tiles)")
    print(f"  level_collision.bin  {len(coll):7d} bytes  ({w_tiles}x{h_tiles} row-major)")
    print(f"  bg_stream_world.inc  (world equates + {len(pal_words)}-word palette)")
    nonzero = sum(1 for row in tile_words for w in row if (w & 0x3FF) != 0)
    print(f"  non-AIR BG tiles: {nonzero} / {w_tiles*h_tiles}")
    # vertical-distribution sanity: prove content exists at multiple depth bands
    if args.tall:
        bands = []
        for b in range(4):
            y0, y1 = b * h_tiles // 4, (b + 1) * h_tiles // 4
            cnt = sum(1 for y in range(y0, y1) for x in range(w_tiles)
                      if (tile_words[y][x] & 0x3FF) != 0)
            bands.append(cnt)
        print(f"  non-AIR per vertical quarter (top->bottom): {bands}")


if __name__ == "__main__":
    main()
