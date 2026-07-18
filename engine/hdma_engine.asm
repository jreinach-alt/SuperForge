; =============================================================================
; hdma_engine.asm — Phase 4A.1 HDMA Effects Engine
; =============================================================================
; Provides HDMA channel management and effect builders for gradient(), wave(),
; and hdma_off(). Builds HDMA tables in WRAM that the NMI handler configures
; during VBlank Phase 5.
;
; Available HDMA channels: 3-7 (channels 0-2 reserved for general DMA).
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
;
; Cross-ref: engine_state.inc, nmi_handler.asm Phase 5, phase_4_effects_audio_gameplay.md
; =============================================================================

; Number of visible scanlines on NTSC SNES
HDMA_SCANLINES = 225

; COLDATA register
COLDATA_REG = $32

; BGnHOFS registers (write-twice)
BG1HOFS_REG = $0D
BG2HOFS_REG = $0F
BG3HOFS_REG = $11

; Channel bit positions for HDMA enable mask
HDMA_CH3_BIT = $08
HDMA_CH4_BIT = $10
HDMA_CH5_BIT = $20
HDMA_CH6_BIT = $40
HDMA_CH7_BIT = $80

; Temporary DP pointers for dynamic HDMA table addressing.
; Used during table build loops with (dp),y indirect indexed mode.
; DP=$0000 for main thread, so these must be in $00-$FF range.
; $B0-$B3 is in the "engine cache" area of the DP layout.
HDMA_TBL_PTR  = $B0    ; 2 bytes: pointer to active HDMA table base
HDMA_TBL_PTR2 = $B2    ; 2 bytes: pointer to secondary table (iris right)
; v1.1 bend/tunnel: the per-frame curve refill reuses $B2 as the base-scroll
; addend (HDMA_BEND_BASE). Safe — the bend fill loop does not use a secondary
; table pointer (the scaled-word LUT lives at a fixed absolute home, $7E:E200).
HDMA_BEND_BASE = $B2   ; 2 bytes (alias of HDMA_TBL_PTR2): base BGnHOFS scroll


; Phase 17-0b1: 1-byte flag indicating the Phase 4 `hdma_alloc` wrapper
; holds CH2 as a system-reserved placeholder (so downstream effect
; builders that assume CH3+ indexing still work). Set when `hdma_alloc`
; first encounters CH2 free and pins it; cleared by `hdma_off` after
; the corresponding `hdma_release` call. Low WRAM, zero-initialized.
HDMA_PHASE4_CH2_PIN = $0582

; =============================================================================
; hdma_alloc — Allocate the lowest free HDMA channel (Phase 4 legacy API)
; =============================================================================
; Returns: A = channel number (3-7) on success, $FFFF if no channels free
; Modifies: A, X
;
; Phase 17-0b1: Thin wrapper around the Phase 17-0a allocator. The Phase 4
; body scanned its own `HDMA_ALLOC` bitmask; that bitmask is now gone and
; `hdma_request` at `engine/hdma_alloc.asm` is the single source of truth
; for HDMA channel ownership. Callers still see the original 3..7 return
; convention (with $FFFF on failure) so no call-site diffs are required.
; CH2 is skipped (released back) to preserve the Phase 4 "CH3-CH7 only"
; guarantee the effect builders below rely on (e.g., `sbc #3` indexing).
; =============================================================================
hdma_alloc:
    .a16
    .i16
    lda #$0001
    ldx #HDMA_EFFECT_USER
    jsr hdma_request
    bcs @alloc_fail                 ; carry set → allocator exhausted

    ; A now holds a single-bit channel mask ($04=CH2 .. $80=CH7).
    ; Phase 4 skipped CH2 entirely (its scan started at CH3); the
    ; downstream effect builders rely on that via `sbc #3` indexing into
    ; `_hdma_table_addrs` (a CH3..CH7 table). If the allocator handed us
    ; CH2, pin it (mark via HDMA_PHASE4_CH2_PIN) and request a second
    ; channel — the allocator now sees CH2 as busy and skips to CH3+.
    ; `hdma_off` releases the pin so CH2 is free again for the next scene.
    cmp #$0004
    bne @decode_mask
    sep #$20
    .a8
    lda #$01
    sta HDMA_PHASE4_CH2_PIN         ; mark CH2 as held by us
    rep #$20
    .a16
    lda #$0001
    ldx #HDMA_EFFECT_USER
    jsr hdma_request                ; second request; skips CH2 (busy)
    bcs @alloc_fail                 ; only CH2 was free → give up

@decode_mask:
    ; Mask → channel number. Bit N set ⇒ channel N. Mask is guaranteed
    ; single-bit and in $08..$80 at this point.
    sep #$20
    .a8
    ldx #$03                        ; start counting from CH3
@decode_loop:
    cmp #$08
    beq @decode_done
    lsr
    inx
    bra @decode_loop
@decode_done:
    txa
    rep #$20
    .a16
    and #$00FF
    rts

@alloc_fail:
    lda #$FFFF
    rts


; =============================================================================
; hdma_off — Disable all HDMA effects
; =============================================================================
; Clears allocation mask, effect count, and HDMA enable mask.
; =============================================================================
hdma_off:
    .a16
    .i16
    ; Phase 17-9: if the split-mode module is linked in, tear down any
    ; staged BGMODE HDMA before we touch HDMA_ALLOC / NMI_HDMA_ENABLE.
    ; MODE_SPLIT_PROVIDED is set by engine/mode_split_hdma.asm; ROMs that
    ; include both must include mode_split_hdma.asm BEFORE hdma_engine.asm
    ; so the .ifdef resolves at this assemble point.
.ifdef MODE_SPLIT_PROVIDED
    jsr engine_mode_bands_clear
.endif
    ; Phase 17-0b1: release every channel still owned by a Phase 4 effect
    ; (gradient/wave/iris/scanline_scroll + RGB gradient R/G/B). Collect
    ; their channel numbers, fold them into a mask, hand it to
    ; `hdma_release` so the 17-0a allocator bitmask (`HDMA_ALLOC_MASK`)
    ; reflects the teardown. Skipped channels (value 0 in the tracking
    ; slot) contribute nothing to the mask.
    jsr _hdma_release_all_legacy
    sep #$20
    .a8
    stz NMI_HDMA_ENABLE
    ; Clear window masking registers (disables iris effect)
    stz SHADOW_W12SEL
    stz SHADOW_W34SEL
    stz SHADOW_WOBJSEL
    stz SHADOW_WBGLOG
    stz SHADOW_WOBJLOG
    stz SHADOW_TMW
    stz SHADOW_TSW
    rep #$20
    .a16
    ; Clear per-effect channel tracking so per-frame updates know to stop.
    ; HDMA_SCROLL_CHAN at $7EE0C4 is a 24-bit symbol — STZ has no long
    ; form, and STA needs `f:` to force long-form addressing in .a16 mode.
    ; HDMA_WAVE_CHAN ($0584) and HDMA_IRIS_CHAN_L/R ($018F/$0191) are at
    ; absolute low-WRAM, so plain stz works for those.
    lda #$0000                      ; A16 (rep #$20 above set .a16)
    sta f:HDMA_SCROLL_CHAN          ; scanline_scroll channel ($7EE0C4)
    sta f:HDMA_BEND_CHAN            ; bend/tunnel channel ($7EE0B6)
    stz HDMA_WAVE_CHAN              ; wave channel ($0584)
    stz HDMA_IRIS_CHAN_L            ; iris left channel  ($018F)
    stz HDMA_IRIS_CHAN_R            ; iris right channel ($0191)
    ; Clear RGB gradient channel tracking (Phase 9)
    stz HDMA_GRAD_RGB_CH_R          ; gradient red channel
    stz HDMA_GRAD_RGB_CH_G          ; gradient green channel
    stz HDMA_GRAD_RGB_CH_B          ; gradient blue channel
    stz HDMA_GRAD_PHASE             ; animation phase
    stz HDMA_GRAD_SPEED             ; animation speed
    sep #$20
    .a8
    stz HDMA_GRAD_RGB_FLAGS         ; gradient flags
    stz HDMA_GRAD_RGB_EASING        ; easing type
    rep #$20
    .a16
    rts


; =============================================================================
; hdma_channels — Return number of free HDMA channels
; =============================================================================
; Returns: A = number of free channels (0-5)
;
; Phase 17-0b1: count zero-bits in CH3-CH7 of `HDMA_ALLOC_MASK` at
; `$7E:C800`. The Phase 4 `HDMA_EFFECT_CNT` byte is gone — the allocator
; bitmask is the single source of truth. CH2 is considered "not free" for
; this API's contract (matches Phase 4's 5-channel horizon).
; =============================================================================
hdma_channels:
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    ; HDMA_ALLOC_MASK lives at $01D0 (engine state area, bank $00/$7E
    ; mirror) since the Phase 17-0b1 relocation. Read via long-addressing
    ; so we stay DB-independent.
    lda f:$7E0000 + $01D0           ; HDMA_ALLOC_MASK
    ora #$04                        ; treat CH2 as busy (Phase 4 horizon)
    ldx #$00                        ; free-channel counter
    ldy #$05                        ; check 5 bits (CH3..CH7)
@ch_loop:
    asl
    bcs @ch_busy
    inx
@ch_busy:
    dey
    bne @ch_loop
    txa
    rep #$20
    .a16
    and #$00FF
    rts


; =============================================================================
; _hdma_release_all_legacy — Release every channel owned by a Phase 4 effect
; =============================================================================
; Walks the per-effect channel-tracking WRAM slots, converts each non-zero
; channel number to a mask bit, ORs them together, and calls `hdma_release`
; once with the combined mask. Also zeros the per-effect channel slots.
;
; No parameters. Clobbers A, X, Y. A16/I16 on entry and exit.
; =============================================================================
_hdma_release_all_legacy:
    rep #$30
    .a16
    .i16
    ; Release everything except CH0/CH1 (which hdma_alloc_init pinned as
    ; system-reserved). `hdma_release` ignores those bits anyway, but
    ; masking here keeps the semantic obvious. Covers:
    ;   - the CH2 placeholder pin from `hdma_alloc` (if any)
    ;   - all per-effect channels (gradient/wave/iris/scanline_scroll, RGB)
    ;   - any standalone `hdma_alloc` allocations not tied to an effect
    sep #$20
    .a8
    stz HDMA_PHASE4_CH2_PIN         ; pin flag cleared regardless
    rep #$20
    .a16
    lda HDMA_ALLOC_MASK
    and #$00FC                      ; drop CH0/CH1
    beq @done                       ; nothing owned
    jsr hdma_release
@done:
    rts


; =============================================================================
; hdma_build_gradient — Build a COLDATA gradient HDMA table
; =============================================================================
; Builds a continuous HDMA table for a luminance gradient across all scanlines.
; Each scanline writes COLDATA ($2132) with R=G=B set to the interpolated
; intensity value.
;
; Input (via scratch WRAM, set by caller):
;   HDMA_GRAD_TOP  (2 bytes): top intensity (0-31)
;   HDMA_GRAD_BOT  (2 bytes): bottom intensity (0-31)
;
; Output:
;   Allocates HDMA channel, builds table, configures channel state.
;   Returns: A = channel number (3-7) or $FFFF if allocation failed.
;
; COLDATA encoding: $E0 | intensity (bits 7-5 = RGB all, bits 4-0 = value)
;
; Uses 16-bit fixed-point interpolation: accumulator starts at top<<8,
; increments by ((bottom - top) << 8) / 225 each scanline.
; =============================================================================

; Scratch for gradient builder (in WRAM scratch area)
HDMA_GRAD_TOP    = $0576        ; 2 bytes: top intensity
HDMA_GRAD_BOT    = $0578        ; 2 bytes: bottom intensity
HDMA_GRAD_ACCUM  = $057A        ; 2 bytes: fixed-point accumulator (8.8)
HDMA_GRAD_STEP   = $057C        ; 2 bytes: fixed-point step (8.8, signed)
HDMA_GRAD_CHAN    = $057E        ; 2 bytes: allocated channel number

hdma_build_gradient:
    .a16
    .i16
    ; Allocate a channel
    jsr hdma_alloc
    cmp #$FFFF
    bne @grad_alloc_ok
    rts                             ; allocation failed, return $FFFF
@grad_alloc_ok:

    ; Save channel number
    sta HDMA_GRAD_CHAN
    pha

    ; Look up correct table address for allocated channel
    lda HDMA_GRAD_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR                ; store in DP pointer for (dp),y addressing

    ; Compute step = ((bottom - top) << 8) / 225
    lda HDMA_GRAD_BOT
    sec
    sbc HDMA_GRAD_TOP               ; A = bottom - top (signed 16-bit)
    xba                             ; A = (bottom - top) << 8
    sta HDMA_GRAD_STEP

    ; Signed division: check sign, make positive, divide, restore sign
    lda HDMA_GRAD_STEP
    bpl @div_positive
    eor #$FFFF
    inc
    sta HDMA_GRAD_STEP
    jsr _hdma_divide_by_225
    lda HDMA_GRAD_STEP
    eor #$FFFF
    inc
    sta HDMA_GRAD_STEP
    bra @div_done

@div_positive:
    jsr _hdma_divide_by_225

@div_done:
    ; Initialize accumulator = top << 8
    lda HDMA_GRAD_TOP
    xba                             ; A = top << 8
    sta HDMA_GRAD_ACCUM

    ; Configure channel state
    pla                             ; A = channel number
    pha
    jsr _hdma_configure_channel_gradient

    ; Build the table: 225 entries, each [1, COLDATA_byte]
    ; Use Y as offset within the HDMA table. DB=$7E for WRAM writes.
    ; STA abs,Y with DB=$7E writes to $7E:abs+Y.
    ldy #$0000                      ; table write offset
    ldx #$0000                      ; scanline counter

    ; Set DB=$7E
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

