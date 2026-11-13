; FIRES (unnamed ports): $420D is MEMSEL. It is INSIDE io_allowed but carries
; no REGISTER_FOOTPRINT name, so no claim can describe it — and the earlier
; gate `continue`d exactly that case as "unnamed port: unclaimable, exempt".
; That is the census-of-undeclared-writers this allocator exists to abolish,
; re-entering through the one door the gate left open. Silence is how the next
; census grows.
;
; NOTE the settlement's own worked example ($4016/$4017) never reached this
; branch while it sat OUTSIDE io_allowed — the ADDRESS rule refused it first.
; Found by running the plant, not by reading the code. This fixture's port
; was $4201 (WRIO) until docs/102 named both WRIO and the joypad pair
; (JOYSER) in REGISTER_FOOTPRINT for the four-pad adapter; MEMSEL is the
; unnamed port that took its place.
.p816
.smart

.segment "CODE"
rgfx_unnamed_fires_go:
    sep #$20
    .a8
    lda #$01
    sta a:$420D
    rts
