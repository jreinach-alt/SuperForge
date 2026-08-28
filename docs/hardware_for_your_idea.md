# Hardware for your idea

> Status: LIVE — what the SNES means for a game idea: design consequences,
> not registers. Budget numbers are the measured pins in
> `docs/01_substrate_reference.md` and `allocator/substrate.toml`; the proven
> forms are finished games in `game/`.

You have an idea. This machine will carry it, carry a version of it, or
refuse it — and which one is knowable up front, because the limits are
numbers, and the numbers in this tree are measured rather than estimated.

The machine in one paragraph: a slow CPU beside strong picture hardware. The
CPU gets roughly 28–37 thousand cycles per 60 fps frame — enough for game
logic, nowhere near enough to draw a picture, and it never draws one. The PPU
composes every frame from parts you have arranged in its memory: background
layers built from 8×8 tiles, up to 128 sprites, a 256-entry palette. Your
program's job is to arrange those parts, then change the arrangement a little
each frame, during the short blanking window when picture memory is writable.
Every consequence below falls out of that sentence.

## You want depth — a 3D world

The machine's one perspective device is **Mode 7**: a single 1024×1024-pixel
textured plane that the PPU can rotate, scale, and — with a per-scanline
register feed — tip over into perspective. One plane. Not two, not walls, not
geometry: hills on it are paint, not height, and the camera it implies has a
heading, a position, and altitude expressed as scale. That turns out to be a
lot.

- `game/mode7_flight` is free flight over that plane, with player-driven
  altitude working the perspective. Its cost story is the design lesson: the
  faithful pose table for 256 headings × 81 altitudes would be 12.7 MB
  against a 524,288-byte cart, so it ships as the two factors the pose
  decomposes into — ~28 KB, exact on both axes — joined per frame by
  hardware multiplies. And it holds 60 fps with zero dropped ticks
  over 240 frames of worst-case input (`tests/test_mode7_flight.py`).
- `game/m7_oshoot` runs the plane as a spinning arena: the floor turns, the
  gameplay stays in world space, and actors are projected onto the rotation.
- `game/railshooter` gets depth **without** the plane doing the work: a 1/z
  projection drawn with sprites through four pre-drawn size tiers. Distance
  can be acted rather than computed.

The perspective itself is PPU-offloaded here: HDMA streams a precomputed
per-scanline table, so the steady-state CPU cost is ~0–1% of the frame. The
naive alternative — recomputing the table in software every frame — measured
at 69–138% of the frame (`docs/01_substrate_reference.md`). On this machine
the difference between those two numbers is the difference between a game and
a slideshow, and the cure is always the same: bake, then stream.

## You want a crowd on screen

The sprite table holds 128 entries. The limit that actually bites is
**per scanline**: at most 32 sprites, and at most 34 eight-pixel slivers, on any
one line — a 32×32 sprite spends 4 slivers on every line it crosses, a 16×16
spends 2. Past the limit the PPU silently drops sprites, on that line, at
that camera pose, and nowhere else (`docs/01_substrate_reference.md`).

The design consequence: crowds want to be spread vertically. A horizontal
row of large things is the failure mode — and it is invisible until one
frame lines them up. This is the one budget the build cannot prove for you,
so where it binds, the arithmetic is done by hand and written down:
`game/railshooter` runs a measured worst case of 22 slivers of the 34.

And a really big thing should not be sprites at all — make it the
background. `game/boss` and `game/boss_saucer` make the boss *be* the Mode 7
plane: it grows from a far speck to the whole screen because it is the
floor, not an object. `game/meteor_event` runs the same trade the other way,
capturing BG platforms into a declared 40-sprite block so they survive a
mid-level video-mode swap. Layers and sprites are interchangeable material;
the hardware only cares which budget each piece is drawn from.

## You want the whole screen to change at once

Picture memory accepts writes only while the screen is blank: about 38
scanlines of VBlank per frame, into which the measured pin says
**5,952 bytes** of DMA actually land (`allocator/substrate.toml`). The full sprite
table costs 544 of those; a 32×32-tile background map is 2 KB of them. VRAM
is 64 KB, so repainting all of it is an eleven-frame project, not a per-frame
one. "Redraw everything every frame" is an idea this machine flatly
declines.

The proven shapes instead:

- **Rebuild in the dark.** At a scene change the screen is blanked and
  writes are free — every game's scene-enter does its heavy lifting there.
  `game/platformer/game.toml` states the rule plainly: the level is built
  under enter-time forced blank, and a running scene cannot rewrite its
  2,048 cells.
- **Change a ribbon per frame.** Streaming (next section).
- **Page the text.** Full-screen dumps don't fit a frame; `game/rpg`'s
  dialog is paged for exactly that reason.
- **Spend one whole VBlank on one cut.** A level that turns upside down can
  bake both orientations into ROM and swap tilemaps in a single 4,096-byte
  DMA — inside the 5,952 pin with ~1.8 KB to spare for the sprite table.
  This is not the rebuild the first bullet refuses: what a running scene
  cannot do is rework its map *by CPU* through the one-cell queue — one
  declared whole-map DMA in one VBlank is a different instrument, and
  declaring its `dma` budget is what makes it legal. Worth knowing before
  that: the hardware has no whole-layer mirror (flips are per-tile attribute
  bits), so the cheapest honest flip inverts the *physics* and leaves the
  picture alone.

