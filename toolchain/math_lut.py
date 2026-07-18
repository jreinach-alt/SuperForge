"""
Math LUT generators for SuperForge Phase 4G builtins.

Generates lookup tables for sin/cos (shared), sqrt, and atan2.
Output format: ca65 .word/.byte directives for inclusion in RODATA.

Turn-based angle conventions (the kit's sf_math convention):
  - Angles: 0.0 to 1.0 = full circle (0° to 360°)
  - sin() is inverted vs mathematical convention: sin(0.25) = -1.0
  - cos(x) = sin(x + 0.25) — quarter-turn offset, shares same LUT
  - All values in 8.8 signed fixed-point format
"""

from __future__ import annotations

import math


def generate_sin_lut() -> list[int]:
    """Generate 256-entry sin LUT in 8.8 signed format (negated-sine turn convention).

    Index: low byte of 8.8 angle (0-255 = 0.0-0.996 turns).
    Value: 8.8 signed (-1.0 to +1.0).
    cos(x) = sin_lut[(index + 64) & 0xFF].
    """
    entries = []
    for i in range(256):
        angle_turns = i / 256.0
        # Negated-sine turn convention: sin(x) = -math.sin(2π * x)
        value = -math.sin(2 * math.pi * angle_turns)
        fixed = int(round(value * 256))
        fixed = max(-32768, min(32767, fixed))
        entries.append(fixed & 0xFFFF)
    return entries


def generate_sqrt_lut() -> list[int]:
    """Generate 256-entry sqrt LUT for integer values 0-255.

    Index: integer part of 8.8 input (high byte).
    Value: sqrt(index) in 8.8 format.

    The engine wrapper extracts the integer part, looks up sqrt(n) and
    sqrt(n+1), then interpolates using the fractional part.
    """
    entries = []
    for i in range(256):
        value = math.sqrt(i)
        fixed = int(round(value * 256))
        entries.append(min(fixed, 0x7FFF))
    return entries


def generate_atan_lut() -> list[int]:
    """Generate 65-entry arctangent LUT for octant decomposition.

    Index i represents ratio i/64 (0.0 to 1.0).
    Value: angle in 256ths of a circle (0-32), stored as 8-bit byte.

    The atan2 wrapper determines the octant, computes min/max ratio,
    looks up the base angle, and maps to the correct full-circle angle.
    """
    entries = []
    for i in range(65):
        ratio = i / 64.0
        angle_rad = math.atan(ratio)
        angle_256ths = round(angle_rad / (2 * math.pi) * 256)
        entries.append(min(angle_256ths, 32))
    return entries


# --- HDMA bend / tunnel curve LUTs (kit brick #1, sf_bend / sf_tunnel) --------
#
# The curve-LUT-driven per-scanline BGnHOFS builder (hdma_build_hofs_curve)
# reads a SIGNED-BYTE base offset per scanline index: -127..+127, stored as a
# raw two's-complement byte (the engine's bit-7 test recovers magnitude+sign).
# The builder scales |base| by amplitude (0-15) via the HW multiplier / 128.
# Two v1 curves, both 256 entries so the (scanline + phase) & $FF index never
# leaves the table.


def generate_bend_sine_lut() -> list[int]:
    """SINE curve for sf_tunnel — 256 signed bytes (-127..+127), one full
    period. DERIVED from the kit's 8.8 sine source-of-truth (generate_sin_lut,
    which stores -sin); this is NOT a new sine — it re-scales the existing kit
    sine to a signed byte. Periodic, so the (scanline+phase) index rolls it
    into a forward tunnel. Key points: [0]=0, [64]=+127, [128]=0, [192]=-127.
    Returned as raw two's-complement bytes (0..255)."""
    sin88 = generate_sin_lut()                 # 8.8 of -sin(2*pi*i/256)
    out = []
    for v in sin88:
        signed = v - 0x10000 if v >= 0x8000 else v   # 8.8 signed
        value = -signed                              # un-negate -> +sin in 8.8
        b = int(round(value / 256.0 * 127))          # 8.8 (~-1..1) -> -127..127
        b = max(-127, min(127, b))
        out.append(b & 0xFF)
    return out


