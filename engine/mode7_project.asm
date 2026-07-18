; =============================================================================
; mode7_project.asm — pseudo-3D (1/z pinhole) object projection (reusable)
; =============================================================================
; Project a world-space object riding a fake-3D ground plane to a screen
; position + apparent size. This is the classic forward-shooter pinhole model
; (Jake Gordon's racing-game canon / Lou's Pseudo-3D page): the camera is a
; pinhole at height CAM_H above the ground, and an object at forward depth z
; projects by 1/z. It is FULLY DECOUPLED from the Mode 7 affine matrix — the
; Mode 7 grid is just the visual backdrop. There is NO matrix inversion: the
; projection LUT (mode7_project.inc) is baked by pure arithmetic from the
; pinhole tuning constants by templates/railshooter/assets/make_project_lut.py.
; (The prior version chained obstacles to the Mode 7 D_V/A_V coefficients, whose
; floor has only ~14 world-px of forward depth — a dead end with no room for a
; multi-frame approach. The pinhole z range is arbitrary, e.g. Z_NEAR..Z_FAR.)
;
; PROJECTION (baked into the LUT, keyed by a z bucket):
;     screen_y = proj_scanline[bucket]                  (bucket = z >> PROJ_Q_LOG2)
;     scale    = proj_xscale[bucket]   (= FOCAL*256/z, a .8 perspective factor)
;     screen_x = 128 + ((obj_x - cam_x) * scale) >> 8
;     tier     = 0..3 by z thresholds (nearer = bigger)
;
; where proj_scanline[bucket] = clamp(HORIZON_Y + CAM_H*256/z, HORIZON_Y, 223).
;
; DEPTH CONTRACT: the caller passes the object's forward depth z directly in
; WORLD PIXELS ahead of the camera (NOT a 256x-scaled quantity) in PROJ_DEPTH.
; The railshooter carries a per-obstacle z scalar that decrements as the object
; approaches and recycles to Z_FAR once it passes the camera. z=0 is at the
; camera; z in (0, PROJ_DMAX] is a visible forward depth; z > PROJ_DMAX culls.
;
; REGISTER / SCRATCH CONTRACT (the caller marshals into these DP slots, then
; JSRs mode7_project; results land back in the same block):
;
;   IN   PROJ_OBJ_X  $48  (s16 world x; lateral)
;        PROJ_DEPTH  $4A  (u16 forward depth z in WORLD PX ahead; 0 = at cam)
;        PROJ_CAM_X  $4C  (s16 camera x)
;        (PROJ_CAM_Y $4E  reserved; depth is supplied directly, not derived)
;   OUT  PROJ_SX     $50  (s16 screen x; caller culls off [-16,256])
;        PROJ_SY     $52  (u8  screen scanline in low byte)
;        PROJ_TIER   $54  (u8  size tier 0..3 in low byte)
;        PROJ_CULLED $56  (u16 0 = visible, nonzero = at/behind cam or past DMAX)
;
; Entry: .a16 .i16, DB = $00 (the template's game-loop default). The routine
; toggles .i8 internally for smul16 and restores .i16 before returning.
; Clobbers: A, X, Y, and the math-helper scratch math_a/math_b/math_p ($B0-$BF).
; Does NOT touch the pv_* projection scratch ($90-$AC) — safe to call from the
; game loop between sf_mode7_tick calls.
;
; Requires (linked into the ROM, in the sf_mode7 link order): mode7_math.asm
; (smul16) and the generated mode7_project.inc (proj_scanline + proj_xscale +
; PROJ_* equates), which the template .includes in RODATA.
; =============================================================================

; Must NOT set .p816/.smart — included into a parent that already does.

; --- projection API block (game DP $48-$57, free in the railshooter set) ---
PROJ_OBJ_X  = $48
PROJ_DEPTH  = $4A           ; forward depth z in WORLD PIXELS ahead of the camera
PROJ_CAM_X  = $4C
PROJ_CAM_Y  = $4E           ; reserved (unused; depth passed directly)
PROJ_SX     = $50
PROJ_SY     = $52
PROJ_TIER   = $54
PROJ_CULLED = $56

; =============================================================================
; mode7_project — see header for the contract.
; =============================================================================
; WIDTH-RISK: entry A16/I16. Toggles I8 around the smul16 call (smul16 wants
; .a16 .i8) and restores I16 before every rts. The @cull / @have_tier /
; @bucket_ok branch targets are reached from multiple paths and carry explicit
; width annotations.
mode7_project:
    .a16
    .i16
    ; --- forward depth z is supplied directly by the caller (world px). ---
    ; z == 0 is at the camera; z in (0, PROJ_DMAX] is a visible forward depth;
    ; z > PROJ_DMAX is past the far edge (or a wrapped-negative "behind" value).
    ; Both edges cull.
    lda PROJ_DEPTH
    sta PROJ_CULLED                 ; reuse PROJ_CULLED as scratch for z
    beq @cull                       ; at the camera
    cmp #(PROJ_DMAX + 1)
    bcs @cull                       ; past the far edge OR wrapped behind

    ; --- size tier from z (nearer = bigger). A = z (positive). ---
    ldx #$0000                      ; tier 0 default (nearest/largest)
    cmp #PROJ_TIER_T0
    bcc @have_tier
    inx                             ; tier 1
    cmp #PROJ_TIER_T1
    bcc @have_tier
    inx                             ; tier 2
    cmp #PROJ_TIER_T2
    bcc @have_tier
    inx                             ; tier 3 (farthest/smallest)
@have_tier:
    .a16
    .i16
    stx PROJ_TIER

    ; --- bucket index = z / PROJ_Q (PROJ_Q is a power of two -> shifts) ---
    lda PROJ_CULLED                 ; A = z (world px)
    .repeat PROJ_Q_LOG2
    lsr a
    .endrepeat
    ; clamp to last bucket (z/Q could equal PROJ_N when z == DMAX)
    cmp #PROJ_N
    bcc @bucket_ok
    lda #(PROJ_N - 1)
@bucket_ok:
    .a16
    .i16
    tax                             ; X = bucket index

    ; --- screen_y = proj_scanline[bucket] (a byte table) ---
    sep #$20
    .a8
    lda f:proj_scanline, x
    rep #$20
    .a16
    and #$00FF
    sta PROJ_SY

    ; --- scale = proj_xscale[bucket] (a word table, = FOCAL*256/z) -> math_b ---
    txa
    asl a                           ; word index -> byte offset
    tax
    lda f:proj_xscale, x
    sta z:math_b + 0                ; math_b = scale (u16, < $8000)
    stz z:math_b + 2

    ; --- dx = obj_x - cam_x -> math_a (signed) ---
    lda PROJ_OBJ_X
    sec
    sbc PROJ_CAM_X
    sta z:math_a + 0
    stz z:math_a + 2

    ; --- math_p = dx * scale (signed) ; screen_x = 128 + (product >> 8) ---
    sep #$10
    .i8
    jsr smul16                      ; .a16 .i8 ; math_p = s32 product
    rep #$10
    .i16
    ; (product >> 8) lives in math_p+1..+2 (bits 23:8). Read it as a 16-bit
    ; word at math_p+1 (low = bit15:8, high = bit23:16).
    lda z:math_p + 1
    clc
    adc #128
    sta PROJ_SX

    stz PROJ_CULLED                 ; visible
    rts

@cull:
    .a16
    .i16
    lda #$0001
    sta PROJ_CULLED
    stz PROJ_SX
    lda #$00F0                      ; park off-screen scanline
    sta PROJ_SY
    lda #$0003
    sta PROJ_TIER                   ; smallest (irrelevant when culled)
    rts
