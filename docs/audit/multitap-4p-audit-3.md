# Audit-3: four-pad adapter (multitap), validation of remediation-2 (`claude/multitap-4p`)

> Independent validation of remediation round 2 per CLAUDE.md "Audit Protocol"
> step 4, and the fold decision. Research only: no code changed, no
> remediation. The auditor wrote neither the sprint, audit-1, audit-2, nor
> either remediation round.

## 1. What was audited

| | |
|---|---|
| Branch / HEAD | `claude/multitap-4p` @ `b93ae1ff`, checked out **detached** in an isolated worktree |
| Base | `origin/main` @ `aee087f0` (14 commits, `git log --oneline aee087f0..HEAD`) |
| Round-2 commits | `06c718fb` (audit-2 doc), `d039ef9c` (N1), `08915cdb` (N2-N4, follow-ups, privacy), `b93ae1ff` (its report) |
| Inputs | `docs/audit/multitap-4p-audit-2.md`; `docs/audit/multitap-4p-remediation-1.md` § "Round 2" |
| Scope | N1 (MEDIUM), N2-N4 (LOW); N5/N6 deferred (checked only that they are recorded); the two open questions (`test_scene_mgr_cut` flake; the 410 / 5,024 / 6,522 mc cost outliers); privacy |
| Toolchain | `PATH=$HOME/toolchains/src/cc65/bin:<main checkout>/.venv/bin:$PATH`; no `PYTEST_ADDOPTS`; every emulator process its own `SF_MESEN_HOME`; pytest as `-c <empty ini> --rootdir .` |
| Scratch | `<scratch>/mtap_audit3/` — scripts `ab_smc.py`, `ab_stats.py`, `n1_drive.py`, `identity.py`, `func_calls.py`, `bp_calls.py`, `bp_testway.py`, `met_lbl.sh`, `falsify.sh`; JSON results beside them |
| Comparison trees | `git archive aee087f0` (`base/`), `git archive HEAD` (`tH/`), and `git archive HEAD` with base's two `vendor/` files copied in (`tVB/`; `diff -rq base/vendor tVB/vendor` empty) — each built in place |
| Host | 8 cores, shared with other sessions' emulator sweeps: load average 3.5-21 during this audit. "Nothing else running" was true of THIS audit's own work (the A/B ran alone), not of the box |

## 2. Test re-runs

### Modules, one process each (verbatim last line)

```
test_mtap_harness rc=0 :: 85 passed in 62.59s (0:01:02)
test_mtap rc=0 :: 51 passed in 43.38s
test_four_pads rc=0 :: 26 passed in 31.70s
test_mtap_cost rc=0 :: 3 passed in 11.92s
```

The round-2 commits touched one test module (`tests/test_mtap_harness.py`,
above); the rest of their diff is `vendor/machine.py`, `vendor/mesen_runner.py`,
`engine/features/mtap/mtap.asm` (comments only) and docs. The full suite was
not re-run (remediation-2 ran it; the only red it reported outside PyYAML is
question 3a below, run here 44 times on its own).

### Gates (sequential, `make <gate>`)

```
width-check rc=0     time-check rc=0     map-check rc=0     tick-check rc=0
cleanroom rc=0       register rc=0       rail-registered rc=0
toy-bad rc=0 (collision gate intact)     rom-unbacked rc=0 (rom-claim backing gate intact)
measure rc=0
```

### Pinned ROMs

| ROM | HEAD worktree | base tree (`aee087f0`, built here) |
|---|---|---|
| microzero | `9ca5e47f5134d534c607fcb302c79b4f` (the pin) | `9ca5e47f5134d534c607fcb302c79b4f` |
| sprite_game | `9c8a69cf873118e81cc043dce9f487f1` | identical |
| split_h_2p_demo | `b26ff7b406cfa4219fd2d19a4e1d117e` | identical |
| room | `9327eecaf23c97a18dd6d4a9e94e4001` | identical |
| patrol | `6d751737be9572c38517bcee4eb69454` | identical |
| stomper | `86906e45adc1a058a272cfd47884b358` | identical |
| meteor_event | `d076b27ee231851bc58f2d822f34716d` | identical (and in `tH/`, `tVB/`) |
| four_pads / mtap_probe | `256a0cad…` / `d6b0e203…` — unchanged from round 1, as claimed | — |

Re-checked after the falsification plants (§5): `four_pads` and `mtap_probe`
rebuilt to the same two md5s.

## 3. Per finding

### N1 (MEDIUM) — pad indices with port 1 empty → **REMEDIATION VERIFIED**

