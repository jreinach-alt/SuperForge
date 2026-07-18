; =============================================================================
; boss — Mode 7 animated boss battle (whole-plane affine boss + sprite combat)
; =============================================================================
; The genre rail for a "the boss IS the screen" fight: the boss is the Mode 7
; BG layer, so the hardware scales + rotates it for free via a single uniform
; affine matrix (sf_mode7_affine.inc). The player, the boss's attacks, and the
; HP HUD are SPRITES composited over it (the affine matrix never touches OBJ).
;
; This forks the racer/mode7_test spine (standard kit boot + the stock engine
; NMI — NO custom VBlank code) but uses the STATIC-affine Mode 7 path instead
; of the perspective floor:
;   - sf_boss_mode7_on installs Mode 7 with M7_PV_ACTIVE=1 (so the stock NMI
;     commits M7SEL/M7X/M7Y + scroll) but arms NO HDMA — a uniform matrix is
;     ~50 cycles/frame, not the ~10k-cycle perspective rebuild.
;   - sf_boss_matrix (first thing each frame, before active display) writes the
;     M7A-D matrix from (scale, angle) directly via mode7_set_static.
;   - the masked reveal uses sf_bright_fade (forced-blank swap), NOT a custom
;     NMI tilemap-swap — deliberately avoiding the Phase-14 silent-BRK region.
;
; MILESTONE 1 (this file's current scope): boot, upload the boss Mode 7 map,
; static affine display centered on the boss face, the player sprite, heartbeat.
; Battle structure (HP/phases/attacks/collision/win-lose) lands in later
; milestones.
;
; OBJ-OVER-MODE-7 (baked in): the Mode 7 map fills VRAM words $0000-$3FFF, so
; the OBJ name base moves to word $4000 (OBSEL=$62); the sprite CHR uploads
; there and OAM tile numbers stay 0.. relative to that base.
;
; Build:  make boss   (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_64k.cfg
;   ^ Linker-config sentinel (GAP-2): 64KB image, the 32KB boss-map blob fills
;     BANK1. The generic build/%.sfc rule reads this and links lorom_64k.cfg
;     instead of the default lorom.cfg; copy-to-adapt keeps the line, no Makefile
;     edit needed. (See docs/guides/adapting_a_rail.md.)
; =============================================================================

.p816
.smart

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

; --- the boss pivot (map pixels): map is 1024x1024, boss face centered ---
BOSS_CX = 512
BOSS_CY = 512

; --- the matrix maps screen->texel: BIGGER scale = boss looks SMALLER. The
;     boss face spans ~384 px; $0180 (1.5) fits it within the 256px view. ---
SCALE_NATIVE  = $0100           ; 1.0 (native texel:pixel)
INIT_SCALE    = $0180           ; 1.5 — whole boss visible at rest. NOTE: this
                                ;   also feeds REVEAL_STEP below (the reveal ramps
                                ;   REVEAL_SCALE down to INIT_SCALE), so keep
                                ;   INIT_SCALE < REVEAL_SCALE — a smaller value
                                ;   here = a bigger boss at rest AND a longer grow-in.
REVEAL_SCALE  = $0500           ; reveal start: boss is tiny/far (5.0 = far away)
DEATH_SCALE   = $0700           ; death end: boss recedes even farther

; --- player sprite placement (fixed-screen, low band; player slides L/R) ---
PLAYER_Y     = 184              ; fixed Y (player only strafes on X)
PLAYER_X0    = 120              ; spawn X (center-ish)
PLAYER_W     = 16               ; player box width (16x16 sprite)
PLAYER_H     = 16
PLAYER_XMIN  = 8                ; clamp range on screen (9-bit X, kept 0..255)
PLAYER_XMAX  = 232

; --- combat tuning ---
PLAYER_SPEED  = 3               ; px/frame strafe
SHOT_SPEED    = 6               ; px/frame upward (toward boss)
SHOT_W        = 8
SHOT_H        = 8
PROJ_W        = 8               ; enemy orb box
PROJ_H        = 8
IFRAME_LEN    = 30              ; player invuln frames after a hit
PLAYER_HP0    = 3
BOSS_HP0      = 240             ; long enough that a chasing player can lose
SHOT_DMG      = 5               ; HP per boss hit (~48 hits to kill)
SHOT_FIRE_GAP = 8               ; min frames between auto-fires (cadence)

; --- boss hitbox: the boss face fills most of the screen, so the hitbox is
;     WIDE — a player shot fired straight up from any column reaches the boss.
;     The boss's ATTACKS, by contrast, rain in a NARROW central column (see
;     ATK_SPAWN_X / ATK_SPREAD), so the player dodges by strafing to a side
;     lane while still able to hit the wide boss. ---
BOSS_HIT_X = 16
BOSS_HIT_Y = 40
BOSS_HIT_W = 224                ; spans most of the 256px screen width
BOSS_HIT_H = 96

; --- attack rain: a narrow central column the player strafes out of. Centered
;     on the player's spawn body-center (PLAYER_X0+4 = 124) and tight, so a
;     player that stays put is reliably hit (the deterministic LOSE path) while
;     strafing to a side lane dodges the whole column. ---
ATK_SPAWN_X = 124               ; column center (= PLAYER_X0 body center)
ATK_SPREAD  = 14                ; +/- horizontal spread (RNG, tight column)

; --- reveal/death pacing ---
REVEAL_FRAMES = 60              ; reveal scale ramp length
HOLD_FRAMES   = 45              ; pause at full size before the fight
FADE_FRAMES   = 32              ; bright-fade length (intro/death/lose)
RESULT_FRAMES = 90              ; how long the result screen holds

; --- per-frame reveal/death scale step (REVEAL_SCALE-INIT_SCALE)/REVEAL_FRAMES
REVEAL_STEP = (REVEAL_SCALE - INIT_SCALE) / REVEAL_FRAMES   ; ~$0015/frame down

; --- state machine indices (b_state) ---
ST_INTRO   = 0                  ; fade IN from black, then -> REVEAL
ST_REVEAL  = 1                  ; ramp scale REVEAL_SCALE -> INIT_SCALE (grow in)
ST_HOLD    = 2                  ; brief pause at full size
ST_FIGHT   = 3                  ; player control + attacks + hit detection
ST_DEATH   = 4                  ; boss recedes (scale up) + fade out (win)
ST_LOSE    = 5                  ; fade out (player died)
ST_RESULT  = 6                  ; result hold (win/lose), then RESET
ST_RESET   = 7                  ; re-init under forced blank -> REVEAL (loop)

; --- joypad masks (JOY1_CURRENT bit layout, matches the racer template) ---
JOY_RIGHT = $0100
JOY_LEFT  = $0200
JOY_A     = $0080
JOY_B     = $8000

; --- attack pool: 8-slot sf_pool + parallel arrays (preflight allocations) ---
ATK_N     = 8
ATK_ALIVE = $1800               ; alive[8]  (2 bytes/slot)
ATK_X     = $1810               ; x[8]
ATK_Y     = $1820               ; y[8]
ATK_VX    = $1830               ; vx[8] (signed)
ATK_VY    = $1840               ; vy[8] (signed)

; --- player-shot pool: 4 slots (the things that damage the boss). Distinct
;     arrays in the same $1800-$1DFF game-array region (pool contract). Drawn
;     in OAM slots 17-20 (past the HP-HUD band at 9-16). ---
SHOT_N     = 4
SHOT_ALIVE = $1850              ; alive[4]
SHOT_X     = $1858              ; x[4]
SHOT_Y     = $1860              ; y[4]
SHOT_OAM0  = 17                 ; first player-shot OAM slot

; --- game DP state (kit contract: $32-$5F) ---
b_scale     = $32               ; current matrix scale (1.7.8)
b_angle     = $34               ; current rotation angle (low byte = 0..255)
b_cx        = $36               ; matrix center X (map px)
b_cy        = $38               ; matrix center Y (map px)
b_state     = $3A               ; state machine index (ST_*)
b_timer     = $3C               ; per-state frame timer (counts down)
b_hp        = $3E               ; boss HP (0..BOSS_HP0)
b_phase     = $40               ; boss phase index (0..2; higher = faster/denser)
b_vuln      = $42               ; boss vulnerability flag (1 = shots can damage)
p_x         = $44               ; player x (16-bit, low byte is the OAM X)
; $46: free (player Y is the constant PLAYER_Y; no p_y variable)
p_hp        = $48               ; player HP (0..PLAYER_HP0)
p_iframe    = $4A               ; player invuln frames remaining
spawn_timer = $4C               ; boss attack spawn cadence countdown
rng         = $4E               ; xorshift RNG state (16-bit)
fire_timer  = $50               ; player auto-fire cadence countdown
b_result    = $52               ; result flag: 1 = win, 2 = lose (for HUD/tests)
b_anglespd  = $54               ; per-frame rotation speed (phase-driven)
su_i        = $56               ; shots_update loop index (byte offset)
au_i        = $58               ; attacks_update loop index (byte offset)
hud_i       = $5A               ; HP-HUD draw loop index
hud_x       = $5C               ; HP-HUD draw x cursor
hud_lit     = $5E               ; HP-HUD lit-segment threshold

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y + scroll commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init

    ; --- STABLE OAM ordering: the draw assigns fixed slots (0 player, 1-8
    ;     attacks, 9-16 HP HUD, 17-20 shots) and the tests read those slots by
    ;     identity, so disable the engine's default Y-sort (mode 2 = stable,
    ;     no remap — sprites keep their call order). ---
    sep #$20
    .a8
    lda #$02
    sta SPR_ORDER_MODE
    rep #$30
    .a16
    .i16

    ; --- boss Mode 7 map upload (under the coldstart forced blank) ---
    sf_mode7_load_map boss_map, #$8000

    ; --- boss palette -> CGRAM 0.. (index 0 = dark arena backdrop) ---
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    ldx #$0000
bpal_loop:
    .a8
    lda f:boss_pal, x
    sta $2122                   ; CGDATA (low then high byte, auto-pair)
    inx
    cpx #(BOSS_PAL_COUNT * 2)
    bne bpal_loop
    rep #$30
    .a16
    .i16

    ; --- sprite CHR + palette out of the Mode 7 map's VRAM ---
    ; Map owns VRAM words $0000-$3FFF, so OBJ name base = word $4000:
    ; OBSEL=$62 (base %010 x $2000 words, 16x16/32x32 size pair). tile 1024 IS
    ; word $4000, so OAM tile numbers stay 0.. relative to the OBSEL base.
    sf_load_obj_pal 0, sprite_pal
    sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes
    sep #$20
    .a8
    lda #$62
    sta $2101                   ; OBSEL: name base word $4000, 16x16/32x32
    rep #$30
    .a16
    .i16

    ; --- Mode 7 static affine on + center on the boss ---
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

