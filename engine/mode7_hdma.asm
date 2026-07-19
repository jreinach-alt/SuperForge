; =============================================================================
; mode7_hdma.asm — Mode 7 Perspective HDMA (Phase 16-0a Brad port)
; =============================================================================
; Derivative work — modified transliteration.
;
;   Source:     https://github.com/bbbradsmith/SNES_stuff/blob/main/dizworld/dizworld.s
;               (specific line ranges in "Correspondence" block below).
;   Author:     Brad Smith (rainwarrior) — https://rainwarrior.ca
;   License:    Creative Commons Attribution 4.0 International (CC BY 4.0)
;               https://creativecommons.org/licenses/by/4.0/
;   Notice:     This file is a derivative work of Brad's pv_rebuild,
;               pv_set_origin, pv_abcd_lines_*, and pv_interpolate_*
;               routines. Modifications vs Brad's original: routine
;               names lost trailing underscores (_full_ → _full);
;               branch anonymous labels (:+ / :-) replaced with named
;               (@label_name); ZP-relative operand syntax replaced with
;               absolute addressing against engine state at $01B1+;
;               entry-point renames for engine integration; additive
;               HDMA channel bitmask OR instead of unconditional write;
;               double-buffered HDMA tables (pv_buffer flip, stride
;               $0900 — matching Brad's double-buffering; an earlier
;               single-buffered draft was replaced, and the pass1/pass2
;               split relies on the flip). The algorithm + numeric
;               output is byte-identical to Brad's on the Mode Y fast
;               path.
;
; Clean transliteration of Brad Smith's Dizworld perspective renderer
; (dizworld.s, rainwarrior 2022) into the SuperForge engine. Replaces
; the pre-16-0a body that used a static baked-h=64 perspective LUT.
;
; See docs/THIRDPARTY.md for consolidated attribution.
;
; Correspondence to dizworld.s:
;   pv_rebuild               = dizworld.s L1886-2454
;   pv_set_origin            = dizworld.s L2767-2832
;   pv_abcd_lines_full       = dizworld.s L2456-2567 (renamed from _full_)
;   pv_abcd_lines_sa1        = dizworld.s L2569-2637
;   pv_abcd_lines_angle0     = dizworld.s L2639-2689
;   pv_interpolate_{2x,4x}   = dizworld.s L2691-2765
;   pv_ztable                = dizworld.s L1722-1850 (vendored as mode7_pv_ztable.inc)
;   pv_buffer_x              = dizworld.s L1873-1883
;   M7_PV_L0..M7_PV_WRAP     = Brad's pv_l0..pv_wrap (ZP -> engine state)
;   M7_PV_POSX, M7_PV_POSY   = Brad's posx, posy
;   M7_PV_ANGLE              = Brad's angle (u8)
;   M7_PV_M7T                = Brad's nmi_m7t (cached A/B/C/D matrix)
;   M7_PV_NMI_M7X, _M7Y      = Brad's nmi_m7x, nmi_m7y
;   M7_PV_FOCUS_Y            = Brad's MODE_Y_SY (default 168)
;
; DP/DB contract: enters at DP=$0000 (main thread convention); sets
; DB=$7E for WRAM table writes; restores DB on exit. M7_PV_* accesses
; use absolute addressing (1 extra cycle vs Brad's DP-relative in ZP;
; ~40 cycles overhead per pv_rebuild, negligible). Math helpers in
; engine/mode7_math.asm use DP $B0-$CD scratch — disjoint from engine
; state at $01B1+, no collision.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc, mode7_math.asm, mode7_pv_ztable.inc.
;
; Cross-ref: engine/mode7_engine.asm (mode7_init/disable),
;            engine/mode7_math.asm (math helpers umul16/smul16/etc.),
;            engine/mode7_nmi.inc (NMI commits M7X/M7Y/M7SEL),
;            engine/frame_lifecycle.asm (mode7_tick dispatcher),
;            engine/mode7_pv_ztable.inc (Z-reciprocal LUT),
;            docs/sprints/phase_16_0a_divergence.md
; =============================================================================

; ---------------------------------------------------------------------------
; Brad-faithful symbol aliases (local to this file)
; ---------------------------------------------------------------------------
; Every aliased absolute-addressing access costs 1 cycle more than Brad's
; DP-relative access. Total: ~40 cycles per pv_rebuild call, negligible.
; These equates let the body of pv_rebuild / pv_set_origin / per-line
; variants be character-by-character transcriptions of dizworld.s.
;
; Brad's in-ZP values map to M7_PV_* engine-state absolute addresses:
pv_buffer   = M7_PV_BUFFER
pv_l0       = M7_PV_L0
pv_l1       = M7_PV_L1
pv_s0       = M7_PV_S0
pv_s1       = M7_PV_S1
pv_sh       = M7_PV_SH
pv_interp   = M7_PV_INTERP
pv_wrap     = M7_PV_WRAP
angle       = M7_PV_ANGLE
posx        = M7_PV_POSX
posy        = M7_PV_POSY
nmi_m7t     = M7_PV_M7T
nmi_m7x     = M7_PV_NMI_M7X
nmi_m7y     = M7_PV_NMI_M7Y

; Brad's computed per-frame scratch (kept in DP $97-$AC for speed;
; per-line loop hits these 224 times, DP vs absolute matters here).
; Using a distinct range from math helper scratch ($B0-$CD) and from
; lut_multiply_16bit scratch ($90-$96).
pv_zr       = $97      ; 2 bytes: running 1/Z (per-line lerp state)
pv_zr_inc   = $99      ; 2 bytes: 1/Z lerp increment
pv_sh_      = $9B      ; 2 bytes: effective SH (when pv_sh=0)
pv_scale    = $9D      ; 4 bytes: A/B/C/D 8-bit scales (packed)
pv_negate   = $A1      ; 1 byte:  sign-bits bitmask
pv_interps  = $A2      ; 2 bytes: interp * 4 (stride)
pv_temp     = $A4      ; 9 bytes: Brad's temp+0..temp+8 scratch

; ---------------------------------------------------------------------------
; WRAM HDMA table anchors (double-buffered, $7E:A000-$B200)
; ---------------------------------------------------------------------------
; Brad's layout at $2000+ in dizworld.s; we anchor at $A000 to avoid
; collision with the reserved program area ($2000-$9FFF). Mutex with
; the legacy engine's Mode 7 tables at $BE00-$CCFF (each ROM uses one
; engine; addresses don't overlap at runtime).

pv_hdma_ab0  = $A000    ; 1024 B: M7A/M7B per-scanline (buffer 0)
pv_hdma_cd0  = $A400    ; 1024 B: M7C/M7D per-scanline (buffer 0)
pv_hdma_bgm0 = $A800
pv_hdma_tm0  = $A810
pv_hdma_abi0 = $A820
pv_hdma_cdi0 = $A830
pv_hdma_col0 = $A840

pv_hdma_ab1  = $A900
pv_hdma_cd1  = $AD00
pv_hdma_bgm1 = $B100
pv_hdma_tm1  = $B110
pv_hdma_abi1 = $B120
pv_hdma_cdi1 = $B130
pv_hdma_col1 = $B140

PV_HDMA_STRIDE = pv_hdma_ab1 - pv_hdma_ab0   ; $0900 = 2304 B

; ---------------------------------------------------------------------------
; HDMA channel configuration
; ---------------------------------------------------------------------------
; Brad's dizworld uses CH0-CH4. We use CH3-CH7 to integrate with the
; engine's existing channel allocator convention. Phase 17-0a allocator
; will replace these literals with per-scene allocator output.
;
; Channel assignment:
;   CH3 (bit $08): BGMODE direct -> $2105   (DMAP $00, 1-byte)
;   CH4 (bit $10): TM indirect    -> $212C  (DMAP $40, 1-byte indirect)
;   CH5 (bit $20): AB indirect    -> $211B  (DMAP $43, 4-byte indirect)
;   CH6 (bit $40): CD indirect    -> $211D  (DMAP $43, 4-byte indirect)
;   CH7 (bit $80): COLDATA indir  -> $2132  (DMAP $40, 1-byte indirect)

M7_PV_HDMA_CH_BGM   = 3
M7_PV_HDMA_CH_TM    = 4
M7_PV_HDMA_CH_AB    = 5
M7_PV_HDMA_CH_CD    = 6
M7_PV_HDMA_CH_COL   = 7

; HDMA enable bitmask for NMI_HDMA_ENABLE.
;
; 16-0a scope only populates CH5 (AB matrix) + CH6 (CD matrix) with
; working per-scanline data. CH3 (BGMODE), CH4 (TM), CH7 (COLDATA)
; have stub tables built by pv_rebuild but NOT enabled — the stubs
; don't handle >128-scanline ranges correctly (`$80 | 224 = $E0`
; decodes as count=96 due to the 7-bit count field). Those channels
; light up when 16-3-3 (COLDATA fog) and 16-3-5 (BGMODE + TM split)
; populate them properly.
;
; ASM ROMs (tests/phase16/test_mode7_brad_flight.asm etc.) bypass
; this by writing $60 directly to $420C in their own NMI handler.
; Engine-NMI ROMs commit NMI_HDMA_ENABLE through the shared NMI path, so
; the bitmask must match the actually-rendered-correctly scope.
M7_PV_HDMA_BITMASK  = $60           ; CH5|CH6 (16-0a scope)
M7_PV_HDMA_BITMASK_FULL = $F8       ; CH3|CH4|CH5|CH6|CH7 (16-3-3 + 16-3-5)

; PPU register targets (BBAD = low byte of $21xx)
M7_PV_BBAD_BGMODE   = $05           ; $2105
M7_PV_BBAD_TM       = $2C           ; $212C
M7_PV_BBAD_M7A      = $1B           ; $211B (continues into M7B at $211C via HDMA Mode 3)
M7_PV_BBAD_M7C      = $1D           ; $211D (continues into M7D at $211E)
M7_PV_BBAD_COLDATA  = $32           ; $2132

