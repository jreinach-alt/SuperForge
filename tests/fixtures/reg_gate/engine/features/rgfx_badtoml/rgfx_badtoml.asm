; the file whose declaration does not PARSE. Before this rule it raised
; tomllib.TOMLDecodeError straight through the gate as a traceback
; . A declaration that cannot be READ is a finding, never a
; crash — and the message has to say why falling through would be dangerous.
;
; The toml is stored as feature.toml.malformed so the allocator's
; `*/feature.toml` glob never sees it; the test renames it into a tmp copy.
.p816
.smart

.segment "CODE"
rgfx_badtoml_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2105
    rts
