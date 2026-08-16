; =============================================================================
; play scene — the shooter: a ship, a planet field, and everything hostile
; =============================================================================
; Composition: shmup_bg (BG1 planet field + BG2 HUD band), shmup_obj (the
; sixteen sprites and the three pools they live in), bg_text (the HUD and the
; verdict rows). Every resource this scene touches is an allocator-emitted
; symbol; the game logic below reads and writes those and nothing else.
;
; LAYER OWNERSHIP, asserted here and in shmup_bg/feature.toml because layer
; identity is not a resource the allocator models: this enter is
; the only writer of BGMODE, BG1SC, BG2SC, BG3SC, BG12NBA, BG34NBA and TM in
; this game's play scene.
.scope play
.include "engine_state_play.inc"    ; GENERATED — this scene's map

; BG3 2bpp tile attr for the HUD (palette 7, priority — the HUD sits above the
; field and the sprites)
PLAY_TXT_ATTR = (7 << 10) | (1 << 13)

; --- scene-scoped engine feature code — INSIDE the scope: its claims are
; scene-scoped, so its symbols must be too --------------------------------
.include "shmup_bg.asm"
.include "shmup_obj.asm"

; =============================================================================
; MESSAGE BLOCKS — two 11-cell rows written ONE CELL PER FRAME
; =============================================================================
; A running scene cannot write VRAM, so the verdict lines go through bg_text's
; VBlank cell queue. Every block is exactly SHM_MSG_LEN chars at the same two
; rows, so a new block TOTALLY overwrites the last one — no residue, no length
; bookkeeping, no clear pass — the same shape breaker uses. It is also what
; makes an in-place restart unnecessary here: the "clear the banner" step is
; just the next block.

; --- shm_msg_addr: block index -> the BG3 VRAM word address of that cell ----
; In/out: A16 = index 0..SHM_MSG_LEN-1 in, VRAM word address out. I16.
shm_msg_addr:
    .a16
    .i16
    cmp #SHM_MSG_W
    bcs @row1
    clc
    adc #(ES_V_TEXT_MAP + SHM_MSG_ROW0 * 32 + SHM_MSG_COL)
    rts
@row1:
    .a16
    .i16
    sec
    sbc #SHM_MSG_W
    clc
    adc #(ES_V_TEXT_MAP + SHM_MSG_ROW1 * 32 + SHM_MSG_COL)
    rts

; --- shm_msg_ptr: point ES_TXT_PTR at the pending block ---------------------
; In/out: A16/I16, DB=0. A = block address low16. Every block lives in this
; scope's RODATA, so one bank byte serves them all.
shm_msg_ptr:
    .a16
    .i16
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^m_blank
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    rts

; --- shm_msg_start: queue a block for the next SHM_MSG_LEN frames -----------
; In/out: A16/I16, DB=0. A = block address low16.
shm_msg_start:
    .a16
    .i16
    sta z:US_MSG
    stz z:US_MSGPOS
    rts

; --- shm_msg_now: write a whole block immediately (scene enter only) --------
; In/out: A16/I16, DB=0, FORCED BLANK. A = block address low16. Clobbers A,X,Y.
shm_msg_now:
    .a16
    .i16
    jsr shm_msg_ptr
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ldy #0
@cell:
    .a16
    .i16
    tya
    jsr shm_msg_addr
    sta a:$2116                     ; VMADD = this cell
    sep #$20
    .a8
    lda [<ES_TXT_PTR], y            ; the character
    rep #$20
    .a16
    and #$00FF                      ; the byte alone: B still holds the address
    sec
    sbc #' '                        ; glyph index (space -> tile 0)
    ora #PLAY_TXT_ATTR
    sta a:$2118                     ; VMDATA, word mode
    iny
    cpy #SHM_MSG_LEN
    bcc @cell
    rts

; --- shm_msg_tick: stage ONE cell of the pending block ----------------------
; In/out: A16/I16, DB=0. Does nothing when no block is pending.
shm_msg_tick:
    .a16
    .i16
    lda z:US_MSG
    bne @go
    rts
