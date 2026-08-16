; SILENT (unnamed ports): It is finding-with-OVERRIDE, not finding-full-stop.
; A port no claim class describes yet has to have an escape hatch, or the
; only way to write one is to invent a footprint name for it.
.p816
.smart

.segment "CODE"
rgfx_unnamed_override_go:
    sep #$20
    .a8
    lda #$FF
    ; REG-LINT: ok — WRIO is deliberately unowned; no claim class describes
    ; the joypad strobe line and this feature is its only writer.
    sta a:$4201
    rts
