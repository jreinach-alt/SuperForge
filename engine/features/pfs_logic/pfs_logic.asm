; =============================================================================
; pfs_logic.asm — the player: walk, jump, 16-bit world-Y physics, the camera
; =============================================================================
; `role = "game_logic"` (feature.toml): this is the GAME, living under
; engine/features/ only because that is where the allocator looks for claims.
; The sibling of `m7x_logic` / `race_logic` / `room_logic`.
;
; =============================================================================
; WHAT `py` IS, AND WHY THE ANSWER HAD TO BE MEASURED
; =============================================================================
; `py` is the FEET CONTACT LINE: the world row of the TOPMOST SOLID PIXEL of
; the surface the player stands on. The colliding body is the 8 px STRICTLY
; ABOVE it — world rows [py-8 .. Py-1] — so `py` itself is inside the floor.
;
; THE NAME IS AMBIGUOUS AND THE ARITHMETIC LOOKS LIKE THE OTHER ANSWER. The
; landing snap (`adc #7` / `and #$FFF8` / `sbc #8`) reads as box-TOP
; arithmetic, and it is: that sequence comes from a probe handed an 8x8 BOX
; whose top is `newy`, so `sbc #8` there really is "box top = tile top - box
; height". The WORLD variant reuses the identical arithmetic but the
; caller-supplied probe (`ps_solidprobe`) tests ONE ROW, so the same
; instructions now land `py` one tile lower — on the contact line.
;
; The comments could not settle it. The published render did, and the
; derivation runs one way only (CLAUDE.md rule 1):
;
;  with no input, OAM slot 0 settles at (124, 145).
;  The draw is `sprite_top = py - cam_y - 15` and the camera clamps
;  to `world_h - 224 = 800` at the world bottom, so
;  py = 145 + 800 + 15 = 960
;  and 960 is exactly the bedrock floor's TOP row (world tile row 120). If
;  `py` were the box top the player would rest at 952 and the sprite would
;  land at OAM y 137.
;
; So: contact line. `tests/test_platformer_stream.py` re-derives that from the
; ROM's own OAM bytes rather than trusting this paragraph.
;
; =============================================================================
; THE TWO TRAPS, BOTH LIVE IN THIS FILE
; =============================================================================
; 1. `pl_walk_blocked` probes rows `py-8` and `py-1`. NOT `py-7` and `py`:
;  `py` IS the floor, so counting it as body makes walking along ANY floor
;  read as "blocked into a wall".
; 2. `pl_owprobe` is a real entry point that always answers "not a one-way
;  top". The authored level marks nothing jump-through, so the integrator's
;  one-way arm has no work — but deleting it would change the branch
;  structure for no gain (feature.toml states this at length).
;
; CLOBBER CONTRACTS. Every routine here is A16/I16 in and A16/I16 out and may
; clobber A, X and Y — `col_map_at` clobbers both index registers and EXITS A8,
; which is a cross-file width contract width-check cannot see (CLAUDE.md rule
; 6). `pl_solid_at` is the single place that seam is crossed, and it is the
; only `rep #$20` in this file that is not paired with a `sep` above it.

; =============================================================================
; TUNING — the constants, as DECIMAL 8.8 rather than hex
; =============================================================================
; `no_literals` refuses `$0400` and the gate is right: it is indistinguishable
; from an address inside a claim — and it refused the DECIMAL 1024 and 1152
; too, for landing inside the `oam_shadow` and `sm_hdma` WRAM claims. So each
; velocity is written as the 8.8 ARITHMETIC it is, which is also the only form
; that says what it means: PFS_FIX is one whole pixel per frame.
PFS_FIX       = 1 << 8      ; the 8.8 scale: 1.0 px/frame
PFS_GRAVITY   = PFS_FIX / 4             ; 0.25 px/frame^2
PFS_MAX_FALL  = PFS_FIX * 4             ; 4.0 px/frame terminal fall
PFS_JUMP_VEL  = PFS_FIX * 4 + PFS_FIX / 2   ; 4.5 px/frame take-off
PFS_JUMP_CUT  = PFS_FIX                 ; 1.0 px/frame — the early-release cap
PFS_WALK      = 2           ; px/frame, integer: walking has no subpixel
PFS_BOX       = 8           ; the physics box is one tile square
PFS_SPR       = 16          ; ...and the picture drawn over it is 16x16
PFS_ANIM_RATE = 8           ; frames per animation step
PFS_ANIM_LEN  = 4           ; steps in the idle cycle

; Both speeds must stay <= 8 px/frame: the landing snap and the head-bump snap
; only reach one tile, so a faster fall embeds in the floor and a faster
; take-off tunnels through a ceiling. Both bounds are asserted below rather
; than left to a comment.
.assert PFS_MAX_FALL <= PFS_BOX * 256, error, "PFS_MAX_FALL > 8 px/frame breaks the landing snap / no-tunnel bound"
.assert PFS_JUMP_VEL <= PFS_BOX * 256, error, "PFS_JUMP_VEL > 8 px/frame can tunnel through ceilings"

