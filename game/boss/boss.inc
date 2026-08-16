; =============================================================================
; boss.inc — the boss rail's own vocabulary (constants only; state is
; allocator-emitted via state.toml, addresses via the generated maps)
; =============================================================================
; Names carry the BS_ prefix. Bit masks are SHIFTS and dimensions are decimal:
; no_literals refuses hex forms that look like addresses, and the gate is right.

; --- pacing ----------------------------------------------------------------
BS_REVEAL_FRAMES = 60           ; reveal ramp length == the track's 60 steps
BS_HOLD_FRAMES   = 45           ; pause at full size before the fight
BS_FADE_FRAMES   = 32           ; state-timer pad around fades. SuperForge's
                                ;   fade feature ramps 1 level/frame (15 frames
                                ;   0<->15), so a 32-frame state wait strictly
                                ;   covers a completed fade. Its role is "state
                                ;   pacing", not "fade length"
BS_RESULT_FRAMES = 90           ; how long the result pose holds

; --- the state machine (+ the capture state) -------------------------------
BS_ST_INTRO  = 0                ; vestigial: battle_init enters REVEAL directly
BS_ST_REVEAL = 1                ; track: boss grows in (5.0 -> 1.5)
BS_ST_HOLD   = 2                ; ring: slow spin at full size
BS_ST_FIGHT  = 3                ; ring: combat, phase-driven spin
BS_ST_DEATH  = 4                ; track: boss recedes + spins (win)
BS_ST_LOSE   = 5                ; fade out (player died)
BS_ST_RESULT = 6                ; hold the outcome, then fade to RESET
BS_ST_RESET  = 7                ; masked re-init -> REVEAL (the loop)
BS_ST_DYING  = 8                ; the ring-capture beat between
                                ;   FIGHT and DEATH — spin at +4/frame until
                                ;   the heading aligns with the death track's
                                ;   baked start (0), so the handover's
                                ;   correction is smaller than one frame's own
                                ;   motion. Appended so indices 0-7 keep their
                                ;   established meanings
BS_DYING_SPIN = 4               ; headings/frame in DYING (> the fight's max 3,
                                ;   so the beat reads as death throes)

; --- the player ------------------------------------------------------------
BS_PLAYER_Y     = 184           ; fixed row; the player only strafes on X
BS_PLAYER_X0    = 120
BS_PLAYER_W     = 16
BS_PLAYER_H     = 16
BS_PLAYER_XMIN  = 8
BS_PLAYER_XMAX  = 232
BS_PLAYER_SPEED = 3             ; px/frame strafe
BS_PLAYER_HP0   = 3
BS_IFRAME_LEN   = 30            ; invuln frames after a hit

; --- combat ----------------------------------------------------------------
BS_SHOT_SPEED = 6               ; px/frame upward
BS_SHOT_W     = 8
BS_SHOT_H     = 8
BS_PROJ_W     = 8
BS_PROJ_H     = 8
BS_BOSS_HP0   = 240
BS_SHOT_DMG   = 5
BS_FIRE_GAP   = 8               ; min frames between player shots (held A)
BS_SHOT_CULL_Y = 16             ; a shot above this row is culled

; the boss hitbox: WIDE (a shot from any lane connects); the rain, by
; contrast, falls in a NARROW centre column the player strafes out of
BS_BOSS_HIT_X = 16
BS_BOSS_HIT_Y = 40
BS_BOSS_HIT_W = 224
BS_BOSS_HIT_H = 96
BS_ATK_SPAWN_X = 124            ; rain column centre (= spawn body centre)
BS_ATK_VY      = 3              ; rain fall speed
BS_ATK_CULL_Y  = 224            ; rain past the bottom is culled
BS_SPAWN_T0    = 30             ; first rain beat after battle_init

; --- the pools (offsets into the bs_actors claim) --------------------------
BS_ATK_N  = 8
BS_SHOT_N = 4
BS_ATK_ALIVE  = 0               ; alive[8]          (2 B/slot throughout)
BS_ATK_X      = 16              ; x[8]
BS_ATK_Y      = 32              ; y[8]
BS_ATK_VX     = 48              ; vx[8] (signed)
BS_ATK_VY_F   = 64              ; vy[8]
BS_SHOT_ALIVE = 80              ; alive[4]
BS_SHOT_X     = 88              ; x[4]
BS_SHOT_Y     = 96              ; y[4]
                                ; total 104 = the claim's bytes, asserted at
                                ;   the include site in scenes/arena.asm

; --- the RNG --------------------------------------------------------------
BS_RNG_SEED = 44257             ; decimal, per m7c_roll's seed idiom; any
                                ;   non-zero value works, and fixing one keeps
                                ;   the attack spread a deterministic sequence

; --- the HP HUD ------------------------------------------------------------
BS_HUD_SEGS   = 8
BS_HUD_SEG_HP = BS_BOSS_HP0 / BS_HUD_SEGS   ; 30 HP per segment
BS_HUD_Y      = 12
BS_HUD_X0     = 80
BS_HUD_DX     = 10

; --- OBJ vocabulary --------------------------------------------------------
BS_PARK_Y = 240                 ; off the visible 224 — where dead slots park
BS_LARGE  = 2                   ; the hi-table size bit (16x16 half of pair 0)
BS_PRIO   = 3 << 4              ; OAM attr: priority 3, over the Mode 7 plane
BS_T_PLAYER0 = 0                ; 16x16 quad {0,1,16,17}
BS_T_PLAYER1 = 2                ; the iframe flash frame, quad {2,3,18,19}
BS_T_ORB     = 4                ; 8x8 attack orb
BS_T_SHOT    = 5                ; 8x8 player bolt
BS_T_PIP_LIT = 6                ; 8x8 HP segment, lit
BS_T_PIP_DIM = 7                ; 8x8 HP segment, depleted
BS_FLASH_MASK = 4               ; frame & this picks the blink phase while
                                ;   iframes run

; --- pad bits (JOY1 standard layout; input.asm's $4218 word) ---------------
BS_JOY_RIGHT = 1 << 8
BS_JOY_LEFT  = 1 << 9
BS_JOY_A     = 1 << 7

; --- boss phases -----------------------------------------------------------
BS_PH1_HP = 161                 ; hp >= this -> phase 0 (spin 1, cadence 36)
BS_PH2_HP = 81                  ; hp >= this -> phase 1 (spin 2, cadence 26)
BS_CAD_P0 = 36                  ;             else phase 2 (spin 3, cadence 18)
BS_CAD_P1 = 26
BS_CAD_P2 = 18
