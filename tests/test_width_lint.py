"""
Unit + integration tests for tools/width_lint.py.

Coverage:
  - Each of the 3 checks against synthetic ca65 inputs (positive + negative)
  - Override convention (justified passes, bare ok rejected)
  - WL-12 regression: reproduce the 17-11 dispatch-chain bug and verify
    the linter catches it
  - Integration smoke: linter runs on real engine/*.asm files

Run with:
    python -m pytest tests/test_width_lint.py -v
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Make tools/ importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import width_lint  # noqa: E402


# --- Helpers -----------------------------------------------------------------

def lint(tmp_path: Path, source: str, name: str = "snippet.asm") -> list[width_lint.Finding]:
    """Write `source` to a tmp .asm file and run the linter on it."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(source).lstrip("\n"))
    return width_lint.lint_file(p)


def rules(findings: list[width_lint.Finding]) -> list[str]:
    return [f.rule for f in findings]


# --- Check 1: multi-path label annotation -----------------------------------

def test_check1_passes_when_label_annotated(tmp_path):
    """Multi-path label with explicit `.a16` directly after — should pass."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        cmp #1
        bne @other
        bra @target
    @other:
        .a16
        sep #$20
        .a8
        nop
        rep #$20
        .a16
        bra @target
    @target:
        .a16
        cmp #240
        rts
    """
    findings = lint(tmp_path, src)
    assert "multipath-label" not in rules(findings)


def test_check1_flags_unannotated_multipath_label(tmp_path):
    """Multi-path label reached from A8 + A16 paths without annotation — flagged."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        bra @target

        sep #$20
        .a8
        bra @target

    @target:
        cmp #240
        rts
    """
    findings = lint(tmp_path, src)
    multipath = [f for f in findings if f.rule == "multipath-label"]
    assert len(multipath) == 1
    assert multipath[0].label == "@target"


def test_check1_single_path_label_not_flagged(tmp_path):
    """Single-arrival label without annotation — not flagged."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        bra @target
    @target:
        cmp #240
        rts
    """
    findings = lint(tmp_path, src)
    multipath = [f for f in findings if f.rule == "multipath-label"]
    assert multipath == []


def test_check1_override_suppresses(tmp_path):
    """Override comment with reason text suppresses the finding."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        bra @target
        sep #$20
        .a8
        bra @target
        ; WIDTH-LINT: ok — both paths re-rep before bra in real impl
    @target:
        cmp #240
        rts
    """
    findings = lint(tmp_path, src)
    assert "multipath-label" not in rules(findings)


def test_check1_bare_override_rejected(tmp_path):
    """Bare `ok` (no reason) is itself flagged as a separate finding."""
    src = """
        .p816
        .smart
        .segment "CODE"
        ; WIDTH-LINT: ok
        nop
    """
    findings = lint(tmp_path, src) + width_lint.detect_bare_overrides(
        tmp_path / "snippet.asm"
    )
    assert any(f.rule == "bare-override" for f in findings)


# --- Check 2: tax / tay cross-width transfers ------------------------------

def test_check2_passes_with_zero_extend(tmp_path):
    """tax preceded by `and #$00FF` after `.a16` — passes."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        lda $1234
        and #$00FF
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" not in rules(findings)


def test_check2_passes_with_width_risk_comment(tmp_path):
    """tax preceded by `; WIDTH-RISK:` — passes."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        ; WIDTH-RISK: caller pre-zeroed C-high; safe to tax in A8/I16
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" not in rules(findings)


def test_check2_flags_undocumented_tax(tmp_path):
    """tax without zero-extend or width-risk comment — flagged.

    This is an earlier bug pattern: tax-after-A8-lda in I16 mode with
    no high-byte clear and no documented contract. The dangerous case is
    A8/I16: the X register is 16-bit but C-high (hidden upper A) is
    whatever stale value was last there, so `tax` corrupts X-high.
    """
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    tax_findings = [f for f in findings if f.rule == "tax-tay-cross-width"]
    assert len(tax_findings) == 1


def test_check2_flags_tay_too(tmp_path):
    """tay is checked the same as tax."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        lda #$01
        tay
        rts
    """
    findings = lint(tmp_path, src)
    tay_findings = [f for f in findings if f.rule == "tax-tay-cross-width"]
    assert len(tay_findings) == 1


def test_check2_a8_i8_tax_not_flagged(tmp_path):
    """A8/I8 tax is an 8-bit-to-8-bit transfer; safe and not flagged."""
    src = """
        .p816
        .smart
        .segment "CODE"
        sep #$30
        .a8
        .i8
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    tax_findings = [f for f in findings if f.rule == "tax-tay-cross-width"]
    assert tax_findings == []


def test_check2_high_byte_mask_does_not_count(tmp_path):
    """`and #$8000` is NOT a low-byte mask and should NOT excuse an A8/I16 tax."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        and #$8000
        sep #$20
        .a8
        tax
        rts
    """
    findings = lint(tmp_path, src)
    tax_findings = [f for f in findings if f.rule == "tax-tay-cross-width"]
    assert len(tax_findings) == 1


def test_check2_a16_tax_not_flagged(tmp_path):
    """A16 tax is the ordinary 16-bit index-load idiom and not a bug."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        lda $1234
        tax
        rts
    """
    findings = lint(tmp_path, src)
    tax_findings = [f for f in findings if f.rule == "tax-tay-cross-width"]
    assert tax_findings == []


# --- Check 3: macro contracts ----------------------------------------------

def test_check3_passes_with_contract_comment(tmp_path):
    """Macro toggling sep with `; WIDTH-RISK:` comment above — passes."""
    src = """
        .p816
        .smart
        .segment "CODE"
        ; WIDTH-RISK: entry A16, exit A8. Caller must rep #$20 to restore.
        .macro STAMP_BYTE
            sep #$20
            sta $E010
        .endmacro
    """
    findings = lint(tmp_path, src)
    assert "macro-no-contract" not in rules(findings)


def test_check3_flags_macro_without_contract(tmp_path):
    """Macro toggling sep without `; WIDTH-RISK:` — flagged."""
    src = """
        .p816
        .smart
        .segment "CODE"
        .macro STAMP_BYTE_BAD
            sep #$20
            sta $E010
        .endmacro
    """
    findings = lint(tmp_path, src)
    macro_findings = [f for f in findings if f.rule == "macro-no-contract"]
    assert len(macro_findings) == 1
    assert macro_findings[0].label == "STAMP_BYTE_BAD"


def test_check3_folded_width_risk_is_flagged_with_own_line_guidance(tmp_path):
    """A WIDTH-RISK marker FOLDED into another comment (not directly after the
    `;`) does NOT satisfy the contract — the marker regex only matches when
    WIDTH-RISK directly follows the comment delimiter. The finding's message
    must explicitly tell the author the contract has to be on its OWN comment
    line, so they don't keep folding it. (ITEM 5 regression.)"""
    src = """
        .p816
        .smart
        .segment "CODE"
        ; Clobbers A. WIDTH-RISK: entry A16, exit A8 — folded, does NOT count
        .macro STAMP_FOLDED
            sep #$20
            sta $E010
        .endmacro
    """
    findings = lint(tmp_path, src)
    macro_findings = [f for f in findings if f.rule == "macro-no-contract"]
    assert len(macro_findings) == 1, (
        f"folded WIDTH-RISK must NOT satisfy the contract; got {macro_findings}"
    )
    assert macro_findings[0].label == "STAMP_FOLDED"
    msg = macro_findings[0].message
    assert "own" in msg.lower() and "comment line" in msg.lower(), (
        f"message must tell the author the contract goes on its OWN comment "
        f"line; got: {msg!r}"
    )
    # The message should also show the folded anti-pattern so the fix is obvious.
    assert "WIDTH-RISK" in msg


