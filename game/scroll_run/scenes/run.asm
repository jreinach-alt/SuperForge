; =============================================================================
; scenes/run.asm — the whole game: run, jump, the seam-blind probes, the goal
; =============================================================================
; THE WHOLE LOOP, in order: horizontal tentative-move with the world clamp
; (revert if solid), jump on a fresh A press (grounded-gated), the physics step
; owning the whole vertical axis, the goal probe under the player's centre,
; then camera follow + the world - camera subtraction + draw. `phys_step` below
; is the vertical integrator, INCLUDING its one-way-platform branches, because
; this level has a live bit-1 tile: the goal pillar's top is land-on-able. (A
; level with no one-way tile can drop those branches — jumper does — but that
; condition does not hold here.)
;
; THERE IS NO SEAM HANDLING IN THIS FILE, AND THAT IS THE POINT. A collision
; layer only 32 tiles wide forces every probe to be page-split at x = 256, and
; every probe is then one more place the split can be got wrong. col_map_at
; takes WORLD pixel coordinates and is total by mask, so every probe below
; passes world x straight through and collision is seam-correct by
; construction. The seam survives in exactly one place — sr_bg's two-page
; display build — which is why this rail's tests drive the CROSSING on the
; picture and the tilemap words, not on the prober.

.scope run

; --- col_map's world binding (composition site; jumper/m7_dungeon's shape) --
; Declared here, not in the feature: col_map carries no default for any of
; these. Each name is `::`-qualified — ca65 defers an unqualified
; parent-scope lookup, and a deferred symbol is not a constant expression,
; which col_map's assembly-time `.if CM_WORLD_BLOB_CHUNKS` needs it to be.
;
; THE WORLD IS 64x32 TILES (512x256 px; the level authors 28 rows and pads
; the rest — sr_rom/feature.toml). W_LOG2 = 6 is the rail: the full two-page
; 0..511 pixel range is one coordinate space. Asserted against the blob's own
; emitted size rather than stated.
CM_WORLD_W_LOG2      = 6
CM_WORLD_H_LOG2      = 5
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ::ES_R_SR_WORLD_SIZE, error, "col_map world size disagrees with the sr_world claim"
CM_WORLD_BLOB        = ::ES_R_SR_WORLD_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_SR_WORLD_BANK
; DERIVED from the claim's own size: 2,048 B against a 32 KB LoROM window is
; 1, so col_map takes its constant-bank branch (m7_dungeon's discharge of the
; bank-adjacency obligation: at CHUNKS = 1 there is nothing to be
; consecutive). The assert is the one-chunk guard that stops the build if the
; world ever grows past a window.
CM_WORLD_BLOB_CHUNKS = (::ES_R_SR_WORLD_SIZE + 32767) / 32768
.assert CM_WORLD_BLOB_CHUNKS = 1, error, "sr_world grew past one 32 KB window — col_map's constant-bank branch no longer holds"
CM_FLAGS             = ::sr_flags_bin
.include "col_map.asm"

; =============================================================================
; THE REGION-CORRECT UNITS — an arc takes TWO scales, not one
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). A VELOCITY is px per frame and scales by r. A GRAVITY is
; px per frame SQUARED and scales by r SQUARED — and doing only the first is
; the classic half-conversion: the fall accelerates at NTSC's rate through
; frames that are 20% longer, so the arc flattens, the apex drops and the hop
; stops clearing what it was tuned to clear.
;
; ON THIS RAIL THAT IS NOT A REFINEMENT, IT IS THE WHOLE CONVERSION. The level
; is authored around the arc — measured, a runner holding RIGHT from the spawn
; reaches x = 104 and stops, 655 of 700 frames blocked against a wall he is
; meant to jump — so the traversal rate is the run AND the arc together, and a
; run-only scale changes what he can clear. game.toml carries that argument.
;
; The pair is what preserves the arc's SHAPE rather than merely its speed:
;
;     apex        = v0^2 / 2g   ->  (v0*r)^2 / (2*g*r^2)   = the same apex
;     flight time = 2*v0/g frames -> (2*v0/g)/r frames, which at 50.007 fps
;                   is the same number of REAL SECONDS as 2*v0/g at 60.099
;
; TS_SCALED is tick_scale's build-time twin of TS_STEP's PAL arm, which is
; what lets a per-frame-SQUARED quantity be scaled TWICE (once here into the
; base, once by the macro). It is NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced, and the
; `+ DEN/2` rounding is the run-time arm's own, so the two cannot disagree by
; a count.

