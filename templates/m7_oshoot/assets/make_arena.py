#!/usr/bin/env python3
"""make_arena.py — authored OPEN Mode 7 arena floor for m7_oshoot.

The overhead-shooter arena: a large OPEN floor field (a two-tone checker motion
cue) so bullets and enemies have room to move and the rotation reads clearly,
bounded by a solid WALL ring, with a few SPARSE interior obstacle blocks (cover).
Unlike the dungeon maze, MOST directions from the centre are open floor — so a
fired bullet flies over the floor (the S3 rendered-floor projection test), and
the floor-vs-wall classifier reads FLOOR around an on-floor bullet at every
plane rotation angle.

The single `is_wall(tx,ty)` predicate is the SINGLE SOURCE OF TRUTH for BOTH the
rendered wall ART and the world-space collision LUT — "what you see is what
blocks you" by construction (kept from the m7_dungeon brick; the test mirrors
is_wall() in Python).

Outputs (committed; SAME filenames/symbols as the m7_dungeon brick so main.asm's
includes/labels are unchanged — only the CONTENT is the open arena):
    dungeon.png             authored source image (1024x1024) — reference only
    dungeon_map.bin         32768-byte interleaved Mode 7 VRAM blob (BANK1)
    dungeon_palette.inc     ca65 CGRAM data (dungeon_pal + DUNGEON_PAL_COUNT)
    dungeon_terrain.bin     16384-byte world terrain table, row-major [ty*128+tx]
                            (1 = solid/wall, 0 = floor/walkable) — collision LUT

Regenerate (from the materialized kit root, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/m7_oshoot/assets/make_arena.py
"""
from __future__ import annotations

import sys
import struct
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- colours (RGB) ---
FLOOR_A = (40, 44, 60)     # floor checker dark  -> reserved to CGRAM index 0
FLOOR_B = (70, 78, 104)    # floor checker light (motion cue)
WALL    = (180, 90, 60)    # solid wall (distinct warm colour)
WALL_LT = (220, 140, 100)  # wall edge highlight (relief under rotation)

# =============================================================================
# OPEN ARENA on the world tile grid (128x128 tiles = 1024x1024 px). The PLAYABLE
# arena is a square region [ARENA_LO, ARENA_HI) tiles, surrounded by a solid wall
# border. Inside the playable region the floor is OPEN, with a few SPARSE square
# OBSTACLE blocks (cover) the player + bullets collide against. Most of the arena
# is open floor so a fired bullet flies over floor in (almost) every direction.
# =============================================================================
ARENA_LO = 4               # inner wall border at tiles 0..ARENA_LO-1 (and HI..)
ARENA_HI = 124             # playable floor = tiles [ARENA_LO, ARENA_HI)
WALL_RING = 3              # thickness of the outer wall ring (tiles)

# A regular LATTICE of small obstacle PILLARS across the playable area: good
# run-and-gun COVER, and — because a pillar is never far from any point — a wall
# is always near a bullet's screen orbit, so the rendered-floor projection test
# (a wrongly-projected bullet swims onto a pillar) is robustly non-vacuous. The
# lattice leaves wide floor lanes between pillars (PILLAR_PITCH tiles apart) so
# the player + chasers move freely. The spawn cell (tile SPAWN_TX/TY = 64,64) and
# its immediate neighbourhood are kept CLEAR (no pillar within PILLAR_CLEAR tiles)
# so the player has open room at boot.
PILLAR_PITCH  = 6                # tiles between pillar centres (lattice spacing,
                                 #   64px — dense enough that a bullet's screen
                                 #   orbit crosses a pillar, so a wrongly-projected
                                 #   bullet reliably swims onto wall pixels)
PILLAR_HALF   = 1                # pillar half-extent (3x3-tile solid block)
PILLAR_PHASE  = 4                # lattice origin offset (so pillars miss the centre)
SPAWN_TX_C    = 64               # spawn cell (must match main.asm SPAWN_TX/TY)
SPAWN_TY_C    = 64
PILLAR_CLEAR  = 8                # tiles around spawn kept pillar-free (open start)


