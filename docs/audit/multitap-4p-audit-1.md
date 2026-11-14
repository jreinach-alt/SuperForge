# Audit-1: four-pad adapter (multitap) and four players (`claude/multitap-4p`)

> Independent audit-1 per CLAUDE.md "Audit Protocol". Research only: no code
> changed, no remediation. The auditor did not implement this sprint.

## 1. What was audited

| | |
|---|---|
| Branch / HEAD | `claude/multitap-4p` @ `e34fb3532b95ca5c7c308b64908366e98320481f`, checked out **detached** (the branch name is checked out in another worktree, `agent-ab63cc8586c3086f6`) |
| Base | `origin/main` @ `aee087f0cb7ebeddf1689bf1dc9ee224d4633f8f` (5 commits: ad555b95, 75859d67, 19e31a47, a135a36c, e34fb353; 38 files, +2904/-37) |
| Date | 2026-11-13 |
| Spec of record | the owner's sentence + the brief (quoted in the dispatch), `docs/102_multitap_four_players.md` |
| Hardware reference | `docs/reference/fullsnes.txt` from the main checkout's tree (not present in this lineage); line numbers below are that file's |
| Toolchain | `PATH=$HOME/toolchains/src/cc65/bin:<main checkout>/.venv/bin:$PATH`; lockstep core `/tmp/Mesen2-lockstep`; every emulator process had its own `SF_MESEN_HOME` under the audit scratch dir |
| Base comparisons | `git archive aee087f0` extracted to scratch (not a git worktree) |

Commands: per-module `python3 -m pytest <module> -q -rsfE -p no:cacheprovider`
(one process each); `make test XDIST=3` (the tree's own target, **no**
`PYTEST_ADDOPTS`); the ten gates by `make <gate>`; `make falsify SET=mtap`;
seven audit-authored plants driven through `tools/falsify.py`'s `run_plant`
(script kept in scratch, not in the tree); scratch scripts for screenshots,
cost, and harness identity.

Environment note: pytest in this nested worktree walks up and takes the main
checkout's `pytest.ini` (`rootdir: <main checkout>`), exactly as the
implementer's paper cut says. I ran with it rather than overriding it; the
suite came out green except the PyYAML module (below), so the walk-up changed
nothing measurable here.

## 2. Test re-run

### New + touched modules, one process each (verbatim summary lines)

| module | result |
|---|---|
| `tests/test_mtap_harness.py` | `9 passed in 4.98s` |
| `tests/test_mtap.py` | `13 passed in 9.36s` |
| `tests/test_four_pads.py` | `18 passed in 17.18s` |
| `tests/test_mtap_cost.py` | `2 passed in 1.93s` |
| `tests/test_allocator.py` | `44 passed in 0.53s` |
| `tests/test_map_freshness_guard.py` | `18 passed in 5.89s` |
| `tests/test_reg_ownership.py` | `24 passed in 3.05s` |
| `tests/test_reg_gate.py` | `1 failed, 99 passed in 17.40s` — **environmental**: run before anything had built `build/mz/symbol_map.json` (`no_literals: symbol map … build/mz/symbol_map.json not found — run the allocator first`); green inside the full suite, which builds its prerequisites |

The implementer's counts (9 / 13 / 18 / 2) match.

### Full suite — `make test XDIST=3`, no `PYTEST_ADDOPTS`

```
==== 4 failed, 2665 passed, 15 skipped, 491 warnings in 2027.12s (0:33:47) =====
schedule-check: ok — 140 module run(s) across 3 worker(s), no module split across workers
```

| failure | on base `aee087f0` | triage |
|---|---|---|
| `test_batch_union.py::test_the_conflicted_fixture_is_NOT_valid_yaml` | FAILED | pre-existing, environmental: `ModuleNotFoundError: No module named 'yaml'` |
| `test_batch_union.py::test_each_validator_accepts_valid_and_REFUSES_broken[x.yml-…]` | FAILED | same |
| `test_batch_union.py::test_the_real_batch4_f1_file_is_REFUSED` | FAILED | same |
| `test_batch_union.py::test_a_parse_failure_is_reported_ahead_of_the_shape` | FAILED | same |

