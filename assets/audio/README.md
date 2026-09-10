# `assets/audio` — audio content (TAD project + checked-in export)

The demo song, sound effects, samples, and the `tad-compiler ca65-export`
artifacts the ROM actually embeds. **The export is checked in** — the build
never compiles Rust, and regeneration is a documented one-command local step
(see below).

## Provenance — every sample is procedurally generated

**No external or reference sample material is used anywhere in here** — a
hard provenance rule for this tree. All seven wavs under `samples/` are synthesised,
deterministically, by [`tools/gen_audio_samples.py`](../../tools/gen_audio_samples.py)
— fixed-seed Karplus-Strong pluck, single-cycle triangle, 25 % pulse, bell
partial stack and band-limited saw, a filtered-noise footstep, and a
pitch-dropping kick. Re-running the tool reproduces the wavs
byte-for-byte:

```bash
python3 tools/gen_audio_samples.py assets/audio/samples
```

The songs (`mml/slice_b_song.mml`, `mml/drive_song.mml`,
`mml/circuit_song.mml`, `mml/far_ridge_song.mml`,
`mml/shallow_water_song.mml`, `mml/foundry_song.mml`) and the SFX
(`sound-effects.txt`) are authored in this repo. Licence: this directory is SuperForge project content;
the *generated* `export/tad_audio_data.asm` carries tad-compiler's own
Unlicense header, and the loader/driver binaries embedded in
`export/tad_audio_data.bin` are Terrific Audio Driver code (Zlib, © Marcus
Rowe) — see `vendor/tad/README.md` for the pin.

## Six songs, because the rails want different things

| song | rails | what it is |
|---|---|---|
| `slice_b_song` | `room`, `rpg`, `mode7_flight` | the ambient piece. Three channels, a whole-bar rest at the end of its 768-tick loop, and echo settings that ARE room A's acoustics |
| `drive_song` | the other 21: `boss_saucer`, `brawler`, `breaker`, `camera_follow`, `hud_game`, `jumper`, `m7_dungeon`, `m7_oshoot`, `maze`, `mill`, `mode7_explore`, `patrol`, `platformer`, `platformer_stream`, `racer`, `railshooter`, `scroll_run`, `shmup`, `split_v_fight`, `sprite_game`, `stomper` | the action piece. Six channels, a drum kit, a sixteenth-note bass |
| `circuit_song` | `microzero` | the racing piece. Six channels in A mixolydian over I - bVII - IV; the flat seventh is the whole colour |
| `far_ridge_song` | `heathaze` | the desert piece. D mixolydian with a flattened SIXTH over a bare D-A fifth drone; a whistled line with more rest than note, three portamento slides, a lub-dub kick once a bar — and **the wind, scored as a NOISE CHANNEL** rather than as an effect (channel F) |
| `shallow_water_song` | `lakeside` | the afternoon piece. F major at `#Tempo 56`, sevenths and ninths instead of triads, and a dominant that stays suspended so nothing ever resolves hard |
| `foundry_song` | `smelter` | the industrial piece. Six channels in C minor over an ostinato; its three parts run at 42, 32 and 96 ticks and coincide once every seven bars |

**Three of the four screen-effect rails now carry a piece of their own, and
re-reading each rail is what moved them.** The old argument — a kit under a
picture is the "prettify the demo" move, which is why `scroller` and
`mode7_chamber` decline audio outright — holds for MEASUREMENT rails, where
music changes what is being measured. It does not hold for a rail that has a
place and a player action in it: `heathaze` has a ridge and a Start, `lakeside`
a surf cycle whose crest is a moment, `smelter` a machine hall with a B toggle
and a Start. Each took a song written for it and cues from the existing
vocabulary. `mode7_flight` is the one that stayed on the ambient piece, and the
"no discrete event to sound" argument now covers three rails rather than four.

That third column is PROSE and the rail lists in it are hand-maintained; the
tree is the source of truth. `grep -o 'Song::[A-Za-z_0-9]*' game/*/main.asm
game/*/scenes/*.asm` derives them in one line, which is what the list above
was rebuilt from after it went stale across the Phase 2 pass.

