; =============================================================================
; sau_floor.asm — the saucer, as the Mode 7 plane: one DMA, 16 colours, 3 regs
; =============================================================================
; bs_floor.asm's shape with this rail's blob. Everything here runs ONCE, at
; scene enter, under forced blank with NMI masked (the scene_mgr enter
; contract). No per-frame cost, no channel — the reveal, BOTH halves of every
; lunge and the death recede are m7_track lookups into m7_affine's shadow,
; never a plane re-upload.
;
; The blob labels (`sau_map_bin`, `sau_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the sau_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SAU_FLOOR_REGS = $4300 + ES_D_SAU_UP_CH * 16

; --- floor_arm: the whole plane (scene enter) ------------------------------
; CONTRACT sau_floor::floor_arm
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
; ONE DMA for the interleaved image: mode 1 writes $2118, $2119, $2118 ... —
; exactly the blob's tilemap/CHR interleave — and VMAIN = $80 advances the word
; address after the HIGH byte so each pair lands as one word. DAS is
; single-shot, armed HERE for THIS transfer. 32,768 B is one whole LoROM
; window, so the transfer cannot cross a bank boundary.
floor_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "floor_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^sau_map_bin
    sta a:SAU_FLOOR_REGS + 4        ; A1B = source bank
    lda #ES_D_SAU_UP_DMAP
    sta a:SAU_FLOOR_REGS + 0        ; DMAP: A->B, 2 regs (mode 1) = interleave
    lda #ES_D_SAU_UP_BBAD
    sta a:SAU_FLOOR_REGS + 1        ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(sau_map_bin)
    stx a:SAU_FLOOR_REGS + 2        ; A1T
    ldy #ES_R_SAU_MAP_SIZE
    sty a:SAU_FLOOR_REGS + 5        ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SAU_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: sixteen absolute CGRAM indices, CPU-written ----------
    ; Sixteen words is thirty-two stores; a DMA would cost more to set up than
    ; to run. CGADD auto-increments; low byte then high byte per word.
    sep #$20
    .a8
    lda #ES_C_SAU_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:sau_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SAU_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: wrap, no flip. At the reveal's far scale the 256-px view
    ; spans ~1280 world px, so the 1024-px sky tiles visibly at the edges —
    ; which on a star field reads as more sky rather than as a seam, and is
    ; why wrap is the right selection here.
    ;
    ; (BGMODE and TM are the scene's `scene_writes`; see this feature's
    ; feature.toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
