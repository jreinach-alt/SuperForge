; =============================================================================
; cf.inc — the camera_follow rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout
; is B=bit 15 ... R=bit 4; `no_literals` refuses the hex forms and the gate is
; right — $0200 lands inside a WRAM claim and nothing in the token
; distinguishes a hardware bit from an address.
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

; The player's move step, in pixels per frame — the second thing to tweak on
; this rail.
CF_SPEED = 2

; The WORLD, in pixels — four screens (2 wide x 2 tall). The FIRST thing to
; tweak: grow them and the camera scrolls further before it clamps; shrink them
; toward 256/224 and the camera barely moves.
CF_WORLD_W = 512
CF_WORLD_H = 448

; The screen, and the half-screen the follow subtracts to centre the player.
; (256x224 is the SNES picture; 128/112 are its halves.)
CF_SCREEN_W = 256
CF_SCREEN_H = 224
CF_HALF_W   = CF_SCREEN_W / 2
CF_HALF_H   = CF_SCREEN_H / 2

; Derived bounds — every clamp in the scene compares against one of these.
; Deriving them HERE, once, is what keeps the ASM and the tests unable to
; disagree about where the world ends.
CF_PLAYER_MAX_X = CF_WORLD_W - 8         ; 504: the 8x8 player's left-edge max
CF_PLAYER_MAX_Y = CF_WORLD_H - 8         ; 440
CF_CAM_MAX_X    = CF_WORLD_W - CF_SCREEN_W   ; 256: cam_x clamps here
CF_CAM_MAX_Y    = CF_WORLD_H - CF_SCREEN_H   ; 224: cam_y clamps here

; Where the player boots: the world centre. The follow then
; puts the camera at (128, 112) and the sprite at screen (128, 112).
CF_BOOT_X = CF_WORLD_W / 2               ; 256
CF_BOOT_Y = CF_WORLD_H / 2               ; 224
