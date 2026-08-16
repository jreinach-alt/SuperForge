; reg-gate fixture (FIRES, item 5 rule 1): rl_mode opens MOSAIC to
; scene-enter code and this file writes it too, with no `scene_writes_shared`.
; The write itself is fine -- the feature-strict tier is not narrowed, and
; MOSAIC is on the claim -- so the ONLY finding is the declaration's.
.p816
rgfx_lies_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2106                 ; MOSAIC — the undeclared co-write
    rts
