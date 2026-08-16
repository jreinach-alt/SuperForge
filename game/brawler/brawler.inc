; =============================================================================
; brawler.inc — the rail's geometry, tuning and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scene) because brawler_bg.asm,
; brawler_obj.asm and the fight scene all read from it. Pure equates: no code,
; no claims, nothing the allocator owns. Every number is written as the algebra
; it is — `no_literals` refuses the bare hex forms, and the shift forms say what
; each number IS.

; --- $4218 bit POSITIONS (shifts, not hex — the no_literals idiom) -----------
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11

; --- tuning ------------------------------------------------------------------
BR_WALK_SPEED  = 2               ; Arthur's move step, px/frame
BR_ENEMY_SPEED = 1               ; how fast Mordred closes
BR_ATTACK_LEN  = 16              ; swing length in frames; hitbox live 4..12
BR_PLAYER_HP   = 3
BR_FOE_HP      = 3
BR_RESPAWN_T   = 90              ; frames Mordred stays gone after a KO
.assert BR_WALK_SPEED <= 8, error, "WALK_SPEED > 8 breaks the clamps (min position >= max step)"

; --- the arena (32x32 sprites on a 256x224 screen) --------------------------
BR_ARENA_L = 8                   ; Arthur's top-left X min
BR_ARENA_R = 216                 ; ...and max: keeps the 32 px body on screen

; THE LANE BAND IS IN CONTENT TERMS, NOT OAM-BOX TERMS. The floor reads as a
; surface seen from the side, so the knights stand ON TOP of it. Every camelot
; frame (both knights, every animation — measured by the generator, which
; refuses to emit if it moves) ends its drawn pixels at row 28 of the 32-row
; cell: four transparent rows under the feet. So the DRAWN feet sit at
; py + BR_CONTENT_BOTTOM and the band pins them to the surface top. A box-edge
; clamp (py + 32 = surface) leaves a 4 px sky gap under the feet — measured on
; screen, so do not regress to it.
BR_CONTENT_BOTTOM = 28
BR_SURFACE_TOP    = 160          ; the floor's top edge: tilemap row 20 x 8 px
BR_LANE_TOP = BR_SURFACE_TOP - BR_CONTENT_BOTTOM   ; 132: feet exactly on it
BR_LANE_BOT = BR_LANE_TOP + 4                      ; 136: 4 px of give
.assert BR_LANE_TOP + BR_CONTENT_BOTTOM = BR_SURFACE_TOP, error, "lane band no longer anchors the drawn feet to the surface top"

; --- spawns ------------------------------------------------------------------
BR_SPAWN_PX = 60
BR_SPAWN_PY = 134                ; mid-band (drawn feet at 162)
BR_SPAWN_EX = 180
BR_SPAWN_EY = 134                ; matches the player's spawn lane

; --- anim states — ALSO the br_anim stride index ----------------------------
; 0/1/2 are Arthur's idle/run/hit tables; 3/4 are Mordred's idle/run. A branch
; chain to a named table per state would have to be written in TWO places (the
; clock and the draw); one stride index does both.
BR_ST_IDLE   = 0
BR_ST_RUN    = 1
BR_ST_ATTACK = 2
BR_ST_E_IDLE = 3
BR_ST_E_RUN  = 4
BR_ANIM_STRIDE = 8               ; bytes per table in br_anim.bin
BR_META_STRIDE = 2               ; (len, rate) per table in br_anim_meta.bin

; --- combat ------------------------------------------------------------------
BR_HIT_W     = 16                ; the swing's hitbox, 16x16 in front of Arthur
BR_HIT_H     = 16
BR_HIT_AHEAD = 28                ; facing right: hitbox left = px + this
BR_HIT_BEHIND = 12               ; facing left:  hitbox left = px - this
BR_HIT_DY    = 8                 ; hitbox top = py + this
BR_BODY_W    = 32                ; Mordred's box for the SWING test
BR_BODY_H    = 32
BR_TOUCH_W   = 28                ; both boxes for the CONTACT test — tighter
BR_TOUCH_H   = 28                ;   than the sprite, so bodies must really meet
BR_STUN_T    = 20                ; Mordred's stagger after a landed hit
BR_INV_T     = 45                ; Arthur's i-frames after taking one
BR_KNOCKBACK = 24                ; px Arthur is pushed away from Mordred

