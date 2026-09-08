# Paper cuts

Friction worth recording: what slowed work down, what misled it, and what it
cost. Append-only, newest section at the bottom, one section per sprint.

Each entry is tagged with the *feeling* — **clunky** / **easy** / **surprise** —
and the *cost*: **HIGH** (≥1 hour lost, or an actively misleading
investigation) · **MEDIUM** (15–60 min) · **LOW** (<15 min, fix
opportunistically). The two are independent: an "easy" win can be HIGH if its
absence elsewhere costs hours.

> **This file is new as of 2026-09-08** and nothing yet points at it. It was
> created because the SFX sprint's brief asked for one; if it is worth keeping,
> `CLAUDE.md`'s pointer list is where it should be named.

---

## Procedural SFX across the rails (2026-09-08)

### TAD's default audio mode is MONO, and nothing says so where you look — **surprise, HIGH**

`Tad_QueuePannedSoundEffect` is documented in `vendor/tad/tad-audio.inc` with
a clear contract (`A` = id, `X` = pan, out-of-range falls back to centre), and
the SPC driver stores the pan exactly as advertised. None of that matters: the
default audio mode is MONO (`tad-audio.inc:123`, in a different section), and
in mono the driver collapses every channel to centre. So the whole panning path
works perfectly and produces nothing.

What made it expensive is that **every layer looked correct**. Reading the
queue function, the send macro and the driver's `__reset_channel` all confirmed
the pan was stored and sent. The emulator said otherwise, and the gap between
"the code is right" and "the output is centred" is where the hour went.

What actually closed it was widening the measurement instead of re-reading the
code: sampling **all eight** DSP voices rather than the two SFX channels showed
that the MUSIC was centred too — which no game-side bug could explain, and
which pointed straight at a global mode. **Lesson: when a per-feature
measurement says "no effect", measure something the feature does not touch. If
that is broken too, the bug is above the feature.**

### An SFX can compile, queue, key on, and be silent — **surprise, HIGH**

`set_instrument_and_gain <inst> E<rate>` is accepted by tad-compiler and reads
like "play this with an exponential decay". `E`/`D` GAIN are *decrease* modes:
they fall from the envelope's **current** level, which key-on leaves at zero.
Five of eleven new effects opened this way. They compiled, the queue carried
them, the voice keyed on, and `ENVX` stayed 0 forever.

Nothing in the toolchain can catch this — it is a legal envelope. Only the DSP
voice shows it. Recorded in `assets/audio/sound-effects.txt` where the next
author will hit it, and guarded by `tests/test_sfx_vocabulary.py`.

### Regenerating the audio export has no `make` target — **clunky, MEDIUM**

`assets/audio/README.md` documents the `tad-compiler ca65-export` command
properly, and the checked-in export is the right call (the build never needs
Rust). But because `make` does not know about it, **editing `sound-effects.txt`
changes nothing until you remember to regenerate** — and the ROM still builds,
so there is no error, just stale sound.

This bit for real: after reverting an experimental `set_pan 0` from the source,
the export was not regenerated, so a full measure/rebuild cycle ran against a
blob that still contained the probe, and the result was misread as "panning
still broken" for one whole iteration. A `make audio-export` target that shells
out when `tad-compiler` is present — and says so clearly when it is not — would
remove the class. The same gap means nothing warns when the committed export is
out of date with respect to its own sources.

### Onset count is the wrong cadence signature for an interruptible effect — **surprise, MEDIUM**

Testing "this cue fires per crossing, not per frame" by counting voice ONSETS
is intuitive and wrong for one-channel + interruptible effects: a repeat
*restarts* a voice that is already sounding, so it never goes silent and the
onset count does not rise. Measured, it **falls** — 71 onsets healthy, 44 with
the cue moved into a per-frame path. The bound passed the defect.

The falsification harness caught it (TEST-BLIND, not a false green), which is
exactly the case `docs/46` exists for. Live-fraction separates the two states
cleanly (19% vs 84%). Both signatures are now in the module with a note on
which is diagnostic for which kind of effect.

### `cd <subdir> && make <target>` silently targets nothing — **clunky, LOW**

Running the export command from `assets/audio/` and chaining `&& make shmup`
fails with "No rule to make target", which is easy to skim past in a long
output block and leaves the previous ROM in place — so the next measurement
silently describes the old binary. Cost twice here. Absolute `make -C` or a
leading `cd` back to the repo root avoids it.

### `make X | tail` reports TAIL's exit code — and I read a RED landing gate as green — **surprise, HIGH**

