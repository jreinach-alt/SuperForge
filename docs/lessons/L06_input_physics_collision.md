# L06 — Input, physics, tile collision

Where a SNES game stops being a picture and starts being a game. Builds on
[L01 (the frame)](L01_the_frame.md) and [L05 (backgrounds & scrolling)](L05_backgrounds_scrolling.md).

## The idea

**Input.** There is no OS and no event queue. Writing `$81` to `$4200` enables
NMI (bit 7) *and* auto-joypad reading (bit 0): every VBlank the hardware clocks
both pads serially into registers, P1 landing as a 16-bit word at `$4218/$4219`.
The read takes time (~4,224 master clocks — comment in `engine/nmi_handler.asm`),
so the engine's NMI polls `$4212` bit 0 until it finishes, then snapshots the
word and edge-detects "newly pressed" into a latch (engine-verified:
`engine/nmi_handler.asm`, Phase 6). Your code never touches the ports — `btn
#BTN_RIGHT` (held) and `btnp #BTN_A` (pressed this frame) read the shadows
(`lib/macros/sf_input.inc`, IDs in `buttons.inc`). Which button sits in which
bit is the controller's shift order, not intuition: A is bit 7 of the LOW byte,
Right is bit 8, up in the high byte — `EXPECTATIONS.md` has the story of the
demo that guessed wrong.

**Physics.** `sf_physics_step` (`lib/macros/sf_physics.inc`) is one frame of
vertical physics over 8.8 fixed-point Y (high byte = pixel, low byte =
subpixel — smooth arcs at 60 fps without floats). Gravity `$0040`
(0.25 px/f²), terminal fall 4 px/f, take-off `$0480` (4.5 px/f). The macro owns
the whole state cycle — standing, take-off, ascent, head bump, apex, descent,
landing snap — so the caller writes no collision response. `sf_jump_cut`,
called every frame the button is *up*, caps a released ascent: tap = hop,
hold = full arc (measured below).

**Collision.** Terrain collision is not a physics engine; it is the tilemap
itself. `sf_tile_flags` marks tile IDs (bit 0 solid, bit 1 one-way platform),
`col_map` probes the flag under any pixel, and `sf_solid_box` tests an 8x8
box's four corners — at `+7`, not `+8`; a `+8` probe reads the neighbouring
tile and sticks you to walls (`lib/macros/sf_map.inc`). The flagship's frame is
the pattern to copy (`templates/platformer/main.asm`, `game_tick`): read input
→ walk X by *tentative position + box probe, revert if blocked* → gate the
jump on `GROUNDED` → `sf_level_physics_step` → pit / coin probes → draw. The
same bytes the PPU renders are the world you collide with.

## See it live

From a materialized kit root (after `bash tools/setup.sh`):

```bash
make platformer
PYTHONPATH=. python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
WR = MemoryType.SnesWorkRam
r = MesenRunner()
r.load_rom("build/platformer.sfc", run_seconds=1.0)
r.debug_break()
r.frame_step(2, start=True)            # press START on the title
r.frame_step(30)                       # release; the game scene starts
x0 = r.read_u16(WR, 0x32)              # PX — player world X (DP $32)
r.frame_step(30, right=True)           # hold Right for 30 frames
print("PX", x0, "->", r.read_u16(WR, 0x32),
      "GROUNDED", r.read_u16(WR, 0x3A))
rest = r.read_u16(WR, 0x34) >> 8       # PYF high byte = pixel Y
apex_held = rest
for _ in range(24):                    # jump with A HELD the whole arc
    r.frame_step(1, a=True)
    apex_held = min(apex_held, r.read_u16(WR, 0x34) >> 8)
for _ in range(30): r.frame_step(1)
landed = r.read_u16(WR, 0x34) >> 8     # where did the arc end?
apex_tap = landed
r.frame_step(1, a=True)                # jump with a 1-frame TAP
for _ in range(24):
    r.frame_step(1)
    apex_tap = min(apex_tap, r.read_u16(WR, 0x34) >> 8)
print("rest", rest, "held apex", apex_held,
      "landed at", landed, "tap apex", apex_tap)
r.stop()
EOF
```

Observed: `PX 24 -> 84` (2 px/frame, the walk probes passing), `GROUNDED 1`,
then `rest 184 held apex 145 landed at 152 tap apex 146`. Three mechanics in
one line: the held arc rises 39 px off the ground (the macro header's "~38 px"
claim, measured); the descent lands pixel-exactly ON the one-way platform
overhead (tile row top 160 − 8 px box = 152 — the landing snap, and the
platform catching a crossing from above); and the tap from there hops only
6 px. That last gap *is* `sf_jump_cut`. Holding Left from spawn instead pins
`PX` at 8: the template's edge clamp.

## Exercise

Make the jump moonier. The tunables are override-before-include: add

```asm
SF_JUMP_VEL = $0600
```

directly under `.smart` at the top of `templates/platformer/main.asm`, then
`make platformer` and rerun the snippet. Expected: the held apex rises ~69 px
off the ground (measured: `rest 184 held apex 115`); the tap hop barely
changes, because the cut cap, not the take-off speed, rules it. Try `$0900`
and the build itself refuses: the macro's `.assert` knows >8 px/frame outruns
the box probe.

## What breaks if…

- **…you read the pad as two bytes and guess the halves.** No crash — the
  button just "never works", because A lives in the low byte and the d-pad in
  the high one. Read the word 16-bit and mask, or stay on `btn`/`btnp`.
  `EXPECTATIONS.md` → "Reading 16-bit values one byte at a time".
- **…you read `$4218` without waiting on `$4212` bit 0.** Early in VBlank the
  auto-read is still shifting; you read half-shifted state (and unused bits
  are open bus, not 0 — `scenarios/knowledge.md`, trap T-8). The engine NMI
  waits for you; keep manual reads out of your own code.
- **…you use `btn` where you mean `btnp`.** Held-A auto-rejump on every
  landing, menus that fire every frame, and the scene-swap ghost where the
  player "won't move until I release and press again" —
  `docs/troubleshooting.md` → "After a scene swap…".
- **…you move faster than 8 px/frame.** The 8x8 box probe covers an 8 px
  step; beyond it you tunnel through walls and floors. The asserts in
  `sf_physics.inc` hold the line — don't work around them, redesign the speed.
- **…`col_map` always returns 0.** Almost always: you never called
  `sf_tile_flags`, you flagged the wrong layer, or you probe outside the map
  (out-of-bounds reads 0 by contract). `docs/troubleshooting.md` → "`col_map`
  always returns 0".

Next: [L07 — Mode 7 in one sitting](L07_mode7.md).
