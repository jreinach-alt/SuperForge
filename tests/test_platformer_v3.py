"""V3 run-gates for the platformer flagship — battery-SRAM "continue" from
the title screen (sf_save + sf_scene composed; templates/platformer/main.asm
"v3 SAVE/CONTINUE" design block is the contract under test).

Feature: GAME OVER with coins collected banks them to SRAM slot 0 (magic
"SF", version 1, payload = the 16-bit COINS word); the title then offers
"SELECT: CONTINUE" — a fresh level + 3 lives with the banked coin count
restored. START is always a new game. Invalid slots (virgin, corrupt,
cleared, wrong version, wrong length) fall back to plain new-game
semantics: no CONTINUE line, SELECT inert.

Test surface (real output, never a proxy):
  - BG3 VRAM glyph words for the CONTINUE line (row 17, cols 8-23) and the
    HUD coin counter (row 1, cols 21-25) — presence AND byte-exact absence.
  - SnesSaveRam slot 0 read directly: magic, version, reserved, length,
    payload vs the run's ACTUAL banked coin count, CRC-16 cross-checked
    against an independent bitwise implementation (not the engine's table).
  - Rendered screenshot pixels: the CONTINUE line's white text present /
    absent in its screen band (artifacts in /tmp/e2e_screenshots/s7m4_*).
  - WRAM game state (SCENE/COINS/LIVES/PX) for the restored-vs-fresh runs.

State cycles (full cycle, both directions, not one happy path):
  virgin boot (no .srm) -> no CONTINUE line, SELECT inert, START fresh ->
  game over with a banked coin -> SRAM slot bytes verified -> SAME-session
  title shows CONTINUE -> HARD power cycle (fresh load_rom; the emulator
  flushes/reseeds the .srm at unload per the S7 M2 probe) -> CONTINUE
  renders + SELECT restores the bank (fresh lives, level reloaded: the
  banked coin's tile respawns and is collectable on top of the bank) ->
  another power cycle -> START with a save present stays a fresh run ->
  corrupt .srm -> full fallback (no line, SELECT inert, START fresh) ->
  wrong-version and wrong-length crafted saves (CRC VALID) -> rejected by
  the format gate specifically -> control: a CRAFTED valid save is honored
  end to end (proves the crafted-file channel passes the CRC gate, so the
  version/length rejections are attributable to those gates alone).

CORRUPTION COVERAGE (what is and isn't exercised, and why): the harness
has no SRAM-write API, but the .srm FILE is the battery — Mesen2 seeds
SRAM from it at load and flushes at unload (sf_save.inc battery caveat).
So corruption is induced HONESTLY by editing the flushed .srm between a
neutral-ROM flush and the next platformer boot: a flipped payload byte
(CRC reject), a valid-CRC ver=2 slot (version-gate reject), a valid-CRC
len=4 slot (length-gate reject), and a valid-CRC control (accepted).
That exercises every fallback branch reachable on real hardware at boot.
NOT exercised here: scene_game's late sf_load-return re-check rejecting
AFTER cont_gate passed at title entry — that branch is defense-in-depth
requiring SRAM to mutate between two frames of one session (no honest
mechanism; the return-code semantics it relies on are unit-proven by
tests/test_save.py's corrupt/cleared-slot gates).

.SRM HYGIENE (cross-test contamination): battery SRAM outlives load_rom
AND test modules (process-global emulator). Every platformer module —
this one and the v1/v2 regression bar — establishes its baseline with
bot.virgin_srm (flush-then-delete; a bare unlink is resurrected by the
unload-flush of a still-loaded platformer ROM). Mid-module file crafting
uses bot.flush_srm (neutral-ROM load) for the same reason: editing the
file while a platformer ROM is live would be overwritten by that ROM's
own unload-flush.
"""
import struct
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from tests import _platformer_bot as bot

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SHOTS = Path("/tmp/e2e_screenshots")
WR = MemoryType.SnesWorkRam
SR = MemoryType.SnesSaveRam
VR = MemoryType.SnesVideoRam

