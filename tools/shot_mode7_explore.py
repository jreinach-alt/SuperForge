"""Render the mode7_explore rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_mode7_explore.py [outdir]

Boots build/mode7_explore.sfc and photographs the six instants that make this
rail's two claims checkable BY LOOKING, along one continuous walk:

    01 spawn        the overworld as it dawns in — roads, mountains, the one
                    enterable house, the avatar on her spawn tile
    02 streamed     twelve tiles west. Most of a VRAM window of world has
                    arrived under her feet since 01, and the picture is
                    coherent: no seam, no stale strip, no torn road. If the
                    stream ever fell behind, this is the frame that shows it
    03 on the door  standing on the house tile, the instant before the wipe
    04 wiping in    the mosaic dissolve mid-flight — the overworld coarsening
                    into blocks. This is the one frame that cannot be inferred
                    from the two either side of it
    05 town         the Mode 1 interior, a different graphics mode entirely,
                    reached without scene_mgr (this file's own swap callback)
    06 returned     back outside AT THE SPOT SHE LEFT, which is the whole
                    reason the transition is not sm_request: overworld::enter
                    would re-upload the 32 KB seed centred on SPAWN and throw
                    that position away

There are no assertions here. This exists so a human (or the maintainer) can
LOOK at the ROM the suite just called green — CLAUDE.md rule 3's "attach a
fresh render from the verified binary", produced from the binary rather than
relayed.

EVERY BEAT IS A POLL, NOT A FRAME COUNT, and this rail is the reason that rule
is written down. Two earlier attempts at an animated capture here used a fixed
frame plan and both produced a plausible artifact that never entered the town:
the grid step is an ATOMIC 8-frame slide, so holding a direction for 4.5 tiles
lets the slide finish after the button changes and lands one tile short; and a
frame-accurate plan that genuinely reached the tile still rendered the wrong
scene at the capture, because a capture between steps drifts the plan against
the ROM's own tick. So this walks until US_CAM_PX/PY
report the tile, and waits until ES_MOS_CTL reports the wipe.

LOCKSTEP: `Machine(rom).advance(n, pad1=...)` parks on an exact emulated frame,
so two runs photograph the same instants and a visual diff between them means
something. No wall-clock anywhere. NOTE Machine.screenshot itself costs one
emulated frame, so the walks below are the drive's own arithmetic.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "mode7_explore.sfc"
WRAM = MemoryType.SnesWorkRam

_MAP = json.loads((SUPERFORGE / "build" / "m7x" / "symbol_map.json").read_text())


def _sym(n):
    for p in _MAP["scenes"]["overworld"]["placements"] + _MAP["globals"]:
        if p["sym"] == n:
            return p["start"]
    raise KeyError(f"{n} not in the emitted map — did the allocator move it?")


PX, PY, MOS, SM = (_sym(n) for n in
                   ("US_CAM_PX", "US_CAM_PY", "ES_MOS_CTL", "ES_SM_CTL"))
HOUSE = (254, 254)              # the one enterable door, in world tiles
WEST_EDGE = 246                 # twelve tiles west of the spawn at (258, 258)
OVERWORLD = 0
SETTLE = 60                     # past the dawn-in


def _u16(m, addr):
    b = m.read_bytes(WRAM, addr, 2)
    return b[0] | (b[1] << 8)


def _tile(m):
    return (_u16(m, PX) // 8, _u16(m, PY) // 8)


def _wiping(m):
    return m.read_bytes(WRAM, MOS, 1)[0] != 0


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name):
        p = out / f"mode7_explore_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:14s} -> {p}  tile={_tile(m)} wiping={_wiping(m)} "
              f"scene={m.read_bytes(WRAM, SM, 1)[0]}")

    def walk(m, pred, pad, limit=600, what=""):
        for _ in range(limit):
            if pred(m):
                return
            m.advance(1, pad1=pad)
        raise SystemExit(f"never reached {what or pred!r} in {limit} frames")

    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        shot(m, "01_spawn")

        walk(m, lambda mm: _tile(mm)[0] <= WEST_EDGE, {"left": True},
             what="the western edge of the walk")
        shot(m, "02_streamed")

        walk(m, lambda mm: _tile(mm)[0] >= HOUSE[0], {"right": True},
             what="the house column")
        walk(m, lambda mm: _tile(mm)[1] <= HOUSE[1] + 1, {"up": True},
             what="the tile below the door")
        shot(m, "03_on_the_door")

        # The wipe, caught IN FLIGHT. Stepping onto the house is what starts
        # it, so this holds Up until ES_MOS_CTL says the dissolve is running
        # and photographs it there rather than a fixed number of frames later.
        walk(m, _wiping, {"up": True}, what="the mosaic wipe")
        m.advance(6)
        shot(m, "04_wiping_in")

        walk(m, lambda mm: not _wiping(mm), {}, what="the wipe finishing")
        m.advance(8, pad1={"left": True})
        shot(m, "05_town")

        # Back out through the door: EDGE-tapped, because the grid step is
        # atomic and a held direction walks straight past it.
        m.advance(8, pad1={"right": True})
        for _ in range(8):
            m.advance(1, pad1={"down": True})
            m.advance(2)
            if _wiping(m):
                break
        walk(m, lambda mm: not _wiping(mm)
             and mm.read_bytes(WRAM, SM, 1)[0] == OVERWORLD, {},
             what="the return to the overworld")
        m.advance(30, pad1={"right": True})
        shot(m, "06_returned")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else SUPERFORGE / "docs" / "img"))
