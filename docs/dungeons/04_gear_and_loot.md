# 04 — Gear and loot

> DRAFT SPEC. **Oracle:** `tools/dungeons/loot.py`. **Tuning data:**
> `tools/dungeons/data/gear.toml`. That file contains 22 bases and 21
> enchants, all with original names. Tuning is a data edit, never an ASM
> edit: the asset generator packs `gear.toml` into ROM tables.

## 1. The model: gear is the build

Each hero equips **5 items**: melee (B), ranged (Y), armor, artifact 1 (L),
artifact 2 (R).

Nothing else defines the character:

- no class
- no skill tree
- no stat allocation

Two levers make this work in the genre reference, and both are kept here:

1. **Every item changes how you play, not just your numbers.**
   - A MAUL is a slow 140° crowd-clearer. TWIN KNIVES are a 10-frame
     single-target blender.
   - An ARBALEST pierces. An EMBER ROD needs no ammo but its shots are slow.
   - BULWARK PLATE trades speed for damage reduction.
   - Artifacts are whole verbs: throw a bomb, plant a heal zone,
     phase-dash, summon a hound, stun ring, light burst.
2. **Respec is free.**
   - Swapping is instant at camp and from the inventory scene.
   - Salvaging refunds every spark invested.
   - A player is never locked in, so experimenting costs nothing.

**Co-op roles emerge from gear.** BOND (heal your partner) and RALLY (revive
your partner faster) are armor enchants that only matter with two players. A
pair naturally splits into "front" and "support" without either player
picking a role.

## 2. The item record: 4 bytes, the roll not the stats

```
byte 0  base id                      (gear.toml [[base]].id; the slot is implied by the base)
byte 1  power                        1..255
byte 2  enchant 1  = id << 3 | tier  (id 0 = empty; tier 1..3, 0 = locked)
byte 3  enchant 2  = id << 3 | tier
```

- **Rarity is derived, not stored.**
  - **unique**: the base is a unique.
  - **rare**: enchant 2 is present on a non-unique.
  - **common**: anything else.
- **Artifacts carry no enchants.** Their power alone scales their effect, and
  their rarity reads as common.
- **Stats are computed at use time** from the base table plus power, and are
  never stored. This is the principle in research §F.
- Two heroes' equipped kits are 40 B. A 24-item stash is 96 B.

## 3. Power and threat

- `floor_threat = 1 + floor × 2`, capped at 250.
- Item power = `floor_threat + offset`.
  - `offset` is drawn from `[-2, -1, 0, +1, +2]` with weights 16/48/96/64/32.
  - Rare items get +1. Uniques get +2.

**Effectiveness is relative, which is how the numbers stay 8-bit:**

```
delta = clamp(weapon_power − enemy_threat + 8, 0, 15)
dmg   = base_dmg × MULT[delta] >> 4        ; MULT[] = 16-entry ROM table, 8 = ×1.0
```

The same rule runs in the other direction, armor power against enemy threat,
for incoming damage. Being 2 floors under-geared is felt. Being 4 under is
punishing.

**Gear score** is the average power of the 5 equipped items. Camp shows it
for both heroes. The `descend` card recommends a floor where the
**pair's average** gear score is within 2 of the threat. That is the
genre reference's party-average auto-balance (research §A).

## 4. Enchantments

- **21 enchants**, each with 3 tiers. Magnitudes per tier are in `gear.toml`.
- Each enchant lists the slots it can roll on. Some roll on 2 slots (EMBER,
  FROST, TITANBANE).
- **Rolled items start every enchant at tier I.**
- **Sparks:**
  - Each hero earns 1 spark per floor cleared.
  - At camp, a spark raises one enchant on one item by one tier, up to III.
  - Salvaging an item refunds every spark spent on it.

  This is the genre reference's enchant-point loop, minus character levels.
  Floors are the level-up.
- **Uniques** carry a fixed signature enchant at tier II in slot 1, plus one
  rolled enchant in slot 2.
- **Implementation order:** each enchant is one small hook in one of five
  places:
  - on-hit
  - on-kill
  - on-damaged
  - on-dodge
  - per-second

  M6 lands the hooks with 4 enchants. M8 fills in the rest from the table.

## 5. Drops

- **Kills** roll from the FX stream. The chance out of 256 is per enemy class
  (`[drops]`).
  - Gear drops are **instanced**: each roll produces one item *per player*,
    tinted in that player's OBJ palette. Only the owner can pick it up.
  - Consumables (ammo, a potion refill, sparks) are **shared**: either player
    can take them.
  - Both rules are the genre reference's (research §A).
- **Chests** are rolled from GEN at generation time, so they are part of the
  seed. A chest holds 1 item per player.
- **The boss** drops 1 guaranteed item per player, rare or better.
- **Pity:** one byte per player. After 6 commons in a row, the next roll is
  rare.
- **Pickup:** walk over your own drop.
  - If the slot is empty, it auto-equips.
  - Otherwise it goes to the backpack: 6 per hero, carried in-run.
  - A full backpack shows "FULL" on the HUD and leaves the drop where it is.
  - At camp, the backpack empties into the shared stash.

## 6. Measured oracle behaviour (20,000 rolls at floor 5)

| | count | share |
|---|---|---|
| common | 14,574 | 72.9% |
| rare | 4,402 | 22.0% (the weight is 25%; the 8 points of headroom are artifacts, which fold to common) |
| unique | 1,024 | 5.1% |

## 7. Tests the ROM must pass (M6)

- For a fixed stream state, the record the ROM writes into the stash slot is
  byte-identical to `Roller.roll`'s output, and its draw count is equal.
- **Asserted on rendered output:** the item name is printed on BG3 by the
  inventory scene. Read the BG3 tilemap cells and compare them against the
  glyph indices of `describe()`'s text. Do not read a "current item"
  variable.
