"""superforge allocator — input schemas + validated loaders.

Loads and validates the allocator's four input kinds:

  substrate.toml            the hardware budget + constraints (deliverable 1)
  <feature>/feature.toml    an engine feature's resource claims + init contract
  <game>/state.toml         user game state, global and scene scope
  <game>/game.toml          the game manifest: globals, scenes, transition graph

Validation is strict: unknown keys are rejected (a typo'd key silently ignored
is how ad-hoc collisions start), required keys and types are enforced, and every
error is a legible SchemaError naming the file, the table, and the problem.

Address-space conventions carried by the claims:
  vram   claims are in WORDS (VMADD space);  dp/wram/oam/rom claims in BYTES;
  cgram  claims in WORDS (one word = one color).

User-state type strings: "u8" | "u16" | "u24" | "u32" | "<Custom>" (size from
[types]) with optional "[N]" array suffix and optional "@dp" placement class
(default placement is wram). Example: "EnemySlot[8]", "u16@dp".

Scene-scoped user state: a flat [scene] table applies to the manifest's single
scene (error if the game has more than one); [scene.<id>] sub-tables target
scenes by id in multi-scene games.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class SchemaError(ValueError):
    """A declaration failed validation. Message is the legible diagnostic."""


# --------------------------------------------------------------------------
# strict-table helper
# --------------------------------------------------------------------------

def _table(d: dict, where: str, required: dict, optional: dict) -> dict:
    """Validate dict *d* against required/optional {key: type-or-tuple} specs.

    Returns d. Rejects unknown keys. `where` names the file+table for errors.
    """
    for key in d:
        if key not in required and key not in optional:
            raise SchemaError(
                f"{where}: unknown key '{key}' "
                f"(allowed: {sorted([*required, *optional])})")
    for key, typ in required.items():
        if key not in d:
            raise SchemaError(f"{where}: missing required key '{key}'")
        if not isinstance(d[key], typ):
            raise SchemaError(
                f"{where}: key '{key}' must be {typ}, got {type(d[key]).__name__}")
    for key, typ in optional.items():
        if key in d and not isinstance(d[key], typ):
            raise SchemaError(
                f"{where}: key '{key}' must be {typ}, got {type(d[key]).__name__}")
    return d


def _name_ok(name: str, where: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise SchemaError(
            f"{where}: name '{name}' must be lower_snake_case ([a-z][a-z0-9_]*)")
    return name


# --------------------------------------------------------------------------
# substrate
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Substrate:
    """Parsed substrate.toml. Raw dict kept for pass-through of documented
    constraint flags; hot fields are promoted to attributes."""
    raw: dict
    vram_words: int
    vram_addr_mask: int
    tilemap_align_words: int
    chr_align_words: int
    obj_chr_align_words: int
    mode7_region_words: int
    mode7_base_word: int
    mode7_obj_chr_floor_word: int
    dp_bytes: int
    wram_bytes: int
    wram_bank_bytes: int
    wram_reserved_low: int
    cgram_words: int
    oam_bytes: int
    oam_sprites: int
    channel_count: int
    dma_mc_per_byte: int
    mc_per_frame: int
    visible_lines: int
    vblank_usable_bytes: int | None     # None until measured (deliverable 6)
    vblank_start_pin: int
    cpu_worst_frame_mc: int | None      # None until measured (master clock)
    rom_bank_bytes: int
    rom_window_bytes: int
    spc_bytes: int                      # audio-CPU RAM; occupancy is exclusive
    sram_bytes: int # battery-backed cart RAM ceiling
    sram_bank: int                      # canonical access bank ($70 — every LoROM
                                        # mapper variant agrees on $70:0000-$7FFF)
    rom_code_windows: int = 1           # windows reserved for linker CODE/RODATA
    vblank_arm_cost_bytes: int | None = None # None until measured (the multi-queue probe)

    @property
    def vblank_budget(self) -> int:
        """The VBlank DMA budget to allocate against: the measured number once
        deliverable 6 has written it, else the documented start pin."""
        return (self.vblank_usable_bytes
                if self.vblank_usable_bytes is not None else self.vblank_start_pin)

    @property
    def vblank_arm_cost(self) -> int:
        """Per-additional-transfer VBlank overhead in byte-equivalents (F9
        multi-queue refinement). 0 until the probe pins it — the
        budget check degrades to the single-transfer model."""
        return (self.vblank_arm_cost_bytes
                if self.vblank_arm_cost_bytes is not None else 0)


def _measure_or_int(v, where: str) -> int | None:
    if v == "MEASURE":
        return None
    if isinstance(v, int):
        return v
    raise SchemaError(f"{where}: expected an integer or 'MEASURE', got {v!r}")


def load_substrate(path: str | Path) -> Substrate:
    path = Path(path)
    with open(path, "rb") as f:
        d = tomllib.load(f)
    try:
        vram, m7 = d["vram"], d["vram"]["mode7"]
        frame = d["frame"]["ntsc"]
        return Substrate(
            raw=d,
            vram_words=vram["words"],
            vram_addr_mask=vram["addr_mask"],
            tilemap_align_words=vram["tilemap_align_words"],
            chr_align_words=vram["chr_align_words"],
            obj_chr_align_words=vram["obj_chr_align_words"],
            mode7_region_words=m7["region_words"],
            mode7_base_word=m7["base_word"],
            mode7_obj_chr_floor_word=m7["displaces_obj_chr_to_word"],
            dp_bytes=d["dp"]["bytes"],
            wram_bytes=d["wram"]["bytes"],
            wram_bank_bytes=d["wram"]["bank_bytes"],
            wram_reserved_low=d["wram"]["reserved_low_bytes"],
            cgram_words=d["cgram"]["words"],
            oam_bytes=d["oam"]["bytes"],
            oam_sprites=d["oam"]["sprites"],
            channel_count=d["channels"]["count"],
            dma_mc_per_byte=d["dma"]["cost_mc_per_byte"],
            mc_per_frame=frame["mc_per_frame"],
            visible_lines=frame["visible_lines"],
            vblank_usable_bytes=_measure_or_int(
                frame["vblank_usable_bytes"], f"{path}: frame.ntsc.vblank_usable_bytes"),
            vblank_start_pin=frame["vblank_usable_start_pin"],
            cpu_worst_frame_mc=_measure_or_int(
                frame["cpu_worst_frame_mc"], f"{path}: frame.ntsc.cpu_worst_frame_mc"),
            rom_bank_bytes=d["rom"]["bank_bytes"],
            rom_window_bytes=d["rom"]["lorom_window_bytes"],
            spc_bytes=d["spc"]["bytes"],
            sram_bytes=d["sram"]["bytes"],
            sram_bank=d["sram"]["bank"],
            rom_code_windows=d["rom"].get("code_windows", 1),
            vblank_arm_cost_bytes=_measure_or_int(
                d.get("measured", {}).get("vblank", {})
                 .get("arm_cost_bytes", "MEASURE"),
                f"{path}: measured.vblank.arm_cost_bytes"),
        )
    except KeyError as e:
        raise SchemaError(f"{path}: missing substrate key {e}") from None


# --------------------------------------------------------------------------
# feature declarations
# --------------------------------------------------------------------------

VRAM_KINDS = ("tilemap", "chr", "mode7", "raw")

# Register names a claim may name, each mapped to the PHYSICAL resource it
# owns: (B-bus port address, sub-resource mask).
#
# Why a footprint and not a bare name set. Contention used to be decided by
# NAME EQUALITY, which got two things wrong at once:
#
#   1. An unrecognised name silently opted a claim out of every exclusivity
# check it should have joined: a claim declaring
#      "VMDATA_L" collided with nothing. Validating against the table's keys
#      turns that into a build error (a typo is not a resource).
#   2. Name equality cannot see that COLDATA_R and COLDATA are different
#      names for intersecting silicon, so a whole-port claim and a plane
# claim composed silently. That was the sub-register hole.
#
# The mask closes (2). Ordinary registers own their whole port (WHOLE). The
# COLDATA planes own one plane-select bit each — the REAL hardware bits
# ($2132 bit5=R, bit6=G, bit7=B), so the table documents itself. Two claims
# contend iff they name the same port AND their masks intersect: the three
# rgb_gradient planes compose (disjoint bits), while COLDATA vs COLDATA_R
# refuses (WHOLE intersects the R bit).
#
# Sub-registering a port is a declaration that the port's writes are
# partitioned by DATA rather than by address. Only add a name here when that
# partition is real in hardware, or the mask lies.
#
# THE TEST FOR WHETHER A PARTITION IS LEGITIMATE: it must be expressible in a
# SINGLE BLIND WRITE. "Real in hardware" was the right instinct and no test at
# all, so it could not settle the cases that actually come up. A writer owns a
# sub-resource only if it can set its own bits without knowing anyone else's.
#
#   COLDATA qualifies. Its plane-select bits live in the DATA ($2132 bit5=R,
#   bit6=G, bit7=B), so each write targets exactly its own plane and needs no
#   knowledge of the other two.
#
#   TM / TS / TMW / TSW / CGADSUB / NMITIMEN do NOT, however layer-shaped
#   their bits look. They are WRITE-ONLY, so read-modify-write is impossible
#   and every writer must supply the whole byte. Verified in Mesen2: $212C
#   appears only in SnesPpu::Write (SnesPpu.cpp:2175) and the PPU's Read
#   switch (:1710) starts at $2134; $4200 appears only in the
#   InternalRegisters write path (InternalRegisters.cpp:299) and its Read
#   switch starts at $4210. A per-layer TM_BG3 or a per-consumer
#   NMITIMEN_IRQ would be a mask that lies.
#
# THE B-BUS INVARIANT, and why $42xx names are fenced off. This table does two
# unrelated jobs: contention checking, and BBAD DERIVATION (HdmaClaim.bbad
# returns port & 0xFF; bbad_span reforms 0x2100 | bbad). Those only agree for
# ports the B bus can actually reach, i.e. $2100-$21FF. A $42xx name on an
# hdma/dma_init claim would silently emit a BBAD aliasing a REAL, different
# register: $4200 -> $2100 INIDISP, $4202 -> $2102 OAMADDL, $4203 -> $2103
# OAMADDH, $4216 -> $2116 VMADDH. So the CPU-bus names below are legal on
# claims.reg ONLY, enforced by _reject_non_b_bus on the hdma/dma_init paths.
WHOLE = 0xFF

# The B bus is what a DMA's BBAD byte can address. A name outside it owns a
# real resource but cannot be a transfer target.
B_BUS_LO, B_BUS_HI = 0x2100, 0x21FF

REGISTER_FOOTPRINT: dict[str, tuple[int, int]] = {
    "INIDISP":   (0x2100, WHOLE),
    "OBSEL":     (0x2101, WHOLE),
    "OAMDATA":   (0x2104, WHOLE),
    "BGMODE":    (0x2105, WHOLE),
    "MOSAIC":    (0x2106, WHOLE),
    "BG1SC":     (0x2107, WHOLE),   # tilemap base + size, per layer. WHOLE:
    "BG2SC":     (0x2108, WHOLE),   # write-only, so no partial ownership even
    "BG3SC":     (0x2109, WHOLE),   # though the size bits look separable.
    "BG4SC":     (0x210A, WHOLE),
    "BG12NBA":   (0x210B, WHOLE),   # CHR base nibble PAIRS (BG1 low, BG2 high)
    "BG34NBA":   (0x210C, WHOLE),   # — write-only, so the pair is one owner
    "BG1HOFS":   (0x210D, WHOLE),   # physically also M7HOFS — one port, one
    "BG1VOFS": (0x210E, WHOLE), # name
    "BG2HOFS":   (0x210F, WHOLE),
    "BG2VOFS":   (0x2110, WHOLE),
    "BG3HOFS":   (0x2111, WHOLE),
    "BG3VOFS":   (0x2112, WHOLE),
    "BG4HOFS":   (0x2113, WHOLE),
    "BG4VOFS":   (0x2114, WHOLE),
    "VMDATAL":   (0x2118, WHOLE),
    "VMDATAH":   (0x2119, WHOLE),
    "M7SEL":     (0x211A, WHOLE),
    "M7A":       (0x211B, WHOLE),
    "M7B":       (0x211C, WHOLE),
    "M7C":       (0x211D, WHOLE),
    "M7D":       (0x211E, WHOLE),
    "M7X":       (0x211F, WHOLE),
    "M7Y":       (0x2120, WHOLE),
    "CGDATA":    (0x2122, WHOLE),
    "W12SEL":    (0x2123, WHOLE),
    "W34SEL":    (0x2124, WHOLE),
    "WOBJSEL":   (0x2125, WHOLE),
    "WH0":       (0x2126, WHOLE),
    "WH1":       (0x2127, WHOLE),
    "WH2":       (0x2128, WHOLE),
    "WH3":       (0x2129, WHOLE),
    "WBGLOG":    (0x212A, WHOLE),   # two-window boolean combine, BG1-4
    "WOBJLOG":   (0x212B, WHOLE),   # ...and OBJ + the MATH window
    "TM":        (0x212C, WHOLE),
    "TS":        (0x212D, WHOLE),
    "TMW":       (0x212E, WHOLE),
    "TSW":       (0x212F, WHOLE),
    "CGWSEL":    (0x2130, WHOLE),
    "CGADSUB":   (0x2131, WHOLE),
    "COLDATA":   (0x2132, WHOLE),   # the whole port: all three planes
    "COLDATA_R": (0x2132, 0x20),    # plane-select bits are the mask, so a
    "COLDATA_G": (0x2132, 0x40),    # plane claim and a whole-port claim are
    "COLDATA_B": (0x2132, 0x80),    # SEEN to intersect
    "SETINI":    (0x2133, WHOLE),
    # THE APU MAILBOX IS ONE RESOURCE UNDER ONE NAME — the ALU precedent
    # applied to $2140-$2143 (APUI00-03). The four ports carry ONE protocol
    # instance (TAD: command + two parameters + spinlock/ack, and the loader
    # handshake multiplexes all four), so separate per-port names would let a
    # claim on half a handshake compose with a claim on the other half while
    # physically fighting. One name has nothing to alias. Do NOT add sibling
    # APUI01-03 names: _register_conflicts fires on port EQUALITY, so a
    # sibling at $2141 would silently compose against this one.
    # It sits on the B bus, so hdma/dma_init MAY target it (a DMA upload
    # path); the expected user today is [[claims.reg]] on the audio feature —
    # tad-audio.s must be the only $2140-43 writer.
    "APUIO":     (0x2140, WHOLE),

    # ---- CPU-bus registers: claims.reg ONLY (see the B-BUS INVARIANT above) --
    "NMITIMEN":  (0x4200, WHOLE),   # NMI enable + IRQ mode + auto-joypad, all
                                    # in one WRITE-ONLY byte, so one owner.
    # THE H/V TIMER IS ONE RESOURCE UNDER ONE NAME, not an H timer and a V
    # timer — the ALU precedent verbatim. Re-derived from Mesen2
    # Core/SNES/InternalRegisters.cpp, whose four write handlers feed a SINGLE
    # timer state and a SINGLE IRQ line:
    #   :352/:357 case 0x4207/0x4208 set _state.HorizontalTimer (lo / bit 8);
    #   :362/:371 case 0x4209/0x420A set _state.VerticalTimer (lo / bit 8);
    #   all four call UpdateIrqLevel() — one _irqLevel circuit, one CPU IRQ
    #   source (SnesIrqSource::Ppu), one $FFEE vector, one TIMEUP flag that
    #   $4211 read-clears (:246-253 -> SetIrqFlag -> ClearIrqSource :180-186).
    # (port, mask) cannot express that: _register_conflicts fires only on port
    # equality, so sibling HTIME/VTIME names would COMPOSE while physically
    # arming one timer — an HTIME-only claimant reshapes the VTIME claimant's
    # trigger (V-only vs H+V is NMITIMEN bits 4/5 against the SAME counters,
    # InternalRegisters.h ProcessIrqCounters). One name has nothing to alias.
    # Write-only ports; the read side (TIMEUP $4211, HVBJOY $4212) is status,
    # not state, and stays outside the claim surface. CPU-bus, so
    # claims.reg only — a transfer
    # claim here would BBAD-alias onto $2107-$210A (the B-BUS INVARIANT).
    "HVIRQ":     (0x4207, WHOLE),
    # THE ALU IS ONE RESOURCE UNDER ONE NAME, not a multiplier and a divider.
    # Re-derived from Mesen2 Core/SNES/AluMulDiv.cpp, which holds a SINGLE
    # _state that the two entry points mutually destroy:
    #   :94  case 0x4203 (start multiply) sets _state.DivResult, which is what
    #        $4214/$4215 RDDIV reads -> starting a multiply destroys the
    #        divide result;
    #   :106 case 0x4206 (start divide) sets _state.MultOrRemainderResult,
    #        which is what $4216/$4217 RDMPY reads -> and vice versa;
    #   :83  blockWrite = _divCounter > 0 || _multCounter > 0 -> a write during
    #        an in-flight op is SILENTLY DROPPED, so a preempting NMI corrupts
    #        the interrupted operation AND gets garbage itself.
    # (port, mask) cannot express that: _register_conflicts only fires when the
    # ports are equal, so separate WRMPYA/WRDIVL names would COMPOSE while
    # physically fighting — the COLDATA sub-register hole inverted (there one
    # port had to be seen as three resources; here two ports must be seen as
    # one). One name has nothing to alias. Covers $4202-$4206 (write:
    # WRMPYA/B, WRDIVL/H/B) and $4214-$4217 (read: RDDIV, RDMPY).
    "ALU":       (0x4202, WHOLE),
}

PPU_REGISTERS = frozenset(REGISTER_FOOTPRINT)

# THE MULTI-PORT SPANS, MADE EXECUTABLE. Two names above own a BLOCK of ports
# under one name, and until this table existed that fact lived only in their
# comments: `register_ports` returns the base port, and `_register_conflicts`
# fires on port EQUALITY. That is sound for the DECLARATION side — every
# declarer of one resource uses the one name, so equality is enough — and
# structurally insufficient for a WRITER-side scan, which sees the actual port
# byte the ASM stores to. Without this, `sta $2141` in a file with no audio
# claim resolves to no name at all and passes, which is the precise write
# tad-audio.inc:49 forbids.
#
# Kept HERE, beside the comment blocks that derive each span from Mesen2, so
# the data and the prose cannot drift. This is the settled default —
# "one source of truth, in the file whose comments already carry the fact"
# It replaced a companion `RESOURCE_SPANS` table in
# `no_literals.py` — the explicitly-REJECTED alternative — which the
# reg-gate convergence audit (§1.3) measured as behaviourally identical
# (`rg_apuio_fires`, `rg_alu_fires`, `rgfx_alu_fires` fire on both tools;
# the declared siblings stay silent on both) but architecturally the wrong
# home. The port kept the extents unchanged and moved the table; the drift
# test that used to pin two tables against each other became
# test_spans_contain_their_base_port, which pins the one table to the
# footprint.
#
# Deliberately NOT a third element on the REGISTER_FOOTPRINT tuples: that
# shape breaks four unpacking sites (`for n, (port, _) in ...` below,
# `port, mask = ...` in register_ports, allocate.py:176/178) and forces an
# edit to tests/test_spc_claim.py:178's exact-tuple assertion — and the
# writer-side gate's acceptance requires the declaration-side tests to stay
# UNTOUCHED and green.
#
# A name absent from this table spans exactly its base port. Ranges are
# INCLUSIVE and must contain the name's base port — locked by
# tests/test_reg_gate.py::test_spans_contain_their_base_port, so a span edited
# to no longer cover the port every declaration-side check uses goes red.
REGISTER_SPANS: dict[str, tuple[tuple[int, int], ...]] = {
    # the APU mailbox: APUI00-03, one protocol instance (see APUIO above)
    "APUIO": ((0x2140, 0x2143),),
    # write ports WRMPYA/B + WRDIVL/H/B, and the read ports RDDIV + RDMPY that
    # the same single AluMulDiv _state feeds (see ALU above)
    "ALU":   ((0x4202, 0x4206), (0x4214, 0x4217)),
    # HTIMEL/H + VTIMEL/H: one timer, one IRQ line (see HVIRQ above)
    "HVIRQ": ((0x4207, 0x420A),),
}


def register_span(name: str) -> tuple[tuple[int, int], ...]:
    """Every (lo, hi) port range `name` owns. Base port when it owns one."""
    port, _mask = REGISTER_FOOTPRINT[name]
    return REGISTER_SPANS.get(name, ((port, port),))


def register_covering_names(port: int) -> tuple[str, ...]:
    """The reverse lookup the writer-side gate needs: names covering `port`.

    REGISTER_FOOTPRINT is name -> port; a scan of ASM has the port and needs
    the names. Sorted for a stable diagnostic. Empty = the port carries no
    footprint name, which is its own finding kind.
    """
    return tuple(sorted(n for n in REGISTER_FOOTPRINT
                        if any(lo <= port <= hi
                               for lo, hi in register_span(n))))

# Names a DMA transfer may target: the B bus only. claims.reg accepts every
# name in the footprint; claims.hdma / claims.dma_init accept this subset.
B_BUS_REGISTERS = frozenset(
    n for n, (port, _) in REGISTER_FOOTPRINT.items()
    if B_BUS_LO <= port <= B_BUS_HI)

# DMAP transfer mode (bits 0-2) -> how many CONSECUTIVE ports the transfer
# drives, starting at BBAD. This is what makes a declaration predict the
# register set the silicon actually sees: one BBAD byte plus a mode is a port
# SPAN, not a single port. mode 3 with BBAD=$211B drives M7A *and* M7B, which
# is why mode7_persp declares two names for one channel.
#
#   0: A            1 port      4: A,B,C,D      4 ports
#   1: A,B          2 ports     5: A,B,A,B      2 ports
#   2: A,A          1 port      6: A,A          1 port
#   3: A,A,B,B      2 ports     7: A,A,B,B      2 ports
DMAP_MODE_SPAN = {0: 1, 1: 2, 2: 1, 3: 2, 4: 4, 5: 2, 6: 1, 7: 2}

DMAP_INDIRECT = 0x40

# active  — HDMA drives the port every scanline of the band: EXCLUSIVE.
# vblank  — serialised NMI-hook queue entries: shared by construction.
# (claims.dma_init declares the third phase, forced_blank; see DmaInitClaim.)
HDMA_PHASES = ("active", "vblank")


def register_ports(names) -> dict[int, int]:
    """Physical footprint of a set of declared names: port -> OR of masks."""
    out: dict[int, int] = {}
    for n in names:
        port, mask = REGISTER_FOOTPRINT[n]
        out[port] = out.get(port, 0) | mask
    return out


def bbad_span(bbad: int, mode: int) -> tuple[int, ...]:
    """The consecutive B-bus ports a (BBAD, DMAP mode) pair actually drives."""
    base = 0x2100 | (bbad & 0xFF)
    return tuple(base + i for i in range(DMAP_MODE_SPAN[mode & 0x07]))


def _parse_registers(t: dict, w: str, key: str = "registers") -> tuple[str, ...]:
    """Shared by claims.hdma and claims.dma_init — one vocabulary, one check.

    `key` exists so claims.reg's `scene_writes` / `scene_writes_shared` get the
    SAME vocabulary check as `registers` rather than a sibling validator with a
    second error vocabulary: a typo is not a resource, wherever it is typed.
    """
    regs = tuple(t[key])
    if not regs or not all(isinstance(r, str) for r in regs):
        raise SchemaError(f"{w}: {key} must be a non-empty list of names")
    unknown = [r for r in regs if r not in REGISTER_FOOTPRINT]
    if unknown:
        raise SchemaError(
            f"{w}: unknown register name(s) {unknown}. A name that is not in "
            f"the footprint table has no physical address or mask, so the "
            f"claim would take part in no exclusivity check and its BBAD byte "
            f"could not be emitted — a typo is not a resource. Known: "
            f"{', '.join(sorted(REGISTER_FOOTPRINT))}")
    return regs


def _reject_not_subset(sub: tuple[str, ...], sup: tuple[str, ...], w: str,
                       sub_key: str, sup_key: str, why: str) -> None:
    """Refuse `sub_key` naming anything outside `sup_key` — claims.reg's two
    subset relations (scene_writes_shared ⊆ scene_writes ⊆ registers)."""
    off = [r for r in sub if r not in sup]
    if off:
        raise SchemaError(
            f"{w}: {sub_key} names {off}, which {sup_key} does not hold "
            f"({', '.join(sup) or 'nothing'}) — {why}")


def _reject_non_b_bus(regs: tuple[str, ...], w: str) -> None:
    """A transfer target must be B-bus addressable. Guards hdma + dma_init.

    A DMA reaches its destination through BBAD, which the hardware widens to
    `$2100 | BBAD`. So a $42xx name on a transfer claim does not fail — it
    silently retargets a REAL, different register ($4202 -> $2102 OAMADDL,
    $4216 -> $2116 VMADDH). Every name in the footprint was inside the B-bus
    range until claims.reg needed NMITIMEN and ALU; this keeps the two
    vocabularies honest about which half they may use.
    """
    off = [r for r in regs if r not in B_BUS_REGISTERS]
    if off:
        detail = ", ".join(
            f"{r} (${REGISTER_FOOTPRINT[r][0]:04X} -> BBAD "
            f"${REGISTER_FOOTPRINT[r][0] & 0xFF:02X} = "
            f"${0x2100 | (REGISTER_FOOTPRINT[r][0] & 0xFF):04X})" for r in off)
        raise SchemaError(
            f"{w}: {detail} is not B-bus addressable, so a DMA cannot target "
            f"it. BBAD is only the LOW byte of the port and the hardware "
            f"widens it to $2100|BBAD, so this claim would drive the register "
            f"shown after the arrow instead — silently. A CPU-written "
            f"register belongs in [[claims.reg]] (docs/09 §2.1).")


def _parse_mode(t: dict, w: str, regs: tuple[str, ...]) -> int:
    """Validate the DMAP transfer mode against the declared register list.

    The mode is what turns one BBAD byte into a port SPAN, so it has to agree
    with the names or the declaration cannot predict the silicon. Default 0
    (single port) is safe because a mismatch is LOUD: a 2-register claim that
    forgets `mode = 3` fails here rather than silently claiming one port.
    """
    mode = int(t.get("mode", 0))
    if mode not in DMAP_MODE_SPAN:
        raise SchemaError(f"{w}: DMAP mode {mode} not in 0..7")
    span = DMAP_MODE_SPAN[mode]
    if len(regs) != span:
        raise SchemaError(
            f"{w}: DMAP mode {mode} drives {span} consecutive port(s) but "
            f"{len(regs)} register(s) {list(regs)} are declared. The mode and "
            f"the register list must agree — they are two halves of one claim "
            f"about which ports the transfer touches.")
    ports = [REGISTER_FOOTPRINT[r][0] for r in regs]
    want = [ports[0] + i for i in range(span)]
    if ports != want:
        raise SchemaError(
            f"{w}: registers {list(regs)} are at ports "
            f"{[f'${p:04X}' for p in ports]}, but a mode-{mode} transfer from "
            f"BBAD ${ports[0] & 0xFF:02X} drives "
            f"{[f'${p:04X}' for p in want]}. A multi-register claim must name "
            f"CONSECUTIVE ports in ascending order.")
    return mode


@dataclass(frozen=True)
class VramClaim:
    name: str
    kind: str                 # tilemap | chr | mode7 | raw
    words: int                # size in words (mode7: fixed by substrate)
    obj: bool = False         # chr claim holds OBJ tiles (Mode 7 displacement rule)
    at: int | None = None     # pinned word address (hardware contract) or packed


@dataclass(frozen=True)
class BytesClaim:             # dp / wram blocks
    name: str
    bytes: int
    dma_source: bool = False  # wram only: must not cross a WRAM bank for DMA
    at: int | None = None     # pinned start (linker-placed contract, e.g. a
                              # vendored unit whose variables the LINKER lays
                              # out — the cfg window must match and an lderror
                              # assert bridges the two) or packed. The
                              # VramClaim.at / CgramClaim.at precedent.


@dataclass(frozen=True)
class CgramClaim:
    name: str
    words: int
    at: int | None = None     # fixed word offset (sub-palette contract) or packed


@dataclass(frozen=True)
class OamClaim:
    name: str
    sprites: int
    at: int | None = None     # pinned first slot (H3, the BytesClaim.at
                              # precedent). OAM index order IS sprite-vs-
                              # sprite priority — lowest index in front — so
                              # a packed claim's front-of-table position is
                              # an ACCIDENT of the (-sprites, name) sort. An
                              # OBJ-HUD that must render over the scene's
                              # sprites pins its range instead

                              # The full priority/size-class vocabulary
                              # is deliberately NOT this field.


@dataclass(frozen=True)
class HdmaClaim:
    name: str
    channels: int
    registers: tuple[str, ...]
    band: tuple[int, int]     # [start_line, end_line) — "scene" = whole frame
    phase: str                # active | vblank
    channel: int | None = None  # pinned channel number, or allocator-assigned
    mode: int = 0             # DMAP transfer mode (bits 0-2); span must match
                              # len(registers) — see DMAP_MODE_SPAN
    indirect: bool = False    # DMAP bit 6: table holds pointers, data in DASB

    @property
    def bbad(self) -> int:
        """The BBAD byte this claim's channel must be programmed with.

        Derived from the DECLARATION, emitted as a symbol, and asserted
        against the live register file at runtime — so the encoding exists in
        exactly one place instead of being hand-narrated into the ASM.
        """
        return REGISTER_FOOTPRINT[self.registers[0]][0] & 0xFF

    @property
    def dmap(self) -> int:
        """The full DMAP byte: transfer mode + indirect flag (A->B)."""
        return (self.mode & 0x07) | (DMAP_INDIRECT if self.indirect else 0)


@dataclass(frozen=True)
class DmaInitClaim:
    """A general-purpose DMA transfer fired at scene-enter time.

    The third phase, `forced_blank`. Distinct from claims.hdma because it is
    not a per-scanline register owner: it is a one-shot upload that runs
    inside the scene_mgr enter contract, where BOTH competing phases are
    masked in hardware — HDMAEN is cleared and NMITIMEN is zeroed
    (scene_mgr.asm enter phase 2). So a dma_init claim composes with every
    `active` and `vblank` claim by construction, including on the same
    channel number, and dma_init claims serialise among themselves because
    scene-enter code runs sequentially.

    What declaring it buys, given it cannot collide: the channel and the
    target registers stop being invisible. Before this class, four features
    drove B-bus ports through a hard-coded channel 0 with a hand-written BBAD
    byte, while the allocator was independently handing channel 0 out to
    HDMA claims (ES_H_BGM_CH = 0, ES_H_OAMQ_CH = 0) — correct only by an
    ordering argument that lived in a comment. Now the channel and the BBAD
    byte are emitted from the declaration, and the disjointness precondition
    is asserted against real hardware rather than asserted in prose.
    """
    name: str
    channel: int              # pinned: enter-time code owns a known channel
    registers: tuple[str, ...]
    mode: int = 0
    indirect: bool = False

    @property
    def bbad(self) -> int:
        return REGISTER_FOOTPRINT[self.registers[0]][0] & 0xFF

    @property
    def dmap(self) -> int:
        return (self.mode & 0x07) | (DMAP_INDIRECT if self.indirect else 0)


@dataclass(frozen=True)
class RegClaim:
    """A register the CPU writes directly — the tenth claim class (docs/09 §2.1).

    NO phase, NO band, NO channel, NO mode. A CPU write is not a transfer: it
    has no DMAP byte and occupies no channel, and its ownership is SCENE-WIDE
    and PHASE-BLIND. That last part is the load-bearing design decision and it
    is deliberately NOT `_register_exclusive`'s rule:

      _register_exclusive lets vblank claims compose, and its docstring says
      exactly why — "they are queue entries the NMI hook fires one after
      another... Serialised writers to one register compose by construction."
      That is a property of the NMI QUEUE, not of registers. A CPU writer is
      not queued: the NMI PREEMPTS the main thread. Reusing that rule here
      would let a vblank-side ALU user compose with race_logic's main-thread
      one, i.e. it would let the hardware-multiplier defect through THE VERY
      CLASS BUILT TO CATCH IT. Two more live cases it would miss:
      mode7_persp's NMI-hook M7X/M7Y/HOFS/VOFS writes against any active-phase
      BG1-scroll claim (the contention its own census row names as the
      danger), and scene_mgr's per-frame NMI INIDISP commit against an
      enter-time forced-blank INIDISP write.

    So: two reg claims whose footprints intersect in one scene CONFLICT, full
    stop. `seed` is the one exemption, and it is about persistence rather than
    time — see the field comment.

    NOT THE RIGHT CLASS FOR FOUR PORTS. `TM`, `TS`, `CGWSEL` and `CGADSUB`
    are composed by the screen/blend vocabulary (ScreenClaim / BlendClaim
    below, docs/99): a layer designation is a `[[claims.screen]]` and
    colour-math programming a `[[claims.blend]]`, and inside a scene that
    composes either half a raw claim on those ports is REFUSED — the
    composition synthesizes its own ownership claim over them, so this class
    meets it as an ordinary intersection. A raw claim on them stays right
    only where the vocabulary does not reach: per-scanline TM under an hdma
    claim, direct colour (CGWSEL b0), TMW/TSW.
    """
    name: str
    registers: tuple[str, ...]
    # seed: this write establishes a BASE VALUE that another DECLARED claim is
    # expected to overwrite, rather than a value that must hold for the frame.
    # The two live instances both already say so in a comment — race.asm:88
    # "BGMODE 7 (HDMA overrides per line)" and :90 "TM: BG1 base (HDMA
    # overrides per line)" — against split_band's active HDMA claims on those
    # exact ports. Declaring it makes the comment checkable.
    #
    # It exempts hdma claims ONLY, never dma_init: an enter-time one-shot is a
    # second ESTABLISHER of a persistent value, not an ongoing overrider, so
    # two of those still fight. And a seed with nothing to override it is a
    # declaration that lies, which check_reg_ownership rejects.
    seed: bool = False
    # scene_writes: the subset of `registers` that scene-enter or boot code
    # MAY write — the owner's CONSENT, which docs/09 §2.1's hole 2 was the
    # absence of. Before it, the writer-side gate asked only "did someone in
    # this scene's closure declare this port", so scene and boot code were an
    # unlimited second writer of every port their closure happened to own.
    #
    # A PERMISSION, not an exclusivity. It does not say "and I never write it
    # myself" — sm_display opens NMITIMEN because BOOT must write it, and
    # scene_mgr's `@switch` writes it too at both ends, by design, masking NMI around the
    # scene switch. That co-write is declared separately, below.
    #
    # A LIST, not a boolean, because a boolean is wrong on two of the six live
    # claims: sm_display is [INIDISP, NMITIMEN] and only NMITIMEN is
    # boot-written (`sm_nmi_core` commits INIDISP every NMI — the hazard
    # docs/09 §2.1 names), and room_layers has nine registers of which two are
    # scene-written.
    scene_writes: tuple[str, ...] = ()
    # scene_writes_shared: the subset of `scene_writes` the owner ALSO writes
    # itself, on purpose. Same discipline as `seed` — a declaration that lies
    # is a finding, in BOTH directions (no_literals' lies-check): a
    # scene_writes register the owner writes without declaring it here, and a
    # scene_writes_shared register the owner does not write at all.
    #
    # Its baseline is 1, not 0, and irreducible: sm_display/NMITIMEN. Boot's
    # $4200 write answers to the globals' union, scene_mgr is the only globals
    # feature declaring NMITIMEN, so NMITIMEN must be opened -- and scene_mgr
    # must write it. Hence a declared escape rather than a rule with one
    # permanent exception.
    scene_writes_shared: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# the screen/blend vocabulary — layer designation + color-math programming
# --------------------------------------------------------------------------
#
# Two claim classes over four write-only ports (TM $212C, TS $212D, CGWSEL
# $2130, CGADSUB $2131). The ports stay WHOLE in REGISTER_FOOTPRINT — they
# fail the single-blind-write test (see the header block above), so they can
# never be sub-registered. What CAN be partitioned is the DECLARATION: each
# feature declares its per-layer intent, and the allocator composes the four
# byte values per scene, refusing any composition the one-blender hardware
# cannot express. Encodings re-derived from Mesen2 Core/SNES/SnesPpu.cpp
# (this checkout):
#
#   TM/TS      value & $1F, bit = layer          :2175-2183
#   layer bits BG1=0 BG2=1 BG3=2 BG4=3 OBJ=4     SnesPpu.h:22 (SpriteLayerIndex)
#   CGWSEL     b7-6 clip, b5-4 prevent (window modes), b1 addend = sub screen,
#              b0 direct color                   :2199-2205
#   CGADSUB    b7 subtract, b6 halve, b5-0 math enables (b5 backdrop
#              RenderBgColor :924, b4 OBJ :962 — palettes 4-7 only,
#              b3-0 BG4..BG1 RenderTilemap :993) :2207-2212
#   window modes Never=0 Outside=1 Inside=2 Always=3
#                                                SnesPpuTypes.h ColorWindowMode

SCREEN_LAYERS = {"bg1": 0, "bg2": 1, "bg3": 2, "bg4": 3, "obj": 4}
MATH_LAYERS = {**SCREEN_LAYERS, "backdrop": 5}
SCREEN_ON = ("main", "sub", "both")
BLEND_OPS = ("add", "sub")              # CGADSUB b7: sub = 1
BLEND_SOURCES = ("sub", "fixed")        # CGWSEL b1: sub = 1
WINDOW_MODES = {"never": 0, "outside": 1, "inside": 2, "always": 3}

# The registers each half of the vocabulary composes — what the synthesized
# per-scene ownership claim holds (allocate.compose_screen_blend). Screen
# claims own the designation ports; blend claims own the math ports. The
# split is deliberate: a raw CGWSEL claim stays expressible in a scene that
# designates layers but declares no blend (e.g. a direct-color scene), and a
# raw TM claim stays expressible in a scene that blends over raw-designated
# layers — the mixing refusal fires exactly where the vocabularies meet on
# one port.
SCREEN_REGS = ("TM", "TS")
BLEND_REGS = ("CGWSEL", "CGADSUB")


@dataclass(frozen=True)
class ScreenClaim:
    """A LAYER-to-SCREEN designation — one layer, one screen, one owner.

    The thirteenth claim class. TM/TS are write-only bytes with one owner per
    scene each under the raw vocabulary, so no two features could ever share
    the screen designation ports. This class moves the declaration to the
    layer: each feature designates its own layer(s), the allocator ORs the
    bits per scene, and layer ownership — not the byte value — becomes the
    contended resource. Two features designating the same layer refuse even
    when they agree on `on`, exactly as two RegClaims on one port do:
    ownership is the resource.
    """
    name: str
    layer: str                # bg1|bg2|bg3|bg4|obj  (SCREEN_LAYERS)
    on: str                   # main|sub|both        (SCREEN_ON)


@dataclass(frozen=True)
class BlendClaim:
    """The color-math unit's programming — the fourteenth claim class.

    The PPU has ONE blender: one add/subtract select (CGADSUB b7), one halve
    (b6), one addend source (CGWSEL b1), one clip mode and one prevent mode
    (CGWSEL b7-4) — all global per frame (Mesen2 SnesPpu.cpp
    ApplyColorMathToPixel, :1302-1380). Those are the GLOBAL fields: two
    blend claims in one scene must agree on all five or the composition
    refuses. What composes is `math` — the per-layer enable bits (CGADSUB
    b5-0), each with one owner per scene (the ScreenClaim rule on the
    CGADSUB axis).
    """
    name: str
    op: str                   # add|sub   (BLEND_OPS)
    source: str               # sub|fixed (BLEND_SOURCES)
    math: tuple[str, ...]     # MATH_LAYERS names — main-screen layers gated in
    half: bool = False        # CGADSUB b6
    clip: str = "never"       # WINDOW_MODES -> CGWSEL b7-6
    prevent: str = "never"    # WINDOW_MODES -> CGWSEL b5-4


# --------------------------------------------------------------------------
# the video/offset vocabulary — the scene's BGMODE, and BG3 as an offset table
# --------------------------------------------------------------------------
#
# Two claim classes over one write-only port (BGMODE $2105) and over one
# hardware path no claim class could see at all: OFFSET-PER-TILE, where in
# modes 2, 4 and 6 the BG3 tilemap stops being tiles and becomes a per-column
# SCROLL OFFSET TABLE. BGMODE stays WHOLE in REGISTER_FOOTPRINT — it is
# write-only and fails the single-blind-write test like every other port in
# that table — and what is partitioned here is again the DECLARATION: a scene
# declares its video mode, the allocator composes the byte, and every claim
# whose legality DEPENDS on the mode can finally be checked against it.
#
# WHY THE MODE HAD TO BECOME DECLARABLE. Two capabilities were undeclarable
# without it, both named in the capability map's offset-per-tile entry:
# nothing said "BG3 is not a drawable layer in this scene", so a text feature
# and an offset-per-tile feature both believed they owned BG3 with no
# collision visible; and the mode restriction — offset-per-tile exists only in
# modes 2/4/6 — was not expressible as a constraint at all. Both are
# properties OF THE MODE, and the mode was a value nobody declared: BGMODE
# appeared in 26 raw [[claims.reg]] footprints across this tree and its VALUE
# lived only in ASM and in feature.toml comments.
#
# Encodings and layer sets re-derived from Mesen2 Core/SNES/SnesPpu.cpp in
# this checkout, per the house rule that a register encoding comes from the
# emulator source and not from a summary:
#
#   BGMODE       b2-0 mode, b3 mode-1 BG3 priority, b4-7 16x16 tiles for
#                BG1..BG4                                        :1951-1959
#   which layers a mode RENDERS   RenderMode0..RenderMode7, :781-859 — a mode
#                calls RenderTilemap once per layer it draws, and a layer it
#                never calls is not on screen in that mode AT ALL
#   which modes FETCH offset words        FetchTileData, :277-390 — modes 2
#                and 6 fetch an H word AND a V word per column (cases 2 and
#                3); mode 4 fetches ONE word (case 2) whose bit 15 selects V
#                over H; every other mode fetches neither
#   the offset words come from BG3's OWN tilemap, indexed by BG3HOFS (the
#                column, 8 px granular) and BG3VOFS (WHICH ROW is the H row);
#                the V row is that row + 0x20 words, wrapping inside the map
#                                        GetHorizontalOffsetByte /
#                                        GetVerticalOffsetByte, :257-276
#   bit 13 applies a column's offset to BG1, bit 14 to BG2      :154-167
#   H: hScroll = (hScroll & 7) | (word & $3F8) — the LAYER keeps its own fine
#                three bits, so a horizontal offset is 8-PIXEL granular and
#                cannot express a sub-tile shear                 :157, :164
#   V: vScroll = word & $3FF — the offset REPLACES the layer's scroll rather
#                than adding to it                               :160, :167
#
# Two of those rows are load-bearing for the refusal set. The render tables
# are why a screen designation of a layer the mode does not draw is a
# declaration that lies rather than a harmless spare bit (the R5 shape, on
# the mode axis). And the fetch schedule is why offset-per-tile outside modes
# 2/4/6 is not "an effect that does not show" but a claim on a mechanism the
# PPU never runs.

# Which BG layers a BGMODE renders. OBJ is absent on purpose: sprites render
# in every mode, so `obj` is never constrained by this table.
#
# Mode 7's row is BG1 alone, and it is the one approximation here: RenderMode7
# also draws BG2 when EXTBG is enabled ($2133 bit 6, :856-858). EXTBG has no
# model in this tree (docs/09's G5 — BG2's pixels ARE BG1's, split by bit 7,
# which is an identity the claim classes cannot express), so a bg2 designation
# under mode 7 WARNS rather than refusing. bg3/bg4 under mode 7 refuse: no
# setting makes RenderMode7 draw them.
MODE_LAYERS = {
    0: ("bg1", "bg2", "bg3", "bg4"),
    1: ("bg1", "bg2", "bg3"),
    2: ("bg1", "bg2"),
    3: ("bg1", "bg2"),
    4: ("bg1", "bg2"),
    5: ("bg1", "bg2"),
    6: ("bg1",),
    7: ("bg1",),
}

# ...and at what depth, which is what decides the ART BUDGET a mode costs.
# Read off the same RenderMode bodies (the second template argument) and
# cross-checked against FetchTileData's GetChrData bpp arguments.
MODE_BPP = {
    0: {"bg1": 2, "bg2": 2, "bg3": 2, "bg4": 2},
    1: {"bg1": 4, "bg2": 4, "bg3": 2},
    2: {"bg1": 4, "bg2": 4},
    3: {"bg1": 8, "bg2": 4},
    4: {"bg1": 8, "bg2": 2},
    5: {"bg1": 4, "bg2": 2},
    6: {"bg1": 4},
    7: {"bg1": 8},
}

# The three modes whose FetchTileData reads offset words. Everything else in
# this vocabulary follows from this tuple.
OFFSET_MODES = (2, 4, 6)

# Modes 2 and 6 fetch an H word and a V word per column, so a column can carry
# both axes; mode 4 fetches one word and bit 15 picks the axis, so a column
# carries one. `axis` says which the table declares.
OFFSET_AXES = ("h", "v", "both")

# The enable bits an offset word can set: bit 13 -> BG1, bit 14 -> BG2. No
# other layer is reachable — SnesPpu.cpp:154 computes the bit from the layer
# index and only indices 0 and 1 are ever passed while an offset is latched.
OFFSET_LAYER_BITS = {"bg1": 0x2000, "bg2": 0x4000}

# The offset word's fields, as the composition emits them.
OFFSET_VALUE_MASK = 0x03FF      # V: vScroll = word & $3FF
OFFSET_H_VALUE_MASK = 0x03F8    # H: ...and the layer keeps its own low 3 bits
OFFSET_VSEL_BIT = 0x8000        # mode 4 only: this word is a V offset

# The registers the offset path READS, and therefore the ports the
# composition takes ownership of. Deliberately NOT BG34NBA: no CHR is fetched
# for BG3 in an offset mode, so the offset path never reads a BG3 chr base and
# claiming it would be a declaration that lies. The bg_text collision the
# vocabulary exists to catch fires on BG3SC regardless.
OFFSET_REGS = ("BG3SC", "BG3HOFS", "BG3VOFS")
VIDEO_REGS = ("BGMODE",)


@dataclass(frozen=True)
class VideoClaim:
    """The scene's VIDEO MODE — the fifteenth claim class.

    BGMODE is a write-only byte with one owner per scene under the raw
    vocabulary, which is correct and says nothing: the OWNER was declarable
    and the MODE was not. Everything a mode decides — which layers exist, at
    what depth, and whether the offset-per-tile path runs at all — was a fact
    about the scene that lived in a comment.

    ONE PER SCENE, and the scene is the unit because BGMODE is: a mid-frame
    mode swap is a per-scanline HDMA rewrite, which keeps the raw claim shape
    (`split_band` is that feature, and it is deliberately mode-agnostic).
    """
    name: str
    mode: int                     # BGMODE b2-0
    bg3_priority: bool = False    # b3 — read only by RenderMode1
    tiles16: tuple[str, ...] = ()  # b4-7, one per BG layer


@dataclass(frozen=True)
class OffsetClaim:
    """OFFSET-PER-TILE — BG3's tilemap as a per-column scroll table, and the
    sixteenth claim class.

    The claim is not "some VRAM holds offsets": it is that IN THIS SCENE BG3
    IS NOT A LAYER. The table it points at is an ordinary
    `[[claims.vram]] kind = "tilemap"` region — that part the claim classes
    always covered — and what they could not say is the consequence, which is
    that every other feature's belief that it can draw on BG3 is now false.

    Ownership therefore moves to the thing contended: the BG3 fetch path. The
    composition synthesizes ownership of BG3SC/BG3HOFS/BG3VOFS, so a feature
    that draws on BG3 meets this one as an ordinary register intersection with
    a message that names the mechanism, and a bg3 screen designation in the
    same scene refuses in the composition.
    """
    name: str
    axis: str                     # h | v | both  (OFFSET_AXES)
    layers: tuple[str, ...]       # bg1 | bg2 — the enable bits it may set


@dataclass(frozen=True)
class SpcClaim:
    """Exclusive occupancy of the audio CPU's entire 64 KiB — the eleventh
    claim class (C1).

    PRESENCE-ONLY, deliberately: no address, no size, no alignment. The
    vendored TAD driver owns and packs all of SPC RAM, and its compiler
    refuses over-budget song compositions at build time (common + song +
    max_edl echo <= 64 KiB, per song). Modelling that interior
    here would be a second source of truth for another tool's allocator,
    drifting with every TAD upgrade. What TAD cannot check is that it is the
    ONLY occupant — its API states the boundary as a comment
    (tad-audio.inc:49) — so this claim is that comment made checkable.

    PROGRAM-WIDE, not per-scene: the driver is initialised once per power-on
    (Tad_Init re-called hardlocks) and the upload persists across scenes, so
    two features holding spc in DIFFERENT scenes still corrupt each other.
    check_spc_exclusivity refuses >1 distinct holder across the whole game.

    The own-driver path (a real region class with ESA/DIR alignment and EDL
    granularity) is pre-scoped in and would replace this shape,
    not extend it.
    """
    name: str


@dataclass(frozen=True)
class RomClaim:
    name: str
    bytes: int
    dma_source: bool = True
    # Pre-chunked so every chunk fits one bank window — AND placed as a
    # CONTIGUOUS RUN of windows with every chunk at
    # window offset 0. So `ES_R_<NAME>_T<i>_BANK == ES_R_<NAME>_T0_BANK + i`
    # and `ES_R_<NAME>_T<i>_ADDR == ES_R_<NAME>_T0_ADDR` hold for the whole
    # claim, which is what lets a consumer address chunk i as BASE+i off one
    # window base (mode7_stream, mode7_floor, col_map all do). It is enforced
    # in `place_rom`, not merely observed: before that branch existed this
    # field promised only the first clause, and 3 of 4 measured shapes packed
    # NON-consecutively. Consumers
    # still assert it at their `.incbin` site — the guarantee is one edit away
    # from not being one, and the assert is what names the edit.
    bank_tiled: bool = False
    # `backed_by` — the ONE escape hatch of the rom-backing gate (docs/37).
    #
    # A rom claim reserves bytes; it does not put any there. The allocator packs
    # it, the emitted ES_R_* symbols name where it went, and the .incbin site's
    # `.assert ^label = ES_R_*_BANK` refuses DRIFT — but nothing ever asked
    # whether an .incbin exists at all, so a claim with no claim-site was silent
    # (rgb_gradient's grad_tabs during the breaker port, 2026-08-02: packed,
    # prerequisited, never included; three HDMA channels streamed whatever
    # bytes happened to live there and every gate stayed green).
    #
    # The default is "some hand-authored .asm in the no_literals scope includes
    # my bytes and ties them to my symbol". A claim whose bytes come from a
    # compilation unit OUTSIDE that scope — a vendored or generated unit the
    # gate never reads — states so here, in prose, naming the unit. Non-empty
    # is enforced: the convention this repo already runs on (`; REG-LINT: ok —
    # <reason>`, `; WIDTH-LINT: ok — <reason>`) is that an escape hatch which
    # need not say why is just a quiet way to turn the rule off.
    backed_by: str = ""

    # `window` — a rom claim PINNED to one LoROM window, because something
    # outside the allocator already fixed it there.
    #
    # The one occupant is `tad_rom`. vendor/rom/lorom_512k.cfg maps segment
    # AUDIO_DATA0 to ROM1 by name, so the TAD export physically IS window 1 —
    # and the allocator, which had no way to say that, agreed with it only
    # because `tad_export` was the largest claim in every composition so far
    # and largest-first first-fit put it there. The `sh2_map` claim is the first
    # rail with a SECOND whole-window claim: at 32,768 B it ties, sorts ahead
    # of `tad_export` by name, takes window 1, and the link then overflows
    # BANK1 by the export's 8,450 bytes. The assumption in that cfg's own
    # comment ("the allocator's whole-window tad_export claim reserves exactly
    # this bank") had expired, silently, and a tie-break decided a hardware
    # placement.
    #
    # Pinned claims are reserved BEFORE any largest-first pass runs, so the pin
    # is the premise the packer solves around rather than a preference it may
    # lose. That reservation is COMPOSITION-WIDE — globals and every scene, in
    # one pass (`allocate.reserve_pinned_rom`), because ROM is physical and
    # `place_rom` runs once per scope over one shared window list. Keeping the
    # pinned pass INSIDE `place_rom` makes that sentence true only within a
    # single call: a scene-scoped pin can then lose its window to a global
    # free claim and report as a collision.
    # This is the same move `vram`/`cgram`/`oam` claims already have in `at=`;
    # ROM simply never needed one until two whole-window claims met.
    #
    # Must be non-negative. There is deliberately no UPPER bound: the substrate
    # declares no ROM-size ceiling, and the FREE pass is equally unbounded (40
    # whole-window free claims reach window 40 with no error), so bounding the
    # pin alone would be a half-answer to a gap that is not the pin's.
    # Deferred with that ceiling.
    window: int | None = None


# --------------------------------------------------------------------------
# feature roles — the census taxonomy, declared rather than inferred
# --------------------------------------------------------------------------
#
# `role` exists because the supply census in docs/09_feature_register.md is
# generated from this tree (tools/gen_register.py), and the category column is
# the one thing in it that is NOT derivable. `car_rom` claims `rom` with no
# deps; `col_map_rom` claims `rom` with no deps -- both blobs. But `backdrop`
# claims `cgram` with no deps and is a feature, and `text_chr` is a companion.
# No other field separates them, so a heuristic cannot: the taxonomy is a
# judgement, and the allocator's own thesis is that a judgement someone made
# becomes a declaration the build proves.
#
# The value set is deliberately coarser than docs/09 §1.3's prose, which draws
# finer distinctions (`infrastructure` vs feature; `global` vs `shared-surface`
# companion). Those survive in that prose. They are not values here because
# neither is build-visible or checkable, and a declared field that no gate can
# ever enforce is a second hand-maintained list -- exactly what the generator
# exists to abolish.
FEATURE_ROLES: dict[str, str] = {
    "feature":   "supplies a demanded capability (bg_text, vwf, col_map)",
    "blob":      "ROM data, no behaviour -- ONLY claims.rom (car_rom, "
                 "font_rom, world_rom, col_map_rom)",
    # The discriminator against `blob` is the CLAIM CLASS, not who the claim is
    # held for. The old gloss ("holds claims on behalf of shared top-level
    # code") is satisfied by every *_rom blob too -- they all exist because an
    # .incbin sits at top level -- so it could not settle col_map_rom, which
    # docs/09 §1.2 mislabelled a companion for a week. If the dir
    # holds nothing but ROM data it is a blob however shared its consumer is.
    "companion": "holds NON-ROM claims (dp/vram/wram/cgram/dma_init) on behalf "
                 "of shared top-level code; a dir claiming only rom is a blob "
                 "(text_dp, text_chr, enter_scr)",
    "consumer":  "game-side user of an engine feature (player_car)",
    "game_logic": "NOT engine -- game code that lives under engine/features/ "
                  "only because that is where the allocator looks (race_logic)",
    "fixture":   "not a shipping dir at all: a toy/probe declaration that "
                 "exercises the allocator or a measurement instrument",
}


@dataclass(frozen=True)
class FeatureDecl:
    name: str
    role: str
    depends: tuple[str, ...]
    vram: tuple[VramClaim, ...]
    dp: tuple[BytesClaim, ...]
    wram: tuple[BytesClaim, ...]
    sram: tuple[BytesClaim, ...]    # program-wide battery-backed region (C2)
    cgram: tuple[CgramClaim, ...]
    oam: tuple[OamClaim, ...]
    hdma: tuple[HdmaClaim, ...]
    dma_init: tuple[DmaInitClaim, ...]
    rom: tuple[RomClaim, ...]
    reg: tuple[RegClaim, ...]
    spc: tuple[SpcClaim, ...]
    vblank_bytes_per_frame: int
    vblank_transfers_per_frame: int  # queued GP-DMAs paying arm cost (F9)
    init_zero: tuple[str, ...]      # claim names zeroed at scene entry
    # the screen/blend vocabulary (composed per scene by the allocator).
    # Defaulted so the two classes bolt on without touching any construction
    # site that predates them.
    screen: tuple[ScreenClaim, ...] = ()
    blend: tuple[BlendClaim, ...] = ()
    # ...and the video/offset vocabulary, defaulted for the same reason.
    video: tuple[VideoClaim, ...] = ()
    offset: tuple[OffsetClaim, ...] = ()

    def claim_names(self) -> set[str]:
        return {c.name for group in (self.vram, self.dp, self.wram, self.sram,
                                     self.cgram, self.oam, self.hdma,
                                     self.dma_init, self.rom, self.reg,
                                     self.spc, self.screen, self.blend,
                                     self.video, self.offset)
                for c in group}


def _as_list_of_tables(v, where: str) -> list[dict]:
    if isinstance(v, list) and all(isinstance(x, dict) for x in v):
        return v
    if isinstance(v, dict):
        return [v]
    raise SchemaError(f"{where}: expected a table or an array of tables")


def _parse_band(v, visible_lines: int, where: str) -> tuple[int, int]:
    if v == "scene":
        return (0, visible_lines)
    if (isinstance(v, list) and len(v) == 2
            and all(isinstance(x, int) for x in v) and 0 <= v[0] < v[1]):
        return (v[0], v[1])
    raise SchemaError(
        f"{where}: band must be \"scene\" or [start, end) with 0 <= start < end, got {v!r}")


# --- the rom-backing hatch's own check (docs/37 §3 case 1) ------------------
# `backed_by` is the ONE way to turn the rom-backing presence check off, and
# non-emptiness alone is a weaker bar than its blast radius warrants. The
# `; WIDTH-LINT: ok — <reason>` precedent it was modelled on differs on both
# axes that matter: that override suppresses ONE finding at ONE site, and it
# lives in the .asm line a reviewer is already reading. This one suppresses a
# whole claim — every chunk of a bank_tiled one — from a feature.toml an ASM
# reviewer never opens. `backed_by = "the asset tool generates it"` would have
# re-opened the grad_tabs bug in one line, with a plausible sentence.
#
# So the statement must CITE: at least one repo-relative path in it has to
# exist on disk. Deliberately not stronger than that — the string is prose for
# a human, and this is the cheapest check that makes the prose falsifiable. It
# does not verify the cited unit actually supplies the bytes (nothing short of
# reading the linker's output could), which is why it is a citation check and
# stated as one.
_PATHISH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z0-9]{1,5}")
_REPO_ROOT = Path(__file__).resolve().parent.parent


# A cited path only counts if it could plausibly BE (or place) a compilation
# unit. Existence alone is too weak: `backed_by = "README.md"` was accepted
# end-to-end, which is a citation-shaped way of writing "trust me". Hence the
# extension allowlist below. Both live citations
# pass unchanged — tad_rom names a `.asm` and a `.cfg`, the fixture names a
# `.asm`. The hatch suppresses a claim's ENTIRE presence check from a
# feature.toml no ASM reviewer opens, so it earns a tighter bar than the
# in-file `; WIDTH-LINT: ok — <reason>` overrides it resembles.
_UNIT_EXTS = frozenset(("asm", "s", "inc", "o", "cfg", "bin"))


def _cites_a_repo_path(statement: str) -> bool:
    """True if `statement` cites a compilation-unit-ish path that exists here."""
    for tok in _PATHISH_RE.findall(statement):
        # `..` cannot reach outside the tree. The build must work from a bare
        # checkout with nothing but this repo on disk, so a path that climbs
        # out of it is a bug even when it resolves on the author's machine.
        if ".." in Path(tok).parts:
            continue
        if Path(tok).suffix.lstrip(".").lower() not in _UNIT_EXTS:
            continue
        if (_REPO_ROOT / tok).exists():
            return True
    return False


def load_feature(path: str | Path, substrate: Substrate) -> FeatureDecl:
    path = Path(path)
    with open(path, "rb") as f:
        d = tomllib.load(f)
    where = str(path)
    _table(d, where, {"name": str, "role": str},
           {"depends": list, "claims": dict, "init": dict})
    name = _name_ok(d["name"], where)
    if path.parent.name != name:
        raise SchemaError(
            f"{where}: feature name '{name}' must match its directory "
            f"'{path.parent.name}' (features are loaded by directory name)")
    role = d["role"]
    if role not in FEATURE_ROLES:
        raise SchemaError(
            f"{where}: role '{role}' is not one of "
            f"{sorted(FEATURE_ROLES)}.\n"
            + "\n".join(f"  {k:<11} {v}" for k, v in FEATURE_ROLES.items())
            + "\nThe role is the supply census's category column "
              "(docs/09_feature_register.md §3), which is generated from this "
              "tree and cannot be derived from the claims.")
    depends = tuple(d.get("depends", []))
    if not all(isinstance(x, str) for x in depends):
        raise SchemaError(f"{where}: depends must be a list of feature names")

    claims = d.get("claims", {})
    _table(claims, f"{where} [claims]", {},
           {"vram": (list, dict), "dp": (list, dict), "wram": (list, dict),
            "cgram": (list, dict), "oam": (list, dict), "hdma": (list, dict),
            "rom": (list, dict), "dma": dict, "dma_init": (list, dict),
            "reg": (list, dict), "spc": (list, dict), "sram": (list, dict),
            "screen": (list, dict), "blend": (list, dict),
            "video": (list, dict), "offset": (list, dict)})

    vram = []
    for i, t in enumerate(_as_list_of_tables(claims.get("vram", []), where)):
        w = f"{where} [[claims.vram]] #{i}"
        _table(t, w, {"kind": str}, {"name": str, "words": int, "tiles": int,
                                     "tile_bytes": int, "obj": bool, "at": int})
        kind = t["kind"]
        if kind not in VRAM_KINDS:
            raise SchemaError(f"{w}: kind '{kind}' not in {VRAM_KINDS}")
        if kind == "mode7":
            words = substrate.mode7_region_words
            if "words" in t or "tiles" in t:
                raise SchemaError(f"{w}: mode7 claims the whole interleaved "
                                  f"region; do not give words/tiles")
        elif "words" in t:
            words = t["words"]
        elif "tiles" in t:
            # tiles are sized in bytes (16/32/64 per 8x8 tile); words = bytes/2
            tb = t.get("tile_bytes", 32)
            if tb not in (16, 32, 64):
                raise SchemaError(f"{w}: tile_bytes must be 16, 32 or 64")
            words = t["tiles"] * tb // 2
        else:
            raise SchemaError(f"{w}: give words= or tiles= (except kind=mode7)")
        if words <= 0:
            raise SchemaError(f"{w}: size must be positive")
        vram.append(VramClaim(name=t.get("name", f"{name}_{kind}{i if i else ''}"),
                              kind=kind, words=words, obj=t.get("obj", False),
                              at=t.get("at")))

    def bytes_claims(key: str, dma_source_allowed: bool) -> list[BytesClaim]:
        out = []
        for i, t in enumerate(_as_list_of_tables(claims.get(key, []), where)):
            w = f"{where} [[claims.{key}]] #{i}"
            opt = {"name": str, "at": int} \
                | ({"dma_source": bool} if dma_source_allowed else {})
            _table(t, w, {"bytes": int}, opt)
            if t["bytes"] <= 0:
                raise SchemaError(f"{w}: bytes must be positive")
            if "at" in t and t["at"] < 0:
                raise SchemaError(f"{w}: at must be non-negative")
            out.append(BytesClaim(name=t.get("name", f"{name}_{key}{i if i else ''}"),
                                  bytes=t["bytes"],
                                  dma_source=t.get("dma_source", False),
                                  at=t.get("at")))
        return out

    dp = bytes_claims("dp", dma_source_allowed=False)
    wram = bytes_claims("wram", dma_source_allowed=True)

    # sram — battery-backed cart RAM, the twelfth claim class (C2).
    # A BytesClaim like dp/wram, with two deliberate differences:
    #
    #   PROGRAM-wide placement. Placed ONCE over one free list spanning the
    #   union of every feature's sram claims across globals + all scenes,
    #   deduped by feature name (allocate.place_sram — the spc holders
    #   pattern). Scene-scoped reuse of a persistent byte would be a save
    #   that corrupts itself: SRAM contents outlive not just the scene but
    # the POWER, so the lifetime is the global one (persistent; the
    #   SRAM-backed subset = 'save state')" and the packer agrees with it.
    #
    #   NEVER in [init] zero. Structurally enforced below (the init_zero
    #   check validates against dp/wram names only — keep it that way): an
    #   init-zeroed save is not a save, and blanket-initialising SRAM erases
    # the one memory whose corruption survives power-off (
    #   CLAUDE.md rule 5 applies with extra force — the only honest read of
    #   raw SRAM is through the save feature's magic+CRC integrity gate).
    #
    # No dma_source: saves are CPU copies, and the <= one-bank-window cap in
    # substrate.toml keeps every claim inside $70:0000-$7FFF anyway
    # Total demand also derives the cart header's $FFD8 size
    # byte + $FFD6 battery type at emit time — see allocate.sram_header_bytes.
    sram = bytes_claims("sram", dma_source_allowed=False)

    cgram = []
    for i, t in enumerate(_as_list_of_tables(claims.get("cgram", []), where)):
        w = f"{where} [[claims.cgram]] #{i}"
        _table(t, w, {"words": int}, {"name": str, "at": int})
        cgram.append(CgramClaim(name=t.get("name", f"{name}_pal{i if i else ''}"),
                                words=t["words"], at=t.get("at")))

    oam = []
    for i, t in enumerate(_as_list_of_tables(claims.get("oam", []), where)):
        w = f"{where} [[claims.oam]] #{i}"
        _table(t, w, {"sprites": int}, {"name": str, "at": int})
        if t["sprites"] <= 0:
            raise SchemaError(f"{w}: sprites must be positive")
        if "at" in t and t["at"] < 0:
            raise SchemaError(f"{w}: at must be non-negative")
        oam.append(OamClaim(name=t.get("name", f"{name}_oam{i if i else ''}"),
                            sprites=t["sprites"], at=t.get("at")))

    hdma = []
    for i, t in enumerate(_as_list_of_tables(claims.get("hdma", []), where)):
        w = f"{where} [[claims.hdma]] #{i}"
        _table(t, w, {"registers": list},
               {"name": str, "channels": int, "band": (str, list), "phase": str,
                "channel": int, "mode": int, "indirect": bool})
        regs = _parse_registers(t, w)
        _reject_non_b_bus(regs, w)
        mode = _parse_mode(t, w, regs)
        phase = t.get("phase", "active")
        if phase not in HDMA_PHASES:
            raise SchemaError(f"{w}: phase '{phase}' not in {HDMA_PHASES}")
        chan = t.get("channel")
        if chan is not None and not (0 <= chan < substrate.channel_count):
            raise SchemaError(f"{w}: pinned channel {chan} out of range "
                              f"0..{substrate.channel_count - 1}")
        hdma.append(HdmaClaim(
            name=t.get("name", f"{name}_hdma{i if i else ''}"),
            channels=t.get("channels", 1), registers=regs,
            band=_parse_band(t.get("band", "scene"), substrate.visible_lines, w),
            phase=phase, channel=chan, mode=mode,
            indirect=bool(t.get("indirect", False))))

    dma_init = []
    for i, t in enumerate(_as_list_of_tables(claims.get("dma_init", []), where)):
        w = f"{where} [[claims.dma_init]] #{i}"
        _table(t, w, {"registers": list, "channel": int},
               {"name": str, "mode": int, "indirect": bool})
        regs = _parse_registers(t, w)
        _reject_non_b_bus(regs, w)
        mode = _parse_mode(t, w, regs)
        chan = t["channel"]
        if not (0 <= chan < substrate.channel_count):
            raise SchemaError(f"{w}: channel {chan} out of range "
                              f"0..{substrate.channel_count - 1}")
        dma_init.append(DmaInitClaim(
            name=t.get("name", f"{name}_dma_init{i if i else ''}"),
            channel=chan, registers=regs, mode=mode,
            indirect=bool(t.get("indirect", False))))

    reg = []
    for i, t in enumerate(_as_list_of_tables(claims.get("reg", []), where)):
        w = f"{where} [[claims.reg]] #{i}"
        _table(t, w, {"registers": list},
               {"name": str, "seed": bool,
                "scene_writes": list, "scene_writes_shared": list})
        # NO _reject_non_b_bus here on purpose: claims.reg is the one class
        # that may name a CPU-bus register, because it declares a CPU WRITE
        # rather than a transfer target.
        regs = _parse_registers(t, w)
        sw = (_parse_registers(t, w, "scene_writes")
              if "scene_writes" in t else ())
        sws = (_parse_registers(t, w, "scene_writes_shared")
               if "scene_writes_shared" in t else ())
        # scene_writes_shared ⊆ scene_writes ⊆ registers. Both relations are
        # checked HERE rather than in allocate.py because they are properties
        # of the declaration alone — no allocation, no other feature and no
        # ASM is needed to know a claim opened a register it does not hold.
        # (The lies-check, which DOES need the ASM, lives in no_literals.)
        _reject_not_subset(sw, regs, w, "scene_writes", "registers",
                           "a claim can only open a register it holds — "
                           "opening one it does not is a permission granted "
                           "over someone else's resource")
        _reject_not_subset(sws, sw, w, "scene_writes_shared", "scene_writes",
                           "the shared list says 'and I write it too', which "
                           "is only meaningful about a register scene code "
                           "was permitted to write in the first place")
        reg.append(RegClaim(name=t.get("name", f"{name}_reg{i if i else ''}"),
                            registers=regs, seed=bool(t.get("seed", False)),
                            scene_writes=sw, scene_writes_shared=sws))

    screen = []
    for i, t in enumerate(_as_list_of_tables(claims.get("screen", []), where)):
        w = f"{where} [[claims.screen]] #{i}"
        _table(t, w, {"layer": str, "on": str}, {"name": str})
        if t["layer"] not in SCREEN_LAYERS:
            raise SchemaError(
                f"{w}: layer '{t['layer']}' is not one of "
                f"{sorted(SCREEN_LAYERS)}. TM/TS carry one enable bit per "
                f"layer (bits 0-4: bg1..bg4, obj); a name outside that set "
                f"has no bit, so the designation could compose with nothing "
                f"— a typo is not a resource.")
        if t["on"] not in SCREEN_ON:
            raise SchemaError(
                f"{w}: on = '{t['on']}' is not one of {list(SCREEN_ON)}. "
                f"A layer is designated to the main screen (TM), the sub "
                f"screen (TS), or both — there is no other place for a "
                f"pixel to go.")
        screen.append(ScreenClaim(
            name=t.get("name", f"{name}_screen{i if i else ''}"),
            layer=t["layer"], on=t["on"]))

    blend = []
    for i, t in enumerate(_as_list_of_tables(claims.get("blend", []), where)):
        w = f"{where} [[claims.blend]] #{i}"
        _table(t, w, {"op": str, "source": str, "math": list},
               {"name": str, "half": bool, "clip": str, "prevent": str})
        if t["op"] not in BLEND_OPS:
            raise SchemaError(
                f"{w}: op = '{t['op']}' is not one of {list(BLEND_OPS)} "
                f"(CGADSUB bit 7: one add/subtract select for the whole "
                f"screen).")
        if t["source"] not in BLEND_SOURCES:
            raise SchemaError(
                f"{w}: source = '{t['source']}' is not one of "
                f"{list(BLEND_SOURCES)} (CGWSEL bit 1: the blender's second "
                f"operand is the sub screen or the fixed color — nothing "
                f"else reaches it).")
        math = tuple(t["math"])
        if not math:
            # R7 — a blender blending nothing. A declaration-alone property,
            # refused at parse like the scene_writes subset relations: no
            # allocation is needed to know it.
            raise SchemaError(
                f"{w}: `math` is empty — a blend claim of feature '{name}' "
                f"programs the color-math unit, and CGADSUB bits 0-5 are the "
                f"only gates that admit a main-screen pixel into the math "
                f"(one enable bit per layer, bit 5 = backdrop). With no "
                f"layer gated in, the blender is programmed to blend "
                f"nothing: no pixel can ever express this claim. Name at "
                f"least one main-screen layer (or \"backdrop\"), or drop "
                f"the claim.")
        if not all(isinstance(m, str) for m in math):
            raise SchemaError(f"{w}: math must be a list of layer names")
        unknown = [m for m in math if m not in MATH_LAYERS]
        if unknown:
            raise SchemaError(
                f"{w}: math names {unknown}, not in {sorted(MATH_LAYERS)}. "
                f"CGADSUB carries one enable bit per main-screen layer plus "
                f"the backdrop (bits 0-5); a name outside that set has no "
                f"bit — a typo is not a resource.")
        for key in ("clip", "prevent"):
            if key in t and t[key] not in WINDOW_MODES:
                raise SchemaError(
                    f"{w}: {key} = '{t[key]}' is not one of "
                    f"{sorted(WINDOW_MODES)} (CGWSEL window modes: never=0, "
                    f"outside=1, inside=2, always=3).")
        blend.append(BlendClaim(
            name=t.get("name", f"{name}_blend{i if i else ''}"),
            op=t["op"], source=t["source"], math=math,
            half=bool(t.get("half", False)),
            clip=t.get("clip", "never"), prevent=t.get("prevent", "never")))

    video = []
    for i, t in enumerate(_as_list_of_tables(claims.get("video", []), where)):
        w = f"{where} [[claims.video]] #{i}"
        _table(t, w, {"mode": int},
               {"name": str, "bg3_priority": bool, "tiles16": list})
        if t["mode"] not in MODE_LAYERS:
            raise SchemaError(
                f"{w}: mode = {t['mode']!r} is not one of "
                f"{sorted(MODE_LAYERS)}. BGMODE bits 0-2 hold the video "
                f"mode and there are eight of them — a ninth is not a "
                f"resource.")
        t16 = tuple(t.get("tiles16", []))
        if not all(isinstance(x, str) for x in t16):
            raise SchemaError(f"{w}: tiles16 must be a list of layer names")
        bad = [x for x in t16 if x not in ("bg1", "bg2", "bg3", "bg4")]
        if bad:
            raise SchemaError(
                f"{w}: tiles16 names {bad}, not in ['bg1', 'bg2', 'bg3', "
                f"'bg4']. BGMODE bits 4-7 carry one 16x16-tile select per BG "
                f"layer and there is no bit for anything else — OBJ sizes "
                f"come from OBSEL, not from here.")
        if len(set(t16)) != len(t16):
            raise SchemaError(
                f"{w}: tiles16 names a layer twice ({list(t16)}) — each "
                f"layer has ONE size bit in BGMODE, so a repeat cannot mean "
                f"anything the single entry does not already say.")
        video.append(VideoClaim(
            name=t.get("name", f"{name}_video{i if i else ''}"),
            mode=t["mode"], bg3_priority=bool(t.get("bg3_priority", False)),
            tiles16=t16))
    if len(video) > 1:
        # A feature declaring two modes is refused HERE rather than in the
        # composition, because it is a property of the declaration alone: no
        # scene is needed to know that one feature cannot want two BGMODEs.
        # (The two-features-in-one-scene case is O1, in the composition.)
        raise SchemaError(
            f"{where}: {len(video)} [[claims.video]] entries — a feature "
            f"declares the video mode ONCE. BGMODE holds one mode for the "
            f"whole scene; a second entry cannot mean 'and also', it can "
            f"only disagree with the first.")

    offset = []
    for i, t in enumerate(_as_list_of_tables(claims.get("offset", []), where)):
        w = f"{where} [[claims.offset]] #{i}"
        _table(t, w, {"axis": str, "layers": list}, {"name": str})
        if t["axis"] not in OFFSET_AXES:
            raise SchemaError(
                f"{w}: axis = '{t['axis']}' is not one of "
                f"{list(OFFSET_AXES)}. An offset word displaces a column "
                f"horizontally, vertically, or (in modes 2 and 6, which "
                f"fetch a word for each) both — there is no third axis on a "
                f"tilemap.")
        layers = tuple(t["layers"])
        if not all(isinstance(x, str) for x in layers):
            raise SchemaError(f"{w}: layers must be a list of layer names")
        if not layers:
            # The R7 shape on this axis: a table that drives nothing. Refused
            # at parse because no allocation is needed to know it — bits 13
            # and 14 are the ONLY gates that apply an offset word to a layer,
            # so with neither declared the table is authored, uploaded and
            # read by the PPU to no effect whatever.
            raise SchemaError(
                f"{w}: `layers` is empty — an offset-per-tile claim of "
                f"feature '{name}' declares BG3's tilemap to be a per-column "
                f"scroll table, and bits 13 and 14 of a word are the only "
                f"gates that apply it to a layer (13 -> BG1, 14 -> BG2). "
                f"With neither, every column of the table is inert: the PPU "
                f"reads the words and displaces nothing. Name at least one "
                f"of ['bg1', 'bg2'], or drop the claim.")
        bad = [x for x in layers if x not in OFFSET_LAYER_BITS]
        if bad:
            raise SchemaError(
                f"{w}: layers names {bad}, not in "
                f"{sorted(OFFSET_LAYER_BITS)}. An offset word reaches BG1 "
                f"(bit 13) and BG2 (bit 14) and nothing else — BG3 is the "
                f"table itself and BG4 does not exist in any mode that "
                f"fetches one, so a name outside that pair has no bit.")
        if len(set(layers)) != len(layers):
            raise SchemaError(
                f"{w}: layers names a layer twice ({list(layers)}) — each "
                f"layer has ONE enable bit in an offset word.")
        offset.append(OffsetClaim(
            name=t.get("name", f"{name}_offset{i if i else ''}"),
            axis=t["axis"], layers=layers))
    if len(offset) > 1:
        raise SchemaError(
            f"{where}: {len(offset)} [[claims.offset]] entries — a feature "
            f"declares the offset table ONCE. There is one BG3 fetch path "
            f"per scene and one pair of rows it reads; a second entry "
            f"describes a table the hardware will never look at.")

    spc = []
    for i, t in enumerate(_as_list_of_tables(claims.get("spc", []), where)):
        w = f"{where} [[claims.spc]] #{i}"
        # Presence-only ON PURPOSE: no bytes, no address, no alignment. The
        # claim asserts exclusive occupancy of the WHOLE 64 KiB; sizing lives
        # in the occupant's own toolchain (TAD's compiler). A
        # size field here would be a parallel model of that tool's interior.
        _table(t, w, {}, {"name": str})
        spc.append(SpcClaim(name=t.get("name", f"{name}_spc{i if i else ''}")))
    if len(spc) > 1:
        raise SchemaError(
            f"{where}: {len(spc)} [[claims.spc]] entries — a feature declares "
            f"SPC occupancy ONCE. The claim is presence-only exclusive "
            f"ownership of the whole 64 KiB; a second entry "
            f"cannot add anything and reads like a region claim, which this "
            f"deliberately is not.")

    rom = []
    for i, t in enumerate(_as_list_of_tables(claims.get("rom", []), where)):
        w = f"{where} [[claims.rom]] #{i}"
        _table(t, w, {"bytes": int}, {"name": str, "dma_source": bool,
                                      "bank_tiled": bool, "backed_by": str,
                                      "window": int})
        backed_by = t.get("backed_by", "")
        if "backed_by" in t and not backed_by.strip():
            raise SchemaError(
                f"{w}: `backed_by` is empty. It is the rom-backing gate's only "
                f"escape hatch (docs/37) and it must NAME the compilation unit "
                f"outside the no_literals scope that supplies these bytes — "
                f"e.g. backed_by = \"assets/audio/export/tad_audio_data.asm "
                f"-> AUDIO_DATA0\". An exemption that need not say why is a "
                f"quiet way to turn the rule off; drop the key to take the "
                f"default (an in-scope .incbin claim site).")
        if "backed_by" in t and not _cites_a_repo_path(backed_by):
            raise SchemaError(
                f"{w}: `backed_by` names no file that exists in this repo. It "
                f"reads \"{backed_by.strip()[:90]}\" — prose, not a citation. "
                f"This hatch turns off the ENTIRE presence check for the claim "
                f"(and for every chunk of a bank_tiled one), from a "
                f"feature.toml an ASM reviewer never opens, so it must be "
                f"CHECKABLE: name the path of the unit that supplies the "
                f"bytes, e.g. backed_by = \"assets/audio/export/"
                f"tad_audio_data.asm:119 -> segment AUDIO_DATA0 "
                f"(vendor/rom/lorom_512k.cfg)\". At least one repo-relative "
                f"path in the string must exist on disk (docs/37 §3 case 1).")
        if "window" in t and t["window"] < 0:
            raise SchemaError(
                f"{w}: `window` is {t['window']} — a LoROM window index must "
                f"be non-negative. Refused here rather than in the allocator "
                f"so the diagnostic names the typo: the placement pass would "
                f"otherwise reject it as belonging to the linker's code "
                f"windows, which is true of 0 and says nothing about -1.")
        rom.append(RomClaim(name=t.get("name", f"{name}_rom{i if i else ''}"),
                            bytes=t["bytes"], dma_source=t.get("dma_source", True),
                            bank_tiled=t.get("bank_tiled", False),
                            backed_by=backed_by.strip(),
                            window=t.get("window")))

    dma_t = claims.get("dma", {})
    _table(dma_t, f"{where} [claims.dma]", {},
           {"vblank_bytes_per_frame": int, "vblank_transfers_per_frame": int})
    vblank_bpf = dma_t.get("vblank_bytes_per_frame", 0)
    # F9 multi-queue model: each queued transfer pays an arm cost. Default is
    # one transfer when the feature moves VBlank bytes at all.
    vblank_tpf = dma_t.get("vblank_transfers_per_frame", 1 if vblank_bpf else 0)
    if vblank_bpf and vblank_tpf < 1:
        raise SchemaError(f"{where} [claims.dma]: vblank_bytes_per_frame > 0 "
                          f"needs vblank_transfers_per_frame >= 1")
    if vblank_tpf and not vblank_bpf:
        raise SchemaError(f"{where} [claims.dma]: vblank_transfers_per_frame "
                          f"without vblank_bytes_per_frame makes no claim")

    init_t = d.get("init", {})
    _table(init_t, f"{where} [init]", {}, {"zero": list})
    init_zero = tuple(init_t.get("zero", []))

    decl = FeatureDecl(name=name, role=role, depends=depends,
                       vram=tuple(vram), dp=tuple(dp),
                       wram=tuple(wram), sram=tuple(sram),
                       cgram=tuple(cgram), oam=tuple(oam),
                       hdma=tuple(hdma), dma_init=tuple(dma_init),
                       rom=tuple(rom), reg=tuple(reg), spc=tuple(spc),
                       vblank_bytes_per_frame=vblank_bpf,
                       vblank_transfers_per_frame=vblank_tpf,
                       init_zero=init_zero,
                       screen=tuple(screen), blend=tuple(blend),
                       video=tuple(video), offset=tuple(offset))

    names = [c.name for group in (decl.vram, decl.dp, decl.wram, decl.sram,
                                  decl.cgram, decl.oam, decl.hdma,
                                  decl.dma_init, decl.rom, decl.reg,
                                  decl.spc, decl.screen, decl.blend,
                                  decl.video, decl.offset)
             for c in group]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SchemaError(f"{where}: duplicate claim names {sorted(dupes)}")
    # dp/wram ONLY, on purpose: an [init] zero naming an sram claim would be
    # an init-zeroed save, i.e. not a save (see the sram class comment above).
    # Keeping sram out of this set is the structural enforcement.
    unknown_zero = set(init_zero) - {c.name for c in (*decl.dp, *decl.wram)}
    if unknown_zero:
        raise SchemaError(
            f"{where}: [init] zero references unknown dp/wram claims "
            f"{sorted(unknown_zero)} (declared: {sorted(c.name for c in (*decl.dp, *decl.wram))})")
    return decl


# --------------------------------------------------------------------------
# user game state
# --------------------------------------------------------------------------

_PRIMITIVES = {"u8": 1, "u16": 2, "u24": 3, "u32": 4}
_TYPE_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<count>[0-9]+)\])?(?:@(?P<place>dp))?$")


@dataclass(frozen=True)
class StateVar:
    name: str
    type_str: str
    size: int                 # total bytes (element size * count)
    place: str                # "dp" | "wram"


@dataclass(frozen=True)
class StateDecl:
    global_vars: tuple[StateVar, ...]
    scene_vars: dict[str, tuple[StateVar, ...]]  # scene id ("" = the single scene)


def _parse_var(name: str, spec: str, types: dict[str, int], where: str) -> StateVar:
    _name_ok(name, where)
    m = _TYPE_RE.fullmatch(spec)
    if not m:
        raise SchemaError(f"{where}: bad type spec '{spec}' for '{name}' "
                          f"(expect e.g. 'u16', 'u16@dp', 'EnemySlot[8]')")
    base = m.group("base")
    if base in _PRIMITIVES:
        elem = _PRIMITIVES[base]
    elif base in types:
        elem = types[base]
    else:
        raise SchemaError(f"{where}: unknown type '{base}' for '{name}' "
                          f"(primitives: {sorted(_PRIMITIVES)}; declare custom "
                          f"sizes in [types])")
    count = int(m.group("count") or 1)
    if count <= 0:
        raise SchemaError(f"{where}: array count must be positive for '{name}'")
    place = m.group("place") or "wram"
    if place == "dp" and elem * count > 32:
        raise SchemaError(f"{where}: '{name}' claims {elem * count} B @dp — DP vars "
                          f"must be hot scalars (<= 32 B); put buffers in wram")
    return StateVar(name=name, type_str=spec, size=elem * count, place=place)


def load_state(path: str | Path) -> StateDecl:
    path = Path(path)
    with open(path, "rb") as f:
        d = tomllib.load(f)
    where = str(path)
    _table(d, where, {}, {"types": dict, "global": dict, "scene": dict})
    types = {}
    for tname, size in d.get("types", {}).items():
        if not isinstance(size, int) or size <= 0:
            raise SchemaError(f"{where} [types]: size of '{tname}' must be a "
                              f"positive integer byte count")
        types[tname] = size

    gvars = tuple(_parse_var(n, s, types, f"{where} [global]")
                  for n, s in d.get("global", {}).items())

    scene_tbl = d.get("scene", {})
    scene_vars: dict[str, tuple[StateVar, ...]] = {}
    if scene_tbl and all(isinstance(v, dict) for v in scene_tbl.values()):
        for sid, tbl in scene_tbl.items():          # [scene.<id>] form
            scene_vars[sid] = tuple(_parse_var(n, s, types, f"{where} [scene.{sid}]")
                                    for n, s in tbl.items())
    elif scene_tbl:
        if any(isinstance(v, dict) for v in scene_tbl.values()):
            raise SchemaError(f"{where} [scene]: mix of flat vars and [scene.<id>] "
                              f"sub-tables — use one form")
        scene_vars[""] = tuple(_parse_var(n, s, types, f"{where} [scene]")
                               for n, s in scene_tbl.items())
    return StateDecl(global_vars=gvars, scene_vars=scene_vars)


# --------------------------------------------------------------------------
# game manifest
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SceneDecl:
    id: str
    features: tuple[str, ...]


# The transition styles a `[[edge]]` may declare. THE FIELD IS LOAD-BEARING FOR
# ANY EDGE THAT GOES THROUGH scene_mgr: allocate.py emits
# `ES_E_<SRC>_TO_<DST>_CUT` from it and the SM_SWITCH macro picks the runtime
# path from that symbol at assembly time, so such an edge's declared style IS
# the path its ROM takes. Before the field was parsed and consumed only
# by a report string (allocate.py's over-budget message) — it read like a
# behaviour selector and selected nothing.
#
#   "fade"   scene_mgr's brightness ramp: fade-out -> forced blank -> the
#            exit/enter switch -> fade-in. The default and the majority.
#   "cut"    the blank switch with NO ramp in either direction: forced blank,
#            exit/enter, back to full brightness. The in-place mode swap,
#            spelled as a transition.
#   "mosaic" mode7_explore's AND rpg's declaration (both edges each, zero
#            sm_request/SM_SWITCH call sites in either), kept rather than
#            rewritten — and it is NOT a scene_mgr phase, because that rail
#            does not use one.
#            `sm_request` is never called there and the phase byte stays 0 for
#            the ROM's life (game/mode7_explore/main.asm:15-22, :377-378,
#            scenes/town.asm:8-11, game.toml:16-28); its wipe is a mosaic
#            dissolve the RAIL drives itself (`mxx_blank_now` /
#            `mxx_swap_service`), and its second `[[scene]]` exists for the
#            ALLOCATOR — so Mode 7 and Mode 1 cannot own BGMODE/TM/BG1SC/
#            BG12NBA in one scene. So the value is accepted for two reasons and
#            neither is "it means fade": the manifest should describe the
#            transition the GAME performs, and refusing it would refuse a
#            shipping rail's build. Emitting `_CUT` absent for it is true in
#            the only sense the symbol claims — this edge does not take the cut
#            path. What IS true about fade is conditional and has no instance
#            today: a rail that declared "mosaic" *and* routed through
#            `sm_request` would get the fade machine, because no mosaic phase
#            exists. A real one would land here as a new style with its own
#            emitted symbol, rather than by reinterpreting this one.
#
# THE GENERAL SHAPE, since "mosaic" is the case that shows it: this enum
# constrains what an edge may SAY. It binds what the ROM DOES only where the
# scene code routes through SM_SWITCH — which is the tie built, and the
# reason the bypass analysis is about call sites rather than about
# this tuple.
EDGE_STYLES = ("fade", "cut", "mosaic")


@dataclass(frozen=True)
class EdgeDecl:
    src: str
    dst: str
    style: str
    budget_bytes: int | None


@dataclass(frozen=True)
class GameManifest:
    globals_: tuple[str, ...]
    scenes: tuple[SceneDecl, ...]
    edges: tuple[EdgeDecl, ...]


def load_manifest(path: str | Path) -> GameManifest:
    path = Path(path)
    with open(path, "rb") as f:
        d = tomllib.load(f)
    where = str(path)
    _table(d, where, {"scene": list}, {"globals": list, "edge": list})
    globals_ = tuple(d.get("globals", []))
    if not all(isinstance(g, str) for g in globals_):
        raise SchemaError(f"{where}: globals must be a list of feature names")

    scenes = []
    for i, t in enumerate(d["scene"]):
        w = f"{where} [[scene]] #{i}"
        _table(t, w, {"id": str, "features": list}, {})
        _name_ok(t["id"], w)
        if not all(isinstance(x, str) for x in t["features"]):
            raise SchemaError(f"{w}: features must be a list of feature names")
        scenes.append(SceneDecl(id=t["id"], features=tuple(t["features"])))
    ids = [s.id for s in scenes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SchemaError(f"{where}: duplicate scene ids {sorted(dupes)}")

    edges = []
    for i, t in enumerate(d.get("edge", [])):
        w = f"{where} [[edge]] #{i}"
        _table(t, w, {"from": str, "to": str, "style": str}, {"budget_bytes": int})
        for endpoint in (t["from"], t["to"]):
            if endpoint not in ids:
                raise SchemaError(f"{w}: scene '{endpoint}' not declared "
                                  f"(scenes: {ids})")
        if t["style"] not in EDGE_STYLES:
            raise SchemaError(f"{w}: unknown style '{t['style']}' "
                              f"(styles: {list(EDGE_STYLES)})")
        edges.append(EdgeDecl(src=t["from"], dst=t["to"], style=t["style"],
                              budget_bytes=t.get("budget_bytes")))
    return GameManifest(globals_=globals_, scenes=tuple(scenes), edges=tuple(edges))
