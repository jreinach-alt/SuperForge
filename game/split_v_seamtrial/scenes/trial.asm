; =============================================================================
; scenes/trial.asm — the sweep that drives the seam, and nothing else
; =============================================================================
; THE WHOLE DIRECTOR, in one place:
;
;   spreadf += SVS_SPR_STEP  while opening, -= while closing   (8.8, triangle)
;   spread   = spreadf >> 8                 the integer split_v_bg reads
;   mid      = SVS_MID_CAM                  fixed: the trial does not pan
;
; and split_v_bg turns (mid, spread) into cam A, cam B and the divider band.
;
; TWO CELLS OF STATE. split_v_fight's director is four (two fighter positions,
; an ease accumulator, a crossover latch) because its spread chases a target
; that moves; here the target IS the ramp, so there is nothing to chase and
; nothing to latch but the triangle's phase. That reduction is what makes the
; rail an isolation of the mechanism -- see the game.toml header.
;
; THE FRACTION IS LOAD-BEARING. SVS_SPR_STEP is $00C0 = 0.75 px/frame. Stepping
; the INTEGER spread instead would move both cameras 1 px at a time and the
; "continuous divergence" this rail is named for would be a stair; the whole
; claim is that the halves part without a pop.

.scope trial

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr sv_arm                      ; stage + bevel VRAM, layers, window recipe
    ; ---- the sweep's opening state ---------------------------------------
    ; Power-on WRAM is random, so these four stores ARE the write-before-read
    ; contract (rule 5) -- not defensive initialisation. In particular a random
    ; US_SDIR would decide the triangle's phase, and a random ES_SV_SPREAD
    ; would be committed by the first NMI before `tick` ever ran.
    stz z:US_SPREADF
    stz z:US_SDIR
    stz z:ES_SV_SPREAD
    lda #SVS_MID_CAM
    sta z:ES_SV_MID                 ; fixed for the whole run: only the
                                    ; divergence moves, never the viewpoint
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on split_v_bg's
    ; behalf (see that feature.toml's attribution note). TM leaves OBJ OFF:
    ; this rail composes no sprite feature, so power-on-random OAM must not be
    ; able to reach the screen (rule 5).
    sep #$20
    .a8
    lda #SVS_BGMODE
    sta a:$2105                     ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    lda #SVS_TM
    sta a:$212C                     ; TM: BG1 + BG2 + BG3 on main, no OBJ
    rep #$20
    .a16
    rts

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
tick:
    .a16
    .i16
    jsr sweep
    rts

; --- exit -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
; Single-scene rail: nothing follows, but the window is disarmed anyway so the
; feature cannot leave a mask armed over a screen it no longer owns -- the
; disarm discipline window_iris exists to enforce, and the same one
; split_v_fight's exit pays.
exit:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$212E                     ; TMW
    rep #$20
    .a16
    rts

; --- sweep: the triangle wave, and the integer split_v_bg reads -------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Opening and closing are separate arms rather than a signed step because the
; CLAMPS differ: opening pins to SVS_SPREAD_MAX exactly (so the widest state is
; a settled value a proof frame can land on), closing pins to zero exactly (so
; the merged state is EXACTLY identical cameras, not "within a fraction of a
; pixel"). A signed step would reach neither endpoint cleanly at 0.75/frame.
; THE 8.8 CAP IS BUILT WITH `xba`, NOT WRITTEN DOWN. `SVS_SPREAD_MAX * 256` is
; the obvious spelling and `no_literals` refuses it -- it reads the `256` as a
; raw address operand, correctly, because it cannot know which literals are
; scale factors. `lda #SVS_SPREAD_MAX` + `xba` is the same value with the
; declared constant still doing the work, and it costs one cycle.
sweep:
    .a16
    .i16
    lda z:US_SDIR
    bne @closing
    ; ---- opening: grow toward the cap ------------------------------------
    lda z:US_SPREADF
    clc
    adc #SVS_SPR_STEP
    tax                             ; X = the candidate, across the width-safe
                                    ; integer test below (A16/I16, so `tax`
                                    ; moves all 16 bits -- no truncation)
    xba
    and #$00FF                      ; the candidate's INTEGER part
    cmp #SVS_SPREAD_MAX
    bcs @cap
    txa
    sta z:US_SPREADF
    bra @publish
@cap:
    .a16
    .i16
    lda #SVS_SPREAD_MAX
    xba                             ; = SVS_SPREAD_MAX in 8.8, exactly
    sta z:US_SPREADF
    lda #1
    sta z:US_SDIR
    bra @publish
@closing:
    .a16
    .i16
    ; ---- closing: shrink toward zero -------------------------------------
    lda z:US_SPREADF
    cmp #SVS_SPR_STEP
    bcs @sub
    lda #0                          ; would cross zero: pin AT zero, reopen.
    sta z:US_SPREADF                ; the merged frame is the rail's headline
    stz z:US_SDIR                   ; claim, so it must be exact
    bra @publish
@sub:
    .a16
    .i16
    sec
    sbc #SVS_SPR_STEP
    sta z:US_SPREADF
@publish:
    .a16
    .i16
    ; ---- spread = spreadf >> 8 (the high byte) ---------------------------
    lda z:US_SPREADF
    xba
    and #$00FF
    sta z:ES_SV_SPREAD
    rts

.endscope
