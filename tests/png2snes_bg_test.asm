; =============================================================================
; png2snes_bg_test — round-trip run-gate for `png2snes.py bg`
; =============================================================================
; Renders REAL converted CC0 BG art: an 8x6-cell patch of the Four Seasons
; platformer tileset (spring terrain blocks), converted with palette grouping
; + tile dedupe + mset-ready map words. CHR loads through sf_load_bg_chr,
; palettes through sf_load_bg_pals, and the map words go STRAIGHT from the
; converter's table to mset — proving the whole contract end to end.
;
; The patch is drawn at tilemap cells (4,4)..(11,9) = screen px (32,32).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"), completion flag set
;   - the screenshot region at (32,32)-(96,80) matches a PIL render of the
;     SOURCE PNG region (BGR15-quantized) — the pytest does the comparison
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_chr, sf_load_bg_pals
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

BG_MX   = $46                   ; map column 0..terrain_map_w-1 (DP scratch)
BG_MY   = $48                   ; map row    0..terrain_map_h-1
BG_TILE = $4A                   ; current map word (tile | pal<<10)
BG_DX   = $4C                   ; destination cell x/y (mx+4, my+4)
BG_DY   = $4E

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM
    sf_engine_init

    ; converted-art uploads under the coldstart forced blank
    sf_load_bg_chr 0, terrain_chr, terrain_chr_bytes
    sf_load_bg_pals 0, terrain_pal, terrain_pal_count

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- place the converted map: mset the table words verbatim ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    ; map word index = (my * map_w + mx) * 2 — mset clobbers X/Y, so the
    ; loop counters live in DP and X is re-derived each pass
    lda BG_MY
    asl a
    asl a
    asl a                       ; my * 8 (terrain_map_w = 8)
    clc
    adc BG_MX
    asl a                       ; word index -> byte offset
    tax
    lda f:terrain_map, x
    sta BG_TILE
    lda BG_MX
    clc
    adc #4
    sta BG_DX
    lda BG_MY
    clc
    adc #4
    sta BG_DY
    mset #1, BG_DX, BG_DY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #terrain_map_w
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #terrain_map_h
    bne @row

    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; NMI DMAs the dirty shadow tilemap to VRAM
    sf_debug_complete
    jmp game_loop

; --- converted art (committed png2snes output; regen-guarded by pytest) ---
.include "fixtures/png2snes/terrain_bg.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "bg_engine.asm"
