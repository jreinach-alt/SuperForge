# 05 — Combat and entities

> DRAFT SPEC. All speeds are in px/tick, scaled by `tick_scale`. All
> durations are in frames, and are class B unless marked (02 §7). The
> numbers are first-pass tuning.

## 1. Heroes

- **Movement.** 8-way, at 1.5 px/tick (8.8 fixed point).
  - Diagonals use 1.0625 px/tick per axis. That is an 8.8 approximation of
    √2/2, not a normalisation computed at runtime.
  - Armor's `move` field adds 0.25 px/tick per point.
- **Collision.** Per axis against the WRAM map:
  - The hero's box is 10×6 px at the feet. Top-down "foot box" collision lets
    the head overlap walls visually.
  - Move X, test 2 corner metatiles, resolve. Then repeat for Y.
- **HP.** Base 40, plus the armor's `hp` and VIGOR. Displayed as a bar (06 §3).
- **I-frames.** 30 frames after taking a hit, with the sprite blinking on
  alternate frames.
- **Knockback.** 6 px over 6 frames, away from the source, resolved through
  collision.

### 1.1 Melee (B)

- A swing is: wind-up 4 f → active 4 f → recovery, to the weapon's `rate`.
- The hitbox is an arc of the weapon's `reach` and `arc`, approximated as 1–3
  axis-aligned boxes in front of the hero:
  - arc ≤ 45°: 1 box
  - arc ≤ 120°: 2 boxes
  - arc > 120°: 3 boxes
- The swing sprite is one 16×16 entry in the hero's swing slot. Per weapon
  base there are 3 frames per direction × 4 directions, with diagonals using
  the nearest cardinal.
- A swing hits each enemy at most once.
- Hit-stop: 2 frames of freeze on the hit enemy only. It is cheap and reads
  as impact.

### 1.2 Ranged (Y)

- **Ammo:** one pool per player, maximum 40.
  - The bundle drop gives +10.
  - QUIVER regenerates 1 ammo per (120 − tier × 30) frames.
  - EMBER ROD uses no ammo.
- **A shot** is an 8×8 sprite from the shared shot pool:
  - speed: the base's `speed` value
  - lifetime: 90 frames
  - It stops on a wall, passes over chasm, and dies on hit unless it has
    PIERCE left.
- **SPLIT** fans 3 or 5 shots at ±15° steps, through a direction LUT of 16
  directions.

### 1.3 Dodge roll (A)

- 10 px/tick for 8 frames, i-frames for the first 12 frames, then a cooldown:
  - 90 frames by default
  - 120 frames in BULWARK PLATE
  - 70 frames in a JERKIN

  This is the genre reference's armor trade-off (research §A).
- A roll passes over nothing: chasms still block it. A roll over a chasm is a
  tier C idea and is NOT in scope.

### 1.4 Potion (X)

- Heals 60% of max HP. The cooldown is 2,700 frames (45 s), tick-scaled.
- The HUD shows a ready pip.

### 1.5 Artifacts (L/R)

Each artifact is a verb with its own cooldown (tick-scaled), in the 4–20 s
band.

| base | effect | entities used |
|---|---|---|
| BLAST JAR | throw an arc to the facing point 48 px away; a 32 px blast deals 3× power-scaled damage | 1 shot + 4 FX |
| MENDING POST | a 6 s zone that heals both heroes inside 40 px, at 2 HP/s | 1 FX entry |
| BLINK SASH | an 8 f, 40 px dash with full i-frames, passing through enemies (not walls) | 0 |
| HOUND CALL | summons a friendly hound actor for 15 s; it uses an actor slot and the enemy AI with its target set inverted | 1 actor |
| QUAKE BELL | stuns enemies within 40 px for 90 f | 4 FX |
| SUN LANTERN | 2 s of blinding light: enemies on screen are stunned for 60 f. On darkness floors (tier C) it opens the lantern window | screen flash via the fixed colour |

## 2. Enemies (tier M: 4 types + 1 boss)

The archetype names below are mechanical. Their in-world names and looks
(Rootling, Thornspitter, Cairnback, Mothwick, the Hollow Crown) are in
10 §5.

| type | size | HP @ threat | behaviour | telegraph |
|---|---|---|---|---|
| **grunt** | 16×16 | 12 | walk toward the nearest hero, swing at 12 px | 12 f flash |
| **archer** | 16×16 | 8 | keep 64–96 px away, fire 1 shot every 90 f | 16 f draw pose |
| **brute** | 32×32 | 40 | slow walk, 24 px slam | 24 f wind-up, ground FX |
| **skitter** | 16×16 | 4 | packs of 3, a fast zig-zag charge, then explode on contact | blink |
| **boss: the Warden** | 64×64, **drawn on BG2** (02 §1) | 300 | 3 phases: a slam ring (shots) → summons 2 grunts → charge across the arena | 30 f for every attack |

- **HP scaling:** `HP × MULT[threat_delta]`, and **+50% with 2 heroes**. That
  co-op factor is this spec's own tuning; the reference's figure was not
  found (research §A).
- **Contact damage:** 3 for a grunt, 0 for an archer (it fights only by
  shooting), 6 for a brute, 5 for a skitter's explosion.
- **Elites (tier S):** a grunt or brute with one armor enchant drawn from
  FX. Elites use OBJ palette 6, show a gold outline, and have a 128/256 gear
  drop chance.

### 2.1 Actor record (16 B `.struct`, 16 slots)

| field | bytes | meaning |
|---|---|---|
| type | 1 | |
| state | 1 | idle / move / windup / attack / hurt / dead |
| timer | 1 | |
| hp | 2 | |
| x, y | 2 + 2 | 12.4 fixed point |
| vx, vy | 1 + 1 | |
| facing | 1 | |
| target | 1 | which hero |
| flags | 1 | stunned, slowed, burning, elite, friendly |
| cell | 1 | owning room |
| spare | 1 | |

- **AI cadence.** "Think" runs every 4th frame, staggered by slot index:
  target selection, pathing, attack decision. Every frame runs only movement,
  collision and timers. This is how 10 enemies fit the 60k mc line in
  02 §4. Measure it.
- **Pathing.** Steer straight toward the target. If blocked on an axis, slide
  on the other axis. If blocked on both for 16 frames, take a random
  perpendicular step for 16 frames (an FX draw). Rooms are designed for
  that; there is no A*.

### 2.2 The Warden on BG2

- **Position.** The boss's world position drives BG2's scroll: `BG2HOFS = cam_x − boss_x`.
- **Poses.** A pose is a tilemap swap: 8×8 cells, queued through a whole-map
  DMA of the 64×64 px region (512 B) in one VBlank.
- **Hit-flash.** A CGRAM write of the boss palette: 32 B in VBlank.
- **Hitbox.** A box in world space. It has nothing to do with sprites.
- **Phases** are driven by the boss's HP thresholds.

## 3. Pack composition by threat

| floor | packs draw from |
|---|---|
| 1–2 | grunt ×3, or skitter ×3 |
| 3–4 | grunt ×2 + archer, or brute + grunt |
| 5+ | brute + archer ×2, or grunt ×2 + skitter ×3, plus a 1-in-8 elite |

A room with 2 `e` markers therefore has ≤ 6 enemies, inside the active cap of
10.

## 4. Feel (non-negotiable acceptance, judged in M5 play-test)

- **Every hit has 3 responses:**
  - a white flash (OBJ palette 7, 4 f)
  - hit-stop (2 f)
  - a hit SFX (the existing `hit` cue)
- Every enemy attack is telegraphed for at least 12 frames.
- **Damage numbers:** none at tier M. HP bars on bosses only.
