; reg-gate fixture (SILENT): an a-initial symbol for a DECLARED port, bare
; and prefixed. Under the old `[azf]?:?` the bare spelling mis-parsed as
; `FADE_LEVEL` and was silent for the WRONG reason; the atomic prefix must
; resolve `AFADE_LEVEL` -> $2100 and find it declared — silent for the
; RIGHT reason, exactly one parse per store.
.p816
AFADE_LEVEL = $2100             ; INIDISP through an a-initial name
rgfx_azfd_arm:
    sep #$20
    .a8
    lda #$0F
    sta AFADE_LEVEL             ; bare a-initial symbol — declared: silent
    sta a:AFADE_LEVEL           ; prefixed — same verdict: silent
    rts
