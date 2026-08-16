"""The two-same-register VBlank probe: two claims on ONE PPU register, WIRED
to ASM, booted, and verified on rendered output.

`allocate._register_exclusive` relaxes register exclusivity for VBlank-phase
claims, on the argument that VBlank GP-DMAs are serialised queue entries.
Taken alone that argument is allocator-level only —
`test_second_vblank_vmdatal_consumer_composes` proves the DECLARATION
allocates, not that the composition runs. This probe closes the gap:

  * two VBlank claims both driving VMDATAL (vba -> targ_a, vbb -> targ_b),
    each fired every NMI on its own allocator-emitted channel;
  * an active-phase COLDATA HDMA pinned to channel 0 = vba's channel, so the
    GP-DMA provably time-shares a LIVE HDMA channel's $43xx register file
    (re-armed after the fires, scene_mgr-style);
  * rendered checks: both VRAM targets byte-exact against their patterns,
    and the COLDATA band split present on screen;
  * a falsification switch (skip claim B's fire + rewipe) proving the
    B-target assertion CAN fail — a test that cannot fail is not evidence;
  * the negative: pinning both VBlank claims to ONE channel must refuse
    (the channel-occupancy teeth the relaxation left in place).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

sys.path.insert(0, str(SUPERFORGE / "tests"))
from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

VR, WR = MemoryType.SnesVideoRam, MemoryType.SnesWorkRam

GAME = SUPERFORGE / "vendor" / "probes" / "probe_vb2reg"
ASM = SUPERFORGE / "vendor" / "probes" / "probe_vb2reg.asm"

PATTERN_A = b"".join((0xA500 + i).to_bytes(2, "little") for i in range(256))
PATTERN_B = b"".join((0xB700 + i).to_bytes(2, "little") for i in range(256))
WIPE = b"\xEE\xEE" * 256


def build(outdir: Path, game: Path = GAME) -> Path:
    """allocate -> no_literals -> ca65 -> ld65, like the probe Makefile rules."""
    mapdir = outdir / "map"
    for cmd in (
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(game), "--out", str(mapdir)],
        # NOTE: no `--partial-files` — this survives only
        # because probe_vb2reg has ZERO rom claims, so the whole-composition
        # rom-backing pass has nothing to report. Add a [[claims.rom]] to the
        # probe and this build helper fails for an unrelated reason.
        [sys.executable, str(SUPERFORGE / "allocator" / "no_literals.py"),
         "--map", str(mapdir / "symbol_map.json"), str(ASM)],
        ["ca65", "--cpu", "65816", "-I", str(mapdir),
         "-I", str(SUPERFORGE / "vendor" / "rom"),
         "-o", str(outdir / "probe.o"), str(ASM)],
        ["ld65", "-C", str(SUPERFORGE / "vendor" / "rom" / "lorom_32k.cfg"),
         "-o", str(outdir / "probe.sfc"), str(outdir / "probe.o")],
    ):
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, f"{cmd[:2]} failed:\n{r.stdout}\n{r.stderr}"
    return outdir / "probe.sfc"


@pytest.fixture(scope="module")
def booted(tmp_path_factory):
    out = tmp_path_factory.mktemp("vb2reg")
    rom = build(out)
    jmap = json.loads((out / "map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in jmap["scenes"]["probe"]["placements"]}
    chans = {c["name"]: c["ch"]
             for c in jmap["scenes"]["probe"]["channels"]}
    runner = MesenRunner()
    runner.boot_rom(str(rom), frames=60)
    runner.debug_break()
    runner.frame_step(3)
    yield runner, syms, chans
    runner.debug_resume()
    runner.stop()


def test_allocator_accepts_and_gives_each_claim_its_own_channel(booted):
    """The relaxation's positive at the map level: two VMDATAL VBlank claims
    allocate, on DISTINCT channels, with the active COLDATA claim pinned to
    channel 0 sharing vba's channel across phases (the time-share case)."""
    _, _, chans = booted
    assert chans["vba"] != chans["vbb"], chans
    assert chans["vbc"] == 0 and chans["vba"] == 0, (
        f"the probe is built to time-share channel 0 across phases; "
        f"got {chans}")