@go:
    .a16
    .i16
    jsr shm_msg_ptr
    ldy z:US_MSGPOS
    sep #$20
    .a8
    lda [<ES_TXT_PTR], y
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #' '
    ora #PLAY_TXT_ATTR
    pha                             ; the tile word, while A carries the index
    tya
    jsr shm_msg_addr
    tax                             ; X = VRAM word address
    pla
    jsr text_queue_cell             ; A = tile word, X = address
    lda z:US_MSGPOS
    inc a
    sta z:US_MSGPOS
    cmp #SHM_MSG_LEN
    bcc @more
    stz z:US_MSG                    ; the block is fully written
@more:
    .a16
    .i16
    rts

; =============================================================================
; HUD — the two live counters, through the same one-cell-per-frame queue
; =============================================================================
; One queue, three customers, one fixed priority: SCORE, then LIVES, then the
; verdict block. The counters go FIRST because they settle in a frame or two
; while a block takes 2*SHM_MSG_W frames to write — put the block first and a
; round ends showing GAME OVER above a LIVES counter still reading 1, for a
; third of a second — long enough to read as a bug.
shm_hud:
    .a16
    .i16
    lda z:US_DIRTY
    bne @counters
    jmp shm_msg_tick
@counters:
    .a16
    .i16
    lda z:US_DIRTY
    and #SHM_DIRTY_SCORE
    beq @lives
    lda z:US_DIRTY
    eor #SHM_DIRTY_SCORE
    sta z:US_DIRTY
    lda #PLAY_TXT_ATTR
    sta z:ES_TXT_TMP
    lda z:US_SCORE                  ; packed BCD, so hex4's nibble walk prints
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_SCORED_C)
    jmp text_queue_hex4             ; ...four DECIMAL digits
@lives:
    .a16
    .i16
    lda z:US_DIRTY
    and #SHM_DIRTY_LIVES
    beq @msg
    lda z:US_DIRTY
    eor #SHM_DIRTY_LIVES
    sta z:US_DIRTY
    lda z:US_LIVES
    and #15
    clc
    adc #('0' - ' ')                ; the '0' glyph's tile index
    ora #PLAY_TXT_ATTR
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_LIVESD_C)
    jmp text_queue_cell
@msg:
    .a16
    .i16
    jmp shm_msg_tick

; =============================================================================
; SCENE LIFECYCLE
; =============================================================================

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    lda f:US_RUNS_LONG
    inc a
    sta f:US_RUNS_LONG
    stz z:US_SCORE
    lda #START_LIVES
    sta z:US_LIVES
    stz z:US_GOVER
    lda #SHIP_SPAWN_X
    sta z:US_PX
    lda #SHIP_SPAWN_Y
    sta z:US_PY
    lda #SPAWN_PERIOD
    sta z:US_SPAWN_T
    stz z:US_SPAWN_IX
    stz z:US_HURT
    stz z:US_ATICK
    stz z:US_AFRAME
    stz z:US_BLINK
    stz z:US_DIRTY                  ; enter prints both counters directly
    stz z:US_MSG
    stz z:US_MSGPOS
    jsr shm_pool_init               ; every slot free, before any tick runs
    ; ---- BG1 + BG2: CHR, palette, the field, the band, layer registers ----
    jsr shm_arm
    ; ---- the sixteen sprites: CHR, three palettes, OBSEL, parked entries ---
    jsr obj_arm
    ; ---- BG3: the HUD's palette and layer registers -----------------------
    sep #$20
    .a8
    lda #ES_C_TEXT_PAL
    sta a:$2121                 ; CGADD = 28 (BG3 palette 7)
    lda #$00                    ; colour 0 (transparent slot)
    sta a:$2122
    sta a:$2122
    lda #$84                    ; colour 1: dark navy $1084
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; colour 2: mid grey $56B5
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; colour 3: white $7FFF
    sta a:$2122
    lda #$7F
    sta a:$2122
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    stz a:$2111                 ; BG3HOFS (write-twice)
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #PLAY_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    ; ---- the HUD labels + the opening values ------------------------------
    lda #PLAY_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_score)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_score
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_SCORE_C)
    jsr text_puts
    lda #.loword(s_lives)
    sta z:ES_TXT_PTR
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_LIVES_C)
    jsr text_puts
    lda z:US_SCORE
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_SCORED_C)
    jsr text_put_hex4
    lda z:US_LIVES
    ldx #(ES_V_TEXT_MAP + SHM_HUD_ROW * 32 + SHM_HUD_LIVESD_C)
    jsr text_put_digit
    lda #.loword(m_blank)
    jsr shm_msg_now             ; the verdict rows start clear
    ; ---- mode + layers: BG1 + BG2 + BG3 + OBJ -----------------------------
    sep #$20
    .a8
    lda #$09                    ; BGMODE 1, BG3 priority high (the HUD sits
                                ; above the field and the sprites)
    sta a:$2105
    lda #$17                    ; TM: BG1 + BG2 + BG3 + OBJ
    sta a:$212C
    rep #$20
    .a16
    ; ---- sprites placed BEFORE the first displayed frame, so frame 0 shows
    ; the ship rather than power-on garbage (rule 5) ------------------------
    jsr obj_draw
    rts

