# Building a SNES DEV Game Jam 2026 entry with this kit

The [SNES DEV Game Jam 2026](https://itch.io/jam/snes-dev-game-jam-2026)
runs **July 31 – November 14, 2026**. This kit is a toolchain in the same
category as the tools the jam page itself recommends (libSFX, PVSnesLib,
SNDK): you write the game, the kit gives you a proven engine, macro
library, starter rails, and an emulator-verified test loop.

This page maps every jam technical restriction to the kit, and flags the
two things an entrant must actively do (the no-SRAM header, and PAL
testing).

## The jam's technical restrictions, rule by rule

| Jam rule | Kit status | What you do |
|---|---|---|
| Game is LoROM | Every kit link shape is LoROM (`infrastructure/rom_template/lorom*.cfg`) | Nothing |
| Max size 512 KB | Kit ROMs are 32–64 KB; the largest link shape (`lorom_stream.cfg`, streaming worlds) is exactly 512 KB | Nothing |
| No special chips (SA-1, Super FX, …) | The kit targets the stock console only: 65816 + PPU + SPC700. No co-processor code exists in the kit | Nothing |
| **No SRAM** | The default `lorom.cfg` is battery-less, **but the default ROM header declares 8 KB SRAM** (so the save-capable link shapes need no variant) | **Include `header_jam.inc` instead of `header.inc`** — it zeroes the cartridge-type and SRAM-size header bytes (verified: changes exactly those two bytes). Do **not** use `sf_save`/`sf_load` or any `*_sram` link shape in a jam entry |
| Works on real hardware | Everything is verified on cycle-accurate Mesen2 under **randomized power-on RAM** (real hardware's cold-boot garbage), which catches the classic works-in-emulator/breaks-on-hardware uninitialized-memory class. The final word is still a real console — if you have a flashcart, test on it; if not, say so in your submission and ask the community | Keep `make check` green; flashcart-test if you can |
| **Works on NTSC and PAL** | The test harness has a region knob: `SF_REGION=pal` forces 50 Hz PAL timing (`SF_REGION=ntsc` forces 60 Hz; default = ROM header). The kit's cold-start → PPU init → NMI → frame-loop pipeline is smoke-verified under both. Two honest caveats: (1) kit templates are tuned at 60 fps — frame-locked game logic runs ~17 % slower on PAL (that is how most licensed-era games behaved too); (2) music tempo is driven by the sound CPU's own region-independent timers, so music speed holds while frame-driven events slow | Boot your entry with `SF_REGION=pal` before submitting; play it — if the slower pace hurts, scale your per-frame velocities/timers by 6/5 when a PAL console is detected, or accept the classic slowdown and note it |
| No ripped music or graphics; free assets allowed | The kit ships only CC0 / recorded-permissive art (`examples/itch_cc0/LICENSES.md`) and its own audio; the **clean-room CI gate** (`tools/cleanroom_check.sh`, first step of `make check`) blocks commercial names and forbidden file classes mechanically | Keep the gate in your fork and your entry stays jam-legal by construction. Add provenance lines for any asset you import |
| Done by yourself; teams allowed with credits | Using an engine/toolchain is normal here (the jam page recommends several). Disclose what you built with — a "made with SuperForge" line costs nothing and reads as honest | Credit your tools and teammates. If any part of your workflow involves AI assistance, ask the hosts in the jam community forum whether/how to disclose it — the rules don't address it, and transparency beats a surprise |

## Attribution you may owe (one line, check it)

The kit's **per-scanline Mode 7 perspective renderer** (the `pv_*` path
behind `sf_mode7` — used by the racer, free-flight, streaming-overworld,
rail-shooter, and perspective split-band rails) is derived from Brad
Smith (rainwarrior)'s dizworld, licensed **CC BY 4.0**. If your entry
uses that path, your ROM contains CC BY code and **your game must credit
him** — a line in your credits screen or itch.io page description works:

> Mode 7 perspective renderer derived from dizworld by Brad Smith
> (rainwarrior), CC BY 4.0.

The flat/uniform-affine Mode 7 path (`sf_mode7_affine` — boss, saucer,
dungeon, overhead-shooter rails) and everything else in the engine is kit
zlib and needs no credit (though credits are always appreciated —
see `NOTICE` for the full third-party picture). When in doubt, include
the line; it costs one sentence.

## Practical notes for an entry

- **Start from the nearest rail**, not from zero: `scenarios/README.md`
  is the routing table (platformer, shmup, brawler, racer, Mode 7
  dungeon/overhead-shooter/flight, boss fights, split-screen, RPG, …).
- **ROM title:** the header ships as `"SUPERFORGE TEST      "` — put your
  game's name in the 21-byte title field (see `header.inc`); emulators,
  flashcarts, and the jam's multicart menu display it.
- **Checksum:** the header ships placeholder checksum bytes; emulators
  tolerate that. Multicart/flashcart tooling usually fixes checksums
  itself, but if you want a valid one, any ROM-header utility can write
  it into `$FFDC-$FFDF` post-build.
- **Submission artifact:** the built `.sfc` is self-contained — it runs
  in any SNES emulator and on real hardware via flashcart, with no
  runtime dependencies.
- **Deadline sanity:** `make check` re-verifies every template and macro
  group end-to-end. Run it before you submit; a green suite plus a
  `SF_REGION=pal` boot is the kit's definition of "ready".
