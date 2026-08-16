; rom-backing fixture — the OUT-OF-SCOPE compilation unit.
;
; The stand-in for `tad_export`'s real shape (docs/37 §3 case 1): a unit that
; supplies a claim's bytes while sitting OUTSIDE the no_literals scope, whose
; claim site is a linker segment rather than an `ES_R_*` assert. It is
; deliberately absent from BOTH arms' file lists — `make rom-unbacked` never
; passes this file to the gate — so `fixture_extern` can only be accounted for
; by its declared `backed_by`, which is the thing under test.
;
; It exists as a FILE rather than as prose because `backed_by` must now cite a
; path that resolves: the hatch suppresses a claim's entire
; presence check from a feature.toml an ASM reviewer never opens, so the
; statement has to be falsifiable. A fixture whose citation pointed at nothing
; would be the fixture teaching the shape the check exists to refuse.
;
; Never assembled: fixture_extern.bin does not exist, and the gate reads text.
.p816
.smart

.segment "BANK9"
fixture_extern_bin:
    .incbin "fixture_extern.bin"
