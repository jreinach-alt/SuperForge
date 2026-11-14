# Audit-2: four-pad adapter (multitap) remediation (`claude/multitap-4p`)

> Independent validation of remediation-1 per CLAUDE.md "Audit Protocol" step
> 4. Research only: no code changed, no remediation. The auditor wrote neither
> the sprint, audit-1, nor the remediation.

## 1. What was audited

| | |
|---|---|
| Branch / HEAD | `claude/multitap-4p` @ `ff4d78fe`, checked out **detached** in an isolated worktree |
| Base / pre-remediation head | `origin/main` @ `aee087f0`; audit-1's head `e34fb353` |
| Remediation commits | `48608115` (audit-1 doc), `c2ce93d6`, `8689c1e2`, `a9df18c9`, `ff4d78fe` — 23 files vs `e34fb353` |
| Inputs | `docs/audit/multitap-4p-audit-1.md`, `docs/audit/multitap-4p-remediation-1.md` |
| Scope | F1 (HIGH), F2 (MEDIUM), F5 (LOW), F7 (LOW); F3/F8 records only; regression |
| Hardware reference | `/home/justin/SuperForge/docs/reference/fullsnes.txt` (read-only; line numbers are that file's) |
| Toolchain | `PATH=$HOME/toolchains/src/cc65/bin:/home/justin/SuperForge/.venv/bin:$PATH`; no `PYTEST_ADDOPTS`; every emulator process its own `SF_MESEN_HOME` |
| Scratch | `/tmp/claude-1000/-home-justin-SuperForge/209f4e6c-da92-421f-bf84-12ae5159976e/scratchpad/mtap_audit2/` (scripts, logs, `shots/`, `contact_sheet.png`) |
| Base trees | `git archive aee087f0` and `git archive e34fb353` extracted under scratch (`tree_*`), built there |

Commands: per-module `python3 -m pytest <m> -q -rsfE -p no:cacheprovider`, one
process each (`modules.sh`); `make test XDIST=3`; the ten gates by `make <gate>`
one after another; `make falsify SET=mtap`; seven audit plants through
`tools/falsify.py`'s `run_plant` (`plants.py`), run last and alone. Audit-only
scratch scripts: `cost.py` (breakpoint cost, census-classified), `presence.py`
(36 configurations, every frame), `boot_shots.py` (boot transient + 11
screenshots), `route.py` / `shot11.py` (input routing), `identity.py`
(default-path identity), `lintexp.py` (width-lint sensitivity),
`region_count.py`, `flake.sh`.

## 2. Test re-runs

### Modules the remediation touched, one process each (verbatim)

```
test_mtap_harness: ============================= 49 passed in 18.62s ==============================
test_mtap: ============================= 51 passed in 39.58s ==============================
test_four_pads: ============================= 26 passed in 17.60s ==============================
test_mtap_cost: ============================== 3 passed in 7.07s ===============================
test_rate_oracle: ============================== 8 passed in 1.25s ===============================
test_register: ============================== 47 passed in 9.07s ==============================
test_make_gates: ============================== 11 passed in 3.82s ==============================
```

Counts 49 / 51 / 26 / 3 / 8 / 47 / 11 match the remediation report.

### Full suite — `make test XDIST=3` (after building every rail), no `PYTEST_ADDOPTS`

```
==== 4 failed, 2752 passed, 15 skipped, 491 warnings in 1826.22s (0:30:26) =====
reading: defect  (4 fault(s))
schedule-check: ok — 140 module run(s) across 3 worker(s), no module split across workers
```

The only reds are the four `test_batch_union.py` PyYAML cases (environmental,
same four as on base per audit-1). **No non-PyYAML failure and no error in this
run**, so the remediation's three other reds did not recur here. The total
(2,756 cases) equals the remediation's (6 failed + 2,749 passed + 1 error).

Verification of the remediation's triage anyway (the code under both tests is
untouched by the branch: `git diff --stat aee087f0 HEAD` on both test files,
`game/meteor_event`, `game/microzero`, `engine/features/scene_mgr` is empty):

