; reg-gate fixture (FIRES): an undeclared port write spelled through a
; file-local equate. Must get the same verdict as `sta a:$2105`.
.p816
RGFX_MODE_PORT = $2100 + 5      ; = $2105 BGMODE, additively spelled
rgfx_alias_arm:
    sep #$20
    .a8
    lda #1
    sta a:RGFX_MODE_PORT        ; BGMODE through the alias: FINDING
    rts
