"""OPT curve-variety render gate (sine / triangle / sawtooth / noise).

Proves engine_scroll_wave_curve warps the BG1 checkerboard with FOUR distinct
curves, not just sine. The wave engine builds a 256-entry signed curve LUT
scaled to +/-amp and samples it per column; speed=0 freezes the phase so each
curve renders a STABLE static warp. The assertions frame-diff the RENDERED
frames of the four curves against each other — a uniform tilemap looks identical
under any tile-aligned offset, so only the rendered pixels prove the warp, and
the per-curve diffs prove the curves are genuinely different shapes (not a
proxy on the LUT bytes).

ROM contract (tests/opt_curve_test.asm): 2D checkerboard BG1; curve select by
controller (none=sine, A=triangle, B=sawtooth, X=noise); the curve LUT is
rebuilt only on change and the NMI tick+flush propagate it to BG3 VRAM.
$7E:E008=1, $7E:E010=SHADOW_BGMODE ($02), $7E:E011=SHADOW_TM ($13),
$7E:E012=last applied curve id.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

# Checkerboard region to diff (avoid overscan border) — same window as mode2.
RX0, RX1 = 32, 224
RY0, RY1 = 40, 180


def _diff(a, b):
    n = 0
    for y in range(RY0, RY1, 2):
        for x in range(RX0, RX1, 2):
            if a.getpixel((x, y)) != b.getpixel((x, y)):
                n += 1
    return n


def _shot(r, name):
    p = SHOTS / name
    r.take_screenshot(str(p))
    return Image.open(p).convert("RGB")


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "opt_curve_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make opt_curve_test` first"
    SHOTS.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()
    shots = {}
    curve_ids = {}
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))

        # Each curve: hold the selecting button, let the LUT rebuild + flush,
        # screenshot the static warp, and record the applied curve id telemetry.
        selectors = {
            "sine": {},
            "tri": {"a": True},
            "saw": {"b": True},
            "noise": {"x": True},
        }
        for label, buttons in selectors.items():
            r.set_input(0, **buttons)
            r.run_frames(16)
            shots[label] = _shot(r, f"opt_curve_{label}.png")
            curve_ids[label] = r.read_bytes(WR, 0xE012, 1)[0]
    finally:
        r.stop()
    return {"debug": debug, "shots": shots, "curve_ids": curve_ids}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x02, "SHADOW_BGMODE != $02"
    assert state["debug"][0x11] == 0x13, "SHADOW_TM != $13"


def test_curve_ids_applied(state):
    """The ROM applied the expected curve id for each button (telemetry)."""
    assert state["curve_ids"] == {"sine": 0, "tri": 1, "saw": 2, "noise": 3}, (
        f"unexpected applied curve ids: {state['curve_ids']}"
    )


def test_checkerboard_renders(state):
    """Each curve frame renders the red+blue checkerboard (not a black backdrop).

    Sample across the whole region (not one scan row): a strong tile-column warp
    can shift a single row to all-red, but both red and blue must appear
    somewhere in the checkerboard."""
    for label, img in state["shots"].items():
        colours = set()
        for y in range(RY0, RY1, 8):
            for x in range(RX0, RX1, 4):
                colours.add(img.getpixel((x, y)))
        bright = [c for c in colours if max(c) > 40]
        assert len(bright) >= 2, f"{label}: checkerboard did not render: {colours}"


def test_each_curve_distinct(state):
    """RENDERED proof of curve variety: every pair of curves produces a
    measurably different warped frame. A uniform offset would make them
    identical; distinct frame-diffs prove the column-offset PATTERN changes
    per curve."""
    shots = state["shots"]
    labels = ["sine", "tri", "saw", "noise"]
    weak = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            n = _diff(shots[labels[i]], shots[labels[j]])
            if n <= 40:
                weak.append((labels[i], labels[j], n))
    assert not weak, f"curve pairs too similar (frame-diff <= 40 px): {weak}"
