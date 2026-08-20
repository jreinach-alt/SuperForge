; =============================================================================
; scenes/arena.asm — the whole fight: reveal, hold, the LUNGE, the BEAM, loop
; =============================================================================
; ONE scope holding this scene's map, its two scene-scoped features, and the
; state machine, expressed against emitted symbols. The driver lives here
; rather than in a `role = "game_logic"` feature: this is a single-scene rail
; and there is no second consumer for any of it.
;
; THE MATRIX DISCIPLINE. Every animated state ends its update by applying ONE
; track entry into m7_affine's DP shadow (M7T_BIND + m7t_apply); the NMI hook
; commits the shadow's eight ports together during VBlank. So each rendered
; frame reads one consistent matrix. Writing M7A-D from the main thread
; instead is a latent tearing bug — the eight ports must be latched before
; scanline 0, and a mid-loop write cannot guarantee that; the shadow idiom is
; the fix m7_affine's feature.toml records.
;
; WHO ADVANCES THE TRACK CURSOR (the m7_track contract's question): this file,
; from its own state — every ramp index is a countdown timer's complement
; (idx = FRAMES + 1 - timer) and the ring index is the live heading byte. No
; cursor variable exists, so a cursor cannot disagree with the clock that
; drives it. FOUR ramps use the idiom here: reveal, lunge-approach,
; lunge-retreat and death-recede.

.scope arena

.include "engine_state_arena.inc"    ; GENERATED — this scene's map
.include "sau_floor.asm"             ; scene-scoped: the plane's upload
.include "sau_obj.asm"               ; scene-scoped: the cast + the pool

; --- the scene's base display ----------------------------------------------
; BGMODE 7 has exactly one BG; TM carries the plane AND the cast (one
; register, one owner — sau_floor's scene_writes carries the attribution).
TM_BG1 = 1
TM_OBJ = 1 << 4

; --- the pivot: the saucer's centre (map px), shown at screen centre -------
; Half the 1024-px map, as a shift (no_literals refuses the decimal form —
; 512 is also an address inside the OAM shadow claim, and nothing in the
; token distinguishes a world constant from a narrated address).
SAU_CX = 1 << 9
SAU_CY = 1 << 9

; --- the pool region's layout agrees with its claim ------------------------
.assert SAU_SHOT_Y + 2 * SAU_SHOT_N = ES_SAU_ACTORS_SIZE, error, "saucer.inc's pool offsets do not tile the sau_actors claim"

; =============================================================================
; enter — the plane, the cast, the pivot, the armed reveal
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 16 colours + M7SEL
    jsr obj_arm                     ; sheet + palette + OBSEL + pool + park

    ; ---- the pivot, seeded before the first NMI is armed ------------------
    ; m7a_set_center writes ES_M7AFF+8..+15 (M7X/M7Y + the screen origin);
    ; battle_init below writes +0..+7 through the reveal track's entry 0.
    ; Between them every byte of the shadow is written before the first commit
    ; reads it — rule 5's write-before-read contract, not defensive init.
    ldx #SAU_CX
    ldy #SAU_CY
    jsr ::m7a_set_center

    stz z:US_FRAME                  ; the blink/flicker clock (persistent, so
                                    ;   it is seeded HERE, not per battle)
    stz z:US_STAR_FAR               ; the two star-band scrolls, same reason:
    stz z:US_STAR_NEAR              ;   the sky must not snap home on the loop
    jsr battle_init                 ; full battle state + reveal[0] + ST_REVEAL

    ; ---- the scene's base display (sau_floor's scene_writes) --------------
    sep #$20
    .a8
    lda #7
    sta a:$2105                     ; BGMODE 7: the affine plane
    lda #(TM_BG1 | TM_OBJ)
    sta a:$212C                     ; TM: the plane AND the cast

    ; ---- lift the blank, through the fade (called in A8, deliberately —
    ; fade_start_in is .a8; from A16 the CPU eats the next opcode byte as the
    ; immediate's high half and the ROM renders black) --------------------------
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; =============================================================================
; exit — nothing to unwind (one scene; the only way out is power-off)
; =============================================================================
exit:
    .a16
    .i16
    rts

; =============================================================================
; battle_init — (re)arm the full battle: reveal-tiny saucer + fresh combat
; =============================================================================
; Called from enter and from the RESET state (the loop). The track binding
; replaces separate scale/angle seeds: entry 0 of the reveal track IS
; (angle 0, scale 5.0).
;
; There is NO rng state on this rail: with no orb rain, nothing here would read
; one — the beam's column is p_x, not a roll. Dead state stays dead.
;
; In/out: A16/I16, DB=0. Clobbers A, X.
; WIDTH-RISK: pure A16/I16; POOL_BIND/M7T_BIND require A16 and leave it;
; pool_init and m7t_apply are A16/I16 both sides with no sep/rep.
battle_init:
    .a16
    .i16
    stz z:US_B_HEADING              ; angle 0
    lda #SAU_BOSS_HP0
    sta z:US_B_HP
    stz z:US_B_PHASE
    stz z:US_B_VULN
    lda #SAU_PLAYER_X0
    sta z:US_P_X                    ; player Y is the constant SAU_PLAYER_Y
    sta z:US_BEAM_X                 ; a harmless column until a lunge locks one
    lda #SAU_PLAYER_HP0
    sta z:US_P_HP
    stz z:US_P_IFRAME
    stz z:US_FIRE_TIMER
    stz z:US_B_RESULT
    stz z:US_PAUSED                 ; each battle starts unpaused (RAM is
                                    ;   random at boot — rule 5)
    ; ---- the lunge and the beam start idle; FIGHT arms them ---------------
    stz z:US_LUNGE_STATE            ; SAU_LG_FAR
    stz z:US_LUNGE_TIMER
    stz z:US_BEAM_STATE             ; SAU_BM_OFF
    stz z:US_BEAM_TIMER
    ; ---- the shot pool, cleared through the mechanism ---------------------
    POOL_BIND ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE
    ldx #SAU_SHOT_N
    jsr ::pool_init
    ; ---- the pre-reveal pose: tiny and unrotated, before the fade lifts ---
    M7T_BIND ::sau_reveal_bin
    lda #0
    jsr ::m7t_apply
    ; ---- enter REVEAL with its ramp timer ---------------------------------
    lda #SAU_ST_REVEAL
    sta z:US_B_STATE
    lda #SAU_REVEAL_FRAMES
    sta z:US_B_TIMER
    rts

; =============================================================================
; tick — one game frame: the pause gate, the state machine, then the draw
; =============================================================================
; START toggles a full freeze on its RISING edge (input's ES_INP_PRESS; Select
; is unmapped). While paused the state machine is skipped, so nothing moves
; and nothing can hurt the player — but the draw, the matrix commit and MAIN's
; audio pump keep running, so the held frame shows and the music plays.
;
; THE BRIGHTNESS RAMP IS DELIBERATELY OUTSIDE THE GATE: `fade_tick` is MAIN's,
; one scope out, and reaching across to gate it on a scene variable would be
; worse than the nuance is worth — a fade is only ever armed on a transition,
; where the player is not holding a controller anyway.
;
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
tick:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #SAU_JOY_START
    beq @no_toggle
    lda z:US_PAUSED
    eor #1
    sta z:US_PAUSED
@no_toggle:
    .a16
    lda z:US_PAUSED
    bne @frozen
    jsr stars_update
    jsr state_update
@frozen:
    .a16
    jsr draw_frame
    lda z:US_FRAME
    inc a
    sta z:US_FRAME                  ; the blink/flicker clock (parity only)
    rts

; =============================================================================
; stars_update — advance the two star bands' scroll, at the fight's tempo
; =============================================================================
; INSIDE THE PAUSE GATE (tick calls it there): a freeze means nothing moves,
; and a sky still sliding behind a frozen fight would say the opposite.
;
; The rate is read off the ROM's own state, never off a frame counter: CALM
; everywhere but FIGHT, and inside FIGHT the phase — which is the HP third —
; adds a step. So the sky is slowest while the saucer is arriving and while it
; is dying, and fastest in the last third of the fight. The far band takes
; half of whatever the near band gets, which is what separates the two depths
; in motion.
;
; Both accumulators are 8.8 and wrap on their own sixteen bits (256.0 px),
; which is the OAM y byte's own modulus — so there is no wrap test here and
; none in the draw.
;
; In/out: A16/I16, DB=0. Clobbers A. No sep/rep in this body.
stars_update:
    .a16
    .i16
    lda z:US_B_STATE
    cmp #SAU_ST_FIGHT
    bne @calm
    lda z:US_B_PHASE                ; 0..2, the HP thirds
    ; `::` because ca65 2.18 will not take a .repeat count that is an
    ; unqualified symbol from OUTSIDE the enclosing .scope — it reports
    ; "Constant expression expected", which reads as a missing definition
    ; rather than as a scope lookup. The same shape appears twice in
    ; draw_stars below.
    .repeat ::SAU_STAR_PH_SH
        asl                         ; * SAU_STAR_PH, the per-phase step
    .endrepeat
    clc
    adc #SAU_STAR_FIGHT
    bra @have
@calm:
    .a16
    lda #SAU_STAR_CALM
@have:
    .a16
    sta z:US_SCR                    ; this frame's NEAR rate, 8.8 px
    clc
    adc z:US_STAR_NEAR
    sta z:US_STAR_NEAR
    lda z:US_SCR
    lsr                             ; the far band drifts at HALF the rate
    clc
    adc z:US_STAR_FAR
    sta z:US_STAR_FAR
    rts

; =============================================================================
; state_update — per-frame state machine (the eight states)
; =============================================================================
; WIDTH-RISK: A16/I16 entry; pure A16/I16 throughout; the jsr'd helpers
; restore A16/I16. Exits A16/I16.
state_update:
    .a16
    .i16
    lda z:US_B_STATE
    asl                             ; *2 for the word jump table
    tax
    jmp (su_jump, x)

su_jump:
    .addr su_intro                  ; SAU_ST_INTRO  (0)
    .addr su_reveal                 ; SAU_ST_REVEAL (1)
    .addr su_hold                   ; SAU_ST_HOLD   (2)
    .addr su_fight                  ; SAU_ST_FIGHT  (3)
    .addr su_death                  ; SAU_ST_DEATH  (4)
    .addr su_lose                   ; SAU_ST_LOSE   (5)
    .addr su_result                 ; SAU_ST_RESULT (6)
    .addr su_reset                  ; SAU_ST_RESET  (7)

; --- INTRO: vestigial (battle_init enters REVEAL directly) ----------------
su_intro:
    .a16
    lda #SAU_ST_REVEAL
    sta z:US_B_STATE
    rts

; --- REVEAL: play the grow-in track; the saucer GROWS as the scale falls ---
; idx = FRAMES + 1 - timer walks entries 1..60 as the timer counts 60..1;
; entry 60 == ring[60] (the generator's seam assert), so HOLD's first ring
; apply at heading 61 continues the motion with no pop.
su_reveal:
    .a16
    lda #SAU_REVEAL_FRAMES + 1
    sec
    sbc z:US_B_TIMER
    sta z:US_SCR                    ; idx, 1..60
    M7T_BIND ::sau_reveal_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_SCR
    sta z:US_B_HEADING              ; the baked angle IS f — keep the live
                                    ;   heading in lockstep for the handover
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #SAU_ST_HOLD
    sta z:US_B_STATE
    lda #SAU_HOLD_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- HOLD: full size, gentle spin on the ring, then the fight --------------
; The fight's entry SNAPS the heading to 0: rotation is OFF in the fight,
; because scaling IS the motion. It is choreography, not a truncation
; artifact, and the art carries it — the hull's lamp ring is twelve-fold, so
; the 105-heading snap lands within 2.4 degrees of a lamp-to-lamp alignment.
su_hold:
    .a16
    lda z:US_B_HEADING
    inc a
    and #255
    sta z:US_B_HEADING
    M7T_BIND ::sau_ring_bin
    lda z:US_B_HEADING
    jsr ::m7t_apply
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #SAU_ST_FIGHT
    sta z:US_B_STATE
    lda #1
    sta z:US_B_VULN                 ; the saucer becomes vulnerable
    stz z:US_B_HEADING              ; rotation OFF for the whole fight
    stz z:US_LUNGE_STATE            ; SAU_LG_FAR
    stz z:US_BEAM_STATE             ; SAU_BM_OFF
    lda #SAU_FAR_P0
    sta z:US_LUNGE_TIMER            ; the first dwell before the first dive
@done:
    .a16
    rts

; --- FIGHT: handed to the combat routine (which applies the matrix) --------
su_fight:
    .a16
    jsr fight_update
    rts

; --- DEATH: play the recede track (spin + shrink away); then RESULT(win) ---
su_death:
    .a16
    lda #SAU_REVEAL_FRAMES + 1
    sec
    sbc z:US_B_TIMER
    sta z:US_SCR                    ; idx, 1..60
    M7T_BIND ::sau_death_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #1
    sta z:US_B_RESULT               ; WIN
    lda #SAU_ST_RESULT
    sta z:US_B_STATE
    lda #SAU_RESULT_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- LOSE: hold the last fight pose, then the DEFEAT result ---------------
; The matrix freezes at the pose the fight left: this state applies no track
; entry, so the shadow simply persists. The DEFEAT word is already on screen —
; draw_overlays paints it for LOSE as well as for RESULT(lose).
su_lose:
    .a16
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #2
    sta z:US_B_RESULT               ; LOSE
    lda #SAU_ST_RESULT
    sta z:US_B_STATE
    lda #SAU_RESULT_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- RESULT: hold the card over the LIVE arena, then fade out into RESET --
; The INVARIANT is that the arena stays visible behind the win/lose word — the
; card must not read against black. Dimming to a mid brightness would express
; that too, but `fade` ramps 0<->15 only and a configurable target would be a
; change to a SHARED engine feature. Holding at full brightness satisfies the
; invariant directly, and that is what the test asserts.
su_result:
    .a16
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    sep #$20
    .a8
    jsr ::fade_start_out            ; (the A8 contract, as above)
    rep #$20
    .a16
    lda #SAU_ST_RESET
    sta z:US_B_STATE
    lda #SAU_FADE_FRAMES            ; > the fade's 15 steps, so RESET's swap
    sta z:US_B_TIMER                ;   runs on a black screen
@done:
    .a16
    rts

; --- RESET: wait out the fade, re-init masked, fade back in (the loop) -----
; The re-init touches no VRAM (map and palette are static), so the fade is
; choreography rather than a masking requirement;
; the swap still runs at brightness 0 because SAU_FADE_FRAMES > 15.
su_reset:
    .a16
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    jsr battle_init                 ; -> ST_REVEAL, the saucer tiny again
    sep #$20
    .a8
    jsr ::fade_start_in
    rep #$20
    .a16
@done:
    .a16
    rts

; =============================================================================
; fight_update — strafe, fire, shots, the LUNGE, the BEAM, phase, win/lose
; =============================================================================
; Combat, through the helpers below. Order matters in one place:
; `saucer_lunge` applies this frame's matrix, so the win check that follows it
; can hand a KNOWN pose to break_off.
; WIDTH-RISK: A16/I16 entry AND exit, with NO A8 window in this body at all —
; the two helpers that narrow (player_fire's and beam_update's SFX queue calls)
; both restore before returning, and the LOSE arm arms no fade, so there is
; nothing here for a sep/rep to get wrong.
fight_update:
    .a16
    .i16
    jsr player_move
    jsr player_fire
    jsr shots_update
    jsr saucer_phase
    jsr saucer_lunge                ; drives the scale AND applies the matrix
    jsr beam_update
    ; ---- iframe countdown -------------------------------------------------
    lda z:US_P_IFRAME
    beq @no_iframe
    dec a
    sta z:US_P_IFRAME
@no_iframe:
    .a16
    ; ---- win / lose checks ------------------------------------------------
    lda z:US_B_HP
    bne @check_lose
    stz z:US_B_VULN                 ; the saucer is dead: no more damage,
    stz z:US_BEAM_STATE             ;   and the beam dies with it
    jsr break_off                   ; climb home, then hand to DEATH
    rts
@check_lose:
    .a16
    lda z:US_P_HP
    bne @alive
    lda #SAU_ST_LOSE
    sta z:US_B_STATE
    lda #SAU_FADE_FRAMES
    sta z:US_B_TIMER
@alive:
    .a16
    rts

; --- break_off: steer the lunge home, then start the recede ----------------
; A recede that added its step to the LIVE scale would start wherever the
; lunge happened to be and end anywhere in a wide band. A BAKED track is
; absolute by construction, and the 2-D (entry x frame) table that would
; express the other thing is explicitly out of scope — so rather than pop from
; a mid-dive pose to the track's rest start, the kill re-uses the RETREAT track
; the rail already owns: the saucer climbs back to rest and DEATH begins on the
; exact seam (death[0] == retr[45] == ring[0], all four asserted in the
; generator).
;
; THE MIRROR CURSOR. Aborting mid-approach, the retreat resumes at the pose
; just drawn: approach index a maps to retreat index 44 - a, i.e.
; timer_retreat = SAU_LUNGE_FRAMES + 1 - timer_approach. The two ramps'
; truncations land on different frames, so the mapping is not exact — measured
; over every T, it is off by exactly ONE unit of 1216 (retr[T] = 787 + 10T
; against appr[44-T] = 786 + 10T) versus a normal frame step of ten. That
; residue IS the dive's terminal clamp step, and NEAR_SCALE was chosen to keep
; it at one: the generator's header carries the derivation, and an exact
; multiple of the step would zero it at the price of making the two ramps each
; other's reverse. Strictly smaller than one frame's own motion, i.e. invisible
; by construction — the boss rail's capture argument, transposed from the
; heading axis to the scale axis. Bounded at 45 frames.
;
; In/out: A16/I16, DB=0. Clobbers A.
break_off:
    .a16
    .i16
    lda z:US_LUNGE_STATE
    beq @home                       ; SAU_LG_FAR: already at rest
    cmp #SAU_LG_RETREAT
    beq @done                       ; already climbing — let it finish
    cmp #SAU_LG_NEAR
    beq @from_near
    ; ---- APPROACH: mirror the cursor -------------------------------------
    lda #SAU_LUNGE_FRAMES + 1
    sec
    sbc z:US_LUNGE_TIMER
    sta z:US_LUNGE_TIMER
    bra @retreat
@from_near:
    .a16
    lda #SAU_LUNGE_FRAMES           ; the apex IS retr[0]; start at retr[1]
    sta z:US_LUNGE_TIMER
@retreat:
    .a16
    lda #SAU_LG_RETREAT
    sta z:US_LUNGE_STATE
@done:
    .a16
    rts
@home:
    .a16
    lda #SAU_ST_DEATH
    sta z:US_B_STATE
    lda #SAU_REVEAL_FRAMES
    sta z:US_B_TIMER
    stz z:US_B_HEADING              ; the death track bakes its own +3/frame
    M7T_BIND ::sau_death_bin
    lda #0
    jsr ::m7t_apply                 ; death[0] == ring[0], the asserted seam
    rts

; --- player_move: LEFT/RIGHT strafe, clamped on screen ---------------------
player_move:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #SAU_JOY_LEFT
    beq @no_left
    lda z:US_P_X
    sec
    sbc #SAU_PLAYER_SPEED
    cmp #SAU_PLAYER_XMIN
    bcs @store_left
    lda #SAU_PLAYER_XMIN
@store_left:
    .a16
    sta z:US_P_X
@no_left:
    .a16
    lda z:ES_INP_CUR
    bit #SAU_JOY_RIGHT
    beq @no_right
    lda z:US_P_X
    clc
    adc #SAU_PLAYER_SPEED
    cmp #SAU_PLAYER_XMAX
    bcc @store_right
    lda #SAU_PLAYER_XMAX
@store_right:
    .a16
    sta z:US_P_X
@no_right:
    .a16
    rts

; --- player_fire: a shot while A is HELD, cadenced -------------------------
; The battle's outcome is player-driven: fire to damage the saucer; hold off
; and it never dies. The cadence makes a held A a
; stream that cannot exhaust the 4-slot pool in one burst.
; WIDTH-RISK: Tad_QueueSoundEffect is a CROSS-FILE callee (vendor/tad) and
; takes A8; the width linter is single-file and cannot see the contract, so
; the sep/rep pair around it is load-bearing.
player_fire:
    .a16
    .i16
    lda z:US_FIRE_TIMER
    beq @ready
    dec a
    sta z:US_FIRE_TIMER
    rts
@ready:
    .a16
    lda z:ES_INP_CUR
    bit #SAU_JOY_A
    beq @no_fire
    POOL_BIND ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE
    ldx #SAU_SHOT_N
    jsr ::pool_spawn
    bmi @no_fire                    ; POOL_FULL -> skip this shot
    ; X = the claimed slot's byte offset (pool_spawn's contract)
    lda z:US_P_X
    clc
    adc #4                          ; centre the 8x8 bolt over the 16x16 hull
    sta f:ES_SAU_ACTORS_LONG + SAU_SHOT_X, x
    lda #SAU_PLAYER_Y - 8           ; spawn just above the hull
    sta f:ES_SAU_ACTORS_LONG + SAU_SHOT_Y, x
    lda #SAU_FIRE_GAP
    sta z:US_FIRE_TIMER
    sep #$20
    .a8
    lda #SFX::footstep              ; the gun report, one per fired shot
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
@no_fire:
    .a16
    rts

; --- shots_update: advance UP, cull at the top, test vs the saucer box -----
; X holds the pool byte offset across the pass; the long,x loads do not move
; it, and pool_kill preserves it (pool.asm's contract).
shots_update:
    .a16
    .i16
    stz z:US_UI
@loop:
    .a16
    ldx z:US_UI
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE, x
    beq @next
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_Y, x
    sec
    sbc #SAU_SHOT_SPEED
    sta f:ES_SAU_ACTORS_LONG + SAU_SHOT_Y, x
    cmp #SAU_SHOT_CULL_Y
    bcc @kill                       ; reached the top band
    ; ---- vs the saucer hitbox, only while vulnerable ----------------------
    ; Strict half-open AABB, one unsigned compare per axis (sprite_game's
    ; catch_dot derivation):
    ; overlap iff (a - b + wa - 1) unsigned< (wa + wb - 1).
    lda z:US_B_VULN
    beq @next
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_X, x
    sec
    sbc #SAU_BOSS_HIT_X
    clc
    adc #SAU_SHOT_W - 1
    cmp #SAU_SHOT_W + SAU_BOSS_HIT_W - 1
    bcs @next
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_Y, x
    sec
    sbc #SAU_BOSS_HIT_Y
    clc
    adc #SAU_SHOT_H - 1
    cmp #SAU_SHOT_H + SAU_BOSS_HIT_H - 1
    bcs @next
    ; ---- hit: drop saucer HP (saturating) and free the shot ---------------
    lda z:US_B_HP
    cmp #SAU_SHOT_DMG
    bcs @dmg
    lda #SAU_SHOT_DMG               ; clamp so it cannot underflow
@dmg:
    .a16
    sec
    sbc #SAU_SHOT_DMG
    sta z:US_B_HP
@kill:
    .a16
    POOL_BIND ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE
    ldx z:US_UI
    jsr ::pool_kill                 ; X preserved
@next:
    .a16
    lda z:US_UI
    clc
    adc #2
    sta z:US_UI
    cmp #2 * SAU_SHOT_N
    bcc @loop
    rts

; =============================================================================
; saucer_lunge — THE HEADLINE: four sub-states, four track applies
; =============================================================================
;   FAR      hold the rest pose, dwell, then APPROACH
;   APPROACH play sau_appr 1..44 (the saucer GROWS); with TELE_F - 1 frames
;            of ramp left, LOCK the beam column to the player's body centre
;            and start the telegraph, so the charge runs DURING the dive
;   NEAR     hold the apex (sau_appr's last entry) while beam_update runs
;   RETREAT  play sau_retr 1..44 back to rest, then FAR with a phase dwell
; WIDTH-RISK: A16/I16 entry/exit (no toggles); m7t_apply is A16/I16 both sides.
saucer_lunge:
    .a16
    .i16
    lda z:US_LUNGE_STATE
    asl
    tax
    jmp (lunge_jump, x)

lunge_jump:
    .addr lg_far                    ; SAU_LG_FAR      (0)
    .addr lg_approach               ; SAU_LG_APPROACH (1)
    .addr lg_near                   ; SAU_LG_NEAR     (2)
    .addr lg_retreat                ; SAU_LG_RETREAT  (3)

; --- FAR: the rest pose is the approach track's entry 0 --------------------
lg_far:
    .a16
    M7T_BIND ::sau_appr_bin
    lda #0
    jsr ::m7t_apply
    lda z:US_LUNGE_TIMER
    dec a
    sta z:US_LUNGE_TIMER
    bne @done
    lda #SAU_LG_APPROACH
    sta z:US_LUNGE_STATE
    lda #SAU_LUNGE_FRAMES
    sta z:US_LUNGE_TIMER
@done:
    .a16
    rts

; --- APPROACH: the dive. Mid-dive, lock the column and telegraph. --------
; THE TELEGRAPH RUNS DURING THE DIVE, not after it. Armed with
; SAU_BEAM_TELE_F - 1 frames of ramp left, its countdown and the ramp's reach
; zero on the SAME frame, so the beam ignites exactly as the saucer reaches its
; apex — the charge is the dive and the shot is the arrival. It also means the
; sight line is drawn against a CHANGING scale (appr[21] -> appr[44], a 1.29x
; span), which is the whole point of anchoring it to the emitter rather than
; to a fixed row: a beam that only ever appeared at one pose could be nailed to
; that pose and nobody would see the difference.
lg_approach:
    .a16
    lda #SAU_LUNGE_FRAMES + 1
    sec
    sbc z:US_LUNGE_TIMER
    sta z:US_SCR                    ; idx, 1..44
    M7T_BIND ::sau_appr_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_LUNGE_TIMER
    dec a
    sta z:US_LUNGE_TIMER
    beq @apex
    cmp #SAU_BEAM_TELE_F - 1
    bne @done
    ; ---- LOCK the beam column to the player's body centre ----------------
    ; The player must then strafe out of this column during the telegraph.
    lda z:US_P_X
    clc
    adc #4                          ; centre the 8 px column on the 16 px hull
    sta z:US_BEAM_X
    lda #SAU_BM_TELE
    sta z:US_BEAM_STATE
    lda #SAU_BEAM_TELE_F
    sta z:US_BEAM_TIMER
    rts
@apex:
    .a16
    lda #SAU_LG_NEAR
    sta z:US_LUNGE_STATE
@done:
    .a16
    rts

; --- NEAR: hold the apex pose until the beam finishes ---------------------
lg_near:
    .a16
    M7T_BIND ::sau_appr_bin
    lda #SAU_LUNGE_FRAMES           ; the ramp's LAST entry = the apex
    jsr ::m7t_apply
    lda z:US_BEAM_STATE
    bne @done                       ; still telegraphing / firing -> hold
    lda #SAU_LG_RETREAT
    sta z:US_LUNGE_STATE
    lda #SAU_LUNGE_FRAMES
    sta z:US_LUNGE_TIMER
@done:
    .a16
    rts

; --- RETREAT: the climb back to rest, then FAR with a phase-scaled dwell ---
lg_retreat:
    .a16
    lda #SAU_LUNGE_FRAMES + 1
    sec
    sbc z:US_LUNGE_TIMER
    sta z:US_SCR                    ; idx, 1..44 (0..44 after a break_off)
    M7T_BIND ::sau_retr_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_LUNGE_TIMER
    dec a
    sta z:US_LUNGE_TIMER
    bne @done
    stz z:US_LUNGE_STATE            ; SAU_LG_FAR
    ; phase 0 = the full dwell, 1 = -12, 2 = -24 (faster lunges as HP drops)
    lda z:US_B_PHASE
    cmp #2
    bcs @p2
    cmp #1
    bcs @p1
    lda #SAU_FAR_P0
    bra @set
@p1:
    .a16
    lda #SAU_FAR_P1
    bra @set
@p2:
    .a16
    lda #SAU_FAR_P2
@set:
    .a16
    sta z:US_LUNGE_TIMER
@done:
    .a16
    rts

; =============================================================================
; beam_update — the telegraph/active timing and the beam-vs-player hit
; =============================================================================
;   TELEGRAPH  dim (every other segment), no damage; the dodge window
;   FIRE       solid and damaging; a player inside the column loses a heart
;              and gains iframes
; The column's hitbox is a narrow vertical strip at beam_x spanning the player
; band, so the player dodges by strafing out of it during the telegraph.
; WIDTH-RISK: A16/I16 entry/exit; the two A8 windows are the SFX queue calls
; (Tad_QueueSoundEffect is a cross-file A8 callee) and both restore A16.
beam_update:
    .a16
    .i16
    lda z:US_BEAM_STATE
    beq @done                       ; SAU_BM_OFF -> nothing
    cmp #SAU_BM_TELE
    beq @tele
    ; ---- FIRE: count down; damage while the player is in the column ------
    lda z:US_BEAM_TIMER
    dec a
    sta z:US_BEAM_TIMER
    bne @hit
    stz z:US_BEAM_STATE             ; the active window closed
    sep #$20
    .a8
    lda #SFX::room_a_ambience       ; the arena's echo settles back
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
    rts
@hit:
    .a16
    ; the column vs the player box, half-open AABB on X (the Y spans agree by
    ; construction: the column starts at row 56 and runs 160 px, the player
    ; band is rows 184..199)
    lda z:US_BEAM_X
    sec
    sbc z:US_P_X
    clc
    adc #SAU_BEAM_W - 1
    cmp #SAU_BEAM_W + SAU_PLAYER_W - 1
    bcs @done
    lda z:US_P_IFRAME
    bne @done                       ; still invulnerable from the last hit
    lda z:US_P_HP
    beq @done                       ; already 0
    dec a
    sta z:US_P_HP
    lda #SAU_IFRAME_LEN
    sta z:US_P_IFRAME
    rts
@tele:
    .a16
    ; ---- TELEGRAPH: count down (no damage); then go ACTIVE ---------------
    lda z:US_BEAM_TIMER
    dec a
    sta z:US_BEAM_TIMER
    bne @done
    lda #SAU_BM_FIRE
    sta z:US_BEAM_STATE
    lda #SAU_BEAM_FIRE_F
    sta z:US_BEAM_TIMER
    sep #$20
    .a8
    lda #SFX::room_b_ambience       ; the beam ignites: the arena rings
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
@done:
    .a16
    rts

; --- saucer_phase: HP thirds -> phase (which shortens the FAR dwell) ------
; Thresholds are the 240/3 bands. No rotation term: the fight's
; heading is 0 throughout, so the boss rail's per-phase spin has no analogue
; here — the phase paces the LUNGE instead, which is this rail's motion.
saucer_phase:
    .a16
    .i16
    lda z:US_B_HP
    cmp #SAU_PH1_HP
    bcs @p0
    cmp #SAU_PH2_HP
    bcs @p1
    lda #2                          ; phase 2: hp <= 80
    sta z:US_B_PHASE
    rts
@p1:
    .a16
    lda #1
    sta z:US_B_PHASE
    rts
@p0:
    .a16
    stz z:US_B_PHASE
    rts

; =============================================================================
; draw_frame — the stable slot map, every slot every frame
; =============================================================================
; 0 gunship · 1-16 the beam lance · 17-24 HP HUD · 25-28 shots · 29 thruster ·
; 30-53 card cells · 56-79 the star field. Dead or unused slots park at
; SAU_PARK_Y so slot identity is stable; the twenty hi-table bytes are cleared
; first and rebuilt whole by the sau_put calls.
;
; The stars go FIRST because that is what they are — the layer behind
; everything, drawn under the plane. Nothing in the order is load-bearing
; (each routine owns disjoint slots and every scratch word is written before
; it is read inside one pass); it is written this way to be read this way.
draw_frame:
    .a16
    .i16
    jsr sau_hi_clear
    jsr draw_stars
    jsr draw_player
    jsr draw_beam
    jsr draw_hp_hud
    jsr draw_shots
    jsr draw_exhaust
    jsr draw_overlays
    rts

; --- draw_player: slot 0, visible HOLD..LOSE ------------------------------
; Hidden pre-fight (states < HOLD) and post-fight (RESULT/RESET) so the
; saucer read is clean. The iframe hit-flash alternates frames so it reads as
; a blink, not a solid swap.
draw_player:
    .a16
    .i16
    lda z:US_B_STATE
    cmp #SAU_ST_HOLD
    bcc @park
    cmp #SAU_ST_RESULT
    bcs @park
    lda #SAU_T_PLAYER0
    sta z:ES_SAU_DRAW + SAU_D_TILE
    lda z:US_P_IFRAME
    beq @tile_picked
    lda z:US_FRAME
    and #SAU_FLASH_MASK
    beq @tile_picked
    lda #SAU_T_PLAYER1
    sta z:ES_SAU_DRAW + SAU_D_TILE
@tile_picked:
    .a16
    lda z:US_P_X
    sta z:ES_SAU_DRAW + SAU_D_X
    lda #SAU_PLAYER_Y
    sta z:ES_SAU_DRAW + SAU_D_Y
    lda #SAU_LARGE
    sta z:ES_SAU_DRAW + SAU_D_SIZE
    ldx #ES_O_PLAYER * 4
    lda z:ES_SAU_DRAW + SAU_D_TILE
    ora #(SAU_PRIO << 8)
    jsr sau_put
    rts
@park:
    .a16
    ldx #ES_O_PLAYER * 4
    jsr sau_park_slot
    rts

; --- draw_beam: slots 1-16, the LANCE from the emitter to the column ------
; OFF parks all sixteen. Otherwise the sixteen cells WALK the straight line
; from the saucer's ventral emitter to the latched column.
;
; WHY THE ORIGIN IS A CONSTANT AND STILL TRACKS THE SAUCER. The emitter is the
; plane's PIVOT (the generator paints its white-hot disc at r <= 2.3 tiles of
; the map centre) and `m7a_set_center` shows the pivot at the screen centre, so
; the matrix changes how BIG the emitter renders and never WHERE. Starting the
; walk at (SAU_BEAM_X0, SAU_BEAM_Y0) therefore lands it inside the emitter at
; every pose the lunge reaches — no divide by the live scale, and nothing to
; drift. The debut's column started at row 56 and stood at the player's x, so
; it touched the saucer only by coincidence and read as a bar someone had left
; on the screen.
;
; TELEGRAPH draws the EVEN cells with the thin sight tile: a dotted line
; already aimed at where the beam will land, which is what makes the dodge
; window legible. FIRE draws all sixteen with the full-width body and puts the
; burst tile on the FIRST and LAST, so the lance visibly leaves the emitter and
; lands on the ship.
;
; THE WALK. US_HUD_X is the X accumulator in 8.8 and US_SCR its step
; (delta * SAU_BEAM_MUL — four shifts and an add, no divide); Y is a plain
; integer cursor in US_HUD_THR stepping SAU_BEAM_PITCH, because that axis'
; span is a compile-time constant. US_DI is the cell index. All four are
; per-frame scratch, written before read inside this one pass.
; WIDTH-RISK: A16/I16 entry AND exit, and NO sep/rep in this body at all —
; sau_put, sau_park_slot and beam_slot_x are each A16/I16 both sides.
draw_beam:
    .a16
    .i16
    stz z:US_DI
    lda #SAU_BEAM_Y0
    sta z:US_HUD_THR                ; the Y cursor, whole pixels
    lda #SAU_BEAM_X0
    xba                             ; << 8 into the 8.8 accumulator's high half
    sta z:US_HUD_X
    ; ---- the X step: (beam_x - X0) * 17 == (d << 4) + d, signed ----------
    lda z:US_BEAM_X
    sec
    sbc #SAU_BEAM_X0
    sta z:US_SCR
    asl
    asl
    asl
    asl
    clc
    adc z:US_SCR
    sta z:US_SCR
@loop:
    .a16
    .i16
    lda z:US_BEAM_STATE
    beq @park
    cmp #SAU_BM_FIRE
    beq @fire
    lda z:US_DI
    and #1
    bne @park                       ; the odd cell is the sight line's gap
    lda #SAU_T_BEAM_TELE | (SAU_PRIO << 8)
    bra @draw
@fire:
    .a16
    .i16
    lda z:US_DI
    beq @burst                      ; the muzzle, on the emitter
    cmp #SAU_BEAM_SEGS - 1
    beq @burst                      ; ...and the impact, on the ship
    lda #SAU_T_BEAM | (SAU_PRIO << 8)
    bra @draw
@burst:
    .a16
    .i16
    lda #SAU_T_BEAM_FLARE | (SAU_PRIO << 8)
@draw:
    .a16
    .i16
    sta z:ES_SAU_DRAW + SAU_D_TILE
    lda z:US_HUD_X
    xba
    and #255                        ; the accumulator's whole-pixel half
    sta z:ES_SAU_DRAW + SAU_D_X
    lda z:US_HUD_THR
    sta z:ES_SAU_DRAW + SAU_D_Y
    stz z:ES_SAU_DRAW + SAU_D_SIZE
    jsr beam_slot_x
    lda z:ES_SAU_DRAW + SAU_D_TILE
    jsr sau_put
    bra @next
@park:
    .a16
    .i16
    jsr beam_slot_x
    jsr sau_park_slot
@next:
    .a16
    .i16
    lda z:US_HUD_X
    clc
    adc z:US_SCR
    sta z:US_HUD_X
    lda z:US_HUD_THR
    clc
    adc #SAU_BEAM_PITCH
    sta z:US_HUD_THR
    lda z:US_DI
    inc a
    sta z:US_DI
    cmp #SAU_BEAM_SEGS
    bcc @loop
    rts

; --- beam_slot_x: X = the shadow byte offset of beam cell US_DI ----------
; In/out: A16/I16, DB=0. Clobbers A.
beam_slot_x:
    .a16
    .i16
    lda z:US_DI
    clc
    adc #ES_O_BEAM
    asl
    asl                             ; slot * 4 = shadow byte offset
    tax
    rts

; --- draw_hp_hud: eight segment pips over the saucer (slots 17-24) --------
; Segment i is LIT while b_hp > i * SAU_HUD_SEG_HP. A running accumulator
; produces the threshold sequence for one add per segment, rather than a
; multiply per segment.
draw_hp_hud:
    .a16
    .i16
    stz z:US_DI                     ; segment index 0..7
    lda #SAU_HUD_X0
    sta z:US_HUD_X
    stz z:US_HUD_THR                ; threshold = segment * SAU_HUD_SEG_HP
@loop:
    .a16
    .i16
    lda z:US_B_HP
    cmp z:US_HUD_THR
    beq @dim                        ; equal/below -> depleted
    bcc @dim
    lda #SAU_T_PIP_LIT | (SAU_PRIO << 8)
    bra @have
@dim:
    .a16
    lda #SAU_T_PIP_DIM | (SAU_PRIO << 8)
@have:
    .a16
    sta z:ES_SAU_DRAW + SAU_D_TILE
    lda z:US_HUD_X
    sta z:ES_SAU_DRAW + SAU_D_X
    lda #SAU_HUD_Y
    sta z:ES_SAU_DRAW + SAU_D_Y
    stz z:ES_SAU_DRAW + SAU_D_SIZE
    lda z:US_DI
    clc
    adc #ES_O_HUD
    asl
    asl                             ; slot * 4 = shadow byte offset
    tax
    lda z:ES_SAU_DRAW + SAU_D_TILE
    jsr sau_put
    lda z:US_HUD_X
    clc
    adc #SAU_HUD_DX
    sta z:US_HUD_X
    lda z:US_HUD_THR
    clc
    adc #SAU_HUD_SEG_HP
    sta z:US_HUD_THR
    lda z:US_DI
    inc a
    sta z:US_DI
    cmp #SAU_HUD_SEGS
    bcc @loop
    rts

; --- draw_shots: slots 25-28, live at position or parked ------------------
draw_shots:
    .a16
    .i16
    stz z:US_DI
@loop:
    .a16
    .i16
    ldx z:US_DI
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_ALIVE, x
    beq @park
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_X, x
    sta z:ES_SAU_DRAW + SAU_D_X
    lda f:ES_SAU_ACTORS_LONG + SAU_SHOT_Y, x
    sta z:ES_SAU_DRAW + SAU_D_Y
    stz z:ES_SAU_DRAW + SAU_D_SIZE
    jsr shot_slot_x
    lda #SAU_T_SHOT | (SAU_PRIO << 8)
    jsr sau_put
    bra @next
@park:
    .a16
    jsr shot_slot_x
    jsr sau_park_slot
@next:
    .a16
    lda z:US_DI
    clc
    adc #2
    sta z:US_DI
    cmp #2 * SAU_SHOT_N
    bcc @loop
    rts

; --- shot_slot_x: X = the shadow byte offset of the shot at US_DI ---------
; US_DI is a pool BYTE offset (2 per slot), so the doubling below turns it
; into a slot index step before the *4.
shot_slot_x:
    .a16
    .i16
    lda z:US_DI
    asl                             ; byte offset *2 = slot offset step
    clc
    adc #ES_O_SHOTS * 4
    tax
    rts

; --- draw_exhaust: slot 29, the thruster flame, FIGHT only ---------------
; Drawn only during the fight, so the overlay bands stay clear in every other
; state. Two tiles alternating on a frame-parity class read as a pulse.
draw_exhaust:
    .a16
    .i16
    lda z:US_B_STATE
    cmp #SAU_ST_FIGHT
    bne @park
    lda z:US_FRAME
    and #SAU_EXH_MASK
    beq @lo
    lda #SAU_T_EXH_HI
    bra @have
@lo:
    .a16
    lda #SAU_T_EXH_LO
@have:
    .a16
    ora #(SAU_PRIO << 8)
    sta z:ES_SAU_DRAW + SAU_D_TILE
    lda z:US_P_X
    clc
    adc #4                          ; centre the 8 px flame under the hull
    sta z:ES_SAU_DRAW + SAU_D_X
    lda #SAU_PLAYER_Y + 14
    sta z:ES_SAU_DRAW + SAU_D_Y
    stz z:ES_SAU_DRAW + SAU_D_SIZE
    ldx #ES_O_EXHAUST * 4
    lda z:ES_SAU_DRAW + SAU_D_TILE
    jsr sau_put
    rts
@park:
    .a16
    ldx #ES_O_EXHAUST * 4
    jsr sau_park_slot
    rts

; =============================================================================
; draw_stars — slots 56-79, the sky, on the sprite layer and under the plane
; =============================================================================
; TWO BANDS OF TWELVE, each emitted by the same loop with different parameters.
; A band's screen position is its home table plus two offsets that are computed
; ONCE per band, so the per-star work is two adds, a mask and a sau_put:
;
;   y = (home_y + (scroll >> 8)) & 255   — the drift. The mask is the whole
;       wrap: OAM y is a byte, rows 224..255 are off the bottom of a 224-line
;       screen, and the PPU's own (scanline - y) & 255 comparison brings a
;       sprite back in at the top. So a star slides off the bottom and slides
;       in at the top with no test and no pop.
;   x = home_x + (SCREEN_CX >> SH) - (hull_centre >> SH)  — the parallax. The
;       gunship IS the camera on this rail, so its strafe is the only honest
;       sideways motion available, and the field counter-slides against it.
;       Each term is shifted separately (both are positive, so this is a plain
;       lsr and the difference carries the sign): SH = 3 for the near band and
;       4 for the far, the same half-rate relationship the drift has.
;
; NOTHING HERE READS THE MATRIX, and that is the point of the whole change: a
; star's rendered size is its 8x8 cell at every pose the four scale ramps
; reach. The field it replaces was painted into the Mode 7 plane and therefore
; zoomed with the saucer.
;
; WIDTH-RISK: A16/I16 entry AND exit, and no sep/rep in this body or in
; star_band — sau_put is A16/I16 both sides.
draw_stars:
    .a16
    .i16
    lda z:US_P_X
    clc
    adc #SAU_PLAYER_W / 2
    sta z:US_SCR                    ; the hull's centre column, both bands' input
    ; ---- the FAR band: half the drift, half the slide --------------------
    lda z:US_SCR
    .repeat ::SAU_STAR_PAR_FAR_SH
        lsr
    .endrepeat
    sta z:US_STAR_DX
    lda #(SAU_EMIT_CX >> SAU_STAR_PAR_FAR_SH)
    sec
    sbc z:US_STAR_DX                ; signed: + when the ship is left of centre
    sta z:US_STAR_DX
    lda z:US_STAR_FAR
    xba
    and #255                        ; the accumulator's whole-pixel half
    sta z:US_STAR_DY
    lda #SAU_T_STAR_FAR | (SAU_STAR_ATTR << 8)
    sta z:US_STAR_T
    stz z:US_DI
    lda #2 * SAU_STAR_FAR_N
    sta z:US_STAR_END
    jsr star_band
    ; ---- the NEAR band: it starts where the far band's table ended -------
    lda z:US_SCR
    .repeat ::SAU_STAR_PAR_SH
        lsr
    .endrepeat
    sta z:US_STAR_DX
    lda #(SAU_EMIT_CX >> SAU_STAR_PAR_SH)
    sec
    sbc z:US_STAR_DX
    sta z:US_STAR_DX
    lda z:US_STAR_NEAR
    xba
    and #255
    sta z:US_STAR_DY
    lda #SAU_T_STAR_NEAR | (SAU_STAR_ATTR << 8)
    sta z:US_STAR_T
    lda #2 * SAU_STAR_N
    sta z:US_STAR_END
    jsr star_band
    rts

; --- star_band: one depth band, from US_DI to US_STAR_END ------------------
; In:  A16/I16, DB=0. US_DI = the first star's WORD offset into the home
;      tables, US_STAR_END = one past the last, US_STAR_DX / US_STAR_DY = the
;      band's screen offset, US_STAR_T = tile | attr << 8.
; Out: A16/I16, US_DI = US_STAR_END. Clobbers A, X, Y.
star_band:
    .a16
    .i16
@loop:
    .a16
    .i16
    ldx z:US_DI
    lda f:star_home_x, x
    clc
    adc z:US_STAR_DX
    sta z:ES_SAU_DRAW + SAU_D_X
    lda f:star_home_y, x
    clc
    adc z:US_STAR_DY
    and #255                        ; the OAM y byte IS the wrap (see above)
    sta z:ES_SAU_DRAW + SAU_D_Y
    stz z:ES_SAU_DRAW + SAU_D_SIZE  ; every star is 8x8 (OBSEL pair 0, small)
    txa
    lsr                             ; word offset -> star index
    clc
    adc #ES_O_STARS
    asl
    asl                             ; slot * 4 = shadow byte offset
    tax
    lda z:US_STAR_T
    jsr sau_put
    lda z:US_DI
    inc a
    inc a
    sta z:US_DI
    cmp z:US_STAR_END
    bcc @loop
    rts

; --- the star homes: twelve far (0-11), twelve near (12-23) ---------------
; THE ROW SPACING IS A HARDWARE BUDGET, not a look. A band shares one scroll
; offset, so its stars keep their spacing forever; spacing every pair of a
; band at least 16 rows apart over the y byte's 256 therefore means no two
; stars of one band can EVER share a scanline (a star is 8 rows tall). At most
; one far star and one near star can coincide, so this whole field costs any
; scanline 2 of its 32 sprites and 2 of its 34 tile slivers, whatever the
; fight is doing — which is why a sparse field on OBJ is affordable where a
; dense one would drop the gunship.
;
; The columns are scattered by hand between 16 and 232 so the widest strafe
; slide (+/- 14 px) cannot push a star past either screen edge — which keeps
; every X9 bit 0 without sau_put having to assume it.
star_home_x:
    .word 30, 187, 96, 224, 58, 141, 19, 210, 118, 74, 165, 43     ; far
    .word 152, 66, 231, 108, 25, 196, 84, 172, 47, 129, 218, 93    ; near
star_home_y:
    .word 3, 26, 44, 68, 88, 110, 133, 152, 175, 196, 217, 239     ; far
    .word 14, 35, 57, 79, 99, 121, 142, 163, 186, 206, 228, 248    ; near

; =============================================================================
; The text cards — the boot title and the result word, as OBJ glyphs
; =============================================================================
; The overlay/title/text/banner emitters, over the 24-slot card band. The
; word is emitted FIRST (lower OAM slots) and
; its banner after it (higher slots), so the word composites in front of its
; own backing — the ordering is the OAM index alone, since every sprite on
; this rail carries the same priority.
draw_overlays:
    .a16
    .i16
    stz z:US_CARD_I                 ; the next free cell in the band
    lda z:US_B_STATE
    cmp #SAU_ST_FIGHT
    bcc @title                      ; INTRO/REVEAL/HOLD -> the boot title
    cmp #SAU_ST_LOSE
    beq @defeat
    cmp #SAU_ST_RESULT
    bne @park_rest                  ; FIGHT/DEATH/RESET -> no card
    lda z:US_B_RESULT
    cmp #2
    beq @defeat
    lda #SAU_VICTORY_X
    sta z:US_PEN_X
    lda #SAU_CARD_Y
    sta z:US_PEN_Y
    ldx #STR_VICTORY
    jsr draw_text
    jsr draw_card_bg
    bra @park_rest
@defeat:
    .a16
    lda #SAU_DEFEAT_X
    sta z:US_PEN_X
    lda #SAU_CARD_Y
    sta z:US_PEN_Y
    ldx #STR_DEFEAT
    jsr draw_text
    jsr draw_card_bg
    bra @park_rest
@title:
    .a16
    lda #SAU_TITLE1_X
    sta z:US_PEN_X
    lda #SAU_TITLE_Y1
    sta z:US_PEN_Y
    ldx #STR_TITLE1
    jsr draw_text
    lda #SAU_TITLE2_X
    sta z:US_PEN_X
    lda #SAU_TITLE_Y2
    sta z:US_PEN_Y
    ldx #STR_TITLE2
    jsr draw_text
@park_rest:
    .a16
    ; every cell the current card did NOT use goes off-screen, so a six-glyph
    ; DEFEAT cannot leave the seventh glyph of a previous VICTORY on display
    lda z:US_CARD_I
    clc
    adc #ES_O_CARDS
    asl
    asl
    tax
    lda #SAU_CARD_SLOTS
    sec
    sbc z:US_CARD_I
    tay
    jsr sau_park_range
    rts

; --- card_emit: one cell into the next free card slot ---------------------
; In:  A16/I16, DB=0. A = the tile (0..255); ES_SAU_DRAW+SAU_D_X/+SAU_D_Y set.
; Out: A16/I16. US_CARD_I advanced by one. Clobbers A, X, Y.
card_emit:
    .a16
    .i16
    ora #(SAU_PRIO << 8)
    sta z:ES_SAU_DRAW + SAU_D_TILE
    stz z:ES_SAU_DRAW + SAU_D_SIZE
    lda z:US_CARD_I
    clc
    adc #ES_O_CARDS
    asl
    asl                             ; slot * 4 = shadow byte offset
    tax
    lda z:ES_SAU_DRAW + SAU_D_TILE
    jsr sau_put
    lda z:US_CARD_I
    inc a
    sta z:US_CARD_I
    rts

; --- draw_text: spell a length-prefixed glyph run, left to right ----------
; In:  A16/I16, DB=0. X = the byte offset into glyph_strings of the run's
;      COUNT byte. US_PEN_X / US_PEN_Y = the pen; US_CARD_I = the next cell.
; Out: A16/I16. The pen and US_CARD_I advanced. Clobbers A, X, Y.
;
; SAU_G_SPACE advances the pen without emitting, so a run's CELL count and
; its GLYPH count differ — which is why the band's bound is asserted against
; the drawn counts below rather than against the run lengths.
; WIDTH-RISK: the two `sep #$20` windows read one string byte each and restore
; A16 before anything else; card_emit and sau_put are A16/I16 both sides.
draw_text:
    .a16
    .i16
    sep #$20
    .a8
    lda f:glyph_strings, x
    rep #$20
    .a16
    and #$00FF
    sta z:US_SCR                    ; cells remaining in this run
    inx
@loop:
    .a16
    .i16
    lda z:US_SCR
    beq @done
    sep #$20
    .a8
    lda f:glyph_strings, x
    rep #$20
    .a16
    and #$00FF
    cmp #SAU_G_SPACE
    beq @advance
    ; ---- emit this glyph into the next free cell -------------------------
    sta z:ES_SAU_DRAW + SAU_D_TILE
    lda z:US_PEN_X
    sta z:ES_SAU_DRAW + SAU_D_X
    lda z:US_PEN_Y
    sta z:ES_SAU_DRAW + SAU_D_Y
    phx                             ; card_emit needs X for the slot offset
    lda z:ES_SAU_DRAW + SAU_D_TILE
    jsr card_emit
    plx
@advance:
    .a16
    .i16
    lda z:US_PEN_X
    clc
    adc #SAU_GTEXT_ADV
    sta z:US_PEN_X
    inx
    lda z:US_SCR
    dec a
    sta z:US_SCR
    bra @loop
@done:
    .a16
    .i16
    rts

; --- draw_card_bg: a two-row banner behind the result word ---------------
; Emitted AFTER the word, so its higher OAM slots put it behind. US_DI = the
; column counter, US_HUD_X = the pen.
draw_card_bg:
    .a16
    .i16
    stz z:US_DI
    lda #SAU_CARD_BG_X0
    sta z:US_HUD_X
@col:
    .a16
    .i16
    lda z:US_HUD_X
    sta z:ES_SAU_DRAW + SAU_D_X
    lda #SAU_CARD_BG_Y0
    sta z:ES_SAU_DRAW + SAU_D_Y
    lda #SAU_T_CARDBG
    jsr card_emit
    lda z:US_HUD_X
    sta z:ES_SAU_DRAW + SAU_D_X
    lda #SAU_CARD_BG_Y0 + 8
    sta z:ES_SAU_DRAW + SAU_D_Y
    lda #SAU_T_CARDBG
    jsr card_emit
    lda z:US_HUD_X
    clc
    adc #8
    sta z:US_HUD_X
    lda z:US_DI
    inc a
    sta z:US_DI
    cmp #SAU_CARD_BG_TILES
    bcc @col
    rts

; --- the glyph runs: a COUNT byte, then that many cells -------------------
; SAU_G_SPACE = 255 marks a cell that only advances the pen. A sentinel WORD
; would look like an address, which is exactly what `no_literals` refuses, and
; a count byte halves the table besides.
glyph_strings:
STR_VICTORY = * - glyph_strings
    .byte 7, SAU_G_V, SAU_G_I, SAU_G_C, SAU_G_T, SAU_G_O, SAU_G_R, SAU_G_Y
STR_DEFEAT = * - glyph_strings
    .byte 6, SAU_G_D, SAU_G_E, SAU_G_F, SAU_G_E, SAU_G_A, SAU_G_T
STR_TITLE1 = * - glyph_strings              ; "SAUCER DOWN"
    .byte 11, SAU_G_S, SAU_G_A, SAU_G_U, SAU_G_C, SAU_G_E, SAU_G_R, SAU_G_SPACE
    .byte SAU_G_D, SAU_G_O, SAU_G_W, SAU_G_N
STR_TITLE2 = * - glyph_strings              ; "<> MOVE   A FIRE"
    .byte 15, SAU_G_LARR, SAU_G_RARR, SAU_G_SPACE, SAU_G_M, SAU_G_O, SAU_G_V
    .byte SAU_G_E, SAU_G_SPACE, SAU_G_SPACE, SAU_G_A, SAU_G_SPACE, SAU_G_F
    .byte SAU_G_I, SAU_G_R, SAU_G_E

; The card band's bound, proven at BUILD time rather than guarded at runtime
; (pool.asm's "the caller discharges the bound" discipline): the two widest
; things the band ever holds are the boot title's two rows and a VICTORY word
; with its banner.
SAU_TITLE_DRAWN  = 10 + 11                          ; spaces emit nothing
SAU_RESULT_DRAWN = 7 + 2 * SAU_CARD_BG_TILES
.assert SAU_TITLE_DRAWN <= SAU_CARD_SLOTS, error, "the boot title overflows the cards OAM band"
.assert SAU_RESULT_DRAWN <= SAU_CARD_SLOTS, error, "the result card overflows the cards OAM band"

.endscope
