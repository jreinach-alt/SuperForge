"""no_literals.py: clean symbol-driven source passes; planted raw addresses,
smuggled immediates, and squatting assignments fail; I/O ports stay legal."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
TOOL = SUPERFORGE / "allocator" / "no_literals.py"

MAP = {
    "spaces": {"wram_bytes": 0x20000, "wram_base_addr": 0x7E0000,
               "dp_bytes": 256, "vram_words": 0x8000,
               "io_allowed": [[0x2100, 0x21FF], [0x4200, 0x43FF]]},
    "globals": [],
    "scenes": {"toy": {"placements": [
        {"sym": "ES_FEAT_A_POS", "class": "dp", "start": 0, "size": 4,
         "scope": "toy", "consumer": "engine:feat_a", "kind": ""},
        {"sym": "US_SCRATCH", "class": "wram", "start": 0x203, "size": 16,
         "scope": "toy", "consumer": "user", "kind": ""},
        {"sym": "ES_V_FEAT_A_MAP", "class": "vram", "start": 0x1400,
         "size": 0x400, "scope": "toy", "consumer": "engine:feat_a",
         "kind": "tilemap"},
    ], "channels": [], "vblank_bytes": 0,
        # The reg pass's DEFAULT tier used to be "no pass at all" for a path
        # matching no context shape — which is what
        # every synthetic file in this module is. It is now the composed union
        # of the map's scenes, so these fixtures are reg-checked like anything
        # else, and CLEAN's `sta $4200` needs a declaration exactly as a real
        # program's would.
        #
        # That is the point of this build rather than an inconvenience of it: a
        # file the gate does not check is a file the gate should not call
        # "clean". $2116/$2118 need nothing added — the vram placement above
        # already covers the vram latch and data port.
        #
        # The union tiers now accept only what this build's
        # OWNER opened, so the claim carries `scene_writes` — these synthetic
        # files are boot-shaped code and NMITIMEN is exactly the register a
        # real global feature opens to it (scene_mgr's sm_display shape). An
        # entry with the key ABSENT opens nothing, which is the fail-closed
        # reading a stale map should get; that is why this had to be added
        # rather than defaulted.
        "reg": [{"name": "toy_nmi", "registers": ["NMITIMEN"],
                 "seed": False, "consumer": "engine:feat_a",
                 "scene_writes": ["NMITIMEN"],
                 "scene_writes_shared": []}]}},
}


def run(tmp_path, source: str):
    mp = tmp_path / "symbol_map.json"
    mp.write_text(json.dumps(MAP))
    src = tmp_path / "t.asm"
    src.write_text(source)
    return subprocess.run(
        [sys.executable, str(TOOL), "--map", str(mp), str(src)],
        capture_output=True, text=True)


CLEAN = """
; clean engine source: symbols + I/O ports only
.p816
        lda z:ES_FEAT_A_POS
        sta a:US_SCRATCH
        ldx #ES_V_FEAT_A_MAP
        stx $2116               ; VMADD — silicon, allowed
        sta $2118               ; VMDATA
        lda #$80
        sta $4200               ; NMITIMEN
        lda #$0F                ; a value, not an address
        ldy #$1000              ; a value outside every emitted range
        .byte $7E, $02, $03     ; data directive: not scanned
