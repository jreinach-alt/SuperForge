; =============================================================================
; smt_opt.asm — offset-per-tile: BG3's tilemap as a per-column scroll table
; =============================================================================
; THE WHOLE MECHANISM, stated once. In modes 2, 4 and 6 the PPU's per-column
; fetch reads two extra words out of BG3's tilemap and uses them as that
; column's scroll (Mesen2 Core/SNES/SnesPpu.cpp, FetchTileData cases 2 and 3
; under BgMode 2, and GetTilemapData at :153-169). Bit 13 of a word applies it
; to BG1, bit 14 to BG2, and bits 9-0 are the value. The vertical word
; REPLACES the layer's own BGnVOFS for that column; a column with its bit
; clear falls back to it.
;
; WHICH TWO WORDS: BG3HOFS picks the column (8 px granular) and BG3VOFS picks
; WHICH ROW of BG3's map is the horizontal row; the vertical row is that row
; plus 0x20 words, wrapping inside the map (:273). Both are zero here, so row
; 0 is the H row and row 1 is the V row — and only row 1 is rewritten per
; frame, because this table is vertical-only.
;
; THERE IS NO HDMA CHANNEL IN THIS FILE. That is the point of the whole rail:
; every other per-column effect in this tree spends a channel running the
; length of the picture, and this one spends none. The per-frame cost is one
; 64 B VBlank transfer of the row, declared in feature.toml, and it does not
; change with how many columns move.

; The VBlank transfer's register file, addressed through the channel the
; `smt_vrow` hdma claim names.
SMT_ROW_REGS = $4300 + ES_H_SMT_VROW_CH * 16

; --- smt_arm_rows: the table's two rows, into VRAM (scene enter) ------------
; CONTRACT smt_arm_rows
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the all-zero H row in BG3 map row 0, and the flat control row in
;             map row 1, so the very first displayed frame is a declared
;             picture rather than whatever VRAM held
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; THE FIRST V ROW IS UPLOADED HERE and not left to the first VBlank, because
; between the display coming out of forced blank and the first armed NMI there
; is at least one frame, and VRAM at that point holds whatever the previous
; scene left — offset words made of a font, or of nothing. Rule 5: never
; assume a region you did not write.
;
; BG3SC, BG3HOFS AND BG3VOFS ARE NOT WRITTEN HERE. The offset composition owns
; those three ports and grants its consent to SCENE-ENTER code (docs/100 §6),
; which is where they are written — beside the composed BGMODE, because the
; two together are what make this a mode-2 scene whose BG3 is a table. A
; write here would be a second writer of a port this feature declares no
; [[claims.reg]] for, and `no_literals` refuses it by name.
smt_arm_rows:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_arm_rows"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- row 0: the horizontal words, all zero ---------------------------
    ; Mode 2 fetches an H word for every column whether or not one is wanted,
    ; so "vertical only" is expressed by a row with neither enable bit set —
    ; not by leaving the row unwritten.
    lda #ES_V_SMT_TAB
    sta a:$2116
    ldx #.loword(smt_hrow_bin)
    ldy #ES_R_SMT_HROW_SIZE
    lda #^smt_hrow_bin
    jsr smt_up_dma
    ; ---- row 1: the flat control, as the opening picture ------------------
    lda #(ES_V_SMT_TAB + SMT_COLS)
    sta a:$2116
    ldx #(.loword(smt_col_bin) + SMT_FLAT_INDEX * SMT_ROW_BYTES)
    ldy #SMT_ROW_BYTES
    lda #^smt_col_bin
    jsr smt_up_dma
    rts

; --- smt_advance: one frame of the animation phase --------------------------
; CONTRACT smt_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = this frame's step in WHOLE phases (a TS_STEP output)
;   out:      ES_SMT_PHASE advanced and wrapped into 0..SMT_PHASES-1
;   clobbers: A, N, Z, C
;   assumes:  main thread. The VBlank commit READS the accumulator; this
;             writes it, which is lakeside's division between the feature that
;             consumes a quantity and the scene that drives it
;   tail:     rts
;
; TICK: ok -- the step arrives already scaled. The caller applies TS_STEP to
;   SMT_PHASE_BASE and hands the result in; nothing here counts frames and
;   there is no per-frame immediate in this routine.
;
; THE WRAP IS A MASK, and that is a property of SMT_PHASES rather than a
; convenience: 64 is a power of two AND the point at which every plate's
; harmonic and every jet's completes a whole number of cycles, so the
; animation closes there with no seam. tools/gen_smelter_assets.py is where
; those two facts meet.
smt_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_advance"
    clc
    adc z:ES_SMT_PHASE
    and #(SMT_PHASES - 1)
    sta z:ES_SMT_PHASE
    rts

