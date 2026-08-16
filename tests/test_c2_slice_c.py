"""this slice — "it remembers": persistence, the twin, and the pip HUD, end to end.

Every assertion lands on a hardware-destination region or a render — live
SnesSaveRam bytes, the built ROM's header bytes, BG3's VRAM tilemap words,
OAM bytes, screenshot pixels — never a proxy variable (CLAUDE.md rule 2).
The CRC oracle is INDEPENDENT: this file builds its own CRC-16/CCITT table
from the polynomial and never reads the engine's LUT, so an engine-side
table bug cannot certify itself.

THE THREE HARNESS TRAPS, already paid for once, are honoured
throughout:
  * live SRAM is read via MemoryType.SnesSaveRam mid-run — the .srm FILE is
    stale until a ROM unload flushes it;
  * a cold boot uses the `virgin_srm` ordering — load a NEUTRAL ROM first
    (unloading the room flushes its battery NOW), then delete the .srm,
    then boot: a bare delete is silently resurrected by the next load's
    unload-flush;
  * the .srm file is the corruption channel — fixtures are crafted between
    a neutral-ROM flush and the next boot, and every rejection case ships
    beside a crafted-VALID control that PASSES the gate, so the reds
    isolate the format checks rather than the channel.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

import mesen_runner  # noqa: E402
from mesen_runner import MesenRunner, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "room.sfc"
NEUTRAL = SUPERFORGE / "build" / "toy.sfc"      # no SRAM: a flush-only cart

# --- the emitted map: addresses are asked for, never hardcoded -------------
_JMAP = json.loads((SUPERFORGE / "build" / "rm" / "symbol_map.json").read_text())


def _sym(name, scene=None):
    pools = ([_JMAP["scenes"][scene]["placements"]] if scene
             else [_JMAP["globals"]])
    for pool in pools:
        for p in pool:
            if p["sym"] == name:
                return p
    raise KeyError(name)


SM_CTL = _sym("ES_SM_CTL")["start"]
TITLE_MAP = _sym("ES_V_TEXT_MAP", "title")["start"]     # VRAM word address
HERO2_SLOT = _sym("ES_O_HERO2", "room")["start"]
PIPS_SLOT = _sym("ES_O_HUD_PIPS", "room")["start"]
PIPS_COUNT = _sym("ES_O_HUD_PIPS", "room")["size"]

SCENE_TITLE, SCENE_ROOM = 0, 1

# The title's VISITS hex4 lands at tilemap row 21 col 17 (title.asm), with
# BG3 attr palette 7 + priority; glyph index = ASCII - 32 (bg_text).
TXT_ATTR = (7 << 10) | (1 << 13)
VISITS_CELL = TITLE_MAP + 21 * 32 + 17

# Slot-0 format constants (save/feature.toml). The TEST side of the format
# contract — deliberately restated here, not read out of save.asm.
MAGIC = b"SF"
FORMAT_VER = 1
HDR_SIZE = 8
SRM_SIZE = 2048                 # $FFD8 = $01 -> 1024<<1

# --- the INDEPENDENT CRC-16/CCITT oracle -----------------------------------
POLY = 0x1021


def _mktab():
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ POLY) if (c & 0x8000) else (c << 1)
            c &= 0xFFFF
        tab.append(c)
    return tab


_TAB = _mktab()


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = ((crc << 8) ^ _TAB[((crc >> 8) ^ b) & 0xFF]) & 0xFFFF
    return crc


def slot_image(payload: bytes, *, version=FORMAT_VER, length=None,
               crc=None) -> bytes:
    """A 32-B slot image in the shipped format, CRC computed by the oracle
    unless overridden (the corruption fixtures override)."""
    length = len(payload) if length is None else length
    hdr = MAGIC + bytes([version, 0]) + length.to_bytes(2, "little")
    body = hdr + b"\x00\x00" + payload
    c = crc16(body) if crc is None else crc
    return (hdr + c.to_bytes(2, "little") + payload).ljust(32, b"\x00")


# --------------------------------------------------------------------------
# runner + drive helpers
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runner():
    assert ROM.exists(), f"{ROM} missing — run `make room`"
    assert NEUTRAL.exists(), f"{NEUTRAL} missing — run `make toy`"
    r = MesenRunner()
    yield r
    # leave no battery behind: later modules (test_room_window boots this
    # ROM) should start from their own state, not this module's saves
    r.boot_rom(str(NEUTRAL), frames=18)
    srm_path().unlink(missing_ok=True)
    r.stop()


def srm_path() -> Path:
    """The ACTIVE process's Saves/room.srm — the home dir is fixed at the
    first MesenRunner init in this process (SF_MESEN_HOME honoured there),
    so ask the module global rather than recomputing the default."""
    params = getattr(mesen_runner, "_GLOBAL_INIT_PARAMS", None)
    home = params[1] if params else mesen_runner._DEFAULT_HOME_DIR
    return Path(home) / "Saves" / (ROM.stem + ".srm")


def virgin_boot(r, boot_frames=120):
    """The reference's cold-boot ordering: neutral ROM first (flushes the room
    cart's battery NOW), then delete the .srm, then boot the room — SRAM
    seeds from power-on randomness, not from a resurrected file."""
    r.boot_rom(str(NEUTRAL), frames=18)
    srm_path().unlink(missing_ok=True)
    r.boot_rom(str(ROM), frames=boot_frames)


def crafted_boot(r, srm: bytes, boot_frames=120):
    """Boot the room off a crafted .srm (the corruption channel).

    Saves/ is created explicitly: on a virgin SF_MESEN_HOME it exists only
    after a room boot's unload-flush has made it, so without the mkdir this
    helper is order-dependent — selecting a crafted_boot test alone against
    a fresh home hit FileNotFoundError.
    """
    r.boot_rom(str(NEUTRAL), frames=18)
    srm_path().parent.mkdir(parents=True, exist_ok=True)
    srm_path().write_bytes(srm.ljust(SRM_SIZE, b"\x00"))
    r.boot_rom(str(ROM), frames=boot_frames)


def scene_state(r):
    b = r.read_bytes(MemoryType.SnesWorkRam, SM_CTL, 4)
    return b[0], b[2]


def settle(r, want, limit=300):
    """`limit` is EMULATED frames — a transition takes frames to complete,
    and the wall-clock loop this replaced bought however many of them the
    host had spare.

    Plus two frames for the picture to catch up to the flag: this module
    reads rendered BG3 tilemap words after settling, and the scene manager
    reports (want, 0) one frame before the composited frame shows it. Same
    reason as test_room_window's settle, which measured it."""
    try:
        r.wait_until(lambda: scene_state(r) == (want, 0),
                     max_frames=limit, what=f"scene {want} running")
    except TimeoutError:
        raise AssertionError(
            f"scene {want} never settled: at {scene_state(r)}")
    r.wait_frames(2)


