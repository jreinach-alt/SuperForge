# Remediation-1: four-pad adapter (multitap) and four players (`claude/multitap-4p`)

> Remediation of `docs/audit/multitap-4p-audit-1.md`, per CLAUDE.md "Audit
> Protocol" step 3. In scope: F1, F2, F5, F7. Out of scope: F3 (deferred;
> follow-up note in docs/102 §7.3 only), F4, F6, F9 (accepted), F8 (deferred;
> documented as untested). The remediation agent did not write the sprint or
> the audit. Audit-2 validates this.

| | |
|---|---|
| Branch | `claude/multitap-4p`, base `origin/main` @ `aee087f0`, audited HEAD `e34fb353` |
| Commits | `48608115` docs: audit-1 report · `c2ce93d6` 1/3 harness · `8689c1e2` 2/3 presence + cost + contract · `a9df18c9` 3/3 the record · plus the commit that adds this file |
| Hardware reference | `<main checkout>/docs/reference/fullsnes.txt` (owner's tree; line numbers are that file's) |
| Scratch | `<scratch>/mtap_rem1/` |

## F1 (HIGH) — per-pad presence

### Record

`docs/102` D10 (L210 onward) rewritten: the old premise ("fullsnes does not
document what a standard pad returns after its 16th bit") is marked wrong and
the two fullsnes passages cited — Joypad bits "17th and up — Padding (always
1=Low) (or 0=High when no pad connected)" (L3181) and the controller-ID table
"0000.00000000 No controller connected / 0000.11111111 Normal Joypad"
(L3021-3022).

### Measured first (scratch Level-0 ROM `ext.asm`, `ext_measure.py`)

Bits 17-24 of every line under nine configurations, before any engine code:
a line with a pad reads `$FF`, an empty port or adapter slot `$00`, exactly as
fullsnes says (e.g. `pad,tap1010`: port 1 `ff`, port-2 pin 4 `ff`, pin 5 `00`,
slot 3 bits 17-24 `ff`, slot 4 `00`). Mesen models it; the harness only had
to be able to configure it.

### Harness (commit `c2ce93d6`)

* `vendor/mesen_runner.py` `PORT_EMPTY`, `TAP_FULL`, `check_ports`,
  `ensure_ports(port1, port2, tap_slots)`; `_apply_port2` sets
  `ControllerType::None` (0) for an empty port 1, an empty port 2, or an
  empty adapter sub-port. `ensure_port2_device(mode)` is now
  `ensure_ports(port2=mode)` (port 1 pad, slots full). The default two-pad
  path is still a no-op with no `SetSnesConfig` call.
* `vendor/machine.py` `Machine(..., port1=, tap_slots=)`; the replay-triple
  text names the ports only when they are not the default.

### Design and cost

* **Bit:** one clock past the 16th of each line. P1 = `$4016` bit 0; P2 =
  `$4017` bit 0 (plain pad or slot 1); P3 = `$4017` bit 1 (slot 2); P4 = slot
  3's 17th clock of `$4017` bit 0 under WRIO.7 = 0.
