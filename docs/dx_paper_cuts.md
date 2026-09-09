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

## lakeside — a sea, gated on the picture (2026-09-09)

### `ES_SM_CTL` names the next scene 16 frames before that scene's `tick` runs — **surprise, MEDIUM**

Driving a rail from the title into its play scene wants a "the scene is live"
signal, and the obvious one is the scene manager's own control byte: step until
`ES_SM_CTL` reads the destination id, then start pressing. Measured on
`lakeside`, that byte flips **16 frames early** — scene_mgr names the
destination when a FADED transition begins and holds the switch under `fade`'s
ramp, so `lake::tick` has not run once when the byte already says `lake`.

What made it cost time is how it PRESENTS. A press train of eleven presses
landed ten toggles: the first press vanished and every other one worked. That
reads as an off-by-one in the harness — I went looking at `frame_step`'s input
latch timing and its docstring's "visible in the SAME step's readback" before
suspecting the ROM side at all. The give-away, once measured, was that the ten
that worked were exactly the ten that fell after the ramp.

**The fix is to wait on the SCENE'S OWN OUTPUT, not on the manager's byte.**
`tests/test_lakeside_audio.py::_enter_lake` steps until `ES_WAT_SCROLL` has
actually advanced, which is `lake::tick` having called `wat_advance` — a signal
that cannot be true before the scene runs. Frame-counted throughout, so
`make time-check` stays clean. Any rail with a `style = "fade"` edge has this
shape; a drive keyed to `ES_SM_CTL` alone spends its first ~16 frames of input
on a scene that is not listening.

### `play_noise`'s length is the INSTRUMENT's, and copying the nearest example truncates a long effect — **clunky, MEDIUM**

`play_noise` plays the noise generator, but the BRR sample still ends the
voice: a non-looping instrument plays noise only for the length of its own data
(`/tmp/tad/docs/bytecode-assembly-syntax.md`, under `play_noise`). Both noise
effects already in `sound-effects.txt` — `skid` and `explosion` — open with
`step`, which is a 0.1 s one-shot, and both are short enough that it never
shows. So the house pattern for "a noise effect" is a pattern that silently
caps at a fifth of a second, and the obvious move (copy the nearest existing
noise effect) is the wrong one for anything longer.

A 0.8 s wave authored that way is cut off inside its own swell. The fix is one
token — a LOOPING instrument (`saw`), whose noise runs until key-off — but
nothing at the call site says so, and the effect that needs it is exactly the
kind you would not think to check. The reason is now written into
`sound-effects.txt`'s own block, beside the GAIN trap that block already
records.

### Decrease-mode GAIN rates are much slower than they read, and only the DSP will tell you — **surprise, LOW**

`sound-effects.txt`'s header already warns that `E<rate>` at key-on decays from
silence and is never audible. The sibling it does not warn about: a mid-effect
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

### No paper cut from the pre-existing module

`tests/test_lakeside.py` (29 cases) stayed green with no change: this rail
already composed `audio`, so the `Tad_Init` boot cost the last three rails paid
for was already in its frame arithmetic. Running it before the push anyway —
the one line the previous section asks for.
