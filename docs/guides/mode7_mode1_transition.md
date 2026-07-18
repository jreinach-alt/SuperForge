# The Mode 7 ↔ Mode 1 transition primitive (`sf_swap_to_mode7` / `sf_swap_to_mode1`)

A Mode-1 ↔ Mode-7 BG-mode switch is **discontinuous**: `BGMODE`, the whole VRAM
image, and the shared `CGRAM 0-15` all change at once. Show any of that mid-change
and you get a torn frame. This primitive brackets the whole rebuild in forced blank
+ NMI mask so the swap is atomic, and bakes in the three gotchas the hand-rolled
RPG/boss sequence kept re-hitting.

The proof + worked example is **`templates/meteor_event/`** — an in-level "meteor
event" cutscene in a Mode-1 platformer that swaps to Mode 7 for a falling meteor and
back. Run it: `make meteor_event`.

> **Provenance.** This promotes the RPG overworld↔town swap (`templates/rpg/`) from a
> copy-pasted sequence into a documented brick. The roadmap's old shorthand
> "`sf_mosaic_transition` + `mode_band`" was a **misnomer** — there is no `mode_band`
> brick; the transition is `sf_swap_to_mode7`/`sf_swap_to_mode1` over the forced-blank
> scene-init contract. (The Mode-7 sky-split TM HDMA that name conflated with is a
> separate, out-of-scope shape — see "What this is NOT" below.)

---

## The macros (`lib/macros/sf_scene_mode.inc`)

```asm
; Mode 1 -> Mode 7 (atomic; brackets its own blank_enter/exit — do NOT nest it)
sf_swap_to_mode7  map_label, map_size, pal_src, pal_count
;   map_label   interleaved Mode 7 VRAM blob (any bank)
;   map_size    transfer size in BYTES (#$8000 = full 32 KB)
;   pal_src     ROM label of the Mode 7 plane palette (N .word BGR15)
;   pal_count   number of COLOURS to restage into CGRAM 0.. — a BARE constant
;               (e.g. 16, NOT #16; used in a `cpx #(N*2)` expression)
; After it returns the screen shows the Mode 7 plane (BG1) + OBJ at the shadow
; brightness. Call sf_boss_center / the first sf_boss_matrix AFTER it.

