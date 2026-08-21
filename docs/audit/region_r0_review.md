# region R0 — an independent review

> Independent verification of commits `8624b33`, `b16a469`, `cf649d5` (tip
> `cf649d5`) against [`docs/94`](../94_region_support_spec.md) §3's **R0** and
> §4's constraints, as amended. The claim of record is
> [`docs/97`](../97_region_r0_landing.md).
>
> This review is research only. No code was changed and no finding below was fixed.
> Every experiment ran in a throwaway copy outside the repo; the worktree was
> clean before this file was written and is clean apart from it.

---

## 0. Aggregate verdict

**YES — R0 satisfies `docs/94` §3 and §4, with one clause PARTIAL.**

All four R0 clauses are discharged and all six §4 constraints hold. I re-ran
every measurement `docs/97` rests on and **every number reproduced to the
digit**, including the halves, the frame periods, the 31-image enumeration, the
`$FFD7` census across all 56 linked images, the `microzero` pin, the 37-rail
picture diff with its PAL non-vacuity control, and both planted refusals.

The one PARTIAL is **R0's third clause, second half** — *"…and a build declares
the region it targets."* The `.ifndef SF_HDR_DEST` hatch is real (I proved it by
hand: defining `SF_HDR_DEST = $02` puts `$02` at `$7FD9`, and reverting restores
the pinned `microzero` md5), but **nothing in the tree exercises it and no test
covers it**. Every image declares `$01`. The mechanism is present; the clause is
discharged only in the weak sense that a byte exists and is now overridable.

Nothing I found falsifies a landed claim. The findings are **documentation
accuracy** (three statements about what the build does that the build does not
do), **test-claim accuracy** (one docstring that says a case catches something a
planted defect proves it does not), and **one pre-existing gate-integrity hole**
in the census counter which I reproduced and which is the most probable
mechanism behind the implementer's reported census discrepancy.

---

## 1. Per-criterion table

### `docs/94` §3 — R0

| # | criterion | verdict | evidence |
|---|---|---|---|
| R0-1 | Boot reads `$213F` bit 4 and stores a region flag readable by game code | **✓** | `engine/features/region/region.asm:43-63` — `stz` then `lda a:$213F` / `and #RGN_PAL_BIT` (`RGN_PAL_BIT = 1 << 4`, :35) / `beq`. Called once from `MAIN` (`game/scroller/main.asm:112`, `game/brawler/main.asm`). Claim: one `dp` word, `engine/features/region/feature.toml`. Emitted as `ES_RGN_PAL` in `build/scr/symbol_map.json` / `build/br/symbol_map.json` (global, `dp`, 2 B, consumer `engine:region`) |
| R0-2 | The flag is correct under `SF_REGION=ntsc` and `SF_REGION=pal` | **✓** | Measured on the shipped `scroller.sfc` (same md5 both arms): `ES_RGN_PAL` = `{0}` on NTSC, `{1}` on PAL. Re-measured under `SF_HW_POWERON=ones`, `=zeros`, `=random` — all six boots correct (§4.1 below). Held for a **30 s real-time run**: 1,803 NTSC frames and 1,501 PAL frames, one distinct value each |
| R0-3a | The header destination byte is derivable rather than hardcoded | **✓** | `vendor/rom/header.inc:58-72` — `.ifndef SF_HDR_DEST` / default `$01` / `.byte SF_HDR_DEST`. Proven by hand: `SF_HDR_DEST = $02` before the include yields `$7FD9 = $02` on `microzero`; reverting rebuilds `e45ddeabac4218cd71709da7b9fcc849` |
| R0-3b | …and a build declares the region it targets | **PARTIAL** | All 56 images declare `$01`. No build overrides, no test covers the hatch, and `test_destination_byte_is_the_declared_default` asserts only the default. See **F5** |
| R0-4 | The ROM-size byte tells the truth on all 37 rails | **✓** | All **56** linked images read directly: **2 declare `$05` and are 32,768 B; 54 declare `$09` and are 524,288 B; none lies.** Exactly the note's §2.1 sentence. Pre-change: 20 of 37 rails declared `$05` at 524,288 B, 17 declared `$09` — reproduced from the pre-change build |
| §3 framing | *"discharged by a test that reads rendered output, per CLAUDE.md rule 2"* | **✓, with reasoning** | R0's subject has no picture. The tests read the feature's **own output region** — the flag word out of a running machine, the header bytes out of the linked image — and the player-visible half of the promoted timebase is read from **OAM** (`ES_O_KNIGHTS+2`, the tile byte the PPU draws from). The NTSC-picture constraint is discharged by a **pixel** diff (§4.1), though by a tool rather than by a suite case — see **F9** |

