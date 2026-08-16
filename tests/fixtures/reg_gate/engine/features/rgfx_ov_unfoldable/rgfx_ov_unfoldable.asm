; FIRES: the fold's sentinel meeting the override's ambiguity rule.
;
; `sta a:$2100 + STRIDE` will not fold, so `_store_port` returns the internal
; UNRESOLVED_PORT sentinel; the undeclared `sta a:$2101` one line later shares
; the standalone override's ±3-line window. Two subjects, so rule 3 refuses
; both — correctly. What was WRONG is what it then said: the sentinel was
; formatted as an address, so the refusal named a port `$-001` that no reader
; can look up, and told the author to type `; REG-LINT: ok $-001 — <reason>`,
; a spelling `_override_res`'s `\$(?P<port>[0-9A-Fa-f]+)` rejects — leaving
; the override SILENTLY IGNORED, which is the exact shape of un-followable
; advice `_reg_verdict` guards against one function over.
;
; A write whose port will not fold has NO port to name, so rule 1 is
; unreachable for it by construction and the refusal has to say so and point
; at the escape hatch that does work: the same-line form (rule 2).
.p816
.smart

.segment "CODE"
rgfx_ov_unfoldable_go:
    sep #$20
    .a8
    lda #$01
    ; REG-LINT: ok — one of these is safe by construction, but which?
    sta a:$2100 + STRIDE
    sta a:$2101
    rts
