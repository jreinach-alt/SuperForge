; =============================================================================
; play scene — the game: a hero, a level, two ghosts and six coins
; =============================================================================
; Composition: platformer_bg (the level on BG1 + the parallax skyline on BG2),
; platformer_obj (the three actors), rgb_gradient (the dusk wash on the
; backdrop, and with it the colour math), bg_text (the HUD). Every resource
; this scene touches is an allocator-emitted symbol; the game logic below
; reads and writes those and nothing else.
;
; LAYER OWNERSHIP, asserted here and in platformer_bg/feature.toml because
; layer identity is not a resource the allocator models: this
; enter is the only writer of BGMODE, BG1SC, BG2SC, BG3SC, BG12NBA, BG34NBA
; and TM in this game's play scene.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; =============================================================================
; THE REGION-CORRECT UNITS — an arc takes TWO scales, not one
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). A VELOCITY is px per frame and scales by r. A GRAVITY is
; px per frame SQUARED and scales by r SQUARED — and doing only the first is
; the classic half-conversion: the fall accelerates at NTSC's rate through
; frames that are 20% longer, the arc flattens, the apex drops and the hop
; stops clearing the pit it was tuned to clear. docs/95 §3.3 names this rail
; as the one needing the two-constant treatment; this is it.
;
; The pair preserves the arc's SHAPE, not merely its speed:
;
;     apex        = v0^2 / 2g   ->  (v0*r)^2 / (2*g*r^2)   = the same apex
;     flight time = 2*v0/g frames -> (2*v0/g)/r frames, which at 50.007 fps
;                   is the same number of REAL SECONDS as it was at 60.099
;
; TS_SCALED / TS_SCALE are tick_scale's build-time twin of TS_STEP's PAL arm,
; which is what lets a per-frame-SQUARED quantity be scaled TWICE (once here
; into the base, once by the macro). They are NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced, and the
; `+ DEN/2` rounding is the run-time arm's own, so the two cannot disagree by
; a count.

; --- the three rates on one r: the walk, the ghosts, the animation clock ---
; PLF_WALK is still the one number to reach for when tuning how the hero
; feels; what changed is that it is a RATE rather than a per-frame immediate.
TS_WALK_BASE = PLF_WALK * TS_ONE
; THE GHOSTS' BEAT. gh_step moves one pixel a frame — it is written as an
; `inc a`/`dec a` rather than as a constant, which is why the base is spelled
; here and not in platformer.inc. It stays a separate pair from the animation
; clock even though the two bases are numerically equal: they are different
; QUANTITIES (world px against animation units) and a shared accumulator
; would couple them the day either is tuned.
TS_GHOST_BASE = 1 * TS_ONE
; ONE ANIMATION UNIT. The DIVIDER (PLF_ANIM_RATE) is untouched — scaling a
; small integer divider is docs/95 §5.2's class C and has no correct answer —
; so what is scaled is the amount the CLOCK advances by.
TS_ANIM_BASE = TS_ONE

; --- gravity: the r^2 site, and the only one on this rail ------------------
; TS_STEP applies exactly one r, so the other one goes into the BASE — on the
; PAL arm only, which is why the tick branches on ES_RGN_PAL BEFORE the macro
; instead of after it. Both arms share one accumulator: a console cannot
; change region, so only one of them is ever taken.
TS_GRAV_BASE   = PLF_GRAVITY * TS_ONE
TS_SCALED TS_GRAV_BASE_R, TS_GRAV_BASE

; --- the three velocities: one r each, chosen once at enter ----------------
; The two negative ones are scaled as MAGNITUDES and negated, so the rounding
; happens on the number the physics means rather than on a two's complement.
PLF_JUMP_MAG   = (1 << 16) - PLF_JUMP_VEL
PLF_CUT_MAG    = (1 << 16) - PLF_JUMP_CUT
PLF_JUMP_VEL_R = (1 << 16) - TS_SCALE(PLF_JUMP_MAG)
PLF_JUMP_CUT_R = (1 << 16) - TS_SCALE(PLF_CUT_MAG)
TS_SCALED PLF_MAX_FALL_R, PLF_MAX_FALL

; The bounds the SCALED constants have to keep, asserted rather than trusted.
; A region scale is exactly the kind of change that walks a tuned constant
; through a bound nobody re-checked.
;   * do_physics' landing snap is derived from the SURFACE's row, so it holds
;     at any speed — but only while a single frame's step cannot cross more
;     than one tile row, which is PLF_BOX px;
;   * gh_step probes ONE PIXEL past the leading edge and then moves, so a
;     step of 2 px can put the ghost 1 px into the wall it turns at on the
;     next frame. Bounded, and bounded by this assert: with a base of 1 px
;     the published step is 1 or 2 and never 3.
.assert PLF_MAX_FALL_R <= PLF_BOX * 256, error, "the PAL-scaled PLF_MAX_FALL crosses more than one tile row in a frame — the landing snap's no-tunnel bound does not cover it"
.assert TS_SCALE(PLF_JUMP_MAG) <= PLF_BOX * 256, error, "the PAL-scaled jump velocity crosses more than one tile row in a frame"
.assert TS_SCALE(TS_GHOST_BASE) < 2 * TS_ONE, error, "the PAL-scaled ghost step can reach 3 px — gh_step's one-pixel lookahead would let a ghost walk 2 px into a wall"

