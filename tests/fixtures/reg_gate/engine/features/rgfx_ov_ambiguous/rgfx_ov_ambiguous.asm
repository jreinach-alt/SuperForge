; FIRES (override rule 3): a STANDALONE override whose ±3-line window holds
; would-be findings for TWO DIFFERENT ports. Which one it excuses cannot be
; told from the text, so it excuses neither and says so.
.p816
.smart

.segment "CODE"
rgfx_ov_ambiguous_go:
    sep #$20
    .a8
    lda #$01
    ; REG-LINT: ok — one of these is safe by construction, but which?
    sta a:$2101
    sta a:$2106
    rts
