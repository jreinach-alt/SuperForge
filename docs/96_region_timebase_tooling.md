# 96 — Region speed: the instrument, the lint, and a timebase that reaches parity

> Status: TOOLING + PROTOTYPE. It answers `docs/94` §2's ruling of 2026-08-20
> — *"the instrument and the mechanism"* — and it changes no default
> behaviour on either region. The 185-site retune is **not** authorised by
> that ruling and is not attempted here.
>
> `docs/94` is the source of record for the requirement; `docs/95` for the
> measurement pass this sits on; this file is the source of record for **how
> a candidate speed scheme is adjudicated**, and for what the first three
> candidates measured.

## 0. The four things to read first

**One.** *Parity is reachable, and the number is 0.99919.* One tick per frame,
the per-frame delta scaled by the measured frame ratio in 8.8 with the
fraction carried between frames, reads **PAL/NTSC = 0.99919** on the prototype
rail against the uncompensated **0.83208** — a residual of **−0.081%**, an
order of magnitude inside the 1–2% scale a scheme has to be judged at. It
costs **+634 master cycles per PAL frame, 0.15% of the frame**, and that cost
is **O(1) in the size of the tick**, which is the property the refuted scheme
does not have.

**Two.** *`docs/95` §4 refuted 6-ticks-per-5-frames on the tightest rail's
budget, and that refutation is correct and is not a statement about the
console.* Measured here: the scroller returns **+20.1%** of usable per-frame
work under PAL, against the **+16.1%** `docs/95` measured on
`split_h_2p_demo`, and against the **+20.0%** a whole-extra-tick scheme
demands. The return is a function of the RAIL'S FIXED COST (974 mc here), not
of PAL. A light rail clears the bar; the tightest one does not. Both
measurements stand.

**Three.** *The 185 is now a baseline, and the state half of it reproduces
exactly.* `make tick-check` finds **356 sites** across 697 files. Its
`tick-state` check — `docs/95` §5.2's own stated rule, mechanised — reports
**135 declarations across 27 rails**, which is `docs/95`'s number and
`docs/95`'s rail count, to the site. The other classes differ in GRANULARITY,
not in substance, and §3.4 reconciles each one.

**Four.** *A rate oracle must gate its denominator, or it measures the
harness.* The platformer's landing cadence read **0.99969 — PARITY —** while
the rail was plainly running 17% slow, because a real-time-fair input script
presses A at the same cadence in both regions and the hero lands once per
press. Dividing by AIRBORNE seconds instead of by wall seconds turns the same
numerator into a property of gravity and reads 0.81606. Any observable a drive
script can pace needs that treatment (§2.4).

---

## 1. What was missing

`docs/93` reported *"every rail runs at 83.2% of NTSC speed under PAL"* and
`docs/94` §2 made speed parity the requirement. Neither number could be
re-derived on demand. `tools/pal_probe.py` answers the neighbouring question —
*"is frame N the same picture in both regions?"* — and it is deliberately
FRAME-anchored, so it cannot see a speed difference at all: at equal frame
index the two regions agree, and that agreement **is** the bug.

Three things were therefore built, in dependency order:

| # | artifact | answers |
|---|---|---|
| 1 | `tools/rate_oracle.py` | *what is this rail's real-time progress rate, per region, and what is the ratio?* |
| 2 | `tools/tick_lint.py` + `make tick-check` | *how many sites assume one tick is one frame, and has that grown?* |
| 3 | `game/scroller` `-D SF_TICK=n` + `tools/measure_tb_cost.py` + `tools/tb_picture_diff.py` | *does a declared timebase reach parity, what does it cost, and did the NTSC picture move?* |

---

## 2. The rate oracle

### 2.1 What it measures, and why it is not a frame count

A frame counter trivially reports 50 against 60 and says nothing about whether
the player's ship moved the same distance per second. Every observable in the
registry is therefore **game-visible progress**, and each one carries, in the
tool, the sentence that says why it is a fair measure for its rail.

Real time comes from the master clock, which the emulator advances at the
region's own rate — read from the implementing code, not remembered:

```cpp
// Mesen2 Core/SNES/SnesConsole.cpp:209
_masterClockRate = _region == ConsoleRegion::Pal ? 21281370 : 21477270;
```

so real seconds = master cycles ÷ that rate. Both ends of a measurement window
are timed exactly, so the rate is Δprogress ÷ Δreal-seconds with **no
frame-quantisation term**: the two regions' sample instants differ, and each
is exact, and the division is exact. What is left is the observable's own
non-uniformity, and `--halves` prints each half's rate so a reader can judge
it rather than take it on trust. On `scroller` and `brawler` the two halves
agree to the printed digit.

### 2.2 The input script is indexed on SECONDS, and that is load-bearing

