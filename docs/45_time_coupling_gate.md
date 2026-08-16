# 45 — The time-coupling gate (`make time-check`)

> Status: LIVE — what `make time-check` catches and — §4 — what it cannot; `boot_to_frame` and the absolute-frame rule

## 1. The diagnosis

`AGENTS.md` has carried the rule for a long time:

> `run_frames`/`set_input` are wall-clock and are for interactive verification
> only — a measurement or capture calibrated against them drifts with host
> load.

An earlier pass **claimed to have closed the class.** Measured with the lint
that this document describes:

| rule | sites |
|---|---|
| `wallclock-run-frames` | 22 |
| `wallclock-run-seconds` | 18 |
| `wallclock-sleep` | 5 |
| `wallclock-timeout-s` | 5 |
| `free-run-read` | 6 |
| **total** | **56** across `tests/` + `tools/` |

(A raw-grep census taken beforehand said 27 across 14 test files. Both numbers
are right and they count different things: the grep counted `tests/` only and
included prose — five of its hits were comments and docstrings explaining why a
`run_frames` had been *removed*. The lint is AST-based, so it counts code, and
it also reads `tools/`, where most of the residue lived.)

**The gap was philosophical, and this repo already knows the answer.**
`no_literals` makes a hardcoded address *impossible*. `width_lint` makes a
width bug *visible*. `toy-bad` proves the allocator still refuses. The class
that has cost the most was prevented by **prose**. Prose is not a gate.

## 2. The gate

`tools/no_wallclock.py`, wired as `make time-check` (0.85 s), deliberately
built on `tools/width_lint.py`'s shape: same CLI (`--baseline`, `--json`,
`--write-baseline`, `--quiet`, `--summary`), same baseline semantics
(`(file, line, rule)` keys), same override grammar. If you have run
`make width-check`, you have run this.

It sits in `make gates`, in the **pre-push hook**, and in `make push`.

### The six checks

| rule | what it flags |
|---|---|
| `wallclock-sleep` | a `time.sleep(...)` call |
| `wallclock-run-frames` | a `.run_frames(n)` call — sleeps n/60 WALL seconds beside a core on its own thread: ~4x its argument under free-run, **zero** on a parked runner |
| `wallclock-run-seconds` | a `run_seconds=` keyword — a different amount of boot on every host |
| `wallclock-timeout-s` | a `timeout_s=` keyword — `max_frames=` bounds the same wait on the PPU's own counter |
| `free-run-read` | a read of emulator state taken while the core is FREE-RUNNING, on a path where a wall-clock advance is the only thing that placed it in time |
| `bare-override` | a `# WALL-CLOCK: ok` with no reason text |

