; control: multi-path label in A with NO annotation.
; MUST FIRE [multipath-label] — proves the presence check is live. The
; body below control_fires' header is byte-identical to hole_reverse.asm
; apart from hole_reverse's one added `.a8` line (asserted by
; test_truth_reverse_is_control_plus_one_line).
.p816
.smart
.segment "CODE"
start:
    rep #$20
    .a16
    lda #$1234
    beq shared                  ; arrives A16
    sep #$20
    .a8
    lda #$12
    bra shared                  ; arrives A8
shared:
    lda #$34                    ; width-ambiguous, no annotation
    rts
