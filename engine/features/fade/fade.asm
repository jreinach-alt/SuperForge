; =============================================================================
; fade.asm — INIDISP brightness ramp (global feature)
; =============================================================================
; ES_FADE_CTL: +0 level (0..15) +1 dir (0 idle · 1 in · 2 out) fade_tick writes
; the INIDISP shadow (ES_SM_NMI+1) ONLY while ramping — when idle the shadow
; keeps whatever the phase machine set (e.g. $80 blank).

; --- fade_init: boot init contract ------------------------------------------
; CONTRACT fade_init
;   entry:    A16 I16
;   exit:     A16 I16
;   out:      ES_FADE_CTL zeroed — level 0 and direction idle, the
;             write-before-read establishment for both bytes (rule 5)
;   clobbers: nothing. One `stz` and an `rts`
;   assumes:  ONCE, from MAIN's boot block
;   tail:     rts
fade_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "fade_init"
    stz z:ES_FADE_CTL
    rts

; --- fade_start_in / fade_start_out -----------------------------------------
; CONTRACT fade_start_in
;   entry:    A8 I16
;   exit:     A8 I16
;   out:      ES_FADE_CTL+1 = 1 (ramping in). The LEVEL byte is left where
;             it stands, so a fade reversed mid-ramp resumes from the
;             brightness on screen rather than from an end stop
;   clobbers: A, N, Z
;   assumes:  the caller is in A8 — the arm is one 8-bit store, and an A16
;             arrival would write the neighbouring level byte with it.
;             Arming only; fade_tick does the stepping
;   tail:     rts
fade_start_in:
    .a8
    SF_ASSERT_WIDTH 8, 16, "fade_start_in"
    lda #1
    sta z:ES_FADE_CTL+1
    rts
; CONTRACT fade_start_out
;   entry:    A8 I16
;   exit:     A8 I16
;   out:      ES_FADE_CTL+1 = 2 (ramping out). The level byte is left
;             where it stands, as in fade_start_in
;   clobbers: A, N, Z
;   assumes:  the caller is in A8, for the reason fade_start_in's contract
;             gives. Arming only; fade_tick does the stepping
;   tail:     rts
fade_start_out:
    .a8
    SF_ASSERT_WIDTH 8, 16, "fade_start_out"
    lda #2
    sta z:ES_FADE_CTL+1
    rts

; --- fade_tick: step the ramp one frame (call once per frame) ---------------
; CONTRACT fade_tick
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       ES_FADE_CTL — the level byte and the direction byte
;   out:      the level stepped one toward its end stop, the direction
;             cleared to idle when it arrives, and the INIDISP shadow
;             (ES_SM_NMI+1) written from the level — but ONLY while
;             ramping, so an idle fade leaves whatever the phase machine
;             set
;   clobbers: A, N, Z, C. The index registers are untouched
;   assumes:  ONCE per frame, unconditionally; it returns immediately when
;             idle. Both this and mosaic_tick write the INIDISP shadow and
;             neither claims INIDISP, so the allocator has nothing to
;             check — gate this on mosaic_active, or tick mosaic LAST
;   tail:     rts
fade_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "fade_tick"
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
