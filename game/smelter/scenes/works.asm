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
    stz z:US_TSC_ACC                ; the timebase's carried fraction
    stz z:US_TSC
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
