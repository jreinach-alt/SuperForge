# CLAUDE.md

This repo's agent operating manual is **`AGENTS.md`** — read it first. It defines the two realms (Knowledge / Action), the routing and confidence-tiering disciplines, the engineering-rigor rules, the boundaries, and the map of the repo.

**Claude Code specifics:**

- Skills live in `.claude/skills/` — `/build`, `/inspect`, `test-authoring`. Invoke them by name.
- The lint gates (`width-check` + `zp-check`) run automatically via `.claude/settings.json` hooks after asm edits. `zp-check` (DP-allocation collision gate, `tools/zp_lint.py` against `reports/zp_lint_baseline.json`) needs the materialized `engine/engine_state.inc` for its symbol table; it SKIPs cleanly in the bare staging overlay and runs for real in a materialized kit. New DP state must be declared as an `ES_*` symbol in `engine/engine_state.inc`.
- MesenRunner (`infrastructure/test_harness/`) is the emulator harness — prefer it over reading source to verify behavior (`/inspect`).

Everything else is in `AGENTS.md`.