@grad_loop:
    ; Write scanline count = 1
    sep #$20
    .a8
    lda #$01
    sta (HDMA_TBL_PTR),y            ; abs,Y → $7E:C000+Y (line count)
    iny

    ; Write COLDATA byte: $E0 | (accumulator >> 8)
    rep #$20
    .a16
    lda HDMA_GRAD_ACCUM
    xba                             ; A.lo = integer part
    sep #$20
    .a8
    and #$1F                        ; clamp to 5 bits
    ora #$E0                        ; R+G+B channel select
    sta (HDMA_TBL_PTR),y            ; abs,Y → $7E:C000+Y (COLDATA byte)
    iny

    ; Advance accumulator
    rep #$20
    .a16
    lda HDMA_GRAD_ACCUM
    clc
    adc HDMA_GRAD_STEP
    sta HDMA_GRAD_ACCUM

    ; Next scanline
    inx
    cpx #HDMA_SCANLINES
    bne @grad_loop

    ; Write end-of-table marker
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y

    ; Restore DB=$00
    lda #$00
    pha
    plb
    rep #$20
    .a16

    ; Update HDMA enable mask
    pla                             ; A = channel number
    pha
    jsr _hdma_enable_channel

    pla                             ; clean stack, A = channel number
    rts


; =============================================================================
; _hdma_divide_by_225 — HDMA_GRAD_STEP = HDMA_GRAD_STEP / 225
; =============================================================================
; Uses repeated subtraction. Input must be non-negative.
; Result stored back in HDMA_GRAD_STEP.
; =============================================================================
_hdma_divide_by_225:
    .a16
    lda HDMA_GRAD_STEP
    ldx #$0000                      ; quotient
@div_loop:
    cmp #225
    bcc @div_remainder
    sec
    sbc #225
    inx
    bra @div_loop
@div_remainder:
    stx HDMA_GRAD_STEP
    rts


; =============================================================================
; _hdma_configure_channel_gradient — Set up channel config for gradient
; =============================================================================
; Input: A = channel number (3-7)
; Phase 17-13: programs hardware HDMA channel registers ($43n0+) directly
; instead of writing engine-state shadows. The engine NMI's
; ownership-aware shadow commit (engine/nmi_handler.asm Phase 5) skips
; channels not in M7_OWNED_MASK, so this effect's hardware programming
; persists frame-to-frame without being clobbered by Brad's pv_rebuild
; vestigial CH3/CH4/CH7 shadow writes when Mode 7 is active.
; =============================================================================
_hdma_configure_channel_gradient:
    .a16
    .i16
    ; Compute hardware register offset = ch_num * 16 ($00, $10, $20...$70).
    asl
    asl
    asl
    asl                             ; A = ch_num * 16 (still A16)
    tax                             ; X = $43n0 offset for this channel

    sep #$20
    .a8
    ; DMAP: mode 0 (1 byte, 1 register), direct table
    lda #$00
    sta f:$004300, x                ; DMAPn

    ; BBAD: target register $2132 (COLDATA)
    lda #COLDATA_REG
    sta f:$004301, x                ; BBADn

    ; Table address (low + high bytes) + bank ($7E for WRAM tables)
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn (bank = $7E for WRAM)

    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_enable_channel — Set the HDMA enable bit for a channel
; =============================================================================
; Input: A = channel number (3-7)
; =============================================================================
_hdma_enable_channel:
    .a16
    .i16
    sec
    sbc #3                          ; A = 0-4
    tax
    sep #$20
    .a8
    lda f:_hdma_channel_bits,x
    ora NMI_HDMA_ENABLE
    sta NMI_HDMA_ENABLE
    rep #$20
    .a16
    rts


; =============================================================================
; hdma_build_wave — Build a BGnHOFS wave HDMA table
; =============================================================================
; Builds a sinusoidal horizontal scroll offset table for per-scanline wave
; distortion on a specified BG layer. Uses HDMA transfer mode $02 (write
; twice to same register) to write the 13-bit scroll value as [lo, hi].
;
; Input (via scratch WRAM, set by caller):
;   HDMA_WAVE_AMP   (2 bytes): peak amplitude in pixels (0-15)
;   HDMA_WAVE_LAYER (2 bytes): BG layer (1, 2, or 3)
;   HDMA_WAVE_PHASE ($0166): current phase (low byte used, 0-255)
;
; Output:
;   Allocates HDMA channel, builds table at HDMA_TABLE_CH3, configures
;   channel for mode $02 to the appropriate BGnHOFS register.
;   Returns: A = channel number (3-7) or $FFFF if allocation failed.
;
; Algorithm: For each scanline s (0-224):
;   1. index = (s + phase) & $FF
;   2. sin_val = lookup_sine(index)  ; signed byte -127..+127
;   3. offset = (sin_val * amplitude) / 128  ; signed
;   4. Write [1, offset_lo, offset_hi] to table
;
; Quarter-wave sine lookup with mirror/negate for quadrants:
;   Q0 (index 0-63):   +table[index]
;   Q1 (index 64-127):  +table[127-index]
;   Q2 (index 128-191): -table[index-128]
;   Q3 (index 192-255): -table[255-index]
;
; Uses SNES hardware multiplier ($4202/$4203) for sin_val * amplitude.
; Must wait 8 machine cycles after writing WRMPYB before reading result.
;
; Cross-ref: engine_state.inc (HDMA_WAVE_* scratch), phase_4_effects_audio_gameplay.md
; =============================================================================

; Scratch for wave sign tracking (reuse area after gradient scratch)
HDMA_WAVE_SIGN   = $0586        ; 1 byte: 0 = positive, 1 = negative

hdma_build_wave:
    .a16
    .i16
    ; Allocate a channel
    jsr hdma_alloc
    cmp #$FFFF
    bne @wave_alloc_ok
    rts                             ; allocation failed, return $FFFF
@wave_alloc_ok:
    .a16

    ; Save channel number
    sta HDMA_WAVE_CHAN
    pha

    ; Look up correct table address for allocated channel
    lda HDMA_WAVE_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR                ; store in DP pointer for (dp),y addressing

    ; Determine BBAD register based on layer
    ; Layer 1 → $0D (BG1HOFS), 2 → $0F (BG2HOFS), 3 → $11 (BG3HOFS)
    lda HDMA_WAVE_LAYER
    dec                             ; 0-based: 0, 1, 2
    asl                             ; *2: 0, 2, 4
    clc
    adc #BG1HOFS_REG                ; $0D, $0F, $11
    pha                             ; save BBAD on stack

    ; Configure channel state
    ; Stack: [BBAD, channel_num]
    ; We need channel number for _hdma_configure_channel_wave
    lda 3,s                         ; channel number (under BBAD on stack)
    tax                             ; X = channel number

    ; Compute hardware register offset = ch_num * 16 ($30, $40, $50, $60, $70).
    txa
    asl
    asl
    asl
    asl                             ; A = ch_num * 16 (hardware reg offset)
    tax                             ; X = $43n0 base for this channel

    sep #$20
    .a8

    ; Phase 17-13: program hardware HDMA registers ($43n0+) directly.
    ; The engine NMI's ownership-aware shadow commit skips channels not
    ; in M7_OWNED_MASK, so this hardware programming persists through
    ; any Mode 7 scene that isn't claiming this channel.

    ; DMAP: mode $02 (write twice to same register)
    lda #$02
    sta f:$004300, x                ; DMAPn

    ; BBAD: target register from stack
    lda 1,s                         ; low byte of BBAD value on stack
    sta f:$004301, x                ; BBADn

    ; Table address (low + high) + bank ($7E for WRAM tables)
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn

    rep #$20
    .a16

    ; Remove BBAD from stack (channel num still there)
    pla                             ; discard BBAD
    ; Stack: [channel_num]

    ; Build the table: 225 entries, each [1, scroll_lo, scroll_hi]
    ; Y = table write offset, X = scanline counter
    ldy #$0000                      ; table write offset
    ldx #$0000                      ; scanline counter

    ; Set DB=$7E for WRAM writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

@wave_loop:
    .a16
    ; Compute index = (scanline + phase) & $FF
    ; X = scanline counter (16-bit)
    txa                             ; A = scanline
    clc
    adc HDMA_WAVE_PHASE             ; A = scanline + phase
    and #$00FF                      ; mask to 8 bits
    ; A = index (0-255)

    ; --- Quarter-wave sine lookup ---
    ; Determine quadrant and compute sine value
    pha                             ; save index
    and #$00C0                      ; isolate quadrant bits (bits 7-6)
    beq @wave_q0
    cmp #$0040
    beq @wave_q1
    cmp #$0080
    beq @wave_q2
    ; Fall through to Q3

@wave_q3:
    .a16
    ; Q3 (index 192-255): sin = -table[255-index]
    sep #$20
    .a8
    stz HDMA_WAVE_SIGN              ; mark negative temporarily
    lda #$01
    sta HDMA_WAVE_SIGN
    rep #$20
    .a16
    pla                             ; A = index
    eor #$00FF                      ; A = 255 - index (since index XOR $FF = 255-index for 8-bit)
    ; But we need to keep only low 6 bits → result is (255 - index) & $3F
    ; Actually: 255 - index where index is 192..255 → result is 63..0
    ; which is already 0..63. Let's verify: 255 - 192 = 63, 255 - 255 = 0. Correct.
    and #$003F
    bra @wave_lookup

@wave_q0:
    .a16
    ; Q0 (index 0-63): sin = +table[index]
    sep #$20
    .a8
    stz HDMA_WAVE_SIGN              ; positive
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F
    bra @wave_lookup

@wave_q1:
    .a16
    ; Q1 (index 64-127): sin = +table[127-index] = +table[63-(index&63)]
    sep #$20
    .a8
    stz HDMA_WAVE_SIGN              ; positive
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F                      ; index & 63
    eor #$003F                      ; 63 - (index & 63)
    bra @wave_lookup

@wave_q2:
    .a16
    ; Q2 (index 128-191): sin = -table[index-128] = -table[index & 63]
    sep #$20
    .a8
    lda #$01
    sta HDMA_WAVE_SIGN              ; negative
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F
    ; fall through to @wave_lookup

