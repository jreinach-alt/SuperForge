; Silent sibling of hole_axis: the A axis gets its forced annotation, the
; bare `.i16` stays (and agrees with both I arrivals).
; MUST STAY SILENT.
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
    .i16
    sep #$20                    ; forced narrowing on the multipath axis
    .a8
    lda #$34
    rts
