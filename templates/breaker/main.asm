; =============================================================================
; breaker — a paddle-and-ball block-breaker
; =============================================================================
; A cyan paddle (d-pad left/right), a white ball, and a 6-row rainbow brick
; wall on BG1. Bricks are tile-flagged cells (`sf_tile_flags` bit 1); the ball
; probes its leading edge at two points with `col_map` and breaks bricks with
; `mset`-as-you-break. Walls (flag bit 0) reflect without breaking. Paddle
; english: where the ball lands on the paddle picks its outgoing angle
; (4 zones: -2/-1/+1/+2). SCORE / BALLS HUD on BG3.
;
; Controls: Left/Right move the paddle · A launches the ball from WAIT ·
;           Start restarts after GAME OVER or a WIN.
;
; Built from the kit's scenario recipes — the same three the other rails mix:
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
; File layout (section banners, in order):
;   INIT              — RESET: uploads, palettes, tile flags, first level, NMI on
;   MAIN LOOP         — game_loop, the once-per-frame heartbeat (start reading here)
;   PER-FRAME UPDATE  — state dispatch (WAIT / PLAY / GAME OVER-WIN) + gameplay subs
;   SUBROUTINES       — move/collide/score/draw helpers, level build, HUD
;   DATA              — tile bitmaps + HUD/message strings
; game_loop is the once-per-frame heartbeat — start reading there.
;
; Build:  make breaker   (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad.cfg
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "BRICK BUSTER"
SF_HDR_TITLE_SET = 1
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
.include "tad-audio.inc"        ; TAD ca65 audio-driver API imports
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids (the compiled song set)
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_sfx (blips)
.include "sf_fx.inc"            ; sf_colormath_on + sf_gradient_rgb (backdrop ramp)

; --- colours (15-bit BGR) ---
OBJ_CYAN   = $7FE0              ; paddle
OBJ_WHITE  = $7FFF              ; ball
BG_GREY    = $39CE              ; walls
BG_RED     = $001F              ; brick row colours (base face)...
BG_ORANGE  = $01BF
BG_YELLOW  = $03FF
BG_GREEN   = $03E0
; brick bevel — a lighter top/left highlight + a darker bottom/right shadow per
; row colour, for a raised-brick look (BG palette 0 slots 6-13, previously free)
BG_RED_HL    = $295F
BG_RED_SH    = $000D
BG_ORANGE_HL = $2AFF
BG_ORANGE_SH = $00AD
BG_YELLOW_HL = $2BFF
BG_YELLOW_SH = $01AD
BG_GREEN_HL  = $2BEA
BG_GREEN_SH  = $01A0

; --- backdrop gradient (COLDATA colour-add on the BACKDROP only): a subtle
;     night ramp behind the arena. Intensity 0-31 per channel, top -> bottom. ---
SKY_TOP_R = 4                   ; dark slate-blue at the top of the field
SKY_TOP_G = 6
SKY_TOP_B = 14
SKY_BOT_R = 1                   ; near-black deep blue at the pit
SKY_BOT_G = 1
SKY_BOT_B = 6

; --- DP game state: $32-$5F is the game's window; the engine owns the rest
;     (see engine_state.inc). All 16-bit words. ---
PX      = $32                   ; paddle X (top-left)
BX      = $34                   ; ball X
BY      = $36                   ; ball Y
VX      = $38                   ; ball X velocity (signed 16-bit)
VY      = $3A                   ; ball Y velocity (signed 16-bit)
SCORE   = $3C                   ; running score (10 per brick)
BALLS   = $3E                   ; balls remaining (starts at 3)
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
BALLS_STR = $56                 ; 2-byte HUD buffer: BALLS as 1 ASCII digit + NUL
BLINK   = $58                   ; WAIT-screen frame counter (blinks "PRESS A")

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

; =============================================================================
; INIT — boot: NMI vector, GFX/audio uploads, palettes, tile flags, first
;        level, then NMI on. Runs once under the coldstart forced blank.
; =============================================================================

NMI:
.include "nmi_handler.asm"          ; stock engine NMI (commits shadow OAM + scroll)

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    sf_audio_init                   ; upload the SPC700 driver ONCE at boot, while
                                    ;   the S-SMP is still in IPL and NMI is off
    jsr hdma_alloc_init             ; HDMA allocator baseline (for the backdrop ramp)

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
    sf_bg_color 0, 6, BG_RED_HL         ; brick bevel highlight/shadow (slots 6-13)
    sf_bg_color 0, 7, BG_RED_SH
    sf_bg_color 0, 8, BG_ORANGE_HL
    sf_bg_color 0, 9, BG_ORANGE_SH
    sf_bg_color 0, 10, BG_YELLOW_HL
    sf_bg_color 0, 11, BG_YELLOW_SH
    sf_bg_color 0, 12, BG_GREEN_HL
    sf_bg_color 0, 13, BG_GREEN_SH
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

    ; Arm the backdrop gradient once, under forced blank, before NMI. Colour
    ; math ADDs a per-scanline COLDATA ramp on the BACKDROP ONLY, so the bricks,
    ; walls, sprites and HUD are untouched — only the empty space behind the
    ; arena picks up the night ramp. The NMI re-arms HDMA ($420C) each VBlank.
    sf_colormath_on #1, #$20        ; CGADSUB: ADD fixed colour on the backdrop
    sf_gradient_rgb #SKY_TOP_R, #SKY_TOP_G, #SKY_TOP_B, #SKY_BOT_R, #SKY_BOT_G, #SKY_BOT_B

    sf_debug_magic

    ; The 65816 carries its register width in the P flags; the .a8/.a16/.i16
    ; directives tell the assembler which width the CPU is in so it sizes
    ; immediates right. sep #$20 = 8-bit A (this port takes one byte); the
    ; matching .a8 keeps assembler and CPU in sync (see width-tracking rule).
    sep #$20
    .a8
    lda #$81
    sta $4200                       ; NMITIMEN (interrupt enable): NMI + auto-joypad on
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: the once-per-frame heartbeat. Start reading here.
; =============================================================================
game_loop:
    sf_frame_begin
    sf_audio_tick                   ; pump the audio queue + song streaming, every frame
    jsr update                      ; state-dispatched game logic
    jsr hud_update                  ; reprint numbers when DIRTY
    jsr draw                        ; paddle + ball -> shadow OAM
    jsr mirror_debug                ; score/balls/bricks/state -> $7E:E010+
    sf_frame_end
    jmp game_loop

; =============================================================================
; PER-FRAME UPDATE — state dispatch: run WAIT / PLAY / GAME OVER-WIN this frame
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
    ; Blink "PRESS A" on a free-running frame counter: toggle the prompt row
    ; every 32 frames (bit 5), acting only on the phase edge (low 5 bits zero)
    ; so we reprint/clear twice a cycle, not every frame. The title above stays.
    inc BLINK
    lda BLINK
    and #$1F
    bne @blink_done                 ; not a phase edge: leave the prompt as-is
    lda BLINK
    and #$20
    beq @blink_show
    sf_text_clear #16, #17          ; hide phase: clear just the PRESS A row (16)
    bra @blink_done
@blink_show:
    .a16
    print str_press_a, #96, #128    ; show phase: reprint PRESS A
@blink_done:
    .a16
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
    sf_text_clear #14, #20          ; wipe the title card + "PRESS A"
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
    sf_sfx #SFX::robot_ascend        ; win fanfare blip (rising)
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
; SUBROUTINES — gameplay helpers: input, ball physics, collision, HUD, draw,
;               level build. Called from the state handlers above.
; =============================================================================

; --- move_paddle — d-pad left/right, clamped to the walls ---
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

; --- move_ball_x / move_ball_y — per-axis move-check with leading-edge probes ---
; The canonical maze move-check shape, plus brick breaking: compute the
; tentative position, probe the leading edge at two points (so cell-spanning
; contacts register), and either take the move or reflect the axis. Max speed
; is 2 px/frame against 8 px tiles — no tunnelling.
; The two probes sit at +1 and +6 of the 8 px ball, not the 0/7 corners, so a
; lone corner pixel can slide past a live cell without breaking it — a bounded
; 1 px clip, invisible because the ball tile's corner pixels are transparent.
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
    sta HITF                        ; HITF = both probes' bits (wall 1 / brick 2)
    bne @bounce
    lda NEWX
    sta BX                          ; clear: take the move
    rts
@bounce:
    .a16
    lda HITF
    and #2                          ; did a brick break this contact?
    bne @reflect                    ;   yes: its ding stands, no wall tick
    sf_sfx #SFX::menu_cursor        ; wall bounce blip
@reflect:
    .a16
    lda VX                          ; blocked: reflect, stay put
    eor #$FFFF                      ; negate (two's complement): reverse VX
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
    sta HITF                        ; HITF = both probes' bits (wall 1 / brick 2)
    bne @bounce
    lda NEWY
    sta BY
    rts
@bounce:
    .a16
    lda HITF
    and #2                          ; did a brick break this contact?
    bne @reflect                    ;   yes: its ding stands, no wall tick
    sf_sfx #SFX::menu_cursor        ; wall bounce blip
@reflect:
    .a16
    lda VY
    eor #$FFFF                      ; negate (two's complement): reverse VY
    inc a
    sta VY
    rts

; --- probe_point — test (PROBE_X, PROBE_Y); break a brick where one is hit ---
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
    sf_sfx #SFX::collect_coin       ; brick-break blip (the satisfying "ding")
    lda #2                          ; A = 2: brick broke — blocked, distinct from
    rts                             ;   wall (1) so the bounce skips the wall tick

; --- paddle_check — ball vs paddle (only while falling) + english ---
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
    sf_sfx #SFX::menu_select        ; paddle bounce blip
    ; Snap the ball onto the paddle top (192). This is a deliberate rescue: a
    ; fast descent can be as deep as ~207 inside the paddle box when the hit
    ; registers, and snapping up to 192 keeps it from sinking past the paddle
    ; on the next frame. Visible only on the steepest catches (normal 1-2 px).
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

; --- floor_check — ball below the paddle = ball lost ---
floor_check:
    .a16
    rep #$30
    lda BY
    cmp #BALL_LOST_Y
    bcs @lost
    rts
@lost:
    .a16
    sf_sfx #SFX::player_hurt         ; ball-lost blip
    dec BALLS
    lda #1
    sta DIRTY
    lda BALLS
    beq @game_over
    stz STATE                       ; back to WAIT (ball rides the paddle)
    stz BLINK                       ; PRESS A starts shown again
    print str_title, #80, #112      ; re-show the title card between balls
    print str_press_a, #96, #128
    rts
@game_over:
    .a16
    lda #2
    sta STATE
    print str_gameover, #88, #128
    print str_pressstart, #80, #144
    rts

; --- hud_update — reprint SCORE/BALLS when they changed this frame ---
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
    ; BALLS is 0-3: print ONE ASCII digit (a 5-digit "00003" reads as a score).
    ; '0'+BALLS in the low byte, NUL in the high byte -> a 1-char string in one
    ; store. BALLS never grows past 1 digit, so no stale trailing cols.
    lda BALLS
    clc
    adc #'0'
    and #$00FF
    sta BALLS_STR
    print BALLS_STR, #208, #8
    rts

; --- draw — paddle (3 x 8px sprites) + ball -> shadow OAM, slot order 0..3 ---
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
    ; slot 3: ball — only while the game is live (state 0/1). After GAME OVER
    ; or WIN (state 2/3) leave it parked offscreen (spr_clear set Y=$F0), so no
    ; ball freezes mid-flight over the end screen.
    rep #$30
    .a16
    .i16
    lda STATE
    cmp #2
    bcs @no_ball
    spr #1, BX, BY, #$02, #2            ; slot 3: ball (OBJ pal 1)
@no_ball:
    .a16
    rts

; --- mirror_debug — game state -> debug region (test-readable, A16 = 2 bytes) ---
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

; --- reset_game — full (re)start: map, HUD, state. Idempotent. ---
reset_game:
    .a16
    sf_text_clear #14, #20          ; wipe the title card + any message rows
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
    stz BLINK                       ; PRESS A starts shown, blink from here
    print str_score, #8, #8
    print str_balls, #160, #8
    print str_title, #80, #112      ; "BRICK BUSTER" title card
    print str_press_a, #96, #128
    rts

; --- build_level — walls (tile 1) + 6 rainbow brick rows (tiles 2-5) ---
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
; DATA — tiles (SNES 4bpp planar, 32 bytes each) + strings
; =============================================================================

; wall: solid colour 1 (grey)
wall_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; bricks: 7x7 face + transparent right column / bottom row = mortar lines.
; Each face is beveled: top row + left column = the row's highlight index,
; bottom row + right column = its shadow index, interior = its base colour.
; Indices per row colour — base / highlight / shadow:
;   red 2/6/7 · orange 3/8/9 · yellow 4/10/11 · green 5/12/13.
; (These bytes are generated; regenerate if the bevel layout changes.)
brick_red_tile:
    .byte $00,$FE, $02,$FE, $02,$FE, $02,$FE
    .byte $02,$FE, $02,$FE, $FE,$FE, $00,$00
    .byte $FE,$00, $82,$00, $82,$00, $82,$00
    .byte $82,$00, $82,$00, $FE,$00, $00,$00

brick_orange_tile:
    .byte $00,$00, $7E,$7C, $7E,$7C, $7E,$7C
    .byte $7E,$7C, $7E,$7C, $FE,$00, $00,$00
    .byte $00,$FE, $00,$82, $00,$82, $00,$82
    .byte $00,$82, $00,$82, $00,$FE, $00,$00

brick_yellow_tile:
    .byte $00,$FE, $02,$82, $02,$82, $02,$82
    .byte $02,$82, $02,$82, $FE,$FE, $00,$00
    .byte $00,$FE, $7C,$82, $7C,$82, $7C,$82
    .byte $7C,$82, $7C,$82, $00,$FE, $00,$00

brick_green_tile:
    .byte $00,$00, $7E,$00, $7E,$00, $7E,$00
    .byte $7E,$00, $7E,$00, $FE,$00, $00,$00
    .byte $FE,$FE, $FE,$82, $FE,$82, $FE,$82
    .byte $FE,$82, $FE,$82, $FE,$FE, $00,$00

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
str_title:      .byte "BRICK BUSTER", 0
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
.include "tad_bridge.asm"          ; TAD audio bridge (tad_bridge_init/process, tad_sfx)
; backdrop-gradient engine partners (order: hdma_alloc -> hdma_engine ->
; hdma_color_engine; colormath_engine is order-independent)
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
.include "sf_text_data.inc"
