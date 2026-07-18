---
name: test-authoring
description: Write or review a test that proves a rendering / VRAM / OAM / CGRAM / audio feature works. Enforces the rule that a test asserts on the real output region, never a proxy variable. Trigger when adding or reviewing a test for any hardware-facing feature.
---

A test must read the **actual output region the feature produces** — not a variable that "should" reflect it. A proxy-variable test passes while the feature is silently broken; that is **worse than no test**, because it manufactures false confidence.

## Writing the test

1. **Name the output region** the feature claims to produce: VRAM tilemap/CHR, OAM entries, CGRAM palette, SPC RAM, or screenshot pixels.
2. **Read that region directly** with MesenRunner (`/inspect`) and assert on those bytes.
3. **Reject proxy assertions.** Asserting on a program variable that "should" be a function of the output is not a test of the output. *(Trap: asserting `cam_x > 1024` to "prove streaming fired" — `cam_x` advances every frame regardless.)*
4. **For a *visible* feature, the output region is the SCREEN — not just the intermediate buffer.** OAM/VRAM bytes are *intermediate state*; the player sees *pixels*. A sprite's `OAM X` increasing proves the engine placed it; it does **not** prove the sprite is visible, the right colour, or moving the right direction on screen. Verify the rendered result: a screenshot pixel/colour at a known location, or the coloured-blob centroid. "OAM moved +80" and "the red square moved 80px right on screen" are different claims — assert the one the feature actually makes. *(This caught a real gap: a move test that only read OAM X passed while never confirming the sprite rendered at all.)*
5. **Composited features** (BG priority, sprite-on-BG, color math, parallax) need more than a single-layer byte read: assert a **composited screenshot pixel** at a known location, or a **structural cross-layer invariant** (e.g. "BG2 is ≥78% transparent so BG1 isn't occluded").
6. **Drive the WHOLE input/state space, not one sample.** Every direction/axis/button the code handles — all four of the d-pad (not just Right and Left), press *and* release, held *and* tapped. Every state transition — jump physics verifies ascent → apex → land (not just apex); streaming verifies forward *and* reverse motion. A test that exercises one direction or one transition silently ships the rest broken. *(Real trap: a move test that checked Right + Left but never Up/Down — the untested axis could be reversed and the test stays green.)*
7. **Tie input to the visible result, end to end.** When validating controls, drive the *physical* input (`set_input`) and confirm the *on-screen* result, so a self-consistent-but-reversed mapping can't pass. "Inject Right → the blob's screen-X increases" catches a reversal that "BTN_RIGHT → X+= → OAM X+" (all internally consistent) would not.

## Harness facts that bite

- **Screenshots are 256×239 — taller than the 224-line game area.** `take_screenshot` includes overscan rows, so screenshot row ≠ game Y (the picture sits a few rows down). Don't assert a thin pixel band at an exact game Y; locate the feature first (centroid / scan for the colour) or use a generous band.
- **`set_input`/`run_frames` are wall-clock, not frame-deterministic.** Input edges land "approximately," so blind choreography (hold N frames, assume position) flakes. For wall-clock tests, write **closed-loop bots**: read OAM each frame and decide the next input from the actual position; assert positions with a small tolerance where an input release races (e.g. respawn checks ±8px). Poll a debug mirror to detect events instead of counting frames to them.
- **Frame-stepped input is the deterministic alternative.** `runner.frame_step(n, **buttons)` latches the full controller state and advances EXACTLY n frames (the emulator parks between steps); `with runner.frame_stepping():` breaks on entry and restores free-running on exit, even through an assertion failure. **Reach for frame-stepping when** the assertion is per-frame-exact (movement deltas, physics traces, byte-identical replay, long scripted rallies — it runs at host speed, no sleeps); **stay wall-clock when** the test only needs coarse outcomes ("moved right", "event happened within 5 s") or exercises real-time pacing itself. HAZARDS: (1) while parked, `run_frames` is a useless sleep and a wall-clock test sharing the runner sees a frozen machine — always restore free-run before handing off (the context manager does); (2) at the park point OAM/VRAM hold the *previous* boundary's DMA (a constant one-frame lag vs WRAM) and a latched button reaches WRAM state on the next step — allow one settle step before asserting exact deltas. See `tests/test_frame_step.py` (the determinism gate) and the breaker win gate for working patterns.
- **BG3 text-layer constants** (for asserting on `print`/`sf_print_u16` output): the BG3 tilemap lives at VRAM **byte** address `0xC000` (word $6000); cell (tx,ty) is at `0xC000 + (ty*32 + tx)*2`; a glyph's tile word is `0x3C00 | (160 + ord(ch) - 0x20)` (font base 160, palette 7, priority bit set).

## Helpers

The canonical assertions (`assert_screenshot_pixel`, `assert_oam_entry`, `assert_cgram_palette`, `assert_vram_region_distinct`, `drive_state_cycle` in `infrastructure/test_harness/visual_assertions.py`) make this cheap — use them when they fit.

**The test name is a contract.** If it claims to verify "streaming under all motion," the assertion surface must match the claim — not a proxy that happens to track it.
