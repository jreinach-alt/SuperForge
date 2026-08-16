; reg-gate fixture (SILENT): every write here rides a claim this feature
; actually holds — the latches and the data ports on the vram/cgram/oam region
; claims, OBSEL on its [[claims.reg]]. Nothing here may flag; this is the
; false-positive guard for the whole reg pass, so it is also the file a reader
; opens to learn the rule.
;
; NOTE the latches are silent BY THE RULE, not by exemption. That category deleted
; "no footprint name -> unclaimable, exempt": a latch is the *where* of a data
; port and rides the claim on the RESOURCE that port serves. Delete the
; [[claims.vram]] below and $2115/$2116 FIRE.
.p816
rgfx_covered_upload:
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN — vram latch: rides the vram claim
    ldx #0
    stx $2116                   ; VMADDL — vram latch: rides the vram claim
    lda #$41
    sta $2118                   ; VMDATAL — covered by the vram claim
    sta $2119                   ; VMDATAH — covered by the vram claim
    stz $2121                   ; CGADD — cgram latch: rides the cgram claim
    sta $2122                   ; CGDATA — covered by the cgram claim
    sta $2104                   ; OAMDATA — covered by the oam claim
    lda #2
    sta $2101                   ; OBSEL — declared by rgfx_covered_obsel
    rts
