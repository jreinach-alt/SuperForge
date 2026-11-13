; =============================================================================
; fp.inc — the four_pads rail's geometry and vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because fp_obj.asm and the
; play scene both read it and ca65 resolves scopes backward. Pure equates: no
; code, no claims, nothing the allocator owns.

; --- JOY word bit POSITIONS (the $4218 layout, which mtap's P3/P4 words and
;     pad_btn share). Shifts, because a bare 4096 is also a plausible VRAM
;     word address and no_literals cannot know which you meant.
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11
; Every BUTTON bit (B Y Sel St U D L R A X L R = bits 15..4). Bits 3..0 are a
; standard pad's signature (always 0), so a lamp tests exactly the buttons.
JOY_ANY   = $FFF0

; --- the players ---------------------------------------------------------------
FP_PLAYERS = 4
FP_SPEED   = 2                    ; px per NTSC frame (TS_STEP's base rate)
; The play field: tokens stay inside it, so no X ever reaches 256 (X9 = 0) and
; no token can walk under the lamp row.
FP_X_MIN   = 8
FP_X_MAX   = 240
FP_Y_MIN   = 40
FP_Y_MAX   = 200

; --- the lamps -------------------------------------------------------------
FP_LAMP_Y  = 16                   ; one row along the top
FP_LAMP_X0 = 40                   ; player 1's lamp; each next one +56
FP_LAMP_DX = 56

; --- tiles (the fp_obj_chr blob's order) ------------------------------------
FP_TILE_TOKEN = 0
FP_TILE_RING  = 1
FP_TILE_LIT   = 2

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_PLAY = 0
