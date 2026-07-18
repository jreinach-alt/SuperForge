; =============================================================================
; breaker — a paddle-and-ball block-breaker (the 14th rail)
; =============================================================================
; A cyan paddle (d-pad left/right), a white ball, and a 6-row rainbow brick
; wall on BG1. Bricks are tile-flagged cells (`sf_tile_flags` bit 1); the ball
; probes its leading edge at two points with `col_map` and breaks bricks with
; `mset`-as-you-break. Walls (flag bit 0) reflect without breaking. Paddle
; english: where the ball lands on the paddle picks its outgoing angle
; (4 zones: -2/-1/+1/+2). SCORE / BALLS HUD on BG3.
;
; Composed bricks (per scenarios/README.md routing map):
;   sprite_game  -> spr + col_box (ball vs paddle)
;   maze         -> sf_tile_flags + col_map terrain probes, mset map building
;   hud_game     -> sf_text HUD, reprint-on-change
;
; Game flow: WAIT (ball rides paddle, A launches) -> PLAY -> ball below the
; paddle costs a ball -> 0 balls = GAME OVER, all 180 bricks = YOU WIN; Start
; restarts either way. Launch direction alternates with the balls remaining.
;
; State (DP $32-$5F): see the equates below.
; Debug mirrors ($7E:E0xx): score $E010, balls $E012, bricks left $E014,
; state $E016 (0=wait 1=play 2=game-over 3=win).
; Sprites (slot = call order after spr_clear): 0-2 paddle (tile 2), 3 ball
; (tile 1).
;
; Done-condition (emulator-verifiable, deterministic — no RNG; the full list
; is tests/test_breaker.py):
;   - boots ($7E:E000 == "SFDB"); walls + 180 bricks visible on BG1 (VRAM +
;     rendered pixels), HUD labels + counters printed on BG3
;   - d-pad moves the paddle BOTH directions (OAM + pixels), clamped to the
;     walls; in WAIT the ball rides the paddle
;   - A launches (state 0 -> 1, ball rises); the ball bounces off walls and
;     paddle, staying inside the arena; brick cells it hits go to tile 0 in
;     VRAM, BRICKS ($E014) drops, SCORE ($E010) rises and the printed counter
;     reprints
;   - a closed-loop paddle bot keeps the rally alive (paddle bounce works)
;   - losing a ball returns to WAIT with BALLS down one; losing the last ball
;     -> state 2 + "GAME OVER" rendered; Start rebuilds the wall and resets
;     the counters (all 180 bricks back in VRAM)
;
; Build:  make breaker      (-> build/breaker.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags, col_map
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16, sf_text_clear
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "sf_collision.inc"     ; col_box
.include "engine_state.inc"

; --- colours (15-bit BGR) ---
OBJ_CYAN   = $7FE0              ; paddle
OBJ_WHITE  = $7FFF              ; ball
BG_GREY    = $39CE              ; walls
BG_RED     = $001F              ; brick row colours...
BG_ORANGE  = $01BF
BG_YELLOW  = $03FF
BG_GREEN   = $03E0

; --- DP game state ($32-$5F is the game's per AGENTS/macro README) ---
PX      = $32                   ; paddle X (top-left)
BX      = $34                   ; ball X
BY      = $36                   ; ball Y
VX      = $38                   ; ball X velocity (signed 16-bit)
VY      = $3A                   ; ball Y velocity (signed 16-bit)
SCORE   = $3C
BALLS   = $3E
BRICKS  = $40                   ; bricks remaining
STATE   = $42                   ; 0 wait / 1 play / 2 game over / 3 win
LOOPI   = $44                   ; map-build loop counters (mset clobbers X/Y)
LOOPJ   = $46
PROBE_X = $48                   ; ball terrain probe point
PROBE_Y = $4A
NEWX    = $4C                   ; tentative ball position
NEWY    = $4E
TMP     = $50                   ; scratch (sprite x, row tile)
HITF    = $52                   ; probe hit accumulator
DIRTY   = $54                   ; 1 = HUD numbers need reprint

; --- geometry ---
PADDLE_Y     = 200
PADDLE_W     = 24               ; 3 x 8px sprites
PADDLE_SPEED = 3
PADDLE_MIN_X = 8                ; right of the left wall (col 0)
PADDLE_MAX_X = 224              ; 248 - PADDLE_W (left of the right wall)
BALL_WAIT_Y  = 192              ; riding the paddle
BALL_LOST_Y  = 216              ; below the paddle = ball lost
BRICK_TOTAL  = 180              ; 6 rows x 30 cols

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; --- uploads under the coldstart forced blank (before screen-on) ---
    sf_load_bg_tile 1, wall_tile
    sf_load_bg_tile 2, brick_red_tile
    sf_load_bg_tile 3, brick_orange_tile
    sf_load_bg_tile 4, brick_yellow_tile
    sf_load_bg_tile 5, brick_green_tile
    sf_bg_color 0, 1, BG_GREY
    sf_bg_color 0, 2, BG_RED
    sf_bg_color 0, 3, BG_ORANGE
    sf_bg_color 0, 4, BG_YELLOW
    sf_bg_color 0, 5, BG_GREEN
    sf_load_obj_tile 1, ball_tile
    sf_load_obj_tile 2, paddle_tile
    sf_obj_color 0, 1, OBJ_CYAN     ; paddle: OBJ palette 0
    sf_obj_color 1, 1, OBJ_WHITE    ; ball:   OBJ palette 1
    sf_text_init                    ; font + white text colour

    jsr init_ppu
    gfxmode #1                      ; BG1 on, shadow tilemaps zeroed

    ; --- terrain flags: tile 1 = wall (solid), tiles 2-5 = brick ---
    sf_tile_flags 1, SF_FLAG_SOLID  ; bit 0: reflects, never breaks
    sf_tile_flags 2, $02            ; bit 1: brick — reflects AND breaks
    sf_tile_flags 3, $02
    sf_tile_flags 4, $02
    sf_tile_flags 5, $02

    jsr reset_game                  ; map + HUD + vars (state = WAIT)

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                       ; NMI + auto-joypad on
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin
    jsr update                      ; state-dispatched game logic
    jsr hud_update                  ; reprint numbers when DIRTY
    jsr draw                        ; paddle + ball -> shadow OAM
    jsr mirror_debug                ; score/balls/bricks/state -> $7E:E010+
    sf_frame_end
    jmp game_loop

; =============================================================================
; update — dispatch on STATE
; =============================================================================
update:
    rep #$30
    .a16
    .i16
    lda STATE
    beq @wait
    cmp #1
    beq @play
    jmp state_end                   ; 2 game over / 3 win
@wait:
    .a16
    jmp state_wait
@play:
    .a16
    jmp state_play

; --- WAIT: ball rides the paddle; A launches -------------------------------
state_wait:
    .a16
    jsr move_paddle
    rep #$30
    .a16
    lda PX
    clc
    adc #8                          ; ball centred on the 24px paddle
    sta BX
    lda #BALL_WAIT_Y
    sta BY
    btnp #BTN_A
    bne @launch
    rts
@launch:
    .a16
    rep #$30
    lda #1
    sta STATE
    lda #$FFFE                      ; VY = -2 (up)
    sta VY
    lda BALLS                       ; alternate launch angle with balls left
    lsr a
    bcs @vx_right
    lda #$FFFF                      ; VX = -1
    sta VX
    bra @msg
@vx_right:
    .a16
    lda #1                          ; VX = +1
    sta VX
@msg:
    .a16
    sf_text_clear #16, #20          ; wipe "PRESS A"
    rts

; --- PLAY: move everything, collide, score ---------------------------------
state_play:
    .a16
    jsr move_paddle
    jsr move_ball_x
    jsr move_ball_y
    jsr paddle_check
    jsr floor_check
    ; win when the wall is gone (only from PLAY — floor_check may have left it)
    rep #$30
    .a16
    lda BRICKS
    beq @maybe_win
    rts
@maybe_win:
    .a16
    lda STATE
    cmp #1
    beq @win
    rts
@win:
    .a16
    lda #3
    sta STATE
    print str_win, #96, #128
    rts

; --- GAME OVER / WIN: Start restarts ----------------------------------------
state_end:
    .a16
    btnp #BTN_START
    bne @restart
    rts
@restart:
    .a16
    jsr reset_game
    rts

; =============================================================================
; move_paddle — d-pad left/right, clamped to the walls
; =============================================================================
move_paddle:
    .a16
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PX
    sec
    sbc #PADDLE_SPEED
    cmp #PADDLE_MIN_X
    bcs @store_l
    lda #PADDLE_MIN_X
@store_l:
    .a16
    sta PX
@no_left:
    .a16
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PX
    clc
    adc #PADDLE_SPEED
    cmp #PADDLE_MAX_X
    bcc @store_r
    lda #PADDLE_MAX_X
@store_r:
    .a16
    sta PX
@no_right:
    .a16
    rts

; =============================================================================
; move_ball_x / move_ball_y — per-axis move-check with leading-edge probes
; =============================================================================
; The canonical maze move-check shape, plus brick breaking: compute the
; tentative position, probe the leading edge at two points (so cell-spanning
; contacts register), and either take the move or reflect the axis. Max speed
; is 2 px/frame against 8 px tiles — no tunnelling.
move_ball_x:
    rep #$30
    .a16
    .i16
    lda BX
    clc
    adc VX
    sta NEWX
    lda VX
    bmi @lead_left
    lda NEWX
    clc
    adc #7                          ; moving right: probe the right edge
    bra @lead
@lead_left:
    .a16
    lda NEWX                        ; moving left: probe the left edge
@lead:
    .a16
    sta PROBE_X
    lda BY
    inc a
    sta PROBE_Y                     ; probe near the top of the ball...
    jsr probe_point
    sta HITF
    rep #$30
    .a16
    lda BY
    clc
    adc #6
    sta PROBE_Y                     ; ...and near the bottom
    jsr probe_point
    ora HITF
    bne @bounce
    lda NEWX
    sta BX                          ; clear: take the move
    rts
@bounce:
    .a16
    lda VX                          ; blocked: reflect, stay put
    eor #$FFFF
    inc a
    sta VX
    rts

move_ball_y:
    rep #$30
    .a16
    .i16
    lda BY
    clc
    adc VY
    sta NEWY
    lda VY
    bmi @lead_top
    lda NEWY
    clc
    adc #7                          ; moving down: probe the bottom edge
    bra @lead
@lead_top:
    .a16
    lda NEWY                        ; moving up: probe the top edge
@lead:
    .a16
    sta PROBE_Y
    lda BX
    inc a
    sta PROBE_X
    jsr probe_point
    sta HITF
    rep #$30
    .a16
    lda BX
    clc
    adc #6
    sta PROBE_X
    jsr probe_point
    ora HITF
    bne @bounce
    lda NEWY
    sta BY
    rts
@bounce:
    .a16
    lda VY
    eor #$FFFF
    inc a
    sta VY
    rts

; =============================================================================
; probe_point — test (PROBE_X, PROBE_Y); break a brick where one is hit
; =============================================================================
; Returns A16 = 1 if the point is blocked (wall OR brick), 0 if clear.
; A brick hit clears its cell (mset tile 0 — unflagged), scores 10, and
; decrements BRICKS. Clobbers A, X, Y (col_map/mset do).
probe_point:
    .a16
    col_map #1, PROBE_X, PROBE_Y, #1    ; bit 1: brick?
    bne @brick
    col_map #1, PROBE_X, PROBE_Y, #0    ; bit 0: solid wall?
    rts                                 ; A = 0/1
@brick:
    .a16
    rep #$30
    .i16
    lda PROBE_X                     ; cell = probe point >> 3
    lsr a
    lsr a
    lsr a
    sta LOOPI                       ; (reuse the map-build slots as cell x/y)
    lda PROBE_Y
    lsr a
    lsr a
    lsr a
    sta LOOPJ
    mset #1, LOOPI, LOOPJ, #0       ; break it: tile 0 = empty, no flags
    rep #$30
    .a16
    lda SCORE
    clc
    adc #10
    sta SCORE
    dec BRICKS
    lda #1
    sta DIRTY                       ; HUD reprint
    rts                             ; A = 1: blocked (the ball reflects)

; =============================================================================
; paddle_check — ball vs paddle (only while falling) + english
; =============================================================================
; 4-zone english: outgoing VX from where the ball's centre struck the 24px
; paddle — outer quarter -2/+2, inner quarter -1/+1. More control than a
; centre-side split: the player can aim.
paddle_check:
    .a16
    rep #$30
    lda VY
    bpl @falling
    rts                             ; moving up: no paddle contact
@falling:
    .a16
    col_box BX, BY, #8, #8, PX, #PADDLE_Y, #PADDLE_W, #8
    bne @hit
    rts
@hit:
    .a16
    rep #$30
    lda #BALL_WAIT_Y                ; snap on top of the paddle
    sta BY
    lda #$FFFE                      ; VY = -2 (up)
    sta VY
    ; english: outgoing VX from where the ball's centre struck the paddle
    lda BX
    clc
    adc #4
    sec
    sbc PX                          ; dx = ball centre - paddle left (-4..28)
    bmi @far_left
    cmp #6
    bcc @far_left
    cmp #12
    bcc @mid_left
    cmp #18
    bcc @mid_right
    lda #2                          ; outer right: VX = +2
    sta VX
    rts
@mid_right:
    .a16
    lda #1
    sta VX
    rts
@mid_left:
    .a16
    lda #$FFFF                      ; -1
    sta VX
    rts
@far_left:
    .a16
    lda #$FFFE                      ; -2
    sta VX
    rts

; =============================================================================
; floor_check — ball below the paddle = ball lost
; =============================================================================
floor_check:
    .a16
    rep #$30
    lda BY
    cmp #BALL_LOST_Y
    bcs @lost
    rts
@lost:
    .a16
    dec BALLS
    lda #1
    sta DIRTY
    lda BALLS
    beq @game_over
    stz STATE                       ; back to WAIT (ball rides the paddle)
    print str_press_a, #96, #128
    rts
@game_over:
    .a16
    lda #2
    sta STATE
    print str_gameover, #88, #128
    print str_pressstart, #80, #144
    rts

; =============================================================================
; hud_update — reprint SCORE/BALLS when they changed this frame
; =============================================================================
hud_update:
    rep #$30
    .a16
    lda DIRTY
    bne @reprint
    rts
@reprint:
    .a16
    stz DIRTY
    sf_print_u16 SCORE, #56, #8
    sf_print_u16 BALLS, #208, #8
    rts

; =============================================================================
; draw — paddle (3 x 8px sprites) + ball -> shadow OAM, slot order 0..3
; =============================================================================
draw:
    .a16
    spr_clear
    spr #2, PX, #PADDLE_Y, #$00, #2     ; slot 0: paddle left  (OBJ pal 0)
    rep #$30
    .a16
    lda PX
    clc
    adc #8
    sta TMP
    spr #2, TMP, #PADDLE_Y, #$00, #2    ; slot 1: paddle mid
    rep #$30
    .a16
    lda PX
    clc
    adc #16
    sta TMP
    spr #2, TMP, #PADDLE_Y, #$00, #2    ; slot 2: paddle right
    spr #1, BX, BY, #$02, #2            ; slot 3: ball (OBJ pal 1)
    rts

; =============================================================================
; mirror_debug — game state -> debug region (test-readable, A16 = 2 bytes)
; =============================================================================
mirror_debug:
    rep #$30
    .a16
    .i16
    ldx #$0000                      ; ",x" forces true 24-bit long encoding
    lda SCORE
    sta f:$7E0000 + $E010, x
    lda BALLS
    sta f:$7E0000 + $E012, x
    lda BRICKS
    sta f:$7E0000 + $E014, x
    lda STATE
    sta f:$7E0000 + $E016, x
    rts

; =============================================================================
; reset_game — full (re)start: map, HUD, state. Idempotent.
; =============================================================================
reset_game:
    .a16
    sf_text_clear #16, #20          ; wipe any message rows
    jsr build_level
    rep #$30
    .a16
    .i16
    stz SCORE
    lda #3
    sta BALLS
    lda #BRICK_TOTAL
    sta BRICKS
    stz STATE                       ; WAIT
    lda #116
    sta PX                          ; paddle centred
    lda #1
    sta DIRTY                       ; numbers print on the first frame
    print str_score, #8, #8
    print str_balls, #160, #8
    print str_press_a, #96, #128
    rts

; =============================================================================
; build_level — walls (tile 1) + 6 rainbow brick rows (tiles 2-5)
; =============================================================================
; Top wall row 2, side walls cols 0/31 rows 3..27 (bottom open — that's the
; pit). Bricks rows 5..10, cols 1..30, row colour cycling red/orange/yellow/
; green. mset clobbers X/Y, so the counters live in DP.
build_level:
    rep #$30
    .a16
    .i16
    stz LOOPI
@top:
    .a16
    mset #1, LOOPI, #2, #1
    rep #$30
    .a16
    lda LOOPI
    inc a
    sta LOOPI
    cmp #32
    bne @top
    lda #3
    sta LOOPI
@sides:
    .a16
    mset #1, #0, LOOPI, #1
    mset #1, #31, LOOPI, #1
    rep #$30
    .a16
    lda LOOPI
    inc a
    sta LOOPI
    cmp #28
    bne @sides
    lda #5
    sta LOOPJ
@rows:
    .a16
    lda LOOPJ
    sec
    sbc #5
    and #3
    clc
    adc #2                          ; row tile: 2 + ((row-5) & 3)
    sta TMP
    lda #1
    sta LOOPI
@cols:
    .a16
    mset #1, LOOPI, LOOPJ, TMP
    rep #$30
    .a16
    lda LOOPI
    inc a
    sta LOOPI
    cmp #31
    bne @cols
    lda LOOPJ
    inc a
    sta LOOPJ
    cmp #11
    bne @rows
    rts

; =============================================================================
; data — tiles (SNES 4bpp planar, 32 bytes each) + strings
; =============================================================================

; wall: solid colour 1 (grey)
wall_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; bricks: 7x7 face + transparent right column / bottom row = mortar lines.
; Face colour index picks the row colour: 2=red, 3=orange, 4=yellow, 5=green.
brick_red_tile:                     ; colour 2 = plane1 only
    .byte $00,$FE, $00,$FE, $00,$FE, $00,$FE
    .byte $00,$FE, $00,$FE, $00,$FE, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

brick_orange_tile:                  ; colour 3 = planes 0+1
    .byte $FE,$FE, $FE,$FE, $FE,$FE, $FE,$FE
    .byte $FE,$FE, $FE,$FE, $FE,$FE, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

brick_yellow_tile:                  ; colour 4 = plane 2 only
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $FE,$00, $FE,$00, $FE,$00, $FE,$00
    .byte $FE,$00, $FE,$00, $FE,$00, $00,$00

brick_green_tile:                   ; colour 5 = planes 0+2
    .byte $FE,$00, $FE,$00, $FE,$00, $FE,$00
    .byte $FE,$00, $FE,$00, $FE,$00, $00,$00
    .byte $FE,$00, $FE,$00, $FE,$00, $FE,$00
    .byte $FE,$00, $FE,$00, $FE,$00, $00,$00

; ball: 8x8 round-ish, colour 1 (white, OBJ palette 1 via spr flags)
ball_tile:
    .byte $3C,$00, $7E,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $7E,$00, $3C,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; paddle segment: 8x6 bar, colour 1 (cyan, OBJ palette 0)
paddle_tile:
    .byte $00,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

str_score:      .byte "SCORE", 0
str_balls:      .byte "BALLS", 0
str_press_a:    .byte "PRESS A", 0
str_gameover:   .byte "GAME OVER", 0
str_pressstart: .byte "PRESS START", 0
str_win:        .byte "YOU WIN!", 0

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