### `docs/94` §4 — constraints

| # | constraint | verdict | evidence |
|---|---|---|---|
| §4.1 | NTSC picture pixel-identical per rail; every image change enumerated | **✓** | `tools/tb_picture_diff.py`, pre-change image as reference, frames 120/300/600, both regions, **all 37 rails re-run**: NTSC **IDENTICAL 37/37**. PAL differs on **exactly `scroller` and `brawler`** (the non-vacuity control fires) and is vacuous on the other 35. `brawler` re-run under its oracle drive (`--pad left`) as well: NTSC identical, PAL differs on all three frames. Enumeration verified complete and correct — §2 below |
| §4.2 | `microzero.sfc` holds `e45ddeabac4218cd71709da7b9fcc849` | **✓** | Measured on a fresh build. Also asserted by `tests/test_c2_sram_class.py:265` (3 passed) |
| §4.3 | All 37 rails keep building; `make bare-check` stays GREEN | **✓ / delegated** | Full rail build from a clean `build/`: exit 0, 56 images, 43 s. `make bare-check` **not run here** — it is being run against this exact tip in parallel, and two would contend for the box. See §7 |
| §4.4 | `width-check`, `time-check`, `toy-bad`, `rom-unbacked`, `measure`, `register`, `rail-registered`, `cleanroom` clean | **✓** | All eight re-run green, plus `tick-check`. Transcript in §6 |
| §4.5 | Allocator remains the authority; no raw address literals; anything new that occupies a resource is declared | **✓** | `region` declares one `dp` claim; `tick_scale` declares **none** — confirmed against the emitted maps, where no placement carries consumer `engine:tick_scale`. `no_literals.py` ran on every rail build (it is a build step). `RGN_PAL_BIT = 1 << 4` and `TS_ONE = 1 << 8` are shifts precisely because the gate refuses hex operands |
| §4.6 | 512 KB cap and no-SRAM rule hold for anything this work adds | **✓** | Max image 524,288 B across all 56. `git diff a8fcbc8..cf649d5` adds no `sram` claim (the three `$01` / two `$03` SRAM-size bytes are pre-existing `save`-feature rails) |

---

## 2. The 31-image enumeration (`docs/97` §5)

Built the tree at `a8fcbc8` (the pre-change tip) into a scratch clone with the
same target list, then md5-compared all 56 images against the tip.

**Exactly 31 images moved.** The moved set is exactly `docs/97` §5's list — no
image moved that is absent from the list, and no listed image failed to move.

* **(a) 29 header-only.** Byte-diffed, not assumed: in every one of the 29 the
  only differing offsets are `$7FD7` (`$05` → `$09`) and the
  complement/checksum pair. 28 of them differ at `{$7FD7, $7FDC, $7FDE}` and
  `split_h_persp_demo` at `{$7FD7, $7FDC, $7FDD, $7FDE, $7FDF}` (its checksum
  high bytes moved too). 19 rails + the 10 variant/control images, exactly as
  listed.
* **(b) 2 composition.** `scroller.sfc` `f34ae672…` → `1cc6f109…` and
  `brawler.sfc` `1b72f8d1…` → `af404239…`, both matching §5's before/after
  pairs.
* **Unchanged, byte for byte:** the other 16 rails plus `toy`, `probe_vblank`,
  `probe_cpu`, `probe_cpu_step` — 25 images.

**"The seventeen hand declarations moved zero bytes" — proven, not accepted.**
16 of the 17 are byte-identical outright. `brawler` is the seventeenth and it
did move, which §5's bullet does not qualify (**F4**). I settled the substance
directly: with `brawler`'s composition reverted to `a8fcbc8` and its hand
`SF_HDR_ROM_SIZE = $09` line deleted — so the byte comes from the linker
config — the image rebuilds to **`1b72f8d129fd7a3b667a9c4d9c8c7586`**, the
pre-change md5, exactly. The derivation moved zero bytes on all 17; `brawler`'s
movement is entirely the composition.

---

## 3. The reported census discrepancy — the gate, and what I found

> *"`make register` printed `census matches the tree (155 dirs)` while the tree
> held 157; a direct `gen_register.py --check` on the same tree reported drift;
> could not reproduce."*

### 3.1 What I ruled out

* **Not a `make` wrapper problem.** `register:` (Makefile:2603) is exactly
  `$(PY) tools/gen_register.py --check`, `PY := python3`, no prerequisites, and
  `register` **is** in `.PHONY` (Makefile:21, a continuation line). `make
  register` and the direct call print identical output on this tip.
