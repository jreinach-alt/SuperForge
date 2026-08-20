"""Boot one rail under BOTH console regions and diff what the machine did.

Usage:
    python3 tools/pal_probe.py build/microzero.sfc --map build/mz/symbol_map.json
    python3 tools/pal_probe.py build/racer.sfc  --map build/rc/symbol_map.json \
        --anchor game --frames 60,240,600 --outdir build/pal_shots

WHY THIS EXISTS. `vendor/mesen_runner.py` has carried an `SF_REGION` knob
(`ntsc` / `pal` / unset = the header's destination code) since it was written
and nothing in the tree ever used it. The SNES DEV Game Jam asks for "works on
NTSC and PAL", and that sentence cannot be answered by reading ASM: it is a
question about the machine, so it is measured (CLAUDE.md rule 1).

THE ONE-PROCESS CONSTRAINT, and how this handles it. `_apply_region` runs once
per process from `_make_base_snes_config`, so a PAL run and an NTSC run cannot
share a process. This script is therefore its own parent: it re-executes
ITSELF twice with `SF_REGION` set, each child doing one region's pass and
printing JSON, and the parent diffs the two. Nothing here needs the region to
change mid-process.

THE TWO ANCHORS, and why the choice is load-bearing.
  * `--anchor ppu` (default) indexes the input script and every capture on the
    ABSOLUTE PPU FRAME. This is the hardware timeline: "at the same position
    in the frame sequence, is the machine in the same state?"
  * `--anchor game` indexes both on the GAME's own frame counter
    (`ES_SM_FRAME`). The boot's init work costs a fixed number of MASTER
    CYCLES, and a PAL frame is 425,568 mc against NTSC's 357,368 — so the
    same boot spans one fewer frame boundary and the game's frame counter
    sits one ahead of the PPU's for the rest of the run. This anchor removes
    that constant phase and asks the narrower question: "does GAME frame N
    render the same picture in both regions?"
Neither subsumes the other, and a rail can be identical under one and one
animation step off under the other depending on whether its animation is
clocked from the NMI or from the main loop. Read both.

What it prints per capture: whether VRAM, OAM, CGRAM, WRAM, SPC RAM, the DSP
registers and the PNG are byte-identical across the two regions, and for a
differing PNG the pixel count and bounding box. It also prints the measured
master cycles per frame in each child, which is the proof the knob was live
at all (357,366 vs 425,566 — anything else and the run means nothing).

Report only: it asserts nothing and always exits 0 unless a child fails.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

# A drive that gets past a title screen where a rail has one and then works
# the pad through every direction and face button. Identical in both regions;
# what it does is not the point, that both machines are given the same script
# is.
SCRIPT = [(30, {}), (2, {"start": True}), (28, {}),
          (60, {"right": True, "b": True}), (60, {"left": True, "b": True}),
          (60, {"up": True, "a": True}), (60, {"down": True, "y": True}),
          (60, {"right": True, "a": True}), (240, {"right": True})]


def _sha(b):
    return hashlib.sha1(b).hexdigest()[:16]


def worker(args):
    """One region's pass. Prints a JSON line; the parent reads it."""
    import ctypes
    import machine as M
    import mesen_runner as _mr
    from mesen_runner import MemoryType

    regions = {"vram": MemoryType.SnesVideoRam, "oam": MemoryType.SnesSpriteRam,
               "cgram": MemoryType.SnesCgRam, "wram": MemoryType.SnesWorkRam,
               "spcram": MemoryType.SpcRam, "dsp": MemoryType.SpcDspRegisters}

    def master_clock(lib):
        buf = (ctypes.c_uint8 * _mr._SNES_STATE_BUF_BYTES)()
        lib.GetConsoleState(ctypes.cast(buf, ctypes.c_void_p),
                            _mr._CONSOLE_TYPE_SNES)
        return int.from_bytes(bytes(buf)[0:8], "little")

    caps_at = sorted(int(x) for x in args.frames.split(","))
    name = Path(args.rom).stem
    region = os.environ.get("SF_REGION", "auto")
    pads = []
    for n, pad in SCRIPT:
        pads.extend([pad] * n)
    smf = None
    if args.map:
        smf = {x["sym"]: x["start"]
               for x in json.load(open(args.map))["globals"]}.get("ES_SM_FRAME")
    if args.anchor == "game" and smf is None:
        raise SystemExit("--anchor game needs --map naming a map with "
                         "ES_SM_FRAME (every game/ rail has one)")

    m = M.Machine(args.rom)
    lib = m._lib

    def gframe():
        return int.from_bytes(
            m.read_bytes(MemoryType.SnesWorkRam, smf, 2), "little")

    def clock():
        return gframe() if args.anchor == "game" else m.ppu_frame_count()

    # 20 frames of warm-up puts every rail's boot behind us (the longest
    # measured is 6 frames) so the game's counter is live, and gives the
    # master-clock reading a window to be measured over. The first advance is
    # taken BEFORE the clock is read: a Machine loads at scanline 0 and parks
    # at 224, so a reading spanning the load charges the frame with 224 extra
    # lines and reports ~372k instead of the frame's real 357,366.
    m.advance(1)
    c0 = master_clock(lib)
    f0 = m.ppu_frame_count()
    m.advance(19)
    out = {"rom": name, "region": region, "rom_md5": m.rom_md5,
           "anchor": args.anchor, "ppu_at_warmup": m.ppu_frame_count(),
           "mc_per_frame": (master_clock(lib) - c0)
                           / (m.ppu_frame_count() - f0),
           "caps": []}
    if smf is not None:
        out["game_frame_at_warmup"] = gframe()
    for t in caps_at:
        while clock() < t:
            k = clock()
            m.advance(1, pad1=(pads[k] if k < len(pads) else None) or None)
        rec = {"clock": clock(), "ppu": m.ppu_frame_count()}
        for label, mt in regions.items():
            rec[label] = _sha(m.read_region(mt))
        if args.outdir:
            png = str(Path(args.outdir) / f"{name}.{region}.{t}.png")
            m.take_screenshot(png)          # costs one frame, in both regions
            rec["png"] = png
            rec["png_sha"] = _sha(Path(png).read_bytes())
        out["caps"].append(rec)
    if smf is not None:
        cur = m.ppu_frame_count()
        if cur < args.drift_frame:
            m.advance(args.drift_frame - cur)
        out["drift_ppu"] = m.ppu_frame_count()
        out["drift_game"] = gframe()
    m.close()
    print("SFPAL " + json.dumps(out))


