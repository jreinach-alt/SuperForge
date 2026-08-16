; reg-gate fixture (SILENT): the declared ALU claim covers $4202-$4206.
.p816
rgfx_alus_mul:
    sep #$20
    .a8
    lda #7
    sta $4202                   ; WRMPYA — ALU, declared
    sta $4203                   ; WRMPYB — same claim, via the span
    rts
