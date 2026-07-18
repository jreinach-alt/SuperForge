; =============================================================================
; mode2_test — dispatcher Mode 2 (offset-per-tile / OPT) render gate.
; =============================================================================
; Drives engine_gfxmode(2) + the offset-per-tile engine (offset_engine.asm) and
; proves the OPT warp RENDERS. Mode 2 repurposes BG3's tilemap as a per-column
; horizontal-offset source merged into BG1's H-scroll. BG1 carries a 2D
; checkerboard (content varies across BOTH axes) so a tile-granular column shift
; is visible (a uniform tilemap looks identical under any offset — see the
; offset_engine header).
;
; State cycle (driven by controller input, OPT on vs off):
;   A released → all column offsets zero  → flat checkerboard
;   A held     → column N offset = N*8 px → stepped tile-column warp
; The offset shadow is flushed to BG3 VRAM in the NMI each frame; the test
; frame-diffs the two rendered states.
;
; Asset layout:
;   VRAM word $0000 BG1 tilemap   word $0400 BG2   word $0800 BG3 (OPT src)
;   VRAM word $1000 BG1+BG2 4bpp chr
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE $02, SHADOW_TM $13
;   - frame-diff: the A-held (warped) frame differs measurably from the
;     A-released (flat) frame across the checkerboard region
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

JOY_A_HI       = $80            ; A button = JOY1H ($4218 high byte) bit 7

.segment "CODE"

; NMI: ack + flush the OPT shadow buffer to BG3 VRAM.
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

; BG1 chr: tile 0 transparent, tile 1 red (value 1), tile 2 blue (value 2).
bg1_chr:
    .res 32, $00                    ; tile 0
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .res 16, $00                    ; tile 1: value 1
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF
    .res 16, $00                    ; tile 2: value 2
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

    ; --- CGRAM: 0 black, 1 red ($001F), 2 blue ($7C00) ---
    sep #$20
    .a8
    stz $2121
    stz $2122
    stz $2122
    lda #$1F
    sta $2122
    stz $2122                       ; 1: red
    stz $2122
    lda #$7C
    sta $2122                       ; 2: blue
    rep #$20
    .a16

    ; --- BG1 chr at word $1000 (96 B) ---
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

    ; --- BG1 tilemap: 2D checkerboard tile = ((row ^ col) & 1) + 1 ---
    lda #$0000
    sta $2116
    ldx #$0000
@bg1tm:
    txa
    and #$001F                      ; col
    sta $00
    txa
    lsr
    lsr
    lsr
    lsr
    lsr                             ; row
    eor $00
    and #$0001
    inc                             ; tile 1 or 2
    sta $2118
    inx
    cpx #$0400
    bcc @bg1tm

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
    stz $210F
    stz $210F
    stz $2110
    stz $2110
    rep #$20
    .a16

    ; --- gfxmode(2) ---
    lda #$0002
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
    lda #$81                        ; NMI on + auto-joypad
    sta $4200
    cli
    rep #$20
    .a16

    lda #$0001
    sta f:DEBUG_BASE + $08

; --- Game loop: A held → ramp offsets; released → zero. NMI flushes. ---
game_loop:
    wai                             ; wait for NMI (auto-joypad started)

    ; Wait for auto-joypad to finish ($4212 bit 0 = 1 while in progress).
    sep #$20
    .a8
@joy_wait:
    lda $4212
    and #$01
    bne @joy_wait

    lda $4218                       ; P1 low byte (A = bit 7 of the 16-bit word)
    and #JOY_A_HI
    rep #$20
    .a16
    bne @warp_on

    ; --- warp OFF: all column offsets = 0 ---
    ldx #$0000
@off_loop:
    lda #$0001
    sta API_BLOCK_BASE + 0          ; layer BG1
    stz API_BLOCK_BASE + 2
    txa
    sta API_BLOCK_BASE + 4          ; col
    stz API_BLOCK_BASE + 6
    stz API_BLOCK_BASE + 8          ; dx = 0
    stz API_BLOCK_BASE + 10
    stz API_BLOCK_BASE + 12         ; dy = 0
    stz API_BLOCK_BASE + 14
    phx
    jsr engine_scroll_column
    plx
    inx
    cpx #$0020
    bcc @off_loop
    bra game_loop

@warp_on:
    ; --- warp ON: column N offset dx = N*8 (one tile column per step) ---
    ldx #$0000
@on_loop:
    lda #$0001
    sta API_BLOCK_BASE + 0
    stz API_BLOCK_BASE + 2
    txa
    sta API_BLOCK_BASE + 4          ; col
    stz API_BLOCK_BASE + 6
    txa
    asl
    asl
    asl                             ; dx = col * 8
    sta API_BLOCK_BASE + 8
    stz API_BLOCK_BASE + 10
    stz API_BLOCK_BASE + 12         ; dy = 0
    stz API_BLOCK_BASE + 14
    phx
    jsr engine_scroll_column
    plx
    inx
    cpx #$0020
    bcc @on_loop
    jmp game_loop
