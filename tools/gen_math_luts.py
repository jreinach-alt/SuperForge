#!/usr/bin/env python3
"""gen_math_luts.py — regenerate lib/macros/sf_math_luts.inc.

Emits the three lookup tables the sf_math group's subroutines consume
(values come from toolchain/math_lut.py — the numeric single source of
truth; this script only owns the ca65 formatting):

  math_sin_lut   256 x .word — 8.8 signed. Index = angle low byte
                 (0..255 = one full turn). Stores the NEGATED sine, so
                 index 64 (a quarter turn) reads -$0100; index 192 reads
                 +$0100. Cosine = the negated value at (index+64)&255.
  math_sqrt_lut  256 x .word — sqrt(index) in 8.8. Index = the integer
                 part (high byte) of the 8.8 input; the runtime
                 interpolates between adjacent entries with the fraction.
  math_atan_lut  65 x .byte — atan(index/64) in 256ths of a turn (0..32).
                 Consumed by the octant-decomposition arctangent.

Run from a tree that has toolchain/ as a package (the materialized kit
root, or any checkout with toolchain/math_lut.py importable):

  PYTHONPATH=. python3 tools/gen_math_luts.py

Writes lib/macros/sf_math_luts.inc (deterministic output).
"""
from pathlib import Path

from toolchain.math_lut import (generate_atan_lut, generate_sin_lut,
                                generate_sqrt_lut)

HEADER = """\
; =============================================================================
; sf_math_luts.inc — generated lookup tables for the sf_math group
; =============================================================================
; GENERATED FILE — do not hand-edit. Regenerate with:
;   PYTHONPATH=. python3 tools/gen_math_luts.py
; (values from toolchain/math_lut.py; this file only freezes the bytes)
;
; Angle convention everywhere in the kit: 0..255 = one full turn.
; math_sin_lut stores the NEGATED sine in 8.8 signed, so:
;   math_sin_lut[0]   = $0000          math_sin_lut[64]  = $FF00 (-1.0)
;   math_sin_lut[128] = $0000          math_sin_lut[192] = $0100 (+1.0)
; cosine = -math_sin_lut[(i + 64) & 255]  (the runtime does the negate).
; math_sqrt_lut[n] = sqrt(n) in 8.8 (n = integer part of the 8.8 input).
; math_atan_lut[r] = atan(r/64) in 256ths of a turn (0..32), for the
; octant-decomposition arctangent.
; =============================================================================
"""


def words(label, vals, per=8):
    out = [f"{label}:"]
    for i in range(0, len(vals), per):
        chunk = ", ".join(f"${v & 0xFFFF:04X}" for v in vals[i:i + per])
        out.append(f"    .word {chunk}")
    return out


def bytes_(label, vals, per=16):
    out = [f"{label}:"]
    for i in range(0, len(vals), per):
        chunk = ", ".join(f"${v & 0xFF:02X}" for v in vals[i:i + per])
        out.append(f"    .byte {chunk}")
    return out


if __name__ == "__main__":
    lines = [HEADER]
    lines += words("math_sin_lut", generate_sin_lut())
    lines.append("")
    lines += words("math_sqrt_lut", generate_sqrt_lut())
    lines.append("")
    lines += bytes_("math_atan_lut", generate_atan_lut())
    lines.append("")
    target = Path(__file__).resolve().parent.parent / "lib" / "macros" / "sf_math_luts.inc"
    target.write_text("\n".join(lines))
    print(f"wrote {target}")
