; =============================================================================
; contract_caller_bad.asm — the FIRING half of the cross-file fixture pair
; =============================================================================
; The shape CLAUDE.md rule 6 says is checked only on the emulator: a caller in
; a DIFFERENT file arriving at the wrong width. Both directions are here, so
; the fixture cannot pass by a check that only looks one way.
.p816
.smart
.segment "CODE"

caller_bad:
    .a8
    .i16
    jsr fx_needs_a16                ; arrives A8, declared A16 -> fires
    rep #$20
    .a16
    jsr fx_needs_a8                 ; arrives A16, declared A8 -> fires
    sep #$30
    .a8
    .i8
    jsr fx_needs_a16                ; wrong on BOTH axes -> fires twice
    rts
