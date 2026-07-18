; SuperForge — CPU Bootstrap Initialization
;
; Standard SNES CPU initialization sequence. Call RESET as the entry point.
; After this runs:
;   - CPU is in native mode (65816)
;   - 16-bit accumulator and index registers
;   - Stack pointer at $1FFF
;   - Direct Page at $0000
;   - Data Bank at $00
;   - Interrupts disabled
;   - Screen blanked (forced blank)
;
; Context for modification:
;   HW registers: $2100 (INIDISP), $4200 (NMITIMEN), $420D (MEMSEL/FastROM),
;                 $2181-$2183 (WRAM addr), $4300-$4305 (DMA ch0), $420B (DMA enable)
;   Memory: clears ALL 128KB WRAM ($7E:0000-$7F:FFFF) via DMA — this zeroes
;           the stack, register file, debug region, and program area
;   Gotcha: stack pointer is re-set AFTER WRAM clear because DMA zeroed it
;   Gotcha: DMA transfer size $0000 = 65536 bytes (wraps), not zero bytes
;   Gotcha: DMA source uses fixed-address mode ($08) — source byte never advances
;   Cross-ref: header.inc (vectors point here), lorom.cfg (segment layout)

.p816                       ; Enable 65816 mode
.smart                      ; Let ca65 track register widths

.segment "CODE"

NMI_STUB:
NMI:                        ; Default NMI handler (override in real games)
    rti

RESET:
    sei                     ; Disable interrupts
    clc
    xce                     ; Switch to native mode (clear emulation flag)

    ; Set processor status: 16-bit A and X/Y
    rep #$30
    .a16
    .i16

    ; Set stack pointer to top of low RAM
    ldx #$1FFF
    txs

    ; Set Direct Page to $0000 (register file base)
    lda #$0000
    tcd

    ; Set Data Bank to $00
    .a8
    sep #$20
    lda #$00
    pha
    plb
    rep #$20
    .a16

    ; Force screen blank (write $80 to INIDISP / $2100)
    sep #$20
    .a8
    lda #$80
    sta $2100

    ; Canonical full PPU-register power-on init (forced blank above). Writes
    ; every display-affecting $2101-$2133 to a known value so the rendered
    ; frame is deterministic across random cold power-ons (PPU-latch
    ; randomization). Pixel-transparent on the default path (writes = Mesen's
    ; default PPU init). Runs in A8 (forced-blank context); leaves A8.
    ; See docs/sprints/power_on_fullfidelity_plan.md §5.
    .a8
    .include "ppu_reset.inc"

    ; Disable all interrupts on PPU side
    stz $4200               ; NMITIMEN: disable NMI, IRQ, auto-joypad

    ; Enable FastROM (access banks $80-$FF at 3.58 MHz)
    lda #$01
    sta $420D

    ; -----------------------------------------------------------------
    ; Full WRAM clear via DMA ($7E:0000 - $7F:FFFF, 128 KB)
    ; -----------------------------------------------------------------
    ; DMA to WRAM port $2180. Set WRAM address via $2181-$2183.
    ; Source is a zero byte in ROM (fixed source address).
    ; Two passes: bank $7E (64 KB) then bank $7F (64 KB).
    ; -----------------------------------------------------------------
    rep #$20
    .a16

    ; Set WRAM target address to $000000 (bank $7E, offset $0000)
    stz $2181               ; WRAM low/mid address = $0000
    .a8
    sep #$20
    stz $2183               ; WRAM bank bit = 0 (bank $7E)

    ; Configure DMA channel 0
    lda #$08                ; Fixed source, write to single register
    sta $4300               ; DMA0 parameters
    lda #$80                ; Destination: $2180 (WRAM data port)
    sta $4301

    ; Source: address of a zero byte in ROM
    ; Use the ROM padding area which is filled with $00
    ; .loword() extracts bits 0-15; ^label extracts the bank byte.
    ; This works for both LoROM ($00:8xxx) and HiROM ($C0:xxxx).
    rep #$20
    .a16
    lda #.loword(_zero_byte) ; Source address (low 16 bits)
    sta $4302
    .a8
    sep #$20
    lda #^_zero_byte        ; Source bank
    sta $4304

    ; Transfer size: $0000 = 65536 bytes (full bank)
    rep #$20
    .a16
    stz $4305               ; Transfer count = $0000 (wraps to 64KB)

    ; Start DMA channel 0 — clears bank $7E
    .a8
    sep #$20
    lda #$01
    sta $420B               ; DMA enable: channel 0

    ; Now clear bank $7F
    ; Set WRAM bank bit to 1 (bank $7F)
    lda #$01
    sta $2183

    ; Reset source address (DMA modified it, but source is fixed mode so OK)
    ; Reset transfer size
    rep #$20
    .a16
    stz $4305               ; Transfer count = $0000 (64KB again)

    ; Start DMA channel 0 — clears bank $7F
    .a8
    sep #$20
    lda #$01
    sta $420B

    rep #$30
    .a16
    .i16

    ; Re-set stack pointer (WRAM clear zeroed the stack area)
    ldx #$1FFF
    txs

    ; Jump to user code (defined in the test ROM)
    jmp MAIN

; Zero byte source for DMA WRAM clear (lives in ROM, filled with $00)
_zero_byte:
    .byte $00