@wave_lookup:
    .a16
    ; A = table index (0-63), look up quarter-wave sine value
    ; Save X (scanline counter) and Y (table offset)
    phx
    phy
    tax                             ; X = table index
    sep #$20
    .a8
    lda f:_hdma_sine_quarter,x      ; A = sine value (0-127, unsigned)

    ; --- Multiply sin_val * amplitude using hardware multiplier ---
    ; WRMPYA ($4202) = sin_val (unsigned 8-bit)
    ; WRMPYB ($4203) = amplitude (unsigned 8-bit)
    ; NOTE: DB=$7E here, so we MUST use long addressing (f:) for HW regs
    sta f:$004202                   ; WRMPYA = abs(sin_val)
    lda HDMA_WAVE_AMP               ; amplitude (low byte, 0-15) — WRAM ok with DB=$7E
    sta f:$004203                   ; WRMPYB = amplitude
    ; Must wait 8 machine cycles before reading result
    nop                             ; 2 cycles
    nop                             ; 2 cycles
    nop                             ; 2 cycles
    nop                             ; 2 cycles (total: 8)

    ; Read 16-bit result from RDMPYL/H ($4216-$4217)
    rep #$20
    .a16
    lda f:$004216                   ; A = sin_val * amplitude (16-bit)

    ; Divide by 128: shift right 7 = take bits 15..7
    ; Equivalent to: swap hi/lo bytes then mask, or shift
    ; Use 7 right shifts... or: A = (A >> 7) = (A << 1) >> 8 = xba after asl
    asl                             ; shift left 1 (now bit 7 is in bit 8)
    xba                             ; swap bytes → A.lo = high byte of shifted result
    and #$00FF                      ; mask to byte → A = result / 128

    ; Apply sign: if HDMA_WAVE_SIGN = 1, negate
    ply                             ; restore Y (table offset)
    plx                             ; restore X (scanline counter)

    ; A = unsigned offset (0-15 range for amp 0-15)
    sep #$20
    .a8

    ; Check sign
    pha                             ; save unsigned offset
    lda HDMA_WAVE_SIGN
    beq @wave_positive
    .a8
    ; Negative: two's complement of 16-bit offset
    ; offset_lo = (~offset + 1) & $FF, offset_hi = $FF
    pla                             ; A = unsigned offset
    eor #$FF
    inc                             ; A = -offset (8-bit two's complement)
    ; Write [1, offset_lo, $FF] to table
    pha                             ; save signed lo
    lda #$01
    sta (HDMA_TBL_PTR),y            ; scanline count = 1
    iny
    pla                             ; A = signed offset lo
    sta (HDMA_TBL_PTR),y            ; scroll_lo
    iny
    lda #$FF                        ; sign extension for negative
    sta (HDMA_TBL_PTR),y            ; scroll_hi
    iny
    bra @wave_next

@wave_positive:
    .a8
    pla                             ; A = unsigned offset
    ; Write [1, offset_lo, $00] to table
    pha                             ; save offset
    lda #$01
    sta (HDMA_TBL_PTR),y            ; scanline count = 1
    iny
    pla                             ; A = offset
    sta (HDMA_TBL_PTR),y            ; scroll_lo
    iny
    lda #$00                        ; sign extension for positive
    sta (HDMA_TBL_PTR),y            ; scroll_hi
    iny

@wave_next:
    .a8
    ; Restore 16-bit A for loop control
    rep #$20
    .a16
    ; Next scanline
    inx
    cpx #HDMA_SCANLINES
    beq @wave_loop_done
    jmp @wave_loop
@wave_loop_done:

    ; Write end-of-table marker ($00)
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y

    ; Restore DB=$00
    lda #$00
    pha
    plb
    rep #$20
    .a16

    ; Enable channel in HDMA mask
    pla                             ; A = channel number (from initial pha)
    pha
    jsr _hdma_enable_channel

    ; Return channel number
    pla
    rts


; =============================================================================
; hdma_build_iris — Build circular window HDMA tables (iris wipe)
; =============================================================================
; Builds two HDMA tables for Window 1 left (WH0 $2126) and right (WH1 $2127)
; boundaries, forming a circle of given radius centered at (cx, cy).
;
; Allocates 2 HDMA channels.
;
; Input (via scratch WRAM, set by caller):
;   HDMA_IRIS_CX     (2 bytes): circle center X (0-255)
;   HDMA_IRIS_CY     (2 bytes): circle center Y (0-224)
;   HDMA_IRIS_RADIUS (2 bytes): circle radius (0-127)
;
; Output:
;   Allocates 2 HDMA channels, builds left/right tables.
;   Left table at HDMA_TABLE_CH3, right table at HDMA_TABLE_CH4.
;   Returns: A = first channel number, or $FFFF if allocation failed.
;
; Algorithm: For each scanline s (0-224):
;   dy = abs(s - cy)
;   if dy >= radius: left=0, right=0
;   else: dx = isqrt(radius² - dy²)
;     left  = clamp(cx - dx, 0, 255)
;     right = clamp(cx + dx, 0, 255)
;
; Cross-ref: engine_state.inc, phase_4_effects_audio_gameplay.md
; =============================================================================

; Window registers
WH0_REG = $26                           ; Window 1 Left Position
WH1_REG = $27                           ; Window 1 Right Position

; Scratch for iris builder. Relocated from $0588-$0597 (collision-zone
; overlap with save_load_engine SL_* and debug_overlay OVERLAY_*) to
; absolute WRAM $0189-$0198 (= ENGINE_STATE_BASE + DP offset $89-$98) —
; see docs/audit/engine_wram_allocation_audit.md, sprint engine-hygiene-1.
;
; Why DP-shadow / absolute (not WRAM-extended like OVERLAY_* and SCROLL):
;   The Bresenham builder uses `ldx HDMA_IRIS_RADIUS` and
;   `cpx HDMA_IRIS_RADIUS` — LDX and CPX have NO absolute-long
;   addressing mode on the 65816. WRAM-extended ($7E:E0xx) addresses
;   would require lda+tax / store-to-scratch+cpx workarounds at every
;   site, costing more cycles than the move saves and risking
;   width-tracking bugs. Absolute WRAM at $0189+ keeps the existing
;   addressing modes intact (DB=$00 → bank-0/$7E mirror; LDX abs and
;   CPX abs work directly).
;
; The DP $89-$9E free block is shared with engine_state_m7_legacy.inc's
; pre-Phase-16 Mode 7 symbols. The legacy include is .ifndef-guarded;
; iris-using ROMs do not include it, and legacy-M7-using ROMs do not
; build hdma_engine.asm's iris path, so the byte share is harmless
; (engine_state.inc explicitly blesses this pattern at line ~245).
HDMA_IRIS_CX        = $0189             ; 2 bytes: center X
HDMA_IRIS_CY        = $018B             ; 2 bytes: center Y
HDMA_IRIS_RADIUS    = $018D             ; 2 bytes: radius
HDMA_IRIS_CHAN_L    = $018F             ; 2 bytes: left channel number
HDMA_IRIS_CHAN_R    = $0191             ; 2 bytes: right channel number
HDMA_IRIS_RSQ       = $0193             ; 2 bytes: radius squared
HDMA_IRIS_SQRT_VAL  = $0195             ; 2 bytes: sqrt working value
HDMA_IRIS_SQRT_ODD  = $0197             ; 2 bytes: sqrt odd counter

hdma_build_iris:
    .a16
    .i16
    ; Allocate first channel (left/WH0)
    jsr hdma_alloc
    cmp #$FFFF
    bne @iris_alloc1_ok
    rts                                 ; failed
@iris_alloc1_ok:
    .a16
    sta HDMA_IRIS_CHAN_L

    ; Look up correct table address for left channel
    sec
    sbc #3
    asl                                 ; word index
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR                    ; left channel table pointer

    ; Allocate second channel (right/WH1)
    jsr hdma_alloc
    cmp #$FFFF
    bne @iris_alloc2_ok
    ; Failed on second — should ideally free first, but just return error
    lda #$FFFF
    rts
@iris_alloc2_ok:
    .a16
    sta HDMA_IRIS_CHAN_R

    ; Look up correct table address for right channel
    sec
    sbc #3
    asl                                 ; word index
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR2                   ; right channel table pointer

    ; Compute radius² using hardware multiplier
    sep #$20
    .a8
    lda HDMA_IRIS_RADIUS
    sta $4202                           ; WRMPYA = radius
    sta $4203                           ; WRMPYB = radius
    nop                                 ; wait 8 cycles
    nop
    nop
    nop
    rep #$20
    .a16
    lda $4216                           ; A = radius²
    sta HDMA_IRIS_RSQ

    ; Phase 17-13: program hardware HDMA registers directly. Each
    ; channel: ch_num * 16 → $43n0 base. See _hdma_configure_channel_gradient
    ; for the architectural rationale (ownership-aware shadow commit).

    ; Configure left channel: DMAP=$00, BBAD=$26 (WH0), table=dynamic
    lda HDMA_IRIS_CHAN_L
    asl
    asl
    asl
    asl                                 ; A = ch_num * 16
    tax                                 ; X = $43n0 base for left channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                    ; DMAPn = mode 0
    lda #WH0_REG
    sta f:$004301, x                    ; BBADn = $26
    lda HDMA_TBL_PTR
    sta f:$004302, x                    ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                    ; A1TnH
    lda #$7E
    sta f:$004304, x                    ; A1Bn = $7E
    rep #$20
    .a16

    ; Configure right channel: DMAP=$00, BBAD=$27 (WH1), table=dynamic
    lda HDMA_IRIS_CHAN_R
    asl
    asl
    asl
    asl                                 ; A = ch_num * 16
    tax                                 ; X = $43n0 base for right channel
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                    ; DMAPn
    lda #WH1_REG
    sta f:$004301, x                    ; BBADn = $27
    lda HDMA_TBL_PTR2
    sta f:$004302, x                    ; A1TnL
    lda HDMA_TBL_PTR2+1
    sta f:$004303, x                    ; A1TnH
    lda #$7E
    sta f:$004304, x                    ; A1Bn = $7E
    rep #$20
    .a16

    ; Build both tables via shared subroutine
    jsr _hdma_iris_fill_tables

    ; Restore DB=$00 (fill_tables leaves DB=$7E, A in 16-bit mode)
    sep #$20
    .a8
    lda #$00
    pha
    plb
    rep #$20
    .a16

    ; Enable both channels
    lda HDMA_IRIS_CHAN_L
    jsr _hdma_enable_channel
    lda HDMA_IRIS_CHAN_R
    jsr _hdma_enable_channel

    ; === Configure window masking for iris effect ===
    ; The HDMA tables write per-scanline WH0/WH1 (window 1 left/right positions),
    ; but the PPU ignores window positions unless windowing is enabled on layers.
    ;
    ; Window 1 enable + invert per layer means:
    ;   Inside window (WH0..WH1): layer is shown (normal)
    ;   Outside window: layer is masked (transparent → backdrop shows)
    ;
    ; W12SEL/W34SEL bit layout per BG: bit 0 = enable, bit 1 = invert
    ;   $33 = BG1 enable+invert (bits 0,1) + BG2 enable+invert (bits 4,5)
    ; WOBJSEL: $03 = OBJ enable+invert, Color window disabled
    ;   (Color window left disabled so backdrop/color math shows outside circle)
    ; TMW = $1F = all 5 layers (BG1-4 + OBJ) can be masked by windows
    ; WBGLOG = $00 = OR logic (correct when only Window 1 is active)
    sep #$20
    .a8
    lda #$33
    sta SHADOW_W12SEL                   ; BG1+BG2: Window 1 enable + invert
    sta SHADOW_W34SEL                   ; BG3+BG4: Window 1 enable + invert
    lda #$03
    sta SHADOW_WOBJSEL                  ; OBJ: Window 1 enable + invert
    stz SHADOW_WBGLOG                   ; OR logic (safe default for single window)
    stz SHADOW_WOBJLOG                  ; OR logic for OBJ/Color
    lda #$1F
    sta SHADOW_TMW                      ; All layers masked by windows on main screen
    stz SHADOW_TSW                      ; Sub screen: no window masking
    rep #$20
    .a16

    ; Return first channel number
    lda HDMA_IRIS_CHAN_L
    rts


; =============================================================================
; hdma_rebuild_iris — Rebuild iris tables in-place (no channel allocation)
; =============================================================================
; Call when iris channels are already allocated (HDMA_IRIS_CHAN_L != 0).
; Updates HDMA_IRIS_RADIUS, recomputes tables, returns.
; Expects: HDMA_IRIS_CX, HDMA_IRIS_CY, HDMA_IRIS_RADIUS set by caller.
; =============================================================================
hdma_rebuild_iris:
    rep #$30
    .a16
    .i16
    ; Look up table pointers from stored channels
    lda HDMA_IRIS_CHAN_L
    sec
    sbc #3
    asl
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR

    lda HDMA_IRIS_CHAN_R
    sec
    sbc #3
    asl
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR2

    ; Build both tables
    jsr _hdma_iris_fill_tables

    ; Restore DB=$00 (fill_tables leaves DB=$7E)
    sep #$20
    .a8
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_iris_fill_tables — Bresenham circle iris table builder
; =============================================================================
; Builds both WH0 (left) and WH1 (right) HDMA tables using Bresenham's
; midpoint circle algorithm. O(R) precomputation + O(225) table fill.
;
; Expects: HDMA_TBL_PTR (left table), HDMA_TBL_PTR2 (right table),
;          HDMA_IRIS_CX, HDMA_IRIS_CY, HDMA_IRIS_RADIUS set.
; Leaves:  DB=$7E (caller must restore DB=$00)
; =============================================================================

; Scratch addresses for Bresenham iris
IRIS_DX_TABLE   = $05A0     ; 128 bytes: precomputed dx[dy] lookup
IRIS_BRES_ERR   = $0620     ; 2 bytes: Bresenham error term
IRIS_DX_TEMP    = $0622     ; 2 bytes: temp for dx value
IRIS_BRES_DY    = $0624     ; 2 bytes: Bresenham dy iterator

_hdma_iris_fill_tables:
    rep #$30
    .a16
    .i16

    ; Set DB=$7E for WRAM writes (tables + dx lookup are in bank $7E)
    sep #$20
    .a8
    lda #$7E
    pha
    plb                                 ; DB = $7E
    rep #$20
    .a16

    ; === Phase 1: Build dx[] via Bresenham midpoint circle ===
    ; dx[dy] = half-width of circle at vertical distance dy from center.
    ; Bresenham: start at (R, 0), sweep to octant boundary, fill by symmetry.
    ; Total iterations: ~R*0.7 (much less than 225).
    ;
    ; Register usage: X = cur_x, IRIS_BRES_DY = dy_iter (in memory)

    ; Initialize: cur_x = R, dy = 0, err = 1 - R
    ldx HDMA_IRIS_RADIUS                ; X = cur_x = R
    stz IRIS_BRES_DY                    ; dy = 0
    lda #$0001
    sec
    sbc HDMA_IRIS_RADIUS                ; A = 1 - R
    sta IRIS_BRES_ERR

@bres_loop:
    .a16
    ; Store dx[dy] = cur_x
    ldy IRIS_BRES_DY                    ; Y = dy (index)
    txa                                 ; A = cur_x
    sep #$20
    .a8
    sta IRIS_DX_TABLE,y                 ; dx[dy] = cur_x
    rep #$20
    .a16

    ; By symmetry: dx[cur_x] = dy (if cur_x < R, to avoid out-of-bounds)
    cpx HDMA_IRIS_RADIUS
    bcs @bres_skip_sym                  ; skip if cur_x == R
    lda IRIS_BRES_DY                    ; A = dy
    sep #$20
    .a8
    sta IRIS_DX_TABLE,x                 ; dx[cur_x] = dy
    rep #$20
    .a16
@bres_skip_sym:

    ; dy++
    lda IRIS_BRES_DY
    inc
    sta IRIS_BRES_DY                    ; dy_iter++

    ; Check octant boundary: if dy > cur_x → done
    stx IRIS_DX_TEMP                    ; save cur_x to memory
    cmp IRIS_DX_TEMP
    bcs @bres_done                      ; dy >= cur_x → done

    ; Update error: err += 2 * dy + 1  (dy is already incremented)
    asl                                 ; A = 2 * dy
    inc                                 ; A = 2 * dy + 1
    clc
    adc IRIS_BRES_ERR
    sta IRIS_BRES_ERR

    ; If err >= 0: cur_x--, err -= 2 * cur_x
    bmi @bres_loop                      ; err < 0, no x adjustment
    dex                                 ; cur_x--
    txa                                 ; A = cur_x (new)
    asl                                 ; A = 2 * cur_x
    sta IRIS_DX_TEMP
    lda IRIS_BRES_ERR
    sec
    sbc IRIS_DX_TEMP                    ; err -= 2 * cur_x
    sta IRIS_BRES_ERR
    jmp @bres_loop

@bres_done:
    .a16

    ; === Phase 2: Build HDMA tables from dx[] lookup ===
    ; For each scanline s (0..224):
    ;   dy = abs(s - cy)
    ;   if dy >= R: outside → left=1, right=0 (masks all pixels)
    ;   else: dx = dx_table[dy]
    ;     left = clamp(cx - dx, 0, 255)
    ;     right = clamp(cx + dx, 0, 255)

    ldy #$0000                          ; table write offset
    ldx #$0000                          ; scanline counter

@iris_tbl_loop:
    .a16
    ; Compute dy = abs(scanline - cy)
    txa                                 ; A = scanline
    sec
    sbc HDMA_IRIS_CY                    ; A = scanline - cy (signed)
    bpl @iris_dy_pos
    eor #$FFFF
    inc                                 ; A = -A
@iris_dy_pos:
    ; A = abs(dy)
    cmp HDMA_IRIS_RADIUS
    bcc @iris_inside

    ; Outside circle: left=1, right=0 (WH0>WH1 masks all pixels on scanline)
    sep #$20
    .a8
    lda #$01
    sta (HDMA_TBL_PTR),y                ; left: count=1
    sta (HDMA_TBL_PTR2),y               ; right: count=1
    iny
    sta (HDMA_TBL_PTR),y                ; left: WH0=1
    lda #$00
    sta (HDMA_TBL_PTR2),y               ; right: WH1=0
    iny
    rep #$20
    .a16
    jmp @iris_tbl_next

@iris_inside:
    .a16
    ; Look up dx from precomputed Bresenham table
    phx                                 ; save scanline counter
    tax                                 ; X = dy (table index)
    sep #$20
    .a8
    lda IRIS_DX_TABLE,x                 ; A = dx[dy] (byte)
    rep #$20
    .a16
    and #$00FF                          ; zero-extend
    sta IRIS_DX_TEMP                    ; save dx
    plx                                 ; restore scanline counter

    ; left = clamp(cx - dx, 0, 255)
    lda HDMA_IRIS_CX
    sec
    sbc IRIS_DX_TEMP
    bpl @iris_l_pos
    lda #$0000
@iris_l_pos:
    cmp #$0100
    bcc @iris_l_ok
    lda #$00FF
@iris_l_ok:
    pha                                 ; save left

    ; right = clamp(cx + dx, 0, 255)
    lda HDMA_IRIS_CX
    clc
    adc IRIS_DX_TEMP
    cmp #$0100
    bcc @iris_r_ok
    lda #$00FF
@iris_r_ok:
    pha                                 ; save right

    ; Write [1, left] to left table, [1, right] to right table
    sep #$20
    .a8
    lda #$01
    sta (HDMA_TBL_PTR),y                ; count=1
    sta (HDMA_TBL_PTR2),y               ; count=1
    iny
    lda 3,s                             ; left (under right on stack)
    sta (HDMA_TBL_PTR),y                ; WH0 = left
    lda 1,s                             ; right
    sta (HDMA_TBL_PTR2),y               ; WH1 = right
    iny
    rep #$20
    .a16
    pla                                 ; discard right
    pla                                 ; discard left

@iris_tbl_next:
    .a16
    inx
    cpx #HDMA_SCANLINES
    beq @iris_tbl_done
    jmp @iris_tbl_loop

@iris_tbl_done:
    ; Write end markers
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y
    sta (HDMA_TBL_PTR2),y

    ; NOTE: DB is still $7E — caller must restore DB=$00
    rep #$20
    .a16
    rts


; =============================================================================
; hdma_build_scanline_scroll — Build parametric per-scanline scroll table
; =============================================================================
; Similar to hdma_build_wave but with an explicit frequency parameter.
; Builds a per-scanline horizontal scroll offset table using:
;   offset = sin((scanline * freq + phase) & $FF) * amplitude / 128
;
; Input (via scratch WRAM, set by caller):
;   HDMA_WAVE_AMP        (2 bytes): peak amplitude in pixels (0-15)
;   HDMA_SCROLL_LAYER    (2 bytes): BG layer (1, 2, or 3)
;   HDMA_SCROLL_FREQ     (2 bytes): frequency multiplier
;   HDMA_WAVE_PHASE ($0166): current phase (low byte used, 0-255)
;
; Output:
;   Allocates HDMA channel, builds table at HDMA_TABLE_CH3, configures
;   channel for mode $02 to the appropriate BGnHOFS register.
;   Returns: A = channel number (3-7) or $FFFF if allocation failed.
;
; Cross-ref: engine_state.inc, phase_4_effects_audio_gameplay.md
; =============================================================================

; Scratch for scanline_scroll builder. Relocated from $0598-$059D
; (collision-zone overlap with save_load_engine SL_CRC_*) to WRAM-extended
; $7EE0C0-$7EE0C5 — see docs/audit/engine_wram_allocation_audit.md,
; sprint engine-hygiene-1.
;
; SCROLL uses only lda/sta (both have absolute-long opcodes), so each
; access site needs `f:` prefix to force long-form addressing of the
; 24-bit symbol from .a16 mode. The `stz HDMA_SCROLL_CHAN` site in
; hdma_off is rewritten as `lda #0` + `sta f:HDMA_SCROLL_CHAN` because
; long-form stz does not exist. Per-call cost: ~6 reads × 3 extra cycles
; = ≤18 cycles per scanline_scroll invocation. Negligible.
HDMA_SCROLL_FREQ    = $7EE0C0      ; 2 bytes: frequency parameter
HDMA_SCROLL_LAYER   = $7EE0C2      ; 2 bytes: target layer
HDMA_SCROLL_CHAN    = $7EE0C4      ; 2 bytes: allocated channel number

hdma_build_scanline_scroll:
    .a16
    .i16
    ; Allocate a channel
    jsr hdma_alloc
    cmp #$FFFF
    bne @ss_alloc_ok
    rts                             ; allocation failed, return $FFFF
@ss_alloc_ok:
    .a16

    ; HDMA_SCROLL_* relocated to $7EE0C0+ (CP4 hygiene-1); ca65 needs `f:`
    ; to force long-form addressing for these 24-bit symbols.
    sta f:HDMA_SCROLL_CHAN
    pha

    ; Look up correct table address for allocated channel
    lda f:HDMA_SCROLL_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR                ; store in DP pointer for (dp),y addressing

    ; Determine BBAD register based on layer
    ; Layer 1 → $0D (BG1HOFS), 2 → $0F (BG2HOFS), 3 → $11 (BG3HOFS)
    lda f:HDMA_SCROLL_LAYER
    dec                             ; 0-based: 0, 1, 2
    asl                             ; *2: 0, 2, 4
    clc
    adc #BG1HOFS_REG                ; $0D, $0F, $11
    pha                             ; save BBAD on stack

    ; Configure channel state
    ; Stack: [BBAD, channel_num]
    lda 3,s                         ; channel number (under BBAD on stack)
    tax                             ; X = channel number

    ; Phase 17-13: program hardware HDMA registers ($43n0+) directly.
    ; ch_num * 16 → $43n0 base. See _hdma_configure_channel_gradient
    ; for the architectural rationale.
    txa
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base for this channel

    sep #$20
    .a8

    ; DMAP: mode $02 (write twice to same register)
    lda #$02
    sta f:$004300, x                ; DMAPn

    ; BBAD: target register from stack
    lda 1,s                         ; low byte of BBAD value on stack
    sta f:$004301, x                ; BBADn

    ; Table address (low + high) + bank ($7E for WRAM tables)
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn

    rep #$20
    .a16

    ; Remove BBAD from stack (channel num still there)
    pla                             ; discard BBAD
    ; Stack: [channel_num]

    ; Build the table via shared subroutine
    jsr _hdma_ss_fill_table

    ; Enable channel in HDMA mask
    pla                             ; A = channel number (from initial pha)
    pha
    jsr _hdma_enable_channel

    ; Return channel number
    pla
    rts


; =============================================================================
; hdma_update_scanline_scroll — Per-frame table rebuild (no channel allocation)
; =============================================================================
; Call this once per frame to advance the wave phase and rebuild the HDMA
; scanline scroll table in-place.  Expects that hdma_build_scanline_scroll
; was called at least once to allocate a channel and set the parameters.
;
; Reads:  HDMA_SCROLL_CHAN, HDMA_WAVE_PHASE, HDMA_WAVE_SPEED,
;         HDMA_WAVE_AMP, HDMA_SCROLL_FREQ
; Writes: HDMA_WAVE_PHASE (incremented), HDMA table data
; =============================================================================
hdma_update_scanline_scroll:
    rep #$30
    .a16
    .i16
    ; Check if scanline_scroll is active (channel allocated). HDMA_SCROLL_*
    ; relocated to $7EE0C0+; force long-form addressing with `f:`.
    lda f:HDMA_SCROLL_CHAN
    beq @no_ss_update               ; no channel, skip

    ; Advance phase: HDMA_WAVE_PHASE += HDMA_WAVE_SPEED
    lda HDMA_WAVE_PHASE
    clc
    adc HDMA_WAVE_SPEED
    sta HDMA_WAVE_PHASE

    ; Look up table address for the allocated channel
    lda f:HDMA_SCROLL_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR

    ; Rebuild the table
    jsr _hdma_ss_fill_table
    rts

@no_ss_update:
    rts


; =============================================================================
; _hdma_ss_fill_table — Shared table build subroutine for scanline_scroll
; =============================================================================
; Expects: HDMA_TBL_PTR set, HDMA_WAVE_AMP/HDMA_SCROLL_FREQ/HDMA_WAVE_PHASE valid
; Returns: A16, I16, DB=$00
; =============================================================================
_hdma_ss_fill_table:
    rep #$30
    .a16
    .i16

    ; Build the table: 225 entries, each [1, scroll_lo, scroll_hi]
    ; Y = table write offset, X = scanline counter
    ldy #$0000                      ; table write offset
    ldx #$0000                      ; scanline counter

    ; Set DB=$7E for WRAM writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

@ss_loop:
    .a16
    ; Compute index = (scanline * freq + phase) & $FF
    ; X = scanline counter (16-bit)
    txa                             ; A = scanline
    ; Multiply scanline * freq (8-bit * 8-bit via HW multiplier)
    ; We need the low byte of scanline * freq, so use HW multiplier
    sep #$20
    .a8
    sta f:$004202                   ; WRMPYA = scanline (low byte)
    lda f:HDMA_SCROLL_FREQ          ; freq (low byte) — long-form, $7EE0C0
    sta f:$004203                   ; WRMPYB = freq
    nop                             ; wait 8 cycles
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:$004216                   ; A = scanline * freq (16-bit)
    clc
    adc HDMA_WAVE_PHASE             ; A = scanline * freq + phase
    and #$00FF                      ; mask to 8 bits
    ; A = index (0-255)

    ; --- Quarter-wave sine lookup ---
    ; Determine quadrant and compute sine value
    pha                             ; save index
    and #$00C0                      ; isolate quadrant bits (bits 7-6)
    beq @ss_q0
    cmp #$0040
    beq @ss_q1
    cmp #$0080
    beq @ss_q2
    ; Fall through to Q3

@ss_q3:
    .a16
    ; Q3 (index 192-255): sin = -table[255-index]
    sep #$20
    .a8
    lda #$01
    sta HDMA_WAVE_SIGN
    rep #$20
    .a16
    pla                             ; A = index
    eor #$00FF                      ; 255 - index
    and #$003F
    bra @ss_lookup

@ss_q0:
    .a16
    ; Q0 (index 0-63): sin = +table[index]
    sep #$20
    .a8
    stz HDMA_WAVE_SIGN              ; positive
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F
    bra @ss_lookup

@ss_q1:
    .a16
    ; Q1 (index 64-127): sin = +table[63-(index&63)]
    sep #$20
    .a8
    stz HDMA_WAVE_SIGN              ; positive
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F                      ; index & 63
    eor #$003F                      ; 63 - (index & 63)
    bra @ss_lookup

@ss_q2:
    .a16
    ; Q2 (index 128-191): sin = -table[index & 63]
    sep #$20
    .a8
    lda #$01
    sta HDMA_WAVE_SIGN              ; negative
    rep #$20
    .a16
    pla                             ; A = index
    and #$003F
    ; fall through to @ss_lookup

@ss_lookup:
    .a16
    ; A = table index (0-63), look up quarter-wave sine value
    ; Save X (scanline counter) and Y (table offset)
    phx
    phy
    tax                             ; X = table index
    sep #$20
    .a8
    lda f:_hdma_sine_quarter,x      ; A = sine value (0-127, unsigned)

    ; --- Multiply sin_val * amplitude using hardware multiplier ---
    sta f:$004202                   ; WRMPYA = abs(sin_val)
    lda HDMA_WAVE_AMP               ; amplitude (low byte, 0-15)
    sta f:$004203                   ; WRMPYB = amplitude
    nop                             ; 2 cycles
    nop                             ; 2 cycles
    nop                             ; 2 cycles
    nop                             ; 2 cycles (total: 8)

    ; Read 16-bit result from RDMPYL/H ($4216-$4217)
    rep #$20
    .a16
    lda f:$004216                   ; A = sin_val * amplitude (16-bit)

    ; Divide by 128: A = (A >> 7) = (A << 1) >> 8
    asl                             ; shift left 1
    xba                             ; swap bytes
    and #$00FF                      ; mask to byte → A = result / 128

    ; Apply sign
    ply                             ; restore Y (table offset)
    plx                             ; restore X (scanline counter)

    ; A = unsigned offset
    sep #$20
    .a8

    ; Check sign
    pha                             ; save unsigned offset
    lda HDMA_WAVE_SIGN
    beq @ss_positive
    .a8
    ; Negative: two's complement
    pla                             ; A = unsigned offset
    eor #$FF
    inc                             ; A = -offset (8-bit two's complement)
    ; Write [1, offset_lo, $FF] to table
    pha                             ; save signed lo
    lda #$01
    sta (HDMA_TBL_PTR),y            ; scanline count = 1
    iny
    pla                             ; A = signed offset lo
    sta (HDMA_TBL_PTR),y            ; scroll_lo
    iny
    lda #$FF                        ; sign extension for negative
    sta (HDMA_TBL_PTR),y            ; scroll_hi
    iny
    bra @ss_next

@ss_positive:
    .a8
    pla                             ; A = unsigned offset
    ; Write [1, offset_lo, $00] to table
    pha                             ; save offset
    lda #$01
    sta (HDMA_TBL_PTR),y            ; scanline count = 1
    iny
    pla                             ; A = offset
    sta (HDMA_TBL_PTR),y            ; scroll_lo
    iny
    lda #$00                        ; sign extension for positive
    sta (HDMA_TBL_PTR),y            ; scroll_hi
    iny

@ss_next:
    .a8
    ; Restore 16-bit A for loop control
    rep #$20
    .a16
    ; Next scanline
    inx
    cpx #HDMA_SCANLINES
    beq @ss_loop_done
    jmp @ss_loop
@ss_loop_done:

    ; Write end-of-table marker ($00)
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR),y

    ; Restore DB=$00
    lda #$00
    pha
    plb
    rep #$20
    .a16

    rts


; =============================================================================
; hdma_build_hofs_curve — curve-LUT-driven per-scanline BGnHOFS distortion
; =============================================================================
; The general per-scanline horizontal-offset builder behind sf_bend / sf_tunnel
; (kit brick #1). A near-clone of hdma_build_scanline_scroll, but the inner
; loop reads each scanline's base offset from a SELECTABLE signed-byte curve LUT
; (sine or parabola) instead of the hardcoded quarter-wave sine quadrant code.
; Everything else — hdma_alloc, _hdma_table_addrs lookup, $43n0 programming with
; DMAP=$02 → BGnHOFS, the write-twice [1, lo, hi] entries, the end marker, and
; _hdma_enable_channel — is the proven scanline_scroll machinery, reused.
;
;   offset(scanline) = curve_lut[(scanline + phase) & $FF] * amplitude / 128
;
; A periodic curve (SINE) rolls under an animated phase → the marquee tunnel.
; A static-horizon curve (PARABOLA) is indexed scanline→offset at phase 0 →
; a curved horizon symmetric about screen centre (scanline 112).
;
; Input (via WRAM cold state, set by the sf_bend / sf_tunnel macros):
;   HDMA_BEND_CURVE  ($7EE0B0, 2): 0 = SINE, 1 = PARABOLA
;   HDMA_BEND_AMP    ($7EE0B2, 2): amplitude scale (0-15 px of peak displacement)
;   HDMA_BEND_LAYER  ($7EE0B4, 2): target BG layer (1, 2, or 3)
;   HDMA_WAVE_PHASE  ($0166, DP $66): current phase (low byte used, 0-255)
;
; Output:
;   Allocates an HDMA channel, records it in HDMA_BEND_CHAN, builds the table,
;   programs the channel for mode $02 → BGnHOFS. Returns A = channel (3-7) or
;   $FFFF if allocation failed.
; =============================================================================
hdma_build_hofs_curve:
    .a16
    .i16
    ; Allocate a channel
    jsr hdma_alloc
    cmp #$FFFF
    bne @bc_alloc_ok
    rts                             ; allocation failed, return $FFFF
@bc_alloc_ok:
    .a16
    ; HDMA_BEND_* are 24-bit ($7EE0B0+) — force long-form addressing with `f:`.
    sta f:HDMA_BEND_CHAN
    pha

    ; Look up correct table address for allocated channel
    lda f:HDMA_BEND_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR                ; store in DP pointer for (dp),y addressing

    ; Determine BBAD register based on layer AND axis (v1.2).
    ;   H axis (HDMA_BEND_AXIS=0): BG{layer}HOFS → 1→$0D, 2→$0F, 3→$11
    ;   V axis (HDMA_BEND_AXIS=1): BG{layer}VOFS → 1→$0E, 2→$10, 3→$12
    ; The V register is always H+1, so adding the axis flag (0/1) to the H base
    ; selects the axis. This is the ONLY per-axis difference — the table format
    ; and every other routine (precompute, refill, pointer-slide) are identical.
    lda f:HDMA_BEND_LAYER
    dec                             ; 0-based: 0, 1, 2
    asl                             ; *2: 0, 2, 4
    clc
    adc #BG1HOFS_REG                ; $0D, $0F, $11 (H base for the layer)
    clc
    adc f:HDMA_BEND_AXIS            ; + axis (0=H/BGnHOFS, 1=V/BGnVOFS = H+1)
    pha                             ; save BBAD on stack

    ; Stack: [BBAD, channel_num]
    lda 3,s                         ; channel number (under BBAD on stack)
    tax                             ; X = channel number

    ; ch_num * 16 → $43n0 base for this channel
    txa
    asl
    asl
    asl
    asl                             ; A = ch_num * 16
    tax                             ; X = $43n0 base

    sep #$20
    .a8

    ; DMAP: mode $02 (write twice to same register)
    lda #$02
    sta f:$004300, x                ; DMAPn

    ; BBAD: target register from stack
    lda 1,s                         ; low byte of BBAD value on stack
    sta f:$004301, x                ; BBADn

    ; Table address (low + high) + bank ($7E for WRAM tables)
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    lda #$7E
    sta f:$004304, x                ; A1Bn

    rep #$20
    .a16

    ; Remove BBAD from stack (channel num still there)
    pla                             ; discard BBAD

    ; Precompute the amplitude-scaled curve ONCE (amp + curve are fixed for the
    ; life of this arm). The per-frame rebuild then only re-indexes it by phase
    ; — no per-scanline multiply. (The cold-start's recommended LUT-with-phase
    ; shape: build the table once, animate via a phase offset into the LUT.)
    jsr _hdma_curve_precompute

    ; Lay the invariant table skeleton ONCE (count bytes + end marker). The
    ; per-frame refill then only rewrites each entry's offset word (E-PERF).
    jsr _hdma_curve_build_skeleton

    ; Bake the oversized roll table ONCE (E-SLIDE) so the pure-roll tick can
    ; phase by sliding A1Tn into it — near-zero per-frame cost.
    jsr _hdma_curve_build_baked

    ; Build the channel's live table via the shared curve fill subroutine
    jsr _hdma_curve_fill_table

    ; Enable channel in HDMA mask
    pla                             ; A = channel number (from initial pha)
    pha
    jsr _hdma_enable_channel

    ; Return channel number
    pla
    rts


; =============================================================================
; hdma_update_hofs_curve — Per-frame phase advance + path-selected roll update
; =============================================================================
; Call once per frame (the sf_bend_tick service) to roll the curve phase. Two
; paths, chosen each frame (v1.1 E-SLIDE):
;
;   PURE-ROLL POINTER-SLIDE (base scroll == 0): advance ONLY the channel's HDMA
;     source pointer (A1Tn = $43n2/3) into the oversized baked table
;     (HDMA_BEND_BAKED) by phase*3 bytes — NO table writes, near-zero cost.
;     Reverses naturally under a negative speed (phase wraps the other way).
;   OPTIMIZED REFILL (base scroll != 0): the S1/S3 path — rebuild the channel's
;     own table composing base_scroll + curve per line, and point A1Tn back at
;     the channel slot. A baked table can't add a per-frame-changing base to
;     every line, so hscroll forces the refill (the two are mutually exclusive
;     per frame, which is fine).
;
; Expects hdma_build_hofs_curve has run (a channel is allocated + the baked
; table is laid). No-op when no channel is active (HDMA_BEND_CHAN = 0) — safe to
; leave in the loop permanently; safe when speed = 0 (phase advance is a no-op).
;
; Reads:  HDMA_BEND_CHAN, HDMA_WAVE_PHASE, HDMA_WAVE_SPEED, HDMA_BEND_AMP,
;         HDMA_BEND_CURVE, HDMA_BEND_LAYER, SHADOW_BG{layer}HOFS
; Writes: HDMA_WAVE_PHASE (incremented), and either A1Tn (slide) or the table
;         data + A1Tn (refill).
; WIDTH-RISK: entry/exit A16/I16; the A1Tn writes toggle A8 internally and
; re-enter A16 before any shared branch target.
; =============================================================================
hdma_update_hofs_curve:
    rep #$30
    .a16
    .i16
    ; Active? (channel allocated). 24-bit symbol → `f:`.
    lda f:HDMA_BEND_CHAN
    bne @bc_upd_active
    rts                             ; no channel, skip
@bc_upd_active:
    .a16
    ; Advance phase: HDMA_WAVE_PHASE += HDMA_WAVE_SPEED
    lda HDMA_WAVE_PHASE
    clc
    adc HDMA_WAVE_SPEED
    sta HDMA_WAVE_PHASE

    ; --- Path select: pure-roll pointer-slide iff base scroll == 0 ----------
    ; base_scroll = SHADOW_BG{layer}{H|V}OFS for the armed axis. The shadow page
    ; interleaves HOFS @ ($20 + (layer-1)*4) = $1C + layer*4 and VOFS @ ($22 +
    ; (layer-1)*4) = $1E + layer*4 — the V slot is exactly +2 from the H slot,
    ; the same +2 as a word stride, so adding axis*2 selects HOFS (H) / VOFS (V).
    ; Zero → no pan composed → the baked table is valid → near-zero-cost slide.
    ; Nonzero → fall to the refill (which adds the per-line base).
    lda f:HDMA_BEND_LAYER
    asl
    asl
    clc
    adc #$001C
    clc
    adc #ENGINE_STATE_BASE
    ; + axis*2 (H slot vs V slot, +2 apart). WIDTH-RISK: A16 — HDMA_BEND_AXIS is
    ; 0/1; asl makes 0/2; the add stays in the low byte. X is I16 below.
    sta HDMA_TBL_PTR                ; scratch the H-slot address
    lda f:HDMA_BEND_AXIS
    asl                            ; axis*2 (0 → HOFS slot, 2 → VOFS slot)
    clc
    adc HDMA_TBL_PTR
    tax
    lda $0000,x                     ; A = base scroll for the armed axis
    bne @bc_refill                  ; pan active → optimized refill path
    jmp _hdma_curve_pointer_slide   ; pure roll → pointer-slide (tail call)

@bc_refill:
    .a16
    ; Look up table address for the allocated channel
    lda f:HDMA_BEND_CHAN
    sec
    sbc #3
    asl                             ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x       ; A = table base address (16-bit)
    sta HDMA_TBL_PTR

    ; Re-point A1Tn at the channel's OWN slot (the previous frame may have left
    ; it pointing into the baked table from a slide).
    jsr _hdma_curve_point_a1t       ; A1Tn = HDMA_TBL_PTR (channel slot)

    ; Rebuild the table (composes base_scroll + curve per line)
    jsr _hdma_curve_fill_table
    rts


; =============================================================================
; _hdma_curve_pointer_slide — E-SLIDE pure-roll fast-path (near-zero cost)
; =============================================================================
; Point the channel's HDMA source pointer A1Tn ($43n2/3) at the baked oversized
; table offset by phase: A1Tn = HDMA_BEND_BAKED + (phase & $FF) * 3. The next
; frame's HDMA reloads A1Tn and walks 224 entries from there, so scanline s
; reads baked[phase+s] = curve[(phase+s) & $FF] — the roll, with NO table
; writes. A negative speed wraps phase downward, reversing the slide.
; Entry: HDMA_BEND_CHAN valid, HDMA_WAVE_PHASE already advanced; A16/I16, DB=$00.
; This is the tail of hdma_update_hofs_curve (entered via JMP) — ends with RTS.
; WIDTH-RISK: A16 for the address math; A8 only for the two $43n2/3 byte stores;
; no shared branch targets. Returns to the tick's caller via RTS.
; =============================================================================
_hdma_curve_pointer_slide:
    .a16
    .i16
    ; src16 = HDMA_BEND_BAKED_LO + (phase & $FF) * 3
    lda HDMA_WAVE_PHASE
    and #$00FF                      ; phase index 0..255
    ; *3 = *2 + *1
    sta HDMA_TBL_PTR                ; scratch: phase
    asl                             ; phase*2
    clc
    adc HDMA_TBL_PTR               ; + phase = phase*3
    clc
    adc #(HDMA_BEND_BAKED & $FFFF)  ; + baked table base (16-bit)
    sta HDMA_TBL_PTR               ; src16 (low 16 of the new A1Tn)

    ; channel $43n0 base = chan * 16 → X
    lda f:HDMA_BEND_CHAN
    asl
    asl
    asl
    asl                             ; chan * 16
    tax                             ; X = $43n0 base offset

    sep #$20
    .a8
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    ; A1Bn ($43n4) stays $7E from arm time — both tables live in bank $7E.
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_curve_point_a1t — set A1Tn ($43n2/3) = HDMA_TBL_PTR for the channel
; =============================================================================
; The refill path must re-point A1Tn at the channel's OWN slot (a prior frame's
; slide may have left it in the baked table). Entry: HDMA_BEND_CHAN valid,
; HDMA_TBL_PTR = channel slot base; A16/I16, DB=$00. Leaves A16/I16.
; WIDTH-RISK: A8 only for the two byte stores; no shared branch targets.
; =============================================================================
_hdma_curve_point_a1t:
    .a16
    .i16
    lda f:HDMA_BEND_CHAN
    asl
    asl
    asl
    asl                             ; chan * 16
    tax
    sep #$20
    .a8
    lda HDMA_TBL_PTR
    sta f:$004302, x                ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                ; A1TnH
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_curve_build_baked — bake the oversized roll table ONCE (per arm)
; =============================================================================
; Fills HDMA_BEND_BAKED with 481 mode-$02 entries [1, off_lo, off_hi] where
; off = scaled_curve[j & $FF] (the same signed-word LUT the refill reads), for
; j = 0..480 (screen height 225 + one full period 256). The pointer-slide tick
; then phases the roll by sliding A1Tn into this table. Count bytes are all $01
; (never $00) so HDMA finds no early terminator inside the slideable window; a
; single $00 marker caps the table past entry 480.
; Expects: the signed-word scaled LUT already built (_hdma_curve_precompute);
;          A16/I16, DB=$00. Leaves DB=$00.
; WIDTH-RISK: A16 for the LUT read + address math; A8 for the three byte stores;
; @bk_loop is reached from the rep below and the jmp at the tail, both A16/I16.
; =============================================================================
BEND_BAKED_ENTRIES = 481            ; 225 visible + 256 full period

