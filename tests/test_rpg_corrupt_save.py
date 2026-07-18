"""Bad-CRC corrupt-save fallback for the rpg boot-load hook (audit-1 L3).

The rpg oracle's absent_save_boots_fresh_overworld scenario (formerly
corrupt_save_falls_back_to_fresh_overworld) only exercises ABSENT/garbage SRAM:
fresh_sram deletes the .srm, so the boot SRAM is power-on garbage that fails the
'SF' MAGIC gate before the CRC is ever checked. That is a real path, but its old
name over-claimed — it does NOT test a VALID-magic / BAD-CRC record, which is
the discriminating gate sf_save_exists actually guards.

This test closes that gap HONESTLY (the platformer-v3 phase-E pattern):
  1. Boot virgin, walk to the SAVE POINT + A -> the ROM writes a VALID engine
     save (magic 'SF' + version + length + CRC-16 + {town, tx, ty} payload).
  2. Flush the live SRAM to the .srm (neutral-ROM load), read it back, FLIP ONE
     PAYLOAD BYTE. The 'SF' magic stays intact; the stored CRC no longer matches
     the payload — a corrupt save, not an absent one.
  3. Reload the rpg. The boot-load hook (try_boot_load -> sf_save_exists) must
     REJECT the bad-CRC record at the CRC gate and fall back to a FRESH
     OVERWORLD, exactly as if there were no save.

Test surface (real output, never a proxy):
  - The corruption is verified to have landed: the .srm magic is still 'SF' and
    the flipped payload byte differs from the saved value (the bad-CRC record is
    genuinely on disk).
  - The REJECTION is read from the live SRAM destination (magic intact, payload
    byte still flipped — the boot did NOT rewrite the slot) AND from the rendered
    result: the scene-state word == overworld (not town) and the Mode 7 grass
    floor renders (green pixel at y=160). A boot that wrongly ACCEPTED the bad
    record would land in the town (state==town, gray cobble floor).

State cycle exercised: virgin -> save(valid) -> corrupt-on-disk(bad CRC) ->
reboot rejects -> fresh overworld. This is the CRC-reject transition the
garbage-SRAM oracle scenario structurally cannot reach (garbage dies at the
magic gate first).

Skips cleanly when build/rpg.sfc + the neutral ROM are absent.
"""

from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SR = MemoryType.SnesSaveRam

SCENE_MIRROR = 0xE016          # sf_state_mirror: 0 overworld / 1 town / 2 battle
HDR = 8                        # magic(2) ver(1) rsvd(1) len(2) crc(2)
PAYLOAD_FLIP_OFS = HDR + 0     # flip the first payload byte (scene id) — magic intact
SAVED_SCENE = 1                # the save records scene=town

# Mode 7 grass-floor pixel (matches the oracle's boots_into_..._overworld assert
# at (128,160) rgb [37,111,49] tol 50). On a town boot this pixel is gray cobble.
FLOOR_X, FLOOR_Y = 128, 160
FLOOR_RGB, FLOOR_TOL = (37, 111, 49), 50
E2E = Path("/tmp/e2e_screenshots")


def _px(path, x, y):
    return Image.open(path).convert("RGB").load()[x, y]


pytestmark = pytest.mark.skipif(
    not (BUILD / "rpg.sfc").exists() or not (BUILD / "text_test.sfc").exists(),
    reason="rpg.sfc / text_test.sfc not built "
           "(dryrun_split.sh + make rpg + make testroms)",
)


def _rom():
    return str(BUILD / "rpg.sfc")


def _neutral():
    return BUILD / "text_test.sfc"


# The save-point drive (lifted verbatim from the oracle's
# save_at_save_point_writes_sram scenario): A to enter town, settle the wipe,
# 6 left + 2 down to the tile east of the save point (10,18), A to save.
_SAVE_STEPS = [
    ([], 14), (["a"], 2), ([], 32),
    (["left"], 2), ([], 8), (["left"], 2), ([], 8), (["left"], 2), ([], 8),
    (["left"], 2), ([], 8), (["left"], 2), ([], 8), (["left"], 2), ([], 8),
    (["down"], 2), ([], 8), (["down"], 2), ([], 8),
    (["a"], 2), ([], 14),
]


def _btn(names):
    return {n: True for n in names}


def _drive(r, steps):
    for names, frames in steps:
        r.set_input(0, **_btn(names))
        r.run_frames(frames)
    r.set_input(0)
    r.run_frames(2)


def test_bad_crc_save_rejected_boots_fresh_overworld():
    from _srm import virgin_srm, flush_srm, srm_path

    r = MesenRunner()
    try:
        # ---- 1. virgin boot -> walk to save point -> write a VALID save ------
        virgin_srm(r, "rpg.sfc", _neutral())
        r.load_rom(_rom(), run_seconds=1.0)
        _drive(r, _SAVE_STEPS)
        # the live SRAM now holds a valid slot 0 (the oracle save scenario
        # asserts magic 'SF' + CRC + payload here)
        live = bytes(r.read_bytes(SR, 0, HDR + 8))
        assert live[0:2] == b"SF", f"save point did not write a valid record: {live[:8]!r}"

        # ---- 2. flush to disk, FLIP ONE PAYLOAD BYTE (magic intact, CRC bad) --
        flush_srm(r, _neutral())                       # materialize the .srm
        p = srm_path("rpg.sfc")
        srm = bytearray(p.read_bytes())
        assert srm[0:2] == b"SF", "flushed .srm lost the save magic"
        saved_byte = srm[PAYLOAD_FLIP_OFS]
        srm[PAYLOAD_FLIP_OFS] ^= 0xFF                  # corrupt one payload byte
        assert srm[0:2] == b"SF", "corruption clobbered the magic (must stay valid)"
        assert srm[PAYLOAD_FLIP_OFS] != saved_byte, "flip did not change the byte"
        p.write_bytes(bytes(srm))

        # ---- 3. reload -> the bad-CRC record must be REJECTED ----------------
        r.load_rom(_rom(), run_seconds=1.0)
        r.run_frames(14)

        # rejection from the SRAM destination: the slot was NOT rewritten — the
        # magic is still 'SF' and our flipped byte is still flipped (a boot that
        # re-saved would overwrite it).
        after = bytes(r.read_bytes(SR, 0, HDR + 8))
        assert after[0:2] == b"SF", "SRAM magic vanished after reboot"
        assert after[PAYLOAD_FLIP_OFS] == (saved_byte ^ 0xFF), \
            "boot rewrote the corrupted slot — it should have left the bad record untouched"

        # rejection from the rendered result: fresh OVERWORLD, not the town the
        # corrupt record encoded. State mirror + the Mode 7 grass floor pixel.
        state = r.read_u16(WR, SCENE_MIRROR)
        assert state == 0, (
            f"bad-CRC save was ACCEPTED — booted state {state} "
            f"({'town' if state == 1 else 'battle' if state == 2 else '?'}), "
            "expected overworld (0). The CRC gate failed to reject it.")

        # rendered grass floor: green on the overworld, gray cobble in the town.
        E2E.mkdir(parents=True, exist_ok=True)
        shot = E2E / "rpg_bad_crc_fresh_overworld.png"
        r.take_screenshot(str(shot))
        got = _px(shot, FLOOR_X, FLOOR_Y)
        assert all(abs(g - w) <= FLOOR_TOL for g, w in zip(got, FLOOR_RGB)), (
            f"floor pixel ({FLOOR_X},{FLOOR_Y})={got} not the overworld grass "
            f"{FLOOR_RGB} +/-{FLOOR_TOL} — the bad-CRC save left the player in the town.")
    finally:
        r.stop()
