# Gallery loop seams

Every clip under `docs/img/` loops forever, so the join from its last frame
back to its first is the one cut a viewer actually sees. It is the only edit in
the file, and it is measured rather than eyeballed.

`tools/gif_seam.py` reads the numbers back out of the **written GIF**, decoded
through the palette the file ships, and `tools/record_pres_gif.py` prints them
on every recording.

- **mad** — mean absolute difference per channel across the join, 0..255.
- **pct>16** — percentage of pixels whose largest channel difference clears 16,
  i.e. the fraction of the screen that visibly changes at the wrap.
- **first / last** — each end's own mean luma. A clip that ends on black only
  rejoins invisibly if it begins on black too, so both ends are reported.

**WHAT THIS METRIC CANNOT SEE, measured rather than supposed.** The numbers are
read back through the palette the GIF ships, so on a rail whose sky is DITHERED
the figure is dominated by how that shared <=128-colour palette quantises the
dither, not by how the two ends register. Two `racer` takes whose raw endpoint
screenshots measured identically (mad 4.66, sky 5.62, floor 4.43, on both a
pre-fix and a post-fix ROM) scored 2.48 and 4.91 here, purely on the colour
census: removing two thirds of the diagonal centre-line yellow changed which
colours the palette could afford, and stopped it hiding the sky. An earlier
edition of this file claimed `racer`'s sky band contributed ZERO pixels to the
seam; that was a palette result reported as a picture one, and it is withdrawn.

**And 0.00 has two different causes here.** On `split_v_fight`,
`boss_saucer` and `mode7_explore` it is a flat sky the shared palette has
nothing to be short of. On `lakeside` and `heathaze` it is stronger and
narrower: **the two ends are ONE FRAME**, because each take is cut on the
EFFECT'S OWN ANIMATION PERIOD. `heathaze`'s picture is a pure function of
`ES_HZ_PHASE` and comes back to the frame it opened on 57 captures later, and
again at 114; `lakeside`'s is a pure function of `ES_WAT_SCROLL` and comes back
after 128; `smelter`'s is a pure function of `ES_SMT_PHASE` and comes back
after 57. All three intervals were
measured the same way rather than derived — drive the recorder's own 3-frame
grid, compare decoded frames byte for byte, take the first index that repeats
capture 0 — and both hold at the strongest available reading: **0 differing
pixels of 61,184**, on the RAW captures before quantisation AND on the frames
decoded back out of the written GIF. On these three the metric is agreeing with
a picture, not with a palette.

`smelter` adds one thing the other two did not have to state: **a return of the
ANIMATION'S OWN COUNTER is not automatically a return of the picture.** Its
phase advances 0.375 a frame through `TS_STEP`, which publishes whole units and
carries the rest, so 57 captures is 64.125 phases — the loop plus an eighth the
accumulator is still holding. Measured over 384 captures from its own anchor:
the phase returns at 57, 114, 171 and 228, and the frames pixel-identical to
the opening one are 57, 170, 227 and 284. The eighth tips a whole phase at
irregular multiples, so 114 is one phase out and the others are not. The drive
still closes on the PHASE — that is the ROM's own account of where the
animation is — and which return it closes on is what the measurement decided.

Those two used to reach 0.00 by returning to the TITLE, which was the same
statement about a different edge: the composed state is per scene, so the title
returned to is the title departed from. **That claim did not go anywhere** —
`tests/test_lakeside.py::test_the_title_scene_does_not_inherit_the_lake_blend`
and `tests/test_heathaze.py::test_the_title_returns_undisplaced` assert it
bit-for-bit, and `tools/shot_lakeside.py` / `tools/shot_heathaze.py` render the
pair for a human. It is off the gallery clips because at 20 fps a title card
between two fade ramps does not read as a scene change, it reads as a FLASH —
and because it was costing 62 of `lakeside`'s 166 captures and 54 of
`heathaze`'s 120, so between a third and a half of each clip was the one
picture with none of the effect in it.

Read a figure on a flat-sky rail (`split_v_fight`, `boss_saucer`,
`mode7_explore`, all 0.00) as a statement about the join — and
`split_h_2p_demo` reads that way too, for a different reason: its whole world
is five flat colours, so there is nothing for a shared palette to be short of.
Read one on a
dithered-sky rail (`racer`, `railshooter`, `mode7_flight`) as a statement about
the join AND the quantisation together, and compare it only against another
take of the SAME rail. Tuning a loop mark against this number across rails is
tuning against the palette.

