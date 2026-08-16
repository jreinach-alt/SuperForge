; superforge — CPU bootstrap.
;
; DELIBERATE, and unusual: NO blanket 128 KB WRAM zero-clear.
; superforge's power-on-fidelity invariant is init-BY-CONTRACT:
; every consumer declares exactly the state it needs initialized and the
; scene entry code inits precisely that. Blanket zeroing hides uninit-read
; bugs that bite on real hardware (RAM is random at power-on).
;
; After RESET runs: native mode, A8/I16, stack at SYS_STACK_TOP (an
; allocator-emitted symbol — the system reservation is substrate data, not a
; narrated constant), DP=$0000, DBR=$00, forced blank asserted, every
; display-affecting PPU register initialized (ppu_reset.inc), FastROM on,
; interrupts/NMI off. Jumps to MAIN.
;
; Contract: include AFTER the generated engine_state_globals.inc (SYS_STACK_TOP
; lives there) and define MAIN in the including ROM.

.p816
.smart

.segment "CODE"

RESET:
    sei
    clc
    xce                     ; native mode

    rep #$30
    .a16
    .i16
    ldx #SYS_STACK_TOP      ; stack top: allocator-emitted (substrate data)
    txs
    lda #$0000
    tcd                     ; DP = $0000

    sep #$20
    .a8
    lda #$00
    pha
    plb                     ; DBR = $00

    lda #$80
    sta $2100               ; INIDISP: forced blank
    .a8
    .include "ppu_reset.inc"

    stz $4200               ; NMITIMEN: NMI/IRQ/auto-joypad off
    stz $420C               ; HDMAEN: no HDMA channels armed — power-on state
                            ; is NOT guaranteed zero; a randomly-armed channel
                            ; runs garbage tables every scanline and can abort
                            ; same-channel GP-DMA (surfaced as an intermittent
                            ; multi-queue probe stall under random power-on)
    lda #$01
    sta $420D               ; MEMSEL: FastROM

    rep #$30
    .a16
    .i16
    jmp MAIN
