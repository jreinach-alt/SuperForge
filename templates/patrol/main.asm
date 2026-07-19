; =============================================================================
; patrol — dodge patrolling enemies (enemy patrol + the full kit)
; =============================================================================
; Two magenta enemies pace their beats — one on the ground between two low
; walls, one on a floating platform turning at its ledges — while a red
; player runs and jumps through. Touching an enemy knocks the player back to
; the spawn and ticks the "HITS 00000" counter; getting past them is the
; game. Composes every kit surface: sprites, BG terrain, text HUD, tile
; collision, jump physics, and patrol.
;
; Controls:
;   D-pad left/right   run          A   jump (dodge the two patrolling enemies)
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: uploads, PPU, build the level, HUD, spawn actors, boot
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the HITS string, terrain + sprite tile art, engine includes
; game_loop is the frame heartbeat; start reading there.
;
; Level (32x28 tiles):
;   ground row 26 (full width); side borders cols 0/31 rows 0..25
;   low walls cols 10 + 20, rows 24..25 (16px — jumpable; the ground
;     enemy patrols between them: bounds ex 88..152)
;   platform row 20, cols 4..8 (px 32..71, top 160; the ledge enemy
;     patrols it: bounds ex 32..64)
;   player spawns at (200, 200) — right zone, outside both beats
;
; State (DP): player $32-$3E (pos/physics, as jumper) + enemy 1 $40/$42 +
;             enemy 2 $44/$46 + patrol scratch $48-$4C (shared) + map $4E +
;             hits $50.  Debug mirrors: $7E:E010 = hits.
;
; Done-condition (emulator-verifiable):
;   - boots; terrain + red player + 2 magenta enemies rendered; HITS 00000
;   - both enemies bounce inside their EXACT bounds forever
;   - walking into an enemy's beat -> contact -> respawn at (200,200), HITS
;     ticks (text), and the player can keep playing
;   - standing outside the beats -> no hits
;
; Build:  make patrol      (-> build/patrol.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "NIGHT PATROL"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags
.include "sf_physics.inc"       ; sf_jump, sf_physics_step
.include "sf_enemy.inc"         ; sf_patrol_step
.include "sf_collision.inc"     ; col_box (player-enemy contact)
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED   = $001F               ; player colour (15-bit BGR: red)
OBJ_MAGEN = $7C1F               ; enemies (OBJ palette 1)
BG_GREY   = $39CE               ; terrain colour (15-bit BGR: grey)
SPAWN_X   = 200                 ; player spawn / knockback X
SPAWN_Y   = 200                 ; player spawn / knockback Y

PX       = $32                  ; --- player (same layout as jumper) ---
PYF      = $34
VY       = $36
NEWY     = $38
GROUNDED = $3A
PYI      = $3C
NEWX     = $3E
E1X      = $40                  ; --- enemy 1: ground beat (ey #200) ---
E1DIR    = $42
E2X      = $44                  ; --- enemy 2: platform beat (ey #152) ---
E2DIR    = $46
PNEWX    = $48                  ; patrol scratch (shared between enemies)
PLEADX   = $4A
PFOOTY   = $4C
MP_I     = $4E                  ; map-fill loop counter
HITS     = $50                  ; knockback counter (HUD)
SPEED    = 2                    ; horizontal run step, px/frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, level, actors)
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
    sf_bg_color 0, 1, BG_GREY
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED
    sf_obj_color 1, 1, OBJ_MAGEN

    jsr init_ppu
    gfxmode #1

    ; --- terrain: tile 2 solid ---
    sf_tile_flags 2, SF_FLAG_SOLID
    rep #$30
    .a16                        ; first width switch: 16-bit A/X/Y. .a16/.i16 tell
    .i16                        ;   ca65 the CPU width so it sizes operands right
    stz MP_I
@ground:
    mset #1, MP_I, #26, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #32
    bne @ground
    stz MP_I
@border:
    mset #1, #0,  MP_I, #2
    mset #1, #31, MP_I, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #26
    bne @border
    lda #24
    sta MP_I
@lowwalls:                      ; cols 10 + 20, rows 24..25 (jumpable)
    mset #1, #10, MP_I, #2
    mset #1, #20, MP_I, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #26
    bne @lowwalls
    lda #4
    sta MP_I
@plat:                          ; row 20, cols 4..8
    mset #1, MP_I, #20, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #9
    bne @plat

    ; --- HUD + actors ---
    print str_hits, #8, #8
    sf_print_u16 HITS, #48, #8

    lda #SPAWN_X
    sta PX
    lda #SPAWN_Y * 256
    sta PYF
    stz VY
    stz GROUNDED
    stz HITS
    lda #120                    ; ground enemy starts mid-beat
    sta E1X
    lda #1
    sta E1DIR
    lda #48                     ; platform enemy starts mid-platform
    sta E2X
    lda #1
    sta E2DIR

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
; MAIN LOOP — game_loop: player move + jump, one patrol step per enemy, contact
;             check (knockback + HITS), then draw all three actors. Per-frame.
; =============================================================================
game_loop:
    sf_frame_begin

    ; --- player horizontal (per-axis move-check, as jumper) ---
    rep #$20
    .a16
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
    sf_solid_box NEWX, PYI
    bne x_blocked
    lda NEWX
    sta PX
x_blocked:
    .a16

    ; --- jump on a fresh A press ---
    btnp #BTN_A
    beq no_jump
    sf_jump VY, GROUNDED
no_jump:
    .a16

    ; --- player vertical ---
    sf_physics_step PYF, VY, PX, NEWY, GROUNDED

    rep #$20
    .a16
    lda PYF
    xba
    and #$00FF
    sta PYI

    ; --- enemies: one patrol step each (ey passed immediate — read-only) ---
    sf_patrol_step E1X, #200, E1DIR, PNEWX, PLEADX, PFOOTY
    sf_patrol_step E2X, #152, E2DIR, PNEWX, PLEADX, PFOOTY

    ; --- contact: either enemy overlapping the player -> knockback ---
    col_box PX, PYI, #8, #8,  E1X, #200, #8, #8
    beq chk_e2                  ; trampoline: the 2nd col_box expansion is
    jmp hit                     ; >127 bytes (see lib/macros/README.md)
chk_e2:
    .a16
    col_box PX, PYI, #8, #8,  E2X, #152, #8, #8
    bne hit                     ; hit block starts right below
    jmp no_hit
hit:
    .a16
    lda #SPAWN_X                ; knockback: respawn + count the hit
    sta PX
    lda #SPAWN_Y * 256
    sta PYF
    stz VY
    stz GROUNDED
    lda HITS
    inc a
    sta HITS
    ldx #$0000
    sta f:$7E0000 + $E010, x    ; debug mirror
    sf_print_u16 HITS, #48, #8  ; reprint the counter (NMI commits it)
    lda PYF
    xba
    and #$00FF
    sta PYI
no_hit:
    .a16

    spr_clear
    spr #1, PX, PYI, #$00, #2   ; player (slot 0)
    spr #1, E1X, #200, #$02, #2 ; ground enemy (slot 1, OBJ palette 1)
    spr #1, E2X, #152, #$02, #2 ; platform enemy (slot 2)
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the HITS label string, terrain + sprite tile art, and engine includes.
; =============================================================================
str_hits:
    .byte "HITS", 0

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
.include "text_engine.asm"
.include "sf_text_data.inc"
