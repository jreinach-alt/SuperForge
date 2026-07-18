; =============================================================================
; mode0_test — run-gate for the all-modes gfxmode dispatcher, Mode 0 path.
; =============================================================================
; Drives engine_gfxmode(0) (the bg_mode_engine.asm dispatcher) and proves the
; Mode-0 PPU setup RENDERS four independent BG layers. Four 2bpp BG layers, one
; per screen quadrant, each in its own colour, so a screenshot pixel-sample of
; each quadrant confirms independent layer compositing.
;
; All content is authored directly via the PPU ports under the coldstart forced
; blank; the dispatcher writes BGMODE/SC/NBA/TM; this ROM turns the screen on.
;
; Done-condition (rendered OUTPUT only):
;   - boots ($7E:E000 == "SFDB"); completion flag $7E:E008 == 1
;   - SHADOW_BGMODE == $00, SHADOW_TM == $1F (4 BGs + OBJ)
;   - four screen quadrants sample red / green / blue / yellow
;   - CGRAM holds the four sub-palette ramps (bytes verified)
;
; Asset layout:
;   VRAM word $0000  BG1 tilemap   word $0400 BG2   $0800 BG3   $0C00 BG4
;   VRAM word $1000  shared 2bpp chr (tile 0 transparent, tile 1 = colour 3)
;   CGRAM 0-3 red ramp, 32-35 green, 64-67 blue, 96-99 yellow
;
; Build: default 32KB lorom.cfg via the generic tests/%.sfc rule.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
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
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    jmp MAIN

    .include "bg_mode_engine.asm"

; -----------------------------------------------------------------------------
; Shared 2bpp chr: tile 0 = transparent, tile 1 = solid colour index 3.
; -----------------------------------------------------------------------------
mode0_chr_data:
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
mode0_chr_data_end:

; -----------------------------------------------------------------------------
; MAIN
; -----------------------------------------------------------------------------
MAIN:
    rep #$30
    .a16
    .i16

    sf_debug_magic

    ; --- OAM cull: park all 128 sprites off-screen (Y=$F0) ---
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

    ; --- VRAM: shared chr at word $1000 (32 bytes = 2 tiles × 16) ---
    sep #$20
    .a8
    lda #$80
    sta $2115                       ; VMAIN: +1 after high byte
    rep #$20
    .a16
    lda #$1000
    sta $2116
    ldx #$0000
@upload_chr:
    sep #$20
    .a8
    lda f:mode0_chr_data, x
    sta $2118
    inx
    lda f:mode0_chr_data, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #$0020
    bcc @upload_chr

    ; --- BG1 tilemap (word $0000): upper-left quadrant tile 1 ---
    lda #$0000
    sta $2116
    jsr fill_ul
    ; --- BG2 tilemap (word $0400): upper-right ---
    lda #$0400
    sta $2116
    jsr fill_ur
    ; --- BG3 tilemap (word $0800): lower-left ---
    lda #$0800
    sta $2116
    jsr fill_ll
    ; --- BG4 tilemap (word $0C00): lower-right ---
    lda #$0C00
    sta $2116
    jsr fill_lr

    ; --- CGRAM: 4 sub-palette ramps. coldstart already zeroed CGRAM. ---
    sep #$20
    .a8
    ; BG1 palette @ CGRAM 0 — RED ramp
    lda #$00
    sta $2121
    stz $2122
    stz $2122                       ; 0: $0000
    lda #$0A
    sta $2122
    stz $2122                       ; 1: $000A
    lda #$14
    sta $2122
    stz $2122                       ; 2: $0014
    lda #$1F
    sta $2122
    stz $2122                       ; 3: $001F bright red
    ; BG2 palette @ CGRAM 32 — GREEN ramp
    lda #$20
    sta $2121
    stz $2122
    stz $2122
    lda #$40
    sta $2122
    lda #$01
    sta $2122                       ; $0140
    lda #$80
    sta $2122
    lda #$02
    sta $2122                       ; $0280
    lda #$E0
    sta $2122
    lda #$03
    sta $2122                       ; $03E0 bright green
    ; BG3 palette @ CGRAM 64 — BLUE ramp
    lda #$40
    sta $2121
    stz $2122
    stz $2122
    lda #$00
    sta $2122
    lda #$28
    sta $2122                       ; $2800
    lda #$00
    sta $2122
    lda #$50
    sta $2122                       ; $5000
    lda #$00
    sta $2122
    lda #$7C
    sta $2122                       ; $7C00 bright blue
    ; BG4 palette @ CGRAM 96 — YELLOW ramp (R+G)
    lda #$60
    sta $2121
    stz $2122
    stz $2122
    lda #$4A
    sta $2122
    lda #$01
    sta $2122                       ; $014A
    lda #$94
    sta $2122
    lda #$02
    sta $2122                       ; $0294
    lda #$FF
    sta $2122
    lda #$03
    sta $2122                       ; $03FF bright yellow
    rep #$20
    .a16

    ; --- Zero scroll registers (PPU scroll is undefined at reset) ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    rep #$20
    .a16

    ; --- gfxmode(0) ---
    lda #$0000
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

    ; --- Screen on ---
    lda #$0F
    sta $2100

    ; --- Completion flag + spin ---
    rep #$20
    .a16
    lda #$0001
    sta f:DEBUG_BASE + $08
    sep #$20
    .a8
@spin:
    bra @spin


; --- Quadrant fillers. Each writes a 32x32 tilemap, tile 1 in its quadrant. ---
fill_ul:
    .a16
    .i16
    ldy #$0000
@r:
    ldx #$0000
@c:
    cpy #14
    bcs @off
    cpx #16
    bcs @off
    lda #$0001
    bra @w
@off:
    lda #$0000
@w:
    sta $2118
    inx
    cpx #32
    bcc @c
    iny
    cpy #32
    bcc @r
    rts

fill_ur:
    .a16
    .i16
    ldy #$0000
@r:
    ldx #$0000
@c:
    cpy #14
    bcs @off
    cpx #16
    bcc @off
    lda #$0001
    bra @w
@off:
    lda #$0000
@w:
    sta $2118
    inx
    cpx #32
    bcc @c
    iny
    cpy #32
    bcc @r
    rts

fill_ll:
    .a16
    .i16
    ldy #$0000
@r:
    ldx #$0000
@c:
    cpy #14
    bcc @off
    cpy #28
    bcs @off
    cpx #16
    bcs @off
    lda #$0001
    bra @w
@off:
    lda #$0000
@w:
    sta $2118
    inx
    cpx #32
    bcc @c
    iny
    cpy #32
    bcc @r
    rts

fill_lr:
    .a16
    .i16
    ldy #$0000
@r:
    ldx #$0000
@c:
    cpy #14
    bcc @off
    cpy #28
    bcs @off
    cpx #16
    bcc @off
    lda #$0001
    bra @w
@off:
    lda #$0000
@w:
    sta $2118
    inx
    cpx #32
    bcc @c
    iny
    cpy #32
    bcc @r
    rts
