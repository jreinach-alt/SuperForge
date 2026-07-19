# L01 — The frame: VBlank and why everything waits for it

## The idea

The video chip (PPU) draws the screen top to bottom, one scanline at a time:
262 lines per frame on NTSC, of which ~224 are visible, at ~60 frames per
second (hardware-reference). After the last visible line comes **VBlank** —
the ~38-line gap while the beam "returns to the top". Two facts follow, and
together they shape every SNES program:

1. **During the visible part of the frame, the PPU owns its memories.** Your
   CPU can compute freely, but it cannot safely touch video memory while the
   PPU is reading it to build the picture (L04 shows what happens if you try).
   VBlank is the only per-frame window for getting results onto the screen.
2. **The PPU fires an interrupt (NMI) at the start of every VBlank.** That
   interrupt is the metronome. The idiomatic game loop does a frame's worth
   of logic, stages the results in ordinary RAM, then *waits* for the NMI to
   copy them across and start the next frame.

So the frame is your unit of time (velocity is pixels-per-frame, animation is
frames-per-step) *and* your budget (a frame's logic must fit inside a frame —
L09 has the kit's measured numbers). In this kit the wait is explicit:
`sf_frame_begin` spins on a flag that only the NMI handler sets, and the
handler also increments a frame counter (engine-verified:
`FRAME_COUNTER`, 16-bit, WRAM `$010C` — see `engine/engine_state.inc`).
Everything waits for VBlank; the counter is the proof.

## See it live

From the kit root, with `build/hello_world.sfc` built (L00):

```bash
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/hello_world.sfc", run_seconds=2.0)

def frames():
    lo, hi = r.read_bytes(MemoryType.SnesWorkRam, 0x010C, 2)
    return lo | (hi << 8)

a = frames()
r.run_frames(60)               # ~one second of emulation
b = frames()
print(f"counter: {a} -> {b} (delta {b-a})")

r.debug_break()                # park execution at the frame boundary
vals = [frames()]
for _ in range(5):
    r.frame_step(1)            # advance exactly one frame
    vals.append(frames())
print("stepped:", vals)
r.stop()
EOF
```

Observed output (absolute values vary with boot timing; the deltas are the
point):

    counter: 115 -> 177 (delta 62)
    stepped: [178, 179, 180, 181, 182, 183]

Two honest readings. `run_frames` paces by wall-clock, so its delta is
*about* 60 — the heartbeat is real but the count is sloppy. `frame_step`
advances exactly one PPU frame per call: five steps, five increments, no
drift. That is why every deterministic capture in the kit's test suite uses
frame-stepping, never wall-clock timing.

## Exercise

The frame is the time unit: speed is whatever you add *per frame*. In
`examples/move_sprite/main.asm` change `PLAYER_SPEED = 2` to `4`, rebuild
(`make move_sprite`), then step exactly 30 frames of Right and read the
player's position word (WRAM `$32`, this example's `PLAYER_X`):

```python
r.frame_step(30, right=True)
```

Verified outcome: X moves 120 pixels — 4 px/frame times 30 frames, exact.

## What breaks if…

**…a frame's logic doesn't fit in a frame.** Nothing crashes. The loop misses
the next NMI, catches the one after, and the whole game runs at half speed —
uniformly, silently. This was normal in licensed-era games under load, and it
is the failure you will actually ship: it looks like "the game feels slow",
not like a bug. Diagnose it by measurement, not vibes: read `FRAME_COUNTER`
across one loop iteration; a healthy loop advances it by 1, an overrun by 2.
L09 covers the budget arithmetic.

**…you assume 60 everywhere.** PAL consoles run 50 frames per second, so
frame-locked logic runs ~17% slower there — pace, not glitches. The kit's
harness has a region knob (`SF_REGION=pal`) and
[`../../JAM.md`](../../JAM.md) has the full region story; the honest summary
lives in [`../../EXPECTATIONS.md`](../../EXPECTATIONS.md) under declared gaps.

**…a test paces by wall-clock.** `run_frames(60)` gave us 62 frames above.
Scripts calibrated with run-then-hope capture the wrong frame on someone
else's machine; the kit's rule is frame-step for anything that asserts exact
state. You just watched why.

Next: [L02 — The graphics model](L02_graphics_model.md): what those VBlank
copies are actually filling.
