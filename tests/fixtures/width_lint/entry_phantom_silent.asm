; Hole 4, phantom half: the regression guard for the fall-through model.
; `entry_documented` is a subroutine entry whose only in-file predecessors
; are (a) a return hidden behind an unnamed label (`:   rts`) and (b) an
; assembler-time symbol assignment — the two shapes that used to make
; _previous_real_instruction synthesise a phantom A16 fall-through arrival
; and contradict the documented A8 entry annotation (the naive-fix false
; positive on bg_text/scene_mgr/vwf/MAIN entry points).
; MUST STAY SILENT.
.p816
.smart
.segment "CODE"
helper:
    rep #$20
    .a16
    .i16
    lda #$1234
    beq :+
    lda #$5678
:   rts                         ; return behind an unnamed label

; --- entry_documented: entered A8/I16 by contract; callers live elsewhere ---
ENTRY_REGS = $4300 + 2 * 16     ; symbol assignment — emits no bytes

entry_documented:
    .a8                         ; documents the (cross-file) caller contract
    .i16
    lda #$12
    rts