| test | HEAD `ff4d78fe` | base `aee087f0` | pre-remediation `e34fb353` | verdict |
|---|---|---|---|---|
| `test_scene_mgr_cut.py` (whole module, 6 runs each, alone) | 6/6 green | **5/6** — run 2: `4 passed, 1 error` (`test_the_cut_holds_its_forced_blank_inside_vblank` setup: saw **5** `$2100` writes, wants 4) | 6/6 green | **pre-existing flake, reproduced on base**; rarer on this box than the remediation saw (it reported 1/8 and 2/8 green) |
| `test_dma_init_forced_blank.py` (whole module, 2 runs each, alone) | 9 passed ×2 | 9 passed ×2 | 9 passed ×2 | did not reproduce alone, nor under the XDIST=3 suite; "load-sensitive" neither confirmed nor refuted |

The claimed bug in the second test's failure message is real
(`tests/test_dma_init_forced_blank.py:357-362`): a fire whose MDMAEN mask names
other than one channel gets `"key": None` (`:265-268`), and
`test_every_observed_fire_matches_a_declared_claim` then formats its message
with `sorted(unknown)` and `k[0]` — a `TypeError` whenever `None` is in the
set, so the assertion's own diagnosis is lost. Pre-existing, not this branch;
recorded as N5 below.

### Gates (sequential, nothing else running)

`width-check 0 · time-check 0 · map-check 0 · tick-check 0 · cleanroom 0 ·
register 0 · rail-registered 0 · toy-bad 0 · rom-unbacked 0 · measure 0`.
(`zp-check` does not exist in this lineage — `No rule to make target`.)

### Pinned / unchanged ROMs

