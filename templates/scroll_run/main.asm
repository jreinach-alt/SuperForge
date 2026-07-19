; =============================================================================
; scroll_run — run right across a two-screen level (scrolling levels)
; =============================================================================
; A 512px-wide level: run and jump from the left edge to the gold goal
; pillar at the far right, over raised platforms and solid pillars, with the
; camera following (clamped at both world edges). Reaching the goal prints
; GOAL and freezes input. Composes the whole kit: ROM level + seam-aware
; collision/physics (sf_level), camera (sf_camera), text (sf_text), sprites
; and input. Vertical stays one screen (the 8.8 physics range); X is the
; full 0..511 world.
;
; Controls:
;   D-pad left/right   run          A   jump (fixed height)
;   (reaching the goal prints GOAL and freezes input)
;
; The level (see `level` below, 64x28): floor rows 26..27; border cols 0/63;
; pillars at world cols 14 (rows 22..25) and 44 (rows 20..25); platforms at
; rows 22 cols 24..27, row 20 cols 30..34 (crosses the page seam at col 32!),
; row 22 cols 38..41; goal tile 3 at col 60 rows 24..25.
;
; State (DP): player $32-$3E (as jumper) + level scratch $40-$44 (cornx/
;             corny/lvar) + loader scratch $46-$4A + cam $4C/$4E + state $50.
; Debug mirrors: $7E:E010 = state (0 play / 1 won).
;
; Done-condition (emulator-verifiable):
;   - boots; camera clamped at 0 (left edge); player at rest on the floor
;   - running right scrolls the camera once past screen-center, revealing
;     right-page content; camera clamps at 256 at the right edge
;   - the seam platform (cols 30..34) is land-on-able; pillars block
;   - touching the goal pillar (world x ~480..487) -> GOAL text + freeze
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: uploads, PPU, tile flags, load the level, spawn player
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the GOAL string, the level map, tile art, then engine includes
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Build:  make scroll_run      (-> build/scroll_run.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "GOLD SPRINT"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags
.include "sf_level.inc"         ; level init/load/collision/physics
.include "sf_camera.inc"        ; sf_camera_follow, sf_clamp0
.include "sf_physics.inc"       ; sf_jump (+ tunables)
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_text.inc"          ; sf_text_init, print
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED  = $001F                ; player sprite colour (15-bit BGR)
BG_GREY  = $39CE                ; terrain colour (15-bit BGR)
BG_GOLD  = $035F                ; goal pillar colour (15-bit BGR)
WORLD_W  = 512                  ; level width in pixels (two 256px pages)

PX       = $32                  ; player world x (0..511)
PYF      = $34                  ; player y, 8.8 fixed-point
VY       = $36                  ; vertical velocity, 8.8 fixed-point
NEWY     = $38                  ; tentative y for the physics step
GROUNDED = $3A                  ; nonzero while the player rests on solid ground
PYI      = $3C                  ; player y in integer pixels (PYF high byte)
NEWX     = $3E                  ; tentative x before the solid-box check
CORNX    = $40                  ; level-prober scratch (probe cell x)
CORNY    = $42                  ; level-prober scratch (probe cell y)
LVAR     = $44                  ; level-prober scratch (page / variant)
TXV      = $46                  ; loader scratch: tile x
TYV      = $48                  ; loader scratch: tile y
TILEV    = $4A                  ; loader scratch: tile id
CAM_X    = $4C                  ; camera world x (follows player, edge-clamped)
CAM_Y    = $4E                  ; camera world y (stays 0; one screen tall)
STATE    = $50                  ; 0 play / 1 won
SCRX     = $52                  ; player screen x (world - cam)
SPEED    = 2                    ; run step in pixels per frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, load, spawn)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_text_init
    sf_load_bg_tile 2, terrain_tile
    sf_load_bg_tile 3, goal_tile   ; goal pillar: colour index 2 -> gold
    sf_bg_color 0, 1, BG_GREY
    sf_bg_color 0, 2, BG_GOLD
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED

    jsr init_ppu
    gfxmode #1
    sf_level_init

    sf_tile_flags 2, SF_FLAG_SOLID
    sf_tile_flags 3, $02        ; goal: its own (non-solid) flag bit
    sf_level_load level, TXV, TYV, TILEV

    ; --- player spawns at the left edge, on the floor ---
    ; (.a16/.i16 track the CPU's register width for ca65 — the 65816 switches
    ;  between 8- and 16-bit registers and the assembler must match the CPU so
    ;  immediates are sized right; the first of several width blocks here.)
    rep #$30                    ; go 16-bit: accumulator + index registers
    .a16
    .i16
    lda #16
    sta PX
    lda #200 * 256
    sta PYF
    stz VY
    stz GROUNDED
    stz STATE
    stz CAM_Y

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt + joypad enable): turn on
                                ;   the VBlank NMI (bit 7) and auto joypad read
                                ;   (bit 0) so the loop's btn/btnp reads have data
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — once per frame: run/jump, seam-aware collision, goal check, draw
; =============================================================================
game_loop:
    sf_frame_begin

    lda STATE
    beq playing
    jmp draw                    ; won: input frozen, camera holds

