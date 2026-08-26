; =============================================================================
; hz_bg.asm — BG1: the desert world
; =============================================================================
; The keystone BG pattern: an enter-time forced-blank CHR + tilemap + palette
; upload through the declared `hz_up` dma_init channel, and nothing else. The
; world does not move — the DISPLACEMENT is this rail's subject, not a camera —
; so there is no per-frame work here and no NMI hook entry.
;
; WHAT IS *NOT* HERE: BGMODE, BG1SC, BG12NBA and BG1VOFS. (BG1HOFS is not
; this feature's at all — `haze` seeds and drives it in the desert scene,
; `hz_flat` establishes it on the title screen; feature.toml says why.) Those are
; declared in this feature's `[[claims.reg]]` under `scene_writes`, which is a
; PERMISSION granted to scene-enter code — and no_literals' declaration-
; that-lies check refuses the permission if this file writes them too. So they
; live in game/heathaze/scenes/*.asm, where the display shape of a Mode 1 scene
; with BG3 on top is decided, and that placement is enforced rather than
; conventional.
;
; TM IS NOT HERE EITHER. This feature declares `[[claims.screen]] bg1 -> main`
; and `bg3 -> main`; the allocator composes those into one TM/TS pair per
; scene and emits it, and the scene writes ES_SCR_<SCENE>_TM. Nothing here
; narrates a layer mask — which is what lets stage 2 add a sub-screen shimmer
; layer without this file changing at all.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `hz_up` dma_init claim names — a declared resource, not a hard-coded 0.
HZ_REGS = $4300 + ES_D_HZ_UP_CH * 16

; --- hz_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; CONTRACT hz_up_dma
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
hz_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_up_dma"
    stx a:HZ_REGS + 2               ; A1T
    sty a:HZ_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:HZ_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_HZ_UP_DMAP
    sta a:HZ_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_HZ_UP_BBAD
    sta a:HZ_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_HZ_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- hz_arm_bg: CHR, the map, the palette (scene enter) ------------------------
; CONTRACT hz_arm_bg
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the desert's CHR and tilemap in VRAM, its palette in CGRAM
;             group 0 — word 0 included, which is the hardware backdrop
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
hz_arm_bg:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_arm_bg"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- the world's CHR -----------------------------------------------------
    lda #ES_V_HZ_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(hz_chr_bin)
    ldy #ES_R_HZ_CHR_SIZE
    lda #^hz_chr_bin
    jsr hz_up_dma
    ; ---- the world's tilemap -----------------------------------------------
    lda #ES_V_HZ_MAP
    sta a:$2116
    ldx #.loword(hz_map_bin)
    ldy #ES_R_HZ_MAP_SIZE
    lda #^hz_map_bin
    jsr hz_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — one word,
    ; two meanings, which is why this feature claims it rather than composing
    ; `backdrop` (feature.toml). CGDATA is a byte port written low-then-high,
    ; so the loop is CPU-side.
    sep #$20
    .a8
    lda #ES_C_HZ_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:hz_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_HZ_PAL_SIZE
    bcc :-
    rts
