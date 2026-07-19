"""
SuperForge Test Harness — Mesen2 Native Library Integration

Drives the Mesen2 cycle-accurate SNES emulator via its C API (MesenCore.so)
to run test ROMs and verify memory state.

Two execution modes:
  1. RunTest mode: Load ROM, run 500 frames, read 8 bytes from a memory address.
     Simple but sufficient for most assertion-based tests.
  2. RetroArch fallback: Uses SRAM-based protocol via RetroArch + bsnes-mercury.

Usage:
    from mesen_runner import MesenRunner, MemoryType

    runner = MesenRunner()
    result = runner.run_test("test.sfc", address=0x0000, mem_type=MemoryType.SnesWorkRam)
    assert result[:4] == b"SFDB"  # debug region magic bytes
"""

import atexit
import contextlib
import ctypes
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import time
from enum import IntEnum
from pathlib import Path
from typing import Optional


# Mesen2 MemoryType enum (from Core/Shared/MemoryType.h)
class MemoryType(IntEnum):
    SnesMemory = 0       # Full SNES address space (bus reads)
    SpcMemory = 1        # SPC700 address space
    SnesPrgRom = 14      # PRG ROM
    SnesWorkRam = 15     # 128KB WRAM ($7E0000-$7FFFFF)
    SnesSaveRam = 16     # SRAM (battery-backed)
    SnesVideoRam = 17    # 64KB VRAM
    SnesSpriteRam = 18   # OAM (544 bytes)
    SnesCgRam = 19       # CGRAM / palette (512 bytes)
    SnesRegister = 20    # Hardware registers
    SpcRam = 21          # SPC700 RAM (64KB)
    SpcDspRegisters = 23 # SPC700 DSP registers (128 bytes, verified by probing)


# --- Visual Guardrail G3: MesenRunner read-logging ---------------------------
#
# Records which memory regions / screenshots each test reads at runtime so the
# surface linter (tools/surface_lint.py) can flag a visual-tagged test that
# reads ONLY WRAM game variables and never an output region (OAM / VRAM /
# CGRAM / screenshot). The mutation gate (G2, later sprint) consumes the same
# read-log to know which region/crop to corrupt per test.
#
# Design constraints (spec §3.1):
#   * INERT unless explicitly enabled. The pytest plugin sets
#     SUPERFORGE_READLOG=1 (or calls enable_read_logging()). With the flag
#     off, every read entry point is byte-for-byte unchanged and the global
#     log stays empty — normal runner use must not change behavior or cost.
#   * Log by APPENDING ONLY. The recorder never touches a read's return
#     value; instrumentation wraps the read but the data path is untouched.
#   * Bucketed per test id. A module-scoped runner fixture is reused across
#     many tests, so the plugin tags the active test id on the module-level
#     recorder around each test call; reads are filed under that id.

# Output regions per visual_correctness.md §3 G3 / spec §3.2. A read of one of
# these (or a screenshot access) is the only thing that satisfies the gate.
# WRAM (incl. shadow OAM/CGRAM/tilemap shadows), SRAM and SPC RAM are NOT
# output regions — shadow WRAM is what gets DMA'd, not what the user perceives.
OUTPUT_MEMORY_TYPES = frozenset(
    {
        MemoryType.SnesVideoRam,   # VRAM
        MemoryType.SnesSpriteRam,  # OAM
        MemoryType.SnesCgRam,      # CGRAM / palette
    }
)


def _mem_type_is_output(mem_type: "MemoryType | int") -> bool:
    """True if a read of *mem_type* counts as an output-region read (§3.2)."""
    try:
        return MemoryType(int(mem_type)) in OUTPUT_MEMORY_TYPES
    except (ValueError, TypeError):
        return False


# --- Break-on-uninitialized-read: Mesen per-address access counters ----------
#
# Mirrors Core/Debugger/MemoryAccessCounter.h `struct AddressCounters`. Mesen's
# debugger tracks, per byte of each memory region, the master-clock stamp and
# count of the last read / write / exec. The DLL exports GetMemoryAccessCounts
# (offset, length, memoryType, AddressCounters* out) which memcpy's the array
# for a region.
#
# An *uninitialized read* is a byte that was READ since power-on but never
# WRITTEN — i.e. WriteCounter == 0 and ReadCounter > 0 — in volatile RAM. This
# is exactly Mesen's own ReadResult::FirstUninitRead/UninitRead classification
# (MemoryAccessCounter.cpp:34, gated on `counts.WriteStamp == 0 &&
# IsVolatileRam(...)`), recomputed here from the raw counters so it works
# regardless of whether Mesen's internal break-on-uninit flag is armed.
#
# The counters only accumulate while the debugger is active. The detector run
# (load_rom_with_uninit_detection) initializes the debugger BEFORE the ROM runs
# so reads/writes during emulation are counted from power-on; a normal
# load_rom() inits the debugger after the run, so the per-address history is
# incomplete and the detector requires its own load path.
class _AddressCounters(ctypes.Structure):
    """Mirrors Core/Debugger/MemoryAccessCounter.h `struct AddressCounters`."""
    _fields_ = [
        ("ReadStamp", ctypes.c_uint64),
        ("WriteStamp", ctypes.c_uint64),
        ("ExecStamp", ctypes.c_uint64),
        ("ReadCounter", ctypes.c_uint32),
        ("WriteCounter", ctypes.c_uint32),
        ("ExecCounter", ctypes.c_uint32),
    ]


# Volatile-RAM regions the uninit-read detector inspects by default. These match
# Mesen's IsVolatileRam() for the SNES side (WRAM/VRAM/OAM/CGRAM are garbage at
# power-on; SaveRam and hardware registers are excluded). SpcRam is volatile too
# but the SPC700 has its own bootstrap discipline, so it is opt-in via the
# `mem_types` argument rather than a default.
#
# SCOPE LIMIT (see docs/conventions/power_on_fidelity.md §4): these counters
# increment on CPU/BUS reads only, NOT on PPU render fetches. So including
# VRAM/OAM/CGRAM here catches the CPU *reading* those regions (rare — e.g. the
# VRAM read port), NOT the common "PPU displays uninitialized VRAM" class (S2 /
# Tetris-Attack). That display class is caught by G6 (render-determinism), not
# here. This detector = CPU-side uninit reads; G6 = uninit memory reaching screen.
UNINIT_DETECT_MEMORY_TYPES = (
    MemoryType.SnesWorkRam,
    MemoryType.SnesVideoRam,
    MemoryType.SnesSpriteRam,
    MemoryType.SnesCgRam,
)


class UninitializedReadError(AssertionError):
    """Raised by assert_no_uninitialized_reads when a ROM reads uninit memory.

    Carries `.findings` — a list of (MemoryType, count) tuples — so callers can
    inspect which regions were read before being written since power-on.
    """

    def __init__(self, message: str, findings: list):
        super().__init__(message)
        self.findings = findings


class _ReadLogRecorder:
    """Module-level read-log recorder shared across all MesenRunner instances.

    Inert until :meth:`enable` (or the ``SUPERFORGE_READLOG`` env var) turns
    it on. The pytest plugin attaches the active test id via :meth:`set_test`
    so reads from a module-scoped runner are bucketed per test.

    The log is a flat list of records; each record carries the test id it was
    captured under (or ``None`` when no test is active). Records are dicts:
        {"test": <id|None>, "mem_type": <int>, "addr": <int>, "count": <int>,
         "output": <bool>}
    for memory reads, or
        {"test": <id|None>, "kind": "screenshot", "output": True}
    for screenshot accesses.
    """

    def __init__(self) -> None:
        # Honor the env var at construction; the plugin / explicit enable()
        # can still toggle it at runtime.
        self._enabled = os.environ.get("SUPERFORGE_READLOG", "") not in ("", "0")
        self._records: list[dict] = []
        self._current_test: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def set_test(self, test_id: Optional[str]) -> None:
        """Tag (or clear) the active test id all subsequent reads file under."""
        self._current_test = test_id

    def reset(self) -> None:
        """Drop all recorded reads (keeps enabled state + current test id)."""
        self._records = []

    def records(self) -> list[dict]:
        """A copy of every recorded read (across all tests)."""
        return list(self._records)

    def records_for(self, test_id: Optional[str]) -> list[dict]:
        """Records captured under *test_id*."""
        return [r for r in self._records if r.get("test") == test_id]

    def as_readlog(self) -> dict:
        """Group records by test id → {test_id: [record, ...]}.

        Records with no active test (``test is None``) are filed under the
        ``"<no-test>"`` key so they aren't silently dropped.
        """
        out: dict[str, list[dict]] = {}
        for r in self._records:
            key = r.get("test")
            out.setdefault(key if key is not None else "<no-test>", []).append(r)
        return out

    def log_memory_read(self, mem_type: "MemoryType | int", addr: int,
                        count: int) -> None:
        if not self._enabled:
            return
        self._records.append(
            {
                "test": self._current_test,
                "mem_type": int(mem_type),
                "addr": int(addr),
                "count": int(count),
                "output": _mem_type_is_output(mem_type),
            }
        )

    def log_screenshot(self) -> None:
        if not self._enabled:
            return
        self._records.append(
            {
                "test": self._current_test,
                "kind": "screenshot",
                "output": True,
            }
        )


# Process-global recorder instance. Shared by every MesenRunner and by the
# pixel-read helpers in visual_assertions.py.
READ_LOG = _ReadLogRecorder()


# --- Visual Guardrail G2: MesenRunner mutation mode --------------------------
#
# Mutation mode SIMULATES A VISUAL DEFECT (wrong rendered output) so the
# mutation gate (tools/mutation_gate.py) can detect a visual-tagged test that
# CANNOT fail on such a defect — an indirect-evidence test. The discipline is
# visual_correctness.md §2's sabotage check made mechanical: corrupt what a
# test reads and require it to fail; a test that still PASSES is a survivor.
#
# Design constraints (spec §3.1 / §3.4):
#   * OFF by default; opt-in via SUPERFORGE_MUTATE=1 or enable_mutation().
#     With the flag off every read entry point is byte-for-byte unchanged —
#     normal runner use, and the G3 read-log, are completely unaffected.
#   * Deterministic. Output-region bytes are bit-inverted (^0xFF) — every
#     byte is guaranteed to differ from the real value, reproducibly, with no
#     randomness. Screenshots are flat-painted a fixed sentinel color.
#   * Transform the RETURN COPY only. The corruption is applied to the bytes /
#     PNG handed back to the caller; the emulator core's memory is NEVER
#     written. (You are mutating the return value, not the machine.)
#   * Output regions only. VRAM / OAM / CGRAM reads (OUTPUT_MEMORY_TYPES) and
#     screenshots are corrupted; WRAM / SRAM / SPC reads PASS THROUGH UNCHANGED.
#     This is the crux: a correct visual test asserts on the output → fails; an
#     indirect test asserts on an untouched WRAM proxy → still passes → that is
#     the survivor signal the gate reports. Corrupting WRAM would mask exactly
#     the tests G2 exists to catch.
#   * Composes with read-logging: the read is logged FIRST (unchanged G3
#     behavior), THEN the return value is corrupted if mutation is on and the
#     region is an output region.

# Sentinel fill color for a flat-painted (mutated) screenshot — garish magenta,
# matching the G1 sabotage fixture (tests/test_golden_frames.py). A real frame
# is effectively never a uniform magenta field, so a pixel-read assertion on a
# correctly-rendered golden will differ from this and fail under mutation.
MUTATION_FLAT_COLOR = (255, 0, 255)

# Byte transform applied to every output-region byte. XOR 0xFF guarantees a
# per-byte difference (b != b ^ 0xFF for all b) and is its own inverse, so the
# corruption is fully deterministic and reproducible.
_MUTATION_XOR = 0xFF


class _MutationController:
    """Module-level mutation switch shared across all MesenRunner instances.

    Inert until :meth:`enable` (or the ``SUPERFORGE_MUTATE`` env var) turns it
    on. When enabled, MesenRunner corrupts the COPY it returns from
    output-region reads (bit-invert) and from screenshots (flat paint), never
    the emulator core's state.
    """

    def __init__(self) -> None:
        self._enabled = os.environ.get("SUPERFORGE_MUTATE", "") not in ("", "0")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def mutate_bytes(self, data: bytes) -> bytes:
        """Return a bit-inverted copy of *data* (deterministic ^0xFF)."""
        return bytes(b ^ _MUTATION_XOR for b in data)

    def mutate_byte(self, value: int) -> int:
        """Return the bit-inverted single byte value (deterministic ^0xFF)."""
        return (int(value) ^ _MUTATION_XOR) & 0xFF


# Process-global mutation controller. Shared by every MesenRunner.
MUTATION = _MutationController()


def enable_mutation() -> None:
    """Turn mutation mode on (the mutation-gate pytest plugin calls this)."""
    MUTATION.enable()


def disable_mutation() -> None:
    """Turn mutation mode off."""
    MUTATION.disable()


def mutation_enabled() -> bool:
    """Module-level convenience: True if mutation mode is active."""
    return MUTATION.enabled


def _flat_paint_png(path: str) -> None:
    """Overwrite the PNG at *path* with a uniform sentinel-color frame.

    Reads the existing image's size, paints a flat ``MUTATION_FLAT_COLOR``
    fill of the same dimensions, and writes it back over the same path. This
    is the screenshot analogue of the bit-invert: the rendered surface a
    caller reads back is corrupted, but the emulator's own frame buffer is
    untouched (we only rewrite the file we just produced).
    """
    from PIL import Image

    with Image.open(path) as img:
        size = img.size
    flat = Image.new("RGB", size, MUTATION_FLAT_COLOR)
    flat.save(path)


def enable_read_logging() -> None:
    """Turn read-logging on (the pytest surface-lint plugin calls this)."""
    READ_LOG.enable()


def disable_read_logging() -> None:
    """Turn read-logging off."""
    READ_LOG.disable()


def reset_read_log() -> None:
    """Module-level convenience: clear the global read-log."""
    READ_LOG.reset()


def get_read_log() -> list[dict]:
    """Module-level convenience: a copy of every recorded read."""
    return READ_LOG.records()


def set_read_log_test(test_id: Optional[str]) -> None:
    """Tag the active test id on the global recorder (pytest plugin hook)."""
    READ_LOG.set_test(test_id)


