; =============================================================================
; racer — Mode 7 kart-style racing rail (perspective floor + steerable vehicle)
; =============================================================================
; The genre rail for racing games on the Mode 7 perspective floor. Forks the
; proven mode7_test spine (standard kit boot + the sf_mode7 macro group + the
; stock engine NMI — NO custom VBlank code; the engine NMI commits M7SEL/M7X/
; M7Y, the BG1 scroll shadows, the HDMA channel configs, and the OAM DMA) and
; adds the racing layer:
;   - a first-party closed-circuit track (assets/make_track.py -> the kit's
;     Mode 7 converter -> committed track_map.bin + track_palette.inc)
;   - kart physics: B accelerates, releasing coasts (8.8 speed, capped),
;     d-pad LEFT/RIGHT steers (angle +/-1 per frame, 0..255 = one turn)
;   - per-frame position integration, the proven racing-camera pattern:
;     sincos(angle), then pos -= (sina, cosa) x speed via smul16, wrapping
;     to the 1024px map with `and #$03FF` on the integer word
;   - a fixed-screen kart sprite (OBJ over the floor) with a lean frame on
;     steer, and a sprite-based speed bar
;
; WHY THE HUD IS SPRITES: BG3 does not exist in Mode 7 — the mode has exactly
; one BG layer (the perspective floor) plus OBJ, so sf_text/print (BG3
; renderers) have nothing to draw on. Sprite HUDs are the rail's path; the
; engine's per-scanline mode-split (Mode 7 floor below a Mode 1 band) is the
; text-HUD path, out of rail scope.
;
; THE SKY: Mode 7 has no second BG layer, so the band ABOVE the horizon would
; otherwise show the ground tilemap smeared upward. arm_sky_split (below) runs
; a 2-band TM HDMA on CH2 that turns BG1 off above the horizon, revealing the
; CGRAM[0] backdrop — which make_track.py reserves as a sky blue. Combined with
; the arcade-racer perspective (high horizon at PV_L0_RACING, strong far-scale
; PV_S0_RACING for a long forward view), the rail reads like a real racer.
;
; OBJ-OVER-MODE-7 GOTCHA (baked in below): the Mode 7 map fills VRAM words
; $0000-$3FFF wholesale, so the OBJ name base MUST move out of it — OBSEL is
; set to $62 (name base word $4000, 16x16/32x32 size pair) and the CHR
; uploads at word $4000. OBJ rendering itself is mode-independent.
;
; Controls: B = accelerate, LEFT/RIGHT = steer, START = pause/unpause.
; No button = coast to a stop.
;
; File layout (the section banners below, in order):
;   INIT             — NMI vector, cold boot, uploads, effect arm, screen-on
;   MAIN LOOP        — the once-per-frame heartbeat; START READING AT game_loop
;   SUBROUTINES      — game helpers (day-night machine, sky split), then the
;                      engine modules the macros JSR into
;   DATA             — perspective LUT, first-party assets, the track blob
;
; game_loop is the once-per-frame heartbeat: input -> physics -> camera ->
; draw -> effects, bracketed by sf_frame_begin/sf_frame_end.
;
; Tuning (override by defining before .include, or just edit):
;   ACCEL      speed gained per frame holding B   (8.8; default $0010)
;   DECEL      speed lost per frame coasting      (8.8; default $0008)
;   SPEED_CAP  top speed                          (8.8; default $0300 = 3 px/f)
;   PV_*       the perspective trapezoid — the proven racing set below; the
;              flight set (45, 224, 436, 77, 0, 2, 1 + focus 168) is the
;              other worked example (see docs/guides/mode7_racer.md)
;
; Done-condition (emulator-verifiable, tests/test_racer.py):
;   - boots ($7E:E000 == "SFDB"); heartbeat at $7E:E010 advances
;   - the perspective floor renders (distinct colors below the horizon)
;   - the kart sprite is visible (OAM slot 0 + screenshot pixels at 120,176)
;   - holding B builds speed and moves the camera (M7_PV_POSX/POSY change)
;   - steering LEFT and RIGHT changes the angle byte and the rendered view
;
; Build:  make racer   (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad_m7.cfg
;   ^ Linker-config sentinel: this ROM needs BOTH a dedicated 32KB bank for
;     the Mode 7 track-map blob (BANK1) and the TAD audio banks (driver +
;     compiled song set). The generic build/%.sfc rule reads this line and
;     links lorom_tad_m7.cfg instead of the default lorom.cfg — a *_tad*.cfg
;     name also links the TAD audio objects and adds the audio include path.
;     Copy-to-adapt keeps the line; no Makefile edit needed. (See
;     docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "NITRO RACER"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; the Mode 7 macro group
.include "sf_fx.inc"            ; gradient + color math + palette cycle
.include "tad-audio.inc"        ; TAD driver ca65 API (the vendored audio driver)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids for the shipped song set
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music
.include "engine_state.inc"

; --- tuning (assemble-time) ---
.ifndef ACCEL
ACCEL = $0010                   ; 8.8: +0.0625 px/f per frame of B
.endif
.ifndef DECEL
DECEL = $0008                   ; 8.8: -0.03 px/f per frame coasting
.endif
.ifndef SPEED_CAP
SPEED_CAP = $0300               ; 8.8: 3 px/frame top speed
.endif
.ifndef GRASS_CAP
GRASS_CAP = $00C0               ; 8.8: off-road crawl speed (0.75 px/frame)
.endif
.ifndef OFFROAD_DRAG
OFFROAD_DRAG = $0038            ; 8.8: speed bled per frame while on grass
.endif

; --- the racing-camera parameter set (arcade kart-racer forward view) ---
; Horizon high on the screen (~25% down) with strong far-compression so the
; track recedes to a distant vanishing point — you can read the upcoming curve,
; not just the few metres ahead the old low-horizon/low-far-scale set (96/192)
; showed. PV_L0_RACING == the sky/floor split scanline (arm_sky_split + the
; mode7_scene_contract horizon both key off it).
PV_L0_RACING     = 56           ; horizon scanline (~25% down; sky is a thin band)
PV_L1_RACING     = 224          ; bottom scanline
PV_S0_RACING     = 576          ; far-scale (long forward view; bigger = see further)
PV_S1_RACING     = 28           ; near-scale (texel step at the bottom)
PV_SH_RACING     = 16           ; vertical squash (road aspect)
PV_INTERP_RACING = 4            ; compute every 4th scanline, lerp between.
                                ;   The budget knob that keeps steering at 60fps:
                                ;   a rebuild at this trapezoid measures 245,779
                                ;   master clocks (interp 4) vs 293,612 (interp 2)
                                ;   on the emulator, and the rendered frames are
                                ;   indistinguishable here (3% of pixels differ,
                                ;   all sub-texel edge jitter) — this ramp is too
                                ;   gentle for the lerp to show.
PV_WRAP_RACING   = 1
FOCUS_Y_RACING   = 200          ; car planted low under the higher horizon

; --- spawn: on the start/finish line, facing along the track ---
START_X = 872                   ; east side of the ring (center 512 + r 360)
START_Y = 512
VEHICLE_X = 128 - 16            ; fixed-screen 32x32 kart: centered, ...
VEHICLE_Y = 168                 ; ...planted around the focus scanline

; --- OBJ tiles (OAM numbers, relative to the OBSEL name base) ---
VEHICLE_BASE = 0

; --- joypad masks (JOY1_CURRENT bit layout) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_START = $1000
JOY_B     = $8000

; --- sky TM-split (see arm_sky_split) ---
; A 5-byte $212C HDMA table in free low WRAM ($7E:2010): BG1 off above the
; horizon (so the CGRAM[0] sky backdrop shows), BG1+OBJ on below it.
SKY_SPLIT_TABLE = $7E0000 + $2010
SKY_HORIZON     = PV_L0_RACING          ; scanline where the floor begins (56)

; =============================================================================
; Day-night cycle — the signature look on the Mode 7 rail.
; =============================================================================
; Two effects compose it:
;
; 1. GRADIENT HORIZON TINT — sf_gradient_rgb drives COLDATA per scanline on
;    3 HDMA channels; color math SUBTRACTS the fixed color on BG1 (the floor;
;    OBJ — kart + HUD — stays un-mathed). The ramp is strongest at the top of
;    the frame and ~zero at the bottom: a depth-graded haze toward the
;    horizon. DAY subtracts blue/green near the horizon (warm glow); NIGHT
;    subtracts heavy red/green over the whole floor (dark, blue-dominant).
;
;    ARM ORDER (the engine constraint this template proves out): the
;    gradient BUILDERS (hdma_build_gradient_rgb/_stops) refuse to arm while
;    M7_PV_ACTIVE = 1 — a legacy-engine guard (legacy Mode 7 tables lived in
;    the gradient's $C000+ region). The kit's PV Mode 7 builds its tables at
;    $7E:A000-$B200 and pins only CH5+CH6, so the resources are disjoint;
;    the rail pre-pins Mode 7's CH5+CH6, arms the gradient BEFORE
;    sf_mode7_on (first-fit then hands it CH3/CH4/CH7), and runs every
;    day-night retune through the engine's IN-PLACE rebuild
;    (sf_gradient_update — no realloc, no M7 guard), never re-arming.
;    Verified at runtime: $7E:E012 holds the first gradient channel
;    (expect 3).
;
; 2. PALETTE-CYCLE ACCENT — CGRAM entries 2 (kerb white) and 3 (kerb red)
;    swap every PALCYC_SPEED frames: the rumble stripes at the road edges
;    flash red/white like trackside lights. ONLY the kerb pair cycles — the
;    road checker and the start line own dedicated CGRAM indices that never
;    rotate (make_track.py authors the start-line white one RGB step off the
;    kerb white precisely so the converter gives it its own index). Per the
;    sf_fx.inc contract the two entries are fed through sf_pal (shadow +
;    dirty); sf_pal_cycle_tick commits the dirty range only, so the rest of
;    the direct-uploaded track palette is untouched.
;
; Phase machine (R_TODPH): DAY(0) -> TO_NIGHT(1) -> NIGHT(2) -> TO_DAY(3).
; Holds last TOD_HOLD frames; blends last TOD_BLEND frames, stepping six
; 8.8 color accumulators toward the other keyframe every TOD_STEP_FRAMES
; frames (32 steps; hold entry snaps to the exact keyframe — no drift).
; Debug mirror for test orchestration: $7E:E014 = phase (visual assertions
; stay on rendered pixels; the mirror only sequences the screenshots).
; TOD_HOLD is deliberately long (15 s) so the base test_racer.py visual
; assertions all land inside the first DAY hold.

; COLDATA subtract keyframes (5-bit 0-31 per channel; top = scanline 0)
DAY_TR   = 0
DAY_TG   = 6
DAY_TB   = 14                   ; day: pull blue/green near the horizon -> warm
DAY_BR   = 0
DAY_BG   = 0
DAY_BB   = 0                    ; day: near field untinted
NIGHT_TR = 16
NIGHT_TG = 13
NIGHT_TB = 4                    ; night: pull red/green hard -> dark blue
NIGHT_BR = 10
NIGHT_BG = 8
NIGHT_BB = 2

TOD_HOLD        = 900           ; frames per DAY / NIGHT hold (15 s)
TOD_STEP_FRAMES = 8             ; frames per blend step (power of 2)
TOD_BLEND_STEPS = 32            ; steps per blend
TOD_BLEND       = TOD_STEP_FRAMES * TOD_BLEND_STEPS    ; 256 frames

; per-step 8.8 increments, day -> night (exact: deltas * 8 are integers)
GINC_TR = (((NIGHT_TR - DAY_TR) * 256) / TOD_BLEND_STEPS) & $FFFF
GINC_TG = (((NIGHT_TG - DAY_TG) * 256) / TOD_BLEND_STEPS) & $FFFF
GINC_TB = (((NIGHT_TB - DAY_TB) * 256) / TOD_BLEND_STEPS) & $FFFF
GINC_BR = (((NIGHT_BR - DAY_BR) * 256) / TOD_BLEND_STEPS) & $FFFF
GINC_BG = (((NIGHT_BG - DAY_BG) * 256) / TOD_BLEND_STEPS) & $FFFF
GINC_BB = (((NIGHT_BB - DAY_BB) * 256) / TOD_BLEND_STEPS) & $FFFF

PALCYC_SPEED = 16               ; frames per palette rotation step

; --- game DP state (kit contract: $32-$5F) ---
R_POSX   = $32                  ; camera x, 16.16 (fraction word, integer word)
R_POSY   = $36                  ; camera y, 16.16
R_ANGLE  = $3A                  ; angle word (low byte = 0..255 turn)
R_SPEED  = $3C                  ; speed, 8.8
R_VTILE  = $3E                  ; this frame's kart tile (frame select)
R_VFLAGS = $40                  ; this frame's kart OAM flags (lean H-flip)
R_TICKX  = $42                  ; HUD draw scratch: tick x
R_TICKI  = $44                  ;   tick loop index
R_TICKN  = $46                  ;   lit tick count
R_TICKT  = $48                  ;   tick tile
R_TODPH  = $4A                  ; day-night phase 0-3 (see the block above)
R_TODT   = $4C                  ; frames left in the current phase
R_GTR    = $4E                  ; gradient color accumulators, 8.8:
R_GTG    = $50                  ;   top R/G/B then bottom R/G/B — stepped
R_GTB    = $52                  ;   between the DAY_*/NIGHT_* keyframes
R_GBR    = $54
R_GBG    = $56
R_GBB    = $58
R_PVPH   = $5A                  ; perspective-rebuild pacing: 0 = idle,
                                ;   1 = a rebuild's finish half runs this frame
R_SURF   = $5C                  ; off-road probe scratch: map byte offset
R_PAUSE  = $5E                  ; pause: 0 = racing, 1 = frozen (START toggles)

.segment "CODE"

; =============================================================================
; INIT — NMI vector, cold boot, uploads, effect arm, screen-on
; =============================================================================

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)
    sf_audio_init               ; boot the S-SMP + TAD driver ONCE, before NMI
                                ;   is enabled (the SPC700 must still be in
                                ;   its IPL state for the synchronous upload)

    ; --- track upload (under the coldstart forced blank) ---
    sf_mode7_load_map track_map, #$8000

    ; track palette -> CGRAM 0.. (the floor's colors)
    sep #$20
    .a8                         ; the 65816 switches the accumulator between
                                ;   8- and 16-bit; .a8/.a16 marks tell the
                                ;   assembler (and the reader) which mode the
                                ;   CPU is in — a mismatch corrupts silently
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    ldx #$0000
tpal_loop:
    .a8
    lda f:track_pal, x
    sta $2122                   ; CGDATA (low byte then high byte, auto-pair)
    inx
    cpx #(TRACK_PAL_COUNT * 2)
    bne tpal_loop
    rep #$30
    .a16
    .i16

    ; --- kart sprite: palette + CHR out of the Mode 7 map's VRAM ---
    ; The map owns VRAM words $0000-$3FFF, so the OBJ name base moves to
    ; word $4000: OBSEL = $62 (base %010 x $2000 words, size pair 3 =
    ; 16x16 small / 32x32 large). sf_load_obj_chr addresses VRAM as
    ; tile*16 words, so "tile 1024" IS word $4000 — OAM tile numbers stay
    ; 0.. relative to the OBSEL base.
    sf_load_obj_pal 0, vehicle_pal
    sf_load_obj_chr 1024, vehicle_chr, vehicle_chr_bytes
    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: name base word $4000, 16x16/32x32
    lda #$10
    sta SHADOW_TM               ; OBJ on — mode7_init preserves bit 4 and
                                ;   ORs in BG1; the NMI commits TM = $11
    rep #$30
    .a16
    .i16

    ; --- day-night gradient: arm BEFORE sf_mode7_on (see the day-night block
    ; above — the arm builders refuse under M7_PV_ACTIVE=1; runtime retunes
    ; go through the in-place rebuild).
    ;
    ; CHANNEL ORDER MATTERS: pre-pin Mode 7's CH5+CH6 FIRST. The gradient's
    ; legacy channel wrapper guarantees CH3..CH7 (CH2 is placeholder-pinned),
    ; so an unpinned first-fit would hand the gradient CH3/CH4/CH5 — and
    ; Mode 7's later bootstrap-pin ORs CH5+CH6 in WITHOUT a conflict check
    ; (silent double-claim: the NMI then commits the AB-matrix config over
    ; the gradient's CH5 every VBlank, killing the blue ramp; measured on
    ; the emulator). mode7_hdma_alloc_request is idempotent — mode7_init
    ; repeats the same pin inside sf_mode7_on. Result: gradient = CH3/CH4/
    ; CH7, Mode 7 = CH5/CH6, disjoint; $7E:E012 verifies (expect 3).
    jsr mode7_hdma_alloc_request
    sf_gradient_ease #0         ; linear ramp
    sf_gradient_rgb #DAY_TR, #DAY_TG, #DAY_TB, #DAY_BR, #DAY_BG, #DAY_BB
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; debug: first gradient channel (expect 3)
    sf_gradient_phase #0        ; no phase animation — tod_update retunes

    ; color math: SUBTRACT the fixed color on BG1 + backdrop ($21). The
    ; per-scanline COLDATA ramp becomes the depth-graded horizon tint; OBJ
    ; (kart + speed bar) is outside the mask and stays un-mathed.
    sf_colormath_on #2, #$21
    sf_colormath_tint #0, #0, #0

    ; TOD state: start of the DAY hold; accumulators = day keyframe in 8.8
    stz R_TODPH
    lda #TOD_HOLD
    sta R_TODT
    lda #(DAY_TR * 256)
    sta R_GTR
    lda #(DAY_TG * 256)
    sta R_GTG
    lda #(DAY_TB * 256)
    sta R_GTB
    lda #(DAY_BR * 256)
    sta R_GBR
    lda #(DAY_BG * 256)
    sta R_GBG
    lda #(DAY_BB * 256)
    sta R_GBB
    ldx #$0000
    lda #$0000
    sta f:$7E0000 + $E014, x    ; debug: phase mirror = DAY

    ; --- palette-cycle accent: the kerb rumble stripes ONLY ---
    ; Feed the cycled pair through the shadow path (sf_pal — values
    ; byte-identical to track_pal, so the first tick's commit is seamless),
    ; then arm the rotation: entries 2..3, one swap every PALCYC_SPEED
    ; frames. The road checker (entries 4..5) and the start line (6..7)
    ; sit OUTSIDE the cycled range and hold still — cycling them once made
    ; ~40% of the screen strobe.
    sf_pal #2, #29, #29, #29    ; entry 2 = kerb white ($77BD)
    sf_pal #3, #26, #5,  #5     ; entry 3 = kerb red ($14BA)
    sf_pal_cycle #2, #2, #PALCYC_SPEED

    ; --- Mode 7 on + the racing camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0_RACING, #PV_L1_RACING, #PV_S0_RACING, #PV_S1_RACING, #PV_SH_RACING, #PV_INTERP_RACING, #PV_WRAP_RACING
    sf_mode7_focus #FOCUS_Y_RACING

    lda #START_X
    sta R_POSX + 2              ; integer px
    stz R_POSX + 0              ; fraction = 0
    lda #START_Y
    sta R_POSY + 2
    stz R_POSY + 0
    stz R_ANGLE
    stz R_SPEED
    stz R_PVPH                  ; no rebuild in flight
    stz R_PAUSE                 ; racing (START toggles the freeze)
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE

    sf_mode7_tick               ; first table build BEFORE screen-on (one-shot:
                                ;   under forced blank the frame budget is moot)

    jsr arm_sky_split           ; CH2 TM-split: reveal the sky above the horizon

    spr_clear
    sf_debug_magic

    ; --- race music (asynchronous: the song streams to the SPC700 over the
    ; game loop's sf_audio_ticks; ~10-60 frames until it audibly starts) ---
    sf_music #Song::gimo_297

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    sta SHADOW_INIDISP          ; the NMI re-commits INIDISP from this shadow
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
; MAIN LOOP — the once-per-frame heartbeat
; =============================================================================
; (Branch targets in this loop are plain labels, not @-locals: every sf_
; macro invocation emits labels of its own, which ends a ca65 cheap-local
; scope — an @label defined before a macro call can't be referenced after
; it.)
game_loop:
    .a16
    sf_frame_begin              ; wait for the NMI; latch input
    sf_audio_tick               ; pump TAD every frame (streams the song load
                                ;   + the command queue; skip it and the
                                ;   SPC700 never hears anything)

    ; ---------------- pause: START freezes the race -------------------------
    ; Rising-edge toggle from the engine's per-frame pressed latch (stable
    ; for exactly one frame after sf_frame_begin). While paused, the frame
    ; bracket and the audio pump keep running (music plays on) but the whole
    ; per-frame body is skipped: the shadow OAM keeps last frame's sprites,
    ; the palette cycle and day-night clock stop, the camera holds — a true
    ; freeze-frame. Any in-flight perspective rebuild resumes on unpause.
    lda JOY1_PRESSED_LATCH
    bit #JOY_START
    beq pz_no_toggle
    lda R_PAUSE
    eor #$0001
    sta R_PAUSE
pz_no_toggle:
    .a16
    lda R_PAUSE
    beq pz_run
    jmp game_heartbeat          ; paused: only the heartbeat + frame end run
pz_run:
    .a16

    ; ---------------- steering: LEFT/RIGHT rotate 1/256 turn per frame ------
    ; (also selects the kart's draw frame: lean toward the turn)
    lda #(VEHICLE_BASE + vehicle_f0)
    sta R_VTILE                 ; default: straight frame
    lda #$0080                  ; large (16x16), no flip, OBJ palette 0
    sta R_VFLAGS
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq st_no_left
    lda R_ANGLE
    inc a
    and #$00FF
    sta R_ANGLE
    lda #(VEHICLE_BASE + vehicle_f1)
    sta R_VTILE                 ; lean frame (drawn as-is = lean left)
st_no_left:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq st_no_right
    lda R_ANGLE
    dec a
    and #$00FF
    sta R_ANGLE
    lda #(VEHICLE_BASE + vehicle_f1)
    sta R_VTILE
    lda #$00C0                  ; lean frame H-flipped = lean right
    sta R_VFLAGS
st_no_right:
    .a16

    ; ---------------- throttle: B accelerates, coasting decays --------------
    lda JOY1_CURRENT
    bit #JOY_B
    beq th_coast
    lda R_SPEED
    clc
    adc #ACCEL
    cmp #SPEED_CAP
    bcc th_store
    lda #SPEED_CAP              ; clamp at top speed
th_store:
    .a16
    sta R_SPEED
    bra th_done
th_coast:
    .a16
    lda R_SPEED
    sec
    sbc #DECEL
    bcs th_coast_store
    lda #$0000                  ; floor at standstill
th_coast_store:
    .a16
    sta R_SPEED
th_done:
    .a16

    ; ---------------- integrate: pos -= (sina, cosa) x speed ----------------
    ; The proven racing-camera pattern: sincos resolves the heading, smul16
    ; scales it by the 8.8 speed into a 16.16 step, and the subtraction
    ; advances "toward the horizon" (the renderer's forward convention).
    ; The integer word wraps to the 1024px map with `and #$03FF`.
    ; (math_a/math_b/math_p/sina/cosa are mode7_math.asm's DP scratch,
    ; defined below this point — the `a:` prefix makes the forward refs
    ; explicit absolute, which with DB=0 reaches the same DP bytes.)
    lda R_ANGLE
    and #$00FF
    jsr sincos                  ; sina/cosa <- signed 8.8 (engine mode7_math)

    sep #$10                    ; smul16 contract: .a16 .i8, DP=0, DB=0
    .i8
    lda a:sina
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16                  ; math_p = sina x speed (s32, 16.16)
    lda R_POSX + 0
    sec
    sbc a:math_p + 0
    sta R_POSX + 0              ; fraction word
    lda R_POSX + 2
    sbc a:math_p + 2
    and #$03FF                  ; wrap to the 1024px map
    sta R_POSX + 2              ; integer word

    lda a:cosa
    sta a:math_a
    lda R_SPEED
    sta a:math_b
    jsr smul16
    lda R_POSY + 0
    sec
    sbc a:math_p + 0
    sta R_POSY + 0
    lda R_POSY + 2
    sbc a:math_p + 2
    and #$03FF
    sta R_POSY + 2
    rep #$30
    .a16
    .i16

    ; ---------------- off-road: grass drags the kart ------------------------
    ; The track is not just paint — the Mode 7 map doubles as the collision
    ; ground truth. The camera's integer position picks the map tile under
    ; the kart: tilemap byte offset = (tile_y * 128 + tile_x) * 2, because
    ; the committed blob interleaves tilemap bytes at even offsets (that IS
    ; the Mode 7 VRAM word layout). The generated track_surface table then
    ; classifies the tile; above a crawl on grass, speed bleeds off fast —
    ; cutting the circuit costs time. (Reads the ROM copy of the map, not
    ; VRAM: VRAM is unreadable outside blanking, the ROM blob is identical.)
    lda R_POSY + 2
    and #$03F8                  ; y & ~7  =  tile row * 8
    asl
    asl
    asl
    asl
    asl                         ; * 32 -> tile row * 256 = the row's byte offset
    sta R_SURF
    lda R_POSX + 2
    and #$03F8                  ; x & ~7  =  tile col * 8
    lsr
    lsr                         ; / 4 -> tile col * 2 = byte offset in the row
    ora R_SURF                  ; row bits (>= 256) and col bits (< 256) are
                                ;   disjoint, so OR composes the full offset
    tax
    sep #$20
    .a8
    lda f:track_map, x          ; even byte = tile number under the kart
    rep #$20
    .a16
    and #$00FF
    tax
    sep #$20
    .a8
    lda f:track_surface, x      ; 1 = grass, 0 = paved
    beq or_paved
    rep #$20
    .a16
    lda R_SPEED
    cmp #GRASS_CAP
    bcc or_done                 ; already at crawl speed: no extra drag
    sbc #OFFROAD_DRAG           ; carry is set from the cmp above
    cmp #GRASS_CAP
    bcs or_store
    lda #GRASS_CAP              ; floor the bleed at the crawl speed
or_store:
    .a16
    sta R_SPEED
    bra or_done
or_paved:
    .a8
    rep #$20
    .a16
or_done:
    .a16

    ; ---------------- camera + Mode 7 service (60 fps, frame-paced) ---------
    ; A full perspective rebuild — what an angle change demands — costs 69% of
    ; a frame at this trapezoid (measured on the emulator: 245,779 master
    ; clocks at interp 4; interp 2 costs 293,612 = 82%), and this rail also
    ; spends every scanline on HDMA (matrix, gradient, sky split) plus the
    ; per-frame game work. One frame cannot hold all of it, so a naive
    ; sf_mode7_tick halves the loop to 30 fps whenever the kart steers.
    ;
    ; The fix is the classic racing-game trick: SPREAD the rebuild across two
    ; frames using the engine's split entry points (see pv_rebuild in
    ; engine/mode7_hdma.asm). Frame A runs pv_rebuild_pass1 — the per-scanline
    ; coefficient emit (measured 136,890 mc at interp 4), into the hidden half
    ; of the double buffer, so the displayed frame still shows the previous
    ; view. Frame B runs pv_rebuild_pass2 — interpolation + pointing the HDMA
    ; channels at the new half (108,351 mc). Each half fits its frame beside
    ; the HDMA + game overhead. The view turns in 2-unit steps every other
    ; frame (the same average rate as 1/frame), but position, sprites, and
    ; effects update every frame and the loop never misses a NMI. The cheap
    ; origin re-anchor (camera translation) still runs EVERY frame, so
    ; forward motion stays 60 Hz smooth even while a rebuild is in flight.
    ;
    ; This block is sf_mode7_tick's dispatch with the rebuild split in two;
    ; the Mode 7 HUD-overlay hook is omitted (this rail's HUD is sprites).
    ; A copied rail that arms the barrel effect keeps working: the hook runs
    ; after pass 2, when the new tables are complete.
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE
    ; --- yield to the day-night gradient's table rebuild. On the frames a
    ; blend steps COLDATA (every 8th blend frame, plus the hold-entry snap),
    ; tod_update below rebuilds three 225-entry HDMA tables — a whole-frame-
    ; class cost by itself. Pausing the perspective pacing for that one frame
    ; keeps the two big table builds out of the same frame, so steering
    ; through a blend degrades no further than idling through one. (The
    ; gradient-step frame itself still overruns — an engine-wide cost every
    ; gradient-blending rail pays; see tests/test_racer.py for the pinned
    ; cadence.) This predicts tod_update's own step condition one call early.
    lda R_TODPH
    and #$0001
    beq m7svc_no_pause          ; DAY/NIGHT holds: no gradient work, no pause
    lda R_TODT
    dec a
    beq m7svc_pause             ; timer expiring: hold-entry snap rebuilds
    and #$0007
    cmp #$0001
    bne m7svc_no_pause          ; not a step frame
m7svc_pause:
    .a16
    sep #$20
    .a8
    bra m7svc_origin            ; skip launch/finish; origin re-anchor still runs
m7svc_no_pause:
    .a16
    sep #$20
    .a8                         ; 8-bit accumulator for the 1-byte flags
    lda R_PVPH
    bne m7svc_finish            ; a rebuild is in flight -> finish it now
    lda M7_DIRTY_REBUILD
    beq m7svc_origin            ; angle unchanged -> cheap path only
    stz M7_DIRTY_REBUILD        ; consume the flag (this scheduler owns it)
    rep #$30
    .a16
    .i16
    jsr pv_rebuild_pass1        ; frame A: emit into the hidden buffer half
    sep #$20
    .a8
    lda #$01
    sta R_PVPH                  ; remember: finish half is due next frame
    bra m7svc_origin
m7svc_finish:
    .a8
    rep #$30
    .a16
    .i16
    jsr pv_rebuild_pass2        ; frame B: interpolate + flip the channels
    jsr mode7_barrel_apply      ; post-rebuild hook (no-op: no barrel armed)
    sep #$20
    .a8
    stz R_PVPH
m7svc_origin:
    .a8
    lda M7_DIRTY_ORIGIN
    beq m7svc_done              ; camera did not move (never true while driving)
    stz M7_DIRTY_ORIGIN
    rep #$30
    .a16
    .i16
    jsr mode7_set_origin        ; re-anchor M7X/M7Y + scroll (the ~1% path)
    sep #$20
    .a8
m7svc_done:
    .a8
    rep #$30
    .a16
    .i16

    ; ---------------- draw: stable OAM slots (0 = kart, 1-6 = speed bar) ----
    spr_clear
    spr R_VTILE, #VEHICLE_X, #VEHICLE_Y, R_VFLAGS, #2

    ; sprite speed bar: 6 ticks, lit count = speed >> 7 (0..6 at the cap)
    lda R_SPEED
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta R_TICKN
    lda #16
    sta R_TICKX
    stz R_TICKI
hud_loop:
    .a16
    lda R_TICKI
    cmp R_TICKN
    bcs hud_dim
    lda #(VEHICLE_BASE + VEHICLE_TICK_LIT)
    bra hud_put
hud_dim:
    .a16
    lda #(VEHICLE_BASE + VEHICLE_TICK_DIM)
hud_put:
    .a16
    sta R_TICKT
    spr R_TICKT, R_TICKX, #16, #$00, #2
    lda R_TICKX
    clc
    adc #8
    sta R_TICKX
    lda R_TICKI
    inc a
    sta R_TICKI
    cmp #6
    bcc hud_loop

    ; ---------------- day-night + palette-cycle service ---------------------
    jsr tod_update              ; phase machine + in-place gradient retunes
    sf_pal_cycle_tick           ; rotate + commit dirty CGRAM range (must run
                                ;   BEFORE sf_frame_end — the queue contract)

    ; ---------------- heartbeat: frame counter -> debug region --------------
game_heartbeat:
    .a16
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    lda R_TODPH
    sta f:$7E0000 + $E014, x    ; phase mirror (test orchestration only)

    sf_frame_end                ; resolve sprites; signal the OAM DMA
    jmp game_loop

; =============================================================================
; SUBROUTINES — game helpers (day-night machine, sky split)
; =============================================================================

; =============================================================================
; tod_update — the day-night phase machine (call once per frame, A16/I16).
; =============================================================================
; DAY(0)/NIGHT(2) holds: count down TOD_HOLD frames, nothing else. Blends
; (TO_NIGHT=1 / TO_DAY=3): every TOD_STEP_FRAMES frames step the six 8.8
; color accumulators toward the other keyframe (+GINC_* toward night,
; -GINC_* toward day), write the integer parts into the engine's gradient
; scratch, and run the engine's IN-PLACE rebuild (no channel realloc — the
; path that works while Mode 7 is active). Entering a hold snaps the
; accumulators to the exact keyframe (belt + braces against step drift).
; Clobbers A, X, Y.
tod_update:
    .a16
    .i16
    lda R_TODT
    dec a
    sta R_TODT
    bne @in_phase

    ; --- timer expired: advance the phase ---
    lda R_TODPH
    inc a
    and #$0003
    sta R_TODPH
    and #$0001
    bne @enter_blend
    ; entering a HOLD: load the hold timer + snap to the exact keyframe
    lda #TOD_HOLD
    sta R_TODT
    lda R_TODPH
    bne @snap_night             ; phase 2 = NIGHT hold
    lda #(DAY_TR * 256)         ; phase 0 = DAY hold
    sta R_GTR
    lda #(DAY_TG * 256)
    sta R_GTG
    lda #(DAY_TB * 256)
    sta R_GTB
    lda #(DAY_BR * 256)
    sta R_GBR
    lda #(DAY_BG * 256)
    sta R_GBG
    lda #(DAY_BB * 256)
    sta R_GBB
    jmp @apply
@snap_night:
    .a16
    lda #(NIGHT_TR * 256)
    sta R_GTR
    lda #(NIGHT_TG * 256)
    sta R_GTG
    lda #(NIGHT_TB * 256)
    sta R_GTB
    lda #(NIGHT_BR * 256)
    sta R_GBR
    lda #(NIGHT_BG * 256)
    sta R_GBG
    lda #(NIGHT_BB * 256)
    sta R_GBB
    jmp @apply
@enter_blend:
    .a16
    lda #TOD_BLEND
    sta R_TODT
    rts

@in_phase:
    .a16
    lda R_TODPH
    and #$0001
    beq @ret_hold               ; holds: nothing to retune
    ; blends: step on frames where (timer mod TOD_STEP_FRAMES) == 1 —
    ; timer runs TOD_BLEND-1 .. 1 here, so this fires exactly
    ; TOD_BLEND_STEPS times per blend (249, 241, ... 9, 1).
    lda R_TODT
    and #(TOD_STEP_FRAMES - 1)
    cmp #$0001
    beq @step_go
@ret_hold:
    .a16
    rts
@step_go:
    .a16
    lda R_TODPH
    cmp #$0003
    beq @to_day
    ; toward night: accumulators += GINC_*
    lda R_GTR
    clc
    adc #GINC_TR
    sta R_GTR
    lda R_GTG
    clc
    adc #GINC_TG
    sta R_GTG
    lda R_GTB
    clc
    adc #GINC_TB
    sta R_GTB
    lda R_GBR
    clc
    adc #GINC_BR
    sta R_GBR
    lda R_GBG
    clc
    adc #GINC_BG
    sta R_GBG
    lda R_GBB
    clc
    adc #GINC_BB
    sta R_GBB
    jmp @apply
@to_day:
    .a16
    lda R_GTR
    sec
    sbc #GINC_TR
    sta R_GTR
    lda R_GTG
    sec
    sbc #GINC_TG
    sta R_GTG
    lda R_GTB
    sec
    sbc #GINC_TB
    sta R_GTB
    lda R_GBR
    sec
    sbc #GINC_BR
    sta R_GBR
    lda R_GBG
    sec
    sbc #GINC_BG
    sta R_GBG
    lda R_GBB
    sec
    sbc #GINC_BB
    sta R_GBB
    ; fall through to @apply
@apply:
    .a16
    ; integer parts -> the engine's gradient scratch, then in-place rebuild
    lda R_GTR
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_R
    lda R_GTG
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_G
    lda R_GTB
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_TOP_B
    lda R_GBR
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_R
    lda R_GBG
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_G
    lda R_GBB
    xba
    and #$00FF
    sta HDMA_GRAD_RGB_BOT_B
    sf_gradient_update          ; in-place rebuild (Mode-7-safe; no realloc)
@done:
    .a16
    rts

; =============================================================================
; arm_sky_split — reveal the sky above the horizon (call once, A16/I16 entry).
; =============================================================================
; Mode 7 has a single BG layer (the perspective floor), so without help the
; ground tilemap smears upward past the horizon where a SKY belongs (the
; original racer defect — mode7_scene_contract.check_sky_distinct catches it).
; The fix is a per-scanline TM split: turn BG1 OFF above the horizon so the
; CGRAM[0] backdrop (make_track.py reserves index 0 for a sky blue) shows, and
; keep BG1 ON below it for the floor. OBJ stays on in both bands so the
; fixed-screen HUD (speed bar at y=16, above the horizon) still renders.
;
; Mechanism: a 2-band $212C (TM) HDMA table on CH2. CH2 is the channel the
; legacy hdma_alloc pins as an idle placeholder (so effect builders index from
; CH3) — here it earns its keep. We program CH2's DMA registers DIRECTLY and OR
; its bit into NMI_HDMA_ENABLE; the engine NMI then re-arms $420C every VBlank
; but leaves CH2's hardware config alone (it is not Mode-7-owned). This mirrors
; exactly how gradient_rgb drives its non-Mode-7 channels — the engine NMI
; only rewrites channel configs it owns (see nmi_handler.asm's HDMA
; ownership gate). Budget: CH0/1 reserved + CH3/4/7 gradient + CH5/6 matrix
; + CH2 here = all 8 channels, no spare.
;
; WIDTH-RISK: entry A16/I16. Sets A8 for the byte writes to $43xx + the
; NMI_HDMA_ENABLE RMW, restores caller width via PLP. I16 unchanged.
arm_sky_split:
    php                         ; WIDTH-LINT: ok — save/restore caller width via PLP
    sep #$20
    .a8
    rep #$10
    .i16
    ; --- build the 2-band TM table in WRAM ($7E:2010) ---
    ; [56, $10]  : lines 0..55  -> TM = OBJ only (BG1 off): the sky backdrop
    ; [ 1, $11]  : line 56      -> TM = BG1 + OBJ: the Mode 7 floor
    ; [ 0]       : terminator   -> TM holds $11 for the rest of the frame
    ldx #$0000
    lda #(SKY_HORIZON)          ; 56 lines, non-repeat (bit7=0)
    sta f:SKY_SPLIT_TABLE + 0, x
    lda #$10                    ; BG1 off, OBJ on
    sta f:SKY_SPLIT_TABLE + 1, x
    lda #$01                    ; 1 line, non-repeat
    sta f:SKY_SPLIT_TABLE + 2, x
    lda #$11                    ; BG1 + OBJ
    sta f:SKY_SPLIT_TABLE + 3, x
    lda #$00                    ; terminator (stz has no abs-long mode)
    sta f:SKY_SPLIT_TABLE + 4, x
    ; --- configure CH2 DMA registers directly (non-Mode-7-owned) ---
    lda #$00
    sta $4320                   ; DMAP2: A->B, absolute table, 1 byte -> 1 reg
    lda #$2C
    sta $4321                   ; BBAD2: $212C (TM)
    lda #<SKY_SPLIT_TABLE
    sta $4322                   ; A1T2L
    lda #>SKY_SPLIT_TABLE
    sta $4323                   ; A1T2H
    lda #^SKY_SPLIT_TABLE
    sta $4324                   ; A1B2 (bank $7E)
    ; --- arm CH2 in the NMI HDMA enable mask (additive; pv_rebuild ORs too) ---
    lda NMI_HDMA_ENABLE
    ora #$04
    sta NMI_HDMA_ENABLE
    plp                         ; WIDTH-LINT: ok — restores caller A16/I16
    rts

; =============================================================================
; SUBROUTINES — engine modules (the documented sf_mode7.inc link-partner
; order, plus the sprite + DMA engines sf_frame_end / spr require; the
; perspective LUT slots into RODATA mid-list)
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"      ; channel wrapper + helpers (sf_fx order:
.include "hdma_color_engine.asm";   alloc -> hdma -> color; the color engine
                                ;   pulls gradient_ease_lut.inc itself)
.include "colormath_engine.asm" ; sf_colormath_* (shadow-only; NMI commits)
.include "palette_engine.asm"   ; sf_pal / sf_pal_cycle (+ dma_scheduler tick)
.include "tad_bridge.asm"       ; the tad_* entry points sf_audio.inc JSRs into
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; =============================================================================
; DATA — first-party assets + the track blob
; =============================================================================

; --- first-party assets (committed generator output; see assets/*.py) ---
.include "assets/vehicle.inc"
.include "assets/track_palette.inc"

; --- the 32KB interleaved track blob (its own ROM bank) ---
.segment "BANK1"
; ca65 resolves .incbin relative to THIS file's directory, not via -I — so
; the "assets/<basename>" form is copy-safe (copy-to-adapt only changes the
; basename).
track_map:
    .incbin "assets/track_map.bin"