; --- smt_nmi_row: the V row, every armed VBlank -----------------------------
; CONTRACT smt_nmi_row
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_SMT_PHASE — the current phase, 0..SMT_PHASES-1
;             ES_SMT_FLATSEL — 0 = the running table, 1 = the flat control
;   out:      BG3's V row rewritten with the 32 words for this phase, so the
;             next frame's every column is displaced by the amount the ROM
;             holds for it
;   clobbers: A, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. It programs its own VMAIN and VMADD, so where it
;             sits in the hook is free — the rule a new VBlank VRAM writer
;             answers is "program your own, or be ordered last".
;             sm_nmi_core re-arms $4300 from the scene's HDMA shadow AFTER the
;             hook returns, which is what makes using a channel here legal
;   tail:     rts
;
; ONE CONTIGUOUS 64 B BLOCK, ONE TRANSFER, THE SAME SIZE EVERY FRAME — so the
; `[claims.dma]` declaration in feature.toml is exact rather than a worst case,
; and the allocator proves it against the substrate's measured VBlank budget.
;
; THE ROW IS CHOSEN BY PHASE, NOT COUNTED IN FRAMES. ES_SMT_PHASE is the
; accumulated output of the scene's TS_STEP, so it is already a region-correct
; quantity and the animation inherits that correctness with no clock of its
; own — it holds still exactly when the phase stops advancing, and its cycle
; closes on the 64 rows the blob holds.
;
; TICK: ok -- the row index is a function of the accumulated PHASE, which the
;   scaler already expressed against the declared tick. Nothing here counts
;   frames.
;
; DAS is single-shot — the transfer consumes it — so it is armed inside this
; routine, once, for the one transfer it fires.
smt_nmi_row:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "smt_nmi_row"
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    lda #ES_H_SMT_VROW_DMAP
    sta a:SMT_ROW_REGS + 0          ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_H_SMT_VROW_BBAD
    sta a:SMT_ROW_REGS + 1          ; BBAD: VMDATAL
    lda #^smt_col_bin
    sta a:SMT_ROW_REGS + 4          ; A1B: the blob's own bank
    rep #$20
    .a16
    lda #(ES_V_SMT_TAB + SMT_COLS)
    sta a:$2116                     ; VMADD = BG3's V row (row 1 of the map)
    lda #SMT_ROW_BYTES
    sta a:SMT_ROW_REGS + 5          ; DAS (re-armed for THIS transfer)
    ; ---- which row ---------------------------------------------------------
    ; The flat control selects the blob's last row. THE MECHANISM IS NOT
    ; DISARMED BY IT: the same channel fires the same 64 B into the same
    ; place, and the row it moves has every enable bit still set with every
    ; value at its base. Exactly one variable moves between running and flat,
    ; which is what makes the flat frame a control rather than a second
    ; unexplained state.
    lda z:ES_SMT_FLATSEL
    bne @flat
    lda z:ES_SMT_PHASE              ; already wrapped by smt_advance
    bra @pick
@flat:
    .a16
    .i16
    lda #SMT_FLAT_INDEX
