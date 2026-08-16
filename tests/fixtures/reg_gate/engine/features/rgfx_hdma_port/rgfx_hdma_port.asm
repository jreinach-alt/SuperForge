; reg-gate fixture (SILENT): a CPU store to a data port this feature claims
; as a PORT (hdma), with no vram claim at all — vwf.asm:352's shape.
.p816
rgfx_hp_seed:
    sep #$20
    .a8
    lda #$00
    sta $2118                   ; VMDATAL — covered by the hdma port claim
    rts