; =============================================================================
; The frame spine: matrix first (consistent frame), then the per-state update,
; then the per-state draw. The state machine drives b_scale/b_angle/combat; the
; draw is shared. Stable OAM slots (preflight map):
;   0      player ship
;   1-8    attack projectiles (draw-every-frame, dead parked at y=$F0)
;   9-16   boss HP HUD segments
; =============================================================================
game_loop:
    .a16
    sf_frame_begin              ; wait for the NMI; latch input

    ; --- the matrix FIRST, before active display (one consistent frame) ---
    sf_boss_matrix b_scale, b_angle

    jsr state_update            ; per-state logic (reveal ramp, combat, death...)
    sf_bright_fade_tick         ; advance any armed brightness fade (masked swaps)

    jsr draw_frame              ; player + attack pool + HP HUD into stable OAM

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
    lda #30
    sta spawn_timer
    stz fire_timer
    stz b_result
    lda #$ACE1                  ; non-zero xorshift seed
    sta rng
    ; clear the attack pool + the player-shot pool (all slots free)
    sf_pool_init ATK_ALIVE, ATK_N
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
    sta b_vuln                  ; boss becomes vulnerable in the fight
su_hold_ret:
    .a16
    rts

; --- FIGHT: handed to the combat routine (M4/M5). ---
su_fight:
    .a16
    jsr fight_update
    rts

