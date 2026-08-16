; Rule 3: a sep/rep + directive pair must agree with itself.
; `sep #$20` forces A8; the `.a16` behind it claims A16 — one of the two
; is wrong (a typo class the presence check could never see).
; MUST FIRE [sep-annotation-mismatch]. Silent sibling: hole_reverse_fixed.
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
    sep #$20                    ; forces A8...
    .a16                        ; ...but the directive claims A16
    lda #$1234
    rts
