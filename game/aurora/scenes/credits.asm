.scope credits
.include "engine_state_credits.inc"  ; GENERATED — this scene's map

; --- the scene's own features ----------------------------------------------
; Included HERE rather than at file scope because their claims are
; scene-scoped: the ES_V_/ES_C_/ES_D_ symbols they read are in the map above
; and resolve only inside this scope. The blobs they upload are at file scope
; and ca65 resolves outward, which is what makes the split work.
.include "aur_bg.asm"
.include "aur_obj.asm"
.include "aur_roll.asm"
.include "aur_write.asm"

; --- enter: the whole picture, under forced blank --------------------------
; Nothing here is per-frame. After this the only VRAM that moves is the roll's
; thirteen map rows and the pen's tiles.
enter:
    .a16
    .i16
    jsr aur_arm_bg                  ; BG1 + BG2 CHR, both maps, both palettes
    jsr aur_obj_arm                 ; OBSEL, the OBJ page, the three figures
    jsr aur_roll_init
    jsr aur_write_init
    stz z:US_TSC_ACC                ; TICK: ok -- the scaler's carried
    stz z:US_TSC                    ; TICK: ok -- ...and its output. Power-on
                                    ;   dp is random (rule 5)
    sep #$20
    .a8
    lda #ES_VID_CREDITS_BGMODE
    sta a:$2105                     ; BGMODE 3 — composed, not written by hand
    lda #ES_SCR_CREDITS_TM
    sta a:$212C
    lda #ES_SCR_CREDITS_TS
    sta a:$212D
    lda #ES_SCR_CREDITS_CGWSEL      ; ...and CGWSEL b0 with it: DIRECT COLOUR
    sta a:$2130                     ;   arrives through the composition, not
    rep #$20                        ;   from a literal in this file
    .a16
    rts

; --- tick: two verbs, and the roll's scaled rate ---------------------------
tick:
    .a16
    .i16
    ; B holds the roll still — the picture stops changing entirely, which is
    ; what makes a still of it worth taking.
    lda z:ES_INP_CUR
    and #JOY_B
    sta z:ES_AUR_HOLD
    ; Start writes the word again.
    lda z:ES_INP_PRESS
    and #JOY_START
    beq :+
    jsr aur_write_restart
:   .a16
    .i16
    TS_STEP z:US_TSC_ACC, AUR_PHASE_BASE   ; -> A = whole phases this frame,
    jsr aur_roll_tick                      ;   the fraction carried by the
                                           ;   scaler and not by the feature
    rts

exit:
    .a16
    .i16
    rts
.endscope