## You want a world bigger than the screen

What the player sees at one instant is small — the Mode 7 plane is a fixed
128×128 tiles (32 KB: half of VRAM, whenever the plane is on). But the plane
is a torus: it
wraps, so an endless ground costs nothing (`game/railshooter`'s grid never
runs out). A *distinct* world bigger than the window means streaming: keep
the map in ROM and feed the wrap as the camera moves.

- `game/mode7_explore` walks a 512×512-tile world — 256 KB of map — through
  the 128×128 window, with a town interior and a mosaic transition beside it.
- `game/racer` streams the same way under a fast, steerable camera.
- `game/platformer_stream` is the identical idea side-on, in an ordinary
  tiled mode.

The per-frame feed is a few rows and columns — two rows plus two columns is
about 512 bytes of the VBlank budget (`docs/01_substrate_reference.md`),
under a tenth of the pin. Worlds are cheap in ROM (the cart here is 524,288 bytes)
and impossible to hold in VRAM, so the native shape is bake-and-stream, never
load-and-hold. Collision doesn't need a copy either: `engine/features/col_map`
reads the same ROM world the picture streams from, measured at 951.9 master
clocks per query — 0.27% of a frame (`docs/09_feature_register.md`).

## You want a look — colour as material

256 palette entries on screen, five bits per channel. Background figures
draw against 4- or 16-colour sub-palettes of those 256; sprites are always
16-colour; Mode 7 tiles index the full 256 flat — over there, a pixel value
*is* a palette index, which is why one palette word can double as the sky.

The machine's signature texture is **palette animation**: rewrite a handful
of palette words and everything painted with them changes at once.
`game/mode7_flight`'s free-running day/night clock re-lights the whole world
that way — terrain, fog and sky together. The other instrument is
**per-scanline colour** by HDMA: `engine/features/rgb_gradient` streams three
colour-math channels for sky ramps and vignettes, composed by six games, and
`game/racer` runs its day-night cycle through the same registers with tables
that change. The proven idiom of all of it is light *added* over dark —
dusks, fog, dawn — and it is close to free at runtime, because the PPU does
the per-line work.

The third instrument is the **colour-math unit**, which is really a second,
private screen. Designate a layer to the SUB screen and the PPU adds it into
the MAIN one per pixel, optionally halved. `game/lakeside` puts a drifting
water surface there and the lake bed reads *through* it —
`min((main + sub) >> 1, 31)` per five-bit channel — with the hardware's own
edge case doing the work at the shoreline: where the sub screen has no pixel
the fixed colour substitutes and the halving is disabled, so dry land arrives
at full intensity. There is exactly one blender for the whole screen, which is
why designation and blend are **declared** (`[[claims.screen]]` /
`[[claims.blend]]`) and two features that both want it are refused by name at
build time rather than found by debugging
(`docs/99_color_math_composition.md`).

And the picture can be **bent** rather than repainted. A scroll register
rewritten per scanline by HDMA displaces a layer line by line for no CPU
during display: `game/heathaze` runs a mirage that way. The axis is the whole
character of it — a per-scanline `BGnHOFS` only shears each row sideways and
every source row still appears exactly once, while a per-scanline `BGnVOFS`
makes scanline N draw source row N+d(N), so rows are duplicated and skipped
and the ground boils. The warp is a table, not artwork: 65 baked phases at a
256-byte stride put an animation frame one 8-bit store away.

## You want music

The audio system is its own computer: a separate sound CPU with 64 KiB of
private RAM. The vendored TAD driver owns that space outright, and its
compiler refuses an over-budget composition at build time — audio that does
not fit fails the *build*, not the performance
(`allocator/substrate.toml`, `[spc]`). On the main CPU, music is nearly
free: the per-frame driver call measures 438 master clocks — 0.123% of the
frame (`engine/features/audio/feature.toml`).

Eight games compose audio. `game/room` is the reference: one song persisting
across scene changes, per-room echo, sound effects under the music. Silence
is a design position too — several games' `game.toml` headers rule "this
rail composes no audio", each with its reason.

## You want what is not there

The honest list. Each entry is a flat no, with the nearest thing that works.

- **Polygonal 3D.** No polygon hardware exists, and 28–37k CPU cycles per
  frame is orders of magnitude short of rasterizing in software; this tree
  models a plain cart, no coprocessors. Nearest proven: the Mode 7 plane for
  the ground (`game/mode7_flight`) and sprite size tiers for objects in
  depth (`game/railshooter`). It reads as a 3D flyover; it is a textured
  plane and a cast of sprites, and that is the whole trick.
- **Online play.** No network hardware, nothing to model. Nearest proven:
  two pads on a split screen — `game/split_h_2p_demo` runs two independent
  Mode 7 cameras, one world, 60 fps, for ~40 register stores a frame
  (`tests/test_split_h_2p_demo.py`) — or asynchronous rivalry through the
  battery save (`engine/features/save`; `game/microzero`'s time-trial shape
  is the natural host for a ghost).
