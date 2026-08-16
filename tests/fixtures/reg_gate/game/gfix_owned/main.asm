; reg-gate fixture (FIRES, item 5): boot writes NMITIMEN, which the global's
; claim OPENS, beside INIDISP, which the same claim HOLDS but does not open.
;
; This is scene_mgr's sm_display shape exactly, and it is why `scene_writes`
; is a list of registers rather than a boolean on the claim: boot must write
; NMITIMEN, and INIDISP is committed by playtesting's own NMI hook every frame
; (the enter-time-INIDISP hazard docs/09 §2.1 names). One claim, one register
; opened, one not. The diagnostic must name INIDISP ALONE.
.p816
gfix_owned_boot:
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN — opened: SILENT
    lda #$8F
    sta a:$2100                 ; INIDISP — owned, NOT opened: FINDING
    rts
