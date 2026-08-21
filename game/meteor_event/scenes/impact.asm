; =============================================================================
; scenes/impact.asm — the Mode-7 cutscene: the approach, the crossover, the glow
; =============================================================================
; One scope holding this scene's map, its two scene-scoped features, and the
; LOCKED two-phase meteor:
;
;   (A) SPRITE PHASE  (t 0..71)   the plane is parked OFF-FIELD so the backdrop
;       reads black, and a single OBJ meteor sweeps in from just off the
;       top-left, growing through six discrete frames (three 16x16 FIERY
;       specks, three 32x32 ROCKY) with a flip-cycle standing in for spin,
;       composited over the captured ground the other scene left standing.
;   (B) CROSSOVER     (t == 72)   the sprite is parked and the Mode-7 plane is
;       revealed at the scale that renders it at the same ~32 px, at the same
;       screen point.
;   (C) MODE-7 PHASE  (t 72..179) the plane GROWS IN PLACE about a pivot pinned
;       at the art centre while the screen ORIGIN slides it off the
;       bottom-right, a slow tumble spins it, and the red glow rises with the
;       descent, holds and recedes.
;
; THE MATRIX DISCIPLINE. Every frame of both phases ends having applied ONE
; entry of met_grow into m7_affine's DP shadow (M7T_BIND + m7t_apply); the NMI
; hook commits the shadow's eight ports together during VBlank, so each
; rendered frame reads one consistent matrix. Writing M7A-D from the main
; thread mid-loop instead contradicts the "latched before scanline 0" rule the
; ports actually have — m7_affine's feature.toml records why the shadow idiom
; is the fix.
;
; WHO ADVANCES THE TRACK CURSOR (the m7_track contract's question): this file,
; from its own state. The cursor IS `g_timer - MET_SPRITE_END`, so no cursor
; variable exists and the cursor cannot disagree with the scene clock. The
; sprite phase indexes entry 0, which is the crossover pose — one blob, two
; phases (gen_meteor_tracks.py's seam assert).

.scope impact

.include "engine_state_impact.inc"   ; GENERATED — this scene's map
.include "met_floor.asm"             ; scene-scoped: the plane's upload
.include "met_glow.asm"              ; scene-scoped: the red impact glow

; --- the meteor sprite's hi-table field ------------------------------------
; met_put ORs its two bits into a byte the clear zeroed, which is right for a
; table rebuilt whole every frame. This scene does NOT rebuild the table — the
; captured blocks must stand untouched — so the ONE slot that changes size
; between frames (16x16 FIERY -> 32x32 ROCKY) clears its own field first.
; Derived from the claim, not narrated: the byte index and the field position
; both fall out of the slot number.
MTR_HI_BYTE = ES_O_METEOR / 4
MTR_HI_MASK = 255 - (3 << ((ES_O_METEOR & 3) * 2))

; =============================================================================
; enter — the plane, the pivot, the parked-off-field opening
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 16 colours + M7SEL
    jsr glow_arm                    ; the band table + the channel's shadow slot

    ; ---- PIN the affine pivot at the meteor art centre --------------------
    ; Constant for the whole scene, which is what makes the scale ramp grow
    ; the meteor IN PLACE and the tumble spin it about its own centre with no
    ; drift. m7a_set_center also seeds the screen origin from the pivot; the
    ; next call overrides it with the off-field park, in that order.
    ldx #MET_CX
    ldy #MET_CY
    jsr ::m7a_set_center
    lda #MET_OFF_HOFS
    ldx #MET_OFF_VOFS
    jsr set_origin

    ; ---- the crossover pose, held through the whole sprite phase ----------
    M7T_BIND ::met_grow_bin
    lda #0
    jsr ::m7t_apply

    ; ---- the scene clock, and the glow's ramp state ----------------------
    lda #MET_ST_SCENE
    sta z:US_G_STATE
    stz z:US_G_TIMER
    stz z:US_G_GLOW
    stz z:US_G_CM_ON
    jsr draw_meteor                 ; frame 0 shows the speck, not power-on OAM

    ; ---- the scene's base display (met_floor's scene_writes) --------------
    sep #$20
    .a8
    lda #7
    sta a:$2105                     ; BGMODE 7: the affine plane
    lda #(MET_TM_BG1 | MET_TM_OBJ)
    sta a:$212C                     ; TM: the plane AND the captured cast
    ; ---- arm the glow channel in the HDMAEN shadow (the NMI applies it) ---
    lda z:ES_SM_NMI+2
    ora #(1 << ES_H_GLOW_CH)
    sta z:ES_SM_NMI+2
    ; ---- lift the blank, through the fade (called in A8 — see level::enter)
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; =============================================================================
; exit — the colour math, back to the boot state
; =============================================================================
; scene_mgr has already cleared HDMAEN and the HDMAEN shadow by the time this
; runs, and clears the channel register shadow after it — so the only thing
; this scene leaves behind is the colour-math mode, and glow_disarm is that.
exit:
    .a16
    .i16
    jsr glow_disarm
    rts

; =============================================================================
; tick — one frame of the cutscene
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; WIDTH-RISK: A16/I16 entry; every helper is A16/I16 on both sides. The A8
; windows are inside `sm_request` at the end and inside met_glow's math
; helpers, and each restores A16.
; THE CUTSCENE PLAYHEAD IS WHAT THE TIMEBASE SCALES. US_G_TIMER indexes BAKED
; PER-FRAME TRACKS — the growth matrix through m7t_apply, the sprite approach's
; screen position, and the orientation flips at MET_FR_* — so the way to run
; the cutscene at the same speed on both machines is to walk the INDEX faster,
; not to re-bake anything. The tables stay byte-identical; the timer advances
; by THIS FRAME'S TICKS.
;
; The two phase boundaries are already >= and < tests (`bcs @mode7`,
; `bcc @done`), so a step that lands past one rather than on it is handled by
; the comparison that was already there.
;
; TICK: ok — this note is the region compensator's derivation for this scene;
;   naming the frame beside the tick is its subject rather than a coupling.
tick:
    .a16
    .i16
    ; This frame's ticks, published once and read by the advance below.
    TS_STEP z:US_TS_TICK_ACC, TS_ONE
    sta z:US_TS_TICK
    lda z:US_G_TIMER
    cmp #MET_SPRITE_END
    bcs @mode7
    jsr sprite_phase
    bra @advance
@mode7:
    .a16
    .i16
    jsr mode7_phase
@advance:
    .a16
    .i16
    lda z:US_G_TIMER
    clc
    adc z:US_TS_TICK            ; the playhead, at this console's tick rate
    sta z:US_G_TIMER
    cmp #MET_SCN_END
    bcc @done
    ; ---- the cutscene is over: ask for the swap back and release control --
    lda #MET_ST_RESTORE
    sta z:US_G_STATE
    sep #$20
    .a8
    SM_SWITCH "IMPACT", "LEVEL"     ; the declared edge picks the id AND the
    rep #$20                        ;   path — see level.asm's site
    .a16
@done:
    .a16
    .i16
    rts

; =============================================================================
; (A) the SPRITE phase — the far approach
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; The plane is held OFF-FIELD and at the crossover pose. With M7SEL bit 7 set,
; everything outside the 1024-px field shows the BACKDROP, so what is on
; screen is black sky, the captured ground, the player, and the approaching
; speck.
sprite_phase:
    .a16
    .i16
    lda #MET_OFF_HOFS
    ldx #MET_OFF_VOFS
    jsr set_origin
    M7T_BIND ::met_grow_bin
    lda #0
    jsr ::m7t_apply                 ; the crossover pose, held
    jsr draw_meteor
    rts

; --- draw_meteor: the growing far-approach sprite -------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; centre = (SPR_X0 + t, SPR_Y0 + t), one pixel per frame on both axes — a
; 45-degree streak, multiply-free, and CONTINUOUS with the Mode-7 phase's
; 3 px/frame slide on the same diagonal.
;
; OBJ cannot hardware-scale, so the growth is six discrete frames, and OBJ
; cannot rotate, so the spin is a FLIP CYCLE: the orientation steps every
; MET_FLIP_PERIOD frames through {normal, H, V, H+V} and the off-centre
; craters reorient with it. Both flip bits are plain OAM attribute bits here,
; and met_put takes the whole attribute byte — so there is no attribute mask to
; work around.
draw_meteor:
    .a16
    .i16
    ; ---- the swept centre --------------------------------------------------
    lda z:US_G_TIMER
    clc
    adc #MET_SPR_X0
    sta z:US_SPR_X                  ; centre x, for now
    ; centre y = t + MET_SPR_Y0, and MET_SPR_Y0 is NEGATIVE (the sprite starts
    ; just off the top edge). Written as the subtraction it is, so the operand
    ; is a positive constant rather than a two's-complement literal ca65 would
    ; range-check against a 16-bit immediate.
    lda z:US_G_TIMER
    sec
    sbc #(0 - MET_SPR_Y0)
    sta z:US_SPR_Y
    ; ---- the growth frame, and the half-size that turns centre into corner -
    lda z:US_G_TIMER
    cmp #MET_FR_R2
    bcs @r2
    cmp #MET_FR_R1
    bcs @r1
    cmp #MET_FR_R0
    bcs @r0
    cmp #MET_FR_F2
    bcs @f2
    cmp #MET_FR_F1
    bcs @f1
    lda #MET_T_FIERY0
    bra @small
@f1:
    .a16
    .i16
    lda #MET_T_FIERY1
    bra @small
@f2:
    .a16
    .i16
    lda #MET_T_FIERY2
    bra @small
@r0:
    .a16
    .i16
    lda #MET_T_ROCK0
    bra @large
@r1:
    .a16
    .i16
    lda #MET_T_ROCK1
    bra @large
@r2:
    .a16
    .i16
    lda #MET_T_ROCK2
@large:
    .a16
    .i16
    sta z:US_SPR_TILE
    lda #MET_LARGE
    sta z:ES_MET_DRAW + MET_D_SIZE  ; 32x32: OBSEL pair 3's LARGE half
    lda #16
    bra @corner
@small:
    .a16
    .i16
    sta z:US_SPR_TILE
    stz z:ES_MET_DRAW + MET_D_SIZE  ; 16x16
    lda #8
@corner:
    .a16
    .i16
    ; top-left = centre - half. A is the half-size.
    sta z:US_G_SCR
    lda z:US_SPR_X
    sec
    sbc z:US_G_SCR
    sta z:ES_MET_DRAW + MET_D_X     ; may be NEGATIVE — met_put derives X9
    lda z:US_SPR_Y
    sec
    sbc z:US_G_SCR
    sta z:ES_MET_DRAW + MET_D_Y
    ; ---- the flip cycle: o = (t / MET_FLIP_PERIOD) & 3 --------------------
    ; No divide: repeated subtraction tracking the quotient, then mask the low
    ; two bits.
    lda z:US_G_TIMER
    stz z:US_G_SCR
@div:
    .a16
    .i16
    cmp #MET_FLIP_PERIOD
    bcc @div_done
    sec
    sbc #MET_FLIP_PERIOD
    inc z:US_G_SCR
    bra @div
@div_done:
    .a16
    .i16
    lda z:US_G_SCR
    and #3
    stz z:US_G_SCR                  ; rebuild it as the attribute bits
    lsr                             ; bit 0 -> carry = H, A = the V bit
    bcc :+
    pha
    lda z:US_G_SCR
    ora #MET_HFLIP
    sta z:US_G_SCR
    pla
:   .a16
    .i16
    beq :+
    lda z:US_G_SCR
    ora #MET_VFLIP
    sta z:US_G_SCR
:   .a16
    .i16
    ; ---- clear this slot's hi field, then emit -----------------------------
    jsr meteor_hi_clear
    ldx #(ES_O_METEOR * 4)
    lda z:US_G_SCR
    ora #MET_PRIO
    xba                             ; the attribute byte into the high half
    ora z:US_SPR_TILE
    jsr ::met_put
    rts

; =============================================================================
; (C) the MODE-7 phase — grow in place, slide off, tumble, glow
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; m = g_timer - MET_SPRITE_END, the Mode-7 elapsed frame AND the track cursor.
mode7_phase:
    .a16
    .i16
    lda z:US_G_TIMER
    sec
    sbc #MET_SPRITE_END
    sta z:US_G_SCR                  ; m, kept for the slide and the glow

    ; ---- the matrix: scale ramp composed with the tumble, baked -----------
    ; One track entry per frame. Recomputing it at runtime would cost a trig
    ; lookup and two signed multiplies every frame; the entry here IS that
    ; answer, baked.
    M7T_BIND ::met_grow_bin
    lda z:US_G_SCR
    jsr ::m7t_apply

    ; ---- the slide: the PIVOT is pinned, so only the origin moves ---------
    ; The meteor centre goes (CROSS_X + 3m, CROSS_Y + 3m); rendering the pinned
    ; pivot there means HOFS = MET_CX - that, VOFS = MET_CY - that. 3m as
    ; 2m + m, multiply-free.
    lda z:US_G_SCR
    asl                             ; 2m
    clc
    adc z:US_G_SCR                  ; 3m
    sta z:US_SPR_X                  ; borrow: nothing else uses it this frame
    lda #(MET_CX - MET_CROSS_X)
    sec
    sbc z:US_SPR_X
    tay                             ; HOFS
    lda #(MET_CY - MET_CROSS_Y)
    sec
    sbc z:US_SPR_X
    tax                             ; VOFS
    tya
    jsr set_origin

    ; ---- the sprite is gone: the plane IS the meteor now ------------------
    ; The SIZE bit goes with it, and that is not tidiness. MET_PARK_Y is 240,
    ; which puts a 16x16 sprite at rows 240..255 — entirely off the 224-line
    ; screen — but a 32x32 one at rows 240..271, and the PPU WRAPS that: the
    ; bottom sixteen rows render at screen y 0..15. Measured: leaving the size
    ; bit set after the crossover painted a slice of the rocky frame across the
    ; top-left corner for the whole Mode-7 phase.
    jsr meteor_hi_clear
    ldx #(ES_O_METEOR * 4)
    jsr ::met_park_slot

    jsr scene_glow
    rts

; --- scene_glow: the red impact glow, synced to the descent ---------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. US_G_SCR holds m on entry.
;
; The schedule, and its performance gate: the target is QUANTISED to steps of 8
; and the table rebuild is GATED on the quantised value having CHANGED, so the
; long approach and the hold cost nothing and only the handful of intensity
; steps pay. An unconditional per-frame rebuild overruns the frame budget and
; runs the whole scene at about a third speed.
scene_glow:
    .a16
    .i16
    lda z:US_G_SCR
    cmp #MET_GLOW_START
    bcc @zero                       ; the meteor is still high
    cmp #MET_GLOW_PEAK
    bcc @rise
    cmp #MET_GLOW_HOLD_END
    bcc @peak
    cmp #MET_GLOW_RECEDE_END
    bcc @recede
@zero:
    .a16
    .i16
    lda #0
    bra @quant
@rise:
    .a16
    .i16
    ; raw = m - GLOW_START, one unit per frame, clamped at the 5-bit maximum
    lda z:US_G_SCR
    sec
    sbc #MET_GLOW_START
    cmp #(MET_GLOW_MAX + 1)
    bcc @quant
@peak:
    .a16
    .i16
    lda #MET_GLOW_MAX
    bra @quant
@recede:
    .a16
    .i16
    ; raw = MAX - 3*(m - HOLD_END)/2 — ~1.5 units per frame over
    ; the 24-frame window, which reaches zero before SCN_END. A negative
    ; result means "already out", so it falls through to zero.
    lda z:US_G_SCR
    sec
    sbc #MET_GLOW_HOLD_END
    sta z:US_G_SCR
    asl                             ; 2x
    clc
    adc z:US_G_SCR                  ; 3x
    lsr                             ; 3x/2
    sta z:US_G_SCR
    lda #MET_GLOW_MAX
    sec
    sbc z:US_G_SCR
    bpl @quant
    lda #0
@quant:
    .a16
    .i16
    ; quantise to steps of 8, as a shift pair rather than a mask, so no
    ; literal that looks like an address appears
    .repeat 3
        lsr
    .endrepeat
    .repeat 3
        asl
    .endrepeat
    ; ---- THE GATE: rebuild only when the quantised target actually changed
    cmp z:US_G_GLOW
    bne @changed
    rts
@changed:
    .a16
    .i16
    sta z:US_G_GLOW
    cmp #0                          ; `sta` does NOT set the flags on the
                                    ;   65816 — without this the branch below
                                    ;   would read the CMP that got us here,
                                    ;   whose Z is clear BY CONSTRUCTION, and
                                    ;   the math-OFF arm would be unreachable.
                                    ;   Measured: colour math stayed armed
                                    ;   through the swap back.
    bne @ensure_on
    ; ---- target 0: turn colour math OFF, once ----------------------------
    lda z:US_G_CM_ON
    beq @write
    stz z:US_G_CM_ON
    jsr glow_math_off
    bra @write
@ensure_on:
    .a16
    .i16
    ; ---- target > 0: turn colour math ON, once ---------------------------
    ; ADD to backdrop + BG1 with OBJ EXCLUDED, so the captured green ground
    ; and the white player are not stained red (met_glow.asm carries the mask).
    lda z:US_G_CM_ON
    bne @write
    lda #1
    sta z:US_G_CM_ON
    jsr glow_math_on
@write:
    .a16
    .i16
    lda z:US_G_GLOW
    jsr glow_set                    ; the gated rebuild: eight band bytes
    rts

; --- meteor_hi_clear: zero this ONE slot's X9 + SIZE field -----------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; met_put ORs its two bits into a byte a full clear had zeroed, which is right
; for a table rebuilt whole every frame. This scene does NOT rebuild it — the
; captured blocks must stand untouched — so the one slot whose size changes
; (16x16 FIERY -> 32x32 ROCKY -> parked) clears its own field first.
;
; WIDTH-RISK: toggles A8 for the read-modify-write and restores A16.
meteor_hi_clear:
    .a16
    .i16
    sep #$20
    .a8
    lda a:::MET_HI_BASE + MTR_HI_BYTE
    and #MTR_HI_MASK
    sta a:::MET_HI_BASE + MTR_HI_BYTE
    rep #$20
    .a16
    rts

; =============================================================================
; set_origin — the screen origin, into m7_affine's shadow
; =============================================================================
; In:  A16/I16, DB=0. A = HOFS, X = VOFS. Out: clobbers A.
;
; A CROSS-FEATURE SHADOW WRITE, and a declared one: $210D/$210E belong to
; m7_affine's `m7_matrix` claim and only its NMI commit ever writes the ports.
; What this touches is the shadow's origin half (ES_M7AFF+12/+14), exactly the
; two words `m7a_set_center` computes — this scene needs them decoupled from
; the pivot, because the pivot is PINNED at the art centre all scene while the
; origin is what slides the meteor off the bottom. m7x_logic makes the same
; kind of statement about the same feature's shadow for the same reason.
set_origin:
    .a16
    .i16
    sta z:ES_M7AFF + 12             ; BG1HOFS (= M7HOFS)
    txa
    sta z:ES_M7AFF + 14             ; BG1VOFS (= M7VOFS)
    rts

.endscope
