; =============================================================================
; scenes/arena.asm — the whole fight: reveal, hold, combat, dying, death, loop
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
; WHO ADVANCES THE TRACK CURSOR (the m7_track contract's question): this
; file, from its own state — the ramp index is the state timer's complement
; (idx = FRAMES + 1 - timer), the ring index is the live heading byte. No
; cursor variable exists, so the cursor cannot disagree with the state clock.

.scope arena

.include "engine_state_arena.inc"    ; GENERATED — this scene's map
.include "bs_floor.asm"              ; scene-scoped: the plane's upload
.include "bs_obj.asm"                ; scene-scoped: the cast + the pools

; --- the scene's base display ----------------------------------------------
; BGMODE 7 has exactly one BG; TM carries the plane AND the cast (one
; register, one owner — bs_floor's scene_writes carries the attribution).
TM_BG1 = 1
TM_OBJ = 1 << 4

; --- the pivot: the boss face centre (map px), shown at screen centre ------
; Half the 1024-px arena, as a shift (no_literals refuses the decimal form —
; 512 is also an address inside the OAM shadow claim, and nothing in the
; token distinguishes a world constant from a narrated address).
BS_CX = 1 << 9
BS_CY = 1 << 9

; --- the pool region's layout agrees with its claim ------------------------
.assert BS_SHOT_Y + 2 * BS_SHOT_N = ES_BS_ACTORS_SIZE, error, "boss.inc's pool offsets do not tile the bs_actors claim"

; =============================================================================
; enter — the plane, the cast, the pivot, the armed reveal
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 16 colours + M7SEL
    jsr obj_arm                     ; sheet + palette + OBSEL + pools + park

    ; ---- the pivot, seeded before the first NMI is armed ------------------
    ; m7a_set_center writes ES_M7AFF+8..+15 (M7X/M7Y + the screen origin);
    ; battle_init below writes +0..+7 through the reveal track's entry 0. Between
    ; them every byte of the shadow is written before the first commit reads
    ; it — rule 5's write-before-read contract, not defensive init.
    ldx #BS_CX
    ldy #BS_CY
    jsr ::m7a_set_center

    stz z:US_FRAME                  ; the free-running blink clock (persistent,
                                    ;   so it is seeded HERE, not per battle)
    jsr battle_init                 ; full battle state + reveal[0] + ST_REVEAL

    ; ---- the scene's base display (bs_floor's scene_writes) ---------------
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
; battle_init — (re)arm the full battle: reveal-tiny boss + fresh combat
; =============================================================================
; Called from enter and from the RESET state (the loop). The track binding
; replaces separate scale/angle seeds: entry 0 of the reveal track IS
; (angle 0, scale 5.0).
; In/out: A16/I16, DB=0. Clobbers A, X.
; WIDTH-RISK: pure A16/I16; POOL_BIND/M7T_BIND require A16 and leave it;
; pool_init and m7t_apply are A16/I16 both sides with no sep/rep.
battle_init:
    .a16
    .i16
    stz z:US_B_HEADING              ; angle 0
    lda #BS_BOSS_HP0
    sta z:US_B_HP
    stz z:US_B_PHASE
    stz z:US_B_VULN
    lda #BS_PLAYER_X0
    sta z:US_P_X                    ; player Y is the constant BS_PLAYER_Y
    lda #BS_PLAYER_HP0
    sta z:US_P_HP
    stz z:US_P_IFRAME
    lda #BS_SPAWN_T0
    sta z:US_SPAWN_TIMER
    stz z:US_FIRE_TIMER
    stz z:US_B_RESULT
    lda #BS_RNG_SEED
    sta z:US_RNG                    ; non-zero xorshift seed
    ; ---- both pools cleared through the mechanism -------------------------
    POOL_BIND ES_BS_ACTORS_LONG + BS_ATK_ALIVE
    ldx #BS_ATK_N
    jsr ::pool_init
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx #BS_SHOT_N
    jsr ::pool_init
    ; ---- the pre-reveal pose: tiny and unrotated, before the fade lifts ---
    M7T_BIND ::bs_reveal_bin
    lda #0
    jsr ::m7t_apply
    ; ---- enter REVEAL with its ramp timer ---------------------------------
    lda #BS_ST_REVEAL
    sta z:US_B_STATE
    lda #BS_REVEAL_FRAMES
    sta z:US_B_TIMER
    rts

; =============================================================================
; tick — one game frame: the state machine, then the draw
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
tick:
    .a16
    .i16
    jsr state_update
    jsr draw_frame
    lda z:US_FRAME
    inc a
    sta z:US_FRAME                  ; the blink clock (parity classes only)
    rts

; =============================================================================
; state_update — per-frame state machine (with the DYING beat)
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
    .addr su_intro                  ; BS_ST_INTRO  (0)
    .addr su_reveal                 ; BS_ST_REVEAL (1)
    .addr su_hold                   ; BS_ST_HOLD   (2)
    .addr su_fight                  ; BS_ST_FIGHT  (3)
    .addr su_death                  ; BS_ST_DEATH  (4)
    .addr su_lose                   ; BS_ST_LOSE   (5)
    .addr su_result                 ; BS_ST_RESULT (6)
    .addr su_reset                  ; BS_ST_RESET  (7)
    .addr su_dying                  ; BS_ST_DYING  (8)

; --- INTRO: vestigial (battle_init enters REVEAL directly) ----------------
su_intro:
    .a16
    lda #BS_ST_REVEAL
    sta z:US_B_STATE
    rts

; --- REVEAL: play the grow-in track; the boss GROWS as the scale falls -----
; idx = FRAMES + 1 - timer walks entries 1..60 as the timer counts 60..1;
; entry 60 == ring[60] (the generator's seam assert), so HOLD's first ring
; apply at heading 60+1 continues the motion with no pop.
su_reveal:
    .a16
    lda #BS_REVEAL_FRAMES + 1
    sec
    sbc z:US_B_TIMER
    sta z:US_SCR                    ; idx, 1..60
    M7T_BIND ::bs_reveal_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_SCR
    sta z:US_B_HEADING              ; the baked angle IS f — keep the live
                                    ;   heading in lockstep for the handover
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #BS_ST_HOLD
    sta z:US_B_STATE
    lda #BS_HOLD_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- HOLD: full size, gentle spin on the ring, then the fight --------------
su_hold:
    .a16
    lda z:US_B_HEADING
    inc a
    and #255
    sta z:US_B_HEADING
    M7T_BIND ::bs_ring_bin
    lda z:US_B_HEADING
    jsr ::m7t_apply
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #BS_ST_FIGHT
    sta z:US_B_STATE
    lda #1
    sta z:US_B_VULN                 ; the boss becomes vulnerable
@done:
    .a16
    rts

; --- FIGHT: combat, then the ring at the phase-advanced heading ------------
su_fight:
    .a16
    jsr fight_update
    M7T_BIND ::bs_ring_bin
    lda z:US_B_HEADING
    jsr ::m7t_apply
    rts

; --- DYING: the ring-capture beat ------------------------------------------
; Spin at +BS_DYING_SPIN (faster than any fight phase — death throes) until
; the forward distance to heading 0 (the death track's baked start) is less
; than one frame's spin, then snap the remainder and hand over. The snap is
; strictly smaller than the motion a normal frame shows, so the handover is
; invisible by construction; bounded at ceil(256/4) = 64 frames.
su_dying:
    .a16
    lda z:US_B_HEADING
    clc
    adc #BS_DYING_SPIN
    and #255
    sta z:US_B_HEADING
    lda #0
    sec
    sbc z:US_B_HEADING
    and #255                        ; forward distance to 0
    cmp #BS_DYING_SPIN
    bcc @capture
    M7T_BIND ::bs_ring_bin
    lda z:US_B_HEADING
    jsr ::m7t_apply
    rts
@capture:
    .a16
    stz z:US_B_HEADING
    lda #BS_ST_DEATH
    sta z:US_B_STATE
    lda #BS_REVEAL_FRAMES
    sta z:US_B_TIMER
    M7T_BIND ::bs_death_bin
    lda #0
    jsr ::m7t_apply                 ; death[0] == ring[0], the asserted seam
    rts

; --- DEATH: play the recede track (spin + shrink away); then RESULT(win) ---
su_death:
    .a16
    lda #BS_REVEAL_FRAMES + 1
    sec
    sbc z:US_B_TIMER
    sta z:US_SCR                    ; idx, 1..60
    M7T_BIND ::bs_death_bin
    lda z:US_SCR
    jsr ::m7t_apply
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #1
    sta z:US_B_RESULT               ; WIN
    lda #BS_ST_RESULT
    sta z:US_B_STATE
    lda #BS_RESULT_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- LOSE: the fade-out was armed at the transition; wait it through -------
; The matrix freezes at the last fight pose: this state applies no track
; entry, so the shadow simply persists.
su_lose:
    .a16
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    lda #2
    sta z:US_B_RESULT               ; LOSE
    lda #BS_ST_RESULT
    sta z:US_B_STATE
    lda #BS_RESULT_FRAMES
    sta z:US_B_TIMER
@done:
    .a16
    rts

; --- RESULT: hold the outcome pose, then fade out into RESET ---------------
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
    lda #BS_ST_RESET
    sta z:US_B_STATE
    lda #BS_FADE_FRAMES             ; > the fade's 15 steps, so RESET's swap
    sta z:US_B_TIMER                ;   runs on a black screen
@done:
    .a16
    rts

; --- RESET: wait out the fade, re-init masked, fade back in (the loop) -----
; The re-init touches no VRAM (map and palette are static), so the fade is
; choreography rather than a masking requirement;
; the swap still runs at brightness 0 because BS_FADE_FRAMES > 15.
su_reset:
    .a16
    lda z:US_B_TIMER
    dec a
    sta z:US_B_TIMER
    bne @done
    jsr battle_init                 ; -> ST_REVEAL, boss tiny again
    sep #$20
    .a8
    jsr ::fade_start_in
    rep #$20
    .a16
@done:
    .a16
    rts

; =============================================================================
; fight_update — combat: strafe, fire, shots, rain, contacts, phase, win/lose
; =============================================================================
; Combat, through the helpers below; the win transition goes to DYING (the
; capture beat) rather than straight to DEATH.
; WIDTH-RISK: A16/I16 entry/exit; the jsr'd helpers all keep A16/I16; the one
; A8 window is the LOSE arm's fade call, restored before the store after it.
fight_update:
    .a16
    .i16
    jsr player_move
    jsr player_fire
    jsr shots_update
    jsr boss_spawn
    jsr attacks_update
    jsr boss_phase
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
    stz z:US_B_VULN                 ; boss dead -> the capture beat, then DEATH
    lda #BS_ST_DYING
    sta z:US_B_STATE
    rts
@check_lose:
    .a16
    lda z:US_P_HP
    bne @alive
    sep #$20
    .a8
    jsr ::fade_start_out            ; player dead -> fade out under LOSE
    rep #$20
    .a16
    lda #BS_ST_LOSE
    sta z:US_B_STATE
    lda #BS_FADE_FRAMES
    sta z:US_B_TIMER
@alive:
    .a16
    rts

; --- player_move: LEFT/RIGHT strafe, clamped on screen ---------------------
player_move:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #BS_JOY_LEFT
    beq @no_left
    lda z:US_P_X
    sec
    sbc #BS_PLAYER_SPEED
    cmp #BS_PLAYER_XMIN
    bcs @store_left
    lda #BS_PLAYER_XMIN
@store_left:
    .a16
    sta z:US_P_X
@no_left:
    .a16
    lda z:ES_INP_CUR
    bit #BS_JOY_RIGHT
    beq @no_right
    lda z:US_P_X
    clc
    adc #BS_PLAYER_SPEED
    cmp #BS_PLAYER_XMAX
    bcc @store_right
    lda #BS_PLAYER_XMAX
@store_right:
    .a16
    sta z:US_P_X
@no_right:
    .a16
    rts

; --- player_fire: a shot while A is HELD, cadenced -------------------------
; The battle's outcome is player-driven: fire to damage the boss; hold off
; and the boss never dies. The cadence makes a held
; A a stream that cannot exhaust the 4-slot pool in one burst.
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
    bit #BS_JOY_A
    beq @no_fire
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx #BS_SHOT_N
    jsr ::pool_spawn
    bmi @no_fire                    ; POOL_FULL -> skip this shot
    ; X = the claimed slot's byte offset (pool_spawn's contract)
    lda z:US_P_X
    clc
    adc #4                          ; centre the 8x8 bolt over the 16x16 ship
    sta f:ES_BS_ACTORS_LONG + BS_SHOT_X, x
    lda #BS_PLAYER_Y - 8            ; spawn just above the ship
    sta f:ES_BS_ACTORS_LONG + BS_SHOT_Y, x
    lda #BS_FIRE_GAP
    sta z:US_FIRE_TIMER
@no_fire:
    .a16
    rts

; --- shots_update: advance UP, cull at the top, test vs the boss box -------
; X holds the pool byte offset across the pass; the long,x loads do not move
; it, and pool_kill preserves it (pool.asm's contract).
shots_update:
    .a16
    .i16
    stz z:US_UI
@loop:
    .a16
    ldx z:US_UI
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_ALIVE, x
    beq @next
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_Y, x
    sec
    sbc #BS_SHOT_SPEED
    sta f:ES_BS_ACTORS_LONG + BS_SHOT_Y, x
    cmp #BS_SHOT_CULL_Y
    bcc @kill                       ; reached the top band
    ; ---- vs the boss hitbox, only while vulnerable ------------------------
    ; Strict half-open AABB, one unsigned compare per axis (sprite_game's
    ; catch_dot derivation):
    ; overlap iff (a - b + wa - 1) unsigned< (wa + wb - 1).
    lda z:US_B_VULN
    beq @next
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_X, x
    sec
    sbc #BS_BOSS_HIT_X
    clc
    adc #BS_SHOT_W - 1
    cmp #BS_SHOT_W + BS_BOSS_HIT_W - 1
    bcs @next
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_Y, x
    sec
    sbc #BS_BOSS_HIT_Y
    clc
    adc #BS_SHOT_H - 1
    cmp #BS_SHOT_H + BS_BOSS_HIT_H - 1
    bcs @next
    ; ---- hit: drop boss HP (saturating) and free the shot -----------------
    lda z:US_B_HP
    cmp #BS_SHOT_DMG
    bcs @dmg
    lda #BS_SHOT_DMG                ; clamp so it cannot underflow
@dmg:
    .a16
    sec
    sbc #BS_SHOT_DMG
    sta z:US_B_HP
@kill:
    .a16
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx z:US_UI
    jsr ::pool_kill                 ; X preserved
@next:
    .a16
    lda z:US_UI
    clc
    adc #2
    sta z:US_UI
    cmp #2 * BS_SHOT_N
    bcc @loop
    rts

; --- boss_spawn: the rain, on the phase cadence ----------------------------
; A narrow centre column (BS_ATK_SPAWN_X +/- ~15 via the RNG) the player
; strafes out of; a player who stays put is reliably hit (the deterministic
; LOSE path), while the WIDE boss hitbox still lets side-lane shots connect.
boss_spawn:
    .a16
    .i16
    lda z:US_SPAWN_TIMER
    beq @fire
    dec a
    sta z:US_SPAWN_TIMER
    rts
@fire:
    .a16
    POOL_BIND ES_BS_ACTORS_LONG + BS_ATK_ALIVE
    ldx #BS_ATK_N
    jsr ::pool_spawn
    bmi @reload                     ; pool full -> just reset the cadence
    ; X = slot offset; rng_next clobbers A only, so X carries through
    jsr rng_next
    and #31                         ; 0..31
    sec
    sbc #16                         ; -16..+15 (the tight column)
    clc
    adc #BS_ATK_SPAWN_X
    sta f:ES_BS_ACTORS_LONG + BS_ATK_X, x
    lda #BS_BOSS_HIT_Y              ; spawn from the face band
    sta f:ES_BS_ACTORS_LONG + BS_ATK_Y, x
    jsr rng_next
    and #3
    sec
    sbc #1                          ; -1..+2
    cmp #2
    bne @vx_store
    lda #0                          ; map +2 -> 0 (mostly straight down)
@vx_store:
    .a16
    sta f:ES_BS_ACTORS_LONG + BS_ATK_VX, x
    lda #BS_ATK_VY
    sta f:ES_BS_ACTORS_LONG + BS_ATK_VY_F, x
@reload:
    .a16
    lda z:US_B_PHASE
    cmp #2
    bcs @p2
    cmp #1
    bcs @p1
    lda #BS_CAD_P0
    bra @set
@p1:
    .a16
    lda #BS_CAD_P1
    bra @set
@p2:
    .a16
    lda #BS_CAD_P2
@set:
    .a16
    sta z:US_SPAWN_TIMER
    rts

; --- attacks_update: integrate the rain; cull; contact vs the player -------
attacks_update:
    .a16
    .i16
    stz z:US_UI
@loop:
    .a16
    ldx z:US_UI
    lda f:ES_BS_ACTORS_LONG + BS_ATK_ALIVE, x
    beq @next
    lda f:ES_BS_ACTORS_LONG + BS_ATK_X, x
    clc
    adc f:ES_BS_ACTORS_LONG + BS_ATK_VX, x
    sta f:ES_BS_ACTORS_LONG + BS_ATK_X, x
    lda f:ES_BS_ACTORS_LONG + BS_ATK_Y, x
    clc
    adc f:ES_BS_ACTORS_LONG + BS_ATK_VY_F, x
    sta f:ES_BS_ACTORS_LONG + BS_ATK_Y, x
    cmp #BS_ATK_CULL_Y
    bcs @kill                       ; past the bottom of the play area
    ; ---- vs the player box (strict half-open AABB, per axis) --------------
    lda f:ES_BS_ACTORS_LONG + BS_ATK_X, x
    sec
    sbc z:US_P_X
    clc
    adc #BS_PROJ_W - 1
    cmp #BS_PROJ_W + BS_PLAYER_W - 1
    bcs @next
    lda f:ES_BS_ACTORS_LONG + BS_ATK_Y, x
    sec
    sbc #BS_PLAYER_Y
    clc
    adc #BS_PROJ_H - 1
    cmp #BS_PROJ_H + BS_PLAYER_H - 1
    bcs @next
    ; ---- contact: always free the attack; damage only outside iframes -----
    POOL_BIND ES_BS_ACTORS_LONG + BS_ATK_ALIVE
    ldx z:US_UI
    jsr ::pool_kill                 ; X preserved
    lda z:US_P_IFRAME
    bne @next
    lda z:US_P_HP
    beq @next                       ; already 0
    dec a
    sta z:US_P_HP
    lda #BS_IFRAME_LEN
    sta z:US_P_IFRAME
    bra @next
@kill:
    .a16
    POOL_BIND ES_BS_ACTORS_LONG + BS_ATK_ALIVE
    ldx z:US_UI
    jsr ::pool_kill
@next:
    .a16
    lda z:US_UI
    clc
    adc #2
    sta z:US_UI
    cmp #2 * BS_ATK_N
    bcs @done
    brl @loop                       ; the integrate+contact body outgrew a
@done:                              ;   short branch
    .a16
    rts

; --- rng_next: the 16-bit xorshift -----------------------------------------
; x ^= x<<7; x ^= x>>9; x ^= x<<8. Returns the new state in A; clobbers
; nothing else.
rng_next:
    .a16
    .i16
    lda z:US_RNG
    .repeat 7
        asl
    .endrepeat
    eor z:US_RNG
    sta z:US_RNG
    .repeat 9
        lsr
    .endrepeat
    eor z:US_RNG
    sta z:US_RNG
    .repeat 8
        asl
    .endrepeat
    eor z:US_RNG
    sta z:US_RNG
    rts

; --- boss_phase: HP thirds -> phase + spin; the boss keeps turning ---------
; Thresholds (240/3 bands) and spins (1/2/3); a separate angle-speed variable
; is folded into the add — nothing else would read it.
boss_phase:
    .a16
    .i16
    lda z:US_B_HP
    cmp #BS_PH1_HP
    bcs @p0
    cmp #BS_PH2_HP
    bcs @p1
    lda #2                          ; phase 2: hp <= 80
    sta z:US_B_PHASE
    lda #3
    bra @spd
@p1:
    .a16
    lda #1
    sta z:US_B_PHASE
    lda #2
    bra @spd
@p0:
    .a16
    stz z:US_B_PHASE
    lda #1
@spd:
    .a16
    clc
    adc z:US_B_HEADING
    and #255
    sta z:US_B_HEADING
    rts

; =============================================================================
; draw_frame — the stable slot map, every slot every frame
; =============================================================================
; 0 player · 1-8 attacks · 9-16 HP HUD · 17-20 shots. Dead slots park at
; BS_PARK_Y so slot identity is stable; the six hi-table
; bytes are cleared first and rebuilt whole by the bs_put calls.
draw_frame:
    .a16
    .i16
    jsr bs_hi_clear
    ; ---- slot 0: the player ship ------------------------------------------
    ; Hidden pre-fight (states < HOLD) and post-fight (RESULT/RESET) so the
    ; boss read is clean; visible HOLD..LOSE and through the DYING beat. The
    ; iframe hit-flash alternates frames so it reads as a blink.
    lda z:US_B_STATE
    cmp #BS_ST_HOLD
    bcc @park_player
    cmp #BS_ST_RESULT
    bcc @vis                        ; HOLD/FIGHT/DEATH/LOSE
    cmp #BS_ST_DYING
    beq @vis                        ; the capture beat: still the fight tableau
    bra @park_player                ; RESULT/RESET
@vis:
    .a16
    lda #BS_T_PLAYER0
    sta z:ES_BS_DRAW + BS_D_TILE
    lda z:US_P_IFRAME
    beq @tile_picked
    lda z:US_FRAME
    and #BS_FLASH_MASK
    beq @tile_picked
    lda #BS_T_PLAYER1
    sta z:ES_BS_DRAW + BS_D_TILE
@tile_picked:
    .a16
    lda z:US_P_X
    sta z:ES_BS_DRAW + BS_D_X
    lda #BS_PLAYER_Y
    sta z:ES_BS_DRAW + BS_D_Y
    lda #BS_LARGE
    sta z:ES_BS_DRAW + BS_D_SIZE
    ldx #ES_O_PLAYER * 4
    lda z:ES_BS_DRAW + BS_D_TILE
    ora #BS_PRIO << 8
    jsr bs_put
    bra @attacks
@park_player:
    .a16
    ldx #ES_O_PLAYER * 4
    jsr bs_park_slot
@attacks:
    .a16
    ; ---- slots 1-8: the attack pool (live at position, dead parked) -------
    stz z:US_DI
@atk_loop:
    .a16
    ldx z:US_DI
    lda f:ES_BS_ACTORS_LONG + BS_ATK_ALIVE, x
    beq @atk_park
    lda f:ES_BS_ACTORS_LONG + BS_ATK_X, x
    sta z:ES_BS_DRAW + BS_D_X
    lda f:ES_BS_ACTORS_LONG + BS_ATK_Y, x
    sta z:ES_BS_DRAW + BS_D_Y
    stz z:ES_BS_DRAW + BS_D_SIZE
    lda z:US_DI
    asl                             ; pool byte offset *2 = slot offset step
    clc
    adc #ES_O_ATTACKS * 4
    tax
    lda #BS_T_ORB | (BS_PRIO << 8)
    jsr bs_put
    bra @atk_next
@atk_park:
    .a16
    lda z:US_DI
    asl
    clc
    adc #ES_O_ATTACKS * 4
    tax
    jsr bs_park_slot
@atk_next:
    .a16
    lda z:US_DI
    clc
    adc #2
    sta z:US_DI
    cmp #2 * BS_ATK_N
    bcs @atk_done
    brl @atk_loop                   ; the emit body outgrew a short branch
@atk_done:
    .a16
    ; ---- slots 9-16: the boss HP HUD --------------------------------------
    jsr draw_hp_hud
    ; ---- slots 17-20: the player shots ------------------------------------
    stz z:US_DI
@shot_loop:
    .a16
    ldx z:US_DI
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_ALIVE, x
    beq @shot_park
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_X, x
    sta z:ES_BS_DRAW + BS_D_X
    lda f:ES_BS_ACTORS_LONG + BS_SHOT_Y, x
    sta z:ES_BS_DRAW + BS_D_Y
    stz z:ES_BS_DRAW + BS_D_SIZE
    lda z:US_DI
    asl
    clc
    adc #ES_O_SHOTS * 4
    tax
    lda #BS_T_SHOT | (BS_PRIO << 8)
    jsr bs_put
    bra @shot_next
@shot_park:
    .a16
    lda z:US_DI
    asl
    clc
    adc #ES_O_SHOTS * 4
    tax
    jsr bs_park_slot
@shot_next:
    .a16
    lda z:US_DI
    clc
    adc #2
    sta z:US_DI
    cmp #2 * BS_SHOT_N
    bcc @shot_loop
    rts

; --- draw_hp_hud: eight segment pips over the boss (slots 9-16) ------------
; Segment i is LIT while b_hp > i * BS_HUD_SEG_HP. A running accumulator
; produces the threshold sequence for one add per segment, rather than a
; multiply per segment.
draw_hp_hud:
    .a16
    .i16
    stz z:US_DI                     ; segment index 0..7
    lda #BS_HUD_X0
    sta z:US_HUD_X
    stz z:US_HUD_THR                ; threshold = segment * BS_HUD_SEG_HP
@loop:
    .a16
    lda z:US_B_HP
    cmp z:US_HUD_THR
    beq @dim                        ; equal/below -> depleted
    bcc @dim
    lda #BS_T_PIP_LIT | (BS_PRIO << 8)
    bra @have
@dim:
    .a16
    lda #BS_T_PIP_DIM | (BS_PRIO << 8)
@have:
    .a16
    sta z:ES_BS_DRAW + BS_D_TILE
    lda z:US_HUD_X
    sta z:ES_BS_DRAW + BS_D_X
    lda #BS_HUD_Y
    sta z:ES_BS_DRAW + BS_D_Y
    stz z:ES_BS_DRAW + BS_D_SIZE
    lda z:US_DI
    clc
    adc #ES_O_HUD
    asl
    asl                             ; slot * 4 = shadow byte offset
    tax
    lda z:ES_BS_DRAW + BS_D_TILE
    jsr bs_put
    lda z:US_HUD_X
    clc
    adc #BS_HUD_DX
    sta z:US_HUD_X
    lda z:US_HUD_THR
    clc
    adc #BS_HUD_SEG_HP
    sta z:US_HUD_THR
    lda z:US_DI
    inc a
    sta z:US_DI
    cmp #BS_HUD_SEGS
    bcc @loop
    rts

.endscope