def test_check3_macro_without_sep_rep_not_flagged(tmp_path):
    """A macro with no width-toggling instructions is not flagged."""
    src = """
        .p816
        .smart
        .segment "CODE"
        .macro PURE_LOAD
            lda $1234
            sta $5678
        .endmacro
    """
    findings = lint(tmp_path, src)
    macro_findings = [f for f in findings if f.rule == "macro-no-contract"]
    assert macro_findings == []


def test_check3_passes_with_contract_in_long_header_block(tmp_path):
    """
    SuperForge convention: macros sit under multi-paragraph block comments
    where WIDTH-RISK lives 8-15 lines above the .macro line. The header-
    block scan must find it as long as the comment block is contiguous.
    """
    src = """
        .p816
        .smart
        .segment "CODE"
        ; -----------------------------------------------------------------
        ; STAMP_X — write a debug byte from the X register to a fixed slot.
        ;
        ; Used by the harness ROMs to capture intermediate state. Designed
        ; to be safe to call from any code path; saves all registers.
        ;
        ; Clobbers: nothing visible to caller (PHA/PLA bracketing).
        ; Cost: ~30 cy.
        ;
        ; WIDTH-RISK: entry A8 or A16; uses sep #$20 only (never sep #$30)
        ; so caller's I-width tracking is preserved.
        ; -----------------------------------------------------------------
        .macro STAMP_X
            php
            sep #$20
            sta $E010
            plp
        .endmacro
    """
    findings = lint(tmp_path, src)
    macro_findings = [f for f in findings if f.rule == "macro-no-contract"]
    assert macro_findings == [], (
        f"WIDTH-RISK in header block should satisfy contract; got: {macro_findings}"
    )


def test_check3_header_block_scan_stops_at_code(tmp_path):
    """
    If a non-comment line breaks the header block AND the WIDTH-RISK
    comment is more than 5 lines away (outside the original spec's
    fallback window), the scan does NOT count it.
    """
    src = """
        .p816
        .smart
        .segment "CODE"
        ; WIDTH-RISK: applies to UNRELATED_THING, not the macro below
        unrelated_label:
            ; comment line 1
            ; comment line 2
            ; comment line 3
            ; comment line 4
            rts
        .macro STAMP_LOST
            sep #$20
            sta $E010
        .endmacro
    """
    findings = lint(tmp_path, src)
    macro_findings = [f for f in findings if f.rule == "macro-no-contract"]
    assert len(macro_findings) == 1
    assert macro_findings[0].label == "STAMP_LOST"


# --- Override mechanism -----------------------------------------------------

def test_override_em_dash(tmp_path):
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        ; WIDTH-LINT: ok — caller already pre-zeroed C-high
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" not in rules(findings)


def test_override_double_hyphen(tmp_path):
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        ; WIDTH-LINT: ok -- caller already pre-zeroed C-high
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" not in rules(findings)


def test_override_colon(tmp_path):
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        ; WIDTH-LINT: ok: caller already pre-zeroed C-high
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" not in rules(findings)


def test_override_bare_rejected_by_detector(tmp_path):
    """`; WIDTH-LINT: ok` with no reason is itself a bare-override finding."""
    p = tmp_path / "snippet.asm"
    p.write_text("; WIDTH-LINT: ok\n")
    bare = width_lint.detect_bare_overrides(p)
    assert len(bare) == 1
    assert bare[0].rule == "bare-override"


def test_override_bare_does_not_suppress(tmp_path):
    """A bare `; WIDTH-LINT: ok` near a real violation does NOT suppress it."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$10
        .i16
        sep #$20
        .a8
        ; WIDTH-LINT: ok
        lda #$01
        tax
        rts
    """
    findings = lint(tmp_path, src)
    assert "tax-tay-cross-width" in rules(findings)


# --- WL-12 regression: 17-11 dispatch chain bug ----------------------------

DISPATCH_CHAIN_BUG = """
    .p816
    .smart
    .segment "CODE"
    ; Reconstructs the 17-11 frame-dispatch chain bug pattern.
    ; @after_dispatch is reached from multiple branch paths in mixed
    ; A-width modes, but has no explicit annotation — silent BRK.

    rep #$30
    .a16
    .i16

@frame_loop:
    rep #$20
    .a16
    lda $0E00
    inc
    sta $0E00

    cmp #1
    bne @not_frame_1
    jsr engine_call_1
    bra @after_dispatch
@not_frame_1:
    cmp #30
    bne @not_frame_30
    sep #$20
    .a8
    lda #$AA
    sta $E010
    bra @after_dispatch
@not_frame_30:
    cmp #220
    bne @not_frame_220
    jsr engine_reject
    sep #$20
    .a8
    lda $E090
    sta $E082
    bra @after_dispatch
@not_frame_220:
    cmp #240
    bne @after_dispatch
    sep #$20
    .a8
    lda $E091
    sta $E086
    ; bug: missing rep #$20 / .a16 before fall-through to multi-path label

@after_dispatch:
    cmp #240
    rts

engine_call_1:
    rts
engine_reject:
    rts
"""


def test_wl12_dispatch_chain_bug_caught(tmp_path):
    """WL-12: linter must flag the 17-11 dispatch-chain pattern."""
    findings = lint(tmp_path, DISPATCH_CHAIN_BUG, name="dispatch_chain_bug.asm")
    multipath = [f for f in findings if f.rule == "multipath-label"]
    after_dispatch_findings = [f for f in multipath if f.label == "@after_dispatch"]
    assert len(after_dispatch_findings) == 1, (
        f"expected exactly 1 @after_dispatch finding, got "
        f"{len(after_dispatch_findings)}: {after_dispatch_findings}"
    )
    f = after_dispatch_findings[0]
    assert "@after_dispatch" in f.message
    assert "no explicit" in f.message


def test_wl12_dispatch_chain_fixed_passes(tmp_path):
    """The fixed dispatch chain (with `.a16` after `@after_dispatch:`) passes."""
    fixed = DISPATCH_CHAIN_BUG.replace(
        "@after_dispatch:\n    cmp #240",
        "@after_dispatch:\n    .a16\n    cmp #240",
    )
    findings = lint(tmp_path, fixed, name="dispatch_chain_fixed.asm")
    multipath = [f for f in findings if f.rule == "multipath-label"]
    after_dispatch_findings = [f for f in multipath if f.label == "@after_dispatch"]
    assert after_dispatch_findings == []


# WL-12 acceptance: the on-disk fixture files (committed alongside the
# linter) must reproduce the exact 17-11 bug pattern AND its fix. These
# tests use the real files to lock in the regression so anyone editing
# the linter or the fixtures sees the failure immediately.

