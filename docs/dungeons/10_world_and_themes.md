# 10 — World and visual themes

> DRAFT SPEC, owner direction of 2026-11-16: **borrow liberally from a
> 1984 fantasy film about a storybook world being erased by an advancing
> void.** It is referred to here as "the film". Its title, characters, places
> and creatures are not named in the tree, and `make cleanroom` denylists them.
>
> **What "borrow liberally" means here: evocation, not reproduction.** We take
> the film's *mood, palette, scale, motifs and genre ideas*. None of these
> belong to anyone: a world unmade by forgetting, a melancholy swamp, a desert
> of colossi, a tower at the centre of everything. We do **not** take its
> *specific expression*: no character, creature design, named place, prop,
> line or shot reproduced or lightly disguised. Every design in this file is
> drawn fresh.

## 1. Premise (original)

The realm of **Lumenvale** exists only while it is remembered. A silence
called **the Unwriting** has begun to erase it from the edges inward:

- where it passes, places do not burn or fall
- they simply *stop*, leaving pale blank nothing behind

Beneath the realm lies **the Underleaf**, layer on layer of half-forgotten
places, and each one the Unwriting takes is gone for good. Two wanderers, the
players, descend from **the Last Lantern**, a camp kept by an old
lamplighter. Each floor they clear is a memory carried back up, and the
lantern burns a little brighter.

Why this premise fits the game:

| premise element | mechanic it explains |
|---|---|
| floors are "remembered" anew every time | procedural generation is in-fiction: no two floors are the same |
| gear is "what you carried back out of a memory" | loot defines the hero, and there is no class |
| the Unwriting at the edges | the generator's `void` cells already *are* the unwritten: black outside the rooms. Tier S makes it advance (§4) |
| two wanderers, one lantern | couch co-op, the revive loop, and the SUN LANTERN artifact |

## 2. The look: "80s matte painting on a 16-bit screen"

The film's look is painted backdrops, practical creatures, and colour that is
dusty and luminous at once. Translated to the SNES:

- **Palette philosophy.** Desaturated mid-tones (dusty violet, sage, ivory,
  stone) carry 80% of the screen. Saturated colour is spent only on what
  matters: loot, braziers, the heroes, magic.
  - Each biome has one "glow" hue, used on lit tile edges and on its BG
    palette's top two entries.
  - The Unwriting is the only pure-white-to-nothing gradient in the game.
- **Light.** Warm light sits on cold stone everywhere. Braziers cycle a
  3-entry palette ramp (tier S, `palette cycle`: no new claim class).
- **Scale.** The film dwarfs its hero against vast things. A top-down screen
  shows scale through **set-piece rooms**:
  - a boss arena floor with a colossal carved face,
  - a cell whose floor is a giant's hand.
  - Each is a hand-authored 16×16-metatile template drawn as one large
    prerendered image (11 §3).
- **The book frame.** Menus, the descend card and the results screen are
  pages of an old illuminated book: parchment BG, a drop-cap glyph and an
  ink-line border. (Illuminated manuscripts are a public tradition, not the
  film's.) The descend card's page turns via the `mosaic` edge.

## 3. Biomes (tier M ships 1, tier S 2, tier C 3)

| biome | the feeling | palette anchors | signature tiles | its own hazard |
|---|---|---|---|---|
| **The Hollow Wood** (M) | ancient, enormous, whispering | moss green, bark umber, amber glow | colossal roots as walls, fungus braziers, hollow-log doorways | none: the teaching biome |
| **The Grieving Fen** (S) | melancholy so heavy it slows you | grey-teal, bruise violet, pale reed gold | still black water (chasm), dead reeds, drowned stones | **sorrow mire**: standing still for 2 s applies FROST-style slow; keep moving |
| **The Shifting Waste** (S) | heat, emptiness, colossi half-buried | ochre, rose sand, sun white | dunes (rubble), half-buried statue walls, glyph stones | **dune drift**: sand metatiles slowly convert to walkable from the edges (4-cell queue), opening shortcuts |
| **The Pale Spire** (C) | the centre of everything, ivory and silent | ivory, pearl, gold leaf, sky blue | white stone, gilded trim, open galleries | the Unwriting is visible *inside* |

**How a biome is applied:** the same templates, a different CHR and palette
set, and per-biome template weights. One biome costs **1 CHR blob (≤16 KB) +
1 enemy CHR set + 1 song**, not new templates. Biomes can add their own
templates later, through the existing `type` header plus a planned `biome=`
key.

## 4. The Unwriting as a mechanic (tier S)

- A floor's **void** cells are the Unwriting. After 3 minutes on a floor,
  unvisited dead-end cells begin to **unwrite**:
  - Their metatiles turn to a white "blank" tile and then to void, 4 cells per
    frame through the cell queue.
  - Whatever is inside is lost, chests included.
- This is pressure without a timer UI. It rewards the co-op pair splitting up
  across a branch (06 §2 lets them, within the leash).
- Visual: one metatile kind with a 4-frame white → black palette ramp, plus
  the colour-math fixed colour pulsing toward white on the frame a cell goes.
- **Determinism:** which cells go and in what order is drawn from GEN at
  generation time, so it is part of the seed and testable.

## 5. Bestiary (themes over the 05 archetypes)

| archetype (05) | themed name | design note (original) |
|---|---|---|
| grunt | **Rootling** | a knot of animated root with one ember eye, which swings a branch-arm |
| archer | **Thornspitter** | a bulb plant that spits seeds. It keeps its distance and roots in place to fire |
| brute | **Cairnback** | a slow mound of mossy stones with a beast's gait. It slams |
| skitter | **Mothwick** | dusty moths with candle-flame wings. They burst into sparks on contact |
| boss | **The Hollow Crown** | a great antlered *absence*: a crown and antlers framing nothing, with pieces of forest orbiting it. Drawn on BG2 (05 §2.2) |
| tier S, Fen | **Mournwader** | a long-legged heron-thing that never stops weeping, and slows what it touches |
| tier S, Waste | **Glasswyrm** | burrows; shows only as a ripple until it strikes |

**Explicitly not used** (the film's specific expressions):

- a furry flying dragon companion
- a horse lost in a swamp
- a giant wise turtle
- a stone-eating giant
- a wolf hunting on the void's behalf
- twin sphinxes that judge travellers
- a twin-serpent amulet
- an ivory tower ruled by a child sovereign

If an idea is recognisable as one of those, redraw it.

## 6. Heroes

Two wanderers of no fixed type. Both use one shared design, a cloaked
traveller with a satchel and a lantern hook, and only the palette differs:

- **P1:** dusk blue with a silver trim
- **P2:** amber with a copper trim

The cloak silhouette is the read at 16×16. The weapon is the second read, on
its own swing sprite.

## 7. The camp: the Last Lantern

A small top-down clearing at the realm's last bright point. It holds:

- **the lamplighter** (dialog: run summary, hints, spark upgrades)
- **the salvage anvil**
- **the stash chest**
- **the stair-well**: pick a depth here

The lantern's light radius grows with the deepest floor cleared. That is the
`window_iris` lantern, which already exists in the kit and is affordable here,
because camp has no combat load (02 §4).
