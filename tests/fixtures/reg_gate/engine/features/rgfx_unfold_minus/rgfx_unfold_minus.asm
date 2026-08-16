; FIRES (expression fold): `sta a:$2107 - 1` IS a MOSAIC write. The sharpest spelling
; in the reference set (probe fp3_minus): before the fold this produced
; ZERO findings OF ANY KIND, because the address rule permits $2107 as an io
; literal and the reg rule's fold returned None.
.p816
.smart

.segment "CODE"
rgfx_unfold_minus_go:
    sep #$20
    .a8
    lda #$11
    sta a:$2107 - 1
    rts
