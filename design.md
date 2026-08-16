# SuperForge — Design

> What this engine is, why it is shaped this way, and what holds it true.
> `README.md` introduces it; `AGENTS.md` operates it; this document explains
> it. Every claim below is checkable against a file in this tree, cited inline.

## 1. The problem: composition is where SNES engines die

The SNES is a fixed budget of scarce, shared resources: 64 KB of word-addressed
VRAM, 256 direct-page bytes, 128 KB of work RAM, 256 palette words, 128 sprite
slots, eight DMA/HDMA channels, a measured 5,952 usable VBlank-DMA bytes per
frame, 32 KB ROM windows, the audio CPU's 64 KiB, one battery-backed save
window (`docs/01_substrate_reference.md`, `allocator/substrate.toml`). A frame
is 357,368 master clocks; a hard 60 fps leaves ~28–37k CPU cycles to spend.

Practice claims those resources by convention. A tilemap sits at VRAM word
`$6000` because a comment says so. A subsystem takes direct-page bytes
`$A0`–`$AF` because nothing looked like it was using them. HDMA channel 5
belongs to the gradient effect until a second effect wants it. The claims live
in comments, header files and the author's memory, and nothing checks them — so
each feature works alone and the *combination* fails silently: a sprite that
vanishes at one camera position, a subsystem fine until another is switched on.

The failure concentrates where the machine is most interesting: the three
subsystems hardest to land — split-mode rendering, Mode 7 worlds streamed
beyond VRAM, variable-width fonts — are hard *as compositions*. Each needs a
resource somebody else took without writing it down, and the collision is
decided at design time but surfaces at runtime, far from its cause.

## 2. The bet: you declare, and the build proves

SuperForge's structural idea: **resources are never allocated by hand. Features
and games declare what they need, and a build-time allocator packs the
declarations against the machine's measured limits — emitting the complete
address map, or refusing with names.**

Features declare their claims in a `feature.toml` (155 dirs under
`engine/features/`); a game declares its composition — global features,
per-scene features, transition edges — in a `game.toml` and its variables in a
`state.toml` (37 games under `game/`); the machine itself is declared in
`allocator/substrate.toml`, every budget either taken exactly from the hardware
reference or *measured on the cycle-accurate emulator and pinned*, never
estimated.

A claim is a typed, named request against one resource class. A real one — the
red plane of the sky gradient, from
`engine/features/rgb_gradient/feature.toml`:

```toml
[[claims.hdma]]
name = "colr"
registers = ["COLDATA_R"]
mode = 0
indirect = true
band = "scene"
phase = "active"
channels = 1
```

One HDMA channel, driving one sub-register, every visible scanline of active
display — but not *which* channel; the allocator decides that per composition.
It is precise enough that a second claim on `COLDATA_R` in an overlapping band
refuses the build while one on `COLDATA_G` composes: the plane-select bits are
independent silicon, per `REGISTER_FOOTPRINT` in `allocator/schemas.py`.

### The twelve claim classes

The full vocabulary, exactly as `allocator/schemas.py` validates it:

| class | declared as | unit | what it claims |
|---|---|---|---|
| `vram` | `[[claims.vram]]` | words (VMADD) | a `tilemap` / `chr` / `mode7` / `raw` region; per-kind hardware alignment enforced |
| `wram` | `[[claims.wram]]` | bytes | work RAM; a `dma_source` claim may not cross a 64 KB bank |
| `dp` | `[[claims.dp]]` | bytes | direct page — 256 bytes, the scarcest class |
| `cgram` | `[[claims.cgram]]` | words (one color each) | palette groups; `at` pins a sub-palette contract |
| `oam` | `[[claims.oam]]` | sprite slots | of the 128; `at` pins a range, because slot order *is* sprite priority |
| `hdma` | `[[claims.hdma]]` | channels | of the 8: register set + scanline band + phase + DMAP mode |
| `dma` | `[claims.dma]` | bytes + transfers per frame | the VBlank GP-DMA budget this feature spends every frame |
| `dma_init` | `[[claims.dma_init]]` | a channel at scene enter | a one-shot upload fired under forced blank with NMI masked |
| `rom` | `[[claims.rom]]` | bytes | data windows, packed into 32 KB LoROM banks; `bank_tiled` chunking for DMA sources |
| `reg` | `[[claims.reg]]` | register names | a PPU/CPU port the CPU writes directly — scene-wide, phase-blind ownership |
| `spc` | `[[claims.spc]]` | presence | exclusive occupancy of the audio CPU's entire 64 KiB, program-wide |
| `sram` | `[[claims.sram]]` | bytes | battery-backed save bytes at bank `$70`, program-wide |

