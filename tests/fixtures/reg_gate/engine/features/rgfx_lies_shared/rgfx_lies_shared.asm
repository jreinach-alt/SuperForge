; reg-gate fixture (SILENT, item 5): identical ASM to rgfx_lies. The only
; difference is one line of TOML -- `scene_writes_shared = ["MOSAIC"]` -- so
; this pair isolates the declaration as the thing under test.
.p816
rgfx_lies_shared_enter:
    sep #$20
    .a8
    lda #$07
    sta a:$2106                 ; MOSAIC — the DECLARED co-write
    rts