Base run: `4 failed, 34 passed in 23.62s` (same four). **No new failure.** The
implementer's "full suite not re-run after the fixes" gap is closed by this
run: the 12 `PYTEST_ADDOPTS` failures and the load-flaky one did not recur.
15 skips are all `SF_REFERENCE_TREE`/reference-tree skips, none in a module
this branch touched.

### Gates (run one after another, nothing else running)

| gate | exit |
|---|---|
| `width-check` | 0 |
| `time-check` | 0 |
| `map-check` | 0 |
| `tick-check` | 0 |
| `cleanroom` | 0 |
| `register` | 0 |
| `rail-registered` | 0 |
| `toy-bad` | 0 |
| `rom-unbacked` | 0 |
| `measure` | 0 |

### Pinned / unchanged ROMs

* `build/microzero.sfc` = `9ca5e47f5134d534c607fcb302c79b4f`, the pin in
  `tests/test_c2_sram_class.py:299` and `tools/falsify_*_binding.py`.
* Built on the base tree and compared byte-for-byte (md5): `microzero`,
  `sprite_game`, `split_h_2p_demo`, `room`, `patrol`, `stomper` — all
  identical to the branch. The `io_allowed` widening and the two new
  `REGISTER_FOOTPRINT` names change no existing ROM.
* Branch artifacts for reference: `four_pads.sfc` `f40f561070d740d7a68efb0dd313a9bb`,
  `mtap_probe.sfc` `387f24e635e97dafde980b1f6f897cab`.

## 3. Per acceptance criterion

| # | criterion (brief / owner) | verdict | evidence |
|---|---|---|---|
| 1 | adapter detected at boot | ✓ | `engine/features/mtap/mtap.asm:45-105` (fullsnes L3432-3445 sequence: WRIO=$FF :59, strobe on :61, 8×bit 1, strobe off :71, 8×bit 1, `A=$FF ∧ B≠$FF` :81-86); called before `$4200` is armed, `game/four_pads/main.asm` MAIN; `test_mtap.py::test_detection_sets_the_flag_with_an_adapter_and_clears_it_without`, Level-0 `test_mtap_harness.py::test_the_adapter_answers_detection_and_the_plain_pad_does_not` |
| 2 | P3, P4 read each frame with edge detection like P1/P2 | ✓ | `mtap.asm:160-205` (cur→prev, `press = cur AND NOT prev`); `test_mtap.py` MT-2/MT-3 parametrised over all four players, every button bit |
| 3 | WRIO bit 7 restored | ✓ | `mtap.asm:177` ($7F) and `:198` ($FF) on the one straight-line path, no branch between; `mtap_init` leaves $FF (:59). `test_the_select_line_is_released_…` (plant `wrio-left-low` FIRED) |
| 4 | no adapter: P3/P4 read nothing, frame cost unchanged | partial | nothing read ✓ (`mtap.asm:131-133`, `test_without_an_adapter_players_3_and_4_read_nothing`, plant `absent-path-falls-through` FIRED). Cost: a rail that composes `mtap` pays **136 mc/frame** without an adapter (measured below) — not literally unchanged; a rail that does not compose it pays 0 and is byte-identical (§2). See F6 |
| 5 | per-frame cost measured, small (well under 2 lines), only paid with an adapter | partial | measured both ways ✓; "only with an adapter" ✓ (136 vs 2,202). But 2,202 mc = 1.61 lines is not "well under" (the record says so honestly), and the **worst case is 6,220-6,528 mc = 4.6-4.8 lines** for a caller at the top of VBlank — measured by me on the probe, reported nowhere. See F2 |
| 6 | `btn`/`btnp` for players 0-3, out of range → 0 | ✓ | `pad_btn` `mtap.asm:218-247`, `pad_btnp` `:259-288` (X = 0..3 by equality, everything else `lda #0`); `test_out_of_range_players_answer_zero_…` checks both for X=4,5; plants FIRED for both routines (implementer: `pad_btn`; audit: `pad_btnp`) |
| 7 | harness drives pads behind the adapter; default behaviour byte-identical | ✓ | `vendor/mesen_runner.py` `PORT2_*`, `ensure_port2_device`; `vendor/machine.py` `port2=`, `advance(pad3/4/5)`. Identity verified by me (§6) |
| 8 | demo: four players each move their own sprite | ✓ | `game/four_pads/scenes/play.asm:73-163`; `test_each_token_moves_with_its_own_pad_and_no_other[0-3]`; my screenshots 05-09 |
| 9 | demo: screen shows which pads are connected / pressed | **partial** | pressed ✓ (lamp LIT, `play.asm:192-199`). Connected: adapter-level only (`play.asm:178-181`) — P1 and P2 are drawn "connected" with nothing in either port; P3/P4 are drawn whenever the adapter answered, pad or no pad. The reason given for not doing better (docs/102 D10) is factually wrong — see **F1** |
| 10 | emulator tests | ✓ | 42 new cases across four modules, Level-0 harness proof underneath |
| 11 | fault plants | ✓ | `make falsify SET=mtap`: 6/6 FIRED, tree clean; audit plants 6/7 FIRED, 1 TEST-BLIND by design (§9) |

