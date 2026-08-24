; =============================================================================
; sit_cam.asm — the seam-IRQ trial: two frozen cameras, band 2 by IRQ + GP-DMA
; =============================================================================
; The mechanism, per channel:
;
;  ch ES_H_SITAB_CH DMAP $43 (mode 3 + INDIRECT) -> M7A/M7B whole frame
;  ch ES_H_SITCD_CH DMAP $43 -> M7C/M7D whole frame
;  Each index table holds TWO band-local repeat entries streaming the
;  SAME fixed-angle 448 B pose — band 2's entry re-starts it at line
;  112. In the HDMAEN mask; armed via the sm_hdma shadow.
;
;  ch ES_H_SITXY_CH DMAP $03 (mode 3, DIRECT) -> M7X/M7Y band 2
;  ch ES_H_SITHV_CH DMAP $03 -> M7HOFS/M7VOFS band 2
;  THE TRIAL: pre-armed as GP-DMA (A1T -> a 4-byte staged block, DAS=4),
;  NEVER in the HDMAEN mask, fired by ONE MDMAEN write from the seam
;  IRQ handler in scanline 112's trailing HBlank. Their A1T/DAS are
;  consumed by every fire and re-armed by sm_nmi_core's shadow MVN
;  every armed VBlank — the DAS-is-single-shot lesson, riding the
;  engine's own re-arm path (the sm_hdma comment's "channels re-init
;  cleanly even when a GP-DMA time-shared their registers", proven
;  here in the direction it was written for).
;
;  Under -DSIT_HDMA_ORIGIN (the CONTROL) the same two channels instead
;  carry the classic 11-byte origin tables ([112,X,Y][1,X,Y][0], non-repeat
;  counts: fire once, hold) and ARE in the HDMAEN mask; no IRQ, no vector,
;  no VTIME. Same DMAP, same BBAD, same values — the gold assertion is
;  default vs control framebuffers BYTE-IDENTICAL on an absolute frame.
;
;  Under -DSIT_MISTIME (the NON-VACUITY control) VTIME = 60: the same fire
;  lands in scanline 60's HBlank, so content lines 60..111 render with
;  band 2's warm origin and the SAME full-frame metric flips.
;
; Contract: template-wide DB=$00; every WRAM touch is long-addressed, so no DB
; assumption anywhere in this file (the IRQ handler interrupts the main loop
; wherever it is).

; --- geometry: the world, the seam, the two frozen cameras -------------------
; DERIVED, not narrated: the map wraps at SIT_MAP_T tiles (the PPU samples Mode
; 7 modulo 128) and the warm/cool stripe period is the generator's own STRIPE
; constant — camera 1 sits mid-world on a COOL stripe centre, camera 2 exactly
; one stripe east on a WARM one. Band-2 red is the position oracle.
SIT_TILE_PX   = 8
SIT_MAP_T     = 128
.assert ES_R_SIT_MAP_SIZE = SIT_MAP_T * SIT_MAP_T * 2, error, "sit_cam: the map blob is not the 128x128 interleaved image the wrap math assumes"
SIT_WORLD_PX  = SIT_MAP_T * SIT_TILE_PX     ; 1024
SIT_STRIPE_T  = 32                          ; the generator's STRIPE
SIT_STRIPE_PX = SIT_STRIPE_T * SIT_TILE_PX  ; 256 px per colour stripe
SIT_SEAM      = 112                         ; band 1 = 0..111, band 2 = 112..223
SIT_LINES     = 224
SIT_HALF_W    = 128                         ; half the 256-px screen

SIT_P1_X0 = SIT_WORLD_PX / 2                ; 512: camera 1, COOL stripe
SIT_P1_Y0 = SIT_WORLD_PX / 2
SIT_P2_X0 = SIT_P1_X0 + SIT_STRIPE_PX       ; 768: camera 2, WARM stripe
SIT_P2_Y0 = SIT_P1_Y0

; Band origins at the fixed heading: pure subtraction, no solve. VOFS is the
; camera Y minus the band's own BOTTOM scanline (band-local pose tables).
SIT_B1_HOFS = SIT_P1_X0 - SIT_HALF_W
SIT_B1_VOFS = SIT_P1_Y0 - SIT_SEAM
SIT_B2_HOFS = SIT_P2_X0 - SIT_HALF_W
SIT_B2_VOFS = SIT_P2_Y0 - SIT_LINES

