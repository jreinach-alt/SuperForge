; =============================================================================
; obj_hud_test — OBJ sprite-font HUD renderer render gate (the showcase brick).
; =============================================================================
; Proves the sf_obj_text.inc HUD primitive renders a legible glyph readout as OBJ
; sprites in OBJ palette 7, over a real BG, in EVERY mode — the two that matter
; are a NORMAL mode (Mode 1) and the 256-colour Mode 3 (where the BG owns CGRAM
; 0-239 and the HUD must own its reserved OBJ pal 7 = CGRAM 240-255). One ROM,
; parametrised by -D HUD_MODE3: default = Mode 1, with HUD_MODE3 = Mode 3.
;
; What it draws (both modes):
;   - a BG fill so the screen is NOT black (Mode 1: a solid tile; Mode 3: an
;     8bpp ramp painted from CGRAM 0-239 ONLY — the contract's constraint).
;   - HUD readout via sf_obj_print "MOSAIC" at (x=16, y=8)  [top band]
;   - a numeric readout via sf_obj_num #7 at (x=80, y=8)
;   - "COLORMATH ADD" via sf_obj_print at (x=16, y=20)
;   These are OBJ palette 7 glyphs (CGRAM 240-255), rendered on top of the BG.
;
; OBSEL=$02 → OBJ name base VRAM word $4000 (per-page VRAM rule); glyph CHR is
; uploaded there by sf_obj_text_init under forced blank. The HUD's 16 pal-7
; colours go to CGRAM 240-255 by the same init.
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE low 3 bits == the mode
;   - OAM slots 0.. carry the HUD glyph sprites (tile != 0, palette field == 7,
;     Y in the top band) — structural cross-check
;   - a SCREENSHOT scan along the glyph row finds the glyph colour (pal-7 slot 1,
;     white) at the expected positions, in BOTH modes (the Python test asserts
;     the rendered pixels) — the legibility proof, incl. the 256-colour case
;   - CGRAM 240-255 hold the HUD palette (pal-7 entry 1 == white); in Mode 3,
;     CGRAM 0-239 hold the BG ramp (disjoint) — the palette-split proof
;
; Build: default 32KB lorom.cfg via the generic tests/%.sfc rule (Mode 1) and an
; explicit rule with -D HUD_MODE3 (Mode 3).
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "engine_state.inc"

ENGINE_A0      = $40
API_BLOCK_BASE = $60

DEBUG_BASE     = $7EE000
DBG_BGMODE     = $10
DBG_TM         = $11

.segment "CODE"

NMI:
    rti
NMI_STUB:
    rti

RESET:
    sf_coldstart
    jmp MAIN

    .include "bg_mode_engine.asm"

; The HUD primitive under test + its glyph data (include each ONCE per ROM).
.include "sf_obj_text_data.inc"
.include "sf_obj_text.inc"

; HUD strings (NUL-terminated ASCII).
hud_str1:  .byte "MOSAIC", 0
hud_str2:  .byte "COLORMATH ADD", 0

.ifdef HUD_MODE3
; --- Mode 3 BG1 8bpp chr: tile 0 transparent, tiles 1..4 a 0..239 ramp. Same
;     encoding as mode3_test but the ramp tops out at value ~239 so it stays in
;     CGRAM 0-239 (the HUD owns 240-255). 4 sub-tiles per 8bpp tile (16 B each).
bg_chr:
    .res 64, $00                    ; tile 0 transparent
    ; tile 1 (K=0, values 0..63)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 2 (K=1, values 64..127)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    ; tile 3 (K=2, values 128..191)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    ; tile 4 (K=3, values 192..223 — capped below 240 so the HUD owns 240-255)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $00, $0F, $00, $0F, $00
    .byte $0F, $00, $0F, $00, $0F, $00, $0F, $00
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
bg_chr_end:
.else
; --- Mode 1 BG1 4bpp: tile 0 transparent, tile 1 solid colour index 1 (blue). ---
bg_chr:
    .res 32, $00                    ; tile 0 transparent
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .res 16, $00                    ; tile 1: solid value 1 (planes 2,3 = 0)
bg_chr_end:
.endif

MAIN:
    rep #$30
    .a16
    .i16

    sf_debug_magic

    ; --- OAM cull (park all 128 sprites off-screen at Y=$F0) ---
    sep #$20
    .a8
    stz $2102
    stz $2103
    rep #$10
    .i16
    ldx #$0080
@oam_low:
    stz $2104
    lda #$F0
    sta $2104
    stz $2104
    stz $2104
    dex
    bne @oam_low
    ldx #$0020
@oam_hi:
    stz $2104
    dex
    bne @oam_hi
    rep #$20
    .a16

.ifdef HUD_MODE3
    ; --- Mode 3: CGRAM 0..239 = ramp (CGRAM[N]=N for N<240); 240..255 left to
    ;     the HUD (sf_obj_text_init writes those). Proves the palette split. ---
    sep #$20
    .a8
    stz $2121                       ; CGADD 0
    rep #$30
    .a16
    .i16
    ldx #$0000
@cg:
    sep #$20
    .a8
    txa
    sta $2122                       ; low byte = N
    stz $2122                       ; high byte = 0
    rep #$20
    .a16
    inx
    cpx #240                        ; N = 0..239 ONLY
    bcc @cg
.else
    ; --- Mode 1: BG palette 0 colour 1 = blue ($7C00) so the BG fill is visible
    ;     and DISTINCT from the HUD glyph colour (pal-7 white). ---
    sep #$20
    .a8
    stz $2121                       ; CGADD 0
    stz $2122
    stz $2122                       ; colour 0 black
    lda #$00
    sta $2122
    lda #$7C
    sta $2122                       ; colour 1 = $7C00 blue
    rep #$20
    .a16
.endif

    ; --- BG1 chr upload ---
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
.ifdef HUD_MODE3
    lda #$1000                      ; Mode 3 BG1 chr (like mode3_test)
    sta $2116
    ldx #$0000
@chr:
    sep #$20
    .a8
    lda f:bg_chr, x
    sta $2118
    inx
    lda f:bg_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(bg_chr_end - bg_chr)
    bcc @chr
.else
    lda #$2000                      ; Mode 1 BG1 chr base (BG12NBA $42 → word $2000)
    sta $2116
    ldx #$0000
@chr:
    sep #$20
    .a8
    lda f:bg_chr, x
    sta $2118
    inx
    lda f:bg_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(bg_chr_end - bg_chr)
    bcc @chr
.endif

    ; --- Zero scroll ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    rep #$20
    .a16

    ; --- gfxmode(mode) via the dispatcher ---
.ifdef HUD_MODE3
    lda #$0003
.else
    lda #$0001
.endif
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    ; --- Record shadow registers ---
    sep #$20
    .a8
    lda SHADOW_BGMODE
    sta f:DEBUG_BASE + DBG_BGMODE
    lda SHADOW_TM
    sta f:DEBUG_BASE + DBG_TM
    rep #$20
    .a16

    ; --- BG1 tilemap: paint a fill so the screen isn't black. The dispatcher
    ;     cleared the WRAM shadow only; we render with no engine NMI, so author
    ;     live VRAM at this mode's BG1SC address. ---
.ifdef HUD_MODE3
    ; Mode 3 BG1 tilemap word $0000: place ramp tiles 1..4 across rows 12..16.
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #$0000
    sta $2116
    ldx #$0000
@tm3_clear:
    stz $2118
    inx
    cpx #$0400
    bcc @tm3_clear
    ldy #12
@tm3_row:
    tya
    asl
    asl
    asl
    asl
    asl                             ; row*32
    clc
    adc #14
    sta $2116
    sep #$20
    .a8
    lda #$01
    sta $2118
    stz $2119
    lda #$02
    sta $2118
    stz $2119
    lda #$03
    sta $2118
    stz $2119
    lda #$04
    sta $2118
    stz $2119
    rep #$20
    .a16
    iny
    cpy #17
    bcc @tm3_row
.else
    ; Mode 1 BG1 tilemap word $5800 (@mode1_init's BG1SC): solid block of tile 1
    ; over rows 7..20, cols 4..27 — a blue field behind the HUD.
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #$5800
    sta $2116
    ldy #$0000
@tm1_row:
    ldx #$0000
@tm1_col:
    cpy #7
    bcc @tm1_off
    cpy #21
    bcs @tm1_off
    cpx #4
    bcc @tm1_off
    cpx #28
    bcs @tm1_off
    lda #$0001
    bra @tm1_w
@tm1_off:
    lda #$0000
@tm1_w:
    sta $2118
    inx
    cpx #32
    bcc @tm1_col
    iny
    cpy #32
    bcc @tm1_row
.endif

    ; =========================================================================
    ; THE HUD UNDER TEST — uploaded + placed under forced blank, screen still off.
    ; =========================================================================
    ; OBSEL: OBJ name base VRAM word $4000 (per-page VRAM rule) with the 8x8
    ; SMALL size pair — the HUD glyphs are 8x8 sprites. OBSEL = %000_00_010:
    ; size=%000 (8x8 small / 16x16 large), base=%010 (×$2000 words = $4000) = $02.
    ; (racer/mode7_flight use $62 = same $4000 base but 16x16/32x32, for their
    ; large sprites; the HUD overrides the size field to 8x8.)
    sep #$20
    .a8
    lda #$02
    sta $2101
    rep #$20
    .a16

    ; Upload glyph CHR (→ OBJ VRAM word $4000) + OBJ pal 7 (→ CGRAM 240-255).
    sf_obj_text_init               ; default base tile 1024 = word $4000

    ; Place the HUD runs. spr_clear first → the readout takes OBJ slots 0..
    spr_clear
    sf_obj_print hud_str1, #16, #8     ; "MOSAIC"  at top band (slots 0..5)
    sf_obj_num   #7,       #80, #8     ; numeric "00007" (slots 6..10)
    sf_obj_print hud_str2, #16, #20    ; "COLORMATH ADD" (slots 11..)

    ; Commit shadow OAM → hardware OAM. This static-render gate has no NMI/frame
    ; loop (engine_spr_resolve only ENQUEUES a VBlank DMA, which never drains
    ; here), so DMA the shadow OAM directly to OAM under forced blank: spr_clear
    ; already parked unused slots at Y=$F0, and our glyphs filled slots 0..N — no
    ; sort needed for a static HUD. Shadow OAM is 544 contiguous bytes
    ; ($7E:0300 low 512 + $7E:0500 hi 32) → one DMA to OAMDATA ($2104).
    sep #$20
    .a8
    stz $2102                       ; OAMADDR low = 0
    stz $2103                       ; OAMADDR high = 0 (OAM write ptr at entry 0)
    lda #$00
    sta $4300                       ; DMAP: CPU->PPU, fixed B-addr increment, 1 reg
    lda #$04
    sta $4301                       ; B-addr = $2104 (OAMDATA)
    ldx #$0300
    stx $4302                       ; A1T low/high = $0300
    lda #$7E
    sta $4304                       ; A1B bank = $7E (WRAM)
    ldx #544
    stx $4305                       ; DAS = 544 bytes (512 low + 32 hi tables)
    lda #$01
    sta $420B                       ; trigger DMA channel 0
    rep #$20
    .a16

    ; --- Screen on (full brightness) ---
    sep #$20
    .a8
    lda #$0F
    sta $2100
    rep #$20
    .a16

    ; --- Completion + spin ---
    lda #$0001
    sta f:DEBUG_BASE + $08
    sep #$20
    .a8
@spin:
    bra @spin

; --- engine code linked into the ROM ---
; The HUD primitive calls engine_spr / engine_spr_clear (via spr_clear and the
; helper subroutines); those live in sprite_engine.asm, whose resolve path
; references dma_scheduler.asm. (We don't call resolve, but ca65 links the whole
; module — dma_scheduler is its link partner, same as a1_sprite.asm.)
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
