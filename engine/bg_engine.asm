; =============================================================================
; bg_engine.asm — BG Engine (Mode 1 Setup, Map Rendering, Scrolling)
; =============================================================================
; Manages BG layer configuration, shadow tilemaps, and scroll registers.
;
; Provides four engine functions:
;   engine_gfxmode  — ID 7: gfxmode(mode)       — configure PPU for Mode 1
;   engine_scroll   — ID 8: scroll(layer, x, y)  — set shadow scroll registers
;   engine_mget     — ID 9: mget(layer, mx, my)  — read tilemap entry
;   engine_mset     — ID 10: mset(layer, mx, my, tile) — write tilemap entry
;
; Shadow tilemaps (WRAM bank $7E, accessed via DB=$7E):
;   SHADOW_BG1_TILEMAP ($A200): 2048 bytes (32x32 x 2 bytes)
;   SHADOW_BG2_TILEMAP ($AA00): 2048 bytes
;   SHADOW_BG3_TILEMAP ($B200): 2048 bytes
;
; PPU register values for Mode 1:
;   BGMODE  ($2105) = $09    Mode 1, BG3 priority=1, 8x8 tiles
;   BG1SC   ($2107) = $58    BG1 tilemap at word $5800 (byte $B000), 32x32
;   BG2SC   ($2108) = $5C    BG2 tilemap at word $5C00 (byte $B800), 32x32
;   BG3SC   ($2109) = $60    BG3 tilemap at word $6000 (byte $C000), 32x32
;   BG12NBA ($210B) = $42    BG1 tiles at word $2000, BG2 at word $4000
;   BG34NBA ($210C) = $0A    BG3 tiles at $A000
;   TM      ($212C) = $17    Enable Sprites + BG1 + BG2 + BG3
;
; API parameter block (DP-relative at $60):
;   engine_scroll: +0=layer(4B), +4=x(4B), +8=y(4B)
;   engine_mget:   +0=layer(4B), +4=mx(4B), +8=my(4B)
;   engine_mset:   +0=layer(4B), +4=mx(4B), +8=my(4B), +12=tile(4B)
;   engine_gfxmode: +0=mode(4B)
;
; Return value: ENGINE_A0 ($40, 4 bytes)
;
; Prerequisites: engine_state.inc included, .p816/.smart set by parent.
; Do NOT add .p816/.smart — this file is included into a parent.
; Cross-ref: engine_state.inc, handlers_engine.asm
; =============================================================================

; API parameter addresses (DP-relative, matches handlers_engine.asm)
; ENGINE_A0 = $40, API_BLOCK_BASE = $60 (defined in handlers_engine.asm)
; For test ROMs that include this file directly, define if not already defined:
.ifndef ENGINE_A0
ENGINE_A0       = $40
.endif
.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif

; BG engine scratch (WRAM, after sprite engine scratch $0560-$056F)
BG_SCRATCH      = $0576         ; 2 bytes: temporary for BG calculations
BG_SCRATCH2     = $0578         ; 2 bytes: temporary for tilemap base address


; =============================================================================
; engine_gfxmode — Set up PPU for Mode 1
; =============================================================================
; Guarded: bg_mode_engine.asm (Phase 17-0) defines a replacement dispatcher
; and sets BG_MODE_ENGINE_PROVIDES_GFXMODE. When both files are included in
; the same ROM, this Mode-1-only body is skipped so the new dispatcher wins.
; ROMs that include only bg_engine.asm (Phase 3/12/13/font) keep the
; original body unchanged.
.ifndef BG_MODE_ENGINE_PROVIDES_GFXMODE

