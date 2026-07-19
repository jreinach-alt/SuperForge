; =============================================================================
; maze — walk a room with solid walls (tile collision)
; =============================================================================
; A red player you move with the d-pad through a walled room: a border wall
; plus two interior walls, all built from a solid-flagged tile. Movement is
; the canonical per-axis move-check: compute the tentative position, test it
; with sf_solid_box, keep it only if clear — so you slide along walls instead
; of sticking to them. Demonstrates the tile-collision surface (sf_map.inc)
; composed with backgrounds + sprites + input. Adapt it: bigger maps, hazard
; tiles (sf_tile_flags bit 1 + col_map), doors (clear a cell with mset).
;
; Controls:
;   D-pad   move the player (walk into a wall and you slide along it, not stick)
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: tile + palette uploads, PPU, build the walled room, boot
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the wall + sprite tile art, engine includes
; game_loop is the frame heartbeat; start reading there.
;
; State (DP): player pos $32/$34, tentative pos $36/$38, map-fill $46-$47.
;
; Done-condition (emulator-verifiable):
;   - boots; grey walls + red player visible
;   - the player moves freely in open floor (all four directions)
;   - walking into a wall stops AT the wall edge (no overlap, no pass-through,
;     no sticking — the free axis still slides)
;
; Build:  make maze      (-> build/maze.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "LABYRINTH"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags, sf_solid_box (+ col_map)
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED  = $001F                ; player colour (15-bit BGR: red)
BG_GREY  = $39CE                ; walls
PX       = $32                  ; player position
PY       = $34
NEWX     = $36                  ; tentative position (per-axis move check)
NEWY     = $38
MZ_I     = $46                  ; map-build loop counter
SPEED    = 2                    ; player move step, px/frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, room, boot)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; uploads under the coldstart forced blank (before screen-on)
    sf_load_bg_tile 2, wall_tile
    sf_bg_color 0, 1, BG_GREY
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED

    jsr init_ppu
    gfxmode #1                  ; zeros shadow tilemaps + sets 32x32 dims

    ; --- the room (after gfxmode): tile 2 = wall, flagged solid ---
    sf_tile_flags 2, SF_FLAG_SOLID

    rep #$30
    .a16                        ; first width switch: 16-bit A/X/Y. .a16/.i16 tell
    .i16                        ;   ca65 the CPU width so it sizes operands right
    ; border: top row 0 + bottom row 27 (28 rows = 224 px visible)
    stz MZ_I
@border_h:
    mset #1, MZ_I, #0,  #2
    mset #1, MZ_I, #27, #2
    lda MZ_I
    inc a
    sta MZ_I
    cmp #32
    bne @border_h
    ; border: left col 0 + right col 31
    stz MZ_I
@border_v:
    mset #1, #0,  MZ_I, #2
    mset #1, #31, MZ_I, #2
    lda MZ_I
    inc a
    sta MZ_I
    cmp #28
    bne @border_v
    ; interior wall A: vertical, col 12, rows 1..13 (gap below)
    lda #1
    sta MZ_I
@wall_a:
    mset #1, #12, MZ_I, #2
    lda MZ_I
    inc a
    sta MZ_I
    cmp #14
    bne @wall_a
    ; interior wall B: horizontal, row 18, cols 18..30 (gap left)
    lda #18
    sta MZ_I
@wall_b:
    mset #1, MZ_I, #18, #2
    lda MZ_I
    inc a
    sta MZ_I
    cmp #31
    bne @wall_b

    ; player starts in the open left chamber
    lda #40
    sta PX
    lda #100
    sta PY

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMITIMEN: enable NMI (VBlank IRQ) + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: per-axis move-check (tentative move, keep only if the
;             map is clear), then draw the sprite. Once-per-frame.
; =============================================================================
game_loop:
    sf_frame_begin

    ; --- X axis: tentative move, keep only if clear ---
    rep #$20
    .a16
    lda PX
    sta NEWX
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda NEWX
    clc
    adc #SPEED
    sta NEWX
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda NEWX
    sec
    sbc #SPEED
    sta NEWX
@no_left:
    sf_solid_box NEWX, PY       ; test the X move against the map
    bne @x_blocked
    lda NEWX
    sta PX
@x_blocked:
    .a16

    ; --- Y axis: same, against the (possibly updated) X ---
    lda PY
    sta NEWY
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda NEWY
    clc
    adc #SPEED
    sta NEWY
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda NEWY
    sec
    sbc #SPEED
    sta NEWY
@no_up:
    sf_solid_box PX, NEWY       ; test the Y move against the map
    bne @y_blocked
    lda NEWY
    sta PY
@y_blocked:
    .a16

    spr_clear
    spr #1, PX, PY, #$00, #2
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the wall + sprite tile art (SNES 4bpp planar) and the engine includes.
; =============================================================================
; solid 8x8 4bpp tiles (all colour index 1)
wall_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
