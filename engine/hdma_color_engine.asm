; =============================================================================
; hdma_color_engine.asm — Phase 9 Advanced HDMA Color Effects
; =============================================================================
; Extends the HDMA engine with RGB gradient support using 3 independent
; COLDATA channels (CH3=Red $20, CH4=Green $40, CH5=Blue $80).
;
; Provides:
;   hdma_build_gradient_rgb   — 2-stop RGB gradient (6 params)
;   hdma_build_gradient_stops — N-stop RGB gradient from WRAM array
;   hdma_apply_easing         — Apply easing LUT to intensity value
;   hdma_gradient_rgb_rebuild — In-place table rebuild (no reallocation)
;   hdma_update_gradient_rgb  — Per-frame animation update
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set,
;                hdma_engine.asm included (provides hdma_alloc etc.)
;
; Cross-ref: engine_state.inc, hdma_engine.asm, gradient_ease_lut.inc,
;            phase_9_advanced_hdma_color_effects.md
; =============================================================================

; COLDATA channel-select prefixes
COLDATA_RED   = $20
COLDATA_GREEN = $40
COLDATA_BLUE  = $80

; Maximum gradient stops
GRAD_MAX_STOPS = 16

; Gradient stop structure size (6 bytes each)
GRAD_STOP_SIZE = 6

; Additional DP pointers for multi-table writes
; Reuse $B4-$B7 from engine cache area (not used by other HDMA effects simultaneously)
HDMA_TBL_PTR_G = $B4    ; 2 bytes: green table pointer
HDMA_TBL_PTR_B = $B6    ; 2 bytes: blue table pointer


; =============================================================================
; hdma_build_gradient_rgb — Build 3-channel RGB gradient HDMA tables
; =============================================================================
; Builds 3 independent COLDATA HDMA tables (one per R/G/B channel).
; Each table has 225 entries + terminator, targeting $2132 with different
; channel-select prefixes.
;
; Input (via WRAM scratch):
;   HDMA_GRAD_RGB_TOP_R/G/B: top color intensities (0-31 each)
;   HDMA_GRAD_RGB_BOT_R/G/B: bottom color intensities (0-31 each)
;   HDMA_GRAD_RGB_EASING:    easing type (0-3)
;
; Output:
;   Allocates 3 HDMA channels (CH3-CH5), builds tables at:
;     $7E:C000-$C1C3 (red), $7E:C1C4-$C387 (green), $7E:C388-$C54B (blue)
;   Returns: A = first allocated channel (3) or $FFFF on failure.
;
; Clobbers: A, X, Y
; =============================================================================
hdma_build_gradient_rgb:
    .a16
    .i16

    ; --- Check Mode 7 mutual exclusion ---
    ; Recovery merge: read Brad's M7_PV_ACTIVE (live engine). The legacy
    ; M7_ACTIVE at $89 is dead state — only used by mode7_engine_legacy.asm
    ; (Phase 8/8T/14/15 frozen engine), which runs in its own test ROMs
    ; that don't use Phase 9 RGB gradient anyway.
    sep #$20
    .a8
    lda M7_PV_ACTIVE
    beq @rgb_m7_ok
    rep #$20
    .a16
    lda #$FFFF
    rts
@rgb_m7_ok:
    rep #$20
    .a16

    ; --- Release any existing gradient_rgb channels ---
    jsr _hdma_rgb_release

    ; --- Allocate 3 channels ---
    jsr hdma_alloc
    cmp #$FFFF
    bne @rgb_alloc1_ok
    rts
@rgb_alloc1_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_R
    pha                             ; save first channel for return

    jsr hdma_alloc
    cmp #$FFFF
    bne @rgb_alloc2_ok
    ; Failed — ideally free first, but return error
    pla
    lda #$FFFF
    rts
@rgb_alloc2_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_G

    jsr hdma_alloc
    cmp #$FFFF
    bne @rgb_alloc3_ok
    ; Failed
    pla
    lda #$FFFF
    rts
