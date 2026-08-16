#!/usr/bin/env python3
"""gen_iris_lut.py — the lantern's circle, as a half-width table.

Emits (byte-identical on re-run, pure integer math):
  iris_lut.bin   2*(2*R+1) bytes — half-width at each row offset, as 16-bit
                 little-endian WORDS

WHY WORDS for values that all fit in a byte. The rebuild kernel runs A16, so a
byte LUT cost it a `sep #$20` / `lda` / `rep #$20` / `and #$00FF` sandwich on
every circle row just to read one number — 9 cycles and two width transitions
per row, inside the hottest loop in the room. Storing the high byte (always
zero, asserted below) buys the whole sandwich back for 97 extra ROM bytes.

`half_widths()` is unchanged and is still the tests' oracle: only the on-disk
ENCODING widened, so every expected table byte is identical.

Entry i is the half-width at dy = i - R, i.e. the largest h with
h^2 + dy^2 <= R^2. So the lit span on that scanline is [cx-h, cx+h]
inclusive, and the window is `WH0 = cx-h, WH1 = cx+h` (both bounds are
inclusive in hardware — SnesPpuTypes.h:109-124).

INTEGER ONLY, and deliberately so: this file is also the TESTS' ORACLE.
A float sqrt with rounding would make the oracle's answer depend on the
host's libm at the boundary rows, and the test asserts screenshot pixels
against exactly this table. `isqrt` is exact.

There is no anti-aliasing and no soft edge. One window gives one hard span
per scanline, which is what the hardware does and what a shipping SNES
lantern looks like.
"""
import sys
from math import isqrt
from pathlib import Path

RADIUS = 48                             # px; the lit circle's radius


def half_widths(radius: int = RADIUS) -> list[int]:
    """Half-width per row offset, dy = -radius .. +radius inclusive."""
    r2 = radius * radius
    return [isqrt(r2 - dy * dy) for dy in range(-radius, radius + 1)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_iris_lut.py <outdir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    lut = half_widths()
    assert len(lut) == 2 * RADIUS + 1, len(lut)
    assert lut[RADIUS] == RADIUS, "the middle row must be the full radius"
    assert lut[0] == 0 and lut[-1] == 0, "the end rows must close the circle"
    assert max(lut) == RADIUS
    # The kernel reads these 16 bits wide and does NOT mask the high byte, so
    # the high byte being zero is load-bearing rather than incidental.
    assert all(0 <= h <= 0xFF for h in lut), "a half-width would set the high byte"
    blob = b"".join(h.to_bytes(2, "little") for h in lut)
    (out / "iris_lut.bin").write_bytes(blob)
    print(f"gen_iris_lut: {len(lut)} entries ({len(blob)} B as 16-bit words), "
          f"radius {RADIUS} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
