"""Render the smelter rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_smelter.py [outdir]

Boots build/smelter.sfc and photographs the whole of what the rail is for, on
ABSOLUTE frames: the title in mode 1 with text on BG3, the works in mode 2 with
BG3 read as a column table, the same works further round the phase loop, the
flat control inside the scene, and the title returned to — which is the frame
that shows BG3 got its meaning back. No assertions; this exists so a human can
LOOK at the ROM the suite just called green.

THE PAIR THAT CARRIES THE POINT is `works` and `works_flat`. They are the same
scene, the same transfer, the same 64 B into the same VRAM row; the only
difference is WHICH of the blob's 65 rows moves. If the running frame is not
visibly the flat frame with its columns lifted out of it, the composition is
not doing what it claims.

THE SECOND PAIR IS `title` AND `title_returned`, and it is the hygiene half.
`works` leaves BG3SC pointing at a page of scroll words, so the returned title
is what the text layer looks like AFTER a scene used BG3 as data. It must be
indistinguishable from the first one — `bg_text`'s four BG3 registers are all
in its `scene_writes` and the title's enter writes all four, for exactly that
reason. A rail that skipped them would render offset words as glyphs, and that
is what these two frames are here to rule out.

AND `title` AND `works_flat` ARE THE SAME PICTURE IN TWO DIFFERENT MODES. BG1
and BG2 are 4bpp under mode 1 and mode 2 alike, so the identical CHR, maps and
palettes draw the identical world; the title writes BG1VOFS/BG2VOFS to the two
values the flat control row carries. Put those two frames side by side and the
only difference is the text.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
two runs photograph the same instants and a visual diff means something. No
wall-clock anywhere. NOTE Machine.screenshot itself costs one emulated frame,
so the frame arithmetic below is the drive's own rather than free-standing
timestamps.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine  # noqa: E402

ROM = SUPERFORGE / "build" / "smelter.sfc"

# The beats, in ABSOLUTE emulated frames — the same ones tests/test_smelter.py
# drives, so a render and an assertion are talking about the same instant.
TITLE = 40              # past the fade-in
SETTLE = 90             # title -> works, both ramps, then a settled run
SHOW = 20               # long enough for a toggle to reach the PPU
HALF_CYCLE = 85         # far enough round the 64-phase loop to be a different
                        #   picture: 0.375 phases a frame, so ~32 phases


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name, note):
        p = out / f"smelter_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:16s} -> {p}   {note}")

    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        shot(m, "title", "mode 1 — BG3 is a text layer over the same world")

        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "works", "mode 2 — BG3's map read as one scroll offset per "
                         "8-pixel column; four plates on four harmonics and "
                         "the melt erupting between them")

        m.advance(HALF_CYCLE)
        shot(m, "works_phase", "further round the phase loop — a different "
                               "row of the same table over the same art")

        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        shot(m, "works_flat", "B: the flat control row, inside the scene. "
                              "Same channel, same 64 B, same destination — "
                              "only the values move, which is what makes it "
                              "the control every per-column measurement is "
                              "taken against")

        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "title_returned", "the title after `works` pointed BG3SC at a "
                                  "page of scroll words — indistinguishable "
                                  "from the first frame")

    print(f"\n{len(shots)} render(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "build/shots/smelter"))
