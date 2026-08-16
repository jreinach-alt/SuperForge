; reg-gate fixture (SILENT): CPU stores to a data port named ONLY on a
; dma_init claim — "a data port you claim as a port" through the dma_init
; half of the covered branch, isolated from the vram/hdma shapes.
.p816
rgfx_dip_seed:
    sep #$20
    .a8
    lda #$00
    sta $2118                   ; VMDATAL — covered by the dma_init port claim
    sta $2119                   ; VMDATAH — same claim
    rts
