# Contributing

## The hard rules (CI-enforced)

1. **No copyrighted content, ever.** No commercial ROMs, no game-music rips,
   no commercial sample-pack recordings, no extracted commercial sprites or
   tiles, no all-rights-reserved reference docs. The clean-room gate
   (`tools/cleanroom_check.sh`) blocks commercial names, forbidden file
   classes (`.sfc`, `.rsn`, `.spc`, emulator cores), and oversized media —
   it runs in CI and must stay green.
2. **Assets must be CC0/public-domain with provenance recorded.** New art or
   audio source material goes in `examples/itch_cc0/` (or a sibling dir) with
   an entry in its `LICENSES.md`: author, source URL, license, date.
3. **"Make it look like [a commercial game]" means reproduce the technique
   with original art** — never copy, extract, or rip an asset.

## The quality bar

- **Everything is verified on the emulator.** A change isn't done because it
  assembles — `make check` (width gate + build + full suite) must pass, and
  new features need a test that asserts on real hardware output (OAM, VRAM,
  CGRAM, screenshot, recorded audio), not a proxy variable.
- **Width discipline.** 65816 width mismatches are the platform's #1 silent
  corruption bug. The `width-check` gate runs over every `.asm`/`.inc`; new
  macros document their entry/exit width contract (`; WIDTH-RISK:` header).
- **The macro library is the front door.** New capabilities ship as macros
  with the landmines baked in, plus a template or example that proves them.

See `AGENTS.md` for the full engineering-rigor rules — they apply to human
contributors too.
