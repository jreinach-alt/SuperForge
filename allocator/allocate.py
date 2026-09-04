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
from schemas import (BLEND_REGS, MATH_LAYERS, MODE_BPP, MODE_LAYERS,  # noqa: E402
                     OFFSET_H_VALUE_MASK, OFFSET_LAYER_BITS, OFFSET_MODES,
                     OFFSET_REGS, OFFSET_ROW_VOFS, OFFSET_ROWSEL_MODE,
                     OFFSET_ROWSEL_REG, OFFSET_VALUE_MASK, OFFSET_VSEL_BIT,
                     REGISTER_FOOTPRINT, TILEMAP_SHAPES, VIDEO_REGS,
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
    # vram tilemap only: BGnSC's two size bits, from the claim's declared
    # `shape` (schemas.TILEMAP_SHAPES). 0 for every other class and for every
    # 32x32 map, so _SC_BASE is unchanged wherever a shape was never declared.
    shape_bits: int = 0

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
    # C6: ...and the scene's composed video mode + offset table
    # (compose_video_offset's return, or None where neither is declared).
    video_offset: dict | None = None


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
    # C5: the per-edge blend-persistence notes (check_blend_edges) and the
    # number of edges that check actually examined. Program-wide rather than
    # per-scene because an edge belongs to neither of its two scenes; the
    # count rides along so a run that examined no candidate edge says so
    # instead of reading as clean.
    blend_edge_warnings: list[str] = field(default_factory=list)
    blend_edges_checked: int = 0


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
                    # R6 / O5 — vocabulary mixing. One side is a scene's
                    # synthesized composition; the other is a raw
                    # [[claims.reg]] on a port that composition owns. The
                    # refusal is this same intersection — a vocabulary is
                    # just another claimant — but the FIX differs per
                    # vocabulary and, inside video/offset, per PORT, so the
                    # message is chosen rather than shared.
                    (rc, rw) = (a, wa) if _is_vocab_who(wb) else (b, wb)
                    (vc, vw) = (b, wb) if _is_vocab_who(wb) else (a, wa)
                    head = (f"REGISTER ownership contention in scene "
                            f"'{scope}': {rc.name} ({rw}) claims {shared} as "
                            f"a raw [[claims.reg]], but this scene also "
                            f"composes the {_vocab_of(vw)} vocabulary over "
                            f"the same port ({vc.name}, {vw}) — two "
                            f"vocabularies, one write-only port. Every "
                            f"writer of a write-only register supplies the "
                            f"WHOLE byte, so the raw value and the composed "
                            f"value cannot both hold.")
                    if _vocab_of(vw) == VOCAB_WHO:
                        raise AllocationError(
                            head + " Move the raw claim into the "
                            "vocabulary: a TM/TS designation becomes "
                            "[[claims.screen]] (layer, on) on the feature "
                            "that owns the layer; CGWSEL/CGADSUB "
                            "programming becomes [[claims.blend]] (docs/99)")
                    if [r for r in shared if r in OFFSET_REGS]:
                        # THE BG3-AS-DATA REFUSAL. A feature that draws on
                        # BG3 has met the scene's offset table. Nothing in
                        # the register footprint could say this before: both
                        # sides claim BG3SC and the collision read as an
                        # ordinary double-owner, which names neither the
                        # hazard nor the choice.
                        raise AllocationError(
                            head + f" And on {[r for r in shared if r in OFFSET_REGS]} "
                            f"it is not a tie to break: BG3 IS THIS SCENE'S "
                            f"OFFSET TABLE, not a drawable layer. In modes "
                            f"{list(OFFSET_MODES)} the PPU reads BG3's map "
                            f"entries as per-column scroll offsets and never "
                            f"renders the layer (Mesen2 SnesPpu.cpp "
                            f"RenderMode2/4/6 draw BG1/BG2 and OBJ only; the "
                            f"words are fetched at :257-276), so a feature "
                            f"that draws on BG3 and an offset-per-tile "
                            f"feature cannot both hold this scene whatever "
                            f"they agree about the registers. Draw "
                            f"'{rc.name}' on a BG the mode renders, or put "
                            f"the offset table in a scene of its own "
                            f"(docs/100)")
                    raise AllocationError(
                        head + " Move the raw claim into the vocabulary: "
                        "the scene's BGMODE becomes a [[claims.video]] "
                        "claim (mode, and the bg3_priority / tiles16 bits "
                        "with it) on the feature that defines the display "
                        "shape. A per-scanline BGMODE rewrite is the one "
                        "case that keeps the raw shape, in a scene that "
                        "composes no [[claims.video]] claim (docs/100)")
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
            # KIND FIRST, then the claimant. The two axes are independent and
            # the advice differs on both, so a single `if vocab` ahead of the
            # kind test hands a dma_init conflict the per-scanline sentence —
            # advice naming `seed = true` beside an hdma claim, for a
            # conflict the dma_init arm below exists to say `seed` cannot
            # answer. A message that misdirects is the defect here.
            if kind == "dma_init":
                hint = ("A dma_init is a one-shot enter-time ESTABLISHER, "
                        "not an ongoing overrider, so `seed` does not "
                        "exempt it")
                if _is_vocab_who(wa):
                    hint += (", and the composed screen/blend state is "
                             "established at scene enter too — so these are "
                             "two enter-time writers of one port with no "
                             "ordering between them, which no declaration "
                             "makes compose. Drop the port from the "
                             "dma_init claim if the transfer does not "
                             "really drive it, or keep the RAW claim shape "
                             "in a scene that composes no vocabulary half "
                             "on it")
            elif _is_vocab_who(wa):
                # The reg side is the synthesized screen/blend composition
                # against an HDMA claim. It has no `seed` for an author to
                # mark, on purpose: the vocabulary has no per-scanline story
                # (a stated limit).
                hint = ("The screen/blend vocabulary has no per-scanline "
                        "story — a per-scanline rewrite of these ports "
                        "keeps the RAW claim shape (a [[claims.reg]] with "
                        "`seed = true` beside the hdma claim), in a scene "
                        "that does not compose the vocabulary on them")
            else:
                hint = ("If the transfer is meant to overwrite this base "
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

# The COLOR WINDOW's own programming — the precondition `clip`/`prevent` of
# "outside"/"inside" depend on, and which the vocabulary deliberately does
# not compose (a stated limit, docs/99 §8). Read off the Mesen2 source
# rather than off a summary, and NOT the register set the BG windows use:
#
#   the color window is index 5 (SnesPpu.h:23 ColorWindowIndex);
#   ActiveLayers[5] / InvertedLayers[5] come from WOBJSEL $2125 alone —
#     ProcessWindowMaskSettings(value, 4) sets 0+4 (OBJ) and 1+4 (color)
#     (SnesPpu.cpp:2136-2138, :1487-1498). W12SEL/W34SEL carry offsets 0
#     and 2, i.e. BG1-BG4, and never reach index 5;
#   MaskLogic[5] comes from WOBJLOG $212B bits 2-3 (:2169-2172, the
#     assignment itself at :2172) — WBGLOG is MaskLogic[0..3], the BG layers;
#   the two windows' edges come from WH0-WH3 $2126-$2129 (:2141-2159), read
#     by PixelNeedsMasking (SnesPpuTypes.h:109-124).
#
# With none of them programmed, activeWindowCount is 0 (:1278) and
# ProcessMaskWindow falls through to `return false` (:1484), so
# isInsideWindow is false for EVERY pixel and each mode degenerates to a
# fixed one — see _WINDOWLESS below.
_COLOR_WINDOW_REGS = ("WOBJSEL", "WOBJLOG", "WH0", "WH1", "WH2", "WH3")

# The register that ENABLES the color window, which is the only one whose
# absence makes the precondition unsatisfiable. `activeWindowCount` is
# ActiveLayers[5] summed over the two windows (:1278) and ActiveLayers[5] is
# written from WOBJSEL alone (:1487-1498); with those bits clear the count is
# 0 and ProcessMaskWindow returns false (:1484) whatever WH0-WH3 and WOBJLOG
# hold. So the check keys on THIS, not on the full set: a claimant naming
# only an edge register (WH0) shapes a window nothing switches on, and
# silencing the warning for it would be silencing it for a claim that cannot
# satisfy the precondition.
_COLOR_WINDOW_ENABLE = ("WOBJSEL",)

# What a window mode degenerates to when isInsideWindow is false everywhere,
# per (field, mode). Three of the four are EXACT; the clip/outside collapse
# is not, and _windowless_note says so rather than claiming it is.
_WINDOWLESS = {("clip", "outside"): "always", ("clip", "inside"): "never",
               ("prevent", "outside"): "always",
               ("prevent", "inside"): "never"}


def _windowless_note(fld: str, mode: str, g) -> tuple[str, str]:
    """(degenerate mode, caveat) for `fld = mode` with no color window.

    The collapse is exact in three of the four cases and NOT in the fourth,
    and the difference is a rendered pixel, so the message has to carry it:

      clip = "inside"     -> never:  the arm tests `if(isInsideWindow)` and
        never fires, so neither the pixel nor the halve is touched — the
        same as Never's `break` (SnesPpu.cpp:1318-1323 vs :1309). EXACT.
      prevent = "outside" -> always: both arms `return` and neither touches
        anything first (:1338-1342 vs :1350). EXACT.
      prevent = "inside"  -> never:  never fires, as clip/inside. EXACT.
      clip = "outside"    -> always: BOTH zero the main pixel, but the
        OutsideWindow arm ALSO forces the halve off (`halfShift = 0`,
        :1314) where Always zeroes only the pixel (:1325). halfShift is the
        `>> halfShift` applied to the sum at :1374-1376, so with `half`
        set the two produce different pixels: outside leaves a full-
        intensity addend, always halves it. In SUBTRACT mode the clamp
        makes it moot — `max(0 - x, 0)` is 0 and 0 >> n is 0 either way
        (:1368-1370) — so the divergence is `half` AND op = "add", which is
        exactly what this checks rather than asserting either way.
    """
    degen = _WINDOWLESS[(fld, mode)]
    if fld == "clip" and mode == "outside" and g.half and g.op == "add":
        return degen, (
            " — but NOT exactly: the outside arm also forces the halve off "
            "(halfShift = 0, SnesPpu.cpp:1314) where \"always\" zeroes only "
            "the pixel (:1325), and this blend declares half = true with "
            "op = \"add\", so it renders a FULL-intensity addend where "
            "\"always\" would render a halved one (the >> halfShift at "
            ":1374-1376)")
    return degen, ""


def _vocab_of(who: str) -> str | None:
    """Which composed vocabulary a synthesized claim's `who` belongs to, or
    None for an ordinary feature. Two vocabularies now synthesize per-scene
    ownership claims — screen/blend over TM/TS/CGWSEL/CGADSUB, video/offset
    over BGMODE and BG3's fetch registers — and the register gate has to tell
    them apart, because the MIGRATION a raw claimant is pointed at differs."""
    return next((v for v in _VOCABS if who.startswith(v)), None)


def _is_vocab_who(who: str) -> bool:
    return _vocab_of(who) is not None


def compose_screen_blend(screen: list[tuple], blend: list[tuple],
                         reg: list[tuple], scope: str,
                         direct: list[tuple] = ()) -> dict | None:
    """Compose a scene's screen/blend claims, or REFUSE (R1-R5).

    `screen`/`blend`/`reg` are [(claim, who)] over the globals+scene UNION —
    the check_reg_ownership convention, for the same reason (F2: a global
    designation and a scene-scoped second designation must still refuse).
    Returns None when the scene carries no vocabulary claim; else the
    composed dict: the four register values, the registers the synthesized
    ownership claim holds, warnings for the allocation report, and the
    refusal-check census. Refusal messages name the claiming features and
    the hardware mechanism — the messages are the deliverable.

    `direct` is the scene's DIRECT COLOR declarers — the [(video claim, who)]
    pairs whose `direct_color` is true, and empty for every scene that
    declares none. It is the one input here that is not a claim of THIS
    vocabulary: it is declared on `[[claims.video]]`, because what it decides
    is how an 8bpp layer's pixel bytes are read — a property of the mode,
    gated by the mode, and meaningless in a mode with no 8bpp layer (O12). It
    is COMPOSED here because CGWSEL is composed here and nowhere else:
    splitting one register between two compositions would give it two owners,
    which is the shape every refusal in this file exists to prevent. So the
    declaration lives where the fact does and the write stays with the port's
    one owner — and DECLARING IT IS CLAIMING CGWSEL, blend claim or no blend
    claim.
    """
    if not screen and not blend and not direct:
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
        g, _gwho = blend[0]
        # R4 — a sub-screen blend needs a sub screen. Where the sub screen
        # holds no pixel the hardware substitutes the FIXED COLOR and
        # disables halving (Mesen2 SnesPpu.cpp ApplyColorMathToPixel,
        # :1352-1362), so a sub-source blend in a scene with no
        # sub-designated layer never sees its declared source.
        if g.source == "sub" and not subs:
            # NAME EVERY CLAIMANT, as R1/R2/R3/R6 do. R2 has already proven
            # the scene's blend claims agree on `source`, so every one of
            # them declares the offending value and every one of them is an
            # author who has to act — naming blend[0] alone sends a
            # three-feature scene to one of three tomls, arbitrarily.
            offenders = [(c, who) for c, who in blend if c.source == "sub"]
            claimants = ", ".join(f"{c.name} ({who})" for c, who in offenders)
            raise AllocationError(
                f"BLEND source contention in scene '{scope}': {claimants} "
                f"declare{'' if len(offenders) > 1 else 's'} "
                f"source = \"sub\" but no layer in this "
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
    if blend:
        g, _ = blend[0]

        def declarers(fld: str, val) -> str:
            """Every blend claim declaring `fld = val`, named. R2 has proven
            the scene's claims agree on all five global fields, so that is
            every one of them — and every one is an author who has to act.
            The same reason R1/R2/R3/R4/R6 name both sides."""
            return ", ".join(f"{c.name} ({who})" for c, who in blend
                             if getattr(c, fld) == val)

        # The always-modes: legal, expressible hardware states a rail may
        # want deliberately (prevent = "always" IS the boot off state, and
        # composing it is how a scene disarms an inherited blender — §4), so
        # they compose. But they are also the shape R7 refuses on the `math`
        # axis — a declared blend that can never fire — so the author hears
        # about it. R7 stays a refusal because an empty `math` list is a
        # MALFORMED declaration with no hardware state behind it; these two
        # name a real state the PPU can hold.
        if g.prevent == "always":
            warnings.append(
                f"blend {declarers('prevent', 'always')} declares "
                f"prevent = \"always\": "
                f"CGWSEL bits 5-4 = 3 makes the color-math unit return "
                f"before any math for every pixel (Mesen2 SnesPpu.cpp:1350), "
                f"so this blend is programmed and can never fire. That is "
                f"the boot OFF state and composing it deliberately is "
                f"legitimate — disarming a blender inherited across a "
                f"transition is the case (docs/99 §4) — but if the blend is "
                f"meant to be visible, this is why it is not")
        if g.clip == "always":
            warnings.append(
                f"blend {declarers('clip', 'always')} declares "
                f"clip = \"always\": "
                f"CGWSEL bits 7-6 = 3 zeroes the main-screen pixel for every "
                f"pixel BEFORE the color-math enable is even tested "
                f"(SnesPpu.cpp:1325, ahead of the AllowColorMath test at "
                f":1328), which is an unconditional full-screen blackout, "
                f"not a blend")
        # The window precondition. clip/prevent of "outside"/"inside" read
        # the COLOR WINDOW, which this vocabulary does not compose (docs/99
        # §8). Unprogrammed, isInsideWindow is false everywhere and the mode
        # collapses to a fixed one — so this is a warning, not a refusal:
        # the window may be programmed by a claimant this check cannot
        # attribute, and proving window ownership reaches into a claim
        # surface the vocabulary has not opened.
        # Keyed on the ENABLE register, not on the whole window set: an edge
        # or logic register shapes a window that WOBJSEL still has to switch
        # on, so a claim naming only WH0 leaves the precondition exactly as
        # unsatisfiable as no claim at all.
        win = sorted({c.name for c, who in reg
                      if not _is_vocab_who(who)
                      and _register_conflicts(c.registers,
                                              _COLOR_WINDOW_ENABLE)})
        for fld in ("clip", "prevent"):
            mode = getattr(g, fld)
            if (fld, mode) in _WINDOWLESS and not win:
                degen, caveat = _windowless_note(fld, mode, g)
                warnings.append(
                    f"blend {declarers(fld, mode)} declares "
                    f"{fld} = \"{mode}\", "
                    f"which reads the COLOR WINDOW — and no claim in this "
                    f"scene names WOBJSEL, the register that ENABLES it "
                    f"(ActiveLayers[5], from WOBJSEL alone; Mesen2 "
                    f"SnesPpu.cpp:1487-1498). Programming a usable window "
                    f"needs {', '.join(_COLOR_WINDOW_REGS)} — WOBJSEL bits "
                    f"5/7 to enable, WOBJLOG bits 2-3 to combine the two "
                    f"windows (:2169-2172), WH0-WH3 for their edges "
                    f"(SnesPpuTypes.h:109-124) — but WOBJSEL is the one "
                    f"whose absence settles it: with those bits clear "
                    f"activeWindowCount is 0 (:1278) and ProcessMaskWindow "
                    f"returns false (:1484) whatever the others hold, so "
                    f"every pixel reads as OUTSIDE the window and "
                    f"{fld} = \"{mode}\" behaves as "
                    f"{fld} = \"{degen}\"{caveat}. The vocabulary composes "
                    f"no window registers by design (docs/99 §8): declare "
                    f"them as a [[claims.reg]] on the feature that owns the "
                    f"window")

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
                  | (0x02 if g.source == "sub" else 0)
                  | (0x01 if direct else 0))
    else:
        # Screen claims with no blend: the explicit OFF state
        # vendor/rom/ppu_reset.inc establishes at boot — prevent = always
        # ($30) structurally disables the math, CGADSUB gates nothing.
        # BIT 0 IS COMPOSED ON BOTH PATHS. Direct color is not a property of
        # the blender and does not need one: it is read by GetRgbColor
        # (SnesPpu.cpp:1071) whatever CGADSUB holds, so a scene that declares
        # it with no blend at all still gets the bit — and, since it is the
        # only thing in that scene with an opinion about CGWSEL, still owns
        # the port to write it from.
        cgwsel, cgadsub = 0x30 | (0x01 if direct else 0), 0x00

    regs = ((SCREEN_REGS if screen else ())
            + (BLEND_REGS if blend else
               (("CGWSEL",) if direct else ())))
    feats = sorted({who for _, who in [*screen, *blend, *direct]})
    return {"tm": tm, "ts": ts, "cgwsel": cgwsel, "cgadsub": cgadsub,
            "direct": [(c, who) for c, who in direct],
            "registers": regs, "features": feats,
            "screen": [(c, who) for c, who in screen],
            "blend": [(c, who) for c, who in blend],
            "warnings": warnings,
            "designations": len(screen), "blends": len(blend),
            "checks": checks}


# --------------------------------------------------------------------------
# the video/offset vocabulary — per-scene composition (C6)
# --------------------------------------------------------------------------

# The synthesized composed claim's consumer tag, and the second entry in
# _VOCABS. check_reg_ownership keys its mixing diagnostics off these prefixes,
# so a raw claim on a composed port refuses through the SAME reg-x-reg
# intersection every raw pair goes through.
MODE_WHO = "video/offset"

_VOCABS = (VOCAB_WHO, MODE_WHO)

# BGMODE bits 4-7: one 16x16-tile select per BG layer, in layer order.
_TILES16_BIT = {"bg1": 0x10, "bg2": 0x20, "bg3": 0x40, "bg4": 0x80}

# The modes in which CGWSEL bit 0 means anything: the ones that render a layer
# at 8bpp. DERIVED from MODE_BPP rather than written out, so this set cannot
# drift from the table every other mode check in this file decides on.
# GetRgbColor's direct-colour arm is guarded by
# `if constexpr(bpp == 8 && directColorMode)` and nothing else
# (SnesPpu.cpp:1071), and mode 7 is in the set by its OWN path: RenderTilemap
# hands the flag down for modes 3 and 4 (:2414), while RenderTilemapMode7
# selects its direct-colour arm for layerIndex 0 (:2466) and computes the
# colour at :1243.
DIRECT_COLOR_MODES = tuple(sorted(m for m, depths in MODE_BPP.items()
                                  if 8 in depths.values()))


def _mode_shape(mode: int) -> str:
    """'bg1 4bpp + bg2 4bpp' — a mode's layer set with its depths, for the
    refusal messages. Derived from MODE_BPP rather than written out, so a
    message cannot drift from the table the checks decide on."""
    return " + ".join(f"{lyr} {MODE_BPP[mode][lyr]}bpp"
                      for lyr in MODE_LAYERS[mode])


def check_chr_depth(video: list[tuple], vram: list[tuple],
                    scope: str) -> tuple[int, list[str]]:
    """A CHR claim's DEPTH against the depth its mode renders that layer at.

    O9. A 4bpp tile is 32 bytes and an 8bpp tile is 64, and the PPU reads
    whatever the MODE says regardless of what the claim reserved — so mode 4
    (bg1 8bpp) beside a 32-byte BG1 claim is not a tight fit, it is every tile
    made of half of one tile and half of the next, with the second half of the
    set never reached. Nothing in this tree could find that before, because
    `MODE_BPP` was imported for exactly one purpose — building the "(bg1 4bpp
    + bg2 4bpp)" text inside refusal MESSAGES — and was never checked against
    anything. `tile_bytes` was validated as one of 16/32/64 and stopped there.

    THE OBJ ARM IS MODE-INDEPENDENT and holds without a video claim at all:
    SnesPpu.cpp:770 fetches sprite pixels through GetTilePixelColor<4> with
    the depth written into the template argument, so OBJ is 4bpp in all eight
    modes and a 16- or 64-byte OBJ claim is wrong in every one of them.

    THE RATCHET. `layers` is optional, so this cannot refuse what it cannot
    see; a scene that declares a mode and carries a sized BG CHR claim without
    it gets a WARNING naming the claim. That is the first rung, and the same
    shape the width lint's routine contracts were adopted through — a check
    that starts by counting what it is not reaching.

    A claim sized in `words` rather than `tiles` has no declared depth at all
    and is invisible here. That is a stated limit, not an oversight: `words`
    is the escape hatch for a claim whose shape is a hardware window rather
    than a tile count (a whole OBJ name table, the Mode 7 region).

    Returns (checks_run, warnings); raises AllocationError on a disagreement.
    """
    checks = 0
    warnings: list[str] = []
    mode = video[0][0].mode if video else None
    for c, who in vram:
        if c.kind != "chr" or c.tile_bytes is None:
            continue
        if c.obj:
            checks += 1
            if c.tile_bytes != 32:
                raise AllocationError(
                    f"CHR DEPTH contention in scene '{scope}': {c.name} "
                    f"({who}) declares obj = true and tile_bytes = "
                    f"{c.tile_bytes}, which is {c.tile_bytes // 8}bpp. OBJ is "
                    f"4bpp in EVERY video mode — SnesPpu.cpp:770 fetches "
                    f"sprite pixels through GetTilePixelColor<4> with the "
                    f"depth in the template argument, so no mode changes it — "
                    f"and a sprite tile is 32 bytes. Declare tile_bytes = 32, "
                    f"or size the claim in `words` if it is a whole name "
                    f"table rather than a tile count")
            continue
        if mode is None:
            continue                     # no mode declared: nothing to check
        if not c.layers:
            warnings.append(
                f"chr {c.name} ({who}) is {c.tile_bytes // 8}bpp and names no "
                f"`layers`, so its depth is NOT checked against mode {mode} "
                f"({_mode_shape(mode)}). The PPU reads a tile at the depth "
                f"the MODE says and the claim only reserves the space — "
                f"declare layers = [...] and the two are joined")
            continue
        for lyr in c.layers:
            checks += 1
            if lyr not in MODE_LAYERS[mode]:
                vc, vwho = video[0]
                raise AllocationError(
                    f"CHR DEPTH contention in scene '{scope}': {c.name} "
                    f"({who}) holds tiles for {lyr}, but {vc.name} ({vwho}) "
                    f"declares mode {mode}, which renders "
                    f"{_mode_shape(mode)}. Mode {mode} never calls "
                    f"RenderTilemap for {lyr} (Mesen2 SnesPpu.cpp "
                    f"RenderMode{mode}), so these tiles are uploaded and "
                    f"never fetched. Drop {lyr} from `layers`, or declare a "
                    f"mode that renders it")
            want = MODE_BPP[mode][lyr] * 8
            if c.tile_bytes != want:
                vc, vwho = video[0]
                raise AllocationError(
                    f"CHR DEPTH contention in scene '{scope}': {c.name} "
                    f"({who}) holds {lyr} tiles at tile_bytes = "
                    f"{c.tile_bytes} ({c.tile_bytes // 8}bpp), but {vc.name} "
                    f"({vwho}) declares mode {mode}, which renders "
                    f"{_mode_shape(mode)} — {lyr} at {MODE_BPP[mode][lyr]}bpp, "
                    f"{want} bytes a tile. The PPU fetches at the MODE's "
                    f"depth and the claim only reserves the space, so this "
                    f"composition draws every tile from "
                    f"{'half of one tile and half of the next' if want > c.tile_bytes else 'the first half of each pair'}"
                    f". Declare tile_bytes = {want}, or a mode that renders "
                    f"{lyr} at {c.tile_bytes // 8}bpp")
    return checks, warnings


def compose_video_offset(video: list[tuple], offset: list[tuple],
                         screen: list[tuple], scope: str,
                         bands: list[tuple] = ()) -> dict | None:
    """Compose a scene's video-mode and offset-per-tile claims, or REFUSE.

    `video`/`offset`/`screen` are [(claim, who)] over the globals+scene UNION,
    the check_reg_ownership convention and for the same reason: a global mode
    claim and a scene-scoped second one must still refuse.

    Returns None when the scene carries neither claim; else the composed dict
    — the BGMODE byte, the registers the synthesized ownership claim holds,
    the offset table's emitted field constants, warnings for the allocation
    report, and the refusal-check census.

    O5's register arm is NOT here: it arises in check_reg_ownership, where a
    feature that draws on BG3 meets this composition's synthesized claim as an
    ordinary intersection. What is here is the arm no register can see — a
    [[claims.screen]] designation of a layer the mode does not render.
    """
    if not video and not offset and not bands:
        return None
    checks = 0
    warnings: list[str] = []

    # O10 — bands are rows OF A TABLE. A scene that selects between rows of
    # an offset table it does not have is declaring a transfer onto a port
    # that means nothing here (BG3VOFS scrolls a drawable BG3 in every other
    # mode), and two bands claims are two HDMA channels on one port.
    if bands:
        checks += 1
        bc, bwho = bands[0]
        if not offset:
            raise AllocationError(
                f"OFFSET BANDS in scene '{scope}': {bc.name} ({bwho}) "
                f"declares {bc.rows} bands, but no [[claims.offset]] holds "
                f"this scene. A band is one ROW of the scene's offset table "
                f"selected per scanline through BG3VOFS (rowOffset = "
                f"VScroll >> 3, SnesPpu.cpp:262); with no table BG3 is a "
                f"drawable layer here, or absent from the mode, and the "
                f"channel this would synthesize on BG3VOFS would scroll a "
                f"picture, not select a row. Compose the feature that "
                f"declares the table into this scene, or drop the bands "
                f"claim (docs/100 §5, O10)")
        if len(bands) >= 2:
            c, who = bands[1]
            raise AllocationError(
                f"OFFSET BANDS contention in scene '{scope}': {bc.name} "
                f"({bwho}) and {c.name} ({who}) both declare bands over this "
                f"scene's one offset table. There is one BG3VOFS and one row "
                f"it names per scanline, so two band sets are two HDMA "
                f"channels driving one write-twice port on the same lines — "
                f"the contention split-mode died on. One feature declares "
                f"the scene's bands (docs/100 §5, O10)")

    # O1 — one video mode, one owner. BGMODE is a write-only byte and the
    # OWNERSHIP of it, not the value, is the resource: two features declaring
    # the same mode still refuse, exactly as two RegClaims on one port do.
    if len(video) >= 2:
        checks += 1
        (g, gwho) = video[0]
        for c, who in video[1:]:
            agree = " — even though they agree" if g.mode == c.mode else ""
            raise AllocationError(
                f"VIDEO MODE contention in scene '{scope}': {g.name} "
                f"({gwho}) declares mode {g.mode} and {c.name} ({who}) "
                f"declares mode {c.mode}{agree}. A scene has ONE video mode: "
                f"BGMODE bits 0-2 hold it for the whole frame, and the "
                f"ownership of that byte is the resource. One feature "
                f"declares the scene's display shape; a second feature that "
                f"needs a mode depends on the first. A mid-frame mode change "
                f"is a per-scanline HDMA rewrite and keeps the raw "
                f"[[claims.reg]] shape (docs/100)")

    # O2 — one offset table, one owner. There is one BG3 fetch path.
    if len(offset) >= 2:
        checks += 1
        (g, gwho) = offset[0]
        c, who = offset[1]
        raise AllocationError(
            f"OFFSET-PER-TILE contention in scene '{scope}': {g.name} "
            f"({gwho}) and {c.name} ({who}) both declare BG3's tilemap to be "
            f"this scene's per-column offset table. There is one BG3 fetch "
            f"path per scene, reading one pair of rows chosen by BG3VOFS "
            f"(Mesen2 SnesPpu.cpp GetHorizontalOffsetByte / "
            f"GetVerticalOffsetByte, :257-276), so the second table is one "
            f"the hardware will never look at. One feature owns the table; a "
            f"second feature that needs per-column displacement writes into "
            f"that one")

    mode = video[0][0].mode if video else None

    if offset:
        oc, owho = offset[0]
        checks += 5                      # O3 + O4 + O6 + O7's TWO arms
                                         # (both-under-4, per_column-under-2/6)

        # O3 — offset-per-tile needs a DECLARED mode. Without one the mode
        # restriction cannot be proven at all, which is the hole this
        # vocabulary exists to close: the claim would compose in silence in a
        # scene whose BGMODE some raw claim writes to a value nobody declared.
        if not video:
            raise AllocationError(
                f"OFFSET-PER-TILE in scene '{scope}': {oc.name} ({owho}) "
                f"declares BG3's tilemap to be a per-column offset table, "
                f"but no [[claims.video]] claim in this scene declares the "
                f"video mode. Only modes 2, 4 and 6 fetch offset words "
                f"(Mesen2 SnesPpu.cpp FetchTileData, :277-390) — in every "
                f"other mode the table is authored, uploaded and never read "
                f"— so the claim cannot be checked against a mode nobody "
                f"declared. Add a [[claims.video]] claim naming this "
                f"scene's mode (docs/100)")

        # O4 — the mode restriction, and the whole reason the mode had to
        # become a declaration. FetchTileData branches on BgMode and only
        # three of its eight arms call the offset fetchers.
        if mode not in OFFSET_MODES:
            vc, vwho = video[0]
            raise AllocationError(
                f"OFFSET-PER-TILE contention in scene '{scope}': {oc.name} "
                f"({owho}) declares BG3's tilemap to be a per-column offset "
                f"table, but {vc.name} ({vwho}) declares mode {mode} "
                f"({_mode_shape(mode)}). Offset-per-tile exists in modes "
                f"{list(OFFSET_MODES)} ONLY: FetchTileData branches on the "
                f"video mode and only those three arms call "
                f"GetHorizontalOffsetByte (Mesen2 SnesPpu.cpp, :277-390), so "
                f"under mode {mode} the PPU never reads a word of this "
                f"table and every column stays where the layer's own scroll "
                f"puts it. Declare mode 2 (bg1 4bpp + bg2 4bpp, an H word "
                f"and a V word per column), 4 (bg1 8bpp + bg2 2bpp, one word "
                f"whose bit 15 picks the axis) or 6 (bg1 4bpp, hi-res), or "
                f"drop the offset claim")

        # O7 — the two-axis states are TWO STATES, and each mode has exactly
        # one of them. This was a WARNING on the mode-4 arm and no check at
        # all on the other, which is the shape a declaration takes when it
        # cannot say what its author means: `both` had to cover a column
        # displaced on both axes (modes 2 and 6, a word fetched for each) AND
        # a table whose columns each carry one axis picked by bit 15 (mode 4,
        # one word fetched). Two different hardware states under one name, so
        # the composition could only read the second meaning aloud on every
        # build of a CORRECT declaration — a warning that was the definition
        # of the value rather than a report of a defect.
        #
        # `per_column` is the second state's own name, and with it each value
        # refuses in the other's modes. What that buys is the case the warning
        # was guarding and could not stop: a table MOVED BETWEEN MODES keeps
        # its declaration and changes its meaning, and now stops the build
        # instead.
        if mode == 4 and oc.axis == "both":
            vc, vwho = video[0]
            raise AllocationError(
                f"OFFSET-PER-TILE contention in scene '{scope}': {oc.name} "
                f"({owho}) declares axis = \"both\", but {vc.name} ({vwho}) "
                f"declares mode 4. \"both\" is a column displaced on BOTH "
                f"axes at once, and mode 4 has no such state: it fetches ONE "
                f"word per column and bit 15 selects that word's axis (Mesen2 "
                f"SnesPpu.cpp FetchTileData case 2 under BgMode 4, and the "
                f"bit-15 test at :156-161), so a column is displaced "
                f"vertically or horizontally and never both. What mode 4 CAN "
                f"do — and modes 2 and 6 cannot — is carry both axes ACROSS "
                f"THE TABLE, one per column: declare axis = \"per_column\", "
                f"which emits MASK, HMASK and VSEL and says which bit picks. "
                f"This is a refusal rather than a warning because the two "
                f"declarations mean different things: a table moved between "
                f"mode 2 and mode 4 keeps its `axis` and changes its meaning, "
                f"and that is the migration this stops (docs/100)")

        if mode in (2, 6) and oc.axis == "per_column":
            vc, vwho = video[0]
            raise AllocationError(
                f"OFFSET-PER-TILE contention in scene '{scope}': {oc.name} "
                f"({owho}) declares axis = \"per_column\", but {vc.name} "
                f"({vwho}) declares mode {mode}. \"per_column\" is a table "
                f"whose columns each carry ONE axis, chosen by bit 15 of the "
                f"word — and bit 15 is read in mode 4 alone (Mesen2 "
                f"SnesPpu.cpp:156-161). Mode {mode} fetches an H word AND a V "
                f"word for every column (FetchTileData cases 2 and 3, "
                f":277-390), so the axis is not a per-column choice there: "
                f"every column gets both, and the word's bit 15 selects "
                f"nothing. Declare axis = \"both\" for a column displaced on "
                f"both axes, or \"h\"/\"v\" for a table that uses one — or "
                f"declare mode 4, where the choice exists. This is a refusal "
                f"rather than a warning because the two declarations mean "
                f"different things and a table moved between the modes keeps "
                f"its `axis` (docs/100)")

        # O6 — the driven layer must exist in the mode. An enable bit for a
        # layer the mode never renders is the R5 shape: the bit sits set, the
        # PPU applies the offset to a layer whose pixels no pass produces.
        for lyr in oc.layers:
            if lyr not in MODE_LAYERS[mode]:
                vc, vwho = video[0]
                raise AllocationError(
                    f"OFFSET-PER-TILE contention in scene '{scope}': "
                    f"{oc.name} ({owho}) drives {lyr} from the offset table, "
                    f"but {vc.name} ({vwho}) declares mode {mode}, which "
                    f"renders {_mode_shape(mode)}. Mode {mode} never calls "
                    f"RenderTilemap for {lyr} (Mesen2 SnesPpu.cpp "
                    f"RenderMode{mode}), so displacing it displaces a layer "
                    f"no pass draws. Drop {lyr} from `layers`, or declare a "
                    f"mode that renders it")

        # O11 — 16x16 TILES AND A HORIZONTALLY DISPLACED LAYER. The one
        # interaction between the two halves of this vocabulary, and it is
        # not symmetric between the axes:
        #
        #   the TILEMAP ENTRY a column reads is picked from the DISPLACED
        #        scroll — `column = columnIndex + (hScroll >> 3)`, then
        #        `column >>= 1` for LargeTiles (SnesPpu.cpp:195, :199), and
        #        `row = (realY + vScroll) >> 4` (:186) — so both axes reach it
        #   WHICH HALF of a 16-wide tile is drawn is picked from the LAYER's
        #        OWN register: `useSecondTile = (((column << 3) +
        #        config.HScroll) & 0x08) == 0x08` (:235) — `config.HScroll`,
        #        not the displaced `hScroll`
        #   the VERTICAL half IS displaced: it is taken from
        #        `tileData.VScroll` (:243, :250), which GetTilemapData wrote
        #        from the displaced value (:206)
        #
        # So 16x16 is COHERENT with a vertical offset and INCOHERENT with a
        # horizontal one: a horizontally displaced column fetches the right
        # tile and draws the wrong half of it. MEASURED on this emulator, not
        # only read: a 16x16 BG1 driven by a horizontal word of 8 rendered
        # every EVEN screen column as though the word were 0 and every ODD one
        # as though it were 16 — 30 of 31 screen columns fit that model against
        # 16 of 31 for a coherent one, and of the 15 columns actually carrying
        # a displacement, 14 fit it and ZERO fit the coherent model (the odd
        # one out is a rail override that zeroes its word). The same probe
        # measured a VERTICAL word coherent at 27 of 27 over six scanlines.
        #
        # A REFUSAL where the composition can PROVE the layer takes horizontal
        # words — `h` (every word) and `both` (every column, both axes). Under
        # `per_column` the axis is bit 15 of each WORD, which is DATA in a
        # blob the composition cannot read, so it warns and names the two
        # conditions the table has to satisfy instead. That is the docs/99
        # rule (refuse what the silicon cannot express, warn about what it
        # can) resolved the way the bg2-under-mode-7 arm resolves it: where
        # the thing that would make the composition correct is outside what
        # this vocabulary models, over-refusal is its own defect.
        if video:
            vc, vwho = video[0]
            checks += 1                      # O11 live
            for lyr in [x for x in oc.layers if x in vc.tiles16]:
                if oc.axis in ("h", "both"):
                    raise AllocationError(
                        f"VIDEO/OFFSET contention in scene '{scope}': "
                        f"{vc.name} ({vwho}) declares 16x16 tiles for {lyr}, "
                        f"and {oc.name} ({owho}) drives {lyr} from the offset "
                        f"table on a HORIZONTAL axis (axis = "
                        f"\"{oc.axis}\"). A 16x16 layer picks its TILEMAP "
                        f"ENTRY from the displaced scroll (column = "
                        f"columnIndex + (hScroll >> 3), then column >>= 1 — "
                        f"Mesen2 SnesPpu.cpp:195, :199) but picks WHICH HALF "
                        f"of that 16-wide tile to draw from the LAYER's own "
                        f"register (useSecondTile = (((column << 3) + "
                        f"config.HScroll) & 8) == 8, :235), so a displaced "
                        f"column fetches the right tile and draws the wrong "
                        f"half of it: measured here, a word of 8 moves an "
                        f"EVEN column by 0 and an ODD column by 16, which "
                        f"pulls the two halves of every large tile apart "
                        f"rather than shearing the picture. The VERTICAL axis "
                        f"has no such split — the vertical half comes from "
                        f"the displaced tileData.VScroll (:243, :206) — so "
                        f"drive {lyr} vertically, drive the horizontal axis "
                        f"on a layer this scene does not declare 16x16, or "
                        f"drop {lyr} from `tiles16` (docs/100)")
                notes = []
                if oc.axis == "per_column":
                    notes.append(
                        "any HORIZONTAL word it carries for that layer is "
                        "incoherent — the tilemap entry moves with the "
                        "displaced scroll and the half-select does not "
                        "(SnesPpu.cpp:195/:199 against :235), so a value of 8 "
                        "renders as 0 on an even screen column and 16 on an "
                        "odd one; only values whose bit 3 equals the layer's "
                        "own BGnHOFS bit 3 survive, i.e. whole 16-pixel steps")
                notes.append(
                    "two adjacent screen columns SHARE one tilemap entry "
                    "(column >>= 1, :199) but each keeps its own row from its "
                    "OWN displaced vScroll (row = (realY + vScroll) >> 4, "
                    ":186), so the two halves of a large tile must carry the "
                    "SAME vertical displacement or the tile reads two "
                    "different map rows and tears down the middle")
                warnings.append(
                    f"{vc.name} ({vwho}) declares 16x16 tiles for {lyr} and "
                    f"{oc.name} ({owho}) drives {lyr} from the offset table "
                    f"(axis = \"{oc.axis}\"). Two conditions on the TABLE'S "
                    f"WORDS follow, and the composition cannot read a word: "
                    + "; and ".join(notes))

        # O5, the designation arm — BG3 IS the table. The register arm of the
        # same rule fires in check_reg_ownership against the synthesized
        # claim below; this one catches the claimant that draws on BG3 by
        # designating it rather than by writing its registers.
        for c, who in screen:
            if c.layer == "bg3":
                raise AllocationError(
                    f"OFFSET-PER-TILE contention in scene '{scope}': "
                    f"{c.name} ({who}) designates bg3 -> {c.on}, but "
                    f"{oc.name} ({owho}) declares BG3's tilemap to be this "
                    f"scene's per-column OFFSET TABLE. In modes "
                    f"{list(OFFSET_MODES)} BG3 IS NOT A DRAWABLE LAYER: the "
                    f"PPU reads its map entries as scroll offsets and never "
                    f"renders it (Mesen2 SnesPpu.cpp RenderMode2/4/6 draw "
                    f"BG1/BG2 and OBJ only), so the TM/TS bit this "
                    f"designation composes is inert and the 'tiles' it would "
                    f"show are the offset words. One or the other holds this "
                    f"scene: draw the layer on a BG the mode renders, or put "
                    f"the offset table in a scene of its own (docs/100)")

        # Hardware behaviour an author of this table has to design around —
        # real, not refusable, and the reason it is a warning is that both
        # facts are properties of a CORRECT declaration.
        if oc.axis in ("h", "both", "per_column"):
            warnings.append(
                f"offset {oc.name} ({owho}) declares a HORIZONTAL axis: a "
                f"horizontal offset is 8-PIXEL granular. The hardware "
                f"composes hScroll = (BGnHOFS & 7) | (word & $3F8) — the "
                f"LAYER keeps its own fine three bits and the word's are "
                f"dropped (Mesen2 SnesPpu.cpp:157, :164) — so a column "
                f"cannot be sheared by less than a tile's width. A vertical "
                f"offset has no such rule: vScroll = word & $3FF, to the "
                f"pixel (:160, :167)")
        warnings.append(
            f"offset {oc.name} ({owho}): the offset word REPLACES the "
            f"layer's scroll for that column rather than adding to it "
            f"(vScroll = word & $3FF), and a column whose enable bit is "
            f"clear falls back to the layer's own BGnVOFS/BGnHOFS — so the "
            f"table holds absolute positions, not deltas")
        undesignated = [lyr for lyr in oc.layers
                        if lyr not in {c.layer for c, _ in screen}]
        if undesignated:
            warnings.append(
                f"offset {oc.name} ({owho}) drives {undesignated}, which no "
                f"[[claims.screen]] claim in this scene designates to a "
                f"screen. Displacing a layer that is on neither screen "
                f"displaces nothing visible — this is a warning rather than "
                f"a refusal because the layer may be designated by a raw TM "
                f"claim the vocabulary cannot attribute")

    if video:
        checks += 2                      # O8 + O12 live
        vc, vwho = video[0]
        # O8 — a designation the mode does not render. R5's rule on the mode
        # axis: the enable bit is set and no pass ever produces a pixel for
        # it. OBJ is exempt — sprites render in every mode.
        for c, who in screen:
            if c.layer == "obj" or c.layer in MODE_LAYERS[vc.mode]:
                continue
            if vc.mode == 7 and c.layer == "bg2":
                warnings.append(
                    f"{c.name} ({who}) designates bg2 -> {c.on} under mode "
                    f"7, where BG2 exists ONLY with EXTBG enabled ($2133 "
                    f"bit 6; Mesen2 SnesPpu.cpp RenderMode7, :856-858). "
                    f"EXTBG has no model in this tree — BG2's pixels ARE "
                    f"BG1's, split by bit 7, an identity the claim classes "
                    f"cannot express (docs/09 G5) — so this composes and "
                    f"warns rather than refusing. Without EXTBG the "
                    f"designation is inert")
                continue
            raise AllocationError(
                f"SCREEN designation contention in scene '{scope}': "
                f"{c.name} ({who}) designates {c.layer} -> {c.on}, but "
                f"{vc.name} ({vwho}) declares mode {vc.mode}, which renders "
                f"{_mode_shape(vc.mode)}. Mode {vc.mode} never calls "
                f"RenderTilemap for {c.layer} (Mesen2 SnesPpu.cpp "
                f"RenderMode{vc.mode}), so the TM/TS enable bit this "
                f"designation composes is INERT — set, and no pass ever "
                f"produces a pixel through it. Designate a layer the mode "
                f"renders, or declare a mode that renders {c.layer} "
                f"(docs/100)")

        # O12 — direct color under a mode with no 8bpp layer. A WARNING, and
        # the decision is the tree's own rule applied literally: refuse what
        # the silicon cannot express, warn about what it can. CGWSEL b0 set
        # under mode 1 is a legal, expressible, perfectly stable PPU state —
        # the bit holds, GetRgbColor's `bpp == 8` guard is false for every
        # layer the mode renders, and nothing consults it. That is exactly
        # the shape of the two notes beside this one (bg3_priority outside
        # mode 1, a tiles16 bit for a layer the mode does not draw), and it is
        # NOT the shape of O4/O6/O8, each of which refuses a declaration whose
        # own subject the mode deletes.
        if vc.direct_color and vc.mode not in DIRECT_COLOR_MODES:
            warnings.append(
                f"{vc.name} ({vwho}) declares direct_color under mode "
                f"{vc.mode} ({_mode_shape(vc.mode)}): CGWSEL bit 0 is read "
                f"by GetRgbColor under `bpp == 8 && directColorMode` alone "
                f"(Mesen2 SnesPpu.cpp:1071) and mode {vc.mode} renders no "
                f"8bpp layer, so the bit holds and no pass consults it. "
                f"Direct color reaches a layer in modes "
                f"{list(DIRECT_COLOR_MODES)} only — 3 and 4 through "
                f"RenderTilemap (:2414), 7 through RenderTilemapMode7's own "
                f"arm for layer 0 (:2466). That is a legal, expressible PPU "
                f"state — it composes, and this says why it does nothing")
        # ...and mode 7 reaches it, but reaches only HALF of it. There is no
        # tilemap palette field on the Mode 7 path, so the three low channel
        # bits the tilemap supplies in modes 3 and 4 are unavailable and the
        # colour is 3-3-2 with the LSBs clear.
        if vc.direct_color and vc.mode == 7:
            warnings.append(
                f"{vc.name} ({vwho}) declares direct_color under mode 7, "
                f"where the colour is 3-3-2 and NOTHING ELSE. Modes 3 and 4 "
                f"build it from the pixel AND the tilemap entry's 3-bit "
                f"palette field, which supplies the low bit of each channel "
                f"(Mesen2 SnesPpu.cpp:1071-1076, paletteIndex from "
                f"`(tilemapData >> 10) & 0x07` at :1023); the Mode 7 path "
                f"has no tilemap palette field and computes "
                f"`((c & 0x07) << 2) | ((c & 0x38) << 4) | ((c & 0xC0) << 7)` "
                f"(:1243), so those three bits are zero and each channel's "
                f"darkest step is the only one below its 3-bit quantum. The "
                f"declaration is right and the art budget is smaller than it "
                f"is in mode 3 or 4")
        if vc.bg3_priority and vc.mode != 1:
            warnings.append(
                f"{vc.name} ({vwho}) declares bg3_priority under mode "
                f"{vc.mode}: BGMODE bit 3 is read by RenderMode1 alone "
                f"(Mesen2 SnesPpu.cpp:799), so the bit holds and nothing "
                f"consults it. That is a legal, expressible PPU state — it "
                f"composes, and this says why it does nothing")
        for lyr in vc.tiles16:
            if lyr not in MODE_LAYERS[vc.mode]:
                warnings.append(
                    f"{vc.name} ({vwho}) declares 16x16 tiles for {lyr} "
                    f"under mode {vc.mode}, which renders "
                    f"{_mode_shape(vc.mode)}: the size bit holds and no "
                    f"pass reads it, because {lyr} is not drawn in this mode")

    # -- the composed values ------------------------------------------------
    bgmode = None
    if video:
        vc, _ = video[0]
        bgmode = vc.mode | (0x08 if vc.bg3_priority else 0)
        for lyr in vc.tiles16:
            bgmode |= _TILES16_BIT[lyr]

    fields: dict[str, int] = {}
    if offset:
        oc, _ = offset[0]
        for lyr in oc.layers:
            fields[lyr.upper()] = OFFSET_LAYER_BITS[lyr]
        # `per_column` publishes exactly what `both` publishes: mode 4's one
        # word carries either axis, so a table that uses both needs both value
        # masks and the bit that picks between them.
        if oc.axis in ("v", "both", "per_column"):
            fields["MASK"] = OFFSET_VALUE_MASK
        if oc.axis in ("h", "both", "per_column"):
            fields["HMASK"] = OFFSET_H_VALUE_MASK
        if mode == 4:
            fields["VSEL"] = OFFSET_VSEL_BIT
        if bands:
            # The band count and the row stride the HDMA table is built
            # from. Whether the rows a band names EXIST in the table's VRAM
            # claim is not reachable from here (docs/100 §14, the placement
            # limit); the parser holds the hardware ceiling.
            fields["BANDS"] = bands[0][0].rows
            fields["ROW_VOFS"] = OFFSET_ROW_VOFS

    regs = ((VIDEO_REGS if video else ())
            + (OFFSET_REGS if offset else ()))
    feats = sorted({who for _, who in [*video, *offset]})
    return {"bgmode": bgmode, "fields": fields, "registers": regs,
            "features": feats,
            "mode": mode,
            # ...and the size bits, so a test can join a ROM's $2105 on the
            # DECLARATION rather than on a literal.
            "tiles16": list(video[0][0].tiles16) if video else [],
            "axis": offset[0][0].axis if offset else None,
            "layers": list(offset[0][0].layers) if offset else [],
            "bands": bands[0][0].rows if bands else 1,
            "video": [(c, who) for c, who in video],
            "offset": [(c, who) for c, who in offset],
            "bands_claims": [(c, who) for c, who in bands],
            "warnings": warnings,
            "modes": len(video), "offsets": len(offset), "checks": checks}


def check_blend_edges(edges, scenes, greg) -> tuple[list[str], int]:
    """Per EDGE: does anyone establish the blender in the destination scene?

    The composed state is PER SCENE and nothing carries it across an edge.
    A scene that composes a blend programs CGWSEL/CGADSUB on enter; a
    successor that composes no blend half and has no raw CGWSEL/CGADSUB
    owner writes neither port, so the previous scene's blend persists into
    it. `vendor/rom/ppu_reset.inc` runs once, from the CPU bootstrap
    (vendor/rom/init.inc), so the boot off state is not re-established at a
    transition, and the vocabulary has no exit half — the raw claimants'
    self-disarm-at-exit shape (rgb_gradient's `rg_disarm`) has no analogue
    here.

    A WARNING, NOT A REFUSAL, and that is the design decision. Persistence
    across an edge can be exactly what a rail wants — a blend held through a
    fade, an effect that outlives the scene that armed it — and refusing a
    hardware-legal, sometimes-intended composition is its own defect class.
    So this names the edge and the remedy and leaves the choice with the
    author, like the OBJ-palette and layer-owner notes beside it.

    Reads the edges the allocator already has (the same list `ES_E_*` is
    emitted from), never a second enumeration. Returns (warnings, edges
    examined) — the count is the population, so a check that examined
    nothing reads as having examined nothing rather than as clean.
    """
    warnings: list[str] = []
    checked = 0
    for src, dst in edges:
        s_sb = scenes[src].screen_blend
        if s_sb is None or not s_sb["blend"]:
            continue                 # the source arms no blender: nothing to
        checked += 1                 # persist, so this edge is not a candidate
        d_sb = scenes[dst].screen_blend
        if d_sb is not None and d_sb["blend"]:
            continue                 # the destination composes its own state
        raw = sorted({c.name for c, who in [*greg, *scenes[dst].regs]
                      if not _is_vocab_who(who)
                      and _register_conflicts(c.registers, BLEND_REGS)})
        if raw:
            continue                 # a raw owner is answerable for the ports
        warnings.append(
            f"transition {src}->{dst}: scene '{src}' composes a blend "
            f"(CGWSEL=${s_sb['cgwsel']:02X} CGADSUB=${s_sb['cgadsub']:02X}) "
            f"but scene '{dst}' composes no [[claims.blend]] and no "
            f"[[claims.reg]] in it owns CGWSEL/CGADSUB — so nothing writes "
            f"those ports on entering '{dst}' and the blend PERSISTS into "
            f"it. The composed state is per scene and the boot reset runs "
            f"only at power-on. If that is deliberate (a blend held through "
            f"a transition), nothing to do; if not, give '{dst}' a "
            f"[[claims.blend]] composing the state it wants, or leave "
            f"CGWSEL/CGADSUB to a [[claims.reg]] owner that disarms at "
            f"scene exit (docs/99 §4)")
    return warnings, checked


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
                             else c.kind,
                             shape_bits=TILEMAP_SHAPES[c.shape][1]))

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
                             else c.kind,
                             shape_bits=TILEMAP_SHAPES[c.shape][1]))
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
    gvideo: list[tuple] = []
    goffset: list[tuple] = []
    gbands: list[tuple] = []
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
        gvideo += [(c, who) for c in f.video]
        goffset += [(c, who) for c in f.offset]
        gbands += [(c, who) for c in f.offset_bands]
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
        s_video: list[tuple] = []
        s_offset: list[tuple] = []
        s_bands: list[tuple] = []
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
            s_video += [(c, who) for c in f.video]
            s_offset += [(c, who) for c in f.offset]
            s_bands += [(c, who) for c in f.offset_bands]
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
        # DIRECT COLOR arrives from the VIDEO half and is composed in this
        # one — the declaration is a property of the mode and the emission
        # belongs to CGWSEL's one owner (compose_screen_blend's docstring
        # says why). Reading the video claims here, ahead of C6, cannot
        # reorder a refusal: O1 (two video claims in one scene) still fires
        # below, and nothing in this function refuses on `direct`.
        sm.screen_blend = compose_screen_blend(
            [*gscreen, *s_screen], [*gblend, *s_blend],
            [*greg, *sm.regs], sc.id,
            [(c, who) for c, who in [*gvideo, *s_video] if c.direct_color])
        if sm.screen_blend is not None:
            sm.screen_blend["checks"] += 1          # R6 live via the union
            sm.regs.append((
                RegClaim(name="screen_blend",
                         registers=sm.screen_blend["registers"],
                         scene_writes=sm.screen_blend["registers"]),
                f"{VOCAB_WHO} <- {', '.join(sm.screen_blend['features'])}"))

        # C6: compose the video/offset vocabulary over the same union, then
        # synthesize its per-scene ownership claim the same way. O5's
        # register arm (a feature drawing on BG3 beside an offset table) and
        # the raw-BGMODE mixing refusal both arise from the ordinary
        # reg-x-reg intersection in check_reg_ownership below.
        #
        # ORDER: after screen/blend, because O8 reads the scene's screen
        # claims and a scene whose designations are themselves contended
        # should hear R1 first — the designation set O8 judges is not
        # settled until R1 has passed.
        sm.video_offset = compose_video_offset(
            [*gvideo, *s_video], [*goffset, *s_offset],
            [*gscreen, *s_screen], sc.id, [*gbands, *s_bands])
        if sm.video_offset is not None:
            sm.video_offset["checks"] += 1     # O5's register arm, via the union
            vo_who = f"{MODE_WHO} <- {', '.join(sm.video_offset['features'])}"
            # BANDS: the composition drives BG3VOFS per scanline ITSELF, so
            # it synthesizes the HDMA claim that does it — one channel, mode
            # 2 (BG3VOFS is write-twice), active phase, the whole frame —
            # and marks its ownership `seed`: the scene's enter write is the
            # base the channel overrides from line 0. A second active claim
            # on BG3VOFS meets this one in assign_channels as an HDMA
            # register contention (O10). Without bands there is no seed, so
            # a foreign channel on the port still refuses in check 2 below.
            if sm.video_offset["bands"] > 1:
                bc, bwho = sm.video_offset["bands_claims"][0]
                hdma_claims.append((HdmaClaim(
                    name=f"{bc.name}_rowsel", channels=1,
                    registers=(OFFSET_ROWSEL_REG,),
                    band=(0, sub.visible_lines), phase="active",
                    mode=OFFSET_ROWSEL_MODE), vo_who))
                sm.video_offset["rowsel"] = f"{bc.name}_rowsel"
            sm.regs.append((
                RegClaim(name="video_offset",
                         registers=sm.video_offset["registers"],
                         scene_writes=sm.video_offset["registers"],
                         seed=sm.video_offset["bands"] > 1),
                vo_who))

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

        # O9 — the CHR depth join. Separate from compose_video_offset because
        # it reads a different claim class and holds in one arm (OBJ) with no
        # video claim at all; folded into the same census and report so an
        # author sees one video/offset section rather than two.
        #
        # AFTER check_reg_ownership, AND THAT ORDER IS LOAD-BEARING. Both
        # refuse `bg_text` composed into an offset-mode scene, and they say
        # different things about it. O9 says "these BG3 tiles are uploaded and
        # never fetched", which is true and is the shallower half; the register
        # arm says BG3 IS THIS SCENE'S OFFSET TABLE and names the two features
        # contending for BG3SC, which is the hazard and the choice. An author
        # who hears O9 first fixes it by dropping `layers` — silencing a check
        # instead of moving the feature. Composed first, this ran first and
        # took that refusal's place; it is here so the better message wins,
        # and O9 still fires wherever no register collision exists.
        chr_checks, chr_warn = check_chr_depth(
            [*gvideo, *s_video], [*g_vram, *s_vram], sc.id)
        if chr_checks or chr_warn:
            if sm.video_offset is None:
                sm.video_offset = {"bgmode": None, "fields": {}, "registers": (),
                                   "features": [], "mode": None, "axis": None,
                                   "tiles16": [],
                                   "layers": [], "video": [], "offset": [],
                                   "bands": 1, "bands_claims": [],
                                   "warnings": [], "modes": 0, "offsets": 0,
                                   "checks": 0, "chr_only": True}
            sm.video_offset["checks"] += chr_checks
            sm.video_offset["warnings"] += chr_warn
            # ...and the claims it read, so VERIFY can re-run it the way it
            # re-runs the composition itself. A check whose inputs the stored
            # dict does not carry is a check the checker cannot reproduce.
            sm.video_offset["chr_vram"] = [*g_vram, *s_vram]

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

    # C5 transition hygiene: the composed color-math state is per scene and
    # nothing carries it across an edge. Warns, never refuses — persistence
    # can be deliberate. Reads the edges already enumerated above.
    blend_warns, blend_edges = check_blend_edges(
        [(e.src, e.dst) for e in manifest.edges], scenes, greg)

    alloc = Allocation(sub, globals_map, global_channels, scenes, edge_reloads,
                       globals_init_zero=g_init_zero,
                       global_dma_inits=gdma_init,
                       global_regs=greg,
                       spc_owner=spc_owner,
                       edge_styles=edge_styles,
                       blend_edge_warnings=blend_warns,
                       blend_edges_checked=blend_edges)
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
        # C5, same discipline: re-compose the screen/blend vocabulary from
        # the claims the solver recorded and require byte-for-byte agreement
        # with what it stored. R1-R5 run again here as a side effect, so a
        # refusal the solver somehow skipped still stops the build.
        #
        # WHAT THIS BUYS AND WHAT IT DOES NOT, stated rather than implied:
        # compose_screen_blend is pure over its inputs, so re-running it on
        # the same claim objects cannot disagree about a legal composition —
        # this is not an independent derivation of the four bytes. What it
        # catches is the values or the ownership set being MUTATED after
        # composition and before emission, and the claim lists in the stored
        # dict drifting from what those values were computed from. Held
        # anyway because the alternative is a checker that mirrors every
        # class but this one, and the tree's rule is that the solver and the
        # checker do not get to disagree about what a legal map is.
        sb = sm.screen_blend
        if sb is not None:
            try:
                again = compose_screen_blend(
                    sb["screen"], sb["blend"],
                    [*alloc.global_regs, *sm.regs], sid, sb["direct"])
            except AllocationError as e:
                raise AssertionError(f"VERIFY: {e}") from e
            for k in ("tm", "ts", "cgwsel", "cgadsub", "registers",
                      "warnings"):
                if again[k] != sb[k]:
                    raise AssertionError(
                        f"VERIFY: screen/blend '{k}' in scene '{sid}' does "
                        f"not re-compose from its own claims: stored "
                        f"{sb[k]!r}, recomposed {again[k]!r}")
        # C6, the same discipline on the video/offset half. Same purity
        # caveat, same reason for holding it anyway.
        vo = sm.video_offset
        if vo is not None:
            try:
                again = compose_video_offset(
                    vo["video"], vo["offset"],
                    (sm.screen_blend or {}).get("screen", []), sid,
                    vo.get("bands_claims", []))
                # O9 re-run over the same claims, and appended in the same
                # order the solver appended them — the chr check contributes
                # to this scene's warnings, so a verify that skipped it would
                # report a drift on every scene that has one.
                _cc, cw = check_chr_depth(vo["video"], vo.get("chr_vram", []),
                                          sid)
            except AllocationError as e:
                raise AssertionError(f"VERIFY: {e}") from e
            if again is None:                    # chr-only: no mode, no table
                again = {"bgmode": None, "fields": {}, "registers": (),
                         "warnings": []}
            again["warnings"] = [*again["warnings"], *cw]
            for k in ("bgmode", "fields", "registers", "warnings"):
                if again[k] != vo[k]:
                    raise AssertionError(
                        f"VERIFY: video/offset '{k}' in scene '{sid}' does "
                        f"not re-compose from its own claims: stored "
                        f"{vo[k]!r}, recomposed {again[k]!r}")
    # C5 transition hygiene, mirrored over the same edges the solver read.
    e_warns, e_checked = check_blend_edges(
        [(src, dst) for src, dst, _b, _budget in alloc.edge_reloads],
        alloc.scenes, alloc.global_regs)
    if (e_warns, e_checked) != (alloc.blend_edge_warnings,
                                alloc.blend_edges_checked):
        raise AssertionError(
            f"VERIFY: the blend-edge check does not reproduce: stored "
            f"{alloc.blend_edges_checked} edge(s)/"
            f"{len(alloc.blend_edge_warnings)} warning(s), recomputed "
            f"{e_checked}/{len(e_warns)}")


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
                # THE WHOLE BGnSC BYTE, base AND size bits. The size bits were
                # left out until a 32x64 map arrived, and their absence was
                # the emitted-encoding rule's own failure mode: the shape got
                # narrated at the write site, where nothing checks it, and a
                # map declared 0x800 words was addressed as 0x400 — a picture
                # made entirely of its first 32 rows, with no gate red.
                # Byte-identical for every 32x32 claim, which is every claim
                # that predates the `shape` field.
                lines += [f"{s}_SC_BASE = "
                          f"${((p.start >> 8) & 0x7C) | p.shape_bits:02X}"]
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
    the other. A `direct_color` video claim owns CGWSEL on its own — the bit
    it composes is in that port — so a scene with direct color and no blend
    publishes CGWSEL and withholds CGADSUB. Emitting all four regardless would state a value for a port
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
             ";   [[claims.blend]]; CGWSEL bit 0 from [[claims.video]]'s",
             ";   direct_color, declared with the mode and written here",
             ";   because this composition is CGWSEL's one owner.",
             ";   Scene-enter code writes these ports from these symbols —",
             ";   never a narrated value. A half this scene composes no claim",
             ";   for owns no port here and emits no symbol: writing it is",
             ";   another claimant's business."]
    if sb["screen"]:
        lines += [
            f"ES_SCR_{up}_TM = ${sb['tm']:02X}"
            f"    ; {contrib(('main', 'both'))}",
            f"ES_SCR_{up}_TS = ${sb['ts']:02X}"
            f"    ; {contrib(('sub', 'both'))}"]
    else:
        lines.append(f"; ES_SCR_{up}_TM / _TS absent — no [[claims.screen]] in "
                     f"this scene: TM/TS are not this composition's to write")
    dc = (" direct-color<-" + ", ".join(who for _, who in sb["direct"])
          if sb["direct"] else " direct color 0")
    if sb["blend"]:
        g, _ = sb["blend"][0]
        math = ", ".join(f"{m}<-{who}" for c, who in sb["blend"]
                         for m in c.math)
        lines += [
            f"ES_SCR_{up}_CGWSEL = ${sb['cgwsel']:02X}"
            f"    ; source={g.source} clip={g.clip} prevent={g.prevent}"
            f"{dc}",
            f"ES_SCR_{up}_CGADSUB = ${sb['cgadsub']:02X}"
            f"    ; op={g.op}{' half' if g.half else ''} math: {math}"]
    elif sb["direct"]:
        # DIRECT COLOR WITH NO BLEND — CGWSEL alone. The port is owned
        # because b0 is composed for it, and CGADSUB is not, because nothing
        # in this scene composed a bit of it. Half of a half, and it is the
        # per-half ownership rule taken at its word rather than rounded up.
        lines += [
            f"ES_SCR_{up}_CGWSEL = ${sb['cgwsel']:02X}"
            f"    ; math off (prevent=always){dc}",
            f"; ES_SCR_{up}_CGADSUB absent — no [[claims.blend]] in this "
            f"scene: the composed OFF state is ${sb['cgadsub']:02X}, but "
            f"establishing it belongs to whoever owns that port (docs/99 §4)"]
    else:
        lines.append(f"; ES_SCR_{up}_CGWSEL / _CGADSUB absent — no "
                     f"[[claims.blend]] in this scene: the composed OFF state "
                     f"is ${sb['cgwsel']:02X}/${sb['cgadsub']:02X}, but "
                     f"establishing it belongs to whoever owns these ports "
                     f"(docs/99 §4)")
    lines.append("")
    return lines


