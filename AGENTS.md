# AGENTS.md — SuperForge operating manual

SuperForge is an SNES engine built around a declarative resource allocator.
Games are hand-written WDC 65816 assembly (ca65/ld65 → `.sfc`) running on real
hardware at a hard 60 fps, with ~28–37k CPU cycles per frame to spend.

**`CLAUDE.md` is the rules — the seven non-negotiables. This file is the daily
driver:** what to run, how the allocator changes the way you write code, which
patterns are already established, and which mistakes this project has already
paid for. Read both.

## Arriving solo (a fresh agent's first hour)

The read order, when nobody is briefing you:

1. [`CLAUDE.md`](CLAUDE.md) — the seven rules. Everything else assumes them.
2. **This file's "The one idea"** (next section) — you declare resources and
   the build proves the declaration. It changes what "add a feature" means.
3. [`docs/01_substrate_reference.md`](docs/01_substrate_reference.md) — the
   budget a frame, VBlank and the DMA path actually afford.
4. [`docs/capability_envelope.md`](docs/capability_envelope.md) — what already
   exists, proven game by game. Check it before designing anything new.

Then build something before reading more — `make toy && make microzero` — and
before running the full suite, build every rail first (the `make` block in the
build-and-test section below is the list). **The gates teach:** run
`make rail-registered` or `make toy-bad` and read what they print rather than
memorizing their rules — every refusal names the site, the file or the
collision, and following the printed list is the intended workflow.

Walking a game idea in from zero? [`docs/lessons/`](docs/lessons/) is the
five-step arc — see it run → idea vs envelope → small change → scaffold →
prove the mechanic — and the README's "Try it" section is the same arc as
prompts.

---

## The one idea that changes how you work

**You do not allocate resources. You declare them, and the build proves the
declaration is collision-free.**

The conventional way to write an SNES engine is to claim
WRAM/DP/VRAM/HDMA-channel/VBlank/ROM-bank resources ad hoc and keep them apart
by unwritten "these won't be used together" assumptions. Split-mode rendering,
large-world Mode 7 streaming and variable-width fonts are the three subsystems
that reliably die of the resulting collisions, because each of them needs a
resource somebody else already took without saying so. This repo replaces the
assumption with a declarative allocator that runs *as part of the build*:

- Features declare what they need in `feature.toml`; games in `game.toml` /
  `state.toml`; the machine's real limits live in `allocator/substrate.toml`.
- `allocator/allocate.py` packs the claims and **emits symbols** into
  `build/*.inc` + `build/symbol_map.json`.
- An infeasible declaration **stops the build**. That is the feature, not an
  obstacle — it is a design answer arriving at build time instead of as a
  corruption bug months later.
- `allocator/no_literals.py` then fails the build if engine ASM contains a raw
  address literal. You physically cannot hardcode an address.

Practical consequences, and they are not optional:

- **Never hardcode an address, a channel number, or a register encoding.** Use
  the emitted symbol. HDMA channels come from `ES_H_<CLAIM>_CH`. BG register
  encodings come from emitted `_SC_BASE` / `_NBA` symbols — do not hand-narrate
  a VRAM base into a register value in ASM.
- **Adding state means editing a `.toml`, then rebuilding**, not finding a free
  byte. If the allocator refuses, the design is over budget — fix the design.
- **Every `feature.toml` declares a `role`**, and the build refuses an unknown
  one: `feature` (supplies a demanded capability) · `blob` (ROM data, no
  behaviour) · `companion` (holds claims for shared top-level code) · `consumer`
  (game-side user of an engine feature) · `game_logic` (**not engine** — game
  code that lives under `engine/features/` only because that is where the
  allocator looks) · `fixture` (a toy or probe declaration, never a supplier).
  It exists because the supply census in `docs/09` §3 is generated from the
  tree and this is the one column no claim can distinguish: `car_rom` and
  `col_map_rom` both claim `rom` with no deps and are blobs, while `backdrop`
  claims `cgram` with no deps and is a feature. A new dir also needs a
  `supplies / serves` line in `09` §3.1 — `make register` refuses a census
  entry with no serves entry, and vice versa.
- `make toy-bad` exists to prove the refusal still works. **A build where the
  ALLOCATOR accepts `engine/toy_bad` is a broken build** — so the target checks
  that it refused, and refused on the VRAM collision rather than on some
  unrelated error, and reports that verdict in its exit status: **0 = refused
  correctly**. Run it plainly; do not invert it. (Every gate used to invert it,
  back when it failed on every path — which meant none of them could tell a
  refusal from a toothless allocator.)

---

## Build and test

(`.claude/skills/test-authoring.md` and `inspect.md` carry the operational
test-writing and debugging disciplines; the `.claude/hooks/` lint gate fires
width-check + time-check on edits automatically.)

```bash
bash tools/setup.sh          # once: ca65/ld65, libSDL2, MesenCore.so, Pillow, pytest
make toy                     # the allocator spine: allocator + gates + toy ROM (32,768 B)
make microzero               # the smallest complete game (524,288 B)
make toy-bad                 # the collision gate: passes iff the ALLOCATOR refused
                             # the infeasible decl, on the collision. Not inverted.
make rom-unbacked            # the backing gate: passes iff no_literals refused a
                             # rom claim with no .incbin. Same polarity (docs/37).
make width-check             # width-tracking lint, STRICT, zero findings tolerated
                             # (annotations PRESENT and TRUE against same-file
                             #  arrivals, jsr/jsl included — CLAUDE.md rule 6)
make time-check              # the TIME-COUPLING lint (docs/45): wall-clock waits
                             # in tests/ + tools/. 0.85 s, baseline currently
                             # EMPTY. Override with
                             # `# WALL-CLOCK: ok — <reason>`; a bare stamp is
                             # itself a finding.
make cleanroom               # the name tripwire: no committed file may carry a
                             # retail game / company / brand name except through
                             # an allowlisted entry with a written reason.
make falsify                 # plant defects, require the named tests to go RED,
                             # restore. NOT in `make gates` and NOT in the push
                             # set — it rebuilds ROMs and must not run beside a
                             # suite. `SET=` / `ONLY=` narrow it. docs/46
make determinism             # one MODULE= run twice in fresh processes; every
                             # recorded Machine read and PNG hash must be
                             # BIT-identical, not merely green twice.
                             # FALSIFY=1 runs the planted control. Same footing
                             # as falsify: NOT in `make gates`, and it must not
                             # run beside a suite. docs/53
make measure                 # re-measure the substrate pins and check them against substrate.toml
make rail-registered         # a game/ rail is wired into every one of its
                             # registration sites (the summary line prints the
                             # site count it actually evaluated)
make register                # docs/09's supply census still agrees with the tree
                             # (make register-write regenerates; prose findings
                             #  it reports are hand-fixes, never rewritten)
