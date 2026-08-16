; reg-gate fixture (FIRES): $2118 with NO claim here — the owner survey
; names the siblings' hdma and dma_init port claims instead of "nobody".
.p816
rgfx_dpf_poke:
    sep #$20
    .a8
    lda #$00
    sta $2118                   ; VMDATAL — undeclared here: FINDING
    rts
