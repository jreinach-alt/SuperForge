; =============================================================================
; sf_mode7.inc — Mode 7 perspective-floor macros (macro library)
; =============================================================================
; The front door over the engine's Mode 7 renderer: a per-scanline
; perspective floor (HDMA rewrites the affine matrix every scanline) with a
; camera you steer by (posx, posy, angle). Angle convention: 0..255 = one
; full turn, counter-clockwise; the map is 1024x1024 px (128x128 tiles of
; 8x8 px, 256 8bpp tiles max), wrapping when wrap=1.
;
; THE ARCHITECTURE IN 3 LINES (who commits what):
;   1. Main thread (these macros + sf_mode7_tick): write camera/perspective
;      state, then rebuild the per-scanline HDMA tables (pv_rebuild) and the
;      rotation origin + scroll shadows (pv_set_origin) when flagged dirty.
;   2. The engine NMI handler commits everything during VBlank: M7SEL/M7X/M7Y
;      (mode7_nmi.inc, gated on M7_PV_ACTIVE), the BG1 scroll shadows to
;      $210D/$210E (Mode 7 scroll shares those registers), and the HDMA
;      channel configs (CH5=matrix A/B, CH6=matrix C/D) from the engine-state
;      shadows that pv_rebuild wrote, then re-arms $420C.
;   3. HDMA itself feeds $211B-$211E per scanline during active display —
;      zero CPU cost. A kit ROM therefore needs NO custom NMI handler: the
;      stock engine/nmi_handler.asm covers the whole commit path.
;
; ENGINE LINK PARTNERS — include in THIS ORDER inside the CODE segment
; (mode7_math reads the sine LUT through the label, pv_rebuild needs the
; math helpers, mode7_engine JSRs into both + the allocator):
;
;   .include "engine_state.inc"        ; (top of file, equates only)
;   ...
;   .segment "CODE"
;   NMI:
;   .include "nmi_handler.asm"         ; pulls mode7_nmi.inc itself
;   ...
;   mode7_sin_lut:
;       .include "mode7_sin_lut.inc"   ; 512-entry sine LUT, 1.7.8 signed:
;                                      ;   stores the NEGATED sine, so index
;                                      ;   64 (a quarter turn) reads -$0100
;   .include "hdma_alloc.asm"          ; channel allocator (mode7_init pins
;                                      ;   CH5+CH6 through it)
;   .include "mode7_math.asm"          ; smul16 / sincos / divide helpers
;   .segment "RODATA"
;   .include "mode7_pv_ztable.inc"     ; Z-reciprocal LUT for the projection
;   .segment "CODE"
;   .include "mode7_hdma.asm"          ; pv_rebuild + pv_set_origin
;   .include "mode7_engine.asm"        ; mode7_init/disable/vram_upload
;                                      ;   (self-includes the HDMA-allocator
;                                      ;   wrapper)
;
; DP SCRATCH MAP (engine-claimed, transient — none of it survives across an
; engine call; game DP $32-$5F is never touched):
;   $90-$96  multiply-helper scratch (used under pv_rebuild)
;   $97-$AC  per-frame projection scratch (pv_zr/pv_scale/pv_temp...). This
;            transiently OVERLAPS API-block slots $94-$9F — fine by
;            construction: the macros marshal into the API block immediately
;            before the JSR that consumes it, and nothing here calls into a
;            projection rebuild while API-block args are still live.
;   $B0-$CD  math helpers (math_a/math_b/math_p, cosa/sina, sincos temp)
; WRAM (bank $7E): HDMA tables double-buffered at $A000-$B24F; one-byte HDMA
; indirect sources at $3600-$3602 (written by mode7_init).
;
; MUTEX: Mode 7 and the BG1/BG2 tilemap engines are mutually exclusive on
; screen (Mode 7 repurposes BG1 + VRAM wholesale). mode7_disable restores the
; previous graphics mode.
;
; *** THE SKY RULE — A PERSPECTIVE FLOOR REQUIRES A HORIZON SKY-SPLIT. ***
; Mode 7 has a SINGLE BG layer (the perspective floor). Whenever the horizon is
; ON-SCREEN (sf_mode7_perspective l0 > 0 — i.e. the floor does NOT fill the
; whole screen top-to-bottom), the band ABOVE the horizon would otherwise show
; the ground tilemap SMEARED UPWARD — the "floor-in-sky" defect. TWO things fix
; it together; do BOTH:
;   1. sf_mode7_flags #$C0  — set M7SEL out-of-map to FILL (tile 0), not WRAP
;      ($00). WRAP tiles the floor across the off-map area; FILL shows tile 0.
;   2. sf_mode7_sky_split   — a per-scanline TM HDMA that turns BG1 OFF above
;      the horizon so the CGRAM[0] backdrop (reserve it as a SKY colour in your
;      asset generator) shows there, and keeps BG1 ON below it for the floor.
; A floor with l0 == 1 (the near-orthographic top-down view, horizon at the very
; top) does NOT need the split — the floor legitimately fills the screen. Any
; floor with a visible horizon (l0 in the tens) MUST arm sf_mode7_sky_split, or
; the sky band renders smeared ground. (Background: the rpg overworld shipped
; without this and the user rejected the floor-in-sky render; the racer's
; arm_sky_split is the proven pattern this macro generalises.)
; =============================================================================

