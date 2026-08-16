; reg-gate fixture (FIRES): boot writes BGMODE with no global declaring it —
; the globals'-union context refuses.
.p816
gfix_bad_boot:
    sep #$20
    .a8
    lda #1
    sta a:$2105                 ; BGMODE — globals declare nothing: FINDING
    rts
