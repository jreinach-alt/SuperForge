#!/usr/bin/env python3
"""gen_bend_luts.py — regenerate engine/hdma_bend_luts.inc.

Emits the two signed-byte curve LUTs the HDMA bend/tunnel builder
(hdma_build_hofs_curve, kit brick #1 sf_bend/sf_tunnel) reads per scanline.
Values come from toolchain/math_lut.py — the numeric single source of truth;
this script only owns the ca65 formatting (the gen_math_luts.py discipline):

  _hdma_curve_sine      256 x .byte — one full sine period in signed bytes
                        (-127..+127, raw two's-complement). DERIVED from the
                        kit's 8.8 sine SoT (generate_sin_lut) — NOT a new sine
                        — re-scaled to a byte. Periodic, so the
                        (scanline+phase)&$FF index rolls it into a tunnel.
  _hdma_curve_parabola  256 x .byte — a curved-horizon bowl symmetric about
                        the screen centre (scanline 112): 0 at centre, +127 at
                        the top & bottom edges; indices past 224 clamp.

The engine reads each as a signed byte (lda f:LABEL,x); its bit-7 test
recovers magnitude + sign, then scales |base| by amplitude / 128.

Run from a tree that has toolchain/ as a package (the materialized kit root,
or any checkout with toolchain/math_lut.py importable):

  PYTHONPATH=. python3 tools/gen_bend_luts.py

Writes engine/hdma_bend_luts.inc (deterministic output).
"""
from pathlib import Path

from toolchain.math_lut import (generate_bend_horizon_lut,
                                generate_bend_parabola_lut,
                                generate_bend_sine_lut)

HEADER = """\
; =============================================================================
; hdma_bend_luts.inc — curve LUTs for the HDMA bend / tunnel builder
; =============================================================================
; GENERATED FILE — do not hand-edit. Regenerate with:
;   PYTHONPATH=. python3 tools/gen_bend_luts.py
; (values from toolchain/math_lut.py; this file only freezes the bytes)
;
; Signed bytes, -127..+127, stored as raw two's-complement ($80..$FF =
; negative). hdma_build_hofs_curve reads one per scanline index and its bit-7
; test recovers magnitude + sign before scaling by amplitude / 128.
;   _hdma_curve_sine     one full sine period (DERIVED from the kit 8.8 sine
;                        SoT generate_sin_lut): [0]=0 [64]=+127 [128]=0
;                        [192]=-127. Rolls with phase -> tunnel.
;   _hdma_curve_parabola curved horizon symmetric about scanline 112: 0 at
;                        the centre, +127 at the top & bottom edges; indices
;                        past 224 clamp to the edge so a phase roll stays bounded.
;   _hdma_curve_horizon  v1.2-R V-axis (BGnVOFS) RECIPROCAL / 1-over-z
;                        perspective (SIGNED, -127..+127). Maps each ground
;                        scanline to a BOUNDED source row src = horizon +
;                        span*d/(d+tau), d = scanline - horizon; offset = src -
;                        scanline. Steepest AT the horizon (top) so rows bunch
;                        DRAMATICALLY there (>=4x vs foreground), saturating
;                        toward the bottom — a barrel / perspective horizon.
;                        src stays < 256 so the field never wraps into the sky
;                        (clean render). Replaces the old quadratic ramp (~1.3x).
;                        Compressed end at the TOP (correct direction).
; =============================================================================
"""


def bytes_(label, vals, per=8):
    out = [f"{label}:"]
    for i in range(0, len(vals), per):
        chunk = ", ".join(f"${v & 0xFF:02X}" for v in vals[i:i + per])
        out.append(f"    .byte {chunk}")
    return out


if __name__ == "__main__":
    lines = [HEADER]
    lines += bytes_("_hdma_curve_sine", generate_bend_sine_lut())
    lines.append("")
    lines += bytes_("_hdma_curve_parabola", generate_bend_parabola_lut())
    lines.append("")
    lines += bytes_("_hdma_curve_horizon", generate_bend_horizon_lut())
    lines.append("")
    target = (Path(__file__).resolve().parent.parent
              / "engine" / "hdma_bend_luts.inc")
    target.write_text("\n".join(lines))
    print(f"wrote {target}")
