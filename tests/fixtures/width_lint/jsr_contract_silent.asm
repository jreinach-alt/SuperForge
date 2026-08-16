; Silent sibling of jsr_contract_fires: the caller narrows before the
; call, so the in-file call arrival matches the callee's bare entry
; annotation. MUST STAY SILENT.
.p816
.smart
.segment "CODE"
caller:
    rep #$20
    .a16
    .i16
    sep #$20
    .a8
    jsr helper8                 ; call site is A8 — honours the contract
    rep #$20
    .a16
    rts

helper8:
    .a8                         ; entry contract: callers arrive A8
    .i16
    lda #$12
    rts
