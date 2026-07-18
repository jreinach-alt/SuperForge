# Troubleshooting — symptom → cause → fix

Indexed by WHAT YOU SEE. Find your symptom, apply the fix, move on. Every
entry here is a failure class that actually happened during the kit's build —
none are hypothetical.

**The probe-first rule:** before reasoning from source, READ THE HARDWARE
STATE — debug magic, OAM, VRAM, CGRAM, a screenshot (`/inspect`). The emulator
is ground truth; five minutes of probing beats an hour of code archaeology.
The first four entries below are the standard probe ladder.

---

## Probe ladder (run these in order when "it doesn't work")

| Probe | Reads | Healthy looks like |
|---|---|---|
| 1. Boot check | WRAM `$E000`, 4 bytes | `b"SFDB"` — the ROM booted and reached `sf_debug_magic` |
| 2. Liveness | WRAM `$E008`, u16 | `1` — ran to `sf_debug_complete`. Test ROMs set it; game TEMPLATES generally don't (they loop forever after `sf_debug_magic`) — a 0 there is only a finding if the ROM actually calls the macro |
| 3. Screenshot | `take_screenshot()` | the world you expect (works headless) |
| 4. State dump | OAM / VRAM / CGRAM / your DP vars | values you wrote, not zeros/garbage |

---

## Build errors

### `Error: ':' expected` or `Unexpected trailing garbage` at a macro call
**Cause:** the macro's `.inc` was not included — ca65 reads the unknown macro
name as a label.
**Fix:** add the missing `.include` (the macro→include map is in
`lib/macros/README.md`).

### `Range error (N not in [-128..127])`
**Cause:** a short branch (`beq`/`bne`/`bcc`/`bcs`) jumps over a macro call
whose expansion is >127 bytes (the print macros, `sf_camera_follow`,
`sf_physics_step`, `col_box` chains...).
**Fix:** the trampoline idiom — invert the branch to a near label and `jmp`:
```asm
    beq @do
    jmp skip_it
@do:
    sf_print_u16 SCORE, #56, #8
skip_it:
```

### `Symbol '@loop' is undefined` after adding a macro call
**Cause:** macros with `.local` labels (`sf_solid_box`, `sf_physics_step`,
`sf_jump`, `sf_pool_spawn`, the patrol/stomp macros) expand to real labels,
which END the cheap-local `@` scope — an `@label` defined before the call
can't be referenced after it.
**Fix:** use a named label for any branch that spans such a macro call.

### `Cannot open include file`
**`.include` vs `.incbin` resolve DIFFERENTLY — do not conflate them.**

- **`.include "foo.inc"`** (text source): ca65 searches the INCLUDING FILE's
  directory plus the `-I` paths (`lib/macros`, `engine`,
  `infrastructure/rom_template`, and — for a template build — that template's
  own `assets/`). It does NOT use your shell's cwd.
  **Fix:** write the path relative to the file doing the including (e.g. a test
  ROM in `tests/` includes `fixtures/png2snes/hero16.inc`; a template includes
  `assets/<theme>_collision.inc`), or rely on an `-I` dir.

- **`.incbin "foo.bin"`** (binary blob, e.g. a Mode 7 map): ca65 does **NOT**
  honor `-I` for `.incbin` — `-I` is a *source*-include path only. `.incbin`
  searches the INCLUDING FILE's directory and your shell's CWD (and
  `--bin-include-dir`, which the kit does not pass). So a repo-root path like
  `templates/rpg/assets/ovw_map.bin` only works by the CWD branch (you build
  from the repo root), and a copied template silently breaks until you also
  change the `templates/<old>/` part of the path.
  **Fix (the copy-safe form the templates now use):** write the `.incbin`
  path relative to the including file — `.incbin "assets/<basename>.bin"`. Then
  copying `templates/rpg/` → `templates/<theme>/` only needs the *basename*
  changed (`ovw_map.bin` → `<theme>_map.bin`), never the directory, and the
  build no longer depends on which cwd you launch `make` from.

### `ld65: Warning: Segment 'SRAMDATA' does not exist`
**Cause:** the linker config declares an SRAM segment no kit ROM uses.
**Fix:** none needed — benign, every kit ROM prints it. (Tracked for the
repo split, which will own its `lorom.cfg`.)

---

## Boots wrong / shows nothing

### Black screen, no debug magic at `$E000`
**Causes, most common first:**
1. Code emitted before `.segment "CODE"` — `header.inc` leaves the assembler
   in the VECTORS segment; anything before the segment directive corrupts the
   vector table. The ROM links fine and boots nowhere.
2. The frame loop runs but NMI was never enabled — `sf_frame_begin` spins on
   `NMI_DONE_FLAG` forever. Write `$81` to `$4200` after setup.
