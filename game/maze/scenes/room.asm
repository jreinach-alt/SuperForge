; =============================================================================
; scenes/room.asm — the whole game: the per-axis move-check
; =============================================================================
; The whole game loop: compute the tentative X, probe the map, keep it only if
; clear; then the tentative Y against the (possibly updated) X; then draw.
; Testing and committing the axes SEPARATELY is the whole lesson — a diagonal
; push into a wall keeps the free axis moving (a slide) instead of cancelling
; the move (a stick). The four-corner box test is mz_solid_box, over col_map.

; --- col_map's world binding -------------------------------------------------
; Declared at the COMPOSITION site, not in the feature: col_map carries no
; default for any of these — a defaulted world size reads real
; ROM bytes at the wrong stride and returns a plausible flag.
;
; THE WORLD IS THE 32x32 ROOM MAP, so both log2s are 5 — asserted against the
; blob's own emitted size rather than stated, so a re-themed room of another
; size stops the build here instead of reading the wrong stride.
CM_WORLD_W_LOG2      = 5
CM_WORLD_H_LOG2      = 5
.assert (1 << CM_WORLD_W_LOG2) * (1 << CM_WORLD_H_LOG2) = ES_R_MZ_ROOM_SIZE, error, "col_map world size disagrees with the mz_room claim"

CM_WORLD_BLOB        = ES_R_MZ_ROOM_ADDR
CM_WORLD_BLOB_BANK   = ES_R_MZ_ROOM_BANK
; DERIVED from the claim's own size, not narrated: 1024 B against a 32 KB
; LoROM window is 1, so col_map takes its constant-bank branch and owes no
; bank-adjacency assert (m7_dungeon's binding carries the full argument,
; including why every route to CHUNKS >= 2 is refused upstream — the plain
; ES_R_* symbols cease to exist the day the claim is tiled). 32768 is the
; window SIZE in bytes, the same value col_map's own `rpc = 32768 / W` names.
CM_WORLD_BLOB_CHUNKS = (ES_R_MZ_ROOM_SIZE + 32767) / 32768
CM_FLAGS             = mz_flags_bin
.include "col_map.asm"