; --- the IRQ line (V-only; internal scanlines — irq.asm's contract) ----------
.ifdef SIT_MISTIME
SIT_VTIME = 60                  ; mid-band-1 fire: the corruption control
.else
SIT_VTIME = SIT_SEAM            ; content line 111 draws during internal
                                ; scanline 112; the fire lands in its trailing
                                ; HBlank and content line 112 picks it up
.endif

; --- sit_tbl layout (68 B; the toml carries the map) -------------------------
SIT_IDX_AB        = ES_SIT_TBL + 0          ; 7 B  AB index table
SIT_IDX_CD        = ES_SIT_TBL + 16         ; 7 B  CD index table
SIT_STAGE_XY      = ES_SIT_TBL + 32         ; 4 B  staged M7X/M7Y (sitxy A1T)
SIT_STAGE_HV      = ES_SIT_TBL + 36         ; 4 B  staged HOFS/VOFS (sithv A1T)
SIT_OTBL_XY       = ES_SIT_TBL + 40         ; 11 B origin table (control only)
SIT_OTBL_HV       = ES_SIT_TBL + 56         ; 11 B origin table (control only)
SIT_IDX_AB_LONG   = ES_SIT_TBL_LONG + 0
SIT_IDX_CD_LONG   = ES_SIT_TBL_LONG + 16
SIT_STAGE_XY_LONG = ES_SIT_TBL_LONG + 32
SIT_STAGE_HV_LONG = ES_SIT_TBL_LONG + 36
SIT_OTBL_XY_LONG  = ES_SIT_TBL_LONG + 40
SIT_OTBL_HV_LONG  = ES_SIT_TBL_LONG + 56

; --- sit_cnt layout (12 B; the trial's evidence surface) ---------------------
SIT_CNT_IRQ_LONG  = ES_SIT_CNT_LONG + 0     ; u16 seam-IRQ fire count
SIT_CNT_WAKE_LONG = ES_SIT_CNT_LONG + 2     ; u16 raw wai wakes (main.asm's)
SIT_CNT_ENTH_LONG = ES_SIT_CNT_LONG + 4     ; entry OPHCT lo, hi bit
SIT_CNT_ENTV_LONG = ES_SIT_CNT_LONG + 6     ; entry OPVCT lo, hi bit
SIT_CNT_FIREH_LONG = ES_SIT_CNT_LONG + 8    ; post-fire OPHCT lo, hi bit
SIT_CNT_FIREV_LONG = ES_SIT_CNT_LONG + 10   ; post-fire OPVCT lo, hi bit

; --- the channel register files (live writes: boot arm + the fire) -----------
SIT_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8      ; 16 B of register file per channel
SIT_XY_REGS = $4300 + ES_H_SITXY_CH * 16
SIT_HV_REGS = $4300 + ES_H_SITHV_CH * 16

; =============================================================================
; sit_arm — build every table, stage every channel (scene enter). In/out:
; A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X. The caller ORs the
; HDMAEN bits into the scene_mgr shadow after (matrix pair always; plus the
; origin pair ONLY under -DSIT_HDMA_ORIGIN — the seam channels staying out of
; that mask IS the shipping mechanism).
; =============================================================================
sit_arm:
    .a16
    .i16
    ; ---- the declared init contract: zero BOTH claims first ----------------
    ; Power-on WRAM is random; the DMA controller's terminator processing still
    ; fetches address bytes after a $00 count, so even never-stamped table tail
    ; bytes must not be garbage (sh2_cam's sh2_arm and mode7_persp's persp_arm
    ; are the precedent, and open the same way). The counters
    ; must start at 0 for the cadence assertions to mean anything at all.
    lda #0
    ldx #(ES_SIT_TBL_SIZE - 2)
:   sta f:ES_SIT_TBL_LONG, x
    dex
    dex
    bpl :-
    ldx #(ES_SIT_CNT_SIZE - 2)
:   sta f:ES_SIT_CNT_LONG, x
    dex
    dex
    bpl :-

    ; ---- matrix index tables: two band-local repeat entries each -----------
    ; 128 is the HDMA repeat flag; 128|112 = "a NEW 4-byte unit every scanline,
    ; 112 times". Entry 2 re-starts the SAME pose at line 112 — both bands
    ; stream one table; position alone distinguishes them.
    sep #$20
    .a8
    lda #(128 | SIT_SEAM)
    sta f:SIT_IDX_AB_LONG + 0       ; band 1: lines 0..111
    sta f:SIT_IDX_AB_LONG + 3       ; band 2: lines 112..223
    sta f:SIT_IDX_CD_LONG + 0
    sta f:SIT_IDX_CD_LONG + 3
    lda #0
    sta f:SIT_IDX_AB_LONG + 6       ; terminators
    sta f:SIT_IDX_CD_LONG + 6
    rep #$20
    .a16
    lda #ES_R_SIT_POSE_AB_ADDR      ; both entries -> the one fixed pose
    sta f:SIT_IDX_AB_LONG + 1
    sta f:SIT_IDX_AB_LONG + 4
    lda #ES_R_SIT_POSE_CD_ADDR
    sta f:SIT_IDX_CD_LONG + 1
    sta f:SIT_IDX_CD_LONG + 4

    ; ---- band 1's origin registers (the SEED) + band 2's staged bytes ------
    jsr sit_stamp_band1             ; forced blank: write-twice pairs safe
    jsr sit_stamp_stage

    ; ---- channel shadow: the matrix pair (INDIRECT) ------------------------
    ; A1B is the INDEX table's bank ($7E); DASB ($43x7) is the POSE blob's —
    ; getting those two the wrong way round is the classic indirect-HDMA bug,
    ; which is why both come from emitted symbols.
    sep #$20
    .a8
    ldx #(ES_H_SITAB_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITAB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 2-regs-write-twice
    lda #ES_H_SITAB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B
    lda #ES_R_SIT_POSE_AB_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB
    rep #$20
    .a16
    lda #SIT_IDX_AB
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    sep #$20
    .a8
    ldx #(ES_H_SITCD_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITCD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SITCD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_SIT_POSE_CD_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #SIT_IDX_CD
    sta f:ES_SM_HDMA_LONG+2, x

.ifndef SIT_HDMA_ORIGIN
    ; ---- THE TRIAL: seam pair staged as GP-DMA -----------------------------
    ; The shadow slots carry the full GP-DMA config; sm_nmi_core's MVN
    ; re-stamps the live registers from them every armed VBlank, which IS the
    ; per-frame A1T/DAS re-arm. DAS is written 16-bit so its high byte is
    ; explicit rather than left over from the transition clear.
    sep #$20
    .a8
    ldx #(ES_H_SITXY_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITXY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP $03: A->B, 2 regs write twice
    lda #ES_H_SITXY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7X
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the stage block's bank
    rep #$20
    .a16
    lda #SIT_STAGE_XY
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T
    lda #4
    sta f:ES_SM_HDMA_LONG+5, x      ; DAS = 4 (lo+hi)
    sep #$20
    .a8
    ldx #(ES_H_SITHV_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITHV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SITHV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7HOFS
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SIT_STAGE_HV
    sta f:ES_SM_HDMA_LONG+2, x
    lda #4
    sta f:ES_SM_HDMA_LONG+5, x
    ; ---- and the LIVE registers, for fires before the first armed NMI ------
    ; The arm sequence CLIs at the end of boot; the first VBlank MVN has not
    ; run yet, so a seam fire in that window would read power-on channel
    ; registers (DAS random -> an arbitrary-length transfer). Write them now,
    ; under forced blank, so the very first fire is already correct.
    jsr sit_rearm_live
.else
    ; ---- THE CONTROL: the classic origin channel pair ----------------------
    ; Non-repeat counts — the opposite reading of the same byte: 112 means
    ; "transfer the 4-byte unit ONCE, then idle 111 lines", then the count-1
    ; entry fires band 2's values at line 112 and the terminator ends the
    ; channel (the write-twice latch holds the value to the frame's bottom).
    ; The line-0 unit delivers band 1's own values — the same bytes the seed
    ; wrote — so the seed's overrider arrives at the top of every frame.
    sep #$20
    .a8
    lda #SIT_SEAM
    sta f:SIT_OTBL_XY_LONG + 0
    sta f:SIT_OTBL_HV_LONG + 0
    lda #1
    sta f:SIT_OTBL_XY_LONG + 5
    sta f:SIT_OTBL_HV_LONG + 5
    lda #0
    sta f:SIT_OTBL_XY_LONG + 10     ; terminators
    sta f:SIT_OTBL_HV_LONG + 10
    rep #$20
    .a16
    jsr sit_stamp_otbl
    ; shadow staging: SAME DMAP, SAME BBAD as the trial build — the whole delta
    ; is A1T (table vs stage block) and the HDMAEN mask bit.
    sep #$20
    .a8
    ldx #(ES_H_SITXY_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITXY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SITXY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SIT_OTBL_XY
    sta f:ES_SM_HDMA_LONG+2, x
    sep #$20
    .a8
    ldx #(ES_H_SITHV_CH * SIT_SHDW_CH_SIZE)
    lda #ES_H_SITHV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SITHV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SIT_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SIT_OTBL_HV
    sta f:ES_SM_HDMA_LONG+2, x
.endif
    rts

; =============================================================================
; sit_stamp_band1 — band 1's four origin registers, written directly. VBlank or
; forced blank ONLY: all four are write-twice ports on the shared Mode-7
; ValueLatch, and the only legal writer during active display is HDMA. Runs at
; enter (the seed) and every armed VBlank (the seam fire left band 2's values
; in the registers; band 1 of the NEXT frame needs its own back). WIDTH-RISK:
; entry A16/I16; exits A16/I16 (sep/rep balanced). Clobbers A.
; =============================================================================
sit_stamp_band1:
    .a16
    .i16
    sep #$20
    .a8
    lda #<SIT_P1_X0
    sta a:$211F
    lda #>SIT_P1_X0
    sta a:$211F                     ; M7X
    lda #<SIT_P1_Y0
    sta a:$2120
    lda #>SIT_P1_Y0
    sta a:$2120                     ; M7Y
    lda #<SIT_B1_HOFS
    sta a:$210D
    lda #>SIT_B1_HOFS
    sta a:$210D                     ; M7HOFS
    lda #<SIT_B1_VOFS
    sta a:$210E
    lda #>SIT_B1_VOFS
    sta a:$210E                     ; M7VOFS
    rep #$20
    .a16
    rts

; =============================================================================
; sit_stamp_stage — band 2's 8 origin bytes into the staged GP-DMA source
; blocks. Byte order per block = the DMA mode-$03 send order: reg lo, reg hi,
; reg+1 lo, reg+1 hi — which is exactly the per-register lo/hi pairing the
; shared ValueLatch needs. Static values here; a live-seam game would rewrite
; these in its VBlank hook, which is why the routine runs there every frame.
; WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep balanced). Clobbers A.
; =============================================================================
sit_stamp_stage:
    .a16
    .i16
    sep #$20
    .a8
    lda #<SIT_P2_X0
    sta f:SIT_STAGE_XY_LONG + 0
    lda #>SIT_P2_X0
    sta f:SIT_STAGE_XY_LONG + 1
    lda #<SIT_P2_Y0
    sta f:SIT_STAGE_XY_LONG + 2
    lda #>SIT_P2_Y0
    sta f:SIT_STAGE_XY_LONG + 3
    lda #<SIT_B2_HOFS
    sta f:SIT_STAGE_HV_LONG + 0
    lda #>SIT_B2_HOFS
    sta f:SIT_STAGE_HV_LONG + 1
    lda #<SIT_B2_VOFS
    sta f:SIT_STAGE_HV_LONG + 2
    lda #>SIT_B2_VOFS
    sta f:SIT_STAGE_HV_LONG + 3
    rep #$20
    .a16
    rts

.ifndef SIT_HDMA_ORIGIN
; =============================================================================
; sit_rearm_live — the seam pair's LIVE channel registers (DMAP/BBAD/A1B +
; A1T/DAS), for the boot window between CLI and the first armed NMI's shadow
; MVN. After that first MVN the shadow is the re-arm path and this routine has
; no caller in steady state. WIDTH-RISK: entry A16/I16; exits A16/I16 (sep/rep
; balanced). Clobbers A.
; =============================================================================
sit_rearm_live:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_H_SITXY_DMAP
    sta a:SIT_XY_REGS + 0
    lda #ES_H_SITXY_BBAD
    sta a:SIT_XY_REGS + 1
    lda #ES_SIT_TBL_BANK
    sta a:SIT_XY_REGS + 4
    lda #ES_H_SITHV_DMAP
    sta a:SIT_HV_REGS + 0
    lda #ES_H_SITHV_BBAD
    sta a:SIT_HV_REGS + 1
    lda #ES_SIT_TBL_BANK
    sta a:SIT_HV_REGS + 4
    rep #$20
    .a16
    lda #SIT_STAGE_XY
    sta a:SIT_XY_REGS + 2           ; A1T
    lda #4
    sta a:SIT_XY_REGS + 5           ; DAS (lo+hi)
    lda #SIT_STAGE_HV
    sta a:SIT_HV_REGS + 2
    lda #4
    sta a:SIT_HV_REGS + 5
    rts

; =============================================================================
; sit_seam_irq — the trial's core: fire the pre-armed pair in the blanking gap
; between band 1's last line and band 2's first. The game defines
; SF_IRQ_VECTOR = sit_seam_irq before header.inc.
;
; Contract: DB=$00 and DP=$0000 template-wide (init.inc; never changed), so the
; a:/f: addressing here is valid from any interrupt point. Preserves A (16-bit
; push); X/Y untouched; P restored by rti. Critical section = entry .. The
; MDMAEN write (the HBlank spin + ~5 A8 instructions); everything after the
; fire is measurement tail and may spill into the next line freely (no register
; writes). WIDTH-RISK: IRQ entry width UNKNOWN -> rep #$20 before the 16-bit
; save; the body runs A8; exits rep #$20 + 16-bit pla; rti restores caller P
; (and with it the caller's widths).
; =============================================================================
sit_seam_irq:
    rep #$20
    .a16
    pha
    sep #$20
    .a8
    lda a:$2137                     ; latch entry H/V (WRIO bit 7: power-on
                                    ; $FF, InternalRegisters.cpp:33)
    lda a:$213F                     ; reset the OPHCT/OPVCT read toggles
    lda a:$213C
    sta f:SIT_CNT_ENTH_LONG         ; entry H low 8
    lda a:$213C
    and #1
    sta f:SIT_CNT_ENTH_LONG + 1     ; entry H bit 8
    lda a:$213D
    sta f:SIT_CNT_ENTV_LONG         ; entry V low 8
    lda a:$213D
    and #1
    sta f:SIT_CNT_ENTV_LONG + 1     ; entry V bit 8
@spin:                              ; gate on the HBlank flag: sets at dot 274
    .a8                             ; ($4212 bit 6); the HDMA event at dot 276
    bit a:$4212                     ; stalls the CPU, so the fire below always
    bvc @spin                       ; lands strictly after that line's HDMA
    lda #((1 << ES_H_SITXY_CH) | (1 << ES_H_SITHV_CH))
    sta a:$420B                     ; MDMAEN FIRE: 8 bytes -> the four
                                    ; write-twice pairs, channel order
    lda a:$2137                     ; re-latch IMMEDIATELY: the completion point
    ; --- non-critical tail ---
    lda a:$4211                     ; TIMEUP read: ack, or the line re-fires
    lda a:$213F
    lda a:$213C
    sta f:SIT_CNT_FIREH_LONG
    lda a:$213C
    and #1
    sta f:SIT_CNT_FIREH_LONG + 1
    lda a:$213D
    sta f:SIT_CNT_FIREV_LONG
    lda a:$213D
    and #1
    sta f:SIT_CNT_FIREV_LONG + 1
    rep #$20
    .a16
    lda f:SIT_CNT_IRQ_LONG
    inc a
    sta f:SIT_CNT_IRQ_LONG          ; fire counter: lockstep with sm_frame
    pla
    rti

.else
; =============================================================================
; sit_stamp_otbl — both bands' origin values into the control build's HDMA
; tables (static positions, stamped once).
; 16-bit stores land [lo, hi] per value slot. Caller guarantees VBlank or
; forced blank — the tables are read by the HDMA init fetch at line 0.
; WIDTH-RISK: entry A16/I16; exits A16/I16 (no width toggles). Clobbers A.
; =============================================================================
sit_stamp_otbl:
    .a16
    .i16
    lda #SIT_P1_X0
    sta f:SIT_OTBL_XY_LONG + 1      ; M7X (band 1)
    lda #SIT_P1_Y0
    sta f:SIT_OTBL_XY_LONG + 3      ; M7Y
    lda #SIT_B1_HOFS
    sta f:SIT_OTBL_HV_LONG + 1      ; M7HOFS
    lda #SIT_B1_VOFS
    sta f:SIT_OTBL_HV_LONG + 3      ; M7VOFS
    lda #SIT_P2_X0
    sta f:SIT_OTBL_XY_LONG + 6      ; M7X (band 2)
    lda #SIT_P2_Y0
    sta f:SIT_OTBL_XY_LONG + 8
    lda #SIT_B2_HOFS
    sta f:SIT_OTBL_HV_LONG + 6
    lda #SIT_B2_VOFS
    sta f:SIT_OTBL_HV_LONG + 8
    rts
.endif

; =============================================================================
; sit_vblank — the per-frame VBlank work, called from sm_nmi_hook. Trial
; build: re-establish band 1's registers (the seam fire replaced them) and
; re-stamp the staged bytes (static here; the live-seam shape kept honest).
; The A1T/DAS re-arm is NOT here — it is sm_nmi_core's shadow MVN, which runs
; after the hook returns. Control build: re-stamp the table value slots (the
; registers themselves are HDMA's to write from line 0). In/out: A8/I16, DB=0
; (the sm_nmi_hook contract). Clobbers A. WIDTH-RISK: A8 entry -> rep to A16
; for the stampers -> sep back to A8.
; =============================================================================
sit_vblank:
    .a8
    .i16
    rep #$20
    .a16
.ifndef SIT_HDMA_ORIGIN
    jsr sit_stamp_band1
    jsr sit_stamp_stage
.else
    jsr sit_stamp_otbl
.endif
    sep #$20
    .a8
    rts