## 4. Hardware correctness (fullsnes vs emulator)

**Detection** (`mtap.asm:57-105` vs fullsnes L3432-3445). Matches the
documented sequence for port 2 (n=1): strobe high, 8 reads of `$4017` bit 1,
strobe low, 8 more, present iff A=$FF and B≠$FF. WRIO is set to $FF first
(slot select 1/2), which is what makes B = slot-2 data. Strobe is left low,
as the auto-read requires (fullsnes L2950-2951). Run with the auto-read off
(asserted in the contract; `main.asm` order confirms). fullsnes notes games
usually also probe port 1 to warn about a tap there (L3434) — not done, not
asked for. Hot-plug unsupported (D6), stated.

**P3 = `$421E`.** fullsnes L3414-3424: with WRIO.7=1 the tap routes slots 1/2
to pins 4/5; "Player 3 data will obviously show up in JOY4"; `$421E` is JOY4,
gameport 2 pin 5 (L146). Correct for the slot it claims (slot 2). The harness
measured index 2 → `$421E` too.

**P4 clocking** (`mtap.asm:173-205`). WRIO.7=0 (`$7F`, bit 6 stays HighZ, no
other bit used on this console per L2996-3003), then 12 reads of `$4017`
bit 0. Bit order: the pad shifts B, Y, Sel, St, U, D, L, R, A, X, L, R
(fullsnes L3165-3176); eight `rol`s of the high byte put B at bit 15 … R at
bit 8; four `rol`s of the low byte plus four A8 `asl`s put A X L R at bits
7..4 and zeros at 3..0 — the `$4218` layout. Verified on the emulator for
every button (MT-2 P4), and my off-by-one plant FIRED. No latch/strobe is
issued: correct, the auto-read already strobed every slot (fullsnes L3414-3424,
"the strobe on/off part … is usually done via automatic reading").

