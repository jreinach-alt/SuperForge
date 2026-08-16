; reg-gate fixture (FIRES, item 5): the SPAN case. The scene's closure owns
; the ALU through one claim named `ALU`, whose footprint port is $4202 — but
; the hardware multiplier/divider is one resource spread over $4202-$4206 and
; $4214-$4217 (schemas.REGISTER_SPANS, derived from Mesen2's AluMulDiv.cpp,
; where multiply and divide mutually destroy one _state).
;
; So a write to $4204 is a write to a port no footprint name SITS at. It must
; resolve to `ALU` and be refused against the ALU claim's empty scene_writes.
; A base-port comparison would miss it, which is why the check span-expands.
.p816
s4_enter:
    sep #$20
    .a8
    lda #7
    sta a:$4204                 ; WRDIVL's port, inside ALU's span: FINDING
    rts
