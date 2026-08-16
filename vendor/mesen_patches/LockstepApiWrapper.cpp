// SuperForge lockstep-harness InteropDLL entry points (docs/53 D-DH2; applied by
// vendor/mesen_patches/apply.sh into InteropDLL/). Everything here is
// ADDITIVE: no stock export changes behaviour, and a legacy MesenRunner on
// this core sees exactly the core it always saw.
//
// The design constraint, from SuperForge P3 /: a frame
// advance that RETURNS ONLY WHEN THE FRAMES ARE EMULATED, and that does not
// round-trip through the async break/resume request machinery's racing bool
// channel unguarded. The stock machinery's two failure modes (measured in
// SuperForge):
//
//   * lost wakeup — Debugger::Step / Run clears _waitForBreakResume BEFORE
//     the emulation thread sets it on its way into SleepUntilResume; the
//     release is consumed and the core sleeps forever with the request
//     armed;
//   * armed-while-running — DebugBreakHelper's entry spin exits on
//     IsExecutionStopped()'s conflation with transient thread pauses, so a
//     step request is re-armed against a RUNNING cpu and resets the
//     countdown mid-flight (the overshoot the Python harness's reissue
//     throttle exists to avoid).
//
// Both are killed by one precondition made checkable by the LockstepSync
// patch: ONLY arm a step while MesenLockstep::breakSleepDepth > 0 — the
// emulation thread is provably inside the wait loop, past its
// _waitForBreakResume=true write — and observe completion as the monotonic
// MesenLockstep::parkGeneration advancing. Polling a monotonic counter from
// the waiting side cannot lose a wakeup; there is nothing to consume.
//
// Threading contract: these entries are for a SINGLE api-thread client (the
// SuperForge Machine — one Python thread). They are not made concurrency-safe
// against other simultaneous debugger API callers, and do not need to be:
// the Machine holds the only reference and never overlaps calls.
#include "Common.h"
#include "Core/Shared/Emulator.h"
#include "Core/Shared/EmuSettings.h"
#include "Core/Shared/Video/VideoDecoder.h"
#include "Core/Shared/DebuggerRequest.h"
#include "Core/Debugger/Debugger.h"
#include "Core/Debugger/DebugTypes.h"
#include "Core/Debugger/LockstepSync.h"
#include "Core/SNES/SnesPpuTypes.h"
#include "Utilities/VirtualFile.h"

#include <atomic>
#include <chrono>
#include <fstream>
#include <sstream>
#include <thread>

extern unique_ptr<Emulator> _emu;

// Pending power-on seed (docs/53 D-DH2 patch 2). -1 = unseeded: the stock
// random_device-seeded stream, i.e. exactly the pre-patch behaviour. Applied
// (a) inside LoadRomParked, at a point where the previous console's
// emulation thread is provably parked, so the draw sequence between reseed
// and the new console's RAM randomization is identical on every load; and
// (b) by plain LoadRom callers never — the legacy path is untouched.
static std::atomic<int64_t> s_powerOnSeed{-1};

namespace
{
	// Error codes shared by the exports below (0 = success). Kept negative
	// and distinct so the Python side can raise precise failures.
	constexpr int32_t kErrNoRom = -1;
	constexpr int32_t kErrNoDebugger = -2;
	constexpr int32_t kErrNotParked = -3;
	constexpr int32_t kErrLoadFailed = -4;
	constexpr int32_t kErrParkNeverLanded = -5;
	constexpr int32_t kErrBulkOvershoot = -6;
	constexpr int32_t kErrWalkOvershoot = -7;
	constexpr int32_t kErrNotAtPark = -8;

	Debugger* GetDbg(DebuggerRequest& req)
	{
		return req.GetDebugger();
	}

	void ReadPpu(Debugger* dbg, uint32_t& frame, uint32_t& scanline)
	{
		SnesPpuState state = {};
		dbg->GetPpuState(state, CpuType::Snes);
		frame = state.FrameCount;
		scanline = state.Scanline;
	}

	bool ParkedInSleep()
	{
		return MesenLockstep::breakSleepDepth.load(std::memory_order_acquire) > 0;
	}

