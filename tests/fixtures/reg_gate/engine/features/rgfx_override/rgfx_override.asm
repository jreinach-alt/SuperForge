; reg-gate fixture (SILENT): `; REG-LINT: ok — reason` suppresses within
; 3 lines, matching the width/zp/channel convention.
.p816
rgfx_ov_arm:
    sep #$20
    .a8
    lda #3
    ; REG-LINT: ok — fixture demonstrating the override hatch, not a claim
    sta a:$2106                 ; MOSAIC — overridden with a reason
    rts
