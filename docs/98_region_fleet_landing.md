# 98 — The fleet converts: region parity across the tree

> Status: LANDED. This note records the sweep that took `tick_scale` from two
> rails to the whole tree, the pin move that came with it, and the two rails
> that stay deferred with their measurements. The requirement is `docs/94`;
> the mechanism and its instrument are `docs/96`; the R0 foundation is
> `docs/97`.

## 1. The result

> **AMENDED 2026-08-24.** `split_h_2p_demo`, one of the two deferrals below,
> has since been converted by the path §4 named for it. The tree's live counts
> are therefore **29 of 37 composing** and **one deferral** (`rpg`); the band
> is unchanged. §4's `split_h_2p_demo` entry carries the addendum and its
> measurements. Everything else in this section is the sweep's own result and
> stands as it landed.

**28 of the 37 rails now compose `region` + `tick_scale` and run at measured
speed parity on PAL** — every playable game in the tree. The measured band
across the registry's observables is **0.994–1.027** against an uncompensated
0.832, with every shortfall from 1.000 explained by a named mechanism
(integer-step quantisation, a semi-implicit integrator's half-step sampling,
a level's own collision probes) rather than left as noise.

- **7 rails are exempt by design** — the determinism rigs, whose
  frame-indexed sweeps are their subject (`split_v_seamtrial`'s absolute-frame
  picture claims, the `split_h_*` demos, `seam_irq_trial`). Each states its
  reason in its own `game.toml`.
- **2 rails stay deferred, each with its measurement** (§4).

NTSC is untouched everywhere: the oracle's NTSC column is unmoved on every
converted rail, `tools/tb_picture_diff.py` reads NTSC pixel-identical against
every pre-change image, and every rail's own test module passes unmodified.
No gallery clip needed re-recording — the NTSC picture is the same picture.

## 2. The doctrine the sweep settled

Every number is classified by its **dimension**, not by where it sits:

| kind | treatment |
|---|---|
| velocity (px/frame) | × r once (r = 1.2018039, the measured frame ratio) |
| acceleration (px/frame²) | × r² — the second r rides the base on the PAL arm; `tick_scale` itself supplies one gain and was not touched. Arcs keep their apex to ~1% (the residue is the integrator's sampled half-step, derived in the jumper ledger) |
| small integer step | through `TS_STEP` with the fraction carried |
| playhead into a baked per-frame table | the cursor is scaled; the table stays byte-identical |
| countdown / duration | stays integer, disclosed (a PAL swing window is 20% wider; a PAL round count runs 0.43 s longer) |
| event per button press | not a rate; never scaled |

A consumer declares two `u16@dp` per scaled rate. `tick_scale` claims nothing
of its own and `depends = ["region"]`, which auto-includes the flag.

## 3. The pin moved with the flagship

`microzero.sfc`: **`e45ddeabac4218cd71709da7b9fcc849` →
`dea58053943943d693d85f89506a2bba`**, reproducible from a wiped build tree,
per `docs/94` §4.2's amended clause. The five live sites of the old value were
updated by value-enumeration in the conversion commits; the historical docs
keep the old value as the record of what was true when they landed. Both
falsification suites were re-run against the new pin and fired 6/6 and 3/3 —
the pin binds, it is not decoration.

The flagship's streaming margin was the one close number: PAL-compensated top
speed stages a worst case of **8 tile-crossings against a clamp of 8**, and
the proof is the deferral counter — `CAM − LAST` at the park point read **0 on
all 3,600 measured frames**, both regions, flat out and sweeping every
heading. `mode7_stream` itself is untouched.

## 4. The deferrals, so nobody re-litigates them from scratch

*(Two when this landed. One of them, `split_h_2p_demo`, has since been
converted — its entry carries the addendum. Both entries stay: the reasoning is
the record, and the converted one is also the worked example of what the path
it named actually cost.)*

- **`rpg`** — the grid stepper welds "8 pixels" to "8 frames": `try_step`
  commits a destination tile and arms an 8-frame slide that moves 1 px/frame,
  and the town avatar renders only at `tile*8`. Scaling the slide desynchronises
  the pixel walk from the frame count; the honest fix re-derives the slide
  from pixels-remaining, which redefines a byte inside `rpg_logic`'s declared
  claim. Deferred until someone owns that redefinition.

  > **Addendum, 2026-08-24 — DISCHARGED.** Someone owned it. `rpg_hot + 12` is
  > now `step_px`, the PIXELS REMAINING to the destination tile: `try_step`
  > arms it to `TILE_PX`, the walk lays down the whole pixels `TS_STEP`
  > publishes for a base of 1 px/frame, and arrival is that distance reaching
  > zero. Nothing is welded — the tile is 8 px on both machines and the frames
  > it takes are the region's answer. The town's `town_rep` was converted with
  > it: the same published step, spent in throttle units, with the overshoot
  > carried into the next tile rather than dropped.
  >
  > **The deciding frame had to come out of the same budget, and a pixel scale
  > alone would have missed it.** A held direction is 8 px over NINE frames
  > here — eight walking, one deciding, because the frame that finds the walk
  > at rest arms the next tile and moves nothing. Scaling only the eight gives
  > PAL 1 + 6.65 frames against NTSC's 1 + 8 and measures **0.975**, outside
  > §1's band. So the frame's budget is spent WHOLE: a frame that arrives with
  > pixels still in hand decides and keeps walking. On NTSC the budget is
  > exactly one pixel and the tile exactly eight, so a frame can never arrive
  > with a pixel left over — the deciding frame is never free and the walk is
  > the same nine frames it always was. That is the same objection
  > `m7x_logic`'s "THE GRID STEP IN TWO REGIONS" raised against a pixel budget
  > on `mode7_explore`; this rail answers it inside the budget instead of by
  > scaling the tick.
  >
  > **Measured** (`tools/rate_oracle.py`, 2026-08-24):
  >
  > | observable | NTSC/s | PAL/s | ratio | uncompensated |
  > |---|---|---|---|---|
  > | `rpg` `m7_path` — the Mode 7 camera origin | 53.430 px | 53.508 px | **1.00145** | 0.83142 |
  > | `rpg_town` `avatar_x` — the avatar's OAM X byte | 60.015 px | 60.675 px | **1.01100** | 0.83324 |
  >
  > The town needed a registry entry of its own (`rpg_town`, same image, same
  > map) because its rate is tiles per second and not the plane's pixels, and
  > it needed the module's `drive` hook — the first use of it — because the
  > plaza row is walled at both ends and a seconds-indexed shuttle short
  > enough to fit beat against the frame grid until the avatar parked (NTSC
  > halves 60.10 then 55.94 against PAL 60.01 and 61.34). The replacement
  > reverses on the avatar's own drawn position and never reads the frame
  > index.
  >
  > **NTSC is unmoved.** Both oracle NTSC columns are identical to their
  > pre-change readings; `tools/tb_picture_diff.py` reads NTSC pixel-identical
  > against the pre-change image in BOTH scenes (overworld, `--pad down`,
  > frames 120/300/600; town, `--pad up`, frames 60/75/90/300), with PAL
  > differing on both — the non-vacuity control. A per-frame trace of the
  > camera origin, both camera tiles, the town tile and the avatar's OAM is
  > byte-identical to the pre-change ROM over 200 frames on both drives.
  >
  > The save torch's `town_flare` stays an integer 12 frames — §2's disclosed
  > countdown row — so a PAL flare runs 0.24 s against NTSC's 0.20 s. The
  > mosaic wipe and the boot fade are the same class and are equally untouched.
  >
  > **§1's headline counts are left as the sweep landed them** and are not
  > edited here: they are one of several records of the same census, and
  > moving one of them alone is how two documents start disagreeing. They are
  > reconciled together, not rail by rail.
  >
  > `tick-check`'s baseline moves 356 → 350 with it, and only on this rail:
  > three of its ten entries WERE the deferral (`RPG_STEP_DX`'s per-frame
  > comment, `RPG_STEP_N`'s "frames left in the slide", `STEP_FRAMES = 8`) and
  > are gone; three more now carry a written reason; four moved and are
  > re-anchored unchanged. §5's "the baseline held at 356" is the record of the
  > sweep, not a pin.
- **`split_h_2p_demo`** — 22 followers and two cameras share one baked
  movement LUT with no build-time base to scale, and the state-step form
  measurably overruns the PAL frame (tick counter 423 against 479 frames).
  The named path is a second LUT at the PAL magnitude selected by
  `ES_RGN_PAL`: +1 KB, zero per-frame cost, asset work across seven variant
  images.

  **ADDENDUM, 2026-08-24 — CONVERTED, by that path.** `sh2_move256` is now a
  2 KB claim holding two arms of the same table: 2.0 px per NTSC frame at
  offset 0 and **2.40361** px per PAL frame one stride on, the ratio read out
  of `tick_scale.asm`'s `TS_GAIN_NUM`/`TS_GAIN_DEN` rather than copied. A
  scene-enter read of `ES_RGN_PAL` picks the arm into one `dp` word, which is
  ORed into the `h * 4` index the camera drive and every follower already
  build — so the state step is **not** repeated and the overrun shape does not
  return: the scene tick reads **479 against 479 VBlanks in both regions**,
  where the state-step form read 423.

  **`tick_scale` is composed as well, for the one rate the pair cannot
  carry.** A held D-pad steps a heading one pose per frame and a follower's
  steering correction is the same ±1 — a rate in the LUT's own INDEX, which no
  table indexed by heading can hold. With the arms alone the translation
  reaches parity and the ROTATION stays at 0.832, which flies the camera round
  a circle 1.2 times too wide; the registry's `cam1_head` observable is exactly
  that number. So the heading goes through `TS_STEP`: **one expansion per
  frame**, published to both cameras and all 22 followers, which §2's sharing
  rule allows because all three are the same base rate.

  Measured, 14 s real-time window, pad 1 holding B + RIGHT:

  | observable | before | after |
  |---|---:|---:|
  | `cam1_x` | 0.80538 | **1.00063** |
  | `cam1_y` | 0.86167 | **0.99969** |
  | `cam1_head` | 0.83208 | **1.00088** |

  NTSC is untouched by both the §1 standard and a stricter one: the oracle's
  NTSC column reads 76.106099 / 76.606327 / 60.098807 px or units per second
  **before and after**, and the parent plus **all seven `-D` variant images**
  are pixel-identical against their pre-change captures at frames 120/300/600.
  The variants' md5s moved — the tables changed — and the pictures did not.
  The rail also ships a gallery clip from the `sh2_autocam` arm
  (`reports/gallery_loop_seams.md`).

## 5. What the sweep found beyond its brief

- `pfs_logic`'s landing snap put the player a whole tile high on its first
  row — NTSC's slower fall never reached it; PAL's faster step did. Fixed,
  NTSC-identical under four drives. **A region scale does not create that
  defect class — it reaches it.**
- The `tick-check` baseline held at **356 through the entire sweep** — no
  conversion added a frame-coupled site, and none was silently suppressed
  (two lanes caught the override radius blanking neighbours and separated
  their annotations).

## 6. What this does not do

R1 (the taller PAL active area) is designed (`docs/95`) and unbuilt. Audio
keeps real time on both regions and is documented, not compensated
(`docs/95` §5.6). Nothing here has run on hardware or a second emulator —
`docs/95` §10's list carries forward unchanged.
