; Silent sibling of hole_unknown_noann: the same mixed known/UNKNOWN
; arrivals with the label annotated. The bare `.a16` agrees with the known
; arrival and documents the unknown one. MUST STAY SILENT.
.p816
.smart
.segment "CODE"
entry:
    bne shared                  ; arrives (unknown/unknown)
    rep #$20
    .a16
    lda #$1234
    bra shared                  ; arrives A16
shared:
    .a16
    lda #$1234
    rts
