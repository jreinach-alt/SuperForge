# 93 — PAL: what the kit does at 50 Hz, measured

> Status: RESEARCH — a measurement pass, not a change. Nothing in `engine/`,
> `game/`, `tests/` or the gates was touched. Every defect named here is
> recorded and left standing.

## 0. The verdict, before the evidence

All 37 rails **boot, run and render correctly under PAL.** Nothing crashes,
nothing hangs, nothing corrupts, no per-scanline table under-covers the frame
and no VBlank transfer overruns. The tightest budgets in the kit get *looser*,
not tighter: a PAL frame carries **19.1% more master cycles** and its VBlank
window swallows **at least 37.6% more DMA bytes** than the pinned NTSC figure.

Everything that differs at all traces to one of three things, and none of them
is breakage:

1. **The clock.** PAL is 50.007 fps against NTSC's 60.099. Every rail runs at
   **83.2% speed**; a game-second takes 20.0% longer. Nothing compensates,
   because nothing in the kit reads the region.
2. **A constant boot-phase offset of at most one frame.** 14 of 37 rails start
   their frame loop one PPU frame earlier under PAL, because the boot's fixed
   master-cycle cost spans one fewer of PAL's longer frames. Measured at PPU
   frame 240 and again at 1800: the offset is **constant. It never grows.**
3. **The APU keeps real time while the game slows down.** The S-SMP has its
   own crystal, so music plays at its NTSC tempo while the game runs at 5/6
   speed. Nothing in the kit syncs gameplay to music, so today this is
   inaudible drift rather than a bug — but it is the one class that a future
   feature could turn into one.

The honest reading of the jam's "works on NTSC and PAL" is therefore:
**the kit already satisfies the reading the jam almost certainly means**, and
the cheapest correct action is a header fix plus a stated
limitation — **not** a speed-compensation engine. §10 argues that from the
measurements; §11 says what to do first.

## 1. Why this exists

The SNES DEV Game Jam 2026 (submissions 2026-07-31 to 2026-10-31) lists eight
technical restrictions. Most are settled by reading the image: LoROM ✓ (map
mode `$30` on all 41 built images), ≤512 KB ✓ (every rail is exactly
524,288 B — *at* the cap), no special chips ✓; the SRAM rule is a known
composition question (`platformer`, `room` and `rpg` compose `save`, and their
headers say so: cart type `$02`, SRAM size `$01` = 2 KB).

**"Game works on NTSC and PAL" is the one that cannot be read off the file.**
It is a question about the machine, and CLAUDE.md rule 1 says a question about
the machine is measured on the emulator, never reasoned out of the ASM. This
document is that measurement.

> **ADDENDUM 2026-08-23 — the page itself was read, and all eight are now
> recorded.** The jam is hosted at
> <https://itch.io/jam/snes-dev-game-jam-2026>; its "Technical restrictions"
> list holds exactly eight items, quoted: (1) "Game is done by yourself (no
> hacks, ripped musics or graphics). The use of free assets is allowed";
> (2) "Team projects are allowed, please state every member that contributed
> and how they contributed"; (3) "Game is Lorom"; (4) "Game has max. size of
> 512KB"; (5) "Game uses no special chips (SA-1, Super FX etc.)"; (6) "Game
> uses no SRAM"; (7) "Game works on real hardware"; (8) "Game works on NTSC
> and PAL". The two this document originally left unrecorded are (1) and
> (2) — authorship rules, neither file-checkable nor machine-checkable, which
> is why a measurement pass had nothing to hold them against. The exact
> wording of (6) also settles the phrasing question this section left open:
> the rule is flat "no SRAM", not a size or battery constraint — `JAM.md`
> row 4 carries the consequence. Same page: only playable games are valid
> entries, and judging is on Graphics, Music/Sound, Technical Implementation,
> Controls, and Gameplay/Creativity.

## 2. Three prior claims, checked before anything was built on them

| claim | verdict | evidence |
|---|---|---|
| The instrument exists and has never been used: `vendor/mesen_runner.py` supports `SF_REGION=ntsc`/`pal`, applied once per process from `_make_base_snes_config`; nothing else in the tree names it | **HELD** | `_apply_region` at `vendor/mesen_runner.py:1367`, `_REGION_PAL = 2` at :1364, called from `_make_base_snes_config` :1462. `grep -rn SF_REGION .` returns **7 hits, all in that one file**. No test, no Makefile target, no doc. The other `Region` hits in `allocator/no_literals.py`, `vendor/machine.py` and `docs/09` are *memory* regions, not console region |
| Every ROM header declares destination `$01` (North America / NTSC) at `$7FD9` | **HELD, and it is a single hardcoded byte** | `vendor/rom/header.inc:41` is `.byte $01`; I read `$7FD9` out of all **41 built images** (37 rails + toy + 3 probes) and every one is `$01`. Unlike the cart-type and SRAM-size bytes it has no `.ifndef` override, so a game cannot change it |
| No region handling in the engine: no PAL path, no 50 Hz logic; `$213F` is read only to reset the OPHCT/OPVCT toggles | **HELD** | The only `$213F` reads are `sit_cam.asm:409,430`, `shg_cam.asm:475,496`, `m7f_cam.asm:230` and two vendored probes — each immediately followed by `$213C`/`$213D` counter reads, never the bit-4 region test (`$213F` bit 4 is the PAL flag — `SnesPpu.cpp:1853`, `GetRegion() == Pal ? 0x10 : 0`; bit 7 is the odd-frame flag). `grep -i` for PAL/NTSC/50 Hz across `engine/` and `game/` returns only palette identifiers (`@pal:` loop labels) and NTSC-labelled cycle comments. **Nothing writes `$2133` (SETINI) anywhere in the tree**, so interlace and overscan are whatever the PPU powers on with (§13) |

