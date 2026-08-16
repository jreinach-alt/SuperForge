; reg-gate fixture (FIRES): the advice must be followable across
; the transfer KIND too.
;
; cov_init drives BGMODE as a claims.dma_init. `seed` exempts an hdma
; overrider and does NOT exempt a dma_init -- check_reg_ownership calls it "a
; one-shot enter-time ESTABLISHER, not an ongoing overrider" -- so the
; seed'd-separate-claim advice the hdma case gets would be refused by the
; build here. This scene pins that the refusal says the thing that IS
; reachable instead.
.p816
s9_enter:
    sep #$20
    .a8
    lda #$09
    sta a:$2105                 ; BGMODE — covered by a dma_init only: FINDING
    rts
