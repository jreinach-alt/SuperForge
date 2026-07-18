; =============================================================================
; hello_world — the simplest visible SuperForge project
; =============================================================================
; Boots from a fresh clone and puts one visible sprite on screen: a solid red
; 8x8 square at (120,100). Proves the toolchain end-to-end — cold boot, OBJ
; tile + palette upload, sprite placement, and the frame loop pushing it to
; hardware — using only the macro library and the engine.
;
; Done-condition (emulator-verifiable):
;   - $7E:E000 == "SFDB"  (booted)
;   - hardware OAM slot 0 == X120 Y100 tile1  (sprite placed + DMA'd)
;   - screenshot: the pixels around (123,103) are red; the backdrop is not.
;
; Build:  make hello_world      (-> build/hello_world.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"

.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end

.include "engine_state.inc"

OBJ_RED = $001F                 ; 15-bit BGR: red

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; boot + WRAM clear (screen force-blanked)
    sf_engine_init              ; engine state

    ; --- visible-sprite setup (must precede init_ppu / screen-on) ---
    sf_obj_color 0, 1, OBJ_RED  ; OBJ palette 0, colour slot 1 = red
    sf_load_obj_tile 1, sprite_tile  ; tile #1 = solid square (all colour 1)

    jsr init_ppu                ; Mode 1 + OBJ + OAMADD=0 + screen on
    spr_clear
    sf_debug_magic              ; "SFDB" -> $7E:E000

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
    spr_clear
    spr #1, #120, #100, #$00, #2   ; tile 1, OBJ palette 0, priority 2
    sf_frame_end
    jmp game_loop

; --- one solid 8x8 4bpp tile: every pixel = colour index 1 ---
sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00   ; rows 0-3, planes 0/1
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00   ; rows 4-7, planes 0/1
    .byte $00,$00, $00,$00, $00,$00, $00,$00   ; rows 0-3, planes 2/3
    .byte $00,$00, $00,$00, $00,$00, $00,$00   ; rows 4-7, planes 2/3

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
