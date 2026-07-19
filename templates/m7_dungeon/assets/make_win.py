#!/usr/bin/env python3
"""make_win.py — a 16x16 gold SPARKLE-STAR OBJ for the m7_dungeon goal win-card.

Wave-D dressing: reaching the GOAL cell draws a 3-star banner overlay (the win
card). This authors the star (an original kit UI element — no pack source), a 4-
point sparkle in bright GOLD so it reads as "you reached the exit" and, by being
warm-YELLOW (high green), never trips the enemy-warm colour band (which the win
sprite shares no screen region with anyway). 4bpp planar CHR; 16x16 = tiles
0/1/16/17 at the hardware OBJ layout (same 18-tile upload as the hero/enemy).

Emits win.inc (win_chr + WIN_CHR_BYTES + win_pal + WIN_PAL_COUNT + WIN_TILE).
Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_win.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 4-point sparkle star, authored programmatically. index: 0 transparent, 1 outline,
# 2 gold body, 3 bright highlight core.
def _star_rows():
    rows = []
    cx = cy = 7.5
    for y in range(16):
        row = []
        for x in range(16):
            dx, dy = abs(x - cx), abs(y - cy)
            core = dx + dy <= 1.5
            body = dx + dy <= 4.0
            arm = (dx <= 1.0 and dy <= 7.0) or (dy <= 1.0 and dx <= 7.0)
            if core:
                row.append("3")
            elif body or arm:
                row.append("2")
            elif (dx + dy <= 5.0) or ((dx <= 2.0 and dy <= 7.5) or (dy <= 2.0 and dx <= 7.5)):
                row.append("1")            # outline halo around body + arms
            else:
                row.append(".")
        rows.append("".join(row))
    return rows

STAR = _star_rows()


def encode_tile_4bpp(rows, ox, oy):
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            ch = rows[oy + y][ox + x]
            v = 0 if ch == "." else int(ch, 16)
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def bgr555(rgb):
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


PAL = [
    (0, 0, 0),          # 0 transparent
    (120, 80, 20),      # 1 outline (dark gold)
    (248, 200, 64),     # 2 body (gold)
    (255, 244, 176),    # 3 highlight (bright)
]


def _emit(label, blob):
    out = [f"{label}:"]
    for i in range(0, len(blob), 16):
        out.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    return out


def main():
    assert len(STAR) == 16 and all(len(r) == 16 for r in STAR)
    # Emit the 16x16 star as two TIGHT 64-byte row blobs (top tiles TL,TR and
    # bottom tiles BL,BR) instead of the 18-tile zero-padded layout — bank 0 is
    # nearly full, so this saves 448 bytes of ROM. main.asm DMAs them to the OBJ
    # tile pair and the +16 (lower) tile pair with two sf_load_obj_chr calls.
    top = encode_tile_4bpp(STAR, 0, 0) + encode_tile_4bpp(STAR, 8, 0)   # TL,TR
    bot = encode_tile_4bpp(STAR, 0, 8) + encode_tile_4bpp(STAR, 8, 8)   # BL,BR

    lines = [
        "; win.inc — GENERATED (make_win.py). 16x16 gold sparkle-star goal win-card OBJ.",
        "; original kit UI art (no pack source); CC0.",
        "WIN_TILE = 0",
    ]
    lines += _emit("win_chr_top", top)
    lines += _emit("win_chr_bot", bot)
    lines.append(f"WIN_CHR_ROW_BYTES = {len(top)}")
    lines.append("")
    lines.append("win_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("WIN_PAL_COUNT = 16")
    lines.append("")
    (HERE / "win.inc").write_text("\n".join(lines))
    print(f"wrote win.inc ({len(top) + len(bot)} CHR bytes, 2 row blobs)")


if __name__ == "__main__":
    main()