* **Not a stale count within one process.** `n = len(census)` comes from
  `load_tree()`'s live filesystem glob (`gen_register.py:151`), and the OK line
  is printed **only after** `fresh == current` has already held — so within one
  invocation and one repo root the printed count cannot be stale relative to the
  tree it just compared.
* **Not a dir/name mismatch.** A `feature.toml` whose `name` differs from its
  directory is refused by `allocator/schemas.py:959` before the census sees it.
  Planted and confirmed.
* **Not a missed addition.** Planting a properly-named 158th dir makes
  `--check` report drift by name (`audit_probe_b is in the census but has no
  'supplies / serves' entry`). The gate has teeth on that axis.

### 3.2 What I reproduced — and it is a real hole

The census is built from **`feature.toml` files**, not from directories:

```python
for p in sorted(repo.glob("**/feature.toml")):        # gen_register.py:151
...
census = {n: d for n, d in everything.items()
          if (features_dir / n / "feature.toml").exists()}   # :177
```

but the generated sentence it emits asserts **directories**:

```
**All 157 dirs under `engine/features/` accounted for.**   docs/09 §3, :665
```

Planted in a scratch copy: a directory `engine/features/audit_half_made/`
holding an `.asm` and **no `feature.toml`**. On disk there are then **158**
dirs. The gate says:

```
register OK: census matches the tree (157 dirs); demand lint reached 18/25 …
```

**exit 0.** A half-created feature directory — source present, declaration
absent — is invisible to the census, to the count, and to the doc's
completeness sentence, and the gate reports OK against a number that is not the
number of dirs in the tree. That is precisely the shape the report names.

### 3.3 The most probable history

I could not reproduce a *false OK on a genuinely drifted tree* — that direction
is structurally closed. What I can reproduce is the **exact reported pair of
observations**, and the timeline that produces them needs no bug beyond §3.2:

1. `engine/features/region/` and `engine/features/tick_scale/` exist as
   directories holding their `.asm` (so `ls` says **157**), with their
   `feature.toml` not yet written. `make register` legitimately counts **155**
   and legitimately says OK, because `docs/09` also holds 155.
2. The two `feature.toml` files are written. Now the census is 157, `docs/09`
   still 155, and a direct `--check` reports **drift**.

Both statements are true, minutes apart, and after `make register-write` the
condition is gone for ever — which is why it did not reproduce.

A second, equally unfalsifiable-after-the-fact candidate is a **second repo
root**: `REPO` is `Path(__file__).resolve().parent.parent`, so running
`make register` from another checkout of this repo scans *that* tree. The
pre-change clone prints, verbatim,
`register OK: census matches the tree (155 dirs); demand lint reached 18/25
demand rows and found no contradiction`.

### 3.4 Verdict on the census discrepancy

**The gate is not lying about drift. It is lying about "dirs".** No claim in
`docs/97` depends on the count being a dir count, and the 157 in §4.3 is
correct for this tip (157 `feature.toml` files, 157 directories). But the gate's
own reach line and the doc's completeness sentence can both report OK while a
directory under `engine/features/` is unaccounted for. That is a
gate-integrity defect — pre-existing, **not introduced by R0**, and one line to
close. See **F3**.

---

## 4. Adversarial pass

### 4.1 The flag is written on both paths before any read — measured

`region_init` writes on both arms (`stz` at :46, `sta` at :55) and
`feature.toml`'s `[init] zero` names the claim. Note that `[init] zero` emits a
**comment contract** into the generated `.inc`
(`allocator/allocate.py:1394-1403`), not code — so `region_init`'s own `stz` is
the only actual initialisation, and the position of `jsr region_init` in `MAIN`
is load-bearing (**F10**).

Measured on `build/scroller.sfc`, all six combinations:

| `SF_HW_POWERON` | region | `ES_RGN_PAL` | `US_TS_STEP` |
|---|---|---|---|
| `ones` (all RAM `$FF`) | ntsc | `{0}` | `{2}` |
| `ones` | pal | `{1}` | `{2,3}` |
| `zeros` | ntsc / pal | `{0}` / `{1}` | `{2}` / `{2,3}` |
| `random` | ntsc / pal | `{0}` / `{1}` | `{2}` / `{2,3}` |

`ones` is the decisive arm: an unwritten word would read `$FFFF`. It reads 0 and
1. This is also the strongest available evidence for `region_init`'s **A16
entry contract**, which `width_lint` cannot check across files (CLAUDE.md rule
6): entering in A8 would leave the high byte as power-on garbage and the `ones`
arm would fail on NTSC. It does not.

### 4.2 The mask, bit 7, and long-run stability

