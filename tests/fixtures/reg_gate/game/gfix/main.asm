; reg-gate fixture (SILENT): a game top-level file — boot writes NMITIMEN,
; which the GLOBAL feature's reg claim declares (microzero main.asm's shape).
.p816
gfix_boot:
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN — declared by the global's claim
    rts