| ROM | HEAD | base `aee087f0` | `e34fb353` |
|---|---|---|---|
| `microzero` | `9ca5e47f5134d534c607fcb302c79b4f` | same | same |
| `sprite_game` | `9c8a69cf873118e81cc043dce9f487f1` | same | same |
| `split_h_2p_demo` | `b26ff7b406cfa4219fd2d19a4e1d117e` | same | same |
| `room` | `9327eecaf23c97a18dd6d4a9e94e4001` | same | same |
| `patrol` | `6d751737be9572c38517bcee4eb69454` | same | same |
| `stomper` | `86906e45adc1a058a272cfd47884b358` | same | same |
| `four_pads` | `256a0cadc115aed5d2289b19095f344d` | — | `f40f5610…` (audit-1's) |
| `mtap_probe` | `d6b0e203a4024841fc2c09d8139f76e3` | — | `387f24e6…` (audit-1's) |

## 3. Per finding

### F1 (HIGH) — per-pad presence → **REMEDIATION VERIFIED** (with one harness defect found on the way, N1)

**Record.** docs/102 D10 (L210 onward) now cites fullsnes' "17th and up —
Padding (always 1=Low) (or 0=High when no pad connected)" (fullsnes L3181) and
the ID table's "0000.00000000 No controller connected / 0000.11111111 Normal
Joypad" (L3021-3022). Both quotations checked against the file. The false
premise is marked wrong, not quietly replaced.

**Hardware sequence vs fullsnes.**

* Boot census (`engine/features/mtap/mtap.asm:153-193`): fresh strobe, 16 clocks
  of `$4016` and `$4017`, then the 17th of each; `$4017` bit 0 → P2 (port 2
  pin 4 = plain pad or slot 1), bit 1 → P3 (pin 5 = slot 2) via `asl` + mask
  (`:164-167`); P1 from `$4016` bit 0 (`:168-170`); P3 cleared without an
  adapter (`:173-174`). With an adapter WRIO.7 = 0 and 17 clocks of `$4017`
  give slot 3's 17th (`:176-189`). This is fullsnes' MP5 read order (L3414-3424:
  player 2/3 bits from `$4017` bits 0/1 first, then `[4201h].Bit7=0`, then
  player 4/5) with "read any number of bits" (L3416-3417) taken to 17. The
  WRIO 0→1 settling note (L3420, L3427-3428) is respected: after `$FF` is
  written back (`:192-193`) nothing *reads* the ports; the next access is the
  re-latch strobe (a write, delivered to every player per L3414).
* Periodic census (`:300-301`, `:319-369`): first half reads one more bit of
  `$4016` and `$4017` *before* the select line drops — the same "player 2-3
  before 4-5" order fullsnes asks for (L3426-3432, which also names the Tribal
  Tap passing CLK to player 2 during the 4/5 read; the split makes that
  irrelevant here, P2's 17th is read on a call where slot 3 is clocked only
  after it). The masked merge (`eor`/`and #$07`/`eor`, `:328-331`) gives
  `(new & 7) | (old & ~7)`; bits 4-7 and the high byte stay 0. Second half:
  12 buttons + 4 ID + the 17th of slot 3 (`:342-356`), `tsb`/`trb` of bit 3
  only.
* Re-latch at the end of `mtap_init` (`:203-205`) is on every exit path
  (`@init_done` is reached by both the adapter and the no-adapter arm).

**Does anything between a census and the next automatic read see clocked-out
bits?** Only `mtap` touches `$4016/$4017` in the tree (`grep 4016\|4017
engine/features/input*/` is empty; JOYSER/WRIO are `mtap`'s declared claims);
`input_read`/`input2_read` read `$4218-$421B`, which manual clocks do not
change. A mid-frame census leaves lines clocked past 17, and the next VBlank's
automatic read re-strobes every pad. The only window where a clocked-out line
was observable was the rail's first call before any automatic read — the boot
transient the re-latch fixes (below).

**Census split vs a skipped call or a lag frame.** Each half derives its bits
from the automatic read that immediately preceded *its own* call; the only state
carried between halves is `ES_MTAP_TICK`. A skipped frame (a lag frame on which
the loop does not call) just moves the second half to a later frame's fresh
read — still correct. A lag frame cannot put two calls between two automatic
reads on a rail whose loop syncs on an armed NMI (audit-1 §4 for `scene_mgr`).
Two calls in one frame are a contract violation already ("ONCE per frame",
`:230`); even then the second half would read slot 3's 30th bit (padding,
same presence answer) — the buttons would be wrong, as before the remediation.
Reasoned, not emulated: no harness primitive skips a call or lags a frame on
demand.

**Emulator: every configuration the harness drives (36), every frame.**
`presence.py` on `mtap_probe`: for each of port 1 {pad, empty} × port 2 {pad,
empty, adapter × 16 slot patterns}, `ES_MTAP_PADS` and the probe's `pad_here`
answers (`US_HERE`) read after **every** frame for 110 frames — frames 1-40
nothing held, 41-110 every button (all four d-pad directions included) held on
every index. That spans the boot census and three periodic censuses (both
halves). **36/36 correct from frame 1, zero deviations on any frame**: no
flicker at a census boundary, and presence does not ride on button bits (P3/P4
read `$FFF0` while held where present). On `four_pads` the tokens and lamps
shown (OAM Y ≠ 240) equal the expected set for all 36 at frame 10 (boot
census) and frame 100 (after periodic censuses): **36/36**.

**The boot P4 transient.** `boot_shots.py`: `four_pads`, adapter full, then
slot 3 empty, stepped one frame at a time from load: `ES_INP4_CUR`,
`ES_INP4_PRESS`, P4's flip word and P4's token attr for frames 1-12 are
`0, 0, 0, $36` throughout (no flip, nothing held/pressed); `ES_INP3_CUR` 0.
Gone. The plant `boot-relatch-dropped` (FIRED in `make falsify SET=mtap`)
proves the test that guards it is live.

**Screenshots (captured by this audit, read).**
`…/mtap_audit2/shots/01..11_*.png`, `…/mtap_audit2/contact_sheet.png`:

| shot | configuration | on screen | ✓ |
|---|---|---|---|
| 01 | pad / pad | P1 red, P2 blue (token + ring lamp) | ✓ |
| 02 | port 2 empty | P1 only | ✓ |
| 03 | port 1 empty | P2 only | ✓ |
| 04 | both empty | nothing | ✓ |
| 05 | adapter full, all four moving | four tokens displaced, four lamps lit | ✓ |
| 06 | adapter, slots 1+3 | P1, P2, P4; P3 absent | ✓ |
| 07 | port 1 empty, slot 2 only | P3 only | ✓ |
| 08 | adapter, no pads | P1 only | ✓ |
| 09 | adapter, slot 4 only (held) | P1 only; slot 4 unread | ✓ |
| 10 | adapter, slot 3 only, P4 held right+down+X | P1 and P4; P4 moved, lamp lit | ✓ |
| 11 | port 1 empty, slots 2-4, `pad3` held X | P3 and P4 drawn ✓ — but **P4's** lamp is lit, not P3's | ✗ harness (N1) |

Shot 11 led to **N1**: with port 1 empty, every `advance(padN=…)` index
reaches the device one port position *earlier* than documented. Presence and
the engine are correct; the harness's input routing is not.

**Verdict F1:** the engine, demo and record close F1. Presence matches reality
for all 36 configurations at boot and across censuses, the census is fullsnes'
sequence, the split is safe by construction, no flicker, the boot transient is
gone. The new harness knob it rests on has a routing defect (N1) that no
committed test happens to exercise.

### F2 (MEDIUM) — worst-case cost → **REMEDIATION VERIFIED**

Re-measured by this audit (`cost.py`: exec breakpoints on each ROM's labels
from its `cmp`-proved labelled twin, master-clock delta jsr→next, 140 calls
per row, each call classified by `ES_MTAP_TICK` read at the begin breakpoint):

| ROM / timing | adapter | plain calls | census P1-3 half | census P4 half | max lines |
|---|---|---|---|---|---|
| `four_pads`, after the read | no | 136 ×140 | — | — | 0.10 |
| `four_pads`, after the read | yes | **2,256** ×130 | **2,594** ×5 | **2,626** ×5 | **1.93** |
| `mtap_probe`, top of VBlank | no | 136 ×140 | — | — | 0.10 |
| `mtap_probe`, top of VBlank | yes | 6,274-**6,582** ×130 | 6,612-6,788 ×5 | 6,644-**6,886** ×5 | **5.05** |

Every remediation number reproduces exactly (136; 2,256 / 2,594 / 2,626; 6,274
min and 6,886 max). One nuance: the record's "plain calls 6,274-6,516" (docs/102
L325) — this audit's 140-call sample saw a plain call at **6,582** (N4; the
range is sample-dependent because the read's start steps in 256 mc).
`docs/capability_envelope.md:130` and docs/102 §7.2/D7 carry both timings.