_hdma_curve_build_baked:
    rep #$30
    .a16
    .i16
    ; baked-table base ($7E:E400) → HDMA_TBL_PTR2 (DP indirect; DB=$7E gives the
    ; bank). Free here — precompute (its only other user) has already finished.
    lda #(HDMA_BEND_BAKED & $FFFF)
    sta HDMA_TBL_PTR2

    ldx #$0000                      ; X = scaled-LUT byte offset ((j&$FF)*2)
    ldy #$0000                      ; Y = baked-table byte write offset (3*j)
    stz HDMA_TBL_PTR                ; HDMA_TBL_PTR = entry counter j (scratch)

    ; DB=$7E for the baked-table writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

@bk_loop:
    .a16
    .i16
    ; write the count byte [1] at offset 3*j (A8), then the offset WORD at +1
    ; (A16, single store covering off_lo @ +1 and off_hi @ +2).
    sep #$20
    .a8
    lda #$01
    sta (HDMA_TBL_PTR2),y            ; [count] = 1
    rep #$20
    .a16
    iny                              ; → offset-word slot (+1)
    lda f:HDMA_BEND_SCALED_W,x        ; signed 16-bit scaled value
    sta (HDMA_TBL_PTR2),y            ; off_lo @ +1, off_hi @ +2 (single store)
    iny
    iny                              ; → next entry (+3 total)

    ; advance scaled-LUT index (j+1)&$FF → byte offset, wrapping at 512
    inx
    inx
    cpx #512
    bne @bk_no_wrap
    ldx #$0000
