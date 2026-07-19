; =============================================================================
; sprite_game — a minimal sprite game (the smallest end-to-end starting point)
; =============================================================================
; A red player sprite you move with the d-pad, and a yellow "dot" to catch.
; When the player overlaps the dot (col_box), the dot jumps to the next preset
; position and the score increments. Movement + multi-sprite + collision + game
; state, all from the macro library. Adapt it: change the sprites, the control,
; what "catching" does.
;
; Controls:
;   D-pad   move the red player (up / down / left / right)
;
; State (DP, main-thread DP=$0000): player $32/$34, dot $36/$38, score $3A,
; dot-index $3C. Sprites: slot 0 = player (OBJ palette 0, red), slot 1 = dot
; (OBJ palette 1, yellow) — slot order is set by spr_clear + the draw order.
;
; Done-condition (emulator-verifiable, deterministic — no RNG):
;   - boots ($7E:E000 == "SFDB")
;   - both sprites visible (red player + yellow dot)
;   - drive the player onto the dot -> score ($3A) increments by 1 and the dot
;     (OAM slot 1 / $36,$38) jumps to the next preset; driving onto it again ->
;     score 2, dot at the following preset
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: palette + tile upload, PPU, start positions, boot
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the sprite tile art, the dot presets, then the engine includes
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Build:  make sprite_game      (-> build/sprite_game.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "DOT CHASER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "sf_collision.inc"     ; col_box (+ engine_api)
.include "engine_state.inc"

OBJ_RED    = $001F              ; player colour (15-bit BGR)
OBJ_YELLOW = $03FF              ; dot colour (15-bit BGR)
PLAYER_X   = $32                ; player screen X (DP word)
PLAYER_Y   = $34                ; player screen Y (DP word)
DOT_X      = $36                ; dot screen X (DP word)
DOT_Y      = $38                ; dot screen Y (DP word)
SCORE      = $3A                ; catches so far (DP word)
DOT_IDX    = $3C                ; which preset the dot sits on (0-3, DP word)
SPEED      = 2                  ; player move step in pixels per frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, start state)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    sf_obj_color 0, 1, OBJ_RED      ; player: OBJ palette 0, slot 1
    sf_obj_color 1, 1, OBJ_YELLOW   ; dot:    OBJ palette 1, slot 1
    sf_load_obj_tile 1, sprite_tile

    jsr init_ppu

    ; (.a16/.i16 track the CPU's register width for ca65 — the 65816 switches
    ;  between 8- and 16-bit registers and the assembler must match the CPU so
    ;  immediates are sized right; the first of several width blocks here.)
    rep #$30                    ; go 16-bit: accumulator + index registers
    .a16
    .i16
    lda #120
    sta PLAYER_X
    lda #100
    sta PLAYER_Y
    lda #200                        ; dot preset 0
    sta DOT_X
    lda #60
    sta DOT_Y
    stz SCORE
    stz DOT_IDX

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt + joypad enable): turn on
                                ;   the VBlank NMI (bit 7) and auto joypad read
                                ;   (bit 0) so the loop's btn reads have data
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — once per frame: read the d-pad, test the catch, draw both sprites
; =============================================================================
game_loop:
    sf_frame_begin

    ; --- move the player with the d-pad ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PLAYER_X
    clc
    adc #SPEED
    sta PLAYER_X
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PLAYER_X
    sec
    sbc #SPEED
    sta PLAYER_X
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda PLAYER_Y
    clc
    adc #SPEED
    sta PLAYER_Y
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda PLAYER_Y
    sec
    sbc #SPEED
    sta PLAYER_Y
@no_up:

    ; --- catch the dot? player box vs dot box, both 8x8 ---
    col_box PLAYER_X, PLAYER_Y, #8, #8, DOT_X, DOT_Y, #8, #8
    beq @no_catch
    ; overlap -> score++ and move the dot to the next preset (debounces: next
    ; frame the dot is elsewhere, so one pass = one catch).
    rep #$30
    .a16
    .i16
    inc SCORE
    lda DOT_IDX
    inc a
    and #$0003                      ; 4 presets, wrap
    sta DOT_IDX
    asl a
    asl a                           ; *4 bytes per (x,y) preset
    tax
    lda f:dot_presets, x
    sta DOT_X
    lda f:dot_presets + 2, x
    sta DOT_Y
@no_catch:

    ; --- draw: slot 0 = player (pal 0), slot 1 = dot (pal 1, flags $02) ---
    spr_clear
    spr #1, PLAYER_X, PLAYER_Y, #$00, #2
    spr #1, DOT_X, DOT_Y, #$02, #2
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the sprite tile art, the dot presets, then the engine includes
; =============================================================================
; one solid 8x8 4bpp tile (all colour index 1)
sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; dot preset positions (x, y), cycled on each catch
dot_presets:
    .word 200, 60
    .word 60, 60
    .word 200, 160
    .word 60, 160

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "collision_engine.asm"
