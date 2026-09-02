; =============================================================================
; mil_opt.asm — one row a frame, and bit 15 picks each column's axis
; =============================================================================
; MODE 4 FETCHES ONE OFFSET WORD PER COLUMN, not two. Modes 2 and 6 run
; GetHorizontalOffsetByte AND GetVerticalOffsetByte inside a column's group;
; mode 4 runs only the first, and bit 15 of the word it returns decides whether
; the value lands on vScroll or hScroll (Mesen2 SnesPpu.cpp FetchTileData case
; 2 under BgMode 4, and the bit-15 test at :156-161).
;
; So this rail uploads ONE 32-word row a frame — 64 B, one transfer, no HDMA
; channel — and every column on screen moves on the axis its own word names.
; Smelter uploads the same 64 B for a V row and a second, all-zero H row it
; never uses, because mode 2 fetches a word for each axis whether or not you
; mean to use one.
;
; THE ROW IS CHOSEN BY PHASE, NOT COUNTED IN FRAMES. ES_MIL_PHASE is the
; accumulated output of the scene's TS_STEP, so the animation is region-correct
; with no clock of its own and holds still exactly when the phase does.
;
; TICK: ok -- the row index is a function of the accumulated PHASE, which the
;   scaler already expressed against the declared tick. Nothing here counts
;   frames.

MIL_ROW_REGS = $4300 + ES_H_MIL_VROW_CH * 16

; THE FIELD CONSTANTS ARE THE INCLUDING SCENE'S. The composition emits one
; set per scene (ES_OPT_HALL_*, ES_OPT_MELT_*), and this file is included
; inside each scene's .scope after the scene has aliased its own set to the
; four names below -- so the walker reads the declaration of the room it is
; serving, and a room that forgot to alias does not assemble.
.ifndef MIL_OPT_BG1
    .error "mil_opt.asm: alias MIL_OPT_BG1/BG2/VSEL/MASK to this scene's ES_OPT_* before including it"
.endif

; --- mil_nmi_row: the offset row, every armed VBlank ------------------------
; CONTRACT mil_nmi_row
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_MIL_PHASE — the current phase, 0..SMIL_PHASES-1
;             ES_MIL_FLATSEL — 0 = the running row, 1 = the flat control
;   out:      BG3's offset row rewritten with the 32 words for this phase, and
;             ES_MIL_SHOWN published with the phase they came from
;   clobbers: A, X, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. It programs its own VMAIN and VMADD, so where it sits
;             in the hook is free
;   tail:     rts
;
; DAS is single-shot — the transfer consumes it — so it is armed inside this
; routine, once, for the one transfer it fires.
mil_nmi_row:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_nmi_row"
    jsr mil_row_regs
    rep #$20
    .a16
    lda #SMIL_ROW_BYTES
    sta a:MIL_ROW_REGS + 5          ; DAS (re-armed for THIS transfer)
    jsr mil_row_source
    ldx #0
    jsr mil_stage_row_into
    jsr mil_commit_vofs             ; ...and the fallback both layers use
    sep #$20
    .a8
    lda #(1 << ES_H_MIL_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
    rts

; --- mil_row_regs: the transfer's registers, bar DAS ------------------------
; CONTRACT mil_row_regs
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      VMAIN, the channel's DMAP/BBAD/A1T/A1B and VMADD programmed for
;             a word-port transfer from the staging buffer to the table's
;             first row. DAS is NOT here: it is the caller's, because it is
;             the one thing the hall (one row) and the melt (two) disagree on
;   clobbers: A, N, Z
;   assumes:  VBlank
;   tail:     rts
mil_row_regs:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_row_regs"
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    lda #ES_H_MIL_VROW_DMAP
    sta a:MIL_ROW_REGS + 0
    lda #ES_H_MIL_VROW_BBAD
    sta a:MIL_ROW_REGS + 1
    lda #^ES_MIL_STAGE_LONG
    sta a:MIL_ROW_REGS + 4          ; the source is WRAM, not ROM: the camera
                                    ;   has to be folded in first
    rep #$20
    .a16
    ; ---- WHICH ROW OF BG3'S MAP. Mode 4 reads the row BG3VOFS selects; the
    ; hall keeps that at row 0 for the whole frame, and the melt's channel
    ; walks it per band (mil_melt.asm). Both restage from row 0 up.
    lda #ES_V_MIL_TAB
    sta a:$2116
    lda #.loword(ES_MIL_STAGE_LONG)
    sta a:MIL_ROW_REGS + 2          ; A1T: the STAGED rows, not the ROM rows
    sep #$20
    .a8
    rts