def press_start(r):
    r.set_input(0, start=True)
    r.wait_frames(4)                      # 4 EMULATED frames of the press
    r.set_input(0)
    r.wait_frames(4)


def enter_room(r):
    settle(r, SCENE_TITLE)
    press_start(r)
    settle(r, SCENE_ROOM)


def back_to_title(r):
    press_start(r)
    settle(r, SCENE_TITLE)


def title_visits_digits(r):
    """The rendered VISITS value: BG3 tilemap words of the hex4 cells.

    This is the OUTPUT region — the tile words the PPU composes — not the
    WRAM variable they were rendered from. Each word must carry the title's
    exact attr bits; the glyph nibble decodes per bg_text's ASCII-32 map.
    """
    settle(r, SCENE_TITLE)
    raw = r.read_bytes(MemoryType.SnesVideoRam, VISITS_CELL * 2, 8)
    val = 0
    for i in range(4):
        word = raw[2 * i] | (raw[2 * i + 1] << 8)
        assert word & 0xFC00 == TXT_ATTR, \
            f"digit {i} attr wrong: ${word:04X} (not the title text attr)"
        glyph = word & 0x3FF
        d = glyph - (ord("0") - ord(" "))
        if d > 9:
            d -= 7                      # 'A'.. glyphs skip the punctuation run
        assert 0 <= d <= 15, f"digit {i} glyph {glyph} is not a hex digit"
        val = (val << 4) | d
    return val


