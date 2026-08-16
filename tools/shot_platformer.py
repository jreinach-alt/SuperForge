#!/usr/bin/env python3
"""shot_platformer.py — boot the platformer and capture frames for inspection.

Usage:  python3 tools/shot_platformer.py OUTDIR [walk_frames]

Drives title -> play (START), then optionally holds RIGHT for N frames so the
camera advances and the two parallax bands separate. Everything is
frame-counted, never wall-clock (AGENTS.md).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
from mesen_runner import MesenRunner  # noqa: E402

ROM = "build/platformer.sfc"


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/plf")
    walk = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    out.mkdir(parents=True, exist_ok=True)

    r = MesenRunner()
    r.boot_rom(ROM, frames=90)
    r.take_screenshot(str(out / "01_title.png"))

    r.set_input(0, start=True)
    r.wait_frames(4)
    r.set_input(0)
    r.wait_frames(70)
    r.take_screenshot(str(out / "02_play_spawn.png"))

    r.set_input(0, right=True)
    r.wait_frames(walk)
    r.set_input(0)
    r.wait_frames(8)
    r.take_screenshot(str(out / "03_play_walked.png"))

    r.set_input(0, right=True, a=True)
    r.wait_frames(12)
    r.set_input(0, right=True)
    r.wait_frames(10)
    r.set_input(0)
    r.wait_frames(4)
    r.take_screenshot(str(out / "04_play_jump.png"))
    r.stop()
    print(f"shots -> {out}")


if __name__ == "__main__":
    main()
