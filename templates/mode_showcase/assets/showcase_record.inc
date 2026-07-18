; =============================================================================
; showcase_record.inc — RECORD: multi-slot SRAM save/recall + debug export.
; =============================================================================
; Two record paths (spec "tune-and-record"):
;   1. SRAM SLOTS (sf_save engine) — save/recall the full knob block across
;      power-cycle. Saved payload = the 30 knob values + the 30 aux bytes
;      (SHOW_KNOB_VAL..+60), so a recalled config restores every knob exactly.
;      FOUR slots (0..3): the active slot is SHOW_SAVE_SLOT_SEL (selected on the
;      record screen via L/R) so the user can keep several finds and revisit one
;      later (spec "SRAM save SLOTS"). Slot dispatch is RUNTIME (the sf_save
;      macro takes a compile-time slot, so we drive the engine directly).
;   2. Debug-region export — each demo frame, mirror the live 30 knob values to
;      SHOW_DBG_MIRROR ($7E:E300) so the MCP/test harness reads tuned values out
;      programmatically (paste back as source defaults — the no-recompile loop).
;
; SRAM save/recall is bound to the PARAM SHEET (the record screen): A = save,
; B = recall, L/R = select slot. The sheet is frozen so captures are stable.
; =============================================================================

SHOW_SAVE_LEN     = 60        ; 30 knob values + 30 aux bytes
SHOW_SAVE_VER     = 1
SHOW_SAVE_NSLOTS  = 4         ; SRAM slots (engine cap is 4 x 2KB)

; -----------------------------------------------------------------------------
; _show_slot_base — set SL_SLOT_BASE from the runtime SHOW_SAVE_SLOT_SEL (0..3).
; slot base = slot * SF_SAVE_SLOT_SIZE (2048 = <<11). A16/I16 in/out.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry/exit.
.proc _show_slot_base
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_SAVE_SLOT_SEL
    and #$03                          ; clamp 0..3 (defensive)
    rep #$20
    .a16
    and #$00FF
    ; * 2048 = << 11
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl                               ; 11 shifts
    sta SL_SLOT_BASE
    rts
.endproc

; -----------------------------------------------------------------------------
; show_save_params — write the knob block to the ACTIVE SRAM slot. Drives the
; save engine directly (runtime slot). src is the bank-$7E 16-bit WRAM offset.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; engine_save runs its own widths; exits A16/I16.
.proc show_save_params
    rep #$30
    .a16
    .i16
    jsr _show_slot_base               ; SL_SLOT_BASE = active slot * 2048
    lda #(SHOW_KNOB_VAL & $FFFF)
    sta SL_SRC_ADDR
    lda #SHOW_SAVE_LEN
    sta SL_LENGTH
    lda #SHOW_SAVE_VER
    sta SL_VERSION
    jsr engine_save
    rts
.endproc

; -----------------------------------------------------------------------------
; show_recall_params — load the ACTIVE SRAM slot back into the knob block.
; On success the knobs are restored; the next show_apply pushes them to the PPU.
; No-op (knobs unchanged) if the slot is empty/corrupt (engine checks magic+CRC).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; engine_load runs its own widths; exits A16/I16.
.proc show_recall_params
    rep #$30
    .a16
    .i16
    jsr _show_slot_base               ; SL_SLOT_BASE = active slot * 2048
    lda #(SHOW_KNOB_VAL & $FFFF)
    sta SL_SRC_ADDR
    jsr engine_load
    ; A = length / $FFFF / $FFFE — dest untouched on the error codes; the demo's
    ; per-frame apply reflects whatever loaded.
    rts
.endproc

; -----------------------------------------------------------------------------
; show_slot_select_next — cycle the active SRAM slot 0->1->2->3->0 (L/R on the
; record screen). The selected slot is surfaced on the param sheet.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte RMW; exits A16/I16.
.proc show_slot_select_next
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_SAVE_SLOT_SEL
    inc a
    cmp #SHOW_SAVE_NSLOTS
    bcc @store
    lda #0
@store:
    sta f:SHOW_SAVE_SLOT_SEL
    rep #$20
    .a16
    rts
.endproc

.proc show_slot_select_prev
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_SAVE_SLOT_SEL
    bne @dec
    lda #SHOW_SAVE_NSLOTS
@dec:
    dec a
    sta f:SHOW_SAVE_SLOT_SEL
    rep #$20
    .a16
    rts
.endproc

; -----------------------------------------------------------------------------
; show_dbg_export — mirror the 30 live knob values to SHOW_DBG_MIRROR ($7E:E300).
; Called every demo frame. Long-addressed copy (both ends in bank $7E).
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte copy; exits A16/I16.
.proc show_dbg_export
    rep #$30
    .a16
    .i16
    ldx #0
@cp:
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL, x
    sta f:SHOW_DBG_MIRROR, x
    rep #$20
    .a16
    inx
    cpx #(SHOW_N_SLOTS * SHOW_N_PARAMS)
    bcc @cp
    ; also mirror the active slot + preset for the harness to read state.
    ; (The arena-mutex owner is read directly from SHOW_ARENA_OWNER at $7E:E325 —
    ; it lives outside the 32-byte mirror window so no extra export is needed.)
    sep #$20
    .a8
    lda f:SHOW_ACTIVE_SLOT
    sta f:SHOW_DBG_MIRROR + 30
    lda f:SHOW_PRESET
    sta f:SHOW_DBG_MIRROR + 31
    rep #$20
    .a16
    rts
.endproc