Two of these carry the model's sharpest judgements:

- **`hdma`'s collision unit is `(register, band, phase, channel)`**, not
  "channel": channels are reusable across disjoint scanline bands and across
  frame phases (VBlank GP-DMA and active-display HDMA are time-disjoint on one
  channel), so the usual "channels 0–1 reserved for VBlank" convention is
  modelled away rather than inherited (`allocator/allocate.py`).
- **`reg` is deliberately phase-blind**: a CPU write is not a queued transfer —
  the NMI preempts the main thread — so two `reg` claims whose footprints
  intersect in one scene conflict, full stop. The one shaped escape, `seed =
  true`, declares a base value a *declared* HDMA claim overwrites per line,
  checked in both directions (`RegClaim` in `allocator/schemas.py`).

### Scenes scope the map; your state is a first-class consumer

Global features are placed once and subtracted from every scene's budget; each
scene packs its own features into what remains, and *different scenes reuse the
same space*. That is why a title screen does not reserve Mode 7's VRAM: in
`game/microzero/game.toml` the `race` scene's `mode7_floor` claims the
interleaved 32 KB region, and `title` and `results` — composing only `bg_text`
and `backdrop` — get it back. Scene transitions are `[[edge]]` declarations
with a byte budget, and the allocator verifies each edge's reload fits it.

The developer's own variables go through the same allocator, declared in
`state.toml` with sizes and scope — `score = "u16"` globally, `vel = "u16@dp"`
hot in a scene, `EnemySlot[8]` a typed array — and come back as emitted symbols
(`US_SCORE`, `US_VEL`) beside the engine's claims
(`game/microzero/state.toml`). No hunting for a free byte; a `results` variable
may occupy a `race` variable's address — the scoping is the proof.

## 3. How a build actually runs

```
feature.toml ×N + game.toml + state.toml + substrate.toml
 → allocator/allocate.py      resolve deps → reserve globals → pack per scene
                              (most-constrained-first) → check edge budgets →
                              independently re-verify → emit
 → build/engine_state_globals.inc + engine_state_<scene>.inc
   + allocation_report.txt + symbol_map.json
 → allocator/no_literals.py   emitted symbols are the only legal addresses
 → ca65 → ld65 → .sfc         `.assert` ties ROM claims to linker placement
 → the gate battery           `make gates`; `make bare-check` to land (§4)
```

Nothing is hand-placed — the emitted include is the only source of addresses.
Verbatim, from `build/engine_state_race.inc` after `make microzero`:

```asm
ES_V_M7 = $0000
ES_V_SKY_MAP = $4400
ES_V_SKY_MAP_SC_BASE = $44
ES_H_COLR_CH = 3    ; COLDATA_R band 0-224 phase active
US_VEL = $7C
```

The Mode 7 region's word base; a tilemap base and the `BGxSC` encoding
*derived* from it; the red plane's assigned channel; a hot user variable. The
derived encodings (`_SC_BASE`, `_NBA`, `_BBAD`, `_DMAP`) keep register
arithmetic out of write sites, where it could silently disagree with the claim.

### Collisions are unexpressible, not merely detected

`allocator/no_literals.py` is the other half of the contract. Only fixed
hardware I/O ports may be literal — silicon, not allocated. Everything else is
refused: address operands into WRAM/DP/ROM, immediates and constant definitions
that name an emitted claim's address, channel *masks* into `$420B`/`$420C` that
do not derive from an emitted `ES_*_CH` symbol, DMAP/BBAD stores that do not
derive from the claim's emitted encoding. Two further passes close what a
literal-scan cannot see: the **reg-ownership pass** refuses a CPU write to a
footprint-named port that no claim in the file's scope declares or opens, and
the **rom-backing pass** refuses a `rom` claim with no `.incbin` tied to its
symbols (a claim reserves bytes; it puts none there) unless it cites, by an
existing path, the out-of-scope unit supplying them
(`docs/37_rom_claim_backing_gate.md`). Every override requires a written reason
— a bare stamp is itself a finding. The consequence is the point: hardcoding an
address, a channel number or a register encoding is not a bug the build
catches; it is a sentence the language cannot say.

