; =============================================================================
; level_tail_test — run-gate for the S3 sf_level extensions, ON THE SEAM
; =============================================================================
; A 512x224 level world where every new surface crosses the x=256 page seam
; (the exact gap these extensions close):
;   - a ONE-WAY platform (tile 3, $02) on row 20, cols 28-36 (x 224-295):
;     jump through from below, land ON it, stand across the seam, walk off
;   - a PATROL enemy on a raised solid ledge (row 16, cols 26-38, x 208-311):
;     sf_level_patrol_step walks it across the seam and ledge-turns at both
;     ends without overhanging
;   - solid ground (tile 1) on row 24 with a PIT at cols 40-47 (x 320-383):
;     sf_pit + respawn, level-world edition
; Player: d-pad walk (clamped), A jump with sf_jump_cut, level integrator,
; camera follow.
;
; Debug mirrors:
;   $7E:E010 player world x     $7E:E012 player pixel y
;   $7E:E014 grounded           $7E:E016 deaths
;   $7E:E018 enemy world x      $7E:E01A enemy dir
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"
.include "sf_level.inc"         ; level world + integrator + seam patrol
.include "sf_frame.inc"
.include "engine_state.inc"

BG_GREY  = $39CE
BG_GREEN = $03E0
BG_GOLD  = $035F
OBJ_RED  = $001F
OBJ_BLUE = $7C00

SPAWN_X  = 16
SPAWN_Y  = 184                  ; ground row 24: top 192, box rest 184

PX       = $32                  ; player
PYF      = $34
VY       = $36
NEWY     = $38
GROUNDED = $3A
CORNX    = $3C                  ; level prober scratch
CORNY    = $3E
LVAR     = $40
EX       = $42                  ; patrol enemy
EY       = $44
EDIR     = $46
ENEWX    = $48                  ; patrol scratch
ELEADX   = $4A
EFOOTY   = $4C
ELVAR    = $4E
DEATHS   = $50
CAMX     = $52
CAMY     = $54
TXV      = $56                  ; level-load scratch
TYV      = $58
TILEV    = $5A

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_bg_tile 1, solid_tile
    sf_load_bg_tile 2, solid_tile   ; ledge uses the same look, palette 1
    sf_load_bg_tile 3, plat_tile
    sf_bg_color 0, 1, BG_GREY
    sf_bg_color 1, 1, BG_GOLD
    sf_bg_color 2, 1, BG_GREEN
    sf_load_obj_tile 1, actor_tile
    sf_obj_color 0, 1, OBJ_RED
    sf_obj_color 1, 1, OBJ_BLUE

    jsr init_ppu
    gfxmode #1
    sf_level_init
    sf_tile_flags 1, SF_FLAG_SOLID
    sf_tile_flags 2, SF_FLAG_SOLID
    sf_tile_flags 3, SF_FLAG_PLATFORM
    sf_level_load level_map, TXV, TYV, TILEV

    rep #$30
    .a16
    .i16
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
    stz DEATHS
    lda #240                    ; enemy starts left of the seam, on the ledge
    sta EX
    lda #120                    ; ledge row 16: top 128, box rest 120
    sta EY
    lda #1
    sta EDIR
    stz CAMX
    stz CAMY

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

    ; --- walk (clamped to the 512 world; walls not under test here) ---
    btn #BTN_RIGHT
    beq lt_no_right
    rep #$20
    .a16
    lda PX
    inc a
    inc a
    cmp #496
    bcs lt_no_right
    sta PX
lt_no_right:
    .a16
    btn #BTN_LEFT
    beq lt_no_left
    rep #$20
    .a16
    lda PX
    dec a
    dec a
    cmp #8
    bcc lt_no_left
    sta PX
lt_no_left:
    .a16

    ; --- jump + variable-height cut ---
    btnp #BTN_A
    beq lt_no_jump
    sf_jump VY, GROUNDED
lt_no_jump:
    .a16
    btn #BTN_A
    bne lt_a_held
    sf_jump_cut VY
lt_a_held:
    .a16

    sf_level_physics_step PYF, VY, PX, NEWY, GROUNDED, CORNX, CORNY, LVAR

    ; --- pit: past the death line -> respawn + count ---
    sf_pit PYF, #216
    beq lt_no_pit
    lda DEATHS
    inc a
    sta DEATHS
    lda #SPAWN_X
    sta PX
    lda #(SPAWN_Y << 8) & $FFFF
    sta PYF
    stz VY
    stz GROUNDED
lt_no_pit:
    .a16

    ; --- the seam-aware patrol ---
    sf_level_patrol_step EX, EY, EDIR, ENEWX, ELEADX, EFOOTY, ELVAR

    ; --- camera + mirrors ---
    lda PYF
    xba
    and #$00FF
    sta TILEV                   ; player pixel y (TILEV is init-only scratch)
    sf_camera_follow PX, TILEV, 512, 224, CAMX, CAMY
    scroll #1, CAMX, CAMY

    ldx #$0000
    lda PX
    sta f:$7E0000 + $E010, x
    lda PYF
    xba
    and #$00FF
    sta f:$7E0000 + $E012, x
    lda GROUNDED
    sta f:$7E0000 + $E014, x
    lda DEATHS
    sta f:$7E0000 + $E016, x
    lda EX
    sta f:$7E0000 + $E018, x
    lda EDIR
    sta f:$7E0000 + $E01A, x

    ; --- draw (screen = world - camera) ---
    spr_clear
    lda PX
    sec
    sbc CAMX
    sta CORNX                   ; reuse as draw scratch post-physics
    lda PYF
    xba
    and #$00FF
    sta CORNY
    spr #1, CORNX, CORNY, #$00, #2
    lda EX
    sec
    sbc CAMX
    sta CORNX
    lda EY
    sta CORNY
    spr #1, CORNX, CORNY, #$02, #2
    sf_frame_end
    sf_debug_complete
    jmp game_loop

; --- the level: 28 rows x 64 tile IDs ---
level_map:
    ; rows 0-15: sky
    .repeat 16 * 64
    .byte 0
    .endrepeat
    ; row 16: the patrol ledge, cols 26-38 (world x 208-311, crosses the seam)
    .repeat 26
    .byte 0
    .endrepeat
    .repeat 13
    .byte 2
    .endrepeat
    .repeat 25
    .byte 0
    .endrepeat
    ; rows 17-19: sky
    .repeat 3 * 64
    .byte 0
    .endrepeat
    ; row 20: the one-way platform, cols 28-36 (world x 224-295, crosses the seam)
    .repeat 28
    .byte 0
    .endrepeat
    .repeat 9
    .byte 3
    .endrepeat
    .repeat 27
    .byte 0
    .endrepeat
    ; rows 21-23: sky
    .repeat 3 * 64
    .byte 0
    .endrepeat
    ; row 24: ground with the pit at cols 40-47 (world x 320-383)
    .repeat 40
    .byte 1
    .endrepeat
    .repeat 8
    .byte 0
    .endrepeat
    .repeat 16
    .byte 1
    .endrepeat
    ; rows 25-27: underground fill below the ground (pit stays open)
    .repeat 3
    .repeat 40
    .byte 1
    .endrepeat
    .repeat 8
    .byte 0
    .endrepeat
    .repeat 16
    .byte 1
    .endrepeat
    .endrepeat
.assert * - level_map = 28 * 64, error, "level must be 28x64"

; solid 8x8 tile / platform ledge tile / actor tile
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
actor_tile:
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
