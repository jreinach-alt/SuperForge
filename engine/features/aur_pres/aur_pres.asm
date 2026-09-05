; =============================================================================
; aur_pres — the beats: black, the scene, the pen, the card, black
; =============================================================================
; A ONE-SCENE RAIL WITH NOTHING TO DO IN IT still has to be watchable, and the
; scene on its own is not: the pen spends itself in seventy frames and the
; colour cycle is a fifty-one-second drift with no beginning and no end, so
; after those seventy frames nothing marks time at all. This gives it a
; shape — without touching the drift, which is the thing worth watching.
;
; THE BEATS WAIT ON DIFFERENT THINGS, deliberately.
;
;   UP     the fade ramp — waits on `fade` going idle, not on a frame count,
;          so retuning the ramp cannot desynchronise this
;   PLAY   the PEN, watched on its own frame counter: the beat ends when the
;          word is written, whatever that costs, rather than on a count that
;          would have to be retuned beside it
;   HOLD   a tuned count — the only beat that is a matter of taste
;   DOWN   the ramp again
;   RESET  the ink draining, counted down in slices by aur_write's VBlank arm
;
; THE COLOUR CYCLE IS NOT A BEAT AND IS NEVER RESET. It runs underneath all
; five of them and the loop does not touch it, which is the whole reason the
; piece is worth watching twice: the aurora is a different colour every time
; round, and over sixteen passes it travels the rail's full journey from
; cyan-teal to violet. An earlier cut put the CHR page back at each loop and
; the cost was exactly that — every pass opened on the same teal, and fifteen
; of the sixteen phases were unreachable without a stopwatch.
;
; THE TIMER IS IN TICKS, NOT FRAMES. It is stepped by the same TS_STEP output
; the hue cycle reads, so a PAL console holds the card for the same wall-clock
; time on fifty frames that an NTSC one holds it for on sixty, and the beat
; boundaries stay where the cycle's do.
;
; NOTHING HERE WRITES A PPU REGISTER. Brightness has one writer in this tree —
; `sm_nmi_core` commits the shadow `fade` ramps — so a beat that wants black
; arms a direction and waits, and this feature claims no register at all.

; --- aur_pres_init ---------------------------------------------------------
; CONTRACT aur_pres_init
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      the first beat armed: UP, with the pen held so the word does not
;             start writing behind a fade. MAIN has already armed the ramp
;   clobbers: A, N, Z
;   assumes:  enter-time. Power-on dp is RANDOM (rule 5), so this is the
;             write-before-read contract for both words
;   tail:     rts
aur_pres_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_pres_init"
    stz z:ES_AUR_PST                ; = AUR_P_UP
    stz z:ES_AUR_PTIM
    rts

; --- aur_pres_again: Start, from the top ------------------------------------
; CONTRACT aur_pres_again
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      the DOWN beat armed and the ramp started, so Start always
;             re-enters through a fade rather than snatching the picture away
;   clobbers: A, N, Z
;   assumes:  main-loop
;   tail:     rts
aur_pres_again:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_pres_again"
    lda #AUR_P_DOWN
    sta z:ES_AUR_PST
    sep #$20
    .a8
    jsr fade_start_out              ; A8 by contract — see fade.asm
    rep #$20
    .a16
    rts

; --- aur_pres_tick: run the beat, once a frame ------------------------------
; CONTRACT aur_pres_tick
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       A = whole ticks this frame (TS_STEP's output)
;   out:      ES_AUR_HOLD raised for the beats that stand still, the beat
;             advanced where its wait has ended, and the restores armed on the
;             edge into RESET
;   clobbers: A, X, Y, N, Z, C
;   assumes:  called once a frame from the scene's tick, BEFORE aur_hue_tick —
;             the hold it raises is what that reads
;   tail:     rts
aur_pres_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_pres_tick"
    tay                             ; Y = ticks this frame, kept across the
                                    ;   dispatch: only two beats spend them
    lda z:ES_AUR_PST
    asl a
    tax
    jmp (@beat, x)
@beat:
    .addr @up, @play, @hold, @down, @reset

; ---- UP: the scene, brightening. The pen is held so the word does not
; start writing behind a fade.
@up:
    .a16
    .i16
    jsr @freeze
    lda z:ES_FADE_CTL               ; the ramp's own two bytes: level, dir
    and #$FF00                      ; ...the direction, in the high byte
    beq :+
    rts                             ; still ramping
:   lda #AUR_P_PLAY
    sta z:ES_AUR_PST
    rts

; ---- PLAY: the pen writes the word, and the beat is over when it has
@play:
    .a16
    .i16
    lda z:ES_AUR_WFRAME
    cmp #AUR_WRITE_FRAMES
    bcs :+
    rts                             ; the pen is still moving
:   lda #AUR_P_HOLD
    sta z:ES_AUR_PST
    lda #AUR_PRES_HOLD
    sta z:ES_AUR_PTIM
    rts

; ---- HOLD: the finished card stands. The cycle keeps running under it
@hold:
    .a16
    .i16
    jsr @spend
    beq :+
    rts                             ; the card has not stood long enough
:   lda #AUR_P_DOWN
    sta z:ES_AUR_PST
    sep #$20
    .a8
    jsr fade_start_out
    rep #$20
    .a16
    rts

; ---- DOWN: going to black, still cycling
@down:
    .a16
    .i16
    lda z:ES_FADE_CTL
    and #$FF00
    beq :+
    rts                             ; still ramping
:   ; At black: ask for the ink back, counted down in slices by aur_write's
    ; own VBlank arm. The AURORA is deliberately left alone — see the header.
    jsr aur_write_restart
    lda #AUR_P_RESET
    sta z:ES_AUR_PST
    rts

; ---- RESET: the ink draining, at black
@reset:
    .a16
    .i16
    jsr @freeze
    lda z:ES_AUR_WRESET
    beq :+
    rts                             ; the ink is still draining
:   stz z:ES_AUR_PST                ; = AUR_P_UP, and round again
    sep #$20
    .a8
    jsr fade_start_in
    rep #$20
    .a16
    rts

; ---- the two helpers ------------------------------------------------------
; `freeze` raises the hold the pen reads — the same flag B raises for the
; whole piece. It is raised per frame rather than latched because the scene
; clears it every frame, so B and the beats are one flag with one writer
; instead of two that argue.
;
; THE HUE CYCLE READS IT TOO, which is the one place a beat still stops the
; colour: `aur_hue_tick` early-outs on it, so the drift pauses through UP and
; RESET. Both are short and both sit at or near black, so it costs the journey
; about forty frames a lap and nothing a viewer can see.
@freeze:
    .a16
    .i16
    lda #1
    sta z:ES_AUR_HOLD
    rts

; `spend` takes this frame's ticks off the beat's timer and returns Z set when
; it has run out. Y carries the ticks in; a frame that scaled to none leaves
; the timer alone, which is what makes the beat lengths region-correct.
@spend:
    .a16
    .i16
    tya
    beq @left
    cmp z:ES_AUR_PTIM
    bcc :+
    lda z:ES_AUR_PTIM               ; ...never past zero
:   eor #$FFFF
    sec
    adc z:ES_AUR_PTIM               ; PTIM - min(ticks, PTIM)
    sta z:ES_AUR_PTIM
    rts
@left:
    .a16
    .i16
    lda z:ES_AUR_PTIM
    rts
