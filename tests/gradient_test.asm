; =============================================================================
; gradient_test — run-gate for the sf_gradient_* macros (RGB COLDATA gradient)
; =============================================================================
; Arms a pure-red → pure-blue 2-stop gradient over the full scanline range and
; makes the fixed color visible with the minimal color-math setup (add fixed
; color on the backdrop — the sf_fx.inc header recipe): screen pixel = black
; backdrop + COLDATA(scanline) = the ramp itself, row by row.
;
; The other gradient macros are exercised for expansion + engine-path coverage
; with visually neutral arguments: ease #0 (linear), phase #0 (animation off),
; one forced sf_gradient_update, and sf_gradient_tick in the loop (no-op while
; animation is off).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = first HDMA channel (3..7)
;   - screenshot rows: top rows red-dominant, bottom rows blue-dominant,
;     red monotonically falling / blue monotonically rising down the frame
;   - frame heartbeat at $7E:E010 advances
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_gradient_* macro group
.include "engine_state.inc"

GRAD_TOP_R = 31                 ; top = pure red
GRAD_BOT_B = 31                 ; bottom = pure blue

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    jsr init_ppu                ; engine PPU defaults (screen on)

    ; --- color math: add the fixed color on the backdrop (NMI commits the
    ;     shadows every VBlank; raw $2130/$2131 writes would be overwritten) ---
    sep #$20
    .a8
    lda #$00
    sta SHADOW_CGWSEL           ; fixed color is the addend, math always on
    lda #$20
    sta SHADOW_CGADSUB          ; add (no half) on the backdrop
    rep #$30
    .a16
    .i16

    ; --- arm the gradient: red (31,0,0) at the top → blue (0,0,31) at the
    ;     bottom; linear easing; animation off; one forced rebuild ---
    sf_gradient_ease #0
    sf_gradient_rgb #GRAD_TOP_R, #0, #0, #0, #0, #GRAD_BOT_B
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record first allocated channel for the test
    sf_gradient_phase #0
    sf_gradient_update

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
    sf_frame_begin              ; wait for NMI (re-arms $420C from the mask)
    sf_gradient_tick            ; no-op (animation off) — loop-path coverage

    ; --- heartbeat: engine frame counter → debug region $7E:E010 ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

.include "ppu_init.inc"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
