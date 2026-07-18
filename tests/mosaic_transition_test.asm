; =============================================================================
; mosaic_transition_test — run-gate for the sf_mosaic_transition wipe macros
; =============================================================================
; Two visually-distinct full-screen scenes and a caller swap routine, with the
; wipe driven by the test harness:
;   - scene A: RED BG1 fill + a white OBJ sprite mid-screen
;   - A press -> sf_mosaic_transition_arm $01, swap_to_b   (wipe to scene B)
;   - swap_to_b: recolor BG1 -> BLUE under the kit forced-blank bracket
;   - scene B: BLUE BG1 fill + the sprite back
; The wipe must, MID-transition, simultaneously (a) DARKEN the screen (the
; darkness ease) and (b) PIXELATE the BG (mosaic size>0) and (c) DROP the OBJ
; sprite (sprites have no HW mosaic) — then restore a clean, full-bright scene B.
;
; Done-condition (emulator-verifiable, rendered output + the committed shadow
; registers which the NMI writes to the PPU):
;   - boots ($7E:E000 == "SFDB"); frame heartbeat at $7E:E010 advances
;   - BEFORE arm: bright RED scene, sprite present
;   - MID OUT phase: SHADOW_MOSAIC nonzero (pixelated) AND brightness < full
;     (darkened) AND the OBJ bit of SHADOW_TM is clear (sprite dropped)
;   - AFTER the wipe settles: bright BLUE scene, sprite back, mosaic cleared,
;     brightness full
;
; Debug region ($7E:E000):
;   +$10  frame heartbeat (FRAME_COUNTER)
;   +$12  SHADOW_MOSAIC mirror   +$14  SHADOW_INIDISP mirror
;   +$16  SHADOW_TM mirror       +$18  transition state (sf_mosaic_transition_active)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_sprite.inc"        ; spr (OBJ)
.include "sf_video.inc"         ; sf_load_obj_tile, sf_obj_color
.include "sf_scene_mode.inc"    ; sf_blank_enter / sf_blank_exit (swap bracket)
.include "sf_mosaic_transition.inc"  ; arm / tick / active
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

JOY_A      = $0080              ; JOY1_PRESSED_LATCH bit (A button)

fill_x = $1800
fill_y = $1802
fill_tile = $1804

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

    ; --- scene A assets: two BG1 tiles for a checkerboard (so the mosaic is
    ;     visibly detectable on the rendered frame) + a white OBJ sprite ---
    sf_load_bg_tile 1, wall_tile    ; tile 1 = color 1 (the scene's main color)
    sf_load_bg_tile 2, dark_tile    ; tile 2 = color 2 (checker contrast)
    sf_bg_color 0, 1, $001F         ; BG1 pal0 color 1 = RED (r31)
    sf_bg_color 0, 2, $0010         ; BG1 pal0 color 2 = dark red (checker)
    sf_bg_color 0, 0, $0000         ; backdrop black
    ; OBJ sprite CHR at tile 64 (word $0400 — past the BG1 tilemap at $0000,
    ; before BG1 CHR at $2000; OBSEL name base = word $0000 so tile 64 = $0400).
    spr_clear                       ; init shadow OAM (Y=$F0 x128)
    sf_load_obj_tile 64, sprite_tile
    sf_obj_color 0, 1, $7FFF        ; OBJ pal0 color 1 = white

    jsr init_ppu
    gfxmode #1                  ; Mode 1; zeros BG shadows

    ; fill BG1 with a checkerboard of tile 1 / tile 2 (32x28)
    rep #$30
    .a16
    .i16
    stz fill_y
@fill_row:
    stz fill_x
@fill_col:
    ; tile = 1 + ((x ^ y) & 1)  -> alternating checker
    lda fill_x
    eor fill_y
    and #$0001
    inc a                       ; 1 or 2
    sta fill_tile
    mset #1, fill_x, fill_y, fill_tile
    lda fill_x
    inc a
    sta fill_x
    cmp #32
    bcc @fill_col
    lda fill_y
    inc a
    sta fill_y
    cmp #28
    bcc @fill_row

    sf_debug_magic

    ; enable NMI + auto-joypad
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- place the sprite (a center white block) every frame. The wipe's OBJ
    ;     drop (SHADOW_TM bit4 clear) hides ALL sprites at the hardware level
    ;     during the dissolve, so this still-placed sprite vanishes mid-wipe. ---
    spr_clear                    ; reset shadow OAM each frame (slot-order contract)
    spr #64, #120, #100, #0, #3  ; tile 64, (120,100), pal 0, priority 3 (front)

    ; --- A edge -> arm the wipe to scene B (BG1 only -> bg_mask $01) ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq @no_a
    sf_mosaic_transition_arm #$01, swap_to_b
@no_a:
    .a16

    ; --- per-frame wipe service ---
    sf_mosaic_transition_tick

    ; --- mirrors for ground-truth cross-checks (rendered output is the gate) ---
    sep #$20
    .a8
    ldx #$0000
    lda SHADOW_MOSAIC
    sta f:$7E0000 + $E012, x
    lda SHADOW_INIDISP
    sta f:$7E0000 + $E014, x
    lda SHADOW_TM
    sta f:$7E0000 + $E016, x
    rep #$30
    .a16
    .i16
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    sf_mosaic_transition_active
    sta f:$7E0000 + $E018, x

    sf_frame_end                ; resolve shadow OAM + signal DMA -> NMI commits
    jmp game_loop

; -----------------------------------------------------------------------------
; swap_to_b — the caller's mid-transition scene swap: recolor BG1 to BLUE under
; the kit forced-blank bracket. RTS-terminated (the wipe tail-calls it).
; Entry: A8/I16 (the stepper's swap-frame convention). Exit: A8/I16.
; -----------------------------------------------------------------------------
.a8
.i16
swap_to_b:
    sf_blank_enter              ; force blank + mask NMI
    sf_bg_color 0, 1, $7C00     ; BG1 pal0 color 1 = BLUE (b31)
    sf_bg_color 0, 2, $4000     ; BG1 pal0 color 2 = dark blue (checker)
    sf_blank_exit               ; drop blank + re-enable NMI
    sep #$20
    .a8
    rts

; ---- assets ----
wall_tile:
    ; 4bpp solid tile, all pixels color index 1.
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00
dark_tile:
    ; 4bpp solid tile, all pixels color index 2 (the checker contrast). Color 2
    ; = bitplane1 set: [bp0,bp1] per row -> $00,$FF; planes 2-3 zero.
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF, $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00
sprite_tile:
    ; 4bpp solid 8x8 sprite, all pixels color index 1 (white).
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
.include "sprite_engine.asm"
.include "sf_mosaic_transition_data.inc"
