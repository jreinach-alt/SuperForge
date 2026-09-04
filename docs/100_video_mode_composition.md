# 100 — The video/offset vocabulary: a scene's mode, and BG3 as data

> Status: LIVE — `claims.video` + `claims.offset` (C6), landed 2026-08-28.
> The fifteenth and sixteenth claim classes (`allocator/schemas.py`), the
> per-scene composition and refusal set (`allocator/allocate.py`,
> `compose_video_offset`), and the writer-side consent that lets scene code
> write the composed state (the synthesized ownership claim in each scene's
> `symbol_map.json` reg union). Exercised by one rail, `smelter` — which
> since 2026-08-28 also carries a PLAYER standing on the table's own
> numbers (§10).

## 1. The problem: the mode was a value nobody declared

BGMODE `$2105` decides more about a scene than any other byte on the machine.
Bits 0-2 pick one of eight video modes, and the mode decides **which BG layers
exist at all**, **at what colour depth**, and **whether the offset-per-tile
path runs**. Bit 3 is mode 1's BG3-priority select; bits 4-7 are a 16x16-tile
select per layer.

Before this vocabulary, BGMODE was a `(port, WHOLE)` row in
`REGISTER_FOOTPRINT` and nothing else. That is correct as far as it goes —
the port is write-only, one owner per scene — and it says nothing about the
mode. Measured on the tree that adopted the vocabulary: BGMODE appeared in
raw `[[claims.reg]]` footprints across the feature layer and its VALUE lived
only in ASM immediates and in feature.toml comments (`lake_bg`'s
"BGMODE is $09: mode 1, plus the BG3-priority bit", `hz_bg`'s the same).

`docs/capability_map/ppu_core.md` §9 (Forge2) rated offset-per-tile
**`partial`** and named exactly two consequences:

> nothing declares "BG3 is not a drawable layer in this scene" (a text feature
> and an offset-per-tile feature would both believe they own BG3 with no
> collision visible) … the mode restriction — offset-per-tile exists only in
> modes 2/4/6 — is not expressible as a constraint at all.

Both are properties **of the mode**. The fix is the same one docs/99 made on
the blender: not a finer mask but a finer **declaration**. A scene declares
its video mode, the allocator composes the byte, and every claim whose
legality depends on the mode can finally be checked against it.

## 2. The hardware model

Re-derived from the Mesen2 source on disk (`/tmp/Mesen2/Core/SNES/`), per the
house rule that register encodings and hardware behaviour come from the
emulator source, not from a summary. All references are to `SnesPpu.cpp` in
this checkout unless named otherwise. `fullsnes`'s own §Offset-Per-Tile is a
stub ("XXX - Under construction, see Anomie's docs"), which is why every row
below is a source citation rather than a quotation.

| fact | where |
|---|---|
| `BGMODE`: b2-0 mode, b3 mode-1 BG3 priority, b4-7 16x16 tiles for BG1..BG4 | :1951-1959 |
| which BG layers a mode RENDERS — a mode calls `RenderTilemap` once per layer it draws, and a layer it never calls is not on screen in that mode at all | `RenderMode0`..`RenderMode7`, :781-859 |
| mode 7 draws BG2 **only** with EXTBG (`$2133` bit 6) | :856-858 |
| which modes FETCH offset words: 2 and 6 fetch an H word AND a V word per column (cases 2 and 3); 4 fetches ONE word (case 2); every other mode fetches neither | `FetchTileData`, :277-390 |
| the words come from **BG3's own tilemap**, indexed by BG3HOFS (the column, 8 px granular) and BG3VOFS (which ROW is the H row); the V row is that row + `0x20` words, wrapping inside the map | `GetHorizontalOffsetByte` / `GetVerticalOffsetByte`, :257-276 |
| bit 13 applies a column's offset to BG1, bit 14 to BG2 | :154-155 |
| H: `hScroll = (hScroll & 7) \| (word & $3F8)` — the LAYER keeps its own fine three bits, so a horizontal offset is 8-PIXEL granular | :157, :164 |
| V: `vScroll = word & $3FF` — the offset REPLACES the layer's scroll rather than adding to it | :160, :167 |
| in mode 4 bit 15 of the single word selects V over H | :156-161 |
| the offset latches are cleared at the start of each scanline's fetch | :284-287 |
| `BGnSC`: b7-2 the tilemap base, b0 DoubleWidth, b1 DoubleHeight | :1978-1980 |

**The colour depths, from the same `RenderMode` bodies** (the second template
argument, cross-checked against `FetchTileData`'s `GetChrData` bpp arguments):

| mode | BG1 | BG2 | BG3 | BG4 | offset-per-tile |
|---|---|---|---|---|---|
| 0 | 2bpp | 2bpp | 2bpp | 2bpp | — |
| 1 | 4bpp | 4bpp | 2bpp | — | — |
| **2** | **4bpp** | **4bpp** | *the table* | — | **H and V, per column** |
| 3 | 8bpp | 4bpp | — | — | — |
| **4** | **8bpp** | **2bpp** | *the table* | — | **one word, bit 15 picks the axis** |
| 5 | 4bpp | 2bpp | — | — | — (hi-res) |
| **6** | **4bpp** | — | *the table* | — | **H and V, per column** (hi-res) |
| 7 | (M7) | EXTBG | — | — | — |

Three rows are load-bearing for the refusal set. The render table is why a
screen designation of a layer the mode does not draw is a declaration that
lies rather than a spare bit. The fetch schedule is why offset-per-tile outside
modes 2/4/6 is not "an effect that does not show" but a claim on a mechanism
the PPU never runs. And the **bpp columns** are what a CHR claim's depth is
checked against (§5, O9): a 4bpp tile is 32 bytes and an 8bpp tile is 64, the
PPU fetches at the MODE's depth whatever the claim reserved, and until mode 4
every composed mode rendered its layers at the depth the art happened to be.

**`axis = "both"` under mode 4 was refused, and that was wrong.** The refusal
reasoned about a COLUMN — a mode-4 column carries one axis, which is true —
and then rejected a claim about the TABLE. Bit 15 is per WORD, so a mode-4
table can drive one column vertically and its neighbour horizontally, and that
mixing is the only thing mode 4 does which mode 2 cannot. It also made the
truth undeclarable rather than merely unusual: `axis` selects which value mask
is published and the two mask differently (`$3FF` against `$3F8`), so a mixed
table declaring `"v"` got `MASK` and no `HMASK` and had no symbol to build half
its words from. `both` is legal in all three offset modes now and means "this
table uses both axes"; what differs by mode is where the choice lives, and the
composition warns at that boundary because the same declaration means "both
axes per column" one mode over.

**Two things about offset-per-tile were measured on a shipped binary rather
than read**, because reading a fetch order is not the same as watching it:

- **The offset words for a column are fetched AFTER that column's tilemap
  data**, so the word written at table column *k* displaces **screen column
  k+1**. Before `tools/gen_smelter_assets.py` shifted its table to match, the
  first plate rendered three columns wide with an invisible ghost beside it.
- **Screen column 0 cannot be displaced at all** — the latches are cleared at
  the start of each scanline's fetch, so the leftmost column always shows its
  layer's own `BGnVOFS`.

`tests/test_smelter.py::test_the_world_column_under_a_screen_column_is_the_one_that_moves_it`
asserts the first as a measurement rather than as an assumption: a shift of 0 explains the
picture and ±1 does not, so the maximum is sharp.
`test_screen_column_zero_lands_when_the_port_it_falls_back_on_is_free`
asserts the second — and asserts it as a limit PAID rather than merely
suffered, which is what §12.1 changed.

## 3. The vocabulary

Two claim classes, declared in `feature.toml` like every other claim, composed
per scene like every other claim.

```toml
[[claims.video]]           # the scene's VIDEO MODE — one per scene, one owner
mode = 2                   # 0..7                      (BGMODE b2-0)
bg3_priority = false       # optional, default false    (b3, mode 1 only)
tiles16 = []               # optional: bg1|bg2|bg3|bg4  (b4-7)
direct_color = false       # optional: 8bpp pixels ARE the colour (CGWSEL b0)

[[claims.offset]]          # OFFSET-PER-TILE: BG3's tilemap IS the table
axis   = "v"               # h | v | both
layers = ["bg1", "bg2"]    # the enable bits it may set: 13 -> BG1, 14 -> BG2

[[claims.offset_bands]]    # BANDS: this SCENE reads the table in `rows` bands
rows   = 3                 # 2..32 table rows, selected per scanline
```

A video claim declares the scene's display shape; it has one owner per scene,
and a mid-frame mode change is a per-scanline HDMA rewrite that keeps the raw
`[[claims.reg]]` shape (`split_band` is that feature, and it is deliberately
mode-agnostic).

An offset claim declares that **in this scene BG3 is not a layer**. The table
it points at is an ordinary `[[claims.vram]] kind = "tilemap"` region and
always was; what the claim classes could not say is the consequence, which is
that every other feature's belief that it can draw on BG3 is now false.

`direct_color` declares that this scene's **8bpp layer indexes no palette**:
its pixel byte is the colour, 3-3-2, with the tilemap entry's 3-bit palette
field supplying the low bit of each channel. It is on the **video** claim and
not on a colour-math one because that is what it is a property of —
`GetRgbColor` acts on the flag under
`if constexpr(bpp == 8 && directColorMode)` and nothing else
(`SnesPpu.cpp:1071`) — but it *composes* into `CGWSEL` bit 0, which the
screen/blend vocabulary owns, so **the declaration is here and the emission
is in docs/99 §4**. One register, one composition writing it. Which modes it
means anything in is `MODE_BPP`'s answer and not a second list: 3, 4 and 7
(O11 below).

## 4. Composition

Per scene, over the union of the scene's features and the globals (the same
union every ownership check runs over):

```
BGMODE = mode | (bg3_priority << 3) | OR of (1 << (4 + layer index)) for tiles16
```

The offset claim composes no byte — the words are VRAM, not a register — and
what it composes is **ownership**: the synthesized per-scene claim holds
`BG3SC`, `BG3HOFS` and `BG3VOFS`, the three ports the offset path reads.

**`BG34NBA` is deliberately not among them.** No CHR is fetched for BG3 in an
offset mode, so the offset path never reads a BG3 chr base and claiming that
port would be a declaration that lies. The collision the vocabulary exists to
catch fires on `BG3SC` regardless — `bg_text` claims all four.

A bands claim declares that **this scene reads the table in more than one
row**. The PPU fetches the row `BG3VOFS` names — `rowOffset = VScroll >> 3`
(`SnesPpu.cpp:257-276`) — so a per-scanline rewrite of that one port hands
each band of the picture its own 32 words, and the composition synthesizes
the transfer that does it: an active-phase HDMA claim on `BG3VOFS`, one
channel, DMAP mode 2 (the port is write-twice), the whole frame, named
`<claim>_rowsel` and assigned and emitted like any channel. It is a claim of
the SCENE's use of the table and not of the table, and it lives on a
scene-scoped feature beside the table claim: `mill`'s table is one global
feature's claim in every room of the rail and only the melt reads it in
bands (§13.7).

A scene that declares neither claim has **no composition at all**, not an
empty one, which is what keeps every rail predating the vocabulary
byte-identical.

`direct_color` composes no bit of `BGMODE`. It composes `CGWSEL` bit 0 in the
screen/blend half (docs/99 §4), and declaring it makes that composition own
`CGWSEL` — with a blend claim as before, and without one, `CGWSEL` alone.

Worked example — the `smelter` rail's two scenes, one set of art:

```
title:  BGMODE = $09    ; mode 1 + BG3 priority; BG3 is a 2bpp text layer
works:  BGMODE = $02    ; mode 2, 4bpp on BG1 and BG2; BG3 is the table
        ES_OPT_WORKS_BG1  = $2000
        ES_OPT_WORKS_BG2  = $4000
        ES_OPT_WORKS_MASK = $03FF
```

## 5. The refusal set

An infeasible composition stops the build — that is the feature. Each refusal
names the claiming features and the hardware mechanism it protects.

- **O1 — one video mode, one owner.** Two `[[claims.video]]` claims in one
  scene refuse, **even when they agree on `mode`**. BGMODE holds one mode for
  the whole frame and the ownership of that byte — not its value — is the
  resource: the same rule `claims.reg` applies to whole ports, and the same
  rule R1 applies to a layer's designation.
- **O2 — one offset table, one owner.** Two offset claims in one scene refuse.
  There is one BG3 fetch path per scene reading one pair of rows, so the second
  table is one the hardware will never look at.
- **O3 — an offset claim needs a declared mode.** An offset claim in a scene
  with no video claim refuses. This is the hole the vocabulary exists to close:
  without a declared mode the restriction cannot be checked at all, and the
  claim would compose in silence in a scene whose BGMODE some raw claim writes
  to a value nobody declared.
- **O4 — offset-per-tile exists in modes 2, 4 and 6 ONLY.** `FetchTileData`
  branches on the video mode and only three of its eight arms call
  `GetHorizontalOffsetByte`, so under any other mode the PPU never reads a word
  of the table. The message names the declared mode, the three that have the
  path, and what each of the three costs in art.
- **O5 — BG3 IS the offset table, not a layer.** Two arms, because a feature
  can draw on BG3 two ways:
  - a `[[claims.screen]]` designation of `bg3` in a scene carrying an offset
    claim refuses in the composition;
  - a raw `[[claims.reg]]` on `BG3SC`/`BG3HOFS`/`BG3VOFS` refuses through the
    synthesized ownership claim, as an ordinary reg×reg intersection — but with
    the offset message, because the fix is not to pick a winner. **It is not a
    tie to break**: one or the other holds the scene.
- **O6 — a driven layer the mode does not render.** `layers` naming a layer the
  declared mode never draws refuses (bg2 under mode 6). R5's shape on the mode
  axis: the enable bit is set and the offset displaces a layer no pass
  produces.
- **O7 — mode 4 carries one axis per column.** `axis = "both"` under mode 4
  refuses. One word is fetched and bit 15 selects the axis, so a column carries
  one or the other and never both. Modes 2 and 6 fetch a word for each and are
  where `"both"` is expressible.
- **O8 — a designation the mode does not render.** A `[[claims.screen]]` claim
  for a BG layer the declared mode never draws refuses, **with or without an
  offset claim**. R5's rule on the mode axis, and the same sentence: the TM/TS
  enable bit is set and no pass ever produces a pixel through it. OBJ is exempt
  — sprites render in every mode.
- **O9 — a CHR claim's DEPTH against the depth its mode renders that layer
  at.** A `kind = "chr"` claim may name the BG `layers` its tiles are fetched
  for; when it does, `tile_bytes` must equal `MODE_BPP[mode][layer] * 8`. A
  4bpp tile is 32 bytes and an 8bpp tile is 64, and **the PPU fetches at the
  MODE's depth whatever the claim reserved** — so mode 4 (bg1 8bpp) beside a
  32-byte BG1 claim is not a tight fit, it is every tile made of half of one
  tile and half of the next, with the back half of the set never reached.
  Naming a layer the mode does not render refuses too, on O6's grounds one
  claim class over: tiles uploaded for a layer no pass fetches.

  **The OBJ arm holds without a video claim at all.** A sprite's depth is not
  a property of the mode — `SnesPpu.cpp:770` fetches sprite pixels through
  `GetTilePixelColor<4>` with the depth written into the template argument —
  so OBJ is 4bpp in all eight modes and a 16- or 64-byte OBJ claim is wrong in
  every one of them. `layers` and `obj = true` are mutually exclusive for the
  same reason: OBJ is not a layer whose depth a mode decides.

  **Why nothing found this before.** `MODE_BPP` was imported by the allocator
  for exactly one purpose — building the "(bg1 4bpp + bg2 4bpp)" text inside
  refusal MESSAGES — and was never checked against anything; `tile_bytes` was
  validated as one of 16/32/64 and stopped there. It stayed invisible because
  until mode 4 every composed mode rendered its layers at the depth the art
  happened to be. **The same claim is wrong one mode over**, which is what
  makes this a join rather than a field validation.

  **`layers` is OPTIONAL and the check says what it did not reach.** A scene
  that declares a mode and carries a sized BG CHR claim without it gets a
  warning naming the claim — the ratchet's first rung, the shape the width
  lint's routine contracts were adopted through. A claim sized in `words`
  rather than `tiles` declares no depth at all and is invisible here: `words`
  is the escape hatch for a claim whose shape is a hardware WINDOW rather than
  a tile count (a whole OBJ name table, the Mode 7 region), and that is a
  stated limit rather than an oversight.

Beside them, a raw `[[claims.reg]]` on BGMODE in a scene that composes a video
claim refuses with the docs/99 R6 message on this port: two vocabularies, one
write-only byte, and the migration named.

One worked refusal, verbatim from the build (`bg_text` composed into the
`smelter` rail's mode-2 scene, which is why that feature is scene-scoped to the
title in `game/smelter/game.toml`):

```
ALLOCATION FAILED: REGISTER ownership contention in scene 'works': text_bg3
(engine:bg_text) claims ['BG3HOFS', 'BG3SC', 'BG3VOFS'] as a raw
[[claims.reg]], but this scene also composes the video/offset vocabulary over
the same port (video_offset, video/offset <- engine:smt_opt) — two
vocabularies, one write-only port. Every writer of a write-only register
supplies the WHOLE byte, so the raw value and the composed value cannot both
hold. And on ['BG3HOFS', 'BG3SC', 'BG3VOFS'] it is not a tie to break: BG3 IS
THIS SCENE'S OFFSET TABLE, not a drawable layer. In modes [2, 4, 6] the PPU
reads BG3's map entries as per-column scroll offsets and never renders the
layer (Mesen2 SnesPpu.cpp RenderMode2/4/6 draw BG1/BG2 and OBJ only; the words
are fetched at :257-276), so a feature that draws on BG3 and an
offset-per-tile feature cannot both hold this scene whatever they agree about
the registers. Draw 'text_bg3' on a BG the mode renders, or put the offset
table in a scene of its own (docs/100)
```

**Warnings**, in the allocation report, where the silicon CAN express the state
— the docs/99 rule verbatim: *refuse what the silicon cannot express, warn
about what it can*.

- `bg3_priority` under a mode other than 1: BGMODE bit 3 is read by
  `RenderMode1` alone (:799), so the bit holds and nothing consults it.
- `tiles16` naming a layer the mode does not draw: the same shape on the size
  bits.
- a `bg2` designation under mode 7: BG2 exists there only with EXTBG, which
  has no model in this tree (BG2's pixels ARE BG1's, split by bit 7 — docs/09's
  G5), so this composes and warns rather than refusing. Over-refusal is a
  defect class of its own.
- an offset claim whose `axis` includes `h`: horizontal offsets are 8-PIXEL
  granular, because the layer keeps its own low three bits.
- every offset claim: the word REPLACES the layer's scroll rather than adding
  to it, and a column with its enable bit clear falls back to the layer's own
  register — so the table holds absolute positions, not deltas.
- an offset claim driving a layer no `[[claims.screen]]` claim in the scene
  designates: displacing a layer that is on neither screen displaces nothing
  visible. A warning and not a refusal for the WOBJSEL reason (docs/99 §8) —
  the layer may be designated by a raw TM claim the vocabulary cannot
  attribute.
- **O11 — `direct_color` under a mode with no 8bpp layer**, and under mode 7.
  Two arms, both warnings, and the first is the decision worth stating: the
  bit HOLDS. CGWSEL b0 set under mode 1 is a legal, stable, expressible PPU
  state in which `GetRgbColor`'s `bpp == 8` guard is false for every layer the
  mode renders and no pass consults the flag — the same shape as
  `bg3_priority` outside mode 1 and a `tiles16` bit for a layer nothing draws,
  and NOT the shape of O4/O6/O8, each of which refuses a declaration whose own
  subject the mode deletes. The set of modes it is live in is derived from
  `MODE_BPP` rather than listed: 3 and 4 reach it through `RenderTilemap`
  (`:2414`), 7 through `RenderTilemapMode7`'s own arm for layer 0 (`:2466`).
  The second arm fires under **mode 7**, where the declaration is right and
  buys less: that path has no tilemap palette field, so the colour is
  `((c & 0x07) << 2) | ((c & 0x38) << 4) | ((c & 0xC0) << 7)` (`:1243`) — 3-3-2
  with every channel's low bit clear — where modes 3 and 4 take the low bit of
  each channel from the tilemap entry's 3-bit palette field
  (`(tilemapData >> 10) & 0x07`, `:1023`, folded in at `:1071-1076`).

Each warning is counted in the allocator's summary line beside the refusal
checks, so a run that examined nothing reads as having examined nothing.

- **O10 — bands are rows OF A TABLE, and the row-selecting channel is the
  composition's.** Two arms. A `[[claims.offset_bands]]` in a scene with no
  offset claim refuses: with no table BG3 is a drawable layer here (or absent
  from the mode) and the channel this would synthesize on `BG3VOFS` would
  scroll a picture, not select a row. Two bands claims refuse: one port, one
  row per scanline, two channels driving it. And a feature's own active
  HDMA claim on `BG3VOFS` beside a bands claim meets the synthesized
  `_rowsel` claim in `assign_channels` as an ordinary HDMA register
  contention — which is the refusal the raw shape could not reach. The
  composition's `BG3VOFS` ownership is marked `seed` when bands are declared
  (the scene's enter write is the base value the channel overrides from line
  0), and a `seed` beside a raw hdma claim is exactly what check 2 of the
  register gate CONSENTS to; without the synthesized claim a foreign channel
  would have slipped through as the seed's own overrider. Without bands there
  is no seed and the raw channel still refuses in check 2, as before. The
  parser holds the hardware ceiling — a BG3 tilemap has 32 rows, the 1K-word
  page `BG3SC` addresses — and whether the rows a band names EXIST in the
  table's VRAM claim is not reachable (§14, the placement limit).

## 6. Emission

For every scene carrying at least one vocabulary claim, the scene's generated
include gains a symbol **per half the composition owns**:

```
ES_VID_<SCENEID>_BGMODE            where the scene declares a video mode
ES_OPT_<SCENEID>_BG1 / _BG2        the enable bits its offset claim declares
ES_OPT_<SCENEID>_MASK / _HMASK     the value field for the axes it declares
ES_OPT_<SCENEID>_VSEL              mode 4 only: the axis-select bit
ES_OPT_<SCENEID>_BANDS             with a bands claim: the rows selected between
ES_OPT_<SCENEID>_ROW_VOFS          ...and BG3VOFS = row * this selects a row
ES_H_<CLAIM>_ROWSEL_CH/_BBAD/_DMAP ...and the synthesized channel, as any channel
```

`direct_color` emits nothing **here**. It is a `CGWSEL` bit and it is
published as part of `ES_SCR_<SCENEID>_CGWSEL` by the screen/blend half
(docs/99 §6), so the scene's one write of that port carries it — the port's
one owner still supplies its whole byte. The scene's `symbol_map.json` entry
carries `direct_color` on **both** the `screen_blend` and the `video_offset`
object, so a reader who has the mode has the pixel rule that goes with it.

**The field set is derived from the declaration, not fixed.** `layers` decides
which enable bits exist, `axis` decides which value mask, and `VSEL` appears
only under the one mode whose word carries an axis select. A rail that builds
a word with a bit its claim did not declare has no symbol to build it from.
That is the docs/99 §6 rule — a symbol is the permission slip, issued only for
what the composition owns — applied to a set of constants rather than to a
port.

A half the scene composes nothing for emits a commented placeholder line
instead of a symbol, saying so.

The composition also lands machine-readably: the scene's entry in
`symbol_map.json` gains a `video_offset` object — the composed BGMODE, the
mode, the offset table's declared axis and layers, the emitted fields, the
registers the composition owns, and the contributing features — so a test can
assert a ROM's mode and its per-column words against the DECLARATION instead of
re-typing either.

## 7. The tilemap's shape, which this sprint completed

`BGnSC` bits 0 and 1 are DoubleWidth and DoubleHeight, and the emitted
`_SC_BASE` encoding carried **only the base**. The two size bits were left to
be narrated at the write site, which is the second uncheckable copy of a claim
that the emitted encodings exist to prevent — `platformer_bg.asm` said so out
loud: *"the emitted _SC_BASE carries only the base (bits 2-7), so the size is
OR'd in here"*.

It went unnoticed because every tilemap in the tree was 32x32, where the
narrated bits are zero. `smelter`'s two 32x64 maps are the first that are not,
and the symptom was a picture made entirely of the map's first 32 rows with no
gate red.

A tilemap claim now declares its shape:

```toml
[[claims.vram]]
name  = "smt_pmap"
kind  = "tilemap"
words = 0x800
shape = "32x64"          # 32x32 | 64x32 | 32x64 | 64x64
```

`words` alone cannot distinguish 64x32 from 32x64 — both are `0x800` — so the
shape is a **declaration**, and the parse refuses a shape that disagrees with
the size. The emitted `_SC_BASE` now carries the whole byte. Three existing
write sites dropped their hand-OR and their ROMs are byte-identical.

## 8. Coexistence and migration

Raw `BGMODE` and raw BG3 register claims remain fully legal — every existing
composition in the tree is untouched and byte-identical, and both stay in
`REGISTER_FOOTPRINT`. The vocabulary is opt-in: no feature that predates it
declares either class, so none of its checks reach a scene that does not
compose one.

The seam is refereed by the synthesized ownership claim, and it is per half:

- the claim owns **BGMODE** only where the scene declares a video mode;
- it owns **BG3SC/BG3HOFS/BG3VOFS** only where the scene declares an offset
  table;
- so a raw BGMODE claim composes beside a scene that declares only an offset
  table (which O3 refuses for a different reason), and a raw BG3 claim composes
  beside a scene that declares only a mode.

The migration rule, when a scene wants both vocabularies on one port: move the
raw claim into the new one. A feature's BGMODE intent becomes a
`[[claims.video]]` claim on the feature that defines the scene's display shape.
For BG3 there is no migration, and the refusal says so: one or the other holds
the scene.

## 9. What the rail added to the tree's transition-hygiene list

`smelter`'s two scenes draw **the same art under two declared modes** — BG1
and BG2 are 4bpp in mode 1 and mode 2 alike — so `smt_bg` is global and does
not change a byte across the edge. What changes is what BG3 MEANS.

That extends a rule the tree has now stated three times:

| feature | what persists across the edge |
|---|---|
| `blend_off` | the **composed blend state** — CGWSEL/CGADSUB (docs/99 §4) |
| `hz_flat` | a **scroll port a transfer drove** — BG1VOFS/BG1HOFS |
| the `smelter` title's enter | **a whole layer's identity** — BG3SC still points at a page of scroll words |

A scene that drew text on BG3 without re-pointing BG3SC would render 64 bytes
of vertical scroll positions **as glyphs**. The discharge is `bg_text`'s — all
four of its BG3 registers are in `scene_writes` and the title's enter writes
all four — and `tests/test_smelter.py::test_the_title_returns_with_bg3_a_layer
_again` asserts the returned title pixel-identical to the one before the works
ever ran.

Colour math was never special. Neither was a scroll port. What persists is
**everything a scene establishes and its successor does not**.

## 10. The rail's player, and what a sprite costs the proof

`smelter` ships a knight. He walks, he jumps, and he **rides** whichever plate
he is standing on — and the reason he is in a document about a claim class is
that he closes a gap a picture cannot.

Everything in §5 and §9 is about what the DISPLAY does. A per-column equality
says the crust line in column 17 is exactly where the word for column 17 puts
it, and that is a strong statement about the PPU. It is not a statement about
the world the rail is drawing. A rail could satisfy every one of those
equalities while the number meant nothing at all outside the frame buffer.

The knight is the statement that it does. `smt_kn_ride` takes his Y from
`smt_plate_top`, which reads **the same 64-byte row the VBlank transfer moves
into BG3's map** — so the collision and the picture are not kept in step, they
are the same number used twice. The assertion is his FEET, in the rendered
frame, on the plate's TOP EDGE, in the same frame, at the height the word in
`build/smelter.sfc` puts it, at every phase of the harmonic
(`tests/test_smelter.py::test_the_knight_stands_on_the_word_the_rom_holds`,
and `..._rides_the_plate_rather_than_hovering_over_it` for the six-capture
version a single frame cannot distinguish from a coincidence).

**And it costs the composition nothing, which is why this rail could have one
and `heathaze` could not.** The plates are BACKGROUND. A per-column equality
reads a BG edge; a sprite drawn over four columns of that edge is a sprite, not
a displacement, and the OBJ layer is exempt from the mode's layer-existence
rule (O8) because sprites render in every mode. `heathaze` is the contrast: its
claim is a per-ROW equality on the picture itself, and a moving object in the
band would have destroyed it. The rule generalises — **a player is free where
the subject is a layer the player is not drawn on, and expensive where the
subject is the picture.**

Two things about the art turned out to be load-bearing rather than decorative,
and both are inherited from the pack rather than re-derived:

- the `camelot` pack frames every 32x32 cell with **four transparent rows under
  the feet**, so the drawn content ends at row 28. That number (`SMT_KN_BOTTOM`,
  measured off the pixels at build time) is what puts him ON the metal instead
  of four pixels into it — and it is also why the per-column plate cases keep
  working while he stands in four of their columns, which
  `..._does_not_hide_the_edge_the_per_column_cases_read` asserts where the
  reason is written down;
- a 32x32 knight is exactly a plate's four columns wide, which is what makes
  "he is standing on THAT plate" legible and the gaps a jump rather than a step.

**One defect this bought, worth recording because the shape recurs.** His
vertical position started as 8.8, the tree's usual unit. It cannot hold both
ends of his own movement: the highest plate sits at screen row 11 and a jump's
apex is 50 px, so his Y goes genuinely NEGATIVE — while a miss carries him past
row 232 on the way out of the world. In 8.8 those two are **the same bit
pattern** (row 232 and row -24 are both `$E8..`), so the kill test read a fall
as "above the screen", skipped the respawn, and wrapped him round to the top.
The fix is one bit moved from the fraction to the row: **9.7**, spanning
-256..+255 whole rows, with both conversions written against a single
`SMT_KN_FRAC` so they cannot drift. It is planted
(`tools/plants/smelter.py::the-knights-y-is-8-8-again`) because it took a person
walking him off the edge to find it the first time, and every other case in the
module stays green under it.

## 11. What the rail animates that is NOT the table

`smelter` swaps four CHR tiles every VBlank, so the lava churns under a tilemap
that never changes. It is in this document for one reason: **it is the only
motion in the rail that the offset vocabulary has nothing to do with**, and a
rail that demonstrates a claim class has to be able to say which of its moving
parts the class accounts for.

The two mechanisms are shown apart by the rail's own control. B selects the
table's flat row — every column on its base, every enable bit still set — and
with the picture standing still, anything left moving in the melt is the CHR
and can be nothing else
(`tests/test_smelter.py::test_the_melt_churns_while_every_column_stands_still`).
**The control deliberately does not freeze the animation**: its whole value is
that exactly ONE variable moves between running and flat, and a control that
stopped the CHR too would leave two.

**The body's frames are BUILT, not rotated.** The crust's animation is a
horizontal rotation of its rows, which closes at 8 because a rotation by 8 of an
8-wide tile is the identity. The body's used to be the vertical equivalent — the
texture drifting upward — and a texture that slides is not a boiling liquid, so
it is a **bubble field** now: one bead per body tile, born at a fixed step,
rising a row per step, swelling for two and gone by the fifth. That is not a
rotation of anything, so the property that made frame 8 equal frame 0 had to be
re-established rather than inherited: every age and every rise is taken modulo
`MELT_ANIM_FRAMES`, and the generator asserts frame 0 is byte-identical to the
tile the boot upload writes. Zero extra cost — the same four tiles, the same
128 B a frame.

Bubbles are drawn in indices the body already uses (7 for the film, 5 for the
rim), never the crust's index 3, and that is checked per frame. The reason is
the test instrument, the same one §11.1's palette cycle had to respect: every
column scan finds the melt's surface by nearest match to the crust colour, so a
new bright index in the body would give `crust_y` a second edge to find and
report it as the offset table being wrong. And the tile REPEATS across the whole
lava, so a bubble is not one bubble — it is one every eight pixels. A 3x3 blob
at that density stops reading as lava and starts reading as a honeycomb, which
is why the peak radius is 1 and the shape is a plus.

Three constraints shaped what could be animated, and the first is the
interesting one:

- **The wall is excluded, and it is the one surface that could not have
  joined.** It has to be invariant under vertical displacement — one word moves
  a whole column of a layer, and the wall shares BG2 with the melt — so every
  animation frame would have to be vertically uniform, and the case that checks
  the invariance would no longer be able to tell "the wall moved" from "the
  wall animated". **Motion belongs where the constraint is not.** The lava is
  supposed to move with its column, so a texture that changes as it moves reads
  as molten rather than as a defect.
- **The animation's cycle must DIVIDE the phase loop.** The rail's picture is a
  pure function of `ES_SMT_PHASE`, which is what makes the gallery clip close on
  itself at a measured seam of 0.00/255. Eight frames every 2 phases is 16, and
  16 divides 64. Asserted in the generator, and asserted again from the picture's
  side by requiring a single constant lag to explain the frame index at every
  capture.
- **The crust's top row may not move.** It is the unbroken bright line every
  per-column equality lands on, so an animation that disturbed it would take the
  whole module down with a failure pointing at the offset table rather than at
  the art. The crust's frames rotate HORIZONTALLY, which leaves a uniform row
  alone by construction; the body's rotate vertically. Both rotations are the
  identity at frame 8, which is also why the loop closes with no discontinuity
  to hide — a seed-drift animation was the obvious first idea and does not close,
  its periods being 3, 4 and 5.

**Cost**: 128 B a frame on the channel the offset row already uses, taking the
scene to 192 B and two VBlank transfers. DAS is single-shot and the row spends
it, so the second transfer re-arms — the tree's own lesson, and the reason the
declaration says two.

**And the hygiene obligation it creates was already discharged.** A scene that
animates shared CHR hands its successor whichever frame it stopped on; here
`smt_bg` re-uploads its whole art on every scene enter, so the title is frame 0
without anything new being written. That is not an assumption —
`test_the_title_returns_with_bg3_a_layer_again` requires the returned title
PIXEL-IDENTICAL to the one before the works ever ran, and it is what proves it.

### 11.1 The wall's colour rotation — the other half, and why it is a palette

The melt churns by swapping CHR. The wall flows by rotating COLOURS, and the
split is not stylistic: **it is the constraint from §11 deciding which mechanism
each surface may have.**

The wall must be invariant under vertical displacement — one word moves a whole
column of BG2, and the wall shares that layer with the melt. A CHR animation
would have to keep every frame vertically uniform, and worse, it would leave
`test_the_wall_does_not_move_when_its_column_does` unable to tell "the wall
moved" from "the wall animated". **A palette cycle does not touch a pixel**, so
the invariance survives by construction rather than by care.

That forced a change of shape, and the change is the interesting part. The wall
used to be two indices with its streaks drawn into the tile, and **two indices
cannot flow** — rotating two colours is a flicker, not a direction. So the wall
now carries no pattern in its pixels at all: **one tile, every row identical,
every column its own palette index** (8..15, free space in the melt's CGRAM
group). The pattern IS the eight colours those indices hold, and rotating them
walks a band of lightness left to right across the whole layer, for **16 bytes
of CGRAM a frame** against the CHR swap's 128.

Two consequences worth keeping:

- **The wall's map lost its second tile.** The defect a human caught — a
  vertically uniform tile whose MAP alternated two streak phases per row, which
  is a horizontal seam every 8 pixels — was fixed by alternating on the column.
  Moving the pattern into the palette removed the alternation altogether: there
  is now one wall tile everywhere, so there is no second tile left to get wrong.
- **A palette cycle has a constraint a CHR swap does not, and it is about the
  test instrument.** Every column scan in `tests/test_smelter.py` finds its edge
  by NEAREST CGRAM COLOUR against a palette read once; while the wall's colours
  rotate, a wall pixel's colour need not be in that snapshot at all. So the
  requirement is the sharp one: every wall shade must be closer to some other
  WALL shade than to either measured edge, at every step — which the ramp's own
  span settles for every snapshot at once. Asserted in the generator and again
  from the ROM's bytes in
  `test_the_wall_cycle_cannot_impersonate_a_measured_edge`. Without it a shade
  could drift into range of the crust's white-hot line and every column scan
  would find the wall, reported as the offset table being wrong.

**Ownership went where the claim is.** `smt_mpal` is `smt_bg`'s CGRAM claim and
`smt_bg` is global to both scenes; the phase that picks a step is scene-scoped
to `works`. So `smt_bg` does the writing and `works` decides when and which —
the same split the rail uses wherever scene state drives a global asset. The
title never calls it and keeps step 0 from its enter upload.

**And matching a test pair got harder in a way worth recording.** With two art
cycles running, the invariance case has to compare frames drawn with IDENTICAL
art. Pairing on `phase % 16` looked right and failed: `TS_STEP` publishes whole
units and carries the fraction, so the phase advances 1 on some frames and 0 on
others, and the lag between the phase a test reads and the phase the NMI drew
from is not constant. The pair is matched on the ART BYTES instead — the wall's
CGRAM words and the animated CHR block, read off the machine at each capture —
which is what actually drew the frame.

## 12. The world that scrolls, and the two hardware facts it exposed

The rail started one screen wide, and a table that is exactly as wide as the
screen hides two things about offset-per-tile. Widening the world to four
screens (128 world columns, 16 plate slots, `SCREENS` in
`tools/gen_smelter_assets.py`) surfaced both, and both cost a defect first.

**The table is world space and scrolling is an addition at the read head.**
There is one blob and one row per phase, indexed by WORLD column. The DMA that
moves BG3's V row every VBlank starts at `cam + 1` instead of at 0, so the
camera costs no rebuild, no second table and no extra byte of VBlank — the
transfer is the same 64 B into the same place, from a different offset. The
`+ 1` is the fetch lead (§2), moved out of the generator and paid here, which
is what makes each row usable for two things at once: the 32 words the transfer
moves, and the one word the fallback needs. The layers' own `BGnHOFS` carry the
camera at full pixel resolution, so the 8-px quantisation of the read head and
the sub-column remainder never disagree —
`tests/test_smelter.py::test_the_same_agreement_holds_with_the_camera_off_zero`
asserts the same equality the static case asserts, at a camera two screens in,
and requires that a camera 8 px either side explains the picture at NO lag.

**A 16-bit port written from an 8-bit accumulator is a garbage write even when
the picture is identical.** The `BGnHOFS` pair is a write-twice latch: low byte,
then high. The high byte came from `xba`, which serves B — and B holds the
camera's high byte only if the camera was loaded SIXTEEN BITS WIDE. Written in
A8, the load takes the low byte and `xba` hands over whatever the previous
16-bit operation left in B, which here was the DMA source address's high byte,
recomputed every frame from the phase. `BGnHOFS` is 10 bits, so the damage
landed in bits 8-9: both layers scrolled by a multiple of 256 px, and both maps
repeat every 256 px, so **the picture was byte-identical and no test in the
module could have seen it.** It was found by reading the routine after a
different symptom, and the fix is the `rep #$20` now standing four lines above
the writes with the reason written beside it. The general shape is worth having
in mind: a wrong write whose damage is invisible today becomes visible the day
someone changes the map's period.

### 12.1 The fallback port is a whole-screen quantity, not column 0's

Screen column 0 cannot be displaced — the offset latches are cleared at the
start of each scanline's fetch (§2) — so it shows its layer's own `BGnVOFS`.
The obvious move is to load that register with column 0's own word, and the
rail did, and **it shipped a defect a person caught by looking at the clip.**

A word carries ONE enable bit. So a plate column displaces BG1 and leaves BG2 at
`BG2VOFS`; a gap column displaces BG2 and leaves BG1 at `BG1VOFS`. The fallback
registers are not column 0's — they are read by **every column whose word drives
the other layer**, which is sixteen of thirty-two on this screen. Loading
`BG2VOFS` with column 0's word therefore gave the melt behind all four platforms
one shared height belonging to the left edge: it rose and fell together, at a
different rate from the jets beside it, and SNAPPED to the base the moment the
camera put a plate under column 0. Measured before the fix, on fourteen
consecutive samples: the crust row in every plate column equalled
`where(CRUST_PX, BG2VOFS)` to the pixel.

The settlement is to spend each port on whoever else is already reading it, and
give column 0 what is left:

| port | who else falls back on it | what it carries | what column 0 gets |
|---|---|---|---|
| `BG1VOFS` | gap columns' BG1 — and a gap column has no plate pixels | column 0's own word, when column 0 is a plate column | its plate, exactly where the word says |
| `BG2VOFS` | **every plate column's melt** — sixteen columns, visible | the melt's own base, so the lava behind the platforms is one calm level | its melt at that base, not at its jet |

One column at the left edge, against sixteen in the middle. The hardware limit
is paid on the layer where nothing else was spending the port, and STATED on the
layer where something was.

Two things about how this was missed are worth keeping. Every case in the module
measured where the crust IS in the columns the table drives; **not one measured
the columns it does not** — the same shape as the wall defect in §11.1, and the
same lesson: ask what else moves when the thing under test moves.
And the picture was entirely plausible, because it was lava, and it moved.
`test_the_melt_behind_every_plate_is_one_calm_level` is the case that had no
counterpart, and `tools/plants/smelter.py::the-fallback-carries-column-zeros-melt`
restores the defect so it is not found by eye twice.

### 12.2 The lava is a collision, and until this sprint it was a picture

Every surface in this rail is a word in the offset table that the collision
reads back — the plates, from the first day (§10). The lava was not. The knight
fell to `SMT_KN_KILL_Y = 232`, a fixed screen row near the bottom of the
picture, and only then died: a player watched him drop THROUGH molten metal and
off the edge of the world, which on a rail whose whole claim is "the collision
reads the word the picture is drawn from" was the one surface still taken on
faith.

`smt_melt_top` is `smt_plate_top`'s sibling and the difference between them is
the interesting part: **the fallback is part of the answer.** A column whose
word carries the BG1 bit does not displace BG2 at all, so its melt is at
`BG2VOFS` — the melt's base, per §12.1 — and reading the word's VALUE there
would return the PLATE's height, a hundred rows wrong and in the direction that
kills the player in mid-air. A collision that reads the table has to read the
table the way the PPU does, fallback included.

What it buys beyond correctness: the surface MOVES, so a jet at its peak reaches
up and takes him earlier than the level of the lake would. That is the mechanism
being honest rather than a difficulty knob, and it is the same word doing it.

**KILLING HIM ON CONTACT WAS THE FIRST ATTEMPT AND IT WAS WRONG FOR THE
PICTURE.** He touched the crust line and vanished in the same frame, which made
the death one frame long — and the melt's own bubbling, the thing the player is
meant to watch, never had time to be seen at all. He goes IN now: the lava is
drawn behind him the whole way down, and the sprite leaves only once his highest
drawn pixel is under the surface. That is `SMT_KN_TOP`, measured off the art per
build like `SMT_KN_BOTTOM` beside it, because "fully submerged" is a statement
about his pixels and not about his 32 px cell — Arthur's frames carry eleven
transparent rows above the helmet, and taking the cell's edge would despawn him
visibly late, in the frames that are under the lava.

Then **the melt holds him for three seconds before the wipe**, and a hold is not
a pause: only the knight stops. The plates keep their harmonics, the wall keeps
flowing, and the lava keeps boiling over the place he went in — which is the
whole reason the CHR animation is worth having. The hold is counted in
`US_TSC`, the same scaled phase step the animations and the physics consume,
so `SMT_SINK_HOLD = (3 * 60 * SMT_PHASE_BASE) / 256` is three real seconds in
either region with no clock of its own. It saturates at 1 rather than reaching
0, because 1 has to keep meaning "under" through the wipe.

Two assertions, both off the picture:

- `test_he_sinks_into_the_lava_and_leaves_only_once_he_is_under` — there ARE
  frames with his pixels below the surface (he is going in), and there is NO
  frame with his highest pixel below it (he left when submerged). His pixels
  off the rendered frame, the surface off the ROM's row, re-derived every
  capture because the surface moves.
- `test_the_melt_holds_him_under_before_it_wipes` — the gap between "no OBJ
  pixel in the frame" and "no row of the blob explains the frame" is the hold,
  in emulated frames, against a length derived from the rail's own `.inc`. And
  across that gap the melt's CHR must take more than one value and the row that
  explains the picture must change, so a hold that froze the foundry fails it.

Three things cost more than they looked. The scene asked `mosaic_active` BEFORE
ticking him and the tick is what decides, so on the frame he went under the
answer was still "alive" and he was staged one more time — one frame at 60 Hz,
invisible to a player and exactly what a case reading the frame sees; two calls
and thirty cycles fixed it. Leaving the physics running under the melt kept
integrating a fall nothing stops, and ~256 rows down his 9.7 Y goes negative,
so the submersion test read the sign first, took him for "above the screen", and
stopped reaching the hold at all — the counter froze mid-count and the wipe
never came, which is why being under short-circuits the whole tick. And the new
`smt_kn_sink` claim is DP, so it is random at power-on: unwritten, it read
non-zero and the knight never appeared at boot. **A state whose zero is the
normal case still has to be written** — the uninitialised-read detector named
the two bytes.

**AND THREE ASSERTIONS IN THE STATE-CYCLE CASE WERE TRUE FOR THE WRONG REASON**,
which shortening the fall is what exposed. All three leaned on him drifting
right through a long descent: "he walked past the metal" was his X clearing the
span, which only happened in the air (the plate logic has always used his
CENTRE); "he is falling" compared his feet to the metal UNDER him, which over a
gap is nothing, so it only fired once he had drifted as far as the NEXT plate —
and it wanted a full body-height of drop, which no longer exists, because the
metal is at row ~68 and the melt takes him at ~101; "he reached the bottom of
the world" was two thirds of the picture, a depth he no longer reaches. Each is
now the statement the rail actually makes and none depends on how far he falls.
**A test that passes for a reason adjacent to its name survives every change
that keeps the reason true, and dies on the first one that does not.**

### 12.3 Death is an event, and a state cycle is not the same claim

Falling out of the world used to respawn the knight in the frame the kill test
fired: he blinked from the bottom of the screen to the spawn, and every frame of
it was a legal running frame. It is now `mosaic_arm` with `smt_kn_respawn` as the
swap callback, so the fall, the dissolve, the move and the return are one
legible event — the consumer's side of the mosaic contract (park OAM, gate the
scene's own brightness writers, `jsr mosaic_tick` last).

The test that already existed asserted the state CYCLE — he rides, he walks off,
he falls, he reaches the bottom, he comes back on the spawn plate at the ride
equality — and every one of those endpoints holds under a cut. So the event
needed its own assertion, and it is read off the picture rather than off the
mosaic's state: **while the wipe runs, no row of the blob explains the frame at
any lag**, because the PPU is replicating one pixel across each block and the
crust lines the table put in place are smeared away. Measured: fourteen
consecutive captures at 6-15 unexplained columns, bracketed on both sides by
exact fits. A cut has no such run.

## 13. `mill` — mode 4, where the AXIS is the per-column choice

`smelter` (§§10–12) is the rail this vocabulary was built for, and it cannot
demonstrate half of what the vocabulary describes. Mode 2 fetches a word for
EACH axis (`SnesPpu.cpp` `GetTilemapData`, :155-162), so a column's axis is not
something a rail chooses — it has both. **Mode 4 fetches ONE word and bit 15
picks.** That single difference is what `game/mill` exists to exercise, and it
is what makes a mixed table possible and necessary at the same time: a mode-4
rail that used one axis would be smelter with a richer BG1.

### 13.1 What the rail is

Two stations of machinery in a two-screen hall. Each is an upright, four SHAFT
columns whose words are VERTICAL and drive BG1, then a conveyor run whose words
are HORIZONTAL and drive BG2 — thirty-two columns, both axes, one 64-byte
transfer a frame and no HDMA channel anywhere. `tests/test_mill.py` asserts the
axis per column and asserts that two columns eight pixels apart disagree about
it in ONE frame, which is the statement mode 2 cannot make.

The second station's shaft carries a **lift**, and the lift is the rail's
argument that the mechanism composes with a game rather than only with a demo:
the car is a BG1 column like any other, the rider inside it is a sprite that
cannot be one, and the two rooms the lift joins are one mode, one CHR page and
one OBJ sheet apart.

### 13.2 The three things it added that smelter did not have

**The fetch lead is baked into the blob.** Offset words are fetched AFTER a
column's tilemap data, so the word at map index *j* displaces SCREEN column
*j+1*. Smelter pays that at the DMA's read head because its table is
world-space; mill's is screen-space, so the generator stores
`column_word(j + LEAD)` at index *j* and the two shifts cancel. **The rail
shipped without it once** — every bay's leftmost column stood still while its
neighbours pumped, 30 of 32 columns displaced by their neighbour's word, and it
was reported as an animation defect because that is what a fetch-order defect
looks like when you are not looking for one.

**A column can be OCCLUDED by a sprite's absence.** Mode 4 renders
`BG2lo(1) · OBJ0(2) · BG1lo(3) · OBJ1(4)` (`RenderMode4`, :824) and a sprite
draws only where the pixel already there scores lower (:958). An OBJ at
priority 0 therefore scores 2 and LOSES to BG1's 3 — so the car's shell, opaque
everywhere but a hole cut where its port is, hides the rider and the port does
not. No window register, no mask, no per-scanline work, and the occlusion
follows the car up the shaft because it IS the car.

**Sprite-versus-sprite depth is the OAM INDEX, not the priority.** This is the
one the priority table actively misleads you about, and it cost a defect: the
PPU keeps ONE sprite pixel per column, not one per priority. Mesen writes it as
a single buffer — `_spriteColorsCopy[x] = color` beside
`_spritePriorityCopy[x] = Priority` (:772-776) — so where two sprites overlap,
exactly one survives evaluation and only the SURVIVOR's priority is compared
against the backgrounds. Raising the lobby player to priority 2 to put him in
front of a retracted lift door changed nothing, measured. The rail answers by
swapping the player and the leaves through its OAM block by ride state: ahead
of them on the deck, behind them inside a bay.

### 13.3 What the falsification harness found here

`tools/plants/mill.py` is eight plants and two of them came back **TEST-BLIND**
on their first run — the plant reached the artifact and the assertion stayed
green. Both findings were about the ORACLE rather than the picture:

- `table-column-lead-removed` edits the generator, so the blob moves with the
  defect; a test that joins the picture to the blob goes on agreeing with
  itself. The oracle that does not move is the ART's geometry — a station is an
  upright and then `SHAFT_COLS` shafts — and lining the table up with that is
  the entire job of the lead.
- `the-rider-outranks-the-car` found something sharper: with the port at
  22x30 in a 32x48 car and the rider's ink 11x17, **the shell had nothing to
  cut**. Priority 0 was doing no observable work at all, and no amount of
  looking at the picture would have said so, because the picture is right
  either way. The harness reported that the mechanism could be REMOVED without
  the screen changing. The port is 18x16 now — a viewing port down to about the
  knees — which is both what the plant needs and what a lift door looks like.

The second is the more useful shape to remember: a plant that stays green is
not always a hole in a test. Sometimes it is a mechanism that is not yet
load-bearing, and the honest response is to make it so or to retire the claim.

### 13.4 A control that lost its button

The rail's flat control — the blob's last row, every column at rest with every
enable and axis bit still set, so exactly one variable differs between running
and flat — was on B. When the lift was built, B was given to holding the ride
so a still could be taken anywhere in the sequence, and **nothing wrote
`ES_MIL_FLATSEL` any more** while `hall.asm` went on describing the behaviour.
The control was unreachable for the whole of the lift's development. It was
found by `test_the_flat_control_is_a_row_and_not_a_disarm`, which selected it
and could not. Y holds the flat row now; B still holds the ride.

### 13.5 Collision, and why half of it is a scroll word

The rail was a demonstration you watched until the deck became a place to
stand. What makes its collision worth having rather than borrowed from
`col_map` is that **half of it cannot be a tile-flag table**:

- **The static half is the painter's own record.** `paint_deck_and_melt`
  registers the columns it lays a floor in, and that set is emitted as a
  32-bit map. It is not a second description of the picture — it is the same
  call. And the holes in it are not level design: A SHAFT COLUMN CANNOT HAVE A
  DECK IN IT, because it is displaced vertically so every row of it must be
  identical, and a deck is a horizontal course. The gaps in the hall's floor
  are what offset-per-tile costs on the axis this rail chose.
- **The dynamic half reads the live displacement.** The lift's four columns
  are one of those holes, and the car fills it when it is parked — its bottom
  IS the deck's top, which the generator asserts. So whether a figure can
  stand there is a function of the car's displacement, the same quantity the
  offset word for those columns carries. The tiles never change; the answer
  does.

**And `col_map` was not rejected for being narrow — two earlier accounts in
this document were wrong.** Recorded as wrong, because both were asserted
without reading enough of the feature:

- *"a tile-flag table cannot separate this floor, because the art dedups"* —
  false by measurement: the deck row's twelve tile ids are disjoint from the
  holes' and appear nowhere else in the map.
- *"col_map reads a byte-per-tile blob, which is the Mode 7 world shape"* —
  false. `jumper` and `maze` bind it in **BGMODE 1** with 32×32 worlds;
  `patrol`, `stomper` and `scroll_run` likewise. Twelve rails compose it,
  across modes, across worlds from 32×32 to 512×512.

What `col_map` wants is an **authored logical world**: one byte per cell, from
which the display tilemap is *built*. `maze_rom` says it outright — the blob is
"col_map's world AND the BG render source" — so the drawn terrain and the solid
terrain agree by construction rather than by two loops staying in step. That
model is mode-agnostic, and it is a good one.

`mill` has no such blob. Its BG1 is **painted as a picture** and then cut into
8×8 tiles; the tile ids are an artifact of the cut and the dedup, not authored
cells. There is no logical grid to bind, and making one would mean authoring
the mill as a grid and deriving the art from it — the reverse of how a
converted concept-art kit is made. The floor map here is the painter's own
record for exactly that reason.

One half of the question is outside any static world map regardless: whether
the car is under those four columns is a property of a FRAME. `col_map` states
that boundary itself — "it answers questions ABOUT the world" — and honouring
it is correct, not a shortfall.

### 13.6 A lift that never leaves is a bridge

The dynamic half shipped unreachable, and the harness is what said so. The car
only moved while the player was aboard, and he could only walk while it was
parked — so `mil_solid`'s reading of the car could never answer anything but
"floor". A plant that deleted the reading entirely left every case green.

That is the same finding shape as §13.3's port, arriving a second time in one
rail, and it is worth stating as a rule: **a mechanism whose input never varies
is not a mechanism.** The fix was to make the lift behave like a lift — it
comes when he is near the shaft and withdraws when he is not, on the same
position-driven rule the lobby's doors use, so the hole in the floor opens and
shuts and the reading has something to read. Measured afterwards: walking back
to a departed lift, he is held at the shaft's edge for ten frames and starts
moving on the exact frame the car lands.

One defect fell out of that immediately, and it is a good example of two
things being the same until they are not: the camera was `CAM_MAX - car`
unconditionally, which was correct while the car only moved with him in it.
Once the lift could leave on its own, the camera panned away from the man
standing on the deck every time it was called elsewhere. It follows the RIDE
now, not the car.

### 13.7 The floor both rooms share — the table read in bands

The hall used to read one row of the table for a whole frame, and a third
scene, the melt, was built under the deck to read three. That room is gone.
It was a scene the lift dropped into and climbed back out of, which broke the
rail's continuity for the sake of a demonstration, and the thing being
demonstrated — a molten channel every column of which carries a vertical word
— was on screen for a few seconds of a trip nobody had a reason to take.

The channel is the FLOOR OF BOTH ROOMS now. The lobby is the ground floor at
the bottom of the shaft and the hall is what the lift opens onto, so a
channel that jumped between them would be two channels; `SMIL_FLOOR_Y` (152)
and `SMIL_CHANNEL_Y` (168) are one statement of that, asserted in the
generator rather than commented, and `paint_floor` is the one function both
rooms call. The hall therefore reads three rows of the table in every frame
and the lobby two, through the same synthesized channel:

| room | band | table row | what it shows |
|---|---|---|---|
| hall | A, lines 0..`FLOOR_Y`−1 | 0, the room's running row, restaged every VBlank | the hammer's stroke, the belts running, the car with him in it |
| hall | B, `FLOOR_Y`..`CHANNEL_Y`−1 | 2, a row of zeros written once at enter | the deck plate — no enable bit, both layers at their fallback scroll |
| hall | C, `CHANNEL_Y`..223 | 1, a ripple row, restaged every VBlank | the channel, every column a VERTICAL word |
| lobby | A, lines 0..`CHANNEL_Y`−1 | 2, the zero row | the wall, the two bays and the floor plate — a room that does not move |
| lobby | C, `CHANNEL_Y`..223 | 1, the same ripple row | the same channel, at the same screen line |

`[[claims.offset_bands]] rows = 3` is the feature's, so both rooms declare
three and the lobby spends two of them — the declaration is what the table's
VRAM has to hold and what the channel is synthesized for, not a count of the
bands a given scene happens to draw.

Band C is what the split exists for. Its columns are the same screen columns
that carry a HORIZONTAL word in band A — a belt column's tread slides
sideways above the deck while its channel art slides up or down below it, by
exactly the difference of its two ripple words, and one pair of frames shows
both. Mode 4 made the axis a per-column choice; bands make it per-column PER
BAND. Band B is the control the picture carries itself: a still band between
two moving ones, from the same table, in the same frame. `Y` holds both
moving bands flat (the room's control row and the ripple's) and the whole
picture stops, pixel for pixel.

**THE HALL'S EDGES ARE THE CAMERA'S, and that is the half a fixed split
cannot show.** The deck and the channel are at fixed WORLD rows and the
camera climbs, so their screen rows are `DECK_ROW*8 − cam` and
`MELT_ROW*8 − cam`, rebuilt every VBlank from `ES_MIL_CAM` and clamped to the
picture's depth. By the time the car is a third of the way up, both have
closed and the hall reads one row again — the clamp is what makes a closing
band write no entry rather than a zero-count one, and a zero count byte is
the table's TERMINATOR.

**The ripple displaces DOWNWARD only.** A vertical word replaces the layer's
scroll, so a column pushed up by k samples k rows past the map's bottom
edge, which wrap to its top. Pushed down by k it samples k rows of the deck's
lip instead, which reads as the surface lifting under the floor — so the lip
is drawn `SMIL_RIPPLE_AMP` rows deep, and the band's top few lines can
legitimately hold still while the rest of it moves. Thirty-two ripple rows
and a flat one at the room row's stride (`mil_ripple.bin`), one ripple row
per phase, and in the hall the same walker stages both rows into one 128 B
transfer to two consecutive table rows. The walker takes a DESTINATION offset
and derives its source from it, because the lobby stages only the surface:
while that went into slot 0 the car override fired on it and the lift's four
columns held still in a rippling channel.

**What was measured, and the defect it names.** The band edges land where the
camera says: the first screen row that moves below the deck is the derived
edge, within the lip's depth and never above it. And the SPLIT CAP is 96, not
the hardware's 127. A non-repeat HDMA count byte is seven bits, so 127 is what
one entry can hold; 96 is what this rail allows, because the picture is 224
lines and 224 > 2 × 96, so every table it builds has AT LEAST THREE ENTRIES.
At 127 the hall's table collapses to two — 127 + 97 — at exactly the camera
where both lower bands have closed — `cam <= 216`, about eighty pixels
into the climb — and
measured there the channel drove `BG3VOFS` **not once in the whole picture**:
every row read whichever row the port last held, which is the channel's, so
the machines stood still and the lift car with its rider in it left the
screen. Three entries or more drove every band from the top of the picture at
every camera, at each of 96+96+32, 75+75+74, 127+83+14 and 127+63+16+18.

WHY the third entry matters is **not established**. The channel is armed
through the scene_mgr shadow and can take its first transfer of a frame from
the seeded `$43x8/9` and `$43xA` before the frame-start init reloads them
(below), and a two-entry table is the case where that transfer's own reload
lands on the table's terminator — but why a third entry survives the same
seed is not something reading `SnesDmaController.cpp` settled, and two other
seeds were measured and each broke a different part of the picture. The rule
followed here is the measurement, and `tools/gen_mill_assets.py`'s `BAND_MAX`
and `mil_band.asm` both say so in those words rather than inventing a
mechanism. `tools/plants/mill.py` plants the 127 back, so the cap cannot
quietly return.

**The seed the shadow needs.** The room's first frame read 382 bytes of RAM
nobody had written (`$7E:0003` up to `$7E:01B9`). The NMI copies a channel's
shadow slot to `$43x0-$43xA` and sets `HDMAEN` in the same VBlank, and a
channel enabled mid-frame runs on that VBlank's remaining lines from whatever
`$43xA` (the line counter) and `$43x8/9` (the current table address) hold —
the init that reloads them comes at the NEXT frame's line 0. Each line
decrements the counter first; from zero that wraps to `$FF`, "repeat, 127
lines", a transfer every line from an address stepping by the transfer's
width (`SnesDmaController.cpp ProcessHdmaChannels`: decrement, DoTransfer =
bit 7, a new entry only when the low seven bits reach 0). Three seeds, three
pictures: `$43xA = 0` walks memory as above; `$7F`, the longest plain hold,
ends the walk but the hold lands on EVERY frame, so the first band's write
reaches `BG3VOFS` at line 128 and the top 128 lines read whichever row the
port already held — the hall's machines standing still under a table that was
advancing; `1` gives no walk, no hold, and every band from the top of the
picture. **It is NOT harmless to the picture**, which an earlier draft of this
section said it was: removing the seed on a tree that had it put the hall's
machine band back to reading the room's row for about 27 lines and the walk's
leavings under that. §14 records it as a limit of the shadow, and the fix
belongs there — seed every armed slot's counter, or defer the `HDMAEN` write
to the frame's own init — rather than in each rail that arms one.

**What the harness said.** Five plants on the bands — the deck band reading
the ripple row, the channel band reading the machine row, the ripple staged
from the room's row, the band channel never armed, and the split cap put back
to 127 — each FIRED on the case written for it, alongside the hall's
(`tools/plants/mill.py`). Three of the hall's older plants stopped applying
when the walker was refactored for a second row and were re-anchored; a plant
whose anchor drifts is reported as PLANT-NOT-APPLIED rather than counted,
which is the harness refusing to pass on nothing.

**A defect the zero row found.** `mil_zero_row` and the lobby's `lobby_flat`
wrote their 32 zero words with 16-bit `stz` to `$2118` and `$2119`: the
first store writes both port bytes and steps the address, the second writes
the NEXT word's high byte and `$211A` (M7SEL), so every odd word kept a
stale low byte and the loop's 32 turns reached 64 words. Harmless by luck —
the enable bits are in the high byte, which was zeroed, and mode 4 never
reads M7SEL — and visible the moment a room read its zero row back:
`0000 0075 0000 007f`. Both loops store 8-bit now.

**And a defect the camera found.** Two rows chosen against the old camera did
not survive the move that put the channel on screen. The camera now rests at
the map's bottom, and there a ram at `FLOOR+13` spent half its stroke ABOVE
the picture — measured, the whole of v=0..72 changed nine screen rows,
because the only part of the hammer ever in frame was the bottom of it — and
a conveyor at `FLOOR+20` sat in the middle of the run the head needed. The
ram is at `FLOOR+18` and the belt at `FLOOR+24`: the head hangs at screen
80..128, lifts to 8..56, and comes down onto the conveyor. A row is the
SUBJECT'S VISIBILITY here, not decoration, and the generator says so where
the constant is.

## 14. Stated limits

- **The offset TABLE'S CONTENT is not modelled.** The claim says BG3's tilemap
  is a table of scroll words; it does not say which words, how they get there,
  or how often. That is the rail's business, proved the way everything here is
  proved — on the emulator, by tests that read the rendered output.
- **Mode 7's BG2 is an approximation.** `MODE_LAYERS[7]` is BG1 alone, and a
  bg2 designation there warns rather than refusing, because EXTBG has no model
  in this tree (docs/09 G5). If EXTBG is ever declared, that row and that
  warning are what change.
- **A per-scanline BGMODE rewrite stays raw.** `split_band` swaps the mode at a
  scanline seam and is mode-agnostic by construction; the vocabulary has no
  per-scanline story, and composing a video claim against an active-phase
  BGMODE transfer refuses with a message that says exactly this.
- **`tiles16` is composed and not checked further.** 16x16 tiles change the
  tilemap's addressing, and nothing here verifies that a claim's tilemap is
  sized for them.
- **Direct color is ALL-OR-NOTHING PER LAYER, and the vocabulary cannot make
  it otherwise.** `direct_color` is one CGWSEL bit for the whole frame, so a
  scene that declares it declares it for every pixel of its 8bpp layer: the
  layer's CGRAM entries stop being read at all, and its fitted palette is
  retired. Per-region control would be an HDMA channel on `CGWSEL`, which is
  a raw `[[claims.reg]]` + `[[claims.hdma]]` shape this vocabulary composes
  nothing for — the same line `split_band` sits on for BGMODE. `mill`'s two
  builds are the honest statement of the cost: `build/mill.sfc` is the
  96-entry fitted palette and `build/mill_direct.sfc` is the same geometry
  with the palette gone, and they are two ROMs rather than two regions of one
  because there is no third option in the silicon.
- **Nothing checks that an 8bpp layer's ART is direct-colour art.** The
  composition proves the scene declared the rule its pixels are read by; that
  the pixels MEAN anything under it is the rail's business, proved on the
  emulator by a test that reads the rendered pixel (`tests/test_mill_direct.py`
  computes the expected BGR555 from the CHR byte and the tilemap word the PPU
  actually read, and asserts the screenshot). A declaration is not a
  quantiser.
- **The composition proves declarations, not writes.** The emitted symbols and
  the write consent exist so scene code CAN establish the composed state
  through the gate; whether a scene actually writes them is proven on the
  emulator.
- **One column's word drives one layer, with one value.** Bits 13 and 14 select
  which BG a V word displaces and the value is shared, so a column cannot place
  BG1 and BG2 at two different heights. Setting both bits gives them the SAME
  height, which for a plate over lava is worse than the fallback. This is
  hardware, not vocabulary — but it is the reason §12.1's settlement is a
  trade-off and not an oversight, and a composition that needs two independent
  per-column displacements needs a second mechanism.
- **The fallback ports are not modelled at all.** `[[claims.offset]]` says a
  table displaces named layers; nothing in it says that a layer's own
  `BGnVOFS`/`BGnHOFS` is simultaneously the value for every column the table
  does NOT drive on that layer. The allocator registers the ports as owned
  (`smt_fallback` here) and stops there. What they carry, and who else is
  reading them, is the rail's business and is proved on the emulator — §12.1 is
  the case that says why that is a limit worth naming rather than a detail.
- **Collision is not modelled by the vocabulary at all, and could not be.**
  `mill`'s floor map is emitted by its own generator and read by its own
  feature; nothing in `[[claims.offset]]` says that a displaced column cannot
  carry a horizontal course, which is the fact the holes in that floor come
  from. The composition proves the columns do not collide as RESOURCES; what
  the art in them can be is the rail's to know. §13.5 is the case for why that
  line is in the right place — a vocabulary that tried to model it would be
  modelling the picture.
- **A channel armed through the scene_mgr shadow runs from its seeded slot,
  and NOT only on the arming frame.** §13.7 measured it: the NMI copies the
  slot and sets HDMAEN in one VBlank, and the channel's first transfer of a
  picture can come off `$43x8/9` and `$43xA` rather than off what the
  frame-start init derives from A1T. Zero wraps to a 127-line repeat that
  walks memory two bytes a line (a rule-5 finding); `$7F` holds the first
  band's write off until line 128 on every frame; `1` is what `mil_band`
  seeds and what leaves the picture right. An earlier draft of §13.7 called
  this harmless to the picture because line 0 re-inits — it is not, and
  removing the seed put the hall's machine band back to reading its row for
  about 27 lines. It is also the suspect in the two-entry table §13.7
  records, which is a defect this vocabulary cannot see: the composition
  proves the CHANNEL is the scene's, not that the table the rail builds for
  it has a shape the hardware runs. A fix in the shadow itself (seed every
  armed slot's counter, or defer the HDMAEN write to the frame's own init)
  is the right shape and is not in this sprint. No other rail's slot seeds
  `$43xA`.
- **The rows a band names are not checked to exist.** `rows = 3` promises
  three rows of the table; the composition cannot see the table's VRAM claim
  (below), so it holds the hardware ceiling of 32 and stops. A band naming a
  row the table does not hold reads whatever is there.
- **Nothing here reaches the offset table's VRAM PLACEMENT.** BG3SC bases are
  1K-word granular and the fetch reads two rows of the claimed region, so 30 of
  a 32-row map are addressable and never read. That is what the granularity
  costs and it is cheaper than any way of avoiding it.
