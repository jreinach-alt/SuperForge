; =============================================================================
; sprg.inc — the sprite_game rail's geometry and vocabulary
; =============================================================================
; Top-level (included by main.asm before the scenes) because sprg_obj.asm and
; the play scene both read from it and ca65 resolves scopes backward. Pure
; equates: no code, no claims, nothing the allocator owns.

; --- $4218 bit POSITIONS. Written as shifts because a bare 4096 is also a
;     plausible VRAM word address and no_literals cannot know which you meant.
;     This rail reads ONLY the d-pad — no A/B/X/Y.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11

; --- the actors --------------------------------------------------------------
; SPEED = 2 px/frame, both boxes 8x8, player spawn at (120, 100). NO CLAMP —
; the four move blocks are bare adc/sbc, so positions wrap as unsigned 16-bit
; words and the OBJ feature derives X9 from bit 8 every frame instead of
; assuming it clear. Walking off an edge and reappearing is the rail's
; behaviour, not a defect to bound away.
SPRG_SPEED  = 2
SPRG_SIZE   = 8
SPRG_HOME_X = 120
SPRG_HOME_Y = 100

; --- the dot's preset cycle --------------------------------------------------
; Four (x, y) spots, advanced +1 with wrap on each catch. Declaring the COUNT
; and deriving the wrap mask from it keeps the two from drifting apart.
SPRG_PRESETS = 4

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_PLAY = 0                   ; the only one