`free-run-read` is the one that is not a grep. Inside one function body, in
line order, the lint tracks park state (`debug_break` / `frame_step` /
`frame_stepping()` / `boot_to_frame` park; `debug_resume` / `load_rom` /
`boot_rom` resume) and whether a wall-clock advance has happened since. A read
call reached free-running *after* such an advance is the exact shape measured
at **58% stale captures under 6 CPU burners** (see
`mesen_runner._park_for_capture`'s docstring).

`Path(p).read_bytes()` shares a name with `runner.read_bytes(mem, addr, n)`.
Arity discriminates them exactly — every harness read passes a `mem_type` —
and that discrimination is a regression test, because without it the rule was
unusable.

### The override

```python
# WALL-CLOCK: ok — <reason text>
```

within **3 lines** before, on, or after the flagged line. Separators: em-dash,
en-dash, `--`, ` - `, `: `. **The reason text is REQUIRED** — a bare
`# WALL-CLOCK: ok` is itself a finding, because a stamp with no reason is how
an override convention rots into a rubber stamp. Reviewers spot-check the
reasons.

Legitimate exceptions exist and this is how you express them. The ones in the
tree today:

| site | reason |
|---|---|
| `test_slice_b_audio.py` ×3, `test_runner_guard.py` ×3 | **the audio carve-out** AGENTS.md already names. An `enable_audio` runner is throttled to 60 fps, so wall and emulated time coincide by construction, and what the assertion reads is a real-time WAV |
| `conftest.py` ×2 | polling whether the **emulation thread** is stopped / has resumed. A parked core advances zero frames, so an emulated-frame wait there would block on exactly the state being detected |
| `test_map_freshness_guard.py` | filesystem **mtime granularity**. No emulator involved |
| `test_wait_primitives.py` ×2 | one polls the filesystem for Mesen's PNG with *deliberately* no emulated advance; the other's assertion **is** a real-time gap on a STOPPED machine — emulated time cannot pass at all, and the question is whether the video decoder changes the buffer anyway |

### The baseline

`reports/time_lint_baseline.json` ships as `[]`. All 56 findings were driven
to zero in the pass that landed the gate rather than grandfathered; the
mechanism stays live and tested so a future residue has somewhere honest to go.

**Prefer an override to a baseline entry.** The override keeps the reason next
to the code, where a reviewer sees it. A baseline entry is a line number in a
JSON file that nobody reads and that goes stale the moment the file is edited.

## 3. What was migrated

`MesenRunner.boot_to_frame(rom, frame)` is the primitive the migration moved to
(§5). Test-side:

- **`test_split_v_fight.py`** — the `_shot` helper photographed after 4.0 wall
  seconds; it now lands on absolute frame 240. The autodemo arc walked 40
  samples of `run_frames(12)`; it now walks 40 samples of `frame_step(12)`
  from `boot_to_frame(120)`, so it samples the same 40 instants of the demo on
  every host — and its assertions are *"a merged frame occurred"* and *"the
  fighters swapped sides"*, exactly the shape that passes or fails on which
  instants were sampled. The wall-clamp test held LEFT for a wall budget a
  loaded box could under-deliver; its assertion is *"two stills a second apart
  are identical"*, which fails if the fighters were still walking.
- **`test_slice_b_audio.py`** — the boot was not part of the audio carve-out
  (nothing is recording during a boot) and became `boot_rom(frames=120)`.
- **`test_split_h_2p_sprites.py`** — module boot.

Tool-side: four `measure_*` scripts moved `run_to_break(timeout_s=30)` →
`max_frames=600` (a `False` is now a claim about the ROM, not about the host);
`measure_cpu_store_vblank`'s poll loop → `wait_frames(1)`; `shot_microzero`
photographs absolute frame 180 so two runs of it are diffable;
`record_gallery_clip`'s `--settle` is now emulated frames.

## 4. What this lint does **NOT** catch

Every gate in this repo states its own limits; one that does not is worse than
none.

1. **Single-file, single-function.** `free-run-read`'s park model is per
   function body. A fixture that parks the core and yields it to a test
   function is invisible from that test — the read there reads as
   unparked-but-not-wall-advanced, which is not a finding. This direction
   fails **safe** (no false positive) and **blind** (no catch).
2. **It does not see across the call boundary.** `D.enter_race(runner, syms)`
   may sleep, park, or resume; the lint does not open it. Helper modules
   (`tests/mz_drive.py`, `tests/plf_drive.py`, `tools/*.py`) are themselves
   scanned, so a sleep is found where it is *written* — but the caller's park
   state is not modelled through the call.
3. **It cannot see a budget that is already a number.** `frame_step(30)` where
   the scene needs 40 is a wrong constant, not a wall-clock coupling, and no
   static rule distinguishes them.
4. **It does not know whether a capture lands on an ABSOLUTE frame.** A boot
   that free-runs `wait_frames(120)` and captures is clean here and still
   host-dependent by ±2 frames, because `wait_frames` returns `>= n`. That is
   `boot_to_frame`'s job. **The two are complementary and neither subsumes the
   other** — a module can pass `time-check` and still be load-sensitive, which
   is the most important sentence in this document.
5. **New wall-clock vocabulary is invisible.** `time.monotonic()` deadlines,
   `threading.Event.wait(timeout=)`, `subprocess(timeout=)`, `select` are NOT
   flagged. Every one of them appears in this tree for legitimate
   process-orchestration reasons (`test_bare_check.py`,
   `test_repo_tree_lock.py`), and flagging them would have produced a baseline
   of noise that teaches people to ignore the gate. The five names it does
   know are the ones that couple a *test of the emulator* to the host.
6. **`vendor/` is out of scope, deliberately.** `mesen_runner.py` *implements*
   the wall-clock primitives. A gate that flags its own subject is noise.

## 5. `boot_to_frame` — landing on an absolute frame

`boot_rom(rom, frames=N)` bounds the boot in emulated frames, which is already
immune to how *fast* the host is — but it lands on `>= N`, not on `N`.
`wait_frames`' 1 ms poll can miss a frame boundary, and the gap between it
returning and a subsequent break landing is a host-load question. **Measured
on one box: a fixed free-run budget landed on frame 90, 91 or 92 under
contention against a flat 91 when idle.**

Two frames is nothing to a test that reads a settled value and the whole
ballgame to a test that reads the **picture**. The microzero race render's
near rows sit on the black/white start-finish checker, so scanline 223 carries
white on some landings and not others:
`test_both_edge_scanlines_carry_their_declared_tint` failed *"stray
{(255, 255, 255)}"* **2 runs in 6** under 10 spinners on 4 cores while passing
every time on an idle box. The gradient was never wrong. The frame was a
different frame.

`boot_to_frame(rom, frame, margin=20)` free-runs `frame - margin` (fast, and
the slop there is harmless), parks, and **steps** the last `margin` frames
(exact). Every host then renders the same picture. Stepping cannot go
backwards, so an overshoot is an **assert**, not a silent clamp — a clamp
would quietly hand the host back the decision about which frame you
photographed.

## 5.1 The measurement — what the two boots actually land on

Pass/fail under load is a blunt instrument (a tolerant assertion hides a
non-deterministic boot). The sharp measurement is what the boot LANDS ON and
what it PHOTOGRAPHS. Six reps of each style, under 12 spinners on 4 cores (3x
oversubscription), against `build/sv_autodemo.sfc` — a **moving** scene:

| boot | distinct landing frames | distinct PNGs |
|---|---|---|
| `load_rom(rom, run_seconds=4.0)` | **6** — 218, 240, 261, 300, 313, 337 | **5** |
| `boot_to_frame(rom, 120)` | **1** — 120, every rep | **1** |

A 119-frame spread is two seconds of game time. The same probe against
`sv_hold_split.sfc` — a **still** scene — gives 6 distinct frames and 1 PNG,
which is the honest control: the PNG stability there comes from the ROM not
moving, not from the boot. That is exactly why "the test passes anyway" is not
evidence that the boot is deterministic.

**Where load-sensitivity did NOT reproduce, stated plainly.** `test_platformer`,
`test_shmup`, `test_measure_vblank` and `test_park_guard` — the four modules
that had historically gone red — ran 3/3 green at 3x on that box, and
`test_split_v_fight` ran 4/4 green at 3x on its PRE-migration code. The fixes
that landed earlier (the frame-walk stall guard, the capture park, the shmup
drift-test rewrite) hold. The migrations here are justified by the
determinism table above, not by a red they turned green.

## 6. Verified

- Lint falsification: a freshly planted `run_frames` inside the gate's live
  scope is refused against the shipped baseline; a planted bare
  `# WALL-CLOCK: ok` is refused *and* does not silence the finding it sits on.
  Both are pytest tests (`tests/test_no_wallclock.py`), so the gate's teeth
  are re-checked on every suite run rather than remembered.
- 23 tests over the lint, 6 fixtures (clean control, every wall-clock shape,
  free-run-read, overridden, bare stamp).

## See also

- [`docs/46_falsification_harness.md`](46_falsification_harness.md) — `make falsify`
- [`docs/44_bare_check_migration.md`](44_bare_check_migration.md) — the landing gate this one runs inside