A human holds RIGHT for two seconds, not for 120 frames. A frame-indexed
script hands PAL 100 frames of RIGHT where NTSC got 120 — a 5/6 throttle on
the INPUT — and the rail would then measure slow because the harness drove it
slow. Every script in the registry is written in seconds and each region
converts with its own measured frame period.

### 2.3 The four rails, and why each observable is fair

| class | rail | observable | why it is progress |
|---|---|---|---|
| scrolling | `scroller` | `cam_x` — world px travelled | `scroller_bg`'s VBlank commit writes BG1HOFS straight from this word (`scroller_bg.asm:193`). It is the scroll position the PPU renders with, so world px/s **is** the speed the picture slides at. |
| Mode 7 | `racer` | `m7_path` — 2-D path length of `ES_M7ORG` +0/+2 | M7X/M7Y, *"the camera's world pixel x/y"* (`rc_logic.asm:187`), committed to the PPU by the NMI hook every VBlank (`mode7_persp.asm:134`). The floor is drawn FROM this point, so the path it traces is the ground covered. |
| Mode 7 | `racer` | `heading` — heading units turned | `mode7_persp` retargets the pose LUTs from it, so the WHOLE FLOOR rotates by it. No position measure captures the rate the world turns under the player. |
| sprite animation | `brawler` | `knight_tile` — OAM tile-byte changes | Read out of the sprite table the PPU draws from — rendered output, not the counter behind it. Counting the frames on which the drawn tile CHANGES measures the walk cycle where a player perceives it. |
| sprite animation | `brawler` | `px` — world px walked | the other half of "the same animation at the same speed". |
| physics / jump | `platformer` | `arc_rate` — arcs completed per **airborne** second | a property of gravity and the jump impulse alone (§2.4). |
| physics / jump | `platformer` | `fall_speed` — 8.8 px of vertical travel per **airborne** second | vertical speed in the units the physics keeps; the finest-grained progress measure in the tree, so it adjudicates 1% most cheaply. |

Two rails needed a `guard` — declared state that must hold for the window to
mean anything (`US_GAMEOVER`, `US_HP`, `US_GOVER`, `US_LIVES`). A rail that
dies mid-window averages a live half with a frozen half and reports a ratio
that is about nothing; the guard makes that loud instead of silent. It fired
for real: a run-and-shuttle drive walks the platformer's hero into a
patrolling ghost inside 5 s.

### 2.4 The trap the oracle found in itself

The platformer's first physics observable was *landings per second*. It read
**0.99969 — PARITY** — on a rail measurably running 17% slow. The drive
presses A on a real-time cadence, the hero lands once per press in both
regions, and the observable was measuring the harness.

Two fixes, both kept:

* **gate the denominator.** `arc_rate` counts the same landings but divides by
  the seconds the hero is OFF THE GROUND. That is "how fast does one ballistic
  arc complete", which no script can pace. It reads 0.81606.
* **do not let the input script change the arc.** `do_jump`
  (`play.asm:449`) launches on the press EDGE of A-or-B and CUTS THE RISE when
  neither is held — a variable-height jump. A fixed real-time hold buys 9 rise
  frames on NTSC and 7.5 on PAL, so the two regions fly **different arcs** and
  the ratio measures the cut. The drive now ALTERNATES the two face buttons, so
  one is always held (never cut) and a fresh press edge is always available
  (always able to launch). `fall_speed` moved from 0.81186 to **0.83169** —
  within 0.05% of the frame ratio — once that confound was removed.

That second one is a finding in its own right and §3.5 records it: **a button
hold measured in frames is a frame coupling on the INPUT side**, and it is not
in `docs/95` §5.5's 185, which enumerates state, routines, generators and
substrate — not input durations.

### 2.5 The output, both regions, stock builds

