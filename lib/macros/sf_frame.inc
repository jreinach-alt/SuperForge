; =============================================================================
; sf_frame.inc — engine-state init + frame-loop macros (macro library, rung A2)
; =============================================================================
; The structural macros that turn a bare booted ROM into a running 60fps game:
;   sf_engine_init   one-time engine-state setup (run once after sf_coldstart)
;   sf_frame_begin   top of the per-frame loop: wait for VBlank, latch input
;   sf_frame_end     bottom of the loop: resolve sprites, signal the VBlank DMA
;
; Usage:
;   RESET:
;       sf_coldstart
;       sf_engine_init
;       jsr init_ppu            ; engine PPU setup (Mode 1 + OBJ + screen on)
;       ... one-time game setup ...
;       lda #$81 : sta $4200    ; enable NMI + auto-joypad
;   game_loop:
;       sf_frame_begin
;       ... author update + draw (btn, spr, ...) ...
;       sf_frame_end
;       bra game_loop
;
; This is a MINIMAL frame loop — the WAIT/INPUT/RESOLVE/SIGNAL spine only. The
; full engine loop also ticks HDMA / Mode 7 / audio / streaming here; those are
; added by their own rungs when those features appear. Factored from the
; parent engine's proven frame spine (MAIN init + run-one-frame sequence).
;
; Requires (linked): engine/engine_state.inc, engine/nmi_handler.asm (the NMI
; vector handler that sets NMI_DONE_FLAG + drains the DMA queue), and the
; sprite + DMA engine (engine_spr_resolve / dma_queue_signal).
; =============================================================================

.ifndef SF_FRAME_INC
SF_FRAME_INC = 1

; -----------------------------------------------------------------------------
; sf_engine_init — initialize engine state once, after sf_coldstart.
; -----------------------------------------------------------------------------
; Sets the VBlank DMA budget + queue pointer and zeroes the per-frame sync
; flags, controller shadows, and counters. (sf_coldstart's WRAM clear already
; zeroed these; this is the explicit, self-documenting init the engine expects
; and is robust if a ROM ever skips the full clear.)
;
; WIDTH-RISK: toggles A8/A16 internally; exits A16/I16.
.macro sf_engine_init
    rep #$30
    .a16
    .i16
    lda #VBLANK_DMA_BUDGET
    sta NMI_DMA_BUDGET
    lda #DMA_QUEUE_BASE
    sta NMI_DMA_QUEUE_PTR
    stz NMI_DMA_QUEUE_COUNT
    stz JOY1_CURRENT
    stz JOY1_PREVIOUS
    stz JOY1_PRESSED
    stz FRAME_COUNTER
    stz SPRITE_COUNT
    sep #$20
    .a8
    stz NMI_DONE_FLAG
    stz NMI_DMA_READY
    stz OAM_DIRTY
    stz FRAME_PHASE
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_frame_begin — wait for the frame boundary, then latch input.
; -----------------------------------------------------------------------------
; WAIT: spin until the NMI signalled completion AND the DMA it queued last
; frame was actually transferred (NMI_DONE_FLAG=1 && NMI_DMA_READY=0). The
; DMA_READY check prevents the over-budget-frame race where a mid-frame NMI
; sets DONE without doing the DMA and a stale DONE lets WAIT proceed before the
; shadow OAM has been pushed (native_frame_run_one's documented hazard).
; INPUT: snapshot JOY1_PRESSED into the latch so btnp reads a stable rising
; edge for the whole frame.
;
; WIDTH-RISK: sets its own A8 for the flag spin and A16 for the latch; exits
; A16. Safe regardless of caller width.
.macro sf_frame_begin
    .local lbl_wait
    sep #$20
    .a8
    stz FRAME_PHASE
lbl_wait:
    lda NMI_DONE_FLAG
    beq lbl_wait
    lda NMI_DMA_READY
    bne lbl_wait               ; DMA still pending — wait for the NMI that drains it
    stz NMI_DONE_FLAG
    rep #$20
    .a16
    ; INPUT latch (P1)
    lda JOY1_PRESSED
    stz JOY1_PRESSED
    sta JOY1_PRESSED_LATCH
    sep #$20
    .a8
    lda #$02
    sta FRAME_PHASE
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_frame_end — resolve sprites to the OAM DMA queue and signal the NMI.
; -----------------------------------------------------------------------------
; engine_spr_resolve builds the priority-0 OAM DMA entry from the shadow OAM
; (if dirty); dma_queue_signal sets NMI_DMA_READY so the next VBlank NMI drains
; the queue (shadow OAM -> hardware OAM at $2104). After this, sf_frame_begin's
; WAIT blocks until that DMA has actually run.
;
; WIDTH-RISK: enters either width; sets A8 for the phase write, A16/I16 for the
; engine calls; exits A16/I16.
.macro sf_frame_end
    sep #$20
    .a8
    lda #$04
    sta FRAME_PHASE
    rep #$30
    .a16
    .i16
    jsr engine_spr_resolve
    jsr dma_queue_signal
.endmacro

.endif ; SF_FRAME_INC
