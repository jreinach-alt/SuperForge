; FIRES (unnamed ports): $4201 is WRIO. It is INSIDE io_allowed but carries
; no REGISTER_FOOTPRINT name, so no claim can describe it — and the earlier
; gate `continue`d exactly that case as "unnamed port: unclaimable, exempt".
; That is the census-of-undeclared-writers this allocator exists to abolish,
; re-entering through the one door the gate left open. Silence is how the next
; census grows.
;
; NOTE the settlement's own worked example ($4016/$4017) can never reach this
; branch — it sits OUTSIDE io_allowed, so the ADDRESS rule refuses it first.
; Found by running the plant, not by reading the code.
.p816
.smart

.segment "CODE"
rgfx_unnamed_fires_go:
    sep #$20
    .a8
    lda #$FF
    sta a:$4201
    rts
