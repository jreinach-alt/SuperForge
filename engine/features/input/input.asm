; =============================================================================
; input.asm — auto-joypad pad 1 with edge detection (global feature)
; =============================================================================
; ES_INP_CUR / ES_INP_PREV / ES_INP_PRESS (2 B each, DP). $4218 bit layout is
; the standard JOY1 word (B=$8000 ... R=$0010).

; --- input_init: boot init contract -----------------------------------------
; In/out: A16/I16.
input_init:
    .a16
    .i16
    stz z:ES_INP_CUR
    stz z:ES_INP_PREV
    stz z:ES_INP_PRESS
    rts

; --- input_read: latch this frame's pad state (call once per frame) ---------
; In/out: A16/I16, DB=0. Waits out auto-joypad busy ($4212 bit 0).
input_read:
    .a16
    .i16
    sep #$20
    .a8
:   lda a:$4212                 ; HVBJOY: bit 0 = auto-joyread in progress
    lsr
    bcs :-
    rep #$20
    .a16
    lda z:ES_INP_CUR
    sta z:ES_INP_PREV
    lda a:$4218                 ; JOY1L/H
    sta z:ES_INP_CUR
    ; press = cur AND NOT prev
    lda z:ES_INP_PREV
    eor #$FFFF
    and z:ES_INP_CUR
    sta z:ES_INP_PRESS
    rts
