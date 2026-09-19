; =============================================================================
; m7x_logic.asm — the walk machine: grid steps, world collision, the camera
; =============================================================================
; RPG grid movement. The avatar is pinned at screen centre (m7x_obj) and it is
; the CAMERA that moves: one press slides it exactly one tile — eight world
; pixels over eight frames at one pixel a frame — and while that slide is in
; flight no new input is read. That is what makes movement read as walking a
; grid rather than as free scrolling, and it is also what bounds the camera at
; 1 px/frame, sixty-four times inside mode7_stream's clamp of eight tiles per
; axis per frame.
;
; Every address here is an emitted symbol: `no_literals` refuses anything
; else, so the constants below are all tunings and none of them are addresses.
;
; TWO BEHAVIOURS KEPT DELIBERATELY RATHER THAN TIDIED AWAY:
;
;  * THE DIAGONAL FALL-THROUGH. Input priority is LEFT -> RIGHT -> UP -> DOWN,
;  and after each try the dispatch stops only if a slide actually STARTED. A
;  direction that was BLOCKED falls through to the next held axis. That is
;  what lets a held diagonal keep moving along the open axis instead of
;  freezing against a wall; without it a blocked priority axis eats the whole
;  diagonal.
;  * THE FACING IS LATCHED EVEN WHEN THE STEP IS REJECTED. She turns to face a
;  wall she cannot walk into. It is the feedback that says the press
;  registered and the terrain refused, and a version that only turns on a
;  successful step reads as a dropped input.

; --- the grid ---------------------------------------------------------------
; TILE_PX and STEP_FRAMES are equal by design, not by coincidence: the slide
; moves one pixel a frame, so a step takes exactly as many frames as the tile
; is pixels wide and the camera is grid-aligned again the moment it lands.
MXL_TILE_PX     = 8
MXL_STEP_FRAMES = MXL_TILE_PX
.assert MXL_TILE_PX = M7X_WORLD_PX / M7X_WORLD_T, error, "m7x_logic: the tile step disagrees with the generated world geometry"

