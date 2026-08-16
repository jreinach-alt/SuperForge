; reg-gate fixture (FIRES, item 5 rule 1): rl_cgd opens CGDATA
; to scene-enter code and this file writes it too, with no
; `scene_writes_shared`. The write itself is silent -- the feature-strict tier
; is not narrowed and CGDATA is on the claim -- so the ONLY finding is the
; declaration's, exactly as in rgfx_lies.
.p816
rgfx_lies_data_enter:
    sep #$20
    .a8
    lda #$1F
    sta a:$2122                 ; CGDATA — the undeclared co-write
    rts
