; =============================================================================
; jumper.inc — the rail's geometry + feel tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex: $4218's word layout
; is B=15 Y=14 Sel=13 Start=12 Up=11 Down=10 Left=9 Right=8 A=7 X=6 L=5 R=4.
JOY_A     = 1 << 7
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

; The horizontal run step, px/frame — the third thing to tweak on this rail.
JR_SPEED = 2

; --- the physics feel, 8.8 fixed-point --------------------------------------
; The first two things to tweak: assemble-time constants, so the feel is
; retuned by editing a number and rebuilding — the rail's fourth teaching.
; Written as the 8.8 derivation (`px << 8` = whole pixels; `1 << 7` = half a pixel;
; `no_literals` refuses a bare 1152, and the shift form says what the number
; IS — a fixed-point quantity, not an address):
;   gravity  0.25 px/f^2 = $0040      fall acceleration
;   max fall 4 px/f      = $0400      terminal fall speed
;   jump vel 4.5 px/f    = $0480      take-off -> apex ~38 px in ~18 frames
JR_GRAVITY  = 1 << 6
JR_MAX_FALL = 4 << 8
JR_JUMP_VEL = (4 << 8) + (1 << 7)

; -JR_JUMP_VEL as an unsigned 16-bit word (two's complement) — the take-off
; velocity, in shift form.
JR_NEG_JUMP_VEL = (1 << 16) - JR_JUMP_VEL

; The override bounds: both speeds must stay <= 8 px/frame — the 8x8 box probe + the row-top snaps only cover an
; 8 px step. Faster falls embed in floors; faster take-offs tunnel ceilings.
.assert JR_MAX_FALL <= 8 << 8, error, "JR_MAX_FALL > 8 px/frame breaks the landing snap / no-tunnel bound"
.assert JR_JUMP_VEL <= 8 << 8, error, "JR_JUMP_VEL > 8 px/frame can tunnel through ceilings"

; --- the spawn --------------------------------------------------------------
; x=48, standing on the ground: rest y = ground row top (26 * 8 = 208) minus
; the 8 px box = 200. The enter code writes pyf = JR_SPAWN_Y * 256 (8.8).
JR_SPAWN_X = 48
JR_SPAWN_Y = 200