### Refusal is a design answer

An infeasible composition stops the build with names, not a stack trace. The
deliberately-colliding manifest in `engine/toy_bad/` (two fixtures pinning the
same VRAM base) produces, verbatim:

```
ALLOCATION FAILED: VRAM overlap in scene 'bad': pin_b_map (engine:pin_b) pinned
at [$1000..$1400) collides with pin_a_map (engine:pin_a) at [$1000..$1400)
```

Over-budget refusals list every contributing claim with its size: what wants
the space, and by how much it does not fit — a design answer you can act on
(move a band, drop a plane, split a scene) instead of a corruption bug weeks
later. `make toy-bad` proves the refusal keeps its teeth: it exits 0 only when
the allocator *refused* that manifest, on the VRAM collision specifically;
`make rom-unbacked` holds the same polarity for the backing gate.

## 4. What holds it true

The allocator proves spatial and budget composition; everything behavioural is
held by a test substrate whose rules are gates, not intentions.

- **Cycle-accurate, in lockstep.** Tests drive a headless Mesen2 core through a
  `Machine` API (`vendor/machine.py`) loaded parked and advancing only by
  synchronous calls — free-run, wall-clock waits and timeouts are *absent from
  the surface*, not policed by lint. Every trajectory is a pure function of
  `(ROM md5, seed, input script)`; power-on RAM is random, seeded per load.
  `make determinism` runs a scope twice and requires every read and screenshot
  bit-identical (`docs/53_deterministic_harness_settlement.md`).
- **Tests read the rendered output** — VRAM, OAM, CGRAM bytes or screenshot
  pixels, never a proxy variable that "should" reflect them: a test that passes
  while the feature is silently broken is worse than no test, because it is
  trusted (`CLAUDE.md` rule 2). **And never the host clock**: waits are counted
  in emulated frames, and when the picture is the assertion the capture lands
  on an absolute frame — `make time-check` enforces it, baseline empty,
  override only with a written reason; audio is the stated carve-out, a WAV
  being a recording of real time (`docs/45_time_coupling_gate.md`).
- **The budgets are pins, and pins are tripwires.** The VBlank budget (5,952
  B/frame), per-transfer arm cost (128 B-equivalents) and worst 60 fps frame
  (305,348 master clocks) are measured in `allocator/substrate.toml`; `make
  measure` re-measures and fails on drift. The allocator budgets *against* the
  pins, so a drifted model fails the build, not the game.
- **Gates print their own reach.** The backing gate reports how many scanned
  files credited; the register gate, how many rows its lint reached; the
  cleanroom sweep, files swept and allowlist hits — a pass that checked nothing
  reads as disarmed, not clean (`AGENTS.md` tabulates each gate).
- **The gates themselves are falsified.** `make falsify` plants a defect per
  guarded behaviour, then requires: the built artifact's md5 to *move* (a plant
  that never reached the binary is a failed plant — the tests are not even
  run), the named tests to go red, the tree to restore byte-exactly.
  Plant-failure and test-failure are opposite findings, never conflated
  (`docs/46_falsification_harness.md`).
- **Landing evidence is an artifact, not a memory** — nothing runs
  automatically. `make bare-check` clones HEAD into a scratch directory —
  refusing a dirty tree by name — and runs the gate block plus the full suite
  there, so the build sees only committed content and no stale artifacts. It
  writes `build/bare_check.json`: SHA, per-gate verdicts, suite summary, ROM
  md5s — and, under `isolation.not_reproduced`, what a same-box clone cannot
  prove (`docs/44_bare_check_migration.md`).

Two disciplines round out the substrate: `make width-check` holds the 65816's
silent-corruption class — a mis-annotated register width assembles a stray byte
the CPU executes as `BRK` — at a zero-finding baseline (`tools/width_lint.py`),
and an emulator-quirk claim carries a four-part burden of proof before it is
anything but your own bug (`CLAUDE.md` rules 6–7).

## 5. The library as the proof

