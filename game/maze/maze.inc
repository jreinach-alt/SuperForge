; =============================================================================
; maze.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex: $4218's word layout
; is B=bit 15 ... R=bit 4; `no_literals` refuses the hex forms and the gate is
; right — nothing in a bare $0200 distinguishes a hardware bit from an address.
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

; The player's move step, px/frame — the first thing to tweak on this rail: it
; must stay under one 8 px tile so a single step can never cross a wall cell.
; The no-tunnel property is this constant.
MZ_SPEED = 2

; The player's spawn, in the open left chamber.
MZ_SPAWN_X = 40
MZ_SPAWN_Y = 100

; The collision flag bit the move-check tests: bit 0 = SOLID. mz_flags.bin
; gives tile 2 this bit; the probe masks the returned flag byte with it.
; this bit; the probe masks the returned flag byte with it.
MZ_FLAG_SOLID = 1 << 0

; The box probe's far-corner offset: the player box spans 8 px, so the far
; corners are +7, not +8 — a +8 probe reads the NEIGHBOURING tile and sticks
; the player to walls one pixel early (m7_dungeon's FP_FAR derives the same
; fact).
MZ_BOX_FAR = 7
