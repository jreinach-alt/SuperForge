# `vendor/tad` — Terrific Audio Driver ca65 API (vendored, unmodified)

Two files from https://github.com/undisbeliever/terrific-audio-driver
(`audio-driver/ca65-api/`), © Marcus Rowe, **Zlib licence** — SPDX headers
intact, contents byte-unmodified.

**Vendored at upstream commit `822164b` = `v0.3.0-48-g822164b`.**
Fetched **fresh from upstream** on 2026-07-30 — a copy of a copy is not a
provenance source, so the bytes come from the project that publishes them, and
the sha256s below are recorded so a later reader can check that claim rather
than take it.

| file | sha256 at vendoring |
|---|---|
| `tad-audio.inc` | `63782062d67c735ca2baa2c75c06413f222e6b8dd420b73a59ba6225befff088` |
| `tad-audio.s` | `3ee69484c61f831201031721982ac91dacbbca3d72b634b63cea1a1844a1c822` |

## What these are, and what is deliberately NOT here

`tad-audio.s` is the S-CPU side of the driver: the loader handshake,
`Tad_Init` / `Tad_Process` / `Tad_LoadSong` and the queue API. It places its
CPU-side state itself — **16 bytes via `.bss` and 2 bytes via `.zeropage`**
— which in this repo land in allocator-pinned claims (the `audio` feature's
`tad_bss` / `tad_zp`; see `engine/features/audio/`). The lderror asserts in
the audio feature's wrapper refuse the build if the linker and the
allocator ever disagree.

The SPC700 loader + driver **binaries** are not here — `tad-compiler
ca65-export` embeds them in the audio-data blob under `assets/audio/`
(loader at offset 0, driver at offset 116, exported as `Tad_Loader_Bin` /
`Tad_AudioDriver_Bin` by the generated `.asm`). Regeneration instructions
live in `assets/audio/README.md`.

## Rules

- **Do not modify these files.** All SuperForge adaptation (memory-map defines,
  segment names, integration asserts) lives in the SuperForge-authored wrapper
  under `engine/features/audio/` — the file that `.include`s `tad-audio.s`.
- These files are outside the `no_literals` scan scope by placement
  (`vendor/` is not in any game's ASM list) — deliberate: they are
  upstream-pinned, not hand-authored engine ASM.
- To upgrade TAD: pick the new upstream commit, re-copy both files, update
  the pin + hashes here, and re-run the audio run-gate — API/driver
  compatibility is proven by the loader handshake + audible-playback test,
  never assumed (`TAD_IO_VERSION` is additionally link-asserted between the
  generated export and `tad-audio.s`).