; --- mil_row_source: this phase's hall row (or the flat control) -----------
; CONTRACT mil_row_source
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MIL_PHASE — the current phase, 0..SMIL_PHASES-1
;             ES_MIL_FLATSEL — 0 = the running row, 1 = the flat control
;   out:      ES_MIL_NMI_SCRATCH+0..2 — the ROM row's 24-bit address, and
;             ES_MIL_SHOWN published with the phase it came from
;   clobbers: A, N, Z, C
;   assumes:  VBlank
;   tail:     rts
mil_row_source:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_row_source"
    lda z:ES_MIL_FLATSEL
    bne @flat
    lda z:ES_MIL_PHASE
    bra @pick
@flat:
    .a16
    .i16
    lda #SMIL_FLAT_INDEX
@pick:
    .a16
    .i16
    sta z:ES_MIL_SHOWN              ; ...what a test must join on, not the
                                    ;   counter the main thread will advance
    .repeat ::SMIL_PHASE_SHIFT      ; `::` — this file is included inside the
    asl a                           ;   scene's .scope and .repeat needs its
    .endrepeat                      ;   count as a constant at parse time
    clc
    adc #.loword(mil_row_bin)       ; the blob fits one 32 KB window, so this
    sta z:ES_MIL_NMI_SCRATCH        ;   16-bit add cannot leave the bank
    sep #$20
    .a8
    lda #^mil_row_bin
    sta z:ES_MIL_NMI_SCRATCH + 2    ; ...and the bank, for the long read
    rep #$20
    .a16
    rts

; --- mil_commit_vofs: the two V fallbacks, every armed VBlank ---------------
; CONTRACT mil_commit_vofs
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1VOFS and BG2VOFS set to the camera
;   clobbers: A, N, Z
;   assumes:  VBlank
;   tail:     rts
;
; THIS IS WHERE EVERY UNDRIVEN COLUMN GETS ITS VERTICAL POSITION, and it is a
; per-frame port now rather than an enter-time one. A column whose word does not
; carry a layer's enable bit shows that layer at its own BGnVOFS — and on this
; rail that is most of the screen: the pier, both stations' conveyor bays and
; the whole tail run take BG1 from here, and every shaft and upright column
; takes BG2 from here. Left at their enter values they would hold still while
; the driven columns climbed, which is the same defect as the staging routine's
; and the opposite half of it.
;
; WIDTH-RISK: the loads are A16 so `xba` serves the high byte of a 10-bit
; write-twice latch. The A8 form of this shipped on smelter and the damage was
; invisible only because both its maps repeated every 256 px.
mil_commit_vofs:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_commit_vofs"
    lda z:ES_MIL_CAM
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; ...high
    rep #$20
    .a16
    lda z:ES_MIL_CAM
    sep #$20
    .a8
    sta a:$2110                     ; BG2VOFS, low
    xba
    sta a:$2110
    rep #$20
    .a16
    rts

; --- mil_stage_row_into: a ROM row + the camera, into a staged row ---------
; CONTRACT mil_stage_row_into
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X — the destination's byte offset in the staging buffer: 0 for
;             the table's first row, SMIL_ROW_BYTES for its second
;             ES_MIL_NMI_SCRATCH+0..2 — the ROM row's 24-bit address
;   out:      SMIL_COLS words at ES_MIL_STAGE_LONG + X, each VERTICAL word
;             carrying the camera, and ES_MIL_CAM_SHOWN published with the
;             camera they were built from
;   clobbers: A, X, Y, N, Z, C
;   assumes:  VBlank, called only from a rail's NMI row routine
;   tail:     rts
;
; THE CAR RIDES IN ROW 0 ONLY. The override that puts the scene's car
; displacement into the lift's four columns applies to the hall's row; a
; ripple row staged at another offset gets its own words unchanged, because
; below the deck those columns are channel, and the channel ripples.
;
; AN OFFSET WORD REPLACES A LAYER'S SCROLL, IT DOES NOT ADD TO IT — the
; hardware computes vScroll = word & $3FF for that column (SnesPpu.cpp:160) and
; discards BGnVOFS entirely. So a column the table drives does NOT follow the
; camera unless the camera is IN the word, and a rail that scrolled without
; this would show its machines nailed to the screen while the hall moved past
; them. It is the vertical twin of smelter's world-space table: there the READ
; HEAD moved with a horizontal camera, here the VALUES move with a vertical one.
;
; ONLY THE VERTICAL WORDS GET IT. A horizontal word's value is a belt phase and
; has nothing to say about where the camera is; the columns it drives take
; their vertical position from BG2VOFS like any undriven column. The axis bit
; picks who gets the add, and it is the same bit the PPU will read.
;
; BOTH ENDS ARE LONG-ADDRESSED. The row is in ROM (bank from `^`, carried in
; the scratch) and the staging buffer is in WRAM above $2000, which under LoROM
; is ROM in bank 0 — `sta a:` there writes to the cartridge and reads back what
; was always there. The repo has paid for that one twice; ES_MIL_STAGE_LONG is
; the allocator's 24-bit form and exists to make it unspellable.
;
; WIDTH-RISK: A16 throughout. The add is 16-bit and the mask puts it back
; inside the ten value bits — a carry into bit 10 sets no enable bit but does
; silently halve the offset the PPU reads.
mil_stage_row_into:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_stage_row_into"
    lda z:ES_MIL_CAM
    sta z:ES_MIL_CAM_SHOWN          ; ...the camera THIS frame is drawn from
    stx z:ES_MIL_NMI_SCRATCH + 8    ; the destination's base: 0 = the car's row
    ldy #0
