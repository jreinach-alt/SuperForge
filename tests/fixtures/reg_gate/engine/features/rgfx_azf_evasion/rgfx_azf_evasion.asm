; reg-gate fixture (FIRES twice): a port equate whose name
; starts with a/z/f (case-insensitive), stored bare AND prefixed. The old
; `[azf]?:?` prefix ate the bare spelling's leading `F` (dest `ADE_PORT` =
; nothing) and the store evaded; both spellings must get one verdict. The
; sibling rgfx_azf_declared declares INIDISP, so the refusal also pins the
; "declared elsewhere by" survey path.
.p816
FADE_PORT = $2100               ; INIDISP through an f-initial name
rgfx_azf_fade:
    sep #$20
    .a8
    lda #$0F
    sta FADE_PORT               ; bare spelling — the old evasion: FINDING
    sta a:FADE_PORT             ; prefixed sibling — always fired: FINDING
    rts
