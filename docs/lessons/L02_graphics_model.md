# L02 — The graphics model: tiles, tilemaps, palettes, OAM

## The idea

The PPU has no framebuffer. You never draw a pixel; you arrange references to
**tiles**, and the PPU composes the picture live, every frame, from three
small dedicated memories (hardware-reference; sizes below are the hardware's):

- **VRAM (64 KB)** holds two kinds of data. **CHR**: the tiles themselves —
  8x8 pixel patterns, 4 bits per pixel in the common modes, 32 bytes per
  tile. **Tilemaps**: grids of 16-bit entries, each naming a tile plus its
  palette group, flip bits, and priority. A background is a tilemap pointed
  at CHR.
- **CGRAM (512 bytes)** holds the 256 colors, each a 15-bit BGR word. Colors
  act in groups of 16: a 4bpp pixel's value 0-15 selects a color *within its
  group* — and value 0 means transparent, so a "16-color" tile really gets 15.
- **OAM (544 bytes)** holds 128 sprite records: X, Y, tile number,
  attributes. A sprite is not an image — it is a record saying "draw OBJ tile
  N at (X,Y) with palette P". Sprites are how anything moves without
  rewriting a tilemap.

Everything on a SNES screen is one of those two things — background layers or
sprites. The design consequence: your art must *become* CHR + palette data
before the hardware can show it. The kit's converter `tools/png2snes.py` does
exactly that, validation-first: it enforces the hardware's limits loudly
instead of silently mangling art that doesn't fit.

## See it live

First, read all three memories of the running hello_world (L00) and match
them to the source:

```bash
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/hello_world.sfc", run_seconds=2.0)
tile = r.read_bytes(MemoryType.SnesVideoRam, 32, 32)
print("VRAM tile 1:", " ".join(f"{b:02X}" for b in tile))
lo, hi = r.read_bytes(MemoryType.SnesCgRam, 258, 2)
print(f"CGRAM obj pal0 color1: ${hi:02X}{lo:02X}")
print("OAM record 0:", list(r.read_bytes(MemoryType.SnesSpriteRam, 0, 4)))
r.stop()
EOF
```

Observed: the 32 VRAM bytes are the `FF 00` rows of `sprite_tile` from
`main.asm` (OBJ tile N lives at VRAM word N*16 — engine-verified layout, see
`lib/macros/sf_video.inc`); the color reads `$001F` (red); the OAM record is
`[120, 100, 1, 32]`. Source, memory, screen — one chain.

Now the pipeline, end-to-end on real art. The kit ships CC0 packs
(`examples/itch_cc0/`); the shmup's ghost enemy was converted from one.
Reproduce that conversion yourself and diff it against the shipped asset:

```bash
unzip -o -q examples/itch_cc0/dungeonSprites_v1.0.zip -d art/
python3 tools/png2snes.py sprite art/dungeonSprites_v1.0/ghost_/idleWalkRun_ \
    --size 16 --name ghost --out /tmp/ghost.inc
diff /tmp/ghost.inc templates/shmup/assets/ghost.inc
```

Observed: the converter reports `8 frame(s) -> /tmp/ghost.inc (1024 CHR
bytes, 3 colors, 1 animation(s): idleWalkRun)`, and the diff shows exactly
one differing line — the `; cmd:` provenance comment. Byte-identical payload:
the shipped asset is nothing but this command's output. See it rendered:

```bash
make shmup
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner()
r.load_rom("build/shmup.sfc", run_seconds=3.0)
r.take_screenshot("/tmp/shmup.png")
r.stop()
EOF
```

`/tmp/shmup.png` shows the converted hero, ghosts, and terrain in play.

## Exercise

Convert a different animation from the same pack:

```bash
python3 tools/png2snes.py sprite art/dungeonSprites_v1.0/goblinKing_/idle_ \
    --size 16 --name goblin --out /tmp/goblin.inc
```

Verified outcome: `8 frame(s) ... 1024 CHR bytes, 5 colors`, and the emitted
`.inc` carries frame constants plus an animation table, ready for
`sf_load_obj_chr`. Open it — the header comment documents its own load
contract.

## What breaks if…

**…you feed it modern art.** The kit ships a canonical reject fixture —
AI-generated, smooth-shaded, not hardware-scale — precisely to show this:

```bash
unzip -o -q examples/itch_cc0/SNES_overworld_RPG_character_sprite_top-down_persp.zip -d art/
python3 tools/png2snes.py sprite art/rotations --size 16 --name walker --out /tmp/walker.inc
```

Observed, verbatim (first line):

    png2snes: REJECT: 40 distinct opaque colors across 4 frame(s); an SNES OBJ palette holds 15 + transparent.

…followed by the per-frame color census and three options (redraw at SNES
scale, split by palette, or `--auto-fix` quantize — loudly, with a preview
PNG). This is the limitation half of the lesson: 15 colors + transparent per
palette, 8 background palette groups, art authored at hardware scale. No
converter setting removes those walls; they are the platform. If your
instincts are engine-shaped, read
[`../snes_vs_modern_engines.md`](../snes_vs_modern_engines.md) before
fighting them, and the png2snes section of
[`../troubleshooting.md`](../troubleshooting.md) when a conversion rejects.

Next: [L03 — 8/16-bit width](L03_width.md), the CPU trick that corrupts
programs which look correct.
