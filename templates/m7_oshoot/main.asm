; =============================================================================
; m7_oshoot — Mode 7 rotating-floor OVERHEAD SHOOTER (rotating Mode 7 floor) — S1..S6
; =============================================================================
; The genre rail for a top-down run-and-gun on a ROTATING Mode 7 ground plane
; (rotating-floor overhead-stage run-and-gun). FORKED from m7_dungeon: it
; keeps the static-affine rotating floor + the world->screen TRANSPOSE-matrix
; sprite projection + the world-space gameplay model, and swaps the dungeon's
; tank controls for "face-where-you-move" 8-WAY aim/move (model A), adds a
; sf_pool BULLET pool projected onto the spinning floor, timed enemy WAVES, and
; world-space bullet<->enemy collision.
;
; CONTROL MODEL A (owner-locked): the D-pad picks one of 8 compass headings and
; moves the player's WORLD position along it; R_ANGLE snaps to that heading so
; the floor rotates and the player's facing always reads "up". Fire (A) shoots
; FORWARD along the facing (up on screen = along the heading in world). The last
; facing PERSISTS when stationary, so stand-and-shoot works.
;
; The floor is the Mode 7 BG, scaled+rotated as one rigid image by a single
; UNIFORM affine matrix (sf_mode7_affine.inc — the same static-affine path the
; boss rail uses). The hero is an OBJ composited over it at screen centre; the
; affine matrix never touches OBJ, so the hero stays pinned + upright while the
; world spins beneath.
;
; THE ARCHITECTURE (static-affine, ~no HDMA):
;   - sf_boss_mode7_on installs Mode 7 with M7_PV_ACTIVE=1 so the STOCK engine
;     NMI commits M7SEL/M7X/M7Y + scroll from shadows. NO custom NMI handler, no
;     perspective HDMA — a uniform matrix is ~50 cycles, not the ~10k perspective
;     rebuild.
;   - sf_boss_center world_x, world_y  pins the player's WORLD (x,y) to screen
;     centre (128,112) every frame: a per-frame MOVING PIVOT. The pivot is the
;     centre of rotation, so pinning it to the player keeps the player centred as
;     the floor spins. (Net-new vs the boss, which pins the pivot ONCE — here it
;     moves each frame. It is just a shadow write the stock NMI already commits.)
;   - sf_boss_matrix #SCALE, angle  rotates the whole plane uniformly so the
;     player's facing reads "up". SCALE=$0100 (1.0) = flat, no zoom. Call FIRST
;     after sf_frame_begin so the whole visible frame reads one matrix.
;
; S1 SCOPE: 8-WAY aim/move (control model A) over the m7_dungeon spine —
;   - The D-pad picks one of 8 compass headings (dir8_angle table) and snaps
;     R_ANGLE to it; the SAME R_ANGLE drives sf_boss_matrix, so the floor rotates
;     and the player's facing always reads "up". Facing PERSISTS when no direction
;     is held (R_MOVING=0) so stand-and-shoot works.
;   - While a direction is held the world advances FORWARD along the facing at a
;     fixed MOVE_SPEED (pos -= sincos*speed: DX=-sina, DY=-cosa, the m7_dungeon
;     sign convention), so the floor SCROLLS in the faced direction.
; MOVE_SPEED is capped SLOW (<= ~1.25 px/frame) so per-step collision cannot
; tunnel a 2-tile (16px) wall in a single step.
;
; WORLD-SPACE WALL COLLISION (kept from m7_dungeon) — the hero must NOT pass
; walls. Collision is done in WORLD space, independent of the render rotation:
;   - dungeon_terrain.bin (128x128 byte LUT, 1=solid/0=floor) is emitted from the
;     SAME is_wall() predicate that paints the wall art, so "what you see is what
;     blocks you" by construction. A world pixel (wx,wy) maps to tile (wx>>3,
;     wy>>3) and reads terrain[ty*128+tx].
;   - CANDIDATE-TEST-COMMIT + PER-AXIS SLIDE: each axis is committed only if its
;     candidate footprint is clear, so a diagonal push into an axis-aligned wall
;     SLIDES along it (the unblocked axis still progresses).
;   - HERO FOOTPRINT: an 8px box (HALF=4) whose 4 world corners are sampled.
; DBG_BLOCK_CT mirrors the blocked-axis count.
;
; S2 SCOPE: sf_pool BULLETS fired along the facing, advanced in WORLD space.
; S3 SCOPE: bullet PROJECTION onto the rotating floor (draw_bullets, transpose
;   matrix, shared M7A_SAV..D snapshot) — THE CRUX (the projection 3-time-bug
;   class). S4 SCOPE: timed enemy WAVES (sf_pool) chasing the player in world
;   space, projected onto the floor. S5 SCOPE: bullet<->enemy WORLD-SPACE box
;   collision (rotation-invariant, never reads the matrix) + hero CONTACT
;   knockback+HITS (kept from m7_dungeon).
;
; OBJ-OVER-MODE-7 (baked in): the Mode 7 map fills VRAM words $0000-$3FFF, so the
; OBJ name base moves to word $4000 (OBSEL=$62); the hero CHR uploads there and
; the OAM tile number stays 0 relative to that base.
;
; Build:  make m7_oshoot   (the generic templates rule reads the LDCFG sentinel)
; LDCFG: lorom_64k.cfg
;   ^ Linker-config sentinel (GAP-2): 64KB image, the 32KB floor-map blob fills
;     BANK1. The generic build/%.sfc rule reads this and links lorom_64k.cfg.
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (rising-edge fire) + buttons.inc
.include "sf_pool.inc"          ; sf_pool_init/spawn/kill_x/count (bullet + enemy pools)
.include "sf_mode7.inc"         ; sf_mode7_load_map (the VRAM map DMA wrapper)
.include "sf_mode7_affine.inc"  ; sf_boss_mode7_on / sf_boss_center / sf_boss_matrix
.include "engine_state.inc"

; --- collision toggle (negative control). Build with -DNO_COLLISION=1 to DISABLE
;     the wall reject so the test can confirm the assertion catches a real failure
;     (the hero then WALKS THROUGH walls). Default = collision ON. ---
.ifndef NO_COLLISION
NO_COLLISION = 0
.endif

; --- sprite-size regression toggle (negative control for the phantom-diamond
;     bug). Build with -DBUGGY_SPRITE_SIZE=1 to RESTORE the old size bit (bit7
;     SET) on the hero + enemies, selecting the 32x32 LARGE size of OBSEL pair
;     $62. A 32x32 hero at tile 0 then reads a 4x4 tile block whose lower-left
;     quadrant is tile 32 = the enemy CHR -> a phantom yellow diamond bleeds
;     into the hero. Default = 16x16 (bit7 CLEAR), the correct size. The
;     regression test asserts the size bit is CLEAR / no diamond, and the
;     BUGGY build FAILS it (proving non-vacuity). ---
.ifndef BUGGY_SPRITE_SIZE
BUGGY_SPRITE_SIZE = 0
.endif
.if BUGGY_SPRITE_SIZE = 0
HERO_SIZE_BIT  = $0000          ; bit7 CLEAR -> 16x16 (small size of OBSEL $62)
ENEMY_SIZE_BIT = $0000
.else
HERO_SIZE_BIT  = $0080          ; bit7 SET -> 32x32 LARGE (the phantom-diamond bug)
ENEMY_SIZE_BIT = $0080
.endif

; --- S3 bullet-projection NON-VACUITY toggle. Build with -DBULLET_PROJ_FORWARD=1
;     to project bullets with the FORWARD (screen->texel) matrix [[A,B],[C,D]]
;     instead of its inverse (the TRANSPOSE [[A,C],[B,D]]). Bullets then rotate
;     the WRONG way and SWIM onto the walls under floor rotation. The rendered-
;     floor S3 test must FAIL on this build (a held bullet lands on WALL pixels at
;     rotated angles) and PASS on the default — proving the floor test is not
;     vacuous. Default = the correct TRANSPOSE projection. ---
.ifndef BULLET_PROJ_FORWARD
BULLET_PROJ_FORWARD = 0
.endif

; --- S5 bullet<->enemy collision toggle (negative control). Build with
;     -DNO_BULLET_COLLISION=1 to DISABLE the world-space bullet<->enemy overlap
;     so bullets pass THROUGH enemies (enemies survive at every angle). The S5
;     hit-through-rotation test must FAIL on this build (enemy not killed) —
;     proving the collision assertion is not vacuous. Default = collision ON. ---
.ifndef NO_BULLET_COLLISION
NO_BULLET_COLLISION = 0
.endif

