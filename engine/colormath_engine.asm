; =============================================================================
; colormath_engine.asm — Color Math Engine for SuperForge
; =============================================================================
; Manages SNES color math PPU registers via shadow state.
; Provides blend() and tint() API functions.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
;
; IMPORTANT: Branch targets that are reached via conditional branches from
; 8-bit mode need explicit .a8 directives, because ca65's .smart tracking
; follows the fall-through path (which may switch to 16-bit before rts).
;
; PPU registers managed:
;   $212C (TM)      — Main screen designation (shadow at SHADOW_TM)
;   $212D (TS)      — Sub screen designation (shadow at SHADOW_TS)
;   $2130 (CGWSEL)  — Color addition select (shadow at SHADOW_CGWSEL)
;   $2131 (CGADSUB) — Color math designation (shadow at SHADOW_CGADSUB)
;   $2132 (COLDATA) — Fixed color data (shadows at SHADOW_COLDATA_R/G/B)
;
; Cross-ref: engine_state.inc, superforge_spec_v0.3.md
; =============================================================================

; --- Color math state constants (guard against missing engine_state.inc) ---
.ifndef ES_SHADOW_TS
ES_SHADOW_TS         = $44
ES_SHADOW_CGWSEL     = $45
ES_SHADOW_CGADSUB    = $46
ES_SHADOW_COLDATA_R  = $47
ES_SHADOW_COLDATA_G  = $48
ES_SHADOW_COLDATA_B  = $49
ES_BLEND_DIRTY       = $4A
ES_TINT_ACTIVE       = $4B
SHADOW_TS            = $0144
SHADOW_CGWSEL        = $0145
SHADOW_CGADSUB       = $0146
SHADOW_COLDATA_R     = $0147
SHADOW_COLDATA_G     = $0148
SHADOW_COLDATA_B     = $0149
BLEND_DIRTY          = $014A
TINT_ACTIVE          = $014B
.endif

.ifndef SHADOW_TM
SHADOW_TM            = $012F
.endif

; --- API parameter block addresses ---
.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif
.ifndef ENGINE_A0
ENGINE_A0       = $40
.endif

; --- Blend mode constants ---
BLEND_NONE = 0
BLEND_ADD  = 1
BLEND_SUB  = 2
BLEND_HALF = 3


; =============================================================================
; engine_blend — Set blending mode for a layer
; =============================================================================
; Params (API_BLOCK_BASE, 16-bit each):
;   +$00: layer (1=BG1, 2=BG2, 3=BG3, 4=OBJ)
;   +$04: mode  (0=NONE, 1=ADD, 2=SUB, 3=HALF)
;
; Modifies: SHADOW_TM, SHADOW_TS, SHADOW_CGWSEL, SHADOW_CGADSUB, ES_BLEND_DIRTY
; =============================================================================
engine_blend:
    rep #$30
    .a16
    .i16

    ; --- Compute layer_bit from layer parameter ---
    ; layer: 1=BG1($01), 2=BG2($02), 3=BG3($04), 4=OBJ($10)
    lda API_BLOCK_BASE + 0          ; layer
    and #$00FF
    cmp #$0004
    bne @blend_bg
    ; OBJ: layer_bit = $10
    lda #$0010
    bra @blend_got_bit
@blend_bg:
    ; BG layers: layer_bit = 1 << (layer - 1)
    dec                             ; A = layer - 1
    tax
    lda #$0001
    cpx #$0000
    beq @blend_got_bit
@blend_shift:
    asl
    dex
    bne @blend_shift
@blend_got_bit:
    ; A = layer_bit (16-bit, but only low 8 bits matter)
    sta ENGINE_A0                   ; temp: save layer_bit

    ; --- Check blend mode ---
    sep #$20
    .a8

    lda API_BLOCK_BASE + 4          ; mode (low byte)
    bne @blend_enable

    ; === BLEND_NONE: Remove layer from sub screen and color math ===
    lda ENGINE_A0                   ; layer_bit
    eor #$FF                        ; ~layer_bit
    and SHADOW_TS                   ; shadow_ts &= ~layer_bit
    sta SHADOW_TS

    lda ENGINE_A0                   ; layer_bit
    eor #$FF
    and SHADOW_CGADSUB              ; shadow_cgadsub &= ~layer_bit
    sta SHADOW_CGADSUB

    ; Restore layer to main screen
    lda ENGINE_A0                   ; layer_bit
    ora SHADOW_TM                   ; shadow_tm |= layer_bit
    sta SHADOW_TM

    ; Mark dirty
    lda #$01
    sta BLEND_DIRTY

    rep #$20
    .a16
    rts

