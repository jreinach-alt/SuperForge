; =============================================================================
; autoscroll_test — run-gate for sf_autoscroll_v (vertical autoscroll brick)
; =============================================================================
; A horizontal-stripe BG1 (green every other tile row) autoscrolls vertically
; at 1 px/frame via sf_autoscroll_v — no input. The world must drift DOWN the
; screen (the shmup "flying up" direction).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"), completion flag set
;   - SHADOW_BG1VOFS ($0122) decreases frame over frame (wraps as u16)
;   - $7E:E010 mirrors the counter for the test
;   - the on-screen stripe pattern shifts DOWN by exactly the VOFS delta
;     (the pytest correlates pixels with the register delta)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset, sf_autoscroll_v + loaders
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

BG_GREEN = $03E0
BG_MX    = $46                  ; tilemap fill loop scratch (DP)
BG_MY    = $48
BG_TILE  = $4A
SCRL_Y   = $4C                  ; the autoscroll counter

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM
    sf_engine_init

    sf_load_bg_tile 1, bg_tile  ; BG1 CHR: tile 1 = solid colour index 1
    sf_bg_color 0, 1, BG_GREEN

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- horizontal stripes: even tile rows green, odd rows empty ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MY
    and #$0001
    eor #$0001                  ; tile 1 on even rows
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
    cmp #32
    bne @row

    stz SCRL_Y
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin
    sf_autoscroll_v #1, SCRL_Y, #1
    ldx #$0000
    lda SCRL_Y
    sta f:$7E0000 + $E010, x    ; mirror the counter for the test
    sf_debug_complete
    jmp game_loop

; one solid 8x8 4bpp tile (all colour index 1)
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