; The live window of the swing: ATTACKT counts DOWN from BR_ATTACK_LEN, and
; the hitbox is live on swing frames 4..12, i.e.
; while ATTACKT is in [ATTACK_LEN-12, ATTACK_LEN-4].
BR_HIT_FIRST = BR_ATTACK_LEN - 12
BR_HIT_LAST  = BR_ATTACK_LEN - 4

; --- the floor ---------------------------------------------------------------
; The terrain PATCH is 8x6 cells; the floor tiles it horizontally by
; `col mod 8` and vertically by picking a patch ROW: row 1 (the grass tops) for
; the surface, row 2 (the dirt fill) for everything under it.
BR_PATCH_W    = 8
BR_FLOOR_ROW  = 20               ; tilemap row of the grass top = surface / 8
BR_FLOOR_END  = 28               ; one past the last filled row
BR_PATCH_TOP  = 1                ; patch row index for the surface
BR_PATCH_FILL = 2                ; patch row index for the body
BR_MAP_W      = 32               ; tilemap width in cells
.assert BR_FLOOR_ROW * 8 = BR_SURFACE_TOP, error, "the floor row and the surface top disagree"

; --- OAM slot assignment -----------------------------------------------------
; Arthur holds slot +0, which always wins overlap against slot +1 (lower slot =
; drawn in front). True Y-sorted depth would need per-frame slot assignment,
; which is out of this rail's scope at two actors.
BR_OAM_ARTHUR  = 0
BR_OAM_MORDRED = 1

; OAM attribute bytes. Bit 0 = the 9th TILE bit (second OBJ name table), bits
; 1-3 = palette, 4-5 = priority, 6 = H-flip, 7 = V-flip. Size is NOT here — it
; is a hi-table bit (see brawler_obj.asm). Both knights draw at priority 2;
; Arthur is palette 0 / name table 0 and Mordred palette 1 / name table 1.
BR_PRI          = 2 << 4
BR_ATTR_ARTHUR  = BR_PRI                      ; palette 0, name table 0
BR_ATTR_MORDRED = BR_PRI | (1 << 1) | (1 << 0); palette 1, name table 1
BR_ATTR_HFLIP   = 1 << 6

; --- BG3 text geometry -------------------------------------------------------
; Pixel columns / 8. "HP" at px 8 -> col 1, its counter at px 32 -> col 4;
; "FOE" at px 88 -> col 11, counter px 120 -> col 15; "WINS" at px 168 ->
; col 21, counter px 208 -> col 26. "GAME OVER" at px (96,104) -> col 12
; row 13.
BR_HUD_ROW    = 1
BR_HP_LABEL_C = 1
BR_HP_VAL_C   = 4
BR_FOE_LABEL_C = 11
BR_FOE_VAL_C  = 15
BR_WINS_LABEL_C = 21
BR_WINS_VAL_C = 26
BR_VAL_CELLS  = 4                ; text_queue_hex4 stages exactly TXT_Q_MAX
.assert BR_WINS_VAL_C + BR_VAL_CELLS <= BR_MAP_W, error, "the WINS counter runs off the tilemap row"
BR_OVER_ROW   = 13
BR_OVER_C     = 12
BR_OVER_LEN   = 9                ; "GAME OVER"

; The HUD pump: one queue run per frame, so the three counters take turns.
; hudp counts 3 -> 2 -> 1 -> 0 and reprints HP, FOE, WINS in that order.
BR_HUD_PUMP = 3

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_FIGHT = 0                  ; the only one
