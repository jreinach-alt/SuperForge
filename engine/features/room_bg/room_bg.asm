; =============================================================================
; room_bg.asm — the room: BG1 floor/walls, BG2 decor
; =============================================================================
; CHR, tilemaps and palettes come from the bg1_*/bg2_* claims
; (tools/gen_room_assets.py); every register base comes from the allocator's
; emitted encoding, never from mask arithmetic here. Everything is written
; once, at scene enter, under forced blank — no channel, no WRAM, no per-frame
; cost.
;
; This file puts two layers on screen. What DIMS BG1 and CLIPS BG2 is
; window_iris; see its feature.toml for the register contract.
;
; LAYER OWNERSHIP is asserted in room_bg/feature.toml, in prose, because layer
; identity is not a resource the allocator models. This scene's enter is the
; only writer of BGMODE/BG1SC/BG2SC/BG12NBA/TM.

; The enter-time GP-DMA register file, addressed through the channel the
; room_up dma_init claim names — a declared resource, not a hard-coded 0.
RB_REGS = $4300 + ES_D_ROOM_UP_CH * 16

; --- rb_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — it is consumed by the transfer, so every caller of this
; routine re-arms it here, per call (lessons_learned "DAS Is Single-Shot").
; That is why DAS is written inside the routine and not by the caller: there is
; exactly one arming site and it cannot be forgotten.
rb_up:
    .a16
    .i16
    stx a:RB_REGS + 2               ; A1T
    sty a:RB_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:RB_REGS + 4               ; A1B
    lda #ES_D_ROOM_UP_DMAP
    sta a:RB_REGS + 0               ; DMAP: A->B, 2 regs write-once
    lda #ES_D_ROOM_UP_BBAD
    sta a:RB_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_ROOM_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; --- room_arm: uploads + BG1/BG2 registers (scene enter) -------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
room_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR ---------------------------------------------------------
    sep #$20
    .a8
    lda #^bg1_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BG1_CHR
    sta a:$2116
    ldx #.loword(bg1_chr_bin)
    ldy #ES_R_BG1_CHR_ROM_SIZE
    jsr rb_up
    ; ---- BG1 tilemap -----------------------------------------------------
    sep #$20
    .a8
    lda #^bg1_map_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BG1_MAP
    sta a:$2116
    ldx #.loword(bg1_map_bin)
    ldy #ES_R_BG1_MAP_ROM_SIZE
    jsr rb_up
    ; ---- BG2 CHR ---------------------------------------------------------
    sep #$20
    .a8
    lda #^bg2_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BG2_CHR
    sta a:$2116
    ldx #.loword(bg2_chr_bin)
    ldy #ES_R_BG2_CHR_ROM_SIZE
    jsr rb_up
    ; ---- BG2 tilemap -----------------------------------------------------
    sep #$20
    .a8
    lda #^bg2_map_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BG2_MAP
    sta a:$2116
    ldx #.loword(bg2_map_bin)
    ldy #ES_R_BG2_MAP_ROM_SIZE
    jsr rb_up
    ; ---- palettes: BG1 at word 32, BG2 at word 48 ------------------------
    sep #$20
    .a8
    lda #ES_C_BG1_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:bg1_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BG1_PAL_ROM_SIZE
    bcc :-
    sep #$20
    .a8
    lda #ES_C_BG2_PAL
    sta a:$2121
    rep #$20
    .a16
    ldx #0
:   lda f:bg2_pal_bin, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BG2_PAL_ROM_SIZE
    bcc :-
    ; ---- BG registers ----------------------------------------------------
    sep #$20
    .a8
    lda #ES_V_BG1_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_BG2_MAP_SC_BASE
    sta a:$2108                     ; BG2SC
    lda #(ES_V_BG1_CHR_NBA | (ES_V_BG2_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: BG1 low nibble, BG2 high
    ; scroll pinned at 0 — the room is one screen and does not scroll, and a
    ; scene must not inherit whatever the previous one left in these latches
    stz a:$210D                     ; BG1HOFS (write-twice)
    stz a:$210D
    stz a:$210E                     ; BG1VOFS
    stz a:$210E
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    rep #$20
    .a16
    rts
