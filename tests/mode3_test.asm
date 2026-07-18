; =============================================================================
; mode3_test — dispatcher Mode 3 (256-colour / 8bpp BG1) render gate.
; =============================================================================
; Drives engine_gfxmode(3) and proves the Mode-3 8bpp path RENDERS a smooth
; 256-colour ramp. BG1 is 8bpp (direct CGRAM index). CGRAM is filled so
; CGRAM[N] = N (little-endian BGR555), and four 8bpp ramp tiles place pixel
; values 0..255 across a 32-pixel-wide strip. A screenshot sample across the
; strip must show a smooth left-to-right colour gradient (many distinct
; colours), which only happens if the 8bpp tiles + 256-entry CGRAM render.
;
; Asset layout:
;   VRAM word $0000  BG1 tilemap (32x32)
;   VRAM word $1000  BG1 chr (5 × 8bpp tiles: tile 0 transparent, 1..4 ramp)
;   CGRAM 0..255     CGRAM[N] = N
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE == $03, SHADOW_TM $13
;   - the on-screen ramp strip shows >= 24 distinct colours, monotonically
;     varied across its width (smooth ramp, not a flat block)
;   - CGRAM mid/high entries match the CGRAM[N]=N rule (bytes verified)
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

; -----------------------------------------------------------------------------
; BG1 8bpp chr: tile 0 transparent, tiles 1..4 ramp (pixel value = K*64+R*8+C).
; 8bpp encoding: four 16-B plane-pair sub-tiles. base = K*64 + R*8 (multiple
; of 8), V_C = base + C, C in 0..7.  Plane 0 → $55, plane 1 → $33, plane 2 →
; $0F; planes 3..7 constant = bit P of base.
; -----------------------------------------------------------------------------
bg1_chr:
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
    ; tile 4 (K=3, values 192..255)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
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

    ; --- CGRAM: CGRAM[N] = N for N = 0..255 ---
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
    cpx #$0100
    bcc @cg

    ; --- BG1 chr at word $1000 (320 bytes = 5 tiles) ---
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
    cpx #$0140                      ; 320 bytes
    bcc @chr

    ; --- BG1 tilemap at word $0000: clear, then 4 ramp tiles on rows 12..15
    ;     cols 14..17 (a 32x32 px block centred-ish). 4 stacked rows make the
    ;     strip taller for robust sampling. ---
    lda #$0000
    sta $2116
    ldx #$0000
@tm_clear:
    stz $2118
    inx
    cpx #$0400
    bcc @tm_clear

    ; place ramp tiles 1..4 at (col 14..17) across rows 12..15.
    ldy #12                         ; row
@place_row:
    ; tilemap word addr = row*32 + 14
    tya
    asl
    asl
    asl
    asl
    asl                             ; row * 32
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
    cpy #16
    bcc @place_row

    ; --- Zero scroll ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    rep #$20
    .a16

    ; --- gfxmode(3) ---
    lda #$0003
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
