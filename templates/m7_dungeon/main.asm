; =============================================================================
; m7_dungeon — Mode 7 rotating-floor top-down dungeon (TANK CONTROLS)
; =============================================================================
; A top-down dungeon crawler with TANK CONTROLS: the player's FACING always reads
; "up", and the dungeon floor ROTATES + SCROLLS underneath a hero pinned at screen
; centre. The floor is the Mode 7 background — one rigid image under a single
; uniform affine matrix; the hero is an OBJ composited on top, so it stays upright
; while the world spins. Enemies patrol the corridors in world space, walls block
; you (collision is done in world space, not on the rotated picture), and touching
; an enemy knocks you back to the start.
;
; Controls:
;   LEFT / RIGHT   turn the heading (the whole floor rotates under you)
;   B or UP        throttle forward along the way you face
;   Y or DOWN      reverse   (release the throttle -> coast to a stop)
;
; File layout (major banners, top to bottom):
;   INIT         — upload the map / CHR / palettes, start Mode 7 + the music
;   MAIN LOOP    — game_loop: turn, throttle, integrate, collide, patrol, contact, draw
;   SUBROUTINES  — per-axis collision, world->screen projection, patrol, contact
;   DATA         — enemy spawn table, terrain LUT, the Mode 7 map blob
;
; game_loop is the once-per-frame heartbeat — start reading there.
;
; Build:  make m7_dungeon
; LDCFG: lorom_tad_m7.cfg
;   ^ Linker-config sentinel: a 96KB image. Bank 0 = code + the 16KB terrain LUT;
;     BANK1 = the 32KB Mode 7 map blob; bank 2 = the TAD audio song data. A
;     *_tad*.cfg name also links the TAD audio objects (so the music + hit sound
;     reach the SPC700; a no-audio-bank cfg would boot the game silent).
;
; HOW THE FLOOR MOVES (the static-affine trick — the whole rail rests on it):
;   The floor is drawn by ONE uniform affine matrix per frame, with NO per-scanline
;   HDMA. Three macro calls do it (installed in INIT, refreshed each frame):
;   - sf_boss_mode7_on   turns Mode 7 on so the stock engine's VBlank handler
;                        commits the matrix + scroll from shadow registers — no
;                        custom NMI, no perspective table. That per-scanline table
;                        is what the perspective path rebuilds every frame (the
;                        persp_cycles gate clocks a full solve at ~138% of one
;                        frame); keeping the plane flat is what buys the CPU budget.
;   - sf_boss_center wx, wy  pins the player's WORLD (x,y) to screen centre as the
;                        matrix PIVOT. The pivot is the centre of rotation, so
;                        moving it with the player keeps the player centred while
;                        the floor rotates + scrolls around them.
;   - sf_boss_matrix SCALE, angle  rotates the plane so the facing reads "up".
;                        SCALE = $0100 (1.0) is flat, no zoom.
;   The Mode 7 map fills VRAM words $0000-$3FFF, so OBJ CHR can't share low VRAM:
;   the OBJ name base moves to word $4000 (OBSEL = $62) and the hero's OAM tile
;   number stays 0 relative to that base. The affine matrix never touches OBJ, so
;   the hero (and the enemy sprites) composite on top, upright.
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SPIN DUNGEON"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; sf_mode7_load_map (the VRAM map DMA wrapper)
.include "sf_mode7_affine.inc"  ; sf_boss_mode7_on / sf_boss_center / sf_boss_matrix
.include "sf_fx.inc"            ; sf_bright_fade (+ _tick): the get-hit screen flash
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD ca65 audio-driver API imports
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids (the compiled song set)
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music / sf_sfx

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

; --- enemy-colour regression toggle (non-vacuity control for the enemy colour
;     band). Build with -DENEMY_MISCOLOR=1 to load a COOL (floor-blue) OBJ palette
;     for the enemy instead of the demon's warm enemy_pal, so the enemy renders
;     blue and the rendered enemy-warm band reads 0 pixels. Proves the enemy
;     colour-band tests are NOT vacuous (they CAN fail). Default = the real demon. ---
.ifndef ENEMY_MISCOLOR
ENEMY_MISCOLOR = 0
.endif
.if BUGGY_SPRITE_SIZE = 0
HERO_SIZE_BIT  = $0000          ; bit7 CLEAR -> 16x16 (small size of OBSEL $62)
ENEMY_SIZE_BIT = $0000
.else
HERO_SIZE_BIT  = $0080          ; bit7 SET -> 32x32 LARGE (the phantom-diamond bug)
ENEMY_SIZE_BIT = $0080
.endif

; --- world geometry ---
SCALE_VIEW = $0100              ; 1.0 screen->texel (FLAT, no zoom)
WORLD_MAX  = 1023               ; walkable plane is 0..1023 px (128 tiles * 8)
HERO_HALF  = 4                  ; footprint half-extent: 8px box (near pos-4 .. far pos+3)

; --- tank-control tuning (signed 8.8 speed) ----------------------------------
; Turn rate: 1 heading unit (1/256 turn) per held LEFT/RIGHT frame — slow enough
; to aim a tank cleanly.
TURN_STEP = 1
; Throttle is SIGNED 8.8 (256 = 1.0 px/frame). Capped SLOW so the per-step
; collision can't tunnel a 2-tile (16px) wall: top speed <= ~1.25 px/frame.
ACCEL     = $0010               ; +0.0625 px/f per held throttle frame (ramp up)
DECEL     = $0008               ; speed bled per coast frame (toward hover/0)
SPEED_CAP = $0140               ; +1.25 px/frame forward cap (320 = 1.25*256)
SPEED_REV = $FEC0               ; -1.25 px/frame reverse cap (signed: -$0140)

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_DOWN  = $0400
JOY_UP    = $0800
JOY_START = $1000                ; START toggles pause
JOY_Y     = $4000
JOY_B     = $8000