; Two's complement of the two UPWARD velocities, folded at assembly time.
PFS_JUMP_UP     = (PFS_FIX * PFS_FIX) - PFS_JUMP_VEL
PFS_JUMP_CUT_UP = (PFS_FIX * PFS_FIX) - PFS_JUMP_CUT

; Masks written as arithmetic, for the same reason as the velocities.
PFS_TILE_MASK = (PFS_FIX * PFS_FIX) - PFS_BOX     ; $FFF8: down to the tile row's top pixel
PFS_HI_ONES   = (PFS_FIX * PFS_FIX) - PFS_FIX     ; $FF00: the sign extension / the y byte
PFS_LO_BYTE   = PFS_FIX - 1

; Joypad bit masks ($4218), as bit POSITIONS — `no_literals` flags a bare 256
; or 512 because it cannot tell it from an address inside a claim, and the
; shift form is the idiom AGENTS.md prescribes.
PFS_JOY_A     = 1 << 7
PFS_JOY_RIGHT = 1 << 8
PFS_JOY_LEFT  = 1 << 9

; The camera's clamp, derived from the world the level generator EMITTED and
; the screen the PPU renders — never transcribed, so a re-authored world moves
; both ends together.
PFS_CAM_X_MAX = PFS_WORLD_W_PX - PFS_SCREEN_W
PFS_CAM_Y_MAX = PFS_WORLD_H_PX - PFS_SCREEN_H
.assert PFS_CAM_X_MAX > 0 && PFS_CAM_Y_MAX > 0, error, "the world is smaller than one screen — the follow camera has nothing to clamp"

; =============================================================================
; DP FIELD ALIASES — the `pfs_player` and `pfs_probe` claims' own layouts
; =============================================================================
PL_PX     = ES_PFS_PLAYER + 0       ; world X of the box's LEFT column
PL_PY     = ES_PFS_PLAYER + 2       ; world Y of the FEET CONTACT LINE
PL_PYSUB  = ES_PFS_PLAYER + 4       ; the 8.8 fraction (low byte meaningful)
PL_VY     = ES_PFS_PLAYER + 6       ; signed 8.8 px/frame; negative = up
PL_NEWY   = ES_PFS_PLAYER + 8       ; the probe row handed to the probes
PL_GROUND = ES_PFS_PLAYER + 10      ; 1 standing / 0 airborne
PL_FACING = ES_PFS_PLAYER + 12      ; 0 right / 1 left
PL_ATICK  = ES_PFS_PLAYER + 14      ; anim clock
PL_AFRAME = ES_PFS_PLAYER + 16      ; anim frame
PL_TENTX  = ES_PFS_PLAYER + 18      ; tentative world X for the walk probe
PL_TSW_A  = ES_PFS_PLAYER + 20      ; the timebase's three (fraction, step)
PL_TSW    = ES_PFS_PLAYER + 22      ;   pairs: walk, gravity, anim clock
PL_TSG_A  = ES_PFS_PLAYER + 24
PL_TSG    = ES_PFS_PLAYER + 26
PL_TSA_A  = ES_PFS_PLAYER + 28
PL_TSA    = ES_PFS_PLAYER + 30
PL_VMAX   = ES_PFS_PLAYER + 32      ; ...and the three region-picked velocity
PL_VJUMP  = ES_PFS_PLAYER + 34      ;   constants, chosen once at enter
PL_VCUT   = ES_PFS_PLAYER + 36
.assert PL_VCUT + 2 - ES_PFS_PLAYER = ES_PFS_PLAYER_SIZE, error, "the player's field layout does not fill its DP claim"

; =============================================================================
; THE REGION-CORRECT UNITS — an arc takes TWO scales, not one
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). A VELOCITY is px per frame and scales by r. A GRAVITY is
; px per frame SQUARED and scales by r SQUARED. Together they leave
; apex = v0^2/2g unchanged, so the hero clears the same gaps on both machines
; — which on THIS rail also means the follow camera traces the same path, and
; therefore that the streamer is asked for the same tiles at the same real
; moments.
;
; TS_SCALED / TS_SCALE are tick_scale's build-time twin of TS_STEP's PAL arm,
; which is what lets a per-frame-SQUARED quantity be scaled TWICE (once here
; into the base, once by the macro). They are NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced.

TS_WALK_BASE   = PFS_WALK * TS_ONE
TS_ANIM_BASE   = TS_ONE             ; the DIVIDER (PFS_ANIM_RATE) is untouched
TS_GRAV_BASE   = PFS_GRAVITY * TS_ONE
TS_SCALED TS_GRAV_BASE_R, TS_GRAV_BASE

TS_SCALED PFS_MAX_FALL_R,    PFS_MAX_FALL
TS_SCALED PFS_JUMP_VEL_R,    PFS_JUMP_VEL
TS_SCALED PFS_JUMP_CUT_R,    PFS_JUMP_CUT
PFS_JUMP_UP_R     = (PFS_FIX * PFS_FIX) - PFS_JUMP_VEL_R
PFS_JUMP_CUT_UP_R = (PFS_FIX * PFS_FIX) - PFS_JUMP_CUT_R

