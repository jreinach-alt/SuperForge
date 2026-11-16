# 02 — Architecture and budget

> DRAFT SPEC. Capability evidence: `research/kit_capabilities.md`. Every
> number tagged **(est.)** is an estimate and MUST be replaced by a
> measurement before the milestone that relies on it closes (CLAUDE.md
> rule 1). Every number tagged **(pin)** is a measured value from
> `allocator/substrate.toml`.

## 1. The picture (Mode 1)

| layer | job | notes |
|---|---|---|
| **BG1** | the whole floor | `tiles16`, 64×64 tilemap = 1024×1024 px, 4bpp. **Resident**: uploaded once in `floor::enter` under forced blank, never streamed. Wall-top metatiles set the tilemap priority bit, so a hero at OBJ priority 2 walks *behind* them. That gives depth with no second layer. |
| **BG2** | **the boss** | 32×32 tilemap, 4bpp, composed only in the boss room's state. The boss is a background that moves by scroll: the kit's "a really big thing should be the background" lesson (`docs/hardware_for_your_idea.md`). It costs 0 OAM entries and 0 per-line slivers, against the 16 entries and 8 slivers a 64×64 sprite boss would take. Outside the boss room BG2 is disabled in TM. |
| **BG3** | HUD text | `bg_text`, 2bpp, high priority (BGMODE b3). Top 2 rows: P1 HP / ammo / cooldowns on the left, P2 on the right. |
| **OBJ** | heroes, enemies, shots, drops, FX | 16×16 / 32×32 OBSEL pair (§3). |

**Why one resident BG1 floor.** The generated floor is exactly 64×64 metatiles
(03 §2). In 16×16-tile mode that is one 64×64 tilemap, 8 KB of VRAM.

- **What it buys:**
  - No streaming at all. The kit's 2-axis streamer reads ROM blobs, and
    rebuilding it for WRAM would cost 64 KB.
  - No per-frame VRAM traffic for the map, apart from the door/chest cell
    queue.
  - Camera motion is free: two scroll registers.
- **What it costs:**
  - The first `tiles16` rail in the tree. `docs/100` states that nothing checks
    the CHR page's `N/N+1/N+16/N+17` quad layout. **The asset generator owns
    that invariant, and a test asserts it from VRAM** (08 M2).

### 1.1 VRAM plan (declared, never hand-placed: the allocator emits the bases)

| claim | size | note |
|---|---|---|
| BG1 tilemap 64×64 | 8 KB | `shape = "64x64"` (proven by `pfs_bg`) |
| BG1 CHR, 4bpp | ≤ 16 KB | ≤ 128 metatiles × 4 tiles × 32 B, laid out in 16-wide rows for the quad |
| BG3 tilemap + 2bpp font | ~4 KB | `bg_text` / `text_chr` |
| OBJ CHR, two name tables | 16 KB | table 0: **4 streamed slots** (hero 1, hero 2, swing 1, swing 2: 16 tiles), plus shots, drops, FX and pips, resident. Table 1: the floor's enemy set, resident, uploaded at enter (§1.2) |
| BG2 boss CHR + 32×32 map | ≤ 10 KB | the boss's poses as BG tiles |
| **total** | **≤ 54 KB of 64 KB** | leaves ~10 KB headroom (est.). The allocator proves the fit at M2 |

### 1.2 Why the heroes are streamed (the arithmetic)

The resident option was tried on paper and refused:

- Hero frames are 44 frames × 4 tiles = 176 tiles.
- Swing frames are 45 frames × 4 tiles = 180 tiles.
- That is **356 tiles against a 256-tile name table**, before shots and FX.

**Decision:** every frame, DMA the current frame of each hero and each swing
from ROM into 4 fixed 16×16 slots.

- Cost: 4 × 128 B = 512 B, plus 4 × 128 B arm cost = **1,024 B-equivalent of
  the 5,952 B VBlank pin**. Together with OAM's 544 B, that leaves about
  4.3 KB for the HUD queue and the cell queue.
- **A new feature in this tree (`obj_stream`), with a shipped precedent.**
  SUPERFORGE GT streams one car frame per VBlank from ROM into fixed VRAM
  slots: 1.3 MB of frames through 16 KB (`sf-gt:README.md`). Port its
  mechanism. It declares `[claims.dma]`, and its test reads the 4 slots out of
  VRAM after a known input sequence and compares them against the frame
  blob.
- Enemies stay resident in table 1: about 140 tiles, with side-facing frames
  and left by HFLIP.

### 1.3 CGRAM plan

