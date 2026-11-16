# 12 — Music and sound

> DRAFT SPEC, owner direction of 2026-11-16: **80s orchestral fantasy**, with
> influence from two early-80s fantasy-film scores. The first is a
> barbarian-epic score: brass, war drums and a chanting men's choir. The
> second is a goblin-maze fantasy score: a synth-orchestra hybrid with
> whimsy. The visual source film (10) also lends its own score's soaring
> wonder.
>
> **Influence means vocabulary, not quotation.** The scores teach modes,
> orchestration, rhythm and texture, and every melody here is written new. No
> theme, motif, chord progression signature or rhythm hook is transcribed or
> paraphrased. Composer and title names are denylisted by
> `make cleanroom`.

## 1. Three colours, mapped to game states

| colour | where | what it borrows (as technique) | how it sounds on this machine |
|---|---|---|---|
| **Wonder** | title, camp, a floor cleared | the source film's soaring strings over a synth pad; **Lydian** lift (♯4) | a string ensemble melody over a slow detuned pad, celesta answers, gentle timpani rolls at phrase ends |
| **Mystery** | exploring a floor | the maze score's hybrid: arpeggiated synth figures under woodwind staccato, music-box colour, a light backbeat at most; **Dorian**, chromatic neighbour notes | a pulsing 8th-note synth arp (bass + pluck), a flute/oboe line, celesta or harp sparkles, an occasional low pad swell |
| **War** | a pack fight, the boss | the epic score's **unison horns and low brass**, ostinato war drums, chanted choir on open vowels; **Aeolian/Phrygian**, power fifths, ♭VI–♭VII–i cadences, pedal tones | brass in octaves, taiko + timpani ostinato, a formant "OH/AH" choir on long tones, strings doubling the brass rhythm |

**The leitmotif: "the Lantern"** (original). A 4-note rising figure, ending on
a held 5th: a hopeful question. It appears in:

| state | treatment |
|---|---|
| Wonder | full, on strings |
| Mystery | fragmented, on solo flute |
| War | augmented and minor, on horns |
| the descend-card sting | 2 s on celesta |
| floor cleared | resolved to the tonic, full ensemble |

**The Unwriting motif.** A descending whole-tone line. It never resolves.

## 2. Adaptive music: built on the driver's proven channel mask

TAD's `SET_MUSIC_CHANNELS` (an 8-bit key-on mask, `vendor/tad/tad-audio.inc`)
lets one song carry **layers** that the game switches on and off. There is no
song reload, so there is no seam. Each floor song is written as **one song,
8 channels**:

