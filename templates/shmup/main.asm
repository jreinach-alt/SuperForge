; =============================================================================
; shmup — vertical-scrolling shooter rail (REAL converted CC0 art)
; =============================================================================
; The genre rail for vertical shmups, and the proof-of-pipeline template: every
; visible asset came through tools/png2snes.py from the packs in
; examples/itch_cc0/ (see assets/*.inc headers for the exact commands):
;   - ship    = dungeonSprites fHero idle (24x24 P-mode -> re-centered 16x16)
;   - enemies = dungeonSprites ghost (16x16, own OBJ palette)
;   - terrain = Four Seasons tileset spring patch (8x6 metacells, 1 BG palette,
;               mset-ready map words)
; Composes: sf_pool (bullets + enemies), sf_autoscroll_v (terrain drift),
; col_box (bullet hits + ship damage), sf_anim (frame cycling), sf_audio (TAD
; music + SFX), sf_text (HUD), the OBJ/BG blob loaders.
;
; Controls:
;   d-pad   move the ship (clamped to the playfield)
;   A       fire (rising edge — one bullet per press)
;   START   on GAME OVER, begin a fresh game
;
; The game: bullets fly up at 4 px/f; ghosts spawn on a timer at table-driven
; columns and drift down at 1 px/f. A bullet hit bursts both and scores a point.
; A ghost that touches the ship costs one of 3 lives — the ship respawns at spawn
; and blinks through its i-frames; at zero lives it is GAME OVER (the world
; freezes until START restarts). Music plays throughout; firing and kills blip.
;
; STABLE OAM SLOTS (the sf_pool draw idiom): every pool slot is drawn every
; frame — live actors at their position, dead slots parked at y=$F0 — so OAM
; slot k always belongs to the same actor: 0 = ship, 1-6 = bullets, 7-10 =
; ghosts. Tests (and your debugging) can identify actors by OAM slot.
;
; File layout (top to bottom; the major === section banners):
;   INIT         — RESET: one-time uploads, PPU, game state, then boot the loop
;   MAIN LOOP    — game_loop, the once-per-frame heartbeat (read this first)
;   SUBROUTINES  — draw_lives (HUD helper) + restart_game (soft restart)
;   DATA         — strings, spawn/island tables, the bullet tile, converted art
; game_loop is the frame heartbeat; start reading there to see the whole shape.
;
; Tuning (override by defining before .include, or just edit):
;   SHIP_SPEED   px/frame d-pad movement (default 2)
;   BULLET_SPEED px/frame upward        (default 4)
;   ENEMY_SPEED  px/frame downward      (default 1)
;   SPAWN_PERIOD frames between spawns  (default 48)
;   START_LIVES  ships before GAME OVER (default 3)
;   IFRAMES      invulnerable frames after a hit (default 90)
;
; Done-condition (emulator-verifiable):
;   - boots; terrain + ship render (screenshot pixels match the converted art)
;   - terrain autoscrolls DOWN; ship moves in all four directions, clamped
;   - A spawns a bullet that travels up and dies at the top; music + SFX audible
;   - ghosts spawn, descend, die to bullets; SCORE counts up on the HUD
;   - a ghost touching the ship costs a life (blink + respawn); 0 lives = GAME OVER
;
; Build:  make shmup        (the generic templates rule reads the LDCFG sentinel below)
; LDCFG: lorom_tad.cfg
;   ^ Linker-config sentinel: the TAD-audio link shape (data banks for the music
;     + SFX). The generic build/%.sfc rule reads this; a *_tad*.cfg name also
;     links the TAD driver objects + adds the audio include path, so no Makefile
;     edit is needed. (Was the default lorom.cfg — this rail fits in one bank; the
;     swap is purely to gain the audio banks.)
; =============================================================================

.p816
.smart

; ROM header title (opt-in; see infrastructure/rom_template/header.inc)
.define SF_HDR_TITLE "ASTRO BARRAGE"
SF_HDR_TITLE_SET = 1
.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_load_obj_chr/pal, sf_load_obj_tile, sf_obj_color
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_collision.inc"     ; col_box
.include "sf_bg.inc"            ; gfxmode, mset, sf_autoscroll_v, BG loaders
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_pool.inc"          ; sf_pool_init/spawn/kill_x/count
.include "sf_anim.inc"          ; sf_anim_step / sf_anim_tile (frame cycling)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD driver ca65 API (the vendored audio driver)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids for the shipped song set
.include "sf_audio.inc"         ; sf_audio_init / sf_audio_tick / sf_music / sf_sfx

; --- tuning (assemble-time) ---
.ifndef SHIP_SPEED
SHIP_SPEED = 2
.endif
.ifndef BULLET_SPEED
BULLET_SPEED = 4
.endif
.ifndef ENEMY_SPEED
ENEMY_SPEED = 1
.endif
.ifndef SPAWN_PERIOD
SPAWN_PERIOD = 48
.endif
.assert BULLET_SPEED <= 8, error, "BULLET_SPEED > 8 can tunnel past a 16px enemy between frames"
.assert SHIP_SPEED <= 8, error, "SHIP_SPEED > 8 breaks the clamps: PX-SHIP_SPEED can wrap below 0 (unsigned), sailing past the cmp bound"

; --- player-damage tuning ---
.ifndef START_LIVES
START_LIVES  = 3                ; ships before GAME OVER
.endif
.ifndef IFRAMES
IFRAMES      = 90               ; invulnerable frames after a hit (also the blink window)
.endif
BLINK_PHASE  = $04              ; blink mask on HURTLOCK: hidden while (HURTLOCK & $04) -> ~4 on / 4 off
SHIP_SPAWN_X = 120              ; ship spawn + respawn column (16px ship, playfield centre-ish)
SHIP_SPAWN_Y = 180             ; ship spawn + respawn row (low, clear of the ghost spawn line)
ANIM_RATE    = 6                ; game frames per animation step (hero + ghost share the clock)

; --- night-sky backdrop (CGRAM color 0, BGR15) ---
NIGHT_SKY    = $1C61            ; deep midnight blue instead of void black (sprites
                               ;   still read clearly; it is far darker than the terrain)

; --- OBJ VRAM layout (loaders assert the 16-alignment) ---
HERO_BASE   = 0                 ; tiles 0-31   (fHero, 2 VRAM rows)
GHOST_BASE  = 32                ; tiles 32-63  (ghost, 2 VRAM rows)
BULLET_TILE = 64                ; one 8x8 tile

; --- DP state ($30-$5F, the template convention; API block owns $60+) ---
PX       = $32                  ; ship x (pixels, top-left of 16x16)
PY       = $34                  ; ship y
SCORE    = $36
SPAWN_T  = $38                  ; frames until next ghost
SPAWN_IX = $3A                  ; spawn-column table cursor (0..7)
SCRL     = $3C                  ; autoscroll counter
BOFF     = $3E                  ; bullet loop offset (byte offset into arrays)
EOFF     = $40                  ; enemy loop offset
BX       = $42                  ; current bullet x/y (collision + draw scratch)
BY       = $44
EX       = $46                  ; current enemy x/y
EY       = $48
TT       = $4A                  ; tilemap-build scratch: map word
TX       = $4C                  ;   patch cell x (0..7)
TY       = $4E                  ;   patch cell y (0..5)
ISL      = $50                  ;   island table cursor (byte offset)
SDIRTY   = $52                  ; 1 = score/lives changed, reprint the HUD
HURTLOCK = $54                  ; i-frames after a ghost hit (invuln + blink countdown)
ATICK    = $56                  ; shared animation clock: frame-rate divider
AFRAME   = $58                  ;   ...and the current step index (0..7)

; --- pools (the $1800-$1DFF game-array region — see sf_pool.inc) ---
BULLET_N  = 6
BUL_ALIVE = $1800               ; alive[6]
BUL_X     = $1810               ; x[6]
BUL_Y     = $1820               ; y[6]
ENEMY_N   = 4
ENE_ALIVE = $1830               ; alive[4]
ENE_X     = $1840               ; x[4]
ENE_Y     = $1850               ; y[4]
; game state (rest of the $1800-$1DFF region; clear of the pools above and of
; TAD's BSS at $1DE0-$1DFF)
LIVES     = $1858               ; ships remaining (START_LIVES down to 0)
GAMEOVER  = $185A               ; 1 = terminal state: world frozen, START restarts
LIVES_STR = $185C               ; 2-byte HUD buffer: LIVES as one ASCII digit + NUL

.segment "CODE"

; =============================================================================
; INIT — interrupt vectors + one-time boot (RESET: uploads, PPU, game state)
; =============================================================================
NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    sf_audio_init               ; ONCE, at boot (S-SMP still in IPL, NMI not yet on)

    ; --- converted-art + font uploads (under the coldstart forced blank) ---
    sf_load_bg_chr 0, terrain_chr, terrain_chr_bytes
    sf_load_bg_pals 0, terrain_pal, terrain_pal_count
    sf_text_init                ; font -> BG3 tiles (and white text colour)
    sf_load_obj_chr HERO_BASE,  hero_chr,  hero_chr_bytes
    sf_load_obj_chr GHOST_BASE, ghost_chr, ghost_chr_bytes
    sf_load_obj_pal 0, hero_pal
    sf_load_obj_pal 1, ghost_pal
    sf_load_obj_tile BULLET_TILE, bullet_tile
    sf_obj_color 2, 1, $03FF    ; bullet = yellow, OBJ palette 2
    sf_bg_color 0, 0, NIGHT_SKY ; backdrop (CGRAM 0): a night sky, not a black void

    jsr init_ppu                ; engine PPU defaults (OBSEL $00: 8x8/16x16)
    gfxmode #1                  ; enable BG1+BG3 (zeros the shadow tilemaps)

    ; --- scatter terrain ISLANDS over the black backdrop ---
    ; The converted 8x6-cell patch is stamped at staggered origins (the
    ; islands table); everything else stays tile 0 = transparent over the
    ; black backdrop, so sprites read clearly against the sky (a busy
    ; full-screen tilemap buries the gameplay). The 32-high map wraps as it
    ; autoscrolls, so the island field loops seamlessly.
    rep #$30
    .a16                        ; 16-bit A/X/Y here. The 65816's register width is set
                                ;   at RUNTIME by sep/rep; the .a16/.i16 directives tell
    .i16                        ;   the assembler which width the CPU is in so it encodes
                                ;   each op right (the width linter checks the match).
    stz ISL
isl_loop:
    stz TY
isl_row:
    stz TX
isl_col:
    lda TY
    asl a
    asl a
    asl a                       ; py * 8
    clc
    adc TX
    asl a                       ; word index -> byte offset
    tax
    lda f:terrain_map, x
    sta TT
    ; dest cell = island origin + patch cell, wrapped into the 32x32 map
    ldx ISL
    lda f:island_xs, x
    clc
    adc TX
    and #$001F
    sta BX                      ; (collision scratch doubles as build scratch)
    lda f:island_ys, x
    clc
    adc TY
    and #$001F
    sta BY
    mset #1, BX, BY, TT
    lda TX
    inc a
    sta TX
    cmp #8
    bne isl_col
    lda TY
    inc a
    sta TY
    cmp #6
    bne isl_row
    lda ISL
    inc a
    inc a
    sta ISL
    cmp #(2 * 5)                ; 5 islands
    bne isl_loop

    ; --- HUD ---
    print score_str, #8, #8
    sf_print_u16 SCORE, #56, #8
    print lives_str, #152, #8

    ; --- game state ---
    sf_pool_init BUL_ALIVE, BULLET_N
    sf_pool_init ENE_ALIVE, ENEMY_N
    rep #$30
    .a16
    .i16
    lda #SHIP_SPAWN_X
    sta PX
    lda #SHIP_SPAWN_Y
    sta PY
    stz SCORE
    stz SCRL
    stz SPAWN_IX
    stz SDIRTY
    lda #SPAWN_PERIOD
    sta SPAWN_T
    lda #START_LIVES
    sta LIVES
    stz HURTLOCK
    stz GAMEOVER
    stz ATICK
    stz AFRAME
    jsr draw_lives              ; paint the initial LIVES digit

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMITIMEN: enable VBlank NMI ($80) + auto-joypad read
                                ;   ($01) — the frame heartbeat starts here
    rep #$30
    .a16
    .i16

    sf_music #Song::gimo_297    ; boot the in-game track (streams over the ticks)

; =============================================================================
; MAIN LOOP — the once-per-frame heartbeat (input -> update -> draw)
; =============================================================================
game_loop:
    sf_frame_begin
    sf_audio_tick               ; drive the async song load + SFX queue, every frame

    lda GAMEOVER
    beq gs_play                 ; playing -> run the update block
    jmp go_draw                 ; GAME OVER: freeze the world; only DRAW + restart run
gs_play:
    .a16

    sf_anim_step ATICK, AFRAME, #ANIM_RATE, #hero_anim_idle_len  ; shared frame clock

    ; ---------------- input: move the ship (clamped to the playfield) -------
    btn #BTN_RIGHT
    beq mv_no_right
    rep #$20
    .a16
    lda PX
    clc
    adc #SHIP_SPEED
    cmp #224                    ; right clamp: 256px screen - 16px ship - 16px inset
    bcc mv_store_x_r            ;   (the 256px active width, not a cropped 240)
    lda #224
mv_store_x_r:
    sta PX
mv_no_right:
    .a16
    btn #BTN_LEFT
    beq mv_no_left
    rep #$20
    .a16
    lda PX
    sec
    sbc #SHIP_SPEED
    cmp #8                      ; left clamp — safe because PX >= 8 always and
    bcs mv_store_x_l            ;   SHIP_SPEED <= 8 (asserted), so no u16 wrap
    lda #8
mv_store_x_l:
    sta PX
mv_no_left:
    .a16
    btn #BTN_DOWN
    beq mv_no_down
    rep #$20
    .a16
    lda PY
    clc
    adc #SHIP_SPEED
    cmp #200                    ; bottom clamp: 224px screen - 16px ship - 8px inset
    bcc mv_store_y_d
    lda #200
mv_store_y_d:
    sta PY
mv_no_down:
    .a16
    btn #BTN_UP
    beq mv_no_up
    rep #$20
    .a16
    lda PY
    sec
    sbc #SHIP_SPEED
    cmp #32                     ; keep clear of the HUD row
    bcs mv_store_y_u
    lda #32
mv_store_y_u:
    sta PY
mv_no_up:
    .a16

    ; ---------------- fire: A (rising edge) spawns a bullet -----------------
    btnp #BTN_A
    beq fire_done
    sf_pool_spawn BUL_ALIVE, BULLET_N
    bmi fire_done               ; pool full -> the press is swallowed
    lda PX
    clc
    adc #4                      ; centre the 8px bullet on the 16px ship
    sta BUL_X, x
    lda PY
    sec
    sbc #8                      ; muzzle: just above the ship
    sta BUL_Y, x
    sf_sfx #SFX::fire_arrow     ; muzzle blip — after the slot write (sf_sfx clobbers X)
fire_done:
    .a16

    ; ---------------- bullets: fly up, die at the top ------------------------
    ; (pure indexed ops — X survives the whole loop; see sf_pool.inc idiom)
    ldx #$0000
bul_loop:
    lda BUL_ALIVE, x
    beq bul_next
    lda BUL_Y, x
    sec
    sbc #BULLET_SPEED
    sta BUL_Y, x
    cmp #16                     ; Y above 16 = up behind the HUD row -> expire
    bcs bul_next
    sf_pool_kill_x BUL_ALIVE    ; off the top
bul_next:
    inx
    inx
    cpx #(2 * BULLET_N)
    bne bul_loop

    ; ---------------- spawner: a ghost every SPAWN_PERIOD frames ------------
    lda SPAWN_T
    dec a
    sta SPAWN_T
    bne spawn_done
    lda #SPAWN_PERIOD
    sta SPAWN_T
    sf_pool_spawn ENE_ALIVE, ENEMY_N
    bmi spawn_done              ; wave full -> skip this beat
    stx EOFF                    ; sf_pool_spawn clobbers nothing else we hold
    lda SPAWN_IX
    asl a
    tax
    lda f:spawn_xs, x
    ldx EOFF
    sta ENE_X, x
    lda #24                     ; spawn just below the HUD (row 3): a small on-screen
    sta ENE_Y, x                ;   pop-in, not an off-top slide-in — keep it thin
    lda SPAWN_IX
    inc a
    and #$0007                  ; cycle the 8-entry column table
    sta SPAWN_IX
spawn_done:
    .a16

    ; ---------------- enemies: drift down, despawn past the bottom ----------
    ldx #$0000
ene_loop:
    lda ENE_ALIVE, x
    beq ene_next
    lda ENE_Y, x
    clc
    adc #ENEMY_SPEED
    sta ENE_Y, x
    cmp #208                    ; Y past 208 = fully below the 224px screen (16px ghost)
    bcc ene_next
    sf_pool_kill_x ENE_ALIVE    ; escaped off the bottom
ene_next:
    inx
    inx
    cpx #(2 * ENEMY_N)
    bne ene_loop

    ; ---------------- collisions: each live bullet vs each live ghost -------
    stz BOFF
col_b_loop:
    ldx BOFF
    lda BUL_ALIVE, x
    bne col_b_live
    jmp col_b_next
col_b_live:
    .a16
    lda BUL_X, x
    sta BX
    lda BUL_Y, x
    sta BY
    stz EOFF
col_e_loop:
    ldx EOFF
    lda ENE_ALIVE, x
    bne col_e_live
    jmp col_e_next
col_e_live:
    .a16
    lda ENE_X, x
    sta EX
    lda ENE_Y, x
    sta EY
    col_box BX, BY, #8, #8,  EX, EY, #16, #16
    bne col_hit
    jmp col_e_next
col_hit:
    .a16
    ldx BOFF
    sf_pool_kill_x BUL_ALIVE
    ldx EOFF
    sf_pool_kill_x ENE_ALIVE
    lda SCORE
    inc a
    sta SCORE
    lda #1
    sta SDIRTY
    sf_sfx #SFX::noise          ; ghost explodes (kill feedback)
    jmp col_b_next              ; this bullet is spent
col_e_next:
    .a16
    lda EOFF
    inc a
    inc a
    sta EOFF
    cmp #(2 * ENEMY_N)
    bcs col_b_next
    jmp col_e_loop
col_b_next:
    .a16
    lda BOFF
    inc a
    inc a
    sta BOFF
    cmp #(2 * BULLET_N)
    bcs col_done
    jmp col_b_loop
col_done:
    .a16

    ; ---------------- player damage: a ghost touching the ship costs a life --
    ; i-frames gate the hit and drive the blink; on contact respawn at spawn,
    ; burst the ghost, dock a life, and enter GAME OVER at zero ships.
    lda HURTLOCK
    beq dmg_check
    dec a
    sta HURTLOCK
    jmp dmg_done                ; still invulnerable this frame
dmg_check:
    .a16
    stz EOFF
dmg_e_loop:
    ldx EOFF
    lda ENE_ALIVE, x
    beq dmg_e_next
    lda ENE_X, x
    sta EX
    lda ENE_Y, x
    sta EY
    col_box PX, PY, #16, #16, EX, EY, #16, #16
    bne dmg_hit
dmg_e_next:
    .a16
    lda EOFF
    inc a
    inc a
    sta EOFF
    cmp #(2 * ENEMY_N)
    bcc dmg_e_loop
    jmp dmg_done
dmg_hit:
    .a16
    ldx EOFF
    sf_pool_kill_x ENE_ALIVE    ; the colliding ghost bursts too
    sf_sfx #SFX::player_hurt
    lda #SHIP_SPAWN_X
    sta PX
    lda #SHIP_SPAWN_Y
    sta PY
    lda #IFRAMES
    sta HURTLOCK                ; invuln + blink window
    lda LIVES
    beq dmg_done                ; already empty (guarded; the loop gate normally
    dec a                       ;   prevents any hit once GAME OVER latches)
    sta LIVES
    lda #$0001
    sta SDIRTY                  ; reprint the LIVES digit
    lda LIVES
    bne dmg_done                ; ships left -> keep flying
    lda #$0001
    sta GAMEOVER                ; out of ships -> terminal state
    stz HURTLOCK                ; draw the ship solid on the frozen screen
    print gameover_str, #96, #96
    print restart_str, #88, #112
dmg_done:
    .a16

    ; ---------------- world: terrain drifts down (skipped while GAME OVER) ---
    sf_autoscroll_v #1, SCRL, #1

go_draw:
    .a16
    ; ---------------- HUD: reprint SCORE + LIVES only when they changed ------
    lda SDIRTY
    beq hud_done
    stz SDIRTY
    sf_print_u16 SCORE, #56, #8
    jsr draw_lives
hud_done:
    .a16

    ; ---------------- draw: every slot every frame (stable OAM slots) -------
    spr_clear
    ; slot 0: the ship — animated idle frame, blinking while in i-frames
    lda HURTLOCK
    beq draw_ship               ; vulnerable -> always draw
    and #BLINK_PHASE
    bne ship_hidden             ; blink-off phase -> leave the ship parked (spr_clear did)
draw_ship:
    .a16
    sf_anim_tile hero_anim_idle, AFRAME
    clc
    adc #HERO_BASE
    sta BX                      ; tile scratch (collision/draw scratch, free here)
    spr BX, PX, PY, #$80, #2
ship_hidden:
    .a16

    ; slots 1-6: bullets (8x8 small, palette 2); dead slots park at y=$F0
    stz BOFF
draw_b_loop:
    ldx BOFF
    lda BUL_ALIVE, x
    beq draw_b_dead
    lda BUL_X, x
    sta BX
    lda BUL_Y, x
    sta BY
    bra draw_b_put
draw_b_dead:
    .a16
    stz BX
    lda #$00F0
    sta BY
draw_b_put:
    .a16
    spr #BULLET_TILE, BX, BY, #$04, #2
    lda BOFF
    inc a
    inc a
    sta BOFF
    cmp #(2 * BULLET_N)
    bcs draw_b_done
    jmp draw_b_loop
draw_b_done:
    .a16

    ; slots 7-10: ghosts (16x16 large, palette 1); dead slots park at y=$F0.
    ; All live ghosts share this frame's animation step (one table lookup).
    sf_anim_tile ghost_anim_idleWalkRun, AFRAME
    clc
    adc #GHOST_BASE
    sta TT                      ; ghost tile this frame (map-build scratch, free here)
    stz EOFF
draw_e_loop:
    ldx EOFF
    lda ENE_ALIVE, x
    beq draw_e_dead
    lda ENE_X, x
    sta EX
    lda ENE_Y, x
    sta EY
    bra draw_e_put
draw_e_dead:
    .a16
    stz EX
    lda #$00F0
    sta EY
draw_e_put:
    .a16
    spr TT, EX, EY, #$82, #2
    lda EOFF
    inc a
    inc a
    sta EOFF
    cmp #(2 * ENEMY_N)
    bcs draw_e_done
    jmp draw_e_loop
draw_e_done:
    .a16

    ; ---------------- GAME OVER: START begins a fresh game ------------------
    lda GAMEOVER
    beq frame_tail
    btnp #BTN_START
    beq frame_tail
    jsr restart_game
frame_tail:
    .a16
    sf_frame_end
    jmp game_loop

; =============================================================================
; SUBROUTINES — HUD helper + the soft restart
; =============================================================================
; draw_lives — paint LIVES (0..3) as one ASCII digit at the right of the HUD row.
draw_lives:
    rep #$30
    .a16
    .i16
    lda LIVES
    clc
    adc #'0'
    and #$00FF
    sta LIVES_STR               ; digit in the low byte, 0 (NUL) high -> 1-char string
    print LIVES_STR, #200, #8
    rts

; restart_game — soft restart to a fresh game after GAME OVER. Never re-runs
; sf_coldstart or sf_audio_init (the S-SMP is live, past IPL); it rebuilds only
; the game's own state, and the music keeps playing across the restart.
restart_game:
    rep #$30
    .a16
    .i16
    sf_pool_init BUL_ALIVE, BULLET_N
    sf_pool_init ENE_ALIVE, ENEMY_N
    lda #SHIP_SPAWN_X
    sta PX
    lda #SHIP_SPAWN_Y
    sta PY
    stz SCORE
    stz SPAWN_IX
    lda #SPAWN_PERIOD
    sta SPAWN_T
    lda #START_LIVES
    sta LIVES
    stz HURTLOCK
    stz GAMEOVER
    lda #$0001
    sta SDIRTY                  ; force the SCORE + LIVES reprint next frame
    sf_text_clear #12, #15      ; wipe the GAME OVER / PRESS START banner rows
    rts

; =============================================================================
; DATA — strings, spawn + island tables, the bullet tile, converted art
; =============================================================================
score_str:
    .byte "SCORE", 0
lives_str:
    .byte "LIVES", 0
gameover_str:
    .byte "GAME OVER", 0
restart_str:
    .byte "PRESS START", 0

; ghost spawn columns (16px ghost, playfield x 8..224) — table-driven so runs
; are deterministic enough to test, varied enough to play
spawn_xs:
    .word 24, 120, 200, 64, 168, 88, 216, 40

; terrain island origins (tilemap cells, staggered; patch is 8x6)
island_xs:
    .word 2, 14, 24, 8, 20
island_ys:
    .word 2, 9, 18, 22, 28

; one 8x8 bullet: a 4px-wide column, colour index 1 (OBJ palette 2 slot 1)
bullet_tile:
    .byte $3C,$00, $3C,$00, $3C,$00, $3C,$00
    .byte $3C,$00, $3C,$00, $3C,$00, $3C,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

; --- converted art (committed png2snes output; see headers for the commands) ---
.include "assets/hero.inc"
.include "assets/ghost.inc"
.include "assets/terrain.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"
.include "tad_bridge.asm"       ; TAD front-end the sf_audio_* macros call into