The split is not decoration. `slice_b_song`'s rest half-bar is the window
`tests/test_slice_b_audio.py` uses to hear room B's echo tail ring where room
A's collapses — a piece with a kit under it has no such window, so making the
action rails loud would have cost the room rail its demonstration. Its echo
header is load-bearing for the same reason: `room_a_ambience` restores exactly
those EVOL/EFB values, so they are not free to change.

`drive_song` therefore carries its own header — 64 ms of echo buffer (8 KiB of
ARAM rather than 16) behind a low-passed FIR, a slap instead of a cavern.

`circuit_song` is the third, and it exists because a racing game wants neither
of the other two: the room's ambience has no pulse and `drive_song` is D minor
written for a shooter. A mixolydian keeps a major third with a flat seventh,
so the I - bVII - IV turnaround stays bright without ever resolving, which is
the sound a lap is supposed to have. It is declared with `#KeySignature +fc`
rather than accidentals, so the mode is stated once instead of being spelled
out bar by bar.

`far_ridge_song`, `shallow_water_song` and `foundry_song` are the fourth,
fifth and sixth, and each exists because a rail wanted a character the first
three cannot be edited into. `slice_b_song`'s loop and its composed rest
half-bar are calibrated to the room rail's reverb A/B demonstration, so
borrowing it and retuning it is not available — the demonstration is what
would break.

* **`far_ridge_song`** is heat and distance. A MAJOR third over a bare fifth is
  the "wide open"; a FLAT sixth is the ache; Mixolydian b6 is the mode that has
  both, and the song sits on a D-A drone so the two are always audible against
  each other. More rest than note, by design — the silence is the space.
* **`shallow_water_song`** refuses plain triads and refuses to resolve. Every
  chord carries its seventh and most carry a ninth, and the V is a `C7sus4`
  whose leading tone is simply absent, so the turn back to F is a lean rather
  than a snap. Its pad voices the third and the seventh and nothing else: the
  colour is carried by the interval, not by stacking the chord.
* **`foundry_song`** is the first in the tree whose subject is RHYTHM rather
  than harmony. `smelter` draws four steel plates each rising on its own
  harmonic, never in step; the song is three parts at three lengths — the
  ostinato at 42 ticks, the metal strikes at 32, the press at 96 — whose least
  common multiple is 672, so no two of them repeat their alignment inside a
  seven-bar cycle. C minor with the flat second and the tritone written as
  accidentals rather than into the key signature, which is what keeps them
  audible as faults.

**Its echo header is 12/24, and that is not its choice to make.** `drive_song`
was authored with a 10/20 header and the boss_saucer gate went red on it,
because `room_a_ambience` and `beam_end` write `set_echo_volume 12` /
`set_echo_feedback 24` as LITERALS: those two values are a tree-wide constant
that lives in the sound-effect definitions, not in any song. A grep for a
song's NAME cannot find a coupling expressed as its VALUE. Buffer length and
FIR remain per-song and both new songs set their own.

Two arrangement rules in it are hardware, not taste, and
`tests/test_drive_song.py` asserts both off the S-DSP:

* **Nothing is scored on channels G or H.** Those map onto DSP voices 6 and 7,
  which the driver ducks while a sound effect plays, so any part written there
  vanishes whenever the game makes a noise.
* **The kit does not use the noise generator.** There is one, and when an
  effect wants it the driver zeroes the volume of every music channel sharing
  it (`audio-driver.asm`, the `SfxNoise` branch). A noise hi-hat would drop out
  under every explosion. So the drums are samples: `kick` is a one-shot written
  for the job, and `step` — the footstep burst — is the snare at `o3` and the
  hat at `o5`. Both drum channels run under `K0` (no key-off, since the
  one-shots decay to zero themselves and a key-off would choke the kick's
  tail), which is why their gaps are `w` waits and never `r` rests.

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

Fifteen effects, shared by every rail that composes `audio`. Sharing is the
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
| `wave_break` | a crest arriving — three bands slurred under ONE key-on, so it is a break and not three hisses | sustained noise on `saw` |

**An effect that does not set its own volume is QUIET.** Nothing here called
`set_volume` until 2026-09-10, so every cue on every rail played at the
driver's default channel volume — measured on the chip as VOL 24, against
music channels running 48–63 on the same rails. A cue at 38% of the loudest
voice it must be heard over is not a cue, and on `microzero`, whose song is
mixed hot, the rail was reported as having no sound effects at all. Two
effects now set it (`chime` 255, `pickup` 192 — a lap outranks a checkpoint);
the other thirteen still run at the default, which is a tree-wide mix
decision rather than a bug fix, since fifteen rails would change balance at
once.

