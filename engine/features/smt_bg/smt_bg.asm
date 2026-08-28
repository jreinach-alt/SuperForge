; =============================================================================
; smt_bg.asm — BG1 and BG2: the plates and the melt
; =============================================================================
; The keystone BG pattern: an enter-time forced-blank CHR + tilemap + palette
; upload through the declared `smt_up` dma_init channel, and nothing else. The
; world does not scroll — the per-column DISPLACEMENT is this rail's subject,
; not a camera — so there is no per-frame work here and no NMI hook entry.
;
; ONE SET OF ART, TWO DECLARED MODES. Both scenes call this: `title` is a
; mode-1 scene and `works` is a mode-2 scene, and BG1 and BG2 are 4bpp in
; both. Not one byte here changes across the edge, which is the rail's
; structural claim — what changes is BG3, from a text layer to a table of
; scroll words.
;
; WHAT IS *NOT* HERE: BGMODE, BG1VOFS and BG2VOFS. The mode is a
; [[claims.video]] claim carried per scene, and the two scroll ports answer to
; a different feature in each scene (`smt_flat` on the title, `smt_opt` in the
; works), because in the works they are the FALLBACK an ungated column falls
; back to and on the title they are the picture's position. A write here would
; be a declaration that lies and `no_literals` refuses it.
;
; TM IS NOT HERE EITHER. This feature declares `[[claims.screen]] bg1 -> main`
; and `bg2 -> main`; the allocator composes those into one TM/TS pair per scene
; and emits it, and the scene writes ES_SCR_<SCENE>_TM.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `smt_up` dma_init claim names — a declared resource, not a hard-coded 0.
SMT_REGS = $4300 + ES_D_SMT_UP_CH * 16

; --- smt_up_dma: one VRAM upload. VMADD must already be set by the caller ---
; CONTRACT smt_up_dma
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
smt_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_up_dma"
    stx a:SMT_REGS + 2              ; A1T
    sty a:SMT_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:SMT_REGS + 4              ; A1B — the bank byte the caller passed
    lda #ES_D_SMT_UP_DMAP
    sta a:SMT_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_SMT_UP_BBAD
    sta a:SMT_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_SMT_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- smt_pal_up: one 16-word CGRAM group ------------------------------------
; CONTRACT smt_pal_up
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the byte offset into `smt_pal_bin`, A = the CGRAM word index
;   out:      16 words written from the blob
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked
;   tail:     rts
;
; CGDATA is a BYTE port written low-then-high, so this is a CPU loop rather
; than a transfer — the same shape hz_bg and lake_bg use, for the same reason.
smt_pal_up:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_pal_up"
    sep #$20
    .a8
    sta a:$2121                     ; CGADD = the claim's word base
    rep #$20
    .a16
    ldy #0                          ; X walks the blob, Y counts words out —
@word:                              ;   and that assignment is forced: the
    .a16                            ;   65816 has absolute-long indexed by X
    .i16                            ;   and NO Y form of it
    lda f:smt_pal_bin, x            ; one blob, two groups — see feature.toml
    sep #$20                        ;   for why it is not two blobs
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    iny
    cpy #16
    bcc @word
    rts

; --- smt_wall_glow: one step of the wall's colour rotation ------------------
; CONTRACT smt_wall_glow
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the cycle step, 0..SMT_WALL_PAL_FRAMES-1
;   out:      the wall's eight CGRAM words rewritten with that step's colours
;   clobbers: A, X, Y, N, Z, C
;   assumes:  VBlank or forced blank — CGRAM is not writable during active
;             display. Called from the works scene's NMI hook, and NOT called
;             at all by the title, which keeps step 0 from its enter upload
;   tail:     rts
;
; THE PATTERN IS IN THE PALETTE, WHICH IS WHY THIS EXISTS AT ALL. The wall's
; tile carries no pattern — one tile, every row identical, every column its own
; index — so rotating these eight colours walks a band of lightness sideways
; across the whole layer for 16 bytes of CGRAM a frame. Sixteen bytes buys what
; a CHR swap would spend a hundred and twenty-eight on, and it is the ONLY
; motion available to this surface: the wall must be invariant under vertical
; displacement, so a CHR animation would have to keep every frame vertically
; uniform and would leave the case that checks the invariance unable to tell
; "moved" from "animated". A colour rotation does not touch a pixel.
;
; IT LIVES HERE AND NOT IN `smt_opt` BECAUSE OWNERSHIP IS WHERE THE CLAIM IS.
; `smt_mpal` is this feature's CGRAM claim and this feature is global to both
; scenes; the PHASE that picks a step is scene-scoped to the works. So the
; works decides WHEN and WHICH and this file does the writing, which is the
; same split the rail uses everywhere a global asset is driven by scene state.
;
; TICK: ok -- the step is a function of the accumulated PHASE, which the scaler
;   already expressed against the declared tick. Nothing here counts frames.
smt_wall_glow:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_wall_glow"
    .repeat ::SMT_WALL_PAL_LOG2_BYTES
    asl a                           ; ...the step's offset, in blob bytes
    .endrepeat
    tax
    sep #$20
    .a8
    lda #(ES_C_SMT_MPAL + ::SMT_WALL_IX0)
    sta a:$2121                     ; CGADD = the wall's first entry
    rep #$20
    .a16
    ldy #0                          ; X walks the blob (absolute-long indexed
@word:                              ;   exists for X only), Y counts words out
    .a16
    .i16
    lda f:smt_wall_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    iny
    cpy #::SMT_WALL_SHADES
    bcc @word
    rts

; --- smt_arm_bg: CHR, both tilemaps, both palettes (scene enter) ------------
; CONTRACT smt_arm_bg
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the plate and melt CHR in VRAM, both 32x64 tilemaps in their
;             claimed pages, and CGRAM groups 0 and 2 written — group 0's
;             word 0 included, which is the hardware backdrop
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
smt_arm_bg:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_arm_bg"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- the shared CHR: BG1's plates then BG2's cavern and melt ----------
    lda #ES_V_SMT_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(smt_chr_bin)
    ldy #ES_R_SMT_CHR_SIZE
    lda #^smt_chr_bin
    jsr smt_up_dma
    ; ---- BG1's tilemap: four plates in a field of transparent cells -------
    lda #ES_V_SMT_PMAP
    sta a:$2116
    ldx #.loword(smt_pmap_bin)
    ldy #ES_R_SMT_PMAP_SIZE
    lda #^smt_pmap_bin
    jsr smt_up_dma
    ; ---- BG2's tilemap: wall, crust, melt ---------------------------------
    lda #ES_V_SMT_MMAP
    sta a:$2116
    ldx #.loword(smt_mmap_bin)
    ldy #ES_R_SMT_MMAP_SIZE
    lda #^smt_mmap_bin
    jsr smt_up_dma
    ; ---- the two palette groups -------------------------------------------
    ldx #0
    lda #ES_C_SMT_PPAL
    jsr smt_pal_up
    ldx #SMT_PAL_MELT_OFF
    lda #ES_C_SMT_MPAL
    jsr smt_pal_up
    rts
