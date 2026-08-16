; reg-gate fixture (FIRES, item 5 / M4b): THE DISCRIMINATING SIBLING.
;
; $212C TM is covered by a transfer claim of feature `rgfx_cov`, and the SAME
; feature opens TM on a [[claims.reg]] — but does NOT list it in that claim's
; `scene_writes`. The two readings of the covered rule diverge here and only
; here:
;
;   WEAK   "keep it if the same feature opens that register on a
;           [[claims.reg]]"                                  -> exit 0
;   STRONG "...and lists it in that claim's scene_writes"     -> exit 1
;
; The STRONG reading is what was built, so this fixture expects exit 1. Consent is
; uniform across both arms: an HDMA owner that merely happens to hold a reg
; claim cannot grant scene writes it never consented to — which is the precise
; gap this change exists to close, reopened on the arm it was extended to
; cover.
;
; This fixture is REQUIRED rather than optional. s5 next door is `declared`
; AND `covered` and exits 0 under both readings, so it cannot fail under
; either — and a gate whose fixture cannot fail is the "trusting a green test
; you have not tried to break" anti-pattern.
.p816
s7_enter:
    sep #$20
    .a8
    lda #$11
    sta a:$212C                 ; TM — covered + reg-claimed, NOT opened: FINDING
    rts
