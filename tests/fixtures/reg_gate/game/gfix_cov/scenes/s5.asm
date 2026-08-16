; reg-gate fixture (SILENT, item 5 / M4b): the silent sibling — race's BGMODE
; shape. The port is covered by a transfer claim AND opened by a
; [[claims.reg]] whose `scene_writes` lists it, so scene-enter code may seed it.
;
; NOTE for the reader, and it is the point of s7 next door: this fixture is
; `declared` AND `covered`, so it exits 0 under BOTH readings of the covered
; rule and CANNOT discriminate between them. It proves M4b did not disable the
; arm; it does not pin which reading was built. s7 does that.
.p816
s5_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2105                 ; BGMODE — covered, and opened: SILENT
    rts
