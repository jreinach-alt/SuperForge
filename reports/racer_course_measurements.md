# racer — course geometry and handling, measured

Every number here is measured — from the generators (the SSoT for the world
and the physics constants) or on the lockstep `Machine` against
`build/racer.sfc` — not estimated. Emulator probes read `US_SPEED` /
`ES_M7ORG` via `build/rc/symbol_map.json`; that is design instrumentation,
not test surface (the test module reads pixels, per CLAUDE.md rule 2).
The course and the handling are ONE design: the pair a corner actually tests
is (speed cap, road half-width), and both live in
`tools/gen_racer_assets.py` so they move together.

## The world and the course

| fact | value |
|---|---|
| streamed world | 512×512 tiles = 4096×4096 px, torus |
| course shape | a closed 16-corner octilinear loop (`gen_racer_assets.COURSE`): 12 left + 4 right turns — an S-complex off the north straight, a chicane on the bottom straight, one right off the long diagonal |
| track area (road+kerb) | 48,912 tiles = **18.7%** of the world |
| track bounding box | tiles 40..472 × 32..456 = 433×425 (**85% × 83%** of span), legs crossing the interior |
| road width | 33 tiles = 264 px kerb-to-kerb; **29 tiles = 232 px drivable** |
| torus wrap limit | streamed window is camera ±64 tiles mod 512, so painted track must span < 448/axis; the generator asserts it (433 and 425 measured) |
| grass | checker + a ~1/9 quadratic-residue tuft scatter, aperiodic on the window's 128-tile wrap — ground texture at speed, and streamed-VRAM churn stays proportional to distance (the odometer the off-road tests read) |

## Handling against that course

| fact | value |
|---|---|
| top speed | 15.0 px/frame (`RC_SPEED_CAP $0F00`), measured flat from frame 60 |
| acceleration | 0.25 px/f² (`RC_ACCEL $0040`): rest → cap in **60 frames**; the cap divides by the six bar ticks exactly ($0F00/6 = $0280) |
| coast | 0.1875 px/f² (`RC_DECEL`): cap → rest in 80 frames |
| off-road | crawl 4.0 px/f (`RC_GRASS_CAP`), 27% of the cap; drag 1.5 px/f² reaches it from the cap in ~8 frames |
| turn rate | 1 pose step/frame = 5.625°/frame; full-speed turning circle 15×64/2π ≈ **153 px**, 0.66 road widths — every corner is takeable at the cap, and a U-turn inside the road width is not |
| cross the drivable road at cap | 232 px / 15 = **15.5 frames** |
| centre-line → kerb at cap | 116 px / 15 = **7.7 frames** |
| perpendicular escape from rest | measured: drag bites at **frame 31**, 122 px |
| straight-line run from the green flag | measured: on-road to **frame 141** — 1,671 px of start/finish straight before the first corner's run-off |

## The margins, stated

The first corner sits ~1,470 px past the green flag, arriving ~40 frames
after the ramp tops out; a kerb is 7.7 frames from the centre line at the
cap against a 12–15-frame reaction budget, and full lock corrects 45° of
heading in 8 frames — so holding the road is work, and losing it is a
mistake rather than a default. The four right-handers mean both steering
directions carry the lap; the long SE diagonal holds the streamer's
worst case (rows AND columns staged every frame) for 152 tiles at
whatever speed the player carries onto it.
