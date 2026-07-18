"""Fault injection for the oracle loop's FAIL-side proof (spec B.6, Brick 5).

The proof plan requires every re-expressed gate to PASS on the good ROM AND
FAIL on a *genuinely faulted* ROM — not on a faulted expectation (audit-1
finding MED-A). This module patches a single byte (two for the racer, whose
steering has a +dir and a -dir update site) at a UNIQUE byte-signature anchor in
a built ROM, flipping one opcode/operand so the target hardware region misbehaves
on a real Mesen run.

Faults are TEST-ONLY — they live here, not in ``oracle.py`` (the harness runtime
must never carry the ability to corrupt a ROM). Each probe is anchored by a hex
signature verified to occur exactly once in its target ROM; ``fault_inject``
asserts both the single-match invariant AND that the byte at the patch offset
still equals the documented original before patching, so a rebuild that shifts or
mutates the site fails loudly instead of silently no-op'ing.

LoROM file offset = ((bank << 15) | (addr & 0x7FFF)) with no copier header — but
the probes are signature-anchored, so this module never computes an offset from a
bank/addr; it locates each site by its byte pattern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Patch:
    signature: bytes   # unique byte pattern anchoring the site
    offset: int        # byte to patch, relative to the signature start
    orig: int          # expected current value at signature+offset
    new: int           # replacement value


@dataclass(frozen=True)
class _Probe:
    rom: str           # target ROM basename (informational)
    patches: tuple[_Patch, ...]
    region: str        # documented faulted hardware region (for the proof)
    note: str


# Signature-anchored probe registry (VERIFIED GROUND TRUTH, spec B.6 / Brick 5
# fault-injection investigation). Each signature is a single match in its ROM.
PROBES: dict[str, _Probe] = {
    "sprite_game_break_relocate": _Probe(
        rom="sprite_game",
        patches=(_Patch(bytes.fromhex("E63AA53C1A"), 4, 0x1A, 0xEA),),
        region="oam",
        note="dot never relocates; OAM slot 1 stays x=200 (not 60)",
    ),
    "breaker_corrupt_brick_palette": _Probe(
        rom="breaker",
        patches=(_Patch(bytes.fromhex("A91F8D2221"), 1, 0x1F, 0xF0),),
        region="cgram",
        note="CGRAM[2] = 0x00F0 (not 0x001F)",
    ),
    "breaker_skip_final_brick": _Probe(
        rom="breaker",
        patches=(_Patch(bytes.fromhex("A9B4008540"), 1, 0xB4, 0xB5),),
        region="vram",
        note=("BRICKS seed 181 not 180; bot clears all VRAM bricks but the "
              "BRICKS mirror never hits 0, STATE never reaches win, "
              "'YOU WIN!' never renders"),
    ),
    "racer_freeze_steer": _Probe(
        rom="racer",
        patches=(
            _Patch(bytes.fromhex("A53A1A29FF00"), 2, 0x1A, 0xEA),  # +dir update
            _Patch(bytes.fromhex("A53A3A29FF00"), 2, 0x3A, 0xEA),  # -dir update
        ),
        region="screenshot",
        note="R_ANGLE frozen at 0 both directions; the Mode-7 floor never rotates",
    ),
    "save_flip_byte": _Probe(
        rom="save_test",
        patches=(_Patch(bytes.fromhex("A9038532"), 1, 0x03, 0x04),),
        region="sram",
        note="every saved payload byte +1: SRAM[0x08:8] = [4,11,18,…] not [3,10,17,…]",
    ),
}


class FaultError(ValueError):
    """A probe's signature is missing or non-unique, or the byte at its patch
    offset does not match the documented original (rebuild drift)."""


def _apply_patch(data: bytearray, probe_name: str, patch: _Patch) -> int:
    sig = patch.signature
    first = data.find(sig)
    if first < 0:
        raise FaultError(
            f"probe '{probe_name}': signature {sig.hex()} not found "
            "(ROM rebuilt / drifted?)"
        )
    if data.find(sig, first + 1) >= 0:
        raise FaultError(
            f"probe '{probe_name}': signature {sig.hex()} is NOT unique "
            "(multiple matches — anchor no longer single-site)"
        )
    pos = first + patch.offset
    cur = data[pos]
    if cur != patch.orig:
        raise FaultError(
            f"probe '{probe_name}': byte at signature+{patch.offset} is "
            f"{cur:#04x}, expected {patch.orig:#04x} (rebuild drift)"
        )
    data[pos] = patch.new
    return pos


def fault_inject(rom_bytes: bytes, probe: str) -> bytes:
    """Return a copy of ``rom_bytes`` with the named ``probe``'s fault applied.

    Each probe applies one byte patch (two for ``racer_freeze_steer``), located
    by a unique signature. Raises ``FaultError`` on a missing/duplicate signature
    or a byte that no longer matches the documented original."""
    if probe not in PROBES:
        raise FaultError(
            f"unknown probe '{probe}'. Known: {', '.join(sorted(PROBES))}")
    p = PROBES[probe]
    data = bytearray(rom_bytes)
    for patch in p.patches:
        _apply_patch(data, probe, patch)
    return bytes(data)


def probe_region(probe: str) -> str:
    """The documented hardware region a probe's fault corrupts — the region the
    FAIL-side proof expects the failing assert to name."""
    if probe not in PROBES:
        raise FaultError(f"unknown probe '{probe}'")
    return PROBES[probe].region
