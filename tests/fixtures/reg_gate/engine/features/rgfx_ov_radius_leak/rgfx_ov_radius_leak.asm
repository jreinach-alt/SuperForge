; FIRES (port-scoped override): the both-sides-missed MEDIUM, as a fixture.
; convergence §4.4 item 1, probe fp12_radius — BOTH gates gave 0 findings.
;
; MOSAIC is DECLARED above, so the override on its line is honest about ITS
; site. OBSEL ($2101) is NOT declared and sits one line later, inside the
; ±3-line radius. Before this rule, the MOSAIC override silenced the OBSEL write:
; a reviewer reading a stated MOSAIC reason had no cue an unrelated write was
; riding on it — the rubber-stamping regression the override convention warns
; about. The override is now bound to the write on its own line.
.p816
.smart

.segment "CODE"
rgfx_ov_radius_leak_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2106                 ; REG-LINT: ok — MOSAIC is safe by construction
    sta a:$2101
    rts
