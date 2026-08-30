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

; The pad bits this rail reads. A BIT POSITION in the joypad word the input
; feature publishes, not an address — every rail in this tree spells its own,
; because which button a rail uses is the rail's choice.
;
; B AND Y ARE TWO DIFFERENT CONTROLS AND THEY WERE ONE BUTTON FOR A WHILE.
; B originally held the FLAT CONTROL — the blob's last row, every column at
; rest with every enable and axis bit still set, which is what makes the flat
; frame a control rather than a second unexplained state. When the lift was
; built B was given to holding the RIDE so a still could be taken anywhere in
; it, and the flat control silently became unreachable: nothing wrote
; ES_MIL_FLATSEL any more, while hall.asm still described the behaviour. Found
; by tests/test_mill.py, which asserted the control and could not select it.
; Y now holds the flat row; B still holds the ride.
JOY_B     = 1 << 15
JOY_Y     = 1 << 14
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

; How far UP the art sits inside the glass. The pack frames Arthur with eleven
; transparent rows above the helmet, so his drawn content does not start at the
; top of his 32x32 box; this is what lands his head near the TOP of the port
; rather than halfway down it. Expressed as a RAISE and subtracted, for the
; same reason the other biases here are.
;
; Raised from 4 to 9 when the port was narrowed: at 4 his head sat nine rows
; below the glass and the ten rows the shell cut were most of him, so the
; window showed a sliver. Measured against the sprite's own CHR read out of
; VRAM — see tests/test_mill.py::rider_ink, which is also what the numbers
; below are checked by.
SMIL_RIDER_RAISE = 9

; THE PARK ROW IS A FUNCTION OF THE SPRITE'S SIZE, and 240 is not it.
;
; OAM Y is 8 bits and the PPU wraps at 256, so a sprite parked at 240 occupies
; rows 240..255 AND 0..(size-17). At 16x16 that is nothing — which is why
; oam_park_all's 240 is correct: it clears the hi table in the same pass, so
; every sprite it parks is SMALL. This rider sets the size bit to LARGE, and
; at 32x32 a park at 240 wrapped SIXTEEN ROWS OF HIM ONTO THE TOP OF THE
; SCREEN — visible in the middle of the shaft after the lift had left it.
;
; A 32x32 sprite therefore has exactly ONE park row: 224. Below it and part of
; the sprite is on screen; above it and part of it wraps.
SMIL_PARK_Y = 256 - SMIL_RIDER_BOX

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

; --- the shaft's light ----------------------------------------------------
; What the blend ADDS to bg2 inside the colour window, per channel, 0..31. A
; cold wash and a faint lift in green: red left at 0 so the shaft reads as lit
; from somewhere other than the melt below it, which is the only warm light in
; the picture. Halved by the blend, so these are twice what lands.
SMIL_TINT_R = 0
SMIL_TINT_G = 4
SMIL_TINT_B = 12

; --- the lobby ------------------------------------------------------------
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8

SMIL_DOOR_BAYS = 2
SMIL_RIDER_GROUP = 4          ; 32x32 cells to an OBJ name-table group

SMIL_WALK_STEP = 2

; HIS BOX IS THE DECK LINE, and once there are lift doors that is structural
; rather than cosmetic. The pack frames Arthur with four transparent rows under
; the feet, so his drawn content ends at row 28 of 32 and this lands those feet
; ON the deck. It also lands his BOX inside the doorway, whose floor is the same
; deck — and a player sunk even a little into it has that much of himself
; hanging below doors that stop where the doorway does. mil_obj asserts the fit.
SMIL_WALK_Y    = SMIL_LOBBY_FLOOR * 8 - SMIL_RIDER_BOX
SMIL_WALK_MIN  = 8
SMIL_WALK_MAX  = 256 - SMIL_RIDER_BOX - 8

; The leaves sit at the opening's top row.
SMIL_DOOR_Y = SMIL_DOOR_TOP * 8

SMIL_SPAWN_X    = 120         ; the player, between the two bays
SMIL_DOOR_REACH = 48          ; how near a bay he must stand for it to open.
                              ;   The OPENING is 64 px wide, so half of it is
                              ;   32 and anything less than that leaves places
                              ;   inside the doorway where the doors are shut.
                              ;   48 is the half-width plus a stride of
                              ;   approach, and the two bays' centres are 112
                              ;   apart, so the reaches still do not overlap
SMIL_DOOR_STEP  = 2           ; a leaf's travel a frame

; --- the ride, and the four things the player can be doing in the lobby -----
; The travel is still the door's own state — a leaf caught half-way reverses
; from where it is. These say which way it is being DRIVEN and who has the
; controls, which is a different question and the reason they are separate.
SMIL_BOARD_FREE   = 0         ; he walks; a bay opens because he is near it
SMIL_BOARD_IN     = 1         ; he is walking into a bay that is held open
SMIL_BOARD_ABOARD = 2         ; he is inside; the doors shut OVER him (OAM
                              ;   order, measured — see mil_obj.asm) and the
                              ;   scene switches when they are shut
SMIL_BOARD_OUT    = 3         ; he has just arrived; the doors part to reveal
                              ;   him, and he is free when they are open
SMIL_BOARD_DEST   = SMIL_DOOR_W * 4 - SMIL_RIDER_BOX / 2   ; ...a bay's left
                              ; edge to the px that centres him in it

; --- the lift, when he is not on it -----------------------------------------
; A LIFT THAT NEVER LEAVES IS A BRIDGE. The car parks on the deck and its four
; columns are the only floor across that shaft — so if it stays parked forever,
; `mil_solid`'s reading of the car's displacement can never answer anything but
; "floor", and the dynamic half of this rail's collision is code that cannot
; run. That is not a hypothesis: the falsification harness reported it, by
; taking the car test OUT and finding every case still green.
;
; So the car behaves like a lift: it comes when he is near the shaft and
; withdraws when he is not, and the hole in the floor opens and shuts with it.
; ONE RULE, POSITION-DRIVEN, which is the same shape as the lobby's doors —
; the travel is the state and there is no timer to keep in step with anything.
SMIL_LIFT_REACH = 56          ; how near the shaft's centre he must be. Wide
                              ;   enough that it is down before he can reach
                              ;   its columns, so he never steps onto a hole
SMIL_CAR_AWAY   = 64          ; how far up it withdraws. Well short of
                              ;   SMIL_CAR_TOP, which is what ends the ride —
                              ;   a car that withdrew that far would take an
                              ;   empty lift to the lobby
SMIL_CAR_CALL   = 3           ; ...and how fast it answers, in pixels a frame
; TICK: ok -- a rate against a HELD position, not a count of frames: he decides
;   how long it takes by where he stands, exactly as the lobby's doors do.
