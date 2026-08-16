; SILENT (override rule 1): the override NAMES this build it excuses.
; `; REG-LINT: ok $2101 — reason` is unambiguous wherever it sits, and is the
; spelling the ambiguous-case diagnostic tells the author to reach for.
; The second write is declared-by-nobody too but names a DIFFERENT port, so
; the named override must NOT cover it — that is the whole point of naming.
.p816
.smart

.segment "CODE"
rgfx_ov_named_port_go:
    sep #$20
    .a8
    ; REG-LINT: ok $2101 — OBSEL is set once at boot by this feature alone
    lda #$01
    sta a:$2101
    rts
