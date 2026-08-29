; mill.inc — the rail's tuning, beside the geometry the generator emits.
;
; What is HERE is what a person chose; what is in the GENERATED mil_art.inc is
; what the art is. The split is smelter's and the reason is the same: a
; constant the tools compute and a constant somebody tuned go stale for
; different reasons and should not sit in one file.

; THE PHASE'S RATE, in 8.8 phases per NTSC frame. The row table closes on
; SMIL_PHASES, so this decides how long a piston stroke and a belt lap take.
; $0060 = 0.375 phases a frame -> 64 phases in about 2.8 s.
;
; It is fed to TS_STEP, so PAL runs the same 64 rows in the same wall-clock
; time with the fraction carried between frames.
SMIL_PHASE_BASE = $0060

; The screen the picture is drawn into, for the tests' geometry.
SMIL_SCREEN_W = 256

; The pad bit the flat control reads. A BIT POSITION in the joypad word the
; input feature publishes, not an address — every rail in this tree spells its
; own, because which button a rail uses is the rail's choice.
JOY_B     = 1 << 15
JOY_UP    = 1 << 11
JOY_DOWN  = 1 << 10

; THE CAMERA'S RATE, in whole pixels a frame. Not fed to TS_STEP: this is a
; HELD-INPUT speed, so a PAL console's longer frame makes the same hold cover
; the same ground in fewer frames and the player closes the loop. The phase
; below IS scaled, because nothing holds a button to make a piston stroke.
; TICK: ok -- a rate against held input, which is its own timebase.
SMIL_CAM_STEP = 3