All three held. Two are now measured rather than grepped.

## 3. The instrument

### 3.1 The knob, and proving it was live

`SF_REGION` is read once per process and layered onto the shared SNES config;
unset (or `auto`) leaves Mesen on `ConsoleRegion::Auto`, which asks the
cartridge. `BaseCartridge::GetRegion` (`/tmp/Mesen2/Core/SNES/BaseCartridge.cpp:779`)
maps destination codes `$02..$0C`, `$11`, `$12` to PAL and everything else to
NTSC — so with the knob unset, **every rail in this tree runs NTSC**, and that
is the region the whole suite has always measured.

A region knob that silently did nothing would make every number below
meaningless, so every probe reports the machine's own master-clock rate per
frame before it reports anything else:

```
SF_REGION=ntsc   357,366 mc/frame        SF_REGION=pal   425,566 mc/frame
SF_REGION unset  357,366 mc/frame  (= NTSC, via the $01 destination code)
```

357,368 = 1364 × 262 and 425,568 = 1364 × 312 are the nominal figures; the
measured pair is 2 mc lower because scanline 240 of every other frame is 1360
dots rather than 1364 (`SnesPpu.cpp:397`: *"In non-interlace mode scanline 240
of every other frame … is only 1360 cycles"*), which averages to −2. `SnesConsole.cpp:209` confirms
Mesen also models the two different crystals — 21,281,370 Hz PAL against
21,477,270 Hz NTSC — so the frame *rates* are 50.0072 and 60.0988 Hz.

### 3.2 One region per process, and how that was handled

`_apply_region` runs at global init, so a PAL run and an NTSC run cannot share
a process — a pytest process can hold one region and no more. The harness
therefore **re-executes itself**: the parent runs one child per region with
`SF_REGION` in the child's environment, each child prints one JSON line, and
the parent diffs the two. Nothing needs the region to change mid-process, and
no fixture has to be region-aware.

That harness is committed as **`tools/pal_probe.py`** — the one artifact of
this sprint besides the document. It is report-only: it asserts nothing, is
wired into no gate, and changes no existing behaviour.

```
python3 tools/pal_probe.py build/racer.sfc --map build/rc/symbol_map.json \
    --anchor game --frames 120,360 --outdir build/pal_shots
```

### 3.3 The two anchors — the subtlest trap in the sprint

"The same frame number" means different things in the two regions, and picking
the wrong one silently manufactures or hides differences.

* **`--anchor ppu`** indexes the input script *and* every capture on the
  absolute PPU frame. This is the hardware timeline: *at the same position in
  the frame sequence, is the machine in the same state?*
* **`--anchor game`** indexes both on the game's own frame counter
  (`ES_SM_FRAME`, present in every rail). This removes the boot phase of §6.3
  and asks the narrower question: *does game frame N render the same picture?*

Neither subsumes the other, and the difference is not academic: `boss` is
byte-identical under the PPU anchor and one animation step apart under the game
anchor, because its animation is clocked from the NMI rather than from the main
loop. **§5 reports both columns for every rail.** A first version of the game-anchored probe
indexed the *captures* by the game frame but the *input script* by the advance
count — which fed the two regions different input at different game frames and
produced differences that were the harness's, not the kit's. That version was
discarded and both sweeps re-run; it is recorded here because it is the exact
shape of the trap.

Determinism: `Machine` seeds the power-on RNG (`SetPowerOnSeed`), so the
randomised power-on RAM is bit-identical across the two regions and a
difference cannot be RNG. Every advance is lockstep-verified against the PPU's
own frame counter and parks at scanline 224 — which is past the 224-line
active display in **both** regions, since the PPU renders the same 224 lines
either way (§4).

## 4. What PAL actually is, measured

| | NTSC | PAL | how |
|---|---|---|---|
| scanlines per frame | **0..262** | **0..312** | sampled the PPU's own scanline counter across a free-run; `min 0 max 262 / distinct 263` vs `max 312 / distinct 313` (the extra line is the alternate-frame parity line) |
| master cycles per frame | **357,366** | **425,566** | `GetConsoleState` MasterClock delta over 60 lockstep frames |
| master clock | 21,477,270 Hz | 21,281,370 Hz | `SnesConsole.cpp:209` |
| frame rate | 60.0988 Hz | **50.0072 Hz** | the two rows above |
| **active display** | **224 lines** | **224 lines** | `SnesPpu.cpp:558`: `_vblankStartScanline = _state.OverscanMode ? 240 : 225` — **not region-conditional**. Nothing in the tree writes `$2133`, so overscan is off in both |
| VBlank lines | 37–38 | **87–88** | 262 − 225 vs 312 − 225 |
| usable VBlank GP-DMA | **5,952 B** | **≥ 8,192 B** | the `probe_vblank` sweep, run under each region. NTSC reproduces the pinned `substrate.toml` value exactly; PAL delivered the probe's *entire* 8 KB target, so its ceiling is above the probe's range (theoretical: 88 × 1364 / 8 ≈ 15,004 B) |
| Mesen capture geometry | 256 × 239 | 256 × 239 | all 370 captured PNGs, both regions, one size |

**The intuition this corrects.** The obvious worry going in was "things sized
to NTSC's scanline count under-cover PAL's taller frame". PAL's frame is
indeed 50 lines taller — **but every one of those extra lines is VBlank.** The
*picture* is 224 lines in both regions unless a game sets the overscan bit, and
nothing here does. So `railshooter`'s 180-line pose blob, `mode7_persp`'s
`PERSP_LINES = 224 - HUD_LINES`, `rgb_gradient`'s `GRAD_LINES = 224`,
`sh2_cam`'s `SH2_LINES = 224`, `met_glow`'s `.assert BANDS * LINES = 224` and
the seam IRQs armed at content line 112 all cover exactly as much of the PAL
picture as they cover of the NTSC one. **No per-scanline table under-covers.**
That is confirmed the hard way below: every raster rail renders pixel-identical.

The taller frame runs entirely the *safe* direction — 19.1% more CPU cycles per
frame and 2.35× the VBlank lines. If a rail fits NTSC, it fits PAL.

What the taller frame *does* cost is on the television, not in the machine: 224
picture lines inside a 288-line PAL field means horizontal borders top and
bottom, where an NTSC set shows the same 224 lines nearly full-height. That is
a real difference and I could not measure it here (§12) — Mesen hands back the
same 239-row buffer for both regions.

## 5. Per-rail results

Both anchors, all 37 rails, same ROM, same input script, same power-on seed.
Captures at frames 60 / 120 / 240 / 420 / 600. A cell is what differed between
the two regions at *any* capture; **`identical` means every byte of VRAM, OAM,
CGRAM, WRAM, SPC RAM and the DSP registers, and every pixel of the PNG.**
`boot Δ` is the boot-phase offset in frames (§6.3); `drift` re-reads that
offset at PPU frame 240 after the run — `none` means it is still the same
number, i.e. it did not accumulate.

| rail | boot Δ | drift | PPU-anchored | game-anchored |
|---|---|---|---|---|
| `boss` | -1 | none | WRAM | OAM, WRAM, picture (13349 px max) |
| `boss_saucer` | -1 | none | WRAM, SPC, DSP, picture (942 px max) | SPC, DSP |
| `brawler` | 0 | none | OAM, WRAM, picture (104 px max) | OAM, WRAM, picture (104 px max) |
| `breaker` | -1 | none | WRAM, SPC, DSP, picture (50624 px max) | SPC, DSP |
| `camera_follow` | 0 | none | **identical** | **identical** |
| `hud_game` | 0 | none | **identical** | **identical** |
| `jumper` | 0 | none | **identical** | **identical** |
| `m7_dungeon` | -1 | none | WRAM | OAM, WRAM, picture (74 px max) |
| `m7_oshoot` | -1 | none | WRAM | OAM, WRAM, picture (794 px max) |
| `maze` | 0 | none | **identical** | **identical** |
| `meteor_event` | 0 | none | **identical** | **identical** |
| `microzero` | 0 | none | **identical** | **identical** |
| `mode7_chamber` | 0 | none | **identical** | **identical** |
| `mode7_explore` | 0 | none | **identical** | **identical** |
| `mode7_flight` | -1 | none | WRAM | OAM, WRAM, picture (163 px max) |
| `patrol` | -1 | none | WRAM | OAM, WRAM, picture (32 px max) |
| `platformer` | -1 | none | VRAM, OAM, WRAM, SPC, DSP, picture (57344 px max) | WRAM, SPC, DSP |
| `platformer_stream` | 0 | none | **identical** | **identical** |
| `racer` | -1 | none | WRAM, SPC, DSP | SPC, DSP |
| `railshooter` | 0 | none | **identical** | **identical** |
| `room` | -1 | none | OAM, WRAM, SPC, DSP, picture (26 px max) | OAM, WRAM, SPC, DSP, picture (26 px max) |
| `rpg` | -1 | none | WRAM, SPC, DSP | SPC, DSP |
| `scroll_run` | 0 | none | **identical** | **identical** |
| `scroller` | 0 | none | **identical** | **identical** |
| `seam_irq_trial` | 0 | none | WRAM | WRAM |
| `shmup` | -1 | none | WRAM, SPC, DSP | OAM, WRAM, SPC, DSP, picture (51832 px max) |
| `split_h_2p_demo` | 0 | none | WRAM | WRAM |
| `split_h_demo` | 0 | none | **identical** | **identical** |
| `split_h_irq_grad_demo` | -1 | none | WRAM | WRAM, picture (2048 px max) |
| `split_h_matrix_demo` | 0 | none | **identical** | **identical** |
| `split_h_persp3_demo` | 0 | none | **identical** | **identical** |
| `split_h_persp_demo` | 0 | none | **identical** | **identical** |
| `split_v_demo` | 0 | none | **identical** | **identical** |
| `split_v_fight` | 0 | none | WRAM, SPC, DSP | OAM, WRAM, SPC, DSP, picture (228 px max) |
| `split_v_seamtrial` | 0 | none | **identical** | **identical** |
| `sprite_game` | 0 | none | **identical** | **identical** |
| `stomper` | -1 | none | WRAM | OAM, WRAM, picture (32 px max) |

**How to read it.** `drift` is `none` on all 37 rails: the offset at frame 1800
is the offset at frame 20. The `WRAM`-only cells are per-frame counters one
step apart (§6.4 tabulates the actual bytes). The two anchor columns disagree
on which rails differ *because the boot offset sits between the NMI's frame
count and the main loop's* — §6.4. No cell anywhere is corruption; every
picture captured in this sprint is a correct render of its rail.

## 6. The damage taxonomy

Sorted by what the difference *is*, with the rails it applies to.

### 6.1 T0 — no difference at all

**19 of 37 rails are byte-identical and pixel-identical under BOTH anchors**,
with the region knob demonstrably live: `camera_follow`, `hud_game`, `jumper`,
`maze`, `meteor_event`, `microzero`, `mode7_chamber`, `mode7_explore`,
`platformer_stream`, `railshooter`, `scroll_run`, `scroller`, `split_h_demo`,
`split_h_matrix_demo`, `split_h_persp3_demo`, `split_h_persp_demo`,
`split_v_demo`, `split_v_seamtrial`, `sprite_game`.

That list covers the raster machinery that was the obvious suspect: the four
`split_h_*` HDMA/perspective demos, both vertical splits, the Mode 7
world-streamer, the level-streamer, and `railshooter` with its 180-line pose
blob. The two scanline-**IRQ** rails are not in it, but only because of WRAM
counters — `seam_irq_trial` renders pixel-identical under both anchors, and
`split_h_irq_grad_demo` under the PPU anchor (§6.7). **Per-scanline HDMA, Mode
7 matrices, streaming, split-screen and the seam IRQ behave identically at
50 Hz, down to the pixel.**

### 6.2 T1 — the clock (universal, and the only difference a player sees)

Every rail runs at **50.007/60.099 = 83.2% speed**. A game-second takes 20.0%
longer; a 10-second timer becomes 12 seconds; a walk cycle plays 1/6 slower.
Nothing compensates and nothing tries to. This is the classic un-ported PAL
release, and it is what the overwhelming majority of homebrew ships.

### 6.3 T2 — the boot-phase offset: constant, ≤1 frame, never grows

**Mechanism, measured directly.** The boot's init work costs a fixed number of
master cycles; a PAL frame is 19.1% longer, so the same work spans one fewer
frame boundary. The PPU frame at which each rail's frame counter first reads 1:

| rail | NTSC | PAL |
|---|---|---|
| `microzero`, `camera_follow`, `maze`, `split_v_fight`, … (23 rails) | 1–5 | same |
| `boss`, `m7_dungeon`, `m7_oshoot`, `patrol`, `stomper`, `split_h_irq_grad_demo` | 2 | **1** |
| `mode7_flight` | 3 | **2** |
| `breaker`, `platformer`, `room`, `shmup` | 5 | **4** |
| `boss_saucer`, `racer`, `rpg` | 6 | **5** |

14 of 37 rails shift by exactly one frame; 23 do not shift at all. **No rail
shifts by more than one.**

**It does not accumulate.** The same offset re-read at PPU frame 240 and again
at 1800 is the same number, every rail, every time. The game's own counter
reads `[9, 29, 59, 119, 239, 479, 899]` at PPU frames `[10, 30, 60, 120, 240,
480, 900]` under NTSC and `[10, 30, 60, 120, 240, 480, 900]` under PAL for
`boss` — a constant +1, out to 900 frames. **PAL drops no frames.**

The cleanest picture of it: `boss_saucer` driven with no input at all, six
consecutive screenshots from PPU frame 300 —

```
ntsc  af5c37bb  af5c37bb  3a9c09bd  3a9c09bd  3a9c09bd  3a9c09bd
pal   af5c37bb  3a9c09bd  3a9c09bd  3a9c09bd  3a9c09bd  3a9c09bd
```

The same two frames of the same animation, one frame apart. Not corruption —
phase.

### 6.4 T2′ — which anchor exposes it depends on which counter the rail uses

This is the finding that makes the two columns of §5 worth reading side by
side. `boss`, `m7_dungeon`, `m7_oshoot`, `mode7_flight`, `patrol` and `stomper`
are **pixel-identical under the PPU anchor and one step apart under the game
anchor**; `boss_saucer`, `breaker` and `platformer` are the exact reverse. The
reason is that a rail's animation may be clocked from the NMI (a PPU-frame
counter) or from the main loop (`ES_SM_FRAME`), and the boot offset sits
*between* those two counters. Neither anchor is "the true one".

