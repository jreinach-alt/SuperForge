; =============================================================================
; smoke.asm — toolchain pipeline smoke test ROM
; =============================================================================
; Hand-written 65816 assembly (no macros) proving the end-to-end pipeline:
;   ca65 -> ld65 -> .sfc -> MesenRunner boot -> debug-magic readback.
;
; It is deliberately minimal: it does NOT exercise any engine, asset, or
; rendering subsystem. Its only job is to confirm that the assembler, linker,
; ROM template (header.inc / init.inc / lorom.cfg), and the emulator harness
; agree on the boot contract — so every later ROM can trust the pipeline.
;
; Boot contract (the standard test-ROM pattern):
;   RESET (init.inc) -> SEI/CLC/XCE native, 16-bit A/X, stack, DP=$0000,
;                       DB=$00, forced blank, full WRAM clear -> jmp MAIN
;   MAIN              -> write "SFDB" magic to $7E:E000
;                     -> write completion flag $0001 to $7E:E008
;                     -> STP (halt CPU)
;
; Debug region ($7E:E000+):
;   $E000-$E003: "SFDB" magic        (proves MAIN ran and reached the writes)
;   $E008-$E009: completion flag $0001 (proves MAIN ran to the end)
;
; Build (from repo root; -I supplies header.inc / init.inc / lorom.cfg):
;   ca65 -I infrastructure/rom_template tests/smoke.asm -o smoke.o
;   ld65 -C infrastructure/rom_template/lorom.cfg smoke.o -o smoke.sfc
;
; Verify (MesenRunner):
;   read_bytes(SnesWorkRam, 0xE000, 4) == b"SFDB"
;   read_u16  (SnesWorkRam, 0xE008)    == 1
; =============================================================================

.p816
.smart

; header.inc emits the ROM header + interrupt vectors and references the
; RESET / NMI / NMI_STUB labels that init.inc defines. It ends in the VECTORS
; segment, so an explicit `.segment "CODE"` must precede any of our own code.
.include "header.inc"

; init.inc supplies RESET (native-mode bring-up + full WRAM clear), the NMI /
; NMI_STUB stubs, and finishes with `jmp MAIN`. We only author MAIN below.
.include "init.inc"

; -----------------------------------------------------------------------------
; Debug region layout (WRAM bank $7E)
; -----------------------------------------------------------------------------
DEBUG_MAGIC      = $E000        ; "SFDB" (4 bytes)
DEBUG_COMPLETE   = $E008        ; completion flag (2 bytes)

; =============================================================================
; MAIN — entry from init.inc (native mode, A/X/Y 16-bit, DP=$0000, DB=$00)
; =============================================================================
; WRAM above $8000 in bank $00 maps to ROM under LoROM, so reaching $7E:E000
; needs full 24-bit long addressing. With DB=$00 a bare `sta f:$7Exxxx` can be
; mis-encoded as DB-relative STA abs (hitting I/O), so we use the reliable
; `ldx #0` + `sta f:$7E0000 + addr, x` form (opcode $9F, absolute-long,X) which
; ca65 always encodes as a true 24-bit access.

.segment "CODE"

MAIN:
    ; A is 16-bit on entry from init.inc (.a16 / .i16 in effect).
    rep #$30
    .a16
    .i16

    ldx #$0000              ; X = 0 so the ",x" forces absolute-long encoding

    ; --- Write "SFDB" magic to $7E:E000 (little-endian: "SF" then "DB") ---
    lda #$4653              ; 'S'=$53 low, 'F'=$46 high -> bytes $53,$46 = "SF"
    sta f:$7E0000 + DEBUG_MAGIC, x
    lda #$4244              ; 'D'=$44 low, 'B'=$42 high -> bytes $44,$42 = "DB"
    sta f:$7E0000 + DEBUG_MAGIC + 2, x

    ; --- Set completion flag $0001 at $7E:E008 ---
    lda #$0001
    sta f:$7E0000 + DEBUG_COMPLETE, x

    ; Halt the CPU. The debug region now holds the verifiable result.
    stp