WL12_BUG_FIXTURE = ROOT / "tests" / "fixtures" / "width_lint" / "wl12_dispatch_chain_bug.asm"
WL12_FIXED_FIXTURE = ROOT / "tests" / "fixtures" / "width_lint" / "wl12_dispatch_chain_fixed.asm"


def test_wl12_fixture_bug_caught_on_disk():
    """WL-12 acceptance gate: the bug fixture file produces exactly one
    multipath-label finding for `@after_dispatch`."""
    assert WL12_BUG_FIXTURE.exists(), (
        f"WL-12 fixture missing: {WL12_BUG_FIXTURE}"
    )
    findings = width_lint.lint_file(WL12_BUG_FIXTURE)
    multipath = [f for f in findings if f.rule == "multipath-label"]
    after_dispatch = [f for f in multipath if f.label == "@after_dispatch"]
    assert len(after_dispatch) == 1, (
        f"expected exactly 1 @after_dispatch finding from WL-12 bug fixture, "
        f"got {len(after_dispatch)} multipath findings: "
        f"{[(f.label, f.line) for f in multipath]}"
    )
    f = after_dispatch[0]
    assert "@after_dispatch" in f.message
    assert f.line > 0


def test_wl12_fixture_fixed_passes_on_disk():
    """WL-12 acceptance gate: the fixed fixture file produces zero
    multipath-label findings for `@after_dispatch`."""
    assert WL12_FIXED_FIXTURE.exists(), (
        f"WL-12 fixture missing: {WL12_FIXED_FIXTURE}"
    )
    findings = width_lint.lint_file(WL12_FIXED_FIXTURE)
    multipath = [f for f in findings if f.rule == "multipath-label"]
    after_dispatch = [f for f in multipath if f.label == "@after_dispatch"]
    assert after_dispatch == [], (
        f"fixed WL-12 fixture should have zero @after_dispatch findings; "
        f"got {after_dispatch}"
    )


# --- Check 4: stz long / abs-long operand ----------------------------------

def test_check4_flags_stz_forced_long(tmp_path):
    """`stz f:$7E0008` (forced long) is illegal — must be flagged with the
    helpful 'use lda #0 + sta f:...,x' message."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz f:$7E0008
    """)
    stz = [f for f in findings if f.rule == "stz-long"]
    assert len(stz) == 1, f"expected 1 stz-long finding, got {rules(findings)}"
    assert "no absolute-long form" in stz[0].message
    assert "sta f:$7E0000+addr,x" in stz[0].message
    assert "Illegal addressing mode" in stz[0].message


def test_check4_flags_stz_forced_long_indexed(tmp_path):
    """`stz f:$7E0000 + 8, x` (forced long, indexed) is also illegal."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz f:$7E0000 + 8, x
    """)
    assert [f.rule for f in findings].count("stz-long") == 1


def test_check4_flags_stz_abs_long_literal(tmp_path):
    """`stz $7E0008` — a 24-bit literal ca65 resolves to abs-long — is
    illegal and flagged."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz $7E0008
    """)
    assert [f.rule for f in findings].count("stz-long") == 1


def test_check4_does_not_flag_stz_forced_abs(tmp_path):
    """`stz a:$2102` (forced absolute, 16-bit) is LEGAL — not flagged."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz a:$2102
        stz a:$0F00
    """)
    assert [f for f in findings if f.rule == "stz-long"] == []


def test_check4_does_not_flag_stz_dp_or_abs(tmp_path):
    """`stz <$10`, `stz $10`, `stz $2102` are all legal — not flagged."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz <$10
        stz $10
        stz $2102
    """)
    assert [f for f in findings if f.rule == "stz-long"] == []


def test_check4_override_suppresses(tmp_path):
    """A WIDTH-LINT override on the same line suppresses the stz-long finding."""
    findings = lint(tmp_path, """
        .p816
        .smart
        .segment "CODE"
        stz f:$7E0010                ; WIDTH-LINT: ok — verified safe in fixture
    """)
    assert [f for f in findings if f.rule == "stz-long"] == []


WL_STZ_FIXTURE = ROOT / "tests" / "fixtures" / "width_lint" / "wl_stz_long.asm"


def test_check4_fixture_on_disk():
    """The committed fixture must yield exactly 3 stz-long findings (the 3
    illegal lines), with the 2 legal blocks + the overridden line silent."""
    assert WL_STZ_FIXTURE.exists(), f"fixture missing: {WL_STZ_FIXTURE}"
    findings = width_lint.lint_file(WL_STZ_FIXTURE)
    stz = [f for f in findings if f.rule == "stz-long"]
    assert len(stz) == 3, (
        f"expected exactly 3 stz-long findings (the 3 illegal lines), got "
        f"{[(f.line) for f in stz]}"
    )


# --- Integration: linter runs cleanly on engine/*.asm ----------------------

