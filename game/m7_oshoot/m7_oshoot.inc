; =============================================================================
; m7_oshoot.inc — the rail's vocabulary: tuning, pool layout, the arena
; =============================================================================
; Constants only — no addresses. Every address in this rail comes from the
; allocator's emitted map; `allocator/no_literals.py` refuses anything else.
; What lives here is the game's own numbers: the arena's geometry, the eight
; headings, the speeds and cadences, and the byte offsets INSIDE the
; `mo_actors` claim.
;
; The tuning numbers are stated at each one, with the reasoning that fixes them.

; --- the world ---------------------------------------------------------------
; 128 tiles of 8 px. Bound to col_map through CM_WORLD_W_LOG2 in scenes/arena.asm
; so the picture's wrap and the probe's wrap are one number; WORLD_MAX is
; DERIVED from it rather than written as 1023, which `no_literals` would refuse
; anyway (a bare 1023 is an address-shaped token).
MO_WORLD_LOG2 = 7
MO_WORLD_T    = 1 << MO_WORLD_LOG2              ; 128 tiles
MO_TILE_LOG2  = 3                               ; 8 px per tile
MO_WORLD_MAX  = (1 << (MO_WORLD_LOG2 + MO_TILE_LOG2)) - 1   ; 1023, the last px

; The spawn cell — the arena centre, open floor with room in every direction so
; the wave RING (+/-120 px) lands inside the playable square rather than in the
; wall. MUST match SPAWN_TX/SPAWN_TY in tools/gen_m7_oshoot_assets.py, which
; asserts the cell is not solid.
MO_SPAWN_TX = 64
MO_SPAWN_TY = 64
MO_SPAWN_PX = MO_SPAWN_TX * 8 + 4               ; 516
MO_SPAWN_PY = MO_SPAWN_TY * 8 + 4               ; 516

; The hero's footprint: an 8 px box spanning HALF either side of the centre
; PIXEL, so near = centre - 4 and far = centre + 3. Writing +HALF instead makes
; the box nine pixels wide and the hero stops one pixel short of every wall,
; which reads as a rendering offset rather than a collision bug.
MO_HERO_HALF = 4
MO_FP_NEAR   = (0 - MO_HERO_HALF) & $FFFF
MO_FP_FAR    = MO_HERO_HALF - 1

; --- TURN AND THROTTLE — a continuous heading ---------------------------------
; LEFT/RIGHT turn the heading CONTINUOUSLY through m7_affine's 256-entry table;
; UP/DOWN drive forward/back along whatever the facing now is; L/R strafe
; sideways without touching it. Forward is therefore screen-up at every heading,
; forever, and the d-pad never changes meaning underneath the player.
;
; THIS REPLACES AN EIGHT-WAY COMPASS SNAP, and the snap is gone rather than
; disabled — `dir8_angle`, the UDLR bitfield that indexed it, the MO_DIR_*
; vocabulary and the `moving` gate it drove are all deleted. The snap produced
; two defects: a 45 degree visual jolt on every direction change, and a d-pad
; whose relationship to the screen moved with the view.
;
; TURN RATE: 3 of 256 units per held frame = 4.22 deg/frame, a full revolution in
; 85 frames (1.42 s). m7_dungeon uses 1 (4.27 s/rev), which is a crawler's weight
; and too slow to bring a target round in a shooter. 3 sits an order of magnitude
; below the 32-unit (45 deg) step it replaces, which is what makes the smoothness
; bound a real gate rather than a marginal one.
MO_TURN_STEP = 3

; Speed is capped SLOW so the per-step collision cannot tunnel a wall in one
; step. $0140 in 8.8 is +1.25 px/frame — UNCHANGED from the 8-way scheme,
; deliberately: the chase-escape arithmetic below is stated against this exact
; number and halving the chasers' rate was tuned to it.
MO_MOVE_SPEED = $0140
MO_MOVE_REV   = (0 - MO_MOVE_SPEED) & $FFFF     ; reverse, symmetric

