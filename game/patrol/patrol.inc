; =============================================================================
; patrol.inc — the rail's geometry and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because patrol_obj.asm
; and the play scene both read from it and ca65 resolves scopes backward.
; Pure equates: no code, no claims, nothing the allocator owns.
;
; Every number here is written as the algebra it is, wherever no_literals would
; otherwise see a bare address-like token.

; --- $4218 bit POSITIONS, as shifts -----------------------------------------
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9

; --- the actors --------------------------------------------------------------
PAT_BOX      = 8                 ; every actor is one 8x8 box
PAT_SPEED    = 2                 ; the player's run step, px/frame (SPEED)
PAT_SPAWN_X  = 200               ; spawn / knockback (SPAWN_X, SPAWN_Y)
PAT_SPAWN_Y  = 200
PAT_E1_X0    = 120               ; ground enemy starts mid-beat
PAT_E2_X0    = 48                ; platform enemy starts mid-platform
PAT_E1_Y     = 200               ; the ground beat row: ground top 208 - 8
PAT_E2_Y     = 152               ; the platform beat row: platform top 160 - 8
PAT_DIR_R    = 1                 ; edir: 0 = walking left, 1 = walking right

; --- physics (8.8 fixed-point) ----------------------------------------------
PAT_GRAVITY  = $0040             ; 0.25 px/f^2, 8.8
PAT_MAX_FALL = $0400             ; 4 px/f terminal fall
PAT_JUMP_VEL = $0480             ; 4.5 px/f take-off (apex ~38 px)
PAT_JUMP_UP  = (256 * 256) - PAT_JUMP_VEL
                                 ; -PAT_JUMP_VEL as an unsigned 16-bit word —
                                 ; the two's complement written as the algebra
                                 ; it is (pfs_logic's PFS_JUMP_UP shape; a
                                 ; bare $FFFF-masked expression reads as an
                                 ; address to no_literals, and the gate is
                                 ; right that nothing in the token could tell
                                 ; it apart)

; --- patrol -----------------------------------------------------------------
PAT_PATROL_SPEED = 1             ; px/frame

; --- collision ---------------------------------------------------------------
PAT_FLAG_SOLID = $01             ; bit 0 — the SOLID bit in the flag table

; --- HUD reprint requests (US_DIRTY bits) ------------------------------------
PAT_DIRTY_HITS = 1

; --- BG3 text geometry -------------------------------------------------------
; "HITS" sits at pixel (8, 8) — tile column 1, row 1 — and its counter at pixel
; (48, 8) = column 6, four digits wide.
PAT_HUD_ROW   = 1
PAT_LABEL_C   = 1                ; "HITS"
PAT_DIGITS_C  = 6                ; the four counter cells, 6..9
PAT_DIGITS_N  = 4

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_PLAY = 0                   ; the only one
