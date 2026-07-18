#!/usr/bin/env python3
"""make_sprites.py — first-party battle-actor OBJ sprites for the boss template.

Hand-authored SNES pixel art (no external PNGs; deterministic, stdlib only),
encoded to SNES 4bpp planar CHR and laid out on the hardware's 16-tile VRAM
rows (an NxN sprite reads each lower tile row at +16 tile numbers — the same
blob contract as tools/png2snes.py sprite mode and make_vehicle.py).

ORIGINAL actors (clean-room — no commercial art):
    PLAYER     16x16, 2 frames — a small arrowhead "Skiff" gunship, top-down.
               frame 0 = neutral, frame 1 = hit/flash (white-shifted body).
               A 16x16 sprite is 2x2 tiles at {N, N+1, N+16, N+17}; frame 1
               sits one VRAM tile-column over at {N+2, N+3, N+18, N+19}.
    PROJECTILE 8x8, 1 frame — a glowing red enemy orb (the boss's bolt).
    SHOT       8x8, 1 frame — a cyan player bullet (the thing that damages the
               boss). Distinct color from the enemy orb so they never confuse.
    HP_LIT     8x8, 1 frame — a green HP-bar segment (boss HP HUD, filled).
    HP_DIM     8x8, 1 frame — a dark depleted HP-bar segment (HUD, empty).

CHR layout (32 bytes/tile, 16 tiles per VRAM row):
    VRAM row 0 (tiles 0..15):   player F0 top  (0,1), player F1 top  (2,3),
                                projectile (4), shot (5), hp_lit (6), hp_dim (7)
    VRAM row 1 (tiles 16..31):  player F0 bot (16,17), player F1 bot (18,19)
The blob is 2 VRAM rows = 32 tiles x 32 bytes = 1024 bytes.

Output (committed): sprites.inc — sprite_chr (1024-byte blob), sprite_chr_bytes,
sprite_pal (16 BGR555 words, OBJ palette), and base-tile equates relative to
the OBSEL name base. The boss template uploads at OBJ name base word $4000
(tile 1024 — Mode 7 owns VRAM $0000..$3FFF):
    sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes
    sf_load_obj_pal 0, sprite_pal
A frame's OAM tile = 1024 + SPR_<actor>.

Regenerate:  python3 templates/boss/assets/make_sprites.py
(no imports beyond the stdlib; deterministic output)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

# palette index -> RGB (index 0 = transparent, never rendered)
PALETTE = {
    0: (0, 0, 0),
    1: (20, 22, 34),        # hull outline / shadow
    2: (60, 120, 210),      # player hull, mid
    3: (120, 190, 255),     # player hull, lit
    4: (235, 245, 255),     # cockpit / flash white
    5: (255, 96, 32),       # enemy projectile core (molten orange-red)
    6: (150, 40, 16),       # enemy projectile rim (dark red)
    7: (120, 255, 230),     # player shot core (cyan)
    8: (32, 150, 150),      # player shot rim (teal)
    9: (80, 90, 120),       # hull engine glow / detail
    10: (64, 232, 96),      # HP-HUD lit segment (bright green)
    11: (40, 52, 64),       # HP-HUD dim/depleted segment (dark slate)
}

# 16x16 player "Skiff" gunship, top-down ('.' = transparent, digits = pal idx)
PLAYER_F0 = [
    ".......11.......",
    "......1441......",
    "......1441......",
    ".....144441.....",
    ".....143341.....",
    "....14333341....",
    "....13322331....",
    "...1332222331...",
    "...1322222231...",
    "..133222222331..",
    "..132299992231..",
    ".1132299992311..",
    ".1.1329999231.1.",
    "....11999911....",
    ".....1.11.1.....",
    "................",
]


def hit_frame(rows: list[str]) -> list[str]:
    """Hit/flash frame: push the body brighter (2->3, 3->4) so a single-frame
    swap reads as a damage flash. Outline + engine glow stay put."""
    table = str.maketrans({"2": "3", "3": "4"})
    return [r.translate(table) for r in rows]


# 8x8 enemy projectile — a glowing molten orb with a dark rim
PROJECTILE = [
    "..6666..",
    ".655556.",
    "6555556.",  # noqa: E501 (kept square below)
    "65555556",
    "65555556",
    "6555556.",
    ".655556.",
    "..6666..",
]
# normalize to exactly 8 wide
PROJECTILE = [(r + "........")[:8] for r in PROJECTILE]

# 8x8 player shot — a cyan bolt, distinct from the enemy orb
SHOT = [
    "...77...",
    "..7887..",
    ".788887.",
    ".788887.",
    ".788887.",
    ".788887.",
    "..7887..",
    "...77...",
]
SHOT = [(r + "........")[:8] for r in SHOT]

# 8x8 boss-HP-bar segment, LIT — a solid green pip (index A=10). The outline
# (index 1) keeps segments crisp against the boss BG.
HP_LIT = [
    "........",
    ".AAAAAA.",
    ".AAAAAA.",
    ".AAAAAA.",
    ".AAAAAA.",
    ".AAAAAA.",
    ".AAAAAA.",
    "........",
]
HP_LIT = [(r + "........")[:8] for r in HP_LIT]

# 8x8 boss-HP-bar segment, DIM — an empty/depleted pip: index-B ring, hollow.
HP_DIM = [
    "........",
    ".BBBBBB.",
    ".B....B.",
    ".B....B.",
    ".B....B.",
    ".B....B.",
    ".BBBBBB.",
    "........",
]
HP_DIM = [(r + "........")[:8] for r in HP_DIM]


def encode_tile_4bpp(rows: list[str], ox: int, oy: int) -> bytes:
    """One 8x8 tile at (ox, oy) of a character grid -> 32 bytes SNES 4bpp
    planar: rows 0-7 of [plane0, plane1], then rows 0-7 of [plane2, plane3].
    Index chars are HEX (0-9, A-F) so palette entries 10-15 are addressable.
    NEVER masks the index — asserts the 0..15 range (the parent repo's silent
    `& 0x03` quantization incident is the canonical scar)."""
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            ch = rows[oy + y][ox + x]
            v = 0 if ch == "." else int(ch, 16)
            assert 0 <= v <= 15, f"palette index {v} out of 4bpp range"
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def bgr555(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def main() -> None:
    for art in (PLAYER_F0,):
        assert len(art) == 16 and all(len(r) == 16 for r in art), "player art 16x16"
    for art in (PROJECTILE, SHOT, HP_LIT, HP_DIM):
        assert len(art) == 8 and all(len(r) == 8 for r in art), "8x8 art"

    player_f0 = PLAYER_F0
    player_f1 = hit_frame(PLAYER_F0)

    # 32-tile blob (2 VRAM rows x 16 tiles x 32 bytes). A 16x16 sprite's four
    # 8x8 tiles live at {N, N+1, N+16, N+17}: top row in VRAM row 0, bottom
    # row in VRAM row 1 (+16 tile numbers — the hardware layout).
    tiles = [bytes(32)] * 32
    for base, art in ((0, player_f0), (2, player_f1)):   # F0 at tile 0, F1 at 2
        for ty in range(2):                              # 16x16 = 2x2 subtiles
            for tx in range(2):
                tiles[base + ty * 16 + tx] = encode_tile_4bpp(art, tx * 8, ty * 8)
    tiles[4] = encode_tile_4bpp(PROJECTILE, 0, 0)        # enemy orb (8x8)
    tiles[5] = encode_tile_4bpp(SHOT, 0, 0)              # player shot (8x8)
    tiles[6] = encode_tile_4bpp(HP_LIT, 0, 0)            # HP-HUD lit pip (8x8)
    tiles[7] = encode_tile_4bpp(HP_DIM, 0, 0)            # HP-HUD dim pip (8x8)
    blob = b"".join(tiles)
    assert len(blob) == 1024, len(blob)

    lines = [
        "; =============================================================================",
        "; sprites.inc — boss-arena battle-actor OBJ CHR + palette (GENERATED)",
        "; =============================================================================",
        "; Regenerate: python3 templates/boss/assets/make_sprites.py",
        "; Actors: PLAYER 16x16 (2 frames: neutral + hit), PROJECTILE 8x8 (enemy",
        "; orb), SHOT 8x8 (player bullet). 2 VRAM tile rows, 1024 bytes.",
        "; LOAD CONTRACT: upload sprite_chr at a 16-aligned OBJ tile index. The",
        "; boss template uses the OBJ name base = VRAM word $4000 = tile 1024",
        "; (Mode 7 owns VRAM $0000..$3FFF):",
        ";     sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes",
        ";     sf_load_obj_pal 0, sprite_pal",
        "; A frame's OAM tile = 1024 + SPR_<actor>. The 16x16 player reads its",
        "; lower tile row at +16 tile numbers; use OBSEL size pair 3 (16x16",
        "; small / 32x32 large) and set the 16x16-small size flag for the player",
        "; and the 8x8 entries (a 16x16-small slot renders 8x8 art with the",
        "; other 3 subtiles transparent).",
        "; =============================================================================",
        "",
        "SPR_PLAYER_T0   = $00      ; player frame 0 (neutral); 16x16 at {0,1,16,17}",
        "SPR_PLAYER_T1   = $02      ; player frame 1 (hit/flash); 16x16 at {2,3,18,19}",
        "SPR_PROJECTILE  = $04      ; enemy projectile orb (8x8)",
        "SPR_SHOT        = $05      ; player shot / damages the boss (8x8)",
        "SPR_HP_LIT      = $06      ; boss HP-bar segment, filled (8x8, green)",
        "SPR_HP_DIM      = $07      ; boss HP-bar segment, depleted (8x8, slate)",
        f"sprite_chr_bytes = {len(blob)}",
        "SPRITE_PAL_COUNT = 16",
        "",
        "sprite_chr:",
    ]
    for off in range(0, len(blob), 16):
        chunk = ", ".join(f"${b:02X}" for b in blob[off:off + 16])
        lines.append(f"    .byte {chunk}")
    lines += ["", "sprite_pal:"]
    for i in range(16):
        word = bgr555(PALETTE[i]) if i in PALETTE else 0
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines.append("")
    (HERE / "sprites.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'sprites.inc'} ({len(blob)} CHR bytes)")


if __name__ == "__main__":
    main()