; HDMA DMAP modes
M7_PV_DMAP_DIRECT_1B    = $00       ; mode 0: 1 byte, 1 register
M7_PV_DMAP_INDIRECT_1B  = $40       ; mode 0 + indirect flag
M7_PV_DMAP_INDIRECT_4B  = $43       ; mode 3: 4 bytes, 2 registers, indirect

; OR / AND masks for non-clobbering updates to NMI_HDMA_ENABLE
M7_PV_ENABLE_OR_MASK    = M7_PV_HDMA_BITMASK
M7_PV_ENABLE_AND_MASK   = $FF ^ M7_PV_HDMA_BITMASK

; ---------------------------------------------------------------------------
; Indirect tables — 1-byte WRAM sources consumed by CH4/CH7 HDMA indirect.
; ---------------------------------------------------------------------------
; These MUST live in WRAM bank $7E because the CH4/CH7 indirect-data bank
; byte ($43n7) is $7E. Phase 8 parks these at $7E:3600+ and initializes
; them at RESET. We keep the same pattern.
;
; mode7_init (engine/mode7_engine.asm) writes these bytes at boot; any
; bare test ROM that bypasses mode7_init must init them directly.

pv_tm_bg1obj    = $3600         ; WRAM: TM = BG1 + OBJ (Mode 7 ground band)
pv_tm_bg2obj    = $3601         ; WRAM: TM = BG2 + OBJ (Mode 1 sky band, 16-3-5)
pv_fade_black   = $3602         ; WRAM: COLDATA = $E0 (fog stub, 16-3-3)


; =============================================================================
; pv_buffer_x — Returns X = 0 or PV_HDMA_STRIDE based on pv_buffer flag
; =============================================================================
; Correspondence: dizworld.s L1873-1883.
; Used by pv_rebuild to select the inactive double-buffer set.
;
; Mode: .a8 .i16 on entry and exit.
; =============================================================================
pv_buffer_x:
    .a8
    .i16
    lda pv_buffer
    beq @buf0
        ldx #PV_HDMA_STRIDE
        rts
@buf0:
        ldx #0
        rts


; =============================================================================
; mode7_build_hdma_tables — Engine-public entry point
; =============================================================================
; Thin wrapper around pv_rebuild. Called automatically by frame_lifecycle's
; mode7_tick in RESOLVE phase when M7_DIRTY_REBUILD is set, or manually by
; Phase 8T ASM templates.
;
; Precondition: A16, I16, DP=$0000.
; Modifies: A, X, Y, DB (saved and restored inside pv_rebuild).
; =============================================================================
mode7_build_hdma_tables:
    jsr pv_rebuild
    rts


; =============================================================================
; engine_mode7_barrel — arm the per-scanline M7A "barrel" override (G1)
; =============================================================================
; The Mode 7 "barrel chamber" capability. pv_rebuild computes M7A inline (a
; perspective trapezoid). This hook lets a caller inject an ARBITRARY per-
; scanline M7A curve (the captured 1.0->1.5->1.0 barrel) WITHOUT forking
; pv_rebuild: pv_rebuild runs unchanged, then mode7_barrel_apply overwrites
; the M7A word of every floor-band scanline in the active AB double-buffer
; from the caller's table. M7B/M7C/M7D keep the engine's per-frame rotation
; (so the floor still spins) while M7A carries the bow.
;
; Param block (API_BLOCK_BASE):
;   API_BLOCK_BASE + $00 = barrel table address, low word (16-bit)
;   API_BLOCK_BASE + $02 = barrel table bank (low byte)
; The table is a contiguous array of u16 M7A words (8.8), one per FLOOR
; scanline, index 0 == scanline M7_PV_L0. It must hold at least
; (M7_PV_L1 - M7_PV_L0) entries. $0100 = 1.0 (no bow); larger = wider texel
; span = the row stretches outward (the barrel bulge).
;
; Call convention: A16, I16 on entry and exit. Modifies: A, X.
; =============================================================================
engine_mode7_barrel:
    .a16
    .i16
    lda API_BLOCK_BASE + $00
    sta M7_BARREL_PTR + 0               ; 16-bit store: low + high pointer bytes
    sep #$20
    .a8
    lda API_BLOCK_BASE + $02
    sta M7_BARREL_PTR + 2               ; bank byte
    lda #$01
    sta M7_BARREL_ACTIVE
    rep #$20
    .a16
    rts


; =============================================================================
; engine_mode7_barrel_off — disarm the M7A barrel override
; =============================================================================
; Clears the active flag; the next pv_rebuild's M7A perspective values stand
; unmodified. Call convention: A16, I16 on entry and exit. Modifies: A.
; =============================================================================
engine_mode7_barrel_off:
    .a16
    .i16
    sep #$20
    .a8
    stz M7_BARREL_ACTIVE
    rep #$20
    .a16
    rts


; =============================================================================
; mode7_barrel_apply — per-frame post-build hook (G1)
; =============================================================================
; Called once per frame AFTER mode7_build_hdma_tables (wired into
; sf_mode7_tick). No-op when M7_BARREL_ACTIVE == 0. When active, overwrites
; the M7A word (offset +0 of each 4-byte [A,B] entry) of every FLOOR-band
; scanline in the ACTIVE AB buffer with the caller's barrel table.
;
; The active AB buffer base is pv_hdma_ab0 + pv_buffer_x (bank $7E). The
; floor band is M7_PV_L1 - M7_PV_L0 scanlines; the per-scanline stride in the
; FINAL (post-interpolation) buffer is 4 bytes ([A,B] words). Reads the
; caller table via the M7_BARREL_PTR far pointer, advancing 2 bytes/scanline.
;
; WIDTH-RISK: enters A16/I16 (post-pv_rebuild contract). Toggles A8 only for
; the active-flag test + the buffer-select byte path; the copy loop runs
; A16/I16. Exits A16/I16. DB is the caller's (the [math_a],y / [math_p] far
; pointers carry their own bank bytes, so DB is irrelevant here).
;
; DP scratch: uses math_a ($B0, 3-byte far) as the AB write pointer and
; math_p ($B6, 3-byte far) as the table read pointer — both engine-transient,
; never live across this hook (pv_rebuild already returned).
; =============================================================================
mode7_barrel_apply:
    .a16
    .i16
    sep #$20
    .a8
    lda M7_BARREL_ACTIVE
    bne :+
    rep #$20
    .a16
    rts
:
    .a8
    ; --- floor scanline count = L1 - L0 (the override span) ---
    lda M7_PV_L1
    sec
    sbc M7_PV_L0
    bne :+                              ; zero-height floor -> nothing to do
    rep #$20
    .a16
    rts
:
    .a8
    sta pv_temp + 2                     ; pv_temp+2 = remaining scanline count (u8)

    ; --- AB write pointer = pv_hdma_ab0 + pv_buffer_x, bank $7E ---
    jsr pv_buffer_x                     ; X = 0 or PV_HDMA_STRIDE (.a8 .i16)
    rep #$20
    .a16
    txa
    clc
    adc #.loword(pv_hdma_ab0)
    sta z:math_a + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_a + 2                    ; AB buffer lives in WRAM bank $7E

    ; --- table read pointer = M7_BARREL_PTR (far) ---
    rep #$20
    .a16
    lda M7_BARREL_PTR + 0
    sta z:math_p + 0
    sep #$20
    .a8
    lda M7_BARREL_PTR + 2
    sta z:math_p + 2

    rep #$20
    .a16
    .i16
    ldy #0                              ; Y = byte offset into the AB buffer
@barrel_loop:
    .a16
    .i16
    lda [math_p]                        ; A = barrel_table[i] (u16 M7A word)
    sta [math_a], y                     ; overwrite M7A at AB[entry].A (offset +0)
    ; advance the table read pointer by 2 bytes (16-bit pointer add)
    lda z:math_p + 0
    clc
    adc #2
    sta z:math_p + 0
    ; advance the AB write offset by 4 bytes (one [A,B,C-skip... ] entry)
    iny
    iny
    iny
    iny
    sep #$20
    .a8
    dec pv_temp + 2
    rep #$20
    .a16
    bne @barrel_loop

    rts


; =============================================================================
; mode7_band_splice — per-frame post-build hook (sibling of mode7_barrel_apply)
; =============================================================================
; The C-horiz PERSPECTIVE splice primitive. Where mode7_barrel_apply overwrites
; ONLY the M7A word across the WHOLE floor band, this routine overwrites ALL
; FOUR matrix coefficients (M7A/M7B in the AB buffer, M7C/M7D in the CD buffer)
; for a caller-specified scanline SUB-RANGE [seam .. M7_PV_L1), from caller AB/CD
; source tables. That splices a SECOND (captured-once) per-scanline camera over
; the bottom band, producing two distinct perspective floors at a clean seam.
;
; Called every frame AFTER sf_mode7_tick (pv_rebuild), because pv_rebuild rewrites
; the whole floor with the live camera into the freshly-flipped active buffer, so
; the splice must re-apply into that buffer each frame. The buffer double-flips;
; the active base is pv_hdma_ab0/cd0 + pv_buffer_x (bank $7E) — the SAME buffer
; discipline mode7_barrel_apply uses.
;
; The FINAL (post-interpolation) AB/CD buffers hold 4 bytes per FLOOR scanline
; ([A_lo,A_hi,B_lo,B_hi] in AB; [C_lo,C_hi,D_lo,D_hi] in CD), index 0 == scanline
; M7_PV_L0. Band-2 starts at byte offset (seam - L0)*4; its length is
; (L1 - seam)*4 bytes. The caller's AB/CD source tables are laid out identically,
; index 0 == the seam scanline (i.e. they hold ONLY the band-2 span).
;
; PARAMETERS (via the API block, DP $60 — the same marshal slots the sf_split_h
; macros use; NO new persistent DP state, so no zp-check baseline churn):
;   API_BLOCK_BASE + 0  (word)  source AB table address low word
;   API_BLOCK_BASE + 2  (byte)  source AB table bank
;   API_BLOCK_BASE + 4  (word)  source CD table address low word
;   API_BLOCK_BASE + 6  (byte)  source CD table bank
;   API_BLOCK_BASE + 8  (byte)  seam scanline (first line of the bottom band)
;
; WIDTH-RISK: enters A16/I16 (post-pv_rebuild contract). Toggles A8 only for the
; active-flag test, the seam/L1 arithmetic, and the buffer-select bank byte; the
; copy loops run A16/I16. Exits A16/I16. DB is the caller's — the [math_a],y /
; [math_b],y far pointers carry their own bank bytes, so DB is irrelevant here.
;
; DP scratch: math_a ($B0, 3-byte far) = source read pointer, math_b ($B4, 3-byte
; far) = active-buffer write pointer, pv_temp+2 (u8) = the band-2 byte count / 4
; loop counter. All engine-transient (pv_rebuild already returned; nothing live).
; Clobbers A, X, Y.
; =============================================================================
mode7_band_splice:
    .a16
    .i16
    sep #$20
    .a8
    lda M7_PV_ACTIVE                    ; only splice when the renderer is live
    bne :+
    rep #$20
    .a16
    rts