In every case the difference is **one step of one counter**. At the same game
frame, with the same input:

| rail | differing WRAM bytes | what they are |
|---|---|---|
| `split_v_fight` | **1** | `US_ATK+2`: `$00` vs `$01` |
| `stomper` | 9 | `US_BLINK` `F1`/`F0`, `US_BOXX`/`US_E1X`/`US_E2X`/… each ±1 |
| `patrol` | 9 | `US_FRAMES` `F1`/`F0`, four sprite X positions ±1 |
| `boss` | 11 | `US_FRAME` `F1`/`F0`, `US_B_HEADING` ±1, `US_SPAWN_TIMER` ±1, the Mode 7 matrix one rotation step |
| `shmup` | 11 | `US_ATICK`, `US_BLINK`, `US_BY`, `US_SPAWN_T`, the scroll — each ±1 |
| `m7_dungeon` | 12 | the Mode 7 pose, the hot camera and the enemy position, each ±1 |
| `boss_saucer` | 8 | heading ±1, timer ∓1, both star layers by exactly one scroll step (+16 / +32), the Mode 7 matrix one rotation step |

Every value is one step of a per-frame integrator. Nothing is a wrong value; it
is a value read one frame early or late.

The picture differences follow the same shape. `breaker`, `platformer` and
`shmup` show a whole-screen difference at frame 60 with a mean-brightness ratio
of 1.08 / 1.38 / 0.90 and a maximum channel delta of 17 / 33 — **a fade one
step further along**, not a wrong picture. `split_h_irq_grad_demo` differs on
3–8 scattered *whole rows* out of 224 — the per-scanline gradient's animation
phase moving a band boundary by a row. `room` differs on 26 pixels, one 8×8
sprite. `boss` differs across the whole Mode 7 plane because the plane is one
rotation step round; both renders are correct (screenshots taken).

