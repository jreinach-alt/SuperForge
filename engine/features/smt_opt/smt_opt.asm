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
    clc
    adc #.loword(smt_col_bin)       ; the blob fits one 32 KB window, so this
    sta a:SMT_ROW_REGS + 2          ;   16-bit add cannot leave the bank
    sep #$20
    .a8
    lda #(1 << ES_H_SMT_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
    rts

; --- smt_plate_top: where a plate's surface is, this frame ------------------
; CONTRACT smt_plate_top
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the plate index, 0..SMT_PLAT_COUNT-1
;   out:      A = the plate's top edge in screen pixels
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
    lda #SMT_PLAT_TOP_PX
    sec
    sbc z:ES_SMT_SCRATCH
    rts

.segment "RODATA"
; Each plate's first column, as a BYTE offset into a 32-word row. Generated
; geometry restated once, here, because the ASM needs it as data rather than
; as an equate — smt_art.inc carries the equates the assertion below checks it
; against.
smt_plate_col:
    .word SMT_PLAT_0_COL * 2, SMT_PLAT_1_COL * 2
    .word SMT_PLAT_2_COL * 2, SMT_PLAT_3_COL * 2
.segment "CODE"