	// A REAL park, as distinct from the transient break-request park that
	// exists inside a DebugBreakHelper window. SleepUntilResume enters its
	// wait loop on two paths: the notification path (a step/pause landed —
	// _waitForBreakResume set true first, so Emulator::IsPaused() reads
	// true for the whole park) and the breakRequestCount-only path (a
	// helper is holding the thread momentarily — _waitForBreakResume stays
	// false). The first smoke run of LoadRomParked exited its pause wait on
	// the transient park, read IsPaused()==false at the reload, and the
	// power-on break was never planted; requiring both closes that hole,
	// and every park the lockstep entries produce is the notification kind.
	bool ParkedForReal()
	{
		return ParkedInSleep() && _emu->IsPaused();
	}

	// Wait until the emulation thread is inside the break-sleep loop with a
	// park generation newer than `gen`. Polls a monotonic counter — the
	// waiting side re-reads state, so no wakeup can be lost. UNBOUNDED by
	// design (: a hung advance is a hung test and should present
	// as one, not be converted into a guessed verdict by a wall guard).
	void AwaitParkAfter(uint64_t gen)
	{
		while(!(MesenLockstep::parkGeneration.load(std::memory_order_acquire) > gen && ParkedForReal())) {
			std::this_thread::sleep_for(std::chrono::microseconds(100));
		}
	}

	// Arm a step request and wait for the resulting park. PRECONDITION:
	// ParkedInSleep() — the caller verified it; this is what makes the
	// arm+release race-free (see the file header).
	void StepAndAwait(Debugger* dbg, int32_t count, StepType type)
	{
		uint64_t gen = MesenLockstep::parkGeneration.load(std::memory_order_acquire);
		// Debugger::Step is the stock arm+release primitive: BreakHelper's
		// entry spin exits immediately (genuinely parked, _executionStopped
		// true), the request is armed against a non-executing cpu, and the
		// _waitForBreakResume clear lands strictly AFTER the emulation
		// thread's set (program order: set -> depth++ -> we observed
		// depth > 0). The 1 ms poll inside the wait loop picks the clear up.
		dbg->Step(CpuType::Snes, count, type);
		AwaitParkAfter(gen);
	}

	// One verified frame walk to `parkScanline` — the C++ mirror of the
	// Python harness's _walk_one_frame, minus the reissue machinery (whose
	// reason to exist this file removes). Returns the frame delta (0 or 1)
	// or a negative error. Delta 0 = the walk started past the frame-count
	// increment (scanline parkScanline+1..261) and only normalized the
	// position; the caller loops.
	int32_t WalkOneFrame(Debugger* dbg, uint32_t parkScanline)
	{
		uint32_t f0, sl0;
		ReadPpu(dbg, f0, sl0);
		StepAndAwait(dbg, (int32_t)parkScanline, StepType::SpecificScanline);
		uint32_t f1, sl1;
		ReadPpu(dbg, f1, sl1);
		if(sl1 != parkScanline) {
			// A SpecificScanline park that is not at its own target
			// scanline — with the armed-while-running path closed this is
			// unreachable; report rather than loop blind.
			return kErrNotAtPark;
		}
		int32_t delta = (int32_t)(f1 - f0);
		if(delta != 0 && delta != 1) {
			return kErrWalkOvershoot;
		}
		return delta;
	}
}