Driven with **no input at all**, `brawler`, `room` and `platformer` are
pixel-identical between regions across six consecutive frames, and
`boss_saucer` shows exactly the one-frame shift above.

### 6.5 T3 — audio: the APU keeps real time, the game does not

Every rail that composes `audio` shows SPC RAM and DSP registers differing at
the same frame — `racer`, `rpg`, `shmup`, `split_v_fight`, `breaker`,
`boss_saucer`, `platformer`, `room`. That is **correct**, and it is the one
difference that is not a phase artifact:

* The S-SMP runs on its own crystal, independent of the console's region.
  Mesen models this faithfully — `Spc.cpp:126`,
  `_clockRatio = (spcSampleRate * 64) / GetMasterClockRate()`, so SPC cycles
  per *master* cycle rise exactly as the master clock falls and SPC cycles per
  *second* stay at 2,048,000.
* Tempo therefore comes from the S-DSP `TIMER_0` register — TAD's own
  `SET_SONG_TIMER` command, `vendor/tad/tad-audio.inc:189` — not from the video
  clock. **Music plays at its NTSC tempo on a PAL machine while the game runs
  at 83.2% speed.**
* `Tad_Process` is called once per frame from the main loop, so the driver is
  serviced at 50 Hz instead of 60. It is a queue-servicing state machine with
  no frame-rate assumption, and no rail blocks on the loader (`Tad_LoadSong` is
  called and never waited on), so nothing stalls. The practical effect is that
  SFX trigger granularity coarsens from 16.6 ms to 20 ms.
