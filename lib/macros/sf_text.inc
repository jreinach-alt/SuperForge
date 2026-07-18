; =============================================================================
; sf_text.inc — text + HUD macros (macro library)
; =============================================================================
; Render ASCII text and decimal numbers to the BG3 text layer over the engine's
; text engine. Each macro marshals its arguments into the API block and calls
; the engine fn directly (the macro is the wrapper — see sf_sprite.inc). Text
; goes to the shadow BG3 tilemap; the NMI handler DMAs the dirty shadow to VRAM
; every frame, so text appears/updates at the next VBlank.
;
; BG3 is the kit's TEXT LAYER by construction: the `print` macros hard-wire
; layer 3 (no layer argument to get wrong) AND set the per-tile BG3 priority
; bit on every glyph, which under Mode 1's BGMODE=$09 lifts the text above
; BG1/BG2 — so HUD text really does sit on top of the game background.
; (BGMODE's BG3-priority bit alone is NOT enough: it only elevates
; priority-FLAGGED tiles, and the engine's print writes the tile word without
; bit 13 — unflagged text renders BELOW BG1 and is occluded by any wall/floor
; tile it overlaps. The macros bake the bit into the colour value the engine
; shifts into the tile word; emulator-verified against a BG1 wall cell.)
;
; Requires (linked into the ROM): engine/engine_state.inc + engine/bg_engine.asm
; + engine/text_engine.asm, plus sf_text_data.inc (the font data + the decimal
; routine — include it at the BOTTOM of main.asm in CODE, next to the engine
; .asm includes). The NMI handler + dma_scheduler commit the dirty shadow
; tilemap to VRAM. engine_api.inc supplies the API block SSoT.
;
; Setup ordering (by construction — text is undefined otherwise):
;   1. sf_coldstart            (forced blank; clears CGRAM/VRAM)
;   2. sf_text_init            (font upload to VRAM — MUST be under the forced
;                              blank, i.e. before init_ppu/gfxmode turn the
;                              screen on. Also sets the default white colour.)
;   3. jsr init_ppu / gfxmode #1   (gfxmode ZEROS all shadow tilemaps,
;                              including BG3's)
;   4. print / sf_print_u16    (AFTER gfxmode, or the text is wiped)
;   5. enable NMI; reprint whenever the text changes
;
; Colour contract: the font glyphs use colour 3 of the selected BG3 palette.
; The default palette is 7, so the glyph colour lives at CGRAM entry 31
; (= 7*4 + 3; BG3 palettes are 2bpp — 4 colours each, entries pal*4..pal*4+3).
; sf_text_init sets entry 31 to white so text is visible by default; use
; sf_text_color to change it. NOTE: CGRAM entries 28-31 alias BG1 (4bpp)
; palette 1 slots 12-15 — if your game uses BG1 palette 1, avoid those slots.
;
; Clobber contract: all macros here clobber A, X, Y, plus DP $A0-$A2 (the
; engine's text scratch pointer), the engine's text scratch WRAM $057A-$0586
; (TEXT_SCRATCH_TX..NLEFT), and WRAM $0530-$0535 (the decimal buffer,
; sf_print_u16 only). They expect DB=$00 (the kit's standard data bank).
; All of that scratch is transient (consumed within the call), and none of it
; touches the template DP range ($32+), so print/sf_print_u16 are SAFE TO
; CALL MID-GAME-LOOP — reprint a counter or a status line whenever it changes.
; =============================================================================

.ifndef SF_TEXT_INC
SF_TEXT_INC = 1

.include "engine_api.inc"

; Decimal conversion buffer (6 bytes: 5 ASCII digits + NUL). Lives in the
; verified-unaliased WRAM scratch hole $0520-$053F (the engine's VWF scratch
; uses $0520-$0527; $0528+ is free — see engine/text_engine.asm).
SF_DEC_BUF = $0530

; -----------------------------------------------------------------------------
; sf_text_color color15 — set the text colour (CGRAM entry 31).
; -----------------------------------------------------------------------------
; color15 is 15-bit BGR (e.g. $7FFF white, $001F red, $03E0 green). Writes the
; glyph colour of the default text palette (BG3 palette 7, colour 3). CGRAM is
; writable during forced blank / VBlank — call in setup (sf_text_init already
; defaults this to white; call this after it to override).
; WIDTH-RISK: enters any width, uses A8 for the byte writes, exits A16.
.macro sf_text_color sf_color
    sep #$20
    .a8
    lda #31                    ; CGRAM entry 31 = BG3 palette 7, colour 3
    sta $2121                  ; CGADD
    lda #<(sf_color)
    sta $2122                  ; CGDATA low byte
    lda #>(sf_color)
    sta $2122                  ; CGDATA high byte
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_text_init — upload the font and initialize the text engine.
; -----------------------------------------------------------------------------
; Uploads the built-in 8x8 font (96 ASCII glyphs $20-$7F, 2bpp, 1536 bytes from
; sf_text_data.inc) to the engine's font slot — BG3 tile 160 — and initializes
; the engine's font state (monospace, base tile 160), then sets the default
; text colour to white so `print` is visible with no further setup.
;
; VRAM contract (verified on the emulator): gfxmode's BG34NBA=$0A puts the
; BG3 CHR base at word $2000 — the SAME region as the BG1 CHR base (BG12NBA).
; Font tile 160 (2bpp, 8 words/tile) therefore lives at word $2500, and the
; 96 glyphs occupy words $2500-$27FF = BG1 4bpp tile indices 80-127. Keep
; game BG1 tiles below index 80 (sf_load_bg_tile slots 0-79 are safe).
;
; Call under forced blank, after sf_coldstart and BEFORE init_ppu/gfxmode turn
; the screen on. CPU word writes (1536 bytes is setup-time only; NMI is off
; during setup by the kit's boot contract).
; WIDTH-RISK: enters any width, toggles A8 for VMAIN, exits A16/I16.
.macro sf_text_init
    .local up
    sep #$20
    .a8
    lda #$80
    sta $2115                  ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #$2500                 ; VRAM word $2500 — BG3 chr base $2000 + tile 160
    sta $2116                  ; VMADD
    ldx #$0000
up:
    lda f:sf_font_2bpp, x      ; next source word (bank from the label)
    sta $2118                  ; VMDATA word, VMADD++
    inx
    inx
    cpx #1536                  ; 96 tiles x 16 bytes
    bne up
    jsr engine_print_init      ; FONT_BASE_TILE=160, monospace, VWF off
    sf_text_color $7FFF        ; default glyph colour: white (never invisible)
.endmacro

; -----------------------------------------------------------------------------
; print str_label, x, y [, pal] — print a NUL-terminated string on BG3.
; -----------------------------------------------------------------------------
;   str_label  a BARE ROM label of NUL-terminated ASCII (chars $20-$7F render;
;              others are skipped) — e.g. `print msg, #8, #8` with
;              `msg: .byte "SCORE", 0` in CODE/RODATA. NOT verbatim — the macro
;              takes the label's address + bank itself.
;   x, y       pixel coordinates (verbatim operands — write `#8`); snapped to
;              the 8x8 tile grid (x>>3, y>>3). On-screen text: x 0-247, y 0-223.
;   pal        BG3 palette 0-7 (verbatim, optional — default #7, the palette
;              sf_text_init colours white).
; Writes the shadow BG3 tilemap + marks it dirty; the NMI commits it next
; VBlank. Text persists until overprinted (print spaces to erase). Call AFTER
; gfxmode (it zeros the shadow tilemap). Clipped at column 31 (no wrap).
; Clobbers A, X, Y + DP $A0-$A2.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_print runs its
; own widths and returns A16.
.macro print sf_str, sf_x, sf_y, sf_pal
    rep #$30
    .a16
    .i16
    lda #.loword(sf_str)
    sta API_BLOCK_BASE + $00   ; str_ptr low 16
    lda #.bankbyte(sf_str)
    sta API_BLOCK_BASE + $02   ; str_ptr bank (engine reads the low byte)
    lda sf_x
    sta API_BLOCK_BASE + $04   ; x (pixels)
    lda sf_y
    sta API_BLOCK_BASE + $08   ; y (pixels)
.ifblank sf_pal
    lda #$0007                 ; default palette 7 (white via sf_text_init)
.else
    lda sf_pal
.endif
    ora #$0008                 ; + BG3 priority: engine shifts <<10 -> bit 13,
    sta API_BLOCK_BASE + $0C   ;   so text renders ABOVE BG1/BG2 (see header)
    lda #$0003
    sta API_BLOCK_BASE + $10   ; layer 3 = BG3, the text layer (by construction)
    jsr engine_print
.endmacro

; -----------------------------------------------------------------------------
; sf_print_u16 value, x, y [, pal] — print a 16-bit number as 5 decimal digits.
; -----------------------------------------------------------------------------
;   value      16-bit unsigned, 0-65535 (verbatim operand — a memory operand
;              like `SCORE` reads that address; `#1234` prints a literal).
;   x, y, pal  as `print`.
; Renders zero-padded 5 digits ("00042") — a fixed-width HUD counter that
; never leaves stale digits behind when the value shrinks. Converts via
; _sf_u16_to_dec5 (sf_text_data.inc) into SF_DEC_BUF, then prints it.
; Reprint after the value changes (cheap: 5 tiles + one tilemap DMA).
; Clobbers A, X, Y + DP $A0-$A2 + SF_DEC_BUF ($0530-$0535).
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_print_u16 sf_val, sf_x, sf_y, sf_pal
    rep #$30
    .a16
    .i16
    lda sf_val
    jsr _sf_u16_to_dec5        ; SF_DEC_BUF <- 5 ASCII digits + NUL
    lda #SF_DEC_BUF
    sta API_BLOCK_BASE + $00   ; str_ptr = the decimal buffer
    stz API_BLOCK_BASE + $02   ; bank 0 (low WRAM mirror in bank $00)
    lda sf_x
    sta API_BLOCK_BASE + $04
    lda sf_y
    sta API_BLOCK_BASE + $08
.ifblank sf_pal
    lda #$0007
.else
    lda sf_pal
.endif
    ora #$0008                 ; + BG3 priority (same contract as print)
    sta API_BLOCK_BASE + $0C
    lda #$0003
    sta API_BLOCK_BASE + $10   ; layer 3 = BG3 (by construction)
    jsr engine_print
.endmacro

; -----------------------------------------------------------------------------
; sf_text_clear y_start, y_end — erase whole text rows (scene transitions).
; -----------------------------------------------------------------------------
;   y_start, y_end   verbatim TILE-row operands (`#0`, `#28`): rows
;                    [y_start, y_end) of BG3 are zeroed (end EXCLUSIVE).
; The scene-flow eraser: clears titles/HUDs in one call instead of printing
; spaces. Pixel y / 8 = tile row (print's y=8 lives on tile row 1). The NMI
; commits the cleared rows next frame. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); engine_bg3_clear_rows
; expects 16-bit AXY and returns A16.
.macro sf_text_clear sf_y0, sf_y1
    rep #$30
    .a16
    .i16
    lda sf_y0
    sta API_BLOCK_BASE + $00
    lda sf_y1
    sta API_BLOCK_BASE + $04
    jsr engine_bg3_clear_rows
.endmacro

.endif ; SF_TEXT_INC
