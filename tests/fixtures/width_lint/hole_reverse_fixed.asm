; Silent sibling of hole_reverse: the same multipath arrivals resolved the
; correct way — a FORCED narrowing (sep + directive), legal from any
; arriving width. MUST STAY SILENT. Also the silent sibling for
; sep_ann_mismatch_fires (the pair here agrees with itself).
.p816
.smart
.segment "CODE"
start:
    rep #$20
    .a16
    lda #$1234
    beq shared                  ; arrives A16
    sep #$20
    .a8
    lda #$12
    bra shared                  ; arrives A8
shared:
    sep #$20                    ; forced narrowing: correct from A8 or A16
    .a8
    lda #$34
    rts
