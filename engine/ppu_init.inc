; =============================================================================
; ppu_init.inc — PPU Register Initialization for SuperForge Engine
; =============================================================================
; Call init_ppu as a subroutine after WRAM clear and before enabling NMI.
; Sets up Mode 1 with OBJ layer, default scroll, and screen-on.
;
; Prerequisites: CPU in native mode, 8-bit A, interrupts disabled,
;                engine_state.inc already included (provides SHADOW_* addresses)
; Cross-ref: engine_state.inc (shadow registers), nmi_handler.asm (Phase 4)
; =============================================================================

; Prerequisite: engine_state.inc must be included before this file.
; Prerequisite: .p816 and .smart must be set.

; --- PPU Initialization Subroutine ---
; Call with JSR init_ppu. Expects engine_state.inc to be already included.
; Returns with 8-bit A.
init_ppu:
    sep #$20
    .a8

    ; BGMODE ($2105): Mode 1, BG3 priority bit set
    lda #$09
    sta $2105

    ; OAMADDL/H ($2102/$2103): Set OAM address to 0
    ; Ensures DMA to $2104 starts writing at OAM byte 0.
    ; Without this, the latch retains an undefined power-on value on
    ; real hardware, causing OAM DMA to write at the wrong offset.
    stz $2102
    stz $2103

    ; OBJ size and name base ($2101)
    ; Bits 7-5: OBJ size (000 = 8x8 small, 16x16 large)
    ; Bits 4-3: Name select (0)
    ; Bits 2-0: Name base address (0 = VRAM word $0000)
    lda #$00
    sta $2101

    ; Initialize all BG scroll registers to 0
    stz $210D               ; BG1HOFS low
    stz $210D               ; BG1HOFS high
    stz $210E               ; BG1VOFS low
    stz $210E               ; BG1VOFS high
    stz $210F               ; BG2HOFS low
    stz $210F               ; BG2HOFS high
    stz $2110               ; BG2VOFS low
    stz $2110               ; BG2VOFS high
    stz $2111               ; BG3HOFS low
    stz $2111               ; BG3HOFS high
    stz $2112               ; BG3VOFS low
    stz $2112               ; BG3VOFS high

    ; Main screen designation ($212C): enable OBJ layer
    lda #$10                ; Bit 4 = OBJ
    sta $212C

    ; Sub screen designation ($212D): none
    stz $212D

    ; Color math ($2130-$2131): add fixed color to backdrop
    ; CGWSEL=$02: use fixed color as sub screen source
    ; CGADSUB=$20: add fixed color to backdrop
    ; When COLDATA is 0 (default), this is a no-op.
    ; gradient() uses HDMA to write per-scanline COLDATA values,
    ; creating a visible sky gradient on the backdrop color.
    lda #$02
    sta $2130               ; CGWSEL: fixed color as sub screen
    lda #$20
    sta $2131               ; CGADSUB: add to backdrop

    ; Fixed color ($2132): black background
    lda #$E0                ; Set R+G+B to 0 (bits 7-5 = color plane select)
    sta $2132

    ; Initialize shadow registers in engine state (absolute addressing)
    lda #$09
    sta SHADOW_BGMODE
    stz SHADOW_MOSAIC
    lda #$10
    sta SHADOW_TM

    ; Phase 17 Sprint D-5 (Bug A): default BG2 tilemap VRAM destination
    ; for the NMI BG2 DMA. Static-mode ROMs use $5C00 (matches PPU_BG2SC_VALUE
    ; = $5C). Streaming-mode boot overrides BG2_TILEMAP_VRAM_HI = $48 to
    ; relocate BG2 tilemap out of BG1 streaming page 1's region.
    lda #PPU_BG2_VRAM_HI_STATIC
    sta BG2_TILEMAP_VRAM_HI

    ; Screen on: full brightness, disable forced blank
    lda #$0F
    sta $2100
    sta SHADOW_INIDISP

    rts
