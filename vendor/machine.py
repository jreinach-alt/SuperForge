"""Machine — the lockstep test substrate (docs/53 D-DH1).

The emulator as a subroutine of the test: the core is loaded PARKED and only
ever advances by synchronous calls from the test thread. There is no
``run_frames``, no ``run_seconds=``, no ``debug_break``/``debug_resume``, no
``timeout_s=``, no ``set_input`` against a moving core — **absent from the
API, not forbidden by a lint**. Sequencing is program order; every read and
every screenshot is taken from a parked exact frame; the whole trajectory is
a pure function of the replay triple ``(rom md5, seed, input script)``,
which every Machine failure prints.

Substrate: the eight lockstep exports of the patched core built by
``vendor/mesen_patches/apply.sh`` (bind it with ``SF_MESEN_CORE`` or the
``core_path`` parameter — the stock shared core at /tmp/Mesen2 lacks them
and is never patched in place). ``LoadRomParked`` brings a fresh console up
parked at the planted power-on break with access counters live from the
reset vector; ``RunFramesSync`` emulates exactly N frames and returns parked
at the canonical scanline. Neither round-trips through the async
break/resume machinery unguarded — see ``vendor/mesen_patches/README.md``
for the mechanism and ``_CANONICAL_PARK_SCANLINE``'s block comment in
``mesen_runner.py`` for the park-point semantics (they are REUSED here, not
re-derived: WRAM coherent, OAM/VRAM one committed frame behind, input
latched at the park polled at the very next boundary).

The legacy ``MesenRunner`` is untouched and remains the interactive /
``tools/shot_*`` / audio substrate. This module deliberately reuses its
process-global core bootstrap, its ``MemoryType`` enum, its G2/G3
read-log + mutation hooks (a Machine read is an output-region access like
any other), and its input struct — one core, one init, two driving models.

Wall-clock note (docs/45): nothing in this file calibrates a VERDICT
against host time. The bounded sleeps inside the C++ entries and close()
are release-latency polls on a monotonic condition, not measurements.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

# The well-known home of the patched core (vendor/mesen_patches/apply.sh).
# The default binding when nothing chose a core yet: an explicit
# SF_MESEN_CORE (honoured inside _detect_core_path) or an already-imported
# mesen_runner always precedes this. tests/conftest.py makes the same
# choice for whole pytest runs. Defined BEFORE the mesen_runner import
# because the export block below needs it.
_LOCKSTEP_CORE_WELL_KNOWN = "/tmp/Mesen2-lockstep/InteropDLL/obj.linux-x64/MesenCore.so"

# H-1: export this module's core resolution BEFORE importing
# mesen_runner, whose import-time preload dlopens _DEFAULT_CORE_PATH
# immediately (mesen_runner.py's _eager_preload_mesen_core, needed to claim
# the loader's TLS slots ahead of scipy). Without this, an unset
# SF_MESEN_CORE meant the preload dlopened the STOCK core while
# Machine.__init__ initialized the LOCKSTEP one — two builds of one C++
# singleton in one process, a guaranteed SEGFAULT with no traceback

# Exporting here makes the preload and the real load the same file by
# construction — what tests/conftest.py does for pytest sessions, moved to
# where the choice is actually made. Guarded on mesen_runner NOT being
# imported yet: after its import the preload has already happened, and
# exporting a path it never saw would only desynchronize
# _default_core_path() from the preloaded file (the __init__ guard below
# turns that arrival order into a legible MachineError instead).
if ("mesen_runner" not in sys.modules
        and not os.environ.get("SF_MESEN_CORE", "").strip()
        and os.path.exists(_LOCKSTEP_CORE_WELL_KNOWN)):
    os.environ["SF_MESEN_CORE"] = _LOCKSTEP_CORE_WELL_KNOWN

import mesen_runner as _mr
from mesen_runner import MemoryType  # re-exported for Machine users

__all__ = ["Machine", "MachineError", "MemoryType", "DEFAULT_POWERON_SEED"]

# The committed default power-on seed (docs/53 D-DH3): ONE fixed value the
# whole default suite runs, so a red replays anywhere. Env-overridable for
# deliberate sweeps (``SF_POWERON_SEED=7 make seeds`` — material);
# the override is read once at import, like the SF_* knobs in mesen_runner.
DEFAULT_POWERON_SEED = int(os.environ.get("SF_POWERON_SEED", "0x5F0426") or "0x5F0426", 0) \
    if str(os.environ.get("SF_POWERON_SEED", "")).strip() else 0x5F0426

_PARK_SCANLINE = _mr._CANONICAL_PARK_SCANLINE

def _default_core_path() -> str:
    """Which core this Machine should bind, in precedence order.

    A MISSPELLED ``SF_MESEN_CORE`` used to degrade in
    silence. ``_detect_core_path`` (mesen_runner.py) honours the override
    only when the file EXISTS and otherwise falls through to the stock
    candidate order; this function tested the variable for truthiness
    alone. The two agreed on the fallback, so nothing broke — the user just
    got the stock core and, one frame later, "it is the stock core. Build
    the patched one", which sends them to rebuild a core they had already
    built and merely mistyped the path to. An explicitly-requested core
    that does not exist is a request this module cannot honour, so it says
    so instead of quietly substituting a different one.
    """
    override = os.environ.get("SF_MESEN_CORE", "").strip()
    if override and not os.path.exists(override):
        raise MachineError(
            f"SF_MESEN_CORE names a file that does not exist:\n"
            f"    {override}\n"
            "so the core binding you asked for cannot be honoured. (The "
            "legacy resolver falls back to the stock core here, which is "
            "why this used to surface as the misleading 'it is the stock "
            "core. Build the patched one'.) Fix: correct the "
            "path, or unset SF_MESEN_CORE to take the lockstep core at\n"
            f"    {_LOCKSTEP_CORE_WELL_KNOWN}\n"
            "(build it with `bash vendor/mesen_patches/apply.sh`)."
        )
    if _mr._GLOBAL_INIT_DONE:
        return _mr._GLOBAL_INIT_PARAMS[0]
    if override:
        return _mr._DEFAULT_CORE_PATH  # already honours the env override
    if os.path.exists(_LOCKSTEP_CORE_WELL_KNOWN):
        return _LOCKSTEP_CORE_WELL_KNOWN
    return _mr._DEFAULT_CORE_PATH


class MachineError(RuntimeError):
    """A lockstep-entry failure, carrying the replay triple."""


# --- the determinism manifest (docs/53 D-DH5) -------------------
#
# When SF_DETERMINISM_LOG names a file, every Machine event that a test can
# observe is appended to it in program order: loads (rom md5 + seed),
# advances (frames + both pads), reads and writes (region, addr, count, and
# a sha1 of the bytes as the test saw them), captures (sha1 of the PNG
# bytes), and H-2, closing the read
# escapes — the counter/clock queries: `ppu_frame_count` (the value),
# `writes`/`reads` (region, addr, the count value), and `uninit`
# (queried types, total hits, sha1 of the full result dict); plus
# `memory_size` (region, the value), which closes the last
# public read with no record. The invariant is now checkable in one pass:
# EVERY public read on Machine appends here. Internal plumbing does not —
# `_memory_size` is the unlogged path the read/uninit implementations use,
# because their own record already covers what they computed. `make
# determinism` runs a module twice into two such manifests and requires
# them BYTE-IDENTICAL — the property D-DH5 defines as done. Hashes
# rather than raw bytes keep a full-module manifest small; program order is
# well-defined because the gate runs single-process (this recorder is not
# xdist-aware and does not need to be).
_DET_LOG_PATH = os.environ.get("SF_DETERMINISM_LOG", "").strip()
_DET_LOG_FH = None


def _det_log(*record):
    global _DET_LOG_FH
    if not _DET_LOG_PATH:
        return
    if _DET_LOG_FH is None:
        _DET_LOG_FH = open(_DET_LOG_PATH, "a", buffering=1)
    _DET_LOG_FH.write(json.dumps(record) + "\n")


def _bind_lockstep(lib: ctypes.CDLL) -> ctypes.CDLL:
    """Bind the lockstep exports, failing legibly on a stock core."""
    missing = [n for n in ("LoadRomParked", "RunFramesSync", "SetPowerOnSeed",
                           "FlushVideoFrame", "TakeScreenshotToFile",
                           "LockstepBreakSleepDepth", "LockstepParkGeneration")
               if not hasattr(lib, n)]
    if missing:
        raise MachineError(
            f"this MesenCore lacks the lockstep exports {missing} — it is the "
            f"stock core. Build the patched one (bash "
            f"vendor/mesen_patches/apply.sh) and bind it with SF_MESEN_CORE "
            f"or Machine(core_path=...)."
        )
    lib.LoadRomParked.restype = ctypes.c_int32
    lib.LoadRomParked.argtypes = [ctypes.c_char_p]
    lib.RunFramesSync.restype = ctypes.c_int32
    lib.RunFramesSync.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    lib.SetPowerOnSeed.restype = None
    lib.SetPowerOnSeed.argtypes = [ctypes.c_int64]
    lib.FlushVideoFrame.restype = ctypes.c_bool
    lib.FlushVideoFrame.argtypes = [ctypes.c_uint32]
    lib.TakeScreenshotToFile.restype = ctypes.c_bool
    lib.TakeScreenshotToFile.argtypes = [ctypes.c_char_p]
    lib.LockstepBreakSleepDepth.restype = ctypes.c_uint32
    lib.LockstepBreakSleepDepth.argtypes = []
    lib.LockstepParkGeneration.restype = ctypes.c_uint64
    lib.LockstepParkGeneration.argtypes = []
    return lib


_RC_NAMES = {
    -1: "no ROM running", -2: "no debugger", -3: "core not parked",
    -4: "LoadRom failed", -5: "power-on park never landed",
    -6: "bulk step overshoot", -7: "frame walk overshoot",
    -8: "park is not at the canonical scanline",
}


class Machine:
    """A parked SNES that advances only when told to, exactly as far as told.

    ``Machine(rom)`` loads PARKED at the planted power-on break (frame 0,
    nothing executed unobserved, access counters live from the reset
    vector). ``advance(frames=N)`` emulates exactly N PPU frames — verified
    against the machine's own counter — and returns parked at the canonical
    scanline. Reads, writes and screenshots all happen against that parked
    exact frame.

    The core is a process-global singleton; a Machine is a lightweight
    handle plus the input log that makes its trajectory replayable. Building
    a second Machine reloads the core — the first handle is SUPERSEDED: its
    driving and reading methods raise (they would silently operate the new
    machine's state), and its close() is a no-op (the core now belongs to
    the successor). ``Machine.close_current()`` closes whichever handle owns
    the core — the right teardown for a fixture whose test may itself have
    built more machines.
    """

    _current: Optional["Machine"] = None

    def __init__(self, rom_path, seed: int = DEFAULT_POWERON_SEED,
                 uninit_detection: bool = False,
                 core_path: Optional[str] = None):
        rom_abs = os.path.abspath(str(rom_path))
        if not os.path.exists(rom_abs):
            raise FileNotFoundError(f"ROM not found: {rom_abs}")
        resolved_core = core_path or _default_core_path()
        # H-1 guard: never dlopen a SECOND, different MesenCore
        # build into this process. If mesen_runner's import-time preload
        # already loaded one file and _global_initialize is about to CDLL a
        # different one, the second load segfaults with no traceback (two
        # builds of one C++ singleton's three-way experiment).
        # This arm is reachable only when mesen_runner was imported before
        # this module (so the export block at the top could not align the
        # preload); turn the crash into a sentence naming both paths.
        if (not _mr._GLOBAL_INIT_DONE
                and _mr._PRELOAD_HANDLE is not None
                and os.path.realpath(resolved_core)
                != os.path.realpath(_mr._DEFAULT_CORE_PATH)):
            raise MachineError(
                "refusing to load a second MesenCore build into this "
                "process: mesen_runner's import-time preload already "
                f"dlopened\n    {_mr._DEFAULT_CORE_PATH}\n"
                "and this Machine resolved\n"
                f"    {resolved_core}\n"
                "— initializing it would segfault (one C++ singleton, two "
                "builds; H-1). Fix: set SF_MESEN_CORE to the "
                "intended core before the first mesen_runner import, or "
                "import machine before mesen_runner (it exports its "
                "resolution)."
            )
        # The SAME conflict, arriving AFTER the core was
        # initialized. `_global_initialize` early-returns the existing lib
        # (mesen_runner.py's `if _GLOBAL_INIT_DONE: return _GLOBAL_LIB`) and
        # IGNORES core_path, so this does not crash — it silently hands back
        # the incumbent. The old fall-through then reported "it is the stock
        # core. Build the patched one (bash vendor/mesen_patches/apply.sh)",
        # which misdiagnoses twice over: the patched core may exist and be
        # exactly what was requested, and rebuilding it would change nothing
        # because the binding is process-global and already spent. Both
        # directions are caught, including the mirror case the audit flagged
        # as latent — lockstep already initialized, stock requested, where
        # `_bind_lockstep` SUCCEEDS and `self._core_path` would otherwise
        # record a file this handle is not running.
        if (_mr._GLOBAL_INIT_DONE
                and os.path.realpath(resolved_core)
                != os.path.realpath(_mr._GLOBAL_INIT_PARAMS[0])):
            raise MachineError(
                "refusing to bind a second MesenCore build in this process: "
                "the core was already initialized as\n"
                f"    {_mr._GLOBAL_INIT_PARAMS[0]}\n"
                "and this Machine resolved\n"
                f"    {resolved_core}\n"
                "— one C++ singleton, two builds. "
                "The first initialization wins and cannot be undone: "
                "core_path= is ignored once a MesenRunner or an earlier "
                "Machine has loaded a ROM, so you would silently drive the "
                "core named first. Fix: choose the core BEFORE the first "
                "load (set SF_MESEN_CORE, or import machine before "
                "mesen_runner — it exports its resolution), or run this "
                "Machine in its own process."
            )
        lib = _mr._global_initialize(
            resolved_core, _mr._DEFAULT_HOME_DIR, False)
        self._lib = _bind_lockstep(lib)
        self._core_path = resolved_core
        self.rom_path = rom_abs
        self.rom_md5 = hashlib.md5(Path(rom_abs).read_bytes()).hexdigest()
        self.seed = int(seed)
        self.input_log: list[tuple] = []
        self._ppu_buf = (ctypes.c_uint8 * _mr._PPU_STATE_BUF_SIZE)()
        self._closed = False

        # Patch 2: the power-on RNG draws from a seed-determined stream for
        # THIS load (RamState stays Random — rule 5; randomized RAM made
        # replayable). uninit_detection asks for nothing extra at load time:
        # LoadRomParked always arms the counters from power-on (that is its
        # definition); the flag is kept for call-site declarations of intent
        # and gates the counter API check below.
        lib.SetPowerOnSeed(ctypes.c_int64(self.seed))
        rc = lib.LoadRomParked(rom_abs.encode("utf-8"))
        if rc != 0:
            self._raise(f"LoadRomParked failed: {_RC_NAMES.get(rc, rc)}")

        # The Machine's whole life is parked stepping: lift the wall-clock
        # throttle so an advance runs at host speed (the same MaximumSpeed
        # flag the legacy debug_break raises; frame skipping is disabled
        # process-wide by the shared base config, so captures see every
        # frame). AFTER the load, deliberately — a load resets emulation
        # flags, and a pre-load set was measured pacing advance(90) at
        # 1.53 s (= 90 frames of 60 fps throttle) instead of host speed.
        # close() restores normal pacing on the way out.
        if hasattr(lib, "SetEmulationFlag"):
            lib.SetEmulationFlag(_mr._EMU_FLAG_MAXIMUM_SPEED, True)
        if uninit_detection and not hasattr(lib, "GetMemoryAccessCounts"):
            self._raise("this core lacks GetMemoryAccessCounts")
        self.uninit_detection = uninit_detection
        Machine._current = self
        _det_log("load", self.rom_md5, self.seed)

    def _check_live(self):
        if self._closed:
            self._raise("this Machine is closed")
        if Machine._current is not self:
            self._raise("this Machine was superseded by a later load — its "
                        "state is gone; drive the newest Machine")

    # --- identity ---------------------------------------------------------

    @property
    def triple(self) -> tuple:
        """The replay triple: (rom md5, seed, input script so far)."""
        return (self.rom_md5, self.seed, tuple(self.input_log))

    def _raise(self, msg: str):
        raise MachineError(f"{msg}\n  replay triple: rom md5 {self.rom_md5}, "
                           f"seed {self.seed:#x}, input log "
                           f"{tuple(self.input_log)!r}")

    # --- the machine's own clock -----------------------------------------

    def _ppu(self) -> tuple[int, int]:
        self._lib.GetPpuState(self._ppu_buf, _mr._CPU_TYPE_SNES)
        f = _mr._PPU_STATE_FRAMECOUNT_OFFSET
        s = _mr._PPU_STATE_SCANLINE_OFFSET
        return (int.from_bytes(bytes(self._ppu_buf[f:f + 4]), "little"),
                int.from_bytes(bytes(self._ppu_buf[s:s + 2]), "little"))

    def ppu_frame_count(self) -> int:
        """Frames since power-on, from the PPU's own counter.

        Manifest-logged:
        this is a test-observable read, so the determinism gate must see
        both the query and the value. Internal `_ppu()` uses do NOT log —
        they are `advance`'s own landing verification, whose divergence
        already raises and fails the gate on exit-code inequality.
        """
        value = self._ppu()[0]
        _det_log("ppu_frame_count", value)
        return value

    # --- input ------------------------------------------------------------

    def _latch(self, controller_index: int, buttons: Optional[dict]):
        """Latch a FULL controller state (unnamed buttons released)."""
        state = _mr.DebugControllerState()
        for name in (buttons or {}):
            if buttons[name]:
                field = _mr._BUTTON_MAP.get(name.lower())
                if field is None:
                    raise ValueError(f"unknown button {name!r}")
                setattr(state, field, 1)
        self._lib.SetInputOverrides(controller_index, state)

    # --- advancing --------------------------------------------------------

    def advance(self, frames: int = 1, pad1: Optional[dict] = None,
                pad2: Optional[dict] = None) -> "Machine":
        """Emulate exactly `frames` frames, both pads in a STATED state.

        Input semantics are the park-latch semantics the legacy runner
        proved (see the class docstring): both pads are latched here —
        every button not named is RELEASED, on both pads, always — and the
        latched state is polled at each of the `frames` boundaries. The
        WRAM effect of a press is visible in this call's own readback; the
        OAM effect one advance later (the constant one-frame presentation
        lag of the park point).
        """
        self._check_live()
        if frames < 1:
            raise ValueError(f"advance needs frames >= 1, got {frames}")
        self._latch(0, pad1)
        self._latch(1, pad2)
        self.input_log.append((frames,
                               tuple(sorted(k for k, v in (pad1 or {}).items() if v)),
                               tuple(sorted(k for k, v in (pad2 or {}).items() if v))))
        _det_log("advance", frames, *self.input_log[-1][1:])
        before, _ = self._ppu()
        rc = self._lib.RunFramesSync(frames, _PARK_SCANLINE)
        if rc != 0:
            self._raise(f"RunFramesSync({frames}) failed: {_RC_NAMES.get(rc, rc)}")
        after, scanline = self._ppu()
        if after != before + frames or scanline != _PARK_SCANLINE:
            self._raise(
                f"advance({frames}) landed at frame {after} scanline "
                f"{scanline}, expected frame {before + frames} scanline "
                f"{_PARK_SCANLINE}")
        return self

    def run_until(self, pred: Callable[["Machine"], bool], max_frames: int,
                  what: str = "") -> int:
        """Advance one frame at a time until `pred(self)` is true.

        Bounded in EMULATED frames only. `pred` reads OUTPUT state (that is
        the caller's contract — same discipline as every assertion). Returns
        the number of frames advanced; raises with the replay triple when
        the budget is exhausted.
        """
        for i in range(max_frames):
            if pred(self):
                return i
            self.advance(1)
        if pred(self):
            return max_frames
        self._raise(f"run_until({what or pred!r}) not satisfied within "
                    f"{max_frames} frames")

    # --- reads (always from the parked exact frame) -----------------------

    def _memory_size(self, mem_type: MemoryType) -> int:
        """The raw size query, UNLOGGED — the internal plumbing path.

        `read_bytes`, `read_region` and `get_uninitialized_reads` all need a
        region's size to do their own work. Those calls are not test
        observations: whatever they compute is already covered by the
        `read`/`uninit` record they produce (a `read` record carries the
        very count this returned). Logging them would roughly DOUBLE a
        read-heavy manifest — 1368 reads in `test_split_h_2p_sprites` — to
        record a value that is constant within a run, so the split keeps
        the manifest about what the TEST saw.
        """
        return self._lib.GetMemorySize(int(mem_type))

    def get_memory_size(self, mem_type: MemoryType) -> int:
        """Region size in bytes. Manifest-logged.

        This was the one public read on `Machine` with no manifest record.
        Nothing live escaped through it — its only in-tree caller
        (`tests/test_machine.py:70`) launders the value straight into a
        `read_bytes` count, which IS logged — but "every public read is in
        the manifest" is an invariant a reader can check in one pass,
        whereas "every public read except this one, because its value
        cannot vary" is an argument that has to be re-derived every time
        the core or this method changes. The value is cheap; the exception
        was not. Internal callers take `_memory_size` and stay silent.
        """
        value = int(self._memory_size(mem_type))
        _det_log("memory_size", int(mem_type), value)
        return value

    def read_bytes(self, mem_type: MemoryType, address: int, count: int) -> bytes:
        """Read `count` bytes; G3-logged, G2-mutated like every output read."""
        self._check_live()
        _mr.READ_LOG.log_memory_read(mem_type, address, count)
        size = self._memory_size(mem_type)
        if size <= 0 or address + count > size:
            data = bytes(self._lib.GetMemoryValue(int(mem_type), address + i) & 0xFF
                         for i in range(count))
        else:
            buf = (ctypes.c_uint8 * size)()
            self._lib.GetMemoryState(int(mem_type), buf)
            data = bytes(buf[address:address + count])
        if _mr.MUTATION.enabled and _mr._mem_type_is_output(mem_type):
            data = _mr.MUTATION.mutate_bytes(data)
        _det_log("read", int(mem_type), address, count,
                 hashlib.sha1(data).hexdigest())
        return data

    def read_byte(self, mem_type: MemoryType, address: int) -> int:
        return self.read_bytes(mem_type, address, 1)[0]

    def read_u16(self, mem_type: MemoryType, address: int) -> int:
        data = self.read_bytes(mem_type, address, 2)
        return data[0] | (data[1] << 8)

    def read_region(self, mem_type: MemoryType) -> bytes:
        return self.read_bytes(mem_type, 0, self._memory_size(mem_type))

    # --- writes (parked pokes, the legacy write API's semantics) ----------

    def write_bytes(self, mem_type: MemoryType, address: int, data: bytes):
        self._check_live()
        if not hasattr(self._lib, "SetMemoryValues"):
            self._raise("this core lacks the memory-write exports")
        arr = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        self._lib.SetMemoryValues(int(mem_type), address, arr, len(data))
        _det_log("write", int(mem_type), address,
                 hashlib.sha1(bytes(data)).hexdigest())

    def write_byte(self, mem_type: MemoryType, address: int, value: int):
        self.write_bytes(mem_type, address, bytes([value & 0xFF]))

    # --- access counters / uninit detector --------------------------------

    def _counts(self, mem_type: MemoryType, address: int):
        buf = (_mr._AddressCounters * 1)()
        self._lib.GetMemoryAccessCounts(address, 1, int(mem_type), buf)
        return buf[0]

    def writes(self, mem_type: MemoryType, addr: int) -> int:
        """Write count for one address since power-on (counters are armed
        from the reset vector by LoadRomParked's oracle, made the
        universal idiom).

        Manifest-logged with the query AND the value: a
        counter asserted only against a threshold is exactly the read that
        used to escape the manifest.
        """
        value = int(self._counts(mem_type, addr).WriteCounter)
        _det_log("writes", int(mem_type), addr, value)
        return value

    def reads(self, mem_type: MemoryType, addr: int) -> int:
        """Read count for one address since power-on. Manifest-logged —
        see `writes`."""
        value = int(self._counts(mem_type, addr).ReadCounter)
        _det_log("reads", int(mem_type), addr, value)
        return value

    def get_uninitialized_reads(self, mem_types=_mr.UNINIT_DETECT_MEMORY_TYPES) -> dict:
        """Map each memory type to the addresses read-before-written.

        The legacy detector's own definition and return shape, kept exactly
        (WriteCounter == 0 and ReadCounter > 0, recomputed from the raw
        counters; ``{MemoryType: [addr, ...]}``, empty dict == clean) —
        complete by construction here, because LoadRomParked attached the
        counters before the first instruction.
        """
        result: dict = {}
        for mt in mem_types:
            size = self._memory_size(mt)
            if size <= 0:
                continue
            buf = (_mr._AddressCounters * size)()
            self._lib.GetMemoryAccessCounts(0, size, int(mt), buf)
            bad = [addr for addr, c in enumerate(buf)
                   if c.WriteCounter == 0 and c.ReadCounter > 0]
            if bad:
                result[MemoryType(int(mt))] = bad
        # Manifest-logged: the queried types, the total hit
        # count, and a hash of the full result — hashed like read bytes so
        # a non-empty dict (which can be thousands of addresses) does not
        # bloat the manifest, while any cross-run difference in it still
        # flips the byte-identity verdict.
        _det_log("uninit", [int(mt) for mt in mem_types],
                 sum(len(v) for v in result.values()),
                 hashlib.sha1(json.dumps(
                     {int(k): v for k, v in result.items()},
                     sort_keys=True).encode()).hexdigest())
        return result

    def assert_no_uninitialized_reads(self, mem_types=_mr.UNINIT_DETECT_MEMORY_TYPES,
                                      max_examples: int = 8) -> None:
        """The legacy assert, with the replay triple in the failure text."""
        found = self.get_uninitialized_reads(mem_types)
        if not found:
            return
        lines = [f"  {mt!r}: {len(addrs)} addr(s), e.g. "
                 f"{[hex(a) for a in addrs[:max_examples]]}"
                 for mt, addrs in found.items()]
        self._raise("uninitialized reads (read-before-write since power-on):\n"
                    + "\n".join(lines))

    # --- captures (parked, decode-flushed, exact) --------------------------

    def take_screenshot(self, output_path: str) -> str:
        """Capture the frame current at call time to `output_path`.

        The legacy contract, kept exactly (the imported oracle helpers rely
        on it): the capture costs ONE emulated frame — both pads RELEASED
        for it, the stated-state discipline — and the PNG holds the pixels
        of the frame that was current when you called. What changes under
        lockstep is that the decode pipeline is FLUSHED (FlushVideoFrame)
        between the advance and the copy, so WHICH frame is in the buffer
        is an observable, not a race the host's load runs (the legacy
        parked path measured a 0.4%-under-load wrong-frame residual; this
        path's frame choice is deterministic).
        """
        self._check_live()
        _mr.READ_LOG.log_screenshot()
        self.advance(1)
        self.input_log.append(("shot",))
        if not self._lib.FlushVideoFrame(5000):
            self._raise("FlushVideoFrame: decode thread did not consume the "
                        "submitted frame within 5s — dead decode thread")
        out = os.path.abspath(str(output_path))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if not self._lib.TakeScreenshotToFile(out.encode("utf-8")):
            self._raise(f"TakeScreenshotToFile({out}) failed")
        if _mr.MUTATION.enabled:
            _mr._flat_paint_png(out)
        _det_log("shot", hashlib.sha1(Path(out).read_bytes()).hexdigest())
        return out

    def screenshot(self, output_path: str) -> str:
        """Alias of take_screenshot (the brief's short name)."""
        return self.take_screenshot(output_path)

    # --- teardown ---------------------------------------------------------

    def close(self):
        """Hand the process-global core back free-running.

        The module-boundary contract (tests/conftest.py's parked-core
        guard) is that no module finishes with the shared core parked; a
        Machine parks by definition, so its teardown resumes. Ordered the
        race-free way: the core is verifiably in its break sleep (that is
        the Machine's invariant), so one ResumeExecution is a clean
        release, verified by frame progress.
        """
        if self._closed or Machine._current is not self:
            self._closed = True
            return
        self._closed = True
        Machine._current = None
        try:
            self._latch(0, None)
            self._latch(1, None)
        except Exception:
            pass
        if hasattr(self._lib, "SetEmulationFlag"):
            self._lib.SetEmulationFlag(_mr._EMU_FLAG_MAXIMUM_SPEED, False)
        # Release-and-verify, borrowing conftest._unpark_core's shape: the
        # verify is against EMULATED progress (the frame/scanline pair
        # moving). The wall deadline converts a genuinely-dead core into a
        # legible error at teardown, not into a verdict about the ROM.
        import time
        before = self._ppu()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            self._lib.ResumeExecution()
            settle = time.time() + 0.1
            while time.time() < settle:
                if self._ppu() != before:
                    return
                time.sleep(0.001)
        raise MachineError("close(): the core did not resume free-running")

    @classmethod
    def close_current(cls):
        """Close whichever Machine currently owns the core (fixture teardown)."""
        if cls._current is not None:
            cls._current.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