; The file's own bounds, re-asserted on the SCALED pair — a region scale is
; exactly the kind of change that walks a tuned constant through a bound
; nobody re-checked.
.assert PFS_MAX_FALL_R <= PFS_BOX * 256, error, "the PAL-scaled PFS_MAX_FALL > 8 px/frame breaks the landing snap / no-tunnel bound"
.assert PFS_JUMP_VEL_R <= PFS_BOX * 256, error, "the PAL-scaled PFS_JUMP_VEL > 8 px/frame can tunnel through ceilings"
; AND ONE THIS RAIL ADDS, because it is the only streamed platformer in the
; set: the follow camera IS the player's position, so a frame's camera step is
; a frame's player step, and pfs_stream stages one ring line per TILE the
; camera crosses against a clamp of PFS_CLAMP per axis. Keeping the scaled
; step under one tile is what keeps the worst frame at one line per axis and
; therefore inside the clamp with a whole line of margin.
.assert PFS_MAX_FALL_R < PFS_BOX * 256, error, "the PAL-scaled terminal fall can cross a whole tile in one frame — the streamer's per-axis clamp no longer has a line of margin"
.assert TS_SCALE(TS_WALK_BASE) < PFS_BOX * TS_ONE, error, "the PAL-scaled walk can cross a whole tile in one frame — the streamer's per-axis clamp no longer has a line of margin"

; --- ts_publish: this frame's three region-correct steps, published once ----
; In/out: A16/I16, DB=0. Clobbers A. Called at the top of pfs_logic_tick, so
; every consumer below reads a settled word.
;
; On NTSC each publishes the constant this file authored, to the unit, and the
; carried fraction stays 0 for ever — which is why the NTSC picture cannot
; move.
ts_publish:
    .a16
    .i16
    TS_STEP z:PL_TSW_A, TS_WALK_BASE
    sta z:PL_TSW
    TS_STEP z:PL_TSA_A, TS_ANIM_BASE
    sta z:PL_TSA
    ; Gravity is per-frame-SQUARED: the second r rides the BASE, so the arm
    ; is chosen BEFORE the macro rather than after it. ANONYMOUS LABELS, not
    ; `@cheap` ones: TS_STEP's `.local` labels are plain symbols, so expanding
    ; it between a `@label` and its use RESETS the cheap-local scope and the
    ; branch target goes undefined.
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:PL_TSG_A, TS_GRAV_BASE_R
    bra :++
:   .a16
    .i16
    TS_STEP z:PL_TSG_A, TS_GRAV_BASE
:   .a16
    .i16
    sta z:PL_TSG
    rts

; --- ts_arm: the accumulators, and the region's three velocity constants ----
; CONTRACT ts_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the timebase accumulators seeded — every word written here,
;             because power-on DP is random (rule 5)
;   clobbers: A, N, Z
;   assumes:  the scene enter, before the first tick
;   tail:     rts
;
; is RANDOM (rule 5), so these stores ARE the write-before-read contract.
ts_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "ts_arm"
    lda #0
    sta z:PL_TSW_A
    sta z:PL_TSW
    sta z:PL_TSG_A
    sta z:PL_TSG
    sta z:PL_TSA_A
    sta z:PL_TSA
    lda z:ES_RGN_PAL
    beq :+
    lda #PFS_MAX_FALL_R
    sta z:PL_VMAX
    lda #PFS_JUMP_UP_R
    sta z:PL_VJUMP
    lda #PFS_JUMP_CUT_UP_R
    sta z:PL_VCUT
    rts
:   .a16
    .i16
    lda #PFS_MAX_FALL               ; today's constants, to the bit
    sta z:PL_VMAX
    lda #PFS_JUMP_UP
    sta z:PL_VJUMP
    lda #PFS_JUMP_CUT_UP
    sta z:PL_VCUT
    rts

PB_X = ES_PFS_PROBE + 0             ; the world PIXEL pair a probe is asked
PB_Y = ES_PFS_PROBE + 2             ;   about (col_map does the >>3 itself)
PB_T = ES_PFS_PROBE + 4             ; transient: the integrator's tentative
                                    ;  pixel, then the draw's screen y
.assert PB_T + 2 - ES_PFS_PROBE = ES_PFS_PROBE_SIZE, error, "the probe block's field layout does not fill its DP claim"