make test                    # full suite with a TRUE exit code + full log in build/pytest.log
make test XDIST=3            # ...the same target, parallel.
python3 -m pytest tests/ -q  # same suite, direct        (measured 7:40)
python3 -m pytest tests/ -q -n 3   # parallel, pytest-xdist  (measured 3:08 on 4 cores)
                             # PICK -n FROM `nproc`, NOT FROM THIS LINE. The
                             # suite is emulator-bound — one Mesen core per
                             # worker — so oversubscription does not just slow
                             # it, it can stall it: on a 2-core runner
                             # -n 3 ran 4:05 once and then sat past 18 min with
                             # no output. One worker per core is the safe rule.
                             # BUILD FIRST — for the FULL suite that means EVERY
                             # rail, i.e. `make gates`' own rail block plus the
                             # probes:
                             #   make toy microzero room probes breaker shmup \
                             #        platformer split_v_fight m7_dungeon \
                             #        split_h_2p_demo sh2-variants \
                             #        mode7_explore platformer_stream boss \
                             #        boss_saucer \
                             #        meteor_event \
                             #        hud_game scroller camera_follow \
                             #        maze jumper patrol sprite_game stomper \
                             #        scroll_run brawler \
                             #        split_h_matrix_demo \
                             #        split_h_persp3_demo split_v_demo \
                             #        svd-nowin split_v_seamtrial \
                             #        split_h_demo shd-autodemo \
                             #        split_h_persp_demo shp-autodemo \
                             #        racer mode7_chamber railshooter \
                             #        rs-probe m7_oshoot rpg \
                             #        mode7_flight \
                             #        seam_irq_trial sit-origin sit-mistime \
                             #        split_h_irq_grad_demo shg-nograd \
                             #        shg-origin
                             # (svd-nowin: test_split_v_demo's non-vacuity
                             #  control ROM — running the module without it
                             #  is 1 failed, for the same reason as below.
                             #  shd-autodemo / shp-autodemo: the controller-
                             #  free PILOT ROMs. Not controls — the BASE rails
                             #  are this pair's controls — but
                             #  test_autodemo_variants reads all four, so
                             #  without them the module is 4 failed.
                             #  sh2-variants: test_split_h_2p_sprites needs the
                             #  FORWARD/TIEROFF/CULLOFF ROMs — running it alone
                             #  without them is 3 failed, and under xdist two
                             #  workers race the build script)
                             # TWO independent reasons, and the second is the
                             # one that bites. (1) several fixtures shell out to
                             # make, and on a cold tree two workers race the
                             # same build/*.o. (2) EIGHT modules read their
                             # rail's symbol_map.json at MODULE SCOPE, i.e. at
                             # COLLECTION, before any fixture can build it —
                             # test_breaker, test_m7_dungeon, test_mode7_explore,
                             # test_platformer_stream, test_shmup,
                             # test_split_v_fight, test_split_h_2p_{demo,
                             # sprites}, test_c2_slice_c / test_room_window /
                             # test_slice_b_audio. Single-process the guard names
                             # the map and the fix; UNDER XDIST a collection-time
                             # failure presents as a crashed LAST worker holding
                             # an innocent pure-Python test's name
                             # (`AssertionError: ('tests/test_allocator.py::...',
                             # <WorkerController gw3>)`, `no tests ran`) — which
                             # reads like a build race and is not one. A shorter
                             # `make toy microzero room probes` is NOT sufficient
                             # and has cost two whole suite attempts.
                             # Each worker gets its own SF_MESEN_HOME (conftest),
                             # so Screenshots/ and Saves/*.srm do not collide,
                             # and the two modules that plant into the working
                             # tree (test_register, test_make_gates) hold a lock
                             # so their save/restore windows cannot overlap.
                             # -n 4 was faster (2:22) on a 4-core dev box.
make gates                   # the whole gate block in its listed order,
                             # one summary table + both ROM md5s at the end
make bare-check              # THE LANDING GATE. `make gates`, but in a FRESH CLONE
                             # of HEAD — so it sees only committed content and no
                             # stale artifacts. Refuses loudly on a dirty tree.
                             # Writes build/bare_check.json: the SHA, per-gate
                             # verdicts, the suite summary, and the ROM census
                             # — every build/*.sfc, sized against its own
                             # header and md5'd (recorded, not pinned).
                             # ~8.5 min. Runs a suite of its own — do NOT run
                             # `make test` alongside it. docs/44.
make push                    # gated push: register + width-check + toy-bad +
                             # rom-unbacked as prerequisites, then `git push`