; Parameters: API_BLOCK_BASE+0 = mode (only mode 1 supported currently)
;
; Writes PPU registers directly (must be called during forced blank).
; Writes shadow copies of BGMODE, TM, INIDISP.
; Clears all 3 shadow tilemaps to zero.
; Marks BG_TILEMAP_DIRTY = $07 (all layers) and BG_SHADOW_REGS_DIRTY = 1.
; Sets GFXMODE_STATE = $01.
;
; Clobbers: A, X. Expects 16-bit AXY on entry.
; =============================================================================
engine_gfxmode:
    ; Write PPU registers directly (we are in forced blank)
    sep #$20
    .a8

    ; BGMODE ($2105): Mode 1, BG3 priority=1, 8x8 tiles
    lda #PPU_BGMODE_MODE1
    sta $2105
    sta SHADOW_BGMODE           ; shadow copy

    ; BG1SC ($2107): tilemap at word $5800 (byte $B000), 32x32
    lda #PPU_BG1SC_VALUE
    sta $2107

    ; BG2SC ($2108): tilemap at word $5C00 (byte $B800), 32x32
    lda #PPU_BG2SC_VALUE
    sta $2108
    ; Phase 17 Sprint D-5: BG2_TILEMAP_VRAM_HI is initialized in init_ppu
    ; (the universal entry); engine_gfxmode does not need to re-publish it.

    ; BG3SC ($2109): tilemap at word $6000 (byte $C000), 32x32
    lda #PPU_BG3SC_VALUE
    sta $2109

    ; BG12NBA ($210B): BG1 chr word $2000, BG2 chr word $4000
    ; Each nibble × $1000 = word address.  Only bits 0-2 / 4-6 matter.
    lda #PPU_BG12NBA_VALUE
    sta $210B

    ; BG34NBA ($210C): BG3 tiles at word $A000
    lda #PPU_BG34NBA_VALUE
    sta $210C

    ; TM ($212C) = $17: Enable Sprites + BG1 + BG2 + BG3
    lda #$17
    sta $212C
    sta SHADOW_TM

    ; Enable display at full brightness: INIDISP = $0F
    lda #$0F
    sta $2100
    sta SHADOW_INIDISP

    ; Store gfxmode state = 1 (Mode 1 active)
    lda #$01
    sta GFXMODE_STATE

    ; Mark shadow regs dirty
    lda #$01
    sta BG_SHADOW_REGS_DIRTY

    rep #$20
    .a16

    ; Clear shadow tilemaps (3 x 2048 bytes = 6144 bytes)
    ; Must set DB=$7E to access WRAM $A200+
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; Clear BG1 tilemap ($A200, 2048 bytes = 1024 words)
    ldx #$0000
@clear_bg1:
    stz $A200,x
    inx
    inx
    cpx #$0800                  ; 2048 bytes
    bne @clear_bg1

    ; Clear BG2 tilemap ($AA00, 2048 bytes)
    ldx #$0000
@clear_bg2:
    stz $AA00,x
    inx
    inx
    cpx #$0800
    bne @clear_bg2

    ; Clear BG3 tilemap ($B200, 2048 bytes)
    ldx #$0000
@clear_bg3:
    stz $B200,x
    inx
    inx
    cpx #$0800
    bne @clear_bg3

    plb                         ; restore DB

    ; Mark all layers dirty for initial DMA
    sep #$20
    .a8
    lda #$07
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16

    ; Clear scroll shadow registers to 0
    stz SHADOW_BG1HOFS
    stz SHADOW_BG1VOFS
    stz SHADOW_BG2HOFS
    stz SHADOW_BG2VOFS
    stz SHADOW_BG3HOFS
    stz SHADOW_BG3VOFS

    ; Return 0
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts

.endif  ; .ifndef BG_MODE_ENGINE_PROVIDES_GFXMODE


; =============================================================================
; engine_scroll — Set shadow scroll registers for a BG layer
; =============================================================================
; Parameters (API block):
;   API_BLOCK_BASE + 0  = layer (1-3), 32-bit, low 16 used
;   API_BLOCK_BASE + 4  = x (pixel scroll), 32-bit, low 16 used
;   API_BLOCK_BASE + 8  = y (pixel scroll), 32-bit, low 16 used
;
; Writes to SHADOW_BGnHOFS and SHADOW_BGnVOFS based on layer number.
;
; Clobbers: A, X. Expects 16-bit AXY on entry.
; =============================================================================
engine_scroll:
    rep #$20
    .a16

    ; Read layer number (1-3)
    lda API_BLOCK_BASE + 0
    dec                         ; convert 1-based to 0-based (0-2)
    asl
    asl                         ; offset = (layer-1) * 4 (each layer has HOFS+VOFS = 4 bytes)
    tax                         ; X = offset into shadow scroll array

    ; Write HOFS: SHADOW_BG1HOFS is at absolute $0120
    ; shadow_scroll_base + X + 0 = HOFS, +2 = VOFS
    lda API_BLOCK_BASE + 4      ; x scroll value
    sta SHADOW_BG1HOFS,x

    lda API_BLOCK_BASE + 8      ; y scroll value
    sta SHADOW_BG1VOFS,x

    ; Return 0
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_mget — Read tilemap entry from shadow tilemap
; =============================================================================
; Parameters (API block):
;   API_BLOCK_BASE + 0  = layer (1-3)
;   API_BLOCK_BASE + 4  = mx (map x, 0-31)
;   API_BLOCK_BASE + 8  = my (map y, 0-31)
;
; Returns: 16-bit tilemap word in ENGINE_A0 (low 16 bits)
;
; Formula: offset = (my * 64) + (mx * 2), then lda tilemap_base,x
;
; Must set DB=$7E to access shadow tilemaps at $A200+.
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_mget:
    rep #$30
    .a16
    .i16

    ; Calculate byte offset within tilemap: my * 64 + mx * 2
    lda API_BLOCK_BASE + 8      ; my
    asl
    asl
    asl
    asl
    asl
    asl                         ; A = my * 64
    sta BG_SCRATCH              ; save row offset

    lda API_BLOCK_BASE + 4      ; mx
    asl                         ; A = mx * 2
    clc
    adc BG_SCRATCH              ; A = my*64 + mx*2
    tax                         ; X = byte offset within tilemap (0-2046)

    ; Set DB=$7E to access WRAM shadow tilemaps
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16

    ; Dispatch on layer number to use the correct base address
    lda API_BLOCK_BASE + 0      ; layer (1-3)
    cmp #$0002
    beq @mget_bg2
    cmp #$0003
    beq @mget_bg3
    ; Default: layer 1
    lda a:SHADOW_BG1_TILEMAP,x  ; read from BG1 shadow tilemap
    bra @mget_done
