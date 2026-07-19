; =============================================================================
; meteor_event — an in-level "meteor event" cutscene that swaps Mode-1 <-> Mode-7
; =============================================================================
; A tiny Mode-1 platformer slice that becomes a cutscene and returns: you walk the
; player right until a meteor event triggers, the screen freezes and captures the
; platforms as sprites, forced-blank-swaps to a STATIC Mode-7 meteor scene, plays
; the meteor's approach, then swaps back and hands control back. The whole thing
; is one state machine:
;   PLAY -> FREEZE -> CAPTURE -> SCENE(grow->fall->glow->recede) -> RESTORE -> PLAY.
;
; The Mode-7 payoff runs three stages, each its own subroutine below:
;   meteor zoom/scale/FALL  — ramp g_scale so the meteor GROWS, then drive the
;                             Mode-7 pivot DOWN (sf_boss_center Y) so it EXITS the
;                             bottom.
;   red impact glow         — a red ADD gradient that RISES to occupy the lower
;                             band BEHIND the OBJ sprites (OBJ excluded from color
;                             math, so the captured green ground + white player
;                             stay un-tinted), HOLDS, then RECEDES.
;   swap back + restore     — sf_swap_to_mode1_begin/end re-builds the Mode-1
;                             level (BG CHR + tilemap + shared palette), drops the
;                             captured OBJ ground, UNFREEZES and RELEASES control.
;
; Controls:  D-pad RIGHT walks the player right (toward the trigger). During the
;            cutscene the D-pad is GATED (the player does not move); control is
;            released again after the meteor event ends.
;
; File layout (major banners, top to bottom):
;   INIT         — RESET: OBJ + Mode-1 BG upload under forced blank, arm the red
;                  glow, paint the level, seed the state machine
;   MAIN LOOP    — game_loop: the state jump table (do_play .. do_restore)
;   SUBROUTINES  — the state helpers + scene stages (enter_scene, scene_glow,
;                  exit_scene) + the BG->OBJ platform capture
;   ENGINE+DATA  — engine link partners, the capture row table, the assets + map
;
; game_loop is the once-per-frame heartbeat — start reading there.
;
; THE STORY (a real, tiny Mode-1 platformer slice that becomes a cutscene):
;
;   ST_PLAY   Mode 1. A flat ground (BG1 tile rows 24..27) + two raised
;             platforms (BG1 platform tiles), and a player OBJ the D-PAD walks
;             RIGHT across the screen. The player advances in WORLD X; the
;             camera (BG1 HOFS) follows. When the player reaches the "open flat
;             ground" TRIGGER (world X >= TRIGGER_X), the event begins.
;
;   ST_FREEZE The meteor is coming. FREEZE: physics + scroll halt, and INPUT IS
;             GATED — the D-pad no longer moves the player (proven on rendered
;             output: the player pixel does not move while input is held). The
;             frozen frame is held briefly so the freeze is observable.
;
;   ST_CAPTURE THE CRUX. Walk the visible BG1 tilemap; for every on-screen
;             PLATFORM cell emit an OBJ sprite pixel-aligned where that BG tile
;             was (spr tile, mx*8 - hofs, my*8 - vofs). Then BLACK the Mode-1 BG
;             (drop BG from TM) so only the captured OBJ ground remains — it
;             lands on the SAME pixels the BG tiles occupied (the alignment proof).
;
;   ST_SCENE  Forced-blank SWAP to the Mode-7 meteor scene via the
;             sf_swap_to_mode7 primitive: blank, re-upload the meteor map,
;             re-stage its palette, switch to whole-plane affine Mode 7, unblank.
;             A STATIC meteor on the Mode-7 BG with the captured platforms+player
;             composited as OBJ on top. (The scene stages grow/fall it here.)
;
; Kit macros used:
;   sf_coldstart / sf_engine_init        boot baseline (sf_core / sf_frame)
;   gfxmode / mset / sf_load_bg_chr      Mode 1 BG ground + platforms (sf_bg/sf_video)
;   spr / spr_clear                      OBJ player + the captured platform sprites
;   sf_load_obj_chr / sf_load_obj_pal    OBJ CHR/pal at the Mode-7-safe base $4000
;   btn (BTN_RIGHT)                      D-pad walk + the gated-input proof (sf_input)
;   sf_swap_to_mode7                     the forced-blank Mode-1->Mode-7 swap
;   sf_boss_mode7_on / center / matrix   whole-plane affine meteor (sf_mode7_affine)
;   sf_mode7_load_map                    the meteor VRAM blob DMA (sf_mode7)
;
; -D BUILD CONTROLS (non-vacuity; build via build_meteor_event_variants.sh):
;   -DNO_CAPTURE  skip the BG->OBJ capture -> at the swap the ground VANISHES to
;                 black (the capture alignment test MUST FAIL on this build).
;   -DNO_FREEZE   input still moves the player during "freeze" (the freeze test
;                 MUST FAIL on this build).
;
; Build:  make meteor_event   (generic templates rule reads the LDCFG sentinel)
; LDCFG: lorom_64k.cfg
;   ^ 64KB image: the 32KB meteor Mode-7 map blob fills BANK1.
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "METEOR EVENT"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_chr
.include "sf_input.inc"         ; btn / btnp
.include "sf_mode7.inc"         ; sf_mode7_load_map
.include "sf_mode7_affine.inc"  ; sf_boss_mode7_on / sf_boss_center / sf_boss_matrix
.include "sf_fx.inc"            ; sf_gradient_rgb/_update/_ease + sf_colormath_on/off
.include "sf_scene_mode.inc"    ; sf_blank_enter/exit + sf_swap_to_mode7/_mode1
.include "engine_state.inc"

; --- state machine ---
ST_PLAY    = 0
ST_FREEZE  = 1
ST_CAPTURE = 2
ST_SCENE   = 3
ST_RESTORE = 4          ; swap Mode-7 -> Mode-1, rebuild the level
; after ST_RESTORE the machine returns to ST_PLAY with control RELEASED.

; =============================================================================
; LOCKED METEOR DESIGN — a ~3s (~180-frame) two-phase approach:
;   (A) SPRITE PHASE  (g_timer 0..SPRITE_END): the very-small far approach. The
;       Mode-7 plane is scrolled OFF-FIELD (black backdrop); a meteor OBJ sprite
;       enters off-screen upper-left and moves toward the interior, GROWING
;       through 4 discrete pre-drawn frames (FAR 16x16 tiny -> MID 16x16 ->
;       BIG 32x32 -> QUAD 64x64). Reaches ~64px at the crossover.
;   (B) CROSSOVER     (g_timer == SPRITE_END): hide the sprite, reveal the Mode-7
;       meteor plane scaled to ~the sprite's final on-screen size (~64px) at the
;       SAME screen point the sprite occupied (CROSS_X,CROSS_Y). 1-frame blank ok.
;   (C) MODE-7 PHASE  (g_timer SPRITE_END..SCN_END): the plane scales UP from the
;       crossover size to FULL, CENTERED about the affine pivot (M7X/M7Y=512=the
;       meteor art centre) so it grows IN PLACE; the SCROLL slides the meteor off
;       the bottom-right (translation decoupled from the centred scale); a SLOW
;       TUMBLE ramps the affine angle a small step/frame throughout.
; =============================================================================

; --- meteor affine pivot (map px): the meteor art is dead-centred on tile
;     (64,64) = pixel (512,512), so the pivot == the art centre -> the Mode-7
;     zoom grows IN PLACE and the tumble spins about the centre (no drift). ---
MET_CX = 512
MET_CY = 512

