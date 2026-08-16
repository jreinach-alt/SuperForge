---
name: inspect
description: Observe actual SNES hardware state through SuperForge's lockstep Machine — read OAM (sprites), VRAM (tiles/tilemaps), CGRAM (palette), WRAM (game state), capture a screenshot at an exact frame, drive the pad. The verification workhorse; reach for it BEFORE reading asm to chase a bug.
---

Observe hardware **ground truth** instead of reasoning from source. A 5-line
OAM dump beats 500 lines of tracing, and CLAUDE.md rule 1 makes it the rule:
build → `.sfc` → emulator → read memory → assert. **Measure; never estimate.**

## The shape

```python
import json, sys
from pathlib import Path
sys.path.insert(0, "vendor")
from machine import Machine, MemoryType

MAP = json.loads(Path("build/maze/symbol_map.json").read_text())

def sym(name, scene="room"):            # tests/test_maze.py:72 is canonical
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    return next(p for p in pool if p["sym"] == name)

with Machine("build/maze.sfc") as m:
    m.advance(120)                              # exactly 120 emulated frames
    m.advance(60, pad1={"right": True, "b": True})
    oam  = m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)
    cg   = m.read_bytes(MemoryType.SnesCgRam, 0, 512)
    vram = m.read_bytes(MemoryType.SnesVideoRam,
                        sym("ES_V_MZ_MAP")["start"] * 2, 2048)   # words -> bytes
    shadow = m.read_bytes(MemoryType.SnesWorkRam,
                          sym("ES_OAM_SHADOW", scene=None)["start"], 544)
    m.screenshot("/tmp/probe.png")
```

`MemoryType`: `SnesWorkRam`, `SnesSaveRam`, `SnesVideoRam`, `SnesSpriteRam`,
`SnesCgRam`, `SpcRam`.

## Four rules that make the observation worth having

1. **NEVER free-run.** `Machine` is a pure function of (ROM md5, power-on seed,
   input script) and every read comes from a **parked, exact frame**. Advance in
   emulated frames — `advance(n, pad1=…)` — or bound a wait with
   `run_until(pred, max_frames=N)`. A read taken off a free-running core is a
   read at an unknown time, and two of those disagree for reasons that have
   nothing to do with the bug you are chasing. On the legacy free-running
   harness (`vendor/mesen_runner.py`) the equivalents are `wait_frames` /
   `wait_until`, and **`boot_to_frame(rom, N)` when the picture is the answer**
   — `boot_rom(frames=N)` lands on `>= N`, which moved a track far enough to
   flip an assertion 2 runs in 6 under load.
2. **Addresses come from the emitted map, never a literal.** This is not style:
   the allocator owns every address, `allocator/no_literals.py` refuses a raw
   one in engine ASM, and a probe that hardcodes `$7E0123` asserts against an
   address the next allocation may not use. The map's top level is
   `spaces` / `globals` / `scenes` / `spc_owner`; `globals` and each scene's
   `placements` are **lists of records** (`{"sym", "kind", "class", "start", "size",
   "scope", "consumer"}`), so you search them, you do not index by name — hence
   the `sym()` helper above. **Units bite**: a `vram` `start` is in **words**
   (×2 for a byte address), a `wram` `start` is an **offset** from
   `spaces.wram_base_addr` (`0x7E0000`) and `SnesWorkRam` reads take that same
   offset. Getting it wrong yields a plausible wrong address, not an error.
3. **`advance` latches BOTH pads, and OAM lags one frame.** Every button not
   named is released, on both pads, every call. A press's WRAM effect shows in
   that call's readback; its **OAM effect one advance later** — that is the park
   point, not a race. Allow one settle frame before reading an exact delta.
4. **Both power-on RAM and the seed are real.** RAM is random at boot by
   design (CLAUDE.md rule 5) — `Machine` seeds it deterministically so a probe
   reproduces, but a byte you never wrote is garbage on purpose. If a value
   looks wrong, check whether anything initialised it before blaming the code
   that read it; `m.get_uninitialized_reads()` answers that directly.

## Which region holds the answer

| symptom | read |
|---|---|
| sprite missing / misplaced / flickering | **OAM** — positions, tile numbers, and the hi-table (X9 bit + size, 2 bits per sprite) |
| wrong tiles, wrong BG, garbage graphics | **VRAM** — CHR and tilemap; compare against the source bytes, not against what it should look like |
| wrong colours, a black band, a wash | **CGRAM** — and remember word 0 is the backdrop |
| game logic / state / a counter | **WRAM** at an emitted `ES_*` address |
| audio | **SpcRam** |
| **layer priority, colour math, parallax, windows** | **the screenshot.** Single-layer bytes can be perfectly correct while the picture is wrong — this is the one class where a byte read cannot answer |

## Reading a screenshot

Frames come back **256×239**, and the active picture is **224 lines starting at
PNG row 7** (`tests/frame_geometry.py` — `PICTURE_TOP`, `PICTURE_LINES`,
`REAL_Y_BIAS`; measured, not assumed). So a screenshot row is **not** a game
scanline. Locate the feature (scan for its colour, take a centroid) rather than
asserting a thin band at an exact Y, and when you do count pixels over a
region, **check the population is the feature's** — a whole-band count once
attributed 93.6 % of its "kerb white" to the start-line chequer.

Mesen expands BGR555 at full brightness as `(v << 3) | (v >> 2)` per channel.

## Two kinds of question — do not mix them up

- **"What does the machine do?"** — a bug, a cycle count, a wrong pixel →
  **this skill**. Reading ASM to reason it out is the slow, wrong path.
- **"What do our own tools do?"** — does this claim occupy a channel, what does
  this gate check, is this asset what its licence says → **open the implementing
  file.** It is deterministic and it is in this repo. A comment, a doc's count,
  a `feature.toml` note or a licence shipped beside an asset is *secondary* —
  usually right, and not evidence. Three assertions in one session were wrong
  exactly this way, each caught by someone else.

## And the emulator is not the bug

Before claiming a quirk you must do **all four**: reproduce on bsnes, read the
Mesen2 source (`/tmp/Mesen2/Core/SNES/`), cite a shipping game, and name the
exact hardware mechanism. Can't do all four → it is your code. Say *"I don't
understand this yet"* — the honest framing leads to the bug; the lazy one
buries it.
