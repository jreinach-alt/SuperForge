; FIRES: two DISTINCT writes that will not
; fold, with a same-line override on the FIRST.
;
; The sentinel was the identity, so `-1 == -1` made every unfoldable write in
; a file the SAME subject: rule 2 matched this override against the NEXT
; line's write and returned "excused". Measured on the pre-fix branch — ZERO
; findings for both, and the second line is `sta a:$2107 - 1`, which IS a
; MOSAIC write and is the fold's own sharpest case (before it, this produced no
; finding of any kind, because the ADDRESS rule permits $2107 as an io
; literal). An override reading "this one is safe" silenced a different write
; the author never mentioned.
;
; A site whose port will not fold is identified by its LINE (`_site_id`), so
; the override binds to line 1 of the pair and the second FIRES. Rule 3 has
; the same shape: two unfoldable sites are two members of the radius set, not
; one, so a standalone override over them is AMBIGUOUS rather than silently
; covering both.
.p816
.smart

.segment "CODE"
rgfx_ov_unfold_pair_go:
    sep #$20
    .a8
    lda #$01
    sta a:$2100 + STRIDE        ; REG-LINT: ok — this one is safe by construction
    sta a:$2107 - 1
    rts
