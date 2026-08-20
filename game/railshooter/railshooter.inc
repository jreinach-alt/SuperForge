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
; (Makefile), so the Mode 7 floor is DRAWN on scanlines 44..223.
;
; THE SEAM IS NOT THE HORIZON, and reading it as one is what put the actors on
; a second camera. The plane's own vanishing row is 38.39 scanlines ABOVE the
; seam (screen y 5.6, inside the sky band) because the pose hyperbola has
; k0 = 38.39; the seam is only where the plane starts being drawn. The
; projection LUT is keyed to the VANISHING row (gen_railshooter_assets.py
; HORIZON_Y = 6) and that file asserts the derivation. What ties RS_Z_FAR to
; the LUT here is rs_obj.asm's bucket-count .assert.
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
; 128/256 = 0.5 world px/frame, carried in 8.8, and it is NOT a taste
; setting — it is one half of the ground lock. The Mode 7 plane shows exactly
; 53.8 texture px of depth (the pose blob's 436:77 scale ratio, not a choice),
; so ANY object standing on the ground crosses the visible plane in
; 53.8/speed frames and nothing else. At the shipped 1.5 px/frame that is 36
; frames — MEASURED at 29 frames over rows 50..200 — while an obstacle took
; 153, so the pylons slid over the ground by up to 11.7x at the horizon. The
; other half of the lock is the projection LUT, whose A = 2511 * RS_OBS_STEP /
; speed; at this speed and RS_OBS_STEP = 5 that is CAM_H = 98, HORIZON_Y = 6,
; FOCAL = 384 (tools/gen_railshooter_assets.py, where the derivation is
; asserted). Speed and step therefore move TOGETHER or the surface and the
; things standing on it come apart again.
;
; 0.5 px/frame buys a 108-frame (1.8 s) crossing, and every frame of it is
; moving and growing — the shipped 1.5 spent 76 of its 154 frames as a
; near-static speck in the top six scanlines. Any pair with
; RS_OBS_STEP = 9.8 * speed keeps the lock; what moves is that crossing time.
;
; AND WHY THIS PAIR AND NOT ANOTHER ON THE LINE. `cam_y` is an integer and
; Mode 7 has no fractional scroll, so the plane advances in whole texture px —
; 18.8 SCREEN px at the bottom row, at any speed. 128/256 emits exactly one
; such step every OTHER frame, a regular 30 Hz cadence; a non-dyadic speed
; emits them on an irregular 2-or-3 frame pattern, and irregular is what reads
; as judder. This rail has already paid for that once on the lateral axis (see
; RS_PATH_SHIFT), and the forward axis is the same defect with a different
; letter.
RS_RAIL_SPEED_88 = 128              ; 0.5 in 8.8 — LOCKED to RS_OBS_STEP
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
; |slope| under this reads as straight, as a fraction of the path amplitude —
; 18/64 is the same 0.28 the shipped 40/144 was, so the ship banks over the
; same part of each bend.
RS_BANK_DEAD   = 18

; --- the depth axis ----------------------------------------------------------
; Each actor carries a forward depth z ahead of the camera, decremented by a
; constant every frame. The unit is 1/9.8 of a plane texture pixel — a SCALE,
; not an arbitrary axis — chosen so RS_OBS_STEP is a small integer while the
; rail advances RS_RAIL_SPEED_88/256 texture px. That equality IS the ground
; lock: 5 z per frame is exactly 0.5 texture px per frame, so an actor closes
; ground at the rail's own speed and its projected contact point tracks the
; grid under it. Change either number without the other and the pylons slide
; again — MEASURED at 4-against-128, which is the lock read 20% slow and shows
; up as an actor/surface rate ratio of 0.8 at every row.
;
; Z_FAR IS JUST UNDER THE SEAM. The LUT's A/k0 = 25088/38.39 = 653, so an actor
; spawned at RS_Z_FAR is projected to scanline 45 — one row inside the plane.
; It rises out of the horizon instead of popping in below it, and nothing is
; ever projected into the sky band.
RS_Z_FAR      = 640                 ; the far edge, one row under the seam
RS_Z_NEAR     = 16                  ; the LUT's low end; actors free long before
RS_OBS_STEP   = 5                   ; z closed per frame — LOCKED to the speed
; z falls RS_OBS_STEP per frame while `dist` rises 1 per frame, so
; `dist * RS_OBS_STEP + z` is INVARIANT for an actor across its whole flight.
; RS_LEAD is that invariant expressed in FRAMES: an actor spawned now at
; z = RS_Z_FAR arrives RS_LEAD frames from now, so the path index at
; (dist + RS_LEAD) is where the camera WILL BE when it gets here. That is what
; makes a lane offset a real "will this hit me" number instead of a guess.
;
; ARRIVAL IS THE BOTTOM OF THE SCREEN NOW, not z = 0 — see RS_OBS_HIT_Z — so
; the lead is the FLOWN part of the range and not the whole of it. Under the
; old projection the two were nearly the same number because the clamp did the
; work; under the ground lock an actor reaches scanline 223 at z = 113 and the
; remaining 105 units are 26 frames of a sprite parked on the bottom edge.
RS_LEAD       = (RS_Z_FAR - RS_OBS_HIT_Z) / RS_OBS_STEP     ; 105 frames

; --- the hazard field --------------------------------------------------------
; Spawned on a SCHEDULE and freed on arrival, not recycled forever: the pool
; genuinely allocates and frees on both sides, which is the property the rail
; exists to exercise — a field that never empties never tests a free.
RS_OBS_N      = 4                   ; pooled hazards == the OAM window width
RS_OBS_GAP    = 40                  ; frames between spawns (2-3 alive at 105/40)
; ARRIVAL = THE BOTTOM EDGE. The LUT puts scanline 223 at z = 25088/217.39 =
; 115, so that is the first z fully off the bottom of the frame. Freeing there
; is what stops a 32x32 hazard sitting clamped on the last scanline for the 20
; frames its old z = 8 threshold took to run out.
RS_OBS_HIT_Z  = 115                 ; at/below this the hazard has ARRIVED
RS_SHIP_HIT_X = 40                  ; |wx - cam_x| that counts as a collision
RS_LANES      = 4                   ; lateral offsets around the path

; --- the pylons: what the S-curve bends around -------------------------------
; One per bend, standing on the rail's CENTRE column — the line the rail would
; fly if it flew straight — so the ship's own swing is what carries it past.
; (The `centre - 2*path` placement this comment used to describe was tried and
; measured: it puts the column entirely off the left edge at closest approach.
; See rs_spawn_pylon.) Drawn as a three-tall stack of one tier frame.
;
; WHAT MAKES THE PASS WIDE IS THE BEAT, and it is a PHASE and not a counter:
; `rs_spawn` fires the pylon when the arrival phase is a bend EXTREME, so the
; pass distance is the path's full amplitude every time and no boot phase can
; put the column on the ship's nose. RS_PYL_GAP is what that beat WORKS OUT TO
; — half a period, one per bend, alternating sides — and is kept as the name
; for that cadence rather than as the thing counted to.
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
RS_PYL_GAP    = RS_PATH_HALF        ; the beat the phase test works out to
RS_PYL_STACK  = 3                   ; sprites in the column
RS_PYL_H32    = 32                  ; stack step at the two large tiers
RS_PYL_H16    = 16                  ; ...and at the two small ones

; --- tier hysteresis ---------------------------------------------------------
; An actor's z is monotone DECREASING as it approaches, so its tier only ever
; GROWS (3 -> 0). A tier advances only when z falls RS_TIER_HYST BELOW the
; threshold, which is what stops a boundary-sitting actor flickering between
; two pre-drawn sizes.
; RE-SOLVED FOR THE GROUND LOCK, and solved to keep the SCREEN bands exactly
; where they were: y(266) = 98, y(378) = 71, y(490) = 56, the same three rows
; the shipped LUT put them on. Must equal TIER_T0/T1/T2 in
; tools/gen_railshooter_assets.py, which asserts the bands stay distinct.
RS_TIER_T0    = 272                 ; == the LUT's TIER_T0 (screen y 98)
RS_TIER_T1    = 384                 ; screen y 71
RS_TIER_T2    = 498                 ; screen y 56
RS_TIER_HYST  = 12                  ; three frames of overshoot, as before
RS_TIER_FAR   = 3                   ; the tier a spawn starts at

; --- the reticle: the ONLY thing the player controls -------------------------
; A point on the GROUND PLANE in world coordinates, projected through the same
; pinhole as every hazard. That is what makes the ship's lateral swing DRAG it
; across the screen as an emergent consequence of the projection rather than a
; faked screen-space nudge. LEFT/RIGHT move its world x;
; UP/DOWN move its forward depth, because a one-axis reticle could only ever
; reach hazards at one depth.
; The four depth numbers are re-solved onto the locked LUT so the reticle
; reaches the SAME screen rows as before: y(224) = 116, y(136) = 187,
; y(479) = 58. The reticle is a ground point, so under the lock it is now
; literally standing on the grid rather than on a second camera's idea of it.
RS_RET_Z_INIT = 227                 ; screen y 116 — mid-screen, tier-0 country
RS_RET_Z_MIN  = 138                 ; screen y 187
RS_RET_Z_MAX  = 479                 ; screen y 58
RS_RET_Z_STEP = 7                   ; z/frame on UP/DOWN — ~3.5 screen px at
                                    ;   RS_RET_Z_INIT, the shipped feel
RS_RET_SPEED  = 3                   ; world px/frame on LEFT/RIGHT
; MEASURED, not guessed, and RE-SOLVED for the lock — as a RATIO, which is what
; the shipped comment was really claiming. At RS_RET_Z_INIT the lateral gain is
; FOCAL/z = 384/227 = 1.69 screen px per world px (it was 44/60 = 0.73), and
; the S-curve's steepest bend now moves the camera 1.57 world px/frame (the
; amplitude moved WITH the gain — gen_railshooter_assets.py PATH_AMP, 144 -> 64,
; so the SCREEN drag is the shipped one), which drags the aim 2.66 screen
; px/frame. Three world px/frame of correction buys 5.1: the same ~1.9x
; authority over the worst drag, and the same ~5 screen px per frame of aim
; travel the shipped 6-at-0.73 gave. Aiming is correcting back onto a target
; rather than a fight the pad cannot win.
RS_RET_TOL    = 6                   ; screen px of forgiveness on the box test

; --- firing ------------------------------------------------------------------
; A press does TWO things. It runs a SCREEN-SPACE hitscan (§ rs_fire) against
; the same projection cache the OAM emit uses, and it spawns a tracer for feel.
; The hitscan is screen-space and not world-space because a fixed world
; tolerance cannot match a sprite's footprint across depth: 32 screen px is 19
; world px at RS_RET_Z_MIN and 40 at RS_RET_Z_MAX. Matching what the player
; SEES at every depth is the only tolerance that behaves the same at both ends
; of the range.
RS_BUL_N      = 3
RS_BUL_SPEED  = 20                  ; z/frame — recedes toward the horizon
RS_BUL_SPAWN  = 171                 ; born level with the ship (screen y 152),
                                    ;   re-solved onto the locked LUT
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