| palettes | use |
|---|---|
| BG 0–1 | HUD. Mode 1's BG3 is 2bpp, and its 8 sub-palettes are CGRAM words 0–31, the same words as BG palettes 0–1. So 0–1 belong to the HUD, and BG1 does not use them |
| BG 2–6 | biome: floor, walls, chasm, braziers, doors/chests |
| BG 7 | the boss (BG2). Its hit-flash rewrites this palette for 4 f |
| OBJ 0 / 1 | P1 hero / P2 hero (the same CHR, palette swap: the `split_v_obj` precedent) |
| OBJ 2 / 3 | P1 drop tint / P2 drop tint (instanced loot, 06 §4) |
| OBJ 4–6 | enemies (biome set) |
| OBJ 7 | the **flash** palette: all-white, used for hit-flash by swapping the attribute (zero DMA) |

## 2. WRAM and DP plan (all through `state.toml`; symbols are `US_*`)

| state | scope | size | note |
|---|---|---|---|
| floor map | **global** (see §6) | 4,096 B | one byte per metatile; doubles as the collision grid (03 §4.1) |
| cell grid + door masks | global | 16 B | the 4×4 macro grid |
| spawn table | global | 32 × 3 B | type, mx, my |
| actor table | global | 16 × 16 B (`.struct`) | enemies (§4) |
| shot table | scene `floor` (shots in flight are dropped on pause; fine) | 24 × 8 B | shared player/enemy pool (`pool`) |
| drop table | global | 12 × 8 B | gear and consumables on the ground |
| hero state ×2 | global | ~48 B each | pos, HP, cooldowns, i-frames, facing, downed timer |
| equipped ×2 | global | 5 × 4 B each | the item records (04 §2) |
| stash | global | 24 × 4 B | camp storage, shared |
| run state | global | ~16 B | run seed, floor index, lives, pity ×2, sparks ×2 |
| GEN / FX PRNG | global, `@dp` | 2 × 2 B | 03 §2.3 |
| camera | scene `floor`, `@dp` | 4 B | |

### 2.1 The save (battery SRAM: decided)

The kit's `save` feature is proven: CRC-16, magic and version, reject codes,
and a power-cycle test. Its **24 B payload cap is a constant, "a choice, not a
law"** (`engine/features/save/feature.toml`). Dungeons raises it. The save
record:

| field | bytes |
|---|---|
| equipped kits, 2 × 5 × 4 B | 40 |
| stash, 24 × 4 B | 96 |
| sparks ×2, deepest floor, lives meta, options | 8 |
| **payload** | **144 B** |

- No separate spark ledger is needed. Sparks spent on an item are its enchant
  tiers above I, which are already in the record (04 §2). Salvage refunds
  read them from the record.
- 2 slots × (8 B header + 144 B) = 304 B. The `sram` claim grows from the
  feature's 64 B. The allocator already derives the cart header from the
  claim: `$FFD8 = $01` (2 KiB declared, the minimum) and `$FFD6 = $02`
  (battery), both read from `engine/features/save/feature.toml`. So 304 B
  changes no header byte.
- The CRC routine's cost grows with the payload. **Measure it** in M7. It runs
  at camp only, never in a floor frame.
- **Change the feature, not a copy of it.** Raise the cap in `save` itself:
  turn the constant into a declared parameter, and keep `platformer`, `room`
  and `rpg` byte-identical. Their tests are the regression guard.

### 2.2 DP

DP is the scarcest class. Only these go `@dp`:

