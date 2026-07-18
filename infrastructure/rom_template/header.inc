; SuperForge — SNES ROM Header and Vector Table
;
; Include this file in every ROM to produce valid LoROM headers.
; The assembler will place these in the HEADER and VECTORS segments
; which the linker maps to $00FFC0-$00FFFF.
;
; Usage:
;   .include "header.inc"
;   (after defining RESET and NMI labels in your CODE segment)
;
; Context for modification:
;   Requires labels: RESET (entry point), NMI (VBlank handler), NMI_STUB (RTI)
;   Map mode $30 = LoROM + FastROM (3.58 MHz for ROM-bank accesses)
;   Gotcha: checksum/complement are placeholders ($FFFF/$0000) — real ROMs
;           need a checksum fixup tool; emulators tolerate invalid checksums
;   Cross-ref: init.inc (defines RESET, NMI, NMI_STUB), lorom.cfg (segment map)
;
; OPT-IN IRQ VECTOR (additive; default byte-identical):
;   The native-mode IRQ vector ($FFEE) defaults to NMI_STUB. A ROM that wants
;   a scanline (H/V-count) IRQ handler defines the override BEFORE including
;   this file — a forward reference to a label defined later is fine:
;
;       SF_IRQ_VECTOR = my_irq_handler
;       .include "header.inc"
;
;   The handler must end in RTI and ack the IRQ by reading TIMEUP ($4211).
;   Enable via NMITIMEN $4200 bits $20 (V-count) / $10 (H+V) — compose bits
;   through a shadow (SHADOW_NMITIMEN in engine_state.inc), never blind-store
;   $4200 — and remember CLI: the standard coldstart's SEI masks IRQ until
;   the main thread unmasks it. The emulation-mode vector ($FFFE) stays on
;   the stub — this platform runs native mode only.

; ============================================================
; Internal ROM Header ($00FFC0 - $00FFDF, 32 bytes)
; ============================================================
.segment "HEADER"

; Bytes $FFC0-$FFD4: ROM title (21 bytes, padded with spaces)
.byte "SUPERFORGE TEST      "

; Byte $FFD5: Map mode
;   Bits 0-3: Map type ($0 = LoROM)
;   Bit 4:    Speed ($1 = FastROM / 3.58 MHz)
;   Value $30 = LoROM + FastROM
.byte $30

; Byte $FFD6: Cartridge type
;   $02 = ROM + SRAM (kit default — battery-less games still declare it so
;   the save-capable link shapes need no header variant; emulators size
;   SRAM from $FFD8)
; OPT-IN OVERRIDE (additive; default byte-identical): define BEFORE the
; include — or just .include "header_jam.inc" — for a ROM-only header
; ($00/$00), e.g. for jam/multicart rules that forbid SRAM.
.ifndef SF_HDR_CART_TYPE
SF_HDR_CART_TYPE = $02
.endif
.byte SF_HDR_CART_TYPE

; Byte $FFD7: ROM size (log2 of KB)
;   $08 = 2^8 = 256 KB (we use 32KB but declare larger for compatibility)
.byte $08

; Byte $FFD8: SRAM size (log2 of KB)
;   $03 = 2^3 = 8 KB (4 save slots x 2 KB each); $00 = no SRAM
.ifndef SF_HDR_SRAM_SIZE
SF_HDR_SRAM_SIZE = $03
.endif
.byte SF_HDR_SRAM_SIZE

; Byte $FFD9: Destination code
;   $01 = North America
.byte $01

; Byte $FFDA: Fixed value ($33 for extended header, $00 otherwise)
.byte $33

; Byte $FFDB: ROM version
.byte $00

; Bytes $FFDC-$FFDD: Checksum complement (filled by tool or set to $FFFF)
.word $FFFF

; Bytes $FFDE-$FFDF: Checksum (filled by tool or set to $0000)
.word $0000

; ============================================================
; Interrupt Vectors ($00FFE0 - $00FFFF, 32 bytes)
; ============================================================
.segment "VECTORS"

; --- Native mode vectors ($FFE0-$FFEF) ---
.word $0000         ; $FFE0: reserved
.word $0000         ; $FFE2: reserved
.word NMI_STUB      ; $FFE4: COP      (unused, stub)
.word NMI_STUB      ; $FFE6: BRK      (unused, stub)
.word NMI_STUB      ; $FFE8: ABORT    (unused, stub)
.word NMI           ; $FFEA: NMI      (VBlank interrupt)
.word $0000         ; $FFEC: reserved
; IRQ vector: NMI_STUB unless the ROM defined SF_IRQ_VECTOR before the
; include (see "OPT-IN IRQ VECTOR" above). Default emits the exact same
; word as the old hardwired `.word NMI_STUB` — existing ROMs byte-identical.
.ifndef SF_IRQ_VECTOR
SF_IRQ_VECTOR = NMI_STUB
.endif
.word SF_IRQ_VECTOR ; $FFEE: IRQ      (opt-in; stub by default)

; --- Emulation mode vectors ($FFF0-$FFFF) ---
.word $0000         ; $FFF0: reserved
.word $0000         ; $FFF2: reserved
.word NMI_STUB      ; $FFF4: COP
.word $0000         ; $FFF6: reserved
.word NMI_STUB      ; $FFF8: ABORT
.word NMI_STUB      ; $FFFA: NMI
.word RESET         ; $FFFC: RESET    (power-on entry point)
.word NMI_STUB      ; $FFFE: IRQ/BRK
