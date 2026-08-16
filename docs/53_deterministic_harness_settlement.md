# 53 — Settlement: the deterministic harness

> Status: LIVE — the settled deterministic-harness design — lockstep `Machine`, the two core patches, the determinism gate

**Status: SETTLED.** This document locks the decisions the test substrate is
built on. The evidence behind them is a measurement campaign into a flaky
suite; what survives that campaign is here.

## The decisions (locked)

- **D-DH1 — Lockstep-only test substrate.** Tests drive the emulator
  exclusively through a `Machine` API whose core is loaded PARKED and
  advances only by synchronous calls (`advance(frames=N)`,
  `run_until(pred, max_frames=N)`). The test-facing API has **no**
  free-run, no wall-clock waits, no debug break/resume, no timeouts — the
  properties are absent from the surface, not policed by lint. The legacy
  `MesenRunner` remains for interactive use, `tools/shot_*`, and audio.

- **D-DH2 — Two patches to the vendored Mesen core** (we build
  `MesenCore.so` from source; the fork rides `tools/setup.sh`'s pin):
  1. a **genuinely synchronous frame-advance entry** in the InteropDLL —
     returns only when the requested frames are emulated, does not route
     through the async break/resume state machine. That kills the
     lost-wakeup class at the root; `mesen_runner.py:1935`'s reissue loop is
     one of its children. Includes load-parked-at-reset semantics so
     counters/detectors arm without the two-load dance.
  2. a **power-on RAM seed knob**: `RamPowerOnState::Random` stays the
     regime (CLAUDE.md rule 5 untouched — never zero-init), seeded
     deterministically per load.

- **D-DH3 — Seeded determinism and the replay triple.** Every `Machine`
  test's trajectory is a pure function of `(ROM md5, seed, input script)`,
  and every failure prints that triple. The default suite runs one fixed,
  committed seed; a separate sweep target exercises fresh seeds
  deliberately (power-on-fidelity hunting becomes an axis, not ambient
  noise). Detector strength is preserved or improved; render-flap checks
  become controlled experiments across seeds.

- **D-DH4 — Hermetic suite (build side).** End state: tests never run
  `make` and never write the live tree; artifacts are built once by the
  runner of record and manifest-checked by a session fixture;
  build-system tests run in cloned trees. **Not yet reached** — see
  "What remains open" below.

- **D-DH5 — The determinism gate is the definition of done.**
  `make determinism` runs a migrated scope twice and requires every
  recorded read and every PNG **bit-identical** — not merely green twice.
  Each migration lands inside this gate; the gate is falsified by a
  planted wall-coupled read going red (sensitivity control).

- **D-DH6 — The first module migrated** was
  `tests/test_split_h_2p_sprites.py`, chosen because it carried a live
  desync. Exit criterion: the migrated module runs **bit-identical under 32
  burners, ≥3 consecutive runs**, on the box class where the desync was
  measured.

- **D-DH7 — Scope boundaries, stated.** The audio carve-out is unchanged
  (wall-clock by nature, quarantined, labelled). Wrong frame *constants*
  remain expressible — deterministically wrong is the accepted good
  failure mode.

## What remains open

The substrate is settled; the migration of every existing module onto it is
not. Four things are known to be outstanding, and each is a real hole rather
than a tidy-up:

1. **The determinism manifest has read escapes.** `ppu_frame_count()`,
   `writes()`/`reads()` and `get_uninitialized_reads()` are observable by a
   test but are not logged, so a value that differed across runs *without
   flipping a verdict* would leave two manifests comparing equal while
   `make determinism` pronounced the run bit-identical. The first migrated
   module uses none of them, so its D-DH5 verdict stands — but the access
   counters are the intended universal idiom, which is exactly when this
   residual stops being empty. Either add logging to those four methods, or
   state the exclusion in the gate's own docstring.

2. **`save_state()` / `from_state()` are deferred.** They are in the `Machine`
   API sketch and deliberately not shipped: nothing migrated so far needed
   them. Whoever migrates a savestate-natural module either builds them or
   records that the suite never wanted them.

3. **The build side is not hermetic yet.** Fixtures still shell out to `make`
   (which is why `-n` above one races a cold tree), build-system tests still
   plant into the live tree behind a lock, and an mtime discipline still
   props the whole thing up. D-DH4 is the end state, not the current one.

4. **The compensation stack is still load-bearing** — stall guards, the park
   guard, the wait primitives, the vacuity guards. They exist to make a
   free-running core survivable, and they retire only as their last users
   migrate. When they do, `make time-check` demotes from a gate to a style
   lint and `make determinism` widens to the full non-audio suite.

Nothing lands on the main line except by the standing landing rule:
`make bare-check` green on the exact tip, pins unmoved, artifact cited
([`docs/44`](44_bare_check_migration.md)).