; BG3 2bpp tile attr for the HUD (palette 7, priority — the HUD sits above the
; level, the sky and the sprites)
PLAY_TXT_ATTR = (7 << 10) | (1 << 13)

; The HUD's two live cells, and the labels that never change.
HUD_LIVES_CELL = ES_V_TEXT_MAP + 7
HUD_COINS_CELL = ES_V_TEXT_MAP + 23

; The pause banner: eight cells on row 13, written one per frame through
; bg_text's queue. Pausing queues "PAUSED  ", unpausing
; queues eight spaces, so a block always totally overwrites its predecessor
; and there is no clear pass and no length bookkeeping.
PLF_MSG_LEN  = 8
PLF_MSG_CELL = ES_V_TEXT_MAP + 13*32 + 12

; Where rgb_gradient's dusk ramp LANDS, declared at the composition site
; because it is this scene's look and not the feature's (rgb_gradient.asm has
; no default). IT LANDS ON THE BACKDROP ALONE: the ramp IS the sky — it shows
; through every transparent level cell and every gap between the hills — and
; BG1's terrain, BG2's skyline, BG3's HUD and the actors all keep their
; authored colours.
RG_MATH_LAYERS = PLF_MATH_BACKDROP

; --- scene-scoped engine feature code — INSIDE the scope: its claims are
; scene-scoped, so its symbols must be too --------------------------------
.include "platformer_bg.asm"
.include "platformer_obj.asm"
.include "rgb_gradient.asm"

; =============================================================================
; ENTER — the only place this rail's whole look is legal to write
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr contract).
enter:
    .a16
    .i16
    ; ---- the text sub-palette + BG3's registers ---------------------------
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; colour 0: black $0000
    sta a:$2122
    sta a:$2122
    lda #$84                    ; colour 1: dark navy $1084
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: white $7FFF
    sta a:$2122
    lda #$7F
    sta a:$2122
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #PLAY_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the level, the sky, the sprites, the dusk ------------------------
    jsr plf_arm
    jsr obj_arm
    jsr rg_arm
    jsr plf_plx_arm
    ; ---- BGMODE + TM, and the four HDMA channels in the enable shadow -----
    sep #$20
    .a8
    lda #$09                    ; BGMODE 1, BG3 priority high (the HUD sits
    sta a:$2105                 ;   above the level and the sky)
    lda #$17                    ; TM: BG1 + BG2 + BG3 + OBJ
    sta a:$212C
    lda z:ES_SM_NMI+2
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH) | (1 << ES_H_PLX_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    ; ---- the round --------------------------------------------------------
    jsr round_reset
    ; ---- the HUD's fixed labels, and its two live digits ------------------
    lda #PLAY_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_lives)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_lives
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 1)
    jsr text_puts
    lda #.loword(s_coins)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + 17)
    jsr text_puts
    lda z:US_LIVES
    ldx #HUD_LIVES_CELL
    jsr text_put_digit          ; forced blank: straight to VRAM, no queue
    lda z:US_COINS
    ldx #HUD_COINS_CELL
    jsr text_put_digit
    ; ---- sprites placed BEFORE the first displayed frame, so frame 0 shows
    ; the hero rather than power-on garbage (rule 5) ------------------------
    jsr do_draw
    rts

; --- round_reset: everything a fresh round starts from ----------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; Every value below is the FRESH-RUN baseline, written unconditionally. The
; continue then restores exactly ONE of them, and only on a full-length
; successful load — so a rejected load needs no fallback work, and a
; half-restored state is impossible by construction rather than by care.
round_reset:
    .a16
    .i16
    lda f:US_RUNS_LONG
    inc a
    sta f:US_RUNS_LONG
    lda #PLF_SPAWN_X
    sta z:US_PX
    jsr plr_spawn_y
    lda #0
    sta z:US_FACING
    sta z:US_COINS
    sta z:US_GOVER
    sta z:US_PAUSED             ; WRAM is random at power-on: this store IS
    sta z:US_DIRTY              ;   the write-before-read contract (rule 5)
    sta z:US_ATICK
    sta z:US_AFRAME
    sta z:US_MSG
    sta z:US_MSGPOS
    lda #PLF_LIVES
    sta z:US_LIVES
    lda #PLF_GRACE
    sta z:US_HURT               ; spawn grace i-frames
    ; ---- the timebase's eight words, and the three region-selected feel
    ;      constants. WRAM is random at power-on, so these stores ARE the
    ;      write-before-read contract too. -------------------------------
    lda #0
    sta z:US_TSW_ACC
    sta z:US_TSW
    sta z:US_TSG_ACC
    sta z:US_TSG
    sta z:US_TSA_ACC
    sta z:US_TSA
    sta z:US_TSH_ACC
    sta z:US_TSH
    lda z:ES_RGN_PAL
    beq :+
    lda #PLF_MAX_FALL_R
    sta z:US_VMAX
    lda #PLF_JUMP_VEL_R
    sta z:US_VJUMP
    lda #PLF_JUMP_CUT_R
    sta z:US_VCUT
    bra :++
:   .a16
    .i16
    lda #PLF_MAX_FALL           ; today's constants, to the bit
    sta z:US_VMAX
    lda #PLF_JUMP_VEL
    sta z:US_VJUMP
    lda #PLF_JUMP_CUT
    sta z:US_VCUT
