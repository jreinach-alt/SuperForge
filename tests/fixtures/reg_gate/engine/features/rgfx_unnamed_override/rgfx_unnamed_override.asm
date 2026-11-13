; SILENT (unnamed ports): It is finding-with-OVERRIDE, not finding-full-stop.
; A port no claim class describes yet has to have an escape hatch, or the
; only way to write one is to invent a footprint name for it.
.p816
.smart

.segment "CODE"
rgfx_unnamed_override_go:
    sep #$20
    .a8
    lda #$01
    ; REG-LINT: ok — MEMSEL is deliberately unowned; no claim class describes
    ; the ROM access speed and this feature is its only writer.
    sta a:$420D
    rts
