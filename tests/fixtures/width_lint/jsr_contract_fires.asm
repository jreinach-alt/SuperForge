; Hole 4, firing half: jsr/jsl sites are REAL arrivals. The callee's bare
; `.a8` entry annotation is a caller/callee width contract; this caller
; jsr's while still A16. Under the old model call sites never registered,
; so entry labels were invisible even in-file.
; MUST FIRE [annotation-contradicts-arrival] with a (call) arrival.
.p816
.smart
.segment "CODE"
caller:
    rep #$20
    .a16
    .i16
    jsr helper8                 ; call site is A16 — violates the contract
    rts

helper8:
    .a8                         ; entry contract: callers arrive A8
    .i16
    lda #$12
    rts
