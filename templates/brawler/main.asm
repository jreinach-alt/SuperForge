; =============================================================================
; brawler — side-view beat-em-up rail (camelot CC0 art end-to-end)
; =============================================================================
; The genre rail for brawlers/fighters, and the S2 look-and-feel payoff:
; ANIMATED multi-frame 32x32 characters with H-flip facing, straight from
; `tools/png2snes.py sprite --anims` (commands in assets/*.inc headers):
;   - player = Arthur Pendragon (idle 4 / run 8 / hit 4)
;   - enemy  = Mordred (idle 4 / run 8), AI: walks toward the player
;   - floor  = the Four Seasons terrain patch (BG1 strip)
; Composes: sf_anim (clocks + tables), the facing H-flip idiom, col_box
; (timed attack hitbox + contact), sf_text HUD (HP / FOE / WINS).
;
; LANE MOVEMENT: 4-way movement, but the floor reads as a SURFACE SEEN FROM
; THE SIDE (owner-confirmed look): characters stand ON TOP of it. The clamp
; is in CONTENT terms, not OAM-box terms: every camelot frame (both
; knights, idle + run — measured) ends its drawn pixels at row 28 of the
; 32-row cell, i.e. 4 transparent rows under the feet. So the DRAWN feet
; sit at PY + CONTENT_BOTTOM, and the band pins them to the surface top
; (y=160): PY spans 132 (feet exactly on the edge) to 136 (4px of give).
; Set LANE_BOT = LANE_TOP for zero give. A box-edge clamp (PY+32 = 160)
; leaves a 4px sky gap under the feet — measured on screen, don't regress
; to it. NOTE: draw order is FIXED here —
; the player holds OAM slot 0, which always wins overlap against slot 1
; (lower slot = drawn in front). True Y-sorted depth (whoever is lower on
; screen in front) needs per-frame slot assignment — out of this rail's
; scope at two actors.
;
; THE 9-BIT TILE LESSON, exercised: Arthur loads at OBJ base 0 (tiles
; 0-255); Mordred at base 256 (tiles 256-511, the second OBJ name table).
; The OAM tile byte holds only the low 8 bits — bit 8 travels in the
; attribute's name-select bit = spr flags bit 0. Every Mordred tile is
; >=256, so his flags carry a constant |1 (see MORDRED_FLAGS).
;
; Combat:
;   - A = sword swing: plays the hit anim for ATTACK_LEN frames; the 16x16
;     hitbox in FRONT of Arthur is live during frames 4..12; first overlap
;     with Mordred lands ONE hit per swing (latched): FOE hp -1, brief stun.
;   - FOE hp 0 -> WINS +1, Mordred despawns and respawns at an edge after
;     RESPAWN_T frames with full hp.
;   - contact while not invulnerable: HP -1, knockback + i-frames; HP 0 ->
;     "GAME OVER" + freeze (the proven lockout pattern).
;
; State machine discipline (sf_anim.inc): ATICK/AFRAME reset on EVERY anim
; state change (idle<->run<->hit), or a 4-step table gets indexed past its
; end by a stale 8-step frame counter.
;
; CAMELOT PACK NOTES (read before adapting):
;   - sheet layout is row-major: collected frame index = row*8 + col;
;     RIGHT-facing frames are cols 0-3 of each row (left-facing 4-7 exist
;     but the kit's facing idiom H-flips the right frames instead — half
;     the CHR). The per-character row map is in the pack's "- READ ME -".
;   - the "hit" row is a DAMAGE-REACTION flash, not an attack swing. This
;     rail uses Arthur's as a pseudo-swing for compactness; a real swing
;     is the separate WEAPON sheets (excalibur_, staff_) composited as an
;     overlay sprite — see acceptance run #12's camelot_arena for the
;     worked pattern.
;
; Tuning: WALK_SPEED, ENEMY_SPEED, ATTACK_LEN, PLAYER_HP, FOE_HP, RESPAWN_T
; (define before .include, or edit).
;
; Done-condition (emulator-verifiable):
;   - boots; floor + both knights + "HP 3  FOE 3  WINS 0"-style HUD render
;   - Arthur walks all 4 directions inside the arena, faces his travel
;     direction (OAM H-flip), and ANIMATES (idle<->run tile cycling)
;   - Mordred walks toward Arthur and faces him
;   - a swing in range: FOE hp ticks down on the HUD; 3 hits -> WINS +1,
;     respawn; contact: HP ticks down + knockback; HP 0 -> GAME OVER freeze
;
; Build:  make brawler        (-> build/brawler.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_load_obj_chr/pal
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_collision.inc"     ; col_box
.include "sf_bg.inc"            ; gfxmode, mset, BG loaders
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_anim.inc"          ; sf_anim_step, sf_anim_tile
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"

; --- tuning (assemble-time) ---
.ifndef WALK_SPEED
WALK_SPEED = 2
.endif
.ifndef ENEMY_SPEED
ENEMY_SPEED = 1
.endif
.ifndef ATTACK_LEN
ATTACK_LEN = 16                 ; frames; hitbox live 4..12
.endif
.ifndef PLAYER_HP
PLAYER_HP = 3
.endif
.ifndef FOE_HP
FOE_HP = 3
.endif
.ifndef RESPAWN_T
RESPAWN_T = 90
.endif
.assert WALK_SPEED <= 8, error, "WALK_SPEED > 8 breaks the clamps (min position >= max step)"

; --- arena (32x32 sprites; screen 256x224) ---
ARENA_L  = 8
ARENA_R  = 216
CONTENT_BOTTOM = 28             ; drawn feet inside the 32x32 cell. png2snes
                                ;   emits this per conversion — the asserts
                                ;   below pin it to the committed assets, so
                                ;   re-converted art that moves the baseline
                                ;   fails the build instead of floating
LANE_TOP = 132                  ; drawn feet (PY+28) = 160: ON the surface top
LANE_BOT = 136                  ; drawn feet = 164: max 4px of give
.assert LANE_TOP + CONTENT_BOTTOM = 160, error, "lane band no longer anchors drawn feet to the surface top (y=160)"

; --- OBJ VRAM layout ---
ARTHUR_BASE  = 0                ; tiles 0-255 (16 frames @ 32x32)
MORDRED_BASE = 256              ; tiles 256-511 (second name table)
MORDRED_FLAGS = $03             ; palette 1 (bits 3:1) | name bit (tile>=256)

; --- anim states ---
ST_IDLE   = 0
ST_RUN    = 1
ST_ATTACK = 2

; --- DP state ($32-$5F; API block owns $60+) ---
PX      = $32                   ; player x (top-left of 32x32)
PY      = $34
FACING  = $36                   ; 0 = right, 1 = left
ASTATE  = $38                   ; ST_*
ATICK   = $3A                   ; player anim clock
AFRAME  = $3C
ATTACKT = $3E                   ; frames left in the swing (0 = not attacking)
EX      = $40                   ; enemy x/y
EY      = $42
EFACE   = $44                   ; enemy facing (computed toward player)
ETICK   = $46                   ; enemy anim clock
EFRAME  = $48
PTILE   = $4A                   ; draw scratch
PFLAGS  = $4C
HX      = $4E                   ; attack hitbox x/y
HY      = $50
EMOV    = $52                   ; 1 = enemy moved this frame (anim select)

; --- low-frequency state (the $1800-$1DFF game-array region) ---
HP      = $1800                 ; player hp
FOE     = $1802                 ; enemy hp
WINS    = $1804
PINV    = $1806                 ; player i-frames
ESTUN   = $1808                 ; enemy stun frames after a landed hit
ERESP   = $180A                 ; respawn countdown (0 = enemy active)
AHIT    = $180C                 ; this swing already landed (latch)
SDIRTY  = $180E                 ; 1 = HUD needs reprint
GAMEOVER = $1810

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; --- uploads under the coldstart forced blank ---
    sf_load_bg_chr 0, terrain_chr, terrain_chr_bytes
    sf_load_bg_pals 0, terrain_pal, terrain_pal_count
    sf_text_init
    sf_load_obj_chr ARTHUR_BASE,  arthur_chr,  arthur_chr_bytes
    sf_load_obj_chr MORDRED_BASE, mordred_chr, mordred_chr_bytes
    sf_load_obj_pal 0, arthur_pal
    sf_load_obj_pal 1, mordred_pal

    jsr init_ppu

    ; OBSEL pair 3: small = 16x16, large = 32x32 (brief forced blank)
    sep #$20
    .a8
    lda #$80
    sta $2100
    lda #$60
    sta $2101
    lda #$0F
    sta $2100
    rep #$30
    .a16
    .i16

    gfxmode #1

    ; --- floor: a terrain band across rows 20-27 (grass top + dirt fill) ---
    rep #$30
    .a16
    .i16
    stz PTILE                   ; reuse as column counter during build
floor_col:
    ; top row (my=20): patch cell (col mod 8, row 1) — the grass-top blocks
    lda #8                      ; patch row 1 -> word index = 1*8 + (col mod 8)
    sta PFLAGS
    lda PTILE
    and #$0007
    clc
    adc PFLAGS
    asl a
    tax
    lda f:terrain_map, x
    sta HX
    mset #1, PTILE, #20, HX
    ; fill rows 21-27: patch cell (col mod 8, row 2)
    lda #21
    sta HY
floor_fill:
    lda #16                     ; patch row 2 -> word index = 2*8 + (col mod 8)
    sta PFLAGS
    lda PTILE
    and #$0007
    clc
    adc PFLAGS
    asl a
    tax
    lda f:terrain_map, x
    sta HX
    mset #1, PTILE, HY, HX
    lda HY
    inc a
    sta HY
    cmp #28
    bne floor_fill
    lda PTILE
    inc a
    sta PTILE
    cmp #32
    beq floor_done
    jmp floor_col
floor_done:
    .a16

    ; --- HUD ---
    print hp_str, #8, #8
    print foe_str, #88, #8
    print wins_str, #168, #8

    ; --- game state ---
    lda #60
    sta PX
    lda #134                    ; mid-band (drawn feet at 162)
    sta PY
    stz FACING
    stz ASTATE
    stz ATICK
    stz AFRAME
    stz ATTACKT
    lda #180
    sta EX
    lda #134                    ; mid-band (matches the player's spawn lane)
    sta EY
    lda #1
    sta EFACE
    stz ETICK
    stz EFRAME
    lda #PLAYER_HP
    sta HP
    lda #FOE_HP
    sta FOE
    stz WINS
    stz PINV
    stz ESTUN
    stz ERESP
    stz AHIT
    stz GAMEOVER
    lda #1
    sta SDIRTY

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    sf_frame_begin

    lda GAMEOVER
    beq alive
    jmp draw_phase              ; frozen: keep committing frames, ignore input
alive:
    .a16

    ; ---------------- player: attack state runs to completion ---------------
    lda ATTACKT
    beq not_attacking
    dec a
    sta ATTACKT
    bne attack_running
    ; swing over -> back to idle (reset the anim clock: state change)
    lda #ST_IDLE
    sta ASTATE
    stz ATICK
    stz AFRAME
attack_running:
    .a16
    jmp player_done             ; no movement while swinging
not_attacking:
    .a16

    ; A starts a swing (rising edge)
    btnp #BTN_A
    beq no_attack
    lda #ATTACK_LEN
    sta ATTACKT
    lda #ST_ATTACK
    sta ASTATE
    stz ATICK
    stz AFRAME
    stz AHIT                    ; new swing: the hit latch re-arms
    jmp player_done
no_attack:
    .a16

    ; ---------------- player: 4-way lane movement, facing from travel -------
    stz EMOV                    ; reuse as "player moved" within this block
    btn #BTN_RIGHT
    beq pm_no_right
    rep #$20
    .a16
    lda PX
    clc
    adc #WALK_SPEED
    cmp #ARENA_R
    bcc pm_sx_r
    lda #ARENA_R
pm_sx_r:
    sta PX
    stz FACING                  ; travel right -> face right
    lda #1
    sta EMOV
pm_no_right:
    .a16
    btn #BTN_LEFT
    beq pm_no_left
    rep #$20
    .a16
    lda PX
    sec
    sbc #WALK_SPEED
    cmp #ARENA_L                ; safe: PX >= ARENA_L(8) and WALK_SPEED <= 8
    bcs pm_sx_l
    lda #ARENA_L
pm_sx_l:
    sta PX
    lda #1
    sta FACING                  ; travel left -> face left
    sta EMOV
pm_no_left:
    .a16
    btn #BTN_DOWN
    beq pm_no_down
    rep #$20
    .a16
    lda PY
    clc
    adc #WALK_SPEED
    cmp #LANE_BOT
    bcc pm_sy_d
    lda #LANE_BOT
pm_sy_d:
    sta PY
    lda #1
    sta EMOV
pm_no_down:
    .a16
    btn #BTN_UP
    beq pm_no_up
    rep #$20
    .a16
    lda PY
    sec
    sbc #WALK_SPEED
    cmp #LANE_TOP               ; safe: PY >= LANE_TOP and WALK_SPEED <= 8
    bcs pm_sy_u
    lda #LANE_TOP
pm_sy_u:
    sta PY
    lda #1
    sta EMOV
pm_no_up:
    .a16

    ; anim state from movement (reset clocks only on CHANGE)
    lda EMOV
    beq pm_want_idle
    lda ASTATE
    cmp #ST_RUN
    beq player_done
    lda #ST_RUN
    sta ASTATE
    stz ATICK
    stz AFRAME
    bra player_done
pm_want_idle:
    .a16
    lda ASTATE
    cmp #ST_IDLE
    beq player_done
    lda #ST_IDLE
    sta ASTATE
    stz ATICK
    stz AFRAME
player_done:
    .a16

    ; ---------------- enemy: respawn clock / stun / chase -------------------
    lda ERESP
    beq enemy_active
    dec a
    sta ERESP
    beq :+
    jmp enemy_done              ; still gone this frame
:
    ; respawn at the right edge, full hp
    lda #ARENA_R
    sta EX
    lda #134                    ; mid-band (on the surface)
    sta EY
    lda #FOE_HP
    sta FOE
    lda #1
    sta SDIRTY
    jmp enemy_done
enemy_active:
    .a16
    lda ESTUN
    beq enemy_chase
    dec a
    sta ESTUN
    stz EMOV                    ; stunned: stands (idle anim)
    jmp enemy_anim
enemy_chase:
    .a16
    stz EMOV
    ; face + walk toward the player, axis by axis
    lda EX
    cmp PX
    beq ec_no_x
    bcc ec_go_right
    lda #1
    sta EFACE                   ; player is to the left
    lda EX
    sec
    sbc #ENEMY_SPEED
    sta EX
    lda #1
    sta EMOV
    bra ec_no_x
ec_go_right:
    .a16
    stz EFACE
    lda EX
    clc
    adc #ENEMY_SPEED
    sta EX
    lda #1
    sta EMOV
ec_no_x:
    .a16
    lda EY
    cmp PY
    beq ec_no_y
    bcc ec_go_down
    lda EY
    sec
    sbc #ENEMY_SPEED
    sta EY
    lda #1
    sta EMOV
    bra ec_no_y
ec_go_down:
    .a16
    lda EY
    clc
    adc #ENEMY_SPEED
    sta EY
    lda #1
    sta EMOV
ec_no_y:
    .a16
enemy_anim:
    .a16
    ; enemy anim clock (idle when stunned/still, run when chasing)
    sf_anim_step ETICK, EFRAME, #8, #4
    ; (both mordred tables are stepped at len 4 — run uses steps 0-3 of 8;
    ;  keeping one clock length avoids a reset on every stun flicker)
enemy_done:
    .a16

    ; ---------------- combat: the timed hitbox ------------------------------
    ; (jmp trampolines throughout — these gates span the col_box expansion)
    lda ATTACKT
    bne :+
    jmp no_hitbox
:   cmp #(ATTACK_LEN - 12)      ; live window: frames 4..12 of the swing
    bcs :+
    jmp no_hitbox
:   cmp #(ATTACK_LEN - 4 + 1)
    bcc :+
    jmp no_hitbox
:   lda AHIT
    beq :+
    jmp no_hitbox               ; this swing already landed
:   lda ERESP
    beq :+
    jmp no_hitbox               ; nobody to hit
:
    ; hitbox 16x16 in front of Arthur
    lda FACING
    bne hb_left
    lda PX
    clc
    adc #28
    bra hb_store
hb_left:
    .a16
    lda PX
    sec
    sbc #12
hb_store:
    .a16
    sta HX
    lda PY
    clc
    adc #8
    sta HY
    col_box HX, HY, #16, #16,  EX, EY, #32, #32
    bne :+
    jmp no_hitbox
:   ; landed: latch, hurt the foe
    lda #1
    sta AHIT
    sta SDIRTY
    lda #20
    sta ESTUN
    lda FOE
    dec a
    sta FOE
    bne no_hitbox
    ; KO: win + schedule respawn
    lda WINS
    inc a
    sta WINS
    lda #RESPAWN_T
    sta ERESP
no_hitbox:
    .a16

    ; ---------------- combat: contact hurts the player ----------------------
    lda PINV
    beq contact_check
    dec a
    sta PINV
    jmp contact_done
contact_check:
    .a16
    lda ERESP
    beq :+
    jmp contact_done
:   col_box PX, PY, #28, #28,  EX, EY, #28, #28
    bne :+
    jmp contact_done
:   lda HP
    dec a
    sta HP
    lda #1
    sta SDIRTY
    lda #45
    sta PINV
    ; knockback away from the enemy
    lda PX
    cmp EX
    bcc kb_left
    lda PX
    clc
    adc #24
    cmp #ARENA_R
    bcc kb_store
    lda #ARENA_R
    bra kb_store
kb_left:
    .a16
    lda PX
    sec
    sbc #24
    cmp #ARENA_L
    bcs kb_store
    lda #ARENA_L
kb_store:
    .a16
    sta PX
    lda HP
    bne contact_done
    ; KO'd: game over lockout
    lda #1
    sta GAMEOVER
    print over_str, #96, #104
contact_done:
    .a16

    ; ---------------- player anim clock (per current state) -----------------
    ; (jmp trampolines: short branches can't span the sf_anim_step expansions)
    lda ASTATE
    cmp #ST_RUN
    bne :+
    jmp pa_run
:   cmp #ST_ATTACK
    bne :+
    jmp pa_attack
:   sf_anim_step ATICK, AFRAME, #8, #arthur_anim_idle_len
    jmp pa_done
pa_run:
    .a16
    sf_anim_step ATICK, AFRAME, #6, #arthur_anim_run_len
    jmp pa_done
pa_attack:
    .a16
    sf_anim_step ATICK, AFRAME, #4, #arthur_anim_hit_len
pa_done:
    .a16

    ; ---------------- HUD reprint on change ---------------------------------
    lda SDIRTY
    beq draw_phase
    stz SDIRTY
    sf_print_u16 HP, #32, #8
    sf_print_u16 FOE, #120, #8
    sf_print_u16 WINS, #208, #8

; =============================================================================
draw_phase:
    .a16
    spr_clear

    ; --- slot 0: Arthur (tile from state's table; H-flip from FACING) ---
    lda ASTATE
    cmp #ST_RUN
    bne :+
    jmp pd_run
:   cmp #ST_ATTACK
    bne :+
    jmp pd_attack
:   sf_anim_tile arthur_anim_idle, AFRAME
    jmp pd_tile
pd_run:
    .a16
    sf_anim_tile arthur_anim_run, AFRAME
    jmp pd_tile
pd_attack:
    .a16
    sf_anim_tile arthur_anim_hit, AFRAME
pd_tile:
    .a16
    clc
    adc #ARTHUR_BASE
    sta PTILE
    lda #$0080                  ; large (32x32), palette 0
    ldx FACING
    beq pd_face
    ora #$0040                  ; facing left -> H-flip
pd_face:
    .a16
    sta PFLAGS
    spr PTILE, PX, PY, PFLAGS, #2

    ; --- slot 1: Mordred (base 256: name bit constant in MORDRED_FLAGS) ---
    lda ERESP
    beq ed_visible
    ; respawning: park off-screen (keeps slot 1 stable). 32x32 sprites park
    ; at Y=$E0, NOT the usual $F0: OAM Y wraps mod 256, so a 32-tall sprite
    ; at $F0 pokes its bottom rows back onto screen lines 1-16.
    stz PTILE
    lda #$00E0
    sta HY
    spr PTILE, #0, HY, #(MORDRED_FLAGS | $80), #2
    jmp drawn
ed_visible:
    .a16
    lda EMOV
    bne :+
    jmp ed_idle
:   sf_anim_tile mordred_anim_run, EFRAME
    jmp ed_tile
ed_idle:
    .a16
    sf_anim_tile mordred_anim_idle, EFRAME
ed_tile:
    .a16
    ; MORDRED_BASE = 256: OAM tile byte = low 8 bits (the offset itself);
    ; bit 8 rides in MORDRED_FLAGS' name bit
    sta PTILE
    lda #(MORDRED_FLAGS | $80)  ; large + palette 1 + name bit
    ldx EFACE
    beq ed_face
    ora #$0040
ed_face:
    .a16
    sta PFLAGS
    spr PTILE, EX, EY, PFLAGS, #2
drawn:
    .a16

    sf_frame_end
    jmp game_loop

; =============================================================================
hp_str:
    .byte "HP", 0
foe_str:
    .byte "FOE", 0
wins_str:
    .byte "WINS", 0
over_str:
    .byte "GAME OVER", 0

; --- converted art (committed png2snes output; see headers for commands) ---
.include "assets/arthur.inc"
.include "assets/mordred.inc"
.include "assets/terrain.inc"

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "collision_engine.asm"
.include "text_engine.asm"
.include "sf_text_data.inc"

; content-anchor agreement: the committed assets' baselines must match the
; CONTENT_BOTTOM the lane band was derived from (png2snes emits these)
.assert arthur_content_bottom = CONTENT_BOTTOM, error, "arthur re-converted with a different feet baseline — re-derive LANE_TOP/LANE_BOT"
.assert mordred_content_bottom = CONTENT_BOTTOM, error, "mordred re-converted with a different feet baseline — re-derive LANE_TOP/LANE_BOT"