| ch | layer | on when |
|---|---|---|
| 0 | bass / pedal | always |
| 1 | synth arp (the Mystery bed) | always |
| 2 | woodwind melody | exploring |
| 3 | pad | always |
| 4 | brass | **fight** (a pack is alive in the heroes' cell) |
| 5 | war drums | **fight** |
| 6–7 | choir / strings doubling | fight + boss. Assumed to be the voices SFX borrow (§4) |

- The game sends the mask on fight start and fight end, gated to the next bar
  line so the change lands musically. The bar clock is a frame count derived
  from the song's tempo, computed by the asset generator.
- **The Unwriting (10 §4)** clears one more channel bit per 30 s once it
  begins, from the top down. The music *literally loses instruments* as the
  floor is erased. It is the cheapest dramatic effect in the game: one driver
  command.
- **Test:** the TAD channel mask that the S-CPU sends appears in the
  driver's command port log. The audible result is checked as a recorded WAV,
  per the audio carve-out in CLAUDE.md rule 2: the channels' RMS in
  fight-on and fight-off windows differs.

## 3. Instruments: synthesised, per house policy

`tools/gen_audio_samples.py` records a project decision (2026-07-30): **every
sample is synthesised by the repo, and none is sourced.** This spec keeps that
rule (09 Q9 asks whether to relax it). The 80s orchestral sound is then an
honest synth-orchestra, which is exactly the hybrid texture the maze score is
known for.

| instrument | synthesis recipe (in `gen_audio_samples.py`) | BRR form | est. size |
|---|---|---|---|
| **string ensemble** | 3 detuned band-limited saws (±7 cents), a low-pass, a slow attack via ADSR | single-cycle loop ×3 phases (64 samples each) | ~110 B |
| **brass / horn** | saw through a resonant low-pass whose cutoff rises in the attack; the **attack** is a 0.1 s one-shot + a looped sustain cycle | attack one-shot + loop | ~1.2 KB |
| **choir "OH/AH"** | a glottal pulse train through 3 vowel formant filters (AH ≈ 700/1220/2600 Hz, OH ≈ 450/800/2830 Hz), with slight vibrato baked into a long loop | ~0.25 s loop per vowel | ~2.5 KB ×2 |
| **timpani** | pitched decaying sine + inharmonic partials + a noise strike | one-shot 0.6 s | ~3 KB |
| **war drum (taiko)** | a low sine with a pitch drop + filtered noise body (the existing `kick` recipe, longer and lower) | one-shot 0.4 s | ~2 KB |
| **harp** | Karplus-Strong (the existing `pluck`, brighter) | one-shot 0.5 s | ~2.5 KB |
| **celesta / music box** | the bell partial stack (the existing `bell`), a short decay | loop | ~40 B |
| **flute / oboe** | a sine + 2nd/3rd harmonics + breath noise in the attack; oboe gets a nasal formant | loop + short attack | ~400 B each |
| **synth pad** | 2 detuned pulses (25% / 50%), a slow attack | loop | ~80 B |
| **synth bass / arp pluck** | the existing `tri` + `pluck` | reuse | 0 |

**Hall:** TAD echo at a long feedback, a constant EDL (the same rule as the
existing songs, `assets/audio/sound-effects.txt`). Per-biome ambience SFX
re-shape EVOL/EFB at floor enter, which is the proven `room` pattern.

**Budget:** TAD owns the SPC's 64 KiB, and an over-budget song **fails the
build**. Target for the instrument set: ≤ 20 KB. Each song ≤ 6 KB of sequence
data. Measure both from the TAD compiler's report in M10 and write them here.

## 4. SFX (shares voices with music)

TAD has **two** sound-effect channels (`tad-audio.inc:162`). The S-DSP has
only 8 voices, so an SFX borrows a voice from the song.

- **Unverified here:** which music channels the SFX interrupt. Read the TAD
  docs at M10 and record the answer.
- §2 assumes channels 6–7, and that is why they carry only doublings, never
  the melody. If the TAD docs say otherwise, move the doubling layers to the
  channels the SFX actually borrow.

| cue | recipe | reuse? |
|---|---|---|
| hit / pickup / footstep / explosion / chime | the existing cues | **reuse** |
| swing ×3 weights | a filtered noise whoosh, with pitch by weight | new |
| bow / bolt / ember | pluck + noise, saw zap, noise crackle | new |
| roll | short noise sweep | new |
| potion / revive | rising bell arpeggio | new |
| down | a falling tone + timpani | new |
| gate seal / open | taiko hit + low brass stab / a reversed bell | new |
| the Unwriting | a high sine fading with pitch drift: the "erasure" | new |

## 5. The cue sheet (tier M → S)

| song | colour | layers | tier |
|---|---|---|---|
| **Title: "The Book Opens"** | Wonder → the War tag | a full statement of the Lantern | M |
| **The Last Lantern (camp)** | Wonder, quiet | strings, celesta, pad | M |
| **The Hollow Wood (floor)** | Mystery ↔ War, adaptive §2 | 8-ch layered | M |
| **The Hollow Crown (boss)** | War, full | brass, choir, drums; the Unwriting motif on a pad | S (M uses the floor song with every layer on) |
| **The Grieving Fen** | Mystery, slower, oboe-led | adaptive | S |
| **The Shifting Waste** | Mystery in Phrygian, hand-drum bed | adaptive | S |
| **Results: "A Memory Kept"** | Wonder, the Lantern resolved | short, non-looping | S |

## 6. Process (for the composing agent)

1. Write the synthesis recipes first (M10a). Audition them as WAVs before any
   melody is written. If the brass or the choir fails to convince, raise
   09 Q9 then. Don't compose around a weak instrument.
2. Write each song as MML, with a header comment that states:
   - the mode
   - the leitmotif treatment
   - the layer plan
   - what was borrowed **as technique**, the way `foundry_song.mml`
     documents its design
3. **The originality check.** Before commit, the composer states in the MML
   header that no melody, progression or rhythm hook is taken from the
   influence scores. Reviewers listen with that question in mind.
4. Audio has never run on a cart (`JAM.md` row 6c). The flashcart listen in
   M10 is part of done.
