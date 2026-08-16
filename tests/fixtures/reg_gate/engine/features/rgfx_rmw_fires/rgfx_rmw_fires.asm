; FIRES (RMW writes): read-modify-WRITE instructions targeting an undeclared PPU
; port. `inc a:$2106` and `trb a:$2106` are real 65816 instructions that write
; MOSAIC, and the earlier gate — whose write set was sta/stx/sty/stz — could
; not see them at all .
;
; Latent in this tree: zero live RMW instructions target an io port today
; (every one is accumulator-mode or a DP symbol). The fixture is the whole
; coverage, which is why it has to exist.
.p816
.smart

.segment "CODE"
rgfx_rmw_fires_go:
    sep #$20
    .a8
    inc a:$2106
    trb a:$2106
    rts
