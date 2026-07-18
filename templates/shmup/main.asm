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
; col_box (hits), sf_text (score HUD), the OBJ/BG blob loaders.
;
; Controls: d-pad moves the ship, A fires (rising edge, one bullet per press).
; Bullets fly up at 4 px/f; ghosts spawn on a timer at table-driven columns
; and drift down at 1 px/f; a bullet hit kills both and scores a point.
;
; STABLE OAM SLOTS (the sf_pool draw idiom): every pool slot is drawn every
; frame — live actors at their position, dead slots parked at y=$F0 — so OAM
; slot k always belongs to the same actor: 0 = ship, 1-6 = bullets, 7-10 =
; ghosts. Tests (and your debugging) can identify actors by OAM slot.
;
; NO player-damage state machine by design — the rail stays thin. Lives /
; game-over / win lockout are game-loop composition, proven in the patrol and
; stomper templates; graft their pattern when your game needs it.
;
; Tuning (override by defining before .include, or just edit):
;   SHIP_SPEED   px/frame d-pad movement (default 2)
;   BULLET_SPEED px/frame upward        (default 4)
;   ENEMY_SPEED  px/frame downward      (default 1)
;   SPAWN_PERIOD frames between spawns  (default 48)
;
; Done-condition (emulator-verifiable):
;   - boots; terrain + ship render (screenshot pixels match the converted art)
;   - terrain autoscrolls DOWN; ship moves in all four directions, clamped
;   - A spawns a bullet that travels up and dies at the top
;   - ghosts spawn, descend, die to bullets; SCORE counts up on the HUD
;
; Build:  make shmup        (-> build/shmup.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_load_obj_chr/pal, sf_load_obj_tile, sf_obj_color
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_collision.inc"     ; col_box
.include "sf_bg.inc"            ; gfxmode, mset, sf_autoscroll_v, BG loaders
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_pool.inc"          ; sf_pool_init/spawn/kill_x/count
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"

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
SDIRTY   = $52                  ; 1 = score changed, reprint the HUD

; --- pools (the $1800-$1DFF game-array region — see sf_pool.inc) ---
BULLET_N  = 6
BUL_ALIVE = $1800               ; alive[6]
BUL_X     = $1810               ; x[6]
BUL_Y     = $1820               ; y[6]
ENEMY_N   = 4
ENE_ALIVE = $1830               ; alive[4]
ENE_X     = $1840               ; x[4]
ENE_Y     = $1850               ; y[4]

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init

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

    jsr init_ppu                ; engine PPU defaults (OBSEL $00: 8x8/16x16)
    gfxmode #1                  ; enable BG1+BG3 (zeros the shadow tilemaps)

    ; --- scatter terrain ISLANDS over the black backdrop ---
    ; The converted 8x6-cell patch is stamped at staggered origins (the
    ; islands table); everything else stays tile 0 = transparent over the
    ; black backdrop, so sprites read clearly against the sky (a busy
    ; full-screen tilemap buries the gameplay). The 32-high map wraps as it
    ; autoscrolls, so the island field loops seamlessly.
    rep #$30
    .a16
    .i16
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

    ; --- game state ---
    sf_pool_init BUL_ALIVE, BULLET_N
    sf_pool_init ENE_ALIVE, ENEMY_N
    rep #$30
    .a16
    .i16
    lda #120
    sta PX
    lda #180
    sta PY
    stz SCORE
    stz SCRL
    stz SPAWN_IX
    stz SDIRTY
    lda #SPAWN_PERIOD
    sta SPAWN_T

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    sf_frame_begin

    ; ---------------- input: move the ship (clamped to the playfield) -------
    btn #BTN_RIGHT
    beq mv_no_right
    rep #$20
    .a16
    lda PX
    clc
    adc #SHIP_SPEED
    cmp #224                    ; right clamp (16px ship, 240px visible edge)
    bcc mv_store_x_r
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
    cmp #200
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
    cmp #16
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
    lda #24
    sta ENE_Y, x
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
    cmp #208
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

    ; ---------------- HUD: reprint the score only when it changed -----------
    lda SDIRTY
    beq hud_done
    stz SDIRTY
    sf_print_u16 SCORE, #56, #8
hud_done:
    .a16

    ; ---------------- draw: every slot every frame (stable OAM slots) -------
    spr_clear
    ; slot 0: the ship (16x16 large, OBJ palette 0)
    spr #(HERO_BASE + hero_f0), PX, PY, #$80, #2

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

    ; slots 7-10: ghosts (16x16 large, palette 1); dead slots park at y=$F0
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
    spr #(GHOST_BASE + ghost_f0), EX, EY, #$82, #2
    lda EOFF
    inc a
    inc a
    sta EOFF
    cmp #(2 * ENEMY_N)
    bcs draw_e_done
    jmp draw_e_loop
draw_e_done:
    .a16

    ; ---------------- world: terrain drifts down ----------------------------
    sf_autoscroll_v #1, SCRL, #1

    sf_frame_end
    jmp game_loop

; =============================================================================
score_str:
    .byte "SCORE", 0

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
