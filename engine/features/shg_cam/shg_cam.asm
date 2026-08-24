; =============================================================================
; shg_cam.asm — the applied seam-IRQ case: TWO MOVING cameras, band 2 by IRQ
; =============================================================================
; The mechanism, per channel:
;
;  ch ES_H_SHGAB_CH DMAP $43 (mode 3 + INDIRECT) -> M7A/M7B whole frame
;  ch ES_H_SHGCD_CH DMAP $43 -> M7C/M7D whole frame
;  Each index table holds TWO band-local repeat entries streaming the SAME
;  fixed-angle 448 B pose — band 2's entry re-starts it at line 112. In
;  the HDMAEN mask; armed via the sm_hdma shadow.
;
;  ch ES_H_SHGXY_CH DMAP $03 (mode 3, DIRECT) -> M7X/M7Y band 2
;  ch ES_H_SHGHV_CH DMAP $03 -> M7HOFS/M7VOFS band 2
;  THE FREED PAIR: pre-armed as GP-DMA (A1T -> a 4-byte staged block,
;  DAS = 4), NEVER in the HDMAEN mask, fired by ONE MDMAEN write from the
;  seam IRQ handler in scanline 112's trailing HBlank. Their A1T/DAS are
;  consumed by every fire and re-armed by sm_nmi_core's shadow MVN every
;  armed VBlank — the DAS-is-single-shot lesson riding the engine's own
;  re-arm path. What their absence from HDMAEN BUYS is shg_grad's channel.
;
;  Under -DSHG_HDMA_ORIGIN (the GOLD control) the same two channels instead
;  carry the classic 11-byte origin tables ([112,X,Y][1,X,Y][0], non-repeat
;  counts: fire once, hold) and ARE in the HDMAEN mask; no IRQ, no vector, no
;  VTIME. That build also implies -DSHG_NO_GRAD (it has no freed channel to
;  spend), so it is compared against the -DSHG_NO_GRAD build and the two must
;  render BYTE-IDENTICAL.
;
; WHAT IS NEW HERE AGAINST sit_cam: THE VALUES MOVE. Camera 1 pans +1 px/frame
; in Y and camera 2 +2 (different speeds are the independent-driver signal; X
; is fixed so each band stays on its own colour stripe). The positions live in
; WRAM, advance in the scene TICK, and are read by the VBlank hook that
; re-stamps band 1's registers and re-stages band 2's eight bytes. So the seam
; DMA delivers a genuinely live origin every frame rather than a boot-time
; constant — which is what makes the freed channel's payload a claim about a
; working rail. Ordering: tick runs to completion before the frame's `wai`, so
; the hook never reads a half-advanced pair.
;
; Contract: template-wide DB=$00; every WRAM touch is long-addressed, so no DB
; assumption anywhere in this file (the IRQ handler interrupts the main loop
; wherever it is).

; --- geometry: the world, the seam, the two cameras --------------------------
; DERIVED, not narrated: the map wraps at SHG_MAP_T tiles (the PPU samples Mode
; 7 modulo 128) and the warm/cool stripe period is the generator's own STRIPE
; constant — camera 1 starts mid-world on a COOL stripe centre, camera 2
; exactly one stripe east on a WARM one. Band-2 red is the position oracle.
SHG_TILE_PX   = 8
SHG_MAP_T     = 128
.assert ES_R_SHG_MAP_SIZE = SHG_MAP_T * SHG_MAP_T * 2, error, "shg_cam: the map blob is not the 128x128 interleaved image the wrap math assumes"
SHG_WORLD_PX  = SHG_MAP_T * SHG_TILE_PX     ; 1024
SHG_WORLD_MASK = SHG_WORLD_PX - 1           ; the pan wrap
SHG_STRIPE_T  = 32                          ; the generator's STRIPE
SHG_STRIPE_PX = SHG_STRIPE_T * SHG_TILE_PX  ; 256 px per colour stripe
SHG_SEAM      = 112                         ; band 1 = 0..111, band 2 = 112..223
SHG_LINES     = 224
SHG_HALF_W    = 128                         ; half the 256-px screen

SHG_P1_X0 = SHG_WORLD_PX / 2                ; 512: camera 1, COOL stripe
SHG_P1_Y0 = SHG_WORLD_PX / 2
SHG_P2_X0 = SHG_P1_X0 + SHG_STRIPE_PX       ; 768: camera 2, WARM stripe
SHG_P2_Y0 = SHG_P1_Y0

