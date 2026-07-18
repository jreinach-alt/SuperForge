; =============================================================================
; bright_fade_test — run-gate for sf_bright_fade + sf_bright_fade_tick
; =============================================================================
; Renders a bright scene (white backdrop) at the kit boot's full brightness
; (init_ppu leaves SHADOW_INIDISP = $0F — the documented starting value) and
; drives BOTH fade directions from the test harness:
;   - A pressed (edge) → sf_bright_fade #0,  #60   (fade DOWN to black)
;   - B pressed (edge) → sf_bright_fade #15, #60   (fade UP to full)
; sf_bright_fade_tick runs every frame; the NMI commits SHADOW_INIDISP to
; $2100 each VBlank.
;
; Done-condition (emulator-verifiable, rendered pixels only):
;   - boots ($7E:E000 == "SFDB"); frame heartbeat at $7E:E010 advances
;   - after A: mean screen luminance decreases monotonically across ≥3
;     sample points and ends near-black
;   - after B: mean luminance rises monotonically back to near the start
;   - $7E:E014 mirrors SHADOW_INIDISP (supplemental ground truth only —
;     the assertions are on screenshot pixels)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; sf_bg_color (backdrop setup)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_bright_fade macro group
.include "engine_state.inc"

BD_WHITE   = $7FFF              ; 15-bit BGR white backdrop
JOY_A      = $0080              ; JOY1_PRESSED_LATCH bit (A button)
JOY_B      = $8000              ; JOY1_PRESSED_LATCH bit (B button)
FADE_LEN   = 60                 ; frames per fade

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

    ; backdrop = white (CGRAM entry 0), under the coldstart forced blank
    sf_bg_color 0, 0, BD_WHITE

    jsr init_ppu                ; screen on — SHADOW_INIDISP = $0F (the
                                ; fade's documented sane starting value)

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
    sf_frame_begin              ; wait for NMI; latch input

    ; --- A edge → arm fade DOWN; B edge → arm fade UP (test-driven) ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_A
    beq @no_a
    sf_bright_fade #0, #FADE_LEN
@no_a:
    .a16
    lda JOY1_PRESSED_LATCH
    bit #JOY_B
    beq @no_b
    sf_bright_fade #15, #FADE_LEN
@no_b:
    .a16
    sf_bright_fade_tick         ; the per-frame stepper service

    ; --- mirrors: SHADOW_INIDISP → $E014 (supplemental), heartbeat → $E010 ---
    lda SHADOW_INIDISP
    and #$00FF
    ldx #$0000
    sta f:$7E0000 + $E014, x
    lda FRAME_COUNTER
    sta f:$7E0000 + $E010, x
    jmp game_loop

.include "ppu_init.inc"
.include "dma_scheduler.asm"
.include "bright_fade_engine.asm"