"""


def test_clean_source_passes(tmp_path):
    r = run(tmp_path, CLEAN)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("line,cls", [
    ("        sta $7E0203", "address"),          # long WRAM literal
    ("        lda a:$0203", "address"),          # absolute WRAM literal
    ("        lda $04", "address"),              # DP literal operand
    ("        sta $0F00", "address"),            # unallocated WRAM still illegal
    ("        ldx #$1400", "immediate"),         # VRAM word target smuggled
    ("        ldx #$7E0203", "immediate"),       # long WRAM addr smuggled
    ("MY_BUF = $0203", "assign"),                # squatting assignment
    ("        sf_upload $1400, #$40", "address"),  # macro arg literal
    # F6: number-base evasions — the same byte as $0203 in other bases
    ("        sta 515", "address"),              # decimal address literal
    ("        sta %0000001000000011", "address"),  # binary address literal
    ("        ldy #515", "immediate"),           # decimal immediate smuggle
    ("MY_BUF = 515", "assign"),                  # decimal squatting assignment
    ("        ldx #5120", "immediate"),          # decimal VRAM base ($1400)
])
def test_planted_literals_fail(tmp_path, line, cls):
    r = run(tmp_path, CLEAN + line + "\n")
    assert r.returncode == 1, f"{line!r} passed but must fail\n{r.stderr}"
    assert f"[{cls}]" in r.stderr, f"expected class {cls}:\n{r.stderr}"
    assert "NO-LITERALS FAILED" in r.stderr


def test_io_long_form_allowed(tmp_path):
    r = run(tmp_path, "        sta $002118\n")
    assert r.returncode == 0, r.stderr


def test_value_immediates_stay_legal(tmp_path):
    # masks/counts that do not fall in any emitted range must not be findings
    r = run(tmp_path, "        lda #$0FFF\n        ldx #$8000\n        and #$03FF\n")
    assert r.returncode == 0, r.stderr
    # VRAM claim INTERIORS are data space for immediates (palette colors,
    # masks) — only the exact base is the smuggle signature
    r2 = run(tmp_path, "        ldx #$1500\n")     # inside [1400..1800), not base
    assert r2.returncode == 0, r2.stderr


def test_small_decimal_and_binary_stay_legal(tmp_path):
    """F6 must not add loop-count noise: decimal/binary below 256 stay legal
    both as immediates and in address-operand position, and out-of-range
    decimal immediates are data like their hex equivalents."""
    r = run(tmp_path, "        ldy #200\n"          # the classic loop count
                      "        lda #%00001111\n"    # a mask
                      "        adc 42\n"            # decimal operand < 256
                      "        ldx #4096\n")        # = $1000, outside all claims
    assert r.returncode == 0, r.stderr


def test_missing_map_is_usage_error(tmp_path):
    src = tmp_path / "t.asm"
    src.write_text("nop\n")
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(tmp_path / "nope.json"), str(src)],
        capture_output=True, text=True)
    assert r.returncode == 2


# -- channel numbers are allocated resources too ----------------

@pytest.mark.parametrize("line", [
    "        sta a:$4301",              # channel 0's BBAD
    "        sta a:$4300",              # channel 0's DMAP
    "        lda a:$4315",              # channel 1's DAS
    "        sta a:$437F",              # the top of the file
])
def test_raw_channel_register_fails(tmp_path, line):
    """`sta a:$4301` hardcodes channel 0, and $4300-$43FF sits inside
    io_allowed as a RANGE — so the plain I/O allowance let this through for
    a whole phase. Four features drove B-bus ports this way while staying
    invisible to the channel-occupancy gate; this is the gate that sees it."""
    r = run(tmp_path, CLEAN + line + "\n")
    assert r.returncode == 1, r.stdout
    assert "hardcodes DMA channel" in (r.stdout + r.stderr)


def test_register_file_base_immediate_stays_legal(tmp_path):
    """The immediate form addresses the WHOLE file rather than picking a
    channel — scene_mgr's MVN destination — and the base-equate idiom builds
    the per-channel address from the emitted number. Both must pass, or the
    rule breaks the only correct way to reach the register file."""
    r = run(tmp_path, CLEAN + "        ldy #$4300\n")
    assert r.returncode == 0, r.stdout
    r = run(tmp_path, CLEAN + "FNT_REGS = $4300 + ES_D_FONT_UP_CH * 16\n")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("line", [
    "        ldy #$4310",               # picks channel 1
    "        ldx #$4372",               # picks channel 7
])
def test_channel_picking_immediate_fails(tmp_path, line):
    """The exemption is `#$4300`, not the $4300-$437F range.

    The stated justification was "the immediate form addresses the whole file
    rather than picking a channel" — true of #$4300 and false of every other
    value in the range. A 16-byte MVN restoring ONE channel's registers is a
    plausible future idiom and would have hardcoded the channel silently.
    """
    r = run(tmp_path, CLEAN + line + "\n")
    assert r.returncode == 1, r.stdout
    assert "picks DMA channel" in (r.stdout + r.stderr)


def test_equated_channel_register_fails(tmp_path):
    """`REGS = $4301` / `sta a:REGS` used to pass: the channel check lived only
    on the operand path, so naming the address in an equate laundered it."""
    r = run(tmp_path, CLEAN + "REGS = $4301\n        sta a:REGS\n")
    assert r.returncode == 1, r.stdout
    assert "names a DMA channel register file" in (r.stdout + r.stderr)


def test_wram_long_address_is_not_reported_as_a_channel(tmp_path):
    """`sta f:$7E4301` is a WRAM long address, not a DMA register.

    It was reported as "hardcodes DMA channel 0" and skipped the allocated-claim
    lookup, losing the "inside claim X" hint. Still a finding —
    it always was — but now the right one.
    """
    r = run(tmp_path, CLEAN + "        sta f:$7E4301\n")
    assert r.returncode == 1, r.stdout
    out = r.stdout + r.stderr
    assert "hardcodes DMA channel" not in out, out
    assert "raw address operand" in out, out


@pytest.mark.parametrize("enable", ["$420B", "$420C"])
def test_literal_channel_mask_fails(tmp_path, enable):
    """MDMAEN/HDMAEN take a bitmask over CHANNELS, so a literal immediate
    hardcodes which channel fires. A raw-ADDRESS rule cannot see this one:
    the literal is a value, not an address."""
    r = run(tmp_path, CLEAN + f"        lda #$01\n        sta a:{enable}\n")
    assert r.returncode == 1, r.stdout
    assert "literal channel mask" in (r.stdout + r.stderr)


# Every one of these passed the first version of the mask rule, which matched
# exactly `^lda #(hex|decimal)$` on the single non-blank line above the store
#. The `%`-binary miss also
# contradicted this tool's own documented base policy, and `lda #$01` / `.a8` /
# `sta a:$420B` is a one-line edit away from any of these stores in the real
# codebase — a bare width directive was enough to disarm the rule.
@pytest.mark.parametrize("body,why", [
    ("        lda #%00000001\n        sta a:$420B\n", "%-binary literal"),
    ("        ldx #$01\n        stx a:$420B\n", "stx instead of sta"),
    ("        ldy #$02\n        sty a:$420C\n", "sty instead of sta"),
    ("        lda #$01\n        nop\n        sta a:$420B\n", "an intervening nop"),
    ("        lda #$01\n        .a8\n        sta a:$420B\n",
     "an intervening width directive"),
    ("        lda #$01\n        sep #$20\n        sta a:$420B\n",
     "an intervening sep"),
    ("        lda #$01\n        sta f:$00420B\n", "the long store form"),
    ("        lda #$01\n        ora #$02\n        sta a:$420B\n",
     "two literals OR-ed together"),
])
def test_channel_mask_evasions_fail(tmp_path, body, why):
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{why} evaded the rule:\n{r.stdout}"
    assert "channel mask" in (r.stdout + r.stderr), why


def test_equated_channel_mask_fails(tmp_path):
    """An equate is a literal with a name on it.

    The assign path only checks whether the VALUE is an allocated address, and
    $01 is not, so `MASK = $01` sails through and the mask rule then sees a
    symbol. Caught now because the rule demands the immediate NAME a channel,
    rather than merely not be a bare number.
    """
    r = run(tmp_path, CLEAN + "MASK = $01\n        lda #MASK\n        sta a:$420B\n")
    assert r.returncode == 1, r.stdout
    assert "channel mask" in (r.stdout + r.stderr)


# -- the HDMAEN SHADOW is a mask surface too --------------------

@pytest.mark.parametrize("body,why", [
    ("        lda #$FF\n        sta z:ES_SM_NMI+2\n", "hex literal"),
    ("        lda #%10000000\n        sta z:ES_SM_NMI+2\n", "binary literal"),
    ("        lda #64\n        sta z:ES_SM_NMI+2\n", "decimal literal"),
    ("        lda #$40\n        sta ES_SM_NMI+2\n", "no width prefix"),
    ("        lda #$40\n        sta z:ES_SM_NMI + 2\n", "spaced offset"),
    ("        ldx #$40\n        stx z:ES_SM_NMI+2\n", "stx"),
    ("        lda #$40\n        .a8\n        sta z:ES_SM_NMI+2\n",
     "intervening directive"),
    ("        lda #(1 << ES_H_BGM_CH)\n        ora #$80\n"
     "        sta z:ES_SM_NMI+2\n", "undeclared bit OR-ed onto a legal mask"),
    ("MASK = $40\n        lda #MASK\n        sta z:ES_SM_NMI+2\n",
     "equated mask"),
    ("        lda #$40\n        sta z:ES_SM_NMI, x\n",
     "indexed store — a computed index can reach +2"),
])
def test_literal_mask_into_the_hdmaen_shadow_fails(tmp_path, body, why):
    """`sta z:ES_SM_NMI+2` is a write to HDMAEN, one frame delayed.

    `sm_nmi_core` is the ONLY per-frame writer of `$420C` and it writes
    whatever this byte holds, so gating the register while leaving the shadow
    open is a rule that documents a guarantee it does not provide — the mask
    rule's own docstring cited the shadow's store sites as the justification
    for accepting a memory-sourced `$420C` write, and those sites were
    ungated. `lda #$FF / sta z:ES_SM_NMI+2` passed clean while the identical
    literal into `$420C` was refused,
    and that is the path a later review used to arm an undeclared channel 6 in the
    results scene, destroying the screen with 266/266 tests green (N1).
    """
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{why} reached HDMAEN unchallenged:\n{r.stdout}"
    out = r.stdout + r.stderr
    assert "channel mask" in out or "no traceable source" in out, out
    assert "HDMAEN shadow" in out, out


@pytest.mark.parametrize("body,why", [
    ("        lda #1\n        sta z:ES_SM_NMI\n", "+0 is nmi_ready"),
    ("        lda #$80\n        sta z:ES_SM_NMI+1\n", "+1 is the INIDISP shadow"),
    ("        stz z:ES_SM_NMI+2\n", "stz disarms"),
])
def test_non_mask_bytes_of_the_nmi_block_stay_legal(tmp_path, body, why):
    """Only `+2` is a channel mask.

    `+0` (nmi_ready) and `+1` (the INIDISP shadow) legitimately take literals —
    `lda #1 / sta z:ES_SM_NMI` is sm_frame_sync and `lda #$80 / sta
    z:ES_SM_NMI+1` is scene_mgr's forced-blank request. A rule that flagged
    them would be false-positive noise, and noise is how a gate gets disabled.
    """
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 0, f"{why} was wrongly flagged:\n{r.stdout}"


def test_symbol_sourced_channel_mask_stays_legal(tmp_path):
    """The legal forms, all of which appear in the engine as-is.

    A shifted channel symbol; several OR-ed together (race.asm arms seven
    channels this way, across two immediates, into the SHADOW); a mask loaded
    from MEMORY (scene_mgr's `lda z:ES_SM_NMI+2` / `sta a:$420C` — the shadow,
    whose own store sites this rule now really does police); and `stz`.
    """
    r = run(tmp_path, CLEAN
            + "        lda #(1 << ES_H_BGM_CH)\n        sta a:$420B\n"
            + "        lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH))\n"
            + "        ora #(1 << ES_D_FONT_UP_CH)\n        sta a:$420C\n"
            + "        lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH))\n"
            + "        ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH))\n"
            + "        sta z:ES_SM_NMI+2\n"
            + "        lda z:ES_SM_NMI+2\n        sta a:$420C\n"
            + "        stz a:$420C\n")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("body,why", [
    ("        lda #$01\n        tax\n        stx a:$420B\n", "tax"),
    ("        lda #$01\n        asl a\n        sta a:$420B\n", "asl a"),
    ("        lda #$01\n        pha\n        pla\n        sta a:$420B\n", "pla"),
    ("        ldy #$02\n        tya\n        sta a:$420C\n", "tya"),
])
def test_implied_operand_ops_cannot_launder_a_literal_mask(tmp_path, body, why):
    """A register transfer is not a memory load.

    The provenance walk classified every register-setting instruction WITHOUT a
    `#` operand as "loaded from memory", and callers treat "memory" as legal
    (its provenance is whatever wrote that memory, policed at those store
    sites). Implied-operand ops have no such store site — the value came from
    another register or the stack — so `lda #$01 / tax / stx a:$420B` and
    `lda #$01 / asl a / sta a:$420B` both passed clean. They now fail closed as
    "unknown": contrived shapes, but the classification was simply wrong.
    """
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{why} laundered a literal mask:\n{r.stdout}"
    assert "no traceable source" in (r.stdout + r.stderr), r.stdout


def test_memory_sourced_and_memory_rmw_masks_stay_legal(tmp_path):
    """The N6 fix must not sweep in real memory loads or memory RMW.

    `lda a:<table>` genuinely reads memory (legal — policed where that memory
    is written). `inc a:<counter>` modifies MEMORY, not A, so it must not end
    the walk at all: the mask two lines up is still the traceable source.
    """
    r = run(tmp_path, CLEAN
            + "        lda a:US_SCRATCH\n        sta a:$420B\n"
            + "        lda #(1 << ES_H_BGM_CH)\n"
            + "        inc a:US_SCRATCH\n        sta a:$420B\n")
    assert r.returncode == 0, r.stdout


# -- ONE write set, both passes (tsb/trb and the RMW family at the surface) --
#
# The channel rules matched sta/stx/sty/stz only while the reg-ownership pass
# knew the RMW family — and the ownership pass hands the whole channel
# territory to the channel rules, so a `tsb a:$420B` was counted by one pass,
# deferred to the other, and seen by NEITHER. STORE_RE/ENC_STORE_RE and
# REG_WRITE_MN are now built from the same WRITE_STORES/WRITE_RMW tuples;
# these are the behavioural proofs on each side of the territory split.

@pytest.mark.parametrize("body,why", [
    ("        lda #$01\n        tsb a:$420B\n", "tsb arms a literal channel"),
    ("        lda #$02\n        trb a:$420C\n",
     "trb disarms a literal channel — a disarm mask names channels too"),
    ("        lda #$01\n        tsb z:ES_SM_NMI+2\n",
     "tsb into the HDMAEN shadow"),
])
def test_a_literal_mask_through_tsb_trb_fails(tmp_path, body, why):
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{why} passed clean:\n{r.stdout}"
    assert "literal channel mask" in (r.stdout + r.stderr), r.stdout


@pytest.mark.parametrize("body,why", [
    ("        inc a:$420C\n", "inc on HDMAEN"),
    ("        asl z:ES_SM_NMI+2\n", "asl on the shadow"),
])
def test_memory_rmw_on_the_mask_surface_fails_closed(tmp_path, body, why):
    """The stored mask derives from the surface's own value — no allocated
    channel symbol can feed it, so the site takes an override or a rewrite."""
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{why} passed clean:\n{r.stdout}"
    assert "read-modify-write" in (r.stdout + r.stderr), r.stdout


def test_a_symbol_mask_through_tsb_stays_legal(tmp_path):
    r = run(tmp_path, CLEAN + "        lda #(1 << ES_H_BGM_CH)\n"
                              "        tsb a:$420B\n")
    assert r.returncode == 0, r.stdout


def test_tsb_against_a_hardware_register_is_seen_by_both_passes(tmp_path):
    """The pair the shared write set exists for: the SAME mnemonic against
    the enable port fires the CHANNEL pass, and against an in-class PPU port
    fires the REG-OWNERSHIP pass — neither side of the territory split can
    lose it any more."""
    r = run(tmp_path, CLEAN + "        lda #$01\n        tsb a:$420B\n"
                              "        lda #$07\n        tsb a:$2105\n")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "[channel]" in out and "$420B" in out, out
    assert "[reg]" in out and "BGMODE" in out, out


# -- DP relocation: the reg pass attributes dp writes through a moved D ------
#
# The tool's header used to state this as ITS blind spot: `lda #$2100 / tcd /
# sta $05` IS a BGMODE write and no reg pass saw it, backstopped only
# incidentally by the address rule's refusal of the raw `$05`. The pass now
# tracks DP per routine and attributes dp operands; these hold each polarity,
# and each proves it exercised the NEW code — the decimal spelling is
# invisible to every other rule, the passing arms are checked against the
# summary's own `dp:` census (so a pass that never ran cannot read as clean),
# and the declared arm is paired with its undeclared refusal.

def run_map(tmp_path, mapdict, source: str):
    mp = tmp_path / "symbol_map.json"
    mp.write_text(json.dumps(mapdict))
    src = tmp_path / "t.asm"
    src.write_text(source)
    return subprocess.run(
        [sys.executable, str(TOOL), "--map", str(mp), str(src)],
        capture_output=True, text=True)


def test_the_header_example_is_caught_and_attributed_to_bgmode(tmp_path):
    """`lda #$2100 / tcd / sta $05`: the address rule still refuses the raw
    literal (the backstop, unweakened) AND the reg pass now names BGMODE."""
    r = run(tmp_path, CLEAN + "        lda #$2100\n        tcd\n"
                              "        sta $05\n")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "raw address operand" in out, out          # the backstop held
    assert "$2105" in out and "BGMODE" in out, out    # the attribution is new
    assert "relocated" in out, out


def test_the_decimal_dp_spelling_no_other_rule_can_see_is_caught(tmp_path):
    """`sta 5` rides the address rule's F6 decimal exemption, so before the
    DP pass this whole file exited 0 — the sharpest liveness proof there is."""
    r = run(tmp_path, CLEAN + "        lda #$2100\n        tcd\n"
                              "        sta 5\n")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "BGMODE" in out and "relocated" in out, out


def test_a_declared_relocated_write_passes_and_undeclared_fails(tmp_path):
    """The declared/legitimate shape: the write is attributed to its port
    and answers to the SAME claim machinery as an absolute write — a map
    that declares (and opens) the register accepts it, the same map without
    the declaration refuses it, and the summary census proves the passing
    arm was ATTRIBUTED rather than skipped."""
    import copy
    body = (CLEAN + "        lda #$2100\n        tcd\n"
                    "        sta z:ES_FEAT_A_POS\n")   # dp offset 0 -> $2100
    declared = copy.deepcopy(MAP)
    declared["scenes"]["toy"]["reg"].append(
        {"name": "toy_disp", "registers": ["INIDISP"], "seed": False,
         "consumer": "engine:feat_a", "scene_writes": ["INIDISP"],
         "scene_writes_shared": []})
    ok = run_map(tmp_path, declared, body)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "dp: 1 relocation(s) tracked, 1 dp write-site(s) attributed" in \
        ok.stdout, ok.stdout
    bad = run_map(tmp_path, MAP, body)
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "INIDISP" in (bad.stdout + bad.stderr), bad.stdout + bad.stderr


def test_a_benign_relocation_passes_and_the_tracker_says_it_ran(tmp_path):
    """A save-area repoint (page misses the io window) is legal — and the
    census must still count the relocation, or a silent tracker would be
    indistinguishable from a clean one."""
    r = run(tmp_path, CLEAN + "        lda #$0300\n        tcd\n"
                              "        sta z:ES_FEAT_A_POS\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dp: 1 relocation(s) tracked, 0 dp write-site(s) attributed" in \
        r.stdout, r.stdout


def test_a_dynamic_dp_is_refused_at_the_establishing_instruction(tmp_path):
    """A `tcd` this file cannot fold poisons every later dp operand — one
    conservative refusal at the cause, not silence."""
    r = run(tmp_path, CLEAN + "        lda a:US_SCRATCH\n        tcd\n"
                              "        sta z:ES_FEAT_A_POS\n")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "cannot fold" in out and "unattributable" in out, out


def test_a_phd_pld_bracket_restores_and_the_channel_territory_refuses(
        tmp_path):
    """Two more shapes: after `pld` the home page is back (the write is the
    allocator's own dp byte again — legal), and a dp write into the channel
    territory is refused outright, since the channel rules cannot see the
    dp-relative form."""
    ok = run(tmp_path, CLEAN
             + "        phd\n        lda #$2100\n        tcd\n"
             + "        pld\n        sta z:ES_FEAT_A_POS\n")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = run(tmp_path, CLEAN + "        lda #$4200\n        tcd\n"
                                "        lda #$01\n        sta $0B\n")
    out = bad.stdout + bad.stderr
    assert bad.returncode == 1, out
    assert "channel territory" in out and "$420B" in out, out


# -- DMAP/BBAD must come from the declaration, not from a literal (F8) -------

ENC_PRELUDE = "FNT_REGS = $4300 + ES_D_FONT_UP_CH * 16\n"


@pytest.mark.parametrize("body,what", [
    ("        lda #$01\n        sta a:FNT_REGS + 0\n", "DMAP"),
    ("        lda #$18\n        sta a:FNT_REGS + 1\n", "BBAD"),
    ("        lda #%00000001\n        sta a:FNT_REGS\n", "DMAP"),
    ("        lda #$40\n        .a8\n        sta f:ES_SM_HDMA_LONG+0, x\n", "DMAP"),
    ("        lda #$32\n        sta f:ES_SM_HDMA_LONG+1, x\n", "BBAD"),
    ("        stz a:FNT_REGS + 0\n", "DMAP"),
])
def test_literal_channel_encoding_fails(tmp_path, body, what):
    """A site free to invent DMAP/BBAD is free to drive a register its .toml
    never named — the drift that was closed for the sites that existed, and
    that nothing stopped a new site from reintroducing. probe_vb2reg's nine
    literal DMAP/BBAD writes all passed this tool before the rule existed, and
    two of its claims were under-declared as a direct result.
    """
    r = run(tmp_path, CLEAN + ENC_PRELUDE + body)
    assert r.returncode == 1, r.stdout
    assert what in (r.stdout + r.stderr), r.stdout


@pytest.mark.parametrize("prelude,why", [
    ("FNT_REGS = $4300 + ES_D_FONT_UP_CH * 16\n", "canonical"),
    ("FNT_REGS = $4300 | ES_D_FONT_UP_CH * 16\n", "OR instead of +"),
    ("FNT_REGS = $4300 + (ES_D_FONT_UP_CH * 16)\n", "parenthesised product"),
    ("FNT_REGS = $4300 + 16 * ES_D_FONT_UP_CH\n", "reversed product"),
    ("FNT_REGS = $4300 + (ES_D_FONT_UP_CH << 4)\n", "shift instead of * 16"),
    ("FNT_REGS := $4300 | ES_D_FONT_UP_CH * 16\n", "colon-eq, OR"),
    ("FNT_REGS=$4300+ES_D_FONT_UP_CH*16\n", "no whitespace"),
])
def test_every_equivalent_base_spelling_still_gates_the_encoding(
        tmp_path, prelude, why):
    """Whichever way the base is spelled, writes through it are still checked.

    `_channel_bases` decided WHOSE `+0`/`+1` writes the DMAP/BBAD rule inspects,
    and it demanded the exact textual shape `$4300 + ES_?_<CLAIM>_CH * 16` while
    the assign path accepted `$4300` on the much looser "mentions an
    `ES_[HD]_*_CH` symbol". Four arithmetically-identical spellings therefore
    passed the assign check, never entered `bases`, and turned the encoding rule
    OFF for the whole file with a clean build — F8 reopened by a pair of
    parentheses. Both rules now share
    one predicate, so they cannot disagree.

    For channels 0..7, `$4300 | ch*16`, `$4300 + ch*16`, `$4300 + 16*ch` and
    `$4300 + (ch << 4)` compute the identical address — an author picking any of
    them is writing correct, idiomatic ca65.
    """
    r = run(tmp_path, CLEAN + prelude
            + "        lda #$04\n        sta a:FNT_REGS + 1\n")
    assert r.returncode == 1, f"the {why} base spelling disabled the rule:\n{r.stdout}"
    assert "BBAD" in (r.stdout + r.stderr), r.stdout


def test_two_step_base_construction_is_refused_at_the_assign(tmp_path):
    """`OFF = CH*16` / `REGS = $4300 + OFF` never reaches the encoding rule.

    The second line names `$4300` without naming a channel symbol, so the ASSIGN
    rule refuses it and the file does not build — which is the right outcome,
    but it means writes through such a base are never encoding-checked. Pinned
    here so the pairing is deliberate rather than accidental: if a future change
    ever makes that assign legal, this test goes red and the encoding side has
    to be taught the same shape.
    """
    r = run(tmp_path, CLEAN
            + "OFF = ES_D_FONT_UP_CH * 16\nFNT_REGS = $4300 + OFF\n"
            + "        lda #$04\n        sta a:FNT_REGS + 1\n")
    assert r.returncode == 1, r.stdout
    assert "names a DMA channel register file" in (r.stdout + r.stderr), r.stdout


def test_symbol_channel_encoding_stays_legal(tmp_path):
    """The emitted symbols, bare and with a source-side bit OR-ed on.

    `ES_H_PROBE_DMA_DMAP | DMAP_FIXED_SRC` is probe_vblank's real form: DMAP
    bit 3 holds the A-bus address fixed, which is a SOURCE-side property and
    therefore not part of any destination claim (D6), so OR-ing it on at the
    site is correct and must stay legal.
    """
    r = run(tmp_path, CLEAN + ENC_PRELUDE
            + "        lda #ES_D_FONT_UP_DMAP\n        sta a:FNT_REGS + 0\n"
            + "        lda #ES_D_FONT_UP_BBAD\n        sta a:FNT_REGS + 1\n"
            + "        lda #(ES_H_PROBE_DMA_DMAP | DMAP_FIXED_SRC)\n"
            + "        sta f:ES_SM_HDMA_LONG+0, x\n"
            + "        lda #ES_H_COLR_BBAD\n"
            + "        sta f:ES_SM_HDMA_LONG+1, x\n")
    assert r.returncode == 0, r.stdout


def test_non_encoding_offsets_stay_legal(tmp_path):
    """Only +0 and +1 are the declaration's business.

    A1T/A1B/DAS/DASB are the transfer's source and length — the feature's own
    data, not anything the allocator emits — so the rule must not touch them.
    """
    r = run(tmp_path, CLEAN + ENC_PRELUDE
            + "        lda #$7E\n        sta a:FNT_REGS + 4\n"
            + "        lda #$00\n        sta a:FNT_REGS + 5\n"
            + "        lda #$06\n        sta a:FNT_REGS + 6\n")
    assert r.returncode == 0, r.stdout


def test_channel_lint_override_needs_a_reason(tmp_path):
    """A bare `; CHANNEL-LINT: ok` is a silent way to turn the rule off.

    Same convention as the width lint: the reason after
    the separator is required, and a bare override is itself a finding, so
    rubber-stamping shows up in review as a red build rather than as a comment.
    """
    bare = run(tmp_path, CLEAN + ENC_PRELUDE
               + "        lda #$01\n        ; CHANNEL-LINT: ok\n"
               + "        sta a:FNT_REGS + 0\n")
    assert bare.returncode == 1, bare.stdout
    assert "bare `; CHANNEL-LINT: ok`" in (bare.stdout + bare.stderr)

    good = run(tmp_path, CLEAN + ENC_PRELUDE
               + "        lda #$01\n"
               + "        ; CHANNEL-LINT: ok — shared with VMAIN, .assert guards it\n"
               + "        sta a:FNT_REGS + 0\n")
    assert good.returncode == 0, good.stdout


# -- the enable-port surface is a PREDICATE, not a pattern ---
#
# Three rounds of this rule matched the store's destination textually, and each
# round an arithmetically-identical spelling walked past it. R5 was the fourth:
# `MUT_HDMAEN = $420C` then `sta a:MUT_HDMAEN` put a literal mask into the real
# HDMAEN while the gate printed "1 file(s) clean". Every case below was
# ACCEPTED by the pre-predicate tool. Adding these six spellings to a pattern
# list would have been the fourth patch; the rule now RESOLVES the destination
# instead, so a seventh spelling has nothing to walk past.

@pytest.mark.parametrize("label,body", [
    ("direct alias",
     "MUT_HDMAEN = $420C\n        lda #$40\n        sta a:MUT_HDMAEN\n"),
    ("chained alias",
     "A_PORT = $420C\nB_PORT = A_PORT\n        lda #$40\n        sta a:B_PORT\n"),
    ("alias declared AFTER the store",
     "        lda #$40\n        sta a:LATE_PORT\nLATE_PORT = $420B\n"),
    ("MDMAEN alias",
     "FIRE = $420B\n        lda #$01\n        sta a:FIRE\n"),
    # STORE_RE's old `[azf]?:?` ate the bare leading letter of a symbol
    # operand (reg-writer-gate review) — dest `ADE_EN` resolved to
    # nothing and the store evaded THIS pass too. The atomic prefix fix
    # repairs both passes; this param pins the channel-mask side.
    ("bare store to an f-initial alias (the [azf]-prefix trap)",
     "FADE_EN = $420C\n        lda #$40\n        sta FADE_EN\n"),
    ("shadow offset spelled +1+1",
     "        lda #$FF\n        sta z:ES_SM_NMI+1+1\n"),
    ("alias equate to the shadow byte",
     "HD_SH = ES_SM_NMI+2\n        lda #$FF\n        sta z:HD_SH\n"),
])
def test_literal_mask_cannot_reach_an_enable_port_by_any_spelling(
        tmp_path, label, body):
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 1, f"{label}: ACCEPTED — {r.stdout}{r.stderr}"
    assert "channel" in (r.stdout + r.stderr)


@pytest.mark.parametrize("label,body", [
    ("symbolic mask through an alias",
     "MUT = $420C\n        lda #(1 << ES_H_BGM_CH)\n        sta a:MUT\n"),
    ("stz disarms",            "        stz a:$420C\n"),
    ("ES_SM_NMI+1 is the INIDISP shadow, not a mask",
     "        lda #$0F\n        sta z:ES_SM_NMI+1\n"),
    ("ES_SM_NMI+0 is nmi_ready, not a mask",
     "        lda #$01\n        sta z:ES_SM_NMI\n"),
])
def test_the_predicate_does_not_over_refuse(tmp_path, label, body):
    """Closing six holes must not cost a legal form. `+0`/`+1` of the NMI
    block take literals legitimately and must stay legal, or the rule starts
    lying about a different byte."""
    r = run(tmp_path, CLEAN + body)
    assert r.returncode == 0, f"{label}: refused — {r.stdout}{r.stderr}"
