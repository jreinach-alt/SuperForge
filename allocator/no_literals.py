#!/usr/bin/env python3
"""superforge — no-raw-address-literals enforcement.

Makes collisions *unexpressible*: engine and user sources may reference
allocated resources only through allocator-emitted symbols. Fixed hardware
I/O ports are the only allowed literals — those are silicon, not allocated
(you *must* write $2118 for VMDATA). Grandfather nothing.

Ruleset (documented precision/recall trade, per finding class):

  NUMBER BASES.  `$`-hex, ca65 `%`-binary, and bare decimal literals are
  all matched — `sta 515` and `sta %0000001000000011` are the same byte as
  `sta $0203` and get the same verdict (the decimal/binary evasion, F6).
  One deliberate asymmetry: decimal/binary literals below 256 in address-
  operand position are EXEMPT (they are overwhelmingly loop counts and
  masks; hex address operands stay fully strict, so `lda $04` is still a
  finding while `adc 42` is not).

  ADDRESS OPERANDS (strict — the real disease).  Any numeric literal in an
  instruction's operand position addresses memory by number: direct page
  (`lda $04`, `z:`), absolute (`sta $0203`, `a:`), long (`sta $7E0203`, `f:`),
  indexed/indirect forms. Allowed only when the effective target lies in the
  I/O ranges from the symbol map (spaces.io_allowed: $2100-$21FF, $4200-$43FF).
  Everything else is a finding — WRAM, DP, and ROM data cannot be addressed
  by literal, whether or not that byte happens to be allocated yet.

  IMMEDIATES (value-checked, all bases).  `#$xxxx` (or `#nnn` / `#%..`) with
  value >= $100 is a finding when it falls inside an *allocator-emitted* WRAM
  claim (16-bit offset or $7E/$7F long form), or exactly equals a VRAM
  claim's BASE word address (the "VRAM word target used as a data address"
  smuggle — e.g. `ldx #$1400 / stx VMADD`). VRAM interiors are not matched:
  interior words collide with ordinary data values (palette colors, masks),
  and interior addressing flows through base+offset symbol arithmetic anyway.
  Values below $100 and values outside every emitted range are data, not
  addresses — masks and loop counts stay legal.

  ASSIGNMENTS (`SYM = $xxxx` in engine source; any base).  Same value check
  as immediates. Defining a constant that names an allocated address is how
  squatting starts; the allocator's own generated .inc is exempt because it
  is the single legitimate source of such constants (do not pass build/ files
  to this tool).

  CHANNEL MASKS ($420B / $420C / the HDMAEN shadow).  MDMAEN and HDMAEN
  take a bitmask over CHANNELS, so `lda #$01` / `sta a:$420B` hardcodes
  "channel 0" just as surely as `sta a:$4301` does — and a raw-address rule
  cannot see it, because the literal is a value rather than an address. The
  legal form names the allocated channel: `lda #(1 << ES_D_<CLAIM>_CH)`.
  The check walks back over the instructions that produced the stored
  register and requires EVERY immediate feeding it to reference an
  `ES_*_CH` symbol — so an intervening `.a8`, a `%`-binary literal, an
  equated mask and `stx`/`sty` are all covered.

  The rule's targets are the SYMBOLS THAT REACH THE REGISTER, not just the
  register literal. `sm_nmi_core` is the only per-frame writer of `$420C`
  and it writes whatever `ES_SM_NMI+2` holds, so that WRAM byte IS HDMAEN,
  one frame delayed — and it is therefore gated at its own store sites too.
  It was not, for one release: `lda #$FF / sta z:ES_SM_NMI+2` passed clean
  while the identical literal into `$420C` was refused, which is the path
  a follow-up review used to arm an undeclared channel in a scene the runtime tests
  never sampled. Only the `+2`
  byte is a mask: `+0` is `nmi_ready` and `+1` is the INIDISP shadow, both
  of which legitimately take literals. An INDEXED store into the block is
  reported regardless of offset, because a computed index can reach `+2`
  and this single-file walk cannot prove it does not.

  A value loaded from MEMORY (`lda z:ES_SM_NMI+2` / `sta a:$420C`) stays
  legal: its provenance is the shadow, which the paragraph above now really
  does police. `stz` is legal everywhere (it disarms).

  CHANNEL ENCODING (DMAP / BBAD).  A claim's channel register file holds
  the transfer's shape at +0 (DMAP) and its destination port at +1 (BBAD).
  The allocator emits both bytes from the declaration
  (ES_[HD]_<CLAIM>_{DMAP,BBAD}), so a site that writes them as literals is
  free to name one register in the .toml and drive another in silicon —
  the exact drift exists to close, and the reason two probe
  claims still under-declared their footprint after that closure
. This rule constrains the
  SHAPE of the write, not its value, so it is not circular: every
  immediate feeding a `+0`/`+1` store into a channel register file (or into
  the HDMA shadow the NMI copies there) must reference an `ES_*_DMAP` /
  `ES_*_BBAD` symbol. Combining bits is fine
  (`#(ES_H_PROBE_DMA_DMAP | DMAP_FIXED_SRC)`).

  REG OWNERSHIP (the writer-side gate for claims.reg — docs/09 §2.1 hole 1).
  C4 declares CPU-register ownership and check_reg_ownership refuses
  conflicting DECLARATIONS, but an UNDECLARED write was invisible: every
  $21xx/$42xx literal is io_allowed by design, so a feature that simply does
  not declare stayed exactly as invisible as the census rows once were.
  Region classes have no such gap — their emitted symbol is the only way to
  address them — so the asymmetry was real and specific to registers. This
  pass closes it: a sta/stx/sty/stz whose destination resolves to a bank-0
  port carrying a REGISTER_FOOTPRINT name must be declared by, or covered
  by, the claim set the file is checked against.

  The write set is sta/stx/sty/stz PLUS the RMW family (inc dec asl lsr rol
  ror trb tsb) — `inc a:$2105` writes BGMODE. Every resolved port gets a
  CATEGORY (channel / latch / data / in-class / unnamed), and each has a
  rule: a latch is the *where* of a data port, so it rides the claim on the
  RESOURCE it serves; an unnamed port is a finding-with-override.

  Destination resolution anchors the BASE term and folds its constant additive
  tail. A term it cannot fold — `- 1`, `| $0006`, `+ SYM` — resolves to
  UNRESOLVED_PORT and is ALWAYS a finding: reporting the base IS the
  laundering, since `sta a:$2100 + 5` is BGMODE, not INIDISP. The one
  exception is $4300-$437F, whose whole extent belongs to the channel rules
  and whose `<FEAT>_REGS = $4300 + ES_[HD]_<CLAIM>_CH * 16` idiom is
  unfoldable by construction.

  See scan_reg_ownership for
  the path map (which file answers to which claims), the covered-port rule,
  the multi-port resource spans, and the stated residue (engine/toy and the
  vendored probes match no context shape and are fixture residue, per
  docs/09 §2.1's own census boundary; the vendored boot includes —
  vendor/rom/ppu_reset.inc et al., .include'd into gated main.asm files —
  are equally unwatched, because the scan reads each listed file's own text
  and never expands includes).

  STATED LIMIT, unchanged and shared with every other lint here: a write
  through a RELOCATED direct page is invisible. `lda #$2100 / tcd / sta $05`
  IS a BGMODE write and no reg pass sees it. It is backstopped today — the
  ADDRESS rule refuses `$05` as a raw operand, so the build stops — but that
  backstop is incidental, and a DP-relative write through an EMITTED symbol
  would pass. No in-tree code relocates DP (`grep '^\\s*tcd'` = one site,
  vendor/rom/init.inc:34, DP = $0000), so this is latent and exotic; recorded
  rather than built for (convergence §4.4 item 2).

  Override: `; REG-LINT: ok [$port] — <reason>` within 3 lines, reason
  required, bare form itself a finding — and PORT-SCOPED: an explicit
  `$port` excuses only that port; a comment on a write's own line excuses
  that write; a standalone unscoped one excuses its window only when every
  would-be finding in it is the same port, and is otherwise AMBIGUOUS and
  excuses nothing. A radius that is NOT port-scoped silences every finding
  within ±3 lines, so one stated BGMODE reason could carry an unrelated
  OBSEL write next door — a reviewer-facing hazard both implementations
  missed (convergence §4.4 item 1).

  OVERRIDES.  A site verified safe by construction is suppressed with
  `; CHANNEL-LINT: ok — <reason>` within 3 lines, matching the width-lint /
  zp-lint convention this repo already uses. The reason after the separator
  (em dash, `--`, ` - `, or `:`) is REQUIRED; a bare `; CHANNEL-LINT: ok`
  is itself a finding, so the escape hatch cannot be used silently.

  ROM BACKING (the presence-side gate for claims.rom — docs/37).  The rules
  above are all about a site NARRATING an address the allocator owns. This one
  is the mirror: a `rom` claim RESERVES bytes and puts none there, so a claim
  with no `.incbin` anywhere is an unbacked window that the ROM will
  nevertheless read. The drift direction was already asserted hard
  (`.assert ^label = ES_R_*_BANK` at each claim site); the PRESENCE direction
  was not checked at all, and `grad_tabs` shipped unbacked with every gate
  green (2026-08-02). Whole-invocation rather than per-file, because the
  question is about the composition. See `scan_rom_backing` for the rule, the
  declaration-block extent, the `backed_by` escape hatch and three stated
  limits.

  Data directives (.byte/.word/.res/...) are not scanned (tile data, LUTs);
  smuggling an address through a data table is out of scope here and
  on record as a known limitation.

Exit codes: 0 clean, 1 findings (one `file:line: [class] message` per line),
2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

HEX = r"\$[0-9A-Fa-f]+"
BIN = r"%[01]+"                       # ca65 binary literal
# bare decimal: not digits inside a $hex/%bin literal or an identifier
DEC = r"(?<![\w$%])[0-9]+"
NUM = rf"(?:{HEX}|{BIN}|{DEC})"
COMMENT_RE = re.compile(r";.*$")
STRING_RE = re.compile(r'"[^"]*"|\'[^\']*\'')
DIRECTIVE_RE = re.compile(r"^\s*\.[A-Za-z_]\w*")
ASSIGN_RE = re.compile(r"^\s*@?\w+\s*(?::?=)\s*(?P<rest>.*)$")
LABEL_RE = re.compile(r"^\s*@?\w+:\s*")
# an instruction operand numeric literal ($hex / %binary / decimal — F6),
# optionally behind a width/bank prefix
OPERAND_NUM_RE = re.compile(rf"(?P<prefix>[#<>^]?)\s*(?:[zaf]:)?(?P<num>{NUM})")
# any identifier-led statement: a 65816 mnemonic OR a macro invocation — macro
# address arguments obey the same rule (pass emitted symbols, not numbers)
MNEMONIC_RE = re.compile(r"^\s*(?P<mn>[A-Za-z_@]\w*)\b\s*(?P<rest>.*)$")


def _lit_value(tok: str) -> tuple[int, str]:
    """Parse a $hex / %binary / decimal literal -> (value, base-tag)."""
    if tok.startswith("$"):
        return int(tok[1:], 16), "hex"
    if tok.startswith("%"):
        return int(tok[1:], 2), "bin"
    return int(tok, 10), "dec"


class Finding:
    def __init__(self, path: Path, line_no: int, cls: str, msg: str):
        self.path, self.line_no, self.cls, self.msg = path, line_no, cls, msg

    def __str__(self):
        return f"{self.path}:{self.line_no}: [{self.cls}] {self.msg}"


def load_map(path: Path) -> tuple[list[tuple[int, int]], list[dict], dict]:
    """Returns (io_allowed ranges, allocated placements with class info, raw map).

    The raw dict is the reg-ownership pass's input: scenes.<id>.reg is the
    allocator-resolved globals+closure union, emitted for exactly this gate
    (allocate.py's emission comment names docs/09 §2.1's hole).
    """
    d = json.loads(path.read_text())
    io = [(a, b) for a, b in d["spaces"]["io_allowed"]]
    placements = list(d.get("globals", []))
    for sc in d.get("scenes", {}).values():
        placements += sc.get("placements", [])
    return io, placements, d


def _is_channel_base_expr(rest: str) -> bool:
    """Does this expression build a DMA channel register-file base?

    ONE predicate, used by both channel rules. They used to disagree: the
    assign path accepted `$4300` whenever the expression mentioned an
    `ES_[HD]_*_CH` symbol anywhere, while `_channel_bases` (which decides whose
    `+0`/`+1` writes the DMAP/BBAD rule inspects) demanded the exact textual
    shape `$4300 + ES_?_<CLAIM>_CH * 16`. Four arithmetically-identical
    spellings — `$4300 | CH * 16`, `$4300 + (CH * 16)`, `$4300 + 16 * CH`,
    `$4300 + (CH << 4)` — therefore passed the assign check, never entered
    `bases`, and turned the encoding rule OFF for the whole file while the
    build stayed clean.
    A single predicate cannot disagree with itself.
    """
    return bool(re.search(r"\$4300(?![0-9A-Fa-f])", rest)
                and CH_SYM_RE.search(rest))


def _allocated_hit(value: int, placements: list[dict]) -> str | None:
    """Does `value` land inside an emitted range? Returns a description."""
    for p in placements:
        cls, start, size = p["class"], p["start"], p["size"]
        end = start + size
        if cls == "wram":
            if start <= value < end and value >= 0x100:
                return f"WRAM claim {p['sym']} [${start:04X}..${end:04X})"
            long_start, long_end = 0x7E0000 + start, 0x7E0000 + end
            if long_start <= value < long_end:
                return f"WRAM claim {p['sym']} [${long_start:06X}..${long_end:06X})"
        elif cls == "sram":
            # the wram rule's shape at bank $70: a bare
            # 16-bit hit needs value >= $100 (below that it is
            # indistinguishable from DP offsets and small data), while the
            # $70-long form is ALWAYS a finding — nothing but the battery
            # window lives at $70xxxx, so the literal can only be a
            # hand-narrated save address.
            if start <= value < end and value >= 0x100:
                return f"SRAM claim {p['sym']} [${start:04X}..${end:04X})"
            long_start, long_end = 0x700000 + start, 0x700000 + end
            if long_start <= value < long_end:
                return (f"SRAM claim {p['sym']} "
                        f"[${long_start:06X}..${long_end:06X})")
        elif cls == "vram" and value >= 0x100 and value == start:
            # exact BASE match only: the smuggle that matters is loading a
            # claim's base as a VMADD target; interior words collide with
            # ordinary data values (palette colors, masks) far too often,
            # and interior addressing goes through base+offset symbol
            # arithmetic anyway
            return f"VRAM claim {p['sym']} base ${start:04X}"
        # DP offsets are < $100 — reachable only as operands, which the strict
        # address-operand rule already rejects wholesale
    return None


def scan_line(path: Path, line_no: int, raw: str, io, placements) -> list[Finding]:
    line = STRING_RE.sub("", COMMENT_RE.sub("", raw))
    if not line.strip():
        return []
    findings: list[Finding] = []

    m = ASSIGN_RE.match(line)
    if m and not DIRECTIVE_RE.match(line):
        rest = m.group("rest")
        # An equate is a literal with a name on it, so the channel rule has to
        # exist on the assign path too: `REGS = $4301` / `sta a:REGS` used to
        # pass clean, because the operand path is where the channel check lived
        # The codebase's own idiom —
        # `<FEAT>_REGS = $4300 + ES_H_<CLAIM>_CH * 16` — must keep working, so
        # $4300 is allowed exactly when the expression also names the channel
        # through its emitted symbol. Any other $43xx constant is a hardcoded
        # channel number.
        for hm in re.finditer(NUM, rest):
            value, _ = _lit_value(hm.group(0))
            if 0x4300 <= value <= 0x437F:
                if value == 0x4300 and _is_channel_base_expr(rest):
                    continue                # the register-file base idiom
                findings.append(Finding(
                    path, line_no, "channel",
                    f"constant assignment {hm.group(0)} names a DMA channel "
                    f"register file directly (channel {((value & 0x7F) >> 4)}) "
                    f"— channels are allocated. Build the base from the "
                    f"emitted number: "
                    f"`<FEAT>_REGS = $4300 + ES_H_<CLAIM>_CH * 16`"))
                continue
            hit = _allocated_hit(value, placements)
            if hit:
                findings.append(Finding(
                    path, line_no, "assign",
                    f"constant assignment names allocated address "
                    f"{hm.group(0)} inside {hit} — use the emitted symbol"))
        return findings

    if DIRECTIVE_RE.match(line):
        return findings                     # data directives: not scanned

    body = LABEL_RE.sub("", line)
    mi = MNEMONIC_RE.match(body)
    if not mi or not mi.group("rest"):
        return findings
    for om in OPERAND_NUM_RE.finditer(mi.group("rest")):
        value, base = _lit_value(om.group("num"))
        if om.group("prefix") in ("#", "<", ">", "^"):
            # The immediate exemption for the register file is exactly $4300 —
            # the whole-file base (scene_mgr's MVN destination). `ldy #$4310`
            # and `ldx #$4372` DO pick channels 1 and 7, so the old
            # range-shaped exemption was broader than its own justification
            # and a 16-byte MVN
            # restoring one channel's registers would have hardcoded it.
            if 0x4301 <= (value & 0xFFFF) <= 0x437F and (value >> 16) == 0:
                findings.append(Finding(
                    path, line_no, "channel",
                    f"immediate #{om.group('num')} picks DMA channel "
                    f"{((value & 0x7F) >> 4)} — only the whole-file base "
                    f"#$4300 is silicon. Build a per-channel address from the "
                    f"emitted number: `$4300 + ES_H_<CLAIM>_CH * 16`"))
                continue
            hit = _allocated_hit(value, placements)
            if value >= 0x100 and hit:
                findings.append(Finding(
                    path, line_no, "immediate",
                    f"immediate #{om.group('num')} is an allocated address "
                    f"({hit}) — load the emitted symbol instead"))
            continue
        # address operand: strict for hex; decimal/binary below 256 are
        # loop counts and masks, not sneaked addresses (F6 exemption)
        if base != "hex" and value < 0x100:
            continue
        # $4300-$437F is inside io_allowed as a RANGE, but a channel's
        # register file is not plain silicon the way $2100 is: the channel
        # NUMBER is an allocated resource. `sta a:$4301` hardcodes channel 0's
        # BBAD, which is exactly how four features drove B-bus ports while
        # staying invisible to the occupancy gate. Checked before
        # the io_allowed allowance, and only for address operands — the
        # immediate form (`ldy #$4300`, scene_mgr's MVN destination) addresses
        # the whole file rather than picking a channel, and stays legal.
        #
        # Bank 0 only. Bank $7E used to be accepted here too, which meant
        # `sta f:$7E4301` — a WRAM long address, not a DMA register — was
        # reported as "hardcodes DMA channel 0" and skipped the allocated-claim
        # lookup that would have named which claim it landed in
        # (diagnostic quality only, never a false negative, since the
        # address rule below catches it).
        if 0x4300 <= (value & 0xFFFF) <= 0x437F and (value >> 16) == 0:
            findings.append(Finding(
                path, line_no, "channel",
                f"raw channel register {om.group('num')} hardcodes DMA "
                f"channel {((value & 0x7F) >> 4)} — channels are allocated. "
                f"Declare claims.hdma or claims.dma_init and address the file "
                f"through the emitted number: "
                f"`<FEAT>_REGS = $4300 + ES_H_<CLAIM>_CH * 16`"))
            continue
        if any(lo <= value <= hi for lo, hi in io):
            continue
        if (value >> 16) == 0x00 and any(
                lo <= (value & 0xFFFF) <= hi for lo, hi in io):
            continue                        # $002118-style long I/O form
        hit = _allocated_hit(value, placements)
        where = f" (inside {hit})" if hit else ""
        findings.append(Finding(
            path, line_no, "address",
            f"raw address operand {om.group('num')}{where} — resources are "
            f"allocated; reference them through allocator-emitted symbols "
            f"(only hardware I/O ports may be literal)"))
    return findings


# --- channel-mask ($420B/$420C) and channel-encoding (DMAP/BBAD) rules -------

# A store into MDMAEN/HDMAEN or into the HDMAEN shadow byte, in any of the store
# flavours. `stz` is matched but exempted below because clearing is always legal.
# `$00420B` is the bank-0 long form of the same register; both are matched.
# `ES_SM_NMI` is scene_mgr's NMI control block: +2 is the HDMAEN shadow that
# sm_nmi_core copies to $420C every armed frame (see the module docstring's
# CHANNEL MASKS paragraph — the shadow is a mask surface, not a plain byte).
HDMAEN_SHADOW_SYM = "ES_SM_NMI"
HDMAEN_SHADOW_OFF = 2
# Any store, of any flavour. WHAT it stores to is decided by a predicate
# (_enable_target), not by this pattern — see that function for why.
# The width/bank prefix is an ATOMIC group `(?:[azf]:)?` (OPERAND_NUM_RE's
# shape), never `[azf]?:?`: with the letter and colon independently optional
# the class eats the bare leading a/z/f of a SYMBOL operand — `sta FADE_PORT`
# resolved as dest `ADE_PORT` = nothing while `sta a:FADE_PORT` fired.
STORE_RE = re.compile(
    r"^\s*(?P<op>sta|stx|sty|stz)\s+(?:[azf]:)?(?P<dest>.*?)\s*$", re.I)
# The enable ports themselves, as literals. `$00420B` is the bank-0 long form.
ENABLE_LIT_RE = re.compile(r"^\$(?:00)?(420B|420C)$", re.I)
INT_TERM_RE = re.compile(r"(?<![\w$])(\d+)(?![\w])")
# `<BASE> = $4300 + ES_?_<CLAIM>_CH * 16` — the codebase's idiom for addressing
# a claim's DMA register file through its allocated channel number.
CH_SYM_RE = re.compile(r"ES_[HD]_\w+_CH(?!\w)")
ASSIGN_LHS_RE = re.compile(r"^\s*(?P<sym>@?\w+)\s*(?::?=)\s*(?P<rest>.*)$")
# The scene_mgr HDMA shadow: 128 B of WRAM MVN'd to $4300 verbatim every armed
# frame, so a write to its +0/+1 slots IS a write to DMAP/BBAD.
SHADOW_BASE_RE = re.compile(r"^ES_SM_HDMA(_LONG)?$", re.I)
# A store into offset +0 (DMAP) or +1 (BBAD) of one of those bases. The offset
# may be absent (bare base = +0) and an index may follow (the shadow form).
# Same atomic prefix group as STORE_RE — `[azf]?:?` would eat the bare leading
# a/z/f of a base symbol, the same mechanism, on this pass's own copy of it.
ENC_STORE_RE = re.compile(
    r"^\s*(?P<op>sta|stx|sty|stz)\s+(?:[azf]:)?(?P<base>\w+)"
    r"(?:\s*\+\s*(?P<off>[01]))?\s*(?:,\s*[xy])?\s*$", re.I)
# An A/X/Y-setting instruction, for the provenance walk.
LOAD_RE = re.compile(r"^\s*(?P<mn>lda|ldx|ldy|ora|and|eor|adc|sbc|txa|tya|tax|tay|"
                     r"pla|plx|ply|clc|sec|sep|rep|inc|dec|asl|lsr|rol|ror)\b"
                     r"\s*(?P<rest>.*)$", re.I)
IMM_RE = re.compile(r"^#(?P<val>.+)$")
# Instructions that end a provenance walk: control flow makes the register's
# source unknowable from one file's text.
FLOW_RE = re.compile(r"^\s*(?:j(?:sr|mp|ml|sl)|bra|brl|b(?:cc|cs|eq|ne|mi|pl|vc|vs)|"
                     r"rts|rtl|rti)\b", re.I)
LABEL_ONLY_RE = re.compile(r"^\s*@?\w+:\s*$")
# --- the override grammar, factored -----------------------------------------
#
# One spelling of the convention, parameterised by token, instead of a
# hand-copied regex pair per lint. The reg and channel rules had
# character-identical pairs; a third copy is how the separator alternations
# drift apart.
#
# The optional PORT token — `; REG-LINT: ok $2101 — reason` — is new. See
# `_reg_override_for` for what it scopes; the channel rule ignores it and
# keeps today's radius behaviour, so the convention is EXTENDED, not forked.
_OVERRIDE_CACHE: dict[str, tuple] = {}


def _override_res(token: str) -> tuple[re.Pattern, re.Pattern]:
    """(reasoned, bare) matchers for `; <TOKEN>-LINT: ok [$port] — reason`.

    The separator (em dash, `--`, ` - `, `:`) and the required reason are the
    repo-wide convention; a bare form is itself a finding, because an escape
    hatch that need not say why is just a quiet way to turn the rule off.
    """
    if token not in _OVERRIDE_CACHE:
        _OVERRIDE_CACHE[token] = (
            re.compile(rf";\s*{token}:\s*ok\s*(?:\$(?P<port>[0-9A-Fa-f]+))?\s*"
                       rf"(?P<sep>—|--|\s-\s|:)\s*(?P<reason>\S.*)$", re.I),
            re.compile(rf";\s*{token}:\s*ok\s*$", re.I))
    return _OVERRIDE_CACHE[token]


OVERRIDE_RE, BARE_OVERRIDE_RE = _override_res("CHANNEL-LINT")

# Register-setting instructions whose source is NOT memory: a transfer, a pull,
# or a shift/inc of the register itself. `_provenance` used to lump these in
# with memory loads and call the result legal, which let an implied-operand op
# launder a literal past the mask rule — `lda #$01 / tax / stx a:$420B` and
# `lda #$01 / asl a / sta a:$420B` were both ACCEPTED
# A transfer is not memory; the walk
# cannot follow it within one file, so it now reports "unknown" and fails closed.
_IMPLIED_SETTERS = {"txa", "tya", "tax", "tay", "pla", "plx", "ply"}
_RMW_SETTERS = {"inc", "dec", "asl", "lsr", "rol", "ror"}

_STORE_ONLY = re.compile(r"^\s*(?:sta|stx|sty|stz)\b", re.I)
_REG_OF = {"sta": "a", "stx": "x", "sty": "y"}
_SETS = {"lda": "a", "ora": "a", "and": "a", "eor": "a", "adc": "a", "sbc": "a",
         "txa": "a", "tya": "a", "pla": "a", "inc": "a", "dec": "a", "asl": "a",
         "lsr": "a", "rol": "a", "ror": "a",
         "ldx": "x", "tax": "x", "plx": "x",
         "ldy": "y", "tay": "y", "ply": "y"}


def _strip(raw: str) -> str:
    return STRING_RE.sub("", COMMENT_RE.sub("", raw))


def _override_near(lines: list[str], idx: int) -> tuple[bool, Finding | None]:
    """Is there a `; CHANNEL-LINT: ok — reason` within 3 lines of `idx` (0-based)?

    A BARE `; CHANNEL-LINT: ok` returns (False, finding): the escape hatch has
    to say why, or it is just a way to turn the rule off quietly.
    """
    for k in range(max(0, idx - 3), min(len(lines), idx + 4)):
        if OVERRIDE_RE.search(lines[k]):
            return True, None
        if BARE_OVERRIDE_RE.search(lines[k]):
            return False, ("bare", k + 1)
    return False, None


def _channel_bases(lines: list[str]) -> set[str]:
    """Symbols that name a DMA channel register file in this file.

    Uses `_is_channel_base_expr` — the SAME predicate the assign path applies
    when it decides whether a `$4300` constant is the legitimate register-file
    base idiom. See that function for why the two must not diverge.
    """
    out = set()
    for raw in lines:
        line = _strip(raw)
        if DIRECTIVE_RE.match(line):
            continue
        m = ASSIGN_LHS_RE.match(line)
        if m and _is_channel_base_expr(m.group("rest")):
            out.add(m.group("sym").upper())
    return out


def _provenance(lines: list[str], store_idx: int, reg: str):
    """Immediates feeding `reg` at `lines[store_idx]`, walking backwards.

    Returns (immediates, verdict) where verdict is one of:
      "immediate" — the register's value came from immediates only (returned)
      "memory"    — the last load of `reg` read memory, so the value is not a
                    literal in this file (legal: its provenance is whatever
                    wrote that memory, which this rule polices there)
      "unknown"   — control flow, a label, or the top of the file intervened
    """
    imms = []
    for j in range(store_idx - 1, max(-1, store_idx - 40), -1):
        line = _strip(lines[j])
        if not line.strip():
            continue
        if FLOW_RE.match(line) or LABEL_ONLY_RE.match(line) or LABEL_RE.match(line):
            return imms, "unknown"
        if DIRECTIVE_RE.match(line) or _STORE_ONLY.match(line):
            continue                      # width directives and other stores
        m = LOAD_RE.match(line)
        if not m:
            return imms, "unknown"
        mn = m.group("mn").lower()
        if _SETS.get(mn) != reg:
            continue                      # touches a different register
        operand = m.group("rest").strip()
        if mn in _RMW_SETTERS and operand.lower() not in ("", "a"):
            continue                      # `inc $10` modifies MEMORY, not A
        im = IMM_RE.match(operand)
        if not im:
            if mn in _IMPLIED_SETTERS or (mn in _RMW_SETTERS
                                          and operand.lower() in ("", "a")):
                return imms, "unknown"    # a transfer/pull/shift, not memory
            return imms, "memory"         # genuinely loaded from memory
        imms.append((j + 1, im.group("val").strip()))
        if mn in ("lda", "ldx", "ldy"):
            return imms, "immediate"      # a load ends the chain
    return imms, "unknown"


def _additive_const(expr: str, sym: str) -> int | None:
    """Sum the integer terms of `<sym> + a + b ...`. None if it is not that.

    Evaluated rather than pattern-matched, so `+2`, `+1+1` and `+ 2` are one
    case. `ES_SM_NMI+1+1` reaching HDMAEN while `ES_SM_NMI+2` was refused was
    the shape to avoid — a rule that reads an offset textually is a rule
    that only knows the spellings someone thought of.
    """
    rest = expr[expr.index(sym) + len(sym):]
    if not re.fullmatch(r"(?:\s*\+\s*\d+)*\s*", rest):
        return None
    return sum(int(t) for t in INT_TERM_RE.findall(rest))


def _enable_target(dest: str, aliases: dict[str, str]) -> str | None:
    """What mask surface does a store to `dest` reach? None = not a mask.

    A PREDICATE, not a pattern, and for the reason N3 established one file
    over: three rounds of this rule matched the destination textually, and
    each round an arithmetically-identical spelling walked past it. R5 was the
    fourth — `MUT_HDMAEN = $420C` then `sta a:MUT_HDMAEN` put a literal mask
    into the real HDMAEN while no_literals reported "1 file(s) clean". Adding
    that spelling would have been the fourth patch to a pattern list; asking
    "does this destination REACH an enable port" cannot be spelled around,
    because aliases are resolved (`aliases`) and offsets are evaluated.

    The surfaces are the ports `$420B`/`$420C` and the WRAM shadow byte
    `ES_SM_NMI+2`, which sm_nmi_core copies into `$420C` every armed frame.
    `+0`/`+1` of that block are nmi_ready and the INIDISP shadow and take
    literals legitimately — but an INDEXED store into the block counts
    whatever its stated offset, since a computed index can reach +2.
    """
    port, why = _enable_port(dest, aliases)
    return None if port is None else why


def _enable_port(dest: str, aliases: dict[str, str]) -> tuple[str | None, str | None]:
    """(canonical port, human description) for a store destination.

    Split from _enable_target so consumers can ask WHICH port without parsing
    a message. tests/test_dma_init_forced_blank.py needs MDMAEN specifically —
    per-claim coverage is counted from `sta $420B` sites — and asking it to
    match on prose would rebuild the textual coupling this predicate exists to
    remove. Canonical means `$420B`/`$420C` however spelled, including through
    an alias, so that consumer now sees alias-spelled firing sites too.
    """
    d = dest.strip()
    idx = bool(re.search(r",\s*[xy]\s*$", d, re.I))
    if idx:
        d = re.sub(r",\s*[xy]\s*$", "", d, flags=re.I).strip()
    lit = ENABLE_LIT_RE.match(d)
    if lit:
        return f"${lit.group(1).upper()}", f"${lit.group(1).upper()}"
    base = d.split("+")[0].strip()
    if base in aliases:
        port, _ = _enable_port(aliases[base], aliases)
        return port, f"{base} (= {aliases[base]})"
    if re.fullmatch(rf"{HDMAEN_SHADOW_SYM}(_LONG)?", base, re.I):
        if idx:
            return "shadow", (f"the HDMAEN shadow ({HDMAEN_SHADOW_SYM}, indexed"
                              f" — a computed index can reach "
                              f"+{HDMAEN_SHADOW_OFF})")
        off = _additive_const(d, base)
        if off == HDMAEN_SHADOW_OFF:
            return "shadow", f"the HDMAEN shadow ({base}+{off})"
    return None, None


def _enable_aliases(lines: list[str]) -> dict[str, str]:
    """Local symbols that resolve to a mask surface, to a fixpoint.

    `MUT_HDMAEN = $420C` makes MUT_HDMAEN a mask surface; `X = MUT_HDMAEN`
    makes X one too. Iterated rather than single-pass so a chain of equates
    cannot launder the port, and so declaration order does not matter.
    """
    aliases: dict[str, str] = {}
    for _ in range(8):                      # depth bound; chains are short
        grew = False
        for raw in lines:
            m = ASSIGN_LHS_RE.match(_strip(raw))
            if not m or DIRECTIVE_RE.match(_strip(raw)):
                continue
            sym, rest = m.group("sym"), m.group("rest").strip()
            if sym in aliases:
                continue
            if _enable_target(rest, aliases):
                aliases[sym] = rest
                grew = True
        if not grew:
            break
    return aliases


def scan_enables(path: Path, lines: list[str]) -> list[Finding]:
    """A literal mask feeding MDMAEN/HDMAEN is a hardcoded channel number.

    See the module docstring's CHANNEL MASKS paragraph. The rule is inverted
    relative to its first version: instead of matching one exact `lda #<lit>`
    shape on the immediately preceding line, it walks back over the
    instructions that produced the stored register and requires every immediate
    feeding it to name an allocated channel. That closes `%`-binary literals,
    `stx`/`sty`, equated masks, and — the hole that made the rule a one-line
    edit away from silent — ANY intervening line, including the bare `.a8`
    directives that sit next to these stores throughout the codebase


    The target set is the set of symbols that REACH HDMAEN, not the register
    literal alone: the WRAM shadow byte is gated here too, because gating only
    `$420C` while its one and only writer copies an ungated WRAM byte into it
    is a rule that documents a guarantee it does not provide

    """
    findings = []
    aliases = _enable_aliases(lines)
    for i, raw in enumerate(lines, start=1):
        m = STORE_RE.match(_strip(raw))
        if not m:
            continue
        reg = _enable_target(m.group("dest"), aliases)
        if reg is None:
            continue                      # not a mask surface
        op = m.group("op").lower()
        if op == "stz":
            continue                      # disarming is always legal
        ok, bare = _override_near(lines, i - 1)
        if bare:
            findings.append(Finding(
                path, bare[1], "channel",
                "bare `; CHANNEL-LINT: ok` — the override must state WHY the "
                "site is safe by construction (`; CHANNEL-LINT: ok — reason`)"))
            continue
        if ok:
            continue
        imms, verdict = _provenance(lines, i - 1, _REG_OF[op])
        if verdict == "memory":
            continue                      # a shadow/computed mask, not a literal
        bad = [(ln, v) for ln, v in imms if not CH_SYM_RE.search(v)]
        if verdict == "unknown" and not imms:
            findings.append(Finding(
                path, i, "channel",
                f"the value stored to {reg} has no traceable source in this "
                f"file — a channel mask must be built from the allocated "
                f"number (`lda #(1 << ES_H_<CLAIM>_CH)`). Suppress with "
                f"`; CHANNEL-LINT: ok — <reason>` if it is safe by construction"))
            continue
        for ln, v in bad:
            findings.append(Finding(
                path, ln, "channel",
                f"literal channel mask #{v} feeds {reg} (line {i}) — the mask "
                f"names allocated channels. Use `lda #(1 << ES_H_<CLAIM>_CH)` "
                f"(or ES_D_ for a dma_init claim) so enabling a channel goes "
                f"through its declaration"))
    return findings


def scan_channel_encoding(path: Path, lines: list[str]) -> list[Finding]:
    """DMAP/BBAD must come from the emitted symbols, not from a literal.

    See the module docstring's CHANNEL ENCODING paragraph. The rule constrains
    the SHAPE of the write (a literal immediate feeding `<CH_REGS> + 0/+1`, or
    the HDMA shadow's `+0/+1` slots), not the value, so it is not the circular
    check the work item's first pass argued against: nothing here compares the
    literal to the emitted byte, it just refuses to let a site invent one.
    """
    bases = _channel_bases(lines)
    findings = []
    for i, raw in enumerate(lines, start=1):
        line = _strip(raw)
        m = ENC_STORE_RE.match(line)
        if not m:
            continue
        base = m.group("base").upper()
        if base not in bases and not SHADOW_BASE_RE.match(base):
            continue
        off = int(m.group("off") or 0)
        what = "DMAP" if off == 0 else "BBAD"
        op = m.group("op").lower()
        ok, bare = _override_near(lines, i - 1)
        if bare:
            findings.append(Finding(
                path, bare[1], "encoding",
                "bare `; CHANNEL-LINT: ok` — the override must state WHY the "
                "site is safe by construction (`; CHANNEL-LINT: ok — reason`)"))
            continue
        if ok:
            continue
        if op == "stz":
            findings.append(Finding(
                path, i, "encoding",
                f"`stz` writes a literal zero into {what} at {base}+{off} — "
                f"the byte is emitted from the declaration; store "
                f"`ES_[HD]_<CLAIM>_{what}` instead"))
            continue
        imms, verdict = _provenance(lines, i - 1, _REG_OF[op])
        want = rf"ES_[HD]_\w+_{what}"
        if verdict == "immediate" and imms and re.search(want, imms[0][1]):
            continue                      # the emitted symbol, possibly OR-ed
        if verdict == "memory":
            # A table-driven DMAP (probe_vb2reg's tab_cfg) is not a literal in
            # this file, but it is also not the declaration. Reported, so it
            # takes an explicit override with a stated reason.
            findings.append(Finding(
                path, i, "encoding",
                f"{what} at {base}+{off} is loaded from memory rather than "
                f"from ES_[HD]_<CLAIM>_{what} — the declaration is the single "
                f"source of the encoding. Suppress with "
                f"`; CHANNEL-LINT: ok — <reason>` if the value provably "
                f"agrees with the declared footprint"))
            continue
        detail = (f"#{imms[0][1]}" if imms else "a value with no traceable "
                  "source in this file")
        findings.append(Finding(
            path, imms[0][0] if imms else i, "encoding",
            f"{detail} feeds {what} at {base}+{off} (line {i}) — DMAP and BBAD "
            f"are emitted from the claim's declaration. Store "
            f"`ES_[HD]_<CLAIM>_{what}` so the .toml and the silicon cannot "
            f"disagree, or suppress with `; CHANNEL-LINT: ok — <reason>`"))
    return findings


# --- reg ownership: the writer-side gate for claims.reg (docs/09 §2.1) -------
#
# The path map decides which claim set a file answers to:
#
#   engine/features/<name>/*.asm  -> that feature's OWN claims, reloaded from
#        its sibling feature.toml via schemas.load_feature. Directory-keyed,
#        not filename-keyed: the audio feature's asm is tad_wrapper.asm, not
#        audio.asm, and a filename map would silently unwatch it. The toml
#        rather than the symbol map, because the build scans ALL feature files
#        for BOTH games — room_bg.asm is scanned against microzero's map,
#        where room_bg has no presence at all; the toml is the only
#        game-independent source of a feature's claims (and the same loader
#        allocate.py uses, so the gate cannot disagree with the allocator).
#
#   game/<g>/scenes/<s>.asm       -> the scene's UNION from the symbol map:
#        scenes.<s>.reg (the allocator-resolved globals+closure union) plus
#        the union's covered ports (channels/dma_init registers + region-class
#        data ports), NARROWED TO WHAT EACH OWNER OPENED — see `scene_writes`
#        below. Attribution used to say only "someone in this scene declared
#        it"; it now says "and its owner expects enter-time code to write it".
#
#   game/<g>/main.asm             -> the GLOBALS' union: game.toml globals
#        filtered against the map's reg entries by consumer, and narrowed the
#        same way. (Global hdma/dma_init PORT coverage is still not extended
#        here. The map's channel entries DO carry a consumer now — item 5
#        emits it — so the old reason is gone; what remains is that no in-tree
#        boot write needs it, and a future one fails LOUD with the
#        declare-or-own message. Extending it is a decision, not a fix-up.)
#
#   anything else                 -> the COMPOSED UNION of every scene in the
#        map: the floor tier, and the weakest meaningful check ("somebody in
#        this program declared it"). `engine/toy` and the vendored probes take
#        it, and they carry feature.toml declarations — declared, not
#        grandfathered — so the floor still has something to check against.
#        docs/09 §2.1's census boundary keeps them out of the CENSUS, not out
#        of the gate. There is NO "no reg pass" branch — `reg_context` ends
#        `return _composed_union_context(...)`, and engine/toy/main.asm and
#        the three probes all measure as composed-union.
#
# SCENE_WRITES — the owner's consent (docs/09 §2.1 hole 2). The three
# UNION tiers above are closure-wide: they answer "did anyone here declare
# this port", which made scene and boot code an unlimited second writer of
# every port their closure happened to own. A `[[claims.reg]]` may now carry
# `scene_writes`, a subset of its own `registers`, meaning "scene-enter or
# boot code MAY write these registers of mine". The union tiers see only that
# subset — on BOTH arms of the acceptance test:
#
#   declared -> keep an in-class port only if its [[claims.reg]] opens it;
#   covered  -> keep an in-class port put there by an hdma/dma_init claim only
#               if the SAME feature opens that register on a [[claims.reg]]
#               AND lists it in that claim's `scene_writes` (the STRONG
#               reading: consent is uniform across both arms).
#
# Narrowing `declared` alone is not a half-measure, it is inert — race's
# $2105 BGMODE and $212C TM are declared AND covered, so the second disjunct
# accepts them whatever the first says. Region DATA/LATCH ports are NOT
# narrowed either way: a latch rides the claim on the RESOURCE its data port
# serves, which is about hardware structure rather than about who may write.
#
# THE LIMIT THIS LEAVES, stated here because it is met SILENTLY — the write is
# accepted, so there is no diagnostic to read (docs/09 §2.1's
# successor-residue item 8, where it was the only record). Consent is
# per-PORT, not per-scene: the scene tier's union INCLUDES the globals' reg
# claims, so a register a global feature opens is open to EVERY scene, not
# just to the one whose feature needed it. `sm_display` opens NMITIMEN for
# boot, and that also makes `sta a:$4200` legal from any scene file in the
# game. Narrowing it would need consent to name a scope, which is a schema
# change and a decision rather than a fix-up.
#
# The FEATURE-STRICT tier is deliberately unchanged — a feature writing its
# own declared port is already the strong case. `scene_writes` is a PERMISSION
# and not an exclusivity: it does not say the owner stays out. Where the owner
# does write it too, `scene_writes_shared` declares that, and the
# declaration-that-lies check (`scan_reg_declaration_lies`) refuses both
# directions of an untrue declaration — the same discipline `seed` carries.
#
# COVERED (legal without a [[claims.reg]]): the data port of a region class
# the checked claim set holds (vram -> VMDATAL/H, cgram -> CGDATA, oam ->
# OAMDATA), and any port named on its hdma/dma_init claims ("a data port you
# claim as a port" — vwf's `sta $2118` under its VMDATAL/H vblank claim,
# rgb_gradient's COLDATA store under its three plane claims). The address/
# increment latches ($2102/03, $2115-$2117, $2121) carry no footprint name,
# and they are CHECKED, not exempt: each is covered only by the owning
# region's resource claim (oam -> $2102/03, vram -> $2115-$2117, cgram ->
# $2121) — §2.1's covered case as a rule, no longer an accident of the
# footprint table (see the coverage note ~30 lines below). MDMAEN/HDMAEN are
# likewise unnamed; the channel-mask pass polices those by provenance.
#
# stz IS a write here (stz $2105 sets BGMODE 0): the channel-mask pass's
# "stz disarms" exemption is about masks, not modes.

# Multi-port resources hold ONE footprint name, so every port of the resource
# must resolve to that name: `sta $4203` (WRMPYB) is checked against the same
# ALU claim as `sta $4202`. The spans live in `schemas.REGISTER_SPANS`, beside
# the comment blocks that derive each one from Mesen2 — the settled
# default, "one source of truth, in the file whose comments already carry the
# fact". A companion table HERE was the explicitly-rejected
# alternative and shipped anyway in the landed gate's first pass; the reg-gate
# convergence audit (§1.3) measured the two as behaviourally identical and
# ruled the placement, so this is now a lookup, not a table.

# Region class -> the data port(s) a claim of that class covers for CPU writes.
DATA_PORTS: dict[str, tuple[int, ...]] = {
    "vram":  (0x2118, 0x2119),        # VMDATAL / VMDATAH
    "cgram": (0x2122,),               # CGDATA
    "oam":   (0x2104,),               # OAMDATA
    "wram":  (0x2180,),               # WMDATA
}

# --- the PORT CATEGORY map ---------------------------------------------------
#
# Over PORTS, not over footprint names, because several of docs/09 §2.1's
# latches have no name at all: VMAIN, VMADDL/H, CGADD, OAMADDL/H, WMDATA and
# WMADD* are all absent from REGISTER_FOOTPRINT — §2.1's own "C4 needed none
# of them as names".
#
# THIS IS THE LARGEST SINGLE COVERAGE ITEM here, and the reason this rule
# exists: before it, a port with no footprint name was `continue`d as
# "unclaimable, exempt". That reached the right verdict for latches by
# accident — the footprint table happening not to name them — rather than by a
# rule, and it left the gate blind to 48 of the live tree's 158 non-channel io
# write sites (30%), all of them $2116/$2115/$2121/$2102/$2103. Measured, not
# argued: the census reproduces that table character-for-character
# (tools/reg_census.py), so the number is checkable rather than asserted.
#
# The rule a latch now answers to: a latch is the *where* of a data port, so
# it rides the claim on the RESOURCE it serves. `sta $2116` is legal in a file
# that claims `vram`, or that names VMDATAL/VMDATAH on any claim; it is a
# finding in a file that claims neither.
REG_LATCH = {0x2102: ("oam", "OAMADDL"), 0x2103: ("oam", "OAMADDH"),
             0x2115: ("vram", "VMAIN"), 0x2116: ("vram", "VMADDL"),
             0x2117: ("vram", "VMADDH"), 0x2121: ("cgram", "CGADD"),
             0x2181: ("wram", "WMADDL"), 0x2182: ("wram", "WMADDM"),
             0x2183: ("wram", "WMADDH")}
REG_DATA = {0x2104: ("oam", "OAMDATA"), 0x2118: ("vram", "VMDATAL"),
            0x2119: ("vram", "VMDATAH"), 0x2122: ("cgram", "CGDATA"),
            0x2180: ("wram", "WMDATA")}
# resource -> the data port NAMES that hold it. Naming any of them on any
# claim covers the resource's latches too: a latch is the *where* of that
# port. `wram`/WMDATA is latent — no in-tree site writes $2180-$2183 today —
# but WMDATA/WMADD* are a SINGLE GLOBAL CURSOR, so two undeclared users is
# precisely the silent fight this gate exists to refuse.
RESOURCE_PORT_NAMES = {"vram": ("VMDATAL", "VMDATAH"), "cgram": ("CGDATA",),
                       "oam": ("OAMDATA",), "wram": ("WMDATA",)}
# The channel rules' territory: MDMAEN/HDMAEN and every claim's register file.
# Skipped here so a single write is never reported by two rules.
REG_CHANNEL_PORTS = (0x420B, 0x420C)
REG_CHANNEL_FILE = (0x4300, 0x437F)

# --- the WRITE-SHAPE set -----------------------------------------------------
#
# Write-shaped mnemonics. The four stores were the whole set until the RMW
# family was added; `inc a:$2105` and `trb a:$2105` are real 65816 instructions
# that WRITE a PPU port and the gate could not see them at all (probe
# `fp1_rmw`: 0 findings before, 2 after).
#
# stx/sty are in because the tree writes io ports with them — 12 + 3 live
# sites, including vwf.asm's `stx a:$2116` 16-bit VMADD — and because STORE_RE
# already treats all four as stores.
#
# mvn/mvp are NOT here and CANNOT be: both take BANK bytes as operands, never
# an address, so no operand of theirs is ever an io port. (In this tree they
# only ever appear as hand-assembled `.byte $54, ...` data, which is unscanned
# anyway.) Recording the reason because "add every write-shaped mnemonic"
# would otherwise look like an oversight.
REG_WRITE_MN = {"sta", "stx", "sty", "stz",
                "inc", "dec", "asl", "lsr", "rol", "ror", "trb", "tsb"}


def _reg_category(port: int) -> tuple[str, object]:
    """(kind, info) for an io port. kind in {channel, latch, data, in-class,
    unnamed}; info is (resource, name) for latch/data, the covering footprint
    names for in-class, None otherwise."""
    if port in REG_CHANNEL_PORTS or \
            REG_CHANNEL_FILE[0] <= port <= REG_CHANNEL_FILE[1]:
        return "channel", None
    if port in REG_LATCH:
        return "latch", REG_LATCH[port]
    if port in REG_DATA:
        return "data", REG_DATA[port]
    import schemas
    names = schemas.register_covering_names(port)
    return ("in-class", names) if names else ("unnamed", None)

REG_OVERRIDE_RE, REG_BARE_OVERRIDE_RE = _override_res("REG-LINT")

# The ca65 width/bank prefix. ATOMIC — letter and colon together, never
# independently optional. The non-atomic `[azf]?:?` spelling eats the leading
# letter of `sta FADE_EN` and resolves `ADE_EN`, which let literal HDMAEN
# masks past the channel rules (fixed in 20c5c63; the reg-gate convergence
# §1.5 measured the unlanded gate STILL carrying the bug and called the fix
# "the strongest single argument against a wholesale replacement"). Do not
# respell this.
PREFIX_RE = re.compile(r"^\s*(?:[azf]:)?\s*", re.I)


def _name_ports(name: str, footprint: dict) -> tuple[int, ...]:
    """Physical ports a footprint name covers (multi-port resources spanned).

    `footprint` is still a parameter rather than an import so the callers that
    already hold `schemas.REGISTER_FOOTPRINT` keep passing it and the tests
    can hand in a synthetic one; the SPAN half now comes from schemas.
    """
    import schemas
    return tuple(p for lo, hi in schemas.register_span(name)
                 for p in range(lo, hi + 1))


def _port_names(footprint: dict) -> dict[int, set[str]]:
    """port -> footprint names reaching it. A port absent here carries no
    footprint name at all — see `_reg_category`'s `unnamed` verdict."""
    out: dict[int, set[str]] = {}
    for n in footprint:
        for p in _name_ports(n, footprint):
            out.setdefault(p, set()).add(n)
    return out


def _ports_of_names(names, footprint) -> set[int]:
    return {p for n in names for p in _name_ports(n, footprint)}


def _covers_resource(res: set[str], names: set[str], resource: str,
                     port_name: str) -> bool:
    """Does a claim set cover a latch/data port of `resource`? Either it holds
    the region, or it names one of the region's data ports (or the port
    itself) on any claim — 'a data port you claim as a port'.

    Module-level, and the ONE reader of the latch/data-port rule: `RegContext`
    asks it to reach a VERDICT, `_feature_port_owners` asks it to name who
    ELSE covers a port. Making those two separate pieces of code is what goes
    wrong: the survey then looks only at footprint NAMES, so a latch (which
    has none) and a region-claimed data port both report "declared by nobody"
    while a sibling plainly holds the covering claim. A refusal that is
    affirmatively wrong about who owns a resource is worse for a reviewer than
    one that says nothing. One predicate cannot disagree with itself.
    """
    if resource in res:
        return True
    covering = set(RESOURCE_PORT_NAMES.get(resource, ())) | {port_name}
    return bool(covering & names)


def _feature_claim_view(decl) -> tuple[set[str], set[str]]:
    """(footprint names, region classes) a loaded feature declares — the two
    inputs `_covers_resource` asks about, read the same way for the rule and
    for the survey."""
    names = {r for c in (*decl.reg, *decl.hdma, *decl.dma_init)
             for r in c.registers}
    res = {cls for cls in DATA_PORTS if getattr(decl, cls, None)}
    return names, res


class RegContext:
    """The claim set a file's port writes are checked against."""

    def __init__(self, label: str, declared: dict[int, list[str]],
                 covered: set[int], hint: str,
                 names: set[str] | None = None,
                 res: set[str] | None = None,
                 tier: str = "feature-strict",
                 owned: dict[int, list[tuple[str, str, str]]] | None = None):
        self.label = label            # e.g. "feature 'vwf'" / "scene 'race'"
        # Which TIER checked this file. The tiers are not equally
        # strong — a scene file is checked against the union of its whole
        # closure, so "someone in this scene declared it" is all it can say
        # (docs/09 §2.1 hole 2, still open) — and a summary line that hides
        # that reports a weaker check as if it were the strict one.
        self.tier = tier
        self.declared = declared      # port -> ["claim 'x' (engine:f)", ...]
        self.covered = covered        # ports legal without a reg claim
        self.hint = hint              # where a missing declaration belongs
        # The latch verdict is over NAMES and RESOURCE CLASSES, not
        # over ports — "does this file claim `vram`, or name VMDATAL on any
        # claim" cannot be asked of a port set. Populated by every context
        # builder from the SAME claim data `declared`/`covered` come from, so
        # the two views cannot disagree about what a file declares.
        self.names = names or set()   # footprint names on reg/hdma/dma_init
        self.res = res or set()       # region classes claimed (vram/oam/...)
        # item 5: ports this closure OWNS but whose owner did not open to
        # scene/boot code. Nothing is ever ACCEPTED on this — it is only how
        # the refusal names who to go and ask. Empty at the feature-strict
        # tier, which is not narrowed.
        self.owned = owned or {}

    def satisfies_resource(self, resource: str, port_name: str) -> bool:
        """Is a latch/data port of `resource` covered here? See
        `_covers_resource` — the same predicate the owner survey asks, so a
        site the rule ALLOWS via a resource claim is a site the survey can
        NAME the holder of."""
        return _covers_resource(self.res, self.names, resource, port_name)


_SUBSTRATE_CACHE: list = []           # lazy singleton; [None] = load failed


def _substrate():
    if not _SUBSTRATE_CACHE:
        import schemas
        _SUBSTRATE_CACHE.append(
            schemas.load_substrate(Path(__file__).parent / "substrate.toml"))
    return _SUBSTRATE_CACHE[0]


def _tomllib():
    """tomllib, imported lazily — the tool stays a standalone script and the
    rules that never touch a .toml never pay for it."""
    import tomllib
    return tomllib


def _load_decl(loader, toml: Path, what: str, path: Path):
    """Load a declaration, or return the Finding that says why not.

    A declaration that cannot be READ is a finding, never a traceback.
    Catching `schemas.SchemaError` alone covers every WRONG-TYPED shape —
    `load_feature` validates types thoroughly (`claims` as a string,
    `registers` as a string, `words` as a string all produce clean findings)
    — but NOT a TOML SYNTAX error, which raises `tomllib.TOMLDecodeError`
    straight through the gate as a traceback (convergence §1.6, probe
    `badtoml`).

    AttributeError/TypeError are caught alongside. `schemas`' own type
    validation already closes them, so they are belt-and-braces: a future
    loader change cannot silently reopen a wrong-typed shape as a
    traceback, it reopens as a finding. `Exception` is deliberately NOT
    caught: a bug in the gate must not be laundered into a declaration
    complaint.
    """
    import schemas
    tomllib = _tomllib()
    try:
        return loader()
    except schemas.SchemaError as e:
        return Finding(path, 1, "reg", f"{what} failed to load: {e}")
    except tomllib.TOMLDecodeError as e:
        return Finding(path, 1, "reg",
                       f"`{toml}` does not parse as TOML ({e}) — the "
                       f"declaration cannot be read, so nothing can be "
                       f"checked against it, and falling through would give "
                       f"this file's io writes the WEAKEST check instead of "
                       f"the strict one. Fix the file")
    except (AttributeError, TypeError) as e:
        return Finding(path, 1, "reg",
                       f"`{toml}` parsed as TOML but is not a well-formed "
                       f"{what} ({type(e).__name__}: {e}) — the declaration "
                       f"cannot be read. Fix the file")


def _feature_reg_context(path: Path) -> "RegContext | Finding":
    """engine/features/<name>/*.asm -> the feature's own claims."""
    import schemas
    toml = path.parent / "feature.toml"
    if not toml.exists():
        return Finding(path, 1, "reg",
                       f"feature file has no sibling feature.toml at {toml} — "
                       f"every engine/features/<name>/ dir declares one")
    decl = _load_decl(lambda: schemas.load_feature(toml, _substrate()),
                      toml, "feature.toml", path)
    if isinstance(decl, Finding):
        return decl
    fp = schemas.REGISTER_FOOTPRINT
    declared: dict[int, list[str]] = {}
    for c in decl.reg:
        for p in _ports_of_names(c.registers, fp):
            declared.setdefault(p, []).append(
                f"[[claims.reg]] '{c.name}' of feature '{decl.name}'")
    names, res = _feature_claim_view(decl)
    covered = set()
    for c in (*decl.hdma, *decl.dma_init):
        covered |= _ports_of_names(c.registers, fp)
    for cls in res:
        covered.update(DATA_PORTS[cls])
    return RegContext(
        f"feature '{decl.name}'", declared, covered,
        f"add a [[claims.reg]] to {toml}", names, res)


def _resource_claim_label(decl, resource: str, port_name: str) -> str:
    """WHY a sibling covers a latch/data port of `resource`, in one clause.

    The region arm is the common one; the name arm is the `vwf` shape (no
    region claim, VMDATAL/H named on a vblank hdma claim) — which covers that
    resource's LATCHES too, so the survey has to be able to say so."""
    if resource in _feature_claim_view(decl)[1]:
        return f"{resource} region claim"
    covering = set(RESOURCE_PORT_NAMES.get(resource, ())) | {port_name}
    for kind, claims in (("", decl.reg), ("hdma ", decl.hdma),
                         ("dma_init ", decl.dma_init)):
        for c in claims:
            hit = sorted(covering & set(c.registers))
            if hit:
                return f"{kind}claim '{c.name}' names {'/'.join(hit)}"
    return f"{resource} claim"             # unreachable: the caller tested it


def _feature_port_owners(path: Path, port: int, resource: str | None = None,
                         port_name: str | None = None) -> list[str]:
    """Which sibling features (same engine/features root) hold `port` — on a
    [[claims.reg]], or by naming it on an hdma/dma_init claim (labelled by
    claim kind). The port-claim survey exists because §2.1's first real
    collision pair is exactly that shape: window_iris's COLDATA store vs
    rgb_gradient's three COLDATA-plane hdma claims — a reg-only survey said
    "declared by nobody" about it. Finding-path only — the clean path never
    loads the whole dir.

    `resource`/`port_name` are set for a latch or data port, and extend the
    survey to the resource-claim shape: a sibling that holds the REGION
    (`[[claims.vram]]`), or that names one of the region's data ports, may
    legally drive this port even though it names nothing that resolves TO it.
    Without them every one of the 79 newly-covered latch sites reported
    "declared by nobody" while a sibling held the covering claim — the same
    wrong-attribution defect, on the newly covered category. Tested with
    `_covers_resource`, the predicate the RULE uses, so a site the gate
    permits is a site the survey can attribute.
    """
    import schemas
    fp = schemas.REGISTER_FOOTPRINT
    owners = []
    for toml in sorted(path.parent.parent.glob("*/feature.toml")):
        if toml == path.parent / "feature.toml":
            continue
        try:
            d = schemas.load_feature(toml, _substrate())
        except (schemas.SchemaError, _tomllib().TOMLDecodeError,
                AttributeError, TypeError):
            # The same class one level out: a SIBLING whose toml will not
            # load must not take down the refusal being written ABOUT ANOTHER
            # FILE. Skipping it only costs a name in the "declared elsewhere
            # by" list; tracebacking here would replace a real finding with a
            # crash, which is strictly worse. The sibling gets its own finding
            # when the gate reaches it.
            continue
        why: list[str] = []
        for c in d.reg:
            if port in _ports_of_names(c.registers, fp):
                why.append(f"claim '{c.name}'")
        for kind, claims in (("hdma", d.hdma), ("dma_init", d.dma_init)):
            for c in claims:
                if port in _ports_of_names(c.registers, fp):
                    why.append(f"{kind} claim '{c.name}'")
        if not why and resource is not None:
            # Only when the port-name survey found nothing for this sibling:
            # naming the port IS the more precise statement, and a feature
            # that does both should be reported once.
            names, res = _feature_claim_view(d)
            if _covers_resource(res, names, resource, port_name):
                why.append(_resource_claim_label(d, resource, port_name))
        owners += [f"{d.name} ({w})" for w in why]
    return owners


# --- item 5: the weak tiers see only what the OWNER opened ------------------
#
# The three union tiers (scene, globals, composed) used to accept any port
# their closure declared — "someone in this scene declared this port". That is
# docs/09 §2.1's hole 2: the port's OWNER was never asked whether scene-enter
# or boot code is supposed to write it, so scene and boot code were an
# unlimited second writer of every port their closure happened to own.
#
# `scene_writes` is that consent, and these three helpers are how the tiers
# read it. The FEATURE-STRICT tier is deliberately untouched — a feature
# writing its own declared port is already the strong case.
#
# Note what is NOT narrowed, in both helpers: the region data/latch ports
# (OAMDATA, VMDATAL/H, CGDATA, WMDATA, $2102/03, $2115-$2117, $2121). A latch
# rides the claim on the RESOURCE its data port serves, which is a statement
# about hardware structure rather than about who may write it, and narrowing
# it would refuse every shipped upload path. That is a stated limit and it
# stays whole.

def _reg_claim_view(reg_entries, footprint) \
        -> tuple[dict[int, list[str]], dict[int, list[tuple[str, str, str]]],
                 set[str], dict[str, set[str]]]:
    """Read a map's `reg` entries into the four views the tiers need.

    declared  — ports the claims OPEN to scene/boot code (from `scene_writes`).
                THIS is the narrowing: pre-item-5 it was every port the claim
                HELD.
    owned     — ports a claim holds but does NOT open, as
                (who, register NAME, claim KIND) triples. Nothing accepts on
                this; it exists so the refusal can name who to go and ask, and
                print the one-line fix. A refusal that says "declared by
                nobody" about a port whose owner is three lines away in a toml
                teaches nothing. The name and the kind are carried because the
                ADVICE depends on both — see `_reg_verdict`.
    names     — every footprint name on the claims, NOT narrowed. It feeds the
                latch/data resource view (`satisfies_resource`), which is not
                what this work is about.
    consent   — consumer -> the register NAMES it opened, for the `covered`
                narrowing below, which has to ask "did the feature that COVERS
                this port also open it".
    """
    declared: dict[int, list[str]] = {}
    owned: dict[int, list[tuple[str, str, str]]] = {}
    names: set[str] = set()
    consent: dict[str, set[str]] = {}
    for c in reg_entries:
        names |= set(c["registers"])
        opened = set(c.get("scene_writes", ()))
        consent.setdefault(c["consumer"], set()).update(opened)
        who = f"[[claims.reg]] '{c['name']}' ({c['consumer']})"
        for n in c["registers"]:
            for p in _ports_of_names((n,), footprint):
                if n in opened:
                    if who not in declared.setdefault(p, []):
                        declared[p].append(who)
                elif (who, n, "reg") not in owned.setdefault(p, []):
                    owned[p].append((who, n, "reg"))
    return declared, owned, names, consent


def _kinded_transfers(sc: dict) -> list[tuple[str, dict]]:
    """A scene's transfer claims, each tagged with the CLASS it was declared
    as. `channels` are claims.hdma (both phases) and `dma_init` are
    claims.dma_init — a distinction `check_reg_ownership` acts on and a merged
    tuple threw away."""
    return ([("hdma", c) for c in sc.get("channels", [])]
            + [("dma_init", c) for c in sc.get("dma_init", [])])


def _transfer_covered(entries, consent: dict[str, set[str]], footprint,
                      owned: dict[int, list[tuple[str, str, str]]] | None = None
                      ) -> set[int]:
    """Ports an hdma/dma_init claim covers, with the IN-CLASS half narrowed.

    `entries` is (KIND, claim) pairs, kind in {"hdma", "dma_init"}. The kind is
    carried into `owned` because the reachable FIX differs by it: `seed`
    exempts an hdma overrider and does NOT exempt a dma_init
    (`check_reg_ownership`, allocate.py), so advising a seed'd reg claim
    against a dma_init would be advice the build then refuses.

    Pre-item-5 every port named on any transfer claim in the closure was
    covered outright, and narrowing only `declared` would have left that
    disjunct wide open — measured, that leaves $211B-$211E M7A-M7D and $2132
    COLDATA writable from race.asm and $2126/$2127 WH0/WH1 from room.asm with
    zero findings, and leaves the mechanism INERT on its own worked example
    ($2105 BGMODE and $212C TM in race are declared AND covered, so the second
    disjunct accepts them whatever the first says).

    So an in-class port survives only if the SAME feature opens that register
    on a [[claims.reg]] **and lists it in that claim's `scene_writes`** — the
    STRONG reading of the rule (owner-
    confirmed 2026-08-02). The weak reading would stop at "opens it on a
    [[claims.reg]]", which lets an HDMA owner that merely happens to hold a
    reg claim grant scene writes it never consented to — the precise gap this
    work item exists to close, reopened on the arm it was extended to cover.
    Measured cost of strong over weak on the tree: zero.

    A port that fails the check is recorded in `owned` (when given) against
    the transfer claim, so the refusal can name it.
    """
    out: set[int] = set()
    for kind, c in entries:
        who = c.get("consumer")
        opened = consent.get(who, set())
        for n in c["registers"]:
            ports = _ports_of_names((n,), footprint)
            if n in opened:
                out |= ports
                continue
            for p in ports:
                if _reg_category(p)[0] != "in-class":
                    # Region data/latch: NOT narrowed, and not covered here
                    # either. It reaches the same verdict one rule later, on
                    # the RESOURCE route (`satisfies_resource`), because
                    # `names` is unioned with these same transfer registers by
                    # both callers. Measured exhaustively over
                    # REGISTER_FOOTPRINT: the only non-in-class ports any
                    # claimable name reaches are
                    # OAMDATA/VMDATAL/VMDATAH/CGDATA, each of them the
                    # RESOURCE_PORT_NAMES entry of its own region — so adding
                    # them to `out` here changed no verdict anywhere, in
                    # either direction, and NO fixture could tell the two
                    # spellings apart (experiments 9 and 10: 112/112 green
                    # with the arm removed). Stating the redundancy is honest
                    # where an unfalsifiable `out.add(p)` claiming to be the
                    # data/latch guarantee was not; the property that makes it
                    # redundant is pinned by
                    # test_the_resource_route_owns_every_data_port_a_claim_can_name.
                    continue
                if owned is not None:
                    label = (f"transfer claim '{c['name']}'"
                             + (f" ({who})" if who else ""))
                    if (label, n, kind) not in owned.setdefault(p, []):
                        owned[p].append((label, n, kind))
    return out


def _scene_union(sc: dict, globals_placements: list, footprint) \
        -> tuple[dict[int, list[str]], set[int], set[str], set[str],
                 dict[int, list[tuple[str, str, str]]]]:
    declared, owned, names, consent = _reg_claim_view(sc.get("reg", []),
                                                      footprint)
    transfers = _kinded_transfers(sc)
    covered = _transfer_covered(transfers, consent, footprint, owned)
    for _kind, c in transfers:
        names |= set(c["registers"])
    classes = {p["class"] for p in (*sc.get("placements", []),
                                    *globals_placements)}
    res: set[str] = set()
    for cls, ports in DATA_PORTS.items():
        if cls in classes:
            covered.update(ports)
            res.add(cls)
    return declared, covered, names, res, owned


def _scene_reg_context(path: Path, raw_map: dict) -> "RegContext | Finding":
    """game/<g>/scenes/<s>.asm -> the scene's union from the symbol map."""
    import schemas
    sid = path.stem
    sc = raw_map.get("scenes", {}).get(sid)
    if sc is None:
        return Finding(
            path, 1, "reg",
            f"scene file '{sid}' is not a scene in the symbol map "
            f"({sorted(raw_map.get('scenes', {}))}) — declare it in game.toml "
            f"so its features' claims exist to check against")
    declared, covered, names, res, owned = _scene_union(
        sc, raw_map.get("globals", []), schemas.REGISTER_FOOTPRINT)
    return RegContext(
        f"scene '{sid}'", declared, covered,
        "add a [[claims.reg]] to the feature.toml of the feature this write "
        "serves (docs/09 §2.1's attribution convention), and list that "
        "feature in the scene", names, res, "scene-union", owned)


def _main_reg_context(path: Path, raw_map: dict) -> "RegContext | Finding":
    """game/<g>/main.asm -> the globals' union (boot/top-level code)."""
    import schemas
    gt = path.parent / "game.toml"
    if not gt.exists():
        return Finding(path, 1, "reg",
                       f"game top-level file has no sibling game.toml at {gt}")
    manifest = _load_decl(lambda: schemas.load_manifest(gt),
                          gt, "game.toml", path)
    if isinstance(manifest, Finding):
        return manifest
    fp = schemas.REGISTER_FOOTPRINT
    global_consumers = {f"engine:{g}" for g in manifest.globals_}
    declared: dict[int, list[str]] = {}
    owned: dict[int, list[tuple[str, str, str]]] = {}
    names: set[str] = set()
    for sc in raw_map.get("scenes", {}).values():
        for c in sc.get("reg", []):
            if c["consumer"] not in global_consumers:
                continue
            # NOTE — the FILTER is load-bearing and stays. `names` is
            # built from the SAME globals-filtered claims as `declared`, so
            # the latch rule inherits the globals' union rather than the
            # composed union of every scene. The unlanded gate used the
            # composed union here and the convergence measured the landed
            # rule as STRICTLY STRONGER (§1.9, probe `tierprobe`: a boot
            # write to a port only a SCENE feature declares FIRES here and is
            # SILENT there). Explicitly on the do-not-port list.
            names |= set(c["registers"])
            # item 5: the globals' union asks the OWNER too. Boot writing a
            # port a global feature merely HOLDS is exactly the hole — the
            # sm_display shape, where NMITIMEN is boot's to write and INIDISP
            # is committed by scene_mgr's own NMI hook every frame.
            opened = set(c.get("scene_writes", ()))
            who = f"[[claims.reg]] '{c['name']}' ({c['consumer']})"
            for n in c["registers"]:
                for p in _ports_of_names((n,), fp):
                    if n in opened:
                        if who not in declared.setdefault(p, []):
                            declared[p].append(who)
                    elif (who, n, "reg") not in owned.setdefault(p, []):
                        owned[p].append((who, n, "reg"))
    covered = set()
    res: set[str] = set()
    classes = {p["class"] for p in raw_map.get("globals", [])}
    for cls, ports in DATA_PORTS.items():
        if cls in classes:
            covered.update(ports)
            res.add(cls)
    return RegContext(
        f"game '{path.parent.name}' top-level (globals' union)", declared,
        covered,
        "add a [[claims.reg]] to a GLOBAL feature's feature.toml — boot code "
        "answers to the globals' union; a scene feature's claim does not "
        "reach it", names, res, "globals-union", owned)


def _composed_union_context(path: Path, raw_map: dict) -> "RegContext":
    """The DEFAULT tier for a path matching no other shape.

    Returning None here — no reg pass at all — would let `engine/toy/main.asm`
    plus the three vendored probes fall straight through. That is fail-OPEN on
    a new surface: a file added to any scan list is silently unchecked, and the
    only thing the gate prints about it is "clean". Measured:
    `engine/toy/main.asm` -> `1 file(s) clean`, ZERO io write sites examined,
    while the same file holds 29 of them (convergence §1.10).

    The composed union of every scene in the map is the WEAKEST meaningful
    check — "somebody in this program declared it" — and that is the point:
    it is strictly better than nothing, and the map handed to any one
    invocation always belongs to that invocation's game, so it is also sound.
    A file that deserves a stronger tier gets one by matching a stronger
    shape; this is the floor, not the target.
    """
    import schemas
    declared: dict[int, list[str]] = {}
    owned: dict[int, list[tuple[str, str, str]]] = {}
    names: set[str] = set()
    covered: set[int] = set()
    res: set[str] = {p["class"] for p in raw_map.get("globals", [])}
    fp = schemas.REGISTER_FOOTPRINT
    for sc in raw_map.get("scenes", {}).values():
        # item 5: the floor tier narrows too. The toy and the vendored probes
        # take this tier and they DO carry declarations, so there
        # is something to narrow against; leaving the floor un-narrowed would
        # make it the one door boot code could still write anything through.
        d, o, n, consent = _reg_claim_view(sc.get("reg", []), fp)
        for src, dst in ((d, declared), (o, owned)):
            for p, whos in src.items():
                for w in whos:
                    if w not in dst.setdefault(p, []):
                        dst[p].append(w)
        names |= n
        transfers = _kinded_transfers(sc)
        covered |= _transfer_covered(transfers, consent, fp, owned)
        for _kind, c in transfers:
            names |= set(c["registers"])
        res |= {p["class"] for p in sc.get("placements", [])}
    for cls, ports in DATA_PORTS.items():
        if cls in res:
            covered.update(ports)
    n = len(raw_map.get("scenes", {}))
    return RegContext(
        f"the composed union of {n} scene(s)", declared, covered,
        "add a [[claims.reg]] to the feature.toml of the feature this write "
        "serves, and compose that feature into this program",
        names, res, "composed-union", owned)


def reg_context(path: Path, raw_map: dict) -> "RegContext | Finding | None":
    """Resolve which claim set `path` answers to.

    There is no out-of-scope answer for a real file. The tiers, strongest
    first: a feature file answers to its OWN toml; a scene file to that
    scene's union; `main.asm` to the globals' union; anything else to the
    composed union (`_composed_union_context`).
    """
    parts = path.parts
    if len(parts) >= 4 and parts[-4:-2] == ("engine", "features"):
        return _feature_reg_context(path)
    if (len(parts) >= 4 and parts[-4] == "game" and parts[-2] == "scenes"
            and path.suffix == ".asm"):
        return _scene_reg_context(path, raw_map)
    if len(parts) >= 3 and parts[-3] == "game" and parts[-1] == "main.asm":
        return _main_reg_context(path, raw_map)
    return _composed_union_context(path, raw_map)


# --- the fail-closed fold -----------------------------------------------------
#
# The port value that means "this operand reaches the io window, but its
# EFFECTIVE port cannot be folded from this file's text". Not a real port —
# every io port is >= $2100 — so it can share the return channel with one, and
# every caller must fail CLOSED on it rather than fall back to the base.
#
# Before this, `_port_expr_value` returned None for anything that was not
# a `+`-sum (`- 1`, `| $0006`, `+ SYM`), `_store_port` passed the None on, and
# the site was SILENTLY SKIPPED. A review found that and accepted it as stated
# residue, correcting only the prose. Probes then proved all three spellings
# live (`fp3_minus` / `fp4_or` / `rg_unfoldable_fires`: silent before, firing
# after) and turned up the sharpest version — `sta a:$2107 - 1` IS a MOSAIC
# write, and the earlier gate produced ZERO findings of any kind on it, because
# the address rule permits `$2107` as an io literal.
#
# Reporting the base IS the laundering: `sta a:$2100 + 5` is BGMODE, not
# INIDISP.
UNRESOLVED_PORT = -1


def _site_id(idx: int, port: int):
    """What an override is SCOPED to, for the write at 0-based line `idx`.

    A resolved write is identified by its PORT: two `sta a:$2101` are the same
    subject, and `; REG-LINT: ok $2101` covers both — that is the whole
    model. An UNFOLDABLE write has no port, so it is identified by its LINE.

    Using the sentinel AS the identity does not work: `-1 == -1` makes every
    unfoldable write in a file the SAME subject. Two consequences, both
    measured before the fix — one cosmetic, one a silence:

      * the ambiguity diagnostic formatted it as a port, `$-001`, and told the
        author to type `; REG-LINT: ok $-001 — <reason>`, which the override
        grammar's `\\$(?P<port>[0-9A-Fa-f]+)` rejects, so following the printed
        advice VERBATIM was silently ignored;
      * rule 2 matched one unfoldable write's override against ANOTHER's:
        `sta a:$2100 + STRIDE  ; REG-LINT: ok — this one is safe` silenced
        `sta a:$2107 - 1` (which IS a MOSAIC write — the fold rule's
        sharpest case) on the next line. Zero findings. Rule 3 would do the
        same via the radius set, two unfoldable sites collapsing to one
        member.

    A sentinel is not an address and it is not an identity. This makes that
    structural rather than remembered.
    """
    return port if port != UNRESOLVED_PORT else (UNRESOLVED_PORT, idx)


def _site_label(site) -> str:
    """How a site is NAMED to a reader. `$-001` is not a port anyone can look
    up; an unfoldable operand has to be described as the state it is in.

    This once had no caller at all and its literal was hand-copied into
    `_window_desc`'s singular branch — two sources for one sentence, which is
    how the two drift. `_window_desc` routes through it, so the function has
    exactly one caller and the sentence has exactly one home.
    """
    return (f"${site:04X}" if isinstance(site, int)
            else "an operand whose port cannot be folded")


def _window_desc(sites) -> str:
    """The ±3-line window's contents, for the ambiguity refusal. Ports first
    and sorted; the unfoldable sites counted rather than repeated, because
    'an operand whose port cannot be folded' twice reads as a bug."""
    parts = [f"${p:04X}" for p in sorted(s for s in sites if isinstance(s, int))]
    n = sum(1 for s in sites if not isinstance(s, int))
    if n == 1:
        parts.append(_site_label(None))
    elif n > 1:
        parts.append(f"{n} operands whose port cannot be folded")
    return ", ".join(parts)

# A write operand: an optional width/bank prefix, then the BASE term (a
# literal or a symbol), then whatever follows it. Anchored, so the base is the
# FIRST term rather than any literal found anywhere in the expression.
BASE_TERM_RE = re.compile(
    rf"^\s*(?:[azf]:)?\s*(?P<base>{HEX}|{BIN}|{DEC}|[A-Za-z_@]\w*)"
    rf"(?P<tail>.*)$")
INDEX_SUFFIX_RE = re.compile(r",\s*[xy]\s*$", re.I)


def _fold_offset(tail: str) -> int | None:
    """The constant added to a write's base operand, or None if not constant.

    Evaluated rather than pattern-matched, so `+5`, `+ 5` and `+1+4` are one
    case — a rule that reads an offset textually only knows the spellings
    someone thought of.

    None means "there is a term here I cannot fold" (`+ SYM`, `- 1`, `| $10`,
    `<< 4`). The caller fails closed on that instead of reporting the base.
    """
    t = INDEX_SUFFIX_RE.sub("", tail.strip()).strip()
    if not t:
        return 0
    if not re.fullmatch(rf"(?:\s*\+\s*{NUM}\s*)+", t):
        return None
    return sum(_lit_value(m.group(0))[0] for m in re.finditer(NUM, t))


def _port_expr_value(expr: str, aliases: dict[str, int]) -> int | None:
    """`$2105` / `8453` / `%...` / `ALIAS` / any `+`-sum of those -> value.

    Kept for the ADDRESS rule's callers. The reg pass resolves through
    `_store_port`, which folds fail-closed; this one still returns None for an
    unfoldable term because its callers want a value or nothing.
    """
    total = 0
    for term in expr.split("+"):
        term = term.strip()
        if not term:
            return None
        if re.fullmatch(NUM, term):
            total += _lit_value(term)[0]
        elif term in aliases:
            total += aliases[term]
        else:
            return None
    return total


def _port_aliases(lines: list[str]) -> dict[str, int]:
    """File-local equates that resolve to an I/O port value, to a fixpoint.

    `MY_BGMODE = $2105` / `sta a:MY_BGMODE` must get the same verdict as the
    literal spelling — this tool's own history is four
    rounds of textual patterns being spelled around, and the fix each time
    was resolution. Cross-file equates stay invisible: the tool-wide
    single-file limit.
    """
    aliases: dict[str, int] = {}
    for _ in range(8):                  # depth bound; chains are short
        grew = False
        for raw in lines:
            line = _strip(raw)
            if DIRECTIVE_RE.match(line):
                continue
            m = ASSIGN_LHS_RE.match(line)
            if not m or m.group("sym") in aliases:
                continue
            # An equate's RHS is the SAME expression shape as a write's
            # operand, so it is resolved by the SAME function rather than by a
            # second reading of it. Not tidiness — a second door here, where
            # the definition side takes `rest.split("+")[0]`, resolves `BGM =
            # $2100 + 5` to INIDISP and launders a BGMODE write. One resolver
            # cannot disagree with itself. UNRESOLVED_PORT propagates, so `FOO
            # = $2100 + BAR` / `sta a:FOO` fails closed too.
            v = _store_port(m.group("rest").strip(), aliases)
            if v is not None:
                aliases[m.group("sym")] = v
                grew = True
        if not grew:
            break
    return aliases


def _store_port(dest: str, aliases: dict[str, int]) -> int | None:
    """The bank-0 I/O port a store destination reaches, or None.

    Handles literals in any base, long bank-0 forms ($002105), file-local
    aliases (+ additive offsets), and strips an index suffix — an indexed
    store is resolved at its base port (no in-tree instance; a computed
    index that walks ports is invisible to a single-file scan, same stance
    as the rest of the tool). `f:$7E2105` is WRAM, not a port: skipped here,
    owned by the address rule.
    """
    d = INDEX_SUFFIX_RE.sub("", dest.strip()).strip()
    if d.startswith("(") or d.startswith("["):
        return None                     # indirect: unknowable in one file
    # BASE_TERM_RE carries the ca65 width/bank prefix in the ATOMIC form.
    # STORE_RE eats it for its own callers, but the mnemonic-based
    # enumeration hands the operand over untouched, so the one resolver has to
    # know the syntax — rather than a second call site re-parsing it and
    # drifting. That drift is exactly the non-atomic `[azf]?:?` spelling: it
    # eats the leading letter of `sta FADE_EN` and resolves `ADE_EN`.
    m = BASE_TERM_RE.match(d)
    if not m:
        return None
    tok, tail = m.group("base"), m.group("tail")
    if re.fullmatch(NUM, tok):
        v = _lit_value(tok)[0]
        if (v >> 16) != 0:
            return None                 # `f:$7E2105` is WRAM, not a port
        v &= 0xFFFF
    elif tok in aliases:
        v = aliases[tok]
    else:
        return None
    if v == UNRESOLVED_PORT:
        return UNRESOLVED_PORT          # propagates through an alias chain
    if not _in_io(v):
        return None
    # Fail CLOSED on a term this file cannot fold.
    off = _fold_offset(tail)
    if off is None:
        if REG_CHANNEL_FILE[0] <= v <= REG_CHANNEL_FILE[1]:
            # `<FEAT>_REGS = $4300 + ES_[HD]_<CLAIM>_CH * 16` is the tree's own
            # way of spelling a channel's base, and the whole $4300-$437F
            # extent belongs to the channel rules — hand it on as before.
            return v
        return UNRESOLVED_PORT
    v += off
    return v if _in_io(v) else None


def _in_io(v: int) -> bool:
    """The bank-0 io window this tool polices."""
    return 0x2100 <= v <= 0x21FF or 0x4200 <= v <= 0x43FF


def _reg_override_for(lines: list[str], idx: int, port: int, site,
                      radius_sites: set,
                      line_sites: dict) -> tuple[bool, tuple | None]:
    """Does a reg override excuse the write at `idx` (0-based), for `port`?

    The both-sides-missed MEDIUM (convergence §4.4 item 1). A SITE-RADIUS
    override — any `; REG-LINT: ok — reason` within ±3 lines silencing ANY
    reg finding in that window — is not enough. Probe `fp12_radius`: one
    `; REG-LINT: ok — BGMODE is safe here by construction` silenced an
    entirely unrelated, undeclared `sta a:$2101` (OBSEL) on the next line.
    BOTH gates: 0 findings.

    Deferring that is tempting — width/zp/channel share the identical
    radius grammar, so port-scoping the reg rule alone forks the convention —
    but the severity is understated by it. The override is a REVIEWER-FACING
    artifact: a reviewer reading a stated BGMODE reason has no cue that an
    OBSEL write is riding on it. That is the rubber-stamping regression the
    repo's own override convention warns about.

    So the override is now PORT-SCOPED, by three rules, in order:

    1. **Explicit port** — `; REG-LINT: ok $2101 — reason` excuses only
       $2101, anywhere in radius. Always unambiguous.
    2. **Same line as the write** — the comment is attached to the
       instruction, so it excuses THAT write and nothing else. This is what
       closes fp12_radius: the override sits on the $2105 line, so the $2101
       write one line later is not covered by it.
    3. **Standalone, no port** — excuses the radius ONLY IF every would-be
       finding in it resolves to the same port. That is today's behaviour for
       every real case (all three shipped fixtures, and every live override —
       of which there are currently zero). If the window spans two or more
       DISTINCT ports it is AMBIGUOUS: the override does not apply, and the
       author is told to name the port.

    Rule 3 is what keeps this an EXTENSION rather than a fork — the
    unscoped spelling still works wherever it was unambiguous to begin with.

    `site`/`radius_sites`/`line_sites` are SITE IDENTITIES (`_site_id`), not
    ports: rules 2 and 3 ask "is this the same subject?", and for a write
    whose port will not fold the answer is per-LINE, not "every unfoldable
    write is the same one". Rule 1 still takes the port,
    because naming one is what rule 1 is — and an unfoldable write has no
    port to name, so no explicit-port override can ever reach it. The
    ambiguity refusal says so instead of printing the sentinel.
    """
    ambiguous = None
    for k in range(max(0, idx - 3), min(len(lines), idx + 4)):
        m = REG_OVERRIDE_RE.search(lines[k])
        if m:
            named = m.group("port")
            if named is not None:                       # rule 1
                if int(named, 16) == port:
                    return True, None
                continue                    # names a DIFFERENT port: not ours
            own = line_sites.get(k)
            if own is not None:                         # rule 2
                # The comment is attached to an instruction, so it excuses
                # THAT instruction's site — whether or not it would itself
                # have fired. This is the clause that closes fp12_radius: the
                # reason names BGMODE, the override sits on the BGMODE line,
                # and the OBSEL write next door is not covered by it.
                if own == site:
                    return True, None
                continue
            if len(radius_sites) <= 1:                  # rule 3
                return True, None
            ambiguous = ("ambiguous", k + 1)
            continue
        if REG_BARE_OVERRIDE_RE.search(lines[k]):
            return False, ("bare", k + 1)
    return False, ambiguous


def scan_reg_ownership(path: Path, lines: list[str],
                       ctx: "RegContext | Finding | None",
                       stats: dict | None = None) -> list[Finding]:
    """An in-scope port store must be declared or covered — see the block
    comment above for the path map, the covered rule, and the residue.

    `stats` accumulates the census the summary line reports. It is
    optional so the pass keeps working for a caller that only wants findings.
    """
    if stats is not None and ctx is not None and not isinstance(ctx, Finding):
        stats["tiers"][ctx.tier] = stats["tiers"].get(ctx.tier, 0) + 1
    if ctx is None:
        if stats is not None:
            stats["tiers"]["no-reg-pass"] = \
                stats["tiers"].get("no-reg-pass", 0) + 1
        return []
    if isinstance(ctx, Finding):
        return [ctx]
    import schemas
    port_names = _port_names(schemas.REGISTER_FOOTPRINT)
    findings: list[Finding] = []
    aliases = _port_aliases(lines)

    # PASS 1 — resolve every write-shaped site. Override scoping needs the
    # whole map before it can decide any override's scope: rule 2 asks "does the
    # override's OWN line hold a write?" (whether or not that write would
    # itself fire), and rule 3 asks "does this radius hold more than one
    # would-be finding?". Neither is answerable one line at a time.
    #
    # Enumerate by MNEMONIC, not by STORE_RE. The four stores were the whole
    # write set until the RMW family was added; `inc a:$2105` and
    # `trb a:$2105` write a PPU port and were invisible. STORE_RE is left
    # untouched — `scan_enables`/`scan_channel_encoding` share it, and its
    # atomic prefix is what makes those two fast.
    line_sites: dict = {}                   # 0-based line -> _site_id
    candidates: list[tuple] = []            # (line1, port, kind, info, rest)
    for i, raw in enumerate(lines, start=1):
        line = _strip(raw)
        if not line.strip() or DIRECTIVE_RE.match(line):
            continue
        if ASSIGN_RE.match(line) and not LABEL_RE.match(line):
            continue                    # `FOO = $2105` defines, never writes
        mi = MNEMONIC_RE.match(LABEL_RE.sub("", line))
        if not mi or mi.group("mn").lower() not in REG_WRITE_MN:
            continue
        port = _store_port(mi.group("rest") or "", aliases)
        if port is None:
            continue
        line_sites[i - 1] = _site_id(i - 1, port)
        if port == UNRESOLVED_PORT:
            kind, info = "unresolved", None
            if stats is not None:
                stats["cats"]["unresolved"] = \
                    stats["cats"].get("unresolved", 0) + 1
        else:
            kind, info = _reg_category(port)
            if stats is not None:
                stats["cats"][kind] = stats["cats"].get(kind, 0) + 1
            if kind == "channel":
                continue                # the channel rules own these
            if port in ctx.declared or port in ctx.covered:
                continue                # declared, or covered as a port
            if kind in ("latch", "data") and ctx.satisfies_resource(*info):
                continue                # the resource claim covers it
        candidates.append((i, port, kind, info, mi.group("rest") or ""))

    # PASS 2 — apply overrides, port-scoped.
    would_fire = {i - 1: _site_id(i - 1, port)
                  for i, port, _k, _inf, _r in candidates}
    for i, port, kind, info, rest in candidates:
        idx = i - 1
        site = _site_id(idx, port)
        radius = {s for k, s in would_fire.items() if abs(k - idx) <= 3}
        ok, note = _reg_override_for(lines, idx, port, site, radius,
                                     line_sites)
        if note and note[0] == "bare":
            findings.append(Finding(
                path, note[1], "reg",
                "bare `; REG-LINT: ok` — the override must state WHY the "
                "site is safe by construction (`; REG-LINT: ok — reason`)"))
            continue
        if ok:
            continue
        if note and note[0] == "ambiguous":
            findings.append(Finding(path, i, "reg", _ambiguous_verdict(
                port, rest.strip(), radius, note[1])))
            continue
        msg = (_unresolved_verdict(rest.strip(), ctx) if kind == "unresolved"
               else _reg_verdict(path, port, kind, info, ctx, port_names))
        if msg:
            # Appended to the finding rather than filed as its own, so
            # the note travels with the refusal it explains and the finding
            # COUNT is unchanged — a malformed override is not a second
            # violation, it is a failed attempt to excuse this one.
            findings.append(Finding(path, i, "reg",
                                    msg + _malformed_override_note(lines, idx)))
    return findings


# --- item 5: the declaration-that-lies check --------------------------------
#
# `scene_writes` is a permission, and like `seed` it is a declaration that can
# LIE. `seed`'s validator (allocate.py) refuses a seed with nothing to override
# it; this is the same discipline for the same reason, in both directions:
#
#   1. a `scene_writes` register the owner ALSO writes, without saying so in
#      `scene_writes_shared` — the declaration reads "enter-time code writes
#      this, I do not", and the owner's own ASM contradicts it;
#   2. a `scene_writes_shared` register the owner does NOT write — the
#      declaration claims a co-write that is not there.
#
# PLACEMENT, and it is deliberate rather than an oversight: this check needs
# the ASM, so it lives here and not in allocate.py beside `seed`'s validator.
# It runs at the FEATURE-STRICT tier over `path.parent.glob("*.asm")` — the
# scanned file's own directory, derived entirely from the scanned path, which
# is what `_feature_reg_context` (feature.toml) and `_feature_port_owners`
# (every sibling's feature.toml) already do. Reading a file the scan was not
# handed is established here; the only new thing is that it is a `.asm`.
#
# WHAT IT DOES NOT DO — and the obvious specification of it is measurably
# wrong. That specification asks for "require the owner's ASM in
# the invocation's file list and FAIL LOUD when absent". Measured: 5 of the 11
# claim owners have no `.asm` at all (`backdrop` among them) and 4 of the 5
# live invocations pass a single file, so absence is the NORMAL case and a
# fail-loud rule would refuse four of five invocations. The intent behind it —
# never a silently disarmed pass — is real, and is discharged two other ways:
# the summary line reports how many claims this invocation VALIDATED, so a
# zero reads as disarmed rather than clean; and the in-tree guard plants a
# co-write and requires it to fire in that exact invocation, which is the only
# proof of arming a count cannot fake.
#
# Granularity is per REGISTER, span-expanded — NOT per claim. Per claim
# false-positives on the live tree: `room_layers` opens BGMODE/TM while
# `room_bg.asm` writes BG1SC/BG2SC/BG12NBA/BG1HOFS/BG1VOFS/BG2HOFS/BG2VOFS,
# which are DISJOINT sets, and a whole-claim comparison calls that a lie
# (measured: claim-granular baseline 2, register-granular 1). Span expansion
# is what keeps it honest the other way: a claim opening `ALU` against an
# owner that writes only `$4204` must still fire, and no footprint name sits
# at $4204.

def _owner_write_ports(d: Path) -> dict[int, list[str]]:
    """Every RESOLVABLE io port written by any `.asm` in feature directory `d`.

    Deliberately NOT filtered by category. Keeping in-class ports only makes
    both rules structurally blind to a whole register class:
    `written` could never hold a data port, so for a data/latch register rule 2
    always answered "no `.asm` here writes it" — a REFUSAL, breaking the build,
    whose diagnostic asserted something the file three lines away contradicted
    and whose advice was to delete a TRUE declaration. Rule 1 was blind the
    same way in the other direction. Four data ports are namable on a claim
    (OAMDATA $2104, VMDATAL/H $2118/$2119, CGDATA $2122), so the shape was
    declarable and latent rather than impossible. `rgfx_lies_data` and
    `rgfx_lies_data_shared` are the pair; the filter is what makes them fail.
    Sharper still, the summary's arming count reported such a claim as
    `validated` — the disclosure G2 introduced certifying the one case it
    exists to expose — which no fix to the count itself could have addressed,
    because the count was right that the claim had been examined and wrong
    only because the examination could not see the register class.

    The category filter was never load-bearing anyway: both rules intersect
    against `_ports_of_names`, so a port no footprint name reaches (every
    channel port, every unnamed port) can never appear in a `hits` set no
    matter what this returns.

    KNOWN LIMIT, unchanged by the fix: a co-write whose operand does not fold
    to a port (`_store_port` -> UNRESOLVED_PORT) is invisible here, so rule 2
    could still call it absent. The write-site pass refuses an unresolved io
    write in its own right (`_unresolved_verdict`), and the live tree carries
    `0 unresolved`, so the shape cannot reach a green build today.

    Overrides are deliberately NOT honoured here: `; REG-LINT: ok` excuses a
    write from the OWNERSHIP rule, and this is a different question — whether
    the declaration describes the code. A co-write is a co-write.
    """
    out: dict[int, list[str]] = {}
    for asm in sorted(d.glob("*.asm")):
        try:
            lines = asm.read_text().splitlines()
        except OSError:
            continue
        aliases = _port_aliases(lines)
        for i, raw in enumerate(lines, start=1):
            line = _strip(raw)
            if not line.strip() or DIRECTIVE_RE.match(line):
                continue
            if ASSIGN_RE.match(line) and not LABEL_RE.match(line):
                continue
            mi = MNEMONIC_RE.match(LABEL_RE.sub("", line))
            if not mi or mi.group("mn").lower() not in REG_WRITE_MN:
                continue
            port = _store_port(mi.group("rest") or "", aliases)
            if port is None or port == UNRESOLVED_PORT:
                continue
            out.setdefault(port, []).append(f"{asm.name}:{i}")
    return out


def scan_reg_declaration_lies(path: Path, stats: dict | None = None) \
        -> list[Finding]:
    """Is this feature's `scene_writes` declaration true of its own ASM?

    Feature files only — the other tiers have no single owner to ask. The test
    for "a feature file" is that the scanned file's own directory holds a
    `feature.toml`, which is the same question `_feature_reg_context` asks and
    is what the docstring always claimed. It used to ALSO require the path
    shape `engine/features/<name>/<file>.asm`, which is a stricter thing than
    it reads as: `engine/toy/feat_a/` is a real feature directory carrying
    two `scene_writes` declarations and was silently out of scope —
    invisible except as a smaller number in the summary's count. The
    vendored probes stay out of scope either way, and correctly: their `.asm`
    sits a level ABOVE the feature dir, so those writes are the boot writes the
    permission grants rather than owner co-writes, and no `feature.toml` is
    beside them to ask.

    Runs once per DIRECTORY (on the alphabetically-first `.asm`) so a feature
    that grows a second file reports once rather than twice. The directory glob
    rather than the scanned file alone is what keeps rule 2 correct that day:
    a co-write in the sibling file is still a co-write.
    """
    import schemas
    d = path.parent
    toml = d / "feature.toml"
    if not toml.exists():
        return []              # not a feature dir; and where one is EXPECTED
    asms = sorted(d.glob("*.asm"))          # the write-site pass files that
    if not asms or asms[0].name != path.name:
        return []                          # a sibling already ran the check
    try:
        decl = schemas.load_feature(toml, _substrate())
    except (schemas.SchemaError, _tomllib().TOMLDecodeError,
            AttributeError, TypeError):
        return []                          # ditto — one finding, not two
    fp = schemas.REGISTER_FOOTPRINT
    written = _owner_write_ports(d)
    findings: list[Finding] = []
    for c in decl.reg:
        if not c.scene_writes and not c.scene_writes_shared:
            continue
        if stats is not None:
            stats["lies_validated"] = stats.get("lies_validated", 0) + 1
        shared = set(c.scene_writes_shared)
        for r in c.scene_writes:
            hits = sorted(_ports_of_names((r,), fp) & set(written))
            if not hits or r in shared:
                continue
            where = ", ".join(s for p in hits for s in written[p])
            findings.append(Finding(
                path, 1, "reg",
                f"declaration that lies: [[claims.reg]] '{c.name}' of feature "
                f"'{decl.name}' opens {r} to scene-enter or boot code via "
                f"`scene_writes`, but {decl.name}'s own ASM writes it too, at "
                f"{where}. `scene_writes` says who ELSE may write the "
                f"register; it does not say the owner stays out. If the "
                f"co-write is deliberate — as it is for scene_mgr's NMITIMEN, "
                f"masked around the scene switch — declare it: add "
                f"`scene_writes_shared = [\"{r}\"]` to that claim in {toml}. "
                f"If it is not deliberate, one of the two writers is a bug. "
                f"A permission nobody checked against the code is worth as "
                f"much as an undeclared write"))
        for r in c.scene_writes_shared:
            if _ports_of_names((r,), fp) & set(written):
                continue
            findings.append(Finding(
                path, 1, "reg",
                f"declaration that lies: [[claims.reg]] '{c.name}' of feature "
                f"'{decl.name}' declares {r} in `scene_writes_shared` — "
                f"\"scene-enter code writes this and so do I\" — but no "
                f"`.asm` in {d} writes it. The same lie in the other "
                f"direction: it silently widens the gate, because the "
                f"co-write it excuses does not exist. Either the write was "
                f"removed and this entry should go with it, or it lives in a "
                f"file outside this feature's directory, where it answers to "
                f"a different claim set. Drop {r} from `scene_writes_shared` "
                f"in {toml}"))
    return findings


# A `; REG-LINT:` comment that misses the strict grammar is INVISIBLE.
# Measured on a $2106 MOSAIC site, all three spellings: `; REG-LINT: ok $-001
# — …` -> exit 1 with no word about the override; `; REG-LINT: ok, mosaic is
# safe here` -> the same; `; REG-LINT: OK — legal reason` -> exit 0. So the
# failure mode is SAFE — the underlying finding still fires, and the cost is a
# lost DIAGNOSTIC, not a silence. That is the whole severity: the author typed
# an escape hatch, the tool ignored it, and the refusal said nothing about
# why. Naming it costs one loose pre-match.
#
# Reg form only. `; CHANNEL-LINT:` and `; WIDTH-LINT:` keep pure ±3-line radius
# semantics — an accepted divergence, documented in AGENTS.md.
REG_LOOSE_OVERRIDE_RE = re.compile(r";\s*REG-LINT:", re.I)


def _malformed_override_note(lines: list[str], idx: int) -> str:
    """A `; REG-LINT:` in radius that parses as neither override form."""
    for k in range(max(0, idx - 3), min(len(lines), idx + 4)):
        if not REG_LOOSE_OVERRIDE_RE.search(lines[k]):
            continue
        # The two forms that DO parse are handled elsewhere: the reasoned one
        # excuses (or names another port, or is ambiguous), and the bare one
        # gets its own finding. Neither is malformed.
        if REG_OVERRIDE_RE.search(lines[k]) or \
                REG_BARE_OVERRIDE_RE.search(lines[k]):
            continue
        return (f" — NOTE: the `; REG-LINT:` comment at line {k + 1} does not "
                f"parse as an override (`; REG-LINT: ok [$port] — <reason>`), "
                f"so it excuses nothing and this finding is not the one you "
                f"meant to suppress. The separator must be an em dash, `--`, "
                f"` - ` or `:`, the reason is required, and a port is written "
                f"as four hex digits (`$2105`). This is a lost diagnostic "
                f"rather than a silence — the finding above fired either way")
    return ""


def _ambiguous_verdict(port: int, operand: str, radius: set,
                       ov_line: int) -> str:
    """Override rule 3's refusal: a standalone override over two subjects.

    The ADVICE this prints has to be advice that can be TYPED.
    For a resolved port that is rule 1, `; REG-LINT: ok $2101 — <reason>`.
    For a write whose port will not fold there is no port to name, so rule 1
    is unreachable by construction and printing `$-001` sent the author to a
    spelling the grammar rejects in silence. The reachable escape hatch there
    is rule 2 — the comment on the write's own line — plus the fix that is
    actually wanted, which is to make the operand foldable. That branch also
    carries `_unresolved_verdict`'s teaching text, which the ambiguity return
    used to swallow.
    """
    head = (f"undeclared CPU write to ${port:04X}" if port != UNRESOLVED_PORT
            else f"`{operand}` reaches the io window but its effective port "
                 f"cannot be folded from this file")
    fix = (f"Name the port (`; REG-LINT: ok ${port:04X} — <reason>`), or put "
           f"the comment on the line of the write it excuses"
           if port != UNRESOLVED_PORT else
           "An unfoldable operand has no port to NAME, so no override can be "
           "scoped to it by port: put `; REG-LINT: ok — <reason>` on THIS "
           "line, where it binds to this write alone — or write the port "
           "directly, or through an equate that resolves to it (`sta a:$2100 "
           "+ 5` is BGMODE, not INIDISP)")
    return (f"{head}, and the `; REG-LINT: ok` at line {ov_line} is AMBIGUOUS "
            f"here — it stands alone and its ±3-line window holds writes to "
            f"{_window_desc(radius)}, so which one it excuses cannot be told "
            f"from the text. {fix}. A reviewer reading one stated reason must "
            f"not have a second, unrelated write riding on it")


def _unresolved_verdict(operand: str, ctx: "RegContext") -> str:
    """The write reaches io, but which port is not knowable here."""
    return (f"`{operand}` reaches the io window, but its effective port "
            f"cannot be folded from this file — the operand adds a term that "
            f"is not a constant, so no ownership check for {ctx.label} is "
            f"possible and the port would otherwise be taken to be the base "
            f"(`sta a:$2100 + 5` is BGMODE, not INIDISP). Write the port "
            f"directly, or through an equate that resolves to it, or suppress "
            f"with `; REG-LINT: ok — <reason>` if the site is safe by "
            f"construction")


def _reg_verdict(path: Path, port: int, kind: str, info,
                 ctx: "RegContext", port_names: dict) -> str | None:
    """The teaching diagnostic for an undeclared write.

    Category-specific and tier-aware: a refusal has to say what claim would
    satisfy it, in the vocabulary of the tier the file answers to. It also
    keeps the LANDED gate's owner survey — the convergence (§1.12) found the
    two sides' diagnostics complementary rather than competing, and named the
    survey "the single highest-value port in either direction"; it is the only
    thing that turns "declared by nobody" into the name of the feature you are
    about to have a silent fight with.
    """
    # A latch/data refusal surveys for the RESOURCE too, not just the port
    # name — a claim shape the RULE treats as sufficient is a claim shape
    # the survey has to be able to see.
    res_name = info if kind in ("latch", "data") else (None, None)
    owners = (_feature_port_owners(path, port, *res_name)
              if ctx.label.startswith("feature ") else [])
    who = (f"declared elsewhere by {', '.join(owners)} — a second writer is "
           f"the silent fight claims.reg exists to refuse"
           if owners else "declared by nobody")
    if kind in ("latch", "data"):
        import schemas
        resource, name = info
        what = ("data port" if kind == "data" else
                f"address/increment latch of the {resource} data port")
        # Only offer names a claim can actually CARRY. `_parse_registers`
        # refuses anything outside REGISTER_FOOTPRINT, and WMDATA/WMADD* /
        # VMAIN / VMADD* / CGADD / OAMADD* are all absent from it (docs/09
        # §2.1's "C4 needed none of them as names"). Listing an unclaimable
        # name would be advice the build then rejects, which is the worst
        # shape a diagnostic can take: it costs a reader a build to find out.
        claimable = sorted(n for n in
                           set(RESOURCE_PORT_NAMES.get(resource, ())) | {name}
                           if n in schemas.REGISTER_FOOTPRINT)
        fix = (f"claim the `{resource}` region, or name "
               f"{' / '.join(claimable)} on the claim that drives it"
               if claimable else
               f"claim the `{resource}` region — ${port:04X} carries no "
               f"REGISTER_FOOTPRINT name, so no [[claims.reg]] can name it "
               f"and the region claim is the only thing that covers it")
        held = (f"claims neither a `{resource}` region nor any of "
                f"{', '.join(claimable)} on an hdma/dma_init/reg claim"
                if claimable else f"holds no `{resource}` claim")
        # The hint names the FILE the declaration belongs in; when no
        # [[claims.reg]] can name this port, the class in it has to change
        # too, or the refusal points at a fix the schema then rejects.
        hint = (ctx.hint if claimable else
                ctx.hint.replace("[[claims.reg]]", f"[[claims.{resource}]]"))
        return (f"undeclared CPU write to ${port:04X} ({name}) — it is the "
                f"{what}, and {ctx.label} {held}; {who}. A port write rides "
                f"the claim on the RESOURCE it serves: {fix}. {hint} "
                f"(docs/09 §2.1)")
    if kind == "unnamed":
        # The confirmed default: "silence is how the next census grows".
        # Exempting these does the OPPOSITE by construction: a port with no
        # footprint name is `continue`d as "unnamed port: unclaimable,
        # exempt", which is the census-of- undeclared-writers disease C4
        # abolished, re-entering through the one door the gate left open.
        #
        # Landed only AFTER the latch category: without it this fired on all
        # 48 latch sites at once. Surveyed before landing — tools/reg_census.py
        # reports ZERO unnamed sites in the live population, so the cost to the
        # tree is zero declarations and zero overrides.
        #
        # Note the settlement's own worked example ($4016/$4017, serial
        # joypad) can never reach this branch: it is outside `io_allowed`, so
        # the ADDRESS rule refuses it first. 568 unnamed ports do live inside
        # the window — $4201 WRIO, the $4207-$420A timers, the $213x/$421x
        # read ports.
        return (f"CPU write to ${port:04X}, which has no REGISTER_FOOTPRINT "
                f"name — so no claim can describe it and this write is "
                f"invisible to every ownership check, including this one. "
                f"{ctx.label} cannot declare it as things stand. Add the name "
                f"to `REGISTER_FOOTPRINT` first, then declare it — or "
                f"suppress with `; REG-LINT: ok — <reason>` if the port is "
                f"deliberately unowned (e.g. $4201 WRIO, or the $4207-$420A "
                f"timer ports, which no claim class describes yet) "
                "")
    names = "/".join(sorted(port_names[port]))
    if port in ctx.owned:
        # the narrowed refusal: the port IS owned by this closure, and the owner
        # did not open it. This is the one case where the gate knows exactly
        # who to name and exactly what to type, so it says both — "declared by
        # nobody" would be false here, and a diagnostic that made the author
        # hunt for the owner is how a real gate gets worked around.
        # THE ADVICE MUST NAME AN EDIT THE BUILD WOULD ACCEPT — the same bar
        # the latch/data branch above holds itself to. The class stays open
        # on two further axes if only the holder-type one is fixed; all
        # three are answered from the same place, the (who, NAME, KIND)
        # triples `owned` carries:
        #
        #   holder type — a port owned ONLY through a transfer claim cannot be
        #     fixed by adding `scene_writes` to that claim: `_table` refuses
        #     the key on hdma/dma_init.
        #   NAME — `sorted(port_names[port])[0]` is the alphabetically-first
        #     COVERING name, which is not always a name the owning claim
        #     HOLDS. For a claim holding COLDATA_R the old text advised
        #     `scene_writes = ["COLDATA"]` and `_reject_not_subset` then
        #     refused precisely that edit — with the advice's own parenthetical
        #     ("a subset of its own `registers`") asserting the property it
        #     violated. So the name printed comes from the holders themselves.
        #   KIND — `seed` exempts an hdma overrider and does NOT exempt a
        #     dma_init (check_reg_ownership: "a one-shot enter-time
        #     ESTABLISHER, not an ongoing overrider"). Advising a seed'd reg
        #     claim against a dma_init-covered port is advice the build
        #     refuses, so that case gets the fix that actually exists.
        held = sorted(ctx.owned[port])
        holders = sorted({who for who, _n, _k in held})
        reg_names = sorted({n for who, n, k in held if k == "reg"})
        xfer_names = sorted({n for who, n, k in held if k != "reg"})
        seedable = reg_names or not any(k == "dma_init" for _w, _n, k in held)
        # A name the OWNING claim holds; the covering-name fallback is only
        # reachable if `owned` were ever populated without one.
        reg_name = (reg_names or xfer_names or sorted(port_names[port]))[0]
        if reg_names:
            fix = (f"add `scene_writes = [\"{reg_name}\"]` to that "
                   f"[[claims.reg]] (a subset of its own `registers`), or "
                   f"move the write into the owning feature")
        elif seedable:
            fix = (f"give the owning feature a [[claims.reg]] naming "
                   f"{reg_name}, with `scene_writes = [\"{reg_name}\"]` AND "
                   f"`seed = true` — a transfer claim already drives this "
                   f"port, so a reg claim on it is refused without `seed`, "
                   f"which is the declaration that this CPU write establishes "
                   f"a base value the transfer overrides. Do NOT add "
                   f"`scene_writes` to the transfer claim itself; it does not "
                   f"take the key. `vb2reg_coldata` in "
                   f"vendor/probes/probe_vb2reg/vb_b/feature.toml is the "
                   f"worked example. Or move the write into the owning "
                   f"feature")
        else:
            fix = (f"move the write into the owning feature. A claims.dma_init "
                   f"drives {reg_name} here, and `seed` does NOT exempt one — "
                   f"it is a one-shot enter-time ESTABLISHER, not an ongoing "
                   f"overrider, so a [[claims.reg]] on this register is "
                   f"refused by check_reg_ownership WITH or without `seed`, "
                   f"and there is no declaration that makes an enter-time CPU "
                   f"write and an enter-time transfer of one register compose. "
                   f"The alternative is on the transfer's side: drop "
                   f"{reg_name} from the dma_init claim if the transfer does "
                   f"not really drive it. Do NOT add `scene_writes` to the "
                   f"transfer claim itself; it does not take the key")
        # The co-write escape is only reachable where a [[claims.reg]] can
        # exist at all: `scene_writes_shared` is a subset of `scene_writes`,
        # which is a subset of a reg claim's `registers`. In the dma_init case
        # above there is no such claim to put it on, so offering it would be
        # the same class of dead advice one sentence later.
        shared_tail = ("" if not (reg_names or seedable) else
                       f" If the owner also writes {reg_name} itself, say so "
                       f"with `scene_writes_shared`.")
        return (f"undeclared CPU write to ${port:04X} ({names}) — {ctx.label} "
                f"OWNS this port, via {' and '.join(holders)}, "
                f"but the owner has not opened it to scene-enter or boot code. "
                f"Ownership is not permission: a claim declares who the port "
                f"belongs to, and `scene_writes` declares that its owner "
                f"expects enter-time or boot code to write it too. Without "
                f"that, this write is a second writer the owner never "
                f"consented to. Fix: {fix}.{shared_tail} "
                f"(docs/09 §2.1 hole 2)")
    # The span-alias case has to explain itself or it reads as a
    # typo. `$4203` is WRMPYB and `$2141` is APUI01 — neither is the port its
    # covering NAME sits at, because ALU and APUIO each own a BLOCK under one
    # name (schemas.REGISTER_SPANS). Without this clause the refusal says
    # "$2141 (APUIO)" and the author's first thought is that the tool is
    # confused (convergence §1.12).
    import schemas
    alias = ""
    if all(schemas.REGISTER_FOOTPRINT[n][0] != port for n in port_names[port]):
        alias = (f", which is inside `{sorted(port_names[port])[0]}`'s span "
                 f"(one resource, one name, several ports)")
    return (f"undeclared CPU write to ${port:04X} ({names}){alias} — "
            f"{ctx.label} holds no [[claims.reg]] naming it and no claim "
            f"covers it; {who}. {ctx.hint} (docs/09 §2.1)")


# --- rom backing: does every `rom` claim have bytes? (docs/37) --------------
#
# The asymmetry this closes. A `rom` claim reserves bytes; it does not put any
# there. The allocator packs it and emits ES_R_<NAME>_{BANK,ADDR,OFF,SIZE};
# the claim site in ASM ties its `.incbin` to those symbols with
# `.assert ^label = ES_R_<NAME>_BANK`, so the claim DRIFTING away from its data
# is refused at assembly time. Nothing anywhere asked the other question —
# does the claim have any data at all — so an `.incbin` that was never written
# left the claim's window holding whatever the linker put there, silently.
#
# Observed, not hypothesised: rgb_gradient's `grad_tabs` during a later
# breaker port (2026-08-02). The asset tool generated it, the Makefile
# prerequisited it, the allocator packed it, and no `.asm` file included it.
# Three HDMA channels streamed the neighbouring blob's bytes as COLDATA. The
# only symptom was a missing backdrop wash, and `make register`, `no_literals`,
# `width-check`, the allocator's own packing and the full pytest suite were all
# green.
#
# THE RULE. A rom placement is BACKED when either
#
#   (a) one of the scanned files holds an `.incbin` whose DECLARATION BLOCK
#       references one of that placement's emitted symbols — literally
# (`ES_R_FONT_BIN_BANK`) or through a ca65 `.sprintf` template that
#       expands to it (`ES_R_WORLD_MAP_T%d_BANK`); or
#
#   (b) its `[[claims.rom]]` declares `backed_by = "<where the bytes are>"`,
#       naming a compilation unit outside the no_literals scope.
#
# and is otherwise a build refusal that NAMES the claim, its feature, its size
# and the symbols it emitted.
#
# THE DECLARATION BLOCK is deliberately narrow: from the nearest preceding
# label definition through the directives that follow, stopping at the next
# label, `.segment`, or `.incbin`. That is exactly the shape every claim site
# in this tree already has, and the narrowness is the teeth: a wide window
# would let the asserts of a NEIGHBOURING blob credit a claim whose own
# `.incbin` is the missing one, which is the failure this gate exists to catch.
# The cost is that a claim-site shape whose asserts are SEPARATED FROM the
# `.incbin` BY ANOTHER LABEL is refused rather than accepted — loudly, with a
# message naming the required shape. That direction of error is the correct one
# for a gate.
#
# Asserts placed BEFORE the `.incbin` are ACCEPTED, and deliberately so: the
# block is bounded by the label, and everything between that label and the next
# boundary is the same claim site whichever side of the `.incbin` it sits on.
# (This paragraph used to claim they were refused — measured, they are not.
# The rule was right; the sentence was not.)
#
# WHY PER-GAME, not tree-wide. The check runs inside no_literals, whose `--map`
# is exactly the composition being built. A claim in a feature no game composes
# has no placement, reserves no bytes and can back nothing — there is nothing
# to check and nothing at risk. Tree-wide would have to invent a composition to
# check against, and would report on features that are not in any ROM.
#
# KNOWN LIMITS, stated rather than papered over (docs/37 §5):
#
# 1. CLOSED. `.repeat` counts are still not evaluated, but a
#      hand-written count is no longer accepted: the allocator emits
#      `ES_R_<NAME>_CHUNKS` and a narrated count wrapping a templated claim
#      site is refused (`NARRATED CHUNK COUNT`, scan_chunk_count_narration).
#      This block used to claim the residue was caught by "the linker's segment
#      sizes and the per-chunk `.assert`". IT IS NOT, and that was MEASURED:
#      `.repeat 8` -> `.repeat 7` on microzero's world_map left this gate green,
#      ca65 exit 0, ld65 exit 0, ROM still 524,288 B, and 18,478 bytes of map
#      silently became $FF fill. Unused ca65 equates have no diagnostic and the
#      BANK segments are `optional = yes`. A stated-and-wrong backstop is worse
#      than a stated hole — it retires the question.
#
#   2. THE BYTES ARE NOT INSPECTED. This proves an `.incbin` exists and is tied
#      to the claim; it does not prove the file it names holds the right bytes,
#      is non-empty, or is the size the claim declared. ca65 would need to
#      export the included size for that. STILL OPEN.
#
# 3. CLOSED. `.include`s are still not expanded, but membership
#      is no longer "any scanned file": a claim site credits a claim only
#      within the `.include` closure of the translation unit's root, so a site
#      in a file this composition never assembles cannot back its claim.
#      Verified against `ca65 --create-full-dep` ground truth — the closure
#      matches the assembler's real set exactly on all three games (microzero
#      19/19, room 15/15, breaker 11/11).
#
# 4. CONDITIONAL CLAIM SITES DO NOT CREDIT. A site inside
#      `.if`/`.ifdef`/`.ifndef`/`.ifblank`/`.ifconst` is skipped, so its claim
#      reads UNBACKED — loudly, never silently. Deliberately over-strict: even
#      `.if 1` skips. Zero live exposure (`in_conditional` is 0 on all three
#      games). `.repeat` is excluded from this because derived counts are the
#      blessed shape.
#
# 5. CLOSED. A `%s` blanket in an `ES_R_*` template is refused
#      (`BLANKET ROM TEMPLATE`) rather than matching every claim by accident.
#
# THESE FIVE ARE THE SAME LIST AS docs/37 §5, WHICH POINTS HERE. The comment
# and the doc have drifted apart twice, and on the second occasion this block
# was still byte-identical to the original gate commit AFTER the doc was
# corrected — i.e. the accurate doc was routing readers to the stale copy.
# If you change a limit, change both.

# A reference to an emitted ROM symbol. `%`-format specs are allowed inside the
# name so `.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)` is one token.
ROM_SYM_REF_RE = re.compile(r"ES_R_(?:[A-Za-z0-9_]|%[-+ #0-9.]*[diouxXs])+")
ROM_SYM_SUFFIXES = ("_BANK", "_ADDR", "_OFF", "_SIZE")
# `.incbin`, with or without a label on the SAME line. The bare form
# (`^\s*\.incbin`) missed `font_bin: .incbin "x.bin"` entirely — no block, no
# refs, the claim reported unbacked while its claim site sat right there, and
# the refusal told the author to add the label + `.incbin` + `.assert` they
# already had. Not hypothetical: the vendored TAD generator emits exactly that
# shape at assets/audio/export/tad_audio_data.asm:119.
INCBIN_RE = re.compile(r"^\s*(?:[^\s;].*?:\s*)?\.incbin\b", re.I)
# ...and when the label IS on the `.incbin` line, the declaration block STARTS
# there: walking backwards from it would swallow the PRECEDING blob's asserts,
# which is the wide-window weakening the block's narrowness exists to prevent.
LABELLED_INCBIN_RE = re.compile(r"^\s*[^\s;].*?:\s*\.incbin\b", re.I)
LABEL_DEF_RE = re.compile(r"^\s*[^\s;].*:\s*$")
SEGMENT_RE = re.compile(r"^\s*\.(?:segment|code|rodata|bss|data|zeropage)\b", re.I)
_FMT_SPEC_RE = re.compile(r"%[-+ #0-9.]*([diouxXs])")


def _rom_ref_matcher(ref: str):
    """A predicate matching emitted ROM symbols against one source reference.

    A literal reference is an exact (case-insensitive) name. A `.sprintf`
    template becomes a regex — `%d`/`%x`/`%u` are the chunk index, `%s` a name
    fragment — which is how a `.repeat`-generated claim site, whose chunk
    symbols never appear as text anywhere, gets credited at all.
    """
    if "%" not in ref:
        want = ref.upper()
        return lambda sym: sym == want
    # Split on the ORIGINAL, upper-case the literal parts only. `.upper()`
    # first turns `%d` into `%D`, which the conversion-spec pattern no longer
    # matches — every templated claim site then compiles to a literal regex
    # that matches nothing, and the 12 chunk placements in this tree read as
    # unbacked while their `.repeat` claim sites sit right there.
    pat = "".join(
        (r"\d+" if part in "diouxX" else r"\w+") if i % 2
        else re.escape(part.upper())
        for i, part in enumerate(_FMT_SPEC_RE.split(ref)))
    rx = re.compile(rf"^{pat}$")
    return lambda sym: bool(rx.match(sym))


def _rom_backing_refs(lines: list[str]) -> tuple[list, int]:
    """Matchers for every emitted ROM symbol referenced from an `.incbin`'s
    declaration block. See the DECLARATION BLOCK paragraph above for the
    block's extent and for why it is this narrow.

    Comments are stripped, STRINGS ARE NOT — unlike every other pass here,
    which uses `_strip`. The templated claim sites live INSIDE strings
    (`.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)`), so `_strip` would delete the
    only text that names the 12 chunk placements microzero and probe_colmap
    between them declare, and the gate would refuse a fully-backed tree.
    """
    stripped = [COMMENT_RE.sub("", raw) for raw in lines]
    out, skipped = [], 0
    cond = 0                     # unevaluated `.if`/`.ifdef` nesting depth
    for i, line in enumerate(stripped):
        if COND_OPEN_RE.match(line):
            cond += 1
        elif COND_CLOSE_RE.match(line):
            cond = max(0, cond - 1)
        if not INCBIN_RE.match(line):
            continue
        if cond:
            # KNOWN LIMIT 4: a textual scan cannot evaluate
            # `.if`/`.ifdef`, and `.if 0` around the `.incbin` with the asserts
            # left outside is exactly the shape docs/37 §1 calls the nasty one
            # — ca65 accepts it and the drift asserts still pass. So a claim
            # site inside a conditional does NOT credit. The claim then reads
            # UNBACKED, which is loud and fixable (make it unconditional, or
            # declare `backed_by`), instead of credited-but-empty, which is
            # the bug.
            skipped += 1
            continue
        lo = i
        while lo > 0 and not LABELLED_INCBIN_RE.match(line):
            prev = stripped[lo - 1]         # back to the claim site's label
            if INCBIN_RE.match(prev) or SEGMENT_RE.match(prev):
                break
            lo -= 1
            if LABEL_DEF_RE.match(prev):
                break
        hi = i + 1
        while hi < len(stripped):           # forward over the .asserts
            nxt = stripped[hi]
            if (INCBIN_RE.match(nxt) or SEGMENT_RE.match(nxt)
                    or LABEL_DEF_RE.match(nxt)):
                break
            hi += 1
        for ref in ROM_SYM_REF_RE.findall("\n".join(stripped[lo:hi])):
            out.append(_rom_ref_matcher(ref))
            for suf in ROM_SYM_SUFFIXES:    # the BASE the suffix hangs off
                if ref.upper().endswith(suf):
                    out.append(_rom_ref_matcher(ref[:-len(suf)]))
                    break
    return out, skipped


# Conditional assembly. `.repeat` is deliberately NOT here: a `.repeat` with a
# derived count is the blessed claim-site shape, and a narrated one is already
# refused by scan_chunk_count_narration.
COND_OPEN_RE = re.compile(r"^\s*\.if(?:def|ndef|blank|nblank|const|p\d*|"
                          r"ref|nref)?\b", re.I)
COND_CLOSE_RE = re.compile(r"^\s*\.endif\b", re.I)

REPEAT_RE = re.compile(r"^\s*\.repeat\s+([^,]+?)\s*(?:,|$)", re.I)
ENDREPEAT_RE = re.compile(r"^\s*\.endrepeat\b", re.I)
_TEMPLATED_CHUNK_RE = re.compile(r"(ES_R_[A-Za-z0-9_]*?)_T%[-+ #0-9.]*[diouxX]")


BLANKET_TEMPLATE_RE = re.compile(r"ES_R_[A-Za-z0-9_]*%[-+ #0-9.]*s")


def scan_blanket_rom_template(path: Path, lines: list[str]) -> list[Finding]:
    r"""Refuse a claim-site template whose `%s` credits a whole CLASS of claims.

    Template expansion exists for one reason: a `bank_tiled`
    claim's chunk symbols appear nowhere as text, only inside
    `.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)`. `%d` is a chunk INDEX and
    compiles to `\d+`. `%s` is a name FRAGMENT and compiles to `\w+`, so
    `.sprintf("ES_R_%s_BANK", NAME)` compiles to `^ES_R_\w+_BANK$` — which
    matches every rom symbol in the composition. One such claim site anywhere
    in the translation unit silently disables the presence check for the whole
    ROM, and the census would still read `N via an .incbin claim site`,
    indistinguishable from clean.

    HOW WIDE depends on the rest of the pattern, and the refusal deliberately
    does not try to bound it per-form. `ES_R_%s_BANK` credits every rom claim;
    `ES_R_%s_T%d_BANK` compiles to `^ES_R_\w+_T\d+_BANK$` and credits every
    BANK_TILED claim's chunks — narrower, still a class rather than the one
    claim the site is supposed to back, and still invisible in the census.
    (The mode7_stream retrofit's prose once described the second form with
    the first form's blast radius. The refusal itself was never in question:
    it is textual on `%s` and fires for both.)

    Nothing in this tree uses `%s` (all 8 templates are `%d`), and a name
    fragment is not a chunk index, so the honest close is to refuse it rather
    than to try to bound its blast radius. Per-FILE and unconditional: a
    template is text in one file.
    """
    findings = []
    for i, raw in enumerate(lines, start=1):
        for hit in BLANKET_TEMPLATE_RE.findall(COMMENT_RE.sub("", raw)):
            findings.append(Finding(
                path, i, "rom-template",
                f"BLANKET ROM TEMPLATE: `{hit}` uses a `%s` conversion. "
                f"Template expansion exists for chunk INDICES (`%d` -> "
                f"`\\d+`); `%s` is a name fragment and expands to `\\w+`, so "
                f"this reference stops naming ONE claim and credits every rom "
                f"symbol matching the rest of the pattern — `ES_R_%s_BANK` "
                f"credits every rom claim in the composition, "
                f"`ES_R_%s_T%d_BANK` credits every bank_tiled claim's chunks. "
                f"Either way the presence check stops distinguishing the "
                f"claim you meant, without changing a single number in the "
                f"census (docs/37 §5 limit 5). Name the claim, "
                f"or index its chunks with `%d`."))
    return findings


def scan_chunk_count_narration(path: Path, lines: list[str]) -> list[Finding]:
    """Refuse a `.repeat <literal>` whose body names chunk symbols by template.

    THE CLOSE FOR docs/37 KNOWN LIMIT 1. A textual scan cannot evaluate ca65
    arithmetic, so a claim site that under-covers its own chunk count reads as
    backing every chunk. The doc used to say the linker and the per-chunk
    `.assert`s caught that residue; measured, they do not.
    `.repeat 8` -> `.repeat 7` on microzero's world map left the backing gate,
    ca65 and ld65 all green, the ROM the same 524,288 bytes, and 18,478 bytes
    of world map replaced by `$FF` fill. An unused ca65 equate is not a
    diagnostic, and `lorom_512k.cfg` marks the BANK segments `optional = yes`,
    so a short segment is not a link error either.

    Rather than teach the scanner ca65 arithmetic, take the count out of the
    ASM: the allocator emits `ES_R_<NAME>_CHUNKS` and the claim site says
    `.repeat ES_R_WORLD_MAP_CHUNKS, WI`. Then the count is DERIVED, cannot
    disagree with the packing, and the residue does not exist. This pass is
    what makes that mandatory rather than merely available — a narrated count
    is a second copy of the allocator's arithmetic, which is the one thing
    this repo is built to not have.

    Per-FILE and unconditional (never skipped by `--partial-files`): unlike the
    backing question, "is this count narrated" is answerable from one file.
    """
    findings, depth, narrated = [], 0, []
    for i, raw in enumerate(lines, start=1):
        line = COMMENT_RE.sub("", raw)
        m = REPEAT_RE.match(line)
        if m:
            depth += 1
            count = m.group(1).strip()
            # a bare decimal/hex literal is a narration; anything else is an
            # expression over symbols, which is what this pass wants
            lit = re.fullmatch(r"\$?[0-9A-Fa-f]+|%[01]+", count) is not None
            narrated.append((i, count) if lit else None)
            continue
        if ENDREPEAT_RE.match(line):
            depth -= 1
            if narrated:
                narrated.pop()
            continue
        if not depth or not any(narrated):
            continue
        t = _TEMPLATED_CHUNK_RE.search(line)
        if not t:
            continue
        base = t.group(1).upper()
        inner = max(k for k, n in enumerate(narrated) if n)
        at, count = narrated[inner]
        findings.append(Finding(
            path, at, "chunk-count",
            f"NARRATED CHUNK COUNT: `.repeat {count}` wraps a claim site that "
            f"names {base}'s chunks by template (line {i}). The count is a "
            f"second copy of the allocator's packing arithmetic, and nothing "
            f"catches it drifting: a short `.repeat` leaves later chunks' "
            f"windows packed and unfilled while the backing gate, ca65 and "
            f"ld65 all stay green (docs/37 §5 limit 1). Use the "
            f"emitted count: `.repeat {base}_CHUNKS, ...`"))
        narrated[inner] = None    # one finding per `.repeat`, not per line
    return findings


def rom_placements(raw_map: dict) -> list[dict]:
    """Every `rom` placement in the composition, globals and scenes, once each.

    De-duplicated by symbol: a global blob is listed under `globals` only, but
    a claim shared by two scenes appears in each scene's placements with the
    same emitted symbol and the same single physical window.
    """
    seen, out = set(), []
    pools = [raw_map.get("globals", [])]
    pools += [sc.get("placements", []) for sc in raw_map.get("scenes", {}).values()]
    for pool in pools:
        for p in pool:
            if p.get("class") != "rom" or p["sym"] in seen:
                continue
            seen.add(p["sym"])
            out.append(p)
    return out


INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"', re.I)


def include_closure(root: Path, files: list[Path]) -> set[Path]:
    """The scanned files ca65 actually assembles into `root`'s translation unit.

    SCANNED IS NOT ASSEMBLED. Three hand-maintained lists decide
    membership and the gate used to read the loosest one:

      game.toml `globals` + `[[scene]].features`  -> the ALLOCATOR (what is packed)
      main.asm's `.include` closure               -> ca65 (what gets bytes)
      the Makefile's `$(wildcard engine/features/*/*.asm)` -> the GATE

    For microzero those differ by 9 files: the wildcard scans all 24 engine
    `.asm`, and 15 are ever `.include`d into it. A claim site placed in one of
    the other 9 credited the claim while contributing no bytes to the ROM —
    the grad_tabs bug, green, one file-move away, and reachable through
    the Makefile's own wildcard.

    Resolution is by BASENAME against the scanned list, because `.include
    "scene_mgr.asm"` is resolved by ca65 against a `-I` set this tool does not
    receive. Generous where it is uncertain (two scanned files with the same
    basename both count) and exact where it matters: a file no `.include`
    names is out, which is the case the gate was blind to.

    The direction of error is the safe one. If the root is wrong, the closure
    collapses and the claims read UNBACKED — a loud refusal, never a silent
    pass.
    """
    by_name: dict[str, list[Path]] = {}
    for p in files:
        by_name.setdefault(p.name, []).append(p)
    seen, frontier = {root}, [root]
    while frontier:
        for raw in frontier.pop().read_text().splitlines():
            m = INCLUDE_RE.match(COMMENT_RE.sub("", raw))
            if not m:
                continue
            for q in by_name.get(PurePosixPath(m.group(1)).name, []):
                if q not in seen:
                    seen.add(q)
                    frontier.append(q)
    return seen


def scan_rom_backing(files: list[Path], raw_map: dict, map_path: Path,
                     stats: dict | None = None,
                     root: Path | None = None) -> list[Finding]:
    """Refuse a `rom` claim that no `.incbin` puts bytes into. See above.

    Whole-INVOCATION, not per-file: the question is whether a claim is backed
    ANYWHERE in the composition, which no single file can answer. Findings are
    reported against the symbol map, since that is where the unbacked claim
    exists — the tree's fault is an absence, and an absence has no line number.

    Only files in `root`'s `.include` closure can credit a claim — see
    `include_closure`. `root` defaults to the FIRST file in the list, which is
    the translation-unit root in every invocation in this tree (the Makefile
    lists `main.asm` first, and the probe invocations pass one file).
    """
    placements = rom_placements(raw_map)
    if not placements:
        return []
    inside = include_closure(root or files[0], files)
    matchers, in_conditional = [], 0
    for p in files:
        if p in inside:
            ms, skipped = _rom_backing_refs(p.read_text().splitlines())
            matchers += ms
            in_conditional += skipped

    findings, backed, declared = [], 0, 0
    for pl in placements:
        sym = pl["sym"]
        if pl.get("backed_by", "").strip():
            declared += 1
            continue
        if any(m(sym) or any(m(sym + s) for s in ROM_SYM_SUFFIXES)
               for m in matchers):
            backed += 1
            continue
        who = pl.get("consumer", "?")
        scope = pl.get("scope", "global")
        syms = ", ".join(sym + s for s in ROM_SYM_SUFFIXES)
        findings.append(Finding(
            map_path, 0, "rom-backing",
            f"ROM CLAIM UNBACKED: '{sym}' ({who}, scope '{scope}', "
            f"{pl['size']} B) is packed into the ROM but NO .asm IN THIS "
            f"COMPOSITION'S TRANSLATION UNIT includes its bytes "
            f"({len(inside)} of {len(files)} scanned file(s) are reachable "
            f"from {(root or files[0]).name}'s .include closure; a claim site "
            f"in one of the other {len(files) - len(inside)} contributes no "
            f"bytes to this ROM). The allocator reserved the window and "
            f"emitted {syms}; whatever the linker leaves there is what the "
            f"claim will read. Add the claim site — a label, an `.incbin`, and "
            f"`.assert ^label = {sym}_BANK` — or, if the bytes come from a "
            f"compilation unit outside the no_literals scope, declare it: "
            f"`backed_by = \"<which unit supplies them>\"` on the "
            f"[[claims.rom]]"))
    if stats is not None:
        # the REACH numbers, in tools/gen_register.py's style: state the limit
        # AND print how far the check actually got. `scanned` vs `assembled`
        # is exactly that gap, so it is a number on the summary line
        # rather than a sentence in a doc.
        stats["rom"] = {"backed": backed, "declared": declared,
                        "unbacked": len(findings),
                        "scanned": len(files), "assembled": len(inside),
                        "in_conditional": in_conditional}
    return findings


def new_stats() -> dict:
    """The census the summary line reports. `tiers` counts FILES by the
    strength of the check they got; `cats` counts SITES by category."""
    return {"tiers": {}, "cats": {}}


def scan_file(path: Path, io, placements, raw_map: dict | None = None,
              stats: dict | None = None) -> list[Finding]:
    findings = []
    lines = path.read_text().splitlines()
    for i, raw in enumerate(lines, start=1):
        findings += scan_line(path, i, raw, io, placements)
    findings += scan_enables(path, lines)
    findings += scan_channel_encoding(path, lines)
    # per-FILE and unconditional — a narrated chunk count is visible in one
    # file, so unlike the backing question it is not skipped by
    # `--partial-files`. See the pass's docstring for why it exists at all.
    findings += scan_chunk_count_narration(path, lines)
    findings += scan_blanket_rom_template(path, lines)
    if raw_map is not None:
        findings += scan_reg_ownership(path, lines, reg_context(path, raw_map),
                                       stats)
        # item 5: independent of the write-site pass, and deliberately so —
        # it asks about the DECLARATION, not about any one write, so it must
        # not be gated on a context resolving or on a site firing.
        findings += scan_reg_declaration_lies(path, stats)
    return findings


def summarise(n_files: int, stats: dict) -> str:
    """The HONEST summary line.

    `no-literals OK: 26 file(s) clean` is true of the ADDRESS rule and says
    nothing about whether the reg pass examined anything. On
    `engine/toy/main.asm`, where an earlier form of this gate examined ZERO
    sites, "clean" was the only thing it printed (convergence §1.13). A gate that
    reports "clean" for a file it never checked is the toothless-gate failure
    mode `tests/test_make_gates.py` exists to warn about, wearing a green
    summary.

    So the line now carries (a) the TIER split, keeping the weaker check
    visible — a scene file is union-checked, which is docs/09 §2.1 hole 2,
    still open — and (b) the per-category site census, so "0 examined" is
    something you can READ rather than something you have to instrument for.
    """
    out = f"no-literals OK: {n_files} file(s) clean"
    tiers, cats = stats.get("tiers", {}), stats.get("cats", {})
    if tiers:
        out += " (" + ", ".join(f"{n} {t}" for t, n in sorted(tiers.items())) + ")"
    total = sum(cats.values())
    # Every category the gate can produce is listed, INCLUDING the zeroes:
    # "0 unnamed" says the unnamed rule ran and found none, which is a
    # different statement from the category being absent from the line.
    detail = ", ".join(f"{cats.get(k, 0)} {k}" for k in
                       ("channel", "data", "latch", "in-class", "unnamed",
                        "unresolved"))
    out += (f"; reg ownership: {total} io write-site(s) examined"
            + (f" ({detail})" if total else ""))
    # item 5: the lies-check's own arming disclosure. It is silent for an
    # owner with no `.asm`, which is CORRECT (nothing to lie about) but
    # indistinguishable from "the feature files were not in this invocation's
    # list" — and 4 of the 5 live invocations pass a single file. So the count
    # is printed unconditionally: a zero here reads as DISARMED rather than as
    # clean, which is the same discipline the tier split and the category
    # census already carry. Proof of arming, which no count can fake, is the
    # planted co-write in test_reg_gate.py's in-tree guard.
    out += (f"; scene_writes: {stats.get('lies_validated', 0)} "
            f"claim(s) validated against their owner's ASM")
    # The rom-backing census, printed on the same discipline as the two above:
    # a composition with no rom claims says "0 claim(s)", which reads as
    # NOTHING TO CHECK rather than as clean, and a composition with claims
    # shows how many were proven by a claim site vs. waved through by a
    # `backed_by` declaration — the exemptions stay counted, in the open.
    rom = stats.get("rom")
    if stats.get("rom_skipped"):
        out += ("; rom backing: SKIPPED (--partial-files: this file list is a "
                "subset of the composition, which cannot answer the question)")
    elif rom is None:
        out += "; rom backing: 0 claim(s) in this composition"
    else:
        out += (f"; rom backing: {rom['backed'] + rom['declared']} claim(s) "
                f"({rom['backed']} via an .incbin claim site, "
                f"{rom['declared']} via a declared backed_by; credited from "
                f"{rom['assembled']}/{rom['scanned']} scanned file(s) — the "
                f"rest are not in this composition's .include closure)")
        if rom.get("in_conditional"):
            out += (f" [{rom['in_conditional']} .incbin(s) inside an "
                    f"unevaluated .if/.ifdef did NOT credit — KNOWN LIMIT 4]")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="superforge no-raw-address-literals gate: engine/user sources "
                    "reference allocated resources through emitted symbols only.")
    ap.add_argument("--map", required=True, help="symbol_map.json from allocate.py")
    ap.add_argument("files", nargs="+", help=".asm/.inc sources to scan "
                    "(never the generated build/ output)")
    # The rom-backing pass is the one check here that is about the WHOLE
    # composition rather than about a file: "is this claim backed anywhere".
    # A caller that deliberately passes a SUBSET of a composition's ASM — the
    # reg-gate plant tests hand one planted file a whole game's map — cannot
    # answer it, and every claim reads as unbacked.
    #
    # Opt-OUT rather than opt-in, and the polarity is the point: the six
    # Makefile invocations that gate real ROMs pass complete file sets and get
    # the check by DEFAULT. A partial caller must say it is partial, and then
    # the summary line says SKIPPED so the run can never read as clean. An
    # opt-in flag would have been silent everywhere it was forgotten, which is
    # the failure mode this gate exists to close.
    ap.add_argument("--partial-files", action="store_true",
                    help="the file list is a SUBSET of the composition's ASM; "
                         "skip the whole-composition rom-backing check, which "
                         "a subset cannot answer (reported as SKIPPED)")
    # SCANNED IS NOT ASSEMBLED. Only files in the translation unit can back a
    # claim (see include_closure). The root defaults to the FIRST positional
    # file, which is the translation-unit root in every invocation in this tree
    # — the Makefile lists `main.asm` first and the probes pass one file. Name
    # it explicitly when that is not true; get it wrong and the closure
    # collapses and the claims read UNBACKED, which is loud, not silent.
    ap.add_argument("--asm-root", default=None,
                    help="the translation unit's root .asm (default: the first "
                         "positional file). Only files reachable from its "
                         ".include closure can back a rom claim.")
    args = ap.parse_args(argv)

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"no_literals: symbol map {map_path} not found — run the "
              f"allocator first", file=sys.stderr)
        return 2
    io, placements, raw_map = load_map(map_path)

    all_findings: list[Finding] = []
    stats = new_stats()
    paths: list[Path] = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"no_literals: {p} not found", file=sys.stderr)
            return 2
        paths.append(p)
        all_findings += scan_file(p, io, placements, raw_map, stats)
    # Whole-invocation, after every file is read: "is this claim backed
    # anywhere in the composition" is a question no single file can answer.
    if args.partial_files:
        stats["rom_skipped"] = True
    else:
        root = Path(args.asm_root) if args.asm_root else paths[0]
        if root not in paths:
            print(f"no_literals: --asm-root {root} is not in the scanned file "
                  f"list — the translation unit's root must be scanned",
                  file=sys.stderr)
            return 2
        all_findings += scan_rom_backing(paths, raw_map, map_path, stats, root)

    if all_findings:
        for fi in all_findings:
            print(fi, file=sys.stderr)
        n_rom = sum(1 for f in all_findings if f.cls == "rom-backing")
        n_chunk = sum(1 for f in all_findings if f.cls == "chunk-count")
        n_tmpl = sum(1 for f in all_findings if f.cls == "rom-template")
        parts = []
        if n_rom:
            parts.append(f"{n_rom} unbacked ROM claim(s)")
        if n_chunk:
            parts.append(f"{n_chunk} narrated chunk count(s)")
        if n_tmpl:
            parts.append(f"{n_tmpl} blanket rom template(s)")
        rest = len(all_findings) - n_rom - n_chunk - n_tmpl
        if rest:
            parts.append(f"{rest} raw-address")
        # the original wording is kept for the raw-address-only case, which
        # is what every pre-existing consumer of this line reads
        what = (f"{len(all_findings)} raw-address finding(s)"
                if not (n_rom or n_chunk or n_tmpl)
                else f"{len(all_findings)} finding(s) ({', '.join(parts)})")
        print(f"NO-LITERALS FAILED: {what} — "
              f"the map is derived, never narrated", file=sys.stderr)
        return 1
    print(summarise(len(args.files), stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