playing:
    .a16
    ; --- horizontal: tentative move, seam-aware solid check ---
    lda PYF
    xba
    and #$00FF
    sta PYI
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
    sf_clamp0 NEWX, (WORLD_W - 8)
    sf_level_solid_box NEWX, PYI, CORNX, CORNY, LVAR
    bne x_blocked
    lda NEWX
    sta PX
x_blocked:
    .a16

    btnp #BTN_A
    beq no_jump
    sf_jump VY, GROUNDED
no_jump:
    .a16

    sf_level_physics_step PYF, VY, PX, NEWY, GROUNDED, CORNX, CORNY, LVAR

    rep #$20
    .a16
    lda PYF
    xba
    and #$00FF
    sta PYI

    ; --- goal check: the flag-2 tile under the player's center point ---
    lda PX
    clc
    adc #4
    sta CORNX
    lda PYI
    clc
    adc #4
    sta CORNY
    lda CORNX                   ; page-split the point for col_map
    cmp #256
    bcc goal_left
    sec
    sbc #256
    sta CORNX
    lda #$0002
    sta LVAR
    bra goal_probe
goal_left:
    .a16
    lda #$0001
    sta LVAR
goal_probe:
    .a16
    col_map LVAR, CORNX, CORNY, #1
    beq draw
    lda #$0001                  ; reached the goal pillar
    sta STATE
    ldx #$0000
    sta f:$7E0000 + $E010, x
    print str_goal, #112, #96

draw:
    .a16
    ; --- camera + draw at the screen position ---
    sf_camera_follow PX, #112, WORLD_W, 224, CAM_X, CAM_Y
    rep #$20
    .a16
    lda PX
    sec
    sbc CAM_X
    sta SCRX
    spr_clear
    spr #1, SCRX, PYI, #$00, #2
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the GOAL string, the level map, the tile art, then the engine includes
; =============================================================================
str_goal:
    .byte "GOAL", 0

; --- the level: 64x28 tile IDs (2 = solid grey, 3 = gold goal) ---
level:
.repeat 19                      ; rows 0..18: bare borders
    .byte 2
    .repeat 62
        .byte 0
    .endrepeat
    .byte 2
.endrepeat
; row 19: border only (above the col-44 pillar top)
    .byte 2
    .repeat 62
        .byte 0
    .endrepeat
    .byte 2
; row 20: border + seam platform cols 30..34 + pillar col 44
    .byte 2
    .repeat 28
        .byte 0
    .endrepeat
    .byte 0                     ; col 29
    .repeat 5
        .byte 2                 ; cols 30..34 (crosses the seam at 32)
    .endrepeat
    .repeat 9
        .byte 0                 ; cols 35..43
    .endrepeat
    .byte 2                     ; col 44
    .repeat 18
        .byte 0                 ; cols 45..62
    .endrepeat
    .byte 2
; row 21: border + pillar col 44
    .byte 2
    .repeat 43
        .byte 0                 ; cols 1..43
    .endrepeat
    .byte 2
    .repeat 18
        .byte 0
    .endrepeat
    .byte 2
; row 22: border + pillar col 14 + platform cols 24..27 + plat cols 38..41 + pillar col 44
    .byte 2
    .repeat 13
        .byte 0                 ; cols 1..13
    .endrepeat
    .byte 2                     ; col 14
    .repeat 9
        .byte 0                 ; cols 15..23
    .endrepeat
    .repeat 4
        .byte 2                 ; cols 24..27
    .endrepeat
    .repeat 10
        .byte 0                 ; cols 28..37
    .endrepeat
    .repeat 4
        .byte 2                 ; cols 38..41
    .endrepeat
    .repeat 2
        .byte 0                 ; cols 42..43
    .endrepeat
    .byte 2                     ; col 44
    .repeat 18
        .byte 0
    .endrepeat
    .byte 2
; row 23: border + pillars cols 14, 44
    .byte 2
    .repeat 13
        .byte 0                 ; cols 1..13
    .endrepeat
    .byte 2                     ; col 14
    .repeat 29
        .byte 0                 ; cols 15..43
    .endrepeat
    .byte 2                     ; col 44
    .repeat 18
        .byte 0                 ; cols 45..62
    .endrepeat
    .byte 2
.repeat 2                       ; rows 24..25: border + pillars 14/44 + goal col 60
    .byte 2
    .repeat 13
        .byte 0                 ; cols 1..13
    .endrepeat
    .byte 2                     ; col 14
    .repeat 29
        .byte 0                 ; cols 15..43
    .endrepeat
    .byte 2                     ; col 44
    .repeat 15
        .byte 0                 ; cols 45..59
    .endrepeat
    .byte 3                     ; col 60: the goal
    .repeat 2
        .byte 0                 ; cols 61..62
    .endrepeat
    .byte 2
.endrepeat
.repeat 2                       ; rows 26..27: solid floor
    .repeat 64
        .byte 2
    .endrepeat
.endrepeat

.assert * - level = 28 * 64, error, "level must be exactly 28 rows x 64 bytes"

; solid 8x8 4bpp tiles (colour index 1)
terrain_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
goal_tile:                      ; colour index 2 (bitplane 1)
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
