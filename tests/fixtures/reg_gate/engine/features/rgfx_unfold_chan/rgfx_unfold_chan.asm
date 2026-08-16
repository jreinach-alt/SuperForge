; SILENT (expression fold): the tree's OWN idiom for a channel's register file —
; `<FEAT>_REGS = $4300 + ES_[HD]_<CLAIM>_CH * 16`. The offset is unfoldable,
; but the whole $4300-$437F extent belongs to the channel rules, so it
; resolves to the base and is handed on rather than failing closed.
; 115 live sites in this tree are this exact shape; a fold that failed closed
; on them would have made this build unlandable.
.p816
.smart
.import ES_H_FAKE_CH

.segment "CODE"
FAKE_REGS = $4300 + ES_H_FAKE_CH * 16

rgfx_unfold_chan_go:
    sep #$20
    .a8
    lda #$02
    sta a:FAKE_REGS + 0
    lda #$18
    sta a:FAKE_REGS + 1
    rts
