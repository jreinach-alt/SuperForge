; FIRES: `_window_desc`'s PLURAL branch had no test.
;
; Its singular branch is asserted at test_reg_gate.py's ambiguity test, and
; the singular literal duplicated `_site_label` by hand — two sources for
; one sentence, which is how the two drift. `_site_label` now has this one
; caller and the plural branch has this fixture.
;
; Three writes whose ports will not fold share the standalone override's
; ±3-line window. None can be named by rule 1 (an unfoldable write has no
; port to name), so rule 3 refuses, and the refusal must say "3 operands
; whose port cannot be folded" — plural, counted, not repeated three times.
.p816
.smart

.segment "CODE"
rgfx_ov_unfold_triple_go:
    sep #$20
    .a8
    lda #$01
    ; REG-LINT: ok — which of the three is this about?
    sta a:$2100 + STRIDE
    sta a:$2105 + STRIDE
    sta a:$2107 + STRIDE
    rts
