; reg-gate fixture (FIRES): the ADVICE must name a register the
; OWNING CLAIM HOLDS.
;
; cov_plane holds COLDATA_R -- one PLANE of the $2132 COLDATA port -- and does
; not open it. Four footprint names cover $2132 (COLDATA, COLDATA_B,
; COLDATA_G, COLDATA_R) and the alphabetically-first is COLDATA, which this
; claim does NOT hold: advising `scene_writes = ["COLDATA"]` sends the author
; to an edit `_reject_not_subset` then refuses -- while the same sentence
; asserts, parenthetically, that it is "a subset of its own `registers`".
.p816
s8_enter:
    sep #$20
    .a8
    lda #$1F
    sta a:$2132                 ; COLDATA — owned via the PLANE name: FINDING
    rts
