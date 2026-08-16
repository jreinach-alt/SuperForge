; =============================================================================
; platformer.inc — the rail's geometry, physics constants and state vocabulary
; =============================================================================
; Included by main.asm before anything else, so every scene and every feature
; asm sees one set of numbers. Nothing here is an ADDRESS: addresses come from
; the allocator's emitted includes, and no_literals proves it.

; --- $4218 bit POSITIONS. Written as shifts because a bare 4096 is also a
;     plausible VRAM word address and no_literals cannot know which you meant.
JOY_RIGHT  = 1 << 8
JOY_LEFT   = 1 << 9
JOY_DOWN   = 1 << 10
JOY_UP     = 1 << 11
JOY_START  = 1 << 12
JOY_SELECT = 1 << 13
JOY_A      = 1 << 7
JOY_B      = 1 << 15

; --- the world, in cells and pixels -----------------------------------------
PLF_MAP_W      = 64            ; cells across: 512 px, two 32x32 hardware pages
PLF_MAP_H      = 32            ; cells down: 28 visible + 4 spare (see the
                               ;   level blob's claim — the spare rows make the
                               ;   probe's row index a mask)
PLF_SKY_PERIOD = 8             ; BG2's column period, 64 px
PLF_WORLD_W    = PLF_MAP_W * 8         ; 512 px — derived, so the number the
                                       ;   walk clamps against cannot drift
                                       ;   from the map it clamps inside
PLF_SCREEN_W   = 256
PLF_CAM_MAX    = PLF_WORLD_W - PLF_SCREEN_W    ; the camera stops with the world's
                                       ;   right edge on the screen's right

; --- tile ids (a level byte IS a tile number, and also indexes the flags) ----
PLF_T_SKY   = 0
PLF_T_GRND  = 1
PLF_T_LEDGE = 2
PLF_T_PLAT  = 3
PLF_T_COIN  = 4
PLF_T_DIRT  = 5
PLF_T_COUNT = 9                ; ...plus cloud, hill body, hill crest on BG2

; --- collision flags, one byte per tile id ----------------------------------
PLF_F_SOLID = 1                ; blocks every direction
PLF_F_PLAT  = 2                ; ONE-WAY: blocks only a downward crossing
PLF_F_COIN  = 4                ; walk-through, picked up on touch

; --- the parallax bands -----------------------------------------------------
; y_split 96: clouds above, hills below. It is an HDMA non-repeat COUNT byte,
; so it must be 1..128, and the two bands below it must also each fit in one
; entry -- 224 - 96 = 128 exactly, which is why the table is three entries and
; not four. (128 is the largest legal count: $80. A split below 96 would need
; the bottom band split in two.)
PLF_PLX_SPLIT = 96
PLF_PLX_LINES = 224

; The ratios are POWERS OF TWO so the rebuild is shifts, not a multiply, and
; therefore needs no claim on the ALU. $0020 / $0060 are 32/256 and 96/256 --
; exactly 1/8 and 3/8.
;   top (far clouds) = cam >> 3
;   bot (near hills) = (cam + cam*2) >> 3
PLF_PLX_SHIFT = 3

; --- physics (8.8 where the name says F) ------------------------------------
PLF_GRAVITY   = $0030          ; 0.1875 px/frame^2
PLF_JUMP_VEL  = $FC00          ; -4.0 px/frame at the launch
PLF_JUMP_CUT  = $FE00          ; releasing the button clamps a rise to -2.0
PLF_MAX_FALL  = $0400          ; terminal velocity, 4.0 px/frame — the number
                               ;   the LANDING frame depends on, which is why
                               ;   the jump test asserts the rest position and
                               ;   not just the apex
PLF_WALK      = 2              ; px/frame
PLF_BOX       = 8              ; the hero's physics box is 8x8; the SPRITE is
                               ;   16x16 drawn at (box.x - 4, box.y - 8)

PLF_SPAWN_X   = 24
PLF_SPAWN_Y   = 184            ; box rest on the ground surface (row 24 top=192)
PLF_PIT_Y     = 216            ; box y past this = fallen below the world
PLF_LIVES     = 3
PLF_COINS_ALL = 6

; --- the ghosts -------------------------------------------------------------
PLF_G1_Y      = 184            ; ghost 1's beat is the ground
PLF_G2_Y      = 120            ; ghost 2's is the seam ledge (row 16, top 128)
PLF_G1_X      = 112
PLF_G2_X      = 240
PLF_G1_MIN_X  = 64             ; ghost 1 turns back east here, so its beat
                               ;   never reaches spawn — a fair start
PLF_GHOST_W   = 8              ; the ghost's contact box, like the hero's

; --- i-frames, and the blink they drive -------------------------------------
PLF_GRACE     = 60             ; granted at the start of a fresh level
PLF_RESPAWN_I = 90             ; ...and on a mid-level respawn
PLF_BLINK     = 4              ; hidden while (hurt & 4): ~4 frames on, 4 off

; --- animation --------------------------------------------------------------
PLF_ANIM_RATE = 8              ; frames per step
PLF_ANIM_STEPS = 4             ; the pack's four idle frames

; --- the OBJ pages' frame bases (see platformer_obj/feature.toml's layout) ---
; A MULTIPLE OF 16 EACH, and 32 apart. That is the imported blobs' load
; contract, and it is hardware: a 16x16 OBJ reads {N, N+1, N+16, N+17}, so a
; four-frame sheet occupies TWO 16-wide tile rows = 32 tiles, and two actors
; spaced 16 apart would put the second's top row on the first's bottom row.
; These bases are a multiple of 16 each and 32 apart, for that reason.
PLF_HERO_TILE  = 0             ; frame f occupies tiles {2f, 2f+1, 2f+16, 2f+17}
PLF_GHOST_TILE = 32

