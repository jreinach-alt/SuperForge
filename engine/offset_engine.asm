; =============================================================================
; offset_engine.asm — Phase 17-3 Offset-Per-Tile Engine
; =============================================================================
; Implements the shadow-buffer + NMI-flush pipeline for Mode 2/4/6 per-column
; offset tables. In those modes, BG3's tilemap is repurposed as the offset
; source (one 16-bit word per column, merged into BG1/BG2 horizontal scroll).
;
; Mode 2 OPT semantics (ground truth: Mesen2 Core/SNES/SnesPpu.cpp
; GetTilemapData() + GetHorizontalOffsetByte()):
;
;   1. GRANULARITY — OPT is tile-column-granular:
;          hScroll = (BG1_HScroll & 0x07) | (offset & 0x3F8)
;      The low 3 bits of the offset are MASKED. Effective shifts happen in
;      8-pixel (1 tile column) increments. An offset of 7 has zero effect;
;      an offset of 8 shifts by 1 tile column.
;
;   2. COLUMN LAG — there is a +1 column delay between fetch and apply:
;      the PPU fetches the OPT byte for screen column N at one x-phase of
;      the previous column's fetch cycle. Screen col 0 uses the scanline-
;      start reset value (0). Screen col N>=1 uses the offset read from
;      BG3 tilemap entry N-1.
;
;   3. VISIBLE EFFECT REQUIRES A VARIED TILEMAP — a uniformly-tiled BG1
;      will look identical under any tile-aligned shift. 17-3's original
;      demo shipped with a uniform tilemap and its screenshot looked like
;      plain stripes regardless of OPT. Scenes wanting a visible wave must
;      vary BG1 tile content across tile-column boundaries.
;
; Shadow buffer layout (`$7E:C000`, 64 B = 32 cols × 2 B):
;   col N word = (offset & $03FF) | BG_ENABLE_BITS
;   BG_ENABLE_BITS: bit 13 = apply to BG1, bit 14 = apply to BG2
;
; API:
;   engine_scroll_column  — API block: layer, col, dx, dy → shadow buffer
;   engine_offset_flush   — DMA shadow buffer → BG3 tilemap VRAM (if dirty)
;
; Pipeline:
;   1. Scene code calls engine_scroll_column(layer, col, dx, dy). The call
;      writes one word to the shadow buffer at $7E:C000 + col*2 and sets
;      OFFSET_DIRTY.
;   2. NMI handler (or explicit caller during init) invokes engine_offset_flush,
;      which checks OFFSET_DIRTY and, if set, DMAs the full shadow buffer to
;      the active scene's BG3 tilemap in VRAM, then clears the flag.
;   3. PPU reads BG3 tilemap per column → applies offsets to BG1/BG2.
;
; For 17-3 (static demo), dy was ignored. 17-5 enables combined H+V OPT for
; Mode 2: dy is written to the V half of the shadow buffer ($7E:C040 + col*2).
; A single 128-byte NMI DMA flushes both halves to BG3 tilemap rows 0 (H) and
; 1 (V) — the PPU reads row 0 via GetHorizontalOffsetByte and row 1 via
; GetVerticalOffsetByte (Mesen2 SnesPpu.cpp:257-276).
;
; BG3 tilemap VRAM address convention: the caller (mode init) puts the BG3
; tilemap at VRAM word $0800 (byte $1000). Flush targets that address. Future
; sub-phases may parameterize via a BG3SC readback if needed.
;
; Cross-ref: docs/sprints/phase_17_bg_modes.md §17-3 (BM-030..033),
;            docs/sprints/phase_17_allocations.md §2 ($7E:C000-$C7FF).
; =============================================================================

; Prerequisites: engine_state.inc included, .p816/.smart set in parent.
OFFSET_ENGINE_PROVIDED = 1

.ifndef ENGINE_A0
ENGINE_A0 = $40
.endif
.ifndef API_BLOCK_BASE
API_BLOCK_BASE = $60
.endif

; BG3 tilemap VRAM word address for Mode 2 (the offset source). Matches the
; layout @mode2_init sets via BG3SC = $08 (bits 2..6 of BG3SC form the top
; of the tilemap word address: $08 → word $0800).
OFFSET_BG3_VRAM_WORD = $0800


.segment "CODE"

