; =============================================================================
; split_v.inc — the split_v_fight rail's geometry and tuning
; =============================================================================
; Every value here is a constant of the ARENA or the FEEL, never an address:
; addresses are the allocator's and arrive through the emitted map.

.ifndef SPLIT_V_INC
SPLIT_V_INC = 1

; --- the arena -------------------------------------------------------------
; The stage map is 256 px periodic (32 tiles x 8 px), which is what makes the
; mod-256 camera arithmetic in split_v_bg correct rather than merely tolerable.
SV_ARENA_MID = 128              ; arena centre in world px = the screen centre
SV_ARENA_LO  = 24               ; left wall: a fighter's centre cannot go below
SV_ARENA_HI  = 232              ; right wall

; --- the feel --------------------------------------------------------------
SV_WALK_SPD  = 2                ; px/frame per fighter

; Below this separation the view is FULLY MERGED. Above it the cameras diverge
; by half the excess, so each fighter stays the same distance inside its own
; half as it would have been in a single view.
SV_MERGE_DX  = 128

; The cap on divergence. 48 px gives a band half-width of 3 (hw = spread >> 4),
; i.e. a 7 px divider — wide enough to read, narrow enough not to eat the play
; area at full separation.
SV_SPREAD_MAX = 48

; The per-frame ease rate toward the distance-derived target, 8.8.
; COUPLED TO SV_WALK_SPD: both fighters walking apart changes dx by
; 2*SV_WALK_SPD per frame, so the target moves at ~SV_WALK_SPD/frame. An ease
; slower than that makes the divider visibly lag the fighters; $00C0 (0.75
; px/frame) against a walk of 2 is deliberately just under, so the split
; trails the motion slightly and reads as weight rather than as lag.
SV_SPR_STEP  = $00C0

; --- the auto-demo ---------------------------------------------------------
; Frames held at each wall before reversing. NOT decoration: the ease chases
; its target at SV_SPR_STEP (0.75 px/frame) while the target moves at
; SV_WALK_SPD (2 px/frame), so without a hold the demo reverses before the
; divergence ever reaches full width and the divider never opens past ~3 px.
SV_DWELL = 72

; --- the round -------------------------------------------------------------
; A round is COUNT -> LIVE -> KO -> COUNT, and the cycle is what gives this
; rail a loop point it never had: the clip can cut on a round start, which is
; the one moment the fighters are back on their marks with the view merged.
SV_R_COUNT = 0
SV_R_LIVE  = 1
SV_R_KO    = 2

; The count is 3, 2, 1, FIGHT. A power-of-two beat is not decoration: the drawn
; glyph is DERIVED from the round timer by a shift (split_v_obj's
; sv_count_draw), so a second word holding "which beat" — and able to disagree
; with the clock driving it — never exists.
SV_COUNT_SHIFT = 5
SV_COUNT_STEP  = 1 << SV_COUNT_SHIFT    ; 32 frames a beat
SV_COUNT_BEATS = 4
SV_COUNT_LEN   = SV_COUNT_STEP * SV_COUNT_BEATS
SV_KO_LEN      = 94                     ; the KO pose holds, then the next round.
                                        ; 1.6 s: long enough to read who fell,
                                        ; short enough that the clip does not
                                        ; spend a quarter of itself on a still
                                        ; picture.
                                        ;
                                        ; AND THE ODD VALUE IS LOAD-BEARING. The
                                        ; gallery clip samples every 3rd frame
                                        ; and cuts its loop on the round's FIGHT
                                        ; beat, so the two ends land on the same
                                        ; instant of the count only if the whole
                                        ; round is a multiple of 3 frames long.
                                        ; At 96 they landed one frame apart and
                                        ; the join carried the idle animation's
                                        ; phase: mad 2.03. Measured, not
                                        ; reasoned — tools/gif_seam.py.

; Life. FOUR segments, and the number is a claim: split_v_obj declares eight
; OAM sprites for the two bars, so changing this changes the claim.
SV_HP_SHIFT = 2
SV_HP_MAX   = 1 << SV_HP_SHIFT

; The fighters' opening marks, symmetric about the arena centre and inside
; SV_MERGE_DX of each other so a round OPENS on a merged view.
SV_SPAWN_DX = 30
.assert SV_SPAWN_DX * 2 < SV_MERGE_DX, error, "the fighters spawn far enough apart to open the split, so a round no longer starts on the seamless frame"

