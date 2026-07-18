# SNES vs modern engines — the idiom guardrail

If your instincts come from Unity, Godot, or any modern engine, READ THIS
BEFORE WRITING CODE. The SNES is not a slow PC: it is a different machine
shape, and modern idioms don't degrade gracefully on it — they simply don't
exist. Every section below is a translation: the modern reflex, why it can't
work here, and the SNES-native pattern this kit gives you instead.

## The machine you actually have

- **CPU:** 65816 @ ~2.7-3.6 MHz. One 60fps frame is a budget of a few tens
  of thousands of cycles — and the frame DEADLINE is hard. There is no
  "lower the framerate" escape: miss VBlank and the picture tears.
- **No floating point. No divide. No multiply on the base instruction set
  you'd recognize.** `a / b` is not slow — it does not exist.
- **No framebuffer.** You cannot "set pixel (x,y)". The PPU composes the
  picture every scanline from tilemaps, tiles, sprites, and palettes.
- **Fixed memory:** 128 KB WRAM, 64 KB VRAM, 544 bytes of OAM, 512 bytes of
  CGRAM. No heap, no allocator, no GC.

## Numbers: 8.8 fixed-point, not float

The modern reflex: `float speed = 2.5f; pos += speed * dt;`

Here: a 16-bit word holds **8.8 fixed-point** — high byte = signed integer
pixels, low byte = 1/256 fractions. `$0280` is 2.5 px/frame. Add and subtract
are plain 16-bit ops; the integer pixel is the high byte (`xba` or `>>8`).
The kit's physics (`sf_physics.inc`) runs entirely in 8.8: `SF_GRAVITY =
$0040` is 0.25 px/f². There is no `dt` — see "Time" below.

Division: don't. Shift right for powers of two; for anything else,
restructure (multiply by a reciprocal constant, use a table, or redesign so
the divide never appears). If you catch yourself wanting `atan2`, `sqrt`,
`sin` — those are LOOKUP TABLES on this platform, never math.

## Time: the frame IS the clock

The modern reflex: `Update(float deltaTime)`, frame-rate independence.

Here: the machine is the clock. NTSC VBlank fires exactly 60 times a second;
one pass through your game loop = exactly 1/60 s. "Speed 2" means 2 px/frame
= 120 px/s, always. No delta-time, no interpolation, no catch-up loops. The
kit's frame bracket (`sf_frame_begin` / `sf_frame_end`) pins your loop to
VBlank; cooldowns and timers are frame COUNTERS (the shmup's spawn timer
counts 48 frames, not 0.8 seconds).

## Drawing: tiles + sprites + palettes, never pixels

The modern reflex: draw calls, render textures, `SetPixel`, a UI canvas.

Here the picture is composed by hardware from:
- **BG layers** — tilemaps of 8x8 tiles (`gfxmode`, `mset`, `scroll`). A
  "level" is tile indices in a map, not an image.
- **Sprites (OBJ)** — up to 128 OAM entries, hardware sizes only (8x8,
  16x16, 32x32... via OBSEL pairs). An actor is `spr tile, x, y, flags, pri`
  re-stated every frame.
- **Palettes** — 4bpp art picks 16-color palettes (8 for BG, 8 for OBJ);
  **color index 0 is transparent**, so 15 usable colors. Tinting/flashing =
  palette writes, not shaders.
- **Text/HUD** — tiles on BG3 (`sf_text.inc`), not a UI system.

Per-scanline hardware limits are real: >32 sprites on one scanline simply
drop. Don't line your actors up in a row off-screen — park dead sprites at
y=$F0.

And the cardinal port rule: **VRAM/CGRAM/OAM are writable only during
VBlank or forced blank.** The kit's pattern is shadow state — your code
writes WRAM shadows (`mset`, `spr`, `scroll` all do), and the NMI handler
commits them during VBlank. Load art in setup under forced blank
(`sf_load_*`), then never touch the ports directly mid-frame.

## Objects: pools + parallel arrays, not GameObjects

The modern reflex: `Instantiate(bulletPrefab)`, a `List<Enemy>`, garbage
collection, components.

Here: memory is laid out at ASSEMBLE TIME. An actor type is a set of
parallel arrays (x[], y[], alive[]) at fixed WRAM addresses, and "spawning"
is claiming a free slot (`sf_pool.inc`: init/spawn/kill_x/count). Nothing is
ever allocated or freed; the maximum count is a design decision you make up
front (6 bullets, 4 enemies — that's the cartridge spirit). State machines
are a byte holding an enum, not a coroutine.

| Modern concept | SNES-native equivalent |
|---|---|
| GameObject / entity | a pool slot: index into parallel arrays |
| `Instantiate` / `Destroy` | `sf_pool_spawn` / `sf_pool_kill_x` |
| `Update()` per object | one pass over each pool per frame |
| Transform.position (float) | 8.8 fixed-point words in DP/WRAM |
| SpriteRenderer | an OAM entry, re-drawn every frame |
| Tilemap / level asset | BG tilemap words (`mset`), tile flags for collision |
| Camera | BG scroll registers (`scroll`, `sf_camera_follow`) |
| Canvas / UI text | BG3 tiles (`print`, `sf_print_u16`) |
| Physics engine | integer AABB (`col_box`) + tile flags (`col_map`) + a 20-line integrator (`sf_physics_step`) |
| Coroutine / timer | a frame-counter byte you decrement |
| `Time.deltaTime` | does not exist — the frame is 1/60 s |
| Asset import pipeline | `tools/png2snes.py` (≤15 colors, hardware sizes) |
| Hot reload / inspector | MesenRunner memory reads + screenshots (`/inspect`) |

## Collision: rectangles and tiles, not physics engines

The modern reflex: colliders, rigidbodies, raycasts, collision matrices.

Here: two primitives cover the 16-bit genre space —
- `col_box` — integer AABB overlap between two rectangles (hits, pickups,
  hurt boxes).
- `col_map` + flagged tiles — "is this pixel inside solid terrain?" The
  platformer probes its corners against the tile grid (`sf_solid_box`).

Movement is move-check-commit per axis at ≤8 px/frame (faster tunnels
through 8px tiles — that's why the kit's tunables assert the bound). Gravity
+ jumping is ~20 lines of 8.8 integration (`sf_physics_step`), not a physics
engine, and that's a feature: it's deterministic, cycle-cheap, and tunable to
the pixel.

## Audio (when you get there)

No `AudioSource.Play()`. The SNES has a second computer (the SPC700 + DSP)
with 64 KB of its own RAM; music and SFX are sequenced from short looped
samples uploaded at boot. Audio lands in a later phase of this kit — the
mindset to pre-load: samples are a budget, not files you stream.

## How to use this kit without fighting the machine

1. **Route through the macro library** (`lib/macros/`) — the hardware
   sequencing (blank windows, shadow commits, width discipline, OBJ VRAM
   grid) is baked in so generated code is right by construction.
2. **Design in hardware units:** pixels, tiles, frames, palette slots, pool
   slots. If a design needs floats, per-pixel drawing, or unbounded object
   counts, redesign it in those units first — the redesign is usually
   simpler than the original.
3. **Verify on the emulator, by reading real output** — OAM/VRAM/screenshot,
   not intuition (`AGENTS.md`, Engineering rigor).
4. When stuck on a symptom, `docs/troubleshooting.md` is symptom-indexed.
