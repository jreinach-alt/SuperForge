# mode_showcase — PPU effect showcase instrument

## What it is

An interactive SNES PPU effect playground. Pick a background mode from a menu,
then tune that mode's effect stack LIVE with on-screen knobs — no recompile — and
save the settings you like to SRAM. It is a generic HARNESS: each BG mode is a
"page" that registers its own knobs, presets, and content. The shipping build
wires Mode 0 (PLANES) and Mode 1 (GLASS) with real knobs and presets; the other
menu slots are stub pages. This is NOT an autonomous reel — everything is driven
by the pad.

| Button | Action |
|---|---|
| **Menu: D-pad** | move the mode cursor (two columns, modes 0-7) |
| **Menu: A** | select the highlighted mode -> instructions -> demo |
| **Demo: Select** | cycle the active knob slot (6 slots) |
| **Demo: D-pad / A·B / X·Y / L·R** | adjust the active slot's 5 knobs |
| **Demo: Start** | return to the menu |
| **Demo: Start+Select** | freeze into the full-parameter sheet (page with D-pad) |
| **Sheet: A / B** | save / load the parameter set to/from SRAM |

## What it teaches

- **A table-driven parameter model** — one generic router owns 6 slots x 5 knobs
  (`SHOW_N_SLOTS` x `SHOW_N_PARAMS`) in WRAM ($7E:E200). Each mode page supplies a
  30-entry descriptor table (min/max/step/default) plus an apply hook; the router,
  HUD, param-sheet, and record screen are all generic over the ACTIVE mode's
  resolved tables.
- **A scene state machine** — `sf_scene.inc` drives MENU -> INSTRUCTIONS -> DEMO
  (`SC_MENU` / `SC_INSTR` / `SC_DEMO`); `sf_scene_dispatch` calls the active scene's
  per-frame tick, and Start/Select are interpreted per-scene.
- **A self-registering dispatch layer** — `show_register_mode` lets each page add
  itself to the per-mode vtables with unique symbols, so a new mode never edits the
  vtables, the Makefile, or `main.asm`.
- **An OBJ-font HUD + a live limit meter** — `sf_obj_text` renders the knob values
  and the slot bar as sprites (OBJ palette 7); a green/yellow/red meter watches the
  heartbeat, HDMA channels, and OAM-per-line budget, and a $C000 arena mutex
  auto-disables a second heavy effect.

## Three things to tweak

- **`str_tagline`** (`main.asm`, the menu strings; default "TUNE LIVE INSTRUMENT")
  — the subtitle under the title on the menu screen. Change the bytes to re-label
  the menu; the mode labels are the `str_m0`..`str_m7` strings just below it.
- **The boot mode** (`main.asm`, in RESET: the `lda #0` -> `sta f:SHOW_CUR_MODE`
  seed) — which mode the menu cursor starts on. Set it to `#1` to open on GLASS
  instead of PLANES.
- **A page's knob ranges** (`assets/showcase_mode1.inc` for GLASS,
  `assets/showcase_mode0.inc` for PLANES) — each page's 30-entry descriptor table
  is the min/max/step/default of that mode's live knobs. Widen a range there and
  the on-screen knob sweeps further.

## How it's verified

- **Build:** `make mode_showcase` (the `LDCFG: lorom_show.cfg` sentinel selects a
  256KB LoROM + SRAM image with room for every mode page).
- **Test:** `python -m pytest tests/test_mode_showcase.py -q` — reads the rendered
  output: the menu renders the mode list and a movable caret; A advances to the
  instructions and then the live demo; the HUD draws the active slot's knob values;
  and adjusting a knob changes the rendered PPU state.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/mode_showcase.sfc', run_seconds=1.5); r.take_screenshot('/tmp/mode_showcase.png'); r.stop()"`
