; =============================================================================
; saucer.inc — boss_saucer's own vocabulary (constants only; state is
; allocator-emitted via state.toml, addresses via the generated maps)
; =============================================================================
; Names carry the SAU_ prefix. Bit masks are SHIFTS and dimensions are decimal:
; no_literals refuses hex forms that look like addresses, and the gate is right.

; --- pacing ----------------------------------------------------------------
SAU_REVEAL_FRAMES = 60          ; reveal ramp length == the track's 60 steps
SAU_HOLD_FRAMES   = 45          ; pause at full size before the fight
SAU_FADE_FRAMES   = 32          ; state-timer pad around fades. SuperForge's
                                ;   fade feature ramps 1 level/frame (15 frames
                                ;   0<->15), so a 32-frame state wait strictly
                                ;   covers a completed fade. Its role is "state
                                ;   pacing", not "fade length"
SAU_RESULT_FRAMES = 90          ; how long the result card holds

; --- the state machine -----------------------------------------------------
; Eight indices, with no ninth: the boss rail's DYING capture beat exists
; because that rail's fight rotates freely, so its death track's baked start
; angle is player-dependent. This rail's fight holds angle 0, so DEATH enters
; from the baked start exactly and there is nothing to capture.
SAU_ST_INTRO  = 0               ; vestigial: battle_init enters REVEAL directly
SAU_ST_REVEAL = 1               ; track: the saucer grows in (5.0 -> 1.5)
SAU_ST_HOLD   = 2               ; ring: slow spin at full size
SAU_ST_FIGHT  = 3               ; the LUNGE cycle + the BEAM + combat
SAU_ST_DEATH  = 4               ; track: the saucer recedes + spins (win)
SAU_ST_LOSE   = 5               ; the player died
SAU_ST_RESULT = 6               ; hold the outcome card, then fade to RESET
SAU_ST_RESET  = 7               ; masked re-init -> REVEAL (the loop)

; --- the LUNGE: the rail's headline ----------------------------------------
; The saucer dives at the camera by ramping the matrix scale DOWN (a smaller
; value samples fewer texels per pixel, so the plane looks BIGGER).
SAU_LG_FAR      = 0             ; dwell at rest scale, then APPROACH
SAU_LG_APPROACH = 1             ; ramp down to the apex; at apex lock the beam
SAU_LG_NEAR     = 2             ; hold the apex while the beam runs
SAU_LG_RETREAT  = 3             ; ramp back up to rest, then FAR
; The realized ramp length. A scale ramp driven by COMPARISON rather than by
; counting (subtract a step, clamp at the near scale) runs 45 frames with a
; terminal clamp even though its nominal step count is 40. This constant is
; the length the track blobs were BAKED with; the generator derives the same 45
; from the same arithmetic, and a disagreement would break its seam asserts.
SAU_LUNGE_FRAMES = 45
; the FAR dwell, shortened by phase: faster lunges as HP drops
SAU_FAR_P0 = 40                 ; the full dwell
SAU_FAR_P1 = 28                 ; full - 12
SAU_FAR_P2 = 16                 ; full - 24

; --- the BEAM --------------------------------------------------------------
; A vertical energy column fired at the lunge apex, its X LOCKED to the
; player's body centre at the approach's last frame — so the telegraph is the
; player's window to strafe out of the column.
SAU_BM_OFF  = 0
SAU_BM_TELE = 1                 ; dim (every other segment), no damage
SAU_BM_FIRE = 2                 ; solid, damaging
SAU_BEAM_SEGS   = 16            ; 16 x 8 px = 128 px of column
SAU_BEAM_Y0     = 56            ; the saucer's ventral emitter row
SAU_BEAM_PITCH  = 8             ; segment stride (the tile butts seamlessly)
SAU_BEAM_W      = 8
SAU_BEAM_TELE_F = 24            ; telegraph frames (the dodge window)
SAU_BEAM_FIRE_F = 30            ; active frames
SAU_BEAM_HIT_Y  = SAU_BEAM_Y0
SAU_BEAM_HIT_H  = 160           ; reaches well past SAU_PLAYER_Y (184)

; --- the player ------------------------------------------------------------
SAU_PLAYER_Y     = 184          ; fixed row; the player only strafes on X
SAU_PLAYER_X0    = 120
SAU_PLAYER_W     = 16
SAU_PLAYER_H     = 16
SAU_PLAYER_XMIN  = 8
SAU_PLAYER_XMAX  = 232
SAU_PLAYER_SPEED = 3            ; px/frame strafe
SAU_PLAYER_HP0   = 3
SAU_IFRAME_LEN   = 30           ; invuln frames after a beam hit

; --- combat ----------------------------------------------------------------
SAU_SHOT_SPEED  = 6             ; px/frame upward
SAU_SHOT_W      = 8
SAU_SHOT_H      = 8
SAU_BOSS_HP0    = 240
SAU_SHOT_DMG    = 5             ; ~48 hits to kill
SAU_FIRE_GAP    = 8             ; min frames between player shots (held A)
SAU_SHOT_CULL_Y = 16            ; a shot above this row is culled

; the saucer hitbox: WIDE (a shot from any lane connects); the BEAM, by
; contrast, is a NARROW locked column the player strafes out of
SAU_BOSS_HIT_X = 16
SAU_BOSS_HIT_Y = 40
SAU_BOSS_HIT_W = 224
SAU_BOSS_HIT_H = 96