@rgb_alloc3_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_B

    ; --- Set up table pointers ---
    ; Red table at fixed offset HDMA_RGB_TBL_R ($C000)
    lda #HDMA_RGB_TBL_R
    sta HDMA_TBL_PTR
    ; Green table at HDMA_RGB_TBL_G ($C0E2)
    lda #HDMA_RGB_TBL_G
    sta HDMA_TBL_PTR_G
    ; Blue table at HDMA_RGB_TBL_B ($C1C4)
    lda #HDMA_RGB_TBL_B
    sta HDMA_TBL_PTR_B

    ; --- Configure channels ---
    ; Red channel: DMAP=$00, BBAD=$32 (COLDATA)
    lda HDMA_GRAD_RGB_CH_R
    jsr _hdma_configure_channel_gradient
    ; Phase 17-13: program hardware HDMA registers ($43n0+) directly.
    ; ch_num * 16 → $43n0 base for each color channel. See
    ; engine/hdma_engine.asm _hdma_configure_channel_gradient (which red
    ; channel uses) for the full architectural rationale.

    ; Green channel
    lda HDMA_GRAD_RGB_CH_G
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base for green channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                ; DMAPn
    lda #COLDATA_REG
    sta f:$004301, x                ; BBADn
    lda HDMA_TBL_PTR_G
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR_G+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn
    rep #$20
    .a16
    ; Blue channel
    lda HDMA_GRAD_RGB_CH_B
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base for blue channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                ; DMAPn
    lda #COLDATA_REG
    sta f:$004301, x                ; BBADn
    lda HDMA_TBL_PTR_B
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR_B+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn
    rep #$20
    .a16

    ; --- Compute per-channel step values ---
    ; step_r = ((bot_r - top_r) << 8) / 225
    lda HDMA_GRAD_RGB_BOT_R
    sec
    sbc HDMA_GRAD_RGB_TOP_R
    xba                             ; << 8
    sta HDMA_GRAD_RGB_STEP_R
    lda HDMA_GRAD_RGB_STEP_R
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_R

    lda HDMA_GRAD_RGB_BOT_G
    sec
    sbc HDMA_GRAD_RGB_TOP_G
    xba
    sta HDMA_GRAD_RGB_STEP_G
    lda HDMA_GRAD_RGB_STEP_G
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_G

    lda HDMA_GRAD_RGB_BOT_B
    sec
    sbc HDMA_GRAD_RGB_TOP_B
    xba
    sta HDMA_GRAD_RGB_STEP_B
    lda HDMA_GRAD_RGB_STEP_B
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_B

    ; --- Initialize accumulators ---
    lda HDMA_GRAD_RGB_TOP_R
    xba
    sta HDMA_GRAD_RGB_ACCUM_R
    lda HDMA_GRAD_RGB_TOP_G
    xba
    sta HDMA_GRAD_RGB_ACCUM_G
    lda HDMA_GRAD_RGB_TOP_B
    xba
    sta HDMA_GRAD_RGB_ACCUM_B

    ; --- Build all 3 tables ---
    jsr _hdma_rgb_fill_tables

    ; --- Enable all 3 channels ---
    lda HDMA_GRAD_RGB_CH_R
    jsr _hdma_enable_channel
    lda HDMA_GRAD_RGB_CH_G
    jsr _hdma_enable_channel
    lda HDMA_GRAD_RGB_CH_B
    jsr _hdma_enable_channel

    ; Return first channel
    pla
    rts


; =============================================================================
; hdma_build_gradient_stops — Build N-stop RGB gradient from WRAM array
; =============================================================================
; Reads stop array from HDMA_GRAD_STOP_ADDR. Each stop is 6 bytes:
;   +0: scanline (16-bit, 0-224)
;   +2: red (8-bit, 0-31)
;   +3: green (8-bit, 0-31)
;   +4: blue (8-bit, 0-31)
;   +5: padding
;
; Input:
;   HDMA_GRAD_STOP_ADDR: pointer to stop array in WRAM
;   HDMA_GRAD_STOP_COUNT: number of stops (2-16)
;   HDMA_GRAD_RGB_EASING: easing type (0-3)
;
; Output: A = first channel or $FFFF on failure
; =============================================================================
hdma_build_gradient_stops:
    .a16
    .i16

    ; --- Check Mode 7 mutual exclusion ---
    ; Recovery merge: read Brad's M7_PV_ACTIVE (see gradient_rgb above).
    sep #$20
    .a8
    lda M7_PV_ACTIVE
    beq @stops_m7_ok
    rep #$20
    .a16
    lda #$FFFF
    rts
@stops_m7_ok:
    .a8
    ; Validate stop count (2-16)
    lda HDMA_GRAD_STOP_COUNT
    cmp #2
    bcc @stops_invalid
    cmp #GRAD_MAX_STOPS+1
    bcc @stops_count_ok
@stops_invalid:
    rep #$20
    .a16
    lda #$FFFF
    rts
