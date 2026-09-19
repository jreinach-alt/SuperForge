# CLAUDE.md — SuperForge

An SNES engine built around a **declarative resource allocator** that proves
feature composition is collision-free at build time. Games are hand-written WDC
65816 assembly (ca65/ld65 → `.sfc`) running on real SNES hardware at a hard
60 fps. **Every cycle matters** (~28–37k cycles/frame).

**Two files, two jobs — read them in this order:**

| file | job |
|---|---|
| **this file** | the **rules** — the seven non-negotiables |
| [`AGENTS.md`](AGENTS.md) | the **operating manual** — what to run, how the allocator changes the way you write code, the established patterns, the anti-patterns already paid for |

Then [`docs/01_substrate_reference.md`](docs/01_substrate_reference.md) — the
hardware budget the allocator solves against.

The single most important thing to internalise before writing any code is in
AGENTS.md: **you do not allocate resources here, you declare them, and the build
proves the declaration.** An infeasible composition stops the build; a raw
address literal stops the build. Both are the point.

## Build & test

```bash
bash tools/setup.sh                    # one-time: ca65/ld65, libSDL2, Mesen2 core, Pillow, pytest
make toy                               # the allocator spine + toy ROM (32,768 B)
make microzero                         # the smallest complete game (524,288 B)
make toy-bad                           # the collision gate: passes iff the ALLOCATOR refused the infeasible decl
python3 -m pytest tests/ -q            # tests drive Mesen2 headless and read hardware
make falsify                           # plant defects; require the ARTIFACT md5 to move,
                                       # the named tests to go RED, and the tree to restore
                                       # exactly. Not in `make gates` — docs/46
make bare-check                        # THE LANDING GATE — clones HEAD and runs the
                                       # gate block in that clone
```

**`make bare-check` is the landing gate.** It clones the repo at HEAD into a
scratch dir so the build sees only committed content and no stale artifacts,
then runs the whole gate block there. Cite its `build/bare_check.json` on the
exact tip. It runs on the same box you are on, so it does not buy a different
machine, an absent toolchain, a different OS image, or full git history — that
residue is recorded in the artifact and in
[`docs/44`](docs/44_bare_check_migration.md).

Gates — keep clean: `make width-check` · `make time-check` (the
TIME-COUPLING lint: no wall-clock waits in `tests/`/`tools/`, override
`# WALL-CLOCK: ok — <reason>`, baseline empty — docs/45; it does NOT know
whether a capture lands on an absolute frame, so read its §4) ·
`make map-check` (the MAP-DERIVATION lint, the fourth sibling — the class
`no_literals` cannot see because it is not in the ROM's source: a `tests/` or
`tools/` Python file that addresses emulator memory with a LITERAL instead of a
value read out of the rail's `symbol_map.json`. It does not corrupt the
console, it corrupts the MEASUREMENT — when the allocator repacks, the literal
keeps pointing where the thing used to be and the module goes RED on a correct
ROM. Measured 2026-09-04: BG2's tilemap moved $3C00 -> $5000 when a tile count
grew and a script holding the old base reported 1,230 wrong pixels in a ROM
whose CHR was byte-identical to the blob that built it. Override
`# MAP: ok — <reason>`, reason REQUIRED; **baseline EMPTY** — the seven it
shipped with were closed rather than carried (four OAM slot bases derived from
the rails' emitted `ES_O_*` placements, three probe addresses resolved from
`vendor/probes/probe_cpu_ref.asm`'s own equates, which is the primary source
for a ROM the allocator never touches), and
`tests/test_map_lint.py::test_the_baseline_is_empty` is the ratchet that keeps
it there: a grandfathered finding is neither derived nor approved. Rule is
deliberately narrow —
only the ADDRESS argument of a `Machine` accessor, and never zero, because a
zero is a hardware region ORIGIN and cannot move; widening it to any four-hex
literal finds 251 lines and teaches people to ignore the gate. Stated limits:
single-expression not dataflow, so an address carried in through a module
constant is invisible; it cannot tell whether a literal is CORRECT; and it
reaches only committed files, so a scratch script — which is what produced the
measured instance — is outside every gate there is) ·
`make tick-check` (the FRAME-ASSUMPTION lint, the third sibling — the class
the allocator cannot see: no NEW site that assumes ONE TICK IS ONE FRAME,
override `TICK: ok — <reason>`, baseline holds 350 — docs/96. A finding is
not a defect, which is why this one is deliberately **not** in `gates` or
`bare-check` until its baseline is driven down) ·
`make toy-bad` (the allocator must refuse; the target itself is **not**
inverted — it exits 0 when it did) ·
`make rom-unbacked` (same polarity: every `rom` claim has an `.incbin` that
actually fills it — docs/37) · `make measure` (the pinned budgets) ·
`make register` (the feature register agrees with the tree;
`make register-write` regenerates it) ·
`make rail-registered` (every rail under `game/` is named at all ten of
its registration sites, derived from the tree rather than listed —
`tools/rail_registered.py`; the summary prints how many site checks actually
ran, so a disarmed pass reads as disarmed. Eleven until 2026-08-23, when the
landing gate's two hand-maintained ROM lists were replaced by derivation and
the two sites that read them collapsed into one — docs/44 §7) ·
`make cleanroom` (the name tripwire: no committed file carries a retail game,
company or hardware-brand name except through an allowlist entry with a
written reason — `tools/cleanroom_check.sh`. A FLOOR, not a guarantee — a
wordlist can never be complete, and the high-risk artifacts are guarded by
NOTICE and the per-pack READMEs under `vendor/art/`, not by grep) ·
`make determinism` (the lockstep property: one module run TWICE in fresh
processes, every recorded `Machine` read and every PNG hash BIT-IDENTICAL —
not merely green twice. `MODULE=` picks it, `FALSIFY=1` runs the planted
sensitivity control, and the polarity is `toy-bad`'s: exit 0 says the
property held, so a reproducibly-RED module with identical manifests passes
and the summary says so. Like `falsify`, it is **outside `gates` and
`bare-check`** — it runs a pytest module of its own, twice, and must not
race a live suite — docs/53) ·
`make bare-check` (all of the above except `tick-check` and `determinism`,
from a clone of HEAD — the landing gate).

