; =============================================================================
; play scene — the arena: a paddle, a ball, and 180 bricks
; =============================================================================
; Composition: breaker_bg (BG1 arena + BG2 night bed), breaker_obj (paddle +
; ball), bg_text (the HUD and the message rows), rgb_gradient (the backdrop
; wash).
;
; LAYER OWNERSHIP, asserted here and in breaker_bg/feature.toml because layer
; identity is not a resource the allocator models: this enter is
; the only writer of BGMODE, BG1SC, BG2SC, BG3SC, BG12NBA, BG34NBA and TM in
; this game's play scene.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; BG3 2bpp tile attr for the HUD (palette 7, priority — the HUD sits above the
; arena and is never tinted, because colour math targets BG1+BG2 only)
PLAY_TXT_ATTR = (7 << 10) | (1 << 13)

; Where rgb_gradient's wash LANDS, declared at the composition site because it
; is this scene's look and not the feature's (rgb_gradient.asm has no
; default). BG1 is the arena and BG2 the sky; BG3 (the HUD, see above) and OBJ
; are absent so they render untinted.
RG_MATH_LAYERS = (1 | 2)

; --- scene-scoped engine feature code — INSIDE the scope: its claims are
; scene-scoped, so its symbols must be too --------------------------------
.include "breaker_bg.asm"
.include "breaker_obj.asm"

; =============================================================================
; THE TWO BASE RATES tick_scale SCALES (docs/96 §4, docs/97 §3)
; =============================================================================
; The bat is the ordinary case: BRK_PADDLE_SPEED is now a RATE rather than a
; per-frame immediate, and on NTSC TS_STEP publishes it to the pixel.
TS_PADDLE_BASE = BRK_PADDLE_SPEED * TS_ONE
; The ball is not. Its velocity is a signed word holding +-BRK_SPEED_1 or
; +-BRK_SPEED_2, set by the launch angle and re-set by the paddle english on
; every return, so there is no ONE constant to scale — the SPEED CLASS is
; state. What is scaled is therefore BOTH CLASSES, each with its own pair, and
; `brk_ball_delta` selects between them by magnitude and re-applies the sign.
;
; TWO PAIRS RATHER THAN ONE SCALED UNIT, and the difference is measurable. A
; single published unit (1 on NTSC, 1/2 on PAL) would give the right AVERAGE
; for both classes — a class-2 ball would alternate 2 and 4 — but 4 px is a
; big frame against an 8 px cell, and every reflection costs a whole frame of
; travel, so the lumpier the step the noisier the measured path. Two pairs
; give 1/2 and 2/3 instead of 1/2 and 2/4.
TS_BALL1_BASE  = BRK_SPEED_1 * TS_ONE
TS_BALL2_BASE  = BRK_SPEED_2 * TS_ONE
.include "rgb_gradient.asm"

; =============================================================================
; MESSAGE BLOCKS — two 11-cell rows written ONE CELL PER FRAME
; =============================================================================
; A running scene cannot write VRAM, so the verdict lines go through bg_text's
; VBlank cell queue: 22 frames (0.37 s) to swap a block, which reads as a
; wipe-in rather than a delay. Every block is exactly BRK_MSG_LEN chars at the
; same two rows, so a new block TOTALLY overwrites the last one — no residue,
; no length bookkeeping, no clear pass.

; --- brk_msg_addr: block index -> the BG3 VRAM word address of that cell ----
; In/out: A16 = index 0..BRK_MSG_LEN-1 in, VRAM word address out. I16.
; Clobbers nothing else — callers hold the index in Y across it.
brk_msg_addr:
    .a16
    .i16
    cmp #BRK_MSG_W
    bcs @row1
    clc
    adc #(ES_V_TEXT_MAP + BRK_MSG_ROW0 * 32 + BRK_MSG_COL)
    rts
@row1:
    .a16
    .i16
    sec
    sbc #BRK_MSG_W
    clc
    adc #(ES_V_TEXT_MAP + BRK_MSG_ROW1 * 32 + BRK_MSG_COL)
    rts

; --- brk_msg_ptr: point ES_TXT_PTR at the pending block ---------------------
; In/out: A16/I16, DB=0. A = block address low16. Every block lives in this
; scope's RODATA, so one bank byte serves them all.
brk_msg_ptr:
    .a16
    .i16
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^m_wait
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    rts