; --- exit: put the sprites back --------------------------------------------
; In/out: A16/I16, DB=0, forced blank.
; The scroll needs no teardown: main.asm's NMI hook stops calling the commit
; the moment `cur` leaves this scene.
exit:
    .a16
    .i16
    jmp obj_park

; --- tick: one game frame --------------------------------------------------
; In/out: A16/I16, DB=0. Display is active: no VRAM writes here — the two
; things that must reach VRAM (a HUD cell, a verdict cell) are STAGED and
; committed by the NMI hook, and BG1VOFS likewise.
tick:
    .a16
    .i16
    jsr shm_update
    jsr shm_hud
    jmp obj_draw

; =============================================================================
; PER-FRAME UPDATE
; =============================================================================
; START LEAVES, FROM ANY STATE. On the GAME OVER screen it is the restart (the
; first half of the trip through the title that rebuilds a fresh round); while
; playing it is the way out of one. Checked before everything else and
; returning immediately: the scene is leaving, so running another frame of
; physics into it is work whose result is discarded.
shm_update:
    .a16
    .i16
    lda z:US_BLINK
    inc a
    sta z:US_BLINK              ; a free-running heartbeat: "the tick ran"
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @live
    sep #$20
    .a8
    lda #SCENE_TITLE
    jsr sm_request
    rep #$20
    .a16
    rts
@live:
    .a16
    .i16
    ; The animation clock runs even on the GAME OVER freeze, so an in-flight
    ; burst finishes rather than stopping mid-explosion.
    jsr shm_anim
    lda z:US_GOVER
    beq @play
    jmp shm_age_bursts          ; frozen: only the bursts still move
@play:
    .a16
    .i16
    jsr shm_drift               ; the field keeps falling
    jsr shm_move_ship
    jsr shm_fire
    jsr shm_move_bullets
    jsr shm_spawn
    jsr shm_move_foes
    jsr shm_age_bursts
    jsr shm_hits               ; bullets vs fighters
    jmp shm_damage             ; fighters vs the ship

; --- shm_anim: the shared animation clock ----------------------------------
; In/out: A16/I16, DB=0. One divider and one step index, shared by the ship
; and every fighter — so the whole cast's engine plumes flicker together,
; which is one lookup a frame instead of five.
shm_anim:
    .a16
    .i16
    lda z:US_ATICK
    inc a
    cmp #ANIM_RATE
    bcc @store
    lda z:US_AFRAME
    inc a
    cmp #ANIM_STEPS
    bcc :+
    lda #0
:   .a16
    .i16
    sta z:US_AFRAME
    lda #0
@store:
    .a16
    .i16
    sta z:US_ATICK
    rts

; --- shm_move_ship: the d-pad, clamped to the playfield --------------------
; In/out: A16/I16, DB=0.
; All four directions, and each clamp compares AFTER the move so a held
; direction parks against the edge instead of oscillating. The subtractions are
; safe against unsigned wrap because SHIP_SPEED <= SHIP_MIN_X and <= SHIP_MIN_Y
; (asserted in shmup.inc).
shm_move_ship:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PX
    clc
    adc #SHIP_SPEED
    cmp #SHIP_MAX_X
    bcc :+
    lda #SHIP_MAX_X
:   .a16
    .i16
    sta z:US_PX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PX
    sec
    sbc #SHIP_SPEED
    cmp #SHIP_MIN_X
    bcs :+
    lda #SHIP_MIN_X
:   .a16
    .i16
    sta z:US_PX
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_PY
    clc
    adc #SHIP_SPEED
    cmp #SHIP_MAX_Y
    bcc :+
    lda #SHIP_MAX_Y