def read_slot0(r) -> bytes:
    return r.read_bytes(MemoryType.SnesSaveRam, 0, 32)


# --------------------------------------------------------------------------
# the artifact: the shipped header declares the battery
# --------------------------------------------------------------------------

def test_room_header_declares_the_battery():
    """$FFD6/$FFD8 out of the .sfc FILE — what a flashcart, bsnes, or real
    hardware reads. The other half of the A3 derivation contract (microzero
    asserts $00/$00 + a pinned md5 in test_c2_sram_class)."""
    img = ROM.read_bytes()
    assert img[0x7FD6] == 0x02, f"cart type ${img[0x7FD6]:02X}, want $02"
    assert img[0x7FD8] == 0x01, f"SRAM size ${img[0x7FD8]:02X}, want $01 (2 KiB)"


# --------------------------------------------------------------------------
# cold boot: power-on garbage must read as "no save"
# --------------------------------------------------------------------------

def test_cold_boot_rejects_virgin_garbage(runner):
    """Virgin SRAM is random (never zeroed — rule 5 applies to SRAM with
    extra force), so the ONLY thing standing between power-on noise and a
    corrupted visits count is the magic+version+length+CRC gate. The
    falsification for this test's teeth is the planted magic-only gate run
    recorded in this change report: with the CRC check skipped, the
    crc-flipped fixture below boots to a nonzero count and this file reds.
    """
    virgin_boot(runner)
    assert title_visits_digits(runner) == 0, \
        "a virgin cart booted with a remembered count — raw SRAM was trusted"
    enter_room(runner)
    oam = runner.read_bytes(MemoryType.SnesSpriteRam, PIPS_SLOT * 4,
                            PIPS_COUNT * 4)
    lit = [i for i in range(PIPS_COUNT) if oam[i * 4 + 1] != 240]
    assert lit == [0], f"first visit should light exactly pip 0, lit={lit}"


# --------------------------------------------------------------------------
# the save is destination bytes, certified by the independent oracle
# --------------------------------------------------------------------------

def test_entering_the_room_saves_slot0_with_oracle_verified_crc(runner):
    virgin_boot(runner)
    enter_room(runner)
    slot = read_slot0(runner)
    assert slot[:2] == MAGIC, f"magic {slot[:2]!r}"
    assert slot[2] == FORMAT_VER and slot[3] == 0
    length = slot[4] | (slot[5] << 8)
    assert length == 2, f"payload length {length}, want 2 (visits u16)"
    visits = slot[8] | (slot[9] << 8)
    assert visits == 1, f"first visit saved {visits}"
    stored = slot[6] | (slot[7] << 8)
    want = crc16(slot[:6] + b"\x00\x00" + slot[8:8 + length])
    assert stored == want, \
        f"stored CRC ${stored:04X} != oracle ${want:04X} — the engine's " \
        f"table or kernel disagrees with CRC-16/CCITT"


# --------------------------------------------------------------------------
# the power cycle — the user-visible invariant
# --------------------------------------------------------------------------

