# 08 — Milestones (the build order for the implementing agent)

> Each milestone is **independently shippable and independently testable**.
> Every one closes on the same bar:
>
> 1. The ROM builds, and `make <rail>` + `make rail-registered` +
>    `make register` + `make width-check` are green.
> 2. The milestone's tests **read rendered output**: VRAM, OAM, CGRAM, or a
>    screenshot at an absolute frame. They never read a proxy variable
>    (CLAUDE.md rule 2).
> 3. A **fresh render from the built binary** is attached to the report
>    (rule 3).
> 4. Every **(est.)** number the milestone relies on has been **measured**,
>    and the measurement is written back into the spec.
> 5. `make bare-check` is green on the pushed tip, and `build/bare_check.json`
>    is cited.
>
> Work in ≤50-line ASM / ≤30-line Python steps, building and testing as you
> go. Never write more than 100 lines without a build.

## M0 — Scaffold (`game/dungeons`)

- Fork `game/microzero`'s shapes, per `docs/lessons/04`.
- Scenes: `title`, `descend`, `floor`. Each is a `bg_text` + `backdrop` card
  naming its gap ("GAP: GENERATOR").
- Compose `region` + `tick_scale` + `input` + `input2` from day one.
- **Test:** boot, press Start, and read the BG3 cells of the descend card.

## M1 — `rng` feature + seed capture

- Write `engine/features/rng`: xorshift16 per 03 §2.2, two DP states, with no
  `[init] zero` (the seed is explicit).
- Record a **measured** cycle count in its `feature.toml`.
- `run_seed` = `sm_frame` sampled at the title press, forced nonzero.
- The descend card prints `SEED XXXX` (4 hex digits).
- **Tests:**
  1. Under lockstep `Machine`, press Start on frame F. The card's glyph
     cells spell `level_seed`'s input as the oracle computes it from F.
  2. A probe scene draws 4 values from state 1 and prints them. The glyphs
     must read `8181 6021 E999 2E0B`.

## M2 — Generator + `dgn_bg` (the first `tiles16` rail)

- Extend the oracle first: `levelgen.tilemap(lv)` (03 §4.2 autotiling), and
  a template-blob packer in `tools/gen_dungeons_assets.py` that runs
  `lint_templates`.
- ASM `dgn_gen` (role `game_logic`) runs in `floor::enter` under forced blank
  with NMI masked, then DMAs the 8 KB tilemap.
- **Tests:**
  - For seeds {1, `$BEEF`, `$1234`} × floors {0, 4, 8}:
    - The VRAM BG1 tilemap equals `tilemap(lv)` word for word.
    - The WRAM map equals `lv.tiles`.
    - The spawn table equals `lv.spawns`.
    - The GEN draw count equals `lv.draws`.
  - The CHR quad layout: for 5 metatiles, VRAM CHR at N, N+1, N+16 and N+17
    equals the generator's 16×16 source.
  - **Measure** the generation time in frames. The target is under 30.
  - A screenshot, with the camera placed at the start marker.

## M3 — Two heroes on the floor

- Features: `obj_stream` (02 §1.2), hero movement and foot-box collision
  (05 §1), and the camera with the spread leash (06 §2).
- **Tests:**
  - **Collision invariant.** Drive 600 frames of scripted input for both pads
    into walls and chasms. On every frame, the hero OAM position + camera
    → world foot box overlaps no non-walkable metatile of the oracle map.
  - **Leash invariant.** Drive the pads apart for 300 frames. The OAM-derived
    world positions never exceed the 224/176 spread.
  - **Stream slots.** After a known input, VRAM in the 4 streamed slots
    equals the generator's frame blob for the expected animation frame.
  - A screenshot of both heroes, P1 blue and P2 amber, from CGRAM.

## M4 — Combat core

- Melee, ranged, roll and potion.
- The actor pool (16 × 16 B `.struct`) and the shot pool (`pool`).
- Grunt and archer AI with a 4-frame think stagger.
- Packs spawn on room entry. Gates seal and open through the 4-cell queue.
- Hit-flash (OBJ palette 7), hit-stop, the `hit` SFX.
- **Tests:**
  - Entering a pack room puts gate metatiles into the VRAM tilemap within
    2 frames, and they clear within 2 frames of the last kill.
  - A melee hit puts OBJ palette 7 in the enemy's OAM attribute for 4 frames.
  - An enemy's death removes it from OAM (it parks).

## M5 — The line ledger and the frame budget

- Land `obj_rotate`.
- Build the worst-case room: an arena template, 2 full packs, both heroes on
  one row, 16 shots.
- **Tests:**
  - STAT77 range/time-over stay clear for 600 frames with rotation off.
  - Under the planted 12-in-a-row overload, every enemy is drawn in at least
    1 of every 3 frames.
  - **Measure every line of 02 §4** and replace each (est.).
  - Zero dropped ticks over 600 frames.

## M6 — Loot

- Kill drops (instanced and tinted), chest rolls (GEN), pickup, the backpack.
- The `inventory` scene, plus the floor `resume` round trip (02 §6).
- **Tests:**
  - A chest's record in WRAM equals `Roller.roll` for the GEN state at
    generation.
  - The inventory scene's BG3 cells spell `describe(record)`.
  - floor → inventory → floor leaves the VRAM tilemap and the actor table
    byte-identical.

## M7 — Down, revive, lives; `results`; `camp`; persistence

- The 06 §5 rules, the camp scene, salvage and sparks.
- Save, which depends on **09 Q1**.
- **Tests:**
  - A downed hero's OAM shows the downed frame.
  - The partner's held A for 90 frames restores HP: the HUD bar cells
    change.
  - Timer expiry decrements the lives digit on the descend card.
  - A save round-trips through a power cycle (the `test_c2_slice_c` pattern).

## M8 — Content to tier M

- All 21 enchants (through the 5 hooks) and all 6 artifacts.
- The brute and the skitter.
- `enemies.toml`, with the pack tables of 05 §3.
- **Tests:** one rendered-output test per artifact. Each one asserts its
  visible effect: an FX OAM entry, the stunned enemy's frozen OAM position,
  or the healed HUD cells.

## M9 — The Warden (BG2 boss)

- Implement 05 §2.2.
- **Tests:**
  - BG2 scroll registers track `cam − boss` (read the PPU shadow-owner's
    emitted state, or a screenshot column).
  - The pose swap lands in the BG2 tilemap in one VBlank.
  - The exit stairs are inert until the boss's HP reaches 0, then `descend`.

## M10 — Audio, region, determinism, ship

- Songs and SFX (07 §4).
- `rate_oracle` measures region parity inside the fleet band (`docs/98`).
- `make determinism MODULE=tests/test_dungeons.py`.
- `make falsify` with a dungeons plant: break the leash or a door gap, and a
  named test must go RED.
- A flashcart run on NTSC (and PAL if available), recorded in `JAM.md`'s
  shape.

## Dependency graph

```
M0 ─► M1 ─► M2 ─► M3 ─► M4 ─► M5 ─► M6 ─► M7 ─► M8 ─► M9 ─► M10
                    └──── the asset generator grows alongside every milestone ────┘
```

- M5 deliberately comes **before** loot and content. It is the milestone that
  can force a design cut (fewer enemies, an AI cadence change). Taking that
  cut later would invalidate more work.
- M6 and M7 can swap order if 09 Q1 is still open.