def _on_pillar(tx: int, ty: int) -> bool:
    """True iff (tx,ty) is inside a lattice pillar (and not in the spawn-clear
    zone). The lattice is at tiles == PILLAR_PHASE (mod PILLAR_PITCH), +/- HALF."""
    # keep the spawn neighbourhood clear
    if abs(tx - SPAWN_TX_C) <= PILLAR_CLEAR and abs(ty - SPAWN_TY_C) <= PILLAR_CLEAR:
        return False
    mx = (tx - PILLAR_PHASE) % PILLAR_PITCH
    my = (ty - PILLAR_PHASE) % PILLAR_PITCH
    near_x = mx <= PILLAR_HALF or mx >= PILLAR_PITCH - PILLAR_HALF
    near_y = my <= PILLAR_HALF or my >= PILLAR_PITCH - PILLAR_HALF
    return near_x and near_y


def is_wall(tx: int, ty: int) -> bool:
    """World-space wall predicate — single source of truth for art + collision.
    Solid outside the playable arena (the wall ring + the void beyond), and solid
    on any lattice pillar; open floor everywhere else."""
    if _on_pillar(tx, ty):
        return True
    # outer wall ring + everything outside the playable square
    if tx < ARENA_LO or ty < ARENA_LO or tx >= ARENA_HI or ty >= ARENA_HI:
        return True
    if tx < ARENA_LO + WALL_RING or ty < ARENA_LO + WALL_RING \
       or tx >= ARENA_HI - WALL_RING or ty >= ARENA_HI - WALL_RING:
        return True
    return False


def tile_color(tx: int, ty: int):
    if is_wall(tx, ty):
        return WALL_LT if not (tx & 1) or not (ty & 1) else WALL
    return FLOOR_B if ((tx >> 1) ^ (ty >> 1)) & 1 else FLOOR_A


def build_png(path: Path) -> None:
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    for ty in range(128):
        for tx in range(128):
            c = tile_color(tx, ty)
            for py in range(8):
                for pxi in range(8):
                    px[tx * 8 + pxi, ty * 8 + py] = c
    img.save(path)
    print(f"wrote {path}")


def build_terrain() -> bytes:
    """128x128 world terrain byte table, row-major [ty*128+tx], from the SAME
    is_wall() predicate that paints the art: 1 = solid/wall, 0 = floor/walkable."""
    out = bytearray(128 * 128)
    for ty in range(128):
        for tx in range(128):
            out[ty * 128 + tx] = 1 if is_wall(tx, ty) else 0
    return bytes(out)


def reserve_backdrop(tile_data: bytes, palette: bytes):
    """Force CGRAM index 0 to FLOOR_A (the Mode 7 backdrop slot), remapping any
    tile pixel that landed on index 0 to a freshly appended duplicate colour."""
    from toolchain.mode7_assets import rgb_to_bgr555
    want = rgb_to_bgr555(*FLOOR_A)
    idx0 = struct.unpack_from("<H", palette, 0)[0]
    if idx0 == want:
        return tile_data, palette
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    free = used
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free * 2, idx0)
    struct.pack_into("<H", pal, 0, want)
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from kit root with PYTHONPATH=.")

    png = HERE / "dungeon.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "dungeon_map.bin").write_bytes(blob)
    print(f"wrote dungeon_map.bin ({len(blob)} bytes)")

    terrain = build_terrain()
    assert len(terrain) == 16384, len(terrain)
    (HERE / "dungeon_terrain.bin").write_bytes(terrain)
    print(f"wrote dungeon_terrain.bin ({len(terrain)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; dungeon_palette.inc — GENERATED (make_arena.py). CGRAM idx0 = floor.",
        "dungeon_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; colour {i}")
    lines += ["", f"DUNGEON_PAL_COUNT = {used}", ""]
    (HERE / "dungeon_palette.inc").write_text("\n".join(lines))
    print(f"wrote dungeon_palette.inc ({used} colours)")

    # spawn cell centre is fixed by main.asm (SPAWN_TX/TY=14 -> px 116,116); it is
    # open floor by construction (well inside the playable arena, clear of all
    # OBSTACLES). Report it for cross-checks.
    print(f"arena playable tiles [{ARENA_LO},{ARENA_HI}); spawn tile (14,14) "
          f"px (116,116) floor={not is_wall(14, 14)}")


if __name__ == "__main__":
    main()
