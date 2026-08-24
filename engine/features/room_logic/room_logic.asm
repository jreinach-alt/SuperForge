; =============================================================================
; room_logic.asm — 8-way D-pad movement with the walls as the only collision
; =============================================================================
; px/py are the hero's TOP-LEFT corner in screen pixels (user state, declared
; in game/room/state.toml). The room is one screen and does not scroll, so
; screen space and world space are the same thing here.
;
; The bounds are a CLAMP, not a test. There is no "can I move there?" branch to
; get wrong and no out-of-bounds state to recover from — the same shape as
; col_map's total-over-u16 kernel, where the seam is removed rather than
; guarded. The cost is that a diagonal into a corner slides along the wall,
; which is what a player expects anyway.

RM_SPEED = 2                        ; px per frame, per axis — a RATE now, not
                                    ; a per-frame immediate. The scene
                                    ; publishes this frame's whole-pixel share
                                    ; of it in US_TS_STEP (tick_scale's
                                    ; TS_STEP), and RM_MOVE_PAD reads that
                                    ; word. On NTSC the published value is
                                    ; RM_SPEED to the pixel, so the picture
                                    ; cannot move; on PAL it alternates 2/3 in
                                    ; the pattern that averages 2.4036.
                                    ;
                                    ; READING A US_ SYMBOL FROM FEATURE CODE is
                                    ; this file's existing shape, not a new
                                    ; coupling: rm_spawn already writes US_PX /
                                    ; US_PY / US_PX2 / US_PY2 by name, because
                                    ; the GAME owns the hero's position and
                                    ; this feature owns only the kernel's DP
                                    ; scratch (feature.toml's split). The
                                    ; published step joins that list.
RM_LO    = 8                        ; the wall is one 8-px cell thick
RM_HI_X  = 256 - 8 - 16             ; screen width  - wall - sprite = 232
RM_HI_Y  = 224 - 8 - 16             ; visible height - wall - sprite = 200
RM_SPAWN_X = 128 - 8                ; centred horizontally
RM_SPAWN_Y = 112 - 8                ; ...and vertically
RM_STEP_PERIOD = 9                  ; frames between footsteps while moving
                                    ; (2 px/frame -> one step per 18 px)

; Joypad bit masks ($4218), written as bit POSITIONS. A bare 512 or 2048 here
; is indistinguishable from an address inside a claim, and no_literals flags it
; — correctly, since it cannot know which was meant. The shift form is the same
; idiom AGENTS.md prescribes for channel masks.
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9
JOY_DOWN  = 1 << 10
JOY_UP    = 1 << 11

; --- RM_MOVE_PAD: one pad's two-axis move + clamp, against one hero --------
; Expanded twice in rm_move (pad 1 -> px/py, pad 2 -> px2/py2). Pure A16 — no
; sep/rep inside, so it is width-neutral at any A16 call site and needs no
; WIDTH-RISK contract. Anonymous labels only: cheap @locals would collide
; across two expansions inside one scope. Real motion of EITHER hero bumps the
; shared moved-this-frame flag (ES_RM_HOT+4) — one pair of feet or two, the
; footstep cadence below is the same walk sound.
;
; Guarded: this file is included once per room scene SCOPE, and ca65 macros are
; GLOBAL — an unguarded second definition is an assembly error. (The file's
; equates are scope-local and redefine cleanly; only the macro needs this.) The
; two definitions would be identical, so first-wins is correct, not a shadowing
; hazard.
.if .not .definedmacro(RM_MOVE_PAD)
.macro RM_MOVE_PAD pad_cur, hx, hy
    ; ---- horizontal ------------------------------------------------------
    lda z:hx
    sta z:ES_RM_HOT + 0             ; working copy
    lda z:pad_cur
    and #JOY_LEFT
    beq :+
    lda z:ES_RM_HOT + 0
    sec
    sbc z:US_TS_STEP
    sta z:ES_RM_HOT + 0
:   lda z:pad_cur
    and #JOY_RIGHT
    beq :+
    lda z:ES_RM_HOT + 0
    clc
    adc z:US_TS_STEP
    sta z:ES_RM_HOT + 0
:   lda z:ES_RM_HOT + 0
    bpl :+                          ; went negative (left of the wall)?
    lda #RM_LO
:   cmp #RM_LO
    bcs :+
    lda #RM_LO
:   cmp #(RM_HI_X + 1)
    bcc :+
    lda #RM_HI_X
:   cmp z:hx                        ; clamped result vs pre-move position:
    beq :+                          ; the wall eats the motion, no step
    inc z:ES_RM_HOT + 4
:   sta z:hx
    ; ---- vertical --------------------------------------------------------
    lda z:hy
    sta z:ES_RM_HOT + 2
    lda z:pad_cur
    and #JOY_UP
    beq :+
    lda z:ES_RM_HOT + 2
    sec
    sbc z:US_TS_STEP
    sta z:ES_RM_HOT + 2
:   lda z:pad_cur
    and #JOY_DOWN
    beq :+
    lda z:ES_RM_HOT + 2
    clc
    adc z:US_TS_STEP
    sta z:ES_RM_HOT + 2
:   lda z:ES_RM_HOT + 2
    bpl :+
    lda #RM_LO
:   cmp #RM_LO
    bcs :+
    lda #RM_LO
:   cmp #(RM_HI_Y + 1)
    bcc :+
    lda #RM_HI_Y
:   cmp z:hy
    beq :+
    inc z:ES_RM_HOT + 4
:   sta z:hy
.endmacro
.endif

; --- rm_spawn: put both heroes on the floor (scene enter) ------------------
; CONTRACT rm_spawn
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both actors placed — the bearer centred, the twin a step to
;             his left
;   clobbers: A, N, Z
;   assumes:  the room is already armed
;   tail:     rts
;
; (both inside the clamp bounds, so frame 0 is a legal state).
rm_spawn:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rm_spawn"
    lda #RM_SPAWN_X
    sta z:US_PX
    lda #RM_SPAWN_Y
    sta z:US_PY
    lda #(RM_SPAWN_X - 32)
    sta z:US_PX2
    lda #RM_SPAWN_Y
    sta z:US_PY2
    rts

; --- rm_move: one frame of movement, both pads (scene tick) ----------------
; CONTRACT rm_move
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both actors stepped: pad 1 moves the bearer (px/py), pad 2
;             the twin (px2/py2) off input2's JOY2 word, same bit layout
;   clobbers: A, N, Z
;   assumes:  both pads are already latched
;   tail:     rts
;
; (px2/py2) — input2's JOY2 word, same bit layout. Clobbers A.
rm_move:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rm_move"
    stz z:ES_RM_HOT + 4             ; moved-this-frame flag (footstep input)
    RM_MOVE_PAD ES_INP_CUR,  US_PX,  US_PY
    RM_MOVE_PAD ES_INP2_CUR, US_PX2, US_PY2
    ; ---- footstep: fires on real motion only (the clamp comparison above
    ; means pushing into a wall is silent), at most every RM_STEP_PERIOD
    ; frames; going idle resets the cadence so the next walk starts with an
    ; immediate step.
    ;
    ; NOT REGION-SCALED, deliberately. RM_STEP_PERIOD is an integer countdown
    ; between SFX queues — docs/95 §5.2's class B, the class with no correct
    ; x5/6 and only a rounding policy — and scaling it is a game-feel decision
    ; this composition does not take. The consequence is stated rather than
    ; hidden: the WALK is region-correct and the cadence is not, so a PAL hero
    ; covers about 21.6 px between footsteps where an NTSC one covers 18.
    lda z:ES_RM_HOT + 4
    beq @idle
    lda z:ES_RM_STEP
    bne @between_steps
    sep #$20
    .a8
    lda #SFX::footstep
    jsr Tad_QueueSoundEffect        ; A8, KEEP X/Y, DB=0 is lowram, DP=0
    rep #$20
    .a16
    lda #RM_STEP_PERIOD
    sta z:ES_RM_STEP
    rts
@between_steps:
    .a16
    dec z:ES_RM_STEP
    rts
@idle:
    .a16
    stz z:ES_RM_STEP
    rts

; --- rm_centre_x / rm_centre_y: the hero's centre, for the lantern --------
; CONTRACT rm_centre_x
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      A = the window's x centre. It follows the sprite's MIDDLE
;             rather than its corner, which is what keeps the window
;             steady as the sprite flips
;   clobbers: A, N, Z, C, V
;   assumes:  nothing — a pure function of the position words
;   tail:     rts
;
; its corner, or the light sits up and to the left of the person holding it.
rm_centre_x:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rm_centre_x"
    lda z:US_PX
    clc
    adc #8
    rts

; CONTRACT rm_centre_y
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      A = the window's y centre, on rm_centre_x's convention
;   clobbers: A, N, Z, C, V
;   assumes:  nothing — a pure function of the position words
;   tail:     rts
rm_centre_y:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rm_centre_y"
    lda z:US_PY
    clc
    adc #8
    rts

; --- the visit-pip HUD: min(visits, 8) lamp dots, slots 0..7 ---------------
; The hud_pips claim's slots, PINNED at 0 (the H3 pin) so the row renders over
; both heroes by declaration — OAM index order is sprite priority. 8x8 small
; OBJ (hi-table bits stay 0 = small, the boot-park state), tile 2 of the hero
; CHR block (rides hero_up's existing upload), OBJ palette 0 —
; colour-math-exempt (SnesPpu.cpp:962), so the pips stay lit outside the
; lantern. Along the top wall band (OBJ scanlines 1..8), clear of the caption
; row's glyph cells.
RL_PIP_COUNT = 8
RL_PIP_TILE  = 2
RL_PIP_ATTR  = 48               ; prio 2 (bits 5-4), OBJ palette 0
RL_PIP_Y     = 0                ; OBJ Y=0 renders scanlines 1..8
RL_PIP_X0    = 8                ; first pip; then +RL_PIP_DX each
RL_PIP_DX    = 10

; --- hud_pips_arm: write the row into the OAM shadow (scene enter) ---------
; CONTRACT hud_pips_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the HUD pips' entries staged
;   clobbers: A, X, N, Z, C, V
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. The shadow writes and the scene's own are mutually
;             exclusive by construction
;   tail:     rts
;
; itself is DMA'd next armed VBlank). Uses ES_RM_HOT+0/+2 as enter-time scratch
; — rm_hot is per-tick transient, and enter runs before any tick, so the phases
; are mutually exclusive by construction. Clobbers A, X.
hud_pips_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hud_pips_arm"
    lda f:US_VISITS_LONG
    cmp #(RL_PIP_COUNT + 1)
    bcc :+
    lda #RL_PIP_COUNT               ; min(visits, 8)
:   sta z:ES_RM_HOT + 0             ; lit pips remaining
    lda #RL_PIP_X0
    sta z:ES_RM_HOT + 2             ; running x-coordinate
    ldx #0                          ; byte cursor over the 8 entries
    sep #$20
    .a8
; WIDTH-RISK: loop body is A8/I16 by contract — entered via the sep above, X
; stays a 16-bit cursor (cpx compares index-width), exits via the rep below. No
; pushes/pulls inside.
@pip:
    .a8
    lda z:ES_RM_HOT + 2
    sta a:ES_OAM_SHADOW + ES_O_HUD_PIPS * 4 + 0, x  ; X (always < 256: X9=0,
    clc                                             ; the boot-park hi bits)
    adc #RL_PIP_DX
    sta z:ES_RM_HOT + 2
    lda z:ES_RM_HOT + 0
    beq @park                       ; beyond the count: park this one
    dec z:ES_RM_HOT + 0
    lda #RL_PIP_Y
    bra :+
@park:
    .a8
    lda #240                        ; Y = $F0: off-screen
:   sta a:ES_OAM_SHADOW + ES_O_HUD_PIPS * 4 + 1, x
    lda #RL_PIP_TILE
    sta a:ES_OAM_SHADOW + ES_O_HUD_PIPS * 4 + 2, x
    lda #RL_PIP_ATTR
    sta a:ES_OAM_SHADOW + ES_O_HUD_PIPS * 4 + 3, x
    inx
    inx
    inx
    inx
    cpx #(RL_PIP_COUNT * 4)
    bcc @pip
    rep #$20
    .a16
    rts

; --- hud_pips_park: hide the whole row (scene exit) ------------------------
; CONTRACT hud_pips_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the pips' slots parked
;   clobbers: A, X, N, Z, C
;   assumes:  the scene that armed the slots re-parks them
;   tail:     rts
;
; A, X.
hud_pips_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hud_pips_park"
    ldx #0
    sep #$20
    .a8
; WIDTH-RISK: A8/I16 loop, same contract as @pip above.
@park:
    .a8
    lda #240
    sta a:ES_OAM_SHADOW + ES_O_HUD_PIPS * 4 + 1, x
    inx
    inx
    inx
    inx
    cpx #(RL_PIP_COUNT * 4)
    bcc @park
    rep #$20
    .a16
    rts