**Tests are true contracts and can fail.**
`test_a_call_after_the_auto_read_stays_under_two_scanlines_census_included`
(`tests/test_mtap_cost.py:132`) requires ≥ 4 census calls in a 72-call sample
and bounds every call < 2,728 mc (margin to the real worst: 102 mc). Audit
plant `a2-census-p4-too-slow` (32 extra slot-3 clocks in the P4 half; presence
unaffected because bit 49 is still padding) — **FIRED**.
`test_a_caller_at_the_top_of_vblank_pays_the_auto_read_wait` (`:153`) asserts
min > 4,224 and max < 7,334. Audit plant `a2-guard-line-226` (guard keyed to
the wrong line, so line-225 callers no longer wait) — **FIRED**; the
remediation's `d7-guard-skipped` also names it (FIRED). The upper bound has
448 mc of slack over the measured max; it is derived (work bound + read +
latest start), not fitted, which is the right shape.

### F5 (LOW) — auto-joypad contract → **REMEDIATION VERIFIED**

`mtap.asm:227-229`: "the AUTOMATIC JOYPAD READ IS ENABLED (NMITIMEN bit 0
set): with it off, a call on the first VBlank line waits forever …"; docs/102
D7 states the same limit and why the wait is unbounded. Matches the audit-1
recommendation (fix the text). Not emulated (a contract text change).

### F7 (LOW) — record drift → **REMEDIATION VERIFIED**, with two small new drifts (N3, N4) and one formatting regression (N2)

| item | check | result |
|---|---|---|
| (a) docs/102 MT-7 surface | now "the slot routing of the NEXT frame's automatic read … DP words" | matches `tests/test_mtap.py:199-211` ✓ |
| (b) docs/09 `mtap` row "16 clocks" | now "12 clocks … the ID nibble is not clocked" | matches `mtap.asm:46-57` ✓ |
| (c) envelope L24 "All 40 games" | "All 41 games in Part 1" | Part 1 has 41 rows (`grep`), 43 rails exist ✓ |
| (c) region counts | "36 of 43 compose, 34 measured; `aurora`, `mill` unmeasured" | `region_count.py`: 43 `game/*/game.toml`, **36** compose `region`+`tick_scale`, **34** of those in `RAILS`, missing exactly `aurora`, `mill` ✓ (the oracle also lists `rpg_town`, not a `game/` dir — not a counting error) |
| (c) `four_pads` rate oracle | reproduce | `python3 tools/rate_oracle.py four_pads`: `token_oam_x 120.198 / 120.184 0.99989 PARITY`, `player_x 120.198 / 120.101 0.99919 PARITY` — **identical** ✓ |
| docs/09 census table `dp`×7 → ×9 | `make register` 0 | ✓ |

