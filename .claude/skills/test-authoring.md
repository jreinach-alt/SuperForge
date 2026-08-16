---
name: test-authoring
description: Write or review a test that proves a rendering / VRAM / OAM / CGRAM / audio feature works on SuperForge's lockstep harness. Enforces CLAUDE.md rule 2 — assert on the rendered output, never a proxy variable, never against the host clock. Trigger when adding or reviewing a test for any hardware-facing feature.
---

**Parent rule: CLAUDE.md #2.** A test reads the **actual output the feature
produces** — VRAM / OAM / CGRAM bytes or screenshot pixels — never a variable
that "should" reflect it, and never on a schedule set by the host clock. A
proxy-variable test passes while the feature is silently broken; that is
**worse than no test**, because whoever ships does so trusting it.

## The harness — `Machine`, and when it is not the answer

`vendor/machine.py` is the lockstep substrate. It is a **pure function of (ROM
md5, power-on seed, input script)** and every read comes from a parked, exact
frame.

```python
from machine import Machine, MemoryType

with Machine("build/racer.sfc") as m:      # seeded power-on RAM, parked
    m.advance(90)                          # exactly 90 emulated frames
    m.advance(30, pad1={"right": True})    # both pads LATCHED, stated
    oam = m.read_bytes(MemoryType.SnesSpriteRam, 0, 544)
    m.screenshot("/tmp/f.png")
```

1. **`advance(n, pad1=…, pad2=…)` latches BOTH pads.** Every button not named
   is **released**, on both pads, always. There is no "still held from last
   call" — say what is held, every call.
2. **`run_until(pred, max_frames=N, what=…)` is bounded in EMULATED frames**,
   and `pred` must read **output** state, same discipline as an assertion.
3. **`advance` has a one-frame presentation lag.** A press's effect on WRAM is
   visible in that call's own readback; its effect on **OAM is one advance
   later** — that is the park point, not a race. Allow one settle frame before
   asserting an exact OAM delta.
4. **Legacy `MesenRunner` (`vendor/mesen_runner.py`) is the free-running
   harness** and still backs many modules. There, wait in emulated frames —
   `wait_frames(n)` / `wait_until(pred, max_frames=N)` / `run_to_break(
   max_frames=…)` / `boot_rom(rom, frames=N)` — and **when the PICTURE is the
   assertion use `boot_to_frame(rom, N)`**, which free-runs most of the boot
   and STEPS the last 20 frames so every host photographs frame N *exactly*.
   `boot_rom(frames=N)` lands on `>= N`: measured here, a fixed free-run budget
   landed on 90/91/92 under contention against a flat 91 idle, and those two
   frames failed a scanline-223 assertion 2 runs in 6.
5. **`run_frames(n)` sleeps n/60 WALL seconds** beside a core on its own
   thread: ~4× its argument free-running and **zero** on a parked runner. Two
   tests once asserted over nothing and passed. `make time-check` refuses new
   ones; the only way past is `# WALL-CLOCK: ok — <reason>`, the reason is
   REQUIRED, and a bare stamp is itself a finding.
6. **Audio is the one real carve-out** — a WAV is a recording of real time, so
   those runners stay wall-clock and throttled to 60 fps by construction. State
   it that way, not as an exception.
7. **Hand the core back.** It is a process-global singleton; a module that
   parks it and ends strands the next module's runner, and the red lands on the
   victim. `with Machine(...)` and `with runner.frame_stepping():` both restore
   on the way out, including through a failed assertion.

## Addresses come from the emitted map — never a literal

SuperForge's whole premise is that you do not allocate, you declare. **The same
applies to a test.** Read `build/<rail>/symbol_map.json` and index it by symbol
name; a hardcoded `$7E0123` in a test is the identical defect
`allocator/no_literals.py` refuses in engine ASM, one layer up, ungated.

The map's shape — **read it, do not guess it**; the top level is
`spaces` / `globals` / `scenes` / `spc_owner`, and `globals` and each scene's
`placements` are **lists of records**, not dicts:

```python
MAP = json.loads((BUILD / "maze" / "symbol_map.json").read_text())

def _sym(name, scene="room"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")

V_CHR = _sym("ES_V_MZ_CHR")["start"]                  # VRAM *words*
shadow = _sym("ES_OAM_SHADOW", scene=None)["start"]   # WRAM, offset from…
base   = MAP["spaces"]["wram_base_addr"]              # …0x7E0000
```