; --- the swing -------------------------------------------------------------
; SWG counts DOWN from SV_SWING_LEN and the hitbox is live in a WINDOW inside
; that count, latched to one hit per swing. A window, a reach that follows
; facing, and a latch is the whole active-frames combat pattern.
SV_SWING_LEN   = 20
SV_SWING_FIRST = SV_SWING_LEN - 13      ; live while swg is in [FIRST, LAST]
SV_SWING_LAST  = SV_SWING_LEN - 6
.assert SV_SWING_FIRST > 0, error, "the swing's active window opens after the swing has ended"
SV_SWING_REACH = 44                     ; px between fighter centres for a hit
SV_SWING_LUNGE = 2                      ; px/frame carried forward while active
SV_HIT_LEN     = 24                     ; the defender's reaction, in frames
SV_KNOCKBACK   = 12                     ; px a landed hit pushes the defender

; THE VERTICAL GATE IS WHAT MAKES THE JUMP A DEFENCE. A swing misses a fighter
; whose height differs by this much, so hopping over one is a real answer to it
; rather than decoration — and it is the reason the jump is a COMMAND here and
; not an animation.
SV_SWING_VGATE = 14

; --- the jump --------------------------------------------------------------
; 8.8, both of them. Apex = V0^2 / (2 * GRAV) ~= 40 px and the hop lasts
; ~2 * V0 / GRAV ~= 40 frames: high enough to clear a swing's vertical gate by
; a wide margin at the top, brief enough that committing to it is a risk.
SV_JUMP_V0 = $0400              ; 4.0 px/frame upward
SV_GRAV    = $0033              ; 0.199 px/frame^2 down

; --- the sprite HUD's geometry --------------------------------------------
; Screen space, not world space. P1's bar grows right from the left edge and
; P2's grows left from the right, so damage eats INWARD on both.
SV_LIFE_Y  = 12
SV_LIFE_X1 = 8
SV_LIFE_X2 = 256 - 8 - 16               ; the right edge, less one 16px frame
SV_COUNT_Y = 84
SV_COUNT_LETTERS = 5                    ; "FIGHT" — the widest count phase
SV_COUNT_DIGIT_X = SV_ARENA_MID - 8     ; one 16px glyph, centred on the seam
SV_COUNT_WORD_X  = SV_ARENA_MID - (SV_COUNT_LETTERS * 16) / 2

; Off-screen, for a claimed sprite with nothing to show — AND THE HEIGHT
; MATTERS. OAM y wraps mod 256, so the condition is that the parked sprite ENDS
; at or before the wrap, not that it reaches it: 240 + 16 = 256 exactly, and
; 240 + 32 = 272, which pokes sixteen rows of a 32-tall sprite back onto
; scanlines 0..15 as a band of debris along the top of the picture.
;
; It shipped that way for one recording. The blades are 32-tall and were parked
; at the 16-tall constant, and two swords sat at the top of the screen through
; the entire clip — invisible to every byte assertion, because the OAM entry
; was exactly what the code intended. Caught by looking at the render.
SV_PARK_Y   = 240               ; the 16x16 HUD sprites
SV_PARK_Y32 = 224               ; ...and the 32x32 blades

; --- the animation tables (tools/gen_split_v_assets.py ANIM_TABLES) --------
; The state word is ALSO the table's stride index, so the clock and the draw
; cannot pick different tables.
SV_ST_IDLE = 0
SV_ST_WALK = 1
SV_ST_JUMP = 2
SV_ST_ATK  = 3
SV_ST_HIT  = 4
SV_ST_KO   = 5
SV_ANIM_STRIDE = 4              ; frames per table in sv_anim.bin
SV_META_STRIDE = 2              ; (len, rate) per table in sv_anim_meta.bin

; --- the pad bits ---------------------------------------------------------
; $4218 (JOY1) and $421A (JOY2) share a layout, so these apply to both pads.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_UP    = 1 << 11
JOY_A     = 1 << 7              ; attack
JOY_B     = 1 << 15             ; jump — and so does Up, because both are what
                                ; a hand reaches for and neither costs anything

.endif ; SPLIT_V_INC