* Nothing reads back: every game-side use of the TAD API in this tree is
  `Tad_Init`, `Tad_LoadSong`, `Tad_Process` or `Tad_QueueSoundEffect`. **No
  rail branches on driver state**, so the APU's region-dependent progress
  cannot leak into game logic.

Today this is inaudible drift. It is worth writing down because it is the class
a future rhythm or cutscene-sync feature would turn into a real bug — and the
fix then is not "detect the region", it is "drive the sync from the audio side."

### 6.6 T4 — input timing: the same instant is a different game frame

Under the **PPU anchor** — the same button pressed at the same position on the
hardware timeline, which is what a human pressing at a wall-clock moment
actually does — `platformer` diverges: at frame 600 the NTSC run reads
`COINS 2` and the PAL run `COINS 1`. One frame of boot phase put the player one
frame of physics from a pickup and the deterministic sim amplified it. **Both
frames are correct, complete, playable renders.**

Under the **game anchor** — the same button at the same *game* frame —
`platformer`'s VRAM, OAM, CGRAM and picture are **identical at every capture**,
and by frame 600 even WRAM matches. So this is not the simulation diverging
between regions; it is the ≤1-frame phase of T2 arriving at the input. It
matters to a *test* that compares pictures across regions, which is why §8 and
tier 2 exist, and not to a player.

### 6.7 T5 — sub-scanline: the seam IRQ lands a dot or three later

The two IRQ rails record the raster position at which their seam IRQ enters and
fires. Same PPU frame, no input:

| counter | NTSC | PAL |
|---|---|---|
| `seam_irq_trial` `SIT_CNT_ENTH` (entry OPHCT) | 47 | 48 |
| `seam_irq_trial` `SIT_CNT_FIREH` (post-fire OPHCT) | 10 | 11 |
| `split_h_irq_grad_demo` `SHG_CNT_FIREH` | 16 | 13 |

One to three **dots** — a fraction of a scanline. Both handlers gate the MDMAEN
fire on the HBlank flag (`bit a:$4212 / bvc`), which absorbs it completely:
`seam_irq_trial` renders **pixel-identical under both anchors**. This is the
finest-grained difference the sprint found and it is inside the margin the
design already builds for.

### 6.8 What is NOT in the taxonomy

No rail crashed, hung, dropped a frame, corrupted VRAM/OAM/CGRAM, overran
VBlank, mis-timed an IRQ into the picture, or lost its seam. Those were the
hypotheses worth falsifying and all of them were falsified.

Two residues, named so they are not mistaken for findings later:

* `split_h_2p_demo` differs in two WRAM bytes at `$01E8/$01E9` — inside the
  reserved stack page (`SYS_STACK_TOP = $01FF`), below the live stack pointer.
  Dead residue; no symbol owns it; I did not chase it further.
* `room` prints `[CPU] Uninitialized memory read: $000057/$000058` from the
  core on **both** regions identically. Pre-existing, not region-related, out
  of this sprint's scope — recorded so the next reader does not re-find it as a
  PAL bug.

## 7. The pinned budgets under PAL

