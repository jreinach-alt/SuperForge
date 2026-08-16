#pragma once
#include <atomic>
#include <cstdint>

// SuperForge lockstep-harness observability (docs/53 D-DH2 patch 1; applied by
// vendor/mesen_patches/apply.sh into Core/Debugger/).
//
// The stock debugger's park/release channel is a pair of bare bool writes
// (_waitForBreakResume) racing in both directions: the API thread clears it
// to release a step, the emulation thread sets it when entering its break
// sleep, and nothing orders the two. When the clear lands BEFORE the set,
// the wakeup is consumed and the emulation thread sleeps forever with the
// step request armed — the lost-wakeup class SuperForge's signature D
// measured, and the reason every Python-side step/resume call site grew a
// reissue loop.
//
// These two atomics do not replace that channel — they make the emulation
// thread's position in it OBSERVABLE, which is what a genuinely synchronous
// frame-advance entry needs:
//
//  (a) refuse to arm a step request unless the emulation thread is provably
//      INSIDE the break-sleep wait loop (breakSleepDepth > 0). By program
//      order on the emulation thread, depth is raised only after
//      _waitForBreakResume was set, so an arm-then-clear that happens after
//      observing depth > 0 can never be the losing side of the race — and a
//      request can never be armed against a still-running CPU (the re-arm
//      mid-run overshoot, the other half of the class).
//
//  (b) wait for step completion by watching a monotonic generation counter
//      (parkGeneration) instead of re-deriving "stopped" from
//      IsExecutionStopped(), whose OR with Emulator::IsThreadPaused()
// reports transient lock pauses as parks (the conflation).
//      A monotonic counter polled from the waiting side cannot lose a
//      wakeup: the waiter re-reads state, never consumes a signal.
//
// Process-global rather than Debugger members, deliberately: a ROM reload
// builds a fresh Debugger, and the generation counter must stay monotonic
// across that boundary so a waiter armed before the reload observes the new
// console's first park. (Members would also change the class layout, which
// this makefile — no header dependency tracking — must never see.)
namespace MesenLockstep
{
	// > 0 while the emulation thread is inside SleepUntilResume's wait
	// loop, i.e. genuinely parked, past the point where _waitForBreakResume
	// was set. NOT the same as IsExecutionStopped().
	extern std::atomic<uint32_t> breakSleepDepth;

	// Incremented once each time the emulation thread ENTERS the wait loop.
	// A caller that records g before releasing a step observes completion
	// as parkGeneration > g (with breakSleepDepth > 0 confirming the park
	// is still held).
	extern std::atomic<uint64_t> parkGeneration;
}