```
scroller  [scrolling]  scroller.sfc  md5 f34ae672bc8b98e034172ba1e28acbbf  build=stock
  frame period   ntsc   357,366 mc  (60.0988 fps)   pal   425,566 mc  (50.0072 fps)
  frame-rate ratio  pal/ntsc = 0.83208   <- what an UNCOMPENSATED rail must beat
  window         warm 2 s, measure 12 s of REAL time in each region
  guard          held in both regions (none declared)

  observable     unit                 NTSC/s        PAL/s     ratio
  cam_x          world px            120.198      100.014   0.83208  -16.8%
                 halves 1st/2nd      120.198      120.198   100.014   100.014   <- drive uniformity

racer  [mode7]  racer.sfc  md5 99afc4226424823fabdf9c2b1e7b1b88  build=stock
  frame period   ntsc   357,366 mc  (60.0988 fps)   pal   425,566 mc  (50.0072 fps)
  frame-rate ratio  pal/ntsc = 0.83208   <- what an UNCOMPENSATED rail must beat
  window         warm 4 s, measure 12 s of REAL time in each region
  guard          held in both regions (US_PAUSED)

  observable     unit                 NTSC/s        PAL/s     ratio
  m7_path        world px            243.228      203.145   0.83520  -16.5%
                 halves 1st/2nd      243.782      242.675   204.489   201.801   <- drive uniformity
  heading        heading units        60.099       50.007   0.83208  -16.8%
                 halves 1st/2nd       60.099       60.099    50.007    50.007   <- drive uniformity

brawler  [sprite animation]  brawler.sfc  md5 1b72f8d129fd7a3b667a9c4d9c8c7586  build=stock
  frame period   ntsc   357,366 mc  (60.0988 fps)   pal   425,566 mc  (50.0072 fps)
  frame-rate ratio  pal/ntsc = 0.83208   <- what an UNCOMPENSATED rail must beat
  window         warm 6 s, measure 14 s of REAL time in each region
  guard          held in both regions (US_GAMEOVER, US_HP)

  observable     unit                 NTSC/s        PAL/s     ratio
  knight_tile    tile changes         10.005        8.287   0.82831  -17.2%
                 halves 1st/2nd        9.993       10.016     8.287     8.287   <- drive uniformity
  px             world px            120.198      100.014   0.83208  -16.8%
                 halves 1st/2nd      120.198      120.198   100.014   100.014   <- drive uniformity

platformer  [physics / jump]  platformer.sfc  md5 c990560be6cbab973b99f365c3b031df  build=stock
  frame period   ntsc   357,366 mc  (60.0988 fps)   pal   425,566 mc  (50.0072 fps)
  frame-rate ratio  pal/ntsc = 0.83208   <- what an UNCOMPENSATED rail must beat
  window         warm 3 s, measure 14 s of REAL time in each region
  guard          held in both regions (US_GOVER, US_LIVES)

  observable     unit                 NTSC/s        PAL/s     ratio
  arc_rate       arcs / airborne s     1.495        1.220   0.81606  -18.4%
                 halves 1st/2nd        1.409        1.582     1.220     1.220   <- drive uniformity
  fall_speed     px/256 per air s  30550.331    25408.546   0.83169  -16.8%
                 halves 1st/2nd    29929.206    31177.995 25408.546 25408.546   <- drive uniformity
```

Seven observables, four motion classes: **0.816 … 0.835, clustered on
0.83208**, which is the frame ratio itself and `docs/93`'s 83.2% reproduced
from rendered state rather than quoted. The two that sit off the cluster are
the two whose numerators are integer EVENTS — `knight_tile` at 0.82831 and
`arc_rate` at 0.81606 — where ±1 event over a window of ~140 is worth ±0.7%
and ~21 is worth ±5%. Those two are coarse by construction; `cam_x`, `px`,
`heading` and `fall_speed` are the fine ones and all four land within 0.05% of
the frame ratio.

### 2.6 The one-process constraint

`mesen_runner._apply_region` runs once per process (from
`_make_base_snes_config`), so NTSC and PAL cannot share one. `tools/pal_probe.py`
solved this by re-executing itself once per region and diffing the children's
JSON; the oracle, `tools/measure_tb_cost.py` and `tools/tb_picture_diff.py`
all follow that precedent rather than inventing a second pattern.

---

## 3. `make tick-check` — the frame-assumption lint

### 3.1 Why a gate and not a list

`docs/95` §5.5's 185 sites were prose in a document, which means they were
already rotting: the next countdown anybody writes is site 186 and no gate
notices. This repo has a settled answer to that shape — `width_lint` for a
class the assembler cannot see, `no_wallclock` for a class the test runner
cannot see — and this is the same move for **the class the allocator cannot
see**. The allocator proves two features do not collide in SPACE. Nothing in
the tree proved anything about their unit of TIME.

**A finding is not a defect.** Every rail ships one tick per frame on purpose
and every one of these sites is correct today. What a finding says is: *this
site would have to be re-decided if the tick ever stopped being the frame.*

### 3.2 The checks

| rule | scope | what it takes |
|---|---|---|
| `tick-state` | `game/*/state.toml` | a declared word whose OWN COMMENT names a frame unit — frames, tick, timer, clock, anim, countdown, i-frames, 8.8. `docs/95` §5.2's rule, mechanised. A **bare companion** — a declaration with no comment of its own, directly under one that has a frame unit — inherits it. |
| `tick-routine` | `engine/**`, `game/**` `.asm` | a routine named `*_tick` / `*_step` / `*_advance` — the shape `docs/95` §5.1 derived its 27 from. |
| `tick-constant` | `engine/**`, `game/**` `.asm/.inc` | an equate whose NAME carries a frame unit (`*_FRAMES`, `*_RATE`, `*_PER_FRAME`) or whose comment gives it one in UNIT SHAPE (`px/frame`, `per frame`, `N frames`). |
| `tick-generator` | `tools/gen_*.py` | a build-time constant baked against a frame index. |
| `tick-substrate` | everything in scope | the NTSC frame's master-cycle count as a literal (`357368` / `357366`), or the substrate's `frame.ntsc` table read by name. |
| `bare-override` | everything | a `TICK: ok` with no reason. |

