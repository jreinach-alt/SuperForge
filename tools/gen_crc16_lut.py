#!/usr/bin/env python3
"""gen_crc16_lut.py — the save feature's CRC-16/CCITT lookup table.

Emits crc16_lut.bin: 256 entries x 2 bytes little-endian = 512 B, poly $1021,
no bit reflection — the table form of

    for each byte: index = (CRC >> 8) ^ byte; CRC = (CRC << 8) ^ tab[index]

with init $FFFF applied by the kernel (engine/features/save/save.asm), i.e.
CRC-16/CCITT-FALSE — a standard, widely published CRC family. The 512-B table
is reproduced HERE from the polynomial rather than carried as data, and the
generator asserts its first eight entries against the published first row
(REF_ROW0 below), so a change to the polynomial or to the shift direction is a
build stop rather than a silently different checksum.

Deterministic: pure integer math, byte-identical on re-run.
"""
import sys
from pathlib import Path

POLY = 0x1021

# The published CRC-16/CCITT table's first row (poly $1021, MSB-first, no
# reflection), asserted below: same polynomial, same shift direction, same
# table = same CRC family.
REF_ROW0 = (0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7)


def entry(i: int) -> int:
    crc = i << 8
    for _ in range(8):
        crc = ((crc << 1) ^ POLY) if (crc & 0x8000) else (crc << 1)
        crc &= 0xFFFF
    return crc


def table() -> list[int]:
    t = [entry(i) for i in range(256)]
    assert tuple(t[:8]) == REF_ROW0, (
        "table disagrees with the published CRC-16/CCITT first row — "
        f"got {[hex(x) for x in t[:8]]}")
    return t


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_crc16_lut.py <outdir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    blob = b"".join(v.to_bytes(2, "little") for v in table())
    assert len(blob) == 512
    (out / "crc16_lut.bin").write_bytes(blob)
    print(f"gen_crc16_lut: 256 entries, poly ${POLY:04X} -> {out / 'crc16_lut.bin'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