**Timbre is the other half of audibility, and it is per-rail.** A cue voiced
by an instrument its rail's own song already plays does not read as a cue.
`microzero`'s checkpoint was `select` (pluck) against a song that scores
pluck on channel D; bell is the one instrument `circuit_song` never uses,
which is why both of that rail's cues are bell now. **Before choosing a cue,
read the rail's song's `@` declarations** — the vocabulary is shared but the
right choice from it is not.

**Export order IS the priority policy.** The ca65 queue holds ONE effect per
frame and the LOWER id wins (`tad-audio.s:1293`), so the ordering in
`slice_b.terrificaudio` is a design decision: the four echo-carrying effects
sort highest (losing one leaves the reverb wrong for the rest of the scene),
ordinary events next, and `footstep`/`skid` lowest — a footstep must lose to
an explosion. `wave_break` sorts with the ordinary events: a crest the rail
timed should be heard.
Appending to a list RENUMBERS everything below it — `wave_break` moved
`footstep` from 12 to 13 and `skid` from 13 to 14 — so a re-export obliges a
relink of every audio rail, not only the ones whose content changed. Removing
the LAST entry of the last list renumbers nothing, which is what made
retiring `wind` free (below).

### WEATHER IS NOT AN EFFECT — the one that was tried and withdrawn

There WAS a sixteenth, `wind`, and it is worth recording why it is gone
rather than quietly dropping it. It was a low-priority effect re-queued by
`heathaze` on a cadence, and on the chip it measured **VOL 18 with ENVX 48
against the drone's VOL 42 and ENVX 127 — about 7% of a music voice's
amplitude.** It sounded on 99.8% of frames and swept its noise band exactly
as scored, and it could not be heard.

Volume alone would not have rescued it, and the three reasons are the general
rule for any AMBIENCE on this chip:

* **An effect can be ducked and dropped.** G and H are the SFX channels, the
  driver ducks them for any effect, and a low-priority arrival is dropped
  outright when both are busy. Air does not stop because a button was pressed.
* **An effect is a one-shot.** Continuity had to be manufactured by re-queuing
  it faster than its own length, so the cadence and the effect duration were a
  pair that had to be kept in step forever. A song channel with `&` slurs
  sends no key-off at all.
* **An effect did not reach the echo.** This is the big one. The 128 ms buffer
  is what smears the LFSR's edges into a rush; dry, the identical band is tape
  hiss. `E1` on a music channel is the difference between "noise is playing"
  and "wind is blowing".

So weather belongs in the SONG, as a noise channel — `far_ridge_song`'s
channel F is the worked example, and it holds the generator continuously at a
level that sits under the drone rather than beneath the floor. The effect was
removed rather than left unused precisely because leaving it is leaving a
trap: the next author wanting wind on another rail would reach for
`SFX::wind` and land back on the 7% bed. **One generator is the constraint
that makes this a rule and not a preference** — a song noise channel is muted
whenever an effect plays noise, so the technique is available exactly to a
rail whose cues are not noisy, which the composition has to check. `heathaze`
qualifies: its only cue is `select`, a pluck.

**Cost, measured:** the eleven added effects and two added instruments took the
blob from 8,450 to 8,701 B against a 16,384 B claim (halved 2026-09-08); the
three songs and two effects added on 2026-09-09 took it from 11,864 to
13,616 B, and moving heathaze's wind out of the effect list and into
`far_ridge_song` as a noise channel left it at 13,651 B — 2,733 B spare. Bytecode is nearly free
(~15 B an effect); BRR is not (~1 KB per 0.12 s one-shot). That is why the set
leans on `play_noise` and `portamento_calc` and why the only new instruments
are single-cycle 64-sample loops at ~36 B each. **Songs are now the growth
term, not effects** — the whole 2026-09-09 pass added no instrument and no
sample, and still spent 1,752 B, because a six-channel piece is a few hundred
bytes of bytecode each. The next composition should check the margin before it
is written, not after.

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