; --- the run: one r, an ordinary consumer pair -----------------------------
; SR_SPEED is still the one number to reach for when tuning how this rail
; feels; what changed is that it is a RATE rather than a per-frame immediate.
TS_RUN_BASE = SR_SPEED * TS_ONE

; --- gravity: the r^2 site, and the only one on this rail ------------------
; TS_STEP applies exactly one r, so the other one goes into the BASE — on the
; PAL arm only, which is why the tick branches on ES_RGN_PAL BEFORE the macro
; instead of after it. Both arms share one accumulator: a console cannot
; change region, so only one of them is ever taken.
TS_GRAV_BASE   = SR_GRAVITY * TS_ONE
TS_SCALED TS_GRAV_BASE_R, TS_GRAV_BASE

; --- the two velocities: one r each, chosen once at enter ------------------
TS_SCALED SR_MAX_FALL_R,     SR_MAX_FALL
TS_SCALED SR_JUMP_VEL_R,     SR_JUMP_VEL
SR_NEG_JUMP_VEL_R = (1 << 16) - SR_JUMP_VEL_R

; scroll_run.inc's own bound, re-asserted on the SCALED pair. The 8x8 box
; probe and the row-top snaps only cover an 8 px step in either direction, and
; a region scale is exactly the kind of change that walks a tuned constant
; through a bound nobody re-checked.
.assert SR_MAX_FALL_R <= 8 << 8, error, "the PAL-scaled SR_MAX_FALL exceeds 8 px/frame — the landing snap / no-tunnel bound does not cover it"
.assert SR_JUMP_VEL_R <= 8 << 8, error, "the PAL-scaled SR_JUMP_VEL exceeds 8 px/frame — a take-off that fast can tunnel a ceiling"

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr sr_arm                      ; CHR, palette, BOTH map pages, the camera
    jsr sr_obj_arm                  ; OBJ CHR, palette, OBSEL, tile + attr
    ; ---- BG3: the text surface (hud_game's enter shape) -------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #SR_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- BG3 palette: ALL FOUR claimed words 28..31 (bg_text's claim) -----
    ; The font's glyph strokes author colour index 3 -> CGRAM word 31, so
    ; every claimed word is written (hud_game's values). The first cut of
    ; this block wrote only 28..29 and the GOAL text rendered in whatever
    ; the power-on RNG left at word 31 — green under the default seed — the
    ; exact rule-5 class the random power-on regime exists to surface, caught
    ; the first time the goal actually rendered.
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                     ; CGADD = the claim base (word 28)
    stz a:$2122                     ; colour 0 (transparent slot): black
    stz a:$2122
    lda #$52                        ; colour 1: dim slate $2952
    sta a:$2122
    lda #$29
    sta a:$2122
    lda #$B5                        ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                        ; colour 3: WHITE $7FFF — the glyph ink,
    sta a:$2122                     ;   and the pixel the goal test counts
    lda #$7F
    sta a:$2122
    rep #$20
    .a16
    ; ---- the player spawns at the left edge, standing on the floor --------
    ; grounded starts 0 — the first falling step's ground probe lands the
    ; player and sets the flag, so the spawn needs no special case.
    ; state 0 = playing.
    lda #SR_SPAWN_X
    sta z:US_PX
    lda #(SR_SPAWN_Y << 8)          ; rest on the floor row, 8.8
    sta z:US_PYF
    stz z:US_VY
    stz z:US_GROUNDED
    stz z:US_STATE
    stz z:US_FRAMES
    ; ---- the timebase's four words, and the two region-selected feel
    ;      constants. Power-on DP is RANDOM (rule 5), so these stores ARE the
    ;      write-before-read contract, not defensive initialisation.
    stz z:US_TSR_ACC
    stz z:US_TSR
    stz z:US_TSG_ACC
    stz z:US_TSG
    lda z:ES_RGN_PAL
    beq :+
    lda #SR_MAX_FALL_R
    sta z:US_VMAX
    lda #SR_NEG_JUMP_VEL_R
    sta z:US_VJUMP
    bra :++
:   .a16
    .i16
    lda #SR_MAX_FALL                ; today's constants, to the bit
    sta z:US_VMAX
    lda #SR_NEG_JUMP_VEL
    sta z:US_VJUMP
:   .a16
    .i16
    lda #SR_SPAWN_Y
    sta z:US_PYI
    lda #SR_SPAWN_X                 ; boot camera is 0 (sr_arm), so scrx = px
    sta z:US_SCRX
    jsr sr_obj_draw                 ; stage the runner BEFORE the first NMI,
                                    ;   so frame 0 commits a real entry
    ; ---- the scene's base display -----------------------------------------
    ; BGMODE, TM, BG1SC, BG12NBA: the scene_writes this scene owns on sr_bg's
    ; behalf; BG3SC/BG34NBA/BG3HOFS/BG3VOFS: on bg_text's. Values from the
    ; allocator's emitted encodings — EXCEPT the two hardware-shape bits an
    ; encoding cannot carry: BG1SC's size bit (the claim IS 64x32, sr_bg's
    ; feature.toml) and BGMODE's BG3-priority bit (hud_game's derivation).
    sep #$20
    .a8
    lda #(ES_V_SR_MAP_SC_BASE | 1)  ; BG1SC: base from the claim, size 64x32
    sta a:$2107
    lda #ES_V_SR_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                     ; BG3SC: 32x32 text map at its base
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 chr = the font base
    stz a:$2111                     ; BG3HOFS (write-twice): text is
    stz a:$2111                     ;   screen-space; it never scrolls
    stz a:$2112                     ; BG3VOFS
    stz a:$2112
    lda #$09                        ; BGMODE 1 + BG3 priority high, so the
    sta a:$2105                     ;   text draws over the terrain
    lda #$15                        ; TM: OBJ + BG3 + BG1 — the main-screen
    sta a:$212C                     ;   layer set this rail composites
    rep #$20
    .a16
    rts