:
    .a8
    ; --- band-2 scanline count = L1 - seam (the override span, in scanlines) ---
    lda M7_PV_L1
    sec
    sbc API_BLOCK_BASE + 8             ; A = L1 - seam
    bne :+                             ; zero-height bottom band -> nothing to do
    rep #$20
    .a16
    rts
:
    .a8
    sta pv_temp + 2                    ; pv_temp+2 = remaining scanline count (u8)

    ; --- band-2 byte offset in the active buffer = (seam - L0) * 4 ---
    lda API_BLOCK_BASE + 8            ; seam
    sec
    sbc M7_PV_L0                       ; A = seam - L0 (u8, < 224)
    rep #$20
    .a16
    and #$00FF                         ; mask to u8 (A16: 3-byte imm)
    asl a
    asl a                              ; A16 = (seam - L0) * 4 = band-2 byte offset
    sta pv_temp + 4                    ; pv_temp+4 = band-2 byte offset (u16)

    ; =====================================================================
    ; AB pass: src = API AB far ptr -> dst = active AB buffer + band-2 offset
    ; =====================================================================
    ; --- source read pointer (math_a) = API_BLOCK_BASE+0 (far) ---
    lda API_BLOCK_BASE + 0
    sta z:math_a + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2
    sta z:math_a + 2
    ; --- dst write pointer (math_b) = pv_hdma_ab0 + pv_buffer_x + band-2 offset ---
    jsr pv_buffer_x                    ; X = 0 or PV_HDMA_STRIDE (.a8 .i16)
    rep #$20
    .a16
    txa
    clc
    adc #.loword(pv_hdma_ab0)
    clc
    adc pv_temp + 4                    ; + band-2 byte offset
    sta z:math_b + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_b + 2                   ; active buffer lives in WRAM bank $7E
    rep #$20
    .a16
    jsr splice_copy_band              ; copy 4 bytes/scanline for pv_temp+2 lines

    ; =====================================================================
    ; CD pass: src = API CD far ptr -> dst = active CD buffer + band-2 offset
    ; =====================================================================
    ; reload the scanline count (splice_copy_band consumes pv_temp+2)
    sep #$20
    .a8
    lda M7_PV_L1
    sec
    sbc API_BLOCK_BASE + 8
    sta pv_temp + 2
    ; --- source read pointer (math_a) = API_BLOCK_BASE+4 (far) ---
    rep #$20
    .a16
    lda API_BLOCK_BASE + 4
    sta z:math_a + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 6
    sta z:math_a + 2
    ; --- dst write pointer (math_b) = pv_hdma_cd0 + pv_buffer_x + band-2 offset ---
    jsr pv_buffer_x
    rep #$20
    .a16
    txa
    clc
    adc #.loword(pv_hdma_cd0)
    clc
    adc pv_temp + 4
    sta z:math_b + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_b + 2
    rep #$20
    .a16
    jsr splice_copy_band

    rts

; =============================================================================
; splice_copy_band — copy 4 bytes/scanline from [math_a] to [math_b] for
; pv_temp+2 scanlines (both far pointers, bank set by the caller). Advances
; through both buffers via a shared 16-bit Y byte offset.
; WIDTH-RISK: entry A16/I16. Copy loop stays A16/I16. Exits A16/I16.
; Clobbers A, Y (and decrements pv_temp+2 to 0).
; =============================================================================
splice_copy_band:
    .a16
    .i16
    ldy #0                             ; Y = shared byte offset into both buffers
@splice_line:
    .a16
    .i16
    lda [math_a], y                    ; A/C word (offset +0)
    sta [math_b], y
    iny
    iny
    lda [math_a], y                    ; B/D word (offset +2)
    sta [math_b], y
    iny
    iny
    sep #$20
    .a8
    dec pv_temp + 2                    ; one scanline done
    rep #$20
    .a16
    bne @splice_line
    rts