But the edit to the envelope's region row **dropped its cell separator**
(N2), and the census period is worded two ways (N3).

### F3 / F8 — records only

* F3: docs/102 §7.3 "Follow-up (audit-1 F3, deferred)" present (L356) with the
  order hazard named; no code change to `input`. `microzero` md5 unchanged ✓.
* F8: docs/102 D6 (L165-170) states `B ≠ $FF` is untested, why, and that an
  audit plant left every test green ✓. Detection code (`mtap.asm:138-143`)
  unchanged except comments and the shared `ES_MTAP_ON` scratch, which the
  presence code overwrites only after the verdict.

## 4. Regression

* **Default harness path byte-identical** (`identity.py`, audit-1's method):
  a seven-step two-pad script through `Machine` on `sprite_game` and
  `split_h_2p_demo`, per-step md5 of all WRAM, OAM, VRAM, CGRAM, plus the input
  log and replay triple — with the **base** `vendor/`, the **e34fb353**
  `vendor/`, and **HEAD**'s: per-rail records identical in all three.
* **No leak into a later load:** a fourth run in one process first ran and
  closed three `four_pads` Machines (port 1 empty; port 2 empty; port 1 empty +
  adapter slots `0101`, buttons held), then the default runs: identical to
  base; module state after = `('pad', 'pad', (True, True, True, True))`. By
  construction `ensure_ports` compares the whole `(port1, port2, slots)` tuple
  (`vendor/mesen_runner.py:1582-1586`) and `MesenRunner`'s loads route through
  `ensure_port2_device` → `ensure_ports(port2=…)`, which resets port 1 and the
  slots too.
* Pinned ROMs: §2. Rails not composing `mtap` are byte-identical.

## 5. Width / DP discipline (`git diff e34fb353 -- '*.asm' '*.inc' '*.toml'`)

* **Branch-target widths.** Every new multi-path label is annotated and true:
  `@skip16`, `@boot_p4`, `@clock17`, `@p4_gone`, `@init_done` (.a8, all
  arrivals A8); `@slot3` (.a8 — the `beq` and the census's `jmp` both A8),
  `@release`, `@census`, `@census_p4`, `@p4_here`, `@p4_done` (.a8);
  `pad_here`'s `@nobody` (.a16); probe `@here`/`@there` (.a16). The macro
  `MTAP_P4_BUTTONS` has no sep/rep/labels and asserts A8 at expansion; its
  `; WIDTH-RISK:` contract (`mtap.asm:39-45`) is updated for the census. No new
  `tax`/`tay`. `make width-check` 0.
* **Stack balance:** no push/pull anywhere in `mtap_init`, `mtap_read` (either
  census half) or `pad_here`; the split carries state in DP, not on the stack.
  The probe's new `@here` loop pushes nothing.
* **A16 table read:** `pad_here`'s `lda f:mtap_pad_bit, x` reads two bytes;
  the table has a fifth `0` byte (`:481`) so X = 3 reads `P4, 0`, and the `and`
  with the always-zero high byte of `ES_MTAP_PADS` clears it. Correct.
* **DP ownership:** two new claims `mtap_pads`, `mtap_tick` (2 B each) in
  `feature.toml`, both in `[init] zero`, every access `z:ES_*`; DP 14 → 18 B;
  `US_HERE` is `@dp` in the probe's `state.toml`. No raw DP literal.
* **The width-linter weakness** (same-named `@` labels merged across routines).
  `mtap.asm` has exactly one duplicated set, `@p1..@p4` in `pad_btn` and
  `pad_btnp` (both all-A16). Sensitivity on scratch copies (`lintexp.py`; the
  tree untouched): an A8 arrival planted at `pad_btnp`'s `@p4` — **flagged**;
  at `pad_btn`'s — **flagged**; an A16 arrival at `@slot3` — **flagged**; at
  `@census_p4` — **flagged**. The merge only adds arrivals, so a wrong-width
  arrival still contradicts that label's own annotation; a false negative
  would need two same-named labels with *different* annotations, which mtap
  does not have. **mtap is not affected.** (Dropping `.a8` at `@p4_done`,
  whose arrivals and sequential state agree, is not flagged — harmless here.)

## 6. Falsification

`make falsify SET=mtap` (the remediation's set): **11/11 FIRED**, `git status
after restore: (clean)`.

Audit plants (`plants.py`, one line each through `run_plant`, last and alone):

| plant | file | named test(s) | verdict |
|---|---|---|---|
| `a2-census-drops-p3` — census merge mask `P1|P2` | `mtap.asm` | `test_the_census_re_reads_presence_once_a_period_in_two_halves` | FIRED (1 red) |
| `a2-census-p4-reads-16th` — `.repeat 4` → 3 | `mtap.asm` | presence [36] + census re-read | FIRED (17 red, 20 green: exactly the slot-3-present configs + the census test) |
| `a2-pad-here-table-swapped` — P3/P4 entries swapped | `mtap.asm` | presence [36] | FIRED (16 red) |
| `a2-boot-census-no-shift` — boot `asl` dropped | `mtap.asm` | presence [36] + no-adapter boot-only | FIRED (26 red) |
| `a2-census-p4-too-slow` — 32 extra clocks | `mtap.asm` | `test_a_call_after_the_auto_read_…census_included` | FIRED |
| `a2-guard-line-226` | `mtap.asm` | `test_a_caller_at_the_top_of_vblank_pays_the_auto_read_wait` | FIRED |
| `a2-harness-port1-empty-ignored` | `vendor/mesen_runner.py` | `test_the_17th_bit_is_…` [36] | FIRED (18 red) |

After the run: `git status --short` empty, `git diff --stat` empty,
`mtap.asm` / `mesen_runner.py` md5 = HEAD's. **But `build/four_pads.sfc` was
`8fdfe1f4…`, not its baseline** — `a2-guard-line-226` declares the probe as
its artifact, and its named test's module fixture (`test_mtap_cost.py`
`labels_built`) also runs `make fp-labels`, rebuilding `four_pads` from the
planted source; the restore rebuilds only the declared artifact. `make
four_pads fp-labels mtap-probe` brought it back to `256a0cad…`. The
remediation's own `d7-guard-skipped` has the same shape (probe artifact, a
`test_mtap_cost` test); in the full set a later `four_pads` plant happens to
rebuild it clean. See N6. Final md5s: `four_pads 256a0cad…`, `mtap_probe
d6b0e203…`, `microzero 9ca5e47f…`, `sprite_game 9c8a69cf…`, `split_h_2p_demo
b26ff7b4…`.

## 7. New findings

**N1 — MEDIUM: with port 1 empty, the harness's pad indices reach the wrong
devices.** `route.py` on `mtap_probe` (button X on one index at a time, the
four player words read):

| configuration | pad1 | pad2 | pad3 | pad4 | pad5 |
|---|---|---|---|---|---|
| default | P1 | P2 | — | — | — |
| port 1 empty | **P2** | — | — | — | — |
| adapter | P1 | P2 | P3 | P4 | — |
| port 1 empty + adapter | **P2** | **P3** | **P4** | — | — |
| port 1 empty + adapter `1011` | **P2** | — | **P4** | — | — |

So `pad1` drives port 2's device and `pad2..pad4` drive slots 2-4 whenever
port 1 is `PORT_EMPTY` — Mesen's override index evidently counts *connected*
controllers, and `Machine.advance` / its docstring (`vendor/machine.py:428-433`:
"`pad2` is slot 1 …") assume fixed positions. The input log and replay triple
then record `pad1` as port-1 input that went to port 2. Screenshot 11 shows it:
`pad3` (documented slot 2 = P3) held X, and **P4's** lamp lit. No committed
test gives a wrong verdict today (every port-1-empty case either holds no
button or holds every button on every index, which hides the shift), and
presence is unaffected (it reads no buttons). But the remediation's new API
invites exactly the test that would be wrong — "port 1 empty: holding pad1
does nothing" would see P2 respond — an indirect-evidence trap (CLAUDE.md
"Indirect-Evidence Tests"). *Action: fix before fold or document as a hard
limit* — re-index overrides by port position when port 1 is empty (or refuse
`pad1` input with `port1=PORT_EMPTY` and shift the rest), and add a Level-0
case that holds ONE index per configuration and reads which line answers.

**N2 — LOW (introduced by the remediation): the envelope's region-parity row
lost a table cell.** `docs/capability_envelope.md:152` has 3 `|` where its
neighbours have 4 (`e34fb353` had 4): "…opt-in per rail 36 of the 43 rails…"
— the separator before the proving-games cell was deleted, so the capability
and proof cells merge, and the "against the **0.832** an uncompensated rail
reads" clause now dangles after the aurora/mill parenthesis. *Action: fix*
(restore the `|`, re-order the sentence).

**N3 — LOW: the census period is worded two ways.** The code's period is 33
calls (32 decrements from the reload, then the two halves on consecutive
calls; `tests/test_mtap.py` asserts the next first half at the 32nd call after
the second). docs/102 D10 (L228) and docs/09 L986 say "every 32 calls";
`docs/capability_envelope.md:130` says "two census calls in every 33" and D10
itself "hot-plug is seen within 33 calls". Not wrong in substance; pick one.

**N4 — LOW: two counts in docs/102.** §7.4 (L381) says `test_mtap_harness.py`
has **47** cases; it collects **49** (9 + 36 + 1 + 3). §7.2 (L325) "6,274-6,516
for plain calls" — 6,582 observed in 140 calls (state it as a sample, or the
bound).

**N5 — LOW, pre-existing, not this branch:** `test_dma_init_forced_blank.py`
`test_every_observed_fire_matches_a_declared_claim` crashes building its own
message when a fire's key is `None` (§2). *Action: defer* — own lane.

**N6 — LOW, process: a plant whose named test rebuilds an undeclared artifact
leaves that artifact planted.** `run_plant` restores and md5-checks only
`p.artifact`; `test_mtap_cost.py`'s fixture rebuilds both `four_pads` and
`mtap_probe`. Seen with this audit's `a2-guard-line-226`; the remediation's
`d7-guard-skipped` has the same shape and is cleaned only by plant order.
*Action: defer* — declare both artifacts on cost-test plants (or have
`run_plant` rebuild every target a named module's fixture builds).

Residual (not a finding): that an *adapter's* empty slot reads 0 past bit 16
rests on fullsnes' generic "no pad connected" rows plus Mesen's model; fullsnes'
MP5 section does not say it slot by slot, and no Mesen source is on disk.
Same standing as audit-1 §4.

## 8. Verdict

| finding | verdict |
|---|---|
| F1 per-pad presence (HIGH) | **REMEDIATION VERIFIED** — 36/36 at boot and every frame across three censuses, both on the probe and on the demo's OAM; fullsnes sequence; boot transient gone; screenshots match (harness defect N1 found alongside) |
| F2 worst-case cost (MEDIUM) | **REMEDIATION VERIFIED** — every row reproduced to the cycle; both new tests fire under audit plants |
| F5 auto-joypad contract (LOW) | **REMEDIATION VERIFIED** |
| F7 record drift (LOW) | **REMEDIATION VERIFIED** — all items and the rate-oracle numbers reproduce; new LOW drift N2-N4 |
| F3 / F8 records | recorded as stated; no regression |

**Aggregate: REMEDIATION VERIFIED** for F1, F2, F5, F7. No regression in the
engine, the demo, the default harness path or any pinned ROM; the full suite
is green apart from the environmental PyYAML four.

**Fold-readiness:** ready to fold into `origin/main` once the owner decides
N1. The engine/demo work is done; N1 is a defect in the remediation's new
*test-harness* knob (port 1 empty misroutes every pad index) that no current
test trips but the next presence/input test easily could. Owner's choice:
(a) a short remediation for N1 (+ N2, a one-character fix, and N3/N4 wording)
before folding — recommended, ~small; or (b) fold now with N1 documented as a
harness limit in `Machine`'s docstring and docs/102 D10, fixing it in its own
lane. N5 and N6 are pre-existing/process items for their own lanes.