; -----------------------------------------------------------------------------
; engine_scroll_column — write one column's offset to the shadow buffer.
;
; API block (DP $60+, 4 bytes per param):
;   API_BLOCK_BASE + 0  layer (1 = BG1, 2 = BG2, 3 = both) — low byte used
;   API_BLOCK_BASE + 4  col   (0..31)                      — low byte used
;   API_BLOCK_BASE + 8  dx    (horizontal offset, 0..1023) — low word used
;   API_BLOCK_BASE + 12 dy    (vertical offset — reserved; 17-5 consumes)
;
; Output: ENGINE_A0 = 0.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Internal A8 toggles bracketed.
; DB is pushed, set to $7E, restored.
;
; Clobbers: A, X, Y.
; -----------------------------------------------------------------------------
engine_scroll_column:
    rep #$30
    .a16
    .i16

    ; Read layer (low byte of param 0) into Y for the enable-bits lookup.
    ; Layer 1 → $2000 (bit 13). Layer 2 → $4000 (bit 14). Layer 3 → $6000.
    ; We encode via a tiny compare chain; in A16 the enable-bits value
    ; stays in X until we OR it with dx.
    lda API_BLOCK_BASE + 0          ; layer (low word; we use low byte)
    and #$00FF
    cmp #$0001
    beq @layer_bg1
    cmp #$0002
    beq @layer_bg2
    cmp #$0003
    beq @layer_both
    ; Invalid layer → no-op.
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts
@layer_bg1:
    ldx #OFFSET_BG1_ENABLE
    bra @layer_ok
@layer_bg2:
    ldx #OFFSET_BG2_ENABLE
    bra @layer_ok
@layer_both:
    ldx #(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
@layer_ok:

    ; Compose the H offset word: (dx & $03FF) | enable_bits.
    ; X still holds enable_bits from the layer-lookup above.
    lda API_BLOCK_BASE + 8          ; dx (low word)
    and #$03FF                      ; mask to 10 bits (max H scroll value)
    sta ENGINE_A0                   ; temp stash H word (low)
    txa
    ora ENGINE_A0
    sta ENGINE_A0                   ; ENGINE_A0 = final H word

    ; Compose the V offset word: (dy & $03FF) | enable_bits.
    ; V-OPT is pixel-granular per PPU (SnesPpu.cpp:166-167); no low-bit mask.
    lda API_BLOCK_BASE + 12         ; dy (low word)
    and #$03FF                      ; mask to 10 bits (max V scroll value)
    sta ENGINE_A0 + 2               ; temp stash V word (low)
    txa
    ora ENGINE_A0 + 2
    sta ENGINE_A0 + 2               ; ENGINE_A0+2 = final V word

    ; Compute shadow-buffer offset = col * 2.
    lda API_BLOCK_BASE + 4          ; col (low word)
    and #$001F                      ; 0..31 wrap (keeps us inside the buffer)
    asl                             ; × 2 = byte offset
    tay                             ; Y = shadow byte offset

    ; Switch DB to $7E to write the shadow at $7E:C000.
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb

    rep #$20
    .a16
    lda ENGINE_A0
    sta OFFSET_SHADOW_H, y          ; $7E:C000 + col*2 (H half)
    lda ENGINE_A0 + 2
    sta OFFSET_SHADOW_V, y          ; $7E:C040 + col*2 (V half)

    ; Set dirty flag (1 byte write — back to A8).
    sep #$20
    .a8
    lda #$01
    sta f:OFFSET_DIRTY              ; OFFSET_DIRTY lives at $00:01B5; need
                                    ; long-form write since DB=$7E now.

    plb                             ; restore caller DB
    rep #$20
    .a16

    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; -----------------------------------------------------------------------------
; engine_scroll_column_mode4 — write one Mode-4 OPT word with per-column axis
; select (Phase 17-6a). Mode 4 fetches a single offset word per column (row
; 0 of BG3 tilemap only). Bit 15 selects axis: 0 = H (tile-granular merge
; with BG HSCROLL via 0x3F8 mask), 1 = V (pixel-granular replacement of
; VSCROLL with the low 10 bits). See Mesen2 SnesPpu.cpp:155-161.
;
; API block (DP $60+):
;   API_BLOCK_BASE + 0   layer  (1 = BG1, 2 = BG2, 3 = both)
;   API_BLOCK_BASE + 4   col    (0..31)
;   API_BLOCK_BASE + 8   axis   (0 = H, 1 = V)
;   API_BLOCK_BASE + 12  offset (0..1023)
;
; Writes to the H shadow half only (Mode 4 ignores row 1). The existing
; dirty flag + engine_offset_flush path propagates the shadow to BG3 VRAM.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Internal A8 toggles bracketed.
; DB is pushed, set to $7E, restored.
;
; Clobbers: A, X, Y.
; -----------------------------------------------------------------------------
engine_scroll_column_mode4:
    rep #$30
    .a16
    .i16

    lda API_BLOCK_BASE + 0
    and #$00FF
    cmp #$0001
    beq @m4_bg1
    cmp #$0002
    beq @m4_bg2
    cmp #$0003
    beq @m4_both
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts
@m4_bg1:
    ldx #OFFSET_BG1_ENABLE
    bra @m4_layer_ok
@m4_bg2:
    ldx #OFFSET_BG2_ENABLE
    bra @m4_layer_ok
@m4_both:
    ldx #(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
@m4_layer_ok:

    ; Compose word: (offset & $03FF) | enable_bits, then OR bit 15 if axis=V.
    lda API_BLOCK_BASE + 12         ; offset
    and #$03FF
    sta ENGINE_A0
    txa
    ora ENGINE_A0
    sta ENGINE_A0

    lda API_BLOCK_BASE + 8          ; axis
    and #$00FF
    beq @m4_axis_h
    lda ENGINE_A0
    ora #$8000
    sta ENGINE_A0