@pick:
    .a16
    .i16
    ; `::` IS LOAD-BEARING. This file is included inside the works scene's
    ; `.scope`, and `.repeat` needs its count as a CONSTANT at the moment it
    ; is parsed — an unqualified name inside a scope becomes a scope-local
    ; forward reference, which is not one, and ca65 says only "Constant
    ; expression expected". smt_art.inc is included at FILE scope by main.asm
    ; (both scenes read its geometry), so the global qualifier is what makes
    ; the value available here. water.asm avoids the question by including its
    ; own art .inc inside the scope; this rail cannot, because the title scene
    ; reads the same constants.
    .repeat ::SMT_PHASE_SHIFT
    asl a                           ; ...the row's offset, in blob bytes
    .endrepeat
    sta z:ES_SMT_NMI_SCRATCH + 4    ; ...the ROW's base, kept for column 0
    ; ---- WHERE IN THE ROW: the camera, and the one-column lead -------------
    ; The row is WORLD-space, so scrolling is an addition here and nothing
    ; else. The transfer wants world columns cam+1 .. cam+32, because the word
    ; at BG3 map column j displaces SCREEN column j+1 — the lead, measured on
    ; this binary and now paid at the read head instead of baked into the blob.
    lda z:ES_SMT_CAM
    sta z:ES_SMT_CAM_SHOWN          ; ...the camera THIS frame is drawn from
    .repeat 3
    lsr a                           ; ...to a whole column
    .endrepeat
    sta z:ES_SMT_NMI_SCRATCH + 2    ; the camera's own column, for below
    inc a                           ; ...+1: the fetch lead, paid here at the
    asl a                           ;   read head rather than baked in the blob
    clc
    adc z:ES_SMT_NMI_SCRATCH + 4
    clc
    adc #.loword(smt_col_bin)       ; the blob fits one 32 KB window, so this
    sta a:SMT_ROW_REGS + 2          ;   16-bit add cannot leave the bank
    sep #$20
    .a8
    lda #(1 << ES_H_SMT_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
    ; ---- the two H ports: the camera itself --------------------------------
    ; Write-twice latches, low byte then high. The table quantises to 8 px and
    ; these do not, which is the whole reason the pair works: the read head
    ; steps one word as the camera crosses each 8-px boundary and the layers
    ; carry the sub-column remainder, so the two never disagree.
    ;
    ; THE LOAD IS A16 AND THAT IS THE WHOLE POINT OF THESE FOUR LINES. `xba`
    ; swaps A with B, so the byte it hands the high write is only the camera's
    ; high byte if the camera was loaded SIXTEEN BITS WIDE. Written in A8 this
    ; reads the low byte alone and `xba` then serves whatever the previous
    ; 16-bit operation happened to leave in B — here the DMA source address's
    ; high byte, computed four instructions earlier, which changes with the
    ; phase. BGnHOFS is 10 bits, so that lands in bits 8-9 and scrolls both
    ; layers by a multiple of 256 px; the maps repeat every 256, so the picture
    ; is IDENTICAL and nothing downstream can see it. A garbage write whose
    ; damage is invisible is still a garbage write.
    ;
    ; WIDTH-RISK: entry A8. The rep/sep pair below is a forced narrowing, and
    ; the accumulator is returned to A8 for the fall-through.
    rep #$20
    .a16
    lda z:ES_SMT_CAM                ; ...both bytes, so B is the camera's high
    sep #$20
    .a8
    ; EACH PORT'S PAIR IS WRITTEN CONSECUTIVELY, not interleaved. These are
    ; write-twice latches and the two ports were being driven low, low, high,
    ; high; keeping each register's two bytes adjacent costs nothing and
    ; removes the question entirely. Not a claim about a shared latch — an
    ; unnecessary interleave beside a bug that had just been found here is not
    ; worth defending.
    sta a:$210D                     ; BG1HOFS, low
    xba
    sta a:$210D                     ; BG1HOFS, high
    xba
    sta a:$210F                     ; BG2HOFS, low
    xba
    sta a:$210F                     ; BG2HOFS, high
    xba
    ; ---- SCREEN COLUMN 0, WHICH THE HARDWARE CANNOT DISPLACE ---------------
    ; The offset latches are cleared at the start of each scanline's fetch, so
    ; the leftmost column always shows its layer's own BGnVOFS. On a static
    ; screen that is one column at the fallback and the rail simply asserted
    ; it. Under scrolling it would be a permanently WRONG column travelling
    ; along the left edge — so the fallback register is made to carry that
    ; column's own value. The hardware limit is not worked around; the port it
    ; falls back to is loaded with the right answer.
    ;
    ; The word is read from the SAME ROW the transfer just moved, at the
    ; camera's own column — which is why the blob no longer bakes the lead in.
    ; One column drives one layer, and the other layer is either transparent
    ; there (BG1 over a gap) or calm by construction (the melt under a plate),
    ; so the one word settles both.
    rep #$20
    .a16
    lda z:ES_SMT_NMI_SCRATCH + 2
    asl a
    clc
    adc z:ES_SMT_NMI_SCRATCH + 4
    tax
    lda f:smt_col_bin, x
    sta z:ES_SMT_NMI_SCRATCH
    and #ES_OPT_WORKS_BG1
    beq @col0_gap
    lda z:ES_SMT_NMI_SCRATCH
    and #ES_OPT_WORKS_MASK
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rep #$20
    .a16
    lda #SMT_VOFS_BG2               ; ...and the melt is calm under a plate
    bra @col0_bg2