`allocator/substrate.toml`'s frame table is explicitly `[frame.ntsc]`, and
`allocator/pin_budgets.py` and `allocator/schemas.py` both read
`d["frame"]["ntsc"]` by name. There is no `[frame.pal]`. So: **what do the pins
mean at 50 Hz?**

| pin | NTSC (pinned) | PAL (measured / derived) | direction |
|---|---|---|---|
| `mc_per_frame` | 357,368 | **425,568** | +19.1% cycles per frame |
| `vblank_lines` | 38 | **88** | 2.3× |
| `vblank_usable_bytes` | 5,952 (measured) | **≥ 8,192** (measured; probe saturated) | ≥ +37.6% |
| `cpu_worst_frame_mc` | 305,348 = **85.4%** of a frame | same 305,348 mc = **71.8%** of a frame | 13.6 points of headroom returned |

The work itself costs the same. Re-running the `probe_cpu` latch-ring
measurement under each region on the same drive:

```
ntsc  work max 215,444 mc  NMI max 16,800 mc  worst total 232,244 = 65.0% of a frame
pal   work max 209,660 mc  NMI max 16,800 mc  worst total 226,460 = 53.2% of a frame
loop iterations: 240 in 240 frames, both regions
```

The NMI handler's worst frame agrees **to the master cycle** — 16,800 in both —
and the game-loop work differs by 2.7% — trajectory phase, not region cost. A
65% frame becomes a 53% frame purely because the frame got bigger. **The pins
are conservative for PAL in every direction; nothing needs re-pinning to make
PAL safe.** (This run approaches its cruise speed on one rung rather than
replaying the pinned ladder, so 232,244 is not the pinned worst case of
305,348 — the comparison is NTSC-against-PAL on the identical script, which is
the number this section needs.)

## 8. Our own tooling's NTSC assumptions

Nothing here is a ROM defect. It is what would have to move if PAL ever became
something the suite *asserts* rather than something a probe visits.

| site | assumption | what happens under PAL |
|---|---|---|
| `allocator/substrate.toml` `[frame.ntsc]` + `pin_budgets.py:57` + `schemas.py:142` | the frame table is NTSC by name, and there is no PAL sibling | pins read as NTSC; nothing breaks, nothing describes PAL |
| `tests/test_measure_vblank.py:120` | `assert 4000 <= usable <= 6479` — the 38-line NTSC ceiling | **would fail**: PAL delivers ≥ 8,192 |
| `tests/test_measure_cpu.py:61,93` | `FRAME_MC = 357368`; `if max(sv, ev) >= 262 … continue` treats a latch as a torn slot | the guard discards **every** legitimate PAL latch above line 261; the modulo normalisation is wrong by 68,200 mc |
| `tests/test_mode7_flight.py:168`, `test_scene_mgr_shadow.py:46`, `test_pfs_stream.py:122`, `test_platformer.py:42`, `test_room_window.py:630`, `test_microzero_stream.py:30` | `FRAME_MC = 357368` for percent-of-frame and modulo arithmetic | percentages overstate by 19.1%; a delta spanning a frame wraps wrong |
| `tests/frame_geometry.py` | "256×239, picture starts at PNG row 7" as *a fact about the machine* | **holds under PAL** — measured across all 370 captures, both regions, one geometry. The file's claim is now true of both regions, not just the one it was written against |
| `engine/features/irq/irq.asm:48` | `In: A16 = internal scanline (0..261)` | inert — both call sites arm line 112 — but the documented contract is NTSC-shaped and would mislead someone arming a VBlank-region line |
| `tests/test_decl_impl_channels.py:353` | an mc-per-frame bound stated as NTSC in the comment | the bound is deliberately loose; it survives |

## 9. Where the kit sits on the compliance spectrum

The jam says "works on NTSC and PAL" and does not say which of these it means.
Measured, the kit sits like this.

**Rung 1 — boots and is playable on both, at different speeds.**
**ALREADY TRUE, for all 37 rails, with evidence.** Every rail boots, holds its
frame cadence at 50 Hz, renders correctly, takes input and is playable. The
only player-visible difference is that everything is 20% slower. This is the
un-compensated PAL release that most homebrew ships, and that many commercial
PAL conversions of the era shipped too.

**Rung 2 — the picture is correct on both.** **ALREADY TRUE**, and more
strongly than expected: 19 rails are pixel-identical and the rest differ only
by ≤1 frame of animation phase. The 224-line active display does not change
with region, so no per-scanline table under-covers and no raster effect
mis-lands. The residue is cosmetic: a PAL television shows those 224 lines with
borders top and bottom, which a PAL-aware release would fill by enabling
overscan (239 lines) and extending the per-scanline tables — a real piece of
work (§10 tier 3) for an entirely cosmetic gain.

**Rung 3 — runs at the same speed on both.** **NOT TRUE, and not close.**
It needs region detection (`$213F` bit 4), plus a compensation strategy, plus
re-tuning every rail's constants against it. §10 costs it.

**Which rung does the jury care about?** The rule sits among hard,
file-checkable constraints — LoROM, ≤512 KB, no special chips, no SRAM — beside
one other machine-level one, "works on real hardware". Read in that company,
"works on NTSC and PAL" is most naturally the same kind of statement: **it runs on both machines**, i.e. it does not
region-lock, does not hang on a 50 Hz console, and does not corrupt its display
there. That is rung 1, and the kit clears it. A jury asking for rung 3 would be
asking for something a large share of commercial PAL releases never delivered.

