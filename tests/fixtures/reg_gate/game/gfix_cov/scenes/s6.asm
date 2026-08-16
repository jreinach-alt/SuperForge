; reg-gate fixture (SILENT, item 5 / M4b): the region data half is NOT
; narrowed. CGDATA is covered by the closure's `cgram` placement — a latch or
; data port rides the claim on the RESOURCE its data port serves, which is a
; statement about hardware structure rather than about who may write it.
; Narrowing it would refuse every shipped upload path. residue of that rule.
.p816
s6_enter:
    sep #$20
    .a8
    lda #$00
    sta a:$2121                 ; CGADD — the latch rides the same placement
    lda #$7F
    sta a:$2122                 ; CGDATA — region data port: SILENT
    rts