:   .a16
    .i16
    sta z:US_PY
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_PY
    sec
    sbc #SHIP_SPEED
    cmp #SHIP_MIN_Y
    bcs :+
    lda #SHIP_MIN_Y
:   .a16
    .i16
    sta z:US_PY
@no_up:
    .a16
    .i16
    rts

; --- shm_fire: A (rising edge) spawns one bullet ---------------------------
; In/out: A16/I16, DB=0. A full pool swallows the press, which is the whole of
; the rate limit — seven bullets in flight IS the cap.
shm_fire:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    bne @go
    rts
@go:
    .a16
    .i16
    ldx #SHM_BUL
    ldy #SHM_BUL_N
    jsr shm_pool_spawn
    bmi @full
    lda z:US_PX
    clc
    adc #BULLET_DX              ; centre the 8px bullet on the 16px ship
    sta f:ES_SHM_POOLS_LONG + SHM_PX, x
    lda z:US_PY
    sec
    sbc #BULLET_DY              ; the muzzle, just above the nose
    sta f:ES_SHM_POOLS_LONG + SHM_PY, x
    jmp shm_blip
@full:
    .a16
    .i16
    rts

; --- shm_move_bullets: up, and gone at the top -----------------------------
; In/out: A16/I16, DB=0. Pure indexed work, so X survives the whole loop.
shm_move_bullets:
    .a16
    .i16
    ldx #SHM_BUL
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next
    lda f:ES_SHM_POOLS_LONG + SHM_PY, x
    sec
    sbc #BULLET_SPEED
    sta f:ES_SHM_POOLS_LONG + SHM_PY, x
    cmp #BULLET_TOP
    bcs @next                   ; still below the HUD band
    jsr shm_pool_kill
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SHM_BUL + 2 * SHM_BUL_N)
    bcc @one
    rts

; --- shm_spawn: a fighter every SPAWN_PERIOD frames ------------------------
; In/out: A16/I16, DB=0.
; The columns come from an eight-entry table, walked in order: deterministic
; enough to test, varied enough to play, and no RNG to make a run
; unreproducible.
shm_spawn:
    .a16
    .i16
    lda z:US_SPAWN_T
    dec a
    sta z:US_SPAWN_T
    beq @now
    rts
@now:
    .a16
    .i16
    lda #SPAWN_PERIOD
    sta z:US_SPAWN_T
    ldx #SHM_FOE
    ldy #SHM_FOE_N
    jsr shm_pool_spawn
    bmi @full                   ; the wave is full: skip this beat
    phx
    lda z:US_SPAWN_IX
    asl
    tax
    lda f:shm_spawn_xs, x
    plx
    sta f:ES_SHM_POOLS_LONG + SHM_PX, x
    lda #FOE_SPAWN_Y
    sta f:ES_SHM_POOLS_LONG + SHM_PY, x
    lda z:US_SPAWN_IX
    inc a
    and #7                      ; cycle the eight-entry column table
    sta z:US_SPAWN_IX
@full:
    .a16
    .i16
    rts

; --- shm_move_foes: down, and gone past the bottom -------------------------
; In/out: A16/I16, DB=0.
shm_move_foes:
    .a16
    .i16
    ldx #SHM_FOE
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next
    lda f:ES_SHM_POOLS_LONG + SHM_PY, x
    clc
    adc #FOE_SPEED
    sta f:ES_SHM_POOLS_LONG + SHM_PY, x
    cmp #FOE_GONE_Y
    bcc @next
    jsr shm_pool_kill           ; escaped off the bottom
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SHM_FOE + 2 * SHM_FOE_N)
    bcc @one
    rts

; --- shm_age_bursts: count every live burst down, free it at zero ----------
; In/out: A16/I16, DB=0. Runs on the GAME OVER freeze too, so an explosion
; started on the fatal frame finishes rather than hanging.
shm_age_bursts:
    .a16
    .i16
    ldx #SHM_BUR
@one:
    .a16
    .i16
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next
    lda f:ES_SHM_POOLS_LONG + SHM_PT, x
    dec a
    sta f:ES_SHM_POOLS_LONG + SHM_PT, x
    bne @next                   ; still burning
    jsr shm_pool_kill
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SHM_BUR + 2 * SHM_BUR_N)
    bcc @one
    rts

