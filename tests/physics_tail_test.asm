; =============================================================================
; physics_tail_test — run-gate for variable jump + one-way platforms + pits
; =============================================================================
; One world exercising all three S2 physics-tail features:
;   - solid ground (tile 1, $01) on row 24, cols 0-19 — cols 20+ are a PIT
;   - a one-way platform (tile 2, $02 — green) on row 20, cols 8-12:
;     reachable by a FULL jump from the ground (apex ~146 < platform rest
;     152), passed through from below, stood on, walked off
;   - sf_jump_cut wired to "A not held" — tap = short hop, hold = full arc
;   - sf_pit #216 -> respawn at the start + a death counter
;
; Debug mirrors:
;   $7E:E010  apex of the LAST completed jump (min pixel y while airborne)
;   $7E:E012  current pixel y       $7E:E014  grounded
;   $7E:E016  deaths (pit falls)    $7E:E018  player x
;
; Done-condition (emulator-verifiable): see tests/test_physics_tail.py —
; tap apex is measurably lower than held apex; a full jump from under the
; platform lands ON it at pixel 152; walking off its edge falls back to
; 184; walking right past col 20 falls into the pit, trips the death plane,
; respawns at the start with deaths+1.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_video.inc"         ; sf_load_obj_tile, sf_obj_color
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp
.include "sf_map.inc"           ; sf_tile_flags (+ SF_FLAG_*)
.include "sf_physics.inc"       ; sf_physics_step, sf_jump, sf_jump_cut, sf_pit
.include "sf_frame.inc"
.include "engine_state.inc"

BG_GREY  = $39CE
BG_GREEN = $03E0
OBJ_RED  = $001F

SPAWN_X  = 16
SPAWN_Y  = 184                  ; rest pixel on the ground (row 24 top - 8)

PX       = $32                  ; player x (pixels)
PYF      = $34                  ; player y, 8.8 (physics owns)
VY       = $36                  ; signed 8.8 velocity
NEWY     = $38                  ; physics scratch
GROUNDED = $3A
MINY     = $3C                  ; min pixel y since takeoff (apex tracker)
AIRBORNE = $3E                  ; 1 = has been airborne since last apex report
DEATHS   = $40
MAPI     = $42                  ; map-build loop counter
PIXY     = $44                  ; current pixel y (drawn)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_bg_tile 1, solid_tile
    sf_load_bg_tile 2, plat_tile
    sf_bg_color 0, 1, BG_GREY
    sf_bg_color 1, 1, BG_GREEN
    sf_load_obj_tile 1, player_tile
    sf_obj_color 0, 1, OBJ_RED

    jsr init_ppu
    gfxmode #1

    ; --- ground: row 24, cols 0-19 (cols 20-31 = the pit) ---
    rep #$30
    .a16
    .i16
    stz MAPI
@ground:
    mset #1, MAPI, #24, #1
    lda MAPI
    inc a
    sta MAPI
    cmp #20
    bne @ground
    ; --- one-way platform: row 20, cols 8-12 (palette 1 = green) ---
    lda #8
    sta MAPI
@plat:
    mset #1, MAPI, #20, #(2 | (1 << 10))
    lda MAPI
    inc a
    sta MAPI
    cmp #13
    bne @plat

    sf_tile_flags 1, SF_FLAG_SOLID
    sf_tile_flags 2, SF_FLAG_PLATFORM

    ; --- player state ---
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
    lda #$00FF
    sta MINY
    stz AIRBORNE
    stz DEATHS

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- walk (no walls in this arena; clamp to the playfield) ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PX
    inc a
    inc a
    cmp #240
    bcs @no_right
    sta PX
@no_right:
    .a16
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PX
    dec a
    dec a
    cmp #8                      ; safe: PX >= 8, step 2
    bcc @no_left
    sta PX
@no_left:
    .a16

    ; --- jump on press; cut the arc while A is up ---
    btnp #BTN_A
    beq pt_no_jump
    sf_jump VY, GROUNDED
pt_no_jump:
    .a16
    btn #BTN_A
    bne pt_a_held
    sf_jump_cut VY
pt_a_held:
    .a16

    sf_physics_step PYF, VY, PX, NEWY, GROUNDED

    ; --- apex tracking (min pixel while airborne; report on landing) ---
    lda PYF
    xba
    and #$00FF
    sta PIXY
    lda GROUNDED
    bne @landed
    lda #$0001
    sta AIRBORNE
    lda PIXY
    cmp MINY
    bcs @apex_done
    sta MINY
    bra @apex_done
@landed:
    .a16
    lda AIRBORNE
    beq @apex_done
    stz AIRBORNE
    lda MINY
    ldx #$0000
    sta f:$7E0000 + $E010, x    ; the completed jump's apex
    lda #$00FF
    sta MINY
@apex_done:
    .a16

    ; --- pit: past the death line -> respawn + count it ---
    sf_pit PYF, #216
    beq pt_no_pit
    lda DEATHS
    inc a
    sta DEATHS
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
    lda #$00FF
    sta MINY
    stz AIRBORNE
pt_no_pit:
    .a16

    ; --- mirrors ---
    ldx #$0000
    lda PIXY
    sta f:$7E0000 + $E012, x
    lda GROUNDED
    sta f:$7E0000 + $E014, x
    lda DEATHS
    sta f:$7E0000 + $E016, x
    lda PX
    sta f:$7E0000 + $E018, x

    spr_clear
    spr #1, PX, PIXY, #$00, #2
    sf_frame_end
    sf_debug_complete
    jmp game_loop

; solid 8x8 tile (color index 1) / platform tile (top half only, "ledge" look)
solid_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
plat_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
player_tile:
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