; --- brk_msg_start: queue a block for the next BRK_MSG_LEN frames -----------
; In/out: A16/I16, DB=0. A = block address low16.
brk_msg_start:
    .a16
    .i16
    sta z:US_MSG
    stz z:US_MSGPOS
    rts

; --- brk_msg_now: write a whole block immediately (scene enter only) --------
; In/out: A16/I16, DB=0, FORCED BLANK. A = block address low16. Clobbers A, X, Y.
brk_msg_now:
    .a16
    .i16
    jsr brk_msg_ptr
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ldy #0
@cell:
    .a16
    .i16
    tya
    jsr brk_msg_addr
    sta a:$2116                     ; VMADD = this cell
    sep #$20
    .a8
    lda [<ES_TXT_PTR], y            ; the character
    rep #$20
    .a16
    and #$00FF                      ; the byte alone: B still holds the address
    sec
    sbc #' '                        ; glyph index (space -> tile 0)
    ora #PLAY_TXT_ATTR
    sta a:$2118                     ; VMDATA, word mode
    iny
    cpy #BRK_MSG_LEN
    bcc @cell
    rts

; --- brk_msg_tick: stage ONE cell of the pending block ----------------------
; In/out: A16/I16, DB=0. Does nothing when no block is pending.
brk_msg_tick:
    .a16
    .i16
    lda z:US_MSG
    bne @go
    rts
@go:
    .a16
    .i16
    jsr brk_msg_ptr
    ldy z:US_MSGPOS
    sep #$20
    .a8
    lda [<ES_TXT_PTR], y
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #' '
    ora #PLAY_TXT_ATTR
    pha                             ; the tile word, while A carries the index
    tya
    jsr brk_msg_addr
    tax                             ; X = VRAM word address
    pla
    jsr text_queue_cell             ; A = tile word, X = address
    lda z:US_MSGPOS
    inc a
    sta z:US_MSGPOS
    cmp #BRK_MSG_LEN
    bcc @more
    stz z:US_MSG                    ; the block is fully written
@more:
    .a16
    .i16
    rts

; =============================================================================
; HUD — the two live counters, through the same one-cell-per-frame queue
; =============================================================================
; One queue, three customers, one fixed priority: SCORE, then BALLS, then the
; message block. The counters go FIRST because they are one cell (or one
; four-cell run) and settle in a frame or two, while a block takes 2*BRK_MSG_W
; frames to write — put the block first and the round ends with "GAME OVER"
; sitting above a BALLS counter still reading 1, for a third of a second.
; This way the numbers are already true when the verdict starts wiping in.
brk_hud:
    .a16
    .i16
    lda z:US_DIRTY
    bne @counters
    jmp brk_msg_tick
@counters:
    .a16
    .i16
    lda z:US_DIRTY
    and #BRK_DIRTY_SCORE
    beq @balls
    lda z:US_DIRTY
    eor #BRK_DIRTY_SCORE
    sta z:US_DIRTY
    lda #PLAY_TXT_ATTR
    sta z:ES_TXT_TMP
    lda z:US_SCORE                  ; packed BCD, so hex4's nibble walk prints
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_SCORED_C)
    jmp text_queue_hex4             ; ...four DECIMAL digits
@balls:
    .a16
    .i16
    lda z:US_DIRTY
    and #BRK_DIRTY_BALLS
    beq @msg
    lda z:US_DIRTY
    eor #BRK_DIRTY_BALLS
    sta z:US_DIRTY
    lda z:US_BALLS
    and #15
    clc
    adc #('0' - ' ')                ; the '0' glyph's tile index
    ora #PLAY_TXT_ATTR
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_BALLSD_C)
    jmp text_queue_cell
@msg:
    .a16
    .i16
    jmp brk_msg_tick