:   .a16
    .i16
    ; ---- the two ghosts ---------------------------------------------------
    lda #1
    sta z:US_E1ALIVE
    sta z:US_E2ALIVE
    sta z:US_E2D                ; ghost 2 starts walking east...
    lda #0
    sta z:US_E1D                ; ...and ghost 1 west
    lda #PLF_G1_X
    sta z:US_E1X
    lda #PLF_G2_X
    sta z:US_E2X
    ; ---- CONTINUE: consume the title's pending flag -----------------------
    ; The gate is sv_load's RETURN CODE, not the slot's bytes: only a load
    ; that answers with exactly PLF_SAVE_LEN touches the coin count. The
    ; payload lands in the global `bank` word rather than on US_COINS, so a
    ; rejected or oversize load cannot reach the round's state at all.
    lda f:US_CONTPEND_LONG
    beq @fresh
    lda #0
    sta f:US_CONTPEND_LONG
    sta z:SV_SLOT               ; slot 0 (A is still 0)
    lda #US_BANK
    sta z:SV_PTR
    lda #PLF_SAVE_LEN
    sta z:SV_CAP                ; dest capacity: the 2-byte bank
    sep #$20
    .a8
    lda #US_BANK_BANK
    sta z:SV_PTR+2
    rep #$20
    .a16
    jsr sv_load
    cmp #PLF_SAVE_LEN
    bne @fresh
    lda f:US_BANK_LONG
    cmp #PLF_COINS_ALL          ; a banked count at or past the target would
    bcs @fresh                  ;   win the round on frame 1 — refuse it
    sta z:US_COINS
@fresh:
    .a16
    .i16
    rts

; --- plr_spawn_y: the hero, standing on the spawn ledge ---------------------
; In/out: A16/I16, DB=0. Clobbers A.
plr_spawn_y:
    .a16
    .i16
    lda #PLF_SPAWN_Y
    sta z:US_PIXY
    xba
    and #$FF00
    sta z:US_PYF                ; the 8.8 form of the same number
    lda #0
    sta z:US_VY
    sta z:US_GROUNDED
    rts

; --- exit: put back everything a menu does not expect to inherit ------------
; In/out: A16/I16, DB=0, forced blank.
exit:
    .a16
    .i16
    jsr rg_disarm               ; or the menus inherit this scene's tint
    jsr obj_park                ; ...and its cast
    jsr plf_park                ; ...and its scroll latches
    jsr plf_q_init              ; ...and a half-staged coin cell
    rts

; =============================================================================
; TICK — one frame
; =============================================================================
; In/out: A16/I16, DB=0. Display is active: no VRAM writes here. The three
; things that must reach VRAM (a HUD digit, a banner cell, a collected coin's
; tilemap cell) are STAGED and committed by the NMI hook.
tick:
    .a16
    .i16
    ; ---- this frame's four region-correct steps, published once ----------
    ; BEFORE the pause and game-over gates, deliberately: a step word that
    ; stops being republished is a stale word waiting to be read, and nothing
    ; below MOVES on a frozen frame anyway — the freeze is that the readers do
    ; not run, never that a rate was zeroed (platformer_bg/feature.toml).
    ; On NTSC each publishes the constant platformer.inc authored, to the
    ; unit, and the carried fraction stays 0 for ever.
    TS_STEP z:US_TSW_ACC, TS_WALK_BASE
    sta z:US_TSW
    TS_STEP z:US_TSH_ACC, TS_GHOST_BASE
    sta z:US_TSH
    TS_STEP z:US_TSA_ACC, TS_ANIM_BASE
    sta z:US_TSA
    ; Gravity is per-frame-SQUARED: the second r rides the BASE, so the arm
    ; is chosen BEFORE the macro rather than after it. ANONYMOUS LABELS, not
    ; `@cheap` ones: TS_STEP's `.local` labels are plain symbols, so expanding
    ; it between a `@label` and its use RESETS the cheap-local scope and the
    ; branch target goes undefined.
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
    jsr do_msg                  ; the banner drains whatever the state is
    ; ---- START toggles a full freeze -------------------------------------
    lda z:US_GOVER
    bne @ended
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @pause_state
    lda z:US_PAUSED
    eor #1
    sta z:US_PAUSED
    beq @unpaused
    lda #1                      ; toggled to paused -> show it
    bra @banner
@unpaused:
    .a16
    .i16
    lda #2                      ; toggled to running -> wipe the row
@banner:
    .a16
    .i16
    sta z:US_MSG
    lda #0
    sta z:US_MSGPOS
@pause_state:
    .a16
    .i16
    lda z:US_PAUSED
    beq @running
    rts                         ; paused: nothing below runs, and because the
                                ;   camera therefore does not advance, the
                                ;   rebuilt parallax table is identical frame
                                ;   to frame and the sky pixels do not move
@ended:
    .a16
    .i16
    ; The round is over: the world holds while the fade takes the screen. Only
    ; the HUD drains, so the last life or the sixth coin is on screen for it.
    jsr do_hud
    rts
@running:
    .a16
    .i16
    jsr do_anim
    jsr do_walk
    jsr do_jump
    jsr do_physics
    jsr do_pit
    lda z:US_GOVER              ; the last life can end the round mid-frame...
    bne @drawn
    jsr do_coin
    lda z:US_GOVER              ; ...and so can the sixth coin
    bne @drawn
    jsr do_ghosts
    jsr do_combat