; --- tick -------------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A, X, Y.
; THE ORDER: state gate, pixel-y mirror, horizontal, jump, physics, mirror
; again, goal probe, then camera + subtraction + draw. The draw path runs in
; BOTH states — once won, input is frozen and the camera holds, but the runner
; is still on screen, so the win screen is the play screen stopped rather than
; a different picture.
tick:
    .a16
    .i16
    inc z:US_FRAMES
    ; ---- this frame's two region-correct steps, published once ------------
    ; On NTSC each publishes the constant scroll_run.inc authored, to the
    ; unit, and the carried fraction stays 0 for ever — which is why the NTSC
    ; picture cannot move.
    ; BEFORE THE WIN GATE, deliberately: a step word that stops being
    ; republished is a stale word waiting to be read, and a frozen frame reads
    ; none of them anyway.
    TS_STEP z:US_TSR_ACC, TS_RUN_BASE
    sta z:US_TSR
    ; Gravity is per-frame-SQUARED: the second r rides the BASE, so the arm is
    ; chosen BEFORE the macro rather than after it. Both arms share one
    ; accumulator — a console cannot change region, so only one is ever taken.
    ; ANONYMOUS LABELS, not `@cheap` ones: TS_STEP's `.local` labels are plain
    ; symbols, so expanding it between a `@label` and its use RESETS the
    ; cheap-local scope and the branch target goes undefined.
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:US_TSG_ACC, TS_GRAV_BASE_R
    bra :++
