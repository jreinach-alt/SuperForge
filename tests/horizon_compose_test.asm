; =============================================================================
; horizon_compose_test — glowing-horizon COMPOSITION (DoD v1.3 Addendum)
; =============================================================================
; Layers THREE already-shipped kit bricks into one convincing glowing perspective
; horizon — NO new engine code, pure macro assembly (C-STACK):
;
;   1. GEOMETRY — sf_bend_v SF_CURVE_HORIZON on BG1's VERTICAL axis: the
;      reciprocal / 1-over-z perspective row-squash (rows bunch DRAMATICALLY at
;      the horizon, spread toward the foreground), rolled every frame by
;      sf_bend_tick so the ground flows toward the viewer (the V tunnel). Solid
;      horizontal ground bands (the v1.2 clean-render constraint — per-line V
;      remap shows only as moving band EDGES, never torn interior detail).
;
;   2. COLOR RAMP + GLOW BAND — sf_gradient_stops: a per-scanline COLDATA ($2132)
;      RGB gradient, SCREEN-FIXED (indexed by scanline, NOT part of the rolling
;      BG), so it stays put while the ground rolls beneath it (closes the v1.2
;      transient-sky gap). Stops: dark sky up top, easing to a BRIGHT warm stop
;      AT the horizon scanline = the glow band, then a ground tint fading dark
;      toward the foreground.
;
;   3. ATMOSPHERIC HAZE — sf_colormath_on #1 (ADD) on BG1 + backdrop: the ground
;      BG pixels are tinted toward each row's COLDATA fixed color, so the
;      compressed distant rows near the horizon fade toward the bright horizon
;      color (depth approximated by the per-row COLDATA intensity ramp, C-DEPTH —
;      the per-scanline color-math STRENGTH ramp is the deferred sf_colormath_hdma
;      gap, OUT of scope). ADD chosen because the horizon glow is LIGHT: distant
;      ground washes toward the bright sky/horizon color = atmospheric haze.
;
; HDMA CHANNEL ALLOCATION (C-CHAN — arm GRADIENT FIRST so it owns CH3-CH5 fixed
; tables $C000-$C54B; bend then lands on CH6, table at $CC00, clear of the
; gradient region — no collision; color math is shadow-register, not a channel):
;   gradient → CH3,CH4,CH5  (COLDATA R/G/B, tables $C000/$C1C4/$C388)
;   bend_v   → CH6          (BG1VOFS, table $CC00)
;   color math → no channel (SHADOW_CGWSEL/CGADSUB, NMI commits)
;
; Done-condition (emulator-verifiable, rendered pixels — test_horizon_compose.py):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = bend channel, $7E:E016 = grad chan
;   - (a) the V-bend ground still compresses toward the horizon (geometry intact)
;   - (b) a vertical color gradient: sky rows ramp top→horizon (monotonic)
;   - (c) a bright horizon BAND: the horizon-row region is brighter than above/below
;   - (d) atmospheric fade: a ground band near the horizon tints CLOSER to the
;         horizon color than a foreground band
;   - the gradient/horizon band stays at a FIXED screen row while the ground rolls
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_bend_v / sf_tunnel_v / sf_bend_tick / gradient / colormath
.include "engine_state.inc"

BG_GREEN  = $03E0               ; 15-bit BGR green ground band colour (index 1)
BG_SKY    = $1004               ; 15-bit BGR dark navy backdrop (CGRAM 0). DARK so
                                ;   the COLDATA sky ramp ADDS up to a visible sky
                                ;   gradient (backdrop + fixed(scanline)); a bright
                                ;   backdrop would saturate the add.
BG_HLINE  = $7FFF               ; 15-bit BGR white horizon line (index 2) — with ADD
                                ;   math + the bright COLDATA glow stop it blooms.
BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A

SKY_ROWS  = 6                   ; top 6 tile rows (48px) = sky; row 6 = horizon line;
                                ;   rows 7..31 = perspective ground bands
HORIZON_Y = 48                  ; horizon scanline (tile row 6 * 8) — the glow band

BEND_AMP   = 128                ; reciprocal-horizon squash (full byte; bunches ground
                                ;   rows ~4x just below the horizon — the barrel)
BEND_SPEED = 2                  ; V tunnel phase roll per frame (ground flows forward)

; --- gradient stop array (5 stops, sky->horizon-glow->ground), copied to WRAM ---
; format per stop: scanline(16b), r(8b), g(8b), b(8b), pad(8b)   (0-31 per channel)
GRAD_STOP_WRAM = $E020          ; debug region $7E:E020 (free 4KB test region);
                                ;   the stops builder reads ($B8),y with DB=$7E.
