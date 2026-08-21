; =============================================================================
; scenes/world.asm — the whole game: read the d-pad, move the camera
; =============================================================================
; The whole of the gameplay is eleven instructions: four button tests, each
; adding or subtracting SCR_SPEED from one camera word, then a scroll and a
; sprite.
;
; THE CAMERA IS scroller_bg's DP CLAIM, not this scene's state, because the
; routine that READS it is that feature's VBlank commit (pfs_bg's division,
; unchanged). This scene WRITES it, which is the same shape split_v_fight's
; director has with `ES_SV_SPREAD` / `ES_SV_MID`.
;
; NO CLAMP, deliberately. The camera is bounded nowhere at all, and a 32x32 map
; on a 10-bit scroll latch wraps every 256 px on both axes — so scrolling
; forever is a torus, not a wall. That is a real property of the rail and the
; test drives past the wrap in both directions rather than stopping at the
; first screenful.

.scope world

; =============================================================================
; THE PROTOTYPE TIMEBASE — `-D SF_TICK=n`, DEFAULT OFF (docs/96 §4)
; =============================================================================
; The architectural question docs/95 §5 leaves open is whether the 185 sites
; that assume "one tick is one frame" are hard BECAUSE THERE ARE 185 OF THEM,
; or hard BECAUSE THEY ARE WRITTEN IN THE WRONG UNIT. If game logic were
; expressed against a DECLARED TICK, region compensation would be a property
; of the tick generator instead of 185 call sites — the same move docs/95 §5.3
; proposes for scanline coverage.
;
; This rail is where that is tested, and it was chosen for three reasons:
;   * it is the smallest rail in the tree. The whole of its motion is two
;     words, so a timebase change touches one routine and the oracle can see
;     it exactly (tools/rate_oracle.py reads the scroller at 0.83208 with a
;     first-half/second-half spread of ZERO — a 0.1% change is unmissable);
;   * its step is an INTEGER 2 px/frame, which is docs/95's HARD class, not
;     the 33 8.8 rate accumulators that scale cleanly. A scheme that cannot
;     fix the simplest integer rail cannot fix 30 integer countdowns;
;   * nothing else composes scroller_bg, so the blast radius is one ROM.
;
; WITH NO DEFINE, EVERY LINE BELOW IS ABSENT AND `TB_ADD`/`TB_SUB` EXPAND TO
; THE ORIGINAL IMMEDIATES. `build/scroller.sfc` holds
; f34ae672bc8b98e034172ba1e28acbbf either way.
;
; SF_TICK values:
;   1  lump      6 logic ticks per 5 frames on PAL — the scheme docs/95 §4
;                refuted on the TIGHTEST rail's budget. Here the budget is
;                not the obstacle, so what this measures is its PARITY.
;   2  accum6_5  one tick per frame; the per-frame step scaled by 6/5 in 8.8
;                with the fraction carried between frames.
;   3  accum     the same, scaled by the MEASURED frame ratio 1.201804
;                (60.09879 / 50.00714 fps) rather than by 6/5. The difference
;                between 2 and 3 is the whole reason 6/5 is not the right
;                constant, and it is worth 0.15%.
;   4  intscale  one tick per frame, step scaled and ROUNDED TO AN INTEGER —
;                docs/95 §5.2's class B/C, "no correct x5/6, only a rounding
;                policy". round(2 x 1.2018) = 2.
;   5  intup     the same with the rounding taken UP: 3.
.ifdef ::SF_TICK

; One pixel in the kit's 8.8 rate format. Written as a shift, not as 256:
; `no_literals` reads an operand's numeric tokens, and this rail's WRAM claims
; start at 512, so a bare decimal step constant would land inside
; ES_OAM_SHADOW and be refused. Building every constant out of shifts and
; small factors keeps the arithmetic visible AND the gate satisfied.
TB_ONE_PX   = 1 << 8
TB_PAL_BIT  = 1 << 4                    ; $213F bit 4: 1 on a PAL console

