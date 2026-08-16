; SILENT (latch/data category): the same two latch writes, under a `vram` region claim.
; The false-positive guard for the latch rule — the whole live tree is this
; shape, which is why closing the blind spot cost ZERO declarations.
.p816
.smart

.segment "CODE"
rgfx_latch_silent_go:
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$10
    .i16
    ldx #$0000
    stx a:$2116
    sta a:$2118
    rts
