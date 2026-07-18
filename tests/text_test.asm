; =============================================================================
; text_test — run-gate for the text macros (font, print, decimal HUD counter)
; =============================================================================
; Initializes the text engine, prints strings and numbers on BG3, and records
; the shadow-tilemap words + decimal conversions to the debug region. Runs the
; frame loop so the NMI commits the shadow BG3 tilemap to VRAM — the pytest
; asserts the REAL outputs: VRAM font bytes, VRAM tilemap words, and rendered
; white pixels on screen.
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"), completes ($7E:E008 == 1)
;   - VRAM @ word $2500 holds the font ('H' glyph bytes match sf_font_2bpp)
;   - shadow + VRAM BG3 tilemap hold the printed tile words (pal 7 | tile)
;   - _sf_u16_to_dec5 produces "00000"/"00042"/"10000"/"65535"
;   - the screen shows the text (white pixels in the printed rows)
;
; Debug region map ($7E:E000):
;   +$10  shadow BG3 (0,0)  expect $3CC8  ("H", pal 7)
;   +$12  shadow BG3 (1,0)  expect $3CC9  ("I", pal 7)
;   +$14  FONT_BASE_TILE    expect 160
;   +$16  VWF_ACTIVE        expect 0 (byte)
;   +$18  shadow BG3 (1,2)  expect $3CD3  ("S" of "SCORE", pal 7)
;   +$20  dec5(0)     "00000\0" (6 bytes)
;   +$28  dec5(42)    "00042\0"
;   +$30  dec5(10000) "10000\0"
;   +$38  dec5(65535) "65535\0"
;   +$40  shadow BG3 (0,4)  expect $3CB1  ("1" of "12345")
;   +$42  shadow BG3 (1,4)  expect $3CB2  ("2")
;   +$44  shadow BG3 (4,4)  expect $3CB5  ("5")
;
; Composited-priority case: BG1 green wall cells sit exactly under "HI" —
; the glyphs must still render (the print macros set the BG3 priority bit;
; without it, Mode 1 draws unflagged BG3 BELOW BG1 and the text vanishes).
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_bg.inc"            ; gfxmode
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM
    sf_engine_init

    sf_text_init                ; font -> VRAM word $2500, mono, white colour
    sf_load_bg_tile 1, bg_tile  ; BG1 tile for the composited-priority case
    sf_bg_color 0, 1, $03E0     ; green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; Mode 1 (zeros the shadow tilemaps)

    ; --- BG1 wall cells under the "HI" text (composited-priority case) ---
    mset #1, #0, #0, #1
    mset #1, #1, #0, #1

    ; --- print test content (after gfxmode — it wipes shadow BG3) ---
    print str_hi, #0, #0        ; "HI" at tile (0,0), default pal 7
    print str_score, #8, #16    ; "SCORE" at tile (1,2)
    sf_print_u16 #12345, #0, #32 ; "12345" at tile row 4

    ; --- record shadow BG3 words ---
    rep #$30
    .a16
    .i16
    ldx #$0000
    lda f:$7E0000 + $B200, x    ; shadow BG3 (0,0)
    sta f:$7E0000 + $E010, x
    lda f:$7E0000 + $B202, x    ; (1,0)
    sta f:$7E0000 + $E012, x
    lda f:$7E0000 + $B282, x    ; (1,2) = $B200 + 2*64 + 1*2
    sta f:$7E0000 + $E018, x
    lda f:$7E0000 + $B300, x    ; (0,4) = $B200 + 4*64
    sta f:$7E0000 + $E040, x
    lda f:$7E0000 + $B302, x    ; (1,4)
    sta f:$7E0000 + $E042, x
    lda f:$7E0000 + $B308, x    ; (4,4)
    sta f:$7E0000 + $E044, x

    ; --- record engine text state ---
    lda FONT_BASE_TILE
    sta f:$7E0000 + $E014, x    ; expect 160
    sep #$20
    .a8
    lda VWF_ACTIVE
    sta f:$7E0000 + $E016, x    ; expect 0
    rep #$20
    .a16

    ; --- decimal conversion edge cases (buffer copied per case) ---
    lda #0
    jsr _sf_u16_to_dec5
    ldy #$E020
    jsr copy_dec_buf
    lda #42
    jsr _sf_u16_to_dec5
    ldy #$E028
    jsr copy_dec_buf
    lda #10000
    jsr _sf_u16_to_dec5
    ldy #$E030
    jsr copy_dec_buf
    lda #65535
    jsr _sf_u16_to_dec5
    ldy #$E038
    jsr copy_dec_buf

    sf_debug_magic
    sf_debug_complete

    ; enable NMI + auto-joypad; run the loop so the NMI DMAs shadow -> VRAM
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin
    jmp game_loop

; -----------------------------------------------------------------------------
; copy_dec_buf — copy SF_DEC_BUF (6 bytes) to debug region offset Y ($7E:00Y).
; -----------------------------------------------------------------------------
; In: Y = 16-bit debug-region address (e.g. $E020). Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; exits A16/I16.
copy_dec_buf:
    rep #$30
    .a16
    .i16
    tyx                         ; X = destination offset in bank $7E
    lda a:SF_DEC_BUF            ; bytes 0-1
    sta f:$7E0000, x
    lda a:SF_DEC_BUF + 2        ; bytes 2-3
    sta f:$7E0002, x
    lda a:SF_DEC_BUF + 4        ; bytes 4-5 (digit 4 + NUL)
    sta f:$7E0004, x
    rts

str_hi:
    .byte "HI", 0
str_score:
    .byte "SCORE", 0

; one solid 8x8 4bpp tile (all colour index 1) for the BG1 underlay
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
.include "dma_scheduler.asm"
