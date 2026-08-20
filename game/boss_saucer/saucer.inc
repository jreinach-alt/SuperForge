; =============================================================================
; saucer.inc — boss_saucer's own vocabulary (constants only; state is
; allocator-emitted via state.toml, addresses via the generated maps)
; =============================================================================
; Names carry the SAU_ prefix. Bit masks are SHIFTS and dimensions are decimal:
; no_literals refuses hex forms that look like addresses, and the gate is right.

; --- pacing ----------------------------------------------------------------
SAU_REVEAL_FRAMES = 60          ; reveal ramp length == the track's 60 steps
SAU_HOLD_FRAMES   = 45          ; pause at full size before the fight
SAU_FADE_FRAMES   = 32          ; state-timer pad around fades. SuperForge's
                                ;   fade feature ramps 1 level/frame (15 frames
                                ;   0<->15), so a 32-frame state wait strictly
                                ;   covers a completed fade. Its role is "state
                                ;   pacing", not "fade length"
SAU_RESULT_FRAMES = 90          ; how long the result card holds

; --- the state machine -----------------------------------------------------
; Eight indices, with no ninth: the boss rail's DYING capture beat exists
; because that rail's fight rotates freely, so its death track's baked start
; angle is player-dependent. This rail's fight holds angle 0, so DEATH enters
; from the baked start exactly and there is nothing to capture.
SAU_ST_INTRO  = 0               ; vestigial: battle_init enters REVEAL directly
SAU_ST_REVEAL = 1               ; track: the saucer grows in (5.0 -> 1.5)
SAU_ST_HOLD   = 2               ; ring: slow spin at full size
SAU_ST_FIGHT  = 3               ; the LUNGE cycle + the BEAM + combat
SAU_ST_DEATH  = 4               ; track: the saucer recedes + spins (win)
SAU_ST_LOSE   = 5               ; the player died
SAU_ST_RESULT = 6               ; hold the outcome card, then fade to RESET
SAU_ST_RESET  = 7               ; masked re-init -> REVEAL (the loop)

; --- the LUNGE: the rail's headline ----------------------------------------
; The saucer dives at the camera by ramping the matrix scale DOWN (a smaller
; value samples fewer texels per pixel, so the plane looks BIGGER).
SAU_LG_FAR      = 0             ; dwell at rest scale, then APPROACH
SAU_LG_APPROACH = 1             ; ramp down to the apex; lock the beam and
                                ;   telegraph with TELE_F of the dive left
SAU_LG_NEAR     = 2             ; hold the apex while the beam runs
SAU_LG_RETREAT  = 3             ; ramp back up to rest, then FAR
; The realized ramp length. A scale ramp driven by COMPARISON rather than by
; counting (subtract a step, clamp at the near scale) runs 44 frames with a
; terminal clamp even though its nominal step count is 40. This constant is
; the length the track blobs were BAKED with; the generator derives the same 44
; from the same arithmetic, and a disagreement would break its seam asserts.
SAU_LUNGE_FRAMES = 44
; the FAR dwell, shortened by phase: faster lunges as HP drops
SAU_FAR_P0 = 40                 ; the full dwell
SAU_FAR_P1 = 28                 ; full - 12
SAU_FAR_P2 = 16                 ; full - 24

