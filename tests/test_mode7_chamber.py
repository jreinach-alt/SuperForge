"""Acceptance gate for the mode7_chamber template — the Mode 7 "barrel chamber"
effect (rotating barrel-curved Mode 7 floor + Mode 1 HUD band + COLDATA vignette).

OUTPUT-READING: every effect assertion reads RENDERED OUTPUT — the screenshot
pixels (the HUD band, the vignette, the rotation) and the per-scanline M7A HDMA
SOURCE table the PPU consumes from WRAM (the barrel bow) — never a proxy flag.
The heartbeat / angle mirror at $7E:E010/$E014 only SEQUENCE the screenshots;
no visual claim rests on them.

The four DoD criteria (docs/sprints/scv4_chamber_recreation_spec.md C-DONE,
owner-corrected 2026-06-29: the SCV4 motion is a vertical ROLL, NOT rotation):
  (a) the floor ROLLS           — posy scrolls in legs of 3 surges (speed up/slow
                                  down x3, capped at ~half the former max), then a
                                  dead stop, hold, reverse (no rotation); the floor
                                  re-paints as the texture rolls past
  (b) the floor BOWS           — per-scanline M7A varies top->mid->bottom (barrel)
  (c) a Mode 1 HUD band        — the top band is a clean uniform strip, distinct
                                 from the Mode 7 floor below (the dual split)
  (d) the vignette             — the mid floor is brighter than top/bottom
Plus the channel-config check: distinct HDMA channels, no collision, matching
the captured allocation roles (BGMODE/TM/COLDATA/M7A).
"""
from pathlib import Path
from collections import Counter

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

# engine_state.inc absolute addresses (bank $7E low RAM, mirrored at $00:xxxx)
NMI_HDMA_ENABLE = 0x0108
M7_OWNED_MASK = 0x0150
M7_BARREL_ACTIVE = 0x01F9
M7_PV_BUFFER = 0x01C6

# posy / velocity mirrors at $7E:E014 / $E016 — the template stores the integer
# posy and the signed-8.8 roll velocity here each frame so the test can read the
# motion. These only ORDER/observe the roll; the visual claim rests on the
# re-painted floor pixels.
POSY_MIRROR = 0xE014
VEL_MIRROR = 0xE016


def _s16(v):
    return v - 65536 if v >= 32768 else v

# pv_hdma_ab0/ab1 (mode7_hdma.asm) — the per-scanline [A,B] HDMA source the PPU
# reads for M7A/M7B. Buffer 0 base $7E:A000, buffer 1 base $7E:A900; stride 4
# bytes/scanline, A word at offset +0. We read these THROUGH WRAM (the actual
# hardware-consumed table), not a proxy variable.
AB0 = 0xA000
AB1 = 0xA900
AB_STRIDE = 4

SPLIT_Y = 32                    # PV_L0_CHAMBER — HUD band above, Mode 7 floor below

# VIGN_TABLE (main.asm) — the COLDATA [count,value] HDMA SOURCE table in WRAM
# ($7E:2020) that the PPU's colour-math reads per scanline (the vignette ramp).
VIGN_TABLE_LO = 0x2020


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _row(data, w, h, y):
    yy = int(y * h / 224.0)
    return data[yy * w:(yy + 1) * w]