The test is a mask (`and #RGN_PAL_BIT`, `RGN_PAL_BIT = 1 << 4`), read in the
file. Stability, measured over 30 s of **real** time in each region:

```
LONGRUN region=ntsc : frames= 1803 real_s=30.00 distinct ES_RGN_PAL values= [0]
LONGRUN region=pal  : frames= 1501 real_s=30.02 distinct ES_RGN_PAL values= [1]
```

**But the suite cannot tell the mask from the compare.** I planted the exact
defect the mask exists to avoid — `cmp #(RGN_PAL_BIT | 3)` / `bne` in place of
`and` / `beq` — rebuilt `scroller`, and re-ran the probe:

```
PLANT(compare) region=ntsc : ES_RGN_PAL= [0] TS_STEP= [2]
PLANT(compare) region=pal  : ES_RGN_PAL= [1] TS_STEP= [2, 3]
```

Identical, passing results. The harness boots deterministically, so `$213F`
bit 7 is always clear at the read instant and the compare is right by
coincidence. `test_the_flag_is_stable_for_the_whole_run`'s docstring says bit 7
toggling "is exactly what a compare-against-`$13` would have picked up" — it is
not: the flag is latched **once**, so a wrong latch is stable, and stability
cannot see it. See **F2**.

### 4.3 The three pre-existing `$213F` reads

Read at the sites rather than taken from the note. `sit_cam.asm:409,430` and
`shg_cam.asm:475,496` both run `lda a:$2137` → `lda a:$213F` → `$213C`/`$213D`;
`m7f_cam.asm:230` runs `lda f:$00213F` → `lda f:$002137` → `$213C`. Every one
re-establishes the toggle state it consumes, immediately before consuming it.
The note's argument holds.

Stronger than the argument: **none of those three rails composes `region`**, so
their code did not change at all. `seam_irq_trial` and `split_h_irq_grad_demo`
are **byte-identical** pre-to-post; `mode7_flight` differs only in `$7FD7` and
its checksum pair. And all five images in that family — plus `sit_origin`,
`sit_mistime`, `shg_nograd`, `shg_origin` — are NTSC-identical in the picture
diff. The timing-fragile rails were not touched.

### 4.4 `tick_scale` claims nothing — and the `depends` claim is wrong

**Claims nothing: TRUE.** No placement in either composing rail's emitted map
carries consumer `engine:tick_scale`. `region`'s single `dp` word is the only
new claim in the tree (`ES_RGN_PAL`, 2 B, global, at dp `$0F` in `scroller` and
`$26` in `brawler`).

**"…so composing it without the flag it reads is a refusal" — FALSE.**
`allocator/allocate.py:422-447` (`resolve_features`) **auto-expands** `depends`.
Measured: removing `"region"` from `game/scroller/game.toml`'s `globals` and
building produces `ES_RGN_PAL` in the emitted map and a
**byte-identical** `scroller.sfc` (`1cc6f10974bcc9c06a60ec434ad0ce02`). It is a
silent satisfaction, not a refusal.

The safety property the sentence is defending does hold, by a different
mechanism: with `depends` removed *and* `region` uncomposed, the build fails at
assembly —
`engine/features/region/region.asm(46): Error: Symbol 'ES_RGN_PAL' is undefined`
— so a silent scale of 1.0 is impossible. But the stated mechanism is not what
the tool does, in a repo whose own rule is *"if you are about to state what a
tool does, open the tool."* Four live sites repeat it. See **F1**.

### 4.5 `tick-check`'s baseline: 356 → 356

Diffed the two baselines on the `(file, rule, message)` multiset myself:
**identical — 0 dropped, 0 added**, and per-file counts unchanged. Exactly five
entries moved line numbers:

| file | rule | line |
|---|---|---|
| `game/brawler/scenes/fight.asm` | tick-routine | 317 → 369 |
| `game/brawler/scenes/fight.asm` | tick-routine | 457 → 510 |
| `game/brawler/state.toml` | tick-state | 82 → 114 |
| `game/rpg/main.asm` | tick-constant | 74 → 70 |
| `game/rpg/main.asm` | tick-routine | 339 → 335 |

The two `rpg` moves are the deleted `SF_HDR_ROM_SIZE` block shifting lines up.
No site was silently dropped. Live gate: `tick_lint: 0 NEW finding(s) across
705 file(s); 356 held by the baseline`.

### 4.6 Both planted refusals reproduce

* **The lying header.** `microzero.sfc` copied and `$7FD7` poked to `$05`:
  `fix_checksum.py` exits 1 with the note's message verbatim and **leaves the
  bytes untouched**.
