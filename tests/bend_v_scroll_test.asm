; =============================================================================
; bend_v_scroll_test — run-gate for V-SCROLL compose (SHADOW_BGnVOFS, v1.2)
; =============================================================================
; The V mirror of bend_hscroll_test: a STATIC vertical horizon squash
; (sf_bend_v SF_CURVE_HORIZON, speed 0) whose underlying field is PANNED
; vertically every frame via the normal `scroll` macro. The V-axis refill
; composes per line  offset = SHADOW_BG{layer}VOFS + curve, so the field flows
; up/down under the barrel while STAYING compressed — the authentic vertical-
; shooter use (a ground/starfield scrolling toward a fixed horizon).
;
; The main loop ramps SHADOW_BG1VOFS (via scroll #1,#0,vofs) by +1 each frame.
; Because the base scroll is nonzero, sf_bend_tick takes the OPTIMIZED REFILL
; path (the baked pointer-slide can't add a per-frame-changing base), recomposing
; base + curve every line. The curve itself never rolls (speed 0), so the SQUASH
; SHAPE holds while the bands MARCH downward.
;
; Done-condition (read from RENDERED PIXELS, test_bend_v.py):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = channel (3..7); $7E:E010 heartbeat
;   - $7E:E014 = the live VOFS pan value (advances — proves the pan runs)
;   - the band pattern PANS vertically frame-to-frame (a band at row y moves to
;     a different y) AND the spacing still VARIES down the frame (stays squashed)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_frame.inc"
.include "sf_fx.inc"
.include "engine_state.inc"

BG_GREEN  = $03E0
BG_MX     = $46
BG_MY     = $48
BG_TILE   = $4A
PAN_VOFS  = $4C                 ; DP: the per-frame vertical pan accumulator

BEND_AMP   = 128               ; reciprocal horizon squash, unity passthrough
                                ; (|off|*128/128 = |off|) — matches bend_v_test.

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    jsr hdma_alloc_init

    sf_load_bg_tile 1, bg_tile
    sf_bg_color 0, 1, BG_GREEN

    jsr init_ppu
    gfxmode #1

    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda #1                      ; the 4px-period band tile on every row (8px source
    sta BG_TILE                 ; period — matches bend_v_test's field)
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #32                      ; fill all 32 rows (256px) so the deep-pulled
                                 ; foreground always has band content (clean render)
    bne @row

    ; seed the pan accumulator and the BG at vofs 0
    stz PAN_VOFS
    scroll #1, #0, #0

    ; --- arm the STATIC V horizon squash (speed 0): the SHAPE holds, the field
    ;     pans under it via scroll each frame ---
    sf_bend_v #SF_CURVE_HORIZON, #BEND_AMP
    ldx #$0000
    sta f:$7E0000 + $E012, x

    sf_debug_magic

    sep #$20
    .a8
    lda $4210
@wait_vblank_end:
    lda $4212
    bmi @wait_vblank_end
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- pan the field vertically: SHADOW_BG1VOFS += 1 via the normal scroll ---
    lda PAN_VOFS
    inc a
    and #$00FF                  ; keep the pan in 0..255 (a 256px world wrap)
    sta PAN_VOFS
    scroll #1, #0, PAN_VOFS     ; sets SHADOW_BG1VOFS = pan (the refill composes it)

    sf_bend_tick                ; refill path (base != 0): recompose base + curve

    ; --- heartbeat + live pan value for the test ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    lda PAN_VOFS
    sta f:$7E0000 + $E014, x
    jmp game_loop

; 4px-period band tile (rows 0-3 green index 1, rows 4-7 gap) — matches bend_v_test.
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
