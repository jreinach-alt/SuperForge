; =============================================================================
; m7dg_floor.asm — the dungeon's Mode 7 plane: one DMA, nine colours, three
; regs
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM.
;
; The blob labels (`m7dg_map_bin`, `m7dg_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the
; m7dg_up dma_init claim names — a declared resource, not a hard-coded 0.
M7DG_REGS = $4300 + ES_D_M7DG_UP_CH * 16

; --- floor_arm: the whole plane (scene enter) ------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_m7_dungeon_assets.py emits the blob already in that layout. DMA
; mode 1 writes B, B+1, B, B+1 ... — with BBAD = VMDATAL that is $2118, $2119,
; $2118, $2119, which is exactly the interleave. So the whole plane is one
; transfer of 32,768 bytes with no unpacking pass.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is written,
; by one word. That is what makes the alternating byte pair land as one word
; and step to the next — with the default $00 it would advance after the LOW
; byte and every high byte would overwrite the wrong word.
;
; DAS is single-shot (consumed by the transfer), so it is armed HERE, for THIS
; transfer. There is one transfer and therefore one arming site; the rule bites
; when a loop fires several and only the first moves bytes.
;
; The blob is 32,768 B = one whole LoROM window, so this cannot cross a bank
; boundary — a DMA's A-bus address wraps within its bank rather than carrying.
floor_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^m7dg_map_bin
    sta a:M7DG_REGS + 4             ; A1B = source bank
    lda #ES_D_M7DG_UP_DMAP
    sta a:M7DG_REGS + 0             ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_M7DG_UP_BBAD
    sta a:M7DG_REGS + 1             ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(m7dg_map_bin)
    stx a:M7DG_REGS + 2             ; A1T
    ldy #ES_R_M7DG_MAP_SIZE
    sty a:M7DG_REGS + 5             ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_M7DG_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: nine absolute CGRAM indices, CPU-written -------------
    ; Nine words is eighteen stores; a DMA would cost more to set up than to
    ; run. CGADD auto-increments, so this build takes low byte then high byte
    ; per word and walks itself.
    sep #$20
    .a8
    lda #ES_C_M7DG_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:m7dg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7DG_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: no screen-over repeat, no flip. The map is 128x128 tiles and
    ; the PPU samples it modulo 128, so the world TILES infinitely — which is
    ; what a dungeon whose walls enclose the player wants, and it is why this
    ; rail needs no clamp in the renderer. (BGMODE and TM are the scene's
    ; `scene_writes`; see this feature's feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
