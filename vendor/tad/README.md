# `vendor/tad` — Terrific Audio Driver ca65 API (vendored, **MODIFIED**)

Two files from https://github.com/undisbeliever/terrific-audio-driver
(`audio-driver/ca65-api/`), © Marcus Rowe, **Zlib licence** — SPDX headers
intact.

> **THIS IS AN ALTERED VERSION OF TERRIFIC AUDIO DRIVER, NOT THE ORIGINAL.**
> Zlib licence clause 2 requires an altered source to be plainly marked as
> such, so it is marked here, in `docs/92_provenance_audit.md`, in the header
> of each patch under `patches/`, and inside the changed code itself. Do not
> report behaviour of this build to upstream as if it were theirs.

**Based on upstream commit `822164b` = `v0.3.0-48-g822164b`**, fetched fresh
from upstream on 2026-07-30 — a copy of a copy is not a provenance source, so
the bytes came from the project that publishes them.

| file | sha256 AS VENDORED (upstream, before our patches) | sha256 NOW |
|---|---|---|
| `tad-audio.inc` | `63782062d67c735ca2baa2c75c06413f222e6b8dd420b73a59ba6225befff088` | `bb11cd307d75d6f4e16634869a30ff3b14ccf7202204368ad1aa9af77ced23e7` |
| `tad-audio.s` | `3ee69484c61f831201031721982ac91dacbbca3d72b634b63cea1a1844a1c822` | `9601af881f71da718e0428b73b0fa04138ea684e9f96f3dbd1d270a0f97f8152` |

Both columns are kept: the first is the provenance claim (these bytes came
from upstream), the second is what is on disk (and differs, deliberately).

## The fork, and why it exists

**`patches/0001-set-channel-detune.patch` adds ONE IO command to the driver:
`SET_CHANNEL_DETUNE` (command 22).** Upstream has no way to change a sound
attribute from the S-CPU while it is playing — every one of its eleven
commands is global (volumes, pause) or per-song (timer, channel mask). There
is no per-voice pitch control, so nothing driven by game state — an engine
note tracking speed, a doppler, a siren — can be expressed at all.

**What the patch does NOT add is the mechanism.** The driver already stores
`channelSoA_detune_l/h`, "an i16 VxPITCH offset added to every play_note or
portamento instruction", and already applies it. It was reachable only from
song bytecode (`set_detune`, MML `D`). The patch adds a doorway to a room
that was already built: the command packs a channel index and a 13-bit signed
detune into the two parameter bytes the IO protocol already carries, and
writes the two bytes the channel already has.

The protocol had room: the command field is 4 bits, so 16 slots, of which
upstream uses 11. This takes slot 22; 24, 26, 28 and 30 remain free.

**Checked before forking, so the cost was known:** upstream at v0.4.2 — 96
commits past our pin — still has `TAD_IO_VERSION = 20`, `N_COMMANDS = 11` and
the same eleven commands. This is a design boundary upstream, not a version
lag, so bumping the pin would not have bought it.

**`TAD_IO_VERSION` is bumped 20 → 21 by the patch, and that is the safety
property that makes the fork carryable.** `tad-audio.s` exports the version
and the generated `tad_audio_data.asm` link-asserts against it, so a driver
and an API that disagree REFUSE TO LINK, by name. Rebuilding the export with
an unpatched compiler produces exactly that error rather than a subtly wrong
ROM. It was observed doing so during the port.

## Rebuilding the patched driver

The export under `assets/audio/export/` is checked in, so this is only needed
when the driver itself changes.

```bash
git clone https://github.com/undisbeliever/terrific-audio-driver.git /tmp/tad
git -C /tmp/tad checkout 822164b
git -C /tmp/tad apply /path/to/vendor/tad/patches/0001-set-channel-detune.patch
# the SPC700 assembler is a crate INSIDE that repo — no external toolchain
make -C /tmp/tad/audio-driver              # -> audio-driver.bin (3,244 B)
cargo build --release --manifest-path /tmp/tad/Cargo.toml -p tad-compiler
```

`tad-compiler` embeds `audio-driver.bin` via `include_bytes!`, so the export
carries the patched driver. The compiler has its own `assert!(TAD_IO_VERSION
== 21)` (patched from 20) — a third place the version mismatch is caught, and
it fails the Rust build rather than producing a bad blob.

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