class DebugControllerState(ctypes.Structure):
    """Mesen2 DebugControllerState struct for input injection.

    Maps to Core/Debugger/DebugTypes.h DebugControllerState.
    Field order must match the C++ struct exactly.
    """
    _fields_ = [
        ("A", ctypes.c_bool),
        ("B", ctypes.c_bool),
        ("X", ctypes.c_bool),
        ("Y", ctypes.c_bool),
        ("L", ctypes.c_bool),
        ("R", ctypes.c_bool),
        ("U", ctypes.c_bool),
        ("D", ctypes.c_bool),
        ("Up", ctypes.c_bool),
        ("Down", ctypes.c_bool),
        ("Left", ctypes.c_bool),
        ("Right", ctypes.c_bool),
        ("Select", ctypes.c_bool),
        ("Start", ctypes.c_bool),
    ]


# --- Deterministic frame-stepping constants (S7 M1) --------------------------
#
# All four values below were verified EMPIRICALLY against the exact
# MesenCore.so binary in use (no Mesen2 source tree was available), by
# loading a kit ROM whose NMI increments a per-frame counter and probing
# each candidate value. Probe methodology + raw outputs are recorded in
# the S7 M1 sprint report; summary:
#
# _CPU_TYPE_SNES = 0
#     First arg of the exported `Step(CpuType, int32 count, StepType)`.
#     Disassembly of the export confirms CpuType is passed as a single
#     byte (%dil); 0 selects the SNES main CPU.
#
# _STEP_TYPE_PPU_FRAME = 6
#     Triangulated by probing every candidate 0..10 from a parked state
#     and reading the PPU FrameCount + Scanline + Cycle + PC after each:
#       0 -> one CPU instruction (PC +1 instr, frame/scanline unchanged)
#       3 -> one CPU cycle        4 -> one PPU dot (Cycle +1)
#       5 -> one scanline (Scanline +1, FrameCount unchanged)
#       6 -> FrameCount +1 exactly, x10 consecutive; count=2/5/10 give
#            +2/+5/+10 exactly  (== StepType::PpuFrame)
#       7 -> ran to scanline 1 (SpecificScanline)
#       8 -> stopped at the NMI handler entry, FrameCount +1 (RunToNmi)
#       9 -> ran away, never stopped (RunToIrq; the kit ROMs use no IRQ)
#     The layout matches upstream Mesen2 DebugTypes.h StepType: Step=0,
#     StepOut=1, StepOver=2, CpuCycleStep=3, PpuStep=4, PpuScanline=5,
#     PpuFrame=6, SpecificScanline=7, RunToNmi=8, RunToIrq=9, StepBack=10.
#
# _PPU_STATE_FRAMECOUNT_OFFSET = 8
#     Byte offset of the u32 FrameCount inside the struct filled by the
#     exported GetPpuState(void*, CpuType). Found by diffing two
#     free-running snapshots 0.3 s apart: exactly one aligned u32 in the
#     first 256 bytes advanced by ~18 (60 fps x 0.3 s) — offset 8.
#     Cross-checked against the WRAM FRAME_COUNTER engine mirror and the
#     known leading layout (u16 Cycle @0, u16 Scanline @2, u16 HClock @4,
#     pad, u32 FrameCount @8).
#
# _EMU_FLAG_MAXIMUM_SPEED = 4
#     SetEmulationFlag(4, True) lifted free-run from ~60 fps to host
#     speed (~150 fps on the reference VM) and bulk frame-steps from
#     16.6 ms/frame to ~6.6 ms/frame; (4, False) restored ~60 fps.
#     Matches upstream EmulationFlags::MaximumSpeed.
_CPU_TYPE_SNES = 0
_STEP_TYPE_PPU_SCANLINE = 5
_STEP_TYPE_PPU_FRAME = 6
_PPU_STATE_SCANLINE_OFFSET = 2
_PPU_STATE_FRAMECOUNT_OFFSET = 8
_EMU_FLAG_MAXIMUM_SPEED = 4

_STEP_TYPE_SPECIFIC_SCANLINE = 7

# The canonical park scanline. Empirically established (and the reason a
# plain PpuFrame step is NOT a sufficient park): a PpuFrame step stops
# one frame of PPU time after the REQUEST point, preserving whatever
# scanline offset the emulator happened to be at — it does not snap to
# the frame boundary. The very first break after load_rom therefore
# inherits a wall-clock-nondeterministic in-frame offset, and that
# offset persists through every subsequent step (measured park scanlines
# across runs: 225, 229, 254, 258, and render-region 0..39). Two
# identical scripted runs then read their per-frame state at DIFFERENT
# pipeline positions (before vs after the frame's input poll and update),
# which broke trace determinism at the input-press frame.
#
# Fix: after every PpuFrame advance, normalize with a SpecificScanline
# step (StepType 7 — verified: the COUNT argument is the target
# scanline; Step(0, N, 7) runs until scanline N). Scanline 224 = end of
# the render period, just before VBlank/NMI of the next boundary:
#   - the frame's game update has long completed -> WRAM coherent
#   - the next NMI (DMA + auto-joypad) has not started -> OAM/VRAM hold
#     the PREVIOUS boundary's committed draw (a constant 1-frame lag)
#   - an input override latched here is polled at the very next
#     boundary -> its WRAM effect is visible in the SAME step's
#     readback, its OAM effect one step later. Always. On every run.
# Normalizing to 224 never crosses a frame boundary (the PpuFrame break
# parks at >= 225 or in the early render region; running forward to 224
# does not pass scanline 225 again), so frame accounting stays exact.
_CANONICAL_PARK_SCANLINE = 224

# Size of the scratch buffer handed to GetPpuState. The SNES PpuState
# struct is a few hundred bytes; 16 KB of headroom means a future core
# with a larger struct cannot scribble past our allocation.
_PPU_STATE_BUF_SIZE = 16384


# SNES button name -> DebugControllerState field name mapping
_BUTTON_MAP = {
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "l": "L",
    "r": "R",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "select": "Select",
    "start": "Start",
}


# --- Mesen2 SnesConfig structs (for controller port configuration) ---
# These mirror Core/Shared/SettingTypes.h and are needed to register
# controller devices so that SetInputOverrides works.

class _KeyMapping(ctypes.Structure):
    _fields_ = [
        ("A", ctypes.c_uint16), ("B", ctypes.c_uint16),
        ("X", ctypes.c_uint16), ("Y", ctypes.c_uint16),
        ("L", ctypes.c_uint16), ("R", ctypes.c_uint16),
        ("Up", ctypes.c_uint16), ("Down", ctypes.c_uint16),
        ("Left", ctypes.c_uint16), ("Right", ctypes.c_uint16),
        ("Start", ctypes.c_uint16), ("Select", ctypes.c_uint16),
        ("U", ctypes.c_uint16), ("D", ctypes.c_uint16),
        ("TurboA", ctypes.c_uint16), ("TurboB", ctypes.c_uint16),
        ("TurboX", ctypes.c_uint16), ("TurboY", ctypes.c_uint16),
        ("TurboL", ctypes.c_uint16), ("TurboR", ctypes.c_uint16),
        ("TurboSelect", ctypes.c_uint16), ("TurboStart", ctypes.c_uint16),
        ("GenericKey1", ctypes.c_uint16),
        ("CustomKeys", ctypes.c_uint16 * 100),
    ]

class _KeyMappingSet(ctypes.Structure):
    _fields_ = [
        ("Mapping1", _KeyMapping), ("Mapping2", _KeyMapping),
        ("Mapping3", _KeyMapping), ("Mapping4", _KeyMapping),
        ("TurboSpeed", ctypes.c_uint32),
    ]

class _ControllerConfig(ctypes.Structure):
    _fields_ = [("Keys", _KeyMappingSet), ("Type", ctypes.c_uint32)]

class _OverscanDimensions(ctypes.Structure):
    _fields_ = [
        ("Left", ctypes.c_uint32), ("Right", ctypes.c_uint32),
        ("Top", ctypes.c_uint32), ("Bottom", ctypes.c_uint32),
    ]

class _SnesConfig(ctypes.Structure):
    """Mirrors Core/Shared/SettingTypes.h SnesConfig struct."""
    _fields_ = [
        ("Port1", _ControllerConfig),
        ("Port2", _ControllerConfig),
        ("Port1SubPorts", _ControllerConfig * 4),
        ("Port2SubPorts", _ControllerConfig * 4),
        ("Region", ctypes.c_uint32),
        ("AllowInvalidInput", ctypes.c_bool),
        ("BlendHighResolutionModes", ctypes.c_bool),
        ("HideBgLayer1", ctypes.c_bool),
        ("HideBgLayer2", ctypes.c_bool),
        ("HideBgLayer3", ctypes.c_bool),
        ("HideBgLayer4", ctypes.c_bool),
        ("HideSprites", ctypes.c_bool),
        ("DisableFrameSkipping", ctypes.c_bool),
        ("ForceFixedResolution", ctypes.c_bool),
        ("Overscan", _OverscanDimensions),
        ("InterpolationType", ctypes.c_uint32),
        ("ChannelVolumes", ctypes.c_uint32 * 8),
        ("EnableRandomPowerOnState", ctypes.c_bool),
        ("EnableStrictBoardMappings", ctypes.c_bool),
        ("RamPowerOnState", ctypes.c_uint32),
        ("SpcClockSpeedAdjustment", ctypes.c_int32),
        ("PpuExtraScanlinesBeforeNmi", ctypes.c_uint32),
        ("PpuExtraScanlinesAfterNmi", ctypes.c_uint32),
        ("GsuClockSpeed", ctypes.c_uint32),
        ("BsxCustomDate", ctypes.c_int64),
    ]


