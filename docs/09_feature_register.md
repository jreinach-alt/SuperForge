# 09 — Feature Register & Architecture Map

> Status: LIVE — the demand↔supply census `make register` gates, plus the architecture map

**Status:** the artifact. Delivered 2026-07-28 against
[`docs/08_feature_register_spec.md`](08_feature_register_spec.md).

**What this is.** The join between what SuperForge must eventually *support*
(19 rails' worth of demand) and what
it currently *supplies* (20 `engine/features/*` dirs at delivery — the generated
census below tracks the live count; **sixteen** claim classes in
`allocator/schemas.py` — `claims.reg` landed 2026-07-30, `claims.spc` with C1,
`claims.sram` with C2, `claims.screen`/`claims.blend` with C5 — the
composed color-math vocabulary, docs/99 — and `claims.video`/`claims.offset`
with C6, the composed video mode and BG3-as-a-scroll-table, docs/100). Before this file, the
two halves existed and nothing connected them, so "does this demanded feature
need a claim class that doesn't exist?" had no answer you could look up. It has
now been asked twice and answered twice — both times the answer was yes (§2),
and the first of the two answers has since been built.

**What this is not.** Not an API reference — it is about *placement and claims*.
Not a rewrite of the demand catalogue, which stays the demand source of truth.
Not a migration plan.

**Scope of this delivery.** The mapping (§1), the missing-class rows (§2), the
supply census (§3), the architecture map (§4), and the unbuilt-feature needs
(§5). The generator, the `make register` target and the supply-half agreement
test — spec acceptance criterion 5 — were slipped at first delivery per `08` §6
and **closed the following day** (2026-07-28). §3's
census is now generated from the tree and gated; **§1.1/§1.2's claim-classes
column is not**, and the boundary between the two is deliberate — see the note
below and §3's preamble.

**Provenance of the table.** The demand half is hand-maintained from the spec and
the spec — it encodes intent. The supply half was read out of each
`feature.toml` and cross-checked against the feature's `.asm`, which is how §2's
second missing class was found: two features write PPU registers that no
declaration covers, and only reading both halves together shows it.

---

## 1. The register

Status vocabulary, used precisely throughout:

| status | meaning |
|---|---|
| **built** | a feature supplies it, and its claims cover what its code does |
| **PARTIAL** | some of it is supplied; the gap is named in the note |
| **unclaimed** | the code does the thing, but no claim covers the resource. A **declaration to write** — the vocabulary already has the names |
| **blocked** | needs a claim class or register name the allocator does not have. A **name to add**, or a class to design |
| **not built** | nothing supplies it |

**`unclaimed` and `blocked` are deliberately distinct.** Conflating them is how a
cheap task gets scheduled as a hard one: `CGWSEL`/`CGADSUB` are in
`REGISTER_FOOTPRINT` already (`allocator/schemas.py:290-291`), so colour math is
a declaration away once the claim class exists.

> **CORRECTED 2026-08-02 .** This paragraph
> used to end *"`BGnSC`/`BG12NBA`/`BG34NBA`/`CGADD` are genuinely absent and
> need adding first"*, and it was the worked example of the distinction it was
> teaching. Three of those four are **present**: `schemas.py:253-258` carries
> `BG1SC`–`BG4SC`, `BG12NBA`, `BG34NBA` (plus every `BGnHOFS`/`BGnVOFS`, `TM`,
> `TS`). They landed with the `claims.reg` class itself — commit `268093a`,
> *"superforge C4 M1+M2: the reg claim class and its ownership pass"* — and this
> prose was not revisited. Only `CGADD` ($2121) is genuinely absent, and it is
> the CGRAM address port, which `claims.cgram` already expresses. The
> line-number cite above was stale by the same drift. **The lesson is the
> paragraph's own:** a doc that names absent vocabulary goes stale the moment
> the vocabulary lands, and nothing gates it — `make register` checks the
> census block, not this prose.

### 1.1 The spec vocabulary — the fourteen terms

| demand | supplied by | claim classes | missing classes | demanded by (rails) | phase | status |
|---|---|---|---|---|---|---|
| **BG** | `room_bg` (BG1+BG2, Mode 1, shipping); `sky_band` (one layer, one shape) | `vram`×4, `cgram`×2, `dma_init`, `reg` (9 registers + `scene_writes`) | — | `platformer_stream`, `platformer`, `split_v_fight`, `meteor_event`, `rpg`, `mode_showcase`; **+6 of the showcase 8** | 3 | **PARTIAL — but per-rail work, not blocked** (corrected 2026-08-02). A complete two-layer Mode 1 BG feature ships: `room_bg` owns BG1+BG2 with a full `claims.reg`, composed by the `room` game in two scenes (`game/room/game.toml:18,25`). Registers are all in `REGISTER_FOOTPRINT`. What does *not* exist is a **generalised** BG feature — each rail writes its own, following `room_bg`'s 166-line pattern. **The real constraint is F-A, MEASURED:** BG layers cannot be split across features (a level feature owning BG1 + a sky feature owning BG2 is *refused* — `BG12NBA` is one write-only port, one owner per scene). `room_bg` already pays this deliberately. route: **one BG feature per rail owning all its co-resident layers**; H2 is therefore not a gate. **A second instance landed and made it a pattern** (2026-08-02): `breaker_bg` owns BG1+BG2 for the `breaker` rail and adds the two things `room_bg` never had to do — a tilemap **built** at enter from declared geometry rather than uploaded, and one that **mutates on running frames** through a VBlank cell queue. Five BG rails remain; each is per-rail work against this pattern, not new engine work. The stale text this replaced — *"BG2SC/BG12NBA/BG2 scroll are CPU-written with no claim (`sky_band.asm:94-101`)"* — predates both tomls declaring them (`sky_band/feature.toml:42`, `room_bg/feature.toml:89`). |
| **SPR** | `oam_sprites` | `wram` (544 B shadow), `hdma` (vblank), `dma` | — | `racer`, `split_h_2p_demo`, `m7_dungeon`, `m7_oshoot`, `boss_saucer`, `railshooter`, `platformer`, `split_v_fight` | 3 (shipped in 1) | **built** — the engine is the supplier; `player_car` is a game-side consumer of it, not a co-supplier. |
| **TXT** | `bg_text` (deps: `text_dp` companion, `font_rom` blob, `text_chr` CHR-page companion) | `vram` (32×32 map), `cgram` (palette 7). The 96 glyphs are tiles 0..95 of **`text_chr`'s** claim, not `bg_text`'s — see §3 | **CPU-written PPU register** — the scene sets BG3SC/BG34NBA undeclared | `split_h_demo` (TXT/BG3), `platformer` (TXT), `rpg` (dialog); implied by `mode7_chamber`'s Mode-1 HUD band | 2 | **built, fixed-width** — VWF is its own row, not a status here. |
| **VWF** | `vwf` (deps: `text_dp` companion, `text_chr` CHR-page companion, `vwf_rom` blob) | `wram` (240 B canvas, dma source), `dp` (22 B pen/shift), `hdma` (vblank, VMDATAL+VMDATAH mode 1) + `claims.dma` (224 B, 1 transfer). **No `vram` claim of its own** — its destination tiles are a sub-range of `text_chr`'s | — | `platformer`, `rpg` (dialog) | 2 | **built** (2026-07-28). Same output surface as TXT, different renderer: one tile per 8 px of *rendered* text. **The upload question is closed by MEASUREMENT, not argument**: `probe_vblank` cmd 4 + `tools/measure_cpu_store_vblank.py` put the CPU-store ceiling at **324 VRAM words/VBlank = 18.37 byte-equivalents per word**, so a GP-DMA (measured 128 B arm + 2 B/word) is cheaper from **W ≈ 8 words = one 2bpp tile** upward. A glyph straddling a tile boundary dirties two, so VWF is on the far side of `txt_q`'s threshold in its cheapest case (294 B-equiv as CPU stores vs 160 as a DMA) — and `txt_q`'s own 4-word capacity could not hold a tile (8 words) anyway. One declaration covers both reveal models because the dirty span is always contiguous: a typewriter tick and a whole-window clear differ only in DAS. **The channel-contention warning that stood here was wrong**: HDMA occupancy is per-phase (`allocate.channel_free`) and `_register_exclusive` is `active`-only, so a *vblank* claim lands beside an active one — `vwfq` sits on the same channel as `rgb_gradient`'s `COLDATA_G` and race's ACTIVE count stays 7 of 8. See §8. **Validated on bsnes as well as Mesen2 — a second emulator, no visual defects** (CLAUDE.md rule 3 closed, and rule 7's cross-check satisfied in the positive direction: two independent emulators agree, so the rendering is hardware behaviour and not a Mesen2 artifact). |
| **OBJ-HUD** | — | *derived:* `oam` slot range + `cgram` (OBJ palette) on top of `oam_sprites` | — | `racer` (speed bar), `boss_saucer` (HP pips, text cards), `mode_showcase` | 3 | **PARTIAL** — a HUD discipline, not a sprite engine; distinct from SPR: the mechanism exists, and the convention now has its **first shipped instance** (2026-07-30): the `room` game's visit-pip row — an `oam` claim with the new `at = 0` pin (H3's slice) on `room_logic`, tile authored into the hero's existing CHR blob, OBJ palette 0. Exactly the predicted shape: claims + a pin, no new machinery. The generic discipline (a reusable HUD feature, Mode-7-scene HUDs) is still unbuilt. |
| **M7** | `mode7_floor` (dep: `world_rom` blob) | `vram` (`kind = "mode7"`, the interleaved 32 KB), `cgram` (17 words pinned at 0), `rom`×2 | — | `racer`, `mode7_explore`, `split_h_*` family, `m7_dungeon`, `m7_oshoot`, `boss_saucer`, `mode7_flight`, `railshooter`, `mode7_chamber`, `meteor_event`, `rpg` | 2 | **built** — the plane: interleaved region + palette pinned at 0 + CHR. |
| **M7-persp** | `mode7_persp` (dep: `pose_rom` blob) | `hdma`×2 (active, mode 3, indirect — M7A/B + M7C/D), `wram` (32 B index tables), `dp` (8 B origin shadows) | **CPU-written PPU register** — M7X/M7Y are VBlank CPU stores, undeclared (`mode7_persp.asm:139-145`) | `racer` (69%/frame full software rebuild), `split_h_demo`, `split_h_persp_demo`, `split_h_persp3`, `mode7_flight`, `railshooter` | 2 | **built** — PPU-offloaded from ROM pose tables; never a live solve. |
| **M7-affine** | `mode7_floor` (plane only) | plane: as M7 above. Matrix: **nothing** | — (the names M7A–M7D exist) | `m7_dungeon`, `m7_oshoot`, `boss_saucer`, `rpg`, `meteor_event` — **~1%/frame** vs perspective's 69% | 3 | **built** (2026-08-04). `m7_affine` owns the static M7A–D matrix — a build-time 256-entry heading→matrix LUT, a sixteen-byte DP shadow, and an NMI-hook commit that latches all eight ports together; and it holds **no HDMA claim at all**, as the PARTIAL note predicted. `m7_project` supplies the companion half the demanding rails also need: putting a sprite on that plane, through the matrix's transpose. The plane itself is per-rail (`m7dg_floor`; `mode7_floor` for microzero). |
| **SPLIT** | `split_band` | `hdma`×2 (active — BGMODE direct, TM indirect) | — | `split_h_demo`, `split_h_2p_demo`, `split_h_persp_demo`, `split_h_matrix/persp3`, `split_h_irq_grad_demo`, `split_v_fight` (window), `mode7_chamber`, `mode7_flight`, `railshooter` | 2 | **built, later GENERALISED** — sole **active-phase** owner of BGMODE, frame-wide (`band = "scene"`). No longer single-shape: finding B1 (§6) said the answer to a second split shape is *the same claim with different table values*, and the `split_h_demo` port is the second binding that proves it. Five includer-bound symbols, no defaults, each missing one a named `.error` (col_map's shape): `SB_LINES` / `SB_MODE_TOP` / `SB_MODE_BOT` / `SB_TM_TOP` / `SB_TM_BOT`. microzero binds 44 / $09 / $07 / $16 / $11 (BG2 sky + BG3 HUD + OBJ over BG1 + OBJ) and `split_h_demo` binds 40 / $09 / $07 / **$04 / $01** (BG3 alone over BG1 alone). Claim set untouched; microzero's image byte-identical across the change (md5 `e45ddeab…` unmoved). See the phase caveat below. |
| **STREAM** | `mode7_stream` (deps: `world_rom`, `mode7_floor`) | `dp`×2 (22 B hot + 2 B NMI), `wram`×3 (1 KB rows + 1 KB cols + 32 B meta), `hdma` (vblank), `dma` (2048 B/frame, 16 transfers) | — | `mode7_explore` (M7, 2-axis), `platformer_stream` (**normal BG**, 2-axis) | 2 | **built** — `mode7_stream` is the M7 2-axis mechanism; the normal-BG 2-axis demand is met by its sibling `pfs_stream` (proven in `platformer_stream`), a distinct mechanism by design — its header states why it is not a parameterisation of this one. |
| **GRAD** | `rgb_gradient` | `hdma`×3 (active, mode 0, indirect — COLDATA_R/G/B planes), `rom` (672 B) | — | `racer` (CH3/4/7), `split_h_irq_grad_demo`, `platformer_stream` (CH3–CH5), `platformer` | 2 | **built** — **not `sky_band`**, which declares zero `claims.hdma` and whose own toml says "Costs NO HDMA channel". Corrected from the `08` seed. |
| **CM** | `rgb_gradient` (incidental) | none covering it | **CPU-written PPU register** (§2.1) | `racer`, `boss_saucer` (dim), `meteor_event` (glow), `mode7_chamber` (vignette) | 3 | **CLOSED for the gradient case; still open for colour math WITHOUT one.** This row's "unclaimed" reading is stale: §2.1's `claims.reg` class landed, and `rgb_gradient/feature.toml`'s `grad_math` claim now names CGWSEL + CGADSUB, covering the writes at `rgb_gradient.asm:111-129`. So a scene that composes `rgb_gradient` gets CM declared by composition — which is how `breaker` discharged its CM demand without writing anything. **CLOSED for the without-a-gradient case too** (2026-08-25): `claims.blend` is the declaration a rail wanting colour math and no gradient now writes, and `claims.screen` is its companion for the TM/TS designations the blend has to gate against — the composed vocabulary, docs/99. `rgb_gradient`'s `grad_math` claim stays a raw `[[claims.reg]]`, which is why a scene composing it must not also carry a blend claim (R6, docs/99 §7); migrating it is per-rail work, not engine work. |
| **POOL** | `pool` (the mechanism) + the consumer's own `wram` claim; `shmup_obj` holds the folded form | `wram` (160 B — three pools, one region, 16-byte stride per field) + `oam`×4 (pinned slot ranges) | — | `m7_dungeon`, `m7_oshoot` (2×), `boss_saucer`, `railshooter` | 3 | **built** (2026-08-02) — and **the prediction in this row held in both halves, with `allocator/schemas.py` untouched.** A pool is an `alive[]` array plus parallel arrays and a scan; there is no channel, register or VBlank cost for a class to describe. Two notes for a later generaliser: the pools live ON `shmup_obj` because the stable-OAM-slot contract IS the coupling (pool slot k is always OAM slot k), and the routines index ONE claim by compile-time offset, so a shared `actor_pool` would need a 24-bit base in DP. **Later GENERALISED, and both notes came true.** `engine/features/pool/` is that shared feature: one 4-byte DP claim holding a 24-bit base the caller stamps per call, `[dp],y` inside, the consumer keeping the arrays. It was lifted out precisely because the first note's coupling FAILS on `railshooter` — that rail re-derives its obstacle OAM order from depth every frame, so pool slot and OAM slot are deliberately unrelated. `shmup_obj`'s fold is left exactly as it shipped (it is right for that rail, and re-pointing it at `pool` would move a ROM nothing asked to move). |
| **SAVE** | `save` | `sram` (64 B — 2 slots × 32 B), `dp` (17 B args/CRC scratch), `rom` (512 B CRC-16 LUT) | — (the **`sram` class SHIPPED** with it, C2 2026-07-30 —; program-wide packer, both cart header bytes derived from demand) | `rpg`, `platformer`, `mode_showcase` | 3 | **built** (2026-07-30) — magic "SF" + version + length + CRC-16/CCITT gate, verify-before-copy, `$FFFF`/`$FFFE` rejection codes, dest untouched on both, all under allocator symbols. The `room` game ships it: visits survive power-off; title renders the remembered count. |
| **AUD** | `audio` (deps: `tad_rom` blob) | `spc` (whole-space exclusive) + `reg` (`APUIO`) + `wram` (16 B, pinned `$1F00` — the driver's linker-placed `.bss`) + `dp` (2 B, pinned `$F0` — the SFX queue) ; `tad_rom`: `rom` (32 KB whole-window, bank-start by arithmetic) | — | `racer`, `mode7_explore`, `split_h_2p_demo`, `m7_dungeon`, `boss_saucer`, `split_v_fight`, `rpg`, `platformer` | 3 | **built** (2026-07-30) — vendored TAD at `822164b` (`vendor/tad/`), content pipeline documented in `assets/audio/README.md` (procedural samples, checked-in ca65-export). The `room` game ships it: one song persisting across three scenes, per-room reverb (EVOL/EFB against a program-constant EDL — erratum), a footstep under music. Surfaces: `tests/test_slice_b_audio.py` (SPC-RAM boot compare, DSP A→B→A cycle, tick-counter persistence, WAV audibility + aligned rest-tail difference). Settlement unchanged: TAD's compiler packs the interior; SuperForge owns the boundary. |

**The BGMODE phase caveat (finding B1, stated precisely).** `split_band` is the
sole owner of BGMODE *in the active phase* — one exclusive `claims.hdma`,
`band = "scene"`, driving the whole frame, in **both** of its bindings
(microzero's race and `split_h_demo`'s cockpit). It is **not** the only writer:
`title.asm:71`, `results.asm:62`, `race.asm:62` and
`game/split_h_demo/scenes/cockpit.asm`'s enter each set the base BGMODE at
scene enter under forced blank. Those do not collide (disjoint phases) and are
correct, but they are undeclared (§2.1). So: *a second splitter is duplication,
not a new feature* — and the per-scene base mode is a separate, currently
unmodelled thing.

### 1.2 Terms outside the spec vocabulary line

the spec's vocabulary line names fourteen terms, but its *"Features composed"*
column uses more. These rows exist so those demands are visible and so three
built dirs stop reading as unaccounted-for. **Provenance** distinguishes a term
vendored — one this tree already carries an implementation of — from one that
is greenfield here.

| demand | provenance | supplied by | claim classes | missing | demanded by | phase | status |
|---|---|---|---|---|---|---|---|
| **hires text (Mode 5/6)** | **vendored** — a hires text engine exists and is proven | — | *derived:* TXT's surface + a hires BG mode | **BGnSC / BG12NBA / BG34NBA** to place a second tilemap/CHR base at a seam (B2) | **no rail** — the demand catalogue has no term for it at all (finding B3); `mode_showcase` is the only BG-mode harness | 3 | **not built; blocked** — genuinely new territory here, not a port of a rail. The digest under-represents it because rails were mined for *composition*, not BG modes. |
| **col_map** (world-space collision) | vendored — four rails ship it | `col_map` (deps: **none** — the world is bound by the includer, §1.2a) | `dp` (10 B `cm_hot`) + `rom` (256 B flag table, on the blob) | — | `mode7_explore`, `platformer_stream`, `m7_dungeon`, `m7_oshoot` | **2** | **built** (2026-07-28). §5's "no new claim class" prediction **held** — `allocator/schemas.py` is unchanged on the branch. **Decoupled from the streaming ring structurally, not by discipline**: the kernel reads the 256 KB world blob directly by `world_rom`'s bank tiling, so there is no window to fall off and no WRAM mirror to keep in sync — the mirror form has shipped two aliasing bugs. **Cost MEASURED at 951.9 mc/query** (`tools/measure_col_map_cost.py`, K=200..4000, spread 0.30), by a probe that `.include`s the shipped kernel rather than a copy — planting in `col_map.asm` turns the probe-driven test red, so the published figure cannot drift from what ships. That is 0.27% of the frame, 1.8% of the reference workload's headroom, per query. **The function is TOTAL over u16**: the world-size masks after `lsr ×3` make every input name a real tile, so there is no bounds check, no sentinel and no branch — the classic silent-corruption seam is removed rather than guarded, and the torus costs zero extra cycles because the mask was needed to build the index anyway. **Later GENERALISED**: the folded 512s became expressions in `CM_WORLD_W_LOG2`/`_H_LOG2` resolved at ASSEMBLY time, and the blob is now bound by the INCLUDER through six symbols (`rgb_gradient`'s shape, each missing one a named `.error`, no defaults), so `depends` is `[]` and a second rail binds its own world without a second backend. The chunk-bank add is elided by an assembly-time `.if CHUNKS = 1`, never a runtime branch. The deferred torus limit is RESOLVED, and the resolution is that **bounds is not a probe axis** — a bounded world clamps in the GAME before it queries, so the probe stays total by mask and the clamp stays a gameplay rule. VERIFIED byte-identical: `microzero` md5 `e45ddeab…` unmoved, cost still 951.9 mc/query, and all six `.error`s OBSERVED to fire naming their symbol (`tools/falsify_col_map_binding.py`, 6/6). **No `[init] zero`** — write-before-read by construction (docs/09 §4.5's second form), gated by T6 . The per-frame `cm_tick` lives in `race.asm`, not the feature: `ES_M7ORG` is `mode7_persp`'s claim, and three of the four demanding rails have no Mode 7 camera origin. |
| **scene flow** (scene SM, scene-swap, transitions) | vendored | `scene_mgr` | `dp`×2 (4 B ctl + 3 B nmi), `wram`×2 (128 B HDMA shadow + 2 B frame counter) | — | `platformer` (title→game→over→win), `rpg`, `boss_saucer`, `meteor_event`, `mode7_explore`, `mode_showcase` | 1 (shipped) | **built** — the demand catalogue lists scene transitions as an ingredient of the reference racing rail; it is a demanded capability, not just infrastructure. |
| **fades** | vendored | `fade` | `dp` (2 B: level + direction) | — | `platformer` (`sf_bright_fade` idle ~35 cyc), `mode7_explore` (mosaic), `rpg` (mosaic) | 1 (shipped) | **built** — INIDISP ramp; the NMI commits the level. |
| **input (1 pad)** | vendored | `input` | `dp`×3 (cur, prev, press) | — | every rail | 1 (shipped) | **built** — auto-joypad pad 1 with edge detection. |
| **2-controller input** | `input2` | `dp`×3 (cur, prev, press — the JOY2 word at `$421A`) | — | `split_v_fight`, `split_h_2p_demo` | 3 | **built** (2026-07-30) — the cheapest row in the table, delivered as predicted: a second dp triple, no new class, no `reg` claim (reads). A **sibling global feature** rather than three more claims on `input`, because `input` is composed by microzero, whose md5 is the pinned measurement reference — one added claim measurably moves it (see `input2/feature.toml` for the measured evidence + the fold-back path). The `room` game drives its second hero from it. |
| **M7-scale** | vendored | — | *derived:* same surface as M7-affine's matrix (scaling **is** an affine matrix) | — | `mode7_flight` (altitude-driven), `boss_saucer` (scaling boss) | 3 | **not built** — folds into M7-affine's missing static-matrix owner rather than needing its own mechanism. Worth its own row because two rails demand *scaling* specifically. |
| **parallax** | `platformer_bg` (with the BG layers it bands) | `hdma`×1 (mode 2, direct, BG2HOFS) + `wram` 16 B (the table) | — | `platformer` | 3 | **built** (2026-08-02) — and the prediction in this row held: **no new claim class.** A stepped-band table is one `hdma` claim over one `wram` claim, and the shape is the whole design: three HDMA non-repeat-pause entries and a terminator, ten bytes, **532 mc/frame measured** — against ~22,000 mc for the 224-entry per-scanline fill the instinct reaches for. Two notes for a later generaliser: the ratios are powers of two so the rebuild needs no `ALU` claim, and the bands and the foreground camera share ONE DP shadow committed in one place, so they cannot disagree. |
| **palette-cycle** | vendored | — | *derived:* `cgram` + a VBlank write path (`dma` or CPU stores) | — | `racer` | 3 | **not built** — small; the `cgram` class already expresses the destination. |
| **BG→OBJ capture** | vendored | — | *derived:* `vram` + `oam` + a forced-blank transfer | — | `meteor_event` (PLAY→FREEZE→CAPTURE→SCENE→RESTORE) | 4 | **not built** — a transition technique, not a steady-state feature. |

### 1.3 The "one feature → many dirs" shape — no instance in the tree today

Spec §3.1 requires the register to be able to express one demand term supplied by
several dirs, and requires an honest answer about whether anything uses it.

**Nothing does.** Every apparently-multi-dir row resolves to one supplier plus
supporting dirs of a *different* kind:

| looks like | actually |
|---|---|
| GRAD = `rgb_gradient` + `sky_band` | **wrong** — `sky_band` declares zero `claims.hdma`; it is a BG texture layer a gradient happens to colour (the `08` seed's error) |
| TXT = `bg_text` + `text_dp` + `font_rom` | supplier + **global companion** + **ROM blob** |
| M7 = `mode7_floor` + `world_rom` | supplier + blob |
| M7-persp = `mode7_persp` + `pose_rom` | supplier + blob |
| STREAM = `mode7_stream` + `world_rom` | supplier + blob |
| SPR = `oam_sprites` + `player_car` | supplier + **game-side consumer** |

**Update 2026-07-28 — a new category, and the first real instance of shared ownership.** `text_chr` is neither a blob, a companion-for-DP, nor a consumer: it owns a **spatial** resource that two *different suppliers* draw into. It exists because BG3 has one base nibble (BG34NBA) and `chr_align_words = 0x1000`, so two renderers on BG3 physically cannot hold separate `chr` claims — see §5.1. The alternatives were both worse: sizing `bg_text`'s claim for a feature that is not itself (its declaration would grow when `vwf` is in the build, and `vwf` cannot be placed without it), or duplicating the 96 font tiles into a second page — **1,536 B that microzero's `title→race` reload budget refuses outright** (measured: 41,298 vs `budget_bytes = 40000`, refused at *every* window size). The pattern is `text_dp`'s argument applied to VRAM: shared consumers, one owner, on a companion. `vwf.asm` `.assert`s the sub-range boundary against the emitted symbols, so the split is a build-time gate and not prose.

So the tree otherwise factors cleanly: **exactly one supplier per demand term**,
plus blobs, companions and consumers. That is a real and useful property — it
means "who owns this?" has a single answer today — and it is worth re-checking
when it stops being true. The schema must still permit the many-dirs shape;
this row records that nothing exercises it, rather than manufacturing a pair to
satisfy the criterion.

---

## 2. Missing claim classes

Two were ranked here. Both were found by joining demand to supply — neither is
visible from either half alone, which is the argument for the join. **§2.1 has
since SHIPPED as `claims.reg` (2026-07-30); §2.2 remains open.** The section is
kept in full because the boundary rule and the census are the reference for
"is my register write in this class?", and because the reasoning is what the
next class should be argued from.

### 2.1 CPU-written register ownership — **SHIPPED as `claims.reg`**

Nine claim classes existed. Every one described a resource claimed by an HDMA
channel (`hdma`), a DMA transfer (`dma`, `dma_init`), or a memory region
(`vram`/`dp`/`wram`/`cgram`/`oam`/`rom`). **None described a register the CPU
writes directly** — the commonest thing an SNES feature does. A feature that
sets a static register once at scene enter declares nothing, and the contention
checker cannot see it.

#### The class boundary — which CPU register writes are in, which are not

**This paragraph is load-bearing and was missing until 2026-07-28.** Without it
the census could not be checked for completeness, and "is my feature's register
write in this class?" had no answer — which made deferring the class a shrug
rather than a decision. Nine features CPU-write PPU registers; the rule that
separates them is *what the write configures*, not that it happens.

**COVERED by an existing claim — no census row, nothing missing:**

- **A write to the address or increment latch of a data port whose RESOURCE you
 already claim.** `VMADDL/H` + `VMAIN` for a `vram` claim, `CGADD` for a
 `cgram` claim, `OAMADDL/H` for an `oam` claim — and equally for a data port
 you claim *as a port*, by naming it on a `claims.hdma` or `claims.dma_init`
 claim. The claim already says "this resource is mine", and these latches are
 the only way the CPU reaches it: the address write is the *where* of an
 already-declared *what*.

This is why the census below skips `$2115`/`$2116`, `$2121`/`$2122` and
`$2102`/`$2103`. Those omissions were correct; the reason was simply never
written down.

**Why "resource" and not "memory region" — settled 2026-07-30 by the C4
pass, and the wording matters.** The rule used to say "a region you claim",
and then listed `$2102`/`$2103` (OAMADD) as covered on `oam_sprites`. But
`oam_sprites` claims **no `oam` region at all** — its claims are `wram`, `hdma`
and `dma`; the `oam` claims belong to `player_car` and `room_hero`. So the
letter of the rule said not-covered while the text said covered, and the
paragraph could not answer for the one port it named. Three readings were
considered and rejected:

- *"a region claimed anywhere in this composition"* makes coverage **non-local**
 — the same code is covered or not depending on which *other* features a scene
 happens to compose. `oam_sprites` is global; a scene with parked-only sprites
 and no `oam` claim would make its OAMADD write uncovered. A rule an author
 self-checks against has to be answerable from one feature.
- *"give `oam_sprites` an `oam` claim"* contradicts the design. Its own toml:
 "Scenes claim OAM slot ranges (`[[claims.oam]]`) and write their entries into
 the shadow." It is the transport, not the owner, and a whole-table claim would
 collide with every scene's slot claim against the 128-sprite budget.
- *a special-cased "port driver acting on behalf of claimants"* case has no
 general principle and would need re-litigating for the next port.

Generalising *region* → *resource* fixes it locally and mechanically:
`oam_sprites` declares `registers = ["OAMDATA"]`, so its OAMADD write services
a port it holds. The tell that this is the right rule is that it makes the
existing census rows **derivable instead of judgement calls** —
`rgb_gradient`'s `COLDATA` write is covered (it claims `COLDATA_R/G/B`) while
`window_iris`'s identical `COLDATA` write is **not** (it claims only
`WH0`/`WH1`), which is exactly how the census already had them.

It also decides the vocabulary: `VMAIN`, `VMADDL/H`, `OAMADDL/H` and `CGADD` are
covered ports, so **C4 needed none of them** as names. (`CGADD` is still owed for
the separate per-scanline-palette case — that is an HDMA target,
not a CPU write.)

**Counts, measured 2026-07-28 against `engine/features/*/*.asm`** (VWF — the previous parenthetical had never been revisited, and its convention
was never stated):

| ports | features | which |
|---|---|---|
| `$2115`/`$2116` | **6** | `bg_text`, `mode7_floor`, `mode7_stream`, `player_car`, `sky_band`, `vwf` |
| `$2121`/`$2122` | **3** | `mode7_floor`, `player_car`, `sky_band` |
| `$2102`/`$2103` | **1** | `oam_sprites` |

**Re-counted 2026-07-28 after the col_map pass: unchanged at 6 / 3 / 1.**
`col_map` writes no `$21xx` or `$42xx` port at all — its only non-DP accesses
are `lda a:CM_WORLD_WIN,x` and `lda f:col_flags_bin,x` — so it owes no census
row. Recorded because "the number did not move" is itself a checked fact here,
and the paragraph below is about exactly the danger of assuming that.

These count **features**, and that is the ambiguity worth naming: `engine/toy/`
and the game's own scene code write these ports too and are not features. The
old numbers ("six", "four", "one") counted *files including the toy* — so "six"
was right for the five features on `main`, and then became right again for a
different reason when this pass added `vwf`. A number that survives a change
by coincidence is worse than one that is simply stale, because nothing draws
attention to it. **Applied to: VWF's `$2115`/`$2116`
writes are covered by the `VMDATAL`/`VMDATAH` port declaration on its `vwfq`
`claims.hdma` — vwf holds no `vram` claim (its toml states exactly this
coverage) — and need no census
row** — G5's premise that they are undeclarable does not survive the boundary.

**IN the class — a census row is required:**

- **A write that configures a LAYER or a MODE that another feature could also
 want.** BG*n*SC, BG12NBA/BG34NBA, BGMODE, BG*n*HOFS/VOFS, M7SEL, M7X/M7Y,
 CGWSEL, CGADSUB, OBSEL, INIDISP, TM/TS. Nothing scopes these to one owner, and
 two features setting one of them is a silent fight.

The discriminator in one line: **does the write claim a resource, or address one
you already claimed?**

#### The census — eight live instances

(Five through; added three, and the note after the table
explains why the count is the least interesting thing about them.)

All confirmed by reading each ROM against its declaration.

| feature | CPU-writes | what it declares instead | note | opened to scene/boot code (`scene_writes`, item 5) |
|---|---|---|---|---|
| `sky_band` | `$2108` BG2SC, `$210B` BG12NBA, `$210F` BG2HOFS, `$2110` BG2VOFS (`sky_band.asm:94-101`) | only `["VMDATAL","VMDATAH"]` on a `dma_init` claim | the toml asserts the exclusivity in a comment — see below | — its BG writes are the feature's own |
| `rgb_gradient` | `$2130` CGWSEL, `$2131` CGADSUB (`rgb_gradient.asm:111-129`) | the three `COLDATA_*` planes on `hdma` claims | colour-math mode, not the COLDATA data port | — CGWSEL/CGADSUB stay closed; **plant A** proves a scene write to `$2130` now refuses |
| `mode7_persp` | `$210D`/`$210E` as **M7HOFS/M7VOFS**, write-twice (`mode7_persp.asm:147-153`), plus `$211F`/`$2120` M7X/M7Y | `M7A`–`M7D` on two `hdma` claims | **added 2026-07-28.** `$210D` is `BG1HOFS`'s physical port (`schemas.py:216`), so a second feature wanting BG1 scroll in a Mode-1 band contends here with nothing to see it. The toml discloses M7X/M7Y; the HOFS/VOFS pair was uncounted. | — M7A–M7D are `hdma` claims with no reg claim; **plant D** proves `$211B` now refuses through the narrowed `covered` arm |
| `player_car` | `$2101` **OBSEL** (`player_car.asm:68-70`) | `vram`, `cgram`, `oam`, `dma_init` | **added 2026-07-28.** The most dangerous of the three: OBSEL sets sprite size *and* CHR base for **every** sprite, so `oam_sprites` and any second sprite feature share it globally. The *value* comes from an emitted symbol (`ES_V_CAR_CHR_OBSEL_BASE`) — so the address discipline holds and only the ownership is invisible. | — `car_obsel` opens nothing; **plant C** proves `$2101` now refuses |
| `scene_mgr` | `$2100` **INIDISP** (`scene_mgr.asm`'s `sm_nmi_core`) | `dp`, `wram` | **added 2026-07-28,** and the benign one: single writer by design, committing `fade`'s shadow. Worth a row anyway — any feature wanting forced blank mid-scene (a VWF full-row repaint, say) needs to know who owns brightness. | `sm_display` opens **NMITIMEN** only, plus `scene_writes_shared = ["NMITIMEN"]` — the tree's one irreducible co-write. INIDISP stays closed (**plant G**) |
| `window_iris` | `$2125` WOBJSEL, `$2123` W12SEL, `$212E` TMW, `$2130` CGWSEL, `$2131` CGADSUB, `$2132` COLDATA (`window_iris.asm`, `wi_arm`/`wi_disarm`) | `hdma` (WH0+WH1), `wram`, `dp`, and its LUT on `room_rom` | **added 2026-07-29 by**, and the sharpest row in the table: see the note below. | — WH0/WH1 belong to the `iris` hdma claim; **plant H** proves `$2126` now refuses |
| `room_bg` | `$2107` BG1SC, `$2108` BG2SC, `$210B` BG12NBA, `$210D`-`$2110` BG1/BG2 scroll (`room_bg.asm:149-163`); `$2105` BGMODE + `$212C` TM (**`room.asm:95,97`** — the SCENE's enter code, not `room_bg.asm`) | `vram`×4, `cgram`×2, `dma_init` | `sky_band`'s row, one game over — and now with a SECOND layer, so the comment-asserted exclusivity covers two BGs instead of one. **Corrected 2026-07-30:** an earlier revision credited BGMODE/TM to `room_bg.asm`, which writes neither. | `room_layers` opens **BGMODE + TM** only — the two `room.asm` writes. The other seven stay the feature's own, which is why the field is a LIST and the lies-check is per-REGISTER |
| `room_hero` | `$2101` **OBSEL** (`room_hero.asm`, `hero_arm`) | `vram`, `cgram`, `oam`, `dma_init` | `player_car`'s row in a different game. Same mitigation: the value comes from `ES_V_HERO_CHR_OBSEL_BASE`, so only the ownership is invisible. | — `hero_obsel` opens nothing |

** did not add a seventh instance — it added three, and one of them is
the first REAL collision the class describes.** The brief
framed the question as "does this add a seventh row or do we close C4 first",
and the framing undercounted: a window feature needs the selection registers
*and* `CGWSEL`/`CGADSUB`, and those two already belong to `rgb_gradient`'s row.

So `window_iris` and `rgb_gradient` are **two features that want the same two
registers for incompatible purposes**: `rgb_gradient` writes `CGWSEL = $00`
("math always, add the fixed colour") and `window_iris` writes `CGWSEL = $20`
("math outside the window, subtract it"). Every other row in this census is a
feature writing a register *nobody else happens to want* — true today, unwritten,
and the thing the allocator exists to stop being a matter of luck. This is the
first pair where the conflict is real rather than potential. They live in
different games right now, so nothing breaks; nothing would refuse if they did
not.

**Two inputs for C4's design, found while building this and worth not
rediscovering:**

1. **The window and colour-math register file is laid out in exact mode-4 DMA
 spans.** `_parse_mode` accepts `["W12SEL","W34SEL","WOBJSEL","WH0"]`
 (`$2123`-`$2126`), `["TM","TS","TMW","TSW"]` (`$212C`-`$212F`) and
 `["CGWSEL","CGADSUB","COLDATA","SETINI"]` (`$2130`-`$2133`), all at mode 4
 (verified by running it). So a static register write *can* be expressed as a
 `dma_init` claim today, from a 4-byte ROM table.
2. **It would buy visibility, not refusal, and therefore did not do
 it.** `allocate.py`'s only register-contention pass is over `claims.hdma` in
 the `active` phase; `dma_init` claims are recorded and their channel/DMAP/BBAD
 emitted, but never intersected. Verified by experiment: two features each
 declaring `dma_init` on `CGWSEL` in one scene allocate cleanly. Firing a
 GP-DMA we would not otherwise perform, to obtain a symbol, in exchange for
 ownership nothing enforces, is worse than an honest undeclared write — but
 the span property is real and C4 may want it.

Also the same shape, and not features — **corrected 2026-07-30 against a grep of
the tree, having been wrong in both directions:** microzero's `title`, `race` and
`results` each write BGMODE (`$2105`), BG3SC (`$2109`), BG34NBA (`$210C`) **and
TM (`$212C`, which the previous revision omitted entirely though all three write
it — an in-class register, uncounted)**. **M7SEL (`$211A`) is written by
`race.asm` alone**, not by all three. `room.asm` additionally writes BG3HOFS /
BG3VOFS (`$2111`/`$2112`), which appeared in no row.

Where these ended up: scene-enter code has no `feature.toml`, and `[[scene]]`
accepts only `id` + `features` (`schemas.py`'s `load_manifest` passes an empty
optional set), so it cannot hold a claim. Each write is therefore attributed to
**the feature it serves** — BG3's registers to `bg_text`, `M7SEL` to
`mode7_floor`, BGMODE/TM to whichever feature defines the scene's display shape
(`backdrop` for the four BG3-only scenes, `room_bg` for the room, `split_band`
for race as a `seed`). See §2.1's "What C4 does NOT close" below for the residue
this leaves.

**Why this ranks above IRQ.** `sky_band`'s `feature.toml` says:

> *"Register ownership: `$2108` (BG2SC), `$210B` (BG12NBA) and `$210F`/`$2110`
> (BG2 scroll) are written by nothing else in the game — ppu_reset zeroes them at
> boot and no other feature touches them."*

That is a **correct exclusivity fact asserted in a comment** — an unwritten
"these won't be used together" assumption, which is the precise thing this repo
exists to abolish. It is true today, nothing checks it, and the second BG feature
to land breaks it silently. The IRQ gap blocks a rail; this one is
already true in the tree.

This is the same class as `claims.dma_init` — a real hardware write the model had
no vocabulary for, found by cross-checking declaration against implementation —
and a fix would have the same shape. Note the vocabulary is *mostly* already
there: `BG2HOFS`, `BG2VOFS`, `CGWSEL`, `CGADSUB`, `BGMODE`, `M7X`, `M7Y`,
`M7SEL` and `OBSEL` are all in `REGISTER_FOOTPRINT`. `BG2SC` / `BG12NBA` /
`BG34NBA` / `CGADD` are not — that is finding B2, and it is a separate, smaller
problem.

### IMPLEMENTED — `claims.reg`, landed 2026-07-30

The class shipped. `[[claims.reg]]` takes `registers` and an optional `seed`;
`check_reg_ownership` in `allocate.py` enforces it over the global+scene union
and is mirrored in `verify`. Fourteen features declare it (re-counted
2026-07-31 by `grep -l '\[\[claims.reg\]\]'` — the previous "thirteen" went
stale when `audio`'s `apuio_mailbox` landed with; this section's
own lecture on counts applies to it). The three design
questions this section deferred, answered:

**Does a static write want a `phase`? No — and `_register_exclusive` must NOT be
reused.** That function returns True only for `active` because vblank HDMA
claims are *serialised NMI-queue entries*, which its docstring says outright.
That is a property of the queue, not of registers: a CPU writer is **preempted**
by the NMI, not queued. Reusing it would have let a vblank-side ALU user compose
with `race_logic`'s main-thread one — letting the hardware-multiplier defect
through the very class built to catch it. Two further live cases it would have
missed: `mode7_persp` writes M7X/M7Y/HOFS/VOFS **in the NMI hook**, so the
active-phase BG1-scroll rival its own row names as the danger would have
composed; and `scene_mgr` commits INIDISP every NMI, so an enter-time forced-
blank INIDISP write would have composed while being reverted a frame later.
**C4 ownership is scene-scoped and phase-blind.**

**Is `forced_blank`-only sufficient, or must enter-time and VBlank be
distinguished? Neither — that was the wrong axis.** The tree writes in three
contexts (enter/forced-blank, NMI/vblank, main-thread/active) and for conflict
purposes all three behave identically. The real axis is **owner vs seed**: does
the value have to persist, or is it a base another *declared* claim overwrites?
One optional boolean, not a phase enum. It is self-checking — a `seed` with no
intersecting `hdma` claim in scope is a declaration that lies, and the build says
so — and it exempts `hdma` only, never `dma_init` (a one-shot enter-time
establisher is a second owner, not an ongoing overrider).

**Value or ownership only? Ownership only.** `seed` captures the one
value-adjacent fact needed ("someone else overwrites this") without modelling
value compatibility at all. The OBSEL evidence also still holds: `player_car`
and `room_hero` both take the value from an emitted symbol.

Two vocabulary consequences worth knowing before adding a name:

- **The ALU is ONE name** at `($4202, WHOLE)`, covering `$4202`-`$4206` +
 `$4214`-`$4217`. Mesen2's `AluMulDiv.cpp` holds a single `_state` that the
 multiply and divide entry points mutually destroy (`:94` starting a multiply
 clobbers `DivResult`, which is what RDDIV reads; `:106` starting a divide
 clobbers `MultOrRemainderResult`, which is what RDMPY reads), and `:83` drops a
 write made during an in-flight operation *silently*. `(port, mask)` cannot
 express cross-**port** aliasing — `_register_conflicts` only fires on equal
 ports — so separate `WRMPYA`/`WRDIVL` names would have composed while
 physically fighting. This is the `COLDATA` sub-register hole inverted.
- **`$42xx` names are legal on `claims.reg` only**, enforced by a B-bus guard on
 the transfer paths. BBAD is only a port's low byte, widened by hardware to
 `$2100|BBAD`, so a CPU-bus name on an `hdma`/`dma_init` claim does not fail —
 it silently retargets a real, different register (`$4202`→`$2102` OAMADDL,
 `$4216`→`$2116` VMADDH).
- **A sub-register partition is legitimate only if it is expressible in a SINGLE
 BLIND WRITE.** `COLDATA` qualifies (the plane-select bits are in the data).
 `TM`/`TS`/`TMW`/`TSW`/`CGADSUB`/`NMITIMEN` do **not**, however layer-shaped
 their bits look: they are write-only (verified in Mesen2 — `$212C` appears only
 in `SnesPpu::Write`, `$4200` only in the `InternalRegisters` write path), so
 read-modify-write is impossible and every writer must supply the whole byte. A
 per-layer `TM_BG3` would be a mask that lies.

### What C4 does NOT close — two named holes

**1. ~~C4 is the first claim class with no writer-side gate.~~ CLOSED
2026-07-31 — the reg-ownership pass in `allocator/no_literals.py`.** The hole
as it stood: C4 declared ownership but could not prevent an *undeclared*
write — `no_literals` permits any `$21xx`/`$42xx` store by design, so a
feature that simply did not declare stayed as invisible as the census rows
once were. Region classes never had this gap (their emitted symbol is the
only way to address them), so the asymmetry was real and specific to
registers.

The mechanism that closed it, in the same build invocation as the literal
gate: a `sta`/`stx`/`sty`/`stz` whose destination resolves to a bank-0 port
carrying a `REGISTER_FOOTPRINT` name must be declared by, or covered by, the
claim set its file answers to. `engine/features/<name>/*.asm` answers to its
own `feature.toml` (directory-keyed — the audio feature's asm is
`tad_wrapper.asm` — and reloaded through `schemas.load_feature`, because the
build scans both games' feature files against either game's map);
`game/<g>/scenes/<s>.asm` answers to the scene's union in `symbol_map.json`
(the input the emission comment prepared); `game/<g>/main.asm` answers to
the globals' union via `game.toml`. Covered without a `[[claims.reg]]`: the
data port of a region class the claim set holds (vram → VMDATAL/H, cgram →
CGDATA, oam → OAMDATA) and any port named on its `hdma`/`dma_init` claims —
this section's own boundary rule, enforced instead of prose. The ALU and
APUIO resource spans make every port of those resources answer to their one
name (`sta $4203` is checked against the ALU claim). The refusal names the
file, the port, the footprint name, and who does own it — or "declared by
nobody — add a `[[claims.reg]]`".

**Strengthened 2026-08-01 by a cross-comparison pass** (this gate was built
twice, independently; the two final gates were cross-fired and the stronger
halves merged). What changed, and each item's measured effect:

- **The write set is no longer four stores.** `inc`/`dec`/`asl`/`lsr`/`rol`/
 `ror`/`trb`/`tsb` write ports too — `inc a:$2105` sets BGMODE. (`mvn`/`mvp`
 cannot be in the set: both take bank bytes, never an address.)
- **~~Ports with no footprint name are exempt by scope~~ — no longer true, and
 this was the largest hole.** Latches (VMAIN, VMADD*, CGADD, OAMADD*,
 WMADD*) now ride the claim on the RESOURCE their data port serves: `sta
 $2116` is legal under a `vram` claim or with VMDATAL/H named on any claim,
 and a finding otherwise. Exemption-by-scope reached the right verdict *by
 the footprint table happening not to name them*, not by a rule, and it left
 **48 of the live tree's 158 non-channel io write sites unchecked (30%)**.
 Closed at a cost of **zero new declarations** — measured with
 `tools/reg_census.py`, 110 → 158 checked on microzero.
- **A port with no footprint name at all is a finding-with-override** ("silence is how the next census grows"), not a silent
 exemption. Zero live sites; `$4201` WRIO is the worked case.
- **An operand the file cannot fold fails CLOSED.** `sta a:$2107 - 1` IS a
 MOSAIC write and used to produce no finding of any kind; `+ SYM` and
 `| $0006` likewise. Reporting the base is the laundering. `$4300-$437F` is
 the one exception — the channel rules own that extent, and the tree's
 `<FEAT>_REGS = $4300 + ES_[HD]_<CLAIM>_CH * 16` idiom is unfoldable by
 construction (115 live sites).
- **The override is PORT-SCOPED.** `; REG-LINT: ok [$port] — <reason>`: an
 explicit port excuses only that port; a comment on a write's own line
 excuses that write; a standalone unscoped one excuses its ±3-line window
 only when every would-be finding in it is the same port, and is otherwise
 ambiguous and excuses nothing. Previously one stated BGMODE reason could
 silence an unrelated OBSEL write next door — a reviewer-facing hazard
 *both* implementations of this gate had.
- **~~`engine/toy` and the vendored probes match no path shape and stay
 ungated~~ — no longer true.** The default tier for a path matching no other
 shape is now the composed union of the map's scenes, so the toy and probes
 are CHECKED and have declared their boot writes
 (`engine/toy/feat_a`, `probe_vblank`, `probe_vb2reg/vb_a`). The old default
 was fail-OPEN: `engine/toy/main.asm` reported `1 file(s) clean` with **zero**
 of its 29 io write sites examined.
- **The summary line reports what was examined**, at which tier:
 `26 file(s) clean (22 feature-strict, 1 globals-union, 3 scene-union); reg
 ownership: 235 io write-site(s) examined (77 channel, 45 data, 48 latch,
 65 in-class, 0 unnamed, 0 unresolved)`. A disarmed pass now says so.

Still residue: the vendored boot includes
(`vendor/rom/ppu_reset.inc` et al., `.include`d into both gated `main.asm`s
via `init.inc`) are equally unwatched: the scan reads each listed file's own
text and never expands includes, so hole 2's amended main.asm rule covers
writes *textually in* main.asm and the boot reset chain — the sanctioned
single-writer case — stays single-file-textual residue, the same stance as
the tool's other limits. Fixtures + tests at
`tests/fixtures/reg_gate/` + `tests/test_reg_gate.py`, design record at; the second, unlanded
implementation's scoping record is + (ported 2026-08-01 with supersession
headers), and the two gates' cross-fire is.

A limit that used to be stated here (convergence §4.4 item 2) is **closed
as of 2026-08-25**: a write through a RELOCATED direct page — `lda #$2100 /
tcd / sta $05` IS a BGMODE write — is now tracked by the reg pass, which
folds DP state per routine and attributes direct-page operands to the port
they actually hit, running the same ownership checks as an absolute write
(the decimal spelling `sta 5` and an *emitted* dp symbol included, neither
of which the address rule could refuse). An unfoldable `tcd`/`pld` or
offset fails closed at the establishing site; a dp write into the channel
territory is refused outright. The tool's header carries the model, the
adoption-side declaration design, and what remains single-file/straight-line
about it; the summary's `dp:` census makes the tracker's reach readable.
The bare-literal backstop is unchanged.

**2. Scene-enter and boot register writes have no structural owner.** They are
attributed to the feature they serve, which works and is checked for
*collisions*, but the attribution itself is a convention no gate fully
enforces. **Amended 2026-07-31: the writer-side gate makes the convention
checkable at the union level** — a scene write to a register *no* feature of
that scene declares now refuses the build (`room.asm` writing a register
nobody in the room scene declared is a finding), and a `main.asm`/boot write
answers to the globals' union.

**CLOSED 2026-08-02 (queue item 5 — settlement brief).**
What remained unenforced was the attribution itself: the union check proved
*someone in this scene declared it*, not *the register's owner expects this*. A
`[[claims.reg]]` now carries an optional **`scene_writes`** — a subset of its
own `registers` meaning *"scene-enter or boot code may write these registers
of mine"* — and the three union tiers (scene, globals, composed) narrow
**both arms** of their acceptance test to that subset: `declared` keeps an
in-class port only if its claim opens it, and `covered` keeps an in-class port
an `hdma`/`dma_init` claim covers only if the same feature opens it on a
`[[claims.reg]]` **and lists it in `scene_writes`**. Region data/latch ports
are not narrowed (§2.5's residue). A companion `scene_writes_shared` declares
the one irreducible co-write (`scene_mgr`/NMITIMEN), and a
declaration-that-lies check refuses an untrue declaration in either direction.

Measured: eleven declarations across ten tomls, zero findings on the clean
tree, both ROM md5s unmoved, and all eight of's previously-
**accepted** plants now refuse. The two structural alternatives this closes
*without* — a companion dir per scene, or extending `SceneDecl`/
`GameManifest`/`load_manifest` to carry claims — remain larger than C4 was
and were rejected on cost in

**Successor residue**, carried in:
- item 1 — a scene write to a port **no** feature of the scene owns at all is
 still attributed only by the union, not to a specific feature;
- item 7 — the **dead-permission** direction (`scene_writes` naming a register
 *nothing* writes) needs a repo-wide scope the per-game gate lacks: `text_bg3`
 opens BG3HOFS/BG3VOFS and only `room`'s scenes write them, so a per-invocation
 version fires on `microzero`;
- item 8 — a scene write to a **globals**-owned port (`$4200` from a scene) is
 still accepted; the scene tier's union includes the globals' claims, and
 separating them is a tier change rather than a field (plant F pins this
 limit deliberately). **Also stated in `no_literals.py`'s header block since
 the item-5 remediation** — an implementer meets this limit *silently*, since
 the write is accepted and there is no diagnostic to read, so the one place it
 was recorded was the one place they were not looking ;
- item 9 — `no_literals` remains **single-file textual**; the lies-check reads
 the owner's directory, not the whole program.

### 2.2 Scanline IRQ / mid-frame CPU — blocks a proven rail

`split_h_irq_grad_demo` is a **proven** rail whose whole mechanism is a
seam-scanline IRQ supplying the band origin, which **frees an HDMA channel** — 3
channels busy instead of 6 — spent on a per-line COLDATA gradient (the spec).
`seam_irq_trial` is the same mechanism.

**There is no IRQ claim class**, so a composition already proven on hardware
cannot be declared. None of `{vram, dp, wram, cgram, oam, hdma, dma, dma_init,
rom}` expresses "the seam IRQ vector and its mid-frame fire window are taken."
VBlank-cycles are not active-display IRQ cycles.

the spec item 1 proposed either a new IRQ/mid-frame-slot class **or** folding it
into the HDMA-band model as an alternative channel-provider. The second framing
is the interesting one for the allocator: the rail's whole point is *trading* an
IRQ slot for a channel, so a model that sees both as channel-providers could
prove the trade rather than just permit it.

Surfaces on the current roadmap in ****, after Phases 2 and 3 build on top
of it. Recorded in as an abstract someday item and in
the spec as a taxonomy gap; this register is where those two facts are joined to
the rail that needs it.

### 2.3 Status of the spec's three taxonomy gaps — two are already closed

the spec item 4 still reads "close the three taxonomy gaps" as though all three
were open. They are not:

| the spec gap | state |
|---|---|
| 1. Scanline-IRQ resource class | **OPEN** — §2.2 above |
| 2. HDMA channel needs `(register, band)` sub-structure | **CLOSED** — `HdmaClaim.band` is a real `[start, end)` tuple (`schemas.py:370`, parsed by `_parse_band`), and contention is physical `(port, mask)` intersection, so sub-registers work too (the `COLDATA_*` planes compose while `COLDATA` refuses against any of them) |
| 3. Frame-phase / double-buffer ownership | **PARTLY CLOSED** — `phase ∈ {active, vblank, forced_blank}` is modelled and load-bearing. Double-buffer ownership is **not** modelled; microzero uses a single buffer, so nothing demands it yet. The vendored reference scene already implements the pattern (`pv_hdma_ab0/ab1`), so this is "model a known-solved pattern" |

### 2.4 SPC RAM occupancy — **SHIPPED as `claims.spc`** (C1, 2026-07-30)

The eleventh claim class, and deliberately the smallest: **presence-only,
exclusive, PROGRAM-wide.** `[[claims.spc]]` (a `name`, nothing else) asserts
occupancy of the audio CPU's entire 64 KiB; a second holder anywhere in the
game — same scene, different scenes, globals vs scene — refuses the build with
both features named. `substrate.toml [spc]` records the space;
`check_spc_exclusivity` (`allocator/allocate.py`) runs over the resolved
global + scene closures before any placement; `symbol_map.json` carries the
owner as `spc_owner` (no symbol is emitted — ownership classes are checks,
not layouts; the `reg` precedent). Alongside it, **`APUIO` = `($2140, WHOLE)`**
joined `REGISTER_FOOTPRINT` under the ALU one-name-per-resource convention,
so the mailbox is claimable through §2.1's shipped machinery.

**The class boundary.** A feature is IN when it occupies SPC RAM or drives
the CPU↔APU boundary: uploads through the loader, owns the driver, places
samples/songs/echo. It declares `spc` (occupancy) + `reg` on `APUIO`
(the mailbox). A feature that merely *asks* the occupant for services
(play a song id, trigger an SFX) through the occupant's API is OUT — it
depends on the audio feature, it does not claim. Census instances: **one**
— `engine/features/audio/` (2026-07-30), holding `spc` + `reg`
APUIO + the driver's pinned `tad_bss`/`tad_zp` byte claims; `tad_rom` is
its blob. The room game's scenes queue SFX through the API and claim
nothing — the OUT case, as designed.

**Why not a region packer** — settled by reading TAD's memory model at the
vendored pin, ratified against the artifact: the occupant's own
compiler packs the space and refuses over-budget compositions per song at
build time; a SuperForge-side model of that interior would be a second source
of truth for another tool's allocator. The claim is the *boundary* TAD
states only as a comment (`tad-audio.inc:49`). The own-driver region form
(ESA/DIR alignment, EDL granularity, C5 voices) is pre-scoped in and would replace this shape, not extend it.

**Why PROGRAM-wide when every sibling check is per-scene:** the occupant's
driver initialises once per power-on (`Tad_Init` re-called hardlocks) and
its Audio-RAM upload persists across scene transitions, so scene separation
composes nothing. `tests/test_spc_claim.py::test_refusal_is_program_wide`
locks this — it goes red under a per-scene implementation (verified by
planting one).

**What this does NOT close** (the same two holes as §2.1, inherited
knowingly — **hole 1 since closed, 2026-07-31**): ~~no writer-side gate — a
raw `sta $2140` in an undeclared file still assembles ($2140-43 sit inside
`io_allowed`'s `$2100-$21FF` window)~~ — the C4 writer-side gate landed
(§2.1 hole 1), and the APUIO span makes every `$2140-$2143` store in a
gated file answer to the `audio` feature's claim. And the `Tad_Init`
boot contract (once-only, IPL running, interrupts off, >40 scanlines
post-reset) is a scene-manager/boot contract with an emulator test, arriving
with — a timing contract is not a resource claim.

---

## 3. Supply census

> **What is gated here, and what is not.** The census block below is GENERATED
> from the tree and `make register` fails when it and the tree disagree, so it
> cannot drift. Two neighbouring things are **hand-maintained and ungated**,
> deliberately, and a reader should not extend the census's authority to them:
>
> - **§1.1/§1.2's `claim classes` column.** The spec asked for the row to be
> split so this column could be generated too; it was not, and deferring is
> defensible on two grounds neither party stated at the time. Those rows are
> keyed by **demand term** (`TXT`, `GRAD`, `STREAM`), not by dir, so
> generating the column needs a machine-readable demand→dir map that does not
> exist and is hand-owned judgement. And the cells carry sizes and
> annotations the census does not produce (`` `wram` (240 B canvas, dma
> source) ``) — generating them verbatim would *lose* information. Re-derived
> from the tomls at and correct as of 2026-07-29; nothing holds them
> there. Closing it needs a declared `supplies` field on `feature.toml`, which
> is its own pass.
> - **§3.1's `supplies / serves` column.** Judgement by design. Only its KEY SET
> is checked against the census — a new dir cannot land without a serves line
> and a deleted one cannot linger — never its words.
>
> The prose in §1/§5 that *cites* the census is checked, but only within a
> stated bound: `make register` prints `demand lint reached N/M demand rows`,
> and rows naming no dir in either their subject or their `supplied by` column
> are outside it. See `tools/gen_register.py`'s KNOWN LIMIT.

<!-- BEGIN GENERATED: census -->
**All 179 dirs under `engine/features/` accounted for.** 91 feature &middot; 48 blob &middot; 3 companion &middot; 27 consumer &middot; 10 game_logic.

Generated from the tree by `tools/gen_register.py`; `make register` fails when this block and the tree disagree. Every column here is a fact a `feature.toml` states -- including `role`, which is declared rather than inferred because nothing in the claims distinguishes a blob from a feature. The judgement columns live in §3.1, which is hand-owned.

| dir | role | scope | claims | depends |
|---|---|---|---|---|
| `audio` | **feature** | unused | `dp`, `wram`, `reg`, `spc` | `tad_rom` |
| `backdrop` | **feature** | scene | `cgram`, `reg` | &mdash; |
| `barrel_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `bg_text` | **feature** | scene | `vram`, `cgram`, `reg` | `text_dp`, `font_rom`, `text_chr` |
| `blend_off` | **feature** | unused | `blend` | &mdash; |
| `brawler_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `brawler_rom` |
| `brawler_obj` | **consumer** | unused | `vram`&times;2, `cgram`&times;2, `oam`, `dp`, `dma_init`, `reg` | `oam_sprites`, `brawler_rom` |
| `brawler_rom` | **blob** | unused | `rom`&times;9 | &mdash; |
| `breaker_bg` | **feature** | unused | `vram`&times;4, `cgram`&times;2, `wram`&times;2, `dma_init`, `reg` | `breaker_rom` |
| `breaker_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;2, `dma_init`, `reg` | `oam_sprites`, `breaker_rom` |
| `breaker_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `bs_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `bs_rom` |
| `bs_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;5, `dp`, `wram`, `dma_init`, `reg` | `oam_sprites`, `bs_rom`, `pool` |
| `bs_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `car_rom` | **blob** | global | `rom`&times;2 | &mdash; |
| `cf_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dp`, `dma_init`, `reg` | `cf_rom` |
| `cf_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;2, `dma_init`, `reg` | `oam_sprites`, `cf_rom` |
| `cf_rom` | **blob** | unused | `rom`&times;4 | &mdash; |
| `col_map` | **feature** | scene | `dp` | &mdash; |
| `col_map_rom` | **blob** | global | `rom` | &mdash; |
| `dialog` | **feature** | unused | `vram`, `cgram`, `dp`, `wram`, `hdma`, `dma_init`, `dma` | `bg_text`, `text_chr`, `dlg_rom` |
| `dlg_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `enter_scr` | **companion** | global | `dp`, `dma_init`&times;2 | &mdash; |
| `fade` | **feature** | global | `dp` | &mdash; |
| `font_rom` | **blob** | global | `rom` | &mdash; |
| `haze` | **feature** | unused | `dp`&times;2, `hdma`&times;2, `reg` | `hz_rom` |
| `hero_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `hud_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;2, `dma_init`, `reg` | `oam_sprites`, `hud_rom` |
| `hud_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `hz_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg`, `screen`&times;2 | `hz_rom` |
| `hz_flat` | **feature** | unused | `reg` | &mdash; |
| `hz_rom` | **feature** | unused | `rom`&times;5 | &mdash; |
| `input` | **feature** | global | `dp`&times;3 | &mdash; |
| `input2` | **feature** | unused | `dp`&times;3 | &mdash; |
| `irq` | **feature** | unused | `reg` | &mdash; |
| `jumper_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `jumper_rom` |
| `jumper_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dma_init`, `reg` | `oam_sprites`, `jumper_rom` |
| `jumper_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `lake_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg`, `screen`&times;2 | `lake_rom` |
| `lake_rom` | **blob** | unused | `rom`&times;3 | &mdash; |
| `m7_affine` | **feature** | unused | `dp`, `rom`, `reg` | &mdash; |
| `m7_barrel` | **feature** | unused | `dp`&times;2, `wram`, `hdma`&times;2, `reg`&times;2 | `barrel_rom`, `input` |
| `m7_persp_project` | **feature** | unused | `dp`, `reg` | `sh2_sprite_rom` |
| `m7_project` | **feature** | unused | `dp` | `m7_affine` |
| `m7_track` | **feature** | unused | `dp` | `m7_affine` |
| `m7c_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `m7c_rom` |
| `m7c_roll` | **game_logic** | unused | `dp` | `m7_barrel` |
| `m7c_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `m7dg_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `m7dg_rom` |
| `m7dg_obj` | **consumer** | unused | `vram`, `cgram`&times;3, `oam`&times;4, `dp`, `dma_init`, `reg` | `oam_sprites`, `m7dg_rom`, `m7_project` |
| `m7dg_rom` | **blob** | unused | `rom`&times;10 | &mdash; |
| `m7f_cam` | **feature** | unused | `dp`&times;4, `wram`&times;2, `hdma`&times;2, `reg`&times;2 | `m7f_rom` |
| `m7f_floor` | **feature** | unused | `vram`, `cgram`&times;2, `wram`&times;3, `rom`&times;2, `hdma`, `dma_init`, `reg`&times;2 | `m7f_rom` |
| `m7f_logic` | **game_logic** | unused | &mdash; | `m7f_cam`, `input` |
| `m7f_obj` | **feature** | unused | `vram`, `cgram`&times;2, `oam`&times;4, `dp`, `dma_init`, `reg` | `m7f_rom`, `oam_sprites`, `m7f_cam` |
| `m7f_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `m7x_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `m7x_rom` |
| `m7x_logic` | **game_logic** | unused | `dp`&times;2 | `m7x_floor`, `m7x_obj` |
| `m7x_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;2, `dp`, `dma_init`, `reg` | `oam_sprites`, `m7x_rom` |
| `m7x_rom` | **blob** | unused | `rom`&times;8 | &mdash; |
| `m7x_town` | **feature** | unused | `vram`&times;2, `cgram`, `oam`&times;2, `dp`, `reg` | `m7x_rom` |
| `maze_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `maze_rom` |
| `maze_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dma_init`, `reg` | `oam_sprites`, `maze_rom` |
| `maze_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `met_bg` | **feature** | unused | `vram`&times;2, `cgram`, `wram`, `dma_init`, `reg` | `met_rom` |
| `met_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `met_rom` |
| `met_glow` | **feature** | unused | `wram`, `hdma`, `reg` | &mdash; |
| `met_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;4, `dp`, `dma_init`, `reg` | `oam_sprites`, `met_rom` |
| `met_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `mil_band` | **feature** | unused | `wram`, `offset_bands` | `mil_opt` |
| `mil_bg` | **feature** | unused | `vram`&times;5, `cgram`&times;2, `dma_init`, `reg`, `screen`&times;2 | `mil_rom` |
| `mil_mode` | **feature** | unused | `video` | &mdash; |
| `mil_mode_dc` | **feature** | unused | `video` | &mdash; |
| `mil_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dp`&times;9, `dma_init`, `reg`, `screen` | `oam_sprites`, `mil_rom` |
| `mil_opt` | **feature** | unused | `vram`, `dp`&times;6, `wram`, `hdma`, `reg`, `offset`, `dma` | `mil_rom` |
| `mil_rom` | **blob** | unused | `rom`&times;10 | &mdash; |
| `mil_tint` | **feature** | unused | `reg`, `blend` | &mdash; |
| `mo_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `mo_rom` |
| `mo_obj` | **consumer** | unused | `vram`, `cgram`&times;4, `oam`&times;6, `dp`, `wram`, `dma_init`, `reg` | `oam_sprites`, `mo_rom`, `m7_project`, `pool` |
| `mo_rom` | **blob** | unused | `rom`&times;10 | &mdash; |
| `mode7_floor` | **feature** | scene | `vram`, `cgram`, `rom`&times;2, `reg` | `world_rom` |
| `mode7_persp` | **feature** | scene | `dp`, `wram`, `hdma`&times;2, `reg` | `pose_rom` |
| `mode7_stream` | **feature** | scene | `dp`&times;2, `wram`&times;3, `hdma`, `dma` | &mdash; |
| `mosaic` | **feature** | unused | `dp`, `reg` | &mdash; |
| `oam_sprites` | **feature** | global | `wram`, `hdma`, `dma` | &mdash; |
| `patrol_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `patrol_rom` |
| `patrol_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;3, `dma_init`, `reg` | `oam_sprites`, `patrol_rom` |
| `patrol_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `pfs_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dp`, `dma_init`, `reg` | `pfs_rom` |
| `pfs_logic` | **game_logic** | unused | `vram`, `cgram`, `oam`, `dp`&times;2, `dma_init`, `reg` | &mdash; |
| `pfs_rom` | **blob** | unused | `rom`&times;8 | &mdash; |
| `pfs_stream` | **feature** | unused | `dp`&times;2, `wram`&times;2, `hdma`, `dma_init`, `dma` | &mdash; |
| `platformer_bg` | **feature** | unused | `vram`&times;3, `cgram`&times;2, `dp`&times;2, `wram`&times;2, `hdma`, `dma_init`, `reg`&times;2 | `platformer_rom` |
| `platformer_obj` | **consumer** | unused | `vram`, `cgram`&times;2, `oam`&times;3, `dma_init`, `reg` | `oam_sprites`, `platformer_rom` |
| `platformer_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `player_car` | **consumer** | scene | `vram`, `cgram`, `oam`, `dma_init`, `reg` | `oam_sprites`, `car_rom` |
| `pool` | **feature** | unused | `dp` | &mdash; |
| `pose_rom` | **blob** | global | `rom`&times;2 | &mdash; |
| `race_logic` | **game_logic** | scene | `dp`, `reg` | `mode7_persp`, `mode7_stream` |
| `rc_grad` | **feature** | unused | `wram`, `hdma`&times;3, `reg` | &mdash; |
| `rc_kart` | **consumer** | unused | `vram`, `cgram`, `oam`&times;3, `dma_init`, `reg` | `oam_sprites`, `rc_rom` |
| `rc_logic` | **game_logic** | unused | `dp`, `reg` | `mode7_persp`, `mode7_stream`, `col_map` |
| `rc_rom` | **blob** | unused | `rom`&times;3 | &mdash; |
| `region` | **feature** | global | `dp` | &mdash; |
| `rgb_gradient` | **feature** | scene | `rom`, `hdma`&times;3, `reg` | &mdash; |
| `room_bg` | **feature** | unused | `vram`&times;4, `cgram`&times;2, `dma_init`, `reg` | `room_rom` |
| `room_hero` | **consumer** | unused | `vram`, `cgram`, `oam`&times;2, `dma_init`, `reg` | `oam_sprites`, `hero_rom` |
| `room_logic` | **game_logic** | unused | `oam`, `dp`&times;2 | `room_hero`, `window_iris` |
| `room_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `rpg_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `rpg_rom` |
| `rpg_logic` | **game_logic** | unused | `dp`, `wram` | &mdash; |
| `rpg_obj` | **feature** | unused | `vram`, `cgram`, `oam`&times;2, `dma_init`, `reg` | `rpg_rom`, `oam_sprites` |
| `rpg_rom` | **blob** | unused | `rom`&times;9 | &mdash; |
| `rpg_town` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `rpg_rom` |
| `rs_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `rs_rom` |
| `rs_logic` | **game_logic** | unused | `dp` | `pool`, `rs_obj`, `mode7_persp` |
| `rs_obj` | **consumer** | unused | `vram`, `cgram`&times;2, `oam`&times;7, `dp`, `wram`&times;2, `dma_init`, `reg` | `oam_sprites`, `pool`, `rs_rom` |
| `rs_rom` | **blob** | unused | `rom`&times;7 | &mdash; |
| `sau_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `sau_rom` |
| `sau_obj` | **consumer** | unused | `vram`, `cgram`&times;2, `oam`&times;8, `dp`, `wram`, `dma_init`, `reg` | `oam_sprites`, `sau_rom`, `pool` |
| `sau_rom` | **blob** | unused | `rom`&times;9 | &mdash; |
| `save` | **feature** | unused | `dp`, `sram`, `rom` | &mdash; |
| `scene_mgr` | **feature** | global | `dp`&times;2, `wram`&times;2, `reg` | &mdash; |
| `scroller_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dp`, `dma_init`, `reg` | `scroller_rom` |
| `scroller_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dma_init`, `reg` | `oam_sprites`, `scroller_rom` |
| `scroller_rom` | **blob** | unused | `rom`&times;4 | &mdash; |
| `sh2_cam` | **feature** | unused | `dp`&times;2, `wram`, `hdma`&times;6, `reg` | `sh2_rom`, `input`, `input2` |
| `sh2_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `sh2_rom` |
| `sh2_obj` | **consumer** | unused | `vram`, `cgram`&times;2, `oam`, `dp`, `dma_init`, `reg` | `oam_sprites`, `m7_persp_project`, `sh2_swarm`, `sh2_sprite_rom`, `sh2_rom` |
| `sh2_rom` | **blob** | unused | `rom`&times;11 | &mdash; |
| `sh2_sprite_rom` | **blob** | unused | `rom`&times;8 | &mdash; |
| `sh2_swarm` | **game_logic** | unused | `dp`, `wram`&times;2 | `sh2_cam`, `m7_persp_project`, `sh2_sprite_rom`, `sh2_rom`, `input`, `input2` |
| `shg_cam` | **feature** | unused | `wram`&times;2, `hdma`&times;4, `reg` | `shg_rom`, `irq` |
| `shg_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `shg_rom` |
| `shg_grad` | **feature** | unused | `wram`, `hdma`, `reg` | &mdash; |
| `shg_rom` | **blob** | unused | `rom`&times;3 | &mdash; |
| `shm_cam` | **feature** | unused | `dp`, `wram`, `hdma`&times;2, `reg` | `input` |
| `shm_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `shm_rom` |
| `shm_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `shmup_bg` | **feature** | unused | `vram`&times;3, `cgram`&times;2, `dp`, `dma_init`, `reg` | `shmup_rom` |
| `shmup_obj` | **consumer** | unused | `vram`, `cgram`&times;3, `oam`&times;4, `wram`, `dma_init`, `reg` | `oam_sprites`, `shmup_rom` |
| `shmup_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `shp_cam` | **feature** | unused | `dp`, `wram`, `hdma`&times;6, `reg` | `shp_rom`, `input` |
| `shp_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `shp_rom` |
| `shp_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `sit_cam` | **feature** | unused | `wram`&times;2, `hdma`&times;4, `reg` | `sit_rom`, `irq` |
| `sit_floor` | **feature** | unused | `vram`, `cgram`, `dma_init`, `reg` | `sit_rom` |
| `sit_rom` | **blob** | unused | `rom`&times;4 | &mdash; |
| `sky_band` | **feature** | scene | `vram`&times;2, `cgram`, `rom`&times;3, `dma_init`, `reg` | &mdash; |
| `smt_bg` | **feature** | unused | `vram`&times;3, `cgram`&times;2, `dma_init`, `reg`, `screen`&times;2 | `smt_rom` |
| `smt_flat` | **feature** | unused | `reg`, `screen`, `video` | &mdash; |
| `smt_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dp`&times;6, `dma_init`, `reg`, `screen` | `oam_sprites`, `smt_rom` |
| `smt_opt` | **feature** | unused | `vram`, `dp`&times;6, `hdma`, `reg`, `video`, `offset`, `dma` | `smt_rom` |
| `smt_rom` | **blob** | unused | `rom`&times;11 | &mdash; |
| `split_band` | **feature** | scene | `hdma`&times;2, `reg` | &mdash; |
| `split_v_bg` | **feature** | unused | `vram`&times;4, `cgram`&times;2, `dp`&times;2, `dma_init`, `reg` | `split_v_rom` |
| `split_v_obj` | **feature** | unused | `vram`&times;2, `cgram`&times;3, `oam`&times;6, `dp`, `dma_init`, `reg` | `split_v_rom` |
| `split_v_rom` | **blob** | unused | `rom`&times;12 | &mdash; |
| `sprg_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;3, `dma_init`, `reg` | `oam_sprites`, `sprg_rom` |
| `sprg_rom` | **blob** | unused | `rom`&times;2 | &mdash; |
| `sr_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dp`, `dma_init`, `reg` | `sr_rom` |
| `sr_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dma_init`, `reg` | `oam_sprites`, `sr_rom` |
| `sr_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `stomper_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dma_init`, `reg` | `stomper_rom` |
| `stomper_obj` | **consumer** | unused | `vram`, `cgram`, `oam`, `dp`, `dma_init`, `reg` | `oam_sprites`, `stomper_rom` |
| `stomper_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `svd_bg` | **feature** | unused | `vram`&times;2, `cgram`, `dp`&times;2, `wram`, `hdma`, `dma_init`, `reg` | `svd_rom` |
| `svd_obj` | **consumer** | unused | `vram`, `cgram`, `oam`&times;3, `dma_init`, `reg` | `oam_sprites`, `svd_rom` |
| `svd_rom` | **blob** | unused | `rom`&times;6 | &mdash; |
| `tad_rom` | **blob** | unused | `rom` | &mdash; |
| `text_chr` | **companion** | scene | `vram` | &mdash; |
| `text_dp` | **companion** | global | `dp`&times;3, `dma_init` | &mdash; |
| `tick_scale` | **feature** | global | &mdash; | `region` |
| `vwf` | **feature** | scene | `dp`, `wram`, `hdma`, `dma` | `text_dp`, `text_chr`, `vwf_rom` |
| `vwf_rom` | **blob** | global | `rom`&times;2 | &mdash; |
| `water` | **feature** | unused | `vram`&times;2, `cgram`, `dp`, `hdma`, `dma_init`, `reg`, `screen`, `blend`, `dma` | `water_rom` |
| `water_rom` | **blob** | unused | `rom`&times;4 | &mdash; |
| `window_iris` | **feature** | unused | `dp`, `wram`, `hdma`, `reg` | `room_rom` |
| `world_rom` | **blob** | global | `rom` | &mdash; |
<!-- END GENERATED: census -->

Spec acceptance 2: every `engine/features/*` dir appears as a supplier, a
supporting blob, or a global companion. **None unaccounted for.** Two categories
beyond the spec's three were needed and are named rather than fudged:
*game-side consumer* and *game logic*, both of which live under
`engine/features/` today.

`role` is declared in each `feature.toml` and validated by
`allocator/schemas.py`, because it is the one column in the census that no
claim distinguishes: `car_rom` and `col_map_rom` both claim `rom` with no deps
and are blobs, while `backdrop` claims `cgram` with no deps and is a feature.
Its value set is coarser than the labels below on purpose — it carries only
distinctions a gate could enforce, so the finer ones
(*infrastructure* vs feature, *global* vs *shared-surface* companion) live here
in prose, where they are read rather than checked.

### 3.1 What each dir serves — hand-owned

The judgement column, kept out of the generated block above because it is not a
tree fact. `make register` asserts only that this table's dir set matches the
census, so a new dir cannot land without an entry — the words are never
machine-written.

| dir | supplies / serves |
|---|---|
| `audio` | AUD — the TAD occupant: `spc` exclusivity + the `APUIO` mailbox + the driver's pinned lowram/DP state; game code asks it for music/SFX, it never claims per scene (program-wide by the driver's own contract) |
| `backdrop` | **infrastructure** (micro-feature) — scene backdrop colour; deliberately its own claim so a Mode 7 floor palette declaring word 0 refuses the build |
| `barrel_rom` | `m7_barrel` — the two per-scanline matrix COLUMNS, and the feature's DOMAIN written down : `bow_a` is nine 192-line M7A columns **indexed by BOW STEP** (step 0 flat = the runtime non-vacuity control, step 8 the chamber's captured `$0100`→`$0180`→`$0100` raised cosine) and `persp_d` is ONE 192-line M7D column **indexed by nothing** — the perspective hyperbola `S(k) = K/(k+k0)`, single because the camera height is fixed and the bow lives entirely in A. Mode-2 data (2 B/line, one write-twice register) rather than `pose_rom`'s 4-byte `[A,B]`/`[C,D]` pairs, because this rail's angle is constant so M7B/M7C are zero on every line and `m7_barrel` writes them once instead. 3,840 B against `pose_rom`'s 128 KB, and the whole set fits one LoROM window so the DASB byte is static. **THE CONSEQUENCE OF THOSE TWO DOMAINS, stated here because this is the surface a scheduler reads :** a rail that ROTATES, or that RAMPS ITS PERSPECTIVE SCALE, or that wants more than one band, is **not** served by this blob as it stands — it needs a SECOND AXIS baked into `barrel_rom` (and the ROM cost multiplies by that axis's length). Do not schedule such a rail against this supply row without that work in its scope — a table-driven feature gets mis-scheduled whenever its domain lives somewhere other than the surface the scheduler reads |
| `bg_text` | TXT, fixed-width |
| `blend_off` | **infrastructure** (micro-feature) — the colour-math unit's OFF state, expressed as a `[[claims.blend]]` (`prevent = "always"`, composing CGWSEL $30). The composed blend state is per scene and nothing carries it across an edge, so a scene that composes no blend half inherits its predecessor's; this is the remedy docs/99 §4 names, in claim form rather than as a raw CGWSEL/CGADSUB owner that disarms at exit. Composing it gives the successor scene ownership of both ports and the symbols to write them from. `lakeside`'s title scene is the worked case, and the composition warns on the claim by design — that warning is how an author who wrote `prevent = "always"` by accident learns why their blend is invisible |
| `brawler_bg` | **BG (row 10)** — the `brawler` rail's whole Mode-1 display shape (BGMODE $09 / TM $15 owner; `bg_text` rides BG3 beside it). The keystone BG pattern's next instance after `stomper_bg`, with the axis THIS rail adds: the tilemap is built by **TILING an 8×6 art PATCH** (`col mod 8` across, patch row 1 on the surface row and row 2 down the body) rather than by rendering a per-cell world blob, which is the reason the map blob is 48 words instead of 1024. The rows above and below the floor are written EXPLICITLY as the reserved blank tile (power-on VRAM is random, and nothing here clears a shadow first). Scroll is STATIC, pinned by the feature's own arm (HOFS 0, VOFS −1), which is what puts tilemap row 20's top edge on screen y 160 — the surface the lane band anchors the knights' DRAWN FEET to |
| `brawler_obj` | **THE SECOND OBJ NAME TABLE** — the `brawler` rail's two knights, staged into the `oam_sprites` shadow every frame. Arthur fills OBJ name table 0 (256 tiles, exactly) so Mordred is loaded at the SECOND base and reached through OBSEL's name-select gap plus the OAM attribute's 9th tile bit. Two `obj` vram claims; the allocator cannot say which is table 0 (`VramClaim.obj` is a bare bool), so the gap is **derived from the two emitted bases** (`ES_V_BR_MOR_CHR − ES_V_BR_ART_CHR`) and the build refuses unless it is a whole number of 4 K-word steps and fits OBSEL's two bits — the identity lives in OBSEL and the attribute, where the hardware puts it, and the allocator's job stays "hand out non-overlapping space". Also the tree's FIRST non-zero hi-table SIZE bits (both knights are the large half of pair 3), and a park row of 224 rather than `oam_park_all`'s 240, because OAM Y wraps mod 256 and a 32-tall sprite at 240 shows its bottom rows on scanlines 0..15 |
| `brawler_rom` | `brawler_bg` + `brawler_obj` — nine blobs from `tools/gen_brawler_assets.py`, converted from the ORIGINAL pack PNGs (`vendor/art/camelot`, CC0; `vendor/art/four_seasons_tileset`, a permissive **non-CC0** grant) and byte-identical to the vendored `png2snes` reference conversion: Arthur's 16 frames (8192 B = one whole name table), Mordred's 12 (6144 B), both palettes, the 49-tile terrain patch with its palette and 48-word map, and the five animation tables packed on an 8-byte stride with their `(len, rate)` companion — length is DATA because the rail's stated lesson is that a 4-step table indexed by a stale 8-step counter reads past its end |
| `breaker_bg` | **BG** — the `breaker` arena: BG1 walls + brick wall, BG2 night bed, in ONE feature. Also owns the map's 32x32 collision mirror and the live tilemap-cell break queue, because a running scene cannot read VRAM back |
| `breaker_obj` | `breaker`'s paddle (3 OBJs) + ball; SPR consumer |
| `breaker_rom` | `breaker_bg` + `breaker_obj` |
| `bs_floor` | **M7 plane** — the `boss` rail's arena: the pinned interleaved Mode 7 region, a sixteen-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot, the arena dark), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. The EIGHTH instance of the `m7dg_floor` sibling ruling (`mo_floor` is the nearest, and cannot serve because it is welded to `mo_rom`'s blobs by name). No `hdma` claim: the whole rail is one uniform matrix per frame — the scale RAMP costs a track lookup, not a channel, which is's cheapness claim surviving the axis it said was missing |
| `bs_obj` | **the boss fight's cast, and POOL's third generic consumer** — the `boss` rail's player ship (16×16, hit-flash frame), eight pooled attack-rain orbs, the eight-segment boss-HP HUD, four pooled player shots. Twenty-one sprites in twenty-four slots so all six hi-table bytes have one owner and are rebuilt whole (mo_obj's ruling); the slot map is PINNED to stable identities (0 player, 1-8 attacks, 9-16 HUD, 17-20 shots) so a test reads an actor by slot. Holds both pools' storage in one `bs_actors` wram claim at documented offsets (rs_obj's shape, what `pool.asm`'s binding contract is written against). OBSEL claimed here, size pair 0 — the pair that survives a $62 mis-sizing |
| `bs_rom` | `bs_floor` + `bs_obj` + `m7_track` — seven blobs from two generators: `tools/gen_boss_assets.py` authors the 32 KB interleaved arena-golem plane, its sixteen-word palette, the 32-tile OBJ sheet and its palette (a shape predicate over the tile grid — first-party procedural authoring, so there is no converter to ground-truth); `tools/gen_boss_tracks.py` bakes the THREE matrix-track blobs (`bs_ring` 256 headings at rest scale 1.5, `bs_reveal` 61 entries 5.0→1.5, `bs_death` 61 entries 1.5→4.8) from the declared schedule constants with the exact smul16 floor-shift arithmetic, and asserts both seams (reveal[60]==ring[60], death[0]==ring[0]) |
| `car_rom` | `player_car` |
| `cf_bg` | **BG** — the `camera_follow` rail's whole display: the keystone BG pattern (scroller_bg's instance, unchanged mechanics — one layer, two tiles, a 32×32 checkerboard **built** at enter, CGRAM word 0 owned) with the camera axis UPGRADED from pad-driven to **follow-derived**: cam = clamp(player − half-screen, 0, world − screen), recomputed by the scene's tick as a pure function of the player's world position and committed by the NMI hook to BG1HOFS/BG1VOFS. The clamp is the rail — the camera stops at the 512×448 world's edges while the player keeps walking. **The supply-column instance this rail adds (wave nine):** `room_bg` is ACCEPTED by the allocator for this composition (probe run 2026-08-07 — depends drags `room_rom` in, 22 placements, allocation OK) and still cannot express the rail: its own code pins BG1HOFS/BG1VOFS at zero. The allocator proves collision-freedom, not sufficiency; the run-it-first prophylactic catches refusals, and reading the feature's ASM is still what catches pins |
| `cf_obj` | the `camera_follow` rail's one 8×8 player, drawn at **world − camera** (`US_SCRX`/`US_SCRY`, the subtraction staying game-side in the scene's tick as the source has it) and re-staged into the `oam_sprites` shadow every frame. Mid-world the camera tracks so the sprite HOLDS screen-centre while the BG slides; at a world edge the camera clamps so the BG holds and the sprite WALKS to the screen edge — which regime is on screen is decided entirely by the subtraction this feature consumes. SPR consumer, hud_obj's pinned-at-0 claim shape |
| `cf_rom` | `cf_bg` + `cf_obj` — four small blobs (2 BG tiles, 1 OBJ tile, 2 palettes) from `tools/gen_cf_assets.py`, no tilemap (the map is built at enter; in this rail the 256 px map repeating under a 512×448 world is itself a lesson — "a small tilemap covers a large world"). Byte-identical content to `scroller_rom`'s blobs by shared ancestry (both source templates keep the same solid tile and colour constants), generated per-rail so neither rail can silently re-point the other's art |
| `col_map` | col_map (§1.2) |
| `col_map_rom` | `col_map`'s derived flag table |
| `dialog` | **DIALOG (debut)** — the opaque BG3 message window: a nine-patch panel of OPAQUE 2bpp CHR drawn over a RUNNING scene, paged text flowing inside it, closing back to the scene it covered. The two things `bg_text` structurally cannot do — index 0 is transparent by hardware so a box of font glyphs is not a box, and every bg_text entry point but the 4-word `txt_q` writes VRAM under forced blank at scene ENTER. Claims NO PPU register (bg_text still owns BG3's layer set, the scene's BG feature still owns BGMODE/TM) and commits its whole row span through one vblank `hdma`+`dma` claim — the shape `text_dp`'s own toml prescribes for a tilemap block. Its page is a second `kind="chr"` claim reached at tile 512 from BG3's base, with the reach ASSERTED from emitted symbols because docs/09 §5.1's `reach =` field does not exist yet |
| `dlg_rom` | `dialog`'s nine nine-patch tiles + its 4-colour panel sub-palette |
| `enter_scr` | **global companion** — enter-time scratch + `mode7_floor`'s two upload shapes |
| `fade` | fades (§1.2) |
| `font_rom` | `bg_text` |
| `hero_rom` | `room_hero` |
| `hud_obj` | `hud_game`'s player (one 8x8 OBJ); SPR consumer — the smallest OBJ feature in the tree, and the one that shows the hi-table-byte rule at its floor: it claims FOUR sprites for ONE player so the draw can rebuild the byte from the player's own X rather than read-modify-write around three slots it does not own (`breaker_obj`'s and `split_v_obj`'s argument, minimum size) |
| `hud_rom` | `hud_obj` |
| `input` | input, 1 pad (§1.2) |
| `input2` | input, pad 2 (§1.2's 2-controller row) — a sibling of `input`, not claims on it, so microzero's pinned DP map never re-packs (measured; see the toml) |
| `irq` | **SCANLINE IRQ (C3, the later rails-tail debut)** — the permanent owner/dispatcher seat for the one H/V timer: a single `reg` claim on the spanned `HVIRQ` name ($4207–$420A as ONE resource, the ALU precedent — schemas.py derives it from Mesen2 InternalRegisters.cpp:352-377), so an HTIME-only claimant and a VTIME-only claimant refuse instead of composing, per scene, through the existing ownership pass. Rails and consumers never claim HVIRQ themselves — they compose `irq` and call `irq_arm_v` (VTIME + the arm sequence contract; NMITIMEN stays `sm_display`'s, composed by boot or post-switch code under its existing `scene_writes` (never scene enter — the switch-restore strips it), and scene_mgr's switch-time masking IS disarm-across-scenes). The $FFEE vector is a link-time opt-in (`SF_IRQ_VECTOR` in `vendor/rom/header.inc`, default stub, byte-identical undefined); the handler is rail code at debut. Deferred with named triggers in the toml: WRAM-indirect dispatch, dynamic-VTIME helper, cycle-budget row. First consumer: `sit_cam` |
| `jumper_bg` | **BG** — the `jumper` rail's terrain layer, and the seventh instance of the keystone BG pattern. One layer, three tiles, **no camera**: the world is one screen and the whole vertical axis belongs to the player's physics, so BG1HOFS/BG1VOFS are pinned by the feature's own arm (HOFS 0, VOFS −1 per pfs_bg's scanline derivation) and never republished. What it adds to the pattern: the tilemap is **built from the `jr_world` blob** at enter — one ROM source for the drawn terrain and for `col_map`'s solid terrain, so the two agree by construction |
| `jumper_obj` | the `jumper` rail's player: one 8×8 OBJ whose position is the **whole output of the physics** — OAM entry 0 is the surface the state-cycle tests trace per frame (ascent, apex, descent, the landing frame, rest). Re-staged into the `oam_sprites` shadow every frame from the tick, matching the source's per-frame `spr_clear` + `spr`; X9 derived from bit 8 every frame rather than assumed clear. SPR consumer |
| `jumper_rom` | `jumper_bg` + `jumper_obj` + `col_map` — six blobs from `tools/gen_jumper_assets.py`: BG/OBJ CHR + palettes (terrain tile id 2, sprite tile id 1), the 1,024 B `jr_world` tile-id map (five `mset` loops baked row for row — level DESIGN, not a taught expression, unlike scroller's checkerboard), and the 256 B `jr_flags` tile-id→flag table (entry 2 = solid, mirroring `sf_tile_flags 2, SF_FLAG_SOLID`). `jr_world` is the single source of truth for terrain: display builds from it, collision probes it |
| `lake_bg` | **BG** — the `lakeside` rail's lakeshore world AND its display shape: BG1's shore-and-bed picture — a meandering waterline over silt, pebble, sandbar and weed clusters, dropping off a jagged shelf into open water — plus BGMODE $09, BG1SC, BG12NBA and both BG1 offsets. The keystone BG pattern's vocabulary-native instance — it designates its layers with `[[claims.screen]]` instead of raw-claiming TM, which is the only way a BG feature can stand in a scene that composes a blend (docs/99 R6 refuses the 27 features that raw-claim TM/TS). **It designates bg3 as well as bg1**, which is the demonstration: `bg_text` claims BG3's layout registers and deliberately not TM, so before the vocabulary its layer was on only because some TM owner happened to set the bit — here the bit is a named claim and `bg_text` composes untouched. BG12NBA stays a raw `[[claims.reg]]` here because the vocabulary composes the four blend ports and nothing else; the scene's write folds `water`'s emitted `ES_V_WAT_CHR_NBA` into this feature's, and the composition names the split as a warning |
| `haze` | **DISPLACEMENT** — heat shimmer as per-scanline `BG1VOFS` **and** `BG1HOFS`, on two HDMA channels across a declared band. **VERTICAL, and that is the effect's whole character**: an inferior mirage comes from a vertical refractive-index gradient (hot thin air at the ground, cooler denser air above) and rays bend along the gradient, which is why a mirage shows an inverted patch of sky below the horizon. The two axes are not symmetric on this hardware either — a per-scanline `BGnHOFS` shears each row sideways and every source row still appears exactly once, while a per-scanline `BGnVOFS` makes scanline N show source row N + d(N), so rows are DUPLICATED AND SKIPPED and the picture compresses and stretches. That squashing is the boiling. The HORIZONTAL term is the second half and it is a different phenomenon, not a second opinion about the same one: the mirage is the layer's stratification, the sideways jitter is turbulent cells drifting through the sightline. It gets its own channel, table, amplitude (a quarter of the vertical peak), wavelength and phase for that reason — and a flatter ramp, because turbulent cells are distributed through the air column while the layer's depth only lies along a horizon-ward sightline. Mode 3 could drive both ports from ONE channel (`B, B, B+1, B+1` over `$210D`/`$210E`, which `sh2_cam` and three siblings do) but it is 4 bytes a scanline: the stride doubles to 512, 65 blobs is 33,280 B against a 32,768 B bank window HDMA cannot cross, and it would cost half the phases AND force both axes to share one table. **The warp is a TABLE, not artwork**: `hz_rom` holds 64 complete HDMA tables at a 256 B stride plus a 65th all-zero CONTROL, so a blob's address is `hz_warp + (n << 8)` and the entire per-frame cost is ONE 8-bit store to the channel's A1T high byte; rebuilding it instead is priced by `platformer_bg` at ~16 cycles an entry. Amplitude peaks at the HORIZON and decays toward the viewer as `1/(y - horizon)`, because heat haze is path length through hot air and a sightline to the horizon grazes along the hot layer for its whole length while one to your feet crosses a thin slice; the wave lives in a PERSPECTIVE coordinate (the integral of that falloff) so an eddy has one physical size everywhere. It claims BOTH scroll ports TWICE — an `hdma` claim for the band and a `seed` `reg` claim for the base the head-skip entry restates — which the allocator requires to be a matched pair (`check_reg_ownership`, checks 2 and 3). The phase advance is a velocity and takes one factor of r through `TS_STEP` |
| `hz_bg` | **BG** — the `heathaze` rail's desert world AND its display shape: BG1's road-to-a-mesa picture (a four-step Bayer sky, eight sub-cell ridge profiles so the skyline is smooth rather than a comb, a bleached horizon strip, and a floor scattered by a hash rather than a modulus) plus BGMODE $09, BG1SC, BG12NBA and BG1VOFS. Vocabulary-native like `lake_bg`, and for the same reason — it designates bg1 and bg3 with `[[claims.screen]]`, so `bg_text` composes untouched. **`BG1VOFS` is deliberately NOT here**: on this rail that port belongs to whichever feature answers for it in the scene, `haze` in the desert and `hz_flat` on the title, because one is a seed under a transfer claim and the other is a plain owner and a feature cannot conditionally claim |
| `hz_flat` | **The composed UNDISTORTED state for `BG1VOFS`, as a claim** — `blend_off`'s shape on a register that is not the blender, and the generalisation this rail paid for. `haze` drives `BG1VOFS` per scanline, so at a scene edge the port holds whatever the last scanline left in it; a successor composing no `BG1VOFS` claimant writes nothing and inherits a displaced world. Compose this into a non-shimmering scene and that scene owns the port, gets the symbol emitted, and establishes the flat base on enter. **An HDMA-driven register needs the same per-scene disarm discipline the blender does** — colour math was never special, it was the first port anyone noticed it on |
| `hz_rom` | `hz_bg` + `haze` — four blobs from `tools/gen_haze_assets.py`: the 31-tile 4bpp CHR, the 1,024-word tilemap, the sixteen-word palette group 0 (word 0 included: it is also the backdrop and the sky's top step), and the 8,448-byte warp table — 32 phases plus one all-zero control at a 256 B stride. The warp blob is the biggest thing in the rail and it is what buys the effect: holding every phase resident trades 8 KB of the one budget with room to spare for ~1,700 CPU cycles a frame that would otherwise go on rebuilding a picture already in ROM. The control is a COMPLETE table rather than a disarm, so the before/after pair differs in the table and in nothing else |
| `lake_rom` | `lake_bg` — three blobs from `tools/gen_lakeside_assets.py`: the 26-tile 4bpp CHR (sky, two ridge profiles, beach, six coast profiles, the bed and its clusters), the 1,024-word tilemap and the sixteen-word palette group 0 (word 0 included: it is also the backdrop slot). The map is a BLOB rather than a build loop — `scroller_rom` argues the opposite and is right for its rail, where the loop is the lesson; here the world's job is to be a KNOWN main-screen operand, so it is authored byte for byte and the test compares uploaded VRAM against the source bytes |
| `m7_affine` | **M7-affine's matrix half** — the static rotation matrix itself: a build-time 256-entry heading→matrix LUT, the sixteen-byte DP shadow (M7A–M7D + M7X/M7Y + M7HOFS/M7VOFS), and the NMI-hook commit that latches all eight ports together. No HDMA channel, no runtime trig, no multiply. `mode7_floor` (or a rail's own floor feature) still supplies the plane; this is the half that was PARTIAL |
| `m7_barrel` | **THE BARREL-BOWED PER-SCANLINE MODE-7 MATRIX (#18)** — `mode7_chamber`'s new engine feature, and its design question decided: SuperForge's matrix stream is ROM-resident and INDIRECT, so a *per-frame overwrite of a live solve* becomes a **baked ROM column set with a runtime axis**. Two INDIRECT channels, DMAP **mode 2** (one write-twice register, 2 B/line): M7A carries a raised-cosine BOW selected by a pad-driven step, M7D the perspective hyperbola. M7B/M7C are declared and CPU-written once at enter — the angle is constant, so streaming them would be zeroes into registers that already hold zero. The camera origin rides a DP shadow the NMI hook commits, which is what turns the vertical roll into apparent rotation for one 16-bit add a frame. **Not a `mode7_persp` parameterisation** (four of four differ: a BOW axis vs a HEADING axis, an A column independent of the perspective scale vs `S(k)·cos h`, a blob bound by name, and mode 2 vs mode 3) — composing `mode7_persp` is ACCEPTED by the allocator and renders microzero's un-bowed floor at +127,232 B of ROM, the class for the eighth wave running. **Not `m7_affine`** either: one uniform matrix per frame cannot express a per-scanline bow, and it REFUSES against `mb_origin` first |
| `m7_persp_project` | **World→screen projection on a PER-SCANLINE Mode 7 plane** — the inverse of what `sh2_cam`'s matrix channels stream. `m7_project` cannot serve it: that one inverts a UNIFORM rotation by transpose, and this plane's matrix changes every scanline, so the inverse is taken against the RAMP — a build-time `sp_vk` LUT maps forward distance to band-local row and a reciprocal table turns the lateral into screen x. Sign/magnitude split so every rotation product is an 8×8 HARDWARE multiply (the `ALU` claim, which `m7_project` deliberately declined for twelve products a frame); a Chebyshev pre-cull with NO multiplies runs first, then the v dot, then the v/d/k/seam culls, and only survivors pay for the u dot |
| `m7_project` | **World→screen projection on a static-affine plane** — the INVERSE of the PPU's screen→texel matrix, which at a fixed scale is its TRANSPOSE, so the same four coefficients read as (A,C) for x and (B,D) for y. A world-space comparisons-only pre-cull (rotation preserves distance, so a point outside the padded view's circumradius is off-screen at every heading) rejects before any arithmetic; survivors go through a software shift-add signed 16×16 sized to the operands. No `alu` claim and no hardware multiplier. Reusable: needs the same map |
| `m7_track` | **THE MATRIX-TRACK MECHANISM** — the frame-indexed Mode 7 matrix-track player: `M7T_BIND` stamps a track blob's 24-bit base (pool_ptr's shape) and `m7t_apply` clamps an entry index against the blob's own count header, reads the two baked words, derives the other two by the uniform-scale identity (M7C = −M7B negated AFTER the floor shift, M7D = M7A) and writes `m7_affine`'s DP shadow — so the NMI commit that feature already owns latches the ramped matrix tear-free, and `m7_affine` itself is untouched. The player holds no cursor: the CONSUMER indexes (a state timer's complement for a ramp, a masked heading byte for a ring), which is what lets one scene hold four tracks for four stamps and one 4-byte claim. Track DATA is per-rail `rom` with provenance in the rail's generator. Debuts on `boss`; `boss_saucer` and `meteor_event` inherit it unchanged — the feature.toml carries the format, the seam-assert discipline and the ring-capture idiom for ramps entered from a free heading |
| `m7c_floor` | **M7 plane (#18)** — the `mode7_chamber` rail's own floor: the pinned interleaved Mode 7 region, a six-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot, and it is what the Mode-1 band above the seam actually shows), one mode-1 DMA that streams the interleaved blob straight in, and M7SEL selecting the 128×128 wrapping playfield that makes the vertical roll seamless. Static — it never scrolls, rotates or streams, so it holds no channel; everything per-scanline on this rail belongs to `m7_barrel`, `split_band` and `rgb_gradient`. A SIBLING of `m7dg_floor`/`sh2_floor`/`shp_floor`/`m7x_floor` for the reason `shp_floor`'s header states generally: a feature here cannot take a blob as a parameter. **Not `mode7_floor`** — that depends on `world_rom` (256 KB this rail never reads, measured at +262,946 B) and pins CGRAM 0..16 for microzero's palette against this rail's six |
| `m7c_roll` | **game_logic** (#18) — the `mode7_chamber` rail's whole motion model, and it is NOT a rotation: the angle is constant and the floor TEXTURE rolls vertically through m7_barrel's static bow, so the apparent rotation IS the scroll. The roll runs in LEGS of three surges — rise by ACCEL to a randomised peak, touch it for one frame, fall four times faster to a creep — then a dead stop, then a REVERSE leg whose peaks come from a SECOND LFSR so the two directions do not replay each other. Per-frame cost is one 24-bit add and four DP stores; nothing rebuilds a matrix, because there is no solve to rebuild. The three-state cycle is also the rail's test surface: forward AND reverse AND idle, driven deterministically by the rail itself on absolute frames, with no pad |
| `m7c_rom` | `m7c_floor` — the interleaved 32 KB ashlar-stone chamber plane (a two-tone block checker with mortar relief and full-width brass ribs every 8 tiles: the ribs are the MOTION CUE, since they bow with the barrel and ride up and down with the roll) and its six-word palette, in which word 4 duplicates word 0 by construction because index 0 is reserved as the backdrop. `tools/gen_chamber_assets.py` authors both procedurally and REFUSES to emit anything that disagrees with `vendor/art/mode7_chamber/`'s vendored oracles, or anything at all if either is absent — `gen_split_h_persp_assets.py`'s shape |
| `m7dg_floor` | **M7 plane** — the `m7_dungeon` rail's own floor: the pinned interleaved Mode 7 region, a nine-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. A SIBLING of `mode7_floor`, not a reuse of it — that feature depends on `world_rom` and streams a position-wrapped window out of a 512x512 world |
| `m7dg_obj` | **The `m7_dungeon` rail's cast** — hero, three enemies, the win card's three stars. The hero is PINNED at (120,104) because `m7a_set_center` holds the pivot at screen centre at every heading; everything else is projected through `m7_project` each frame, so an enemy stays on its own floor tile while the floor turns. Eight OAM slots for seven sprites, so both hi-table bytes have one owner and can be rebuilt whole; OBSEL is claimed here, as on every other rail's OBJ feature |
| `m7dg_rom` | `m7dg_floor` — the interleaved 32 KB Mode 7 image and the nine-word palette, byte-identical to the vendored reference conversion (`tools/gen_m7_dungeon_assets.py` refuses to emit anything else); `m7dg_obj` — the three 18-tile OBJ sheets and their 16-word palettes, likewise byte-identical |
| `m7f_cam` | **THE ALTITUDE AXIS — a bounded-but-unpurchasable domain, FACTORED** — `mode7_flight`'s per-scanline Mode 7 camera, and the one net-new mechanism in the later rails's last rail. Its pose domain is 256 headings &times; 81 altitudes = 20,736, both axes free and player-driven, and the faithful product table is **12.7 MB** against a 512 KB ceiling — so "small and bounded vs unbounded" has a third case and the LUT-SEP settles it: BAKE THE FACTORS, JOIN PER FRAME. `pose(h,a)[k] = S_a(k)&middot;R(h)`, so heading enters only through (cos, sin) and altitude only through the scale profile; `m7f_rom` holds both at 28 KB, exact on both axes. The join is TWO hardware multiplies per scanline (C = &minus;B and D = A are a negate and a copy), the trig signs hoisted into four loop variants chosen once a frame, into a DOUBLE-BUFFERED WRAM band table two **DIRECT** mode-3 channels stream — direct because the data is composed live, where `mode7_persp`/`sh2_cam` are indirect because theirs is ROM-resident and only a pointer moves. **Not a `mode7_persp` parameterisation** (five differ: its hard binding to `pose_rom`'s symbols, 180 lines at a 1024 B stride, a head-skip keyed on HUD_LINES, INDIRECT vs DIRECT, and no altitude axis at all). Owns the `ALU` claim, so the rail's movement products live here too. Its own cost is a declared output region: an SLHV latch pair brackets the join every frame |
| `m7f_floor` | **M7 plane + the sky band** — `mode7_flight`'s overworld: the pinned interleaved Mode 7 region, a sixteen-word absolute palette at CGRAM 0 (**word 0 is the SKY** — it is the backdrop the split reveals, and the generator asserts no floor CHR byte is 0), one mode-1 DMA that streams the interleaved blob straight in, M7SEL's screen-over wrap, and the scene's BGMODE/TM. The **NINTH** instance of the `m7dg_floor` sibling ruling. The sky is a one-channel two-band TM split that turns BG1 OFF above the horizon — `sky_band` cannot serve it (a BG2 texture behind a Mode-1 HUD band, costing no channel), because Mode 7 has one background and the sky is its absence |
| `m7f_logic` | **The flight model** — `mode7_flight`'s four axes: heading &plusmn;1 of 256 per held frame, a SIGNED 8.8 throttle (B forward, Y reverse, release hovers — one integrator for all three because the sign carries it), and altitude &plusmn;1 index per held frame clamped at both ends so the rail has no fail state. Holds no state of its own: every word it writes is `m7f_cam`'s pose claim, and the position integrator it calls lives there too because the ALU is WHOLE and that feature owns it |
| `m7f_obj` | **The flight rail's cast** — an airship and its ground shadow, both at a FIXED screen position: the world moves, the ship does not. The shadow is the rail's ALTIMETER and the only altitude readout it has (Mode 7 has one layer and the plane is using it, so there is no tilemap for a HUD) — its tile, its hardware size bit, its screen x and its screen y all track the altitude together down a **FIVE-RUNG LADDER**, which is what makes "the ship climbed" an OAM assertion rather than a variable read. FIVE steps out of the two sizes OBSEL carries, because apparent size is the ART inside the box and not the box: two drawn ellipses in the 32 box, three in the 16 one, 26/20/14/10/6 px wide. Each rung's screen x is `128 - box/2` and its y base the centre locus minus `box/2`, so the ellipse's centre stays on the airship's column and on one continuous line down the screen — one shared x served both boxes before the ladder and put the 16 px shadow eight pixels left of the ship. Four OAM slots for the two, so the first hi-table byte has one owner and is rebuilt whole; four more for the CLOUDS, which carry **OBJ priority 0** — the one rank BG1 draws over in BGMODE 7 — so the ground occludes them and a climb uncovers a cloud row by row instead of the hard cull that popped a whole one into place in a frame. OBSEL is claimed here, and on this rail it is load-bearing rather than routine |
| `m7f_rom` | **The two POSE FACTORS, plus the flight rail's art** — 25,920 B of per-altitude scale profiles (81 levels &times; 160 band lines &times; 2 B, one 32 KB window so no profile straddles a bank), 2,048 B of 256-heading trig, the 32 KB interleaved plane, one 4-row&times;16-col OBJ sheet and three palettes. The profile byte is `min(255, S/4)`, which reproduces an 8-bit reciprocal-LUT clamp EXACTLY — the horizon coefficient saturating above alt ~213 of 240 — by construction rather than as a special case. Everything authored, nothing converted from a source `.bin`: no converter, so no ground-truth obligation to discharge |
| `m7x_floor` | **M7 plane** — the `mode7_explore` rail's own floor: the pinned interleaved Mode 7 region, a twelve-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot), one mode-1 DMA that streams the interleaved seed straight in, and the scene's BGMODE/TM/M7SEL. A SIBLING of `m7dg_floor` and of `mode7_floor` for the ruling those two record — the plane is per-rail because the blob and the palette are. What is NEW here against `m7dg_floor` is that this plane STREAMS: the seed is the initial 128×128 window and `mode7_stream` replaces its rows and columns as the camera walks, which costs this feature nothing (only tilemap LOW bytes stream; the CHR half of the region is never rewritten after the upload) |
| `m7x_logic` | **The `mode7_explore` rail's walk machine** — grid movement on an 8 px tile step animated over 8 frames at 1 px/frame, D-pad priority L→R→U→D **with fall-through on a blocked axis** (so a held diagonal keeps moving along the open axis instead of freezing against a wall), facing latched even when the step is rejected, camera clamped to `[64, 447]` on both axes so the 128-tile window never crosses the world's toroidal seam, and blocking read through `col_map` as a contiguous terrain-class range (water..mountain). It also DECLARES `ES_M7ORG` — the camera-origin shadow `mode7_stream` still reads by name after the blob retrofit — because this rail cannot compose `mode7_persp`, whose HDMA claims own M7A–M7D that `m7_affine` CPU-writes |
| `m7x_obj` | **The `mode7_explore` rail's avatar** — one 16×16 sprite, PINNED at screen centre because `m7a_set_center` holds the affine pivot there and on this rail the avatar *is* the camera, so no projection is composed at all. Three authored facings on the PPU's {N, N+1, N+16, N+17} quad grid (DOWN 16, UP 18, SIDE 20) with LEFT as SIDE H-flipped through the free OAM attribute bit; four OAM slots for the one sprite so the hi-table byte has a single owner and can be rebuilt whole; OBSEL claimed here, as on every other rail's OBJ feature |
| `m7x_rom` | **the `mode7_explore` rail's world** — a 512x512-tile (4096x4096 px) Mode 7 streaming overworld and its Mode 1 town interior: the 256 KB bank-tiled flat tilemap `mode7_stream` walks, the 32 KB interleaved VRAM seed the floor uploads once, the 12-word absolute palette (word 0 included: it is also the backdrop slot, and this rail's tile 0 is opaque grass because a flat top-down view has no horizon showing through), the avatar's three-facing OBJ sheet, and the interior's four tiles. **The tilemap is the SINGLE SOURCE OF TRUTH for terrain** — collision reads a byte of it and LUTs it through the 256-byte `m7x_terr` rather than consulting a second 256 KB table, which is both what fits in a 512 KB ROM and what stops "what you see" drifting from "what blocks you". Named `m7x_map`, not `world_map`: that family is `world_rom`'s, and `mode7_stream` binds a rail's blob through `ES_R_*` symbols, so two rails claiming one name is a real collision. All eight claims are BACKED as of the rail slice — `game/mode7_explore/main.asm` carries the `.incbin` sites (the map as a `.repeat ES_R_M7X_MAP_CHUNKS` template, the other seven plain), and `make rom-unbacked` walks them as part of that composition's translation unit. The two town blobs are backed NOW though this slice never reads them, so the town slice inherits a placed, asserted blob instead of renegotiating the packer's answer for every other claim in the window |
| `m7x_town` | **The `mode7_explore` rail's Mode 1 town interior** — the room the gallery row's mosaic wipe carries Elnora into, and the whole of it in one feature: BG1's layer configuration, the room geometry, the collision, the edge-triggered walk and the avatar's OAM entry. `town_classify` is the single source of truth for what is DRAWN and what BLOCKS, and the class value **is** the BG1 tile id (FLOOR 0 / WALL 1 / DOOR 2 / TABLE 3), so the rendered tilemap and the collision test cannot drift — there is no second table. Its VRAM is **pinned** into upper VRAM (CHR word `$5000`, tilemap `$5800`) rather than packed, which is what keeps the Mode 7 image at `$0000-$3FFF` and the avatar's OBJ CHR at `$4000` standing across the visit: the return re-stages 24 B of palette and re-streams **nothing**. It deliberately does NOT claim `BG1HOFS`/`BG1VOFS` — `m7_affine` is global on this rail and commits those two ports every frame in every scene, so the interior pins its fixed camera *through* that owned API (`m7a_set_center` at the pivot `(128,112)`, for which the routine's two subtractions give `HOFS = VOFS = 0`) instead of contending for them |
| `maze_bg` | **BG** — the `maze` rail's walled room on BG1, and the first BG feature whose tilemap is RENDERED FROM col_map's OWN WORLD BLOB: the enter loop reads `mz_room`'s 1024 tile-id bytes and writes each straight to VMDATA, so the wall you see and the wall that blocks are one byte. Scroll pinned at enter with pfs_bg's measured VOFS −1, `room_bg`'s way, because the room is one screen — so world y = screen y = OAM y and the wall-stop coordinates are the same numbers in all three surfaces. Owns CGRAM word 0 (at palette group 0 that word IS the backdrop slot) |
| `maze_obj` | the `maze` rail's red 8×8 player, staged into the `oam_sprites` shadow every frame FROM THE POSITION THE COLLISION DECIDED — US_PX/US_PY bound through MZO_PX/MZO_PY aliases (the m7dg_obj binding pattern), so the sprite and the wall probe cannot disagree about where the player is. X9 derived from bit 8 of X per frame rather than assumed clear. SPR consumer |
| `maze_rom` | `maze_bg` + `maze_obj` + `col_map` — six blobs from `tools/gen_maze_assets.py`, and the load-bearing one is `mz_room`: the 32×32 byte tile-id map of the hand-built room (border + two interior walls, authored by four loops at build time rather than baked as a bitmap), which is BOTH the BG render source and col_map's bound world. Plus the 256-entry flag table (tile 2 = SOLID, `sf_tile_flags 2` as data), 3 BG tiles, 1 OBJ tile, 2 palettes |
| `met_bg` | **BG** — the `meteor_event` rail's Mode-1 platformer slice: a flat green ground band (BG rows 24..27) and two raised platforms, painted into a 32×32 BG1 **tilemap shadow in WRAM** that one enter DMA pushes to VRAM. That shadow is the load-bearing part — it is what the BG→OBJ capture READS, so the sprites the capture emits are derived from the bytes the PPU is actually fetching rather than from an author-time guess. Its CHR and tilemap are **pinned above the Mode 7 region** (`$5000`/`$4800`, m7x_town's route), so the swap to the cutscene never clobbers them and the return needs no restore code — the alternative is re-uploading both purely to undo a clobber the allocator can declare away. Owns CGRAM word 0 and deliberately does NOT claim `BG1HOFS`: `m7_affine` is global here and commits that port every frame in both scenes, so the camera rides its shadow |
| `met_floor` | **M7 plane** — the `meteor_event` cutscene's meteor plane: the pinned interleaved Mode 7 region, a sixteen-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot, and the night sky there is what the OFF-FIELD park during the sprite phase actually shows), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL — M7SEL bit 7 set, so outside the 1024-px field shows BACKDROP instead of wrapping the meteor back into view. The NINTH instance of the `m7dg_floor` sibling ruling. No `hdma` claim: the zoom, the slide and the tumble are one uniform matrix per frame plus two origin words |
| `met_glow` | **The red impact glow** — one active-display HDMA channel streaming the R plane of COLDATA from a seventeen-byte WRAM table, plus the colour-math mode (`CGWSEL`/`CGADSUB`) that reaches backdrop + BG1 and EXCLUDES OBJ so the captured ground and the player are not stained red. Eight band entries in the HDMA **non-repeat pause** shape rather than 224 per-line bytes (AGENTS.md's cycle note), and the table is rebuilt only when the QUANTISED intensity changes — measured: an unconditional per-frame rebuild runs the scene at ~1/3 speed. **Not `rgb_gradient`**: that feature streams three STATIC ROM tables over a fixed band geometry, and a static wash cannot rise and recede |
| `met_obj` | **The `meteor_event` rail's whole OBJ cast, and the declared bound on the capture** — the player, the far-approach meteor sprite, and up to forty captured BG blocks. GLOBAL rather than scene-scoped because the cast SPANS THE SWAP (mosaic's reason in mode7_explore): the capture is written in the Mode-1 scene and composited over the Mode-7 meteor in the next one, so its CHR base, palette and slot identities must be the same resources on both sides. row 24 files this rail as "medium" because the capture's "OAM cost is bounded by nothing declared"; here it is `sprites = 40`, derived from the level's geometry (two full ground block-rows ≤17 each + two four-cell platforms ≤3 each) with the emit cursor compared against `ES_O_CAPTURE_SPRITES`, and the shipped path MEASURES 36 blocks (37 live sprites with the player). Written ONCE and left standing through the transition — SuperForge's OAM shadow is state, so a per-frame re-emit is not needed. OBSEL claimed here, size pair 3 (16×16 / 32×32) |
| `met_rom` | `met_floor` + `met_obj` + `met_bg` + `m7_track` — eight blobs from two generators. `tools/gen_meteor_assets.py` authors the 32 KB interleaved cratered-meteor plane, its sixteen-word palette, the 96-tile OBJ sheet (three 32×32 ROCKY frames, three 16×16 FIERY specks, the capture block, the player) and its palette, plus the level's four BG tiles and palette — all from shape predicates — first-party procedural authoring, so there is no converter to ground-truth. `tools/gen_meteor_tracks.py` bakes `met_grow`, the 109-entry matrix track that composes the `MET_SCALE_STEP` $0030 scale ramp with its +4/frame tumble, using the exact smul16 floor-shift arithmetic; entry 0 is the crossover pose the sprite phase holds, and the generator asserts both the ramp's clamp point and the entry-0 identity |
| `mil_bg` | **BG at TWO DIFFERENT DEPTHS, which is a first in this tree** — the `mill` rail's two layers under mode 4, where the PPU renders bg1 at 8bpp and bg2 at 2bpp. Smelter's mode 2 renders both at 4bpp, which is why ONE `smt_chr` claim serves both its layers; here that is impossible and the two CHR claims are 64 and 16 bytes a tile. Both name their `layers`, so **O9 joins each depth to the depth the scene's declared mode actually renders it at** — the check that did not exist until this rail needed it, and the one that turns "mode 4 beside a 32-byte-a-tile BG1 claim" from a green build into a refusal. The palettes carry the other half of the depth fact and it is not about the art: a 2bpp tilemap entry's palette field is three bits selecting one of eight groups of FOUR, so BG2 is PINNED to CGRAM 0..31 whatever else is on screen, while an 8bpp layer has no palette field and indexes CGRAM directly with the pixel value — so BG1's 64-word claim starts at 32 because of the DEPTHS, not because somebody chose it. Neither BGMODE nor any scroll port is here: the mode is a `[[claims.video]]` claim and the four scroll ports are `mil_opt`'s FALLBACK |
| `mil_obj` | **THE ONE THING OFFSET-PER-TILE CANNOT DO, and the reason mode 4's priority order is worth knowing.** A displaced column moves WHOLE and on an 8-pixel grid; the rider in the `mill` rail's elevator has to sit at a pixel position, at a different height from the column he is inside, and be OCCLUDED BY IT. So he is an OBJ — and the occlusion is FREE. Mode 4 renders BG2lo(1) · OBJ0(2) · BG1lo(3) · OBJ1(4) · BG2hi(5) · OBJ2(6) · BG1hi(7) · OBJ3(8) (SnesPpu.cpp RenderMode4, :824) and a sprite draws only where the pixel already there scores LOWER — `(_mainScreenFlags[x] & 0x0F) < spritePrio`, :958. **At OBJ priority 0 the rider scores 2: under BG1's 3, over BG2's 1.** The car's art is opaque everywhere except a hole cut where its glass is, so he is drawn through the hole and nowhere else, with no window register, no mask and not one per-scanline cycle — and the occlusion rides up the shaft with the car because it IS the car. Measured as an equality on the rendered frame: **0 rider pixels outside the glass and 1,665 inside, over the whole ride**, decidable from the picture alone because OBJ reads CGRAM 128..255 and `mil_bg`'s 8bpp ramps stop at 127 — which is what that budget was cut for before this feature existed. `smt_obj`'s knight is the same pack at priority 3 for the opposite reason: he has to be in front of everything. Two idle cells indexed by the rail's PHASE, one 32x32 OBJ, and the car's screen row DERIVED from the offset word (`SMIL_CAR_ROW*8 - camera - car`) rather than tracked beside it, so there is no second copy of the car's position to drift from the first |
| `mil_band` | **THE OFFSET TABLE READ IN BANDS, IN EVERY ROOM OF THE RAIL** — the PPU fetches the row `BG3VOFS` names (`rowOffset = VScroll >> 3`, SnesPpu.cpp:257-276), so an HDMA channel rewriting that one port per scanline hands each band of the picture its own 32 words. `mill` uses it for its FLOOR: both rooms stand on the same molten channel at the same screen rows and what is above it differs, so the lobby reads two rows (the room from a row with no enable bit, the channel from a RIPPLE row) and the hall three (its machines, the deck, the channel). **The hall's band edges MOVE** — its deck and channel are at fixed world rows and its camera climbs, so the channel band shrinks to nothing as the lift rises, which is the per-scanline claim seen as motion rather than as a static split; its table is rebuilt every VBlank from the camera, the lobby's is a constant built at enter. The declaration is `[[claims.offset_bands]] rows = 3`: the composition SYNTHESIZES the channel (`mil_bands_rowsel`: BG3VOFS, mode 2, active, the whole frame), assigns and emits it, and marks its own BG3VOFS ownership `seed`, so a second active channel on that port meets it as an ordinary HDMA register contention (O10) — the refusal a raw `seed` beside a raw hdma claim could not reach. It also carries the rail's hardest-won fact: **the scene_mgr HDMA shadow's `$430A` is what a channel starts a frame with**, so a slot seeded to a 127-line hold delayed every frame's first band to line 128 (the hall's machines stood still while their table advanced) and a slot seeded to 0 made the channel repeat-transfer and walk 433 bytes of never-written WRAM. Seeded to 1 — one line, then the first entry — both go away; measured three ways in `mil_band.asm` |
| `mil_mode` | **THE ROOM'S VIDEO MODE, ON ITS OWN** — mode 4 for both of `mill`'s scenes, and nothing else. It lived on `mil_opt` until 2026-09-04, because O3 demands a declared mode before an offset claim can be checked against one; splitting it says the truer thing, that the TABLE is a mechanism and the MODE is a property of the room, and it is what makes the rail's direct-colour variant a ONE-DECLARATION difference instead of a duplicated feature. The shipping ROM is byte-identical across the split (`mill.sfc` md5 unchanged): BGMODE composes from the same claim in the same scene union, so the emitted value and every placement are the same. |
| `mil_mode_dc` | **THE SAME MODE WITH `direct_color = true`, AND THAT IS THE WHOLE DIFFERENCE BETWEEN TWO ROMS.** `build/mill_direct.sfc` composes this one where `build/mill.sfc` composes `mil_mode`; every other claim on the rail is shared, and the two allocations are identical placement for placement (asserted by `tests/test_mill_direct.py::test_the_two_builds_allocate_one_map`). The field composes CGWSEL bit 0 — declared on the video claim because `GetRgbColor` acts on it under `bpp == 8 && directColorMode` alone (SnesPpu.cpp:1071), emitted by the screen/blend half because that is CGWSEL's one owner (docs/99 §4). With it set, BG1's 8bpp pixel IS its colour, 3-3-2, and **the tilemap entry's three-bit palette field supplies the low bit of each channel** (`(tilemapData >> 10) & 0x07`, :1023, folded in at :1071-1076) — three bits the indexed build explicitly ignores (":1077 Ignore palette bits for 256-color layers"), which this declaration makes load-bearing. The cost is stated rather than hidden: direct colour is ALL-OR-NOTHING for the layer, so `mil_bg`'s 96-word BG1 palette is still claimed, still uploaded, and never read — there is one CGWSEL bit and no per-region control without an HDMA channel on the port, which is why this is a second ROM and not a second region (docs/100 §14). Measured on the boot lobby: 29,792 BG1 pixels render the expression exactly, zero of them do so in the indexed build, and the two pictures sit a mean 7.6 eye-weighted units apart. |
| `mil_opt` | **MODE 4'S AXIS BIT** — the half offset-per-tile that `smt_opt` cannot reach. Modes 2 and 6 run `GetHorizontalOffsetByte` AND `GetVerticalOffsetByte` inside a column's group, so a column is displaced on both axes and the axis is not a choice; **mode 4 fetches ONE word and BIT 15 SELECTS ITS AXIS** (SnesPpu.cpp `FetchTileData` case 2 under BgMode 4, the bit-15 test at :156-161). So one 32-word row pumps a bay of pistons vertically and runs the next bay's belts sideways, for the same zero HDMA channels and the same 64 B in one VBlank transfer — and this rail uploads ONE row where smelter uploads a V row plus an all-zero H row it never uses. `axis = "both"` under mode 4 MEANS that, and it is a declaration the vocabulary REFUSED until this rail asked for it: O7 reasoned about a COLUMN (a mode-4 column does carry one axis, which is true) and rejected a claim about the TABLE. It is a warning now, because the same word means "both axes per column" one mode over. **TWO AXES FORCE TWO LAYERS**, which is the design consequence worth carrying: a displaced column moves WHOLE, so V displacement needs art identical row to row and H displacement shows the NEIGHBOURING TILE and needs one repeating texture across the map row — incompatible in one layer, so BG1 takes the pistons and BG2 the belts. Also the owner of the four fallback scrolls and of the phase the row index is chosen by |
| `mil_rom` | `mil_bg` + `mil_opt` — six blobs from `tools/gen_mill_assets.py`, now part-procedural and part CONVERTED FROM THE KIT (`vendor/art/forge_line`, docs/92 §5.1a — the sheets carry no pixel grid and are resampled through `tools/kit_import.py`, not sliced): the 256-tile 8bpp BG1 CHR page (16,384 B, 209 used — 64 bytes a tile, which is what 8bpp costs and why the budget that bought smelter fifteen tiles buys about sixty here), the 64-tile 2bpp BG2 page (1,024 B, 42 authored), two 2,048-byte 32x32 tilemaps, ONE 208-byte palette blob carrying BG1's 96 colours and BG2's two 4-colour groups at `SMIL_PAL2_OFF` (one blob and not two for smelter's reason: the uploader reaches the second group by an offset from the first base symbol, and two claims are two blobs the packer orders by SIZE — a signed distance whose sign is not this file's to decide), and the 8,256-byte row table: 128 complete mode-4 offset rows plus a flat CONTROL at a 64 B stride. **THE ONE-COLUMN FETCH LEAD IS BAKED INTO THIS BLOB**, and it is the defect the rail shipped: offset words are fetched AFTER a column's tilemap data, so the word at index j displaces SCREEN column j+1. Smelter pays this at the read head because its table is world-space and scrolls; this one is screen-space and does not, so `row_table()` applies it and `SMIL_LEAD` is emitted for the ASM and the tests. Without it every group of columns had its FIRST member driven by the previous group's word — the leftmost column of each piston bay held still while three beside it pumped, and the first column of each belt was handed a piston's word and stopped running. A human saw it in the clip before any test did. Its companion is `T1_PILLAR`, the sixth BG1 tile: screen column 0 takes no word at all (the PPU clears the latches per scanline fetch), so it is drawn as the hall's masonry buttress rather than as a machine that never moves, and the 31 displaceable columns left over are why the rightmost bay's belt is three wide and the hall runs off the edge mid-bay. The control row is a complete row with every value at rest AND EVERY ENABLE BIT AND EVERY AXIS BIT STILL SET, so the flat picture and the moving one differ in the table and in nothing else |
| `mil_tint` | **A COLOUR WINDOW OVER ONE SHAFT, FOR ZERO CHANNELS** — and the reason it is free is a property of this rail rather than of the effect. Colour math is a per-LAYER enable and otherwise global, so `math = ["bg2"]` alone would tint the whole far wall; what makes it LOCAL is the colour window, whose bounds are WH0/WH1 — screen X positions. The `mill` rail's lift shaft does not move horizontally, so those are constants written ONCE at enter: no HDMA channel, nothing on the per-frame budget. A shaft that panned would want the bounds per scanline and that is a channel, which is the honest limit on the trick. **WOBJSEL bit 5 is what gates window 1 onto the colour window at all** — `ProcessWindowMaskSettings(value, 4)` writes layer index 4 = OBJ and index 5 = the COLOUR window (SnesPpu.cpp:1487-1495), so this is not a layer mask and the OBJ mask stays off. Tints BG2 and not the rider, because "the inside space" is what shows THROUGH the car's glass and the glass is a hole in BG1: the rider keeps his own colour and the read is light in the shaft rather than a blue man. The alternative was priced and refused — colour math on OBJ applies only to sprites on **palettes 4-7** (`_spritePalette[x] > 3`, :962), so tinting him would move him off palette 0 for a worse picture. Measured as an A/B against the same rail built with the added colour at zero: **747 pixels changed, every one of them inside the window's four columns, zero outside** — which settles the polarity of CGWSEL's `prevent` field (whose vocabulary names are not the hardware's numbers) and the containment in one measurement rather than by reasoning about either |
| `mo_floor` | **M7 plane** — the `m7_oshoot` rail's arena: the pinned interleaved Mode 7 region, a ten-word absolute palette at CGRAM 0 (word 0 included, because in Mode 7 it is both palette index 0 and the backdrop slot — nine authored tones plus `reserve_backdrop`'s duplicate of the dark floor tone into word 0), one mode-1 DMA that streams the interleaved blob straight in, and the scene's M7SEL. The SIXTH instance of the `m7dg_floor` ruling (`rs_floor`, `sh2_floor`, `shm_floor`, `m7x_floor` are the others) — and the first where the nearest sibling is not `mode7_floor` but `m7dg_floor` itself, which is mechanism-identical and still cannot serve because it `depends = ["m7dg_rom"]` and resolves that blob's symbols by name. Claims **no `hdma`**: the whole rail is one uniform matrix per frame, which is's measured reason this rail is the cheap one |
| `mo_obj` | **the cast on the spinning floor, and POOL's SECOND generic consumer** — `m7_oshoot`'s hero, six pooled wave-chasers and eight pooled bullets: sixteen slots = four whole hi-table bytes rebuilt every frame, `obj = true` CHR floored past the Mode 7 region with the OBSEL base emitted. The hero does NOT project (the pivot pins him at screen centre by construction, so his screen position is a constant); everything else goes through `m7_project`'s transpose against a pivot that **moves every frame**, which is the stress row 20 names and `m7_dungeon` does not have. Holds both pools' storage in one `mo_actors` `wram` claim at documented offsets — `rs_obj`'s shape, which is the shape `pool.asm`'s binding contract is written against — while the rail's driver stays in the scene asm (`m7_dungeon`'s split, not `railshooter`'s `rs_logic`). Bullets draw with the ENEMY CHR under a third OBJ palette, so a rendered bullet is identified by its colour: the reference rail's own decision, and what its oracle asserts |
| `mo_rom` | `mo_floor` + `mo_obj` + `col_map` — nine blobs from `tools/gen_m7_oshoot_assets.py`: the interleaved 32 KB arena plane and its ten-word palette (`mo_pal.bin`, 20 B), the packed 16 KB tile-id map col_map reads with its 256-entry flag table, and two 18-tile OBJ sheets with three OBJ palettes. The load-bearing property is that ONE wall predicate produces both the painted tile and the collision flag, so the "what you see is what blocks you" invariant holds by construction and is asserted in the generator. All authored, nothing imported — so there is no converter between a source asset and the ROM, and therefore no converter to ground-truth (`mode7_explore`'s route) |
| `mode7_floor` | M7; M7-affine's plane half |
| `mode7_persp` | M7-persp |
| `mode7_stream` | STREAM |
| `mosaic` | **The pixelate-to-black scene wipe** — a symmetric 20-frame OUT / 15-frame IN dissolve that fires a caller-supplied swap routine at peak black, with mosaic size locked to `15 - brightness` so a clean image and a black one are the two ends of one curve. Owns `MOSAIC` ($2106) outright and a seven-byte DP state block; drives brightness through scene_mgr's INIDISP shadow the way `fade` does, and claims no register for it. It deliberately does NOT own `TM`: an OBJ drop inside the wipe is refused here by `check_reg_ownership`'s reg×reg pass against every BG feature in the tree, and is defeated anyway on an HDMA-TM Mode 7 scene — so hiding OBJ is a stated caller contract, gated on the `mosaic_active` query. See the feature.toml header |
| `oam_sprites` | SPR |
| `patrol_bg` | **BG** — the `patrol` rail's terrain: a 32×28 walled level (ground, side borders, two jumpable low walls, a floating platform), the seventh instance of the keystone BG pattern. What is specific to it: the tilemap is **rendered at enter from the `pat_map` blob** rather than built from an expression (maze's shape — the same 1,024 bytes are col_map's world, so the picture and the collision cannot drift), and the scroll is **pinned at enter with the VOFS −1** (maze's rule: world y = screen y = OAM y, so a wall-stop or beat-bound coordinate is the same number in the map, the picture and the OAM byte). Owns CGRAM word 0 (at palette group 0 that word IS the backdrop slot) |
| `patrol_obj` | the `patrol` rail's three actors — the red player and BOTH magenta patrollers — one 8×8 OBJ each from ONE shared tile in two OBJ palettes (all three draw tile #1, attr $00 vs $02). Player pinned at OAM 0, enemies at 1..2, so a test reads an entry and says which actor it is; claims the hi-table byte's fourth slot as pad and REBUILDS the byte from the three X values every frame (`hud_obj`'s argument, one slot bigger). SPR consumer |
| `patrol_rom` | `patrol_bg` + `patrol_obj` + the play scene's col_map binding — six blobs from `tools/gen_patrol_assets.py`: two tile tables stated twice and checked against each other, three colours across two palettes, and the LEVEL as data (`pat_map`, authored by four mset loops; `pat_flags`, `sf_tile_flags 2, SOLID` as a 256-entry table) — the one-source-two-consumers shape maze established |
| `pfs_bg` | **BG** — the `platformer_stream` level layer, and the first BG feature in the set whose tilemap is a RING rather than a picture: a 64x64 map (four 32x32 hardware pages, which is why the claim is 0x1000 words and not 0x400) that `pfs_stream` slides over a world sixteen times its area. Owns the layer — BGMODE/TM/TS/BG1SC/BG12NBA, the CHR page, the 16-word palette, and the two-axis DP camera the NMI hook commits to BG1HOFS *and* BG1VOFS — while `pfs_stream` owns the contents. Also owns CGRAM word 0, both because `backdrop` cannot compose with a BG feature and because at palette group 0 that word IS the backdrop slot. The rail's only layer: the open sky is the backdrop under `rgb_gradient`'s dusk ramp, not a BG2 |
| `pfs_logic` | the `platformer_stream` player — walk, variable-height jump, and the **16-bit world-Y** integrator that is the point of it: the level is 1024 px tall and the spawn fall crosses about five screens in one continuous arc, so position is a 16.8 split rather than the 8-bit screen Y every prior platformer here integrates. Its collision probes ask `col_map` about a WORLD tile coordinate, never about the ring, so what blocks the player is the true level geometry and not whatever window is resident |
| `pfs_rom` | `pfs_bg` + `pfs_stream` + `pfs_logic` — the `platformer_stream` world. The 128x128 tilemap is claimed TWICE, column-major and row-major, because a 2-axis streamer's two inner loops want opposite orders and each copy is exactly one 32 KB LoROM window so neither producer's source pointer crosses a bank seam. Plus the 16 KB world-space collision table (`col_map`'s blob) and its flag LUT, the Four Seasons CHR and palette (vendored — quantized from a vendored tileset image), and the hero, which needed no vendoring at all:'s `vendor/art/dungeon_sprites/ref_hero.inc` is byte-identical to this rail's |
| `pfs_stream` | **STREAM, normal-BG 2-axis** — row 5, closed, and a SIBLING of `mode7_stream` rather than a binding of it: Mode 7 writes a flat byte array with one linear address space, a normal-BG 64x64 ring is four word pages, so every staged line crosses a page boundary on both axes. Collapses two unlike producers onto ONE staging shape — stage into a 64-word slot buffer indexed by ring slot, then two 32-word page-aligned sub-transfers — after which the axes differ only in the VMAIN increment (stride 32 for columns, stride 1 for rows). Costs one extra 128-byte copy per streamed column and removes an entire second producer |
| `platformer_bg` | **BG + PARALLAX** — the `platformer` 512×224 level on BG1 *and* the two-band parallax skyline on BG2, in ONE feature: this rail is the exact composition F-A measured as refused, so the two layers cannot be authored apart. Shares one CHR page and one 16-colour palette between them. **PARALLAX's first instance** — one mode-2 direct HDMA channel over a 16-byte WRAM table of three HDMA non-repeat-pause entries, not a 224-entry per-scanline fill, with power-of-two band ratios so the rebuild needs no `ALU` claim. Also owns the DP camera the NMI hook commits to BG1HOFS, the coin-pickup VBlank cell queue, the collected-coin bitmap, and CGRAM word 0 (`backdrop` cannot compose with a BG feature) |
| `platformer_obj` | `platformer`'s hero and two patrol ghosts; SPR consumer. Claims FOUR OAM slots for three actors, so the hi-table byte (4 sprites × 2 bits) has one owner and can be rebuilt whole rather than read-modify-written — the fourth is parked for the ROM's life and the claim exists to make that ownership checkable |
| `platformer_rom` | `platformer_bg` + `platformer_obj` — art, palettes, and the level itself as immutable ROM. The ACTORS are imported from the vendored dungeonSprites pack (`vendor/art/dungeon_sprites/`), two 16-aligned 32-tile OBJ pages 32 apart; the level and skyline tiles are hand-authored, because no pack ships this rail's geometry |
| `player_car` | consumes `oam_sprites` + `car_rom`; supplies no demand term |
| `pool` | **POOL** — fixed-slot actor pools as a REUSABLE mechanism: `pool_init` / `pool_spawn` / `pool_kill` / `pool_count` over an `alive[]` array whose 24-bit base the caller stamps into this feature's ONE 4-byte DP claim. **All four ship, each with a live caller and a falsification plant** — `pool_count` answers the live count in A and is driven by `rs_pool_census`, the reference rail's own two-count-per-frame mirror, re-expressed as declared state. **This implementation has four behavioural deltas from the obvious macro form** — the routines require A16/I16 where the macros self-narrowed with `rep #$30`, `pool_kill` does not preserve A, the slot count is an unenforced runtime argument rather than a compile-time `.assert`, and `pool_spawn` leaves a different X on the full path; the table is in `pool.asm`'s header and in and the width one is silent-corruption class. **It claims the mechanism and nothing else — the CONSUMER claims the arrays**, because a pool's slot count, field set and multiplicity are all game vocabulary. That split is what lets one scene hold TWO pools (`railshooter`'s obstacles + bullets) for the price of two base stamps, and it is the contract `m7_oshoot`, `boss` and `boss_saucer` build against next — four templates, the largest shared gap remaining. NOT a sibling pair (`input`/`input2` exists for a MEASURED reason — a claim on `input` moved microzero's pinned md5 — and `pool` is composed by no pinned game), and NOT `shmup_obj`'s fold-into-the-sprite-feature shape: folded because *"pool slot k is ALWAYS OAM slot k"* was the coupling, and `railshooter`'s depth-ordered obstacle emit makes that false. Costs `[dp],y` (7 cycles) plus a ~10-cycle base stamp per CALL against `shmup`'s 5-cycle `long,x` — amortised over a scan, and the per-slot game loops are unchanged |
| `pose_rom` | `mode7_persp` |
| `race_logic` | microzero's physics + lap machine; not engine |
| `rc_grad` | **A COLDATA WASH WITH A TIME AXIS** — `racer`'s day-night cycle, and the answer to the one thing `rgb_gradient` structurally cannot do. Same three active indirect channels, one COLDATA plane each; the difference is WHERE THE HEADER TABLES LIVE. `rgb_gradient` assembles `rg_tab_r/g/b` into the CODE BANK pointing at one static blob ("fixed camera height -> fixed band geometry, no fog dynamics"), so there is no writable surface at all — composing it renders one wash at every hour of this rail's day. `rc_grad` moves the three tables to a 24-B WRAM claim and puts EIGHT keyframes behind them, retargeting the data pointers at keyframe *k* — `mode7_persp`'s `persp_set_pose` shape applied to COLDATA instead of M7A-M7D. **Not a `rgb_gradient` parameterisation, and the two REFUSE together** on `COLDATA_B` register contention, which is the declaration doing its job. The alternative is rebuilding three 225-entry tables in place every eighth frame and pacing the perspective work around the cost; a retarget is six stores. Also owns the colour-math mode (CGWSEL/CGADSUB), so a scene composing it gets CM declared by composition |
| `rc_kart` | **OBJ OVER MODE 7, WITH THE HUD IN IT** — `racer`'s whole visible foreground: a screen-fixed kart with a straight frame and a lean frame, plus a six-tick sprite speed bar at y=16 in the sky band. The HUD is sprites because **BG3 does not exist in Mode 7** — so this is the rail that proves the OBJ path carries a HUD without a text renderer. The Mode-7 map owns VRAM words `$0000-$3FFF` wholesale, so the `obj = true` CHR claim makes the allocator floor the base past it and emit the OBSEL encoding: the "OBJ-OVER-MODE-7 GOTCHA" discharged by declaration rather than by a hand-narrated mask. Eight slots claimed for seven drawn (whole hi-table bytes, `hud_obj`'s argument). **Refuses beside `player_car`** — and one resource EARLIER than expected, on CGRAM `[128..144)`, because OBJ palette 0 is a hardware-fixed window with one owner |
| `rc_logic` | `racer`'s throttle / steer / integrate / off-road kernel; not engine. A different physics model from `race_logic`, not a fork of it: accelerate toward a cap while B is held, coast to a FULL stop when it is not, and bleed hard toward the crawl speed while `col_map` says the tile under the kart is grass — no brake, no reverse, no laps. Cutting the circuit costs time instead of a lap count. The one claim genuinely shared with `race_logic` is the hardware ALU, re-declared verbatim including its argument for why that class is not phase-partitioned |
| `rc_rom` | `rc_kart` — the kart CHR (two 16x16 frames plus the two speed-bar tick tiles, in one 16-wide OBJ grid row pair) and its OBJ palette; `rc_grad` — the eight day-night COLDATA keyframes, ONE contiguous claim because the pointer arithmetic is `base + k*672`. `tools/gen_racer_assets.py` emits all three byte-identically. **No kerb-palette artifact**, and the absence is a design decision rather than an omission: cycling a pair of kerb CGRAM entries reads on screen as the kerb flickering rather than as the kart moving past it, which is the opposite of the speed cue it is meant to give — so the red and white blocks are two fixed entries of the world's own floor palette and nothing writes CGRAM after scene enter |
| `region` | **REGION — the console's own region line, once at boot.** Reads `$213F` bit 4 (measured in-ROM by docs/95 §1.3: `$03` on NTSC, `$13` on PAL) and publishes `ES_RGN_PAL`, 0 or 1, for any game code to branch on. **Opt-in on purpose**: docs/95 §7's R0-b reads the same bit unconditionally in `vendor/rom/init.inc`, which moves the image on all 37 rails including `microzero` and breaks docs/94 §4.2's md5 pin for nothing — a declared feature keeps every rail that does not compose it byte-identical, which is the reversibility property held by construction rather than by care. Holds no `reg` claim: the reg-ownership pass is a WRITER-side gate and this feature only reads (the three other `$213F` sites in the tree, which read it to reset the OPHCT/OPVCT flip-flops, carry no reg claim either). Composed by **32 of the 39 rails** — every playable game, plus the two screen-effect rails (`lakeside`, `heathaze`). The seven determinism rigs state their exemption in their own `game.toml`s and the two deferred rails their measurements in `docs/98` |
| `rgb_gradient` | GRAD; CM incidentally and unclaimed |
| `room_bg` | the `room` game's BG1 floor/walls + BG2 decor; the layers `window_iris` dims and clips |
| `room_hero` | consumes `oam_sprites` + `hero_rom`; supplies no demand term |
| `room_logic` | the `room` game's movement + wall clamp; not engine |
| `room_rom` | `room_bg`'s tiles/maps/palettes and `window_iris`'s circle LUT |
| `rpg_floor` | **BG (M7)** — the `rpg` overworld's Mode 7 ground plane: the interleaved 32 KB region, a 32-word palette pinned at CGRAM 0 (an 8bpp Mode 7 pixel value IS an absolute index) and `M7SEL` at wrap, because the world is a 1024-px torus. A SIBLING of `mode7_floor` for that feature's own stated reason — it `depends` on microzero's 256 KB `world_rom` and pins microzero's palette. BGMODE/TM are `split_band`'s, which is how a Mode 7 sky split is expressed here |
| `rpg_logic` | the `rpg` rail's GAME code — grid movement over `col_map`, the town walk, NPC adjacency, the save payload staging and the scene-swap request; global-lifetime hot state because the overworld camera must survive the town visit |
| `rpg_obj` | the `rpg` rail's actors in OAM (avatar + villagers), in BOTH scenes: unlike `mode7_explore`, where the overworld avatar is pinned at the affine pivot, both of this rail's scenes place a MOVING sprite from a tile coordinate, so one routine serves both. SPR consumer |
| `rpg_rom` | `rpg_floor` + `rpg_town` + `rpg_obj` + `col_map` — nine blobs from `tools/gen_rpg_assets.py`, including the world in BOTH representations the hardware forces: the interleaved Mode 7 region and a flat one-byte-per-tile map `col_map` can probe, emitted from one source so they cannot drift |
| `rpg_town` | **BG (Mode 1)** — the `rpg` rail's town interior: BG1 tilemap + a 64-tile 4bpp tileset + CGRAM word 0, one owner for all of the scene's non-BG3 layers. Its tileset is DELIBERATELY the largest `kind="chr"` claim in the scene: chr claims pack by `(-align, -words, name)`, so a tileset above `text_chr`'s 880 words keeps `text_chr` and `dlg_chr` in ADJACENT pages, which is what puts `dialog`'s panel inside BG3's 1024-tile reach |
| `rs_floor` | **M7 plane** — the `railshooter` rail's grid: the pinned interleaved Mode 7 region, a sixteen-word absolute palette at CGRAM 0 (word 0 included — this rail SEES it, because `split_band` turns BG1 off above the seam so every sky scanline is the backdrop), one mode-1 DMA that streams the interleaved blob straight in, and the scene's M7SEL. Static — the plane never streams, because the camera advances forever and the hardware's own Mode 7 addressing wraps a 128×128 world at 1024 px, which is exactly what an endless rail wants. The FIFTH instance of the `m7dg_floor` ruling (`sh2_floor`, `shm_floor`, `m7x_floor` are the others): `mode7_floor` ALLOCATES for this composition and cannot serve — `depends = ["world_rom"]` is microzero's 256 KB circuit and its CGRAM pin is that rail's palette, so composing it renders a race track under a rail shooter for 226,767 B more ROM |
| `rs_logic` | the `railshooter` rail's driver: auto-advance (the camera never stops — the axis that makes this a rail shooter rather than a racer), the **graded bank ramp** (the path's own slope quantised into four steps a side and then walked ONE STEP PER FRAME toward that target, so the ship rolls instead of flipping between three states — the tween is here, in the quantiser, because the signal it grades was already continuous), fire on the A edge, the obstacle field's approach/recycle, the grow-only size-tier hysteresis, and the bullet × obstacle window test. Not engine. Shares no kernel with `race_logic` or `rc_logic` — both are velocity models over a collision map and this rail has no throttle, no brake, no drag and no collision map |
| `rs_obj` | **the whole visible foreground, and POOL's first generic consumer** — `railshooter`'s ship (**five bank poses**, level plus four steps of roll, the right side H-flipped from the left because the light that shades it has no lateral component), four pooled hazards, three tracers, a pylon stack, the HUD and a world-anchored reticle (counts and OAM sub-windows re-cut by the redesign —; the sub-windows are now `.assert`-tied to their claims), `obj = true` CHR floored past the Mode 7 region with the OBSEL base emitted. Also owns the **pinhole (1/z) projection** (a software shift-add multiply, `m7_project`'s ALU ruling taken again at eleven products a frame) and the **depth-sorted OAM emit with no sort**: pass 1 projects each obstacle once into a 48-B cache, pass 2 walks size tier 0→3 filling slots 1..6, so nearer obstacles take lower slots and draw in front — back-to-front layering re-derived from depth every frame, decoupled from the pool slot an actor happens to live in. That decoupling is the one place this rail DEPARTS from `shmup_obj`'s ruling, and it is why `pool` is a feature rather than a fold. The projection is now the **Mode 7 plane's OWN camera** rather than a second one over the same picture — its vanishing row is the pose blob's (screen y 6, 38 rows above the seam) and its focal is the plane's, so an actor closing z at the rail's own speed tracks the grid it stands on at every screen row; the shipped pinhole put the vanishing row AT the seam and the pylons slid over the ground by up to 11x near the horizon. It also carries a **nine-bit lateral cull**: OAM x is signed 9-bit, so a projected centre outside the frame by more than a sprite's width is culled rather than folded modulo 512 onto the other side — reachable only once the lateral gain became the plane's |
| `rs_rom` | `rs_floor` + `rs_obj` — the interleaved 32 KB grid plane and its palette, the 256-tile OBJ sheet and its palettes (256 and not 224 since the ship's bank ramp: five 32×32 poses need five four-row lanes, and the old sheet's 24 spare tiles were the wrong SHAPE for one — its ship palette is now a monotone six-step hull ramp plus rim, canopy, livery and exhaust, asserted monotone in the generator), the 256-entry baked S-path (`rs_path.bin`), and the two halves of the pinhole projection LUT (81 scanline bytes, 81 scale words) baked at build time by `tools/gen_railshooter_assets.py` — whose three pinhole constants are DERIVED from the pose blob's own hyperbola and asserted there, so a projection that is not the plane's camera fails the generator rather than shipping. The generator also emits `rs_map_probe.bin`, the MEASUREMENT plane the `rs-probe` variant ROM carries (`make rs-probe`): the same 32 KB with magenta re-spent to mark grid intersections and nothing else, which is what makes the surface's screen px/frame readable off a rendered frame. All authored, nothing imported, so there is no external fallback and none is needed on a bare runner |
| `sau_floor` | **M7 plane** — the `boss_saucer` rail's arena: the pinned interleaved Mode 7 region, a sixteen-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot, the night sky), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. Thirteen authored floor colours, not fifteen: the two star tones left with the star field. Everything off the disc is value 0 and therefore TRANSPARENT, which is what makes the plane a hole the priority-0 star sprites show through and the disc an eclipse over them. The NINTH instance of the `m7dg_floor` sibling ruling (`bs_floor` is the nearest, and cannot serve because it is welded to `bs_rom`'s blobs by name). No `hdma` claim: the rail runs FOUR scale ramps and still costs a track lookup per frame, not a channel |
| `sau_obj` | **the saucer fight's cast, and POOL's fourth generic consumer** — the `boss_saucer` rail's gunship (16×16, hit-flash frame), the sixteen-cell BEAM lance (walked from the plane's pivot — which is where the saucer's emitter renders at every scale — to the latched column, so it stays welded to the saucer), the eight-segment saucer-HP HUD, four pooled player shots, the thruster flame, and the twenty-four-cell glyph card band the boot title and the DEFEAT/VICTORY cards draw into, and the twenty-four-sprite STAR FIELD. Eighty sprites in eighty slots = twenty whole hi-table bytes, all rebuilt whole every frame (mo_obj's ruling); the slot map is PINNED to stable identities (0 gunship, 1-16 beam, 17-24 HUD, 25-28 shots, 56-79 stars) so a test reads an actor by slot. ONE pool, not the boss rail's two — the orb rain is gone from this fork. OBSEL claimed here, size pair 0. **The star field is the one band that is not cast**: it was PLANE TEXTURE until 2026-08-20, which tied it to the four scale ramps so the sky zoomed with the saucer; on OBJ it is decoupled from the matrix by construction. It carries a SECOND cgram claim (OBJ palette 1, pinned contiguous at 144 so one enter loop uploads both) because every entry of the cast palette already has an owner and this rail's pixel counts are attributable only while no tone belongs to two populations — and it draws at OAM priority 0, the one OBJ priority Mode 7 puts BELOW BG1, so the hull eclipses a star and the transparent sky does not. Its twelve-and-twelve home rows are spaced ≥16 apart and a band shares one scroll offset, so no two stars of a band can ever share a scanline: 2 sprites and 2 slivers of any line's 32/34, measured |
| `sau_rom` | `sau_floor` + `sau_obj` + `m7_track` — nine blobs from two generators: `tools/gen_saucer_assets.py` authors the 32 KB interleaved "Sable Halo" saucer plane, its sixteen-word palette, the 48-tile OBJ sheet (cast + eighteen 5×7 glyph faces + the two star faces in row 0's last two cells) and its TWO OBJ palettes from concentric-band predicates over the tile grid — first-party procedural authoring, so there is no converter to ground-truth; the plane's off-disc region is now ONE flat tone (CGRAM 0, which a Mode 7 pixel value of 0 makes transparent), because the star scatter that used to live there moved to OBJ; `tools/gen_saucer_tracks.py` bakes the FIVE matrix-track blobs (`sau_ring` 256 headings at the rest scale 900, `sau_reveal` 61 entries 1260→900, `sau_appr`/`sau_retr` 45 entries each for the two halves of the LUNGE at angle 0, `sau_death` 61 entries 900→1260) with the exact smul16 floor-shift arithmetic, and asserts all four handover seams plus the recede landing back on the reveal's own start scale. The size envelope is bounded at both ends by measured hardware facts its header carries: scale 256 is the magnification floor, and the M7SEL wrap ceiling — a rotated screen's support plus the disc's own 176 px radius reaching the next 1024 px copy of the map — caps any pose that can be rendered at an arbitrary heading at 1264 |
| `save` | SAVE — battery-backed persistence over its own `sram` claim (the class's first occupant): 2×32 B slots, magic "SF" + version + length + CRC-16/CCITT verify-before-copy, `$FFFF`/`$FFFE` rejection codes, under allocator symbols |
| `scene_mgr` | scene flow (§1.2) |
| `scroller_bg` | **BG** — the `scroller` rail's whole display, and the smallest instance of the keystone BG pattern in the tree: ONE layer, TWO tiles, a 32×32 tilemap **built** at enter by a `(col ^ row) & 1` loop (the `mset` lesson, kept as a loop rather than baked into a blob), and a two-axis DP camera the NMI hook commits to BG1HOFS *and* BG1VOFS. Owns CGRAM word 0 for the usual two reasons at once (`backdrop` cannot compose with a BG feature, and at palette group 0 that word IS the backdrop slot). **What makes it "the sanity rail for `room_bg` outside the `room` game":** `room_bg` itself is not composable anywhere else — it `depends` on `room_rom` and resolves six of that blob's symbols by name, and the allocator refuses it beside any other BG feature on register contention (both messages transcribed in `game/scroller/game.toml`). So the pattern is what ports, and this feature proves it carries the one degree of freedom `room_bg` explicitly pins to zero: **scroll** |
| `scroller_obj` | the `scroller` rail's one 8×8 sprite, pinned at screen (120, 100) and re-staged into the `oam_sprites` shadow every frame. The sprite HOLDING STILL is the rail's assertion, not a detail — sprite-over-BG compositing is what the demo is, and a BG-only test cannot see half of it. Re-staged per frame rather than written once at enter, deliberately: a write-once sprite would pass a "sprite holds" assertion for the wrong reason and leave the staging path untested for the whole run. SPR consumer |
| `scroller_rom` | `scroller_bg` + `scroller_obj` — and the one blob in the set with **no tilemap**, because this rail's map is built by code at scene enter rather than uploaded. Four small blobs (2 BG tiles, 1 OBJ tile, 2 palettes) from `tools/gen_scroller_assets.py`, which states its two 32-byte tile tables twice and checks them against each other, and its two colour constants once |
| `sh2_cam` | **HORIZONTAL 2-CAMERA SPLIT** — `split_h_2p_demo`'s whole subject: two independently-positioned Mode 7 cameras over ONE plane, seam at scanline 112, on **SIX** active HDMA channels (a PERBAND shape: a matrix pair AND an origin pair per band — the generated census row above says `hdma`&times;6, and this sentence used to say four). The MATRIX pair (DMAP `$43`, indirect) streams a ROM-resident per-scanline pose through M7A–M7D, so neither band runs a live perspective solve; the ORIGIN pair (DMAP `$03`, direct, non-repeat counts) gives each band its own M7X/M7Y + M7HOFS/M7VOFS, re-derived per frame from that band's heading and position ("pure subtraction at a fixed heading" stopped being true once the cameras started rotating). **Not a `mode7_persp` parameterisation** — that feature is one band with a CPU NMI-hook origin shadow, a head-skip index shape, and a 180-line/1024-B pose stride; the origin difference alone is a different CLAIM SET (`reg` vs `hdma`) and a feature cannot conditionally claim. **Not a `split_band` generalisation** either: this rail writes BGMODE 7 / TM 1 once under forced blank for all 224 lines, so the split is of the camera ORIGIN, not of the video mode, and there is no second splitter |
| `sh2_floor` | **M7 plane** — the `split_h_2p_demo` rail's world: the pinned interleaved Mode 7 region, a five-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. Static — it never scrolls, rotates or streams, so it holds no channel; everything per-scanline on this rail is `sh2_cam`'s. A SIBLING of `m7dg_floor`, which is welded to the dungeon's blobs and nine-word palette |
| `sh2_obj` | **The `split_h_2p_demo` rail's cast** — `sh2_swarm`'s 24 live entities projected onto BOTH cameras every frame through `m7_persp_project`, written into the `oam_sprites` shadow with SLOT COMPACTION (visible markers take consecutive slots; a culled one costs no store; the tail is parked only to the previous frame's watermark). Owns the OBJ character block, OBSEL, 32 OAM slots — eight whole hi-table bytes, so the X9/size pairs are rebuilt rather than patched — and TWO palettes, which is what makes the band that produced a sprite legible in the PICTURE: band 1 white, band 2 magenta |
| `sh2_rom` | `sh2_floor` — the interleaved 32 KB warm/cool checker world and its five-word palette; `sh2_cam` — the 256-heading per-scanline pose SET, 448 B per heading, cut into eight bank slices per channel (114,688 B each for AB and CD), which the four INDIRECT matrix channels fetch by heading; the single fixed-angle 448-byte pair is still emitted and is what the `pose1` oracle gates. All byte-identical to the committed reference bytes (`tools/gen_split_h_2p_assets.py` refuses to emit anything else, against `vendor/art/split_h_2p/`) |
| `sh2_sprite_rom` | `m7_persp_project` — the clamped sincos set, the `sp_vk` inverse of the floor's own ramp, the reciprocal pair and the size ladder; `sh2_obj` — the 64-name OBJ character block; `sh2_swarm` — the 64-record entity seed table and the 8x4 waypoint loops. All six LUT/CHR blobs byte-identical to the committed reference bytes; the swarm's world is this rail's own (there is no reference waypoint set for this plane) and is gated by SIMULATION over four laps of the complete 256-state camera cycle instead |
| `sh2_swarm` | **The `split_h_2p_demo` rail's WORLD MODEL** — 24 live entities: two whose world position IS a camera's (so each player's marker draws in the OTHER band and self-culls in its own, where it projects to `v = 0`) and 22 AI waypoint followers steering round eight four-target loops. World-space only, so the AI is rotation-invariant by construction and "the cast moves" stays separable from "the cameras move". Claims NO `reg`: the steering cross product needs signed 8x8 products and `ALU` has one owner, so `m7_persp_project` publishes `mpp_mul8` and this calls it — the allocator's refusal answering the design question at build time. Also holds the LIVE count (poked 1..64 by the cadence later rails) and the main loop's own frame counter, whose lockstep with `scene_mgr`'s VBlank counter IS the cadence gate |
| `shg_cam` | **THE SEAM-IRQ APPLIED CASE (lane 2)** — `split_h_irq_grad_demo`'s origin half: `sit_cam`'s mechanism with the cameras MOVING. Two whole-frame INDIRECT matrix channels streaming one fixed-angle pose to both bands; the seam pair (`shgxy`/`shghv`, mode 3, band [112,224), out of the HDMAEN mask) fired by ONE MDMAEN from the V-IRQ handler at internal scanline 112; the band-1 origin as the `seed = true` reg claim its VBlank hook re-establishes every frame. **What is new against `sit_cam` is the LIVE value**: camera 1 pans +1 px/frame in Y and camera 2 +2, advanced in the scene tick and re-staged by the hook, so the eight bytes the seam DMA delivers change every frame instead of being a boot-time constant — which is what makes the freed channel's payload a claim about a working rail rather than a still. `irq` consumer #2. NOT `sh2_cam`: re-run for this composition and refused on `['M7A','M7B']` in band 0-112 (`game.toml`'s header carries the verbatim text) |
| `shg_floor` | **M7 plane** — the `split_h_irq_grad_demo` rail's world: the pinned interleaved Mode 7 region, one mode-1 enter DMA, the scene's BGMODE/TM/M7SEL, and a five-word absolute palette at CGRAM 0 written **by CPU from named constants rather than a blob**, because every colour must keep BLUE = 0 — that is what makes the rendered blue channel exactly `shg_grad`'s ADD term and the gradient assertion checker-immune. `sit_rom`'s palette carries blue in three of its five words, so the otherwise byte-identical art could not be reused whole |
| `shg_grad` | **THE FREED CHANNEL'S PAYLOAD (lane 2)** — the rail's reason to exist: ONE active-display HDMA channel driving `COLDATA` **as a whole port** with one byte per scanline (`$E0 | v` sets R=G=B in a single write), so a 224-line ramp is a 227-byte repeat-mode table built at boot in WRAM, plus the fixed-colour ADD mode (`CGWSEL`/`CGADSUB`) as its own C4 reg claim. **Not `rgb_gradient`, and run rather than reasoned**: composing it refuses on `['COLDATA_B~COLDATA ($2132)']` — the whole-port claim and the plane claims are SEEN to intersect by construction (`schemas.py`:200-208) — and it would also spend THREE channels and a 672 B ROM table where this rail has one channel and an arithmetic loop. The FIRST whole-port `COLDATA` claim in the tree; the first `CGWSEL` writer outside `rgb_gradient` |
| `shg_rom` | `shg_floor` — the interleaved 32 KB warm/cool checker world; `shg_cam` — the ONE fixed-angle 448-byte pose pair both bands stream. **Three claims, not four**: the reference rail includes exactly these files across its own template boundary from `split_h_2p_demo` and writes its palette by CPU, so there is no `pal` blob to back. From `tools/gen_split_h_2p_assets.py` against the `vendor/art/split_h_2p` oracle, byte-identical to the committed reference bytes |
| `shm_cam` | **N-BAND FLAT MATRIX CAMERAS** — the whole subject of `split_h_matrix_demo` (2 bands) *and* `split_h_persp3_demo` (3), on **TWO** active HDMA channels whatever N is: one DIRECT DMAP-`$03` pair over M7A/M7B and M7C/M7D, whose WRAM table holds one NON-REPEAT entry per band, so a band's CONSTANT matrix costs exactly one HBlank write per channel per frame and N cameras cost what one does. **Not a `sh2_cam` parameterisation, and this was RUN rather than reasoned** : four properties differ, and the sharpest is that the band count is a DECLARATION there and a table entry here — giving `sh2_cam` a third band is refused as *"HDMA register contention … `sh2ab2` and `sh2ab3` both drive `['M7A','M7B']`"*, so row 12 is an edit to that feature, not an argument to it. The other three: INDIRECT pose streaming vs four constant words, four channels vs two (DASB is per-channel, so an indirect pair is forced per band), and a 229,376 B pose-slice dependency neither rail reads. The ORIGIN is the mirror image of `sh2_cam`'s: written ONCE under forced blank for every band and therefore a plain `reg` claim, not a `seed` — the split here is of the MATRIX, so all bands share one origin. Also holds the live band's zoom — an autonomous HDMA-table sweep re-expressed as a pad-driven state cycle |
| `shm_floor` | **M7 plane** — the matrix-band pair's world, shared by BOTH rails: the pinned interleaved Mode 7 region, a three-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. Static — everything per-scanline on these rails is `shm_cam`'s. A SIBLING of `sh2_floor` (which is welded to that rail's blobs and five-word palette), which is itself a sibling of `m7dg_floor`: the third instance of the same shape and the first to serve two rails at once. The world is a 1×1-tile checker DELIBERATELY — two colours and no landmark, so an on-screen checker PERIOD is the only thing a test can read and "N distinct cameras" cannot pass on scenery |
| `shm_rom` | `shm_floor` — the interleaved 32 KB checker world and its three-word palette, and **that is the whole of both rails' art**. One blob feature for two ROMs: `split_h_matrix_demo` and `split_h_persp3_demo` want byte-identical `checker_map.bin` files (md5 `07a9125927a98955daa1445b2ffd2c2c` for both), which is the mechanical half of the sibling case. Byte-identical to the committed reference bytes — `tools/gen_split_h_matrix_assets.py` refuses to emit anything else, and refuses to emit at all with the oracle absent, against `vendor/art/split_h_matrix/` (VENDORED rather than gated on an external checkout, so the one non-tautological check runs under `make bare-check` too) |
| `shmup_bg` | **BG** — the `shmup` planet field on BG1 + the fixed HUD band on BG2, in ONE feature, sharing ONE CHR page between the two layers (BG12NBA's nibbles may name the same base). Also owns the per-frame BG1VOFS scroll shadow the NMI hook commits — the autoscroll, which is a wrapping 32×32 map and a scroll register, **not** streaming — and CGRAM word 0, because `backdrop` cannot compose with a BG feature (both declare BGMODE+TM) |
| `shmup_obj` | `shmup`'s ship, bullets, enemy fighters and kill-bursts; SPR consumer — **and POOL's first instance**: the pool arrays as one `wram` claim, the stable OAM slot ranges as four pinned `oam` claims. One feature rather than two because pool slot k IS OAM slot k. Confirms `docs/09` §1.1's prediction that POOL needs no new claim class |
| `shmup_rom` | `shmup_bg` + `shmup_obj` |
| `shp_cam` | **TWO PERSPECTIVE CAMERAS ON DIFFERENT ANIMATION AXES** — `split_h_persp_demo`'s whole subject: the perspective question answered per BAND. Six active HDMA channels, seam at 112: a per-band matrix pair (DMAP `$43`, indirect, **REPEAT** mode — a new 4-byte unit every scanline, which is what makes each band a per-scanline TRAPEZOID rather than one constant matrix) plus a per-band origin pair (DMAP `$03`, direct, non-repeat) giving each band its own M7X/M7Y + M7HOFS/M7VOFS. Band 1 streams a **64-HEADING** set and band 2 an **8-ZOOM** set — two different ROM sets at different perspective parameters, which is the difference `sh2_cam` cannot express: its table is indexed by heading and this rail's second camera animates its SCALE. **Not a `sh2_cam` parameterisation** (four of four differ: the animation axis, one pose set vs two, `h >> 6` bank arithmetic vs none, and a per-frame world drive vs cameras that deliberately hold still); **not a `shm_cam` one either**, in the opposite direction — that feature's matrix claims are DIRECT with ONE constant unit per band, a flat camera by construction. Per-frame CPU is FOUR STORES: the DASB bytes and both origin tables are static, so VBlank re-points two pose pointers and nothing else |
| `shp_floor` | **M7 plane** — the `split_h_persp_demo` rail's world: the pinned interleaved Mode 7 region, a five-word absolute palette at CGRAM 0 (word 0 included: it is also the backdrop slot), one mode-1 DMA that streams the interleaved blob straight in, and the scene's BGMODE/TM/M7SEL. Static — it never scrolls, rotates or streams, so it holds no channel; everything per-scanline on this rail is `shp_cam`'s. A SIBLING of `sh2_floor` on a **one**-of-three margin rather than three-of-three (only the blob binding differs), and its header says so plainly: a feature here cannot take a blob as a parameter, so "the same code against a different blob" is a new feature by construction. If features ever gain a blob parameter, this and `shm_floor` are the first to collapse into `sh2_floor` |
| `shp_rom` | `shp_floor` — the interleaved 32 KB warm/cool checker world (**byte-identical to `sh2_rom`'s**: one `checker_map.bin` serves both rails, so the oracle is the already-vendored `vendor/art/split_h_2p/ref_checker_map.bin`, named rather than copied) and this rail's OWN five-word cool-green/warm-red palette; `shp_cam` — **two** per-scanline pose sets, 448 B per band-local pose: camera A's 64 headings (28,672 B per register pair, exactly one LoROM window, which is what makes the DASB bytes static) and camera B's 8 zoom steps, with zoom index 0 pinned onto camera A's heading-0 pose so the collapse control is reachable at runtime. `tools/gen_split_h_persp_assets.py` refuses to emit a map or palette that disagrees with the oracle, or anything at all if either is absent |
| `sit_cam` | **THE SEAM-IRQ TRIAL (lane 1)** — `seam_irq_trial`'s whole subject: band 2's Mode 7 origin delivered by a seam-scanline V-IRQ (VTIME = SEAM = 112, internal scanlines) firing ONE MDMAEN write at two pre-armed GP-DMA channels in the HBlank gap, instead of an origin HDMA pair. TWO whole-frame INDIRECT matrix channels (one per register pair — the fixed-angle pose makes sh2_cam's per-band four unnecessary: a two-entry index table re-starts the same 448 B pose at line 112), TWO seam claims (`sitxy`/`sithv`, mode 3, band [112,224), honest DMAP/BBAD derivation) that ride the `sm_hdma` shadow MVN for their per-frame A1T/DAS re-arm but stay OUT of the HDMAEN mask (a convention proven by falsify plant, not a schema field), and the band-1 origin as the `seed = true` reg claim its own VBlank hook re-establishes every frame. NOT `sh2_cam`: run, not reasoned — composing it refuses twice over (matrix x matrix in band 0-112; origin-channel x seam claim in band 112-224 — the second refusal IS the trial's either/or, spoken by the allocator). H1/H2 re-measured on THIS engine loop; `irq` consumer #1 |
| `sit_floor` | **M7 plane** — the `seam_irq_trial` rail's world: the pinned interleaved Mode 7 region, a five-word absolute palette at CGRAM 0 (word 0 = the backdrop slot), one mode-1 enter DMA, and the scene's BGMODE/TM/M7SEL. A sibling of `sh2_floor`, whose `depends = ["sh2_rom"]` would drag the 256-heading slices this rail never reads |
| `sit_rom` | `sit_floor` — the interleaved 32 KB warm/cool checker world + its five-word palette; `sit_cam` — the ONE fixed-angle 448-byte pose pair both bands stream (the reference trial includes exactly these files from `split_h_2p_demo`'s assets). All four blobs from `tools/gen_split_h_2p_assets.py` against the `vendor/art/split_h_2p` oracle — byte-identical to the committed reference bytes, nothing read from outside this tree |
| `sky_band` | BG, partially |
| `smt_bg` | **BG** — the `smelter` rail's two layers AND the layer bases both its scenes share: BG1's four steel plates and BG2's cavern-and-melt, 4bpp each, at 32x64 tilemaps whose SHAPE the claim declares (the first non-32x32 map in the tree, and what found that the emitted `_SC_BASE` was carrying only the base). **BG1 is transparent everywhere a plate is not**, which is what turns one background layer into four independently movable objects: a per-column offset displaces a whole column, so a BG1 that also carried scenery would tear it. BG2's cavern wall is drawn with VERTICAL streaks only and no horizontal feature anywhere, so displacing a column of wall is invisible and the crust line is the only thing that can be seen to move — deliberate, and what makes the per-column equality readable at every column. **That is a property of the TILE AND the MAP, and the rail shipped it half-done**: the tile's eight rows were identical and the map still alternated two streak phases per MAP ROW, which is a horizontal seam every 8 pixels and made the wall slide 3 px sideways for every 8 px a column travelled. A human saw it in the gallery clip; every test in the module measured where the crust IS and none measured what the rest of the column did while it got there. Fixed by alternating on the column, asserted by `test_the_wall_does_not_move_when_its_column_does`, and planted. GLOBAL across both scenes and byte-identical in them: BG1 and BG2 are 4bpp under mode 1 and mode 2 alike, so the mode change costs no art. Neither BGMODE nor either VOFS port is here — the mode is a per-scene `[[claims.video]]` claim and the two scroll ports answer to `smt_flat` on the title and `smt_opt` in the works |
| `smt_flat` | **the title scene's answer for two scroll ports, and the generalisation of `hz_flat` from a PORT to a LAYER'S IDENTITY.** It composes mode 1 with the BG3-priority bit, designates bg3 to the main screen, and establishes BG1VOFS/BG2VOFS at the same two values the works scene's flat control row carries — so the title and the flattened works are the same picture. The new lesson is the third bullet: `works` leaves BG3SC pointing at a table of scroll words, and a scene that drew text without re-pointing it would render 64 bytes of vertical scroll positions AS GLYPHS. `blend_off` was the blender, `hz_flat` was a scroll port a transfer drove, and this is a whole layer's meaning — the rule was never about colour math. The re-point is `bg_text`'s to make, and it is scene-scoped to the title because a global one would meet the offset composition in `works` and stop the build by name (docs/100 O5) |
| `smt_obj` | **the rail's PLAYER, and the reason an offset is a position rather than a display trick.** A knight — Arthur Pendragon out of the vendored `camelot` pack (CC0), traced from the pack's own PNG at build time — as ONE 32x32 OAM entry, walking, jumping and RIDING whichever plate he stands on. The whole feature exists for one equality: `smt_kn_ride` takes his Y from `smt_plate_top`, which reads the same 64-byte row the VBlank transfer moves into BG3's map, so the collision and the picture cannot disagree — not because they are kept in step but because there is only one number, and `tests/test_smelter.py` asserts it as his FEET on the plate's TOP EDGE, both read off the rendered frame, at every phase. It costs the rail's proof nothing: the plates are background, so a sprite drawn over four columns of one is a sprite and not a displacement — the difference from `heathaze`, where a moving object would have destroyed the per-row equalities. Two art facts are load-bearing rather than decorative: the pack frames every cell with four transparent rows under the feet (`SMT_KN_BOTTOM`, measured off the pixels), which is what puts him ON the metal rather than four pixels into it, and a 32x32 knight is exactly a plate's four columns wide. His vertical unit is **9.7 and not 8.8** — the highest plate puts a jump's apex genuinely above the screen while a miss carries him past row 232, and in 8.8 those two are the same bit pattern |
| `smt_opt` | **OFFSET-PER-TILE (debut)** — BG3's tilemap declared to be this scene's per-column scroll table, with `[[claims.video]] mode = 2` beside it. In modes 2, 4 and 6 the PPU reads BG3's map entries as per-column scroll offsets and never renders the layer, so the claim's content is not "some VRAM holds offsets" — it is that BG3 IS NOT A LAYER HERE, which is what no claim class could say before. The composition synthesizes ownership of BG3SC/BG3HOFS/BG3VOFS, so a feature that draws on BG3 meets it as an ordinary register intersection with a message naming the mechanism. **ZERO HDMA CHANNELS during active display, which is the headline**: the words ride the tilemap fetch a layer already pays for, so the whole per-frame cost is one 64 B VBlank transfer of the row and thirty-two independent columns cost exactly what one would. `axis = "v"` because a horizontal offset is 8-pixel granular (the layer keeps its own low three bits); the all-zero H row is still uploaded, because mode 2 fetches a word for each axis whether or not one is meant. Also the owner of the two FALLBACK scrolls — what a column with its enable bit clear falls back to — and of the phase the row index is chosen by |
| `smt_rom` | `smt_bg` + `smt_opt` — six blobs from `tools/gen_smelter_assets.py`: the 13-tile 4bpp CHR, two 4,096-byte 32x64 tilemaps, an 8-frame CHR animation for the melt's four contiguous slots (1,024 B — the classic BG swap: the map never changes and a VBlank transfer moves 128 B of pixels under it, and frame 0 is byte-identical to those slots in `smt_chr` so the boot upload, the animation and the title's restore are the same pixels rather than three pictures that agree). **the WALL gets a COLOUR rotation instead** (128 B — eight steps of eight BGR555 words), and the split is the constraint deciding, not taste: the wall must stay invariant under vertical displacement, so a CHR animation would have to keep every frame vertically uniform AND would leave the invariance case unable to tell "moved" from "animated", while a palette cycle does not touch a pixel. It forced a change of shape worth knowing — two indices cannot flow, so the wall now carries NO pattern in its pixels: one tile, every row identical, every column its own palette index in the group's free 8..15, and the pattern IS the eight colours those indices hold), one 64-byte palette blob carrying both CGRAM groups (one blob and not two, because the uploader needs a small POSITIVE offset from one base symbol and the packer is free to order two claims either way), the all-zero 64-byte H row, and the 4,160-byte column table — 64 complete BG3 offset rows plus a flat CONTROL at a 64 B stride. The control row is a complete row with every value at its base AND EVERY ENABLE BIT STILL SET, so the flat picture and the moving one differ in the table and in nothing else |
| `split_band` | SPLIT — **the one splitter, now with a binding contract.** Two active-display HDMA claims, `band = "scene"` (frame-wide: the seam lives in the TABLE, not in the band), driving BGMODE direct and TM indirect from ROM-resident tables. As of the four band bytes and the seam line are supplied by the INCLUDER through five symbols with no defaults, so a second rail with a different split shape is a second BINDING rather than a second feature — finding B1's ruling, executed. Two bindings ship: microzero's race (seam 44, TM $16/$11) and `split_h_demo`'s cockpit (seam 40, TM $04/$01). What is still single-shape is the TABLE STRUCTURE — two bands, one seam; an N-band split would be a third parameter, not a fifth value |
| `split_v_bg` | **WINDOW DUAL-CAMERA** — the subject of `split_v_fight` and, unchanged, of `split_v_seamtrial`: the SAME feature under two directors, one deriving `(mid, spread)` from a fighter distance and one from a frame counter, which is the generalisation claim's split_v pair row made and this rail's fifteen rendered-output cases discharge. Two cameras onto ONE stage clipped to opposite screen halves by PPU window 1, diverging continuously from the fighter distance so at zero separation the halves are pixel-identical and the ever-present seam is invisible. Owns BG1+BG2+BG3 and the full window recipe (WH0–WH3, W12SEL, W34SEL, WBGLOG, TMW, WOBJSEL). **Not a `window_iris` variant** — that feature claims W12SEL/WOBJSEL/TMW, so the two can never share a scene; it is the mechanism's neighbour, not its shape. **No channel claim**: a straight moving seam is three CPU shadow writes a frame, against the 3-channel HDMA a *shaped* seam would need. Shares one CHR + one tilemap between both layers (the split is purely camera scroll), and claims CGRAM word 0 because `backdrop` cannot compose with a BG feature |
| `split_v_obj` | `split_v_fight`'s two fighters; SPR consumer. One 32×32 knight drawn twice as a P1/P2 **OBJ-palette swap** — team colour is what makes a side-swap read at a glance, and doing it with palettes rather than a second CHR copy keeps the claim at one sprite's worth. Claims OBSEL (as every rail's OBJ feature does — `oam_sprites` is the OAM transport, not the size/base authority) and four pinned OAM slots so the two fighters sit at known indices and the hi-table byte has one owner |
| `split_v_rom` | `split_v_bg` + `split_v_obj` — the arena art. **Its seven FIGHTER/HUD claims arrive in any composition that names `split_v_bg`**, because that feature's `depends` is coarser than the five stage/bevel claims it actually resolves; `split_v_seamtrial` draws no sprite and backs all seven with zero blobs — each one sized to its claim, because the backing gate checks presence and not fill — so the coupling is visible in the artifact rather than hidden behind plausible art. Its two palette claims are also 16 words against 8- and 4-word CGRAM claims, so `SV_PAL_UP` overruns both — inert by upload ORDER in `split_v_fight`, made inert by BLOB CONTENT in the trial. Stage palette and fighter CHR are imported from two registered art packs (both CC0 — per-pack detail in `NOTICE`) and vendored under `vendor/art/split_v/` for bare runners; the stage tiles, the tilemap and the bevel bar are authored. The importer is ground-truthed against a hardware render it did not produce, which is how it was caught converting the knight 4 px off (`--anchor` is inert for an already-boxed frame) |
| `sprg_obj` | `sprite_game`'s two actors (rail 3); SPR consumer — a red player and a yellow dot, both 8×8, drawn from ONE shared CHR tile through TWO OBJ palettes (the "two independently-coloured sprites over one tile" lesson, carried by the OAM attribute palette bits). Claims OBSEL (every rail's OBJ feature does — `oam_sprites` is the OAM transport, not the size/base authority) and four pinned OAM slots — player at 0, dot at 1, per the source's own slot order, which is also sprite-vs-sprite priority — so the draw rebuilds the one hi-table byte from both actors' X values. The X9 derivation is LIVE here, not defensive: the rail has no screen clamp, so the player genuinely crosses X = 256 |
| `sprg_rom` | `sprg_obj` — the shared 8×8 tile (32 B) + both OBJ palettes (64 B), from `tools/gen_sprite_game_assets.py`, which derives `sprite_tile` from its pixel description and checks it against the same bytes stated literally, plus the `OBJ_RED`/`OBJ_YELLOW` colour equates |
| `sr_bg` | **BG — THE PAGE-SEAM WORLD** — the `scroll_run` rail's 512px terrain: the keystone BG pattern's first **64×32 two-page tilemap** instance (`words = 0x800`, placed on the 0x400-word SC alignment; the enter code ORs size bit 0 into the emitted `_SC_BASE` — the shape is the claim's, the base the allocator's). `sr_build_map` writes BOTH hardware pages from the `sr_world` blob at enter — page 0 = world cols 0..31, page 1 = cols 32..63 — so the seam at world column 32 is a display-addressing fact this feature owns; collision needs no seam handling because `col_map` probes the same blob in world coordinates (a page-split point query has no counterpart here). Also the follow camera's publisher: cam_x live and clamped (written by the scene tick as a pure function of the player), cam_y pinned 0, both committed to BG1HOFS/BG1VOFS by the NMI hook every armed frame |
| `sr_obj` | the `scroll_run` runner: one 8×8 red OBJ re-staged into the `oam_sprites` shadow every frame from **US_SCRX** — the screen coordinate the scene derived by the world − camera subtraction, which is the half of the rail's lesson this feature renders. X9 rebuilt from bit 8 every frame though the clamp keeps scrx on screen (the stale-X9 lesson). SPR consumer |
| `sr_rom` | `sr_bg` + `sr_obj` + the `run` scene's `col_map` binding — six blobs from `tools/gen_sr_assets.py`: three tiles derived from their pixel descriptions, both palettes, the **64×32 world** (a 28-row `level` table row for row + 4 pad rows below the screen), and the flag table mirroring its `sf_tile_flags` calls — entry 3 = $02, the goal's non-solid flag, which is ALSO the one-way-platform bit, so the goal pillar's top can be landed on from above but does not block from the side |
| `stomper_bg` | **BG (row 8)** — the `stomper` rail's whole Mode-1 display shape (BGMODE $09 / TM $15 owner; `bg_text` rides BG3 beside it). The keystone BG pattern's next instance after `scroller_bg`, with the axis THIS rail adds: the 32×32 tilemap is **built from the `st_world` ROM blob** at scene enter, so the same bytes that drive the display drive `col_map`'s collision probes — display and collision cannot disagree, by construction. Scroll is STATIC, pinned by the feature's own arm (HOFS 0, VOFS −1 — world row = screen row = OAM row), because the arena is one screen and the vertical axis belongs to the player's physics |
| `stomper_obj` | the `stomper` rail's three live actors — the red player and the two magenta patrollers — staged into the `oam_sprites` shadow every frame from `US_PX`/`US_PYI` and the enemy triples. FIXED SLOTS, PARK-ON-DEATH: a `spr_clear` + sequential `spr` model compacts slots when an enemy dies; SuperForge's positional claims pin player = +0, enemies = +1/+2, and cull a dead enemy by parking its entry (Y = $F0), which renders identically and keeps every OAM readback interpretable. Four sprites claimed for three actors — the hi-table-byte rule (`hud_obj`'s argument, one size up); SPR consumer |
| `stomper_rom` | `stomper_bg` + `stomper_obj` + the scene's `col_map` binding — six blobs from `tools/gen_stomper_assets.py`: the 32×32 `st_world` arena (four `mset` loops, baked loop for loop), the `st_flags` table ([2] = SOLID, mirroring `sf_tile_flags 2`), 3 BG + 2 OBJ tiles stated as `.byte` tables and checked against their derivations, and the three-colour palette set (grey terrain, red player, magenta enemies) |
| `svd_bg` | **WINDOW DUAL-CAMERA, THE SEAM AS SUBJECT** — `split_v_demo`'s stage: BG1 left of a seam, BG2 right of it, over ONE upload (BG2SC = BG1's map, both `BG12NBA` nibbles = BG1's CHR), with **two independent player cameras**. Sibling of `split_v_bg` and deliberately not a reuse of it: that feature's seam is FIXED at centre and its subject is the cameras CONVERGING to pixel identity; this one's seam **moves, slants and clips OBJ**, so the two are two owners of every window register and cannot share a scene. Its seam bar is the BACKDROP through a window-2 band (`sf_split_v_colorseam`'s polarity — CGRAM word 0, claimed here), not a BG3 bevel, so BG3 is off TM entirely. **ONE HDMA channel drives ALL FOUR edges**: WH0–WH3 are consecutive ports, which is exactly DMAP mode 4, and the straight seam uses NON-REPEAT entries (11 B, two 4-byte groups, the registers holding through the idle lines) while the diagonal reads `svd_rom`'s static 899 B blob — so the mode switch repoints A1T instead of switching mechanism, and WH0–WH3 stay off the `reg` claim rather than needing a `seed = true` that would lie |
| `svd_obj` | `split_v_demo`'s two markers; SPR consumer. One 8×8 tile drawn twice — P1's straddling the seam, P2's in the right half — placed there so the per-half OBJ clip has something to CUT: with `WOBJSEL` = window-1-inside and OBJ in `TMW`, P1's marker is sliced at the seam and P2's vanishes. The claim is four OAM slots for two sprites, the hi-table-byte rule at its floor (`hud_obj`'s / `split_v_obj`'s argument), plus OBSEL |
| `svd_rom` | `svd_bg` + `svd_obj` — six blobs from `tools/gen_svd_assets.py`, every number stated here rather than inferred: the 32-entry height map and its four-branch cell rule baked into a 32×32 tilemap, five 4bpp tiles (0 EMPTY, so tile ids 1..4 are the four solid colours), the five BGR15 colours with **word 0 white — the seam bar IS the backdrop**, the marker tile, and the **diagonal seam's HDMA table**: 224 per-scanline (WH0, WH1, WH2, WH3) groups from `DIAG_BASE = 72` / `DIAG_SLOPE = $0080`. A ROM blob because that slant is static — `sf_split_v.inc` says the tables are built once — and 899 B never straddles a bank, which HDMA's non-incrementing A1B requires |
| `tad_rom` | `audio`'s ca65-export blob — loader + SPC700 driver + common data + songs in one bank-start `.incbin` (assets/audio) |
| `text_chr` | **shared-surface companion** (§1.3) — the BG3 CHR page, for `bg_text` AND `vwf` |
| `text_dp` | **global companion** — `bg_text`'s DP block + the font-upload channel |
| `tick_scale` | **THE TIMEBASE — one tick per frame, the per-frame delta scaled by the measured frame ratio, the fraction carried** (docs/96 §4, promoted out of `-D SF_TICK=n`). Supplies the `TS_STEP` macro and the ratio; `depends = ["region"]`, which **auto-includes** `region` in any composition that takes this feature (`resolve_features` expands `depends`) — inclusion, not a refusal: a rail listing only `tick_scale` builds byte-identically to one listing both. A silent 1.0 is ruled out from the other side — with `region` uncomposed, `ES_RGN_PAL` is undefined and ca65 stops the build. **Claims nothing itself**, and that is the design rather than an omission: the only two things such a claim could hold are the region flag (`region` owns it, and a second copy is the duplicated-constant defect this kit exists to refuse) and a shared accumulator (which docs/96 §7 rules out — two consumers on different rates cannot share a carried fraction). A CONSUMER declares two `u16@dp` per rate it scales. Measured by `tools/rate_oracle.py` on the rails that compose it: `scroller` `cam_x` 0.83208 → **0.99919**; `brawler` `knight_tile` 0.82831 → **0.99969** (read out of the OAM tile byte the PPU draws from) and `px` 0.83208 → **0.99909**. NTSC pixel-identical on every composer. First landed on `scroller` and `brawler` (the figures above); the fleet then converted 26 more, measured band **0.994–1.027** across the registry's observables — velocities ×r, accelerations ×r² (arcs keep their apex to ~1%), playheads scaled over byte-identical tables, countdowns left integer. The sweep, its two deferrals and the pin move: `docs/98` |
| `vwf` | VWF |
| `vwf_rom` | `vwf` (768 B left-aligned 1bpp masks + 96 B advances) |
| `water` | **BLEND** — a real BG2 water surface on the SUB screen, half-added over the main-screen world: `[[claims.screen]]` bg2→sub plus `[[claims.blend]]` add/half/source=sub/math=[bg1, backdrop], its own CHR + map + palette group 2, the drifting BG2HOFS the NMI hook commits, and a 32-byte CHR rewrite beside it that walks the surface's highlight through four phases — indexed by the accumulated scroll, so the twinkle inherits the region-correct rate and holds when the drift is stilled, with no clock of its own and no channel. **The first consumer of the screen/blend vocabulary** (docs/99) and the reason it exists: the same picture previously needed one feature owning TM, TS, CGWSEL, CGADSUB and both layers, which is a monolith rather than a composition. `bg3` is absent from `math` deliberately, so text over the water stays legible at full intensity — the per-layer enable doing the job it exists for. The drift is a velocity and takes one factor of r through `TS_STEP`; the accumulator pair belongs to the consumer's `state.toml` |
| `water_rom` | `water` — three blobs from `tools/gen_lakeside_assets.py`: the 22-tile 4bpp surface CHR (0 empty for the edge, each zone's ripple, the jagged top, the zone seam, and the highlight's display slot plus its four phases), the 1,024-word surface map and the sixteen-word palette group 2. Split from `lake_rom` rather than merged so the surface's art travels with the feature that draws it. It also emits `lk_art.inc` — the tile indices the highlight loop walks, pinned by format version at the consumer rather than copied into it |
| `window_iris` | **WINDOW** — per-scanline WH0/WH1 + windowed colour math; the first supplier of's flagship gap |
| `world_rom` | `mode7_floor`, `mode7_stream` |

**No claim is supplied twice** (the spec's stated finding condition). The one
place two dirs claim the same *resource kind* at the same address — CGRAM word 0
— is `backdrop` vs `mode7_floor`'s palette, and that is deliberate: they must
refuse the build together.

**Verified rather than assumed**, per AGENTS.md's "prove the gate fails on a real
violation": adding `backdrop` to the race scene's feature list (which already
carries `mode7_floor`) and re-running `allocate` refuses with

```
AllocationError: CGRAM overlap in scene 'race': backdrop_color (engine:backdrop)
pinned at [0..1) words collides with another sub-palette
```

so the two tomls' comments describe enforced behaviour, not intent.

**Placement observation, not a finding:** `player_car` and `race_logic` are
game-specific but live under `engine/features/`. Harmless now; worth watching
when a second game lands, since the directory name implies engine ownership.
`race_logic` now declares `role = "game_logic"`, so that observation is at least
machine-visible rather than only recorded here.

---

## 4. The architecture map — "I am adding a feature, what do I do?"

The rules below are all real and all enforced. Today they are enforced *by the
build failing*, and they live nowhere a new author reads — which is the fourth
question in `08` §1 and the one that keeps costing time.

### 4.1 Claim scope follows the CODE's include scope

This is the rule most likely to be got wrong, because the failure is an
undefined-symbol assembly error whose message says nothing about scope.

`game/microzero/main.asm` includes feature `.asm` files at **two** levels:

- **Top level** — *"engine feature runtimes (shared code, global symbols only)"*:
 `scene_mgr`, `input`, `fade`, `bg_text`, `mode7_floor`, `split_band`,
 `oam_sprites`.
- **Inside a scene's `.scope`** — e.g. `race.asm:18-23` includes `mode7_persp`,
 `rgb_gradient`, `mode7_stream`, `player_car`, `race_logic`, `sky_band`.

The consequence:

> **Top-level shared code cannot see a scene-scoped symbol.** A scene-scoped
> claim emits inside `.scope <scene>`. So a feature whose code is included at top
> level must either take the scene's address **as a parameter**, or put its claim
> on a **global companion feature**.

Both patterns are in the tree and both are load-bearing:

| pattern | example |
|---|---|
| shared routine takes the scene base **in a register** | `bg_text.asm:120` — *"In: X = VRAM word base (the scene's `ES_V_FONT`)"*. The scene sets BG34NBA from its own symbol; the shared code only ever names *global* symbols directly (`ES_R_FONT_BIN_SIZE`, from the global `font_rom`). |
| shared routine's claim sits on a **global companion** | `font_up` (the font-CHR upload channel) sits on **`text_dp`**, not `bg_text`, because `text_upload_font` is shared top-level code. `mode7_floor`'s two upload shapes (`m7chr_up`, `m7map_up`) sit on **`enter_scr`** for the same reason. |
| code inside a scene scope declares **its own** scene-scoped claims | `sky_band`, `player_car`, `mode7_persp`, `rgb_gradient`, `mode7_stream` |

So a feature can perfectly well have *scene-scoped spatial claims* and
*top-level code* at once — `bg_text` and `mode7_floor` both do. What cannot
happen is top-level code *dereferencing* a scene-scoped symbol.

**Deciding where your feature goes:** if its code must run for more than one
scene from one copy, it is top-level and its claims are global (or passed in). If
it belongs to one scene, put it in that scene's scope and declare scene-scoped
claims — they are the cheaper kind, because the allocator can reuse the space in
other scenes.

### 4.2 Which claim class for which mechanism

| the mechanism | the class | exclusivity |
|---|---|---|
| HDMA drives a port **every scanline of a band** | `claims.hdma`, `phase = "active"` | **exclusive** on `(port, mask, band)` |
| a GP-DMA fires from the **NMI hook** each frame | `claims.hdma`, `phase = "vblank"` + `[claims.dma]` byte/transfer budget | **shared** — serialised queue entries; the NMI core re-arms `$43xx` from the shadow afterwards |
| a **one-shot enter-time upload** under forced blank | `claims.dma_init`, `phase = "forced_blank"` | **no exclusivity** — `scene_mgr`'s enter clears HDMAEN and zeroes NMITIMEN, so it cannot race an active or vblank claim even on a shared channel number |
| a memory region | `vram` / `dp` / `wram` / `cgram` / `oam` / `rom` | packed and proven disjoint |
| **a register the CPU writes directly**, configuring a layer or mode another feature could want | `claims.reg` | **exclusive for the whole SCENE, phase-blind** — see §2.1. Also refuses against an `hdma`/`dma_init` claim on the same port, since the transfer destroys the value the write establishes |
| ...where a DECLARED transfer claim is meant to overwrite that base value | `claims.reg` + `seed = true` | composes with `hdma` claims on the port (never `dma_init`), and a seed with nothing overriding it is refused as a lie |
| **putting a layer on the main or sub screen** (TM/TS) | `claims.screen` — `layer` + `on`, NOT a `claims.reg` on TM/TS | **exclusive per LAYER, per scene** — the allocator ORs the enable bits and refuses two designators of one layer even when they agree. docs/99 |
| **programming the colour-math unit** (CGWSEL/CGADSUB) | `claims.blend` — `op`/`half`/`source`/`math`/`clip`/`prevent`, NOT a `claims.reg` on CGWSEL/CGADSUB | **one blender per scene**: the five global fields must agree across the scene's blend claims; `math` composes, one owner per enable bit. docs/99 |
| ...**per-scanline** TM/TS, or direct colour (CGWSEL b0), or TMW/TSW | `claims.reg` (+ `seed = true` beside the `hdma` claim, for the per-scanline case) | the vocabulary above deliberately does **not** cover these, and a raw claim stays legal in a scene that composes no vocabulary half on that port. docs/99 §8 |
| **occupying the audio CPU** — driver + samples + songs + echo, and the loader/mailbox that feeds it | `claims.spc` (+ `claims.reg` on `APUIO`) | **exclusive for the whole PROGRAM** — one occupant per game across all scenes; see §2.4. Presence-only: the occupant's own toolchain packs the 64 KiB interior |

Two details that are easy to get wrong:

- **`mode = N` is a port *span*, not one port.** One BBAD byte plus a mode
 determines the register set the silicon sees: mode 3 at BBAD `$211B` drives
 M7A *and* M7B, which is why `mode7_persp` declares two names on one channel.
 Declare every port the mode actually drives.
- **Sub-registers are real where the hardware partitions by data.** `COLDATA`'s
 three plane-select bits are the mask, so `rgb_gradient`'s three plane claims
 compose while a whole-port `COLDATA` claim refuses against any of them. Only
 add a sub-register name when that partition is real in hardware, or the mask
 lies.

### 4.3 What is a claim, and what is not

**A claim owns the *destination* ports.** Source-side details are deliberately
not declared. DMAP's fixed-source bit (`$08`) is the worked example: it is a
property of where bytes come from, not of what they contend for.

This matters because of a specific reflex: when a gate complains, the instinct is
to widen the declaration until it stops. That would model a source detail as a
claimed resource, and the declaration would stop meaning "what this feature
contends for."

### 4.4 The register-encoding rule

BBAD and DMAP come **from the declaration**, as emitted symbols —
`ES_H_<CLAIM>_BBAD` / `ES_H_<CLAIM>_DMAP` for `claims.hdma`, `ES_D_*` for
`claims.dma_init`. Channel numbers come from `ES_H_<CLAIM>_CH`.

**Hand-narrating an encoding is the same violation as hand-narrating an
address.** `allocator/no_literals.py` refuses a new site that writes its own
literal DMAP/BBAD, a raw `$43xx` operand, an equate naming one, a
channel-picking immediate, and a literal MDMAEN/HDMAEN mask — including one
stored to the WRAM HDMAEN shadow. Two guarded exceptions exist and carry
`; CHANNEL-LINT: ok — <reason>` at their sites.

Same rule for BG bases: use the emitted `_SC_BASE` / `_NBA` symbols. Do not
narrate a VRAM base into a register value in ASM.

### 4.5 Init contract and test contract

Every new feature ships both.

**Init contract** — either declare `[init] zero = [...]` for the blocks that need
it, or establish write-before-read *by construction* and say so in the toml.
Power-on RAM is random (CLAUDE.md rule 5), and the uninit-read detector holds you
to whichever you chose. `enter_scr` is the worked example of the second form:
*"every routine writes before it reads, per call — no boot zeroing needed."*
Do not zero-init "to be safe" — it hides bugs that bite on hardware.

**Test contract** — the test reads the **output region the feature produces**:
VRAM/OAM/CGRAM bytes or screenshot pixels, never a proxy variable. Drive whole
state cycles, not snapshots. For a composition, assert both features' outputs in
the same frame. And prove the test fails on a real violation before believing
it — this repo has twice shipped an assertion narrower than its own name
(`.md` §3.4).

### 4.6 The checklist

1. Decide scope: one scene → scene scope; many scenes from one copy → top level,
 claims global or passed in (§4.1).
2. Write `feature.toml`: `name`, `depends`, claims (§4.2), `[init]` (§4.5).
3. Build. **An infeasible declaration stops the build — that is the answer
 arriving early, not an obstacle.**
4. Use the emitted symbols in ASM (§4.4). Never a literal address, channel or
 encoding.
5. Write the rendered test (§4.5), then try to break it.
6. If your feature CPU-writes a register, **first check §2.1's class boundary** —
 a write that merely addresses a **resource you already claim** is covered and
 needs nothing (`VMADD`/`VMAIN` for a `vram` claim, `CGADD` for `cgram`,
 `OAMADD` for `oam`, and the address latch of any data port you name on an
 `hdma`/`dma_init` claim). Then check whether the port has a **vocabulary**:
 `TM`/`TS`/`CGWSEL`/`CGADSUB` are the four the screen/blend classes compose
 (docs/99), and inside a scene that composes them a `[[claims.reg]]` on the
 same port is **refused** — two vocabularies cannot both supply one
 write-only byte. Put a layer designation in `[[claims.screen]]` and
 colour-math programming in `[[claims.blend]]`, and let the SCENE write the
 composed `ES_SCR_*` values:

 ```toml
 [[claims.screen]] # bg2 onto the sub screen — not a claims.reg on TS
 layer = "bg2"
 on = "sub"

 [[claims.blend]] # the blender — not a claims.reg on CGWSEL/CGADSUB
 op = "add"
 source = "sub"
 math = ["bg1", "backdrop"]
 ```

 A raw claim on those four stays right in the cases the vocabulary does not
 cover, and only there: a scene that composes no vocabulary half on that
 port — per-scanline TM rewritten by HDMA (`seed = true` beside the `hdma`
 claim), direct colour (CGWSEL b0), TMW/TSW. docs/99 §7-8 names each.

 Every other write that configures a **layer or a mode** another feature
 could also want (BG*n*SC, BG*nn*NBA, BGMODE, BG*n*HOFS/VOFS, M7SEL,
 M7X/M7Y, COLDATA, OBSEL, INIDISP, TMW/TSW, NMITIMEN, ALU) goes in
 `[[claims.reg]]`:

 ```toml
 [[claims.reg]]
 registers = ["BG1SC", "BG12NBA"]
 # seed = true # ONLY if a declared hdma claim in the same scene is
 # meant to overwrite this base value per line/frame
 ```

 Ownership is **exclusive for the whole scene and phase-blind** — do not reach
 for a `phase` field, and read §2.1 before "unifying" this with the HDMA pass.
 If your write is to a *new* CPU-bus (`$42xx`) register, it needs the
 ALU-style aliasing analysis first: check whether the hardware shares state
 across ports before adding a name, or the footprint lies.
7. If your feature's ASM writes a register it does *not* declare, **the build
 refuses** (since 2026-07-31 — §2.1 hole 1's writer-side gate, the
 reg-ownership pass in `allocator/no_literals.py`). The refusal names the
 port, its footprint name, and who does own it; the fix is the
 `[[claims.reg]]` from step 6, or — for a data port whose resource you
 already claim — nothing, because the covered rule already legalises it.
 `; REG-LINT: ok — <reason>` is the escape hatch for a site that is safe
 by construction.

---

## 5. What each unbuilt feature would need

Spec acceptance 7: flag any *other* missing claim class before it blocks a phase.
Beyond §2's two, one more candidate surfaced and one commonly-assumed one did
not.

| unbuilt | would need | new class? |
|---|---|---|
| ~~**VWF** ~~ **BUILT 2026-07-28** | `wram` tile buffer + `dp` shift state + `rom` width table + `vram` destination, over TXT's surface. **Upload path undecided** — CPU stores in the NMI hook (no channel, no bytes) vs a vblank `hdma`+`dma` pair; `text_dp`'s `txt_q` comment states the threshold and the arm-charge reasoning (§1.1) | **no — CONFIRMED**, and the undecided half is now decided. It shipped as `wram` 240 B (dma source) + `dp` 22 B + a vblank `hdma` (VMDATAL/VMDATAH, mode 1) + `claims.dma` 224 B / 1 transfer, and **no `vram` claim of its own** — the destination is a sub-range of `text_chr`'s page (§1.3), which is the one prediction here that was wrong in shape rather than in class. The upload path was settled by MEASUREMENT, not argument: the CPU-store ceiling is 324 VRAM words/VBlank = 18.37 byte-equivalents per word, so a GP-DMA wins from one 2bpp tile (8 words) upward. Row kept rather than deleted, same as col_map's below. |
| ~~**col_map** ~~ **BUILT 2026-07-28** | `rom` flag table + `dp`; reads the world blob | **no — CONFIRMED.** It shipped as exactly that (`dp` 10 B + `rom` 256 B on a global companion) and `allocator/schemas.py` is untouched. Row kept rather than deleted: a prediction that was checked and held is worth more on the record than a blank. |
| **OBJ-HUD** | `oam` slot range + `cgram`, over `oam_sprites` | **no — CONFIRMED** by the first instance (: the `room` pip row): claims + the `OamClaim.at` pin, zero new classes. The generic discipline row in §1.1 stays PARTIAL. |
| **M7-affine matrix** | writes M7A–D once at enter — **no HDMA claim at all** | **no**, but it needs §2.1's class to declare the ownership |
| **M7-scale** | same as the above; scaling *is* an affine matrix | **no** |
| **CM** | a declaration over CGWSEL/CGADSUB, which are already named | **no** — needs §2.1's class only |
| ~~**POOL**~~ **BUILT 2026-08-02** | `wram` arrays + `oam` slot range | **no — CONFIRMED.** It shipped as exactly that: `shm_pools` (160 B `wram`) plus four pinned `[[claims.oam]]` on `shmup_obj`, and `allocator/schemas.py` is untouched. Row kept rather than deleted — the col_map convention: a checked prediction is worth more on the record than a blank. |
| ~~**2-controller input**~~ **BUILT 2026-07-30 (C2)** | a second `dp` triple | **no — CONFIRMED**: it shipped as exactly that (`input2`, dp×3 + `[init] zero`), zero schema changes. Row kept — a checked prediction beats a blank. |
| **palette-cycle** | `cgram` + a VBlank write path | **no** |
| ~~**parallax**~~ **BUILT 2026-08-02** | `hdma` per-band BGnHOFS + a `wram` table | **no — CONFIRMED.** It shipped as exactly that: one mode-2 direct `hdma` claim on BG2HOFS over a 16-byte `wram` claim on `platformer_bg`, and `allocator/schemas.py` is untouched. Row kept rather than deleted — the col_map convention: a checked prediction is worth more on the record than a blank. |
| **BG (generalised)** | BGnSC / BGnNBA / scroll ownership per layer | **yes-ish** — needs §2.1's class **and** B2's four register names |
| **hires text (Mode 5/6)** | a second tilemap + CHR base at a seam | **blocked on B2** — `BGnSC`/`BG12NBA`/`BG34NBA` must be added to `REGISTER_FOOTPRINT` first |
| ~~**SAVE**~~ **BUILT 2026-07-30 (C2)** | SRAM region + size, battery-backed, game-lifetime | **YES — a third missing class, and it SHIPPED as predicted.** The prediction held in every part: `[[claims.sram]]` as a `BytesClaim` region packer over a new `[sram]` substrate table (the entry this row said was absent), PROGRAM-wide placement (one free list, union across scenes, deduped by feature name — the first program-wide packer; `spc` is program-wide but a check), size derived from demand, and BOTH cart header bytes (`$FFD6` battery type + `$FFD8` size — the second was the only one on record) emitted as derived encodings with `.ifndef` defaults in `header.inc`. Settlement brief shipped by the C2 pass with `engine/features/save` as the class's first occupant. Row kept rather than deleted — the col_map convention: a checked prediction is worth more on the record than a blank. |
| **AUD** | `rom` blobs + `wram` driver state | **settled — (2026-07-30), the re-test this row asked for.** the earlier *reasoning* (off-CPU ⇒ no class) is refuted by C1 and stays refuted. But the tested counter-argument substantially holds: at the vendored pin (`822164b`), TAD owns all 64 KB and its compiler refuses over-budget compositions per song at build time (common + song + `max_edl` echo ≤ 64 KiB), echo pinned at end-of-ARAM with runtime EDL clamped to `max_edl`. Under a vendored TAD the class SuperForge needs is a **whole-space exclusive `spc` claim** (the occupancy boundary TAD states only as a comment) **+ the single `APUIO` name in `REGISTER_FOOTPRINT` (one name covering `$2140–$2143`, §2.4) with a `[[claims.reg]]` row + the `Tad_Init` boot contract** — not a region packer over TAD's interior. The full region class (alignment + granularity) is the own-driver shape, pre-scoped in **Shipped end-to-end by 2026-07-30 — class core (§2.4) + the `audio`/`tad_rom` dirs + the playable (`room`'s three scenes).** |

**So the full missing-class list is three, ranked:** CPU-written PPU register
ownership (§2.1, live in the tree) · SRAM (above, blocks's SAVE) ·
scanline IRQ (§2.2, blocks a rail). Plus B2's four register **names**,
which are an afternoon rather than a design.

> **Superseded count (2026-07-30):** is the current
> missing-class list (C1–C5; §2.1 landed as the `reg` class), and
> settles C1's shape under a vendored TAD to an exclusivity claim +
> vocabulary rather than a region packer. The ranking logic above survives;
> the count does not.

### 5.1 A missing *mechanism*, not a missing class: declared spatial sub-range adjacency

**Registered 2026-07-28 from the VWF pass's G1 decision**, which is the first
composition to need it. The claim classes are sufficient; what is missing is a
way to declare *"my claim must be reachable from the same BG base as that
claim."* Three measured facts make it a real gap rather than a wish:

1. **`chr_align_words = 0x1000`** (`substrate.toml:14`), so every `kind = "chr"`
 claim lands on its own 4 K-word page. Two features cannot land in one page
 even when both fit.
2. **A BG layer has one base nibble but a 10-bit tile index.** From
 `/tmp/Mesen2/Core/SNES/SnesPpu.cpp:239-248`: `tileIndex = tilemapData & 0x3FF`
 and `tileStart = config.ChrAddress + tileIndex * 4 * bpp`, so a 2bpp layer
 reaches `1024 × 8 = 8192` words = **two consecutive `chr_align` pages** from
 its base. So two disjoint claims one page apart *are* addressable together —
 the mechanism the hardware offers is real and the allocator cannot express it.
3. **Packing order decides it, and nothing checks the result.** In microzero's
 `race`, chr claims pack `car_chr` → `$4000` (obj, `0x2000` align), `font` →
 `$5000`, `sky_chr` → `$6000`, and a 14-tile VWF strip claim → **`$7000`**.
 `$7000 − $5000 = $2000` = tile **1024** — exactly **one tile past** BG3's
 reach, purely because `sky_chr`'s 128 words occupy the page between them.
 Swap those two placements and the composition works. Nothing declares the
 requirement, so nothing notices.

The consequence for VWF: a second BG3 CHR claim cannot be addressed alongside
`bg_text`'s `font`, so the choices collapse to (a) one claim with a sub-range
split the allocator does not prove, or (b) a page duplicating the 96 font tiles
— **1,536 B that `title→race`'s reload budget refuses** (measured: reload 41,298
vs `budget_bytes = 40000`, and refused at *every* window size because the
duplicated font alone exceeds the 238 B of slack). Both are workarounds for a
constraint that could simply be declared.

**Status after the VWF pass:** VWF took the companion route (§1.3) rather than live with the constraint, so this is now a **clean follow-up** and not a workaround anyone is enduring. It still binds the moment a feature needs a CHR page it cannot share — a second sprite CHR bank, or hires text's second base at a seam (§6-B2).

Sketch of the fix, for whoever takes it: a `reach = "<claim>"` (or
`page_group`) field on `claims.vram` asserting "place me within the declaring
layer's tile reach of that claim", packed as a group and verified in step 5
alongside the existing alignment checks. Cheaper than §2.1's register class — no
contention semantics, no phase question — and it converts a silent geometry
accident into a build-time refusal. Note it also needs the reach to be a
function of `bpp`: 4bpp halves it to one page.

#### The same gap on the TILEMAP side — scope the mechanism to both

**Registered 2026-07-28 from VWF.** The section above was written
from the CHR case, and the name "CHR-page adjacency" made it look narrower than
it is. The identical gap exists for **tilemaps**, and VWF is already standing in
it:

`vwf_map_row` (`engine/features/vwf/vwf.asm`) writes 14 tilemap cells at a word
address its *caller* supplies — in microzero, `VWF_ROW_CELL` in
`game/microzero/scenes/race.asm`, which is inside `bg_text`'s `text_map` claim.
`vwf` neither claims `text_map` nor `depends` on it. This is the first case in
the repo where **one feature's routine writes another feature's claimed region**,
and unlike the CHR sub-range it got no `.assert` and no declaration.

It is distinct from the pre-existing "scene picks the cells" pattern
(`race_logic`'s lap digit): there the scene calls **`bg_text`'s own** routine
into **`bg_text`'s own** claim, so ownership is never crossed. Here the routine
belongs to `vwf` and the region belongs to `bg_text`.

What is missing is the same mechanism, not a new claim class: a way to declare
*"this sub-range of that claim is mine"* so the allocator can prove the two
sub-ranges are disjoint. The CHR side got a hand-written `.assert` derived from
emitted symbols (`vwf.asm`'s `VWF_TILE0` block) precisely because the
declaration was not available; the tilemap side should get the same treatment
from the same mechanism when it lands.

**Interim guard, and what it does NOT cover.** `race.asm` now `.assert`s at
build time that the dialog row's whole 14-cell span lies inside `text_map`. That
catches a row walked off the end of the claim. It does **not** catch the case
that actually matters — a row pointed at the HUD's row 2, silently overwriting
`SCORE` — because nothing declares which cells of `text_map` `bg_text` itself is
using. That is exactly the sub-range declaration this section is registering as
missing, and it is why the interim guard is a guard and not a fix.

---

## 6. The `08` §3.4 worked examples, reproduced from the table

The point of these is that a designer should get the answer by *reading* the
register, not by writing code and discovering it from a build failure. Both
below are read off §1 and §2 without re-deriving anything.

### A. Mode 1 HUD band on top, Mode 7 world map below

**Fits, built, and SHIPPED TWICE** — it is microzero's race scene, and as of 2026-08-07 it is also the `split_h_demo` rail this row is named after, which is the same four features at a different seam with different band bytes.

| need | supplied by | claims | status from §1 |
|---|---|---|---|
| the band split | `split_band` | 2× `hdma` active — BGMODE direct, TM indirect | built, **generalised** — two bindings |
| the M7 plane | `mode7_floor` | `vram` (M7 region), `cgram` at 0, `rom` | built |
| the transform | `mode7_persp` | 2× `hdma` active — M7A/B, M7C/D (mode 3) | built |
| the HUD text | `bg_text` | `vram`, `cgram` | built, fixed-width |

**Finding A1 reproduces:** if the world map wants a *static or rotating uniform*
transform — an RPG overworld, not a racing floor — the M7-affine row reads
**PARTIAL**, and the note names the gap exactly: nothing owns setting a static
M7A–D matrix. The register also gives the payoff without anyone deriving it: a
matrix set once at enter needs **no HDMA claim**, so that composition costs **2
active channels rather than 4**, and ~1%/frame rather than perspective's 69%.

### B. Mode 5 text box on top, Mode 1 RPG town below

**The shape fits and reuses the same mechanism; it is blocked on register
vocabulary; and it exposes a hole in the demand vocabulary itself.** Read
straight off the table:

- **B1 — do not build a second splitter. DISCHARGED 2026-08-07 .**
 SPLIT's row shows `split_band` as the sole **active-phase** owner of BGMODE,
 `band = "scene"` (the whole frame — the seam lives in the *table*, not the
 band). A Mode 5 / Mode 1 split is therefore not a second claim, it is the same
 claim with different table values. Generalise `split_band`'s hardcoded table.
 Without this row, an author sees a feature named for Mode-1-over-Mode-7 and
 reasonably writes their own splitter — and the collision gate **will not
 object**, because two disjoint-band BGMODE claims are physically legal. That
 is the duplication this register exists to prevent.

 **What landed.** The `split_h_demo` rail needed exactly the
 predicted thing — the same mechanism at a different seam with different TM
 bytes — and took this answer instead of writing `split_h_band`. The table's
 five values are now includer-bound with no defaults (`SB_LINES`,
 `SB_MODE_TOP`, `SB_MODE_BOT`, `SB_TM_TOP`, `SB_TM_BOT`; each missing one a
 named `.error`, all five OBSERVED to fire), microzero binds what was folded in
 and is byte-identical, and the register now describes a feature with two live
 bindings rather than one hardcoded shape. **The row was right and it was
 cheap**: the generalisation is 40 lines of contract in a data-only file, and
 the port that used it never opened the question of a second splitter.
 **What B1 does NOT yet cover** is the table's STRUCTURE — two bands, one
 seam. A three-band split (`mode7_chamber` row 18) is a third
 parameter, not a sixth value, and stays open.
- **B2 — blocked, and precisely which kind.** Mode 5 is hires with different BG
 depths, so the two bands want different tilemap and CHR bases: `BGnSC` and/or
 `BG12NBA` must change at the seam, which is a per-scanline write, which is an
 `hdma` claim. `BG1SC`, `BG2SC`, `BG3SC`, `BG12NBA`, `BG34NBA` and `CGADD` are
 **not in `REGISTER_FOOTPRINT`** — `_parse_registers` raises a `SchemaError`
 listing the known names. Loud, not silent, and by design. **Keep this distinct
 from CM:** CGWSEL/CGADSUB *are* in the table, so colour math is *unclaimed*
 (a declaration to write) while this is *blocked* (a name to add).
- **B3 — the demand vocabulary has no term for hires text.** §1.2 carries it as
 its own row, marked **vendored**: a working hires text engine
 exists and is proven. No rail in the demand catalogue performs a Mode 5 split at
 all — `meteor_event` does Mode 1 ⇄ M7 as a *forced-blank scene swap*, not a
 split. So this is genuinely new territory here, and the register says so
 instead of implying TXT covers it.
- **B4 — an unmeasured hardware assumption.** Whether `BGnSC` can be safely
 changed mid-frame by HDMA is **not established**, and CLAUDE.md's
 measure-don't-estimate rule applies. The existing split already carries a seam
 artifact that was asserted rather than fixed (line 44 renders backdrop). **Probe
 before feature**, in the shape of `vendor/probes/probe_vb2reg` — no register row
 should imply this composition is available until the probe says the mechanism
 works.

**The acceptance sentence.** Asked *"can I build a Mode 5 text box over a Mode 1
town?"*, this register answers: **the split mechanism exists and is owned by
`split_band`; you need four register names added; and the mid-frame `BGnSC`
change is unmeasured — probe it first.**

---

## 7. Acceptance self-check against `08` §5

| # | criterion | state |
|---|---|---|
| 1 | Every the spec vocabulary feature has a row | **met** — all 14 in §1.1, plus 10 more in §1.2 |
| 2 | Every `engine/features/*` dir accounted for; many-dirs visible if used | **met** — §3, all 20, none unaccounted. Many-dirs: **no instance in the tree today**, recorded honestly in §1.3 rather than manufactured. No claim supplied twice |
| 3 | Both missing classes in the missing-class column, CPU-write ranked first | **met** — §2.1 (live in the tree, two instances named) then §2.2 (IRQ). A **third** surfaced: SRAM (§5) |
| 4 | The §3.4 worked examples reproduce | **met** — §6. M7-affine PARTIAL; B2's four names blocked and kept distinct from CM's unclaimed; `split_band` sole active-phase owner of BGMODE; hires text carried as its own term |
| 5 | Supply half regenerates from the tree, test enforces agreement | **met (2026-07-28)** — slipped at first delivery, closed the next day: §3's census is generated inside `BEGIN/END GENERATED` markers, `make register` checks it, `tests/test_register.py` plants drift in both halves. **§1.1/§1.2's claim-classes column is NOT covered** — see the note under §3 |
| 6 | Architecture map answers "where does a new feature go" without assembling | **met** — §4, with the scope rule verified from both sides (§4.1) |
| 7 | Names what each unbuilt feature needs, flagging further missing classes | **met** — §5, which surfaced SRAM |

---

## 8. What this changes for

- **VWF and col_map need no new claim class. BOTH SHIPPED 2026-07-28 AND THE
 PREDICTION HELD** — `allocator/schemas.py` is untouched by either pass.
 Both compose from existing classes over existing surfaces (§5). That was the
 question the register was built to answer before those features land, and the
 answer is clean. **VWF's upload path is now measured and settled** — a vblank
 `claims.hdma` + `claims.dma`, see the §1.1 row and
- **Correction — the "7 of 8 active channels" figure does not constrain a
 vblank claim, and an earlier draft of this row said it did.** Channel
 occupancy is checked **per phase** (`allocate.py` `channel_free`: `p ==
 phase`) and `_register_exclusive` returns True for `"active"` only, so a
 vblank claim SHARES a channel number with an active one — verified by
 running hypothetical declarations through `allocate.py` against the live
 manifest: `race` + a vblank claim still reports 7/8 with `vwfq` sitting on
 ch2 alongside `colg`, while `race` + an *active* claim reports 8/8. The
 over-claim that costs `race` its last channel is an **active** claim, which
 VWF must not make anyway. What a vblank over-claim really costs is declared
 **bytes** — 448 B/frame leaves 736 free rather than 1,152 — and that is the
 number to keep honest. `_register_exclusive`'s own docstring explains all of
 this; the draft warning was written without reading it.
- **Build order (review decision, 2026-07-28): VWF first, col_map second.**
 col_map is `rom` + `dp` with no contention surface at all — it can teach you
 nothing about the model. VWF is half the pair matrix's named hard case and the
 only feature that spends a budget. If either is going to stress the
 allocator, it is VWF, and you want that in week one. **Both are now done, in
 that order, and the call was right**: col_map's build surfaced no allocator
 question whatsoever. What it did surface is a gap in `tools/width_lint.py`
 (its own queued pass per)
 and one in `[init] zero`, which the allocator emits as *comments* and no gate
 proves — see. Neither is a claim-model question,
 which is itself the evidence that the model held.
- **The generator moves ahead of the pair matrix** (same review). Criterion 5
 was slipped on the reasoning that a hand-derived register "only drifts once
 features land". It drifted *during this pass* — `the working notes`'s own collider
 table still carried the corrected GRAD error after §1.3 had corrected it. So
 the generator's slot is **after VWF and col_map, before the pair matrix is
 called green**: declaring 21 pairs green against a register known to be stale
 is proving the wrong thing thoroughly, which is the objection that put the
 declaration↔implementation cross-check first.
 **Postscript (2026-07-29): the pair matrix was RETIRED, not run** — owner
 the settled option A. Derivation in:
 the "21 pairs" were asserted in four documents and defined in none, all 21 of
 the only coherent reconstruction already coexist *simultaneously* in the race
 scene, the allocator's checks are monotonic so pairwise runs over a composed
 set are provably vacuous, and "a pair" is undefined once `depends` exists. The
 sequencing argument above still stands on its own terms — a stale register is
 a bad thing to prove anything against — and the generator did in fact make the
 derivation possible, since `role` is what makes "which dirs are capabilities"
 machine-readable.
- **Three classes are missing, none blocking**: CPU-written PPU register
 ownership (live in the tree now), SRAM (blocks's SAVE), scanline IRQ
 (blocks a rail). Each should be designed before the phase that needs
 it, not during.
- **B2's four register names** (`BGnSC`, `BG12NBA`, `BG34NBA`, `CGADD`) are an
 afternoon, and any hires or multi-base composition needs them first.
- **`split_band` is the splitter.** A second split shape is a table
 parameterisation, not a new feature.
- ~~**The supply half is hand-derived and will drift.** Treat §1's claim columns
 and §3 as accurate as of `ecacc4a`.~~ **CLOSED 2026-07-28** — §3 is now
 GENERATED from the tree and gated by `make register`; it cannot drift without
 failing the build. **§1's claim columns are a different matter and are still
 hand-maintained** — see §3's preamble and the note below. Kept struck rather
 than deleted because the split between the two is the point.
 *(This bullet was still live, and still false, at — a prose bullet
 rather than a table row, so the demand lint's shape cannot see it. It is a
 working example of that gate's KNOWN LIMIT as well as a stale line.)*
