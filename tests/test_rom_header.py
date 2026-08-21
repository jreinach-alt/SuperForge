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

THE SAME IS TRUE OF THE TWO HEADER FIELDS ADDED BELOW (docs/94 R0, docs/97).

  * `$FFD7` ROM SIZE, "2^N KB". `vendor/rom/header.inc` carried a hardcoded
    `$05` default — 32 KB, the toy/probe size — and TWENTY of the thirty-seven
    rails inherited it while linking 524,288 B. Seventeen others declared `$09`
    by hand in their own `main.asm`: the same fact written down eighteen times
    and checked nowhere. The byte is now IMPORTED from the linker config
    (`SF_LD_ROM_SIZE`), the only file that knows how big the image will be.
  * `$FFD9` DESTINATION. A hardcoded `.byte $01` with no override at all. Now
    `.ifndef`-guarded, default unchanged.

Both are invisible to every emulator in this repo for exactly the reason the
checksum was, which is why they went unnoticed for as long as they did — and
why these cases open the LINKED IMAGE and compare each field to the file's own
length. A source-level assertion about `header.inc` would pass with the linker
config exporting the wrong number, which is the drift the import was
introduced to close.
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


# ===========================================================================
# The header FIELDS: $FFD7 ROM size and $FFD9 destination  (docs/94 R0)
# ===========================================================================

BUILD = SUPERFORGE / "build"
OFF_ROMSIZE = 0x7FD7
OFF_DEST = 0x7FD9

# Every rail is a `game/*/game.toml` dir — derived from the tree rather than
# listed, so a new rail is covered the day it lands (`make rail-registered`'s
# own convention). Plus the two non-rail images linked through the same header.
RAILS = sorted(p.parent.name for p in SUPERFORGE.glob("game/*/game.toml"))
EXTRA = ["toy", "probe_vblank"]


def _image(stem: str) -> bytes:
    rom = BUILD / f"{stem}.sfc"
    if not rom.exists():
        pytest.fail(
            f"{rom} is not built. These cases read the LINKED IMAGES, so they "
            f"need the whole rail set: build it with AGENTS.md's BUILD-FIRST "
            f"make block (and `make toy probes`).")
    return rom.read_bytes()


@pytest.mark.parametrize("stem", RAILS + EXTRA)
def test_rom_size_byte_tells_the_truth(stem):
    """$FFD7 declares 2^N KB and the image really is that many bytes."""
    img = _image(stem)
    n = img[OFF_ROMSIZE]
    assert 0 <= n < 32, f"{stem}: ROM-size byte ${n:02X} is not a sane 2^N KB"
    assert (1024 << n) == len(img), (
        f"{stem}: header declares ${n:02X} = {1024 << n} B but the image is "
        f"{len(img)} B. This is the declaration-lies defect docs/94 §1 names; "
        f"the byte comes from the linker config's SF_LD_ROM_SIZE export.")


@pytest.mark.parametrize("stem", RAILS + EXTRA)
def test_destination_byte_is_the_declared_default(stem):
    """$FFD9 is $01 (North America) on every image in this tree.

    The point of the `.ifndef` is not that anything overrides it today —
    nothing does — but that a build CAN, without editing a vendored file. The
    byte declares the TARGET MARKET, not the runtime region: a cart composing
    `engine/features/region` reads the console's own region line from $213F at
    boot and adapts, which is why this default stays correct for a ROM meant to
    run on both machines."""
    assert _image(stem)[OFF_DEST] == 0x01


def test_no_image_declares_32k_unless_it_is_32k():
    """The regression this change exists to prevent, stated as a property.

    Twenty rails used to declare $05 at 524,288 B. Naming that count here would
    age badly — rails come and go — so the case asserts over the whole set
    instead."""
    liars = [(s, len(_image(s))) for s in RAILS + EXTRA
             if _image(s)[OFF_ROMSIZE] == 0x05 and len(_image(s)) != 32768]
    assert liars == [], f"images declaring 32 KB while not being 32 KB: {liars}"


def test_the_build_step_refuses_a_lying_rom_size_byte(built, tmp_path):
    """The gate has teeth: doctor a real image and require the refusal.

    `tools/fix_checksum.py` is the one build step that already reads the
    finished image, so it is the only place that can compare the declaration to
    the truth — and every rail's recipe already runs it. A COPY is doctored
    (never a tracked artifact) and the tool is invoked exactly as the Makefile
    invokes it. Sibling of `test_the_checker_actually_rejects_a_bad_checksum`
    above, for the neighbouring field."""
    src = BUILD / "microzero.sfc"
    victim = tmp_path / "liar.sfc"
    victim.write_bytes(src.read_bytes())
    buf = bytearray(victim.read_bytes())
    assert buf[OFF_ROMSIZE] == 0x09 and len(buf) == 524288
    buf[OFF_ROMSIZE] = 0x05                     # the exact defect, planted
    victim.write_bytes(bytes(buf))

    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "tools" / "fix_checksum.py"),
         str(victim)], capture_output=True, text=True)
    assert r.returncode != 0, (
        "fix_checksum.py ACCEPTED a header declaring 32 KB on a 524,288 B "
        "image — the gate is disarmed, and 20 rails shipped exactly this")
    assert "declaration lies" in (r.stdout + r.stderr)
    # ...and it REFUSED rather than silently patching: the bytes are untouched.
    assert victim.read_bytes() == bytes(buf)