@mget_bg2:
    lda a:SHADOW_BG2_TILEMAP,x  ; read from BG2 shadow tilemap
    bra @mget_done
@mget_bg3:
    lda a:SHADOW_BG3_TILEMAP,x  ; read from BG3 shadow tilemap
@mget_done:

    plb                         ; restore DB

    ; Store result in ENGINE_A0
    sta ENGINE_A0
    stz ENGINE_A0 + 2           ; zero-extend to 32-bit
    rts


; =============================================================================
; engine_mset — Write tilemap entry to shadow tilemap
; =============================================================================
; Parameters (API block):
;   API_BLOCK_BASE + 0  = layer (1-3)
;   API_BLOCK_BASE + 4  = mx (map x, 0-31)
;   API_BLOCK_BASE + 8  = my (map y, 0-31)
;   API_BLOCK_BASE + 12 = tile_word (16-bit tilemap entry)
;
; Marks the layer dirty in BG_TILEMAP_DIRTY bitmask.
;
; Formula: offset = (my * 64) + (mx * 2), then sta tilemap_base,x
;
; Clobbers: A, X, Y. Expects 16-bit AXY on entry.
; =============================================================================
engine_mset:
    rep #$30
    .a16
    .i16

    ; Calculate byte offset within tilemap: my * 64 + mx * 2
    lda API_BLOCK_BASE + 8      ; my
    asl
    asl
    asl
    asl
    asl
    asl                         ; A = my * 64
    sta BG_SCRATCH              ; save row offset

    lda API_BLOCK_BASE + 4      ; mx
    asl                         ; A = mx * 2
    clc
    adc BG_SCRATCH              ; A = my*64 + mx*2
    tax                         ; X = byte offset within tilemap (0-2046)

    ; Load tile value to write
    lda API_BLOCK_BASE + 12     ; tile_word (low 16 bits)

    ; Set DB=$7E to access WRAM shadow tilemaps
    phb
    pha                         ; save tile value on stack
    sep #$20
    .a8
    lda #$7E
    pha
    plb                         ; DB = $7E
    rep #$20
    .a16
    pla                         ; recover tile value

    ; Dispatch on layer number to use the correct base address
    ; Save A (tile value) in Y temporarily
    tay                         ; Y = tile value
    lda API_BLOCK_BASE + 0      ; layer (1-3)
    cmp #$0002
    beq @mset_bg2
    cmp #$0003
    beq @mset_bg3
    ; Default: layer 1
    tya                         ; A = tile value
    sta a:SHADOW_BG1_TILEMAP,x
    bra @mset_done
@mset_bg2:
    tya
    sta a:SHADOW_BG2_TILEMAP,x
    bra @mset_done
@mset_bg3:
    tya
    sta a:SHADOW_BG3_TILEMAP,x
@mset_done:

    plb                         ; restore DB

    ; Mark layer dirty in BG_TILEMAP_DIRTY
    ; dirty bit = 1 << (layer - 1)
    lda API_BLOCK_BASE + 0      ; layer (1-3)
    dec                         ; 0-2
    tax
    sep #$20
    .a8
    lda f:_bg_dirty_bits,x      ; look up dirty bit mask
    ora BG_TILEMAP_DIRTY        ; combine with existing dirty flags
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16

    ; Return 0
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; _bg_get_tilemap_base — Get shadow tilemap base address for a layer
; =============================================================================
; Input:  A = layer number (1-3)
; Output: A = WRAM base address ($A200, $AA00, or $B200)
; Clobbers: X
; =============================================================================
_bg_get_tilemap_base:
    dec                         ; convert 1-based to 0-based (0-2)
    asl                         ; word index
    tax
    lda f:_bg_tilemap_bases,x
    rts

; Lookup table: tilemap base addresses per layer
_bg_tilemap_bases:
    .word SHADOW_BG1_TILEMAP    ; layer 1 -> $A200
    .word SHADOW_BG2_TILEMAP    ; layer 2 -> $AA00
    .word SHADOW_BG3_TILEMAP    ; layer 3 -> $B200

; Lookup table: dirty bit masks per layer (0-indexed)
_bg_dirty_bits:
    .byte $01                   ; layer 1 -> bit 0
    .byte $02                   ; layer 2 -> bit 1
    .byte $04                   ; layer 3 -> bit 2
