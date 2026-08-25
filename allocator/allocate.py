#!/usr/bin/env python3
"""superforge — the declarative resource allocator.

I/O contract: allocate(substrate, features, user_state, manifest) -> Allocation,
or raise AllocationError with a legible diagnostic (the CLI exits non-zero and
the Make recipe treats that as a build failure — the collision gate's teeth).

Algorithm:
  1. resolve deps        expand each scene's feature set through `depends`
  2. reserve globals     global features + global user state, placed once,
                         subtracted from every scene's budget
  3. per scene           place engine + user claims per resource class
                         (most-constrained-first greedy; correctness of the
                         model matters more than search sophistication)
  4. per edge            verify the A->B reload fits the transition budget
  5. verify              belt-and-suspenders overlap/alignment/budget re-check,
                         independent of the solver's bookkeeping
  6. emit                build/engine_state_<scene>.inc + allocation_report.txt
                         + symbol_map.json (feeds no_literals.py)

Address conventions: VRAM in words, CGRAM in words, OAM in sprite slots,
DP/WRAM/ROM in bytes. WRAM placements are absolute offsets into the 128 KB
($7E:0000-based); emitted symbols carry bank + 16-bit offset + 24-bit long.
ROM placements are (bank-window index, offset) pairs; window capacity is the
LoROM 32 KB DMA window. ROM capacity is not bounded by the substrate (the
linker config owns real cartridge size); the report lists windows used.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schemas import (BLEND_REGS, MATH_LAYERS, REGISTER_FOOTPRINT,  # noqa: E402
                     SCREEN_LAYERS, SCREEN_REGS, WINDOW_MODES,
                     BytesClaim, DmaInitClaim,
                     FeatureDecl, GameManifest, HdmaClaim, RegClaim,
                     SchemaError, StateDecl, StateVar, Substrate, VramClaim,
                     load_feature, load_manifest, load_state, load_substrate)


class AllocationError(ValueError):
    """The declared game does not fit. Message is the legible diagnostic."""


GLOBAL = "<global>"     # scope tag for game-lifetime placements


@dataclass(frozen=True)
class Placement:
    """One resolved claim: [start, start+size) in its class's address space."""
    name: str            # claim name (emitted symbol derives from this)
    cls: str             # dp | wram | vram | cgram | oam | rom
    start: int
    size: int            # in the class's units (words for vram/cgram)
    scope: str           # GLOBAL or scene id
    consumer: str        # "engine:<feature>" | "user"
    kind: str = ""       # vram: tilemap/chr/mode7/raw; rom: chunk suffix
    # rom only: the claim's declared out-of-scope backing statement, carried
    # into symbol_map.json so no_literals' rom-backing gate (docs/37) can see
    # the exemption without re-reading feature.toml. Empty = the default rule
    # (an in-scope .incbin claim site must exist).
    backed_by: str = ""

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass(frozen=True)
class ChannelAssign:
    name: str
    channel: int
    registers: tuple[str, ...]
    band: tuple[int, int]
    phase: str
    scope: str
    consumer: str
    bbad: int = 0       # B-bus low byte, derived from registers[0]
    dmap: int = 0       # transfer mode + indirect flag


@dataclass
class SceneMap:
    scene: str
    placements: list[Placement] = field(default_factory=list)
    channels: list[ChannelAssign] = field(default_factory=list)
    vblank_bytes: int = 0
    vblank_transfers: int = 0       # queued GP-DMAs/frame, each paying arm cost
    init_zero: list[str] = field(default_factory=list)   # claim names to zero
    dma_inits: list[tuple] = field(default_factory=list)  # (claim, scope, who)
    regs: list[tuple] = field(default_factory=list)       # (RegClaim, who) — C4
    # C5: the scene's composed screen/blend vocabulary (compose_screen_blend's
    # dict), or None where the scene carries no vocabulary claim. The
    # synthesized ownership claim it implies ALSO sits in `regs`, which is
    # how it reaches check_reg_ownership, the report, and the symbol map.
    screen_blend: dict | None = None


@dataclass
class Allocation:
    substrate: Substrate
    globals_map: list[Placement]
    global_channels: list[ChannelAssign]
    scenes: dict[str, SceneMap]
    edge_reloads: list[tuple[str, str, int, int | None]]  # (src, dst, bytes, budget)
    globals_init_zero: list[str] = field(default_factory=list)  # global claims to zero at boot
    global_dma_inits: list[tuple] = field(default_factory=list)  # (claim, scope, who)
    global_regs: list[tuple] = field(default_factory=list)       # (RegClaim, who) — C4
    # C1: the single program-wide SPC RAM occupant, or None. (feature, claim,
    # sorted scopes it was declared in) — check_spc_exclusivity guarantees <= 1.
    spc_owner: tuple[str, str, list[str]] | None = None
    #: the declared transition style per edge, (src, dst, style,
    # dst_scene_index). Carried separately from edge_reloads because it is
    # SYMBOL input rather than budget bookkeeping — emit() turns it into the
    # `ES_E_*` block the SM_SWITCH macro resolves its call against, which is
    # what makes `style` load-bearing instead of a report string.
    edge_styles: list[tuple[str, str, str, int]] = field(default_factory=list)


# --------------------------------------------------------------------------
# interval free-list
# --------------------------------------------------------------------------