@drawn:
    .a16
    .i16
    jsr do_hud
    jsr do_camera
    jsr do_draw
    rts

; --- do_anim: the shared clock the hero and both ghosts run on --------------
; In/out: A16/I16, DB=0. Clobbers A.
do_anim:
    .a16
    .i16
    ; THE CLOCK ADVANCES BY US_TSA, NOT BY ONE. That is this rail's answer to
    ; docs/95 §5.2's class C: a frame-rate divider is a small integer with no
    ; correct x5/6, so PLF_ANIM_RATE is left alone and what the clock ADVANCES
    ; BY is scaled instead — 1 unit per NTSC frame, 1.2018 per PAL frame,
    ; the fraction carried by tick_scale. On NTSC US_TSA is exactly 1 every
    ; frame, so this is `inc a` in behaviour.
    lda z:US_ATICK
    clc
    adc z:US_TSA
    cmp #PLF_ANIM_RATE
    bcc @store
    ; CARRY THE OVERSHOOT rather than zeroing. On NTSC the clock arrives at
    ; the divider EXACTLY (it steps by 1 from 0), so tick - rate = 0 and this
    ; is the `lda #0` it replaces; on PAL a 2-unit frame can cross the divider
    ; by one, and dropping that one is a bias nothing downstream can see.
    sec
    sbc #PLF_ANIM_RATE
    sta z:US_ATICK
    lda z:US_AFRAME
    inc a
    cmp #PLF_ANIM_STEPS
    bcc :+
    lda #0
:   .a16
    .i16
    sta z:US_AFRAME
    rts
@store:
    .a16
    .i16
    sta z:US_ATICK
    rts

; =============================================================================
; THE WORLD, AS A QUESTION — box probes over platformer_bg's ROM level
; =============================================================================
; --- box_solid: is the 8x8 box at (US_AX, US_AY) inside solid terrain? ------
; In:  A16/I16, DB=0. US_AX / US_AY = the box's top-left, in world pixels.
; Out: A16 = 0 clear / non-zero blocked. Clobbers A, X, Y, US_PROBEX/Y, US_TMP.
;
; Four corners, and every one of them is checked: a box that only tested its
; leading edge would walk into a wall it is one pixel taller than.
box_solid:
    .a16
    .i16
    lda z:US_AX
    sta z:US_PROBEX
    lda z:US_AY
    sta z:US_PROBEY
    jsr plf_flags
    and #PLF_F_SOLID
    bne @hit
    lda z:US_AX
    clc
    adc #(PLF_BOX - 1)
    sta z:US_PROBEX
    jsr plf_flags
    and #PLF_F_SOLID
    bne @hit
    lda z:US_AY
    clc
    adc #(PLF_BOX - 1)
    sta z:US_PROBEY
    jsr plf_flags
    and #PLF_F_SOLID
    bne @hit
    lda z:US_AX
    sta z:US_PROBEX
    jsr plf_flags
    and #PLF_F_SOLID
    rts
@hit:
    .a16
    .i16
    lda #PLF_F_SOLID
    rts

; --- edge_flags: the OR of the flags under the box's two x extremes ---------
; In:  A16/I16, DB=0. US_AX = the box's x, US_AY = the row to probe.
; Out: A16 = the combined flags. Clobbers A, X, Y, US_PROBEX/Y, US_TMP,
;      US_TMP2.
edge_flags:
    .a16
    .i16
    lda z:US_AX
    sta z:US_PROBEX
    lda z:US_AY
    sta z:US_PROBEY
    jsr plf_flags
    sta z:US_TMP2
    lda z:US_AX
    clc
    adc #(PLF_BOX - 1)
    sta z:US_PROBEX
    jsr plf_flags
    ora z:US_TMP2
    rts

; =============================================================================
; MOVEMENT
; =============================================================================
; --- do_walk: the d-pad, per axis, against the level ------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
; The tentative x is probed BEFORE it is committed, so a wall blocks the move
; rather than being escaped from afterwards.
do_walk:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @left
    lda z:US_PX
    clc
    adc z:US_TSW
    cmp #(PLF_WORLD_W - PLF_BOX)
    bcs @left                   ; the world's right edge
    sta z:US_AX
    lda z:US_PIXY
    sta z:US_AY
    jsr box_solid
    bne @left
    lda z:US_AX
    sta z:US_PX
    lda #0
    sta z:US_FACING
@left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @done
    lda z:US_PX
    sec
    sbc z:US_TSW
    cmp #PLF_BOX
    bcc @done                   ; the world's left edge
    sta z:US_AX
    lda z:US_PIXY
    sta z:US_AY
    jsr box_solid
    bne @done
    lda z:US_AX
    sta z:US_PX
    lda #1
    sta z:US_FACING
@done:
    .a16
    .i16
    rts

; --- do_jump: A or B launches; releasing BOTH cuts the rise short -----------
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE CUT IS WHY THE JUMP IS VARIABLE-HEIGHT, and it is a CLAMP rather than a
; zeroing: a released button takes the rise down to PLF_JUMP_CUT and no
; further, so a tap still leaves the ground. Both operands are negative, so the
; unsigned compare is the signed one.
do_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #(JOY_A | JOY_B)        ; either face button, the player's pick
    beq @cut
    lda z:US_GROUNDED
    beq @cut
    lda z:US_VJUMP
    sta z:US_VY
    lda #0
    sta z:US_GROUNDED
    jsr plf_blip
    rts                         ; a launch frame is never also a cut frame
@cut:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #(JOY_A | JOY_B)
    bne @done                   ; still held -> keep rising
    lda z:US_VY
    bpl @done                   ; falling -> nothing to cut
    cmp z:US_VCUT
    bcs @done                   ; already slower than the cut
    lda z:US_VCUT
    sta z:US_VY
@done:
    .a16
    .i16
    rts

; --- do_physics: gravity, the tentative step, and what it lands on ----------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
;
; THE LANDING FRAME IS WHERE THE BUGS LIVE, not the apex. An apex depends only
; on PLF_JUMP_VEL and PLF_GRAVITY; the rest position depends on PLF_MAX_FALL
; and on this snap, and a snap that is off by the box height embeds the sprite
; in the floor while every apex assertion still passes. So the snap is derived
; from the SURFACE's row rather than from the position the fall reached:
; row_top - PLF_BOX puts the box's bottom exactly on the surface, at any speed.
do_physics:
    .a16
    .i16
    ; ---- gravity, clamped at terminal velocity ---------------------------
    lda z:US_VY
    clc
    adc z:US_TSG
    bmi @store_v                ; still rising: no terminal clamp applies
    cmp z:US_VMAX               ; >= terminal -> clamp to it. The `+ 1`
    bcc @store_v                ;   the immediate form carried is folded
    lda z:US_VMAX               ;   into the compare: A = VMAX clamps to VMAX
@store_v:
    .a16
    .i16
    sta z:US_VY
    ; ---- the tentative position ------------------------------------------
    clc
    adc z:US_PYF
    sta z:US_NEWY
    xba
    and #$00FF
    sta z:US_TMP                ; ...and its integer part
    lda #0
    sta z:US_GROUNDED
    lda z:US_VY
    bmi @rising
    ; ---- falling: what is under the box's bottom edge? -------------------
    lda z:US_PX
    sta z:US_AX
    lda z:US_TMP
    clc
    adc #PLF_BOX                ; the row just below the box
    sta z:US_AY
    jsr edge_flags
    sta z:US_TMP2
    and #PLF_F_SOLID
    bne @land
    lda z:US_TMP2
    and #PLF_F_PLAT
    beq @apply
    ; A ONE-WAY PLATFORM ONLY CATCHES A CROSSING FROM ABOVE. The test is the
    ; box's OLD bottom against the surface's top: at or above it, the box was
    ; over the platform and now lands on it; below it, the box is inside the
    ; platform's own body and passes through.
    jsr row_top
    sta z:US_TMP2
    lda z:US_PIXY
    clc
    adc #PLF_BOX                ; the pre-move bottom
    cmp z:US_TMP2
    beq @land
    bcs @apply
@land:
    .a16
    .i16
    jsr row_top
    sec
    sbc #PLF_BOX                ; ...so the box's bottom rests on the surface
    xba
    and #$FF00
    sta z:US_NEWY
    lda #0
    sta z:US_VY
    lda #1
    sta z:US_GROUNDED
    bra @apply
@rising:
    .a16
    .i16
    ; ---- rising: a head bump blocks the whole step -----------------------
    lda z:US_PX
    sta z:US_AX
    lda z:US_TMP
    sta z:US_AY
    jsr edge_flags
    and #PLF_F_SOLID
    beq @apply
    lda #0
    sta z:US_VY
    lda z:US_PYF
    sta z:US_NEWY
@apply:
    .a16
    .i16
    lda z:US_NEWY
    sta z:US_PYF
    xba
    and #$00FF
    sta z:US_PIXY
    rts

; --- row_top: the pixel y of the top of the row containing US_AY ------------
; In/out: A16/I16, DB=0. Out: A16. Clobbers A.
; Shifts rather than a mask, so the constant stays a small one.
row_top:
    .a16
    .i16
    lda z:US_AY
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl
    .endrepeat
    rts

; --- do_pit: falling past the world costs a life ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
do_pit:
    .a16
    .i16
    lda z:US_PIXY
    cmp #(PLF_PIT_Y + 1)
    bcc @done
    jsr life_lost
@done:
    .a16
    .i16
    rts

; --- do_coin: the box's centre, against the coin flag -----------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
; plf_flags leaves the cell index in X, which is exactly what plf_take_coin
; wants — so the pickup needs no second lookup and the two cannot disagree
; about which cell was collected.
do_coin:
    .a16
    .i16
    lda z:US_PX
    clc
    adc #(PLF_BOX / 2)
    sta z:US_PROBEX
    lda z:US_PIXY
    clc
    adc #(PLF_BOX / 2)
    sta z:US_PROBEY
    jsr plf_flags
    and #PLF_F_COIN
    beq @done
    jsr plf_take_coin           ; the bitmap AND the tilemap cell
    lda z:US_COINS
    inc a
    sta z:US_COINS
    lda z:US_DIRTY
    ora #2                      ; the coins digit wants reprinting
    sta z:US_DIRTY
    jsr plf_blip
    lda z:US_COINS
    cmp #PLF_COINS_ALL
    bcc @done
    lda #SCENE_WIN
    jsr round_ends
