; reg-gate fixture (SILENT, item 5 rule 2): identical ASM to
; rgfx_lies_data. The only difference is one line of TOML.
.p816
rgfx_lies_data_shared_enter:
    sep #$20
    .a8
    lda #$1F
    sta a:$2122                 ; CGDATA — the DECLARED co-write
    rts