SCENE, LIVES, COINS, PX = 0x1804, 0x1800, 0x1802, 0x32
CONTOK = 0x180E                  # main.asm: 1 = slot 0 continuable
SPAWN_X = 24

# v3 save format (main.asm "v3 SAVE/CONTINUE"): slot 0, ver 1, 2-byte payload
SAVE_VER, SAVE_LEN = 1, 2
HDR = 8                          # magic(2) ver(1) rsvd(1) len(2) crc(2)

# BG3 text layer (test-authoring skill): tilemap at VRAM byte $C000,
# cell (tx,ty) at +(ty*32+tx)*2, glyph word $3C00 | (160 + ord(ch) - $20).
BG3_MAP = 0xC000
CONT_STR = "SELECT: CONTINUE"    # printed at x=64,y=136 -> col 8, row 17
CONT_ROW, CONT_COL = 17, 8
COINS_HUD_ROW, COINS_HUD_COL = 1, 21   # sf_print_u16 COINS, #168, #8

# Screenshot band for the CONTINUE line: game y 136-143, the 256x239 Mesen
# frame sits the picture a few rows down -> generous band, clear of
# "PRESS START" (game y 120-127) and of the hill silhouette (dark purple,
# never white).
CONT_BAND = (64, 136, 192, 156)


