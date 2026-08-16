; FIRES (WRAM port pair): WMDATA + WMADDL with no `wram` claim.
; Latent — no in-tree site writes $2180-$2183 today — but WMDATA/WMADD* are a
; SINGLE GLOBAL CURSOR, so two undeclared users is exactly the silent fight
; claims.reg exists to refuse .
.p816
.smart

.segment "CODE"
rgfx_wmdata_fires_go:
    sep #$20
    .a8
    lda #$00
    sta a:$2181
    lda #$42
    sta a:$2180
    rts
