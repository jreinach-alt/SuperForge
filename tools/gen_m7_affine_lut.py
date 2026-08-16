#!/usr/bin/env python3
"""gen_m7_affine_lut.py — the Mode 7 static-affine rotation matrix, tabulated.

Emits (byte-identical on re-run, pure integer math after the trig):

    m7_affine_lut.bin   256 headings x 4 signed 16-bit LE words = 2048 B
                        per heading, in order:  M7A  M7B  M7C  M7D

WHY A TABLE AND NOT A SOLVE
---------------------------
The Mode 7 affine matrix for a uniform rotation at scale 1.0 is

    M7A =  cos(t)      M7B = sin(t)
    M7C = -sin(t)      M7D = cos(t)          (uniform scale: D = A, C = -B)

in signed 1.7.8 fixed point. At a FIXED scale it is a pure function of one
byte, so it has exactly 256 possible answers -- which is a table, not a solve.

A runtime solve computes it every frame: `sincos` (a 512-entry LUT read)
plus TWO signed 16x16 multiplies via `smul16`. That is
strictly more work for the same answer, because at scale $0100 the multiply is
the IDENTITY:

    M7A = (cos * $0100) >> 8 == cos

VERIFIED, not assumed: a direct cos/sin table reproduces the
sincos+smul16 result for ALL 256 headings with ZERO discrepancies, and the
vendored 512-entry sin_lut matches its own stated rule
(`sin_lut[i] = round(sin(i*pi/256) * 256)`) at every one of its 512 entries.
So this is not an approximation of the source's math -- it is bit-identical to
it, and `tests/test_m7_affine_lut.py` holds that to account.

THE ANGLE CONVENTION, inherited deliberately
--------------------------------------------
Heading is 0..255 for one full turn (the rail's own convention: LEFT increments,
RIGHT decrements, wrapped to 8 bits). A runtime solve reaches the same values
through a 512-entry half-step table indexed `angle*2`, with cosine a quarter
period along at `(angle*2 + 128) & $1FE`. Composing those gives, for heading
`a`:

    sin(a) = round(sin(a * pi/128) * 256)
    cos(a) = round(cos(a * pi/128) * 256)

which is what this file tabulates directly. Range is -256..+256 inclusive,
so every entry fits a signed 16-bit word (256 = 1.0 in 1.7.8).
"""
import math
import sys
from pathlib import Path

HEADINGS = 256          # one full turn, the rail's 8-bit heading
ONE = 256               # 1.0 in signed 1.7.8


def coeff(a: int) -> tuple[int, int, int, int]:
    """(M7A, M7B, M7C, M7D) for heading `a`, signed 1.7.8.

    Uniform scale 1.0, so D == A and C == -B: the matrix is a pure rotation
    and its inverse is its transpose, which is what makes the world->screen
    sprite projection a coefficient swap rather than a matrix solve.
    """
    t = a * math.pi / (HEADINGS // 2)
    c = round(math.cos(t) * ONE)
    s = round(math.sin(t) * ONE)
    return c, s, -s, c


def build() -> bytes:
    out = bytearray()
    for a in range(HEADINGS):
        for v in coeff(a):
            assert -32768 <= v <= 32767, (a, v)
            out += (v & 0xFFFF).to_bytes(2, "little")
    assert len(out) == HEADINGS * 4 * 2 == 2048, len(out)
    return bytes(out)


def main(argv):
    if len(argv) != 2:
        print("usage: gen_m7_affine_lut.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    blob = build()
    (outdir / "m7_affine_lut.bin").write_bytes(blob)
    print(f"wrote {outdir / 'm7_affine_lut.bin'} ({len(blob)} B, "
          f"{HEADINGS} headings x 4 words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
