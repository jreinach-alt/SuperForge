"""Render the microzero loop to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_microzero.py [outdir]

Boots build/microzero.sfc, walks title -> race -> results, and saves a
screenshot at each stop plus a few along the drive. No assertions: this
exists so a human (or the maintainer) can LOOK at the ROM that the suite
just called green.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam
TITLE, RACE, RESULTS = 0, 1, 2


def scene_state(runner, syms):
    cur, _nxt, phase = runner.read_bytes(WR, syms["ES_SM_CTL"]["start"], 3)
    return cur, phase


def wait_for_scene(runner, syms, scene_id, limit=600):
    for _ in range(limit):
        if scene_state(runner, syms) == (scene_id, 0):
            runner.frame_step(2)
            return
        runner.frame_step(1)
    raise AssertionError(f"scene {scene_id} never settled")


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {name: {p["sym"]: p for p in
                   jmap["scenes"][name]["placements"] + jmap["globals"]}
            for name in ("title", "race", "results")}
    lut = D.load_tool("gen_move_lut")

    runner = MesenRunner()
    # An ABSOLUTE frame, so two runs of this tool photograph the same
    # instant of the race and a visual diff between them means something.
    runner.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 180)
    runner.debug_break()
    runner.frame_step(2)

    runner.take_screenshot(str(out / "01_title.png"))
    print("title  ->", out / "01_title.png")

    runner.frame_step(2, start=True)
    runner.frame_step(2)
    wait_for_scene(runner, syms["race"], RACE)
    runner.take_screenshot(str(out / "02_race_start.png"))
    print("race   ->", out / "02_race_start.png")

    sim = D.sim_from_rom(runner, syms["race"], lut)
    total = 0
    for i, frames in enumerate((60, 120, 180), start=3):
        for _ in range(frames):
            D.drive_sim(runner, sim, 1, **D.track_buttons(sim, lut))
        total += frames
        p = out / f"{i:02d}_race_driving_f{total}.png"
        runner.take_screenshot(str(p))
        print("race   ->", p)

    D.drive_laps(runner, syms["race"], sim, lut, 3)
    wait_for_scene(runner, syms["results"], RESULTS)
    runner.frame_step(120)
    runner.take_screenshot(str(out / "06_results.png"))
    print("result ->", out / "06_results.png")

    runner.frame_step(2, start=True)
    runner.frame_step(2)
    wait_for_scene(runner, syms["title"], TITLE)
    runner.take_screenshot(str(out / "07_title_again.png"))
    print("title  ->", out / "07_title_again.png")

    runner.debug_resume()
    runner.stop()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mz_shots")
