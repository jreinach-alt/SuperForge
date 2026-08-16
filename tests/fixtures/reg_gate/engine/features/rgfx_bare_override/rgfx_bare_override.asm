; reg-gate fixture (FIRES): a bare `; REG-LINT: ok` with no reason.
.p816
rgfx_bov_arm:
    sep #$20
    .a8
    lda #3
    ; REG-LINT: ok
    sta a:$2106                 ; MOSAIC — bare override: FINDING
    rts
