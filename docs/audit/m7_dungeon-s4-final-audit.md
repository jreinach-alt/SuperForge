# m7_dungeon S4 enemy system — FINAL independent audit

**Agent role:** independent AUDIT (did not implement). Audit Protocol close for the
`m7_dungeon` rail S4 enemy system (invisible-enemy fix + forward-vs-inverse Mode 7
floor-glue fix + spread-across-maze culling-by-visibility).
**Branch:** `claude/m7-s4-auditF` (worktree off `origin/claude/m7-dungeon-s4-place` @ `8b240b3`).
**Verification only — NO code changes.** All evidence from the cycle-accurate emulator
(Mesen2 headless) reading the RENDERED OUTPUT (OAM = where sprites actually draw +
framebuffer pixels), never a same-formula projection oracle.

## AGGREGATE VERDICT: **VERIFIED** (PASS)

All five acceptance criteria pass under independent re-derivation. The committed suite is
green (21/21), all three gates clean, and my own framebuffer/OAM detectors — which do NOT
share the ASM projection formula — confirm the fix on the rendered floor across a full turn.
One stress flag (E1 OAM x in the 256..511 range while not parked) was investigated to ground
and is **benign** (correct 9-bit off-screen placement, zero rendered pixels, no ghost) — filed
as an observation, not a defect.

---

## Re-run of the committed suite + gates (VERBATIM)

```
make m7_dungeon                                  -> built build/m7_dungeon.sfc
build_m7_dungeon_variants.sh                      -> nocol, far, goalspawn, projfwd .sfc
python -m pytest tests/test_m7_dungeon.py -v      -> 21 passed in 159.56s
make width-check     -> clean (108 files)
make zp-check        -> 0 finding(s); 165 DP symbols / 204 bytes
tools/cleanroom_check.sh -> cleanroom: clean
```

`test_s4_floor_regression_fails_on_forward_build` **exists and passes** on the default build
(it asserts the buggy forward-build FAILS the floor check). ROM md5: default
`e8a41fd1…`, projfwd `81847890…`, goalspawn `ffb0832a…`.

---

## Criterion 1 — enemies GLUED TO THE FLOOR under rotation — **VERIFIED**

Method (independent of the ASM formula): rotate in place (hold LEFT) through 11 distinct
headings across a full turn; for each ON-SCREEN enemy read its drawn centre **from OAM**
(rendered output), sample a framebuffer annulus (r 7..11) around that drawn centre, classify
each pixel FLOOR (blue checker, b≥r) vs WALL (terracotta, r≫b).

| angle | enemy | drawn (sx,sy) | floor px | wall px | verdict |
|------:|:-----:|:-------------:|---------:|--------:|:-------:|
|   0 | E0 | (168,112) | 196 | 15 | FLOOR |
|  24 | E0 | (160,134) | 188 | 27 | FLOOR |
|  48 | E0 | (143,149) | 181 | 30 | FLOOR |
|  72 | E0 | (120,151) | 184 | 30 | FLOOR |
|  96 | E0 | ( 99,140) | 185 | 28 | FLOOR |
| 120 | E0 | ( 88,118) | 204 | 13 | FLOOR |
| 144 | E0 | ( 90, 96) | 219 |  2 | FLOOR |
| 168 | E0 | (105, 78) | 215 |  4 | FLOOR |
| 192 | E0 | (128, 72) | 209 |  8 | FLOOR |
| 216 | E0 | (150, 78) | 212 |  6 | FLOOR |
| 240 | E0 | (165, 96) | 220 |  2 | FLOOR |

On FLOOR at **every** angle (floor 181–220, wall 2–30, floor always >2× wall). The drawn
centre traces a clean circle about screen centre (128,112) — the enemy orbits WITH the floor
(glued to its world tile), not pinned on screen. A finer adversarial sweep (32 angles, every
8 units over a full turn) shows zero non-floor on-screen samples. Renders:
`build/_audit_fixed_a0.png`, `build/_audit_fixed_a96.png` (a96 = floor rotated 135°, E0 on the
dark-blue corridor to the left, hero centred + upright).

## Criterion 2 — NON-VACUITY of the floor guard — **VERIFIED**

Built + ran the committed `-DENEMY_PROJ_FORWARD` ROM myself through the same detector:

| angle | enemy | floor px | wall px |
|------:|:-----:|---------:|--------:|
|   0 | E0 | 196 |  15 (FLOOR — angle-0 calibration) |
|  24 | E0 |   0 | 225 (WALL) |
|  48 | E0 |   0 | 219 (WALL) |
|  72 | E0 |   0 | 219 (WALL) |
|  96 | E0 |   0 | 224 (WALL) |
| 120 | E0 |  92 | 130 (WALL) |
| 144–240 | E0 | 0 | ~217 (WALL) |

