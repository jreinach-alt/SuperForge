; =============================================================================
; boss_saucer — Mode 7 SCALING boss battle (a lunging flying saucer + beam)
; =============================================================================
; The SCALING genre rail: like the boss template, the boss IS the Mode 7 BG
; layer (the hardware affine matrix scales + rotates the whole plane for free),
; but here SCALING is the headline motion. The saucer LUNGES toward the camera —
; the affine matrix zooms it from a far speck to a screen-filling disc — and at
; the lunge apex it FIRES A VERTICAL BEAM straight down a locked column. The
; player, the beam, the player's shots, and the HP HUD are SPRITES composited
; over the Mode 7 saucer (the affine matrix never touches OBJ).
;
; Controls:  LEFT / RIGHT  strafe the gunship   ·   A (held)  fire upward
;            START  pause / unpause   (Select is unmapped — no in-game menu)
;
; Forked from templates/boss/main.asm (same static-affine spine). What changed:
;   - the orb-rain attack (an 8-slot sf_pool of falling SPR_PROJECTILE orbs) is
;     REMOVED. The saucer attacks with a BEAM, not orbs.
;   - FIGHT now runs a LUNGE CYCLE that drives b_scale every frame:
;        FAR (rest scale) -> APPROACH (ramp scale DOWN, saucer GROWS to fill the
;        screen) -> NEAR (lock the beam column to the player's X, telegraph then
;        fire the beam) -> RETREAT (ramp scale back UP to rest) -> repeat.
;     Bigger b_scale value = SMALLER/farther saucer (the matrix maps
;     screen->texel), so a lunge is a scale RAMP-DOWN. Rotation is OFF in the
;     fight so SCALING is the obvious motion, not spin.
;   - the BEAM: a vertical column of SPR_BEAM 8x8 sprites stacked from the
;     saucer's underside emitter (~y=56) past the player band (~y=184). Drawn
;     DIM during a ~24f telegraph (the player's window to strafe out of the
;     locked column), then FULL + DAMAGING during a ~30f active window
;     (col_box player-vs-beam-column drops p_hp + arms iframes).
;
; The static-affine plumbing is unchanged from the boss template:
;   - sf_boss_mode7_on installs Mode 7 with M7_PV_ACTIVE=1 (so the stock NMI
;     commits M7SEL/M7X/M7Y + scroll) but arms NO HDMA — one uniform affine
;     matrix per frame is cheap, unlike the per-scanline matrix rebuild an HDMA
;     perspective effect pays every frame.
;   - sf_boss_matrix (first thing each frame, before active display) writes the
;     M7A-D matrix from (scale, angle) directly via mode7_set_static.
;   - the masked reset uses sf_bright_fade (forced-blank swap), NOT a custom
;     NMI tilemap-swap: rebuilding the tilemap live risks a mid-frame VRAM write
;     the PPU is still reading, so the swap is done under forced blank instead.
;
; OBJ-OVER-MODE-7 (baked in): the Mode 7 map fills VRAM words $0000-$3FFF, so
; the OBJ name base moves to word $4000 (OBSEL base bits %010); the sprite CHR uploads
; there and OAM tile numbers stay 0.. relative to that base.
;
; OAM SLOT MAP (this template — SPR_ORDER_MODE=2, stable slots, tests read by
; identity):
;     0       player gunship (16x16)
;     1-16    beam column segments (SPR_BEAM 8x8; parked y=$F0 when no beam)
;     17-24   boss HP HUD (8 SPR_HP_LIT/DIM pips)
;     25-28   player shots (SPR_SHOT)
;
; File layout (top to bottom): tuning equates -> RESET (init: Mode 7 map,
;   palette, sprite CHR, Mode 7 on, audio) -> game_loop (the frame spine) ->
;   battle_init -> state_update (the ST_* state machine) -> fight_update + its
;   helpers (player move/fire, shots, lunge, beam, phase) -> draw_frame +
;   draw_hp_hud -> draw_text / draw_overlays / draw_title (the text cards) ->
;   engine includes -> committed assets (palette, sprites, the Mode 7 map blob).
; Frame loop: game_loop is the once-per-frame heartbeat — start reading there.
;
; Build:  make boss_saucer  (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad_m7.cfg
;   ^ Linker-config sentinel: a 96KB, three-bank image — code in bank 0, the 32KB
;     saucer-map blob in BANK1 (bank 1), and the TAD audio data in bank 2. The
;     generic build/%.sfc rule reads this line; because the name matches *_tad*.cfg
;     it ALSO links the TAD audio driver + song objects and adds the audio include
;     path (no Makefile edit). Copy-to-adapt keeps the line. The saucer map needs a
;     dedicated bank because the whole 32KB fills one bank and DMA can't cross a
;     bank boundary. (See docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "SAUCER DOWN"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_video.inc"         ; sf_load_obj_chr, sf_load_obj_pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_mode7.inc"         ; sf_mode7_load_map (the VRAM map DMA wrapper)
.include "sf_mode7_affine.inc"  ; sf_boss_mode7_on / sf_boss_center / sf_boss_matrix
.include "sf_fx.inc"            ; sf_bright_fade / sf_bright_fade_tick (masked fade)
.include "sf_collision.inc"     ; col_box (AABB hit detection)
.include "sf_pool.inc"          ; sf_pool_* (the 8-slot attack pool)
.include "sf_input.inc"
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD driver ca65 API (the vendored SPC700 driver)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids for the shipped song set
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music / sf_sfx

; --- the saucer pivot (map pixels): map is 1024x1024, saucer centered ---
BOSS_CX = 512
BOSS_CY = 512

; --- the matrix maps screen->texel: BIGGER scale = saucer looks SMALLER. ---
;     SCALING IS THE HEADLINE: the saucer lunges by ramping scale DOWN (grows).
SCALE_NATIVE  = $0100           ; 1.0 (native texel:pixel)
INIT_SCALE    = $0180           ; 1.5 — whole saucer visible at rest (the FAR/rest
                                ;   pose of the lunge cycle). A smaller value here
                                ;   = a bigger saucer at rest.
REVEAL_SCALE  = $0500           ; reveal start: saucer is tiny/far (5.0)
DEATH_SCALE   = $0700           ; death recede ceiling (safety clamp). NOTE: the
                                ;   recede adds REVEAL_STEP for REVEAL_FRAMES frames,
                                ;   so from INIT_SCALE it only reaches ~$04C8 — this
                                ;   ceiling is never actually hit; it just bounds it.

; --- the LUNGE: the saucer dives toward the camera. NEAR is much SMALLER than
;     INIT_SCALE (rest) so the saucer visibly GROWS to fill the screen on the
;     approach. The lunge is the whole point of this demo. ---
LUNGE_NEAR_SCALE = $00A0        ; near/lunge apex (0.625) — saucer fills the view
LUNGE_FAR_FRAMES = 40           ; dwell at rest before each approach
LUNGE_RAMP_FRAMES = 40          ; approach + retreat ramp length (each)
; per-frame approach/retreat scale step (INIT_SCALE - LUNGE_NEAR_SCALE)/ramp
LUNGE_STEP    = (INIT_SCALE - LUNGE_NEAR_SCALE) / LUNGE_RAMP_FRAMES  ; =$0005/fr

; --- player sprite placement (fixed-screen, low band; player slides L/R) ---
PLAYER_Y     = 184              ; fixed Y (player only strafes on X)
PLAYER_X0    = 120              ; spawn X (center-ish)
PLAYER_W     = 16               ; player box width (16x16 sprite)
PLAYER_H     = 16
PLAYER_XMIN  = 8                ; clamp range on screen (9-bit X, kept 0..255)
PLAYER_XMAX  = 232

; --- combat tuning ---
PLAYER_SPEED  = 3               ; px/frame strafe
SHOT_SPEED    = 6               ; px/frame upward (toward the saucer)
SHOT_W        = 8
SHOT_H        = 8
IFRAME_LEN    = 30              ; player invuln frames after a hit
PLAYER_HP0    = 3
BOSS_HP0      = 240             ; long enough that a careless player can lose
SHOT_DMG      = 5               ; HP per saucer hit (~48 hits to kill)
SHOT_FIRE_GAP = 8               ; min frames between auto-fires (cadence)

; --- saucer hitbox: the saucer disc fills the screen center, so the hitbox is
;     WIDE — a player shot fired straight up from any column reaches it. The
;     saucer's BEAM, by contrast, is a NARROW locked column, so the player
;     dodges the beam by strafing out of the column while still able to hit the
;     wide saucer. ---
BOSS_HIT_X = 16
BOSS_HIT_Y = 40
BOSS_HIT_W = 224                ; spans most of the 256px screen width
BOSS_HIT_H = 96

; --- the BEAM: a vertical energy column the saucer fires straight down at the
;     lunge apex. The column X is LOCKED to the player's X when the approach
;     completes (so the player must strafe out during the telegraph). Drawn as a
;     stack of SPR_BEAM 8x8 segments from the saucer emitter (y=BEAM_Y0) down
;     past the player band. ---
BEAM_SEGS       = 16            ; number of 8x8 beam segments (16 * 8 = 128 px)
BEAM_Y0         = 56            ; top of the beam (saucer underside emitter)
BEAM_W          = 8             ; beam column hit width (the 8x8 segment width)
BEAM_TELEGRAPH  = 24            ; telegraph frames (dim, no damage — dodge window)
BEAM_ACTIVE     = 30            ; active frames (full, damaging)
; the beam's hitbox spans from its top down past the player (Y/H cover the
; player band; the X is beam_x, set per-fire).
BEAM_HIT_Y      = BEAM_Y0
BEAM_HIT_H      = 160           ; reaches well past PLAYER_Y (184)

; --- beam sub-states (beam_state) ---
BEAM_OFF   = 0
BEAM_TELE  = 1                  ; telegraphing (dim, dodge window)
BEAM_FIRE  = 2                  ; active (full, damaging)

; --- lunge sub-states (lunge_state), driven during FIGHT ---
LUNGE_FAR      = 0              ; dwell at rest scale, then -> APPROACH
LUNGE_APPROACH = 1              ; ramp scale DOWN to NEAR (saucer GROWS); at near,
                                ;   lock the beam column + start the telegraph
LUNGE_NEAR     = 2              ; hold near while the beam telegraphs then fires
LUNGE_RETREAT  = 3              ; ramp scale UP back to rest, then -> FAR

; --- reveal/death pacing ---
REVEAL_FRAMES = 60              ; reveal scale ramp length
HOLD_FRAMES   = 45              ; pause at full size before the fight
FADE_FRAMES   = 32              ; bright-fade length (intro/death/lose)
RESULT_FRAMES = 90              ; how long the result screen holds
RESULT_DIM    = 7               ; brightness (0..15) the scene dims to behind a
                                ;   result card — dimmed, NOT black, so the win/
                                ;   lose word reads over the still-visible arena

; --- result / title text cards (8x8 glyph sprites over the scene; slots 29+, so
;     the tests' stable slot map 0..28 is untouched). Glyph tiles are SPR_G_*
;     (assets/sprites.inc); the pen advances GTEXT_ADV px per cell. ---
GTEXT_END     = $FFFE           ; glyph-string terminator (not a valid tile)
GTEXT_SPACE   = $FFFF           ; glyph-string space: advance the pen, draw nothing
GTEXT_ADV     = 6               ; pen advance per glyph cell (5px glyph + 1px gap)
CARD_Y        = 100             ; result-card text row (vertically centred-ish)
DEFEAT_X      = (256 - 6 * GTEXT_ADV) / 2   ; "DEFEAT" = 6 cells, centred
VICTORY_X     = (256 - 7 * GTEXT_ADV) / 2   ; "VICTORY" = 7 cells, centred
CARD_BG_TILES = 8               ; banner width in 8x8 SPR_CARDBG tiles (64px)
CARD_BG_X0    = 128 - CARD_BG_TILES * 8 / 2 ; centred banner left edge (=96)
CARD_BG_Y0    = CARD_Y - 4      ; banner top (the glyph row sits centred in it)

; --- boot title card: the game name + the controls line, shown over the dark
;     sky ABOVE the growing saucer (below the HP HUD row) during REVEAL + HOLD,
;     then auto-dismissed when the fight starts. The reviewer played three loops
;     before discovering A = fire, so the controls line is the point. Placed high
;     over the sky so no banner is needed. ---
TITLE_Y1      = 30              ; game-name row
TITLE_Y2      = 42              ; controls row
TITLE1_CELLS  = 11             ; "SAUCER DOWN"     (S A U C E R _ D O W N)
TITLE2_CELLS  = 15             ; "<> MOVE   A FIRE"
TITLE1_X      = (256 - TITLE1_CELLS * GTEXT_ADV) / 2   ; centred
TITLE2_X      = (256 - TITLE2_CELLS * GTEXT_ADV) / 2   ; centred

; --- per-frame reveal/death scale step (REVEAL_SCALE-INIT_SCALE)/REVEAL_FRAMES
REVEAL_STEP = (REVEAL_SCALE - INIT_SCALE) / REVEAL_FRAMES   ; =$000E/frame down

; --- state machine indices (b_state) ---
ST_INTRO   = 0                  ; fade IN from black, then -> REVEAL
ST_REVEAL  = 1                  ; ramp scale REVEAL_SCALE -> INIT_SCALE (grow in)
ST_HOLD    = 2                  ; brief pause at full size
ST_FIGHT   = 3                  ; player control + lunge + beam + hit detection
ST_DEATH   = 4                  ; saucer recedes (scale up) + fade out (win)
ST_LOSE    = 5                  ; fade out (player died)
ST_RESULT  = 6                  ; result hold (win/lose), then RESET
ST_RESET   = 7                  ; re-init under forced blank -> REVEAL (loop)

; --- joypad masks (JOY1_CURRENT / JOY1_PRESSED_LATCH bit layout) ---
JOY_RIGHT = $0100               ; strafe right
JOY_LEFT  = $0200               ; strafe left
JOY_A     = $0080               ; fire
JOY_START = $1000               ; pause toggle (rising edge; Select is unmapped)

; --- player-shot pool: 4 slots (the things that damage the saucer). Arrays in
;     the $1800-$1DFF game-array region (pool contract). Drawn in OAM slots
;     25-28 (past the beam band 1-16 and the HP-HUD band 17-24). The orb pool
;     from the boss template is REMOVED (the saucer attacks with the beam). ---
SHOT_N     = 4
SHOT_ALIVE = $1850              ; alive[4]
SHOT_X     = $1858              ; x[4]
SHOT_Y     = $1860              ; y[4]

; --- pause flag ($1868, just past the shot pool). 1 = the fight is frozen;
;     START toggles it. Select is intentionally left unmapped (this rail has no
;     in-game menu). Cleared by battle_init (never assume power-on zero). ---
PAUSED     = $1868

; --- OAM slot map (stable; SPR_ORDER_MODE=2). Each band is non-overlapping. ---
PLAYER_SLOT = 0                 ; player gunship
BEAM_SLOT0  = 1                 ; beam segments 1..16
HUD_SLOT0   = 17                ; HP HUD pips 17..24 (8)
SHOT_SLOT0  = 25                ; player shots 25..28 (4)

; --- game DP state (kit contract: $32-$5F). The boss template's orb-pool vars
;     (spawn_timer, au_i) are repurposed for the lunge + beam. ---
b_scale     = $32               ; current matrix scale (1.7.8) — DRIVEN BY LUNGE
b_angle     = $34               ; current rotation angle (low byte = 0..255)
b_cx        = $36               ; matrix center X (map px)
b_cy        = $38               ; matrix center Y (map px)
b_state     = $3A               ; state machine index (ST_*)
b_timer     = $3C               ; per-state frame timer (counts down)
b_hp        = $3E               ; saucer HP (0..BOSS_HP0)
b_phase     = $40               ; saucer phase index (0..2; higher = faster lunge)
b_vuln      = $42               ; saucer vulnerability flag (1 = shots can damage)
p_x         = $44               ; player x (16-bit, low byte is the OAM X)
beam_x      = $46               ; beam column X (locked to player X at approach end)
p_hp        = $48               ; player HP (0..PLAYER_HP0)
p_iframe    = $4A               ; player invuln frames remaining
lunge_state = $4C               ; lunge sub-state (LUNGE_*) — was spawn_timer
rng         = $4E               ; xorshift RNG state (16-bit)
fire_timer  = $50               ; player auto-fire cadence countdown
b_result    = $52               ; result flag: 1 = win, 2 = lose (for HUD/tests)
lunge_timer = $54               ; lunge/beam phase countdown — was b_anglespd
                                ;   (rotation is OFF in the fight, so b_anglespd
                                ;   is free to repurpose). FAR dwell, then beam
                                ;   telegraph + active countdown — these phases
                                ;   never overlap (FAR has no beam; NEAR has the
                                ;   beam), so one timer covers both.
su_i        = $56               ; shots_update / draw loop index (byte offset)
beam_state  = $58               ; beam sub-state (BEAM_*) — was au_i
hud_i       = $5A               ; HP-HUD draw loop index / beam draw loop index
hud_x       = $5C               ; HP-HUD draw x cursor / beam draw Y cursor
hud_lit     = $5E               ; HP-HUD lit threshold / player-tile scratch

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y + scroll commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    sf_audio_init               ; boot the S-SMP + TAD driver ONCE, at power-on (the
                                ;   S-SMP must still be in its IPL state; this rail's
                                ;   soft reset is a masked re-init, never a re-boot,
                                ;   so sf_audio_init is never called a second time)

    ; --- STABLE OAM ordering: the draw assigns fixed slots (0 player, 1-16
    ;     beam segments, 17-24 HP HUD, 25-28 shots) and the tests read those
    ;     slots by identity, so disable the engine's default Y-sort (mode 2 =
    ;     stable, no remap — sprites keep their call order). ---
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- boss Mode 7 map upload (under the coldstart forced blank) ---
    sf_mode7_load_map saucer_map, #$8000

    ; --- boss palette -> CGRAM 0.. (index 0 = dark arena backdrop) ---
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    ldx #$0000
bpal_loop:
    .a8
    lda f:saucer_pal, x
    sta $2122                   ; CGDATA (low then high byte, auto-pair)
    inx
    cpx #(SAUCER_PAL_COUNT * 2)
    bne bpal_loop
    rep #$30
    .a16
    .i16

    ; --- sprite CHR + palette out of the Mode 7 map's VRAM ---
    ; Map owns VRAM words $0000-$3FFF, so OBJ name base = word $4000:
    ; OBSEL base bits %010 = word $4000. tile 1024 IS word $4000, so OAM tile
    ; numbers stay 0.. relative to the OBSEL base.
    sf_load_obj_pal 0, sprite_pal
    sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes
    sep #$20
    .a8
    lda #$02
    sta $2101                   ; OBSEL (OBJ size + name base): base word $4000,
                                ;   size pair 0 = 8x8 small / 16x16 large. The player
                                ;   is a 16x16 LARGE sprite (its 2x2 tile block at
                                ;   {0,1,16,17}); every other actor (beam, shot, HP
                                ;   pip, text glyph) is an 8x8 SMALL sprite — one
                                ;   tile, no neighbor bleed.
    rep #$30
    .a16
    .i16

    ; --- Mode 7 static affine on + center on the saucer ---
    sf_boss_mode7_on
    sf_boss_center #BOSS_CX, #BOSS_CY

    jsr battle_init             ; arm the state machine: reveal-tiny + fresh combat
    sf_boss_matrix b_scale, b_angle     ; first matrix before screen-on

    spr_clear
    sf_debug_magic

    ; --- start DARK (INTRO fades IN from black). The intro fade is "masked"
    ;     by construction: INIDISP starts at brightness 0 and the discontinuous
    ;     boss-map upload above already happened under the coldstart forced
    ;     blank, so the first visible pixel only appears as the fade brightens.
    sep #$20
    .a8
    lda #$00
    sta $2100                   ; INIDISP: brightness 0 (display on, but black)
    sta SHADOW_INIDISP          ; NMI re-commits INIDISP from this shadow
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16
    sf_bright_fade #15, #FADE_FRAMES    ; arm the fade-IN (0 -> 15 over 32 frames)
    sf_music #Song::gimo_297            ; start the boss theme; it streams in over the
                                        ;   sf_audio_ticks the frame loop pumps below

; =============================================================================
; The frame spine: matrix first (consistent frame), then the per-state update,
; then the per-state draw. The state machine drives b_scale (the LUNGE) + combat;
; the draw is shared. Stable OAM slots (preflight map):
;   0       player ship
;   1-16    beam column segments (draw-every-frame, dead parked at y=$F0)
;   17-24   saucer HP HUD segments
;   25-28   player shots
; =============================================================================
game_loop:
    .a16
    sf_frame_begin              ; wait for the NMI; latch input
    sf_audio_tick               ; pump TAD every frame (streams the song load + the
                                ;   queued SFX to the SPC700; never gate it on state)

    ; --- START toggles a full freeze (its rising edge; Select is unmapped). While
    ;     paused the state machine + combat below are skipped, so nothing moves and
    ;     nothing can hurt the player; the matrix commit, the draw, the audio, and
    ;     the frame sync keep running, so the held frame shows and the music plays. ---
    lda JOY1_PRESSED_LATCH
    bit #JOY_START
    beq gl_no_toggle
    lda PAUSED
    eor #$0001
    sta PAUSED
gl_no_toggle:
    .a16

    ; --- the matrix FIRST, before active display (one consistent frame) ---
    sf_boss_matrix b_scale, b_angle

    lda PAUSED
    bne gl_frozen               ; paused -> skip the update + the fade advance
    jsr state_update            ; per-state logic (reveal, lunge, beam, death...)
    sf_bright_fade_tick         ; advance any armed brightness fade (masked swaps)
gl_frozen:
    .a16
    jsr draw_frame              ; player + beam + HP HUD + shots into stable OAM

    ; --- heartbeat + debug mirrors (test orchestration; visual asserts stay on
    ;     rendered pixels — these only sequence screenshots / read HP). ---
    ldx #$0000
    lda FRAME_COUNTER
    sta f:$7E0000 + $E010, x
    lda b_state
    sta f:$7E0000 + $E012, x    ; state index
    lda b_hp
    sta f:$7E0000 + $E014, x    ; boss HP
    lda p_hp
    sta f:$7E0000 + $E016, x    ; player HP
    lda b_scale
    sta f:$7E0000 + $E018, x    ; current matrix scale
    lda b_result
    sta f:$7E0000 + $E01A, x    ; result (0 none / 1 win / 2 lose)
    lda beam_state
    sta f:$7E0000 + $E01C, x    ; beam sub-state (0 off / 1 telegraph / 2 active)
    lda lunge_state
    sta f:$7E0000 + $E01E, x    ; lunge sub-state (0 far / 1 appr / 2 near / 3 ret)

    sf_frame_end                ; resolve sprites; signal the OAM DMA
    jmp game_loop

; =============================================================================
; battle_init — (re)arm the full battle: reveal-tiny boss + fresh combat state.
; Called from RESET and from the RESET state (loop). A16/I16 entry/exit.
; =============================================================================
battle_init:
    .a16
    .i16
    lda #REVEAL_SCALE
    sta b_scale                 ; start tiny/far (grows in during REVEAL)
    stz b_angle
    lda #BOSS_CX
    sta b_cx
    lda #BOSS_CY
    sta b_cy
    lda #BOSS_HP0
    sta b_hp
    stz b_phase
    stz b_vuln
    lda #PLAYER_X0
    sta p_x                     ; player Y is the constant PLAYER_Y (no p_y var)
    lda #PLAYER_HP0
    sta p_hp
    stz p_iframe
    stz fire_timer
    stz b_result
    stz PAUSED                  ; each battle starts unpaused (RAM is random at boot)
    lda #$ACE1                  ; non-zero xorshift seed
    sta rng
    ; --- lunge + beam start idle (the fight arms them on FIGHT entry) ---
    stz lunge_state             ; LUNGE_FAR
    stz beam_state              ; BEAM_OFF
    stz lunge_timer
    lda #PLAYER_X0
    sta beam_x                  ; harmless initial column (off until a fire locks)
    ; clear the player-shot pool (all slots free); the orb pool is removed
    sf_pool_init SHOT_ALIVE, SHOT_N
    ; enter REVEAL with its ramp timer
    lda #ST_REVEAL
    sta b_state
    lda #REVEAL_FRAMES
    sta b_timer
    rts

; =============================================================================
; state_update — per-frame state machine (A16/I16 entry/exit).
; =============================================================================
; Dispatches on b_state. Each state advances b_timer and may transition. The
; matrix scale/angle and combat all flow from here; the draw is separate.
; WIDTH-RISK: A16/I16 entry; pure A16/I16 throughout (no width toggles); the
; jsr'd helpers (combat) restore A16/I16. Exits A16/I16.
state_update:
    .a16
    .i16
    lda b_state
    asl                         ; *2 for the word jump table
    tax
    jmp (su_jump, x)

su_jump:
    .addr su_intro              ; ST_INTRO  (0)
    .addr su_reveal             ; ST_REVEAL (1)
    .addr su_hold               ; ST_HOLD   (2)
    .addr su_fight              ; ST_FIGHT  (3)
    .addr su_death              ; ST_DEATH  (4)
    .addr su_lose               ; ST_LOSE   (5)
    .addr su_result             ; ST_RESULT (6)
    .addr su_reset              ; ST_RESET  (7)

; --- INTRO: reserved (battle_init enters REVEAL directly with a fade-in). ---
su_intro:
    .a16
    lda #ST_REVEAL
    sta b_state
    rts

; --- REVEAL: ramp scale REVEAL_SCALE -> INIT_SCALE so the boss GROWS in. ---
su_reveal:
    .a16
    lda b_scale
    sec
    sbc #REVEAL_STEP            ; smaller scale = bigger boss
    cmp #INIT_SCALE
    bcs su_reveal_store         ; still above target -> keep shrinking the value
    lda #INIT_SCALE             ; clamp at full size
su_reveal_store:
    .a16
    sta b_scale
    ; gentle idle rotation begins once visible (atmosphere)
    lda b_angle
    inc a
    and #$00FF
    sta b_angle
    lda b_timer
    dec a
    sta b_timer
    bne su_done
    ; reveal complete -> HOLD
    lda #INIT_SCALE
    sta b_scale
    lda #ST_HOLD
    sta b_state
    lda #HOLD_FRAMES
    sta b_timer
su_done:
    .a16
    rts

; --- HOLD: brief pause at full size, slow rotation, then FIGHT. ---
su_hold:
    .a16
    lda b_angle
    inc a
    and #$00FF
    sta b_angle
    lda b_timer
    dec a
    sta b_timer
    bne su_hold_ret
    lda #ST_FIGHT
    sta b_state
    lda #1
    sta b_vuln                  ; saucer becomes vulnerable in the fight
    ; --- arm the lunge cycle: rest at FAR scale, dwell, then approach ---
    lda #INIT_SCALE
    sta b_scale
    stz lunge_state             ; LUNGE_FAR
    stz beam_state              ; BEAM_OFF
    lda #LUNGE_FAR_FRAMES
    sta lunge_timer
    stz b_angle                 ; rotation OFF in the fight (scaling is the motion)
su_hold_ret:
    .a16
    rts

; --- FIGHT: handed to the combat routine. ---
su_fight:
    .a16
    jsr fight_update
    rts

; --- DEATH: boss recedes (scale UP) at full brightness (the death tilt-spin),
;     then dims the scene and shows the VICTORY card at RESULT. ---
su_death:
    .a16
    lda b_scale
    clc
    adc #REVEAL_STEP            ; bigger value = boss shrinks away
    cmp #DEATH_SCALE
    bcc su_death_store
    lda #DEATH_SCALE            ; clamp
su_death_store:
    .a16
    sta b_scale
    ; spin faster as it dies
    lda b_angle
    clc
    adc #3
    and #$00FF
    sta b_angle
    lda b_timer
    dec a
    sta b_timer
    bne su_death_ret
    ; recede done -> dim the scene (not black) behind the VICTORY card, RESULT(win)
    sf_bright_fade #RESULT_DIM, #FADE_FRAMES
    lda #1
    sta b_result               ; WIN
    lda #ST_RESULT
    sta b_state
    lda #RESULT_FRAMES
    sta b_timer
su_death_ret:
    .a16
    rts

; --- LOSE: fade to black (already armed on entry); then RESULT(lose). ---
su_lose:
    .a16
    lda b_timer
    dec a
    sta b_timer
    bne su_lose_ret
    lda #2
    sta b_result               ; LOSE
    lda #ST_RESULT
    sta b_state
    lda #RESULT_FRAMES
    sta b_timer
su_lose_ret:
    .a16
    rts

; --- RESULT: hold the win/lose screen, then arm a fade-out into RESET. ---
su_result:
    .a16
    lda b_timer
    dec a
    sta b_timer
    bne su_result_ret
    ; arm a fade to black, then RESET masks the re-init at INIDISP==0
    sf_bright_fade #0, #FADE_FRAMES
    lda #ST_RESET
    sta b_state
    lda #FADE_FRAMES            ; wait out the fade before the masked swap
    sta b_timer
su_result_ret:
    .a16
    rts

; --- RESET: wait for the fade-out to reach black (INIDISP==0), then re-init
;     the battle UNDER forced blank (the masked swap), and fade back IN. ---
su_reset:
    .a16
    lda b_timer
    dec a
    sta b_timer
    bne su_reset_ret
    ; INIDISP is now 0 (the fade-out completed) — the masked swap frame.
    ; Re-init all battle state (this is the discontinuous "swap"); the map +
    ; palette are static so no VRAM upload is needed, but if any were it would
    ; be safe here because the screen is black.
    jsr battle_init             ; -> ST_REVEAL, fresh combat, boss tiny again
    sf_bright_fade #15, #FADE_FRAMES    ; fade back IN
su_reset_ret:
    .a16
    rts

; =============================================================================
; fight_update — combat: player control, player shots, the LUNGE cycle (drives
; b_scale + the beam), beam-vs-player hit detection, phase pacing, win/lose.
; A16/I16 throughout.
; WIDTH-RISK: A16/I16 entry/exit. The jsr'd helpers all keep A16/I16; col_box
; and the sf_pool macros assert/return A16/I16. No width toggles in this body.
; =============================================================================
fight_update:
    .a16
    .i16
    jsr player_move             ; LEFT/RIGHT strafe + clamp
    jsr player_fire             ; A-fire a SPR_SHOT upward
    jsr shots_update            ; advance shots; shot-vs-saucer col_box
    jsr boss_phase              ; HP-driven phase (paces the lunge cycle)
    jsr boss_lunge              ; the LUNGE: ramp b_scale FAR<->NEAR, drive beam
    jsr beam_update             ; beam telegraph/active timing + beam-vs-player
    ; --- iframe countdown ---
    lda p_iframe
    beq fu_no_iframe
    dec a
    sta p_iframe
fu_no_iframe:
    .a16
    ; --- win / lose checks ---
    lda b_hp
    bne fu_check_lose
    ; saucer dead -> DEATH (recede + fade), win
    stz b_vuln
    stz beam_state              ; kill the beam on death
    lda #ST_DEATH
    sta b_state
    lda #REVEAL_FRAMES
    sta b_timer
    rts
fu_check_lose:
    .a16
    lda p_hp
    bne fu_alive
    ; player dead -> dim the scene (not black) so the DEFEAT card reads, LOSE
    sf_bright_fade #RESULT_DIM, #FADE_FRAMES
    lda #ST_LOSE
    sta b_state
    lda #FADE_FRAMES
    sta b_timer
fu_alive:
    .a16
    rts

; =============================================================================
; player_move — LEFT/RIGHT strafe p_x by PLAYER_SPEED, clamp on-screen.
; WIDTH-RISK: A16/I16 entry/exit (no toggles).
; =============================================================================
player_move:
    .a16
    .i16
    lda JOY1_CURRENT
    bit #JOY_LEFT
    beq pm_no_left
    lda p_x
    sec
    sbc #PLAYER_SPEED
    cmp #PLAYER_XMIN
    bcs pm_store_left
    lda #PLAYER_XMIN
pm_store_left:
    .a16
    sta p_x
pm_no_left:
    .a16
    lda JOY1_CURRENT
    bit #JOY_RIGHT
    beq pm_no_right
    lda p_x
    clc
    adc #PLAYER_SPEED
    cmp #PLAYER_XMAX
    bcc pm_store_right
    lda #PLAYER_XMAX
pm_store_right:
    .a16
    sta p_x
pm_no_right:
    .a16
    rts

; =============================================================================
; player_fire — fire a SPR_SHOT while A is HELD, rate-limited by fire_timer
; (one shot per SHOT_FIRE_GAP frames). Shots spawn just above the player and
; travel up (advanced in shots_update). A-driven (not auto) so the battle's
; outcome is player-driven: fire to damage the boss, hold off and the boss
; never dies. The cadence makes a held A a steady stream, not a one-per-frame
; flood that exhausts the 4-slot pool.
; WIDTH-RISK: A16/I16 entry/exit.
; =============================================================================
player_fire:
    .a16
    .i16
    ; tick the cadence countdown down to 0
    lda fire_timer
    beq pf_ready
    dec a
    sta fire_timer
    rts
pf_ready:
    .a16
    ; A must be HELD to fire (btn-style; the cadence rate-limits a held A)
    lda JOY1_CURRENT
    bit #JOY_A
    beq pf_no_fire
    sf_pool_spawn SHOT_ALIVE, SHOT_N
    cmp #$FFFF
    beq pf_no_fire              ; pool full -> skip this shot
    tax                         ; X = byte offset of the claimed slot
    lda p_x
    clc
    adc #4                      ; center the 8x8 shot over the 16x16 player
    sta SHOT_X, x
    lda #PLAYER_Y
    sec
    sbc #8                      ; spawn just above the player
    sta SHOT_Y, x
    lda #SHOT_FIRE_GAP
    sta fire_timer
    sf_sfx #SFX::fire_arrow     ; the player's gun report (one per fired shot)
pf_no_fire:
    .a16
    rts

; =============================================================================
; shots_update — advance every live player shot UP; cull off the top; test each
; vs the boss hitbox (when b_vuln) -> drop b_hp + free the shot.
; WIDTH-RISK: A16/I16 entry/exit. col_box + sf_pool_kill_x keep A16/I16. X holds
; the slot offset across col_box (col_box clobbers A,X,Y) -> re-derive via the
; loop index kept on the stack? No: we reload X from the loop var su_i each pass.
; =============================================================================
shots_update:
    .a16
    .i16
    stz su_i
su_loop:
    .a16
    ldx su_i
    lda SHOT_ALIVE, x
    beq su_next                 ; free slot
    ; move up
    lda SHOT_Y, x
    sec
    sbc #SHOT_SPEED
    sta SHOT_Y, x
    cmp #16                     ; reached the top band -> cull
    bcc su_kill
    ; --- shot box vs boss hitbox (only damages while vulnerable) ---
    lda b_vuln
    beq su_next
    ldx su_i
    col_box SHOT_X, SHOT_Y, #SHOT_W, #SHOT_H, #BOSS_HIT_X, #BOSS_HIT_Y, #BOSS_HIT_W, #BOSS_HIT_H
    cmp #$0001
    bne su_next
    ; hit! drop boss HP (saturating) and free the shot
    lda b_hp
    cmp #SHOT_DMG
    bcs su_dmg
    lda #SHOT_DMG               ; clamp so it can't underflow below 0
su_dmg:
    .a16
    sec
    sbc #SHOT_DMG
    sta b_hp
    bra su_kill
su_kill:
    .a16
    ldx su_i
    sf_pool_kill_x SHOT_ALIVE
su_next:
    .a16
    lda su_i
    clc
    adc #2
    sta su_i
    cmp #(2 * SHOT_N)
    bne su_loop
    rts

; =============================================================================
; boss_lunge — THE HEADLINE: drive b_scale every frame through the lunge cycle.
;   FAR (0): hold at rest scale (INIT_SCALE), dwell lunge_timer frames -> APPROACH
;   APPROACH (1): ramp b_scale DOWN by LUNGE_STEP toward LUNGE_NEAR_SCALE (the
;     saucer visibly GROWS). When it reaches NEAR, LOCK the beam column to the
;     player's current X and start the beam TELEGRAPH -> NEAR.
;   NEAR (2): hold at NEAR scale (the beam runs in beam_update). When the beam
;     finishes (beam_state back to OFF) -> RETREAT.
;   RETREAT (3): ramp b_scale UP by LUNGE_STEP back toward INIT_SCALE. When it
;     reaches rest -> FAR (and re-arm the dwell).
; Phase shortens the FAR dwell (faster lunges as HP drops).
; WIDTH-RISK: A16/I16 entry/exit (no toggles).
; =============================================================================
boss_lunge:
    .a16
    .i16
    lda lunge_state
    asl
    tax
    jmp (lunge_jump, x)
lunge_jump:
    .addr bl_far                ; LUNGE_FAR      (0)
    .addr bl_approach           ; LUNGE_APPROACH (1)
    .addr bl_near               ; LUNGE_NEAR     (2)
    .addr bl_retreat            ; LUNGE_RETREAT  (3)

; --- FAR: hold rest scale, dwell, then approach. ---
bl_far:
    .a16
    lda #INIT_SCALE
    sta b_scale
    lda lunge_timer
    dec a
    sta lunge_timer
    bne bl_ret
    lda #LUNGE_APPROACH
    sta lunge_state
bl_ret:
    .a16
    rts

; --- APPROACH: ramp scale DOWN (saucer grows). At NEAR, lock beam + telegraph. ---
bl_approach:
    .a16
    lda b_scale
    sec
    sbc #LUNGE_STEP             ; smaller value = bigger saucer (lunge in)
    cmp #LUNGE_NEAR_SCALE
    bcs bl_appr_store           ; still above NEAR -> keep growing
    ; reached NEAR: clamp, lock the beam column, start the telegraph
    lda #LUNGE_NEAR_SCALE
    sta b_scale
    ; LOCK the beam column to the player's body-center X at approach end. The
    ; player must then strafe out of this column during the telegraph.
    lda p_x
    clc
    adc #4                      ; center the 8px beam over the 16px player body
    sta beam_x
    lda #BEAM_TELE
    sta beam_state
    lda #BEAM_TELEGRAPH
    sta lunge_timer             ; beam_update counts this down
    lda #LUNGE_NEAR
    sta lunge_state
    rts
bl_appr_store:
    .a16
    sta b_scale
    rts

; --- NEAR: hold at NEAR while beam_update runs the telegraph+active timing.
;     When the beam returns to OFF, retreat. ---
bl_near:
    .a16
    lda #LUNGE_NEAR_SCALE
    sta b_scale
    lda beam_state
    bne bl_near_ret             ; beam still telegraphing/firing -> hold
    lda #LUNGE_RETREAT
    sta lunge_state
bl_near_ret:
    .a16
    rts

; --- RETREAT: ramp scale UP back to rest, then FAR (re-arm dwell, phase-paced). ---
bl_retreat:
    .a16
    lda b_scale
    clc
    adc #LUNGE_STEP            ; bigger value = saucer shrinks back to rest
    cmp #INIT_SCALE
    bcc bl_ret_store
    ; reached rest: clamp + go FAR with a phase-scaled dwell
    lda #INIT_SCALE
    sta b_scale
    lda #LUNGE_FAR
    sta lunge_state
    ; phase 0 = full dwell, phase 1 = -12, phase 2 = -24 (faster lunges)
    lda b_phase
    cmp #2
    bcs blr_p2
    cmp #1
    bcs blr_p1
    lda #LUNGE_FAR_FRAMES
    bra blr_set
blr_p1:
    .a16
    lda #(LUNGE_FAR_FRAMES - 12)
    bra blr_set
blr_p2:
    .a16
    lda #(LUNGE_FAR_FRAMES - 24)
blr_set:
    .a16
    sta lunge_timer
    rts
bl_ret_store:
    .a16
    sta b_scale
    rts

; =============================================================================
; beam_update — run the beam timing while it is armed (only during LUNGE_NEAR).
;   TELEGRAPH (1): dim, no damage; count lunge_timer down -> ACTIVE.
;   FIRE (2): full, damaging; while active, col_box player-vs-beam-column drops
;     p_hp + arms iframes; count down -> OFF.
; The beam column hitbox is a narrow vertical strip at beam_x spanning the
; player band; the player dodges by strafing out of the column in TELEGRAPH.
; WIDTH-RISK: A16/I16 entry/exit. col_box keeps A16/I16. No width toggles.
; =============================================================================
beam_update:
    .a16
    .i16
    lda beam_state
    beq bu_ret                  ; BEAM_OFF -> nothing
    cmp #BEAM_TELE
    beq bu_tele
    ; --- BEAM_FIRE (active): count down; damage if the player is in the column ---
    lda lunge_timer
    dec a
    sta lunge_timer
    bne bu_active_hit
    ; active window done -> beam OFF
    stz beam_state
    rts
bu_active_hit:
    .a16
    ; beam column box (beam_x, BEAM_HIT_Y, BEAM_W, BEAM_HIT_H) vs player box
    col_box beam_x, #BEAM_HIT_Y, #BEAM_W, #BEAM_HIT_H, p_x, #PLAYER_Y, #PLAYER_W, #PLAYER_H
    cmp #$0001
    bne bu_ret
    ; overlap while active -> damage if not currently invulnerable
    lda p_iframe
    bne bu_ret
    lda p_hp
    beq bu_ret                  ; already 0
    dec a
    sta p_hp
    lda #IFRAME_LEN
    sta p_iframe
    sf_sfx #SFX::player_hurt     ; the beam connects (once per hit; iframes gate it)
    rts
bu_tele:
    .a16
    ; telegraph: count down (no damage); when done -> ACTIVE
    lda lunge_timer
    dec a
    sta lunge_timer
    bne bu_ret
    lda #BEAM_FIRE
    sta beam_state
    lda #BEAM_ACTIVE
    sta lunge_timer
    sf_sfx #SFX::robot_fires_laser  ; the saucer's beam ignites (once, on go-active)
bu_ret:
    .a16
    rts

; =============================================================================
; boss_phase — derive b_phase from b_hp (thresholds). Phase paces the lunge
; cycle (shorter FAR dwell at lower HP). No rotation in the fight (scaling is
; the motion). A16/I16. Thresholds (BOSS_HP0=240, /3): hp>160 -> 0,
; 80<hp<=160 -> 1, hp<=80 -> 2.
; WIDTH-RISK: A16/I16 entry/exit (no toggles).
; =============================================================================
boss_phase:
    .a16
    .i16
    lda b_hp
    cmp #161                    ; hp > 160 -> phase 0  (BOSS_HP0=240, /3 bands)
    bcs bp_p0
    cmp #81                     ; 80 < hp <= 160 -> phase 1
    bcs bp_p1
    lda #2                      ; phase 2: hp <= 80
    sta b_phase
    rts
bp_p1:
    .a16
    lda #1
    sta b_phase
    rts
bp_p0:
    .a16
    stz b_phase
    rts

; =============================================================================
; draw_frame — shared per-frame OAM draw into the stable slot map: player at
; slot 0, beam 1-16, HP HUD 17-24, shots 25-28; unused slots parked off-screen.
; WIDTH-RISK: A16/I16 entry/exit (the spr macro handles its own widths).
; =============================================================================
draw_frame:
    .a16
    .i16
    spr_clear
    ; --- slot 0 = player (16x16 large). Hidden pre-fight + post-fight so the
    ;     boss read is clean; visible from HOLD onward. A hit-flash frame
    ;     (SPR_PLAYER_T1) shows while iframes are active. ---
    lda b_state
    cmp #ST_HOLD
    bcc df_park_player          ; states < HOLD: pre-fight, hide the player
    cmp #ST_RESULT
    bcs df_park_player          ; RESULT/RESET: hide the player
    ; pick the player frame: flash while invulnerable
    lda p_iframe
    beq df_neutral
    ; flash on alternate frames so it reads as a blink, not a solid swap
    lda FRAME_COUNTER
    and #$0004
    beq df_neutral
    lda #SPR_PLAYER_T1
    bra df_have_tile
df_neutral:
    .a16
    lda #SPR_PLAYER_T0
df_have_tile:
    .a16
    sta hud_lit                 ; reuse hud_lit as the player-tile scratch here
    spr hud_lit, p_x, #PLAYER_Y, #$0080, #2
    bra df_beam
df_park_player:
    .a16
    spr #SPR_PLAYER_T0, #0, #$00F0, #$0080, #2   ; parked off-screen (y=$F0)
    bra df_beam

; --- slots 1-16 = the BEAM column (draw EVERY slot; not-drawn parked at y=$F0).
;     Stacked SPR_BEAM 8x8 segments at beam_x from BEAM_Y0 down. When the beam
;     is OFF all 16 park. TELEGRAPH draws only every-other segment (sparse =
;     the dim "charging" read, the player's dodge window). FIRE draws all 16
;     (the solid descending beam). hud_i = segment index, hud_x = the segment Y.
df_beam:
    .a16
    stz hud_i                   ; beam segment index 0..15
    lda #BEAM_Y0
    sta hud_x                   ; running Y cursor for the segment
df_beam_loop:
    .a16
    lda beam_state
    beq df_beam_park            ; BEAM_OFF -> park this segment
    cmp #BEAM_FIRE
    beq df_beam_draw            ; active -> draw every segment
    ; telegraph -> draw only even segments (sparse dim look)
    lda hud_i
    and #$0001
    bne df_beam_park            ; odd segment in telegraph -> park (gap)
df_beam_draw:
    .a16
    spr #SPR_BEAM, beam_x, hud_x, #$0000, #2   ; 8x8 beam segment at (beam_x, Y)
    bra df_beam_next
df_beam_park:
    .a16
    spr #SPR_BEAM, #0, #$00F0, #$0000, #2        ; parked off-screen (y=$F0)
df_beam_next:
    .a16
    lda hud_x
    clc
    adc #8                      ; next segment 8px lower (seamless stack)
    sta hud_x
    lda hud_i
    inc a
    sta hud_i
    cmp #BEAM_SEGS
    bne df_beam_loop

    ; --- slots 17-24 = saucer HP HUD (8 segment sprites). ---
    jsr draw_hp_hud

    ; --- slots 25-28 = player shots (draw EVERY slot; dead parked) ---
    stz su_i
df_shot_loop:
    .a16
    ldx su_i
    lda SHOT_ALIVE, x
    beq df_shot_park
    ldx su_i
    spr #SPR_SHOT, SHOT_X, SHOT_Y, #$0000, #2       ; 8x8 cyan player bolt
    bra df_shot_next
df_shot_park:
    .a16
    spr #SPR_SHOT, #0, #$00F0, #$0000, #2
df_shot_next:
    .a16
    lda su_i
    clc
    adc #2
    sta su_i
    cmp #(2 * SHOT_N)
    bne df_shot_loop
    ; --- thruster exhaust below the player: a pulsing flame, FIGHT only (slot
    ;     29). The overlays own slots 29+ in the non-fight states (title + result
    ;     cards), so gating on FIGHT keeps this clear of them. ---
    lda b_state
    cmp #ST_FIGHT
    bne df_no_exhaust
    lda FRAME_COUNTER
    and #$0008
    beq df_exh_lo               ; alternate short / tall flame every 8 frames
    lda #SPR_EXH_HI
    bra df_exh_have
df_exh_lo:
    .a16
    lda #SPR_EXH_LO
df_exh_have:
    .a16
    sta hud_lit                 ; flame tile -> scratch (spr takes a DP operand)
    lda p_x
    clc
    adc #4                      ; centre the 8px flame under the 16px player
    sta hud_x
    spr hud_lit, hud_x, #(PLAYER_Y + 14), #$0000, #2   ; just below the hull
df_no_exhaust:
    .a16
    jsr draw_overlays           ; result / title text cards (OAM slots 29+)
    rts

; =============================================================================
; draw_hp_hud — saucer HP bar as a row of 8 segment sprites (OAM slots 17-24).
; Each segment covers BOSS_HP0/8 HP; segment i is LIT (SPR_HP_LIT) while
; b_hp > i*(BOSS_HP0/8), else DIM (SPR_HP_DIM). Drawn at a fixed top-screen row
; over the saucer BG (sprite-over-BG composition). Always draws all 8 slots so
; the OAM slot map stays stable (shots land at 25-28).
; WIDTH-RISK: A16/I16 entry/exit. The spr macro handles its own widths; the
; hud_* loop scratch stays A16. No width toggles.
; =============================================================================
HUD_SEG_HP = (BOSS_HP0 / 8)     ; HP represented by one segment (=12)
HUD_Y      = 12                 ; HP-bar row (top of screen, over the boss BG)
HUD_X0     = 80                 ; first segment x
HUD_DX     = 10                 ; segment spacing

draw_hp_hud:
    .a16
    .i16
    stz hud_i
    lda #HUD_X0
    sta hud_x
dh_loop:
    .a16
    ; threshold for this segment = hud_i * HUD_SEG_HP (small exact multiply)
    ldx #0
    stz hud_lit                 ; product accumulator
dh_mul:
    .a16
    cpx hud_i
    beq dh_mul_done
    lda hud_lit
    clc
    adc #HUD_SEG_HP
    sta hud_lit
    inx
    bra dh_mul
dh_mul_done:
    .a16
    ; segment lit if b_hp > threshold
    lda b_hp
    cmp hud_lit
    beq dh_dim                  ; equal/below -> depleted
    bcc dh_dim
    spr #SPR_HP_LIT, hud_x, #HUD_Y, #$0000, #2
    bra dh_seg_next
dh_dim:
    .a16
    spr #SPR_HP_DIM, hud_x, #HUD_Y, #$0000, #2
dh_seg_next:
    .a16
    lda hud_x
    clc
    adc #HUD_DX
    sta hud_x
    lda hud_i
    inc a
    sta hud_i
    cmp #8
    bne dh_loop
    rts

; =============================================================================
; draw_text — spell a glyph string as 8x8 SMALL OBJ sprites, left to right.
;   X (i16) = byte offset into glyph_strings of the first glyph word.
;   hud_x   = pen X (advanced GTEXT_ADV px per cell); hud_i = pen Y (held).
; Each word is a glyph TILE (SPR_G_*); GTEXT_SPACE advances the pen without
; drawing, GTEXT_END ends the run. Glyphs land in shadow-OAM slots 29+ (drawn
; after the player/beam/HUD/shots), so the tests' stable slot map 0..28 is
; untouched. Reuses the HP-HUD loop scratch (hud_x/hud_i/hud_lit), which is free
; by the time draw_overlays runs at the tail of draw_frame.
; WIDTH-RISK: A16/I16 entry/exit. spr clobbers X (our string cursor), so the
; offset is saved across it (phx/plx). No width toggles.
; =============================================================================
draw_text:
    .a16
    .i16
@loop:
    .a16
    lda f:glyph_strings, x      ; next glyph word (long: the string lives in ROM)
    cmp #GTEXT_END
    beq @done
    cmp #GTEXT_SPACE
    beq @advance                ; space: skip the draw, still advance the pen
    sta hud_lit                 ; glyph tile -> DP scratch (spr takes a DP operand)
    phx                         ; spr clobbers X — save the string cursor
    spr hud_lit, hud_x, hud_i, #$0000, #3   ; pri 3 = in front of the banner
    plx
@advance:
    .a16
    lda hud_x
    clc
    adc #GTEXT_ADV
    sta hud_x
    inx
    inx                         ; next glyph word (2 bytes)
    bra @loop
@done:
    .a16
    rts

; =============================================================================
; draw_overlays — the result text card over the dimmed end-of-battle scene.
; LOSE and RESULT(lose) draw DEFEAT; RESULT(win) draws VICTORY; every other
; state draws nothing. Called at the tail of draw_frame. A16/I16.
; =============================================================================
draw_overlays:
    .a16
    .i16
    lda b_state
    cmp #ST_FIGHT
    bcc @title                  ; INTRO/REVEAL/HOLD (< FIGHT) -> boot title card
    cmp #ST_LOSE
    beq @defeat                 ; LOSE: the player died -> DEFEAT
    cmp #ST_RESULT
    bne @none                   ; not a card state
    lda b_result
    cmp #2                      ; RESULT: 2 = lose, 1 = win
    beq @defeat
    ; --- VICTORY card (win) ---
    lda #VICTORY_X
    sta hud_x
    lda #CARD_Y
    sta hud_i
    ldx #STR_VICTORY
    bra @paint
@defeat:
    .a16
    lda #DEFEAT_X
    sta hud_x
    lda #CARD_Y
    sta hud_i
    ldx #STR_DEFEAT
@paint:
    .a16
    ; text FIRST (lower OAM slots = frontmost on SNES; pri 3 as well), then the
    ; dark banner behind it (higher slots, pri 2 — over the BG, under the text)
    jsr draw_text
    jsr draw_card_bg
@none:
    .a16
    rts
@title:
    .a16
    jsr draw_title
    rts

; =============================================================================
; draw_title — the boot title card: game name (SAUCER DOWN) + the controls line,
; two centred glyph rows over the dark sky above the growing saucer. No banner
; (the sky is already dark up here). Shown while state < FIGHT. A16/I16.
; =============================================================================
draw_title:
    .a16
    .i16
    lda #TITLE1_X
    sta hud_x
    lda #TITLE_Y1
    sta hud_i
    ldx #STR_TITLE1
    jsr draw_text
    lda #TITLE2_X
    sta hud_x
    lda #TITLE_Y2
    sta hud_i
    ldx #STR_TITLE2
    jsr draw_text
    rts

; =============================================================================
; draw_card_bg — a 2-row x CARD_BG_TILES dark banner behind a result/title word.
; Drawn AFTER the text (higher OAM slots) so the pri-3 text stays in front; the
; banner is pri 2 (over the Mode 7 BG, under the text). hud_i = tile counter,
; hud_x = pen X. A16/I16.
; =============================================================================
draw_card_bg:
    .a16
    .i16
    stz hud_i
    lda #CARD_BG_X0
    sta hud_x
@col:
    .a16
    spr #SPR_CARDBG, hud_x, #CARD_BG_Y0, #$0000, #2        ; upper banner cell
    spr #SPR_CARDBG, hud_x, #(CARD_BG_Y0 + 8), #$0000, #2  ; lower banner cell
    lda hud_x
    clc
    adc #8
    sta hud_x
    lda hud_i
    inc a
    sta hud_i
    cmp #CARD_BG_TILES
    bne @col
    rts

; --- glyph strings: runs of glyph TILE words, GTEXT_END-terminated. The STR_*
;     equates are byte offsets into this table (what draw_text takes in X). ---
glyph_strings:
STR_VICTORY = * - glyph_strings
    .word SPR_G_V, SPR_G_I, SPR_G_C, SPR_G_T, SPR_G_O, SPR_G_R, SPR_G_Y, GTEXT_END
STR_DEFEAT = * - glyph_strings
    .word SPR_G_D, SPR_G_E, SPR_G_F, SPR_G_E, SPR_G_A, SPR_G_T, GTEXT_END
STR_TITLE1 = * - glyph_strings          ; "SAUCER DOWN"
    .word SPR_G_S, SPR_G_A, SPR_G_U, SPR_G_C, SPR_G_E, SPR_G_R, GTEXT_SPACE
    .word SPR_G_D, SPR_G_O, SPR_G_W, SPR_G_N, GTEXT_END
STR_TITLE2 = * - glyph_strings          ; "<> MOVE   A FIRE"
    .word SPR_G_LARR, SPR_G_RARR, GTEXT_SPACE, SPR_G_M, SPR_G_O, SPR_G_V, SPR_G_E
    .word GTEXT_SPACE, GTEXT_SPACE, SPR_G_A, GTEXT_SPACE, SPR_G_F, SPR_G_I, SPR_G_R, SPR_G_E, GTEXT_END

; =============================================================================
; Engine includes — the sf_mode7_affine.inc link-partner order, plus the sprite
; + DMA engines spr / sf_frame_end require. NO HDMA-effect engines (the static
; affine path uses no HDMA), but mode7_engine.asm self-pulls the HDMA allocator,
; so hdma_alloc is included for its symbols.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "bright_fade_engine.asm"   ; sf_bright_fade / sf_bright_fade_tick
.include "collision_engine.asm"     ; col_box (AABB hit detection)
.include "tad_bridge.asm"           ; tad_* entry points the sf_audio macros call
                                    ;   (the TAD driver + song blob link as separate
                                    ;   objects, pulled in by the *_tad*.cfg build rule)

mode7_sin_lut:
    .include "mode7_sin_lut.inc"    ; defines sin_lut: (used by sincos)
.include "hdma_alloc.asm"           ; allocator symbols mode7_engine references
.include "mode7_math.asm"           ; sincos + smul16 (matrix trig + multiply)

.segment "RODATA"
.include "mode7_pv_ztable.inc"      ; pulled by mode7_hdma.asm's data refs

.segment "CODE"
.include "mode7_hdma.asm"           ; pv_* (referenced by mode7_engine paths)
.include "mode7_engine.asm"         ; mode7_set_static (+ self-pulls allocator)

; --- first-party assets (committed generator output; see assets/*.py) ---
.include "assets/saucer_palette.inc"
.include "assets/sprites.inc"

; --- the 32KB interleaved boss-map blob (bank 1 of the 96KB image) ---
.segment "BANK1"
; .incbin resolves relative to THIS file's own directory (not via -I), so the
; "assets/<basename>" form stays copy-safe — copy-to-adapt only changes the basename.
saucer_map:
    .incbin "assets/saucer_map.bin"
