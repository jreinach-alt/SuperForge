# `assets/audio` — audio content (TAD project + checked-in export)

The demo song, sound effects, samples, and the `tad-compiler ca65-export`
artifacts the ROM actually embeds. **The export is checked in** — the build
never compiles Rust, and regeneration is a documented one-command local step
(see below).

## Provenance — every sample is procedurally generated

**No external or reference sample material is used anywhere in here** — a
hard provenance rule for this tree. All four wavs under `samples/` are synthesised,
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

## The sound-effect vocabulary

Fourteen effects, shared by every rail that composes `audio`. Sharing is the
architecture working, not a compromise: there is ONE export blob for the whole
tree, so an effect authored for one rail is linked into all of them — `laser`
is the shmup's gun and the saucer arena's, and neither pays for the other's.

| effect | what it is for | voice |
|---|---|---|
| `room_a_ambience` / `room_b_ambience` | `room`'s per-space reverb (EVOL/EFB only) | echo, no note |
| `beam_fire` / `beam_end` | the saucer arena's beam: an echo swell AND a tone, in ONE effect | `saw` / `tri_bass` |
| `explosion` | a kill | noise |
| `hit` | damage taken | noise + `step` |
| `laser` | a shot | `saw`, falling sweep |
| `jump` | a take-off, a ball off a bat | `square_lead`, rising sweep |
| `pickup` | a coin, a brick, score | `bell` |
| `chime` | a round bell, a save recorded | `bell` |
| `select` | a confirm, a gate accepting, an NPC starting to talk | `pluck` |
| `thud` | a wall, a stomp | `step` |
| `footstep` | a walked tile | `step` |
| `skid` | leaving the road | sustained noise |

**Export order IS the priority policy.** The ca65 queue holds ONE effect per
frame and the LOWER id wins (`tad-audio.s:1293`), so the ordering in
`slice_b.terrificaudio` is a design decision: the four echo-carrying effects
sort highest (losing one leaves the reverb wrong for the rest of the scene),
ordinary events next, and `footstep`/`skid` lowest — a footstep must lose to
an explosion.

**Cost, measured:** the eleven added effects and two added instruments took the
blob from 8,450 to 8,701 B against a 16,384 B claim (halved 2026-09-08). Bytecode is nearly free
(~15 B an effect); BRR is not (~1 KB per 0.12 s one-shot). That is why the set
leans on `play_noise` and `portamento_calc` and why the only new instruments
are single-cycle 64-sample loops at ~36 B each.

### Two things that are silent, not broken-looking

Both compile, queue and key on. Neither produces a sound. Both were found on
the emulator by reading the S-DSP voice, and neither is visible any other way.

1. **A DECREASE-mode GAIN as an effect's opening envelope.** `E<rate>` and
   `D<rate>` fall from the envelope's CURRENT level, and key-on leaves that at
   zero — so `set_instrument_and_gain step E14` decays from silence and the
   voice reads `ENVX = 0` forever. Percussive effects open with
   `set_instrument_and_adsr <inst> 15 <decay> <sustain> <rate>` instead
   (attack 15 = instant). Fixed `F<level>` gain is fine; `I<rate>` is fine
   because it rises from zero by definition.

2. **TAD's default audio mode is MONO** (`tad-audio.inc:123`). In mono the
   driver collapses every channel to centre, so `Tad_QueuePannedSoundEffect`
   costs cycles and achieves nothing — and it is not subtle: before this was
   found, EVERY DSP voice on every rail, music included, read
   `VOL_L == VOL_R`. A rail that pans must set
   `Tad_audioMode = TadAudioMode::STEREO` **between `Tad_Init` and
   `Tad_LoadSong`**; the mode only takes effect at the next song load
   (`tad-audio.inc:525`). `shmup`, `boss_saucer` and `split_v_fight` do.

Both are guarded by `tests/test_sfx_vocabulary.py`, whose cases read the DSP
voice rather than the queue byte — the queue is consumed and reset inside the
same frame (`tad-audio.s:993`), so it reads `$FF` at every frame boundary and
a test watching it would pass on a silent rail.

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