def _detect_core_path() -> str:
    """Auto-detect the MesenCore library path based on platform."""
    system = platform.system()

    if system == "Windows":
        # Check common Windows locations for MesenCore.dll
        candidates = [
            # Repo-local tools directory
            str(Path(__file__).resolve().parent.parent.parent / "tools" / "Mesen" / "MesenCore.dll"),
            # User's AppData
            str(Path.home() / "Mesen2" / "MesenCore.dll"),
            # Program Files
            r"C:\Program Files\Mesen2\MesenCore.dll",
            r"C:\Program Files (x86)\Mesen2\MesenCore.dll",
            # Common dev location
            r"C:\Mesen2\MesenCore.dll",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        # Fallback: search PATH for MesenCore.dll
        found = shutil.which("MesenCore.dll")
        if found:
            return found
        return candidates[0]  # Return first candidate for error message

    else:  # Linux / macOS
        candidates = [
            "/tmp/Mesen2/InteropDLL/obj.linux-x64/MesenCore.so",
            str(Path(__file__).resolve().parent.parent.parent / "tools" / "Mesen" / "MesenCore.so"),
            str(Path.home() / "Mesen2" / "MesenCore.so"),
            "/usr/local/lib/MesenCore.so",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]


def _detect_home_dir() -> str:
    """Platform-appropriate temp/home directory for Mesen.

    Env knob (mirrors the ``SF_HW_POWERON`` / ``SF_REGION`` pattern; read once
    at module import): ``SF_MESEN_HOME``, when set to a non-empty path,
    overrides the default and becomes this process's Mesen home — its
    ``Screenshots/`` and ``Saves/*.srm`` subdirs live there. This isolates
    parallel MesenRunner processes on one host. The shared default
    ``/tmp/mesen_home`` cross-contaminated concurrent sessions: a
    ``take_screenshot`` new-file poll returning a sibling's frame, and a stale
    ``Saves/*.srm`` faking a "cold" boot. Set it per-worktree when booting
    rails concurrently. Unset / empty -> the default paths below are UNCHANGED.
    """
    override = os.environ.get("SF_MESEN_HOME", "").strip()
    if override:
        return override
    if platform.system() == "Windows":
        return str(Path(tempfile.gettempdir()) / "mesen_home")
    return "/tmp/mesen_home"


_DEFAULT_CORE_PATH = _detect_core_path()
_DEFAULT_HOME_DIR = _detect_home_dir()

# Default path to RetroArch + bsnes-mercury-accuracy (fallback)
if platform.system() == "Windows":
    _DEFAULT_RETROARCH = shutil.which("retroarch") or "retroarch.exe"
    _DEFAULT_BSNES_CORE = ""  # Not typically used on Windows
else:
    _DEFAULT_RETROARCH = "/usr/bin/retroarch"
    _DEFAULT_BSNES_CORE = "/usr/lib/x86_64-linux-gnu/libretro/bsnes_mercury_accuracy_libretro.so"


# --- Process-global Mesen2 native-library state (issue #123) -----------------
#
# Mesen2 exposes a singleton emulator inside the loaded MesenCore.so:
# `InitDll` and `InitializeEmu` register process-wide threads, callbacks,
# audio device, video decoder, controller config, and debugger state. Calling
# them more than once per process accumulates state on the C side — register
# tables, debug callbacks, controller mappings — that the .so never frees
# until the process exits. After several hundred init cycles MesenCore.so
# segfaults inside a stale callback dispatch (issue #123).
#
# Pre-fix: every `MesenRunner()` construction re-ran the full init sequence
# because the `_initialized` guard was per-instance. Even when individual
# tests used `@pytest.fixture(scope="module")`, a full pytest run still
# created N >> 200 fresh instances across all test modules.
#
# Fix: hoist the init+lib-handle state to module scope. The first
# `MesenRunner` construction in a process performs InitDll + InitializeEmu +
# SetSnesConfig once. Subsequent constructions reuse the same library handle
# and skip the native init entirely. `stop()` calls `Stop(0)` (and the
# C-API `ReleaseDebugger` when available) but never tears down the global
# emulator — that lives until process exit.
#
# All access to these globals is single-threaded (pytest runs sequentially
# in one Python thread; Mesen2 runs its own internal emulator thread but
# we don't touch these globals from there).
_GLOBAL_LIB: Optional[ctypes.CDLL] = None
_GLOBAL_INIT_DONE: bool = False
_GLOBAL_INIT_PARAMS: Optional[tuple] = None  # (core_path, home_dir, no_audio)


# --- dlopen-order hazard with scientific Python stack (issue #123, part 2) ---
#
# Even with the InitDll/InitializeEmu deduplication above, a separate failure
# mode produces the same opaque process-segfault: the order in which
# MesenCore.so and scipy/numpy's bundled native libraries are loaded into the
# process matters.
#
# Reproducer:
#     python -c "import scipy.signal; \
#                from infrastructure.test_harness.mesen_runner import MesenRunner; \
#                r = MesenRunner(); r.load_rom('build/bootstrap.sfc', 0.05); r.stop()"
#     -> Segmentation fault (139) inside ctypes.CDLL(MesenCore.so)
#
# Reverse order:
#     python -c "from infrastructure.test_harness.mesen_runner import MesenRunner; \
#                r = MesenRunner(); r.load_rom('build/bootstrap.sfc', 0.05); r.stop(); \
#                import scipy.signal"
#     -> exit 0
#
# scipy/numpy ship bundled `libscipy_openblas-*.so` and `libgfortran-*.so` and
# load them lazily on first import. MesenCore.so is a C++ binary linked against
# libstdc++, libSDL2, ALSA, and pulse. When scipy's libgfortran/openblas
# initializes first, its OpenMP/pthread/TLS slot allocation conflicts with
# MesenCore's static C++ initializers — the first `dlopen("MesenCore.so")`
# in that state segfaults inside glibc's loader.
#
# This is a pre-existing pytest collection/import-order accident. The early
# tests (`tests/audio/test_brr_algorithm.py`, etc.) `import scipy.signal`,
# numpy, etc. before any MesenRunner-using test file is collected. By the
# time `test_col_map_768.py` constructs its first runner, the loader is
# already in the bad state.
#
# Fix: dlopen MesenCore at *this module's import time*, before any test
# module has had a chance to import scipy. The `MesenRunner` class is the
# canonical entry point in `tests/conftest.py`'s sys.path, so this module
# is imported very early in the pytest session — well before scipy.
#
# We do NOT yet call `InitDll` / `InitializeEmu` here (those still happen
# lazily in `_global_initialize` so test failure modes around the init
# sequence are still localized to constructor invocation). Just `dlopen`
# is enough to claim the loader's TLS slots before scipy does.
#
# If MesenCore.so is missing the eager preload silently no-ops; the
# real `FileNotFoundError` is raised later from `_global_initialize`
# with the same diagnostic message it always has.
def _eager_preload_mesen_core() -> Optional[ctypes.CDLL]:
    """Eagerly dlopen MesenCore.so at module import time.

    Returns the loaded handle or None if the .so was not found. The
    handle is cached in the module-level ``_PRELOAD_HANDLE`` so the
    Python GC doesn't dispose it before ``_global_initialize`` reuses it.

    This must run before any test module imports scipy/numpy. Because
    ``tests/conftest.py`` puts ``infrastructure/test_harness`` on the
    sys.path and several test files do ``from mesen_runner import ...``
    at module scope, this hook fires very early in pytest collection —
    typically before any scientific-Python import.
    """
    if not os.path.exists(_DEFAULT_CORE_PATH):
        return None
    try:
        # RTLD_GLOBAL would be preferable (so MesenCore's symbols are
        # visible to subsequently-loaded SDL backends) but we can't
        # change the load mode mid-stream and ctypes.CDLL defaults to
        # RTLD_LOCAL. The ordering claim — MesenCore loads its
        # libstdc++/libSDL/libgfortran-equivalent dependencies before
        # scipy's bundled libgfortran/openblas does — works either way.
        return ctypes.CDLL(_DEFAULT_CORE_PATH)
    except OSError:
        # Don't fail module import on a broken .so — keep the lazy
        # path's diagnostic for the real failure surface.
        return None


_PRELOAD_HANDLE: Optional[ctypes.CDLL] = _eager_preload_mesen_core()


def _bind_global_functions(lib: ctypes.CDLL) -> None:
    """Bind C function signatures on a freshly-loaded MesenCore library.

    Called exactly once per process from ``_global_initialize``.
    """
    lib.InitDll.restype = None
    lib.InitDll.argtypes = []

    lib.InitializeEmu.restype = None
    lib.InitializeEmu.argtypes = [
        ctypes.c_char_p,    # homeFolder
        ctypes.c_void_p,    # windowHandle
        ctypes.c_void_p,    # viewerHandle
        ctypes.c_int,       # softwareRenderer
        ctypes.c_int,       # noAudio
        ctypes.c_int,       # noVideo
        ctypes.c_int,       # noInput
    ]

    lib.LoadRom.restype = ctypes.c_int
    lib.LoadRom.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

    lib.Stop.restype = None
    lib.Stop.argtypes = [ctypes.c_int]

    lib.InitializeDebugger.restype = None
    lib.InitializeDebugger.argtypes = []

    # ReleaseDebugger may not be present on every Mesen2 build — bind
    # defensively so the runner still works on older cores.
    if hasattr(lib, "ReleaseDebugger"):
        lib.ReleaseDebugger.restype = None
        lib.ReleaseDebugger.argtypes = []

    lib.GetMemoryValue.restype = ctypes.c_uint8
    lib.GetMemoryValue.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    lib.GetMemorySize.restype = ctypes.c_int32
    lib.GetMemorySize.argtypes = [ctypes.c_uint32]

    lib.GetMemoryState.restype = None
    lib.GetMemoryState.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

    # --- Memory WRITE path (S5-a, mirrors the read path above) ----------------
    # MesenCore.so exports three write entry points. The InteropDLL source is
    # not vendored locally (/tmp/Mesen2 holds only the built MesenCore.so), so
    # the signatures below were recovered by disassembling each export's
    # prologue and reading the System V AMD64 argument-register usage:
    #
    #   SetMemoryValue (uint32 memType, uint32 addr, uint8 value)
    #       %edi=memType, %esi=addr, %dl=value. Exact mirror of GetMemoryValue.
    #   SetMemoryValues(uint32 memType, uint32 addr, uint8* buffer, int32 length)
    #       %edi=memType, %esi=addr, %rdx=buffer, %ecx=length. Writes `length`
    #       bytes starting at `addr` — the bulk mirror of read_bytes()'s range.
    #   SetMemoryState(uint32 memType, uint8* buffer, int32 length)
    #       %edi=memType, %rsi=buffer, %edx=length. Writes from region offset 0
    #       (no start address) — region-prefix replace; bound for completeness.
    #
    # Bound defensively (hasattr) so the runner still imports on an older core
    # that lacks the write exports; write_bytes() raises a clear RuntimeError at
    # call time when the needed export is missing.
    if hasattr(lib, "SetMemoryValue"):
        lib.SetMemoryValue.restype = None
        lib.SetMemoryValue.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint8,
        ]
    if hasattr(lib, "SetMemoryValues"):
        lib.SetMemoryValues.restype = None
        lib.SetMemoryValues.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int32,
        ]
    if hasattr(lib, "SetMemoryState"):
        lib.SetMemoryState.restype = None
        lib.SetMemoryState.argtypes = [
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int32,
        ]

    # --- Per-address access counters (break-on-uninitialized-read detector) ---
    # Mesen exposes per-address read/write/exec counters via the debugger. An
    # uninitialized read is a byte whose WriteCounter==0 (never written since
    # power-on) but ReadCounter>0 (was read) in volatile RAM — exactly the
    # hardware-fidelity bug the random-power-on regime exists to catch. Bound
    # defensively: older cores may lack these exports (the detector raises a
    # clear RuntimeError at call time when missing). See _AddressCounters and
    # get_uninitialized_reads() below.
    if hasattr(lib, "GetMemoryAccessCounts"):
        lib.GetMemoryAccessCounts.restype = None
        # (uint32 offset, uint32 length, uint32 memoryType, AddressCounters* out)
        lib.GetMemoryAccessCounts.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
    if hasattr(lib, "ResetMemoryAccessCounts"):
        lib.ResetMemoryAccessCounts.restype = None
        lib.ResetMemoryAccessCounts.argtypes = []

    lib.IsRunning.restype = ctypes.c_int
    lib.IsRunning.argtypes = []

    lib.SetInputOverrides.restype = None
    lib.SetInputOverrides.argtypes = [ctypes.c_uint32, DebugControllerState]

    lib.SetSnesConfig.restype = None
    lib.SetSnesConfig.argtypes = [_SnesConfig]

    lib.TakeScreenshot.restype = None
    lib.TakeScreenshot.argtypes = []

    # Audio recording (WAV capture)
    lib.WaveRecord.restype = None
    lib.WaveRecord.argtypes = [ctypes.c_char_p]

    lib.WaveStop.restype = None
    lib.WaveStop.argtypes = []

    lib.WaveIsRecording.restype = ctypes.c_bool
    lib.WaveIsRecording.argtypes = []

    # --- Deterministic frame-stepping (S7 M1) — bind defensively so the
    # runner still imports and works on older cores that lack the debug
    # stepping exports (same convention as ReleaseDebugger above). The
    # frame-step API raises a clear RuntimeError at call time when any
    # of these is missing.
    if hasattr(lib, "Step"):
        lib.Step.restype = None
        # Disassembly-verified: (uint8 cpuType, int32 count, uint32 stepType).
        # c_uint32 for cpuType is ABI-safe (the callee reads only %dil).
        lib.Step.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
    if hasattr(lib, "IsExecutionStopped"):
        lib.IsExecutionStopped.restype = ctypes.c_bool
        lib.IsExecutionStopped.argtypes = []
    if hasattr(lib, "ResumeExecution"):
        lib.ResumeExecution.restype = None
        lib.ResumeExecution.argtypes = []
    if hasattr(lib, "GetPpuState"):
        lib.GetPpuState.restype = None
        lib.GetPpuState.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    if hasattr(lib, "SetEmulationFlag"):
        lib.SetEmulationFlag.restype = None
        lib.SetEmulationFlag.argtypes = [ctypes.c_uint32, ctypes.c_bool]


# --- Hardware-faithful power-on memory state (SF_HW_POWERON) -----------------
#
# Real SNES RAM/VRAM/CGRAM/OAM power on holding garbage, NOT zero. A ROM that
# DISPLAYS a region it never initialized will show that garbage on real
# hardware; on an emulator that zero-fills RAM the same ROM looks fine. This is
# a silent-corruption class — the harness masking it (zero-init) is the worst
# state, because the suite goes green while the cart is broken on metal.
#
# The motivating uninitialized-display flapper was the Phase-13 standalone town
# ROM (tests/phase13/rpg_town_13_13.asm): it rendered an uninitialized OBJ-CHR
# block (the Child-NPC tiles) that varies across power-ons, which is exactly the
# bug class tools/render_determinism_check.py (G6) was built to catch. NOTE: the
# CURRENT RPG-slice S2 town is CLEAN — it initializes the memory it displays and
# is deterministic across power-ons. The S2-corruption owner directive that
# launched this workstream traces to that Phase-13 town flapper, not to a bug in
# the S2 slice itself. (Earlier wording here mis-attributed the flapper to S2.)
#
# Mesen2's RamState enum (Core/Shared/SettingTypes.h):
#     Random   = 0   <- true per-power-cycle randomness (mt19937 seeded from
#                       std::random_device once per process; varies every run)
#     AllZeros = 1   <- fixed 0x00 fill (a deterministic emulator convenience,
#                       NOT hardware-faithful)
#     AllOnes  = 2   <- fixed 0xFF fill (also a fixed fill — this is the value a
#                       prior experiment misread as "random"; it is constant)
#
# Mesen2 consumes RamPowerOnState for ALL of WRAM, VRAM, CGRAM, OAM, SRAM
# (SnesMemoryManager / SnesPpu / BaseCartridge -> EmuSettings::InitializeRam).
# The separate EnableRandomPowerOnState bool gates only the EXTRA PPU
# register-latch randomization (SnesPpu::RandomizeState); it does NOT gate the
# RAM fill.
#
# IMPORTANT (the O2 finding): a zero-initialized ctypes _SnesConfig() leaves
# RamPowerOnState == 0 == RamState::Random. So the harness has been running
# RANDOM power-on for RAM all along — it was never zero-init. The
# SF_HW_POWERON knob therefore exists to (a) make the intent explicit and (b)
# add the PPU-latch randomization (full hardware fidelity), while leaving an
# escape hatch to FORCE zero-init for deterministic local debugging.
#
# G6 synergy: random power-on + the G6 render-determinism gate is a true
# uninitialized-memory DETECTOR. A correct ROM initializes every pixel it
# displays, so its screenshot stays byte-identical across fresh power-ons (G6
# PASS). A ROM that displays uninitialized memory flaps across fresh power-ons
# (G6 FAIL) — pinpointing a latent hardware-fidelity bug.
#
# Knob (env var SF_HW_POWERON), read once per process at global init:
#   unset / "" / "0" / "default"  -> leave the struct as-is (current behavior;
#                                    RamPowerOnState=Random, PPU-latch rand OFF).
#                                    Default is unchanged so the suite stays
#                                    green until the owner sequences a rollout.
#   "1" / "random" / "hw"         -> RamPowerOnState=Random AND
#                                    EnableRandomPowerOnState=True (full
#                                    hardware fidelity, incl. PPU latches).
#   "zeros" / "zero"              -> RamPowerOnState=AllZeros (force fixed
#                                    zero-init; deterministic-debug escape hatch).
#   "ones"                        -> RamPowerOnState=AllOnes (fixed 0xFF;
#                                    diagnostic — surfaces uninit regions as a
#                                    constant pattern).

# Mesen2 RamState enum values (Core/Shared/SettingTypes.h).
_RAMSTATE_RANDOM = 0
_RAMSTATE_ALLZEROS = 1
_RAMSTATE_ALLONES = 2

# Mesen2 ConsoleRegion enum values (Core/Shared/SettingTypes.h).
_REGION_AUTO = 0
_REGION_NTSC = 1
_REGION_PAL = 2


def _apply_region(cfg: "_SnesConfig") -> None:
    """Apply the SF_REGION console-region knob to ``cfg`` in place.

    SF_REGION unset / "" / "auto"  -> no-op (Mesen ConsoleRegion::Auto —
                                     region from the ROM header destination
                                     code; every existing run unchanged).
    SF_REGION=ntsc                 -> force 60 Hz NTSC timing.
    SF_REGION=pal                  -> force 50 Hz PAL timing (the jam's
                                     "works on NTSC and PAL" check: boot a
                                     ROM under PAL and assert its frame
                                     loop / rendering still behaves).

    Like SF_HW_POWERON this is applied once per process from
    ``_make_base_snes_config`` — one region per test process.
    """
    mode = os.environ.get("SF_REGION", "").strip().lower()
    if mode in ("", "auto", "0"):
        return
    if mode == "ntsc":
        cfg.Region = _REGION_NTSC
    elif mode == "pal":
        cfg.Region = _REGION_PAL
    else:
        raise ValueError(
            f"SF_REGION={mode!r} not recognized. Use '' / 'auto' (header "
            "destination code decides), 'ntsc', or 'pal'."
        )