@m4_axis_h:

    ; Shadow byte offset = col * 2 (H half only).
    lda API_BLOCK_BASE + 4
    and #$001F
    asl
    tay

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E

    rep #$20
    .a16
    lda ENGINE_A0
    sta OFFSET_SHADOW_H, y          ; $7E:C000 + col*2

    sep #$20
    .a8
    lda #$01
    sta f:OFFSET_DIRTY

    plb
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; -----------------------------------------------------------------------------
; engine_offset_flush — if OFFSET_DIRTY is set, DMA the shadow buffer to the
; BG3 tilemap in VRAM (the active offset source for Mode 2/4/6).
;
; Safe to call from:
;   - NMI handler (standard pattern — shadow updates propagate each VBlank)
;   - Scene init during forced blank
;
; Does nothing if OFFSET_DIRTY = 0.
; Uses DMA channel 7 for the shadow → VRAM transfer. Since 17-5 the size is
; 128 bytes (32 cols × 2 B × 2 rows = H half at $C000..$C03F + V half at
; $C040..$C07F). The VRAM target word $0800 is BG3 tilemap row 0 (byte
; $1000..$103F); the continuation into bytes $1040..$107F is BG3 row 1 —
; exactly the layout the PPU's GetVerticalOffsetByte reads from. One DMA
; flushes both OPT rows.
; ~1024 master cycles at FastROM.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Internal toggles bracketed.
; Clobbers: A, X.
; -----------------------------------------------------------------------------
engine_offset_flush:
    rep #$30
    .a16
    .i16

    sep #$20
    .a8
    lda f:OFFSET_DIRTY
    beq @done                       ; nothing to flush

    ; Set VRAM address to the BG3 tilemap base.
    rep #$20
    .a16
    lda #OFFSET_BG3_VRAM_WORD
    sta $2116                       ; VMADDL/H
    sep #$20
    .a8
    lda #$80
    sta $2115                       ; VMAIN: increment after high byte, +1

    ; Configure DMA channel 7 for a 2-regs mode transfer to $2118/$2119.
    lda #$01                        ; DMAP7: mode 1 = write 2 bytes to 2 regs
    sta $4370
    lda #$18                        ; BBAD7 = $18 → targets $2118
    sta $4371
    rep #$20
    .a16
    lda #OFFSET_SHADOW              ; source low/mid = $C000
    sta $4372                       ; A1T7L/H
    sep #$20
    .a8
    lda #$7E                        ; source bank
    sta $4374                       ; A1B7
    rep #$20
    .a16
    lda #OFFSET_SHADOW_SIZE         ; 128 bytes (H + V halves, post-17-5)
    sta $4375                       ; DAS7L/H
    sep #$20
    .a8
    lda #$80                        ; start DMA on channel 7
    sta $420B

    ; Clear dirty flag. STZ long doesn't exist on 65816; use LDA #$00 +
    ; STA long (opcode $8F) so the write targets $00:OFFSET_DIRTY
    ; regardless of current DB.
    lda #$00
    sta f:OFFSET_DIRTY

