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
VROM = SUPERFORGE / "vendor" / "rom"
OFF_ROMSIZE = 0x7FD7
OFF_DEST = 0x7FD9

# ---------------------------------------------------------------------------
# WHY THE CASES BELOW CARRY A MARKER, AND WHY IT IS NOT A SKIP
#
# They open the LINKED IMAGES under build/. In the normal suite those are
# guaranteed present by the BUILD GRAPH, not by luck: the Makefile's `test:`
# target takes every rail plus `toy` and `probes` as PREREQUISITES, and
# `make rail-registered` (site 12) fails when a rail is missing from that
# list. So `_image()` FAILS on a missing image -- it never skips -- and that
# failure is a true statement about the tree rather than an accident of
# ordering.
#
# One caller runs this module BEFORE anything is linked: `tools/setup.sh`'s
# sanity step, a fresh-clone toolchain check that has no build/ to read. It
# went 75-red for exactly that reason and took `make bare-check` down with it
# at its `setup` step. It now DESELECTS these cases by marker:
#
#     python3 -m pytest ... -m "not needs_linked_images"
#
# That is a deselection at ONE NAMED CALL SITE, not a condition inside the
# tests. Nothing in this file can make a case vanish from a normal run: a run
# that passes no `-m` collects every one of them, and pytest's own summary
# line says "N deselected" the moment anything does.
#
# The rejected alternative was a stand-down-if-the-file-is-absent condition on
# each case. It would have gone green in the fresh clone AND green in a normal
# run with a broken or half-finished build -- the second is the whole failure:
# 75 cases reporting nothing while reading as a pass. A test that stands down
# when its subject is missing is how coverage evaporates without anyone seeing
# it, so the tripwire below refuses that machinery in this file by name.
#
# `test_the_image_cases_cannot_be_dropped_except_by_the_pre_build_caller`
# below is the tripwire that holds this contract.
# ---------------------------------------------------------------------------

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


@pytest.mark.needs_linked_images
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


@pytest.mark.needs_linked_images
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


def test_the_destination_byte_can_be_overridden(built, tmp_path):
    """The `.ifndef SF_HDR_DEST` hatch, exercised — docs/94 R0's "a build
    declares the region it targets".

    Every image in this tree takes the $01 default, so the hatch is the only
    thing that makes $FFD9 a DECLARATION rather than a constant — and until
    this case existed, nothing in the tree touched it. A mis-spelled `.ifndef`,
    or the `.byte` drifting above its guard, would have left every image at $01
    and been invisible: the audit proved the hatch works BY HAND and filed the
    absence of this case as the reason R0's third clause reads PARTIAL
    (`docs/audit/region_r0-audit-1.md` F5).

    The toy is assembled and linked TWICE into tmp_path with the same ca65 /
    ld65 invocation the Makefile uses — once plain, once with
    `-D SF_HDR_DEST=$02` (Europe). `tools/fix_checksum.py` is deliberately NOT
    run on either arm, so both carry the unfilled checksum pair and the
    comparison is not polluted by a recomputed one.

    The part that makes this more than "the byte we set came back": the two
    images must differ AT $FFD9 AND NOWHERE ELSE. That is what says the hatch
    reaches the destination byte and only the destination byte."""
    def link(stem, *extra):
        obj, sfc = tmp_path / f"{stem}.o", tmp_path / f"{stem}.sfc"
        r = subprocess.run(
            ["ca65", "--cpu", "65816", *extra, "-I", str(BUILD), "-I", str(VROM),
             "-o", str(obj), "engine/toy/main.asm"],
            cwd=SUPERFORGE, capture_output=True, text=True)
        assert r.returncode == 0, f"ca65 failed:\n{r.stdout}{r.stderr}"
        r = subprocess.run(
            ["ld65", "-C", str(VROM / "lorom_32k.cfg"), "-o", str(sfc), str(obj)],
            cwd=SUPERFORGE, capture_output=True, text=True)
        assert r.returncode == 0, f"ld65 failed:\n{r.stdout}{r.stderr}"
        return sfc.read_bytes()

    control = link("dest_default")
    override = link("dest_europe", "-D", "SF_HDR_DEST=$02")

    assert control[OFF_DEST] == 0x01, (
        f"the control arm reads ${control[OFF_DEST]:02X} at $FFD9 — the "
        f"default itself has moved, so this case proves nothing about the hatch")
    assert override[OFF_DEST] == 0x02, (
        f"SF_HDR_DEST = $02 did not reach $FFD9 (found "
        f"${override[OFF_DEST]:02X}) — the .ifndef hatch is not wired, and "
        f"every image would silently declare North America")
    moved = [i for i in range(len(control)) if control[i] != override[i]]
    assert moved == [OFF_DEST], (
        f"the override moved bytes other than $FFD9: "
        f"{[hex(i) for i in moved]} — the hatch is reaching further than the "
        f"destination byte")