class FreeList:
    """Sorted disjoint free intervals [start, end) over one address space."""

    def __init__(self, start: int, end: int):
        self.free: list[tuple[int, int]] = [(start, end)]

    def carve(self, start: int, size: int) -> bool:
        """Reserve [start, start+size) if wholly free; False otherwise."""
        end = start + size
        for i, (a, b) in enumerate(self.free):
            if a <= start and end <= b:
                repl = []
                if a < start:
                    repl.append((a, start))
                if end < b:
                    repl.append((end, b))
                self.free[i:i + 1] = repl
                return True
        return False

    def fit(self, size: int, align: int = 1, min_start: int = 0,
            max_end: int | None = None, no_cross: int | None = None) -> int | None:
        """First aligned fit >= min_start; None if nothing fits.

        no_cross: block size whose multiples the placement must not straddle
        (the DMA bank rule). max_end: exclusive ceiling on the placement end.
        """
        for a, b in self.free:
            lo = max(a, min_start)
            start = (lo + align - 1) // align * align
            while True:
                end = start + size
                if end > b or (max_end is not None and end > max_end):
                    break
                if no_cross is not None and start // no_cross != (end - 1) // no_cross:
                    # snap to the next bank boundary and retry within this hole
                    nb = (start // no_cross + 1) * no_cross
                    start = (nb + align - 1) // align * align
                    continue
                assert self.carve(start, size)
                return start
        return None


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _register_conflicts(a_names, b_names) -> list[str]:
    """Declared names from two claims whose PHYSICAL footprints intersect.

    Replaces the old `set(a.registers) & set(b.registers)`. Name equality was
    not enough in either direction:

      - identical names still resolve to the same port, so the common case is
        unchanged and reports the same way ("both drive ['BGMODE']");
      - DIFFERENT names can be intersecting silicon. COLDATA_R is one plane of
        the COLDATA port, so a plane claim and a whole-port claim contend even
        though the strings differ. Name equality missed that entirely — the
         sub-register hole — and reported such a pair as composing.

    Reported as "A~B" when the names differ, so the diagnostic says *why* two
    unlike names collide instead of looking like a bug in the checker.
    """
    out: set[str] = set()
    for na in a_names:
        port_a, mask_a = REGISTER_FOOTPRINT[na]
        for nb in b_names:
            port_b, mask_b = REGISTER_FOOTPRINT[nb]
            if port_a == port_b and (mask_a & mask_b):
                out.add(na if na == nb else f"{na}~{nb} (${port_a:04X})")
    return sorted(out)


def check_reg_ownership(reg: list[tuple], hdma: list[tuple],
                        dma_init: list[tuple], scope: str) -> None:
    """C4: a CPU-written register has ONE owner per scene (docs/09 §2.1).

    `reg`/`hdma` are [(claim, who)]; `dma_init` is [(claim, scope, who)]. All
    three must be the UNION of globals and this scene's features, for the same
    reason the HDMA pre-pass takes `reserved` — scene_mgr owns INIDISP and
    NMITIMEN globally, and a scene-scoped second writer must still refuse (F2,
    the cross-scope silent-composition hole).

    PHASE-BLIND ON PURPOSE, and this is the design decision of the class: see
    RegClaim's docstring for why `_register_exclusive`'s rule is HDMA-specific
    and would let the hardware-multiplier defect through the class built to
    catch it. Do not "unify" the two passes.

    Three checks:
      1. reg x reg  — any intersecting footprint refuses. No same-feature
         exemption: two claims of one feature fighting over a port is still a
         bug, and no such pair exists in the tree to grandfather.
      2. reg x (hdma | dma_init) — an owner refuses against a transfer claim
         on its port, because a per-scanline or per-frame transfer DESTROYS the
         persistent value the CPU write established. This is what catches
         window_iris's COLDATA subtract constant against rgb_gradient's
         per-line COLDATA planes, a conflict no phase model can see.
      3. seed validity — `seed` exempts (2) for hdma only, and a seed with
         nothing overriding it is a declaration that lies.
    """
    for i, (a, wa) in enumerate(reg):
        for b, wb in reg[i + 1:]:
            shared = _register_conflicts(a.registers, b.registers)
            if shared:
                if _is_vocab_who(wa) != _is_vocab_who(wb):
                    # R6 — vocabulary mixing. One side is the scene's
                    # synthesized screen/blend composition; the other is a
                    # raw [[claims.reg]] on a port the composition owns. The
                    # refusal is this same intersection — the vocabulary is
                    # just another claimant — but the FIX is different, so
                    # the message is too.
                    (rc, rw) = (a, wa) if _is_vocab_who(wb) else (b, wb)
                    (vc, vw) = (b, wb) if _is_vocab_who(wb) else (a, wa)
                    raise AllocationError(
                        f"REGISTER ownership contention in scene '{scope}': "
                        f"{rc.name} ({rw}) claims {shared} as a raw "
                        f"[[claims.reg]], but this scene also composes the "
                        f"screen/blend vocabulary over the same port "
                        f"({vc.name}, {vw}) — two vocabularies, one "
                        f"write-only port. Every writer of a write-only "
                        f"register supplies the WHOLE byte, so the raw "
                        f"value and the composed value cannot both hold. "
                        f"Move the raw claim into the vocabulary: a TM/TS "
                        f"designation becomes [[claims.screen]] (layer, on) "
                        f"on the feature that owns the layer; CGWSEL/"
                        f"CGADSUB programming becomes [[claims.blend]] "
                        f"(docs/99)")
                raise AllocationError(
                    f"REGISTER ownership contention in scene '{scope}': "
                    f"{a.name} ({wa}) and {b.name} ({wb}) both write {shared} "
                    f"— a CPU-written register has one owner per scene. If one "
                    f"of these only seeds a base value that a declared hdma "
                    f"claim overwrites, mark it `seed = true` (docs/09 §2.1)")

    xfer = [(c, who, "hdma") for c, who in hdma] + \
           [(c, who, "dma_init") for c, _, who in dma_init]
    for a, wa in reg:
        overriders = []
        for c, wc, kind in xfer:
            shared = _register_conflicts(a.registers, c.registers)
            if not shared:
                continue
            if a.seed and kind == "hdma":
                overriders.append(f"{c.name} ({wc})")
                continue
            if _is_vocab_who(wa):
                # The reg side is the synthesized screen/blend composition.
                # It has no `seed` for an author to mark, on purpose: the
                # vocabulary has no per-scanline story (a stated limit).
                hint = ("The screen/blend vocabulary has no per-scanline "
                        "story — a per-scanline rewrite of these ports "
                        "keeps the RAW claim shape (a [[claims.reg]] with "
                        "`seed = true` beside the hdma claim), in a scene "
                        "that does not compose the vocabulary on them")
            else:
                hint = ("A dma_init is a one-shot enter-time ESTABLISHER, "
                        "not an ongoing overrider, so `seed` does not "
                        "exempt it"
                        if kind == "dma_init" else
                        "If the transfer is meant to overwrite this base "
                        "value, mark the reg claim `seed = true`")
            raise AllocationError(
                f"REGISTER ownership contention in scene '{scope}': {a.name} "
                f"({wa}) CPU-writes {shared} but {c.name} ({wc}) also drives "
                f"it as a claims.{kind} transfer — the transfer overwrites the "
                f"value the CPU write establishes. {hint} (docs/09 §2.1)")
        if a.seed and not overriders:
            raise AllocationError(
                f"REGISTER claim '{a.name}' ({wa}) in scene '{scope}' declares "
                f"`seed = true` but no claims.hdma claim in this scene drives "
                f"{list(a.registers)} — a seed says 'another declared claim "
                f"overwrites this base value', and nothing here does. Either "
                f"drop `seed` (making this the owner) or the overriding "
                f"feature is missing from the scene (docs/09 §2.1)")


# --------------------------------------------------------------------------
# the screen/blend vocabulary — per-scene composition (C5)
# --------------------------------------------------------------------------

# The synthesized composed claim's consumer tag. check_reg_ownership keys its
# vocabulary-mixing diagnostic (R6) off this prefix, so the refusal arises
# from the SAME reg-x-reg intersection every raw pair goes through — the
# vocabulary is just another claimant of its ports, not a special-cased lint.
VOCAB_WHO = "screen/blend"

# A BG layer's designation usually belongs to the feature that owns the
# layer's base registers. Not provably — split designator/owner shapes are
# conceivable — so the cross-check below WARNS rather than refuses.
_LAYER_REGS = {"bg1": ("BG1SC", "BG12NBA"), "bg2": ("BG2SC", "BG12NBA"),
               "bg3": ("BG3SC", "BG34NBA"), "bg4": ("BG4SC", "BG34NBA")}


def _is_vocab_who(who: str) -> bool:
    return who.startswith(VOCAB_WHO)


def compose_screen_blend(screen: list[tuple], blend: list[tuple],
                         reg: list[tuple], scope: str) -> dict | None:
    """Compose a scene's screen/blend claims, or REFUSE (R1-R5).

    `screen`/`blend`/`reg` are [(claim, who)] over the globals+scene UNION —
    the check_reg_ownership convention, for the same reason (F2: a global
    designation and a scene-scoped second designation must still refuse).
    Returns None when the scene carries no vocabulary claim; else the
    composed dict: the four register values, the registers the synthesized
    ownership claim holds, warnings for the allocation report, and the
    refusal-check census. Refusal messages name the claiming features and
    the hardware mechanism — the messages are the deliverable.
    """
    if not screen and not blend:
        return None
    checks = 0

    # R1 — the same layer designated twice. Ownership, not the value, is the
    # resource, so identical `on` still refuses (the RegClaim rule).
    if len(screen) >= 2:
        checks += 1
    owners: dict[str, tuple] = {}
    for c, who in screen:
        if c.layer in owners:
            p, pwho = owners[c.layer]
            agree = " — even though they agree" if p.on == c.on else ""
            raise AllocationError(
                f"SCREEN designation contention in scene '{scope}': "
                f"{p.name} ({pwho}) designates {c.layer} -> {p.on} and "
                f"{c.name} ({who}) designates {c.layer} -> {c.on}{agree}. "
                f"A layer's screen designation is a binding with one owner: "
                f"TM/TS hold one enable bit per layer, and the OWNERSHIP of "
                f"that bit, not its value, is the resource — the same rule "
                f"[[claims.reg]] applies to whole ports. One feature "
                f"designates a layer; a second feature that needs it on "
                f"screen depends on the first")
        owners[c.layer] = (c, who)

    # R2 — one blender. The global fields are per-frame hardware singletons:
    # CGADSUB bit 7 is one add/subtract select for the whole screen, bit 6
    # one halve, CGWSEL bit 1 one addend source, bits 7-6 one clip mode and
    # bits 5-4 one prevent mode.
    if len(blend) >= 2:
        checks += 2                      # R2 + R3 live
        (g, gwho) = blend[0]
        for c, who in blend[1:]:
            for fld in ("op", "half", "source", "clip", "prevent"):
                va, vb = getattr(g, fld), getattr(c, fld)
                if va != vb:
                    raise AllocationError(
                        f"BLEND contention in scene '{scope}': {g.name} "
                        f"({gwho}) declares {fld} = {va!r} and {c.name} "
                        f"({who}) declares {fld} = {vb!r}. The PPU has ONE "
                        f"color-math unit — CGADSUB bit 7 is one add/"
                        f"subtract select for the whole screen, bit 6 one "
                        f"halve, CGWSEL bit 1 one addend source, bits 7-4 "
                        f"one clip and one prevent mode — so every global "
                        f"field must agree across a scene's blend claims. "
                        f"What composes is `math`: each claim gates its own "
                        f"layers in")
        # R3 — one enable bit per math layer, one owner (the R1 rule on the
        # CGADSUB axis).
        m_owners: dict[str, tuple] = {}
        for c, who in blend:
            for m in c.math:
                if m in m_owners:
                    p, pwho = m_owners[m]
                    raise AllocationError(
                        f"BLEND math contention in scene '{scope}': {p.name} "
                        f"({pwho}) and {c.name} ({who}) both gate '{m}' "
                        f"into the color math. CGADSUB holds one enable bit "
                        f"per layer, and the bit's ownership is the "
                        f"resource — one owner per scene, the same rule as "
                        f"a layer's screen designation")
                m_owners[m] = (c, who)

    mains = {c.layer for c, _ in screen if c.on in ("main", "both")}
    subs = {c.layer for c, _ in screen if c.on in ("sub", "both")}
    warnings: list[str] = []

    if blend:
        checks += 2                      # R4 + R5 live
        g, gwho = blend[0]
        # R4 — a sub-screen blend needs a sub screen. Where the sub screen
        # holds no pixel the hardware substitutes the FIXED COLOR and
        # disables halving (Mesen2 SnesPpu.cpp ApplyColorMathToPixel,
        # :1352-1362), so a sub-source blend in a scene with no
        # sub-designated layer never sees its declared source.
        if g.source == "sub" and not subs:
            raise AllocationError(
                f"BLEND source contention in scene '{scope}': {g.name} "
                f"({gwho}) declares source = \"sub\" but no layer in this "
                f"scene is designated to the sub screen. Where the sub "
                f"screen has no pixel the hardware substitutes the FIXED "
                f"COLOR and disables halving (Mesen2 SnesPpu.cpp "
                f"ApplyColorMathToPixel), so this blend would never see its "
                f"declared source — a declaration that lies. Designate a "
                f"layer on = \"sub\" with a [[claims.screen]] claim, or "
                f"declare source = \"fixed\"")
        # R5 — math gates MAIN-screen pixels by their winning layer, so an
        # enable bit for a layer that is not on the main screen is inert.
        # backdrop is exempt: it is always the main screen's floor.
        for c, who in blend:
            for m in c.math:
                if m != "backdrop" and m not in mains:
                    raise AllocationError(
                        f"BLEND math contention in scene '{scope}': {c.name} "
                        f"({who}) gates '{m}' into the color math, but no "
                        f"[[claims.screen]] claim in this scene designates "
                        f"{m} to the MAIN screen. Color math gates a MAIN-"
                        f"screen pixel by its winning layer, so the enable "
                        f"bit for a layer that is not main-designated is "
                        f"inert — set, and no pixel ever qualifies through "
                        f"it. Designate {m} on = \"main\" (or \"both\"); a "
                        f"raw TM claim cannot satisfy this — the "
                        f"composition can only prove what the vocabulary "
                        f"declares")

    # -- warnings: real hardware behaviour the author must know, not
    # refusals -------------------------------------------------------------
    math_union = {m for c, _ in blend for m in c.math}
    if "obj" in math_union:
        warnings.append(
            "OBJ in math: only sprite palettes 4-7 participate — CGADSUB "
            "bit 4 admits an OBJ pixel only when its palette index is > 3 "
            "(Mesen2 SnesPpu.cpp:962); palettes 0-3 opt out per sprite")
    if "obj" in subs:
        warnings.append(
            "OBJ designated to the sub screen: sprites become blend SOURCE "
            "material — wherever math fires, a sub-screen sprite pixel is "
            "the blender's second operand")
    for layer, (c, who) in sorted(owners.items()):
        for reg_name in _LAYER_REGS.get(layer, ()):
            for rc, rwho in reg:
                if _is_vocab_who(rwho) or rwho == who:
                    continue
                if reg_name in rc.registers:
                    warnings.append(
                        f"{layer} is designated by {c.name} ({who}) but its "
                        f"{reg_name} is claimed by {rc.name} ({rwho}) — the "
                        f"designator should usually own the layer it puts "
                        f"on screen (a split designator/owner shape is "
                        f"conceivable, so this is a warning, not a refusal)")

    # -- the composed values ------------------------------------------------
    tm = ts = 0
    for c, _ in screen:
        bit = 1 << SCREEN_LAYERS[c.layer]
        if c.on in ("main", "both"):
            tm |= bit
        if c.on in ("sub", "both"):
            ts |= bit
    if blend:
        g, _ = blend[0]
        cgadsub = ((0x80 if g.op == "sub" else 0)
                   | (0x40 if g.half else 0))
        for m in sorted(math_union):
            cgadsub |= 1 << MATH_LAYERS[m]
        cgwsel = ((WINDOW_MODES[g.clip] << 6)
                  | (WINDOW_MODES[g.prevent] << 4)
                  | (0x02 if g.source == "sub" else 0))
        # CGWSEL bit 0 (direct color) composes 0 — a stated limit: direct
        # color stays out of the vocabulary, expressible as a raw CGWSEL
        # claim in a scene with no blend claims.
    else:
        # Screen claims with no blend: the explicit OFF state
        # vendor/rom/ppu_reset.inc establishes at boot — prevent = always
        # ($30) structurally disables the math, CGADSUB gates nothing.
        cgwsel, cgadsub = 0x30, 0x00

    regs = ((SCREEN_REGS if screen else ())
            + (BLEND_REGS if blend else ()))
    feats = sorted({who for _, who in [*screen, *blend]})
    return {"tm": tm, "ts": ts, "cgwsel": cgwsel, "cgadsub": cgadsub,
            "registers": regs, "features": feats,
            "screen": [(c, who) for c, who in screen],
            "blend": [(c, who) for c, who in blend],
            "warnings": warnings,
            "designations": len(screen), "blends": len(blend),
            "checks": checks}


def check_spc_exclusivity(global_feats, scene_feats) -> tuple[str, str, list[str]] | None:
    """C1: SPC RAM (all 64 KiB of it) has ONE occupant per PROGRAM.

    PROGRAM-WIDE, NOT PER-SCENE — the one place this class differs from every
    other check in this file, and the load-bearing design decision: the
    occupant's driver is initialised once per power-on (TAD's Tad_Init
    hardlocks on a second call) and its Audio-RAM upload persists across
    scene transitions, so two features holding spc in DIFFERENT scenes — or
    one global and one scene-scoped — still corrupt each other at runtime.
    A per-scene union check (check_reg_ownership's shape) would pass exactly
    the cross-scene composition that breaks on hardware.

    PRESENCE-ONLY on the same reasoning as SpcClaim's docstring: the
    occupant's own toolchain packs the space and refuses over-budget
    compositions at build time; this check is the BOUNDARY —
    the claim-shaped form of tad-audio.inc:49's "must be the only code that
    accesses $2140-$2143", which nothing else enforces.

    Returns the single owner as (feature, claim, sorted scopes) or None, for
    the symbol map — no symbol is emitted (ownership classes are checks, not
    layouts; the reg class is the precedent).
    """
    holders: dict[str, tuple[str, set[str]]] = {}
    for f in global_feats:
        for c in f.spc:
            holders.setdefault(f.name, (c.name, set()))[1].add("globals")
    for sid, feats in scene_feats.items():
        for f in feats:
            for c in f.spc:
                holders.setdefault(f.name, (c.name, set()))[1].add(f"scene '{sid}'")
    if len(holders) > 1:
        detail = "; ".join(
            f"{feat} (claim '{cn}', declared in {', '.join(sorted(scopes))})"
            for feat, (cn, scopes) in sorted(holders.items()))
        raise AllocationError(
            f"SPC RAM occupancy contention: {detail} — the audio CPU's 64 KiB "
            f"is owner-exclusive and PROGRAM-wide: one occupant per game "
            f"across ALL scenes, because the driver is initialised once per "
            f"power-on and packs the whole space. Two occupants cannot be "
            f"composed by scene separation.")
    for feat, (cn, scopes) in holders.items():
        return (feat, cn, sorted(scopes))
    return None


def place_sram(global_feats, scene_feats, sub: Substrate) -> list[Placement]:
    """C2: battery-backed cart RAM — the first PROGRAM-wide region PACKER.

    PROGRAM-WIDE like check_spc_exclusivity, a PACKER like place_bytes — the
    third placement shape: `spc` is program-wide but a check;
    `wram` packs but per-scene (each scene's free list forks the globals' —
    reuse across scenes is the feature). SRAM must be both at once, because
    its contents outlive not just the scene but the POWER: a scene-scoped
    reuse of a persistent byte is a save that corrupts itself. So ONE free
    list spans the union of every feature's sram claims across globals + all
    scenes, deduped by feature name (the spc holders pattern — a feature
    composed into three scenes places its claim once), placed once, and the
    placements join the GLOBALS map so symbols emit once in the globals inc
    (: "global (persistent; the SRAM-backed subset = 'save
    state')").

    Placement itself is place_bytes verbatim: pins carve first, deterministic
    largest-first packing, complete blame lists on refusal. Layout stability
    across builds is the save FORMAT's job — a moved layout is detected-
    invalid via magic/version/CRC, never silently mis-read; a game wanting
    manual stability pins with `at`.
    """
    seen: set[str] = set()
    claims: list[tuple[BytesClaim, str]] = []
    for f in global_feats:
        seen.add(f.name)
        claims += [(c, f"engine:{f.name}") for c in f.sram]
    for feats in scene_feats.values():
        for f in feats:
            if f.name in seen:
                continue
            seen.add(f.name)
            claims += [(c, f"engine:{f.name}") for c in f.sram]
    if not claims:
        return []
    fl = FreeList(0, sub.sram_bytes)
    return place_bytes("sram", claims, GLOBAL, fl, sub.sram_bytes)


def sram_header_bytes(placements: list[Placement],
                      sub: Substrate) -> tuple[int, int] | None:
    """Derive the cart header's ($FFD8 size, $FFD6 type) from packed demand.

    : the header byte is a pure FUNCTION of the claims, so
    "what the cart declares" and "what the game writes" cannot disagree —
    the exact bug C2 names. No claims -> None (emit nothing; the
    header.inc defaults hold at $00/$00 and claim-less ROMs stay
    byte-identical). Else the smallest exponent N >= 1 with 1024<<N >=
    demand — $FFD8 = N, $FFD6 = $02 (ROM+RAM+battery; Mesen persists on the
    size byte alone but bsnes and real hardware read the chipset byte, so
    BOTH are driven — settlement §2.4/§3.3).
    """
    total = sum(p.size for p in placements if p.cls == "sram")
    if total == 0:
        return None
    n = 1
    while (1024 << n) < total:
        n += 1
    if (1024 << n) > sub.sram_bytes:
        # Unreachable while the substrate cap is itself a power-of-two window
        # (place_bytes refuses > sram_bytes first); kept so a future cap that
        # is not a representable size fails loudly instead of shipping a
        # header that declares more SRAM than the model allows.
        raise AllocationError(
            f"SRAM header derivation: demand {total} B rounds up to "
            f"{1024 << n} B (1024<<{n}), which exceeds the substrate's "
            f"{sub.sram_bytes} B window — the cart cannot declare it")
    return n, 0x02


def _xfer_of(assigns) -> list[tuple]:
    """ChannelAssigns -> the [(claim-like, who)] shape check_reg_ownership takes.

    A multi-channel claim appears once per channel, so dedupe on (name,
    consumer, registers) — otherwise one claim would be reported N times.
    """
    seen, out = set(), []
    for ca in assigns:
        k = (ca.name, ca.consumer, ca.registers)
        if k not in seen:
            seen.add(k)
            out.append((ca, ca.consumer))
    return out


def _register_exclusive(phase: str) -> bool:
    """Does this phase give a claim EXCLUSIVE ownership of its registers?

    Only while the display is active. Two HDMA channels driving one register
    on the same scanline genuinely fight, and no channel shuffle can fix it —
    that is the class split-mode died on, and it stays a build-stopping error.

    VBlank-phase claims are not concurrent owners: they are queue entries the
    NMI hook fires one after another (mode7_stream already drives 16
    back-to-back VMDATAL transfers through a single claim, and the NMI core
    re-arms every channel from the scene_mgr shadow afterwards). Serialised
    writers to one register compose by construction, so demanding register
    exclusivity there is a FALSE NEGATIVE — it refused, for instance, leading-
    edge streaming plus any second VBlank VRAM upload in the same scene.

    What still binds a vblank claim, so the gate keeps its teeth: it occupies
    a channel number for its phase (place_channels' occupancy check, which
    also makes the 8-channel pool bind), and its cost is charged against the
    MEASURED byte + per-transfer arm budget in claims.dma.
    """
    return phase == "active"


# --------------------------------------------------------------------------
# feature resolution
# --------------------------------------------------------------------------

def resolve_features(names: tuple[str, ...], features: dict[str, FeatureDecl],
                     where: str) -> list[FeatureDecl]:
    """Expand a feature list through `depends`, stable order, cycle-safe."""
    out: list[FeatureDecl] = []
    seen: set[str] = set()
    visiting: list[str] = []

    def visit(n: str):
        if n in seen:
            return
        if n in visiting:
            cycle = " -> ".join([*visiting[visiting.index(n):], n])
            raise AllocationError(f"{where}: dependency cycle: {cycle}")
        if n not in features:
            raise AllocationError(
                f"{where}: unknown feature '{n}' (known: {sorted(features)})")
        visiting.append(n)
        for dep in features[n].depends:
            visit(dep)
        visiting.pop()
        seen.add(n)
        out.append(features[n])

    for n in names:
        visit(n)
    return out


# --------------------------------------------------------------------------
# per-class placement
# --------------------------------------------------------------------------

def _fail_over_budget(cls: str, scope: str, claims: list[tuple[str, int]],
                      budget: int, unit: str):
    """Raise the over-budget diagnostic. `claims` must be EVERY contributing
    claim of the class in this scope (globals + all features + user state),
    not just the one that failed to place — the shortfall arithmetic and the
    blame list are only correct over the complete set (F3)."""
    total = sum(sz for _, sz in claims)
    detail = " + ".join(f"{n}({sz})" for n, sz in claims)
    if total > budget:
        raise AllocationError(
            f"{cls.upper()} over budget in scene '{scope}' by {total - budget} "
            f"{unit}: {detail} exceeds {budget}")
    # totals fit but no hole does: alignment/pinning/bank constraints
    # fragment the space — say so rather than print a negative "shortfall"
    raise AllocationError(
        f"{cls.upper()} placement infeasible in scene '{scope}': {detail} "
        f"totals {total} of {budget} {unit}, but alignment/pinning/bank "
        f"constraints leave no hole that fits")


def place_vram(claims: list[tuple[VramClaim, str]], sub: Substrate, scope: str,
               fl: FreeList,
               reserved: list[tuple[str, int]] = ()) -> list[Placement]:
    """claims: [(claim, consumer)]. Mutates fl (the scene's VRAM space).
    reserved: already-placed (global) claims of this class, named in
    over-budget blame lists so the arithmetic covers every contributor."""
    out: list[Placement] = []
    aligns = {"tilemap": sub.tilemap_align_words, "chr": sub.chr_align_words,
              "mode7": sub.mode7_region_words, "raw": 1}
    has_mode7 = any(c.kind == "mode7" for c, _ in claims)

    def align_of(c: VramClaim) -> int:
        return sub.obj_chr_align_words if (c.kind == "chr" and c.obj) else aligns[c.kind]

    # pinned first (hardware contracts), then most-constrained (align, size desc)
    pinned = [(c, who) for c, who in claims if c.at is not None or c.kind == "mode7"]
    packed = [(c, who) for c, who in claims if c.at is None and c.kind != "mode7"]
    for c, who in pinned:
        at = sub.mode7_base_word if c.kind == "mode7" else c.at
        al = align_of(c)
        if at % al:
            raise AllocationError(
                f"VRAM claim '{c.name}' ({who}) pinned at ${at:04X} violates its "
                f"{c.kind} alignment of ${al:04X} words — the hardware cannot "
                f"express this base")
        if at + c.words > sub.vram_words:
            raise AllocationError(
                f"VRAM claim '{c.name}' ({who}) pinned at ${at:04X}+{c.words} words "
                f"runs past the ${sub.vram_words:04X}-word VRAM (VMADD wraps at "
                f"bit 15 — reduce the base mod ${sub.vram_addr_mask + 1:04X})")
        if not fl.carve(at, c.words):
            holder = next((p for p in out if _overlaps((at, at + c.words),
                                                       (p.start, p.end))), None)
            with_ = (f"{holder.name} ({holder.consumer}) at "
                     f"[${holder.start:04X}..${holder.end:04X})" if holder
                     else "an already-reserved region")
            raise AllocationError(
                f"VRAM overlap in scene '{scope}': {c.name} ({who}) pinned at "
                f"[${at:04X}..${at + c.words:04X}) collides with {with_}")
        out.append(Placement(c.name, "vram", at, c.words, scope, who,
                             "chr_obj" if (c.kind == "chr" and c.obj)
                             else c.kind))

    packed.sort(key=lambda t: (-align_of(t[0]), -t[0].words, t[0].name))
    for c, who in packed:
        min_start = (sub.mode7_obj_chr_floor_word
                     if (has_mode7 and c.kind == "chr" and c.obj) else 0)
        at = fl.fit(c.words, align_of(c), min_start=min_start)
        if at is None:
            _fail_over_budget("vram", scope,
                              [*reserved, *((x.name, x.words) for x, _ in claims)],
                              sub.vram_words, "words")
        out.append(Placement(c.name, "vram", at, c.words, scope, who,
                             "chr_obj" if (c.kind == "chr" and c.obj)
                             else c.kind))
    return out


def place_bytes(cls: str, claims: list[tuple[BytesClaim, str]], scope: str,
                fl: FreeList, budget: int, unit: str = "B",
                bank_bytes: int | None = None,
                reserved: list[tuple[str, int]] = ()) -> list[Placement]:
    out = []
    # Pinned claims carve their exact range FIRST, so a pin can never be
    # displaced by packing order — and a pin that lands on anything already
    # placed (system-reserved low, an earlier global, another pin) refuses
    # with the pin named. The free-list is the arbiter, same as fit().
    pinned = [(c, who) for c, who in claims if c.at is not None]
    for c, who in sorted(pinned, key=lambda t: (t[0].at, t[0].name)):
        no_cross = bank_bytes if (bank_bytes and c.dma_source) else None
        if no_cross and (c.at // no_cross) != ((c.at + c.bytes - 1) // no_cross):
            raise AllocationError(
                f"{cls} claim '{c.name}' ({who}, {scope}): pinned at "
                f"${c.at:04X}..${c.at + c.bytes:04X} crosses a "
                f"{no_cross // 1024} KB bank boundary and is a DMA source")
        if not fl.carve(c.at, c.bytes):
            raise AllocationError(
                f"{cls} claim '{c.name}' ({who}, {scope}): pinned range "
                f"${c.at:04X}..${c.at + c.bytes:04X} is not free — it "
                f"overlaps an earlier placement, another pin, or the "
                f"system-reserved region. The allocation report shows the "
                f"live {cls} layout; move the pin to a free range")
        out.append(Placement(c.name, cls, c.at, c.bytes, scope, who))
    ordered = sorted(((c, who) for c, who in claims if c.at is None),
                     key=lambda t: (-t[0].bytes, t[0].name))
    for c, who in ordered:
        no_cross = bank_bytes if (bank_bytes and c.dma_source) else None
        at = fl.fit(c.bytes, 1, no_cross=no_cross)
        if at is None:
            _fail_over_budget(cls, scope,
                              [*reserved, *((x.name, x.bytes) for x, _ in claims)],
                              budget, unit)
        out.append(Placement(c.name, cls, at, c.bytes, scope, who))
    return out


def place_state_vars(vars_: tuple[StateVar, ...], scope: str, dp_fl: FreeList,
                     wram_fl: FreeList, sub: Substrate,
                     dp_declared: list[tuple[str, int]],
                     wram_declared: list[tuple[str, int]]) -> list[Placement]:
    out = []
    # complete blame lists (F3): a failure names every same-class state var
    # in this call plus everything already placed (dp_declared/wram_declared
    # carry the engine + globals placements)
    all_vars = {"dp": [(v.name, v.size) for v in vars_ if v.place == "dp"],
                "wram": [(v.name, v.size) for v in vars_ if v.place != "dp"]}
    for v in sorted(vars_, key=lambda v: (-v.size, v.name)):
        if v.place == "dp":
            at = dp_fl.fit(v.size)
            if at is None:
                _fail_over_budget("dp", scope, dp_declared + all_vars["dp"],
                                  sub.dp_bytes, "B")
            out.append(Placement(v.name, "dp", at, v.size, scope, "user"))
        else:
            at = wram_fl.fit(v.size)
            if at is None:
                _fail_over_budget("wram", scope, wram_declared + all_vars["wram"],
                                  sub.wram_bytes - sub.wram_reserved_low, "B")
            out.append(Placement(v.name, "wram", at, v.size, scope, "user"))
    return out


def place_cgram(claims, scope, fl: FreeList, sub: Substrate,
                reserved: list[tuple[str, int]] = ()) -> list[Placement]:
    out = []
    pinned = [(c, w) for c, w in claims if c.at is not None]
    packed = [(c, w) for c, w in claims if c.at is None]
    for c, who in pinned:
        if not fl.carve(c.at, c.words):
            raise AllocationError(
                f"CGRAM overlap in scene '{scope}': {c.name} ({who}) pinned at "
                f"[{c.at}..{c.at + c.words}) words collides with another sub-palette")
        out.append(Placement(c.name, "cgram", c.at, c.words, scope, who))
    for c, who in sorted(packed, key=lambda t: (-t[0].words, t[0].name)):
        at = fl.fit(c.words, 16)     # sub-palettes live on 16-color boundaries
        if at is None:
            _fail_over_budget("cgram", scope,
                              [*reserved, *((x.name, x.words) for x, _ in claims)],
                              sub.cgram_words, "words")
        out.append(Placement(c.name, "cgram", at, c.words, scope, who))
    return out


def place_oam(claims, scope, fl: FreeList, sub: Substrate,
              reserved: list[tuple[str, int]] = ()) -> list[Placement]:
    out = []
    # Pinned slot ranges carve FIRST — the place_bytes shape (H3,
    # §2.6). OAM index order IS sprite-vs-sprite priority (lowest in front),
    # so where a claim lands is user-visible: an OBJ-HUD that must render
    # over the scene's sprites pins its range instead of relying on the
    # packing sort putting it there by accident. A pin that lands on
    # anything already placed — or past the 128-sprite table — refuses with
    # the pin named; the free list is the arbiter, same as fit().
    pinned = [(c, who) for c, who in claims if c.at is not None]
    for c, who in sorted(pinned, key=lambda t: (t[0].at, t[0].name)):
        if not fl.carve(c.at, c.sprites):
            raise AllocationError(
                f"OAM claim '{c.name}' ({who}, {scope}): pinned slot range "
                f"{c.at}..{c.at + c.sprites} is not free — it overlaps an "
                f"earlier placement, another pin, or runs past the "
                f"{sub.oam_sprites}-sprite table. The allocation report "
                f"shows the live OAM layout; move the pin to a free range")
        out.append(Placement(c.name, "oam", c.at, c.sprites, scope, who))
    for c, who in sorted(((c, w) for c, w in claims if c.at is None),
                         key=lambda t: (-t[0].sprites, t[0].name)):
        at = fl.fit(c.sprites)
        if at is None:
            _fail_over_budget("oam", scope,
                              [*reserved, *((x.name, x.sprites) for x, _ in claims)],
                              sub.oam_sprites, "sprites")
        out.append(Placement(c.name, "oam", at, c.sprites, scope, who))
    return out


def reserve_pinned_rom(claims: list[tuple], windows: list[FreeList],
                       sub: Substrate) -> dict[tuple[str, str], int]:
    """Reserve every PINNED rom claim in the WHOLE composition, before any free
    claim is placed anywhere. Returns {(scope, claim name): byte start}.

    `claims` is (RomClaim, who, scope) over globals AND every scene.

    THIS IS HOISTED OUT OF `place_rom` DELIBERATELY. ROM is physical, not
    scene-scoped, so `place_rom` runs once for globals and again per scene
    over ONE shared window list. A pinned
    pass living inside each call is therefore only a premise WITHIN that call:
    a scene-scoped pin — or scene B's pin against scene A's free claim — loses
    its window to whatever was placed first and surfaces as "another claim
    reached it first", which reads as a collision rather than as the packer
    failing to solve around a fixed point. Reserving here, once, over the whole
    composition, is what makes `RomClaim.window`'s docstring TRUE: the pin is
    the premise, not a preference it may lose. Latent when it was found (every
    rom claim in the tree is global today), but the unstated-ordering-assumption
    shape is exactly what produced the bug this field exists to fix.
    """
    win = sub.rom_window_bytes
    at_of: dict[tuple[str, str], int] = {}
    pinned = [t for t in claims if t[0].window is not None]
    for c, who, scope in sorted(pinned, key=lambda t: (t[0].window, t[0].name,
                                                       t[2])):
        if c.window < 0:
            raise AllocationError(
                f"ROM claim '{c.name}' ({who}) pins window {c.window}: a "
                f"window index must be non-negative")
        if c.bank_tiled or c.bytes > win:
            raise AllocationError(
                f"ROM claim '{c.name}' ({who}) pins window {c.window} but is "
                f"{c.bytes} B (window = {win} B) — a pin names ONE window, so "
                f"a claim that spans several cannot take one")
        if c.window < sub.rom_code_windows:
            raise AllocationError(
                f"ROM claim '{c.name}' ({who}) pins window {c.window}, which "
                f"belongs to the linker (CODE+RODATA occupy windows 0.."
                f"{sub.rom_code_windows - 1})")
        while len(windows) <= c.window:
            windows.append(FreeList(0, win))
        at = windows[c.window].fit(c.bytes)
        if at is None:
            raise AllocationError(
                f"ROM claim '{c.name}' ({who}) pins window {c.window}, which "
                f"has no room for {c.bytes} B — another claim reached it "
                f"first, or two claims pin the same window")
        at_of[(scope, c.name)] = c.window * win + at
    return at_of


def place_rom(claims, scope, windows: list[FreeList], sub: Substrate,
              pinned_at: dict[tuple[str, str], int]) -> list[Placement]:
    """Windows is a growable list of per-bank-window free lists (shared across
    scenes — ROM is physical, not scene-scoped).

    `pinned_at` carries the composition-wide reservations `reserve_pinned_rom`
    already made (and already validated), so this pass only records them as
    Placements; everything else first-fits largest-first around them.
    """
    out = []
    win = sub.rom_window_bytes
    pinned = [t for t in claims if t[0].window is not None]
    free = [t for t in claims if t[0].window is None]
    for c, who in sorted(pinned, key=lambda t: (t[0].window, t[0].name)):
        out.append(Placement(c.name, "rom", pinned_at[(scope, c.name)], c.bytes,
                             scope, who, backed_by=c.backed_by))
    for c, who in sorted(free, key=lambda t: (-t[0].bytes, t[0].name)):
        if c.bytes > win and c.dma_source and not c.bank_tiled:
            raise AllocationError(
                f"ROM claim '{c.name}' ({who}): {c.bytes} B exceeds the "
                f"{win} B LoROM DMA window and is a DMA source — a transfer "
                f"cannot span a bank (A1B is constant). Mark it bank_tiled "
                f"(pre-chunked) or split the asset")
        if c.bank_tiled and c.bytes > win:
            # A CONTIGUOUS RUN, every chunk at window offset 0 — not a
            # per-chunk first fit. Three call sites read chunk i out of bank
            # BASE+i off a single window base (mode7_stream's MVN stub table
            # and stream_stage_col, mode7_floor's seed upload, col_map's
            # `bank = T0_BANK + (ty >> log2(rpc))`), and until this branch
            # existed the packer promised them nothing: `bank_tiled` meant
            # only "every chunk fits one bank window", never "adjacent", and
            # first-fitting each chunk INDEPENDENTLY — rescanning from window
            # 0 each time — let a short tail chunk land BEHIND its own
            # predecessors. Measured on the real function before this change:
            # a 3-chunk blob behind a window-3 pin packed [1,2,4]; a ragged
            # blob behind a small pin packed [2,3,1] with its tail at offset
            # $0100; and TWO ragged tiled blobs with no pin at all packed
            # non-consecutively. Every one of those reads a plausible-looking
            # wrong 32 KB of ROM at runtime with nothing to say so

            #
            # PACK, don't refuse. Those shapes are placeable — they just are
            # not placeable by an independent first fit — so refusing them
            # would be this packer's limitation dressed up as a design answer,
            # which is not what "an infeasible declaration stops the build"
            # is for. The cost is bounded and is only paid by a RAGGED tiled
            # blob: its tail chunk can no longer backfill an earlier partial
            # window. It still leaves [piece, win) of its own window free for
            # later claims, and it buys an invariant three call sites already
            # depended on. Byte-neutral on every rail in the tree at the time
            # this landed (all tiled blobs there are whole multiples of the
            # window and were already consecutive).
            pieces = [min(c.bytes - k * win, win)
                      for k in range((c.bytes + win - 1) // win)]

            def _free_at_zero(fl: FreeList, size: int) -> bool:
                """Can this window give [0, size)? `carve(0, size)` needs a
                free interval starting exactly at 0 and long enough."""
                return bool(fl.free) and fl.free[0][0] == 0 and fl.free[0][1] >= size

            # First run of len(pieces) windows that can each take its chunk at
            # offset 0. An index past the end is a window that does not exist
            # yet, which is free by construction — so this terminates, and it
            # materialises only the windows it actually uses rather than the
            # ones it probed.
            base_wi = 0
            while not all(
                    base_wi + k >= len(windows)
                    or _free_at_zero(windows[base_wi + k], pieces[k])
                    for k in range(len(pieces))):
                base_wi += 1
            while len(windows) < base_wi + len(pieces):
                windows.append(FreeList(0, win))
            for chunk_i, piece in enumerate(pieces):
                at = windows[base_wi + chunk_i].fit(piece)
                assert at == 0, (
                    f"bank_tiled run placement for '{c.name}' chunk {chunk_i} "
                    f"landed at {at}, not 0 — the run scan and the carve "
                    f"disagree")
                out.append(Placement(
                    f"{c.name}_t{chunk_i}", "rom",
                    (base_wi + chunk_i) * win, piece, scope, who,
                    kind="chunk", backed_by=c.backed_by))
            continue

        remaining, chunk_i = c.bytes, 0
        while remaining > 0:
            piece = min(remaining, win)
            at = None
            for wi, fl in enumerate(windows):
                at = fl.fit(piece)
                if at is not None:
                    bank = wi
                    break
            if at is None:
                windows.append(FreeList(0, win))
                bank = len(windows) - 1
                at = windows[-1].fit(piece)
            suffix = f"_t{chunk_i}" if (c.bank_tiled and c.bytes > win) else ""
            out.append(Placement(f"{c.name}{suffix}", "rom", bank * win + at,
                                 piece, scope, who, kind="chunk" if suffix else "",
                                 backed_by=c.backed_by))
            remaining -= piece
            chunk_i += 1
    return out


def assign_channels(claims: list[tuple[HdmaClaim, str]], scope: str,
                    sub: Substrate,
                    reserved: list[ChannelAssign]) -> list[ChannelAssign]:
    """Assign HDMA/DMA channel claims to the 8 shared channels.

    Conflict model (the axis split-mode died on):
      - collision unit is (register, band, phase, channel);
      - one channel is reusable across DISJOINT bands and across phases
        (VBlank GP-DMA vs active-display HDMA are time-disjoint);
      - two claims driving the SAME register in overlapping bands of the same
        ACTIVE-display band conflict regardless of channel numbering.
        VBlank-phase claims are serialised queue entries, not concurrent
        owners, so they may share a register — see _register_exclusive.
    `reserved` carries global-scope assignments into every scene.
    """
    # register-level conflicts first — a channel shuffle cannot fix these
    flat: list[tuple[HdmaClaim, str]] = sorted(
        claims, key=lambda t: (t[0].channel is None, -(t[0].band[1] - t[0].band[0]),
                               t[0].name))
    everything = [(c, who) for c, who in flat]
    for i, (a, wa) in enumerate(everything):
        for b, wb in everything[i + 1:]:
            if (a.phase == b.phase and _register_exclusive(a.phase)
                    and _overlaps(a.band, b.band)):
                shared = _register_conflicts(a.registers, b.registers)
                if shared:
                    raise AllocationError(
                        f"HDMA register contention in scene '{scope}', band "
                        f"{max(a.band[0], b.band[0])}-{min(a.band[1], b.band[1])}: "
                        f"{a.name} ({wa}) and {b.name} ({wb}) both drive "
                        f"{shared} in the same phase '{a.phase}'")
    # ...and neither can it fix a conflict against an already-reserved
    # (global-scope) assignment: the pre-pass must see the UNION, not just
    # this call's claims (a global and a scene claim driving the same
    # register in overlapping bands of the same phase conflict regardless
    # of channel numbering — the cross-scope silent-composition hole, F2)
    seen_res: set = set()
    for r in reserved:
        rk = (r.name, r.scope, r.consumer, r.registers, r.band, r.phase)
        if rk in seen_res:
            continue                    # multi-channel claims repeat per channel
        seen_res.add(rk)
        r_scope = "global" if r.scope == GLOBAL else f"scene '{r.scope}'"
        for c, who in everything:
            if (c.phase == r.phase and _register_exclusive(c.phase)
                    and _overlaps(c.band, r.band)):
                shared = _register_conflicts(c.registers, r.registers)
                if shared:
                    raise AllocationError(
                        f"HDMA register contention in scene '{scope}', band "
                        f"{max(c.band[0], r.band[0])}-{min(c.band[1], r.band[1])}: "
                        f"{c.name} ({who}) and {r.name} ({r.consumer}, {r_scope}) "
                        f"both drive {shared} in the same phase "
                        f"'{c.phase}'")

    occupancy: dict[int, list[tuple[tuple[int, int], str, str]]] = {
        ch: [] for ch in range(sub.channel_count)}
    for r in reserved:
        occupancy[r.channel].append((r.band, r.phase, r.name))

    def channel_free(ch: int, band, phase) -> bool:
        return all(not (p == phase and _overlaps(band, b))
                   for b, p, _ in occupancy[ch])

    out: list[ChannelAssign] = []
    for c, who in flat:
        need = c.channels
        got: list[int] = []
        if c.channel is not None:
            for ch in range(c.channel, c.channel + need):
                if ch >= sub.channel_count or not channel_free(ch, c.band, c.phase):
                    holders = [n for b, p, n in occupancy.get(ch, [])
                               if p == c.phase and _overlaps(c.band, b)]
                    raise AllocationError(
                        f"HDMA channel contention in scene '{scope}', band "
                        f"{c.band[0]}-{c.band[1]}: {c.name} ({who}) pinned to ch{ch} "
                        f"but {' and '.join(holders) or 'the pool'} already holds it "
                        f"in phase '{c.phase}'")
                got.append(ch)
        else:
            for ch in range(sub.channel_count):
                if len(got) == need:
                    break
                if channel_free(ch, c.band, c.phase):
                    got.append(ch)
            if len(got) < need:
                usage = "; ".join(
                    f"ch{ch}: {', '.join(n for _, _, n in occ)}"
                    for ch, occ in occupancy.items() if occ)
                raise AllocationError(
                    f"HDMA channels over capacity in scene '{scope}': {c.name} "
                    f"({who}) needs {need} channel(s) in band {c.band[0]}-"
                    f"{c.band[1]} phase '{c.phase}' but the pool of "
                    f"{sub.channel_count} is exhausted ({usage})")
        for ch in got:
            occupancy[ch].append((c.band, c.phase, c.name))
            out.append(ChannelAssign(c.name, ch, c.registers, c.band, c.phase,
                                     scope, who, c.bbad, c.dmap))
    return out


# --------------------------------------------------------------------------
# the allocator
# --------------------------------------------------------------------------

def allocate(sub: Substrate, features: dict[str, FeatureDecl],
             state: StateDecl, manifest: GameManifest) -> Allocation:
    # -- 1. resolve deps ---------------------------------------------------
    global_feats = resolve_features(manifest.globals_, features, "globals")
    scene_feats: dict[str, list[FeatureDecl]] = {}
    for sc in manifest.scenes:
        expanded = resolve_features(sc.features, features, f"scene '{sc.id}'")
        scene_feats[sc.id] = [f for f in expanded
                              if f.name not in {g.name for g in global_feats}]

    # scene-var scope check
    for sid in state.scene_vars:
        if sid and sid not in scene_feats:
            raise AllocationError(
                f"state.toml [scene.{sid}]: no such scene in the manifest "
                f"(scenes: {sorted(scene_feats)})")
    if "" in state.scene_vars and len(manifest.scenes) != 1:
        raise AllocationError(
            "state.toml: a flat [scene] table needs a single-scene game; "
            "use [scene.<id>] sub-tables to target scenes by id")

    # C1 SPC RAM occupancy — PROGRAM-wide, so it runs over the resolved
    # closures before any per-scene work, and fails fast.
    spc_owner = check_spc_exclusivity(global_feats, scene_feats)

    # C2 SRAM — the program-wide packer, same early position for the same
    # reason: it runs over the resolved closures (globals + every scene,
    # deduped by feature name), never per scene. Placements join globals_map
    # below so the symbols emit once, in the globals inc.
    sram_map = place_sram(global_feats, scene_feats, sub)

    # -- 2. reserve globals ------------------------------------------------
    # Global claims are placed once; every scene's free lists start as
    # (console - system reservations - globals).
    dp_g = FreeList(0, sub.dp_bytes)
    wram_g = FreeList(sub.wram_reserved_low, sub.wram_bytes)
    vram_g = FreeList(0, sub.vram_words)
    cgram_g = FreeList(0, sub.cgram_words)
    oam_g = FreeList(0, sub.oam_sprites)
    # windows [0, code_windows) belong to the linker (CODE+RODATA) — seed them
    # zero-capacity so no claim can ever land there; claim sites .assert their
    # blob's linker bank/addr against the emitted _BANK/_ADDR symbols.
    rom_windows: list[FreeList] = [FreeList(0, 0)
                                   for _ in range(sub.rom_code_windows)]
    # PINNED rom claims are reserved across the WHOLE composition here, before
    # any free claim is placed in any scope — see reserve_pinned_rom.
    pinned_rom_at = reserve_pinned_rom(
        [(c, f"engine:{f.name}", GLOBAL) for f in global_feats for c in f.rom]
        + [(c, f"engine:{f.name}", sid)
           for sid, feats in scene_feats.items() for f in feats for c in f.rom],
        rom_windows, sub)

    # Collect claims PER CLASS across all global features before placing —
    # a failure's blame list + shortfall must cover every contributing
    # claim, not just the one that happened to fail to place (F3).
    globals_map: list[Placement] = [*sram_map]
    gvblank = 0
    gxfers = 0
    ghdma: list[tuple[HdmaClaim, str]] = []
    gdma_init: list[tuple[DmaInitClaim, str, str]] = []
    greg: list[tuple] = []
    g_init_zero: list[str] = []
    gscreen: list[tuple] = []
    gblend: list[tuple] = []
    g_vram, g_dp, g_wram, g_cgram, g_oam, g_rom = [], [], [], [], [], []
    for f in global_feats:
        who = f"engine:{f.name}"
        g_vram += [(c, who) for c in f.vram]
        g_dp += [(c, who) for c in f.dp]
        g_wram += [(c, who) for c in f.wram]
        g_cgram += [(c, who) for c in f.cgram]
        g_oam += [(c, who) for c in f.oam]
        g_rom += [(c, who) for c in f.rom]
        ghdma += [(c, who) for c in f.hdma]
        gdma_init += [(c, GLOBAL, who) for c in f.dma_init]
        greg += [(c, who) for c in f.reg]
        gscreen += [(c, who) for c in f.screen]
        gblend += [(c, who) for c in f.blend]
        gvblank += f.vblank_bytes_per_frame
        gxfers += f.vblank_transfers_per_frame
        g_init_zero += list(f.init_zero)
    wram_usable = sub.wram_bytes - sub.wram_reserved_low
    globals_map += place_vram(g_vram, sub, GLOBAL, vram_g)
    globals_map += place_bytes("dp", g_dp, GLOBAL, dp_g, sub.dp_bytes)
    globals_map += place_bytes("wram", g_wram, GLOBAL, wram_g, wram_usable,
                               bank_bytes=sub.wram_bank_bytes)
    globals_map += place_cgram(g_cgram, GLOBAL, cgram_g, sub)
    globals_map += place_oam(g_oam, GLOBAL, oam_g, sub)
    globals_map += place_rom(g_rom, GLOBAL, rom_windows, sub, pinned_rom_at)
    globals_map += place_state_vars(
        state.global_vars, GLOBAL, dp_g, wram_g, sub,
        [(p.name, p.size) for p in globals_map if p.cls == "dp"],
        [(p.name, p.size) for p in globals_map if p.cls == "wram"])
    global_channels = assign_channels(ghdma, GLOBAL, sub, [])

    # -- 3. per scene ------------------------------------------------------
    import copy
    scenes: dict[str, SceneMap] = {}
    for sc in manifest.scenes:
        sm = SceneMap(scene=sc.id)
        dp_fl = copy.deepcopy(dp_g)
        wram_fl = copy.deepcopy(wram_g)
        vram_fl = copy.deepcopy(vram_g)
        cgram_fl = copy.deepcopy(cgram_g)
        oam_fl = copy.deepcopy(oam_g)

        # collect per class across the scene's features (mirror the globals
        # pass / VRAM path) so any over-budget blames the complete set (F3)
        feats = scene_feats[sc.id]
        s_vram, s_dp, s_wram, s_cgram, s_oam, s_rom, hdma_claims = \
            [], [], [], [], [], [], []
        s_screen: list[tuple] = []
        s_blend: list[tuple] = []
        sm.vblank_bytes = gvblank
        sm.vblank_transfers = gxfers
        for f in feats:
            who = f"engine:{f.name}"
            s_vram += [(c, who) for c in f.vram]
            s_dp += [(c, who) for c in f.dp]
            s_wram += [(c, who) for c in f.wram]
            s_cgram += [(c, who) for c in f.cgram]
            s_oam += [(c, who) for c in f.oam]
            s_rom += [(c, who) for c in f.rom]
            hdma_claims += [(c, who) for c in f.hdma]
            sm.dma_inits += [(c, sc.id, who) for c in f.dma_init]
            sm.regs += [(c, who) for c in f.reg]
            s_screen += [(c, who) for c in f.screen]
            s_blend += [(c, who) for c in f.blend]
            sm.vblank_bytes += f.vblank_bytes_per_frame
            sm.vblank_transfers += f.vblank_transfers_per_frame
            sm.init_zero += list(f.init_zero)

        # C5: compose the screen/blend vocabulary over the global+scene
        # union (R1-R5 refuse here), then SYNTHESIZE its per-scene ownership
        # claim into the scene's reg union — with scene-enter write consent
        # for exactly the ports it composes, so a scene file writing the
        # emitted values passes the reg-ownership gate. R6 (vocabulary
        # mixing) then arises from the ordinary reg-x-reg intersection in
        # check_reg_ownership below, not from a special-cased lint.
        sm.screen_blend = compose_screen_blend(
            [*gscreen, *s_screen], [*gblend, *s_blend],
            [*greg, *sm.regs], sc.id)
        if sm.screen_blend is not None:
            sm.screen_blend["checks"] += 1          # R6 live via the union
            sm.regs.append((
                RegClaim(name="screen_blend",
                         registers=sm.screen_blend["registers"],
                         scene_writes=sm.screen_blend["registers"]),
                f"{VOCAB_WHO} <- {', '.join(sm.screen_blend['features'])}"))

        def g_of(cls: str) -> list[tuple[str, int]]:
            """The globals already occupying this class — blame-list context."""
            return [(p.name, p.size) for p in globals_map if p.cls == cls]

        sm.placements += place_vram(s_vram, sub, sc.id, vram_fl,
                                    reserved=g_of("vram"))
        sm.placements += place_bytes("dp", s_dp, sc.id, dp_fl, sub.dp_bytes,
                                     reserved=g_of("dp"))
        sm.placements += place_bytes("wram", s_wram, sc.id, wram_fl, wram_usable,
                                     bank_bytes=sub.wram_bank_bytes,
                                     reserved=g_of("wram"))
        sm.placements += place_cgram(s_cgram, sc.id, cgram_fl, sub,
                                     reserved=g_of("cgram"))
        sm.placements += place_oam(s_oam, sc.id, oam_fl, sub,
                                   reserved=g_of("oam"))
        sm.placements += place_rom(s_rom, sc.id, rom_windows, sub,
                                   pinned_rom_at)
        svars = state.scene_vars.get(sc.id, state.scene_vars.get("", ()))
        sm.placements += place_state_vars(
            svars, sc.id, dp_fl, wram_fl, sub,
            [(p.name, p.size) for p in [*globals_map, *sm.placements]
             if p.cls == "dp"],
            [(p.name, p.size) for p in [*globals_map, *sm.placements]
             if p.cls == "wram"])
        sm.channels = assign_channels(hdma_claims, sc.id, sub, global_channels)

        # C4 register ownership over the global+scene UNION (F2): scene_mgr
        # owns INIDISP/NMITIMEN globally, so a scene-scoped second writer has
        # to refuse against it.
        check_reg_ownership([*greg, *sm.regs],
                            [*ghdma, *hdma_claims],
                            [*gdma_init, *sm.dma_inits], sc.id)

        # F9 multi-queue model: every queued transfer beyond the first pays
        # the measured arm cost in byte-equivalents (0 until pinned).
        arm_total = sub.vblank_arm_cost * max(sm.vblank_transfers - 1, 0)
        if sm.vblank_bytes + arm_total > sub.vblank_budget:
            contributors = [(f.name, f.vblank_bytes_per_frame)
                            for f in [*global_feats, *feats]
                            if f.vblank_bytes_per_frame]
            if arm_total:
                contributors.append(
                    (f"arm_overhead({sm.vblank_transfers} transfers x "
                     f"{sub.vblank_arm_cost} B)", arm_total))
            _fail_over_budget("vblank-dma", sc.id, contributors,
                              sub.vblank_budget, "B/frame")
        scenes[sc.id] = sm

    # -- 4. per edge -------------------------------------------------------
    edge_reloads: list[tuple[str, str, int, int | None]] = []
    edge_styles: list[tuple[str, str, str, int]] = []
    # The scene id a `sm_request` takes is the MANIFEST ORDER index (the
    # sm_enter_tab/sm_tick_tab/sm_exit_tab row), so the emitted edge block
    # carries it too — otherwise the call site hand-writes "scene id 1 =
    # impact" beside the edge name and the two can drift silently.
    scene_index = {sc.id: i for i, sc in enumerate(manifest.scenes)}
    for e in manifest.edges:
        dst = scenes[e.dst]
        reload_bytes = sum(p.size * 2 for p in dst.placements
                           if p.cls in ("vram", "cgram"))
        if e.budget_bytes is not None and reload_bytes > e.budget_bytes:
            raise AllocationError(
                f"transition {e.src}->{e.dst} ({e.style}): scene reload is "
                f"{reload_bytes} B (VRAM+CGRAM to load under forced blank) but "
                f"the edge budget is {e.budget_bytes} B — over by "
                f"{reload_bytes - e.budget_bytes} B")
        edge_reloads.append((e.src, e.dst, reload_bytes, e.budget_bytes))
        edge_styles.append((e.src, e.dst, e.style, scene_index[e.dst]))

    alloc = Allocation(sub, globals_map, global_channels, scenes, edge_reloads,
                       globals_init_zero=g_init_zero,
                       global_dma_inits=gdma_init,
                       global_regs=greg,
                       spc_owner=spc_owner,
                       edge_styles=edge_styles)
    verify(alloc)
    return alloc


# --------------------------------------------------------------------------
# 5. verify — belt-and-suspenders, independent of the solver
# --------------------------------------------------------------------------

def verify(alloc: Allocation):
    sub = alloc.substrate
    # sram rides check_set like every other bounded class: its placements
    # live in globals_map, so the overlap walk + this cap bound re-check the
    # program-wide packing independently of place_sram's bookkeeping.
    caps = {"dp": sub.dp_bytes, "wram": sub.wram_bytes, "vram": sub.vram_words,
            "cgram": sub.cgram_words, "oam": sub.oam_sprites,
            "sram": sub.sram_bytes}

    def check_set(placements: list[Placement], scope: str):
        by_cls: dict[str, list[Placement]] = {}
        for p in placements:
            by_cls.setdefault(p.cls, []).append(p)
        for cls, ps in by_cls.items():
            ps = sorted(ps, key=lambda p: p.start)
            for a, b in zip(ps, ps[1:]):
                if a.end > b.start:
                    raise AssertionError(
                        f"VERIFY: {cls} overlap in '{scope}': {a.name} "
                        f"[{a.start}..{a.end}) vs {b.name} [{b.start}..{b.end})")
            if cls in caps:
                for p in ps:
                    if p.start < 0 or p.end > caps[cls]:
                        raise AssertionError(
                            f"VERIFY: {cls} out of range in '{scope}': {p.name} "
                            f"[{p.start}..{p.end}) exceeds {caps[cls]}")
        for p in placements:
            if p.cls == "vram":
                align = {"tilemap": sub.tilemap_align_words,
                         "chr": sub.chr_align_words,
                         "chr_obj": sub.obj_chr_align_words,
                         "mode7": sub.mode7_region_words, "raw": 1}[p.kind or "raw"]
                if p.kind == "chr" and p.start % sub.chr_align_words:
                    raise AssertionError(
                        f"VERIFY: chr claim {p.name} at ${p.start:04X} unaligned")
                if p.kind == "chr_obj" and p.start % sub.obj_chr_align_words:
                    raise AssertionError(
                        f"VERIFY: obj chr claim {p.name} at ${p.start:04X} unaligned")
                if p.kind == "tilemap" and p.start % sub.tilemap_align_words:
                    raise AssertionError(
                        f"VERIFY: tilemap claim {p.name} at ${p.start:04X} unaligned")
            if p.cls == "wram" and p.start < sub.wram_reserved_low:
                raise AssertionError(
                    f"VERIFY: wram claim {p.name} inside the system-reserved "
                    f"low ${sub.wram_reserved_low:04X}")

    check_set(alloc.globals_map, GLOBAL)
    for sid, sm in alloc.scenes.items():
        check_set([*alloc.globals_map, *sm.placements], sid)
        occ: dict[tuple[int, str], list[tuple[tuple[int, int], str]]] = {}
        for ca in [*alloc.global_channels, *sm.channels]:
            occ.setdefault((ca.channel, ca.phase), []).append((ca.band, ca.name))
        for (ch, phase), entries in occ.items():
            entries.sort()
            for (b1, n1), (b2, n2) in zip(entries, entries[1:]):
                if _overlaps(b1, b2):
                    raise AssertionError(
                        f"VERIFY: channel {ch} double-booked in '{sid}' phase "
                        f"{phase}: {n1} {b1} vs {n2} {b2}")
        # register-level, across the global+scene UNION: two claims driving
        # the same register in overlapping bands of the same ACTIVE band
        # conflict regardless of channel numbering (F2 — the class split-mode
        # died on). Must use the SAME exclusivity rule as place_channels, or
        # the solver and the checker disagree about what a legal map is.
        assigns = [*alloc.global_channels, *sm.channels]
        for i, a in enumerate(assigns):
            for b in assigns[i + 1:]:
                if (a.name, a.scope, a.consumer) == (b.name, b.scope, b.consumer):
                    continue        # two channels of ONE claim, not a conflict
                if (a.phase == b.phase and _register_exclusive(a.phase)
                        and _overlaps(a.band, b.band)):
                    shared = _register_conflicts(a.registers, b.registers)
                    if shared:
                        raise AssertionError(
                            f"VERIFY: register contention in '{sid}' phase "
                            f"'{a.phase}': {a.name} (ch{a.channel}) and {b.name} "
                            f"(ch{b.channel}) both drive {shared} in "
                            f"overlapping band {max(a.band[0], b.band[0])}-"
                            f"{min(a.band[1], b.band[1])}")
        if sm.vblank_bytes > sub.vblank_budget:
            raise AssertionError(f"VERIFY: vblank budget exceeded in '{sid}'")
        # C4 register ownership, re-run over the same global+scene union the
        # solver used. Same reason the register pre-pass is mirrored above: if
        # the solver and the checker disagree about what a legal map is, one of
        # them is decoration.
        try:
            check_reg_ownership(
                [*alloc.global_regs, *sm.regs],
                _xfer_of([*alloc.global_channels, *sm.channels]),
                [*alloc.global_dma_inits, *sm.dma_inits], sid)
        except AllocationError as e:
            raise AssertionError(f"VERIFY: {e}") from e


# --------------------------------------------------------------------------
# 6. emit
# --------------------------------------------------------------------------

def _sym(p: Placement) -> str:
    prefix = {"dp": "ES", "wram": "ES", "vram": "ES_V", "cgram": "ES_C",
              "oam": "ES_O", "rom": "ES_R", "sram": "ES_S"}[p.cls]
    if p.consumer == "user":
        prefix = {"dp": "US", "wram": "US"}.get(p.cls, "US")
    return f"{prefix}_{p.name.upper()}"


# The FORMAT VERSION of the emitted includes — the shape of the symbol set
# above, not the values in it. A rail pins the number it was written against
# with `.assert SF_INC_FORMAT = N` at its own include site, so a change to what
# an emitted symbol MEANS stops each consumer's build with its own message
# instead of quietly re-pointing an offset. Bump it when the emitted symbols
# change shape — a renamed or removed companion, a different unit for a class,
# a claim's symbols restructured. Do NOT bump it for a re-pack: a placement
# moving is the normal case and is exactly what the _ADDR/_BANK asserts at the
# claim sites already cover.
INC_FORMAT_VERSION = 1

_INC_CONVENTIONS = [
    "; Do not edit, do not hand-place. The map is derived, never narrated.",
    "; Conventions: DP symbols are direct-page offsets; WRAM symbols are",
    ";   $7E-bank offsets with _BANK/_LONG companions; VRAM symbols are",
    ";   WORD addresses (VMADD); CGRAM symbols are word indices; OAM",
    ";   symbols are sprite slot indices; ROM symbols are (bank window,",
    ";   offset) pairs; SRAM symbols are bank-$70 offsets with _BANK/_LONG",
    ";   companions (battery-backed, program-wide, always-slow 8 mc/access).",
    ";   _SIZE companions give the claim size.",
]


def _placement_lines(placements, sub: Substrate) -> list[str]:
    lines: list[str] = []
    # `ES_R_<NAME>_CHUNKS` — how many bank windows a bank_tiled claim was
    # split into, so the claim site's `.repeat` takes a DERIVED count instead
    # of a hand-written one.
    #
    # Why it exists: docs/37 §5 limit 1 used to say a short `.repeat` was
    # caught by "the linker's segment sizes and the per-chunk `.assert`".
    # Measured, that is false — `.repeat 8` -> `.repeat 7` on microzero's
    # world map leaves the backing gate, ca65 AND ld65 all green,
    # the ROM the same 524,288 bytes, and 18,478 bytes of map replaced by $FF
    # fill. An unused ca65 equate produces no diagnostic and lorom_512k.cfg
    # marks the BANK segments `optional = yes`, so a short segment is not a
    # link error either. A count narrated in ASM is a second copy of the
    # allocator's arithmetic, and this repo's whole premise is that there is
    # only one.
    chunk_counts: dict[str, int] = {}
    for p in placements:
        if p.cls == "rom" and p.kind == "chunk":
            base = re.sub(r"_T\d+$", "", _sym(p))
            chunk_counts[base] = chunk_counts.get(base, 0) + 1
    for base, n in sorted(chunk_counts.items()):
        lines.append(f"{base}_CHUNKS = {n}")
    for p in sorted(placements, key=lambda p: (p.cls, p.start)):
        s = _sym(p)
        if p.cls == "dp":
            lines += [f"{s} = ${p.start:02X}",
                      f"{s}_SIZE = {p.size}"]
        elif p.cls == "wram":
            bank = 0x7E + (p.start >> 16)
            off = p.start & 0xFFFF
            lines += [f"{s} = ${off:04X}",
                      f"{s}_BANK = ${bank:02X}",
                      f"{s}_LONG = ${bank:02X}{off:04X}",
                      f"{s}_SIZE = {p.size}"]
        elif p.cls == "sram":
            # the WRAM companion pattern at the substrate's SRAM bank: the
            # offset for indexed forms, _LONG for `sta f:ES_S_*_LONG, x`
            # (the usual SRAM_BASE convention, under an emitted symbol)
            bank = sub.sram_bank
            lines += [f"{s} = ${p.start:04X}",
                      f"{s}_BANK = ${bank:02X}",
                      f"{s}_LONG = ${bank:02X}{p.start:04X}",
                      f"{s}_SIZE = {p.size}"]
        elif p.cls == "vram":
            lines += [f"{s} = ${p.start:04X}",
                      f"{s}_WORDS = {p.size}"]
            # derived PPU register encodings — so ASM never does mask
            # arithmetic on bases (BGnSC = (value & $7C) << 8 words;
            # BGnnNBA nibble = base >> 12; see lessons_learned "PPU
            # Register Encoding")
            if p.kind == "tilemap":
                lines += [f"{s}_SC_BASE = ${(p.start >> 8) & 0x7C:02X}"]
            elif p.kind in ("chr", "chr_obj"):
                lines += [f"{s}_NBA = ${(p.start >> 12) & 0x0F:02X}"]
                if p.kind == "chr_obj":
                    # OBSEL bits 0-2: OBJ name base in 8K-word steps (the
                    # size-mode bits 5-7 are a game choice, not layout)
                    lines += [f"{s}_OBSEL_BASE = ${(p.start >> 13) & 0x07:02X}"]
        elif p.cls == "cgram":
            lines += [f"{s} = {p.start}",
                      f"{s}_WORDS = {p.size}"]
        elif p.cls == "oam":
            lines += [f"{s} = {p.start}",
                      f"{s}_SPRITES = {p.size}"]
        elif p.cls == "rom":
            bank, off = divmod(p.start, sub.rom_window_bytes)
            lines += [f"{s}_BANK = {bank}",
                      f"{s}_OFF = ${off:04X}",
                      f"{s}_ADDR = ${0x10000 - sub.rom_window_bytes + off:04X}",
                      f"{s}_SIZE = {p.size}"]
    return lines


def _channel_lines(chans, dma_inits=()) -> list[str]:
    """Channel number AND the register encoding, both from the declaration.

    The BBAD/DMAP bytes are emitted rather than hand-written in ASM for the
    same reason _SC_BASE and _NBA are: an encoding narrated at the write site
    is a second, uncheckable copy of the claim. The gap was exactly
    that copy drifting — a claim naming one register while its code drove
    another. Emitting it leaves one source, so the two cannot disagree.
    """
    lines = ["; ---- DMA/HDMA channels ----"]
    for ca in sorted(chans, key=lambda c: (c.channel, c.band)):
        s = f"ES_H_{ca.name.upper()}"
        lines += [f"{s}_CH = {ca.channel}"
                  f"    ; {','.join(ca.registers)} band "
                  f"{ca.band[0]}-{ca.band[1]} phase {ca.phase}",
                  f"{s}_BBAD = ${ca.bbad:02X}"
                  f"    ; -> ${0x2100 | ca.bbad:04X}",
                  f"{s}_DMAP = ${ca.dmap:02X}"
                  f"    ; mode {ca.dmap & 0x07}"
                  f"{', indirect' if ca.dmap & 0x40 else ', direct'}"]
    for di, scope, who in sorted(dma_inits, key=lambda t: (t[0].channel, t[0].name)):
        s = f"ES_D_{di.name.upper()}"
        lines += [f"{s}_CH = {di.channel}"
                  f"    ; {','.join(di.registers)} phase forced_blank ({who})",
                  f"{s}_BBAD = ${di.bbad:02X}"
                  f"    ; -> ${0x2100 | di.bbad:04X}",
                  f"{s}_DMAP = ${di.dmap:02X}"
                  f"    ; mode {di.dmap & 0x07}"
                  f"{', indirect' if di.dmap & 0x40 else ', direct'}"]
    lines.append("")
    return lines


def _screen_blend_lines(sid: str, sb: dict | None) -> list[str]:
    """The composed color-math state, as symbols the scene writes from.

    The values are emitted rather than hand-written at the write site for
    _channel_lines' reason verbatim: an encoding narrated at the write site
    is a second, uncheckable copy of the claim. Scene-enter code writes the
    composed ports from these symbols (the synthesized claim's scene_writes
    is exactly this consent), so the state a scene establishes IS the state
    its declarations composed.

    A SYMBOL IS PUBLISHED ONLY FOR A PORT THE COMPOSITION OWNS, which is
    per-half (compose_screen_blend's `registers`): screen claims own TM/TS,
    blend claims own CGWSEL/CGADSUB, and a scene can carry one half without
    the other. Emitting all four regardless would state a value for a port
    the scene's composition does not own — a screen-only scene publishing
    `ES_SCR_<ID>_CGWSEL = $30` beside a feature that owns and programs
    CGWSEL — and the writer-side gate would ACCEPT a scene write of it
    wherever that raw owner opened the port with `scene_writes`. That is the
    second uncheckable copy this emission exists to prevent, with the
    allocator as its author. The composed OFF values still exist (the
    allocation report and symbol map carry all four); what is withheld is a
    symbol to write an unowned port FROM.
    """
    if sb is None:
        return []
    up = sid.upper()

    def contrib(on_filter):
        names = [f"{c.layer}<-{who}" for c, who in sb["screen"]
                 if c.on in on_filter]
        return ", ".join(names) if names else "no designation"

    lines = ["; ---- screen/blend: the composed color-math state ----",
             ";   TM/TS from [[claims.screen]]; CGWSEL/CGADSUB from",
             ";   [[claims.blend]]. Scene-enter code writes these ports from",
             ";   these symbols — never a narrated value. A half this scene",
             ";   composes no claim for owns no port here and emits no",
             ";   symbol: writing it is another claimant's business."]
    if sb["screen"]:
        lines += [
            f"ES_SCR_{up}_TM = ${sb['tm']:02X}"
            f"    ; {contrib(('main', 'both'))}",
            f"ES_SCR_{up}_TS = ${sb['ts']:02X}"
            f"    ; {contrib(('sub', 'both'))}"]
    else:
        lines.append(f"; ES_SCR_{up}_TM / _TS absent — no [[claims.screen]] in "
                     f"this scene: TM/TS are not this composition's to write")
    if sb["blend"]:
        g, _ = sb["blend"][0]
        math = ", ".join(f"{m}<-{who}" for c, who in sb["blend"]
                         for m in c.math)
        lines += [
            f"ES_SCR_{up}_CGWSEL = ${sb['cgwsel']:02X}"
            f"    ; source={g.source} clip={g.clip} prevent={g.prevent}"
            f" (direct color composed 0)",
            f"ES_SCR_{up}_CGADSUB = ${sb['cgadsub']:02X}"
            f"    ; op={g.op}{' half' if g.half else ''} math: {math}"]
    else:
        lines.append(f"; ES_SCR_{up}_CGWSEL / _CGADSUB absent — no "
                     f"[[claims.blend]] in this scene: the composed OFF state "
                     f"is ${sb['cgwsel']:02X}/${sb['cgadsub']:02X}, but "
                     f"establishing it belongs to whoever owns these ports "
                     f"(docs/99 §4)")
    lines.append("")
    return lines


def _edge_lines(edge_styles) -> list[str]:
    """The declared transition style, as symbols the ASM resolves against.

    . `style` used to be parsed into EdgeDecl and consumed by exactly
    one report string (the over-budget message above), so it read like a
    behaviour selector and selected nothing. These symbols are what make it
    load-bearing: `scene_mgr.inc`'s SM_SWITCH macro builds
    `ES_E_<SRC>_TO_<DST>_CUT` from its two arguments and picks the runtime
    path with a `.if` on it, at ASSEMBLY time. So the edge a scene requests
    must be declared (an undeclared one has no symbol and the macro `.error`s
    by name), and the path it takes is the one the declaration names — a rail
    cannot say "fade" through the macro and run the cut.

    `_DST` rides along for the same reason: `sm_request` takes the MANIFEST
    ORDER index, and a call site that hand-writes it beside the edge name
    keeps a second copy of the manifest's ordering that nothing checks.

    `SF_SM_CUT` is emitted ONLY when some edge declares "cut" — the irq
    `$FFEE` precedent (vendor/rom/header.inc's `.ifndef SF_IRQ_VECTOR`).
    scene_mgr defaults it to 0 and assembles the cut path only under it, so a
    composition with no cut edge is byte-identical to before.
    """
    if not edge_styles:
        return []
    lines = ["; ---- transition edges: the declared style, per edge ----",
             ";   SM_SWITCH \"SRC\", \"DST\" (scene_mgr.asm) resolves its call "
             "against these.",
             ";   _DST = the manifest-order scene id. _CUT is PRESENT iff the",
             ";   style is \"cut\" and ABSENT otherwise — a presence test, not a",
             ";   value test, because SM_SWITCH expands INSIDE a scene's",
             ";   `.scope` and ca65 defers an unqualified global there: "
             "`.defined`",
             ";   answers at assembly time where `.if <symbol>` reports "
             "\"constant",
             ";   expression expected\". The `.ifndef SF_IRQ_VECTOR` idiom, "
             "per edge."]
    if any(style == "cut" for _, _, style, _ in edge_styles):
        lines.append("SF_SM_CUT = 1"
                     "    ; some edge declares \"cut\": assemble scene_mgr's "
                     "cut path")
    for src, dst, style, dst_idx in edge_styles:
        s = f"ES_E_{src.upper()}_TO_{dst.upper()}"
        lines.append(f"{s}_DST = {dst_idx}    ; scene '{dst}' (manifest order)")
        if style == "cut":
            lines.append(f"{s}_CUT = 1    ; style = \"cut\"")
        else:
            lines.append(f"; {s}_CUT absent — style = \"{style}\"")
    lines.append("")
    return lines


def _init_contract_lines(zero_names, placements, when: str) -> list[str]:
    if not zero_names:
        return []
    lines = [f"; ---- init contract: claims to zero {when} "
             "(power-on RAM is random) ----"]
    for name in zero_names:
        p = next(p for p in placements if p.name == name)
        lines.append(f";   {_sym(p)} (+_SIZE)")
    lines.append("")
    return lines


def emit(alloc: Allocation, out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    sub = alloc.substrate

    # globals file — included ONCE, unscoped, before any scene file --------
    glines = [
        "; engine_state_globals.inc — GENERATED by superforge/allocator/allocate.py",
        *_INC_CONVENTIONS,
        "; Include this file ONCE at top level (never inside a .scope), before",
        "; any engine_state_<scene>.inc.",
        "",
        "; ---- format version (the SHAPE of these symbols, not their values) ----",
        "; Pin it at the include site: `.assert SF_INC_FORMAT = N, error, \"...\"`,",
        "; so a change to what an emitted symbol MEANS stops your build by name",
        "; rather than re-pointing an offset under you. A claim MOVING does not",
        "; bump this — the _ADDR/_BANK asserts at the claim sites cover that.",
        f"SF_INC_FORMAT = {INC_FORMAT_VERSION}",
        "",
        "; ---- system (substrate data: the reserved low WRAM = DP page + stack) ----",
        f"SYS_STACK_TOP = ${sub.wram_reserved_low - 1:04X}",
        "",
    ]
    if alloc.globals_map:
        glines.append("; ---- globals (game-lifetime; stable across every scene) ----")
        glines += _placement_lines(alloc.globals_map, sub)
        glines.append("")
    hdr = sram_header_bytes(alloc.globals_map, sub)
    if hdr is not None:
        # Derived cart-header encodings — the _SC_BASE/_NBA family applied to
        # the header: header.inc consumes these through its .ifndef defaults
        # (generated inc is included BEFORE header.inc in every main.asm), so
        # the cart's declared SRAM size + battery type are pure functions of
        # the claims and can never disagree with what the game writes
        # No sram claims -> this block is absent and the
        # $00/$00 defaults hold, byte-identically.
        n, cart = hdr
        total = sum(p.size for p in alloc.globals_map if p.cls == "sram")
        glines += [
            "; ---- cart header derivation (sram demand -> $FFD8/$FFD6) ----",
            f"SF_HDR_SRAM_SIZE = ${n:02X}"
            f"    ; $FFD8: 1024<<{n} = {1024 << n} B declared"
            f" ({total} B demanded)",
            f"SF_HDR_CART_TYPE = ${cart:02X}"
            f"    ; $FFD6: ROM+RAM+battery — sram claims exist",
            "",
        ]
    if alloc.global_channels or alloc.global_dma_inits:
        glines += _channel_lines(alloc.global_channels, alloc.global_dma_inits)
    glines += _edge_lines(alloc.edge_styles)
    glines += _init_contract_lines(alloc.globals_init_zero, alloc.globals_map,
                                   "once at boot")
    p_g = out_dir / "engine_state_globals.inc"
    p_g.write_text("\n".join(glines))
    written.append(p_g)

    # per-scene files — in a multi-scene ROM, include each inside
    # `.scope <scene_id>` so same-named claims in different scenes stay
    # distinct symbols; globals resolve through the enclosing scope ---------
    for sid, sm in alloc.scenes.items():
        lines = [
            f"; engine_state_{sid}.inc — GENERATED by superforge/allocator/allocate.py",
            *_INC_CONVENTIONS,
            "; Scene-scoped map: include AFTER engine_state_globals.inc. In a",
            f"; multi-scene ROM, wrap in `.scope {sid}` ... `.endscope` — scene",
            "; symbols scope cleanly; globals resolve through the enclosing scope.",
            "",
        ]
        if sm.placements:
            lines.append(f"; ---- scene '{sid}' ----")
            lines += _placement_lines(sm.placements, sub)
            lines.append("")
        if sm.channels or sm.dma_inits:
            lines += _channel_lines(sm.channels, sm.dma_inits)
        lines += _screen_blend_lines(sid, sm.screen_blend)
        lines += _init_contract_lines(sm.init_zero, sm.placements,
                                      "on scene entry")
        p_inc = out_dir / f"engine_state_{sid}.inc"
        p_inc.write_text("\n".join(lines))
        written.append(p_inc)

    # allocation report ----------------------------------------------------
    rep = ["superforge allocation report", "=" * 60]
    if alloc.substrate.vblank_usable_bytes is None:
        rep.append(f"NOTE: VBlank budget uses the START PIN "
                   f"({sub.vblank_start_pin} B) — not yet measured (deliverable 6)")
    for sid, sm in alloc.scenes.items():
        rep.append(f"\nscene '{sid}'")
        rep.append("-" * 60)
        for cls, unit, fmt in (("dp", "B", "02X"), ("wram", "B", "04X"),
                               ("vram", "words", "04X"), ("cgram", "words", "d"),
                               ("oam", "sprites", "d"), ("rom", "B", "05X")):
            ps = sorted((p for p in [*alloc.globals_map, *sm.placements]
                         if p.cls == cls), key=lambda p: p.start)
            if not ps:
                continue
            used = sum(p.size for p in ps)
            # ROM is the one class with no SUBSTRATE capacity — the linker
            # config owns the real cartridge size, so a fixed denominator here
            # would be a number this file cannot know. What it CAN say is the
            # space it actually laid claims into: the windows spanned by the
            # placements, less the code windows the linker owns. That reads the
            # same way as the other classes and, unlike a cartridge size, it
            # moves when packing does — which is the fragmentation the free
            # column is there to show.
            if cls == "rom":
                last_win = max(p.end - 1 for p in ps) // sub.rom_window_bytes
                cap = ((last_win + 1 - sub.rom_code_windows)
                       * sub.rom_window_bytes)
            else:
                cap = {"dp": sub.dp_bytes, "wram": sub.wram_bytes,
                       "vram": sub.vram_words, "cgram": sub.cgram_words,
                       "oam": sub.oam_sprites}[cls]
            rep.append(f"  {cls.upper():6} {used}/{cap} {unit} used, "
                       f"{cap - used} free")
            for p in ps:
                scope = "global" if p.scope == GLOBAL else "scene"
                rep.append(f"    [{p.start:{fmt}}..{p.end:{fmt}}) "
                           f"{p.name:24} {p.consumer:18} {scope}")
        chans = [*alloc.global_channels, *sm.channels]
        if chans:
            rep.append(f"  CHANNELS ({len({c.channel for c in chans})}/"
                       f"{sub.channel_count} used)")
            for ca in sorted(chans, key=lambda c: (c.channel, c.band)):
                rep.append(f"    ch{ca.channel} {ca.name:24} "
                           f"{','.join(ca.registers):18} band {ca.band[0]:3}-"
                           f"{ca.band[1]:3} {ca.phase}")
        # C4: CPU-written register ownership. Emits no symbol (the VALUE comes
        # from elsewhere — an emitted _OBSEL_BASE, a game constant), so the
        # report IS the deliverable: who owns which port, visible at a glance.
        regs = [*alloc.global_regs, *sm.regs]
        if regs:
            owned = sorted({r for c, _ in regs for r in c.registers})
            rep.append(f"  REGISTERS ({len(owned)} owned by CPU write)")
            for c, who in sorted(regs, key=lambda t: (t[1], t[0].name)):
                rep.append(f"    {c.name:24} {who:18} "
                           f"{'seed ' if c.seed else 'owns '}"
                           f"{','.join(c.registers)}")
        # C5: the composed screen/blend state — the values, the per-layer
        # designations with their owners, and the warnings (real hardware
        # behaviour worth knowing, not refusals).
        sb = sm.screen_blend
        if sb is not None:
            # All four VALUES, and which of them this composition OWNS. The
            # report shows the composed off state either way; the `owns`
            # tail is what says whether a symbol was published for it.
            rep.append(f"  SCREEN/BLEND TM=${sb['tm']:02X} TS=${sb['ts']:02X} "
                       f"CGWSEL=${sb['cgwsel']:02X} "
                       f"CGADSUB=${sb['cgadsub']:02X} "
                       f"(owns {','.join(sb['registers'])})")
            for c, who in sb["screen"]:
                rep.append(f"    {c.layer} -> {c.on:5} {'':16} {who}")
            for c, who in sb["blend"]:
                rep.append(f"    blend {c.op}{' half' if c.half else ''} "
                           f"source={c.source} math={','.join(c.math)} "
                           f"clip={c.clip} prevent={c.prevent}  {who}")
            for w in sb["warnings"]:
                rep.append(f"    WARNING: {w}")
        arm_total = sub.vblank_arm_cost * max(sm.vblank_transfers - 1, 0)
        rep.append(f"  VBLANK-DMA {sm.vblank_bytes}"
                   f"{f' + {arm_total} arm' if arm_total else ''}"
                   f"/{sub.vblank_budget} B/frame"
                   f" ({sm.vblank_transfers} transfers)")
    for src, dst, bytes_, budget in alloc.edge_reloads:
        b = f" (budget {budget})" if budget else ""
        rep.append(f"\ntransition {src}->{dst}: reload {bytes_} B{b}")
    p_rep = out_dir / "allocation_report.txt"
    p_rep.write_text("\n".join(rep) + "\n")
    written.append(p_rep)

    # machine-readable symbol map (feeds no_literals.py) -------------------
    def pj(p: Placement) -> dict:
        d = {"sym": _sym(p), "class": p.cls, "start": p.start, "size": p.size,
             "scope": "global" if p.scope == GLOBAL else p.scope,
             "consumer": p.consumer, "kind": p.kind}
        # rom-backing gate input (docs/37). Emitted only where it means
        # something — a `backed_by` on any other class would be noise the gate
        # never reads, and a key present-but-empty on 40 non-rom placements
        # reads like a field someone forgot to fill.
        if p.cls == "rom":
            d["backed_by"] = p.backed_by
        return d

    jmap = {
        "spaces": {
            "wram_bytes": sub.wram_bytes,
            "wram_base_addr": 0x7E0000,
            "dp_bytes": sub.dp_bytes,
            "vram_words": sub.vram_words,
            "io_allowed": [[0x2100, 0x21FF], [0x4200, 0x43FF]],
            "spc_bytes": sub.spc_bytes,
            "sram_bytes": sub.sram_bytes,
            "sram_base_addr": sub.sram_bank << 16,
        },
        # C1: the single program-wide SPC RAM occupant (or null). No symbol
        # to emit; recorded so the ownership is machine-readable and a future
        # writer-side gate has its input — the reg class precedent.
        "spc_owner": (None if alloc.spc_owner is None else
                      {"feature": alloc.spc_owner[0],
                       "claim": alloc.spc_owner[1],
                       "declared_in": alloc.spc_owner[2]}),
        "globals": [pj(p) for p in alloc.globals_map],
        #: the declared transition style per edge. The `.inc` block is
        # what the ASM resolves against; this is the machine-readable copy, so
        # a test can assert the ROM's rendered transition against the DECLARED
        # style rather than against a constant it re-types.
        "edges": [{"src": src, "dst": dst, "style": style,
                   "dst_scene_index": idx}
                  for src, dst, style, idx in alloc.edge_styles],
        "scenes": {sid: {"placements": [pj(p) for p in sm.placements],
                         # item 5 (M2b): `consumer` on the TRANSFER entries.
                         # Only `reg` carried one before, and
                         # _main_reg_context's own comment recorded the gap as
                         # the reason global hdma/dma_init port coverage was
                         # not extended there. The writer-side gate's `covered`
                         # narrowing needs to ask WHICH feature covers a port
                         # before it can ask whether that same feature opened
                         # it, so the answer has to be in the map.
                         "channels": [{"name": c.name, "ch": c.channel,
                                       "registers": list(c.registers),
                                       "band": list(c.band), "phase": c.phase,
                                       "bbad": c.bbad, "dmap": c.dmap,
                                       "consumer": c.consumer}
                                      for c in [*alloc.global_channels,
                                                *sm.channels]],
                         # forced_blank phase: enter-time GP-DMA, declared so
                         # the channel + target ports are not invisible.
                         "dma_init": [{"name": d.name, "ch": d.channel,
                                       "registers": list(d.registers),
                                       "phase": "forced_blank",
                                       "bbad": d.bbad, "dmap": d.dmap,
                                       "consumer": who}
                                      for d, _, who in [*alloc.global_dma_inits,
                                                        *sm.dma_inits]],
                         # C4: CPU-written register ownership. No symbol to
                         # emit; recorded so the ownership is machine-readable
                         # (and so a future writer-side gate has its input —
                         # docs/09 §2.1's named hole).
                         "reg": [{"name": c.name, "registers": list(c.registers),
                                  "seed": c.seed, "consumer": who,
                                  # the owner's CONSENT for scene-enter
                                  # and boot writes, and the subset of it the
                                  # owner also writes itself. The writer-side
                                  # gate narrows its `declared`/`covered` view
                                  # to these; without them a scene is an
                                  # unlimited second writer of every port its
                                  # closure happens to own (docs/09 §2.1 hole 2).
                                  "scene_writes": list(c.scene_writes),
                                  "scene_writes_shared":
                                      list(c.scene_writes_shared)}
                                 for c, who in [*alloc.global_regs, *sm.regs]],
                         "vblank_bytes": sm.vblank_bytes,
                         "vblank_transfers": sm.vblank_transfers,
                         # C5: the composed screen/blend state, present only
                         # where the scene composes it (an absent key keeps
                         # every pre-vocabulary map byte-identical). The .inc
                         # block is what the ASM resolves against; this is
                         # the machine-readable copy, so a test can assert
                         # the ROM's rendered state against the DECLARED
                         # composition rather than re-typing the values —
                         # the `edges` precedent. The synthesized ownership
                         # claim itself rides the `reg` list above.
                         **({"screen_blend": {
                                 "tm": sm.screen_blend["tm"],
                                 "ts": sm.screen_blend["ts"],
                                 "cgwsel": sm.screen_blend["cgwsel"],
                                 "cgadsub": sm.screen_blend["cgadsub"],
                                 # WHICH of the four the composition OWNS —
                                 # per-half, so a reader can tell a composed
                                 # value from an off value the scene does not
                                 # own and does not publish a symbol for
                                 # (_screen_blend_lines).
                                 "registers": list(
                                     sm.screen_blend["registers"]),
                                 "features": sm.screen_blend["features"]}}
                            if sm.screen_blend is not None else {})}
                   for sid, sm in alloc.scenes.items()},
    }
    p_json = out_dir / "symbol_map.json"
    p_json.write_text(json.dumps(jmap, indent=2) + "\n")
    written.append(p_json)
    return written


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="superforge declarative resource allocator: proves the declared "
                    "game collision-free and emits the map, or fails the build "
                    "with a legible reason.")
    ap.add_argument("--game", required=True,
                    help="game dir containing game.toml (+ optional state.toml)")
    ap.add_argument("--features-dir", default=None,
                    help="dir containing <feature>/feature.toml (default: --game dir)")
    ap.add_argument("--substrate",
                    default=str(Path(__file__).parent / "substrate.toml"))
    ap.add_argument("--out", default="build",
                    help="output dir for .inc / report / symbol map")
    args = ap.parse_args(argv)

    try:
        sub = load_substrate(args.substrate)
        game_dir = Path(args.game)
        manifest = load_manifest(game_dir / "game.toml")
        state_path = game_dir / "state.toml"
        state = load_state(state_path) if state_path.exists() else StateDecl((), {})
        fdir = Path(args.features_dir) if args.features_dir else game_dir
        features = {}
        for fpath in sorted(fdir.glob("*/feature.toml")):
            decl = load_feature(fpath, sub)
            features[decl.name] = decl
        alloc = allocate(sub, features, state, manifest)
        # emit is inside the try: the sram header derivation can refuse
        # (a demand the window cannot declare), and that is a build stop
        # with a legible reason, not a traceback.
        written = emit(alloc, args.out)
    except (SchemaError, AllocationError) as e:
        print(f"ALLOCATION FAILED: {e}", file=sys.stderr)
        return 1
    print(f"allocation OK: {len(alloc.scenes)} scene(s), "
          f"{sum(len(s.placements) for s in alloc.scenes.values()) + len(alloc.globals_map)} "
          f"placements -> {', '.join(str(w) for w in written)}")
    # C5 census — printed unconditionally, on the house discipline: a zero
    # reads as "nothing composed", never as silence, so a composition that
    # was supposed to carry the vocabulary and does not is visible from the
    # summary. Counts are per-scene compositions (a global claim composed
    # into two scenes counts in both, which is what "across S scene(s)"
    # reads as); the check count is the allocation-time refusal checks that
    # were LIVE (R1 needs two designations, R2/R3 two blend claims, R4/R5 a
    # blend claim, R6 the synthesized ownership claim in the scene's union
    # — R7 is refused at parse, so every blend claim counted here already
    # passed it).
    sbs = [sm.screen_blend for sm in alloc.scenes.values()
           if sm.screen_blend is not None]
    if sbs:
        print(f"screen/blend: {sum(sb['designations'] for sb in sbs)} "
              f"designation(s), {sum(sb['blends'] for sb in sbs)} blend "
              f"claim(s) composed across {len(sbs)} scene(s), "
              f"{sum(sb['checks'] for sb in sbs)} refusal check(s) evaluated")
    else:
        print("screen/blend: nothing composed (no vocabulary claims in "
              "this composition)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
