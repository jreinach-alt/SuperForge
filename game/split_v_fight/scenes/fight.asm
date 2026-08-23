; =============================================================================
; scenes/fight.asm — the arena, and the camera director that drives the split
; =============================================================================
; THE WHOLE MECHANISM, in one place:
;
;   dx      = |fx2 - fx1|                        the fighter separation
;   target  = clamp((dx - MERGE_DX) / 2, 0, MAX) the divergence that would keep
;                                                each fighter as far inside its
;                                                own half as a single view had
;   spreadf += step toward target                eased, 8.8
;   spread   = spreadf >> 8                      the integer the feature reads
;   mid      = (fx1 + fx2)/2 - 128               the shared viewpoint
;
; and split_v_bg turns (mid, spread) into cam A, cam B and the divider band.
;
; Below MERGE_DX the target is ZERO, so the two cameras converge on `mid` and
; the halves become the same picture. That is the seam disappearing — not a
; special case, just the target reaching its floor.

.scope fight

; =============================================================================
; THE REGION-CORRECT UNITS — an arc takes TWO scales, and this one has a
; combat window hanging off it
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). A VELOCITY is px per frame and scales by r. A GRAVITY is
; px per frame SQUARED and scales by r SQUARED. Together they leave
; apex = v0^2/2g unchanged — and on THIS rail the apex is a rule rather than a
; look: SV_SWING_VGATE says a swing misses a fighter whose height differs by
; 14 px, so the hop IS the defence. An arc flattened by 17% would quietly stop
; being one.
;
; TS_SCALED / TS_SCALE are tick_scale's build-time twin of TS_STEP's PAL arm,
; which is what lets a per-frame-SQUARED quantity be scaled TWICE (once here
; into the base, once by the macro). They are NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced, and the
; `+ DEN/2` rounding is the run-time arm's own, so the two cannot disagree by
; a count.