; --- the shot pool (offsets into the sau_actors claim) ---------------------
; ONE pool: the boss rail's 8-slot orb rain has no analogue here — this saucer
; attacks with a BEAM, not orbs.
SAU_SHOT_N     = 4
SAU_SHOT_ALIVE = 0              ; alive[4]         (2 B/slot throughout)
SAU_SHOT_X     = 8              ; x[4]
SAU_SHOT_Y     = 16             ; y[4]
                                ; total 24 = the claim's bytes, asserted at
                                ;   the include site in scenes/arena.asm

; --- the HP HUD ------------------------------------------------------------
SAU_HUD_SEGS   = 8
SAU_HUD_SEG_HP = SAU_BOSS_HP0 / SAU_HUD_SEGS   ; 30 HP per segment — derived
                                ;   from the two constants above rather than
                                ;   written out, so the HUD cannot drift from
                                ;   the HP pool it reports
SAU_HUD_Y      = 12
SAU_HUD_X0     = 80
SAU_HUD_DX     = 10

; --- OBJ vocabulary --------------------------------------------------------
SAU_PARK_Y = 240                ; off the visible 224 — where dead slots park
SAU_LARGE  = 2                  ; the hi-table size bit (16x16 half of pair 0)
SAU_PRIO   = 3 << 4             ; OAM attr: priority 3, over the Mode 7 plane.
                                ;   EVERY sprite on this rail uses it, so the
                                ;   card glyphs sit in front of their own
                                ;   banner by OAM INDEX alone
SAU_T_PLAYER0 = 0               ; 16x16 quad {0,1,16,17}
SAU_T_PLAYER1 = 2               ; the iframe flash frame, quad {2,3,18,19}
SAU_T_SHOT    = 5               ; 8x8 player bolt
SAU_T_PIP_LIT = 6               ; 8x8 HP segment, lit
SAU_T_PIP_DIM = 7               ; 8x8 HP segment, spent
SAU_T_BEAM    = 8               ; 8x8 beam segment
SAU_T_EXH_LO  = 9               ; thruster flame, short phase
SAU_T_EXH_HI  = 10              ; thruster flame, tall phase
SAU_T_CARDBG  = 11              ; the result banner's cell
SAU_FLASH_MASK = 4              ; frame & this picks the iframe blink phase
SAU_EXH_MASK   = 8              ; frame & this picks the flame phase

; --- the glyph cards -------------------------------------------------------
; Text is OBJ glyphs from the rail's own sheet. The strings are LENGTH-PREFIXED
; byte runs rather than sentinel-terminated word runs: a sentinel that looks
; like an address is precisely what `no_literals` refuses, and a count byte is
; smaller anyway.
SAU_G_SPACE   = 255             ; advance the pen, draw nothing (not a tile)
SAU_GTEXT_ADV = 6               ; pen advance per cell (5 px face + 1 px gap)
SAU_CARD_SLOTS = 24             ; the cards OAM band's width (sau_obj's claim)
SAU_CARD_Y     = 100            ; the result word's row
SAU_CARD_BG_TILES = 8           ; banner width, 8x8 cells (64 px)
SAU_CARD_BG_X0    = 128 - SAU_CARD_BG_TILES * 8 / 2      ; = 96, centred
SAU_CARD_BG_Y0    = SAU_CARD_Y - 4                       ; the word sits in it
SAU_DEFEAT_X  = (256 - 6 * SAU_GTEXT_ADV) / 2            ; "DEFEAT",  6 cells
SAU_VICTORY_X = (256 - 7 * SAU_GTEXT_ADV) / 2            ; "VICTORY", 7 cells
SAU_TITLE_Y1  = 30              ; the boot title's name row
SAU_TITLE_Y2  = 42              ; ...and its controls row
SAU_TITLE1_X  = (256 - 11 * SAU_GTEXT_ADV) / 2           ; "SAUCER DOWN"
SAU_TITLE2_X  = (256 - 15 * SAU_GTEXT_ADV) / 2           ; "<> MOVE   A FIRE"

; the glyph tile numbers, gen_saucer_assets.py's GLYPH_ORDER in order
SAU_G_A = 20
SAU_G_C = 21
SAU_G_D = 22
SAU_G_E = 23
SAU_G_F = 24
SAU_G_I = 25
SAU_G_M = 26
SAU_G_N = 27
SAU_G_O = 28
SAU_G_R = 29
SAU_G_S = 30
SAU_G_T = 31
SAU_G_U = 32
SAU_G_V = 33
SAU_G_W = 34
SAU_G_Y = 35
SAU_G_LARR = 36
SAU_G_RARR = 37

; --- pad bits (JOY1 standard layout; input.asm's $4218 word) ---------------
SAU_JOY_A     = 1 << 7
SAU_JOY_RIGHT = 1 << 8
SAU_JOY_LEFT  = 1 << 9
SAU_JOY_START = 1 << 12

; --- saucer phases ---------------------------------------------------------
SAU_PH1_HP = 161                ; hp >= this -> phase 0 (dwell 40)
SAU_PH2_HP = 81                 ; hp >= this -> phase 1 (dwell 28)
                                ;             else phase 2 (dwell 16)
