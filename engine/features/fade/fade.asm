; =============================================================================
; fade.asm — INIDISP brightness ramp (global feature)
; =============================================================================
; ES_FADE_CTL: +0 level (0..15) +1 dir (0 idle · 1 in · 2 out) fade_tick writes
; the INIDISP shadow (ES_SM_NMI+1) ONLY while ramping — when idle the shadow
; keeps whatever the phase machine set (e.g. $80 blank).

; --- fade_init: boot init contract ------------------------------------------
; In/out: A16/I16.
fade_init:
    .a16
    .i16
    stz z:ES_FADE_CTL
    rts

; --- fade_start_in / fade_start_out -----------------------------------------
; In/out: A8. Arms the ramp; fade_tick does the stepping.
fade_start_in:
    .a8
    lda #1
    sta z:ES_FADE_CTL+1
    rts
fade_start_out:
    .a8
    lda #2
    sta z:ES_FADE_CTL+1
    rts

; --- fade_tick: step the ramp one frame (call once per frame) ---------------
; In/out: A16/I16.
fade_tick:
    .a16
    .i16
    sep #$20
    .a8
    lda z:ES_FADE_CTL+1
    beq @done                   ; idle
    cmp #2
    beq @out
    ; ---- ramping in: level +1 toward 15 ------------------------------------
    lda z:ES_FADE_CTL
    inc
    sta z:ES_FADE_CTL
    cmp #15
    bcc @commit
    stz z:ES_FADE_CTL+1         ; reached full — idle
    bra @commit
@out:
    .a8
    ; ---- ramping out: level -1 toward 0 ------------------------------------
    lda z:ES_FADE_CTL
    beq @out_done
    dec
    sta z:ES_FADE_CTL
    bne @commit
@out_done:
    .a8
    stz z:ES_FADE_CTL+1         ; reached black — idle
@commit:
    .a8
    lda z:ES_FADE_CTL
    sta z:ES_SM_NMI+1           ; INIDISP shadow (NMI commits at VBlank)
@done:
    .a8
    rep #$20
    .a16
    rts