; =============================================================================
; SCENE LIFECYCLE
; =============================================================================

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- a fresh round, every time. This is also the RESTART path: the trip
    ; through the title exists precisely so that rebuilding the wall happens
    ; here, under forced blank, where it is legal.
    lda f:US_ROUNDS_LONG
    inc a
    sta f:US_ROUNDS_LONG
    stz z:US_SCORE
    lda #BRK_START_BALLS
    sta z:US_BALLS
    lda #BRK_BRICK_TOTAL
    sta z:US_BRICKS
    lda #BRK_STATE_WAIT
    sta z:US_GSTATE
    lda #BRK_PADDLE_HOME
    sta z:US_PX
    stz z:US_VX
    stz z:US_VY
    stz z:US_BLINK
    stz z:US_TSP_ACC            ; the timebase's three carried fractions and
    stz z:US_TSP                ;   the three published steps: all written
    stz z:US_TS1_ACC            ;   before any of them is read
    stz z:US_TS1
    stz z:US_TS2_ACC
    stz z:US_TS2
    stz z:US_DIRTY                  ; enter prints both counters directly
    stz z:US_MSG
    stz z:US_MSGPOS
    jsr brk_ball_ride               ; the ball starts on the paddle
    ; ---- BG1 + BG2: CHR, palettes, the level, layer registers -------------
    jsr brk_arm
    jsr brk_q_init
    ; ---- the paddle and the ball: CHR, palette, OBSEL, OAM entries --------
    jsr obj_arm
    ; ---- BG3: the HUD's palette and layer registers -----------------------
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; colour 0 (transparent slot)
    sta a:$2122
    sta a:$2122
    lda #$84                    ; colour 1: dark navy $1084
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: white $7FFF
    sta a:$2122
    lda #$7F
    sta a:$2122
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #PLAY_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the HUD labels + the opening values ------------------------------
    lda #PLAY_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_score)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_score
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_SCORE_C)
    jsr text_puts
    lda #.loword(s_balls)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_BALLS_C)
    jsr text_puts
    lda z:US_SCORE
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_SCORED_C)
    jsr text_put_hex4
    lda z:US_BALLS
    ldx #(ES_V_TEXT_MAP + BRK_HUD_ROW * 32 + BRK_HUD_BALLSD_C)
    jsr text_put_digit
    lda #.loword(m_wait)
    jsr brk_msg_now             ; the whole block at once: we are blanked
    ; ---- the backdrop wash: three indirect COLDATA channels + colour math --
    jsr rg_arm
    ; ---- mode + layers: BG1 + BG2 + BG3 + OBJ -----------------------------
    sep #$20
    .a8
    lda #$09                    ; BGMODE 1, BG3 priority high (the HUD sits
                                ; above the arena)
    sta a:$2105
    lda #$17                    ; TM: BG1 + BG2 + BG3 + OBJ
    sta a:$212C
    ; ---- arm the three gradient channels in the HDMAEN shadow -------------
    lda z:ES_SM_NMI+2
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    ; ---- sprites placed BEFORE the first displayed frame, so frame 0 shows
    ; the paddle rather than power-on garbage (rule 5) ----------------------
    jsr obj_place
    rts

; --- exit: put the colour math, the sprites and the queue back -------------
; In/out: A16/I16, DB=0, forced blank.
exit:
    .a16
    .i16
    jsr rg_disarm               ; or the title inherits this scene's tint
    jsr obj_park
    jsr brk_q_init              ; ...and its half-staged bricks
    rts

; --- tick: one game frame --------------------------------------------------
; In/out: A16/I16, DB=0. Display is active: no VRAM writes here — the two
; things that must reach VRAM (a broken brick, a HUD cell) are STAGED and
; committed by the NMI hook.
tick:
    .a16
    .i16
    jsr brk_update
    jsr brk_hud
    jsr obj_place
    rts

; =============================================================================
; PER-FRAME UPDATE — state dispatch
; =============================================================================
brk_update:
    .a16
    .i16
    lda z:US_BLINK
    inc a
    sta z:US_BLINK              ; a free-running heartbeat: "the tick ran"
    ; ---- this frame's three region-correct steps, published once ----------
    ; BEFORE the START test and the state dispatch, deliberately: WAIT moves
    ; the bat too, and a step word that stops being republished is a stale
    ; word waiting to be read.
    TS_STEP z:US_TSP_ACC, TS_PADDLE_BASE
    sta z:US_TSP
    TS_STEP z:US_TS1_ACC, TS_BALL1_BASE
    sta z:US_TS1
    TS_STEP z:US_TS2_ACC, TS_BALL2_BASE
    sta z:US_TS2
    ; START LEAVES, FROM ANY STATE. Start IS the restart here — it is the
    ; first half of the trip through the title that rebuilds the wall — so
    ; gating it on the end screens (as a restart-in-place would) would mean
    ; the only way out of a round is to lose it. Checked before the
    ; dispatch, and returning immediately: the scene is leaving, so running
    ; another frame of physics into it is work whose result is discarded.
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @dispatch
    sep #$20
    .a8
    lda #0                      ; scene id: title
    jsr sm_request
    rep #$20
    .a16
    rts