; --- DEATH: boss recedes (scale UP) + fade to black; then RESULT(win). ---
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
; fight_update — combat: player control, attack pool, player shots, col_box
; hit detection (M4) + phase pacing + win/lose (M5). A16/I16 throughout.
; WIDTH-RISK: A16/I16 entry/exit. The jsr'd helpers all keep A16/I16; col_box
; and the sf_pool macros assert/return A16/I16. No width toggles in this body.
; =============================================================================
fight_update:
    .a16
    .i16
    jsr player_move             ; LEFT/RIGHT strafe + clamp
    jsr player_fire             ; auto/A-fire a SPR_SHOT upward
    jsr shots_update            ; advance shots; shot-vs-boss col_box
    jsr boss_spawn              ; cadence spawn of SPR_PROJECTILE attacks
    jsr attacks_update          ; advance attacks; attack-vs-player col_box
    jsr boss_phase              ; HP-driven phase + rotation speed
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
    ; boss dead -> DEATH (recede + fade), win
    stz b_vuln
    lda #ST_DEATH
    sta b_state
    lda #REVEAL_FRAMES
    sta b_timer
    rts
fu_check_lose:
    .a16
    lda p_hp
    bne fu_alive
    ; player dead -> arm fade-out, LOSE
    sf_bright_fade #0, #FADE_FRAMES
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
; boss_spawn — on the spawn cadence (phase-scaled), launch a SPR_PROJECTILE from
; near the boss face toward the player, with an RNG horizontal spread.
; WIDTH-RISK: A16/I16 entry/exit. rng_next keeps A16/I16.
; =============================================================================
boss_spawn:
    .a16
    .i16
    lda spawn_timer
    beq bs_fire
    dec a
    sta spawn_timer
    rts
