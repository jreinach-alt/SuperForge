; =============================================================================
; play scene — the whole game: a movable sprite over a live "SCORE" line
; =============================================================================
; The rail's subject is bg_text END TO END, and the two halves of that are both
; here:
;
;   THE LABEL is printed ONCE, in `enter`, under the scene_mgr forced blank,
;   with `text_puts` — the only way a five-cell string may reach VRAM.
;
;   THE COUNTER is reprinted from `tick`, on a RUNNING frame, through
;   bg_text's one-run VBlank queue (`text_queue_hex4` stages, the NMI hook's
;   `text_vblank_commit` writes) — and ONLY on the frames US_SCORE actually
;   changed. `hud_refresh` returns without staging anything when US_DIRTY is
;   clear, so `text_vblank_commit` is a no-op and the four counter cells are
;   not rewritten. That is the reprint-on-change pattern this rail exists to
;   teach, and it is measured on the destination VRAM bytes' write counters
;   rather than on the flag (tests/test_hud_game.py).
;
; EDGE VS LEVEL INPUT, the rail's other lesson: the d-pad reads ES_INP_CUR
; (held — move while down) and the score reads ES_INP_PRESS (the rising edge —
; one bump per press, however long A is held).
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; The scene's own feature code, inside the scope: hud_obj's claims are
; scene-scoped, so its asm has to see this scene's emitted symbols.
.include "hud_obj.asm"

; =============================================================================
; THE ONE BASE RATE tick_scale SCALES (docs/96 §4, docs/97 §3)
; =============================================================================
; HUD_SPEED is still the one number to reach for when tuning how this rail
; feels; what changed is that it is now a RATE rather than a per-frame
; immediate. On NTSC TS_STEP publishes it to the pixel, so the picture cannot
; move; on PAL it publishes 2 or 3 in the pattern that averages 2.4036.
;
; THE SCORE IS NOT SCALED AND MUST NOT BE. It is bumped on the RISING EDGE of
; A — one bump per press however long the button is held — so it is an event
; count, not a rate per second, and a player pressing A ten times scores ten
; on either machine already. That is this rail's edge-vs-level lesson stated
; in the time domain: the HELD d-pad is a rate and scales, the PRESSED button
; is an edge and does not. `blink` is likewise left alone: it is the
; free-running heartbeat and drives nothing.
TS_MOVE_BASE = HUD_SPEED * TS_ONE

; BG3 2bpp tile attr: palette 7 (claim pins CGRAM words 28..31), priority set
; so the HUD line draws over the player where they overlap — BGMODE bit 3
; below puts BG3's priority-1 tiles above the sprites, which is what a HUD is.
TXT_ATTR = (7 << 10) | (1 << 13)

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- CGRAM: backdrop (word 0) + the 4-colour text sub-palette ---------
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    stz a:$2122                 ; black backdrop: colour 0 stays $0000 and
    stz a:$2122                 ;   nothing else ever writes it
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    ; $2122 is a byte port: two writes per colour, low then high (A8 only)
    stz a:$2122                 ; colour 0 (transparent slot): black $0000
    stz a:$2122
    lda #$52                    ; colour 1: dim slate $2952
    sta a:$2122
    lda #$29
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: WHITE $7FFF — the HUD colour, and
    sta a:$2122                 ;   the pixel the render test counts
    lda #$7F
    sta a:$2122
    ; ---- BG3 regs: map base, chr base, mode, layer enable -----------------
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC: 32x32 map at the scene's base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA: BG3 chr = the scene's font base
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    lda #$09                    ; BGMODE 1, BG3 priority high
    sta a:$2105
    lda #$14                    ; TM: BG3 + OBJ. This scene never draws on
    sta a:$212C                 ;   BG1, so BG1 is not enabled.
    rep #$20
    .a16
    ; ---- font + tilemap ---------------------------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the player's CHR, palette, OBSEL and resting OAM entries ----------
    jsr hud_obj_arm
    ; ---- game state. Power-on WRAM/DP is RANDOM (rule 5): these stores ARE
    ; the write-before-read contract for every word state.toml declares. -----
    lda #HUD_HOME_X
    sta z:US_PX
    lda #HUD_HOME_Y
    sta z:US_PY
    stz z:US_SCORE
    stz z:US_DIRTY
    stz z:US_BLINK
    stz z:US_TS_ACC             ; the timebase's carried fraction, and this
    stz z:US_TS_STEP            ;   frame's step: written before either is read
                                ;   (enter's own placement runs first)
    ; ---- the HUD, printed under the blank where a whole string is legal ---
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_score)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_score
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + HUD_ROW * 32 + HUD_LABEL_C)
    jsr text_puts
    lda z:US_SCORE              ; packed BCD 0000 -> four '0' glyphs
    ldx #(ES_V_TEXT_MAP + HUD_ROW * 32 + HUD_DIGITS_C)
    jsr text_put_hex4
    ; ---- the player's first placement, so frame 1 draws him where he is ---
    jsr hud_obj_place
    rts

