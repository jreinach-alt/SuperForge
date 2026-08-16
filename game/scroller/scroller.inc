; =============================================================================
; scroller.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout
; is B=bit 15 ... R=bit 4; `no_literals` refuses the hex forms and the gate is
; right — $0200 lands inside a WRAM claim and nothing in the token
; distinguishes a hardware bit from an address. The shift also says what these
; are: "bit 9 of a hardware word".
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

; The scroll step, in pixels per frame. The first number to reach for when
; tuning how this rail feels.
SCR_SPEED = 2

; The map is 32x32 8 px cells, so the world is 256 px on each axis and the
; camera wraps every 256. Derived once here so a test and the ASM cannot
; disagree about it.
SCR_WORLD_PX = 32 * 8
