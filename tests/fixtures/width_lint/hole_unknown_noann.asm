; hole 2: one UNKNOWN + one known A16 arrival, no annotation
; at all. The old check dropped the UNKNOWN component, saw a single-element
; mode set, and never examined the label — not even for presence.
; MUST FIRE [unknown-arrival] (severity=warn, still gates).
.p816
.smart
.segment "CODE"
entry:
    bne shared                  ; arrives (unknown/unknown) — no width declared yet
    rep #$20
    .a16
    lda #$1234
    bra shared                  ; arrives A16
shared:
    lda #$34
    rts