@blend_enable:
    .a8                             ; branch target from 8-bit bne above
    pha                             ; save mode

    ; Move layer from main to sub screen
    lda ENGINE_A0                   ; layer_bit
    eor #$FF
    and SHADOW_TM                   ; shadow_tm &= ~layer_bit
    sta SHADOW_TM

    lda ENGINE_A0                   ; layer_bit
    ora SHADOW_TS                   ; shadow_ts |= layer_bit
    sta SHADOW_TS

    ; Enable color math for this layer
    ; First, clear mode bits (bit 6 half, bit 7 subtract) to set fresh
    lda SHADOW_CGADSUB
    and #$3F                        ; clear bits 6-7 (half/sub flags)
    ora ENGINE_A0                   ; |= layer_bit
    sta SHADOW_CGADSUB

    ; Use sub screen mode
    lda #$02
    sta SHADOW_CGWSEL

    ; Apply mode-specific bits
    pla                             ; restore mode
    cmp #BLEND_SUB
    bne @blend_check_half
    ; Subtract mode: set bit 7
    lda SHADOW_CGADSUB
    ora #$80
    sta SHADOW_CGADSUB
    bra @blend_done

@blend_check_half:
    .a8                             ; branch target from 8-bit bne above
    cmp #BLEND_HALF
    bne @blend_done
    ; Half mode: set bit 6
    lda SHADOW_CGADSUB
    ora #$40
    sta SHADOW_CGADSUB
    ; ADD mode: no extra bits needed (fall through)

@blend_done:
    .a8                             ; branch target from 8-bit bra/bne above
    ; Mark dirty
    lda #$01
    sta BLEND_DIRTY

    rep #$20
    .a16
    rts


; =============================================================================
; engine_tint — Set or disable fixed color tint
; =============================================================================
; Params (API_BLOCK_BASE, 16-bit each):
;   +$00: r (0-31)
;   +$04: g (0-31)
;   +$08: b (0-31)
;
; If r=0 AND g=0 AND b=0: disable tint.
; Otherwise: enable fixed color tint.
;
; Modifies: SHADOW_CGWSEL, SHADOW_CGADSUB, SHADOW_COLDATA_R/G/B,
;           ES_TINT_ACTIVE, ES_BLEND_DIRTY
; =============================================================================
engine_tint:
    rep #$30
    .a16
    .i16

    ; Check if all channels are zero (disable tint)
    lda API_BLOCK_BASE + 0          ; r
    ora API_BLOCK_BASE + 4          ; g
    ora API_BLOCK_BASE + 8          ; b
    bne @tint_enable

    ; === Disable tint ===
    sep #$20
    .a8

    ; Clear fixed color values
    stz SHADOW_COLDATA_R
    stz SHADOW_COLDATA_G
    stz SHADOW_COLDATA_B
    stz TINT_ACTIVE

    ; Remove backdrop from color math participation
    lda SHADOW_CGADSUB
    and #$DF                        ; clear bit 5 (backdrop)
    sta SHADOW_CGADSUB

    ; Mark dirty
    lda #$01
    sta BLEND_DIRTY

    rep #$20
    .a16
    rts

@tint_enable:
    .a16                            ; branch target from 16-bit bne above
    ; === Enable tint with fixed color ===
    sep #$20
    .a8

    ; Use fixed color mode (not sub screen)
    lda #$00
    sta SHADOW_CGWSEL

    ; Backdrop participates in color math
    lda SHADOW_CGADSUB
    ora #$20                        ; set bit 5 (backdrop)
    sta SHADOW_CGADSUB

    ; Store color channel values
    lda API_BLOCK_BASE + 0          ; r (low byte)
    and #$1F
    sta SHADOW_COLDATA_R

    lda API_BLOCK_BASE + 4          ; g (low byte)
    and #$1F
    sta SHADOW_COLDATA_G

    lda API_BLOCK_BASE + 8          ; b (low byte)
    and #$1F
    sta SHADOW_COLDATA_B

    ; Mark tint active
    lda #$01
    sta TINT_ACTIVE

    ; Mark dirty
    lda #$01
    sta BLEND_DIRTY

    rep #$20
    .a16
    rts


