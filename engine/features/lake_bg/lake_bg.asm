; =============================================================================
; lake_bg.asm — BG1: the lakeshore world
; =============================================================================
; The keystone BG pattern: an enter-time forced-blank CHR + tilemap + palette
; upload through the declared `lk_up` dma_init channel, and nothing else. The
; world does not move — the blender is this rail's subject, not a camera — so
; there is no per-frame work here and no NMI hook entry.
;
; WHAT IS *NOT* HERE: BGMODE, BG1SC, BG12NBA, BG1HOFS and BG1VOFS. Those are
; declared in this feature's `[[claims.reg]]` under `scene_writes`, which is a
; PERMISSION granted to scene-enter code — and no_literals' declaration-
; that-lies check refuses the permission if this file writes them too. So they
; live in game/lakeside/scenes/*.asm, where the display shape of a Mode 1 scene
; with BG3 on top is decided, and that placement is enforced rather than
; conventional.
;
; TM IS NOT HERE EITHER, and that one is the point of the rail. This feature
; declares `[[claims.screen]] bg1 -> main` and `bg3 -> main`; the allocator
; composes those with `water`'s `bg2 -> sub` into one TM/TS pair per scene and
; emits it. The scene writes ES_SCR_<SCENE>_TM. Nothing here narrates a layer
; mask.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `lk_up` dma_init claim names — a declared resource, not a hard-coded 0.
LK_REGS = $4300 + ES_D_LK_UP_CH * 16

; --- lk_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; CONTRACT lk_up_dma
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the source address low 16, Y = the byte count, A = the
;             source bank in the low byte
;   out:      the block transferred to VRAM from the caller's VMADD
;   clobbers: A, N, Z
;   assumes:  forced blank, and the enter-time window in which the channel
;             registers are free — this is a dma_init claim, phase
;             forced_blank by class
;   tail:     rts
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, once per
; call, which is the only shape a caller cannot forget.
lk_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lk_up_dma"
    stx a:LK_REGS + 2               ; A1T
    sty a:LK_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:LK_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_LK_UP_DMAP
    sta a:LK_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_LK_UP_BBAD
    sta a:LK_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_LK_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- lk_arm: CHR, the map, the palette (scene enter) ------------------------
; CONTRACT lk_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the world's CHR and tilemap in VRAM, its palette in CGRAM
;             group 0 — word 0 included, which is the hardware backdrop
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
lk_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lk_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- the band CHR -----------------------------------------------------
    lda #ES_V_LK_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(lk_chr_bin)
    ldy #ES_R_LK_CHR_SIZE
    lda #^lk_chr_bin
    jsr lk_up_dma
    ; ---- the world's tilemap -----------------------------------------------
    lda #ES_V_LK_MAP
    sta a:$2116
    ldx #.loword(lk_map_bin)
    ldy #ES_R_LK_MAP_SIZE
    lda #^lk_map_bin
    jsr lk_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — one word,
    ; two meanings, which is why this feature claims it rather than composing
    ; `backdrop` (feature.toml). CGDATA is a byte port written low-then-high,
    ; so the loop is CPU-side.
    sep #$20
    .a8
    lda #ES_C_LK_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:lk_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_LK_PAL_SIZE
    bcc :-
    rts
