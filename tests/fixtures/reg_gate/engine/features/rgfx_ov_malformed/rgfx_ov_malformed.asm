; reg-gate fixture (FIRES): two `; REG-LINT:` comments that parse as
; NEITHER override form. Both writes fire — the failure mode is SAFE — but
; each refusal must now also say that the comment beside it excuses nothing.
;
; The two spellings are the ones the spec measured live:
;   `$-001`     — the sentinel an earlier gate printed as advice, which the
;                 grammar rejects (a port is four hex digits)
;   `ok, reason` — a comma where the separator must be an em dash, `--`,
;                 ` - ` or `:`
.p816
rgfx_ov_malformed_a:
    sep #$20
    .a8
    lda #3
    ; REG-LINT: ok $-001 — the port sentinel is not a port
    sta a:$2106                 ; MOSAIC — fires, and the note fires with it
    rts

rgfx_ov_malformed_b:
    lda #1
    ; REG-LINT: ok, comma is not a separator
    sta a:$2101                 ; OBSEL — same, second spelling
    rts
