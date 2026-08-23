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

IT ALSO REFUSES A LYING ROM-SIZE BYTE. $FFD7 declares 2^N KB and it was
FALSE on 20 of 37 rails (docs/94 §1); the byte now comes from the linker
config, and _check_rom_size is what keeps the config and the image from
drifting apart again. This is the only build step that reads the finished
image, so it is the only place that can compare the declaration to the truth
— and a tool that patched a checksum over a lying header would be certifying
the lie.

That refusal is what makes the byte usable as an AUTHORITY rather than just a
field, so `declared_size` below is public: `tools/bare_check.sh` asks each
built image how long it says it is instead of carrying a hand-maintained list
of expected sizes. One decoding, two readers.
"""
import sys
from pathlib import Path

# header offsets within a LoROM image (HiROM would be $FFC0; we build LoROM
# only, and an unexpected layout must fail loudly rather than patch garbage)
HDR = 0x7FC0
OFF_TITLE = HDR + 0x00
OFF_MAPMODE = HDR + 0x15
OFF_ROMSIZE = HDR + 0x17
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
    _check_rom_size(image, path)


def declared_size(image: bytes) -> int | None:
    """The image length $FFD7 declares, in bytes — 2^N KB, or None if N is
    out of range.

    THE ONE DECODING OF THAT BYTE IN THIS TREE, and it is public because it
    has two readers. `_check_rom_size` below compares it to the truth on
    every linked image on every build; `tools/bare_check.sh`'s census uses it
    as the PER-IMAGE expected size, in place of the hand-maintained list of
    `rom:size` pairs the landing gate carried until 2026-08-23. Both read the
    format from here, so neither can drift into an opinion of its own about
    where the byte lives or what it means.
    """
    n = image[OFF_ROMSIZE]
    return 1024 << n if n < 32 else None


def _check_rom_size(image: bytes, path: Path) -> None:
    """$FFD7 declares 2^N KB. Refuse an image whose declaration is not true.

    THIS IS THE GATE ON docs/94 R0's fourth clause, and it exists because the
    declaration was FALSE on 20 of 37 rails: vendor/rom/header.inc carried a
    hardcoded 32 KB default that every rail not overriding it inherited while
    linking 524,288 B. The byte is now imported from the linker config
    (SF_LD_ROM_SIZE), and this is what stops the config and the image drifting
    apart again — the check runs on every linked image on every build, because
    every rail's recipe already runs this tool.

    Deliberately a HARD REFUSAL rather than a warning, and deliberately here
    rather than in a separate gate: this is the one build step that already
    reads the finished image, so it is the only place that can see both the
    declaration and the truth. A tool that patched a checksum over a lying
    header would be certifying the lie."""
    n = image[OFF_ROMSIZE]
    declared = declared_size(image)
    if declared != len(image):
        shown = f"{declared} B" if declared is not None else f"2^{n} KB"
        raise SystemExit(
            f"{path}: header ${OFF_ROMSIZE:04X} declares ROM size ${n:02X} "
            f"= {shown}, but the image is {len(image)} B. The declaration "
            f"lies. The byte comes from the linker config's SF_LD_ROM_SIZE "
            f"export (vendor/rom/lorom_*.cfg) — fix it there, or define "
            f"SF_HDR_ROM_SIZE before including header.inc.")


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