; Mode 7 -> Mode 1 (framing pair — caller's BG uploads run BETWEEN the two halves)
sf_swap_to_mode1_begin  mode      ; blank -> sf_mode7_off -> gfxmode #mode -> re-blank
    ; ... caller's BG CHR / palette / mset uploads here, under the still-raised blank ...
sf_swap_to_mode1_end    TM_value  ; set SHADOW_TM (e.g. #$11 = BG1+OBJ) -> unblank -> NMI on
```

`ca65` macros can't take a code block, so the reverse swap is a **framing pair**: the
caller runs its Mode-1 CHR/palette/tilemap uploads between `_begin` and `_end`, all
under the one forced blank the `_begin` half leaves raised.

### The three gotchas the macro handles for you

1. **`CGRAM 0-15` is shared** between the Mode-1 BG palette and the Mode-7 plane
   palette. A Mode-1 palette load overwrote 0-15, so the plane would render near-black.
   `sf_swap_to_mode7` **re-stages the Mode-7 palette** under the blank (`pal_src`/`pal_count`).
2. **BG1 CHR (word `$2000`) lives inside the Mode-7 map region (`$0000-$3FFF`).** The
   Mode-1 BG CHR upload clobbered the Mode-7 image, so the macro **re-uploads the map**
   under the blank. (Symmetrically, `_begin`/`_end` is where you re-upload the Mode-1
   BG CHR when coming back.)
3. **`gfxmode` turns the screen back ON** (`INIDISP=$0F`) and enables BG1/2/3 mid-sequence.
   `sf_swap_to_mode1_begin` **re-raises the blank** after `gfxmode`, and `_end` sets
   `SHADOW_TM` explicitly (use `#$11` = BG1+OBJ to mask BG2/BG3 — their uninitialized CHR
   would otherwise decode as full-screen garbage, a real power-on-fidelity trap).

---

## Persisting a Mode-1 scene across the swap — the BG→OBJ capture (the crux)

The swap blacks the Mode-1 BG. To keep the player + platforms visible while the BG is
gone (so the ground looks seamless across the mode change), **capture the visible BG
tiles into OBJ sprites** — OBJ is mode-independent, so it survives the swap untouched.

`templates/meteor_event/` does this dynamically (`draw_capture_sprites`):

```
at freeze: walk the visible BG1 shadow tilemap; for each PLATFORM cell emit an OBJ
sprite at  X = mx*8 - hofs ,  Y = my*8 - vofs   (the frozen camera's scroll)
then black the BG (clear TM bit0) — the captured OBJ ground now stands in for it.
```

Two things to decide:

- **CHR strategy.** The simplest (used here): pre-bake the platform/ground art as OBJ
  CHR in **upper VRAM (word `$4000+`, `OBSEL=$62`)**, clear of the Mode-7 `$0000-$3FFF`
  region — a one-and-done upload that survives the swap. (Alternative: a blank-time
  BG→OBJ CHR DMA.)
- **Budget.** Capture only the **platform cells**, not a full 16×14 grid (224 > the
  128-OBJ limit). HUD at the top and ground at the bottom are on different scanlines, so
  the 32-per-scanline cap is comfortable.

The alignment is the load-bearing claim, so it's tested by a **before/after pixel diff**
at the freeze (the captured OBJ ground must land on the same pixels the BG tiles
occupied) — verified camera- and sub-tile-correct (Δ≤1px even at a non-tile-aligned
camera), with a `-DNO_CAPTURE` control that makes the ground vanish to black.

---

## The meteor-event choreography (the worked example)

A small timed state machine (`g_state`: PLAY→FREEZE→CAPTURE→SCENE→RESTORE→PLAY):

1. **Trigger** — player walks right to an open flat area.
2. **Freeze** — physics + scroll halt, input gated (player pixels don't move under held input).
3. **Capture** — BG→OBJ (above); BG blacks.
4. **Swap** — `sf_swap_to_mode7` brings in the Mode-7 meteor plane; captured OBJ on top.
5. **Spin-in-place + arc + grow** — the rotation pivot `M7X/M7Y` is **pinned at the
   meteor's map centre** (`sf_boss_center` once), so `sf_boss_matrix scale, angle`
   spins the meteor about *its own centre* instead of orbiting it. To move it, only
   the **BG scroll** is swept each frame (`HOFS = MET_CX − Sx`, `VOFS = MET_CY − Sy`),
   carrying the on-screen centre along an arc — off-screen top-left → down → right →
   off-screen bottom-right — while the scale ramps it up as it nears. `M7SEL=$80`
   (outside-field-transparent) keeps the off-field region black so the exited
   meteor never wraps back into the sky.

   > **Spin pivot ≠ scroll.** This is the load-bearing fix: rotating about a pivot
   > offset from the meteor centre makes it *orbit* (the meteor swings back up the
   > sky). Pin the pivot to the meteor centre for in-place spin, and translate via
   > the scroll, decoupled from rotation.
6. **Red glow, synced to the descent** — a COLDATA gradient whose bottom-red
   intensity tracks the meteor's screen-Y (`glow = (Sy − Y0) >> n`): it rises as the
   meteor falls into the lower screen, peaks at impact, then recedes after the
   flight. `sf_colormath_on #1, #$21` (backdrop+BG1, **OBJ bit 4 excluded** so the
   sprites aren't tinted).
7. **Swap back** — `sf_swap_to_mode1_begin/_end` rebuilds the level; capture OBJ dropped.
8. **Release** — unfreeze; the d-pad moves the player again (one-shot via `g_event_done`).

> **Gradient ordering gotcha:** `sf_gradient_rgb` refuses to build while `M7_PV_ACTIVE=1`.
> Arm the gradient **before** the Mode-7 enable, then drive it per-frame with
> `sf_gradient_update`.

---

## Architecture: whole-screen Mode 7 + sprite HUD (no mode-band)

During the event the **entire screen is Mode 7** (the meteor is the Mode-7 BG, black is
its backdrop); the player, platforms, and HUD are all **OBJ sprites** composited on top.
There is **no per-scanline `$2105` mode-band** and no live Mode-1 layer retained. Because
OBJ is mode-independent, this keeps the whole event on proven bricks — sprite-over-Mode-7
(the `boss` rail), uniform affine scale (`sf_boss_matrix`), COLDATA gradient (`sf_fx`),
forced-blank swap (this primitive) — plus the one net-new capture.

## What this is NOT

A **true per-scanline mode-split** — a Mode-7 element coexisting in the *same frame* with
a *live* Mode-1 scene (e.g. a retained Mode-1 HUD band) — is a separate, harder,
VRAM-bounded shape (Mode 7 owns the lower 32 KB; a full Mode-1 layer can't share the
frame). It is **out of scope** here; the sprite HUD replaces the band. Revisit only if a
future item specifically wants live mode coexistence.

---

## Done-condition (what "it works" means)

`tests/test_meteor_event.py` (17, all reading rendered/HW output) asserts the full DoD,
each with a `-D` non-vacuity control that fails the real assertion:

- BGMODE flips Mode1→Mode7→Mode1 across the event (framebuffer + the live mode register).
- Captured platform sprites are pixel-aligned at the freeze (`-DNO_CAPTURE`).
- Freeze gates input; control is released after (`-DNO_FREEZE` / `-DNO_RELEASE`).
- Meteor grows (rendered bbox t0 < t1) then exits the bottom (`-DNO_SCALE`).
- Red gradient occupies the lower band behind un-tinted sprites, then recedes (`-DNO_GRADIENT`).

**Note:** the Mode-7 scene updates at ~½ NMI rate (per-frame gradient + matrix rebuild) —
fine for a cutscene with gameplay frozen; if you reuse this under live gameplay, only
rebuild the gradient when its colour changes.

## Placeholder art

`templates/meteor_event/assets/make_assets.py` generates everything deterministically
(no external PNGs): the meteor plane, the platform/ground OBJ CHR, the player. CC0-style —
swap in your own and rebuild.