# The reference's version of this block named seven of ITS engine files. None of
# them exist here, so every case skipped and the integration surface was dead
# while still reporting green.
#
# THIS LIST IS NO LONGER A MIRROR — it is DERIVED, in both of the two ways it
# used to be able to drift:
#
#   * WHICH targets. `make -s print-width-targets` echoes the Makefile's own
#     `WIDTH_LINT_TARGETS`, so the target set has exactly one definition. The
#     shape of that variable — engine, game, vendor/rom, and vendor/probes'
#     first-party probes with the vendored CPU-calibration one filtered out by
#     name — is the Makefile's to state, and this file no longer restates it.
#   * WHICH FILES a target expands to. `width_lint.expand_paths` is the CLI's
#     own expansion, called here directly. Before, the CLI expanded a
#     directory over `*.asm` AND `*.inc` while this list globbed `*.asm` for
#     engine/ and game/ and `*.inc` for vendor/rom only — so every `.inc`
#     under engine/ and game/ was inside the gate and outside the suite. That
#     gap was written down in this comment and closed nowhere.
def _lint_targets():
    # --no-print-directory is LOAD-BEARING, not politeness. This collection
    # runs top-level on a dev box, but inside the landing gate the suite runs
    # UNDER `make test`, and a sub-make inherits `w` through MAKEFLAGS — so
    # without the flag, stdout gains `make[3]: Entering directory '...'` and
    # the split below reads `make[3]:` as a target path. That exact shape
    # took the whole module out of a fresh-clone run once (collection error,
    # 257 tests uncollected). The line filter is the backstop for any other
    # banner a make wrapper might add: a target line never starts with
    # `make`-colon or `make[`.
    out = subprocess.run(
        ["make", "-s", "--no-print-directory", "print-width-targets"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    targets = [t for ln in out.stdout.splitlines()
               if not re.match(r"^\s*make(\[\d+\])?:", ln)
               for t in ln.split()]
    assert targets, "make print-width-targets echoed nothing"
    return [Path(p) for p in width_lint.expand_paths(
        [str(ROOT / t) for t in targets])]


LINT_TARGETS = sorted(_lint_targets())
VENDORED_ASM = {"probe_cpu_ref.asm"}


def test_lint_targets_discovered():
    """The derivation actually finds ASM — guards against a silent no-op.

    If a refactor moves engine/ or game/, this fails instead of leaving
    test_engine_files_runnable parametrized over an empty list (which pytest
    reports as passing).
    """
    assert LINT_TARGETS, "no .asm found under engine/ or game/ — discovery broke"


def test_the_mirror_expands_what_the_target_expands():
    """The asymmetry this derivation exists to close, asserted directly.

    Every extension the CLI reads must be represented here. `.inc` under
    engine/ and game/ is the half that used to be missing: it was in the gate
    and out of the suite, so a width bug in a first-party `.inc` failed
    `make width-check` and passed `pytest`."""
    covered = {p.suffix for p in LINT_TARGETS}
    assert set(width_lint.LINT_EXTENSIONS) <= covered, (
        f"the mirror expands {covered} but the CLI reads "
        f"{width_lint.LINT_EXTENSIONS}")
    engine_game_inc = [p for p in LINT_TARGETS
                       if p.suffix == ".inc"
                       and p.relative_to(ROOT).parts[0] in ("engine", "game")]
    assert engine_game_inc, (
        "no engine/ or game/ .inc in the derived target set — either the tree "
        "genuinely has none (then delete this assertion) or the derivation "
        "regressed to the .asm-only glob it replaced")


def test_the_vendored_exclusion_is_real():
    """Every name in VENDORED_ASM must exist, and the superforge probes must be IN.

    An exclusion list that names a file which has been renamed or deleted
    quietly stops excluding anything — or, worse, a rename of a superforge probe
    into a vendored-looking name would drop it out of the gate with nothing
    to notice. Both directions are asserted here.
    """
    probes = ROOT / "vendor" / "probes"
    for name in VENDORED_ASM:
        assert (probes / name).exists(), (
            f"VENDORED_ASM names {name!r}, which does not exist — the exclusion "
            f"is stale and may be excluding nothing, or the wrong thing")
    covered = {p.name for p in LINT_TARGETS}
    assert {"probe_vblank.asm", "probe_vb2reg.asm"} <= covered, (
        "superforge's own probes dropped out of the width-lint scope: "
        f"{sorted(covered & {'probe_vblank.asm', 'probe_vb2reg.asm'})}")


@pytest.mark.parametrize("path", LINT_TARGETS, ids=lambda p: str(p.name))
def test_engine_files_runnable(path):
    """The linter runs without crashing on every engine/game ASM file."""
    findings = width_lint.lint_file(path)
    # Smoke test: linter completes without crashing. The zero-findings
    # assertion is a separate concern — see test_repo_width_lint_is_clean.
    assert isinstance(findings, list)


def test_repo_width_lint_is_clean():
    """This repo's width-lint baseline is ZERO. Keep it there.

    `make width-check` runs strict (no baseline file). This test is the same
    gate expressed in pytest so a violation fails the suite too, not only the
    Makefile target — a developer running only pytest should still see it.

    Run through `lint_paths`, which is the two-phase whole-tree run the CLI
    does: file-by-file `lint_file` cannot see a cross-file contract violation
    at all, so a per-file loop here would have been a pytest gate that says
    "clean" about a check it never ran.
    """
    all_findings, _stats = width_lint.lint_paths([str(p) for p in LINT_TARGETS])
    offenders: dict = {}
    for d in all_findings:
        offenders.setdefault(str(Path(d.file).relative_to(ROOT)), []).append(d)
    assert not offenders, (
        "width-lint findings introduced (baseline is zero):\n"
        + "\n".join(
            f"  {f}:{d.line} {d.rule} — {d.message}"
            for f, ds in offenders.items()
            for d in ds
        )
    )


def test_lint_file_returns_findings_list():
    """analyze_file returns a populated line model for a real source file."""
    fa = width_lint.analyze_file(LINT_TARGETS[0])
    assert isinstance(fa.lines, list)
    assert len(fa.lines) > 0


# --- Width-state model -----------------------------------------------------

def test_sep_rep_track_runtime_width(tmp_path):
    """Internal: sep #$20 / rep #$20 toggle the analyzer's tracked A-width."""
    src = """
        .p816
        .smart
        .segment "CODE"
        rep #$30
        .a16
        .i16
        nop                          ; A-width should be a16 here
        sep #$20
        .a8
        nop                          ; A-width should be a8 here
    """
    p = tmp_path / "state.asm"
    p.write_text(textwrap.dedent(src).lstrip("\n"))
    fa = width_lint.analyze_file(p)

    nop_lines = [i for i, line in enumerate(fa.lines) if "nop" in line]
    assert len(nop_lines) == 2, f"expected 2 nops, got {len(nop_lines)}"
    assert fa.width_at[nop_lines[0]].a == "a16", \
        f"first nop state.a={fa.width_at[nop_lines[0]].a}"
    assert fa.width_at[nop_lines[1]].a == "a8", \
        f"second nop state.a={fa.width_at[nop_lines[1]].a}"


# --- the gate's real claim: AGREEMENT, not presence
#
# Each hole has a fixture that MUST FIRE its rule and a sibling that MUST
# STAY SILENT. The firing four are minimal cases distilled from the four
# holes the presence-only gate used to walk straight past; the jsr-contract,
# phantom-entry and sep-mismatch shapes were added when the gate was widened.
# Every fixture was falsified from the CLI before these tests were written.

TRUTH_FIXDIR = ROOT / "tests" / "fixtures" / "width_lint"


def _truth_findings(name: str):
    p = TRUTH_FIXDIR / name
    assert p.exists(), f"fixture missing: {p}"
    return width_lint.lint_file(p)


def test_truth_control_fires():
    """The presence check is live: multipath in A, no annotation, fires."""
    fs = _truth_findings("control_fires.asm")
    assert [f.rule for f in fs] == ["multipath-label"]
    assert fs[0].label == "shared"
    assert fs[0].severity == "error"


def test_truth_reverse_is_control_plus_one_line():
    """The headline case: hole_reverse is control_fires plus ONE code line —
    the wrong bare `.a8`. Under the presence-only gate that one line turned a
    firing finding into silence; under this gate both fire."""
    def code_lines(name):
        return [
            l for l in (TRUTH_FIXDIR / name).read_text().splitlines()
            if l.strip() and not l.strip().startswith(";")
        ]
    control = code_lines("control_fires.asm")
    reverse = code_lines("hole_reverse.asm")
    assert len(reverse) == len(control) + 1
    i = next(k for k, (a, b) in enumerate(zip(control, reverse)) if a != b)
    assert reverse[i].strip() == ".a8", f"the added line is {reverse[i]!r}"
    assert reverse[:i] == control[:i]
    assert reverse[i + 1:] == control[i:]


def test_truth_hole1_reverse_fires():
    """Hole 1: a bare annotation contradicted by an arrival FIRES (the old
    gate bailed at 'an annotation exists')."""
    fs = _truth_findings("hole_reverse.asm")
    assert [f.rule for f in fs] == ["annotation-contradicts-arrival"]
    f = fs[0]
    assert f.label == "shared"
    assert f.severity == "error"
    assert "bare .a8" in f.message
    assert "a16" in f.message


def test_truth_hole1_sibling_forced_silent():
    """The same multipath arrivals with a FORCED narrowing (sep + directive)
    stay silent — legal from any arriving width."""
    assert _truth_findings("hole_reverse_fixed.asm") == []


def test_truth_hole3_axis_fires():
    """Hole 3: an annotation on the non-ambiguous axis does not cover the
    ambiguous one."""
    fs = _truth_findings("hole_axis.asm")
    assert [f.rule for f in fs] == ["annotation-wrong-axis"]
    assert fs[0].label == "shared"
    assert "other axis" in fs[0].message


def test_truth_hole3_sibling_silent():
    assert _truth_findings("hole_axis_fixed.asm") == []


def test_truth_hole2_unknown_fires_as_warn_and_gates():
    """Hole 2: mixed known/UNKNOWN arrivals on an un-annotated label are
    reported (severity=warn) instead of silently dropped — and they still
    gate: main() exits 1."""
    fs = _truth_findings("hole_unknown_noann.asm")
    assert [f.rule for f in fs] == ["unknown-arrival"]
    assert fs[0].severity == "warn"
    assert fs[0].label == "shared"
    rc = width_lint.main(
        [str(TRUTH_FIXDIR / "hole_unknown_noann.asm"), "--quiet"])
    assert rc == 1, "a warn-severity finding must still gate"


def test_truth_hole2_sibling_annotated_silent():
    assert _truth_findings("hole_unknown_annotated.asm") == []


def test_truth_rule3_sep_annotation_mismatch_fires():
    """Rule 3: sep/rep + directive must agree with each other."""
    fs = _truth_findings("sep_ann_mismatch_fires.asm")
    assert [f.rule for f in fs] == ["sep-annotation-mismatch"]
    assert fs[0].label == "shared"
    assert "forces a8" in fs[0].message


def test_truth_hole4_jsr_contract_fires():
    """Hole 4, firing half: a jsr site is a REAL arrival, checked against
    the callee's bare entry annotation (in-file caller/callee contract)."""
    fs = _truth_findings("jsr_contract_fires.asm")
    assert [f.rule for f in fs] == ["annotation-contradicts-arrival"]
    assert fs[0].label == "helper8"
    assert "(call)" in fs[0].message, "the arrival should be named a call"


def test_truth_hole4_jsr_sibling_silent():
    """A caller that narrows before the call honours the contract."""
    assert _truth_findings("jsr_contract_silent.asm") == []


def test_truth_hole4_entry_phantom_silent():
    """Hole 4, phantom half: an entry label preceded by a symbol assignment
    and a `:  rts` return keeps its documented entry annotation without a
    phantom fall-through contradicting it."""
    assert _truth_findings("entry_phantom_silent.asm") == []


def test_truth_entry_phantom_guard_guards(monkeypatch):
    """entry_phantom_silent is silent BECAUSE the fall-through model skips
    symbol assignments and reads `:  rts` as a return — not vacuously.
    Restoring the old walk (stop at the first non-blank/comment/label/
    directive line, verbatim) brings the phantom arrival back, and it must
    then contradict the documented entry annotation."""
    def old_walk(lines, idx):
        for i in range(idx - 1, -1, -1):
            if width_lint.RE_COMMENT_OR_BLANK.match(lines[i]):
                continue
            if width_lint.RE_LABEL.match(lines[i]):
                continue
            if width_lint.RE_DIRECTIVE.match(lines[i]):
                continue
            return lines[i]
        return None

    monkeypatch.setattr(width_lint, "_previous_real_instruction", old_walk)
    fs = width_lint.lint_file(TRUTH_FIXDIR / "entry_phantom_silent.asm")
    assert any(
        f.rule == "annotation-contradicts-arrival"
        and f.label == "entry_documented"
        for f in fs
    ), (
        "the guard no longer guards: with the old fall-through walk restored, "
        "the phantom arrival should contradict the entry annotation — if this "
        "fails, the fixture is silent for some other reason and proves nothing"
    )


def test_truth_summary_line_states_what_it_checked(capsys):
    """The summary says WHAT it checked, not just how much it found — a count
    with no subject is unreadable when the gate goes red."""
    rc = width_lint.main(
        [str(TRUTH_FIXDIR / "hole_reverse_fixed.asm"), "--summary"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "checked:" in out
    assert "jsr" in out          # the arrival kinds are named
    assert "stz-long" in out     # ... through to the last check
    # The file declares no contract, so the cross-file pass did nothing here
    # and the summary must SAY it did nothing. This is the line that used to
    # read "cross-file callers invisible" as a flat statement of the limit;
    # now the limit is conditional on declaring, so the summary reports the
    # condition instead of asserting the limit.
    assert "contracts: 0 declared" in out
    assert "cross-file pass is inert" in out


def test_truth_summary_line_counts_a_pass_that_did_work(capsys):
    """...and the same line must say so when the pass DID check something.

    A disarmed run and an armed one have to be distinguishable from the
    summary alone, or "0 finding(s)" reads the same either way."""
    rc = width_lint.main([
        str(TRUTH_FIXDIR / "contract_callee.asm"),
        str(TRUTH_FIXDIR / "contract_caller_ok.asm"), "--summary"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "contracts: 3 declared" in out
    assert "cross-file call-site width(s) compared" in out
    assert "cross-file pass is inert" not in out


# --- Check 5: the routine contract and the cross-file pass ------------------
#
# The hole CLAUDE.md rule 6 states openly — "callers in other files are
# invisible in both directions... checked only by the emulator" — closed for
# the routines that DECLARE. Every fixture below is a real file pair on disk,
# because a cross-file check tested against a single tmp file is not testing
# the thing it claims to.

CONTRACT_CALLEE = TRUTH_FIXDIR / "contract_callee.asm"
CONTRACT_OK = TRUTH_FIXDIR / "contract_caller_ok.asm"
CONTRACT_BAD = TRUTH_FIXDIR / "contract_caller_bad.asm"
CONTRACT_MALFORMED = TRUTH_FIXDIR / "contract_malformed.asm"


def test_contract_fixtures_exist():
    for p in (CONTRACT_CALLEE, CONTRACT_OK, CONTRACT_BAD, CONTRACT_MALFORMED):
        assert p.exists(), f"fixture missing: {p}"


def test_a_declared_callee_called_at_the_wrong_width_fires(capsys):
    """THE HEADLINE: a caller in ANOTHER file arriving wrong, named at both
    ends. Three call sites, four axes wrong between them."""
    findings, stats = width_lint.lint_paths(
        [str(CONTRACT_CALLEE), str(CONTRACT_BAD)])
    xf = [f for f in findings if f.rule == "cross-file-width"]
    assert len(xf) == 4, [f.message for f in xf]
    # Both ends named: the caller's file:line is the finding's own location,
    # and the callee's declaration is cited inside the message.
    for f in xf:
        assert f.file == str(CONTRACT_BAD)
        assert "contract_callee.asm:" in f.message
        assert f.label in ("fx_needs_a16", "fx_needs_a8")
    # ...and both directions are represented, so a one-way check cannot pass.
    assert any("arrives in .a8" in f.message for f in xf)
    assert any("arrives in .a16" in f.message for f in xf)
    assert any("arrives in .i8" in f.message for f in xf)


def test_a_correct_cross_file_pair_is_clean():
    """The control. Same declarations, every arrival right — no finding, and
    the sites were really compared rather than skipped."""
    findings, stats = width_lint.lint_paths(
        [str(CONTRACT_CALLEE), str(CONTRACT_OK)])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.declared == 3
    assert stats.sites_checked > 0, "clean, but nothing was checked"
    assert stats.sites_unprovable == 0


def test_an_unknown_declaration_accepts_any_arrival():
    """`A? I?` means the routine establishes its own widths, so no arrival is
    a finding — the ok fixture calls it from A16 and from A8."""
    findings, _ = width_lint.lint_paths(
        [str(CONTRACT_CALLEE), str(CONTRACT_OK)])
    assert [f for f in findings if f.label == "fx_any_width"] == []
    table, errs, _stats, _lf = width_lint.collect_contracts(
        [str(CONTRACT_CALLEE)])
    assert table["fx_any_width"].entry_a == width_lint.UNKNOWN
    assert table["fx_any_width"].entry_i == width_lint.UNKNOWN


def test_unknown_is_a_statement_not_an_opt_out():
    """...and the callee has to EARN it: `A?` with no sep/rep before the
    first width-sensitive instruction is its own finding, or one character
    would opt any routine out of the whole pass."""
    findings = width_lint.lint_file(CONTRACT_MALFORMED)
    unk = [f for f in findings
           if f.rule == "contract-unknown-not-established"]
    assert [f.label for f in unk] == ["fx_unknown_never_set"]
    assert "lda #$12" in unk[0].message


def test_a_malformed_declaration_is_its_own_finding():
    """A header that reads as a checked contract while nothing checks it is
    worse than no header. One finding per broken routine — a cascade would
    make the count useless as a diagnosis."""
    findings = width_lint.lint_file(CONTRACT_MALFORMED)
    got = {(f.label, f.rule) for f in findings}
    assert got == {
        ("fx_bad_slot", "contract-malformed"),
        ("fx_missing_slot", "contract-malformed"),
        ("fx_half_axis", "contract-malformed"),
        ("fx_bad_token", "contract-malformed"),
        ("fx_wrong_name", "contract-malformed"),
        ("fx_directive_drift", "contract-directive-mismatch"),
        ("fx_unknown_never_set", "contract-unknown-not-established"),
    }, sorted(got)


def test_a_malformed_declaration_never_becomes_a_checking_basis():
    """It is reported AND withheld: a half-parsed contract must not be what a
    caller in another file is checked against."""
    table, errs, stats, _lf = width_lint.collect_contracts(
        [str(CONTRACT_MALFORMED)])
    for name in ("fx_bad_slot", "fx_missing_slot", "fx_half_axis",
                 "fx_bad_token", "fx_wrong_name"):
        assert name not in table, name
    assert stats.declared == 2      # only the two well-formed ones


def test_the_pass_is_inert_where_the_callee_does_not_declare(tmp_path):
    """Property (a), asserted rather than assumed: an UNDECLARED callee is
    exactly as unchecked as before this pass existed. That is what let this
    land on a tree whose width-lint baseline is zero."""
    (tmp_path / "callee.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        plain_callee:
            .a16
            .i16
            rts
    """).lstrip("\n"))
    (tmp_path / "caller.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        plain_caller:
            .a8
            .i8
            jsr plain_callee
            rts
    """).lstrip("\n"))
    findings, stats = width_lint.lint_paths(
        [str(tmp_path / "callee.asm"), str(tmp_path / "caller.asm")])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.declared == 0 and stats.sites_checked == 0


def test_an_unprovable_arrival_is_counted_not_fired(tmp_path):
    """The other half of "no flood": where the CALLER's own width is unknown
    the pass cannot prove anything, so it counts instead of firing. Firing
    would reintroduce the baseline by the back door."""
    (tmp_path / "caller.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        unprovable_caller:
            jsr fx_needs_a16
            rts
    """).lstrip("\n"))
    findings, stats = width_lint.lint_paths(
        [str(CONTRACT_CALLEE), str(tmp_path / "caller.asm")])
    assert [f for f in findings if f.rule == "cross-file-width"] == []
    assert stats.sites_unprovable == 2      # both axes, one site


def test_a_same_file_call_is_left_to_check_one(tmp_path):
    """No double-counting: check 1 already models an in-file jsr as an
    arrival, so the contract pass must not report the same site again."""
    (tmp_path / "both.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        ; CONTRACT local_callee
        ;   entry:    A16 I16
        ;   exit:     A16 I16
        ;   clobbers: A
        local_callee:
            .a16
            .i16
            rts
        local_caller:
            .a8
            .i16
            jsr local_callee
            rts
    """).lstrip("\n"))
    findings = width_lint.lint_file(tmp_path / "both.asm")
    assert [f.rule for f in findings if f.rule == "cross-file-width"] == []
    # check 1 sees it, and says so in its own vocabulary
    assert any(f.rule == "annotation-contradicts-arrival" for f in findings)


def test_an_ambiguous_bare_name_is_not_resolved(tmp_path):
    """A name several files define cannot be resolved by a whole-tree run.
    Checking a caller against a declaration it may not link against is the
    indirect-evidence shape, and it can fail in either direction. This tree's
    own instance was three `cam_arm`s — sh2_cam's, shg_cam's and shp_cam's —
    and the way it was bought back was a rename, not a smarter linter: the
    declaring one is `sh2_arm` now. The synthetic twins below keep the shape
    under test whether or not the tree still has an instance of it."""
    for n in ("a", "b"):
        (tmp_path / f"def_{n}.asm").write_text(textwrap.dedent(f"""
            .p816
            .smart
            .segment "CODE"
            ; CONTRACT twin_{n}
            ;   entry:    A16 I16
            ;   exit:     A16 I16
            ;   clobbers: A
            twin_{n}:
                .a16
                .i16
            shared_name:
                .a16
                rts
        """).lstrip("\n"))
    (tmp_path / "caller.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        amb_caller:
            .a8
            .i16
            jsr shared_name
            rts
    """).lstrip("\n"))
    # Only def_a declares `shared_name`; def_b defines a label of the same
    # name, which is enough to make the call unresolvable.
    s = (tmp_path / "def_a.asm").read_text().replace(
        "; CONTRACT twin_a", "; CONTRACT shared_name").replace(
        "twin_a:\n    .a16\n    .i16\n", "")
    (tmp_path / "def_a.asm").write_text(s)
    findings, stats = width_lint.lint_paths(
        [str(tmp_path / "def_a.asm"), str(tmp_path / "def_b.asm"),
         str(tmp_path / "caller.asm")])
    assert [f for f in findings if f.rule == "cross-file-width"] == []
    assert stats.sites_ambiguous == 1
    assert stats.ambiguous_names == {"shared_name"}


def test_a_global_scope_qualified_call_is_seen(tmp_path):
    """`jsr ::name` is ca65's explicit global-scope form and this tree writes
    it wherever a routine is expanded inside a scene's `.scope` — about ninety
    call sites. It names the same routine a bare `jsr` does, so the cross-file
    pass has to see it: while it did not, those calls were neither checked nor
    counted as skipped, and the summary reported a reach it did not have."""
    (tmp_path / "callee.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        ; CONTRACT narrow_entry
        ;   entry:    A8 I16
        ;   exit:     A8 I16
        ;   clobbers: A
        narrow_entry:
            .a8
            .i16
            rts
    """).lstrip("\n"))
    (tmp_path / "caller.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        wide_caller:
            .a16
            .i16
            jsr ::narrow_entry
            rts
    """).lstrip("\n"))
    findings, stats = width_lint.lint_paths(
        [str(tmp_path / "callee.asm"), str(tmp_path / "caller.asm")])
    xf = [f for f in findings if f.rule == "cross-file-width"]
    assert len(xf) == 1, [width_lint.format_finding(f) for f in findings]
    assert xf[0].label == "narrow_entry"
    assert "A8" in xf[0].message and ".a16" in xf[0].message
    # and the same call, correctly narrowed, is CHECKED rather than skipped
    (tmp_path / "caller.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        ok_caller:
            .a8
            .i16
            jsr ::narrow_entry
            rts
    """).lstrip("\n"))
    findings, stats = width_lint.lint_paths(
        [str(tmp_path / "callee.asm"), str(tmp_path / "caller.asm")])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.sites_checked == 2          # both axes of the one call
    assert stats.callees == {"narrow_entry"}


def test_a_global_scope_qualified_call_in_the_defining_file_is_check_1s(tmp_path):
    """Stripping the `::` also puts a same-file `jsr ::name` back under check
    1, where it belongs — the cross-file pass must not double-count an arrival
    the label check already models."""
    (tmp_path / "one.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        ; CONTRACT local_callee
        ;   entry:    A16 I16
        ;   exit:     A16 I16
        ;   clobbers: A
        local_callee:
            .a16
            .i16
            rts
        local_caller:
            .a8
            .i16
            jsr ::local_callee
            rts
    """).lstrip("\n"))
    findings, stats = width_lint.lint_paths([str(tmp_path / "one.asm")])
    assert [f for f in findings if f.rule == "cross-file-width"] == []
    assert stats.sites_checked == 0
    assert any(f.rule == "annotation-contradicts-arrival" for f in findings)


def test_a_scope_qualified_contract_binds_its_last_segment(tmp_path):
    """`microzero::sm_nmi_hook` is how a name 37 rails share can still
    declare. The qualifier keys it uniquely; the label it binds is the last
    segment."""
    (tmp_path / "q.asm").write_text(textwrap.dedent("""
        .p816
        .smart
        .segment "CODE"
        ; CONTRACT some_rail::hook
        ;   entry:    A8 I16
        ;   exit:     A8 I16
        ;   clobbers: A
        hook:
            .a8
            .i16
            rts
    """).lstrip("\n"))
    table, errs, stats, _lf = width_lint.collect_contracts(
        [str(tmp_path / "q.asm")])
    assert errs == [], [f.message for f in errs]
    assert "some_rail::hook" in table
    assert table["some_rail::hook"].entry_a == "a8"


def test_the_contract_and_the_label_directive_cannot_drift():
    """A declaration is documentation first, and documentation drifts. Inside
    the defining file the two are pinned to each other."""
    findings = width_lint.lint_file(CONTRACT_MALFORMED)
    drift = [f for f in findings if f.rule == "contract-directive-mismatch"]
    assert [f.label for f in drift] == ["fx_directive_drift"]
    assert ".a8" in drift[0].message and "A16" in drift[0].message


def test_the_live_tree_declares_and_the_pass_is_armed():
    """The pilot, asserted against the real tree: the three migrated features
    plus their callers declare, and the cross-file pass really compares call
    sites. A contract set that stopped being read would leave this at zero
    while every other test still passed."""
    # One derivation, one hardening: _lint_targets carries the
    # --no-print-directory + banner-filter treatment a sub-make needs, and a
    # second raw invocation here would fail under the landing gate the same
    # way the collection-time one once did.
    files = [str(p) for p in LINT_TARGETS]
    table, errs, stats, label_files = width_lint.collect_contracts(files)
    assert errs == [], [f.message for f in errs]
    for name in ("stream_arm", "stream_tick", "stream_nmi_dispatch",
                 "sh2_arm", "sh2_tick", "sh2_advance", "sh2_region",
                 "TS_STEP", "TS_SCALED"):
        assert name in table, f"{name} lost its contract"
    findings, stats = width_lint.lint_paths(files)
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.sites_checked >= 12, (
        f"the cross-file pass compared only {stats.sites_checked} widths — "
        f"it has been disarmed")


# --- Check 6: the declaration is MANDATORY on the feature layer -------------
#
# Check 5's optional grammar, ratcheted. Every fixture here is a small TREE
# rather than a file, because "exported" is a relation between files and a
# single-file fixture cannot express it — the same reason check 5's fixtures
# are file pairs on disk.


def _plant_feature_tree(root: Path, *, declared: bool = False,
                        override: str = "") -> tuple[Path, Path]:
    """Plant one exported feature routine and one caller in another file.

    `engine/features/**` is matched on path COMPONENTS, so a tmp tree built
    under those names is inside the check's scope exactly as the repo's own
    files are.
    """
    feat = root / "engine" / "features" / "plant"
    rail = root / "game" / "plant_rail"
    feat.mkdir(parents=True)
    rail.mkdir(parents=True)

    header = ""
    if declared:
        header = (
            "; CONTRACT plant_export\n"
            ";   entry:    A16 I16\n"
            ";   exit:     A16 I16\n"
            ";   clobbers: A\n"
        )
    (feat / "plant.asm").write_text(
        ".p816\n"
        ".smart\n"
        '.segment "CODE"\n'
        "\n"
        "; CONTRACT plant_declared\n"
        ";   entry:    A16 I16\n"
        ";   exit:     A16 I16\n"
        ";   clobbers: A\n"
        "plant_declared:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
        "\n"
        + override
        + header
        + "plant_export:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
    )
    (rail / "main.asm").write_text(
        ".p816\n"
        ".smart\n"
        '.segment "CODE"\n'
        "plant_caller:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr plant_declared\n"
        "    jsr plant_export\n"
        "    rts\n"
    )
    return feat / "plant.asm", rail / "main.asm"


def test_an_undeclared_exported_feature_routine_fires(tmp_path, capsys):
    """THE PLANT. A new export with no header, and the finding names both
    ends: the routine and its own file (where the fix goes) plus the
    cross-file caller that is the evidence it is exported at all."""
    feat, rail = _plant_feature_tree(tmp_path)
    findings, stats = width_lint.lint_paths([str(feat), str(rail)])
    missing = [f for f in findings if f.rule == "contract-missing"]
    assert [f.label for f in missing] == ["plant_export"], [
        width_lint.format_finding(f) for f in findings]
    f = missing[0]
    label_line = feat.read_text().splitlines().index("plant_export:") + 1
    call_line = 1 + next(
        n for n, ln in enumerate(rail.read_text().splitlines())
        if "jsr plant_export" in ln)
    assert f.file == str(feat)
    assert f.line == label_line, f.line   # the label, not the call site
    assert f"{rail}:{call_line}" in f.message, f.message
    assert "; CONTRACT plant_export" in f.message
    # The sibling that DOES declare is silent, so the check is reading the
    # declaration rather than the export.
    assert [g for g in findings if g.label == "plant_declared"] == []
    # ...and the summary carries the ratchet's state with its denominator.
    assert stats.exported_examined == 2
    assert stats.exported_undeclared == 1
    width_lint.main([str(feat), str(rail), "--summary"])
    out = capsys.readouterr().out
    assert "2 uniquely-named routine(s) under engine/features/**" in out
    assert "1 of them carry no contract" in out


def test_the_same_export_declared_is_clean(tmp_path):
    """The control: one line of header is the whole difference between the
    plant and a clean tree."""
    feat, rail = _plant_feature_tree(tmp_path, declared=True)
    findings, stats = width_lint.lint_paths([str(feat), str(rail)])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.exported_examined == 2, "clean, but nothing was examined"
    assert stats.exported_undeclared == 0


def test_the_live_tree_is_at_zero_and_the_ratchet_is_armed():
    """(a) asserted on the real tree: the flip is a RATCHET, not a migration.

    The denominator is asserted with the count — `0 undeclared` out of
    nothing examined is a broken scope reading as a clean gate.
    """
    files = [str(p) for p in LINT_TARGETS]
    findings, stats = width_lint.lint_paths(files)
    assert [f for f in findings if f.rule == "contract-missing"] == []
    assert stats.exported_undeclared == 0
    assert stats.exported_examined >= 200, (
        f"only {stats.exported_examined} exported feature routine(s) "
        f"examined — the scope has stopped matching the tree")


def test_a_game_scene_routine_is_out_of_scope(tmp_path):
    """(b) the stated ceiling: the requirement is the FEATURE layer's. A
    rail's own scene routine, exported and undeclared, is not a finding."""
    (tmp_path / "game" / "rail_a").mkdir(parents=True)
    (tmp_path / "game" / "rail_b").mkdir(parents=True)
    (tmp_path / "game" / "rail_a" / "scene.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "scene_helper:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
    )
    (tmp_path / "game" / "rail_b" / "main.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "scene_caller:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr scene_helper\n"
        "    rts\n"
    )
    findings, stats = width_lint.lint_paths([
        str(tmp_path / "game" / "rail_a" / "scene.asm"),
        str(tmp_path / "game" / "rail_b" / "main.asm")])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.exported_examined == 0


def test_a_name_several_features_define_is_exempt_and_counted(tmp_path):
    """(c) the same exemption check 5 makes, for the same reason: a caller of
    a bare name two files define cannot be resolved, so a declaration there
    would buy no check. Counted as shared-name, never fired."""
    for feature in ("alpha", "beta"):
        d = tmp_path / "engine" / "features" / feature
        d.mkdir(parents=True)
        (d / f"{feature}.asm").write_text(
            ".p816\n.smart\n"
            '.segment "CODE"\n'
            "floor_arm:\n"
            "    .a16\n"
            "    .i16\n"
            "    rts\n"
        )
    rail = tmp_path / "game" / "rail"
    rail.mkdir(parents=True)
    (rail / "main.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "rail_caller:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr floor_arm\n"
        "    rts\n"
    )
    findings, stats = width_lint.lint_paths([
        str(tmp_path / "engine" / "features" / "alpha" / "alpha.asm"),
        str(tmp_path / "engine" / "features" / "beta" / "beta.asm"),
        str(rail / "main.asm")])
    assert [f for f in findings if f.rule == "contract-missing"] == []
    assert stats.exported_examined == 0
    assert stats.exported_shared == 2


def test_a_feature_routine_nobody_else_calls_is_not_exported(tmp_path):
    """Not every label in a feature is an export. A routine only its own file
    calls is check 1's, and demanding a header for it would be noise."""
    d = tmp_path / "engine" / "features" / "solo"
    d.mkdir(parents=True)
    (d / "solo.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "; CONTRACT solo_entry\n"
        ";   entry:    A16 I16\n"
        ";   exit:     A16 I16\n"
        ";   clobbers: A\n"
        "solo_entry:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr solo_private\n"
        "    rts\n"
        "solo_private:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
    )
    findings, stats = width_lint.lint_paths([str(d / "solo.asm")])
    assert findings == [], [width_lint.format_finding(f) for f in findings]
    assert stats.exported_examined == 0


def test_the_override_suppresses_and_a_bare_one_does_not(tmp_path):
    """The escape hatch, with the reason the convention demands everywhere."""
    feat, rail = _plant_feature_tree(
        tmp_path, override="; WIDTH-LINT: ok — a probe hook, entry width is "
                           "the caller's by design\n")
    findings, _ = width_lint.lint_paths([str(feat), str(rail)])
    assert [f for f in findings if f.rule == "contract-missing"] == []

    bare = tmp_path / "bare"
    bare.mkdir()
    feat2, rail2 = _plant_feature_tree(bare, override="; WIDTH-LINT: ok\n")
    findings2, _ = width_lint.lint_paths([str(feat2), str(rail2)])
    assert [f.label for f in findings2 if f.rule == "contract-missing"] == [
        "plant_export"]


def test_a_qualified_call_still_counts_as_an_export(tmp_path):
    """A feature routine reached only as `jsr scene::name` — the form ca65
    needs when the feature body is included inside a scene's `.scope` — is
    exported. Indexing the bare name alone would read it as dead code and
    exempt eleven of this tree's routines from the requirement."""
    d = tmp_path / "engine" / "features" / "qual"
    d.mkdir(parents=True)
    (d / "qual.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "qual_commit:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
    )
    rail = tmp_path / "game" / "rail"
    rail.mkdir(parents=True)
    (rail / "main.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "qual_caller:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr play::qual_commit\n"
        "    rts\n"
    )
    findings, stats = width_lint.lint_paths(
        [str(d / "qual.asm"), str(rail / "main.asm")])
    assert [f.label for f in findings if f.rule == "contract-missing"] == [
        "qual_commit"]
    assert stats.exported_examined == 1


def test_a_malformed_contract_is_not_also_reported_as_missing(tmp_path):
    """One violation, one diagnosis. A header that fails to parse is already
    `contract-malformed`; adding `contract-missing` on top would make the
    count useless as a diagnosis and read as two defects."""
    d = tmp_path / "engine" / "features" / "broke"
    d.mkdir(parents=True)
    (d / "broke.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "; CONTRACT broke_entry\n"
        ";   entry:    A16 I16\n"
        ";   clobbers: A\n"
        "broke_entry:\n"
        "    .a16\n"
        "    .i16\n"
        "    rts\n"
    )
    rail = tmp_path / "game" / "rail"
    rail.mkdir(parents=True)
    (rail / "main.asm").write_text(
        ".p816\n.smart\n"
        '.segment "CODE"\n'
        "broke_caller:\n"
        "    .a16\n"
        "    .i16\n"
        "    jsr broke_entry\n"
        "    rts\n"
    )
    findings, _ = width_lint.lint_paths(
        [str(d / "broke.asm"), str(rail / "main.asm")])
    assert rules(findings) == ["contract-malformed"], [
        width_lint.format_finding(f) for f in findings]
