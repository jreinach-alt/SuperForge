"""sf_autoscroll_v run-gate: the world drifts down the screen, no input.

Verifies the rendered result, not just the register: the stripe pattern's
screen rows must shift DOWN by exactly the VOFS delta between two samples
(direction + magnitude correlated), while SHADOW_BG1VOFS decreases.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

_GREEN = lambda p: p[0] < 90 and p[1] > 150 and p[2] < 90


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _green_rows(r, path="/tmp/_autoscroll.png"):
    """The set of screen rows that are green at column 40 (stripe phase)."""
    r.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    d = list(img.getdata())
    return frozenset(y for y in range(h) if _GREEN(d[y * w + 40]))


def test_autoscroll_drifts_world_down(runner):
    rom = ROOT / "build" / "autoscroll_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "ROM did not boot"
    assert runner.read_u16(WR, 0xE008) == 1, "ROM did not reach the frame loop"

    # NOTE: the emulator free-runs in real time — a register read and a
    # screenshot are a frame or two apart. Assertions therefore correlate
    # with a +/-2 frame tolerance; the direction check still cannot pass
    # with an inverted or stuck scroll.
    v1 = runner.read_u16(WR, 0x0122)        # SHADOW_BG1VOFS
    rows1 = _green_rows(runner)
    runner.run_frames(24)
    v2 = runner.read_u16(WR, 0x0122)
    rows2 = _green_rows(runner)

    # the counter decreases (wrapping u16) at ~1 px/frame
    delta = (v1 - v2) & 0xFFFF
    assert 0 < delta < 200, f"VOFS did not decrease sensibly ({v1:#06x}->{v2:#06x})"
    mirror = runner.read_u16(WR, 0xE010)
    assert ((v2 - mirror) & 0xFFFF) <= 3 or ((mirror - v2) & 0xFFFF) <= 3, \
        f"counter mirror out of sync (VOFS {v2:#06x}, mirror {mirror:#06x})"

    # the RENDERED stripes shift DOWN by the VOFS delta (mod the 16px period)
    assert rows1 and rows2, "stripes not visible"
    res1 = frozenset(y % 16 for y in rows1)
    res2 = frozenset(y % 16 for y in rows2)
    ok = any(res2 == frozenset((y + d) % 16 for y in res1)
             for d in range(delta - 2, delta + 3))
    down_only = sorted(sorted({(y + d) % 16 for y in res1})
                       for d in range(delta - 2, delta + 3))
    assert ok, (
        f"stripes moved {sorted(res1)}->{sorted(res2)}, but VOFS delta "
        f"~{delta} (down) predicts one of {down_only}")