; --- shm_burst: start a kill-burst at (US_BX, US_BY) -----------------------
; In/out: A16/I16, DB=0. A full pool silently drops it — a burst is visual
; only, so dropping one costs nothing the game depends on. Clobbers A, X, Y.
shm_burst:
    .a16
    .i16
    ldx #SHM_BUR
    ldy #SHM_BUR_N
    jsr shm_pool_spawn
    bmi @full
    lda z:US_BX
    sta f:ES_SHM_POOLS_LONG + SHM_PX, x
    lda z:US_BY
    sta f:ES_SHM_POOLS_LONG + SHM_PY, x
    lda #BURST_LIFE
    sta f:ES_SHM_POOLS_LONG + SHM_PT, x
@full:
    .a16
    .i16
    rts

; --- shm_blip: one sound effect --------------------------------------------
; In/out: A16/I16, DB=0.
; WIDTH-RISK: Tad_QueueSoundEffect is a CROSS-FILE callee (vendor/tad) and
; takes A8; the width linter is single-file and cannot see the contract, so the
; sep/rep pair around it is load-bearing and stays here rather than at the call
; sites.
shm_blip:
    .a16
    .i16
    sep #$20
    .a8
    lda #SFX::footstep
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16
    rts

; =============================================================================
; COLLISION — an AABB overlap test, twice
; =============================================================================
; The `col_map` feature does not fit here and is not composed: it is a
; tile-flag lookup into an immutable ROM world blob, and this rail has no
; collision map at all — only actors against actors. So the test is four
; compares, and it lives here, in the game, because it IS the game's.
;
; --- shm_overlap: do boxes A and B overlap? --------------------------------
; In:  A16/I16, DB=0. US_AX/US_AY = box A's top-left, US_BX/US_BY = box B's.
;      US_TMP = A's size, US_TMP2 = B's size (square boxes: one number each).
; Out: Z clear = they overlap, Z set = they do not. Clobbers A.
;
; The comparisons are unsigned and every coordinate here is a positive screen
; pixel, so no sign handling is needed: an actor that has left the playfield is
; killed by its own mover before this ever sees it.
shm_overlap:
    .a16
    .i16
    lda z:US_AX
    clc
    adc z:US_TMP
    cmp z:US_BX
    bcc @miss                   ; A's right edge is left of B
    lda z:US_BX
    clc
    adc z:US_TMP2
    cmp z:US_AX
    bcc @miss                   ; B's right edge is left of A
    lda z:US_AY
    clc
    adc z:US_TMP
    cmp z:US_BY
    bcc @miss                   ; A's bottom is above B
    lda z:US_BY
    clc
    adc z:US_TMP2
    cmp z:US_AY
    bcc @miss                   ; B's bottom is above A
    lda #1
    rts
@miss:
    .a16
    .i16
    lda #0
    rts

; --- shm_hits: every live bullet against every live fighter ----------------
; In/out: A16/I16, DB=0.
; Two nested pool sweeps, both cursors in DP because shm_overlap and the kill
; path clobber the registers. A hit kills BOTH, bursts the fighter, scores a
; point and stops that bullet's inner loop — one bullet cannot kill two.
shm_hits:
    .a16
    .i16
    lda #SHM_BUL
    sta z:US_OFF
@bullet:
    .a16
    .i16
    ldx z:US_OFF
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next_bullet
    lda f:ES_SHM_POOLS_LONG + SHM_PX, x
    sta z:US_AX
    lda f:ES_SHM_POOLS_LONG + SHM_PY, x
    sta z:US_AY
    lda #SHM_FOE
    sta z:US_OFF2
@foe:
    .a16
    .i16
    ldx z:US_OFF2
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next_foe
    lda f:ES_SHM_POOLS_LONG + SHM_PX, x
    sta z:US_BX
    lda f:ES_SHM_POOLS_LONG + SHM_PY, x
    sta z:US_BY
    lda #BULLET_W
    sta z:US_TMP
    lda #FOE_W
    sta z:US_TMP2
    jsr shm_overlap
    beq @next_foe
    ; ---- a kill -----------------------------------------------------------
    ldx z:US_OFF2
    jsr shm_pool_kill           ; the fighter
    ldx z:US_OFF
    jsr shm_pool_kill           ; ...and the bullet that spent itself on it
    jsr shm_burst               ; the explosion, at the fighter (US_BX/US_BY)
    jsr shm_score
    jsr shm_blip
    bra @next_bullet
