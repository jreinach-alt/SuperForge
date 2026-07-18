; =============================================================================
; opt_curve_test — OPT curve-variety render gate (sine / triangle / saw / noise).
; =============================================================================
; Forks mode2_test. Proves the offset-per-tile WAVE engine can warp BG1 with
; FOUR different curves (engine_scroll_wave_curve), not just sine, and that each
; curve produces a VISIBLY DISTINCT column-offset pattern on the rendered frame.
;
; Same 2D checkerboard BG1 as mode2_test (content varies across both axes so a
; tile-granular column shift is visible). Instead of a hand-ramped offset, the
; wave engine builds a 256-entry signed curve LUT scaled to +/-amp and samples
; it per column. speed = 0 freezes the phase, so each curve renders a STABLE,
; deterministic static warp — the frame differs per curve only because the LUT
; (and therefore the per-column offset pattern) differs.
;
; Curve select (controller, mutually exclusive; checked in priority order):
;   none → curve 0 SINE      A → curve 1 TRIANGLE
;   B    → curve 2 SAWTOOTH   X → curve 3 NOISE
; engine_scroll_wave_curve is called only when the selected curve CHANGES
; (it resets phase); the NMI tick rewrites the shadow from the frozen LUT each
; frame and engine_offset_flush DMAs it to BG3 VRAM.
;
; Asset layout (identical to mode2_test):
;   VRAM word $0000 BG1 tilemap   $0400 BG2   $0800 BG3 (OPT src)
;   VRAM word $1000 BG1+BG2 4bpp chr
;
; Done-condition (rendered OUTPUT):
;   - boots; completion flag $7E:E008 == 1; SHADOW_BGMODE $02, SHADOW_TM $13
;   - frame-diff: each curve's warped frame differs measurably from the others
;     (the column-offset pattern visibly changes per curve)
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
DBG_CURVE      = $12            ; last applied curve id (telemetry)

; 16-bit auto-joypad word at $4218 (JOY1L | JOY1H<<8):
;   B=15  Y=14  Sel=13  Sta=12  Up=11  Dn=10  Lt=9  Rt=8
;   A=7   X=6   L=5    R=4
JOY_A          = $0080         ; A → triangle
JOY_B          = $8000         ; B → sawtooth
JOY_X          = $0040         ; X → noise

; Wave params. speed=0 freezes the phase → deterministic static warp per curve.
; amp=64 → peak offset +/-64 px = 8 tile columns (well past the 8-px OPT mask).
; freq=8 spreads one curve period across the 32 visible columns.
WAVE_AMP       = 64
WAVE_FREQ      = 8
WAVE_SPEED     = 0

LAST_CURVE     = $7EE020        ; 1 B: previously applied curve (init sentinel)

.segment "CODE"

; NMI: ack + advance the wave (frozen, speed=0) + flush the OPT shadow to VRAM.
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
    jsr engine_scroll_wave_tick     ; rewrite shadow from the curve LUT
    jsr engine_offset_flush         ; DMA shadow → BG3 VRAM
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

; sin_lut must be visible BEFORE offset_engine.asm so the wave/curve path
; (gated on SIN_LUT_PROVIDED) compiles in. mode7_sin_lut.inc sets the guard.
sin_lut_data:
    .include "mode7_sin_lut.inc"
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

    ; --- Seed LAST_CURVE with a sentinel ($FF) so frame 1 forces a build ---
    lda #$FF
    sta f:LAST_CURVE
    rep #$20
    .a16

    ; --- Screen on + NMI + auto-joypad ---
    sep #$20
    .a8
    lda #$0F
    sta $2100
    lda #$81                        ; NMI on + auto-joypad
    sta $4200
    cli
    rep #$20
    .a16

    lda #$0001
    sta f:DEBUG_BASE + $08

; --- Game loop: select curve by button; rebuild LUT only on change. NMI ticks. ---
game_loop:
    wai                             ; wait for NMI (auto-joypad started)

    ; Wait for auto-joypad to finish ($4212 bit 0 = 1 while in progress).
    sep #$20
    .a8
@joy_wait:
    lda $4212
    and #$01
    bne @joy_wait
    rep #$20
    .a16

    ; --- Decide curve from the 16-bit joypad word (priority A > B > X > none) ---
    lda $4218                       ; full 16-bit auto-joypad state
    sta $02                         ; stash joypad word (DP scratch, main-thread)
    ldy #0                          ; Y = selected curve id (default sine)
    lda $02
    and #JOY_A
    beq @chk_b
    ldy #WAVE_CURVE_TRI
    bra @curve_picked
@chk_b:
    lda $02
    and #JOY_B
    beq @chk_x
    ldy #WAVE_CURVE_SAW
    bra @curve_picked
@chk_x:
    lda $02
    and #JOY_X
    beq @curve_picked               ; none held → Y stays 0 (sine)
    ldy #WAVE_CURVE_NOISE
@curve_picked:

    ; --- Only rebuild when the selection changed (rebuild resets phase). ---
    sep #$20
    .a8
    tya                             ; A8 = selected curve id (Y low byte)
    cmp f:LAST_CURVE
    beq @no_change
    sta f:LAST_CURVE
    sta f:DEBUG_BASE + DBG_CURVE
    rep #$20
    .a16

    ; Configure the wave with the selected curve.
    lda #$0001
    sta API_BLOCK_BASE + 0          ; layer BG1
    stz API_BLOCK_BASE + 2
    lda #WAVE_AMP
    sta API_BLOCK_BASE + 4          ; amp
    stz API_BLOCK_BASE + 6
    lda #WAVE_FREQ
    sta API_BLOCK_BASE + 8          ; freq
    stz API_BLOCK_BASE + 10
    lda #WAVE_SPEED
    sta API_BLOCK_BASE + 12         ; speed (0 = frozen)
    stz API_BLOCK_BASE + 14
    tya
    and #$00FF
    sta API_BLOCK_BASE + 16         ; curve id
    stz API_BLOCK_BASE + 18
    jsr engine_scroll_wave_curve
    bra game_loop

@no_change:
    rep #$20
    .a16
    bra game_loop