An allocator that refuses bad compositions is only worth something if good
compositions are plentiful, varied and hard. So the bar this engine is held to
is **37 finished games** (`game/`), not a feature checklist: each declares its
composition in a `game.toml`, takes every address from the allocator, builds to
a byte-exact 524,288-byte ROM, and is verified by booting that ROM and reading
what the PPU actually produced. The `Makefile`'s `gates:` block is the working
inventory (`make rail-registered` fails the build if a game is missing from any
registration site), and the library is composition case law:

- `game/boss_saucer` is the reuse proof: it composes `m7_track` — the
  matrix-track player another game declares — with **zero edits to that
  feature**; its manifest names what it composes, what it does not, and why.
- `game/mode7_explore` makes world streaming beyond VRAM, a Mode 7 ⇄ Mode 1
  scene swap and a mosaic transition share one frame, one VRAM and one DMA
  budget with no hand-placed address between them.
- `game/microzero` is the smallest complete loop — title → race → results →
  title — globals surviving the edges, scene bytes reused across them.

They crowd the hardware's hard corners on purpose — perspective and affine Mode
7, streamed worlds, window-clipped dual cameras, scanline IRQs, mid-level mode
swaps, per-scanline HDMA colour, sprite pools, SRAM saves, audio — and make
those share one frame at once, where convention fails and a proof does not.

The join between demand and supply is itself an artifact:
`docs/09_feature_register.md` maps every demanded capability to the feature
supplying it and the claim classes it uses — specified by
`docs/08_feature_register_spec.md`, gated by `make register` against the tree.
Its status vocabulary separates *unclaimed* (a declaration is owed) from
*blocked* (the model lacks the vocabulary), so a composition needing a claim
class that does not exist surfaces as a named row, not as folklore.

## 6. Boundaries

What the engine deliberately does not do, and why each refusal is load-bearing:

- **No allocation at runtime.** The map is fixed at build time; scene edges are
  the only reconfiguration points, and their reload cost is a declared, checked
  budget. There is no heap and no "find a free byte" path — adding state is
  editing a `.toml` and rebuilding.
- **No scripting layer, no generated game code.** Games are hand-written 65816
  against emitted symbols; the declarative surface is the resource model, not a
  language. At ~28–37k cycles per frame, what you write is what runs, and the
  engine refuses to put an interpreter between you and the budget.
- **Mode 7 is one plane on a fixed torus, and the model says so.** The hardware
  draws one affine background from a 128×128 tile map at a fixed base, half of
  VRAM, interleaved (`allocator/substrate.toml`); a `mode7` claim takes the
  whole region or nothing. Larger worlds are *streamed through* the torus
  (`engine/features/mode7_stream/`); a second view is another register track,
  not a plane.
- **The allocator models what it can prove and names what it does not.** The
  per-scanline sprite ceiling — 32 sprites, 34 slivers per line — is
  deliberately unmodelled; where it binds, the arithmetic is done by hand and
  written down (`docs/01_substrate_reference.md` says so). The audio CPU's
  interior belongs to the vendored driver, the ROM size ceiling to the linker
  config — a model of either would be a second source of truth. And symbol
  *reach* is not policed: one feature naming another's emitted symbol
  assembles once both are composed — the binding contracts (`.error`-guarded
  includer symbols, contract blocks, `; WIDTH-RISK:` markers) carry that
  agreement, and the emulator test proves it
  (`docs/capability_envelope.md`, Part 3).
- **SRAM is a save, not RAM.** Program-wide, never scene-reused, and
  structurally excluded from init-zeroing — an initialised save is not a save.
  Raw SRAM is read only through the save feature's integrity gate (magic +
  CRC), because virgin battery RAM is garbage on real hardware.
- **The gates state their own limits** — what the landing gate cannot
  reproduce, what the time gate cannot see, what the backing gate does not
  inspect: `docs/44_bare_check_migration.md` §3,
  `docs/45_time_coupling_gate.md` §4, `docs/37_rom_claim_backing_gate.md` §5.
  Provenance is written down, not assumed (`NOTICE`,
  `docs/92_provenance_audit.md`).

The pattern in every boundary is the same choice, the whole design applied to
itself: a smaller statement that is proved over a larger one that is asserted.
The allocator proves the composition, the games prove the allocator is worth
composing against, and the gates prove the proofs still have teeth.
