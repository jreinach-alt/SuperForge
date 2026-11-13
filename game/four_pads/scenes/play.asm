; =============================================================================
; play scene — four tokens, four pads, four lamps
; =============================================================================
; Per frame: each player's held word moves its token (d-pad, clamped to the
; play field), an A PRESS flips it (the edge, not the hold), and the lamps and
; tokens are redrawn — players 3/4 only when the adapter answered at boot.
;
; EVERY PAD READ GOES THROUGH pad_btn / pad_btnp (engine/features/mtap), the
; player-indexed query: X = player 0-3, A = button mask. The scene never names
; a player's DP word itself, so the four players are one loop, not four
; copies of it.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

.include "fp_obj.asm"

; THE ONE BASE RATE tick_scale SCALES (docs/96 §4, docs/97 §3): every token
; moves at FP_SPEED. Nothing else on this rail is counted in frames.
TS_MOVE_BASE = FP_SPEED * TS_ONE

; The backdrop colour: a dark slate (15-bit BGR).
FP_BACKDROP = (8 << 10) | (5 << 5) | 4

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- the backdrop (backdrop's claim): CGRAM 0 = a dark slate, written,
    ; not assumed (power-on CGRAM is random); BGMODE 1 with OBJ alone on TM.
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD
    lda #<FP_BACKDROP
    sta a:$2122
    lda #>FP_BACKDROP
    sta a:$2122
    lda #1
    sta a:$2105                 ; BGMODE 1 — inert (no BG enabled), but known
    lda #(1 << 4)
    sta a:$212C                 ; TM: OBJ only
    rep #$20
    .a16
    jsr fp_obj_arm
    ; ---- game state: write-before-read for every word state.toml declares --
    ldx #0
@home:
    .a16
    lda f:fp_home, x
    sta z:US_PX, x
    lda f:fp_home + (FP_PLAYERS * 2), x
    sta z:US_PY, x
    stz z:US_FLIP, x
    inx
    inx
    cpx #(FP_PLAYERS * 2)
    bcc @home
    stz z:US_HELD
    stz z:US_TS_ACC
    stz z:US_TS_STEP
    jsr fp_place
    rts

; --- exit: re-park what enter armed ------------------------------------------
exit:
    .a16
    .i16
    jsr fp_obj_park
    rts

; --- tick: one frame (display active — no PPU writes here) ------------------
; In/out: A16/I16, DB=0.
tick:
    .a16
    .i16
    TS_STEP z:US_TS_ACC, TS_MOVE_BASE
    sta z:US_TS_STEP
    ldx #0
@each:
    .a16
    jsr fp_move                 ; X = player, preserved
    inx
    cpx #FP_PLAYERS
    bcc @each
    jmp fp_place

; --- fp_move: one player's frame: d-pad move (clamped) + A-press flip -------
; In: A16/I16, DB=0, X = player 0-3. Out: X preserved. Clobbers A, Y.
fp_move:
    .a16
    .i16
    lda #JOY_ANY
    jsr pad_btn                 ; A = this player's held buttons
    sta z:US_HELD
    lda #JOY_A
    jsr pad_btnp                ; A pressed THIS frame? (the edge)
    tay                         ; Y = the press (0 or JOY_A) — A16, no stale
                                ;   high byte to carry into the index
    phx
    txa
    asl a
    tax                         ; X = player * 2: the arrays' word index
    tya
    beq @no_flip
    lda z:US_FLIP, x
    eor #(1 << 6)               ; OAM attr bit 6: horizontal flip
    sta z:US_FLIP, x
@no_flip:
    .a16
    lda z:US_HELD
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX, x
    clc
    adc z:US_TS_STEP
    cmp #(FP_X_MAX + 1)
    bcc :+
    lda #FP_X_MAX
:   sta z:US_PX, x
@no_right:
    .a16
    lda z:US_HELD
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX, x
    sec
    sbc z:US_TS_STEP
    cmp #FP_X_MIN               ; FP_X_MIN > the step, so no underflow wrap
    bcs :+
    lda #FP_X_MIN
:   sta z:US_PX, x
@no_left:
    .a16
    lda z:US_HELD
    and #JOY_DOWN
    beq @no_down
    lda z:US_PY, x
    clc
    adc z:US_TS_STEP
    cmp #(FP_Y_MAX + 1)
    bcc :+
    lda #FP_Y_MAX
:   sta z:US_PY, x
@no_down:
    .a16
    lda z:US_HELD
    and #JOY_UP
    beq @no_up
    lda z:US_PY, x
    sec
    sbc z:US_TS_STEP
    cmp #FP_Y_MIN
    bcs :+
    lda #FP_Y_MIN
:   sta z:US_PY, x
@no_up:
    .a16
    plx
    rts

; --- fp_place: state -> the OAM shadow, every slot, every frame -------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; A player is SHOWN when its pad can be there: 0-1 always, 2-3 only with the
; adapter (ES_MTAP_ON). Shown: token at (px, py) with its flip; lamp at its
; row slot, LIT while pad_btn(JOY_ANY) is non-zero, else the RING. Not shown:
; both parked.
fp_place:
    .a16
    .i16
    ldx #0                      ; X = player
@each:
    .a16
    txa
    asl a
    asl a
    tay                         ; Y = slot * 4 (both runs share the stride)
    cpx #2
    bcc @shown                  ; players 1-2: a port pad
    lda z:ES_MTAP_ON
    bne @shown                  ; players 3-4: only behind the adapter
    sep #$20
    .a8
    lda #FP_PARK_Y
    sta a:FP_TOKEN0 + 1, y
    sta a:FP_LAMP0 + 1, y
    rep #$20
    .a16
    bra @next
@shown:
    .a16
    lda #JOY_ANY
    jsr pad_btn                 ; Z clear = this pad holds a button
    beq @ring
    lda #FP_TILE_LIT
    bra @lamp
@ring:
    .a16
    lda #FP_TILE_RING
@lamp:
    .a16
    sep #$20
    .a8
    sta a:FP_LAMP0 + 2, y
    lda f:fp_lamp_x, x
    sta a:FP_LAMP0 + 0, y
    lda #FP_LAMP_Y
    sta a:FP_LAMP0 + 1, y
    rep #$20
    .a16
    phx
    txa
    asl a
    tax                         ; X = player * 2: the state arrays' index...
    ora #FP_ATTR_BASE           ; ...and, as player << 1, the palette field
    ora z:US_FLIP, x            ; plus the token's flip bit
    sep #$20
    .a8
    sta a:FP_TOKEN0 + 3, y
    lda z:US_PX, x
    sta a:FP_TOKEN0 + 0, y
    lda z:US_PY, x
    sta a:FP_TOKEN0 + 1, y
    rep #$20
    .a16
    plx
@next:
    .a16
    inx
    cpx #FP_PLAYERS
    bcc @each
    rts

; --- tables ------------------------------------------------------------------
.segment "RODATA"
; Home positions: x for players 1-4, then y for players 1-4 — the four
; quadrants of the play field.
fp_home:
    .word 64, 184, 64, 184
    .word 80, 80, 160, 160
; Lamp x per player (one byte each): FP_LAMP_X0 + n * FP_LAMP_DX.
fp_lamp_x:
    .byte FP_LAMP_X0, FP_LAMP_X0 + FP_LAMP_DX
    .byte FP_LAMP_X0 + 2 * FP_LAMP_DX, FP_LAMP_X0 + 3 * FP_LAMP_DX
.segment "CODE"
.endscope