@stops_count_ok:
    rep #$20
    .a16

    ; --- Release existing + allocate 3 channels ---
    jsr _hdma_rgb_release

    jsr hdma_alloc
    cmp #$FFFF
    bne @stops_a1_ok
    rts
@stops_a1_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_R
    pha

    jsr hdma_alloc
    cmp #$FFFF
    bne @stops_a2_ok
    pla
    lda #$FFFF
    rts
@stops_a2_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_G

    jsr hdma_alloc
    cmp #$FFFF
    bne @stops_a3_ok
    pla
    lda #$FFFF
    rts
@stops_a3_ok:
    .a16
    sta HDMA_GRAD_RGB_CH_B

    ; --- Set up table pointers ---
    lda #HDMA_RGB_TBL_R
    sta HDMA_TBL_PTR
    lda #HDMA_RGB_TBL_G
    sta HDMA_TBL_PTR_G
    lda #HDMA_RGB_TBL_B
    sta HDMA_TBL_PTR_B

    ; Phase 17-13: same direct-to-hardware retrofit as hdma_build_gradient_rgb.
    ; --- Configure channels (same as rgb) ---
    lda HDMA_GRAD_RGB_CH_R
    jsr _hdma_configure_channel_gradient
    lda HDMA_GRAD_RGB_CH_G
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base for green channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                ; DMAPn
    lda #COLDATA_REG
    sta f:$004301, x                ; BBADn
    lda HDMA_TBL_PTR_G
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR_G+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_CH_B
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base for blue channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                ; DMAPn
    lda #COLDATA_REG
    sta f:$004301, x                ; BBADn
    lda HDMA_TBL_PTR_B
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR_B+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn
    rep #$20
    .a16

    ; --- Build tables from stop array ---
    jsr _hdma_stops_fill_tables

    ; --- Enable all 3 channels ---
    lda HDMA_GRAD_RGB_CH_R
    jsr _hdma_enable_channel
    lda HDMA_GRAD_RGB_CH_G
    jsr _hdma_enable_channel
    lda HDMA_GRAD_RGB_CH_B
    jsr _hdma_enable_channel

    ; Return first channel
    pla
    rts


; =============================================================================
; hdma_gradient_rgb_rebuild — Rebuild tables in-place (no reallocation)
; =============================================================================
; Called when animation dirty flag is set or gradient_update() is called.
; Reads current parameters and rebuilds all 3 tables.
; =============================================================================
hdma_gradient_rgb_rebuild:
    rep #$30
    .a16
    .i16

    ; Check if RGB gradient is active (channel allocated)
    lda HDMA_GRAD_RGB_CH_R
    beq @rebuild_none

    ; Set up table pointers
    lda #HDMA_RGB_TBL_R
    sta HDMA_TBL_PTR
    lda #HDMA_RGB_TBL_G
    sta HDMA_TBL_PTR_G
    lda #HDMA_RGB_TBL_B
    sta HDMA_TBL_PTR_B

    ; Check if multi-stop mode
    sep #$20
    .a8
    lda HDMA_GRAD_RGB_FLAGS
    and #$02                        ; bit 1 = multi-stop mode
    rep #$20
    .a16
    bne @rebuild_stops

    ; --- 2-stop mode: recompute steps and fill ---
    lda HDMA_GRAD_RGB_BOT_R
    sec
    sbc HDMA_GRAD_RGB_TOP_R
    xba
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_R

    lda HDMA_GRAD_RGB_BOT_G
    sec
    sbc HDMA_GRAD_RGB_TOP_G
    xba
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_G

    lda HDMA_GRAD_RGB_BOT_B
    sec
    sbc HDMA_GRAD_RGB_TOP_B
    xba
    jsr _hdma_signed_div_225
    sta HDMA_GRAD_RGB_STEP_B

    lda HDMA_GRAD_RGB_TOP_R
    xba
    sta HDMA_GRAD_RGB_ACCUM_R
    lda HDMA_GRAD_RGB_TOP_G
    xba
    sta HDMA_GRAD_RGB_ACCUM_G
    lda HDMA_GRAD_RGB_TOP_B
    xba
    sta HDMA_GRAD_RGB_ACCUM_B

    jsr _hdma_rgb_fill_tables
    rts

@rebuild_stops:
    jsr _hdma_stops_fill_tables
    rts

@rebuild_none:
    rts


