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

| rail | loop point | mad | pct>16 | first | last | bytes |
|---|---|---:|---:|---:|---:|---:|
| `mode7_flight` | a closed circuit — a full 256 units of heading returns the world position, flown at the day/night step whose 12-step span costs least | 4.22 | 5.8% | 101.2 | 104.4 | 1,330,530 |
| `m7_oshoot` | out and back — the pad is exactly reversible, so the take closes on the opening heading and both position words | 1.25 | 1.3% | 62.9 | 63.7 | 381,232 |
| `split_v_fight` | the cycle itself — apart, through, apart swapped, back through, cut on the merge | 5.40 | 9.5% | 117.8 | 118.6 | 512,763 |
| `mode7_explore` | the spawn tile — an idle capture at (258,258) facing Down, walked back to exactly | 0.00 | 0.0% | 84.0 | 84.0 | 746,911 |
| `meteor_event` | the restored level — the event hands back a walkable Mode-1 level with the player at a fixed screen x | 3.22 | 3.3% | 23.0 | 23.0 | 60,649 |
| `boss_saucer` | **the fade** — `su_result` runs `fade_start_out`, and the scene re-arms the same ramp behind the black | 0.00 | 0.0% | 0.0 | 0.0 | 1,045,923 |
| `railshooter` | the rail's own period — `rs_path` repeats every 256 frames, and a 3-frame capture grid realigns at three of them | 4.15 | 3.9% | 69.6 | 70.4 | 913,654 |
| `microzero` | the title card — title → race → results → title, closed on purpose | 6.11 | 1.5% | 28.5 | 34.4 | 820,884 |

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
- **`microzero`** — the residual *is* the claim. The clip opens on
  `SCORE 0000 LIVES 3` and closes on `SCORE 012C LIVES 2`: globals surviving
  the scene edges, which is what the rail exists to prove.
- **`meteor_event`** — the walk is one-way and the camera does not return, so a
  couple of platforms sit a few tiles left of where they opened. It stays small
  because the event freezes the level for most of the clip.
- **`split_v_fight`** — the fighters cross twice per circuit and the pair's
  midpoint drifts as they do. Measured: the take opens at
  (spread 0, FX1 108, FX2 148) and comes back through (spread 4, 88, 136) and
  (spread 0, 148, 46) — separation and spread return, the midpoint has walked
  16 px left, and no capture holds all three at once. Driving for an exact
  close ran the take to its ceiling and parked 41% of its transitions at the
  walls, which is worse on both counts, so the clip is cut on the cycle its
  beats already form.

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
`mode7_flight` waits out 577 of them for its hour.