* **`TS_BASE_MAX`.** Setting `scroller`'s `TS_CAM_BASE` to `TS_BASE_MAX + 1`
  gives, verbatim, the error `docs/97` §3.1 quotes, and the rail rebuilds to
  `1cc6f10974bcc9c06a60ec434ad0ce02` afterwards. Commit `b16a469`'s whole claim,
  reproduced.

---

## 5. Judging the tests

### `tests/test_region.py` — 11 passed (27 s)

| case | reads | judgement |
|---|---|---|
| `..._flag_is_clear_on_ntsc_and_set_on_pal` | `ES_RGN_PAL` from a running machine, one image both arms | **Sound.** The flag *is* this feature's entire output; this is the output region, not a proxy. The `rom_md5` equality guard is the right control |
| `..._flag_is_stable_for_the_whole_run` | same series | **Sound as a stability check, WRONG in its stated reason.** See **F2** |
| `..._probe_really_ran_two_different_machines` | measured frame period | **Sound** — the instrument's liveness check, and it is what stops every ratio below being about nothing |
| `..._region_is_opt_in_...` | the emitted symbol maps | **Sound.** A build-shape claim checked against the build's own output, which is the primary source for it |
| `..._ntsc_publishes_the_authored_constant_on_every_frame` | `US_TS_STEP` | Set-equality over >100 frames, not an average — the right shape. It is a mechanism word, and the picture half is covered by `tb_picture_diff` rather than by a suite case (**F9**) |
| `..._pal_publishes_a_two_valued_step...` | `US_TS_STEP` | **Sound.** The `{2,3}` set equality excludes both refuted integer schemes by construction |
| `..._scaled_step_is_what_moves_the_camera...` | `US_FRAMES` deltas | **Sound and load-bearing** — it is what rules out the `lump` shape by observation rather than by argument |
| `..._guard_held_so_the_window_means_something` | `US_GAMEOVER`, `US_HP` | **Sound.** A dead-mid-window rail would average a live half with a frozen one |
| `..._walk_cycle_runs_at_the_same_rate_per_real_second` | **OAM** `ES_O_KNIGHTS+2` | **The best case in the module.** Rendered output — the sprite table the PPU draws from — over a real-time window, with a band five times its own width away from the uncompensated value |
| `..._unscaled_heartbeat_...still_reads_five_sixths` | `US_BLINK`, **same run** | **The non-vacuity control, and it is genuine.** Without it "the rates match" is satisfiable by an instrument that cannot see a difference. It also states the sprint's scope honestly |
| `..._both_of_brawlers_scaled_rates_...` | `US_TSP`, `US_TSA` | Mechanism words; acceptable because the player-visible half is covered above |

**Could any pass while the feature is broken?** One way, and I demonstrated it:
a compare-against-`$13` passes every case (§4.2). Nothing else I could construct
survives — removing `region_init` fails the `ones` arm and the PAL arm; a
scale-of-1 fails the walk-cycle case; a harness that lost the region setting
fails the frame-period case; an instrument that stopped seeing rate differences
fails the heartbeat control.

The real-time (not frame-indexed) window is the module's most important
property and it is correctly built: `tests/region_probe.py:107` advances until
the **master clock** says the requested real seconds have passed, with
`MASTER_HZ` read from the emulator's own source. A frame-indexed window would
make every ratio read 5/6 for harness reasons.

### `tests/test_rom_header.py` — 85 passed

Reads the **linked images** and compares each field to the file's own length —
the right surface, and the docstring says why a source-level assertion about
`header.inc` would not do. `RAILS` is derived from `game/*/game.toml` rather
than listed, so a new rail is covered the day it lands.
`test_the_build_step_refuses_a_lying_rom_size_byte` plants the exact historical
defect, requires the refusal, requires the message, **and** requires the bytes
to be untouched. `test_no_image_declares_32k_unless_it_is_32k` states the
regression as a property over the whole set rather than pinning a count.

Coverage gap: `RAILS + EXTRA` omits the 10 variant images and the two CPU
probes (**F9b**). Mitigated — I verified every variant build script
(`tools/build_*.sh`, 9 of them) invokes `fix_checksum.py`, so the gate covers
them at build time even though no case reads them; and I read all 56 images by
hand for this audit.

### Restoration check (the implementer's self-flag)

The implementer reported overwriting the pre-existing `test_rom_header.py` with
a same-named new file and catching it before committing.

**All four original cases are present and pass**, and the file's history is
intact:

* `git log -- tests/test_rom_header.py` → two commits, the tree's initial
  commit and `8624b33`.