## Critical rules (non-negotiable)

1. **Test on the cycle-accurate emulator, never by reading ASM.** Build → `.sfc`
   → Mesen2 headless → read memory → assert, via `MesenRunner`
   (`vendor/mesen_runner.py`). Measure cycle counts; never estimate. Every
   subsystem ships with a test that boots a ROM.
2. **Tests read the rendered OUTPUT** — VRAM/OAM/CGRAM bytes or a screenshot —
   **never a proxy variable.** "Green against a pattern I designed" is not "it
   works." (Indirect-evidence tests are worse than no tests: they pass while the
   feature is silently broken, and whoever ships does so trusting them.)
   **And a test may not be calibrated against the HOST CLOCK.** Wait in
   emulated frames (`wait_frames` / `wait_until` / `frame_step`); when the
   PICTURE is the assertion, land on an absolute frame (`boot_to_frame`).
   `make time-check` enforces this and `# WALL-CLOCK: ok — <reason>` is the
   only way past it — the reason is required, and a bare stamp is itself a
   finding. The audio carve-out is real (a WAV is a recording of real time)
   and is expressed that way, not by exception. docs/45.
3. **Done = a validated render.** Attach a fresh render from the *verified*
   binary to every "it works" claim — render it yourself, don't relay a saved
   screenshot, and don't render from a fresh build when the question is what a
   user pulling this branch actually sees.
4. **No hardware shortcuts.** DMA can't cross bank boundaries; PPU regs are
   VBlank/forced-blank only; re-arm DAS per transfer; respect HDMA/scanline
   timing. Never assume zero-init.
5. **Power-on fidelity.** RAM is random at boot; init WRAM/VRAM/CGRAM under
   forced blank; park OAM offscreen. Never zero-init "to be safe" — it hides
   bugs that bite on real hardware.
