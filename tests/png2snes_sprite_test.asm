; =============================================================================
; png2snes_sprite_test — round-trip run-gate for `png2snes.py sprite`
; =============================================================================
; Displays REAL converted CC0 art from two packs side by side:
;   - hero  (dungeonSprites fHero idle, 24x24 frames re-centered to 16x16)
;     frame 0 as a SMALL sprite at (60,80), OBJ palette 0
;   - arthur (camelot 32x32 sheet, frames 0-7) frame 0 as a LARGE sprite at
;     (120,80), OBJ palette 1
; OBSEL is set to size pair 3 (16x16 small / 32x32 large) so both native
; sizes render in one ROM. CHR loads through sf_load_obj_chr (16-aligned
; bases), palettes through sf_load_obj_pal.
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"), completion flag set
;   - the screenshot's 16x16 region at hero's position matches a PIL render
;     of the SOURCE PNG (BGR15-quantized), and the 32x32 region at arthur's
;     position matches his source frame — the pytest does the comparison
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

HERO_BASE   = 0                 ; OBJ tiles 0-31 (2 VRAM rows)
ARTHUR_BASE = 32                ; OBJ tiles 32-159 (8 VRAM rows)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM
    sf_engine_init

    ; converted-art uploads under the coldstart forced blank
    sf_load_obj_chr HERO_BASE,   hero_chr,   hero_chr_bytes
    sf_load_obj_chr ARTHUR_BASE, arthur_chr, arthur_chr_bytes
    sf_load_obj_pal 0, hero_pal
    sf_load_obj_pal 1, arthur_pal

    jsr init_ppu                ; engine PPU defaults (sets OBSEL=$00, screen on)

    ; OBSEL size pair 3: small = 16x16, large = 32x32 (name base 0).
    ; init_ppu hardwires $00 (8/16), so re-set it under a brief forced blank
    ; (PPU regs are not writable mid-frame with the screen on).
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; forced blank
    lda #$60                    ; size pair 3, name base $0000
    sta $2101
    lda #$0F
    sta $2100                   ; screen back on, full brightness
    rep #$30
    .a16
    .i16

    spr_clear
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
    spr_clear
    ; hero frame 0: small (16x16), palette 0
    spr #(HERO_BASE + hero_f0), #60, #80, #$00, #2
    ; arthur frame 0: large (32x32), palette 1 (flags bit7=size, bits3:1=pal)
    spr #(ARTHUR_BASE + arthur_f0), #120, #80, #$82, #2
    sf_frame_end
    sf_debug_complete
    jmp game_loop

; --- converted art (committed png2snes output; regen-guarded by pytest) ---
.include "fixtures/png2snes/hero16.inc"
.include "fixtures/png2snes/arthur32.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
