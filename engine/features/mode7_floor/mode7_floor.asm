; =============================================================================
; mode7_floor.asm — Mode 7 floor: CHR/palette upload + position-wrapped seed
; =============================================================================
; Shared code; scene symbols come in as parameters, world geometry from the
; game's world.inc (WORLD_* assemble-time constants), the world blob via the
; GLOBAL ES_R_WORLD_MAP_T0 chunk symbols. Forced blank + NMI masked (scene
; enter) — direct port writes throughout. Scratch: ES_ESCR (enter_scr).

; --- m7_upload_pal: floor colors to CGRAM 0.. -------------------------------
; In: A16/I16, DB=0. X = source addr low16, A = source bank (low byte),
;  Y = byte count (colors * 2). CGRAM index 0 is the hardware contract.
m7_upload_pal:
    .a16
    .i16
    stx z:ES_ESCR               ; 24-bit source ptr: low16
    sty z:ES_ESCR+4             ; byte count
    sep #$20
    .a8
    sta z:ES_ESCR+2             ; source bank
    stz a:$2121                 ; CGADD = 0
    ldy #0
@b: .a8
    lda [<ES_ESCR], y
    sta a:$2122
    iny
    cpy z:ES_ESCR+4
    bne @b
    rep #$20
    .a16
    rts

; GP-DMA register files addressed through the channels the two dma_init claims
; name. Both resolve to the same channel today; the point is that the number
; and the target port come from the declaration, not from this file.
M7CHR_REGS = $4300 + ES_D_M7CHR_UP_CH * 16
M7MAP_REGS = $4300 + ES_D_M7MAP_UP_CH * 16

; --- m7_upload_chr: N 8bpp tiles into the Mode 7 CHR (odd VRAM bytes) -------
; In: A16/I16, DB=0. X = source low16, Y = byte count, A = source bank. VMAIN
; $80 + single-reg DMA to $2119 walks the interleaved CHR bytes.
m7_upload_chr:
    .a16
    .i16
    sep #$20
    .a8
    sta a:M7CHR_REGS + 4        ; A1B = source bank
    lda #$80
    sta a:$2115                 ; VMAIN: step after $2119
    rep #$20
    .a16
    stz a:$2116                 ; VMADD = 0 (Mode 7 base is fixed at 0)
    stx a:M7CHR_REGS + 2        ; A1T
    sty a:M7CHR_REGS + 5        ; DAS = byte count
    sep #$20
    .a8
    lda #ES_D_M7CHR_UP_DMAP
    sta a:M7CHR_REGS + 0        ; DMAP: A->B, single reg
    lda #ES_D_M7CHR_UP_BBAD
    sta a:M7CHR_REGS + 1        ; BBAD: VMDATAH (odd bytes = CHR)
    lda #(1 << ES_D_M7CHR_UP_CH)
    sta a:$420B
    rep #$20
    .a16
    rts