; =============================================================================
; hdma_update_gradient_rgb — Per-frame gradient animation update
; =============================================================================
; Called from the native frame loop (after hdma_update_scanline_scroll).
; If animation is active (FLAGS bit 0), advances phase and triggers
; rebuild when the quantized phase changes.
; =============================================================================
hdma_update_gradient_rgb:
    rep #$30
    .a16
    .i16

    ; Check if gradient RGB is active
    lda HDMA_GRAD_RGB_CH_R
    beq @no_grad_update

    ; Check if animation is enabled (FLAGS bit 0)
    sep #$20
    .a8
    lda HDMA_GRAD_RGB_FLAGS
    and #$01
    beq @no_grad_update_a8

    ; Save previous phase high byte for dirty detection
    lda HDMA_GRAD_PHASE+1
    pha                             ; save old quantized phase

    ; Advance phase
    rep #$20
    .a16
    lda HDMA_GRAD_PHASE
    clc
    adc HDMA_GRAD_SPEED
    sta HDMA_GRAD_PHASE

    ; Compare quantized (high byte) — if changed, set dirty
    sep #$20
    .a8
    lda HDMA_GRAD_PHASE+1
    sta HDMA_GRAD_RGB_STEP_R        ; temp: reuse scratch for comparison
    pla                              ; old high byte
    cmp HDMA_GRAD_RGB_STEP_R        ; compare with new
    beq @no_grad_update_a8          ; same quantized value, skip rebuild

    ; Set dirty flag and trigger rebuild
    rep #$20
    .a16
    jsr hdma_gradient_rgb_rebuild
    rts

@no_grad_update_a8:
    .a8
    rep #$20
    .a16
@no_grad_update:
    rts


; =============================================================================
; hdma_apply_easing — Apply easing LUT to intensity value
; =============================================================================
; Input:  A = linear intensity (0-31), 8-bit mode
;         HDMA_GRAD_RGB_EASING = easing type (0-3)
; Output: A = eased intensity (0-31), 8-bit mode
; Clobbers: X (preserved by caller if needed)
; =============================================================================
hdma_apply_easing:
    .a8
    .i16
    ; Quick path: easing type 0 (linear) = identity
    phx
    pha                             ; save intensity
    lda HDMA_GRAD_RGB_EASING
    beq @ease_linear

    ; Compute LUT offset: easing_type * 32 + intensity
    and #$03                        ; mask to 0-3
    ; Multiply by 32: shift left 5 (8-bit)
    asl                             ; *2
    asl                             ; *4
    asl                             ; *8
    asl                             ; *16
    asl                             ; *32
    sta $A0                         ; temp: base offset
    pla                             ; A = linear intensity (0-31)
    and #$1F                        ; clamp to 5 bits
    clc
    adc $A0                         ; A = (easing * 32) + intensity
    rep #$20
    .a16
    and #$00FF                      ; zero-extend to 16-bit index
    tax
    sep #$20
    .a8
    lda f:gradient_ease_lut,x       ; look up eased value
    plx
    rts

@ease_linear:
    .a8
    pla                             ; restore original intensity
    and #$1F                        ; identity: just clamp
    plx
    rts


; =============================================================================
; _hdma_rgb_fill_tables — Build 3 COLDATA tables from accumulators/steps
; =============================================================================
; Expects: HDMA_TBL_PTR (red), HDMA_TBL_PTR_G (green), HDMA_TBL_PTR_B (blue)
;          HDMA_GRAD_RGB_ACCUM_R/G/B and STEP_R/G/B set
;          HDMA_GRAD_RGB_EASING set
; Leaves:  DB=$00, A16, I16
;
; Each table entry is 2 bytes: [count=1, COLDATA_byte].
; Y offset for scanline N = N*2. Y is recomputed from X (scanline counter)
; for each channel write to avoid tracking 3 separate offsets.
; =============================================================================
_hdma_rgb_fill_tables:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E for WRAM writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ldx #$0000                      ; scanline counter

