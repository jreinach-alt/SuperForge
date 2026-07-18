; =============================================================================
; level_test — run-gate for the scrolling-level macros (sf_level.inc)
; =============================================================================
; A 512px-wide ROM level loaded across both hardware pages, then: point
; probes on each page, a box straddling the page seam (world x=256), a
; scripted physics drop that LANDS on the seam platform, and a rendered
; scroll check (camera at 172 -> right-half content visible on screen).
;
; Test level (64x28 tile IDs; tile 2 = solid):
;   borders col 0 + 63 (rows 0..25); floor rows 26..27 (full width)
;   seam platform row 22, world cols 29..35 (px 232..287 x 176..183)
;   right-half wall col 40 (px 320..327), rows 20..25
;
; Debug map ($7E:E000):
;   +$10  point (236,180): platform, left page          -> 1
;   +$12  point (280,180): platform, RIGHT page         -> 1
;   +$14  point (288,180): air past the platform        -> 0
;   +$16  point (324,164): wall, right page             -> 1
;   +$18  box (252,170): corners straddle BOTH pages    -> 1
;   +$1A  box (252,158): same x, above the platform     -> 0
;   +$20..$47  physics drop at px=252 from y=140 (40 steps, y per step):
;              must land at 168 (seam platform top - 8) and stay flat
;   +$48  grounded after the drop                       -> 1
;   +$50  cam_x after sf_camera_follow(pwx=300)         -> 172
;
; Then NMI on + frame loop (camera held at 172) for the pytest's rendered
; checks: the col-40 wall (world px 320..327) at screen x ~148..155, floor
; across the full width, no BG2-layer double image.
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags
.include "sf_level.inc"         ; the surface under test
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

PX       = $32
PYF      = $34
VY       = $36
NEWY     = $38
GROUNDED = $3A
CORNX    = $3C                  ; level-prober scratch
CORNY    = $3E
LVAR     = $40
TXV      = $42                  ; level-loader scratch
TYV      = $44
TILEV    = $46
TRACEPTR = $48
PWX      = $4A                  ; camera target
CAM_X    = $4C
CAM_Y    = $4E

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_bg_tile 2, terrain_tile
    sf_bg_color 0, 1, $39CE     ; grey

    jsr init_ppu
    gfxmode #1                  ; 32x32 regs + shadows zeroed + dims
    sf_level_init               ; BG1 -> 64x32; BG2 layer off the screen

    sf_tile_flags 2, SF_FLAG_SOLID
    sf_level_load test_level, TXV, TYV, TILEV

    ; --- point probes (record A after each) ---
    rep #$30
    .a16
    .i16
    ldx #$0000
    lda #236
    sta CORNX
    sf_level_point CORNX, #180, LVAR
    ldx #$0000
    sta f:$7E0000 + $E010, x

    lda #280
    sta CORNX
    sf_level_point CORNX, #180, LVAR
    ldx #$0000
    sta f:$7E0000 + $E012, x

    lda #288
    sta CORNX
    sf_level_point CORNX, #180, LVAR
    ldx #$0000
    sta f:$7E0000 + $E014, x

    lda #324
    sta CORNX
    sf_level_point CORNX, #164, LVAR
    ldx #$0000
    sta f:$7E0000 + $E016, x

    ; --- seam-straddling box probes ---
    lda #252
    sta PX
    lda #170
    sta NEWY
    sf_level_solid_box PX, NEWY, CORNX, CORNY, LVAR
    ldx #$0000
    sta f:$7E0000 + $E018, x

    lda #158
    sta NEWY
    sf_level_solid_box PX, NEWY, CORNX, CORNY, LVAR
    ldx #$0000
    sta f:$7E0000 + $E01A, x

    ; --- physics drop onto the seam platform (40 recorded steps) ---
    lda #252
    sta PX
    lda #140 * 256
    sta PYF
    stz VY
    stz GROUNDED
    lda #$E020
    sta TRACEPTR
    jsr run_trace

    ldx #$0000
    lda GROUNDED
    sta f:$7E0000 + $E048, x

    ; --- camera over the seam ---
    lda #300
    sta PWX
    stz CAM_Y
    sf_camera_follow PWX, #112, 512, 224, CAM_X, CAM_Y
    rep #$30
    .a16
    ldx #$0000
    lda CAM_X
    sta f:$7E0000 + $E050, x

    sf_debug_magic
    sf_debug_complete

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad on
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin
    sf_camera_follow PWX, #112, 512, 224, CAM_X, CAM_Y
    sf_frame_end
    jmp game_loop

; -----------------------------------------------------------------------------
; run_trace — 40 level-physics steps, storing pixel y per step at [TRACEPTR++].
; WIDTH-RISK: asserts A16/I16; exits A16/I16.
run_trace:
    rep #$30
    .a16
    .i16
    ldy #40
rt_loop:
    phy
    sf_level_physics_step PYF, VY, PX, NEWY, GROUNDED, CORNX, CORNY, LVAR
    rep #$30
    .a16
    .i16
    lda PYF
    xba
    and #$00FF
    ldx TRACEPTR
    sep #$20
    .a8
    sta f:$7E0000, x
    rep #$20
    .a16
    inc TRACEPTR
    ply
    dey
    beq rt_done                 ; trampoline (loop body >127 bytes)
    jmp rt_loop
rt_done:
    rts

; --- the test level: 64x28 tile IDs ---
test_level:
.repeat 20                      ; rows 0..19: bare border rows
    .byte 2
    .repeat 62
        .byte 0
    .endrepeat
    .byte 2
.endrepeat
.repeat 2                       ; rows 20..21: border + wall col 40
    .byte 2
    .repeat 39
        .byte 0
    .endrepeat
    .byte 2
    .repeat 22
        .byte 0
    .endrepeat
    .byte 2
.endrepeat
; row 22: border + seam platform cols 29..35 + wall col 40
    .byte 2
    .repeat 28
        .byte 0
    .endrepeat
    .repeat 7
        .byte 2
    .endrepeat
    .repeat 4
        .byte 0
    .endrepeat
    .byte 2
    .repeat 22
        .byte 0
    .endrepeat
    .byte 2
.repeat 3                       ; rows 23..25: border + wall col 40
    .byte 2
    .repeat 39
        .byte 0
    .endrepeat
    .byte 2
    .repeat 22
        .byte 0
    .endrepeat
    .byte 2
.endrepeat
.repeat 2                       ; rows 26..27: solid floor
    .repeat 64
        .byte 2
    .endrepeat
.endrepeat

.assert * - test_level = 28 * 64, error, "level must be exactly 28 rows x 64 bytes"

; solid 8x8 4bpp tile (colour index 1)
terrain_tile:
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