@dispatch:
    .a16
    .i16
    lda z:US_GSTATE
    beq @wait
    cmp #BRK_STATE_PLAY
    beq @play
    rts                         ; 2 game over / 3 win: the verdict stands
                                ; until Start, which the gate above owns
@wait:
    .a16
    .i16
    jmp brk_state_wait
@play:
    .a16
    .i16
    jmp brk_state_play

; --- WAIT: the ball rides the paddle; A launches ---------------------------
brk_state_wait:
    .a16
    .i16
    jsr brk_move_paddle
    jsr brk_ball_ride
    lda z:ES_INP_PRESS
    and #JOY_A
    bne @launch
    rts
@launch:
    .a16
    .i16
    lda #BRK_STATE_PLAY
    sta z:US_GSTATE
    lda #BRK_SPEED_N2
    sta z:US_VY                 ; up, 2 px/frame
    ; The launch angle ALTERNATES with the balls remaining, so the opening of
    ; every ball is deterministic and different — no RNG, which is what makes
    ; the whole rail emulator-verifiable.
    lda z:US_BALLS
    lsr
    bcs @vx_right
    lda #BRK_SPEED_N1
    sta z:US_VX
    bra @msg
@vx_right:
    .a16
    .i16
    lda #BRK_SPEED_1
    sta z:US_VX
@msg:
    .a16
    .i16
    lda #.loword(m_play)        ; wipe the prompt away
    jmp brk_msg_start

; --- PLAY: move everything, collide, score ---------------------------------
brk_state_play:
    .a16
    .i16
    jsr brk_move_paddle
    jsr brk_move_x
    jsr brk_move_y
    jsr brk_paddle_check
    jsr brk_floor_check
    ; The wall is gone -> a win, but only FROM play: floor_check may have just
    ; ended the round on the same frame the last brick fell.
    lda z:US_BRICKS
    bne @done
    lda z:US_GSTATE
    cmp #BRK_STATE_PLAY
    bne @done
    lda #BRK_STATE_WIN
    sta z:US_GSTATE
    lda #.loword(m_win)
    jmp brk_msg_start
@done:
    .a16
    .i16
    rts

; =============================================================================
; SUBROUTINES — input, ball physics, collision, scoring
; =============================================================================

; --- brk_move_paddle: d-pad left/right, clamped to the walls ---------------
; In/out: A16/I16, DB=0.
brk_move_paddle:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX
    sec
    sbc z:US_TSP
    cmp #BRK_PADDLE_MIN_X
    bcs @store_l
    lda #BRK_PADDLE_MIN_X
@store_l:
    .a16
    .i16
    sta z:US_PX
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX
    clc
    adc z:US_TSP
    cmp #BRK_PADDLE_MAX_X
    bcc @store_r
    lda #BRK_PADDLE_MAX_X
@store_r:
    .a16
    .i16
    sta z:US_PX
@no_right:
    .a16
    .i16
    rts

; --- brk_ball_ride: park the ball centred on the paddle --------------------
; In/out: A16/I16, DB=0.
brk_ball_ride:
    .a16
    .i16
    lda z:US_PX
    clc
    adc #((BRK_PADDLE_W - BRK_BALL_SIZE) / 2)
    sta z:US_BX
    lda #BRK_BALL_WAIT_Y
    sta z:US_BY
    rts

