; rom-backing fixture — the CONTROL arm. Every claim that needs a claim site
; has one, in the shape the tree already uses. `make rom-unbacked` requires
; this file to be ACCEPTED, so a gate that refuses everything cannot pass by
; refusing the other arm.
;
; Never assembled: the gate reads text, and the .bin files named here do not
; exist. Keep it free of instructions — this fixture's subject is claim sites,
; and an io write here would drag in the reg-ownership pass for no reason.
.p816
.smart

.segment "BANK1"
fixture_blob_bin:
    .incbin "fixture_blob.bin"
.assert ^fixture_blob_bin = ES_R_FIXTURE_BLOB_BANK, error, "fixture_blob bank drifted"
.assert .loword(fixture_blob_bin) = ES_R_FIXTURE_BLOB_ADDR, error, "fixture_blob addr drifted"

; the templated claim site: the chunk symbols appear ONLY inside .sprintf
.repeat ES_R_FIXTURE_TILES_CHUNKS, TI
.segment .sprintf("BANK%d", TI + 2)
.ident(.sprintf("fixture_tiles_t%d", TI)):
    .incbin "fixture_tiles.bin", TI * 32768, 32768
.assert ^.ident(.sprintf("fixture_tiles_t%d", TI)) = .ident(.sprintf("ES_R_FIXTURE_TILES_T%d_BANK", TI)), error, "tile chunk bank drifted"
.endrepeat

; fixture_extern has NO claim site here on purpose — its feature.toml declares
; `backed_by`, and that declaration is what must carry it.
