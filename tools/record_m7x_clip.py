#!/usr/bin/env python3
"""Record the mode7_explore gallery clip: walk -> wipe -> town -> wipe -> back.

STATE-DRIVEN, not schedule-driven. Two earlier attempts used a fixed frame
plan and both produced a clip that never entered the town:

  1. holding a direction for 4.5 tiles let the in-flight slide finish AFTER
     the button changed, landing one tile west of the house;
  2. a frame-accurate plan reached the house (probe: cam tile (254,254),
     mosaic state 0->1->2->0) but still rendered the overworld at the
     capture where the town should be — the take_screenshot between steps
     drifts the plan against the ROM's own tick.

So this drives off the ROM's state the way the tests do: walk until the
camera reports the target tile, idle until the wipe reports idle, tap until
the scene changes. Host load and recorder drift cannot desync it.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.record_gallery_clip import record_clip, STEP  # noqa: E402
from vendor.mesen_runner import MemoryType  # noqa: E402

ROM = str(ROOT / "build" / "mode7_explore.sfc")
OUT = str(ROOT / "docs" / "img" / "mode7_explore.gif")
W = MemoryType.SnesWorkRam

_J = json.loads((ROOT / "build" / "m7x" / "symbol_map.json").read_text())


def _sym(n):
    for p in _J["scenes"]["overworld"]["placements"] + _J["globals"]:
        if p["sym"] == n:
            return p["start"]
    raise KeyError(n)


PX, PY, MOS = _sym("US_CAM_PX"), _sym("US_CAM_PY"), _sym("ES_MOS_CTL")
HOUSE = (254, 254)


def tile(r):
    return (r.read_u16(W, PX) // 8, r.read_u16(W, PY) // 8)


def wiping(r):
    return r.read_bytes(W, MOS, 1)[0] != 0


class Arc:
    """One capture per call; advances STEP frames however the state says.

    STEP, not EVERY: take_screenshot pays the remaining frame on SuperForge's
    runner, so a capture is EVERY frames of the ROM's time and playback is
    1:1 (record_gallery_clip.py's SHOT_FRAMES block). This file drove EVERY
    when the committed docs/img/mode7_explore.gif was recorded, so that
    artifact holds 4 frames of gameplay per 50 ms and plays 1.33x fast.
    """

    def __init__(self):
        self.phase = 0
        self.taps = 0
        self.seen_wipe = False

    def __call__(self, r, i):
        p = self.phase
        if p == 0:                                    # a beat, then head west
            self.phase = 1
            return r.frame_step(STEP)
        if p == 1:                                    # west to the house column
            if tile(r)[0] > HOUSE[0]:
                return r.frame_step(STEP, left=True)
            self.phase = 2
            return r.frame_step(STEP)
        if p == 2:                                    # north onto the house
            if tile(r)[1] > HOUSE[1] and not wiping(r):
                return r.frame_step(STEP, up=True)
            self.phase = 3
            return r.frame_step(STEP)
        if p == 3:                                    # the dissolve owns the frame
            if wiping(r):
                self.seen_wipe = True
                return r.frame_step(STEP)
            if self.seen_wipe:
                self.phase = 4
            return r.frame_step(STEP)
        if p == 4:                                    # EDGE-tap south to the door
            if self.taps < 5 and not wiping(r):
                self.taps += 1
                r.frame_step(1, down=True)
                return r.frame_step(STEP - 1)
            if wiping(r):
                self.phase = 5
            return r.frame_step(STEP)
        return r.frame_step(STEP)                    # the exit dissolve + back


if __name__ == "__main__":
    path, n, size = record_clip(ROM, OUT, drive=Arc(), captures=44)

    from PIL import Image, ImageSequence
    im = Image.open(path)
    caps = [f.info.get("duration", 50) // 50 for f in ImageSequence.Iterator(im)]
    raw, stored = sum(caps), len(caps)
    print(f"raw captures {raw} -> {stored} stored")
    print(f"FULLY STATIC raw transitions: {raw - stored}/{raw - 1} "
          f"= {100 * (raw - stored) / (raw - 1):.0f}%")
    print(f"longest hold: {max(caps)} captures ({max(caps) * 50} ms)")
