; =============================================================================
; sf_mosaic_transition_data.inc — mosaic-transition curves + stepper (link part)
; =============================================================================
; The EMITTED half of sf_mosaic_transition.inc: the darkness ease curves and
; the per-frame state-machine stepper the sf_mosaic_transition_tick macro JSRs.
; Include it ONCE at the BOTTOM of main.asm, inside the CODE segment, next to
; the engine .asm includes:
;
;   .include "nmi_handler.asm"   ; (commits SHADOW_MOSAIC / INIDISP / TM)
;   ...
;   .include "sf_mosaic_transition_data.inc)
;
; (If you forget it, the link fails naming _sf_mosaic_step / _sf_mosaic_curve_*
; — that's your cue.)
;
; THE TECHNIQUE (generalized from the RPG slice's scene wipe, S4):
;   A scene swap (Mode 7<->Mode 1, level reload, anything) is discontinuous and
;   tears if shown mid-rebuild. The wipe hides it behind a symmetric mosaic +
;   darkness DISSOLVE:
;     OUT phase  brightness 15->0 (darkness ease), mosaic size 0->15 LOCKED to
;                size = 15 - brightness (the two complementary every frame: full
;                brightness = clean, black = full pixelation). At the darkest
;                frame the caller's SWAP runs (under the kit forced-blank
;                bracket, NMI masked) — the swap frame is black, no flash.
;     IN phase   the new scene brightens 0->15 (sine ease) + de-pixelates,
;                mosaic 15->0, again size = 15 - brightness.
;   OBJ has NO hardware mosaic, so sprites are DROPPED for the whole transition
;   (cleared from SHADOW_TM at arm + after the swap) and RESTORED on the final
;   IN frame — so no un-pixelated sprites float over the dissolving BGs.
;
; SHADOW-DRIVEN (no custom NMI): the stepper writes SHADOW_MOSAIC ($2106
; shadow), SHADOW_INIDISP's brightness nibble ($2100 shadow), and SHADOW_TM
; ($212C shadow); the STOCK engine NMI commits all three every VBlank. The
; slice owned its NMI and wrote the registers directly — the kit reuses the
; engine's commit path, so a kit ROM needs NO custom VBlank code for the wipe.
;
; The mosaic AFFECTED-BG nibble (low nibble of $2106) is supplied by the caller
; at arm time (_sf_mt_bg_mask) — e.g. $01 = BG1 only (a Mode-1 map), $03 =
; BG1+BG2 (a Mode-7 ground + a BG2 sky that should pixelate too). The stepper
; ORs it under the size nibble only when size>0 (a clean frame writes $2106=$00,
; no BG-enable bits — a size-0 mosaic with enable bits set still perturbs the
; image vs a true $00 frame; the slice verified this on the emulator).
; =============================================================================

.ifndef SF_MOSAIC_TRANSITION_DATA_INC
SF_MOSAIC_TRANSITION_DATA_INC = 1

.include "engine_state.inc"     ; SHADOW_MOSAIC, SHADOW_INIDISP, SHADOW_TM (guard)

; -----------------------------------------------------------------------------
; Phase lengths (frames). Override BEFORE including to retune the wipe pace.
; -----------------------------------------------------------------------------
.ifndef SF_MT_OUT_FRAMES
SF_MT_OUT_FRAMES = 20          ; OUT: brightness 15->0 over 20 frames
.endif
.ifndef SF_MT_IN_FRAMES
SF_MT_IN_FRAMES  = 15          ; IN:  brightness 0->15 over 15 frames
.endif

.assert SF_MT_OUT_FRAMES >= 1 && SF_MT_OUT_FRAMES <= 64, error, "OUT 1..64"
.assert SF_MT_IN_FRAMES  >= 1 && SF_MT_IN_FRAMES  <= 64, error, "IN 1..64"

; State machine values (in _sf_mt_state).
SF_MT_IDLE = 0
SF_MT_OUT  = 1
SF_MT_IN   = 2

; -----------------------------------------------------------------------------
; Darkness ease curves (brightness 0..15 per phase frame; ORIGINAL — hand-
; generated quarter-cosine OUT / quarter-sine IN, continuous + monotonic, so
; the dissolve reaches black exactly at the swap and rises smoothly back).
; Indexed by elapsed = PHASE_FRAMES - timer (0..PHASE_FRAMES-1). Sized to the
; defaults; if you raise SF_MT_*_FRAMES past these lengths, extend the tables.
; -----------------------------------------------------------------------------
_sf_mosaic_curve_out:
    .byte $0F, $0F, $0F, $0F, $0E, $0E, $0D, $0D  ; OUT elapsed 0-7
    .byte $0C, $0B, $0B, $0A, $09, $08, $07, $06  ; OUT elapsed 8-15
    .byte $05, $04, $02, $01                       ; OUT elapsed 16-19 (swap forces 0)
_sf_mosaic_curve_out_end:
.assert (_sf_mosaic_curve_out_end - _sf_mosaic_curve_out) >= SF_MT_OUT_FRAMES, error, "extend OUT curve"

_sf_mosaic_curve_in:
    .byte $02, $03, $05, $06, $07, $09, $0A, $0B  ; IN elapsed 0-7
    .byte $0C, $0D, $0E, $0E, $0F, $0F, $0F        ; IN elapsed 8-14 (settled = 15)
_sf_mosaic_curve_in_end:
.assert (_sf_mosaic_curve_in_end - _sf_mosaic_curve_in) >= SF_MT_IN_FRAMES, error, "extend IN curve"

; =============================================================================
; _sf_mosaic_commit — write SHADOW_MOSAIC ($2106) with size = 15 - brightness
; and (when size>0) the caller's affected-BG mask. Reads _sf_mt_bright +
; _sf_mt_bg_mask. The stock NMI commits SHADOW_MOSAIC to $2106 each VBlank.
; Entry/exit A8/I16 (the stepper's convention). Clobbers A.
; WIDTH-RISK: pure A8, no rep/sep, no tax/tay — enters and exits A8/I16.
; =============================================================================
.a8
.i16
.proc _sf_mosaic_commit
    lda #15
    sec
    sbc a:_sf_mt_bright         ; size = 15 - brightness (0..15)
    bne @nonzero
    stz SHADOW_MOSAIC           ; size 0 -> truly clean: $2106 = $00 (no BG bits)
    rts
@nonzero:
    .a8
    asl
    asl
    asl
    asl                         ; size << 4 (high nibble = pixel size)
    ora a:_sf_mt_bg_mask        ; | affected-BG nibble (caller-supplied)
    sta SHADOW_MOSAIC
    rts
.endproc

; =============================================================================
; _sf_mosaic_obj_set — set (A!=0) or clear (A==0) the OBJ bit in SHADOW_TM.
; OBJ has no hardware mosaic, so we DROP the OBJ layer for the dissolve and
; restore it at the end. SHADOW_TM is committed to $212C by the stock NMI.
;   In: A8, A = $10 to enable OBJ, $00 to drop it (we OR/AND the bit).
; Entry/exit A8/I16. Clobbers A.
; WIDTH-RISK: pure A8, no rep/sep — enters and exits A8/I16.
; =============================================================================
.a8
.i16
.proc _sf_mosaic_obj_set
    beq @drop
    lda SHADOW_TM
    ora #$10                    ; OBJ on (bit4)
    sta SHADOW_TM
    rts
@drop:
    .a8
    lda SHADOW_TM
    and #$EF                    ; OBJ off (clear bit4)
    sta SHADOW_TM
    rts
.endproc

; =============================================================================
; _sf_mosaic_step — the per-frame transition state machine.
;   Reads/writes _sf_mt_* state. On the swap frame (end of OUT) JSRs the
;   caller's swap routine via _sf_mt_swap_ptr (a 16-bit CODE address set at arm;
;   $0000 = no swap, e.g. for a fade-in-only or a pure flash). The swap runs at
;   peak darkness (brightness already ~0) — the caller does its forced-blank
;   scene rebuild there; on return the stepper re-drops OBJ and enters IN.
; Entry/exit A8/I16 (the tick macro's convention). Clobbers A, X.
; WIDTH-RISK: A8 entry/exit. Each phase toggles A16 only to build a clean
; 16-bit curve index (and #$00FF + tax, X is I16) then restores A8 before the
; byte ops — both arms balanced, end A8. The swap JSR is the caller's routine
; (its own width contract; the kit forced-blank bracket restores A8 on return).
; =============================================================================
.a8
.i16
.proc _sf_mosaic_step
    lda a:_sf_mt_state
    bne :+
    rts                         ; idle — nothing to do
:   cmp #SF_MT_OUT
    beq @phase_out
    jmp @phase_in               ; state == IN

@phase_out:
    .a8
    ; elapsed = OUT_FRAMES - timer  (0..OUT-1 across the OUT frames)
    lda #SF_MT_OUT_FRAMES
    sec
    sbc a:_sf_mt_timer
    rep #$20
    .a16
    and #$00FF                  ; clean 16-bit curve index
    tax
    sep #$20
    .a8
    lda f:_sf_mosaic_curve_out, x
    sta a:_sf_mt_bright         ; NMI commits brightness to $2100 (via INIDISP)
    jsr _sf_mosaic_apply_bright ; push brightness into SHADOW_INIDISP nibble
    jsr _sf_mosaic_commit       ; size = 15 - brightness, mask under it
    dec a:_sf_mt_timer
    bne @out_done
    ; --- swap frame: force black, hold full pixelation, run the caller swap ---
    stz a:_sf_mt_bright
    jsr _sf_mosaic_apply_bright
    jsr _sf_mosaic_commit       ; size 15 (brightness 0) | the OUTgoing BG mask
    ; JSR the caller's swap routine (does its own forced-blank rebuild).
    lda a:_sf_mt_swap_ptr+0
    ora a:_sf_mt_swap_ptr+1
    beq @no_swap                ; null pointer -> no swap (flash / fade only)
    jsr _sf_mosaic_call_swap
@no_swap:
    .a8
    ; re-drop OBJ for the new scene (the swap may have re-enabled it), so no
    ; sprites show during the IN ramp; restored on the final IN frame.
    lda #$00
    jsr _sf_mosaic_obj_set
    lda #SF_MT_IN
    sta a:_sf_mt_state
    lda #SF_MT_IN_FRAMES
    sta a:_sf_mt_timer
@out_done:
    .a8
    rts

@phase_in:
    .a8
    ; elapsed_in = IN_FRAMES - timer (0..IN-1); first IN frame reads ~0 (matches
    ; the black swap), last reads 15 (full brightness, settled).
    lda #SF_MT_IN_FRAMES
    sec
    sbc a:_sf_mt_timer
    rep #$20
    .a16
    and #$00FF
    tax
    sep #$20
    .a8
    lda f:_sf_mosaic_curve_in, x
    sta a:_sf_mt_bright
    jsr _sf_mosaic_apply_bright
    jsr _sf_mosaic_commit
    dec a:_sf_mt_timer
    bne @in_done
    ; --- final IN frame: clear mosaic, pin full brightness, restore OBJ, idle ---
    stz SHADOW_MOSAIC           ; clear MOSAIC fully ($2106 = $00)
    lda #$0F
    sta a:_sf_mt_bright
    jsr _sf_mosaic_apply_bright ; settled = full brightness
    lda #$10
    jsr _sf_mosaic_obj_set      ; OBJ back on (bit4)
    stz a:_sf_mt_state          ; idle
@in_done:
    .a8
    rts
.endproc

; =============================================================================
; _sf_mosaic_apply_bright — write _sf_mt_bright (0..15) into SHADOW_INIDISP's
; brightness nibble, PRESERVING the forced-blank bit ($80) the kit boot/scene
; may hold. The stock NMI commits SHADOW_INIDISP to $2100 each VBlank.
; Entry/exit A8/I16. Clobbers A.
; WIDTH-RISK: pure A8, no rep/sep — enters and exits A8/I16.
; =============================================================================
.a8
.i16
.proc _sf_mosaic_apply_bright
    lda SHADOW_INIDISP
    and #$F0                    ; keep blank bit + high nibble, clear brightness
    ora a:_sf_mt_bright         ; new brightness nibble (0..15)
    sta SHADOW_INIDISP
    rts
.endproc

; =============================================================================
; _sf_mosaic_call_swap — TAIL-CALL the caller's swap routine via the 16-bit
; pointer _sf_mt_swap_ptr. `jmp (abs)` reads the target from bank $00 (the low
; WRAM mirror — where _sf_mt_swap_ptr lives), then jumps into the swap; the
; swap's RTS returns to the address THIS routine was JSR'd with (the line after
; `jsr _sf_mosaic_call_swap` in _sf_mosaic_step). So no own RTS is needed —
; the indirect JMP tail-calls and the swap returns to the stepper directly.
; (jsr (abs,x) was wrong here: $FC reads its pointer from the PROGRAM bank, not
; from WRAM — see CLAUDE.md cross-bank-pointer discipline.)
; Entry A8/I16; the swap routine sets its own widths and (by the kit forced-
; blank bracket convention) restores A8/I16 before its RTS.
; WIDTH-RISK: A8/I16 entry. No rep/sep here; the indirect JMP transfers control
; to the swap, which owns its widths and restores A8/I16 on return.
; =============================================================================
.a8
.i16
.proc _sf_mosaic_call_swap
    jmp (_sf_mt_swap_ptr)       ; tail-call; swap's RTS returns to the stepper
.endproc

; -----------------------------------------------------------------------------
; Transition state (game-array region tail, abs-reachable with DB=$00). This is
; PERSISTENT across the whole wipe (unlike the dialog scratch). Placed at
; $1DD4, above the dialog scratch ($1DC0-$1DD3) and below the audio tail
; ($1DE0). A ROM uses EITHER dialog OR the transition scratch in a given frame,
; but the ranges are disjoint so both macros can coexist.
; -----------------------------------------------------------------------------
_sf_mt_state    = $1DD4         ; 1 B: SF_MT_IDLE / OUT / IN
_sf_mt_timer    = $1DD5         ; 1 B: frames remaining in the current phase
_sf_mt_bright   = $1DD6         ; 1 B: current brightness 0..15 (size = 15-this)
_sf_mt_bg_mask  = $1DD7         ; 1 B: affected-BG nibble for $2106 low nibble
_sf_mt_swap_ptr = $1DD8         ; 2 B: caller swap routine CODE addr (0 = none)

.endif ; SF_MOSAIC_TRANSITION_DATA_INC