@col0_gap:
    .a16
    .i16
    lda z:ES_SMT_NMI_SCRATCH
    and #ES_OPT_WORKS_MASK
@col0_bg2:
    .a16
    .i16
    sep #$20
    .a8
    sta a:$2110                     ; BG2VOFS, low
    xba
    sta a:$2110                     ; BG2VOFS, high
    rep #$20
    .a16
    sep #$20
    .a8
    ; fall through — the same channel, re-armed, for the melt's CHR

; --- smt_nmi_melt: the melt's CHR, every armed VBlank -----------------------
; CONTRACT smt_nmi_melt
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_SMT_PHASE — the current phase, 0..SMT_PHASES-1
;   out:      the four animated CHR slots rewritten with this frame's pixels,
;             so the lava churns under a tilemap that never changes
;   clobbers: A, N, Z, C
;   assumes:  VBlank, immediately after smt_nmi_row, in the same A8/I16
;             convention. It programs its own VMADD and RE-ARMS DAS, because
;             the row transfer above CONSUMED it
;   tail:     rts
;
; THE CLASSIC BG ANIMATION, and the cheapest thing in this rail after the
; offset row itself: 128 B into four contiguous CHR slots and the whole melt
; changes. No tilemap word moves, no second layer is spent, and the columns go
; on being displaced by exactly the same table — the swap is under the picture
; the offsets bend, not beside it.
;
; DAS IS SINGLE-SHOT AND THE ROW ABOVE ALREADY SPENT IT. This is the second
; transfer on the same channel in the same VBlank, so DAS is re-armed here;
; the tree's own lesson, and the reason `vblank_transfers_per_frame` is 2.
;
; NOT DISARMED BY THE FLAT CONTROL, deliberately. B selects the offset table's
; flat row and nothing else: if it also froze the lava, running and flat would
; differ in TWO things and the comparison could not attribute what it showed.
; The control isolates the table, so the lava churns in both states.
;
; TICK: ok -- the frame index is a function of the accumulated PHASE, the same
;   already-scaled quantity the row index is. Nothing here counts frames, and
;   SMT_MELT_ANIM_FRAMES << SMT_MELT_ANIM_SHIFT divides SMT_PHASES, so the
;   cycle closes with the loop rather than across it.
smt_nmi_melt:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "smt_nmi_melt"
    lda #^smt_melt_anim_bin
    sta a:SMT_ROW_REGS + 4          ; A1B: the animation blob's own bank
    rep #$20
    .a16
    lda #(ES_V_SMT_CHR + ::SMT_MELT_ANIM_FIRST * 16)
    sta a:$2116                     ; VMADD = the first animated CHR slot
    lda #::SMT_MELT_ANIM_BYTES
    sta a:SMT_ROW_REGS + 5          ; DAS, re-armed: the row transfer spent it
    ; ---- which frame ------------------------------------------------------
    lda z:ES_SMT_PHASE
    .repeat ::SMT_MELT_ANIM_SHIFT
    lsr a
    .endrepeat
    and #(::SMT_MELT_ANIM_FRAMES - 1)
    .repeat ::SMT_MELT_ANIM_LOG2_BYTES
    asl a                           ; ...the frame's offset, in blob bytes
    .endrepeat
    clc
    adc #.loword(smt_melt_anim_bin) ; one bank, asserted at the .incbin
    sta a:SMT_ROW_REGS + 2
    sep #$20
    .a8
    lda #(1 << ES_H_SMT_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
    ; ---- and the wall's colours, which are not a transfer at all ----------
    ; SIXTEEN BYTES OF CGRAM, written by the feature that OWNS the palette.
    ; The wall's pattern lives in its eight colours rather than in its pixels,
    ; so rotating them walks a band of lightness across the layer — the only
    ; motion available to a surface that has to stay invariant under vertical
    ; displacement. `smt_bg` does the writing because `smt_mpal` is its claim;
    ; this scene decides the step, because the phase is the scene's.
    rep #$20
    .a16
    lda z:ES_SMT_PHASE
    .repeat ::SMT_WALL_PAL_SHIFT
    lsr a
    .endrepeat
    and #(::SMT_WALL_PAL_FRAMES - 1)
    jsr smt_wall_glow
    sep #$20
    .a8
    rts

