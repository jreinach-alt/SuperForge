; hole 3: multi-path in A, annotated `.i16` ONLY. The old
; check accepted ANY of the four directives — an annotation on the axis
; that is not ambiguous said nothing about the one that is.
; MUST FIRE [annotation-wrong-axis].
.p816
.smart
.segment "CODE"
start:
    rep #$30
    .a16
    .i16
    lda #$1234
    beq shared                  ; arrives A16
    sep #$20
    .a8
    lda #$12
    bra shared                  ; arrives A8
shared:
    .i16                        ; says nothing about the ambiguous A axis
    lda #$34
    rts