@word:
    .a16
    .i16
    lda [ES_MIL_NMI_SCRATCH], y     ; the ROM row's word for this column
    ; ...the ELEVATOR's four columns — in ROW 0 ONLY (see above)...
    ldx z:ES_MIL_NMI_SCRATCH + 8
    bne @not_car
    ; ...MINUS THE LEAD, because Y walks TABLE
    ; INDICES and index j displaces SCREEN column j + SMIL_LEAD. Without it the
    ; override lands one column right of the car: its three right-hand columns
    ; ride and its LEFT EDGE STAYS BEHIND, driven by the phase table it should
    ; have stopped reading. The generator bakes the same lead into the blob;
    ; this is the one place that reads the blob back and has to undo it.
    cpy #((SMIL_CAR_COL - SMIL_LEAD) * 2)
    bcc @not_car
    cpy #((SMIL_CAR_COL - SMIL_LEAD + SMIL_SHAFT_COLS) * 2)
    bcs @not_car
    and #(MIL_OPT_BG1 | MIL_OPT_BG2 | MIL_OPT_VSEL)
    ora z:ES_MIL_CAR                ; THE CAR IS DRIVEN BY THE SCENE, not by
                                    ;   the phase: a cutscene is a performance.
                                    ;   The ROM row still supplies its ENABLE
                                    ;   and AXIS bits, so the flat control row
                                    ;   still flattens it and the column is
                                    ;   declared in one place.
@not_car:
    .a16
    .i16
    bit #MIL_OPT_VSEL           ; ...vertical?
    beq @store                      ; no: a belt phase, not the camera's business
    sta z:ES_MIL_NMI_SCRATCH + 4
    and #MIL_OPT_MASK
    clc
    adc z:ES_MIL_CAM
    and #MIL_OPT_MASK           ; ...back inside the ten value bits
    sta z:ES_MIL_NMI_SCRATCH + 6
    lda z:ES_MIL_NMI_SCRATCH + 4
    and #(MIL_OPT_BG1 | MIL_OPT_BG2 | MIL_OPT_VSEL)
    ora z:ES_MIL_NMI_SCRATCH + 6
@store:
    .a16
    .i16
    sta z:ES_MIL_NMI_SCRATCH + 4    ; park the word while X is computed
    tya
    clc
    adc z:ES_MIL_NMI_SCRATCH + 8    ; the destination: base + the index
    tax
    lda z:ES_MIL_NMI_SCRATCH + 4
    sta f:ES_MIL_STAGE_LONG, x
    iny
    iny
    cpy #SMIL_ROW_BYTES
    bcc @word
    rts