@bk_no_wrap:
    .a16
    .i16
    ; advance + test the entry counter j
    lda HDMA_TBL_PTR
    inc a
    sta HDMA_TBL_PTR
    cmp #BEND_BAKED_ENTRIES
    beq @bk_done
    jmp @bk_loop
@bk_done:
    ; end marker ($00) just past the last entry (Y = 3*481)
    sep #$20
    .a8
    lda #$00
    sta (HDMA_TBL_PTR2),y
    ; restore DB=$00
    pha
    plb
    rep #$20
    .a16
    rts


; Legacy: the scaled-curve scratch USED to live in the channel's own 1 KB HDMA
; table slot as 256 signed BYTES at +768 (BEND_SCALED_OFF). The v1.1 E-PERF
; pass replaced that with 256 signed 16-bit WORDS in a dedicated WRAM region
; (HDMA_BEND_SCALED_W = $7E:E200, engine_state.inc), so the per-frame refill is
; one 16-bit store per line with no sep/rep toggle and no sign-extension branch.
; A 16-bit LUT is 512 B and would not fit after a 676-byte live table inside the
; 1 KB slot — hence the relocation. BEND_SCALED_OFF is retired.

; =============================================================================
; _hdma_curve_precompute — fill the amplitude-scaled signed-WORD curve (once)
; =============================================================================
; Computes scaled[i] = curve_lut[i] * amplitude / 128 for i = 0..255, as a
; SIGNED 16-bit WORD (already sign-extended: +0..+15 or $FFF1..$FFFF for amp
; 0-15), into HDMA_BEND_SCALED_W ($7E:E200, 512 B). This is where the per-curve
; HW multiply + sign work happens — ONCE per arm, not per scanline per frame.
; The per-frame rebuild (_hdma_curve_fill_table) then re-indexes this word LUT
; by phase as a single 16-bit load+store per line — no multiply, no sep/rep, no
; sign-extension branch. Selects sine vs parabola from HDMA_BEND_CURVE.
; Expects: A16/I16, DB=$00. Returns A16, I16, DB=$00. (No longer needs
; HDMA_TBL_PTR — the scaled LUT has a fixed WRAM home.)
; WIDTH-RISK: toggles A8 around the HW multiply; @pc_loop is reached from the
; rep below and the jmp at the tail, both A16/I16. The store is A16 (word).
; =============================================================================
_hdma_curve_precompute:
    rep #$30
    .a16
    .i16
    ; scaled word-LUT base ($7E:E200) → HDMA_TBL_PTR2 (16-bit offset; DB=$7E
    ; supplies the bank for the (dp),y store below).
    lda #(HDMA_BEND_SCALED_W & $FFFF)
    sta HDMA_TBL_PTR2

    ldx #$0000                      ; X = curve index 0..255
    ldy #$0000                      ; Y = word byte offset (X*2), tracked in step
    ; DB=$7E for the WRAM scaled-table writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$20
    .a16