*12 vs 16 bits.* fullsnes: "read any number of bits" (L3416-3417). Bits 13-16 of a
standard pad are ID bits, "always 0=High" (L3177-3180; one exception, the NTT
Data Pad's bit 14, which is not a standard pad). The unclocked bits need no
draining: the next frame's auto-read strobe re-latches every pad, and the MP5
passes the strobe to all of them ("strobe on (to player 1-5)", L3414). So
truncation loses no button on real hardware for any of the twelve buttons;
P4's bits 3-0 read 0 where a full read would read the same 0. **Safe.**

*Restoring WRIO.* `$FF` at `:198` on the only path; nothing touches the ports
afterwards in `four_pads` (fullsnes L3420-3421 asks for "no further access
until next frame" because of the slow 0→1 edge). An NMI cannot land inside
the 12-clock window on `four_pads` (the read runs right after the NMI and
completes in ~1,100 mc); a mid-frame IRQ could, which D9 states and does not
enforce (accepted, below).

**WRIO.7 and the H/V latch.** fullsnes L1365-1369: a 1→0 WRIO.7 edge latches
the H/V counters (and sets `$213F` bit 6), and `$2137` latches only while
WRIO.7 is 1. So `mtap_read` does (a) latch the counters as a side effect on
every adapter frame and (b) disable `$2137` for ~1,000 mc. Neither affects
`four_pads` (no other `$2137`/`$213C`/`$213D` reader; `region_init` reads
`$213F` bit 4 once, before the first `mtap_read`). `$213F` reads also reset
bit 6 and the flip-flops (L1400-1401), which the guard does before its own
`$213D` read — consistent with the tree's convention. The D9 non-enforcement
(a rail composing `mtap` plus `shg_cam`/`sit_cam`) is a real hazard but
latent: no rail composes both. Accept, keep the stated contract.

**V-counter guard** (`mtap.asm:136-157`). fullsnes L2955-2962: the auto-read
begins between H=32.5 and H=95.5 *of the first VBlank line* and lasts 4224
master cycles (~3.1 lines). So in-VBlank-and-idle means either line 225
before the start or line ≥228 after the end; the guard's `V == 225` test
separates them correctly (and the race between the `$4212` read and the
latch only moves the call into `@wait_start`, which then falls through on
busy). Line 225 holds for NTSC and PAL with overscan clear; `V=225` has no
alias in a 9-bit counter (262/312 lines). Can it misfire?

* lag frames on `four_pads`: no — `sm_frame_sync` always waits for an
  *armed* NMI (`engine/features/scene_mgr/scene_mgr.asm:429-442`, `:460-482`),
  so the main loop always resumes after the full NMI body, i.e. after the
  read (measured: the guard never spins on this rail, 120/120 frames);
* PAL: same line by fullsnes; not measured on PAL by either party;
* overscan set: wrong line (stated in D7; no rail sets it);
* **auto-read disabled** (NMITIMEN bit 0 clear) and a caller on line 225:
  `@wait_start` (`:148-152`) never sees the busy bit and **spins forever**.
  The contract's "after the automatic read has STARTED" implies auto-read
  is on, but it is not stated, and a rail that masks `$4200` around a long
  upload (CLAUDE.md "Forced-Blank Does NOT Mask NMI") and polls input there
  would hang. Latent; see F5.
* a caller late in active display (line 224, near its end) clocks into the
  next auto-read; the contract says "until line 224". Latent, stated.

**Where the emulator is my only evidence.** Mesen's `Multitap` slot routing
(index → register), the empty-slot behaviour, and the exact timing of the D7
race. No Mesen source is on disk (`/tmp/Mesen2*` hold only the built core), so
I could not read the device model. fullsnes agrees with the routing
(L3414-3424). I make no claim beyond fullsnes for real hardware; in
particular the 0→1 settling time (L3420, L3427-3428) is not modelled
anywhere and is respected only by construction (nothing reads the port after
the restore).

## 5. Cost

Re-measured with exec breakpoints bracketing the single `jsr mtap_read`
(address found from each ROM's own label file / byte image), 120 samples each,
`MesenRunner`, master cycles, jsr+rts included:

| ROM | adapter | min | max | lines (max) | histogram |
|---|---|---|---|---|---|
| `four_pads` (e34fb353) | no | 136 | 136 | 0.10 | 136×120 |
| `four_pads` | yes | 2,202 | 2,202 | 1.61 | 2,202×120 |
| `mtap_probe` (caller at top of VBlank) | no | 136 | 136 | 0.10 | 136×120 |
| `mtap_probe` | yes | **6,220** | **6,528** | **4.79** | 6220×6, 6286×36, 6330×15, 6396×45, 6462×17, 6528×1 |

* The implementer's 136 / 2,202 reproduce exactly.
* "Only paid with an adapter": true (136 mc without — a `jsr`, a DP load, a
  branch, an `rts`; 0 for rails that do not compose `mtap`).
* Worst case on `four_pads`, lag frame included: 2,202 — the rail cannot reach
  the guard's waiting paths (§4).
* **Worst case for the feature**: a caller that arrives in VBlank before the
  auto-read has started waits it out — ~4,000-4,300 mc of spin on top of the
  2,202 of work, 4.6-4.8 lines. This is the D7 guard doing its job, and most
  of it is idle spin that the caller would otherwise have to pay somewhere,
  but it is the per-frame cost a rail with a short NMI body sees, and neither
  docs/102 §7.2, the capability envelope row ("2,202 mc/frame with the
  adapter"), nor `test_the_present_path_stays_under_two_scanlines` says so.
  See F2.
* PAL not measured (neither by the implementer nor me).

## 6. Harness default path

* Code: `_apply_port2` is a no-op in pad mode; `ensure_port2_device` returns
  without a `SetSnesConfig` when the mode is already right; `advance` latches
  overrides 2-4 and grows the input log only when the adapter is configured
  or `pad3/4/5` is passed; `_raise` text unchanged in pad mode.
  `test_the_default_config_is_the_two_pad_config_it_always_was` checks the
  config struct bytes.
* **Empirical, by me**: a seven-step two-pad script (both pads, d-pad + face
  buttons) through `Machine` on `sprite_game` and `split_h_2p_demo`, recording
  per-step md5 of all WRAM (128 KB), OAM, VRAM, CGRAM, the input log and the
  replay triple — once with the **base** tree's `vendor/`, once with the
  branch's, same ROM file: **JSON byte-identical** for both rails. A third run
  in which an adapter `Machine` (four_pads, `pad3` held) ran and closed first
  in the same process, then the default run: **byte-identical** to base. The
  default path is unchanged and an adapter does not leak into the next load.
* Latent only: `ensure_port2_device` re-applies the *base* config when the
  mode flips, so a `set_power_on_random_latches(True)` made before a load
  that flips the mode back would be silently undone (its docstring says so).
  No test calls `set_power_on_random_latches` today (grep). LOW, accept.

## 7. Demo, judged on screenshots I captured

Scratch: `<scratch>/mtap_audit1/shots/` (11 PNGs) from the e34fb353 binary, with OAM dumped beside each:

| shot | state | what is on screen |
|---|---|---|
| 01 | no adapter, idle | red + blue tokens, red + blue ring lamps; no P3/P4 (OAM Y=240) ✓ |
| 02 | no adapter, P1 right, P2 X | P1 moved +42 px, both lamps lit ✓ |
| 03 | no adapter, pad3/pad4 overrides latched | identical to 01 ✓ |
| 04 | adapter, idle | four tokens in four quadrants, four ring lamps ✓ |
| 05-08 | adapter, each pad alone (diagonals) | only that player's token moves (±42 px both axes), only its lamp lit ✓ |
| 09 | adapter, all four moving at once | all four tokens moved, all four lamps lit ✓ |
| 10 | adapter, slot 4 (pad5) only | nothing changes — slot 4 unread, as decided (D3) ✓ |
| 11 | adapter, P3 taps A | P3 token attr $74 (h-flip) ✓ |

Against the owner's words — "a demo game that can read inputs from all four
controllers": met; it visibly reads all four, independently and at once.
Against the brief's "the screen shows which pads are connected/pressed":
*pressed* is met. *Connected* is met only at adapter granularity, and the
screen gives a viewer no way to know that: an empty port 2 still shows a blue
"connected" P2, and an adapter with one pad in it still shows four players.
The picture is also bare — 8×8 dots, no player numbers, no "no adapter"
indication — which is a polish point, not a correctness one. F1 covers the
substance.

## 8. Width / memory discipline (`git diff aee087f0 -- '*.asm' '*.inc' '*.toml'`)

* Every multi-path label carries its width: `mtap.asm` `@det_a/@det_b/@absent`
  (.a8), `@present` (.a16), `@wait_start/@wait_done/@read_over` (.a8, every
  arriving path is A8), `pad_btn/pad_btnp` arms (.a16); `play.asm`
  `@no_flip…@no_up`, `@shown/@ring/@lamp/@next` (.a16, all arrivals A16);
  `fp_obj.asm` `@slot/@park` (.a8); probe loops annotated. `make width-check`
  exit 0.
* `tay` in `fp_move` (`play.asm:98`) and `tax` sites run in A16 — no stale
  high byte. Fixed-count `rol` in A8 rotate one byte each, as intended.
* Stack: `phx/plx` (`play.asm:99/162`, `:212/228`) and the probe's
  `phx/pha/pla/plx` are all in I16/A16 on every arm; nets zero. No push inside
  a width toggle.
* `; WIDTH-RISK:` markers: none added. None of the six risk categories is
  present (no macro toggling width, no interrupt handler, no width change
  inside a loop that pushes) — absence is correct, not an omission.
* DP ownership: all 14 bytes are `[[claims.dp]]` in `mtap/feature.toml`,
  zeroed in `[init]` and by `mtap_init`; every access is `z:ES_*` symbolic.
  `four_pads` state is `@dp` in `state.toml`. No raw DP literal. `ES_MTAP_ON`
  doubles as detection scratch (A/B bytes) before being overwritten with the
  verdict — inside its own claim, fine.
* Registers: `JOYSER` ($4016-$4017) and `WRIO` ($4201) declared by `mtap`;
  grep confirms no other writer of `$4016`/`$4201` in `engine/`, `vendor/rom`.

## 9. Test-surface check and falsification

Each new test reads the region its name claims: DP words and the probe's
recorded `pad_btn`/`pad_btnp` answers (`test_mtap`), OAM bytes / VRAM / CGRAM
/ screenshot pixels (`test_four_pads`), master clock at breakpoints
(`test_mtap_cost`), hand-run WRAM results with no engine code (`test_mtap_harness`,
Level 0). Edge tests cover press → hold → release. Two surface notes:

* `test_the_present_path_stays_under_two_scanlines` measures only the demo's
  call timing (where the guard never waits); the name claims the present path
  in general, and on the probe that path costs 4.8 lines (F2).
* docs/102's MT-7 row says the surface is "`$2137`-latched counter changes
  after the read"; the test actually reads the slot routing on the next
  auto-read (a better surface). Record and test disagree (F7).

`make falsify SET=mtap` (implementer's set), re-run: **6/6 FIRED**, `git
status after restore: (clean)`.

Audit-authored plants (one line each, run last and alone through
`tools/falsify.py`'s `run_plant`: baseline md5, patch, rebuild, md5 moved,
tests, restore from in-memory snapshot, md5 back):

| plant | file | named test(s) | verdict |
|---|---|---|---|
| P4 low nibble one shift short | `mtap.asm` | `test_every_button_lands_…[3]` | FIRED |
| `pad_btnp` out-of-range answer dropped | `mtap.asm` | `test_out_of_range_players_answer_zero_…` | FIRED |
| P3 read from `$421C` instead of `$421E` | `mtap.asm` | `test_every_button_lands_…[2]` | FIRED |
| D7 guard keyed to line 226 | `mtap.asm` | `…lands…[3]`, `…first_frame_only[3]` | FIRED |
| demo draws P3/P4 without the adapter | `play.asm` | `test_without_the_adapter_players_3_and_4_are_absent` | FIRED |
| demo's tick loop skips player 4 | `play.asm` | `test_each_token_moves_…[3]` | FIRED |
| detection's `B ≠ $FF` rejection removed | `mtap.asm` | all of `test_mtap.py` | **TEST-BLIND** (13 passed) |

The last one was planted expecting it to survive: no test (and no harness
device) presents B=$FF, so fullsnes' second condition is unverified code. LOW
(F8). After the run: `git status --short` empty, `git diff --stat` empty,
`mtap_probe.sfc` / `four_pads.sfc` back to their baseline md5s.

## 10. Findings

**F1 — HIGH (false claim → reduced scope): per-pad "connected" was dropped on
a premise fullsnes contradicts.** docs/102 D10 (`docs/102_multitap_four_players.md:189-192`):
"fullsnes does not document what a standard pad returns after its 16th bit,
so a presence bit would rest on an undocumented behaviour." fullsnes does
document it: Joypad bits, "17th and up — Padding (always 1=Low) (or 0=High
when no pad connected)" (L3181), and the controller-ID table, "0000.00000000
No controller connected / 0000.11111111 Normal Joypad" (L3021-3022). The
branch's own Level-0 test relies on it (`test_mtap_harness.py`
`test_without_the_adapter_pads_3_and_4_reach_nothing`: "Port 2's plain pad
keeps answering 1s after its 16 bits"), and D10 itself says Mesen models an
empty tap slot. Consequence for the owner's demo: "which pads are connected"
is shown at adapter granularity only (P1/P2 always, P3/P4 iff adapter) —
criterion 9 partial. *Recommend: fix.* Correct D10; add a per-player
presence word (17th bit: one extra read of `$4016` bit 0 for P1, of `$4017`
bits 0/1 for P2/P3 after the auto-read; P4 needs its 13th-17th clocks, i.e.
the 12-bit saving is given back for P4 only when presence is wanted), drive
the lamps from it, and test it with Mesen's empty-slot configuration
(`Port2SubPorts[i].Type = 0`) and an empty port 1/2. If the owner prefers
adapter-level, record that as their decision, not as a hardware limit.

**F2 — MEDIUM: the cost claim is a best case presented as the cost.** Measured
worst case for a caller in VBlank before the auto-read starts: 6,220-6,528 mc
(4.6-4.8 NTSC lines), vs the 2,202 mc (1.61 lines) stated in docs/102 §7.2,
`docs/capability_envelope.md` ("2,202 mc/frame with the adapter, 136
without"), and asserted by `test_the_present_path_stays_under_two_scanlines`,
whose name claims the path in general but whose ROM can only reach the
guard's no-wait branch. The demo itself is fine (2,202 on every frame,
including lag frames). Also, even the best case is 1.61 lines against the
brief's "well under 2" (stated honestly in §7.2). *Recommend: fix the record
and the test* — state both numbers (demo-timing 2,202; worst case ~6.5k with
the cause), and measure the worst case on `mtap_probe` in the cost module
with its own bound; consider whether to accept 1.61 or shave further (the
record notes FastROM-mirror code would cut ~¼).

**F3 — LOW: `input_read` race (implementer's §7.3) — real, latent.** fullsnes
L2962-2965: reads of `$4218-$421F` during the auto-read return incorrect
values. `input_read` (`engine/features/input/input.asm:43-53`) waits only while
busy, so a caller in VBlank before the start can read the latch as it begins;
the probe reproduced a lost button. No rail is exposed (every rail syncs on an
armed NMI whose body outlasts the ≤382 mc window — confirmed for
`scene_mgr`). But `mtap.asm:9` documents the per-frame order as
`input_read, input2_read, mtap_read` — the exposed order; the probe had to
invert it. *Recommend: defer* (out of scope; `input` is microzero-pinned),
file a follow-up to share `mtap_read`'s guard, and note the order hazard in
the `mtap` header.

**F4 — LOW: D9 (mid-frame `$2137` reader composed with `mtap`) is unenforced.**
Real per fullsnes L1365-1369; no rail composes both today. *Accept*, as stated.

**F5 — LOW: `mtap_read` hangs if called on line 225 with the auto-read
disabled.** `mtap.asm:148-152` waits for a busy bit that never comes. Contract
implies but does not state "auto-joypad enabled". *Recommend: fix the contract
text* (or bound the wait).

**F6 — LOW: "frame cost unchanged" with no adapter is 136 mc, not zero, for a
rail composing `mtap`.** Inherent to runtime detection. *Accept*; the record
already says "one flag test".

**F7 — LOW: record drift.** (a) docs/102 §3 MT-7 surface ("`$2137`-latched
counter changes") ≠ the test's surface (next auto-read's routing).
(b) `docs/09_feature_register.md:986` says P4 is "16 clocks"; the code clocks
12. (c) `docs/capability_envelope.md:24` still says "All 40 games" (Part 1
now says 41), and L152's region row ("33 of the 40 compose it … all 33 are
measured") is now wrong: `four_pads` composes `region` + `tick_scale` and is
in no `tools/rate_oracle.py` `RAILS` entry, so its PAL parity is unmeasured.
*Recommend: fix* (text only; add `four_pads` to the rate oracle or say it is
unmeasured).

**F8 — LOW: detection's `B ≠ $FF` rejection (`mtap.asm:84-86`) is untested.**
Removing it leaves all 13 `test_mtap` cases green (audit plant). The harness
has no stuck-pin-5 device. *Accept or defer* — document as unverified.

**F9 — LOW: harness `ensure_port2_device` resets the base config on a mode
flip** (undoes a prior `set_power_on_random_latches(True)`); documented in the
docstring, no current caller. *Accept.*

## 11. Verdict

**Remediate** — the engine feature, harness and demo are correct on the
emulator and, as far as fullsnes speaks, on hardware; the full suite and every
gate are green; nothing existing changed. What stands between this and "ship"
is the record and one owner-facing gap:

1. **F1** (HIGH) — correct D10; implement per-pad presence and drive the
   demo's "connected" lamps from it (or get the owner's explicit acceptance of
   adapter-level "connected").
2. **F2** (MEDIUM) — state the worst-case cost; measure and bound it in the
   cost module.
3. **F7** (LOW, cheap) — the four record fixes.
4. **F5** (LOW, cheap) — state "auto-joypad enabled" in `mtap_read`'s contract.

Defer: F3 (follow-up issue), F8. Accept: F4, F6, F9.