* **When:** a census instead of a per-frame read (the owner's rule).
  `mtap_init` (`engine/features/mtap/mtap.asm:99`) takes it at boot: a
  fresh strobe, 16 clocks of both ports, the 17th; with an adapter 17 clocks
  of slot 3. Then it **re-latches every pad** (`:196`; see "found on the way").
  With an adapter, `mtap_read` (`:251`) re-takes it every
  `MTAP_CENSUS_EVERY` = 32 calls (`:36`), split over two consecutive calls:
  players 1-3 (`@census`, `:319`; one more clock of `$4016` and `$4017`
  before the select line drops, merged into bits 0-2 by an eor/and/eor masked
  merge) then player 4 (`@census_p4`, `:337`; slot 3's 13th-17th clocks
  after its 12 buttons). The per-frame price is the census clock alone —
  `dec z:ES_MTAP_TICK` / `beq @census` (`:300-301`).
* **Why split:** both halves on one call measured 2,666 mc + the first half
  (~380 mc), over two scanlines. Split, each call stays under.
* **No adapter:** unchanged absent path (flag test, 136 mc); presence is
  the boot census only (a pad plugged in after power-on is not reported
  connected until reset; its buttons still read). Stated in D10 and tested.
* **API:** `ES_MTAP_PADS` (2 B DP, `feature.toml`; bit n = player n+1,
  `MTAP_PAD_P1..P4` at `mtap.asm:26-29`) and `pad_here` (`:467`; X = player
  0-3 → A = its bit or 0, Z set iff absent, out-of-range → 0; a 4-byte table
  lookup, `mtap_pad_bit` `:480`). New DP claim `mtap_tick` (2 B: countdown +
  which half next). DP 14 → 18 B, only for rails composing `mtap`.
* **Demo:** `game/four_pads/scenes/play.asm:179` `jsr pad_here` replaces
  "players 0-1 always, 2-3 iff adapter". Token and lamp are drawn only while
  that player's pad is connected.

### Cost, before → after (`tests/test_mtap_cost.py`, 72 calls each, master cycles)

| configuration | before (audit-1) | after |
|---|---|---|
| no adapter, `four_pads` | 136 / 136 | **136 / 136** (unchanged) |
| adapter, after the auto-read, `four_pads` | 2,202 / 2,202 (1.61 lines) | **2,256** plain (66×), **2,594** / **2,626** on the two census calls (3× each); max **1.93 lines** |
| adapter, top of VBlank, `mtap_probe` | 6,220 / 6,528 (4.79 lines) | **6,274 / 6,886** (5.05 lines; plain calls 6,274-6,516, census calls up to 6,886) |

Presence costs 54 mc on every call with an adapter, plus ~340-370 mc on 2
calls in 33: ~84 mc/frame averaged. Without an adapter: 0.

### Presence results on the emulator

All 36 harness configurations (port 1 pad/empty × port 2 pad / empty /
adapter with each of the 16 slot patterns): `ES_MTAP_PADS` and the probe's
`pad_here` answers equal the configuration's expected value at boot and after
two census periods (scratch `presence_scan.py`: 36/36; committed as
`test_mtap.py::test_presence_names_exactly_the_connected_pads_at_boot_and_after`).

### Found on the way (fixed): a boot transient the census introduced

The first `test_four_pads.py` run after presence landed had P4's token
flipped at boot. Cause: `four_pads`' first `mtap_read` runs before any
automatic read (MAIN arms NMITIMEN and enters its loop outside VBlank, where
the guard reads "over"), and the boot census had left slot 3 clocked past its
16th bit, so that call shifted out padding 1s — every P4 button "pressed" for
one frame. Fixed by re-latching every pad at the end of `mtap_init`
(`mtap.asm:196`), which restores the state detection alone used to leave.
Plant `boot-relatch-dropped` keeps it fixed. The related first-call `$421E`
read (P3 before any automatic read) is recorded in docs/102 §7.3, not fixed.

## F2 (MEDIUM) — the worst-case cost

* `docs/102` §7.2 (L288 onward) rewritten: a table with both call timings,
  the histogram, the census split, and a "Demo timing vs the worst case"
  paragraph. D7 (L183 onward) also states the worst case.
* `docs/capability_envelope.md` L130 (input row): states 136 without; 2,256
  plain / 2,594 / 2,626 census after the read; 6,274-6,886 (4.6-5.0 lines)
  at the top of VBlank.
* `tests/test_mtap_cost.py`:
  * `test_the_present_path_stays_under_two_scanlines` → **renamed and
    re-scoped** `test_a_call_after_the_auto_read_stays_under_two_scanlines_census_included`
    (`:132`): `four_pads`, 72 samples (> 2 census periods), asserts ≥ 4
    census calls are in the sample and every call < 2,728 mc.
  * **new** `test_a_caller_at_the_top_of_vblank_pays_the_auto_read_wait`
    (`:153`): `mtap_probe`, breakpoints on new labels `mp_read_begin` /
    `mp_read_end` through a new labelled twin (`Makefile:489`
    `$(BUILD)/mtap_probe.lbl`, `cmp`-proved; `mtap-probe` now builds it).
    Asserts min > 4,224 mc (the call waited the whole read) and max < 2,728 +
    4,224 + 382 = 7,334 mc.
  * Output region: the master clock at execution breakpoints.

## F5 (LOW) — contract

`mtap_read`'s CONTRACT `assumes:` now opens with "the AUTOMATIC JOYPAD READ
IS ENABLED (NMITIMEN bit 0 set): with it off, a call on the first VBlank line
waits forever for a read that never starts" (`mtap.asm:227`), and states the
4.6-4.8-line wait (§7.2). docs/102 D7 has the same limit and why the wait is
not bounded.

## F7 (LOW) — record drift

* docs/102 MT-7 surface (L108): now describes what the test reads (the next
  automatic read's slot routing, DP words), and says the H/V-latch side
  effect is not what it reads. MT-8 rewritten, MT-9 added, FP-2 updated.
* `docs/09_feature_register.md` `mtap` row (L986): "16 clocks" → "12 clocks
  … the ID nibble is not clocked", plus presence. `fp_obj` row (L924):
  per-pad presence. Census table regenerated by `make register-write`
  (`dp`×7 → ×9).
* `docs/capability_envelope.md` L24: "All 40 games" → "All 41 games in Part
  1". L93 (`four_pads`): per-pad presence.
* **Region:** `four_pads` registered in `tools/rate_oracle.py` (`:704`,
  a 0.7 s shuttle on player 1, two observables) and measured:

  | observable | NTSC/s | PAL/s | ratio |
  |---|---:|---:|---:|
  | `token_oam_x` (OAM px) | 120.198 | 120.184 | **0.99989** |
  | `player_x` (screen px) | 120.198 | 120.101 | **0.99919** |

  Envelope L152, `docs/98` (new amendment) and the CLAUDE.md pointer now say
  **36 of 43** rails compose `region` and **34** are measured. Counting
  surfaced a pre-existing drift outside this lane: `aurora` and `mill`
  compose `region` but are in neither the rate oracle's `RAILS` nor the
  envelope's Part 1 table. Stated, not fixed.

## F3, F8 — records only

* F3: docs/102 §7.3 "Follow-up (audit-1 F3, deferred)" (L356): share the
  guard with `input_read`/`input2_read` in its own lane (re-pins
  `microzero`); the per-frame order in `mtap`'s header is the exposed order.
* F8: docs/102 D6 (L166): `B ≠ $FF` rejection is in the code but untested;
  no harness device presents B = $FF.

## Tests added or changed

| test | output region read |
|---|---|
| `test_mtap_harness.py::test_the_17th_bit_is_1_behind_a_pad_and_0_on_an_empty_port_or_slot` [36] (Level 0) | WRAM result block of a hand-run read: the 17th bit of each line, slots 3/4's 17th, and the button words with every button held on every index |
| `test_mtap_harness.py::test_an_impossible_port_configuration_is_refused` | `check_ports` raises |
| `test_mtap_harness.py::test_a_default_machine_after_an_empty_port_machine_gets_both_pads_back` [3] | the module's mode state + the Level-0 ROM's 17th bits after a default load |
| `tests/fixtures/mtap_harness/probe_mtap.asm` | gains `R_X17` / `R_X17B`; the existing words unchanged |
| `test_mtap.py::test_presence_names_exactly_the_connected_pads_at_boot_and_after` [36] | `ES_MTAP_PADS` DP word + the probe's recorded `pad_here` answers (`US_HERE`, players 0-5), at boot + 5 and + 75 calls |
| `test_mtap.py::test_the_census_re_reads_presence_once_a_period_in_two_halves` | `ES_MTAP_PADS`, poked to its complement, read after every call: unchanged until the census, bits 0-2 back on one call, bit 3 on the next; the next census exactly 32 calls after |
| `test_mtap.py::test_without_an_adapter_presence_is_the_boot_census_and_never_re_read` | `ES_MTAP_PADS` poked; still poked 96 calls later |
| `test_four_pads.py::test_a_player_is_drawn_only_while_its_own_pad_is_connected` [7] | OAM token + lamp entries (x, y, tile) |
| `test_four_pads.py::test_the_screen_shows_only_the_connected_pads_lamps` | screenshot pixels: P1/P2/P4 token body and lamp ring in their palette colours, P4's lit centre, P3's token and lamp positions = backdrop |
| `test_mtap_cost.py` (two cases above) | master clock at breakpoints |
| `tests/fixtures/mtap_probe/` | records `pad_here` into `US_HERE`; `mp_read_begin/end` labels |

Module counts: harness 9 → 49,
`test_mtap` 13 → 51, `test_four_pads` 18 → 26, `test_mtap_cost` 2 → 3.

## Falsification

`make falsify SET=mtap` — **11/11 FIRED**, exit 0, both ROMs back to their
md5 on rebuild (`mtap_probe` `d6b0e203…`, `four_pads` `256a0cad…`). New plants
(`tools/plants/mtap.py`): `boot-census-p4-dropped`, `census-never-reruns`,
`census-half-clobbers-p4`, `boot-relatch-dropped`, `demo-ignores-presence`;
`d7-guard-skipped` now also names the worst-case cost case (FIRED, 3 red).

Harness hand plants (the harness has no ROM artifact; patch → run → restore,
file md5 `7013693e…` back each time):

| plant | red |
|---|---|
| empty adapter slot configured as a pad | 30 (every tap config with an empty slot), 1111 configs green |
| `check_ports` accepts tap_slots without an adapter | `test_an_impossible_port_configuration_is_refused` |
| `ensure_ports` compares only port 2 | 34, including `…gets_both_pads_back[port1]` (this plant was blind until the test was parametrised per port; the strengthened test is what is committed) |

## Gates and pins

width-check 0 · time-check 0 · map-check 0 · tick-check 0 · cleanroom 0 ·
register 0 · rail-registered 0 · toy-bad 0 · rom-unbacked 0 · measure 0.
`microzero` `9ca5e47f5134d534c607fcb302c79b4f` unchanged; `sprite_game`,
`split_h_2p_demo`, `room`, `patrol`, `stomper` md5-identical to the base
builds. Full suite: see the section below.

## Test runs

One module per process (verbatim summary lines, after the last change):

```
test_mtap_harness: 49 passed in 23.21s
test_mtap:         51 passed in 42.79s
test_four_pads:    26 passed in 27.43s
test_mtap_cost:     3 passed in 8.05s
test_rate_oracle:   8 passed in 1.50s
test_register:     47 passed in 13.54s
test_make_gates:   11 passed in 6.02s
```

Full suite, `make test XDIST=3` after building every rail, no `PYTEST_ADDOPTS`:

```
= 6 failed, 2749 passed, 15 skipped, 491 warnings, 1 error in 2254.08s (0:37:34) =
schedule-check: ok — 140 module run(s) across 3 worker(s), no module split across workers
```

| red | triage |
|---|---|
| `test_batch_union.py` ×4 | PyYAML not installed — pre-existing, environmental (same four on base) |
| `test_dma_init_forced_blank.py::test_every_observed_fire_named_exactly_one_channel`, `…matches_a_declared_claim` | load-sensitive: **9 passed** run alone on the same tree. (The second one's `TypeError` is in its own failure message: it sorts keys that include `None`.) Nothing in this branch touches the rails or code it observes |
| `test_scene_mgr_cut.py::test_the_cut_holds_its_forced_blank_inside_vblank` (setup error) | **pre-existing flake, not this branch.** Reproduces alone (it saw 5, 7 and 9 `$2100` writes where it expects 4). A/B on one scratch copy of HEAD, the same `meteor_event.sfc` (md5 `d076b27e…`, a rail this branch does not touch), only `vendor/mesen_runner.py` + `vendor/machine.py` swapped: the **pre-remediation** harness (e34fb353) passed **2 of 8**, this branch's **1 of 8** — red most of the time either way. It drives the legacy `MesenRunner` with exec breakpoints; audit-1's run happened to get a green one |


## Screenshots

`…/mtap_rem1/shots/01..10_*.png` and `…/mtap_rem1/contact_sheet.png`: pad+pad
(P1, P2), port 2 empty (P1), port 1 empty (P2), both empty (nothing drawn),
full adapter (all four), slots 1+3 (P1, P2, P4), port 1 empty + slot 2 (P3
only), adapter with no pads (P1), slot 4 only (P1), slots 1+3 with P4
holding right+down+X (P4's lamp lit, token moved). Each matches its
configuration.


---

# Round 2 — remediation of audit-2 (`docs/audit/multitap-4p-audit-2.md`)

Agent: a fresh remediation agent (wrote neither the sprint, the audits nor
round 1). In scope: N1 (MEDIUM), N2-N4 (LOW), privacy of the branch's added
lines. N5, N6 recorded as follow-ups only (docs/102 §7.4); F3/F4/F6/F8/F9
unchanged. Commits on `claude/multitap-4p`, not pushed:

| commit | content |
|---|---|
| `06c718fb` | audit-2 report + its paper-cut section, copied verbatim |
| `d039ef9c` | N1: harness index mapping + Level-0 test |
| `08915cdb` | N2-N4 record fixes, N5/N6 follow-ups, local paths scrubbed, round-2 paper cuts |
| (this commit) | this section |

## N1 (MEDIUM) — pad indices with port 1 empty → fixed

**Measured first** (scratch `rawmap.py`, latching RAW override indices on
`probe_mtap_harness.sfc`, one index at a time, for all 36 configurations of
`tests/test_mtap_harness.py::_CONFIGS`): with port 1 empty, raw index 0
reaches port 2 / slot 1 and raw 1-3 reach slots 2-4; raw 4 reaches nothing.
An empty port 2 or an empty adapter slot shifts NOTHING (e.g. `pad-multitap-0101`:
raw 2 → `$421E`, raw 4 → manual bit 1; raw 1 and 3 → nothing). So it is port
1 alone that Mesen drops from its count, not "connected controllers".

**Fix.**

* `vendor/mesen_runner.py:1551` — new `override_index(position, port1)`:
  identity when port 1 holds a pad; `position - 1` (and `None` for position
  0) when it is empty. Comment at `:1509` points at it.
* `vendor/machine.py:413` — `_latch` latches `_mr.override_index(
  controller_index, self.port1)` and returns without a call when it is `None`.
  Before: `self._lib.SetInputOverrides(controller_index, state)`.
  `advance`'s docstring (`:445`) states the positions contract and that the
  input log is by the same positions.
* `MesenRunner.set_input` unchanged: it has no port-1 knob, its loads always
  put a pad in port 1 (`ensure_port2_device` → `ensure_ports(port2=…)`), so
  its indices never shifted.

**Input log.** It already recorded by harness position (`(frames, pad1,
pad2[, pad3, pad4, pad5])`); with the mapping fixed, position k IS port
position k, so entry k now records what was held on that port. The new test
asserts it per press.

**Default path.** Spy on `SetInputOverrides` (scratch `spy.py`): a default
Machine's two advances issue raw indices `[0, 1, 0, 1]` — the same calls as
before (port 1 present → identity). Port 1 empty: `[0, 0]` (pad1 latched
nowhere, pad2 → raw 0). Adapter: `[0..4, 0..4]`; port 1 empty + adapter:
`[0..3, 0..3]`. No config call added (the mapping is pure Python). The
pinned ROMs are unchanged (below).

**Test** — `tests/test_mtap_harness.py:238`
`test_each_pad_index_drives_its_own_port_position_whatever_is_empty`, 36
cases (every configuration of `_CONFIGS`). Level 0 (the hand-run probe, no
engine code). For each position 0-4 in turn it holds ONE `padN` with its own
button bit (B, Y, Select, Start, Up), reads the probe's WRAM result block
(`R_JOY` words for `$4218`/`$421A`/`$421E` and the two manual words
`R_MAN0`/`R_MAN1`), and asserts the set of words that changed versus idle is
exactly `{line: bit}` for the line `_line_for` (`:225`) derives from the
configuration alone — or empty when that position has no device; then
releases and asserts the block is back to idle. It also checks the input log
entry (secondary; the verdict is the hardware read).

**Fault plant** (by hand; `tools/falsify.py` cannot register a plant with no
ROM artifact, see paper cuts): `vendor/machine.py:413` changed to
`raw = controller_index` (the shifted mapping) → **16 failed, 20 passed**:
`empty-pad` and `empty-multitap-*` for every slot pattern except `0000` (the
two port-1-empty configurations with nothing behind port 2, `empty-empty`
and `empty-multitap-0000`, have nothing to misroute). Restored with the
inverse `sed`; `md5sum -c` of `vendor/machine.py` OK.

**Screen.** Audit-2's shot 11 re-taken on `four_pads` (port 1 empty, slots
2-4, `pad3` holding X): P3's (green) lamp is lit, P4's (yellow) ring is
hollow — before the fix it was P4's.

## N2 (LOW) — envelope region-parity row → fixed

`docs/capability_envelope.md:152`. Before: "…opt-in per rail 36 of the 43
rails…" (3 `|`), the "**0.832**" clause after the aurora/mill parenthesis.
After: "…opt-in per rail | 36 of the 43…" (4 `|`, same as its neighbours),
and the clause back where `e34fb353` had it — "at a band of **0.994–1.027**
against the **0.832** an uncompensated rail reads (`docs/98` §1); `four_pads`
measures…". No number changed.

## N3 (LOW) — census period → text made to match the code (33)

The code's period is 33 calls: the second half reloads `ES_MTAP_TICK` to
`MTAP_CENSUS_EVERY` = 32, the 32nd call after it reaches 0 and is the next
first half (`tests/test_mtap.py:303-310` asserts exactly that). Kept the
code — 32 is a countdown, not a stated period, and changing it would move
every census-timing test and cost number — and fixed the text:

* `docs/102_multitap_four_players.md:231` "every `MTAP_CENSUS_EVERY` = 32
  calls" → "once every 33 calls (the countdown `MTAP_CENSUS_EVERY` = 32 runs
  out on the 32nd call after a census's second half, and that half is the one
  extra call)".
* `docs/09_feature_register.md:986` "every 32 calls in two halves" → "once
  every 33 calls in two halves (`MTAP_CENSUS_EVERY` = 32 plain-countdown calls
  + the second half)". `make register` 0.
* `engine/features/mtap/mtap.asm:31-38, :224, :465` — comments only ("calls
  between censuses" → "census countdown (period = this + 1 calls)"; "every
  MTAP_CENSUS_EVERY calls" → "every MTAP_CENSUS_EVERY + 1 calls"). Comment-only:
  `four_pads` and `mtap_probe` md5s unchanged.
* `docs/capability_envelope.md:130` ("two census calls in every 33") and
  docs/102 D10 ("within 33 calls") already said 33.

## N4 (LOW) — two counts in docs/102 → fixed

* §7.4 (`:395`): `test_mtap_harness.py` 47 → **85** (49 collected before
  this round — 9 + 36 + 1 + 3 — plus the 36 new cases); its surface column
  names the new one-index-at-a-time read.
* §7.2 (`:330`): re-measured (scratch `cost.py`: `mtap_probe`, adapter, exec
  breakpoints on `mp_read_begin`/`mp_read_end`, master-clock delta, each call
  classified by `ES_MTAP_TICK` read at its entry breakpoint), 1,320 calls =
  40 census periods, four runs. Three runs identical: plain **6,274-6,582**
  ×1,240 (hist 6274×106, 6340×339, 6384×174, 6450×413, 6516×196, 6582×12),
  players 1-3 half 6,612-6,854 ×40, player 4 half 6,644-6,886 ×40. Text now
  "6,274-6,582 for plain calls … and 6,612-6,886 on census calls", stated
  as a sample (the bound is the test's 7,334). One run (the first) also
  recorded three plain deltas outside every class — 410, 5,024 and 6,522 mc
  — that did not recur; recorded in §7.2 as unexplained, not hidden.

## N5, N6 — follow-ups only

Recorded in docs/102 §7.4 ("Follow-ups, not this lane", `:427`). No change
to `tests/test_dma_init_forced_blank.py` or `tools/falsify.py`.

## Privacy

Local paths in lines the branch adds rewritten: the session scratch
directory → `<scratch>/`, the main checkout's absolute path → `<main
checkout>` (audit-1: 3, audit-2: 3, remediation-1: 2 occurrences; scratch
`scrub.py`). The brief's privacy grep over `git diff origin/main...HEAD`
(added lines naming the home directory, its mangled scratch form, or a
personal mail address) prints nothing.

## Test runs (round 2)

Modules, one process each, own `SF_MESEN_HOME`, `-c <empty ini> --rootdir .`:

```
test_mtap_harness: 85 passed in 106.10s (0:01:46)
test_mtap: 51 passed in 93.69s (0:01:33)
test_four_pads: 26 passed in 65.13s (0:01:05)
test_mtap_cost: 3 passed in 17.04s
```

Full suite, `make test XDIST=3`, no `PYTEST_ADDOPTS`:

```
= 4 failed, 2787 passed, 15 skipped, 491 warnings, 1 error in 3251.55s (0:54:11) =
schedule-check: ok — 140 module run(s) across 3 worker(s), no module split across workers
```

2,792 run cases (4 + 2,787 + 1) = audit-2's 2,756 + the 36 new. Triage:

| red | triage |
|---|---|
| `test_batch_union.py` ×4 | PyYAML not installed — environmental, same four as base |
| `test_scene_mgr_cut.py::test_the_cut_holds_its_forced_blank_inside_vblank` (setup error: 13 `$2100` writes where it wants 4) | **the pre-existing flake** remediation-1 and audit-2 both reproduced on base. Its fixture (`blank_windows`) drives the legacy free-running `MesenRunner` (boot, wall-clock run, `debug_break`, `set_input`) — none of which round 2 changed: `override_index` is called only from `Machine._latch` (`grep`), and `MesenRunner.set_input` is untouched. Alone, 6 runs each on ONE base tree (`git archive aee087f0`, built) with only `vendor/machine.py` + `vendor/mesen_runner.py` swapped: base vendor 5/6 green, round-1 vendor (`ff4d78fe`) 3/6, round-2 vendor (HEAD) 1/6; the base tree as-is 2/4. Red on every vendor; the rate moves with load (the HEAD batch ran 33-47 s per run against 22-26 s for the others) and samples this small do not separate the vendors. Not this round's code; the flake is a free-running wall-clock fixture and should move to `Machine` in its own lane |

Gates (sequential): `width-check 0 · time-check 0 · map-check 0 · tick-check
0 · cleanroom 0 · register 0 · rail-registered 0 · toy-bad 0 · rom-unbacked
0 · measure 0`.

ROM md5s after the round: `microzero 9ca5e47f5134d534c607fcb302c79b4f`,
`sprite_game 9c8a69cf…`, `split_h_2p_demo b26ff7b4…`, `room 9327eeca…`,
`patrol 6d751737…`, `stomper 86906e45…` — the base (`aee087f0`) values audit-2
recorded; `four_pads 256a0cad…`, `mtap_probe d6b0e203…` — unchanged from
round 1.