; --- the BEAM --------------------------------------------------------------
; A LANCE from the saucer's ventral emitter to the column locked onto the
; player's body centre — not a free-floating column. The emitter is the Mode 7
; PIVOT (gen_saucer_assets' predicate paints the white-hot emitter disc at
; r <= 2.3 tiles of the plane's centre) and `m7a_set_center` shows the pivot at
; the screen centre, so the emitter renders at (SAU_EMIT_CX, SAU_EMIT_CY) at
; EVERY scale. That is what welds this end of the beam to the saucer: the
; matrix changes how BIG the emitter is, never where it is, so an origin
; pinned to the screen centre tracks it exactly and needs no divide by the
; live scale.
;
; The far end is the latched column, so the beam POINTS AT WHERE IT WILL LAND
; for the whole telegraph — a far better dodge cue than a bar standing
; somewhere else on the screen.
SAU_BM_OFF  = 0
SAU_BM_TELE = 1                 ; the thin sight line (every other segment)
SAU_BM_FIRE = 2                 ; the solid lance, damaging
SAU_BEAM_SEGS   = 16            ; the OAM band's width, and the walk's length
SAU_EMIT_CX     = 128           ; the pivot's screen column (256/2)
SAU_EMIT_CY     = 112           ; ...and its row (224/2)
SAU_BEAM_X0     = SAU_EMIT_CX - 4    ; an 8x8 cell's top-left for that centre
SAU_BEAM_Y0     = SAU_EMIT_CY - 4
SAU_BEAM_PITCH  = 5             ; the walk's Y stride: fifteen steps of 5 put
                                ;   the last cell over the gunship's upper hull
                                ;   (108 + 75 = 183, hull top 184), and 5 < 8
                                ;   means consecutive cells OVERLAP, so the
                                ;   lance is seamless at any slope
SAU_BEAM_MUL    = 17            ; the X walk's 8.8 step is delta * 17, i.e.
                                ;   delta * 17/256 = delta/15.06 — so fifteen
                                ;   steps land on 255/256 of the span. A divide
                                ;   by 15 in four shifts and one add; the 0.4%
                                ;   shortfall is a quarter-pixel at the widest
                                ;   lane
SAU_BEAM_W      = 8             ; the column's hit width (beam_x is its LEFT
                                ;   edge, so the box IS the tip cell)
SAU_BEAM_TELE_F = 24            ; telegraph frames (the dodge window). Armed
                                ;   with SAU_BEAM_TELE_F of the dive still to
                                ;   run, so the sight line tracks the emitter
                                ;   through a CHANGING scale and the beam
                                ;   fires the moment the saucer reaches its
                                ;   apex
SAU_BEAM_FIRE_F = 30            ; active frames

; --- the player ------------------------------------------------------------
SAU_PLAYER_Y     = 184          ; fixed row; the player only strafes on X
SAU_PLAYER_X0    = 120
SAU_PLAYER_W     = 16
SAU_PLAYER_H     = 16
SAU_PLAYER_XMIN  = 8
SAU_PLAYER_XMAX  = 232
SAU_PLAYER_SPEED = 3            ; px/frame strafe
SAU_PLAYER_HP0   = 3
SAU_IFRAME_LEN   = 30           ; invuln frames after a beam hit

; --- combat ----------------------------------------------------------------
SAU_SHOT_SPEED  = 6             ; px/frame upward
SAU_SHOT_W      = 8
SAU_SHOT_H      = 8
SAU_BOSS_HP0    = 240
SAU_SHOT_DMG    = 5             ; ~48 hits to kill
SAU_FIRE_GAP    = 8             ; min frames between player shots (held A)
SAU_SHOT_CULL_Y = 16            ; a shot above this row is culled

; the saucer hitbox: INSIDE THE RENDERED DISC, not the screen. The debut's box
; was 224 x 96 because the debut's saucer FILLED the screen — every lane sat
; over the hull, so a shot from any lane legitimately connected. The re-pitched
; envelope renders a 100 px disc at rest (centred on the screen, so rows
; 62..162) and 141 px at the apex, and the same box would now delete bolts in
; open star field: a bolt vanishing where there is no saucer reads as a bug,
; and it is one.
;
; The box is deliberately SHALLOW as well as narrow, and the bottom edge is
; what sets it. A box reaching the disc's lower rim (row 162) kills a bolt
; 14 px into its flight — the gunship is at row 184 — so the bolts would blink
; out almost as they spawned; measured on that first cut, the rendered bolt
; centroid never climbed at all. Ending the box at row 119 instead lets a bolt
; cross the gap AND the saucer's lower half, 60 px in ten frames, and pop near
; the canopy: it reads as a hit rather than as a disappearance.
;
; The WIDTH is then set by where that kill happens. A bolt dies on the frame
; its top row reaches 116, i.e. with its body centred eight rows above the
; saucer's own centre, where the disc is 49 px of half-width; the box puts the
; extreme bolt centre 48 px out, so EVERY kill lands inside the rendered disc.
SAU_BOSS_HIT_X = 84
SAU_BOSS_HIT_Y = 64
SAU_BOSS_HIT_W = 88
SAU_BOSS_HIT_H = 56

; --- the shot pool (offsets into the sau_actors claim) ---------------------
; ONE pool: the boss rail's 8-slot orb rain has no analogue here — this saucer
; attacks with a BEAM, not orbs.
SAU_SHOT_N     = 4
SAU_SHOT_ALIVE = 0              ; alive[4]         (2 B/slot throughout)
SAU_SHOT_X     = 8              ; x[4]
SAU_SHOT_Y     = 16             ; y[4]
                                ; total 24 = the claim's bytes, asserted at
                                ;   the include site in scenes/arena.asm

