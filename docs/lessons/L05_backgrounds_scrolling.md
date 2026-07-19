# L05 — Backgrounds, scrolling, cameras

## The idea

A background layer is a tilemap (L02) plus two scroll registers. The common
map is 32x32 entries of 8x8 tiles — a 256x256 pixel surface, about one
screen. Scrolling moves no memory at all: `BG1HOFS`/`BG1VOFS` just change
where in that surface the PPU starts reading, and the map **wraps** on both
axes (hardware-reference) — scroll far enough and you see the same tiles
again. Two consequences: panning is nearly free (two register writes a
frame), and the world is *small* — a level bigger than one screen exists only
as data elsewhere, streamed into the wrapping map at its edges as the view
moves (the kit ships that discipline as proven rails; see below).

A **camera** is then pure software convention: the player moves in *world*
coordinates, the camera picks the visible window (usually "center the
player, clamped at the world edges"), the background scrolls by the camera
position, and sprites draw at `world - camera`. The kit packages the
transform as `sf_camera_follow` (`lib/macros/sf_camera.inc`). One hardware
wrinkle inherited from L04: scroll registers are write-twice 8-bit ports
sharing an internal latch, so the engine keeps scroll *shadows* in WRAM and
lets the NMI write the pairs during VBlank.

## See it live

`templates/scroller/` is the minimal case: a green checkerboard you scroll
with the d-pad under a fixed center sprite.

```bash
make scroller
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/scroller.sfc", run_seconds=2.0)
def hofs():
    lo, hi = r.read_bytes(MemoryType.SnesWorkRam, 0x0120, 2)  # SHADOW_BG1HOFS
    return lo | (hi << 8)
a = hofs()
r.frame_step(60, right=True)
b = hofs()
print(f"H-scroll {a} -> {b}, sprite at", list(r.read_bytes(MemoryType.SnesSpriteRam, 0, 2)))
r.take_screenshot("/tmp/scroller.png")
r.stop()
EOF
```

Observed: `H-scroll 0 -> 120, sprite at [120, 100]` — exactly 2 px/frame for
60 stepped frames, the world sliding under a sprite that never moved; the
screenshot shows the checkerboard phase-shifted from boot.
`templates/camera_follow/` adds the camera: a 512x448 world, clamped follow.

```bash
make camera_follow
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/camera_follow.sfc", run_seconds=2.0)
def w16(a):
    lo, hi = r.read_bytes(MemoryType.SnesWorkRam, a, 2)
    return lo | (hi << 8)
def snap(tag):
    print(f"{tag}: player world X={w16(0x32)}  camera X={w16(0x36)}  "
          f"sprite screen X={r.read_bytes(MemoryType.SnesSpriteRam,0,1)[0]}")
snap("boot         ")
r.frame_step(60, right=True)
snap("mid-world    ")
r.frame_step(120, right=True)
snap("at world edge")
r.stop()
EOF
```

Observed:

    boot         : player world X=256  camera X=128  sprite screen X=128
    mid-world    : player world X=376  camera X=248  sprite screen X=128
    at world edge: player world X=504  camera X=256  sprite screen X=248

Mid-world, the sprite is glued to screen center while the camera moves; at
the edge the camera clamps (256 = world 512 - screen 256) and the *sprite*
finally walks toward the border. That crossover is the whole camera-follow
contract, read straight off the hardware.

## Exercise

The tilemap is just data — repaint it. In `templates/scroller/main.asm` the
checkerboard is built by `lda BG_MX / eor BG_MY / and #$0001`. Delete the
`eor BG_MY` line, rebuild, re-run. Verified outcome: vertical stripes (column
parity alone picks the tile), scrolling unchanged — pattern and motion are
independent layers of the model. Revert when done.

## What breaks if…

**…your level is bigger than the map.** Nothing warns you: the 32x32 map
happily wraps, and your "second screen" shows the first screen again.
Newcomers hit this the day the game outgrows one screen. The honest answer is
streaming — feeding the wrapping map new columns/rows at the edges, inside
the VBlank budget, without tearing — and it is genuinely hard, which is why
the kit ships it as proven rails (`templates/platformer_stream/`,
`templates/mode7_explore/`, guides in `docs/guides/`) rather than a
paragraph of encouragement. Start there, not from scratch.

**…you write scroll registers directly, once.** Each write-twice port wants
low byte then high byte at the same address, and several share the latch. A
single "reset" write leaves the latch half-advanced, so a *later* write lands
as a high byte — the scene jumps by 256 pixels and the bug report says
"scrolling is haunted". The engine's shadow + NMI path exists for this;
[`../../EXPECTATIONS.md`](../../EXPECTATIONS.md) has the worked case and the
pair-then-move-on rule.

**…the pattern is right but the colors are wrong.** Tilemap entries carry a
palette group per cell; a correct tile with the wrong group renders in
someone else's colors — see [`../troubleshooting.md`](../troubleshooting.md)
("BG tiles render with wrong colors").

Next: [L06 — Input, physics, tile collision](L06_input_physics_collision.md),
where the world starts pushing back.