.ifndef SF_MODE7_INC
SF_MODE7_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_mode7_on — switch the PPU to Mode 7 and arm the perspective renderer.
; -----------------------------------------------------------------------------
; Saves the current graphics mode, sets BGMODE=7, loads neutral perspective
; defaults (override with sf_mode7_perspective / sf_mode7_cam / sf_mode7_focus
; BEFORE the first sf_mode7_tick), pins HDMA channels 5+6 in the allocator,
; and flags both dirty bits so the first sf_mode7_tick builds fresh tables.
; Call during forced blank, after the map is uploaded (sf_mode7_load_map).
; Clobbers A, X. Result: M7_PV_ACTIVE=1.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); mode7_init toggles
; widths internally and exits A16/I16.
.macro sf_mode7_on
    rep #$30
    .a16
    .i16
    jsr mode7_init
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_off — leave Mode 7, restore the previous graphics mode.
; -----------------------------------------------------------------------------
; Clears M7_PV_ACTIVE, releases the Mode 7 HDMA channels, restores the saved
; BGMODE and a Mode-1 layer set. Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; exits A16/I16.
.macro sf_mode7_off
    rep #$30
    .a16
    .i16
    jsr mode7_disable
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_load_map src_label, size — DMA an interleaved map into VRAM.
; -----------------------------------------------------------------------------
;   src_label  LABEL of the interleaved data (even bytes = 128x128 tilemap,
;              odd bytes = 8bpp tile pixels — the native Mode 7 VRAM word
;              layout). NOT verbatim: the macro takes .loword()/bank of it,
;              so any bank works (e.g. a BANK1 blob under lorom_64k.cfg).
;              Generate with toolchain/mode7_assets.py (interleave_mode7_data
;              / convert_mode7_full) or commit a fixture generator.
;   size       transfer size in BYTES, verbatim 16-bit operand (#$8000 = the
;              full 32KB map; smaller partial maps upload from word 0 up).
; Wraps the engine's mode7_vram_upload: sets VMAIN=$80 (word increment),
; VMADD=$0000, and fires a general-purpose DMA on channel 1. MUST run during
; forced blank (the kit flow: right after sf_coldstart, before screen-on) —
; the VRAM port ignores writes mid-frame and a long upload would race the
; NMI if one were enabled. Chosen over a CPU copy loop because the engine
; routine is the proven single-DMA path for pre-interleaved data; a CPU loop
; would only be needed for data that still needs interleaving at boot.
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; toggles A8 for the bank byte; exits
; A16/I16.
.macro sf_mode7_load_map sf_src, sf_size
    rep #$30
    .a16
    .i16
    lda #.loword(sf_src)
    sta API_BLOCK_BASE + $00       ; source address (low word)
    sep #$20
    .a8
    lda #^sf_src
    sta API_BLOCK_BASE + $02       ; source bank
    rep #$20
    .a16
    lda sf_size
    sta API_BLOCK_BASE + $04       ; byte count
    jsr mode7_vram_upload
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_cam posx, posy, angle — place the camera (the per-frame call).
; -----------------------------------------------------------------------------
;   posx, posy  16-bit map position in px (verbatim operands — DP words or
;               #imm). Stored as 16.16 with the fraction zeroed.
;   angle       16-bit operand, LOW byte used: 0..255 = one full turn.
; Sets the origin-dirty flag always; sets the rebuild-dirty flag ONLY when
; the angle actually changed (a full rebuild measures 220-295k master
; clocks = 62-83% of a frame for the shipped parameter sets — moving in a
; straight line stays on the ~3,600-mc cheap path; measure your own set
; with tests/persp_cycles_test.asm). sf_mode7_tick consumes the flags.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the angle compare + flag bytes;
; the .local label below the beq carries an explicit .a8; exits A16/I16.
.macro sf_mode7_cam sf_px, sf_py, sf_angle
    .local m7c_same_angle
    rep #$30
    .a16
    .i16
    stz M7_PV_POSX + 0             ; fraction = 0
    lda sf_px
    sta M7_PV_POSX + 2             ; integer px
    stz M7_PV_POSY + 0
    lda sf_py
    sta M7_PV_POSY + 2
    lda sf_angle
    sep #$20
    .a8
    cmp M7_PV_ANGLE
    beq m7c_same_angle
    sta M7_PV_ANGLE
    lda #$01
    sta M7_DIRTY_REBUILD           ; rotation changes the whole matrix table
m7c_same_angle:
    .a8
    lda #$01
    sta M7_DIRTY_ORIGIN            ; translation only re-anchors the origin
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_perspective l0, l1, s0, s1, sh, interp, wrap — the trapezoid.
; -----------------------------------------------------------------------------
;   l0      horizon scanline (8-bit; the floor starts here. 56 = the racer
;           rail's high-horizon view; 96 = the mode7_test run-gate's)
;   l1      bottom scanline (8-bit; usually 224)
;   s0      far-scale  u16 (texel step at l0 — bigger = more compression)
;   s1      near-scale u16 (texel step at l1 — smaller = tighter camera)
;   sh      vertical texel height u16 (0 = derive; nonzero squashes vertical
;           relative to horizontal for a road-like aspect)
;   interp  per-scanline interpolation factor (1/2/4; 2 is the proven value)
;   wrap    1 = the 1024px map wraps, 0 = clamps
; All operands verbatim 16-bit (#imm or DP/abs word); 8-bit fields take the
; low byte. The proven racing-camera set: 96, 224, 192, 24, 16, 2, 1 with
; sf_mode7_focus 192. The proven flight-camera set: 45, 224, 436, 77, 0, 2, 1
; with sf_mode7_focus 168 (also the defaults sf_mode7_on installs).
; INTUITION (the altitude knob): a BIGGER s0 makes the far row span more map, so
; the ground looks FARTHER / more compressed (recedes); a smaller s0 brings it
; closer. Drive s0/s1 per frame from an altitude value (via sf_mode7_scale) for
; a flight rail — see docs/guides/mode7_free_flight.md.
; Flags rebuild + origin dirty. Clobbers A.
; WIDTH-RISK: asserts A16/I16; toggles A8 per byte-wide store; exits A16.
.macro sf_mode7_perspective sf_l0, sf_l1, sf_s0, sf_s1, sf_sh, sf_interp, sf_wrap
    rep #$30
    .a16
    .i16
    lda sf_l0
    sep #$20
    .a8
    sta M7_PV_L0
    rep #$20
    .a16
    lda sf_l1
    sep #$20
    .a8
    sta M7_PV_L1
    rep #$20
    .a16
    lda sf_s0
    sta M7_PV_S0
    lda sf_s1
    sta M7_PV_S1
    lda sf_sh
    sta M7_PV_SH
    lda sf_interp
    sep #$20
    .a8
    sta M7_PV_INTERP
    rep #$20
    .a16
    lda sf_wrap
    sep #$20
    .a8
    sta M7_PV_WRAP
    lda #$01
    sta M7_DIRTY_REBUILD
    sta M7_DIRTY_ORIGIN
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_focus scanline — anchor the rotation origin at a scanline.
; -----------------------------------------------------------------------------
;   scanline  16-bit operand, low byte used (0-223). The camera position maps
;             exactly to this scanline's screen center — 192 puts the "car"
;             low in the racing view; 168 is the flight default.
; Flags origin dirty. Clobbers A.
; WIDTH-RISK: asserts A16/I16; A8 for the byte stores; exits A16.
.macro sf_mode7_focus sf_scanline
    rep #$30
    .a16
    .i16
    lda sf_scanline
    sep #$20
    .a8
    sta M7_PV_FOCUS_Y
    lda #$01
    sta M7_DIRTY_ORIGIN
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_scale s0, s1 — set ONLY the perspective scale (the altitude knob).
; -----------------------------------------------------------------------------
;   s0  far-scale  u16 (texel step at the horizon l0 — bigger = ground recedes)
;   s1  near-scale u16 (texel step at the bottom l1 — bigger = ground recedes)
; The scale-only counterpart of sf_mode7_focus: writes M7_PV_S0/S1 and flags
; M7_DIRTY_REBUILD, leaving l0/l1/sh/interp/wrap as the last sf_mode7_perspective
; set them. Designed for a per-frame altitude derive (climb -> bigger s0/s1 ->
; ground recedes; descend -> smaller -> approaches): map an altitude state var to
; s0/s1 in your game loop, call this, then sf_mode7_tick rebuilds. COST NOTE: a
; scale change fires the full ~10k-cycle rebuild every frame it changes (there is
; no scale-only cheap path, unlike sf_mode7_cam's angle knob) — see
; docs/guides/mode7_free_flight.md for the budget caveat.
; Both operands verbatim 16-bit (#imm or DP/abs word). Flags rebuild dirty.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry (the u16 s0/s1 stores stay A16); toggles A8
; only for the 1-byte M7_DIRTY_REBUILD flag; exits A16.
.macro sf_mode7_scale sf_s0, sf_s1
    rep #$30
    .a16
    .i16
    lda sf_s0
    sta M7_PV_S0
    lda sf_s1
    sta M7_PV_S1
    sep #$20
    .a8
    lda #$01
    sta M7_DIRTY_REBUILD
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_flags m7sel — raw screen-repeat / flip control byte.
; -----------------------------------------------------------------------------
;   m7sel  16-bit operand, low byte = the $211A value: bit7-6 = out-of-map
;          behavior (00 wrap, 10 transparent, 11 fill with tile 0),
;          bit1 = flip vertical, bit0 = flip horizontal.
; Committed to $211A by the engine NMI alongside M7X/M7Y. Flags origin dirty.
; Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; A8 for the byte stores; exits A16/I16.
.macro sf_mode7_flags sf_m7sel
    rep #$30
    .a16
    .i16
    lda sf_m7sel
    sep #$20
    .a8
    sta M7_PV_M7SEL
    lda #$01
    sta M7_DIRTY_ORIGIN
    rep #$20
    .a16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_tick — the per-frame Mode 7 service call (put it in your loop).
; -----------------------------------------------------------------------------
; Transcribed from the engine's proven frame dispatcher: skip everything when
; Mode 7 is inactive; run the full HDMA-table rebuild (220-295k master
; clocks = 62-83% of a frame at the shipped parameter sets — see
; pv_rebuild's split entry points when that must share a frame) only when
; the rebuild flag is set (angle/perspective changed); re-anchor the rotation
; origin + scroll shadows (cheap) only when the origin flag is set (camera
; moved); then let the HUD-overlay hook re-stamp its band table if a HUD
; overlay is active (no-op otherwise). Call it once per frame AFTER your
; sf_mode7_cam updates — and once during setup, before screen-on, so the
; first displayed frame already has valid tables.
; Clobbers A, X, Y.
; WIDTH-RISK: A8 flag checks with rep #$30 around each engine JSR (they want
; A16/I16, DP=$0000); every multi-path label below carries an explicit width
; annotation; exits A16/I16 on all paths.
.macro sf_mode7_tick
    .local m7t_check_origin, m7t_hud_check, m7t_skip
    sep #$20
    .a8
    lda M7_PV_ACTIVE
    beq m7t_skip
    lda M7_DIRTY_REBUILD
    beq m7t_check_origin
    rep #$30
    .a16
    .i16
    jsr mode7_build_hdma_tables
    ; G1: re-stamp the per-scanline M7A barrel curve over the freshly-built
    ; AB buffer (no-op when no barrel is armed). MUST run every rebuild, since
    ; pv_rebuild rewrites M7A from scratch into the flipped double-buffer.
    jsr mode7_barrel_apply
    sep #$20
    .a8
    stz M7_DIRTY_REBUILD
m7t_check_origin:
    .a8
    lda M7_DIRTY_ORIGIN
    beq m7t_hud_check
    rep #$30
    .a16
    .i16
    jsr mode7_set_origin
    sep #$20
    .a8
    stz M7_DIRTY_ORIGIN
m7t_hud_check:
    .a8
    lda M7_HUD_ACTIVE
    beq m7t_skip
    rep #$30
    .a16
    .i16
    jsr mode7_hud_apply
    sep #$20
    .a8
m7t_skip:
    .a8
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_project obj_x, obj_y, cam_x, cam_y — project a ground point.
; -----------------------------------------------------------------------------
; Marshals the four world coordinates into the projection API block (DP $48-$4F)
; and calls mode7_project (engine/mode7_project.asm). Operands are passed
; verbatim into 16-bit loads, so each accepts #imm, a DP slot, or an abs word.
;
; After the call, read the results from the projection block:
;   PROJ_SX     $50  screen x (s16; cull if < -16 or > 256)
;   PROJ_SY     $52  screen scanline (low byte)
;   PROJ_TIER   $54  size tier 0..3 (low byte; 0 = nearest/largest)
;   PROJ_CULLED $56  0 = visible, nonzero = behind camera or past the far edge
;
; Requires: engine/mode7_project.asm linked + the generated mode7_project.inc.
; Clobbers A, X, Y and the math scratch ($B0-$BF). Does NOT disturb the per-
; frame Mode 7 projection scratch, so it is safe in the game loop.
; WIDTH-RISK: asserts A16/I16 entry; mode7_project toggles I8 internally and
; exits A16/I16.
.macro sf_mode7_project sf_ox, sf_oy, sf_cx, sf_cy
    rep #$30
    .a16
    .i16
    lda sf_ox
    sta z:PROJ_OBJ_X
    lda sf_oy
    sta z:PROJ_OBJ_Y
    lda sf_cx
    sta z:PROJ_CAM_X
    lda sf_cy
    sta z:PROJ_CAM_Y
    jsr mode7_project
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_sky_split horizon, table_addr — reveal the sky above the horizon.
; -----------------------------------------------------------------------------
; Call ONCE during setup (after sf_mode7_on, A16/I16 entry). Generalises the
; racer's arm_sky_split: builds a 2-band $212C (TM) HDMA table that turns BG1
; OFF for the first `horizon` scanlines (so the CGRAM[0] sky backdrop shows in
; that band — reserve index 0 as a sky colour in your asset generator) and ON
; below it (so the Mode 7 floor renders). OBJ stays ON in BOTH bands, so a
; fixed-screen HUD or the centred avatar still draws above the horizon too.
;
;   horizon     8-bit operand (low byte used): the scanline the floor BEGINS at
;               — pass the SAME value as sf_mode7_perspective's l0. The sky band
;               is lines 0..horizon-1; the floor is horizon..bottom. Must be in
;               $01..$80 (the per-band count is a 7-bit HDMA repeat count).
;   table_addr  a 5-byte scratch address in WRAM bank $7E (e.g. $7E0000+$2010).
;               The macro writes the band table there; it must persist (the NMI
;               re-arms the channel from it every VBlank), so use a fixed
;               game-WRAM slot, not transient DP scratch.
;
; Mechanism: a 2-band TM table on CH2 (the channel the legacy allocator pins as
; an idle placeholder, so effect builders index from CH3 — here it earns its
; keep). The macro programs CH2's DMA registers DIRECTLY and ORs its bit into
; NMI_HDMA_ENABLE; the engine NMI then re-arms $420C every VBlank but leaves
; CH2's hardware config alone (CH2 is NOT Mode-7-owned, so the ownership gate in
; nmi_handler.asm passes it through untouched). This mirrors how gradient_rgb
; drives its non-Mode-7 channels. Budget: CH2 here + CH5/6 matrix leaves CH0/1/
; 3/4/7 free for a sky gradient or other effects.
;
; HDMA table shape (3 entries):
;   [horizon, $10]  lines 0..horizon-1 -> TM=$10 (OBJ on, BG1 off): the sky
;   [ 1,      $11]  line horizon       -> TM=$11 (BG1 + OBJ): the floor begins
;   [ 0          ]  terminator         -> TM holds $11 for the rest of the frame
;
; Clobbers A, X. Requires NMI_HDMA_ENABLE in scope (engine_state.inc).
; WIDTH-RISK: entry A16/I16. Sets A8 (sep #$20) for the byte writes to the table
; + $43xx + the NMI_HDMA_ENABLE RMW; keeps I16; restores caller width via PLP.
.macro sf_mode7_sky_split sf_horizon, sf_table
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ; --- build the 2-band TM table in WRAM (sf_table, 5 bytes) ---
    ldx #$0000
    lda sf_horizon              ; horizon lines, non-repeat (bit7=0)
    sta f:sf_table + 0, x
    lda #$10                    ; band 1: BG1 off, OBJ on (the sky backdrop)
    sta f:sf_table + 1, x
    lda #$01                    ; 1 line, non-repeat
    sta f:sf_table + 2, x
    lda #$11                    ; band 2: BG1 + OBJ (the Mode 7 floor)
    sta f:sf_table + 3, x
    lda #$00                    ; terminator (stz has no abs-long mode)
    sta f:sf_table + 4, x
    ; --- configure CH2 DMA registers directly (non-Mode-7-owned) ---
    lda #$00
    sta $4320                   ; DMAP2: A->B, absolute table, 1 byte -> 1 reg
    lda #$2C
    sta $4321                   ; BBAD2: $212C (TM)
    lda #<sf_table
    sta $4322                   ; A1T2L
    lda #>sf_table
    sta $4323                   ; A1T2H
    lda #^sf_table
    sta $4324                   ; A1B2 (table bank)
    ; --- arm CH2 in the NMI HDMA enable mask (additive; pv_rebuild ORs too) ---
    lda NMI_HDMA_ENABLE
    ora #$04
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
.endmacro

.endif ; SF_MODE7_INC
