; reg-gate fixture (FIRES): the DISCRIMINATING sibling for s6 and
; s11 -- identical writes, and a closure that claims nothing.
;
; Without it, "the data/latch half is not narrowed" is asserted only by files
; that exit 0, and a tier that stopped examining data ports entirely would
; keep them green. This one says the silence next door is caused by the CLAIM.
.p816
s12_enter:
    sep #$20
    .a8
    lda #$00
    sta a:$2121                 ; CGADD — latch of an unclaimed resource
    lda #$7F
    sta a:$2122                 ; CGDATA — data port, nothing claims cgram
    rts