| rail | loop point | mad | pct>16 | first | last | bytes |
|---|---|---:|---:|---:|---:|---:|
| `mode7_flight` | a closed circuit — a full 256 units of heading returns the world position, flown at the day/night step whose 12-step span costs least | 4.04 | 5.7% | 101.0 | 104.3 | 1,326,866 |
| `m7_oshoot` | out and back — the pad is exactly reversible, so the take closes on the opening heading and both position words | 1.25 | 1.3% | 62.9 | 63.7 | 381,232 |
| `split_v_fight` | **the round start** — the count's FIGHT beat, where `round_arm` has put both fighters back on their marks and the spread has eased to zero | 0.00 | 0.0% | 104.3 | 104.3 | 258,718 |
| `mode7_explore` | the spawn tile — an idle capture at (258,258) facing Down, walked back to exactly | 0.00 | 0.0% | 84.0 | 84.0 | 746,911 |
| `meteor_event` | the restored level — the event hands back a walkable Mode-1 level with the player at a fixed screen x | 3.22 | 3.3% | 23.0 | 23.0 | 60,649 |
| `boss_saucer` | **the fade** — `su_result` runs `fade_start_out`, and the scene re-arms the same ramp behind the black | 0.00 | 0.0% | 0.0 | 0.0 | 412,803 |
| `railshooter` | the rail's own period — `rs_path` repeats every 256 frames, and a 3-frame capture grid realigns at three of them | 2.51 | 2.1% | 90.3 | 90.3 | 876,805 |
| `racer` | a mark on the home straight — a flying lap comes back to it at the cap, and the grid is held until the clock puts both ends of the lap on one day-night keyframe | 2.48 | 3.0% | 92.8 | 92.7 | 448,539 |
| `split_h_2p_demo` | the seeded camera pose — camera 1 back on heading 0, which on this build brings both cameras' positions and all four 8.8 fractions with it | 2.89 | 1.9% | 107.5 | 107.1 | 1,260,283 |
| `lakeside` | **three surf cycles** — the take closes where the surface has drifted 384 px, the first whole number of the picture's own 128 px period to land on the 3-frame capture grid | 0.00 | 0.0% | 120.9 | 120.9 | 352,681 |
| `smelter` | **one phase loop** — the take closes where `ES_SMT_PHASE` has come back to the value it opened on, 57 captures later, which is 64 phases and therefore ONE COMPLETE TURN of every plate's harmonic and every jet's at once. Nothing else is in it: the flat control was cut for `heathaze`'s reason | 0.00 | 0.0% | 51.6 | 51.6 | 203,614 |
| `heathaze` | **two phase loops** — the take closes where `ES_HZ_PHASE` has come back twice to the value it opened on, 57 captures apart. Nothing else is in it: the flat control was cut because a second of frozen picture reads as the effect breaking, not as a control | 0.00 | 0.0% | 135.1 | 135.1 | 149,761 |

## Where the residuals come from

A seam of exactly 0.00 means the two ends are pixel-identical. The rest carry a
named residual, and in each case it is something the rail cannot bring round
inside the 2 MB budget rather than a loose cut:

- **`mode7_flight`** — the cloud band rides its own parallax rate and does not
  come round with the ground. The day/night clock cannot come round at all: it
  is 2,048 frames, 34 s at 1:1, so the clip picks its hour instead and opens at
  the step whose span costs 1 unit of zenith colour rather than 21.
- **`railshooter`** — the hazard ring (`RS_OBS_GAP` = 40 frames) shares no
  useful period with the path's 256, and the two HUD counters are monotone by
  design: score climbs, lives spend down.
- **`racer`** — the racing line is a TWO-lap limit cycle: successive arrivals
  at the mark land 8 px apart along the track and every second one lands on the
  same pixel, so a one-lap take cannot register the floor exactly against a
  45 px capture lattice. What those 8 px move is the textured part of the
  floor — the grass checker beyond the kerbs and the centre-line dashes, in the
  far and middle bands. The sky band contributes ZERO pixels to the seam (the
  day-night wash closes on one keyframe) and so does the near road, which is
  why the mark sits 320 px north of the chequer rather than on it: the near
  rows magnify about 3.3 screen px per world px, and closing on the chequer —
  the one high-frequency thing on this circuit — measures 97.64 for the same
  8 px of error.