; --- mil_arm_scroll: the four fallback ports, once at enter -----------------
; CONTRACT mil_arm_scroll
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1/BG2 H and V scroll set to the rail's rest position
;   clobbers: A, N, Z
;   assumes:  forced blank at scene enter
;   tail:     rts
;
; THESE ARE THE FALLBACK, NOT THE CAMERA. A column whose word does not carry a
; layer's enable bit shows that layer at its own BGnVOFS/BGnHOFS — so on this
; rail BG1's ports are what every BELT column shows for BG1, and BG2's are what
; every PISTON column shows for BG2. Both are the picture at rest, which is why
; the hall does not tear along a bay boundary.
;
; SCREEN COLUMN 0 CANNOT BE DISPLACED AT ALL — the offset latches are cleared
; at the start of each scanline's fetch (SnesPpu.cpp:284-287) — so whatever
; these hold IS the leftmost column, and no word can reach it. This rail
; answers that by DRAWING it rather than paying it off: column 0 is the hall's
; left buttress, opaque on BG1, and a wall that does not move is the room. The
; rail's first cut left a piston housing there instead and it read as a broken
; machine, which it was — see the generator's LEAD block, and note that the
; SAME fetch rule is the reason the words are stored a column early.
;
; WIDTH-RISK: the H ports are 10-bit write-twice latches and the LOAD IS A16.
; `xba` serves B, which holds the high byte only if the value was loaded
; sixteen bits wide — smelter shipped the A8 form of this and the damage was
; invisible because both its maps repeated every 256 px.
mil_arm_scroll:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_arm_scroll"
    lda z:ES_MIL_CAM
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rep #$20
    .a16
    lda z:ES_MIL_CAM
    sep #$20
    .a8
    sta a:$2110                     ; BG2VOFS, low
    xba
    sta a:$2110
    rep #$20
    .a16
    ; The H fallbacks are zero and stay zero: nothing on this rail scrolls the
    ; picture, only the table displaces it. `stz` rather than the loaded form
    ; above BECAUSE it is zero — there is no high byte to get wrong.
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS, low
    stz a:$210D                     ; ...high
    stz a:$210F                     ; BG2HOFS, low
    stz a:$210F                     ; ...high
    rep #$20
    .a16
    rts

; --- mil_advance: one step of the phase ------------------------------------
; CONTRACT mil_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = this frame's WHOLE phase step (a TS_STEP output)
;   out:      ES_MIL_PHASE advanced and wrapped into 0..SMIL_PHASES-1
;   clobbers: A, N, Z, C
;   assumes:  the main thread
;   tail:     rts
;
; TICK: ok -- the step arrives already scaled; nothing here counts frames.
mil_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_advance"
    clc
    adc z:ES_MIL_PHASE
    cmp #SMIL_PHASES
    bcc :+
    sec
    sbc #SMIL_PHASES
:   .a16
    .i16
    sta z:ES_MIL_PHASE
    rts

; --- mil_zero_row: BG3's offset row, with no enable bit in it ---------------
; CONTRACT mil_zero_row
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      SMIL_COLS zero words at BG3's offset row
;   clobbers: A, X, N, Z
;   assumes:  forced blank at scene enter
;   tail:     rts
;
; A MODE-4 SCENE THAT WANTS NO OFFSETS STILL HAS AN OFFSET TABLE. The PPU reads
; BG3's map as per-column scroll words whenever the mode says so, and it does
; not ask whether the scene meant it. So a flat room in this mode disarms the
; table by its CONTENT: no enable bit set anywhere, therefore no column
; displaced, therefore both layers scroll from BGnHOFS/BGnVOFS like an ordinary
; screen.
;
; That is the same hygiene obligation `smelter`'s title discharges by
; re-pointing BG3SC at a text map. This rail stays in ONE MODE across its edge,
; so it cannot point the table away — it has to mean nothing instead.
mil_zero_row:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_zero_row"
    lda #ES_V_MIL_TAB
    ; falls into mil_zero_row_at with A = the table's first row

; --- mil_zero_row_at: a row of zeros at the word address in A --------------
; CONTRACT mil_zero_row_at
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A — the VRAM word address of the row
;   out:      SMIL_COLS zero words written there through the word port
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank
;   tail:     rts
mil_zero_row_at:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_zero_row_at"
    sta a:$2116                     ; VMADD
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    ldx #0
@zero:
    .a8
    .i16
    ; EIGHT-BIT STORES, ONE WORD A TURN. This loop ran in A16 until the melt
    ; read its zero row back: a 16-bit `stz $2118` writes both port bytes and
    ; steps the address, and the 16-bit `stz $2119` after it writes the NEXT
    ; word's high byte and $211A (M7SEL) -- two words consumed per iteration,
    ; every odd word's low byte left stale, and the loop's 32 turns reaching
    ; 64 words. Harmless by luck: the enable bits are in the high byte, which
    ; was zeroed, and mode 4 does not read M7SEL. Not harmless as a
    ; statement of what the row holds.
    stz a:$2118                     ; the word port, low
    stz a:$2119                     ; ...and high
    inx
    cpx #SMIL_COLS
    bcc @zero
    rep #$20
    .a16
    rts