def test_power_cycle_remembers(runner, tmp_path):
    """save -> off -> on -> the TITLE says so. The whole slice in one drive:
    two room entries, an in-process reload of the same path (the settlement's
    faithful power cycle: unload flushes the .srm, the fresh boot seeds from
    it), and the remembered count read out of the rendered BG3 tilemap AND
    the screenshot — the thing the player actually sees."""
    virgin_boot(runner)
    enter_room(runner)
    back_to_title(runner)
    assert title_visits_digits(runner) == 1
    enter_room(runner)                   # visits = 2, saved at enter
    # power off / power on
    runner.boot_rom(str(ROM))
    assert title_visits_digits(runner) == 2, \
        "the power cycle forgot: title does not show the saved count"
    # the battery seed is still a VALID slot after the reload
    slot = read_slot0(runner)
    length = slot[4] | (slot[5] << 8)
    assert slot[:2] == MAGIC and length == 2
    assert (slot[6] | (slot[7] << 8)) == crc16(
        slot[:6] + b"\x00\x00" + slot[8:10])
    # and the pixels: the VISITS line renders visibly (white glyph pixels
    # in the digit cells' band — the composited check on top of the VRAM
    # words; row 21 -> screen y 167..174 with the 1-line VOFS skew)
    shot = tmp_path / "remembered.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    top = next(y for y in range(h)
               if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w)))
    band = [img.getpixel((x, top + y))
            for y in range(21 * 8 - 1, 22 * 8 - 1) for x in range(17 * 8, 21 * 8)]
    white = sum(1 for p in band if all(c >= 240 for c in p))
    assert white > 8, \
        f"no rendered digits in the VISITS cells ({white} white px)"


# --------------------------------------------------------------------------
# the corruption channel — with the crafted-VALID control
# --------------------------------------------------------------------------

CASES = {
    "crc_flip": (slot_image((1234).to_bytes(2, "little"), crc=None), 0),
    "wrong_version": (slot_image((1234).to_bytes(2, "little"), version=9), 0),
    "wrong_length": (slot_image((1234).to_bytes(2, "little"), length=200), 0),
    "crafted_valid": (slot_image((0x0042).to_bytes(2, "little")), 0x42),
}
# flip one CRC bit AFTER building the otherwise-valid image
_bad = bytearray(CASES["crc_flip"][0])
_bad[6] ^= 0x01
CASES["crc_flip"] = (bytes(_bad), 0)


@pytest.mark.parametrize("name", list(CASES))
def test_srm_corruption_channel(runner, name):
    """Bit rot, a foreign version, an impossible length — each must read as
    EMPTY (dest untouched, count 0). The crafted-VALID control proves the
    channel itself passes the gate, so the three rejections isolate the
    format checks rather than a broken fixture path. wrong_version and
    wrong_length carry ORACLE-VALID CRCs on purpose: they are the cases the
    CRC alone cannot catch, which is why the gate checks all four fields."""
    srm, want = CASES[name]
    crafted_boot(runner, srm)
    got = title_visits_digits(runner)
    assert got == want, f"{name}: title shows {got:#06x}, want {want:#06x}"


def test_srm_overlength_valid_crc_rejected_dest_untouched(runner):
    """The residual channel: magic, version, AND CRC all
    oracle-valid, but the stored length (24) exceeds the 2-byte dest the
    boot load offers. sv_check's slot-capacity gate cannot catch it — 24
    is a legal slot length — so without sv_load's SV_CAP gate the copy
    lands 24 bytes on the 2-byte visits: the first two would render on
    the title and the other 22 would scribble the WRAM beyond the dest.
    The reject is asserted on all three output surfaces: the rendered
    title (0000 — the boot-time 0 stands), the dest bytes themselves,
    and the 22 bytes beyond the dest, where the payload's sentinel
    pattern must NOT have landed."""
    sentinel = b"\xa5\x5a" * 11                      # 22 distinctive bytes
    payload = (1234).to_bytes(2, "little") + sentinel
    assert len(payload) == 24                        # max legal slot length
    crafted_boot(runner, slot_image(payload))
    got = title_visits_digits(runner)
    assert got == 0, \
        f"over-length CRC-valid slot ACCEPTED: title shows {got:#06x} — " \
        f"the dest-capacity gate is gone"
    visits = _sym("US_VISITS")["start"]
    dest = runner.read_bytes(MemoryType.SnesWorkRam, visits, 2 + len(sentinel))
    assert dest[:2] == b"\x00\x00", \
        f"visits dest touched by a rejected slot: {dest[:2]!r}"
    assert dest[2:] != sentinel, \
        "the overrun landed: sentinel bytes found beyond the 2-byte dest"


# --------------------------------------------------------------------------
# pad 2 drives the twin — full state cycle, asserted on OAM bytes
# --------------------------------------------------------------------------