@rgb_fill_loop:
    .a16
    ; Compute Y = scanline * 2
    txa
    asl
    tay                             ; Y = X * 2

    ; --- Red channel ---
    lda HDMA_GRAD_RGB_ACCUM_R
    xba                             ; A.lo = integer part
    sep #$20
    .a8
    and #$1F                        ; clamp to 5 bits
    jsr hdma_apply_easing
    ora #COLDATA_RED                ; $20 | intensity
    pha
    lda #$01
    sta (HDMA_TBL_PTR),y            ; [Y] = count byte = 1
    iny
    pla
    sta (HDMA_TBL_PTR),y            ; [Y+1] = COLDATA red byte
    dey                             ; Y back to scanline*2

    ; --- Green channel ---
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_ACCUM_G
    xba
    sep #$20
    .a8
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_GREEN              ; $40 | intensity
    pha
    lda #$01
    sta (HDMA_TBL_PTR_G),y          ; [Y] = count byte = 1
    iny
    pla
    sta (HDMA_TBL_PTR_G),y          ; [Y+1] = COLDATA green byte
    dey                             ; Y back to scanline*2

    ; --- Blue channel ---
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_ACCUM_B
    xba
    sep #$20
    .a8
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_BLUE               ; $80 | intensity
    pha
    lda #$01
    sta (HDMA_TBL_PTR_B),y          ; [Y] = count byte = 1
    iny
    pla
    sta (HDMA_TBL_PTR_B),y          ; [Y+1] = COLDATA blue byte

    ; --- Advance accumulators ---
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_ACCUM_R
    clc
    adc HDMA_GRAD_RGB_STEP_R
    sta HDMA_GRAD_RGB_ACCUM_R

    lda HDMA_GRAD_RGB_ACCUM_G
    clc
    adc HDMA_GRAD_RGB_STEP_G
    sta HDMA_GRAD_RGB_ACCUM_G

    lda HDMA_GRAD_RGB_ACCUM_B
    clc
    adc HDMA_GRAD_RGB_STEP_B
    sta HDMA_GRAD_RGB_ACCUM_B

    inx
    cpx #HDMA_SCANLINES
    beq @rgb_fill_done
    jmp @rgb_fill_loop

@rgb_fill_done:
    ; Write end-of-table markers for all 3 tables
    ; Y = HDMA_SCANLINES * 2 = 450
    txa
    asl
    tay
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y
    sta (HDMA_TBL_PTR_G),y
    sta (HDMA_TBL_PTR_B),y

    ; Restore DB=$00
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_stops_fill_tables — Build tables from multi-stop array
; =============================================================================
; Reads stop array from HDMA_GRAD_STOP_ADDR, interpolates between
; adjacent stops, writes to all 3 channel tables.
; =============================================================================
_hdma_stops_fill_tables:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E for WRAM writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ; TODO: Full multi-stop implementation
    ; For now, use first and last stop as 2-stop fallback
    ; This is a simplified version that will be enhanced

    ldy #$0000                      ; table write offset
    ldx #$0000                      ; scanline counter

    ; Read first stop RGB as top color
    lda HDMA_GRAD_STOP_ADDR
    sta $B8                         ; temp: stop array pointer

    ; Read stop[0] colors
    ldy #2                          ; offset to R in first stop
    lda ($B8),y                     ; low byte = R
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_R
    iny                             ; offset to G
    lda ($B8),y
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_G
    iny                             ; offset to B
    lda ($B8),y
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_B

    ; Read last stop colors
    sep #$20
    .a8
    lda HDMA_GRAD_STOP_COUNT
    dec                             ; last stop index
    rep #$20
    .a16
    and #$00FF
    ; Multiply by 6 (stop size)
    pha
    asl                             ; *2
    clc
    adc 1,s                         ; *3
    asl                             ; *6
    sta 1,s                         ; offset = index * 6
    pla
    clc
    adc $B8                         ; pointer to last stop
    sta $BA                         ; temp pointer

    ldy #2
    lda ($BA),y
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_R
    iny
    lda ($BA),y
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_G
    iny
    lda ($BA),y
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_B

    ; Restore DB=$00 (fill_tables sets DB=$7E internally)
    sep #$20
    .a8
    lda #$00
    pha
    plb
    rep #$20
    .a16

    ; Now do the actual multi-stop fill
    jsr _hdma_stops_fill_multi
    rts


; =============================================================================
; _hdma_stops_fill_multi — Full N-stop interpolation
; =============================================================================
_hdma_stops_fill_multi:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E for WRAM writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

    ; Process stop pairs: for each adjacent pair, interpolate the segment
    ; Use $B8 as current stop pointer, $BA as next stop pointer
    lda HDMA_GRAD_STOP_ADDR
    sta $B8                         ; current stop pointer

    ldy #$0000                      ; table write position (scanline * 2)
    ldx #$0000                      ; current scanline

    ; Fill scanlines before first stop with first stop's color
    ; Read first stop scanline
    lda ($B8)                       ; stop[0].scanline
    beq @stops_start_segment        ; if first stop is at scanline 0, skip fill
    ; Fill 0..stop[0].scanline-1 with stop[0] color
    sta HDMA_GRAD_RGB_STEP_R        ; temp: target scanline
    ; Read first stop colors
    phy
    ldy #2
    lda ($B8),y                     ; R
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_R       ; use as constant value
    iny
    lda ($B8),y                     ; G
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_G
    iny
    lda ($B8),y                     ; B
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_B
    ply

