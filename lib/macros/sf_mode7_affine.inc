; =============================================================================
; sf_mode7_affine.inc — whole-plane STATIC affine Mode 7 (macro library)
; =============================================================================
; The OTHER Mode 7 front door. Where sf_mode7.inc drives a per-scanline
; PERSPECTIVE FLOOR (HDMA rewrites the matrix every scanline for a road/sky
; view), THIS group drives a single UNIFORM affine matrix over the WHOLE plane:
; the Mode 7 BG scales and rotates as one rigid image around a pivot. That is
; the "boss IS the BG" technique — the hardware scales/rotates the boss for
; free; the player and attacks are SPRITES composited over it (the affine
; matrix never touches OBJ).
;
; WHY A SECOND PRIMITIVE: a uniform static matrix costs ~50 cycles/frame (a
; dozen register writes via mode7_set_static) — there is NO per-scanline HDMA,
; so none of the ~10k-cycle perspective-table rebuild and none of CH5/CH6 are
; used. A scaling/rotating boss is therefore nearly free on the cycle budget.
;
; THE ARCHITECTURE IN 3 LINES (who commits what):
;   1. Main thread: sf_boss_matrix computes M7A-M7D from (scale, angle) and
;      writes them DIRECTLY ($211B-$211E) via the engine's mode7_set_static.
;      Call it FIRST thing after sf_frame_begin (before active display), so the
;      whole visible frame reads one consistent matrix — the Phase-14-proven
;      placement; no tearing because M7A-D are latched before scanline 0.
;   2. The stock engine NMI (mode7_nmi.inc, gated on M7_PV_ACTIVE) commits
;      M7SEL/M7X/M7Y from shadows and the BG1 scroll shadows to $210D/$210E
;      (write-twice = the Mode 7 13-bit scroll protocol). sf_boss_mode7_on sets
;      M7_PV_ACTIVE=1 purely to enable that commit — NO perspective HDMA is
;      armed (NMI_HDMA_ENABLE stays 0).
;   3. A kit boss ROM therefore needs NO custom NMI handler: the stock
;      engine/nmi_handler.asm covers M7SEL/M7X/M7Y + scroll; the main thread
;      covers the matrix. This is deliberately the path that AVOIDS the
;      canonical silent-BRK NMI tilemap-swap region (Phase 14-3 corruption).
;
; ENGINE LINK PARTNERS — the template must link (CODE segment), in this order:
;   .include "engine_state.inc"   ; equates (top of file)
;   ...
;   mode7_sin_lut:
;       .include "mode7_sin_lut.inc"   ; defines sin_lut: used by sincos
;   .include "mode7_math.asm"          ; sincos + smul16 (matrix trig+multiply)
;   .include "mode7_engine.asm"        ; mode7_set_static (M7A-D writer)
;
; MUTEX: identical to sf_mode7.inc — Mode 7 repurposes BG1 + VRAM wholesale.
;
; DP SCRATCH: sf_boss_matrix uses mode7_math's scratch (math_a/b/p $B0-$BF,
; cosa/sina $C8-$CB, diz_temp $CC) — engine-claimed transient, never live
; across the macro. Game DP ($32-$5F) is untouched.
; =============================================================================

.ifndef SF_MODE7_AFFINE_INC
SF_MODE7_AFFINE_INC = 1

.include "engine_api.inc"

; The matrix multiply below references mode7_math.asm's DP scratch (math_a/b/p,
; cosa/sina) and the sincos/smul16 routines. Those symbols are defined where
; mode7_math.asm is .include'd in the template (after this file); ca65's
; two-pass resolution makes them visible inside the macro expansion. Do NOT
; redefine them here — that would collide with mode7_math.asm.

; -----------------------------------------------------------------------------
; sf_boss_mode7_on — switch to Mode 7 for a STATIC whole-plane affine boss.
; -----------------------------------------------------------------------------
; Sets BGMODE=7, TM=BG1+OBJ, M7SEL (wrap, no flip), and M7_PV_ACTIVE=1 so the
; stock NMI commits M7SEL/M7X/M7Y + scroll. Does NOT arm any HDMA and does NOT
; pin CH5/CH6 (unlike sf_mode7_on / mode7_init). Installs an identity matrix so
; the first displayed frame is sane before the first sf_boss_matrix. Call under
; forced blank, AFTER sf_mode7_load_map. Clobbers A.
; WIDTH-RISK: entry = A16/I16 (kit setup convention). Internally toggles A8 for
; the 8-bit shadow + PPU register writes, A16 for the identity-matrix word
; writes. Exits A16/I16. No I-width toggles.
.macro sf_boss_mode7_on
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #$07
    sta SHADOW_BGMODE
    sta $2105                   ; immediate effect under forced blank
    lda #$11                    ; BG1 (bit0) + OBJ (bit4) on the main screen
    sta SHADOW_TM
    stz M7_PV_M7SEL             ; 00 = screen-repeat wrap, no flip (NMI commits)
    lda #$01
    sta M7_PV_ACTIVE            ; enable the stock-NMI M7 commit (no HDMA)
    ; --- identity matrix (A=1.0, B=0, C=0, D=1.0) so frame 0 is sane ---
    rep #$20
    .a16
    lda #M7_IDENTITY_COEFF
    sta API_BLOCK_BASE + $00    ; mode7_set_static reads $60-$66 (= API_P0..P3)
    stz API_BLOCK_BASE + $02
    stz API_BLOCK_BASE + $04
    lda #M7_IDENTITY_COEFF
    sta API_BLOCK_BASE + $06
    jsr mode7_set_static