; --- spawn: the maze START cell centre (cell (1,1) -> world tile 14,14 -> px
;     116,116), an open floor tile at the mouth of the start corridor (the path
;     runs RIGHT from here). Overridable via -DSPAWN_TX / -DSPAWN_TY to spawn in a
;     FAR maze cell (collision-everywhere proof). See make_dungeon.py MAZE. ---
.ifndef SPAWN_TX
SPAWN_TX = 14
.endif
.ifndef SPAWN_TY
SPAWN_TY = 14
.endif
SPAWN_PX = SPAWN_TX * 8 + 4      ; 116 (default: tile 14 -> 14*8+4)
SPAWN_PY = SPAWN_TY * 8 + 4      ; 116 (default: tile 14 -> 14*8+4)

; --- hero screen placement (16x16 centred at screen 128,112) ---
HERO_X = 128 - 8
HERO_Y = 112 - 8

; --- title reveal: frames to fade the screen in from black at boot. Kept SHORT so
;     it settles inside the boot-init window (load_rom's wall-clock 0.3s spends most
;     of its budget on the 32KB map DMA, leaving ~6-7 game frames) — the rail boots
;     straight into gameplay and the colour-band tests read the render at boot, so a
;     longer fade would dim the demon below its bright-warm threshold. ---
TITLE_FADE_FRAMES = 4

; --- game DP state (kit template contract: game DP is $32-$5F) ---
R_POSX   = $32                   ; world x, 16.16 (frac word @ +0, integer px @ +2)
R_POSY   = $36                   ; world y, 16.16
R_ANGLE  = $3A                   ; heading (low byte 0..255), drives the matrix
R_SPEED  = $3C                   ; SIGNED 8.8 speed (B/UP fwd, Y/DOWN rev, release=hover)

