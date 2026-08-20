#!/usr/bin/env python3
"""active_lines.py — how many scanlines the PPU actually DREW, read off the frame.

REPORT ONLY. It asserts nothing, is wired into no gate, changes no behaviour,
and always exits 0 unless a child process fails. Sibling of tools/pal_probe.py.

WHY THIS EXISTS, and it is the finding docs/95 §1 turns on. Mesen hands back a
256x239 buffer for BOTH console regions, so the thing a PAL player actually
complains about -- 224 picture lines inside a 288-line PAL field, with a border
top and bottom -- is invisible to this harness. The dimensions do not move; the
region does not move them. Any acceptance criterion phrased as "a PAL frame
shows no border an NTSC frame does not" cannot be discharged here.

WHAT *IS* OBSERVABLE, exactly, and it is what R1 actually needs. Mesen's
SnesPpu::SendFrame clears the top 7 and bottom 8 rows of the buffer whenever
the frame was NOT an overscan frame, and SnesPpu::ApplyHiResMode centres the
picture at `_scanline + 6` in that case and at `_scanline - 1` when it IS one.
So the PPU's ACTIVE LINE COUNT is legible in the rendered PNG two ways, both
of them picture rather than proxy:

  * the picture's vertical EXTENT   224 lines land on rows 7..230
                                    239 lines land on rows 0..238
  * the picture's OFFSET            the same content sits 7 rows higher when
                                    the active area is 239 lines

The offset witness is the strong one: it does not depend on the content being
non-black at the edges, which a dark backdrop would defeat. `--shift` takes two
captures and reports whether the second is the first shifted up by exactly
PICTURE_TOP rows over the overlap, which is the R1 acceptance shape.

Both witnesses are region-INDEPENDENT: they read the PPU's active area, not
the television's visible field. That is the honest instrument, and naming it
that way is the point of this file.

Usage:
    python3 tools/active_lines.py build/racer.sfc
    python3 tools/active_lines.py build/racer.sfc --frames 60,240 --outdir build/al
    python3 tools/active_lines.py --shift a.png b.png
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

# Mesen's own geometry, and the two constants it is expressed in.
# SnesPpu.cpp SendFrame(): `int top = 7; int bottom = 8;` cleared when
# `!_overscanFrame`. ApplyHiResMode(): `_overscanFrame ? _scanline - 1
#                                                      : _scanline + 6`.
FRAME_W, FRAME_H = 256, 239
PICTURE_TOP = 7                 # first picture row when the active area is 224
LINES_224, LINES_239 = 224, 239

# The same pad script tools/pal_probe.py drives, for the same reason: what it
# does is not the point, that every run is given the same script is.
SCRIPT = [(30, {}), (2, {"start": True}), (28, {}),
          (60, {"right": True, "b": True}), (60, {"left": True, "b": True}),
          (60, {"up": True, "a": True}), (60, {"down": True, "y": True}),
          (60, {"right": True, "a": True}), (240, {"right": True})]


def _rows_nonblack(path):
    """Per-row count of pixels that are not pure black, top row first."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    return [sum(1 for x in range(w) if px[x, y] != (0, 0, 0)) for y in range(h)], (w, h)


def read_active_lines(path):
    """{extent, first_row, last_row, verdict} for one capture."""
    rows, size = _rows_nonblack(path)
    first = next((i for i, v in enumerate(rows) if v), None)
    last = next((i for i in range(len(rows) - 1, -1, -1) if rows[i]), None)
    if first is None:
        verdict = "all-black frame — the extent witness cannot speak here; use --shift"
    elif first >= PICTURE_TOP and last is not None and last <= FRAME_H - 9:
        verdict = f"consistent with a {LINES_224}-line active area"
    elif first < PICTURE_TOP or (last is not None and last > FRAME_H - 9):
        verdict = f"OVERSCAN: picture outside rows {PICTURE_TOP}..{FRAME_H - 9}, so the active area is {LINES_239} lines"
    else:
        verdict = "indeterminate"
    return {"size": list(size), "first_nonblack_row": first,
            "last_nonblack_row": last, "verdict": verdict,
            "sha": hashlib.sha1(Path(path).read_bytes()).hexdigest()[:16]}