def _video_offset_lines(sid: str, vo: dict | None) -> list[str]:
    """The composed video mode, and the offset table's field constants.

    Same rule as _screen_blend_lines, and the same reason: an encoding
    narrated at the write site is a second, uncheckable copy of the claim.
    A scene that declares a mode writes BGMODE from its symbol; a scene that
    declares an offset table builds its words from these masks.

    A SYMBOL IS PUBLISHED ONLY FOR WHAT THE COMPOSITION OWNS, per half. A
    scene with an offset claim but no mode claim cannot exist (O3 refuses
    it), but a mode claim alone is ordinary, and it emits no ES_OPT_*.

    THE FIELD SET IS DERIVED FROM THE DECLARATION, not fixed: `layers`
    decides which enable bits exist, `axis` decides which value mask, and
    ES_OPT_<ID>_VSEL appears only under mode 4, the only mode whose word
    carries an axis-select bit. A rail that builds a word with a bit its
    claim did not declare has no symbol to build it from.
    """
    if vo is None:
        return []
    up = sid.upper()
    lines = ["; ---- video/offset: the composed display mode ----",
             ";   BGMODE from [[claims.video]]; the offset word's fields",
             ";   from [[claims.offset]]. Scene code writes and builds from",
             ";   these — never a narrated encoding."]
    if vo["video"]:
        vc, vwho = vo["video"][0]
        bits = [f"mode {vc.mode} ({' + '.join(MODE_LAYERS[vc.mode])})"]
        if vc.bg3_priority:
            bits.append("bg3 priority")
        if vc.tiles16:
            bits.append("16x16: " + ",".join(vc.tiles16))
        lines.append(f"ES_VID_{up}_BGMODE = ${vo['bgmode']:02X}"
                     f"    ; {'; '.join(bits)} <- {vwho}")
    if vo["offset"]:
        oc, owho = vo["offset"][0]
        lines.append(f";   offset table: axis={oc.axis} layers="
                     f"{','.join(oc.layers)} <- {owho}")
        notes = {
            "BG1": "bit 13 — this column's offset drives BG1",
            "BG2": "bit 14 — ...drives BG2",
            "MASK": "the vertical offset field: vScroll = word & $3FF",
            "HMASK": "...horizontal: the layer keeps its own low 3 bits",
            "VSEL": "mode 4 bit 15 — this word is a V offset, not an H one",
            "BANDS": "table rows this scene selects between PER SCANLINE",
            "ROW_VOFS": "BG3VOFS = row * this selects table row `row` "
                        "(rowOffset = VScroll >> 3, SnesPpu.cpp:262)",
        }
        for k, v in vo["fields"].items():
            lines.append(f"ES_OPT_{up}_{k} = ${v:04X}    ; {notes[k]}")
        if vo.get("rowsel"):
            lines.append(f";   bands: {vo['rowsel']} is the composition's own "
                         f"HDMA channel on BG3VOFS (ES_H_"
                         f"{vo['rowsel'].upper()}_*, above). Arm it through "
                         f"the scene_mgr HDMA shadow at enter; the enter-time "
                         f"BG3VOFS write is the SEED it overrides from line 0")
    else:
        lines.append(f"; ES_OPT_{up}_* absent — no [[claims.offset]] in this "
                     f"scene: BG3 is an ordinary layer here (or absent from "
                     f"the mode), not a per-column table")
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
        lines += _video_offset_lines(sid, sm.video_offset)
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
            for c, who in sb["direct"]:
                rep.append(f"    direct color (CGWSEL b0) from {c.name} "
                           f"mode {c.mode}  {who}")
            for w in sb["warnings"]:
                rep.append(f"    WARNING: {w}")
        # C6: the composed video mode and offset table, on the same terms.
        vo = sm.video_offset
        if vo is not None:
            head = (f"BGMODE=${vo['bgmode']:02X}"
                    if vo["bgmode"] is not None else "BGMODE undeclared")
            rep.append(f"  VIDEO/OFFSET {head} "
                       f"(owns {','.join(vo['registers'])})")
            for c, who in vo["video"]:
                rep.append(f"    mode {c.mode} "
                           f"({' + '.join(MODE_LAYERS[c.mode])})"
                           f"{' bg3-priority' if c.bg3_priority else ''}"
                           f"{' 16x16:' + ','.join(c.tiles16) if c.tiles16 else ''}"
                           f"  {who}")
            for c, who in vo["offset"]:
                rep.append(f"    offset-per-tile axis={c.axis} "
                           f"layers={','.join(c.layers)}  {who}")
            for w in vo["warnings"]:
                rep.append(f"    WARNING: {w}")
        arm_total = sub.vblank_arm_cost * max(sm.vblank_transfers - 1, 0)
        rep.append(f"  VBLANK-DMA {sm.vblank_bytes}"
                   f"{f' + {arm_total} arm' if arm_total else ''}"
                   f"/{sub.vblank_budget} B/frame"
                   f" ({sm.vblank_transfers} transfers)")
    for src, dst, bytes_, budget in alloc.edge_reloads:
        b = f" (budget {budget})" if budget else ""
        rep.append(f"\ntransition {src}->{dst}: reload {bytes_} B{b}")
    # C5 transition hygiene, program-wide (an edge belongs to neither of its
    # scenes). The denominator prints unconditionally where any edge could
    # have been a candidate, so "no warnings" and "nothing examined" read
    # differently.
    if alloc.blend_edges_checked or alloc.blend_edge_warnings:
        rep.append(f"\nSCREEN/BLEND transition hygiene: "
                   f"{alloc.blend_edges_checked} edge(s) out of a blending "
                   f"scene examined, {len(alloc.blend_edge_warnings)} "
                   f"warning(s)")
        for w in alloc.blend_edge_warnings:
            rep.append(f"  WARNING: {w}")
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
                                 # CGWSEL b0, declared on [[claims.video]]
                                 # and composed here. A test asserts the
                                 # rendered pixel against the DECLARATION.
                                 "direct_color": bool(
                                     sm.screen_blend["direct"]),
                                 # WHICH of the four the composition OWNS —
                                 # per-half, so a reader can tell a composed
                                 # value from an off value the scene does not
                                 # own and does not publish a symbol for
                                 # (_screen_blend_lines).
                                 "registers": list(
                                     sm.screen_blend["registers"]),
                                 "features": sm.screen_blend["features"]}}
                            if sm.screen_blend is not None else {}),
                         # C6, same contract: the composed BGMODE, the
                         # offset table's declared shape and the field
                         # constants emitted for it, so a test can assert a
                         # ROM's mode and its per-column words against the
                         # DECLARATION rather than re-typing either.
                         **({"video_offset": {
                                 "bgmode": sm.video_offset["bgmode"],
                                 "mode": sm.video_offset["mode"],
                                 "tiles16": sm.video_offset["tiles16"],
                                 "offset_axis": sm.video_offset["axis"],
                                 "offset_layers":
                                     sm.video_offset["layers"],
                                 # Declared here, composed into CGWSEL b0 by
                                 # the screen/blend half. Carried on BOTH
                                 # objects so a reader who has the mode has
                                 # the pixel rule that goes with it.
                                 "direct_color": any(
                                     c.direct_color
                                     for c, _ in sm.video_offset["video"]),
                                 "fields": sm.video_offset["fields"],
                                 "registers": list(
                                     sm.video_offset["registers"]),
                                 "features": sm.video_offset["features"],
                                 "bands": sm.video_offset["bands"],
                                 "rowsel": sm.video_offset.get("rowsel")}}
                            if sm.video_offset is not None else {})}
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
        warns = (sum(len(sb["warnings"]) for sb in sbs)
                 + len(alloc.blend_edge_warnings))
        print(f"screen/blend: {sum(sb['designations'] for sb in sbs)} "
              f"designation(s), {sum(sb['blends'] for sb in sbs)} blend "
              f"claim(s) composed across {len(sbs)} scene(s), "
              f"{sum(sb['checks'] for sb in sbs)} refusal check(s) evaluated, "
              f"{alloc.blend_edges_checked} transition edge(s) examined, "
              f"{warns} warning(s) in the report")
    else:
        print("screen/blend: nothing composed (no vocabulary claims in "
              "this composition)")
    # ...and the video/offset half, reported on the same terms and for the
    # same reason: a run that examined nothing must read as having examined
    # nothing. Live checks per scene: O1 needs two mode claims, O2 two offset
    # claims, O3/O4/O6/O7 an offset claim, O8 and O12 a mode claim, O10 a
    # bands claim, and O5's register arm the synthesized ownership claim in
    # the scene's union. O7 and O12 warn rather than refusing and are counted
    # anyway: what the census reports is checks EVALUATED, and a check whose
    # verdict is a warning was still evaluated.
    vos = [sm.video_offset for sm in alloc.scenes.values()
           if sm.video_offset is not None]
    if vos:
        print(f"video/offset: {sum(vo['modes'] for vo in vos)} mode claim(s), "
              f"{sum(vo['offsets'] for vo in vos)} offset table(s) composed "
              f"across {len(vos)} scene(s), "
              f"{sum(vo['checks'] for vo in vos)} refusal check(s) evaluated, "
              f"{sum(len(vo['warnings']) for vo in vos)} warning(s) in the "
              f"report")
    else:
        print("video/offset: nothing composed (no video or offset claims in "
              "this composition)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