6. **Width-tracking is mandatory in 65816** (the recurring silent-corruption
   class): annotate branch targets `.a8`/`.a16`/`.i16`, mark `; WIDTH-RISK:`,
   and keep `make width-check` clean. A missing annotation assembles a stray
   `$00` that the CPU executes as `BRK` — silent, with no assembler warning.
   **This repo's width-lint baseline is zero. Keep it there.**
   **What clean means: annotations are PRESENT and TRUE against every
   same-file arrival** — fall-through, branch/jmp, and `jsr`/`jsl` call
   sites. A bare `.a8` on a label some path reaches in A16 is a finding, not
   a pass: the two plants that once produced a clean gate and a dead ROM
   (`vwf.asm` `@complete`, the col_map probe's `@finish`) now fire, and both
   shapes are regression fixtures (`tests/fixtures/width_lint/`).
   The semantics: a **bare** directive after a label *asserts* the arriving
   width and must equal every known arrival on its axis; **`sep`/`rep` +
   directive** is a *forced narrowing*, legal from any arrival. **The
   single-file limit is now CONDITIONAL** (2026-08-24): an exported routine
   that declares a routine contract (AGENTS.md, "The routine contract") has
   its cross-file `jsr`/`jsl` arrivals checked by the lint's contract pass,
   and a macro's `SF_ASSERT_WIDTH` checks every expansion site at assembly
   time. Everything UNDECLARED keeps the old limit — callers in other files
   invisible in both directions, checked only by the emulator — so
   `; WIDTH-RISK:` markers stay load-bearing on every routine that has not
   yet migrated, and the lint's summary counts how many declarations and
   call sites the pass actually reached. Since 2026-08-25 the declaration
   is MANDATORY on the feature layer: a uniquely-named routine under
   `engine/features/**` that another file calls and that carries no
   contract is a finding (`contract-missing`, ratchet — zero on the tree
   that adopted it, fires on the first new undeclared export; denominator
   printed). The undeclared remainder is the stated exemptions — rail-side
   routines, names several files define, files outside the feature layer.
7. **The emulator is not the bug.** Before claiming a quirk you MUST: reproduce
   on a 2nd emulator (bsnes), read the Mesen2 source
   (`/tmp/Mesen2/Core/SNES/`), cite a known-good open-source SNES codebase or a
   hardware reference that shows the pattern working, and name the exact
   hardware mechanism. Can't do all four → it's your code. Say "I don't
   understand this yet."

**Work style:** debug with the emulator first (read VRAM/OAM/WRAM), not by
reading source. Decompose into ≤50-line ASM / ≤30-line Python steps; never write
>100 lines without building + testing. **Never guess an address** — in this repo
you cannot: every address is emitted by the allocator, and
`allocator/no_literals.py` fails the build on a raw address literal. That gate is
the point of the design; do not work around it.

**Two kinds of question, two different primary sources — do not mix them up.**
*"What does the machine do?"* (a bug, a cycle count, a wrong pixel) → **measure
on the emulator**; reading ASM to reason it out is the slow, wrong path, per rule
1. *"What do our own tools do?"* (does a vblank claim occupy a channel, what does
this claim cost, is this asset what its licence says) → **read the implementing
code.** It is deterministic, it is in this repo, and it is the primary source.
A comment, a doc's count, a `feature.toml` note, or a licence file shipped beside
an asset is **secondary** — usually right, frequently load-bearing, and not
evidence. Three assertions in one session were wrong exactly this way, each
caught by someone else: a claim set contradicted by the `txt_q` comment that had
already reasoned it out; an asset's provenance taken from a licence its own
author wrote; and a channel-exclusivity warning refuted by
`_register_exclusive`'s docstring, written twice without opening the function.
**If you are about to state what a tool does, open the tool.**

## Agent tooling

`.claude/` ships a lint hook (width-check + time-check fire on edit — findings
print, nothing blocks) and two skills: `test-authoring` (the test-discipline
rules operationalised against `Machine`/`boot_to_frame`) and `inspect`
(emulator-first debugging via the emitted symbol map). Read both skills before
writing your first test.

## Pointers

- Hardware budget + constraints the allocator solves against → [`docs/01`](docs/01_substrate_reference.md)
- **What the feature register must prove, and what a new feature must declare** → [`docs/08`](docs/08_feature_register_spec.md)
- **What each feature supplies, what it claims, what is missing** → [`docs/09`](docs/09_feature_register.md)
  (demand↔supply join + the architecture map: where a new feature goes and what it must declare)
- **Font assets** — the one vendored face, what was examined and REJECTED, and
  the still-open proportional/VWF source question → [`docs/11`](docs/11_font_assets.md)
- **The rom-claim backing gate** — what BACKED means, the `backed_by` hatch, the stated limits → [`docs/37`](docs/37_rom_claim_backing_gate.md)
- **The landing gate** — what `make bare-check` proves and what it cannot,
  and **how to read a red**: `fault_reading` in `build/bare_check.json` says
  whether the tree broke or a wall-clock liveness guard in the shared core
  fired, beside `suite_schedule`'s who-ran-next-to-whom. Advisory — the
  verdict is unchanged (§8) → [`docs/44`](docs/44_bare_check_migration.md)
- **The time-coupling gate** — what `make time-check` catches, what it cannot, and `boot_to_frame` → [`docs/45`](docs/45_time_coupling_gate.md)
- **The falsification harness** — why a plant that no-ops used to read as a pass → [`docs/46`](docs/46_falsification_harness.md)
- **The deterministic harness** — the lockstep `Machine`, the two core patches, the determinism gate → [`docs/53`](docs/53_deterministic_harness_settlement.md)
- **Provenance** — what in this tree is not ours, and how that was established → [`docs/92`](docs/92_provenance_audit.md)
- **Region speed** — the rate oracle, the frame-assumption lint (`make tick-check`), and a prototype timebase measured at 0.99919 parity → [`docs/96`](docs/96_region_timebase_tooling.md)
- **Region support** — the region flag, the two header corrections, and the timebase promoted to a composable feature (R0 landed) → [`docs/97`](docs/97_region_r0_landing.md)
- **Region parity across the tree** — **33 of 40** rails compose `region` +
  `tick_scale` and all 33 are measured, at a 0.994–1.027 band; the 7 exempt by
  design, and the deferrals converted by the paths it named → [`docs/98`](docs/98_region_fleet_landing.md)
  (the sweep landed at 30 of 37; the screen-effect rails were measured into it
  on 2026-08-28 — `heathaze` and `lakeside`, then `smelter` at 0.99989, to five
  places the same as `heathaze` because the two share a scaler and a loop
  length)
- **Video-mode composition** — the video/offset vocabulary (`claims.video` /
  `claims.offset`), what MODE 2/4/6 make BG3 mean, the mode-dependent refusal
  set O1–O12 (including the two the capability map named as unclosable: BG3 as
  data, and offset-per-tile outside its three modes), **`direct_color`, which
  retired docs/99's stated limit: CGWSEL b0 is declared with the mode and
  composed by CGWSEL's one owner**, the `ES_VID_*` /
  `ES_OPT_*` emission whose field set is derived from the declaration, the
  tilemap `shape` that completed the `BGnSC` encoding, and the stated limits →
  [`docs/100`](docs/100_video_mode_composition.md).
  Exercised by three rails: `smelter` (mode 2 — four plates and a melt, every
  8-pixel column on its own scroll, for zero HDMA channels), `aurora`
  (**MODE 3, and the first picture in the tree BUILT for direct colour** —
  an end-credits sky drawn from 2048 colours on a palette budget of zero,
  leaving all 256 CGRAM words to BG2 and the sprites. §14 states the trade's
  other half rather than hiding it: there is no palette to CYCLE, so colour
  animation is CHR traffic — 311,296 B of it — and the per-tile palette field
  cannot stand in, being one low bit a channel and moving in 8x8 blocks. It
  also records what `bank_tiled` does NOT protect: a chunk boundary never
  splits a tile, but A1B is constant so it splits TRANSFERS, and the
  uninitialised-read detector found that where a screenshot could not. §14.5
  records a beat BUILT, MEASURED AND REJECTED — shipping the tinted run unlit
  makes the cycle's first pass the aurora ARRIVING, for no ROM at all, and it
  forces a screen-coherent slot order whose assumed cost (a banding seam) was
  measured and is not there. It was dropped anyway, because a coherent front
  is legible as MOTION even where it is not legible as a seam. §14.6 records
  the other half: the loop puts back the ink and NOTHING else, because a loop
  that also restored the colour opened every pass on the same teal and made
  fifteen of the sixteen phases unreachable) and `mill`
  (**mode 4, where BIT 15 OF EACH WORD PICKS THE AXIS** — pistons pumping
  vertically on BG1 beside conveyors running horizontally on BG2, in the same
  32-word row; plus a lift whose car is a BG1 column, whose rider is occluded
  by it for free at OBJ priority 0, and which carries the player between two
  scenes, and a walkable deck whose HOLES ARE WHAT THE MECHANISM COSTS — a
  vertically displaced column cannot carry a horizontal course, so a shaft
  cannot have a floor, and whether the lift's own columns are floor is read
  from the car's live displacement rather than from a tile flag. §13 also
  records the three things the falsification harness found that a look could
  not: an oracle that moved with its own defect, and TWICE a mechanism doing
  no observable work — an occlusion with nothing to occlude, and a dynamic
  collision whose input never varied)
- **Color-math composition** — the screen/blend vocabulary (`claims.screen` / `claims.blend`), the one-blender refusal set R1–R7 and the line between refusing and warning, the `ES_SCR_*` emission (a symbol only for a port the composition OWNS — ownership is per half), the per-scene state and what that means at a transition edge, coexistence with raw claims, and the stated limits → [`docs/99`](docs/99_color_math_composition.md).
  Exercised by two rails: `lakeside` (the blend itself, asserted as an equality)
  and `heathaze` (the same per-scene disarm rule, on an HDMA-driven scroll port
  rather than on the blender)