:   .a16
    .i16
    TS_STEP z:US_TSG_ACC, TS_GRAV_BASE
:   .a16
    .i16
    sta z:US_TSG
    lda z:US_STATE
    beq @playing
    jmp @draw                       ; won: input frozen, camera holds
@playing:
    .a16
    .i16
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                    ; pixel y for probes + drawing
    jsr move_horizontal
    jsr do_jump
    jsr phys_step
    lda z:US_PYF
    xba
    and #$00FF
    sta z:US_PYI                    ; the physics moved y; refresh the mirror
    jsr goal_check
@draw:
    .a16
    .i16
    jsr follow_camera
    lda z:US_PX
    sec
    sbc z:ES_SR_CAM + 0
    sta z:US_SCRX                   ; THE SUBTRACTION: screen = world - camera
    jsr sr_obj_draw
    rts

; --- move_horizontal: tentative move at the CURRENT pixel y -----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y (the probe's).
; THE SHAPE: both directions apply before the world clamp and the ONE box
; probe, so held Left+Right nets to zero by arithmetic, and the world clamp
; bounds the tentative x BEFORE the probe. The low bound is signed-aware — a
; move that wraps below zero clamps to 0, it does not become 65,000.
move_horizontal:
    .a16
    .i16
    lda z:US_PX
    sta z:US_NEWX
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_NEWX
    clc
    adc z:US_TSR
    sta z:US_NEWX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_NEWX
    sec
    sbc z:US_TSR
    sta z:US_NEWX
@no_left:
    .a16
    .i16
    ; ---- clamp NEWX into 0 .. (WORLD_W - 8): the world bound --------------
    lda z:US_NEWX
    bpl @chk_hi                     ; bit15 clear -> non-negative, check high
    lda #0                          ; wrapped below 0 -> clamp to 0
    bra @clamped
@chk_hi:
    .a16
    .i16
    cmp #SR_PLAYER_MAX_X + 1
    bcc @clamped                    ; <= max -> keep
    lda #SR_PLAYER_MAX_X            ; > max -> clamp to max
@clamped:
    .a16
    .i16
    sta z:US_NEWX
    ; ---- the seam-blind box probe at the tentative x ----------------------
    sta z:US_BX
    lda z:US_PYI
    sta z:US_BY
    jsr sr_solid_box
    bne @blocked                    ; any corner solid: stay put
    lda z:US_NEWX
    sta z:US_PX
@blocked:
    .a16
    .i16
    rts

; --- do_jump: take off on a FRESH A press, only from the ground -------------
; In/out: A16/I16, DB=0. Clobbers A.
; ES_INP_PRESS is the rising edge, so holding A does not auto-rejump; the
; grounded gate is
; why you cannot jump in mid-air. FIXED HEIGHT: there is no jump-cut anywhere
; in this rail — releasing A early changes nothing about the arc.
do_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    beq @done
    lda z:US_GROUNDED
    beq @done
    lda z:US_VJUMP
    sta z:US_VY
    stz z:US_GROUNDED
@done:
    .a16
    .i16
    rts

; --- goal_check: the flag-2 tile under the player's centre ------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y (col_map_at's).
; ONE PROBE: the point (px+4, pyi+4), tested for flag bit 1 — the goal's own
; non-solid bit. No page split is needed (col_map_at is world-space), so this
; is the probe, the state flip, and the GOAL staging and nothing else.
; Standing ON the pillar's top does not
; win — the centre is a row above the goal tiles — which is what makes the
; one-way land a distinct behaviour the tests can drive.
goal_check:
    .a16
    .i16
    lda z:US_PX
    clc
    adc #4
    sta z:CM_PX
    lda z:US_PYI
    clc
    adc #4
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #2                          ; bit 1 = the goal flag
    bne @won
    rep #$20
    .a16
    rts