The buggy forward-matrix build lands enemies on WALLS at **every** rotated angle (12/12
on-screen samples wall-dominated; floor≈0). At angle 0 both builds agree (on floor); the
drawn centre orbits the OPPOSITE direction (e.g. a24 fixed=(160,134) vs buggy=(161,89),
mirrored across y=112), the signature of the forward-vs-inverse error. The fix is real and the
regression test would catch a relapse. Render: `build/_audit_projfwd_BUGGY_a96.png` (red enemy
on terracotta wall vs floor in the fixed build).

## Criterion 3 — CULLING by visibility (drop / pop) — **VERIFIED**

Independent detectors: OAM park-state (rendered) + enemy-red framebuffer pixels. The red
classifier was tuned on-emulator to discriminate the enemy's saturated reds (g<70) from the
terracotta wall (g≈90) so a whole-frame red count isolates the enemy(ies) actually drawn.

**Spawn (pos 116,116, angle 0):**
- E0: OAM x=160 y=104 **ON**, drawn (168,112), 67 enemy-red px.
- E1: OAM y=$F0 (240) **PARK**.
- E2: OAM y=$F0 (240) **PARK** — whole-frame enemy-red = 67 (= E0 only), so E2 is genuinely
  dropped (zero rendered pixels, not merely hidden).

**Near goal (drove committed `assets/maze_route.json`, ended pos 363,363 ≈ goal 356,356):**
- E2: OAM x=128 y=149 **ON** (un-parked), drawn (136,157), 60 enemy-red px — **popped in**.
- E0, E1: **PARK**. Whole-frame enemy-red = 60 (= E2 only). Clean handoff.

Render: `build/_audit_cull_spawn.png` (only E0 visible, to the right) /
`build/_audit_cull_neargoal.png` (E2 popped in below the hero).

**Cull-boundary wrap stress:** drove the full route one frame at a time (and a separate full
360° spin), checking every frame for an on-screen OAM entry at a wrapped x. Zero on-screen
wrap artifacts. See the observation below for the off-screen-margin sprites the spin flagged.

## Criterion 4 — NO REGRESSION — **VERIFIED**

All 21 committed tests green (S1 boot/textured-floor, S2 turn/forward/reverse/aliases, S3
collision incl. far-room, slide, no-tunnel, negative-control, maze-route-reaches-goal, and all
S4). Hero renders cyan + centred + upright at every sampled angle (OAM slot 0 stable; visually
confirmed in every render). S3 collision unaffected (the route reaches the goal; far-room +
slide tests pass).

## Criterion 5 — scale=1.0-only validity of transpose-as-inverse — **VERIFIED / NOTED**

`SCALE_VIEW = $0100` (1.0), passed to `sf_boss_matrix` at both spawn (main.asm:280) and every
frame (main.asm:435). The world→screen projection uses the matrix TRANSPOSE as its inverse
(`proj_dot M7A,M7C` / `M7B,M7D`), which equals the true inverse **only** because the forward
matrix is a pure rotation — i.e. only at scale 1.0. If `SCALE_VIEW` ever changes from $0100 the
transpose stops being the inverse and the floor-glue breaks; this constraint is documented in
the code (main.asm:154-157, 797-802) and is currently honored. No zoom path exists in S4.

---

## Observation (NOT a defect) — off-screen sprites kept at a 9-bit X within the cull margin

A full-360° adversarial spin flagged E1 (mid-path enemy) at a handful of angles with OAM
x in 255..499 and y in the bottom band while OAM y ≠ $F0 (so "not parked"). Investigation to
ground:
- At these frames E1's projected screen pos is just inside the 16px `CULL_MARGIN` (e.g. angle
  8: proj (269,221) → not culled), so the ROM keeps it in OAM rather than parking at $F0.
- OAM x=263 has **bit 8 set**, which the engine routes to the OAM high table (sprite_engine.asm
  ~line 131) → hardware places the 16px sprite at screen X=263 (off the right edge), NOT
  wrapped to the left.
- The framebuffer at every such frame has **exactly one** enemy-red blob (~56 px, the single
  on-screen enemy); there is **no ghost / no left-edge wrap / no second sprite**.

So this is correct hardware behavior, not the wrap artifact criterion 3 warns about. It is
worth noting only because a naive "OAM y≠$F0 ⇒ visible" reading would over-count; the kit's
park-at-$F0 convention is for the FULLY-culled case, while sprites within the 16px margin are
left at a correct off-screen 9-bit X. No change recommended.

---

## Method notes / how to reproduce

Driver + detectors (audit scratch, in the materialized kit, not committed to the rail):
`/tmp/aF_kit/audit_driver.py`, `audit_c1_floor.py`, `audit_c3_cull.py`, `audit_stress.py`.
Floor/wall via framebuffer annulus around the OAM-drawn centre; enemy presence via a
g<70 red discriminator validated on-emulator against the terracotta wall. None of these read
the ASM projection formula to decide WHERE to look — the prior validation failure (a
same-formula oracle that passed while enemies were on walls) is not repeated here.