; --- scene sub-timeline (g_timer frames from ST_SCENE entry) ---
SPRITE_END   = 72               ; 0..71  : SPRITE PHASE (~1.2s @60fps)
SCN_END      = 180              ; 72..179: MODE-7 PHASE (~1.8s) -> ST_RESTORE at 180
M7_LEN       = SCN_END - SPRITE_END   ; 108 : Mode-7 phase length in frames

; --- crossover point: the screen pixel where the sprite hands off to the plane.
;     Upper-left-of-centre so the Mode-7 slide has room to carry it off bottom-right.
CROSS_X      = 76
CROSS_Y      = 62

; --- (A) SPRITE PHASE: the meteor sprite CENTRE drifts in from just off the
;     top-left edge to (CROSS_X,CROSS_Y). centre = (X0+t, Y0+t), step 1 (72px over
;     72 frames) — multiply-free, AND a short enough travel that the small FIERY
;     specks are on-screen and visible from early in the phase (a far speck only a
;     few px off the corner, not a point flung in from way off-screen):
;       t=0 -> (4,-10) just off the top edge ; t=72 -> (76,62) = crossover.
SPR_STEP     = 1                ; px/frame along the streak (X and Y)
SPR_X0       = CROSS_X - SPR_STEP * SPRITE_END   ; 4
SPR_Y0       = CROSS_Y - SPR_STEP * SPRITE_END   ; -10
; sprite-frame thresholds (g_timer): SIX single-sprite frames, ~12 frames each,
; growing FIERY r3->r5->r7 (16x16) then ROCKY r10->r13->r15.5 (32x32). The last
; (R2, r15.5) is the ~32px crossover frame that resembles the Mode-7 rock.
SPR_FR_F1    = 12               ; t>=12 : FIERY r5
SPR_FR_F2    = 24               ; t>=24 : FIERY r7
SPR_FR_R0    = 36               ; t>=36 : ROCKY r10 (32x32 large)
SPR_FR_R1    = 48               ; t>=48 : ROCKY r13
SPR_FR_R2    = 60               ; t>=60 : ROCKY r15.5 (full sprite = crossover frame)
; FLIP-CYCLE TUMBLE (sprite phase only — OBJ can't truly rotate): cycle the meteor
; sprite orientation {normal, H-flip, V-flip, H+V} every SPR_FLIP_PERIOD frames so
; the off-centre craters reorient frame-to-frame (an illusion of spin). The Mode-7
; phase keeps the real smooth affine tumble.
SPR_FLIP_PERIOD = 7             ; frames per orientation step (~6-8 as requested)

; --- (C) MODE-7 PHASE scale ramp (1.7.8; SMALLER value = BIGGER on screen).
;     Crossover scale reveals the Mode-7 meteor at ~32px to MATCH the final 32x32
;     sprite frame (Mode 7's smallest CLEAN render of the full rock); the ramp then
;     shrinks the scale toward FULL so the meteor grows centred on the pivot.
;     Measured: $0E00 ~= 32px on-screen (tuned on the emulator vs the R2 sprite).
MET_SCALE_CROSS = $0E00         ; ~32px on-screen meteor at the crossover
MET_SCALE_FULL  = $0220         ; full-size meteor (nearly fills the screen height)
; step/frame: a brisk ramp so the meteor visibly grows in the pre-glow window
; (m 0..20) — ($0E00-$0220)=$0BE0=3040; /48 ~= 63 frames to reach FULL, about when
; the meteor has slid off the bottom, so it grows for the whole visible Mode-7
; flight. A faster ramp also gives the GROW test a clean real-vs-NO_SCALE
; separation before the glow rises and pollutes the meteor-texel count.
MET_SCALE_STEP  = $0030         ; 48/frame

; --- (C) MODE-7 PHASE slide: the meteor CENTRE goes (CROSS_X,CROSS_Y) -> off the
;     bottom-right. The pivot stays PINNED at the art centre (centred scale), so we
;     move the meteor purely by the BG scroll: render the pivot at screen (Sx,Sy)
;     via HOFS=MET_CX-Sx, VOFS=MET_CY-Sy. m = g_timer - SPRITE_END (0..108).
;     Sx = CROSS_X + SLIDE_SX*m ; Sy = CROSS_Y + SLIDE_SY*m.
SLIDE_SX     = 3                ; px/frame right (45-deg slide; scene_slide uses 3m)
SLIDE_SY     = 3                ; px/frame down  (from (76,62) -> bottom-right corner ~(238,224) at m54)
; the off-field scroll used during the SPRITE PHASE (plane fully off-screen ->
; black backdrop; M7SEL bit7=1 shows backdrop, not wrap). Far from the meteor.
OFF_HOFS     = 1400
OFF_VOFS     = 1400

; --- TUMBLE: a SLOW rotation ramp (a few seconds per revolution). 256 angle units
;     = one full turn; over the ~108-frame Mode-7 phase a step of 4/frame -> ~432
;     units = ~1.7 turns (gentle). -DNO_TUMBLE holds the angle at 0 (the control).
TUMBLE_STEP  = 4

; --- RED GLOW: synced to the descent. Rises as the meteor nears the bottom in the
;     Mode-7 phase, holds, then recedes after it exits. Tracks m (Mode-7 elapsed).
GLOW_START   = 20               ; m>=20 : glow rises (meteor descending)
GLOW_PEAK    = 56               ; rise 20..56 (BOT_R 0 -> ~31), then HOLD
GLOW_HOLD_END= 80               ; m 56..80 : HOLD at peak red
GLOW_RECEDE_END = 104           ; m 80..104 : recede (BOT_R -> 0) before SCN_END (m108)
GLOW_RISE_STEP  = 1             ; BOT_R units per rise frame (quantised in scene_glow)

; --- ground / platform geometry (BG1 tile grid, 32x32; 8px tiles) ---
; flat ground = tile rows 24..27 (pixel y 192..223), full 32 cols, CHR tile 1.
GND_ROW0 = 24
GND_ROW1 = 27
; two raised platforms (each 4 tiles wide, CHR tile 1), at row 18 and row 14.
PLAT_A_ROW = 18
PLAT_A_C0  = 6
PLAT_A_C1  = 9            ; cols 6..9 inclusive
PLAT_B_ROW = 14
PLAT_B_C0  = 20
PLAT_B_C1  = 23          ; cols 20..23 inclusive

; --- BG CHR tile IDs ---
BG_BLANK = 0             ; black
BG_PLAT  = 1            ; green platform/ground (matches OBJ green)

; --- OBJ name base = VRAM word $4000 (tile 1024). Mode 7 owns $0000-$3FFF. ---
; OBSEL $62 -> small = 16x16, large = 32x32. The `spr` flags bit7 selects large.
OBJ_BASE_TILE = 1024
OBJ_GROUND    = OBJ_BASE_TILE + 0   ; 16x16 green block (captured platform/ground)
OBJ_PLAYER    = OBJ_BASE_TILE + 2   ; 16x16 white block (player)
; --- meteor SPRITE growth frames (CHR generated by make_assets.py). Each is a
;     SINGLE OBJ sprite. Three 16x16 FIERY specks then three 32x32 ROCKY frames;
;     the last (r15.5) is the crossover frame and resembles the Mode-7 rock so the
;     hand-off at ~32px is seamless (no QUAD, no 64px). ---
OBJ_MET_F0    = OBJ_BASE_TILE + 4    ; 16x16 FIERY r=3   (base tile 4)
OBJ_MET_F1    = OBJ_BASE_TILE + 6    ; 16x16 FIERY r=5   (base tile 6)
OBJ_MET_F2    = OBJ_BASE_TILE + 8    ; 16x16 FIERY r=7   (base tile 8)
OBJ_MET_R0    = OBJ_BASE_TILE + 64   ; 32x32 ROCKY r=10  (base tile 64)
OBJ_MET_R1    = OBJ_BASE_TILE + 68   ; 32x32 ROCKY r=13  (base tile 68)
OBJ_MET_R2    = OBJ_BASE_TILE + 72   ; 32x32 ROCKY r=15.5 (base tile 72, crossover)
SPR_FLAG_SMALL = $00            ; flags: pal/name 0, small size (16x16)
SPR_FLAG_LARGE = $80            ; flags: bit7 = large (32x32) size select
SPR_FLAG_HFLIP = $40            ; flags: bit6 = H-flip (engine_spr keeps bit6)
; V-flip = OAM attr bit7, NOT reachable through the spr macro (engine_spr masks
; with and #$4F). The flip-cycle pokes it directly into the returned slot's
; shadow-OAM attribute byte (SHADOW_OAM_BASE + slot*4 + 3). SHADOW_OAM_BASE=$0300.
OAM_ATTR_VFLIP = $80

; --- player ---
PLAYER_SCRN_X = 96           ; player's fixed SCREEN x (the world scrolls under it)
PLAYER_Y      = 176          ; sits on the flat ground (ground top = y192; 16px tall)
WALK_SPEED    = 2            ; world px/frame

; --- trigger: world X at which the meteor event fires ---
TRIGGER_X     = 240
; how long ST_FREEZE is held (frames) before capture+swap, so the freeze and
; the input-gate are observable across several captured frames.
FREEZE_HOLD   = 40

; --- game DP ($32-$5F game zone; engine owns $00-$31 + $60+) ---
g_state       = $32  ; current ST_*
g_worldx      = $34  ; player world X (px, 16-bit)
g_camx        = $36  ; BG1 HOFS = camera world X (px)
g_timer       = $38  ; per-state frame timer (scene sub-timer in ST_SCENE)
g_scale       = $3A  ; affine scale mirror (the Mode-7 phase ramps this down)
g_frozen_camx = $3C  ; camera X latched at FREEZE (capture reads the frozen view)
g_cap_done    = $3E  ; ST_CAPTURE BG-black guard (once)
g_scene_done  = $40  ; ST_SCENE swap guard (once)
; --- persistent scene game state ---
; These DP bytes ($42-$4F) belong to engine subsystems (color-math / font /
; HDMA-CH3 shadows in engine_state.inc) that THIS template never activates, so
; the meteor_event game safely reuses them as its own state zone — exactly the
; Phase-1 reuse pattern for $32-$40. They stay covered by ES_* symbols, so
; `make zp-check` is clean. None live in the volatile $54-$60 draw scratch.
g_glow        = $44  ; current red-glow bottom intensity (0..31)
g_cm_on       = $46  ; color-math-ON one-shot guard (glow rise)
g_cm_off      = $48  ; color-math-OFF one-shot guard (glow end)
g_restore_done= $4A  ; ST_RESTORE swap guard (once)
g_event_done  = $4C  ; 1 once the event has fired (don't re-trigger after release)
g_angle       = $4E  ; meteor affine TUMBLE angle (16-bit; low byte = sf_boss_matrix turn)
g_scr         = $42  ; frame-transient scratch word (the swept screen position +
                     ; scale/glow ramps are recomputed from g_timer each frame, so
                     ; no posx/posy DP is stored — $50-$69 is the engine HDMA zone
                     ; the gradient uses (PROJ_SX=$50/PROJ_SY=$52 get clobbered)).
; NOTE: the per-frame draw_capture_sprites scratch lives at $54-$60 and is
; clobbered every frame — persistent state-machine guards must NOT live there.

; --- debug mirrors (SEQUENCE captures only; never an assertion proof) ---
DBG_HEART = $E010    ; frame counter
DBG_STATE = $E012    ; g_state
DBG_WORLDX= $E014    ; player world X
DBG_CAMX  = $E016    ; camera X
DBG_BGMODE= $E018    ; live SHADOW_BGMODE (for the mode-FLIP SEQUENCE assertion
                     ;   only — the PROOF of each mode is the framebuffer)

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

; =============================================================================
; INIT — power-on setup: upload OBJ + Mode-1 BG CHR/palettes under forced blank,
; arm the red-glow gradient, paint the level, seed the state machine, screen + NMI.
; =============================================================================
RESET:
    sf_coldstart
    sf_engine_init

    ; stable OAM slot order (slot = call order after spr_clear)
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; ------------------------------------------------------------------ setup
    ; (under the coldstart forced blank)
    ;
    ; (1) Mode 7 meteor map is uploaded LATER (in the swap), NOT here: BG1 CHR
    ;     (word $2000) overlaps the Mode 7 region ($0000-$3FFF), so uploading it
    ;     now would make the Mode-1 BG read meteor bytes as CHR. Leave VRAM
    ;     $0000-$3FFF coldstart-clean for the Mode-1 phase.
    ;
    ; (2) OBJ CHR + palette at the Mode-7-safe base (word $4000 = tile 1024).
    sf_load_obj_pal 0, meteor_obj_pal
    sf_load_obj_chr OBJ_BASE_TILE, meteor_obj_chr, meteor_obj_chr_bytes
    sep #$20
    .a8
    lda #$62                    ; OBSEL: OBJ name base word $4000, 16x16/32x32
    sta $2101
    rep #$30
    .a16
    .i16

    ; (3) Mode 1 BG. gfxmode sets bases + clears tilemaps but ALSO turns the
    ;     screen ON (INIDISP=$0F) and does NOT enable NMI — so RE-RAISE forced
    ;     blank for the CHR/pal uploads.
    gfxmode #1
    sep #$20
    .a8
    lda #$80
    sta $2100                   ; INIDISP (display control): force blank ON (port-stable)
    rep #$30
    .a16
    .i16

    sf_load_bg_chr 0, meteor_bg_chr, meteor_bg_chr_bytes   ; tile0 blank, tile1 green
    ; BG1 palette 0 = the shared Mode 7 palette (green at index 4 etc.)
    sf_load_bg_pals 0, meteor_pal, 1

    jsr paint_bg_level          ; flat ground + two platforms

    ; --- ARM the red glow gradient NOW, while Mode 7 is INACTIVE. The
    ;     builder (sf_gradient_rgb) REFUSES once M7_PV_ACTIVE=1; once armed the
    ;     guard-free sf_gradient_update rebuilds it in place during the scene.
    ;     Armed with bottom red = 0 (invisible) until the glow ramps g_glow up. Top
    ;     black -> bottom red so the red concentrates in the LOWER band. ---
    sf_gradient_ease #0                          ; linear ramp
    sf_gradient_rgb #0, #0, #0,  #0, #0, #0      ; all black for now (no visible red)

    sep #$20
    .a8
    lda #$11                    ; TM: BG1 + OBJ only (BG2/BG3 off — uninit CHR)
    sta SHADOW_TM
    sta $212C                   ; TM (main-screen layer enable): BG1 + OBJ
    lda #$0F                    ; screen ON, full brightness
    sta $2100
    sta SHADOW_INIDISP
    lda #$81
    sta $4200                   ; NMITIMEN (interrupt enable): NMI on + auto-joypad
    rep #$30
    .a16
    .i16

    spr_clear
    sf_debug_magic

    ; --- init game state ---
    stz g_state                 ; ST_PLAY
    lda #$0000
    sta g_worldx
    stz g_camx
    stz g_timer
    stz g_frozen_camx
    stz g_cap_done
    stz g_scene_done
    lda #MET_SCALE_CROSS
    sta g_scale
    ; scene state (the swept position / scale / glow are derived from g_timer)
    stz g_glow
    stz g_cm_on
    stz g_cm_off
    stz g_restore_done
    stz g_event_done
    stz g_angle                 ; meteor starts unrotated

; =============================================================================
; MAIN LOOP — game_loop dispatches the cutscene state machine through state_jmp:
; ST_PLAY/FREEZE/CAPTURE/SCENE/RESTORE (do_play .. do_restore), then loop_tail.
; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin

    lda g_state
    asl a                       ; *2 for word jump table
    tax
    jmp (state_jmp, x)

state_jmp:
    .addr do_play
    .addr do_freeze
    .addr do_capture
    .addr do_scene
    .addr do_restore

; ------------------------------------------------------------------ ST_PLAY
do_play:
    .a16
    .i16
    jsr play_input              ; walk right (gated builds elsewhere)
    ; camera follows: keep player at fixed screen x, camera = worldx - scrn_x
    lda g_worldx
    sec
    sbc #PLAYER_SCRN_X
    bpl :+
    lda #$0000                  ; clamp camera >= 0
:
    sta g_camx
    scroll #1, g_camx, #0       ; BG1 HOFS = camera X
    jsr draw_play_sprites
    ; trigger check: world X reached the event point AND the event hasn't fired
    ; yet (after the restore releases control, walking right must NOT re-trigger).
    lda g_event_done
    bne dp_no_trigger
    lda g_worldx
    cmp #TRIGGER_X
    bcs dp_trigger              ; short branch; loop_tail may be far under -D builds
dp_no_trigger:
    jmp loop_tail
dp_trigger:
    lda #$0001
    sta g_event_done            ; one-shot: the event fires exactly once
    lda #ST_FREEZE
    sta g_state
    stz g_timer
    lda g_camx                  ; latch the camera for the capture's frozen view
    sta g_frozen_camx
    jmp loop_tail

; ------------------------------------------------------------------ ST_FREEZE
; physics + scroll halt; input is GATED (play_input is NOT called). Hold the
; frozen frame for FREEZE_HOLD frames so the freeze is observable, then capture.
do_freeze:
    .a16
    .i16
.ifdef NO_FREEZE
    ; NON-VACUITY CONTROL: input still moves the player during "freeze".
    jsr play_input
    lda g_worldx
    sec
    sbc #PLAYER_SCRN_X
    bpl :+
    lda #$0000
:
    sta g_camx
    scroll #1, g_camx, #0
.endif
    jsr draw_play_sprites       ; same sprites, same positions (frozen)
    lda g_timer
    inc a
    sta g_timer
    cmp #FREEZE_HOLD
    bcs df_advance              ; held long enough -> advance to CAPTURE
    jmp loop_tail
df_advance:
    lda #ST_CAPTURE
    sta g_state
    jmp loop_tail

; ------------------------------------------------------------------ ST_CAPTURE
; capture the visible BG platforms as OBJ, black the Mode-1 BG, hold a few
; frames so the captured-OBJ-over-black frame is observable, then swap.
do_capture:
    .a16
    .i16
    jsr capture_and_black       ; idempotent (guarded)
    jsr draw_capture_sprites    ; the captured OBJ ground + player
    lda g_timer
    inc a
    sta g_timer
    cmp #(FREEZE_HOLD + 30)
    bcs dc_advance              ; capture-hold elapsed -> swap to the Mode-7 scene
    jmp loop_tail
dc_advance:
    stz g_timer                 ; reset the sub-timer AT the transition (so it is
                                ; 0 the moment g_state==ST_SCENE — no stale value
                                ; for a frame before enter_scene resets it)
    lda #ST_SCENE
    sta g_state
    jmp loop_tail

; ------------------------------------------------------------------ ST_SCENE
; The LOCKED two-phase meteor, sequenced off g_timer (frames since scene entry):
;   SPRITE PHASE (t < SPRITE_END): the Mode-7 plane is scrolled OFF-FIELD (black
;     backdrop); a meteor OBJ sprite enters off-screen upper-left and GROWS through
;     4 discrete frames as it nears the crossover point. Captured ground+player
;     stay composited (the frozen platform). No glow yet.
;   MODE-7 PHASE (t >= SPRITE_END): the sprite is hidden; the Mode-7 meteor plane
;     is revealed at the crossover scale/position and then scales UP centred on the
;     pivot (grows in place) while the scroll SLIDES it off the bottom-right and a
;     SLOW TUMBLE ramps the affine angle. The red glow rises with the descent.
;   t >= SCN_END -> ST_RESTORE.
do_scene:
    .a16
    .i16
    jsr enter_scene             ; idempotent forced-blank swap (guarded)

    ; phase split on the scene sub-timer
    lda g_timer
    cmp #SPRITE_END
    bcc ds_sprite_phase
    jmp ds_mode7_phase

; --- (A) SPRITE PHASE -------------------------------------------------------
ds_sprite_phase:
    .a16
    .i16
    ; keep the Mode-7 plane OFF-FIELD so the backdrop reads black behind the OBJ.
    lda #OFF_HOFS
    sta SHADOW_BG1HOFS
    lda #OFF_VOFS
    sta SHADOW_BG1VOFS
    ; hold the crossover scale + angle 0 (a stable plane just in case it peeks)
    lda #MET_SCALE_CROSS
    sta g_scale
    sf_boss_matrix g_scale, #0

    jsr draw_capture_sprites    ; captured frozen ground + player (slot order kept)
    jsr draw_meteor_sprite      ; the growing far-approach meteor OBJ on top
    jmp ds_advance

; --- (C) MODE-7 PHASE -------------------------------------------------------
ds_mode7_phase:
    .a16
    .i16
    jsr draw_capture_sprites    ; captured OBJ over the revealed Mode-7 meteor
                                ; (the meteor sprite is NOT drawn -> hidden at the
                                ; crossover; spr_clear left its slot off-screen)
    jsr scene_scale             ; ramp g_scale DOWN: meteor grows IN PLACE (centred)
    jsr scene_slide             ; slide the scroll: meteor exits bottom-right
    jsr scene_glow              ; red glow synced to the descent

    ; SLOW TUMBLE: ramp the affine angle a small step/frame (A16 add; sf_boss_matrix
    ; takes the low byte as the turn). The pivot is pinned at the art centre
    ; (enter_scene), so this spins the meteor about its own centre — no drift.
    ; -DNO_TUMBLE compiles the ramp out (angle stays 0): the tumble non-vacuity
    ; control — two frames at different times no longer differ by rotation.
.ifndef NO_TUMBLE
    lda g_angle
    clc
    adc #TUMBLE_STEP
    sta g_angle
.endif
    sf_boss_matrix g_scale, g_angle

ds_advance:
    .a16
    .i16
    ; advance the scene timer; at SCN_END hand off to ST_RESTORE
    lda g_timer
    inc a
    sta g_timer
    cmp #SCN_END
    bcc ds_stay
    lda #ST_RESTORE
    sta g_state
    stz g_timer                 ; reset for the restore hold
ds_stay:
    .a16
    .i16
    jmp loop_tail

; ------------------------------------------------------------------ ST_RESTORE
; swap Mode-7 -> Mode-1, rebuild the level, drop the captured OBJ ground,
; UNFREEZE and RELEASE control -> back to ST_PLAY (the D-pad walks again).
do_restore:
    .a16
    .i16
.ifdef NO_RELEASE
    ; NON-VACUITY CONTROL: never swap back and never release control — stay in
    ; ST_RESTORE forever (the Mode-7 scene + frozen input persist). The control-
    ; released test (held RIGHT advances the player after the event) MUST FAIL.
    jsr draw_capture_sprites    ; keep the captured OBJ over the Mode-7 scene
    jmp loop_tail
.else
    jsr exit_scene              ; idempotent forced-blank swap-back (guarded)
    jsr draw_play_sprites       ; just the player again (captured ground dropped)
    lda #ST_PLAY                ; control released next frame
    sta g_state
    jmp loop_tail
.endif

; ------------------------------------------------------------------ tail
loop_tail:
    .a16
    .i16
    ; debug mirrors (SEQUENCE only)
    ldx #$0000
    lda FRAME_COUNTER
    sta f:$7E0000 + DBG_HEART, x
    lda g_state
    sta f:$7E0000 + DBG_STATE, x
    lda g_worldx
    sta f:$7E0000 + DBG_WORLDX, x
    lda g_camx
    sta f:$7E0000 + DBG_CAMX, x
    lda SHADOW_BGMODE           ; live BG mode (SEQUENCE mirror: 1 or 7)
    and #$00FF
    sta f:$7E0000 + DBG_BGMODE, x
    sf_frame_end
    jmp game_loop

; =============================================================================
; ============================== SUBROUTINES ==================================
; The state handlers' helpers (input, sprite draw, the BG->OBJ capture) and the
; Mode-7 scene stages: enter_scene, the grow/fall stage, scene_glow, exit_scene.
; =============================================================================

; =============================================================================
; play_input — D-pad RIGHT advances the player world X (the walk).
; A16/I16. Clobbers A, X, Y.
; =============================================================================
.proc play_input
    .a16
    .i16
    btn #BTN_RIGHT
    beq pi_done
    lda g_worldx
    clc
    adc #WALK_SPEED
    sta g_worldx
pi_done:
    rep #$30
    .a16
    .i16
    rts
.endproc

; =============================================================================
; draw_play_sprites — the player OBJ at its fixed screen position. (The BG is
; the ground/platforms during ST_PLAY/ST_FREEZE.)
; A16/I16. Clobbers A, X, Y.
; =============================================================================
.proc draw_play_sprites
    .a16
    .i16
    spr_clear
    spr #OBJ_PLAYER, #PLAYER_SCRN_X, #PLAYER_Y, #$00, #1
    rts
.endproc

; =============================================================================
; paint_bg_level — flat ground (rows 24..27) + two raised platforms.
; A16/I16. mset clobbers A,X,Y so loop counters live in DP scratch ($54-$58).
; =============================================================================
.proc paint_bg_level
    .a16
    .i16
    pbl_row = $54
    pbl_col = $56
    ; --- flat ground rows 24..27, all 32 cols ---
    lda #GND_ROW0
    sta pbl_row
pbl_grow:
    stz pbl_col
pbl_gcol:
    mset #1, pbl_col, pbl_row, #BG_PLAT
    lda pbl_col
    inc a
    sta pbl_col
    cmp #32
    bne pbl_gcol
    lda pbl_row
    inc a
    sta pbl_row
    cmp #(GND_ROW1 + 1)
    bne pbl_grow

    ; --- platform A (row 18, cols 6..9) ---
    lda #PLAT_A_C0
    sta pbl_col
pbl_pa:
    mset #1, pbl_col, #PLAT_A_ROW, #BG_PLAT
    lda pbl_col
    inc a
    sta pbl_col
    cmp #(PLAT_A_C1 + 1)
    bne pbl_pa

    ; --- platform B (row 14, cols 20..23) ---
    lda #PLAT_B_C0
    sta pbl_col
pbl_pb:
    mset #1, pbl_col, #PLAT_B_ROW, #BG_PLAT
    lda pbl_col
    inc a
    sta pbl_col
    cmp #(PLAT_B_C1 + 1)
    bne pbl_pb
    rts
.endproc

; =============================================================================
; capture_and_black — THE CRUX. Walk the visible BG1 tilemap; for every
; on-screen PLATFORM cell emit an OBJ sprite pixel-aligned where the BG tile is
; (screen px = mx*8 - hofs, my*8 - vofs). Then drop BG from TM so only the
; captured OBJ remains — it lands on the SAME pixels the BG tiles occupied.
;
; CAPTURE-TABLE APPROACH: the level layout is known at author time, so the set
; of platform cells is a static ROM table (cell_tbl: pairs of (tile_col,
; tile_row), terminated by $FF). We capture each cell's tile as a 16x16 OBJ at
; (col*8 - camx, row*8) — vofs is 0 (BG1 doesn't scroll vertically here). 16x16
; blocks tile across each 8-px BG cell pair; the green block colour matches the
; BG green so the captured ground is visually identical, pixel-aligned to the
; sub-tile via the camera's fractional-free integer scroll.
;
; This respects the 128-OBJ budget: only platform cells are captured (flat
; ground band + two platforms = a bounded count), NOT a full 32x32 grid.
;
; Guarded by g_cap_done so the BG-black write happens once. A16/I16.
; Clobbers A, X, Y.
; =============================================================================
.proc capture_and_black
    .a16
    .i16
    lda g_cap_done
    bne cab_already
    lda #$0001
    sta g_cap_done

.ifndef NO_CAPTURE
    ; (capture itself happens each frame in draw_capture_sprites, which reads
    ;  the same cell_tbl; here we just black the BG so only OBJ remains.)
.endif

    ; BLACK the Mode-1 BG: TM = OBJ only (drop BG1). The captured OBJ ground is
    ; now the ONLY thing on screen at the platform rows.
    sep #$20
    .a8
    lda #$10                    ; TM bit4 = OBJ only
    sta SHADOW_TM
    sta $212C                   ; TM: OBJ only (BG1 dropped)
    rep #$30
    .a16
    .i16
cab_already:
    rep #$30
    .a16
    .i16
    rts
.endproc

; =============================================================================
; draw_capture_sprites — THE CRUX, the genuine dynamic BG->OBJ capture. Reads
; the ACTUAL visible BG1 shadow tilemap ($A200, 32x32 words, row-major) and for
; every PLATFORM cell on screen emits a 16x16 OBJ ground block pixel-aligned to
; where that BG tile rendered.
;
; The visible window: screen pixel x shows world pixel (g_frozen_camx + x), and
; the BG1 tilemap is 32 cols wide and WRAPS (256 px). So screen tile column `sc`
; reads tilemap column tmcol = ((frozen_camx>>3) + sc) & 31, and the block draws
; at screen x = sc*8 (exactly on the pixels the BG tile occupied — same integer
; scroll, no fraction). The capture is therefore camera-correct AND wrap-correct
; by construction: it reproduces what the PPU showed, not an author-time guess.
;
; We scan a fixed set of candidate ROWS (the only rows the level uses platforms
; on: PLAT_B_ROW=14, PLAT_A_ROW=18, and the flat-ground block rows 24 & 26) and
; step screen columns by 2 (a 16x16 block spans 2 BG cells). A cell is a platform
; iff its tilemap CHR index (low 10 bits of the word) == BG_PLAT. Bounded count
; (4 rows x 16 block-cols = 64 max + 1 player) -> within the 128-OBJ budget.
;
; NO_CAPTURE control: emits ONLY the player (no ground) -> at the swap the
; ground band is black, so the capture alignment test fails.
;
; A16/I16. Clobbers A, X, Y. Loop state in DP scratch ($54-$5E).
; =============================================================================
.proc draw_capture_sprites
    .a16
    .i16
    dcs_rowidx  = $54           ; index into cand_rows
    dcs_rowbase = $56           ; row*32 (tilemap word index of column 0 in this row)
    dcs_basecol = $58           ; leftmost on-screen tilemap column (frozen_camx>>3)
    dcs_sc      = $5A           ; current screen tile column (0,2,..,32)
    dcs_sy      = $5C           ; screen y = row*8
    dcs_sx      = $5E           ; screen x = sc*8 - subx
    dcs_subx    = $52           ; frozen_camx & 7 (sub-tile remainder). NB: kept
                                ;   BELOW $60 — the `spr` macro writes the API
                                ;   block at $60.., so capture scratch must not
                                ;   touch $60+ (it is clobbered every spr call).
    spr_clear

.ifndef NO_CAPTURE
    ; leftmost on-screen tilemap column = frozen_camx / 8 (computed once)
    lda g_frozen_camx
    lsr a
    lsr a
    lsr a
    sta dcs_basecol
    ; sub-tile scroll remainder: blocks shift left by (frozen_camx & 7) so the
    ; captured OBJ lands on the SAME pixels the BG tiles did at ANY camera X.
    lda g_frozen_camx
    and #$0007
    sta dcs_subx
    stz dcs_rowidx
dcs_rowloop:
    ldx dcs_rowidx
    lda f:cand_rows, x
    and #$00FF
    cmp #$00FF
    beq dcs_rows_done
    inx                         ; cand_rows is byte-per-entry -> advance by 1
    stx dcs_rowidx
    ; row*32 and row*8 from the row number in A
    pha                         ; save row
    asl a
    asl a
    asl a
    asl a
    asl a                       ; row*32
    sta dcs_rowbase
    pla                         ; row
    asl a
    asl a
    asl a                       ; row*8 = screen y
    sta dcs_sy
    ; scan screen columns 0,2,..,30
    stz dcs_sc
dcs_colloop:
    ; wrapped tilemap word index = rowbase + ((basecol + sc) & 31)
    lda dcs_basecol
    clc
    adc dcs_sc
    and #$001F                  ; wrap to the 32-col row
    clc
    adc dcs_rowbase             ; + row*32 = tilemap word index
    asl a                       ; *2 (word table)
    tax
    lda f:$7E0000 + SHADOW_BG1_TILEMAP, x   ; the ACTUAL visible tilemap word
    and #$03FF                  ; CHR index (low 10 bits)
    cmp #BG_PLAT
    bne dcs_nextcol             ; not a platform cell -> capture nothing here
    ; screen x = sc*8 - subx, emit the 16x16 OBJ ground block at (sx, sy)
    lda dcs_sc
    asl a
    asl a
    asl a                       ; sc*8
    sec
    sbc dcs_subx                ; - sub-tile remainder
    sta dcs_sx
    spr #OBJ_GROUND, dcs_sx, dcs_sy, #$00, #2
dcs_nextcol:
    lda dcs_sc
    clc
    adc #2
    sta dcs_sc
    cmp #34                     ; scan one extra block-col so the right edge is
    bcc dcs_colloop             ;   covered after the sub-tile left shift
    jmp dcs_rowloop
dcs_rows_done:
.endif

    ; player on top (its screen X is fixed; at freeze it sits where it stood)
    spr #OBJ_PLAYER, #PLAYER_SCRN_X, #PLAYER_Y, #$00, #1
    rts
.endproc

; =============================================================================
; enter_scene — forced-blank SWAP to the Mode-7 meteor scene (guarded, once).
; Uses the sf_swap_to_mode7 primitive (handles blank/map/palette/mode).
; Pins the affine pivot at the meteor art centre (so the Mode-7 zoom/tumble are
; centred) and parks the plane OFF-FIELD for the opening SPRITE phase (black
; backdrop). A16/I16. Clobbers A,X,Y.
; =============================================================================
.proc enter_scene
    .a16
    .i16
    lda g_scene_done
    beq es_dowork               ; short branch; the swap body is too far for bne
    jmp es_already
es_dowork:
    lda #$0001
    sta g_scene_done

    ; THE SWAP: blank -> re-upload meteor map -> re-stage meteor palette ->
    ; whole-plane affine Mode 7 -> unblank. (gotchas 1/2/3 handled inside.)
    sf_swap_to_mode7 met_map, #$8000, meteor_pal, 16

    ; M7SEL bit7 = 1: "outside the 1024x1024 field = transparent (backdrop)".
    ; So when the SPRITE phase parks the plane off-field AND when the slide
    ; carries the pivot out of the field, the off-field region shows the (black)
    ; backdrop instead of WRAPPING the meteor back into view. sf_boss_mode7_on
    ; left M7_PV_M7SEL = 0 (wrap); override it here. The stock NMI commits
    ; M7_PV_M7SEL to $211A every VBlank while M7_PV_ACTIVE = 1.
    sep #$20
    .a8
    lda #$80
    sta M7_PV_M7SEL
    rep #$30
    .a16
    .i16

    ; PIN the affine pivot at the meteor art centre (CONSTANT all scene) so the
    ; scale grows the meteor IN PLACE and the tumble spins about its own centre.
    ; sf_boss_center also seeds HOFS/VOFS; do_scene's SPRITE phase immediately
    ; overrides them to OFF-FIELD so the plane is black behind the opening sprite.
    sf_boss_center #MET_CX, #MET_CY
    lda #OFF_HOFS
    sta SHADOW_BG1HOFS
    lda #OFF_VOFS
    sta SHADOW_BG1VOFS
    lda #MET_SCALE_CROSS
    sta g_scale
    sf_boss_matrix g_scale, #0
    stz g_angle                 ; tumble starts at 0
    stz g_timer                 ; the scene sub-timeline counts from 0 here
es_already:
    rep #$30
    .a16
    .i16
    rts
.endproc

; =============================================================================
; draw_meteor_sprite (SPRITE PHASE) — draw the growing far-approach meteor as a
; SINGLE OBJ sprite at the swept screen centre (X0+2t, Y0+2t), picking one of SIX
; pre-drawn frames by g_timer (FIERY r3/r5/r7 16x16 -> ROCKY r10/r13/r15.5 32x32).
; OBJ can't hardware-scale, so growth is purely the discrete frames; the last
; (R2, ~32px) is the crossover frame. A FLIP-CYCLE reorients the sprite every
; SPR_FLIP_PERIOD frames ({normal,H,V,H+V}) for an illusion of spin. Drawn AFTER
; draw_capture_sprites so it composites on TOP of the frozen ground/player.
; A16/I16. Clobbers A,X,Y; uses g_scr + $50-$58 draw-scratch (the glow is OFF in
; the SPRITE phase, so the gradient's $50/$52 shadows are free here).
; =============================================================================
.proc draw_meteor_sprite
    .a16
    .i16
    dms_x     = $50             ; sprite top-left X operand
    dms_y     = $52             ; sprite top-left Y operand
    dms_cx    = $54             ; sprite centre X
    dms_cy    = $56             ; sprite centre Y
    dms_o     = $58             ; flip orientation 0..3 (bit0=H, bit1=V)
    dms_tile  = $5A             ; chosen frame tile
    dms_flags = $5C             ; computed spr `flags` operand (size + H-flip)
    ; centre = (X0 + t, Y0 + t)   (SPR_STEP == 1)
    lda g_timer
    clc
    adc #(SPR_X0 & $FFFF)
    sta dms_cx
    lda g_timer
    clc
    adc #(SPR_Y0 & $FFFF)
    sta dms_cy

    ; --- FLIP-CYCLE orientation: o = (g_timer / SPR_FLIP_PERIOD) & 3 (no divide:
    ;     repeated subtraction tracking the quotient, then mask the low 2 bits).
    ;     -DNO_TUMBLE holds o = 0 (no flip-cycle) — the same control that compiles
    ;     out the Mode-7 affine tumble, so it is "no tumble at all" (non-vacuous for
    ;     both the sprite flip-cycle and the affine spin). ---
    stz dms_o                   ; quotient accumulator (low 2 bits = o)
.ifndef NO_TUMBLE
    lda g_timer
    and #$00FF
dms_div:
    cmp #SPR_FLIP_PERIOD
    bcc dms_div_done
    sec
    sbc #SPR_FLIP_PERIOD
    inc dms_o
    bra dms_div
dms_div_done:
    .a16
    .i16
    lda dms_o
    and #$0003
    sta dms_o                   ; o (0..3)
.endif

    ; pick the frame by size bucket
    lda g_timer
    cmp #SPR_FR_R2
    bcs dms_r2
    cmp #SPR_FR_R1
    bcs dms_r1
    cmp #SPR_FR_R0
    bcs dms_r0
    cmp #SPR_FR_F2
    bcs dms_f2
    cmp #SPR_FR_F1
    bcs dms_f1
    lda #OBJ_MET_F0
    jmp dms_set16
dms_f1:
    .a16
    .i16
    lda #OBJ_MET_F1
    jmp dms_set16
dms_f2:
    .a16
    .i16
    lda #OBJ_MET_F2
    jmp dms_set16
dms_r0:
    .a16
    .i16
    lda #OBJ_MET_R0
    jmp dms_set32
dms_r1:
    .a16
    .i16
    lda #OBJ_MET_R1
    jmp dms_set32
dms_r2:
    .a16
    .i16
    lda #OBJ_MET_R2
    ; fall through to dms_set32
dms_set32:
    .a16
    .i16
    sta dms_tile
    lda dms_cx
    sec
    sbc #16                     ; 32x32 top-left = centre - 16
    sta dms_x
    lda dms_cy
    sec
    sbc #16
    sta dms_y
    lda #SPR_FLAG_LARGE         ; large size (bit7)
    bra dms_addhf
dms_set16:
    .a16
    .i16
    sta dms_tile
    lda dms_cx
    sec
    sbc #8                      ; 16x16 top-left = centre - 8
    sta dms_x
    lda dms_cy
    sec
    sbc #8
    sta dms_y
    lda #SPR_FLAG_SMALL         ; small size
dms_addhf:
    .a16
    .i16
    ; OR in H-flip (spr flags bit6) when o&1
    pha
    lda dms_o
    and #$0001
    beq :+
    pla
    ora #SPR_FLAG_HFLIP
    bra :++
:
    pla
:
    sta dms_flags
    ; emit; the spr macro returns the slot in A
    spr dms_tile, dms_x, dms_y, dms_flags, #0
    ; --- V-flip poke: if o&2, set OAM attr bit7 of the returned slot. The spr
    ;     macro can't reach V-flip (engine_spr masks attr with and #$4F), so poke
    ;     SHADOW_OAM_BASE + slot*4 + 3 directly (bank-0 WRAM mirror; DB=0). ---
    pha                         ; save slot (A16)
    lda dms_o
    and #$0002
    beq dms_no_vflip
    pla                         ; slot
    asl a
    asl a                       ; slot*4
    clc
    adc #(SHADOW_OAM_BASE + 3)   ; attr byte offset within bank-0 WRAM mirror
    tax                         ; X = byte offset (I16)
    sep #$20
    .a8
    lda $0000,x                 ; current attr byte
    ora #OAM_ATTR_VFLIP
    sta $0000,x
    rep #$30
    .a16
    .i16
    rts
dms_no_vflip:
    .a16
    .i16
    pla                         ; discard slot
    rts
.endproc

; =============================================================================
; scene_scale (MODE-7 PHASE) — ramp the affine scale DOWN from MET_SCALE_CROSS to
; MET_SCALE_FULL so the meteor GROWS centred on the pivot (grows in place).
; A16/I16. Clobbers A.
; =============================================================================
.proc scene_scale
    .a16
    .i16
.ifdef NO_SCALE
    ; NON-VACUITY CONTROL: the scale ramp is compiled out — the meteor holds the
    ; crossover scale and never gets bigger. The grow test (real vs NO_SCALE at the
    ; same scene timer) MUST FAIL on this build.
    rts
.endif
    lda g_scale
    sec
    sbc #MET_SCALE_STEP
    cmp #MET_SCALE_FULL
    bcs :+                      ; still > FULL -> keep shrinking the scale
    lda #MET_SCALE_FULL         ; clamp at full size
:
    sta g_scale
    rts
.endproc

; =============================================================================
; scene_slide (MODE-7 PHASE) — slide the meteor off the BOTTOM-RIGHT by setting
; only the BG scroll (pivot stays pinned -> centred scale). m = g_timer-SPRITE_END.
; centre = (CROSS_X + SLIDE_SX*m, CROSS_Y + SLIDE_SY*m); render the pinned pivot
; there via HOFS = MET_CX - centreX, VOFS = MET_CY - centreY. SLIDE_SX=2 (m<<1),
; SLIDE_SY=3 (m<<1 + m), multiply-free. A16/I16. Clobbers A; uses g_scr.
; =============================================================================
.proc scene_slide
    .a16
    .i16
    lda g_timer
    sec
    sbc #SPRITE_END             ; m (>= 0 in this phase)
    sta g_scr                   ; keep m
    ; HOFS = MET_CX - (CROSS_X + 3m) = (MET_CX - CROSS_X) - 3m
    ; 3m right == 3m down -> a 45-degree slide, CONTINUOUS with the 45-degree
    ; sprite-phase path, so the meteor exits the bottom-RIGHT corner (not just
    ; the bottom-centre as a 2:3 slide did).
    asl a                       ; 2m
    clc
    adc g_scr                   ; 3m
    eor #$FFFF
    sec
    adc #(MET_CX - CROSS_X)
    sta SHADOW_BG1HOFS
    ; VOFS = MET_CY - (CROSS_Y + 3m) = (MET_CY - CROSS_Y) - 3m
    lda g_scr                   ; m
    asl a                       ; 2m
    clc
    adc g_scr                   ; 3m
    eor #$FFFF
    sec
    adc #(MET_CY - CROSS_Y)
    sta SHADOW_BG1VOFS
    rts
.endproc

; =============================================================================
; scene_glow — the red impact glow, SYNCHRONISED to the meteor's descent.
; A top-black -> bottom-red ADD gradient (armed at boot, OBJ excluded from color
; math) whose bottom-red intensity TRACKS the meteor's on-screen Y as it falls
; (deeper = redder), then RECEDES after the flight ends.
;
; PERFORMANCE: rebuilding the per-scanline COLDATA tables (sf_gradient_update ->
; 3 divides + a 675-entry fill) is EXPENSIVE — doing it every frame overran the
; frame budget and ran the whole scene at ~1/3 speed (slow motion). The proven
; rails rebuild only when the tint CHANGES, not per frame. So here the target
; intensity is QUANTISED (steps of 8) and the rebuild is GATED on a change: the
; long approach (glow steady at 0) and any hold cost nothing; only the ~handful
; of intensity steps on the rise/recede pay for a rebuild. Color math turns ON
; once the glow first rises and OFF once it has fully receded. A16/I16.
; Clobbers A, X, Y; uses g_scr.
; =============================================================================
.proc scene_glow
    .a16
    .i16
.ifdef NO_GRADIENT
    ; NON-VACUITY CONTROL: the red glow is compiled out — color math is never
    ; turned on and BOT_R stays 0, so NO red appears. The glow test (lower-band
    ; red rises then recedes) MUST FAIL on this build.
    rts
.endif
    ; --- compute this frame's QUANTISED target intensity into A, tracking the
    ;     Mode-7 elapsed m = g_timer - SPRITE_END (scene_glow runs only in the
    ;     Mode-7 phase, so m >= 0). The glow is SYNCED to the descent:
    ;       m <  GLOW_START      : 0           (meteor still high)
    ;       GLOW_START..GLOW_PEAK: rises 0->~31 (raw = (m-GLOW_START), <<-scaled)
    ;       GLOW_PEAK..HOLD_END  : HOLD at 31
    ;       HOLD_END..RECEDE_END : recede ->0
    ;       >= RECEDE_END        : 0           (math OFF) ---
    lda g_timer
    sec
    sbc #SPRITE_END             ; m
    sta g_scr                   ; keep m
    cmp #GLOW_START
    bcc sgl_zero                ; m < GLOW_START -> no glow
    cmp #GLOW_PEAK
    bcc sgl_rise
    cmp #GLOW_HOLD_END
    bcc sgl_peak
    cmp #GLOW_RECEDE_END
    bcc sgl_recede
    bra sgl_zero                ; receded fully
sgl_rise:
    ; raw = (m - GLOW_START), clamped 31 -> reaches peak red ~m51, ~1 unit/frame.
    lda g_scr
    sec
    sbc #GLOW_START
    cmp #32
    bcc sgl_quant
    lda #31
    bra sgl_quant
sgl_peak:
    lda #31
    bra sgl_quant
sgl_recede:
    ; raw = 31 - (m - GLOW_HOLD_END) * 31 / (RECEDE_END-HOLD_END). Window=20f,
    ; ~ raw = 31 - ((m-GLOW_HOLD_END) + (m-GLOW_HOLD_END)<<... ) -> step ~1.5/f.
    lda g_scr
    sec
    sbc #GLOW_HOLD_END          ; 0..20
    sta g_scr
    asl a                       ; 2x
    clc
    adc g_scr                   ; 3x  (3*(m-HOLD_END))
    lsr a                       ; /2 -> ~1.5*(m-HOLD_END) over 20f -> ~30
    eor #$FFFF
    sec
    adc #31                     ; 31 - that
    bpl sgl_quant
sgl_zero:
    lda #$0000
    bra sgl_gate
sgl_quant:
    and #$FFF8                  ; quantise to steps of 8 (few distinct levels)
sgl_gate:
    ; GATE: only pay for a rebuild when the quantised target actually changed.
    cmp g_glow
    bne sgl_changed
    rts                         ; unchanged -> skip the expensive rebuild (THE FIX)
sgl_changed:
    sta g_glow
    bne sgl_ensure_on
    ; target == 0: turn color math OFF once (only if it was on)
    lda g_cm_off
    bne sgl_write
    lda g_cm_on
    beq sgl_write
    lda #$0001
    sta g_cm_off
    sf_colormath_off
    bra sgl_write
sgl_ensure_on:
    ; target > 0: turn color math ON once (ADD; layers backdrop+BG1 = $21; OBJ
    ; bit4 EXCLUDED so the sprites are NOT tinted red)
    lda g_cm_on
    bne sgl_write
    lda #$0001
    sta g_cm_on
    sf_colormath_on #1, #$21
sgl_write:
    lda g_glow
    sta HDMA_GRAD_RGB_BOT_R
    stz HDMA_GRAD_RGB_BOT_G
    stz HDMA_GRAD_RGB_BOT_B
    sf_gradient_update          ; the gated rebuild — now only on intensity steps
    rts
.endproc

; =============================================================================
; exit_scene — forced-blank SWAP BACK Mode-7 -> Mode-1 (guarded, once).
; Uses sf_swap_to_mode1_begin/end: leave Mode 7, gfxmode #1, re-raise blank,
; then re-build the Mode-1 level under the blank (re-upload BG CHR — it lived in
; the $0000-$3FFF Mode-7 region and was clobbered — re-stage the shared BG
; palette CGRAM 0-15, and repaint the tilemap), then TM = BG1+OBJ + unblank.
; Also ensures the glow color math is OFF and the captured-OBJ guard is reset so
; the player walks on a clean Mode-1 level. A16/I16. Clobbers A, X, Y.
; =============================================================================
.proc exit_scene
    .a16
    .i16
    lda g_restore_done
    beq xs_dowork
    jmp xs_already
xs_dowork:
    lda #$0001
    sta g_restore_done

    ; make sure the red glow is gone (defensive — scene_glow normally did this)
    lda g_cm_off
    bne :+
    lda #$0001
    sta g_cm_off
    sf_colormath_off
:
    ; THE SWAP-BACK framing: blank -> sf_mode7_off -> gfxmode #1 -> re-blank
    sf_swap_to_mode1_begin #1

    ; --- rebuild the Mode-1 level under the still-raised blank ---
    ; (1) BG1 CHR (word $2000, inside the clobbered Mode-7 region): re-upload.
    sf_load_bg_chr 0, meteor_bg_chr, meteor_bg_chr_bytes
    ; (2) shared BG palette CGRAM 0-15 (the Mode-7 restage overwrote the green).
    sf_load_bg_pals 0, meteor_pal, 1
    ; (3) repaint the flat ground + two platforms into the BG1 tilemap.
    jsr paint_bg_level

    ; TM = BG1 + OBJ, drop the blank, re-enable NMI.
    sf_swap_to_mode1_end #$11

    ; reset the per-frame draw path back to the Mode-1 player + drop the
    ; captured ground (draw_play_sprites runs in ST_PLAY now). Re-zero the
    ; capture guard so a future event could re-capture (defensive; the event is
    ; one-shot via g_event_done, but keep the guards coherent).
    stz g_cap_done
    ; The camera resumes automatically: ST_PLAY recomputes g_camx from g_worldx
    ; (preserved through the freeze) and re-commits BG1 HOFS via `scroll` every
    ; frame, so the player picks up exactly where it froze.
xs_already:
    rep #$30
    .a16
    .i16
    rts
.endproc

; =============================================================================
; Engine link partners (sf_mode7_affine.inc + sprite/dma engine order).
; =============================================================================
.include "sprite_engine.asm"
.include "input_handler.asm"        ; engine_btn / engine_btnp
.include "dma_scheduler.asm"
.include "bg_engine.asm"            ; engine_gfxmode / engine_mset / engine_scroll
.include "bright_fade_engine.asm"   ; bright-fade partner (hdma/colormath order)

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"          ; HDMA channel wrappers (gradient_rgb partner)
.include "hdma_color_engine.asm"    ; red-glow gradient COLDATA builder/rebuild
.include "colormath_engine.asm"     ; engine_color_math_on/off (OBJ-excluded ADD)
.include "palette_engine.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

; --- candidate ROWS the capture scans (the only tilemap rows the level paints
;     platform tiles on). For each, draw_capture_sprites walks screen columns
;     0,2,..,30, reads the ACTUAL BG1 shadow tilemap, and captures a 16x16 OBJ
;     block at any PLATFORM cell. $FF-terminated. A 16x16 block spans 2 BG cells
;     vertically too, so the flat ground (rows 24..27) is covered by block rows
;     24 and 26; the raised platforms occupy a single 8px-tall BG row each (14,
;     18) and capture as a 16x16 block whose top half is the platform. ---
cand_rows:
    .byte 14                    ; platform B row
    .byte 18                    ; platform A row
    .byte 24                    ; flat-ground block row 0 (covers BG rows 24,25)
    .byte 26                    ; flat-ground block row 1 (covers BG rows 26,27)
    .byte $FF                   ; terminator

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- generated assets (this template's own; no parent reach-back) ---
.include "assets/meteor_pal.inc"    ; meteor_pal, METEOR_PAL_COUNT
.include "assets/obj_assets.inc"    ; meteor_obj_chr/_bytes, meteor_obj_pal
.include "assets/bg_assets.inc"     ; meteor_bg_chr/_bytes

.segment "BANK1"
met_map:
    .incbin "assets/meteor_map.bin"
