; FIRES (latch/data category): VMAIN + VMADDL with no vram claim and no VMDATA*
; name. A latch is the *where* of a data port, so it rides the claim on the
; RESOURCE it serves. Before that category existed these were `continue`d as
; "unnamed, unclaimable" — the 48-of-158 blind spot a measured census measured.
.p816
.smart

.segment "CODE"
rgfx_latch_fires_go:
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$10
    .i16
    ldx #$0000
    stx a:$2116
    rts
