; =============================================================================
; met_floor.asm — the cutscene's Mode 7 plane: one DMA, 16 colours, one reg
; =============================================================================
; bs_floor.asm's shape with this rail's blob. Everything here runs ONCE, at
; scene enter, under forced blank with NMI masked (the scene_mgr enter
; contract). No per-frame cost, no channel — the meteor's grow, slide and
; tumble are m7_track lookups plus two origin words into m7_affine's shadow,
; never a plane re-upload.
;
; The blob labels (`met_map_bin`, `met_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and `make
; rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the met_up
; dma_init claim names — a declared resource, not a hard-coded 0.
MET_FLOOR_REGS = $4300 + ES_D_MET_UP_CH * 16

; --- floor_arm: the whole plane (scene enter) ------------------------------
; CONTRACT met_floor::floor_arm
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
;
; WIDTH-RISK: A16/I16 entry AND exit; `sep #$20` only, I-width never moves.
floor_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "floor_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^met_map_bin
    sta a:MET_FLOOR_REGS + 4        ; A1B = source bank
    lda #ES_D_MET_UP_DMAP
    sta a:MET_FLOOR_REGS + 0        ; DMAP: A->B, 2 regs (mode 1) = interleave
    lda #ES_D_MET_UP_BBAD
    sta a:MET_FLOOR_REGS + 1        ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(met_map_bin)
    stx a:MET_FLOOR_REGS + 2        ; A1T
    ldy #ES_R_MET_MAP_SIZE
    sty a:MET_FLOOR_REGS + 5        ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_MET_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: sixteen absolute CGRAM indices, CPU-written ---------
    ; Sixteen words is thirty-two stores; a DMA would cost more to set up than
    ; to run. CGADD auto-increments; low byte then high byte per word.
    sep #$20
    .a8
    lda #ES_C_M7_PAL
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:met_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MET_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL bit 7 = 1: "outside the 1024x1024 field = transparent, show the
    ; BACKDROP" rather than wrapping the image back into view. That is what
    ; the cutscene needs: the SPRITE phase parks the plane off-field so the
    ; opening reads black behind the approaching sprite,
    ; and the Mode-7 slide later carries the pivot out of the field entirely.
    ; With wrap selected instead, both would tile the meteor across the screen.
    ;
    ; (BGMODE and TM are the scene's `scene_writes`; see this feature's
    ; feature.toml for the attribution.)
    sep #$20
    .a8
    lda #(1 << 7)
    sta a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