; --- the HP HUD ------------------------------------------------------------
SAU_HUD_SEGS   = 8
SAU_HUD_SEG_HP = SAU_BOSS_HP0 / SAU_HUD_SEGS   ; 30 HP per segment — derived
                                ;   from the two constants above rather than
                                ;   written out, so the HUD cannot drift from
                                ;   the HP pool it reports
SAU_HUD_Y      = 12
SAU_HUD_X0     = 80
SAU_HUD_DX     = 10

; --- OBJ vocabulary --------------------------------------------------------
SAU_PARK_Y = 240                ; off the visible 224 — where dead slots park
SAU_LARGE  = 2                  ; the hi-table size bit (16x16 half of pair 0)
SAU_PRIO   = 3 << 4             ; OAM attr: priority 3, over the Mode 7 plane.
                                ;   EVERY sprite on this rail uses it, so the
                                ;   card glyphs sit in front of their own
                                ;   banner by OAM INDEX alone
SAU_T_PLAYER0 = 0               ; 16x16 quad {0,1,16,17}
SAU_T_PLAYER1 = 2               ; the iframe flash frame, quad {2,3,18,19}
SAU_T_SHOT    = 5               ; 8x8 player bolt
SAU_T_PIP_LIT = 6               ; 8x8 HP segment, lit
SAU_T_PIP_DIM = 7               ; 8x8 HP segment, spent
SAU_T_BEAM    = 8               ; 8x8 lance body, full-width so consecutive
                                ;   cells touch at every slope the walk takes
SAU_T_EXH_LO  = 9               ; thruster flame, short phase
SAU_T_EXH_HI  = 10              ; thruster flame, tall phase
SAU_T_CARDBG  = 11              ; the result banner's cell
SAU_T_BEAM_TELE  = 12           ; the telegraph's thin sight cell
SAU_T_BEAM_FLARE = 13           ; the emitter burst / the impact burst
SAU_FLASH_MASK = 4              ; frame & this picks the iframe blink phase
SAU_EXH_MASK   = 8              ; frame & this picks the flame phase

; --- the star field --------------------------------------------------------
; TWENTY-FOUR SPRITES, and the count is the whole point of the change: this
; field used to be PLANE TEXTURE — a two-density hash scatter baked into the
; 128x128 world tile grid — which put ~420 star tiles on screen at rest scale
; AND tied every one of them to the affine matrix, so the sky zoomed in
; lockstep with the saucer through all four scale ramps. A field at infinity
; does not do that. On OBJ the stars are decoupled from the matrix by
; construction, and 24 of them is the sparse sky the fight wanted.
;
; TWO BANDS, and the split is the depth cue the old two-brightness scatter
; used to carry: the far twelve are dimmer, smaller, and drift at HALF the
; near twelve's rate, so the layers separate in MOTION as well as in tone.
SAU_STAR_N      = 24            ; the stars OAM band's width (sau_obj's claim)
SAU_STAR_FAR_N  = 12            ; ...of which the first twelve are the far band
SAU_STAR_PRIO   = 0 << 4        ; OAM attr priority 0 — the ONE OBJ priority
                                ;   Mode 7 puts BELOW BG1, so the hull covers
                                ;   a star and the transparent sky does not
SAU_STAR_PALSEL = 1 << 1        ; OAM attr palette 1 = CGRAM 144..159
SAU_STAR_ATTR   = SAU_STAR_PRIO | SAU_STAR_PALSEL
SAU_T_STAR_FAR  = 14            ; 8x8 far star, one tone, five pixels
SAU_T_STAR_NEAR = 15            ; 8x8 near star, a four-point twinkle

