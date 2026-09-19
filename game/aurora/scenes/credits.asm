.scope credits
.include "engine_state_credits.inc"  ; GENERATED — this scene's map

; --- the scene's own features ----------------------------------------------
; Included HERE rather than at file scope because their claims are
; scene-scoped: the ES_V_/ES_C_/ES_D_ symbols they read are in the map above
; and resolve only inside this scope. The blobs they upload are at file scope
; and ca65 resolves outward, which is what makes the split work.
.include "aur_bg.asm"
.include "aur_obj.asm"
.include "aur_hue.asm"
.include "aur_write.asm"
.include "aur_pres.asm"

; --- enter: the whole picture, under forced blank --------------------------
; Nothing here is per-frame. After this the only VRAM that moves is the roll's
; thirteen map rows and the pen's tiles.
enter:
    .a16
    .i16
    jsr aur_arm_bg                  ; BG1 + BG2 CHR, both maps, both palettes
    jsr aur_obj_arm                 ; OBSEL, the OBJ page, the three figures
    jsr aur_hue_init
    jsr aur_write_init
    jsr aur_pres_init
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

; --- tick: two verbs over a piece that plays itself ------------------------
; THE HOLD HAS ONE WRITER, and it is here. B and the beats both want the
; picture to stand still, so the flag is cleared once a frame and then raised
; by whichever of them is asking — rather than latched by two writers who
; would each clear the other's.
tick:
    .a16
    .i16
    ; B stops the whole piece: the cycle, the pen AND the beats. A still of a
    ; presentation that is still advancing is not a still.
    lda z:ES_INP_CUR
    and #JOY_B
    beq :+
    sta z:ES_AUR_HOLD
    rts
:   .a16
    .i16
    stz z:ES_AUR_HOLD
    ; Start plays it again, and goes out through a fade rather than snatching
    ; the picture away.
    lda z:ES_INP_PRESS
    and #JOY_START
    beq :+
    jsr aur_pres_again
:   .a16
    .i16
    TS_STEP z:US_TSC_ACC, AUR_TICK_BASE    ; -> A = whole ticks this frame,
    pha                                    ;   the fraction carried by the
    jsr aur_pres_tick                      ;   scaler and not by the feature.
    pla                                    ; The beat runs FIRST: the hold it
    jsr aur_hue_tick                       ;   raises is what the cycle reads
    rts

exit:
    .a16
    .i16
    rts
.endscope
