"""Render the mode7_flight rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_mode7_flight.py [outdir]

Boots build/mode7_flight.sfc and photographs six ABSOLUTE frames along ONE
continuous flight, because this rail's subject is an AXIS and an axis is only
legible as a sequence:

    01 spawn        mid-altitude, hovering, over the coast the spawn is pinned to
    02 ceiling      held R to the top of the climb — the ground has receded, the
                    horizon has filled with world, and the shadow has gone small
    03 floor        held L all the way down — the ground has come up to meet the
                    ship, features are large, and the shadow is the BIG one
    04 back to mid  climbed back to the spawn altitude: the axis is reversible,
                    and this frame should read as 01's altitude over different
                    ground
    05 turned       a quarter turn off the boot heading at cruise altitude, with
                    the throttle held — the heading axis, moving independently
    06 both axes    turning and climbing and thrusting at once, which is the
                    composition the whole factored design exists to make cheap
    07 night        the same flight at the clock's opposite pole: the sky ramp,
                    the horizon fog, the cloud palette and the terrain's own
                    ambient all at their dark end
    08 day          ...and a half cycle after that, back at noon. The pair is
                    the day/night axis, which is the only one here that moves
                    with no input at all

There are no assertions here. This exists so a human (or the maintainer) can
LOOK at the ROM the suite just called green — CLAUDE.md rule 3's "attach a fresh
render from the verified binary", produced from the binary rather than relayed.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
`Machine(rom).advance(n, pad1=...)` parks on an exact emulated frame, so two
runs of this tool photograph the same instants and a visual diff between them
means something. No wall-clock anywhere.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine  # noqa: E402

ROM = SUPERFORGE / "build" / "mode7_flight.sfc"

SETTLE = 90             # past the fade-in and settled, before anything is held
ALT_LEVELS = 81         # the altitude axis's depth — one index per held frame
OVERSHOOT = 20          # ...held past the end stop, so the clamp is in shot
# The day/night clock is free-running at 32 phase units a frame and 1,024 per
# step (gen_m7f_gradient.py), so where the shot lands is arithmetic, not a
# poll: frame 507 above sits on step 31, deep night opens on step 48, and noon
# on step 16. Written as the two gaps so the pair is a pure function of the
# script like every other frame here.
TO_NIGHT = (48 - 31) * 1024 // 32       # 544 frames
TO_DAY = 32 * 1024 // 32                # ...then a half cycle back to noon


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    with Machine(str(ROM)) as m:
        m.advance(SETTLE)

        shots.append(("01_spawn_mid_altitude", m.screenshot))
        m.screenshot(str(out / "m7f_01_spawn.png"))

        # --- the climb, held past the ceiling clamp ------------------------
        m.advance(ALT_LEVELS + OVERSHOOT, pad1={"r": True})
        m.screenshot(str(out / "m7f_02_ceiling.png"))

        # --- the dive, held past the floor clamp --------------------------
        m.advance(2 * ALT_LEVELS + OVERSHOOT, pad1={"l": True})
        m.screenshot(str(out / "m7f_03_floor.png"))

        # --- back to the spawn altitude: the axis is reversible -----------
        m.advance(ALT_LEVELS // 2, pad1={"r": True})
        m.screenshot(str(out / "m7f_04_back_to_mid.png"))

        # --- the heading axis, on its own, under throttle -----------------
        m.advance(64, pad1={"left": True, "b": True})
        m.screenshot(str(out / "m7f_05_turned_under_throttle.png"))

        # --- both axes plus throttle: the composition the design is for ---
        m.advance(30, pad1={"left": True, "r": True, "b": True})
        m.screenshot(str(out / "m7f_06_turning_and_climbing.png"))

        # --- the DAY/NIGHT pair, at the two poles of the clock -------------
        # Frames 07 and 08 are the same flight, photographed a half cycle
        # apart, so the sky ramp, the horizon fog, the cloud palette and the
        # terrain's own ambient are all at their opposite ends. The clock is
        # free-running at 2,048 frames a cycle, so these are
        # ABSOLUTE frames like everything else here — no state is forced.
        m.advance(TO_NIGHT)
        m.screenshot(str(out / "m7f_07_night.png"))
        m.advance(TO_DAY)
        m.screenshot(str(out / "m7f_08_day.png"))

    for p in sorted(out.glob("m7f_0*.png")):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  SUPERFORGE / "docs" / "img"))