* `git diff a8fcbc8 cf649d5 -- tests/test_rom_header.py` → `107 insertions,
  0 deletions`. **Zero deleted lines** — the original content survived
  byte-for-byte; the change is a docstring addition plus a new section.
* Run by name: `test_shipped_rom_checksum_is_valid[toy.sfc]`,
  `[microzero.sfc]`, `test_the_checker_actually_rejects_a_bad_checksum`,
  `test_patching_is_idempotent`,
  `test_refuses_an_image_it_does_not_recognise` — **4 passed, 81 deselected**
  (5 ids; the first is parametrised).

---

## 6. Findings

| id | severity | finding | recommendation |
|---|---|---|---|
| **F1** | **MEDIUM** | *"`depends = ["region"]` makes composing the macro without the flag a refusal"* is **false as to mechanism** — `resolve_features` auto-expands `depends`. Measured: dropping `region` from `scroller`'s globals builds a **byte-identical** ROM with `ES_RGN_PAL` still emitted. Four live sites repeat it: `docs/97` §3.2, `engine/features/tick_scale/feature.toml`, `game/scroller/game.toml`, `docs/09` §3.1 (`tick_scale` row). The safety property holds by a different route (a missing `ES_RGN_PAL` is a ca65 error, not a silent 1.0) | **fix** the wording in all four; state the real mechanism (auto-inclusion, plus an undefined-symbol refusal if `region` is absent). The commit message of `8624b33` carries it too and cannot be edited |
| **F2** | **MEDIUM** | `test_the_flag_is_stable_for_the_whole_run`'s docstring claims a compare-against-`$13` "is exactly what" bit 7 toggling "would have picked up". A planted compare passes **every** case in the module (§4.2). The flag is latched once, so a wrong latch is stable | **fix** the docstring to state the honest limit: the mask is proven by reading the file; this harness boots deterministically and cannot exercise the odd-frame case. Settling it needs a boot-parity instrument (`vendor/mesen_runner.py` binds no console `Reset`), a second emulator, or hardware |
| **F3** | **MEDIUM** | The census counts `feature.toml` **files** while the generated doc asserts *"All N **dirs** under `engine/features/` accounted for"*. A dir with no `feature.toml` is silently uncounted and `make register` reports **OK**. Reproduced (§3.2). **Pre-existing, not introduced by R0** | **fix** — one line: compare `len([p for p in FEATURES_DIR.iterdir() if p.is_dir()])` against `len(census)` and refuse the difference by name. It closes friction note #4's shape and makes the reach line mean what it says |
| **F4** | **LOW** | `docs/97` §5: *"the 17 rails that hand-declared `$09` are byte-identical after their declarations were deleted"*. `brawler` is one of the 17 and is **not** byte-identical (it composes). Same looseness in `docs/94` §3's LANDED block (*"moved zero bytes"*) | **fix** the wording. The **substance is correct** and I proved it: `brawler` with the composition reverted and the hand line deleted rebuilds to `1b72f8d129fd7a3b667a9c4d9c8c7586` |
| **F5** | **LOW** | The `SF_HDR_DEST` override is **never exercised** — no build, no test. `test_destination_byte_is_the_declared_default` asserts only `$01`. If the `.ifndef` were mis-spelled or mis-ordered, nothing would catch it. This is what makes R0-3b PARTIAL | **fix** (cheap): one case that assembles a throwaway image with the override and reads `$7FD9`, mirroring the `$FFD7` plant case beside it. I verified it manually; the tree does not |
| **F6** | **LOW** | `vendor/rom/header.inc:39-41`: *"`.byte <import>` emits a byte-sized fixup … while a bare `.byte <import>` is an assembly-time Range error"* — both halves say `<import>`. The second should be `.byte import`. `docs/97` §2.1 has it right | **fix** — one character |
| **F7** | **LOW** | `docs/97` §5(b): *"Both carry the header correction as well."* `brawler`'s `$7FD7` byte did **not** move (it already declared `$09`); its correction is derivational, not a value change | **fix** or **accept** — a half-sentence |
| **F8** | **LOW** | `docs/97` §4.3 is headed *"Run bare, each on the tip of this work"*, and the `cleanroom` line reports 990 where the tip reports 991. **This is not the note's error** — I traced it: in a **git worktree** `.git` is a regular text file, and `--exclude-dir=.git` excludes only directories, so `grep -rIl` counts it. A clone reports 990, a worktree 991 | **accept**, and optionally note it: the gate's reach count is +1 in a worktree and it does sweep the `.git` pointer file (57 bytes, harmless) |
| **F9** | **LOW** | (a) The §4.1 NTSC-pixel-identity constraint has **no suite case** — it is discharged by `tools/tb_picture_diff.py`, run by hand, against a pre-change reference that no longer exists in the tree. Nothing re-checks it on a later change. (b) `test_rom_header.py`'s `RAILS + EXTRA` omits the 10 variant images and the 2 CPU probes; the note states the probe limit, not the variant one | (a) **defer** with the reason written down — a standing per-rail picture diff needs a stored reference set, which is a design decision, not a fix-up. (b) **accept**: every variant script runs `fix_checksum.py` (verified), so the build-time gate covers them |
| **F10** | **INFO** | `[init] zero` emits a **comment contract**, not code (`allocate.py:1394`). `region_init`'s own `stz` is the only real initialisation, so the placement of `jsr region_init` before any reader is load-bearing and unenforced. `feature.toml` documents this correctly | **accept**. The `SF_HW_POWERON=ones` measurement in §4.1 is the instrument that would catch a violation; it did not fire |
| **F11** | **INFO** | `ES_RGN_PAL`'s only reader in the tree is `tick_scale.asm:92`. No *game* code branches on it yet. R0-1 says "readable by game code", which is satisfied by the emitted symbol | **accept** — R1 is where a second reader arrives |

