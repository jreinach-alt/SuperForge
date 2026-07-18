; =============================================================================
; bend_slide_test — run-gate for E-SLIDE: the pure-roll pointer-slide fast-path
; =============================================================================
; Enhancement v1.1 (E-SLIDE): for the pure-roll case (animated, base scroll = 0)
; the per-frame tick does NO table rebuild — it advances ONLY the channel's HDMA
; source pointer A1Tn into a once-baked oversized table, phasing the roll by
; sliding the read window. This ROM arms the marquee sine tunnel as a PURE roll
; (scroll = 0, so the tick takes the slide path) and, on a button-free timeline,
; FLIPS the roll speed from positive to negative partway through via
; sf_bend_phase — proving the SAME armed slide both rolls and reverses live.
;
; A direction byte at $7E:E018 (1 = forward/positive speed, 0 = reverse/negative)
; lets the test correlate captured frames with the active roll direction.
;
; Done-condition (read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = channel (3..7); $7E:E010 heartbeat
;   - $7E:E018 = roll direction flag (1 forward → 0 reverse after the flip)
;   - the per-scanline displacement pattern rolls one way while forward, the
;     OPPOSITE way after the flip — all on the slide fast-path (no rebuild).
;
; The flip happens at frame 90 (FRAME_COUNTER), giving the test a clean forward
; window before and a clean reverse window after.
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

BEND_AMP   = 14
SPEED_FWD  = 2                  ; forward roll
SPEED_REV  = $FFFE              ; −2 reverse roll
FLIP_FRAME = 90                 ; flip direction at this FRAME_COUNTER

DBG_DIR   = $7E0000 + $E018     ; roll-direction flag (1 forward, 0 reverse)

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

    scroll #1, #0, #0           ; base scroll 0 → the tick takes the slide path

    sf_tunnel #SF_CURVE_SINE, #BEND_AMP, #SPEED_FWD
    ldx #$0000
    sta f:$7E0000 + $E012, x
    lda #1
    sta f:DBG_DIR, x            ; start forward

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
    sf_bend_tick                ; slide path (base 0): advance A1Tn, no rebuild

    ; --- at FLIP_FRAME, reverse the roll speed (same armed slide) ----------
    lda FRAME_COUNTER
    cmp #FLIP_FRAME
    bcc @no_flip
    lda f:DBG_DIR
    and #$00FF
    beq @no_flip                ; already flipped
    sf_bend_phase #SPEED_REV    ; flip to reverse
    ldx #$0000
    lda #0
    sta f:DBG_DIR, x            ; mark reverse
@no_flip:
    .a16

    lda FRAME_COUNTER
    ldx #$0000
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