- **Camera roll and free pitch.** The Mode 7 camera is heading, position and
  altitude-as-scale; the horizon is data, not an axis. Nearest proven:
  `game/mode7_chamber` — the floor bows into a barrel and the texture rolls
  *through* the static bow, so all the apparent rotation is scroll
  (`engine/features/m7_barrel`). Camera moves the hardware refuses can often
  be acted with texture motion and palette instead.
- **Text over Mode 7.** The text layer, BG3, does not exist in Mode 7 — the
  game headers repeat it like case law. Nearest proven: a sprite HUD
  (`game/railshooter`: the picture is the HUD), or a split — a Mode 1 HUD
  band sharing the frame with the Mode 7 world below it (`game/microzero`,
  via `engine/features/split_band`).
- **Two perspective planes.** There is one Mode 7 layer. Nearest proven:
  split the *screen* — two cameras onto one world (`game/split_v_fight`,
  `game/split_h_2p_demo`).
- **A random-number generator.** No RNG hardware exists, and — stated so you
  do not go looking — nothing in this tree ships a software one yet either:
  the library's games are deterministic by design, because every test replays
  exactly. A game wanting chance writes a few lines of seeded arithmetic in
  its own logic and feeds it real entropy (frame counters at the moment of a
  button press are the classic source); determinism under test then comes
  from seeding it, which the replay harness already knows how to hold.

## You want it to never stutter

60 fps is not a target here; it is the resolution the machine thinks at. The
frame is 357,368 master clocks, and the reference workload's measured worst
frame spends 305,348 of them (`allocator/substrate.toml`). A frame's work
either fits or the loop parks and the picture repeats a frame — and the
shipped tests treat one repeated tick in 240 worst-case frames as a failure
(`tests/test_mode7_flight.py`).

What makes fitting *normal* rather than heroic is one idiom, applied
everywhere: precompute into ROM, hand the per-line work to HDMA, and measure
what remains. Perspective at ~0–1% instead of a software rebuild's measured
69–138%. Two-band parallax at 532 master clocks a frame — 0.149%
(`engine/features/platformer_bg/feature.toml`). Collision at 951.9 per
query. Music at 438. These are line items, not boasts, and `make measure`
fails the build if one drifts.

**One number up there is regional.** 357,368 master clocks is the *NTSC*
frame. A PAL console's is 425,568 — 19.1% longer — and it arrives 50.007 times
a second against NTSC's 60.099 (`docs/93_pal_region_investigation.md` §3.1).
The 16-bit era's usual answer was to ship the NTSC game unchanged and let PAL
play it at 83.2% speed. This kit's answer is that a game declares its
per-frame rates against a **tick**, and the tick is scaled to whichever
console the cart wakes up on: `engine/features/region` +
`engine/features/tick_scale`, opt-in, composed by 32 of the 39 games — the 30
measured so far hold a real-time band of 0.994–1.027 against that 0.832
(`docs/98_region_fleet_landing.md`). The compensation costs 0.15% of a PAL
frame (`docs/96_region_timebase_tooling.md` §0). What it does **not** buy is
the taller PAL picture: the active area is 224 lines in both regions here, so
a PAL television shows those lines with borders top and bottom — designed and
unbuilt (`docs/95_region_support_design.md`).

Also worth saying: most ideas are not frame-pressured at all. Turn-based
play, walkers, menus and dialog barely tax this machine. The real risk in an
ambitious idea is **composition** — two features that each work alone and
collide over a DMA channel, a palette row, a VRAM page. That is the part
this engine moves to build time: every feature declares what it claims, and
the build proves the combination collision-free or refuses it, by name. A
refusal is a design answer that arrives while your idea is still cheap to
change.

## The napkin numbers

| number | what it means for your idea | pinned in |
|---|---|---|
| 28–37k CPU cycles/frame | logic budget; no pixels are drawn with it | `docs/01_substrate_reference.md` |
| 5,952 B/frame VBlank DMA | how much of the picture can change per frame | `allocator/substrate.toml` (measured) |
| 305,348 of 357,368 mc | the reference worst frame vs the frame | `allocator/substrate.toml` (measured) |
| 128 sprites; 32/line, 34 slivers/line | crowd ceiling; the per-line one is the real one | `docs/01_substrate_reference.md` |
| 64 KB VRAM; Mode 7 plane = 32 KB | the visible world is small — stream it | `docs/01_substrate_reference.md` |
| 256 colours, 5 bits/channel | palette animation is the mood instrument | `docs/01_substrate_reference.md` |
| 64 KiB sound RAM, own CPU | audio fits at build time or fails the build | `allocator/substrate.toml` |
| 524,288 B cart | worlds are cheap in ROM; bake, then stream | `README.md` |

Where to go next: `README.md` tours the showcase games;
`docs/09_feature_register.md` is the inventory of what exists and what each
piece claims; `docs/01_substrate_reference.md` is the raw budget behind every
number above.
