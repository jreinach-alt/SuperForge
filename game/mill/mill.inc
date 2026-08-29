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

; --- the rider's staging geometry -----------------------------------------
; The visible band, BIASED by the sprite box so one unsigned compare covers
; both ends. The car climbs off the TOP and its glass row goes negative; row +
; box is either inside this span (partly on screen) or has wrapped enormous
; (gone). A signed pair of tests would want negative immediates, and a negative
; immediate in ca65 is a hex mask, which is a raw address operand.
SMIL_RIDER_VIS_SPAN = 224 + SMIL_RIDER_BOX

; ...and a nudge right, so he stands centred in the glass rather than against
; its left mullion. The pack does not centre Arthur in his 32x32 cell.
SMIL_RIDER_DX = 3

; How far UP the art sits inside the glass. The pack frames Arthur with
; transparent rows under the feet, so his drawn content does not start at the
; top of his 32x32 box; this is what lands his head in the window rather than
; above it. Expressed as a RAISE and subtracted, for the same reason.
SMIL_RIDER_RAISE = 4

; The documented park: Y >= 240 puts a sprite off the bottom of a 224-line
; picture whatever its size.
SMIL_PARK_Y = 240

; --- the ride -------------------------------------------------------------
; The car's rate, in whole pixels a frame, and how far it goes. SMIL_CAR_TOP is
; past the world's height on purpose: the camera clamps at 0 partway up, and
; the remainder is the car climbing out through the top of the picture.
;
; TICK: ok -- a cutscene's own rate. It is not fed to TS_STEP because the
;   sequence is a PERFORMANCE with a fixed shape, and scaling it would make a
;   PAL run cover the same pixels in the same wall-clock time by moving in
;   coarser steps, which on a 3 px/frame climb is visible judder for no gain.
SMIL_CAR_STEP = 2
SMIL_CAR_TOP  = 400

; ...and a beat at the bottom before it moves, so the sequence OPENS on the
; forge floor rather than on a lift already halfway up it. Counted in the
; rail's own phase, which the scaler has already expressed against the tick,
; rather than in frames.
; TICK: ok -- a threshold on the accumulated PHASE, not a frame count.
SMIL_CAR_WAIT = 24
