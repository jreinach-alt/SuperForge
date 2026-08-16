; wl_stz_long.asm — regression fixture for width_lint Check 4 (stz-long).
;
; STZ has no absolute-long addressing mode. ca65 rejects each of the lines
; below with a bare "Illegal addressing mode" that does not name STZ — the
; exact friction Mode-1 streaming work hit twice. The linter
; must flag them at lint time and name the `lda #0` + `sta f:...,x` fix.
;
; The legal STZ forms further down MUST NOT be flagged.

.p816
.smart
.segment "CODE"

_bad_stz:
    stz f:$7E0008                   ; forced long  -> illegal (S1 repro)
    stz f:$7E0000 + 8, x            ; forced long indexed -> illegal (S2a repro)
    stz $7E0008                     ; abs-long literal -> illegal
    rts

; --- legal forms below: none of these may be flagged ---
_good_stz:
    stz a:$2102                     ; forced absolute (16-bit) — legal
    stz a:$0F00                     ; forced absolute — legal
    stz <$10                        ; forced direct page — legal ; ZP-LINT: ok — width-lint fixture, illustrative DP example
    stz $10                         ; ca65 picks dp — legal ; ZP-LINT: ok — width-lint fixture, illustrative DP example
    stz $2102                       ; ca65 picks abs — legal
    rts

; --- override: a flagged site verified safe-by-construction ---
_overridden:
    stz f:$7E0010                   ; WIDTH-LINT: ok — fixture override case
    rts