def _apply_poweron_state(cfg: "_SnesConfig") -> None:
    """Apply the SF_HW_POWERON power-on-memory policy to ``cfg`` in place.

    Called once per process from :func:`_global_initialize` before
    ``SetSnesConfig``. See the module comment above for the full rationale and
    the Mesen2 RamState semantics. Default (env unset) is a no-op so existing
    behavior is preserved exactly.
    """
    mode = os.environ.get("SF_HW_POWERON", "").strip().lower()
    if mode in ("", "0", "default"):
        # No-op: preserve current behavior (zeroed struct => Random RAM fill,
        # PPU-latch randomization OFF). The suite-wide default is NOT flipped
        # here — the owner sequences the rollout from the blast-radius data.
        return
    if mode in ("1", "random", "hw"):
        cfg.RamPowerOnState = _RAMSTATE_RANDOM
        cfg.EnableRandomPowerOnState = True
    elif mode in ("zeros", "zero"):
        cfg.RamPowerOnState = _RAMSTATE_ALLZEROS
        cfg.EnableRandomPowerOnState = False
    elif mode == "ones":
        cfg.RamPowerOnState = _RAMSTATE_ALLONES
        cfg.EnableRandomPowerOnState = False
    else:
        raise ValueError(
            f"SF_HW_POWERON={mode!r} not recognized. Use one of: "
            "'' / '0' / 'default' (current behavior), '1' / 'random' / 'hw' "
            "(full hardware fidelity), 'zeros' (force zero-init), 'ones' "
            "(force 0xFF fill)."
        )


def _make_base_snes_config(force_random_latches: bool = False) -> "_SnesConfig":
    """Build the canonical harness SNES config.

    Single source of truth for the controller-port + power-on-state config
    applied both at process init (:func:`_global_initialize`) and by the
    per-runner re-apply path (:meth:`MesenRunner.set_power_on_random_latches`).

    The base config mirrors the original inline setup: SNES controller on
    Port 1, default GSU/BS-X, full channel volumes, and the explicit
    documented ``RamState::Random`` power-on default (see the long comment in
    ``_global_initialize`` for why Random is the honest default). The
    ``SF_HW_POWERON`` env knob is then layered on via
    :func:`_apply_poweron_state`.

    ``force_random_latches`` forces ``EnableRandomPowerOnState=True`` AFTER the
    env knob, for the per-golden full-fidelity path (a golden manifest's
    ``full_fidelity: true`` must randomize the PPU register latches regardless
    of the process-wide env default — this is the G6 full-power-on-fidelity
    gate). It never *disables* latches the env knob enabled; it only adds them.
    """
    cfg = _SnesConfig()
    cfg.Port1.Type = 1      # ControllerType::SnesController
    cfg.Port2.Type = 1      # ControllerType::SnesController (enables P2 SetInputOverrides)
    cfg.GsuClockSpeed = 100  # Default GSU clock
    cfg.BsxCustomDate = -1   # Default BS-X date
    for i in range(8):
        cfg.ChannelVolumes[i] = 100
    cfg.RamPowerOnState = _RAMSTATE_RANDOM
    _apply_poweron_state(cfg)
    _apply_region(cfg)
    if force_random_latches:
        cfg.EnableRandomPowerOnState = True
    return cfg


def _global_initialize(
    core_path: str,
    home_dir: str,
    enable_audio: bool,
) -> ctypes.CDLL:
    """Initialize MesenCore exactly once per process.

    Subsequent calls return the cached library handle. If the requested
    init parameters differ from the cached ones (e.g., a later
    ``MesenRunner(enable_audio=True)`` after an earlier ``enable_audio=False``)
    the original init wins and a warning is suppressed — the alternative
    is calling ``InitializeEmu`` again, which is exactly the leak this
    function exists to prevent. Tests that need different audio settings
    must run in separate processes (e.g., ``pytest-forked`` or a dedicated
    audio-recording subprocess driver).
    """
    global _GLOBAL_LIB, _GLOBAL_INIT_DONE, _GLOBAL_INIT_PARAMS

    if _GLOBAL_INIT_DONE:
        return _GLOBAL_LIB  # type: ignore[return-value]

    if not os.path.exists(core_path):
        lib_name = "MesenCore.dll" if platform.system() == "Windows" else "MesenCore.so"
        if platform.system() == "Windows":
            hint = (
                f"{lib_name} not found at {core_path}. "
                "Place MesenCore.dll in tools/Mesen/ or set core_path explicitly."
            )
        else:
            hint = (
                f"{lib_name} not found at {core_path}. "
                "Build Mesen2 first: cd /tmp/Mesen2 && make -j$(nproc)"
            )
        raise FileNotFoundError(hint)

    # Prefer the eagerly-preloaded handle when the caller is requesting
    # the same path (the common case — DEFAULT_CORE_PATH). Re-dlopening
    # a non-default path is fine; ctypes.CDLL refcounts under glibc.
    if _PRELOAD_HANDLE is not None and core_path == _DEFAULT_CORE_PATH:
        lib = _PRELOAD_HANDLE
    else:
        lib = ctypes.CDLL(core_path)
    _bind_global_functions(lib)

    os.makedirs(home_dir, exist_ok=True)

    # Initialize the global emulator instance — exactly once.
    lib.InitDll()

    no_audio = 0 if enable_audio else 1
    lib.InitializeEmu(
        home_dir.encode("utf-8"),
        None,   # windowHandle
        None,   # viewerHandle
        1,      # softwareRenderer
        no_audio,
        1,      # noVideo
        0,      # noInput (0 = enabled, needed for SetInputOverrides)
    )

    # Configure SNES controller on Port 1 so SetInputOverrides works, and
    # codify RamState::Random (=0) as the EXPLICIT, documented harness default
    # rather than relying on the struct-zero coincidence. This is the
    # hardware-faithful power-on model: real SNES WRAM/VRAM/CGRAM/OAM are DRAM
    # garbage at cold power-on with no reproducible pattern, so flat-random is
    # the honest worst case that exposes uninitialized-read bugs (G6 +
    # break-on-uninit-read consume it). Re-seeded per LoadRom by Mesen
    # (SnesConsole::LoadRom -> InitializeRam advances the shared PRNG) so each
    # power-on draws fresh garbage. Writing it explicitly is a NO-OP relative to
    # the prior behavior (the zeroed field was already Random) — it does not
    # change any observable result; it only removes the silent dependence on the
    # struct's default. SF_HW_POWERON may still override this (and add PPU-latch
    # randomization) — _apply_poweron_state (inside _make_base_snes_config) runs
    # last so the env knob wins when set. See docs/conventions/power_on_fidelity.md.
    cfg = _make_base_snes_config()
    lib.SetSnesConfig(cfg)

    _GLOBAL_LIB = lib
    _GLOBAL_INIT_DONE = True
    _GLOBAL_INIT_PARAMS = (core_path, home_dir, no_audio)
    return lib


def _global_lib_or_die() -> ctypes.CDLL:
    """Return the process-global MesenCore handle, raising if not init'd."""
    if _GLOBAL_LIB is None:
        raise RuntimeError(
            "MesenCore library not initialized. Construct a MesenRunner first."
        )
    return _GLOBAL_LIB


def _global_atexit() -> None:
    """Quiesce MesenCore at Python exit.

    This is the second half of the issue #123 fix. The first half
    (``_global_initialize``) ensures we only init once per process.
    The second half is: when Python tears down, we have to make sure
    MesenCore's emulator thread is parked before its DT_FINI destructors
    run, otherwise the DSO unloader and the running emulator thread
    race over shared state and segfault (or trip glibc's "double free
    or corruption" detector — both observed locally on Mesen2 r2.x).

    A test that constructs a ``MesenRunner`` but never calls ``stop()``
    (common in pytest fixtures that ``return MesenRunner()`` without a
    teardown ``yield``) leaves the emulator thread running. The class's
    ``__del__`` parks it on garbage collection, but GC isn't guaranteed
    to run before Python shutdown — and if it doesn't, the process
    crashes on exit. Registering this here gives us a deterministic
    final stop, regardless of GC order.

    We intentionally do NOT free the library, the debugger, or the
    emulator instance. ``Stop(0)`` is sufficient to put the thread in
    a quiescent state where DT_FINI can run cleanly. Calling
    ``ReleaseDebugger`` / ``Release`` here would be safer in principle
    but historically introduces additional teardown sequencing risk
    (the C++ destructors expect a specific call order); ``Stop(0)``
    is the conservative subset that consistently produces clean exits
    in our test environment.
    """
    if _GLOBAL_LIB is None:
        return
    try:
        _GLOBAL_LIB.Stop(0)
    except Exception:
        # During Python shutdown ctypes may raise on attribute access
        # if the module's globals have already been torn down. Swallowing
        # is correct here — we're in a best-effort cleanup path.
        pass


atexit.register(_global_atexit)


