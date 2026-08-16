; =============================================================================
; m7c_floor.asm — the chamber's Mode 7 plane: one DMA, six colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; whole rail's motion is m7_barrel's; the plane under it never changes.
;
; The blob labels (`m7c_map_bin`, `m7c_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the m7c_up
; dma_init claim names — a declared resource, not a hard-coded 0.
M7C_REGS = $4300 + ES_D_M7C_UP_CH * 16

; --- floor_arm: the whole plane (scene enter) -------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_chamber_assets.py emits the blob already in that layout. DMA mode 1
; writes B, B+1, B, B+1 ... — with BBAD = VMDATAL that is $2118, $2119, $2118,
; $2119, which is exactly the interleave. So the whole plane is one transfer of
; 32,768 bytes with no unpacking pass.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is written,
; by one word. With the default $00 it would advance after the LOW byte and
; every high byte would overwrite the wrong word.
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
    lda #^m7c_map_bin
    sta a:M7C_REGS + 4              ; A1B = source bank
    lda #ES_D_M7C_UP_DMAP
    sta a:M7C_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_M7C_UP_BBAD
    sta a:M7C_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(m7c_map_bin)
    stx a:M7C_REGS + 2              ; A1T
    ldy #ES_R_M7C_MAP_SIZE
    sty a:M7C_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_M7C_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: six absolute CGRAM indices, CPU-written -------------
    ; Six words is twelve stores; a DMA would cost more to set up than to run.
    ; CGADD auto-increments, so this build takes low byte then high byte per
    ; word and walks itself.
    ;
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (which is why `backdrop` cannot compose here). It
    ; holds the dark ashlar stone, and it is what the Mode 1 band ABOVE the
    ; seam actually shows: that band's TM enables no layer with content, so
    ; every pixel of it is the backdrop colour with the vignette added.
    ;
    ; WORD 4 DUPLICATES WORD 0 and no pixel uses index 0: the converter moves
    ; every pixel that landed on index 0 onto a freshly appended copy so index
    ; 0 can be reserved for the backdrop. Kept byte-for-byte rather than tidied
    ; — vendor/art/mode7_chamber/README.md carries the trail.
    sep #$20
    .a8
    lda #ES_C_CHAMBER_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:m7c_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7C_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: no screen-over repeat, no flip. The map is 128x128 tiles and
    ; the PPU samples it modulo 128, so the plane WRAPS infinitely in both
    ; axes — which is what makes the vertical ROLL seamless.
    ;
    ; (BGMODE and TM are split_band's seed, written by the scene; see that
    ; feature.toml's attribution note.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
