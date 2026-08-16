; reg-gate fixture (FIRES): an undeclared CPU write to a footprint-named port.
; The exact shape of docs/09 §2.1 hole 1 — the feature simply does not declare.
.p816
rgfx_fires_arm:
    sep #$20
    .a8
    lda #1
    sta a:$2105                 ; BGMODE — no [[claims.reg]] here: FINDING
    rts