; =============================================================================
; engine_color_math_on — cross-demo color-math primitive (Phase 16-3-3-1)
; =============================================================================
; Writes CGWSEL = $02 (sub-screen mode) and CGADSUB = layers | mode_bits.
; Leaves SHADOW_TM/TS untouched (unlike engine_blend, which reroutes layers
; between main and sub screens). Caller is responsible for TM/TS.
;
; BLEND_DIRTY is intentionally NOT written — the flag has zero readers in
; the engine; NMI commits CGWSEL/CGADSUB every frame unconditionally.
; Writing it would burn ~6 cycles/call for no effect.
;
; Params (API_BLOCK_BASE, 16-bit each, only low byte used):
;   +$00: mode   (1=ADD, 2=SUB, 3=HALF_ADD, 4=HALF_SUB)
;   +$04: layers (bit0=BG1, bit1=BG2, bit2=BG3, bit3=BG4, bit4=OBJ, bit5=BD)
;
; CGADSUB encoding: (layers & $3F) | mode_bits where
;   mode=1 ADD      → $00
;   mode=2 SUB      → $80
;   mode=3 HALF_ADD → $40
;   mode=4 HALF_SUB → $C0
;
; Modifies: SHADOW_CGWSEL, SHADOW_CGADSUB
; =============================================================================
engine_color_math_on:
    rep #$30
    .a16
    .i16

    sep #$20
    .a8

    ; CGWSEL = $02 (sub-screen mode)
    lda #$02
    sta SHADOW_CGWSEL

    ; layers & $3F (clamp to valid 6-bit mask)
    lda API_BLOCK_BASE + 4
    and #$3F
    pha                                 ; save layers & $3F

    ; Decode mode → mode_bits
    lda API_BLOCK_BASE + 0
    cmp #$02
    beq @cmo_sub
    cmp #$03
    beq @cmo_half_add
    cmp #$04
    beq @cmo_half_sub
    ; mode=1 ADD (or anything else): mode_bits = $00
    lda #$00
    bra @cmo_apply
@cmo_sub:
    .a8
    lda #$80
    bra @cmo_apply
@cmo_half_add:
    .a8
    lda #$40
    bra @cmo_apply
@cmo_half_sub:
    .a8
    lda #$C0
@cmo_apply:
    .a8
    sta ENGINE_A0                       ; temp: mode_bits
    pla                                 ; restore layers & $3F
    ora ENGINE_A0                       ; CGADSUB = layers | mode_bits
    sta SHADOW_CGADSUB

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_color_math_off — disable color math (Phase 16-3-3-1)
; =============================================================================
; Zeros SHADOW_CGWSEL and SHADOW_CGADSUB. Does not touch TM/TS.
; BLEND_DIRTY not written (see engine_color_math_on rationale).
;
; Params: none.
; Modifies: SHADOW_CGWSEL, SHADOW_CGADSUB
; =============================================================================
engine_color_math_off:
    rep #$30
    .a16
    .i16

    sep #$20
    .a8
    stz SHADOW_CGWSEL
    stz SHADOW_CGADSUB

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_color_math_tint — fixed-color source for color math (Phase 16-3-3-3)
; =============================================================================
; Writes SHADOW_COLDATA_R/G/B. Does NOT touch CGWSEL/CGADSUB — those are
; caller's responsibility via color_math_on. This keeps the enable path
; (mode + layers) and the color path (r, g, b) orthogonal, so the common
; "change fog color without re-enabling" case is one call, not a combined
; 5-param primitive.
;
; BLEND_DIRTY not written — flag has zero readers; NMI commits COLDATA
; every frame unconditionally (see engine_color_math_on rationale).
;
; Each channel is masked to the SNES 5-bit range ($00-$1F).
;
; Params (API_BLOCK_BASE, 16-bit each, low 5 bits used):
;   +$00: r (0-31)
;   +$04: g (0-31)
;   +$08: b (0-31)
;
; Modifies: SHADOW_COLDATA_R, SHADOW_COLDATA_G, SHADOW_COLDATA_B
; =============================================================================
engine_color_math_tint:
    rep #$30
    .a16
    .i16

    sep #$20
    .a8

    lda API_BLOCK_BASE + 0              ; r (low byte)
    and #$1F
    sta SHADOW_COLDATA_R

    lda API_BLOCK_BASE + 4              ; g (low byte)
    and #$1F
    sta SHADOW_COLDATA_G

    lda API_BLOCK_BASE + 8              ; b (low byte)
    and #$1F
    sta SHADOW_COLDATA_B

    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts
