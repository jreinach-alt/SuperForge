; =============================================================================
; mode7_stream_nmi.inc — Mode 7 2-axis streaming VBlank DMA dispatcher.
; =============================================================================
; Included inline from engine/nmi_handler.asm (after mode7_nmi.inc, before the
; Phase-5 HDMA setup) ONLY when the ROM defines MODE7_STREAM_NMI. DMAs the
; staged row/column buffers (filled by mode7_stream_tick on the main thread)
; into the Mode 7 VRAM tilemap LOW bytes (VMDATAL $2118), then clears the
; pending counts so it idles next frame unless the tick re-queues.
;
; Entry contract (the nmi_handler.asm hook site): DP = $0100, DB = $00,
; A16/I16. This include preserves that on exit (ends A16/I16, DB=$00).
;
; Why VMDATAL-only (BBAD = $18) + VMAIN bit7=0:
;   The Mode 7 VRAM word holds [tilemap_id (low), CHR_byte (high)]. Streaming
;   replaces only the tile-id (low byte); the CHR (high byte) is uploaded once
;   at boot and must NOT be touched. Writing VMDATAL with VMAIN bit7=0
;   increments the VRAM word address after the LOW write — so a 128-byte DMA
;   advances 128 words (rows: VMAIN=$00 -> +1 word/byte; columns: VMAIN=$02 ->
;   +128 words/byte = stride down a column), leaving every high byte intact.
;
; DAS ($4305/$4306) is SINGLE-SHOT (CLAUDE.md "DAS Is Single-Shot"): re-armed
; before every MDMAEN write inside the slot loops.
;
; Uses general-purpose DMA channel 0 (NMI owns CH0 here; HDMA setup follows).
; =============================================================================

    ; --- ROW DMAs: VMAIN=$00 (increment +1 word after VMDATAL write) -------
    rep #$20
    .a16
    lda f:$7E0000 + M7S_ROW_COUNT
    bne @m7s_row_go
    jmp @m7s_no_row                 ; trampoline (BEQ range)
@m7s_row_go:
    sta f:$7E0000 + M7S_NMI_COUNT             ; remaining rows (1..8)
    lda #0
    sta f:$7E0000 + M7S_NMI_IDX               ; VADDR table index (0,2,4,..)
    tay                             ; Y = buffer byte offset (0,128,256,..)
@m7s_row_loop:
    sep #$20
    .a8
    lda #$00                        ; VMAIN: +1 word after low-byte write
    sta a:$2115
    rep #$20
    .a16
    lda f:$7E0000 + M7S_NMI_IDX
    tax
    lda f:$7E0000 + M7S_ROW_VADDR, x
    sta a:$2116                     ; VMADD = row VRAM word address
    sep #$20
    .a8
    lda #$00
    sta a:$4300                     ; DMAP0: A->B, 1 reg, fixed B-bus
    lda #$18
    sta a:$4301                     ; BBAD0 = VMDATAL ($2118)
    rep #$20
    .a16
    tya
    clc
    adc #M7S_ROW_BUF
    sta a:$4302                     ; A1T0 (WRAM source low16)
    sep #$20
    .a8
    lda #$7E
    sta a:$4304                     ; A1B0 = WRAM bank
    rep #$20
    .a16
    lda #128
    sta a:$4305                     ; DAS0 = 128 bytes (RE-ARM per slot)
    sep #$20
    .a8
    lda #$01
    sta a:$420B                     ; MDMAEN: trigger CH0
    rep #$20
    .a16
    tya
    clc
    adc #128
    tay                             ; next slot buffer offset
    lda f:$7E0000 + M7S_NMI_IDX
    clc
    adc #2
    sta f:$7E0000 + M7S_NMI_IDX
    lda f:$7E0000 + M7S_NMI_COUNT
    dec
    sta f:$7E0000 + M7S_NMI_COUNT
    bne @m7s_row_loop
    lda #0
    sta f:$7E0000 + M7S_ROW_COUNT             ; clear pending
@m7s_no_row:

    ; --- COLUMN DMAs: VMAIN=$02 (increment +128 words = column stride) -----
    rep #$20
    .a16
    lda f:$7E0000 + M7S_COL_COUNT
    bne @m7s_col_go
    jmp @m7s_no_col
@m7s_col_go:
    sta f:$7E0000 + M7S_NMI_COUNT
    lda #0
    sta f:$7E0000 + M7S_NMI_IDX
    tay
@m7s_col_loop:
    sep #$20
    .a8
    lda #$02                        ; VMAIN: +128 words (column stride)
    sta a:$2115
    rep #$20
    .a16
    lda f:$7E0000 + M7S_NMI_IDX
    tax
    lda f:$7E0000 + M7S_COL_VADDR, x
    sta a:$2116                     ; VMADD = column position (0..127)
    sep #$20
    .a8
    lda #$00
    sta a:$4300
    lda #$18
    sta a:$4301                     ; BBAD0 = VMDATAL
    rep #$20
    .a16
    tya
    clc
    adc #M7S_COL_BUF
    sta a:$4302
    sep #$20
    .a8
    lda #$7E
    sta a:$4304
    rep #$20
    .a16
    lda #128
    sta a:$4305                     ; DAS0 (RE-ARM per slot)
    sep #$20
    .a8
    lda #$01
    sta a:$420B                     ; trigger CH0
    rep #$20
    .a16
    tya
    clc
    adc #128
    tay
    lda f:$7E0000 + M7S_NMI_IDX
    clc
    adc #2
    sta f:$7E0000 + M7S_NMI_IDX
    lda f:$7E0000 + M7S_NMI_COUNT
    dec
    sta f:$7E0000 + M7S_NMI_COUNT
    bne @m7s_col_loop
    lda #0
    sta f:$7E0000 + M7S_COL_COUNT
@m7s_no_col:
    ; VMAIN back to the engine default ($80: increment after high-byte write)
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