### 3.3 The override, and the two rules that keep it honest

```
; TICK: ok — <reason text>          (assembly)
# TICK: ok — <reason text>          (Python, TOML)
```

Reason REQUIRED, separators em-dash / en-dash / `--` / ` - ` / `: ` —
`width_lint`'s and `no_wallclock`'s grammar verbatim, not a third syntax. A
bare stamp is itself a finding.

**One override binds exactly ONE site**, and that is where this gate departs
from its two siblings. They take any override within three lines of a
finding; this tree writes its frame-unit declarations in tight runs — a
declaration every two lines through a rail's rate block — so a three-line
window reaches straight over a neighbour and silences a word its reason was
never written for. The binding instead follows the SHAPE of the comment the
reason is written in:

| the reason is written… | it binds… |
|---|---|
| trailing on the code or declaration line | that line |
| on an INDENTED comment-only line | the declaration whose trailing comment block it continues (walk up to the first non-comment line) — the `state.toml` shape |
| on a comment-only line at COLUMN 0 | the declaration its block heads (walk down to the first non-comment line) — the assembly shape |

A stamp can no longer blank the declaration beside it, and a run of four
rates needs four reasons. An override whose anchor carries no finding binds
nothing: the prose block-headers that introduce a whole derivation are inert
by design, not findings in themselves. Both shapes are regression fixtures
(`tests/fixtures/tick_lint/binding_state.toml`,
`tests/fixtures/tick_lint/override_binding.asm`), and each fixture site is
checked to have been inside the superseded window, so the tests fail if they
stop being regressions.

Two vocabularies, deliberately, and the difference is what keeps the baseline
readable. `tick-state` uses `docs/95`'s loose word list, because a state
declaration's comment is where its author said what the unit WAS. Equates and
generator constants use a strict UNIT SHAPE, because the loose list takes
`EDGE = 2  ; frame line` (a border) and `ROLL_FIX = 8  ; the 8.8 fraction
width` (a shift) — 45 findings of noise measured before the rule was
tightened, and a baseline full of noise teaches people to ignore the gate.
Both false positives are regression fixtures
(`tests/fixtures/tick_lint/frame_engine.asm`, `tests/test_tick_lint.py`).

### 3.4 The count, against `docs/95` §5.5's 185

**356 findings across 697 files.** The classes are not comparable one-to-one,
and pretending they are would be the wrong reconciliation:

| rule | this gate | `docs/95` §5.5 | why they differ |
|---|---|---|---|
| `tick-state` | **135** findings in **27** files | **135** across **27** of 37 rails | **exact, both numbers.** Reproducing it needed the bare-companion rule: `m7_dungeon:stepy`, `m7_oshoot:stepy` and `mode7_explore:step_dy` have no comment of their own and share the frame-unit comment above them. Without those three the doc's own stated rule mechanises to 132, and that gap is the doc's hand-classification step — which §5.2 describes ("machine-derived … then classified") but does not make reproducible. |
| `tick-routine` | 58 in 37 files | 27 | **granularity.** `docs/95` hand-read 31 EXPORTED routines down to the 27 the frame actually clocks. The lint takes the name shape wherever it appears, exported or not, and does not open the call graph — a superset by construction, and its own §"what this does not catch" says so. |
| `tick-constant` | 117 in 29 files | folded into the 27 above | **a class the doc did not enumerate separately.** It names three specimens (`MXL_STEP_FRAMES`, `PFS_CLAMP`, `M7F_PROP_RATE`) inside its engine count; there are 117 sites of that shape and they are the hardest class to region-scale. This is the one place the gate finds materially MORE than the doc, and it is a real finding about the doc. |
| `tick-generator` | 24 in 7 files | 5 generators | **granularity again**: the doc counts TOOLS, the lint counts the frame-indexed CONSTANTS inside them. The 7 files are a superset of the doc's 5 (`gen_boss_tracks`, `gen_saucer_tracks`, `gen_meteor_tracks`, `gen_move_lut`, `gen_pose_tables`) plus `gen_m7f_gradient` and `gen_chamber_assets`. |
| `tick-substrate` | 22 in **18** files | **18** sites | **the file count is exact.** 22 findings because some files carry both a `357368` literal and a `frame.ntsc` read. `vendor/mesen_runner.py` is one of the doc's 18 and is OUT of this gate's scope (`vendor/` is frozen) — so one real site stays uncounted, and §5.4 remains its record. |

**The headline reconciliation: the half of the 185 that is a mechanical rule
reproduces to the site (135 and 18); the halves that were hand-reduced or
counted per-tool differ in granularity, in the direction a lint must (a
superset); and one class — 117 frame-unit equates — the doc did not
separately enumerate at all.**

### 3.5 What the lint does not catch — read this before trusting it