@done:
    .a16
    .i16
    rts

; =============================================================================
; THE GHOSTS
; =============================================================================
; --- do_ghosts: both patrols, and ghost 1's fair-start clamp ----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the probe scratch.
do_ghosts:
    .a16
    .i16
    lda z:US_E1ALIVE
    beq @two
    lda z:US_E1X
    sta z:US_AX
    lda #PLF_G1_Y
    sta z:US_AY
    lda z:US_E1D
    sta z:US_TMP2
    jsr gh_step
    lda z:US_TMP2
    sta z:US_E1D
    ; The ground beat would otherwise walk to x = 0 and grind a player who
    ; never leaves spawn. Turn it back east at the clamp.
    lda z:US_AX
    cmp #PLF_G1_MIN_X
    bcs @one_ok
    lda #PLF_G1_MIN_X
    sta z:US_AX
    lda #1
    sta z:US_E1D
@one_ok:
    .a16
    .i16
    lda z:US_AX
    sta z:US_E1X
@two:
    .a16
    .i16
    lda z:US_E2ALIVE
    beq @done
    lda z:US_E2X
    sta z:US_AX
    lda #PLF_G2_Y
    sta z:US_AY
    lda z:US_E2D
    sta z:US_TMP2
    jsr gh_step
    lda z:US_TMP2
    sta z:US_E2D
    lda z:US_AX
    sta z:US_E2X
@done:
    .a16
    .i16
    rts

; --- gh_step: one patrol step -----------------------------------------------
; In:  A16/I16, DB=0. US_AX = x, US_AY = the beat's y, US_TMP2 = direction
;      (0 = west, 1 = east). Out: US_AX and US_TMP2 updated.
;      Clobbers A, X, Y, US_PROBEX/Y, US_TMP.
;
; A ghost turns for either of two reasons: a wall ahead, or NO FLOOR ahead. The
; second is what keeps ghost 1 out of the pits and ghost 2 on its ledge, and it
; is why the ledge may cross the world's page seam at column 32 without any
; special case: the probe indexes an immutable ROM blob linearly, so the seam
; is not a thing the patrol can notice.
gh_step:
    .a16
    .i16
    lda z:US_TMP2
    beq @west
    lda z:US_AX
    clc
    adc #PLF_GHOST_W            ; the column just past the right edge
    bra @lead
@west:
    .a16
    .i16
    lda z:US_AX
    dec a                       ; ...or just past the left one
@lead:
    .a16
    .i16
    sta z:US_PROBEX
    lda z:US_AY
    clc
    adc #(PLF_BOX / 2)          ; body height: is there a wall?
    sta z:US_PROBEY
    jsr plf_flags
    and #PLF_F_SOLID
    bne @turn
    lda z:US_AY
    clc
    adc #PLF_BOX                ; foot height: is there a floor?
    sta z:US_PROBEY
    jsr plf_flags
    and #(PLF_F_SOLID | PLF_F_PLAT)
    beq @turn
    lda z:US_TMP2
    beq @go_west
    lda z:US_AX
    clc
    adc z:US_TSH                ; the beat's px this frame: 1 on NTSC, 1 or 2
    sta z:US_AX                 ;   on PAL, averaging 1.2018
    rts
@go_west:
    .a16
    .i16
    lda z:US_AX
    sec
    sbc z:US_TSH
    sta z:US_AX
    rts
@turn:
    .a16
    .i16
    lda z:US_TMP2
    eor #1
    sta z:US_TMP2
    rts

; --- do_combat: stomp or hurt, one resolution a frame -----------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
do_combat:
    .a16
    .i16
    lda z:US_HURT
    beq @one
    dec a                       ; i-frames: invulnerable, and blinking
    sta z:US_HURT
    rts
@one:
    .a16
    .i16
    lda z:US_E1ALIVE
    beq @two
    lda z:US_E1X
    sta z:US_AX
    lda #PLF_G1_Y
    sta z:US_AY
    jsr gh_contact
    beq @two
    cmp #1
    bne @hurt
    lda #0
    sta z:US_E1ALIVE
    jsr stomp_bounce
    rts
@two:
    .a16
    .i16
    lda z:US_E2ALIVE
    beq @done
    lda z:US_E2X
    sta z:US_AX
    lda #PLF_G2_Y
    sta z:US_AY
    jsr gh_contact
    beq @done
    cmp #1
    bne @hurt
    lda #0
    sta z:US_E2ALIVE
    jsr stomp_bounce
    rts
@hurt:
    .a16
    .i16
    jsr life_lost
@done:
    .a16
    .i16
    rts

; --- gh_contact: hero box vs ghost box --------------------------------------
; In:  A16/I16, DB=0. US_AX = the ghost's x, US_AY = its y.
; Out: A16 = 0 no contact / 1 stomp / 2 hurt. Clobbers A.
;
; An AABB overlap, then the ONE discrimination that matters: a hero who is
; falling and whose feet are still above the ghost's middle landed ON it.
; The `col_map` feature is a different thing entirely (a tile-flag lookup into
; a world blob) and does not serve an actor-against-actor test, so the four
; compares live here, in the game — the same call shmup makes.
gh_contact:
    .a16
    .i16
    lda z:US_PX
    cmp z:US_AX
    bcs @dx
    lda z:US_AX
    sec
    sbc z:US_PX
    bra @have_dx
