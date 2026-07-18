; =============================================================================
; mode6_test — dispatcher Mode 6 (hi-res 512 + offset-per-tile) render gate.
; =============================================================================
; Mode 6 = BG1 4bpp hi-res (Mode-5 main/sub pair encoding) + BG3 as the OPT
; (offset-per-tile) source; no BG2. This ROM proves BOTH: the hi-res 512-wide
; main/sub split renders (fine per-column detail), AND a controller-toggled OPT
; column warp shifts the hi-res content.
;
; BG1 carries column-varying hi-res content (alternating tile-pairs across tile
; columns) so an OPT column shift is visible. A held → column N H offset = N*8
; px; released → flat. The OPT shadow is flushed to BG3 VRAM each NMI.
;
; Asset layout (BG12NBA=$01 from @mode6_init: BG1 chr word $1000):
;   VRAM word $1000  BG1 4bpp chr — tile 0 solid white, tile 1 transparent,
;                    tile 2 solid (colour 2) → two distinct hi-res pairs
;   VRAM word $0000  BG1 tilemap (DoubleWidth/Height)
;   VRAM word $0800  BG3 tilemap = OPT source (flush target)
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE $06, SHADOW_TM $11
;   - the screenshot is 512 wide with high-frequency per-column detail
;   - frame-diff: A-held (warped) differs from A-released (flat); reverts
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

JOY_A          = $80

.segment "CODE"

NMI:
    rep #$30
    .a16
    .i16
    pha
    phx
    phy
    phb
    sep #$20
    .a8
    lda #$00
    pha
    plb
    lda $4210                       ; ACK NMI
    rep #$30
    .a16
    .i16
    jsr engine_offset_flush
    plb
    ply
    plx
    pla
    rti

NMI_STUB:
    rti

RESET:
    sf_coldstart
    jmp MAIN

    .include "bg_mode_engine.asm"
    .include "offset_engine.asm"

; BG1 4bpp chr: tile 0 solid white (val 1), tile 1 transparent, tile 2 solid
; (val 2). Tilemap entry E → main tile E, sub tile E+1.
bg1_chr:
    ; tile 0: solid value 1
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .res 16, $00
    ; tile 1: transparent
    .res 32, $00
    ; tile 2: solid value 2
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .res 16, $00
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

    ; --- CGRAM: 0 black, 1 white ($7FFF), 2 red ($001F) ---
    sep #$20
    .a8
    stz $2121
    stz $2122
    stz $2122
    lda #$FF
    sta $2122
    lda #$7F
    sta $2122                       ; 1: white
    lda #$1F
    sta $2122
    stz $2122                       ; 2: red
    rep #$20
    .a16

    ; --- BG1 chr at word $1000 (96 B = 3 tiles) ---
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
    cpx #$0060
    bcc @chr

    ; --- BG1 tilemap at word $0000: zero-fill 64×32, then rows 8..23 across
    ;     both submaps with entry = (col & 1) ? 0 : 2  (column-varying so OPT
    ;     shifts are visible). entry 0 → main tile0(white)/sub tile1(blank);
    ;     entry 2 → main tile2(red)/sub tile3(blank). ---
    lda #$0000
    sta $2116
    ldx #$0000
@tm_clear:
    stz $2118
    inx
    cpx #$0800
    bcc @tm_clear

    ; submap 0 rows 8..23
    lda #(8*32)
    sta $2116
    ldx #$0000
@fill0:
    txa
    and #$0001
    beq @e0a
    lda #$0000                      ; odd col → entry 0 (white pair)
    bra @w0
@e0a:
    lda #$0002                      ; even col → entry 2 (red pair)
@w0:
    sta $2118
    inx
    cpx #(16*32)
    bcc @fill0

    ; submap 1 rows 8..23 (word $0400)
    lda #($0400 + 8*32)
    sta $2116
    ldx #$0000
@fill1:
    txa
    and #$0001
    beq @e1a
    lda #$0000
    bra @w1
@e1a:
    lda #$0002
@w1:
    sta $2118
    inx
    cpx #(16*32)
    bcc @fill1

    ; --- BG3 tilemap (OPT source) at word $0800: zero ---
    lda #$0800
    sta $2116
    ldx #$0000
@bg3tm:
    stz $2118
    inx
    cpx #$0400
    bcc @bg3tm

    ; --- Zero scroll ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    rep #$20
    .a16

    ; --- gfxmode(6) ---
    lda #$0006
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    sep #$20
    .a8
    lda SHADOW_BGMODE
    sta f:DEBUG_BASE + DBG_BGMODE
    lda SHADOW_TM
    sta f:DEBUG_BASE + DBG_TM

    ; --- Screen on + NMI + auto-joypad ---
    lda #$0F
    sta $2100
    lda #$81
    sta $4200
    cli
    rep #$20
    .a16

    lda #$0001
    sta f:DEBUG_BASE + $08

game_loop:
    wai
    sep #$20
    .a8
@joy_wait:
    lda $4212
    and #$01
    bne @joy_wait
    lda $4218
    and #JOY_A
    rep #$20
    .a16
    bne @warp_on

    ; warp OFF
    ldx #$0000
@off_loop:
    lda #$0001
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    txa
    sta API_BLOCK_BASE + 4
    stz API_BLOCK_BASE + 6
    stz API_BLOCK_BASE + 8
    stz API_BLOCK_BASE + 10
    stz API_BLOCK_BASE + 12
    stz API_BLOCK_BASE + 14
    phx
    jsr engine_scroll_column
    plx
    inx
    cpx #$0020
    bcc @off_loop
    bra game_loop

@warp_on:
    ldx #$0000
@on_loop:
    lda #$0001
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    txa
    sta API_BLOCK_BASE + 4
    stz API_BLOCK_BASE + 6
    txa
    asl
    asl
    asl                             ; dx = col * 8
    sta API_BLOCK_BASE + 8
    stz API_BLOCK_BASE + 10
    stz API_BLOCK_BASE + 12
    stz API_BLOCK_BASE + 14
    phx
    jsr engine_scroll_column
    plx
    inx
    cpx #$0020
    bcc @on_loop
    jmp game_loop
