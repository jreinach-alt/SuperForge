; =============================================================================
; mode7_engine.asm — Mode 7 PPU Register Management (Phase 16-0a Brad port)
; =============================================================================
; Implements Mode 7 initialization, static affine transform, disable, and
; VRAM upload routines.
;
; Phase 16-0a rewrite: mode7_init + mode7_disable operate on the new
; ES_M7_PV_* engine-state block (Brad's pv_* trapezoid parameters). The
; old $89-$A6 Mode 7 state block stays in engine_state.inc for legacy
; engine compatibility but is not touched here — the live Brad renderer
; uses the new block exclusively.
;
; Routines:
;   mode7_init        — Initialize Brad-port Mode 7 state and PPU registers
;   mode7_set_static  — Write a static affine transform (no HDMA/perspective)
;   mode7_disable     — Turn off Mode 7, restore previous BGMODE
;   mode7_vram_upload — Upload interleaved tilemap+tileset to VRAM via DMA
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
;
; Cross-ref: engine_state.inc (ES_M7_PV_* block), mode7_nmi.inc (VBlank
;            commit), mode7_sin_lut.inc, engine/mode7_hdma.asm (pv_rebuild
;            / pv_set_origin — added in steps 4-6 of 16-0a).
;            NOTE: mode7_perspective_lut.inc is NO LONGER referenced by
;            the live engine as of 16-0a. It is still used by
;            mode7_*_legacy.asm (the frozen Phase 8/8T/14/15 engine).
; =============================================================================

; Phase 17-1 guard: tells bg_mode_engine.asm's gfxmode(7) dispatch path that
; mode7_init is available to JSR. ROMs that include mode7_engine.asm before
; bg_mode_engine.asm get the full Mode 7 PPU init via gfxmode(7); ROMs that
; only include bg_mode_engine.asm (e.g., 17-1 Mode 0 demo) get a minimal
; BGMODE-only stub for the gfxmode(7) path.
MODE7_ENGINE_PROVIDES_INIT = 1

; Phase 17-13 — Mode 7 HDMA allocator wrapper. Provides
; mode7_hdma_alloc_request / _release / _claim_extra / _release_extra
; entry points used by the routines below. Depends on hdma_alloc.asm
; symbols (hdma_alloc_bootstrap, hdma_release) which the parent .asm
; includes before mode7_engine.asm — see Phase 17-13 design doc.
.include "mode7_hdma_allocator.asm"

; Mode 7 PPU register addresses
M7SEL_REG    = $211A    ; Mode 7 settings (repeat, flip)
M7A_REG      = $211B    ; Matrix parameter A (cosA * scaleX) — write-twice
M7B_REG      = $211C    ; Matrix parameter B (sinA * scaleX) — write-twice
M7C_REG      = $211D    ; Matrix parameter C (-sinA * scaleY) — write-twice
M7D_REG      = $211E    ; Matrix parameter D (cosA * scaleY) — write-twice
M7X_REG      = $211F    ; Rotation center X — write-twice
M7Y_REG      = $2120    ; Rotation center Y — write-twice
M7HOFS_REG   = $210D    ; Mode 7 H scroll (shared with BG1HOFS) — write-twice
M7VOFS_REG   = $210E    ; Mode 7 V scroll (shared with BG1VOFS) — write-twice

; Default values for Brad-port Mode Y boot state.
; Matches tests/phase8/mode7_diz_phase8.asm at HEIGHT_DEFAULT=26
; (the Phase 8 Dizworld reference). Users override via mode7_perspective
; / mode7_camera / mode7_focus before calling mode7_on().
M7_PV_DEFAULT_L0     = 45       ; horizon scanline (from 32 + 26/2)
M7_PV_DEFAULT_L1     = 224      ; bottom scanline (Brad's convention)
M7_PV_DEFAULT_S0     = 436      ; far-scale (from 384 + 2*26)
M7_PV_DEFAULT_S1     = 77       ; near-scale (from 64 + 26/2)
M7_PV_DEFAULT_SH     = 0        ; auto / SA=1 path (Mode Y)
M7_PV_DEFAULT_INTERP = 2        ; 2x interpolation
M7_PV_DEFAULT_WRAP   = 1        ; map wrapping
M7_PV_DEFAULT_FOCUS  = 168      ; MODE_Y_SY (Brad's camera focus scanline)

; Identity matrix coefficients (1.0 in Mode 7 format = $0100)
M7_IDENTITY_COEFF   = $0100   ; 1.0 in signed 1.7.8 format


; =============================================================================
; mode7_init — Initialize Brad-port Mode 7 state and PPU registers
; =============================================================================
; Saves the current BGMODE, switches to Mode 7, initializes pv_* state to
; Mode-Y-boot-state defaults, configures PPU registers for Mode 7, and
; flags both rebuild + origin dirty so frame_lifecycle's first BUILD-phase
; call will compute fresh HDMA tables.
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A, X
; =============================================================================
mode7_init:
    .a16
    .i16

    ; Save current gfxmode before switching to Mode 7
    sep #$20
    .a8
    lda SHADOW_BGMODE
    sta M7_PV_PREV_GFXMODE

    ; Set Brad-port Mode 7 active flag
    lda #$01
    sta M7_PV_ACTIVE

    ; Flag both dirty bits so BUILD phase builds fresh tables + origin
    sta M7_DIRTY_REBUILD
    sta M7_DIRTY_ORIGIN

    ; Initialize double-buffer index to 0 (first build writes to buffer A)
    stz M7_PV_BUFFER

    ; Phase 17-11: clear HUD overlay state on Mode 7 (re-)init for
    ; defense-in-depth. Parent-built ROMs already get this from
    ; the parent build's WRAM-clear DMA at RESET; ASM ROMs
    ; that bypass the bootstrap rely on this clear.
    stz M7_HUD_ACTIVE
    stz M7_HUD_HEIGHT

    ; Set pv_* defaults (Mode Y boot state)
    lda #M7_PV_DEFAULT_L0
    sta M7_PV_L0
    lda #M7_PV_DEFAULT_L1
    sta M7_PV_L1
    lda #M7_PV_DEFAULT_INTERP
    sta M7_PV_INTERP
    lda #M7_PV_DEFAULT_WRAP
    sta M7_PV_WRAP
    lda #M7_PV_DEFAULT_FOCUS
    sta M7_PV_FOCUS_Y
    stz M7_PV_ANGLE             ; angle = 0
    stz M7_PV_M7SEL             ; no repeat, no flip

    ; Set BGMODE shadow to $07 (Mode 7)
    lda #$07
    sta SHADOW_BGMODE

    ; Write BGMODE directly to PPU for immediate effect during forced blank
    ; (NMI will also commit this from the shadow register)
    sta $2105

    rep #$20
    .a16

    ; Set 16-bit pv_* params
    lda #M7_PV_DEFAULT_S0
    sta M7_PV_S0
    lda #M7_PV_DEFAULT_S1
    sta M7_PV_S1
    lda #M7_PV_DEFAULT_SH
    sta M7_PV_SH

    ; Set camera position to map center: posx = posy = 512 (integer part).
    ; posx/posy are 4-byte 16.16 fixed-point (bytes 0-1 = fraction, 2-3 = integer).
    ; Brad reads posx+2 as a 16-bit integer (`lda z:posx+2` in .a16 mode),
    ; so the integer part must live as a clean 16-bit value at byte offset 2-3.
    stz M7_PV_POSX + 0          ; fraction low = 0
    stz M7_PV_POSY + 0
    lda #$0200                  ; integer = 512
    sta M7_PV_POSX + 2
    sta M7_PV_POSY + 2

    ; Write M7SEL to PPU
    lda M7_PV_M7SEL
    sta M7SEL_REG

    ; Write rotation center (M7X/M7Y) to screen center temporarily —
    ; pv_set_origin will overwrite with Brad-derived values on first BUILD.
    stz M7X_REG                 ; low byte
    stz M7X_REG                 ; high byte
    stz M7Y_REG                 ; low byte
    stz M7Y_REG                 ; high byte

    ; Set identity matrix by default (A=1.0, B=0, C=0, D=1.0) — pv_rebuild
    ; replaces this with per-scanline values via HDMA on first BUILD.
    ; M7A ($211B): $0100 (1.0)
    lda #<M7_IDENTITY_COEFF
    sta M7A_REG
    lda #>M7_IDENTITY_COEFF
    sta M7A_REG

    ; M7B ($211C): $0000 (0.0)
    stz M7B_REG
    stz M7B_REG

    ; M7C ($211D): $0000 (0.0)
    stz M7C_REG
    stz M7C_REG

    ; M7D ($211E): $0100 (1.0)
    lda #<M7_IDENTITY_COEFF
    sta M7D_REG
    lda #>M7_IDENTITY_COEFF
    sta M7D_REG

    ; Set Mode 7 scroll to 0 (pv_set_origin writes shadow scrolls each frame)
    stz M7HOFS_REG
    stz M7HOFS_REG
    stz M7VOFS_REG
    stz M7VOFS_REG

    ; Update TM shadow: Mode 7 uses BG1 (bit 0). Keep OBJ (bit 4) if enabled.
    lda SHADOW_TM
    and #$10                ; preserve OBJ bit
    ora #$01                ; enable BG1 for Mode 7
    sta SHADOW_TM

    ; Initialize WRAM 1-byte HDMA indirect sources (consumed by CH4 TM and
    ; CH7 COLDATA indirect). The indirect-data bank for those channels is
    ; $7E, so pv_tm_bg1obj/pv_tm_bg2obj/pv_fade_black must live in WRAM.
    lda #$11
    sta f:$7E0000 + $3600       ; pv_tm_bg1obj = TM BG1+OBJ
    lda #$12
    sta f:$7E0000 + $3601       ; pv_tm_bg2obj = TM BG2+OBJ
    lda #$E0
    sta f:$7E0000 + $3602       ; pv_fade_black = COLDATA zero

    ; Phase 17-13: pin Mode 7's default channel set (CH5+CH6) in the
    ; allocator AND set M7_OWNED_MASK. M7_OWNED_MASK is the single source
    ; of truth read by the engine NMI handler (engine/nmi_handler.asm
    ; Phase 5) to gate per-channel shadow→hardware commits — Brad's
    ; vestigial CH3/CH4/CH7 shadow writes from pv_rebuild become inert
    ; for non-Mode-7-owned channels because the NMI ownership gate skips
    ; them. See docs/sprints/phase_17_13_mode7_allocator.md.
    rep #$30
    .a16
    .i16
    jsr mode7_hdma_alloc_request

    rep #$20
    .a16
    rts


; =============================================================================
; mode7_set_static — Write a static affine transform (no perspective HDMA)
; =============================================================================
; Sets the Mode 7 matrix parameters A, B, C, D directly from the API block.
; For static (non-perspective) Mode 7, these values are committed to the PPU
; during VBlank by mode7_nmi.inc. No HDMA is used.
;
; Parameters (in API block, DP-relative):
;   $60 (API_P0): Matrix A coefficient (signed 1.7.8 fixed-point)
;   $62 (API_P1): Matrix B coefficient
;   $64 (API_P2): Matrix C coefficient
;   $66 (API_P3): Matrix D coefficient
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A
; =============================================================================

; API block parameter offsets (DP $60+ as defined in engine layout)
M7_API_PARAM_A = $60
M7_API_PARAM_B = $62
M7_API_PARAM_C = $64
M7_API_PARAM_D = $66

mode7_set_static:
    .a16
    .i16

    ; Write matrix A ($211B) — write-twice: low byte, then high byte
    sep #$20
    .a8
    lda M7_API_PARAM_A          ; low byte of A
    sta M7A_REG
    lda M7_API_PARAM_A + 1      ; high byte of A
    sta M7A_REG

    ; Write matrix B ($211C)
    lda M7_API_PARAM_B
    sta M7B_REG
    lda M7_API_PARAM_B + 1
    sta M7B_REG

    ; Write matrix C ($211D)
    lda M7_API_PARAM_C
    sta M7C_REG
    lda M7_API_PARAM_C + 1
    sta M7C_REG

    ; Write matrix D ($211E)
    lda M7_API_PARAM_D
    sta M7D_REG
    lda M7_API_PARAM_D + 1
    sta M7D_REG

    rep #$20
    .a16
    rts


; =============================================================================
; mode7_disable — Turn off Mode 7 and restore previous graphics mode
; =============================================================================
; Restores the BGMODE that was active before mode7_init was called.
; Clears the M7_ACTIVE flag and disables any Mode 7 HDMA channels.
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A
; =============================================================================
mode7_disable:
    .a16
    .i16
    sep #$20
    .a8

    ; Clear Brad-port Mode 7 active flag
    stz M7_PV_ACTIVE

    ; Phase 17-11: clear HUD overlay flag — mode7_hud requires Mode 7 active.
    stz M7_HUD_ACTIVE

    ; Restore previous BGMODE
    lda M7_PV_PREV_GFXMODE
    sta SHADOW_BGMODE

    ; Clear M7SEL register shadow
    stz M7_PV_M7SEL

    ; Clear dirty flags
    stz M7_DIRTY_REBUILD
    stz M7_DIRTY_ORIGIN

    ; Disable Mode 7 HDMA channels by clearing the HDMA enable mask
    ; (Mode 7 and standard HDMA effects are mutually exclusive, so
    ; clearing the mask effectively disables all Mode 7 HDMA.)
    ; Note: standard HDMA effects should be re-enabled separately
    ; by the caller if needed.
    stz NMI_HDMA_ENABLE

    ; Restore TM to a sensible default: BG1+BG2+BG3+OBJ for Mode 1
    lda #$17                    ; bits 0,1,2,4 = BG1+BG2+BG3+OBJ
    sta SHADOW_TM

    ; Phase 17-13: release Mode 7's default channels (CH5+CH6) and clear
    ; their bits from M7_OWNED_MASK. mode7_hdma_alloc_release wraps
    ; hdma_release + the M7_OWNED_MASK bookkeeping the engine NMI uses to
    ; ownership-gate shadow commits. Defensive CH3 release covers the
    ; case where mode7_hud was active but mode7_hud_off wasn't called
    ; before mode7_disable — idempotent on already-released channels.
    rep #$30
    .a16
    .i16
    jsr mode7_hdma_alloc_release
    lda #$0008                  ; bitmask: CH3 (HUD overlay)
    jsr mode7_hdma_release_extra

    rep #$20
    .a16
    rts


; =============================================================================
; mode7_vram_upload — Upload interleaved tilemap+tileset data to VRAM via DMA
; =============================================================================
; Mode 7 VRAM is interleaved: even bytes are tilemap, odd bytes are tile data.
; This routine sets VRAM address to $0000 (word increment mode, 1-word step)
; and DMA-transfers the pre-interleaved data directly.
;
; Parameters (in API block, DP-relative):
;   $60 (API_P0): Source address (16-bit, low word within bank)
;   $62 (API_P1): Source bank byte (low byte only)
;   $64 (API_P2): Transfer size in bytes (16-bit)
;
; Must be called during forced blank (INIDISP bit 7 set) or VBlank.
; Call convention: A16, I16 on entry and exit.
; Modifies: A, X
; =============================================================================

M7_VRAM_API_SRC_ADDR = $60
M7_VRAM_API_SRC_BANK = $62
M7_VRAM_API_SIZE     = $64

mode7_vram_upload:
    .a16
    .i16

    ; Set VRAM address to $0000 (word address)
    ; VMAIN ($2115): increment mode — increment after writing $2119 (high byte)
    ;   bit 7 = 1: increment after high byte write
    ;   bits 1-0 = 00: increment by 1 word
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: increment after $2119, step 1 word

    rep #$20
    .a16
    stz $2116                   ; VMADDL/H: VRAM word address = $0000

    ; Configure DMA channel 1 for VRAM transfer
    ; DMAP: mode $01 (two bytes: write to $2118 then $2119, word pair)
    sep #$20
    .a8
    lda #$01                    ; Transfer mode 1: two regs (low/high)
    sta $4310                   ; DMAP1

    lda #$18                    ; BBAD: destination = $2118 (VMDATAL)
    sta $4311                   ; BBAD1

    ; Source address
    rep #$20
    .a16
    lda M7_VRAM_API_SRC_ADDR
    sta $4312                   ; A1T1L/H: source address

    sep #$20
    .a8
    lda M7_VRAM_API_SRC_BANK
    sta $4314                   ; A1B1: source bank

    ; Transfer size
    rep #$20
    .a16
    lda M7_VRAM_API_SIZE
    sta $4315                   ; DAS1L/H: transfer size

    ; Execute DMA on channel 1
    sep #$20
    .a8
    lda #$02                    ; Enable channel 1 (bit 1)
    sta $420B                   ; MDMAEN: trigger DMA

    rep #$20
    .a16
    rts


; =============================================================================
; Phase 17-11 — Mode 7 floor + Mode 1 HUD overlay
; =============================================================================
; Adds a single HDMA channel (CH3) on top of Brad's Mode 7 port, switching
; BGMODE from Mode 7 to Mode 1 at a configurable scanline so a HUD bar can
; render with normal Mode 1 BGs while the upper region keeps the Mode 7
; perspective floor.
;
; Mechanism: Brad's pv_rebuild writes a 16-byte BGMODE stub at CH3 each
; frame ("Mode 7 across all 224 scanlines"). After mode7_build_hdma_tables
; returns, mode7_hud_apply rewrites a per-scanline-encoded BGMODE table at
; SPLIT_HDMA_TABLE ($7E:C8A0), overrides Brad's CH3 TBL_LO/HI to point at
; that table, and ORs CH3 ($08) into NMI_HDMA_ENABLE. Brad's CH3 DMAP=$00
; / BBAD=$05 register pair is correct as-is.
;
; Per-scanline encoding:
;   [$80 | floor_lines, $07 × floor_lines, $80 | hud_height, $01 × hud_height, $00]
; This is the empirically validated Phase 17-9 BGMODE encoding (see
; tests/phase17/HANDOFF.md "Visible demo findings"). Up to 256 bytes,
; comfortably inside the SPLIT_HDMA_TABLE allocation ($7E:C8A0-$C99F).
;
; Phase 17-13 will replace the raw CH3 override with allocator-managed
; channel ownership; until then, this is an explicit narrow-scoped break
; from R-06 ("Mode 7 + standard HDMA mutually exclusive") that adds only
; the BGMODE band switch, no gradient/wave/iris.
;
; Cycle budget: ≤700 cycles for typical HUD heights (table write ~226
; bytes + register overrides + enable OR). Well inside the post-build
; envelope.
; =============================================================================

.ifndef API_BLOCK_BASE
API_BLOCK_BASE  = $60
.endif


; =============================================================================
; engine_mode7_hud — Activate Mode 7 floor + Mode 1 HUD overlay
; =============================================================================
; Engine fn: mode7_hud(height) — ID 93.
; Stages active flag + HUD height; the per-frame mode7_hud_apply hook does
; the table build and CH3 override. Pins CH3 in the HDMA allocator so other
; effects (gradient_rgb, wave, iris) can't claim it while the overlay is
; active — without this pin the allocator hands CH3 out as if free, then
; mode7_hud_apply silently overwrites whatever the other effect wrote.
;
; Param: API_BLOCK_BASE + $00 = HUD band height in scanlines (low byte).
;        Valid range 1..223. Out-of-range rejects with no state changes.
;
; Returns ENGINE_A0 = $0000 on accepted, $FFFF on rejected (height < 1
; or height >= 224 — 224 means "entire screen Mode 1" which contradicts
; Mode 7 active).
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A, X.
; =============================================================================
engine_mode7_hud:
    .a16
    .i16
    sep #$20
    .a8
    lda API_BLOCK_BASE + $00
    cmp #1
    bcc @reject                         ; height < 1 → reject
    cmp #224
    bcs @reject                         ; height >= 224 → reject
    sta M7_HUD_HEIGHT
    lda #$01
    sta M7_HUD_ACTIVE

    ; Phase 17-13: pin CH3 in the allocator AND add it to M7_OWNED_MASK
    ; via the wrapper. The engine NMI's ownership gate then commits the
    ; CH3 BGMODE shadow that mode7_hud_apply writes. Idempotent —
    ; re-calling mode7_hud(N) twice in a row OR's the same bit.
    rep #$30
    .a16
    .i16
    lda #$0008                          ; CH3 bit
    ldx #HDMA_EFFECT_MODE7_HUD_BGMODE
    jsr mode7_hdma_claim_extra
    rep #$20
    .a16
    lda #$0000                          ; ENGINE_A0 = 0 (accepted)
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@reject:
    rep #$30
    .a16
    .i16
    lda #$FFFF                          ; ENGINE_A0 = $FFFF (rejected)
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts


; =============================================================================
; engine_mode7_hud_off — Deactivate the HUD overlay
; =============================================================================
; Engine fn: mode7_hud_off() — ID 94.
; Clears the active flag, the CH3 bit in NMI_HDMA_ENABLE, AND releases CH3
; in the HDMA allocator (paired with hdma_alloc_bootstrap in engine_mode7_hud).
; Brad's CH5+CH6 matrix HDMA stays enabled; mode7_disable handles full Mode 7
; teardown including CH5+CH6 release.
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A, X, Y.
; =============================================================================
engine_mode7_hud_off:
    .a16
    .i16
    sep #$20
    .a8
    stz M7_HUD_ACTIVE

    ; Clear CH3 bit (mask = $F7 = ~$08) — additive, leaves CH5+CH6 set.
    lda NMI_HDMA_ENABLE
    and #$F7
    sta NMI_HDMA_ENABLE

    ; Phase 17-13: release CH3 in the allocator AND clear its bit from
    ; M7_OWNED_MASK so the engine NMI stops ownership-gating commits for
    ; it. Other effects can now claim CH3 cleanly via hdma_request.
    rep #$30
    .a16
    .i16
    lda #$0008                          ; CH3 bit
    jsr mode7_hdma_release_extra

    rep #$20
    .a16
    rts


; =============================================================================
; mode7_hud_apply — Per-frame post-build hook (Phase 17-11)
; =============================================================================
; Called once per frame *after* mode7_build_hdma_tables. No-op when
; M7_HUD_ACTIVE = 0. When active, builds the per-scanline BGMODE table at
; SPLIT_HDMA_TABLE, overrides Brad's CH3 register block, and ORs CH3 into
; NMI_HDMA_ENABLE.
;
; Wired into the parent build's mode7_tick (right after pv_rebuild). ASM
; templates call this directly from their main loop after mode7_build_hdma_tables.
;
; WIDTH-RISK: enters A16/I16 (post-pv_rebuild contract). Toggles A-width
; for the byte-write loops. All branch targets reached after a width
; change carry explicit .a8/.a16/.i16 annotations. Exits A16/I16 to match
; the caller's expectation.
;
; DB note: pv_rebuild restores DB to caller's value (typically $00) on
; exit. Long-mode `sta f:$7E0000 + addr, x` writes use the absolute-long
; opcode regardless of DB. CH3 register-state writes (HDMA_CH3_*) are
; absolute (DB-relative), targeting $0152-$0155 which is bank $00 — safe
; with DB=$00.
;
; Call convention: A16, I16 on entry and exit.
; Modifies: A, X, Y.
; =============================================================================
mode7_hud_apply:
    .a16
    .i16
    sep #$20
    .a8
    lda M7_HUD_ACTIVE
    bne :+
    rep #$20
    .a16
    rts
:
    .a8
    ldx #0                              ; X = byte offset into table (.i16)

    ; --- Band 1: sky (pv_l0 scanlines of Mode 1, $01) -----------------
    ; Brad's pv_rebuild only emits per-scanline matrix HDMA from pv_l0
    ; downward; above pv_l0, Mode 7's matrix registers retain residual
    ; identity values, rendering the BG1 tilemap untransformed (a flat
    ; overhead view of the racing tiles, not a sky). 17-11 covers the
    ; gap by switching BGMODE to Mode 1 above pv_l0 — Mode 1 BG1 reads
    ; from BG12NBA-pointed chr (set by the template to empty VRAM), so
    ; the above-horizon region renders as solid CGRAM[0] backdrop.
    ;
    ; Sprint 16-3-5 will land Mode 1 + BG2 cloud parallax above pv_l0;
    ; what 17-11 ships here is the BGMODE switch only. The two compose
    ; cleanly (16-3-5 adds CH4 TM + BG2 chr; the BGMODE table layout
    ; doesn't change).
    lda M7_PV_L0                        ; sky band size in scanlines
    pha                                 ; [sky_remaining]
@sky_group:
    lda 1, S                            ; sky_remaining
    cmp #128
    bcc @sky_small

    ; Big group: emit $FF (= $80|127, repeat-set) + 127 copies of $01.
    lda #$FF
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    ldy #127
    sep #$20
    .a8
    lda #$01
@sky_big_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @sky_big_fill
    ; sky_remaining -= 127
    .a8
    lda 1, S
    sec
    sbc #127
    sta 1, S
    bra @sky_group

@sky_small:
    .a8
    ; If sky_remaining == 0 (e.g. pv_l0 == 0 — fully on-the-floor camera),
    ; skip the small group entirely.
    lda 1, S
    beq @sky_done
    ora #$80                            ; $80|count, repeat-set
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    lda 1, S
    and #$00FF
    tay
    sep #$20
    .a8
    lda #$01
@sky_small_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @sky_small_fill

@sky_done:
    pla                                 ; discard sky_remaining

    ; --- Band 2: floor (224 - pv_l0 - hud_height) lines of Mode 7 ($07) ---
    ; HDMA count field is 7 bits (1..127); a >127-line band must split
    ; into multiple groups. Pattern follows engine/mode_split_hdma.asm
    ; @group_loop: emit `[$FF, $07×127]` chunks while remaining >= 128,
    ; then a single small group `[$80|remaining, $07×remaining]`.
    lda #224
    sec
    sbc M7_PV_L0                        ; subtract sky band
    sec
    sbc M7_HUD_HEIGHT                   ; subtract HUD band
    pha                                 ; [floor_remaining]
@floor_group:
    lda 1, S                            ; floor_remaining (top of stack)
    cmp #128
    bcc @floor_small

    ; Big group: emit $FF (= $80|127, repeat-set) + 127 copies of $07.
    lda #$FF
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    ldy #127
    sep #$20
    .a8
    lda #$07
@floor_big_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @floor_big_fill
    ; floor_remaining -= 127
    .a8
    lda 1, S
    sec
    sbc #127
    sta 1, S
    bra @floor_group

@floor_small:
    .a8
    ; If floor_remaining == 0 we're done with the floor band.
    lda 1, S
    beq @floor_done
    ora #$80                            ; $80|count, repeat-set
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    lda 1, S
    and #$00FF
    tay
    sep #$20
    .a8
    lda #$07
@floor_small_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @floor_small_fill

@floor_done:
    pla                                 ; discard floor_remaining

    ; --- Band 2: HUD (hud_height lines of Mode 1, $01) ---
    ; Same multi-group pattern in case HUD_HEIGHT > 127.
    lda M7_HUD_HEIGHT
    pha                                 ; [hud_remaining]
@hud_group:
    lda 1, S
    cmp #128
    bcc @hud_small

    lda #$FF
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    ldy #127
    sep #$20
    .a8
    lda #$01
@hud_big_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @hud_big_fill
    .a8
    lda 1, S
    sec
    sbc #127
    sta 1, S
    bra @hud_group

@hud_small:
    .a8
    lda 1, S
    beq @hud_done
    ora #$80
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    rep #$20
    .a16
    lda 1, S
    and #$00FF
    tay
    sep #$20
    .a8
    lda #$01
@hud_small_fill:
    .a8
    .i16
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x
    inx
    dey
    bne @hud_small_fill

@hud_done:
    pla                                 ; discard hud_remaining

    ; --- Terminator ($00) — STZ has no long-form, use lda/sta ---
    .a8
    lda #$00
    sta f:$7E0000 + SPLIT_HDMA_TABLE, x

    ; --- Override Brad's CH3 register block ---
    ; CH3 DMAP/BBAD already match what Brad's pv_rebuild writes; we set
    ; them defensively in case a caller invokes mode7_hud_apply before
    ; pv_rebuild has run for this frame.
    lda #$00                            ; direct 1-byte transfer (mode 0)
    sta HDMA_CH3_DMAP
    lda #$05                            ; BBAD: $2105 (BGMODE)
    sta HDMA_CH3_BBAD
    rep #$20
    .a16
    lda #SPLIT_HDMA_TABLE
    sta HDMA_CH3_TBL_LO                 ; 16-bit store covers TBL_LO + TBL_HI

    ; --- OR CH3 into NMI_HDMA_ENABLE additively ---
    sep #$20
    .a8
    lda NMI_HDMA_ENABLE
    ora #$08                            ; CH3 bit
    sta NMI_HDMA_ENABLE

    rep #$20
    .a16
    rts