@stops_prefill_loop:
    cpx HDMA_GRAD_RGB_STEP_R        ; reached first stop scanline?
    bcs @stops_start_segment
    ; Write constant color for this scanline
    jsr _hdma_rgb_write_scanline_const
    inx
    bra @stops_prefill_loop

@stops_start_segment:
    ; Process each stop pair
    ; $BC = stop index counter
    stz $BC                         ; current stop index

@stops_next_pair:
    ; Check if we have a next stop
    sep #$20
    .a8
    lda HDMA_GRAD_STOP_COUNT
    dec                             ; last valid index
    rep #$20
    .a16
    and #$00FF
    cmp $BC
    bne @stops_not_last             ; long branch: beq @stops_postfill
    jmp @stops_postfill
@stops_not_last:
    bcs @stops_not_past             ; long branch: bcc @stops_postfill
    jmp @stops_postfill
@stops_not_past:

    ; Compute next stop pointer: $BA = $B8 + 6
    lda $B8
    clc
    adc #GRAD_STOP_SIZE
    sta $BA

    ; Read current stop scanline and next stop scanline
    lda ($B8)                       ; cur.scanline
    sta HDMA_GRAD_RGB_STEP_R        ; temp: start scanline
    lda ($BA)                       ; next.scanline
    sta HDMA_GRAD_RGB_STEP_G        ; temp: end scanline

    ; Compute span
    sec
    sbc HDMA_GRAD_RGB_STEP_R        ; span = end - start
    bne @stops_nonzero_span         ; long branch: beq @stops_advance_pair
    jmp @stops_advance_pair
@stops_nonzero_span:
    sta HDMA_GRAD_RGB_STEP_B        ; temp: span

    ; Read current stop colors (8.8 accumulators)
    phy
    ldy #2
    lda ($B8),y                     ; R
    and #$00FF
    xba                             ; << 8 to 8.8
    sta HDMA_GRAD_RGB_ACCUM_R
    iny
    lda ($B8),y                     ; G
    and #$00FF
    xba
    sta HDMA_GRAD_RGB_ACCUM_G
    iny
    lda ($B8),y                     ; B
    and #$00FF
    xba
    sta HDMA_GRAD_RGB_ACCUM_B

    ; Save X (scanline counter) — divisions clobber X
    phx

    ; Read next stop colors, compute per-channel steps
    ldy #2
    lda ($BA),y                     ; next R
    and #$00FF
    xba                             ; << 8
    sec
    sbc HDMA_GRAD_RGB_ACCUM_R       ; delta = (next - cur) << 8
    ; Divide by span
    pha
    lda HDMA_GRAD_RGB_STEP_B        ; span
    sta $BE                         ; divisor (temp)
    pla
    jsr _hdma_signed_div_var
    sta HDMA_GRAD_RGB_STEP_R        ; step_r
    pha                             ; save step_r on stack

    ldy #3
    lda ($BA),y                     ; next G
    and #$00FF
    xba
    sec
    sbc HDMA_GRAD_RGB_ACCUM_G
    jsr _hdma_signed_div_var
    pha                             ; save step_g

    ldy #4
    lda ($BA),y                     ; next B
    and #$00FF
    xba
    sec
    sbc HDMA_GRAD_RGB_ACCUM_B
    jsr _hdma_signed_div_var
    sta $BE                         ; step_b in temp

    ; Pop step_g and step_r
    pla                             ; step_g
    sta HDMA_GRAD_RGB_STEP_G
    pla                             ; step_r
    sta HDMA_GRAD_RGB_STEP_R
    lda $BE
    sta HDMA_GRAD_RGB_STEP_B

    plx                             ; restore X (scanline counter) — LIFO: X was pushed after Y
    ply                             ; restore Y (table offset)

    ; Fill scanlines for this segment
    lda ($BA)                       ; next stop scanline (end of segment)
    sta $BE                         ; temp: end scanline