`tests/test_maze.py:72` is the canonical `_sym`. Note the units: a `vram`
placement's `start` is in **words**, a `wram` one is an **offset** from
`spaces.wram_base_addr`, and `MemoryType.SnesWorkRam` reads are offsets too —
mixing those up produces a plausible wrong address rather than a KeyError.

A module-scope map read is checked by `tests/conftest.py`'s freshness guard —
it re-emits the map and compares BYTE FOR BYTE, so "STALE" means exactly "the
committed map differs from what today's declarations produce". If you add a
rail whose module reads its map at collection time, register it in
`conftest.MAPS` **and** `conftest._SUBDIR_MAP` (`make rail-registered` names
the site; missing the second is silent and points at the toy map).

## Writing the test

1. **Name the output region** the feature claims to produce: VRAM tilemap/CHR,
   OAM entries, CGRAM words, SPC RAM, or screenshot pixels.
2. **Read that region directly** and assert on those bytes.
3. **Reject proxy assertions.** A program variable that "should" be a function
   of the output is not a test of the output. *(Recorded trap: asserting
   `cam_x > 1024` to "prove streaming fired" — `cam_x` advances every frame
   regardless, and two independent bugs rode that test for a full work item.)*
4. **For a VISIBLE feature the output region is the SCREEN.** OAM/VRAM are
   intermediate state; the player sees pixels. "OAM X increased by 80" and "the
   red square moved 80 px right on screen" are different claims — assert the
   one the feature makes.
5. **Composited features need composited verification.** BG priority,
   sprite-on-BG, colour math, parallax, window masks: a single-layer byte read
   can be perfectly correct while the picture is wrong. Assert a **screenshot
   pixel at a known location**, or a **structural cross-layer invariant** (e.g.
   "BG2 is ≥78 % transparent, so BG1 is not occluded"). A layer relocation also
   needs a **disjointness** assertion, not just "the moved layer has the right
   bytes at its new address".
6. **Compare whole declared state against an oracle, every frame** — not the
   headline value. A per-field check on the headline shipped a real bug here: a
   call added to a branch holding a live index in X silently rewrote a sector
   byte, and the lap counter kept counting correctly, so the obvious assertion
   passed.
7. **Drive whole cycles, BOTH directions, and the idle.** Forward *and*
   reverse *and* stopped; ascent → apex → **landing** → rest; press *and*
   release; every axis of the d-pad. A test that walks the camera one way locks
   that way and ships the other broken — which is exactly how a wall-collision
   bug survived every "comprehensive" streaming test through twelve work items,
   and how an apex-only jump test survived a landing-frame bug that is obvious
   within seconds of playing it.
8. **Tie input to the visible result, end to end.** Drive the *physical* pad
   and confirm the *on-screen* result, so a self-consistent-but-reversed
   mapping cannot pass. "Inject Right → the blob's screen-X increases" catches
   a reversal that "BTN_RIGHT → X += → OAM X +" (all internally consistent)
   does not.
9. **Streaming's full-window invariant is a STOPPED-camera claim.** While the
   camera moves, VRAM trails it by the staging + VBlank-drain lag *by design*.
   Brake or coast to a stop first.

## Prove the test can fail — two separate proofs

**A green test you have not tried to break is not evidence.** `make falsify`
(docs/46) is the harness, and it draws a distinction most hand-rolled plants
lose:

- **The plant must MOVE THE VALUE.** The harness requires the built artifact's
  **md5 to change** before it will believe anything the tests say. A plant that
  never reached the binary is reported as a **failure of the PLANT**, separately
  from a test that could not see a defect that did reach it — opposite findings
  needing opposite responses. Three plants no-op'd silently and one left
  its test GREEN (`shutil.copy2` preserves mtime, so `make` skipped the
  rebuild).
- **Both arms, always.** A gate that refuses everything and one that refuses
  nothing are both constants and both read like verdicts. Pair every
  "planted → RED" with a "healthy tree → GREEN".

A plant set is `tools/plants/<rail>.py` exposing `PLANTS`; `why=` is required by
the constructor, because a plant whose realism nobody stated proves little.