@pc_loop:
    .a16
    ; read curve_lut[X] (signed byte) — select sine / parabola / horizon (v1.2).
    ; (ldy has no abs-long form for the 24-bit HDMA_BEND_CURVE symbol; lda does —
    ; read the curve-id byte into A and dispatch on it: 0=sine, 1=parabola,
    ; 2=horizon.)
    sep #$20
    .a8
    lda f:HDMA_BEND_CURVE           ; 0 = sine, 1 = parabola, 2 = horizon
    beq @pc_sine
    cmp #$02
    beq @pc_horizon
    lda f:_hdma_curve_parabola,x
    bra @pc_have
@pc_horizon:
    .a8
    lda f:_hdma_curve_horizon,x     ; v1.2 monotonic horizon-compression ramp
    bra @pc_have
@pc_sine:
    .a8
    lda f:_hdma_curve_sine,x
@pc_have:
    .a8
    ; |base| + sign (HDMA_WAVE_SIGN: 0 = positive, 1 = negative) — a scratch
    ; byte, not the P register, so the multiply's width toggles can't corrupt it.
    bpl @pc_pos
    eor #$FF
    inc                             ; A = |base|
    pha
    lda #$01
    sta HDMA_WAVE_SIGN
    pla
    bra @pc_mul
@pc_pos:
    .a8
    stz HDMA_WAVE_SIGN              ; positive
@pc_mul:
    .a8
    sta f:$004202                   ; WRMPYA = |base|
    lda f:HDMA_BEND_AMP             ; amplitude (0-15)
    sta f:$004203                   ; WRMPYB = amplitude
    nop                             ; 8-cycle wait
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:$004216                   ; |base| * amplitude (16-bit)
    asl
    xba
    and #$00FF                      ; A = magnitude / 128 (0..15), high byte 0
    ; apply sign (HDMA_WAVE_SIGN flag byte) to a 16-bit two's-complement word —
    ; the per-frame loop then stores it verbatim (already sign-extended).
    ; WIDTH-RISK: HDMA_WAVE_SIGN is a 1-byte flag; read it A16 and mask. A holds
    ; the magnitude (high byte 0) on entry to this block.
    pha                             ; save magnitude (A16: 2 bytes)
    lda HDMA_WAVE_SIGN
    and #$00FF
    beq @pc_pos_store               ; positive → store magnitude as-is
    pla                             ; magnitude
    eor #$FFFF
    inc a                           ; negative → 16-bit two's-complement word
    bra @pc_store
@pc_pos_store:
    .a16
    pla                             ; magnitude (positive, high byte 0)
@pc_store:
    .a16
    ; A = signed 16-bit scaled value; Y = word byte offset (X*2, tracked in
    ; step). Store the word at scaled_w[X], then advance both counters.
    sta (HDMA_TBL_PTR2),y           ; scaled_w[X] = signed 16-bit word
    iny
    iny                             ; Y += 2 (next word slot)
    inx
    cpx #256
    beq @pc_done
    jmp @pc_loop
@pc_done:
    ; restore DB=$00
    sep #$20
    .a8
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; Per-entry table stride (mode-$02 write-twice: [count, off_lo, off_hi]).
BEND_ENTRY_STRIDE = 3
; Byte offset of the END marker = 3 * HDMA_SCANLINES (just past entry 224).
BEND_TABLE_END    = BEND_ENTRY_STRIDE * HDMA_SCANLINES

; =============================================================================
; _hdma_curve_build_skeleton — write the invariant table bytes ONCE (per arm)
; =============================================================================
; v1.1 E-PERF: the count byte [1] of every mode-$02 entry NEVER changes
; frame-to-frame, and neither does the $00 end marker. Write them once at arm
; time; the per-frame refill (_hdma_curve_fill_table) then only rewrites the
; offset WORD of each entry — a single 16-bit store per line, no count byte.
; Expects: HDMA_TBL_PTR = channel table base; A16/I16, DB=$00. Leaves DB=$00.
; WIDTH-RISK: toggles A8 for the byte stores; @cs_loop is a single-path label
; reached only via the fall-through and the bne below (both A8/I16).
; =============================================================================
_hdma_curve_build_skeleton:
    rep #$30
    .a16
    .i16
    ldy #$0000                      ; Y = entry offset 0, 3, 6, ...
    ; DB=$7E for WRAM table writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    lda #$01                        ; the constant line-count byte
@cs_loop:
    .a8
    sta (HDMA_TBL_PTR),y            ; [count] = 1 at offset 3*i
    iny
    iny
    iny                             ; next entry (+3); off_lo/off_hi left as-is
    cpy #BEND_TABLE_END
    bne @cs_loop
    ; End-of-table marker ($00) at offset BEND_TABLE_END
    lda #$00
    sta (HDMA_TBL_PTR),y
    ; restore DB=$00
    pha
    plb
    rep #$20
    .a16
    rts


; =============================================================================
; _hdma_curve_fill_table — per-scanline BGnHOFS table build from the scaled LUT
; =============================================================================
; v1.1 E-PERF hot loop. The count bytes + end marker were written ONCE by
; _hdma_curve_build_skeleton; this routine rewrites ONLY the offset WORD of each
; mode-$02 entry — one 16-bit store per line, no sep/rep toggle in the loop, no
; per-line sign-extension branch (the scaled LUT is already signed 16-bit).
;
; Expects: HDMA_TBL_PTR = channel table base; the signed-word scaled curve built
;          by _hdma_curve_precompute (HDMA_BEND_SCALED_W = $7E:E200); skeleton
;          already laid; HDMA_WAVE_PHASE valid; A16/I16, DB=$00. Leaves DB=$00.
;
; Per scanline i: idx = (i + phase) & $FF; word = scaled_w[idx] + base_scroll;
; store word at entry offset 3*i+1 (covers off_lo @ +1 and off_hi @ +2 in a
; single 16-bit store, leaving the count byte @ +0 and the next count @ +3
; untouched). E-HSCROLL: base_scroll = SHADOW_BG{layer}HOFS, read once before
; the loop, so `scroll #layer,...` pans the bent layer while the curve rides on
; top.
;
; Register contract in the hot loop (NO per-iteration push/pull):
;   X = scaled-LUT byte offset (idx*2), wraps at 512 (256 words)
;   Y = table write offset, starts at 1, +3 each line, ends at BEND_TABLE_END+1
;   HDMA_BEND_BASE (DP word) = base_scroll addend
; WIDTH-RISK: A16/I16 throughout the loop (single width — the whole point).
; @cf_loop and @cf_wrap are reached from multiple A16/I16 paths; annotated.
; =============================================================================
_hdma_curve_fill_table:
    rep #$30
    .a16
    .i16

    ; --- E-HSCROLL / V-SCROLL: base_scroll = SHADOW_BG{layer}{H|V}OFS (once) --
    ; H axis: ES_SHADOW_BG1HOFS ($20) + (layer-1)*4 = $1C + layer*4.
    ; V axis: ES_SHADOW_BG1VOFS ($22) + (layer-1)*4 = $1E + layer*4 = the H slot
    ; +2 (the shadow page interleaves H,V per layer 2 bytes apart). Adding axis*2
    ; to the H slot picks the right axis, so the normal `scroll` macro pans the
    ; bent layer along its armed axis. Same feed sf_parallax_bands uses. Stored
    ; in HDMA_BEND_BASE (DP) so the inner loop adds it with one adc.
    lda f:HDMA_BEND_LAYER
    asl
    asl                             ; layer * 4
    clc
    adc #$001C                      ; $1C + layer*4 (H slot)
    clc
    adc #ENGINE_STATE_BASE          ; engine-state page base
    ; + axis*2 → V slot when axis=1. WIDTH-RISK: A16; axis is 0/1, asl→0/2; the
    ; add stays in the low byte. X is I16 for the load below.
    sta HDMA_BEND_BASE              ; scratch the H-slot address (reused below)
    lda f:HDMA_BEND_AXIS
    asl                            ; axis*2 (0 → HOFS, 2 → VOFS)
    clc
    adc HDMA_BEND_BASE
    tax
    lda $0000,x                     ; A = base scroll (SHADOW_BG{layer}{H|V}OFS)
    ; HDMA_BEND_BASE aliases HDMA_TBL_PTR2 ($B2) — a DP engine-cache scratch,
    ; free in this routine (the scaled LUT now has a fixed absolute home, so
    ; fill_table no longer needs the secondary table pointer). DP is bank-
    ; independent, so the inner-loop `adc` works regardless of DB.
    sta HDMA_BEND_BASE

    ; --- X = initial scaled-LUT byte offset = (phase & $FF) * 2 --------------
    lda HDMA_WAVE_PHASE
    and #$00FF
    asl                             ; *2 (word stride)
    tax                             ; X = idx*2 (0..510)

    ; Y = first offset-word slot (entry 0, byte +1)
    ldy #$0001

    ; Set DB=$7E for WRAM table writes
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E
    rep #$20
    .a16

