; =============================================================================
; hud.inc — the rail's geometry and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because hud_obj.asm and
; the play scene both read from it and ca65 resolves scopes backward. Pure
; equates: no code, no claims, nothing the allocator owns.

; --- $4218 bit POSITIONS. Written as shifts because a bare 4096 is also a
;     plausible VRAM word address and no_literals cannot know which you meant.
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11

; --- the player --------------------------------------------------------------
; SPEED = 2 px/frame, an 8 px sprite clamped to the 256x224 screen.
HUD_SPEED  = 2
HUD_SIZE   = 8
HUD_MAX_X  = 256 - HUD_SIZE
HUD_MAX_Y  = 224 - HUD_SIZE
HUD_HOME_X = 124                 ; screen centre
HUD_HOME_Y = 108

; --- HUD reprint requests (US_DIRTY bits) ------------------------------------
; One customer, one bit. The mask shape is breaker's and shmup's; this rail has
; the single counter those two have three of, which is the whole point of it
; being the smallest thing that exercises bg_text end-to-end.
HUD_DIRTY_SCORE = 1

; --- BG3 text geometry -------------------------------------------------------
; "SCORE" sits at pixel (8, 8) — tile column 1, row 1 — and its counter at
; pixel (56, 8) = column 7, four digits wide.
HUD_ROW      = 1
HUD_LABEL_C  = 1                 ; "SCORE"
HUD_DIGITS_C = 7                 ; the four counter cells, 7..10
HUD_DIGITS_N = 4

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_PLAY = 0                   ; the only one