@pytest.mark.needs_linked_images
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


def _logical_line(text: str, head: str) -> str:
    """The `head` line of a Makefile with its backslash continuations joined."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(head):
            out = [ln]
            while out[-1].rstrip().endswith("\\"):
                i += 1
                out.append(lines[i])
            return " ".join(x.rstrip().rstrip("\\") for x in out)
    raise AssertionError(f"no {head!r} line in the Makefile")


def test_the_image_cases_cannot_be_dropped_except_by_the_pre_build_caller():
    """The tripwire on the marker contract at the top of the FIELDS section.

    A marker is only safe while the deselection lives at ONE known call site.
    The moment it also lives inside the cases, or inside the suite runner, the
    75 image cases can report nothing and read as a pass — which is exactly the
    state `tools/setup.sh` was in when `make bare-check` died at its `setup`
    step in 19 seconds. So the contract is asserted, not trusted, and it is
    asserted by READING THE TOOLS, which is the primary source for what our own
    tools do (CLAUDE.md, "if you are about to state what a tool does, open the
    tool").

    Four clauses:

      1. this file holds no skip machinery, so nothing here can stand a case
         down on a missing image — `_image` fails, by design;
      2. `tools/setup.sh` drops them by DESELECTING THE MARKER, not by ignoring
         the module — ignoring it would silently take the four checksum cases
         and the override case with it, and those need no build;
      3. the suite's entry point (`make test`) never names the marker, so a
         normal run collects every case;
      4. `toy` and `probe_vblank` — the two non-rail images these cases read —
         are guaranteed by that same entry point's prerequisites. The 37 rails
         are `make rail-registered`'s site 12 and are not re-asserted here; the
         same fact at two sites rots at one of them."""
    src = Path(__file__).read_text()
    # Spelled by concatenation so this case does not trip over itself.
    for token in ("pytest." + "skip", "skip" + "if", "import" + "orskip"):
        assert token not in src, (
            f"{token} appeared in {Path(__file__).name}. These cases must FAIL "
            f"on a missing image, never stand down: a skip goes green in a "
            f"fresh clone and green again on a broken build, and 75 cases then "
            f"report nothing while reading as a pass. The pre-build caller "
            f"deselects by marker instead — see the FIELDS section header.")

    setup_sh = (SUPERFORGE / "tools" / "setup.sh").read_text()
    assert '-m "not needs_linked_images"' in setup_sh, (
        "tools/setup.sh no longer deselects the image cases by marker. It runs "
        "before anything is linked, so if it stopped deselecting them it is "
        "either red on a fresh clone again, or it dropped the module wholesale")
    assert "--ignore" not in setup_sh and "--ignore-glob" not in setup_sh, (
        "tools/setup.sh drops a test module wholesale. The marker exists so "
        "the cases that need no build (the checksum cases, the $FFD9 override) "
        "keep running there")

    makefile = (SUPERFORGE / "Makefile").read_text()
    recipe = _logical_line(makefile, "\t@$(PY) -m pytest tests/")
    assert "needs_linked_images" not in recipe, (
        f"the suite runner names the marker, so a normal run deselects the "
        f"image cases:\n{recipe}")

    prereqs = set(_logical_line(makefile, "test:").split()[1:]) - {"|"}
    for target in ("toy", "probes"):
        assert target in prereqs, (
            f"`make test` no longer takes `{target}` as a prerequisite, so "
            f"{'build/toy.sfc' if target == 'toy' else 'build/probe_vblank.sfc'} "
            f"is not guaranteed to exist when these cases read it")
