; reg-gate fixture (SILENT): scene writes covered by the scene's UNION —
; an OPENED reg port (M7SEL, in its claim's scene_writes), a covered data port
; (CGDATA via a cgram placement), and the latch that rides that same
; placement (CGADD — silent by the latch/data resource rule, not by exemption).
.p816
s1_enter:
    sep #$20
    .a8
    stz $211A                   ; M7SEL — declared in the scene union
    lda #$00
    sta $2121                   ; CGADD — cgram latch: rides the placement
    lda #$7F
    sta $2122                   ; CGDATA — covered: the scene holds cgram
    lda #$81
    sta a:$4200                 ; NMITIMEN — OPENED by glob_nmi's scene_writes
    rts
