; reg-gate fixture (FIRES, item 5): the scene's closure OWNS this port —
; glob_nmi's [[claims.reg]] holds INIDISP — but the claim's `scene_writes`
; does not open it, so scene-enter code has no permission to write it.
;
; This is the shape docs/09 §2.1 hole 2 was the absence of: before item 5 the
; gate asked only "did someone in this scene declare this port", so a scene
; was an unlimited second writer of every port its closure happened to own.
; The neighbouring NMITIMEN write IS opened and must stay silent — the same
; claim, one register opened and one not, which is why the field is a LIST.
.p816
s3_enter:
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN — opened: SILENT
    lda #$0F
    sta a:$2100                 ; INIDISP — owned, NOT opened: FINDING
    rts