; THE THROTTLE IS SET, NOT RAMPED. m7_dungeon ramps at ACCEL = $10 and takes 20
; frames to reach this cap; that would spend HALF the 40-frame post-contact grace
; below top speed, and the grace's whole job is to let a hero who has just been
; knocked back outpace the chasers converging on the spawn. A set throttle keeps
; the measured 1.25 px/frame from frame one. It also keeps the scheme legible,
; which is the point.
;
; m7_dungeon's deliberately-reproduced trap — an UNSIGNED forward clamp, so
; reverse-to-forward snaps while forward-to-reverse ramps — is NOT carried over.
; It is kept there because a recorded route through that maze was driven against
; it; this rail has no such route, and a set throttle has no clamp to be
; asymmetric about.

; STRAFE: slower than forward, so forward stays the primary motion and a strafe
; reads as a sidestep rather than a second way to drive. Screen-right at heading
; t is (cos t, -sin t), so in this rail's `pos -= step` convention a strafe of s
; contributes (-s*cos t, +s*sin t) to the step — see do_integrate. Worst case
; with UP+R held is 1.25 + 0.75 = 2.0 px/frame against an 8 px footprint and
; 24 px pillars, so there is no tunnelling risk. It is ADDITIVE — it does not
; change what the d-pad means — and it is easy to drop.
MO_STRAFE_SPEED = $00C0                         ; +0.75 px/frame, to screen-right
MO_STRAFE_LEFT  = (0 - MO_STRAFE_SPEED) & $FFFF

; --- the pad -----------------------------------------------------------------
; Written as SHIFTS, not hex: `no_literals` refuses `$0200` because nothing in
; the token distinguishes a hardware bit from a WRAM address, and the shift also
; says what the number IS — bit 9 of a hardware word.
MO_JOY_R     = 1 << 4
MO_JOY_L     = 1 << 5
MO_JOY_A     = 1 << 7
MO_JOY_RIGHT = 1 << 8
MO_JOY_LEFT  = 1 << 9
MO_JOY_DOWN  = 1 << 10
MO_JOY_UP    = 1 << 11

