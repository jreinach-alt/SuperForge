; SILENT (RMW writes): the same RMW writes, DECLARED. Proves the new mnemonics
; go through the same ownership check as a store rather than becoming an
; unconditional finding — and that accumulator-mode RMW (`lsr a`, 39 live
; sites) and DP-symbol RMW (`asl z:SYM`) never resolve to a port.
.p816
.smart

.segment "CODE"
rgfx_rmw_silent_go:
    sep #$20
    .a8
    inc a:$2106
    trb a:$2106
    lsr a
    asl a
    rts
