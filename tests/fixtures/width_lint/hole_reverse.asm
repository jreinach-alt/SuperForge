; hole 1: control_fires plus ONE line — a WRONG bare `.a8`.
; One predecessor arrives A16; a bare annotation asserts the arriving
; width. Under the presence-only gate this was SILENT (adding a wrong
; annotation turned a firing finding into silence).
; MUST FIRE [annotation-contradicts-arrival].
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
    .a8
    lda #$34                    ; width-ambiguous, no annotation
    rts
