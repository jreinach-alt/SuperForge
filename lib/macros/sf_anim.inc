; =============================================================================
; sf_anim.inc — animation clock + frame-table lookup (macro library)
; =============================================================================
; The look-and-feel brick: multi-frame actors that play their png2snes
; animations and face left/right with the hardware H-flip.
;
; The data comes from `tools/png2snes.py sprite --anims ...`, which emits per-
; animation tables of BASE-RELATIVE TILE OFFSETS (one byte per frame step):
;
;   arthur_anim_run_len = 8
;   arthur_anim_run: .byte $40, $44, $48, $4C, $80, $84, $88, $8C
;
; Per animated actor the game owns two DP words: a TICK (frame-rate divider)
; and a FRAME (step index 0..len-1). Per frame:
;
;       sf_anim_step  PTICK, PFRAME, #6, #arthur_anim_run_len
;       sf_anim_tile  arthur_anim_run, PFRAME      ; A = tile offset
;       clc
;       adc #ARTHUR_BASE                           ; + your load base
;       sta PTILE
;       spr PTILE, PX, PY, PFLAGS, #2
;
; FACING (the H-flip idiom — OAM attribute bit 6 flips the WHOLE hardware
; sprite, any size, zero cost): keep a facing word (0 = right, 1 = left,
; matching the art's drawn direction) and build the spr flags from it:
;
;       lda #$80                ; large size select
;       ldx FACING
;       beq face_done           ; facing right -> no flip
;       ora #$40                ; facing left  -> H-flip
;   face_done:
;       sta PFLAGS
;
; Switching animations (idle <-> run <-> hit): each sf_anim_tile call names
; its table at ASSEMBLE time, so switch by branching to a draw path per
; state — see the brawler template's anim-state dispatch. Reset FRAME and
; TICK to 0 on EVERY state change, or a 4-step table indexed at step 7
; reads past its end.
;
; Requires: nothing (pure data macros — no engine link partners).
; =============================================================================

.ifndef SF_ANIM_INC
SF_ANIM_INC = 1

; -----------------------------------------------------------------------------
; sf_anim_step tick, frame, rate, len — advance an animation clock one frame.
; -----------------------------------------------------------------------------
;   tick   DP/memory word: frame-rate divider counter (game owns, init 0)
;   frame  DP/memory word: current step index (game owns, init 0)
;   rate   verbatim (`#6`): game frames per animation step (6 = 10 steps/s)
;   len    verbatim (`#name_anim_X_len`): steps in the animation
; Every `rate` calls, frame advances and wraps at len. Call once per actor
; per game frame, gated on the actor being in that animation state.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); exits A16.
.macro sf_anim_step sf_tick, sf_frame, sf_rate, sf_len
    .local an_adv, an_done
    rep #$30
    .a16
    .i16
    lda sf_tick
    inc a
    sta sf_tick
    cmp sf_rate
    bcs an_adv
    bra an_done
an_adv:
    .a16
    stz sf_tick
    lda sf_frame
    inc a
    cmp sf_len
    bcc :+
    lda #$0000                  ; wrap
:   sta sf_frame
an_done:
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_anim_tile table, frame — look up the current step's tile offset.
; -----------------------------------------------------------------------------
;   table  BARE ROM label of a png2snes anim table (one byte per step)
;   frame  DP/memory word: the step index (from sf_anim_step)
; Returns the BASE-RELATIVE tile offset in A (0-255); add your sf_load_obj_chr
; base before handing it to spr. Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; the byte-table read masks the high byte
; explicitly; exits A16.
.macro sf_anim_tile sf_table, sf_frame
    rep #$30
    .a16
    .i16
    ldx sf_frame
    lda f:sf_table, x           ; byte entry (+1 stray high byte)
    and #$00FF
.endmacro

.endif ; SF_ANIM_INC