No finding is HIGH. Nothing in `docs/97` that I could check turned out to be
untrue about the machine; the three MEDIUMs are two statements about tools and
one statement about a test.

---

## 7. What I re-ran, and what I took on trust

**Re-ran, from scratch, on this tip:**

* Full rail build from an empty `build/` (56 images, exit 0).
* The pre-change tree built at `a8fcbc8` in a scratch clone, for every
  before/after comparison below.
* `tools/rate_oracle.py scroller brawler --halves`, both regions, both trees.
  Every figure in `docs/97` §4.1 reproduced to the digit, including the halves
  and the frame periods, and the **before** column (0.83208 / 0.82831 / 0.83208)
  from the pre-change images.
* `tools/tb_picture_diff.py` on **all 37 rails**, pre-change image as reference,
  both regions, frames 120/300/600 — plus `brawler` a second time under its
  oracle drive.
* Every `$FFD7` and `$FFD9` byte in all 56 images, plus a full byte-diff of all
  31 moved images.
* `microzero.sfc` md5.
* The `(file, rule, message)` diff of both `tick_lint` baselines.
* Both planted refusals (`fix_checksum` lying header; `TS_BASE_MAX`).
* `tests/test_region.py` (11 passed), `tests/test_rom_header.py` (85 passed),
  the `microzero` md5 pin in `tests/test_c2_sram_class.py` (3 passed).
* Nine gates (§6 transcript below).
* Six original experiments: the power-on matrix, the 30 s stability run, the
  compare-against-`$13` plant, the `depends` auto-inclusion probe, the
  census-hole plant, and the `brawler` derivation rebuild.

**Taken on trust, and why:**

* **`make bare-check`** — not run here: it is being run against this exact tip
  in parallel. Every gate it contains ran green here individually.
* **The full `pytest tests/`** — not run, for the same reason (`bare-check`
  runs a suite of its own and the two must not overlap). I ran the modules this work
  touches plus the `microzero` pin.
* **`docs/93` / `docs/95` / `docs/96` background measurements** — cited, not
  re-derived. Where `docs/97` restates one of their numbers as a *this-work*
  result (the 0.832 before-column, the frame periods, the 20-of-37 count) I
  re-measured it rather than citing.
* **Anything about real hardware or a second emulator** — nothing here was
  checked outside Mesen2, exactly as `docs/97` §6.5 says.

---

## 8. Gate transcript (bare, this tip)

```
make width-check       width_lint: 0 finding(s) across 226 file(s)                                    exit 0
make time-check        no_wallclock: 0 NEW finding(s) across 248 file(s); 0 grandfathered             exit 0
make tick-check        tick_lint: 0 NEW finding(s) across 705 file(s); 356 held by the baseline       exit 0
make toy-bad           toy-bad OK: allocator refused as designed (VRAM overlap)                       exit 0
make rom-unbacked      rom-unbacked OK: backed arm accepted, unbacked arm refused                     exit 0
make register          register OK: census matches the tree (157 dirs); demand lint reached 18/25     exit 0
make rail-registered   rail-registered OK: 37 rail(s) under game/ present at all 12 sites             exit 0
make measure           check OK: substrate pins agree with fresh measurements                         exit 0
make cleanroom         cleanroom: swept 991 text files, 0 zip(s); 3 hit(s) exempted by 2 allowlist
                       entr(y|ies)
                       cleanroom: clean (name tripwire only — NOT a completeness guarantee)           exit 0
```

