; =============================================================================
; stomper — stomp the patrollers (stomp mechanics + the full kit)
; =============================================================================
; Two magenta enemies pace the same beats as the patrol template — but now
; you can fight back: land on one to defeat it (it vanishes, you bounce);
; touch it any other way and you're knocked back to spawn. The "FOES 00002"
; counter ticks down per stomp; defeat both and the screen says CLEAR.
;
; Controls:
;   D-pad left/right   move          A   jump (fixed height)
;   Defeat an enemy by landing on its head (a stomp); any other contact hurts.
;
; Level: as patrol — ground row 26, borders, low walls cols 10/20 rows
; 24..25 (ground beat ex 88..152, ey 200), platform row 20 cols 4..8
; (platform beat ex 32..64, ey 152). Spawn (200, 200).
;
; State (DP): player $32-$3E (as jumper) + enemy 1 $40/$42/$44 (x/dir/alive)
;             + enemy 2 $46/$48/$4A + patrol scratch $4C-$50 (shared) +
;             map $52 + foes $54 + hurts $56 (debug).
; Debug mirrors: $7E:E010 = foes alive, $7E:E012 = hurt count.
;
; Done-condition (emulator-verifiable):
;   - boots; both enemies pace their exact beats; FOES 00002
;   - landing on an enemy: it disappears (sprite culled, magenta drops),
;     the player BOUNCES (y dips then rises ~17px), FOES ticks down (text)
;   - side contact: knockback to spawn (enemy survives)
;   - both stomped -> "CLEAR" printed; the game keeps running
;
; File layout (top to bottom; the major === section banners):
;   INIT       — RESET: uploads, PPU, build the map, HUD, spawn player + enemies
;   MAIN LOOP  — game_loop, the once-per-frame heartbeat (read this first)
;   DATA       — the HUD strings, the tile art, then the engine includes
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Build:  make stomper      (-> build/stomper.sfc)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "STOMP SQUAD"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_map.inc"           ; sf_tile_flags
.include "sf_physics.inc"       ; sf_jump, sf_physics_step
.include "sf_enemy.inc"         ; sf_patrol_step, sf_stomp_check
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED   = $001F               ; player colour (15-bit BGR)
OBJ_MAGEN = $7C1F               ; enemy colour: magenta (15-bit BGR)
BG_GREY   = $39CE               ; terrain colour (15-bit BGR)
SPAWN_X   = 200                 ; player spawn / respawn x (pixels)
SPAWN_Y   = 200                 ; player spawn / respawn y (pixels)

