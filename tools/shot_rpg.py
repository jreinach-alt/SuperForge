"""Render the rpg rail's arc to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_rpg.py [outdir]

Boots build/rpg.sfc and walks the whole thing: the Mode 7 overworld, the
mosaic wipe into the Mode 1 town, the villager's paged dialog box, the panel
CLOSED again so the scene behind it is visible, and the save point. No
assertions — this exists so a human can LOOK at the ROM the suite just called
green (CLAUDE.md rule 3).

Every capture lands on an ABSOLUTE frame and every input is latched per
emulated frame, so two runs of this tool photograph the same instants and a
visual diff between them means something.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "rpg.sfc"
W, S = MemoryType.SnesWorkRam, MemoryType.SnesSaveRam
VIRGIN = bytes((i * 37 + 91) & 0xFF for i in range(64))   # a fresh cart
SRAM_BASE = 0


def press(m, **b):
    m.advance(1, pad1=b)
    m.advance(2)


def walk(m, n, **b):
    for _ in range(n):
        press(m, **b)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    with Machine(str(ROM)) as m:
        m.write_bytes(S, SRAM_BASE, VIRGIN)
        m.advance(120)
        m.screenshot(str(out / "rpg_01_overworld.png"))
        print("overworld ->", out / "rpg_01_overworld.png")

        # Four tiles north into the gate (~9 frames per 8-frame slide), then
        # ten frames into the twenty-frame OUT ramp: half-dissolved, which is
        # the frame the wipe exists to be looked at on.
        m.advance(40, pad1={"up": True})
        m.advance(10)
        m.screenshot(str(out / "rpg_02_wipe.png"))
        print("wipe      ->", out / "rpg_02_wipe.png")

        m.advance(100)
        m.screenshot(str(out / "rpg_03_town.png"))
        print("town      ->", out / "rpg_03_town.png")

        walk(m, 4, left=True)
        walk(m, 9, up=True)
        press(m, a=True)
        m.advance(3)
        m.screenshot(str(out / "rpg_04_dialog.png"))
        print("dialog    ->", out / "rpg_04_dialog.png")

        press(m, a=True)
        m.advance(3)
        m.screenshot(str(out / "rpg_05_dialog_p2.png"))
        print("page 2    ->", out / "rpg_05_dialog_p2.png")

        press(m, a=True)
        m.advance(3)
        press(m, a=True)
        m.advance(3)
        m.screenshot(str(out / "rpg_06_closed.png"))
        print("closed    ->", out / "rpg_06_closed.png")

        # (12,11) -> (20,11) -> (20,15), which is the cell north of the save
        # torch. RIGHT FIRST: row 15 crosses the fountain at x 14..17, so the
        # other order walks into water and stalls.
        walk(m, 8, right=True)
        walk(m, 4, down=True)
        press(m, a=True)
        m.advance(4)
        m.screenshot(str(out / "rpg_07_saved.png"))     # the panel + the torch mid-FLARE
        print("saved     ->", out / "rpg_07_saved.png",
              "  SRAM:", bytes(m.read_bytes(S, SRAM_BASE, 8)).hex())
        # the flare is ONE brief burst — let it expire and photograph the
        # torch restored, so the pair reads "the torch flares ONCE, then back to
        # normal" (the panel text made honest).
        m.advance(30)
        m.screenshot(str(out / "rpg_08_flare_done.png"))
        print("flare done->", out / "rpg_08_flare_done.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
