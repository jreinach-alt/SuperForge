; sram_hdr fixture ROM — exists to be LINKED, so the test can read the cart
; header bytes ($FFD6 cart type, $FFD8 SRAM size) out of a real .sfc. The
; generated globals inc (included first) carries the allocator-derived
; SF_HDR_* symbols; header.inc's .ifndef defaults pick them up.
.p816
.smart

.define SF_HDR_TITLE "SRAM HDR FIXTURE"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc" ; GENERATED — carries SF_HDR_SRAM_SIZE etc.
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

NMI_STUB:
NMI:
    rti

MAIN:
    .a16
    .i16
@loop:
    bra @loop