; =============================================================================
; THE GRID STEP IN TWO REGIONS — why the TICK is scaled and not the pixel
; =============================================================================
; `docs/95` §5.1 #11 names MXL_STEP_FRAMES = MXL_TILE_PX as a HARD INTEGER and
; it is right: the slide moves exactly one pixel a frame for exactly TILE_PX
; frames, and that equality is what leaves the camera grid-aligned the moment
; it lands. It is not scaled here and neither is the tile.
;
; WHAT IS SCALED IS THE STATE STEP ITSELF. `mxl_tick` runs its body 1 or 2
; times per frame — the count `tick_scale` publishes for a base of one tick per
; frame, averaging 1.2018 on PAL and exactly 1 on NTSC. Three reasons that is
; the right shape here rather than the accumulator `scroller` uses:
;
;  * THE CAMERA IS WHOLE PIXELS by declaration (state.toml: "a step is exactly
;    8 px animated over exactly 8 frames at 1 px/frame, so the position is
;    always an integer"). An accumulator on the position publishes 1 or 2 px
;    on exactly the same frames this loop moves on, so it buys no smoothness —
;    only a fraction word and a second way to be wrong.
;  * A PIXEL BUDGET WOULD LEAVE THE ARMING FRAME UNSCALED. A held direction is
;    8 px over NINE frames: eight sliding and one deciding, because
;    `mxl_try_step` arms and returns without moving. Scale only the eight and
;    PAL runs 8 px per 7.66 frames against NTSC's 8 per 9 — 1.0444 px/frame
;    against 0.889, which is 52.2 px/s against 53.4 and reads 0.978, outside
;    tolerance. Scaling the TICK scales the deciding frame with the sliding
;    ones.
;  * THE CLAMP IS UNTOUCHED. `mode7_stream`'s allowance is 8 tiles per axis per
;    frame; two pixels is still thirty-two times inside it, so the quota
;    docs/95 §5.1 #8 warns about is not approached from this direction.
;
; The cost is that ~20% of PAL frames run one extra state step. That is
; docs/96 §4.4's LUMP scheme, whose objection is that its cost is O(tick) —
; and here the tick is one compare, two adds and a countdown, so the objection
; does not reach it. What it buys back is the property that objection was
; about: everything on the rail's clock scales together.
;
; TICK: ok — this block is the region compensator's derivation for this rail.
;   Naming the NTSC frame beside the PAL one is the subject of the comment
;   rather than a coupling in it, exactly as in tick_scale.asm.
MXL_TICK_BASE = TS_ONE                  ; one state step per NTSC frame

; --- the camera clamp -------------------------------------------------------
; The Mode 7 tilemap is a 128x128 TORUS and M7SEL is set to wrap, so a camera
; driven past the authored world's edge would show the same 128 tiles again
; rather than nothing. Keeping the camera at least half a window from either
; edge keeps the visible picture inside authored world at all times. The bounds
; are the GENERATOR's own — it carves a walkable path across exactly this box —
; so the two cannot drift.
MXL_CLAMP_MIN = M7X_CLAMP_MIN
MXL_CLAMP_MAX = M7X_CLAMP_MAX
.assert MXL_CLAMP_MIN = M7X_VRAM_WIN / 2, error, "m7x_logic: the clamp margin is not half the VRAM window"
.assert MXL_CLAMP_MAX = M7X_WORLD_T - 1 - M7X_VRAM_WIN / 2, error, "m7x_logic: the clamp box does not reach the far edge"

; --- spawn ------------------------------------------------------------------
; The generator forces a 7x7 grass clearing here and a walkable path out of it
; on both axes, so the rail starts somewhere you can actually walk from.
MXL_SPAWN_PX = M7X_SPAWN_TX * MXL_TILE_PX
MXL_SPAWN_PY = M7X_SPAWN_TY * MXL_TILE_PX

; --- the pivot: the avatar's TILE, under the avatar's BODY ------------------
; THIS IS A COORDINATE CONTRACT, not framing, and it used to be written as one
; (`MXL_PIVOT_LIFT = 128 - 112`, "sixteen world pixels of vertical framing").
; What the lift actually bought was a picture shifted sixteen world pixels
; against the position every other part of this rail reads: the terrain probe,
; the clamp box and the town trigger all ask about tile (cam_px>>3, cam_py>>3),
; and the avatar is drawn at a FIXED screen box — so a pivot that is not the
; one putting that tile under that box makes "where she is" and "where she
; looks" two different places. MEASURED on the emulator before the change: with
; the camera on tile (258,258) the tile rendered at picture cols 128..135 rows
; 127..134 while her 16x16 body sat at cols 120..135 rows 104..119 — the tile
; she was standing on was drawn NINETEEN SCANLINES BELOW HER FEET, two and a
; bit tile rows. The owner's report was "walking over the town doesn't trigger,
; the trigger point appears to be above the town by a couple rows", which is
; the same nineteen pixels read off a television.
;
; THE CONTRACT: `m7a_set_center(px, py)` puts world pixel (px, py) at screen
; (MXO_CX, MXO_CY) — the same two half-screens m7x_obj pins the avatar's body
; centre on. So the pivot must be the CENTRE of the camera's tile, not its
; origin, and the offsets below are that half tile with the one asymmetry the
; hardware imposes:
;
;   * MXL_PIVOT_DX moves the pivot from the tile's left edge to its middle.
;   * MXL_PIVOT_DY does the same vertically and then takes one scanline back.
;     A BG row and an OBJ row of the same index are not the same scanline: the
;     first displayed BG line is VOFS+1 while an OBJ at y renders starting on
;     y. MEASURED, not assumed — the world's one town_door tile (world px
;     2032,2032 at VOFS 1936) renders with its top row at picture row 95, and
;     the interior's floor (tilemap row 2, VOFS 0) starts at picture row 15.
;
; Both are DERIVED from m7x_obj's pin (a declared `depends`), so re-pinning the
; avatar or resizing her sprite carries the pivot with it instead of leaving
; this file quietly wrong.
MXL_SPR_SCANLINE_BIAS = 1               ; BG row n renders one line lower than
                                        ;   OBJ row n — see above, measured
MXL_SPR_INSET = (MXO_SIZE - MXL_TILE_PX) / 2
MXL_PIVOT_DX = MXO_CX - (MXO_X + MXL_SPR_INSET)
MXL_PIVOT_DY = MXO_CY - (MXO_Y + MXL_SPR_INSET) - MXL_SPR_SCANLINE_BIAS
.assert MXL_PIVOT_DX >= 0, error, "m7x_logic: the pivot's x offset left the tile"
.assert MXL_PIVOT_DX < MXL_TILE_PX, error, "m7x_logic: the pivot's x offset left the tile"
.assert MXL_PIVOT_DY >= 0, error, "m7x_logic: the pivot's y offset left the tile"
.assert MXL_PIVOT_DY < MXL_TILE_PX, error, "m7x_logic: the pivot's y offset left the tile"

