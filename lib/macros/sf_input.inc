; =============================================================================
; sf_input.inc — controller-read macros (macro library, rung A2)
; =============================================================================
; The Action-realm input API. `btn` reports whether a button is currently held;
; `btnp` reports a rising edge (newly pressed this frame). Both call the engine
; input functions directly (the macro IS the wrapper — see sf_sprite.inc).
;
; Requires (linked into the ROM): engine/engine_state.inc (equates) and
; engine/input_handler.asm (engine_btn, engine_btnp). The engine reads its
; controller shadow registers (JOY1_CURRENT / JOY1_PRESSED_LATCH), which the
; NMI handler updates each frame — so the frame loop (sf_frame.inc) and NMI +
; auto-joypad ($4200 bit 0) must be live for these to return real input.
;
; Button IDs come from buttons.inc (BTN_LEFT .. BTN_Y).
; =============================================================================

.ifndef SF_INPUT_INC
SF_INPUT_INC = 1

.include "buttons.inc"

; -----------------------------------------------------------------------------
; btn button_id [, player] -> A — 1 if the button is currently HELD, else 0.
; -----------------------------------------------------------------------------
;   button_id   BTN_* constant (operand passed verbatim — write `#BTN_RIGHT`)
;   player      0 = P1 (default), 1 = P2 (operand verbatim — write `#1`)
; Result (0/1) in A. Clobbers A. Preserves X, Y (engine_btn restores them).
; Idiom:  btn #BTN_RIGHT  /  beq not_held   (A==0 -> branch)
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default). engine_btn enters
; rep #$20 itself and returns A16 with X/Y preserved.
.macro btn sf_button_id, sf_player
    rep #$30
    .a16
    .i16
    ldx sf_button_id
.ifblank sf_player
    ldy #$0000                 ; default player 0 (P1)
.else
    ldy sf_player
.endif
    jsr engine_btn             ; A = 0/1; X/Y preserved
.endmacro

; -----------------------------------------------------------------------------
; btnp button_id [, player] -> A — 1 if the button was NEWLY pressed this frame.
; -----------------------------------------------------------------------------
; Rising-edge read against the per-frame latch the frame loop's INPUT phase
; snapshots (JOY1_PRESSED_LATCH). Same arg/result contract as btn.
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default). engine_btnp enters
; rep #$20 itself and returns A16 with X/Y preserved.
.macro btnp sf_button_id, sf_player
    rep #$30
    .a16
    .i16
    ldx sf_button_id
.ifblank sf_player
    ldy #$0000
.else
    ldy sf_player
.endif
    jsr engine_btnp            ; A = 0/1; X/Y preserved
.endmacro

.endif ; SF_INPUT_INC
