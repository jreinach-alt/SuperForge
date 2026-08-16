; The sibling case: a toml that PARSES
; but whose types are wrong (`registers` a string, not a list). It tracebacks
; on the UNLANDED gate; on this side schemas.load_feature's type validation
; already turns it into a clean SchemaError finding, and that rule's
; AttributeError/TypeError catch is the belt-and-braces that keeps a future
; loader change from reopening it as a traceback.
.p816
.smart

.segment "CODE"
rgfx_wrongtype_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2105
    rts