@stops_seg_loop:
    cpx $BE                         ; reached end scanline?
    bcs @stops_advance_pair
    cpx #HDMA_SCANLINES
    bcs @stops_done                 ; past visible area

    ; Write interpolated color for this scanline
    jsr _hdma_rgb_write_scanline

    ; Advance accumulators
    lda HDMA_GRAD_RGB_ACCUM_R
    clc
    adc HDMA_GRAD_RGB_STEP_R
    sta HDMA_GRAD_RGB_ACCUM_R
    lda HDMA_GRAD_RGB_ACCUM_G
    clc
    adc HDMA_GRAD_RGB_STEP_G
    sta HDMA_GRAD_RGB_ACCUM_G
    lda HDMA_GRAD_RGB_ACCUM_B
    clc
    adc HDMA_GRAD_RGB_STEP_B
    sta HDMA_GRAD_RGB_ACCUM_B

    inx
    bra @stops_seg_loop

@stops_advance_pair:
    ; Move to next pair
    lda $B8
    clc
    adc #GRAD_STOP_SIZE
    sta $B8                         ; advance current stop pointer
    inc $BC                         ; increment stop index
    jmp @stops_next_pair

@stops_postfill:
    ; Fill remaining scanlines with last stop's color
    cpx #HDMA_SCANLINES
    bcs @stops_done

    ; Read last stop colors
    phy
    ldy #2
    lda ($B8),y
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_R
    iny
    lda ($B8),y
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_G
    iny
    lda ($B8),y
    and #$00FF
    sta HDMA_GRAD_RGB_ACCUM_B
    ply

@stops_postfill_loop:
    cpx #HDMA_SCANLINES
    bcs @stops_done
    jsr _hdma_rgb_write_scanline_const
    inx
    bra @stops_postfill_loop

@stops_done:
    ; Write end-of-table markers
    ; Y = current write position = X * 2
    txa
    asl                             ; Y = scanline * 2
    tay
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y
    sta (HDMA_TBL_PTR_G),y
    sta (HDMA_TBL_PTR_B),y

    ; Restore DB=$00
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_rgb_write_scanline — Write one scanline to all 3 tables (interpolated)
; =============================================================================
; Input: X = scanline, Y = write offset (X*2), accumulators set
; Output: Y advanced by 2
; =============================================================================
_hdma_rgb_write_scanline:
    .a16
    .i16
    ; Compute Y from X
    phx
    txa
    asl
    tay                             ; Y = scanline * 2

    ; Red
    lda HDMA_GRAD_RGB_ACCUM_R
    xba                             ; integer part
    sep #$20
    .a8
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_RED
    pha
    lda #$01
    sta (HDMA_TBL_PTR),y
    iny
    pla
    sta (HDMA_TBL_PTR),y
    dey                             ; reset Y for green

    ; Green
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_ACCUM_G
    xba
    sep #$20
    .a8
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_GREEN
    pha
    lda #$01
    sta (HDMA_TBL_PTR_G),y
    iny
    pla
    sta (HDMA_TBL_PTR_G),y
    dey                             ; reset Y for blue

    ; Blue
    rep #$20
    .a16
    lda HDMA_GRAD_RGB_ACCUM_B
    xba
    sep #$20
    .a8
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_BLUE
    pha
    lda #$01
    sta (HDMA_TBL_PTR_B),y
    iny
    pla
    sta (HDMA_TBL_PTR_B),y

    rep #$20
    .a16
    plx
    rts


; =============================================================================
; _hdma_rgb_write_scanline_const — Write constant color to all 3 tables
; =============================================================================
; Input: X = scanline, accum_R/G/B = plain intensity values (not 8.8)
; =============================================================================
_hdma_rgb_write_scanline_const:
    .a16
    .i16
    phx
    txa
    asl
    tay                             ; Y = scanline * 2

    sep #$20
    .a8
    ; Red
    lda #$01
    sta (HDMA_TBL_PTR),y
    lda HDMA_GRAD_RGB_ACCUM_R
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_RED
    iny
    sta (HDMA_TBL_PTR),y
    dey

    ; Green
    lda #$01
    sta (HDMA_TBL_PTR_G),y
    lda HDMA_GRAD_RGB_ACCUM_G
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_GREEN
    iny
    sta (HDMA_TBL_PTR_G),y
    dey

    ; Blue
    lda #$01
    sta (HDMA_TBL_PTR_B),y
    lda HDMA_GRAD_RGB_ACCUM_B
    and #$1F
    jsr hdma_apply_easing
    ora #COLDATA_BLUE
    iny
    sta (HDMA_TBL_PTR_B),y

    rep #$20
    .a16
    plx
    rts


