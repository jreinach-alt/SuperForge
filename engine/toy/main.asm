; SuperForge allocator toy — the good-case proof ROM.
;
; Purely exercises the machinery: builds against the allocator-emitted
; engine_state_toy.inc and references resources ONLY through emitted symbols
; + hardware I/O ports — the no-literals gate scans this file. Init is
; by-contract (exactly the declared claims), never blanket. Boots on
; MesenRunner; the test reads the rendered VRAM/CGRAM output at the emitted
; addresses (from symbol_map.json) and the WRAM signature.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE TOY"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "engine_state_toy.inc"     ; GENERATED — the scene's map
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

NMI_STUB:
NMI:
    rti

MAIN:
    .a16
    .i16
    ; ---- init contract (scene entry): zero exactly the declared claims ----
    stz z:ES_FEAT_A_POS             ; feat_a_pos, 4 B
    stz z:ES_FEAT_A_POS+2
    stz z:ES_FEAT_B_CURSOR          ; feat_b_cursor, 2 B

    ; ---- global user state: the toy game's power-on values ----
    lda #0
    sta f:US_SCORE_LONG             ; score = 0
    sep #$20
    .a8
    lda #3
    sta f:US_LIVES_LONG             ; lives = 3
    rep #$20
    .a16

    ; ---- scene user state ----
    lda #64
    sta z:US_PLAYER_X
    lda #48
    sta z:US_PLAYER_Y

    ; ---- VRAM upload (under forced blank), all bases allocator-emitted ----
    sep #$20
    .a8
    lda #$80
    sta $2115                       ; VMAIN: word step after $2119 write
    rep #$20
    .a16
    ; init contract covers everything this scene DISPLAYS: power-on VRAM is
    ; random, so the whole 32x32 map + tile 0 are cleared before use — never
    ; rely on the emulator to hand us zeroed video memory.
    ldx #ES_V_FEAT_A_CHR            ; tile #0: fully transparent (backdrop)
    stx $2116                       ; VMADD
    lda #$0000
    ldy #8
@chr0:
    .a16
    sta $2118                       ; VMDATA word
    dey
    bne @chr0

    ldx #ES_V_FEAT_A_MAP            ; whole map -> tile 0 (transparent)
    stx $2116
    lda #$0000
    ldy #ES_V_FEAT_A_MAP_WORDS
@mapclr:
    .a16
    sta $2118
    dey
    bne @mapclr

    ldx #ES_V_FEAT_A_CHR + 8        ; tile #1 of feat_a's CHR (8 words, 2bpp)
    stx $2116
    lda #$FFFF                      ; solid color-3 tile: both planes set
    ldy #8
@chr:
    .a16
    sta $2118
    dey
    bne @chr

    ldx #ES_V_FEAT_A_MAP            ; tilemap row 0: 32 entries of tile #1
    stx $2116
    lda #$0001                      ; tile 1, palette 0
    ldy #32
@map:
    .a16
    sta $2118
    dey
    bne @map

    ldx #ES_V_FEAT_B_FONT           ; marker word inside feat_b's font region
    stx $2116
    lda #$BEEF
    sta $2118

    ; ---- CGRAM: feat_a's sub-palette at the emitted word index ----
    sep #$20
    .a8
    lda #ES_C_FEAT_A_PAL
    sta $2121                       ; CGADD
    ; CGDATA ($2122) is write-twice: low byte then high byte per color
    lda #<$6000                     ; color 0: blue backdrop (BGR555 B=24)
    sta $2122
    lda #>$6000
    sta $2122
    lda #<$001F                     ; color 1: red
    sta $2122
    lda #>$001F
    sta $2122
    lda #<$03E0                     ; color 2: green
    sta $2122
    lda #>$03E0
    sta $2122
    lda #<$7FFF                     ; color 3: white (the tile's color)
    sta $2122
    lda #>$7FFF
    sta $2122

    ; ---- display: Mode 0, BG1 map/CHR bases from the emitted symbols ----
    lda #$00
    sta $2105                       ; BGMODE: mode 0
    lda #<((ES_V_FEAT_A_MAP >> 10) << 2)
    sta $2107                       ; BG1SC: 32x32 map at the emitted base
    lda #<(ES_V_FEAT_A_CHR >> 12)
    sta $210B                       ; BG12NBA: BG1 CHR at the emitted base
    lda #$01
    sta $212C                       ; TM: BG1 on
    stz $210D                       ; BG1HOFS = 0 (write-twice)
    stz $210D
    stz $210E                       ; BG1VOFS = 0 (write-twice)
    stz $210E
    lda #$0F
    sta $2100                       ; INIDISP: screen on, full brightness
    rep #$20
    .a16

    ; ---- boot signature + heartbeat in the user scratch buffer ----
    lda #$4653                      ; 'S','F' (little-endian word)
    sta f:US_SCRATCH_LONG
    lda #$4B4F                      ; 'O','K'
    sta f:US_SCRATCH_LONG+2
    lda #0                          ; heartbeat: write before first read
    sta f:US_SCRATCH_LONG+4         ; (stz has no abs-long form)

@spin:
    .a16
    lda f:US_SCRATCH_LONG+4
    inc a
    sta f:US_SCRATCH_LONG+4
    bra @spin
