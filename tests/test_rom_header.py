"""Every ROM the build ships carries a valid SNES header checksum.

The checksum covers the whole linked image including its own header bytes,
so ca65 cannot emit it — header.inc ships the canonical unfilled pair
($FFFF/$0000) and tools/fix_checksum.py patches the ld65 output. Mesen,
bsnes and snes9x all ignore the field, which is exactly why it went
unnoticed: an unfilled checksum is invisible to every test that runs on an
emulator, and reads as a corrupt dump to a flashcart menu or a verification
tool.

These tests therefore assert the ARTIFACT, not the behaviour — nothing
about the ROM's execution changes when the checksum is wrong.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent

SHIPPED = ("toy.sfc", "microzero.sfc")


def load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, SUPERFORGE / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fx():
    return load_tool("fix_checksum")


@pytest.fixture(scope="module")
def built():
    for target in ("toy", "microzero"):
        r = subprocess.run(["make", target], cwd=SUPERFORGE,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"make {target} failed:\n{r.stderr}"
    return [SUPERFORGE / "build" / n for n in SHIPPED]


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_rom_checksum_is_valid(built, fx, name):
    """The build's own output verifies — i.e. the fixup ran, on every ROM."""
    rom = SUPERFORGE / "build" / name
    image = rom.read_bytes()
    have_c, have = fx.stored(image)
    want = fx.compute(image)
    assert have == want, (
        f"{name}: header checksum ${have:04X} but the image sums to "
        f"${want:04X} — did the link step skip tools/fix_checksum.py?")
    assert have ^ have_c == 0xFFFF, (
        f"{name}: complement ${have_c:04X} is not the inverse of checksum "
        f"${have:04X}")


def test_the_checker_actually_rejects_a_bad_checksum(built, fx, tmp_path):
    """Falsification: a test that cannot fail is worth nothing.

    Flip one byte of the payload — leaving the header untouched — and the
    stored checksum must stop matching. This is the corruption a flashcart's
    verifier is looking for, and it is invisible to every emulator test in
    this suite."""
    good = (SUPERFORGE / "build" / "microzero.sfc").read_bytes()
    corrupt = bytearray(good)
    corrupt[0x1234] ^= 0xFF                  # payload, well clear of $7FC0
    assert fx.stored(bytes(corrupt))[1] != fx.compute(bytes(corrupt)), \
        "a corrupted image still verifies — the checksum proves nothing"

    bad = tmp_path / "bad.sfc"
    bad.write_bytes(bytes(corrupt))
    r = subprocess.run([sys.executable, str(SUPERFORGE / "tools" / "fix_checksum.py"),
                        "--check", str(bad)], capture_output=True, text=True)
    assert r.returncode != 0, \
        f"--check exited 0 on a corrupted image:\n{r.stdout}{r.stderr}"


def test_patching_is_idempotent(built, fx, tmp_path):
    """Re-running the fixup must not fold the previous value back in.

    The complement/checksum pair sums to $FFFF by definition, so the tool
    neutralises it before summing; without that step a second run would
    produce a different number and the build would never converge."""
    rom = tmp_path / "again.sfc"
    rom.write_bytes((SUPERFORGE / "build" / "microzero.sfc").read_bytes())
    first = rom.read_bytes()
    for _ in range(3):
        r = subprocess.run(
            [sys.executable, str(SUPERFORGE / "tools" / "fix_checksum.py"), str(rom)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert rom.read_bytes() == first, \
        "re-running the fixup changed the image — it is not idempotent"


def test_refuses_an_image_it_does_not_recognise(fx, tmp_path):
    """The tool writes four bytes at a fixed offset. On anything that is not
    the LoROM layout it assumes, it must refuse rather than corrupt."""
    junk = tmp_path / "junk.sfc"
    junk.write_bytes(bytes(0x10000))         # zeroes: no printable title
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "tools" / "fix_checksum.py"), str(junk)],
        capture_output=True, text=True)
    assert r.returncode != 0, "patched an unrecognised image"
    assert junk.read_bytes() == bytes(0x10000), "modified it anyway"
