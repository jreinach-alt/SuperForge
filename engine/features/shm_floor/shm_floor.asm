; =============================================================================
; shm_floor.asm — the matrix-band pair's Mode 7 plane: one DMA, three colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; whole of both rails' band structure is the MATRIX's; the world under it never
; changes and both rails see the same one.
;
; The blob labels (`shm_map_bin`, `shm_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, each game backs them, and `make
; rom-unbacked` proves the bytes exist per COMPOSITION (so both ROMs carry
; their own sites for the one shared blob feature).

; The enter-time GP-DMA register file, addressed through the channel the shm_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SHM_REGS = $4300 + ES_D_SHM_UP_CH * 16

; --- the world --------------------------------------------------------------
; DERIVED from the map claim's own size rather than narrated: the Mode 7 blob
; is 2 bytes per tile (tilemap even, CHR odd) over a square plane, so its size
; fixes the side. Writing the derivation is what makes the centre follow the
; map instead of agreeing with it by coincidence — and `no_literals` refuses a
; bare 512 anyway.
SHM_MAP_T    = 128                          ; world side, in tiles
SHM_TILE_PX  = 8
.assert 2 * SHM_MAP_T * SHM_MAP_T = ES_R_SHM_MAP_SIZE, error, "shm_floor world size disagrees with the shm_map claim"
SHM_WORLD_PX = SHM_MAP_T * SHM_TILE_PX      ; 1024 — the plane's period
SHM_CENTRE   = SHM_WORLD_PX / 2             ; 512 — the M7X/M7Y pivot

; The active picture, in scanlines. The bands' heights sum to this, which each
; scene asserts.
SHM_LINES = 224

; TM's layer bits ($212C). Named rather than spelled as one hex byte so the
; single layer these scenes composite is legible at the write site. There is no
; OBJ bit here on purpose: nothing draws on either rail — neither scene
; touches OAM at all.
SHM_TM_BG1 = $01

; --- floor_arm: the whole plane (scene enter) ------------------------------
; CONTRACT shm_floor::floor_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole 32 KB interleaved Mode-7 plane uploaded by ONE
;             DMA, plus the Mode-7 registers and the palette
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. The upload is ONE 32,768-byte DMA: mode 1 writes
;             $2118/$2119 alternately, which is exactly the blob's
;             tilemap/CHR interleave, and VMAIN $80 steps the word address
;             after the HIGH byte. DAS is single-shot and is armed here
;             for THIS transfer; 32,768 B is one whole LoROM window, so it
;             cannot cross a bank
;   tail:     rts
;
; THE ONE-DMA UPLOAD, and why it is one and not two. The Mode 7 region is a
; single 32 KB interleaved image: the PPU reads the TILEMAP out of the even
; (low) VRAM bytes and the 8bpp CHR out of the odd (high) ones.
; Tools/gen_split_h_matrix_assets.py emits the blob already in that layout. DMA
; mode 1 writes B, B+1, B, B+1 … — with BBAD = VMDATAL that is $2118, $2119,
; $2118, $2119, which is exactly the interleave. So the whole plane is one
; transfer of 32,768 bytes with no unpacking pass.
;
; VMAIN = $80: the VRAM address advances after the HIGH byte ($2119) is
; written, by one word. With the default $00 it would advance after the LOW
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
    SF_ASSERT_WIDTH 16, 16, "floor_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^shm_map_bin
    sta a:SHM_REGS + 4              ; A1B = source bank
    lda #ES_D_SHM_UP_DMAP
    sta a:SHM_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_SHM_UP_BBAD
    sta a:SHM_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(shm_map_bin)
    stx a:SHM_REGS + 2              ; A1T
    ldy #ES_R_SHM_MAP_SIZE
    sty a:SHM_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SHM_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: three absolute CGRAM indices, CPU-written -----------
    ; Three words is six stores; a DMA would cost more to set up than to run.
    ; CGADD auto-increments, so this build takes low byte then high byte per
    ; word and walks itself.
    ;
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (which is why `backdrop` cannot compose here). It
    ; holds the muted blue-violet deliberately, so what shows where the plane
    ; does not reach is a sky rather than a floor tint.
    sep #$20
    .a8
    lda #ES_C_SHM_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:shm_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SHM_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: no screen-over repeat, no flip. The map is 128x128 tiles and
    ; the PPU samples it modulo 128, so the world WRAPS infinitely in both axes
    ; — which is what lets the widest band (scale 0.25, sampling a 1024-px span
    ; of world across 224 lines) reach past the map's edge without a fill
    ; colour appearing. (BGMODE and TM are the scene's `scene_writes`; see this
    ; feature's feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