**Driven by hand, one index at a time** (`n1_drive.py`, Level-0 probe
`build/probe_mtap_harness.sfc`, all 36 configurations: port 1 ∈ {pad, empty}
× port 2 ∈ {pad, empty, adapter × 16 slot patterns}). For each position 0-4
alone it holds one button (B, Y, Select, Start, Up), reads the probe's result
block (`$4218`, `$421A`, `$421E` words and the two manual words), diffs against
idle, releases and re-reads. The expected line is written in the script from
fullsnes' wiring (port 1 data1 → `$4218`; port 2 data1 → `$421A`; port 2 data2
→ `$421E`; WRIO.7 = 0 → `$4017` bit 0/1 = slots 3/4), not imported from the
test.

| run | positions driven | mismatches |
|---|---|---|
| HEAD harness (`override_index` live) | 180 | **0** — every position reaches exactly its line, or nothing when empty; every release returns to idle |
| HEAD with `override_index` forced to identity (the raw Mesen index) | 180 | 54, in exactly the 16 configurations with port 1 empty and a device behind port 2 |

The raw run re-measures remediation-2's claim about Mesen independently:
`empty-multitap-1111` raw 0 → `$421A`, 1 → `$421E`, 2 → manual bit 0, 3 →
manual bit 1, 4 → nothing; `empty-multitap-0101` raw 1 → `$421E`, raw 3 →
manual bit 1 (empty slots shift nothing); `empty-pad` raw 0 → `$421A`;
port-1-present configurations identical mapped and raw.

**Input log.** In all 180 presses `input_log[-1]` has the held button at
entry `1 + position` and `()` everywhere else, including for positions with
no device (the log records what was held, by position). Two-pad machines log
3-tuples unless `pad3+` is passed, as the docstring says.

