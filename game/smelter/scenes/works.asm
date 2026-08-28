; =============================================================================
; works scene — MODE 2, and BG3 is not a layer
; =============================================================================
; The scene the effect runs in. Everything visible here that is not in the
; title scene comes from ONE 64 B VBlank transfer: the 32 words of BG3's
; vertical offset row, one per 8-pixel column, chosen out of a resident blob
; by the animation's phase.
;
; THE PER-FRAME WORK IS ONE ROUTINE CALL AND ONE TRANSFER. `smt_advance` moves
; the phase on by this frame's region-corrected step; `smt_nmi_row` fires the
; row into VRAM in VBlank. There is no table build, no HDMA channel, and no
; CPU cost during active display at all — the PPU reads the words as part of
; the tilemap fetch it was going to do anyway.
;
; B FLATTENS EVERY COLUMN, and it is not a convenience. A per-column
; displacement is only measurable against the same picture UNDISPLACED, so the
; flat state is this rail's control — one binary, one scene, nothing else
; different between them.
;
; FLAT IS A ROW, NOT A DISARM. smt_rom's 65th row is a complete offset row
; whose every value is its layer's base and whose every ENABLE BIT IS STILL
; SET, so the same channel fires the same 64 B into the same place in both
; states and exactly one variable moves. Clearing the enable bits instead
; would change two things at once — the values and whether the mechanism runs
; — and a two-variable comparison cannot attribute what it shows.
.scope works
.include "engine_state_works.inc"   ; GENERATED — this scene's map
.include "smt_opt.asm"              ; scene-scoped: its claims are this
                                    ;   scene's, so its symbols resolve here
.include "smt_obj.asm"              ; ...and the knight, AFTER it: his landing
                                    ;   calls smt_plate_top

; =============================================================================
; THE KNIGHT'S THREE RATES, and the one that takes the region ratio twice
; =============================================================================
; TS_STEP applies exactly one r. A run is px per frame and takes one; a GRAVITY
; is px per frame SQUARED and takes two, so the second goes into the BASE — on
; the PAL arm only, which is why the tick branches on ES_RGN_PAL BEFORE the
; macro rather than after it. Both arms share one accumulator: a console cannot
; change region, so only one of them is ever taken.
;
; TS_SCALED is tick_scale's build-time twin of TS_STEP's PAL arm. It is NOT a
; second copy of the ratio — TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's own and
; single-sourced — so the compile-time and run-time arms cannot disagree by a
; count. game/jumper/scenes/sky.asm is where this tree first spelled it.
TS_RUN_BASE  = SMT_KN_SPEED * TS_ONE
TS_GRAV_BASE = SMT_KN_GRAVITY * TS_ONE
TS_SCALED TS_GRAV_BASE_R, TS_GRAV_BASE

; --- the two velocities: one r each, chosen once at enter ------------------
TS_SCALED SMT_KN_MAX_FALL_R, SMT_KN_MAX_FALL
TS_SCALED SMT_KN_JUMP_VEL_R, SMT_KN_JUMP_VEL
SMT_KN_NEG_JUMP_VEL_R = (1 << 16) - SMT_KN_JUMP_VEL_R

; smelter.inc's own bound, re-asserted on the SCALED pair: a region scale is
; exactly the kind of change that walks a tuned constant through a bound
; nobody re-checked.
.assert (SMT_KN_MAX_FALL_R >> 8) <= SMT_KN_LAND_WIN, error, "the PAL-scaled terminal fall is faster than the landing window is wide — the knight can pass through a plate in one frame"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    jsr smt_arm_bg                  ; the world: CHR, both maps, both palettes
    jsr smt_layer_bases             ; BG1SC, BG2SC, BG12NBA
    jsr smt_arm_rows                ; the H row and the flat control row, in
    stz z:ES_SMT_PHASE              ; ...and the animation starts at phase 0
    stz z:ES_SMT_FLATSEL            ; running, not flat, on entry
    stz z:ES_SMT_SCRATCH
    stz z:ES_SMT_SCRATCH + 2
    stz z:ES_SMT_SCRATCH + 4
    stz z:US_TSC_ACC                ; the timebase's carried fraction
    stz z:US_TSC
    ; ---- the knight's timebase, and his two region-selected velocities ----
    ; Power-on DP is RANDOM (rule 5), so these stores ARE the write-before-read
    ; contract rather than defensive initialisation.
    stz z:US_TSKR_ACC
    stz z:US_TSKR
    stz z:US_TSKG_ACC
    stz z:US_TSKG
    lda z:ES_RGN_PAL
    beq :+
    lda #SMT_KN_MAX_FALL_R
    sta z:US_VMAX
    lda #SMT_KN_NEG_JUMP_VEL_R
    sta z:US_VJUMP
    bra :++
:   .a16
    .i16
    lda #SMT_KN_MAX_FALL            ; today's constants, to the bit
    sta z:US_VMAX
    lda #SMT_KN_NEG_JUMP_VEL
    sta z:US_VJUMP
