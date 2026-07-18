; =============================================================================
; mode1_test — Mode-1-via-dispatcher smoke (proves the @mode1_init superset).
; =============================================================================
; The kit's racer / mode7_flight rails reach Mode 1 through the bg_engine.asm
; STUB. This ROM instead drives the all-modes dispatcher (bg_mode_engine.asm)
; via engine_gfxmode(1) and proves the ported @mode1_init produces a working
; Mode 1: the Mode-1 BG registers are set (SHADOW_TM, BGMODE low 3 bits == 1)
; AND a BG1 tile actually RENDERS at the Mode-1 tilemap address.
;
; @mode1_init clears the WRAM shadow tilemaps + marks them dirty for the engine
; NMI DMA; this smoke runs no engine frame loop, so it authors the BG1 chr +
; tilemap DIRECTLY in VRAM (chr word $2000, tilemap word $5800 — the Mode-1
; layout @mode1_init programs into BG12NBA/BG1SC). The dispatcher's register
; writes are what make those VRAM addresses the live BG1 source.
;
; Done-condition (rendered OUTPUT + structural):
;   - boots; completion flag $7E:E008 == 1
;   - SHADOW_BGMODE low 3 bits == 1 (Mode 1; bit 3 = BG3 priority, set by the
;     port to match the stub); SHADOW_TM == $17 (OBJ+BG1+BG2+BG3)
;   - a green BG1 tile renders in the centre of the screen (screenshot pixel)
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

; Two 4bpp tiles: tile 0 = transparent, tile 1 = solid colour index 1.
bg1_tile:
    .res 32, $00                    ; tile 0: transparent
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .res 16, $00                    ; tile 1: solid value 1

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

    ; --- CGRAM: BG palette 0 colour 1 = green ($03E0) ---
    sep #$20
    .a8
    stz $2121                       ; CGADD 0
    stz $2122
    stz $2122                       ; colour 0: black
    lda #$E0
    sta $2122
    lda #$03
    sta $2122                       ; colour 1: $03E0 green
    rep #$20
    .a16

    ; --- BG1 chr at word $2000 (Mode-1 BG1 chr base = BG12NBA $42) ---
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #$2000
    sta $2116
    ldx #$0000
@chr:
    sep #$20
    .a8
    lda f:bg1_tile, x
    sta $2118
    inx
    lda f:bg1_tile, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #$0040                      ; 64 bytes = 2 tiles × 32
    bcc @chr

    ; --- Zero scroll ---
    sep #$20
    .a8
    stz $210D
    stz $210D
    stz $210E
    stz $210E
    rep #$20
    .a16

    ; --- gfxmode(1) via the dispatcher (@mode1_init superset path) ---
    lda #$0001
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

    ; --- Author the BG1 tilemap DIRECTLY in VRAM at word $5800 (the Mode-1
    ;     BG1SC address @mode1_init set). gfxmode only cleared the WRAM shadow;
    ;     we render without the engine NMI DMA, so write live VRAM here.
    ;     Fill a 16x14 centre block with tile 1 (palette 0). ---
    sep #$20
    .a8
    lda #$80
    sta $2115
    rep #$20
    .a16
    lda #$5800                      ; BG1 tilemap base
    sta $2116
    ldy #$0000                      ; row
@tm_row:
    ldx #$0000                      ; col
@tm_col:
    ; tile 1 in rows 7..20, cols 8..23; else tile 0 (transparent).
    cpy #7
    bcc @off
    cpy #21
    bcs @off
    cpx #8
    bcc @off
    cpx #24
    bcs @off
    lda #$0001
    bra @w
@off:
    lda #$0000
@w:
    sta $2118
    inx
    cpx #32
    bcc @tm_col
    iny
    cpy #32
    bcc @tm_row

    ; --- Screen on ---
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
