; =============================================================================
; bend_v_reverse_test — run-gate for V-axis reverse roll (negative speed, v1.2)
; =============================================================================
; Identical to bend_v_test.asm EXCEPT the tunnel_v speed is #$FFFE (= −2) instead
; of #2. The phase advance is a WRAPPING 16-bit add and the curve is sampled at
; (scanline + phase) & $FF, so a NEGATIVE speed wraps the phase DOWNWARD and the
; vertical squash pattern rolls the OPPOSITE direction. The test
; (test_bend_v.py) compares the per-scanline inter-frame band shift of THIS ROM
; against the positive-speed bend_v_test.sfc and asserts the shift direction is
; the OPPOSITE SIGN — not merely "frames differ".
;
; Done-condition (read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = channel (3..7); $7E:E010 heartbeat
;   - the per-scanline band pattern advances in the opposite vertical direction
;     to bend_v_test's positive-speed roll.
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
BG_SKY    = $7000               ; sky blue (backdrop, CGRAM 0)
BG_HLINE  = $7FFF               ; white horizon line
BG_MX     = $46
BG_MY     = $48
BG_TILE   = $4A

SKY_ROWS  = 6                   ; identical horizon framing to bend_v_test, so the
                                ; reverse comparison tracks the SAME field structure

BEND_AMP   = 128               ; reciprocal horizon squash, unity passthrough
                                ; (|off|*128/128 = |off|) — matches bend_v_test so
                                ; the reverse comparison tracks the same field.
BEND_SPEED = $FFFE             ; −2 (two's-complement) → the REVERSE V roll

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
    sf_load_bg_tile 2, hline_tile
    sf_bg_color 0, 0, BG_SKY
    sf_bg_color 0, 1, BG_GREEN
    sf_bg_color 0, 2, BG_HLINE

    jsr init_ppu
    gfxmode #1

    ; horizon-framed field identical to bend_v_test (sky / horizon line / ground)
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
    lda BG_MY
    cmp #SKY_ROWS
    bcc @sky
    beq @hline
    lda #1
    sta BG_TILE                 ; ground: 4px-period band tile
    bra @fill
@sky:
    .a16
    .i16
    stz BG_TILE                 ; sky backdrop
    bra @fill
@hline:
    .a16
    .i16
    lda #2
    sta BG_TILE                 ; horizon line
@fill:
    .a16
    .i16
@col:
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #32                      ; fill all 32 rows (256px) so the deep-pulled
                                 ; foreground always has band content (clean render)
    bne @row

    scroll #1, #0, #0

    ; --- arm the ANIMATED V horizon squash with a NEGATIVE speed (reverse) ---
    sf_tunnel_v #SF_CURVE_HORIZON, #BEND_AMP, #BEND_SPEED
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

; 4px-period band tile (rows 0-3 green index 1, rows 4-7 gap) — matches bend_v_test.
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; horizon-line tile (tile 2): colour index 2 on all 8 rows (plane1=$FF).
hline_tile:
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
