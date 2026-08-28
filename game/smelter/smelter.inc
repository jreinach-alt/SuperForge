; =============================================================================
; smelter.inc — the rail's geometry + tuning
; =============================================================================
; Joypad bit masks as SHIFTS, not hex. $4218's word layout is B=bit 15 ...
; R=bit 4; `no_literals` refuses the hex forms and the gate is right — $1000
; lands inside a claim and nothing in the token distinguishes a hardware bit
; from an address.
JOY_B     = 1 << 15
JOY_START = 1 << 12

; The animation's rate, in PHASES per frame, in the 8.8 unit TS_STEP takes.
; $0060 is 0.375 phases/frame, so the 64-phase loop closes in ~171 NTSC frames
; — about 2.8 s. A plate on the slowest harmonic therefore takes 2.8 s to rise
; and fall once and the fastest takes ~0.95 s, which is the range a foundry
; hoist actually moves in. Faster reads as vibration; slower stops reading as
; motion at all.
;
; ITS DIMENSION IS A VELOCITY, which is why one TS_STEP is the whole of the
; region arm: phases/frame carries exactly one factor of the frame ratio r and
; TS_STEP applies exactly one. A rail whose motion ACCELERATED would need a
; second constant scaled by r^2 (game/jumper/state.toml spells that case).
; There is no such number here.
SMT_PHASE_BASE = $0060

; BG3 2bpp tile attr, TITLE SCENE ONLY: palette 7 (bg_text's claim pins CGRAM
; words 28..31), priority set. With BGMODE's BG3-priority bit also set, a BG3
; tile carrying it sits ABOVE BG1 and BG2 — a legible line of text over the
; plates.
;
; THERE IS NO SUCH CONSTANT FOR `works`, and its absence is the rail: in mode 2
; BG3 is not a layer, so it has no tiles, no palette and no priority. The words
; the PPU reads out of its map are scroll offsets.
SMT_TXT_ATTR = (7 << 10) | (1 << 13)

; =============================================================================
; THE KNIGHT
; =============================================================================
; The pad. $4218's word layout is B = bit 15 ... R = bit 4; JOY_B and JOY_START
; are above.
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9

; The screen's width, as a SHIFT rather than as 256. `no_literals` reads an
; operand's numeric tokens and cannot tell a screen dimension from an address;
; building the constant out of a shift keeps the arithmetic visible AND the
; gate satisfied, which is `tick_scale`'s own note about TS_ONE.
SMT_SCREEN_W = 1 << 8

; The run, in px per frame — a RATE, scaled by one factor of the region ratio
; through TS_STEP. This is still the one number to reach for when tuning how
; the rail feels.
SMT_KN_SPEED = 2

; THE KNIGHT'S VERTICAL UNIT IS 9.7, NOT 8.8, AND THE SEVENTH BIT IS THE
; REASON. His Y has to hold both ends of a jump: the highest plate's top is
; screen row 11 and the apex is 50 px above his standing height, so Y goes
; genuinely NEGATIVE — while a miss drops him past row 232 on the way out of
; the world. In 8.8 those two are the same bit pattern (row 232 is $E8.., and
; so is row -24), so no test can tell "above the screen" from "below the
; world": the first build read row 236 as negative, skipped the kill, and let
; him wrap around to the top of the screen instead of respawning. One bit
; moved from the fraction to the row settles it — 9.7 spans -256..+255 whole
; rows, which covers both ends with the sign intact, and 1/128 px is finer
; than anything this rail's velocities need.
;
; Every conversion is written against SMT_KN_FRAC rather than as a shift by a
; typed number, so the two directions cannot drift apart.
SMT_KN_FRAC  = 7
SMT_KN_ONE_PX = 1 << SMT_KN_FRAC

; Gravity, in 9.7 velocity per frame — a per-frame-SQUARED quantity, so it
; takes TWO factors of the ratio and works.asm is where that arithmetic is
; spelled. 1/4 px per frame per frame.
SMT_KN_GRAVITY = SMT_KN_ONE_PX / 4