PX       = $32                  ; player world x (uses the shared jumper state)
PYF      = $34                  ; player y, 8.8 fixed-point
VY       = $36                  ; vertical velocity, 8.8 fixed-point
NEWY     = $38                  ; tentative y for the physics step
GROUNDED = $3A                  ; nonzero while the player rests on solid ground
PYI      = $3C                  ; player y in integer pixels (PYF high byte)
NEWX     = $3E                  ; tentative x before the solid-box check
E1X      = $40                  ; enemy 1 x (ground beat, drawn at ey #200)
E1DIR    = $42                  ; enemy 1 heading (+1 right / -1 left)
E1ALIVE  = $44                  ; enemy 1 alive flag (0 once stomped)
E2X      = $46                  ; enemy 2 x (platform beat, drawn at ey #152)
E2DIR    = $48                  ; enemy 2 heading (+1 right / -1 left)
E2ALIVE  = $4A                  ; enemy 2 alive flag (0 once stomped)
PNEWX    = $4C                  ; patrol scratch (shared): tentative x
PLEADX   = $4E                  ; patrol scratch (shared): leading-edge x
PFOOTY   = $50                  ; patrol scratch (shared): foot-row y
MP_I     = $52                  ; map-build loop index (INIT only)
FOES     = $54                  ; enemies still alive (HUD, counts down)
HURTS    = $56                  ; times hurt (debug mirror only)
SPEED    = 2                    ; player move step in pixels per frame

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, map, spawn)
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

    sf_tile_flags 2, SF_FLAG_SOLID
    ; (.a16/.i16 track the CPU's register width for ca65 — the 65816 switches
    ;  between 8- and 16-bit registers and the assembler must match the CPU so
    ;  immediates are sized right; the first of several width blocks here.)
    rep #$30                    ; go 16-bit: accumulator + index registers
    .a16
    .i16
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
@lowwalls:
    mset #1, #10, MP_I, #2
    mset #1, #20, MP_I, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #26
    bne @lowwalls
    lda #4
    sta MP_I
@plat:
    mset #1, MP_I, #20, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #9
    bne @plat

    print str_foes, #8, #8
    lda #2
    sta FOES
    sf_print_u16 FOES, #48, #8
    stz HURTS

    lda #SPAWN_X
    sta PX
    lda #SPAWN_Y * 256
    sta PYF
    stz VY
    stz GROUNDED
    lda #120
    sta E1X
    lda #1
    sta E1DIR
    sta E1ALIVE
    lda #48
    sta E2X
    lda #1
    sta E2DIR
    sta E2ALIVE

    rep #$30
    .a16
    ldx #$0000
    lda FOES
    sta f:$7E0000 + $E010, x

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
; MAIN LOOP — once per frame: player physics, patrol, stomp/hurt, draw
; =============================================================================
game_loop:
    sf_frame_begin

    ; --- player horizontal ---
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

    btnp #BTN_A
    beq no_jump
    sf_jump VY, GROUNDED
no_jump:
    .a16

    sf_physics_step PYF, VY, PX, NEWY, GROUNDED

    rep #$20
    .a16
    lda PYF
    xba
    and #$00FF
    sta PYI

    ; --- enemies: patrol only while alive (trampolines over the macro
    ;     expansions; see lib/macros/README.md) ---
    lda E1ALIVE
    bne e1_alive
    jmp e1_done
e1_alive:
    .a16
    sf_patrol_step E1X, #200, E1DIR, PNEWX, PLEADX, PFOOTY
e1_done:
    .a16
    lda E2ALIVE
    bne e2_alive
    jmp e2_done
e2_alive:
    .a16
    sf_patrol_step E2X, #152, E2DIR, PNEWX, PLEADX, PFOOTY
e2_done:
    .a16

    ; --- contact resolution: stomp or hurt, per enemy ---
    sf_stomp_check PX, PYI, VY, E1X, #200, E1ALIVE
    cmp #$0001
    bne r1
    jmp scored
r1: cmp #$0002
    bne r2
    jmp hurt
r2:
    .a16
    sf_stomp_check PX, PYI, VY, E2X, #152, E2ALIVE
    cmp #$0001
    bne r3
    jmp scored
r3: cmp #$0002
    bne r4
    jmp hurt
r4: jmp resolve_done

scored:
    .a16
    lda FOES                    ; a stomp landed: count down + reprint
    dec a
    sta FOES
    ldx #$0000
    sta f:$7E0000 + $E010, x
    sf_print_u16 FOES, #48, #8
    lda FOES
    bne resolve_done_j
    print str_clear, #104, #104 ; both down -> CLEAR mid-screen
resolve_done_j:
    .a16
    jmp resolve_done

hurt:
    .a16
    lda #SPAWN_X                ; knockback: respawn (enemy survives)
    sta PX
    lda #SPAWN_Y * 256
    sta PYF
    stz VY
    stz GROUNDED
    lda HURTS
    inc a
    sta HURTS
    ldx #$0000
    sta f:$7E0000 + $E012, x
    lda PYF
    xba
    and #$00FF
    sta PYI

resolve_done:
    .a16
    spr_clear
    spr #1, PX, PYI, #$00, #2   ; player (slot 0)
    lda E1ALIVE
    beq skip_e1
    spr #1, E1X, #200, #$02, #2 ; ground enemy (slot 1 while alive)
skip_e1:
    .a16
    lda E2ALIVE
    beq skip_e2
    spr #1, E2X, #152, #$02, #2 ; platform enemy
skip_e2:
    .a16
    sf_frame_end
    jmp game_loop

; =============================================================================
; DATA — the HUD strings, the tile art, then the engine includes
; =============================================================================
str_foes:
    .byte "FOES", 0
str_clear:
    .byte "CLEAR", 0

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