.endmacro

; -----------------------------------------------------------------------------
; sf_boss_center cx, cy — pin the scale/rotation pivot to a map point, shown
; at screen center (128,112).
; -----------------------------------------------------------------------------
;   cx, cy  16-bit map pixel coords of the boss pivot (verbatim operands).
; Sets M7X/M7Y (= the affine pivot: the texel that stays fixed at all scales)
; and the BG1 scroll shadows so that pivot renders at screen (128,112):
; HOFS = cx-128, VOFS = cy-112. The stock NMI commits all four. Call once after
; sf_boss_mode7_on (the boss does not move the camera). Clobbers A.
; WIDTH-RISK: entry A16/I16; pure A16 stores; exits A16/I16.
.macro sf_boss_center sf_cx, sf_cy
    rep #$30
    .a16
    .i16
    lda sf_cx
    sta M7_PV_NMI_M7X           ; affine pivot X (NMI writes $211F write-twice)
    lda sf_cy
    sta M7_PV_NMI_M7Y           ; affine pivot Y (NMI writes $2120 write-twice)
    lda sf_cx
    sec
    sbc #128
    sta SHADOW_BG1HOFS          ; NMI commits to $210D (Mode 7 HOFS, write-twice)
    lda sf_cy
    sec
    sbc #112
    sta SHADOW_BG1VOFS          ; NMI commits to $210E (Mode 7 VOFS, write-twice)
.endmacro

; -----------------------------------------------------------------------------
; sf_boss_matrix scale, angle — set the whole-plane uniform affine (per frame).
; -----------------------------------------------------------------------------
;   scale  16-bit 1.7.8 uniform scale coefficient (verbatim operand). The Mode 7
;          matrix maps screen->texel, so a LARGER value samples a WIDER texel
;          span = the boss looks SMALLER/farther; $0100 (1.0) = native size.
;          (Verify direction on the emulator before locking a reveal LUT.)
;   angle  16-bit operand, LOW byte = rotation 0..255 (one full turn). 0 = no
;          rotation. Drives the engine sine LUT via sincos.
; Computes the affine matrix in signed 1.7.8:
;   M7A = (cos * scale) >> 8     M7B = (sin * scale) >> 8
;   M7C = -M7B                   M7D =  M7A
; (uniform scale: scaleX == scaleY, so D=A and C=-B) and commits it directly
; via mode7_set_static. Grounded: docs/reference/fullsnes.txt:958-966; proven by
; Phase 14 update_arena_matrix. Call FIRST after sf_frame_begin.
; Clobbers A, X, Y + the mode7_math scratch. DB must be $00 (kit default).
; WIDTH-RISK: entry A16/I16. sincos runs A16/I16; smul16 REQUIRES .i8, so the
; multiply block toggles to I8 and back to I16 before mode7_set_static. A stays
; 16-bit throughout. Every toggle is annotated; exits A16/I16.
.macro sf_boss_matrix sf_scale, sf_angle
    rep #$30
    .a16
    .i16
    ; --- trig: cosa/sina (signed 1.7.8) from the angle's low byte ---
    lda sf_angle
    and #$00FF
    jsr sincos                  ; -> cosa ($C8), sina ($CA); A16/I16

    ; WIDTH-RISK: smul16 contract is .a16/.i8, DB=0. Toggle I8 for the two
    ; multiplies, then restore I16 before mode7_set_static (which wants I16).
    sep #$10
    .i8
    ; M7A = (cos * scale) >> 8  ->  bytes 1-2 of the s32 product
    lda z:cosa
    sta z:math_a
    lda sf_scale
    sta z:math_b
    jsr smul16                  ; math_p = cos * scale (s32)
    lda z:math_p + 1            ; >> 8 : word formed by product bytes 1-2
    sta API_BLOCK_BASE + $00    ; API_P0 = M7A
    sta API_BLOCK_BASE + $06    ; API_P3 = M7D = M7A (uniform scale)
    ; M7B = (sin * scale) >> 8
    lda z:sina
    sta z:math_a
    lda sf_scale
    sta z:math_b
    jsr smul16
    lda z:math_p + 1
    sta API_BLOCK_BASE + $02    ; API_P1 = M7B
    ; M7C = -M7B
    eor #$FFFF
    inc a
    sta API_BLOCK_BASE + $04    ; API_P2 = M7C
    rep #$10
    .i16
    jsr mode7_set_static        ; write M7A-D to $211B-$211E (A16/I16)
.endmacro

.endif ; SF_MODE7_AFFINE_INC
