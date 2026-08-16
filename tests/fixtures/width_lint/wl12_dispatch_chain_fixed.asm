; -----------------------------------------------------------------------------
; WL-12 regression fixture — FIXED variant.
;
; Companion to wl12_dispatch_chain_bug.asm. Same dispatch chain structure,
; but with that fix applied: every multi-path branch target
; carries an explicit `.a16` annotation, and every `bra` from an A8 block
; restores A16 first.
;
; The width linter must produce ZERO multipath-label findings for this
; file.
; -----------------------------------------------------------------------------

.p816
.smart
.segment "CODE"

LOCAL_FRAME = $0E00
DEBUG_REGION = $7EE000

reset:
    sei
    clc
    xce
    rep #$30
    .a16
    .i16

@frame_loop:
    rep #$20
    .a16
    lda f:LOCAL_FRAME
    inc
    sta f:LOCAL_FRAME

    cmp #1
    bne @not_frame_1
    jsr engine_call_init
    bra @after_dispatch
@not_frame_1:
    .a16
    cmp #30
    bne @not_frame_30
    sep #$20
    .a8
    lda #$AA
    sta f:DEBUG_REGION + $10
    rep #$20
    .a16
    bra @after_dispatch
@not_frame_30:
    .a16
    cmp #220
    bne @not_frame_220
    jsr engine_reject_check
    sep #$20
    .a8
    lda f:DEBUG_REGION + $90
    sta f:DEBUG_REGION + $82
    rep #$20                         ; restore A16 before bra to multi-path
    .a16
    bra @after_dispatch
@not_frame_220:
    .a16
    cmp #240
    bne @after_dispatch
    sep #$20
    .a8
    lda f:DEBUG_REGION + $91
    sta f:DEBUG_REGION + $86
    rep #$20                         ; restore A16 before fall-through
    .a16

@after_dispatch:
    .a16                             ; explicit annotation: multi-path target
    cmp #240
    bra @frame_loop

engine_call_init:
    rts
engine_reject_check:
    rts