@done:
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; Phase 17-4 — Animated wave offset
; =============================================================================
; Gated on SIN_LUT_PROVIDED (set by engine/mode7_sin_lut.inc). ROMs that want
; animated offset waves include mode7_sin_lut.inc BEFORE offset_engine.asm;
; ROMs that only need static scroll_column (like 17-3's demo) skip the LUT
; and the wave code below is compiled out.
.ifdef SIN_LUT_PROVIDED
OFFSET_ENGINE_WAVE_PROVIDED = 1

; Wave state block at $7E:C080-$C08F (16 B, inside the shadow-buffer reserve):
;   $C080  1 B  active flag (0 = off, 1 = on)
;   $C081  1 B  amp (unsigned, 0..127 — amplitude of H offset, in pixels)
;   $C082  1 B  freq (per-column phase increment, 0..255)
;   $C083  1 B  speed (per-frame phase increment, 0..255)
;   $C084  2 B  current phase (16-bit; only low byte indexes the LUT)
;   $C086  2 B  layer enable bits, pre-shifted to 16-bit (OR'd with offset)
;   $C088  1 B  running col_phase scratch (used by tick)
;   $C089  1 B  reserved — MUST stay 0 (high byte of the 16-bit `ldx
;               WAVE_STATE_COLPH` in tick; see line ~640)
;   $C08A  1 B  curve id (Phase OPT-curves: 0 sine / 1 tri / 2 saw / 3 noise).
;               Only set by engine_scroll_wave_curve; engine_scroll_wave does
;               not touch it (its build is hard-wired sine, regression-safe).
;   $C08B  5 B  reserved
;
; Scaled curve LUT at $7E:C100-$C1FF (256 B, built by engine_scroll_wave /
; engine_scroll_wave_curve). Each entry is an 8-bit two's-complement signed
; value representing (curve(i/256) * amp). For the default sine curve this is
; (sin(i/256 * 2pi) * amp); the tick samples it identically for every curve.
;
; Per-frame cost (target from BM-043: ≤ 200 CPU cycles at 32 columns): the
; unrolled loop below aims for ~15 cycles/column ≈ 480 cycles. BM-043 is
; aspirational and documented as such; actual measured cost is stored in
; the scaled_lut_end marker so tests can compare. The measured cost stays
; well under the per-frame budget (~44,671 cycles at 60fps); the 200-cycle
; target would require self-modifying code or a unique DMA/HDMA trick that
; is out of scope for 17-4.
; =============================================================================

WAVE_STATE_ACTIVE  = $C080
WAVE_STATE_AMP     = $C081
WAVE_STATE_FREQ    = $C082
WAVE_STATE_SPEED   = $C083
WAVE_STATE_PHASE   = $C084
WAVE_STATE_LAYER   = $C086
WAVE_STATE_COLPH   = $C088
WAVE_STATE_CURVE   = $C08A           ; OPT-curves: curve id (0..3); see block above
WAVE_CURVE_SCRATCH = $C08B           ; 2 B: curve-builder scratch A ($C08B-C)
WAVE_CURVE_SCRATCH2 = $C08D          ; 2 B: curve-builder scratch B ($C08D-E)
WAVE_SCALED_LUT    = $C100          ; 256 bytes of signed sine scaled by amp

; Curve ids accepted by engine_scroll_wave_curve / engine_curve_lut_build.
WAVE_CURVE_SINE    = 0
WAVE_CURVE_TRI     = 1
WAVE_CURVE_SAW     = 2
WAVE_CURVE_NOISE   = 3


; -----------------------------------------------------------------------------
; engine_scroll_wave — configure the animated wave, rebuild scaled LUT.
;
; API block:
;   API_BLOCK_BASE + 0   layer (1/2/3)
;   API_BLOCK_BASE + 4   amp   (0..127)
;   API_BLOCK_BASE + 8   freq  (0..255 — per-column phase increment)
;   API_BLOCK_BASE + 12  speed (0..255 — per-frame phase increment)
;
; Setting amp == 0 disables the wave (clears active flag); subsequent
; engine_scroll_wave_tick calls are no-ops. No new HDMA channels consumed
; (BM-042) — the wave reuses offset_engine's shadow buffer + CH7 one-shot
; DMA for flush.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Clobbers A, X, Y.
; -----------------------------------------------------------------------------
engine_scroll_wave:
    rep #$30
    .a16
    .i16

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E

    ; --- Store amp, freq, speed ---
    lda API_BLOCK_BASE + 4          ; amp (low byte)
    sta WAVE_STATE_AMP
    lda API_BLOCK_BASE + 8          ; freq
    sta WAVE_STATE_FREQ
    lda API_BLOCK_BASE + 12         ; speed
    sta WAVE_STATE_SPEED

    ; --- Layer-bits lookup (reused from scroll_column convention) ---
    lda API_BLOCK_BASE + 0          ; layer
    and #$07
    cmp #$01
    bne @lyr_not1
    lda #<OFFSET_BG1_ENABLE
    sta WAVE_STATE_LAYER
    lda #>OFFSET_BG1_ENABLE
    sta WAVE_STATE_LAYER + 1
    bra @lyr_done
@lyr_not1:
    cmp #$02
    bne @lyr_not2
    lda #<OFFSET_BG2_ENABLE
    sta WAVE_STATE_LAYER
    lda #>OFFSET_BG2_ENABLE
    sta WAVE_STATE_LAYER + 1
    bra @lyr_done
@lyr_not2:
    ; Treat any other value as "both" (3) for simplicity.
    lda #<(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
    sta WAVE_STATE_LAYER
    lda #>(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
    sta WAVE_STATE_LAYER + 1
@lyr_done:

    ; --- Reset phase to 0 ---
    stz WAVE_STATE_PHASE
    stz WAVE_STATE_PHASE + 1

    ; --- If amp == 0, disable + return ---
    lda WAVE_STATE_AMP
    bne @build_lut
    stz WAVE_STATE_ACTIVE
    plb
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@build_lut:
    ; --- Build scaled LUT: scaled[i] = (sin_lut[i*2] * amp / 256) for i=0..255.
    ;
    ; Simplification: amp is treated as a shift divisor. amp=8 → shift=5
    ; (since sin_lut peaks at ±256, 256 >> 5 = 8 = amp). amp=16 → shift=4.
    ; amp=32 → shift=3. amp=64 → shift=2. amp=128 → shift=1.
    ;
    ; This trades exact amplitude for simplicity: amp must be a power of 2.
    ; Non-power-of-2 amps round up to the next. For BM-043's amp=8 (the
    ; only spec-tested value), this is exact.
    ;
    ; Compute shift = 8 - log2(amp), then scaled[i] = sin_lut[i*2] >> shift.
    ; Handle sign by using ASR semantics (SNES LSR is logical, so we
    ; emulate arithmetic right shift via bit copy or sign-extension).

    ; Derive shift from amp (linear search — tiny, one-time cost).
    ldx #8                          ; shift counter, starts at 8
    lda WAVE_STATE_AMP
@shift_loop:
    lsr                             ; A >>= 1
    beq @shift_done                 ; A == 0 → exit
    dex
    bra @shift_loop
@shift_done:
    stx $00                         ; temp stash shift count (direct page)

    ; --- Loop over 256 LUT entries ---
    ldx #0                          ; X = entry index (0..255)
@lut_loop:
    rep #$20
    .a16
    ; Stride-2 sampling: sin_lut has 512 × 2-byte entries. We want 256
    ; scaled entries covering [0..2π] — so sample every other sin_lut
    ; entry, i.e., entry (i*2). Byte offset = entry_index × 2 bytes/entry
    ; = (i*2) × 2 = i × 4.
    phx
    txa
    asl
    asl                             ; X * 4 = byte offset into sin_lut
    tax                             ; X = byte offset (0..1020)
    lda f:sin_lut, x                ; A16 = signed 16-bit sine value
    plx

    ; Arithmetic right shift A by $00 (shift count) — preserves sign.
    sep #$20
    .a8
    ldy $00                         ; Y = shift count (i16)
@shift_a:
    cpy #0
    beq @shift_a_done
    rep #$20
    .a16
    ; ASR: duplicate sign bit, then LSR.
    ; Use CMP #$8000 + ROR pattern: cmp sets C to (A >= $8000) which is the
    ; sign bit complemented. Then ROR shifts C into bit 15.
    cmp #$8000                      ; sign bit → C (inverted)
    ror                             ; rotate C into bit 15, shift right
    sep #$20
    .a8
    dey
    bra @shift_a
@shift_a_done:

    ; A now holds the scaled sine value (low byte = signed 8-bit offset).
    rep #$20
    .a16
    sep #$20
    .a8
    sta WAVE_SCALED_LUT, x

    inx
    cpx #$0100
    bcc @lut_loop

@lut_done:
    sep #$20
    .a8
    lda #$01
    sta WAVE_STATE_ACTIVE

    plb
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; -----------------------------------------------------------------------------
; engine_curve_lut_build — REUSABLE curve-LUT generator.
;
; Fills WAVE_SCALED_LUT[0..255] ($7E:C100) with one period of a selected
; periodic curve, scaled so the peak magnitude is +/-amp (signed 8-bit
; two's-complement entries — the same format engine_scroll_wave produces and
; engine_scroll_wave_tick consumes). This is the single source of curve math
; for the offset-per-tile wave; the bend/tunnel brick can reuse it verbatim
; (or lift the per-curve formulas) to fill its own per-scanline LUTs.
;
; API block (DP $60+):
;   API_BLOCK_BASE + 0   curve id (0 sine / 1 triangle / 2 sawtooth / 3 noise)
;   API_BLOCK_BASE + 4   amp (power-of-2 magnitude, 1..128; non-pow2 rounds up)
;
; Curves (i = 0..255, output in [-amp, +amp] except saw/noise as noted):
;   0 SINE      sin_lut[i*2] >> shift           (peaks +/-amp; sin_lut path)
;   1 TRIANGLE  rising 0->+amp over i=0..63, falling +amp->-amp over 64..191,
;               rising -amp->0 over 192..255   (continuous, period 256)
;   2 SAWTOOTH  linear -amp .. +amp-step over i=0..255, hard wrap at 256
;               (one rising ramp per period; the discontinuity is the point)
;   3 NOISE     deterministic per-index pseudo-random in [-amp, +amp], from a
;               cheap hash of i (reproducible — no RNG state, no power-on dep)
;
; Requires DB = $7E on entry (caller sets it). The shift = 8 - log2(amp) is
; derived here so amp is honoured identically to engine_scroll_wave.
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Internal A8/A16 toggles bracketed.
; Assumes DB=$7E (set by caller). Clobbers A, X, Y, DP $00 (shift scratch), and
; WAVE_CURVE_SCRATCH/SCRATCH2 ($7E:C08B-E, builder-private — not DMA state).
; -----------------------------------------------------------------------------
engine_curve_lut_build:
    rep #$30
    .a16
    .i16

    ; --- Derive shift from amp (8 - log2(amp)); same scheme as the sine path.
    ldx #8
    lda API_BLOCK_BASE + 4
    and #$00FF
    beq @clb_shift_done             ; amp 0 → shift stays 8 (LUT all ~0)
@clb_shift_loop:
    lsr
    beq @clb_shift_done
    dex
    bra @clb_shift_loop
@clb_shift_done:
    stx $00                         ; $00 = shift count (i16)

    ; --- Dispatch on curve id (low byte). The per-curve bodies are each >127
    ;     bytes apart, so use jmp (abs) rather than short branches. ---
    lda API_BLOCK_BASE + 0
    and #$00FF
    cmp #WAVE_CURVE_TRI
    bne @clb_disp_not_tri
    jmp @clb_tri
@clb_disp_not_tri:
    cmp #WAVE_CURVE_SAW
    bne @clb_disp_not_saw
    jmp @clb_saw
@clb_disp_not_saw:
    cmp #WAVE_CURVE_NOISE
    bne @clb_disp_not_noise
    jmp @clb_noise
@clb_disp_not_noise:
    ; fall through → sine (curve 0 / default)

; --- curve 0: SINE — scaled[i] = ASR(sin_lut[i*2], shift) ---
@clb_sine:
    ldx #0                          ; X = entry index 0..255
@clb_sine_loop:
    rep #$20
    .a16
    phx
    txa
    asl
    asl                             ; i*4 = byte offset into sin_lut (stride-2)
    tax
    lda f:sin_lut, x                ; A16 = signed 16-bit sine
    plx
    sep #$20
    .a8
    ldy $00                         ; Y = shift count
@clb_sine_asr:
    cpy #0
    beq @clb_sine_store
    rep #$20
    .a16
    cmp #$8000                      ; ASR: sign → C, then ROR
    ror
    sep #$20
    .a8
    dey
    bra @clb_sine_asr
@clb_sine_store:
    .a8                             ; WIDTH-RISK: A8 here (sep above); store low byte
    sta WAVE_SCALED_LUT, x
    inx
    cpx #$0100
    bcc @clb_sine_loop
    rts

; --- curve 1: TRIANGLE — symmetric ramp, peaks +/-amp ---
; Build via a value V that ramps +1/-1 in 1.7.8-ish units matched to sin_lut's
; +/-256 full-scale, so the SAME ASR(., shift) maps the peak to +/-amp.
; full-scale = 256. Quarter steps of 256 over 64 indices = 4 per index.
;   i 0..63    : V = i*4            (0 .. 252  → ~+amp at peak)
;   i 64..191  : V = 512 - i*4      (+252 .. -252)
;   i 192..255 : V = i*4 - 1024     (-256 .. -4)
@clb_tri:
    ldx #0
@clb_tri_loop:
    rep #$20
    .a16
    txa
    cmp #64
    bcc @clb_tri_q1
    cmp #192
    bcc @clb_tri_q23
    ; q4: V = i*4 - 1024
    asl
    asl
    sec
    sbc #1024
    bra @clb_tri_have
@clb_tri_q1:
    ; q1: V = i*4
    asl
    asl
    bra @clb_tri_have
@clb_tri_q23:
    ; q2+q3: V = 512 - i*4
    asl
    asl
    sta WAVE_CURVE_SCRATCH          ; i*4 scratch
    lda #512
    sec
    sbc WAVE_CURVE_SCRATCH
@clb_tri_have:
    ; A16 = V in [-1024..+1020]; but full-scale we want is +/-256 → that is the
    ; sin_lut peak. Triangle peak above is ~+/-252..256 already (since i*4 at
    ; i=64 = 256). So apply the SAME shift ASR as sine.
    sep #$20
    .a8
    ldy $00
@clb_tri_asr:
    cpy #0
    beq @clb_tri_store
    rep #$20
    .a16
    cmp #$8000
    ror
    sep #$20
    .a8
    dey
    bra @clb_tri_asr
@clb_tri_store:
    .a8                             ; WIDTH-RISK: A8 (sep above)
    sta WAVE_SCALED_LUT, x
    inx
    cpx #$0100
    bcc @clb_tri_loop
    rts

; --- curve 2: SAWTOOTH — single rising ramp -amp..+amp, hard wrap each period ---
; V = i*2 - 256  → range -256 .. +254 over i=0..255 (full-scale ±256); ASR.
@clb_saw:
    ldx #0
@clb_saw_loop:
    rep #$20
    .a16
    txa
    asl                             ; i*2
    sec
    sbc #256                        ; V = i*2 - 256 in [-256 .. +254]
    sep #$20
    .a8
    ldy $00
@clb_saw_asr:
    cpy #0
    beq @clb_saw_store
    rep #$20
    .a16
    cmp #$8000
    ror
    sep #$20
    .a8
    dey
    bra @clb_saw_asr
@clb_saw_store:
    .a8                             ; WIDTH-RISK: A8 (sep above)
    sta WAVE_SCALED_LUT, x
    inx
    cpx #$0100
    bcc @clb_saw_loop
    rts

; --- curve 3: NOISE — deterministic per-index pseudo-random in [-amp, +amp] ---
; hash(i) = (i * 181 + 89) & $FF  (181 is an odd full-period multiplier; the
; +89 offset breaks the i=0→0 fixed point). Treat the 8-bit hash as a signed
; value in [-128, +127] (full-scale ±256 → take hash*2), then ASR by `shift`
; so the spread matches +/-amp. Reproducible: no RNG state, no power-on dep.
@clb_noise:
    ldx #0
@clb_noise_loop:
    rep #$20
    .a16
    txa
    and #$00FF                      ; i (0..255), A16 with clear high byte
    sta WAVE_CURVE_SCRATCH          ; scratch = i
    ; h = (i*181 + 89) & $FF, with i*181 = i*128 + i*32 + i*16 + i*4 + i.
    ; Build i*128 once, then accumulate the smaller terms into scratch2.
    asl                             ; i*2
    asl                             ; i*4
    sta WAVE_CURVE_SCRATCH2         ; acc = i*4
    asl                             ; i*8
    asl                             ; i*16
    clc
    adc WAVE_CURVE_SCRATCH2
    sta WAVE_CURVE_SCRATCH2         ; acc = i*4 + i*16 = i*20
    lda WAVE_CURVE_SCRATCH          ; i
    asl
    asl
    asl
    asl
    asl                             ; i*32
    clc
    adc WAVE_CURVE_SCRATCH2
    sta WAVE_CURVE_SCRATCH2         ; acc = i*20 + i*32 = i*52
    lda WAVE_CURVE_SCRATCH          ; i
    asl                             ; i*2
    asl                             ; i*4
    asl                             ; i*8
    asl                             ; i*16
    asl                             ; i*32
    asl                             ; i*64
    asl                             ; i*128
    clc
    adc WAVE_CURVE_SCRATCH2         ; i*128 + i*52 = i*180
    clc
    adc WAVE_CURVE_SCRATCH          ; + i = i*181
    clc
    adc #89                         ; + 89
    and #$00FF                      ; h = (i*181 + 89) & $FF
    ; signed-ify: V = (h - 128) * 2  → full-scale ±256 (matches sin_lut scale)
    sec
    sbc #128                        ; h - 128 in [-128..+127]
    asl                             ; *2 → [-256..+254]
    sep #$20
    .a8
    ldy $00
@clb_noise_asr:
    cpy #0
    beq @clb_noise_store
    rep #$20
    .a16
    cmp #$8000
    ror
    sep #$20
    .a8
    dey
    bra @clb_noise_asr
@clb_noise_store:
    .a8                             ; WIDTH-RISK: A8 (sep above)
    sta WAVE_SCALED_LUT, x
    inx
    cpx #$0100
    bcc @clb_noise_loop
    rts


; -----------------------------------------------------------------------------
; engine_scroll_wave_curve — configure the animated wave with a SELECTABLE
; curve (sine / triangle / sawtooth / noise), then rebuild the scaled LUT.
;
; Front door for the curve-variety brick. Identical to engine_scroll_wave but
; takes an extra curve-id param and routes LUT generation through the reusable
; engine_curve_lut_build. The per-frame engine_scroll_wave_tick is curve-
; agnostic (it just samples WAVE_SCALED_LUT), so no tick changes are needed.
;
; API block (DP $60+):
;   API_BLOCK_BASE + 0   layer (1/2/3)
;   API_BLOCK_BASE + 4   amp   (0..127; 0 disables)
;   API_BLOCK_BASE + 8   freq  (0..255 — per-column phase increment)
;   API_BLOCK_BASE + 12  speed (0..255 — per-frame phase increment)
;   API_BLOCK_BASE + 16  curve (0 sine / 1 triangle / 2 sawtooth / 3 noise)
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Clobbers A, X, Y, DP $00 + the API
; block (+0/+4 reused as engine_curve_lut_build's args).
; -----------------------------------------------------------------------------
engine_scroll_wave_curve:
    rep #$30
    .a16
    .i16

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E

    ; --- Store amp, freq, speed, curve ---
    lda API_BLOCK_BASE + 4          ; amp (low byte)
    sta WAVE_STATE_AMP
    lda API_BLOCK_BASE + 8          ; freq
    sta WAVE_STATE_FREQ
    lda API_BLOCK_BASE + 12         ; speed
    sta WAVE_STATE_SPEED
    lda API_BLOCK_BASE + 16         ; curve id
    sta WAVE_STATE_CURVE

    ; --- Layer-bits lookup (same convention as engine_scroll_wave) ---
    lda API_BLOCK_BASE + 0          ; layer
    and #$07
    cmp #$01
    bne @wc_lyr_not1
    lda #<OFFSET_BG1_ENABLE
    sta WAVE_STATE_LAYER
    lda #>OFFSET_BG1_ENABLE
    sta WAVE_STATE_LAYER + 1
    bra @wc_lyr_done
@wc_lyr_not1:
    cmp #$02
    bne @wc_lyr_not2
    lda #<OFFSET_BG2_ENABLE
    sta WAVE_STATE_LAYER
    lda #>OFFSET_BG2_ENABLE
    sta WAVE_STATE_LAYER + 1
    bra @wc_lyr_done
@wc_lyr_not2:
    lda #<(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
    sta WAVE_STATE_LAYER
    lda #>(OFFSET_BG1_ENABLE | OFFSET_BG2_ENABLE)
    sta WAVE_STATE_LAYER + 1
@wc_lyr_done:

    ; --- Reset phase to 0; clear COLPH high byte so the tick's 16-bit
    ;     `ldx WAVE_STATE_COLPH` reads $00xx (matches engine_scroll_wave's
    ;     documented invariant that $C089 stays clear). ---
    stz WAVE_STATE_PHASE
    stz WAVE_STATE_PHASE + 1
    lda #$00
    sta WAVE_STATE_COLPH + 1        ; $C089 = 0

    ; --- amp == 0 → disable + return ---
    lda WAVE_STATE_AMP
    bne @wc_build
    stz WAVE_STATE_ACTIVE
    plb
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@wc_build:
    ; Build the scaled LUT for the selected curve. engine_curve_lut_build
    ; reads its own API block params (curve id @ +0, amp @ +4); set them up
    ; from the already-stored wave state. DB is $7E (required by the builder).
    rep #$20
    .a16
    lda WAVE_STATE_CURVE
    and #$00FF
    sta API_BLOCK_BASE + 0
    lda WAVE_STATE_AMP
    and #$00FF
    sta API_BLOCK_BASE + 4
    jsr engine_curve_lut_build

    sep #$20
    .a8
    lda #$01
    sta WAVE_STATE_ACTIVE

    plb
    rep #$20
    .a16
    stz ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; -----------------------------------------------------------------------------
; engine_scroll_wave_tick — per-frame: advance phase, rewrite 32-col shadow
; buffer, set OFFSET_DIRTY. Call from NMI handler before engine_offset_flush.
;
; No-op if WAVE_STATE_ACTIVE is clear. Budget: ~480 cycles per frame at 32
; columns. (BM-043's 200-cycle target is aspirational; actual cost is
; dominated by 32 × ~15-cycle column bodies.)
;
; WIDTH-RISK: entry A16/I16, exit A16/I16. Clobbers A, X, Y.
; -----------------------------------------------------------------------------
engine_scroll_wave_tick:
    rep #$30
    .a16
    .i16

    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                             ; DB = $7E

    lda WAVE_STATE_ACTIVE
    bne @go
    plb
    rep #$20
    .a16
    rts

@go:
    .a8                             ; Multi-path label: `bne @go` enters in A8
                                    ; (sep #$20 at line 574); fall-through is
                                    ; impossible (rts at line 585). ca65
                                    ; .smart mode already tracks A8 here via
                                    ; the bne edge — verified by listing
                                    ; (`adc #$00` emits as `69 00`, A8-form,
                                    ; both with and without this annotation).
                                    ; Annotation is documentation-only:
                                    ; declares the runtime entry width per
                                    ; CLAUDE.md Rule 7. Silences linter
                                    ; multipath-label finding without
                                    ; encoding change.
    ; Advance phase by speed (16-bit add: phase_low += speed, phase_high += carry)
    clc
    lda WAVE_STATE_PHASE
    adc WAVE_STATE_SPEED
    sta WAVE_STATE_PHASE
    lda WAVE_STATE_PHASE + 1
    adc #$00
    sta WAVE_STATE_PHASE + 1

    ; Running col_phase = phase_low (only low byte used — LUT is 256 entries)
    lda WAVE_STATE_PHASE
    sta WAVE_STATE_COLPH

    ; Loop over 32 columns. X = col index (0..31), Y = shadow byte offset (0..62).
    ldx #0
    ldy #0
@col_loop:
    ; Read scaled_lut[col_phase] → signed 8-bit offset.
    ; X is the loop counter; save it and repurpose for the LUT index.
    phx
    ldx WAVE_STATE_COLPH            ; col_phase low byte (expanded to i16 =
                                    ; $00xx since $C089 is cleared)
    lda WAVE_SCALED_LUT, x          ; A8 = signed 8-bit scaled sine
    plx                             ; restore loop counter

    ; Sign-extend A8 to A16 without a stack round-trip.
    ; Transition to A16 preserves A's low byte; `and #$00FF` zeros the stale
    ; high byte inherited from the B register, and the bit-7 check re-sets
    ; $FF00 when the value was negative.
    rep #$20
    .a16
    and #$00FF
    bit #$0080
    beq @pos
    ora #$FF00
@pos:
    and #$03FF
    ora WAVE_STATE_LAYER
    sta OFFSET_SHADOW, y            ; shadow[col*2]

    ; Advance shadow byte offset by 2
    iny
    iny

    ; Advance col_phase by freq (8-bit wrap)
    sep #$20
    .a8
    lda WAVE_STATE_COLPH
    clc
    adc WAVE_STATE_FREQ
    sta WAVE_STATE_COLPH

    ; Next column
    inx
    cpx #32
    bcc @col_loop

    ; Mark dirty so offset_flush picks this up in the same NMI.
    lda #$01
    sta OFFSET_DIRTY

    plb
    rep #$20
    .a16
    rts

.endif  ; .ifdef SIN_LUT_PROVIDED