; --- maze_obj's position binding --------------------------------------------
; The sprite draws the coordinate the move-check committed — one source of
; truth for "where is the player" (m7dg_obj's MDO_ENEMY_POS pattern).
MZO_PX = US_PX
MZO_PY = US_PY
.include "maze_obj.asm"

; The room's walkable span, derived from col_map's own binding rather than
; restated: the world is 32 tiles of 8 px on each axis.
MZ_WORLD_PX = 1 << (CM_WORLD_W_LOG2 + 3)

.scope room

; =============================================================================
; THE ONE BASE RATE tick_scale SCALES (docs/96 §4, docs/97 §3)
; =============================================================================
; MZ_SPEED is still the one number to reach for when tuning how this rail
; feels; what changed is that it is now a RATE rather than a per-frame
; immediate. On NTSC TS_STEP publishes it to the pixel, so the picture cannot
; move; on PAL it publishes 2 or 3 in the pattern that averages 2.4036.
;
; THE NO-TUNNEL BOUND IS WHAT MAKES THIS SAFE, and it is worth restating where
; the scale happens rather than only in maze.inc: the move-check probes the
; four corners of the box AT THE TENTATIVE POSITION and drops the whole step if
; any is solid, so the property it needs is that one step cannot carry the box
; ACROSS a solid cell without landing in it. That needs step < 8, the cell
; size. The largest step this composition can publish is 3.
;
; The step is per-RATE, not per-axis: x and y both move at MZ_SPEED, so both
; read the one published word and share the one carried fraction.
TS_MOVE_BASE = MZ_SPEED * TS_ONE

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr mz_bg_arm                   ; CHR, palette, the rendered room, the pin
    jsr mzo_arm                     ; OBJ CHR, palette, OBSEL, tile + attr
    ; ---- the player, in the open left chamber ----------------------------
    lda #MZ_SPAWN_X
    sta z:US_PX
    lda #MZ_SPAWN_Y
    sta z:US_PY
    stz z:US_FRAMES
    stz z:US_TS_ACC                 ; the timebase's carried fraction, and this
    stz z:US_TS_STEP                ;   frame's step: written before either is
                                    ;   read (enter's own draw runs first)
    jsr mzo_draw                    ; stage BEFORE the first NMI, so frame 0
                                    ; commits a real entry rather than
                                    ; whatever oam_park_all left
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE, TM, BG1SC and BG12NBA are the `scene_writes` this scene owns on
    ; maze_bg's behalf (that feature.toml's attribution note). Every value
    ; comes from the allocator's emitted encoding; none is narrated from a
    ; VRAM address here.
    sep #$20
    .a8
    lda #1                          ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
    lda #ES_V_MZ_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_MZ_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #((1 << 4) | 1)             ; TM: OBJ + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A, X, Y.
;
; X axis proposed, probed, committed-if-clear; then Y against the committed X.
; LEVEL-triggered input (ES_INP_CUR) — the pad is held to walk. Opposite
; directions both apply and cancel arithmetically (no priority branch).
tick:
    .a16
    .i16
    inc z:US_FRAMES
    ; ---- this frame's region-correct step, published once ------------------
    ; Both axes read it, so it is computed before either tentative move rather
    ; than inside them: compute once per frame per rate, consume as often as
    ; the frame needs.
    TS_STEP z:US_TS_ACC, TS_MOVE_BASE
    sta z:US_TS_STEP
    ; ---- X axis: tentative move, keep only if clear -----------------------
    lda z:US_PX
    sta z:US_CAND_X
    lda z:US_PY
    sta z:US_CAND_Y                 ; probe at the CURRENT y
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_CAND_X
    clc
    adc z:US_TS_STEP
    sta z:US_CAND_X
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_CAND_X
    sec
    sbc z:US_TS_STEP
    sta z:US_CAND_X
@no_left:
    .a16
    .i16
    jsr mz_solid_box                ; test the X move against the map
    bne @x_blocked
    lda z:US_CAND_X
    sta z:US_PX
@x_blocked:
    .a16
    .i16
    ; ---- Y axis: same, against the (possibly updated) X -------------------
    lda z:US_PX
    sta z:US_CAND_X                 ; probe at the COMMITTED x
    lda z:US_PY
    sta z:US_CAND_Y
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_CAND_Y
    clc
    adc z:US_TS_STEP
    sta z:US_CAND_Y
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_CAND_Y
    sec
    sbc z:US_TS_STEP
    sta z:US_CAND_Y
@no_up:
    .a16
    .i16
    jsr mz_solid_box                ; test the Y move against the map
    bne @y_blocked
    lda z:US_CAND_Y
    sta z:US_PY
@y_blocked:
    .a16
    .i16
    jsr mzo_draw                    ; the sprite draws what collision decided
    rts

; --- mz_solid_box: is any corner of the 8x8 box at (US_CAND_X, US_CAND_Y)
;     on a SOLID tile? -------------------------------------------------------
; In: A16/I16, DB=0. Out: A16, A = 0 all corners clear / 1 = blocked, so the
; caller's test is a plain `bne`.
; Clobbers A, X, Y and col_map's cm_hot.
;
; FOUR corners at +0/+MZ_BOX_FAR (the box spans 8 px, so the far corners are
; +7 — a +8 probe reads the NEIGHBOURING tile and sticks the player to walls).
; col_map_at reads CM_PX/CM_PY and never writes
; them, so each corner rewrites only the coordinate that changed.
;
; WIDTH-RISK: col_map_at is a CROSS-FILE contract — entered A16/I16, EXITS
; A8/I16, deliberately (the flag is a byte). The `rep #$20` after each call is
; a forced widening back to this routine's width and must not be dropped: an
; A8 test of a two-byte compare reads a blocked corner as clear. width-check
; cannot see across the file boundary in either direction, so this marker
; carries it (m7_dungeon's FP_CORNER carries the same one).
mz_solid_box:
    .a16
    .i16
    ; corner (x, y)
    lda z:US_CAND_X
    sta z:CM_PX
    lda z:US_CAND_Y
    sta z:CM_PY
    jsr col_map_at
    rep #$20
    .a16
    and #MZ_FLAG_SOLID
    bne @hit
    ; corner (x+7, y)
    lda z:US_CAND_X
    clc
    adc #MZ_BOX_FAR
    sta z:CM_PX
    jsr col_map_at
    rep #$20
    .a16
    and #MZ_FLAG_SOLID
    bne @hit
    ; corner (x, y+7)
    lda z:US_CAND_X
    sta z:CM_PX
    lda z:US_CAND_Y
    clc
    adc #MZ_BOX_FAR
    sta z:CM_PY
    jsr col_map_at
    rep #$20
    .a16
    and #MZ_FLAG_SOLID
    bne @hit
    ; corner (x+7, y+7)
    lda z:US_CAND_X
    clc
    adc #MZ_BOX_FAR
    sta z:CM_PX
    jsr col_map_at
    rep #$20
    .a16
    and #MZ_FLAG_SOLID
    bne @hit
    lda #0                          ; all four corners clear
    rts
@hit:
    .a16
    .i16
    lda #1
    rts

; --- exit -----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. There is nowhere to go —
; one scene, no edges — so the handler exists to satisfy scene_mgr's table
; and re-parks what this scene armed (the exit contract every scene owes).
exit:
    .a16
    .i16
    jsr oam_park_all
    rts

.endscope