; --- brk_probe_score: one probe, and the game's half of a brick break ------
; In/out: A16/I16, DB=0. US_PROBE_X / US_PROBE_Y set by the caller.
; Out: A16 = the cell class (0 clear / 1 wall / 2 brick).
;
; brk_probe (breaker_bg) owns the MAP half of a break: it clears the collision
; cell and stages the VRAM cell. Scoring is the GAME's half and lives here,
; which is why this wrapper exists rather than a fatter probe. It is called
; per probe POINT, not per axis, so two probes breaking two bricks in one
; frame score twice — an `ora` of the two verdicts would have lost one.
brk_probe_score:
    .a16
    .i16
    jsr brk_probe
    cmp #BRK_CELL_BRICK
    beq @broke
    rts
@broke:
    .a16
    .i16
    ; SCORE IS PACKED BCD. `sed` + a 16-bit adc gives four decimal digits, and
    ; bg_text's hex4 nibble walk then prints them as decimal for free — a
    ; decimal formatter this game does not have to own. The 65816
    ; CLEARS D on interrupt entry and rti restores it, so an NMI landing
    ; inside this window cannot inherit decimal mode.
    sed
    clc
    lda z:US_SCORE
    adc #$0010                  ; ten points, in BCD
    sta z:US_SCORE
    cld
    lda z:US_BRICKS
    dec a
    sta z:US_BRICKS
    lda z:US_DIRTY
    ora #BRK_DIRTY_SCORE
    sta z:US_DIRTY
    jsr brk_blip
    lda #BRK_CELL_BRICK
    rts

; --- brk_blip: one sound effect ---------------------------------------------
; In/out: A16/I16, DB=0.
; WIDTH-RISK: Tad_QueueSoundEffect is a CROSS-FILE callee (vendor/tad) and
; takes A8; the width linter is single-file and cannot see the contract, so
; the sep/rep pair around it is load-bearing and stays here rather than at the
; call sites.
brk_blip:
    .a16
    .i16
    sep #$20
    .a8
    lda #SFX::footstep
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
    rts

