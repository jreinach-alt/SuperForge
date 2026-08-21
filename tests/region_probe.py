#!/usr/bin/env python3
"""region_probe.py — boot a ROM under ONE console region and report what the
machine did. A helper for `tests/test_region.py`, not a test module.

WHY A SEPARATE PROCESS. `mesen_runner._apply_region` runs once per process,
from `_make_base_snes_config`, so NTSC and PAL cannot share one — a test that
wants both must fork. `tools/pal_probe.py` established that pattern (re-execute
once per region, diff the children's JSON) and `tools/rate_oracle.py`,
`tools/measure_tb_cost.py` and `tools/tb_picture_diff.py` all follow it; this
follows it too rather than inventing a second one.

THE WINDOW IS REAL TIME, NOT FRAMES, and that is the whole point of the file.
A frame-indexed window hands PAL 50 samples where NTSC got 60 and every rate
then reads 5/6 because the HARNESS ran it 5/6 as long. Real seconds come from
the master clock, which the emulator advances at the region's own rate:

    Mesen2 Core/SNES/SnesConsole.cpp:209
        _masterClockRate = _region == ConsoleRegion::Pal ? 21281370 : 21477270

so the probe advances frames until the master clock says the requested number
of REAL seconds have passed, and reports how many frames that took.

    SF_REGION=pal python3 tests/region_probe.py '<json spec>'

Spec keys: rom, map, scene, seconds, pad, words [[sym, width]...],
oam [[slot, byte]...]. It prints one `SFRGN {json}` line.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

# Read from the implementing code, not remembered — the only correct divisor
# for turning master cycles into real seconds.
MASTER_HZ = {"ntsc": 21_477_270, "pal": 21_281_370}


def _sym(jmap, name, scene):
    pool = jmap["scenes"][scene]["placements"] if scene else jmap["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    if scene:
        return _sym(jmap, name, None)
    raise KeyError(f"{name} is not in the emitted map")


def main() -> int:
    import machine as M
    import mesen_runner as _mr
    from mesen_runner import MemoryType

    spec = json.loads(sys.argv[1])
    region = os.environ.get("SF_REGION", "").strip().lower()
    hz = MASTER_HZ.get(region)
    if hz is None:
        raise SystemExit("region_probe: SF_REGION must be ntsc or pal — "
                         "'auto' cannot be timed, because the rate depends "
                         "on the region Mesen picked.")

    jmap = json.loads((SUPERFORGE / spec["map"]).read_text())
    scene = spec.get("scene")
    words = [(n, w, _sym(jmap, n, scene)["start"])
             for n, w in spec.get("words", [])]
    # An ES_O_* claim is a SPRITE SLOT index; the OAM low table is 4 B/sprite.
    oam = [(s, b, _sym(jmap, s, scene)["start"] * 4 + b)
           for s, b in spec.get("oam", [])]

    m = M.Machine(str(SUPERFORGE / spec["rom"]))
    lib = m._lib

    def master_clock():
        buf = (ctypes.c_uint8 * _mr._SNES_STATE_BUF_BYTES)()
        lib.GetConsoleState(ctypes.cast(buf, ctypes.c_void_p),
                            _mr._CONSOLE_TYPE_SNES)
        return int.from_bytes(bytes(buf)[0:8], "little")

    def rd(mt, addr, w):
        return int.from_bytes(m.read_bytes(mt, addr, w), "little")

    pad = spec.get("pad") or None

    # The frame period, measured the way tools/rate_oracle.py measures it: the
    # first advance is taken BEFORE the clock is read, because a Machine loads
    # at scanline 0 and parks at 224, so a reading spanning the load charges
    # the frame with the extra lines.
    m.advance(1)
    c0, f0 = master_clock(), m.ppu_frame_count()
    m.advance(19)
    mc_per_frame = (master_clock() - c0) / (m.ppu_frame_count() - f0)

    # Warm-up first (the scene has to be entered and the fade run), then the
    # measured window. Both are expressed in REAL seconds.
    for phase, secs in (("warm", spec.get("warm_s", 0.0)),
                        ("run", spec["seconds"])):
        start = master_clock()
        if phase == "run":
            series = {n: [] for n, _, _ in words}
            oam_series = {f"{s}+{b}": [] for s, b, _ in oam}
            frames = 0
        while (master_clock() - start) / hz < secs:
            m.advance(1, pad1=pad)
            if phase == "run":
                frames += 1
                for n, w, a in words:
                    series[n].append(rd(MemoryType.SnesWorkRam, a, w))
                for s, b, a in oam:
                    oam_series[f"{s}+{b}"].append(
                        rd(MemoryType.SnesSpriteRam, a, 1))
        if phase == "run":
            real_s = (master_clock() - start) / hz

    out = dict(region=region, rom=spec["rom"], rom_md5=m.rom_md5,
               mc_per_frame=mc_per_frame, master_hz=hz, fps=hz / mc_per_frame,
               frames=frames, real_s=real_s, words=series, oam=oam_series)
    m.close()
    print("SFRGN " + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
