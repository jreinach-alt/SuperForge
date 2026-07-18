; =============================================================================
; bend_hscroll_test — run-gate for E-HSCROLL: base scroll composes UNDER the bend
; =============================================================================
; Enhancement v1.1 (E-HSCROLL): the per-scanline curve refill now composes
;   offset[line] = base_scroll + scaled_curve[(line + phase) & $FF]
; where base_scroll is read from the bent layer's SHADOW_BGnHOFS (the same
; shadow the `scroll` macro writes). So `scroll #layer, CAM_X, 0` pans the whole
; bent stripe pattern left/right at the caller's speed WHILE the per-scanline
; bend rides on top.
;
; This ROM arms a STATIC sine bend on BG1 (speed 0 — so the only frame-to-frame
; motion is the base scroll, not the roll; that isolates the pan) and drives
; CAM_X up for ~30 frames then back down. The order each frame is:
;   scroll #1, CAM_X, 0     ; update the base scroll shadow
;   sf_bend_tick            ; rebuild the table reading the NEW base scroll
; so each rebuilt line = CAM_X + curve. CAM_X (the running scroll) is published
; to $7E:E014 every frame so the test can correlate frames with scroll value.
;
; Done-condition (read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = channel (3..7); $7E:E010 heartbeat
;   - $7E:E014 = current CAM_X (the base scroll), $7E:E016 = phase (frame index)
;   - as CAM_X increases the whole stripe pattern shifts in one direction; as it
;     decreases it shifts back the other way; the per-scanline sine shape PERSISTS
;     through the pan (the layer stays bent while it pans).
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

CAM_X     = $4C                 ; DP: running base scroll (game-area scratch)
CAM_DIR   = $4E                 ; DP: 1 = panning right (CAM_X++), 0 = left
FIDX      = $50                 ; DP: frame index (for the test timeline)

BEND_AMP   = 14

CAM_STEP   = 2                  ; px/frame pan speed (slow → small per-frame shift)
CAM_TURN   = 40                 ; flip direction after this many frames each way

DBG_CAMX  = $7E0000 + $E014     ; published CAM_X
DBG_FIDX  = $7E0000 + $E016     ; published frame index

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

    ; --- BG1 wide vertical stripes (64px period) ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    lsr
    lsr
    and #$0001
    sta BG_TILE
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #24
    bne @row

    ; --- init the pan state ---
    stz CAM_X
    lda #1
    sta CAM_DIR                 ; start panning right
    stz FIDX

    scroll #1, #0, #0           ; base scroll 0

    ; --- arm a STATIC sine bend on BG1 (speed 0 — isolates the pan) ---
    sf_bend #SF_CURVE_SINE, #BEND_AMP
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

    ; --- advance the pan: CAM_X += / -= CAM_STEP, flip at CAM_TURN ----------
    lda FIDX
    inc a
    sta FIDX

    lda CAM_DIR
    and #$00FF
    beq @pan_left
    ; panning right
    lda CAM_X
    clc
    adc #CAM_STEP
    sta CAM_X
    cmp #(CAM_STEP * CAM_TURN)
    bcc @pan_done
    stz CAM_DIR                 ; reached the right limit → pan left
    bra @pan_done
@pan_left:
    .a16
    lda CAM_X
    sec
    sbc #CAM_STEP
    sta CAM_X
    bne @pan_done               ; back near 0 → pan right again
    lda #1
    sta CAM_DIR
@pan_done:
    .a16

    ; --- feed the base scroll, THEN rebuild (order matters) ---
    scroll #1, CAM_X, #0        ; base scroll → SHADOW_BG1HOFS
    sf_bend_tick                ; rebuild: line = CAM_X + curve

    ; --- publish telemetry for the test ---
    lda CAM_X
    ldx #$0000
    sta f:DBG_CAMX, x
    lda FIDX
    sta f:DBG_FIDX, x
    lda FRAME_COUNTER
    sta f:$7E0000 + $E010, x
    jmp game_loop

bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
