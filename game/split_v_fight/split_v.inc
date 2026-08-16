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

; --- the pad bits ---------------------------------------------------------
; $4218 (JOY1) and $421A (JOY2) share a layout, so these apply to both pads.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9

.endif ; SPLIT_V_INC
