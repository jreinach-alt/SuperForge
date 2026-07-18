#!/usr/bin/env python3
"""make_chamber_tables.py — the two per-scanline HDMA data tables for the
Mode 7 "barrel chamber" demo: the M7A barrel curve and the COLDATA vignette.

These encode FACTUAL HARDWARE CONFIGURATION (the register VALUES the effect
writes), not any game content:
  - chamber_barrel: a symmetric M7A ramp 1.0 -> 1.5 -> 1.0 ($0100->$0180->$0100),
    one u16 per FLOOR scanline (l0..l1-1), the "barrel" horizontal-scale bow.
  - chamber_vignette: the COLDATA ($2132) HDMA table, a brightness vignette
    ramping 0 -> 8 -> 0 ($E0..$E8..$E0) — a direct-HDMA [count,value]... $00
    encoding, brightest through the middle.

Outputs (committed):
    chamber_tables.inc     ca65 RODATA (chamber_barrel + chamber_vignette +
                           CHAMBER_VIGNETTE_LEN)

Regenerate:
    python3 templates/mode7_chamber/assets/make_chamber_tables.py
"""
from __future__ import annotations
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- floor band (must match the demo's sf_mode7_perspective l0/l1) ---
L0 = 32                     # horizon scanline (the HUD/floor split = the mode-split line)
L1 = 224                    # bottom scanline
FLOOR = L1 - L0            # 192 floor scanlines

M7A_FLAT = 0x0100          # 1.0 (edges)
M7A_PEAK = 0x0180          # 1.5 (mid bulge)


def barrel_table() -> list[int]:
    """A symmetric 1.0 -> 1.5 -> 1.0 M7A bow across the FLOOR band, as a RAISED
    COSINE (NOT a triangle). The previous triangle ramp (t = 1 - |i-mid|/mid)
    flipped slope instantly at the midpoint — a discontinuous first derivative
    that rendered as a visual "corner" at screen-centre. The raised cosine has
    ZERO slope at both ends AND at the peak, so the bow is smooth everywhere:
        t = 0.5 * (1 - cos(2*pi * i / FLOOR))   # 0 at ends, 1 at the centre
    """
    out = []
    for i in range(FLOOR):
        t = 0.5 * (1.0 - math.cos(2.0 * math.pi * i / FLOOR))
        val = round(M7A_FLAT + (M7A_PEAK - M7A_FLAT) * t)
        out.append(val & 0xFFFF)
    return out


# The captured COLDATA vignette table (IMG_2984 transcript) — [count, value]
# pairs, $00 terminator. Sums to 224 active scanlines. $Ex = set R+G+B to x.
VIGNETTE = [
    (0x24, 0xE0),   # 36 lines black (HUD band + top)
    (0x08, 0xE2),   # 8  @ 2
    (0x04, 0xE3),   # 4  @ 3
    (0x08, 0xE4),   # 8  @ 4
    (0x0A, 0xE5),   # 10 @ 5
    (0x0C, 0xE6),   # 12 @ 6
    (0x12, 0xE7),   # 18 @ 7
    (0x54, 0xE8),   # 84 @ 8  (the bright middle, ~25% gray)
    (0x0A, 0xE7),   # 10 @ 7
    (0x08, 0xE6),   # 8  @ 6
    (0x06, 0xE5),   # 6  @ 5
    (0x06, 0xE4),   # 6  @ 4
    (0x06, 0xE3),   # 6  @ 3
    (0x01, 0xE1),   # 1  @ 1  (fade to black at the bottom)
]


def main() -> None:
    barrel = barrel_table()
    lines = [
        "; chamber_tables.inc — GENERATED (make_chamber_tables.py).",
        "; M7A barrel curve + COLDATA vignette (factual hardware register values).",
        "",
        f"; M7A barrel: {FLOOR} floor scanlines (l0={L0}..l1={L1}), symmetric",
        f"; raised-cosine bow 1.0 (${M7A_FLAT:04X}) -> 1.5 (${M7A_PEAK:04X}) -> 1.0",
        "; (smooth peak — no mid-screen corner).",
        "chamber_barrel:",
    ]
    for r in range(0, len(barrel), 8):
        row = barrel[r:r + 8]
        lines.append("    .word " + ", ".join(f"${v:04X}" for v in row))
    lines += [
        "",
        "; COLDATA vignette HDMA table: direct [count,value]... $00 ($2132).",
        "; Intensity 0 -> 8 -> 0 ($E0..$E8..$E0), brightest middle 84 lines.",
        "chamber_vignette:",
    ]
    total = 0
    for cnt, val in VIGNETTE:
        lines.append(f"    .byte ${cnt:02X}, ${val:02X}")
        total += cnt
    lines.append("    .byte $00                ; terminator")
    nbytes = len(VIGNETTE) * 2 + 1
    lines += [
        "",
        f"CHAMBER_VIGNETTE_LEN = {nbytes}    ; bytes incl. terminator",
        f"; (vignette covers {total} active scanlines)",
        "",
    ]
    (HERE / "chamber_tables.inc").write_text("\n".join(lines))
    print(f"wrote chamber_tables.inc (barrel {len(barrel)} words, "
          f"vignette {nbytes} bytes, {total} scanlines)")


if __name__ == "__main__":
    main()
