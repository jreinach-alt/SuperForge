; =============================================================================
; contract_caller_ok.asm — the CLEAN half of the cross-file fixture pair
; =============================================================================
; Every call arrives at the width the callee declares, so the cross-file pass
; checks all of them and finds nothing. A fixture that only ever fires proves
; the gate has teeth and says nothing about whether it has aim.
.p816
.smart
.segment "CODE"

caller_ok:
    .a16
    .i16
    jsr fx_needs_a16                ; A16/I16 in, A16/I16 declared
    jsr fx_any_width                ; A? — any arrival is legal
    sep #$20
    .a8
    jsr fx_needs_a8                 ; A8/I16 in, A8/I16 declared
    jsr fx_any_width                ; A? again, from the other width
    rep #$20
    .a16
    rts