`make bare-check 2>&1 | tail -45` exits with `tail`'s status, not `make`'s. The
run came back "exit code 0", I reported the landing gate green, and the
artifact it had just written said `verdict: RED, exit_code: 1`. One gate had
failed.

The infuriating part is that the Makefile warns about this *by name*, eleven
lines above the target I was invoking — the `test:` target exists precisely
because "`pytest -q | tail` reports TAIL's status, not pytest's ... that masked
a red". I read that comment earlier in the same session and then made the
mistake anyway, because the pipe was about output volume, not about exit codes,
and those felt like different concerns.

**What actually fixes it** is not "remember to be careful": it is to never read
a verdict from a pipeline's exit code when the target writes an artifact.
`bare-check` writes `build/bare_check.json` with `verdict`, `exit_code`,
per-gate status and `fault_reading` — read THAT. A wrapper that refuses to pipe
(or a `bare-check` recipe that prints the verdict line last, unpiped) would
close the class for good.

### A concurrent build turned the landing gate red, and the artifact said so before I did — **clunky, MEDIUM**

The gate that failed was `measure`, which counts cycles on the emulator, and
`bare_check.json`'s own `fault_reading` read `harness-liveness` — docs/44 §6's
"a wall-clock guard fired, not a tree break". I had run allocator spikes
concurrently with the run, having noted one turn earlier that bare-check is
flaky under load and that I should not.

Two things would have helped, neither of which is discipline. First, the run
takes ~25 minutes with no output until it ends (its own `tail` buffering), so
there is no ambient signal that something expensive is in flight — a poller
that prints progress makes the cost visible and is what I should have armed at
the start, not after being told. Second, `fault_reading` is excellent and I did
not look at it until the verdict surprised me; it deserves to be in the line
the target PRINTS, not only in the JSON, so a red arrives already labelled
tree-break or liveness.

Filed with the verdict left at RED. The reading is advisory and re-running
clean is the answer, but a red that gets explained away in a report is how a
real one ships.

### `test_measure_vblank` times out under bare-check — SECOND sighting, which docs/44 says is a harness bug report — **surprise, MEDIUM**

Two bare-check runs on this branch went RED in the substrate-measurement
family, and both carried `fault_reading: harness-liveness`:

  7e3dbca   the `measure` gate failed
  c78d955   `test_measure_vblank.py::test_measure_usable_vblank_bytes` and
            `::test_measure_multi_queue_arm_cost`, exceptions
            `TimeoutError` + `AssertionError`

docs/44 §6 is explicit that this is not something to argue away: *"a
`harness-liveness` reading is never a pass, and a SECOND sighting of one is a
bug report — against the harness rather than a rail."* This is that second
sighting, so it is filed rather than dismissed.