def test_pad2_drives_the_twin(runner):
    """Right, then left, then idle, then the wall clamp — all four states,
    read out of hero2's hardware OAM entry (X low byte + the X9 bit from
    the hi table), never out of px2. Pad 1 is untouched throughout, so the
    bearer's entry doubles as the isolation control."""
    virgin_boot(runner)
    enter_room(runner)

    def hero2_x():
        e = runner.read_bytes(MemoryType.SnesSpriteRam, HERO2_SLOT * 4, 2)
        hi = runner.read_bytes(MemoryType.SnesSpriteRam,
                               512 + HERO2_SLOT // 4, 1)[0]
        x9 = (hi >> ((HERO2_SLOT % 4) * 2)) & 1
        return e[0] | (x9 << 8)

    def bearer_x():
        return runner.read_bytes(MemoryType.SnesSpriteRam,
                                 _sym("ES_O_HERO", "room")["start"] * 4, 1)[0]

    start2, start1 = hero2_x(), bearer_x()
    # NOTE: the release step must name controller_index=1 — a bare
    # frame_step(4) writes port 0's override and leaves port 1's held
    # buttons ACTIVE, which is exactly how this test's first version
    # measured a moving "idle" phase.
    with runner.frame_stepping():
        runner.frame_step(20, controller_index=1, right=True)
        runner.frame_step(4, controller_index=1)
    right2 = hero2_x()
    assert right2 > start2, f"pad-2 right did not move the twin ({start2}->{right2})"
    with runner.frame_stepping():
        runner.frame_step(10, controller_index=1, left=True)
        runner.frame_step(4, controller_index=1)
    left2 = hero2_x()
    assert left2 < right2, f"pad-2 left did not move the twin ({right2}->{left2})"
    with runner.frame_stepping():
        runner.frame_step(10, controller_index=1)
    assert hero2_x() == left2, "idle moved the twin"
    # the wall clamp: far more frames than the distance needs
    with runner.frame_stepping():
        runner.frame_step(160, controller_index=1, left=True)
        runner.frame_step(4, controller_index=1)
    assert hero2_x() == 8, f"the west wall clamp should hold at 8, got {hero2_x()}"
    assert bearer_x() == start1, "pad 2 moved the BEARER — port bleed"


# --------------------------------------------------------------------------
# the pip HUD tracks the count — lit, parked, capped, and pinned
# --------------------------------------------------------------------------

def test_hud_pips_track_visits(runner):
    """Boot from a crafted save of 5 visits, enter (6): exactly six pips
    lit at the declared geometry in the PINNED slots 0..7, the rest parked.
    Then a crafted 200: the row caps at 8. Read from hardware OAM against
    the emitted pin — the H3 delivery's whole point is that these slots are
    the front of the table by declaration."""
    crafted_boot(runner, slot_image((5).to_bytes(2, "little")))
    assert title_visits_digits(runner) == 5
    enter_room(runner)
    oam = runner.read_bytes(MemoryType.SnesSpriteRam, PIPS_SLOT * 4,
                            PIPS_COUNT * 4)
    for i in range(PIPS_COUNT):
        x, y, tile, attr = oam[i * 4: i * 4 + 4]
        assert x == 8 + 10 * i and tile == 2 and attr == 48, \
            f"pip {i} entry ({x},{y},{tile},{attr}) off the declared geometry"
        want_lit = i < 6
        assert (y != 240) == want_lit, \
            f"pip {i} {'parked' if want_lit else 'lit'} at visits=6"
    back_to_title(runner)
    # cap: an absurd saved count lights all eight, no more slots exist
    crafted_boot(runner, slot_image((200).to_bytes(2, "little")))
    enter_room(runner)
    oam = runner.read_bytes(MemoryType.SnesSpriteRam, PIPS_SLOT * 4,
                            PIPS_COUNT * 4)
    lit = sum(1 for i in range(PIPS_COUNT) if oam[i * 4 + 1] != 240)
    assert lit == 8, f"cap failed: {lit} pips lit for visits=201"
