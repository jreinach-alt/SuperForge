; =============================================================================
; audio — TAD ca65 API compilation unit + the allocator<->linker bridge
; =============================================================================
; Assembled as a SEPARATE object: the vendored tad-audio.s defines its own
; .bss/.zeropage reservations and must not inherit main.asm's segment or width
; state. It is NOT .included anywhere.
;
; The bridge asserts are the load-bearing part. TAD's 16 B .bss + 2 B
; .zeropage are placed by the LINKER (vendor/rom/lorom_512k.cfg's TADBSS /
; TADZP windows), while the allocator arbitrates the same ranges through the
; audio feature's pinned tad_bss / tad_zp claims (feature.toml `at=`). The two
; are bridged here at link time: if the cfg window, the pin, or a TAD upgrade's
; layout ever disagree, the build REFUSES instead of silently double-booking
; lowram — the failure class a hand-managed window invites, where nothing
; connects the linker cfg to the driver's own declared layout and the two
; drift apart at the next upgrade.
.p816
.smart

.include "engine_state_globals.inc"     ; ES_TAD_* — the allocator's pins

; TAD memory-map + segment configuration (must precede the include).
LOROM = 1
.define TAD_CODE_SEGMENT "CODE"
.define TAD_PROCESS_SEGMENT "CODE"

.include "tad-audio.s"                  ; vendor/tad — unmodified upstream

; --- the allocator<->linker bridge ------------------------------------------
; Tad_flags is the FIRST .bss symbol tad-audio.s declares and Tad_sfxQueue_sfx
; the first .zeropage one, so equality against the pin means the whole block
; sits inside the claim; the cfg window SIZES bound the far end (ld65 refuses a
; segment overflow if a TAD upgrade grows them).
.assert Tad_flags = ES_TAD_BSS, lderror, "TAD .bss drifted from the allocator's tad_bss pin ($1F00): cfg TADBSS window vs engine/features/audio/feature.toml at="
.assert Tad_sfxQueue_sfx = ES_TAD_ZP, lderror, "TAD .zeropage drifted from the allocator's tad_zp pin ($F0): cfg TADZP window vs engine/features/audio/feature.toml at="
