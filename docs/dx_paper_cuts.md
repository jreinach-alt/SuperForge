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

SECOND SIGHTING (2026-09-09, on the camera_follow tip), with a DIFFERENT
symptom from the same cause: 2475 passed, 0 failed, 3 errors, all from
`test_scene_mgr_shadow.py` fixtures shelling out to `make microzero` —

    make[3]: *** No rule to make target
    'engine/features/zz_lockprobe_16992_0/feature.toml',
    needed by 'build/mz/engine_state_globals.inc'.  Stop.

The first sighting was the ALLOCATOR raising FileNotFoundError on a probe dir
that vanished mid-read; this one is MAKE's own `$(wildcard
engine/features/*/feature.toml)` capturing the probe at parse time and finding
it gone by the time the rule ran. Two different layers, one race. Cost so far:
two landing-gate runs, ~26 minutes each, both on tips whose diffs were
unrelated to it.

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

### A denylisted title can be an ordinary English word, and this entry cannot spell it — **surprise, LOW**

`make cleanroom`'s multiword denylist joins each entry's words with a separator
class that also matches the EMPTY string, so a two-word title is matched when
it is written as one word. A test docstring described a cue as not being able
to overtake a resource pool, using a single verb that happens to be a 1980s
driving title with the space removed. The tripwire fired twice — once on the
line pass, once on the comment-wrap pass — and it was right.

THEN THIS ENTRY FIRED IT AGAIN. The first draft quoted the offending verb and
listed four more multiword entries to show how ordinary they are, which put
five denylisted titles into a committed file. `cleanroom` had been run BEFORE
the entry was appended, so it went green, and the landing gate caught it on the
next tip. The fix is not an allowlist: the existing exemptions are for
mechanism language (`run_to_break` is a harness method), and five entries so a
paper cut can be concrete would weaken the floor for nothing. So this entry
describes the class without spelling any member of it.

Three things worth keeping:

* **The collision class is ordinary English.** Several multiword entries are
  phrases a person writes by accident once the separator is dropped, so a red
  here is far more likely to be prose than provenance.
* **The gate block's ORDER paid for itself.** `cleanroom` runs first, so both
  reds cost ~116 seconds each instead of the 25 minutes a failure after the ROM
  builds and the suite would have. The artifact's `test` entry reads "skipped",
  not "FAILED" — one real failure, not two.
* **Run it LAST, or run it again.** Both misses were the same shape: the gate
  was run and then more prose was written before committing. It is cheap enough
  to run immediately before `git add`.

### The lock that closed the race had the answer in it, and had declined to use it — **surprise, MEDIUM**

`tests/conftest.py` already carried a readers-writer lock over the live
`engine/features/` tree: planters take `LOCK_EX`, and three modules that
`copytree` the tree take `LOCK_SH`. The `make` fixtures were excluded on
purpose, and the file says why:

> closing it completely would mean holding this lock across the `make`
> fixtures, which is most of the suite, and that would serialise away the
> parallel speedup the lock exists to make safe.

That is true of the EXCLUSIVE lock and not of the shared one, and the
distinction is the whole fix. `LOCK_SH` holders do not exclude each other, so
46 `make` calls across 38 modules may still overlap exactly as the three
copytree readers already do. The only thing that blocks is a planter's
`LOCK_EX`, and planters run ~0.3-1 s apiece. What the fix actually costs is
the mirror — a planter now waits for in-flight `make` subprocesses — which is
a real cost and a much smaller one than the sentence feared.

The same note had already MEASURED the exposure as active rather than latent
(`make microzero` and `make room` both red under a planted `fade` DP -> WRAM
change) and still left it open. So this was not an unknown race; it was a
known one whose price had not yet been paid. It then cost two landing-gate
runs at ~26 minutes each, on tips whose diffs were unrelated to it, surfacing
through two different layers — the allocator raising on a probe directory that
vanished mid-read, and `make`'s own wildcard capturing that directory at parse
time and finding it gone when the rule ran.

**The general shape worth keeping: when a note explains why a known hole is
left open, the reason has a shelf life.** This one was written when the hole
had cost nothing. Re-read it the first time the hole bills you, because the
trade-off it describes may not be the trade-off you are now making — here the
stated cost was for a lock mode the fix does not use.

`test_bare_check.py`'s five `make` calls are deliberately NOT converted: they
run against a clone in `tmp_path`, so they never read the live tree.


## Phase 2 close — scroll_run, microzero, and the tree-lock fix (2026-09-09)

### A GUARD THAT CANNOT FIRE READS AS LOAD-BEARING — surprise, HIGH

`scroll_run`'s goal chime was written with the edge test every other cue on
this rail needs:

```asm
    lda z:US_STATE
    bne @already_won            ; goal_check re-probes the pillar EVERY frame
    lda #SFX::chime
```

and the test module's docstring said so at length. Both were wrong. `tick`
gates on `US_STATE` at its very top and jumps straight to `@draw` once won, so
`goal_check` is only ever REACHED with `US_STATE == 0`. The branch could not
be taken. The guard was dead the moment it was typed.

**What found it was the plant, and nothing else could have.** Deleting the
guard, rebuilding (md5 moved) and re-running left all five cases GREEN. Read
carelessly that says "the cadence test is weak"; read correctly it says "the
thing you planted was not doing anything". Those are opposite conclusions from
the same green, and the only way to tell them apart is to ask what ELSE would
have to be true for the guard to matter — here, that `goal_check` runs after
the win, which one look at `tick` refutes.

This is the same family as the rule the `m7_oshoot` pass filed —

> a case about a REFUSAL is only meaningful under a drive that provokes the
> refusal, and a moved md5 says nothing about whether the drive reached the
> branch

— and it extends it to the other direction. There the DRIVE never reached the
branch; here NO drive can. **When a plant leaves every case green, decide
which of the two it is before touching the test.** The test that survived
here needed no weakening at all: the invariant it asserts (a won game goes and
stays silent) is real however it is delivered, and it is falsifiable by the
mistake an author would actually make — the cue on the always-run `@draw`
path, which reads 180 of a 200-frame tail against a bar of zero.

The prose cost is worth naming separately: the docstring asserted a control-flow
fact ("goal_check re-probes every frame") that I had written into a comment
myself and then read back as evidence. CLAUDE.md's rule is exactly this — *if
you are about to state what a tool does, open the tool* — and it applies to
one's own ASM from ten minutes ago as much as to somebody else's.

### `flock` LOCKS A FILE DESCRIPTION, NOT A PROCESS — surprise, HIGH

The tree-lock race fix (previous section) added `conftest.run_make`, which
takes `LOCK_SH` on a freshly-opened descriptor. Two modules —
`test_make_gates.py` and `test_rom_backing_gate.py` — hold `LOCK_EX` for the
whole test via `pytestmark = usefixtures("repo_tree_lock")` AND call
`run_make` inside it. `fcntl.flock` is per-file-description, so the second
`open()` gives a lock the process has no relationship to and the test waits
for itself. Forever.

It cost two background runs killed at their timeout, and the first reading was
wrong: two exit-143s look exactly like a slow suite under load, and I spent a
round treating them as one. What identified it was asking the narrow question
"who holds this lock" (`fuser -v build/.repo_tree.lock`) rather than the broad
one "why is this slow" — and one of the two answers was a worker from the
run I had already killed, still parked in the deadlock with the pre-fix
conftest.

`_repo_tree_flock` now suppresses nested acquisition while this process holds
`LOCK_EX`: strictly sound, because `LOCK_EX` is stronger than either mode a
nested caller can ask for. The falsifier
(`test_a_planter_may_call_run_make_without_waiting_for_itself`) runs the
nesting in a CHILD with a `subprocess(timeout=)`, so a regression is a red and
not a hung worker.

### A FILTER THAT ENUMERATES VALUES GOES STALE; ONE THAT COUNTS CELLS DOES NOT — surprise, MEDIUM

`test_register.py::_serves_row` finds a hand-owned §3.1 row by key and had to
exclude the GENERATED census row with the same key. It did that by testing
`"| unused |" not in l and "| scene |" not in l` — two of the census's three
scope values. Composing `audio` onto `microzero` flipped `tad_rom`'s scope to
the third, `global`; the filter stopped excluding the census row; and both
tests that use the helper began planting over the generated table instead of
the hand-owned one. They went red, which is the good half. The bad half is
that a green there would have been a plant into the wrong row.

The helper's own comment already described this trap ("the wrong-row trap this
helper's first draft fell into") — and the fix it shipped was an enumeration,
which is the same trap with a longer fuse. Counting cells (census 5, serves 2)
cannot go stale against a vocabulary it does not read.

Worth noting for anyone reading the census: `scope` is computed against ONE
manifest, `game/microzero/game.toml`. `audio` read `unused` there for the
whole Phase 2 pass while seventeen rails composed it, because the reference
game did not. That is not a bug in the census, but it is easy to misread as a
claim about the tree.

### READ THE TARGET BEFORE OVERWRITING IT — clunky, LOW

I wrote `game/microzero/state.toml` with a `cat >` heredoc to add one word,
having decided from `git status` that the file did not exist. It did — with
four scene sections and thirty lines of reasoning in it. The build named the
casualty within a minute (`Symbol 'US_T_FRAMES_LONG' is undefined`) and
`git checkout --` put it back, so the cost was small, but only because the
file was tracked and the tool that consumes it is strict. The habit that would
have avoided it entirely is a one-line `cat` before the write, and the reason
`git status` was not evidence is that it says nothing about files you have
not yet touched.

### A new song must re-prove the tree's two hardware rules — easy, LOW

`test_drive_song.py` asserts two things off the S-DSP that are properties of
the CHIP, not of that song: nothing scored on channels G/H (voices 6/7, which
the driver ducks for the duration of any effect), and no music voice in NON
(there is one noise generator, and the driver zeroes the volume of any music
channel sharing it). `circuit_song` shipped without either, and the gap was
easy to miss because the module that has them is named after the other song.

Both are now asserted for the new song too, on the TITLE screen where nothing
can queue an effect so both are equalities rather than thresholds, with a
third case (`test_the_title_is_not_silent`) keeping them from passing on a
silent chip. Planted: a `G` part reads 235 of 240 title frames, and a hat
rewritten as `N16,%12` puts a music voice in the mask on 177 of 240.

**Both plants go through the shared audio blob** — one `.terrificaudio`
project exports one `tad_audio_data.bin` for every rail — so each plant is
`edit MML -> tad-compiler ca65-export -> make -> pytest -> restore -> export`.
Worth doing anyway, and the restore is its own small proof: the re-export
comes back byte-identical every time, which is the compiler's determinism
observed rather than assumed. If a third song lands, these two cases are the
ones to copy first; they belong to the chip and every song owes them.

## Phase 2 close, second half — five more rails (2026-09-09)

### A MOVED md5 SAYS THE ROM CHANGED, NEVER THAT THE DRIVE REACHED THE CHANGE — surprise, MEDIUM

Third instance of one rule in one session, and the three together finally give
its general form. The `m7_oshoot` pass filed it as *a case about a REFUSAL is
only meaningful under a drive that provokes the refusal*; `scroll_run`'s goal
guard extended it to *a plant that leaves every case green means the guard is
dead OR the drive never reached it*; `mill` supplied the third corner.

Mill's plant put a `chime` inside the `bne` that guards `mil_lift_call` — an
arm reached only while `ES_MIL_BOARD` is 0. The ROM's md5 moved, the build was
clean, and all three cases stayed green. Read carelessly: the silence case is
weak. Read correctly: the drive is in the LOBBY for most of that window and
steps onto the car almost at once, so the planted line barely ran. Re-planted
at the scene tick's own top — a site nothing can skip — the same case reds at
169 of 335 frames against a bar of zero. The test was never the problem.

**The check that settles it in one step: before believing a green plant, ask
what fraction of the drive's frames actually execute the planted line.** An
md5 diff cannot answer that and neither can a build log; the four plants that
DID fire this pass all sat on paths their drive walks every frame.

### THE FIVE PLANTS, and what each one is worth

One per rail, each aimed at that rail's own edge claim, each restoring to the
byte:

| rail | plant | what red | what stayed green |
|---|---|---|---|
| `hud_game` | `ES_INP_PRESS` -> `ES_INP_CUR` | cadence AND the score case | audibility |
| `railshooter` | same swap in `rs_shot_cue` | cadence only | audibility, both kill cases |
| `mode7_explore` | `US_LANDED` -> `US_STEP_ACTIVE` | footstep cadence only | audibility, idle silence, both doorway cases |
| `m7_dungeon` | `onwin`'s `bne` -> nop | goal re-chime only | five others |
| `mill` | cue on the per-frame tick | pre-arrival silence | audibility |

The right-hand column is the argument for the cadence cases existing at all:
in four of five, EVERY other case in the module passes on the plant. An
audibility case cannot see a cadence defect, because the defect makes the
sound MORE audible, not less.

`hud_game` is the one that reds twice, and it is a nicer shape than the rest:
reading the held state makes `bump_score` score once a FRAME instead of once a
press, so the same defect is visible from the game state and from the chip
independently. Where a rail offers that, the counter case is worth writing
even though the cue case would catch it.

### THE 16 KB CLAIM MOVES EVERY BANK NUMBER BELOW IT — clunky, LOW

Four of the five rails failed to link on the first build, all the same way:
`tad_export`'s half-window takes the top of window 1, the small blobs that used
to own a window now fit BESIDE it, and every later blob shifts. ld65 named the
casualty each time (`poses_ab chunk bank drifted`, `m7dg_tilemap bank
drifted`, `mil_chr1 bank drifted`), which is the `.assert`s doing exactly their
job — the failure is a build refusal naming a symbol rather than a ROM reading
its neighbour's bytes.

Not a defect, and not automatable either: the hand-written `.segment "BANKn"`
directives are the one place the allocator's arithmetic is written down, and
`no_literals` bans the templated form that would let a feature compute them.
Worth knowing before composing `audio` onto a rail with more than one blob
window: budget a build-refuse-fix loop per rail, and read the new claims out of
`build/<rail>/engine_state_globals.inc` rather than guessing the shift.
`m7_dungeon` needed a blob SPLIT rather than a shift — its 16 KB tilemap now
shares window 1 with the export because both are exactly half of one, and the
allocator packs by (-bytes, name).

### A VARIANT SCRIPT IS A SECOND LINK PATH, AND EVERY ONE HAS TO LEARN ABOUT A NEW OBJECT — surprise, MEDIUM

Composing `audio` onto a rail adds two objects to its link. The Makefile recipe
is the obvious place to add them and the easy one to remember; what is easy to
MISS is that some rails are linked twice, by a `tools/build_*.sh` that
re-assembles the same `main.asm` with a `-D` and links it again. `mill-direct`
was spotted while editing mill; `rs-probe` — railshooter's MEASUREMENT ROM,
same shape, different rail — was not, and the landing gate is what found it:

  bare-check: RED — 6330bf31be13: gates, rom-census, rs-probe (119s)
    EXPECTED IMAGE ABSENT — build/rs_probe.sfc was not built by the gate block

Note the SECOND arm of that red. The gate did not merely report a failed step:
its rom-census derived that 59 images were demanded and measured 61, and named
`rs_probe` as the one absent. Two independent readings of one defect, and the
census arm is the one that would still have caught it if the script had failed
quietly.

**The sweep that answers it in one line**, and it is worth running whenever a
composition adds an object to any rail:

    for f in tools/build_*.sh; do
      src=$(grep -oE "^SRC=game/[a-z_0-9]+" $f | sed 's|^SRC=game/||')
      grep -q '"audio"' game/$src/game.toml && \
        { grep -q tad_wrapper $f && echo "OK $f" || echo "NEEDS $f"; }
    done

Ten variant scripts exist; four belong to rails that now have audio, and all
four are correct. Grepping for the RAIL NAME inside the script is the wrong
key — `build_shp_autodemo.sh` mentions `game/split_v_fight` in a comment and
builds `game/split_h_persp_demo`, which reads as a false positive. `SRC=` is
the key that means it.

## The four screen-effect rails (2026-09-09)

### THE ABSENCE OF CUES IS A DECLARATION, NOT AN OMISSION — easy, LOW

`heathaze`, `lakeside`, `smelter` and `mode7_flight` compose `audio` for MUSIC
ONLY. None imports `sf_sfx_queue_c`; none declares a `prev` word; none has a
state.toml change at all. A screen effect has no discrete event whose 0 -> 1
edge is a moment, so there is nothing to latch and nothing to sound.

That turns out to make the tests SHARPER rather than thinner, which was not
obvious going in. Because these four queue nothing, the two tree-wide hardware
rules can be asserted as EQUALITIES: there is no window in which voices 6/7
are legitimately busy, so any sounding there is a part of the song scored
where a future cue would erase it — a claim the cue-carrying rails can only
make on their title screens. One parameterised module covers all four, because
they make one claim four times and four copies of a fixture is not four tests.

### WHICH RAILS STAY SILENT, AND WHY EACH REASON IS STILL LIVE

Thirteen of the seventeen remaining are silent on purpose and say so:

  * `scroller`, `mode7_chamber` — MEASUREMENT rails. Their own headers call
    music "the prettify the demo move" and say "a demo that prettifies stops
    measuring what it was built to measure". Composing audio here would be
    reversing a live reason, not an expired one.
  * `boss`, `meteor_event` — their audio half exists as a SEPARATE RAIL
    (`boss_saucer`). The pair is the demonstration; composing here destroys it.
  * the nine `split_*` / `seam_*` demos — no game events at all.

The four that were wired had either NO stated reason (`heathaze`, `lakeside`,
`smelter` — the deferral the previous pass filed) or an EXPIRED one
(`mode7_flight`: "adding a soundtrack would be content it does not have",
the same sentence `m7_oshoot` and `railshooter` carried, false since the songs
exist). **Reading the stated reason before touching a rail is the whole of the
work here**; four of the seventeen were candidates and thirteen were not, and
nothing but the prose distinguishes them.

### THE ALLOCATOR ANSWERS "DOES IT FIT" WITHOUT A BUILD — easy, LOW

Before wiring anything, all four were test-fitted by copying the game dir to
`/tmp`, adding `"audio", "tad_rom"` to its globals, and running
`allocator/allocate.py --game <copy>`. Four for four in under a minute, no ROM
built and no tree touched. Worth doing first on any composition that might not
fit: the allocator is the authority on feasibility and it is CHEAP, where the
build that would tell you the same thing is minutes and leaves artifacts.

### RE-SEGMENTING IS DERIVABLE; THE ORDER WITHIN A WINDOW IS NOT — clunky, LOW

The bank drift these four hit is the same class the previous five did, but at
this scale it was worth scripting: walk the `<name>_bin:` labels in file order,
read `ES_R_<NAME>_BANK` out of the emitted `.inc`, and insert a `.segment
"BANKn"` wherever the claimed bank changes. Three of four fell out of that.

`mode7_flight` did not, and the reason is the part a script cannot derive from
banks alone: `tad_export` re-sorted the PACKING ORDER inside window 1. The
allocator packs by (-bytes, name), so the three 32 B palettes now group and
`m7f_todpal` sorts BEFORE `grad_tabs` instead of into a window of its own. Its
BANK was right and its ADDR was wrong — and only the second `.assert` of each
pair can see that. A blob in the right bank at the wrong offset reads its
neighbour's bytes, which is exactly what the addr assert exists for.

### COMPOSING `audio` MOVES EVERY ABSOLUTE FRAME BY FOUR — surprise, HIGH (three sightings, one session)

`Tad_Init` hands the driver to the S-SMP a byte at a time through the IPL
handshake and that costs FOUR HARDWARE FRAMES before `MAIN` reaches the scene
enter. Any test that counts absolute frames from power-on and means SCENE
frames is off by four the moment its rail composes `audio`.

Three sightings this session, each found by the landing gate rather than by
me, and each after a push:

  * `test_stomper.py` — the recipes are keyed to absolute ticks; the fixture
    now advances `BOOT + BOOT_SKEW`. This one paid for the constant.
  * `test_railshooter.py` — the roll-in's first five frames and the fail-state
    return. Fixed in the FACTORY (`rail(n)` advances `n + BOOT_SKEW`), because
    every absolute in that module is a scene frame.
  * `test_mode7_flight.py` and `test_mode7_explore.py` — one case each. Fixed
    at the SITE, not the factory: a blanket shift would have moved 116 and 30
    passing cases respectively to prove one, and the other early advances in
    those files are relative steps after a settle rather than absolutes.

**Whether to fix the factory or the site is the only real decision**, and it
turns on one question: does every absolute in this module mean a scene frame,
or just this one? railshooter's did; the other two files' did not.

**THE CHECK THAT WOULD HAVE CAUGHT ALL THREE BEFORE THE PUSH, and it is one
line**: after composing `audio` onto a rail, run that rail's PRE-EXISTING test
module, not only the new audio one. I ran the new modules every time and the
old ones only when the gate named them — which is how the same defect class
cost three separate ~30-minute landing-gate runs. The new module cannot see
this: it is written against the rail as it now is.

    python3 -m pytest tests/test_<rail>.py -q      # BEFORE the push, always

The sibling lesson from the same three: the gate's suite runs everything, so
ONE red aborts nothing else — 1 failed / 2527 passed each time. That is what
made the class visible as a class rather than as three unrelated flakes, and
it is worth reading a red that way: the count of what PASSED is evidence too.

---

## Three screen-effect rails get audio CONTENT, in parallel (2026-09-09)

`heathaze`, `lakeside` and `smelter` each gained a song of their own and cues
of their own, dispatched as three simultaneous worktree-isolated agents. The
entries below are merged from all three; where two agents found the same thing
independently that is said so, because independent rediscovery is the strongest
evidence that a doc gap is real rather than that one agent read carelessly.

### `play_noise` LASTS AS LONG AS THE INSTRUMENT'S SAMPLE, NOT AS LONG AS YOU ASKED — surprise, MEDIUM (found TWICE, independently)

The obvious instrument for a noise effect is `step` — it is the one `skid` and
`hit` and `explosion` already use, and it is literally a noise burst. Written
that way a wind BED is ~12 ticks long and then stops, no matter what duration
the `play_noise` carries; a 0.8 s wave is cut off inside its own swell.

The mechanism is one CAUTION line in the vendor's
`docs/bytecode-assembly-syntax.md`: *"The instrument is used to determine the
length of the noise. If the instrument does not loop, the noise is played for
the length of the instrument's sample."* `play_noise` swaps the S-DSP voice's
output for the noise generator but the BRR decoder keeps running underneath,
so a non-looping sample still hits its END flag and takes the voice with it.
`step`, `pluck` and `kick` do not loop; `tri_bass`, `square_lead`, `bell` and
`saw` do. That is why `skid` gets 96 ms out of `step` and could not get more,
and why both `wind` and `wave_break` are voiced by `saw` — an instrument whose
waveform is never heard, chosen entirely for its loop flag.

**What makes this a trap rather than a fact is that the house pattern encodes
it.** Both noise effects already in `sound-effects.txt` open with `step`, and
both are short enough that the cap never shows — so "copy the nearest existing
noise effect", which is the right instinct everywhere else in this file, is
precisely the wrong move for anything longer than a fifth of a second. Two
agents on two different rails made that exact copy on the same afternoon.
Nothing in `sound-effects.txt`'s own header said so, and that header is
otherwise where this project records this kind of trap (the DECREASE-gain one,
two sections above where `wind` now sits). Both new blocks carry it now,
because "wind", "rain", "sea" and "engine" are all future asks and every one
of them wants a noise bed longer than a sample.

### DECREASE-mode GAIN rates are much slower than they read, and only the DSP will tell you — surprise, LOW

`sound-effects.txt`'s header already warns that `E<rate>` at key-on decays from
silence and is never audible. The sibling it did not warn about: a mid-effect
`E<rate>` is far slower than the number suggests. `E11` from a level of 118
reached only **81 after 27 frames** — so a "long fade away" authored by eye
ends with an audible key-off chop at a third of full volume, which is the
opposite of the shape a draining wave has. `E17` then `E24` reaches ENVX 1 by
the key-off.

There is no way to know but to read `VxENVX` per frame off the DSP and print
the trace. That took one build-and-measure cycle, and the trace is worth
keeping as the way to author any shaped effect:

    envx: 0 2 6 10 14 ... 46 | 118 x9 | 114 108 ... 56 | 45 35 27 20 15 11 8 5 1
          the gather          the break   the drain       ...to silence

**Lesson, and it is CLAUDE.md rule 1 in its audio dialect:** an envelope is a
rendered output. Do not author one from the rate table — plant the effect,
sample `VxENVX` every frame, and read the shape.

### PUT AN AMBIENCE'S SWELL IN THE VOLUME, NOT IN THE ENVELOPE — easy, LOW

A gust wants to breathe. The instinct is to shape it with GAIN, which is what
every percussive effect in the vocabulary does. Don't, for a BED: ENVX is also
the byte a test reads to answer "is this voice sounding", so an envelope that
breathes toward zero is indistinguishable from a bed with holes in it, and the
continuity case cannot tell the two apart. `tremolo` modulates the CHANNEL
VOLUME instead — same audible swell, ENVX stays flat at the fixed gain, and
the two questions stay separable. Measured on the shipped effect: ENVX pinned
at 48 for every frame it sounds, VOL_L walking 7..18.

### `ES_SM_CTL` names the next scene 16 frames before that scene's `tick` runs — surprise, MEDIUM

Driving a rail from the title into its play scene wants a "the scene is live"
signal, and the obvious one is the scene manager's own control byte: step until
`ES_SM_CTL` reads the destination id, then start pressing. Measured on
`lakeside`, that byte flips **16 frames early** — scene_mgr names the
destination when a FADED transition begins and holds the switch under `fade`'s
ramp, so `lake::tick` has not run once when the byte already says `lake`.

What made it cost time is how it PRESENTS. A press train of eleven presses
landed ten toggles: the first press vanished and every other one worked. That
reads as an off-by-one in the harness — the agent went looking at
`frame_step`'s input latch timing and its docstring's "visible in the SAME
step's readback" before suspecting the ROM side at all. The give-away, once
measured, was that the ten that worked were exactly the ten that fell after
the ramp.

**The fix is to wait on the SCENE'S OWN OUTPUT, not on the manager's byte.**
`tests/test_lakeside_audio.py::_enter_lake` steps until `ES_WAT_SCROLL` has
actually advanced, which is `lake::tick` having called `wat_advance` — a signal
that cannot be true before the scene runs. Frame-counted throughout, so
`make time-check` stays clean. Any rail with a `style = "fade"` edge has this
shape; a drive keyed to `ES_SM_CTL` alone spends its first ~16 frames of input
on a scene that is not listening.

### THE DRIVER CLEARS `NON` WHEN AN EFFECT ENDS — surprise, LOW (found by a plant)

The noise-mask case has a non-vacuity companion — "something IS taking the
generator" — and it was written at a 90% bar on the reasoning that `NON` is
sticky once set. It is not: the driver clears the bit when the effect that set
it finishes. So the plant that lengthened the wind's cadence past its own
length reddened the NOISE case as well as the CONTINUITY case, saying one
thing twice and in the worse of the two voices. The bar is now 50% — enough to
say the generator is in real use, not enough to be a second copy of a case
that asks the question directly. **A non-vacuity guard wants the loosest bar
that still refuses vacuity;** tightening it past that silently annexes the
neighbouring claim, and only a plant shows you.

### RE-READING A RAIL BEAT INHERITING ITS PREDECESSOR'S ARGUMENT — surprise, MEDIUM

The four screen-effect rails landed a day earlier as a SET, on the argument
that a screen effect has no discrete event whose 0 -> 1 edge is a moment, so
each gets music and no cues. Handed that argument, the `smelter` agent checked
it against its own rail rather than inheriting it, and found it false there:
`works` has a B toggle and a Start, both already gated on `ES_INP_PRESS`, i.e.
two edges that were sitting there the whole time. The grouping was doing the
reasoning.

**The re-check then propagated, and that is the part worth carrying.** Applied
to the other two, the same question found a surf cycle in `lakeside` whose
crest is a timed moment and a Start in `heathaze` — so the argument that had
covered four rails now covers exactly one (`mode7_flight`), and three rails
that were "correctly" silent by a set-level argument were silent by an
un-checked one. The cheapest place to check is the scene's own tick: **grep it
for `ES_INP_PRESS` before believing "no discrete event", and do it per member,
because a set's argument is only ever as true as its weakest member makes it.**

### A MUSIC-ONLY EQUALITY DOES NOT SURVIVE THE RAIL GAINING CONTENT — surprise, MEDIUM

`tests/test_screen_effect_audio.py` asserts, for four rails at once, that DSP
voices 6 and 7 never sound: they are TAD channels G and H, the driver ducks
them for any effect, and a rail that queues nothing has no window in which
they are legitimately busy. It is a flat equality and it is the right shape
for a rail with music only.

All three rails now queue cues — `heathaze` a wind bed on 99.8% of frames in
its desert scene — and **that module still passes**, because its drive never
presses Start, so for those three it measures the TITLE scene, which has no
cues. The equality is still true and it is now far weaker than it reads: for
three of its four rails it says nothing at all about the scene where the
content is. Its docstring ("none imports `sf_sfx_queue_c`", "queue nothing")
is now false for all three.

The agent that found it could see it on one rail; checking the other two
showed the module had gone from measuring four rails to measuring one. What is
worth carrying forward is the shape: **a case parameterised over rails
inherits its strength from the weakest drive it runs, and a drive that stops
at the boot scene can keep an equality green through exactly the change that
should have retired it.** The replacement claims live in the three
`tests/test_<rail>_audio.py` modules — WHAT sounds on 6/7 rather than WHETHER,
which stays an equality (no music-only instrument is ever keyed there) on
drives that do enter the scene — and the shared module is now scoped to
`mode7_flight`, the one rail whose premise it still describes.

### `make cleanroom` REFUSES AN ORDINARY ENGLISH VERB — surprise, LOW

An assertion message read "the re-queue cadence has <V> the effect it is
keeping alive", where <V> is the everyday verb meaning *to overtake by
running*. It fails the name tripwire: the denylist carries an arcade racer of
exactly that name, and the pattern makes the word separator optional, so all
three spellings — hyphenated, spaced and joined — are unwritable in any
committed file. (This entry cannot print the word for the same reason.)

The failure prints `cleanroom: FAIL — commercial / company name in committed
text` and the offending line, with nothing to say the hit is a verb rather
than a title. Five minutes, and the fix was "grown past".

Not a bug — the tripwire is doing precisely what it says, and its own header
calls itself a floor rather than a ceiling. Recorded because the collision is
invisible until you hit it and the message does not name the word it matched.

### `make rail-registered` FOUND THE ONE SITE A NEW TEST MODULE OWES — easy, LOW (found twice)

A new `tests/test_<rail>_audio.py` that reads its rail's `symbol_map.json`
owes an entry in `test_map_freshness_guard.py`'s reviewed dict, and the gate
named the file, the missing key, the value, and what the red would have looked
like if pushed without it ("`test_the_tree_agrees_with_the_rule` goes red
minutes into a full suite, in a module the port never touched"). Following the
printed line was the whole of the fix, on two rails independently. Recorded as
the gate working exactly as AGENTS.md says the gates work — run it and read
what it prints rather than memorising its rules — and because the alternative
is a ~30-minute landing-gate run to find the same thing. **Run
`make rail-registered` after adding any test module, not only after adding a
rail.**

### ORCHESTRATOR: THE PARALLEL AGENTS' SCRATCHPAD IS ONE DIRECTORY — surprise, MEDIUM

Three agents were dispatched at once, each into its own worktree, and each was
handed the SAME scratchpad path. Worktree isolation says nothing about `/tmp`.
One agent wrote a plant harness to `scratchpad/plant.py`, ran two plants from
it, and the third run died on a `KeyError` inside a *different* script with a
different data structure at the same path — another agent's harness, which had
landed on top of it between the second and third invocation. Nothing was
corrupted in any tree (each harness computes its paths from its own worktree
root), and the cost was five minutes of "why does my file not look like my
file". It would not have been five minutes if the collision had been in a
`.orig` backup rather than in a script: a restore step reading another rail's
saved file would have written it into the wrong tree, and the falsification
harness's whole contract is that the tree restores EXACTLY.

**This one is the orchestrator's, not the agents': the dispatch brief omitted
the line.** The fix is one sentence in it — tell each agent to work in a
subdirectory of the scratchpad named for its rail — and it costs nothing. The
general shape: *worktree isolation isolates the REPO, not the machine.*
Anything an agent writes outside its worktree is shared with its siblings.

### ORCHESTRATOR: APPENDING AN EFFECT RENUMBERS EVERY EFFECT BELOW IT — clunky, MEDIUM

`wave_break` and `wind` are appended to two different lists, and the export's
enum is positional: `footstep` moved 12 -> 13 and `skid` 13 -> 14. So the
central re-export obliges a relink of **every** rail that composes `audio` —
28 of them — not only the three whose content changed. A rail rebuilt from a
stale object file would queue `skid` where it meant `footstep`, silently and
audibly, and no gate reads an effect's id against its name.

Nothing here is wrong; the ordering IS the priority policy and that is worth
more than stable ids. What is worth recording is the cost shape, because it is
not visible from the diff: **a two-line content change to a shared blob is a
whole-tree rebuild, and it is cheapest to batch all the content for a pass and
export ONCE.** Doing it three times, once per agent branch, would have cost
three full rebuilds and three sets of md5 pins. The README's export section now
says so at the point where someone would be about to append.

---

## Two reported defects: a rail that sounded once a lap, and a wind nobody could hear (2026-09-09)

Both were reported by the project owner playing the ROMs, and neither was
caught by a test. That is the interesting part: in both cases the tests were
correct about what they asserted and the assertions were the wrong ones.

### A CUE THAT FIRES CORRECTLY AND ALMOST NEVER READS AS NO CUE AT ALL — surprise, MEDIUM

`microzero` was reported as "entirely missing sfx". It was not missing
anything: the lap chime worked exactly as scored, `test_microzero_audio.py`
proved it against a steering oracle that laps the ring, and the cue fired on
the right edge with a latch. But a lap is upwards of a hundred frames of
driving, the chime was the rail's ONLY cue, and from the couch a rail that is
silent for four seconds at a time is a rail with no sound effects.

**A cue's CADENCE is part of whether it exists.** Nothing in the module was
false; there was simply no case asking "how often does this rail make a
sound", and the answer — once per lap — was one nobody had looked at. The fix
needed no new mechanism: `race_logic` already writes `sector`, the ring's
quadrant, four times a lap, and it is the rail's own state word, so sounding
it is the same latch shape the chime already had. Measured after: a cue about
every 54 frames.

The general shape, and it is the sibling of the set-argument entry above:
**when a rail has exactly one cue, ask what fraction of the runtime it covers
before calling the rail sounded.** The events are usually already there — grep
the tick for the state the feature publishes, not just for `ES_INP_PRESS`.

### `ENVX > 0` IS AUDIBILITY IN THE SAME SENSE A PROXY VARIABLE IS EVIDENCE — surprise, HIGH

`heathaze`'s wind was reported as inaudible. Measured on the chip it was
sounding on 99.8% of frames and sweeping its noise band exactly as scored —
and it was running at **VOL 18 with ENVX 48 against the drone's VOL 42 and
ENVX 127, about 7% of a music voice's amplitude.**

Every case in the module passed on it, because every case asked WHETHER the
voice was sounding and none asked HOW LOUD. That is CLAUDE.md rule 2's
failure mode wearing a costume: the assertion reads the rendered output, off
the S-DSP, exactly as the rule demands — and `ENVX > 0` is still true at an
amplitude nobody can hear. **Reading the right register is not the same as
asking the right question of it.** The replacement asserts a RATIO of
`VOL x ENVX` against the song's own loudest voice, which is the product the
chip actually mixes.

Two follow-on lessons, both from plants:

* **A threshold nothing was measured against is not a bar.** The first ratio
  bar was 0.25, chosen by eye. Scoring the channel at `v3` instead of `v9`
  drops it to a plainly-inaudible 0.29 and PASSED. The bar is 0.50 now,
  checked against a deliberately-too-quiet build. An audibility claim needs a
  too-quiet plant the same way a cadence claim needs a per-frame plant.
* **The plant found a bug in the test, not just a loose bar.** The fixture
  recorded `(SRCN, ENVX)` per voice and the new helper multiplied
  `row[0] * row[1]` — the SAMPLE NUMBER by the envelope. It produced numbers
  that looked plausible and ranked voices almost right. Nothing but a plant
  that should have failed and didn't would have surfaced it.

### WEATHER IS NOT A SOUND EFFECT, AND ONE GENERATOR IS WHY — clunky, MEDIUM

Raising the volume would not have fixed the wind, and working out why is the
transferable part. An effect on this driver is ducked for any other effect,
dropped outright at low priority when both channels are busy, one-shot (so
continuity has to be manufactured by re-queuing it faster than its own
length, forever keeping a cadence and a duration in step), and — the one that
actually decided it — **it does not reach the echo.** The 128 ms buffer is
what smears the LFSR's edges into a rush; dry, the identical noise band is
tape hiss. `E1` on a music channel is the difference between "noise is
playing" and "wind is blowing".

So the wind is now a NOISE CHANNEL IN THE SONG (`far_ridge_song.mml`, channel
F) and the `wind` effect was withdrawn from the vocabulary rather than left
unused — leaving it is leaving the trap, since the next author wanting wind
would reach for `SFX::wind` and land back on the 7% bed. It was the last id
in the last list, so removing it renumbered nothing; had it been anywhere
else it would have obliged another whole-tree relink.

**The constraint that makes this a rule rather than a preference: there is
ONE noise generator, and a song channel holding it is muted whenever an
effect plays noise.** So the technique is available exactly to a rail whose
cues are not noisy — which the composition has to check, and `heathaze`
passes because its only cue is a pluck.

### `N<0-31>` TAKES THE DEFAULT NOTE LENGTH, WHICH IS NOT WHAT A BED WANTS — surprise, LOW

The first scoring of the wind channel was `N17 w1 | N19 w1 | ...` — read as
"set the band, hold a bar". It is not: `N` with no length argument takes the
DEFAULT note length, so each band played a short gust and then held a silent
bar. Measured, the voice sounded on 112 of 600 frames while looking
continuous in the score. Every band needs its own length (`N17,1`) and every
join needs a `&` slur, so that no key-off is sent and the clock changes
inside one held breath — with an instant attack a re-key would be a click at
full level once a bar.

### ORCHESTRATOR: I HAND-ROLLED A DRIVE AND BLAMED THE ROM FOR IT — surprise, LOW

Twice while diagnosing, an ad-hoc probe reported a defect that was the
probe's. `set_input(0, b=True)` before `frame_step(1)` does not press the
button — `frame_step(1, b=True)` does — so the toggle "did not work"; and a
probe that kept pressing Start for 240 frames bounced the rail back to its
title, so the scene "was not reached". Both times the rail's own test module
answered correctly in one run.

**Reach for the rail's existing drive before writing a new one.** The test
modules carry `enter_race`, `_enter_lake`, the steering oracle — drives that
are already known to work, already frame-counted, and already the thing the
gate runs. A fresh probe is worth writing when you need a measurement the
module does not take; it is not worth writing to answer "does this button
work".

### I DELETED A CONSTANT AND RE-RAN EVERY GATE EXCEPT THE ONE THAT READ IT — clunky, MEDIUM

Removing the withdrawn wind bed's `HZ_WIND_PHASES` from `heathaze.inc` was
verified the careful way and still shipped a red: I proved the ROM came back
BYTE-IDENTICAL (nothing referenced the constant in ASM), then re-ran
`cleanroom`, `width-check`, `time-check` and `register` — and pushed. The
landing gate found it in `test_heathaze_audio.py`, which read the constant at
COLLECTION time to derive the old re-queue cadence. Two collection errors,
`reading: defect`, a genuine red on the tip.

Three things worth carrying:

* **A byte-identical binary is not evidence that nothing broke.** It proves
  the ASM did not reference the symbol. The tests are a second consumer of
  the same source file and the ROM cannot speak for them.
* **The gates I chose to re-run were the ones I imagined were affected.** The
  module that named the symbol was not in that set precisely because I was
  thinking about the ROM. The existing rule already covers this — "run the
  rail's own test module before the push, always" — and I had it in mind for
  heathaze's ASM changes and dropped it for a constant deletion, which felt
  too small to need it.
* **A grep for the deleted name would have taken five seconds and found it.**
  `grep -rn HZ_WIND_PHASES` is the whole check; the tree is small enough that
  deleting any named thing should be followed by a grep for that name across
  `game/`, `tests/` and `tools/`, not just a rebuild.

The dead cadence constants and the now-unused `_rail_const` helper went with
the fix, so the module no longer reads a file for numbers the mechanism it
described no longer has.

---

## Forking the audio driver to reach state it already had (2026-09-10)

### THE CAPABILITY WAS ALREADY IN THE DRIVER, BEHIND NO DOOR — surprise, MEDIUM

The vendored driver has no way to change a sound attribute from the S-CPU
while it plays: all eleven IO commands are global or per-song, and sound
effects are queued by id and pan only. The obvious reading is "the driver
cannot do per-voice pitch", and the obvious fix is a large one — write the
mechanism.

Reading the driver's own source rather than its ca65 header says otherwise:

    ; i16 VxPITCH offset added to every play_note or portamento instruction
    channelSoA_detune_l : [u8 : N_CHANNELS]
    channelSoA_detune_h : [u8 : N_CHANNELS]

Per-channel pitch offset, applied on every note, persisting across notes —
all of it there, reachable only from song bytecode. **The work was a doorway,
not a room**: one command in a free protocol slot writing two bytes that
already existed. Fifty lines of SPC700, most of it comment.

The general lesson is the repo's own rule with a sharper edge: the ca65 API
is a *view* of the driver, and a capability absent from the view is not
necessarily absent from the thing. When a vendored dependency seems to lack
something fundamental, read its implementation before designing around it.

### CHECK UPSTREAM BEFORE FORKING, AND CHECK IT PROPERLY — easy, LOW

Before committing to a fork, fetch and diff: upstream at v0.4.2, **96 commits
past our pin**, still has `TAD_IO_VERSION = 20`, `N_COMMANDS = 11` and the
identical eleven commands. That converts "we may be behind" into "this is a
design boundary there", which is the difference between a pin bump and a
fork. Two minutes, and it is the fact the whole decision rests on.

### A LOUD VERSION ASSERT IS WHAT MAKES A FORK CARRYABLE — easy, LOW

`TAD_IO_VERSION` is bumped 20 -> 21 by the patch, and three independent
places assert on it: the generated export link-asserts against `tad-audio.s`,
and the Rust compiler crate has two compile-time assertions. All three fired
during the port — the Rust build refused first, then ld65 refused **by name**
("TAD_IO_VERSION in audio driver does not match TAD_IO_VERSION in
tad-audio.s") when the export was rebuilt against an unpatched API.

That is the property that makes a forked dependency safe to carry rather than
a slow leak: the failure mode of a half-applied fork is a build that stops,
not a ROM that is subtly wrong. **When forking anything with a protocol
version, bump it first and make sure something asserts on it** — before
writing the feature, not after.

### `bbc` IS DIRECT-PAGE ONLY, AND MY SPIKE'S PACKING WAS THE BUG — clunky, LOW

Two self-inflicted stops worth recording because both cost a build cycle.
SPC700's `bbc` tests a bit of a direct-page byte, not of A, so sign-extending
a 5-bit field in the accumulator needs a `cmp`/`bcc` rather than a bit test.

And the first end-to-end spike measured NO pitch change — which read as "the
command does not work" and was actually my parameter packing being nonsense
(`xba` then `ora` then a mask that cleared the channel bits). Replacing it
with a hand-computed constant (channel 1, +600 -> param0 $11, param1 $58)
moved the drone 1203 -> 1803 immediately. **When a new mechanism measures
zero, test it with a hand-computed constant before doubting the mechanism** —
it separates delivery from arithmetic in one build.

### THE FORK LANDED WITHOUT A CONSUMER, AND THEREFORE WITHOUT A REGRESSION TEST — clunky, MEDIUM

Recorded as an open gap rather than resolved. Every subsystem here ships with
a test that boots a ROM, and this one does not: the command is proven by
measurement (a fixed +600 landing exactly, and a sweep driven from a scene's
accumulator) but that evidence lived in a throwaway spike, and nothing in the
tree exercises it.

The reason is that its natural consumer — an engine note — needs a spare
MUSIC channel, and it turns out no rail has one. `circuit_song` scores all
six of A-F; G and H are the pair every song avoids because sound effects duck
them. Channel B rests for eight bars of sixteen, but by an arrangement
decision its own comment defends. So giving the capability a consumer means
re-scoring somebody's song, which is a content decision and not the
orchestrator's to make unilaterally.

The alternative considered and rejected was a probe ROM: the pattern exists
(`vendor/probes/probe_objview.asm`) but a probe carries its own allocator
run, symbol map and assets, which is more scaffolding than a one-command
regression needs and duplicates what a real consumer gives for free.

**The rule this is filed under: infrastructure whose test depends on a
content decision should land WITH the content decision, or with an explicit
note saying it did not.** This is the note.