; --- brk_ball_delta: one axis velocity -> this frame's signed pixel step ----
; NOT `_step`, deliberately: this is a pure function of a velocity and a
; published word, with no state and no clock of its own, and `make tick-check`
; reads a `*_step` name as "a routine the frame clocks". Calling it a delta is
; both more accurate and one fewer entry in that gate's tracked population.
; In:  A16/I16, DB=0. A = the axis velocity (+-BRK_SPEED_1 or +-BRK_SPEED_2,
;      two's complement). Out: A = the signed step to apply this frame.
;      CLOBBERS A ONLY, and no index register at all: the callers keep the
;      velocity in DP and the probe path downstream owns X and Y.
;
; The velocity is one of four values, so this is a two-way magnitude test and
; a sign re-application: the sign is the ball's DIRECTION and never scales,
; only the magnitude does. The word is compared UNSIGNED, which is why the
; negative arm tests against BRK_SPEED_N1 ($FFFF) rather than against -1: as
; unsigned words $FFFF sorts above $FFFE, so `beq` picks class 1 exactly.
;
; ON NTSC THIS IS THE IDENTITY. US_TS1 is BRK_SPEED_1 and US_TS2 is
; BRK_SPEED_2 on every frame while the region flag is clear, so
; brk_move_x/brk_move_y apply exactly the velocity they applied before and
; the picture cannot move.
;
; THE NO-TUNNEL BOUND: the largest thing this can return is 3 px, against the
; 8 px cell the leading-edge probe reads. A step smaller than a cell cannot
; carry the edge ACROSS a live brick without landing in it, which is the
; property breaker.inc's "max speed is 2 px/frame" note is actually
; asserting.
brk_ball_delta:
    .a16
    .i16
    bmi @negative
    cmp #BRK_SPEED_2
    bcc @pos1
    lda z:US_TS2
    rts
@pos1:
    .a16
    .i16
    lda z:US_TS1
    rts
@negative:
    .a16
    .i16
    cmp #BRK_SPEED_N1           ; -1 sorts ABOVE -2 as an unsigned word
    beq @neg1
    lda z:US_TS2
    bra @negate
@neg1:
    .a16
    .i16
    lda z:US_TS1
@negate:
    .a16
    .i16
    eor #$FFFF                  ; two's complement, the rail's own idiom
    inc a                       ;   (BRK_SPEED_N1/N2 are written the same way)
    rts

; --- brk_move_x / brk_move_y: per-axis move-then-probe ---------------------
; In/out: A16/I16, DB=0.
; The canonical shape: compute the tentative position, probe the LEADING edge
; at two points (so a contact spanning two cells still registers), and either
; take the move or reflect the axis. Max speed is 2 px/frame against 8 px
; cells, so the leading edge cannot step over a whole cell — no tunnelling.
brk_move_x:
    .a16
    .i16
    lda z:US_VX
    jsr brk_ball_delta           ; the velocity, scaled to this frame
    clc
    adc z:US_BX
    sta z:US_NEWX
    lda z:US_VX
    bmi @lead_left
    lda z:US_NEWX
    clc
    adc #(BRK_BALL_SIZE - 1)        ; moving right: probe the right edge
    bra @lead
@lead_left:
    .a16
    .i16
    lda z:US_NEWX                   ; moving left: probe the left edge
@lead:
    .a16
    .i16
    sta z:US_PROBE_X
    lda z:US_BY
    clc
    adc #BRK_PROBE_NEAR
    sta z:US_PROBE_Y                ; near the top of the ball...
    jsr brk_probe_score
    sta z:US_HITF
    lda z:US_BY
    clc
    adc #BRK_PROBE_FAR
    sta z:US_PROBE_Y                ; ...and near the bottom
    jsr brk_probe_score
    ora z:US_HITF
    sta z:US_HITF                   ; wall bit 0 | brick bit 1
    bne @bounce
    lda z:US_NEWX
    sta z:US_BX                     ; clear: take the move
    rts
@bounce:
    .a16
    .i16
    lda z:US_HITF
    and #BRK_CELL_BRICK
    bne @reflect                    ; a brick broke: its ding already played
    jsr brk_blip                    ; a wall: its own tick
@reflect:
    .a16
    .i16
    lda z:US_VX
    eor #$FFFF                      ; negate (two's complement): reverse VX
    inc a
    sta z:US_VX
    rts                             ; blocked: reflect and stay put

brk_move_y:
    .a16
    .i16
    lda z:US_VY
    jsr brk_ball_delta           ; the velocity, scaled to this frame
    clc
    adc z:US_BY
    sta z:US_NEWY
    lda z:US_VY
    bmi @lead_top
    lda z:US_NEWY
    clc
    adc #(BRK_BALL_SIZE - 1)        ; moving down: probe the bottom edge
    bra @lead
@lead_top:
    .a16
    .i16
    lda z:US_NEWY                   ; moving up: probe the top edge
@lead:
    .a16
    .i16
    sta z:US_PROBE_Y
    lda z:US_BX
    clc
    adc #BRK_PROBE_NEAR
    sta z:US_PROBE_X
    jsr brk_probe_score
    sta z:US_HITF
    lda z:US_BX
    clc
    adc #BRK_PROBE_FAR
    sta z:US_PROBE_X
    jsr brk_probe_score
    ora z:US_HITF
    sta z:US_HITF
    bne @bounce
    lda z:US_NEWY
    sta z:US_BY
    rts
@bounce:
    .a16
    .i16
    lda z:US_HITF
    and #BRK_CELL_BRICK
    bne @reflect
    jsr brk_blip
@reflect:
    .a16
    .i16
    lda z:US_VY
    eor #$FFFF
    inc a
    sta z:US_VY
    rts

; --- brk_paddle_check: ball vs paddle (only while falling) + english -------
; In/out: A16/I16, DB=0.
; 4-zone english: the outgoing VX comes from WHERE on the 24 px paddle the
; ball's centre struck — outer quarters -2/+2, inner quarters -1/+1. More
; control than a centre-side split: the player can aim.
brk_paddle_check:
    .a16
    .i16
    lda z:US_VY
    bmi @miss                       ; moving up: no paddle contact
    lda z:US_BY
    clc
    adc #BRK_BALL_SIZE
    cmp #BRK_PADDLE_Y
    bcc @miss                       ; the ball's bottom is above the bat
    lda z:US_BY
    cmp #(BRK_PADDLE_Y + BRK_PADDLE_H)
    bcs @miss                       ; ...its top is below the bat
    lda z:US_BX
    clc
    adc #BRK_BALL_SIZE
    cmp z:US_PX
    bcc @miss                       ; ...its right edge is left of the bat
    lda z:US_PX
    clc
    adc #BRK_PADDLE_W
    cmp z:US_BX
    bcc @miss                       ; ...its left edge is right of the bat
    ; ---- a catch --------------------------------------------------------
    jsr brk_blip
    ; Snap the ball onto the paddle's top. A deliberate rescue: a fast descent
    ; can already be several px inside the box when the hit registers, and
    ; snapping up keeps it from sinking through on the next frame. Visible
    ; only on the steepest catches.
    lda #BRK_BALL_WAIT_Y
    sta z:US_BY
    lda #BRK_SPEED_N2
    sta z:US_VY
    lda z:US_BX
    clc
    adc #(BRK_BALL_SIZE / 2)
    sec
    sbc z:US_PX                     ; dx = ball centre - paddle left
    bmi @far_left
    cmp #(BRK_PADDLE_W / 4)
    bcc @far_left
    cmp #(BRK_PADDLE_W / 2)
    bcc @mid_left
    cmp #(BRK_PADDLE_W * 3 / 4)
    bcc @mid_right
    lda #BRK_SPEED_2                ; outer right
    sta z:US_VX
    rts
@mid_right:
    .a16
    .i16
    lda #BRK_SPEED_1
    sta z:US_VX
    rts
@mid_left:
    .a16
    .i16
    lda #BRK_SPEED_N1
    sta z:US_VX
    rts
@far_left:
    .a16
    .i16
    lda #BRK_SPEED_N2
    sta z:US_VX
    rts
@miss:
    .a16
    .i16
    rts

; --- brk_floor_check: below the paddle is the pit --------------------------
; In/out: A16/I16, DB=0.
brk_floor_check:
    .a16
    .i16
    lda z:US_BY
    cmp #BRK_BALL_LOST_Y
    bcs @lost
    rts
@lost:
    .a16
    .i16
    jsr brk_blip
    lda z:US_BALLS
    dec a
    sta z:US_BALLS
    lda z:US_DIRTY
    ora #BRK_DIRTY_BALLS
    sta z:US_DIRTY
    lda z:US_BALLS
    beq @game_over
    lda #BRK_STATE_WAIT
    sta z:US_GSTATE
    stz z:US_VX
    stz z:US_VY
    jsr brk_ball_ride
    lda #.loword(m_wait)
    jmp brk_msg_start
@game_over:
    .a16
    .i16
    lda #BRK_STATE_OVER
    sta z:US_GSTATE
    lda #.loword(m_over)
    jmp brk_msg_start

; --- the backdrop wash's data, a SCENE-scoped claim ------------------------
; rgb_gradient claims grad_tabs itself, so the blob lives here rather than in
; breaker_rom: ca65 resolves scopes backward, and ES_R_GRAD_TABS_* is a symbol
; of THIS scope. It packs after every global blob, which is the order
; main.asm's BANK2 block and this one produce between them (see
; build/bk/allocation_report.txt). The .asserts refuse any drift.
.segment "BANK2"
grad_tabs_bin:
    .incbin "brk_grad.bin"
.assert ^grad_tabs_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(grad_tabs_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"

.segment "RODATA"
s_score: .byte "SCORE", 0
s_balls: .byte "BALLS", 0

; The message blocks. Each is EXACTLY BRK_MSG_LEN bytes — a verdict row then a
; prompt row, both padded to BRK_MSG_W — so a new block overwrites the last one
; cell for cell. The .asserts are the guard: a mistyped block would otherwise
; run off into the next one and write another block's text.
m_wait:  .byte "  PRESS A  ", "           "
.assert * - m_wait = BRK_MSG_LEN, error, "m_wait is not one message block"
m_play:  .byte "           ", "           "
.assert * - m_play = BRK_MSG_LEN, error, "m_play is not one message block"
m_over:  .byte " GAME OVER ", "PRESS START"
.assert * - m_over = BRK_MSG_LEN, error, "m_over is not one message block"
m_win:   .byte " YOU WIN!  ", "PRESS START"
.assert * - m_win = BRK_MSG_LEN, error, "m_win is not one message block"
.segment "CODE"
.endscope