The one thing that *is* worth fixing is not on the spectrum at all: **the
header says the cartridge is North American.** On real hardware that byte is
inert — the console's own region decides 50/60 Hz — but it is what emulators
and flashcart menus read to pick a region automatically. Leaving it at `$01`
while claiming PAL support is the kind of mismatch a reviewer notices in ten
seconds, and it is not the only untrue byte in that header (§13).

## 10. The tiers, costed against 2026-10-31

Sizes are engineering judgement anchored to what this sprint measured; risk is
what could go wrong and what would catch it.

### Tier 0 — say what is true. **~1 hour. No risk.**

Do nothing to the ROM; write down what §9 rung 1 establishes and hand the jam a
sentence: *"Runs on NTSC and PAL hardware. Not speed-compensated: PAL play runs
at 50 Hz, i.e. 83% of NTSC speed. Verified on the cycle-accurate emulator
against both regions — all rails boot, render and play correctly."* Nothing can
regress because nothing changed.

### Tier 1 — stop the header lying. **~2 hours. Low risk, well caught.**

`vendor/rom/header.inc:41` is a bare `.byte $01`. Give it the `.ifndef` shape
its neighbours already have, and pick the honest value. There are three
defensible answers and the choice is reversible:

* keep `$01` and say "NTSC-first, runs on PAL" (zero work, mild mismatch);
* `$02` (Europe) if a PAL-facing build is what gets submitted — but then a
  *default* Mesen/snes9x run auto-selects 50 Hz and the reference render slows
  down, so the suite's implicit region changes and every screenshot oracle
  should be re-blessed at the new default;
* **make it per-rail overridable and leave the default at `$01`.** That is what
  the SRAM and ROM-size bytes already do and it is the only option that lets a
  submission choose without moving anyone else's floor.

Recommended: the third. Caught by: the header dump (a five-line check), the
existing ROM md5 gates moving, and `make gates`.

While in there: **20 of 37 rails declare `$05` (32 KB) in the ROM-size byte
while shipping 524,288 bytes** (§13). Same file, same class of lie, and there
is no gate on it. Fixing that is another hour and is worth doing in the same
change.

### Tier 2 — a PAL lane in the harness. **~1 day. Low risk; nothing ships.**

Turn `tools/pal_probe.py` from a probe into a check: a `make pal-check` that
runs a named subset of rails under both regions and asserts the properties this
document measured — the frame loop advances 1:1, the boot offset does not
exceed one frame, the offset does not grow between frame 240 and 1800, and the
raster rails stay pixel-identical. Region-parameterise the six `FRAME_MC`
constants and the two hard bounds in §8 while doing it.

This buys the thing the sprint could not: **PAL stops being a thing someone
checked once.** It costs a gate that must stay green, and it is the only tier
whose value survives the jam deadline.

### Tier 3 — fill the PAL frame. **~2–4 days. Medium risk.**

Enable overscan (`$2133` bit 2 — `SnesPpu.cpp:2232`, 239 lines) under PAL and extend every
per-scanline table from 224 to 239 entries: `rgb_gradient` `GRAD_LINES`,
`rc_grad` `RCG_LINES`, `mode7_persp`'s `PERSP_LINES` and the generated pose
blobs, `sh2_cam`/`shg_cam`/`sit_cam`'s band arithmetic, `m7_barrel`'s
`MB_LINES`, `met_glow`'s `.assert BANDS * LINES = 224`, plus the HDMA byte
budgets that follow. It also needs region detection to avoid changing the NTSC
picture, which drags tier 4's first half in with it.

Buys a fuller picture on a PAL television. Buys nothing a jury is likely to
check. **Not recommended before the deadline.**

### Tier 4 — run at the same speed on both. **~1–2 weeks. High risk.**

Read `$213F` bit 4 at boot, then choose a compensation strategy — either scale
every per-frame delta by 6/5 in 8.8 (touching physics, animation, timers,
scroll, streaming quotas and every generated LUT), or run the game logic at a
fixed tick and drop/duplicate presentation frames. Both mean re-validating
every rail's oracle at two speeds, and the movement/collision oracles in
`tools/gen_move_lut.py` and friends are bit-exact mirrors that would each need
a second calibration.

This is the change that could break a rail that works today. **Not recommended
at all for this jam**, and if it is ever wanted it belongs in its own phase
with its own audit.

## 11. Recommendation

**Do tier 0 and tier 1, in that order, and stop.** Concretely, first:

1. **Give the destination byte an `.ifndef`, keep the default at `$01`** —
   one edit to `vendor/rom/header.inc`, matching the shape of the two bytes
   above it. It is 20 minutes, it is reversible, and it turns "the header can
   only ever say North America" into "the header states a default a submission
   can override". `$2133` bit 2 is the overscan bit
   (`SnesPpu.cpp:2232`) if tier 3 is ever wanted.
2. **Write the PAL sentence into the submission text**, citing this document.
3. **Fix the 20 ROM-size bytes** in the same change, because it is the same
   file, the same class, and the jam also has a size rule.

Then, if there is calendar left after the game itself is done, **tier 2** —
because a `make pal-check` is the only artifact here that keeps being true
after October.

Do **not** spend the run-up on tier 3 or tier 4. The measurements say the kit
already clears the reading of the rule that a jam jury can actually apply, and
both of those tiers put working rails at risk to chase a reading it probably
does not mean.

## 12. What I could not settle here