; --- the two pools -----------------------------------------------------------
; Byte offsets INSIDE the `mo_actors` wram claim (mo_obj/feature.toml). A fixed
; Byte offsets INSIDE the `mo_actors` wram claim (mo_obj/feature.toml). A fixed
; 16-byte field stride (8 slots x 2 B) so a pool is (base, count) and a field is
; (base + field_offset + slot*2), over an emitted base.
;
; THE COUNTS ARE ONE CONSTANT EACH, and that is what discharges `pool`'s
; unenforced upper bound (pool.asm's porting delta (c)): the same symbol reaches
; pool_init, pool_spawn and pool_count for a given pool, both are <= 128, and
; the 16-byte stride allocates 8 slots for each even where only 6 are used.
MO_POOL_STRIDE = 16                             ; bytes per field = 8 slots x 2

MO_ENE_N       = 6                              ; wave chasers
MO_ENE_ALIVE   = 0 * MO_POOL_STRIDE
MO_ENE_WX      = 1 * MO_POOL_STRIDE
MO_ENE_WY      = 2 * MO_POOL_STRIDE
MO_ENE_DYING   = 9 * MO_POOL_STRIDE             ; frames left of the death flash;
                                                ;   0 = a live chaser. See
                                                ;   MO_DEATH_FRAMES below

MO_BUL_N       = 8                              ; bullets
MO_BUL_ALIVE   = 3 * MO_POOL_STRIDE
MO_BUL_WX      = 4 * MO_POOL_STRIDE
MO_BUL_WY      = 5 * MO_POOL_STRIDE
MO_BUL_VX      = 6 * MO_POOL_STRIDE
MO_BUL_VY      = 7 * MO_POOL_STRIDE
MO_BUL_TTL     = 8 * MO_POOL_STRIDE
MO_ACTORS_BYTES = 10 * MO_POOL_STRIDE           ; 160 — the claim's size

; --- bullets -----------------------------------------------------------------
; Fire (A, rising edge) spawns a bullet at the hero WORLD pos with a velocity
; along the CURRENT facing. Forward is `pos -= step`, so the velocity — a delta
; along the CURRENT facing. Forward is `pos -= step`, so the velocity — a delta
; ADDED to the position each frame — is the NEGATED product. Getting that sign
; wrong fires bullets backward.
MO_BUL_SPEED = $0300                            ; +3.0 px/frame (8.8)
MO_BUL_LIFE  = 90                               ; frames — 3 x 90 = 270 px range

; --- waves, chase, contact ---------------------------------------------------
MO_ENE_SPEED    = 1     ; world px each chaser steps toward the player, per STEP
MO_SPAWN_PERIOD = 50    ; frames between wave beats
MO_RING_N       = 8     ; ring_off entries — the eight compass spawn offsets
MO_CONTACT_W    = 12    ; hero-chaser overlap: |dx| < 12 AND |dy| < 12
MO_GRACE_FRAMES = 40    ; post-respawn frames with contact suppressed

; THE CHASERS STEP EVERY OTHER FRAME. Stepping them every frame makes a chaser
; FASTER THAN THE HERO and the grace window structurally incapable of doing its
; job. The arithmetic, measured on the emulator and reproducible from the two
; speeds alone:
;
;   hero   MO_MOVE_SPEED = 1.25 px/frame ALONG THE HEADING, so per AXIS it is
;          1.25 on a cardinal and 1.25*sin(45) = 0.88 on a diagonal
;   chaser 1 px per axis per frame => 1.0 px/frame cardinal, 1.41 diagonal
;
; So a fleeing hero gains 0.25 px/frame at best (cardinal) and LOSES 0.12 px/frame
; on a diagonal. Escaping the 12 px contact box from a standing start needs
; > 0.30 px/frame sustained across the 40-frame grace — more than the hero can
; ever gain. The grace therefore suppresses the hit without ever creating
; separation, and contact re-fires on the exact frame it expires, forever. That
; is the "constantly knocked back" defect, and it is a SPEED RELATIONSHIP defect
; rather than a stray constant: no value of MO_GRACE_FRAMES fixes a pursuer that
; is faster than the pursued.
;
; Halving the chaser's rate makes the relationship hold on EVERY heading:
;   cardinal  1.25 - 0.5  = 0.75 px/frame gained  -> clears 12 px in 16 frames
;   diagonal  0.88 - 0.5  = 0.38 px/axis/frame    -> clears 12 px in 32 frames
; both inside the 40-frame grace, which is what makes the window mean something.
; The chasers still close on a STANDING player at 0.5-0.71 px/frame, so standing
; still is still fatal — the threat is intact, the counterplay is not absent.
;
; Written as a mask rather than a period because the gate is a parity test on a
; free-running counter (`lsr` + `bcc`), which is the whole of "every other
; frame" in four cycles; a general 1-in-N would need a compare and a reload.
; NOT A LIVE KNOB — it was documented as one and it was not. The chase gate is
; HARD-CODED in arena.asm (`lsr` + `bcc`, i.e. step on even frames only); this
; symbol appears in ZERO instructions, so changing it silently does nothing.
; Kept as the NAME of the every-other-frame rule. To make the cadence tunable,
; wire the gate to an `and #MO_CHASE_HALF` — a ROM-moving change, so it belongs
; to whatever work actually retunes the chase, not to a comment fix.
MO_CHASE_HALF   = 1     ; the rule: step when (frame & this) == 0 — see above

; The invulnerability flicker — the rail's ONE hit cue, and the reason there is
; no longer a full-screen flash. The hero is SCREEN-FIXED by the camera (the
; pivot is re-pinned to him every frame), so a knockback that teleports him to
; spawn moves the FLOOR and not him: without a cue on the avatar itself the only
; feedback is that the world jumped, which reads as confusion rather than damage.
; A blink on the hero's own 16x16 sprite says "you were hit AND you are briefly
; safe" in the genre's standard vocabulary, costs no PPU brightness register, and
; is 0.4% of the screen rather than all of it.
;
; Bit 2 of the grace countdown => 4 frames lit, 4 frames dark (7.5 Hz), five full
; cycles across the 40-frame window. The hit FRAME ITSELF is dark (40 & 4 == 0),
; so the feedback lands on the frame the player is hit rather than four later.
MO_BLINK_MASK   = 4     ; the hero is drawn iff (US_GRACE & this) != 0

; =============================================================================
; THE SAME NUMBERS FOR THE OTHER CONSOLE (engine/features/tick_scale)
; =============================================================================
; `tick_scale` publishes the measured ratio between the two machines' frames as
; a GAIN: a PAL frame lasts r = 1 + TS_GAIN_NUM/TS_GAIN_DEN = 1.2018039 NTSC
; frames. A rate in px per frame therefore takes r to keep px per SECOND, and
; a RANGE expressed as a frame count takes 1/r to keep world pixels.
;
; Only the 8.8 rates are twinned here. The integer ones — MO_TURN_STEP and the
; chaser's one pixel per other frame — have no correct x1.2018 and go through
; TS_STEP's accumulator in arena.asm instead.
;
; TICK: ok — this block is the region compensator's derivation for this rail;
;   naming the NTSC frame beside the PAL one is its subject rather than a
;   coupling in it, exactly as in tick_scale.asm.
.define MO_RGAIN(v)  ((((v) * (TS_GAIN_DEN + TS_GAIN_NUM)) + TS_GAIN_DEN / 2) / TS_GAIN_DEN)
.define MO_RSHRINK(v) (((v) * TS_GAIN_DEN + (TS_GAIN_DEN + TS_GAIN_NUM) / 2) / (TS_GAIN_DEN + TS_GAIN_NUM))

; TICK: ok — the four below are the region compensator's OWN outputs; naming
;   the frame they convert into is what the line is for.
MO_MOVE_SPEED_PAL   = MO_RGAIN(MO_MOVE_SPEED)       ; 320 -> 385 (1.504 px/f)
MO_STRAFE_SPEED_PAL = MO_RGAIN(MO_STRAFE_SPEED)     ; 192 -> 231
MO_BUL_SPEED_PAL    = MO_RGAIN(MO_BUL_SPEED)        ; 768 -> 923
MO_BUL_LIFE_PAL     = MO_RSHRINK(MO_BUL_LIFE)       ; 90 frames -> 75: the
                                                    ;   same 270 px of range
; TICK: ok — a frame count BY CONSTRUCTION, and paired with MO_BUL_SPEED_PAL
;   so that their PRODUCT — the bolt's range in world px — is region-free.

; The two INTEGER rates, as TS_STEP bases in the 8.8 unit that macro takes.
; TS_STEP publishes whole units and carries the remainder, which is the only
; honest answer for a step of 3 (round-to-nearest is 4 and overshoots by 11%,
; round-down is 3 and changes nothing).
MO_TURN_BASE  = MO_TURN_STEP * TS_ONE       ; 3 heading units per NTSC frame
; ...and the chase, at HALF a unit per frame: one pixel every other frame on
; NTSC, exactly as the parity counter it replaced.
MO_CHASE_BASE = TS_ONE / (MO_CHASE_HALF + 1)
.assert MO_CHASE_BASE * 2 <= TS_ONE, error, "m7_oshoot: the chase base can publish 2 — the step below only moves one pixel"
; --- the death flash, and the score ------------------------------------------
; A KILL MUST NOT LOOK LIKE A DESPAWN. A bolt hit no longer frees
; the chaser's slot on the spot: it sets MO_ENE_DYING and the slot stays alive-
; but-dying for these frames — it STOPS MOVING, cannot hurt the hero, cannot be
; re-killed, and draws in the score palette while it flashes. Then pool_kill
; takes the slot back, so the allocate -> active -> free -> REUSE cycle the rail
; exists to show is intact; only the moment of the free moves.
;
; 24 frames = 0.4 s, three lit/dark cycles at the blink mask below. Long enough
; to read at a glance, short enough that a corpse is never mistaken for a threat
; still standing there. The contrast against a DESPAWN is the point: a bolt whose
; TTL expires parks between two frames with no flash at all, which is what makes
; the two distinguishable in the rendered frame.
MO_DEATH_FRAMES = 24
MO_DEATH_BLINK  = 4     ; drawn iff (dying & this) != 0 — bit 2, as the hero's

; The score readout: three 8x8 digits, so 999 is the ceiling and it is CLAMPED
; rather than wrapped (a score that rolls 999 -> 000 reads as a reset, which is
; what a CONTACT means here and nothing else may say). +1 per kill.
MO_SCORE_MAX  = 999

; Digit d draws with tile MO_DIGIT_TILE + d. The glyphs live in the HERO sheet's
; pad tiles — that blob is an 18-tile grid with content only at {0,1,16,17}, so
; 2..11 were zero and now carry the digits. No new CHR claim, no second upload.
MO_DIGIT_TILE = 2

; OBJ palette 3 in an OAM attribute byte is (3 << 1) — the score's own colour
; band, so this module's exact `_yellow`/`_red`/`_cyan` pixel predicates keep
; meaning what they say. mo_obj/feature.toml's score_pal claim carries the rest.
MO_PAL_SCORE  = $06

; Top-left, one digit pitch apart, clear of the 16x16 hero pinned at screen
; centre (120,104) by a wide margin.
MO_SCORE_X    = 16
MO_SCORE_Y    = 16
MO_DIGIT_PITCH = 8

MO_BULHIT_W     = 16    ; bullet-chaser overlap, the same half-open box test.
                        ;   WORLD space, so the hit is ROTATION-INVARIANT — it
                        ;   never reads the matrix, which is the rail's own
                        ;   headline

; --- the cast on screen ------------------------------------------------------
MO_SIZE  = 16                                   ; every actor is 16x16
MO_HALF  = MO_SIZE / 2                          ; OAM (x,y) = centre - half
MO_TILE_WORDS  = 16                             ; an 8x8 4bpp tile = 32 B
MO_SHEET_TILES = 18                             ; the OBJ quad {0,1,16,17} + pad

; The two sheet bases, and the bullet drawing with the chaser's tile: a 16x16
; sprite spans two rows of the 16-wide OBJ sheet, so consecutive actors are 32
; tiles apart.
MO_HERO_TILE   = 0
MO_ENEMY_TILE  = 32
MO_BULLET_TILE = MO_ENEMY_TILE

; OAM attribute bytes: priority 3 (in front of the plane) + the OBJ palette.
MO_PRIO       = $30
MO_PAL_HERO   = $00                             ; OBJ palette 0, at CGRAM 128
MO_PAL_ENEMY  = $02                             ; OBJ palette 1, at 144
MO_PAL_BULLET = $04                             ; OBJ palette 2, at 160

; The hi-table's two bits per sprite: bit 0 = X9, bit 1 = size-select.
;
; CORRECTED: this comment used to read "every actor is the SMALL 16x16 of the
; OBSEL pair, so nothing sets it", and both halves were false. obj_arm writes
; OBSEL size pair 0, which is (8x8 / 16x16) — mo_obj.asm says so and derives the
; base from ES_V_OBJ_CHR_OBSEL_BASE — and mo_put ORs MO_LARGE into EVERY actor's
; hi-table field unconditionally. So the actors are the LARGE half, the bit is
; set on all of them, and the SMALL half is a free 8x8 this rail had been told it
; did not have. The score readout spends it: a HUD digit that leaves this bit
; clear is one tile instead of four. The bit is still DERIVED per slot rather
; than assumed, because assuming it is exactly how the phantom-diamond class of
; bug gets shipped.
MO_LARGE = 2

MO_PARK_Y = $F0                                 ; below the screen — where a
                                                ;   free or culled slot parks