## Attribute the population you counted (the L-5 rule)

When an assertion **counts** pixels over a region, prove the count comes from
the feature under test. `test_the_rumble_strips_show_both_red_and_white`
counted near-white pixels over the whole floor band `y=44..223` against a
threshold of 100 — and **11,067 of 11,825 (93.6 %) came from the start-line
chequer**, not the kerbs. Delete the kerb white entirely and the case still
passes by 110×. The red half *was* specific; the white half tested nothing its
name claimed.

So: **restrict the region to where the feature is** (`y=44..125` yields 758
here), or measure the split and set the threshold against the feature's own
contribution. The test name is a contract — if the name says "the rumble
strips", the counted population has to be the rumble strips.

## When it goes red

1. **Report the determinism triple** — `(rom md5, seed, input script)`. That
   triple *is* the reproduction (docs/53 D-DH3), and you get it two ways:
   `MachineError` prints it on every substrate failure path, and
   `tests/conftest.py` attaches a **`replay triple (lockstep Machine)`** report
   section to any FAILED test that drove a Machine — `Machine._current` plus
   every Machine sitting in the **direct locals** of the failing frames, in that
   order, because a test holding three control trajectories is very likely red
   about one that is not current. `m.triple` is a **property**, not a call.
   *Stated limit: direct locals only — a Machine inside a list, a dict or an
   attribute is not found, and one closed and dropped before the assert is
   gone. Bind it to a local if you want it reported.*
2. **Re-run before believing a flake.** The "same-tree re-run" grace is gone: a
   red on a lockstep node is real on first occurrence, because the four timing
   mechanisms that used to explain flakes were fixed rather than tolerated

3. **Read hardware, don't read ASM.** Dump the region and see the wrong byte —
   that is `/inspect`, and it is faster than tracing. The opposite holds for
   *our own tools*: what the allocator, a gate or a converter does is answered
   by opening the implementing file (CLAUDE.md, "two kinds of question").

**The test name is a contract.** If it claims "streaming under all motion",
"the layer composes", "the asset uploaded", or "the strips show red and white",
the assertion surface must match the claim. Single-axis, single-state,
single-layer, spec-mirror and self-referential assertions are silent-corruption
traps when the claim is broader.

## Capture facts (the three numbers every screenshot assertion needs)

Each is stated by the harness code, at the cited site — re-verify there when a
capture surprises you.

1. **A screenshot costs ONE emulated frame.** The composite holds the
   *previous* completed frame, so bringing the caller's frame in costs an
   advance — paid unconditionally, in both execution modes
   (`vendor/mesen_runner.py` `take_screenshot`: "EXACTLY ONE emulated frame";
   pinned by `tests/test_wait_primitives.py::
   test_a_capture_spends_exactly_one_emulated_frame`). `Machine.take_screenshot`
   keeps the same contract and latches **both pads RELEASED** for that frame
   (`vendor/machine.py`, the stated-state discipline). So count the shot in
   your frame arithmetic — a picture pair meant to sit N frames apart is N−1
   advances plus the shot — and know that a held button is not held through a
   capture.
2. **The PNG carries overscan.** Mesen hands back **256×239**, and the active
   224 picture lines start at **PNG row 7**. The convention is
   `tests/frame_geometry.py`: `PICTURE_TOP = 7`, `png_row(picture_row)`, and
   `REAL_Y_BIAS = 1` (Mesen's `_scanline` is picture row + 1 — measured; the
   module docstring holds the sweep). Sampling `getpixel((x, y))` with a
   picture row for `y` reads seven rows high; go through `png_row()`.
3. **5-bit → 8-bit is BIT REPLICATION: `(c << 3) | (c >> 2)`.** Not `c << 3`
   (up to 7 low per channel — full-scale 31 must map to 255, not 248), and not
   `round(c * 255/31)` (one off at low values: 3 → 24, not 25). Four modules
   define and use it — `tests/test_breaker.py` `_snes8` (whose docstring
   records the arithmetic version failing against the picture),
   `tests/test_platformer.py` `bgr555_to_rgb`, `tests/test_rpg.py`
   `_cgram_rgb`, `tests/test_mode7_flight.py` `_mesen_rgb`. A
   CGRAM-word-vs-pixel comparison through any other expansion is a false red.