These need real hardware or a second emulator. They are part of the
deliverable, not gaps in it.

1. **What a PAL television actually shows.** Mesen hands back the same 256×239
   buffer for both regions, so the border/letterbox question — 224 picture
   lines inside a 288-line PAL field — is invisible to this instrument. Needs a
   PAL console on a PAL set, or at minimum an emulator that models the visible
   field per region.
2. **Whether a real PAL SNES agrees with Mesen's 312-line, 21.28 MHz model.**
   Everything in §4 is Mesen's model, cross-read against Mesen's own source. It
   is a good model and it matches the published figures, but this sprint did
   **not** run a second emulator (bsnes) and did not touch hardware, so
   CLAUDE.md rule 7's bar is not met for any claim of the form "the emulator is
   wrong". I make no such claim: nothing here looked like an emulator bug.
3. **Whether the boot-phase offset is exactly one frame on silicon.** It comes
   from where a fixed master-cycle boot lands relative to a frame boundary, so
   it is sensitive to power-on timing that a real console may not reproduce
   bit-for-bit. The *bound* (≤1 frame, non-growing) should hold; the exact
   value per rail may not.
4. **The audio question a listener would ask.** I measured that SPC RAM and DSP
   state advance further per frame under PAL and read TAD's tempo path in
   source. I did **not** record and compare WAVs across regions. "Music is at
   the same tempo and gameplay is slower" is derived from the clock model and
   the driver's `TIMER_0` path, not from listening.
5. **Flashcart behaviour on a mismatched destination byte.** Whether an FXPAK
   or a PAL console's menu does anything with `$7FD9 = $01` is not something an
   emulator can answer.
6. **Whether the jam's jury tests PAL at all, and how.** §9's reading is an
   argument from the rule's company in the list, not a fact. If it matters,
   ask the organisers — it is one message and it settles the whole tier
   question.

## 13. Recorded, not fixed

This was a research sprint; each of these is written down and left standing.

* **The ROM-size header byte lies on 20 of 37 rails.** `$7FD7` reads `$05`
  (2⁵ KB = 32 KB) on `boss`, `boss_saucer`, `camera_follow`, `jumper`,
  `m7_dungeon`, `m7_oshoot`, `maze`, `meteor_event`, `mode7_explore`,
  `mode7_flight`, `scroll_run`, `scroller`, `split_h_2p_demo`, `split_h_demo`,
  `split_h_matrix_demo`, `split_h_persp3_demo`, `split_h_persp_demo`,
  `split_v_demo`, `split_v_fight`, `split_v_seamtrial` — all of which ship
  524,288 bytes. The other 17 set `SF_HDR_ROM_SIZE = $09` in their `main.asm`;
  these 20 never set it and inherit `header.inc`'s toy/probe default. This is
  the same declaration-lies class the file's own SRAM comment names as "bug
  C2", and **there is no gate on it** — `tools/fix_checksum.py` sums the real
  image and never consults the byte, so nothing notices. Relevant to the jam's
  size rule and to "works on real hardware".
* **Nothing writes `$2133` (SETINI).** Interlace and overscan are inherited
  from power-on in every rail. Today that is benign — both regions render 224
  lines — but it is a PPU register the kit relies on and never sets, which is
  exactly what CLAUDE.md rule 5 asks not to do. It is also the register tier 3
  would need.
* **`engine/features/irq/irq.asm:48` documents its input as "internal scanline
  (0..261)"** — an NTSC-shaped contract. Inert (both call sites arm line 112)
  and worth a word if anyone ever arms a VBlank-region line.
* **`room` reads uninitialised WRAM at `$000057/$000058`.** Reported by the
  core on both regions identically; pre-existing and unrelated to region.

## 14. Reproducing this

```bash
make toy microzero room probes breaker shmup platformer split_v_fight …   # every rail
python3 tools/pal_probe.py build/<rail>.sfc --map build/<d>/symbol_map.json \
        --anchor ppu  --frames 60,120,240,420,600 --outdir build/pal_shots
python3 tools/pal_probe.py build/<rail>.sfc --map build/<d>/symbol_map.json \
        --anchor game --frames 60,120,240,420,600 --outdir build/pal_shots
```

The rail → map-directory mapping is the Makefile's own `allocate.py --out`
argument (`microzero`→`mz`, `racer`→`rc`, `boss`→`bs`, `boss_saucer`→`sau`, …).

The two measurements this document leans on hardest were made with throwaway
scripts rather than committed ones, because both duplicate an existing test
with two constants changed and a committed duplicate would rot:

* **usable VBlank bytes per region** — `tests/test_measure_vblank.py`'s probe
  and protocol with its NTSC sanity bound removed;
* **per-frame work cost per region** — `tests/test_measure_cpu.py`'s latch-ring
  decode with `FRAME_MC` and the `>= 262` torn-slot guard region-parameterised.

Both are one-line changes to those files if the numbers ever need re-taking;
tier 2 would fold them in properly.

Gates after this document and `tools/pal_probe.py` landed, all clean and all
run bare:

```
make width-check    width_lint: 0 finding(s) across 224 file(s)
make time-check     no_wallclock: 0 NEW finding(s) across 240 file(s)
make register       census matches the tree (155 dirs); demand lint 18/25 rows
make rom-unbacked   backed arm accepted, unbacked arm refused
make cleanroom      swept 969 text files; 3 hit(s) exempted by 2 allowlist entries
```
