; =============================================================================
; play scene — the whole game: chase the yellow dot with the red player
; =============================================================================
; The whole game loop: read the d-pad (four independent held-state tests, one
; axis step each), test the catch (an 8x8-vs-8x8 AABB), and on overlap bump the
; score and jump the dot to the next of four preset spots — which
; self-debounces, because next frame the dot is elsewhere.
;
; THE COLLISION IS THE GAME'S OWN, INLINE. The engine's built `col_map` is a
; tile-flag lookup and does not fit an actor-vs-actor test, so this is a local
; AABB with a stated contract: boxes span the half-open [x, x+w), overlap is
; STRICT — touching edge-to-edge is NOT a catch — and coordinates are SIGNED
; 16-bit. For two 8x8 boxes that reduces to |px - dx| <= 7 on both axes, tested
; branch-free per axis below. NOTE the shmup's shm_overlap is NOT the model
; here: its `bcc @miss` after `adc` makes touching count as overlap (unsigned,
; closed range) — a different contract, correct for that game, wrong for this
; one.
;
; NO CLAMP, deliberately: nothing bounds the player, so he leaves the screen and
; wraps. The signed AABB keeps the catch test honest while he is out there
; (px = -2 vs dot at 200 is a 202 px miss, not a $FFFE-unsigned artefact), and
; sprg_obj derives both X9 bits from bit 8 every frame, so an off-screen player
; is drawn off-screen rather than 256 px away.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; The scene's own feature code, inside the scope: sprg_obj's claims are
; scene-scoped, so its asm has to see this scene's emitted symbols.
.include "sprg_obj.asm"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- CGRAM word 0: the backdrop, black. The whole background of this
    ; game IS this colour — there is no BG layer to draw anything else. ------
    sep #$20
    .a8
    lda #ES_C_BACKDROP_COLOR
    sta a:$2121                 ; CGADD = 0
    stz a:$2122                 ; black — written, not assumed: power-on CGRAM
    stz a:$2122                 ;   is random and this colour IS the background
    ; ---- BGMODE + TM (backdrop's scene_writes): mode 1, OBJ ALONE ----------
    lda #1
    sta a:$2105                 ; BGMODE 1 — no BG is enabled, so the mode is
                                ;   inert; written because power-on state is
                                ;   random and the claim's job is a known value
    lda #(1 << 4)
    sta a:$212C                 ; TM: OBJ only (bit 4). No BG bit — this is
                                ;   the rail's whole point
    rep #$20
    .a16
    ; ---- the actors' CHR, palettes, OBSEL and resting entries --------------
    jsr sprg_obj_arm
    ; ---- game state. Power-on WRAM/DP is RANDOM (rule 5): these stores ARE
    ; the write-before-read contract for every word state.toml declares. -----
    lda #SPRG_HOME_X
    sta z:US_PX
    lda #SPRG_HOME_Y
    sta z:US_PY
    stz z:US_SCORE
    stz z:US_DOT_IDX
    ldx #0                      ; preset 0 from the table — one source of
    lda f:dot_presets, x        ;   truth for where the dot sits, rather than
    sta z:US_DOT_X              ;   a spawn coordinate inlined here as well
    lda f:dot_presets + 2, x
    sta z:US_DOT_Y
    ; ---- the first placement, so frame 1 draws both where they are ---------
    jsr sprg_obj_place
    rts

; --- exit: re-park the sprites this scene armed -----------------------------
; In/out: A16/I16, DB=0. Never called — this game has one scene and no edges —
; but the claim's contract is symmetric and a second scene would need it.
exit:
    .a16
    .i16
    jsr sprg_obj_park
    rts

; --- tick: one frame (display active — no PPU writes here) ------------------
; In/out: A16/I16, DB=0. The frame's body, in order: move, catch-test, draw.
tick:
    .a16
    .i16
    jsr move_player
    jsr catch_dot
    jmp sprg_obj_place

; --- move_player: the d-pad, on HELD state -----------------------------------
; In/out: A16/I16, DB=0. Per axis: the two directions are tested
; independently, so holding both cancels out. NO clamp (see the header).
move_player:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX
    clc
    adc #SPRG_SPEED
    sta z:US_PX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX
    sec
    sbc #SPRG_SPEED
    sta z:US_PX
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_PY
    clc
    adc #SPRG_SPEED
    sta z:US_PY
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_PY
    sec
    sbc #SPRG_SPEED
    sta z:US_PY
@no_up:
    .a16
    .i16
    rts

; --- catch_dot: player box vs dot box, and the catch action -----------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Per axis: d = p - dot (SIGNED 16-bit difference; sec/sbc wraps correctly),
; then the in-range test -7 <= d <= +7 as ONE unsigned compare: d + 7 lands
; in [0, 14] exactly when d is in range, and any out-of-range d — including
; every negative d below -7, which wraps to a huge unsigned value — lands at
; 15 or above. Strict half-open overlap, per the contract in the header.
catch_dot:
    .a16
    .i16
    lda z:US_PX
    sec
    sbc z:US_DOT_X
    clc
    adc #(SPRG_SIZE - 1)
    cmp #(2 * SPRG_SIZE - 1)
    bcs @miss                   ; |px - dot_x| >= 8: no overlap
    lda z:US_PY
    sec
    sbc z:US_DOT_Y
    clc
    adc #(SPRG_SIZE - 1)
    cmp #(2 * SPRG_SIZE - 1)
    bcs @miss                   ; |py - dot_y| >= 8: no overlap
    ; ---- the catch: score++, dot to the next preset (self-debouncing —
    ; next frame the dot is elsewhere, so one pass = one catch) --------------
    inc z:US_SCORE
    lda z:US_DOT_IDX
    inc a
    and #(SPRG_PRESETS - 1)     ; wrap, derived from the declared count
    sta z:US_DOT_IDX
    asl a
    asl a                       ; *4 bytes per (x, y) preset
    tax
    lda f:dot_presets, x
    sta z:US_DOT_X
    lda f:dot_presets + 2, x
    sta z:US_DOT_Y
@miss:
    .a16
    .i16
    rts

; --- the dot's preset spots (x, y), cycled on each catch --------------------
; The four corners of the play area, inset far enough that an 8x8 box sits
; wholly on screen at each.
.segment "RODATA"
dot_presets:
    .word 200, 60
    .word 60, 60
    .word 200, 160
    .word 60, 160
.segment "CODE"
.endscope