; --- the pad ----------------------------------------------------------------
; D-PAD ONLY. No other button is read on this rail — there is nothing to press.
; The auto-joypad word input_read latches into ES_INP_CUR ($4218's layout), and
; the overworld reads it at LEVEL (held), not on the edge: holding a direction
; walks.
;
; Written as BIT POSITIONS, following room_logic.asm and m7dg's dungeon.asm —
; and not only for house style: `no_literals` reads a bare $0200 as an address,
; because it is one (it lands inside the OAM shadow's WRAM claim). A shift says
; "bit 9 of a hardware word", which is what these are.
MXL_JOY_RIGHT = 1 << 8
MXL_JOY_LEFT  = 1 << 9
MXL_JOY_DOWN  = 1 << 10
MXL_JOY_UP    = 1 << 11

; --- the candidate the kernel proposes (the mxl_cand claim) -----------------
MXL_CAND_TX = ES_MXL_CAND + 0
MXL_CAND_TY = ES_MXL_CAND + 2

; =============================================================================
; ARMING — once, at scene enter
; =============================================================================
; CONTRACT mxl_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the grid walker's state seeded at the spawn tile
;   clobbers: A, X, Y, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract
;   tail:     rts
;
; --- mxl_arm: seed the world's state before the first NMI is armed ----------
; contract). Clobbers A, X, Y.
;
; Power-on WRAM is random and neither this feature's `m7org` claim nor the
; game's user state declares an `[init] zero` (rule 5): what follows IS the
; write-before-read contract for every byte of both. The kernel's own
; `mxl_cand` scratch is deliberately absent — it is written before it is read
; inside a single try, and pre-filling it would hide the day that stops being
; true.
mxl_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mxl_arm"
    lda #MXL_SPAWN_PX
    sta z:US_CAM_PX
    lda #MXL_SPAWN_PY
    sta z:US_CAM_PY
    stz z:US_STEP_ACTIVE            ; at rest: no slide in flight...
    stz z:US_STEP_REMAIN            ;   ...no frames left in one...
    stz z:US_STEP_DX                ;   ...and no staged delta
    stz z:US_STEP_DY
    stz z:US_FACING                 ; FACE_DOWN — she faces the camera at boot
    stz z:US_TS_ACC                 ; the timebase's carried fraction...
    stz z:US_LANDED                 ;   ...and this frame's landing flag
    jsr mxl_apply_camera            ; ES_M7ORG + the affine shadow, seeded HERE
                                    ;  so stream_arm and the first NMI both
                                    ;  see a real camera rather than power-on
                                    ;  noise
    rts

; =============================================================================
; THE FRAME
; =============================================================================
; CONTRACT mxl_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one frame of the grid slide, or the start of a new one
;   clobbers: A, X, Y, N, Z
;   assumes:  once per frame from the scene tick, during active display
;   tail:     rts
;
; --- mxl_tick: advance a slide, or start one --------------------------------
;
; A slide in flight OWNS the frame: input is not read at all until it lands.
; That is the grid discipline — a step is atomic — and it is also what keeps
; the camera's speed a constant the streamer can be reasoned about against.
mxl_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mxl_tick"
    stz z:US_LANDED                 ; one frame's answer, rebuilt every frame
    ; This frame's state steps: 1 on NTSC to the tick, 1 or 2 on PAL in the
    ; pattern that averages 1.2018. See "THE GRID STEP IN TWO REGIONS" above.
    TS_STEP z:US_TS_ACC, MXL_TICK_BASE
    beq @none                       ; unreachable on either machine, and the
                                    ;   loop below must not run 65,536 times
                                    ;   if that ever stops being true
@again:
    .a16
    .i16
    pha
    jsr mxl_tick_one
    pla
    dec a
    bne @again
@none:
    .a16
    .i16
    rts

; --- mxl_tick_one: ONE state step ------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. This is the body `mxl_tick` used to
; be, unchanged except that a landing now also raises US_LANDED — the scene's
; town trigger reads that instead of comparing US_STEP_ACTIVE either side of
; the call, because on a doubled PAL frame a slide can land and the next one
; arm before the scene looks, and the pair would then read "still sliding".
mxl_tick_one:
    .a16
    .i16
    lda z:US_STEP_ACTIVE
    beq @idle
    ; ---- (1) a slide is in progress: advance it one pixel ----------------
    lda z:US_CAM_PX
    clc
    adc z:US_STEP_DX                ; the staged delta is -1 / 0 / +1
    sta z:US_CAM_PX
    lda z:US_CAM_PY
    clc
    adc z:US_STEP_DY
    sta z:US_CAM_PY
    lda z:US_STEP_REMAIN
    dec
    sta z:US_STEP_REMAIN
    bne @done
    stz z:US_STEP_ACTIVE            ; landed — grid-aligned again
    lda #1
    sta z:US_LANDED
    rts
@idle:
    .a16
    .i16
    ; ---- (2) held D-pad -> try ONE grid step, priority L, R, U, D --------
    ; FALL-THROUGH ON A BLOCKED AXIS. After each try: if a slide started we are
    ; done; if that direction was refused we fall to the next held axis. See
    ; the file header — this is deliberate and it is what makes a held diagonal
    ; slide along a wall instead of stopping dead against it.
    lda z:ES_INP_CUR
    bit #MXL_JOY_LEFT
    beq @chk_right
    lda #FACE_LEFT                  ; latch the facing even if the step fails
    sta z:US_FACING
    ldx #$FFFF                      ; dx = -1 tile
    ldy #0
    jsr mxl_try_step
    lda z:US_STEP_ACTIVE
    bne @done
@chk_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MXL_JOY_RIGHT
    beq @chk_up
    lda #FACE_RIGHT
    sta z:US_FACING
    ldx #1
    ldy #0
    jsr mxl_try_step
    lda z:US_STEP_ACTIVE
    bne @done
@chk_up:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MXL_JOY_UP
    beq @chk_down
    lda #FACE_UP
    sta z:US_FACING
    ldx #0
    ldy #$FFFF
    jsr mxl_try_step
    lda z:US_STEP_ACTIVE
    bne @done
@chk_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #MXL_JOY_DOWN
    beq @done
    lda #FACE_DOWN
    sta z:US_FACING
    ldx #0
    ldy #1
    jsr mxl_try_step
@done:
    .a16
    .i16
    rts

; --- mxl_try_step: arm a slide in tile direction (X=dx, Y=dy) IF it is legal
; In: A16/I16, DB=0. X, Y = signed 16-bit tile deltas, each -1 / 0 / +1. Out:
; A16/I16. US_STEP_ACTIVE set iff the step was armed. Clobbers A, X, Y and
;  the candidate scratch.
;
; TWO REFUSALS, tested in this order and for different reasons:
;
;  * THE CLAMP BOX, first. A step that would push the camera past the authored
;  world is rejected outright — the 128-tile window would then show wrapped
;  repeats instead of world. Tested BEFORE the terrain lookup because it is
;  the cheaper of the two and because it is what makes the lookup's
;  coordinate meaningful.
;  * THE TERRAIN, second. `col_map` reads the tile id out of the flat map and
;  LUTs it through m7x_terr to a terrain CLASS; blocking is a contiguous
;  class RANGE (water..mountain), which is why those two classes are
;  numerically adjacent in the generator. One range test, no set membership,
;  no table of exceptions.
;
; The clamp test also makes col_map's totality safe here: the probe has no
; bounds check and needs none, because this rail decides where to ask before it
; asks.
mxl_try_step:
    .a16
    .i16
    stx z:US_STEP_DX                ; the per-frame PIXEL delta is the same
    sty z:US_STEP_DY                ;   -1/0/+1: one px a frame for eight frames
    ; ---- the candidate tile = (camera tile) + delta ----------------------
    lda z:US_CAM_PX
    .repeat 3
        lsr                         ; px -> tile (MXL_TILE_PX = 8)
    .endrepeat
    clc
    adc z:US_STEP_DX
    sta z:MXL_CAND_TX
    lda z:US_CAM_PY
    .repeat 3
        lsr
    .endrepeat
    clc
    adc z:US_STEP_DY
    sta z:MXL_CAND_TY
    ; ---- the clamp box ---------------------------------------------------
    ; Unsigned compares, and that covers the underflow arm too: a candidate
    ; that went below zero wrapped to $FFxx, which is above the max.
    lda z:MXL_CAND_TX
    cmp #MXL_CLAMP_MIN
    bcc @blocked
    cmp #(MXL_CLAMP_MAX + 1)
    bcs @blocked
    lda z:MXL_CAND_TY
    cmp #MXL_CLAMP_MIN
    bcc @blocked
    cmp #(MXL_CLAMP_MAX + 1)
    bcs @blocked
    ; ---- the terrain -----------------------------------------------------
    ; col_map takes world PIXELS, so the candidate tile goes back up by the
    ; tile size. The tile ORIGIN is what gets asked about; the centre would do
    ; as well, since the answer is the same for all eight pixels.
    lda z:MXL_CAND_TX
    .repeat 3
        asl
    .endrepeat
    sta z:CM_PX
    lda z:MXL_CAND_TY
    .repeat 3
        asl
    .endrepeat
    sta z:CM_PY
    ; WIDTH-RISK: col_map_at is a CROSS-FILE contract — entered A16/I16 and
    ; EXITING A8/I16, deliberately, because the flag it returns is a byte. The
    ; `rep #$20` below is a forced widening back to this routine's width and
    ; must not be dropped: an A8 `cmp #imm` would assemble as two bytes while
    ; the following compares expect three, and the CPU would execute the stray
    ; operand byte. Width-check cannot see across the file boundary in either
    ; direction, so this marker is what carries the contract.
    jsr col_map_at
    rep #$20
    .a16
    and #$00FF                      ; A = the terrain class, zero-extended
    cmp #M7X_TERR_BLOCKED_MIN
    bcc @walkable                   ; below the range -> grass, path, town
    cmp #(M7X_TERR_BLOCKED_MAX + 1)
    bcs @walkable                   ; above it -> the town landmarks
@blocked:
    .a16
    .i16
    ; Water, mountain, or the world's edge. Clear the staged deltas so a later
    ; direction in this frame's dispatch cannot inherit them, and leave
    ; US_STEP_ACTIVE alone — it is already zero, and it is what the caller
    ; branches on to decide whether to fall through to the next held axis.
    stz z:US_STEP_DX
    stz z:US_STEP_DY
    rts
@walkable:
    .a16
    .i16
    lda #MXL_STEP_FRAMES
    sta z:US_STEP_REMAIN
    lda #1
    sta z:US_STEP_ACTIVE
    rts

; --- mxl_apply_camera: the camera -> the streamer AND the picture -----------
; CONTRACT mxl_apply_camera
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the Mode-7 camera words written from the walker's position
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame from the scene tick, during active display,
;             after mxl_tick has committed this frame's position
;   tail:     rts
;
; TWO CONSUMERS, ONE POSITION, and that is the whole point of doing it in one
; place:
;
;  * ES_M7ORG is what mode7_stream reads to decide which world rows and
;  columns must enter the VRAM window. It gets the TRUE camera — the tile
;  ORIGIN, which is the coordinate the streamer's window arithmetic is in.
;  * m7a_set_center is what puts the picture on screen. It gets the CENTRE of
;  that same tile, so the tile the walk machine tests is the tile drawn under
;  the avatar's body — see the pivot block above for the measurement.
;
; Getting these from one variable is what stops "where the world thinks you
; are" and "where the picture says you are" drifting apart, which is a class of
; bug that looks like a streaming bug and is not. The half-tile below is the
; only difference between the two, and it is a difference of FRAMING within one
; tile rather than of position: both describe the same cell.
mxl_apply_camera:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mxl_apply_camera"
    lda z:US_CAM_PX
    sta z:ES_M7ORG + 0              ; M7X px — the streamer's camera
    lda z:US_CAM_PY
    sta z:ES_M7ORG + 2              ; M7Y px
    lda z:US_CAM_PX
    clc
    adc #MXL_PIVOT_DX               ; the tile's middle, not its left edge
    tax
    lda z:US_CAM_PY
    clc
    adc #MXL_PIVOT_DY               ; ...and its middle less the BG/OBJ line
    tay                             ;    bias, so her body lands ON the cell
    jsr ::m7a_set_center            ; pivot -> M7X/M7Y + the screen origin
    rts
