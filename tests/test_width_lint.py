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
# while still reporting green. Discover this repo's ASM instead: the list can
# never go stale, and LINT_TARGETS below asserts it is non-empty so the suite
# fails loudly rather than silently covering nothing.
#
# vendor/ is frozen vendored material and stays out — except that
# vendor/probes/ is not all vendored: probe_vblank.asm and probe_vb2reg.asm are
# fresh SuperForge code, allocator-mapped, no-literals-gated, written here.
# They belong in the gate. Only the CPU-calibration probe is excluded, BY NAME,
# because it is an instrumented copy of frozen reference sources — so a probe
# added later is covered by default rather than silently escaping.
#
# vendor/rom/ is in for the same reason and is the one entry that is `.inc`
# rather than `.asm`: it is first-party, every rail assembles against it, and
# it holds sf_asm.inc — the shared macro header, i.e. the one file where a
# width mistake would be written once and assembled into every ROM expanding
# it. NOTE the asymmetry this makes explicit: the Makefile hands DIRECTORIES to
# the CLI, which expands each to `*.asm` AND `*.inc`, while this list globs
# `*.asm` only — so engine/ and game/ `.inc` files are covered by the target
# and not by this test. Naming vendor/rom's `.inc` files here closes the gap
# for the header without pretending the general one is closed.
#
# This list mirrors WIDTH_LINT_TARGETS in the Makefile — keep them together.
VENDORED_ASM = {"probe_cpu_ref.asm"}
LINT_TARGETS = sorted(
    [p for d in ("engine", "game") for p in (ROOT / d).rglob("*.asm")]
    + [p for p in (ROOT / "vendor" / "probes").glob("*.asm")
       if p.name not in VENDORED_ASM]
    + sorted((ROOT / "vendor" / "rom").glob("*.inc"))
)


def test_lint_targets_discovered():
    """The discovery glob actually finds ASM — guards against a silent no-op.

    If a refactor moves engine/ or game/, this fails instead of leaving
    test_engine_files_runnable parametrized over an empty list (which pytest
    reports as passing).
    """
    assert LINT_TARGETS, "no .asm found under engine/ or game/ — discovery broke"


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
    Makefile target — CI runs both, but a developer running only pytest should
    still see it.
    """
    offenders = {
        str(p.relative_to(ROOT)): width_lint.lint_file(p)
        for p in LINT_TARGETS
    }
    offenders = {k: v for k, v in offenders.items() if v}
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
    assert "cross-file callers invisible" in out  # the limitation is stated