`make cleanroom`, bare, as asked: **991 text files swept, 0 zips, 3 hits
exempted by 2 allowlist entries, clean.** The 991-vs-990 delta against
`docs/97` §4.3 is the worktree `.git` pointer file (**F8**), not a tree
difference.

Picture diff, aggregated over 37 rails:

```
NTSC:  IDENTICAL 37 / 37
PAL:   differs on  scroller  ['300']
                   brawler   ['120', '300', '600']
       vacuous on the other 35 rails
       brawler --pad left:  NTSC IDENTICAL,  PAL differs ['120','300','600']
```

Rate oracle, this tip:

```
scroller  cam_x        ntsc 120.198/s   pal 120.101/s   0.99919  PARITY
brawler   knight_tile  ntsc  10.005/s   pal  10.001/s   0.99969  PARITY
brawler   px           ntsc 120.198/s   pal 120.089/s   0.99909  PARITY
frame period  ntsc 357,366 mc (60.0988 fps)   pal 425,566 mc (50.0072 fps)
```

Pre-change tree, same command: 0.83208 / 0.82831 / 0.83208, with the NTSC
column at 120.198 / 10.005 / 120.198 — unmoved.

---

## 9. Ambiguities, and how I resolved them

1. **Which drive does the "37 of 37" picture diff use?** `docs/97` §4.2 does not
   say. I used the tool's default (`--pad right`) for all 37 and re-ran
   `brawler` under the oracle's `left` as well, so the composing rail is covered
   under both. Reversible default, stated.
2. **Is "a build declares the region it targets" satisfied by everything
   declaring `$01`?** Read literally, yes; read against its evident intent, the
   hatch is what matters and it is untested. I marked the clause **PARTIAL** and
   filed the untested hatch as **F5** rather than failing the clause, because
   `docs/97` §6.3 states the position plainly and the byte's default is
   defensible for a cart that detects at runtime.
3. **Is reading `ES_RGN_PAL` out of WRAM a "rendered output" test?** I accepted
   it: the flag is the whole of what `region` produces, so it is the output
   region and not a proxy for one. The framing sentence in §3 is marked ✓ with
   the reasoning written out.
4. **Does the implementer amending `docs/94` count against the audit?** The
   diff to `docs/94` is purely additive — a LANDED block; **no criterion text
   was altered.** Consistent with that file's own stated convention.

---

## 10. What I could not verify

* **`make bare-check` on this tip** — deliberately not re-run here (§7).
* **The full suite** — same reason (§7).
* **The odd-frame `$213F` case.** The harness boots deterministically and binds
  no console reset, so bit 7 is always clear at the read instant. The mask is
  proven by reading the file; the *behaviour under the other parity* is not
  reachable here. A second emulator or hardware would settle it (**F2**).
* **What a flashcart or a PAL console's menu does with `$7FD9 = $01`** — not
  emulated, exactly as `docs/97` §6.5 and `docs/95` §10 item 6 say.
* **The 155-dir incident itself.** I reproduced its *shape* (§3.2) and the
  timeline that produces it without any bug beyond that shape (§3.3), but the
  original tree state is gone and cannot be recovered.

---

## 11. Friction met during this review

* **surprise / MEDIUM — `.PHONY` continuation lines defeat a naive grep.**
  `grep -n '^\.PHONY' Makefile | grep register` returns nothing, because
  `register` is on the continuation line. I briefly believed `make register`
  was not phony (which would have been a real gate hole) before checking the
  full block. Any gate audit that greps `.PHONY` needs to read the whole
  backslash continuation.
* **clunky / LOW — a picture diff over the whole tree needs a pre-change
  build, and nothing packages that.** Verifying §4.1 meant cloning the tree at
  the previous tip and rebuilding all 56 images to get reference ROMs. It is
  43 s of build and ~20 min of diffing, but the *idea* — "the reference is a
  tree that no longer exists" — is the part a future auditor will re-derive
  from scratch. `tb_picture_diff.py`'s `--pad` and md5-beside-the-name are
  exactly right; what is missing is a stored reference set (see **F9a**).
* **easy / LOW — `SF_HW_POWERON=ones` is the sharpest tool in the box for
  initialisation claims and is barely used.** One env var turns "the flag is
  written on both paths" from an argument into a measurement, because an
  unwritten word reads `$FFFF`. Worth reaching for on every `[init] zero`
  claim, not only when someone asks.
* **surprise / LOW — the cleanroom reach count is environment-dependent.**
  990 in a clone, 991 in a worktree, for a reason that has nothing to do with
  the tree's contents (**F8**). A reach number that moves with the checkout
  shape is slightly less useful as a "was this gate disarmed" signal.
