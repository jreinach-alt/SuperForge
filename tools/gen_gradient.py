#!/usr/bin/env python3
"""gen_gradient.py — deterministic microzero COLDATA tables (whole frame).

Emits gradient_tabs.bin (byte-identical on re-run, pure integer math):
  3 x TOTAL_LINES COLDATA bytes — the R plane's table, then G's, then B's,
  one byte per scanline of the WHOLE frame. Each byte is plane_select |
  intensity: R = $20|v, G = $40|v, B = $80|v, v in 0..31.

Three zones, all static (fixed camera height, fixed geometry):

  sky   lines 0..HUD_LINES-1     deep blue at the top ramping to a warm
                                 horizon. This is the reference sky treatment
                                 (its sky_gradient_gen was run with sky
                                 (2,8,28) -> horizon (31,16,4)); colour math
                                 adds it to sky_band's dark BG2 ramp, which
                                 supplies the texture.
  floor lines HUD_LINES..223     FOG. Full horizon haze at the seam decaying
                                 as (1-depth)^FOG_FALLOFF, so the far rows
                                 saturate toward HORIZON_HAZE and detail
                                 dissolves with distance while the near
                                 field keeps the track's real colours. Our
                                 camera geometry is static, so the whole
                                 curve bakes into the ROM table for free.

The band split does the layer routing for free. TM shows BG2+BG3+OBJ above
the seam and BG1+OBJ below it, so one static CGADSUB (add to BG1+BG2) tints
the sky above and the floor below, while BG3 (the HUD text) and OBJ (the
car) stay out of colour math and render untinted.
"""
import sys
from pathlib import Path

TOTAL_LINES = 224                   # whole frame: the tables now span it
HUD_LINES = 44                      # world.inc: sky band = lines 0..43

SKY_TOP = (2, 8, 28)                # deep blue at the top of the frame
# The horizon haze both bands meet at. Near-neutral and BRIGHT: this is the
# colour distance washes everything out to, so the floor's far rows saturate
# toward it and detail dissolves with depth. Slightly warm and slightly blue
# rather than flat grey, so it still reads as air.
HORIZON_HAZE = (25, 25, 27)
SKY_HORIZON = HORIZON_HAZE          # sky ends on it...
FOG_PEAK = HORIZON_HAZE             # ...and the floor starts on it: the two
                                    # bands meet with no step in the tint
FOG_FALLOFF = 4                     # exponent of the floor's fog decay

PLANE = (0x20, 0x40, 0x80)          # COLDATA plane-select bits (R, G, B)

FLOOR_LINES = TOTAL_LINES - HUD_LINES


def _lerp(a: int, b: int, i: int, n: int) -> int:
    """Integer linear interpolation a -> b over n steps, at step i."""
    return a + (b - a) * i // max(1, n - 1)


def scanline_tint(plane_idx: int) -> list[int]:
    """The VISUAL contract: the 5-bit intensity that must be showing on each
    scanline 0..223. This is what a rendered-pixel test asserts against."""
    top, hor = SKY_TOP[plane_idx], SKY_HORIZON[plane_idx]
    fog = FOG_PEAK[plane_idx]
    # sky: a straight ramp from the top of the frame down to the haze
    out = [_lerp(top, hor, i, HUD_LINES) for i in range(HUD_LINES)]
    # floor: FOG. Full haze at the horizon decaying as (1 - depth)^4, so the
    # far rows saturate toward HORIZON_HAZE and detail dissolves with
    # distance, while the near field — where the player is actually looking —
    # is left essentially untinted and keeps the track's real colours. A
    # LINEAR fade instead spreads a heavy wash over the whole floor, which is
    # what desaturated the track before (see the look-1 commit).
    n = FLOOR_LINES - 1
    out += [fog * (n - i) ** FOG_FALLOFF // n ** FOG_FALLOFF
            for i in range(FLOOR_LINES)]
    assert len(out) == TOTAL_LINES, len(out)
    assert all(0 <= v < 32 for v in out), out
    return out


def channel_values(plane_idx: int) -> list[int]:
    """The ROM TABLE for one plane. Byte i IS what scanline i displays.

    This used to rotate the curve left by one, on the belief that a
    transfer for line N landed at the end of line N and so showed from
    N+1, leaving scanline 0 to a carried-over value. A review falsified
    that with a five-structure probe matrix plus the Mesen2 source: HdmaInit
    runs at scanline 0 clock 12 and the unit transferred on the PRE-RENDER
    line covers the first visible line, so a table unit with cumulative
    line index K is visible exactly at scanline K. There is no carried-over
    line 0 while the channel is armed.

    The rotation therefore put tint(S+1) on scanline S frame-wide and
    landed byte 223 = tint(0) — the SKY-TOP value — on the visible bottom
    line, which shipped as a bright band across the bottom of the floor.
    It read as correct only because the screenshot fixture's anchor was off
    by one in the cancelling direction; see test_microzero_gradient's
    race_shot. Both were fixed together, and had to be: correcting either
    alone turns the cancellation into 180 failing assertions."""
    return scanline_tint(plane_idx)


def sky_tint(plane_idx: int) -> list[int]:
    """Just the sky band's scanline slice — for tests asserting that band."""
    return scanline_tint(plane_idx)[:HUD_LINES]


def floor_tint(plane_idx: int) -> list[int]:
    """Just the floor band's scanline slice (the fog band is included: it is
    below the seam and lands on BG1 like the rest of the floor)."""
    return scanline_tint(plane_idx)[HUD_LINES:]


def tables() -> bytes:
    """The full blob: R table, then G, then B (matches the grad_tabs claim).

    The `assert` is the data half of D6. The allocator lets colr/colg/colb share
    $2132 because COLDATA_R/_G/_B are declared as disjoint PLANE masks, and D6
    says to declare a sub-register partition "only where that partition is real
    in hardware, or the mask lies". Whether it is real here is a property of
    THIS DATA: a value with a foreign plane bit set writes two planes from one
    channel, and the collision proof that let three channels share the port
    becomes a statement about a partition the ROM does not honour. Nothing
    checked it before; the shipped
    blob was clean, so this pins a property rather than fixing a defect. The
    rendered-side check is test_microzero_gradient::
    test_shipped_blob_honours_the_coldata_plane_partition, which reads the built
    artifact so a hand-edited blob fails too.
    """
    out = bytearray()
    for idx, plane in enumerate(PLANE):
        for v in channel_values(idx):
            assert 0 <= v <= 0x1F, (
                f"plane {idx} intensity {v:#04x} does not fit COLDATA's 5-bit "
                f"field — OR-ing it with the plane select would set a foreign "
                f"plane bit and write another channel's plane")
            out.append(plane | v)
    return bytes(out)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gen_gradient.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    blob = tables()
    assert len(blob) == 3 * TOTAL_LINES == 672
    (outdir / "gradient_tabs.bin").write_bytes(blob)
    print(f"gradient_tabs.bin: {len(blob)} B (3 planes x {TOTAL_LINES} lines; "
          f"sky {SKY_TOP}->{SKY_HORIZON}, horizon haze {HORIZON_HAZE} "
          f"decaying ^{FOG_FALLOFF})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