; --- S3 FROZEN-BULLET test hook. Build with -DDBG_FROZEN_BULLET=1 to freeze
;     bullets at their spawn world spot (velocity ignored). The S3 glue-through-
;     rotation test (#3) fires ONE bullet at a known floor spot, then snaps the
;     plane through a heading sweep; the frozen bullet (fixed WORLD pos) must stay
;     glued to the SAME rendered FLOOR spot at every angle (it orbits screen-
;     centre with the floor, never swimming onto a wall). Default = bullets move.
.ifndef DBG_FROZEN_BULLET
DBG_FROZEN_BULLET = 0
.endif

; --- world geometry ---
SCALE_VIEW = $0100              ; 1.0 screen->texel (FLAT, no zoom — per S1 spec)
WORLD_MAX  = 1023               ; walkable plane is 0..1023 px (128 tiles * 8)
HERO_HALF  = 4                  ; footprint half-extent: 8px box (near pos-4 .. far pos+3)

; --- 8-WAY aim/move tuning (S1: control model A) -----------------------------
; The D-pad picks one of 8 compass headings (R_ANGLE in 32-unit steps) and the
; player MOVES forward along it at a FIXED speed (8.8). Facing = move direction,
; so the floor rotates to read "up" and the last facing persists when idle.
; Speed is capped SLOW (<= ~1.25 px/frame) so S3's per-step collision can't
; tunnel a 2-tile (16px) wall in a single step.
MOVE_SPEED = $0140              ; +1.25 px/frame world move along the heading (8.8)

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_DOWN  = $0400
JOY_UP    = $0800
JOY_Y     = $4000
JOY_B     = $8000

; --- 8-way heading table: a D-pad direction code 0..8 -> R_ANGLE (model A). The
;     code is a bitfield UDLR built below (U=8 D=4 L=2 R=1); the table maps each
;     valid single/diagonal combination to the compass heading whose FORWARD
;     world motion (pos -= sincos*speed: DX=-sina, DY=-cosa) points that way:
;       UP(0,-Y)=0  UP+LEFT=32  LEFT(-X,0)=64  DOWN+LEFT=96  DOWN(0,+Y)=128
;       DOWN+RIGHT=160  RIGHT(+X,0)=192  UP+RIGHT=224. $FFFF = no/invalid dir
;     (opposite pair pressed) -> keep the last facing (stand-and-shoot). ---
DIR_NONE = $FFFF
; (the dir8_angle lookup table lives in RODATA near the bottom — it MUST NOT be
;  emitted here: header.inc leaves the assembler in the VECTORS segment until the
;  first .segment "CODE", so a .word table here would overflow the 32-byte
;  VECTORS area. See dir8_angle: below the engine link partners.)

; --- spawn: the ARENA CENTRE (world tile 64,64 -> px 516,516), open floor with
;     room in every direction so the wave RING spawns (player +/-120px) land
;     inside the playable arena, not the surrounding wall/void. Overridable via
;     -DSPAWN_TX / -DSPAWN_TY. See make_arena.py (playable tiles [7,121]). ---
.ifndef SPAWN_TX
SPAWN_TX = 64
.endif
.ifndef SPAWN_TY
SPAWN_TY = 64
.endif
SPAWN_PX = SPAWN_TX * 8 + 4      ; 516 (default, arena centre)
SPAWN_PY = SPAWN_TY * 8 + 4      ; 516

; --- hero screen placement (16x16 centred at screen 128,112) ---
HERO_X = 128 - 8
HERO_Y = 112 - 8

; --- game DP state (kit contract: $32-$5F; matches the mode7_flight register
;     file so S2 can splice the tank integrator in over this layout) ---
R_POSX   = $32                   ; world x, 16.16 (frac word @ +0, integer px @ +2)
R_POSY   = $36                   ; world y, 16.16
R_ANGLE  = $3A                   ; heading (low byte 0..255), drives the matrix
R_MOVING = $3C                   ; 1 = a direction is held this frame (commit the
                                 ;     world step); 0 = idle (facing persists, no move)
DIR_BITS = $3D                   ; one-frame UDLR bitfield scratch (built each frame
                                 ;     from the D-pad, indexes dir8_angle)

; --- S3 collision scratch (game DP $3E-$4F; one-frame scratch, not persistent.
;     $50+ is engine-owned Mode 7 HDMA state — do NOT spill collision scratch
;     there). ----------------------------------------------------------------
STEP_FX  = $3E                   ; this-frame X step 16.16 frac (sina*speed)
STEP_PX  = $40                   ;   ... integer (signed, full 16-bit)
STEP_FY  = $42                   ; this-frame Y step 16.16 frac (cosa*speed)
STEP_PY  = $44                   ;   ... integer
CAND_FRAC = $46                  ; candidate frac word (committed on a clear axis)
CAND_PX  = $48                   ; candidate world x integer px (footprint centre)
CAND_PY  = $4A                   ; candidate world y integer px (footprint centre)
T_PTR    = $4C                   ; 3-byte 24-bit pointer into terrain LUT
SCR_TX   = $4F                   ; scratch: tile x for a corner probe (0..127)

; --- S4 enemy sprite projection -------------------------------------------
; STATIC enemies live at fixed WORLD positions and are PROJECTED onto the
; rotating Mode 7 plane each frame, so they stay glued to their world tile as
; the floor rotates AND scrolls. world->screen needs the INVERSE of the Mode 7
; FORWARD (screen->texel, rotate by -theta) matrix M=[[A,B],[C,D]]. At the fixed
; scale 1.0 here M is a pure rotation, so its inverse is the TRANSPOSE [[A,C],
; [B,D]]; with ONE matrix per frame:
;   (sx,sy) = ( (dx*A + dy*C) >> 8 , (dx*B + dy*D) >> 8 ) + (128,112)
; where (dx,dy) = enemy_world - PIVOT (the player's world pos, = screen centre)
; and A,B,C,D are the SAME M7A-M7D sf_boss_matrix just committed this frame —
; we read them straight out of the API block ($60-$66) BEFORE any spr clobbers
; that DP, then save them in scratch for the per-enemy loop.
; S4: enemies are now a sf_pool of WAVE chasers (timed spawns at a world ring,
; chase toward the player). ENEMY_COUNT = the pool size (slots managed every
; frame for stable OAM). The per-slot LIVE world pos lives in the DBG_ENE_BASE
; mirror (now pool-indexed; dead slots are parked). The enemy pool ALIVE array +
; the wave/chase machinery replace the old fixed-3 corridor patrol.
;   WRAM enemy pool (disjoint from the bullet pool $1800-$185F):
;     ENE_ALIVE $1860  alive[ENEMY_COUNT]  (the live world x/y are the
;                      DBG_ENE_BASE mirror +0/+2, indexed by slot).
ENEMY_COUNT = 6                  ; enemy pool size (wave chasers)
ENE_ALIVE  = $1860               ; sf_pool alive array (disjoint from bullets)
ENEMY_TILE_OBJ = 32              ; OAM tile # (rel OBJ name base $4000): VRAM word
                                 ; $4200 = enemy CHR (hero owns OAM tiles 0..17).
ENEMY_OBJ_VTILE = 1024 + 32      ; absolute VRAM tile for sf_load_obj_chr (word $4200)
; FLAGS low byte = VH00_PPPn: bit7 = OBJ size-select, bits3:1 = OBJ palette
; (PPP), bit0 = name/tile-high (n). With OBSEL pair $62, bit7 CLEAR = the SMALL
; 16x16 size; bit7 SET = the LARGE 32x32 size. We want 16x16, so bit7 stays
; CLEAR. OBJ palette 1 => PPP=001 => bits3:1=%001 => $02.
; (The old $0081 set bit0=name instead, pushing the lookup to tile 256+32=288
; (empty VRAM -> invisible) AND selecting palette 0 (the hero's cyan). The old
; $0082 also set bit7, selecting the 32x32 LARGE size — a latent foot-gun: a
; 32x32 enemy reads a 4x4 tile block and would bleed the hero CHR. $0002 keeps
; the name bit clear (OAM tile stays 32, where the enemy CHR lives), the size
; bit clear (16x16), and selects OBJ palette 1 (red enemy_pal, CGRAM 144..).)
ENEMY_ATTR = $0002 | ENEMY_SIZE_BIT  ; size bit7 CLEAR (16x16) + OBJ palette 1 (PPP=%001)
ENEMY_PRI  = 2                   ; same BG priority band as the hero
SCREEN_CX  = 128                 ; affine pivot renders the player here (X)
SCREEN_CY  = 112                 ;   ... and here (Y)
OBJ_HALF   = 8                   ; 16x16 sprite: OAM (x,y) = centre - 8
CULL_Y     = $00F0               ; park off-screen Y (kit convention)
CULL_MARGIN = 16                 ; px slack so a 16px sprite half-on-screen still shows

; --- S2 BULLET POOL (sf_pool) ----------------------------------------------
; Fire (A, rising edge) spawns a bullet at the hero WORLD pos with a velocity
; along the facing (forward = -(sincos)*speed, the m7_dungeon step convention).
; Bullets travel in WORLD space and despawn at max range (a TTL countdown).
; S3 projects them onto the rotating floor via the SAME transpose matrix the
; enemies use (the shared M7A_SAV..D snapshot).
;
; WRAM POOL-ARRAY MAP (the $1800-$1DFF game-array region; sf_pool.inc requires
; plain absolute addressing reachable with DB=$00, i.e. low-WRAM $0000-$1FFF):
;   BUL_ALIVE $1800  alive[8]   (0=free, 1=live)
;   BUL_X     $1810  world x[8] (16-bit integer px)
;   BUL_Y     $1820  world y[8]
;   BUL_VX    $1830  world step x[8] per frame (signed, set at fire)
;   BUL_VY    $1840  world step y[8] per frame (signed)
;   BUL_TTL   $1850  frames-to-live[8] (max-range despawn)
;   -> bullets occupy $1800-$185F. The enemy pool (S4) takes $1860-$18BF
;      (disjoint). OAM slots are disjoint too (see OAM SLOT MAP below).
BULLET_N   = 8
BUL_ALIVE  = $1800
BUL_X      = $1810
BUL_Y      = $1820
BUL_VX     = $1830
BUL_VY     = $1840
BUL_TTL    = $1850
BULLET_SPEED = $0300             ; +3.0 px/frame world travel (8.8) — fast, fits
                                 ;   the projection cull; <=8 so it can't tunnel a
                                 ;   16px enemy box between frames (col asserts <=8)
BULLET_TTL = 90                  ; max range in frames (3px/f * 90 = 270 world px)
; OAM SLOT MAP (128 entries; disjoint ranges per subsystem). engine_spr assigns
; slot = call order after spr_clear (SPR_ORDER_MODE=2 stable), so the draw order
; below fixes the slots:
;   slot 0                       : hero (16x16, centred + upright)
;   slots 1..ENEMY_COUNT         : enemies (one slot each — 16x16)   [1..6]
;   slots (1+ENEMY_COUNT)..       : bullets (BULLET_N slots — 16x16)  [7..14]
; Drawing EVERY pool slot every frame (live at pos, dead parked at Y=$F0) keeps
; slot identity stable so a test can read an actor by its OAM slot.
BULLET_OAM0 = 1 + ENEMY_COUNT    ; first bullet OAM slot (draw order: after enemies)
; bullet sprite: reuse the enemy CHR (tile 32) but the bullet's OWN OBJ palette
; (palette 2) so a rendered bullet reads distinct from the red enemy. 16x16, no
; size bit (Trap 4: keep bullets 16x16, never set the OBSEL phantom-diamond bit).
BULLET_TILE_OBJ = 32
BULLET_ATTR = $0004              ; OBJ palette 2 (PPP=%010 -> bits3:1=%010=$04),
                                 ;   name bit 0, size bit7 CLEAR (16x16)
BULLET_PRI  = 2

; --- S4 projection scratch (REUSES the S3 collision DP $3E-$4F: that scratch is
;     one-frame and DEAD by the time projection runs — after move_x/move_y AND
;     after the matrix is committed. No new ES_* needed; zp-check stays clean). --
M7A_SAV  = $3E                   ; saved M7A (cos*scale>>8) for this frame
M7B_SAV  = $40                   ; saved M7B (sin*scale>>8)
M7C_SAV  = $42                   ; saved M7C (-M7B)
M7D_SAV  = $44                   ; saved M7D (= M7A)
ENE_IDX  = $46                   ; per-enemy loop index (0..ENEMY_COUNT-1)
PRJ_DX   = $48                   ; enemy_world_x - pivot_x (signed)
PRJ_DY   = $4A                   ; enemy_world_y - pivot_y (signed)
PRJ_SX   = $4C                   ; projected screen x (signed, pre-cull); then OAM x
PRJ_SY   = $4E                   ; projected screen y (signed, pre-cull); then OAM y
; proj_sum (s32 multiply-accumulate) reuses math_p's UNUSED high 4 bytes ($BC-$BF):
; smul16 writes only math_p+0..+3, so $BC-$BF are dead engine scratch during the
; projection — no new game-DP slot needed (keeps zp-check clean).
proj_sum = $BC

; --- S5 patrol/contact scratch (REUSES the same one-frame $46-$4F scratch).
;     patrol_enemies + contact_enemies run AFTER the matrix snapshot (so M7A_SAV
;     ..M7D_SAV $3E-$44 must survive) and BEFORE draw_enemies (which re-inits its
;     own ENE_IDX/PRJ_* scratch). The footprint test reuses CAND_PX/CAND_PY
;     ($48/$4A) + footprint_solid's T_PTR/SCR_TX ($4C-$4F); PAT_IDX ($46) is the
;     ONLY slot the footprint call must not clobber — and it does not (it uses
;     $48-$4F). So nothing here touches $3E-$44. No new DP; zp-check stays clean.
PAT_IDX  = $46                   ; patrol/contact per-enemy loop index

; --- debug mirrors (relative to $7E:E000, read by the test) ---
DBG_HEARTBEAT = $E010            ; 2B frame counter
DBG_POSX      = $E012            ; 2B world x integer px
DBG_POSY      = $E014            ; 2B world y integer px
DBG_ANGLE     = $E016            ; 2B heading
DBG_BLOCK_CT  = $E018            ; 2B count of blocked axis-steps (collision proof)
DBG_LASTTERR  = $E01A            ; 2B last terrain class read (footprint corner)
; S4 per-enemy mirrors: world (x,y) then projected screen (sx,sy), 8 bytes each.
; The test reads these as the projection OUTPUT oracle (computed vs ROM).
DBG_ENE_BASE  = $E020            ; ENEMY_COUNT * 8 bytes:
                                 ;   +0 world_x  +2 world_y  +4 screen_x  +6 screen_y
DBG_ENE_STRIDE = 8

; --- S4 WAVE SPAWN + CHASE, S5 CONTACT -------------------------------------
; S4 turns the enemies into a sf_pool of WAVE CHASERS:
;   - WAVE SPAWN: a SPAWN_T countdown (shmup cadence) spawns one enemy every
;     SPAWN_PERIOD frames at a world-RING position around the player (a few fixed
;     ring offsets cycled by a cursor), so enemies POP IN from off-screen.
;   - CHASE: each frame every live enemy steps ENEMY_SPEED px toward the player's
;     world pos (per-axis sign-of-delta), with the SAME world-space footprint_solid
;     LUT test so it never walks through an arena wall/obstacle. The live world pos
;     is the DBG_ENE_BASE +0/+2 mirror (pool-indexed), which draw_enemies projects.
; This exercises projection under BOTH rotation (the floor) and translation (the
; chasers move + the player moves).
;
; S5 CONTACT (kept from the dungeon brick): each frame, a WORLD-space box overlap
; between the hero + each live enemy. On contact the hero is knocked back to spawn
; (R_POSX/Y = spawn) and a HITS counter ticks, with a post-respawn GRACE window.
ENEMY_SPEED  = 1                 ; world px/frame each chaser steps toward the player
SPAWN_PERIOD = 50                ; frames between wave spawns (shmup cadence)
RING_N       = 8                 ; ring_off table entries (8 compass spawn offsets)
CONTACT_HALF = 6                 ; world-box half-extent for hero-enemy overlap
                                 ;   (12x12 box centred on each body: |dx|<12 AND
                                 ;    |dy|<12 = contact). Sized for a forgiving
                                 ;    overhead-shooter touch with 16px sprites.
GRACE_FRAMES = 40                ; post-respawn frames with contact suppressed
BULHIT_HALF  = 8                 ; bullet<->enemy world-box half-extent: overlap iff
                                 ;   |bx-ex| < 2*BULHIT_HALF AND |by-ey| < 2*. A 16px
                                 ;   box centred on each body — a forgiving hit for
                                 ;   the 16x16 sprites. WORLD-space (never reads the
                                 ;   matrix) -> the hit is ROTATION-INVARIANT.

; --- S5 debug mirrors (in the free gap $E01C-$E01F between DBG_LASTTERR and
;     DBG_ENE_BASE) ---
DBG_HITS      = $E01C            ; 2B hero-enemy contact (knockback) counter
DBG_GRACE     = $E01E            ; 2B post-respawn grace countdown (frames left)
; (the old ENE_DIR_BASE patrol-state table is GONE — chasers steer toward the
;  player each frame, no persistent per-enemy direction is needed.)

; --- S2 BULLET debug mirrors (read by the test; in the free $E050.. gap) ---
DBG_BUL_COUNT = $E050            ; 2B live bullet count (sf_pool_count)
DBG_BUL_BASE  = $E052            ; BULLET_N * 8 bytes per-bullet mirror:
                                 ;   +0 world_x  +2 world_y  +4 screen_x  +6 screen_y
                                 ;   (screen_x/y written by draw_bullets in S3)
DBG_BUL_STRIDE = 8
DBG_KILLS     = $E092            ; 2B bullet<->enemy kill counter (S5)

; --- S4 PERSISTENT wave-spawn state (WRAM, like the mirrors; clear of the DP
;     contract). DBG_ENE_BASE spans $E020..$E04F (6 enemies * 8B); DBG_BUL_BASE
;     spans $E052..$E091 (8 bullets * 8B); DBG_KILLS = $E092. The wave state sits
;     just past it. ---
WAVE_SPAWN_T  = $E094            ; 2B frames-until-next-spawn countdown
WAVE_SPAWN_IX = $E096            ; 2B ring-offset cursor (0..RING_N-1)

; --- S2/S3 BULLET one-frame DP scratch. The bullet update + projection run in
;     the SAME frame window as the enemy patrol/projection, so they must use DP
;     that is dead at that point. The enemy projection owns $3E-$4F ($3E-$44 is
;     the live matrix snapshot M7A_SAV..D; $46-$4F is per-actor projection
;     scratch). draw_bullets runs AFTER draw_enemies, so it may reuse $46-$4F for
;     its own ENE_IDX/PRJ_* equivalents — but the bullet UPDATE (update_bullets)
;     runs BEFORE the matrix snapshot is even needed and only touches its own
;     loop offset, which we keep in a dedicated 1-frame byte at $3D (DIR_BITS is
;     dead by then — it is consumed at the top of the frame). ---
BUL_OFF   = $3D                  ; bullet loop byte offset (reuses dead DIR_BITS)

.segment "CODE"

NMI:
.include "nmi_handler.asm"        ; stock engine NMI (commits M7SEL/M7X/M7Y + scroll)

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; stable OAM ordering: hero at slot 0 (so the test reads OAM slot 0)
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- upload the dungeon Mode 7 map (under forced blank) ---
    sf_mode7_load_map dungeon_map, #$8000

    ; --- dungeon palette -> CGRAM 0.. (idx 0 = floor backdrop) ---
    sep #$20
    .a8
    stz $2121                     ; CGADD = 0
    ldx #$0000
dpal_loop:
    .a8
    lda f:dungeon_pal, x
    sta $2122
    inx
    cpx #(DUNGEON_PAL_COUNT * 2)
    bne dpal_loop
    rep #$30
    .a16
    .i16

    ; --- hero OBJ CHR + palette (Mode 7 owns VRAM $0000-$3FFF; OBJ base word
    ;     $4000 = tile 1024 via OBSEL=$62) ---
    sf_load_obj_pal 0, hero_pal
    sf_load_obj_chr 1024, hero_chr, HERO_CHR_BYTES
    ; --- S4 enemy CHR (VRAM word $4200 = OBJ tile 32) + OBJ palette 1 ---
    sf_load_obj_pal 1, enemy_pal
    sf_load_obj_chr ENEMY_OBJ_VTILE, enemy_chr, ENEMY_CHR_BYTES
    ; --- S3 bullet OBJ palette 2 (reuses the enemy CHR shape, own bright palette
    ;     so a rendered bullet reads distinct from the red enemy + cyan hero) ---
    sf_load_obj_pal 2, bullet_pal
    sep #$20
    .a8
    lda #$62
    sta $2101                     ; OBSEL: name base word $4000, size pair 3:
                                  ;   bit7 CLEAR = 16x16 (small), SET = 32x32 (large)
    rep #$30
    .a16
    .i16

    ; --- Mode 7 ON (static affine, stock NMI commits matrix shadows) ---
    sf_boss_mode7_on

    ; --- spawn world position + heading ---
    lda #SPAWN_PX
    sta R_POSX + 2
    stz R_POSX + 0
    lda #SPAWN_PY
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_ANGLE                   ; facing up at spawn
    stz R_MOVING                  ; idle at spawn (no direction held)

    ; --- centre the floor on the spawn world pos + install the first matrix ---
    sf_boss_center R_POSX + 2, R_POSY + 2
    sf_boss_matrix #SCALE_VIEW, R_ANGLE

    ; --- S5: seed LIVE enemy world pos (DBG_ENE_BASE +0/+2) from the ROM table,
    ;     init each enemy's patrol direction to +PATROL_SPEED, and zero the HITS /
    ;     GRACE counters. The enemies pace from here; the ROM table is the spawn
    ;     seed only (enemies MOVE, so the live pos lives in WRAM). ---
    jsr enemy_init

    ; --- S2: bullet pool starts all-free (sf_coldstart zeroed WRAM, but init
    ;     explicitly on game start per the sf_pool contract) ---
    sf_pool_init BUL_ALIVE, BULLET_N
    rep #$30
    .a16
    .i16

    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                     ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin

    ; ---------------- 8-WAY aim/move (control model A) -----------------------
    ; Build a UDLR bitfield from the held D-pad, look up the heading, and if a
    ; valid direction is held: snap R_ANGLE to it (the floor rotates to read
    ; "up") and set R_MOVING=1 so the step below advances the world. No direction
    ; (or an opposite-pair cancel) -> keep the last facing, R_MOVING=0 (idle), so
    ; stand-and-shoot works (the floor holds its last orientation).
    stz R_MOVING
    stz DIR_BITS                  ; UDLR bitfield accumulator (game scratch)
    ; U=8
    lda JOY1_CURRENT
    bit #JOY_UP
    beq dir_no_up
    lda DIR_BITS
    ora #$0008
    sta DIR_BITS
dir_no_up:
    .a16
    ; D=4
    lda JOY1_CURRENT
    bit #JOY_DOWN
    beq dir_no_down
    lda DIR_BITS
    ora #$0004
    sta DIR_BITS
dir_no_down:
    .a16
    ; L=2
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq dir_no_left
    lda DIR_BITS
    ora #$0002
    sta DIR_BITS
dir_no_left:
    .a16
    ; R=1
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq dir_no_right
    lda DIR_BITS
    ora #$0001
    sta DIR_BITS
dir_no_right:
    .a16
    lda DIR_BITS                  ; A = UDLR bitfield (0..15)
    asl a                         ; *2 (word table index)
    tax
    lda dir8_angle, x             ; heading for this dir, or DIR_NONE
    cmp #DIR_NONE
    beq dir_idle                  ; no/invalid dir -> keep last facing, no move
    sta R_ANGLE                   ; snap facing to the held direction
    lda #$0001
    sta R_MOVING
dir_idle:
    .a16

    ; ---------------- integrate the forward STEP: (sina, cosa) x MOVE_SPEED ---
    ; Forward along the facing is pos -= step where step = (sina, cosa)*speed
    ; (the proven m7_dungeon sign convention: DX=-sina, DY=-cosa). We always
    ; compute the step from the CURRENT facing; move_x/move_y only commit it when
    ; R_MOVING is set (idle frames keep the world fixed but the facing persists).
    lda R_ANGLE
    and #$00FF
    jsr sincos                    ; -> cosa/sina (signed); A16/I16

    ; WIDTH-RISK: smul16 contract is .a16/.i8, DB=0. Toggle I8 for the two
    ; multiplies, restore I16 after. A stays 16-bit throughout.
    sep #$10
    .i8
    lda a:sina
    sta a:math_a
    lda #MOVE_SPEED
    sta a:math_b
    jsr smul16                    ; math_p = sina x speed (s32, 16.16)
    lda a:math_p + 0
    sta STEP_FX                   ; X step fraction
    lda a:math_p + 2
    sta STEP_PX                   ; X step integer (signed)

    lda a:cosa
    sta a:math_a
    lda #MOVE_SPEED
    sta a:math_b
    jsr smul16
    lda a:math_p + 0
    sta STEP_FY
    lda a:math_p + 2
    sta STEP_PY
    rep #$10
    .i16

    ; ---------------- move: per-axis candidate-test-commit (SLIDE), gated ------
    ; Only advance the world while a direction is held (R_MOVING). The world
    ; advances by pos -= step; each axis is tested SEPARATELY so a diagonal push
    ; into an axis-aligned wall still slides along the unblocked axis.
    lda R_MOVING
    beq move_skip
    jsr move_x                    ; commit X step iff its footprint is clear
    jsr move_y                    ; commit Y step iff its footprint is clear
move_skip:
    .a16

    ; ---------------- S2: fire (A rising edge) + advance bullets (world space) -
    ; Fire spawns a bullet at the hero WORLD pos with a velocity along the facing
    ; (forward = -(sincos)*BULLET_SPEED — the SAME sign convention as the hero
    ; step). update_bullets advances every live bullet in WORLD space and
    ; despawns it at max range (TTL). Both run BEFORE the matrix snapshot (they do
    ; not need the matrix — projection is S3); they only touch the bullet pool +
    ; BUL_OFF scratch.
    jsr fire_bullet
    jsr update_bullets

    ; ---------------- render: pin floor to world pos + rotate to heading ------
    sf_boss_center R_POSX + 2, R_POSY + 2
    sf_boss_matrix #SCALE_VIEW, R_ANGLE

    ; --- S4: snapshot the matrix THIS frame committed (API block $60-$66) into
    ;     scratch BEFORE any spr macro reuses that DP. M7A=$60 M7B=$62 M7C=$64
    ;     M7D=$66. The enemy projection reads these so it uses the EXACT matrix
    ;     the floor rendered with -> sprites stay glued (no swim). ---
    lda API_BLOCK_BASE + $00
    sta M7A_SAV
    lda API_BLOCK_BASE + $02
    sta M7B_SAV
    lda API_BLOCK_BASE + $04
    sta M7C_SAV
    lda API_BLOCK_BASE + $06
    sta M7D_SAV

    ; ---------------- S4: wave spawn + chase (world space) -------------------
    ; Spawn a wave enemy on the SPAWN_PERIOD cadence at a world ring (pop-in), then
    ; step every live chaser toward the player. The live world pos in DBG_ENE_BASE
    ; +0/+2 is updated in place. Runs AFTER the matrix snapshot (M7A_SAV..D safe at
    ; $3E-$44) and BEFORE draw_enemies. Scratch lives in the dead $46-$4F DP.
    jsr enemy_waves
    jsr chase_enemies

    ; ---------------- S5: bullet<->enemy WORLD-SPACE collision -----------------
    ; Nested AABB on world coords (never reads the matrix -> rotation-invariant).
    ; On overlap: kill both pool slots + tick KILLS. Gated out by
    ; -DNO_BULLET_COLLISION (the non-vacuity control: bullets pass through enemies).
.if NO_BULLET_COLLISION = 0
    jsr bullet_enemy_collide
.endif

    ; ---------------- S5: hero-enemy CONTACT (world-box) ----------------------
    ; Tick the grace countdown; if not graced, test the hero footprint vs each
    ; enemy in WORLD coords. On contact: knock the hero back to spawn, zero
    ; speed, tick HITS, and (re)arm the grace window so an enemy beat crossing
    ; the spawn cannot immediately re-hit. NOTE: col_box clobbers the API block
    ; ($60), but the matrix was already snapshotted to M7A_SAV..D ($3E-$44),
    ; which draw_enemies reads — so the post-contact projection stays correct.
    jsr contact_enemies

    ; ---------------- draw the hero (slot 0, 16x16, facing up) ----------------
    spr_clear
    ; flags=$0000: OBJ pal 0, size bit7 CLEAR => 16x16 (the SMALL size of OBSEL
    ; pair $62). bit7 SET would select the 32x32 LARGE size, which reads a 4x4
    ; tile block (tiles 0..3,16..19,32..35,48..51) — tile 32 is the enemy CHR,
    ; so a phantom enemy diamond would bleed into the hero's lower quadrant.
    spr #HERO_TILE, #HERO_X, #HERO_Y, #(HERO_SIZE_BIT), #2  ; OBJ pal 0, prio 2, 16x16

    ; ---------------- S4: project + draw the static enemies (slots 1+) --------
    jsr draw_enemies

    ; ---------------- S3: project + draw the bullets (slots BULLET_OAM0+) ------
    ; THE CRUX: project each live bullet onto the rotating floor via the SHARED
    ; M7A_SAV..D snapshot + the TRANSPOSE (same window/matrix as draw_enemies).
    jsr draw_bullets

    ; ---------------- debug mirrors -------------------------------------------
    lda FRAME_COUNTER
    sta f:$7E0000 + DBG_HEARTBEAT
    lda R_POSX + 2
    sta f:$7E0000 + DBG_POSX
    lda R_POSY + 2
    sta f:$7E0000 + DBG_POSY
    lda R_ANGLE
    sta f:$7E0000 + DBG_ANGLE
    ; DBG_BLOCK_CT / DBG_LASTTERR are written in-place by move_x/move_y/terr_at_world.

    sf_frame_end
    jmp game_loop

; =============================================================================
; move_x — try to advance world X by STEP_X (pos -= step), with per-axis collision.
; Computes the candidate X (16.16), clamps the integer to 0..WORLD_MAX, and tests
; the hero footprint at (candidate X, CURRENT Y). Commits the X step ONLY if the
; footprint is clear; otherwise bumps DBG_BLOCK_CT and leaves X unchanged so the
; hero slides (Y may still move in move_y).
; Entry/Exit: A16/I16, DB=0.  Clobbers A, X, Y, CAND_*, T_PTR, SCR_TX.
; =============================================================================
move_x:
    .a16
    .i16
    ; candidate = R_POSX - STEP_X (16.16)
    lda R_POSX + 0
    sec
    sbc STEP_FX
    sta CAND_FRAC
    lda R_POSX + 2
    sbc STEP_PX
    jsr clamp_world               ; A -> 0..WORLD_MAX (bounded clamp)
    sta CAND_PX
    lda R_POSY + 2                ; footprint Y = current (unchanged this axis)
    sta CAND_PY
.if NO_COLLISION = 0
    jsr footprint_solid          ; A != 0 if any corner is solid
    bne mx_blocked
.endif
    ; clear (or collision disabled): commit the X step
    lda CAND_FRAC
    sta R_POSX + 0
    lda CAND_PX
    sta R_POSX + 2
    rts
.if NO_COLLISION = 0
mx_blocked:
    .a16
    .i16
    lda f:$7E0000 + DBG_BLOCK_CT
    inc a
    sta f:$7E0000 + DBG_BLOCK_CT
    rts
.endif

; =============================================================================
; move_y — like move_x for the Y axis: candidate = R_POSY - STEP_Y, footprint at
; (CURRENT/just-committed X, candidate Y). Commits the Y step only if clear.
; Entry/Exit: A16/I16, DB=0.  Clobbers A, X, Y, CAND_*, T_PTR, SCR_TX.
; =============================================================================
move_y:
    .a16
    .i16
    lda R_POSY + 0
    sec
    sbc STEP_FY
    sta CAND_FRAC
    lda R_POSY + 2
    sbc STEP_PY
    jsr clamp_world
    sta CAND_PY
    lda R_POSX + 2                ; footprint X = current (X already resolved)
    sta CAND_PX
.if NO_COLLISION = 0
    jsr footprint_solid
    bne my_blocked
.endif
    lda CAND_FRAC
    sta R_POSY + 0
    lda CAND_PY
    sta R_POSY + 2
    rts
.if NO_COLLISION = 0
my_blocked:
    .a16
    .i16
    lda f:$7E0000 + DBG_BLOCK_CT
    inc a
    sta f:$7E0000 + DBG_BLOCK_CT
    rts
.endif

; =============================================================================
; clamp_world — clamp the 16-bit signed value in A to 0..WORLD_MAX (the walkable
; 0..1023 px plane). Keeps world pos from running negative / over-range when a
; candidate would overshoot the dungeon bounds (the outer ring is wall anyway).
; Entry/Exit: A16/I16.  No DP touched.
; =============================================================================
clamp_world:
    .a16
    .i16
    bpl cw_not_neg               ; A >= 0 (signed)
    lda #0                       ; underflowed below 0 -> clamp to 0
    rts
cw_not_neg:
    .a16
    cmp #(WORLD_MAX + 1)
    bcc cw_done                  ; A <= WORLD_MAX
    lda #WORLD_MAX               ; overshot -> clamp to max
cw_done:
    .a16
    rts

; =============================================================================
; footprint_solid — test the hero's 8px-box footprint (4 corners) against the
; terrain LUT at world centre (CAND_PX, CAND_PY). The body spans HERO_HALF px
; either side: near edge = centre-HERO_HALF, far edge = centre+HERO_HALF-1 (the
; sf_solid_box +7-corner idiom sized to the hero). Returns A=0 if ALL corners are
; floor (clear), A != 0 if ANY corner is solid (blocked) — so the body can't clip
; a wall corner or half-enter a cell.
; Entry/Exit: A16/I16, DB=0.  Clobbers A, X, Y, T_PTR, SCR_TX.
; =============================================================================
footprint_solid:
    .a16
    .i16
    ; --- corner (near X, near Y) ---
    lda CAND_PX
    sec
    sbc #HERO_HALF
    jsr px_to_tile               ; X = tile x
    txa
    sta SCR_TX
    lda CAND_PY
    sec
    sbc #HERO_HALF
    jsr px_to_tile               ; X = tile y
    txy                          ; Y = ty
    ldx SCR_TX
    jsr terr_at_world            ; A = class
    bne fp_solid
    ; --- corner (far X, near Y) ---
    lda CAND_PX
    clc
    adc #(HERO_HALF - 1)
    jsr px_to_tile
    txa
    sta SCR_TX
    lda CAND_PY
    sec
    sbc #HERO_HALF
    jsr px_to_tile
    txy
    ldx SCR_TX
    jsr terr_at_world
    bne fp_solid
    ; --- corner (near X, far Y) ---
    lda CAND_PX
    sec
    sbc #HERO_HALF
    jsr px_to_tile
    txa
    sta SCR_TX
    lda CAND_PY
    clc
    adc #(HERO_HALF - 1)
    jsr px_to_tile
    txy
    ldx SCR_TX
    jsr terr_at_world
    bne fp_solid
    ; --- corner (far X, far Y) ---
    lda CAND_PX
    clc
    adc #(HERO_HALF - 1)
    jsr px_to_tile
    txa
    sta SCR_TX
    lda CAND_PY
    clc
    adc #(HERO_HALF - 1)
    jsr px_to_tile
    txy
    ldx SCR_TX
    jsr terr_at_world
    bne fp_solid
    lda #0                       ; all four corners floor -> clear
    rts
fp_solid:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; px_to_tile — convert a world pixel X in A (0..1023, already clamped) to a tile
; index 0..127 in the X register. tile = (px & 1023) >> 3.
; Entry: A16/I16, A = world px.  Exit: A16/I16, X = tile (0..127). A clobbered.
; WIDTH-RISK: pure A16 math, then tax in A16/I16 (no width hazard). px is bounded
; 0..1023 by clamp_world so the &$03FF is a no-op guard, not a wrap.
; =============================================================================
px_to_tile:
    .a16
    .i16
    and #$03FF                   ; guard to 0..1023 (clamped already)
    lsr a
    lsr a
    lsr a                        ; -> tile 0..127
    tax
    rts

; =============================================================================
; terr_at_world — return terrain class of tile (X=tx, Y=ty) in A (A16, hi=0).
; Reads terrain[ty*128 + tx] from the 16384-byte dungeon_terrain ROM table.
; tx/ty are 0..127 (px_to_tile guarantees the range). 0 = floor, 1 = wall.
; Entry: A16/I16, X=tx, Y=ty. Exit: A16 with class in low 8 bits (hi=0), I16.
; Clobbers A, T_PTR. Mirrors the proven coldstart-probe lookup.
; WIDTH-RISK: builds a 24-bit pointer in A16, toggles A8 for the 1-byte read,
; RESTORES A16 before rts (an A8 exit would mis-size the caller's bne/cmp).
; =============================================================================
terr_at_world:
    .a16
    .i16
    ; offset = ty*128 + tx  (ty 0..127 -> *128 fits in 14 bits)
    tya
    and #$007F
    xba                          ; *256
    lsr a                        ; *128
    sta T_PTR                    ; ty*128 (lo16)
    txa
    and #$007F
    clc
    adc T_PTR                    ; + tx
    ; 24-bit pointer = dungeon_terrain (ROM label) + offset
    clc
    adc #.loword(dungeon_terrain)
    sta T_PTR
    lda #0
    adc #.hiword(dungeon_terrain)
    sep #$20
    .a8
    sta T_PTR + 2                 ; bank byte
    ldy #0
    lda [T_PTR], y               ; A8 terrain class
    sta f:$7E0000 + DBG_LASTTERR  ; mirror last class read (A8 low byte)
    rep #$20
    .a16
    and #$00FF
    rts

; =============================================================================
; fire_bullet — on a rising-edge A press, spawn one bullet at the hero WORLD pos
; with a per-frame velocity along the CURRENT facing. Forward = pos -= step where
; step = (sina, cosa)*speed (the m7_dungeon convention), so the bullet velocity
; (a delta ADDED to pos each frame) is the NEGATED product: VX = -(sina*speed),
; VY = -(cosa*speed). TRAP 1: getting this sign wrong fires bullets backward.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y + math scratch.
; WIDTH-RISK: smul16 contract is .a16/.i8; toggle I8 for the two multiplies and
; restore I16 before the pool stores / rts. A stays 16-bit.
; =============================================================================
fire_bullet:
    .a16
    .i16
    ldx #BTN_A
    ldy #$0000                    ; player 0
    jsr engine_btnp               ; A != 0 on the rising-edge frame
    cmp #$0000
    beq fb_done                   ; not a fresh press
    sf_pool_spawn BUL_ALIVE, BULLET_N
    bmi fb_done                   ; pool full -> swallow the press
    ; X = claimed slot byte offset. Stash it across the trig/multiply.
    stx BUL_OFF
    ; spawn at the hero WORLD integer px
    lda R_POSX + 2
    ldx BUL_OFF
    sta BUL_X, x
    lda R_POSY + 2
    sta BUL_Y, x
    lda #BULLET_TTL
    sta BUL_TTL, x
    ; --- velocity = -(sincos)*BULLET_SPEED (integer px/frame) ---
    lda R_ANGLE
    and #$00FF
    jsr sincos                    ; -> cosa/sina (signed 8.8); A16/I16
    ; WIDTH-RISK: smul16 contract .a16/.i8 — toggle I8 around both multiplies.
    sep #$10
    .i8
    lda a:sina
    sta a:math_a
    lda #BULLET_SPEED
    sta a:math_b
    jsr smul16                    ; math_p = sina*speed (s32 16.16)
    rep #$10
    .i16
    lda a:math_p + 2              ; integer px/frame of the X step
    eor #$FFFF
    inc a                         ; negate -> forward VX
    ldx BUL_OFF
    sta BUL_VX, x
    sep #$10
    .i8
    lda a:cosa
    sta a:math_a
    lda #BULLET_SPEED
    sta a:math_b
    jsr smul16
    rep #$10
    .i16
    lda a:math_p + 2
    eor #$FFFF
    inc a                         ; negate -> forward VY
    ldx BUL_OFF
    sta BUL_VY, x
fb_done:
    .a16
    .i16
    rts

; =============================================================================
; update_bullets — advance every LIVE bullet in WORLD space by its per-frame
; velocity and despawn it when its TTL hits 0 (max range). Mirrors the live
; bullet count + each bullet's world pos to the debug region (DBG_BUL_COUNT /
; DBG_BUL_BASE) so the S2 test can read motion without projection.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y. Uses BUL_OFF.
; =============================================================================
update_bullets:
    .a16
    .i16
.if DBG_FROZEN_BULLET
    ; TEST BUILD (-DDBG_FROZEN_BULLET): freeze bullets at their spawn world spot
    ; (velocity ignored, TTL not ticked) so the S3 rendered-floor sweep can prove
    ; a FIXED world point stays glued to the SAME floor spot as the plane rotates.
    ; Still mirror the count + per-bullet world pos so the test reads them.
    sf_pool_count BUL_ALIVE, BULLET_N
    sta f:$7E0000 + DBG_BUL_COUNT
    stz BUL_OFF
ubf_mirror:
    .a16
    .i16
    ldx BUL_OFF
    lda BUL_X, x
    pha
    lda BUL_Y, x
    pha
    lda BUL_OFF
    asl a
    asl a
    tax
    pla
    sta f:$7E0000 + DBG_BUL_BASE + 2, x
    pla
    sta f:$7E0000 + DBG_BUL_BASE + 0, x
    lda BUL_OFF
    inc a
    inc a
    sta BUL_OFF
    cmp #(2 * BULLET_N)
    bne ubf_mirror
    rts
.endif
    ldx #$0000
ub_loop:
    .a16
    .i16
    lda BUL_ALIVE, x
    bne ub_live
    jmp ub_next
ub_live:
    .a16
    .i16
    ; pos += velocity (world space)
    lda BUL_X, x
    clc
    adc BUL_VX, x
    sta BUL_X, x
    lda BUL_Y, x
    clc
    adc BUL_VY, x
    sta BUL_Y, x
    ; TTL-- ; at 0 -> free the slot (max range)
    lda BUL_TTL, x
    dec a
    sta BUL_TTL, x
    bne ub_next
    sf_pool_kill_x BUL_ALIVE      ; X preserved
ub_next:
    .a16
    .i16
    inx
    inx
    cpx #(2 * BULLET_N)
    bne ub_loop
    ; --- mirror live count + per-bullet world pos for the test ---
    ; Loop over slots 0..N-1; BUL_OFF holds the slot byte offset (idx*2) so it
    ; survives the long-indexed mirror stores (which need X = idx*8). World x/y
    ; come from the pool arrays; screen x/y (+4/+6) are written by draw_bullets.
    sf_pool_count BUL_ALIVE, BULLET_N
    sta f:$7E0000 + DBG_BUL_COUNT
    stz BUL_OFF
ub_mirror:
    .a16
    .i16
    ldx BUL_OFF                   ; X = slot byte offset (idx*2)
    lda BUL_X, x
    pha                           ; save world x
    lda BUL_Y, x
    pha                           ; save world y
    ; mirror index = idx*8 = (slot byte offset)*4
    lda BUL_OFF
    asl a
    asl a                         ; *4
    tax                           ; X = idx*8 (mirror byte offset)
    pla                           ; world y
    sta f:$7E0000 + DBG_BUL_BASE + 2, x
    pla                           ; world x
    sta f:$7E0000 + DBG_BUL_BASE + 0, x
    lda BUL_OFF
    inc a
    inc a
    sta BUL_OFF
    cmp #(2 * BULLET_N)
    bne ub_mirror
    rts

; =============================================================================
; draw_enemies — project each STATIC enemy world (x,y) through THIS frame's
; static-affine matrix to a screen (sx,sy), cull off-screen, and emit its OAM
; entry (slots 1+; the hero already took slot 0). The matrix coeffs are read
; from M7A_SAV..M7D_SAV (snapshotted right after sf_boss_matrix), the pivot is
; the player's world pos (R_POSX/R_POSY integer px) — exactly the texel the
; affine pins to screen centre. world->screen is the INVERSE of the forward
; (screen->texel) matrix; at scale 1.0 that inverse is the TRANSPOSE, so:
;   (sx,sy) = ( (dx*A+dy*C)>>8 , (dx*B+dy*D)>>8 ) + (128,112).
; Entry/Exit: A16/I16, DB=0. Clobbers A,X,Y + math scratch + PRJ_*/ENE_IDX.
; WIDTH-RISK: the smul16 projection runs .a16/.i8 (smul16 contract); proj_axis
; toggles I8 internally and restores I16 before returning. The per-enemy loop +
; the spr call stay A16/I16. Annotated at each toggle.
; =============================================================================
; -----------------------------------------------------------------------------
; proj_dot ca, cb — (PRJ_DX*ca + PRJ_DY*cb) >> 8 -> A (signed 16-bit). Two signed
; 16x16 multiplies (smul16) summed as s32, then arithmetic >>8. ca/cb are DP coeff
; addresses (M7A_SAV..M7D_SAV). Entry/exit A16/I16; toggles I8 for smul16.
; WIDTH-RISK: smul16 contract is .a16/.i8 — toggle I8 around BOTH multiplies,
; restore I16 before the result load (the caller's I16 loop/adc relies on it).
.macro proj_dot ca, cb
    .a16
    sep #$10
    .i8
    lda PRJ_DX
    sta z:math_a
    lda ca
    sta z:math_b
    jsr smul16                    ; math_p = dx*ca (s32)
    lda z:math_p + 0
    sta z:proj_sum + 0            ; stash product 1 (proj_sum reuses math_p hi 4B)
    lda z:math_p + 2
    sta z:proj_sum + 2
    lda PRJ_DY
    sta z:math_a
    lda cb
    sta z:math_b
    jsr smul16                    ; math_p = dy*cb (s32)
    rep #$10
    .i16
    clc                           ; proj_sum (s32) += math_p (s32)
    lda z:proj_sum + 0
    adc z:math_p + 0
    sta z:proj_sum + 0
    lda z:proj_sum + 2
    adc z:math_p + 2
    sta z:proj_sum + 2
    ; >>8 of the s32 sum = the word straddling bytes 1..2 (little-endian). Fits
    ; s16: |dx,dy|<=1023, |coeff|<=256 -> |sum>>8| < 2048.
    lda z:proj_sum + 1
.endmacro

draw_enemies:
    .a16
    .i16
    stz ENE_IDX
de_loop:
    .a16
    .i16
    ; --- S4: skip DEAD pool slots -> park their OAM (stable slots). The pool
    ;     ALIVE array is indexed by slot byte offset (idx*2). ---
    lda ENE_IDX
    asl a                         ; idx*2 (pool stride)
    tax
    lda ENE_ALIVE, x
    bne de_alive
    jmp de_park                   ; free slot -> park OAM off-screen
de_alive:
    .a16
    .i16
    ; --- fetch enemy LIVE world (x,y) from the DBG_ENE_BASE mirror (idx*8). The
    ;     chasers MOVE (enemy_waves spawns, chase_enemies steps toward the player),
    ;     so the world pos is the live WRAM mirror; projection + culling track it. ---
    lda ENE_IDX
    asl a
    asl a
    asl a                         ; *8 (DBG_ENE_STRIDE)
    tax
    lda f:$7E0000 + DBG_ENE_BASE + 0, x   ; live world x
    sec
    sbc R_POSX + 2                ; dx = world_x - pivot_x (signed)
    sta PRJ_DX
    lda f:$7E0000 + DBG_ENE_BASE + 2, x   ; live world y
    sec
    sbc R_POSY + 2                ; dy = world_y - pivot_y (signed)
    sta PRJ_DY
    ; (world (x,y) mirror is already live in DBG_ENE_BASE; no re-mirror needed)

.ifdef ENEMY_PROJ_FORWARD
    ; --- BUGGY (forward matrix) projection, retained ONLY behind this build flag
    ;     so the floor-regression test can PROVE non-vacuity (it must FAIL here).
    ;     Applies M=[[A,B],[C,D]] (screen->texel, rotation by -theta) world->screen,
    ;     so enemies rotate the WRONG way and drift onto the walls. DO NOT ship. ---
    proj_dot M7A_SAV, M7B_SAV     ; sx = (dx*A + dy*B) >> 8  (WRONG: forward matrix)
    ; WIDTH-LINT: ok — proj_dot exits A16/I16 (restored before this clc)
    clc
    adc #SCREEN_CX
    sta PRJ_SX
    proj_dot M7C_SAV, M7D_SAV     ; sy = (dx*C + dy*D) >> 8  (WRONG: forward matrix)
    clc
    adc #SCREEN_CY
    sta PRJ_SY
.else
    ; --- sx = ((dx*A + dy*C) >> 8) + SCREEN_CX  (INVERSE / transpose) ---
    ; world->screen needs the INVERSE of the forward (screen->texel) matrix. At the
    ; fixed scale 1.0 the forward M is a pure rotation [[A,B],[C,D]]=[[cos,sin],
    ; [-sin,cos]], so its inverse is the TRANSPOSE [[A,C],[B,D]]. We feed proj_dot
    ; the transposed coeffs (swap M7B<->M7C across the two dots) -> enemies stay
    ; glued to their world tile / floor under rotation.
    proj_dot M7A_SAV, M7C_SAV     ; sx = (dx*A + dy*C) >> 8  (inverse/transpose)
    ; WIDTH-LINT: ok — proj_dot exits A16/I16 (restored before this clc)
    clc
    adc #SCREEN_CX
    sta PRJ_SX
    ; --- sy = ((dx*B + dy*D) >> 8) + SCREEN_CY  (INVERSE / transpose) ---
    proj_dot M7B_SAV, M7D_SAV     ; sy = (dx*B + dy*D) >> 8  (inverse/transpose)
    clc
    adc #SCREEN_CY
    sta PRJ_SY
.endif

    ; --- mirror projected screen (sx,sy) for the test oracle ---
    jsr ene_mirror_screen

    ; --- cull: off-screen -> park at CULL_Y; else OAM = (sx-8, sy-8) ---
    jsr enemy_culled              ; A != 0 if off-screen
    bne de_park

    ; on-screen: OAM (sx-8, sy-8). sx-8 may be negative for a sprite straddling
    ; the left edge -> mask to 9 bits (engine routes bit8 to the OAM hi table).
    lda PRJ_SX
    sec
    sbc #OBJ_HALF
    and #$01FF
    sta PRJ_SX                    ; PRJ_SX now holds OAM x (9-bit)
    lda PRJ_SY
    sec
    sbc #OBJ_HALF
    and #$00FF
    sta PRJ_SY                    ; PRJ_SY now holds OAM y
    spr #ENEMY_TILE_OBJ, PRJ_SX, PRJ_SY, #ENEMY_ATTR, #ENEMY_PRI
    bra de_next
de_park:
    .a16
    .i16
    ; off-screen: emit the slot but parked at CULL_Y (kit convention) so it does
    ; not wrap/garble on-screen. Keeps slot identity stable for the test.
    spr #ENEMY_TILE_OBJ, #$0000, #CULL_Y, #ENEMY_ATTR, #ENEMY_PRI
de_next:
    .a16
    .i16
    lda ENE_IDX
    inc a
    sta ENE_IDX
    cmp #ENEMY_COUNT
    bcs de_done                   ; idx >= count -> finished
    jmp de_loop                   ; long jump: loop body > 127 bytes (branch range)
de_done:
    .a16
    .i16
    rts

; =============================================================================
; draw_bullets — THE CRUX. Project each LIVE bullet's world (x,y) through THIS
; frame's static-affine matrix onto the rotating floor, cull off-screen, and emit
; its OAM entry (bullet slots BULLET_OAM0..; the hero + enemies already took
; slots 0..ENEMY_COUNT). 95% a copy of draw_enemies — the ONLY differences are
; the pool source (the bullet pool, skip free slots) and the OAM palette/tile.
;
; TRAP 2: it reads the SHARED M7A_SAV..M7D_SAV snapshot taken once this frame
; right after sf_boss_matrix — NOT a per-actor re-snapshot (that reintroduces the
; swim). It MUST run inside that live window (draw_bullets is called right after
; draw_enemies, before sf_frame_end). TRAP 3: it uses the TRANSPOSE (A,C)/(B,D),
; not the forward (A,B)/(C,D). TRAP 4: bullets stay 16x16 (no OBSEL size bit).
; TRAP 5: off-screen bullets are culled (parked at CULL_Y) + the 9-bit OAM X is
; masked (and #$01FF) so a left-edge bullet routes bit8 to the OAM hi-table.
; Entry/Exit: A16/I16, DB=0. Clobbers A,X,Y + math scratch + PRJ_*. Loop offset
; in BUL_OFF (survives the spr clobber of X).
; WIDTH-RISK: proj_dot toggles I8 internally and restores I16; the loop + spr
; stay A16/I16 (annotated at each branch target).
; =============================================================================
draw_bullets:
    .a16
    .i16
    stz BUL_OFF
db_loop:
    .a16
    .i16
    ldx BUL_OFF
    lda BUL_ALIVE, x
    bne db_live
    jmp db_park                   ; free slot -> park its OAM (stable slots)
db_live:
    .a16
    .i16
    ; (dx,dy) = bullet_world - pivot (the player's world pos = screen centre)
    lda BUL_X, x
    sec
    sbc R_POSX + 2
    sta PRJ_DX
    lda BUL_Y, x
    sec
    sbc R_POSY + 2
    sta PRJ_DY
.if BULLET_PROJ_FORWARD
    ; --- BUGGY forward-matrix projection (non-vacuity control): applies
    ;     M=[[A,B],[C,D]] world->screen, so bullets swim onto the WALLS under
    ;     rotation. -DBULLET_PROJ_FORWARD only; DO NOT ship. ---
    proj_dot M7A_SAV, M7B_SAV     ; sx = (dx*A + dy*B) >> 8  (WRONG: forward)
    ; WIDTH-LINT: ok — proj_dot exits A16/I16 (restored before this clc)
    clc
    adc #SCREEN_CX
    sta PRJ_SX
    proj_dot M7C_SAV, M7D_SAV     ; sy = (dx*C + dy*D) >> 8  (WRONG: forward)
    clc
    adc #SCREEN_CY
    sta PRJ_SY
.else
    ; --- sx = ((dx*A + dy*C) >> 8) + SCREEN_CX  (INVERSE / transpose) ---
    proj_dot M7A_SAV, M7C_SAV     ; sx = (dx*A + dy*C) >> 8  (inverse/transpose)
    ; WIDTH-LINT: ok — proj_dot exits A16/I16 (restored before this clc)
    clc
    adc #SCREEN_CX
    sta PRJ_SX
    ; --- sy = ((dx*B + dy*D) >> 8) + SCREEN_CY  (INVERSE / transpose) ---
    proj_dot M7B_SAV, M7D_SAV     ; sy = (dx*B + dy*D) >> 8  (inverse/transpose)
    clc
    adc #SCREEN_CY
    sta PRJ_SY
.endif

    ; --- mirror the projected screen (sx,sy) into the per-bullet mirror (+4/+6) ---
    jsr bul_mirror_screen

    ; --- cull off-screen -> park; else OAM = (sx-8, sy-8) ---
    jsr enemy_culled              ; reuses the shared cull (reads PRJ_SX/PRJ_SY)
    bne db_park
    lda PRJ_SX
    sec
    sbc #OBJ_HALF
    and #$01FF                    ; 9-bit OAM X (engine routes bit8 to hi-table)
    sta PRJ_SX
    lda PRJ_SY
    sec
    sbc #OBJ_HALF
    and #$00FF
    sta PRJ_SY
    spr #BULLET_TILE_OBJ, PRJ_SX, PRJ_SY, #BULLET_ATTR, #BULLET_PRI
    bra db_next
db_park:
    .a16
    .i16
    ; free or off-screen: emit the slot parked at CULL_Y (stable slot identity)
    spr #BULLET_TILE_OBJ, #$0000, #CULL_Y, #BULLET_ATTR, #BULLET_PRI
db_next:
    .a16
    .i16
    lda BUL_OFF
    inc a
    inc a
    sta BUL_OFF
    cmp #(2 * BULLET_N)
    bcs db_done
    jmp db_loop                   ; long jump: loop body > branch range
db_done:
    .a16
    .i16
    rts

; =============================================================================
; bul_mirror_screen — write the projected screen (PRJ_SX,PRJ_SY) into the bullet
; mirror at DBG_BUL_BASE + (slot idx)*8 + 4/+6. The slot idx = BUL_OFF/2, so the
; mirror byte offset = BUL_OFF*4. Entry/Exit A16/I16. Clobbers A, X.
; =============================================================================
bul_mirror_screen:
    .a16
    .i16
    lda BUL_OFF
    asl a
    asl a                         ; *4  (= idx*8 mirror stride)
    tax
    lda PRJ_SX
    sta f:$7E0000 + DBG_BUL_BASE + 4, x
    lda PRJ_SY
    sta f:$7E0000 + DBG_BUL_BASE + 6, x
    rts

; =============================================================================
; enemy_culled — A != 0 if the projected (PRJ_SX,PRJ_SY) is outside the visible
; 256x224 window by more than CULL_MARGIN (the 16px sprite's slack), so the
; caller parks it off-screen. Signed compares (sx/sy may be negative).
; Entry/Exit: A16/I16. Clobbers A. Returns A=0 visible, A=1 culled.
; =============================================================================
enemy_culled:
    .a16
    .i16
    ; sx < -CULL_MARGIN ?  (signed)
    lda PRJ_SX
    clc
    adc #CULL_MARGIN              ; shift so the low bound is 0
    bmi ec_cull                   ; sx + margin < 0 -> off left
    cmp #(256 + 2 * CULL_MARGIN)
    bcs ec_cull                   ; sx + margin >= 256+2*margin -> off right
    lda PRJ_SY
    clc
    adc #CULL_MARGIN
    bmi ec_cull
    cmp #(224 + 2 * CULL_MARGIN)
    bcs ec_cull
    lda #0
    rts
ec_cull:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; enemy_init — initialise the enemy pool (all slots free) + zero the HITS/GRACE/
; KILLS counters + arm the first wave-spawn timer. Called once at boot.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X.
; =============================================================================
enemy_init:
    .a16
    .i16
    sf_pool_init ENE_ALIVE, ENEMY_COUNT
    rep #$30
    .a16
    .i16
    lda #0
    ldx #$0000
    sta f:$7E0000 + DBG_HITS, x
    sta f:$7E0000 + DBG_GRACE, x
    sta f:$7E0000 + DBG_KILLS, x
    sta f:$7E0000 + WAVE_SPAWN_IX, x
    lda #SPAWN_PERIOD
    sta f:$7E0000 + WAVE_SPAWN_T, x
    rts

; =============================================================================
; enemy_waves — one frame of the timed wave spawner (shmup SPAWN_T cadence).
; Decrement WAVE_SPAWN_T; when it hits 0, re-arm it and spawn ONE enemy (if the
; pool has a free slot) at a world-RING offset around the player (cursor cycles
; the ring-offset table). The enemy POPS IN from off-screen and then chases.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y.
; =============================================================================
enemy_waves:
    .a16
    .i16
.if DBG_FROZEN_BULLET
    rts                           ; TEST BUILD: no enemy waves, so the frozen-
                                  ; bullet glue sweep has a clean arena (no chaser
                                  ; contact knocking the player off its position).
.endif
    ldx #$0000
    lda f:$7E0000 + WAVE_SPAWN_T, x
    dec a
    sta f:$7E0000 + WAVE_SPAWN_T, x
    bne ew_done                   ; not time yet
    lda #SPAWN_PERIOD
    sta f:$7E0000 + WAVE_SPAWN_T, x
    ; claim a pool slot (X = byte offset). Full -> skip this beat.
    sf_pool_spawn ENE_ALIVE, ENEMY_COUNT
    bmi ew_done
    stx PAT_IDX                   ; save the slot byte offset (idx*2)
    ; ring offset for this spawn = ring_off[cursor] (cursor*4 -> 2 words: dx, dy)
    ldx #$0000
    lda f:$7E0000 + WAVE_SPAWN_IX, x
    asl a
    asl a                         ; cursor*4 (2 words/entry)
    tax
    lda f:ring_off, x             ; dx
    clc
    adc R_POSX + 2                ; world x = player + ring dx
    pha
    lda f:ring_off + 2, x         ; dy
    clc
    adc R_POSY + 2                ; world y = player + ring dy
    pha
    ; mirror byte offset = (slot byte offset)*4 = idx*8
    lda PAT_IDX
    asl a
    asl a
    tax
    pla                           ; world y
    sta f:$7E0000 + DBG_ENE_BASE + 2, x
    pla                           ; world x
    sta f:$7E0000 + DBG_ENE_BASE + 0, x
    ; advance the ring cursor (mod RING_N)
    ldx #$0000
    lda f:$7E0000 + WAVE_SPAWN_IX, x
    inc a
    cmp #RING_N
    bcc ew_store_ix
    lda #0
ew_store_ix:
    .a16
    .i16
    sta f:$7E0000 + WAVE_SPAWN_IX, x
ew_done:
    .a16
    .i16
    rts

; =============================================================================
; chase_enemies — one frame of CHASE: every LIVE enemy steps ENEMY_SPEED px
; toward the player's world pos on each axis (sign-of-delta). The chasers are
; FLOATING enemies (a common overhead-shooter convention) — they pass OVER the
; interior arena pillars, so a pillar can never box a chaser in (only the player +
; bullets collide with pillars). They spawn + chase inside the arena, so they stay
; in bounds without a wall check. The live world pos is the DBG_ENE_BASE mirror;
; draw_enemies projects it onto the rotating floor.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X. Uses PAT_IDX + CAND_PX/CAND_PY.
; =============================================================================
chase_enemies:
    .a16
    .i16
    stz PAT_IDX
ch_loop:
    .a16
    .i16
    ; skip free slots (X = slot byte offset = idx*2)
    ldx PAT_IDX
    lda ENE_ALIVE, x
    beq ch_next
    ; load live world (x,y)
    lda PAT_IDX
    asl a
    asl a                         ; *4 -> idx*8 mirror offset
    tax
    lda f:$7E0000 + DBG_ENE_BASE + 0, x
    sta CAND_PX
    lda f:$7E0000 + DBG_ENE_BASE + 2, x
    sta CAND_PY
    ; --- X step toward the player: enemy_x += sign(player_x - enemy_x) ---
    lda R_POSX + 2
    sec
    sbc CAND_PX                   ; dx
    beq ch_x_done                 ; aligned
    bpl ch_x_pos
    lda CAND_PX
    sec
    sbc #ENEMY_SPEED
    bra ch_x_store
ch_x_pos:
    .a16
    .i16
    lda CAND_PX
    clc
    adc #ENEMY_SPEED
ch_x_store:
    .a16
    .i16
    sta CAND_PX
ch_x_done:
    .a16
    .i16
    ; --- Y step toward the player: enemy_y += sign(player_y - enemy_y) ---
    lda R_POSY + 2
    sec
    sbc CAND_PY                   ; dy
    beq ch_y_done
    bpl ch_y_pos
    lda CAND_PY
    sec
    sbc #ENEMY_SPEED
    bra ch_y_store
ch_y_pos:
    .a16
    .i16
    lda CAND_PY
    clc
    adc #ENEMY_SPEED
ch_y_store:
    .a16
    .i16
    sta CAND_PY
ch_y_done:
    .a16
    .i16
    ; commit the new world (x,y) to the mirror (X = idx*8)
    lda PAT_IDX
    asl a
    asl a
    tax
    lda CAND_PX
    sta f:$7E0000 + DBG_ENE_BASE + 0, x
    lda CAND_PY
    sta f:$7E0000 + DBG_ENE_BASE + 2, x
ch_next:
    .a16
    .i16
    lda PAT_IDX
    inc a
    inc a                         ; +2 (slot byte offset stride)
    sta PAT_IDX
    cmp #(2 * ENEMY_COUNT)
    bcs ch_done                   ; idx >= count -> finished
    jmp ch_loop                   ; long jump: loop body > 127 bytes (branch range)
ch_done:
    .a16
    .i16
    rts

; =============================================================================
; contact_enemies — hero-enemy CONTACT in WORLD space. Decrement the grace
; countdown; while grace is active, skip contact (no immediate re-hit after a
; respawn whose spawn tile an enemy beat may cross). Otherwise test the hero
; world centre vs each enemy's live world centre as an AABB overlap of two
; (2*CONTACT_HALF)-wide boxes: overlap iff |hx-ex| < 2*CONTACT_HALF AND
; |hy-ey| < 2*CONTACT_HALF (same half-open-box overlap col_box gives, done
; inline so no new engine link). On the first contact: knock the hero back to
; SPAWN (R_POSX/Y = SPAWN_PX/PY, speed 0), tick HITS, and re-arm GRACE — then
; stop (one hit/frame).
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y + $48-$4F scratch (NOT $3E-$44).
; =============================================================================
CONTACT_W = 2 * CONTACT_HALF     ; full box width: overlap threshold per axis
contact_enemies:
    .a16
    .i16
    ; --- grace countdown: if active, decrement and SKIP all contact ---
    ldx #$0000
    lda f:$7E0000 + DBG_GRACE, x
    beq ce_scan                   ; grace == 0 -> contact live
    dec a
    sta f:$7E0000 + DBG_GRACE, x
    rts                           ; graced this frame -> no contact
ce_scan:
    .a16
    .i16
    stz PAT_IDX
ce_loop:
    .a16
    .i16
    ; --- skip DEAD pool slots (no contact from a free slot) ---
    lda PAT_IDX
    asl a                         ; idx*2 (pool stride)
    tax
    lda ENE_ALIVE, x
    beq ce_no                     ; free slot -> no contact
    lda PAT_IDX
    asl a
    asl a
    asl a                         ; *8 (mirror stride)
    tax
    ; --- |hx - ex| < CONTACT_W ?  (abs delta on X) ---
    lda R_POSX + 2
    sec
    sbc f:$7E0000 + DBG_ENE_BASE + 0, x   ; hx - ex (signed)
    jsr abs16                     ; A = |hx - ex|
    cmp #CONTACT_W
    bcs ce_no                     ; >= threshold -> no overlap this enemy
    ; --- |hy - ey| < CONTACT_W ? ---
    lda R_POSY + 2
    sec
    sbc f:$7E0000 + DBG_ENE_BASE + 2, x   ; hy - ey
    jsr abs16
    cmp #CONTACT_W
    bcc ce_hit                    ; both axes overlap -> CONTACT
ce_no:
    .a16
    .i16
    ; next enemy
    lda PAT_IDX
    inc a
    sta PAT_IDX
    cmp #ENEMY_COUNT
    bcc ce_loop
    rts
ce_hit:
    .a16
    .i16
    ; knockback: hero -> spawn, speed 0
    lda #SPAWN_PX
    sta R_POSX + 2
    stz R_POSX + 0
    lda #SPAWN_PY
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_MOVING                  ; knockback halts motion (facing preserved)
    ; HITS += 1
    ldx #$0000
    lda f:$7E0000 + DBG_HITS, x
    inc a
    sta f:$7E0000 + DBG_HITS, x
    ; re-arm GRACE so an enemy beat over the spawn cannot immediately re-hit
    lda #GRACE_FRAMES
    sta f:$7E0000 + DBG_GRACE, x
    rts

; =============================================================================
; bullet_enemy_collide — S5: each LIVE bullet vs each LIVE enemy in WORLD space
; (the shmup nested col_box idiom, done as an inline AABB on world coords — it
; NEVER reads the Mode 7 matrix, so the hit is ROTATION-INVARIANT). On overlap:
; kill BOTH pool slots (bullet + enemy) and tick the KILLS counter. One enemy per
; bullet (the bullet is spent on the first hit). The bullet world pos is the
; BUL_X/BUL_Y pool arrays; the enemy world pos is the DBG_ENE_BASE mirror.
; Outer loop offset (bullet slot byte offset) = BUL_OFF; inner (enemy) = PAT_IDX.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y + $46-$4F scratch (NOT $3E-$44).
; =============================================================================
.if NO_BULLET_COLLISION = 0
bullet_enemy_collide:
    .a16
    .i16
    stz BUL_OFF
bec_b_loop:
    .a16
    .i16
    ldx BUL_OFF
    lda BUL_ALIVE, x
    bne bec_b_live
    jmp bec_b_next
bec_b_live:
    .a16
    .i16
    ; cache the bullet world (x,y) into CAND_PX/CAND_PY (survive the inner loop)
    ldx BUL_OFF
    lda BUL_X, x
    sta CAND_PX
    lda BUL_Y, x
    sta CAND_PY
    stz PAT_IDX
bec_e_loop:
    .a16
    .i16
    lda PAT_IDX
    asl a                         ; idx*2 (pool stride)
    tax
    lda ENE_ALIVE, x
    bne bec_e_live
    jmp bec_e_next
bec_e_live:
    .a16
    .i16
    ; |bx - ex| < 2*BULHIT_HALF ?
    lda PAT_IDX
    asl a
    asl a
    asl a                         ; idx*8 (mirror stride)
    tax
    lda CAND_PX
    sec
    sbc f:$7E0000 + DBG_ENE_BASE + 0, x   ; bx - ex
    jsr abs16
    cmp #(2 * BULHIT_HALF)
    bcs bec_e_next                ; X miss
    ; |by - ey| < 2*BULHIT_HALF ?
    lda PAT_IDX
    asl a
    asl a
    asl a
    tax
    lda CAND_PY
    sec
    sbc f:$7E0000 + DBG_ENE_BASE + 2, x   ; by - ey
    jsr abs16
    cmp #(2 * BULHIT_HALF)
    bcs bec_e_next                ; Y miss -> no overlap
    ; --- HIT: kill the enemy slot, kill the bullet slot, tick KILLS ---
    lda PAT_IDX
    asl a
    tax                           ; X = enemy slot byte offset
    sf_pool_kill_x ENE_ALIVE
    ldx BUL_OFF
    sf_pool_kill_x BUL_ALIVE
    ldx #$0000
    lda f:$7E0000 + DBG_KILLS, x
    inc a
    sta f:$7E0000 + DBG_KILLS, x
    jmp bec_b_next                ; bullet spent -> next bullet
bec_e_next:
    .a16
    .i16
    lda PAT_IDX
    inc a
    sta PAT_IDX
    cmp #ENEMY_COUNT
    bcs bec_b_next
    jmp bec_e_loop
bec_b_next:
    .a16
    .i16
    lda BUL_OFF
    inc a
    inc a                         ; +2 (bullet slot byte stride)
    sta BUL_OFF
    cmp #(2 * BULLET_N)
    bcs bec_done
    jmp bec_b_loop
bec_done:
    .a16
    .i16
    rts
.endif

; =============================================================================
; abs16 — A = |A| for a signed 16-bit accumulator. Entry/Exit A16/I16; no DP.
; =============================================================================
abs16:
    .a16
    .i16
    bpl abs16_done                ; A >= 0 -> already absolute
    eor #$FFFF
    inc a                         ; two's-complement negate
abs16_done:
    .a16
    rts

; =============================================================================
; ene_mirror_base / ene_mirror_screen — write the projected-screen mirror the
; test reads as the projection oracle. Layout per enemy (8 bytes at
; $7E0000+DBG_ENE_BASE + ENE_IDX*8): +0 world_x +2 world_y +4 sx +6 sy. The
; world (x,y) at +0/+2 is now the LIVE patrol position (seeded by enemy_init,
; paced by patrol_enemies) — draw_enemies reads it and only re-mirrors sx/sy.
; Entry/Exit: A16/I16. ene_mirror_base leaves the per-enemy WRAM offset in X.
; Clobbers A, X.
; =============================================================================
; ene_mirror_base — X = idx*8 (long-indexed stores require X, not Y, on 65816).
ene_mirror_base:
    .a16
    .i16
    lda ENE_IDX
    asl a
    asl a
    asl a                         ; *8
    tax                           ; X = idx*8
    rts

ene_mirror_screen:
    .a16
    .i16
    jsr ene_mirror_base           ; X = idx*8
    lda PRJ_SX
    sta f:$7E0000 + DBG_ENE_BASE + 4, x
    lda PRJ_SY
    sta f:$7E0000 + DBG_ENE_BASE + 6, x
    rts

; =============================================================================
; Engine link partners (sf_mode7_affine.inc documented order) + sprite/DMA.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "input_handler.asm"       ; engine_btn/engine_btnp (sf_input.inc partner)

mode7_sin_lut:
    .include "mode7_sin_lut.inc"   ; defines sin_lut: (used by sincos)
.include "hdma_alloc.asm"          ; allocator symbols mode7_engine references
.include "mode7_math.asm"          ; sincos + smul16 (matrix trig + multiply)

.segment "RODATA"
.include "mode7_pv_ztable.inc"     ; pulled by mode7_hdma.asm's data refs

.segment "CODE"
.include "mode7_hdma.asm"          ; pv_* (referenced by mode7_engine paths)
.include "mode7_engine.asm"        ; mode7_set_static

; --- assets ---
.include "assets/dungeon_palette.inc"
.include "assets/hero.inc"
.include "assets/enemy.inc"

; --- 8-way heading table (RODATA, NOT the constants block — see DIR_NONE note).
;     idx = UDLR bitfield (U=8 D=4 L=2 R=1); maps each valid single/diagonal dir
;     to the compass heading whose FORWARD world motion points that way; $FFFF =
;     no/invalid dir (opposite pair) -> keep last facing (stand-and-shoot). ---
.segment "RODATA"
dir8_angle:
    .word DIR_NONE          ; 0  ----  none
    .word 192              ; 1  ---R  right  (forward +X)
    .word 64               ; 2  --L-  left   (forward -X)
    .word DIR_NONE          ; 3  --LR  L+R cancel
    .word 128              ; 4  -D--  down   (forward +Y)
    .word 160              ; 5  -D-R  down-right
    .word 96               ; 6  -DL-  down-left
    .word DIR_NONE          ; 7  -DLR  cancel
    .word 0                ; 8  U---  up     (forward -Y)
    .word 224              ; 9  U--R  up-right
    .word 32               ; 10 U-L-  up-left
    .word DIR_NONE          ; 11 U-LR  cancel
    .word DIR_NONE          ; 12 UD--  U+D cancel
    .word DIR_NONE          ; 13 UD-R  cancel
    .word DIR_NONE          ; 14 UDL-  cancel
    .word DIR_NONE          ; 15 UDLR  cancel

; --- S3 bullet OBJ palette (16 colours, BGR555). The bullet reuses the enemy
;     CHR (indices 1 body / 2 outline / 3 highlight) but a BRIGHT-YELLOW bolt
;     palette so a rendered bullet is plainly distinct from the red enemy and the
;     cyan hero on the framebuffer (the S3 rendered-floor test reads bullet px).
;     idx0 transparent; 1 = bright yellow (255,230,40); 2 = orange (220,120,20);
;     3 = white hot (255,255,210). ---
bullet_pal:
    .word $0000              ; 0 transparent
    .word ((40>>3)<<10)|((230>>3)<<5)|(255>>3)   ; 1 bright yellow
    .word ((20>>3)<<10)|((120>>3)<<5)|(220>>3)   ; 2 orange
    .word ((210>>3)<<10)|((255>>3)<<5)|(255>>3)  ; 3 white hot
    .word $0000, $0000, $0000, $0000
    .word $0000, $0000, $0000, $0000
    .word $0000, $0000, $0000, $0000

; --- S4 wave-spawn ring offsets (RING_N entries, 2 words each: world dx, dy
;     relative to the player). ~120px out so a spawn POPS IN from off the visible
;     window (the player sees it appear and chase). Cycled by WAVE_SPAWN_IX so
;     successive waves come from the 8 compass directions. Signed (use .word with
;     two's-complement for negatives). ---
ring_off:
    .word    0, $FF88           ; N   ( 0,-120)
    .word   85, $FFAB           ; NE  (+85,-85)
    .word  120,    0            ; E   (+120, 0)
    .word   85,   85            ; SE  (+85,+85)
    .word    0,  120            ; S   ( 0,+120)
    .word $FFAB,  85            ; SW  (-85,+85)
    .word $FF88,    0           ; W   (-120, 0)
    .word $FFAB, $FFAB          ; NW  (-85,-85)
.segment "CODE"

; (S4: the old fixed enemy_world SPAWN-SEED ROM table is GONE — enemies are now a
;  sf_pool of wave chasers spawned at runtime at ring offsets, see enemy_waves.)

; --- world terrain LUT (128x128 = 16384 bytes, row-major [ty*128+tx], 1=solid /
;     0=floor). Lives in CODE bank (bank 0) RODATA so terr_at_world's 16-bit
;     pointer math + bank byte reach it. BANK1 is fully consumed by the 32KB map
;     blob, so the terrain table cannot share it. ---
.segment "RODATA"
dungeon_terrain:
    .incbin "assets/dungeon_terrain.bin"

; --- the 32KB interleaved Mode 7 map blob (fills BANK1) ---
.segment "BANK1"
dungeon_map:
    .incbin "assets/dungeon_map.bin"
