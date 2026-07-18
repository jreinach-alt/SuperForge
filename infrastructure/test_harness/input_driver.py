"""Closed-loop input drivers for MesenRunner.

Open-loop input — "hold Left for 30 frames and hope for the right heading" —
is the dominant fragility in this repo's validation. The frame->state transfer
is a magic number baked into test comments (e.g. "Measured: first lap at ~220
frames of B+Left") that silently drifts whenever physics or camera tuning
changes. Every screenshot taken "at a heading" is then taken at *whatever*
heading those frames happened to produce.

These helpers drive inputs CLOSED-LOOP instead: advance deterministically with
``frame_step`` while reading game state each frame, and stop when the state
reaches a target. The result is reproducible (deterministic frame-stepping) and
self-validating (if the input has no effect, the drive times out instead of
silently capturing a wrong state — see ``DriveTimeout``).

Typical use, inside a ``frame_stepping()`` block so the whole sequence is
frame-exact:

    from infrastructure.test_harness.input_driver import drive_to_u8
    with runner.frame_stepping():
        frames = drive_to_u8(runner, 0x3A, target=64,
                             hold={"b": True, "left": True}, tol=2, wrap=256)
        runner.take_screenshot(path)        # captured at a KNOWN heading (~64)

The core is ``drive_until(predicate)``; ``drive_to_u8`` / ``drive_to_u16`` are
thin state-target wrappers over it. Game-specific helpers (steer_to_angle,
walk_to_x, jump_to_apex) belong in the template's own module as one-liners over
these primitives — the closed loop lives here, the addresses live there.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from infrastructure.test_harness.mesen_runner import MemoryType


class DriveTimeout(RuntimeError):
    """A closed-loop drive did not reach its target within ``max_frames``.

    This is a *useful* failure, not just an error: a drive that can't reach its
    target means the programmed input had no (or insufficient) effect on the
    state — e.g. a frozen-steering ROM never reaches the requested heading. Tests
    can assert this is raised to prove an input *should* have moved state and
    didn't.
    """


def drive_until(
    runner,
    predicate: Callable[[], bool],
    *,
    hold: Optional[Mapping[str, bool]] = None,
    max_frames: int = 600,
    port: int = 0,
    what: str = "condition",
) -> int:
    """Advance one frame at a time holding ``hold``, until ``predicate()`` is true.

    Returns the number of frames stepped (0 if already satisfied). Raises
    :class:`DriveTimeout` if the predicate is not satisfied within
    ``max_frames``. Deterministic: built on ``frame_step``, so the returned
    frame count and the resulting state are reproducible run-to-run.

    Call inside a ``runner.frame_stepping()`` block for a fully frame-exact
    sequence; ``frame_step`` will auto-park if you don't, but mixing parked and
    free-running phases is the caller's responsibility.

    Args:
        runner: a live ``MesenRunner``.
        predicate: zero-arg callable returning True when the target is reached.
            It reads whatever state it likes (WRAM/OAM/VRAM) via ``runner``.
        hold: buttons to hold every frame (same names as ``set_input``); buttons
            not named are released each frame.
        max_frames: cap before giving up (raises DriveTimeout).
        port: controller port.
        what: short label used in the timeout message.
    """
    btn = dict(hold or {})
    if predicate():
        return 0
    for i in range(1, max_frames + 1):
        runner.frame_step(1, controller_index=port, **btn)
        if predicate():
            return i
    raise DriveTimeout(
        f"{what}: target not reached after {max_frames} frames "
        f"(hold={btn or 'none'})"
    )


def _mod_dist(a: int, b: int, mod: int) -> int:
    """Shortest distance between two values on a circular range of size ``mod``."""
    d = abs(a - b) % mod
    return min(d, mod - d)


def drive_to_u8(
    runner,
    addr: int,
    target: int,
    *,
    hold: Mapping[str, bool],
    mem: MemoryType = MemoryType.SnesWorkRam,
    tol: int = 1,
    wrap: Optional[int] = None,
    max_frames: int = 600,
    port: int = 0,
) -> int:
    """Drive a 1-byte value at ``addr`` to ``target`` (within ``tol``).

    ``wrap`` enables modular ("circular") distance — pass ``wrap=256`` for a
    0-255 heading so the driver stops at the shortest-arc arrival regardless of
    which direction is held. Without ``wrap`` it uses linear distance.

    The per-frame state delta must be smaller than ``2*tol`` or the value can
    step over the tolerance window without registering; widen ``tol`` for
    fast-moving state.
    """
    def reached() -> bool:
        v = runner.read_bytes(mem, addr, 1)[0]
        if wrap is not None:
            return _mod_dist(v, target, wrap) <= tol
        return abs(v - target) <= tol

    return drive_until(
        runner, reached, hold=hold, max_frames=max_frames, port=port,
        what=f"u8@{addr:#x} -> {target}",
    )


def drive_to_u16(
    runner,
    addr: int,
    target: int,
    *,
    hold: Mapping[str, bool],
    mem: MemoryType = MemoryType.SnesWorkRam,
    tol: int = 1,
    max_frames: int = 600,
    port: int = 0,
) -> int:
    """Drive a 16-bit little-endian value at ``addr`` to ``target`` (within ``tol``).

    For monotonic targets like a world coordinate ("walk right until x >= 400");
    pass ``tol`` large enough to absorb the per-frame velocity.
    """
    def reached() -> bool:
        return abs(runner.read_u16(mem, addr) - target) <= tol

    return drive_until(
        runner, reached, hold=hold, max_frames=max_frames, port=port,
        what=f"u16@{addr:#x} -> {target}",
    )