def _png_delta(pa, pb):
    from PIL import Image, ImageChops
    a, b = Image.open(pa).convert("RGB"), Image.open(pb).convert("RGB")
    if a.size != b.size:
        return f"SIZE {a.size} vs {b.size}"
    diff = ImageChops.difference(a, b)
    n = sum(1 for px in diff.getdata() if px != (0, 0, 0))
    return f"{n} px, bbox {diff.getbbox()}"


def _run_child(args, region):
    env = dict(os.environ, SF_REGION=region)
    argv = [sys.executable, __file__, args.rom, "--worker",
            "--anchor", args.anchor, "--frames", args.frames]
    if args.map:
        argv += ["--map", args.map]
    if args.outdir:
        argv += ["--outdir", args.outdir]
    r = subprocess.run(argv, env=env, capture_output=True, text=True)
    line = next((ln for ln in r.stdout.splitlines()
                 if ln.startswith("SFPAL ")), None)
    if line is None:
        raise SystemExit(f"{region} pass failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(line[len("SFPAL "):])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rom")
    ap.add_argument("--map", help="the rail's build/<d>/symbol_map.json")
    ap.add_argument("--anchor", choices=("ppu", "game"), default="ppu")
    ap.add_argument("--frames", default="60,120,240,420,600")
    ap.add_argument("--outdir", help="write per-region PNGs here")
    ap.add_argument("--drift-frame", type=int, default=1800,
                    help="absolute frame at which the phase offset is re-read")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        return worker(args)
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)

    n, p = _run_child(args, "ntsc"), _run_child(args, "pal")
    print(f"{n['rom']}  md5 {n['rom_md5']}  anchor={args.anchor}")
    print(f"  master cycles/frame   ntsc {n['mc_per_frame']:.0f}"
          f"   pal {p['mc_per_frame']:.0f}"
          f"   (357,366 / 425,566 = the knob was live)")
    if "game_frame_at_warmup" in n:
        dn, dp = n["game_frame_at_warmup"], p["game_frame_at_warmup"]
        print(f"  game frame at ppu 20  ntsc {dn}   pal {dp}"
              f"   -> boot phase offset {dp - dn} frame(s)")
        print(f"  same at ppu {n['drift_ppu']}       ntsc {n['drift_game']}"
              f"   pal {p['drift_game']}"
              f"   -> offset {p['drift_game'] - n['drift_game']}"
              f" ({'NO DRIFT' if p['drift_game'] - n['drift_game'] == dp - dn else 'DRIFTED'})")
    keys = ["vram", "oam", "cgram", "wram", "spcram", "dsp", "png_sha"]
    for cn, cp in zip(n["caps"], p["caps"]):
        bad = [k for k in keys if k in cn and cn[k] != cp[k]]
        tag = "identical" if not bad else "differs: " + ",".join(bad)
        extra = ""
        if "png_sha" in bad:
            extra = "   " + _png_delta(cn["png"], cp["png"])
        print(f"  {args.anchor} frame {cn['clock']:<5} {tag}{extra}")


if __name__ == "__main__":
    main()