3. Setup order broken — see the contract comment at the top of `sf_bg.inc`
   (coldstart → uploads → init_ppu → gfxmode → mset → NMI on → loop).

### Magic present, completion flag stuck at 0
**Cause:** the code crashed between magic and complete. The classic silent
killer is a WIDTH BUG: a label reached in 8-bit A that the assembler tracked
as 16-bit (or vice versa) executes a stray byte as BRK.
**Fix:** `make width-check` — the gate catches the known patterns. If clean,
probe your DP state to find the last value that looks sane.

### The screen is garbage / random colored tiles
**Cause:** VRAM/CGRAM uploads ran with the screen ON. PPU memory is only
writable during forced blank or VBlank; mid-frame writes scatter.
**Fix:** all `sf_load_*` / `sf_*_color` / `sf_text_init` calls go in setup,
after `sf_coldstart` (which force-blanks) and BEFORE `init_ppu`/`gfxmode`
turn the screen on.

---

## Sprites

### Sprite invisible
Check in order:
1. `spr_clear` called once before the first draw? (OAM is NOT in the
   coldstart baseline — unparked slots hold garbage, often off-screen.)
2. OBJ tiles loaded (`sf_load_obj_tile` / `sf_load_obj_chr`) under blank?
3. OBJ palette set (`sf_obj_color` / `sf_load_obj_pal`)? Color 0 is
   transparent — a sprite whose pixels are all index 0 renders as nothing.
4. `spr` flags palette bits (bits 3:1) pointing at the palette you loaded?
5. Y in 0..223? y=$F0 is the park-off-screen convention.