class MesenRunner:
    """
    Drives Mesen2's native emulator core for headless ROM testing.

    Uses the InitDll → InitializeEmu → LoadRom → GetMemoryValue flow
    with noAudio/noVideo/noInput for fully headless cycle-accurate emulation.

    The emulator runs on an internal thread. After loading a ROM and waiting
    for a configurable number of seconds (default 3), memory can be read
    from any region (WRAM, SRAM, VRAM, OAM, CGRAM, SPC RAM).
    """

    def __init__(
        self,
        core_path: str = _DEFAULT_CORE_PATH,
        home_dir: str = _DEFAULT_HOME_DIR,
        enable_audio: bool = False,
        fast_mode: bool = False,
    ):
        """
        Args:
            core_path: Path to MesenCore.so / MesenCore.dll.
            home_dir: Mesen2 home directory (Screenshots/ + Saves/ subdirs
                live here). Defaults to the module ``_DEFAULT_HOME_DIR``,
                which honors the ``SF_MESEN_HOME`` env override — set it
                per-worktree to isolate parallel sessions (see
                ``_detect_home_dir``).
            enable_audio: When True, audio processing runs so WAV
                recording via ``WaveRecord()`` produces output.
            fast_mode: When True, drop the synthetic 1/60 s pacing in
                ``run_frames`` (Mesen2 advances on its own thread at
                full speed) and tighten the screenshot poll cadence
                from 5 ms × 40 to 1 ms × 200 (same 200 ms cap, finer
                detection). Default False to preserve existing test
                semantics. Used by the SuperForge MCP preview panel
                to hit 60 fps end-to-end. See S-3-perf-1 paper-cut +
                ``screenshot_pump/THROUGHPUT_REPORT.md`` for the
                measured attribution.
        """
        self._core_path = core_path
        self._home_dir = home_dir
        self._enable_audio = enable_audio
        self._fast_mode = fast_mode
        self._lib: Optional[ctypes.CDLL] = None
        self._initialized = False
        self._rom_loaded = False
        self._debugger_active = False
        # Deterministic frame-stepping state (S7 M1). True while this
        # runner has execution parked via debug_break()/frame_step().
        self._frame_stepping = False
        # Scratch buffer for GetPpuState, allocated lazily on first use.
        self._ppu_state_buf = None
        # G3 read-logging re-entrancy counter — when > 0, nested reads
        # (read_byte called from read_bytes) do not double-log; only the
        # outermost public read produces a record.
        self._readlog_suppressed = 0

    @property
    def fast_mode(self) -> bool:
        """Whether the runner is in fast (preview-panel) mode."""
        return self._fast_mode

    def _ensure_initialized(self):
        """Bind to the process-global MesenCore library (issue #123).

        The first ``MesenRunner`` constructed in a process performs the
        full ``InitDll`` → ``InitializeEmu`` → ``SetSnesConfig`` sequence
        once via :func:`_global_initialize`. Every subsequent runner
        instance simply reuses the cached library handle. This is
        critical: re-running ``InitializeEmu`` on Mesen2's singleton
        emulator accumulates per-call C-side state (debug callbacks,
        controller registrations, audio device handles) that eventually
        corrupts the heap and segfaults during DSO teardown — the
        original symptom of issue #123.

        Per-instance state (``_rom_loaded``, ``_debugger_active``) is
        still tracked locally so each runner can cycle through
        ``load_rom`` / ``stop`` cleanly without colliding with another
        runner's lifecycle bookkeeping.
        """
        if self._initialized:
            return
        self._lib = _global_initialize(
            self._core_path, self._home_dir, self._enable_audio
        )
        self._initialized = True

    def set_power_on_random_latches(self, enable: bool) -> None:
        """Toggle PPU register-latch power-on randomization for the NEXT load.

        This re-applies the global Mesen SNES config with
        ``EnableRandomPowerOnState`` forced to ``enable`` (RAM power-on stays
        ``Random``). Mesen samples ``EnableRandomPowerOnState`` when it
        constructs the ``SnesPpu`` at ``LoadRom`` (``SnesPpu::RandomizeState``),
        so this MUST be called BEFORE :meth:`load_rom` to take effect on that
        load. ``SetSnesConfig`` mutates the process-global config — call with
        ``enable=False`` afterwards to restore the harness default if a later
        load in the same process must not see randomized latches.

        This is the mechanism behind the golden manifest ``full_fidelity``
        flag (G6 full-power-on-fidelity gate): a full-fidelity golden is
        captured with the PPU latches randomized so the render-determinism
        check exercises true cold-boot conditions. A correctly-initialized ROM
        (full PPU-register init under forced blank — see
        ``infrastructure/rom_template/ppu_reset.inc``) renders byte-identically
        whether the latches are randomized or not. See
        ``docs/conventions/power_on_fidelity.md`` and
        ``docs/sprints/power_on_fullfidelity_plan.md``.
        """
        self._ensure_initialized()
        cfg = _make_base_snes_config(force_random_latches=enable)
        if not enable:
            # Explicitly clear so a prior full-fidelity load doesn't leak its
            # randomized latches into a subsequent default-path load.
            cfg.EnableRandomPowerOnState = False
        self._lib.SetSnesConfig(cfg)  # type: ignore[union-attr]

    def load_rom(self, rom_path: str, run_seconds: float = 3.0):
        """
        Load a ROM and let it execute for the specified duration.

        Args:
            rom_path: Path to .sfc ROM file.
            run_seconds: How long to let the emulation run before reading
                memory. **Wall-clock time, not emulated time.** The clock
                starts at LoadRom (i.e. INCLUDES boot init — RESET vector,
                WRAM clear, asset DMA, etc.), not at frame 0.

                Mesen2 advances frames on its own thread; the typical
                steady-state rate is ~60 fps for the first few seconds,
                BUT degrades for long runs (~50 fps at run_seconds=5,
                ~10 fps at run_seconds=20, ~5 fps at run_seconds=120 —
                debugger state and memory accumulate). Practical effect:
                tests that need to observe frame > ~600 in headless need
                to either bump run_seconds substantially OR poll a frame
                counter from WRAM and bail when it lands. Interactive
                verification past frame ~600 is only feasible in real
                desktop Mesen2 at 60 fps.

                See ``run_frames`` for fast_mode semantics on synthetic
                pacing — fast_mode applies there, not here. ``run_seconds``
                gives the emulator real time to advance and is not elided
                under fast_mode.
        """
        self._ensure_initialized()
        abs_path = os.path.abspath(rom_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"ROM not found: {abs_path}")

        # If a previous test on this runner left execution parked in
        # frame-stepping mode, resume before reloading — a parked
        # emulator makes the post-load sleep below a no-op (the new ROM
        # would never boot). Best-effort, only fires if the new
        # frame-step API was used without a matching debug_resume().
        if self._frame_stepping:
            try:
                self.debug_resume()
            except Exception:
                self._frame_stepping = False

        loaded = self._lib.LoadRom(abs_path.encode("utf-8"), None)
        if not loaded:
            raise RuntimeError(f"Mesen2 failed to load ROM: {abs_path}")
        self._rom_loaded = True

        # Let the emulation run
        time.sleep(run_seconds)

        # Initialize debugger for memory access
        if not self._debugger_active:
            self._lib.InitializeDebugger()
            self._debugger_active = True

    # --- Break-on-uninitialized-read detector --------------------------------
    #
    # Opt-in / queryable — NOT wired to auto-fail the existing suite. A sprint
    # opts a ROM in by calling load_rom_with_uninit_detection() then
    # get_uninitialized_reads() / assert_no_uninitialized_reads(). See
    # docs/conventions/power_on_fidelity.md for the opt-in workflow.

    def _require_access_counter_api(self) -> None:
        """Raise if the loaded MesenCore lacks the access-counter exports."""
        if not hasattr(self._lib, "GetMemoryAccessCounts"):
            raise RuntimeError(
                "This MesenCore build does not export GetMemoryAccessCounts — "
                "the uninitialized-read detector requires a Mesen2 core with "
                "the debugger access-counter API. Rebuild Mesen2 from a recent "
                "SourMesen/Mesen2 checkout (the standard SuperForge core has it)."
            )

    def load_rom_with_uninit_detection(
        self,
        rom_path: str,
        run_seconds: float = 1.5,
    ) -> None:
        """Load a ROM with per-address access counting armed from power-on.

        Unlike :meth:`load_rom` (which inits the debugger *after* the run), this
        initializes the debugger BEFORE the ROM executes so every read/write is
        counted from the first cycle. That is mandatory for the
        uninitialized-read detector: a byte's "was it written before it was
        read" history is only complete if the counters were live for the whole
        run. Call :meth:`get_uninitialized_reads` or
        :meth:`assert_no_uninitialized_reads` afterwards.
        """
        self._ensure_initialized()
        self._require_access_counter_api()
        abs_path = os.path.abspath(rom_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"ROM not found: {abs_path}")

        if self._frame_stepping:
            try:
                self.debug_resume()
            except Exception:
                self._frame_stepping = False

        loaded = self._lib.LoadRom(abs_path.encode("utf-8"), None)
        if not loaded:
            raise RuntimeError(f"Mesen2 failed to load ROM: {abs_path}")
        self._rom_loaded = True

        # Arm the debugger (and thus the access counters) BEFORE running so the
        # counters reflect the full power-on-to-now history. ResetMemoryAccessCounts
        # zeroes any stale counts carried over from a prior ROM on this process-
        # global core, so the detector measures only this ROM's accesses.
        if not self._debugger_active:
            self._lib.InitializeDebugger()
            self._debugger_active = True
        if hasattr(self._lib, "ResetMemoryAccessCounts"):
            self._lib.ResetMemoryAccessCounts()

        # Now let the ROM run with counters live.
        time.sleep(run_seconds)

    def get_access_counts(self, mem_type: MemoryType):
        """Return the per-address access counters for a memory region.

        A list of :class:`_AddressCounters` (read/write/exec stamp + count),
        one per byte of *mem_type*. Requires the debugger to be active — use
        :meth:`load_rom_with_uninit_detection` to arm counting from power-on.
        """
        self._require_access_counter_api()
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom_with_uninit_detection() first.")
        size = self._lib.GetMemorySize(int(mem_type))
        if size <= 0:
            return []
        buf = (_AddressCounters * size)()
        self._lib.GetMemoryAccessCounts(0, size, int(mem_type), buf)
        return list(buf)

    def get_uninitialized_reads(
        self,
        mem_types=UNINIT_DETECT_MEMORY_TYPES,
    ) -> dict:
        """Map each memory type to the list of addresses read-before-written.

        An uninitialized read is a byte whose WriteCounter == 0 (never written
        since power-on) and ReadCounter > 0 (was read) — Mesen's own
        UninitRead classification, recomputed from the raw counters. Only
        volatile RAM is meaningful here (see UNINIT_DETECT_MEMORY_TYPES).

        Returns ``{MemoryType: [addr, ...], ...}`` with only non-empty regions
        present. Empty dict == clean (no uninitialized reads).
        """
        result: dict = {}
        for mt in mem_types:
            counters = self.get_access_counts(mt)
            bad = [
                addr
                for addr, c in enumerate(counters)
                if c.WriteCounter == 0 and c.ReadCounter > 0
            ]
            if bad:
                result[MemoryType(int(mt))] = bad
        return result

    def assert_no_uninitialized_reads(
        self,
        mem_types=UNINIT_DETECT_MEMORY_TYPES,
        max_examples: int = 8,
    ) -> None:
        """Raise :class:`UninitializedReadError` if any uninit read was found.

        Opt-in gate a sprint calls explicitly after
        :meth:`load_rom_with_uninit_detection`. NOT wired into the default
        suite — it surfaces a real hardware-fidelity bug (a ROM displaying or
        consuming memory it never initialized) which most legacy ROMs have not
        been audited for. Roll out per-ROM (latch-hygiene backlog style), not
        big-bang.
        """
        reads = self.get_uninitialized_reads(mem_types)
        if not reads:
            return
        findings = [(mt, len(addrs)) for mt, addrs in reads.items()]
        lines = []
        for mt, addrs in reads.items():
            head = ", ".join(f"${a:04X}" for a in addrs[:max_examples])
            more = "" if len(addrs) <= max_examples else f" ... (+{len(addrs) - max_examples} more)"
            lines.append(f"  {mt.name}: {len(addrs)} byte(s) read before written — {head}{more}")
        msg = (
            "Uninitialized-memory reads detected (read-before-write since "
            "power-on). The ROM consumes or displays memory it never "
            "initialized — a real-hardware bug under random power-on. "
            "See docs/conventions/power_on_fidelity.md.\n" + "\n".join(lines)
        )
        raise UninitializedReadError(msg, findings)

    def get_memory_size(self, mem_type: MemoryType) -> int:
        """Get the size of a memory region in bytes."""
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")
        return self._lib.GetMemorySize(int(mem_type))

    def read_byte(self, mem_type: MemoryType, address: int) -> int:
        """Read a single byte from a memory region."""
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")
        # G3 read-logging — append-only, inert when off (spec §3.1). The
        # re-entrancy guard ensures a single public read produces a single
        # record: read_bytes/read_u16/read_u32 funnel through read_byte but
        # log once at the outer call.
        if not self._readlog_suppressed:
            READ_LOG.log_memory_read(mem_type, address, 1)
        value = self._lib.GetMemoryValue(int(mem_type), address)
        # G2 mutation — corrupt the RETURNED value only (never the core).
        # Skip when nested (read_bytes mutates the assembled buffer once at
        # the outer call) so a byte is never inverted twice (^0xFF^0xFF = id).
        if (not self._readlog_suppressed
                and MUTATION.enabled
                and _mem_type_is_output(mem_type)):
            return MUTATION.mutate_byte(value)
        return value

    def read_bytes(
        self,
        mem_type: MemoryType,
        address: int,
        count: int,
    ) -> bytes:
        """Read multiple bytes from a memory region.

        Uses bulk GetMemoryState when reading >=16 bytes, falling back
        to per-byte GetMemoryValue for small reads.
        """
        # G3 read-logging — record the public read intent (mem_type, addr,
        # count) once, then suppress nested read_byte logging for the
        # small-read path so each public call yields one record.
        if not self._readlog_suppressed:
            READ_LOG.log_memory_read(mem_type, address, count)
        # G2 mutation applies once, at the OUTERMOST public read. When this
        # call is itself nested (read_u16/read_u32 funnel through here), the
        # outer caller mutates the assembled value instead. nested == True
        # means "do not mutate here".
        nested = self._readlog_suppressed > 0
        self._readlog_suppressed += 1
        try:
            if count < 16:
                result = bytearray(count)
                for i in range(count):
                    result[i] = self.read_byte(mem_type, address + i)
                data = bytes(result)
            else:
                # Bulk read: dump the full region and slice
                size = self.get_memory_size(mem_type)
                if size <= 0 or address + count > size:
                    # Fall back to per-byte for out-of-range reads
                    result = bytearray(count)
                    for i in range(count):
                        result[i] = self.read_byte(mem_type, address + i)
                    data = bytes(result)
                else:
                    buf = (ctypes.c_uint8 * size)()
                    self._lib.GetMemoryState(int(mem_type), buf)
                    data = bytes(buf[address:address + count])
        finally:
            self._readlog_suppressed -= 1
        # Corrupt the returned copy only (never the core) when mutation is on,
        # this is an output region, and we are the outermost public read.
        if not nested and MUTATION.enabled and _mem_type_is_output(mem_type):
            return MUTATION.mutate_bytes(data)
        return data

    def read_region(self, mem_type: MemoryType) -> bytes:
        """Read an entire memory region into a bytes object."""
        # G3 read-logging — a full-region dump is logged with count == size.
        size = self.get_memory_size(mem_type)
        if not self._readlog_suppressed:
            READ_LOG.log_memory_read(mem_type, 0, max(size, 0))
        if size <= 0:
            return b""
        buf = (ctypes.c_uint8 * size)()
        self._lib.GetMemoryState(int(mem_type), buf)
        data = bytes(buf)
        # G2 mutation — corrupt the whole returned region copy (spec §3.4)
        # when mutation is on and this is an output region. Core untouched.
        if MUTATION.enabled and _mem_type_is_output(mem_type):
            return MUTATION.mutate_bytes(data)
        return data

    def read_u16(self, mem_type: MemoryType, address: int) -> int:
        """Read a 16-bit little-endian value."""
        data = self.read_bytes(mem_type, address, 2)
        return struct.unpack("<H", data)[0]

    def read_u32(self, mem_type: MemoryType, address: int) -> int:
        """Read a 32-bit little-endian value."""
        data = self.read_bytes(mem_type, address, 4)
        return struct.unpack("<I", data)[0]

    # --- Memory WRITE API (S5-a) ---------------------------------------------
    #
    # Symmetric with read_byte / read_bytes above: same MemoryType enum, same
    # addressing convention (an offset within the region, NOT a SNES bus
    # address). The motivating use is modelling a battery-backed SRAM that
    # survives a load_rom() reload — Mesen randomizes SRAM on every load
    # (RamPowerOnState=Random), so a save→reset→load test must capture the
    # saved bytes with read_bytes(), reload, and write them back with
    # write_bytes() before the ROM's boot-load reads SRAM. See
    # persist_sram_across_reload() below for the full contract.

    def _require_write_api(self) -> None:
        """Raise if the loaded MesenCore lacks the memory-write exports."""
        if not (hasattr(self._lib, "SetMemoryValues")
                or hasattr(self._lib, "SetMemoryValue")):
            raise RuntimeError(
                "This MesenCore build does not export SetMemoryValues / "
                "SetMemoryValue — the memory-write API requires a Mesen2 core "
                "with the debugger memory-write entry points. Rebuild Mesen2 "
                "from a recent SourMesen/Mesen2 checkout (the standard "
                "SuperForge core has them)."
            )

    def write_byte(self, mem_type: MemoryType, address: int, value: int) -> None:
        """Write a single byte to a memory region.

        Args:
            mem_type: MemoryType region (e.g. SnesSaveRam).
            address: Offset within the region (not a SNES bus address).
            value: Byte to write (0..255; masked to 8 bits).
        """
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")
        self._require_write_api()
        self._lib.SetMemoryValue(int(mem_type), address, value & 0xFF)

    def write_bytes(
        self,
        mem_type: MemoryType,
        address: int,
        data: bytes,
    ) -> None:
        """Write *data* into a memory region starting at *address*.

        The mirror of :meth:`read_bytes`. Uses the bulk ``SetMemoryValues``
        export (writes ``len(data)`` bytes starting at ``address``) when
        available, falling back to a per-byte ``SetMemoryValue`` loop on an
        older core. The per-byte fallback is O(n) C calls — fine for the
        small SRAM-slot writes this exists for (tens to a few hundred bytes),
        but avoid it for whole-region (>4 KB) writes.

        Args:
            mem_type: MemoryType region (e.g. SnesSaveRam).
            address: Offset within the region to start writing at.
            data: Bytes to write.

        Notes:
            This writes the EMULATED memory directly; it does not go through
            the SNES bus or any cartridge write-protect logic. For SnesSaveRam
            that is exactly what we want — it models the battery holding state
            across a power cycle.
        """
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")
        self._require_write_api()
        if not data:
            return
        buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        if hasattr(self._lib, "SetMemoryValues"):
            self._lib.SetMemoryValues(int(mem_type), address, buf, len(data))
        else:
            # Per-byte fallback (older core without the bulk export).
            for i, b in enumerate(data):
                self._lib.SetMemoryValue(int(mem_type), address + i, b & 0xFF)

    def persist_sram_across_reload(
        self,
        rom_path: str,
        *,
        capture_addr: int = 0,
        capture_len: int = 0x2000,
        capture_after_seconds: float = 3.0,
        save_fn=None,
        pre_restore_fn=None,
        restore: bool = True,
        run_after_restore_seconds: float = 3.0,
    ) -> bytes:
        """Model a battery-backed SRAM surviving a ROM power-cycle.

        Drives one full save→reset→load cycle on THIS runner and returns the
        SRAM bytes that were captured from the first boot. The cycle is:

          1. ``load_rom(rom_path, run_seconds=capture_after_seconds)`` — boot
             the ROM and let it run.
          2. If ``save_fn`` is given, call ``save_fn(self)`` — the hook that
             makes the first boot's SRAM hold the "saved" bytes. For a real S5
             ROM this drives controller input to trigger the in-game save (the
             ROM writes SRAM itself); for the harness self-test it simply does
             ``write_bytes(SnesSaveRam, …)`` to stand in for a save. If
             ``save_fn`` is None the first boot's existing SRAM is captured
             as-is (use this when the ROM auto-saves during the boot run).
          3. ``read_bytes(SnesSaveRam, capture_addr, capture_len)`` — capture
             the saved bytes (the "battery contents" at power-off).
          4. ``load_rom(rom_path, run_seconds=0.0)`` — reload the ROM (models
             pulling power and turning the console back on).
          5. If ``pre_restore_fn`` is given, call ``pre_restore_fn(self)``
             after the reload but before the restore — e.g. to explicitly
             CLEAR SRAM in a negative-control test (see SRAM-PERSISTENCE
             CAVEAT below for why a clear, not randomization, is the honest
             negative).
          6. If ``restore``: ``write_bytes(SnesSaveRam, capture_addr, captured)``
             — write the captured battery contents back into SRAM (models the
             battery holding state).
          7. sleep ``run_after_restore_seconds`` — let the second boot run and
             read the restored SRAM.

        After this returns, the runner is left loaded on the SECOND boot (post
        power-cycle) so the caller can read the restored rendered/engine state.

        SRAM-PERSISTENCE CAVEAT (verified empirically, S5-a — READ THIS):

          Mesen treats SaveRam as battery-backed and PRESERVES it across an
          in-process ``LoadRom`` of the SAME cartridge — it does NOT
          re-randomize SRAM on reload, even though ``RamPowerOnState=Random``
          (which the harness uses) randomizes WRAM/VRAM/CGRAM/OAM on every
          load. So a save→reset→load on one runner naturally carries SRAM
          across the reload WITHOUT any explicit restore write. Two
          consequences:

            * For the real S5 flow this is convenient: the save the ROM wrote
              on boot 1 is still in SRAM on boot 2, so the ROM's boot-load
              reads it back with no harness intervention. ``restore=True`` is
              then belt-and-suspenders (it re-asserts the captured bytes).
            * For a NEGATIVE control you canNOT prove "persistence is real" by
              skipping the restore and expecting randomization — SRAM persists
              regardless. The honest negative is to EXPLICITLY CLEAR SRAM after
              the reload (via ``pre_restore_fn`` doing
              ``write_bytes(SnesSaveRam, 0, b"\\x00"*N)``) and then skip the
              restore: the cleared state proves the *captured-bytes restore* is
              what re-establishes the save, not incidental survival.

          The ``write_bytes`` API still earns its keep: it is the mechanism for
          deterministically SETTING or CLEARING the battery to a known state,
          which the negative control and any "corrupt-a-byte → CRC rejects"
          test (S5-d) require.

        ORDERING CONTRACT (critical for the S5 ROM/test author):

          The restore write at step 6 happens a few milliseconds (Python time)
          after the step-4 reload's ``LoadRom`` returns — by which point the
          emulator thread has already run the ROM for several frames. So the
          restore is NOT guaranteed to land before the ROM's first RESET
          instructions execute. The S5 ROM MUST therefore be written so its
          boot-time SRAM *consumption* (the magic+CRC check that decides which
          scene to boot into) is IDEMPOTENT / RE-READABLE for a window after
          boot — i.e. it should re-read SRAM once the main loop is running
          rather than latching a one-shot decision in the first few hundred
          cycles of RESET. Two robust patterns:

            (a) Continuous re-read: the ROM keeps reading slot-0 SRAM each
                frame (or for the first N frames) and applies the saved
                scene/position when valid magic appears. The S5-a control ROM
                (tests/rpg_slice/s5a_sram_control.asm) uses this — an infinite
                loop mirroring SRAM into WRAM — so the restore is observed
                whenever it lands, with zero timing dependence.
            (b) Precise PC landing: if the ROM must latch a one-shot boot
                decision early, drive the restore at an exact program point
                with the frame-step API (debug_break + frame_step) instead of
                the ~0s wall-clock window.

          The self-test (test_harness_sram_persist.py) uses pattern (a): it
          proves the restore IS observed across the reload (positive) and,
          using ``pre_restore_fn`` to clear SRAM first, that WITHOUT the
          restore the reload does NOT hold the saved bytes (negative — proving
          the restore write is what carries the save, per the CAVEAT above).

        Args:
            rom_path: ROM to drive the cycle on.
            capture_addr: SRAM offset to capture/restore from. Default 0
                (slot 0 lives at the start of SRAM in the save_load_engine
                layout).
            capture_len: Number of SRAM bytes to capture/restore. Default
                0x2000 = 8 KB = the full lorom_128k.cfg SRAM window.
            capture_after_seconds: run_seconds for the first (save) boot.
            save_fn: Optional ``callable(runner)`` invoked after the first
                boot to make SRAM hold the saved bytes (drive input, or write
                SRAM directly). None → capture the boot's SRAM as-is.
            pre_restore_fn: Optional ``callable(runner)`` invoked after the
                reload but before the restore (step 5). Used by the negative
                control to CLEAR SRAM to a known non-save state — see the
                SRAM-PERSISTENCE CAVEAT (Mesen persists SRAM across reload, so
                clearing is the honest negative).
            restore: When False, SKIP the write-back (step 6). With a clearing
                ``pre_restore_fn``, this is the negative control that proves
                the captured-bytes restore is what re-establishes the save.
            run_after_restore_seconds: run time for the second (load) boot.

        Returns:
            The bytes captured from the first boot's SRAM (length
            ``capture_len``). When ``restore`` is True these are also written
            into the second boot's SRAM.
        """
        # 1. First boot.
        self.load_rom(rom_path, run_seconds=capture_after_seconds)
        # 2. Perform / trigger the save (hook), if provided.
        if save_fn is not None:
            save_fn(self)
        # 3. Capture the battery contents at power-off.
        captured = self.read_bytes(
            MemoryType.SnesSaveRam, capture_addr, capture_len
        )
        # 4. Power-cycle: reload. NOTE: Mesen preserves SaveRam across an
        #    in-process reload of the same cart (see SRAM-PERSISTENCE CAVEAT);
        #    WRAM/VRAM/etc. ARE re-randomized.
        self.load_rom(rom_path, run_seconds=0.0)
        # 5. Optional post-reload hook (e.g. clear SRAM for the negative case).
        if pre_restore_fn is not None:
            pre_restore_fn(self)
        # 6. Restore the battery (models persistence across the power cycle).
        if restore:
            self.write_bytes(MemoryType.SnesSaveRam, capture_addr, captured)
        # 7. Let the second boot run and read the restored SRAM.
        time.sleep(run_after_restore_seconds)
        return captured

    def take_screenshot(self, output_path: Optional[str] = None,
                        settle_frames: int = 0) -> str:
        """
        Capture a screenshot of the current emulator frame.

        Mesen2 saves PNGs to its Screenshots directory using an incrementing
        counter.  This method triggers a capture, waits briefly for the file
        to appear, then optionally moves it to *output_path*.

        Args:
            output_path: If provided, the PNG is moved here.  If None, the
                         file stays in the default Mesen2 Screenshots dir.
            settle_frames: Advance this many frames (via ``run_frames``)
                         BEFORE capturing. Default 0 = today's behavior,
                         byte-for-byte. Bundles the common
                         ``run_frames(N); take_screenshot()`` idiom into one
                         call so the rendered frame can catch up to a
                         just-changed state. Inherits ``run_frames`` semantics:
                         it is the free-running (wall-clock) settle only — a
                         no-op under ``fast_mode`` and while parked in
                         frame-stepping mode (there, advance with
                         ``frame_step`` instead).

        Frame-lag note (cost three S1 reviewers a retake each): the emulator
        commits OAM/VRAM/CGRAM one boundary behind the game update — a constant
        one-frame presentation lag (see ``debug_break``). A screenshot taken on
        the SAME frame that changed a sprite/tile therefore still shows the
        PREVIOUS rendered state; the pixels catch up one frame later. Let at
        least one frame elapse after the change before capturing:
        ``settle_frames=1`` on a free-running runner, or an extra
        ``frame_step(1)`` when parked.

        Returns:
            Absolute path to the saved PNG file.
        """
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")

        # Optional pre-capture settle (default 0 => unchanged). Uses
        # run_frames, so this is the free-running/wall-clock advance; under
        # fast_mode or a parked runner it is a no-op (see the docstring).
        if settle_frames > 0:
            self.run_frames(settle_frames)

        # G3 read-logging — a screenshot is an output-region access (the
        # composited frame). capture_frames() funnels through here, so it is
        # covered transitively (one record per frame captured).
        READ_LOG.log_screenshot()

        ss_dir = os.path.join(self._home_dir, "Screenshots")
        before = set()
        if os.path.isdir(ss_dir):
            before = set(os.listdir(ss_dir))

        self._lib.TakeScreenshot()

        # Poll the Screenshots directory for the new PNG. S-3
        # amendment AC-S3-A7 tightened the original 50 ms × 20 (1 s
        # cap) to 5 ms × 40 (200 ms cap). S-3-perf-1 adds an opt-in
        # fast-mode that further tightens to 1 ms × 200 (same 200 ms
        # cap, finer detection cadence). The throughput sprint
        # measured the 50 ms poll as ~50 ms median latency per
        # screenshot — the dominant cost of the preview pump after
        # the run_frames sleep. fast_mode poll holds the same
        # correctness guarantee (missing file still raises) with
        # ~1 ms median detection latency.
        if self._fast_mode:
            poll_interval_s = 0.001
            poll_iters = 200
        else:
            poll_interval_s = 0.005
            poll_iters = 40

        new_file = None
        for _ in range(poll_iters):
            time.sleep(poll_interval_s)
            if os.path.isdir(ss_dir):
                after = set(os.listdir(ss_dir))
                diff = after - before
                if diff:
                    new_file = os.path.join(ss_dir, sorted(diff)[0])
                    break

        if new_file is None:
            raise RuntimeError(
                "TakeScreenshot() did not produce a file within 200 ms. "
                "The VideoDecoder may not be active."
            )

        if output_path is not None:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            shutil.move(new_file, output_path)
            final_path = os.path.abspath(output_path)
        else:
            final_path = new_file

        # G2 mutation — flat-paint the produced PNG with the sentinel color so
        # any pixel-read assertion sees a corrupted frame. The emulator frame
        # buffer is untouched; we only rewrite the file we just captured.
        if MUTATION.enabled:
            _flat_paint_png(final_path)

        return final_path

    # --- Audio recording ---

    def start_audio_recording(self, output_path: str):
        """Start recording emulator audio to a WAV file.

        Requires enable_audio=True in constructor.

        Args:
            output_path: Path for the output WAV file.
        """
        if not self._rom_loaded:
            raise RuntimeError("No ROM loaded. Call load_rom() first.")
        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        self._lib.WaveRecord(abs_path.encode("utf-8"))

    def stop_audio_recording(self):
        """Stop audio recording and flush the WAV file."""
        self._lib.WaveStop()

    def is_recording_audio(self) -> bool:
        """Check if audio recording is currently active."""
        return self._lib.WaveIsRecording()

    def capture_frames(
        self,
        rom_path: str,
        frame_numbers: list,
        output_dir: str,
        prefix: str = "frame",
    ) -> list:
        """
        Load a ROM and capture screenshots at specific frame numbers.

        Each frame number corresponds to 1/60th of a second.  The method
        loads the ROM, then sleeps in increments to capture at the requested
        frame offsets.

        Args:
            rom_path: Path to .sfc ROM file.
            frame_numbers: Sorted list of frame numbers to capture (e.g.
                           [60, 120, 300]).
            output_dir: Directory to save PNGs.
            prefix: Filename prefix (files are ``{prefix}_{frame:04d}.png``).

        Returns:
            List of absolute paths to saved PNGs, one per frame number.
        """
        self._ensure_initialized()
        abs_path = os.path.abspath(rom_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"ROM not found: {abs_path}")

        os.makedirs(output_dir, exist_ok=True)

        loaded = self._lib.LoadRom(abs_path.encode("utf-8"), None)
        if not loaded:
            raise RuntimeError(f"Mesen2 failed to load ROM: {abs_path}")
        self._rom_loaded = True

        sorted_frames = sorted(frame_numbers)
        paths = []
        current_frame = 0

        for target_frame in sorted_frames:
            delta = target_frame - current_frame
            if delta > 0:
                time.sleep(delta / 60.0)
            current_frame = target_frame

            out = os.path.join(output_dir, f"{prefix}_{target_frame:04d}.png")
            path = self.take_screenshot(output_path=out)
            paths.append(path)

        if not self._debugger_active:
            self._lib.InitializeDebugger()
            self._debugger_active = True

        return paths

    def stop(self):
        """Stop emulation and quiesce the global Mesen2 emulator thread.

        We deliberately do **not** tear down the debugger or the
        emulator instance — those are process-global per the issue #123
        fix and stay live for reuse by the next ``MesenRunner``. What
        ``stop()`` guarantees is that the emulator thread is parked,
        which makes a subsequent ``load_rom`` cleanly start a fresh
        ROM session and (critically) prevents the running emulator from
        racing the DSO unloader at Python exit.
        """
        if self._initialized and self._lib is not None:
            # If this runner left execution parked (frame-stepping mode),
            # resume free-running first so Stop() doesn't race a sleeping
            # break loop and the next load_rom starts from a clean state.
            # Best-effort: never let resume failure mask the stop.
            if self._frame_stepping:
                try:
                    self.debug_resume()
                except Exception:
                    self._frame_stepping = False
            self._lib.Stop(0)
            self._rom_loaded = False
            self._debugger_active = False

    def __del__(self):
        """Best-effort cleanup for runners leaked without ``stop()``.

        Pytest fixtures that ``return MesenRunner()`` (rather than
        ``yield`` + teardown) leak a running emulator into the rest of
        the test session. Without this hook, garbage collection of the
        runner does nothing — the C-side emulator keeps running, and
        the process eventually segfaults at exit (issue #123). With it,
        the emulator at least parks when the runner is reclaimed.

        ``stop()`` itself is also registered process-globally via
        :func:`_global_atexit`, so even if GC never runs the exit path
        is still clean. The two hooks are layered intentionally:
        ``__del__`` cleans up promptly; ``atexit`` is the safety net.
        """
        try:
            self.stop()
        except Exception:
            # ``__del__`` must never raise during Python shutdown.
            pass

    # --- Input injection ---

    def set_input(self, controller_index: int = 0, **buttons: bool):
        """
        Set controller button state via Mesen2 debug API.

        Requires debugger to be initialized (happens automatically after load_rom).

        Args:
            controller_index: Controller port (0 = P1, 1 = P2).
            **buttons: Button states as keyword args.
                       Valid names: a, b, x, y, l, r, up, down, left, right,
                       select, start.

        Example:
            runner.set_input(0, right=True, a=True)

        TWO SILENT INPUT TRAPS (each delivers NO input; neither raises):

          1. fast_mode: the classic ``set_input`` + ``run_frames`` pattern
             delivers no input under ``fast_mode=True``. ``run_frames`` skips
             its synthetic 1/60 s sleep in fast_mode, so zero wall-clock frames
             elapse for the free-running emulator to poll the override — the
             press is set and never read. Use the default ``fast_mode=False``
             for any input-driven test (fast_mode is for the preview pump, not
             assertions). Cost split_v_fight a full re-run.
          2. frame-stepping: an override set here does NOT latch while
             execution is parked under ``debug_break`` / ``frame_step``. The
             emulator is stopped, so nothing polls it; and the next
             ``frame_step`` re-latches its own button set on top. In parked
             mode pass the buttons to ``frame_step(n, **buttons)`` instead — a
             bare ``set_input`` there is silently ineffective. Cost rpg its
             frame-stepped dialog probe.
        """
        if not self._debugger_active:
            raise RuntimeError("Debugger not active. Call load_rom() first.")
        state = DebugControllerState()
        for btn_name, pressed in buttons.items():
            field = _BUTTON_MAP.get(btn_name.lower())
            if field is None:
                raise ValueError(
                    f"Unknown button '{btn_name}'. "
                    f"Valid: {', '.join(sorted(_BUTTON_MAP.keys()))}"
                )
            setattr(state, field, pressed)
        self._lib.SetInputOverrides(controller_index, state)

    # --- Deterministic frame-stepped input (S7 M1) ---
    #
    # The classic wall-clock pattern (set_input + run_frames over a
    # free-running emulator thread) couples test behavior to host
    # scheduling: input takes effect "whenever" relative to the frames
    # that elapse during the sleep. These methods park the emulator at a
    # frame boundary and advance it an EXACT number of frames per call,
    # with controller state latched per step — bit-identical traces
    # across runs.
    #
    # HAZARD — mixing paradigms on a shared runner: while execution is
    # parked, the emulator thread does NOT advance, so run_frames() is a
    # useless sleep and a wall-clock test sharing a module-scoped runner
    # will hang on its WRAM polls / observe a frozen machine. Any test
    # that calls debug_break()/frame_step() MUST call debug_resume()
    # (or use the frame_stepping() context manager) before handing the
    # runner to the next test.

    def _frame_step_lib(self) -> ctypes.CDLL:
        """Return the lib handle, verifying the frame-step exports exist."""
        if not self._debugger_active:
            raise RuntimeError("Debugger not active. Call load_rom() first.")
        lib = self._lib
        missing = [
            name for name in
            ("Step", "IsExecutionStopped", "ResumeExecution", "GetPpuState")
            if not hasattr(lib, name)
        ]
        if missing:
            raise RuntimeError(
                "This MesenCore build lacks the debug-stepping exports "
                f"required for deterministic frame stepping: {missing}. "
                "Rebuild Mesen2 from a recent source tree."
            )
        return lib

    def ppu_frame_count(self) -> int:
        """Read the emulator-side PPU frame counter (frames since power-on).

        Works whether execution is running or parked. This is the
        ground-truth progress indicator for frame stepping — it does not
        depend on the loaded ROM exposing a frame counter of its own.
        """
        lib = self._frame_step_lib()
        if self._ppu_state_buf is None:
            self._ppu_state_buf = (ctypes.c_uint8 * _PPU_STATE_BUF_SIZE)()
        lib.GetPpuState(self._ppu_state_buf, _CPU_TYPE_SNES)
        off = _PPU_STATE_FRAMECOUNT_OFFSET
        return int.from_bytes(bytes(self._ppu_state_buf[off:off + 4]), "little")

    def _ppu_scanline(self) -> int:
        """Current PPU scanline (offset 2 of the GetPpuState struct)."""
        lib = self._frame_step_lib()
        if self._ppu_state_buf is None:
            self._ppu_state_buf = (ctypes.c_uint8 * _PPU_STATE_BUF_SIZE)()
        lib.GetPpuState(self._ppu_state_buf, _CPU_TYPE_SNES)
        off = _PPU_STATE_SCANLINE_OFFSET
        return int.from_bytes(bytes(self._ppu_state_buf[off:off + 2]), "little")

    def _await_step(self, lib, done, reissue, deadline, what: str):
        """Generic wait loop for an issued Step request.

        done(cur)    -> True when the request's goal state is reached
                        (caller includes the IsExecutionStopped check)
        reissue()    -> re-arm the request (lost-wakeup recovery)
        Progress is tracked via the (frame, scanline) pair.

        Lost-wakeup race: a Step request issued in the short window
        while the emulation thread is *entering* its break sleep is
        silently dropped (observed empirically: ~20% of back-to-back
        single-frame steps wedge without recovery). Recovery re-issues
        the request — but ONLY after the emulator has been CONTINUOUSLY
        stopped with zero progress for 50 ms: re-arming an in-flight
        request resets the core's internal step countdown mid-run and
        overshoots (observed). A slow-but-live step reads stopped=False
        while running, so the continuous-stopped requirement makes the
        retry safe.
        """
        last_pos = (self.ppu_frame_count(), self._ppu_scanline())
        last_progress = time.time()
        stopped_since = None
        while time.time() < deadline:
            pos = (self.ppu_frame_count(), self._ppu_scanline())
            now = time.time()
            if pos != last_pos:
                last_pos = pos
                last_progress = now
                stopped_since = None
            stopped = lib.IsExecutionStopped()
            if not stopped:
                stopped_since = None
            elif stopped_since is None:
                stopped_since = now
            if stopped and done():
                # Let the break fully settle before the next Step can be
                # issued — closes the lost-wakeup window from this side
                # (1 ms measured sufficient: 0 losses across 900 steps).
                time.sleep(0.001)
                return
            if (stopped_since is not None
                    and now - stopped_since > 0.05
                    and now - last_progress > 0.05):
                reissue()
                last_progress = time.time()
                stopped_since = None
            time.sleep(0.0002)
        raise TimeoutError(
            f"{what} timed out (frame {self.ppu_frame_count()}, "
            f"scanline {self._ppu_scanline()})"
        )

    def _walk_one_frame(self, deadline):
        """Advance to the next canonical park point (scanline 224) and
        return the frame-counter delta (0 or 1).

        Implemented with SpecificScanline — empirically the reliable
        primitive (PpuFrame counting can MISS a tick on DMA-heavy frames
        and run an extra frame, observed deterministically; a run-to-
        scanline-224 request stops at the first scanline-224 event, no
        counting involved, and never tripped the boundary guard across
        thousands of parks). Delta 0 happens when the walk starts past
        the frame-count increment (scanline 225..261) — it then only
        normalizes the position to 224; the caller loops.
        """
        lib = self._frame_step_lib()
        fc0 = self.ppu_frame_count()
        sl0 = self._ppu_scanline()
        target = _CANONICAL_PARK_SCANLINE

        def issue():
            lib.Step(_CPU_TYPE_SNES, target, _STEP_TYPE_SPECIFIC_SCANLINE)

        def done():
            if sl0 == target:
                # started AT the canonical park: the walk must wrap a
                # full frame — completion requires the counter to have
                # moved, otherwise a lost request would read as done
                # (still parked at 224).
                return (self._ppu_scanline() == target
                        and self.ppu_frame_count() > fc0)
            # started elsewhere (e.g. right after a bulk PpuFrame break,
            # scanline 225..261, or a late break in the render region):
            # reaching 224 is completion; a lost request stays at sl0.
            return self._ppu_scanline() == target

        issue()
        self._await_step(lib, done, issue, deadline, "frame walk")
        delta = self.ppu_frame_count() - fc0
        if delta not in (0, 1):
            raise RuntimeError(
                f"frame walk advanced {delta} frames (expected 0 or 1)"
            )
        return delta

    def _step_to_target(self, target: int, timeout_s: float):
        """Advance execution until the PPU frame counter equals target,
        parking at the canonical scanline (224).

        Two phases:
          1. BULK — chunked PpuFrame steps up to target-1. Fast (one
             request covers many frames) but the PpuFrame countdown can
             deterministically MISS a tick on DMA-heavy frames and run
             one frame long (empirical; see _walk_one_frame). Chunks are
             capped at 16 frames and each chunk is recomputed from the
             live counter, so a +1 anomaly self-corrects into the next
             chunk; the phase cap of target-1 means a +1 on the final
             chunk still cannot pass target.
          2. EXACT — SpecificScanline walks, one verified frame at a
             time, until the counter equals target.
        """
        lib = self._frame_step_lib()
        deadline = time.time() + timeout_s

        # Phase 1: bulk
        while True:
            cur = self.ppu_frame_count()
            if cur >= target - 1:
                break
            chunk = min(16, (target - 1) - cur)
            goal = cur + chunk

            def issue(c=chunk):
                lib.Step(_CPU_TYPE_SNES, c, _STEP_TYPE_PPU_FRAME)

            def done(g=goal):
                return self.ppu_frame_count() >= g

            issue()
            self._await_step(lib, done, issue, deadline, f"bulk step({chunk})")
            if self.ppu_frame_count() > target:
                raise RuntimeError(
                    f"frame step overshot: at frame {self.ppu_frame_count()},"
                    f" wanted {target}"
                )

        # Phase 2: exact walk to target, ending at the canonical park
        while self.ppu_frame_count() < target:
            self._walk_one_frame(deadline)
        if self.ppu_frame_count() != target:
            raise RuntimeError(
                f"frame step overshot: at frame {self.ppu_frame_count()}, "
                f"wanted {target}"
            )

    def _park_at_canonical_scanline(self, timeout_s: float = 10.0,
                                     allow_frame_crossing: bool = False):
        """Normalize the park point to _CANONICAL_PARK_SCANLINE (224).

        Called after every PpuFrame advance (a PpuFrame break preserves
        the request point's in-frame offset and can stop anywhere from
        scanline 225 into the next render region — see the
        _CANONICAL_PARK_SCANLINE comment), and used directly by
        debug_break() to park a free-running emulator.

        With allow_frame_crossing=False (the post-step case) the run to
        scanline 224 must not pass another frame-count increment — the
        guard catches any accounting error. debug_break() passes True:
        parking a free-running emulator crosses boundaries arbitrarily.
        """
        lib = self._frame_step_lib()
        target = _CANONICAL_PARK_SCANLINE
        if self._ppu_scanline() == target and lib.IsExecutionStopped():
            # Double-check against a stale stopped-flag + scanline-224
            # transit read on a still-running emulator: anything running
            # moves off the scanline within ~64 us, so a stable re-read
            # 1 ms later means genuinely parked.
            time.sleep(0.001)
            if self._ppu_scanline() == target and lib.IsExecutionStopped():
                return
        deadline = time.time() + timeout_s
        fc_before = self.ppu_frame_count()

        def issue():
            lib.Step(_CPU_TYPE_SNES, target, _STEP_TYPE_SPECIFIC_SCANLINE)

        def done():
            return self._ppu_scanline() == target

        issue()
        self._await_step(lib, done, issue, deadline, "canonical park")
        if not allow_frame_crossing and self.ppu_frame_count() != fc_before:
            raise RuntimeError(
                "canonical park crossed a frame boundary "
                f"({fc_before} -> {self.ppu_frame_count()})"
            )

    def debug_break(self, timeout_s: float = 10.0):
        """Park execution at a frame boundary (deterministic stepping mode).

        Blocks until the emulator is stopped at the canonical park
        point. Idempotent — calling it while already parked is a no-op.

        Park-point semantics: execution parks at the canonical scanline
        (_CANONICAL_PARK_SCANLINE = 224 — end of the render period,
        just before the next VBlank/NMI). At the park:
          - WRAM is coherent: the frame's game update has completed
          - OAM/VRAM/CGRAM hold the PREVIOUS boundary's committed DMA
            (a constant one-frame presentation lag)
          - an input override latched here is polled at the very next
            boundary, so its WRAM effect is visible in the next
            frame_step's readback and its OAM effect one step later
        Every park on every run observes the same pipeline position —
        per-frame traces are bit-identical across runs.

        While parked, the emulation-speed throttle is lifted
        (MaximumSpeed flag) so frame steps run at host speed;
        debug_resume() restores normal pacing.

        HAZARD: while parked, run_frames() is a useless sleep (the
        emulator does not advance) and any wall-clock test sharing this
        runner will observe a frozen machine. Always debug_resume()
        before handing off — or use the frame_stepping() context manager.
        """
        lib = self._frame_step_lib()
        if self._frame_stepping and lib.IsExecutionStopped():
            return
        if hasattr(lib, "SetEmulationFlag"):
            lib.SetEmulationFlag(_EMU_FLAG_MAXIMUM_SPEED, True)
        # Park a (typically free-running) emulator at the canonical
        # scanline. No exact frame-count contract here — the wall clock
        # decides which frame we park in; determinism begins at the
        # park, where every subsequent frame_step is exact.
        self._park_at_canonical_scanline(timeout_s, allow_frame_crossing=True)
        self._frame_stepping = True

    def frame_step(self, n: int = 1, controller_index: int = 0,
                   timeout_s: Optional[float] = None, **buttons: bool):
        """Latch controller state, then advance EXACTLY n frames.

        The deterministic replacement for set_input + run_frames: the
        full controller state (every button named in **buttons pressed,
        every button NOT named released — same semantics as set_input)
        is latched before the step, and emulation advances exactly n
        PPU frames, blocking until execution is parked again.

        Auto-breaks: if the runner is not already parked (no prior
        debug_break()), it parks first.

        Input latch timing: an override latched at the canonical park
        (scanline 224) is polled at the very next frame boundary — its
        WRAM-side effect (game-state movement) is visible in the SAME
        step's readback, and its OAM-side effect one step later (the
        constant one-frame presentation lag of the park point). Both
        latencies are exact and identical on every run. Allow one settle
        step after changing buttons when a test asserts exact per-frame
        OAM deltas.

        Args:
            n: Number of frames to advance (exact, verified against the
                emulator's PPU frame counter).
            controller_index: Controller port (0 = P1, 1 = P2).
            timeout_s: Wall-clock cap; default scales with n.
            **buttons: Button states, same names as set_input.

        Example:
            runner.debug_break()
            runner.frame_step(1, right=True)    # latch Right, advance 1
            x = runner.read_bytes(MemoryType.SnesSpriteRam, 0, 1)[0]
            runner.debug_resume()               # back to free-running
        """
        if n < 1:
            raise ValueError(f"frame_step needs n >= 1, got {n}")
        if not self._frame_stepping:
            self.debug_break()
        self.set_input(controller_index, **buttons)
        if timeout_s is None:
            # ~6.6 ms/frame measured at host speed; 10x margin + base.
            timeout_s = 10.0 + n * 0.07
        self._step_to_target(self.ppu_frame_count() + n, timeout_s)
        self._park_at_canonical_scanline(timeout_s)

    def debug_resume(self, clear_input: bool = True, timeout_s: float = 10.0):
        """Return the emulator to free-running (wall-clock) mode.

        The mandatory hand-off step after debug_break()/frame_step():
        restores the normal emulation-speed throttle, clears the input
        overrides latched by frame_step (unless clear_input=False), and
        resumes the emulation thread, blocking until it demonstrably
        advances again. Idempotent — safe to call when not parked.

        Tests sharing a module-scoped runner MUST call this before
        finishing if they ever parked execution; otherwise the next
        wall-clock test hangs or flakes on a frozen emulator.
        """
        if not self._frame_stepping:
            return
        lib = self._frame_step_lib()
        if clear_input:
            self.set_input(0)
        if hasattr(lib, "SetEmulationFlag"):
            lib.SetEmulationFlag(_EMU_FLAG_MAXIMUM_SPEED, False)
        # ResumeExecution is subject to the same lost-wakeup race as
        # Step (observed empirically) — verify progress and retry.
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            lib.ResumeExecution()
            start = self.ppu_frame_count()
            settle = time.time() + 0.1
            while time.time() < settle:
                if not lib.IsExecutionStopped() or self.ppu_frame_count() != start:
                    self._frame_stepping = False
                    return
                time.sleep(0.001)
        raise TimeoutError("debug_resume: emulator did not resume free-running")

    @contextlib.contextmanager
    def frame_stepping(self):
        """Context manager: debug_break() on enter, debug_resume() on exit.

        The exception-safe way to use deterministic stepping on a shared
        runner — the resume runs even if an assertion fails mid-block:

            with runner.frame_stepping():
                runner.frame_step(1, right=True)
                ...assertions...
            # free-running again here, even on test failure
        """
        self.debug_break()
        try:
            yield self
        finally:
            self.debug_resume()

    def run_frames(self, n: int):
        """
        Let emulation run for approximately n frames (n/60 seconds).

        Args:
            n: Number of frames (at 60fps).

        When the runner is in ``fast_mode`` (opt-in; default off), the
        synthetic ``time.sleep(n / 60.0)`` is skipped entirely. The
        Mesen2 emulator advances on its own internal thread at full
        host speed, so the sleep is a courtesy delay that adds pure
        latency to round-trip preview pumps. The screenshot-pump
        throughput sprint measured this single change as ~16.7 ms per
        round-trip on a 512KB streaming test ROM — the largest single
        bottleneck after the screenshot poll. Test paths that depend
        on 60-Hz pacing (input-injection delays, timing-sensitive
        assertions) leave ``fast_mode=False`` (the default) and keep
        the existing semantics.

        HAZARD: if execution is parked in frame-stepping mode (see
        ``debug_break``/``frame_step``), this method is a useless sleep —
        the emulator does not advance while stopped. A test that parked
        execution must ``debug_resume()`` before any wall-clock test
        (or any code calling this method) runs on the shared runner.
        """
        if self._fast_mode:
            return
        time.sleep(n / 60.0)

    def await_streaming_idle(self, timeout_frames: int = 60) -> bool:
        """Spin frames until the BG1 streaming engine's NMI queue drains.

        Why this helper exists
        ----------------------
        The Phase 17 streaming engine
        (engine/streaming_engine.asm) is a two-stage pipeline:

          1. Main thread: streaming_compute_next_col advances
             STREAM_LAST_COL when the camera moves and queues a column
             DMA by writing to STREAM_PENDING_TBL + bumping
             STREAM_PENDING (the queue count).
          2. NMI: the VBlank handler reads STREAM_PENDING, drains the
             queued column DMAs to BG1 VRAM, and clears STREAM_PENDING
             back to 0 once all slots in the queue are flushed.

        A test that reads VRAM (or SHADOW_BG1_TILEMAP) BETWEEN those
        two stages observes a half-applied state: STREAM_LAST_COL claims
        the col is "streamed" but VRAM and the SHADOW mirror still hold
        stale data from the previous wrap. The mismatch is silent — no
        error, just stale bytes.

        Sprint D-2 (test_phase17_sprintD2_streaming_correctness.py) hit
        this footgun. The original poll loop was inlined in that test
        with the comment ``"this is NOT masking a streaming bug — it's
        matching the reading-side cadence to the engine's two-stage
        queue→drain protocol."`` Future streaming-aware tests would
        rediscover the issue without this helper.

        Args:
            timeout_frames: Maximum number of frames to wait (default 60
                = 1 second at 60 Hz). The NMI usually drains a single
                queued col in 1 frame; a queue of 4 slots drains in 4.
                60 is a safety ceiling — any longer suggests something
                is genuinely wrong (NMI not running, streaming wedged).

        Returns:
            True if STREAM_PENDING reached 0 within `timeout_frames`,
            False if the timeout expired with the queue still non-zero.

        Notes:
            - Reads STREAM_PENDING at WRAM $062A (engine_state.inc).
            - Calls run_frames(1) per loop iteration (matches the
              60 Hz NMI cadence).
            - Does NOT change controller input — the caller is
              responsible for setting/clearing input as needed. A
              common pattern is to release input before this call so
              the camera stops moving and STREAM_LAST_COL stops
              advancing while we wait for the NMI to catch up.
        """
        STREAM_PENDING_ADDR = 0x062A   # 1 byte; from engine_state.inc
        for _ in range(timeout_frames):
            pending = self.read_bytes(MemoryType.SnesWorkRam, STREAM_PENDING_ADDR, 1)[0]
            if pending == 0:
                return True
            self.run_frames(1)
        # One last check after the loop in case the final frame drained.
        pending = self.read_bytes(MemoryType.SnesWorkRam, STREAM_PENDING_ADDR, 1)[0]
        return pending == 0

    # --- Convenience methods ---

    def run_test(
        self,
        rom_path: str,
        address: int = 0,
        mem_type: MemoryType = MemoryType.SnesWorkRam,
        count: int = 8,
        run_seconds: float = 3.0,
    ) -> bytes:
        """
        All-in-one: load ROM, run, read bytes, stop.

        Args:
            rom_path: Path to .sfc ROM file.
            address: Byte offset within the memory region.
            mem_type: Which memory region to read.
            count: Number of bytes to read.
            run_seconds: How long to let emulation run.

        Returns:
            Bytes read from the specified address.
        """
        self.load_rom(rom_path, run_seconds=run_seconds)
        result = self.read_bytes(mem_type, address, count)
        self.stop()
        return result

    def read_wram(self, rom_path: str, address: int, count: int = 8) -> bytes:
        """Convenience: run test and read bytes from WRAM."""
        return self.run_test(rom_path, address, MemoryType.SnesWorkRam, count)

    def read_sram(self, rom_path: str, address: int = 0, count: int = 8) -> bytes:
        """Convenience: run test and read bytes from SRAM."""
        return self.run_test(rom_path, address, MemoryType.SnesSaveRam, count)

    def read_vram(self, rom_path: str, address: int = 0, count: int = 8) -> bytes:
        """Convenience: run test and read bytes from VRAM."""
        return self.run_test(rom_path, address, MemoryType.SnesVideoRam, count)


