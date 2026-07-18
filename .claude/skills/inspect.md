---
name: inspect
description: Observe actual SNES hardware state via MesenRunner — read OAM (sprites), VRAM (tiles/tilemaps), CGRAM (palette), WRAM (game state), capture screenshots, inject input. The verification workhorse. Works on ANY .sfc, however it was built.
---

Observe hardware **ground truth** instead of reasoning from source. Lead with this to verify a feature or trace a bug.

Use MesenRunner (`infrastructure/test_harness/mesen_runner.py`):

1. **Load:** `runner.load_rom("build/x.sfc", run_seconds=...)`.
2. **Read the region that holds the answer:**
   - **Sprites wrong / missing / flickering?** OAM (`MemoryType.SnesSpriteRam`) — positions, tile numbers, and the X9 / size hi-table.
   - **Tiles or BG wrong?** VRAM (`SnesVideoRam`) — CHR + tilemap.
   - **Colors wrong?** CGRAM (`SnesCgRam`).
   - **Game state / logic?** WRAM (`SnesWorkRam`) — the debug region + engine state.
3. **Screenshot** (`take_screenshot`) — the final composited image is the truth for layer-priority, color-math, and parallax features that single-layer byte reads can't confirm.
4. **Inject input** (`set_input` / `run_frames`) and re-read to test responses.

This is **tool-agnostic** — it reads the hardware, so it works on a ROM you built or one a user brings (AGENTS.md → Boundaries). Reach for it *before* reading asm to chase a bug: a 5-line OAM dump beats 500 lines of tracing.
