#!/usr/bin/env python3
"""tb_picture_diff.py — did the timebase move the picture? Read the pixels.

WHY THIS EXISTS. `docs/94` §4 clause 1: *"The NTSC picture is pixel-identical.
Under SF_REGION=ntsc every rail's rendered frame must match its pre-change
frame, checked per rail with a capture diff."* An md5 on the `.sfc` is a
stronger statement than a capture diff when the image does not move, and
`tools/build_scroller_tb.sh` already asserts that for the flag-OFF arm. It
says nothing at all about the arms where the image DOES move — the five
`-D SF_TICK=n` builds — and those are exactly the ones a reader should not
be asked to take on trust.

So this reads the rendered frame. Same drive, same absolute PPU frames, one
ROM against a reference ROM, per region, and it reports two things that mean
opposite things:

  * NTSC MUST BE IDENTICAL. Every candidate scheme is designed to publish
    today's constant and one tick per frame when the region flag is clear,
    so a single differing pixel on NTSC is the reversibility property
    failing. This is the gate.
  * PAL MUST DIFFER. A compensated build that renders the same PAL frame as
    the uncompensated one did nothing. This is the NON-VACUITY CONTROL, and
    without it "NTSC identical" is satisfied by a scheme that is switched
    off. It is reported, not asserted, because a scheme that reaches parity
    can still agree with the reference on a frame where the camera happens
    to line up.

Anchored on the ABSOLUTE PPU FRAME, not on real time: two ROMs on the same
machine share a timeline, and the question here is "is this the same
picture", which is a question about frames.

    python3 tools/tb_picture_diff.py build/scroller.sfc \\
        build/scroller_tb_lump.sfc build/scroller_tb_accum.sfc
    python3 tools/tb_picture_diff.py --frames 120,300,600 REF ROM...
    python3 tools/tb_picture_diff.py --pad left BEFORE/brawler.sfc \\
        build/brawler.sfc          # a pre-change image as the reference
    python3 tools/tb_picture_diff.py --fresh --pad start,left BEFORE/room.sfc \\
        build/room.sfc             # a rail that writes SRAM: see --fresh

Exit 0 iff every ROM's NTSC captures matched the reference. Non-zero says
which one moved, and on which frame.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

# THE DRIVE, held for the whole capture. The default is the held-RIGHT drive
# tools/rate_oracle.py uses on `scroller`, expressed in FRAMES here because the
# anchor is the frame; `--pad` names a different one for a different rail (the
# oracle drives `brawler` with LEFT, and a rail behind a title screen wants
# `--pad start` or nothing at all). What matters is only that BOTH images are
# driven the SAME way — this tool asks "is this the same picture", not "does
# the rail reach gameplay".
DEFAULT_PAD = "right"


def worker(args):
    import machine as M

    region = os.environ.get("SF_REGION", "auto")
    at = sorted(int(x) for x in args.frames.split(","))
    pad = {b: True for b in args.pad.split(",") if b} or None
    out = []
    for rom in args.roms:
        m = M.Machine(rom)
        shots = {}
        for f in at:
            while m.ppu_frame_count() < f:
                m.advance(1, pad1=pad)
            png = f"{args.outdir}/{Path(rom).stem}.{region}.f{f}.png"
            m.take_screenshot(png)
            shots[f] = hashlib.sha1(Path(png).read_bytes()).hexdigest()[:16]
        out.append({"rom": rom, "md5": m.rom_md5, "shots": shots})
        m.close()
    print("SFTBPIC " + json.dumps({"region": region, "roms": out}))


def _one_child(argv, env, tag):
    r = subprocess.run(argv, env=env, capture_output=True, text=True,
                       cwd=str(SUPERFORGE))
    line = next((x for x in r.stdout.splitlines() if x.startswith("SFTBPIC ")),
                None)
    if line is None:
        raise SystemExit(f"{tag} pass failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(line[len("SFTBPIC "):])


def _child(args, region):
    """One region's captures.

    By default every ROM is loaded in ONE child, in order, which is fine for a
    rail whose picture is a pure function of its image. It is NOT fine for a
    rail that writes SRAM: Mesen keeps its battery files under the process's
    Mesen home (``Saves/*.srm``, see mesen_runner's SF_MESEN_HOME note), so the
    SECOND load boots WARM off the first one's save and renders a different
    picture — for `room` that is a different count of visit pips, and it
    reproduces with the SAME IMAGE loaded twice, which is what proves it is
    the harness and not the ROM. `--fresh` gives every ROM its own child AND
    its own Mesen home, so each one boots cold.
    """
    base = dict(os.environ, SF_REGION=region)
    common = [sys.executable, __file__, "--worker", "--frames", args.frames,
              "--pad", args.pad, "--outdir", args.outdir]
    if not args.fresh:
        return _one_child(common + list(args.roms), base, region)
    out = {"region": region, "roms": []}
    for i, rom in enumerate(args.roms):
        home = os.path.join(tempfile.gettempdir(),
                            f"mesen_home_tbpic_{os.getpid()}_{region}_{i}")
        os.makedirs(home, exist_ok=True)
        env = dict(base, SF_MESEN_HOME=home)
        out["roms"] += _one_child(common + [rom], env,
                                  f"{region}/{Path(rom).name}")["roms"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roms", nargs="+", help="reference ROM first, then variants")
    ap.add_argument("--frames", default="120,300,600",
                    help="absolute PPU frames to capture at")
    ap.add_argument("--pad", default=DEFAULT_PAD,
                    help="comma-separated buttons held for the whole capture "
                         "(e.g. 'left', 'b,right', or '' for none)")
    ap.add_argument("--outdir", default="build/tb_shots")
    ap.add_argument("--fresh", action="store_true",
                    help="load each ROM in its OWN child process with its own "
                         "Mesen home, so a rail that writes SRAM cannot boot "
                         "the next ROM warm off the previous one's save. "
                         "Required for any rail composing `save`; harmless "
                         "elsewhere, and slower by one process per ROM.")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    if args.worker:
        return worker(args)

    rc = 0
    for region in ("ntsc", "pal"):
        rec = _child(args, region)
        ref = rec["roms"][0]
        print(f"[{region}]  reference {Path(ref['rom']).name}  "
              f"md5 {ref['md5']}")
        for r in rec["roms"][1:]:
            same = [f for f, sha in r["shots"].items()
                    if sha == ref["shots"][f]]
            diff = [f for f in r["shots"] if f not in same]
            name = f'{Path(r["rom"]).name} {r["md5"][:8]}'
            if region == "ntsc":
                verdict = ("IDENTICAL — the picture did not move"
                           if not diff else
                           f"MOVED on frame(s) {diff}  <- clause 1 FAILED")
                if diff:
                    rc = 1
            else:
                verdict = (f"differs on frame(s) {diff}"
                           if diff else
                           "IDENTICAL — the scheme changed NOTHING on PAL "
                           "<- vacuous")
            print(f"  {name:<40} {verdict}")
    print("\ncaptures in " + args.outdir)
    return rc


if __name__ == "__main__":
    sys.exit(main())