def generate_bend_parabola_lut(centre: int = 112, last: int = 224,
                               peak: int = 127) -> list[int]:
    """PARABOLA curve for a STATIC curved horizon — 256 signed bytes
    (0..+127), symmetric about the screen centre scanline. offset(s) =
    round(peak * (s - centre)^2 / centre^2), s clamped to 0..last (the active
    scanline range); 0 at the centre, +peak at the top & bottom edges.
    Indices past `last` clamp to the edge value so a stray phase roll stays
    bounded. Returned as raw bytes (all non-negative here, 0..127)."""
    maxd2 = max(centre * centre, (last - centre) ** 2)
    out = []
    for i in range(256):
        s = i if i <= last else last
        d = s - centre
        b = round(peak * (d * d) / maxd2)
        b = max(0, min(127, b))
        out.append(b & 0xFF)
    return out


def generate_bend_horizon_lut(horizon: int = 48, span: float = 180.0,
                              tau: float = 14.0, peak: int = 127) -> list[int]:
    """HORIZON perspective curve for the V-axis barrel/horizon squash — 256
    SIGNED bytes (-peak..+peak), a RECIPROCAL / 1-over-z perspective compression
    (NOT a quadratic ramp, which only reaches ~1.3x; NOT the symmetric parabola
    bow). This realizes the rail-shooter projection y = horizon + k/z by mapping
    each ground scanline to a BOUNDED source row, so the field never wraps the
    tilemap into the foreground (a clean render).

    A receding ground plane's source row advances HYPERBOLICALLY with distance
    below the horizon — fast right at the horizon, SATURATING to a fixed deepest
    row toward the viewer:

        src(s)    = horizon + span * d / (d + tau),   d = s - horizon  (s > horizon)
        offset(s) = round(src(s) - s)                 (0 for s <= horizon: sky)

    The engine adds offset(s) to BGnVOFS, so screen scanline s shows source row
    src(s). src'(s) = span*tau/(d+tau)^2 is LARGEST at the horizon (d=0): rows
    there bunch DRAMATICALLY (a few px apart = compressed), then spread toward the
    foreground where src saturates near horizon+span. offset starts POSITIVE just
    below the horizon (src races ahead of s) and goes NEGATIVE in the foreground
    (src lags s as it saturates) — hence the signed LUT. Because src stays bounded
    by horizon+span (< 256 for the defaults), the source never wraps the 256px
    tilemap back into the sky region: NO duplicate horizon / wrap-gap artifacts.

    With the V demo's amp 128 (unity passthrough, |off|*128/128 = |off|) the
    measured on-screen band-spacing ratio is >=4x (horizon vs foreground), the
    a strong barrel / perspective horizon look — vs the old quadratic's ~1.3x.

    `horizon` ANCHORS the perspective at the horizon-line scanline (default 48 =
    tilemap row 6, the demo's horizon line): offset is 0 (flat) above it so the
    sky region stays undistorted; the receding ground starts exactly there.
    `span` is the source-row depth swept by the ground (keep horizon+span < 256
    to avoid wrap); `tau` is the perspective hardness (smaller bunches harder at
    the horizon).

    Direction: the COMPRESSED end is at the TOP (the distant horizon, where src'
    is steepest), expanding toward the bottom (nearest viewer) — the correct
    horizon orientation. Returned as raw two's-complement bytes (0..255; the
    engine's bit-7 test recovers magnitude + sign). |offset| <= peak <= 127, so
    |off|*amp/128 stays within a byte for amp <= 174 (and the demo uses 128)."""
    out = []
    for i in range(256):
        s = i
        if s <= horizon:
            off = 0
        else:
            d = s - horizon
            src = horizon + span * (d / (d + tau))
            off = round(src - s)
        off = max(-peak, min(peak, off))
        out.append(off & 0xFF)
    return out


