; =============================================================================
; mil_melt — the melt's bands: three table rows, and the channel that picks one
; =============================================================================
; SCENE-SCOPED, like mil_opt.asm: it reads ES_OPT_MELT_* and the channel the
; composition synthesized for THIS scene (ES_H_MIL_BANDS_ROWSEL_*), so it is
; included inside the melt's .scope, after mil_opt.asm, whose walker it reuses.
;
; The rows live in BG3's map at a stride of SMIL_COLS words:
;   row 0  the hall's running (or flat) row, restaged every VBlank
;   row 1  the ripple row for this phase (or its flat control), restaged too
;   row 2  a row of zeros, written once at enter — no enable bit, so every
;          column in band B shows both layers at their fallback scroll
; ...and the HDMA table names them per band: BG3VOFS = row * ROW_VOFS.

; --- mil_melt_arm_bands: the table, the channel slot, and the enable bit ----
; CONTRACT mil_melt_arm_bands
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the HDMA table at ES_MIL_BANDTAB_LONG built; the row-selecting
;             channel's shadow slot filled; its bit ORed into the scene_mgr
;             HDMAEN shadow, which the NMI commits to $420C
;   clobbers: A, X, N, Z
;   assumes:  forced blank, at scene enter, AFTER scene_mgr's transition
;             shadow clear (the switch runs it before enter)
;   tail:     rts
;
; A NON-REPEAT ENTRY WRITES ONCE AND HOLDS. A count byte in $01..$7F means
; "one transfer at the entry's first line, then that many lines before the
; next entry" — the BGnVOFS write-twice latch keeps the value through the
; hold. Three entries for three bands, and the bands' line counts sum to the
; frame, which the generator asserts by construction (they are the map rows
; between the camera and the picture's edges). Every count is under 128, so
; no band needs splitting.
mil_melt_arm_bands:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_melt_arm_bands"
    sep #$20
    .a8
    lda #SMIL_BAND_A_LINES
    sta f:ES_MIL_BANDTAB_LONG + 0   ; band A: the machines...
    lda #0
    sta f:ES_MIL_BANDTAB_LONG + 1   ;   ...read row 0 (BG3VOFS 0, low)
    sta f:ES_MIL_BANDTAB_LONG + 2   ;   ...high
    lda #SMIL_BAND_B_LINES
    sta f:ES_MIL_BANDTAB_LONG + 3   ; band B: the deck...
    lda #<(2 * ES_OPT_MELT_ROW_VOFS)
    sta f:ES_MIL_BANDTAB_LONG + 4   ;   ...read row 2, the zero row
    lda #0
    sta f:ES_MIL_BANDTAB_LONG + 5
    lda #SMIL_BAND_C_LINES
    sta f:ES_MIL_BANDTAB_LONG + 6   ; band C: the channel...
    lda #<(1 * ES_OPT_MELT_ROW_VOFS)
    sta f:ES_MIL_BANDTAB_LONG + 7   ;   ...read row 1, the ripple
    lda #0
    sta f:ES_MIL_BANDTAB_LONG + 8
    sta f:ES_MIL_BANDTAB_LONG + 9   ; the terminator
    ; ---- the channel's shadow slot: DMAP/BBAD from the declaration ------
    ldx #(ES_H_MIL_BANDS_ROWSEL_CH * 16)
    lda #ES_H_MIL_BANDS_ROWSEL_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, mode 2 (write twice)
    lda #ES_H_MIL_BANDS_ROWSEL_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD -> BG3VOFS
    lda #<ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T low
    lda #>ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 3, x    ; A1T high
    lda #ES_MIL_BANDTAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: the WRAM bank the claim landed in
    ; ---- THE LINE COUNTER, SEEDED TO HOLD. The NMI copies this slot to
    ; $43x0-$43xA and sets HDMAEN in the SAME VBlank, and a channel enabled
    ; mid-frame runs on every scanline left of that VBlank from whatever
    ; $43xA (the line counter) and $43x8/9 (the current table address)
    ; already hold -- the init that reloads them from the table comes at the
    ; NEXT frame's line 0. Each line decrements the counter first; from ZERO
    ; that wraps to $FF, which is "repeat, 127 lines": a transfer every line
    ; from an address that steps by the transfer's width. MEASURED: with the
    ; slot's tail zero the channel read 382 never-written bytes up from
    ; $7E:0000 on the melt's first frame, and with the address seeded and
    ; the counter zero it read 291 bytes up from the table's end -- so the
    ; walk is the counter's, not the address's. (SnesDmaController.cpp
    ; ProcessHdmaChannels: decrement, then DoTransfer = bit 7, then a new
    ; entry only when the low seven bits reach 0.) Harmless to the picture,
    ; since BG3VOFS means nothing in VBlank and line 0 re-inits; not
    ; harmless as a read of RAM nobody wrote (rule 5). Seeded to the
    ; longest plain hold, the counter cannot reach zero before the frame's
    ; own init, so the VBlank tail transfers nothing and reads nothing.
    lda #<ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 8, x    ; A2A = A1T, for the same reason
    lda #>ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 9, x
    lda #$7F
    sta f:ES_SM_HDMA_LONG + 10, x   ; NLTR: hold 127 lines, no repeat
    ; ---- ...and the enable bit, in the shadow the NMI writes to $420C ----
    lda z:ES_SM_NMI + 2
    ora #(1 << ES_H_MIL_BANDS_ROWSEL_CH)
    sta z:ES_SM_NMI + 2
    rep #$20
    .a16
    rts

; --- mil_ripple_source: this phase's ripple row (or the flat control) -------
; CONTRACT mil_ripple_source
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MIL_PHASE, ES_MIL_FLATSEL
;   out:      ES_MIL_NMI_SCRATCH+0..2 — the ripple row's 24-bit ROM address
;   clobbers: A, N, Z, C
;   assumes:  VBlank, from mil_nmi_rows
;   tail:     rts
;
; ONE RIPPLE ROW PER 2^SMIL_RIPPLE_SHIFT PHASES: the surface moves slower
; than the machines, and the blob is a quarter the size it would be at the
; hall's rate. The same flat select that flattens the hall's row flattens
; the surface, so Y is one control over both bands that move.
mil_ripple_source:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_ripple_source"
    lda z:ES_MIL_FLATSEL
    bne @flat
    lda z:ES_MIL_PHASE
    .repeat ::SMIL_RIPPLE_SHIFT
    lsr a
    .endrepeat
    bra @pick
@flat:
    .a16
    .i16
    lda #SMIL_RIPPLE_FLAT
@pick:
    .a16
    .i16
    .repeat ::SMIL_PHASE_SHIFT      ; `::` — this file is included inside the
    asl a                           ;   scene's .scope and .repeat needs its
    .endrepeat                      ;   count as a constant at parse time
    clc
    adc #.loword(mil_ripple_bin)    ; the blob fits one 32 KB window, so this
    sta z:ES_MIL_NMI_SCRATCH        ;   16-bit add cannot leave the bank
    sep #$20
    .a8
    lda #^mil_ripple_bin
    sta z:ES_MIL_NMI_SCRATCH + 2
    rep #$20
    .a16
    rts

; --- mil_nmi_rows: BOTH restaged rows, every armed VBlank -------------------
; CONTRACT mil_nmi_rows
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_MIL_PHASE, ES_MIL_FLATSEL, ES_MIL_CAM
;   out:      BG3's rows 0 and 1 rewritten — the hall's row and the ripple —
;             ES_MIL_SHOWN and ES_MIL_CAM_SHOWN published
;   clobbers: A, X, Y, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. Programs its own VMAIN/VMADD/DAS
;   tail:     rts
;
; ONE TRANSFER, TWO ROWS: they are consecutive in the map and consecutive in
; the staging buffer, so 128 B through the word port lands both. The DAS is
; armed here for this transfer and nowhere else — it is consumed by it.
mil_nmi_rows:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_nmi_rows"
    jsr mil_row_regs
    rep #$20
    .a16
    lda #(2 * SMIL_ROW_BYTES)
    sta a:MIL_ROW_REGS + 5          ; DAS: both rows
    jsr mil_row_source              ; the hall's row for this phase...
    ldx #0
    jsr mil_stage_row_into          ;   ...folded with the camera, into +0
    jsr mil_ripple_source           ; the ripple row for this phase...
    ldx #SMIL_ROW_BYTES
    jsr mil_stage_row_into          ;   ...into +64
    jsr mil_commit_vofs             ; ...and the fallback both layers use
    sep #$20
    .a8
    lda #(1 << ES_H_MIL_VROW_CH)
    sta a:$420B                     ; MDMAEN: fire
    rts