; The lump cadence: one frame in five runs the tick twice.
TB_LUMP_PERIOD = 5

; The region ratio, as a rational. 1.201804 = (21477270 / 357368) fps NTSC
; TICK: ok — this is the REGION COMPENSATOR's own derivation, and it is the
;   one site where naming the NTSC frame beside the PAL one is the point
;   rather than the defect. `make tick-check` flagged this comment on its
;   first run against this file, which is the gate doing its job.
; over (21281370 / 425568) fps PAL — the master-clock rates read from Mesen2
; `Core/SNES/SnesConsole.cpp:209` and the frame lengths measured by
; tools/rate_oracle.py in both regions. 6/5 = 1.2 is the same number rounded,
; and the 0.15% between them is measurable.
TB_RATIO_NUM = 1201804
TB_RATIO_DEN = 1000000

TB_STEP_NTSC = SCR_SPEED * TB_ONE_PX
.if ::SF_TICK = 2
TB_STEP_PAL  = SCR_SPEED * TB_ONE_PX * 6 / 5
.else
TB_STEP_PAL  = SCR_SPEED * TB_ONE_PX * TB_RATIO_NUM / TB_RATIO_DEN
.endif
; The integer forms: nearest (x2 + 1) / 2, and up.
TB_INT_PAL   = (SCR_SPEED * 2 * TB_RATIO_NUM / TB_RATIO_DEN + 1) / 2
TB_INT_UP    = (SCR_SPEED * TB_RATIO_NUM + TB_RATIO_DEN - 1) / TB_RATIO_DEN

; --- tb_arm: the region flag, once, at scene enter -------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; $213F is the PPU status byte; bit 4 is the console's own region line and is
; SET on PAL. docs/95 §1.3 measured it in-ROM: $03 under SF_REGION=ntsc, $13
; under pal. Reading it also resets the OPHCT/OPVCT flip-flops, which is why
; the three existing sites in this tree read it at all and why reading it once
; at enter — rather than every frame — costs nothing anyone is using.
tb_arm:
    .a16
    .i16
    stz z:US_TB_ACC
    stz z:US_TB_PH
    stz z:US_TB_REG
    stz z:US_TB_ST
    sep #$20
    .a8
    lda a:$213F
    and #TB_PAL_BIT
    beq @done
    rep #$20
    .a16
    lda #1
    sta z:US_TB_REG
    sep #$20
    .a8
@done:
    .a8
    .i16
    rep #$20
    .a16
    rts

; --- tb_frame: publish this frame's step; return the tick count ------------
; In/out: A16/I16, DB=0. Out: A = logic ticks to run this frame. Clobbers A.
;
; THIS ROUTINE IS THE WHOLE PROPOSAL. Everything downstream keeps saying "move
; one step", and what a step IS becomes a property of the generator. On NTSC
; every scheme publishes exactly today's constant, which is why the NTSC
; picture cannot move.
tb_frame:
    .a16
    .i16
    lda #SCR_SPEED
    sta z:US_TB_ST                  ; the NTSC step, and the default answer
    lda z:US_TB_REG
    bne @pal
    lda #1                          ; NTSC: one tick, today's step
    rts
@pal:
    .a16
    .i16
.if ::SF_TICK = 1
    ; ---- lump: 6 ticks per 5 frames -------------------------------------
    ; The tick is ATOMIC — this kit has no resumable tick — so the sixth one
    ; arrives as a DOUBLE FRAME rather than as a smooth 1.2. On this rail the
    ; doubled frame costs one more pass through eleven instructions; on the
    ; tightest rail docs/95 §4.3 measured the same shape at 121% of a PAL
    ; frame in work alone. Same scheme, different budget.
    lda z:US_TB_PH
    inc a
    cmp #TB_LUMP_PERIOD
    bcc @keep
    stz z:US_TB_PH
    lda #2
    rts
@keep:
    .a16
    .i16
    sta z:US_TB_PH
    lda #1
    rts
