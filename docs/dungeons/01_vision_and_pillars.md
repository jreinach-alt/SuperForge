# 01 — Vision and pillars

> Status: DRAFT SPEC, pre-implementation (2026-11-13). Read 00_README.md for
> how this set is used. Everything here is ORIGINAL: no names, characters,
> art, item names or levels from any commercial game. The genre reference is
> referred to as "the genre reference". Its design lessons are recorded in
> `research/genre_reference.md`; its name stays out of the tree, because
> `make cleanroom` would refuse it and should.

## 1. One sentence

Two friends on one couch, one SNES, one screen: they dive a freshly generated
dungeon floor, and the gear it drops decides who becomes the brawler, the
archer or the healer this run. Nobody picks a class.

The world is **Lumenvale**, a storybook realm being erased from the edges
inward by a silence called the Unwriting. The look is luminous 80s fantasy:
painted, dusty, vast. The score is 80s orchestral, with war brass and synth
mystery. See 10 and 12.

## 2. Pillars (in priority order: when two collide, the higher one wins)

1. **Couch co-op first.** Every system is designed for two players sharing one
   screen. Single player is supported, but it is the case that has to fit the
   two-player design, not the reverse. Concretely:
   - a shared camera,
   - instanced gear drops,
   - a downed/revive loop,
   - partner-facing gear (BOND, RALLY).
2. **Gear is the build.** No class, no skill tree.
   - A player's playstyle is entirely their five equipped items: melee, ranged,
     armor and two artifacts.
   - Swapping is free and instant at a camp, and allowed mid-floor from the
     pause screen.
3. **Every floor is new, every floor is fair.** Floors are stitched from
   hand-authored rooms along a generated critical path. Pure noise is not used.
   - Every floor is provably completable: the generator's oracle checks
     reachability, and the ROM test asserts it.
   - Pacing comes from authored rooms, so it is a design decision, not luck.
4. **Hard 60 fps, no slowdown, ever.** This is the house rule of this engine.
   Enemy counts, projectile counts and effects are capped by design, and the
   caps are measured (see 02 §3).
5. **Readable on a CRT.** A 16×16 hero must read at a glance:
   - silhouette first,
   - player-tinted palettes (P1 blue, P2 amber),
   - telegraphed enemy attacks (a flash or wind-up of at least 12 frames).

## 3. The core loop

```
 CAMP (hub)  ── pick floor depth ──►  FLOOR n (generated)  ── boss ──►  REWARD
    ▲   equip / salvage / upgrade          │  rooms: fight packs, chests,     │
    │                                      │  optional treasure branches      │
    └──────────── return (or descend) ◄────┴── both downed: lose a life ◄─────┘
```

- **One floor** is a playable target of 5 to 10 minutes: 5 to 9 path rooms,
  0 to 2 treasure branches and 1 boss room (03 §3).
- **One run** is an "expedition": floors 1, 2, 3 and so on until the party
  returns or runs out of lives. Depth raises the threat (04 §3), which raises
  drop power.
- **Persistence:** the camp stash plus each player's equipped set, saved to
  battery-backed SRAM (02 §2.1). This is not a jam entry, so the jam's no-SRAM
  rule does not apply (owner, 2026-11-16).

## 4. The controls (both pads identical)

| button | action | notes |
|---|---|---|
| D-pad | move (8-way) | facing = last nonzero direction |
| B | melee | hold = repeat at weapon rate |
| Y | ranged | consumes shared ammo; EMBER ROD needs no ammo |
| A | dodge roll | 12 frames of invulnerability, then a cooldown (05 §2.4) |
| X | potion | heals 60% of max HP, 45 s cooldown, per player |
| L / R | artifact 1 / 2 | each has its own cooldown |
| Start | pause and inventory | pauses both players |
| Select | ping | puts a marker above your hero (a 2-frame cue); costs nothing |

All eight buttons are spoken for. That is deliberate: it caps the equipped kit
at two artifacts rather than three. The researched design implications agree
(research §Implications 1).

## 5. Scope ladder (cut from the bottom)

| tier | contents | must ship? |
|---|---|---|
| **M (minimum)** | 1 biome (the Hollow Wood, 10 §3) tileset, 13 room templates (already authored), 4 enemy types, 1 boss, 22 item bases, 21 enchants, camp, save | yes |
| **S (should)** | 2nd biome (palette swap plus 8 templates), elites, enchant upgrades at camp, ping, music per biome | next |
| **C (could)** | 3rd biome, a 2nd boss, darkness floors lit by SUN LANTERN (the `window_iris` lantern), daily seed | later |
| **W (won't)** | online, more than 2 players, a 3rd artifact slot, procedural music | — |
