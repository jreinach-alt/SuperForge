# racer oracle — the control-gated steer scenario (design record)

`templates/racer/oracle.json` scenario `steer_rotates_floor` proves that
steering LEFT vs RIGHT actually rotates the rendered Mode 7 floor. This file
is the design record for why that scenario is built the way it is; the JSON
description carries only the operational contract.

## Why a naive screenshot diff was invalid

The first form drove a steer and asserted "screenshot changed". It read
~78-88% before/after change on BOTH good and frozen-steer ROMs, because the
floor animates independently of steering (palette cycle, day-night tint,
forward motion) — it PASSED on a broken ROM. Indirect-evidence tests are
worse than no tests; this was the racer's worked example.

## The axis-branch form and the residual trap

The replacement drives LEFT and RIGHT from one shared baseline
(`axis_branch`): reload, re-apply the same prelude per branch, so palette
phase and forward distance match and the only difference between the two
endpoint screenshots is the steer direction. Frame-deterministic stepping
(`align_frame` absorbs boot jitter) plus a `phase_guard` asserts the
per-branch heartbeat ($E010) and day-night phase ($E014) match.

Stress-testing still found a RESIDUAL spurious pass (1 in 55): a per-capture
render-phase BUCKET is assigned independently to each load->capture
sequence — identical in every queryable field (R_POSX/Y, R_ANGLE, $E010,
$E014, ppu_frame_count) yet differing 6.5-91% in the framebuffer. A
frame-count guard is blind to it.

## The shipped fix: same-direction controls (D_stable + retry)

Each direction also captures a SAME-DIRECTION control run. The diff(L,R)
reading is trusted ONLY when diff(L,L') <= control_eps AND diff(R,R') <=
control_eps — both directions internally bucket-stable. A confounded control
re-drives that direction (a fresh load re-rolls the bucket, up to
`max_retries`; fail-loud if exhausted), and the `screenshot_axis_diff`
`control_axes` gate is the in-assert backstop.

Validation, >=100 good + >=100 frozen alternating runs with the gate active:

- GOOD floor diff(L,R) = 42.4% (rock-stable)
- CONTROL-GATED frozen diff(L,R) <= 0.4% (kart H-flip lean-frame noise; the
  up-to-91% raw bucket distance is rejected by the control gate before it
  reaches the diff)
- 0 spurious passes, 0 good failures; margin ~42 pp at `min_frac` 0.15.

NB: the control-gated frozen ceiling (0.4%), NOT the raw bucket distance, is
the discrimination figure.

## Round 3: freeze the floor (S6 hardening — the deterministic fix)

The round-2 gate was still probabilistic: after the S3 racer remediation spread
the perspective rebuild across two frames, the same-direction control's diff no
longer fell under `control_eps` within `max_retries`, and the scenario failed
intermittently ("same-direction control diff 26.3% > eps 2%").

Re-diagnosed on the emulator (not from this record): the rebuild pace counter
`R_PVPH` ($5A) is ALREADY idle (0) at every capture, so the 2-frame pacing was
never the discriminator. The real confounder is that the racer floor ANIMATES
every frame independently of steering — the palette cycle, the day-night blend,
AND forward coast-scroll (the kart coasts after B releases). `take_screenshot`
after a `load -> drive` carries a 1-frame presentation-lag "render bucket": two
independent same-direction captures land one ANIMATED frame apart and read a
large floor diff. Measured: the same-direction diff is bimodal, 0% or ~21%, and
even-frame settling (2/4/6 neutral frames) does NOT collapse it — an animating
floor differs frame-to-frame regardless of parity.

The deterministic fix: stop keying on a lucky bucket and FREEZE the floor before
capturing. The `axis_branch` drive gained opt-in freeze params; the racer scenario
sets `freeze_button: "start"` so, after the steer hold, the harness taps START —
`R_PAUSE` ($5E) stops the palette cycle + day-night clock + camera (a tested
feature: `test_racer_pause_freezes_world`) — reads `R_PAUSE` back to prove the
freeze took (fail-loud), and captures a true freeze-frame that renders identically
on every run while the steered heading is held. `freeze_settle` lets an in-flight
rebuild finish so the frozen floor shows the FINAL angle; `freeze_post` lets the
pause engage. Every branch runs the identical extra frames, so the frame-count /
animation-phase guard still holds; `control_branches` stays on as an in-assert
backstop (now trivially satisfied).

Validation (S6): `diff(L,L') = 0.00%` across independent load pairs (R_PAUSE=1),
`diff(L,R) = 94.8%` (a large, clean steering signal), and
`pytest tests/test_oracles.py -k racer` 5/5 consecutive green (was intermittent).
Under the freeze the calibration figure is the frozen control ceiling (~0%) vs the
~95% steering diff — a far wider margin than the round-2 animated capture's 42% /
0.4%.
