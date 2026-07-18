; =============================================================================
; bright_fade_engine.asm — Per-frame INIDISP brightness fade (Phase 16-6-0)
; =============================================================================
; Provides:
;   engine_bright_fade  — engine entry, stages target+frames and arms the stepper.
;   bright_fade_step    — Per-frame stepper, called from frame_lifecycle SIGNAL.
;
; Symmetric with the volume fade pair at engine/tad_bridge.asm
; (tad_start_fade + tad_fade_step). Operates on SHADOW_INIDISP bits 3-0
; only; the forced-blank bit ($80) is preserved across every step. NMI
; commits SHADOW_INIDISP to PPU $2100 each frame.
;
; State (4 bytes at $36-$39 in engine state, post-audit-1 remediation):
;   BRIGHT_FADE_TARGET     target brightness (0..15)
;   BRIGHT_FADE_STEP_FRAC  "frames to wait between brightness ticks"
;                            countdown. Decremented every frame; when it
;                            hits 0, brightness advances by one nibble unit
;                            and the counter is reloaded from
;                            (FRAMES / remaining_distance, min 1).
;   BRIGHT_FADE_FRAMES     frames remaining (0 = stepper inactive)
;   BRIGHT_FADE_DIRECTION  0 = fading down, 1 = fading up
;
; Algorithm (integer-division pacing, 4-byte state):
;   At fade start: compute distance = |target - current_brightness|. If
;   distance == 0 OR frames == 0, write target instantly and mark inactive.
;   Else: STEP_FRAC = max(frames / distance, 1) (frames per brightness step).
;
;   Per-frame step: decrement STEP_FRAC. When it hits 0, advance brightness
;   by 1 toward target (preserving $80), then reload STEP_FRAC =
;   max((remaining_frames - 1) / remaining_distance, 1). Decrement FRAMES.
;   When FRAMES reaches 0, clamp brightness to target and stay inactive.
;
;   This drifts at most 1 brightness unit from a perfect Bresenham
;   distribution per fade, but is guaranteed monotonic toward target and
;   guaranteed to land at target exactly on the FRAMES==0 frame.
;
; Width contract (WIDTH-RISK: documented entry/exit widths below):
;   engine_bright_fade — A16/I16 entry+exit (matches _engine_wrap_*).
;   bright_fade_step   — A8/I16 entry+exit (matches frame_lifecycle SIGNAL
;                        which `sep #$20` / `.a8` before the JSR, the same
;                        as tad_fade_step's call site).
;
; Cross-ref: engine/tad_bridge.asm tad_fade_step (sibling volume fade),
; engine/frame_lifecycle.asm SIGNAL phase (call site),
; the parent engine-call wrapper _engine_wrap_bright_fade,
; engine/engine_state.inc ES_BRIGHT_FADE_* equates.
; =============================================================================

; =============================================================================
; engine_bright_fade — Begin a per-frame brightness fade
; =============================================================================
; Input: A = target brightness (16-bit, low byte: 0..15; high bits ignored)
;        X = frames (16-bit, low byte: 1..255; 0 = instant set)
; Output: BRIGHT_FADE_* state armed (or instantly applied if frames == 0
;         or current brightness already equals target).
;
; WIDTH-RISK: entry/exit A16/I16. Internally switches to A8 to write the
; 1-byte engine-state fields, then back to A16 before RTS. Caller is
; _engine_wrap_bright_fade which is `rep #$30` throughout — must restore
; A16 before returning.
;
; Clobbers: A, X, Y.
; =============================================================================
engine_bright_fade:
    .a16
    .i16

    ; --- Stage params to engine state ---
    sep #$20
    .a8
    and #$0F                            ; low byte of A → target nibble
    sta BRIGHT_FADE_TARGET

    txa                                 ; A = X low byte = frames
    sta BRIGHT_FADE_FRAMES
    beq @instant                        ; frames == 0 → instant set

    ; --- Compute distance and direction ---
    ; current = SHADOW_INIDISP & $0F.
    lda SHADOW_INIDISP
    and #$0F
    cmp BRIGHT_FADE_TARGET
    beq @already_there                  ; distance == 0
    bcc @fade_up

    ; --- Fading down: current > target ---
    ; A still holds current.
    sec
    sbc BRIGHT_FADE_TARGET              ; A = distance (1..15)
    pha                                 ; stash distance on stack for divide
    stz BRIGHT_FADE_DIRECTION           ; 0 = down
    bra @compute_step_frac

@fade_up:
    .a8                                 ; .a8 — branch target after bcc
    ; current < target. A holds current.
    sta BRIGHT_FADE_STEP_FRAC           ; temp stash of current
    lda BRIGHT_FADE_TARGET
    sec
    sbc BRIGHT_FADE_STEP_FRAC           ; A = target - current = distance (1..15)
    pha                                 ; stash distance
    lda #$01
    sta BRIGHT_FADE_DIRECTION           ; 1 = up

@compute_step_frac:
    ; Stack top = distance (1..15). Compute frames/distance via repeated
    ; subtraction (≤15 iterations).
    pla                                 ; A = distance
    sta BRIGHT_FADE_STEP_FRAC           ; reuse field as divisor temp
    lda BRIGHT_FADE_FRAMES              ; A = total frames
    ldy #$00
@div_loop:
    cmp BRIGHT_FADE_STEP_FRAC
    bcc @div_done
    sbc BRIGHT_FADE_STEP_FRAC
    iny
    bra @div_loop
@div_done:
    .a8
    cpy #$01
    bcs @store_step
    ldy #$01                            ; clamp min to 1
@store_step:
    .a8
    tya
    sta BRIGHT_FADE_STEP_FRAC           ; "frames to wait between ticks"
    rep #$20
    .a16
    rts

@already_there:
    .a8                                 ; reached via beq, still A8
    stz BRIGHT_FADE_FRAMES               ; distance == 0 → mark inactive
    rep #$20
    .a16
    rts

@instant:
    .a8                                 ; reached via beq, still A8
    ; frames == 0: snap SHADOW_INIDISP brightness to target now,
    ; preserve $80 (forced-blank) bit.
    lda SHADOW_INIDISP
    and #$80
    ora BRIGHT_FADE_TARGET
    sta SHADOW_INIDISP
    stz BRIGHT_FADE_FRAMES               ; ensure inactive
    rep #$20
    .a16
    rts


; =============================================================================
; bright_fade_step — Advance brightness fade by one frame
; =============================================================================
; Called from frame_lifecycle.asm SIGNAL phase.
;
; WIDTH-RISK: entry/exit A8/I16 — matches the SIGNAL-phase pre-`sep #$20`
; that wraps the JSR (mirrors tad_fade_step's call site convention). MUST
; preserve I16 width tracking (no `sep #$30`).
;
; If BRIGHT_FADE_FRAMES == 0 → fast exit (~10 cycles).
; Otherwise:
;   1. Decrement STEP_FRAC. If still > 0, decrement FRAMES; if FRAMES hit 0
;      then clamp brightness to target. Return.
;   2. STEP_FRAC hit 0 → advance SHADOW_INIDISP brightness by 1 toward
;      target (preserving $80). Recompute STEP_FRAC =
;      max((FRAMES-1) / remaining_distance, 1). Decrement FRAMES; if it
;      hits 0, clamp brightness to target. Return.
;
; Clobbers: A, X, Y.
; =============================================================================
bright_fade_step:
    .a8
    .i16
    lda BRIGHT_FADE_FRAMES
    beq @done                           ; inactive — fast exit

    ; Active. First: tick the inter-step delay counter.
    dec BRIGHT_FADE_STEP_FRAC
    bne @dec_frames                     ; still waiting → just dec FRAMES

    ; --- STEP_FRAC hit 0: advance brightness by 1 toward target ---
    lda SHADOW_INIDISP
    and #$0F
    cmp BRIGHT_FADE_TARGET
    beq @after_step                     ; already at target — skip step
    ldx BRIGHT_FADE_DIRECTION
    beq @step_down
    ; Fading up: brightness += 1.
    inc a
    bra @apply_step
@step_down:
    .a8                                 ; reached via beq
    ; Fading down: brightness -= 1.
    dec a
@apply_step:
    .a8
    and #$0F                            ; clamp (defensive)
    tax                                 ; X = new brightness (low byte)
    lda SHADOW_INIDISP
    and #$80                            ; preserve forced-blank
    pha
    txa
    ora 1,s                             ; combine new_brightness | blank
    sta SHADOW_INIDISP
    pla                                 ; clean stack

@after_step:
    .a8
    ; Recompute STEP_FRAC = max((FRAMES-1) / remaining_distance, 1).
    ; Remaining distance computed from current SHADOW_INIDISP & $0F vs target.
    lda SHADOW_INIDISP
    and #$0F
    sec
    sbc BRIGHT_FADE_TARGET
    bcs @abs_ready                      ; current >= target
    eor #$FF                            ; two's complement (negate)
    clc
    adc #$01
@abs_ready:
    .a8
    beq @set_step_one                   ; distance == 0 → idle until FRAMES==0
    sta BRIGHT_FADE_STEP_FRAC           ; reuse field as divisor temp
    lda BRIGHT_FADE_FRAMES
    cmp #$02
    bcc @set_step_one                   ; FRAMES <= 1 → STEP_FRAC = 1
    dec a                               ; A = FRAMES - 1
    ldy #$00
@div_loop_step:
    cmp BRIGHT_FADE_STEP_FRAC
    bcc @div_done_step
    sbc BRIGHT_FADE_STEP_FRAC
    iny
    bra @div_loop_step
@div_done_step:
    .a8
    cpy #$01
    bcs @store_step_new
    ldy #$01
@store_step_new:
    .a8
    tya
    sta BRIGHT_FADE_STEP_FRAC
    bra @dec_frames

@set_step_one:
    .a8
    lda #$01
    sta BRIGHT_FADE_STEP_FRAC
    ; Fall through to @dec_frames.

@dec_frames:
    .a8
    dec BRIGHT_FADE_FRAMES
    bne @done
    ; Last frame: clamp brightness to target, preserve $80.
    lda SHADOW_INIDISP
    and #$80
    ora BRIGHT_FADE_TARGET
    sta SHADOW_INIDISP
@done:
    rts