@won:
    .a8
    rep #$20
    .a16
    lda #1                          ; reached the goal pillar
    sta z:US_STATE
    ; ---- stage GOAL into bg_text's VBlank queue ---------------------------
    ; The running-scene print path (text_queue_hex4's own staging shape,
    ; against the published TXT_Q_* layout): four glyph words — exactly
    ; TXT_Q_MAX — one VMADD, count, dirty. text_vblank_commit writes the run
    ; on the next armed VBlank — no forced blank, so the win print lands
    ; without the picture dropping for a frame.
    lda #(('G' - ' ') | SR_TXT_ATTR)
    sta z:TXT_Q_WORDS + 0
    lda #(('O' - ' ') | SR_TXT_ATTR)
    sta z:TXT_Q_WORDS + 2
    lda #(('A' - ' ') | SR_TXT_ATTR)
    sta z:TXT_Q_WORDS + 4
    lda #(('L' - ' ') | SR_TXT_ATTR)
    sta z:TXT_Q_WORDS + 6
    lda #(ES_V_TEXT_MAP + SR_GOAL_ROW * 32 + SR_GOAL_COL)
    sta z:TXT_Q_VMADD
    sep #$20
    .a8
    lda #4
    sta z:TXT_Q_COUNT
    sta z:TXT_Q_DIRTY               ; nonzero = staged (the hex4 shape)
    rep #$20
    .a16
    rts

