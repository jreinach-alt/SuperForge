# 100 — The video/offset vocabulary: a scene's mode, and BG3 as data

> Status: LIVE — `claims.video` + `claims.offset` (C6), landed 2026-08-28.
> The fifteenth and sixteenth claim classes (`allocator/schemas.py`), the
> per-scene composition and refusal set (`allocator/allocate.py`,
> `compose_video_offset`), and the writer-side consent that lets scene code
> write the composed state (the synthesized ownership claim in each scene's
> `symbol_map.json` reg union). Exercised by one rail, `smelter`.

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
the PPU never runs. And the mode-4 row is why `axis = "both"` is expressible
in modes 2 and 6 and not in 4.

**Two things about offset-per-tile were measured on a shipped binary rather
than read**, because reading a fetch order is not the same as watching it:

- **The offset words for a column are fetched AFTER that column's tilemap
  data**, so the word written at table column *k* displaces **screen column
  k+1**. Before `tools/gen_smelter_assets.py` shifted its table to match, the
  first plate rendered three columns wide with an invisible ghost beside it.
- **Screen column 0 cannot be displaced at all** — the latches are cleared at
  the start of each scanline's fetch, so the leftmost column always shows its
  layer's own `BGnVOFS`.

`tests/test_smelter.py::test_the_offset_leads_its_column_by_one` asserts the
first as a measurement rather than as an assumption: a shift of 0 explains the
picture and ±1 does not, so the maximum is sharp.
`test_screen_column_zero_cannot_be_displaced` asserts the second against the
value the scene wrote to BG2VOFS.

## 3. The vocabulary

Two claim classes, declared in `feature.toml` like every other claim, composed
per scene like every other claim.

```toml
[[claims.video]]           # the scene's VIDEO MODE — one per scene, one owner
mode = 2                   # 0..7                      (BGMODE b2-0)
bg3_priority = false       # optional, default false    (b3, mode 1 only)
tiles16 = []               # optional: bg1|bg2|bg3|bg4  (b4-7)

[[claims.offset]]          # OFFSET-PER-TILE: BG3's tilemap IS the table
axis   = "v"               # h | v | both
layers = ["bg1", "bg2"]    # the enable bits it may set: 13 -> BG1, 14 -> BG2
```

A video claim declares the scene's display shape; it has one owner per scene,
and a mid-frame mode change is a per-scanline HDMA rewrite that keeps the raw
`[[claims.reg]]` shape (`split_band` is that feature, and it is deliberately
mode-agnostic).

An offset claim declares that **in this scene BG3 is not a layer**. The table
it points at is an ordinary `[[claims.vram]] kind = "tilemap"` region and
always was; what the claim classes could not say is the consequence, which is
that every other feature's belief that it can draw on BG3 is now false.

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

A scene that declares neither claim has **no composition at all**, not an
empty one, which is what keeps every rail predating the vocabulary
byte-identical.

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

Each warning is counted in the allocator's summary line beside the refusal
checks, so a run that examined nothing reads as having examined nothing.

## 6. Emission

For every scene carrying at least one vocabulary claim, the scene's generated
include gains a symbol **per half the composition owns**:

```
ES_VID_<SCENEID>_BGMODE            where the scene declares a video mode
ES_OPT_<SCENEID>_BG1 / _BG2        the enable bits its offset claim declares
ES_OPT_<SCENEID>_MASK / _HMASK     the value field for the axes it declares
ES_OPT_<SCENEID>_VSEL              mode 4 only: the axis-select bit
```

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

## 10. Stated limits

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
- **The composition proves declarations, not writes.** The emitted symbols and
  the write consent exist so scene code CAN establish the composed state
  through the gate; whether a scene actually writes them is proven on the
  emulator.
- **Nothing here reaches the offset table's VRAM PLACEMENT.** BG3SC bases are
  1K-word granular and the fetch reads two rows of the claimed region, so 30 of
  a 32-row map are addressable and never read. That is what the granularity
  costs and it is cheaper than any way of avoiding it.
