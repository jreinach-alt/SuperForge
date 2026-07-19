# Intro to SNES development — the lesson course

Eleven short lessons that take you from "what even is a SNES program" to a
shippable jam entry, using only what this kit ships. The course teaches the
platform the way the kit practices it: **capabilities and limitations,
honestly**. Every lesson names what the hardware gives you *and* the wall
you will hit, and every claim is tiered the way
[`../../AGENTS.md`](../../AGENTS.md) requires — **engine-verified** (measured
on the emulator, code cited) or **hardware-reference** (from the SNES
references, not separately tested here). Where a lesson says "observed", the
author ran that exact command against a built ROM and pasted the real output.

## How to use it

Work from the kit root on Linux/WSL, one-time setup first:

```bash
bash tools/setup.sh     # toolchain + emulator core + smoke test
```

Each lesson is four sections: **The idea** (the mechanism, plain words),
**See it live** (commands you run; expected output stated), **Exercise** (one
small edit with a verifiable outcome), and **What breaks if…** (the failure
you will actually hit, and how to diagnose it). Lessons build on each other —
L00's ROM is L01's lab rat — so go in order the first time. Nothing here asks
you to write new assembly from scratch; you run, probe, and modify the
shipped examples and templates, which is also how the kit intends real games
to start ([`../../AGENTS.md`](../../AGENTS.md): route to a rail, adapt).

Companion pages you will meet repeatedly:
[`../../EXPECTATIONS.md`](../../EXPECTATIONS.md) (the churn that is normal on
this platform — read it before your first bad evening),
[`../troubleshooting.md`](../troubleshooting.md) (symptom-indexed fixes), and
[`../../JAM.md`](../../JAM.md) (shipping a jam-legal entry).

## The lessons

| # | Lesson | One line |
|---|---|---|
| L00 | [What a SNES program is](L00_what_a_snes_program_is.md) | No OS, no loader: ROM bytes, the reset vector, and the NMI loop — build and boot `hello_world`, read its header and its first sprite off the hardware. |
| L01 | [The frame](L01_the_frame.md) | The PPU's 60 Hz heartbeat is your clock and your budget: why everything waits for VBlank, proved with the frame counter and exact frame-stepping. |
| L02 | [The graphics model](L02_graphics_model.md) | No framebuffer — tiles, tilemaps, palettes, OAM; convert real CC0 art with `png2snes` end-to-end and watch it reject art the hardware can't hold. |
| L03 | [The 65816's one weird trick: 8/16-bit width](L03_width.md) | The platform's #1 silent-corruption class: plant a real width bug, watch `make width-check` catch what the build and a play-test miss. The course's centerpiece; pairs with [`EXPECTATIONS.md`](../../EXPECTATIONS.md). |
| L04 | [DMA](L04_dma.md) | Why you can't touch VRAM mid-frame, and the shadow-then-VBlank pipeline that follows — measured as a one-frame lag between game state and hardware OAM. |
| L05 | [Backgrounds, scrolling, cameras](L05_backgrounds_scrolling.md) | Scrolling moves no memory; the map wraps; a camera is a software transform with a clamp — driven and read live on two templates. |
| L06 | [Input, physics, tile collision](L06_input_physics_collision.md) | Held vs pressed, fixed-point velocity, and how a tilemap doubles as the world's solid geometry. |
| L07 | [Mode 7 in one sitting](L07_mode7.md) | The one rotating/scaling background: what the affine hardware really does, the two projection disciplines, and where the floor's magic ends. |
| L08 | [Audio: BRR, the SPC700 as a second computer, TAD](L08_audio.md) | The sound system is a second CPU you upload a program to — samples, the driver, and making a rail actually beep. |
| L09 | [Budgets & limits — the kit's real measured numbers](L09_budgets_limits.md) | Cycles per frame, sprites per scanline, VRAM ceilings: the walls, with the kit's own measurements instead of folklore. |
| L10 | [Ship it: header, checksum, PAL, flashcart, the jam profile](L10_ship_it.md) | From "works on my emulator" to a submittable `.sfc`: titles, checksums, 50 Hz honesty, real hardware, jam rules. |

## The posture, in one paragraph

This kit verifies on a cycle-accurate emulator with randomized power-on RAM,
asserts on rendered output, and still calls real hardware the final word
([`../../EXPECTATIONS.md`](../../EXPECTATIONS.md), "Emulator vs hardware").
The lessons inherit that posture: when a demo can be measured, it is; when a
claim comes from the references rather than a measurement, it says so; and
when the platform is simply limited — 15 colors per palette, one screen of
tilemap, a VBlank that runs out — the lesson shows you the wall instead of
selling around it. If a lesson's command doesn't produce what the lesson
says, that is a bug in the kit: please report it.
