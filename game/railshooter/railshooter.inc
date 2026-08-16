; =============================================================================
; railshooter.inc — the rail's vocabulary: tuning, pool layout, tier table
; =============================================================================
; Constants only — no addresses. Every address in this rail comes from the
; allocator's emitted map; `allocator/no_literals.py` refuses anything else.
; What lives here is the game's own numbers: speeds, depths, the byte offsets
; INSIDE the rs_actors claim, and the OAM window shape.
;
; THE SHAPE OF THESE NUMBERS IS THE DESIGN. The ship is fixed and flies itself
; around a repeating S-curve; the player owns only a world-anchored aiming
; reticle. So there is nothing here describing a strafing player — every number
; below describes a rail that drives itself, or the one thing the pad aims.

; --- the frame ---------------------------------------------------------------
; The seam is pose_rom's band top: the blob is generated at --lines 180
; (Makefile), so the Mode 7 floor occupies scanlines 44..223 and the horizon IS
; the split_band seam. The projection LUT is baked to the same number
; (tools/gen_railshooter_assets.py HORIZON_Y) — the .assert in rs_obj.asm keeps
; the two from drifting apart.
RS_LINES      = 224
RS_SKY_LINES  = 44                  ; the top band: Mode 1, sky_band's BG2 ramp
; mode7_persp's binding symbol, and it is the SAME number: that feature derives
; PERSP_LINES = 224 - HUD_LINES and the generated pose blobs carry exactly that
; many rows, so the seam, the pose generator's --lines and the projection LUT's
; horizon are one number wearing three names. The .assert in main.asm is what
; keeps them from drifting apart.
HUD_LINES     = RS_SKY_LINES
RS_PERSP_LINES = RS_LINES - RS_SKY_LINES
; The visible width, as a SHIFT: `no_literals` refuses a bare 256 (it is an
; address-shaped token and nothing distinguishes a screen width from a WRAM
; offset), and the shift also says what the number is — 2^8 px, one full OAM
; x byte plus the ninth bit.
RS_SCREEN_W    = 1 << 8
RS_SCREEN_HALF = RS_SCREEN_W / 2    ; the centre column the pinhole maps to

; =============================================================================
; THE S-CURVE — a TRANSLATION of the camera, never a rotation of the plane
; =============================================================================
; The Mode 7 camera origin (M7X/M7Y) is a free per-frame CPU-written VBlank
; shadow over a 16-bit world position that already wraps on the plane's period
; (mode7_persp/feature.toml:36,50). The POSE table is the quantised thing —
; 64 headings, so the smallest turn the plane can make is 5.6 degrees — and a
; curve steered through it reads as binary rather than as a bend. So the
; heading is PINNED AT 0 and the curve is expressed as
;
;     cam_x = RS_CENTRE + rs_path[(dist >> RS_PATH_SHIFT) & RS_PATH_MASK]
;
; ONE ODOMETER DRIVES EVERYTHING. `US_DIST` counts +1 per frame; the path index,
; every spawn schedule and every actor's arrival phase come off it, so the curve
; and the field it bends around are phase-locked by construction rather than by
; tuning.
;
; ONE TABLE ENTRY PER FRAME, and RS_PATH_SHIFT = 0 is the whole of it. Baking
; 64 entries and holding each for four frames does not work: `cam_x` lands in
; BOTH M7X and the floor's HOFS, so the entire Mode 7 plane stands still for
; three frames and then jumps up to 21 screen px sideways, forever — measured
; on the floor's own major grid line at screen row 200 as -21.0/0/0/0. That is
; the same defect 8.8 sub-pixel accumulation exists to keep off the FORWARD
; axis, at four times the step. Baking the period at frame resolution costs
; +384 B of ROM, makes rs_path_at CHEAPER (the shift loop is gone) and leaves
; the sine itself untouched.
RS_PATH_N       = 256               ; entries in the baked table (rs_path.bin)
RS_PATH_MASK    = RS_PATH_N - 1
RS_PATH_SHIFT   = 0                 ; frames per entry = 1 -> S period = 256
RS_PATH_PERIOD  = RS_PATH_N << RS_PATH_SHIFT
RS_PATH_HALF    = RS_PATH_PERIOD / 2        ; one bend
; The sine's DERIVATIVE is the same table read a quarter period along, which is
; what lets the ship's bank LEAD the swing with no extra state and no table.
RS_PATH_QUARTER = RS_PATH_N / 4

