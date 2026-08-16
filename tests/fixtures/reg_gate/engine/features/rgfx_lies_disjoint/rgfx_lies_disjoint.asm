; reg-gate fixture (SILENT, item 5): the owner writes the SEVEN registers it
; did not open, and none of the two it did. Nothing is co-written.
.p816
rgfx_lies_disjoint_enter:
    sep #$20
    .a8
    lda #$60
    sta a:$2107                 ; BG1SC — owned, not opened, owner-written
    sta a:$2108                 ; BG2SC
    lda #$00
    sta a:$210B                 ; BG12NBA
    sta a:$210D                 ; BG1HOFS
    sta a:$210E                 ; BG1VOFS
    sta a:$210F                 ; BG2HOFS
    sta a:$2110                 ; BG2VOFS
    rts
