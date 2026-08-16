; reg-gate fixture (FIRES): WRMPYB is port $4203 — footprint name ALU via the
; resource span, not a port of its own.
.p816
rgfx_aluf_mul:
    sep #$20
    .a8
    lda #7
    sta $4203                   ; WRMPYB — inside ALU's span, undeclared: FINDING
    rts
