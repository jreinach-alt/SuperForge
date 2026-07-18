; =============================================================================
; mode7_test — run-gate for the Mode 7 macros (perspective floor + steering)
; =============================================================================
; Uploads a checkerboard map (tests/fixtures/mode7/checker_map.bin), turns on
; the Mode 7 perspective renderer with the proven racing-camera parameters,
; and steers with the d-pad (LEFT/RIGHT rotate the camera 1/256 turn per
; frame). The stock engine NMI handler does ALL hardware commits — this ROM
; has no custom VBlank code (the architecture sf_mode7.inc documents).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB"); frame heartbeat at $7E:E010 advances
;   - the perspective floor renders: two greens below the horizon (l0=96),
;     checker squares smaller near the horizon than near the bottom
;   - the per-scanline matrix HDMA table in WRAM ($7E:A000 / $A900 double
;     buffer) holds varying nonzero matrix-A coefficients
;   - holding LEFT rotates the view (screenshot changes below the horizon)
;
; Build:  64KB config (the 32KB map blob lives in BANK1) — explicit Makefile
;         rule, lorom_64k.cfg.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_mode7.inc"         ; the Mode 7 macro group
.include "engine_state.inc"

; --- game DP state (kit contract: $32-$5F) ---
M7T_POSX  = $32                 ; camera x (px)
M7T_POSY  = $34                 ; camera y (px)
M7T_ANGLE = $36                 ; camera angle word (low byte = 0..255 turn)

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200

; --- the proven racing-camera parameter set ---
PV_L0_RACING     = 96           ; horizon scanline
PV_L1_RACING     = 224          ; bottom scanline
PV_S0_RACING     = 192          ; far-scale
PV_S1_RACING     = 24           ; near-scale
PV_SH_RACING     = 16           ; vertical squash (road aspect)
PV_INTERP_RACING = 2
PV_WRAP_RACING   = 1
FOCUS_Y_RACING   = 192

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- map + palette upload under the coldstart forced blank ---
    sf_mode7_load_map checker_map, #$8000

    sep #$20
    .a8
    stz $2121                   ; CGADD = 0
    lda #<COLOR_BACKDROP
    sta $2122
    lda #>COLOR_BACKDROP
    sta $2122
    lda #<COLOR_DARK_GREEN      ; palette index 1 (checker tile 0)
    sta $2122
    lda #>COLOR_DARK_GREEN
    sta $2122
    lda #<COLOR_LIGHT_GREEN     ; palette index 2 (checker tile 1)
    sta $2122
    lda #>COLOR_LIGHT_GREEN
    sta $2122
    rep #$30
    .a16
    .i16

    ; --- Mode 7 on + racing camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0_RACING, #PV_L1_RACING, #PV_S0_RACING, #PV_S1_RACING, #PV_SH_RACING, #PV_INTERP_RACING, #PV_WRAP_RACING
    sf_mode7_focus #FOCUS_Y_RACING

    lda #512                    ; center of the wrapped 1024px map
    sta M7T_POSX
    sta M7T_POSY
    stz M7T_ANGLE
    sf_mode7_cam M7T_POSX, M7T_POSY, M7T_ANGLE

    sf_mode7_tick               ; first table build BEFORE screen-on

    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    sta SHADOW_INIDISP          ; the NMI re-commits INIDISP from this shadow
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for the NMI; latch input

    ; --- steering: LEFT/RIGHT rotate 1/256 turn per frame ---
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq @no_left
    lda M7T_ANGLE
    inc a
    and #$00FF
    sta M7T_ANGLE
@no_left:
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq @no_right
    lda M7T_ANGLE
    dec a
    and #$00FF
    sta M7T_ANGLE
@no_right:

    sf_mode7_cam M7T_POSX, M7T_POSY, M7T_ANGLE
    sf_mode7_tick

    ; --- heartbeat: engine frame counter -> debug region $7E:E010 ---
    rep #$30
    .a16
    .i16
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; --- palette (15-bit BGR) ---
COLOR_BACKDROP    = $5400       ; muted blue-violet backdrop (color 0)
COLOR_DARK_GREEN  = $01E0       ; G=15
COLOR_LIGHT_GREEN = $03E0       ; G=31

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order
; =============================================================================
mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- the 32KB interleaved map blob (bank 1 of the 64KB image) ---
.segment "BANK1"
checker_map:
    .incbin "tests/fixtures/mode7/checker_map.bin"
