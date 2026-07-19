; =============================================================================
; railshooter — Mode 7 forward rail shooter (auto-advancing grid + strafe ship)
; =============================================================================
; The genre rail for an arcade forward-shooter on the Mode 7 perspective floor
; (the ground rushes toward the viewer; you strafe and dodge). Shares the
; racer's Mode 7 spine (standard kit boot,
; the sf_mode7 macro group, the stock engine NMI, the CH2 sky TM-split) but
; differs in the two axes that make it a rail shooter rather than a racer:
;
;   * DRIVER = rail (not input-throttle): the camera AUTO-ADVANCES forward at a
;     constant speed every frame with no button held — the grid terrain streams
;     toward the viewer (the speed cue). The racer coasts to a stop; this never
;     stops.
;   * The PLAYER SPRITE strafes: LEFT/RIGHT slide the camera laterally across
;     the world AND lean the ship sprite on screen, instead of the racer's
;     fixed-screen kart + steering. (UP/DOWN reserved for future pitch.)
;
; Hardware composition: a single Mode 7 background band + OBJ + the sky TM-split.
; Two HDMA channels are in use (the Mode 7 matrix + the CH2 sky split), no custom
; per-scanline work beyond them. The genre is built by REUSING existing
; primitives (Mode 7 + the sky split + a rail driver), not by adding new engine
; machinery: the floor is stock Mode 7; only the driver and the actors differ.
;
; THE SKY: same as the racer — Mode 7 has one BG layer, so arm_sky_split turns
; BG1 off above the horizon to reveal the CGRAM[0] backdrop, which
; make_ground.py reserves as a deep-space sky. High horizon + strong far-scale
; give the long forward view a rail shooter needs.
;
; OBJ-OVER-MODE-7: the Mode 7 map fills VRAM words $0000-$3FFF, so OBSEL moves
; the OBJ name base to word $4000 ($62), CHR uploads at word $4000. (Same as
; the racer; the ship sprite is the racer's vehicle CHR as a placeholder.)
;
; Controls: LEFT/RIGHT strafe. Forward motion is automatic. A fires.
;
; PROJECTION (a decoupled pinhole, 1/z, NOT the Mode 7 matrix inverse):
; obstacles ride their OWN pinhole (1/z) projection by engine/mode7_project.asm,
; FULLY DECOUPLED from the Mode 7 affine matrix — the grid is just the visual
; backdrop (see docs/guides/pseudo3d_rail.md for the full model). Each obstacle/bullet
; carries a forward depth z in WORLD PIXELS ahead of the camera. The projection
; routine buckets z against a z-indexed LUT (mode7_project.inc, baked by pure
; pinhole arithmetic) to get its scanline (= HORIZON_Y + CAM_H*256/z), lateral
; scale (= FOCAL*256/z) and size tier. z decrements per frame, giving a smooth
; multi-frame descent from the horizon to the bottom of the screen through 4
; pre-drawn size tiers. (Anchoring obstacles to the Mode 7 matrix instead would
; give only ~14 world-px of forward depth — far too shallow for a multi-frame
; approach; decoupling the actors is exactly how the classic forward shooters
; faked it.)
;
; File layout (top to bottom; the major === section banners):
;   INIT         — RESET: ground + sprite uploads, Mode 7 camera, seed the field
;   MAIN LOOP    — game_loop, the once-per-frame heartbeat (read this first)
;   SUBROUTINES  — bullet/obstacle hit test, obstacle recycle, tier hysteresis,
;                  the sky-split arm
;   DATA         — the lane table, per-tier descriptors, projection LUTs, engine
;                  includes, ship + obstacle art, and the Mode 7 ground blob
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Build:  make railshooter  (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_64k.cfg
;   ^ Linker-config sentinel: 64KB image, the 32KB Mode 7 grid blob fills
;     BANK1. The generic build/%.sfc rule reads this and links lorom_64k.cfg
;     instead of the default lorom.cfg; copy-to-adapt keeps the line, no Makefile
;     edit needed. (See docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "RAIL BLASTER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"
.include "sf_frame.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_mode7.inc"
.include "sf_pool.inc"          ; obstacle + bullet pools
.include "sf_rail.inc"          ; pseudo-3D depth actors: project + sorted draw
.include "sf_input.inc"         ; btnp (A = fire, rising edge)
.include "engine_state.inc"

; --- tuning (assemble-time) ---
RAIL_SPEED   = 6                ; world px/frame forward (constant auto-advance)
STRAFE_SPEED = 5                ; world px/frame lateral on LEFT/RIGHT
SHIP_CENTER  = 128 - 16         ; centered 32x32 ship screen X
SHIP_LEAN    = 24               ; screen-X offset when strafing (banking)
SHIP_Y       = 150              ; ship planted low on the screen

; --- banking: on strafe the world plane tilts a few heading units toward
; the strafe and eases back to straight on release. Kept small so the angle-0
; projection LUT stays valid for obstacles (a 6-unit bank is ~8.4 degrees). ---
BANK_MAX  = 6                   ; peak heading offset (units; 256 = full turn)
BANK_STEP = 1                   ; ease rate toward the target per frame

; --- perspective: high horizon + long forward view (a long-range camera set) ---
PV_L0     = 56                  ; horizon scanline (~25% down; thin sky band)
PV_L1     = 224
PV_S0     = 576                 ; far-scale (long forward view)
PV_S1     = 28
PV_SH     = 16
PV_INTERP = 2
PV_WRAP   = 1
FOCUS_Y   = 200

; --- spawn: mid-map, facing straight down the rail (angle 0) ---
START_X = 512
START_Y = 512
VEHICLE_BASE = 0

; --- obstacle field: pre-drawn discrete-size approaching hazards ---
; The ship CHR fills OBJ tiles 0-63 (VRAM word $4000, 64 tiles). The obstacle
; CHR uploads right after it at VRAM word $4400 = macro base-tile 1088, so its
; OAM tile numbers (relative to OBSEL name base) start at 64.
;
; DEPTH MODEL (pinhole 1/z): each obstacle carries a forward depth z in WORLD
; PIXELS ahead of the camera (PROJ_DMAX from mode7_project.inc is the far edge).
; It decrements RAIL_DEPTH_STEP/frame as the rail advances toward it, and
; recycles to OBS_SPAWN_DEPTH (far) once it reaches Z_NEAR. z is matched against
; the z-indexed pinhole LUT — fully decoupled from the Mode 7 matrix.
OBS_CHR_VRAM_TILE = 1088        ; VRAM word/16 for the obstacles_chr upload
OBS_TILE_BASE     = 64          ; OBJ tile number of the obstacle CHR
OBS_N         = 6               ; pooled obstacles
; pinhole depth tuning (z in world px; PROJ_DMAX = Z_FAR = 640 from the LUT) ---
Z_NEAR        = 16              ; recycle/pass threshold (world px)
OBS_SPAWN_DEPTH = PROJ_DMAX     ; z to (re)spawn far ahead at (= Z_FAR = 640)
RAIL_DEPTH_STEP = 12            ; z closed per frame (~51-frame approach, smooth)
; recycle once z drops below this. Kept just under Z_NEAR (and below one
; RAIL_DEPTH_STEP) so the obstacle is still DRAWN at its nearest z (= ~Z_NEAR,
; screen_y clamped to the bottom) for one frame before it recycles.
OBS_NEAR_KILL = 8
; z stagger between adjacent seeded obstacles (spread the field across the rail)
OBS_DEPTH_STAGGER = (OBS_SPAWN_DEPTH - OBS_NEAR_KILL) / OBS_N
; --- tier hysteresis (stops boundary flicker). An obstacle's
; tier only GROWS as z falls below (threshold - margin); never shrinks until
; recycle. The margin keeps a near-threshold obstacle from flickering tiers.
TIER_HYST     = 12             ; z hysteresis margin (world px)

; --- firing: bullets travel forward (away), reticle marks the aim point --
; Bullets carry a z too; firing it recedes (z INCREASES) up the screen toward
; the horizon, faster than the rail closes obstacles.
BUL_N         = 4               ; pooled bullets
BUL_SPEED     = 20              ; z/frame forward (faster than the rail closes)
BUL_SPAWN_DEPTH = Z_NEAR        ; z a bullet is born at (just ahead of the ship)
BUL_MAX_DEPTH = (PROJ_DMAX - 8) ; kill a bullet once it reaches ~the horizon
RETICLE_DEPTH = 200             ; z ahead the lock-on reticle sits at (world px)
HIT_DEPTH_TOL = 28              ; |bullet_z - obs_z| hit window (world px)
HIT_X_TOL     = 48              ; |bullet_x - obs_x| hit window (world px)

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_A     = $0080

; --- sky TM-split (see arm_sky_split; same pattern as the racer) ---
SKY_SPLIT_TABLE = $7E0000 + $2010
SKY_HORIZON     = PV_L0

; --- game DP state (kit contract: $32-$5F) ---
R_POSX   = $32                  ; camera x, 16.16
R_POSY   = $36                  ; camera y, 16.16
R_ANGLE  = $3A                  ; heading (fixed 0 = straight rail)
R_SHIPX  = $3C                  ; ship sprite screen X (16-bit)
R_VTILE  = $3E                  ; ship draw tile
R_VFLAGS = $40                  ; ship OAM flags (lean H-flip)
; --- obstacle/bullet draw scratch ($42-$47; projection block owns $48-$57) ---
OBS_DRAW_X     = $42            ; computed top-left screen X for the spr call
OBS_DRAW_TILE  = $44            ; OAM tile for the obstacle/bullet
OBS_DRAW_FLAGS = $46            ; OAM flags (size/palette)
; --- loop scratch ($58-$5F; below the kit DP ceiling $5F) ---
; NOTE: sf_rail_draw_sorted (rail_draw.asm) OWNS DP $58-$5F for the duration of
; its call (RD_* scratch). OBS_OFF/BUL_OFF are transient per-loop counters
; (re-stz'd before each use), so sharing the window with the draw is safe. The
; two PERSISTENT-across-frames cursors (R_BANK, OBS_LANE) live in WRAM below so
; the draw can't clobber them.
OBS_OFF        = $58            ; obstacle pool loop byte offset (transient)
BUL_OFF        = $5E            ; bullet pool loop byte offset (transient)
; persistent state moved to the game-array region (rail_draw clobbers $58-$5F):
R_BANK         = $1880          ; banking heading offset, SIGNED 16-bit
OBS_LANE       = $1882          ; respawn lane cursor (0..LANE_N-1)

; --- pools ($1800-$1DFF game-array region; see sf_pool.inc) ---
; NOTE: the *_DEPTH arrays hold a forward depth z in WORLD PX, not a world Y.
OBS_ALIVE = $1800              ; alive[OBS_N]
OBS_WX    = $1810              ; world x[OBS_N] (16-bit; lateral)
OBS_DEPTH = $1820              ; forward depth z[OBS_N] (16-bit, world px)
BUL_ALIVE = $1830              ; alive[BUL_N]
BUL_WX    = $1840              ; world x[BUL_N] (lateral)
BUL_DEPTH = $1850              ; forward depth z[BUL_N] (world px)
; collision scratch (live across the bullet x obstacle nested loop)
BHIT_DEPTH = $1860             ; current bullet z (world px)
BHIT_X     = $1862             ; current bullet world x
; per-obstacle current size tier 0..3 (for grow-only hysteresis)
OBS_TIER  = $1870              ; current tier[OBS_N] (16-bit, 0..3)
; --- sf_rail_draw_sorted scratch (the depth-sorted OAM emit) ---
; The draw routine projects every obstacle into a cache (OBS_N x 4 words =
; 48 bytes) then emits them tier-ordered. The 8-word param block hands it the
; pool array bases + cam_x + count + the per-tier descriptor table + the cache.
RAIL_CACHE  = $1890            ; projection cache: OBS_N x 4 words ($1890-$18BF)
RAIL_PARAMS = $18C0            ; sf_rail param block, 8 words ($18C0-$18CF)

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, Mode 7, seed field)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    jsr hdma_alloc_init

    ; --- ground upload (under the coldstart forced blank) ---
    sf_mode7_load_map ground_map, #$8000

    ; ground palette -> CGRAM 0.. (index 0 = the reserved sky backdrop)
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD (CGRAM address): start the upload at colour 0
    ldx #$0000
gpal_loop:
    .a8
    lda f:ground_pal, x
    sta $2122               ; CGDATA (CGRAM data): write a byte; index auto-advances
    inx
    cpx #(GROUND_PAL_COUNT * 2)
    bne gpal_loop
    rep #$30
    .a16
    .i16

    ; --- ship sprite: palette + CHR out of the Mode 7 map's VRAM ---
    sf_load_obj_pal 0, vehicle_pal
    sf_load_obj_chr 1024, vehicle_chr, vehicle_chr_bytes
    ; --- obstacle/reticle/bullet CHR + its own OBJ palette (after the ship) ---
    sf_load_obj_pal 1, obstacles_pal
    sf_load_obj_chr OBS_CHR_VRAM_TILE, obstacles_chr, obstacles_chr_bytes
    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: name base word $4000, 16x16/32x32
    lda #$10
    sta SHADOW_TM               ; OBJ on; NMI ORs BG1 in -> TM = $11
    rep #$30
    .a16
    .i16

    ; --- Mode 7 on + the long-view rail camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0, #PV_L1, #PV_S0, #PV_S1, #PV_SH, #PV_INTERP, #PV_WRAP
    sf_mode7_focus #FOCUS_Y

    lda #START_X
    sta R_POSX + 2
    stz R_POSX + 0
    lda #START_Y
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_ANGLE
    lda #SHIP_CENTER
    sta R_SHIPX
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE

    sf_mode7_tick               ; first table build BEFORE screen-on

    jsr arm_sky_split           ; CH2 TM-split: sky above the horizon

    ; --- obstacle field: stagger OBS_N hazards across the z (depth) range ---
    ; Slot i spawns at z = OBS_SPAWN_DEPTH - i*OBS_DEPTH_STAGGER (nearer for
    ; higher i), in lane X cycling through obs_lane_x. Staggering across the
    ; whole depth range means at any instant several tiers are on-screen. Each
    ; slot's current tier is seeded to 3 (farthest); the per-frame hysteresis
    ; grows it as z falls (it re-seeds to 3 on recycle in obs_recycle).
    sf_pool_init OBS_ALIVE, OBS_N
    stz OBS_LANE
    lda #OBS_SPAWN_DEPTH
    sta OBS_DRAW_FLAGS          ; OBS_DRAW_FLAGS = running spawn-depth accumulator
    ldx #$0000
obs_seed:
    .a16
    .i16
    lda #$0001
    sta OBS_ALIVE, x            ; mark live
    ; lane X
    ldy OBS_LANE
    lda obs_lane_x, y
    sta OBS_WX, x
    ; current tier = 3 (farthest/smallest; hysteresis grows it as it nears)
    lda #$0003
    sta OBS_TIER, x
    ; z (accumulated, descending)
    lda OBS_DRAW_FLAGS
    sta OBS_DEPTH, x
    sec
    sbc #OBS_DEPTH_STAGGER
    bcs obs_seed_dep_ok
    lda #OBS_NEAR_KILL          ; clamp (never seed below the cam)
obs_seed_dep_ok:
    .a16
    sta OBS_DRAW_FLAGS
    ; advance lane cursor (word offset, cycle 0..3 -> 0,2,4,6 bytes)
    lda OBS_LANE
    clc
    adc #2
    and #$0006
    sta OBS_LANE
    inx
    inx
    cpx #(2 * OBS_N)
    bne obs_seed

    sf_pool_init BUL_ALIVE, BUL_N
    rep #$30
    .a16
    .i16
    stz R_BANK

    spr_clear
    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP (display control): brightness $F = full,
                                ;   forced blank off — the screen turns on now
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt + joypad enable): VBlank NMI
                                ;   (bit 7) + auto joypad read (bit 0)
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — game_loop: one frame of strafe, fire, rail advance, project, draw
; =============================================================================
game_loop:
    .a16
    sf_frame_begin

    ; ---------------- ship frame defaults: straight, centered lean ----------
    lda #(VEHICLE_BASE + vehicle_f0)
    sta R_VTILE
    lda #$0080                  ; large (32x32), no flip, OBJ palette 0
    sta R_VFLAGS

    ; ---------------- strafe: LEFT/RIGHT slide the camera + lean the ship ---
    ; ship screen X follows the strafe direction (banking); camera posx moves
    ; laterally so the grid reacts in 3D.
    lda #SHIP_CENTER
    sta R_SHIPX
    stz OBS_DRAW_X              ; OBS_DRAW_X = bank target this frame (0 default)
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq sf_no_left
    ; camera left: posx -= STRAFE_SPEED (wrap to 1024 map)
    lda R_POSX + 2
    sec
    sbc #STRAFE_SPEED
    and #$03FF
    sta R_POSX + 2
    lda #(SHIP_CENTER - SHIP_LEAN)
    sta R_SHIPX
    lda #(VEHICLE_BASE + vehicle_f1)
    sta R_VTILE                 ; lean frame (drawn as-is = lean left)
    lda #($10000 - BANK_MAX)    ; bank target = -BANK_MAX (tilt left)
    sta OBS_DRAW_X
sf_no_left:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq sf_no_right
    lda R_POSX + 2
    clc
    adc #STRAFE_SPEED
    and #$03FF
    sta R_POSX + 2
    lda #(SHIP_CENTER + SHIP_LEAN)
    sta R_SHIPX
    lda #(VEHICLE_BASE + vehicle_f1)
    sta R_VTILE
    lda #$00C0                  ; lean frame H-flipped = lean right
    sta R_VFLAGS
    lda #BANK_MAX               ; bank target = +BANK_MAX (tilt right)
    sta OBS_DRAW_X
sf_no_right:
    .a16

    ; ---------------- fire: A (rising edge) spawns a forward bullet ---------
    ; The bullet is born at the ship's world X, just ahead of the camera in
    ; depth256, and travels forward (depth increases) faster than the rail
    ; closes obstacles, so it recedes up the screen toward the horizon.
    btnp #BTN_A
    beq fire_done
    sf_pool_spawn BUL_ALIVE, BUL_N
    bmi fire_done               ; pool full -> the press is swallowed
    lda R_POSX + 2
    sta BUL_WX, x
    lda #BUL_SPAWN_DEPTH
    sta BUL_DEPTH, x
fire_done:
    .a16
    .i16

    ; ---------------- banking: ease R_BANK toward the target ----------------
    ; R_BANK is a SIGNED heading offset; step it BANK_STEP/frame toward the
    ; target in OBS_DRAW_X (0 when neutral -> eases back to straight).
    ; diff = target - R_BANK (signed); sign of diff picks the step direction.
    lda OBS_DRAW_X
    sec
    sbc R_BANK                   ; A = target - R_BANK (signed)
    beq bank_done                ; already at target
    bmi bank_step_down           ; diff < 0 -> R_BANK above target, step down
    lda R_BANK                   ; diff > 0 -> step up
    clc
    adc #BANK_STEP
    sta R_BANK
    bra bank_done
bank_step_down:
    .a16
    lda R_BANK
    sec
    sbc #BANK_STEP
    sta R_BANK
bank_done:
    .a16
    ; heading angle byte = R_BANK low 8 bits (negative wraps to 256-n)
    lda R_BANK
    and #$00FF
    sta R_ANGLE

    ; ---------------- rail: auto-advance the camera world Y (floor stream) ---
    ; The camera streams forward along -Y for the floor-motion cue. This is
    ; decoupled from the obstacle depth axis (obstacles carry their own z
    ; scalar advanced below); the camera Y advance only drives the Mode 7 floor
    ; texture scroll (the visual backdrop).
    lda R_POSY + 2
    sec
    sbc #RAIL_SPEED
    and #$03FF
    sta R_POSY + 2

    ; ---------------- obstacles: close z (depth) toward the camera ----------
    ; Every live obstacle's forward depth z decrements RAIL_DEPTH_STEP/frame.
    ; When it reaches ~the camera (Z_NEAR) it recycles far ahead in a new lane.
    stz OBS_OFF
obs_move_loop:
    ldx OBS_OFF
    lda OBS_ALIVE, x
    beq obs_move_next
    lda OBS_DEPTH, x
    sec
    sbc #RAIL_DEPTH_STEP
    bcc obs_move_recycle         ; underflowed past 0 -> passed the camera
    cmp #OBS_NEAR_KILL
    bcc obs_move_recycle         ; reached the camera -> recycle
    sta OBS_DEPTH, x
    bra obs_move_next
obs_move_recycle:
    .a16
    .i16
    jsr obs_recycle              ; respawn far ahead, new lane (X = OBS_OFF)
obs_move_next:
    .a16
    .i16
    lda OBS_OFF
    clc
    adc #2
    sta OBS_OFF
    cmp #(2 * OBS_N)
    bcc obs_move_loop

    ; ---------------- bullets: travel forward (depth increases), die far ----
    stz BUL_OFF
bul_loop:
    ldx BUL_OFF
    lda BUL_ALIVE, x
    beq bul_next
    lda BUL_DEPTH, x
    clc
    adc #BUL_SPEED
    sta BUL_DEPTH, x
    cmp #(BUL_MAX_DEPTH + 1)
    bcc bul_next
    sf_pool_kill_x BUL_ALIVE
bul_next:
    .a16
    .i16
    lda BUL_OFF
    clc
    adc #2
    sta BUL_OFF
    cmp #(2 * BUL_N)
    bcc bul_loop

    ; ---------------- collisions: each live bullet vs each live obstacle ----
    jsr bullet_obstacle_hits

    ; ---------------- camera + Mode 7 service --------------------------------
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE
    sf_mode7_tick

    ; ---------------- draw: ship at OAM slot 0 -------------------------------
    spr_clear
    spr R_VTILE, R_SHIPX, #SHIP_Y, R_VFLAGS, #2

    ; ---------------- obstacle field — tier hysteresis + DEPTH-SORTED draw ---
    ; The obstacles are pseudo-3D depth actors (sf_rail). We do TWO things:
    ;   (1) a hysteresis pre-pass: per live obstacle, grow the STORED tier
    ;       (OBS_TIER[x]) as its z falls past a (threshold - TIER_HYST) grow
    ;       boundary — never shrink during the approach (z monotone down). This
    ;       keeps the proven grow-only hysteresis (no tier flicker).
    ;   (2) sf_rail_draw_sorted: project every obstacle and emit them into OAM
    ;       slots 1..OBS_N ORDERED BY THE STORED TIER — tier 0 (nearest/largest)
    ;       into the lowest slots so it draws IN FRONT of farther obstacles
    ;       (lower OAM index = front). This is the real depth-correct layering +
    ;       the recycle-pop fix: the OAM order is re-derived from depth each
    ;       frame, decoupled from the pool slot an obstacle happens to live in.
    ;
    ; --- (1) hysteresis pre-pass: update OBS_TIER[x] for each obstacle ---
    stz OBS_OFF
obs_hyst_loop:
    .a16
    .i16
    ldx OBS_OFF
    lda OBS_DEPTH, x
    sta z:PROJ_DEPTH            ; obs_tier_hysteresis reads z from PROJ_DEPTH
    jsr obs_tier_hysteresis     ; updates OBS_TIER[x] (grow-only)
    lda OBS_OFF
    clc
    adc #2
    sta OBS_OFF
    cmp #(2 * OBS_N)
    bcc obs_hyst_loop

    ; --- (2) fill the sf_rail param block, then the depth-sorted emit ---
    lda #OBS_ALIVE
    sta RAIL_PARAMS + $00
    lda #OBS_WX
    sta RAIL_PARAMS + $02
    lda #OBS_DEPTH
    sta RAIL_PARAMS + $04
    lda R_POSX + 2
    sta RAIL_PARAMS + $06       ; camera world X
    lda #OBS_N
    sta RAIL_PARAMS + $08
    lda #.loword(rail_tier_tbl)
    sta RAIL_PARAMS + $0A
    lda #RAIL_CACHE
    sta RAIL_PARAMS + $0C
    lda #OBS_TIER
    sta RAIL_PARAMS + $0E       ; stored (hysteresis-applied) tiers
    sf_rail_draw_sorted RAIL_PARAMS    ; emits OBS_N sprites at OAM slots 1..6

    ; ---------------- draw: bullets (slots 7..10) ---------------------------
    ; Every bullet slot is drawn each frame so OAM slots stay stable: live
    ; bullets at their projected ground position, dead/culled slots at y=$F0.
    stz BUL_OFF
draw_bul_loop:
    ldx BUL_OFF
    lda BUL_ALIVE, x
    beq draw_bul_dead
    ; project the bullet's world X + forward depth256
    lda BUL_WX, x
    sta z:PROJ_OBJ_X
    lda BUL_DEPTH, x
    sta z:PROJ_DEPTH
    lda R_POSX + 2
    sta z:PROJ_CAM_X
    jsr mode7_project
    lda z:PROJ_CULLED
    bne draw_bul_dead
    lda z:PROJ_SX
    sec
    sbc #4                      ; center the 8px tracer
    sta OBS_DRAW_X
    bra draw_bul_put
draw_bul_dead:
    .a16
    .i16
    lda #$00F0
    sta z:PROJ_SY
    stz OBS_DRAW_X
draw_bul_put:
    .a16
    .i16
    spr #(OBS_TILE_BASE + obs_bullet), OBS_DRAW_X, z:PROJ_SY, #$0002, #2
    lda BUL_OFF
    clc
    adc #2
    sta BUL_OFF
    cmp #(2 * BUL_N)
    bcc draw_bul_loop

    ; ---------------- draw: lock-on reticle (slot 11) -----------------------
    ; The reticle marks the aim point: a fixed forward depth ahead of the ship
    ; in the ship's lane, projected onto the floor so it tracks with the bank.
    ; This is the single-actor front door: sf_rail_project marshals
    ; (lane_x, depth_z, cam_x) into the projection block and JSRs mode7_project
    ; for us — the reticle sits in the ship's own lane (lane_x == cam_x).
    sf_rail_project R_POSX + 2, #RETICLE_DEPTH, R_POSX + 2
    lda z:PROJ_CULLED
    bne draw_ret_dead
    lda z:PROJ_SX
    sec
    sbc #8                      ; center the 16px reticle
    sta OBS_DRAW_X
    spr #(OBS_TILE_BASE + obs_reticle), OBS_DRAW_X, z:PROJ_SY, #$0002, #2
    bra draw_ret_done
draw_ret_dead:
    .a16
    .i16
    spr #0, #0, #$00F0, #0, #2
draw_ret_done:
    .a16
    .i16

    ; ---------------- heartbeat + state mirror -> debug region --------------
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    lda R_POSY + 2
    sta f:$7E0000 + $E012, x    ; camera Y (rail advance observable)
    lda R_POSX + 2
    sta f:$7E0000 + $E014, x    ; camera X (strafe observable)
    lda OBS_DEPTH + 0
    sta f:$7E0000 + $E016, x    ; obstacle slot 0 depth256 (approach/recycle obs)
    lda OBS_WX + 0
    sta f:$7E0000 + $E018, x    ; obstacle slot 0 world X (lane observable)
    lda R_ANGLE
    sta f:$7E0000 + $E01A, x    ; heading/bank angle (banking observable)
    sf_pool_count BUL_ALIVE, BUL_N
    ldx #$0000
    sta f:$7E0000 + $E01C, x    ; live bullet count (fire/travel/hit observable)
    sf_pool_count OBS_ALIVE, OBS_N
    ldx #$0000
    sta f:$7E0000 + $E01E, x    ; live obstacle count (always OBS_N; recycle)

    sf_frame_end
    jmp game_loop

; =============================================================================
; SUBROUTINES — the jsr'd frame helpers + the one-time sky-split arm
; =============================================================================

; =============================================================================
; bullet_obstacle_hits — kill any (bullet, obstacle) pair within the hit window.
; =============================================================================
; For each live bullet, take its depth256 + lane X, then scan live obstacles: a
; pair within HIT_DEPTH_TOL (depth256) AND HIT_X_TOL (lateral world px) kills
; both — the bullet is freed and the obstacle recycles far ahead.
; WIDTH-RISK: A16/I16 entry and exit; no width toggle. Calls obs_recycle, abs16.
bullet_obstacle_hits:
    .a16
    .i16
    stz BUL_OFF
boh_b_loop:
    ldx BUL_OFF
    lda BUL_ALIVE, x
    bne boh_b_live
    jmp boh_b_next
boh_b_live:
    .a16
    .i16
    ; bullet depth256 + lane X
    lda BUL_DEPTH, x
    sta BHIT_DEPTH
    lda BUL_WX, x
    sta BHIT_X
    stz OBS_OFF
boh_o_loop:
    ldx OBS_OFF
    lda OBS_ALIVE, x
    bne boh_o_live
    jmp boh_o_next
boh_o_live:
    .a16
    .i16
    ; |bullet_depth256 - obs_depth256| < HIT_DEPTH_TOL ?
    lda OBS_DEPTH, x
    sec
    sbc BHIT_DEPTH              ; obs_depth - bullet_depth (signed-ish)
    jsr abs16
    cmp #HIT_DEPTH_TOL
    bcs boh_o_next
    ; |bullet_x - obs_x| < HIT_X_TOL ?
    ldx OBS_OFF
    lda OBS_WX, x
    sec
    sbc BHIT_X
    jsr abs16
    cmp #HIT_X_TOL
    bcs boh_o_next
    ; HIT — free the bullet, recycle the obstacle far ahead
    ldx BUL_OFF
    sf_pool_kill_x BUL_ALIVE
    ldx OBS_OFF
    jsr obs_recycle
    jmp boh_b_next              ; this bullet is spent
boh_o_next:
    .a16
    .i16
    lda OBS_OFF
    clc
    adc #2
    sta OBS_OFF
    cmp #(2 * OBS_N)
    bcs boh_b_next
    jmp boh_o_loop
boh_b_next:
    .a16
    .i16
    lda BUL_OFF
    clc
    adc #2
    sta BUL_OFF
    cmp #(2 * BUL_N)
    bcs boh_done
    jmp boh_b_loop
boh_done:
    .a16
    .i16
    rts

; =============================================================================
; abs16 — A = |A| (16-bit signed). Clobbers nothing but A. A16 entry/exit.
; =============================================================================
abs16:
    .a16
    bpl abs16_done
    eor #$FFFF
    inc a
abs16_done:
    .a16
    rts

; =============================================================================
; obs_recycle — respawn the obstacle at byte offset X far ahead, new lane.
; =============================================================================
; Sets forward depth z = OBS_SPAWN_DEPTH (far edge), world X = the next lane,
; and resets the current tier to 3 (farthest) so the grow-only hysteresis
; restarts. X (the pool byte offset) is preserved. OBS_LANE cycles the lanes.
; WIDTH-RISK: A16/I16 entry and exit; no width toggle.
obs_recycle:
    .a16
    .i16
    lda #OBS_SPAWN_DEPTH
    sta OBS_DEPTH, x
    lda #$0003
    sta OBS_TIER, x             ; reset to farthest tier on recycle
    phx
    ldy OBS_LANE
    lda obs_lane_x, y
    plx
    sta OBS_WX, x
    lda OBS_LANE
    clc
    adc #2
    and #$0006                  ; cycle 0,2,4,6 (4 lane words)
    sta OBS_LANE
    rts

; =============================================================================
; obs_tier_hysteresis — apply grow-only size-tier hysteresis.
; =============================================================================
; On entry X = pool byte offset, PROJ_DEPTH = the obstacle's z (world px). The
; obstacle's z is monotone DECREASING as it approaches, so its tier only ever
; GROWS (number decreases, 3 -> 0). To stop boundary flicker, a tier only
; advances when z falls a TIER_HYST margin BELOW the threshold for the smaller
; (bigger) tier. The stored tier in OBS_TIER[x] never shrinks until recycle.
; The effective tier lands in PROJ_TIER (so the existing dispatch is unchanged)
; and is written back to OBS_TIER[x]. A16/I16 entry and exit; no width toggle.
; WIDTH-RISK: A16/I16 entry and exit; no width toggle.
obs_tier_hysteresis:
    .a16
    .i16
    ; candidate = stored tier; try to grow one step at a time toward 0.
    lda OBS_TIER, x
    ; from tier 3: grow to 2 once z < (TIER_T2 - TIER_HYST)
    cmp #3
    bne @from2
    lda z:PROJ_DEPTH
    cmp #(PROJ_TIER_T2 - TIER_HYST)
    bcs @keep3                  ; z still >= grow boundary -> stay tier 3
    lda #2
    bra @check_more
@keep3:
    .a16
    lda #3
    bra @store
@from2:
    .a16
    lda OBS_TIER, x
    cmp #2
    bne @from1
    lda #2
@check_more:
    .a16
    ; (A = 2) grow to 1 once z < (TIER_T1 - TIER_HYST)
    lda z:PROJ_DEPTH
    cmp #(PROJ_TIER_T1 - TIER_HYST)
    bcs @use2
    lda #1
    bra @check_more1
@use2:
    .a16
    lda #2
    bra @store
@from1:
    .a16
    lda OBS_TIER, x
    cmp #1
    bne @from0
    lda #1
@check_more1:
    .a16
    ; (A = 1) grow to 0 once z < (TIER_T0 - TIER_HYST)
    lda z:PROJ_DEPTH
    cmp #(PROJ_TIER_T0 - TIER_HYST)
    bcs @use1
    lda #0
    bra @store
@use1:
    .a16
    lda #1
    bra @store
@from0:
    .a16
    lda #0                      ; already at the biggest tier; stays
@store:
    .a16
    .i16
    sta OBS_TIER, x
    sta z:PROJ_TIER
    rts

; =============================================================================
; obs_lane_x — the four lateral lanes obstacles spawn into (world X, 0..1023).
; =============================================================================
; Centred around the spawn column (START_X = 512); offsets -48..+48 so the field
; reads as distinct lanes you weave between (the pinhole fan spreads them across
; the screen as they near; near the horizon they converge to centre).
obs_lane_x:
    .word 512, 464, 560, 488

; =============================================================================
; arm_sky_split — reveal the sky above the horizon (call once, A16/I16 entry).
; =============================================================================
; Identical mechanism to the racer: a 2-band $212C (TM) HDMA on CH2 — BG1 off
; above the horizon (the reserved CGRAM[0] sky backdrop shows), BG1+OBJ below.
; CH2 is the idle placeholder hdma_alloc pins; programmed directly + ORed into
; NMI_HDMA_ENABLE (the NMI re-arms $420C, leaving CH2's config alone since it is
; not Mode-7-owned). See templates/racer/main.asm for the full rationale.
;
; WIDTH-RISK: entry A16/I16. Sets A8 for the $43xx byte writes + the
; NMI_HDMA_ENABLE RMW, restores caller width via PLP. I16 unchanged.
arm_sky_split:
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #$0000
    lda #(SKY_HORIZON)          ; N lines, non-repeat (bit7=0)
    sta f:SKY_SPLIT_TABLE + 0, x
    lda #$10                    ; BG1 off, OBJ on -> sky backdrop
    sta f:SKY_SPLIT_TABLE + 1, x
    lda #$01                    ; 1 line, non-repeat
    sta f:SKY_SPLIT_TABLE + 2, x
    lda #$11                    ; BG1 + OBJ -> Mode 7 floor
    sta f:SKY_SPLIT_TABLE + 3, x
    lda #$00                    ; terminator (TM holds $11 below)
    sta f:SKY_SPLIT_TABLE + 4, x
    lda #$00
    sta $4320                   ; DMAP2: A->B, absolute table, 1 byte -> 1 reg
    lda #$2C
    sta $4321                   ; BBAD2: $212C (TM)
    lda #<SKY_SPLIT_TABLE
    sta $4322                   ; A1T2L
    lda #>SKY_SPLIT_TABLE
    sta $4323                   ; A1T2H
    lda #^SKY_SPLIT_TABLE
    sta $4324                   ; A1B2 (bank $7E)
    lda NMI_HDMA_ENABLE
    ora #$04
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
    rts

; =============================================================================
; DATA — engine link-partners (sf_mode7.inc order) + sprite/DMA engines, then
; the per-tier table, projection LUTs, ship + obstacle art, and the ground blob
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "input_handler.asm"        ; engine_btn / engine_btnp (A = fire)

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "mode7_math.asm"

.segment "RODATA"

; =============================================================================
; rail_tier_tbl — per-tier OBJ descriptor (sf_rail_draw_sorted reads this).
; =============================================================================
; 4 rows, tier 0..3, each {tile, flags, center_off} (3 words). The draw routine
; orders + selects by the obstacle's STORED tier (OBS_TIER, grow-only
; hysteresis), then emits at PROJ_SX - center_off. The tile / flag / centre
; mapping for each tier:
;   tier 0 = 32x32 full   (OAM size large, centre 16)
;   tier 1 = 32x32 medium (OAM size large, centre 16)
;   tier 2 = 16x16 full   (OAM size small, centre 8)
;   tier 3 = 16x16 tiny   (OAM size small, centre 8)
rail_tier_tbl:
    .word (OBS_TILE_BASE + obs_t0), $0082, 16    ; tier 0: nearest/largest
    .word (OBS_TILE_BASE + obs_t1), $0082, 16    ; tier 1
    .word (OBS_TILE_BASE + obs_t2), $0002, 8     ; tier 2
    .word (OBS_TILE_BASE + obs_t3), $0002, 8     ; tier 3: farthest/smallest

.include "mode7_pv_ztable.inc"
.include "assets/mode7_project.inc" ; baked projection LUT + PROJ_* equates
                                    ; (must precede mode7_project.asm: the
                                    ; routine's bucket shift uses PROJ_Q_LOG2)

.segment "CODE"
.include "mode7_project.asm"        ; ground-plane projection (needs smul16)
.include "rail_draw.asm"            ; sf_rail_draw_sorted -> depth-sorted OAM emit
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- first-party assets ---
.include "assets/vehicle.inc"
.include "assets/obstacles.inc"     ; obstacle/reticle/bullet CHR + OBJ palette
.include "assets/ground_palette.inc"

; --- the 32KB interleaved grid-terrain blob (bank 1 of the 64KB image) ---
.segment "BANK1"
; .incbin path: resolved relative to THIS file's dir, not via -I — so the
; "assets/<basename>" form is copy-safe (copy-to-adapt only changes the basename).
ground_map:
    .incbin "assets/ground_map.bin"