bs_fire:
    .a16
    sf_pool_spawn ATK_ALIVE, ATK_N
    cmp #$FFFF
    beq bs_reload               ; pool full -> just reset the timer
    txy                         ; keep the claimed slot offset in Y across rng_next
    ; --- spawn X: a NARROW central column (ATK_SPAWN_X +/- ATK_SPREAD via RNG).
    ;     The rain stays over the boss face; the player strafes to a side lane
    ;     to dodge (the wide boss hitbox still lets side-lane shots connect). ---
    jsr rng_next                ; A = rng (16-bit); Y still = slot offset
    and #$001F                  ; 0..31
    sec
    sbc #16                     ; -16..+15 (tight column, ~ATK_SPREAD wide)
    clc
    adc #(ATK_SPAWN_X)          ; centered on the column
    sta ATK_X, y
    lda #BOSS_HIT_Y             ; spawn from the face band
    sta ATK_Y, y
    ; --- VX = small RNG drift (-1..+1); VY = +3 down (toward the player band) ---
    jsr rng_next
    and #$0003
    sec
    sbc #1                      ; -1..+2
    cmp #2
    bne bs_vx_store
    lda #0                      ; map +2 -> 0 (mostly straight down)
bs_vx_store:
    .a16
    sta ATK_VX, y
    lda #3
    sta ATK_VY, y
    tyx                         ; restore X = slot offset
bs_reload:
    .a16
    ; cadence by phase: phase 0 = 36 fr, phase 1 = 26, phase 2 = 18
    lda b_phase
    cmp #2
    bcs bs_p2
    cmp #1
    bcs bs_p1
    lda #36
    bra bs_set
bs_p1:
    .a16
    lda #26
    bra bs_set
bs_p2:
    .a16
    lda #18
bs_set:
    .a16
    sta spawn_timer
    rts

; =============================================================================
; attacks_update — advance every live attack by (vx,vy); cull off-screen; test
; each vs the player box -> drop p_hp (if not in iframes) + set iframes + free.
; WIDTH-RISK: A16/I16 entry/exit. col_box keeps A16/I16; X reloaded from au_i.
; =============================================================================
attacks_update:
    .a16
    .i16
    stz au_i
au_loop:
    .a16
    ldx au_i
    lda ATK_ALIVE, x
    beq au_next
    ; integrate position
    lda ATK_X, x
    clc
    adc ATK_VX, x
    sta ATK_X, x
    lda ATK_Y, x
    clc
    adc ATK_VY, x
    sta ATK_Y, x
    ; cull when past the bottom of the play area (y >= 224)
    cmp #224
    bcs au_kill
    ; --- attack box vs player box ---
    ldx au_i
    col_box ATK_X, ATK_Y, #PROJ_W, #PROJ_H, p_x, #PLAYER_Y, #PLAYER_W, #PLAYER_H
    cmp #$0001
    bne au_next
    ; overlap! always free the attack on contact
    ldx au_i
    sf_pool_kill_x ATK_ALIVE
    ; damage only if not currently invulnerable
    lda p_iframe
    bne au_next
    lda p_hp
    beq au_next                 ; already 0
    dec a
    sta p_hp
    lda #IFRAME_LEN
    sta p_iframe
    bra au_next
au_kill:
    .a16
    ldx au_i
    sf_pool_kill_x ATK_ALIVE
au_next:
    .a16
    lda au_i
    clc
    adc #2
    sta au_i
    cmp #(2 * ATK_N)
    bne au_loop
    rts

