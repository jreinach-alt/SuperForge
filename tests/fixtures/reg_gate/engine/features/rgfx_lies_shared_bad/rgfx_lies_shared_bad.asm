; reg-gate fixture (FIRES, item 5 rule 2): M7SEL is declared in
; `scene_writes_shared` and nothing here writes $211A.
.p816
rgfx_lies_shared_bad_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2106                 ; MOSAIC — written, and correctly not shared
    rts