; --- exit: re-park the sprites this scene armed -----------------------------
; In/out: A16/I16, DB=0. Never called — this game has one scene and no edges —
; but the claim's contract is symmetric and a second scene would need it.
exit:
    .a16
    .i16
    jsr hud_obj_park
    rts

; --- tick: one frame (display active — no direct VRAM writes here) ----------
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    lda z:US_BLINK
    inc a
    sta z:US_BLINK              ; the free-running heartbeat
    ; ---- this frame's region-correct step, published once ------------------
    ; Computed here rather than inside move_player so all four axis moves read
    ; ONE answer: compute once per frame per rate, consume as many times as
    ; the frame needs.
    TS_STEP z:US_TS_ACC, TS_MOVE_BASE
    sta z:US_TS_STEP
    jsr move_player
    jsr bump_score
    jsr hud_refresh
    jmp hud_obj_place

; --- move_player: the d-pad, on HELD state ---------------------------------
; In/out: A16/I16, DB=0. Screen space; the clamp keeps the 8 px box on screen.
; Per axis: the two directions are tested independently, so holding both
; cancels out — which is the reason the clamp can be one-sided.
move_player:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX
    clc
    adc z:US_TS_STEP
    sta z:US_PX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX
    sec
    sbc z:US_TS_STEP
    sta z:US_PX
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_PY
    clc
    adc z:US_TS_STEP
    sta z:US_PY
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_PY
    sec
    sbc z:US_TS_STEP
    sta z:US_PY
@no_up:
    .a16
    .i16
    ; ---- clamp both axes to the screen. The underflow
    ; test is a SIGNED one: a step left from 0 wraps to $FFFE, which is huge
    ; unsigned and negative signed, so `bpl` sorts both ends with one compare.
    lda z:US_PX
    bmi @clamp_x_lo
    cmp #(HUD_MAX_X + 1)
    bcc @clamp_x_done
    lda #HUD_MAX_X
    sta z:US_PX
    bra @clamp_x_done
@clamp_x_lo:
    .a16
    .i16
    stz z:US_PX
@clamp_x_done:
    .a16
    .i16
    lda z:US_PY
    bmi @clamp_y_lo
    cmp #(HUD_MAX_Y + 1)
    bcc @clamp_y_done
    lda #HUD_MAX_Y
    sta z:US_PY
    bra @clamp_y_done
@clamp_y_lo:
    .a16
    .i16
    stz z:US_PY
@clamp_y_done:
    .a16
    .i16
    rts

; --- bump_score: A on the RISING EDGE only ---------------------------------
; In/out: A16/I16, DB=0. ES_INP_PRESS is `cur & ~prev`, so a HELD A sets it on
; exactly one frame — which is the edge-vs-level lesson, and what makes
; "hold A for ten frames, the counter reads 1" a real assertion.
bump_score:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    bne @bump
    rts
@bump:
    .a16
    .i16
    ; SCORE IS PACKED BCD. `sed` + a 16-bit adc gives four decimal digits, and
    ; bg_text's hex4 nibble walk then prints them as decimal for free — a
    ; decimal formatter this game does not have to own (breaker and shmup
    ; make the same call). The 65816 CLEARS D on
    ; interrupt entry and rti restores it, so an NMI landing inside this
    ; window cannot inherit decimal mode.
    sed
    clc
    lda z:US_SCORE
    adc #$0001                  ; one point, in BCD
    sta z:US_SCORE
    cld
    lda z:US_DIRTY
    ora #HUD_DIRTY_SCORE
    sta z:US_DIRTY
    rts

; --- hud_refresh: stage the counter run, ONLY when the value changed --------
; In/out: A16/I16, DB=0.
;
; THE WHOLE POINT OF THE RAIL. A running scene cannot write VRAM directly, so
; the four counter cells go through bg_text's VBlank queue. On a frame where
; US_DIRTY is clear this returns having staged NOTHING — the queue's dirty
; byte stays 0, `text_vblank_commit` returns immediately, and the four cells in
; VRAM are not written at all. One press therefore costs one four-word run,
; not a run every frame.
hud_refresh:
    .a16
    .i16
    lda z:US_DIRTY
    and #HUD_DIRTY_SCORE
    bne @stage
    rts
@stage:
    .a16
    .i16
    lda z:US_DIRTY
    eor #HUD_DIRTY_SCORE
    sta z:US_DIRTY
    lda #TXT_ATTR
    sta z:ES_TXT_TMP
    lda z:US_SCORE              ; packed BCD, so hex4's nibble walk prints
    ldx #(ES_V_TEXT_MAP + HUD_ROW * 32 + HUD_DIGITS_C)
    jmp text_queue_hex4         ; ...four DECIMAL digits

.segment "RODATA"
s_score: .byte "SCORE", 0
.segment "CODE"
.endscope
