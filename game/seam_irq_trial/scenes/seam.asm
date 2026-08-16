; =============================================================================
; scenes/seam.asm — the trial scene: one plane, two frozen cameras, one seam
; =============================================================================
; Enter uploads the plane, builds every table, stages four channel shadows and
; arms the HDMAEN mask — the MATRIX pair always; the seam pair's bits ONLY
; under -DSIT_HDMA_ORIGIN, because keeping them OUT of that mask on the trial
; build IS the mechanism under test (they fire by MDMAEN from the IRQ
; handler; tools/plants/seam_irq_trial.py plants the wrongly-included case
; and the tests must go red).
;
; The IRQ ARM is NOT here: scene enter runs with NMI masked and, on a scene
; switch, scene_mgr rewrites NMITIMEN to $81 AFTER enter returns
; (`@switch`'s $81 restore) — a V-IRQ bit raised here would not survive the
; restore. The arm lives in MAIN's boot block (main.asm), after the enter
; call, per irq.asm's sequence contract. On this single-scene rail that is
; the only path; a multi-scene IRQ game re-arms in its own post-switch code.
;
; The TICK is empty and that is the point: both cameras are frozen (cross-ROM
; pixel equality is the gold assertion, and motion would turn it into a
; phase-alignment question). The whole per-frame mechanism runs in the NMI
; hook (sit_vblank) and the seam handler.

.scope seam

; --- enter -------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 5 colours + M7SEL
    jsr sit_arm                     ; tables + stampers + four channel shadows

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are sit_floor's `scene_writes` (see that toml's
    ; attribution note). Written once, for all 224 lines: this rail does not
    ; split the video mode — the split is entirely in the camera origin.
    sep #$20
    .a8
    lda #$07
    sta a:$2105                     ; BGMODE 7: the affine plane, BG1 only
    lda #SIT_TM_BG1
    sta a:$212C                     ; TM: the plane alone

    ; ---- the HDMAEN mask --------------------------------------------------
    ; scene_mgr's NMI applies this shadow every armed frame; the channel
    ; REGISTERS were staged by sit_arm into the 128-byte shadow the same NMI
    ; MVNs to $4300. The seam pair is deliberately absent on the trial build
    ; — enabled channels re-run their tables every frame, and the trial's
    ; band-2 origin has no table, only a fire.
    lda #((1 << ES_H_SITAB_CH) | (1 << ES_H_SITCD_CH))
.ifdef SIT_HDMA_ORIGIN
    ora #((1 << ES_H_SITXY_CH) | (1 << ES_H_SITHV_CH))
.endif
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY: fade_start_in is `.a8` and a 16-bit caller
    ; makes its `lda #1` eat the next opcode byte — the ROM renders black
    ; with perfect VRAM, and nothing in the build says so. A bare INIDISP
    ; write would not
    ; do: scene_mgr commits INIDISP from its own NMI shadow every frame.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ----------------------------------------------------
; In/out: A16/I16, DB=0. Nothing moves; see the header.
tick:
    .a16
    .i16
    rts

; --- exit: undo what enter armed ---------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
; The plane's VRAM/CGRAM are not torn down (the next enter re-declares what
; it owns); what IS undone is the display state this scene turned on. HDMAEN
; and NMITIMEN (which carries the V-IRQ enable) are scene_mgr's own to clear
; at the transition — the disarm-across-scenes semantics the irq feature
; leans on. No edges exist on this rail, so nothing reaches here yet; it is
; the contract, kept honest.
exit:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