; --- the rail driver ---------------------------------------------------------
; 1.5 world px/frame, carried in 8.8. At 6 px/frame (360 px/sec) the grid
; strobes past faster than an approaching hazard can be read; 1.5 is slow
; enough to track a hazard for seconds, and the fraction is what keeps it from
; reading as steppy. 128 frames (one bend) x 1.5 = 192 px = exactly SIX grid
; periods, so the floor's forward phase repeats at every half-S sample — which
; is what lets a test compare two S phases as a pure lateral shift.
RS_RAIL_SPEED_88 = 384              ; 1.5 in 8.8
RS_ADV_FRAC_MASK = $00FF            ; the accumulator's fractional part

; --- the ship ----------------------------------------------------------------
; FIXED. It does not respond to the pad at all, and its screen x
; never changes — only its CHR frame does, so the bank is a lean and not a
; slide. The lean is driven by the PATH's slope, so a pilot sees the ship being
; flown around the curve.
RS_SHIP_X      = 128 - 16           ; a centred 32x32 sprite's screen X
RS_SHIP_Y      = 150                ; planted low, well below the horizon
RS_LEAN_NONE   = 0
RS_LEAN_LEFT   = 1
RS_LEAN_RIGHT  = 2
RS_BANK_DEAD   = 40                 ; |slope| under this reads as straight

