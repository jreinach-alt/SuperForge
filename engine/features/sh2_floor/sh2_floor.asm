; =============================================================================
; sh2_floor.asm — the split_h_2p rail's Mode 7 plane: one DMA, five colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; whole rail's motion is the CAMERA's; the world under it never changes.
;
; The blob labels (`sh2_map_bin`, `sh2_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the sh2_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SH2_REGS = $4300 + ES_D_SH2_UP_CH * 16

; TM's layer bits ($212C). Named rather than spelled as one hex byte so the
; single layer this scene composites is legible at the write site. There is no
; OBJ bit here on purpose: nothing draws.
SH2_TM_BG1 = $01

; --- floor_arm: the whole plane (scene enter) ------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_split_h_2p_assets.py emits the blob already in that layout. DMA
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
    lda #^sh2_map_bin
    sta a:SH2_REGS + 4              ; A1B = source bank
    lda #ES_D_SH2_UP_DMAP
    sta a:SH2_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_SH2_UP_BBAD
    sta a:SH2_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(sh2_map_bin)
    stx a:SH2_REGS + 2              ; A1T
    ldy #ES_R_SH2_MAP_SIZE
    sty a:SH2_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SH2_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: five absolute CGRAM indices, CPU-written ------------
    ; Five words is ten stores; a DMA would cost more to set up than to run.
    ; CGADD auto-increments, so this build takes low byte then high byte per
    ; word and walks itself.
    ;
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (which is why `backdrop` cannot compose here). The
    ; generator puts the dusk colour there deliberately, so what shows where
    ; the plane does not reach is a sky rather than a floor tint.
    sep #$20
    .a8
    lda #ES_C_SH2_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:sh2_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SH2_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: no screen-over repeat, no flip. The map is 128x128 tiles and
    ; the PPU samples it modulo 128, so the world WRAPS infinitely in both axes
    ; — which is what lets both cameras pan forever without a clamp, and what
    ; makes the world's 1024-px period the only wrap the tick has to honour.
    ; (BGMODE and TM are the scene's `scene_writes`; see this feature's
    ; feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