; =============================================================================
; THE COLLISION SEAM — one query, over col_map, in WORLD space
; =============================================================================
; --- pl_solid_at: is the world pixel (PB_X, PB_Y) inside solid terrain? -----
; In: A16/I16, DB=0. PB_X / PB_Y = world pixel coordinates (ANY u16 — the
;  kernel is total by mask).
; Out: A16 = 1 solid / 0 air. Clobbers A, X, Y and col_map's own ES_CM_HOT.
;
; This asks col_map about a WORLD coordinate, never about the 64x64 ring, so
; what blocks the player is the true level geometry rather than whatever window
; happens to be resident. Collision and streaming are decoupled by construction
; — the reason the probes are caller-supplied at all.
;
; WIDTH-RISK: `col_map_at` is A16 IN and A8 OUT (its own header states the
; contract), and it lives in another file, so width-check cannot see either
; half. The bare `.a8` after the `jsr` is what tells ca65 the truth, and the
; `rep #$20` below is the restore — the only unpaired one in this file.
pl_solid_at:
    .a16
    .i16
    lda z:PB_X
    sta z:CM_PX
    lda z:PB_Y
    sta z:CM_PY
    jsr col_map_at                  ; leaves A8; CM_FLAG holds the flag byte
    .a8                             ; WIDTH-RISK: the CPU is A8 on this line and
                                    ;  ca65 still thinks A16 — a 3-byte `and`
                                    ;  immediate here executes its high byte as
                                    ;  BRK. This directive is the whole fix and
                                    ;  width-check cannot see the need for it,
                                    ;  because the contract is in another file.
    ; A ALREADY HOLDS THE FLAG BYTE — col_map_at's last act is `lda
    ; f:CM_FLAGS,x` / `sta z:CM_FLAG`, so the mask lands on the value without a
    ; second load. That is also why nothing here reads CM_FLAG as a WORD:
    ; CM_FLAG is ONE byte and the byte above it is col_map's own scratch, so a
    ; 16-bit load would read a location nothing has written since power-on. The
    ; mask discards it either way, but Mesen's break-on-uninitialised-read
    ; detector flags the READ, not the use — and a detector that has to be
    ; argued with stops being one (CLAUDE.md rule 5).
    and #PFS_FLAG_SOLID
    rep #$20                        ; WIDTH-RISK: col_map_at EXITS A8
    .a16
    and #PFS_LO_BYTE                ; -> $0000 / $0001 in A16 (clears the B byte)
    rts

; --- pl_solidprobe: the integrator's SOLID probe ---------------------------
; In: A16/I16, DB=0. PL_NEWY = the world row to test; the box spans world
;  columns PL_PX .. PL_PX+7.
; Out: A16 = 1 if EITHER column is solid at that row, else 0. Clobbers A, X, Y.
;
; ONE ROW, not a box — and that is what makes `py` the contact line rather than
; the box top (see the file header). The integrator hands it the row it wants
; tested and re-reads its own state from DP afterwards.
pl_solidprobe:
    .a16
    .i16
    lda z:PL_NEWY
    sta z:PB_Y
    lda z:PL_PX
    sta z:PB_X
    jsr pl_solid_at
    bne @hit
    lda z:PL_PX
    clc
    adc #(PFS_BOX - 1)              ; the box's RIGHT column
    sta z:PB_X
    jsr pl_solid_at
    bne @hit
    lda #0
    rts
@hit:
    .a16
    .i16
    lda #1
    rts

; --- pl_owprobe: the one-way (jump-through) platform probe ------------------
; In/out: A16/I16, DB=0. Always answers 0 — "not a one-way top".
;
; A REAL ENTRY POINT THAT ALWAYS SAYS NO. The authored level marks nothing
; jump-through: every solid tile is fully solid, so the integrator's one-way
; arm has no work. It is kept because deleting it changes that arm's branch
; structure for no gain, and because a future level with a second collision
; value then extends this routine instead of rewriting the integrator.
pl_owprobe:
    .a16
    .i16
    lda #0
    rts

; --- pl_walk_blocked: the horizontal box probe -----------------------------
; In: A16/I16, DB=0. PL_TENTX = the tentative world X of the box's left edge.
; Out: A16 = 1 if any of the four body corners is solid, else 0. PL_PX and
;  PL_NEWY are untouched. Clobbers A, X, Y.
;
; TRAP 1 LIVES HERE. The body is rows [PL_PY-8 .. PL_PY-1] — the 8 px STRICTLY
; ABOVE the feet — because PL_PY is the contact line and therefore the SOLID
; floor row itself. Probing [PL_PY-7 .. PL_PY] would report every floor the
; player is standing on as a wall in front of them.
pl_walk_blocked:
    .a16
    .i16
    ; ---- the top body row: py - 8 -----------------------------------------
    lda z:PL_PY
    sec
    sbc #PFS_BOX
    sta z:PB_Y
    lda z:PL_TENTX
    sta z:PB_X
    jsr pl_solid_at
    bne @hit
    lda z:PL_TENTX
    clc
    adc #(PFS_BOX - 1)
    sta z:PB_X
    jsr pl_solid_at                 ; PB_Y still holds the top body row
    bne @hit
    ; ---- the bottom body row: py - 1, just above the contact line ---------
    lda z:PL_PY
    dec a
    sta z:PB_Y
    lda z:PL_TENTX
    sta z:PB_X
    jsr pl_solid_at
    bne @hit
    lda z:PL_TENTX
    clc
    adc #(PFS_BOX - 1)
    sta z:PB_X
    jsr pl_solid_at
    bne @hit
    lda #0
    rts
@hit:
    .a16
    .i16
    lda #1
    rts

; =============================================================================
; THE VERTICAL ARC — a 16.8 world Y, integrated once per frame
; =============================================================================
; --- pl_addpos: {PL_PY: PL_PYSUB.lo} += sign_extend(PL_VY) ----------------
; In/out: A16/I16, DB=0. Commits both halves AND mirrors the new integer pixel
; to PB_T, so a BLOCKED arm can read the tentative pixel and re-snap PL_PY from
; it (the snap then overwrites the commit — safe by construction). Clobbers A.
;
; WIDTH-RISK: A16 throughout — one PHA (2 bytes) matched by exactly one PLA on
; every path, and no width toggle spans the pair.
pl_addpos:
    .a16
    .i16
    lda z:PL_PYSUB
    and #PFS_LO_BYTE
    clc
    adc z:PL_VY                     ; low byte = new subpixel, high = px delta
    pha
    and #PFS_LO_BYTE
    sta z:PL_PYSUB
    pla
    xba
    and #PFS_LO_BYTE                ; the signed 8-bit pixel delta
    cmp #128
    bcc @pos
    ora #PFS_HI_ONES                ; ...sign-extended to 16 bits
@pos:
    .a16
    .i16
    clc
    adc z:PL_PY
    sta z:PL_PY                     ; the committed integer pixel
    sta z:PB_T                      ; ...mirrored for the blocked arms
    rts

; --- pl_physics: one frame of the whole vertical state cycle ---------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Standing -> take-off -> ascent -> head bump -> apex -> descent -> landing
; snap -> rest, all of it, with no collision response left to the caller.
; The two `jsr` probe seams are bound to the world-space probes above.
pl_physics:
    .a16
    .i16
    lda z:PL_VY
    bpl @falling
    jmp @rising

@falling:
    .a16
    .i16
    ; ---- standing: is the row 1 px below the contact line solid? ----------
    ; A STABLE answer every frame, not only on the snap frame — which is what
    ; lets the jump gate just read PL_GROUND.
    lda z:PL_PY
    inc a
    sta z:PL_NEWY
    jsr pl_solidprobe
    cmp #1
    bne :+
    jmp @stand
:   ; ---- one-way support: resting EXACTLY on a platform top? --------------
    lda z:PL_PY
    and #(PFS_BOX - 1)
    beq :+
    jmp @integrate                  ; mid-tile: nothing one-way to stand on
:   lda z:PL_PY
    clc
    adc #PFS_BOX
    sta z:PL_NEWY
    jsr pl_owprobe
    cmp #1
    bne :+
    jmp @stand
:   jmp @integrate

@stand:
    .a16
    .i16
    stz z:PL_VY                     ; rest, with a stable grounded flag
    stz z:PL_PYSUB                  ; ...pixel-exact: no residual fraction
    lda #1
    sta z:PL_GROUND
    jmp @done

@integrate:
    .a16
    .i16
    ; ---- gravity, clamped to terminal fall speed --------------------------
    lda z:PL_VY
    clc
    adc z:PL_TSG
    cmp z:PL_VMAX
    bcc :+
    lda z:PL_VMAX
:   sta z:PL_VY
    ; ---- the tentative move, then probe the row it landed on --------------
    jsr pl_addpos
    lda z:PB_T
    sta z:PL_NEWY
    jsr pl_solidprobe
    cmp #1
    bne @fall_clear
    ; ---- blocked: the landing snap, over the tentative commit -------------
    ; THE FEET LINE IS THE TOP OF THE TILE ROW THE FEET ENTERED, which is a
    ; floor and not a ceiling. It used to be written `(newy + BOX - 1) & MASK
    ; - BOX`, which is the same answer for every newy STRICTLY inside a tile
    ; and a whole tile too high on the tile's FIRST row: newy = 960 gave 952.
    ; The fall then rested 8 px in the air for one frame and dropped again —
    ; a 7 px hitch on landing, and a 6-frame arc in an arc-rate measurement.
    ;
    ; NTSC never reached it. The standing probe one pixel below the contact
    ; line catches a 4.0 px/frame fall at newy = 959 first, so the exact
    ; boundary was unreachable and the off-by-one sat there. A 4.81 px/frame
    ; PAL fall steps 955 -> 960 in one frame and lands on it, which is how a
    ; region scale finds a latent bound: it does not create the defect, it
    ; reaches it. Measured before the fix: 2 of 15 PAL arcs were 6-frame
    ; stubs resting at y = 952, and `arc_rate` read 1.120 for a rail whose
    ; whole arcs are 35 frames NTSC and 29 PAL — which is 1.003.
    lda z:PL_NEWY
    and #PFS_TILE_MASK              ; the top of the tile row it entered
    sta z:PL_PY
    stz z:PL_PYSUB
    stz z:PL_VY
    lda #1
    sta z:PL_GROUND
    jmp @done

@fall_clear:
    .a16
    .i16
    ; ---- one-way platforms: land only when CROSSING a top from above ------
    lda z:PL_NEWY
    clc
    adc #(PFS_BOX - 1)
    sta z:PB_T                      ; the box's bottom pixel at the new place
    and #PFS_TILE_MASK
    sta z:PL_NEWY                   ; ...and that row's tile top
    lda z:PB_T
    sec
    sbc z:PL_NEWY                   ; 0..7 only if the top was just crossed
    cmp #PFS_BOX
    bcs @ow_none
    lda z:PB_T
    sta z:PL_NEWY
    jsr pl_owprobe
    cmp #1
    bne @ow_none
    lda z:PL_NEWY                   ; the same snap a solid floor takes
    and #PFS_TILE_MASK
    sec
    sbc #PFS_BOX
    sta z:PL_PY
    stz z:PL_PYSUB
    stz z:PL_VY
    lda #1
    sta z:PL_GROUND
    jmp @done

@ow_none:
    .a16
    .i16
    stz z:PL_GROUND                 ; the tentative position stands
    jmp @done

@rising:
    .a16
    .i16
    stz z:PL_GROUND
    lda z:PL_VY
    clc
    adc z:PL_TSG                    ; no clamp is needed while negative
    sta z:PL_VY
    jsr pl_addpos
    lda z:PB_T
    sta z:PL_NEWY
    jsr pl_solidprobe
    cmp #1
    bne @done                       ; clear: the tentative position stands
    ; ---- head bump: below the ceiling tile, and the arc comes down early --
    lda z:PL_NEWY
    and #PFS_TILE_MASK
    clc
    adc #PFS_BOX
    sta z:PL_PY
    stz z:PL_PYSUB
    stz z:PL_VY

@done:
    .a16
    .i16
    rts

; =============================================================================
; THE HORIZONTAL AXIS, THE JUMP, THE CAMERA
; =============================================================================
; --- pl_walk: 2 px/frame either way, level-checked per axis ----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; TENTATIVE-THEN-COMMIT: the step is written to PL_TENTX, the box probe is
; asked about THAT column, and PL_PX only moves if the answer is air. So the
; player stops FLUSH against a wall — the leading box column is the last air
; column — instead of being pushed back out of one.
pl_walk:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #PFS_JOY_RIGHT
    beq @no_right
    lda z:PL_PX
    clc
    adc z:PL_TSW
    cmp #(PFS_WORLD_W_PX - PFS_BOX)
    bcs @no_right                   ; the world's right edge blocks too
    sta z:PL_TENTX
    jsr pl_walk_blocked
    cmp #1
    beq @no_right
    lda z:PL_TENTX
    sta z:PL_PX
    stz z:PL_FACING
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #PFS_JOY_LEFT
    beq @no_left
    lda z:PL_PX
    cmp z:PL_TSW
    bcc @no_left                    ; the world's left edge
    sec
    sbc z:PL_TSW
    sta z:PL_TENTX
    jsr pl_walk_blocked
    cmp #1
    beq @no_left
    lda z:PL_TENTX
    sta z:PL_PX
    lda #1
    sta z:PL_FACING
@no_left:
    .a16
    .i16
    rts

; --- pl_jump: the grounded-gated take-off + the variable-height cut --------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Gated on the PRESS edge, so holding A does not auto-rejump on landing; the
; cut runs on every frame A is NOT held, which is what makes a tap a hop and a
; hold the full arc. Idempotent — it does nothing while falling or already
; slow.
pl_jump:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #PFS_JOY_A
    beq @no_press
    lda z:PL_GROUND
    beq @no_press                   ; mid-air: no second jump
    lda z:PL_VJUMP
    sta z:PL_VY
    stz z:PL_GROUND
@no_press:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #PFS_JOY_A
    bne @held
    lda z:PL_VY
    bpl @held                       ; not rising
    cmp z:PL_VCUT
    bcs @held                       ; already at or below the cap
    lda z:PL_VCUT
    sta z:PL_VY
@held:
    .a16
    .i16
    rts

; --- pl_camera: the two-axis follow camera, clamped to the world -----------
; In/out: A16/I16, DB=0. Clobbers A.
;
; cam = clamp(player - half a screen, 0, world - screen), on BOTH axes — the
; first camera in the set with a live vertical degree of freedom. It writes
; `pfs_bg`'s `pfs_cam` claim, which is the SAME pair the NMI hook commits to
; BG1HOFS/BG1VOFS and the streaming producer derives its resident window from,
; so the scroll and the ring can never disagree about which window is on
; screen.
;
; The low clamp is signed-aware: `bpl` catches a subtraction that went below
; zero (bit 15 set) and pins it to 0 rather than to the top of u16.
pl_camera:
    .a16
    .i16
    lda z:PL_PX
    sec
    sbc #(PFS_SCREEN_W / 2)
    bpl :+
    lda #0
:   cmp #(PFS_CAM_X_MAX + 1)
    bcc :+
    lda #PFS_CAM_X_MAX
:   sta z:ES_PFS_CAM + 0
    lda z:PL_PY
    sec
    sbc #(PFS_SCREEN_H / 2)
    bpl :+
    lda #0
:   cmp #(PFS_CAM_Y_MAX + 1)
    bcc :+
    lda #PFS_CAM_Y_MAX
:   sta z:ES_PFS_CAM + 2
    rts

; --- pl_anim: the idle cycle's clock ---------------------------------------
; In/out: A16/I16, DB=0. Clobbers A. Four steps, one every eight frames.
pl_anim:
    .a16
    .i16
    ; THE CLOCK ADVANCES BY PL_TSA, NOT BY ONE — docs/95 §5.2's class C: a
    ; frame-rate divider is a small integer with no correct x5/6, so
    ; PFS_ANIM_RATE is left alone and what the clock ADVANCES BY is scaled.
    ; On NTSC PL_TSA is exactly 1 every frame, so this is `inc a` in
    ; behaviour, and the overshoot it carries is 0.
    lda z:PL_ATICK
    clc
    adc z:PL_TSA
    sta z:PL_ATICK
    cmp #PFS_ANIM_RATE
    bcc @done
    sec
    sbc #PFS_ANIM_RATE              ; CARRY the overshoot rather than zeroing
    sta z:PL_ATICK
    lda z:PL_AFRAME
    inc a
    cmp #PFS_ANIM_LEN
    bcc :+
    lda #0
:   sta z:PL_AFRAME
@done:
    .a16
    .i16
    rts

; =============================================================================
; THE HERO'S PICTURE — OBJ CHR, the OBJ palette, and one OAM entry a frame
; =============================================================================
; The OAM low table's byte offset for the slot `oam_sprites` handed us, and the
; hi-table byte that carries its X9 and size bits. Both are DERIVED from the
; claims — a re-sized shadow or a moved slot follows them.
PFS_OAM_SLOT = ES_OAM_SHADOW + ES_O_PFS_HERO * 4
PFS_HI_BYTE  = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32 + (ES_O_PFS_HERO / 4)

; OAM attribute bits (entry byte 3) and hi-table bits, as bit positions.
PFS_OBJ_PRIO  = 3 << 4              ; in front of every BG layer
PFS_OBJ_HFLIP = 1 << 6
PFS_HI_X9     = 1 << 0              ; slot 0 occupies the byte's FIRST field,
PFS_HI_LARGE  = 1 << 1              ;   so no shift is needed for either bit

; The GP-DMA register file for the enter-time OBJ CHR upload, addressed through
; the channel the `pfs_hero_up` dma_init claim names.
PL_REGS = $4300 + ES_D_PFS_HERO_UP_CH * 16

; --- pl_up: the OBJ CHR page, WRAM-free, straight out of ROM ---------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). VMADD must already be set. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine. One arming site is the only shape a caller cannot forget.
pl_up:
    .a16
    .i16
    ldx #.loword(pfs_hero_chr_bin)
    stx a:PL_REGS + 2               ; A1T
    ldy #ES_R_PFS_HERO_CHR_SIZE
    sty a:PL_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda #^pfs_hero_chr_bin
    sta a:PL_REGS + 4               ; A1B
    lda #ES_D_PFS_HERO_UP_DMAP
    sta a:PL_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_PFS_HERO_UP_BBAD
    sta a:PL_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_PFS_HERO_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- pl_arm: the OBJ half of the scene's display (scene enter) -------------
; CONTRACT pl_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the player's state seeded and its sheet uploaded
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract
;   tail:     rts
;
; `pfs_bg` owns the BG half — its CHR page, its 16-word palette, the backdrop
; word. This is the OBJ half: the hero's CHR page, OBJ palette 0 at CGRAM 128,
; and OBSEL. Every byte moves under the enter-time forced blank with NMI
; masked, so no NMI can land mid-upload and re-point VMADD (forced blank does
; NOT mask NMI — $4200 bit 7 does).
pl_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pl_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_PFS_HERO_V
    sta a:$2116                     ; VMADD = the claim's word base
    jsr pl_up
    ; ---- OBJ palette 0, CPU-side: 16 words is 64 cycles of forced blank ---
    sep #$20
    .a8
    lda #ES_C_PFS_HERO_PAL_C
    sta a:$2121                     ; CGADD = the claim's base word (128)
    rep #$20
    .a16
    ldx #0
:   lda f:pfs_hero_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_PFS_HERO_PAL_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (8x8 / 16x16), name base from the claim -------
    ; The hero is 16x16, so only the pair's large half is ever used — but
    ; pl_draw still writes the size bit every frame, because a bit left clear
    ; renders a 16x16 sprite as its top-left quarter.
    sep #$20
    .a8
    lda #ES_V_PFS_HERO_V_OBSEL_BASE
    sta a:$2101
    rep #$20
    .a16
    rts

; --- pl_draw: the hero's OAM entry, from this frame's state ----------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; The 16x16 picture is drawn over the 8x8 physics box: centred on it in x (box
; left - 4) and hung from the feet in y (contact line - 15), both in world
; space with the camera subtracted after — which is what keeps the sprite and
; the level in step while the camera clamps.
;
; THE HI-TABLE BYTE IS WRITTEN WHOLE, NOT OR'ED. Slots 1..3 share it and are
; unclaimed: `oam_park_all` zeroed the byte at boot and nothing else in this
; ROM writes it, so a plain store leaves them exactly as parked. THE X9 BIT IS
; DERIVED EVERY FRAME, never assumed — the hero's screen x is its world x minus
; the camera, and while the camera is clamped at a world edge the player walks
; away from centre, so a stale X9 would throw the sprite 256 px sideways.
;
; WIDTH-RISK: the two `sep`/`rep` pairs each narrow for a single byte store and
; widen straight back; every label below carries the width it is reached in.
pl_draw:
    .a16
    .i16
    lda z:PL_PY
    sec
    sbc z:ES_PFS_CAM + 2
    sec
    sbc #(PFS_SPR - 1)              ; feet-hung: the art's last row on the feet
    sta z:PB_Y
    lda z:PL_PX
    sec
    sbc z:ES_PFS_CAM + 0
    sec
    sbc #((PFS_SPR - PFS_BOX) / 2)  ; the 16-wide picture over the 8-wide box
    sta z:PB_X
    ; ---- bytes 2,3: the tile id and the attribute, in one store -----------
    lda z:PL_AFRAME
    asl a                           ; frame f occupies tiles {2f, 2f+1, +16, +17}
    ora #(PFS_OBJ_PRIO << 8)
    ldx z:PL_FACING
    beq @put
    ora #(PFS_OBJ_HFLIP << 8)       ; walking left -> mirror the picture
@put:
    .a16
    .i16
    ldx #0
    sta a:PFS_OAM_SLOT + 2, x
    ; ---- byte 1 = y (byte 0 cleared here, then overwritten below) ---------
    lda z:PB_Y
    xba
    and #PFS_HI_ONES
    sta a:PFS_OAM_SLOT + 0, x
    sep #$20
    .a8
    lda z:PB_X
    sta a:PFS_OAM_SLOT + 0, x       ; byte 0 = x's low eight bits
    rep #$20
    .a16
    ; ---- the hi-table field: X9 from x bit 8, plus the 16x16 size bit -----
    lda z:PB_X
    xba
    and #PFS_HI_X9
    ora #PFS_HI_LARGE
    sep #$20
    .a8
    sta a:PFS_HI_BYTE, x
    rep #$20
    .a16
    rts

; =============================================================================
; THE SCENE'S TWO ENTRY POINTS
; =============================================================================
; CONTRACT pfs_spawn
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the player placed at the spawn point
;   clobbers: A, N, Z
;   assumes:  the level is already armed
;   tail:     rts
;
; --- pfs_spawn: every byte of both DP claims, at scene enter ---------------
;
; THE WRITE-BEFORE-READ CONTRACT, and the reason neither claim declares `[init]
; zero`. Power-on RAM is random (CLAUDE.md rule 5); this routine writes all 26
; bytes before any tick can read one, so a pre-zero would only hide a "the
; spawn never ran" defect behind a plausible answer.
;
; The spawn is in the mouth of the open fall shaft, airborne: `PL_GROUND = 0`
; and `PL_VY = 0` puts the first tick on the integrator's falling arm, and
; gravity alone carries the player about five screens down to the bedrock
; floor. That is what makes the down-axis proof need no scripted input.
pfs_spawn:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_spawn"
    lda #PFS_SPAWN_X
    sta z:PL_PX
    lda #PFS_SPAWN_Y
    sta z:PL_PY
    stz z:PL_PYSUB
    stz z:PL_VY
    stz z:PL_NEWY
    stz z:PL_GROUND
    stz z:PL_FACING
    stz z:PL_ATICK
    stz z:PL_AFRAME
    stz z:PL_TENTX
    stz z:PB_X
    stz z:PB_Y
    stz z:PB_T
    rts

; --- pfs_logic_tick: one game frame ----------------------------------------
; CONTRACT pfs_logic_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one frame of player physics and animation
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame from the scene tick, during ACTIVE DISPLAY —
;             so nothing below it may touch a PPU port that is not
;             write-safe outside VBlank
;   tail:     rts
;
; VRAM: the draw writes the oam_sprites SHADOW and the camera writes DP, and
; both reach hardware through the NMI hook's declared transfers.
;
; ORDER IS LOAD-BEARING. Horizontal first (the vertical probes read PL_PX),
; then the jump gate (it reads the PREVIOUS frame's PL_GROUND, which the
; integrator keeps stable while standing), then the integrator, then the camera
; (it reads the settled position), then the draw (it reads the settled camera).
; The order is forced by those dependencies, not by taste.
pfs_logic_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_logic_tick"
    jsr ts_publish                  ; this frame's region-correct steps, once
    jsr pl_anim
    jsr pl_walk
    jsr pl_jump
    jsr pl_physics
    jsr pl_camera
    jsr pl_draw
    rts