**Default path byte-identical** (`identity.py`, audit-1/2's method): a
seven-step two-pad script through `Machine` on `sprite_game` and
`split_h_2p_demo`, per-step md5 of all WRAM, OAM, VRAM and CGRAM, plus the
input log and the replay triple, with base `vendor/` (`tVB/`) and HEAD's:

| | sprite_game | split_h_2p_demo |
|---|---|---|
| per-step hashes base == HEAD | ✓ (7/7 steps × 4 regions) | ✓ |
| input log, triple (`30e06996…` / `68ad4423…`) | ✓ | ✓ |
| raw `SetInputOverrides` indices (spy) | `[0, 1, 0, 1, …]` both | `[0, 1, 0, 1, …]` both |
| HEAD after three closed non-default Machines in the same process (port 1 empty; port 2 empty; port 1 empty + adapter `0101`, buttons held) | identical to base; module state after `('pad', 'pad', (True, True, True, True))` | same |

The test `test_each_pad_index_drives_its_own_port_position_whatever_is_empty`
(`tests/test_mtap_harness.py:238`) reads the hardware result block and is
Level 0; falsified in §5 (16 red / 36 for the shifted mapping, 36 red / 36 for
a swapped log entry).

### N2 (LOW) — envelope region-parity row → **REMEDIATION VERIFIED**

`docs/capability_envelope.md:152` has 4 `|` like rows 148-151 (awk count), the
"**0.832**" clause sits after "**0.994–1.027**" as `e34fb353` had it, and no
number moved (diff `06c718fb..08915cdb` read whole).

### N3 (LOW) — census period worded two ways → **REMEDIATION VERIFIED** (one residual, N8)

The code's period is 33: `dec z:ES_MTAP_TICK` / `beq @census`
(`mtap.asm`), the second half reloads 32, and `tests/test_mtap.py:303-310`
asserts the next halves land at 0-based calls 31/32 after it. Confirmed
mechanically: planting `MTAP_CENSUS_EVERY = 31` fails exactly that test with
"next came back on calls 30/31; want 31/32" (§5). docs/102 :231, docs/09 :986
and the three `mtap.asm` comments now say 33 / "+ 1". Comment-only in ASM:
`four_pads` and `mtap_probe` md5s unchanged. One residual outside the three
places audit-2 named: `tests/test_mtap_cost.py:20-21`'s docstring still says
"on two calls in every MTAP_CENSUS_EVERY" (N8).

### N4 (LOW) — two counts in docs/102 → **REMEDIATION VERIFIED**

§7.4 says 85 for `test_mtap_harness.py`; the module collects and passes 85.
§7.2 now states 6,274-6,582 plain / 6,612-6,886 census as a sample with the
7,334 bound. This audit's strict-paired samples (§4b): probe plain/census
6,274-6,952 over 17,498 calls — two calls at **6,952**, above the stated
sample range and inside the bound (N9, record only). The "three unexplained
outliers" note is now explained (§4b) and should say so (N7).

### N5, N6 — recorded as follow-ups (docs/102 §7.4 "Follow-ups, not this lane") ✓.

## 4. The two open questions

### 4a. Does HEAD's `vendor/` make `test_scene_mgr_cut` fail more often? — **No.**

**Method** (`ab_smc.py`): the one case
(`test_the_cut_holds_its_forced_blank_inside_vblank`, whose module fixture
`blank_windows` is the red one) run alone, 22 times per arm, arms interleaved
with the order alternating every pair (H,B / B,H / …), one process per run,
own `SF_MESEN_HOME`, nothing else of this audit running. Arms: `tH/` (HEAD
tree, HEAD `vendor/`) vs `tVB/` (HEAD tree, base `vendor/`); identical
`meteor_event.sfc` (`d076b27e…`) in both.

| arm | pass | spurious hits per run (rare − 4), sorted | run time |
|---|---|---|---|
| HEAD `vendor/` | **7/22** | 0×7, 1,1, 2,2,2, 3,3,3,3, 4,4,4, 5,5, 7 (mean 2.23) | 7.8-14.8 s |
| base `vendor/` | **7/22** | 0×7, 1,1,1,1, 2,2,2,2, 3,3,3, 5,5, 7, 8 (mean 2.09) | 7.7-15.9 s |

Fisher exact (two-sided) on pass/fail: **p = 1.0**. Mann-Whitney on the
spurious-hit counts: U = 260, z = 0.42, **p = 0.67**. Pairs agree with each
other (18/22 concordant) and with the host, not the vendor: passing runs began
at load 6.3 on average, failing ones at 9.4; pairs 8-17 passed in both arms,
the rest mostly failed in both.

**Why it fails — found.** Every failure is the fixture's own count assertion
("expected two `$2100` writes per cut switch … saw 5-12"). Resolving the
extra PCs against a label twin of `meteor_event` (`met_lbl.sh`, `-g` + `-Ln`,
`cmp` identical to the shipped ROM):

| PC | label | what it is |
|---|---|---|
| `$81FD` | in `sm_nmi_core` | the NMI's INIDISP commit (`nmi_pc`, ~460 per run) |
| `$8182`, `$81D4` | `@switch` + 5, `@cut_done` + 17 | the instruction after each real `sta a:$2100` — the 4 the test wants |
| **`$81E0`** (94 of the 95 extras, both arms) | `sm_frame_sync` + 7 | the instruction after `wai` (`$81DF` = `CB`, `$81E0` = `A5 20`). **No store to `$2100` there** |
| `$82D6` (1 extra, HEAD arm) | `region_init` entry | boot-time code, no `$2100` store |

These are not `$2100` writes: they are the debugger stops that
`MesenRunner.run_to_break` can manufacture on a free-running emulator — its
own docstring (`vendor/mesen_runner.py`, "A True IS NOT A PROOF THAT A
BREAKPOINT MATCHED") describes the mechanism (`IsExecutionStopped()` true
during an EmulatorLock/DebugBreakHelper window → `_settle_at_break` issues the
`Step` that creates the stop at whatever PC the CPU is at) and measured it at
~2.6% on `room`. A CPU that spends its idle time in `wai` is stopped there. The
fixture classifies "every PC that is not the NMI's" as the switch, so each
manufactured stop is counted as a switch write. Its rate rises with host load,
which is the whole pass/fail pattern above.

**Does anything in HEAD's `vendor/` reach that path?** `git diff aee087f0 HEAD
-- vendor/` read whole: on the free-running path the only additions are
`ensure_port2_device(self._port2)` before each of `MesenRunner`'s four
`LoadRom` calls and `_apply_port2(cfg)` inside `_make_base_snes_config`. For a
default runner `ensure_ports` compares `('pad','pad',TAP_FULL)` with the
module state and returns `False` without a config call, and `_apply_port2` is
a no-op for two plain pads (`test_the_default_config_is_the_two_pad_config_it_
always_was` pins the struct bytes). `run_to_break`, `_settle_at_break`,
`breakpoints`, `snes_state_snapshot`, `set_input` and `debug_break` are not in
the diff. `override_index` is reached only from `Machine._latch` (grep).
Verdict: pre-existing harness flake, not this branch (N10).

### 4b. The 410 / 5,024 / 6,522 mc outliers — **reproduced; a measurement artifact, not a functional defect.**

**Functional, on hardware-faithful timing** (`func_calls.py`, lockstep
`Machine`, adapter, no breakpoints, no wall clock): each frame holds a fresh
pseudo-random 12-button pattern on all four pads, then reads
`ES_INP_CUR`/`ES_INP2_CUR`/`ES_INP3_CUR`/`ES_INP4_CUR` (P4 masked to its 12
clocked bits):

| ROM | calls (frames) | same-frame match, all four pads | lag-1 match |
|---|---|---|---|
| `mtap_probe` (calls at the top of VBlank — the D7 race) | 6,000 (`US_FRAMES` 60 → 6,060) | **6,000 / 6,000** | 0 |
| `four_pads` (calls after the NMI body) | 6,000 | **6,000 / 6,000** | 0 |

A call that did not wait for and read the automatic read would have left P3 =
the previous frame's pattern (a lag-1 match) or garbage; there is none in
12,000 calls.

**The cost measurement, reproduced and attributed.** `bp_testway.py` is
`tests/test_mtap_cost.py::_measure` with identical debugger traffic (one
`snes_state_snapshot` per hit) that also keeps the PC of the hit that closed
each pair; `bp_calls.py` is the same plus PPU frame / scanline at every hit
and P3/P4 read at every true end hit, under held known pads (P3 = `$2060`,
P4 = `$1090`).

| run | calls | pairs closed by a PC that is NOT the end mark (cost mc, closing PC) | strict pairs (closed by the end mark) | P3/P4 at the end mark |
|---|---|---|---|---|
| probe, `bp_calls` | 5,499 | none | 6,274-6,952 | 5,500 / 5,500 correct |
| probe, test-way #1 | 6,000 | **992** @ `$8217` (`mtap_read` `@wait_done`) | — | — |
| probe, test-way #2 | 6,000 | **46** @ `$81F1` (`mtap_read` entry), **3,560** @ `$8215`, **1,278** @ `$8219`, **2,262** @ `$8219` (all in `@wait_done`) | — | — |
| four_pads, `bp_calls` | 5,499 | **10** @ `$8757` (inside the `jsr`), **116** @ `$82F9`, **870** @ `$8341`, **1,404** @ `$8365` (all inside `mtap_read`) | 2,256-2,626 | 5,500 / 5,500 correct |
| four_pads, test-way | 6,000 | **1,908** @ `$8385` (slot-3 clocks) | — | — |

Every under-count (10 of them in 28,998 calls; remediation-2 saw 3 in 5,280)
was closed by a stop at a PC inside the call, never by `mp_read_end` /
`fp_pads_end`; in the instrumented runs the real end hit followed with the
correct P3/P4 and, strict-paired, the same call measured in the normal band.
The same runs logged 143 (probe) and 162 (four_pads) stops at PCs that are
neither mark — 2.6-2.9% of calls, the rate the `run_to_break` docstring
measured — mostly in the probe's own VBlank polls (`$83C5-$83CF`) and in
`four_pads`' `sm_frame_sync` `wai` (`$81B3`, 152 of 162): the 4a mechanism
again. `_measure` (`tests/test_mtap_cost.py:90-110`, the `elif t0 is not None:` at :108) closes a pair on **any**
non-begin hit (`elif t0 is not None:`), so a manufactured stop inside the
call closes it early. The bias is downward only, so the test's upper bounds
stay sound; its floor `lo > AUTO_READ_MC` on the probe can go red on the
harness alone (N7). 410 / 5,024 / 6,522 are the same class (5,024 and 6,522
land in the wait and the work; nothing makes 6,522 special once the closer is
not the end mark).

## 5. Falsification (last and alone; `falsify.sh`)

| plant (one line) | named test | result |
|---|---|---|
| `vendor/machine.py:413` `raw = controller_index` (drop the mapping) | `test_mtap_harness -k each_pad_index` | **16 failed, 20 passed** — the 16 port-1-empty configurations with a device behind port 2 |
| `vendor/machine.py:467` log entries for `pad3`/`pad4` swapped | same | **36 failed** ("pad3's press logged as (2, (), (), (), ('select',), ())") |
| `engine/features/mtap/mtap.asm` `MTAP_CENSUS_EVERY = 31` | `test_mtap.py::test_the_census_re_reads_presence_once_a_period_in_two_halves` | **1 failed** — "next came back on calls 30/31; want 31/32" |
| `vendor/mesen_runner.py:1566` empty port 1's position 0 → raw 0 instead of `None` | `-k each_pad_index` | 36 passed — **an equivalent mutant**: `advance` always latches `pad2` (position 1 → raw 0) right after `pad1`, so whatever position 0 latched on raw 0 is overwritten before the frame runs. Not observable through `advance`; not a test gap |

Each file restored from a byte copy and md5-checked; `make mtap-probe
four_pads fp-labels` rebuilt the planted artifact back to `d6b0e203…` /
`256a0cad…`. Afterwards `git status --short` and `git diff --stat` were empty
(before this report and the paper-cut entry were written).

## 6. Privacy

* the brief's privacy grep over `git diff aee087f0...HEAD` (added lines naming the home directory, its mangled scratch form, the session tmp dir, or a webmail address)
  → **empty** (rc 1). A wider pass over added lines (user name, scratch/venv
  forms) finds only `$HOME/toolchains/...` and `<main checkout>` placeholders.
  Commit messages carry no path or address; they carry the standard
  `Claude-Session:` trailer.
* Author / committer emails, `aee087f0..HEAD`:
  * the account's GitHub **noreply** address (author = committer): `b93ae1ff`, `08915cdb`, `d039ef9c`, `06c718fb`
  * **a personal webmail address** (author = committer) on the other ten:
    `ff4d78fe`, `a9df18c9`, `8689c1e2`, `c2ce93d6`, `48608115`, `e34fb353`,
    `a135a36c`, `19e31a47`, `75859d67`, `ad555b95` — to be rewritten before
    the push, as the brief says.

## 7. New findings

**N7 — LOW: `test_mtap_cost`'s pairing counts a debugger artifact as a call.**
`_measure` closes a begin mark on the next hit of ANY PC. `run_to_break`
manufactures stops at arbitrary PCs (its docstring), ~2.7% of calls here, and
≈0.03% land inside the call (10 / 28,998), giving a too-small cost. On the
probe the floor `lo > 4224` turns red for ~2% of runs (72 samples × ≈2.9e-4)
and reads as a ROM defect; upper bounds are unaffected (downward bias only).
docs/102 §7.2 records the outliers as "Not explained". *Action:* pair strictly
— `elif t0 is not None and st.cpu_pc & 0xFFFF == end & 0xFFFF:` (and drop
`t0` on any other PC) — and replace the §7.2 note with the attribution above.
A one-line, test-only change; fine before the fold or as its first follow-up.

**N8 — LOW: one residual "every 32" wording.** `tests/test_mtap_cost.py:20-21`
docstring "on two calls in every MTAP_CENSUS_EVERY" — two calls in every 33.
*Action:* reword with N7.

**N9 — LOW, record only:** the probe's strict-paired maximum here is 6,952 mc
(2 of 5,499 calls), above docs/102 §7.2's sampled 6,886; the section already
says the range is a sample and the bound is 7,334. *Action:* none required;
widen the quoted sample if §7.2 is touched for N7.

**N10 — LOW, pre-existing, not this branch:** `test_scene_mgr_cut`'s
`blank_windows` counts `run_to_break`'s manufactured stops (PC `$81E0`, after
`sm_frame_sync`'s `wai`) as cut-switch `$2100` writes (§4a). *Action, own
lane:* keep only hits whose PC follows a `sta $2100` (the label twin gives
them), or confirm each with `write_count`, or move the fixture to `Machine`.

## 8. Verdict

| finding | verdict |
|---|---|
| N1 (MEDIUM) pad indices with port 1 empty | **REMEDIATION VERIFIED** — 180/180 positions correct across all 36 configurations, read off the Level-0 hardware result block one index at a time; input log by position; default path byte-identical to base on two rails, raw calls `[0,1,0,1…]`, no leak after non-default Machines; test falsified |
| N2 (LOW) envelope row | **REMEDIATION VERIFIED** |
| N3 (LOW) census period | **REMEDIATION VERIFIED** — code period 33 confirmed by plant; one residual docstring (N8) |
| N4 (LOW) docs/102 counts | **REMEDIATION VERIFIED** — 85 matches; §7.2 sample note now explainable (N7, N9) |
| Regression | none: modules green, gates 0, pinned ROMs identical to base |

**Aggregate: REMEDIATION VERIFIED.**

**Recommendation: FOLD.** Both open questions resolve in the branch's favour
with evidence: the `test_scene_mgr_cut` red is independent of the vendor
change (7/22 vs 7/22, p = 1.0; mechanism identified in pre-existing harness
code the branch does not touch), and the cost outliers are under-counts made
by the test's pairing around the same harness artifact — 12,000 calls on
hardware-faithful timing read every pad correctly, and every real end-mark
hit in 11,000 instrumented calls read the correct P3/P4. N7/N8 are a one-line
test fix plus a docstring and are best done before the fold (minutes; removes
a ~2% false red from a test this branch adds), but nothing found blocks it.
Rewrite the ten personal-address commits before pushing.