def _glyph(ch):
    return 0x3C00 | (160 + ord(ch) - 0x20)


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """Independent CRC-16/CCITT (poly $1021, init $FFFF) — bitwise, NOT the
    engine's lookup table, so the cross-check is real."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _craft_slot0(base_srm: bytes, ver: int, payload: bytes) -> bytes:
    """A crafted slot 0 with a CORRECT CRC over header+payload — the
    engine-format bytes, written by the independent implementation."""
    hdr = b"SF" + bytes([ver, 0]) + struct.pack("<H", len(payload))
    crc = crc16_ccitt(hdr + b"\x00\x00" + payload)
    slot = hdr + struct.pack("<H", crc) + payload
    out = bytearray(base_srm)
    out[0:len(slot)] = slot
    return bytes(out)


def _rom():
    p = BUILD / "platformer.sfc"
    assert p.exists(), f"{p} not built — run `make platformer` first"
    return str(p)


def _neutral():
    p = BUILD / "text_test.sfc"
    assert p.exists(), f"{p} not built — run `make testroms` first"
    return p


def _cont_words(r):
    """The 16 BG3 tilemap words where the CONTINUE line renders."""
    raw = r.read_bytes(VR, BG3_MAP + (CONT_ROW * 32 + CONT_COL) * 2,
                       len(CONT_STR) * 2)
    return list(struct.unpack(f"<{len(CONT_STR)}H", raw))


def _hud_coin_words(r):
    raw = r.read_bytes(VR, BG3_MAP + (COINS_HUD_ROW * 32 + COINS_HUD_COL) * 2, 10)
    return list(struct.unpack("<5H", raw))


def _shot(r, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    r.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _white_in_band(img, band):
    x0, y0, x1, y1 = band
    return any(p[0] > 200 and p[1] > 200 and p[2] > 200
               for y in range(y0, y1)
               for p in (img.getpixel((x, y)) for x in range(x0, x1, 2)))


def _press(r, **btn):
    r.set_input(0, **btn)
    r.run_frames(4)
    r.set_input(0)
    r.run_frames(24)


def _st(r):
    s = bot.st(r)
    s["contok"] = r.read_u16(WR, CONTOK)
    return s


def _drive_to_game_over(r):
    """Hold right: coin A (ground col 7) is collected on the first pass,
    then pit 1 eats all three lives (i-frames don't gate pits)."""
    r.set_input(0, right=True)
    deadline = time.time() + 90
    while r.read_u16(WR, SCENE) == 1 and time.time() < deadline:
        r.run_frames(10)
    r.set_input(0)
    r.run_frames(4)


@pytest.fixture(scope="module")
def flow():
    """Drive the whole save/continue lifecycle once on a single runner and
    snapshot every phase; the tests below assert on the snapshots (the
    test_save.py multi-boot pattern — phases are order-dependent by
    nature: a power cycle consumes the previous boot's flush)."""
    r = MesenRunner()
    d = {}
    try:
        # ---- phase A: virgin boot (no .srm) ------------------------------
        bot.virgin_srm(r, _neutral())
        r.load_rom(_rom(), run_seconds=1.5)
        d["virgin"] = dict(magic=bytes(r.read_bytes(WR, 0xE000, 4)),
                           st=_st(r), cont=_cont_words(r),
                           white=_white_in_band(
                               _shot(r, "s7m4_title_no_continue.png"), CONT_BAND))
        _press(r, select=True)                      # must be inert
        d["virgin_select"] = _st(r)
        _press(r, start=True)                       # fresh run still works
        d["virgin_start"] = _st(r)

        # ---- phase B: the save point fires at game over ------------------
        _drive_to_game_over(r)
        d["over"] = dict(st=_st(r),
                         slot0=bytes(r.read_bytes(SR, 0, HDR + SAVE_LEN)))
        _press(r, start=True)                       # over -> title (same boot)
        d["title_after_over"] = dict(st=_st(r), cont=_cont_words(r))

        # ---- phase C: hard power cycle -> CONTINUE ----------------------
        r.load_rom(_rom(), run_seconds=1.5)         # unload flushes the .srm
        d["reset"] = dict(st=_st(r), cont=_cont_words(r),
                          srm_on_disk=bot.SRM_PATH.exists(),
                          white=_white_in_band(
                              _shot(r, "s7m4_title_continue.png"), CONT_BAND))
        _press(r, select=True)
        r.run_frames(20)                            # HUD reprint committed
        d["continued"] = dict(st=_st(r), hud=_hud_coin_words(r))
        r.run_frames(45)                            # past the scene fade-in
        _shot(r, "s7m4_continued_game.png")
        bot.walk_to(r, 54)                          # coin A respawned: bank+1
        d["continued_pickup"] = _st(r)

        # ---- phase D: power cycle -> START ignores the save --------------
        r.load_rom(_rom(), run_seconds=1.5)
        d["reset2"] = dict(st=_st(r))
        _press(r, start=True)
        d["fresh_with_save"] = _st(r)

        # ---- phase E: corrupt .srm (CRC reject) -> full fallback ---------
        bot.flush_srm(r, _neutral())                # materialize the file
        srm = bot.SRM_PATH.read_bytes()
        assert srm[0:2] == b"SF", "flushed .srm lost the save"
        d["srm_base"] = srm
        bad = bytearray(srm)
        bad[HDR] ^= 0xFF                            # one payload byte flipped
        bot.SRM_PATH.write_bytes(bytes(bad))
        r.load_rom(_rom(), run_seconds=1.5)
        d["corrupt"] = dict(st=_st(r), cont=_cont_words(r))
        _press(r, select=True)
        d["corrupt_select"] = _st(r)
        _press(r, start=True)
        d["corrupt_start"] = _st(r)

        # ---- phase F: valid-CRC, wrong VERSION -> format-gate reject -----
        bot.flush_srm(r, _neutral())
        bot.SRM_PATH.write_bytes(
            _craft_slot0(srm, ver=SAVE_VER + 1, payload=struct.pack("<H", 5)))
        r.load_rom(_rom(), run_seconds=1.5)
        d["wrong_ver"] = dict(st=_st(r), cont=_cont_words(r))

        # ---- phase G: valid-CRC, ver ok, wrong LENGTH -> reject ----------
        bot.flush_srm(r, _neutral())
        bot.SRM_PATH.write_bytes(
            _craft_slot0(srm, ver=SAVE_VER, payload=b"\x05\x00\x00\x00"))
        r.load_rom(_rom(), run_seconds=1.5)
        d["wrong_len"] = dict(st=_st(r), cont=_cont_words(r))

        # ---- phase H (control): a CRAFTED valid save is honored ----------
        bot.flush_srm(r, _neutral())
        bot.SRM_PATH.write_bytes(
            _craft_slot0(srm, ver=SAVE_VER, payload=struct.pack("<H", 5)))
        r.load_rom(_rom(), run_seconds=1.5)
        d["ctrl"] = dict(st=_st(r), cont=_cont_words(r))
        _press(r, select=True)
        d["ctrl_continued"] = _st(r)
    finally:
        r.stop()
    return d


EXPECT_CONT = [_glyph(c) for c in CONT_STR]
NO_CONT = [0] * len(CONT_STR)


# -----------------------------------------------------------------------------
# Feature: title continue-offer gating. Output regions: BG3 VRAM glyph words
# (the CONTINUE line cells), rendered screenshot pixels, WRAM scene state.
# State cycle: virgin SRAM (power-on garbage, no .srm).
# -----------------------------------------------------------------------------
def test_fresh_boot_has_no_continue_line(flow):
    v = flow["virgin"]
    assert v["magic"] == b"SFDB", "ROM never booted"
    assert v["st"]["sc"] == 0, "did not land on the title"
    assert v["st"]["contok"] == 0, "virgin SRAM judged continuable"
    assert v["cont"] == NO_CONT, \
        f"CONTINUE line cells not empty on a virgin boot: {v['cont']}"
    assert not v["white"], "white text rendered in the CONTINUE band"


def test_select_inert_without_save_and_start_starts_fresh(flow):
    assert flow["virgin_select"]["sc"] == 0, \
        "SELECT started something with no save present"
    s = flow["virgin_start"]
    assert (s["sc"], s["lv"], s["co"]) == (1, 3, 0), \
        f"START did not begin a fresh run: {s}"


# -----------------------------------------------------------------------------
# Feature: the save point (game over banks coins). Output region: SnesSaveRam
# slot 0 bytes read directly — magic/version/reserved/length, payload vs the
# run's ACTUAL coin count, CRC cross-checked against the independent
# implementation. State cycle: fresh run -> coin collected -> 3 pit deaths.
# -----------------------------------------------------------------------------
def test_game_over_banks_coins_to_sram(flow):
    o = flow["over"]
    assert o["st"]["sc"] == 2 and o["st"]["lv"] == 0, \
        f"pit route never reached game over: {o['st']}"
    banked = o["st"]["co"]
    assert banked > 0, "route banked no coins — the save gate never fired"
    slot = o["slot0"]
    assert slot[0:2] == b"SF", "slot 0 magic missing after game over"
    assert slot[2] == SAVE_VER, f"version byte {slot[2]} != {SAVE_VER}"
    assert slot[3] == 0, "reserved byte not zero"
    assert struct.unpack_from("<H", slot, 4)[0] == SAVE_LEN
    assert struct.unpack_from("<H", slot, HDR)[0] == banked, \
        "payload differs from the run's actual coin count"
    stored = struct.unpack_from("<H", slot, 6)[0]
    expect = crc16_ccitt(slot[0:6] + b"\x00\x00" + slot[HDR:HDR + SAVE_LEN])
    assert stored == expect, f"CRC {stored:#06x} != independent {expect:#06x}"


def test_title_offers_continue_same_session(flow):
    t = flow["title_after_over"]
    assert t["st"]["sc"] == 0 and t["st"]["contok"] == 1
    assert t["cont"] == EXPECT_CONT, \
        f"CONTINUE glyphs wrong after same-session game over: {t['cont']}"


# -----------------------------------------------------------------------------
# Feature: battery persistence + the continue path. Output regions: BG3 VRAM
# glyph words + screenshot pixels (the offer), WRAM game state + BG3 HUD
# digit glyphs (the restored run). State cycle: hard power cycle (fresh
# load_rom = unload-flush + reseed) -> SELECT -> restored game -> pickup on
# the reloaded level.
# -----------------------------------------------------------------------------
def test_hard_reset_offers_continue_and_renders_line(flow):
    rs = flow["reset"]
    assert rs["srm_on_disk"], "no .srm flushed at ROM unload — no battery"
    assert rs["st"]["sc"] == 0 and rs["st"]["contok"] == 1, \
        f"save did not survive the power cycle: {rs['st']}"
    assert rs["cont"] == EXPECT_CONT, \
        f"CONTINUE glyphs wrong after reset: {rs['cont']}"
    assert rs["white"], "CONTINUE line not visible in the rendered frame"


def test_continue_restores_bank_with_fresh_lives_and_level(flow):
    banked = flow["over"]["st"]["co"]
    c = flow["continued"]
    assert c["st"]["sc"] == 1, "SELECT did not enter the game scene"
    assert c["st"]["co"] == banked, \
        f"restored coins {c['st']['co']} != banked {banked} (new-game default would be 0)"
    assert c["st"]["lv"] == 3, "continue did not grant fresh lives"
    assert c["st"]["px"] == SPAWN_X, "continue did not start at spawn"
    digits = f"{banked:05d}"
    assert c["hud"] == [_glyph(ch) for ch in digits], \
        f"HUD coin glyphs do not show the restored bank: {c['hud']}"
    # the level reloaded WITH the bank live: the banked coin's tile
    # respawned and collecting it stacks on the restored count
    assert flow["continued_pickup"]["co"] == banked + 1, \
        f"coin A pickup on the continue run: {flow['continued_pickup']}"


def test_start_with_save_present_is_a_fresh_run(flow):
    assert flow["reset2"]["st"]["contok"] == 1, "save vanished before phase D"
    s = flow["fresh_with_save"]
    assert (s["sc"], s["lv"], s["co"]) == (1, 3, 0), \
        f"START with a save present did not begin a fresh run: {s}"


# -----------------------------------------------------------------------------
# Feature: graceful fallback on invalid slots. Corruption induced honestly
# through the .srm file (the battery) between flush and reseed — see the
# module docstring's CORRUPTION COVERAGE note. Output regions: BG3 VRAM
# (line absent), WRAM scene/contok, fresh-run state after START.
# State cycles: CRC reject / version reject / length reject / valid control.
# -----------------------------------------------------------------------------
def test_corrupt_save_falls_back_to_new_game(flow):
    c = flow["corrupt"]
    assert c["st"]["contok"] == 0, "corrupt slot judged continuable"
    assert c["cont"] == NO_CONT, f"CONTINUE line on a corrupt save: {c['cont']}"
    assert flow["corrupt_select"]["sc"] == 0, "SELECT acted on a corrupt save"
    s = flow["corrupt_start"]
    assert (s["sc"], s["lv"], s["co"]) == (1, 3, 0), \
        f"START after corrupt save not a clean fresh run: {s}"


def test_wrong_version_save_not_continuable(flow):
    """ver=2 with a VALID CRC: sf_save_exists passes, the format gate must
    reject (the control phase proves crafted slots do pass the CRC gate)."""
    w = flow["wrong_ver"]
    assert w["st"]["contok"] == 0, "foreign-version save judged continuable"
    assert w["cont"] == NO_CONT, f"CONTINUE line on a ver-2 save: {w['cont']}"


def test_wrong_length_save_not_continuable(flow):
    """len=4 with a VALID CRC and the right version: the length gate must
    reject (a foreign payload size is not this game's format)."""
    w = flow["wrong_len"]
    assert w["st"]["contok"] == 0, "foreign-length save judged continuable"
    assert w["cont"] == NO_CONT, f"CONTINUE line on a len-4 save: {w['cont']}"


def test_crafted_valid_save_is_honored_end_to_end(flow):
    """Control for the two rejection tests: a crafted slot 0 (ver 1, len 2,
    payload 5, CRC from the independent implementation) must be offered AND
    restore 5 coins — proving the crafting channel itself passes the CRC
    gate, so the version/length rejections above isolate those gates."""
    c = flow["ctrl"]
    assert c["st"]["contok"] == 1, "crafted valid save not offered"
    assert c["cont"] == EXPECT_CONT
    s = flow["ctrl_continued"]
    assert (s["sc"], s["co"], s["lv"]) == (1, 5, 3), \
        f"crafted save not restored: {s}"
