; =============================================================================
; input.asm — auto-joypad pad 1 with edge detection (global feature)
; =============================================================================
; ES_INP_CUR / ES_INP_PREV / ES_INP_PRESS (2 B each, DP). $4218 bit layout is
; the standard JOY1 word (B=$8000 ... R=$0010).

; --- input_init: boot init contract -----------------------------------------
; CONTRACT input_init
;   entry:    A16 I16
;   exit:     A16 I16
;   out:      ES_INP_CUR / ES_INP_PREV / ES_INP_PRESS all zeroed — the
;             write-before-read establishment for all three, since
;             power-on DP is random (rule 5)
;   clobbers: nothing. Three `stz`s and an `rts`: `stz` sets no flags and
;             the accumulator is neither read nor written
;   assumes:  ONCE, from MAIN's boot block, before the first input_read
;   tail:     rts
input_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "input_init"
    stz z:ES_INP_CUR
    stz z:ES_INP_PREV
    stz z:ES_INP_PRESS
    rts

; --- input_read: latch this frame's pad state (call once per frame) ---------
; CONTRACT input_read
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       $4218 (JOY1L/H), the auto-joypad latch for this frame
;   out:      ES_INP_CUR = this frame's pad word, ES_INP_PREV = last
;             frame's, ES_INP_PRESS = the rising edges (cur AND NOT prev)
;   clobbers: A, N, Z, C. The index registers are untouched
;   assumes:  ONCE per frame, at the top of the main loop. It spins on
;             $4212 bit 0 until auto-joypad read is no longer in progress,
;             so it must not run inside the window auto-joypad itself owns
;   tail:     rts
input_read:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "input_read"
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