; --- the feet anchor, PER FRAME ---------------------------------------------
; WHERE AN ACTOR'S SOLES LAND, and it takes four numbers per actor, not one.
;
; THE HARDWARE TERM FIRST. An OBJ renders one scanline BELOW its OAM y: the
; PPU evaluates a line's sprites during the PREVIOUS line and fills the OBJ
; line buffer a scanline ahead (Mesen2 `SnesPpu::EvaluateNextLineSprites`
; tests `IsVisible(_scanline)` and draws the result on _scanline + 1). So a
; sprite at OAM y = N first draws on scanline N+1. MEASURED: OAM y 176 puts the
; hero's box row 0 on scanline 177.
;
; THE ART TERM SECOND. `content_bottom` is a frame's lowest drawn row + 1
; inside its 16-px box. png2snes emits ONE number per actor, documented as the
; MAX over frames -- and the hero's four frames are [16,15,15,15], so no
; single number is right for all of them. (The spread is the importer's
; centring, not the artist's: the pack's four hero frames share one bottom and
; bob at the head. gen_platformer_assets.py prints both columns.)
;
; PUT TOGETHER: for the frame's last drawn row to land on the last scanline
; ABOVE the surface,
;     OAM_y = surface_top - 1 - content_bottom(frame)
; and since surface_top = US_PIXY + PLF_BOX, the draw code subtracts
;     PLF_*_LIFT(frame) = content_bottom(frame) - PLF_BOX + 1
; from US_PIXY. Two defects trace to the same missing "- 1": without it the
; tallest frame's soles land ON the surface line, so an actor whose frames
; differ overlaps INTERMITTENTLY (the hero) and one anchored on a uniform value
; at or below every frame's bottom overlaps on EVERY frame (the ghost).
PLF_OBJ_Y_LAG = 1              ; scanlines an OBJ renders below its OAM y

PLF_HERO_LIFT_F0 = 16 - PLF_BOX + PLF_OBJ_Y_LAG   ; content_bottom 16
PLF_HERO_LIFT_F1 = 15 - PLF_BOX + PLF_OBJ_Y_LAG   ; content_bottom 15
PLF_HERO_LIFT_F2 = 15 - PLF_BOX + PLF_OBJ_Y_LAG
PLF_HERO_LIFT_F3 = 15 - PLF_BOX + PLF_OBJ_Y_LAG

PLF_GHOST_LIFT_F0 = 15 - PLF_BOX + PLF_OBJ_Y_LAG  ; the ghost's four agree,
PLF_GHOST_LIFT_F1 = 15 - PLF_BOX + PLF_OBJ_Y_LAG  ;   which is why its overlap
PLF_GHOST_LIFT_F2 = 15 - PLF_BOX + PLF_OBJ_Y_LAG  ;   was constant rather than
PLF_GHOST_LIFT_F3 = 15 - PLF_BOX + PLF_OBJ_Y_LAG  ;   a flicker

; --- the save's format ------------------------------------------------------
PLF_SAVE_SLOT = 0
PLF_SAVE_VER  = 1
PLF_SAVE_LEN  = 2              ; payload = the 16-bit coin bank

; --- the scene ids, in game.toml manifest order -----------------------------
SCENE_TITLE = 0
SCENE_PLAY  = 1
SCENE_OVER  = 2
SCENE_WIN   = 3

; --- the colour-math target -------------------------------------------------
; CGADSUB's layer mask for rgb_gradient's ramp: bit5 = BACKDROP.
; Written as a shift because a bare $20 is also a
; offset, and the name is the only thing that says which.
PLF_MATH_BACKDROP = 1 << 5

; --- shared colours ---------------------------------------------------------
; CGRAM word 0 in the PLAY scene: BLACK, because that is what the dusk ramp is
; painted ON. The colour math ADDs rgb_gradient's per-scanline COLDATA to the
; backdrop, so the sky the player sees IS the ramp; any non-zero base would
; lift the ramp's whole range and desaturate it (a $1082 base was exactly a
; teal sky an earlier revision shipped). CGRAM 0 is $0000 — measured off the
; running ROM, not read off the source.
PLF_PLAY_SKY = $0000

; CGRAM word 0 in the THREE MENU scenes, which have no gradient of their own:
; one flat mid-dusk so the cards read as the same evening as the round. Running
; the menus over the live gradient is not available here, because rgb_gradient
; is composed into `play` only (game.toml) and a menu has no BG feature to hang
; the three channels' blob off. A flat swatch out of the MIDDLE OF THE RAMP is
; the honest approximation and it is one word.
;
; DERIVED, not picked: it is the ramp's own scanline 112, (13,4,7) ->
; 13 | 4<<5 | 7<<10. `test_the_menu_backdrop_is_the_ramps_own_midpoint` reads
; it out of CGRAM in all three menu scenes and recomputes it from the blob, so
; it cannot drift away from the sky it is standing in for. (The $1082 teal that
; used to be here was an earlier ramp's base, and once the ramp moved to the
; backdrop it stopped being anything at all.)
PLF_DUSK = $1C8D
