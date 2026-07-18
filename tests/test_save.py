"""Run-gate for the battery-SRAM save/load macros (sf_save.inc).

Feature under test: sf_save / sf_load / sf_save_exists / sf_save_clear
over engine/save_load_engine.asm, linked with lorom_sram.cfg, including
battery persistence across a HARD power cycle.

Test surface (real output, never a proxy):
  - SnesSaveRam bytes read DIRECTLY: slot 0 header (magic "SF", version,
    length) + payload byte-for-byte, the CRC-16 cross-checked against an
    INDEPENDENT bitwise Python implementation (not the engine's table),
    the corrupted slot-1 byte, the cleared slot-2 magic.
  - WRAM destination buffers: $7E:1A00 (restored payload after reset),
    $7E:1B00 (same-boot round trip), $7E:1C00/$1C80 ($EE sentinels that
    a REJECTED load must not clobber).
  - Debug-region result codes mirrored by the ROM (boot discriminator,
    per-call return values).

State cycles exercised (full cycle, not one happy path):
  virgin -> save -> exists(1) -> load(ok) -> corrupt -> load REJECTED
  ($FFFE, dest untouched) -> exists(0) -> save -> clear -> exists(0) ->
  load($FFFF, dest untouched); then HARD RESET — a fresh load_rom is a
  power cycle: the emulator flushes SRAM to <home>/Saves/save_test.srm
  when the old ROM instance unloads and seeds the new instance from it
  (verified by the S7 M2 probe; within a run the live SnesSaveRam region
  is the evidence surface, the .srm is only flushed at unload) — then
  exists(1) -> load restores the payload byte-identically, while the
  corrupt and cleared slots STAY rejected across the reset.

Mesen-persistence note (why no subprocess driver is needed): Mesen2's
in-process LoadRom unloads the previous ROM first, which writes the .srm;
the fresh instance then loads it back. Same path = same .srm = real
power-cycle semantics inside one process. Virgin SRAM (no .srm on disk)
is power-on GARBAGE, not zeros — the fixture deletes any stale .srm and
the assertions never assume zeroed SRAM.
"""
import struct
from pathlib import Path

import pytest

from infrastructure.test_harness import mesen_runner
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SR = MemoryType.SnesSaveRam

SLOT_SIZE = 0x0800
HDR = 8                                   # magic(2) version(1) rsvd(1) len(2) crc(2)
PAYLOAD_LEN = 64
PATTERN = bytes((3 + 7 * i) & 0xFF for i in range(PAYLOAD_LEN))
SENTINEL = b"\xEE" * PAYLOAD_LEN
CORRUPT_OFS = 5                           # slot-1 payload byte the ROM flips