; The take-off, 9.7 px per frame. WITH THE GRAVITY ABOVE THIS IS THE GAME:
; apex = v^2 / 2g = 25 / 0.5 = 50 px, over 40 frames of flight, which at the
; run speed carries 80 px horizontally. The widest gap between two plates is
; 4 columns = 32 px, so a jump clears any of them comfortably — and 50 px of
; apex is LESS than the 80 px spread between the highest and lowest plate, so
; reaching the top one means waiting for it to come down. That is the mechanic
; the moving plates buy, and it is a consequence of these two numbers rather
; than of any code.
; MEASURED AGAINST THE SLOT PITCH, not chosen for feel. Flight is 2*v/g
; frames and the run covers 2 px of each, so the horizontal reach is 4*v/g:
; at v = 5 that is 80 px against a 64 px pitch, and a jump from anywhere on a
; plate OVERSHOOTS THE NEXT ONE — traced on the binary, where the knight left
; slot 0, sailed over slots 1 and 2 with his centre a pixel past each, and
; landed in the melt having touched nothing. At v = 4 the reach is 64 px,
; exactly the pitch, so a jump lands on the neighbour from the middle of the
; plate and the margin is symmetric. The apex drops to 32 px with it, which
; LEAVES THE MECHANIC INTACT: screen 3's slots travel 92-116 px, still well
; past a jump, so the far side is still crossed by waiting rather than by
; jumping higher.
SMT_KN_JUMP_VEL = 4 * SMT_KN_ONE_PX
SMT_KN_NEG_JUMP_VEL = (1 << 16) - SMT_KN_JUMP_VEL

; Terminal fall, 9.7 px per frame. Bounded by the landing window below: a fall
; faster than the window is wide can pass through a plate in one frame.
SMT_KN_MAX_FALL = 6 * SMT_KN_ONE_PX

; THE LANDING WINDOW, in whole px, and it is sized by TWO motions rather than
; one. The knight falls at up to SMT_KN_MAX_FALL a frame and THE PLATE MOVES
; TOO — the fastest harmonic is 3 cycles of +/-40 px over the 64-phase loop at
; 0.375 phases a frame, which peaks near 4 px a frame — so the feet and the
; metal can close on each other from both sides. 12 covers the sum with margin,
; and the snap on landing is what keeps the overshoot invisible.
SMT_KN_LAND_WIN = 12
.assert SMT_KN_LAND_WIN >= (SMT_KN_MAX_FALL / SMT_KN_ONE_PX), error, "the fall is faster than the landing window is wide — the knight can pass through a plate in one frame"

; $2106's low nibble names which layers the wipe pixelates. BG1 is the plates
; and BG2 the melt and the wall; BG3 is the offset TABLE in this scene and is
; not drawn at all, so it is deliberately absent — mosaicking a layer the PPU
; reads as scroll data would be meaningless even if it were harmless.
SMT_MOS_BG1 = 1 << 0
SMT_MOS_BG2 = 1 << 1

; Below this screen row he has missed everything and comes back on plate 0.
SMT_KN_KILL_Y = 232

; Where he starts. Plate 0's own column, so the spawn is a plate rather than a
; coordinate, and moving the plates moves the spawn with them.
SMT_KN_SPAWN_PLATE = 0
SMT_PLAT_SPAWN_COL = SMT_PLAT_0_COL

; THE SCROLL LATCH'S OFF-BY-ONE, which every screen-position number in this
; rail and in tests/test_smelter.py is expressed through.
;
; The vertical scroll latch reads "scanline N shows tilemap line VOFS + N",
; and the first ACTIVE scanline is 1 — so map pixel row P lands on picture row
; P - VOFS - 1. An offset-per-tile word REPLACES a column's VOFS (it does not
; add to it), so for a gated column the same relation holds with the word's
; value in place of the register: picture row = P - word - 1.
;
; That is where the picture's numbers come from. With the plate band's top at
; map pixel row SMT_PLAT_TOP_PX = 320 and the flat control's value 240, a
; plate's top edge sits at picture row 79; the crust at map row 256 with the
; melt's base 126 sits at 129.
SMT_ROW_BIAS = 1
