; =============================================================================
; scenes/demo.asm — the whole rail: two cameras, a movable seam, three modes
; =============================================================================
; The rail's whole game loop: P1's D-pad drives camera A (the left half), P2's
; drives camera B (the right half), P1's shoulders move the seam within
; [SEAM_LO, SEAM_HI], and both markers are re-staged every frame.
;
; WHY THE MODE IS A STATE AND NOT A `-D` DEFINE. Splitting the per-half OBJ clip
; and the diagonal seam into variant ROMs would put each teaching in a binary
; nobody can reach from the default one. The composition here is DECLARED once
; and the two seam shapes are the same HDMA channel reading different tables, so
; making the choice a runtime state costs one DP word and buys what variants
; cannot: every teaching reachable from every other in ONE binary, and the
; transitions between them observable in BOTH directions. The one thing that
; stays a compile-out is `-DNO_WINDOW` — it is a non-vacuity CONTROL, and a
; control written by the code under test is not one.
;
; The mode buttons read ES_INP_PRESS, the `input` feature's own cur AND NOT
; prev. The rail therefore carries no user state at all: the two cameras, the
; seam and the mode are svd_bg's dp claims because svd_bg's VBlank commit is
; what reads them, and there is nothing left for a state.toml to hold.

.scope demo

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr svd_arm                     ; stage, palette, layers, window, channel
    jsr svd_obj_arm                 ; marker CHR, palette, OBSEL, tile/attr/y
    sep #$20
    .a8
    lda #SVD_BGMODE
    sta a:$2105                     ; BGMODE 1
    lda #SVD_TM
    sta a:$212C                     ; TM: BG1|BG2|OBJ
.ifndef SVD_NOWIN
    ; The seam channel, armed in the shadow the NMI applies. svd_arm has
    ; already written its DMAP/BBAD/A1T/A1B and built the straight table, so
    ; the first frame this bit is live reads a table that exists.
    lda z:ES_SM_NMI+2
    ora #(1 << ES_H_SVDW_CH)
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (the NMI applies it)
.endif
    rep #$20
    .a16
    rts

; --- tick -------------------------------------------------------------------
; In/out: A16/I16, DB=0. Once per frame from sm_tick.
tick:
    .a16
    .i16
    jsr cam_a
    jsr cam_b
    jsr seam_move
    jsr mode_cycle
    jsr svd_obj_draw
    rts

; --- cam_a: P1's D-pad drives the LEFT half's camera ------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Masked to a byte, deliberately: the stage map is 256 px periodic,
; so mod-256 IS the correct screen mapping and a camera walked off either end
; wraps into the world rather than needing a clamp. This is also what makes
; the two halves show genuinely different vistas of one asymmetric landscape
; instead of running out of world.
cam_a:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq :+
    lda z:ES_SVD_CAM + 0
    clc
    adc #SVD_CAM_SPD
    and #255
    sta z:ES_SVD_CAM + 0
:   lda z:ES_INP_CUR
    and #JOY_LEFT
    beq :+
    lda z:ES_SVD_CAM + 0
    sec
    sbc #SVD_CAM_SPD
    and #255
    sta z:ES_SVD_CAM + 0
:   rts

; --- cam_b: P2's D-pad drives the RIGHT half's camera -----------------------
; In/out: A16/I16, DB=0. Clobbers A.
; The second pad is the whole reason `input2` is composed: two cameras that
; move INDEPENDENTLY is this rail's first teaching, and one pad cannot show it.
cam_b:
    .a16
    .i16
    lda z:ES_INP2_CUR
    and #JOY_RIGHT
    beq :+
    lda z:ES_SVD_CAM + 2
    clc
    adc #SVD_CAM_SPD
    and #255
    sta z:ES_SVD_CAM + 2
:   lda z:ES_INP2_CUR
    and #JOY_LEFT
    beq :+
    lda z:ES_SVD_CAM + 2
    sec
    sbc #SVD_CAM_SPD
    and #255
    sta z:ES_SVD_CAM + 2
:   rts

; --- seam_move: P1's shoulders sweep the seam, clamped ----------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; The clamp, comparison for comparison: R stops at SEAM_HI, L
; stops at SEAM_LO, and the LOW test is `cmp #SEAM_LO+1 / bcc` so the seam can
; sit ON the low bound and go no further. Holding a shoulder into a bound must
; stop the seam, not wrap it — an unsigned underflow past 0 would put the seam
; at 255 and collapse the right half in one frame.
seam_move:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_R
    beq :+
    lda z:ES_SVD_CAM + 4
    cmp #SVD_SEAM_HI
    bcs :+
    inc a
    sta z:ES_SVD_CAM + 4
:   lda z:ES_INP_CUR
    and #JOY_L
    beq :+
    lda z:ES_SVD_CAM + 4
    cmp #SVD_SEAM_LO + 1
    bcc :+
    dec a
    sta z:ES_SVD_CAM + 4
:   rts

; --- mode_cycle: A steps the seam mode forward, B steps it back -------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; ES_INP_PRESS is cur AND NOT prev, computed by `input` every frame, so a HELD
; button cycles once. Without that the mode would be a function of how long a
; pad is leaned on rather than of how many times it is pressed — and every
; scripted test's mode would depend on its advance() granularity.
;
; Both directions exist because the rail's transitions are a claim: straight
; -> clip -> diagonal -> straight going forward, and the same three in reverse
; going back. A one-direction cycle locks one order and ships the other
; untested (the state-cycle rule).
mode_cycle:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_A
    beq :+
    jsr mode_next
:   lda z:ES_INP_PRESS
    and #JOY_B
    beq :+
    jsr mode_prev
:   rts

; --- mode_next / mode_prev: the cycle, wrapping at both ends ----------------
; In/out: A16/I16, DB=0. Clobbers A.
mode_next:
    .a16
    .i16
    lda z:ES_SVD_MODE
    inc a
    cmp #SVD_MODE_COUNT
    bcc :+
    lda #0
:   sta z:ES_SVD_MODE
    rts

mode_prev:
    .a16
    .i16
    lda z:ES_SVD_MODE
    bne :+
    lda #SVD_MODE_COUNT
:   dec a
    sta z:ES_SVD_MODE
    rts

; --- exit -------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank (scene_mgr exit contract).
; TM is the scene's to clear; everything else the window recipe touched is the
; feature's, and svd_disarm puts it back.
exit:
    .a16
    .i16
    jsr svd_disarm
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    rep #$20
    .a16
    rts

.endscope
