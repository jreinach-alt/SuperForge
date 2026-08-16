; FIRES (expression fold): `sta a:$2100 | $0006` — a bitwise term, not additive.
; Before this rule: silent (probe fp4_or).
.p816
.smart

.segment "CODE"
rgfx_unfold_or_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2100 | $0006
    rts