extern "C" {
	// --- Observability ------------------------------------------------------

	DllExport uint32_t __stdcall LockstepBreakSleepDepth()
	{
		return MesenLockstep::breakSleepDepth.load(std::memory_order_acquire);
	}

	DllExport uint64_t __stdcall LockstepParkGeneration()
	{
		return MesenLockstep::parkGeneration.load(std::memory_order_acquire);
	}

	// --- Patch 2: seedable power-on RAM ------------------------------------

	// Sets the pending power-on seed consumed by every subsequent
	// LoadRomParked. RamState stays Random (SuperForge rule 5 — randomized RAM
	// made REPLAYABLE, not zero-init): the randomizer still runs, drawing
	// from a deterministically-seeded stream. seed < 0 restores the stock
	// unseeded behaviour.
	DllExport void __stdcall SetPowerOnSeed(int64_t seed)
	{
		s_powerOnSeed.store(seed, std::memory_order_release);
	}

	DllExport int64_t __stdcall GetPowerOnSeed()
	{
		return s_powerOnSeed.load(std::memory_order_acquire);
	}

	// --- Patch 1: parked load + synchronous frame advance ------------------

	// Load a ROM and come up PARKED at the planted power-on break: a fresh
	// console, a fresh debugger (access counters zeroed and live from the
	// reset vector — nothing runs unobserved), the emulation thread inside
	// its break sleep after one instruction. Replaces the Python-side
	// two-load arming dance (load_rom_with_uninit_detection) for Machine
	// users; the mechanism is the same InternalLoadRom wasPaused && debugger
	// contract that dance already relies on, driven here with the race-free
	// observability instead of IsExecutionStopped() polling.
	//
	// The FIRST call in a process performs one throwaway plain load to bring
	// up a console (a debugger cannot exist without one). That throwaway
	// boots free-running for the few milliseconds until the pause lands —
	// exactly as the legacy dance's step-1 load does — and is then fully
	// reloaded; its counter history is discarded with it.
	DllExport int32_t __stdcall LoadRomParked(char* filename)
	{
		if(!_emu->IsRunning()) {
			if(!_emu->LoadRom((VirtualFile)filename, VirtualFile())) {
				return kErrLoadFailed;
			}
		}
		{
			// Ensure a debugger exists (GetDebugger(true) auto-inits). The
			// DebuggerRequest is scoped and DROPPED here: InternalLoadRom's
			// BlockDebuggerRequests() waits for every outstanding request to
			// drain, so a request held across the LoadRom below deadlocks
			// against our own hand (measured: the first smoke run of this
			// entry hung exactly there).
			DebuggerRequest req = _emu->GetDebugger(true);
			if(!GetDbg(req)) {
				return kErrNoDebugger;
			}
		}

		// Ensure the CURRENT console's emulation thread is parked in the
		// sleep loop, so (a) IsPaused() is true at the reload (what plants
		// the power-on break) and (b) nothing draws from the settings RNG
		// between the reseed below and the new console's RAM init. Pause()
		// routes to a 1-instruction debugger step; arming it against a
		// running cpu is safe (park-entry has no wakeup to lose), and a
		// 200 ms reissue covers a request the running cpu missed. The
		// bounded window converts a wedged bring-up into an ERROR CODE —
		// this is setup, not a test-path wait.
		if(!ParkedForReal()) {
			auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
			_emu->Pause();
			auto lastIssue = std::chrono::steady_clock::now();
			while(!ParkedForReal()) {
				auto now = std::chrono::steady_clock::now();
				if(now > deadline) {
					return kErrNotParked;
				}
				if(now - lastIssue > std::chrono::milliseconds(200)) {
					_emu->Pause();
					lastIssue = now;
				}
				std::this_thread::sleep_for(std::chrono::microseconds(200));
			}
		}

		// Quiescent point: reseed the power-on RNG (patch 2). Every draw
		// between here and the new console's InitializeRam happens on THIS
		// thread inside LoadRom, in a fixed order — same seed, same
		// power-on bytes, every load.
		int64_t seed = s_powerOnSeed.load(std::memory_order_acquire);
		if(seed >= 0) {
			_emu->GetSettings()->ReseedRng((uint32_t)seed);
		}

		uint64_t gen = MesenLockstep::parkGeneration.load(std::memory_order_acquire);
		if(!_emu->LoadRom((VirtualFile)filename, VirtualFile())) {
			return kErrLoadFailed;
		}

		// The reload built a fresh console + debugger and planted a
		// first-instruction break before starting the emulation thread
		// (InternalLoadRom: needPause = wasPaused && _debugger). Wait for
		// that thread to land in the sleep loop. Bounded for the same
		// reason as above: a park that never lands here is a broken load,
		// not a slow host, and must present as a code.
		auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
		while(!(MesenLockstep::parkGeneration.load(std::memory_order_acquire) > gen && ParkedForReal())) {
			if(std::chrono::steady_clock::now() > deadline) {
				return kErrParkNeverLanded;
			}
			std::this_thread::sleep_for(std::chrono::microseconds(200));
		}
		return 0;
	}

	// Emulate exactly `frameCount` PPU frames and return only when they are
	// emulated, leaving the core parked at `parkScanline` (the caller passes
	// the canonical park scanline — the semantics live in ONE place, the
	// Python harness; see _CANONICAL_PARK_SCANLINE's block comment there).
	//
	// Two phases, the C++ mirror of the Python _step_to_target the suite
	// already proved: bulk PpuFrame chunks (fast, but the PpuFrame countdown
	// can deterministically MISS a tick on DMA-heavy frames and run one
	// frame long), capped at 16 frames, recomputed from the live counter,
	// phase-capped at target-1 so a +1 anomaly cannot pass the target; then
	// exact SpecificScanline walks, one verified frame at a time. The
	// reissue/stall machinery of the Python original does not exist here —
	// its reason (the unguarded arm) is removed by construction.
	//
	// PRECONDITION: the core is parked in the break sleep (LoadRomParked or
	// a previous RunFramesSync left it there). Input overrides latched
	// before this call are polled at each frame boundary, exactly as the
	// legacy frame_step contract documents.
	DllExport int32_t __stdcall RunFramesSync(uint32_t frameCount, uint32_t parkScanline)
	{
		if(!_emu->IsRunning()) {
			return kErrNoRom;
		}
		DebuggerRequest req = _emu->GetDebugger(true);
		Debugger* dbg = GetDbg(req);
		if(!dbg) {
			return kErrNoDebugger;
		}
		if(!ParkedForReal()) {
			return kErrNotParked;
		}

		uint32_t start, sl;
		ReadPpu(dbg, start, sl);
		uint32_t target = start + frameCount;

		// Phase 1: bulk.
		while(true) {
			uint32_t cur;
			ReadPpu(dbg, cur, sl);
			if(cur >= target - 1) {
				break;
			}
			uint32_t chunk = std::min<uint32_t>(16, (target - 1) - cur);
			StepAndAwait(dbg, (int32_t)chunk, StepType::PpuFrame);
			uint32_t now;
			ReadPpu(dbg, now, sl);
			if(now > target) {
				return kErrBulkOvershoot;
			}
		}

		// Phase 2: exact walks to target, ending at the canonical park.
		while(true) {
			uint32_t cur;
			ReadPpu(dbg, cur, sl);
			if(cur >= target) {
				if(cur > target) {
					return kErrWalkOvershoot;
				}
				break;
			}
			int32_t r = WalkOneFrame(dbg, parkScanline);
			if(r < 0) {
				return r;
			}
		}

		// Normalize the park point (the bulk phase can land past the
		// canonical scanline when the +1 anomaly ended it exactly at
		// target). Never crosses another frame-count increment: from
		// 0..parkScanline-1 the walk stays inside the frame; from
		// parkScanline+1..261 the increment already happened.
		uint32_t fc0;
		ReadPpu(dbg, fc0, sl);
		if(sl != parkScanline) {
			StepAndAwait(dbg, (int32_t)parkScanline, StepType::SpecificScanline);
			uint32_t fc1;
			ReadPpu(dbg, fc1, sl);
			if(sl != parkScanline || fc1 != fc0) {
				return kErrNotAtPark;
			}
		}
		return 0;
	}

	// --- Deterministic capture support -------------------------------------

	// Block until the video decode thread has consumed the last submitted
	// frame (VideoDecoder::_frameChanged false). On a parked core the
	// submit stream is quiescent, so this converging is a bounded-latency
	// certainty, not a race — the bound exists to convert a genuinely dead
	// decode thread into a legible false return. After this returns true,
	// the composite buffer deterministically holds the last SUBMITTED
	// frame, and a TakeScreenshot* copies exactly that frame's pixels.
	DllExport bool __stdcall FlushVideoFrame(uint32_t timeoutMs)
	{
		VideoDecoder* vd = _emu->GetVideoDecoder();
		if(!vd) {
			return false;
		}
		auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
		while(vd->IsFrameDecodePending()) {
			if(std::chrono::steady_clock::now() > deadline) {
				return false;
			}
			std::this_thread::sleep_for(std::chrono::microseconds(100));
		}
		return true;
	}

	// Write the current composite frame as a PNG to an explicit path — no
	// Screenshots/ directory, no incrementing counter, no directory-diff
	// polling on the Python side. Uses the stock stream-capture path
	// (VideoDecoder::TakeScreenshot(stringstream&)), so the pixel pipeline
	// is byte-identical to the stock file capture.
	DllExport bool __stdcall TakeScreenshotToFile(char* path)
	{
		VideoDecoder* vd = _emu->GetVideoDecoder();
		if(!vd || !path) {
			return false;
		}
		std::stringstream ss;
		vd->TakeScreenshot(ss);
		std::string data = ss.str();
		if(data.empty()) {
			return false;
		}
		std::ofstream f(path, std::ios::binary | std::ios::trunc);
		if(!f) {
			return false;
		}
		f.write(data.data(), (std::streamsize)data.size());
		f.close();
		return f.good();
	}
}
