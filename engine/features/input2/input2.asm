; =============================================================================
; input2.asm — auto-joypad pad 2 with edge detection (global feature)
; =============================================================================
; ES_INP2_CUR / ES_INP2_PREV / ES_INP2_PRESS (2 B each, DP). $421A bit layout
; is the standard JOY2 word — identical to JOY1 ($4218), so the JOY_* bit
; positions game code defines for pad 1 apply verbatim. Mirrors input.asm;
; see input2/feature.toml for why this is a sibling feature rather than
; three more claims on `input`.

; --- input2_init: boot init contract ----------------------------------------
; In/out: A16/I16.
input2_init:
    .a16
    .i16
    stz z:ES_INP2_CUR
    stz z:ES_INP2_PREV
    stz z:ES_INP2_PRESS
    rts

; --- input2_read: latch this frame's pad-2 state (call once per frame) ------
; In/out: A16/I16, DB=0. Waits out auto-joypad busy ($4212 bit 0) — a
; fall-through no-op when sequenced after input_read, and standalone-correct
; without it.
input2_read:
    .a16
    .i16
    sep #$20
    .a8
:   lda a:$4212                 ; HVBJOY: bit 0 = auto-joyread in progress
    lsr
    bcs :-
    rep #$20
    .a16
    lda z:ES_INP2_CUR
    sta z:ES_INP2_PREV
    lda a:$421A                 ; JOY2L/H
    sta z:ES_INP2_CUR
    ; press = cur AND NOT prev
    lda z:ES_INP2_PREV
    eor #$FFFF
    and z:ES_INP2_CUR
    sta z:ES_INP2_PRESS
    rts