```

**Pushing is gated.** `tools/setup.sh` installs `tools/git-hooks/pre-push`
(via `git config core.hooksPath tools/git-hooks` — hooks do not clone with a
repo), which runs the seconds-scale gates `make register`, `make width-check`,
`make toy-bad` and `make rom-unbacked` before any `git push` leaves the machine
and refuses the push naming the gate that failed. `make push` is the documented
front door: it runs the same four gates as prerequisites and then delegates to
`git push`, so it stays gated even on a clone where setup.sh has not run (fails
closed; on a hook-installed clone the set runs twice, costing under a second).
`rom-unbacked` joined the set late — it had shipped covered only by
`make gates` and, indirectly, the ~8-minute `make test`, so the surfaces a human
actually goes through did not run it. The gate set is deliberately seconds-scale
only (no `make test`/`make measure`/ROM builds: a push gate that costs minutes
gets bypassed). **Bypass, when you mean it:** `git push --no-verify` skips the
hook — a guardrail, not a prison; use it for a deliberately-red WIP push and
expect to answer for what you shipped.

Everything runs from the repo root, and **nothing runs automatically**. There is
no push-triggered CI: `make bare-check` is the landing gate, and it is a thing
you run. As of 2026-08-22 there is no hosted workflow in the tree at all —
`.github/workflows/ci.yml` was deleted, manual-dispatch hatch included, so
`make bare-check` is not merely the preferred gate but the only one
([`docs/44`](docs/44_bare_check_migration.md) §6).

**`make bare-check` is the isolation proof.** It clones HEAD into a scratch dir
and runs the gate block there — so the build sees no uncommitted files, no stale
`build/`, and nothing beside it on disk. What it does **NOT** buy, because it
runs on this box: a different machine, an absent toolchain, a different OS image,
full git history. That residue is recorded in the artifact under
`isolation.not_reproduced` and explained in
[`docs/44`](docs/44_bare_check_migration.md).

**A module whose full run costs real time says so on its first docstring
line**, as `runtime: ~N — <what dominates>`, measured rather than guessed, and
naming a warm build tree where that is what the number depends on. The heavy
ones today are `tests/test_rail_registered.py` (~20+ min — 20 cases, each
synthesising a violating tree and running the gate over every rail),
`tests/test_bare_check.py` (~30-42 s — six repo clones), and the two that
shell out to `make` and are therefore cheap warm and minutes cold,
`tests/test_map_freshness_guard.py` (~6 s) and `tests/test_make_gates.py`
(~2-3 s); select a node rather than the module when you want one answer out
of any of them. Two of those four described themselves as costing *minutes*
and were measured in seconds — a runtime claim nobody re-measures is exactly
the kind of number that rots, so the label carries what it was measured
against.

**Never pipe pytest through `tail` without `PIPESTATUS`.** A masked exit code
let a red suite land once. `make test` does it correctly; copy that pattern.

## What each gate actually proves

| gate | proves |
|---|---|
| `make toy` | the allocator emits a usable map and the ROM links |
| `no_literals` (runs inside `make toy` / `microzero` / `room`) | engine ASM references allocated resources only through emitted symbols, **and — the reg-ownership pass — every CPU write to a bank-0 `$21xx`/`$42xx` port is declared by, or covered by, the claim set its file answers to** (docs/09 §2.1's writer-side gate). **On the three UNION tiers "declared" means the owner OPENED it**: a `[[claims.reg]]` carries an optional `scene_writes` (a subset of its own `registers`) meaning *"scene-enter or boot code may write these registers of mine"*, and the tiers narrow **both** arms of the acceptance test to it — `declared` keeps an in-class port only if its claim opens it, `covered` keeps an in-class port an `hdma`/`dma_init` claim covers only if the same feature opens it on a `[[claims.reg]]` **and lists it in `scene_writes`**. Narrowing `declared` alone is not a half-measure but *inert*: `race`'s `$2105`/`$212C` are declared AND covered. Region data/latch ports are not narrowed; the feature-strict tier is unchanged. `scene_writes` is a PERMISSION, not an exclusivity — where the owner writes the register too (`scene_mgr`/NMITIMEN, the tree's one case) `scene_writes_shared` declares it, and a **declaration-that-lies** check refuses an untrue declaration in either direction, per register and span-expanded. The summary line reports how many claims that check VALIDATED, so a zero reads as disarmed rather than clean. Write set = `sta/stx/sty/stz` **plus the RMW family** (`inc a:$2105` sets BGMODE). Tiers, strongest first: feature files → their own `feature.toml`; scene files → the scene's union in `symbol_map.json`; `main.asm` → the globals' union; **anything else → the composed union** (so `engine/toy` and the vendored probes are CHECKED and declare their boot writes — they are not path-exempt). A **latch** ($2115/$2116/$2121/…) rides the claim on the RESOURCE its data port serves; an **unnamed** port is a finding-with-override; an operand that will not fold (`sta a:$2107 - 1` IS MOSAIC) **fails closed**. Override: `; REG-LINT: ok [$port] — <reason>`, **port-scoped** — same-line binds to that write, a standalone one binds only when its window is unambiguous (a write whose port will not fold has no port to name, so only the same-line form reaches it). **That scoping is the reg lint's alone — do not assume symmetry**: `; CHANNEL-LINT: ok` and `; WIDTH-LINT: ok` keep pure ±3-line RADIUS semantics, and the channel form *parses* a `$port` token but ignores it, so writing one there silences the whole window regardless (an accepted divergence). The summary line reports the tier split + per-category site census, so a disarmed pass says so instead of printing "clean" |
| `make toy-bad` | the **allocator** still refuses `engine/toy_bad`, *and* refuses it on the VRAM collision rather than some other error. The target passes (exit 0) when that held |
| `make rom-unbacked` | every `rom` claim in a composition has bytes: some scanned `.asm` holds an `.incbin` whose declaration block ties it to the claim's emitted `ES_R_*` symbol (literally, or through a `.sprintf` template — the only shape a `bank_tiled` claim's chunk symbols can have), **or** the claim declares `backed_by = "<the unit outside the no_literals scope that supplies them>"`, non-empty, enforced in `schemas.py`. The **drift** direction was already asserted hard (`.assert ^label = ES_R_*_BANK`); the **presence** direction was not asked anywhere, and `grad_tabs` once shipped unbacked with every gate green — three HDMA channels streaming the neighbouring blob's bytes, one missing backdrop wash, nothing red. Note that `.assert`s still PASS with the `.incbin` gone (the label lands at the claim's address either way), so ca65 accepts the broken file and only a presence check sees it. Two arms over one allocation: the target passes (exit 0) iff the **backed** control arm was accepted AND the **unbacked** arm was refused naming both missing claims and not the `backed_by`-declared one. Same non-inverted polarity as `toy-bad`, for the same reason. A claim site only credits when it is in the composition's **translation unit** — the `.include` closure of the root `.asm` — because the Makefile's wildcard scans files the game never assembles; the reach is printed (`credited from 19/28 scanned file(s)`). `backed_by` must **cite a repo path that exists**, not just be non-empty. Five stated limits, three of them closed: chunk counts are now derived (`ES_R_*_CHUNKS`; a narrated `.repeat` count is a refusal), a `%s` template is a refusal, a claim site inside an unevaluated `.if`/`.ifdef` does not credit; the bytes are still uninspected and `.include`d files are still not opened (docs/37 §5) |
| `make width-check` | label width annotations are present **and agree with every same-file arrival** — fall-through, branch/jmp, and `jsr`/`jsl` call sites (baseline is zero; a wrong bare annotation is a finding, and the summary line names what was examined). **AND, where the callee DECLARES, the cross-file call sites**: a routine may state its entry contract in the `CONTRACT` grammar (see "The routine contract" below), and a `jsr`/`jsl` from another file is then compared against it, naming both ends (including the `jsr ::name` form ca65 needs inside a `.scope` — about ninety sites here, invisible to the pass until 2026-08-24 and neither checked nor counted as skipped). The pass activates **only** where the callee declares, so an undeclared routine is exactly as unchecked as before and the gate gained no baseline; an UNKNOWN arrival (the caller's own width is untracked at the site) is unprovable rather than wrong and is counted, not fired; and a bare name **several files define** is reported as AMBIGUOUS and left unresolved rather than checked against a declaration it may not link against (this tree's instance was three `cam_arm`s, bought back by renaming sh2_cam's exports to its feature prefix). The summary prints declarations found, widths compared, and both skip counts, so a disarmed pass reads as disarmed. Remaining limit: an UNDECLARED routine's cross-file contract is still proven only on the emulator, and an indirect dispatch through a vector table has no literal target to check; see CLAUDE.md rule 6 |
| `make time-check` | no NEW wall-clock coupling in `tests/` + `tools/`: `time.sleep`, `.run_frames(`, `run_seconds=`, `timeout_s=`, and a read of a FREE-RUNNING core whose only placement in time is one of those (per-function park model). Baseline `reports/time_lint_baseline.json` ships EMPTY — the 56 findings it started from were migrated, not grandfathered. Override is `# WALL-CLOCK: ok — <reason>` within ±3 lines, reason REQUIRED (a bare stamp is its own finding, and does not silence what it sits on). **Stated limits, and the fourth is the one to remember:** the park model is single-FUNCTION, so a fixture that parks and yields is invisible from the test; it does not see through a call; a wrong frame CONSTANT is not a coupling and is not caught; and **it does not know whether a capture lands on an ABSOLUTE frame** — `boot_rom(frames=N)` lands on `>= N` and a module can pass this gate and still be load-sensitive (that is `boot_to_frame`'s job, and neither subsumes the other). `time.monotonic` deadlines and subprocess/thread timeouts are deliberately NOT flagged: they are all legitimate process orchestration here, and a baseline of noise teaches people to ignore the gate. docs/45 |
| `make tick-check` | no NEW site that assumes ONE TICK IS ONE FRAME, against `reports/tick_lint_baseline.json`. Five checks: a `game/*/state.toml` word whose own comment names a frame unit; a `*_tick`/`*_step`/`*_advance` routine; an equate whose name or unit-shaped comment is in frames; a frame-indexed generator constant; the NTSC frame's master-cycle count as a literal or the substrate's `frame.ntsc` table read by name. Override `TICK: ok — <reason>`, reason REQUIRED, bare stamp is its own finding — `width_lint`'s grammar, not a third syntax. **Its BINDING is its own, and deliberately not the ±3-line window the siblings use**: this tree declares its rates in tight runs, so a window reaches over a neighbour and silences a word its reason was never written for — measured on the live tree, eleven sites were being silenced by an override that is not their binder and thirteen reasoned overrides had their own site outside the window. One override binds ONE site, by the shape of the comment it sits in — trailing on a declaration line it binds that line; on an INDENTED comment-only line it binds the declaration whose trailing comment block it continues; at COLUMN 0 it binds the declaration its block heads. A stamp whose anchor carries no finding binds nothing, which is why the prose block-headers that introduce a derivation are inert rather than findings. **A finding is not a defect**: every one of these sites is correct today and the gate bounds the POPULATION, which is why the baseline ships holding 350 and why the gate is **deliberately NOT in `gates` or `bare-check`** until it is driven down. Its `tick-state` check reproduces docs/95 §5.2's 135 across 27 rails to the site; the other classes are supersets by granularity (docs/96 §3.4). **Stated limits:** lexical not semantic (an uncommented countdown is invisible), it cannot tell a rate from an integer, it does not open the call graph, `vendor/` is out, and a clean run says nothing about whether any RATE matches — that is `tools/rate_oracle.py`. docs/96 |
| `make cleanroom` | no committed file carries a retail game, company or hardware-brand name: a case-insensitive pattern set swept over the tracked tree and over the text members of any committed zip, plus a forbidden-filename class (ROMs, music rips, emulator cores, commercially-named media) and a >2 MB tripwire. **Two normalisations, and both were added because the naive form certifies nothing.** (1) The patterns are anchored on "not an alphanumeric" rather than on `\b` — `_` is a word character, so a `\b`-anchored pattern is blind to every title embedded in a snake_case identifier or a filename, which is where names in a source tree actually live. (2) The multiword titles are swept a SECOND time over a **comment-join** view — each line joined with the two after it, comment markers stripped, whitespace collapsed — because a line-oriented grep cannot see a title that a comment reflow broke across a wrap, and in a prose sweep of this tree that is where the majority of one phrase's occurrences were hiding. Any hit not covered by an entry in the allowlist fails the gate. **An allowlist entry carries a required written reason**, on the same convention as `; WIDTH-LINT: ok — <reason>` — legitimate third-party attribution (an upstream author, an upstream project name) is exactly what the allowlist is for, and a bare entry with no reason is itself a finding. Like every other gate here it prints its own reach — how much of the tree it swept and how many hits the allowlist absorbed — so a disarmed pass reads as disarmed rather than as clean. **Stated limit:** a wordlist is a FLOOR and can never be complete; the high-risk artifacts are copied assets and broken attribution, and those are guarded by NOTICE and the per-pack READMEs under `vendor/art/`, not by grep |
| `make rail-registered` | every rail under `game/` is named at **all** of its registration sites — Makefile `.PHONY`, the `gates:` **rail** list, the `gates:` **md5** list (a separate list), `conftest.MAPS`, `conftest._SUBDIR_MAP`, the landing gate's **derived expected-image set**, `test_map_freshness_guard.py`'s reviewed dict (its `covered ==` literal, read via ast), AGENTS.md's own BUILD-FIRST `make` block (a textual prose check), the Makefile `determinism:` prerequisite list, and the Makefile `test:` prerequisite list (so `make test` cannot collect against an unbuilt rail). Four of the sites have each been missed once, and `MAPS`-without-`_SUBDIR_MAP` is **silent and misdirecting**: `_map_of()` keys off the second dict, so the freshness guard checks the TOY map and the module demands `make toy`, which reads as a missing prerequisite rather than an unregistered rail. Derived, not listed: rails are the `game.toml` dirs, a rail's map comes from the Makefile's own `allocate.py` invocation, the two conftest sites are demanded only where some `tests/test_*.py` reads that map at COLLECTION time (parsed, following a module-scope helper call, a path constant, and an `import` of a `tests/` sibling — the shape `test_platformer.py` uses), the freshness-guard site by that guard's OWN scanner (`maps_named_in` — narrower than the above, deliberately, so the gate never orders an edit the guard's equality test refuses), and the determinism site by any Machine-driving module that names the rail anywhere (ROM via `<rail>.sfc` or map constants) plus the rails the determinism gate's own `--falsify` plant hardcodes. Its first run named a live defect: `microzero`, the first rail in the tree, was absent from `.PHONY`. The summary prints the count of site checks that actually RAN (a deleted check drops the count — a disarmed pass reads as disarmed), and each site is proven against a real planted violation in `tests/test_rail_registered.py`. **The count has moved twice, by DECISION both times:** twelve to eleven on 2026-08-22, when site 4 (`.github/workflows/ci.yml`) went out with the retired hosted workflow and every site after it moved down one; **eleven to ten on 2026-08-23**, when the two `bare_check.sh` sites (its size-assert list, its rom_md5 list) collapsed into one as both lists were replaced by derivation. **Retired in 2026-08-22 with the workflow: the ci.yml ROM-step SWEEP,** the one arm that ran per-STEP instead of per-rail and so could see a VARIANT target (`svd-nowin`) built and never measured, which no rail census structurally can. That left eight variant/control ROMs — `svd_nowin`, `shd_autodemo`, `shp_autodemo`, `rs_probe`, `sit_origin`, `sit_mistime`, `shg_nograd`, `shg_origin` — with their size asserted nowhere and their bytes recorded nowhere, plus seven `sh2_*` variants never measured at all. **CLOSED 2026-08-23 by derivation, not by a wider list:** `bare_check.sh` measures every `build/*.sfc` the block leaves behind, sizes each against its OWN `$FFD7` header byte, and demands the set `rail_registered.py --expected-images` derives from the `gates:` run-list plus the variant scripts' own output names — so an image that stops being built goes RED by name instead of leaving the census. Nothing new is pinned. docs/44 §7. **Limit, stated:** it checks the rail is NAMED at each site, not that the site's recipe is correct — site 6 is the one arm that resolves a target to a FILE, and that is still not a claim the recipe works; and a gate cannot detect its own absence from the runner that would have run it, which got weaker with the workflow (there is one runner now, so the asymmetric-half catch is gone — what remains fires only on a surface that still invokes the gate) |
| `pytest tests/` | behaviour on the cycle-accurate emulator, including the vendored CPU probe. **A module may not finish with the shared Mesen core PARKED** — `tests/conftest.py`'s module-boundary guard errors against the module that leaked the park and then resumes the core, so the failure names the culprit instead of the next module's runner dying on a 30 s "frame counter has not advanced" stall |
| `make bare-check` | that everything above holds **on the commit, not on your machine** — the gate block re-run in a fresh `git clone` of HEAD. Two properties, each of which a local `make gates` structurally cannot have: **(1)** the tree contains only COMMITTED content, so a dirty tree is refused by name before anything runs and a file the build needs but HEAD lacks goes red; **(2)** there is no `build/`, so a stale artifact cannot make a target a no-op — a defect that escaped local runs THREE times. Writes `build/bare_check.json` — the SHA, per-gate verdicts, the suite summary, and the ROM CENSUS — every `build/*.sfc` the block left behind, each sized against its own `$FFD7` header byte and md5'd (**recorded, not pinned**), with the derived set it demanded be present — which is what the landing rule asks you to cite. Proven against real violations in `tests/test_bare_check.py`. **Stated limits:** it runs on THIS box, so it buys no different machine, no genuinely absent toolchain (the clone runs its own `setup.sh`, which verifies rather than bootstraps — a ~10-min Mesen rebuild per run would make the gate unusable, and an unusable gate gets skipped) and no different OS image; and the clone inherits this repo's git depth, so a check that needs full history skips where a full checkout would run it. All of that is recorded in the artifact under `isolation.not_reproduced`. docs/44 |
| `make determinism` | the lockstep property, on one module at a time: `MODULE=` is run TWICE in fresh processes and every recorded `Machine` read and every PNG hash must be **BIT-IDENTICAL**, not merely green twice — two runs that agree on the verdict and disagree on a byte are exactly the flake this gate exists to make loud. Polarity is `toy-bad`'s: exit 0 says the property HELD, so a deterministically-RED module with identical manifests passes and the summary says so (a reproducible red is a finding, not a gate failure). `FALSIFY=1` runs the planted sensitivity+liveness control instead, which is what stops a pass meaning "the comparison never ran". Needs the patched lockstep core (`vendor/mesen_patches/apply.sh`, built by `setup.sh` step 3a). **Outside `gates` and `bare-check`, for `falsify`'s reason** — it runs a pytest module of its own, twice, so it must not race a live suite; the target's rail prerequisites exist so the ROM is there when someone runs it, and that list grows with the sweep. docs/53 |
| `make measure` | the substrate pins still match fresh measurements (vblank exact, CPU within 5%) |
| `make register` | docs/09 §3's census matches the tree, **and** a bounded check on the prose that cites it: in `09`, a **table row** that resolves to an existing dir — via its subject cell or its `supplied by` column — may not also say `not built` / `not started` / `unimplemented` / `TODO` / ❌ (and no live row in §5 may resolve to one at all); a `` `engine/features/X` `` citation must name a real dir. **Not** a general check on prose: a claim in a *paragraph* is invisible to it, and so is a row that names no dir in either place (`AUD`, `OBJ-HUD`, `GRAD` — an example list that SHRINKS as features land; `POOL` and `SAVE` have both left it). The target prints its own reach — `demand lint reached N/M demand rows` — so the gap stays visible. See `lint_text`'s KNOWN LIMIT |

`make bare-check` is the landing gate; `make gates` is the same block without
either of the two properties above, and is the right thing to run *while*
working. Neither runs automatically.

`make measure` is the one people skip and shouldn't. The pins are *substrate
facts* other work is budgeted against; drift there invalidates decisions made
downstream, silently.

**A change that moves `build/microzero.sfc`'s bytes carries the pinned-md5
move in the same change** — `docs/94` §4.2's procedure, every live site of the
old value updated by VALUE-enumeration rather than by name-grep, and both
falsification sets re-run so the new pin is known to bind.

**A change that alters feature composition regenerates the register in the
same change.** `docs/09` is generated — `make register-write` writes it and
`make register` checks it — so adding, removing or re-scoping a feature, a
claim, or a rail's `game.toml` list moves the census, and a change that
leaves `docs/09` behind lands with the `register` gate already red for
whoever picks it up next. It is also in the pre-push set, so the first thing
that happens is a refused push, and the tempting move there — `--no-verify` —
does not just skip this gate, it skips the four that would have caught
something real. Regenerate, read the diff (it is small and legible; if it is
not, the composition changed more than you meant), and commit it beside the
change that moved it. Prose findings the target reports are hand-fixes: the
generator writes the census, never the paragraphs around it.

---

## Tooling

| tool | use it for |
|---|---|
| `vendor/mesen_runner.py` | the cycle-accurate emulator harness — read VRAM/OAM/CGRAM/WRAM, inject input, screenshot |
| `allocator/allocate.py` | emit the map; `build/*/allocation_report.txt` shows the live layout |
| `allocator/no_literals.py` | the raw-address-literal gate + the reg-ownership pass |
| `tools/reg_census.py` | what the reg gate RESOLVES and how it VERDICTS, per site — `--compare A B` answers "did this change alter a verdict I didn't intend" |
| `tools/width_lint.py` | width-tracking static analysis (4 checks + an override convention) |
| `tools/no_wallclock.py` | the time-coupling lint (`make time-check`) — 6 checks + the `# WALL-CLOCK: ok — <reason>` override. docs/45 |
| `tools/falsify.py` | the falsification harness (`make falsify`) — patch, require the ARTIFACT MD5 to move, require the named tests RED, restore, require the md5 back. Plant sets live in `tools/plants/`. docs/46 |
| `allocator/pin_budgets.py` | pin/check the measured substrate budgets |
| `tests/mz_drive.py` | drive microzero deterministically (`brake_to_stop`, `coast_to_stop`, …) |
| `tools/shot_microzero.py` | capture a frame for visual inspection |

**A capability graduating to real work gets its register encodings re-derived
from Mesen2 source — not from a summary document, and not from `fullsnes`
alone.** A faithful *transcription* of one source is not the same as a true
statement: `fullsnes`'s window-area encoding line is both self-contradictory and
wrong, and a summary of it here had copied the error exactly — into the
capability it named as the next thing to build. Mesen2's `Core/SNES/SnesPpu.cpp`
is on disk at `/tmp/Mesen2` and settles these in a minute. This is CLAUDE.md
rule 7's second source applied *before* the bug rather than after it, and it
costs a grep. Corollary: where `fullsnes` hedges ("XXX or is it…", a trailing
`?`), carry the hedge into your spec or resolve it against Mesen2 — do not
launder it into a flat statement.

**Debug with the emulator, not by reading source.** When something misbehaves,
read the actual hardware state first — OAM, VRAM, CGRAM, WRAM — then go to the
source with a specific question. Reading ASM to *guess* at a bug is how sessions
burn their context.

**This rule is now a GATE: `make time-check` (docs/45).** It was prose for a
long time, and 56 violating call sites accumulated underneath it, which is
why it is a target and not a paragraph. What follows is the reasoning; the
gate is what enforces it — and read docs/45 §4 for what the gate cannot see,
because a module can pass it and still be load-sensitive.

**Deterministic captures use frame-step, not wall-clock.** `mesen_runner`
exposes `debug_break` / `frame_step` / `debug_resume`, and parked reads are
bit-identical across runs. `run_frames`/`set_input` are wall-clock and are for
interactive verification only — a measurement or capture calibrated against them
drifts with host load. This mattered: the CPU pin measured 12% off between
same-day runs before the measurement paths moved to frame-step.

**And when the picture is the assertion, land on an ABSOLUTE frame.**
`boot_to_frame(rom, N)` free-runs most of the boot and STEPS the last 20
frames, so every host photographs frame N exactly. `boot_rom(frames=N)` is
immune to how FAST the host is but lands on ">= N": measured here, a fixed
free-run budget landed on 90/91/92 under contention against a flat 91 idle,
and those two frames moved the microzero track far enough that a scanline-223
assertion failed 2 runs in 6 under load. The gradient was never wrong; the
frame was a different frame.

**And when you must wait on a free-running machine, wait in EMULATED frames.**
`wait_frames(n)` / `wait_until(pred, max_frames=N)` / `run_to_break(max_frames=)`
/ `boot_rom(rom, frames=)` bound the wait on the PPU's own frame counter, so
host load changes how long a wait takes in seconds and never how many frames it
covers. `run_frames(n)` sleeps n/60 WALL seconds beside a core that advances on
its own thread: it buys ~4x its argument under free-run and **zero** on a parked
runner. That was once claimed to be the whole of the suite's documented flake
class; it was **one of four** timing defects — the others: `run_frames` beside a
parked emulator advancing zero frames, so two tests asserted over nothing and
passed; Mesen's own `_skipRender` wall timer defeating captures whenever the core
is unthrottled; and `run_to_break` reporting breaks no breakpoint produced,
because `IsExecutionStopped()` also covers thread pauses. The "same-tree re-run"
grace that used to cover the class is gone either way — a red on those nodes is
real on first occurrence, and four mechanisms is a better reason for that than
one.

**Hand the core back before your module ends.** The Mesen2 core is a
process-global singleton while `MesenRunner` instances are per-module, so a
module that parks it and finishes without `debug_resume` strands the NEXT
module's brand-new runner — whose `_frame_stepping` is False, so nothing on it
knows to resume — and the red lands on the victim as *"the emulated frame
counter has not advanced for 30.0s … PARKED in frame-stepping mode"*. That
once cost a `make gates` run four reds across two modules the branch never
touched. `tests/conftest.py` now checks the core at every module boundary and
errors against the module that leaked it, then resumes so the rest of the run is
honest. Use `with runner.frame_stepping():` — the resume survives a failed
assertion — or a yield-fixture whose teardown calls `stop()` (which resumes
first).

**The one deliberate exception is audio**, which is a recording of real time
and stays wall-clock (`tests/test_slice_b_audio.py:17-19`, and the
`enable_audio=True` runner in `tests/test_runner_guard.py` for the same
reason). `MesenRunner` keeps those runners throttled to 60 fps so wall and
emulated time coincide by construction.

That claim was over-stated when it was first written: five wall budgets
survived in the three breakpoint SAMPLE HUNTS
(`test_dma_init_forced_blank`, `test_vwf_render`, `test_scene_mgr_shadow`),
one of them gating an `n == SAMPLE_FIRES` equality. All five are now
frame-counted, and `timeout_s=` appears nowhere in `tests/`. **If you add
a `run_to_break`, pass `max_frames=` — reach for `timeout_s=` only for a wait
that is genuinely on wall time, and say so in a comment.**

---

## Test discipline

The full rule is CLAUDE.md #2. What it means in practice here:

- **Assert on the output region the feature produces** — VRAM tilemap bytes, OAM
  bytes, CGRAM words, screenshot pixels — **never a variable that "should"
  reflect them.** A test that passes while the feature is broken is worse than
  no test, because it is trusted.
- **Compare whole declared state against an oracle, every frame**, rather than
  spot-checking the feature's headline value. A per-field check on the headline
  value shipped a real bug here: adding a subroutine call to a branch that held
  a live index in X silently rewrote a sector byte, and the lap counter kept
  counting correctly, so the obvious assertion passed.
- **Drive whole state cycles, not snapshots.** Ascent → apex → landing → rest;
  forward *and* reverse *and* idle. A test that only walks the camera one
  direction locks that direction and ships the other broken.
- **Read the skip count as a defect signal.** Skips report as not-failing. A
  vendored suite arrived here once with seven skip-if-absent cases naming files
  that do not exist in this repo — the integration surface covered zero files
  while the summary read green. `make test` passes `-rs`, so every run prints
  the REASON beside the count; a bare number cannot be read as a signal.

  The skips that remain are environment-gated, and the one category that
  persists is history-gated: `test_register.py::test_drift_fixtures_match_git_history`
  is parametrized over `(ref, file)` pairs that a depth-limited clone does not
  contain, so it skips there and runs after `git fetch --unshallow`. **A literal
  count in prose ages badly against a parametrized test** — the number in this
  paragraph drifted twice before it was replaced with the category. Read the
  reasons `-rs` prints; do not trust a remembered total.

  **`build/bare_check.json` records only the suite SUMMARY LINE, not the skip
  reasons.** So the one artifact the landing rule tells you to cite drops exactly
  the field that makes a skip count readable — and the scratch clone is deleted
  on success, so the reasons are unrecoverable afterwards unless you knew to set
  `BARE_CHECK_KEEP=1` beforehand. `make test` passes `-rs` precisely so they
  print.
- **Streaming's full-window invariant is a STOPPED-camera claim.**
  `assert_window_exact` asserts `vel == 0` deliberately: while the camera moves,
  VRAM trails it by the staging + VBlank-drain lag *by design*. Brake or coast
  to a stop first.

---

## Established patterns (use them, don't reinvent)

- **Scene-scoped feature code** lives inside the scene's `.scope`; shared cold
  code is top-level with hot state in GLOBAL features (`text_dp`, `enter_scr` =
  8-byte enter-time scratch, write-before-read).
- **HDMA channels**: features declare `claims.hdma`; scenes arm the scene_mgr
  128-byte shadow (`ES_SM_HDMA` + `ES_SM_NMI+2` mask) on enter; the NMI MVNs it
  to `$4300` and applies HDMAEN every armed frame. Channel numbers come from
  emitted `ES_H_<CLAIM>_CH` symbols.
- **ROM claims**: the allocator packs largest-first from window 1 (window 0 =
  code). `.incbin` sites carry `.assert ^label = *_BANK && .loword = *_ADDR`, so
  a mismatch **refuses the build** — move the `.segment "BANKn"` to match the
  allocation report.
- **Live HUD cells**: `bg_text` writes VRAM under forced blank only, so a
  *running* scene changes a cell through the one-cell VBlank queue —
  `text_queue_cell` (main thread) + `text_vblank_commit` (called last in
  `sm_nmi_hook`, though its position is free — it programs its own VMAIN/VMADD,
  which is what makes the DMAs ahead of it unable to reach it). Two CPU stores,
  no channel, no VBlank byte budget. `race_logic`'s lap digit is the worked
  example. A multi-cell version should declare `claims.hdma` + `claims.dma` and
  DMA the buffer instead.
- **VBlank VRAM writers program their own VMAIN + VMADD, so hook order is
  free.** Every one in the tree does it (`bg_text`, `mode7_stream` rows + cols,
  `vwf`), which is why `sm_nmi_hook` has no ordering contract to honour —
  measured twice: reordering `vwf_nmi_commit` ahead of `stream_nmi_dispatch`,
  and moving `text_vblank_commit` to run first, each leave the suite green.
  **The rule for a new consumer is "program your own VMAIN/VMADD, or be ordered
  last".** The second clause currently has no instance, and the first is
  load-bearing rather than incidental: deleting `vwf`'s single `sta a:$2116`
  turns 8 of its 10 tests red.
- **Audio: TAD is the occupant; game code asks, it never claims.** The `audio`
  feature (global) holds `spc` + `reg` APUIO + the driver's pinned
  lowram/DP state; `Tad_Init` runs once in MAIN's boot block (NMI off by
  construction), `Tad_Process` once per frame from the MAIN LOOP (never the
  NMI hook — the ABI forbids ISR calls; costs 438 mc ≈ 55 CPU cycles steady
  state, measured). Scenes queue SFX through the `Tad_*` API and claim
  nothing. Room acoustics = an ambience SFX queued at scene ENTER
  (EVOL/EFB against the program-constant EDL — `set_echo_delay` is
  compiler-refused in SFX at the pin); song persistence across scenes = the
  *absence* of `Tad_LoadSong`. Content pipeline: `assets/audio/README.md`
  (procedural samples, checked-in ca65-export, documented regen).
- **The routine contract: an exported routine DECLARES the machine state it
  needs, in fixed slots, and the build checks the declaration.** CLAUDE.md
  rule 6 states the hole openly — annotations are checked against every
  *same-file* arrival, and "callers in other files are invisible in both
  directions... checked only by the emulator". The contract is what closes it:
  the same header a reader was already going to write, in a shape a ~50-line
  parser can read, so `; WIDTH-RISK:` prose becomes a thing the gate can
  enforce rather than a thing a reviewer has to remember.

  The block sits immediately above the label it binds (or above the `.macro`
  directive, for a macro), after the banner and before the prose. Every slot
  is one comment line; a longer answer continues on the lines indented under
  it. This is `mode7_stream`'s, unedited:

  ```asm
  ; --- stream_arm: init contract + tile tracking from the enter camera -------
  ; CONTRACT stream_arm
  ;   entry:    A16 I16 DB=0
  ;   exit:     A16 I16
  ;   in:       CAM0_TX / CAM0_TY — the enter camera's tile position, as
  ;             build-time constants the rail supplies
  ;   out:      the whole hot block zeroed; ST_CAM_* and ST_LAST_* seeded level
  ;             with each other, so the first tick's delta is zero
  ;   clobbers: A, X, N, Z
  ;   assumes:  the scene's own seed upload already covers the whole 128x128
  ;             window around CAM0. Tracking starts in sync with that upload
  ;             and this routine does not verify it
  ;   tail:     rts
  stream_arm:
      .a16
      .i16
      SF_ASSERT_WIDTH 16, 16, "stream_arm"
  ```

  **The slots, and which are required.** `entry:` `exit:` `clobbers:` are
  required; `in:` `out:` `assumes:` `tail:` are optional. `entry:` and `exit:`
  are the MACHINE slots and are parsed — `A8`/`A16`/`A?`, `I8`/`I16`/`I?`, and
  optional `DB=<expr>` / `DP=<expr>` for a routine that depends on them; `exit:
  none` says control does not come back. The rest are prose, read by people
  and checked only for presence, and each has a job the others do not do:
  `in:`/`out:` are DATA (the machine slots are state); `assumes:` is the
  unchecked precondition, the old free-prose "the caller guarantees…", and it
  is where forced blank, a masked NMI, a latched pad or a VBlank window get
  written down; `clobbers:` names registers **and** state — flags, a DP word,
  a hardware register block; `tail:` is where control must go, which is the
  slot a hook or dispatch routine exists to fill.

  **`A?` is a declaration, not an opt-out.** It says *any arrival is legal
  because the routine establishes its own width* — and the lint then requires
  the body to actually narrow that axis before its first width-sensitive
  instruction. Without that, one character would exempt any routine from the
  whole pass.

  **A name several files define cannot be resolved** by a whole-tree run.
  Those calls are reported as ambiguous and left unchecked; a unique name is
  what buys the check, and the retrofit that bought this tree's is written up
  under "A new exported routine carries its feature's prefix" below. Where the
  name is shared *by design* — every rail has an `sm_nmi_hook` — write the
  contract qualified (`; CONTRACT microzero::sm_nmi_hook`): it keys uniquely,
  documents the contract, and does not pretend to a cross-file check it cannot
  have.

  **The machine half is `SF_ASSERT_WIDTH` / `SF_ASSERT_A` / `SF_ASSERT_I`**
  (`vendor/rom/sf_asm.inc`, built on ca65's `.ASIZE`/`.ISIZE`). They emit no
  bytes and no cycles — a ROM that gains one is byte-identical — and they buy
  two different things depending on where they sit. **In a routine**, under
  its entry directives, an assertion pins the CONTRACT to the DIRECTIVES so
  the two cannot drift; the callers are the lint's job. **In a macro** it is
  the caller check, and cross-file for free: a macro body expands *at* the
  call site, so `.asize` inside it is the caller's tracked width in the
  caller's file. Note the adoption order — `sf_asm.inc` is included once per
  ROM from the rail's `main.asm`, so a macro cannot carry an assertion until
  every rail that expands it includes the header. That include is now on all
  37 rails, which is what let `TS_STEP` take its own assertion: its 73
  expansion sites across `engine/features/**` and `game/**` are now each
  checked by the assembler in the expanding file, and a wrong arrival stops
  the build naming the expansion line rather than the macro's definition.

  **Nothing is required.** A file with an old-style prose header is simply
  UNDECLARED — no finding, no baseline, and its callers stay as unchecked as
  they were. That is what let this land on a tree whose width-lint baseline is
  zero. Declare when the routine is exported and the width matters; a
  malformed declaration IS a finding, because a header that reads as a checked
  contract while nothing checks it is worse than no header at all.
- **A new exported routine carries its feature's prefix.** `mode7_stream`'s
  are `stream_*`, `m7f_cam`'s are `m7f_*`, `m7x_logic`'s are `mxl_*`: a short
  tag derived from the feature name, on every label the feature exports. That
  is not house style for its own sake — a unique name is the whole price of
  the cross-file width check, because a bare name two files define is
  AMBIGUOUS to a whole-tree pass and is left unchecked no matter how carefully
  either end declares. Three sibling features named their cameras `cam_arm` /
  `cam_advance` / `cam_tick` and made seven live call sites unresolvable
  between them; sh2_cam's four exports were renamed `sh2_arm` / `sh2_tick` /
  `sh2_advance` / `sh2_region` to break it, which is the retrofit precedent to
  follow. Labels emit no bytes, so a rename of this kind is byte-identical and
  its cost is only the sweep — call sites, contracts, the `.toml` prose that
  names them, the docs and the tools that read them by name.
- **Region-correct rates: declare the rate against the tick, and let the
  timebase carry the region arm.** A new rail composes `region` + `tick_scale`
  in `globals` and expresses each per-frame rate as a BASE fed to
  `TS_STEP <accumulator>, <base>` (`engine/features/tick_scale/tick_scale.asm`),
  which publishes this frame's whole units — today's constant exactly on NTSC
  (the scale is 1, the carried fraction stays 0 forever, so the NTSC picture
  cannot move) and on PAL the same distance per REAL second. Measured band
  across the tree: 0.994–1.027, against the 0.832 an uncompensated rail reads
  (docs/98 §1).
  **The dependency is an auto-include, not a refusal** — read in
  `resolve_features` (`allocator/allocate.py:422`), not inferred from the
  manifest: it walks `depends` depth-first and emits the dependency ahead of
  the feature naming it, raising only on a cycle or an unknown name. So
  `tick_scale`'s `depends = ["region"]` means listing only `tick_scale` in
  `globals` builds the same bytes as listing both. What makes a silent scale
  of 1 unreachable is the other end: with `region` out of the composition
  altogether, `tick_scale.asm`'s read of `ES_RGN_PAL` is an undefined symbol
  and ca65 stops the build.
  **What the consumer declares** is two `u16@dp` per scaled RATE in its own
  `state.toml` — the carried fraction and this frame's published whole-unit
  step. `game/jumper/state.toml` is the worked case and declares two pairs,
  because an arc has two rates. Two consumers on the same base may share a
  pair; on different bases they may not (they cannot share a carried
  fraction). `tick_scale` itself claims nothing.
  **Classify each number by its DIMENSION, not by where it sits** (docs/98
  §2): velocity (px/frame) × r once; acceleration (px/frame²) × r², and since
  `TS_STEP` applies exactly one r the second goes into the BASE on the PAL arm
  — `game/jumper/scenes/sky.asm` is the only place that arithmetic is spelled,
  and it re-asserts the rail's own no-tunnel bound on the SCALED constants
  rather than assuming a tuned number survives a scale; a playhead into a
  baked per-frame table scales the CURSOR and leaves the table byte-identical
  (`brawler`'s animation divider is untouched — what is scaled is how fast the
  clock advances, docs/97 §3.3); an integer countdown or duration stays an
  integer and the consequence is DISCLOSED rather than rounded away (a PAL
  swing window is 20% wider); an event per button press is not a rate at all
  and never scales.
  **Two build-time backstops.** `TS_BASE_MAX` refuses an over-large base with
  a named error instead of letting the build-time PAL scale wrap silently in
  ca65's 32-bit expression arithmetic. And `make tick-check` holds the
  frame-assumption surface at its baseline — a NEW raw frame-rate assumption
  is a finding; the `TICK: ok — <reason>` override is for a site that REMOVES
  a coupling (an accumulator, a scaler's output), not one that expresses one,
  and a bare stamp is itself a finding.
- **Engine routines document their clobbers — read them.** Bracket calls that
  clobber A/X/Y with `phx`/`plx` when you hold a live index.
- **`no_literals` idioms**: decimal and character literals (`#127`, `#' '`) for
  values; hex only for I/O ports — and a port that configures a layer or a
  mode needs a `[[claims.reg]]` (docs/09 §2.1's boundary rule; the
  reg-ownership pass refuses an undeclared one, naming who does own it).
- **Seam line 44** renders backdrop (mode writes land during its HBlank). It is
  asserted, not a bug.
- **Shared 65816 macros live in `vendor/rom/sf_asm.inc`.** That directory is
  first-party (docs/92) and every rail already assembles with `-I vendor/rom`,
  so adopting a macro costs no include path and no Makefile edit; it is in
  `make width-check`'s target set for the reason the lint exists, since a macro
  is written once and assembled into every ROM that expands it. **Include it
  ONCE, at top level, from the rail's `main.asm`** beside `header.inc` and
  `init.inc` — ca65 refuses a second definition of a macro, and an equate
  defined inside a `.scope` is invisible to the scenes that are not in it. A
  feature file USES these macros and never includes the header; a rail whose
  main forgot the include fails to assemble naming the missing macro. Every
  macro there carries a contract comment (entry/exit width, clobbers, what it
  asserts) — write one for anything you add, and a `; WIDTH-RISK:` wherever the
  macro can change a width the assembler cannot track.
- **Placement assertions: the allocator is the authority on where things GO;
  these state where the code NEEDS them.** `SF_ASSERT_DP`,
  `SF_ASSERT_NO_PAGE_CROSS`, `SF_ASSERT_NO_BANK_CROSS` — a routine writes down
  the property of its own placement its addressing modes depend on, and ca65
  checks it on every build instead of a reader checking a header comment. The
  three shapes worth reaching for: a claim reached with `z:` (a FORCED
  direct-page mode — a symbol outside the page assembles fine and addresses the
  wrong byte of page zero); a block a DMA or HDMA channel walks (the A-bus
  address wraps WITHIN A1B, so a straddling buffer transfers the bank's own low
  bytes); an MVN/MVP block, for the same reason. **An assertion you add must be
  TRUE the day you write it** — it codifies, it does not change placement — and
  when one fires the fix is a declaration change, never a weaker assertion.
  Note what does NOT need one: `lda f:base,x` is absolute-long indexed and does
  carry across a bank, so a CPU-side table read has no such requirement.
- **Establish a constant data bank with `SF_SET_DB`, not `lda`/`pha`/`plb`.**
  `pea` pushes a 16-bit immediate whatever the M flag says, so the bank byte
  goes into both halves of one push and is pulled twice: 13 cycles in 5 bytes,
  A survives, and — the part that actually pays — no `sep`/`rep` round trip,
  because the old form only worked in A8. It clobbers N and Z (`plb` sets them)
  and it moves the stack pointer up and back, so it wants a site where the
  stack is writable. It does **not** replace a bank the code COMPUTED: `pea`
  takes a build-time constant, and a chunk bank derived from a row index still
  goes through `pha`/`plb` with the value already in A. `SF_SET_P_DB` is the
  counterpart that establishes the status byte and the bank from one push
  (`pea` / `plp` / `plb`); it is adopted nowhere today because the tree's DB
  setups either need only the bank or sit in the NMI entry and the RESET path,
  where it costs a cycle to save a byte and would newly pin flags those two
  paths inherit. It also leaves an obligation: `plp` sets M and X at RUNTIME
  and ca65 cannot see through it, so the caller writes the matching
  `.a8`/`.a16`/`.i8`/`.i16` after it.
- **Set and clear flag bits with `tsb`/`trb`** where the load/modify/store had
  no reader of the flags after it. The mask then names the bits being CHANGED
  rather than the bits being kept, which is how a hi-table bit-pair or an
  enable mask is actually reasoned about, and it saves ~2 cycles and 2-3 bytes.
  **The caution is the flags: `tsb`/`trb` set Z from A AND memory, not from the
  result** — convert only after reading what follows the site. **And the second
  caution is a gate**: `no_literals`' channel-mask rule (`scan_enables`) matches
  `sta`/`stx`/`sty`/`stz` only, so an RMW write to the HDMAEN shadow
  (`ES_SM_NMI+2`) is INVISIBLE to it — the register-ownership pass does include
  `tsb`/`trb`, the channel-mask rule does not. Converting an arm/disarm site
  there would move a checked site out of a gate's view, so those keep
  `lda`/`ora`/`sta` until the rule's store set grows.
- **Pad a hardware-latency wait to an EXACT cycle count, and annotate it per
  instruction.** The multiplier needs 8 CPU cycles between the `$4203` write
  and a valid `$4216`; where there is no real work to put in the window the
  form is `xba` / `xba` / `nop` — 3 + 3 + 2, the `xba` pair restoring A — which
  is the same 8 cycles in 3 bytes instead of four `nop`s in 4. The densest
  padding this CPU has is a stack pair (`phb`/`plb`, 7 cycles in 2 bytes), and
  7 does not divide 8; there is no one-cycle instruction to finish it. `xba`
  moves N and Z, so check the site first. **Better than either: fill the window
  with work.** `tools/gen_m7f_join.py` COUNTS the cycles between the write and
  the read and refuses to emit an under-filled one, which is the allocator's
  refusal philosophy applied to instruction scheduling.
- **A generated include carries a FORMAT VERSION and its consumer pins it.**
  The allocator emits `SF_INC_FORMAT` into `engine_state_globals.inc` and a
  rail pins it at its own include site (`.assert SF_INC_FORMAT = N`); an asset
  generator whose emitted LAYOUT is load-bearing emits its record shape beside
  the bytes (`tools/gen_m7f_factors.py` → `m7f_factors.inc`) and its consumer
  pins the format plus each constant it would otherwise re-narrate. The version
  is about SHAPE, not values: a re-pack or a retuned curve does not bump it —
  the `_ADDR`/`_BANK` asserts at the claim sites already cover placement drift.
  **What this closes is a check that looks like it holds and does not:**
  `m7f_cam` asserted its narrated strides against the allocator's claim SIZE,
  which is a product — 80 lines of 4 B passes exactly where 160 of 2 B did,
  with every offset the join reads moved. Six rails carry the allocator pin
  today; this establishes the pattern rather than sweeping the tree.

---

## Anti-patterns this project has already paid for

Each of these carries **the condition that makes it true**, and that condition is
load-bearing: an anti-pattern remembered without it fires on the wrong cases. A
rule recorded as "don't import an asset from outside the tree" once talked a
session out of the *right* asset — the real rule was "don't import an asset whose
source format you would have to infer," which permits a documented one. When you
apply one of these, check the condition still holds; when you add one, write it
down.

- **Reading ASM to guess at a bug** instead of dumping hardware state. The
  emulator is ground truth and it is faster. *Condition: this is about what the
  **machine** does at runtime. It is the opposite for our own tooling — when you
  assert what the allocator, a gate, or a converter does, read the code that
  implements it (CLAUDE.md "Two kinds of question").*
- **Asserting what a tool does from something adjacent to it** — a comment, a
  count in a doc, a `feature.toml` note, a licence file shipped beside an asset.
  All are usually right and none is evidence. Three such assertions shipped in
  one session and every one was caught by someone else.
- **Hardcoding an address** because the allocator was inconvenient. The gate
  exists because this is the class of bug that kills compositions silently.
- **Trusting a green test you have not tried to break.** When you add a gate,
  prove it fails on a real violation before believing it. `make falsify`
  (docs/46) is the harness — and note WHAT it adds: it requires the built
  ARTIFACT's md5 to have MOVED before it will believe anything the tests say.
  A plant that never reached the binary is reported as a failure of the
  PLANT, separately from a test that could not see a defect that did reach
  it. *Condition: the two are opposite findings. Three plants once no-op'd
  silently, one of them leaving its test green.*
- **Git-based restores as the undo for a planted-sabotage falsification pass.**
  A `git checkout <file>` that reverts the sabotage restores HEAD — and silently
  discards any uncommitted implementation it was wrapped around. *Condition:
  only safe when the pre-sabotage state is committed. On a dirty tree, snapshot
  by copy and restore by copy, and keep a guard `assert old in src` in the
  sabotage script — it is what turns silent loss into a visible failure.*
- **Committing while `make falsify` runs in the same worktree.** The harness
  owns the tree for its duration: it patches a source in place, builds, runs,
  and restores. A `git add -A` in that window captures the PLANT — and the
  plant is a defect chosen to be invisible, so nothing goes red afterwards.
  Worse, the edit arrives as a *"the file was modified, this change was
  intentional, don't revert it"* notification, which reads as an instruction
  to keep it. *Condition: the whole falsify run, not just the build step. Treat
  any modification notice during a falsify run as the harness. This is the
  MIRROR of the entry above — that one is git clobbering falsify; this one is
  falsify clobbering git.* (Caught twice.)
- **Asserting a spec's mechanism instead of the user-visible invariant.** A spec
  can be wrong; "freeze" means pixels don't move, not "a variable reads zero."
- **Estimating a cycle count.** Measure it.
- **Claiming a gate passed because it probably will.** A gate is not met until
  it is observed.

## When you finish

Report faithfully. If tests failed, say so with the output; if you skipped a
step, say that. Then:

1. State what you built and what you verified, separately — intent and evidence
   are different claims.
2. Name the test surface for anything you added: the feature, the output region
   the test reads, and the state cycles it drives.