; --- collision scratch (game DP $3E-$4F; ONE-FRAME scratch, not persistent.
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

; --- enemy sprite projection ----------------------------------------------
; Enemies live at WORLD positions and are PROJECTED onto the rotating Mode 7
; plane each frame, so they stay glued to their world tile as the floor rotates
; AND scrolls. world->screen needs the INVERSE of the Mode 7
; FORWARD (screen->texel, rotate by -theta) matrix M=[[A,B],[C,D]]. At the fixed
; scale 1.0 here M is a pure rotation, so its inverse is the TRANSPOSE [[A,C],
; [B,D]]; with ONE matrix per frame:
;   (sx,sy) = ( (dx*A + dy*C) >> 8 , (dx*B + dy*D) >> 8 ) + (128,112)
; where (dx,dy) = enemy_world - PIVOT (the player's world pos, = screen centre)
; and A,B,C,D are the SAME M7A-M7D sf_boss_matrix just committed this frame —
; we read them straight out of the API block ($60-$66) BEFORE any spr clobbers
; that DP, then save them in scratch for the per-enemy loop.
ENEMY_COUNT = 3
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

; --- goal win-card overlay ---------------------------------------------------
; Reaching the GOAL cell draws a 3-star banner (OAM slots 4-6, own OBJ palette 2)
; at screen top. This is an OVERLAY gated on goal-cell contact — NO state machine,
; no input freeze — so the route/collision/pause suites are undisturbed (they read
; WRAM + slots 0-3; the win sprites live in slots 4-6). The goal body is the 24px
; cell centred on GOAL_C* (== make_dungeon cell_world_center('G') px 356,356).
GOAL_CX    = 356                 ; goal cell centre world px (X)
GOAL_CY    = 356                 ;   ... (Y)
GOAL_HALF  = 12                  ; half the 24px goal-cell floor body
WIN_TILE_OBJ = 64                ; OAM tile # (rel OBJ base $4000): win CHR at word $4400
WIN_OBJ_VTILE = 1024 + 64        ; absolute VRAM tile for sf_load_obj_chr
WIN_ATTR   = $0004               ; size bit CLEAR (16x16) + OBJ palette 2 (PPP=%010)
WIN_PRI    = 3                   ; draw above the floor
WIN_Y      = 28                  ; banner row (screen top, clear of the centred hero)

; --- projection scratch (REUSES the collision DP $3E-$4F: that scratch is
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

; --- patrol/contact scratch (REUSES the same one-frame $46-$4F scratch).
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
; Per-enemy mirrors: world (x,y) then projected screen (sx,sy), 8 bytes each.
; The test reads these as the projection OUTPUT oracle (computed vs ROM).
DBG_ENE_BASE  = $E020            ; ENEMY_COUNT * 8 bytes:
                                 ;   +0 world_x  +2 world_y  +4 screen_x  +6 screen_y
DBG_ENE_STRIDE = 8

; --- PATROL + CONTACT tuning -----------------------------------------------
; The enemies PACE their corridor in WORLD space (wall-turn patrol) and a
; hero-enemy CONTACT knocks the hero back to spawn + ticks a HITS counter.
;
; The enemies MOVE, so their world (x,y) can't live in ROM: the LIVE world pos is
; the DBG_ENE_BASE +0/+2 mirror (seeded from the enemy_world ROM table at boot,
; updated in place each frame). draw_enemies already reads the per-enemy world
; pos from DBG_ENE_BASE, so projection + culling track the live position for free.
;
; PATROL: each enemy paces ONE axis at PATROL_SPEED px/frame; its next-step
; footprint is tested vs the SAME world-space terrain LUT the hero uses
; (footprint_solid) and the enemy REVERSES when the step would enter a wall — so
; enemies never walk through walls and pace their corridor naturally.
;
; CONTACT: each frame, WORLD-space box overlap between the hero footprint and
; each enemy (col_box in world coords). On contact the hero is knocked back to
; spawn (R_POSX/Y = spawn, speed 0) and a HITS counter ticks. A post-respawn
; GRACE window suppresses contact for a few frames so an enemy whose beat
; crosses the spawn tile cannot immediately re-hit.
PATROL_SPEED = 1                 ; world px/frame per enemy (slow pace, <=1px/f)
; per-enemy PATROL AXIS: 0 = X (east-west), 1 = Y (north-south). Baked per enemy
; in the patrol dispatch (E0 row-corridor X, E1 column Y, E2 row-corridor X).
CONTACT_HALF = 4                 ; world-box half-extent for hero-enemy overlap
                                 ; (8x8 box centred on each body: |dx|<8 AND
                                 ;  |dy|<8 = contact). Sized so a HEAD-ON drive
                                 ;  into a centreline enemy hits, yet a hero that
                                 ;  WALL-HUGS (the per-axis slide) to ~8px off-centre
                                 ;  in the 16px corridors clears it — the committed
                                 ;  maze_route uses that to dodge past the enemies.
GRACE_FRAMES = 40                ; post-respawn frames with contact suppressed
                                 ; (belt-and-suspenders on top of the spawn
                                 ;  sanctuary below: a brief no-contact window right
                                 ;  after a respawn)
; Spawn sanctuary: the hero cannot be hit while standing on the spawn tile. An
; enemy beat that crosses the spawn (E0 paces the start corridor) would otherwise
; grind down an idle / just-respawned hero — a respawn to spawn is invisible AND
; unfair if it drops you straight back into a patrol. A hero that has DRIVEN off
; the spawn takes contact normally. This suppresses the HIT only; it does NOT move
; any enemy, so what you see patrolling is unchanged. Radius = the contact width.
SPAWN_SANCTUARY = 2 * CONTACT_HALF   ; hero "on spawn" within this world X/Y (= CONTACT_W)

; --- contact debug mirrors (in the free gap $E01C-$E01F between DBG_LASTTERR and
;     DBG_ENE_BASE) ---
DBG_HITS      = $E01C            ; 2B hero-enemy contact (knockback) counter
DBG_GRACE     = $E01E            ; 2B post-respawn grace countdown (frames left)

; --- PERSISTENT enemy patrol state (WRAM $7E:E040.., clear of the 0..$31 engine
;     DP and the $32-$66 template/Mode7 DP — page-0 DP is fully spoken for, so
;     persistent cross-frame state lives in WRAM, like the mirrors). ---
ENE_DIR_BASE  = $E040            ; ENEMY_COUNT * 2 bytes: signed step direction
                                 ;   (+PATROL_SPEED or -PATROL_SPEED) per enemy

; --- PAUSE state (WRAM, persistent). START toggles it; while paused, the world +
;     enemies freeze but the frame still renders (and the music keeps playing). ---
DBG_PAUSED    = $E048            ; 2B: 0 = running, 1 = paused (test-readable)
PREV_START    = $E04A            ; 2B: last frame's START bit, for rising-edge detect

.segment "CODE"

NMI:
.include "nmi_handler.asm"        ; stock engine NMI (commits M7SEL/M7X/M7Y + scroll)

NMI_STUB:
    rti

; =============================================================================
; INIT — power-on setup: upload the map / CHR / palettes under forced blank,
; turn Mode 7 on, seed the world, start the music, then enable the screen + NMI.
; =============================================================================
RESET:
    sf_coldstart
    sf_engine_init
    sf_audio_init                 ; upload the SPC700 driver ONCE at boot, while
                                  ;   interrupts are still off (never on a respawn)

    ; stable OAM ordering: hero at slot 0 (so the test reads OAM slot 0).
    ; sep/rep set the CPU's register width: sep #$20 -> 8-bit accumulator (the
    ; PPU ports below take single bytes); rep #$30 -> 16-bit A + index again. The
    ; .a8/.a16/.i16 lines keep the ASSEMBLER's idea of the width in step with the
    ; CPU's (see the width-tracking gate) — mismatch them and the wrong-size
    ; opcode silently corrupts state far from here.
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- upload the dungeon Mode 7 map (under forced blank) ---
    sf_mode7_load_map dungeon_map, #$8000

    ; --- Load the dungeon palette into CGRAM, the PPU's colour memory: set the
    ;     start index once, then stream bytes (2 per colour). Safe now — the screen
    ;     is force-blanked, so the PPU isn't reading colours mid-frame. ---
    sep #$20
    .a8                           ; 8-bit accumulator: these ports take bytes
    stz $2121                     ; CGADD (CGRAM address): start at colour 0
    ldx #$0000
@pal_loop:
    .a8                           ; branch target: re-assert the CPU width
    lda f:dungeon_pal, x
    sta $2122                     ; CGDATA (CGRAM data): write; index auto-advances
    inx
    cpx #(DUNGEON_PAL_COUNT * 2)
    bne @pal_loop
    rep #$30
    .a16
    .i16

    ; --- hero OBJ CHR + palette (Mode 7 owns VRAM $0000-$3FFF; OBJ base word
    ;     $4000 = tile 1024 via OBSEL=$62) ---
    sf_load_obj_pal 0, hero_pal
    sf_load_obj_chr 1024, hero_chr, HERO_CHR_BYTES
    ; --- enemy CHR (VRAM word $4200 = OBJ tile 32) + OBJ palette 1 ---
.if ENEMY_MISCOLOR
    sf_load_obj_pal 1, miscolor_pal   ; non-vacuity control: render the enemy COOL
.else
    sf_load_obj_pal 1, enemy_pal
.endif
    sf_load_obj_chr ENEMY_OBJ_VTILE, enemy_chr, ENEMY_CHR_BYTES
    ; --- goal win-card CHR (VRAM word $4400 = OBJ tile 64) + OBJ palette 2. The
    ;     16x16 star ships as two tight 64-byte row blobs (bank 0 is nearly full):
    ;     DMA the top tile pair to tile 64 and the bottom pair to tile 64+16=80. ---
    sf_load_obj_pal 2, win_pal
    sf_load_obj_chr WIN_OBJ_VTILE, win_chr_top, WIN_CHR_ROW_BYTES
    sf_load_obj_chr WIN_OBJ_VTILE + 16, win_chr_bot, WIN_CHR_ROW_BYTES
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
    stz R_ANGLE
    stz R_SPEED                   ; hover at spawn (no throttle)

    ; --- centre the floor on the spawn world pos + install the first matrix ---
    sf_boss_center R_POSX + 2, R_POSY + 2
    sf_boss_matrix #SCALE_VIEW, R_ANGLE

    ; --- seed LIVE enemy world pos (DBG_ENE_BASE +0/+2) from the ROM table, init
    ;     each enemy's patrol direction to +PATROL_SPEED, and zero the HITS / GRACE
    ;     counters. The enemies pace from here; the ROM table is the spawn seed only
    ;     (enemies MOVE, so the live pos lives in WRAM). ---
    jsr enemy_init

    ; --- start unpaused (explicit init: RAM is random at power-on) ---
    lda #0
    sta f:$7E0000 + DBG_PAUSED
    sta f:$7E0000 + PREV_START

    ; --- start the dungeon theme. The song loads asynchronously, streaming to the
    ;     SPC over the first frames' sf_audio_ticks (the flagship platformer/rpg
    ;     pattern); the previous (silent) song stops at once. ---
    sf_music #Song::ode_to_joy

    sf_debug_magic

    ; --- screen on + NMI on, with a TITLE fade-IN reveal -----------------------
    ; The rail boots straight into gameplay (Mode 7 has no spare BG text layer, and
    ; the boot-flow tests read live state), so the "title" is a non-gating brightness
    ; fade: come up from black to full over TITLE_FADE_FRAMES so the dungeon reveals
    ; itself on boot. sf_bright_fade_tick (already in the loop) drives it. It settles
    ; in << the ~18-frame load window, so no rendered test ever samples a dim frame.
    sep #$20
    .a8
    stz $2100                     ; INIDISP: brightness 0 (blank off) — start BLACK
    stz SHADOW_INIDISP            ; shadow the NMI re-commits each frame stays in sync
    lda #$81
    sta $4200                     ; NMITIMEN: enable VBlank NMI + auto-joypad read
    rep #$30
    .a16
    .i16
    sf_bright_fade #$0F, #TITLE_FADE_FRAMES   ; arm the boot title reveal (0 -> 15)

; =============================================================================
; MAIN LOOP — game_loop runs once per frame: read input, integrate the tank step,
; collide it against the world, pace the enemies, test contact, then draw.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin
    sf_audio_tick                 ; pump the audio queue + song streaming, every frame
    sf_bright_fade_tick           ; advance the get-hit screen flash (cheap no-op when idle)

    ; ---------------- pause: START toggles it (rising edge) -------------------
    ; Read START; if it just changed to pressed (was released last frame), flip the
    ; pause flag. While paused, the world + enemy update below are skipped, but the
    ; frame still renders and the music keeps playing.
    lda JOY1_CURRENT
    and #JOY_START                ; A = this frame's START bit ($1000 or 0)
    cmp f:$7E0000 + PREV_START    ; changed since last frame?
    beq @pause_done               ; no change -> nothing to toggle
    sta f:$7E0000 + PREV_START    ; record the new START state
    cmp #JOY_START                ; is the new state PRESSED? (0 = just released)
    bne @pause_done               ; released this frame -> not a press
    lda f:$7E0000 + DBG_PAUSED
    eor #$0001                    ; rising edge -> flip 0<->1
    sta f:$7E0000 + DBG_PAUSED
@pause_done:
    .a16
    .i16
    lda f:$7E0000 + DBG_PAUSED
    beq @run_world                ; not paused -> run the world update below
    jmp @paused_skip_move         ; paused -> long jump to render (branch can't reach)
@run_world:
    .a16
    .i16

    ; ---------------- heading: LEFT/RIGHT rotate TURN_STEP per held frame -----
    ; The SAME R_ANGLE feeds sf_boss_matrix below, so the floor rotates under the
    ; turn while the player's facing keeps reading "up". LEFT and RIGHT produce
    ; OPPOSITE angle deltas (the tank turn).
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq @dg_no_left
    lda R_ANGLE
    clc
    adc #TURN_STEP
    and #$00FF
    sta R_ANGLE
@dg_no_left:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq @dg_no_right
    lda R_ANGLE
    sec
    sbc #TURN_STEP
    and #$00FF
    sta R_ANGLE
@dg_no_right:
    .a16

    ; ---------------- throttle: B/UP forward, Y/DOWN reverse, release -> hover -
    ; R_SPEED is SIGNED 8.8. Forward adds ACCEL up to +SPEED_CAP; reverse subtracts
    ; ACCEL down to SPEED_REV; neither held -> bleed toward 0 (hover). The signed
    ; smul16 step below moves the world forward (B/UP) or backward (Y/DOWN).
    lda JOY1_CURRENT
    bit #JOY_B
    bne @dg_fwd
    lda JOY1_CURRENT
    bit #JOY_UP
    bne @dg_fwd
    lda JOY1_CURRENT
    bit #JOY_Y
    bne @dg_rev
    lda JOY1_CURRENT
    bit #JOY_DOWN
    bne @dg_rev
    ; --- no throttle: coast toward hover (move R_SPEED toward 0) ---
    lda R_SPEED
    beq @dg_speed_done             ; already hovering
    bmi @dg_coast_neg
    ; positive speed: subtract DECEL, floor at 0
    sec
    sbc #DECEL
    bpl @dg_speed_store            ; still >= 0
    lda #$0000
    bra @dg_speed_store
@dg_coast_neg:
    .a16
    ; negative speed: add DECEL, ceil at 0
    clc
    adc #DECEL
    bmi @dg_speed_store            ; still < 0
    lda #$0000
    bra @dg_speed_store
@dg_fwd:
    .a16
    lda R_SPEED
    clc
    adc #ACCEL
    cmp #(SPEED_CAP + 1)
    bcc @dg_speed_store            ; below cap (and positive)
    lda #SPEED_CAP
    bra @dg_speed_store
@dg_rev:
    .a16
    lda R_SPEED
    sec
    sbc #ACCEL
    ; clamp to SPEED_REV (both negative): if A < SPEED_REV then A = SPEED_REV.
    pha
    sec
    sbc #SPEED_REV                ; (A - SPEED_REV); negative => A < SPEED_REV
    bpl @dg_rev_ok
    pla
    lda #SPEED_REV
    bra @dg_speed_store
@dg_rev_ok:
    .a16
    pla
@dg_speed_store:
    .a16
    sta R_SPEED
@dg_speed_done:
    .a16

    ; ---------------- integrate STEP only: (sina, cosa) x speed --------------
    ; The tank step: sincos resolves the heading into (sina, cosa), smul16 scales
    ; them by the SIGNED 8.8 speed into a 16.16 step. We compute the STEP here but
    ; do NOT commit it — the collision pass below tests each axis candidate against
    ; the terrain LUT and commits only the unblocked axis (the per-axis slide).
    lda R_ANGLE
    and #$00FF
    jsr sincos                    ; -> sina/cosa (signed); A16/I16

    ; WIDTH-RISK: smul16 contract is .a16/.i8, DB=0. Toggle I8 for the two
    ; multiplies, restore I16 after. A stays 16-bit throughout.
    sep #$10
    .i8
    lda a:sina
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16                    ; math_p = sina x speed (s32, 16.16)
    lda a:math_p + 0
    sta STEP_FX                   ; X step fraction
    lda a:math_p + 2
    sta STEP_PX                   ; X step integer (signed)

    lda a:cosa
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16
    lda a:math_p + 0
    sta STEP_FY
    lda a:math_p + 2
    sta STEP_PY
    rep #$10
    .i16

    ; ---------------- collision: per-axis candidate-test-commit (SLIDE) ------
    ; The world advances by pos -= step. Test each axis SEPARATELY so a diagonal
    ; push into an axis-aligned wall still slides along the unblocked axis.
    jsr move_x                    ; commit X step iff its footprint is clear
    jsr move_y                    ; commit Y step iff its footprint is clear

@paused_skip_move:
    .a16
    .i16
    ; ---------------- render: pin floor to world pos + rotate to heading ------
    ; (Runs even while paused, at the frozen pos/angle, so the still frame keeps
    ;  drawing and the NMI keeps committing a valid matrix.)
    sf_boss_center R_POSX + 2, R_POSY + 2
    sf_boss_matrix #SCALE_VIEW, R_ANGLE

    ; --- snapshot the matrix THIS frame committed (API block $60-$66) into scratch
    ;     BEFORE any spr macro reuses that DP. M7A=$60 M7B=$62 M7C=$64 M7D=$66. The
    ;     enemy projection reads these so it uses the EXACT matrix the floor rendered
    ;     with -> sprites stay glued (no swim). ---
    lda API_BLOCK_BASE + $00
    sta M7A_SAV
    lda API_BLOCK_BASE + $02
    sta M7B_SAV
    lda API_BLOCK_BASE + $04
    sta M7C_SAV
    lda API_BLOCK_BASE + $06
    sta M7D_SAV

    lda f:$7E0000 + DBG_PAUSED
    bne @paused_skip_enemies      ; paused -> the enemies freeze too (no pace / no hit)

    ; --- patrol: pace the enemies (world-space wall-turn) --------------------
    ; Each enemy paces its corridor; the live world pos in DBG_ENE_BASE +0/+2 is
    ; updated in place. Runs AFTER the matrix snapshot (M7A_SAV..D safe at
    ; $3E-$44) and BEFORE draw_enemies (which re-reads the live world pos). The
    ; patrol scratch lives in the now-dead collision DP $46-$4F.
    jsr patrol_enemies

    ; --- contact: hero-enemy overlap (world-box) -----------------------------
    ; Tick the grace countdown; if not graced, test the hero footprint vs each
    ; enemy in WORLD coords. On contact: knock the hero back to spawn, zero
    ; speed, tick HITS, and (re)arm the grace window so an enemy beat crossing
    ; the spawn cannot immediately re-hit. NOTE: col_box clobbers the API block
    ; ($60), but the matrix was already snapshotted to M7A_SAV..D ($3E-$44),
    ; which draw_enemies reads — so the post-contact projection stays correct.
    jsr contact_enemies

@paused_skip_enemies:
    .a16
    .i16
    ; ---------------- draw the hero (slot 0, 16x16, facing up) ----------------
    spr_clear
    ; flags=$0000: OBJ pal 0, size bit7 CLEAR => 16x16 (the SMALL size of OBSEL
    ; pair $62). bit7 SET would select the 32x32 LARGE size, which reads a 4x4
    ; tile block (tiles 0..3,16..19,32..35,48..51) — tile 32 is the enemy CHR,
    ; so a phantom enemy diamond would bleed into the hero's lower quadrant.
    spr #HERO_TILE, #HERO_X, #HERO_Y, #(HERO_SIZE_BIT), #2  ; OBJ pal 0, prio 2, 16x16

    ; --- draw: project + draw the enemies onto the floor (slots 1+) ----------
    jsr draw_enemies

    ; --- goal WIN-CARD overlay: if the hero stands on the GOAL cell, draw a 3-star
    ;     banner (slots 4-6) at screen top. Off-goal, spr_clear already parked those
    ;     slots. OVERLAY only (no state/input change), so the route/collision/pause
    ;     suites are undisturbed. Unsigned window: px-(GOAL_CX-GOAL_HALF) in 0..23
    ;     == inside the 24px goal-cell floor body (px<low wraps high -> also out).
    .a16
    .i16
    lda R_POSX + 2
    sec
    sbc #(GOAL_CX - GOAL_HALF)
    cmp #(GOAL_HALF * 2)
    bcs @no_win
    lda R_POSY + 2
    sec
    sbc #(GOAL_CY - GOAL_HALF)
    cmp #(GOAL_HALF * 2)
    bcs @no_win
    spr #WIN_TILE_OBJ, #(128 - 40), #WIN_Y, #WIN_ATTR, #WIN_PRI  ; slot 4
    spr #WIN_TILE_OBJ, #(128 - 8),  #WIN_Y, #WIN_ATTR, #WIN_PRI  ; slot 5
    spr #WIN_TILE_OBJ, #(128 + 24), #WIN_Y, #WIN_ATTR, #WIN_PRI  ; slot 6
@no_win:
    .a16
    .i16

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
; ============================== SUBROUTINES ==================================
; Collision (move_x/move_y/clamp_world/footprint_solid/px_to_tile/terr_at_world),
; world->screen projection + culling (draw_enemies/enemy_culled/ene_mirror_*),
; and the enemy patrol/contact (enemy_init/patrol_enemies/contact_enemies/abs16).
; =============================================================================

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
    bne @mx_blocked
.endif
    ; clear (or collision disabled): commit the X step
    lda CAND_FRAC
    sta R_POSX + 0
    lda CAND_PX
    sta R_POSX + 2
    rts
.if NO_COLLISION = 0
@mx_blocked:
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
    bne @my_blocked
.endif
    lda CAND_FRAC
    sta R_POSY + 0
    lda CAND_PY
    sta R_POSY + 2
    rts
.if NO_COLLISION = 0
@my_blocked:
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
    bpl @cw_not_neg               ; A >= 0 (signed)
    lda #0                       ; underflowed below 0 -> clamp to 0
    rts
@cw_not_neg:
    .a16
    cmp #(WORLD_MAX + 1)
    bcc @cw_done                  ; A <= WORLD_MAX
    lda #WORLD_MAX               ; overshot -> clamp to max
@cw_done:
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
    bne @fp_solid
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
    bne @fp_solid
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
    bne @fp_solid
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
    bne @fp_solid
    lda #0                       ; all four corners floor -> clear
    rts
@fp_solid:
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
@de_loop:
    .a16
    .i16
    ; --- fetch enemy LIVE world (x,y) from the DBG_ENE_BASE mirror (idx*8). The
    ;     enemies MOVE (patrol), so their world pos is the live WRAM mirror (seeded
    ;     from enemy_world ROM at boot, paced each frame by patrol_enemies), NOT the
    ;     static ROM table. Projection + culling then track the live position
    ;     automatically. ---
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
    bne @de_park

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
    bra @de_next
@de_park:
    .a16
    .i16
    ; off-screen: emit the slot but parked at CULL_Y (kit convention) so it does
    ; not wrap/garble on-screen. Keeps slot identity stable for the test.
    spr #ENEMY_TILE_OBJ, #$0000, #CULL_Y, #ENEMY_ATTR, #ENEMY_PRI
@de_next:
    .a16
    .i16
    lda ENE_IDX
    inc a
    sta ENE_IDX
    cmp #ENEMY_COUNT
    bcs @de_done                   ; idx >= count -> finished
    jmp @de_loop                   ; long jump: loop body > 127 bytes (branch range)
@de_done:
    .a16
    .i16
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
    bmi @ec_cull                   ; sx + margin < 0 -> off left
    cmp #(256 + 2 * CULL_MARGIN)
    bcs @ec_cull                   ; sx + margin >= 256+2*margin -> off right
    lda PRJ_SY
    clc
    adc #CULL_MARGIN
    bmi @ec_cull
    cmp #(224 + 2 * CULL_MARGIN)
    bcs @ec_cull
    lda #0
    rts
@ec_cull:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; enemy_init — seed the LIVE enemy world pos (DBG_ENE_BASE +0/+2) from the
; enemy_world ROM table, set each enemy's patrol direction to +PATROL_SPEED, and
; zero the HITS / GRACE counters. Called once at boot (RESET). The enemies pace
; from these seeds; the ROM table is the spawn seed only.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X.
; =============================================================================
enemy_init:
    .a16
    .i16
    stz PAT_IDX
@ei_loop:
    .a16
    .i16
    ; live world (x,y) = enemy_world[idx]  (ROM idx*4 -> WRAM idx*8 mirror)
    lda PAT_IDX
    asl a
    asl a                         ; *4 (ROM stride: 2 words/enemy)
    tax
    lda f:enemy_world, x          ; seed world x
    pha
    lda f:enemy_world + 2, x      ; seed world y
    pha
    lda PAT_IDX
    asl a
    asl a
    asl a                         ; *8 (WRAM mirror stride)
    tax
    pla                           ; world y
    sta f:$7E0000 + DBG_ENE_BASE + 2, x
    pla                           ; world x
    sta f:$7E0000 + DBG_ENE_BASE + 0, x
    ; direction = +PATROL_SPEED (idx*2 in the ENE_DIR_BASE table)
    lda PAT_IDX
    asl a
    tax
    lda #PATROL_SPEED
    sta f:$7E0000 + ENE_DIR_BASE, x
    ; next enemy
    lda PAT_IDX
    inc a
    sta PAT_IDX
    cmp #ENEMY_COUNT
    bcc @ei_loop                   ; idx < count -> continue
    ; zero HITS + GRACE (explicit init: the test reads HITS from boot)
    lda #0
    ldx #$0000
    sta f:$7E0000 + DBG_HITS, x
    sta f:$7E0000 + DBG_GRACE, x
    rts

; =============================================================================
; patrol_enemies — one frame of WORLD-SPACE wall-turn patrol for every enemy.
; Each enemy paces ONE axis (E0 X, E1 Y, E2 X — baked here by index). The
; candidate next pos is (live + dir) on the pace axis; the same footprint-vs-wall
; test the hero uses (footprint_solid) is run at that candidate — if it would
; enter a WALL, REVERSE the direction (and don't move this frame); else commit
; the candidate to the live mirror. So enemies pace their corridor and never
; walk through a wall.
; Entry/Exit: A16/I16, DB=0. Clobbers A, X, Y + $48-$4F scratch (NOT $3E-$44).
; =============================================================================
patrol_enemies:
    .a16
    .i16
    stz PAT_IDX
@pe_loop:
    .a16
    .i16
    ; --- load live world (x,y) into CAND_PX/CAND_PY (the footprint centre) ---
    ; NOTE: 65816 has abs-long indexed by X only (no long,Y), and footprint_solid
    ; clobbers X — so index registers are re-derived from PAT_IDX where needed
    ; (idx*8 = mirror stride, idx*2 = dir-table stride). CAND_PX/CAND_PY survive
    ; footprint_solid (it reads, never writes them).
    lda PAT_IDX
    asl a
    asl a
    asl a                         ; *8 (mirror stride)
    tax
    lda f:$7E0000 + DBG_ENE_BASE + 0, x
    sta CAND_PX
    lda f:$7E0000 + DBG_ENE_BASE + 2, x
    sta CAND_PY
    ; --- direction (signed step) for this enemy: X = idx*2 (dir-table stride) ---
    lda PAT_IDX
    asl a
    tax
    lda f:$7E0000 + ENE_DIR_BASE, x   ; dir (signed +/-PATROL_SPEED)
    ; --- AXIS dispatch: E1 (idx 1) paces Y; E0/E2 (idx 0/2) pace X ---
    ldy PAT_IDX
    cpy #1
    beq @pe_axis_y
    ; ---- X axis: candidate X = live X + dir ----
    clc
    adc CAND_PX
    sta CAND_PX                   ; candidate X (footprint Y unchanged)
    jsr footprint_solid           ; A != 0 if the candidate footprint hits a wall
    bne @pe_reverse
    ; clear -> commit candidate X to the live mirror (re-derive X = idx*8)
    lda PAT_IDX
    asl a
    asl a
    asl a
    tax
    lda CAND_PX
    sta f:$7E0000 + DBG_ENE_BASE + 0, x
    bra @pe_next
@pe_axis_y:
    .a16
    .i16
    ; ---- Y axis: candidate Y = live Y + dir ----
    clc
    adc CAND_PY
    sta CAND_PY                   ; candidate Y (footprint X unchanged)
    jsr footprint_solid
    bne @pe_reverse
    lda PAT_IDX
    asl a
    asl a
    asl a
    tax
    lda CAND_PY
    sta f:$7E0000 + DBG_ENE_BASE + 2, x
    bra @pe_next
@pe_reverse:
    .a16
    .i16
    ; blocked -> flip the sign of the direction (negate the 16-bit word) and
    ; leave the live pos unchanged this frame (the enemy turns in place).
    lda PAT_IDX
    asl a
    tax                           ; X = idx*2 (dir-table stride)
    lda #0
    sec
    sbc f:$7E0000 + ENE_DIR_BASE, x   ; -dir
    sta f:$7E0000 + ENE_DIR_BASE, x
@pe_next:
    .a16
    .i16
    lda PAT_IDX
    inc a
    sta PAT_IDX
    cmp #ENEMY_COUNT
    bcc @pe_loop                   ; idx < count -> continue
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
    beq @ce_scan                   ; grace == 0 -> contact live
    dec a
    sta f:$7E0000 + DBG_GRACE, x
    rts                           ; graced this frame -> no contact
@ce_scan:
    .a16
    .i16
    ; --- spawn sanctuary: no hit while the hero stands ON the spawn tile. A respawn
    ;     drops the hero back at spawn; if an enemy beat crosses the spawn an idle /
    ;     just-respawned hero would be ground down (HITS climbing while standing
    ;     still). A hero that has DRIVEN off the spawn is hit normally. This gates the
    ;     HIT only — no enemy is moved, so the patrol you see is unchanged. ---
    lda R_POSX + 2
    sec
    sbc #SPAWN_PX
    jsr abs16                     ; |hx - spawn_x|
    cmp #SPAWN_SANCTUARY
    bcs @ce_scan_go                ; off the spawn on X -> contact is live
    lda R_POSY + 2
    sec
    sbc #SPAWN_PY
    jsr abs16                     ; |hy - spawn_y|
    cmp #SPAWN_SANCTUARY
    bcc @ce_safe                   ; within the sanctuary on BOTH axes -> no contact
@ce_scan_go:
    .a16
    .i16
    stz PAT_IDX
@ce_loop:
    .a16
    .i16
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
    bcs @ce_no                     ; >= threshold -> no overlap this enemy
    ; --- |hy - ey| < CONTACT_W ? ---
    lda R_POSY + 2
    sec
    sbc f:$7E0000 + DBG_ENE_BASE + 2, x   ; hy - ey
    jsr abs16
    cmp #CONTACT_W
    bcc @ce_hit                    ; both axes overlap -> CONTACT
@ce_no:
    .a16
    .i16
    ; next enemy
    lda PAT_IDX
    inc a
    sta PAT_IDX
    cmp #ENEMY_COUNT
    bcc @ce_loop
    rts
@ce_hit:
    .a16
    .i16
    ; knockback: hero -> spawn, speed 0
    lda #SPAWN_PX
    sta R_POSX + 2
    stz R_POSX + 0
    lda #SPAWN_PY
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_SPEED
    ; HITS += 1
    ldx #$0000
    lda f:$7E0000 + DBG_HITS, x
    inc a
    sta f:$7E0000 + DBG_HITS, x
    ; re-arm GRACE so an enemy beat over the spawn cannot immediately re-hit
    lda #GRACE_FRAMES
    sta f:$7E0000 + DBG_GRACE, x
    ; the "ow": the hurt sound + a screen flash. The knockback teleports the hero
    ; to spawn, which is INVISIBLE when the hero was already at (or near) spawn — so
    ; the flash is the actual "you got hit" feedback: snap the screen dark this
    ; frame, then pace it back to full over ~24 frames (sf_bright_fade_tick drives it).
    sf_sfx #SFX::player_hurt
    sf_bright_fade #1, #0         ; snap brightness to near-black THIS frame
    sf_bright_fade #$0F, #24      ; then fade back up to full over 24 frames
    rts
@ce_safe:
    .a16
    .i16
    rts                           ; hero on the spawn tile -> no contact this frame

; =============================================================================
; abs16 — A = |A| for a signed 16-bit accumulator. Entry/Exit A16/I16; no DP.
; =============================================================================
abs16:
    .a16
    .i16
    bpl @abs16_done                ; A >= 0 -> already absolute
    eor #$FFFF
    inc a                         ; two's-complement negate
@abs16_done:
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
.include "tad_bridge.asm"          ; TAD audio bridge (tad_bridge_init/process, tad_music/sfx)
.include "bright_fade_engine.asm"  ; engine_bright_fade backing (the get-hit flash)

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
.include "assets/win.inc"

.if ENEMY_MISCOLOR
; Non-vacuity control palette (only compiled for -DENEMY_MISCOLOR): a COOL blue
; ramp so the demon CHR renders blue instead of warm -> the rendered enemy-warm
; band reads 0. The DEFAULT ROM contains none of this (guarded), so it stays
; byte-for-byte identical to a build without the toggle.
miscolor_pal:
    .word $0000, $34E6, $4569, $5A0D, $0000, $0000, $0000, $0000
    .word $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000
.endif

; =============================================================================
; ================================= DATA ======================================
; =============================================================================

; --- enemy SPAWN-SEED world positions (ROM table; 2 words each: world x, world y
;     in integer px). These SEED the live WRAM positions (DBG_ENE_BASE +0/+2) at
;     boot; the enemies then PACE their corridor (patrol_enemies), so the live pos
;     is in WRAM, not here. Each seed is a walkable, footprint-clear floor
;     cell-centre on the navigable START->GOAL route, SPREAD by distance from
;     spawn (px 116,116) so culling-by-visibility is exercised:
;       E0 NEAR-START  tile(19,14) px(156,116)  X-axis pace (start corridor row)
;       E1 MID-PATH    tile(34,24) px(276,196)  Y-axis pace (centre column)
;       E2 PRE-EXIT    tile(39,34) px(316,276)  X-axis pace (row corridor BEFORE
;                      the goal). It sits a few cells before the GOAL (not on the
;                      goal-adjacent cell) so reaching the GOAL (356,356) triggers
;                      NO contact — the exit stays a safe destination. E2 paces
;                      y=276, never the goal's y=356.
;     All three seeds are footprint-clear (verified vs make_dungeon.is_wall).
;     Kept in a small ROM table (no link-cfg widening — BANK1 stays full). ---
enemy_world:
    .word 156, 116                ; E0 near-start (X-axis pace)
    .word 276, 196                ; E1 mid-path  (Y-axis pace)
    .word 316, 276                ; E2 pre-exit  (X-axis pace, relocated off goal)

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
