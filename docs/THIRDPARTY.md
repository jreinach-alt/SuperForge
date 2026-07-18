# Third-Party Notices

This kit incorporates work from the third-party sources below. This file
consolidates license, attribution, and modification notices. Per-file
notices in the affected source files remain authoritative; this file is a
convenience summary. See also `NOTICE` (vendored-component provenance) and
`LICENSE` (per-component license map).

---

## Brad Smith / rainwarrior — `dizworld`

**Source:** https://github.com/bbbradsmith/SNES_stuff/tree/main/dizworld
**Author:** Brad Smith (rainwarrior) — https://rainwarrior.ca
**License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
https://creativecommons.org/licenses/by/4.0/
**Original license text** (from `dizworld/readme.md`):

> "This program was written by Brad Smith. Its source code is made freely
> available under the the terms of the Creative Commons Attribution
> license: CC BY 4.0. This means that you may reuse and modify this code
> as long as you give credit to its original author."

### What we use

The Mode 7 perspective renderer is a transliteration of Brad's
`pv_rebuild` + `pv_set_origin` + supporting routines from `dizworld.s`. The
following files contain derivative or vendored content:

| File | Relationship | Modifications |
|------|--------------|---------------|
| `engine/mode7_pv_ztable.inc` | Verbatim vendor | Unmodified. Copied `pv_ztable` data block from `dizworld.s` L1722-1850. Surrounding comment headers are kit additions. |
| `engine/mode7_hdma.asm` | Derivative (modified transliteration) | Routine names lost trailing underscores (`_full_` → `_full`); anonymous branch labels (`:+`/`:-`) replaced with named labels; ZP-relative operand syntax replaced with absolute addressing against the kit engine state; entry-point renames for engine integration; additive HDMA channel bitmask OR vs Brad's unconditional write; single-buffered HDMA tables vs Brad's double-buffering. Algorithm + byte-exact numeric output unchanged on the Mode Y fast path. |
| `engine/mode7_math.asm` (group 2 routines only) | Derivative (modified transliteration) | DP scratch mapped to the kit's `$B0-$CF`; `sincos` uses the kit's 512-entry sine LUT via byte-offset conversion instead of Brad's 256-entry table. Algorithm unchanged. Group 1 (`lut_multiply_8bit`, `lut_multiply_16bit`) is original kit code, not derivative. |

### Attribution statement

"This work includes portions of `dizworld.s` by Brad Smith (rainwarrior),
licensed CC BY 4.0. The `pv_ztable` reciprocal-distance LUT is used
unmodified; `pv_rebuild`, `pv_set_origin`, their supporting math helpers,
and the per-scanline variant routines are modified transliterations. See
per-file notices for specific modification details."

### Line-range correspondence

For anyone cross-referencing against Brad's source (line numbers match
the `main` branch of `bbbradsmith/SNES_stuff` as of the port preflight):

| Routine | Brad's lines | Kit location |
|---------|--------------|--------------|
| `pv_rebuild` | L1886-2454 | `engine/mode7_hdma.asm::pv_rebuild` |
| `pv_set_origin` | L2767-2832 | `engine/mode7_hdma.asm::pv_set_origin` |
| `pv_abcd_lines_full` | L2456-2567 | `engine/mode7_hdma.asm::pv_abcd_lines_full` |
| `pv_abcd_lines_sa1` | L2569-2637 | `engine/mode7_hdma.asm::pv_abcd_lines_sa1` |
| `pv_abcd_lines_angle0` | L2639-2689 | `engine/mode7_hdma.asm::pv_abcd_lines_angle0` |
| `pv_interpolate_2x`, `_4x` | L2691-2765 | `engine/mode7_hdma.asm::pv_interpolate_{2x,4x}` |
| `pv_ztable` | L1722-1850 | `engine/mode7_pv_ztable.inc` |
| `pv_buffer_x` | L1873-1883 | `engine/mode7_hdma.asm::pv_buffer_x` |
| `umul16`, `smul16`, `smul16_u8`, `udiv32`, `sign`, `sincos` | (scattered throughout dizworld.s math section) | `engine/mode7_math.asm` group 2 |

### Dizworld visual assets — not incorporated

`dizworld/readme.md` also credits the demo's visual assets to CC BY 4.0 /
CC BY 3.0 sources on OpenGameArt.org. **This kit does not ship any of
dizworld's visual assets.** The Mode 7 demos use the kit's own assets,
which have their own provenance.

---

## Terrific Audio Driver (TAD)

**Source:** https://github.com/undisbeliever/terrific-audio-driver
**Author:** Marcus Rowe (undisbeliever)
**License:** zlib

The ca65 API (`lib/tad/tad-audio.s`, `lib/tad/tad-audio.inc`) is vendored
into this kit with headers intact. See `lib/tad/README.md` and `NOTICE`
for the vendored commit and the compiled example-song blob's provenance
(the generated wrapper is Unlicense; the SPC700 loader + driver binaries
are zlib, same upstream).
