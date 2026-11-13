# Research — the genre reference and its precedents

> Gathered 2026-11-13 by web research. Sources were mostly fan wikis and the
> press. The reference studio's own development article returned HTTP 503
> during research, and an engine-vendor spotlight returned 403, so their
> content arrived only through search excerpts. Claims marked
> **[unverified]** could not be confirmed.
>
> **Naming rule.** The reference game, its studio, and named precedents are
> NOT named in this tree. `make cleanroom` refuses those names; the denylist
> entries were added with this spec set. Specs call it "the genre reference".
> The source URLs are kept in the session record rather than here, because
> most of them carry the names in their paths. Generic technical sources,
> which carry no retail name, are cited inline.
>
> Use: this file is what the specs were derived FROM. It is secondary
> material. Where a spec number differs from a figure here, the spec is the
> decision and this file is the evidence it weighed.

## A. The classless gear model of the genre reference (2020)

- **No classes.** Gear is the build.
  - Equipment slots:
    - one melee weapon
    - one ranged weapon
    - one armor
    - up to three artifacts (active items)
  - Each artifact has its own cooldown, and cannot be swapped while it is
    cooling down.
  - Cooldown bands:
    - short: 1.5–3 s
    - mid: 4–6 s
    - long: 15–30 s
  - Some artifacts spend a "soul" resource instead.
- **Power level.** This is the gear score: the average of the equipped
  items' power.
  - Drops scale to the hero's power at mission entry, not to character level.
  - The per-item stat formula was never published.
- **Enchantments.**
  - Weapons and armor have up to 3 enchant slots. Each slot offers up to 3
    random choices, and the player picks 1.
  - Each enchant has tiers I–III. Points cost 1/2/3 for common enchants and
    2/3/4 for powerful ones.
  - Players earn 1 point per character level.
  - Salvage refunds every point and pays currency. This makes respec free,
    and free respec is what lets gear define the build without a class.
  - Example curve: a ranged damage enchant gives +10% / +21% / +33%.
- **Uniques.** A unique is a fixed variant of a base item with a built-in
  enchant. Some enchants exist only on uniques.
- **Ammo.** One global arrow pool per player. Weapons differ in quiver size.
  Bundles refill it.
- **Dodge roll.** About a 3 s cooldown. Heavy armor can double it, which is a
  build trade-off.
- **Healing potion.** Heals about 75% of max HP, on a 45 s cooldown. Some
  gear shortens the cooldown.
- **Co-op loot.**
  - Gear and currency are per-player and instanced, so nobody leaves empty
    handed.
  - Ammo and consumables are shared.
- **Difficulty.** Three modes, with 7 threat levels each.
  - Threat raises enemy HP and damage by roughly 1.3× per step. It also raises
    drop power and adds enemies.
  - Auto-balance uses the party's average power.
  - The exact per-player co-op scaling factor was not found.
- **Down and revive.** A downed ally can be revived within about 30 s, at
  partial HP. Otherwise the party loses a life from a shared pool.
  The pool size is **[unverified]**, recalled as 3.

## B. How the genre reference builds levels

What is established from developer statements reported by the press:

- Levels are assembled room by room, not block by block. The rooms are built
  by hand in an editor and then play-tested for flow and sightlines.
- Designers place "puzzle pieces" for the engine to arrange, either in a fixed
  way or at random.
- Each level has designer controls:
  - a room count
  - mandatory rooms at predefined points
  - ordered room groups: the order of the groups is fixed, and the rooms
    inside each group vary
- The stated reason for this hybrid: pure procedural generation "doesn't take
  into account pacing".
- No published algorithm or conference talk was found.

**Inferred shape.** The levels are hand-authored rooms stitched along a
designed spine, with random choice inside slots. This spec set adopts that
shape (03 §1).

## C. Generators that fit a small budget

**4×4 room grid with a solution path.**
This is a well-known 2008 roguelite platformer's generator, documented at
<https://tinysubversions.com/spelunkyGen/>.

