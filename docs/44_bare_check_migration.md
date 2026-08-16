# 44 — The landing gate: `make bare-check`

> Status: LIVE — what `make bare-check` proves, what it does NOT, and the landing rule that cites it

**Nothing in this repository runs automatically.** There is no push-triggered
CI. The landing gate is a thing you run, on the exact commit you are about to
land, and it produces an artifact you cite: `make bare-check`.

That is a deliberate trade. An automatic gate you do not control has two
failure modes this project has met — it costs minutes of wait per push, and
when its reds are load artefacts rather than defects it trains everyone to
disbelieve its reds, which is worse than not having it. A gate you run
yourself, that writes down exactly what it observed and exactly what it could
not, is the honest version of the same guarantee.

---

## 1. What a local `make gates` structurally cannot prove

Three properties, none of which a run in your working tree can have:

1. **Only committed content.** A `make gates` that passes against an untracked
   file passes against something a reader pulling the branch does not get. This
   is the class where "works here" and "works from a clone" diverge.
2. **No stale tree.** A `build/` full of yesterday's artifacts can make a target
   a no-op. This repo's history records the same defect escaping local runs
   **three times**: the `no_literals` channel rules broke the gated
   `probe_vblank` build, and every local `make test` passed because a stale
   `build/probe_vblank.sfc` made the target a no-op.
3. **Self-containment.** The build must need nothing beside the repo root — no
   sibling checkout, no path outside the tree.

## 2. What `make bare-check` does, and how

`tools/bare_check.sh`. It **clones the repo at HEAD** into a scratch directory
and runs the gate block *there*.

| property | mechanism |
|---|---|
| no stale tree | a fresh `git clone` has no `build/` at all |
| only committed content | a clone can only contain HEAD — and a dirty tree is **refused by name** before anything runs |
| self-containment | the clone sits alone in a scratch dir, so a build reaching outside the tree fails there |
| the gate block | `make gates`, in its own order, inside the clone |
| the extra steps | ROM size assertions + the `probe_cpu` md5 pin, restated in the script (they are not part of `make gates`) |
| a citable result | `build/bare_check.json` |

Three details are load-bearing:

- **Clone, not copy.** An `rsync` would carry uncommitted files and defeat the
  whole point.
- **`git clone --no-local`.** A session checkout may itself be shallow; a local
  hardlink clone does *not* copy `.git/shallow`, and produces a tree whose HEAD
  is right and whose history is unreadable (`git rev-list HEAD` dies with
  *"Could not read &lt;sha&gt;"*). Measured cost of the transport clone: ~4 s,
  19 MB.
- **The script asserts its own preconditions** rather than assuming them. A
  setup step that silently did not happen would make this gate weaker than it
  claims to be, which is the one failure a landing gate must not have.

### The toolchain question, and the judgement call

Rebuilding `MesenCore.so` per run is ~10 minutes, which would make the gate
unusable — and **an unusable gate gets skipped**, so "faithful but skipped" is
strictly worse than "reused and stated".

**What ships:** the clone runs its **own `tools/setup.sh`**, so the fresh-clone
bring-up path is exercised for real. `setup.sh` is verify-then-install, so on a
box that already has them it finds `ca65`/`ld65`, Pillow, pytest and the
already-built `/tmp/Mesen2` core and installs nothing (~7 s). The residue is
that "no toolchain" is verified as *"setup.sh's verification path passes"*, not
as *"it bootstrapped from nothing"*.

## 3. What is NOT proved — stated, not implied

`make bare-check` runs on the same box you are on. It does **not** give you:

- **a genuinely different machine** — same kernel, same CPU, same everything;
- **a genuinely absent toolchain** — see above;
- **a different OS image**;
- **full git history.** The bare-check clone inherits this repo's depth, so
  `test_register.py::test_drift_fixtures_match_git_history` **SKIPS** where a
  full checkout would run it. Only the *consistency* check skips; the drift
  fixtures themselves are hermetic and run.

Every one of these is recorded in `build/bare_check.json` under
`isolation.not_reproduced`, so citing the artifact cannot imply parity it does
not have.

