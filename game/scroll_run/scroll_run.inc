; =============================================================================
; scroll_run.inc — the rail's geometry + feel tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex: $4218's word layout
; is B=15 Y=14 Sel=13 Start=12 Up=11 Down=10 Left=9 Right=8 A=7 X=6 L=5 R=4.
JOY_A     = 1 << 7
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

; The run step, px/frame. The first number to reach for when tuning how this
; rail feels.
SR_SPEED = 2

; --- the physics feel, 8.8 fixed-point --------------------------------------
; Written as the 8.8 derivation (`px << 8` = whole pixels; `1 << 7` = half a
; pixel; `no_literals` refuses a bare 1152, and the shift form says what the
; number IS):
;   gravity  0.25 px/f^2 = $0040      fall acceleration
;   max fall 4 px/f      = $0400      terminal fall speed
;   jump vel 4.5 px/f    = $0480      take-off -> apex ~38 px in ~18 frames
; THE JUMP IS FIXED-HEIGHT: one edge-triggered take-off, and no cut velocity
; at all. Releasing A early does nothing here — see platformer for the
; hold-for-higher variant, which is a different feel and a different rail.
SR_GRAVITY  = 1 << 6
SR_MAX_FALL = 4 << 8
SR_JUMP_VEL = (4 << 8) + (1 << 7)

; -SR_JUMP_VEL as an unsigned 16-bit word (two's complement) — the take-off
; velocity the jump writes, in shift form for the same reason.
SR_NEG_JUMP_VEL = (1 << 16) - SR_JUMP_VEL

; BOTH SPEEDS MUST STAY <= 8 px/frame: the 8x8 box probe + the row-top snaps
; only cover an 8 px step. Faster falls embed in floors; faster take-offs
; tunnel ceilings.
.assert SR_MAX_FALL <= 8 << 8, error, "SR_MAX_FALL > 8 px/frame breaks the landing snap / no-tunnel bound"
.assert SR_JUMP_VEL <= 8 << 8, error, "SR_JUMP_VEL > 8 px/frame can tunnel through ceilings"

; --- the world -------------------------------------------------------------
; 512 px: two 256px hardware pages, and the seam is at world x = 256 (tile
; column 32). Derived as shifts off the col_map binding's own log2 so the
; world size has ONE authoring point (the binding in scenes/run.asm asserts
; the blob agrees).
SR_WORLD_W      = 1 << 9                     ; 512 px
SR_PLAYER_MAX_X = SR_WORLD_W - 8             ; the player clamp: one box short
SR_CAM_MAX_X    = SR_WORLD_W - 256           ; the right camera clamp = 256
SR_HALF_W       = 1 << 7                     ; the follow's half-screen anchor

; --- the spawn --------------------------------------------------------------
; x=16, standing on the floor: rest y = floor row top (26 * 8 = 208) minus
; the 8 px box = 200. The enter code writes pyf = SR_SPAWN_Y * 256 (8.8).
SR_SPAWN_X = 16
SR_SPAWN_Y = 200

; --- the GOAL print ---------------------------------------------------------
; Pixel (112, 96) on the 8px text grid = BG3 tilemap cell (14, 12); four
; glyphs — exactly bg_text's TXT_Q_MAX, so the win staging is one run.
SR_GOAL_ROW = 12
SR_GOAL_COL = 14

; BG3 2bpp tile attr: palette 7 (bg_text's claim pins CGRAM words 28..31),
; priority set so the GOAL line draws over the terrain where they overlap
; (hud_game's TXT_ATTR, same derivation).
SR_TXT_ATTR = (7 << 10) | (1 << 13)