1. **It is lexical, not semantic.** It finds sites that SAY they are counted in
   frames. A countdown named `t` with no comment, in a rail whose loop runs it
   once per frame, is invisible and is exactly as coupled. The honest reading
   of a clean run is *"no NEW site declared a frame unit"*.
2. **It cannot tell a rate from an integer.** `docs/95` §5.2's whole point is
   that class A (33 8.8 accumulators) scales cleanly and classes B and C (30
   integer countdowns, 9 small-integer dividers) do not. That is a judgement
   about what the number MEANS; the lint reports, the human classifies.
3. **It does not see the call graph** (hence `tick-routine`'s superset).
4. **`vendor/` is out** — costs one real `357368` site.
5. **INPUT DURATIONS ARE A CLASS NOBODY HAS COUNTED.** §2.4's jump-cut is a
   frame coupling that lives in neither state nor a routine nor a generator: it
   is "how long a button was held, in frames". `do_jump` is one instance; the
   185 does not include it and neither does this gate. How large that class is
   is unknown and is the obvious next enumeration.
6. **A clean run is not a region-correct tree.** Nothing here measures
   anything. That is `tools/rate_oracle.py`.

### 3.6 Why it is not in `gates` or `bare-check`

A gate whose baseline holds 356 entries has to earn its place before it can
fail a landing. `make time-check` shipped with an EMPTY baseline precisely
because its work item drove all 56 findings to zero first; this one cannot —
135 of its findings are game-design decisions. It runs on demand, and
`tests/test_tick_lint.py` runs it against the live tree so a baseline that
drifts is a red rather than a surprise. Promote it when the baseline has been
driven down and the rule set has stopped moving.

---

## 4. The prototype timebase

### 4.1 The architectural question, and the rail

`docs/95` §5 leaves open whether the 185 sites are hard **because there are
185 of them** or hard **because they are written in the wrong unit**. If game
logic were expressed against a DECLARED TICK, region compensation would be a
property of the tick generator instead of 185 call sites — the same move
`docs/95` §5.3 proposes for scanline coverage.

**`scroller` is where that is tested**, for three reasons:

* it is the **smallest rail in the tree**. The whole of its motion is two
  words, so a timebase change touches one routine and the oracle sees it
  exactly — it reads the stock rail at 0.83208 with a first-half/second-half
  spread of **zero**, so a 0.1% change is unmissable;
* its step is an **integer 2 px/frame**, `docs/95`'s HARD class, not the 33
  8.8 rate accumulators that scale cleanly. A scheme that cannot fix the
  simplest integer rail cannot fix 30 integer countdowns;
* nothing else composes `scroller_bg`, so the blast radius is one ROM.

### 4.2 What was built, and what did not move

`-D SF_TICK=n` on the existing rail. **With no define every line is absent**
and the macros expand to the original immediates, so `build/scroller.sfc`
holds `f34ae672bc8b98e034172ba1e28acbbf` before and after — and
`tools/build_scroller_tb.sh` builds a no-define CONTROL ARM through the
variant recipe and `cmp`s it against the shipped image, so a leaking guard
fails the build rather than quietly moving the baseline every number below is
measured against.

The prototype's state is **declared, not hand-placed**: four `@dp` words in
`game/scroller/state.toml` (`tb_acc`, `tb_ph`, `tb_reg`, `tb_st`), allocated
by the allocator like everything else. They are declared unconditionally and
touched only under the flag; the default build references none of them, and
`US_FRAMES` keeps dp offset `$13` across the addition because the allocator
packs a scene's user words alphabetically and `f` sorts before `t`. That is
why the default image does not move.

Each of the four carries a `TICK: ok — <reason>` override, which is the
convention working on live code rather than on a fixture: they exist to REMOVE
a frame coupling, not to express one. A fifth override sits on the ratio
derivation in `world.asm` — `make tick-check` flagged that comment on its
first run against the file, which is the gate doing its job.

### 4.3 The candidates

| n | scheme | what it does |
|---|---|---|
| 1 | `lump` | 6 logic ticks per 5 frames under PAL — the scheme `docs/95` §4 refuted on the tightest rail's budget. |
| 2 | `accum6_5` | one tick per frame; the per-frame step scaled by **6/5** in 8.8, the fraction carried between frames. |
| 3 | `accum` | the same, scaled by the **measured frame ratio 1.201804** (60.09879 / 50.00714 fps) rather than by 6/5. |
| 4 | `intscale` | one tick per frame; the step scaled and ROUNDED TO THE NEAREST integer — `docs/95` §5.2's class B/C, *"no correct ×5/6, only a rounding policy"*. round(2 × 1.2018) = 2. |
| 5 | `intup` | the same, rounded UP: 3. |

### 4.4 Measured parity

`python3 tools/rate_oracle.py scroller --rom build/scroller_tb_<n>.sfc`, warm
2 s + 12 s window, both regions:

| build | NTSC px/s | PAL px/s | **PAL/NTSC** | error |
|---|---:|---:|---:|---|
| stock | 120.198 | 100.014 | **0.83208** | −16.79% |
| `intscale` | 120.198 | 100.014 | **0.83208** | −16.79% — *changed nothing* |
| `intup` | 120.198 | 150.022 | **1.24812** | +24.81% |
| `accum6_5` | 120.198 | 119.934 | **0.99781** | −0.22% |
| `lump` | 120.198 | 120.017 | **0.99850** | −0.15% |
| **`accum`** | **120.198** | **120.101** | **0.99919** | **−0.081%** |

Four readings worth pulling out.

* **The NTSC column does not move.** 120.198 px/s in every row, including the
  stock rail. That is the reversibility property in the measurement itself,
  before §4.6's pixel proof.
* **`intscale` is the class-B/C problem, measured.** round(2.4) = 2 is the
  best integer answer and it is the answer the rail already had: parity
  unchanged at 0.83208. Round the other way and you overshoot by 24.8%. There
  is no third integer. `docs/95` §5.2's *"39 of these have no correct ×5/6"*
  is not a figure of speech.
* **6/5 is the wrong constant, and it is worth 0.15%.** The frame ratio is
  60.09879 / 50.00714 = **1.201804**, not 1.2. `lump` runs exactly 6 ticks per
  5 frames and lands at 0.99850 for that reason alone — its residual is the
  constant, not the mechanism. `accum6_5` carries the same 6/5 error plus the
  8.8 quantisation of 2.4 and lands at 0.99781.
* **`accum` is the mechanism done right**: the measured ratio, and the
  fraction carried so the published pixels sum to the exact scaled distance
  instead of being re-quantised every frame. **0.99919.** Its remaining
  −0.081% is the 8.8 step itself (615/256 = 2.40234 against a true 2.403608, a
  −0.056% floor) plus the sub-pixel carry pattern beating against the window,
  visible in its halves (120.017 / 120.184). A wider fixed-point step removes
  most of what is left; nothing here needs a different mechanism.

### 4.5 Measured cost

`python3 tools/measure_tb_cost.py` — breakpoints on `world::tick`'s entry and
on the return of its last callee, master clocks at every hit, on the shipping
variant images:

| build | region | tick mc min/med/max | % of frame | Δ vs stock | loop |
|---|---|---:|---:|---:|---|
| stock | ntsc | 970 / 970 / 970 | 0.271% | — | 1 frame |
| any variant | ntsc | 1,290 / 1,290 / 1,290 | 0.361% | **+320 mc** | 1 frame |
| stock | pal | 970 / 970 / 970 | 0.228% | — | 1 frame |
| `lump` | pal | 1,420 / 1,420 / **2,060** | 0.334% | +450 mc | 1 frame |
| `accum6_5` / `accum` | pal | 1,604 / 1,604 / 1,604 | 0.377% | **+634 mc** | 1 frame |
| `intscale` / `intup` | pal | 1,352 / 1,352 / 1,352 | 0.318% | +382 mc | 1 frame |

* **The mechanism costs +320 mc on NTSC** — 0.09% of the frame — paid whether
  or not the region flag is set, because the four axis adds now read a
  published word instead of an immediate and the tick calls the generator. The
  NTSC picture is unchanged (§4.6); this is what it costs to leave the door
  open.
* **`lump`'s cost is BIMODAL and the min/med/max column is why that column
  exists**: 1,420 mc on four frames in five and **2,060 mc on the fifth** —
  the doubled tick, visible directly. An average would have hidden the only
  number that matters.
* **`accum`'s +634 mc is flat, and it is O(1) IN THE SIZE OF THE TICK.** That
  is the load-bearing difference. `lump`'s cost is O(tick): here the doubled
  frame costs one more pass through eleven instructions, and on
  `split_h_2p_demo` at its shipped N=24 the same shape is a second 257,632 mc
  tick, which `docs/95` §4.3 measured at 121% of a PAL frame in work alone and
  which does not fit. The accumulator's +634 mc would be **0.15% of a PAL
  frame and 0.25% of that rail's own tick** — the same number on the lightest
  rail and the heaviest.

### 4.6 The NTSC picture did not move — read off the pixels

`python3 tools/tb_picture_diff.py`, same held-RIGHT drive, captures at
ABSOLUTE PPU frames 120 / 300 / 600, each variant against the stock image:

```
[ntsc]  reference scroller.sfc  md5 f34ae672bc8b98e034172ba1e28acbbf
  scroller_tb_off.sfc            IDENTICAL — the picture did not move
  scroller_tb_lump.sfc           IDENTICAL — the picture did not move
  scroller_tb_accum6_5.sfc       IDENTICAL — the picture did not move
  scroller_tb_accum.sfc          IDENTICAL — the picture did not move
  scroller_tb_intscale.sfc       IDENTICAL — the picture did not move
  scroller_tb_intup.sfc          IDENTICAL — the picture did not move
[pal]  reference scroller.sfc  md5 f34ae672bc8b98e034172ba1e28acbbf
  scroller_tb_off.sfc            IDENTICAL — the scheme changed NOTHING on PAL <- vacuous
  scroller_tb_lump.sfc           differs on frame(s) ['300']
  scroller_tb_accum6_5.sfc       differs on frame(s) ['120', '300', '600']
  scroller_tb_accum.sfc          differs on frame(s) ['300']
  scroller_tb_intscale.sfc       IDENTICAL — the scheme changed NOTHING on PAL <- vacuous
  scroller_tb_intup.sfc          differs on frame(s) ['120', '300', '600']
```

The NTSC arm is `docs/94` §4 clause 1, discharged from rendered pixels rather
than asserted. The PAL arm is the **non-vacuity control**, and without it
"NTSC identical" is satisfied by a scheme that is switched off — which is
exactly what it catches: `tb_off` and `intscale` render PAL identically to the
uncompensated rail, and both of them genuinely do nothing.

**The PAL arm is a weak witness on this rail and the tool says so.** The world
is a 16 px checkerboard wrapping every 256 px, so a compensated camera that is
a multiple of 16 px ahead draws the same picture. `lump` and `accum` therefore
agree with the reference on frames 120 and 600 and differ on 300. That is
aliasing, not evidence of parity; the numeric ratio in §4.4 is the strong
witness and the pixels are the reversibility check.

### 4.7 What PAL actually returns on THIS rail

`docs/95` §4.2 measured **+14.8%..+17.4%** (midpoint +16.1%) of usable
per-frame work on `split_h_2p_demo`, against the **+20.0%** a whole-extra-tick
scheme needs — less than the frame's own +19.1%, because the fixed NMI and
sync cost does not shrink when the frame gets longer. That is a property of
that rail's fixed cost, so it was re-measured here rather than inherited:

```
  ntsc  frame   357,368 mc  - main loop outside the tick    974 mc  - NMI 16,800 mc  =   339,594 mc usable
  pal   frame   425,568 mc  - main loop outside the tick    974 mc  - NMI 16,800 mc  =   407,794 mc usable
  PAL returns +20.1% of usable per-frame work (the FRAME grew +19.1%; a whole-extra-tick scheme needs +20.0%)
```

The main-loop term is measured (`input_read` entry to `sm_frame_sync` entry,
which on this rail contains no NMI because the loop finishes long before
VBlank and then sits in `wai`); the NMI term is `docs/93` §7's measured worst
NMI frame, **16,800 mc, which that pass found identical in both regions to
the master cycle** — cited, not re-measured.

**So the scroller returns +20.1% and clears the +20.0% bar, and
`split_h_2p_demo` returns +16.1% and does not.** Both measurements are right.
What they say together is that **the usable-work return is a function of the
rail's fixed overhead, not a constant of the console** — 974 mc of fixed
main-loop cost here against a rail that also runs `input2_read`, a second
camera and a heavier NMI. `docs/95` §4's refutation of the lump scheme stands
exactly where it was made: on the tightest rail. It is not a statement about
PAL, and this rail is the counter-example that shows the difference.

---

## 5. Is parity reachable in this engine?

**As a mechanism: yes, and the number is 0.99919 at a cost of 0.15% of a PAL
frame.** One tick per frame, the per-frame delta scaled by the measured frame
ratio in fixed point, the fraction carried. It reaches 8× inside the 1–2%
scale a scheme has to be adjudicated at, its residual is a known and reducible
quantisation floor, its cost is flat and independent of how much work the tick
does, and it leaves the NTSC picture pixel-identical. Nothing measured here
suggests a better shape, and the two other shapes both fail for reasons that
are now numbers rather than arguments: the lump scheme's cost is O(tick) and
does not fit the tightest rail, and an integer scale has no correct answer at
all — 0.83208 one way, 1.24812 the other, on a step of 2.

**As a delivered property of the game: no, and the number that says so is
135.** The prototype rail's entire motion is ONE WORD. `make tick-check`
counts **135 declared game-state words across 27 rails**, of which `docs/95`
§5.2 classifies 30 as integer countdowns and 9 as small-integer animation
dividers with **no correct ×5/6, only a rounding policy** — a game-feel
decision taken 39 times. Add 117 frame-unit equates and 58 per-frame routines.
Nothing in this sprint shortens that surface; it only makes it countable, and
the reason it is countable now is that it can no longer grow silently.

**The recommendation, therefore, is not a retune.** It is:

1. **Keep `make tick-check` out of the landing gate and drive its baseline
   down opportunistically.** The population can only go down, and the day it
   is small enough to fail a landing is the day R2 becomes a normal-sized
   piece of work rather than a rewrite.
2. **Write new game logic against a declared tick from the start.** The
   prototype's `tb_frame` is what that looks like: everything downstream keeps
   saying *"move one step"*, and what a step IS becomes a property of the
   generator. A rail written that way is region-correct for the cost of one
   `jsr`; a rail written the other way costs a rounding policy per countdown.
   The gate is what makes the choice visible at the moment it is made.
3. **Do not retune the existing 185 before 2026-10-31.** `docs/95` §7's R2-D
   recommendation stands and this pass gives no reason to overturn it. What it
   overturns is the belief that the MECHANISM was the obstacle. It was not;
   the surface is.
4. **Enumerate the input-duration class** (§3.5 limit 5). `do_jump`'s
   variable-height cut is a frame coupling that is neither state nor routine
   nor generator, it changes what a PAL player's jump DOES, and nobody has
   counted how many of them there are.

---

## 6. Reproducing this

```bash
# --- the oracle, four motion classes, both regions -----------------------
make scroller racer brawler platformer          # rc-assets first for racer
make rate-oracle                                # or:
python3 tools/rate_oracle.py scroller racer brawler platformer --halves
python3 tools/rate_oracle.py --list             # the registry + every observable

# --- the lint ------------------------------------------------------------
make tick-check                                 # 0 NEW against the baseline
make tick-census                                # the per-rule / per-file census
python3 -m pytest tests/test_tick_lint.py -q    # 13 tests, incl. the live tree

# --- the prototype -------------------------------------------------------
make scroller-tb        # 5 variants + the byte-identical control arm
make tb-measure         # cost + the usable-per-frame-work re-measurement
make tb-picture         # NTSC pixel identity, PAL non-vacuity
for v in lump accum6_5 accum intscale intup; do
  python3 tools/rate_oracle.py scroller --rom build/scroller_tb_$v.sfc \
      --label $v --halves
done

# --- the constraints -----------------------------------------------------
md5sum build/microzero.sfc      # e45ddeabac4218cd71709da7b9fcc849
md5sum build/scroller.sfc       # f34ae672bc8b98e034172ba1e28acbbf (unchanged)
python3 -m pytest tests/test_scroller.py -q     # 20 passed
make width-check time-check register rom-unbacked cleanroom
```

Gates after this work landed, all clean and all run bare:

```
make width-check    width_lint: 0 finding(s) across 224 file(s)
make time-check     no_wallclock: 0 NEW finding(s) across 246 file(s)
make tick-check     tick_lint: 0 NEW finding(s) across 699 file(s); 356 held by the baseline
make register       census matches the tree (155 dirs); demand lint 18/25 rows
make rom-unbacked   backed arm accepted, unbacked arm refused
make cleanroom      swept 983 text files, 0 zip(s); 3 hit(s) exempted by 2 allowlist entries
```

---

## 7. For the next implementer

The three tools are report-only and assert nothing. If you are picking this
up:

* **The oracle's registry is the thing to extend.** Adding a rail is a dict
  entry: ROM, emitted map, scene, a seconds-indexed drive, a guard, and one
  observable per motion axis with the sentence that says why it is progress.
  Write that sentence honestly — §2.4 is what happens when an observable
  sounds fair and is not.
* **The lint's baseline is meant to shrink.** `--write-baseline` regenerates
  it; `tests/test_tick_lint.py::test_baseline_matches_the_tree_exactly`
  refuses a baseline with dead entries, so it cannot quietly stop meaning
  anything.
* **The prototype is a prototype.** Its four declared words and its
  `tb_frame` live in `game/scroller/scenes/world.asm` because that is where a
  one-rail experiment belongs. The shipping form is a FEATURE —
  `engine/features/tick_scale/` with its own `feature.toml` and its own dp
  claim — composed by the rails that want it, with each consumer declaring
  its own accumulator instead of sharing one. That is a day's work and it is
  the first thing to do if R2 is ever authorised beyond tooling.

  > **DONE 2026-08-21** — [`docs/97`](97_region_r0_landing.md).
  > `engine/features/tick_scale` is that feature and `-D SF_TICK=n` is gone.
  > It landed with **no dp claim of its own**, against the sketch above, and
  > `docs/97` §3.2 says why: the only two things such a claim could hold are
  > the region flag (`engine/features/region` owns it, and a second copy is
  > the duplicated-constant defect) and a shared accumulator (which the
  > sentence above rules out). It `depends = ["region"]` instead, so taking
  > the arithmetic without the flag it branches on is a refusal.
  > Consumers: `scroller` (0.83208 → **0.99919**) and `brawler`, picked for
  > its MOTION CLASS — `knight_tile` 0.82831 → **0.99969** read out of the
  > OAM tile byte, `px` 0.83208 → **0.99909**. `brawler` is also where the
  > accumulator answers §5's class C: its animation DIVIDER is untouched and
  > what is scaled is the amount the clock advances by.
* **Do not promote `tick-check` into `gates` or `bare-check` until its
  baseline is small.** §3.6 says why, and the day it belongs there will be
  obvious.