; THE DRIFT IS KEYED TO THE FIGHT'S OWN TEMPO, not to a frame counter. The
; near band's scroll accumulator is 8.8 px/frame; the far band takes half of
; whatever the near band gets. Out of the fight (REVEAL, HOLD, DEATH, LOSE,
; RESULT, RESET) the sky is CALM; during FIGHT it quickens, and it quickens
; again with each HP third — the same escalation the FAR dwell already encodes
; (SAU_FAR_P0/P1/P2), made visible in the sky instead of only felt in the
; pacing. Downward, because the gunship is under the saucer and a sky falling
; past you reads as climbing into the fight.
;
; THE RATES ARE SET BY WHAT A 20 fps CLIP CAN SHOW. Calm is 32/256 px/frame =
; 7.5 px/s on the near band and 3.75 on the far: over the gallery clip's 12.7 s
; cycle that is 95 px and 48 px of travel, so a star visibly crosses a third to
; a half of the screen. A drift a viewer cannot see in a clip is not a feature.
SAU_STAR_CALM   = 32            ; 8.8 px/frame, near band, outside the fight
SAU_STAR_FIGHT  = 48            ; ...during FIGHT at phase 0
SAU_STAR_PH_SH  = 4             ; ...+ (1 << this) per HP-third phase, so the
SAU_STAR_PH     = 1 << SAU_STAR_PH_SH   ;   sky is 48/64/80 across the fight

; THE LATERAL SLIDE IS THE PLAYER'S OWN STRAFE, parallaxed. The camera does
; not travel on this rail — the saucer approaches, the gunship holds its row —
; so the one honest source of sideways motion is the ship sliding across the
; view. Stars counter-slide: near band by centre>>3, far band by centre>>4,
; both zeroed on the screen centre, so the gunship at its spawn lane leaves the
; field at its home positions and a full strafe to either wall moves the near
; band 14 px and the far band 7.
SAU_STAR_PAR_SH     = 3         ; near band: (hull centre) >> 3
SAU_STAR_PAR_FAR_SH = 4         ; far band:  (hull centre) >> 4

; --- the glyph cards -------------------------------------------------------
; Text is OBJ glyphs from the rail's own sheet. The strings are LENGTH-PREFIXED
; byte runs rather than sentinel-terminated word runs: a sentinel that looks
; like an address is precisely what `no_literals` refuses, and a count byte is
; smaller anyway.
SAU_G_SPACE   = 255             ; advance the pen, draw nothing (not a tile)
SAU_GTEXT_ADV = 6               ; pen advance per cell (5 px face + 1 px gap)
SAU_CARD_SLOTS = 24             ; the cards OAM band's width (sau_obj's claim)
SAU_CARD_Y     = 100            ; the result word's row
SAU_CARD_BG_TILES = 8           ; banner width, 8x8 cells (64 px)
SAU_CARD_BG_X0    = 128 - SAU_CARD_BG_TILES * 8 / 2      ; = 96, centred
SAU_CARD_BG_Y0    = SAU_CARD_Y - 4                       ; the word sits in it
SAU_DEFEAT_X  = (256 - 6 * SAU_GTEXT_ADV) / 2            ; "DEFEAT",  6 cells
SAU_VICTORY_X = (256 - 7 * SAU_GTEXT_ADV) / 2            ; "VICTORY", 7 cells
SAU_TITLE_Y1  = 30              ; the boot title's name row
SAU_TITLE_Y2  = 42              ; ...and its controls row
SAU_TITLE1_X  = (256 - 11 * SAU_GTEXT_ADV) / 2           ; "SAUCER DOWN"
SAU_TITLE2_X  = (256 - 15 * SAU_GTEXT_ADV) / 2           ; "<> MOVE   A FIRE"

; the glyph tile numbers, gen_saucer_assets.py's GLYPH_ORDER in order
SAU_G_A = 20
SAU_G_C = 21
SAU_G_D = 22
SAU_G_E = 23
SAU_G_F = 24
SAU_G_I = 25
SAU_G_M = 26
SAU_G_N = 27
SAU_G_O = 28
SAU_G_R = 29
SAU_G_S = 30
SAU_G_T = 31
SAU_G_U = 32
SAU_G_V = 33
SAU_G_W = 34
SAU_G_Y = 35
SAU_G_LARR = 36
SAU_G_RARR = 37

; --- pad bits (JOY1 standard layout; input.asm's $4218 word) ---------------
SAU_JOY_A     = 1 << 7
SAU_JOY_RIGHT = 1 << 8
SAU_JOY_LEFT  = 1 << 9
SAU_JOY_START = 1 << 12

; --- saucer phases ---------------------------------------------------------
SAU_PH1_HP = 161                ; hp >= this -> phase 0 (dwell 40)
SAU_PH2_HP = 81                 ; hp >= this -> phase 1 (dwell 28)
                                ;             else phase 2 (dwell 16)
