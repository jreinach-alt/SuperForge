; =============================================================================
; input2.asm — auto-joypad pad 2 with edge detection (global feature)
; =============================================================================
; ES_INP2_CUR / ES_INP2_PREV / ES_INP2_PRESS (2 B each, DP). $421A bit layout
; is the standard JOY2 word — identical to JOY1 ($4218), so the JOY_* bit
; positions game code defines for pad 1 apply verbatim. Mirrors input.asm;
; see input2/feature.toml for why this is a sibling feature rather than
; three more claims on `input`.

; --- input2_init: boot init contract ----------------------------------------
; CONTRACT input2_init
;   entry:    A16 I16
;   exit:     A16 I16
;   out:      pad 2's current / previous / press words all zeroed — the
;             write-before-read establishment for all three (rule 5)
;   clobbers: nothing. Three `stz`s and an `rts`: `stz` sets no flags and
;             the accumulator is neither read nor written
;   assumes:  ONCE, from MAIN's boot block, before the first input2_read
;   tail:     rts
input2_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "input2_init"
    stz z:ES_INP2_CUR
    stz z:ES_INP2_PREV
    stz z:ES_INP2_PRESS
    rts

; --- input2_read: latch this frame's pad-2 state (call once per frame) ------
; CONTRACT input2_read
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       $421A (JOY2L/H), the auto-joypad latch for this frame
;   out:      pad 2's current / previous / press words, on the same edge
;             convention input_read uses for pad 1
;   clobbers: A, N, Z, C. The index registers are untouched
;   assumes:  ONCE per frame. It spins on $4212 bit 0 the same way
;             input_read does — a fall-through no-op when sequenced after
;             it, and standalone-correct without it
;   tail:     rts
input2_read:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "input2_read"
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