; The per-frame Y advance. DIFFERENT SPEEDS IS THE SIGNAL: equal speeds would
; render a moving picture that no test could tell from one camera driving both
; bands, which is the property this rail inherits the split to demonstrate.
.ifdef SHG_FREEZE
SHG_CAM1_DY = 0
SHG_CAM2_DY = 0
.else
SHG_CAM1_DY = 1
SHG_CAM2_DY = 2
.endif

; --- the IRQ line (V-only; internal scanlines — irq.asm's contract) ----------
; VTIME counts INTERNAL scanlines and content line L draws during internal
; scanline L+1, so a seam at content line S arms VTIME = S, NOT S-1: the fire
; lands in internal scanline S's trailing HBlank, after content line S-1
; flushed, and content line S picks the new values up. One line early corrupts
; content line S-1 — planted as `vtime-off-by-one`.
SHG_VTIME = SHG_SEAM

; --- shg_tbl layout (80 B; the toml carries the map) -------------------------
SHG_IDX_AB        = ES_SHG_TBL + 0          ; 7 B  AB index table
SHG_IDX_CD        = ES_SHG_TBL + 16         ; 7 B  CD index table
SHG_STAGE_XY      = ES_SHG_TBL + 32         ; 4 B  staged M7X/M7Y (shgxy A1T)
SHG_STAGE_HV      = ES_SHG_TBL + 36         ; 4 B  staged HOFS/VOFS (shghv A1T)
SHG_OTBL_XY       = ES_SHG_TBL + 40         ; 11 B origin table (control only)
SHG_OTBL_HV       = ES_SHG_TBL + 56         ; 11 B origin table (control only)
SHG_IDX_AB_LONG   = ES_SHG_TBL_LONG + 0
SHG_IDX_CD_LONG   = ES_SHG_TBL_LONG + 16
SHG_STAGE_XY_LONG = ES_SHG_TBL_LONG + 32
SHG_STAGE_HV_LONG = ES_SHG_TBL_LONG + 36
SHG_OTBL_XY_LONG  = ES_SHG_TBL_LONG + 40
SHG_OTBL_HV_LONG  = ES_SHG_TBL_LONG + 56
; The two live camera positions — the one piece of state sit_cam did not have.
SHG_POS1X_LONG    = ES_SHG_TBL_LONG + 72
SHG_POS1Y_LONG    = ES_SHG_TBL_LONG + 74
SHG_POS2X_LONG    = ES_SHG_TBL_LONG + 76
SHG_POS2Y_LONG    = ES_SHG_TBL_LONG + 78
.assert (72 + 8) = ES_SHG_TBL_SIZE, error, "shg_cam: the table layout does not fill its wram claim"

; --- shg_cnt layout (12 B; the rail's evidence surface) ----------------------
SHG_CNT_IRQ_LONG   = ES_SHG_CNT_LONG + 0    ; u16 seam-IRQ fire count
SHG_CNT_WAKE_LONG  = ES_SHG_CNT_LONG + 2    ; u16 raw wai wakes (main.asm's)
SHG_CNT_ENTH_LONG  = ES_SHG_CNT_LONG + 4    ; entry OPHCT lo, hi bit
SHG_CNT_ENTV_LONG  = ES_SHG_CNT_LONG + 6    ; entry OPVCT lo, hi bit
SHG_CNT_FIREH_LONG = ES_SHG_CNT_LONG + 8    ; post-fire OPHCT lo, hi bit
SHG_CNT_FIREV_LONG = ES_SHG_CNT_LONG + 10   ; post-fire OPVCT lo, hi bit

; --- the channel register files (live writes: boot arm + the fire) -----------
SHG_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8      ; 16 B of register file per channel
SHG_XY_REGS = $4300 + ES_H_SHGXY_CH * 16
SHG_HV_REGS = $4300 + ES_H_SHGHV_CH * 16

; =============================================================================
; cam_arm — build every table, seed the positions, stage every channel. The
; caller ORs the HDMAEN bits into the scene_mgr shadow after (matrix pair
; always; plus the origin pair ONLY under -DSHG_HDMA_ORIGIN — the seam channels
; staying out of that mask is what frees shg_grad's).
; =============================================================================
; CONTRACT shg_cam::cam_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every table built, the positions seeded and every channel
;             shadow staged
;   clobbers: A, X, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. The caller ORs the enable bits into the HDMAEN
;             shadow AFTERWARDS
;   tail:     rts
cam_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cam_arm"
    ; ---- the declared init contract: zero BOTH claims first ----------------
    ; Power-on WRAM is random; the DMA controller's terminator processing still
    ; fetches address bytes after a $00 count, so even never-stamped table tail
    ; bytes must not be garbage. The counters must start at 0 for the cadence
    ; assertions to mean anything at all. (Not "zero to be safe" — this is the
    ; claim's own init contract, and the positions below overwrite their slots
    ; immediately.)
    lda #0
    ldx #(ES_SHG_TBL_SIZE - 2)
:   sta f:ES_SHG_TBL_LONG, x
    dex
    dex
    bpl :-
    ldx #(ES_SHG_CNT_SIZE - 2)
:   sta f:ES_SHG_CNT_LONG, x
    dex
    dex
    bpl :-

    ; ---- the two camera positions, at their start poses --------------------
    lda #SHG_P1_X0
    sta f:SHG_POS1X_LONG
    lda #SHG_P1_Y0
    sta f:SHG_POS1Y_LONG
    lda #SHG_P2_X0
    sta f:SHG_POS2X_LONG
    lda #SHG_P2_Y0
    sta f:SHG_POS2Y_LONG

    ; ---- matrix index tables: two band-local repeat entries each -----------
    ; 128 is the HDMA repeat flag; 128|112 = "a NEW 4-byte unit every scanline,
    ; 112 times". Entry 2 re-starts the SAME pose at line 112 — both bands
    ; stream one table; position alone distinguishes them.
    sep #$20
    .a8
    lda #(128 | SHG_SEAM)
    sta f:SHG_IDX_AB_LONG + 0       ; band 1: lines 0..111
    sta f:SHG_IDX_AB_LONG + 3       ; band 2: lines 112..223
    sta f:SHG_IDX_CD_LONG + 0
    sta f:SHG_IDX_CD_LONG + 3
    lda #0
    sta f:SHG_IDX_AB_LONG + 6       ; terminators
    sta f:SHG_IDX_CD_LONG + 6
    rep #$20
    .a16
    lda #ES_R_SHG_POSE_AB_ADDR      ; both entries -> the one fixed pose
    sta f:SHG_IDX_AB_LONG + 1
    sta f:SHG_IDX_AB_LONG + 4
    lda #ES_R_SHG_POSE_CD_ADDR
    sta f:SHG_IDX_CD_LONG + 1
    sta f:SHG_IDX_CD_LONG + 4

    ; ---- band 1's origin registers (the SEED) + band 2's staged bytes ------
    jsr cam_stamp_band1             ; forced blank: write-twice pairs safe
    jsr cam_stamp_stage

    ; ---- channel shadow: the matrix pair (INDIRECT) ------------------------
    ; A1B is the INDEX table's bank ($7E); DASB ($43x7) is the POSE blob's —
    ; getting those two the wrong way round is the classic indirect-HDMA bug,
    ; which is why both come from emitted symbols.
    sep #$20
    .a8
    ldx #(ES_H_SHGAB_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGAB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 2-regs-write-twice
    lda #ES_H_SHGAB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B
    lda #ES_R_SHG_POSE_AB_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB
    rep #$20
    .a16
    lda #SHG_IDX_AB
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    sep #$20
    .a8
    ldx #(ES_H_SHGCD_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGCD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHGCD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_SHG_POSE_CD_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #SHG_IDX_CD
    sta f:ES_SM_HDMA_LONG+2, x

.ifndef SHG_HDMA_ORIGIN
    ; ---- THE FREED PAIR: staged as GP-DMA ----------------------------------
    ; The shadow slots carry the full GP-DMA config; sm_nmi_core's MVN
    ; re-stamps the live registers from them every armed VBlank, which IS the
    ; per-frame A1T/DAS re-arm. DAS is written 16-bit so its high byte is
    ; explicit rather than left over from the transition clear.
    sep #$20
    .a8
    ldx #(ES_H_SHGXY_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGXY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP $03: A->B, 2 regs write twice
    lda #ES_H_SHGXY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7X
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the stage block's bank
    rep #$20
    .a16
    lda #SHG_STAGE_XY
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    lda #4
    sta f:ES_SM_HDMA_LONG+5, x      ; DAS = 4 (lo+hi)
    sep #$20
    .a8
    ldx #(ES_H_SHGHV_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGHV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHGHV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7HOFS
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHG_STAGE_HV
    sta f:ES_SM_HDMA_LONG+2, x
    lda #4
    sta f:ES_SM_HDMA_LONG+5, x
    ; ---- and the LIVE registers, for fires before the first armed NMI ------
    ; The arm sequence CLIs at the end of boot; the first VBlank MVN has not
    ; run yet, so a seam fire in that window would read power-on channel
    ; registers (DAS random -> an arbitrary-length transfer). Write them now,
    ; under forced blank, so the very first fire is already correct.
    jsr cam_rearm_live
.else
    ; ---- THE GOLD CONTROL: the classic origin channel pair ------------------
    ; Non-repeat counts — the opposite reading of the same byte: 112 means
    ; "transfer the 4-byte unit ONCE, then idle 111 lines", then the count-1
    ; entry fires band 2's values at line 112 and the terminator ends the
    ; channel (the write-twice latch holds the value to the frame's bottom).
    ; The line-0 unit delivers band 1's own values — the same bytes the seed
    ; wrote — so the seed's overrider arrives at the top of every frame
    ;
    sep #$20
    .a8
    lda #SHG_SEAM
    sta f:SHG_OTBL_XY_LONG + 0
    sta f:SHG_OTBL_HV_LONG + 0
    lda #1
    sta f:SHG_OTBL_XY_LONG + 5
    sta f:SHG_OTBL_HV_LONG + 5
    lda #0
    sta f:SHG_OTBL_XY_LONG + 10     ; terminators
    sta f:SHG_OTBL_HV_LONG + 10
    rep #$20
    .a16
    jsr cam_stamp_otbl
    ; shadow staging: SAME DMAP, SAME BBAD as the subject build — the whole
    ; delta is A1T (table vs stage block) and the HDMAEN mask bit.
    sep #$20
    .a8
    ldx #(ES_H_SHGXY_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGXY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHGXY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHG_OTBL_XY
    sta f:ES_SM_HDMA_LONG+2, x
    sep #$20
    .a8
    ldx #(ES_H_SHGHV_CH * SHG_SHDW_CH_SIZE)
    lda #ES_H_SHGHV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHGHV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SHG_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHG_OTBL_HV
    sta f:ES_SM_HDMA_LONG+2, x
.endif
    rts

; =============================================================================
; cam_advance — the two cameras' per-frame motion. Called from the scene TICK
; (outside VBlank), so the VBlank hook always reads a settled pair. Camera 1
; pans +1 px/frame in Y, camera 2 +2. X is untouched: each band must stay over
; its own colour stripe, because band-2 red IS the position oracle every
; framebuffer assertion reads. Both wrap at the world width. Under -DSHG_FREEZE
; both deltas are 0 and this is a pair of no-op adds.
; =============================================================================
; CONTRACT cam_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both cameras stepped by this frame's deltas — a pair of
;             no-op adds when both deltas are 0
;   clobbers: A, N, Z, C, V
;   assumes:  once per frame from the scene tick
;   tail:     rts
cam_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cam_advance"
    lda f:SHG_POS1Y_LONG
    clc
    adc #SHG_CAM1_DY
    and #SHG_WORLD_MASK
    sta f:SHG_POS1Y_LONG
    lda f:SHG_POS2Y_LONG
    clc
    adc #SHG_CAM2_DY
    and #SHG_WORLD_MASK
    sta f:SHG_POS2Y_LONG
    rts

; =============================================================================
; cam_stamp_band1 — band 1's four origin registers, written directly from the
; LIVE camera-1 position. VBlank or forced blank ONLY: all four are write-twice
; ports on the shared Mode-7 ValueLatch, and the only legal writer during
; active display is HDMA. Runs at enter (the seed) and every armed VBlank (the
; seam fire left band 2's values in the registers; band 1 of the NEXT frame
; needs its own back). Per register: load the word A16, drop to A8 (B keeps the
; high byte), write lo, XBA, write hi — the per-register lo/hi order the shared
; latch requires. WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced).
; Clobbers A.
; =============================================================================
cam_stamp_band1:
    .a16
    .i16
    lda f:SHG_POS1X_LONG
    sep #$20
    .a8
    sta a:$211F
    xba
    sta a:$211F                     ; M7X
    rep #$20
    .a16
    lda f:SHG_POS1Y_LONG
    sep #$20
    .a8
    sta a:$2120
    xba
    sta a:$2120                     ; M7Y
    rep #$20
    .a16
    lda f:SHG_POS1X_LONG
    sec
    sbc #SHG_HALF_W
    sep #$20
    .a8
    sta a:$210D
    xba
    sta a:$210D                     ; M7HOFS = posx - 128
    rep #$20
    .a16
    lda f:SHG_POS1Y_LONG
    sec
    sbc #SHG_SEAM
    sep #$20
    .a8
    sta a:$210E
    xba
    sta a:$210E                     ; M7VOFS = posy - 112 (band 1's bottom line)
    rep #$20
    .a16
    rts

; =============================================================================
; cam_stamp_stage — band 2's four origin words from the LIVE camera-2 position,
; into the staged GP-DMA source blocks. Word layout matches the DMA mode-$03
; send order (little-endian word = reg lo then reg hi), which is exactly the
; per-register lo/hi pairing the shared ValueLatch needs:
;  SHG_STAGE_XY: [M7X word][M7Y word] SHG_STAGE_HV: [HOFS word][VOFS word]
; Re-run every VBlank — with the cameras moving these eight bytes genuinely
; change each frame, which is what the seam fire is delivering. WIDTH-RISK:
; entry A16/I16; exits A16/I16 (no width toggles). Clobbers A.
; =============================================================================
cam_stamp_stage:
    .a16
    .i16
    lda f:SHG_POS2X_LONG
    sta f:SHG_STAGE_XY_LONG + 0     ; M7X
    sec
    sbc #SHG_HALF_W
    sta f:SHG_STAGE_HV_LONG + 0     ; HOFS = posx - 128
    lda f:SHG_POS2Y_LONG
    sta f:SHG_STAGE_XY_LONG + 2     ; M7Y
    sec
    sbc #SHG_LINES
    sta f:SHG_STAGE_HV_LONG + 2     ; VOFS = posy - 224 (band 2's bottom line)
    rts

.ifndef SHG_HDMA_ORIGIN
; =============================================================================
; cam_rearm_live — the seam pair's LIVE channel registers (DMAP/BBAD/A1B +
; A1T/DAS), for the boot window between CLI and the first armed NMI's shadow
; MVN. After that first MVN the shadow is the re-arm path and this routine has
; no caller in steady state. WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep
; balanced). Clobbers A.
; =============================================================================
cam_rearm_live:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_H_SHGXY_DMAP
    sta a:SHG_XY_REGS + 0
    lda #ES_H_SHGXY_BBAD
    sta a:SHG_XY_REGS + 1
    lda #ES_SHG_TBL_BANK
    sta a:SHG_XY_REGS + 4
    lda #ES_H_SHGHV_DMAP
    sta a:SHG_HV_REGS + 0
    lda #ES_H_SHGHV_BBAD
    sta a:SHG_HV_REGS + 1
    lda #ES_SHG_TBL_BANK
    sta a:SHG_HV_REGS + 4
    rep #$20
    .a16
    lda #SHG_STAGE_XY
    sta a:SHG_XY_REGS + 2           ; A1T
    lda #4
    sta a:SHG_XY_REGS + 5           ; DAS (lo+hi)
    lda #SHG_STAGE_HV
    sta a:SHG_HV_REGS + 2
    lda #4
    sta a:SHG_HV_REGS + 5
    rts

; =============================================================================
; shg_seam_irq — fire the pre-armed pair in the blanking gap between band 1's
; last line and band 2's first. The game defines SF_IRQ_VECTOR = shg_seam_irq
; before header.inc.
;
; Contract: DB=$00 and DP=$0000 template-wide (init.inc; never changed), so the
; a:/f: addressing here is valid from any interrupt point. Preserves A (16-bit
; push); X/Y untouched; P restored by rti. Critical section = entry .. The
; MDMAEN write (the HBlank spin + ~5 A8 instructions); everything after the
; fire is measurement tail and may spill into the next line freely (no register
; writes). RE-MEASURED for THIS rail rather than reused: the seam trial's
; own figures bound a handler running alone, and this one runs in a composition
; with a third active channel.
; WIDTH-RISK: IRQ entry width UNKNOWN -> rep #$20 before the 16-bit save; the
; body runs A8; exits rep #$20 + 16-bit pla; rti restores caller P (and with it
; the caller's widths).
; =============================================================================
shg_seam_irq:
    rep #$20
    .a16
    pha
    sep #$20
    .a8
    lda a:$2137                     ; latch entry H/V (WRIO bit 7: power-on
                                    ; $FF, InternalRegisters.cpp:33)
    lda a:$213F                     ; reset the OPHCT/OPVCT read toggles
    lda a:$213C
    sta f:SHG_CNT_ENTH_LONG         ; entry H low 8
    lda a:$213C
    and #1
    sta f:SHG_CNT_ENTH_LONG + 1     ; entry H bit 8
    lda a:$213D
    sta f:SHG_CNT_ENTV_LONG         ; entry V low 8
    lda a:$213D
    and #1
    sta f:SHG_CNT_ENTV_LONG + 1     ; entry V bit 8
@spin:                              ; gate on the HBlank flag: sets at dot 274
    .a8                             ; ($4212 bit 6); the HDMA event at dot 276
    bit a:$4212                     ; stalls the CPU, so the fire below always
    bvc @spin                       ; lands strictly after that line's HDMA
    lda #((1 << ES_H_SHGXY_CH) | (1 << ES_H_SHGHV_CH))
    sta a:$420B                     ; MDMAEN FIRE: 8 bytes -> the four
                                    ; write-twice pairs, channel order
    lda a:$2137                     ; re-latch IMMEDIATELY: the completion point
    ; --- non-critical tail ---
    lda a:$4211                     ; TIMEUP read: ack, or the line re-fires
    lda a:$213F
    lda a:$213C
    sta f:SHG_CNT_FIREH_LONG
    lda a:$213C
    and #1
    sta f:SHG_CNT_FIREH_LONG + 1
    lda a:$213D
    sta f:SHG_CNT_FIREV_LONG
    lda a:$213D
    and #1
    sta f:SHG_CNT_FIREV_LONG + 1
    rep #$20
    .a16
    lda f:SHG_CNT_IRQ_LONG
    inc a
    sta f:SHG_CNT_IRQ_LONG          ; fire counter: lockstep with sm_frame
    pla
    rti

.else
; =============================================================================
; cam_stamp_otbl — both bands' origin values into the GOLD control build's HDMA
; tables, from the same live positions the subject build stages. 16-bit stores
; land [lo, hi] per value slot. Caller guarantees VBlank or forced blank — the
; tables are read by the HDMA init fetch at line 0. WIDTH-RISK: entry A16/I16;
; exits A16/I16 (no width toggles). Clobbers A.
; =============================================================================
cam_stamp_otbl:
    .a16
    .i16
    lda f:SHG_POS1X_LONG
    sta f:SHG_OTBL_XY_LONG + 1      ; M7X (band 1)
    sec
    sbc #SHG_HALF_W
    sta f:SHG_OTBL_HV_LONG + 1      ; M7HOFS
    lda f:SHG_POS1Y_LONG
    sta f:SHG_OTBL_XY_LONG + 3      ; M7Y
    sec
    sbc #SHG_SEAM
    sta f:SHG_OTBL_HV_LONG + 3      ; M7VOFS
    lda f:SHG_POS2X_LONG
    sta f:SHG_OTBL_XY_LONG + 6      ; M7X (band 2)
    sec
    sbc #SHG_HALF_W
    sta f:SHG_OTBL_HV_LONG + 6
    lda f:SHG_POS2Y_LONG
    sta f:SHG_OTBL_XY_LONG + 8      ; M7Y
    sec
    sbc #SHG_LINES
    sta f:SHG_OTBL_HV_LONG + 8
    rts
.endif

; =============================================================================
; cam_vblank — the per-frame VBlank work, called from sm_nmi_hook. Subject
; build: re-establish band 1's registers (the seam fire replaced them
; mid-frame) and re-stage band 2's eight bytes — both from the positions the
; tick just advanced. The A1T/DAS re-arm is NOT here: it is sm_nmi_core's
; shadow MVN, which runs after the hook returns. Control build: re-stamp the
; table value slots. WIDTH-RISK: A8 entry -> rep to A16 for the stampers ->
; sep back to A8.
; =============================================================================
; CONTRACT cam_vblank
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the table VALUE slots re-stamped — the registers themselves
;             are HDMA's to write from line 0
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
cam_vblank:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "cam_vblank"
    rep #$20
    .a16
.ifndef SHG_HDMA_ORIGIN
    jsr cam_stamp_band1
    jsr cam_stamp_stage
.else
    jsr cam_stamp_otbl
.endif
    sep #$20
    .a8
    rts
