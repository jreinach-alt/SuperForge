; SILENT (latch/data category): vwf's real shape. `stx a:$2116` is the live in-tree site
; class this rule had to not break — deleting vwf's single `sta a:$2116` turns
; 8 of its 10 tests red, so a latch rule that fired on it would be unusable.
.p816
.smart

.segment "CODE"
rgfx_latch_byname_go:
    rep #$10
    .i16
    ldx #$0000
    stx a:$2116
    sep #$20
    .a8
    lda #$FF
    sta a:$2118
    rts