### Sprite shows the WRONG GRAPHIC (shifted/garbled tiles)
**Cause:** a 16x16+ sprite reads its second tile row at +16 tile numbers —
the hardware's OBJ VRAM grid. A CHR blob loaded at a non-16-aligned base tile
shears every frame. (`sf_load_obj_chr` asserts the alignment at build time;
hand-written uploads don't.)
**Fix:** load png2snes blobs at base tiles 0, 16, 32, ...; OAM tile = base +
`<name>_fN`.

### 16x16 sprite renders as a tiny 8x8 corner (or vice versa)
**Cause:** OBSEL size-pair mismatch. `init_ppu` sets `$2101=$00` (8x8 small /
16x16 large); `spr` flags bit 7 selects which half of the pair. A 32x32
sprite needs a different pair (e.g. `$60` = 16/32) — re-set `$2101` under a
brief forced blank after `init_ppu` (see `tests/png2snes_sprite_test.asm`).

### Sprite appears on the RIGHT edge when it should be off the LEFT
**Cause:** X is 9 bits; bit 8 lives in the OAM hi-table. `spr` handles it —
this bites only hand-written OAM writes.
**Fix:** use `spr`, or set the hi-table X9 bit for negative/>255 X.

### A "parked" sprite shows a fragment at the TOP of the screen
**Cause:** OAM Y wraps mod 256. The park-off-screen convention y=$F0 (240)
hides 8x8 and 16x16 sprites, but a 32x32 sprite at 240 spans rows 241-272 —
and 257+ wraps back to screen lines 1-16, so its bottom rows peek out at the
top.
**Fix:** park 32x32 (and larger metasprite parts) at y=$E0 (224): every row
lands in the hidden 225-255 band. Rule of thumb: park_y = 224 works for ALL
sizes; $F0 only for sprites 16px and shorter.

### My actor changed OAM slot / tests can't find it
**Cause:** `spr` assigns slots in call order after `spr_clear` — skipping a
dead actor's draw COMPACTS later actors into earlier slots.
**Fix:** the stable-slot idiom — draw EVERY pool slot every frame, dead ones
at y=$F0 (see `sf_pool.inc` and the shmup template).

---

## Backgrounds & text

### Tilemap I built is empty / partially wiped
**Cause:** `gfxmode` ZEROS the shadow tilemap when it runs.
**Fix:** call `mset` AFTER `gfxmode`, never before.

### BG tiles render with wrong colors
**Cause:** the tilemap word's palette bits (10-12) don't match the palette
the colors were uploaded to. png2snes bg map words carry the right bits —
pass them to `mset` UNALTERED, and upload with `sf_load_bg_pals 0, ...`
(palette numbering in the map starts at 0).

### Text invisible, or behind the background
**Cause:** printing before `gfxmode` (which wipes BG3), or the font wasn't
uploaded (`sf_text_init` under blank). Priority is handled by construction
(print sets the BG3 priority bit).
**Fix:** order per `sf_text.inc`'s header. Also: the font owns BG1 tiles
80-127 (shared CHR base) — keep your BG art in tiles 0-79 when using text.

### `col_map` always returns 0
**Causes:** (1) terrain was never flagged — run `sf_tile_flags` after
building the map; (2) the query is off-map — coordinates are pixels, not
cells. (Tilemap dims are set by `gfxmode` by construction in this kit.)

---

## Game logic

### My array/pool reads back garbage that I never wrote
**Cause:** the arrays live at `$2000+`. With DB=$00, addresses `$2000-$5FFF`
are hardware registers / open bus — NOT WRAM. Reads silently return junk.
**Fix:** game arrays live in `$1800-$1DFF` (the game-array region — see
`sf_pool.inc`'s header for the full memory-placement contract).

### My loop counter is destroyed mid-loop
**Cause:** engine-calling macros (`spr`, `mset`, `col_box`, the print
macros...) clobber A, X, Y.
**Fix:** keep loop counters in DP (`BOFF = $3E` style), reload X from them
after each macro call. Pure-indexed code (the pool iteration idiom) keeps X.

### Movement works right but not left (or down but not up)
**Cause:** unsigned compare on a wrapped subtraction — `0 - 2 = $FFFE`, which
is HUGE unsigned, so it passes a `cmp #MIN`/`bcs` lower-bound check AND a
`cmp #MAX` upper-bound check the wrong way.
**Fix:** make the wrap impossible by construction: keep the position's
minimum >= the maximum step (the shmup clamps PX at 8 and asserts
`SHIP_SPEED <= 8`, so `PX - SHIP_SPEED` can never go below 0), and put an
assemble-time `.assert` on the tunable so a retune can't silently break the
invariant. Then TEST ALL FOUR DIRECTIONS on the emulator; one-direction
tests ship the other broken.

### Everything moves at the wrong speed after refactoring
**Cause:** double-stepping — calling an update macro (physics, autoscroll,
patrol) more than once per frame, or outside the `sf_frame_begin`/`end`
bracket.
**Fix:** one update per actor per frame, inside the frame bracket.

### After a scene swap, the player won't move (or won't interact) until I let go and press again
**Cause:** grid movement / interaction reads the button with a `btnp` **edge**
(pressed-this-frame), but the button was already held *through* the
`sf_scene` swap. The destination scene boots with the button down, so there is
no fresh press edge — the first step/interact silently no-ops until the player
releases and re-presses.
**Fix:** this is correct hardware behaviour, not a bug — design for it. In a
test or a scripted intro, **release the button after the swap before driving
the destination scene** (hold Up to walk onto the trigger → release → press Up
again to take the first step in the new scene). When authoring a golden /
oracle `script`, insert an empty-button frame after the transition completes
(`sf_scene` returns to its idle state) before the next directional press.

### My save→reset→load test passes but the save is actually broken (or: a stale save haunts later tests)
**Cause:** Mesen persists battery SRAM to `<home>/Saves/<rom>.srm` on shutdown
and **reloads it on the next `LoadRom`** — across processes, not just within
one. So (a) a stale `.srm` from an earlier save-writing run silently seeds a
"valid save" into a later test (or a screenshot capture), making it boot from
that save instead of cold; and (b) a save→reset→load test that *seeds* SRAM and
reads back the same value proves nothing if it never power-cycles through the
file.
**Fix:** for a real power-cycle, drive the in-game save, then `MesenRunner`'s
`persist_sram_across_reload` (or two `load_rom` calls on one runner —
SaveRam survives an in-process reload) and assert the ROM **boots into** the
saved state. **Delete the `.srm` before any capture that must be a cold boot.**
And assert the restored **position from the rendered OAM sprite**, not from the
WRAM variable the load writes — reading the loaded variable back is circular;
the OAM entry is the rendered proof (use a map-edge tile so the camera clamps
and the on-screen position is unique to the tile).

---

## Mode 7

### The floor renders, but above the horizon is a stretched smear of the map
**This is the "floor-in-sky" defect — a MANDATORY fix for any floor with a
visible horizon, NOT an accepted limitation.** Mode 7 has a single BG layer,
so the band above `l0` keeps rendering the ground tilemap (stretched) where a
SKY belongs. Whenever the horizon is on-screen (`sf_mode7_perspective` `l0`
above 1 — i.e. the floor does not fill the whole screen top-to-bottom), you
MUST do BOTH of these together:

1. **`sf_mode7_flags #$C0`** — set M7SEL out-of-map behaviour to FILL (tile 0),
   not the default WRAP (`$00`). WRAP tiles the floor across the off-map area;
   FILL shows tile 0 instead. (Half the bug is WRAP doing the smearing.)
2. **`sf_mode7_sky_split #l0, table_addr`** — the kit's reusable macro
   (`lib/macros/sf_mode7.inc`) that arms a per-scanline TM HDMA on CH2 to turn
   BG1 OFF above scanline `l0`, so the CGRAM[0] backdrop shows there. Reserve
   CGRAM index 0 as a SKY colour in your asset generator (mirror the racer's
   `make_track.py` / the rpg's `reserve_sky_backdrop`). For a richer sky, layer
   an RGB gradient (`gradient_rgb`, engine fn 76) on a free channel above it.

No template should hand-roll this anymore — call `sf_mode7_sky_split`. A floor
with `l0 == 1` (the near-orthographic top-down view, horizon at the very top)
legitimately fills the screen and does NOT need the split. Any floor with a
horizon in the tens of scanlines MUST arm it, or you ship the smeared sky the
user will reject. (History: the rpg overworld shipped without this and was
rejected; the racer's `arm_sky_split` was the proven pattern the macro
generalises.)

### The floor renders but never moves or rotates
**Cause:** the per-frame service isn't running, or the camera state never
got flagged dirty — `sf_mode7_tick` only rebuilds/re-anchors when
`sf_mode7_cam` (or a perspective/focus/flags macro) set a dirty flag.
**Fix:** call `sf_mode7_cam ...` then `sf_mode7_tick` once per frame in the
loop, plus one `sf_mode7_tick` during setup so the first displayed frame has
valid tables.

### Sprites are invisible over the Mode 7 floor (the same code worked in Mode 1)
**Cause (two, both silent):**
1. `SHADOW_TM` lost the OBJ bit — `mode7_init` preserves only bit 4 and ORs
   in BG1, so if OBJ wasn't already on in the shadow, TM commits as
   BG1-only.
2. The OBJ name base sits inside the map's VRAM — the Mode 7 map fills
   words `$0000-$3FFF` wholesale, and an OBSEL base of `$00` makes every
   sprite fetch tile bytes from the map data (garbage tiles or "nothing"
   if those bytes are transparent).
**Fix:** set the OBJ bit before `sf_mode7_on` (`lda #$10 / sta SHADOW_TM`),
move the name base out of the map (`OBSEL = $62` = base word `$4000`), and
upload the CHR there (`sf_load_obj_chr 1024, ...` — tile 1024 × 16 words =
word `$4000`). `templates/racer/main.asm` is the worked example.

### `print` / `sf_text` draws nothing in Mode 7
**Not a bug:** BG3 does not exist in Mode 7 — the mode has exactly one BG
layer (the floor) plus OBJ, so the text renderers have no layer to write
to. **Fix:** sprite-based HUDs (the racer's speed bar) — or the mode-split
band, which is the text path and out of rail scope.

---

## Asset conversion (png2snes)

### `REJECT: N distinct opaque colors ... palette holds 15`
Your art exceeds a hardware palette. The error lists the busiest frames.
Options are in the message: redraw at SNES scale, split animations with
disjoint colors into separate conversions, or `--auto-fix` (lossy, writes a
preview PNG — LOOK at it before shipping).

### `REJECT: ... not hardware-scale pixel art`
The input is high-res / AI-generated art, not pixel art. There is no faithful
conversion — commission or redraw at the target size (16x16/32x32, ≤15
colors). This is the converter protecting you from mush, not a bug.

### `REJECT: frames have opaque content larger than the box`
One or more frames don't fit the `--size` box. The error names them and the
content size; convert at the next size up or crop stray pixels.

### `REJECT: tiles need N palettes; SNES BG hardware has 8`
The tileset's global palette assignment doesn't fit. Convert a sub-region
(`--region x,y,w,h` — e.g. one season/biome), or merge near-duplicate colors
in the source. The error names a forcing tile per palette.

### Converted art renders fine but the colors are slightly off
**Not a bug:** SNES color is 5 bits per channel — the converter quantizes
24-bit source colors to BGR15 (each channel loses its low 3 bits).

---

## Tests & emulator

### Screenshot pixels read black/garbage at the top rows (or rows are off by ~8)
**Cause:** Mesen screenshots are 256×239 and include the vertical blanking
pad — active display starts at roughly y≈8, and the bottom edge carries a
similar pad. A pixel probe at y=0..7 samples blanking, not your scene.
**Fix:** sample inside the active region (y≈8..230), or better, self-calibrate:
scan for the first non-backdrop row and select probe rows relative to a
feature you rendered (see `tests/test_platformer_v2.py` for the pattern).

### A register read and a screenshot disagree by a frame
**Cause:** the emulator FREE-RUNS in real time — two reads are never atomic.
**Fix:** event-driven polling (wait for the state, then assert) and ±1-2
frame tolerances on correlated reads. See `tests/test_shmup.py` for the
patterns. Never assert exact equality between two separately-sampled
free-running values.

### A test passes but the feature is visibly broken
**Cause:** the test asserts a proxy (a variable that "should" reflect the
output) instead of the output.
**Fix:** assert on the real surface — OAM bytes, VRAM bytes, screenshot
pixels. A test that passes while the feature is broken is worse than no
test (`test-authoring` skill).