def format_sin_lut_asm() -> str:
    """Format sin LUT as ca65 .word directives."""
    entries = generate_sin_lut()
    lines = [
        "; sin LUT (negated-sine turn convention) — 256 entries × 2 bytes = 512 bytes",
        "; Index: low byte of 8.8 angle (0-255 = 0.0-0.996 turns)",
        "; Value: 8.8 signed (-1.0 to +1.0)",
        "; cos(x) = sin_lut[(index + 64) & 0xFF]",
        "; Generated by toolchain/math_lut.py",
        "math_sin_lut:",
    ]
    for i in range(0, 256, 8):
        chunk = entries[i:i + 8]
        hex_words = ", ".join(f"${v:04X}" for v in chunk)
        lines.append(f"    .word {hex_words}")
    return "\n".join(lines)


def format_sqrt_lut_asm() -> str:
    """Format sqrt LUT as ca65 .word directives."""
    entries = generate_sqrt_lut()
    lines = [
        "; sqrt LUT — 256 entries × 2 bytes = 512 bytes",
        "; Index: integer part of 8.8 input (high byte, 0-255)",
        "; Value: sqrt(index) in 8.8 format",
        "; Generated by toolchain/math_lut.py",
        "math_sqrt_lut:",
    ]
    for i in range(0, 256, 8):
        chunk = entries[i:i + 8]
        hex_words = ", ".join(f"${v:04X}" for v in chunk)
        lines.append(f"    .word {hex_words}")
    return "\n".join(lines)


def format_atan_lut_asm() -> str:
    """Format atan LUT as ca65 .byte directives."""
    entries = generate_atan_lut()
    lines = [
        "; atan LUT — 65 entries × 1 byte = 65 bytes",
        "; Index: ratio * 64 (0-64, where ratio = min/max of |dx|,|dy|)",
        "; Value: angle in 256ths of a circle (0-32)",
        "; Generated by toolchain/math_lut.py",
        "math_atan_lut:",
    ]
    for i in range(0, 65, 16):
        chunk = entries[i:i + 16]
        hex_bytes = ", ".join(f"${v:02X}" for v in chunk)
        lines.append(f"    .byte {hex_bytes}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Verification: print key values
    sin_lut = generate_sin_lut()
    print("sin LUT key values:")
    print(f"  sin(0.000) = ${sin_lut[0]:04X} (expect $0000)")
    print(f"  sin(0.250) = ${sin_lut[64]:04X} (expect $FF00 = -1.0)")
    print(f"  sin(0.500) = ${sin_lut[128]:04X} (expect $0000)")
    print(f"  sin(0.750) = ${sin_lut[192]:04X} (expect $0100 = +1.0)")

    sqrt_lut = generate_sqrt_lut()
    print("\nsqrt LUT key values:")
    print(f"  sqrt(0)   = ${sqrt_lut[0]:04X} (expect $0000)")
    print(f"  sqrt(1)   = ${sqrt_lut[1]:04X} (expect $0100 = 1.0)")
    print(f"  sqrt(4)   = ${sqrt_lut[4]:04X} (expect $0200 = 2.0)")
    print(f"  sqrt(9)   = ${sqrt_lut[9]:04X} (expect $0300 = 3.0)")
    print(f"  sqrt(100) = ${sqrt_lut[100]:04X} (expect $0A00 = 10.0)")

    atan_lut = generate_atan_lut()
    print("\natan LUT key values:")
    print(f"  atan(0/64 = 0.0)  = {atan_lut[0]} (expect 0)")
    print(f"  atan(64/64 = 1.0) = {atan_lut[64]} (expect 32)")
    print(f"  atan(32/64 = 0.5) = {atan_lut[32]} (expect ~21)")