; --- smt_plate_top: where a plate's surface is, this frame ------------------
; CONTRACT smt_plate_top
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the plate index, 0..SMT_PLAT_COUNT-1
;   out:      A = the plate's top edge as a PICTURE ROW
;   clobbers: A, X, Y, N, Z, C
;   assumes:  main thread, after this frame's phase has been advanced
;   tail:     rts
;
; THE COLLISION READS THE TABLE THE PICTURE IS DRAWN FROM, which is the only
; way a moving platform is honest: the plate's screen y is
; SMT_PLAT_TOP_PX - (word & $3FF) because the offset REPLACES BG1's scroll for
; that column, so reading the same word the PPU read is not an approximation of
; where the plate is, it is where the plate is.
;
; TICK: ok -- indexed by the accumulated phase, as smt_nmi_row is.
smt_plate_top:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "smt_plate_top"
    lda z:ES_SMT_FLATSEL
    bne @flat
    lda z:ES_SMT_PHASE
    bra @pick
@flat:
    .a16
    .i16
    lda #SMT_FLAT_INDEX
@pick:
    .a16
    .i16
    .repeat ::SMT_PHASE_SHIFT       ; `::` — see smt_nmi_row's note
    asl a
    .endrepeat
    sta z:ES_SMT_SCRATCH
    txa                             ; the plate index...
    asl a
    tax
    lda f:smt_plate_col, x          ; ...to its first column, as a byte offset
    clc                             ;    into a 32-word row
    adc z:ES_SMT_SCRATCH
    tax                             ; X, not Y: the 65816 has absolute-long
    lda f:smt_col_bin, x            ;   indexed by X and no Y form of it
    and #ES_OPT_WORKS_MASK          ; the value field, from the allocator
    sta z:ES_SMT_SCRATCH
    ; SMT_ROW_BIAS IS IN HERE, and that is what makes this a PICTURE ROW rather
    ; than a map coordinate. The vertical latch reads "scanline N shows tilemap
    ; line VOFS + N" and the first ACTIVE scanline is 1, so map pixel row P
    ; lands on picture row P - VOFS - 1 (smelter.inc). Leaving the bias out put
    ; the knight's feet one row INTO the metal — measured on the binary, which
    ; is the only place a one-pixel claim can be settled.
    lda #(SMT_PLAT_TOP_PX - SMT_ROW_BIAS)
    sec
    sbc z:ES_SMT_SCRATCH
    rts

.segment "RODATA"
; Each plate's first column, as a BYTE offset into a 32-word row. Generated
; geometry restated once, here, because the ASM needs it as data rather than
; as an equate — smt_art.inc carries the equates the assertion below checks it
; against.
; SIXTEEN SLOTS NOW, in WORLD columns: BG1's map repeats every 32, so the four
; drawn groups are plate art in every screen and the world's level design is
; which word each of these columns carries.
smt_plate_col:
    .word SMT_PLAT_0_COL * 2, SMT_PLAT_1_COL * 2
    .word SMT_PLAT_2_COL * 2, SMT_PLAT_3_COL * 2
    .word SMT_PLAT_4_COL * 2, SMT_PLAT_5_COL * 2
    .word SMT_PLAT_6_COL * 2, SMT_PLAT_7_COL * 2
    .word SMT_PLAT_8_COL * 2, SMT_PLAT_9_COL * 2
    .word SMT_PLAT_10_COL * 2, SMT_PLAT_11_COL * 2
    .word SMT_PLAT_12_COL * 2, SMT_PLAT_13_COL * 2
    .word SMT_PLAT_14_COL * 2, SMT_PLAT_15_COL * 2
.segment "CODE"
