; =============================================================================
; colormath_test — run-gate for sf_colormath_on / sf_colormath_off / _tint
; =============================================================================
; Renders a known scene (mid-gray backdrop, CGRAM entry 0 = r=g=b=12) and
; drives the off → on+tint → off state cycle from the test harness: while A
; is HELD, color math is ON with a full-strength red ADD tint on the backdrop
; (CGWSEL=$02 falls back to the fixed color while TS=0 — the file-header
; contract); released, color math is OFF. The macros are re-applied every
; frame (idempotent shadow writes; the NMI commits the shadows each VBlank).
;
; Done-condition (emulator-verifiable, rendered pixels only):
;   - boots ($7E:E000 == "SFDB"); frame heartbeat at $7E:E010 advances
;   - A released: screen is the gray backdrop (r≈g≈b)
;   - A held: red channel rises by the tint (+15 of 31), green/blue unchanged
;   - A released again: pixels revert to the original gray
;   - $7E:E014 mirrors the ROM-side state (0=off, 1=on) as ground truth
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; sf_bg_color (backdrop setup)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_colormath_* macro group
.include "engine_state.inc"

BD_GRAY = $318C                 ; 15-bit BGR, r=g=b=12 — mid-gray backdrop
JOY_A   = $0080                 ; JOY1_CURRENT bit (A button)

TINT_R  = 15                    ; red tint intensity (gray 12 + 15 = 27 of 31)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

    ; backdrop = mid-gray (CGRAM entry 0), under the coldstart forced blank
    sf_bg_color 0, 0, BD_GRAY

    jsr init_ppu                ; engine PPU defaults (screen on, brightness 15)

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

    ; --- A held → color math ON (ADD red tint on the backdrop);
    ;     released → OFF. Driven by the test via set_input. ---
    lda JOY1_CURRENT
    bit #JOY_A
    beq @math_off
    sf_colormath_on #1, #$20    ; mode 1 = ADD, layers $20 = backdrop
    sf_colormath_tint #TINT_R, #0, #0
    lda #$0001
    bra @record
@math_off:
    .a16
    sf_colormath_off
    lda #$0000
@record:
    .a16
    ldx #$0000
    sta f:$7E0000 + $E014, x    ; state mirror (0=off, 1=on) — ground truth

    ; --- heartbeat: engine frame counter → debug region $7E:E010 ---
    lda FRAME_COUNTER
    sta f:$7E0000 + $E010, x
    jmp game_loop

.include "ppu_init.inc"
.include "dma_scheduler.asm"
.include "colormath_engine.asm"
