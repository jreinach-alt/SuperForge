#!/usr/bin/env python3
"""fix_checksum.py — compute and patch a linked SNES ROM's header checksum.

    fix_checksum.py ROM...            patch in place (build step)
    fix_checksum.py --check ROM...    verify only, non-zero exit on mismatch

ca65 cannot do this: the checksum covers the whole linked image, including
its own header bytes, so it only exists after ld65 has run. header.inc
therefore ships the canonical UNFILLED pair — complement $FFFF, checksum
$0000 — and this runs over the output.

Why bother, given Mesen/bsnes/snes9x all ignore it: flashcart menus and ROM
verification tools do not. An unfilled checksum reads as a corrupt dump, and
some hardware loaders refuse to boot on it. It is also the difference
between "the emulator accepts this" and "this is a well-formed SFC".

The algorithm (fullsnes, "SNES Cartridge Header"):
  * the complement/checksum pair is defined to sum to $FFFF, so it is
    neutralised to $FFFF/$0000 before summing — which is what makes this
    IDEMPOTENT: re-running on an already-patched ROM recomputes the same
    value rather than folding the old one in;
  * sum every byte of the image, mod $10000.
A non-power-of-two image is REFUSED rather than mirrored — see _sum_mirrored.
"""
import sys
from pathlib import Path

# header offsets within a LoROM image (HiROM would be $FFC0; we build LoROM
# only, and an unexpected layout must fail loudly rather than patch garbage)
HDR = 0x7FC0
OFF_TITLE = HDR + 0x00
OFF_MAPMODE = HDR + 0x15
OFF_COMPLEMENT = HDR + 0x1C
OFF_CHECKSUM = HDR + 0x1E


def _sum_mirrored(data: bytes) -> int:
    """Byte sum mod $10000, for a power-of-two image.

    The non-power-of-two case — where the hardware mirrors the tail up to
    the next power of two — used to be implemented here and is now REFUSED
    instead. Review finding F5: it was dead code for every size this repo links,
    it was never tested, and its floor-divided repeat count under-mirrored
    any tail that does not divide the head (a 448 KB image, say). Untested
    code that is also wrong is worse than absent: it reads as coverage.
    Anyone who needs it should implement it against a real ROM of that size
    and a test that fails without it."""
    n = len(data)
    if n & (n - 1):
        raise SystemExit(
            f"fix_checksum: {n} B is not a power of two. The mirrored-sum "
            f"path for such images is deliberately not implemented (see this "
            f"docstring) — implement it with a test rather than guessing.")
    return sum(data) & 0xFFFF


def compute(image: bytes) -> int:
    """The checksum this image should carry."""
    buf = bytearray(image)
    buf[OFF_COMPLEMENT:OFF_COMPLEMENT + 2] = b"\xFF\xFF"
    buf[OFF_CHECKSUM:OFF_CHECKSUM + 2] = b"\x00\x00"
    return _sum_mirrored(bytes(buf))


def stored(image: bytes) -> tuple[int, int]:
    """The (complement, checksum) pair currently in the header."""
    return (int.from_bytes(image[OFF_COMPLEMENT:OFF_COMPLEMENT + 2], "little"),
            int.from_bytes(image[OFF_CHECKSUM:OFF_CHECKSUM + 2], "little"))


def _validate_layout(image: bytes, path: Path) -> None:
    """Refuse to patch anything that is not the LoROM image we think it is.

    SCOPE, stated honestly: this is a heuristic, not a format
    check. A constructed binary with printable text at $7FC0 and bit 0 clear
    at $7FD5 WILL be patched. That is acceptable because this runs as a build
    step over its own ld65 output and nothing else — it is a guard against
    being pointed at the wrong file, not a validator for arbitrary input. Do
    not rely on it to reject hostile or unknown binaries."""
    if len(image) < HDR + 0x30:
        raise SystemExit(f"{path}: too small to hold a LoROM header "
                         f"({len(image)} B)")
    title = image[OFF_TITLE:OFF_TITLE + 21]
    if not all(0x20 <= b < 0x7F for b in title):
        raise SystemExit(
            f"{path}: no printable 21-char title at ${HDR:04X} — not the "
            f"LoROM layout this tool patches (HiROM? headered .smc?)")
    mapmode = image[OFF_MAPMODE]
    if mapmode & 0x01:
        raise SystemExit(f"{path}: map mode ${mapmode:02X} is HiROM; this "
                         f"tool patches LoROM images only")


def process(path: Path, check_only: bool) -> bool:
    image = path.read_bytes()
    _validate_layout(image, path)
    want = compute(image)
    want_c = want ^ 0xFFFF
    have_c, have = stored(image)
    title = image[OFF_TITLE:OFF_TITLE + 21].decode("ascii").rstrip()

    if (have, have_c) == (want, want_c):
        print(f"  {path.name}: checksum ${want:04X} OK ({title})")
        return True
    if check_only:
        print(f"  {path.name}: checksum ${have:04X}/${have_c:04X} but the "
              f"image sums to ${want:04X}/${want_c:04X} ({title})",
              file=sys.stderr)
        return False

    buf = bytearray(image)
    buf[OFF_COMPLEMENT:OFF_COMPLEMENT + 2] = want_c.to_bytes(2, "little")
    buf[OFF_CHECKSUM:OFF_CHECKSUM + 2] = want.to_bytes(2, "little")
    path.write_bytes(bytes(buf))
    print(f"  {path.name}: checksum ${want:04X} written ({title})")
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    roms = [Path(a) for a in argv if a != "--check"]
    if not roms:
        print(__doc__, file=sys.stderr)
        return 2
    ok = True
    for rom in roms:
        ok &= process(rom, check_only)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
