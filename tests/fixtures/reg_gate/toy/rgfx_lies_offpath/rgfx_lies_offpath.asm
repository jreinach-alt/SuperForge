; reg-gate fixture (FIRES): M7SEL is declared in
; `scene_writes_shared` and nothing here writes $211A.
;
; The MOSAIC write below carries a reasoned override, because this path shape
; takes the COMPOSED-UNION tier (no engine/features/<name>/ ancestry, so no
; feature-strict context) and the ownership finding would otherwise crowd the
; declaration finding this fixture is about. The override deliberately does NOT
; excuse the lies-check: `_owner_write_ports` ignores overrides, because
; "is this declaration true of the code" is a different question from "is this
; write allowed".
.p816
rgfx_lies_offpath_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2106                 ; REG-LINT: ok — fixture: the ownership verdict
                                ; is not what this fixture is about
    rts