1. Start in the top row.
2. Each step, roll to move left, right or down. The walk is the guaranteed
   solution path.
3. Each cell takes a hand-authored template with the exits it needs.
4. Off-path cells get filler templates.

Cost is O(cells) and a few bytes. It is the best fit for pre-authored chunks.
For a top-down game, generalise the exits into a 4-bit N/E/S/W door mask per
cell, which is what 03 does.

**Other generators.**

- **BSP.** <https://www.roguebasin.com/index.php/Basic_BSP_Dungeon_generation>
  Connected by construction, O(n log n). Its rooms do not match pre-drawn
  chunks.
- **Cellular automata caves.**
  <https://roguebasin.com/index.php/Cellular_Automata_Method_for_Generating_Random_Cave-Like_Levels>
  On a 64×64 grid this is about 130k neighbour reads plus a 2 × 4 KB double
  buffer. That fits under forced blank, but the result is organic and fights
  chunk art.
- **Drunkard's walk.** Cheap and connected. Useful as a spur carver.

**PRNGs.**

- xorshift16, triple (7, 9, 8): 2 bytes of state, period 2¹⁶−1.
  6502 ports are published.
  - Background: <https://en.wikipedia.org/wiki/Xorshift>
  - The NESdev RNG page: <https://www.nesdev.org/wiki/Random_number_generator>
- A 16-bit period is small, so keep **two streams**:
  - a generation stream, seeded per floor
  - a gameplay stream, so that combat RNG never moves the layout
- A seed can be shown as 4 hex glyphs, for sharing.

## D. 16-bit precedents (studied, not copied)

- **A 1993 three-player action RPG** used a shared screen with drop-in co-op.
  - Characters could stick on terrain at scroll edges.
  - Its dungeons ran smoothly *because on-screen enemies were capped*.
    Slowdown was in its uncapped towns.
  - Its producer said multiplayer shaped "field design, and also the tempo".
- **A 1993 two-player top-down shrine shooter** also used one shared screen.
  - It had a co-op move: slide into your partner to launch them.
  - Some stages lagged.
- **A 1993 two-player top-down horror-comedy shooter** varied its weapons per
  enemy type, which is a cheap build system.
  - Its developer wanted battery save and could not afford it, so it used
    passwords. That is the same constraint as an SRAM-less jam entry.
- **Super Famicom random dungeons** existed in a turn-based roguelike series
  (1993, 1995). The games had 30 random floors. Being turn-based sidesteps
  the per-frame CPU limit.
- **Sprite-limit flags.** Range Over (>32 sprites per line) and Time Over
  (>34 slivers per line).
  - <https://sneslab.net/wiki/Range_Over>
  - <https://sneslab.net/wiki/Time_Over>
  - A sprite parked at X = −256 still counts against the limit:
    <https://snes.nesdev.org/wiki/Errata>
  - OAM-order rotation is the usual mitigation, turning dropout into flicker.

## E. Shared-screen co-op camera

There are three classic options:

- split screen
- follow one player
- keep everyone in frame and only scroll when everyone fits

Modern games zoom out. The genre reference never splits: it zooms a little
and offers a teleport-to-ally item.

The SNES cannot zoom a Mode 1 layer, and split screen in this kit costs every
BG layer (research/kit_capabilities.md §2). That leaves one practical choice:
a **centroid camera with a hard leash**, plus a warp-to-partner for a
straggler. 06 specifies it.

## F. Loot with few bytes

- **Tiered affixes.** Normal → magic (≤1 prefix + ≤1 suffix) → rare →
  unique, where unique items carry fixed affixes. This is the classic
  action-RPG lineage.
- **Pity and bad-luck protection.**
  - hard pity at N misses
  - soft pity ramps
  - shuffle bags
  - One counter byte per player is enough on the SNES.
- **Store the roll inputs, never the derived stats.** Derive stats at use
  time from ROM tables. 04's 4-byte record is this principle.
