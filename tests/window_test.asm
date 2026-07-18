; =============================================================================
; window_test — run-gate for the sf_window brick (PPU window masking).
; =============================================================================
; A fully-green BG1 (solid colour index 1, every cell) with a DISTINCT magenta
; backdrop (CGRAM 0). sf_window enables window 1 on BG1 and masks BG1 on the
; MAIN screen INSIDE the window band, so the masked region shows the backdrop
; instead of the BG. The band starts as the right half (WH0=128..WH1=255):
; the LEFT half stays green, the RIGHT half reveals magenta.
;
; Each game-loop frame moves the window LEFT edge (WH0) one pixel to the left
; (down to a floor), so the green/magenta clip edge slides left over time —
; the pytest screenshots two frames and asserts the edge moved.
;
; Done-condition (rendered OUTPUT + the moving edge):
;   - boots ($7E:E000 == "SFDB"), completion flag $7E:E008 == 1
;   - LEFT half (x=60)  renders GREEN (BG1 visible, outside the window)
;   - RIGHT half (x=200) renders MAGENTA (BG1 masked -> backdrop)
;   - $7E:E010 mirrors SHADOW_WH0 (the live left edge) for the test
;   - frame-A vs frame-B: the clip column moves left (WH0 decreased)
;
; Build: default 32KB lorom.cfg via the generic tests/%.sfc rule.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset, sf_bg_color, sf_load_bg_tile
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_window.inc"        ; the brick under test
.include "engine_state.inc"

BG_GREEN    = $03E0             ; bright green (colour index 1)
BD_MAGENTA  = $7C1F             ; bright magenta backdrop (CGRAM 0)

BG_MX       = $46               ; tilemap fill loop scratch (DP)
BG_MY       = $48

WIN_LEFT0   = 128               ; initial window 1 left edge (right half)
WIN_RIGHT0  = 255               ; window 1 right edge (screen edge)
WIN_FLOOR   = 40                ; lowest the left edge slides to

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM/WRAM
    sf_engine_init

    sf_load_bg_tile 1, bg_tile  ; BG1 CHR tile 1 = solid colour index 1
    sf_bg_color 0, 0, BD_MAGENTA ; CGRAM 0 = backdrop (shown where BG masked)
    sf_bg_color 0, 1, BG_GREEN   ; BG1 colour index 1 = green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- fill BG1: every cell = tile 1 (solid green) ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    mset #1, BG_MX, BG_MY, #1
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

    ; --- sf_window: window 1 on BG1, mask BG1 inside the band (main screen) ---
    sf_window1_edges #WIN_LEFT0, #WIN_RIGHT0   ; band = right half [128,255]
    sf_window_bg12 #SF_WIN1_INSIDE             ; BG1 uses window 1, INSIDE area
    sf_window_logic #SF_WINLOG_OR              ; single window -> OR (safe)
    sf_window_mask_main #SF_WIN_BG1            ; disable BG1 inside band on main
    sf_window_mask_sub #0                      ; sub screen unmasked

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

    ; --- slide the window LEFT edge left by 1 px/frame, floored at WIN_FLOOR ---
    sep #$20
    .a8
    lda SHADOW_WH0
    cmp #WIN_FLOOR
    beq @hold
    dec a
    sta SHADOW_WH0              ; NMI re-commits WH0 ($2126) next VBlank
@hold:
    lda SHADOW_WH0
    sta f:$7E0000 + $E010      ; mirror the live left edge for the test
    rep #$20
    .a16

    sf_debug_complete
    jmp game_loop

; one solid 8x8 4bpp tile, all pixels = colour index 1
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