; =============================================================================
; _hdma_rgb_release — Release RGB gradient channels if allocated
; =============================================================================
_hdma_rgb_release:
    rep #$30
    .a16
    .i16
    lda HDMA_GRAD_RGB_CH_R
    beq @release_done

    ; Deallocate each channel by clearing its bit in HDMA_ALLOC
    lda HDMA_GRAD_RGB_CH_R
    jsr _hdma_dealloc_channel
    lda HDMA_GRAD_RGB_CH_G
    jsr _hdma_dealloc_channel
    lda HDMA_GRAD_RGB_CH_B
    jsr _hdma_dealloc_channel

    ; Clear channel tracking
    stz HDMA_GRAD_RGB_CH_R
    stz HDMA_GRAD_RGB_CH_G
    stz HDMA_GRAD_RGB_CH_B

    ; Clear animation state
    stz HDMA_GRAD_PHASE
    stz HDMA_GRAD_SPEED
    sep #$20
    .a8
    stz HDMA_GRAD_RGB_FLAGS
    stz HDMA_GRAD_RGB_EASING
    rep #$20
    .a16

@release_done:
    rts


; =============================================================================
; _hdma_dealloc_channel — Free a single HDMA channel
; =============================================================================
; Input: A = channel number (3-7)
;
; Phase 17-0b1: converts channel number to mask and calls the Phase 17-0a
; `hdma_release` (which maintains `HDMA_ALLOC_MASK` at `$7E:C800`). Also
; clears the channel's bit from `NMI_HDMA_ENABLE` so the per-frame HDMAEN
; arm sequence stops driving it. The Phase 4 `HDMA_ALLOC` / `HDMA_EFFECT_CNT`
; state is gone; this routine is the sole release path for RGB gradient
; channels (still called from `engine_gradient_rgb_release`).
; =============================================================================
_hdma_dealloc_channel:
    .a16
    .i16
    and #$00FF                      ; mask out any garbage in high byte
    sec
    sbc #3                          ; 0-4
    tax
    sep #$20
    .a8
    lda f:_hdma_channel_bits,x      ; bit mask for this channel
    pha                             ; save mask byte for both updates
    eor #$FF                        ; invert for AND-clear
    and NMI_HDMA_ENABLE
    sta NMI_HDMA_ENABLE             ; clear from enable mask
    rep #$20
    .a16
    pla                             ; A = mask byte (low); high is stack garbage
    and #$00FF
    jsr hdma_release                ; push to 17-0a allocator
    rts


; =============================================================================
; _hdma_signed_div_225 — Signed 16-bit division by 225
; =============================================================================
; Input:  A = dividend (signed 16-bit, already shifted << 8)
; Output: A = quotient (signed 16-bit)
; =============================================================================
_hdma_signed_div_225:
    .a16
    bpl @sdiv225_pos
    ; Negative: negate, divide, negate
    eor #$FFFF
    inc
    jsr _hdma_udiv_225
    eor #$FFFF
    inc
    rts
@sdiv225_pos:
    jsr _hdma_udiv_225
    rts

_hdma_udiv_225:
    .a16
    ldx #$0000                      ; quotient
@udiv225_loop:
    cmp #225
    bcc @udiv225_done
    sec
    sbc #225
    inx
    bra @udiv225_loop
@udiv225_done:
    txa                             ; A = quotient
    rts


; =============================================================================
; _hdma_signed_div_var — Signed division by variable in $BE
; =============================================================================
; Input:  A = dividend (signed 16-bit), $BE = divisor (unsigned 16-bit, >0)
; Output: A = quotient (signed 16-bit)
; =============================================================================
_hdma_signed_div_var:
    .a16
    bpl @sdivv_pos
    eor #$FFFF
    inc
    jsr _hdma_udiv_var
    eor #$FFFF
    inc
    rts
@sdivv_pos:
    jsr _hdma_udiv_var
    rts

_hdma_udiv_var:
    .a16
    pha
    lda $BE
    beq @udivv_zero                 ; avoid division by zero
    pla
    ldx #$0000
@udivv_loop:
    cmp $BE
    bcc @udivv_done
    sec
    sbc $BE
    inx
    bra @udivv_loop
@udivv_done:
    txa
    rts
@udivv_zero:
    pla
    lda #$0000
    rts


; =============================================================================
; Easing LUT data (ROM)
; =============================================================================
.include "gradient_ease_lut.inc"
