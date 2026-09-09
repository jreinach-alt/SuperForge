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

### A song's echo header is a CONTRACT with the sound effects, and only two of the three couplings were written down — **surprise, HIGH**

Giving `drive_song` its own echo (EVOL 10 / EFB 20) broke `boss_saucer`, and
the landing gate is what found it. The rail's arena rests at a dry echo, the
beam swells it, and `beam_end` settles it back — by writing `set_echo_volume
12` / `set_echo_feedback 24` LITERALLY. Those are `slice_b_song`'s header
values. On a song whose header is 10/20, the first beam would have moved the
arena to a rest state it was never in, permanently.

So 12/24 is not one song's taste, it is a TREE-WIDE constant: two effects
write it back (`room_a_ambience` when the player leaves the cavern,
`beam_end` when the beam stops), and any song playing on a rail that uses
either must match it or the restore is a lie.

The 20 minutes spent before writing a line found the `room` coupling and
missed this one, and the reason is worth keeping: the room coupling is stated
in PROSE that names the song, so grepping for `slice_b_song` found it.
boss_saucer's coupling is four bare integers in a test (`ECHO_REST = (12, 12,
24)`) and two bare integers in an effect, and nothing in either says which
song they came from. **A grep for the asset's NAME cannot find a coupling
expressed as its VALUE.** The check that would have worked is the one done
afterwards: `awk` the effects file for every `set_echo` write and ask what
each restored value belongs to — four lines, and it enumerates the contract
completely.

Fixed by aligning the song to the constant and writing the reason into the
MML header, where the next person to pick an echo volume will be standing.
The song keeps its own buffer length and FIR taps, which are genuinely free:
the vendored compiler structurally refuses `set_echo_delay` inside an effect,
and no effect touches the FIR.

### Two test modules race through the shared tree, and the loser blames the allocator — **surprise, MEDIUM**

The same landing-gate run also erred with:

    FileNotFoundError: 'engine/features/zz_lockprobe_20442_1/feature.toml'
    make[3]: *** [Makefile:82: build/mz/engine_state_globals.inc] Error 1

`tests/test_repo_tree_lock.py` deliberately plants
`engine/features/zz_lockprobe_<pid>_<n>/` into the LIVE tree and removes it
again; `tests/test_measure_rebuild.py`'s fixture shells out to `make
microzero`, which enumerates `engine/features/*`. Under `-n 2 --dist
loadfile` the two land on different workers and the enumeration catches the
probe mid-life. The artifact's own `suite_schedule` shows them at positions
60/62 and 49/51 — both in their worker's tail, so they overlapped.

Nothing about it points at the cause: the traceback accuses the allocator of
failing to open a feature that no one wrote, on a build target unrelated to
either module. It is also intermittent — the immediately preceding run of the
same gate on the parent commit was green — so a single red here is not
evidence about the tree.

Unfixed, and named here rather than papered over. The shape of a fix is
scheduling, not allocator code: the tree-lock module wants the shared tree to
itself, so it should not be co-schedulable with any module that shells out to
`make`. `docs/44` §8's `fault_reading` called this run `defect` rather than
`harness-liveness`, correctly — it IS a defect, just not one in the diff
under test, which is a third category the reading does not yet have.

---

## Phase 2 — audio onto the silent rails (2026-09-09)

### I sent `make` to /dev/null during a plant, and a FAILED BUILD read as a passing gate — **surprise, HIGH**

Planting two cue sites at once to prove two new tests fire, I ran
`make sprite_game >/dev/null 2>&1; make patrol >/dev/null 2>&1` and then the
tests. They passed. For about a minute that read as "the tests are vacuous."

Neither was true. The plant text had gone in (grep confirmed it) but the build
had failed, so the ROMs under test were the UNPLANTED ones from the previous
build — and a test that passes against an unplanted ROM is the correct answer
to the wrong question. Redirecting `make` to /dev/null and not checking its
status turned a build failure into a silent no-op.

This is exactly the class `docs/46` exists for — "why a plant that no-ops used
to read as a pass" — and the falsification harness guards it by requiring the
ARTIFACT MD5 TO MOVE. I was planting by hand, outside the harness, and skipped
the one check that makes a plant mean anything. Redone with `md5sum` before and
after, both tests fired immediately and named the right cause.

**The rule, and it costs one line: a hand-run plant proves nothing until the
artifact's md5 has moved.** Print it, don't assume it. The same applies to the
restore: both ROMs here were checked back to their exact pre-plant md5 rather
than "it built again, so it must be fine."

### A drive that never produces the event passes the cue test by never testing it — **clunky, MEDIUM**

Every contact-triggered cue on these rails needed a drive that actually makes
contact, and open-loop input sweeps mostly do not. Counted across the four
rails: three geometries on stomper landed zero stomps (two swept symmetrically
around spawn and never reached the enemy's lane; one held left and pinned the
player against the wall at x=8 while the enemy patrolled 94..152 out of reach),
one on sprite_game never met a dot at one of four presets, and one on patrol
never met an enemy. Five drives, zero events, and every one of them would have
passed a bare "is it audible" assertion.

Two things fixed it, and both are cheap enough to be defaults. **Steer
closed-loop**: read the target's own position out of WRAM each frame and press
toward it, rather than authoring a geometry and hoping. **Assert the event
happened**, from the game's own counter (US_FOES, US_SCORE, US_HITS), as a
separate case — so a drive that rots fails loudly on the counter instead of
going quiet on the cue.

### The feature register's rail list says "derived from the tree" and nothing re-derives it — **surprise, LOW**

`docs/09`'s AUD row names its eight audio rails and calls the list "derived
from the tree" — wording added when a previous hand-maintained list was found
stale. But `make register` checks the census (179 dirs), not that list, and
`make register-write` reports "already up to date" without touching it. It is
still hand-maintained prose; only its provenance changed. Adding four rails
meant editing it by hand, which is fine — the trap is the phrase, which reads
as a guarantee that no gate provides.

### Composing `audio` costs FOUR FRAMES of boot, and two oracle modules were keyed to the identity it broke — **surprise, HIGH**

The landing gate went red with twelve failures across `test_patrol.py` and
`test_stomper.py` — the two rails that had just gained audio — and every one
of them accused the actors of walking wrong beats:

    AssertionError: beats frame 91: enemy1 OAM (99, 200), oracle x 95

Nothing was wrong with the beats. `Tad_Init` uploads the loader to the S-SMP
through the IPL's byte-at-a-time handshake before the game loop starts, and
that costs **four hardware frames, once**, before the fade is even done — a
cost every audio rail pays and always has. Measured: `advance(90)` leaves the
scene on tick **86**. Both modules were built on the identity *hardware frame
N ⟺ tick N−1*, which had been free until something took time at boot.

The two modules needed opposite fixes, and the difference is the useful part.

**patrol** compares OAM against a closed-form triangle wave, so the oracle can
simply be evaluated at the tick the scene reports: `US_FRAMES` is read out of
WRAM and the wave is asked about *that*. The identity is gone rather than
re-tuned, so the next rail to gain or lose a boot cost cannot re-break it.
(One subtlety, measured rather than reasoned: hardware OAM lags the counter by
exactly one, because the counter bumps at the top of the tick and the OAM the
PPU shows was DMA'd in the preceding NMI. That is now named `_beat`.)

**stomper** could not do that. Its scripts are recipes *found in the oracle at
absolute ticks* — "stomp at tick 285", "E2 stomp at tick 411" — where the
player follows the script but the enemies' positions are a function of the
tick, so a recipe that lands on a patroller's head only does so if machine and
oracle agree on the tick. Re-deriving three recipes was the wrong trade
against advancing the machine four frames further so the scene reaches the tick
they assume. That is still an absolute, deterministic landing under the
lockstep Machine; it is just counted in the units the oracle models. The skew
then has to appear at every frame→snap index, of which there were four.

**What made this cost an hour rather than five minutes**: twelve failures all
pointing at the actors, and none at boot. So `test_stomper.py` now carries
`test_the_boot_cost_is_what_the_scripts_assume`, which asserts the scene's own
counter against `BOOT_SKEW` and fails with "the rail's boot cost changed" —
one case, by name. Planted at `BOOT_SKEW = 3` it fires alone and says exactly
that. **The general shape: when a module depends on a timing identity, assert
the identity — otherwise every case that rests on it fails together and all of
them blame the physics.**

### An authored drive that only just works is a coin flip, and it passed locally before failing in the clone — **surprise, MEDIUM**

The stomper audio module's drive landed exactly one stomp, late in a 1200-frame
run. It passed here, three times, and in a combined 49-case run. The landing
gate's clone then failed it — and failed it on the RIGHT case, the one that
reads US_FOES and says "the drive never landed a stomp, so the cue case is
asserting nothing. The drive has rotted, not the audio."

Nothing about the ROM changed between those runs. `MesenRunner` re-seeds
power-on RAM per `LoadRom` (the deliberate hardware-faithful regime, CLAUDE.md
rule 5), and a marginal geometry is a coin flip against that. Passing three
times locally was not evidence; it was three heads.

The fix was the one already written down in this very file two entries above
and applied to sprite_game and patrol — **steer closed-loop** — and skipped
here only because the authored drive happened to work. It now reads the live
enemy's position each frame, walks at it, and jumps when grounded and within
the arc's reach. Kill lands at frame 159 of 1200 instead of somewhere near the
end: 7.5x headroom, and identical across three trials.

**Two things worth keeping.** A drive whose event lands near the end of its
budget has no margin — measure WHERE it lands, not just that it did. And a
self-diagnosing fixture earns its keep at exactly this moment: the failure
named the drive instead of sending me back into the audio path.

### `make tick-check` is not in `make gates`, but a test in the suite runs it — so skipping it defers the red by 25 minutes — **clunky, MEDIUM**

The maze commit went through width-check, time-check, register, rail-registered
and rom-unbacked, all clean, and the landing gate then failed on
`test_tick_lint.py::test_make_tick_check_is_clean`. `tick-check` is
deliberately outside `gates` and `bare-check` (CLAUDE.md says so: a finding is
not a defect, and its baseline of 350 has not been driven down) — but the
pytest suite asserts it is clean, and the suite IS in the landing gate. So the
lint is enforced; it just is not enforced anywhere fast.

The finding was fair, and it was in PROSE rather than code: the new `cell` word
was described as "the cell the player was in last tick", and the lint reads a
state declaration whose comment names a frame unit as a frame coupling. The
word holds a POSITION. Two rewrites failed because the explanation itself
needed to say "tick" — the lint scans the comment, so a comment about the lint
trips it — and the right answer was the documented `TICK: ok — <reason>`
override, which is exactly what it exists for.

**The habit worth forming: run `tick-check` beside the other lints on any
commit that adds a state declaration**, since it is the one gate that is
enforced by the suite rather than by `gates` and therefore the one that a
25-minute landing gate is the first to tell you about.

### A plant that moves the md5 and changes nothing still proves nothing — **surprise, MEDIUM**

Two entries above, the rule was "a hand-run plant proves nothing until the
artifact's md5 has moved". m7_oshoot showed that is necessary and not
sufficient.

The gun cue sits BELOW `do_fire`'s pool-full bail, so a press that spawns no
bolt makes no sound. Planting it ABOVE the bail moved the md5 — checked — and
all four cases still passed. The plant was real and the test was vacuous: the
drive pressed on a rising edge every six frames, and at MO_BUL_N = 8 slots with
MO_BUL_LIFE = 90 frames the pool never fills at that rate, so above and below
the bail are the same program.

The fix was a drive that SATURATES the resource the branch guards: pressing
every second frame fills the pool, and then the two separate cleanly — 30% of
frames with the cue below the bail, 88% with it above, against a bar at 55%.
It needed its own fixture, because the other cases want the slower drive.

**The general shape: a case about a REFUSAL is only meaningful under a drive
that provokes the refusal.** Bounds-check cases need the bound reached,
pool-full cases need the pool full, clamp cases need the clamp hit. Plant it,
and if the plant passes, the drive is not reaching the branch — that is a
finding about the test, and the md5 moving says nothing about it either way.