class RetroArchRunner:
    """Fallback: Runs ROMs via RetroArch + bsnes-mercury-accuracy, reads SRAM."""

    def __init__(
        self,
        retroarch_path: str = _DEFAULT_RETROARCH,
        core_path: str = _DEFAULT_BSNES_CORE,
    ):
        self.retroarch = retroarch_path
        self.core = core_path

    def run_and_read_sram(
        self,
        rom_path: str,
        timeout_seconds: int = 10,
    ) -> Optional[bytes]:
        """
        Run a ROM in RetroArch, wait for timeout, read the .srm file.

        The ROM should write test results to SRAM and then STP.

        Returns:
            SRAM contents as bytes, or None if no .srm was created.
        """
        abs_path = os.path.abspath(rom_path)
        rom_name = Path(abs_path).stem

        with tempfile.TemporaryDirectory() as tmpdir:
            saves_dir = os.path.join(tmpdir, "saves")
            os.makedirs(saves_dir)

            # Ensure D-Bus is available (RetroArch crashes without it)
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":99")

            # Start D-Bus if needed
            try:
                dbus_output = subprocess.check_output(
                    ["dbus-launch", "--sh-syntax"],
                    env=env, timeout=5
                ).decode()
                for line in dbus_output.strip().split("\n"):
                    if "=" in line:
                        key, _, val = line.partition("=")
                        val = val.rstrip(";").strip("'\"")
                        env[key] = val
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # Write minimal RetroArch config
            cfg_path = os.path.join(tmpdir, "retroarch.cfg")
            with open(cfg_path, "w") as f:
                f.write(f'savefile_directory = "{saves_dir}"\n')
                f.write('video_driver = "sdl2"\n')
                f.write('audio_driver = "null"\n')
                f.write('input_driver = "null"\n')
                f.write('menu_driver = "null"\n')
                f.write('video_vsync = "false"\n')

            cmd = [
                self.retroarch,
                "-L", self.core,
                abs_path,
                "--config", cfg_path,
                "--verbose",
            ]

            try:
                subprocess.run(
                    cmd,
                    env=env,
                    timeout=timeout_seconds,
                    capture_output=True,
                )
            except subprocess.TimeoutExpired:
                pass  # Expected — ROM halts but RetroArch doesn't exit

            # Look for .srm file
            srm_path = os.path.join(saves_dir, f"{rom_name}.srm")
            # RetroArch may put it in a subdirectory
            if not os.path.exists(srm_path):
                for root, _, files in os.walk(saves_dir):
                    for f in files:
                        if f.endswith(".srm"):
                            srm_path = os.path.join(root, f)
                            break

            if os.path.exists(srm_path):
                with open(srm_path, "rb") as f:
                    return f.read()

            return None


