; reg-gate fixture (SILENT): the data half under a TRANSFER
; claim rather than a placement.
;
; s11's closure holds no cgram placement at all -- the only thing naming
; CGDATA is an hdma claim. The write is silent on the RESOURCE route
; (`satisfies_resource`), because both union tiers put a transfer claim's
; registers into `names`. That is the route `_transfer_covered`'s deleted
; non-in-class arm duplicated: it added these same ports to `covered` one rule
; earlier and no fixture could tell the two spellings apart. This one pins the
; route that actually decides.
.p816
s11_enter:
    sep #$20
    .a8
    lda #$00
    sta a:$2121                 ; CGADD — the latch rides the same name
    lda #$7F
    sta a:$2122                 ; CGDATA — named by an hdma claim: SILENT
    rts
