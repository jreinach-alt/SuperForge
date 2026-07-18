---
name: build
description: Build a SuperForge ROM from 65816 asm source via ca65/ld65 and report the result honestly. Use when asked to build, assemble, or check that asm changes assemble.
---

Build a ROM and report the result honestly. A ROM that links is **not** yet "working" — that's `/inspect`.

## Steps

1. **Prefer the Makefile:** `make <target>` assembles + links in one step with the correct linker config. For a one-off: `ca65 -I infrastructure/rom_template <file>.asm` then `ld65 -C <config> ...` (configs in `infrastructure/rom_template/`).
2. The engine and the macro library are pulled in via the include path — you don't re-implement them.
3. **On error:** report the exact `ca65`/`ld65` message and the `file:line`. **Fix assembler/linker errors before anything else** — they're real bugs, not noise. Don't guess at a fix; read the message.
4. **On success:** the `.sfc` lands in `build/`. Verify it under MesenRunner before calling it done.

## Common failures

- **Width error** — a CPU 8/16-bit mismatch (`A9 01` assembled as a 16-bit immediate, etc.). The platform's most common silent-corruption bug; see AGENTS.md → Rigor. The macros prevent most by construction.
- **Segment placement** — code assembled into the wrong segment builds fine but crashes at runtime. Check the `.segment` directives.
- **Missing include / undefined symbol** — a wrapper or macro not on the include path.