@dx:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc z:US_AX
@have_dx:
    .a16
    .i16
    cmp #PLF_GHOST_W
    bcs @none
    lda z:US_PIXY
    cmp z:US_AY
    bcs @dy
    lda z:US_AY
    sec
    sbc z:US_PIXY
    bra @have_dy
@dy:
    .a16
    .i16
    lda z:US_PIXY
    sec
    sbc z:US_AY
@have_dy:
    .a16
    .i16
    cmp #PLF_BOX
    bcs @none
    ; ---- overlapping. Falling, from above the ghost's middle = a stomp ----
    lda z:US_VY
    bmi @hurt
    beq @hurt
    lda z:US_PIXY
    clc
    adc #(PLF_BOX / 2)
    cmp z:US_AY
    bcs @hurt
    lda #1
    rts
@hurt:
    .a16
    .i16
    lda #2
    rts
@none:
    .a16
    .i16
    lda #0
    rts

; --- stomp_bounce: the hop a defeated ghost gives back ----------------------
; In/out: A16/I16, DB=0. Clobbers A.
stomp_bounce:
    .a16
    .i16
    lda z:US_VCUT               ; half a jump — enough to read as a bounce
    sta z:US_VY
    lda #0
    sta z:US_GROUNDED
    jmp plf_blip

; =============================================================================
; LIVES, AND THE TWO WAYS A ROUND ENDS
; =============================================================================
; --- life_lost: one life, and the last one ends the round -------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; THE SAVE POINT IS HERE, and only on a loss with coins in hand. A win
; completes the loop (there is nothing left to resume) and a zero-coin death
; continues identically to a new game, so neither writes the battery. The one
; moment a player loses progress worth keeping is dying with coins collected.
life_lost:
    .a16
    .i16
    jsr plf_blip
    lda z:US_LIVES
    beq @over                   ; already at zero: do not wrap
    dec a
    sta z:US_LIVES
    lda z:US_DIRTY
    ora #1                      ; the lives digit wants reprinting
    sta z:US_DIRTY
    lda z:US_LIVES
    beq @over
    ; ---- survived: back to spawn, with i-frames --------------------------
    lda #PLF_SPAWN_X
    sta z:US_PX
    jsr plr_spawn_y
    lda #PLF_RESPAWN_I
    sta z:US_HURT
    rts
@over:
    .a16
    .i16
    ; ---- bank the run's coins, if there are any --------------------------
    lda z:US_COINS
    sta f:US_BANK_LONG          ; the ending screen reads this too
    beq @go
    lda #0
    sta z:SV_SLOT               ; slot 0
    lda #PLF_SAVE_LEN
    sta z:SV_LEN
    lda #PLF_SAVE_VER
    sta z:SV_VER
    lda #US_BANK
    sta z:SV_PTR
    sep #$20
    .a8
    lda #US_BANK_BANK
    sta z:SV_PTR+2
    rep #$20
    .a16
    jsr sv_save
@go:
    .a16
    .i16
    lda #SCENE_OVER
    jmp round_ends

; --- round_ends: freeze the world and ask for the ending scene --------------
; In: A16/I16, DB=0. A = the scene id. Clobbers A.
; The transition is REQUESTED, not taken: scene_mgr runs the switch at the
; frame boundary under forced blank, and the tick's `gover` gate holds the
; world still until it does.
round_ends:
    .a16
    .i16
    pha
    lda z:US_COINS
    sta f:US_BANK_LONG          ; the ending screen's coin count
    lda #1
    sta z:US_GOVER
    pla
    sep #$20
    .a8
    jsr sm_request
    rep #$20
    .a16
    rts

; =============================================================================
; THE SCREEN
; =============================================================================
; --- do_hud: at most ONE digit a frame, through bg_text's queue -------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; A running scene reaches VRAM only through that one-cell queue, so `dirty` is
; a two-bit REQUEST rather than a flag, and each frame services the lower of
; the bits that are set. Both counters are single digits by construction
; (lives 0..3, coins 0..6), which is what makes one cell enough. Reprinting
; the whole label every time would be a string per frame through a queue that
; moves one cell.
do_hud:
    .a16
    .i16
    lda z:US_DIRTY
    and #1
    beq @coins
    lda z:US_DIRTY
    dec a                       ; bit 0 was set, so dec clears exactly it
    sta z:US_DIRTY
    lda z:US_LIVES
    ldx #HUD_LIVES_CELL
    bra @digit
@coins:
    .a16
    .i16
    lda z:US_DIRTY
    and #2
    beq @done
    lda z:US_DIRTY
    sec
    sbc #2
    sta z:US_DIRTY
    lda z:US_COINS
    ldx #HUD_COINS_CELL
@digit:
    .a16
    .i16
    clc
    adc #('0' - ' ')            ; glyph index (space is tile 0)
    ora #PLAY_TXT_ATTR
    jsr text_queue_cell
@done:
    .a16
    .i16
    rts