; =============================================================================
; mode7_band_capture — companion of mode7_band_splice (capture-once at boot)
; =============================================================================
; The inverse copy direction: read the ACTIVE AB/CD buffers' band-2 sub-range
; [seam .. M7_PV_L1) into caller-supplied static WRAM save tables. Call ONCE at
; boot, immediately after a camera-B pv_rebuild (so the active buffer holds
; camera B's per-scanline matrix). The saved tables are then re-applied every
; frame by mode7_band_splice over the live camera-A floor.
;
; Same buffer discipline + band-2 geometry as mode7_band_splice (active base =
; pv_hdma_ab0/cd0 + pv_buffer_x, bank $7E; band-2 byte offset = (seam-L0)*4;
; length = (L1-seam)*4). Captures ALL FOUR coefficients (A,B from AB; C,D from
; CD), so the saved camera differs from the live one in every matrix element.
;
; PARAMETERS (via the API block, DP $60 — no new persistent DP state):
;   API_BLOCK_BASE + 0  (word)  destination AB save-table address low word
;   API_BLOCK_BASE + 2  (byte)  destination AB save-table bank
;   API_BLOCK_BASE + 4  (word)  destination CD save-table address low word
;   API_BLOCK_BASE + 6  (byte)  destination CD save-table bank
;   API_BLOCK_BASE + 8  (byte)  seam scanline (first line of the bottom band)
;
; WIDTH-RISK: identical contract to mode7_band_splice — enters/exits A16/I16,
; toggles A8 only for the flag test + seam/L1 arithmetic + bank byte; the copy
; loop runs A16/I16. math_a = active-buffer READ ptr, math_b = save-table WRITE
; ptr (src/dst swapped vs splice). Clobbers A, X, Y, pv_temp+2, pv_temp+4.
; =============================================================================
mode7_band_capture:
    .a16
    .i16
    sep #$20
    .a8
    lda M7_PV_ACTIVE                    ; only capture when the renderer is live
    bne :+
    rep #$20
    .a16
    rts
:
    .a8
    lda M7_PV_L1
    sec
    sbc API_BLOCK_BASE + 8             ; A = L1 - seam
    bne :+
    rep #$20
    .a16
    rts
:
    .a8
    sta pv_temp + 2                    ; band-2 scanline count (u8)
    ; --- band-2 byte offset in the active buffer = (seam - L0) * 4 ---
    lda API_BLOCK_BASE + 8
    sec
    sbc M7_PV_L0
    rep #$20
    .a16
    and #$00FF                         ; mask to u8 (A16: 3-byte imm)
    asl a
    asl a
    sta pv_temp + 4                    ; band-2 byte offset (u16)

    ; --- AB pass: src = active AB buffer + offset, dst = API AB save table ---
    sep #$20
    .a8
    jsr pv_buffer_x                    ; X = 0 or PV_HDMA_STRIDE (.a8 .i16)
    rep #$20
    .a16
    txa
    clc
    adc #.loword(pv_hdma_ab0)
    clc
    adc pv_temp + 4
    sta z:math_a + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_a + 2                   ; active buffer bank $7E (READ side)
    rep #$20
    .a16
    lda API_BLOCK_BASE + 0
    sta z:math_b + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 2
    sta z:math_b + 2                   ; save-table bank (WRITE side)
    rep #$20
    .a16
    jsr splice_copy_band

    ; --- CD pass ---
    sep #$20
    .a8
    lda M7_PV_L1
    sec
    sbc API_BLOCK_BASE + 8
    sta pv_temp + 2                    ; reload scanline count
    jsr pv_buffer_x                    ; X = 0 or PV_HDMA_STRIDE (.a8 .i16)
    rep #$20
    .a16
    txa
    clc
    adc #.loword(pv_hdma_cd0)
    clc
    adc pv_temp + 4
    sta z:math_a + 0
    sep #$20
    .a8
    lda #$7E
    sta z:math_a + 2
    rep #$20
    .a16
    lda API_BLOCK_BASE + 4
    sta z:math_b + 0
    sep #$20
    .a8
    lda API_BLOCK_BASE + 6
    sta z:math_b + 2
    rep #$20
    .a16
    jsr splice_copy_band

    rts


; =============================================================================
; mode7_set_origin — Engine-public entry point
; =============================================================================
; Thin wrapper around pv_set_origin. Reads M7_PV_FOCUS_Y as the target
; scanline. Called automatically by frame_lifecycle's mode7_tick when
; M7_DIRTY_ORIGIN is set.
;
; Precondition: A16, I16, DP=$0000.
; Modifies: A, X, Y.
; =============================================================================
mode7_set_origin:
    .a16
    .i16
    sep #$10
    .i8
    lda M7_PV_FOCUS_Y
    tay
    ; pv_set_origin expects Y = target scanline, .a16 .i8 mode.
    jsr pv_set_origin
    rep #$10
    .i16
    rts


; =============================================================================
; mode7_hdma_disable — Turn off Mode 7's HDMA channels without clobbering
;                      other allocations.
; =============================================================================
; Called from mode7_disable (and from scene transitions). Clears just the
; bits Mode 7 owns in NMI_HDMA_ENABLE, preserving any user HDMA channels.
;
; Precondition: any width; restored on exit.
; =============================================================================
mode7_hdma_disable:
    php
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    and #M7_PV_ENABLE_AND_MASK
    sta NMI_HDMA_ENABLE
    plp
    rts


; =============================================================================
; pv_rebuild — Build all 5 Mode 7 HDMA tables
; =============================================================================
; Correspondence: dizworld.s L1886-2454 (full port in progress).
; Builds BGMODE / TM / AB / CD / COLDATA HDMA tables from the current
; pv_* / posx / posy / angle / M7_M7T state. Ends by writing the new
; HDMA channel settings into new_hdma / new_hdma_en for NMI to commit.
;
; Precondition: A16, I16, DP=$0000.
; Modifies: A, X, Y, DB (saved and restored).
;
; TWO-PASS SPLIT (frame pacing): the body is factored at its register-clean
; seam into two standalone entry points so a caller that cannot afford the
; whole rebuild in one frame can spread it across two:
;   pv_rebuild_pass1 — steps 1-4d: buffer flip + per-scanline coefficient
;                      emit (the heavy ~2/3 of the cost). Emits into the
;                      inactive double-buffer half; the DISPLAYED tables and
;                      the channel config are untouched, so the frame renders
;                      the previous camera exactly as before.
;   pv_rebuild_pass2 — steps 4e-5: neighbor interpolation + channel config +
;                      enable. Completes the flip: the new tables become the
;                      active half the NMI commits.
; Contract for split callers: pass2 must follow pass1 with NO intervening
; pv_rebuild/pass1 (the flip is per-rebuild), and the perspective state
; (pv_l0/l1/interp) must not change between the passes — pass2 re-derives
; its line counts from that state. Everything else pass2 consumes (the
; emitted line data + pv_buffer) persists in WRAM/engine state; the DP
; math_a..math_r / pv_temp scratch may be freely clobbered between passes
; (pv_set_origin runs fine in between). pv_rebuild itself is unchanged in
; behavior: it runs both passes back to back.
; =============================================================================
pv_rebuild:
    .a16
    .i16
    jsr pv_rebuild_pass1            ; steps 1-4d: flip + emit (restores width)
    jmp pv_rebuild_pass2            ; steps 4e-5: interpolate + arm (tail call)

; -----------------------------------------------------------------------------
; pv_rebuild_pass1 — steps 1-4d: buffer flip + per-scanline coefficient emit.
; Precondition: A16, I16, DP=$0000. Modifies A, X, Y, DB (saved/restored).
; -----------------------------------------------------------------------------
pv_rebuild_pass1:
    .a16
    .i16
    php
    phb
    sep #$20
    rep #$10
    .a8
    .i16
    lda #$7E
    pha
    plb                             ; DB = $7E for WRAM table writes

    ; -------------------------------------------------------------------------
    ; Step 1 — flip the double buffer
    ; (dizworld.s L1896-1900)
    ; -------------------------------------------------------------------------
    lda pv_buffer
    eor #1
    sta pv_buffer

    ; -------------------------------------------------------------------------
    ; Step 2 — BGMODE + TM stub tables (16-3-5 populates these properly)
    ; -------------------------------------------------------------------------
    ; Brad's L1901-1950 builds scanline bands that switch BGMODE and TM
    ; at pv_l0. For 16-0a's scope (ground-plane only, no Mode-1 sky band),
    ; we emit a minimal one-entry pair per table that covers the full
    ; screen with Mode 7 + BG1+OBJ. 16-3-5 replaces these stubs with
    ; Brad's full scanline-band logic.
    ;
    ; Emit to the inactive buffer (selected via pv_buffer_x).
    jsr pv_buffer_x                 ; X = 0 or PV_HDMA_STRIDE
    ; BGMODE table: [$80 | 224, $07] + terminator
    ;   count $80|224 = repeat mode, 224 scanlines all writing $07 (Mode 7)
    lda #$80 | 224
    sta a:pv_hdma_bgm0 + 0, x
    lda #$07                        ; BGMODE = Mode 7
    sta a:pv_hdma_bgm0 + 1, x
    stz a:pv_hdma_bgm0 + 2, x       ; count = 0 -> end of table

    ; TM indirect table: [$80 | 224, lo(pv_tm_bg1obj), hi(pv_tm_bg1obj)] + term
    ;   repeat-mode indirect: 224 scanlines all reading from pv_tm_bg1obj
    ;   (which holds $11 = BG1 + OBJ). Indirect chunks are 3 bytes each:
    ;   count, ptr-low, ptr-high (ptr-bank separate in channel config).
    lda #$80 | 224
    sta a:pv_hdma_tm0 + 0, x
    lda #<pv_tm_bg1obj
    sta a:pv_hdma_tm0 + 1, x
    lda #>pv_tm_bg1obj
    sta a:pv_hdma_tm0 + 2, x
    stz a:pv_hdma_tm0 + 3, x        ; count = 0 -> end of table

    ; -------------------------------------------------------------------------
    ; Step 3 — COLDATA fade stub (16-3-3 populates this)
    ; -------------------------------------------------------------------------
    ; Brad's L1953-1985 builds a horizon fog gradient via per-scanline
    ; COLDATA writes. For 16-0a: single stub entry that holds COLDATA
    ; at black ($E0) for all 224 scanlines. 16-3-3 replaces with real
    ; fade.
    lda #$80 | 224
    sta a:pv_hdma_col0 + 0, x
    lda #<pv_fade_black
    sta a:pv_hdma_col0 + 1, x
    lda #>pv_fade_black
    sta a:pv_hdma_col0 + 2, x
    stz a:pv_hdma_col0 + 3, x

    ; -------------------------------------------------------------------------
    ; Step 4a — ZR0, ZR1, and zr_inc (dizworld.s L2013-2115)
    ; -------------------------------------------------------------------------
    ; ZR0 = (1 << 21) / pv_s0   — reciprocal of far-scale
    ; ZR1 = (1 << 21) / pv_s1   — reciprocal of near-scale
    ; zr_inc = (ZR1 - ZR0) / (L1 - L0) × interp  — per-line linear increment
    ;
    ; ZR is the reciprocal of Z. Linearly interpolating 1/Z across
    ; scanlines (which pv_zr_inc does) is the perspective-correct way
    ; to produce the per-scanline scale ramp. pv_ztable inverts each
    ; pv_zr back to a usable Z coefficient.
    rep #$20
    sep #$10
    .a16
    .i8
    phb
    ldy #0
    phy
    plb                             ; DB = 0 for hardware multiply/divide

    ; --- Compute ZR0 = (1 << 21) / pv_s0 ---
    ; Dividend = $00200000 (32-bit); math_a+0 low 16 = 0, math_a+2 high 16 = $20.
    lda #(1 << 21) >> 16
    stz z:math_a + 0
    sta a:math_a + 2
    lda pv_s0
    sta a:math_b + 0
    stz a:math_b + 2
    jsr udiv32
    ; Clamp result to $0001-$FFFF (avoid overflow and zero).
    lda a:math_p + 2
    beq @zr0_lo_ok
        lda #$FFFF
        sta a:math_p + 0
@zr0_lo_ok:
    lda a:math_p + 0
    bne @zr0_store
        inc
@zr0_store:
    sta pv_zr                       ; ZR0 -> pv_zr (initial per-line state)

    ; --- Compute ZR1 = (1 << 21) / pv_s1 ---
    lda pv_s1
    sta a:math_b + 0
    jsr udiv32
    lda a:math_p + 2
    beq @zr1_lo_ok
        lda #$FFFF
        sta a:math_p + 0
@zr1_lo_ok:
    lda a:math_p + 0
    bne @zr1_got
        inc
@zr1_got:
    ; --- Compute zr_inc = (ZR1 - ZR0) / (L1 - L0), then scale by interp ---
    ldy #0                          ; Y = negate flag (0 = positive)
    sec
    sbc pv_zr
    bcs @zr_diff_pos
        eor #$FFFF
        inc
        iny                         ; Y = 1 = negate
@zr_diff_pos:
    sta f:$004204                   ; WRDIVL/H = abs(ZR1 - ZR0)

    ; Clamp pv_interp to 1/2/4, store interp*4 as pv_interps (stride).
    sep #$20
    .a8
    lda pv_interp
    cmp #2
    beq @interp_ok
    cmp #4
    beq @interp_ok
        lda #1                      ; any other value -> 1 (no interpolation)
@interp_ok:
    asl
    asl
    sta pv_interps + 0
    stz pv_interps + 1

    ; Divisor for (ZR1-ZR0) / (L1-L0): scanline count + un-interpolated count.
    lda pv_l1
    sec
    sbc pv_l0
    sta f:$004206                   ; WRDIVB = (L1 - L0). Result ready in ~16 cycles.
    sta pv_temp + 0                 ; temp+0 = L1-L0 = scanline count
    ldx pv_interp
    cpx #4
    bne @unint_try2
        lsr
        lsr
        bra @unint_done
@unint_try2:
    cpx #2
    bne @unint_done_nolsr
        lsr
@unint_done_nolsr:
@unint_done:
    inc
    sta pv_temp + 1                 ; temp+1 = un-interpolated scanline count + 1

    ; Read division result and apply interp scaling + sign.
    rep #$20
    .a16
    lda f:$004214                   ; RDDIVL/H = abs(ZR1-ZR0) / (L1-L0)
    ldx pv_interp
    cpx #4
    bne @zrinc_try2
        asl
        asl
        bra @zrinc_neg
@zrinc_try2:
    cpx #2
    bne @zrinc_neg
        asl
@zrinc_neg:
    cpy #0
    beq @zrinc_store
        eor #$FFFF
        inc
@zrinc_store:
    sta pv_zr_inc                   ; per-line increment (interp-scaled, signed)

    ; -------------------------------------------------------------------------
    ; Step 4b — SA factor, rotation matrix, per-coefficient scales
    ; (dizworld.s L2117-2214)
    ; -------------------------------------------------------------------------
    ; Currently .a16 .i8, DB=0.
    ; SA = (SH * 256) / (S0 * (L1-L0))   if pv_sh != 0
    ; SA = 1                              if pv_sh == 0 (Mode Y default)
    ; In the SH=0 case, pv_sh_ is back-computed as (S0*(L1-L0))/256 so that
    ; downstream code using pv_sh_ (e.g. pv_texel_to_screen — scope 16-4+)
    ; sees the effective vertical texel scale.

    lda pv_s0
    sta z:math_a                    ; math_a low 16 = S0
    lda #0
    ldx pv_temp + 0                 ; X = L1-L0 (scanline count)
    txa
    sta z:math_b                    ; math_b low 16 = L1-L0
    jsr umul16                      ; math_p = S0 * (L1-L0)
    lda z:math_p + 0
    sta z:math_b + 0
    lda z:math_p + 2
    sta z:math_b + 2                ; math_b = 32-bit S0*(L1-L0)
    stz z:math_a + 0
    lda pv_sh
    beq @sa_sh_zero
        ; SH != 0 path: divide (SH*256)<<8 by S0*(L1-L0)
        sta pv_sh_
        sta z:math_a + 2            ; math_a high 16 = SH (so a = SH<<16)
        jsr udiv32
        lda z:math_p + 0            ; quotient low 16 = SA
        bra @sa_done
@sa_sh_zero:
        ; SH == 0 path: SA = 1, pv_sh_ = (S0*(L1-L0))/256
        lda #1 << 8
        lda z:math_b + 1            ; byte 1 of S0*(L1-L0) = that product / 256
        sta pv_sh_
@sa_done:
    sta z:math_a                    ; math_a low 16 = SA (8.8)

    ; --- Fetch sincos into cosa/sina ---
    ; sincos requires .i16 (internal `tax` gets a byte offset up to 1022
    ; into a 2KB LUT; .i8 would truncate). We arrive here in .a16 .i8, so
    ; toggle to .i16 around the call and restore on exit.
    rep #$10
    .i16
    lda #0                          ; high byte of 16-bit A = 0
    ldx angle                       ; low byte = angle (u8)
    txa                             ; A = 16-bit angle (in .a16)
    jsr sincos                      ; -> cosa, sina (signed 1.7.8)
    sep #$10
    .i8

    ; --- Store rotation matrix into nmi_m7t (A,B,C,D in 8.8) ---
    ;   A = cos, B = sin, C = -sin, D = cos
    lda z:cosa
    sta nmi_m7t + 0                 ; A = cos
    sta nmi_m7t + 6                 ; D = cos
    lda z:sina
    sta nmi_m7t + 2                 ; B = sin
    eor #$FFFF
    inc
    sta nmi_m7t + 4                 ; C = -sin

    ; --- Determine negation flags (abs cosa/sina, record sign pattern) ---
    ;   pv_negate bit layout (4 bits, one per coefficient A/B/C/D):
    ;     bit 0 = A negate, bit 1 = B, bit 2 = C, bit 3 = D
    ;   Pattern chosen so per-line EOR-then-INC applies signs correctly after
    ;   the 8-bit unsigned scale * 8-bit z product in the per-line variants.
    ldx #0
    lda z:cosa
    bpl @cosa_pos
        eor #$FFFF
        inc
        sta z:cosa
        ldx #%1001                  ; A and D need negation
@cosa_pos:
    stx pv_negate

    lda z:sina
    bmi @sina_neg
        ; sina positive: B keeps its sign (no negate), C is -sin (already neg)
        lda #%0100                  ; flip only C's negate flag
        bra @sina_apply
@sina_neg:
        eor #$FFFF
        inc
        sta z:sina
        lda #%0010                  ; B needs negation, C un-negated
@sina_apply:
    eor pv_negate
    tax
    stx pv_negate                   ; combined A/B/C/D negate mask

    ; --- Generate per-coefficient 8-bit scales (cos/2, sin/2, SA*cos/2, SA*sin/2) ---
    ; pv_scale layout after this block:
    ;   pv_scale+0 = A scale = cos / 2           (1.7, unsigned)
    ;   pv_scale+1 = B scale = SA * sin / 2     (if SH=0: equals C scale)
    ;   pv_scale+2 = C scale = sin / 2
    ;   pv_scale+3 = D scale = SA * cos / 2     (if SH=0: equals A scale)

    lda z:cosa
    sta z:math_b
    lsr
    tax
    stx pv_scale + 0                ; A = cos / 2
    lda pv_sh
    beq @scale_d_copy_a
        jsr umul16                  ; math_p = SA * cos
        lda z:math_p + 1
        lsr
        cmp #$0100
        bcc @scale_d_ok
            lda #$00FF              ; clamp to $FF
@scale_d_ok:
        tax
@scale_d_copy_a:
    stx pv_scale + 3                ; D = SA * cos / 2 (or cos/2 if SH=0)

    lda z:sina
    sta z:math_b
    lsr
    tax
    stx pv_scale + 2                ; C = sin / 2
    lda pv_sh
    beq @scale_b_copy_c
        jsr umul16                  ; math_p = SA * sin
        lda z:math_p + 1
        lsr
        cmp #$0100
        bcc @scale_b_ok
            lda #$00FF
@scale_b_ok:
        tax
@scale_b_copy_c:
    stx pv_scale + 1                ; B = SA * sin / 2 (or sin/2 if SH=0)

    ; Restore DB to $7E for the remaining WRAM writes in steps 4c/4d/4e/5.
    plb                             ; DB = $7E

    ; -------------------------------------------------------------------------
    ; Step 4c — HDMA indirection buffers (dizworld.s L2218-2298)
    ; -------------------------------------------------------------------------
    ; The AB / CD indirection tables (pv_hdma_abi0, pv_hdma_cdi0) are
    ; 3-byte entries: [count-byte, data-low, data-high]. When HDMA fires,
    ; it reads [data-low, data-high] as a pointer into pv_hdma_ab0/cd0
    ; and streams `count` entries of 4 bytes each to the PPU.
    ;
    ; Layout:
    ;   Head: 0..L0-2 scanlines pointing at pv_hdma_ab0+0 (no-op band —
    ;         BGMODE HDMA has already switched to Mode 1 in 16-3-5, so
    ;         the PPU doesn't care; for 16-0a it reads identity residuals).
    ;   Body: L0..L1-1 scanlines with repeat-mode counts ($80 | N, max 127
    ;         per entry; split across multiple entries if the scanline span
    ;         exceeds 127). Body entries point into pv_hdma_ab0 with an
    ;         incrementing offset so each scanline gets its own A/B/C/D.
    ;   Terminator: count=0 byte.
    sep #$20
    rep #$10
    .a8
    .i16
    jsr pv_buffer_x
    stx pv_temp + 4                 ; temp+4 = pv_buffer_x offset
    stx pv_temp + 6                 ; temp+6 = same (used later for body stride)
    rep #$20
    .a16

    ; --- Head section: scanlines 0..L0-1 ---
    lda pv_l0
    and #$00FF
    beq @abcdi_head_end
    dec                             ; emit one scanline BEFORE L0 (HDMA updates at pv_l0-1 -> pv_l0)
    beq @abcdi_head_end
    sta pv_temp + 2                 ; temp+2 = remaining head scanlines
@abcdi_head:
    cmp #128
    bcc @abcdi_head_cnt_ok
        lda #128                    ; repeat-mode max is 128 (bit 7 set = repeat)
@abcdi_head_cnt_ok:
    sta a:pv_hdma_abi0 + 0, x
    sta a:pv_hdma_cdi0 + 0, x
    eor #$FF
    sec
    adc pv_temp + 2                 ; update remaining count
    and #$00FF
    sta pv_temp + 2
    ; Head entries point at pv_hdma_ab0+0 (same address every entry —
    ; the data won't be displayed because BGMODE HDMA masks it out).
    lda #.loword(pv_hdma_ab0)
    clc
    adc pv_temp + 4
    sta a:pv_hdma_abi0 + 1, x
    lda #.loword(pv_hdma_cd0)
    clc
    adc pv_temp + 4
    sta a:pv_hdma_cdi0 + 1, x
    inx
    inx
    inx                             ; advance by 3 bytes (count + 2-byte ptr)
    lda pv_temp + 2
    bne @abcdi_head
@abcdi_head_end:

    ; --- Body section: scanlines L0..L1-1 ---
    lda pv_temp + 0                 ; L1-L0 (total body scanline count)
    and #$00FF
    sta pv_temp + 2                 ; temp+2 = remaining body scanlines
@abcdi_body:
    cmp #127                        ; repeat-mode max per entry (bit 7 set)
    bcc @abcdi_body_cnt_ok
        lda #127
@abcdi_body_cnt_ok:
    eor #$80                        ; set bit 7 = HDMA repeat mode
    sta a:pv_hdma_abi0 + 0, x
    sta a:pv_hdma_cdi0 + 0, x
    eor #$7F                        ; restore unsigned count for arithmetic
    sec
    adc pv_temp + 2
    and #$00FF
    sta pv_temp + 2
    lda #.loword(pv_hdma_ab0)
    clc
    adc pv_temp + 4
    sta a:pv_hdma_abi0 + 1, x
    lda #.loword(pv_hdma_cd0)
    clc
    adc pv_temp + 4
    sta a:pv_hdma_cdi0 + 1, x
    inx
    inx
    inx
    lda pv_temp + 2
    beq @abcdi_body_end
    ; Multi-chunk case: bump data offset by 127 scanlines * 4 bytes/scanline.
    lda pv_temp + 4
    clc
    adc #(127 * 4)
    sta pv_temp + 4
    lda pv_temp + 2
    bra @abcdi_body
@abcdi_body_end:
    stz a:pv_hdma_abi0 + 0, x       ; count=0 terminator
    stz a:pv_hdma_cdi0 + 0, x

    ; -------------------------------------------------------------------------
    ; Step 4d — per-line ABCD emit (dizworld.s L2299-2362)
    ; -------------------------------------------------------------------------
    ; Re-uses math_a / math_b / math_p / math_r as 24-bit far pointers
    ; into pv_hdma_ab0 / pv_hdma_cd0 at bank $7E. Per-line variants emit
    ; via `sta [math_a], Y` etc. with Y = byte offset into data space.
    ; Y starts at pv_buffer_x and advances by pv_interps (interp*4) each
    ; iteration so interpolated scanlines are skipped.
    ;
    ; Variant dispatch:
    ;   pv_scale+1 == 0 AND pv_negate & %1001 == 0  ->  angle0 (a/d only)
    ;   pv_scale+0 == pv_scale+3 AND pv_scale+1 == pv_scale+2 -> sa1 (d=a, c=-b)
    ;   otherwise -> full (independent A/B/C/D)
    .a16
    .i16
    phb
    sep #$10
    .i8
    ldx #0
    phx
    plb                             ; DB = 0 (hardware multiply + absolute writes)
    ldx #$7E
    stx z:math_a + 2                ; math_*+2 = bank byte ($7E) for indirect long
    stx z:math_b + 2
    stx z:math_p + 2
    stx z:math_r + 2
    lda #.loword(pv_hdma_ab0 + 0)
    sta z:math_a + 0
    lda #.loword(pv_hdma_ab0 + 2)
    sta z:math_b + 0
    lda #.loword(pv_hdma_cd0 + 0)
    sta z:math_p + 0
    lda #.loword(pv_hdma_cd0 + 2)
    sta z:math_r + 0
    rep #$10
    .i16
    ldy pv_temp + 6                 ; Y = pv_buffer_x offset into data space
    lda pv_temp + 1                 ; un-interpolated scanline count
    and #$00FF
    sta pv_temp + 2                 ; temp+2/3 = countdown
    lda pv_negate
    and #$000F
    sta pv_temp + 4                 ; temp+4/5 = negate bitmask (4 bits)

    ; --- Variant selection ---
    ldx pv_scale + 1                ; if B-scale = 0 ...
    bne @variant_not_angle0
        lda pv_negate
        and #%1001
        bne @variant_not_angle0
        ; b=0 + no A/D negate -> angle is 0 exactly. Use the cheap variant.
        jsr pv_abcd_lines_angle0
        bra @variant_done
@variant_not_angle0:
    sep #$20
    .a8
    txa                             ; X.lo -> A (B-scale low byte)
    cmp pv_scale + 2                ; B-scale == C-scale?
    bne @variant_full
    lda pv_scale + 0
    cmp pv_scale + 3                ; A-scale == D-scale?
    bne @variant_full
    ; b==c AND a==d -> SA=1 fast path (Mode Y with non-zero angle).
    rep #$20
    .a16
    jsr pv_abcd_lines_sa1
    bra @variant_done
@variant_full:
    rep #$20
    .a16
    jsr pv_abcd_lines_full
@variant_done:
    plb                             ; DB = $7E

    ; --- pass-1 exit: the per-line emit is complete in the flipped (not yet
    ; displayed) buffer half. Stack here is [P, caller_DB] — same shape the
    ; single-frame exit unwinds. WIDTH-LINT: ok — plp restores the caller's
    ; saved widths (pass1 entry php).
    plb                             ; restore caller's DB (pass-1 entry phb)
    plp                             ; restore caller's flags/widths
    rts

; -----------------------------------------------------------------------------
; pv_rebuild_pass2 — steps 4e-5: interpolation + channel config + enable.
; -----------------------------------------------------------------------------
; Standalone entry: may run a frame after pv_rebuild_pass1 (see the split
; contract at pv_rebuild). The prologue re-derives the cheap step-4a state
; the 4e/5 code reads (pv_interps, pv_temp+1, pv_temp+6) from the persistent
; pv_l0/l1/interp/pv_buffer engine state, so nothing depends on DP scratch
; surviving the frame gap.
; Precondition: any width (saved/restored). DP=$0000.
; Modifies: A, X, Y, DB (saved and restored).
; WIDTH-RISK: entry any width; php/plp bracket the pass — inside, widths are
; set explicitly (A8/I8 for the byte re-derives, then A16/I16 for the 4e/5
; body, exactly the widths the single-frame path arrives with).
; -----------------------------------------------------------------------------
pv_rebuild_pass2:
    php
    phb
    sep #$30
    .a8
    .i8
    ; pv_interps = clamp(pv_interp to 1/2/4) * 4 — as step 4a stored it
    lda pv_interp
    cmp #2
    beq @p2_interp_ok
    cmp #4
    beq @p2_interp_ok
        lda #1                      ; any other value -> 1 (no interpolation)
@p2_interp_ok:
    .a8
    asl
    asl
    sta pv_interps + 0
    stz pv_interps + 1
    ; pv_temp+1 = un-interpolated scanline count + 1 — as step 4a stored it
    lda pv_l1
    sec
    sbc pv_l0
    ldx pv_interp
    cpx #4
    bne @p2_cnt_try2
        lsr
        lsr
        bra @p2_cnt_done
@p2_cnt_try2:
    .a8
    cpx #2
    bne @p2_cnt_done
        lsr
@p2_cnt_done:
    .a8
    inc
    sta pv_temp + 1
    ; pv_temp+6 = byte offset of the half pass 1 emitted into (pv_buffer has
    ; not changed since the pass-1 flip; pv_buffer_x re-derives the same X)
    rep #$10
    .i16
    jsr pv_buffer_x                 ; .a8 .i16 -> X = 0 or PV_HDMA_STRIDE
    stx pv_temp + 6
    lda #$7E
    pha
    plb                             ; DB = $7E for the WRAM table reads/writes
    rep #$30
    .a16
    .i16

    ; -------------------------------------------------------------------------
    ; Step 4e — interpolation (dizworld.s L2365-2386)
    ; -------------------------------------------------------------------------
    ; When pv_interp >= 2, the per-line variants above have only emitted
    ; every 2nd (interp=2) or every 4th (interp=4) scanline. Fill in the
    ; skipped scanlines by linearly averaging their neighbors.
    ; pv_interpolate_4x handles 4x case and falls through to 2x to finish.
    .a16
    .i16
    lda pv_interps
    cmp #(2 * 4)                    ; pv_interps < 8 (interp=1) -> no interpolation
    bcc @interpolate_end
    ldx pv_temp + 6                 ; X = pv_buffer_x offset
    lda pv_temp + 1                 ; un-interpolated scanline count
    and #$00FF
    beq @interpolate_end
    dec
    beq @interpolate_end
    sta pv_temp + 2                 ; countdown = N - 1
    lda pv_interps
    cmp #(4 * 4)                    ; pv_interps == 16 (interp=4)
    beq @interp_do_4x
        jsr pv_interpolate_2x
        bra @interpolate_end
@interp_do_4x:
        jsr pv_interpolate_4x       ; 4x falls through to 2x internally
@interpolate_end:

    ; -------------------------------------------------------------------------
    ; Step 5 — HDMA channel register config (dizworld.s L2391-2450)
    ; -------------------------------------------------------------------------
    ; Writes DMAP / BBAD / table address for CH3-CH7 into engine state
    ; (which the NMI handler commits to $43n0-$43n5 each frame), then
    ; writes the indirect-data bank $43n7 directly (the NMI handler
    ; currently only covers direct HDMA, so indirect channels need the
    ; bank byte written here).
    ;
    ; Finally OR's the channel bitmask into NMI_HDMA_ENABLE (additive,
    ; preserves other HDMA consumers).
    sep #$20
    rep #$10
    .a8
    .i16

    ; --- CH3: BGMODE direct 1-byte ---
    lda #M7_PV_DMAP_DIRECT_1B       ; $00
    sta HDMA_CH3_DMAP
    lda #M7_PV_BBAD_BGMODE          ; $05
    sta HDMA_CH3_BBAD

    ; --- CH4: TM indirect 1-byte ---
    lda #M7_PV_DMAP_INDIRECT_1B     ; $40
    sta HDMA_CH4_DMAP
    lda #M7_PV_BBAD_TM              ; $2C
    sta HDMA_CH4_BBAD
    lda #$7E
    sta f:$004347                   ; CH4 indirect-data bank (long addr —
                                    ; DB is $7E at this point so `sta $4347`
                                    ; would hit WRAM, not the DMA register)

    ; --- CH5: AB indirect 4-byte (M7A/M7B) ---
    lda #M7_PV_DMAP_INDIRECT_4B     ; $43
    sta HDMA_CH5_DMAP
    lda #M7_PV_BBAD_M7A             ; $1B
    sta HDMA_CH5_BBAD
    lda #$7E
    sta f:$004357                   ; CH5 indirect-data bank

    ; --- CH6: CD indirect 4-byte (M7C/M7D) ---
    lda #M7_PV_DMAP_INDIRECT_4B     ; $43
    sta HDMA_CH6_DMAP
    lda #M7_PV_BBAD_M7C             ; $1D
    sta HDMA_CH6_BBAD
    lda #$7E
    sta f:$004367                   ; CH6 indirect-data bank

    ; --- CH7: COLDATA indirect 1-byte ---
    lda #M7_PV_DMAP_INDIRECT_1B     ; $40
    sta HDMA_CH7_DMAP
    lda #M7_PV_BBAD_COLDATA         ; $32
    sta HDMA_CH7_BBAD
    lda #$7E
    sta f:$004377                   ; CH7 indirect-data bank

    ; --- Set table addresses (offset by pv_buffer_x for the active buffer) ---
    jsr pv_buffer_x                 ; X = pv_buffer_x offset (0 or PV_HDMA_STRIDE)
    stx pv_temp + 0
    rep #$20
    .a16

    lda #.loword(pv_hdma_bgm0)
    clc
    adc pv_temp + 0
    sta HDMA_CH3_TBL_LO             ; TBL_LO + TBL_HI are 2 consecutive bytes;
                                    ; 16-bit store writes both atomically

    lda #.loword(pv_hdma_tm0)
    clc
    adc pv_temp + 0
    sta HDMA_CH4_TBL_LO

    lda #.loword(pv_hdma_abi0)
    clc
    adc pv_temp + 0
    sta HDMA_CH5_TBL_LO

    lda #.loword(pv_hdma_cdi0)
    clc
    adc pv_temp + 0
    sta HDMA_CH6_TBL_LO

    lda #.loword(pv_hdma_col0)
    clc
    adc pv_temp + 0
    sta HDMA_CH7_TBL_LO

    ; --- Enable Mode 7 HDMA channels (additive OR) ---
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    ora #M7_PV_ENABLE_OR_MASK
    sta NMI_HDMA_ENABLE
    rep #$20
    .a16
    sep #$10
    .i8

    ; -------------------------------------------------------------------------

    ; (Exit sequence: dizworld.s L2452-2454)
    ; Stack order: [P, caller_DB] at this point (inner phb already balanced).
    plb                             ; restore caller's DB (from initial phb)
    plp                             ; restore flags
    rts


; =============================================================================
; pv_abcd_lines_angle0 — angle=0 fast path (b = c = 0; a/d positive)
; =============================================================================
; Correspondence: dizworld.s L2639-2689 (pv_abcd_lines_angle0_).
; Mode Y boot state hits this path: ~121 CPU cycles per line.
;
; Inputs: pv_zr, pv_zr_inc, pv_scale+0 (A), pv_scale+3 (D).
;         Y = byte offset into pv_hdma_ab0/cd0 data space.
;         pv_temp+2 = un-interpolated scanline countdown.
;         math_a / math_b / math_p / math_r = far pointers into
;                                              pv_hdma_{ab0, ab0+2, cd0, cd0+2}
; Emits: [A, 0, 0, D] (4 bytes) per iteration, advances Y by pv_interps.
; Mode: .a16 .i16, DB=0.
; =============================================================================
pv_abcd_lines_angle0:
    .a16
    .i16
    lda pv_zr
    lsr
    lsr
    lsr
    lsr                             ; A = pv_zr >> 4 (12-bit LUT index)
    tax
    lda f:pv_ztable, x              ; z = pv_ztable[pv_zr >> 4] (8-bit)
    sta a:$4202                     ; WRMPYA = z (16-bit store spuriously
                                    ;   writes $4203 too — mandatory NOP
                                    ;   below before next $4203 write)
    nop
    ; --- Scale A = pv_scale+0 ---
    ldx pv_scale + 0
    stx a:$4203                     ; WRMPYB = scale_a; multiply starts
        ; --- Interpolation step: pv_zr += pv_zr_inc (runs during wait) ---
        lda pv_zr
        clc
        adc pv_zr_inc
        sta pv_zr
    lda a:$4216                     ; A = RDMPYL/H = z * scale_a (16-bit)
    ; --- Scale D = pv_scale+3 ---
    ldx pv_scale + 3
    stx a:$4203                     ; WRMPYB = scale_d; multiply starts
        ; --- Store A coefficient (bits 23:8 of z*scale) while waiting ---
        lsr                         ; 5x LSR lands the 2.6 fixed-point
        lsr                         ;   product at 8.8 matrix format
        lsr
        lsr
        lsr
        sta [math_a], y             ; pv_hdma_ab0+0 at Y = A coefficient
    lda a:$4216
    lsr
    lsr
    lsr
    lsr
    lsr
    sta [math_r], y                 ; pv_hdma_cd0+2 at Y = D coefficient
    ; B = C = 0 for angle=0
    lda #0
    sta [math_b], y                 ; pv_hdma_ab0+2 at Y = B = 0
    sta [math_p], y                 ; pv_hdma_cd0+0 at Y = C = 0
    ; Advance Y by interp stride (4 or 8 or 16 bytes per emit).
    tya
    clc
    adc pv_interps
    tay
    dec pv_temp + 2
    bne pv_abcd_lines_angle0
    rts


; =============================================================================
; pv_abcd_lines_sa1 — SA=1 fast path (d=a, c=-b)
; =============================================================================
; Correspondence: dizworld.s L2569-2637 (pv_abcd_lines_sa1_).
; Used when pv_sh=0 (Mode Y default) AND angle != 0: ~151 CPU cycles/line.
;
; Invariant: A-scale == D-scale AND B-scale == C-scale (magnitude). Signs
; follow pv_negate. Emits in order: A -> D (same value), then B -> C (or
; C -> B) depending on sign pattern.
;
; Inputs same as pv_abcd_lines_angle0. Reads 1 bit of pv_temp+4 per
; coefficient via `lsr pv_temp+4` (walks pv_negate bitmask); reloads it
; from pv_negate at each iteration's end.
; Mode: .a16 .i16, DB=0.
; =============================================================================
pv_abcd_lines_sa1:
    .a16
    .i16
    lda pv_zr
    lsr
    lsr
    lsr
    lsr
    tax
    lda f:pv_ztable, x
    sta a:$4202
    nop                             ; delay after 16-bit store triggers spurious $4203
    ; --- Scale A/D (single multiply since a==d) ---
    ldx pv_scale + 0
    stx a:$4203                     ; WRMPYB = A-scale
        ; Interpolation step during multiply wait.
        lda pv_zr
        clc
        adc pv_zr_inc
        sta pv_zr
    lda a:$4216                     ; A = z * A-scale
    lsr
    lsr
    lsr
    lsr
    lsr                             ; 2.6 * 1.7 >> 5 -> 8.8 matrix format
    ; --- Scale B/C (single multiply since c==-b magnitude) ---
    ldx pv_scale + 1
    stx a:$4203                     ; WRMPYB = B-scale
        ; Apply A negate bit while waiting, then store A and D=A.
        lsr pv_temp + 4             ; shift bit 0 of negate mask into carry
        bcc @sa1_a_pos
            eor #$FFFF
            inc
@sa1_a_pos:
        sta [math_a], y             ; A coefficient at pv_hdma_ab0+0
        sta [math_r], y             ; D = A at pv_hdma_cd0+2
    lda a:$4216                     ; A = z * B-scale
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr pv_temp + 4                 ; next negate bit (for B)
    bcc @sa1_b_pos
        ; B is negative this line -> store +value as C, -value as B
        sta [math_p], y             ; C = +value at pv_hdma_cd0+0
        eor #$FFFF
        inc
        sta [math_b], y             ; B = -value at pv_hdma_ab0+2
        bra @sa1_bc_done
@sa1_b_pos:
        ; B is positive -> store B, C = -B
        sta [math_b], y             ; B = +value at pv_hdma_ab0+2
        eor #$FFFF
        inc
        sta [math_p], y             ; C = -B at pv_hdma_cd0+0
@sa1_bc_done:
    ; Advance to next scanline.
    lda pv_negate                   ; reload full negate mask for next iter
    and #$000F
    sta pv_temp + 4
    tya
    clc
    adc pv_interps
    tay
    dec pv_temp + 2
    bne pv_abcd_lines_sa1
    rts


; =============================================================================
; pv_abcd_lines_full — Full independent A/B/C/D path
; =============================================================================
; Correspondence: dizworld.s L2456-2567 (pv_abcd_lines_full_).
; Used when pv_sh != 0 (tilt cases, non-Mode-Y scenes like boss arena):
; ~209 CPU cycles/line. Four separate multiplies (one per coefficient).
;
; The per-coefficient negate pattern is walked via `lsr pv_temp+4` just
; as in the sa1 variant, but applied independently to all four
; coefficients. Write order: A -> B -> C -> D, overlapping the HW
; multiplier pipeline.
;
; Mode: .a16 .i16, DB=0.
; =============================================================================
pv_abcd_lines_full:
    .a16
    .i16
    lda pv_zr
    lsr
    lsr
    lsr
    lsr
    tax
    lda f:pv_ztable, x
    sta a:$4202
    nop                             ; spurious $4203 delay
    ; --- Scale A ---
    ldx pv_scale + 0
    stx a:$4203
        ; Interpolation step during multiply wait.
        lda pv_zr
        clc
        adc pv_zr_inc
        sta pv_zr
    lda a:$4216                     ; A = z * A-scale
    lsr
    lsr
    lsr
    lsr
    lsr
    ; --- Scale B ---
    ldx pv_scale + 1
    stx a:$4203
        ; Apply A-negate + store A while B-multiply runs.
        lsr pv_temp + 4
        bcc @full_a_pos
            eor #$FFFF
            inc
@full_a_pos:
        sta [math_a], y             ; A at pv_hdma_ab0+0
    lda a:$4216                     ; A = z * B-scale
    lsr
    lsr
    lsr
    lsr
    lsr
    ; --- Scale C ---
    ldx pv_scale + 2
    stx a:$4203
        ; Apply B-negate + store B while C-multiply runs.
        lsr pv_temp + 4
        bcc @full_b_pos
            eor #$FFFF
            inc
@full_b_pos:
        sta [math_b], y             ; B at pv_hdma_ab0+2
    lda a:$4216                     ; A = z * C-scale
    lsr
    lsr
    lsr
    lsr
    lsr
    ; --- Scale D ---
    ldx pv_scale + 3
    stx a:$4203
        ; Apply C-negate + store C while D-multiply runs.
        lsr pv_temp + 4
        bcc @full_c_pos
            eor #$FFFF
            inc
@full_c_pos:
        sta [math_p], y             ; C at pv_hdma_cd0+0
    lda a:$4216                     ; A = z * D-scale
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr pv_temp + 4
    bcc @full_d_pos
        eor #$FFFF
        inc
@full_d_pos:
    sta [math_r], y                 ; D at pv_hdma_cd0+2
    ; Reload negate mask + advance Y + decrement countdown.
    lda pv_negate
    and #$000F
    sta pv_temp + 4
    tya
    clc
    adc pv_interps
    tay
    dec pv_temp + 2
    beq @full_done
    jmp pv_abcd_lines_full          ; jmp (not bne) because body is >128 bytes
@full_done:
    rts
    sep #$20
    rep #$10
    .a8
    .i16
    plb                             ; restore caller's DB
    plp
    rts


; =============================================================================
; pv_set_origin — Compute M7X/M7Y + SHADOW_BG1HOFS/VOFS for focus scanline
; =============================================================================
; Correspondence: dizworld.s L2767-2832.
;
; Anchors posx/posy at the center of scanline Y by reading the freshly-built
; AB/CD HDMA tables (B at pv_hdma_ab0+2, D at pv_hdma_cd0+2 indexed by Y's
; byte offset) and computing:
;   M7X = posx + (scanlines_above_bottom × B)
;   M7Y = posy + (scanlines_above_bottom × D)
; Plus scroll adjustment:
;   SHADOW_BG1HOFS = M7X - 128   (center HDMA scan frustum horizontally)
;   SHADOW_BG1VOFS = M7Y - L1    (pin origin to bottom of screen)
;
; Must run AFTER pv_rebuild (same frame). Reads the HDMA tables from the
; active double-buffer half (selected via pv_buffer_x).
;
; Input:  Y = target scanline (u8). Typically M7_PV_FOCUS_Y (default 168
;         for Mode Y flight; ~192 for racing).
; Precondition: .a16 .i8 mode, DP=$0000.
; Modifies: A, X, Y, math_a / math_b / math_p. Restores DB via phb/plb.
; =============================================================================
pv_set_origin:
    .a16
    .i8
    sty pv_temp + 0                 ; temp+0 = target scanline
    tya
    sec
    sbc pv_l0                       ; A = scanline - pv_l0 (offset from horizon)
    and #$00FF
    asl
    asl                             ; ×4 (each scanline's AB/CD entry = 4 bytes)
    sta pv_temp + 2                 ; temp+2/3 = byte index of target line

    sep #$20
    rep #$10
    .a8
    .i16
    lda pv_l1
    sec
    sbc pv_temp + 0                 ; scanlines above bottom = L1 - Y
    sta z:math_b                    ; math_b = scanline count (u8 for smul16_u8)

    jsr pv_buffer_x                 ; X = pv_buffer_x offset into HDMA buffer
    rep #$20
    .a16
    txa
    clc
    adc pv_temp + 2
    tax                             ; X = byte offset of target scanline's entry

    ; Read B (at AB+2) and D (at CD+2) for the target scanline.
    ; pv_hdma_ab0 / pv_hdma_cd0 are 16-bit equates pointing into bank $7E
    ; WRAM. Using `f:` with these would zero-extend to bank $00 (reading
    ; ROM). Use explicit $7E-bank long form instead.
    lda f:$7E0000 + pv_hdma_ab0 + 2, x  ; B coefficient (M7B for target line)
    sta z:math_a                         ; math_a = B (s16)
    lda f:$7E0000 + pv_hdma_cd0 + 2, x  ; D coefficient (M7D for target line)
    pha                                  ; stash D for second smul16_u8
    sep #$10
    .i8

    ; M7X = posx + (scanline_count × B).
    ; smul16_u8: math_a (s16) × math_b (u8) -> math_p (s24 in bytes 0-2).
    ; On return A = bytes 1-2 of math_p (16-bit integer product, 8.0 result).
    jsr smul16_u8
    clc
    adc posx + 2                    ; + posx integer (bytes 2-3 = signed 16-bit)
    sta nmi_m7x                     ; M7X committed by NMI to $211F

    ; Shadow BG1HOFS = M7X - 128 (centers HDMA frustum on screen column 128).
    sec
    sbc #128
    sta f:SHADOW_BG1HOFS

    ; M7Y = posy + (scanline_count × D).
    pla                             ; recover D coefficient
    sta z:math_a
    jsr smul16_u8
    clc
    adc posy + 2
    sta nmi_m7y                     ; M7Y committed by NMI to $2120

    ; Shadow BG1VOFS = M7Y - L1 (pins world origin to bottom of screen).
    lda pv_l1
    and #$00FF
    eor #$FFFF
    sec
    adc nmi_m7y
    sta f:SHADOW_BG1VOFS

    rts


; =============================================================================
; pv_interpolate_4x — interpolate every 4th-line emit to every-2nd-line
; =============================================================================
; Correspondence: dizworld.s L2691-2731 (pv_interpolate_4x_).
; Falls through to pv_interpolate_2x so the final output is every-line.
;
; Reads line N and line N+16 (4x stride = 4 scanlines × 4 bytes/scanline),
; averages via ADC + ROR, stores at line N+8 (halfway between).
;
; Input: X = pv_buffer_x offset, pv_temp+2 = lines to interpolate.
; Mode: .a16 .i16, DB=$7E.
; =============================================================================
pv_interpolate_4x:
    .a16
    .i16
    lda pv_temp + 2
    pha
    phx
@interp4x_loop:
    lda a:pv_hdma_ab0 + 0,      x
    clc
    adc a:pv_hdma_ab0 + 0 + 16, x
    ror
    sta a:pv_hdma_ab0 + 0 +  8, x
    lda a:pv_hdma_ab0 + 2,      x
    clc
    adc a:pv_hdma_ab0 + 2 + 16, x
    ror
    sta a:pv_hdma_ab0 + 2 +  8, x
    lda a:pv_hdma_cd0 + 0,      x
    clc
    adc a:pv_hdma_cd0 + 0 + 16, x
    ror
    sta a:pv_hdma_cd0 + 0 +  8, x
    lda a:pv_hdma_cd0 + 2,      x
    clc
    adc a:pv_hdma_cd0 + 2 + 16, x
    ror
    sta a:pv_hdma_cd0 + 2 +  8, x
    txa
    clc
    adc #16                         ; advance by 4 output scanlines (4x stride)
    tax
    dec pv_temp + 2
    bne @interp4x_loop
    plx
    pla
    asl                             ; double countdown for 2x pass
    sta pv_temp + 2
    ; Fall through to pv_interpolate_2x


; =============================================================================
; pv_interpolate_2x — interpolate every 2nd-line emit to every-line
; =============================================================================
; Correspondence: dizworld.s L2733-2765 (pv_interpolate_2x_).
;
; Reads line N and line N+8, averages, stores at N+4.
;
; Input: X = byte offset, pv_temp+2 = lines to interpolate.
; Mode: .a16 .i16, DB=$7E.
; =============================================================================
pv_interpolate_2x:
    .a16
    .i16
@interp2x_loop:
    lda a:pv_hdma_ab0 + 0,     x
    clc
    adc a:pv_hdma_ab0 + 0 + 8, x
    ror
    sta a:pv_hdma_ab0 + 0 + 4, x
    lda a:pv_hdma_ab0 + 2,     x
    clc
    adc a:pv_hdma_ab0 + 2 + 8, x
    ror
    sta a:pv_hdma_ab0 + 2 + 4, x
    lda a:pv_hdma_cd0 + 0,     x
    clc
    adc a:pv_hdma_cd0 + 0 + 8, x
    ror
    sta a:pv_hdma_cd0 + 0 + 4, x
    lda a:pv_hdma_cd0 + 2,     x
    clc
    adc a:pv_hdma_cd0 + 2 + 8, x
    ror
    sta a:pv_hdma_cd0 + 2 + 4, x
    txa
    clc
    adc #8                          ; advance by 2 output scanlines (2x stride)
    tax
    dec pv_temp + 2
    bne @interp2x_loop
    rts


; =============================================================================
; pv_fog_gradient_table — static fog color ramp for CH7 HDMA (Phase 16-3-3-4)
; =============================================================================
; 32 bytes, one per scanline in the fog-fade region (placed immediately below
; the horizon at runtime by 16-3-3-6b's CH7 config).
;
;   scanlines 0-15:  linear ramp from minimum-blue to full fog blue
;   scanlines 16-31: uniform full fog blue
;
; Each byte is pre-encoded as a $2132 COLDATA write: bit 7 = blue-channel
; select, bits 0-4 = intensity. HDMA streams these bytes directly to $2132
; with zero CPU cycles per scanline — no channel-select OR or intensity math
; happens at runtime. All generator arithmetic lives in the pytest
; (tests/test_phase16_3_3_4_gradient_table.py) as `round(i * 24 / 15)` for
; i=0..15, then `0x80 | intensity`.
;
; Only the blue channel is varied. Red and green COLDATA channels are set
; once per frame by color_math_tint (Phase 16-3-3-3) and held constant —
; single-CH7 fog can only drive one channel per scanline. 16-3-3-6b will
; decide whether to expand to 3 HDMA channels for full-RGB per-scanline fog.
;
; 4-byte guard prefix ($DE $AD $BE $EF) precedes the table so pytest can
; locate it via a binary search of the built ROM. Robust across ld65
; versions (no linker-map parsing required).
;
; Target fog color matches 16-3-3-3's `color_math_tint(12, 8, 24)` — the
; blue ramp reaches intensity 24 at the full-fog floor, same value the
; engine call writes to SHADOW_COLDATA_B for the uniform-tint demo.
; =============================================================================

.segment "RODATA"

pv_fog_gradient_guard:
    .byte $DE, $AD, $BE, $EF

pv_fog_gradient_table:
    ; Scanlines 0-15: linear ramp (blue intensity 0 → 24)
    .byte $80, $82, $83, $85, $86, $88, $8A, $8B
    .byte $8D, $8E, $90, $92, $93, $95, $96, $98
    ; Scanlines 16-31: uniform full fog (blue intensity 24)
    .byte $98, $98, $98, $98, $98, $98, $98, $98
    .byte $98, $98, $98, $98, $98, $98, $98, $98

.segment "CODE"