; =============================================================================
; rng_next — 16-bit xorshift; returns the new state in A. A16/I16 entry/exit.
; WIDTH-RISK: A16/I16 (no toggles). x ^= x<<7; x ^= x>>9; x ^= x<<8 (8-bit-ish
; xorshift adapted to 16 bits — good enough for spawn spread).
; =============================================================================
rng_next:
    .a16
    .i16
    lda rng
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; <<7
    eor rng
    sta rng
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr                         ; >>9
    eor rng
    sta rng
    asl
    asl
    asl
    asl
    asl
    asl
    asl
    asl                         ; <<8
    eor rng
    sta rng
    rts

; =============================================================================
; boss_phase — derive b_phase from b_hp (thresholds) and spin the boss faster
; in later phases (rotation = atmosphere + difficulty read). A16/I16.
; Phase thresholds (BOSS_HP0=240, /3): hp>160 -> 0, 80<hp<=160 -> 1, hp<=80 -> 2.
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
    ; phase 2: hp <= 80
    lda #2
    sta b_phase
    lda #3
    bra bp_set_spd
bp_p1:
    .a16
    lda #1
    sta b_phase
    lda #2
    bra bp_set_spd
bp_p0:
    .a16
    stz b_phase
    lda #1
bp_set_spd:
    .a16
    sta b_anglespd
    ; advance rotation by the phase speed (the boss keeps turning in the fight)
    lda b_angle
    clc
    adc b_anglespd
    and #$00FF
    sta b_angle
    rts

; =============================================================================
; draw_frame — shared per-frame OAM draw (stable slots; M4/M5 flesh out attacks
; + HP HUD). M3: player at slot 0, all other slots parked off-screen.
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
    bra df_attacks
df_park_player:
    .a16
    spr #SPR_PLAYER_T0, #0, #$00F0, #$0080, #2   ; parked off-screen (y=$F0)
    bra df_attacks

df_attacks:
    .a16
    ; --- slots 1-8 = attack pool (draw EVERY slot; dead parked at y=$F0) ---
    stz au_i
df_atk_loop:
    .a16
    ldx au_i
    lda ATK_ALIVE, x
    beq df_atk_park
    ldx au_i
    spr #SPR_PROJECTILE, ATK_X, ATK_Y, #$0000, #2   ; 8x8 small enemy orb
    bra df_atk_next
df_atk_park:
    .a16
    spr #SPR_PROJECTILE, #0, #$00F0, #$0000, #2
df_atk_next:
    .a16
    lda au_i
    clc
    adc #2
    sta au_i
    cmp #(2 * ATK_N)
    bne df_atk_loop

    ; --- slots 9-16 = boss HP HUD (M5 fills these; park for now to keep the
    ;     OAM slot map stable so player shots land at slots 17-20). ---
    jsr draw_hp_hud

    ; --- slots 17-20 = player shots (draw EVERY slot; dead parked) ---
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
    rts

; =============================================================================
; draw_hp_hud — boss HP bar as a row of 8 segment sprites (OAM slots 9-16).
; Each segment covers BOSS_HP0/8 HP; segment i is LIT (SPR_HP_LIT) while
; b_hp > i*(BOSS_HP0/8), else DIM (SPR_HP_DIM). Drawn at a fixed top-screen row
; over the boss BG (sprite-over-BG composition). Always draws all 8 slots so the
; OAM slot map stays stable (shots land at 17-20).
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
; Engine includes — the sf_mode7_affine.inc link-partner order, plus the sprite
; + DMA engines spr / sf_frame_end require. NO HDMA-effect engines (the static
; affine path uses no HDMA), but mode7_engine.asm self-pulls the HDMA allocator,
; so hdma_alloc is included for its symbols.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "bright_fade_engine.asm"   ; sf_bright_fade / sf_bright_fade_tick
.include "collision_engine.asm"     ; col_box (M4 hit detection)

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
.include "assets/boss_palette.inc"
.include "assets/sprites.inc"

; --- the 32KB interleaved boss-map blob (bank 1 of the 64KB image) ---
.segment "BANK1"
; .incbin (GAP-3): resolved relative to THIS file's dir, not via -I — so the
; "assets/<basename>" form is copy-safe (copy-to-adapt only changes the basename).
boss_map:
    .incbin "assets/boss_map.bin"