def test_both_same_register_vblank_uploads_land_every_frame(booted):
    """THE claim the relaxation rests on, measured end-to-end: with both
    claims fired serially in one NMI, both VRAM targets hold their full
    patterns byte-exactly (the targets were wiped to $EEEE at boot, so a
    stale byte cannot fake a delivery)."""
    runner, syms, _ = booted
    ta = runner.read_bytes(VR, syms["ES_V_TARG_A"]["start"] * 2, 512)
    tb = runner.read_bytes(VR, syms["ES_V_TARG_B"]["start"] * 2, 512)
    assert ta == PATTERN_A, f"target A corrupt: {ta[:8].hex()}..."
    assert tb == PATTERN_B, f"target B corrupt: {tb[:8].hex()}..."


def test_time_shared_active_hdma_still_renders(booted, tmp_path):
    """The COLDATA HDMA on the clobbered-then-re-armed channel renders its
    two bands every frame: blue upper band, red lower band, sampled well
    inside each band."""
    from PIL import Image
    runner, _, _ = booted
    shot = tmp_path / "bands.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    top = D.content_top(img)        # measured, not a hardcoded 7
    blue = img.getpixel((128, top + 56))
    red = img.getpixel((128, top + 168))
    assert blue[2] > 200 and blue[0] < 50, f"upper band not blue: {blue}"
    assert red[0] > 200 and red[2] < 50, f"lower band not red: {red}"


def test_the_target_assertion_can_fail(booted):
    """Falsification: stop firing claim B and rewipe — target B must read
    back as the wipe pattern (the exact state the previous test's assertion
    rejects), while target A keeps landing. Then restore and confirm B
    recovers. A rendered assertion that stayed green here would be
    worthless."""
    runner, syms, _ = booted
    runner.write_bytes(WR, syms["US_SKIP_B"]["start"], bytes([1]))
    runner.write_bytes(WR, syms["US_REWIPE"]["start"], bytes([1]))
    runner.frame_step(3)
    ta = runner.read_bytes(VR, syms["ES_V_TARG_A"]["start"] * 2, 512)
    tb = runner.read_bytes(VR, syms["ES_V_TARG_B"]["start"] * 2, 512)
    assert ta == PATTERN_A, "target A stopped landing during the negative"
    assert tb == WIPE, (
        f"target B should hold the wipe with its fire skipped: {tb[:8].hex()}")
    runner.write_bytes(WR, syms["US_SKIP_B"]["start"], bytes([0]))
    runner.frame_step(2)
    tb = runner.read_bytes(VR, syms["ES_V_TARG_B"]["start"] * 2, 512)
    assert tb == PATTERN_B, "target B did not recover after the negative"


def test_pinning_both_vblank_claims_to_one_channel_refuses(tmp_path):
    """The teeth the relaxation kept: two VBlank claims may share a REGISTER
    but never a CHANNEL in overlapping bands — pinning both to channel 1
    must stop the build (channel 0 stays with the active COLDATA pin)."""
    import shutil
    bad = tmp_path / "game"
    shutil.copytree(GAME, bad)
    for feat, name in (("vb_a", "vba"), ("vb_b", "vbb")):
        f = bad / feat / "feature.toml"
        src = f.read_text().replace(
            'phase = "vblank"', 'phase = "vblank"\nchannel = 1')
        f.write_text(src)
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(bad), "--out", str(tmp_path / "out")],
        capture_output=True, text=True)
    assert r.returncode != 0, "same-channel pin was ACCEPTED — occupancy gone"
    assert "channel contention" in r.stderr + r.stdout