.elseif ::SF_TICK = 4
    ; ---- intscale: the rounding policy, and nothing else -----------------
    lda #TB_INT_PAL
    sta z:US_TB_ST
    lda #1
    rts
.elseif ::SF_TICK = 5
    lda #TB_INT_UP
    sta z:US_TB_ST
    lda #1
    rts
.else
    ; ---- accumulator: one tick, a fractional step, the fraction carried --
    ; acc += step(8.8); this frame's pixels = acc >> 8; acc keeps the low
    ; byte. Over any window the published pixels sum to the exact scaled
    ; distance, which is the property an integer rounding cannot have.
    lda z:US_TB_ACC
    clc
    adc #TB_STEP_PAL
    pha
    and #TB_ONE_PX - 1
    sta z:US_TB_ACC                 ; the carried fraction
    pla
    xba                             ; high byte -> low: the whole pixels
    and #TB_ONE_PX - 1
    sta z:US_TB_ST
    lda #1
    rts
.endif

.macro TB_ADD
    adc z:US_TB_ST
.endmacro
.macro TB_SUB
    sbc z:US_TB_ST
.endmacro

.else                                   ; ---- no SF_TICK: today's rail ----
.macro TB_ADD
    adc #SCR_SPEED
.endmacro
.macro TB_SUB
    sbc #SCR_SPEED
.endmacro
.endif

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr scr_arm                     ; CHR, palette, the built map, the camera
    jsr scr_obj_arm                 ; OBJ CHR, palette, OBSEL, tile + attr
    jsr scr_obj_draw                ; stage the rider BEFORE the first NMI, so
                                    ; frame 0 commits a real entry rather than
                                    ; whatever oam_park_all left
    stz z:US_FRAMES
.ifdef ::SF_TICK
    jsr tb_arm                      ; the region flag, once (docs/96 §4)
.endif
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE, TM, BG1SC and BG12NBA are the `scene_writes` this scene owns on
    ; scroller_bg's behalf (see that feature.toml's attribution note). Every
    ; value comes from the allocator's emitted encoding; none is narrated from
    ; a VRAM address here.
    sep #$20
    .a8
    lda #1                          ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
    lda #ES_V_SCR_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_SCR_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #((1 << 4) | 1)             ; TM: OBJ + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A.
tick:
    .a16
    .i16
    inc z:US_FRAMES
.ifdef ::SF_TICK
    jsr tb_frame                    ; this frame's step -> US_TB_ST; A = ticks
@tb_again:
    .a16
    .i16
    pha
    jsr scroll_from_pad
    pla
    dec a
    bne @tb_again
.else
    jsr scroll_from_pad
.endif
    jsr scr_obj_draw                ; re-staged every frame — see that routine
    rts

; --- scroll_from_pad: the d-pad moves the world ----------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; LEVEL-TRIGGERED, not edge: the pad is held to scroll, so this reads
; ES_INP_CUR and never ES_INP_PRESS. Opposite directions are both applied
; rather than being made exclusive — holding Left+Right nets to zero because
; the two deltas cancel, not because a branch picked one.
scroll_from_pad:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:ES_SCR_CAM + 0
    clc
    TB_ADD
    sta z:ES_SCR_CAM + 0
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:ES_SCR_CAM + 0
    sec
    TB_SUB
    sta z:ES_SCR_CAM + 0
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:ES_SCR_CAM + 2
    clc
    TB_ADD
    sta z:ES_SCR_CAM + 2
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:ES_SCR_CAM + 2
    sec
    TB_SUB
    sta z:ES_SCR_CAM + 2
@no_up:
    .a16
    .i16
    rts

; --- exit -----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. There is nowhere to go —
; this rail has one scene and no edges — so the handler exists to satisfy
; scene_mgr's table and re-parks what this scene armed, which is the exit
; contract every rail's scene owes whether or not it is ever reached.
exit:
    .a16
    .i16
    jsr oam_park_all
    rts

.endscope