**When the residue matters** — a change touching `vendor/`, the Makefile or
`tools/setup.sh`, i.e. anything whose failure mode is "works here, not on a
clean machine" — build it on a genuinely clean machine before landing, and say
in the landing note that you did.

## 4. The load-sensitivity that makes a gate's reds meaningless

A gate is only worth its reds. Five instances of a red that meant nothing about
the code are recorded here because the first of them was a defect in a **gate**:

1. **`tests/test_park_guard.py::test_core_is_parked_tracks_the_emulator_not_a_flag`**
   — the guard called a **free-running** core PARKED.
   `conftest.core_is_parked()` was `bool(lib.IsExecutionStopped())`, and Mesen
   defines that as `_executionStopped || _emu->IsThreadPaused()`
   (`Core/Debugger/Debugger.cpp:738`), with `IsThreadPaused()` =
   `!_emuThread || _threadPaused` and `_threadPaused` set inside
   `WaitForLock()` whenever *any* caller holds the emulator lock
   (`Core/Shared/Emulator.cpp:876`, `895`). The predicate answers "not
   executing right now", which is not "the debugger parked this".
   **Fixed** by keeping the cheap call as a fast negative and, when it says
   stopped, asking the machine — sampling the PPU `(frame, scanline)` pair over
   a bounded window. Measured with the disjunct planted on a free-running core:
   old → `True` (the red), new → `False` in 0.000 s; genuinely parked →
   `True` in 0.751 s. Planted as a regression test.
2. **A frame-walk timeout** — `TimeoutError: frame walk timed out (frame 153,
   scanline 224)` out of `test_platformer.py::test_every_animation_frame_…`.
   The test's own loop is bounded in emulated frames; the **wall bound was
   underneath it**, in `MesenRunner._await_step`, as a total budget.
   **Fixed** by making it a stall guard (observed scanlines push the deadline
   out; a reissue deliberately does not), matching `wait_frames`'s `stall_s`.
   Measured: `frame_step(60, timeout_s=0.3)` now completes in 0.30 s where it
   used to raise; a planted wedge still fails, bounded, in 30 s.
3. **`test_microzero_gradient::test_both_edge_scanlines_carry_their_declared_tint`**
   — "scanline 223 … stray `{(255,255,255)}`", 2 runs in 6 under load, green
   every time idle. Not the gradient: the near rows sit on the black/white
   start-finish **checker**, so white on scanline 223 depends on where the
   track is — and the fixture free-ran a frame budget, which `wait_frames`
   documents as "≥ n". **Fixed** by landing on an exact absolute frame.
   6/6 green under the load that used to produce 2 failures in 6.
4. **`test_measure_vblank`** — the same starvation, surfacing as the harness's
   30 s frozen-counter guard. Green after (2) and the stall-window alignment;
   verified cold under 3× CPU oversubscription.
5. **`test_shmup::test_the_field_drifts_down_on_screen`** — found by
   bare-check's own first run. It tracked the column's *topmost* non-sky pixel,
   a proxy that equals "the field moved 16" only while nothing enters the
   column from above. **Fixed** by matching the column's whole profile.

**Honest residue.** At **3× CPU oversubscription** (12 spinners on 4 cores) the
Mesen emulation thread can genuinely go tens of seconds without producing a
scanline; the harness then reports a stall, correctly. That is the host, not
the ROM, and the diagnostic says so instead of asserting "this is a WEDGE, not
a slow host". **Do not run `make bare-check` against a hammered box, and do not
run `make test` alongside it** — bare-check runs a suite of its own.

## 5. The landing rule

**`make bare-check` green on the exact tip, with the result cited.**

Cite it from `build/bare_check.json` — the SHA, the UTC timestamp, the per-gate
verdicts, the suite summary line and the eight ROM md5s. The point of the rule
is an independent observation, on the exact commit, that is quotable rather
than remembered — and what that observation cannot see is written into the
artifact it produces.

## See also

- `tools/bare_check.sh` — the implementation, and why each step is there.
- `tests/test_bare_check.py` — the plants: it is not a gate until it has been
  broken on purpose.
