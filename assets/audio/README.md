# `assets/audio` — audio content (TAD project + checked-in export)

The demo song, sound effects, samples, and the `tad-compiler ca65-export`
artifacts the ROM actually embeds. **The export is checked in** — the build
never compiles Rust, and regeneration is a documented one-command local step
(see below).

## Provenance — every sample is procedurally generated

**No external or reference sample material is used anywhere in here** (owner
directive, 2026-07-30). All four wavs under `samples/` are synthesised,
deterministically, by [`tools/gen_audio_samples.py`](../../tools/gen_audio_samples.py)
— fixed-seed Karplus-Strong pluck, single-cycle triangle and 25 % pulse,
and a filtered-noise footstep. Re-running the tool reproduces the wavs
byte-for-byte:

```bash
python3 tools/gen_audio_samples.py assets/audio/samples
```

The song (`mml/slice_b_song.mml`) and the SFX (`sound-effects.txt`) are
authored in this repo. Licence: this directory is SuperForge project content;
the *generated* `export/tad_audio_data.asm` carries tad-compiler's own
Unlicense header, and the loader/driver binaries embedded in
`export/tad_audio_data.bin` are Terrific Audio Driver code (Zlib, © Marcus
Rowe) — see `vendor/tad/README.md` for the pin.

## Regenerating the export

Required whenever the project, a sample, the song, or the SFX change.
Build `tad-compiler` once from the vendored pin (`822164b`; ~2 min):

```bash
git clone https://github.com/undisbeliever/terrific-audio-driver.git /tmp/tad
git -C /tmp/tad checkout 822164b
cargo build --release --manifest-path /tmp/tad/Cargo.toml -p tad-compiler
```

Then, from `assets/audio/`:

```bash
/tmp/tad/target/release/tad-compiler ca65-export --lorom \
    --segment AUDIO_DATA0 \
    -a export/tad_audio_data.asm \
    -b export/tad_audio_data.bin \
    -i export/tad_audio_enums.inc \
    slice_b.terrificaudio
```

Commit all three outputs together — the `.asm` carries size asserts against
the `.bin` and a `TAD_IO_VERSION` link-assert against `vendor/tad/`
`tad-audio.s`, so a partial update refuses the build.

## Design notes that live in the content

- **Echo delay is CONSTANT (128 ms, `#EchoLength` = max)**: at the pin the
  compiler structurally refuses `set_echo_delay` inside a sound effect
  (`crates/compiler/src/bytecode.rs:3180` — an SFX cannot know its host
  song's `max_edl`), so per-room reverb is EVOL/EFB re-shaping of one
  fixed 16 KiB buffer. This also removes the `\edl` glitch/settle hazard
  entirely. (Corrects `` §2.4's reading that `set_echo_delay` was
  SFX-usable — see the erratum note there.)
- Room A (boot default, in the song header): `EVOL 12, EFB 24`. Room B
  (`room_b_ambience` SFX): `EVOL 70, EFB 96`. Room A's SFX restores the
  header values exactly.
- Bar 8 of the song is a deliberate near-silence — the audibility test's
  window for hearing the tail difference between rooms.
- `#Tempo 70`; SFX tick clock is the default `8000/100` Hz timer.
