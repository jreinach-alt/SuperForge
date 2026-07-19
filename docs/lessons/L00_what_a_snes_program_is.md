# L00 — What a SNES program is

## The idea

A SNES program is not an app. There is no operating system, no loader, no
runtime: a cartridge is a block of bytes wired into the CPU's address space,
and at power-on the CPU reads a 16-bit address from a fixed location — the
**reset vector** at `$FFFC` — and starts executing whatever it points at.
Everything else (title, sizes, interrupt handlers) lives in the last 64 bytes
of that first bank: 32 bytes of **header**, then the **vector table**.

From reset, your code owns the machine. Nothing is initialized for you — RAM
holds random garbage at power-on (hardware-reference; the kit's emulator runs
randomize it on every boot so tests catch code that secretly relied on zeros).
So every game has the same skeleton: initialize once (clear RAM, load
graphics, turn the screen on), then fall into an endless loop paced by the
**NMI** — an interrupt the video chip fires once per frame, ~60 times a
second. A game is: set up, then answer 60 interrupts per second, forever.

`examples/hello_world/main.asm` is that whole story in ~80 lines: coldstart,
load one tile and one color, screen on, then a `game_loop` that places one
sprite per frame. Lesson L01 dissects the loop; here we prove the skeleton.

## See it live

From the kit root (after `bash tools/setup.sh`):

```bash
make hello_world
ls -l build/hello_world.sfc
```

The ROM is **exactly 32768 bytes** — the entire cartridge, one 32 KB bank.
Look at the header and the reset vector inside it (in this kit's LoROM link
shape, file offset `$7FC0` is CPU address `$FFC0` — engine-verified):

```bash
od -A x -t x1z -j 0x7FC0 -N 32 build/hello_world.sfc
od -A x -t x1  -j 0x7FFC -N 2  build/hello_world.sfc
```

The first dump shows the 21-byte title field (this example ships the kit
default) plus map mode `$30` (LoROM+FastROM). The second is the reset vector:
`a7 84` — little-endian for `$84A7`, which is exactly where the linker placed
this ROM's `RESET:` label (engine-verified: rebuild with `ld65 -Ln` and the
symbol dump shows `0084A7 .RESET`, `008000 .NMI`). Now boot it on the
cycle-accurate emulator and read the hardware:

```bash
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/hello_world.sfc", run_seconds=2.0)
print(bytes(r.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4)))  # boot marker
x, y, tile, attr = r.read_bytes(MemoryType.SnesSpriteRam, 0, 4)
print(f"sprite 0: X={x} Y={y} tile={tile}")
r.take_screenshot("/tmp/hello.png")
r.stop()
EOF
```

Observed output: `b'SFDB'` (the ROM reached its main loop and said so) and
`sprite 0: X=120 Y=100 tile=1` — the values `main.asm` passes to `spr`. Open
`/tmp/hello.png`: a red 8x8 square near screen center on black. That is the
full chain — source → ROM → reset vector → init → frame loop → pixels.

## Exercise

Colors are 15-bit BGR words (L02 explains). In `examples/hello_world/main.asm`
change the equate `OBJ_RED = $001F` to `$03E0`, rebuild, and re-run the probe
above with this extra read:

```python
lo, hi = r.read_bytes(MemoryType.SnesCgRam, 258, 2)
print(f"color = ${hi:02X}{lo:02X}")
```

Verified outcome: the color memory reads `$03E0` and the square is green.

## What breaks if…

**…you skip initialization.** The classic SNES failure: a ROM that works on a
zero-filling emulator and shows garbage — or crashes — on real hardware,
because it read RAM, VRAM, or a PPU register it never wrote. The kit's stance
is to make that bite early: MesenRunner boots with power-on RAM randomized, so
"forgot to init" fails your first test run, not your first console test.
`sf_coldstart` exists to make the defined-baseline path the easy path.

**…the ROM never reaches the loop.** Black screen, and the probe above prints
`b'\x00\x00\x00\x00'` or random bytes instead of `b'SFDB'`. That marker is the
first triage fork: no magic means you crashed in init, magic-but-no-render
means the PPU setup is wrong. Work the probe ladder in
[`../troubleshooting.md`](../troubleshooting.md) ("Boots wrong / shows
nothing") instead of staring at source.

**…you trust screenshot pixel coordinates blindly.** The emulator's screenshot
is 256x239 with the 224 visible lines vertically offset (~7 rows) — our square
sits at OAM Y=100 but its pixels start at row 107 in the PNG. Assert on OAM or
on found-pixel positions, not on hardcoded screen rows; see
[`../troubleshooting.md`](../troubleshooting.md) ("Screenshot pixels read
black/garbage at the top rows").

Next: [L01 — The frame](L01_the_frame.md), where the 60-per-second heartbeat
becomes your clock and your budget.