SRM_PATH = Path(mesen_runner._DEFAULT_HOME_DIR) / "Saves" / "save_test.srm"


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """Independent CRC-16/CCITT (poly $1021, init $FFFF, no reflection) —
    bitwise, NOT the engine's lookup table, so the cross-check is real."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _rom() -> str:
    p = BUILD / "save_test.sfc"
    assert p.exists(), f"{p} not built — run `make save_test` (or `make testroms`) first"
    return str(p)


def _u16(r, addr):
    return r.read_u16(WR, addr)


def _snapshot(r):
    return {
        "magic": bytes(r.read_bytes(WR, 0xE000, 4)),
        "complete": _u16(r, 0xE008),
        "dbg": {ofs: _u16(r, 0xE000 + ofs) for ofs in range(0x10, 0x32, 2)},
        "sram0": bytes(r.read_bytes(SR, 0x0000, HDR + PAYLOAD_LEN)),
        "sram1": bytes(r.read_bytes(SR, 0x0800, HDR + PAYLOAD_LEN)),
        "sram2_hdr": bytes(r.read_bytes(SR, 0x1000, HDR)),
        "w1800": bytes(r.read_bytes(WR, 0x1800, PAYLOAD_LEN)),
        "w1A00": bytes(r.read_bytes(WR, 0x1A00, PAYLOAD_LEN)),
        "w1B00": bytes(r.read_bytes(WR, 0x1B00, PAYLOAD_LEN)),
        "w1C00": bytes(r.read_bytes(WR, 0x1C00, PAYLOAD_LEN)),
        "w1C80": bytes(r.read_bytes(WR, 0x1C80, PAYLOAD_LEN)),
    }


@pytest.fixture(scope="module")
def boots():
    """Boot the ROM twice in one process: run 1 on virgin SRAM (any stale
    .srm deleted first), run 2 as a hard power cycle of the same cart."""
    if SRM_PATH.exists():
        SRM_PATH.unlink()
    r = MesenRunner()
    try:
        r.load_rom(_rom(), run_seconds=1.5)
        run1 = _snapshot(r)
        r.load_rom(_rom(), run_seconds=1.5)        # HARD RESET (power cycle)
        run2 = _snapshot(r)
        run2["srm_on_disk"] = SRM_PATH.exists()    # flushed at run-1 unload
    finally:
        r.stop()
    return run1, run2


def test_both_boots_ran_to_completion(boots):
    for i, run in enumerate(boots, 1):
        assert run["magic"] == b"SFDB", f"run {i} never booted"
        assert run["complete"] == 1, f"run {i} crashed before completing"
    assert boots[0]["dbg"][0x30] == 1, "run 1 did not take the first-boot path"
    assert boots[1]["dbg"][0x30] == 2, "run 2 did not take the second-boot path"


def test_virgin_sram_has_no_valid_save(boots):
    run1, _ = boots
    assert run1["dbg"][0x10] == 0, "virgin SRAM answered sf_save_exists=1"
    # garbage never passes the magic+CRC gate: no-save or corrupt, never a load
    assert run1["dbg"][0x12] in (0xFFFF, 0xFFFE), hex(run1["dbg"][0x12])


def test_save_writes_slot_header_and_payload_to_sram(boots):
    """Destination-region evidence: the SRAM slot bytes themselves."""
    run1, _ = boots
    slot = run1["sram0"]
    assert run1["dbg"][0x14] == 0, "sf_save did not return success"
    assert slot[0:2] == b"SF", "slot 0 magic missing"
    assert slot[2] == 1, "version byte not stored"
    assert slot[3] == 0, "reserved byte not zero"
    assert struct.unpack_from("<H", slot, 4)[0] == PAYLOAD_LEN
    assert slot[HDR:HDR + PAYLOAD_LEN] == PATTERN, "payload bytes differ from source"
    # CRC cross-check against the independent implementation (CRC field
    # zeroed during computation, exactly as the engine does it)
    stored_crc = struct.unpack_from("<H", slot, 6)[0]
    expect = crc16_ccitt(slot[0:6] + b"\x00\x00" + slot[HDR:HDR + PAYLOAD_LEN])
    assert stored_crc == expect, f"stored CRC {stored_crc:#06x} != independent {expect:#06x}"


def test_same_boot_round_trip(boots):
    run1, _ = boots
    assert run1["dbg"][0x16] == 1, "exists != 1 after save"
    assert run1["dbg"][0x18] == PAYLOAD_LEN, "load return != payload length"
    assert run1["w1B00"] == PATTERN, "round-trip payload differs"


def test_corrupt_slot_load_rejects_and_preserves_dest(boots):
    run1, _ = boots
    assert run1["dbg"][0x1A] == 0, "slot-1 save failed"
    # the corruption really landed in SRAM (exactly one byte flipped)
    pay1 = run1["sram1"][HDR:HDR + PAYLOAD_LEN]
    expected = bytearray(PATTERN)
    expected[CORRUPT_OFS] ^= 0xFF
    assert pay1 == bytes(expected), "slot-1 payload not corrupted as scripted"
    # the load REJECTED ...
    assert run1["dbg"][0x1C] == 0xFFFE, hex(run1["dbg"][0x1C])
    # ... and did not clobber a single destination byte
    assert run1["w1C00"] == SENTINEL, "rejected load wrote into its destination"
    # exists agrees: a corrupt slot is not a save
    assert run1["dbg"][0x1E] == 0


def test_clear_invalidates_slot(boots):
    run1, _ = boots
    assert run1["dbg"][0x20] == 1, "slot-2 exists != 1 after save"
    assert run1["dbg"][0x22] == 0, "sf_save_clear return != 0"
    assert run1["dbg"][0x24] == 0, "slot-2 exists != 0 after clear"
    assert run1["dbg"][0x26] == 0xFFFF, "load of cleared slot != no-save"
    assert run1["w1C80"] == SENTINEL, "no-save load wrote into its destination"
    assert run1["sram2_hdr"][0:2] == b"\x00\x00", "cleared magic still in SRAM"


def test_hard_reset_restores_saved_payload(boots):
    """The battery story: a fresh load_rom is a power cycle; slot 0 must
    come back byte-identical."""
    _, run2 = boots
    assert run2["srm_on_disk"], "no .srm flushed at ROM unload — no battery"
    assert run2["dbg"][0x10] == 1, "save did not survive the power cycle"
    assert run2["dbg"][0x12] == PAYLOAD_LEN, hex(run2["dbg"][0x12])
    assert run2["w1A00"] == PATTERN, "restored payload differs from what was saved"
    # the slot bytes themselves survived the flush+reload round trip
    assert run2["sram0"][0:2] == b"SF"
    assert run2["sram0"][HDR:HDR + PAYLOAD_LEN] == PATTERN


def test_corrupt_and_cleared_slots_stay_rejected_after_reset(boots):
    _, run2 = boots
    assert run2["dbg"][0x28] == 0, "corrupt slot answered exists=1 after reset"
    assert run2["dbg"][0x2A] == 0, "cleared slot answered exists=1 after reset"