; --- the depth axis ----------------------------------------------------------
; Each actor carries a forward depth z in WORLD PIXELS ahead of the camera,
; decremented by a constant every frame. At a step of 12 an actor crosses the
; whole range in ~52 frames, which is not long enough to aim at; at 4 it takes
; 160 frames — 2.7 seconds — so it is trackable rather than instantaneous.
RS_Z_FAR      = 640                 ; the far edge (== the LUT's Z_FAR)
RS_Z_NEAR     = 16                  ; "at the camera"
RS_OBS_STEP   = 4                   ; z closed per frame
; z falls RS_OBS_STEP per frame while `dist` rises 1 per frame, so
; `dist * RS_OBS_STEP + z` is INVARIANT for an actor across its whole flight.
; RS_LEAD is that invariant expressed in FRAMES: an actor spawned now at
; z = RS_Z_FAR arrives exactly RS_LEAD frames from now, so the path index at
; (dist + RS_LEAD) is where the camera WILL BE when it gets here. That is what
; makes a lane offset a real "will this hit me" number instead of a guess.
RS_LEAD       = RS_Z_FAR / RS_OBS_STEP      ; 160 frames

; --- the hazard field --------------------------------------------------------
; Spawned on a SCHEDULE and freed on arrival, not recycled forever: the pool
; genuinely allocates and frees on both sides, which is the property the rail
; exists to exercise — a field that never empties never tests a free.
RS_OBS_N      = 4                   ; pooled hazards == the OAM window width
RS_OBS_GAP    = 40                  ; frames between spawns (4 alive at 160/40)
RS_OBS_HIT_Z  = 8                   ; at/below this the hazard has ARRIVED
RS_SHIP_HIT_X = 40                  ; |wx - cam_x| that counts as a collision
RS_LANES      = 4                   ; lateral offsets around the path

; --- the pylons: what the S-curve bends around -------------------------------
; One per bend, placed on the OPPOSITE side of the rail's centre at twice the
; path's amplitude — so the ship visibly swings AROUND it rather than past it.
; Drawn as a three-tall stack of one tier frame.
;
; THE STACK RIDES AN 8-BIT WRAP, ON A NINE-SCANLINE MARGIN. Segment
; k's top is `sy - (k+1)*step`, so the top of a near-tier column is 96 px above
; the ground point and goes NEGATIVE; `rs_put` stores the low byte and the PPU
; renders it wrapped. That is arithmetically CORRECT while the true top is
; > -32 — the wrapped part landing on scanlines 0..k is exactly the part of the
; column at true y 0..k, which is why the column reads as continuous running off
; the top of the frame rather than as a detached block.
;
; The margin: the smallest wrapping segment y observed is 233, and a 32-tall
; sprite starts painting at the BOTTOM of the screen once y <= 223. NINE
; scanlines. Raising RS_PYL_STACK, or shifting the near-band `sy` down ~10 px,
; puts a 32-px slab of pylon at the bottom of the frame with nothing above it.
; `test_no_pylon_segment_is_emitted_into_the_bottom_of_the_screen` refuses any
; emitted segment with y in [192, 223]; read it before changing either number.
RS_PYL_N      = 2
RS_PYL_GAP    = RS_PATH_HALF        ; one per bend
RS_PYL_STACK  = 3                   ; sprites in the column
RS_PYL_H32    = 32                  ; stack step at the two large tiers
RS_PYL_H16    = 16                  ; ...and at the two small ones

; --- tier hysteresis ---------------------------------------------------------
; An actor's z is monotone DECREASING as it approaches, so its tier only ever
; GROWS (3 -> 0). A tier advances only when z falls RS_TIER_HYST BELOW the
; threshold, which is what stops a boundary-sitting actor flickering between
; two pre-drawn sizes.
RS_TIER_T0    = 80                  ; == the LUT's TIER_T0 (asserted in rs_obj)
RS_TIER_T1    = 160
RS_TIER_T2    = 360
RS_TIER_HYST  = 12
RS_TIER_FAR   = 3                   ; the tier a spawn starts at

; --- the reticle: the ONLY thing the player controls -------------------------
; A point on the GROUND PLANE in world coordinates, projected through the same
; pinhole as every hazard. That is what makes the ship's lateral swing DRAG it
; across the screen as an emergent consequence of the projection rather than a
; faked screen-space nudge. LEFT/RIGHT move its world x;
; UP/DOWN move its forward depth, because a one-axis reticle could only ever
; reach hazards at one depth.
RS_RET_Z_INIT = 60                  ; screen y 116 — mid-screen, tier-0 country
RS_RET_Z_MIN  = 30
RS_RET_Z_MAX  = 300
RS_RET_Z_STEP = 3                   ; z/frame on UP/DOWN
RS_RET_SPEED  = 6                   ; world px/frame on LEFT/RIGHT
; MEASURED, not guessed. At RS_RET_Z_INIT the pinhole's lateral gain is
; FOCAL/z = 44/60 = 0.73 screen px per world px. The S-curve's steepest bend
; moves the camera ~3.5 world px/frame, so it drags the aim point ~2.6 screen
; px/frame; at 3 world px/frame the pad could correct only 2.2 and the pilot
; LOST GROUND through every bend. Six gives 4.4 -- a comfortable ~1.7x
; authority over the worst drag, so aiming is correcting back onto a target
; rather than a fight the pad cannot win.
RS_RET_TOL    = 6                   ; screen px of forgiveness on the box test

; --- firing ------------------------------------------------------------------
; A press does TWO things. It runs a SCREEN-SPACE hitscan (§ rs_fire) against
; the same projection cache the OAM emit uses, and it spawns a tracer for feel.
; The hitscan is screen-space and not world-space because a fixed world
; tolerance cannot match a sprite's footprint across depth: 32 screen px is 44
; world px at z=60 and 221 at z=300. Matching what the player SEES at every
; depth is the only tolerance that behaves the same at both ends of the range.
RS_BUL_N      = 3
RS_BUL_SPEED  = 20                  ; z/frame — recedes toward the horizon
RS_BUL_SPAWN  = 40                  ; born level with the ship, not under it
RS_BUL_MAX    = RS_Z_FAR - 8        ; freed once it reaches ~the horizon

; --- the kill flash: what makes a kill not resemble a miss -------------------
RS_BURST_FRAMES = 14                ; how long the flash is held
RS_BURST_SWAP   = 7                 ; frame A for the first half, B for the rest
RS_BURST_OFF    = 8                 ; centre the 32x32 flash on a 16x16 target

; --- what the pilot is told about themselves ---------------------------------
RS_LIVES_N      = 5                 ; five discrete segments
RS_FAIL_FRAMES  = 120               ; the fail state, then a self-restart
RS_SCORE_DIGITS = 4
RS_SCORE_MAX    = 9999
; The HUD's OAM claim is twelve slots; four are digits and five are segments, so
; three are parked spares that round the whole window to seven hi-table bytes.
RS_HUD_PAD      = 3

; --- the HUD's screen placement ----------------------------------------------
; Wholly inside the sky band (y 8..23). It DOES share scanlines with the play
; band -- a pylon's stack stands 96 px above its ground point and crosses these
; lines on about a tenth of frames -- so the two are budgeted TOGETHER, at a
; measured worst case of 22 slivers of the hardware's 34, and the HUD takes the
; lower OAM slots so it draws in front.
RS_HUD_Y      = 8
RS_LIFE_X0    = 16
RS_LIFE_DX    = 16
RS_SCORE_X0   = 176
RS_SCORE_DX   = 16

; --- the pools: byte offsets INSIDE the rs_actors wram claim -----------------
; Three pools, one region, a fixed 16-byte stride per field (8 slots x 2 B) so a
; field is (pool_base + field + slot*2). Game vocabulary, which is why it lives
; here and not in rs_obj/feature.toml.
RS_SLOT_STRIDE = 16                 ; 8 slots x 2 B — the per-FIELD array size

; The field offsets are RELATIVE to a pool's base, and every pool uses the same
; four, which is what lets ONE generic per-actor loop serve the hazards and the
; pylons: pass the pool's base in the cursor and the field offsets never change.
RS_F_ALIVE    = 0 * RS_SLOT_STRIDE
RS_F_WX       = 1 * RS_SLOT_STRIDE
RS_F_Z        = 2 * RS_SLOT_STRIDE
RS_F_TIER     = 3 * RS_SLOT_STRIDE

; A "no hit" sentinel for the hitscan, spelled as a shift because no_literals
; refuses a bare address-shaped hex word.
RS_NO_HIT     = (1 << 16) - 1

RS_OBS_BASE   = 0
RS_OBS_ALIVE  = RS_OBS_BASE + 0 * RS_SLOT_STRIDE
RS_OBS_WX     = RS_OBS_BASE + 1 * RS_SLOT_STRIDE
RS_OBS_Z      = RS_OBS_BASE + 2 * RS_SLOT_STRIDE
RS_OBS_TIER   = RS_OBS_BASE + 3 * RS_SLOT_STRIDE

RS_PYL_BASE   = 4 * RS_SLOT_STRIDE
RS_PYL_ALIVE  = RS_PYL_BASE + 0 * RS_SLOT_STRIDE
RS_PYL_WX     = RS_PYL_BASE + 1 * RS_SLOT_STRIDE
RS_PYL_Z      = RS_PYL_BASE + 2 * RS_SLOT_STRIDE
RS_PYL_TIER   = RS_PYL_BASE + 3 * RS_SLOT_STRIDE

RS_BUL_BASE   = 8 * RS_SLOT_STRIDE
RS_BUL_ALIVE  = RS_BUL_BASE + 0 * RS_SLOT_STRIDE
RS_BUL_WX     = RS_BUL_BASE + 1 * RS_SLOT_STRIDE
RS_BUL_Z      = RS_BUL_BASE + 2 * RS_SLOT_STRIDE

RS_ACTORS_BYTES = RS_BUL_BASE + 3 * RS_SLOT_STRIDE

; --- the OAM window ----------------------------------------------------------
; Twenty-eight slots, seven whole hi-table bytes. OAM index order IS priority
; (lower draws in front), so this list reads front-to-back — see
; rs_obj/feature.toml for why each one sits where it does. The HAZARD
; sub-window is DEPTH-ORDERED, not identity-ordered.
; THE HUD IS IN FRONT OF THE PYLONS. The tempting premise is that the two can
; never share a scanline -- which is false: the pylon's ground point cannot
; reach the sky band, but its SPRITE stands 96 px above that point and crosses
; the HUD's scanlines on about a tenth of frames. The pilot's instruments win
; that priority by construction rather than by luck.
RS_OAM_RETICLE  = 0                 ; the aiming instrument: in front of all
RS_OAM_BURST    = 1
RS_OAM_SHIP     = 2
RS_OAM_HAZARDS  = 3                 ; .. + RS_OBS_N - 1
RS_OAM_SHOTS    = RS_OAM_HAZARDS + RS_OBS_N
RS_OAM_SCORE    = RS_OAM_SHOTS + RS_BUL_N
RS_OAM_LIFE     = RS_OAM_SCORE + RS_SCORE_DIGITS
RS_OAM_PYLONS   = RS_OAM_LIFE + RS_LIVES_N + RS_HUD_PAD    ; scenery: last
RS_OAM_N        = 28
.assert RS_OAM_PYLONS + RS_PYL_N * RS_PYL_STACK = RS_OAM_N, error, "the OAM window overflows its claim"

; --- OBJ tile numbers (OBJ-name-base relative; the sheet's layout) -----------
; A 32x32 frame at base N reads {N..N+3, N+16..N+19, ...} — four rows and four
; columns; a 16x16 frame reads {N, N+1, N+16, N+17} — two rows. That is why the
; ten digits are a TABLE and not base + 2*v: the ninth would want base 144,
; whose N+16 row is already the eighth frame's bottom half.
RS_T_SHIP_F0  = 0                   ; 32x32
RS_T_SHIP_F1  = 4
RS_T_HAZ_T0   = 8
RS_T_HAZ_T1   = 12
RS_T_PYL_T0   = 64
RS_T_PYL_T1   = 68
RS_T_BURST_A  = 72
RS_T_BURST_B  = 76
RS_T_HAZ_T2   = 164                 ; 16x16
RS_T_HAZ_T3   = 166
RS_T_PYL_T2   = 168
RS_T_PYL_T3   = 170
RS_T_RETICLE  = 172
RS_T_BULLET   = 174
RS_T_LIFE_FULL  = 192
RS_T_LIFE_EMPTY = 194

; --- the OAM attribute byte, and the size flag that is NOT in it -------------
; The attribute byte is bit 7 = V-flip, bit 6 = H-flip, bits 5:4 = priority,
; bits 3:1 = palette, bit 0 = tile bit 8. SIZE is not there — it lives in the
; hi table, two bits per sprite alongside X9 — so `rs_put` takes one 16-bit
; parameter whose low byte is the attribute and whose bit 8 is the size
; select. Written as shifts so the meaning is legible and so no_literals never
; sees a bare address-shaped hex word.
RS_ATTR_PRI   = 3 << 4              ; priority 3: in front of the BG
RS_ATTR_HFLIP = 1 << 6
RS_ATTR_PAL0  = 0 << 1              ; OBJ palette 0 — the ship
RS_ATTR_PAL1  = 1 << 1              ; OBJ palette 1 — everything else
RS_SIZE_LARGE = 1 << 8              ; rs_put's parameter flag, NOT an attr bit

; The per-tier OAM descriptor: {tile, attr|size, centre_off}. Four rows, tier 0
; (nearest, largest) to tier 3. The centre offset is half the sprite's width —
; the projection answers with the object's CENTRE and OAM wants its left edge.
RS_TIER_ROWS  = 4
RS_TIER_ROW_B = 6                   ; 3 words per row
RS_CENTRE_32  = 16
RS_CENTRE_16  = 8

; The park scanline: an OAM y of $F0 puts a sprite fully off the bottom of a
; 224-line frame at every size this rail uses.
RS_PARK_Y     = $F0

; --- joypad bit masks --------------------------------------------------------
; SHIFTS, not hex: `$0200` lands inside a WRAM claim and nothing in the token
; distinguishes a hardware bit from an address.
RS_JOY_A     = 1 << 7
RS_JOY_RIGHT = 1 << 8
RS_JOY_LEFT  = 1 << 9
RS_JOY_DOWN  = 1 << 10
RS_JOY_UP    = 1 << 11