class Assembler:
    """Assembles 65816 source files into SNES ROMs using ca65/ld65.

    Supports three linker configurations:
      - lorom.cfg:           32KB single-bank LoROM (default, Phase 1/2A tests)
      - lorom_multibank.cfg: 128KB 4-bank LoROM (larger test ROMs)
      - hirom.cfg:           512KB 8-bank HiROM (production ROMs, convergence tests)

    Usage:
        asm = Assembler()                                  # 32KB LoROM (default)
        asm = Assembler(rom_type="lorom_multibank")        # 128KB LoROM
        asm = Assembler(rom_type="hirom")                  # 512KB HiROM
        asm = Assembler(linker_cfg="/custom/path.cfg",
                        expected_rom_size=65536)           # fully custom
    """

    # Expected ROM sizes for each built-in config
    ROM_SIZES = {
        "lorom":           32768,     # 32KB
        "lorom_multibank": 131072,    # 128KB (4 banks x 32KB)
        "hirom":           524288,    # 512KB (8 banks x 64KB)
    }

    def __init__(
        self,
        template_dir: Optional[str] = None,
        linker_cfg: Optional[str] = None,
        rom_type: Optional[str] = None,
        expected_rom_size: Optional[int] = None,
    ):
        """Initialize the Assembler.

        Args:
            template_dir: Path to ROM template directory. Auto-detected if None.
            linker_cfg: Explicit path to linker config. Overrides rom_type.
            rom_type: One of "lorom", "lorom_multibank", "hirom". Default "lorom".
            expected_rom_size: Override the expected output size (bytes).
        """
        repo_root = Path(__file__).resolve().parent.parent.parent
        if template_dir is None:
            template_dir = str(repo_root / "infrastructure" / "rom_template")

        self.template_dir = template_dir

        # Resolve linker config
        if linker_cfg is not None:
            self.linker_cfg = linker_cfg
            self.rom_type = "custom"
        else:
            if rom_type is None:
                rom_type = "lorom"
            self.rom_type = rom_type
            cfg_name = f"{rom_type}.cfg"
            self.linker_cfg = os.path.join(template_dir, cfg_name)
            if not os.path.exists(self.linker_cfg):
                raise FileNotFoundError(
                    f"Linker config not found: {self.linker_cfg}\n"
                    f"Valid rom_type values: {list(self.ROM_SIZES.keys())}"
                )

        # Determine expected ROM size
        if expected_rom_size is not None:
            self.expected_rom_size = expected_rom_size
        elif self.rom_type in self.ROM_SIZES:
            self.expected_rom_size = self.ROM_SIZES[self.rom_type]
        else:
            self.expected_rom_size = None  # Skip size check for custom configs

        # Verify tools exist
        for tool in ["ca65", "ld65"]:
            if not shutil.which(tool):
                if platform.system() == "Windows":
                    hint = f"{tool} not found. Install cc65 and add its bin/ to PATH."
                else:
                    hint = f"{tool} not found. Install cc65: apt-get install cc65"
                raise FileNotFoundError(hint)

    def assemble(
        self,
        source_path: str,
        output_path: Optional[str] = None,
        include_dirs: Optional[list] = None,
    ) -> str:
        """
        Assemble a .asm file into a .sfc ROM.

        Args:
            source_path: Path to the .asm source file.
            output_path: Path for the output .sfc file. Defaults to same name.
            include_dirs: Additional include directories for ca65 -I flags.

        Returns:
            Path to the assembled .sfc file.
        """
        source = Path(source_path).resolve()
        if output_path is None:
            output_path = str(source.with_suffix(".sfc"))

        obj_path = str(source.with_suffix(".o"))

        # Build include path list
        includes = ["-I", self.template_dir]
        if include_dirs:
            for d in include_dirs:
                includes.extend(["-I", d])

        # Assemble: .asm -> .o
        result = subprocess.run(
            ["ca65", "-o", obj_path, str(source)] + includes,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ca65 assembly failed:\n{result.stderr}\n{result.stdout}"
            )

        # Link: .o -> .sfc
        result = subprocess.run(
            ["ld65", "-o", output_path, "-C", self.linker_cfg, obj_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ld65 linking failed:\n{result.stderr}\n{result.stdout}"
            )

        # Verify output size matches expected ROM size for the config
        if self.expected_rom_size is not None:
            size = os.path.getsize(output_path)
            if size != self.expected_rom_size:
                raise RuntimeError(
                    f"ROM size {size} bytes, expected {self.expected_rom_size} "
                    f"({self.expected_rom_size // 1024}KB {self.rom_type})"
                )

        # Clean up .o file
        if os.path.exists(obj_path):
            os.remove(obj_path)

        return output_path

    def assemble_string(self, source_code: str, output_path: str) -> str:
        """
        Assemble source code from a string (writes to temp file first).

        Args:
            source_code: 65816 assembly source as a string.
            output_path: Path for the output .sfc ROM.

        Returns:
            Path to the assembled .sfc file.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".asm", delete=False
        ) as f:
            f.write(source_code)
            tmp_path = f.name

        try:
            return self.assemble(tmp_path, output_path)
        finally:
            os.unlink(tmp_path)