; =============================================================================
; m7_upload_seed — position-wrapped 128x128 seed window of the world map
; =============================================================================
; In: A16/I16, DB=0. X = cam tile x, Y = cam tile y (world space, 0..511). Rows
; [cy-64, cy+64) x cols [cx-64, cx+64), each byte at VRAM tilemap LOW byte
; position (row & 127, col & 127) — the PPU samples mod 128, so bytes land at
; the WRAPPED position, never sequentially (position-space rule).
;
; Per world row, dest col c = col0 & 127 splits the strip into
;  span A: (128 - c) bytes at VMADD row*128 + c, src rowbase + col0
;  span B: c bytes at VMADD row*128 + 0, src rowbase + ((col0+128-c) & 511)
; The world edge (512) is a multiple of 128, so a source wrap always lands
; exactly on the dest wrap — two spans cover every case. VMADD is re-set per
; span (auto-increment would walk into the next VRAM row); DAS re-armed per
; span (single-shot).
;
; Scratch: ESCR+0 wr · +2 col0 · +4 c · +6 dest row base.
M7SEED_ROWS = 128
m7_upload_seed:
    .a16
    .i16
    txa
    sec
    sbc #(M7SEED_ROWS / 2)
    and #(WORLD_T_TILES - 1)
    sta z:ES_ESCR+2             ; col0
    and #127
    sta z:ES_ESCR+4             ; c (loop-invariant)
    tya
    sec
    sbc #(M7SEED_ROWS / 2)
    and #(WORLD_T_TILES - 1)
    sta z:ES_ESCR               ; wr
    sep #$20
    .a8
    lda #$00
    sta a:$2115                 ; VMAIN: step after $2118 (low bytes)
    lda #ES_D_M7MAP_UP_DMAP
    sta a:M7MAP_REGS + 0        ; DMAP: A->B single reg
    lda #ES_D_M7MAP_UP_BBAD
    sta a:M7MAP_REGS + 1        ; BBAD: VMDATAL
    rep #$20
    .a16
    ldy #M7SEED_ROWS            ; Y = rows remaining
@row:
    .a16
    ; ---- chunk bank = T0_BANK + (wr >> 6) (64 rows per 32 KB window) -----
    lda z:ES_ESCR
    .repeat 6
        lsr
    .endrepeat
    clc
    adc #ES_R_WORLD_MAP_T0_BANK
    sep #$20
    .a8
    sta a:M7MAP_REGS + 4        ; A1B (both spans of this row)
    rep #$20
    .a16
    ; ---- rowbase -> X: window base + (wr & 63) * 512 ----------------------
    lda z:ES_ESCR
    and #(WORLD_ROWS_PER_BANK - 1)
    xba                         ; *256
    asl                         ; *512
    clc
    adc #ES_R_WORLD_MAP_T0_ADDR
    tax
    ; ---- dest row base: (wr & 127) * 128 ----------------------------------
    lda z:ES_ESCR
    and #127
    xba                         ; *256
    lsr                         ; *128
    sta z:ES_ESCR+6
    ; ---- span A: (128 - c) bytes at dest col c ----------------------------
    clc
    adc z:ES_ESCR+4
    sta a:$2116                 ; VMADD = destrow + c
    txa
    clc
    adc z:ES_ESCR+2
    sta a:M7MAP_REGS + 2        ; A1T = rowbase + col0
    lda #M7SEED_ROWS
    sec
    sbc z:ES_ESCR+4
    sta a:M7MAP_REGS + 5        ; DAS = 128 - c (re-armed per span)
    sep #$20
    .a8
    lda #(1 << ES_D_M7MAP_UP_CH)
    sta a:$420B                 ; fire span A
    rep #$20
    .a16
    ; ---- span B (only when c != 0): c bytes at dest col 0 -----------------
    lda z:ES_ESCR+4
    beq @next
    lda z:ES_ESCR+6
    sta a:$2116                 ; VMADD = destrow + 0
    lda #M7SEED_ROWS
    sec
    sbc z:ES_ESCR+4             ; span A length
    clc
    adc z:ES_ESCR+2
    and #(WORLD_T_TILES - 1)    ; src col of span B (world wrap)
    sta z:ES_ESCR+6             ; (dest base consumed — reuse as src col)
    txa
    clc
    adc z:ES_ESCR+6
    sta a:M7MAP_REGS + 2        ; A1T = rowbase + spanB col
    lda z:ES_ESCR+4
    sta a:M7MAP_REGS + 5        ; DAS = c
    sep #$20
    .a8
    lda #(1 << ES_D_M7MAP_UP_CH)
    sta a:$420B                 ; fire span B
    rep #$20
    .a16
@next:
    .a16
    ; ---- advance world row -----------------------------------------------
    lda z:ES_ESCR
    inc
    and #(WORLD_T_TILES - 1)
    sta z:ES_ESCR
    dey
    bne @row
    rts
