; =============================================================================
; sit_floor.asm — the seam_irq_trial rail's Mode 7 plane: one DMA, five colours
; =============================================================================
; Everything here runs ONCE, at scene enter, under forced blank with NMI masked
; (the scene_mgr enter contract). No per-frame cost, no channel, no WRAM. The
; whole rail's difference between the two bands is the CAMERA's (sit_cam); the
; world under them never changes. A sibling of sh2_floor over sit_rom's blobs —
; the mechanism comments live there and in that feature's toml; what is
; repeated here is only what a reader of THIS file needs at the write sites.
;
; The blob labels (`sit_map_bin`, `sit_pal_bin`) are the game's .incbin claim
; sites in main.asm — the feature names them, the game backs them, and
; `make rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the
; sit_up dma_init claim names — a declared resource, not a hard-coded 0.
SIT_REGS = $4300 + ES_D_SIT_UP_CH * 16

; TM's layer bits ($212C). Named so the single layer this scene composites is
; legible at the write site. No OBJ bit: nothing draws but the plane.
SIT_TM_BG1 = $01

; --- floor_arm: the whole plane (scene enter) ------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; ONE mode-1 DMA: the 32,768 B blob is the interleaved Mode 7 image (tilemap
; in even bytes, 8bpp CHR in odd), and BBAD = VMDATAL under VMAIN = $80 makes
; the alternating $2118/$2119 writes land it word by word. DAS is single-shot
; and armed HERE, for THIS transfer. One whole LoROM window, so the A-bus
; address cannot cross a bank boundary.
floor_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #^sit_map_bin
    sta a:SIT_REGS + 4              ; A1B = source bank
    lda #ES_D_SIT_UP_DMAP
    sta a:SIT_REGS + 0              ; DMAP: A->B, 2 regs (mode 1) = the interleave
    lda #ES_D_SIT_UP_BBAD
    sta a:SIT_REGS + 1              ; BBAD: VMDATAL ($2118), so B+1 = $2119
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 (the Mode 7 base is fixed at 0)
    ldx #.loword(sit_map_bin)
    stx a:SIT_REGS + 2              ; A1T
    ldy #ES_R_SIT_MAP_SIZE
    sty a:SIT_REGS + 5              ; DAS (armed for THIS transfer)
    sep #$20
    .a8
    lda #(1 << ES_D_SIT_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs are free)
    rep #$20
    .a16

    ; ---- the palette: five absolute CGRAM indices, CPU-written ------------
    ; WORD 0 IS THE BACKDROP as well as palette index 0 — one slot, one owner,
    ; by hardware contract (why `backdrop` cannot compose here). The dusk
    ; colour sits there so what shows where the plane does not reach is sky.
    sep #$20
    .a8
    lda #ES_C_SIT_CG
    sta a:$2121                     ; CGADD = the claim's base (0, by contract)
    rep #$20
    .a16
    ldx #0
:   lda f:sit_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SIT_PAL_SIZE
    bcc :-

    ; ---- the Mode 7 register the FEATURE owns -----------------------------
    ; M7SEL = 0: no screen-over repeat, no flip — the 128x128 map wraps
    ; infinitely, which is what puts camera 2's warm stripe one 256-px period
    ; east of camera 1's cool one. (BGMODE and TM are the scene's
    ; `scene_writes`; see this feature's toml for the attribution.)
    sep #$20
    .a8
    stz a:$211A                     ; M7SEL
    rep #$20
    .a16
    rts
