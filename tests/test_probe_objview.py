"""probe_objview — the OBJ viewer ladder, verified on the rendered screen.

Test surface (CLAUDE.md rule 2): the output region is the SCREEN — the
ladder's pixels, the backdrop, and the cycling slot's 32x32 region compared
byte-for-byte against the ladder frame it claims to mirror — plus the two
upload destinations (VRAM CHR, CGRAM) read back against the staged source
blobs. State cycles driven: the full 8-step auto cycle with wraparound, the
idle stretch between steps, and a manual A press (fresh press advances NOW,
a held A does not re-fire, and the press restarts the automatic clock).

Addresses come from the emitted map (build/objv_map/symbol_map.json); the
expected colours come from the STAGED palette blob the ROM .incbin'd — the
same bytes a PROBE_OBJVIEW_PAL= override would swap, so these tests keep
meaning "the screen shows the blob" whichever art is staged.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from machine import Machine, MemoryType  # noqa: E402
from frame_geometry import png_row  # noqa: E402

ROW_Y, CYC_Y, CYC_X, RATE, FRAMES = 80, 144, 112, 16, 8  # the .asm's constants


def _snes8(word: int) -> tuple:
    """BGR555 -> RGB888 the way the PPU/Mesen expand it: bit replication."""
    def ch(c):
        return (c << 3) | (c >> 2)
    return (ch(word & 31), ch((word >> 5) & 31), ch((word >> 10) & 31))


@pytest.fixture(scope="module")
def probe():
    """Build the probe through its own make target; hand back paths + map."""
    r = subprocess.run(["make", "probe-objview"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make probe-objview failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads(
        (SUPERFORGE / "build" / "objv_map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p["start"] for p in
            jmap["scenes"]["probe"]["placements"] + jmap["globals"]}
    staged = SUPERFORGE / "build" / "objview_assets"
    return {
        "rom": str(SUPERFORGE / "build" / "probe_objview.sfc"),
        "syms": syms,
        "chr": (staged / "objview_chr.bin").read_bytes(),
        "pal": (staged / "objview_pal.bin").read_bytes(),
    }


def _pal_words(pal: bytes) -> list:
    return [pal[i] | (pal[i + 1] << 8) for i in range(0, len(pal), 2)]


def _crop(img, x, y, w, h):
    """A screen-space crop: picture coordinates in, PNG coordinates out."""
    return img.crop((x, png_row(y), x + w, png_row(y) + h)).tobytes()


def test_the_ladder_renders_the_staged_blobs_over_gray(probe, tmp_path):
    """Screen pixels: per-frame accent border + tick from the palette blob,
    and the neutral gray everywhere no sprite sits."""
    pal = _pal_words(probe["pal"])
    with Machine(probe["rom"]) as m:
        m.advance(20)
        shot = str(tmp_path / "ladder.png")
        m.screenshot(shot)
        img = Image.open(shot).convert("RGB")
        # the backdrop, sampled far from both sprite bands
        assert img.getpixel((128, png_row(30))) == _snes8(0x318C)
        assert img.getpixel((8, png_row(200))) == _snes8(0x318C)
        for i in range(FRAMES):
            # frame i's 2px border is palette index 3+i; its top-left tick
            # (rows 2..4 inside the frame) is index 12. The BOTTOM-RIGHT
            # border pixel is the true-scale probe: it sits outside the
            # top-left 16x16 quadrant, so a wrong OBSEL size mode (large =
            # 16x16, which truncates every frame identically and slips any
            # relative-region comparison) fails HERE — planted and verified.
            assert img.getpixel((i * 32 + 1, png_row(ROW_Y + 1))) == \
                _snes8(pal[3 + i]), f"frame {i} border colour"
            assert img.getpixel((i * 32 + 3, png_row(ROW_Y + 3))) == \
                _snes8(pal[12]), f"frame {i} corner tick"
            assert img.getpixel((i * 32 + 30, png_row(ROW_Y + 30))) == \
                _snes8(pal[3 + i]), f"frame {i} bottom-right border — " \
                f"the frame must render at full 32x32 scale"
        # and the ladder ends where it claims to: one row below is backdrop
        assert img.getpixel((16, png_row(ROW_Y + 33))) == _snes8(0x318C)
        # power-on fidelity: nothing read a byte that was never written
        m.assert_no_uninitialized_reads()


def test_the_uploads_reach_their_claimed_regions(probe):
    """Destination-region bytes: VRAM CHR and CGRAM equal the staged blobs."""
    s = probe["syms"]
    with Machine(probe["rom"]) as m:
        m.advance(5)
        vram = m.read_bytes(MemoryType.SnesVideoRam,
                            s["ES_V_OBJV_CHR"] * 2, len(probe["chr"]))
        assert vram == probe["chr"], "OBJ CHR in VRAM != the staged blob"
        cg = m.read_bytes(MemoryType.SnesCgRam,
                          s["ES_C_OBJV_PAL"] * 2, len(probe["pal"]))
        assert cg == probe["pal"], "OBJ palette in CGRAM != the staged blob"
        back = m.read_bytes(MemoryType.SnesCgRam, s["ES_C_OBJV_BACK"] * 2, 2)
        assert back == (0x318C).to_bytes(2, "little")


def test_the_cycling_slot_walks_all_eight_frames_at_the_rate(probe, tmp_path):
    """The full auto cycle: any 16-frame window advances the slot exactly
    once, eight windows walk every frame and wrap, and at each step the
    slot's 32x32 SCREEN region equals the ladder frame it claims to show."""
    s = probe["syms"]
    with Machine(probe["rom"]) as m:
        m.advance(20)                       # boot settled, NMI running
        seen = []
        for step in range(FRAMES + 1):      # 9 steps proves the wraparound
            cur = m.read_byte(MemoryType.SnesWorkRam, s["US_CUR"])
            seen.append(cur)
            oam = m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)
            slot = s["ES_O_LADDER"] + 8
            assert oam[slot * 4 + 2] == (cur // 4) * 64 + (cur % 4) * 4, \
                "the cycling slot's OAM tile is not frame cur's"
            shot = str(tmp_path / f"cyc{step}.png")
            m.screenshot(shot)              # costs ONE emulated frame
            img = Image.open(shot).convert("RGB")
            assert _crop(img, CYC_X, CYC_Y, 32, 32) == \
                _crop(img, cur * 32, ROW_Y, 32, 32), \
                f"cycler shows cur={cur} but its pixels != ladder frame {cur}"
            m.advance(RATE - 1)             # the shot's frame + 15 = one period
        assert seen == [(seen[0] + k) % FRAMES for k in range(FRAMES + 1)], \
            f"expected one advance per {RATE}-frame window, saw {seen}"


def test_a_fresh_press_advances_now_and_restarts_the_clock(probe, tmp_path):
    """Input to visible result: a fresh A press advances the slot on that
    frame, holding does not re-fire, and the automatic clock restarts from
    the press — nothing moves for 15 more frames, then one auto step."""
    s = probe["syms"]
    with Machine(probe["rom"]) as m:
        m.advance(20)
        before = m.read_byte(MemoryType.SnesWorkRam, s["US_CUR"])
        m.advance(2, pad1={"a": True})      # press NMI + one held NMI
        after = m.read_byte(MemoryType.SnesWorkRam, s["US_CUR"])
        assert after == (before + 1) % FRAMES, "a fresh press must advance"
        shot = str(tmp_path / "pressed.png")
        m.screenshot(shot)                  # +1 frame: OAM/composite settled
        img = Image.open(shot).convert("RGB")
        assert _crop(img, CYC_X, CYC_Y, 32, 32) == \
            _crop(img, after * 32, ROW_Y, 32, 32), \
            "the press's result must be visible on screen"
        m.advance(13)                       # held(1) + shot(1) + 13 = 15
        assert m.read_byte(MemoryType.SnesWorkRam, s["US_CUR"]) == after, \
            "held A re-fired, or the press did not restart the clock"
        m.advance(1)                        # the 16th NMI after the press
        assert m.read_byte(MemoryType.SnesWorkRam, s["US_CUR"]) == \
            (after + 1) % FRAMES, "the restarted clock's auto step"