- **`meteor_event`** — the walk is one-way and the camera does not return, so a
  couple of platforms sit a few tiles left of where they opened. It stays small
  because the event freezes the level for most of the clip.
- **`split_h_2p_demo`** — **the floors close exactly; the residual is entirely
  the cast.** Both cameras' whole state is a function of (frames since enter)
  mod 256 — the 256 forward vectors of one turn sum to zero on both axes and the
  8.8 fractions come back with them — so a take of three turns rejoins the two
  perspective floors pixel for pixel. What does not come round is the swarm: 22
  followers steer toward waypoint loops whose periods share nothing with 256, so
  the markers stand wherever the AI walked them. 1.9% of the picture is about
  what two dozen small sprites cover, which is the check that the residual is
  the one named here. The take cannot be shortened to trim it — 768 frames is
  the FIRST return of the mark to the 3-frame capture grid.
- **`split_v_fight`** — **no residual: 5.40 → 0.00, and the rail is why.** The
  entry above used to describe one that could not be closed: the clip was a
  camera demo whose fighters crossed twice per circuit while the pair's
  MIDPOINT drifted, so separation and spread came round and the midpoint did
  not, and no capture held all three at once. What changed is not the drive but
  the ROM — the rail is a fighting game now, and a fighting game has a round.
  `round_arm` puts both fighters back on their marks and refills both bars, so
  a round start settles all three words at once, by construction. The cut is
  the count's **FIGHT** beat rather than its "3": at the start of a countdown
  the spread is whatever the KO left it at, and 96 frames later it has eased to
  exactly zero from any value inside `SV_SPREAD_MAX`, so the two ends agree
  about the cameras as well as the fighters.

  Three things had to be true and none of them was, at first — the seam is what
  found each one. **(1)** The blades are 32 tall and were parked at the 16-tall
  constant; OAM y wraps mod 256, so sixteen of their rows sat at the top of the
  screen for the whole clip (2.03 → 1.18). **(2)** The whole round has to be a
  multiple of three frames long, because the clip samples every third one —
  `SV_KO_LEN` carries the odd value that makes it so. **(3)** Round ONE opened
  on marks the scene set itself (±20) while every later round used `round_arm`'s
  (±30), so the two ends stood 10 px apart (1.18 → 0.00). All three are
  invisible in play and none is visible to a byte assertion.

  The take has since grown a break-apart and a close-in beat — the fighters
  back off to the arena walls until the ROM reports the spread eased to its
  plateau, then walk back in — which is what makes the divider open and shut
  on camera instead of sitting at zero width for the whole clip. It roughly
  tripled the file (92,646 → 258,718 B, still an eighth of the budget) and did
  **not** move the seam: point (2) above is why it could not, since every beat
  the drive adds is a whole number of 3-frame captures and the round's own
  length is unchanged.

## How a take lands on its loop point

`record_gallery_clip.record_clip` lets a drive **bracket** the take on ROM
state: a falsy `.started` drops lead-in captures, a truthy `.done` closes the
take, and `CAPTURES` becomes a ceiling rather than a schedule. This is the rule
the beats already followed — read the ROM's state, do not count frames to an
event — extended to the first and last beat, because those two are what the
loop is made of. Counting frames to a fade reaching black, or to a heading
coming round, drifts against the ROM's own tick exactly the way counting to a
scene change did.

Dropping is a prefix only, so kept captures stay contiguous and `EVERY` frames
apart, and the 1:1 real-time assertion counts every frame the take consumed,
dropped ones included. A dropped capture pays the screenshot's frame without
taking its picture, which is what makes a long lead-in affordable —
`mode7_flight` waits out 577 of them for its hour, and `racer` 344: the wait
for its hour is spent stationary on the grid, and the out lap that follows is
the ramp to the cap the loop has no way to hold.

**A lead-in does not have to be long to be the point.** `lakeside` drops 11
captures and `heathaze` 16, and what those few carry off the clip is the whole
of the boot, the title card, the Start press and BOTH fade ramps — everything a
viewer reads as a flash at 20 fps. The bracket is what lets that happen without
a frame count: each drive waits for the scene manager to report the effect scene
running with the fade idle at full brightness, and only then opens the take.
Neither clip contains a ramp, so neither one's opening is a guess about how long
a ramp takes.
