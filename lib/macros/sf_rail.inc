; =============================================================================
; sf_rail.inc — pseudo-3D depth-actor scaffolding (macro library)
; =============================================================================
; The reusable bricks for a forward / rail shooter on the Mode 7 perspective
; floor: approaching depth actors (obstacles, hazards, pickups) that ride a
; pinhole (1/z) projection, scale through pre-drawn discrete size tiers, and
; draw back-to-front by depth. This COMPLEMENTS the existing groups:
;   * sf_pool.inc — the fixed-slot actor pool (ALIVE[] + parallel arrays). A
;     rail depth actor IS a pooled actor; sf_rail adds the depth axis + the
;     projection/draw glue on top. sf_enemy.inc is its 2D-platformer sibling
;     (patrol + stomp over the same pool model); sf_rail is the pseudo-3D one.
;   * sf_mode7.inc — the perspective floor (the visual BACKDROP). The depth
;     actors are DECOUPLED from the Mode 7 affine matrix; see the guide.
;   * sf_sprite.inc — sf_rail_draw_sorted emits through engine_spr.
;
; Only mechanics PROVEN on the railshooter template ship here. sf_rail_wave is
; marked SCAFFOLDED (not yet exercised by a shipping template) — see its header.
;
; ----------------------------------------------------------------------------
; THE DEPTH-ACTOR POOL RECORD (a convention over sf_pool's parallel arrays)
; ----------------------------------------------------------------------------
; A depth-actor pool is an sf_pool ALIVE[] array plus three parallel arrays,
; all in the $1800-$1DFF game-array region (sf_pool's rule — plain abs,X), all
; indexed by the SAME pool byte offset (slot k -> byte 2*k):
;
;   ALIVE[N]    word   1 = live, 0 = free          (sf_pool owns this)
;   LANE_X[N]   word   s16 lateral world-px offset (the actor's X in the world)
;   DEPTH_Z[N]  word   u16 forward depth z in WORLD PIXELS ahead of the camera
;                      (0 = at the camera; advance it DOWN per frame to approach,
;                      recycle to a far Z when it passes — see the railshooter)
;   TIER[N]     word   u8 current size tier 0..3 (kept for GROW/SHRINK
;                      hysteresis so a near-threshold actor doesn't flicker
;                      tiers; the projection recomputes a raw tier each frame,
;                      your game applies hysteresis against the stored one)
;
; SIZING: 4 words/actor across 4 arrays = 8 bytes of array per slot per array;
; an N-actor pool needs 4*N words = 8*N bytes total (e.g. N=6 -> 48 bytes per
; array). Lay them out 16 words apart for headroom:
;   OBS_ALIVE = $1800   OBS_LANEX = $1810   OBS_DEPTH = $1820   OBS_TIER = $1870
;
; ----------------------------------------------------------------------------
; THE THREE SURFACES
; ----------------------------------------------------------------------------
;   sf_rail_project   — project ONE actor (lane_x, depth_z, cam_x) to screen
;                       x/y + size tier + culled, via engine/mode7_project.asm.
;   sf_rail_draw_sorted — emit a whole pool to OAM ordered by tier (nearest in
;                       front), the depth-correct draw + the recycle-pop fix.
;   sf_rail_wave      — SCAFFOLDED table-driven wave spawner (not yet shipped).
;
; Requires (linked, in the sf_mode7 link order): mode7_project.asm,
; mode7_math.asm (smul16), rail_draw.asm, sprite_engine.asm, plus the generated
; mode7_project.inc (PROJ_* equates + the projection LUT) .included in RODATA.
; Include sf_pool.inc + sf_sprite.inc + sf_mode7.inc alongside this file.
; Guide: docs/guides/pseudo3d_rail.md. Reference template: templates/railshooter/.
; =============================================================================

.ifndef SF_RAIL_INC
SF_RAIL_INC = 1

; -----------------------------------------------------------------------------
; sf_rail_project lane_x, depth_z, cam_x — project ONE depth actor.
; -----------------------------------------------------------------------------
;   lane_x   s16 lateral world-X of the actor (verbatim operand: #imm/DP/abs)
;   depth_z  u16 forward depth z in WORLD PIXELS ahead of the camera (verbatim)
;   cam_x    s16 camera world-X (verbatim)
;
; Thin wrapper over mode7_project (engine/mode7_project.asm): marshals the three
; values into the projection block and JSRs. The pinhole model is decoupled from
; the Mode 7 affine matrix — depth z is a free forward axis you advance per
; frame, NOT derived from the floor's shallow ~14px matrix depth (see the
; guide's DEAD-ENDS section). After the call, read the results from the block:
;
;   PROJ_SX     $50  screen x of the actor CENTRE (s16; cull off [-16,256])
;   PROJ_SY     $52  screen scanline (low byte; $F0 when culled)
;   PROJ_TIER   $54  raw size tier 0..3 (0 = nearest/largest) by z thresholds
;   PROJ_CULLED $56  0 = visible; nonzero = at/behind cam OR past the far edge
;
; To place the sprite: screen-left X = PROJ_SX - (half the tier's sprite width).
; For stable tiers (no boundary flicker) apply GROW-only hysteresis against your
; stored TIER[] before dispatching the tier -> (tile, size, centre) — the
; railshooter's obs_tier_hysteresis is the worked example.
;
; Clobbers A, X, Y and the math scratch ($B0-$BF). Does NOT disturb the per-
; frame Mode 7 projection scratch, so it is safe in the game loop between
; sf_mode7_tick calls.
; WIDTH-RISK: asserts A16/I16 entry; mode7_project toggles I8 internally and
; restores I16 before returning. Exits A16/I16.
.macro sf_rail_project sf_lanex, sf_depthz, sf_camx
    rep #$30
    .a16
    .i16
    lda sf_lanex
    sta z:PROJ_OBJ_X
    lda sf_depthz
    sta z:PROJ_DEPTH
    lda sf_camx
    sta z:PROJ_CAM_X
    jsr mode7_project
.endmacro

; -----------------------------------------------------------------------------
; sf_rail_draw_sorted params_base — emit a whole pool, ordered by depth tier.
; -----------------------------------------------------------------------------
;   params_base  WRAM address (in $1800-$1DFF) of an 8-word parameter block the
;                CALLER has already filled (see below). Verbatim operand: a
;                symbol/literal (loaded as #imm into X).
;
; Emits every live+visible actor into OAM slots [base, base+count), ORDERED BY
; SIZE TIER: tier 0 (nearest/largest) into the lowest slots, tier 3 into the
; highest, then parks the unused slots at y=$F0. Lower OAM index draws in FRONT
; on the SNES, so nearer actors occlude farther ones — correct back-to-front
; depth layering with NO sort (the engine routine buckets by the tier the
; projection already computed). The order is RE-DERIVED every frame, so an
; actor's pool slot is irrelevant to where it draws — this is the fix for the
; recycle "pop" and the deep-overlap mis-layering a fixed slot->slot map causes.
;
; CALLER CONTRACT (exactly like the spr macro's slot rule):
;   * Call spr_clear, then draw any FIXED-slot sprites (e.g. the player at slot
;     0) FIRST, so SPRITE_COUNT == your intended OAM base when you call this.
;   * Fill the parameter block (8 words at params_base) once before the call:
;       +$00  word  ALIVE[]  base address
;       +$02  word  LANE_X[] base address
;       +$04  word  DEPTH_Z[] base address
;       +$06  word  camera world-X (s16)
;       +$08  word  actor count N (1..32)
;       +$0A  word  ROM address of the per-tier descriptor table (4 entries x
;                   3 words = {tile, flags, center_off}; see below)
;       +$0C  word  WRAM scratch base, N*4 words (8 bytes/actor) the routine
;                   uses as a projection cache — pick a free $1800-region span
;       +$0E  word  TIER[] base address — the EFFECTIVE (stored) size tier per
;                   actor. The routine orders + picks the descriptor by THIS
;                   tier (not the raw projected one), so apply your grow/shrink
;                   hysteresis into TIER[] before the call (the projection still
;                   supplies sx/sy/culled). If you don't want hysteresis, store
;                   the raw PROJ_TIER from sf_rail_project into TIER[] each frame.
;   * Provide the per-tier descriptor table in RODATA (one row per tier 0..3):
;       rail_tier_tbl:
;           .word TIER0_TILE,  TIER0_FLAGS, TIER0_CENTER   ; nearest/largest
;           .word TIER1_TILE,  TIER1_FLAGS, TIER1_CENTER
;           .word TIER2_TILE,  TIER2_FLAGS, TIER2_CENTER
;           .word TIER3_TILE,  TIER3_FLAGS, TIER3_CENTER   ; farthest/smallest
;     flags = OAM attr (bit7 size, bit6 Hflip, bits3:0 palette); center_off =
;     half the sprite width (16 for a 32x32 large frame, 8 for a 16x16 small).
;
; Net: exactly `count` engine_spr calls (live actors tier-ordered, unused slots
; parked). Clobbers A, X, Y, the projection block ($48-$57), the math scratch
; ($B0-$BF), and the routine's DP scratch ($58-$5F).
; WIDTH-RISK: asserts A16/I16 entry; rail_draw_sorted stays A16/I16 (its callees
; mode7_project + engine_spr honor that contract). Exits A16/I16.
.macro sf_rail_draw_sorted sf_params
    rep #$30
    .a16
    .i16
    ldx #(sf_params)
    jsr rail_draw_sorted
.endmacro

; -----------------------------------------------------------------------------
; sf_rail_wave — SCAFFOLDED table-driven wave spawner (NOT YET SHIPPED).
; -----------------------------------------------------------------------------
; !! SCAFFOLDING ONLY — this macro is provided as the documented SHAPE of a
; !! wave system but is NOT exercised by any shipping template and has NOT been
; !! verified on the emulator. Treat it as a starting skeleton, not load-bearing
; !! tested code. The railshooter currently uses a simpler "seed N obstacles
; !! staggered across the depth range + recycle on pass" field (no wave table);
; !! it is the proven path. Adopt sf_rail_wave only with your own run-gate.
;
; INTENDED CONTRACT (the shape a wave system takes — for when a project needs
; paced, counted spawns instead of a steady recycled field):
;
;   A WAVE TABLE is a ROM array of fixed-size entries, one per wave:
;       wave_tbl:
;           ; trigger_frame, count, lane_pattern, kind
;           .word 60,  3, PATTERN_SPREAD, KIND_BLOCK
;           .word 180, 5, PATTERN_LINE,   KIND_FAST
;           ...
;       wave_tbl_end:
;   The game advances a wave cursor + a frame counter; when FRAME_COUNTER
;   reaches the next entry's trigger_frame, it spawns `count` actors (via
;   sf_pool_spawn into the depth-actor pool) at DEPTH_Z = the spawn-far Z, with
;   LANE_X assigned by lane_pattern, and a kind tag if your actors vary.
;
; sf_rail_wave is intentionally a no-op stub until a template proves it: it
; documents the interface so a future builder fills the body against a run-gate
; rather than inventing the convention from scratch. Calling it does nothing.
; WIDTH-RISK: none — empty body. Asserts nothing; safe at any width.
.macro sf_rail_wave sf_wave_tbl, sf_wave_tbl_end, sf_cursor, sf_pool_alive, sf_pool_n
    ; SCAFFOLDED: no shipped implementation. See the header above. A real
    ; implementation compares FRAME_COUNTER to sf_wave_tbl[sf_cursor].trigger,
    ; spawns the entry's `count` into the pool, and advances sf_cursor. Left
    ; empty deliberately so it can't be mistaken for tested, load-bearing code.
.endmacro

.endif ; SF_RAIL_INC