:   .a16
    .i16
    jsr smt_kn_arm                  ; the knight: CHR, palette, OBSEL, spawn
    jsr smt_kn_draw                 ; ...staged BEFORE the first NMI, so frame
                                    ;   0 commits a real entry rather than
                                    ;   whatever oam_park_all left
    sep #$20
    .a8
    ; ---- the composed video mode ------------------------------------------
    ; $02: mode 2, four bits-per-pixel on BG1 and BG2, and BG3 read as offsets
    ; rather than drawn. NOT narrated — the byte is composed from `smt_opt`'s
    ; [[claims.video]] claim, which is the same declaration the allocator
    ; checked the [[claims.offset]] claim against.
    lda #ES_VID_WORKS_BGMODE
    sta a:$2105
    ; ---- BG3 STOPS BEING A LAYER ------------------------------------------
    ; The table's ADDRESS, and the two registers that index it. BG3SC picks
    ; the page the words are read from; BG3HOFS is 0 so a fetch's column index
    ; is the screen column ungrated; BG3VOFS is 0 so map row 0 is the
    ; horizontal row and map row 1 — 0x20 words later — is the vertical one.
    ;
    ; These three ports belong to the OFFSET COMPOSITION, not to any feature's
    ; [[claims.reg]], and it grants its consent to scene-enter code. That is
    ; why they sit here beside the composed BGMODE rather than inside
    ; `smt_opt.asm`: the mode and the table's address are one declaration, and
    ; this is the one place both are written from allocator symbols.
    lda #ES_V_SMT_TAB_SC_BASE
    sta a:$2109                     ; BG3SC — the table's page, from the claim
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; BG3HOFS, high
    stz a:$2112                     ; BG3VOFS, low
    stz a:$2112                     ; BG3VOFS, high
    ; ---- the two FALLBACK scrolls -----------------------------------------
    ; What a column falls back to when its enable bit is clear. BG2's is the
    ; melt's calm level under the plates and is visible in sixteen columns of
    ; every frame; BG1's is unobservable — the gap columns are transparent at
    ; every row — and is written anyway, because a register nobody establishes
    ; holds whatever the previous scene left in it (rule 5).
    lda #<SMT_VOFS_BG1
    sta a:$210E                     ; BG1VOFS, low
    lda #>SMT_VOFS_BG1
    sta a:$210E                     ; BG1VOFS, high
    lda #<SMT_VOFS_BG2
    sta a:$2110                     ; BG2VOFS, low
    lda #>SMT_VOFS_BG2
    sta a:$2110                     ; BG2VOFS, high
    stz a:$210D                     ; BG1HOFS, low
    stz a:$210D                     ; BG1HOFS, high
    stz a:$210F                     ; BG2HOFS, low
    stz a:$210F                     ; BG2HOFS, high
    ; ---- the composed screen/blend state ----------------------------------
    ; TM turns on the two layers `smt_bg` designates — and NOT BG3, which this
    ; scene does not designate and could not: a bg3 designation beside an
    ; offset table is refused by name.
    lda #ES_SCR_WORKS_TM
    sta a:$212C
    lda #ES_SCR_WORKS_TS
    sta a:$212D
    lda #ES_SCR_WORKS_CGWSEL
    sta a:$2130                     ; `blend_off`'s composed off state — this
    lda #ES_SCR_WORKS_CGADSUB       ;   scene arms no blend, and composing the
    sta a:$2131                     ;   off state is what stops it inheriting
                                    ;   one across an edge
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) -----------------
; In/out: A16/I16, DB=0.
;
; TS_STEP IS EXPANDED ONCE, AT THE TOP, and its output is read by the one add
; that consumes it. The step is in WHOLE phases; the fraction it could not
; publish this frame is carried in the accumulator to the next, which is what
; makes a PAL run walk the same 64 rows in the same wall-clock time as an NTSC
; one.
tick:
    .a16
    .i16
    TS_STEP z:US_TSC_ACC, SMT_PHASE_BASE
    sta z:US_TSC
    ; ---- the columns advance every frame, flat or not ----------------------
    ; UNCONDITIONALLY, and that is what makes the toggle a control: flattening
    ; changes ONE thing (which row the transfer reads) and leaves the
    ; animation's position alone, so un-flattening resumes rather than
    ; restarts.
    lda z:US_TSC
    jsr smt_advance
    ; ---- the knight's two rates, and then the knight ----------------------
    ; The gravity arm branches on the region BEFORE the macro, because the
    ; second factor of r lives in the BASE (see the header). Anonymous labels
    ; rather than cheap ones: TS_STEP's own `.local` labels are plain, so a
    ; `@name` here would collide with the expansion's.
    TS_STEP z:US_TSKR_ACC, TS_RUN_BASE
    sta z:US_TSKR
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:US_TSKG_ACC, TS_GRAV_BASE_R
    bra :++
:   .a16
    .i16
    TS_STEP z:US_TSKG_ACC, TS_GRAV_BASE
:   .a16
    .i16
    sta z:US_TSKG
    jsr smt_kn_tick
    jsr smt_kn_draw
    ; ---- B: latch the flat control ----------------------------------------
    lda z:ES_INP_PRESS
    and #JOY_B
    beq @no_toggle
    lda z:ES_SMT_FLATSEL
    eor #1
    sta z:ES_SMT_FLATSEL
@no_toggle:
    .a16
    .i16
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @done
    sep #$20
    .a8
    SM_SWITCH "WORKS", "TITLE"
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

; --- exit: nothing to tear down --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked.
;
; THE TABLE IS NOT TORN DOWN HERE, and that is the design rather than an
; omission: what this scene leaves behind is BG3SC still pointing at a page of
; scroll words and both VOFS ports at their fallbacks, and the successor
; re-establishes all of it. Tearing down here would put the obligation in the
; scene that is leaving, where nothing can check it — the title scene's enter
; is where it is visible and where `bg_text`'s own `scene_writes` consent
; already covers it.
exit:
    .a16
    .i16
    rts
.endscope
