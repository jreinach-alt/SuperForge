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
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    lda #ES_H_MIL_VROW_DMAP
    sta a:MIL_ROW_REGS + 0
    lda #ES_H_MIL_VROW_BBAD
    sta a:MIL_ROW_REGS + 1
    lda #^mil_row_bin
    sta a:MIL_ROW_REGS + 4
    rep #$20
    .a16
    ; ---- WHICH ROW OF BG3'S MAP. Mode 4 reads the row BG3VOFS selects, and
    ; only that one — there is no second row to keep in step, which is the
    ; other half of what "one word a column" buys.
    lda #ES_V_MIL_TAB
    sta a:$2116
    lda #SMIL_ROW_BYTES
    sta a:MIL_ROW_REGS + 5          ; DAS (re-armed for THIS transfer)
    ; ---- which phase, and publish the one this frame is drawn FROM --------
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
    sta a:MIL_ROW_REGS + 2          ;   16-bit add cannot leave the bank
    sep #$20
    .a8
    lda #(1 << ES_H_MIL_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
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
    lda #SMIL_BG1_REST
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rep #$20
    .a16
    lda #SMIL_BG2_REST
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