; --- the four rates on one r ----------------------------------------------
; SV_WALK_SPD and SV_SWING_LUNGE are still the numbers to reach for when
; tuning how this rail feels; what changed is that they are RATES rather than
; per-frame immediates. They keep separate pairs though both are 2 px today.
TS_WALK_BASE  = SV_WALK_SPD * TS_ONE
TS_LUNGE_BASE = SV_SWING_LUNGE * TS_ONE
; ONE ANIMATION UNIT. The DIVIDER (sv_anim_meta's per-table rate) is untouched
; — scaling a small integer divider is docs/95 §5.2's class C and has no
; correct answer — so what is scaled is the amount the CLOCK advances by.
TS_ANIM_BASE  = TS_ONE
; THE DIVIDER'S EASE, AND WHY ITS BASE IS A HALF UNIT. SV_SPR_STEP is already
; an 8.8 rate (0.75 px/frame = 192 counts), so the natural base would be
; 192 * TS_ONE = 49,152 — past tick_scale's TS_BASE_MAX of 42,000, which is
; the point where `base * TS_GAIN_NUM` would wrap ca65's 32-bit expression
; arithmetic. That assert exists to be believed, so the base is expressed in
; HALF counts (96 * TS_ONE = 24,576) and the published step is doubled where
; it is stored. The average is exact either way; what the halving costs is one
; bit of granularity in a smoothing accumulator, which is nothing a divider
; that settles on an integer target can see.
.assert (SV_SPR_STEP / 2) * 2 = SV_SPR_STEP, error, "SV_SPR_STEP is odd — the half-unit timebase base would lose a count per frame"
TS_SPREAD_BASE = (SV_SPR_STEP / 2) * TS_ONE

; --- gravity: the r^2 site, and the only one on this rail ------------------
; TS_STEP applies exactly one r, so the other one goes into the BASE — on the
; PAL arm only, which is why the tick branches on ES_RGN_PAL BEFORE the macro
; instead of after it. Both arms share one accumulator: a console cannot
; change region, so only one of them is ever taken.
TS_GRAV_BASE   = SV_GRAV * TS_ONE
TS_SCALED TS_GRAV_BASE_R, TS_GRAV_BASE

; --- the take-off: one r, chosen once at enter -----------------------------
TS_SCALED SV_JUMP_V0_R, SV_JUMP_V0

; --- THE CLAIM, ASSERTED AT BUILD TIME ------------------------------------
; "The apex is preserved" is the whole reason gravity gets r^2 rather than r,
; and it is cheap to check rather than assume: apex = v0^2 / 2g in the 8.8
; counts US_JMP is kept in, computed for each region from the constants each
; region actually runs. SV_GRAV_PAL is the whole-count part of the PAL step
; TS_STEP publishes (base * r^2, rounded down at the count), which is what the
; integrator adds.
;
; The bound is +/- 1/16. That is not a tolerance the arc needs — the measured
; difference is under 1% — it is a TRIPWIRE: scale the wrong constant, or
; scale gravity once instead of twice, and the apex moves by ~17% and this
; refuses the build with the reason on it rather than shipping a flattened
; hop that only a playtest would find.
SV_GRAV_PAL   = TS_SCALE(TS_GRAV_BASE_R) / TS_ONE
SV_APEX_NTSC  = SV_JUMP_V0 * SV_JUMP_V0 / (2 * SV_GRAV)
SV_APEX_PAL   = SV_JUMP_V0_R * SV_JUMP_V0_R / (2 * SV_GRAV_PAL)
.assert SV_APEX_PAL <= SV_APEX_NTSC + SV_APEX_NTSC / 16, error, "the PAL jump apex is more than 6% ABOVE the NTSC one — the velocity/gravity region scales are not r and r^2"
.assert SV_APEX_PAL >= SV_APEX_NTSC - SV_APEX_NTSC / 16, error, "the PAL jump apex is more than 6% BELOW the NTSC one — the velocity/gravity region scales are not r and r^2, and a flattened arc stops clearing SV_SWING_VGATE"

; =============================================================================
; SV_ANIM_STEP — one fighter's animation clock, one frame
; =============================================================================
; The RATE and the LENGTH come from sv_anim_meta rather than being pasted in as
; macro operands, so the numbers that bound the wrap live beside the frames
; they bound.
;
; THE RESET DISCIPLINE IS THE CALLER'S: every anim-state change zeroes BOTH the
; tick and the step, or a 1-step table gets indexed at step 3 by a stale
; 4-step counter and reads past its end. `set_state` below is the only writer
; of US_AST for exactly that reason.
;
; WIDTH-RISK: A16/I16 in AND out — this macro contains no sep/rep at all, so it
; cannot leak a width to its caller. In: X = the fighter's pair index. Clobbers
; A, Y, US_TILE, US_ATTR (draw scratch, dead until the draw runs later in the
; same tick).
.macro SV_ANIM_STEP
    .local sv_wrap, sv_done
    .assert SV_META_STRIDE = 2, error, "SV_ANIM_STEP's single 16-bit meta read assumes a 2-byte stride"
    lda z:US_AST, x
    asl a                           ; state * SV_META_STRIDE
    phx                             ; the pair index, while X indexes the blob
                                    ; (long,Y is not an addressing mode the
                                    ;  65816 has — only long,X)
    tax
    lda f:sv_anim_meta_bin, x       ; one 16-bit read: len in low, rate in high
    and #$00FF
    sta z:US_TILE                   ; the table's length
    lda f:sv_anim_meta_bin, x
    xba
    and #$00FF
    sta z:US_ATTR                   ; ...and its frame-rate divider
    plx
    ; THE CLOCK ADVANCES BY US_TSA, NOT BY ONE. That is this rail's answer to
    ; docs/95 §5.2's class C: a frame-rate divider is a small integer with no
    ; correct x5/6, so the table's rate is left alone and what the clock
    ; ADVANCES BY is scaled instead — 1 unit per NTSC frame, 1.2018 per PAL
    ; frame, the fraction carried by tick_scale. On NTSC US_TSA is exactly 1
    ; every frame, so this is `inc a` in behaviour.
    lda z:US_ATK, x
    clc
    adc z:US_TSA
    sta z:US_ATK, x
    cmp z:US_ATTR
    bcc sv_done                     ; not time for the next step yet
    ; CARRY THE OVERSHOOT rather than zeroing. On NTSC the clock arrives at
    ; the divider EXACTLY (it steps by 1 from 0 and set_state resets it on
    ; every state change), so tick - rate = 0 and this is the `lda #0` it
    ; replaces; on PAL a 2-unit frame can cross the divider by one, and
    ; dropping that one is a bias nothing downstream can see.
    sec
    sbc z:US_ATTR
    sta z:US_ATK, x
    lda z:US_AFR, x
    inc a
    cmp z:US_TILE
    bcc sv_wrap
    lda #0                          ; past the end: back to step 0
sv_wrap:
    .a16
    .i16
    sta z:US_AFR, x
sv_done:
    .a16
    .i16
.endmacro

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr sv_arm                      ; stage + bevel VRAM, layers, window recipe
    jsr sv_obj_arm                  ; OBSEL (forced-blank-only)
    ; ---- the round's own state, and both fighters' ------------------------
    ; Power-on DP is RANDOM (rule 5), so these stores ARE the write-before-read
    ; contract for every word state.toml declares — not defensive
    ; initialisation. The exceptions are the six write-before-read-PER-CALL
    ; scratch words (US_PCUR, US_PPRESS, US_TILE, US_ATTR, US_OY, US_SLOT),
    ; deliberately NOT zeroed here: zeroing them would disarm the uninit-read
    ; detector on exactly the words whose contract it can check.
    ;
    ; FIRST, so the stance block below can OVERRIDE the spawn marks. Written
    ; the other way round it silently pinned every -DSV_HOLD build to the same
    ; separation, and four pixel-identity cases went red at once — which is
    ; the proof builds earning their keep.
    jsr round_arm
    ; ---- the fighters' opening stance ------------------------------------
.ifdef SV_HOLD
    ; A static proof build: freeze the pair symmetric about centre. A negative
    ; SV_HOLD puts fighter 1 to the RIGHT of fighter 2, which is the crossed
    ; state — the same code path, reached by arithmetic rather than by a flag.
    ; Sign convention: a POSITIVE hold is the UNCROSSED
    ; state, fighter 1 (red) on the left. A negative hold swaps them, which is
    ; the crossed variant -- reached by arithmetic, through the same code path,
    ; so the swap is exercised rather than simulated.
    lda #(SV_ARENA_MID - SV_HOLD)
    sta z:US_FX1
    lda #(SV_ARENA_MID + SV_HOLD)
    sta z:US_FX2
.endif
; ...and the SHIPPING build has no stance block at all: round_arm's spawn marks
; are the only marks, so ROUND ONE OPENS EXACTLY WHERE EVERY LATER ROUND DOES.
; It had a +-20 override here and every subsequent round used round_arm's +-30,
; which is invisible in play and is exactly what the gallery clip's loop cut
; measures: the take opens on round one's FIGHT beat and closes on round two's,
; and the two ends stood 10 px apart. Measured — the seam is the check.
    stz z:US_SPREADF
    stz z:US_CROSSED
    stz z:ES_SV_SPREAD
    stz z:ES_SV_MID
    ; ---- the timebase's ten words, and the region-selected take-off ------
    ; Power-on DP is RANDOM (rule 5), so these stores ARE the write-before-
    ; read contract for every one of them.
    stz z:US_TSW_ACC
    stz z:US_TSW
    stz z:US_TSL_ACC
    stz z:US_TSL
    stz z:US_TSS_ACC
    stz z:US_TSS
    stz z:US_TSA_ACC
    stz z:US_TSA
    stz z:US_TSG_ACC
    stz z:US_TSG
    lda z:ES_RGN_PAL
    beq :+
    lda #SV_JUMP_V0_R
    bra :++
:   .a16
    .i16
    lda #SV_JUMP_V0                 ; today's constant, to the bit
:   .a16
    .i16
    sta z:US_VJUMP
.ifdef SV_HOLD
    ; A proof build: no countdown, because these ROMs exist to freeze ONE
    ; variable and a banner across the middle of the screen is a second one.
    lda #SV_R_LIVE
    sta z:US_RSTATE
.elseif .defined(SV_AUTODEMO)
    lda #SV_R_LIVE
    sta z:US_RSTATE
    ldx #0
    lda #SV_ST_WALK                 ; the demo only ever walks
    jsr set_state
    ldx #2
    lda #SV_ST_WALK
    jsr set_state
.endif
    jsr director                    ; derive mid/spread BEFORE the first NMI,
                                    ; so frame 0 commits a real camera pair
                                    ; rather than whatever the shadow held
    jsr sv_obj_draw
.ifdef SV_NOWIN
    jsr nowin_reference
.endif
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are the scene_writes this scene owns on split_v_bg's
    ; behalf (see that feature.toml's attribution note).
    sep #$20
    .a8
    lda #$01                        ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
.ifndef SV_NOWIN
    lda #$17                        ; TM: OBJ + BG1 + BG2 + BG3 on main
    sta a:$212C
.endif
    rep #$20
    .a16
    rts

.ifdef SV_NOWIN
; --- nowin_reference: the no-split control ---------------------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A.
;
; Window masking off and BG3 off the main screen: ONE camera, no divider. The
; seamlessness proof is that a merged split frame diffs to zero against this,
; which is only meaningful because this arm changes nothing else — same stage,
; same palettes, same sprite placement.
nowin_reference:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$212E                     ; TMW: no window masking at all
    lda #$13                        ; TM: OBJ + BG1 + BG2, BG3 dropped
    sta a:$212C
    rep #$20
    .a16
    rts
.endif

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
tick:
    .a16
    .i16
    ; ---- this frame's five region-correct steps, published once ----------
    ; BEFORE the variant gates, deliberately: the -DSV_HOLD proof builds skip
    ; the whole game body but still run `director`, whose spread EASE reads
    ; US_TSS, and a step word that stops being republished is a stale word
    ; waiting to be read. On NTSC each publishes the constant split_v.inc
    ; authored, to the unit, and the carried fraction stays 0 for ever.
    TS_STEP z:US_TSW_ACC, TS_WALK_BASE
    sta z:US_TSW
    TS_STEP z:US_TSL_ACC, TS_LUNGE_BASE
    sta z:US_TSL
    TS_STEP z:US_TSA_ACC, TS_ANIM_BASE
    sta z:US_TSA
    TS_STEP z:US_TSS_ACC, TS_SPREAD_BASE
    asl a                           ; half counts -> the 8.8 counts the ease
    sta z:US_TSS                    ;   accumulator is kept in
    ; Gravity is per-frame-SQUARED: the second r rides the BASE, so the arm
    ; is chosen BEFORE the macro rather than after it. ANONYMOUS LABELS, not
    ; `@cheap` ones: TS_STEP's `.local` labels are plain symbols, so expanding
    ; it between a `@label` and its use RESETS the cheap-local scope and the
    ; branch target goes undefined.
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:US_TSG_ACC, TS_GRAV_BASE_R
    bra :++
:   .a16
    .i16
    TS_STEP z:US_TSG_ACC, TS_GRAV_BASE
:   .a16
    .i16
    sta z:US_TSG
.ifdef SV_HOLD
    ; frozen: the director still runs so the spread EASES to its fixed point,
    ; which is what makes the held frame a settled state rather than frame 1
    ; of an animation. No clock either — a still that is the assertion has to
    ; be the same still on every host.
.elseif .defined(SV_AUTODEMO)
    jsr demo_walk
    ldx #0
    SV_ANIM_STEP
    ldx #2
    SV_ANIM_STEP
.else
    ; THE ORDER IS THE GAME: the round phase first (it gates input), then each
    ; fighter's own control and physics, then the swings — which read BOTH
    ; fighters' post-move positions, so a swing lands against where the
    ; defender actually is this frame rather than where it was last frame.
    jsr round_step
    ldx #0
    lda z:ES_INP_CUR
    sta z:US_PCUR
    lda z:ES_INP_PRESS
    sta z:US_PPRESS
    jsr fighter_step
    ldx #2
    lda z:ES_INP2_CUR
    sta z:US_PCUR
    lda z:ES_INP2_PRESS
    sta z:US_PPRESS
    jsr fighter_step
    ldx #0
    jsr swing_check
    ldx #2
    jsr swing_check
.endif
    jsr director
    jsr sv_obj_draw
    rts

; =============================================================================
; round_arm — both fighters back on their marks, full life, counting in
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; ONE ROUTINE FOR BOTH ENTRIES, and that is the point: the scene's enter and
; the KO's expiry must produce the SAME state, or the second round differs from
; the first in some word nobody set. A clip that loops on the round start would
; show it.
round_arm:
    .a16
    .i16
    lda #(SV_ARENA_MID - SV_SPAWN_DX)
    sta z:US_FX1
    lda #(SV_ARENA_MID + SV_SPAWN_DX)
    sta z:US_FX2
    lda #SV_R_COUNT
    sta z:US_RSTATE
    lda #SV_COUNT_LEN
    sta z:US_RTIMER
    ldx #0
    jsr round_arm_one
    ldx #2
    jsr round_arm_one
    rts

; --- round_arm_one: one fighter's half of that ----------------------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A.
round_arm_one:
    .a16
    .i16
    lda #SV_HP_MAX
    sta z:US_HP, x
    lda #0
    sta z:US_SWG, x
    sta z:US_SWH, x
    sta z:US_JMP, x
    sta z:US_JVEL, x
    sta z:US_HITT, x
    sta z:US_AST, x                 ; SV_ST_IDLE, written as the zero it is
    .assert SV_ST_IDLE = 0, error, "round_arm_one stores idle as a zero"
    sta z:US_ATK, x
    sta z:US_AFR, x
    rts

; =============================================================================
; round_step — the phase clock: COUNT -> LIVE -> KO -> COUNT
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; LIVE HAS NO TIMER. A round ends when a life bar empties, not when a clock
; runs out, so the only phases that count down are the two that are waiting for
; the picture to be read.
round_step:
    .a16
    .i16
    lda z:US_RSTATE
    cmp #SV_R_LIVE
    bne @timed
    rts
@timed:
    .a16
    .i16
    lda z:US_RTIMER
    dec a
    sta z:US_RTIMER
    bne @waiting
    lda z:US_RSTATE
    cmp #SV_R_COUNT
    bne @next_round
    lda #SV_R_LIVE                  ; ...FIGHT
    sta z:US_RSTATE
    rts
@next_round:
    .a16
    .i16
    jmp round_arm                   ; the KO pose has been read: go again
@waiting:
    .a16
    .i16
    rts

; --- exit -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
; Single-scene rail: nothing follows, but the window is disarmed anyway so the
; feature cannot leave a mask armed over a screen it no longer owns — the
; disarm discipline window_iris exists to enforce.
exit:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$212E                     ; TMW
    rep #$20
    .a16
    rts

; --- director: fighter distance -> the shared viewpoint and the divergence -
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Writes ES_SV_MID and ES_SV_SPREAD, which split_v_bg's VBlank commit turns
; into cam A, cam B and the divider band, and which split_v_obj reads to place
; each fighter against its own half's camera. One producer, three consumers,
; one frame -- so nothing can disagree about where the world is.
director:
    .a16
    .i16
    ; ---- mid = (fx1 + fx2)/2 - 128 ---------------------------------------
    lda z:US_FX1
    clc
    adc z:US_FX2
    lsr a                           ; (fx1+fx2)/2 -- both are 0..255, so the
                                    ; sum cannot overflow 16 bits
    sec
    sbc #SV_ARENA_MID
    and #$00FF                      ; the stage map is 256 px periodic
    sta z:ES_SV_MID
    ; ---- dx = |fx2 - fx1| ------------------------------------------------
    lda z:US_FX2
    sec
    sbc z:US_FX1
    bpl @have_dx
    eor #$FFFF
    inc a                           ; negate: the crossed case has fx1 > fx2,
                                    ; and the SPLIT depends on separation, not
                                    ; on which fighter is which
@have_dx:
    .a16
    .i16
    ; ---- target = clamp((dx - MERGE_DX)/2, 0, SPREAD_MAX) ----------------
    sec
    sbc #SV_MERGE_DX
    bpl @above_merge
    lda #0                          ; inside the merge distance: fully merged
    bra @have_target
@above_merge:
    .a16
    .i16
    lsr a                           ; half the excess
    cmp #(SV_SPREAD_MAX + 1)
    bcc @have_target
    lda #SV_SPREAD_MAX
@have_target:
    .a16
    .i16
    tax                             ; X = target, across the ease below
    ; ---- ease spreadf (8.8) toward the target ----------------------------
    ; The target is an INTEGER px; compare against spreadf's integer part so
    ; the ease settles exactly rather than hunting around the target by a
    ; fraction forever.
    lda z:US_SPREADF
    xba
    and #$00FF                      ; current integer spread
    stx z:ES_SV_SPREAD              ; provisional; overwritten below
    cmp z:ES_SV_SPREAD
    beq @settled
    bcc @ease_up
    ; ease down
    lda z:US_SPREADF
    sec
    sbc z:US_TSS
    bcs @store                      ; no underflow past zero
    lda #0
    bra @store
@ease_up:
    .a16
    .i16
    lda z:US_SPREADF
    clc
    adc z:US_TSS
@store:
    .a16
    .i16
    sta z:US_SPREADF
@settled:
    .a16
    .i16
    ; ---- the integer spread the feature reads ----------------------------
    lda z:US_SPREADF
    xba
    and #$00FF
    sta z:ES_SV_SPREAD
    rts

; =============================================================================
; fighter_step — one fighter, one frame: control, then physics, then the clock
; =============================================================================
; In/out: A16/I16, DB=0. X = the fighter's pair index (0 or 2). US_PCUR and
; US_PPRESS hold THIS fighter's pad. Clobbers A, Y.
;
; THE LOCKOUT LADDER IS THE COMBAT. A hit reaction outranks a swing, a swing
; outranks input, and both run to completion — which is what makes a swing a
; commitment rather than a per-frame damage tick, and what makes being hit
; cost the defender its turn.
; DECOMPOSED, and not for tidiness: the control block plus the physics plus the
; clock is well past a relative branch's 128-byte reach, so a single routine
; would need a jmp trampoline at every early exit. Three routines with plain
; `rts` exits say the same thing without the indirection (brawler's near-bail
; note, taken one step further).
fighter_step:
    .a16
    .i16
    lda z:US_FX1, x
    sta z:US_FX0                    ; where this fighter began the frame
    jsr fighter_control
    jsr jump_step
    jsr clamp_fighter
    jsr pick_state
    SV_ANIM_STEP
    rts

; --- fighter_control: the lockout ladder ----------------------------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A, Y.
fighter_control:
    .a16
    .i16
    lda z:US_HITT, x
    beq @swinging
    dec a
    sta z:US_HITT, x
    bne @done                       ; still reacting
    lda z:US_HP, x
    beq @done                       ; ...out: the KO pose stays put
    lda #SV_ST_IDLE
    jmp set_state
@swinging:
    .a16
    .i16
    lda z:US_SWG, x
    beq @free
    dec a
    sta z:US_SWG, x
    jsr swing_lunge                 ; the blade carries the body forward
    lda z:US_SWG, x
    bne @done
    lda #SV_ST_IDLE                 ; the swing is over
    jmp set_state
@free:
    .a16
    .i16
    ; ---- input, and ONLY while the round is live -------------------------
    ; During the count and after a KO the pads are dead. A fighter that could
    ; walk during "3, 2, 1" would be past its opponent before FIGHT, and the
    ; round-start frame the clip loops on would not be the frame the round
    ; started from.
    lda z:US_RSTATE
    cmp #SV_R_LIVE
    bne @done
    jmp fighter_input
@done:
    .a16
    .i16
    rts

; --- fighter_input: attack, jump, walk ------------------------------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A, Y.
fighter_input:
    .a16
    .i16
    lda z:US_PPRESS
    and #JOY_A
    beq @jump_test
    lda #SV_SWING_LEN               ; a swing starts, and locks out the rest
    sta z:US_SWG, x
    lda #0
    sta z:US_SWH, x                 ; a new swing re-arms the one-hit latch
    lda #SV_ST_ATK
    jmp set_state
@jump_test:
    .a16
    .i16
    lda z:US_JMP, x
    ora z:US_JVEL, x
    bne @done                       ; already airborne: no second jump, and no
                                    ;   walking either (see below)
    lda z:US_PPRESS
    and #(JOY_B | JOY_UP)
    beq @walk
    lda z:US_VJUMP
    sta z:US_JVEL, x
    lda #SV_ST_JUMP
    jmp set_state                   ; the take-off frame does not also walk
@walk:
    .a16
    .i16
    ; GROUND ONLY. A hop is a commitment: it clears a swing's vertical gate,
    ; and paying for that with your footing is what makes it a decision. It
    ; also gives the jump a testable invariant — a fighter lands on the x it
    ; left from.
    lda z:US_PCUR
    and #JOY_LEFT
    beq :+
    lda z:US_FX1, x
    sec
    sbc z:US_TSW
    sta z:US_FX1, x
:   .a16
    .i16
    lda z:US_PCUR
    and #JOY_RIGHT
    beq @done
    lda z:US_FX1, x
    clc
    adc z:US_TSW
    sta z:US_FX1, x
@done:
    .a16
    .i16
    rts

; --- jump_step: the arc, in 8.8 -------------------------------------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A.
;
; ASCENT, APEX, DESCENT AND THE LANDING ARE ONE INTEGRATION, and the landing is
; the arm that matters: height goes to EXACTLY zero and the velocity with it,
; so a fighter that has landed is byte-identical to one that never jumped. A
; landing that merely clamped the height would leave a velocity behind and the
; next frame would sink through the floor.
jump_step:
    .a16
    .i16
    lda z:US_JMP, x
    ora z:US_JVEL, x
    bne @airborne
    rts                             ; grounded and still: nothing to integrate
@airborne:
    .a16
    .i16
    lda z:US_JMP, x
    clc
    adc z:US_JVEL, x
    sta z:US_JMP, x
    bmi @landed                     ; height went negative: through the floor
    lda z:US_JVEL, x
    sec
    sbc z:US_TSG
    sta z:US_JVEL, x
    rts
@landed:
    .a16
    .i16
    lda #0
    sta z:US_JMP, x
    sta z:US_JVEL, x
    lda z:US_HITT, x                ; a fighter landing out of a hit reaction
    bne @done                       ;   keeps reacting; the ladder still holds
    lda z:US_SWG, x
    bne @done
    lda #SV_ST_IDLE
    jsr set_state
@done:
    .a16
    .i16
    rts

; --- swing_lunge: the blade carries the body forward ----------------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A, Y.
;
; The pack's character sheets have NO attack animation — its own row map is
; idle / run / jump-idle / jump-run / turn / hit / death — so the attack here
; is a lunge read: a braced wind-up, a hard forward lean and MOTION, with the
; impact sold by the defender playing the sheet's real `hit` row. The forward
; travel is the half of that the poses cannot supply.
swing_lunge:
    .a16
    .i16
    lda z:US_SWG, x
    cmp #SV_SWING_FIRST
    bcc @done                       ; the window has closed
    cmp #(SV_SWING_LAST + 1)
    bcs @done                       ; ...or has not opened yet
    jsr other_fx
    cmp z:US_FX1, x
    bcc @leftward
    lda z:US_FX1, x                 ; the opponent is to the right
    clc
    adc z:US_TSL
    sta z:US_FX1, x
    rts
@leftward:
    .a16
    .i16
    lda z:US_FX1, x
    sec
    sbc z:US_TSL
    sta z:US_FX1, x
@done:
    .a16
    .i16
    rts

; --- other_fx: the OPPONENT's world x -------------------------------------
; In/out: A16/I16, DB=0. X = this fighter's pair index. Out: A = the other
; fighter's x; X unchanged. Clobbers A.
;
; The two indices are 0 and 2, so the opposite one is an EOR rather than a
; subtraction — and doing it twice restores X without spending a register or
; the stack.
other_fx:
    .a16
    .i16
    txa
    eor #2
    tax
    lda z:US_FX1, x
    pha
    txa
    eor #2
    tax
    pla
    rts

; --- set_state: change a fighter's animation, resetting its clock ---------
; In/out: A16/I16, DB=0. A = the new state, X = the fighter's pair index.
; Clobbers A.
;
; THE ONLY WRITER OF US_AST, and that is the whole point: SV_ANIM_STEP indexes
; a table whose LENGTH comes from the state, so a state change that left a
; stale step index behind would read past a short table's end. Re-entering the
; state a fighter is already in does NOT reset — or a fighter holding right
; would restart its walk cycle every frame and never appear to move its legs.
set_state:
    .a16
    .i16
    cmp z:US_AST, x
    beq @same
    sta z:US_AST, x
    lda #0
    sta z:US_ATK, x
    sta z:US_AFR, x
@same:
    .a16
    .i16
    rts

; --- pick_state: idle or walk, when nothing outranks them -----------------
; In/out: A16/I16, DB=0. X = the fighter's pair index. Clobbers A.
;
; The ladder again, read the other way: a fighter in a hit reaction, a swing or
; the air is already in the state those put it in, and this only chooses
; between the two the FLOOR offers.
;
; WALKING IS "DID IT MOVE", NOT "IS A DIRECTION HELD". The distinction is
; visible: a fighter holding LEFT against the arena wall is going nowhere, and
; gating on the pad would have it run on the spot there forever. Comparing the
; post-clamp position against the frame's own starting one asks the picture's
; question instead of the pad's — and it cost a real test, which held LEFT into
; the wall and required the picture to go still.
pick_state:
    .a16
    .i16
    lda z:US_HITT, x
    bne @done
    lda z:US_SWG, x
    bne @done
    lda z:US_HP, x
    beq @done                       ; KO'd: the pose is the KO
    lda z:US_JMP, x
    ora z:US_JVEL, x
    beq @grounded
    lda #SV_ST_JUMP
    jmp set_state
@grounded:
    .a16
    .i16
    lda z:US_FX1, x
    cmp z:US_FX0
    beq @idle                       ; stood still, or pinned to a wall
    lda #SV_ST_WALK
    jmp set_state
@idle:
    .a16
    .i16
    lda #SV_ST_IDLE
    jmp set_state
@done:
    .a16
    .i16
    rts

; --- clamp_fighter: hold a fighter inside the arena walls -----------------
; In/out: A16/I16, DB=0. X = 0 for fighter 1, 2 for fighter 2. Clobbers A.
;
; The clamp is what makes the ADVERSARIAL input case safe: holding a direction
; into a wall must stop the fighter, not wrap it. Both fx values are treated as
; unsigned 0..255, so an underflow past SV_ARENA_LO shows up as a very large
; number -- which the HIGH comparison catches first. Order matters here.
clamp_fighter:
    .a16
    .i16
    lda z:US_FX1, x
    cmp #(SV_ARENA_HI + 1)
    bcc @lo
    ; either past the right wall or wrapped below zero; both land here
    cmp #$8000
    bcc @hi_clamp
    lda #SV_ARENA_LO                ; wrapped negative -> left wall
    sta z:US_FX1, x
    rts
@hi_clamp:
    .a16
    .i16
    lda #SV_ARENA_HI
    sta z:US_FX1, x
    rts
@lo:
    .a16
    .i16
    cmp #SV_ARENA_LO
    bcs @done
    lda #SV_ARENA_LO
    sta z:US_FX1, x
@done:
    .a16
    .i16
    rts

; The clamp indexes the two fighters as US_FX1[x], x = 0 or 2. That is only
; valid while the allocator packs them adjacent and in that order -- which it
; does today, but packing order is the ALLOCATOR's to choose, not this file's
; to assume. Assert it rather than inherit it: if a future claim reorders the
; DP block, this stops the build instead of clamping the wrong fighter.
; (Every OTHER per-fighter word is declared `u16[2]@dp` — one claim, contiguous
; by construction — precisely so this assertion does not have to be repeated
; nine more times. fx1/fx2 stay scalars because their symbol names are read by
; the tests and by the gallery drive.)
.assert US_FX2 = US_FX1 + 2, error, "fight.asm indexes US_FX1/US_FX2 as a pair; the allocator no longer packs them adjacent"

; =============================================================================
; swing_check — the active window, the vertical gate, and the KO
; =============================================================================
; In/out: A16/I16, DB=0. X = the ATTACKER's pair index. Clobbers A, Y.
;
; Four gates, then a hit: the swing must be live, inside its active window,
; not already spent this swing, and within reach BOTH horizontally and
; VERTICALLY. The vertical one is what makes the jump a defence — a fighter in
; the air is above the blade, and hopping a swing is a real answer to it.
;
; ONE HIT PER SWING, LATCHED. Without the latch the window is eight frames of
; damage rather than one strike, which is not a combat pattern, it is a
; grinder.
swing_check:
    .a16
    .i16
    lda z:US_SWG, x
    beq @bail                       ; not swinging
    cmp #SV_SWING_FIRST
    bcc @bail                       ; the window has closed
    cmp #(SV_SWING_LAST + 1)
    bcs @bail                       ; ...or has not opened yet
    lda z:US_SWH, x
    beq @reach                      ; this swing has not landed yet
@bail:
    .a16
    .i16
    rts
@reach:
    .a16
    .i16
    ; ---- horizontal: |attacker - defender| <= SV_SWING_REACH -------------
    jsr other_fx
    sec
    sbc z:US_FX1, x
    bpl @have_dx
    eor #$FFFF
    inc a                           ; negate; reach does not care which side
@have_dx:
    .a16
    .i16
    cmp #(SV_SWING_REACH + 1)
    bcs @bail
    ; ---- vertical: |attacker height - defender height| < SV_SWING_VGATE ---
    ; The heights are 8.8 and the gate is whole pixels, so both are reduced to
    ; their integer parts FIRST — comparing a 8.8 difference against a pixel
    ; count would gate at 1/256th of the intended height.
    jsr other_jmp
    sec
    sbc z:US_SLOT                   ; ...this fighter's own height, staged there
    bpl @have_dh
    eor #$FFFF
    inc a
@have_dh:
    .a16
    .i16
    cmp #SV_SWING_VGATE
    bcs @bail                       ; the defender is over (or under) the blade
    ; ---- landed ----------------------------------------------------------
    lda #1
    sta z:US_SWH, x                 ; ...and this swing is spent
    jmp swing_land

; --- other_jmp: both fighters' jump heights, in whole pixels ---------------
; In/out: A16/I16, DB=0. X = this fighter's pair index. Out: A = the OTHER
; fighter's height in px, US_SLOT = this fighter's. X unchanged. Clobbers A.
other_jmp:
    .a16
    .i16
    lda z:US_JMP, x
    xba
    and #$00FF
    sta z:US_SLOT                   ; scratch: the draw has not run yet
    txa
    eor #2
    tax
    lda z:US_JMP, x
    xba
    and #$00FF
    pha
    txa
    eor #2
    tax
    pla
    rts

; --- swing_land: the damage, the reaction, the knockback, the KO ----------
; In/out: A16/I16, DB=0. X = the ATTACKER's pair index. Clobbers A, Y.
;
; Everything below happens to the DEFENDER, so the index is flipped once at the
; top and flipped back at the bottom rather than each access carrying the
; arithmetic.
swing_land:
    .a16
    .i16
    txa
    eor #2
    tax                             ; X = the DEFENDER
    ; ---- one segment off the bar -----------------------------------------
    lda z:US_HP, x
    dec a
    sta z:US_HP, x
    ; ---- the reaction: the pack's own `hit` row, and a lockout ------------
    lda #SV_HIT_LEN
    sta z:US_HITT, x
    lda #0
    sta z:US_SWG, x                 ; a swing of its own is interrupted
    lda z:US_HP, x
    bne @staggered
    lda #SV_ST_KO
    jsr set_state
    lda #SV_R_KO
    sta z:US_RSTATE
    lda #SV_KO_LEN
    sta z:US_RTIMER
    bra @knock
@staggered:
    .a16
    .i16
    lda #SV_ST_HIT
    jsr set_state
@knock:
    .a16
    .i16
    ; ---- pushed AWAY from whoever hit it ----------------------------------
    ; The direction comes from the two positions, not from a stored facing:
    ; the fighters may have crossed since the swing started, and a knockback
    ; that pushed the defender INTO the attacker would read as a magnet.
    jsr other_fx                    ; A = the ATTACKER's x (X is the defender)
    cmp z:US_FX1, x
    bcc @push_right
    lda z:US_FX1, x
    sec
    sbc #SV_KNOCKBACK
    sta z:US_FX1, x
    bra @done
@push_right:
    .a16
    .i16
    lda z:US_FX1, x
    clc
    adc #SV_KNOCKBACK
    sta z:US_FX1, x
@done:
    .a16
    .i16
    jsr clamp_fighter
    txa
    eor #2
    tax                             ; ...and the attacker's index back
    rts

.ifdef SV_AUTODEMO
; --- demo_walk: the self-running proof --------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; The fighters march wall to wall THROUGH each other and back, so one boot
; plays the whole cycle: apart (the split opens), together (it merges), past
; each other (the side-swap), apart again on the other side. No input, no
; randomness — a fixed script, so a capture at a given frame is reproducible.
;
; IT HOLDS AT EACH WALL, and that is not cosmetic. The ease chases its target
; at SV_SPR_STEP (0.75 px/frame) while the target moves at SV_WALK_SPD
; (2 px/frame), so a demo that reverses the moment it touches a wall turns
; around before the divergence has ever reached full width — the divider never
; opens past ~3 px and the rail's own headline effect is never actually shown.
; Caught by the animated capture; no still could have shown it.
demo_walk:
    .a16
    .i16
    ; ---- dwelling at a wall? ---------------------------------------------
    ; US_CROSSED carries BOTH the direction (bit 0) and the dwell countdown
    ; (high byte). Packing them is deliberate: a dp claim for a counter that
    ; exists only in the -DSV_AUTODEMO build would shift the allocator's map
    ; and move the SHIPPING ROM's md5 for a variant it does not contain.
    ; US_CROSSED is unused in this build, so it is free real estate.
    lda z:US_CROSSED
    and #$FF00
    beq @moving
    lda z:US_CROSSED
    sec
    sbc #$0100                      ; one frame off the countdown. The
                                    ; direction bit survives untouched: the
                                    ; high byte is non-zero here (tested just
                                    ; above), so the subtraction never borrows
                                    ; into bit 0.
    sta z:US_CROSSED
    rts
@moving:
    .a16
    .i16
    lda z:US_CROSSED
    and #$0001
    bne @leftward
    ; --- fighter 1 ->, fighter 2 <- ---------------------------------------
    lda z:US_FX1
    clc
    adc z:US_TSW
    sta z:US_FX1
    lda z:US_FX2
    sec
    sbc z:US_TSW
    sta z:US_FX2
    lda z:US_FX1
    cmp #SV_ARENA_HI
    bcc @clamp
    lda #((SV_DWELL << 8) | 1)      ; reverse, and HOLD the split open
    sta z:US_CROSSED
    bra @clamp
@leftward:
    .a16
    .i16
    lda z:US_FX1
    sec
    sbc z:US_TSW
    sta z:US_FX1
    lda z:US_FX2
    clc
    adc z:US_TSW
    sta z:US_FX2
    lda z:US_FX1
    cmp #(SV_ARENA_LO + 1)
    bcs @clamp
    lda #(SV_DWELL << 8)            ; reverse to rightward, and hold
    sta z:US_CROSSED
@clamp:
    .a16
    .i16
    ldx #0
    jsr clamp_fighter
    ldx #2
    jsr clamp_fighter
    rts
.endif

.endscope