- the PRNG states
- the camera
- the hero X/Y pairs (split_v_fight's `u16[2]@dp` shape)
- the per-frame scratch the hot loops need

## 3. OAM budget (128 entries; the per-line limit is a HAND LEDGER)

The allocator proves the 128 total. **It does not model 32 sprites or 34
slivers per scanline.** That ledger is written by hand here, the way
`railshooter` keeps its 22-of-34, and is re-measured in M5.

| block | entries | size | slivers on one line, worst |
|---|---|---|---|
| heroes | 2 | 16×16 | 4 |
| weapon swing | 2 | 16×16 | 4 |
| enemies | 10 active | 16×16 (a brute counts as 32×32) | 2 each, or 4 for a brute |
| shots | 16 | 8×8 small | 1 each |
| drops | 8 | 8×8 small | 1 each |
| FX (hits, puffs) | 8 | 8×8 | 1 each |
| ping / downed marker | 2 | 8×8 | 1 each |
| boss | 0 | it is BG2 (§1) | 0 |
| **total pinned** | **≤ 48** | | |

**Design rules that keep the line ledger under 34:**

1. **Enemy cap.** At most 10 active enemies, and at most 1 brute per pack.
   Room templates already spread `e` markers vertically (03 §5); packs spawn
   in a vertical column formation.
2. **OAM rotation.** The emit start index rotates each frame (new: 06 §6). An
   overflow then shows as flicker, never as a stable hole.
3. **The M5 test boots the worst authored room** (the arena template, full
   pack, both heroes on one row, max shots) and reads **STAT77's
   range/time-over bits** every frame for 600 frames. They must stay clear
   with rotation off. That is the real ledger proof.

## 4. CPU budget (NTSC, per frame)

A reference worst 60 fps frame is 305,348 mc (pin). Targets below are in
master clocks, and every one is to be **measured** with the repo's
active-line/cycle tooling in the milestone that lands it.

| work | target (est.) | note |
|---|---|---|
| NMI + OAM DMA + HUD queue | 20,000 | the pinned NMI is 16,800 |
| input ×2, camera, leash | 3,000 | |
| hero logic ×2 (move, collide, attack) | 12,000 | collision is a WRAM-grid lookup, `(y>>4)<<6 | x>>4`. NOT `col_map` (951.9 mc a query, pin) |
| enemy AI × 10 | 60,000 | 6k mc each, all-in |
| shots × 16 vs targets | 30,000 | cell-bucketed: a shot tests only actors in its 2×2 metatile neighbourhood |
| drops, FX, cooldowns | 8,000 | |
| OAM build (rotation, 64 entries) | 25,000 | |
| audio tick | 438 | pin |
| **sum** | **~158,000 (est.)** | roughly half the frame. The other half is the margin this budget is entitled to |

**Rule:** if a measured line exceeds its target by 25%, stop. Either cut the
cap (enemies, shots), or move the work to a 2-frame cadence (AI think on even
or odd frames per actor index). Never let a frame run long: 60 fps is
pillar 4.

## 5. ROM budget (512 KB, 16 windows; window 0 is code)

| blob | size (est.) |
|---|---|
| code (all scenes) | ~40 KB, spills to window 1 if needed |
| room templates (13 now, 40 at tier S) | 40 × 196 B ≈ 8 KB |
| metatile → tilemap-entry table, autotile LUT | ~1 KB |
| BG CHR per biome × 3 | 3 × 16 KB |
| OBJ CHR: hero + swing frames (streamed source) | ~24 KB |
| OBJ CHR: shots, drops, FX (resident) | 4 KB |
| OBJ CHR: enemy sets × 3 | 3 × 8 KB |
| boss BG CHR × 2 | 2 × 10 KB |
| item / enchant / enemy tables | ~2 KB |
| text (names, UI) | ~4 KB |
| TAD audio (driver + songs + SFX) | ~64 KB |
| **total** | **≈ 235 KB of 480 KB usable** |

## 6. Scenes

```
title ──► camp ──► descend ──► floor ──► descend ──► floor ... ──► results ──► camp
             ▲         (card: "FLOOR n",           │ boss down: stairs     │
             └──── pause/inventory is a scene ◄────┘ both down: results ───┘
```

- **`descend`** exists because `sm_request` to the running scene is a no-op.
  `floor → floor` cannot be expressed, so the stairs pass through a card
  scene. The card shows the floor number and the 4-hex-digit seed, and runs
  under a fade that hides `floor::enter`'s forced-blank generation.
- **Generation happens in `floor::enter`**, under forced blank and NMI-masked
  as the house pattern requires. Target: under 30 frames (est.) of black,
  measured in M2.
- **`inventory`** is its own scene. A running scene gets only 4 BG3 cells per
  frame, and the gear screen needs a full text rebuild. **That is why the
  floor's persistent state (map, actors, drops) is `[global]` and not
  scene-scoped.** Scene-scoped bytes are reused by the next scene by
  construction, so a scene-scoped floor would be wiped by opening the
  inventory. WRAM is plentiful (about 5 KB for all of it), and DP is not
  touched.
  - `floor::enter` reads a `resume` flag. When it is set, enter re-uploads the
    BG1 tilemap from the WRAM map instead of generating.
  - **Test: after a floor → inventory → floor round trip, the VRAM tilemap and
    the actor table are byte-identical** (08 M7).
  - 09 Q4 covers the alternative of an in-scene overlay.

## 7. Region

Compose `region` + `tick_scale`, as every playable rail does.

- **Movement and projectile speeds** are rate quantities and are scaled.
- **Cooldowns and i-frames** are integer frame countdowns: class B, not
  scaled. Their PAL duration is disclosed in `game.toml`, as `shmup` does.
- **Exception:** the potion and artifact cooldowns are long enough that the
  ~17% PAL stretch is a balance change. Store them as tick-scaled countdowns
  (decrement by the scaled step), and say so in `game.toml`.
