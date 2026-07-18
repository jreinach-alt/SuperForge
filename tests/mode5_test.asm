; =============================================================================
; mode5_test — dispatcher Mode 5 (hi-res 512×224, line-doubled) render gate.
; =============================================================================
; Drives engine_gfxmode(5) and proves the hi-res 512-wide path RENDERS. Mode 5
; doubles horizontal resolution: each tilemap entry fetches a MAIN tile (writes
; odd output columns) and a SUB tile (writes even output columns), so a 16-px-
; wide on-screen glyph is two 8×8 tiles. We hand-author a tile PAIR whose main
; and sub halves differ — main = solid (colour 1), sub = transparent — so the
; rendered 512-wide frame shows fine per-column detail (adjacent output columns
; differ), which is impossible in a 256-wide mode (those line-double each
; column). That high-frequency horizontal detail is the 512-px proof.
;
; Asset layout (BG12NBA=$31 from @mode5_init: BG1 chr word $1000):
;   VRAM word $1000  BG1 4bpp chr — tile 0 = solid colour 1 (main),
;                    tile 1 = transparent (sub)
;   VRAM word $0000  BG1 tilemap (64×32 DoubleWidth), block of entry 0
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE $05, SHADOW_TM $13
;   - the screenshot is 512 wide
;   - inside the content block, horizontally-adjacent output columns differ
;     frequently (the main/sub per-column split — 512-px detail)
;
; Build: default 32KB lorom.cfg via the generic tests/%.sfc rule.
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

; BG1 4bpp chr: tile 0 = solid colour 1 (the MAIN tile), tile 1 = transparent
; (the SUB tile). The main/sub pair renders main on odd output cols, sub
; (transparent) on even output cols → a 1-px vertical stripe at 512-wide.
bg1_chr:
    ; tile 0: solid value 1 (plane 0 = $FF every row, planes 1..3 = 0)
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .res 16, $00
    ; tile 1: transparent
    .res 32, $00
bg1_chr_end:

MAIN:
    rep #$30
    .a16
    .i16

    sf_debug_magic

    ; --- OAM cull ---
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

    ; --- CGRAM: 0 black, 1 white ($7FFF) ---
    sep #$20
    .a8
    stz $2121
    stz $2122
    stz $2122                       ; 0: black
    lda #$FF
    sta $2122
    lda #$7F
    sta $2122                       ; 1: white
    rep #$20
    .a16

    ; --- BG1 chr at word $1000 (64 B = 2 tiles) ---
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #$1000
    sta $2116
    ldx #$0000
@chr:
    sep #$20
    .a8
    lda f:bg1_chr, x
    sta $2118
    inx
    lda f:bg1_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #$0040
    bcc @chr

    ; --- BG1 tilemap at word $0000 (DoubleWidth 64×32): zero-fill, then a
    ;     block of entry 0 (main tile 0 + auto sub tile 1) across rows 8..23
    ;     cols 0..63. Entry value = $0000 → main tile 0, sub tile 1. ---
    lda #$0000
    sta $2116
    ldx #$0000
@tm_clear:
    stz $2118
    inx
    cpx #$0800                      ; 64×32 entries (DoubleWidth)
    bcc @tm_clear

    ; Fill rows 8..23 (both submaps). Tilemap is 64×32: cols 0..31 in submap 0
    ; (word row*32 + col), cols 32..63 in submap 1 (word $0400 + row*32 + col).
    ; Simplest: write entry 0 to the whole 64×32 region rows 8..23.
    ; Submap 0 rows 8..23:
    lda #(8*32)
    sta $2116
    ldx #$0000
@fill0:
    lda #$0000
    sta $2118                       ; entry 0 = main tile 0 + sub tile 1
    inx
    cpx #(16*32)                    ; 16 rows × 32 cols
    bcc @fill0
    ; Submap 1 (word $0400) rows 8..23:
    lda #($0400 + 8*32)
    sta $2116
    ldx #$0000
@fill1:
    lda #$0000
    sta $2118
    inx
    cpx #(16*32)
    bcc @fill1

    ; --- Zero scroll ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    stz $210F
    stz $210F
    stz $2110
    stz $2110
    rep #$20
    .a16

    ; --- gfxmode(5) ---
    lda #$0005
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    sep #$20
    .a8
    lda SHADOW_BGMODE
    sta f:DEBUG_BASE + DBG_BGMODE
    lda SHADOW_TM
    sta f:DEBUG_BASE + DBG_TM

    ; --- Screen on ---
    lda #$0F
    sta $2100

    rep #$20
    .a16
    lda #$0001
    sta f:DEBUG_BASE + $08
    sep #$20
    .a8
@spin:
    bra @spin
