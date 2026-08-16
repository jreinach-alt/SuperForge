# Lesson 1 — See it run

*Matches Try-it prompt 1. At the end: a built ROM, eight screenshots of it
flying, and a first read of how this build talks to you. This step is short
because it works — the two loops below are the whole of it.*

## The loop

```bash
bash tools/setup.sh                          # once per box
make mode7_flight                            # -> build/mode7_flight.sfc (524,288 B)
python3 tools/shot_mode7_flight.py shots/    # -> eight PNGs of one scripted flight
```

`tools/setup.sh` verifies before it installs — assembler/linker, SDL2, the
emulator cores, Pillow, pytest — then runs its own sanity gates. On a genuinely
cold box the one slow step is building the Mesen2 core (~10 minutes, cached
afterwards); everything else is seconds.

Every showcase game has this same pair: `make <game>` builds it,
`tools/shot_<game>.py [outdir]` renders it. That pair is the standing loop for
the rest of these lessons.

## Reading the build log

The log is a tour of the architecture, in order: the asset **generators** run;
the **allocator** packs every claim and emits `build/m7f/*.inc` +
`symbol_map.json` (nothing in this repo is hand-placed); **`no_literals`**
scans every ASM file for raw address literals and validates register
ownership; then ca65/ld65 link and a checksum fixer signs the ROM.

The wall of file names near the end is the no-literals gate **succeeding** —
its one-line summary ("N files clean, M io write-sites examined") sits under
the list. Loud is normal here; silence would be the worry.

## Where the renders land

- Pass an outdir (as above) and your shots stay in it.
- With **no** argument, `tools/shot_mode7_flight.py` writes into `docs/img/` —
  the *committed* showcase renders. That is deliberate, not a hazard: the
  script is lockstep, so its output is a pure function of (ROM md5, power-on
  seed, input script), and on an unchanged ROM the regenerated PNGs come out
  byte-identical — `git status` stays clean. A dirty `docs/img/` after a shot
  run therefore *means something*: the picture changed.

## Reading what you see

The eight frames walk the game's axes one at a time, and the script's
docstring names each frame's intent — read it before narrating the pictures:

| frames | the axis |
|---|---|
| 01 spawn → 02 ceiling → 03 floor → 04 back to mid | altitude, both directions — the ground recedes as you climb, and the perspective scale is the proof |
| 05 turned | heading, under throttle |
| 06 both axes | turning + climbing + thrust at once — the composition the design exists to make cheap |
| 07 night → 08 day | the free-running day/night clock — the one axis that moves with no input |

When you show the owner, say which input produced each frame ("held R past the
ceiling clamp") — the pictures are evidence, and evidence gets a caption.

## What you just proved

The toolchain works end to end; the renders are deterministic; and "done"
around here means a fresh render from the verified binary attached to the
claim (CLAUDE.md rule 3). You will use all three for the rest of the arc.