@next_foe:
    .a16
    .i16
    lda z:US_OFF2
    clc
    adc #2
    sta z:US_OFF2
    cmp #(SHM_FOE + 2 * SHM_FOE_N)
    bcc @foe
@next_bullet:
    .a16
    .i16
    lda z:US_OFF
    clc
    adc #2
    sta z:US_OFF
    cmp #(SHM_BUL + 2 * SHM_BUL_N)
    bcc @bullet
    rts

; --- shm_score: one point, in packed BCD -----------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
; `sed` + a 16-bit adc gives four decimal digits, and bg_text's hex4 nibble
; walk then prints them as decimal for free — a decimal formatter this game
; does not have to own. The 65816 CLEARS D on interrupt entry and
; `rti` restores it, so an NMI landing inside this window cannot inherit
; decimal mode.
shm_score:
    .a16
    .i16
    sed
    clc
    lda z:US_SCORE
    adc #1
    sta z:US_SCORE
    cld
    lda z:US_DIRTY
    ora #SHM_DIRTY_SCORE
    sta z:US_DIRTY
    rts

; --- shm_damage: a fighter touching the ship costs a life ------------------
; In/out: A16/I16, DB=0.
; The i-frame counter gates the check AND drives the blink, so one word does
; both jobs: while it is running the ship cannot be hit and obj_draw parks it
; every other four frames.
shm_damage:
    .a16
    .i16
    lda z:US_HURT
    beq @check
    dec a
    sta z:US_HURT
    rts                         ; still invulnerable this frame
@check:
    .a16
    .i16
    lda z:US_PX
    sta z:US_AX
    lda z:US_PY
    sta z:US_AY
    lda #SHM_FOE
    sta z:US_OFF
@foe:
    .a16
    .i16
    ldx z:US_OFF
    lda f:ES_SHM_POOLS_LONG + SHM_ALIVE, x
    beq @next
    lda f:ES_SHM_POOLS_LONG + SHM_PX, x
    sta z:US_BX
    lda f:ES_SHM_POOLS_LONG + SHM_PY, x
    sta z:US_BY
    lda #SHIP_W
    sta z:US_TMP
    lda #FOE_W
    sta z:US_TMP2
    jsr shm_overlap
    bne @hit
@next:
    .a16
    .i16
    lda z:US_OFF
    clc
    adc #2
    sta z:US_OFF
    cmp #(SHM_FOE + 2 * SHM_FOE_N)
    bcc @foe
    rts
@hit:
    .a16
    .i16
    ldx z:US_OFF
    jsr shm_pool_kill           ; the colliding fighter bursts too
    jsr shm_burst
    jsr shm_blip
    lda #SHIP_SPAWN_X
    sta z:US_PX
    lda #SHIP_SPAWN_Y
    sta z:US_PY
    lda #IFRAMES
    sta z:US_HURT               ; invulnerability + the blink window
    lda z:US_LIVES
    dec a
    sta z:US_LIVES
    lda z:US_DIRTY
    ora #SHM_DIRTY_LIVES
    sta z:US_DIRTY
    lda z:US_LIVES
    bne @alive
    lda #1
    sta z:US_GOVER              ; out of ships: the world freezes
    stz z:US_HURT               ; ...and the ship draws solid on the freeze
    lda #.loword(m_over)
    jmp shm_msg_start
@alive:
    .a16
    .i16
    rts

; =============================================================================
; DATA
; =============================================================================
.segment "RODATA"
s_score: .byte "SCORE", 0
s_lives: .byte "LIVES", 0

; Fighter spawn columns (16px fighter, playfield x 8..224) — table-driven so a
; run is deterministic enough to test and varied enough to play.
shm_spawn_xs:
    .word 24, 120, 200, 64, 168, 88, 216, 40

; The verdict blocks. Each is EXACTLY SHM_MSG_LEN bytes — a verdict row then a
; prompt row, both padded to SHM_MSG_W — so a new block overwrites the last one
; cell for cell. The .asserts are the guard: a mistyped block would otherwise
; run off into the next one and write another block's text.
m_blank: .byte "           ", "           "
.assert * - m_blank = SHM_MSG_LEN, error, "m_blank is not one message block"
m_over:  .byte " GAME OVER ", "PRESS START"
.assert * - m_over = SHM_MSG_LEN, error, "m_over is not one message block"
.segment "CODE"
.endscope