def shift_report(a_path, b_path, shift=PICTURE_TOP, rows=LINES_224):
    """Is `b` the same picture as `a`, moved up `shift` rows?

    THE R1 ACCEPTANCE SHAPE. `a` is a 224-line capture (picture at rows
    7..230), `b` a 239-line one (picture at rows 0..238). The claim R1 has to
    discharge is that the taller frame did not MOVE the shorter frame's
    content, only extend it -- i.e. a's rows [7, 231) equal b's rows [0, 224).

    The comparison deliberately stops at `rows` (224). Past that, a carries
    Mesen's forced-black bottom band and b carries the new content, and
    counting those as mismatches would report a PASS as an 8-row failure.
    Those 15 new rows are what the extent witness is for, not this one.
    """
    from PIL import Image
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    pa, pb = a.load(), b.load()
    w = min(a.size[0], b.size[0])
    n = min(rows, a.size[1] - shift, b.size[1])
    bad = [y for y in range(n)
           if any(pa[x, y + shift] != pb[x, y] for x in range(w))]
    return {"shift": shift, "compared_rows": n, "mismatched_rows": len(bad),
            "first_mismatches": bad[:8],
            "verdict": ("the second capture IS the first shifted up "
                        f"{shift} rows over all {n} picture rows"
                        if not bad else
                        f"{len(bad)} of {n} picture rows differ")}


def worker(rom, frames, outdir):
    """One region's pass. Prints one JSON line; the parent reads it."""
    import ctypes
    import machine as M
    import mesen_runner as _mr

    def master_clock(lib):
        buf = (ctypes.c_uint8 * _mr._SNES_STATE_BUF_BYTES)()
        lib.GetConsoleState(ctypes.cast(buf, ctypes.c_void_p),
                            _mr._CONSOLE_TYPE_SNES)
        return int.from_bytes(bytes(buf)[0:8], "little")

    region = os.environ.get("SF_REGION", "unset")
    m = M.Machine(rom)
    lib = m._lib
    # The first advance is taken BEFORE the clock is read, for the reason
    # tools/pal_probe.py records: a Machine loads at scanline 0 and parks at
    # 224, so a window spanning the load charges the frame with 224 extra
    # lines and reports ~372k rather than the frame's real 357,366.
    m.advance(1)
    c0 = master_clock(lib)
    f0 = m.ppu_frame_count()
    m.advance(59)
    mc_per_frame = round((master_clock(lib) - c0)
                         / (m.ppu_frame_count() - f0))

    out = {"region": region, "mc_per_frame": mc_per_frame, "caps": []}
    i = 0
    for count, pad in SCRIPT:
        for _ in range(count):
            m.advance(1, pad1=pad or None)
            i += 1
            if i in frames:
                p = f"{outdir}/al_{region}_{i}.png"
                m.screenshot(p)
                rec = read_active_lines(p)
                rec.update({"frame": i, "png": p})
                out["caps"].append(rec)
    m.close()
    print("@@JSON@@" + json.dumps(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom", nargs="?", help="the .sfc to drive")
    ap.add_argument("--frames", default="120,360",
                    help="comma-separated advance counts to capture at")
    ap.add_argument("--outdir", default="build/active_lines")
    ap.add_argument("--shift", nargs=2, metavar=("A.PNG", "B.PNG"),
                    help="report whether B is A shifted up PICTURE_TOP rows")
    a = ap.parse_args()

    if a.shift:
        r = shift_report(*a.shift)
        print(json.dumps(r, indent=1))
        return 0
    if not a.rom:
        ap.error("give a ROM, or --shift A.PNG B.PNG")

    frames = {int(x) for x in a.frames.split(",")}
    Path(a.outdir).mkdir(parents=True, exist_ok=True)

    if os.environ.get("SF_ACTIVE_LINES_CHILD"):
        worker(a.rom, frames, a.outdir)
        return 0

    # _apply_region runs once per process, so one region per child (the
    # constraint tools/pal_probe.py documents and handles the same way).
    results = {}
    for region in ("ntsc", "pal"):
        env = dict(os.environ, SF_REGION=region, SF_ACTIVE_LINES_CHILD="1")
        p = subprocess.run([sys.executable, __file__, a.rom,
                            "--frames", a.frames, "--outdir", a.outdir],
                           env=env, capture_output=True, text=True)
        line = [x for x in p.stdout.splitlines() if x.startswith("@@JSON@@")]
        if not line:
            sys.stderr.write(p.stdout[-4000:] + p.stderr[-4000:])
            return 1
        results[region] = json.loads(line[-1][len("@@JSON@@"):])

    print(f"{'region':6} {'mc/frame':>9}  {'frame':>5} {'rows':>9}  verdict")
    for region, d in results.items():
        for c in d["caps"]:
            span = f"{c['first_nonblack_row']}..{c['last_nonblack_row']}"
            print(f"{region:6} {d['mc_per_frame']:>9}  {c['frame']:>5} "
                  f"{span:>9}  {c['verdict']}")
    (Path(a.outdir) / "active_lines.json").write_text(
        json.dumps(results, indent=1) + "\n")
    print(f"\nwrote {a.outdir}/active_lines.json")
    print("mc/frame is the liveness check: 357366 NTSC / 425566 PAL. "
          "Anything else and the region knob was not live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
