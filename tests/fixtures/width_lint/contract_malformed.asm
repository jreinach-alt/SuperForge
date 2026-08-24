; =============================================================================
; contract_malformed.asm — declarations the parser must REFUSE, not skip
; =============================================================================
; A header that reads to a human as a checked contract while nothing checks it
; is worse than no header, so every shape of unreadable declaration is its own
; finding. One violation per routine, so a count is a diagnosis.
.p816
.smart
.segment "CODE"

; A slot name that is not a slot.
; CONTRACT fx_bad_slot
;   entry:    A16 I16
;   exit:     A16 I16
;   clobbers: A
;   returns:  nothing
fx_bad_slot:
    .a16
    .i16
    rts

; `clobbers:` missing — the routine destroys something and does not say what.
; CONTRACT fx_missing_slot
;   entry:    A16 I16
;   exit:     A16 I16
fx_missing_slot:
    .a16
    .i16
    rts

; An entry slot that names no index width.
; CONTRACT fx_half_axis
;   entry:    A16
;   exit:     A16 I16
;   clobbers: A
fx_half_axis:
    .a16
    .i16
    rts

; A width token that is not one.
; CONTRACT fx_bad_token
;   entry:    A16 I16 X8
;   exit:     A16 I16
;   clobbers: A
fx_bad_token:
    .a16
    .i16
    rts

; The name and the label have drifted apart.
; CONTRACT fx_wrong_name
;   entry:    A16 I16
;   exit:     A16 I16
;   clobbers: A
fx_renamed_label:
    .a16
    .i16
    rts

; The contract declares A16 and the label asserts A8. One of them is lying.
; CONTRACT fx_directive_drift
;   entry:    A16 I16
;   exit:     A8 I16
;   clobbers: A
fx_directive_drift:
    .a8
    .i16
    rts

; `A?` promises the routine establishes its own width, and this one does not:
; the first thing it runs is a width-sensitive load.
; CONTRACT fx_unknown_never_set
;   entry:    A? I16
;   exit:     A8 I16
;   clobbers: A
fx_unknown_never_set:
    .i16
    lda #$12
    rts
