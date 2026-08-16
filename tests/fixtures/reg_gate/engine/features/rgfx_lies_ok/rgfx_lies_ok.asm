; reg-gate fixture (SILENT, item 5): MOSAIC is on the claim but not opened,
; so the owner writing it is not a lie -- it is the default.
.p816
rgfx_lies_ok_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2106                 ; MOSAIC — owned, unopened, owner-written
    rts
