; =============================================================================
; jumper — run and jump across platforms (jump physics)
; =============================================================================
; A red player with gravity: run left/right with the d-pad, jump with A.
; Solid ground along the bottom, three floating platforms at rising heights
; (each reachable from the one below), and a low overhang to bonk your head
; on. The vertical axis belongs entirely to sf_physics_step (take-off,
; ascent, head bump, apex, descent, landing snap, rest); the horizontal axis
; is the maze template's per-axis move-check. Adapt it: retune the feel by
; defining SF_GRAVITY / SF_JUMP_VEL / SF_MAX_FALL before the include;
; bigger jumps need flatter gravity.
;
; Controls:
;   D-pad left/right   run          A   jump (from the ground or a platform)
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: tile + palette uploads, PPU, build the terrain, boot
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the terrain + sprite tile art, engine includes
; game_loop is the frame heartbeat; start reading there.
;
; State (DP): px $32, pyf $34 (8.8), vy $36, newy scratch $38, grounded $3A,
;             pyi $3C (draw-pixel mirror), newx $3E, map-fill $46-$47.
;
; Done-condition (emulator-verifiable):
;   - boots; grey terrain + red player standing on the ground (rest y stable)
;   - jump rises ~38px and lands back at EXACTLY the rest y (full cycle)
;   - jumping from below onto a platform lands ON it (rest = platform top - 8)
;   - walking off a platform edge falls (clamped) and lands below
;   - the overhang bonks: y never passes into it, ascent dies early
;
; Build:  make jumper      (-> build/jumper.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SKY HOPPER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags, sf_solid_box
.include "sf_physics.inc"       ; sf_jump, sf_physics_step
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED  = $001F                ; player colour (15-bit BGR: red)
BG_GREY  = $39CE                ; terrain colour (15-bit BGR: grey)
PX       = $32                  ; player x (pixels)
PYF      = $34                  ; player y, 8.8 fixed (physics owns this)
VY       = $36                  ; vertical velocity, signed 8.8
NEWY     = $38                  ; physics scratch
GROUNDED = $3A                  ; 1 = standing (physics owns this)
PYI      = $3C                  ; draw-pixel mirror of PYF's high byte
NEWX     = $3E                  ; horizontal move-check scratch
MJ_I     = $46                  ; map-fill loop counter
SPEED    = 2                    ; horizontal run step, px/frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, terrain, boot)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_bg_tile 2, terrain_tile
    sf_bg_color 0, 1, BG_GREY
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED

    jsr init_ppu
    gfxmode #1                  ; zeros shadow tilemaps + sets 32x32 dims

    ; --- terrain: tile 2 solid ---
    sf_tile_flags 2, SF_FLAG_SOLID
    rep #$30
    .a16                        ; first width switch: 16-bit A/X/Y. .a16/.i16 tell
    .i16                        ;   ca65 the CPU width so it sizes operands right
    stz MJ_I
@ground:                        ; ground: row 26, full width (top px 208)
    mset #1, MJ_I, #26, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #32
    bne @ground
    lda #8
    sta MJ_I
@plat1:                         ; platform 1: row 22, cols 8..12 (top 176)
    mset #1, MJ_I, #22, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #13
    bne @plat1
    lda #15
    sta MJ_I
@plat2:                         ; platform 2: row 18, cols 15..19 (top 144)
    mset #1, MJ_I, #18, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #20
    bne @plat2
    lda #22
    sta MJ_I
@plat3:                         ; platform 3: row 14, cols 22..26 (top 112)
    mset #1, MJ_I, #14, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #27
    bne @plat3
    lda #28
    sta MJ_I
@overhang:                      ; overhang: row 22, cols 28..30 (bottom 183) —
    mset #1, MJ_I, #22, #2      ; clear of plat1's takeoff window (a jump
    lda MJ_I                    ; arc rising under a lip bonks; level design
    inc a                       ; must leave the approach open)
    sta MJ_I
    cmp #31
    bne @overhang
    stz MJ_I
@border:                        ; side borders: cols 0 and 31, rows 0..25
    mset #1, #0,  MJ_I, #2
    mset #1, #31, MJ_I, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #26
    bne @border

    ; --- player spawns standing on the ground, mid-left ---
    lda #48
    sta PX
    lda #200 * 256              ; rest on the ground row
    sta PYF
    stz VY
    stz GROUNDED

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
; MAIN LOOP — game_loop: horizontal move-check, jump on a fresh A press, then
;             sf_physics_step owns the vertical axis. Once-per-frame.
; =============================================================================
game_loop:
    sf_frame_begin

    ; --- horizontal: tentative move at the CURRENT pixel y, revert if solid ---
    rep #$20
    .a16
    lda PYF
    xba
    and #$00FF
    sta PYI                     ; pixel y for probes + drawing
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
    sf_solid_box NEWX, PYI
    bne @x_blocked
    lda NEWX
    sta PX
@x_blocked:
    .a16

    ; --- jump on a fresh A press (grounded-gated inside the macro) ---
    btnp #BTN_A
    beq no_jump                 ; named label: sf_jump's .local ends @-scope
    sf_jump VY, GROUNDED
no_jump:
    .a16

    ; --- vertical: the physics step owns everything else ---
    sf_physics_step PYF, VY, PX, NEWY, GROUNDED

    rep #$20
    .a16
    lda PYF
    xba
    and #$00FF
    sta PYI

    spr_clear
    spr #1, PX, PYI, #$00, #2
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the terrain + sprite tile art (SNES 4bpp planar) and engine includes.
; =============================================================================
; solid 8x8 4bpp tiles (all colour index 1)
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

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
