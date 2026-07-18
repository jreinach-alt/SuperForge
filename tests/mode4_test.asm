; =============================================================================
; mode4_test — dispatcher Mode 4 (8bpp BG1 + offset-per-tile) render gate.
; =============================================================================
; Mode 4 combines Mode 3's richness (BG1 8bpp, 256-colour direct index) with
; Mode 2's OPT (BG3 tilemap = per-column H offset source, row 0 only). This ROM
; proves BOTH render: an 8bpp colour ramp strip AND a tile-column OPT warp that
; the controller toggles on/off.
;
; BG1 carries an 8bpp 256-colour ramp (so the 8bpp richness is on screen) laid
; out in a vertical-stripe-distinct pattern across tile columns (so the OPT
; column shift is visible). A held → column N H offset = N*8 px; released →
; flat. The OPT shadow is flushed to BG3 VRAM each NMI.
;
; Asset layout:
;   VRAM word $0000 BG1 tilemap   $0400 BG2   $0800 BG3 (OPT src)
;   VRAM word $1000 BG1 8bpp chr (tile 0 transparent, 1..4 ramp)
;   CGRAM 0..255    CGRAM[N] = N
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE $04, SHADOW_TM $13
;   - the 8bpp ramp strip renders >= 24 distinct colours (richness)
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

JOY_A          = $80            ; A = $4218 bit 7

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

; BG1 8bpp chr: tile 0 transparent, tiles 1..4 ramp (value = K*64 + R*8 + C).
bg1_chr:
    .res 64, $00                    ; tile 0
    ; tile 1 (K=0)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 2 (K=1)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    ; tile 3 (K=2)
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $55, $33, $55, $33, $55, $33, $55, $33
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $0F, $00, $0F, $FF, $0F, $00, $0F, $FF
    .byte $00, $00, $00, $00, $FF, $00, $FF, $00
    .byte $00, $FF, $00, $FF, $FF, $FF, $FF, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    ; tile 4 (K=3)
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

    ; --- CGRAM: CGRAM[N] = N ---
    sep #$20
    .a8
    stz $2121
    rep #$30
    .a16
    .i16
    ldx #$0000
@cg:
    sep #$20
    .a8
    txa
    sta $2122
    stz $2122
    rep #$20
    .a16
    inx
    cpx #$0100
    bcc @cg

    ; --- BG1 8bpp chr at word $1000 (320 B) ---
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
    cpx #$0140
    bcc @chr

    ; --- BG1 tilemap: clear, then a ramp row that REPEATS tiles 1..4 across
    ;     ALL 32 columns of rows 10..17 (so column-varying content fills the
    ;     screen width — OPT column shifts are visible everywhere). ---
    lda #$0000
    sta $2116
    ldx #$0000
@tm_clear:
    stz $2118
    inx
    cpx #$0400
    bcc @tm_clear

    ; rows 10..17: tile = (col & 3) + 1, repeating the 4 ramp tiles across width
    ldy #10
@row:
    ; word addr = row*32
    tya
    asl
    asl
    asl
    asl
    asl
    sta $2116
    ldx #$0000
@col:
    txa
    and #$0003
    inc                             ; tile 1..4
    sta $2118
    inx
    cpx #32
    bcc @col
    iny
    cpy #18
    bcc @row

    ; --- BG2 + BG3 tilemap zero ---
    lda #$0400
    sta $2116
    ldx #$0000
@bg2tm:
    stz $2118
    inx
    cpx #$0400
    bcc @bg2tm
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

    ; --- gfxmode(4) ---
    lda #$0004
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