GRAD_STOP_CNT  = 5

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- uploads under the coldstart forced blank (before screen-on) ---
    sf_load_bg_tile 1, bg_tile  ; tile 1 = 4px green / 4px gap ground band
    sf_load_bg_tile 2, hline_tile ; tile 2 = solid white horizon line
    sf_bg_color 0, 0, BG_SKY    ; CGRAM 0 (universal backdrop) = dark navy → sky
    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green ground band
    sf_bg_color 0, 2, BG_HLINE  ; BG palette 0, slot 2 = white horizon line

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- HORIZON-FRAMED field: sky rows / horizon line / ground bands ---
    ;   my <  SKY_ROWS  → tile 0 (transparent → sky-blue backdrop = SKY)
    ;   my == SKY_ROWS  → tile 2 (solid white = the HORIZON LINE)
    ;   my >  SKY_ROWS  → tile 1 (ground band tile; fills ALL rows so the deep
    ;                     V-pull always finds band content — no wrap gap)
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
    lda BG_MY
    cmp #SKY_ROWS
    bcc @sky                    ; my < SKY_ROWS → sky
    beq @hline                  ; my == SKY_ROWS → horizon line
    lda #1
    sta BG_TILE                 ; ground band tile
    bra @fill
@sky:
    .a16
    .i16
    stz BG_TILE                 ; tile 0 → sky backdrop
    bra @fill
@hline:
    .a16
    .i16
    lda #2
    sta BG_TILE                 ; tile 2 → white horizon line
@fill:
    .a16
    .i16
@col:
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #32
    bne @row

    ; --- copy the gradient stop array from ROM into WRAM ($7E:E020) ---
    rep #$30
    .a16
    .i16
    ldx #$0000
@cpstop:
    lda f:grad_stops,x
    sta f:$7E0000 + GRAD_STOP_WRAM, x
    inx
    inx
    cpx #(GRAD_STOP_CNT*6)
    bcc @cpstop

    ; --- BG1 at world-zero scroll; the V bend is the only vertical motion ---
    scroll #1, #0, #0

    ; --- color math: ADD the per-scanline fixed color on BG1 + backdrop, so the
    ;     ground tints toward each row's COLDATA value (haze) and the sky ramp
    ;     adds onto the dark backdrop. Layers $21 = BG1 (bit0) + backdrop (bit5).
    ;     Set up BEFORE arming the gradient (shadow-only; NMI commits). ---
    sf_colormath_on #1, #$21    ; mode 1 = ADD ; layers = BG1 + backdrop

    ; --- arm GRADIENT FIRST (claims CH3-CH5 + the fixed $C000-$C54B tables) ---
    sf_gradient_ease #2         ; ease-out: faster fade near the horizon = depth
    sf_gradient_stops #GRAD_STOP_WRAM, #GRAD_STOP_CNT
    ldx #$0000
    sta f:$7E0000 + $E016, x    ; record gradient first channel for the test
    sf_gradient_phase #0        ; gradient is STATIC (screen-fixed glow band)
    sf_gradient_update          ; force the initial build

    ; --- arm the ANIMATED horizon squash on BG1's VERTICAL axis (lands on CH6) ---
    sf_tunnel_v #SF_CURVE_HORIZON, #BEND_AMP, #BEND_SPEED
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the bend channel for the test

    sf_debug_magic

    ; enable NMI + auto-joypad (VBlank-edge handshake)
    sep #$20
    .a8
    lda $4210                   ; ack pending NMI (read-clear)
@wait_vblank_end:
    lda $4212                   ; HVBJOY
    bmi @wait_vblank_end        ; bit 7 = 1 → still in VBlank
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for NMI; latch input

    sf_bend_tick                ; roll the curve phase + rebuild the V table
    sf_gradient_tick            ; no-op (static gradient) — loop-path coverage

    ; --- frame heartbeat for the test ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; -----------------------------------------------------------------------------
; gradient stop array (ROM): sky -> horizon-glow -> ground (5 stops).
; scanline(16b), r, g, b, pad — intensities 0-31. Color math ADDs these to the
; main screen per scanline, so the picture tints toward each row's value.
; -----------------------------------------------------------------------------
grad_stops:
    ;        scanline   r    g    b   pad
    .word 0
    .byte  3,   5,  14,  0                       ; top of sky: dark navy
    .word 40
    .byte 11,  13,  22,  0                       ; upper sky haze (lighter, bluer)
    .word HORIZON_Y
    .byte 30,  27,  18,  0                       ; HORIZON GLOW BAND: bright warm
    .word 60
    .byte 18,  15,  10,  0                       ; far ground tint (warm, dimmer)
    .word 223
    .byte  3,   4,   2,  0                       ; near foreground: dark

; ground band tile (tile 1): 4px green / 4px gap → 8px source band period.
; Rows 0-3 = colour index 1 (plane0=$FF), rows 4-7 = index 0 (transparent → gap).
; Solid 4px stripes so the per-line V remap shows only moving band EDGES.
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00    ; rows 0-3: plane0=$FF (index 1 green)
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; rows 4-7: index 0 (gap)
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; planes 2-3 = 0
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; horizon-line tile (tile 2): every pixel colour index 2 → plane1=$FF on all 8
; rows. A solid bright bar marking the horizon scanline (blooms under ADD math).
hline_tile:
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF    ; rows 0-7: plane1=$FF (index 2)
    .byte $00,$FF, $00,$FF, $00,$FF, $00,$FF
    .byte $00,$00, $00,$00, $00,$00, $00,$00    ; planes 2-3 = 0
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
