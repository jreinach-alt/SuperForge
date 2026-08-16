; =============================================================================
; scenes/split.asm — the rail's one scene: one plane, two moving cameras, one
;                    seam, one gradient over all of it
; =============================================================================
; Enter uploads the plane, builds every table, stages five channel shadows and
; arms the HDMAEN mask — the MATRIX pair always, the GRADIENT unless
; -DSHG_NO_GRAD, and the seam pair's bits ONLY under -DSHG_HDMA_ORIGIN, because
; keeping them OUT of that mask on the subject build IS what frees the channel
; the gradient spends (they fire by MDMAEN from the IRQ handler;
; tools/plants/split_h_irq_grad_demo.py plants the wrongly-included case and
; the named test must go red).
;
; The IRQ ARM is NOT here: scene enter runs with NMI masked and, on a scene
; switch, scene_mgr rewrites NMITIMEN to $81 AFTER enter returns
; (`@switch`'s $81 restore) — a V-IRQ bit raised here would not survive it.
; The arm lives in MAIN's boot block (main.asm), after the enter call, per
; irq.asm's sequence contract. On this single-scene rail that is the only path;
; a multi-scene IRQ game re-arms in its own post-switch code.
;
; The TICK is ONE call, and it is the whole difference from `seam_irq_trial`'s
; empty one: the two cameras advance at their own speeds, outside VBlank, so
; the NMI hook that re-stamps band 1 and re-stages band 2 always reads a
; settled pair.

.scope split

; --- enter -------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 5 colours + M7SEL
    jsr cam_arm                     ; tables + positions + four channel shadows
.ifndef SHG_NO_GRAD
    jsr grad_arm                    ; the 227-byte COLDATA ramp + colour math
.endif

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are shg_floor's `scene_writes` (see that toml's attribution
    ; note). Written once, for all 224 lines: this rail does not split the video
    ; mode — the split is entirely in the camera origin.
    sep #$20
    .a8
    lda #$07
    sta a:$2105                     ; BGMODE 7: the affine plane, BG1 only
    lda #SHG_TM_BG1
    sta a:$212C                     ; TM: the plane alone

    ; ---- the HDMAEN mask --------------------------------------------------
    ; scene_mgr's NMI applies this shadow every armed frame; the channel
    ; REGISTERS were staged by cam_arm / grad_arm into the 128-byte shadow the
    ; same NMI MVNs to $4300. THE SEAM PAIR IS DELIBERATELY ABSENT on the
    ; subject build — that absence is the freed capacity, and the gradient bit
    ; below is what spends it.
    lda #((1 << ES_H_SHGAB_CH) | (1 << ES_H_SHGCD_CH))
.ifndef SHG_NO_GRAD
    ora #(1 << ES_H_SHGGR_CH)
.endif
.ifdef SHG_HDMA_ORIGIN
    ora #((1 << ES_H_SHGXY_CH) | (1 << ES_H_SHGHV_CH))
.endif
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY: fade_start_in is `.a8` and a 16-bit caller
    ; makes its `lda #1` eat the next opcode byte — the ROM renders black with
    ; perfect VRAM, which cost a real debugging round once already on
    ; `split_v_fight`. A bare INIDISP write would not do:
    ; scene_mgr commits INIDISP from its own NMI shadow every frame.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ----------------------------------------------------
; In/out: A16/I16, DB=0. Runs outside VBlank, before the frame's `wai`.
tick:
    .a16
    .i16
    jsr cam_advance                 ; camera 1 +1 px/frame in Y, camera 2 +2
    rts

; --- exit: undo what enter armed ---------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
; The plane's VRAM/CGRAM are not torn down (the next enter re-declares what it
; owns); what IS undone is the display state this scene turned on — including
; the colour math, which would otherwise wash whatever came next. HDMAEN and
; NMITIMEN (which carries the V-IRQ enable) are scene_mgr's own to clear at the
; transition — the disarm-across-scenes semantics the irq feature leans on. No
; edges exist on this rail, so nothing reaches here yet; it is the contract,
; kept honest.
exit:
    .a16
    .i16
.ifndef SHG_NO_GRAD
    jsr grad_disarm                 ; colour math off — shg_grad writes its own
                                    ; CGWSEL/CGADSUB, so no scene_writes hatch
.endif
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