The tree is not answerable for it. The probe links with `lorom_32k.cfg`, which
this branch never touched; `git diff --name-only origin/main...HEAD` has
nothing on the probe path at all; and both cases pass locally in 1.8 s on a
free box, re-measuring rather than reading a cached artifact (checked:
`build/measurements_vblank.json`'s mtime moves).

What is worth someone's attention is the CONDITION. These are wall-clock
measurements and the landing gate runs the suite with `XDIST=2`, so they are
timed while another worker is doing arbitrary work on the same box. That is a
race the measurement cannot win reliably, and it makes the landing gate's
verdict a coin-flip on any branch, not just this one. Options a future sprint
might weigh: pin the measurement modules to a worker of their own, run them
outside the parallel suite the way `falsify` and `determinism` already are, or
give the guards a budget that survives a loaded box.

Recorded with the verdict left at RED both times.

## SFX request queue (2026-09-08)

### A hardcoded address in a test blamed the ROM for a re-packed map — **surprise, HIGH**

Adding a 17-byte GLOBAL claim moved `ES_SM_FRAME` from `$04A0` to `$04B1`.
`tests/test_room_window.py` carried `SM_FRAME = 0x04A0` as a literal, so it
began reading the first byte of the new feature's state — which is zero — and
two cases went red saying *"the loop is missing frames"* and *"0 usable
samples"*. Both accuse the ROM. The ROM was fine.

What makes it worth filing is that the module's own `_room_symbols()` docstring
**names this exact class**, describes a previous sweep that removed such
literals, and even names `0x04A4` as one of them — and `IRIS_TAB = 0x04A4` was
still sitting eight lines below it. A cleanup that documents itself but leaves
survivors reads, to the next person, as a cleanup that finished.

The useful generalisation: **a test that hardcodes an allocator-owned address
is a landmine for whoever adds the next claim**, and the blast lands on them,
not on the author. `grep -nE "^\s*[A-Z_]+ = 0x[0-9A-Fa-f]{3,}" tests/*.py`
finds them in a second; something like it belongs in a gate.

### A falsification plant went quiet when the config underneath it moved — **surprise, MEDIUM**

`sfx-bank1-alignment-dropped` patched `lorom_512k.cfg` and built `room` to
prove the build refuses a mis-aligned `BANK1`. Two commits later `room` was
relinked with `lorom_64k.cfg`, so the plant patched a file that rail no longer
used: it still "passed" the eye, but the harness reported **TEST-BLIND** —
the defect reached nothing.

A plant going quiet is the same rot as a test going quiet, and it is *harder*
to notice because plants are only run deliberately. Two things follow. Run the
WHOLE set after any build-system change, not just the plants you think you
touched — `--only` would have hidden this indefinitely. And when a mechanism
lives in two files (both linker configs carry that alignment now), it wants a
plant per file: one checked by accident is one not checked.

### The ring self-heals, which hid a missing power-on reset — **surprise, MEDIUM**

The plant that removes `sf_sfx_reset` came back TEST-BLIND at first. The reason
is a genuine property rather than a mistake: an unreset garbage count drains at
one entry per frame and the driver rejects out-of-range ids, so a test looking
minutes into a boot sees a perfectly normal ring. The defect is real but its
window is the first few frames.

Generalises to anything with a pump: **self-healing state cannot be tested
after it has healed.** The case that catches it reads the structure 8 frames in
and asserts four bytes at once, so a lucky random-RAM seed cannot pass it.

---

## The action rails' song (2026-09-08)

### Which song a rail plays, and what depends on it, was nowhere written down — **clunky, MEDIUM**

The ask was "make the music sound less like a music box." The obvious move —
rewrite `slice_b_song` — would have been wrong, and nothing in the docs said
so. Eight rails all did `lda #Song::slice_b_song`, and the fact that ONE of
them (`room`) has an entire test module calibrated to that song's shape lives
in two places, neither of them a doc: a comment inside the MML ("Bar 8 is a
deliberate near-silence … the audibility test's window") and a constant block
in `tests/test_slice_b_audio.py` (`LOOP_TICKS, REST_ALIGN = 768, 716`). The
song's echo header is coupled the same way — `room_a_ambience` restores exactly
`#EchoVolume 12` / `#EchoFeedback 24`, so those three header lines are a
contract with a sound effect, not a taste decision.

Finding that out cost ~20 minutes of reading before a line was written, and the
failure mode had it been missed was not a red test but a *silently destroyed
demonstration* — the room rail would still have passed its RMS threshold while
no longer showing what it exists to show.

Fixed by writing it down: `assets/audio/README.md` now has a "Two songs"
section naming which rail plays which and why the split exists. The general
shape — **an asset whose properties are load-bearing for a test should say so
in the asset's own directory, not only in the test** — is worth carrying.

### `tad-compiler` resolves song paths against the project file, not the cwd — **surprise, LOW**

`tad-compiler song project.terrificaudio mml/drive_song.mml` from the repo root
gives `unable to open drive_song.mml: No such file or directory`, which names a
file *without* the directory prefix that was passed. The tool resolves the path
relative to the project file's own directory (the same way the project's
`source` fields are resolved). Run it from `assets/audio/` and it works. ~2 min,
and the export command in `assets/audio/README.md` already says "from
`assets/audio/`" — the one-off `song` subcommand is where it bites.

### An alphanumeric MML subroutine id needs a trailing space, and the error blames the wrong thing — **surprise, LOW**

`[!e]16` fails with `cannot find subroutine: !e]16` plus two cascading errors
about an unclosed loop. The rule is in the syntax doc ("If the id is an
alphanumeric, a space is required after the `id`"), but the diagnostic reports
the id it *parsed* rather than saying the id ran on into the next token, so the
message reads as "this subroutine does not exist" when the subroutine is fine
and the space is missing. `[!e ]16` compiles. ~3 min, twice (once for `!e`,
once for `!k2`).

### Time-averaged mix levels are the wrong instrument for percussion — **surprise, LOW**

Reading `|VxVOL| × VxENVX` per voice off the S-DSP gives a genuine per-part mix
balance and is the right tool for sustained parts. It systematically
under-reads drums: a kick is a 160 ms one-shot at 2.3 hits/s, so it occupies a
small fraction of the frames no matter how loud it is, and the average says
"8%" for a part that dominates every transient it lands on. Two rounds of
tuning went into chasing that number before noticing the metric was wrong for
the class. Peak-per-part, or simply the listener, is the right judge; the
average is only comparable *between* parts of the same kind.
