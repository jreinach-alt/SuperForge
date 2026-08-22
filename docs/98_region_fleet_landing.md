# 98 — The fleet converts: region parity across the tree

> Status: LANDED. This note records the sweep that took `tick_scale` from two
> rails to the whole tree, the pin move that came with it, and the two rails
> that stay deferred with their measurements. The requirement is `docs/94`;
> the mechanism and its instrument are `docs/96`; the R0 foundation is
> `docs/97`.

## 1. The result

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

## 4. The two deferrals, so nobody re-litigates them from scratch

- **`rpg`** — the grid stepper welds "8 pixels" to "8 frames": `try_step`
  commits a destination tile and arms an 8-frame slide that moves 1 px/frame,
  and the town avatar renders only at `tile*8`. Scaling the slide desynchronises
  the pixel walk from the frame count; the honest fix re-derives the slide
  from pixels-remaining, which redefines a byte inside `rpg_logic`'s declared
  claim. Deferred until someone owns that redefinition.
- **`split_h_2p_demo`** — 22 followers and two cameras share one baked
  movement LUT with no build-time base to scale, and the state-step form
  measurably overruns the PAL frame (tick counter 423 against 479 frames).
  The named path is a second LUT at the PAL magnitude selected by
  `ES_RGN_PAL`: +1 KB, zero per-frame cost, asset work across seven variant
  images.

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
