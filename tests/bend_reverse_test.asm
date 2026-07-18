; =============================================================================
; bend_reverse_test — run-gate for E-DIR: a NEGATIVE speed reverses the roll
; =============================================================================
; Enhancement v1.1 (E-DIR): the phase advance is a WRAPPING 16-bit add
; (HDMA_WAVE_PHASE += HDMA_WAVE_SPEED) and the curve is sampled at
; (scanline + phase) & $FF, so a NEGATIVE (two's-complement) speed makes the
; phase wrap DOWNWARD and the roll runs the opposite direction.
;
; This ROM is identical to bend_test.asm EXCEPT the tunnel speed is #$FFFE
; (= −2) instead of #2. The test (test_bend_reverse.py) compares the per-scanline
; inter-frame shift of THIS ROM against the positive-speed bend_test.sfc and
; asserts the shift direction is the OPPOSITE SIGN — not merely "frames differ".
;
; Done-condition (read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = channel (3..7); $7E:E010 heartbeat
;   - the per-scanline stripe pattern advances UPWARD (the reverse roll), the
;     opposite direction to bend_test's positive-speed downward roll.
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_frame.inc"
.include "sf_fx.inc"
.include "engine_state.inc"

BG_GREEN  = $03E0
BG_MX     = $46
BG_MY     = $48
BG_TILE   = $4A

BEND_AMP   = 14
BEND_SPEED = $FFFE              ; −2 (two's-complement) → the REVERSE roll

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    jsr hdma_alloc_init

    sf_load_bg_tile 1, bg_tile
    sf_bg_color 0, 1, BG_GREEN

    jsr init_ppu
    gfxmode #1

    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    lsr
    lsr
    and #$0001
    sta BG_TILE
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #24
    bne @row

    scroll #1, #0, #0

    ; --- arm the ANIMATED sine tunnel with a NEGATIVE speed (reverse roll) ---
    sf_tunnel #SF_CURVE_SINE, #BEND_AMP, #BEND_SPEED
    ldx #$0000
    sta f:$7E0000 + $E012, x

    sf_debug_magic

    sep #$20
    .a8
    lda $4210
@wait_vblank_end:
    lda $4212
    bmi @wait_vblank_end
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin
    sf_bend_tick
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
