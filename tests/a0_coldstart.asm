; =============================================================================
; a0_coldstart.asm — macro library rung A0: boot + debug region
; =============================================================================
; The first vertical-slice rung. It exercises the boot/debug macros from
; lib/macros/sf_core.inc with NO engine linked — proving the keystone's
; lowest layer (cold-boot + debug-region protocol) runs on real emulated
; hardware, not just "assembles cleanly".
;
; Structure (the standard test-ROM pattern, all via macros):
;   RESET -> sf_coldstart      (CPU bring-up + 128 KB WRAM clear)
;         -> sf_debug_magic    (write "SFDB" to $7E:E000)
;         -> sf_debug_complete (write $0001 to $7E:E008)
;         -> STP               (halt CPU)
;
; This ROM owns its own RESET (via sf_coldstart) and wires its own interrupt
; vectors through header.inc, so it does NOT include init.inc. The engine is
; not present, so NMI is never enabled and the handler is a bare RTI stub.
;
; Build (from repo root; -I supplies header.inc / lorom.cfg, this file's dir
; for sf_core.inc):
;   ca65 --cpu 65816 -I infrastructure/rom_template -I asm_repo_staging/lib/macros \
;        asm_repo_staging/tests/a0_coldstart.asm -o a0.o
;   ld65 -C infrastructure/rom_template/lorom.cfg a0.o -o a0.sfc
;
; Verify (MesenRunner):
;   read_bytes(SnesWorkRam, 0xE000, 4) == b"SFDB"
;   read_u16  (SnesWorkRam, 0xE008)    == 1
; =============================================================================

.p816
.smart

; header.inc emits the ROM header + vectors and references RESET / NMI /
; NMI_STUB. It ends in the VECTORS segment, so an explicit `.segment "CODE"`
; must precede our own code.
.include "header.inc"

; The macro library, rung A0.
.include "sf_core.inc"

.segment "CODE"

; --- NMI handler: bare stub. NMI is never enabled in A0 (no engine). ---
NMI:
NMI_STUB:
    rti

; --- RESET: cold-boot, mark the debug region, halt. ---
RESET:
    sf_coldstart            ; native bring-up + WRAM clear; exits A16/I16
    sf_debug_magic          ; "SFDB" -> $7E:E000
    sf_debug_complete       ; $0001  -> $7E:E008
    stp                     ; halt — debug region now holds the result
