; reg-gate fixture (FIRES): the NAME axis on the transfer branch.
;
; cov_rplane drives COLDATA_R as an hdma claim and nothing holds a
; [[claims.reg]] on $2132, so the reachable fix is a seed'd reg claim -- and it
; has to name COLDATA_R, the name the transfer claim actually holds. A reg
; claim naming a plane the transfer does NOT drive would contend with nothing,
; and `seed = true` with nothing to override is itself refused
; ("a seed says 'another declared claim overwrites this base value', and
; nothing here does").
.p816
s10_enter:
    sep #$20
    .a8
    lda #$3F
    sta a:$2132                 ; COLDATA — hdma-covered via a PLANE: FINDING
    rts
