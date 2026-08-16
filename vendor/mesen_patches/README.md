# mesen_patches — the lockstep core (docs/53 D-DH2)

The two core patches the deterministic-harness settlement ratified, shipped
as files + an apply script so a fresh container reproduces the core without
this branch's author present. `bash vendor/mesen_patches/apply.sh` copies the
pristine shared tree (`/tmp/Mesen2`, never modified — it is shared with other
sessions on this box) to a private tree (`/tmp/Mesen2-lockstep`), applies
these patches, builds, verifies the exports, and caches the `.so` to
`tools/Mesen/MesenCore-lockstep.so`. `tools/setup.sh` step 3a drives it and
verifies-not-rebuilds when the core already exists.

The built core is a **superset**: every stock export is byte-for-byte the
stock behaviour (the only touched stock code path is three lines around the
debugger's break-sleep wait loop, publishing two atomics), so the legacy
`MesenRunner` runs on it unchanged. The harness binds it per-process via
`SF_MESEN_CORE` (head of `_detect_core_path`'s candidate list) or
`Machine(core_path=...)`.

## Patch 1 — synchronous frame advance (the load-bearing one)

Files: `LockstepSync.h` (new, → `Core/Debugger/`), the `Debugger.cpp` hunk of
`lockstep_core_edits.patch`, and the `LoadRomParked` / `RunFramesSync` /
`LockstepBreakSleepDepth` / `LockstepParkGeneration` exports in
`LockstepApiWrapper.cpp` (new, → `InteropDLL/`).

The stock park/release channel is a pair of bare bool writes
(`_waitForBreakResume`) racing in both directions; measured the
two children of that race (lost wakeup → core frozen with the request armed;
armed-while-running → step countdown reset mid-flight). The patch does not
replace the channel — it makes the emulation thread's position in it
observable (`breakSleepDepth` raised strictly after the thread's
`_waitForBreakResume = true` write; `parkGeneration` monotonic across
reloads), and the new entries hold the discipline the observability enables:

* **arm only against a provably-sleeping thread** (`breakSleepDepth > 0`),
  which makes the subsequent release ordered clear-after-set — the losing
  interleave is unreachable, not retried around;
* **observe completion as the monotonic generation advancing**, never as
  `IsExecutionStopped()` (whose OR with transient thread pauses is the
   conflation).

`RunFramesSync(n, parkScanline)` emulates exactly n PPU frames and returns
parked at the canonical scanline (the constant stays Python-side —
`_CANONICAL_PARK_SCANLINE`'s block comment in `vendor/mesen_runner.py` is the
semantics of record). Internally it mirrors the Python `_step_to_target` the
suite already proved: bulk 16-frame `PpuFrame` chunks phase-capped at
target−1 (the countdown's documented +1 anomaly self-corrects), then
verified single-frame `SpecificScanline` walks. The Python original's
reissue/stall machinery has no counterpart here — the race it compensated is
gone, and its waits are UNBOUNDED by design (a hung advance is a hung test:
).

`LoadRomParked(path)` replaces the Python two-load arming dance: it reuses
`InternalLoadRom`'s own `wasPaused && _debugger` contract (pause the current
console — first call in a process does one throwaway plain load to have a
console at all — then reload), so the fresh console comes up with a planted
first-instruction break, a fresh zeroed `MemoryAccessCounter`, and nothing
executed unobserved.

## Patch 2 — seedable power-on RAM

Files: the `EmuSettings.h` hunk (`ReseedRng`, one inline line) and the
`SetPowerOnSeed` / `GetPowerOnSeed` exports.

`RamState::Random` stays the regime (SuperForge rule 5: randomized RAM made
replayable, never zero-init). All power-on randomization draws from
`EmuSettings::_mt`; `LoadRomParked` reseeds it at its quiescent point (the
previous console's emulation thread provably parked, the reload about to run
on the calling thread), so the draw sequence from seed to RAM bytes is fixed
and same-seed loads are bit-identical. Seed < 0 (the default) leaves the
stock `random_device` stream untouched; plain `LoadRom` never reseeds, so
the legacy path is unchanged.

## Capture determinism (rides patch 1)

`FlushVideoFrame(timeoutMs)` + `TakeScreenshotToFile(path)` + the
`VideoDecoder.h` hunk (`IsFrameDecodePending`, one inline line). The stock
capture copies whatever frame the async decode thread last wrote — on a
parked core that is the last submitted frame *eventually*, which is a
wall-clock question the legacy harness measured at 0.4% wrong-frame under
load. The flush turns "eventually" into an observable; the to-file export
drops the Screenshots-directory diff-polling. Pixel pipeline is the stock
one (`VideoDecoder::TakeScreenshot(stringstream&)`).

## Versioning

The patches ride `tools/setup.sh`'s pin of the Mesen2 tree (shallow clone of
SourMesen/Mesen2; the tree this box carries is the one every measured number
in /45/51 was taken against). `lockstep_core_edits.patch` asserts its
context — a future tree where the hunks no longer apply is a loud failure at
apply time, not a silent drift.
