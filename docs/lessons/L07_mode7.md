# L07 — Mode 7 in one sitting

The famous mode, and the most-misunderstood one. Builds on
[L02 (the graphics model)](L02_graphics_model.md) and [L04 (DMA & HDMA)](L04_dma.md).

## The idea

Mode 7 is **one** BG layer — a 128x128-tile, 256-color plane — where the PPU
runs every screen pixel through a 2x2 matrix (`M7A-M7D`, 1.7.8 signed
fixed-point) plus a pivot (`M7X/M7Y`) to find which map texel to draw. That
buys hardware rotation and scaling of the *whole plane*, free, every frame. It
is not a 3D chip, and it never touches sprites: OBJ still has exactly two
hardware sizes (hardware-reference; the matrix applies to BG1 only — engine
receipt: `lib/macros/sf_mode7_affine.inc`, "the matrix never touches OBJ").
Larger coefficient = more map per pixel = the world looks *smaller*.

The kit drives that one piece of hardware two very different ways:

- **`sf_mode7_affine` — one uniform matrix per frame.** Write M7A-D once and
  the plane scales/rotates as a rigid image: the "boss IS the screen"
  technique (`templates/boss/`, guide `docs/guides/mode7_boss.md`). The
  per-frame cost is structurally a dozen register writes
  (`sf_boss_matrix` → `mode7_set_static`) — no HDMA, no tables. Player,
  attacks, HP bar are OBJ composited on top.
- **`sf_mode7` — a new matrix every scanline.** An HDMA channel pair feeds
  M7A-D per line, so each scanline gets its own scale: near lines magnified,
  far lines shrunk — a perspective floor (`templates/mode7_flight/`,
  `templates/racer/`). The hardware part is free; the *CPU* part — rebuilding
  the per-scanline table — is the expensive class on this platform: a full
  live rebuild measures 86–138% of one frame, which is why the engine only
  rebuilds on dirty flags and interpolates (measured, `tests/test_persp_cycles.py`;
  L9 owns the numbers). Holding the angle constant and moving only the origin
  costs ~1% of a frame (measured, `tests/test_mode7_chamber_cycles.py`).

Two consequences newcomers hit immediately. **The sky**: one layer means the
band above the horizon would render the floor smeared upward — every
perspective floor with a visible horizon needs the sky split
(`sf_mode7_sky_split`; the SKY RULE in `lib/macros/sf_mode7.inc`). **Sprite
"scaling"**: objects on the floor can't ride the matrix — the illusion is
pre-drawn size tiers selected by distance (5 apparent sizes on 2 hardware
sizes in the split-screen sprite rail — `docs/guides/split_h.md`).

## See it live

```bash
make boss mode7_flight
PYTHONPATH=. python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
WR = MemoryType.SnesWorkRam
r = MesenRunner()
r.load_rom("build/boss.sfc", run_seconds=0.5)
scales = []
for _ in range(6):
    r.run_frames(12)
    scales.append(hex(r.read_u16(WR, 0xE018)))   # matrix-scale mirror (1.7.8)
print("reveal scale walk:", scales)
r.take_screenshot("/tmp/boss.png")
r.load_rom("build/mode7_flight.sfc", run_seconds=0.7)
r.debug_break()
before = [r.read_u16(WR, a) for a in (0xE018, 0xE01A, 0xE01C)]
r.frame_step(60, r=True)                         # hold R: climb
after = [r.read_u16(WR, a) for a in (0xE018, 0xE01A, 0xE01C)]
print("flight alt/s0/s1:", before, "->", after)
r.debug_resume()
r.take_screenshot("/tmp/flight.png")
r.stop()
EOF
```

Observed: `reveal scale walk: ['0x2ec', '0x244', '0x180', '0x180', ...]` — the
boss's reveal walks the *one* coefficient down (bigger boss) and holds at
`$0180`; `/tmp/boss.png` shows a screen-filling rotated boss with sprite HP
pips over it. The flight line reads `[120, 670, 152] -> [240, 1120, 265]`:
altitude up, both derived scales up, and `/tmp/flight.png` is the classic
receding checkerboard under a clean sky band.

## Exercise

Lower the flight horizon. In `templates/mode7_flight/main.asm` change
`PV_L0_FLIGHT = 64` to `96`, rebuild, re-screenshot. Expected: the sky band
deepens from ~29% to ~43% of the screen and the floor starts lower (verified
on the screenshot). The sky split follows automatically — `SKY_HORIZON` is
defined *from* `PV_L0_FLIGHT`, which is exactly how the smear stays fixed.

## What breaks if…

- **…you ask Mode 7 for two independently scaling objects.** You can't — there
  is one plane and one matrix (or one matrix *per scanline*, which is still one
  object per horizontal band). A second scaled thing is OBJ with size tiers, or
  a raster split. This is the single most common over-promise newcomers import
  from folklore.
- **…you skip the sky split on a perspective floor.** The band above the
  horizon renders the map smeared upward. It looks broken, it is by-design
  hardware behavior, and the fix is two calls — `docs/troubleshooting.md` →
  "above the horizon is a stretched smear of the map". The kit shipped this
  bug once (an overworld the owner rejected); the rule in `sf_mode7.inc` is
  the scar tissue.
- **…you rebuild the full per-scanline table every frame because "it's only a
  table".** 86–138% of a frame: your loop closes every second frame and all
  motion drops to 30 Hz. The two-player split rail exists specifically because
  a second live solve *cannot* fit (measured — `tests/test_persp_cycles.py`).
- **…your sprites vanish the moment you switch to Mode 7.** The map+CHR fill
  VRAM words `$0000-$3FFF`, right where the default OBJ name base points; move
  OBSEL (the flight template does — `docs/troubleshooting.md` → "Sprites are
  invisible over the Mode 7 floor").
- **…a matrix write lands once instead of twice.** M7A-D and friends are
  write-twice 8-bit ports sharing one internal latch; a single write leaves the
  latch half-advanced and the *next* write lands as a high byte — shear,
  garbage, or a plane that "sometimes" flips. `EXPECTATIONS.md` → "The
  byte-order cousin". The macros sequence the pairs for you.

Next: [L08 — audio](L08_audio.md).
