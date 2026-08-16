; FIRES (expression fold): `sta a:$2100 + BG_SLOT` — the base reaches io but the
; offset is a symbol this file cannot fold. Reporting the BASE would be the
; laundering: $2100 is INIDISP, the effective port is not.
; Before this rule: silent (probe rg_unfoldable_fires).
.p816
.smart
.import BG_SLOT

.segment "CODE"
rgfx_unfold_sym_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2100 + BG_SLOT
    rts
