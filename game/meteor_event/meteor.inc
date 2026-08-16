; =============================================================================
; meteor.inc — the meteor_event rail's own vocabulary (constants only; state is
; allocator-emitted via state.toml, addresses via the generated maps)
; =============================================================================
; Names carry the MET_ prefix. Bit masks are SHIFTS and dimensions are decimal:
; no_literals refuses hex forms that look like addresses, and the gate is right.

; --- the state machine -----------------------------------------------------
MET_ST_PLAY    = 0              ; Mode 1: walk right toward the trigger
MET_ST_FREEZE  = 1              ; input GATED, the frozen frame held
MET_ST_CAPTURE = 2              ; the BG->OBJ capture + BG dropped from TM
MET_ST_SCENE   = 3              ; the Mode 7 cutscene (the `impact` scene)
MET_ST_RESTORE = 4              ; the swap-back request

; --- pacing ----------------------------------------------------------------
MET_TRIGGER_X    = 240          ; world X at which the event fires
MET_FREEZE_HOLD  = 40           ; frames held frozen before capture
MET_CAPTURE_HOLD = 30           ; frames the captured-over-black frame holds,
                                ;   stated as its own span because this rail
                                ;   resets the timer at each transition

; --- the player ------------------------------------------------------------
MET_PLAYER_SCRN_X = 96          ; fixed screen x; the world scrolls under it
MET_PLAYER_Y      = 176         ; sits on the ground (top y 192, 16 px tall)
MET_WALK_SPEED    = 2           ; world px/frame

; --- ground / platform geometry (BG1 tile grid, 32x32, 8 px tiles) ---------
; ONE deliberate departure from a one-row platform layout: the raised platforms
; here are TWO rows tall, so every 16x16 captured block covers exactly the cells
; it captured and the alignment invariant is exact over the WHOLE frame — which
; is what lets the test compare green pixel masks before and after the BG is
; dropped instead of comparing a sub-region.
MET_GND_ROW0  = 24              ; flat ground, rows 24..27, all 32 columns
MET_GND_ROW1  = 27
MET_PLAT_A_R0 = 18              ; platform A, rows 18..19, cols 6..9
MET_PLAT_A_R1 = 19
MET_PLAT_A_C0 = 6
MET_PLAT_A_C1 = 9
MET_PLAT_B_R0 = 14              ; platform B, rows 14..15, cols 20..23
MET_PLAT_B_R1 = 15
MET_PLAT_B_C0 = 20
MET_PLAT_B_C1 = 23

MET_MAP_COLS  = 32              ; the BG1 tilemap is 32x32 and WRAPS
MET_MAP_ROWS  = 32
MET_COL_MASK  = 31              ; (basecol + sc) & this -> wrap to the row

; --- BG CHR tile ids -------------------------------------------------------
MET_BG_BLANK = 0                ; colour index 0 -> transparent -> backdrop
MET_BG_PLAT  = 1                ; the solid green platform/ground block

; --- the scene's base display ----------------------------------------------
MET_TM_BG1 = 1                  ; TM bit 0
MET_TM_OBJ = 1 << 4             ; TM bit 4

; =============================================================================
; THE LOCKED TWO-PHASE METEOR
; =============================================================================
MET_SPRITE_END = 72             ; 0..71 : the far-approach SPRITE phase
MET_SCN_END    = 180            ; 72..179 : the MODE-7 phase

; the crossover point: the screen pixel where the sprite hands to the plane
MET_CROSS_X = 76
MET_CROSS_Y = 62

; (A) the sprite sweep: centre = (X0 + t, Y0 + t), step 1. Y0 is
; NEGATIVE (just off the top edge), so it is written as a subtraction the
; assembler folds rather than as a two's-complement literal.
MET_SPR_X0 = MET_CROSS_X - MET_SPRITE_END           ; 4
MET_SPR_Y0 = MET_CROSS_Y - MET_SPRITE_END           ; -10

; growth-frame thresholds on the scene timer: three 16x16 FIERY
; specks then three 32x32 ROCKY frames, the last being the crossover frame
MET_FR_F1 = 12
MET_FR_F2 = 24
MET_FR_R0 = 36
MET_FR_R1 = 48
MET_FR_R2 = 60
MET_FLIP_PERIOD = 7             ; frames per orientation step

; (C) the Mode-7 phase's slide: the meteor centre goes
; (CROSS_X, CROSS_Y) -> off the bottom-right at 3 px/frame on both axes, and
; the pivot stays PINNED at the art centre, so the motion is purely the
; screen origin: HOFS = MET_CX - (CROSS_X + 3m), VOFS = MET_CY - (CROSS_Y + 3m).
MET_SLIDE = 3
MET_CX = 1 << 9                 ; the meteor art centre, map px
MET_CY = 1 << 9                 ;   — half of the 1024 px field

; the off-field origin the SPRITE phase parks the plane at. With
; M7SEL bit 7 set, everything outside the 1024-px field shows the BACKDROP,
; so the plane reads black behind the opening sprite.
MET_OFF_HOFS = 1400
MET_OFF_VOFS = 1400

; --- the red glow, synced to the descent -----------------------------------
; m = the Mode-7 elapsed frame (g_timer - MET_SPRITE_END).
MET_GLOW_START      = 20        ; m >= this : the glow rises
MET_GLOW_PEAK       = 56        ; rise 20..56, then HOLD
MET_GLOW_HOLD_END   = 80        ; hold 56..80
MET_GLOW_RECEDE_END = 104       ; recede 80..104, done before SCN_END (m 108)
MET_GLOW_MAX        = 31        ; COLDATA intensity is 5 bits
MET_GLOW_QUANT      = 7         ; quantise to steps of 8 -> `and #~7`, written
                                ;   as the mask it complements

; --- OBJ vocabulary ---------------------------------------------------------
MET_PARK_Y = 240                ; off the visible 224 — where slots park
MET_LARGE  = 2                  ; the hi-table SIZE bit (32x32 half of pair 3)
MET_PRIO   = 3 << 4             ; OAM attr: priority 3, over the Mode 7 plane
MET_HFLIP  = 1 << 6             ; OAM attr bit 6
MET_VFLIP  = 1 << 7             ; OAM attr bit 7

; sheet layout — gen_meteor_assets.py's, on the PPU's 16-tile VRAM row grid
MET_T_ROCK0  = 0                ; 32x32 ROCKY r=10   (4x4 block from tile 0)
MET_T_ROCK1  = 4                ; 32x32 ROCKY r=13
MET_T_ROCK2  = 8                ; 32x32 ROCKY r=15.5 — the crossover frame
MET_T_BLOCK  = 64               ; 16x16 captured ground/platform block
MET_T_PLAYER = 66               ; 16x16 player
MET_T_FIERY0 = 68               ; 16x16 FIERY r=3
MET_T_FIERY1 = 70               ; 16x16 FIERY r=5
MET_T_FIERY2 = 72               ; 16x16 FIERY r=7

; --- pad bits (JOY1 standard layout; input.asm's $4218 word) ---------------
MET_JOY_RIGHT = 1 << 8

; --- the glow's HDMA table shape (met_glow.asm builds it) ------------------
MET_GLOW_BANDS = 8              ; eight band entries, top to bottom
MET_GLOW_LINES = 28             ; 8 * 28 = 224 active scanlines
MET_COLDATA_R  = 1 << 5         ; COLDATA plane-select bit for RED