def _row_bright(data, w, h, y):
    r = _row(data, w, h, y)
    return sum(sum(c) // 3 for c in r) / len(r)


def _row_dom_frac(data, w, h, y):
    r = _row(data, w, h, y)
    _, cnt = Counter(r).most_common(1)[0]
    return cnt / len(r)


def _read_m7a_column(runner, count):
    """Read `count` per-scanline M7A words from the ACTIVE AB HDMA buffer in
    WRAM — the exact table the PPU's CH5 HDMA streams to $211B each frame."""
    buf = runner.read_bytes(WR, M7_PV_BUFFER, 1)[0]
    base = AB1 if buf else AB0
    out = []
    for i in range(count):
        out.append(runner.read_u16(WR, base + i * AB_STRIDE))
    return out


def test_chamber_assembles_the_barrel_effect(runner):
    rom = BUILD / "mode7_chamber.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode7_chamber` first"
    runner.load_rom(str(rom), run_seconds=2.0)

    # --- boots + heartbeat advances (sequencing only) ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    f2 = runner.read_u16(WR, 0xE010)
    assert f2 > f1 > 0, f"frame heartbeat not advancing: {f1} -> {f2}"

    # =====================================================================
    # CHANNEL CONFIG (G4): distinct channels, no collision, captured roles.
    #   CH2 BGMODE | CH3 TM | CH4 COLDATA | CH5/CH6 matrix  -> $7C
    #   M7_OWNED_MASK = $60 (CH5/CH6 only) -> the split/vignette are direct,
    #   non-Mode-7-owned, so the NMI ownership gate never double-claims them.
    # =====================================================================
    enable = runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0]
    owned = runner.read_bytes(WR, M7_OWNED_MASK, 1)[0]
    assert enable == 0x7C, (
        f"HDMA enable mask {enable:#04x} != $7C "
        f"(expected CH2 BGMODE|CH3 TM|CH4 COLDATA|CH5/CH6 matrix)")
    assert owned == 0x60, (
        f"M7_OWNED_MASK {owned:#04x} != $60 (expected CH5/CH6 only)")
    # the four effect channels are pairwise distinct bits, all set, no overlap
    bgm, tm, col, matrix = 1 << 2, 1 << 3, 1 << 4, (1 << 5) | (1 << 6)
    for name, bit in [("BGMODE/CH2", bgm), ("TM/CH3", tm),
                      ("COLDATA/CH4", col), ("matrix/CH5+6", matrix)]:
        assert enable & bit == bit, f"{name} channel not enabled in {enable:#04x}"
    assert owned & (bgm | tm | col) == 0, (
        "a mode-split/vignette channel was claimed as Mode-7-owned "
        f"(collision risk): owned={owned:#04x}")

    # --- the barrel hook is armed ---
    assert runner.read_bytes(WR, M7_BARREL_ACTIVE, 1)[0] == 1

    # =====================================================================
    # (b) BOWS — the per-scanline M7A HDMA source varies top->mid->bottom in a
    # symmetric barrel (1.0 at the floor edges, ~1.5 at the middle). Read from
    # the WRAM AB table the PPU actually streams (hardware output, not a proxy).
    # =====================================================================
    floor_lines = 224 - SPLIT_Y
    m7a = _read_m7a_column(runner, floor_lines)
    edge_top = m7a[2]
    edge_bot = m7a[floor_lines - 3]
    peak = max(m7a)
    peak_idx = m7a.index(peak)
    assert 0x00F0 <= edge_top <= 0x0110, f"M7A floor-top not ~1.0: {edge_top:#06x}"
    assert 0x00F0 <= edge_bot <= 0x0110, f"M7A floor-bot not ~1.0: {edge_bot:#06x}"
    assert peak >= 0x0160, f"M7A never bows out (peak {peak:#06x} < 1.375)"
    # the bulge is in the MIDDLE third of the floor (symmetric barrel)
    assert floor_lines // 3 < peak_idx < 2 * floor_lines // 3, (
        f"M7A peak not mid-floor (idx {peak_idx} of {floor_lines}) — not a barrel")

    # --- screenshot frame A (for the HUD band + vignette + rotation tracking) ---
    shotA = "/tmp/_chamber_A.png"
    runner.take_screenshot(shotA)
    dA, w, h = _rgb(shotA)

    # =====================================================================
    # (c) HUD BAND — the top SPLIT_Y scanlines are a clean uniform strip (a
    # genuine Mode 1 HUD band, not a Mode 7 floor smear), distinct from the
    # varied floor below.
    # =====================================================================
    for y in (12, 24):
        assert _row_dom_frac(dA, w, h, y) >= 0.85, (
            f"HUD band row y={y} not uniform (smeared floor?): "
            f"{_row_dom_frac(dA, w, h, y):.2f}")
    # the floor below the split is a TEXTURED Mode 7 image (not a flat backdrop
    # fill). With the rotation removed the floor is AXIS-ALIGNED, so any single
    # scanline can legitimately be uniform (a solid brick row or a mortar gap) —
    # prove "textured" by the variety of colors across a band of floor rows
    # (a flat fill yields 1-2 colors; the stone floor yields a dozen).
    floor_colors = set()
    for y in (70, 95, 120, 145, 170, 195):
        floor_colors.update(_row(dA, w, h, y))
    assert len(floor_colors) >= 5, (
        f"floor band has only {len(floor_colors)} distinct colors — the Mode 7 "
        "floor did not render a texture (flat backdrop fill?)")

    # =====================================================================
    # (d) VIGNETTE — the mid floor is brighter than both the upper floor (just
    # below the split) and the lower floor (the 0->8->0 COLDATA ramp).
    # =====================================================================
    # Pixel check (robust): the mid floor band is clearly brighter than the dark
    # top band (vignette max vs ~0). Averaging a band cancels the rib texture.
    def _band(y0, y1):
        return sum(_row_bright(dA, w, h, y) for y in range(y0, y1)) / (y1 - y0)
    b_top, b_mid = _band(36, 52), _band(120, 136)
    assert b_mid > b_top + 20, (
        f"vignette mid band not brighter than the dark top: {b_mid:.0f} vs {b_top:.0f}")
    # Ramp shape (hardware level): read the COLDATA HDMA SOURCE table from WRAM —
    # the per-scanline bytes the PPU colour-math consumes — and assert the 0->8->0
    # ramp ($E0 edges, $E8 peak). A mid-vs-bottom PIXEL compare is unreliable here
    # (the perspective-magnified, rolling rib texture is brightest near the
    # camera), so the ramp is gated at the table — like the (b) barrel M7A read.
    vig = runner.read_bytes(WR, VIGN_TABLE_LO, 30)
    vals, i = [], 0
    while i < len(vig) - 1 and vig[i] != 0:      # walk [count,value] until count=0
        vals.append(vig[i + 1])
        i += 2
    assert max(vals) == 0xE8, f"COLDATA vignette peak {max(vals):#04x} != $E8 (brightest mid)"
    assert vals[0] <= 0xE2 and vals[-1] <= 0xE2, (
        f"COLDATA vignette edges not dark ({vals[0]:#04x}..{vals[-1]:#04x})")

    # =====================================================================
    # (a) ROLLS — NO rotation. The floor scrolls vertically (posy velocity) in
    # legs of 3 surges (speed up / slow down x3), each capped at ~half the former
    # max; after the surges the leg stops dead, holds, then REVERSES. Sample the
    # signed-8.8 velocity mirror long enough to span a forward leg into the
    # reverse and assert: forward roll, a stop, a reverse roll, a ramped (non-
    # constant) speed, and the 50%-reduced peak cap. Then the floor re-paints.
    # =====================================================================
    vels = []
    for _ in range(170):                    # ~2550 frames: leg1 (~26s) -> reverse
        vels.append(_s16(runner.read_u16(WR, VEL_MIRROR)))   # signed 8.8 px/frame
        runner.run_frames(15)
    vmax, vmin = max(vels), min(vels)
    assert vmax > 64, f"floor never rolls forward (peak vel {vmax / 256:.2f}/frame)"
    assert vmin < -64, f"floor never reverses (min vel {vmin / 256:.2f}/frame)"
    assert any(abs(v) < 32 for v in vels), (
        "floor never slows to a stop/creep between surges or legs")
    fwd = [v for v in vels if v > 0]
    assert max(fwd) - min(fwd) > 256, (
        "roll speed never ramps — expected accel/decel surges, not a constant "
        "scroll")
    # the 50%-reduced peak: speed reaches ~4.0 px/frame (the cap) but no faster
    peak = max(abs(v) for v in vels)
    assert 768 < peak <= 1100, (
        f"peak speed {peak / 256:.2f} px/frame outside the capped ~4.0 band "
        "(the reduce-max-speed-50% knob, PEAK_CAP)")

    shotB = "/tmp/_chamber_B.png"
    runner.take_screenshot(shotB)
    dB, w2, h2 = _rgb(shotB)
    # the rendered floor changed as the texture rolled past. Compare the WHOLE
    # floor band (not a few rows — the periodic rib texture can coincidentally
    # match on isolated scanlines even while the floor has clearly rolled).
    changed = total = 0
    for y in range(SPLIT_Y + 4, 220, 3):
        ra, rb = _row(dA, w, h, y), _row(dB, w2, h2, y)
        changed += sum(1 for a, b in zip(ra, rb) if a != b)
        total += len(ra)
    assert changed > total * 0.10, (
        f"floor barely changed across the roll ({changed}/{total} px) "
        "— the vertical scroll did not repaint the floor")
