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

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr sv_arm                      ; stage + bevel VRAM, layers, window recipe
    jsr sv_obj_arm                  ; OBSEL (forced-blank-only)
    ; ---- the fighters' opening stance ------------------------------------
    ; Power-on WRAM is random, so these stores ARE the write-before-read
    ; contract (rule 5) — not defensive initialisation.
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
.else
    lda #(SV_ARENA_MID - 20)
    sta z:US_FX1
    lda #(SV_ARENA_MID + 20)
    sta z:US_FX2
.endif
    stz z:US_SPREADF
    stz z:US_CROSSED
    stz z:ES_SV_SPREAD
    stz z:ES_SV_MID
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
.ifdef SV_HOLD
    ; frozen: the director still runs so the spread EASES to its fixed point,
    ; which is what makes the held frame a settled state rather than frame 1
    ; of an animation.
.elseif .defined(SV_AUTODEMO)
    jsr demo_walk
.else
    jsr walk_p1
    jsr walk_p2
.endif
    jsr director
    jsr sv_obj_draw
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
    sbc #SV_SPR_STEP
    bcs @store                      ; no underflow past zero
    lda #0
    bra @store
@ease_up:
    .a16
    .i16
    lda z:US_SPREADF
    clc
    adc #SV_SPR_STEP
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

; --- walk_p1 / walk_p2: one fighter, one pad ------------------------------
; In/out: A16/I16, DB=0. Clobbers A.
; Port 0 drives fighter 1, port 1 drives fighter 2 (input2's JOY2 word).
walk_p1:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq :+
    lda z:US_FX1
    sec
    sbc #SV_WALK_SPD
    sta z:US_FX1
:   lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq :+
    lda z:US_FX1
    clc
    adc #SV_WALK_SPD
    sta z:US_FX1
:   ldx #0
    jsr clamp_fighter
    rts

walk_p2:
    .a16
    .i16
    lda z:ES_INP2_CUR
    and #JOY_LEFT
    beq :+
    lda z:US_FX2
    sec
    sbc #SV_WALK_SPD
    sta z:US_FX2
:   lda z:ES_INP2_CUR
    and #JOY_RIGHT
    beq :+
    lda z:US_FX2
    clc
    adc #SV_WALK_SPD
    sta z:US_FX2
:   ldx #2
    jsr clamp_fighter
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
.assert US_FX2 = US_FX1 + 2, error, "fight.asm indexes US_FX1/US_FX2 as a pair; the allocator no longer packs them adjacent"

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
    adc #SV_WALK_SPD
    sta z:US_FX1
    lda z:US_FX2
    sec
    sbc #SV_WALK_SPD
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
    sbc #SV_WALK_SPD
    sta z:US_FX1
    lda z:US_FX2
    clc
    adc #SV_WALK_SPD
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
