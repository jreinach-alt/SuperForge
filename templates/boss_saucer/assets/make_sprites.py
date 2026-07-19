#!/usr/bin/env python3
"""make_sprites.py — first-party battle-actor OBJ sprites for boss_saucer.

Hand-authored SNES pixel art (no external PNGs; deterministic, stdlib only),
encoded to SNES 4bpp planar CHR and laid out on the hardware's 16-tile VRAM
rows (an NxN sprite reads each lower tile row at +16 tile numbers — the same
blob contract as the boss template's make_sprites.py / tools/png2snes.py
sprite mode).

This is the boss_saucer variant of the boss template's actor set. The shared
battle code links unchanged, so every actor the original defined is preserved
at the SAME base-tile equate; the only ADDITION is SPR_BEAM, the saucer's
signature attack — a glowing vertical beam SEGMENT that stacks into a
continuous descending column.

ORIGINAL actors (clean-room — no commercial art):
    PLAYER     16x16, 2 frames — a small arrowhead "Skiff" gunship, top-down.
               frame 0 = neutral, frame 1 = hit/flash (white-shifted body).
               A 16x16 sprite is 2x2 tiles at {N, N+1, N+16, N+17}; frame 1
               sits one VRAM tile-column over at {N+2, N+3, N+18, N+19}.
    PROJECTILE 8x8, 1 frame — a glowing red orb. KEPT from the boss template
               so the shared battle code links unchanged; the saucer attacks
               with the BEAM rather than orbs, so this is unused-but-harmless
               (no equate removed, no VRAM tile freed — zero link churn).
    SHOT       8x8, 1 frame — a cyan player bullet (the thing that damages the
               boss). Distinct color from the enemy orb so they never confuse.
    HP_LIT     8x8, 1 frame — a green HP-bar segment (boss HP HUD, filled).
    HP_DIM     8x8, 1 frame — a dark depleted HP-bar segment (HUD, empty).
    BEAM       8x8, 1 frame — NEW. A bright vertical energy-beam SEGMENT: a
               white-hot core column with colored edges, designed to STACK
               vertically (draw a column of these tiles) into a continuous
               descending beam from the saucer's underside emitter. Edges are
               left/right (not top/bottom) so adjacent stacked segments butt
               seamlessly with no horizontal seam between them.

CHR layout (32 bytes/tile, 16 tiles per VRAM row):
    VRAM row 0 (tiles 0..15):   player F0 top  (0,1), player F1 top  (2,3),
                                projectile (4), shot (5), hp_lit (6),
                                hp_dim (7), beam (8)
    VRAM row 1 (tiles 16..31):  player F0 bot (16,17), player F1 bot (18,19)
    VRAM rows 2-3 (tiles 32..): the 8x8 text-glyph font (result/title cards)
The blob is 4 VRAM rows = 64 tiles x 32 bytes = 2048 bytes.

Output (committed): sprites.inc — sprite_chr (1024-byte blob), sprite_chr_bytes,
sprite_pal (16 BGR555 words, OBJ palette), and base-tile equates relative to
the OBSEL name base. The template uploads at OBJ name base word $4000
(tile 1024 — Mode 7 owns VRAM $0000..$3FFF):
    sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes
    sf_load_obj_pal 0, sprite_pal
A frame's OAM tile = 1024 + SPR_<actor>.

Regenerate:  python3 templates/boss_saucer/assets/make_sprites.py
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
    12: (255, 255, 248),    # beam core (white-hot)
    13: (140, 230, 255),    # beam edge (cyan glow)
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
    "6555556.",
    "65555556",
    "65555556",
    "6555556.",
    ".655556.",
    "..6666..",
]
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

# 8x8 boss-HP-bar segment, LIT — a solid green pip (index A=10).
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

# 8x8 beam SEGMENT — a vertical white-hot core (index C=12) flanked by a cyan
# glow (index D=13). Filled top-to-bottom with NO horizontal margin so a
# column of these stacks into a seamless continuous beam; the glow is on the
# LEFT/RIGHT edges only, never the top/bottom, so vertically-adjacent segments
# butt cleanly with no seam between them.
BEAM = [
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
    ".DCCCCD.",
]
BEAM = [(r + "........")[:8] for r in BEAM]

# 8x8 card-banner backing — a solid dark tile (index 1). A row of these draws
# behind the result/title text so the bright glyphs read at HIGH contrast over
# ANY scene (the near-apex saucer hull is bright; INIDISP dims text + hull
# equally, so white-on-hull needs its own dark bed).
CARDBG = ["11111111"] * 8

# 8x8 thruster-exhaust flames (blue index 3 + white-hot core index 4), a short
# and a tall frame. Drawn just below the player during the fight and alternated
# every few frames so the engine pulses — the ship reads as powered, not static.
EXHAUST_LO = [
    "..3443..",
    "..3443..",
    "...34...",
    "........",
    "........",
    "........",
    "........",
    "........",
]
EXHAUST_HI = [
    "..3443..",
    "..3443..",
    "..3443..",
    "...34...",
    "...3....",
    "........",
    "........",
    "........",
]

# --- 8x8 text-glyph font (the result/title cards) -----------------------------
# A minimal 5x7 uppercase font in an 8x8 cell (glyph pixels = index 4, the bright
# near-white already in the palette; pixels sit in cols 0-4 so a 6px pen advance
# leaves a clean 1px inter-letter gap). Only the letters the cards spell + two
# strafe arrows are cut, laid out in GLYPH_ORDER at consecutive tiles from
# FONT_BASE; main.asm spells words as runs of these SPR_G_* tiles. Drawing them
# as 8x8 SMALL sprites is exactly why the OBJ size pair is 0 (8x8 / 16x16).
GLYPH_ROWS = {
    "A": [".444.", "4...4", "4...4", "44444", "4...4", "4...4", "4...4"],
    "C": [".4444", "4....", "4....", "4....", "4....", "4....", ".4444"],
    "D": ["4444.", "4...4", "4...4", "4...4", "4...4", "4...4", "4444."],
    "E": ["44444", "4....", "4....", "4444.", "4....", "4....", "44444"],
    "F": ["44444", "4....", "4....", "4444.", "4....", "4....", "4...."],
    "I": ["44444", "..4..", "..4..", "..4..", "..4..", "..4..", "44444"],
    "M": ["4...4", "44.44", "4.4.4", "4.4.4", "4...4", "4...4", "4...4"],
    "N": ["4...4", "44..4", "4.4.4", "4.4.4", "4..44", "4...4", "4...4"],
    "O": [".444.", "4...4", "4...4", "4...4", "4...4", "4...4", ".444."],
    "R": ["4444.", "4...4", "4...4", "4444.", "4.4..", "4..4.", "4...4"],
    "S": [".4444", "4....", "4....", ".444.", "....4", "....4", "4444."],
    "T": ["44444", "..4..", "..4..", "..4..", "..4..", "..4..", "..4.."],
    "U": ["4...4", "4...4", "4...4", "4...4", "4...4", "4...4", ".444."],
    "V": ["4...4", "4...4", "4...4", "4...4", "4...4", ".4.4.", "..4.."],
    "W": ["4...4", "4...4", "4...4", "4.4.4", "4.4.4", "44.44", "4...4"],
    "Y": ["4...4", "4...4", ".4.4.", "..4..", "..4..", "..4..", "..4.."],
    "LARR": ["...4.", "..44.", ".444.", "4444.", ".444.", "..44.", "...4."],
    "RARR": [".4...", ".44..", ".444.", ".4444", ".444.", ".44..", ".4..."],
}
# fixed tile order (SPR_G_<name> = FONT_BASE + index); keep stable for the ROM
GLYPH_ORDER = ["A", "C", "D", "E", "F", "I", "M", "N", "O", "R",
               "S", "T", "U", "V", "W", "Y", "LARR", "RARR"]
FONT_BASE = 32                  # glyph tiles start on VRAM row 2 (clear of actors)


def glyph_tile(name: str) -> bytes:
    """Encode one 8x8 font glyph (5x7 art, index 4) padded into an 8x8 cell."""
    rows = [(r + "........")[:8] for r in GLYPH_ROWS[name]]
    while len(rows) < 8:
        rows.append("........")
    return encode_tile_4bpp(rows, 0, 0)


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
    for art in (PROJECTILE, SHOT, HP_LIT, HP_DIM, BEAM):
        assert len(art) == 8 and all(len(r) == 8 for r in art), "8x8 art"

    player_f0 = PLAYER_F0
    player_f1 = hit_frame(PLAYER_F0)

    # 64-tile blob (4 VRAM rows x 16 tiles x 32 bytes). A 16x16 sprite's four
    # 8x8 tiles live at {N, N+1, N+16, N+17}: top row in VRAM row 0, bottom
    # row in VRAM row 1 (+16 tile numbers — the hardware layout). Rows 0-1 hold
    # the battle actors; rows 2-3 (tiles 32+) hold the 8x8 text-glyph font.
    tiles = [bytes(32)] * 64
    for base, art in ((0, player_f0), (2, player_f1)):   # F0 at tile 0, F1 at 2
        for ty in range(2):                              # 16x16 = 2x2 subtiles
            for tx in range(2):
                tiles[base + ty * 16 + tx] = encode_tile_4bpp(art, tx * 8, ty * 8)
    tiles[4] = encode_tile_4bpp(PROJECTILE, 0, 0)        # enemy orb (8x8, kept)
    tiles[5] = encode_tile_4bpp(SHOT, 0, 0)              # player shot (8x8)
    tiles[6] = encode_tile_4bpp(HP_LIT, 0, 0)            # HP-HUD lit pip (8x8)
    tiles[7] = encode_tile_4bpp(HP_DIM, 0, 0)            # HP-HUD dim pip (8x8)
    tiles[8] = encode_tile_4bpp(BEAM, 0, 0)              # beam segment (8x8)
    tiles[9] = encode_tile_4bpp(CARDBG, 0, 0)            # card-banner backing (8x8)
    tiles[10] = encode_tile_4bpp(EXHAUST_LO, 0, 0)       # thruster flame, short (8x8)
    tiles[11] = encode_tile_4bpp(EXHAUST_HI, 0, 0)       # thruster flame, tall (8x8)
    for i, name in enumerate(GLYPH_ORDER):               # text font (8x8, tiles 32+)
        tiles[FONT_BASE + i] = glyph_tile(name)
    blob = b"".join(tiles)
    assert len(blob) == 2048, len(blob)

    lines = [
        "; =============================================================================",
        "; sprites.inc — boss_saucer battle-actor OBJ CHR + palette (GENERATED)",
        "; =============================================================================",
        "; Regenerate: python3 templates/boss_saucer/assets/make_sprites.py",
        "; Actors: PLAYER 16x16 (2 frames: neutral + hit), PROJECTILE 8x8 (kept",
        "; from the boss template, unused by the saucer), SHOT 8x8 (player",
        "; bullet), HP_LIT/HP_DIM 8x8 (HUD pips), BEAM 8x8 (saucer's stacking",
        "; vertical beam segment), a card-banner tile + thruster flames, and an",
        "; 8x8 text-glyph font (tiles 32+, the result/title cards). 4 VRAM tile",
        "; rows, 2048 bytes.",
        "; LOAD CONTRACT: upload sprite_chr at a 16-aligned OBJ tile index. The",
        "; template uses the OBJ name base = VRAM word $4000 = tile 1024",
        "; (Mode 7 owns VRAM $0000..$3FFF):",
        ";     sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes",
        ";     sf_load_obj_pal 0, sprite_pal",
        "; A frame's OAM tile = 1024 + SPR_<actor>. Use OBSEL size pair 0 (8x8",
        "; small / 16x16 large): the player draws as a 16x16 LARGE sprite (its",
        "; four 8x8 tiles at {N,N+1,N+16,N+17}, the lower row at +16 tile numbers",
        "; = the hardware layout); every 8x8 actor draws as a SMALL sprite (one",
        "; tile, no neighbor bleed). Stack a column of SPR_BEAM 8x8 slots (8px",
        "; vertical pitch) to draw the continuous descending beam.",
        "; =============================================================================",
        "",
        "SPR_PLAYER_T0   = $00      ; player frame 0 (neutral); 16x16 at {0,1,16,17}",
        "SPR_PLAYER_T1   = $02      ; player frame 1 (hit/flash); 16x16 at {2,3,18,19}",
        "SPR_PROJECTILE  = $04      ; enemy orb (8x8); kept from boss tmpl, unused",
        "SPR_SHOT        = $05      ; player shot / damages the boss (8x8)",
        "SPR_HP_LIT      = $06      ; boss HP-bar segment, filled (8x8, green)",
        "SPR_HP_DIM      = $07      ; boss HP-bar segment, depleted (8x8, slate)",
        "SPR_BEAM        = $08      ; saucer beam segment (8x8); stack vertically",
        "SPR_CARDBG      = $09      ; solid dark banner tile behind result/title text",
        "SPR_EXH_LO      = $0A      ; thruster flame, short frame (8x8)",
        "SPR_EXH_HI      = $0B      ; thruster flame, tall frame (8x8)",
        "",
        "; text-glyph font (8x8, tiles 32+): result/title cards spell words as",
        "; runs of these. main.asm draws each as an 8x8 SMALL sprite.",
    ]
    for i, name in enumerate(GLYPH_ORDER):
        lines.append(f"SPR_G_{name:<8} = ${FONT_BASE + i:02X}"
                     f"      ; glyph '{name}' (8x8)")
    lines += [
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