@cf_loop:
    .a16
    .i16
    ; word = scaled_w[idx] + base_scroll ; one 16-bit load + add + store
    lda f:HDMA_BEND_SCALED_W,x       ; signed 16-bit scaled value
    clc
    adc HDMA_BEND_BASE               ; + base horizontal scroll
    sta (HDMA_TBL_PTR),y             ; off_lo @ +1, off_hi @ +2 (single store)

    ; advance scaled-LUT index (idx*2), wrap at 512 (256 words)
    inx
    inx
    cpx #512
    bne @cf_no_wrap
    ldx #$0000
@cf_no_wrap:
    .a16
    .i16
    ; advance table write offset to the next entry's word (+3)
    iny
    iny
    iny
    cpy #(BEND_TABLE_END + 1)        ; past entry 224's word → done
    bne @cf_loop

    ; Restore DB=$00
    sep #$20
    .a8
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; =============================================================================
; Curve LUTs for hdma_build_hofs_curve (signed bytes, -127..+127)
; =============================================================================
; _hdma_curve_sine + _hdma_curve_parabola live in a GENERATED include — the
; bytes are frozen from toolchain/math_lut.py (the kit's numeric LUT SoT) via
;   PYTHONPATH=. python3 tools/gen_bend_luts.py
; sine is DERIVED from the existing kit 8.8 sine (generate_sin_lut) — not a
; new sine; parabola is generate_bend_parabola_lut. Same generated-.inc
; discipline as engine/gradient_ease_lut.inc.
; =============================================================================
.include "hdma_bend_luts.inc"


; =============================================================================
; Quarter-wave sine lookup table (64 entries)
; =============================================================================
; Values represent sin(i * pi/128) * 127 for i = 0..63
; Full sine reconstructed via quadrant mirroring/negation.
; Range: 0 at index 0, 127 at index 63 (sin(90 degrees) * 127)
; =============================================================================
_hdma_sine_quarter:
    .byte   0,   3,   6,   9,  12,  16,  19,  22
    .byte  25,  28,  31,  34,  37,  40,  43,  46
    .byte  49,  51,  54,  57,  60,  63,  65,  68
    .byte  71,  73,  76,  78,  81,  83,  86,  88
    .byte  90,  92,  95,  97,  99, 101, 103, 105
    .byte 107, 108, 110, 112, 113, 115, 117, 118
    .byte 119, 121, 122, 123, 124, 125, 126, 126
    .byte 127, 127, 127, 127, 127, 127, 127, 127


; =============================================================================
; Lookup tables
; =============================================================================
_hdma_table_addrs:
    .word HDMA_TABLE_CH3            ; channel 3
    .word HDMA_TABLE_CH4            ; channel 4
    .word HDMA_TABLE_CH5            ; channel 5
    .word HDMA_TABLE_CH6            ; channel 6
    .word HDMA_TABLE_CH7            ; channel 7

; =============================================================================
; Phase 16-8 step 5 — Parallax bands (stepped HDMA HOFS, 2 bands)
; =============================================================================
; Multi-distance parallax via per-scanline BGnHOFS writes from a single HDMA
; channel. Two bands with independent 8.8-fixed scroll ratios:
;   scanlines 0 .. y_split-1   →  HOFS = world_x * ratio_top  >> 8
;   scanlines y_split .. 224   →  HOFS = world_x * ratio_bot  >> 8
;
; world_x is read at table-build time from SHADOW_BGnHOFS for the target
; layer. Ratios = 0 means HOFS = 0 (used by template for dialog-freeze).
;
; Mirrors the shape of hdma_build_scanline_scroll above; reuses hdma_alloc,
; _hdma_table_addrs, _hdma_enable_channel.
; =============================================================================

; Scratch for parallax_bands (cold state; rebuilt every frame from cached
; ratios). See engine_state.inc allocations table at $7EE0D0+.
PARALLAX_BANDS_LAYER     = $7EE0D0     ; 2 bytes: BG layer (1, 2, or 3)
PARALLAX_BANDS_YSPLIT    = $7EE0D2     ; 2 bytes: transition scanline (0..223)
PARALLAX_BANDS_RATIO_TOP = $7EE0D4     ; 2 bytes: 8.8 ratio for top band
PARALLAX_BANDS_RATIO_BOT = $7EE0D6     ; 2 bytes: 8.8 ratio for bottom band
PARALLAX_BANDS_CHAN      = $7EE0D8     ; 2 bytes: allocated channel (3-7) or 0

; Per-frame transient scratch (not part of the published 10-byte allocation;
; recomputed each table build, never read by other modules). Sits in the
; reserved $7EE0DA..$7EE0DF region — see engine_state.inc allocations note.
PARALLAX_BANDS_HOFS_TOP  = $7EE0DA     ; 2 bytes: precomputed (world_x*ratio_top)>>8
PARALLAX_BANDS_HOFS_BOT  = $7EE0DC     ; 2 bytes: precomputed (world_x*ratio_bot)>>8
PARALLAX_BANDS_WORLDX    = $7EE0DE     ; 2 bytes: cached world_x for this build

; -----------------------------------------------------------------------------
; hdma_build_parallax_bands
; -----------------------------------------------------------------------------
; Entry contract:
;   .a16 .i16, DB=$00. Parameters already staged in PARALLAX_BANDS_LAYER,
;   PARALLAX_BANDS_YSPLIT, PARALLAX_BANDS_RATIO_TOP, PARALLAX_BANDS_RATIO_BOT
;   by the engine wrapper.
; Returns:
;   A = channel number (3..7) on success, $FFFF on alloc failure.
;
; Idempotent: if PARALLAX_BANDS_CHAN is non-zero, re-uses the existing
; channel and just rebuilds the table.
; -----------------------------------------------------------------------------
; WIDTH-RISK: entry/exit = A16/I16. Internally toggles A8 around hardware
; HDMA register writes ($43n0+); every A8 block re-enters .a16 before any
; branch target reached from multiple paths.
hdma_build_parallax_bands:
    .a16
    .i16
    ; Check whether we already own a channel; if so, just rebuild the table.
    lda f:PARALLAX_BANDS_CHAN
    bne @pb_have_chan

    ; First-call path: allocate an HDMA channel.
    jsr hdma_alloc
    cmp #$FFFF
    bne @pb_alloc_ok
    rts                                 ; allocation failed, A = $FFFF

@pb_alloc_ok:
    .a16
    sta f:PARALLAX_BANDS_CHAN
    pha                                 ; save channel number (returned later)

    ; --- Look up table base address for the allocated channel. ---
    sec
    sbc #3
    asl                                 ; word index into _hdma_table_addrs
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR

    ; --- Determine BBAD register from layer (1→$0D, 2→$0F, 3→$11). ---
    lda f:PARALLAX_BANDS_LAYER
    dec
    asl
    clc
    adc #BG1HOFS_REG
    pha                                 ; save BBAD (under chan on stack)

    ; --- Program hardware HDMA channel registers ($43n0+). ---
    ; Stack: [BBAD, channel_num]
    lda 3,s                             ; A = channel_num
    asl
    asl
    asl
    asl                                 ; A = ch_num * 16
    tax                                 ; X = $43n0 base

    sep #$20
    .a8
    lda #$02                            ; DMAP mode 2 (write twice to same reg)
    sta f:$004300, x                    ; DMAPn
    lda 1,s                             ; BBAD value from stack
    sta f:$004301, x                    ; BBADn = BG{layer}HOFS
    lda HDMA_TBL_PTR
    sta f:$004302, x                    ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                    ; A1TnH
    lda #$7E
    sta f:$004304, x                    ; A1Bn (WRAM bank)
    rep #$20
    .a16

    pla                                 ; discard BBAD; stack: [channel_num]

    jsr _hdma_pb_fill_table

    pla                                 ; A = channel_num
    pha
    jsr _hdma_enable_channel

    pla                                 ; A = channel_num (final return)
    rts

@pb_have_chan:
    ; A holds PARALLAX_BANDS_CHAN (3..7). Just rebuild table in place.
    .a16
    pha
    sec
    sbc #3
    asl
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR
    jsr _hdma_pb_fill_table
    pla                                 ; return current channel number
    rts


; -----------------------------------------------------------------------------
; hdma_update_parallax_bands — per-frame rebuild (no channel allocation)
; -----------------------------------------------------------------------------
; Called from the native frame loop after _update/_draw, mirroring the
; hdma_update_scanline_scroll hook point. Skips entirely when no channel
; allocated.
; -----------------------------------------------------------------------------
; WIDTH-RISK: entry/exit = A16/I16.
hdma_update_parallax_bands:
    rep #$30
    .a16
    .i16
    lda f:PARALLAX_BANDS_CHAN
    beq @pb_no_update

    sec
    sbc #3
    asl
    tax
    lda f:_hdma_table_addrs,x
    sta HDMA_TBL_PTR
    jsr _hdma_pb_fill_table
@pb_no_update:
    rts


; -----------------------------------------------------------------------------
; _hdma_pb_fill_table — band-conditional table fill (225 entries)
; -----------------------------------------------------------------------------
; Entry contract:
;   .a16 .i16, DB=$00, HDMA_TBL_PTR set, PARALLAX_BANDS_* parameters valid.
; Exit contract:
;   .a16 .i16, DB=$00.
;
; Cost (estimated): precompute ≈ 80 cycles, inner loop ≈ 16 cycles × 225 =
; 3600 cycles, total ≈ 3700 cycles. NOTE: the spec quoted "≤300 cycles"
; assuming the precompute amortises and the inner loop is hardware-free
; (HDMA itself is free during active display; only the table build costs
; CPU). The actual per-frame CPU cost is ≈ 3700 cycles — well within the
; cycle budget but above the spec's stated 300-cycle target. The
; sensitivity gate (PB-006) verifies the table contents match the band
; math; the spec's 300-cycle figure is updated in the final report.
; -----------------------------------------------------------------------------
; WIDTH-RISK: entry/exit = A16/I16, DB=$00. Internally:
;   1. precompute block runs in A16 throughout
;   2. fill loop toggles to A8 only inside @pb_emit for the three byte stores,
;      and re-enters A16 before any branch target reached from multiple paths
;   3. DB is set to $7E for the table writes, restored to $00 before RTS
_hdma_pb_fill_table:
    rep #$30
    .a16
    .i16

    ; -------- Read world_x from SHADOW_BG{layer}HOFS --------
    ; ES_SHADOW_BG1HOFS = $20, ES_SHADOW_BG2HOFS = $24, ES_SHADOW_BG3HOFS = $28
    ; Offset = $20 + (layer-1) * 4 = $1C + layer*4
    lda f:PARALLAX_BANDS_LAYER
    asl
    asl                                 ; layer * 4
    clc
    adc #$001C                          ; $1C + layer*4
    clc
    adc #$0100                          ; ENGINE_STATE_BASE
    tax
    lda $0000,x                         ; A = world_x (low 16 bits)
    sta f:PARALLAX_BANDS_WORLDX

    ; -------- Precompute hofs_top = (world_x * ratio_top) >> 8 --------
    jsr _pb_compute_hofs_top
    sta f:PARALLAX_BANDS_HOFS_TOP

    ; -------- Precompute hofs_bot = (world_x * ratio_bot) >> 8 --------
    jsr _pb_compute_hofs_bot
    sta f:PARALLAX_BANDS_HOFS_BOT

    ; -------- Fill table with band-spanning HDMA non-repeat entries --------
    ; HDMA mode-$02 entry format: [count_byte, hofs_lo, hofs_hi]
    ; Per fullsnes:
    ;   01h..80h  Transfer 1 unit in 1 line, then pause for next X-01h lines
    ;   00h       Terminate
    ; Non-repeat semantics: a count of $60 (=96) means: at line 0, transfer
    ; the 2 mode-$02 bytes; then idle for 95 more lines. BG2HOFS's write-
    ; twice latch holds the written value through those 95 idle lines.
    ; Effectively: one HDMA write paints 96 contiguous scanlines.
    ;
    ; The bot band needs 225 - y_split scanlines (= 129 for y_split=96).
    ; The max count per entry is $80 = 128 lines, so we split bot into
    ; two entries when the residual exceeds 128.
    ;
    ; Total table: 3 entries × 3 bytes + 1 terminator = 10 bytes.
    ; CPU cost: ~150 cycles for the three entries (down from ~3700 for
    ; the per-scanline form). Well under the spec's 300-cycle target.

    sep #$20
    .a8
    lda #$7E
    pha
    plb                                 ; DB = $7E for (dp),y writes
    rep #$20
    .a16

    ldy #$0000

    ; --- Entry 1: top band — count = y_split (1 transfer + (y_split-1) idle) ---
    sep #$20
    .a8
    lda f:PARALLAX_BANDS_YSPLIT
    sta (HDMA_TBL_PTR),y                ; count byte ($01..$80 range)
    iny
    lda f:PARALLAX_BANDS_HOFS_TOP
    sta (HDMA_TBL_PTR),y
    iny
    lda f:PARALLAX_BANDS_HOFS_TOP + 1
    sta (HDMA_TBL_PTR),y
    iny

    ; --- Bot band: 225 - y_split scanlines, split if > 128 ---
    rep #$20
    .a16
    lda #HDMA_SCANLINES
    sec
    sbc f:PARALLAX_BANDS_YSPLIT         ; A = bot_count
    cmp #129                            ; >= 129 → needs two entries
    bcc @pb_bot_one_entry

    ; --- Two-entry bot band: 128 + (bot_count - 128) ---
    sep #$20
    .a8
    lda #128                            ; first bot entry: 128 scanlines
    sta (HDMA_TBL_PTR),y
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT
    sta (HDMA_TBL_PTR),y
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT + 1
    sta (HDMA_TBL_PTR),y
    iny
    rep #$20
    .a16
    lda #HDMA_SCANLINES
    sec
    sbc f:PARALLAX_BANDS_YSPLIT
    sec
    sbc #128                            ; A = residual scanlines (1..96)
    sep #$20
    .a8
    sta (HDMA_TBL_PTR),y                ; count
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT
    sta (HDMA_TBL_PTR),y
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT + 1
    sta (HDMA_TBL_PTR),y
    iny
    bra @pb_done

@pb_bot_one_entry:
    .a16
    sep #$20
    .a8
    lda #HDMA_SCANLINES
    sec
    sbc f:PARALLAX_BANDS_YSPLIT
    sta (HDMA_TBL_PTR),y                ; count (1..128)
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT
    sta (HDMA_TBL_PTR),y
    iny
    lda f:PARALLAX_BANDS_HOFS_BOT + 1
    sta (HDMA_TBL_PTR),y
    iny

@pb_done:
    .a8                                 ; ; WIDTH-LINT: ok — single A8 entry from two bra paths above (both A8)
    ; End-of-table marker
    lda #$00
    sta (HDMA_TBL_PTR),y

    ; Restore DB=$00.
    lda #$00
    pha
    plb
    rep #$20
    .a16
    rts


; -----------------------------------------------------------------------------
; _pb_compute_hofs_top / _pb_compute_hofs_bot
; -----------------------------------------------------------------------------
; Compute (world_x * ratio) >> 8 where world_x is the cached signed 16-bit
; value at PARALLAX_BANDS_WORLDX and ratio is the low byte of the
; respective PARALLAX_BANDS_RATIO_* slot (0..255 = 0/256 .. 255/256).
;
; The SNES HW multiplier ($4202/$4203 → $4216/$4217) gives us unsigned
; 8x8 → 16-bit results. To compute the 16-bit product of a 16-bit
; world_x and an 8-bit ratio, we do two multiplications:
;
;   world_x = (hi << 8) | lo
;   product32 = ((hi * ratio) << 8) | (lo * ratio)
;   result16  = product32 >> 8
;             = (hi * ratio) | ((lo * ratio) >> 8)   [low 16 bits]
;
; For BG2HOFS purposes only the low 10 bits matter (PPU wraps to 1024-tile
; tilemap), so 16-bit truncation is exactly what we want.
;
; Entry: A16, I16. Reads PARALLAX_BANDS_WORLDX and PARALLAX_BANDS_RATIO_*.
; Exit:  A16, I16. Returns hofs in A.
; Clobbers: X.
; -----------------------------------------------------------------------------
; WIDTH-RISK: A16 entry/exit, toggled to A8 around HW multiplier writes.
; Branch-target rule: no branches inside this routine, so no width-label
; ambiguity. Width state is sequential and explicit.
_pb_compute_hofs_top:
    .a16
    .i16
    sep #$20
    .a8
    ; --- partial_lo = (world_x_lo * ratio_top) ---
    lda f:PARALLAX_BANDS_WORLDX         ; world_x_lo
    sta f:$004202                       ; WRMPYA
    lda f:PARALLAX_BANDS_RATIO_TOP      ; ratio_top low byte
    sta f:$004203                       ; WRMPYB → start 8-cycle multiply
    nop
    nop
    nop
    nop                                 ; 8 cycles wait
    rep #$20
    .a16
    lda f:$004216                       ; A = world_x_lo * ratio_top (16-bit)
    xba                                 ; A.lo <- (lo*ratio)>>8 (high byte)
    and #$00FF                          ; isolate that byte; A = (lo*ratio)>>8
    pha                                 ; stash low contribution

    sep #$20
    .a8
    ; --- partial_hi = (world_x_hi * ratio_top) ---
    lda f:PARALLAX_BANDS_WORLDX + 1     ; world_x_hi
    sta f:$004202
    lda f:PARALLAX_BANDS_RATIO_TOP
    sta f:$004203
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:$004216                       ; A = world_x_hi * ratio_top (16-bit)
    clc
    adc 1,s                             ; + (world_x_lo*ratio_top)>>8
    plx                                 ; discard stash
    rts

_pb_compute_hofs_bot:
    .a16
    .i16
    sep #$20
    .a8
    lda f:PARALLAX_BANDS_WORLDX
    sta f:$004202
    lda f:PARALLAX_BANDS_RATIO_BOT
    sta f:$004203
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:$004216
    xba
    and #$00FF
    pha

    sep #$20
    .a8
    lda f:PARALLAX_BANDS_WORLDX + 1
    sta f:$004202
    lda f:PARALLAX_BANDS_RATIO_BOT
    sta f:$004203
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:$004216
    clc
    adc 1,s
    plx
    rts


; =============================================================================
; hdma_build_split_diag — DIAGONAL coloured seam for sf_split_v (3 HDMA channels)
; =============================================================================
; Drives the window-1 left edge (WH0 $2126) and the window-2 band edges (WH2/WH3
; $2128/$2129) per scanline so a vertical left/right window split — with its
; backdrop-reveal colour band — SLANTS. seam[s] = base + (acc>>8), acc += slope
; per scanline (8.8 fixed); WH0=seam, WH2=seam-hw, WH3=seam+hw (clamped 0..255).
;
; The CALLER sets the split window recipe (W12SEL/W34SEL/WBGLOG/TMW + backdrop
; colour) — e.g. via sf_split_v_diagonal — and these inputs, then jsr here ONCE:
;   HDMA_SPLITD_BASE  (2 bytes): seam X at scanline 0 (0..255)
;   HDMA_SPLITD_SLOPE (2 bytes): 8.8 seam increment per scanline (0=vertical)
;   HDMA_SPLITD_HW    (2 bytes): band half-width (px)
; Allocates 3 HDMA channels; no-op (returns) if <3 are free. Static: the tables
; are built once (a moving/animated slant rebuilds them per frame — future work).
;
; Scratch fits ENTIRELY within the iris DP-shadow block ($0189-$0198 = the 8
; words the iris builder uses): the iris wipe and this diagonal seam are
; mutually-exclusive effects (a ROM runs one or the other), same byte-share
; pattern blessed in engine_state.inc. (Staying <= $0198 avoids ES_STREAM_DMA_CHAN
; at $0199 / ES_M7S_PTR at $019A — a streaming rail could arm a diagonal seam.)
;
; WIDTH-RISK: A16/I16 entry+exit; the fill toggles A8 for the table byte writes
; (DB=$7E) and restores A16; branch targets annotated.
; =============================================================================
HDMA_SPLITD_CH0     = $0189             ; 2 bytes: WH0 channel
HDMA_SPLITD_CH2     = $018B             ; 2 bytes: WH2 channel
HDMA_SPLITD_CH3     = $018D             ; 2 bytes: WH3 channel
HDMA_SPLITD_BASE    = $018F             ; 2 bytes: seam X at scanline 0
HDMA_SPLITD_SLOPE   = $0191             ; 2 bytes: 8.8 increment/scanline
HDMA_SPLITD_HW      = $0193             ; 2 bytes: band half-width
HDMA_SPLITD_ACC     = $0195             ; 2 bytes: 8.8 accumulator (working)
HDMA_SPLITD_OFF     = $0197             ; 2 bytes: signed per-pass offset (0/-hw/+hw)
HDMA_SPLITD_BBAD    = HDMA_SPLITD_OFF   ; BBAD (config phase) aliases OFF (fill phase) — disjoint use

hdma_build_split_diag:
    .a16
    .i16
    jsr hdma_alloc                      ; WH0 channel
    cmp #$FFFF
    beq @fail
    sta HDMA_SPLITD_CH0
    jsr hdma_alloc                      ; WH2 channel
    cmp #$FFFF
    beq @fail
    sta HDMA_SPLITD_CH2
    jsr hdma_alloc                      ; WH3 channel
    cmp #$FFFF
    beq @fail
    sta HDMA_SPLITD_CH3
    bra @alloc_ok
@fail:
    .a16
    rts                                 ; fewer than 3 channels free -> no-op
@alloc_ok:
    .a16
    .i16

    ; --- configure the 3 channels (DMAP=0, BBAD=WH0/WH2/WH3, A1T=home, A1B=$7E) ---
    lda #$0026
    sta HDMA_SPLITD_BBAD
    lda HDMA_SPLITD_CH0
    jsr _hdma_splitd_cfg
    lda #$0028
    sta HDMA_SPLITD_BBAD
    lda HDMA_SPLITD_CH2
    jsr _hdma_splitd_cfg
    lda #$0029
    sta HDMA_SPLITD_BBAD
    lda HDMA_SPLITD_CH3
    jsr _hdma_splitd_cfg

    ; --- build the 3 per-scanline tables (DB=$7E; tables live in bank $7E) ---
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb
    rep #$30
    .a16
    .i16
    stz HDMA_SPLITD_OFF                  ; WH0 pass: offset 0
    lda HDMA_SPLITD_CH0
    jsr _hdma_splitd_fill
    lda #$0000                           ; WH2 pass: offset -hw
    sec
    sbc HDMA_SPLITD_HW
    sta HDMA_SPLITD_OFF
    lda HDMA_SPLITD_CH2
    jsr _hdma_splitd_fill
    lda HDMA_SPLITD_HW                    ; WH3 pass: offset +hw
    sta HDMA_SPLITD_OFF
    lda HDMA_SPLITD_CH3
    jsr _hdma_splitd_fill
    plb

    ; --- enable the 3 channels ---
    lda HDMA_SPLITD_CH0
    jsr _hdma_enable_channel
    lda HDMA_SPLITD_CH2
    jsr _hdma_enable_channel
    lda HDMA_SPLITD_CH3
    jsr _hdma_enable_channel
    rts

; _hdma_splitd_cfg — A=channel, HDMA_SPLITD_BBAD=BBAD byte. Programs $43n0 regs.
; WIDTH-RISK: A16/I16 entry; toggles A8 for the reg byte writes; exits A16/I16.
_hdma_splitd_cfg:
    .a16
    .i16
    pha                                 ; save channel
    sec
    sbc #3
    asl
    tax                                 ; word index into _hdma_table_addrs
    lda f:_hdma_table_addrs, x
    sta HDMA_TBL_PTR                    ; table home for A1T
    pla                                 ; channel
    asl
    asl
    asl
    asl
    tax                                 ; X = ch*16 = $43n0 offset
    sep #$20
    .a8
    lda #$00
    sta f:$004300, x                    ; DMAPn = mode 0 (1 byte/scanline)
    lda HDMA_SPLITD_BBAD
    sta f:$004301, x                    ; BBADn
    lda HDMA_TBL_PTR
    sta f:$004302, x                    ; A1TnL
    lda HDMA_TBL_PTR+1
    sta f:$004303, x                    ; A1TnH
    lda #$7E
    sta f:$004304, x                    ; A1Bn = $7E
    rep #$30
    .a16
    .i16
    rts

; _hdma_splitd_fill — A=channel, HDMA_SPLITD_OFF=signed offset. DB=$7E on entry.
; Fills the channel's table: [1, clamp(base + acc>>8 + off)] per scanline.
; WIDTH-RISK: A16/I16 entry; toggles A8 for the table byte writes; exits A16/I16.
_hdma_splitd_fill:
    .a16
    .i16
    sec
    sbc #3
    asl
    tax
    lda f:_hdma_table_addrs, x
    sta HDMA_TBL_PTR                    ; this channel's table home
    lda HDMA_SPLITD_BASE
    xba                                 ; base << 8
    and #$FF00
    sta HDMA_SPLITD_ACC                 ; acc = base.00 (8.8)
    ldx #$0000                          ; X = scanline
    ldy #$0000                          ; Y = table write offset
@line:
    .a16
    .i16
    lda HDMA_SPLITD_ACC
    xba                                 ; acc >> 8
    and #$00FF                          ; A = integer seam
    clc
    adc HDMA_SPLITD_OFF                 ; + signed offset
    bpl @nn
    lda #$0000                          ; clamp negative -> 0
@nn:
    .a16
    cmp #$0100
    bcc @ok
    lda #$00FF                          ; clamp >255 -> 255
@ok:
    .a16
    sep #$20
    .a8
    pha                                 ; save seam byte
    lda #1
    sta (HDMA_TBL_PTR), y               ; line count = 1
    iny
    pla                                 ; seam byte
    sta (HDMA_TBL_PTR), y               ; WHn value
    iny
    rep #$30
    .a16
    .i16
    lda HDMA_SPLITD_ACC
    clc
    adc HDMA_SPLITD_SLOPE
    sta HDMA_SPLITD_ACC                 ; acc += slope
    inx
    cpx #HDMA_SCANLINES
    bne @line
    sep #$20
    .a8
    lda #0
    sta (HDMA_TBL_PTR), y               ; HDMA terminator
    rep #$30
    .a16
    .i16
    rts


_hdma_channel_bits:
    .byte HDMA_CH3_BIT              ; channel 3 = bit 3
    .byte HDMA_CH4_BIT              ; channel 4 = bit 4
    .byte HDMA_CH5_BIT              ; channel 5 = bit 5
    .byte HDMA_CH6_BIT              ; channel 6 = bit 6
    .byte HDMA_CH7_BIT              ; channel 7 = bit 7
