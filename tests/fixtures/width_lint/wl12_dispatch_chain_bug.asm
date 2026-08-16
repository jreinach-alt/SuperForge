; -----------------------------------------------------------------------------
; WL-12 regression fixture — reproduces an earlier dispatch-chain bug.
;
; This file is NOT meant to assemble or run; it is consumed by
; tests/test_width_lint.py to verify that tools/width_lint.py catches
; the bug pattern documented in:
;   the friction log "surprise — HIGH — width-risk in test ROM
;                          dispatch chain (silent BRK)"
;
; THE BUG
; -------
; A frame-dispatch chain branches via `bra @after_dispatch` from several
; A-width modes. Some paths arrive in A16, others in A8. The
; @after_dispatch label has NO explicit `.a8`/`.a16`/`.i8`/`.i16`
; annotation — ca65 tracks A-width sequentially per source line, so
; whichever path's last `.aN` directive happens to fall through wins
; the assembler's tracked state. The runtime arrives in a different
; mode → next instruction is decoded with the wrong byte width →
; silent BRK.
;
; THE FIX
; -------
; Add `.a16` (or `.a8`) directly after the multi-path label so the
; assembler's tracked state matches the path-of-most-arrivals's runtime
; width. The fixed variant is wl12_dispatch_chain_fixed.asm.
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

    ; Frame-dispatch chain — multi-path branches into @after_dispatch.
    cmp #1
    bne @not_frame_1
    jsr engine_call_init
    bra @after_dispatch
@not_frame_1:
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
    cmp #220
    bne @not_frame_220
    jsr engine_reject_check
    sep #$20
    .a8
    lda f:DEBUG_REGION + $90
    sta f:DEBUG_REGION + $82
    ; bug: missing rep #$20 / .a16 before bra to multi-path label
    bra @after_dispatch
@not_frame_220:
    cmp #240
    bne @after_dispatch
    sep #$20
    .a8
    lda f:DEBUG_REGION + $91
    sta f:DEBUG_REGION + $86
    ; bug: missing rep #$20 / .a16 before fall-through to multi-path label

@after_dispatch:
    ; BUG: reached from A8 paths AND A16 paths. No explicit .a8/.a16
    ; annotation. ca65 picks whatever the last sequential .aN was —
    ; mismatched runtime causes silent-BRK on the next `cmp #imm`.
    cmp #240
    bra @frame_loop

engine_call_init:
    rts
engine_reject_check:
    rts
