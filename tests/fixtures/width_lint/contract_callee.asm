; =============================================================================
; contract_callee.asm — the DECLARING half of the cross-file fixture pair
; =============================================================================
; Three routines, three shapes of contract. Nothing here is a violation: this
; file is the callee side, and what it is for is to be CALLED — correctly by
; contract_caller_ok.asm, wrongly by contract_caller_bad.asm.
.p816
.smart
.segment "CODE"

; CONTRACT fx_needs_a16
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       nothing
;   out:      nothing
;   clobbers: A, N, Z
;   assumes:  nothing
;   tail:     rts
fx_needs_a16:
    .a16
    .i16
    lda #$1234
    rts

; CONTRACT fx_needs_a8
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       nothing
;   out:      nothing
;   clobbers: A, N, Z
;   assumes:  the VBlank hook's own width pair
;   tail:     rts
fx_needs_a8:
    .a8
    .i16
    lda #$12
    rts

; CONTRACT fx_any_width
;   entry:    A? I?
;   exit:     A8 I8
;   in:       nothing
;   out:      nothing
;   clobbers: A, X, Y, N, Z
;   assumes:  nothing — it narrows both axes before its first use, which is
;             what makes the UNKNOWN entry a promise rather than an opt-out
;   tail:     rts
fx_any_width:
    sep #$30
    .a8
    .i8
    lda #$12
    ldx #$34
    rts