; --- do_msg: the pause banner, one cell a frame -----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; It runs ABOVE the pause gate, so the banner announcing the freeze can finish
; drawing while the world is frozen — which is the whole point of it.
do_msg:
    .a16
    .i16
    lda z:US_MSG
    beq @done
    ; bg_text's queue holds ONE run and do_hud may have taken it this frame.
    ; The banner simply waits — it is eight frames of wipe-in either way.
    sep #$20
    .a8
    lda z:TXT_Q_DIRTY
    rep #$20
    .a16
    and #$00FF
    bne @done
    ; ---- the character: block (US_MSG - 1) at offset US_MSGPOS -----------
    lda z:US_MSG
    dec a
    .repeat 3
        asl                     ; ...times PLF_MSG_LEN
    .endrepeat
    clc
    adc z:US_MSGPOS
    tax
    sep #$20
    .a8
    lda f:s_msg, x
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #' '                    ; glyph index (space -> tile 0)
    ora #PLAY_TXT_ATTR
    ; ---- ...and the cell it goes in --------------------------------------
    pha                         ; the tile word, while X is built
    lda z:US_MSGPOS
    clc
    adc #PLF_MSG_CELL
    tax
    pla
    jsr text_queue_cell
    lda z:US_MSGPOS
    inc a
    sta z:US_MSGPOS
    cmp #PLF_MSG_LEN
    bcc @done
    lda #0
    sta z:US_MSG                ; the block is complete
@done:
    .a16
    .i16
    rts

; --- do_camera: the viewport follows the hero, clamped to the world ---------
; In/out: A16/I16, DB=0. Clobbers A.
; The camera is committed to BG1HOFS — and the two sky bands derived from it —
; in the NMI hook, from this one shadow.
do_camera:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc #(PLF_SCREEN_W / 2)
    bpl @clamp_hi
    lda #0
@clamp_hi:
    .a16
    .i16
    cmp #(PLF_CAM_MAX + 1)
    bcc @store
    lda #PLF_CAM_MAX
@store:
    .a16
    .i16
    sta z:ES_PLF_CAM
    rts

; --- do_draw: the whole cast into the OAM shadow ----------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; Park FIRST, then place: a dead ghost or a blinking hero is simply not
; redrawn, so "invisible" needs no second mechanism.
do_draw:
    .a16
    .i16
    jsr obj_park                ; ...which also zeroes the hi-table byte, so
    jsr obj_hero                ;   obj_put's ORs start from a clean one
    lda z:US_E1ALIVE
    beq @two
    lda z:US_E1X
    sta z:US_AX
    lda #PLF_G1_Y
    sta z:US_AY
    lda #ES_O_GHOSTS
    sta z:US_TMP2
    jsr obj_ghost
@two:
    .a16
    .i16
    lda z:US_E2ALIVE
    beq @done
    lda z:US_E2X
    sta z:US_AX
    lda #PLF_G2_Y
    sta z:US_AY
    lda #(ES_O_GHOSTS + 1)
    sta z:US_TMP2
    jsr obj_ghost
@done:
    .a16
    .i16
    rts

; --- plf_blip: the rail's one sound effect ----------------------------------
; In/out: A16/I16, DB=0.
;
; ONE SFX FOR EVERY TICK — a jump, a coin, a stomp, a hit. `assets/audio/
; export/` is a SHARED, checked-in TAD export whose set is room_a_ambience /
; room_b_ambience / footstep, and regenerating it to add platformer-flavoured
; blips would move `room`'s ROM, whose md5 is pinned. Moving another game's
; pinned artifact to improve this one's audio is not a trade this rail gets to
; make on its own, so the audio-content question stays open for whoever
; regenerates the export deliberately.
;
; WIDTH-RISK: Tad_QueueSoundEffect is a CROSS-FILE callee (vendor/tad) and
; takes A8; the width linter is single-file and cannot see the contract, so the
; sep/rep pair around it is load-bearing and stays here rather than at the call
; sites.
plf_blip:
    .a16
    .i16
    sep #$20
    .a8
    lda #SFX::footstep
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
    rts

; --- the dusk wash's data, a SCENE-scoped claim ----------------------------
; rgb_gradient claims grad_tabs itself, so the blob lives here rather than in
; platformer_rom: ca65 resolves scopes backward, and ES_R_GRAD_TABS_* is a
; symbol of THIS scope. It packs after every global blob, which is the order
; main.asm's BANK2 block and this one produce between them (see
; build/pl/allocation_report.txt). The .asserts refuse any drift.
;
; IT IS NOT OPTIONAL AND ITS ABSENCE IS SILENT: with the claim unfilled the
; three channels stream the linker's fill byte into COLDATA, and a zero byte
; selects NO plane, so the wash simply does not happen and every VRAM, CGRAM
; and OAM assertion still passes. Diagnosed exactly that way -- the arena's
; grass rendered its declared colour with no ramp added, which is what an
; armed channel reading nothing looks like.
.segment "BANK2"
grad_tabs_bin:
    .incbin "plf_grad.bin"
.assert ^grad_tabs_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(grad_tabs_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"

.segment "RODATA"
s_lives:  .byte "LIVES", 0
s_coins:  .byte "COINS", 0
; The two banner blocks, back to back and indexed as one table: block 1 is
; the announcement, block 2 wipes it. Same length, same cells, so a block
; totally overwrites its predecessor -- no residue, no clear pass.
s_msg:    .byte "PAUSED  "
          .byte "        "
.assert (* - s_msg) = (2 * PLF_MSG_LEN), error, "the banner blocks are not PLF_MSG_LEN each"
.segment "CODE"
.endscope