; --- follow_camera: cam_x = clamp(px - 128, 0, 256); cam_y pinned 0 ---------
; In/out: A16/I16, DB=0. Clobbers A.
;
; X IS THE ONLY LIVE FOLLOW AXIS: with a 224-line world and a 112-line
; half-screen anchor, cam_y clamps to 0 every frame, so it is pinned here
; explicitly rather than recomputed. THE CAMERA IS A PURE FUNCTION OF
; THE PLAYER: no camera state survives a tick, which is why walking back from
; a clamped edge re-tracks with no unclamp logic to get wrong
; (camera_follow's shape, one axis).
follow_camera:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc #SR_HALF_W
    bpl @chk_hi                     ; >= 0 -> check the high clamp
    lda #0                          ; player left of centre-range -> pin at 0
    bra @done
@chk_hi:
    .a16
    .i16
    cmp #SR_CAM_MAX_X + 1
    bcc @done                       ; <= max -> keep (TRACKING regime)
    lda #SR_CAM_MAX_X               ; > max -> pin at the far edge (CLAMPED)
@done:
    .a16
    .i16
    sta z:ES_SR_CAM + 0
    stz z:ES_SR_CAM + 2             ; cam_y: pinned 0, every frame
    rts

; --- phys_step: one frame of vertical physics ------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
;
; TWO ARMS. Falling: ground probe / one-way stand probe / integrate / landing
; snap / one-way crossing land. Rising: gravity / head bump. The tentative 8.8
; position lives in US_TENT rather than on the stack — a value pushed in one
; width and popped in another is the silent-corruption class rule 6 exists for
; — and row tops are `lsr x3 / asl x3` rather than `and #$FFF8`, which keeps
; the arithmetic in one width.
;
; THE ONE-WAY CONTRACT (live here because the goal tile carries bit 1): a
; bit-1 tile lands the box when its bottom edge
; CROSSES the tile top from above, supports standing on top (the pixel-
; aligned stand probe), and is transparent from below and from the sides —
; and it never blocks walking, because sr_solid_box tests bit 0 only.
phys_step:
    .a16
    .i16
    lda z:US_VY
    bpl @falling
    jmp @rising                     ; a trampoline: the rising arm is past
                                    ;   short-branch reach
@falling:
    .a16
    .i16
    ; ---- ground probe: solid 1px below the current box? -> standing -------
    lda z:US_PYF
    xba
    and #$00FF
    inc a
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr sr_solid_box
    beq @chk_ow_stand
    jmp @stand
@chk_ow_stand:
    .a16
    .i16
    ; ---- one-way support: resting EXACTLY on a bit-1 top? -----------------
    ; Only meaningful at pixel alignment (box top a multiple of 8, i.e. the
    ; box bottom exactly on a tile boundary) — mid-tile there is nothing
    ; one-way to stand on.
    lda z:US_PYF
    xba
    and #$0007
    beq :+
    jmp @integrate                  ; mid-tile: fall
:   .a16
    .i16
    lda z:US_PYF
    xba
    and #$00FF
    clc
    adc #8                          ; the row just below the box = the tile top
    sta z:US_YB
    lda z:US_PX
    sta z:CM_PX
    lda z:US_YB
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #2                          ; bit 1 = platform/goal top
    beq :+
    rep #$20
    .a16
    jmp @stand
:   .a8
    rep #$20
    .a16
    lda z:US_PX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_YB
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #2
    beq :+
    rep #$20
    .a16
    jmp @stand
:   .a8
    rep #$20
    .a16
    jmp @integrate
@stand:
    .a16
    .i16
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    lda z:US_PYF
    and #$FF00                      ; pixel-exact rest (clear subpixel)
    sta z:US_PYF
    rts
@integrate:
    .a16
    .i16
    ; ---- gravity, clamped to terminal fall speed --------------------------
    lda z:US_VY
    clc
    adc z:US_TSG
    cmp z:US_VMAX
    bcc @noclamp
    lda z:US_VMAX
@noclamp:
    .a16
    .i16
    sta z:US_VY
    ; ---- tentative move, then probe the new pixel -------------------------
    lda z:US_PYF
    clc
    adc z:US_VY
    sta z:US_TENT
    xba
    and #$00FF
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr sr_solid_box
    beq @fall_clear
    ; ---- blocked: landing snap — box bottom -> tile top -------------------
    lda z:US_BY
    clc
    adc #7                          ; the box's bottom pixel
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl                         ; top of the solid tile row it entered
    .endrepeat
    sec
    sbc #8                          ; box top = tile top - box height
    xba                             ; pixel -> 8.8 (value <= $00FF, so
                                    ;   xba is exactly << 8)
    sta z:US_PYF
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    rts
@fall_clear:
    .a16
    .i16
    ; ---- one-way platforms: land only when CROSSING a top from above ------
    ; The new bottom pixel's tile top vs the OLD bottom EDGE — land iff
    ; old_bottom <= tile_top, i.e. the box was entirely above the top last
    ; frame and is at/past it now.
    lda z:US_BY
    clc
    adc #7                          ; the box's bottom pixel at the new pos
    sta z:US_YB                     ; ...is the one-way probe row
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl                         ; that row's tile top
    .endrepeat
    sta z:US_TOPY
    lda z:US_PYF                    ; OLD position (not yet overwritten)
    xba
    and #$00FF
    clc
    adc #8                          ; old bottom EDGE
    cmp z:US_TOPY
    beq @ow_cross
    bcc @ow_cross
    jmp @ow_none                    ; started at/below the top -> pass through
@ow_cross:
    .a16
    .i16
    lda z:US_PX
    sta z:CM_PX
    lda z:US_YB
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #2                          ; bit 1 = platform/goal top
    beq :+
    rep #$20
    .a16
    jmp @ow_land
:   .a8
    rep #$20
    .a16
    lda z:US_PX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_YB
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #2
    beq :+
    rep #$20
    .a16
    jmp @ow_land
:   .a8
    rep #$20
    .a16
    jmp @ow_none
@ow_land:
    .a16
    .i16
    lda z:US_TOPY                   ; the crossed top (already row-aligned)
    sec
    sbc #8                          ; box top = tile top - box height
    xba
    sta z:US_PYF                    ; same landing snap as a solid floor
    stz z:US_VY
    lda #1
    sta z:US_GROUNDED
    rts
@ow_none:
    .a16
    .i16
    lda z:US_TENT                   ; commit the tentative position
    sta z:US_PYF
    stz z:US_GROUNDED
    rts
@rising:
    .a16
    .i16
    stz z:US_GROUNDED
    lda z:US_VY                     ; gravity (no clamp needed while negative)
    clc
    adc z:US_TSG
    sta z:US_VY
    lda z:US_PYF
    clc
    adc z:US_VY
    sta z:US_TENT
    xba
    and #$00FF
    sta z:US_BY
    lda z:US_PX
    sta z:US_BX
    jsr sr_solid_box
    beq @rise_clear
    ; ---- head bump: box top -> first clear row below the ceiling ----------
    lda z:US_BY
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl                         ; the ceiling tile's row
    .endrepeat
    clc
    adc #8                          ; first clear row below it
    xba
    sta z:US_PYF
    stz z:US_VY                     ; kill the ascent — the arc comes down
                                    ;   early, like it should
    rts
@rise_clear:
    .a16
    .i16
    lda z:US_TENT
    sta z:US_PYF
    rts

; --- sr_solid_box: is any corner of an 8x8 box at (US_BX, US_BY) solid? -----
; In: A16/I16, DB=0; US_BX/US_BY = the box's top-left WORLD pixel (the full
; 0..511 x range — no page split, see the file header). Out: A16 = 1/0, Z
; reflecting it (callers use beq/bne). Clobbers A, X, Y (col_map_at's).
;
; FOUR CORNERS: (x,y) (x+7,y) (x,y+7) (x+7,y+7) — the box spans 8 px, so the
; far corners are +7, not +8 (a +8 probe reads the NEIGHBOURING tile and
; sticks you to walls). Each probe is col_map's flag byte tested at bit 0
; (SOLID). A box straddling world x = 256 probes both PAGES of the display
; through the one world blob, and needs no case for it: the coordinate space
; does that work.
;
; WIDTH-RISK: col_map_at EXITS A8 (its stated contract) — every probe return
; narrows, so each corner's 16-bit setup re-widens first. @hit is reached in
; A8 from all four probes.
sr_solid_box:
    .a16
    .i16
    ; corner (x, y)
    lda z:US_BX
    sta z:CM_PX
    lda z:US_BY
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract;
                                    ;   without this ca65 still tracks A16 and
                                    ;   `and #1` assembles 3-byte, the stray $00
                                    ;   executing as BRK (rule 6's silent class,
                                    ;   and its OWN named example)
    and #1                          ; bit 0 = solid
    bne @hit
    rep #$20
    .a16
    ; corner (x+7, y)
    lda z:US_BX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BY
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #1
    bne @hit
    rep #$20
    .a16
    ; corner (x, y+7)
    lda z:US_BX
    sta z:CM_PX
    lda z:US_BY
    clc
    adc #7
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #1
    bne @hit
    rep #$20
    .a16
    ; corner (x+7, y+7)
    lda z:US_BX
    clc
    adc #7
    sta z:CM_PX
    lda z:US_BY
    clc
    adc #7
    sta z:CM_PY
    jsr col_map_at
    .a8                             ; col_map_at EXITS A8 — its stated contract
    and #1
    bne @hit
    rep #$20
    .a16
    lda #0                          ; all four corners clear (Z set)
    rts
@hit:
    .a8
    rep #$20
    .a16
    lda #1                          ; solid (Z clear)
    rts

; --- exit -------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. One scene, no edges —
; the handler satisfies scene_mgr's table and re-parks what this scene armed.
exit:
    .a16
    .i16
    jsr oam_park_all
    rts

.endscope
