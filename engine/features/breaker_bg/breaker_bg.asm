; =============================================================================
; breaker_bg.asm — the arena: BG1 walls + brick wall, BG2 night bed
; =============================================================================
; The BG keystone: the first per-rail BG feature, and the shape the other BG
; rails follow. CHR and palettes come from the breaker_rom
; blobs; every register base comes from the allocator's emitted encoding, never
; from mask arithmetic here.
;
; TWO THINGS MAKE THIS DIFFERENT FROM room_bg, and they are the reason the
; keystone is worth having:
;
;  1. THE TILEMAP IS BUILT, NOT UPLOADED. breaker's BG1 map is the level, not
;  art: 32x32 cells written cell-by-cell under the enter-time forced blank
;  by brk_build_level, which writes the VRAM word and the collision mirror
;  byte in the SAME iteration so the two cannot be built out of step.
;  2. IT MUTATES WHILE THE DISPLAY IS ACTIVE. A broken brick has to become
;  tile 0 on a running frame, which no forced-blank writer can do. The
;  break queue (brk_break stages, brk_vblank_commit writes) is bg_text's
;  live-HUD-cell pattern applied to BG1 — CPU stores in VBlank, no channel,
;  no VBlank byte budget.
;
; LAYER OWNERSHIP is asserted in breaker_bg/feature.toml, in prose, because
; layer identity is not a resource the allocator models. This scene's enter is
; the only writer of BGMODE/BG1SC/BG2SC/BG12NBA/TM.

; The enter-time GP-DMA register file, addressed through the channel the brk_up
; dma_init claim names — a declared resource, not a hard-coded 0.
BRK_REGS = $4300 + ES_D_BRK_UP_CH * 16

; Tilemap attr words. The palette NUMBER is derived from the emitted CGRAM word
; index (4bpp sub-palette p occupies words 16p..16p+15), so a re-packed palette
; claim moves the attr with it instead of silently rendering in someone else's
; colours.
BRK_BG1_ATTR = (ES_C_BRK_PAL / 16) << 10
BRK_BG2_ATTR = (ES_C_SKY_PAL / 16) << 10

; --- the arena's geometry, in BG1 cells -------------------------------------
; Row 2 is the ceiling; rows 3..27 have side walls at cols 0 and 31; rows 5..10
; cols 1..30 are the 180 bricks. The bottom is deliberately OPEN — that gap is
; the pit the ball is lost through, and it is why floor_check exists.
BRK_ROW_CEIL     = 2
BRK_ROW_WALL_LO  = 3
BRK_ROW_WALL_HI  = 28            ; exclusive
BRK_ROW_BRICK_LO = 5
BRK_ROW_BRICK_HI = 11            ; exclusive
BRK_COL_HI       = 31            ; the right wall's column
BRK_BRICK_TOTAL  = 180           ; 6 rows x 30 cols — asserted by the build

; --- collision mirror cell values (breaker_bg/feature.toml) ------------------
BRK_CELL_EMPTY = 0
BRK_CELL_WALL  = 1               ; reflects, never breaks
BRK_CELL_BRICK = 2               ; reflects AND breaks

; --- break queue layout (ES_BRK_Q) ------------------------------------------
; +0 u8 count · +1 u8 pad · then BRK_Q_MAX x { u16 VMADD, u16 tilemap word }.
; The depth is DERIVED from the emitted claim size rather than restated, so the
; toml is the single place the number lives.
BRK_Q_HEAD = 2
BRK_Q_MAX  = (ES_BRK_Q_SIZE - BRK_Q_HEAD) / 4
; One tick probes at most four points (brk_move_x and brk_move_y, two each), so
; four is exactly the worst case and the queue cannot overflow. If a future
; tick probes more, this stops the build rather than silently dropping a brick
; that has already left the collision mirror.
.assert BRK_Q_MAX >= 4, error, "break queue is shallower than one tick's worst case"

; --- brk_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — it is consumed by the transfer, so it is re-armed HERE,
; inside the routine, per call. One arming site, and it cannot be forgotten.
brk_up:
    .a16
    .i16
    stx a:BRK_REGS + 2              ; A1T
    sty a:BRK_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:BRK_REGS + 4              ; A1B
    lda #ES_D_BRK_UP_DMAP
    sta a:BRK_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_BRK_UP_BBAD
    sta a:BRK_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_BRK_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; --- brk_fill_map: fill a whole tilemap with one word ------------------------
; In: A16/I16, DB=0, forced blank. A = tilemap word, X = VRAM word base,
;  Y = word count. Clobbers A, X, Y.
brk_fill_map:
    .a16
    .i16
    pha
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    stx a:$2116                     ; VMADD
    pla
:   sta a:$2118                     ; VMDATA, word mode
    dey
    bne :-
    rts

; --- brk_arm: uploads + BG1/BG2 registers (scene enter) ---------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
brk_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the six arena tiles ------------------------------------
    sep #$20
    .a8
    lda #^brk_bg_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BRK_CHR
    sta a:$2116
    ldx #.loword(brk_bg_chr_bin)
    ldy #ES_R_BRK_BG_CHR_ROM_SIZE
    jsr brk_up
    ; ---- BG2 CHR: the one solid tile the whole layer is made of -----------
    sep #$20
    .a8
    lda #^brk_sky_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_SKY_CHR
    sta a:$2116
    ldx #.loword(brk_sky_chr_bin)
    ldy #ES_R_BRK_SKY_CHR_ROM_SIZE
    jsr brk_up
    ; ---- palettes: BG1 sub-palette then BG2's, CPU stores under the enter's
    ; forced blank. 32 bytes each is not worth arming a channel, and the blob
    ; labels are link-time constants, so `lda f:blob, x` reaches them without a
    ; pointer (the shape room_bg established).
    sep #$20
    .a8
    lda #ES_C_BRK_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:brk_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BRK_BG_PAL_ROM_SIZE
    bcc :-
    sep #$20
    .a8
    lda #ES_C_SKY_PAL
    sta a:$2121
    rep #$20
    .a16
    ldx #0
:   lda f:brk_sky_pal_bin, x
    sep #$20
    .a8
    sta a:$2122
    xba
    sta a:$2122
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BRK_SKY_PAL_ROM_SIZE
    bcc :-
    ; ---- BG2: one solid tile everywhere — the bed the wash lands on -------
    lda #BRK_BG2_ATTR               ; tile 0 of sky_chr | palette 3
    ldx #ES_V_SKY_MAP
    ldy #ES_V_SKY_MAP_WORDS
    jsr brk_fill_map
    ; ---- BG1: the level itself -------------------------------------------
    jsr brk_build_level
    ; ---- BG registers -----------------------------------------------------
    sep #$20
    .a8
    lda #ES_V_BRK_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_SKY_MAP_SC_BASE
    sta a:$2108                     ; BG2SC
    lda #(ES_V_BRK_CHR_NBA | (ES_V_SKY_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: BG1 low nibble, BG2 high
    ; scroll pinned at 0 — the arena is one screen and does not scroll, and a
    ; scene must not inherit whatever the previous one left in these latches
    stz a:$210D                     ; BG1HOFS (write-twice)
    stz a:$210D
    stz a:$210E                     ; BG1VOFS
    stz a:$210E
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    rep #$20
    .a16
    rts

; --- brk_build_level: write the whole BG1 map AND its collision mirror ------
; In/out: A16/I16, DB=0, forced blank (scene enter). Clobbers A, X.
;
; ONE LOOP, TWO WRITES. Each iteration derives one cell's tile from its row and
; column, writes the tilemap word to the VRAM port and the collision byte to
; the mirror. There is deliberately no second pass and no shared table: the two
; representations are produced by the same expression, in the same iteration,
; so "the map says brick, the mirror says empty" is not a state this can reach.
;
; The 32x32 sweep is ~1,024 iterations of straight-line 16-bit work under the
; enter-time forced blank, where nothing else is running and there is no frame
; deadline (scene_mgr's phase-2 switch holds the display blanked and NMI masked
; for as long as enter takes).
brk_build_level:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ldx #ES_V_BRK_MAP
    stx a:$2116                     ; VMADD = the tilemap claim's base
    ldx #0                          ; X = cell index, 0..1023, row-major
@cell:
    .a16
    .i16
    txa
    .repeat 5
        lsr
    .endrepeat
    sta z:US_TMP                    ; row = index >> 5
    lda #BRK_CELL_EMPTY             ; default: nothing here
    sta z:US_NEWX                   ; (tile id doubles as the cell class below)
    lda z:US_TMP
    cmp #BRK_ROW_CEIL
    bne @not_ceil
    lda #1                          ; the ceiling: a wall right across
    sta z:US_NEWX
    bra @have
@not_ceil:
    .a16
    cmp #BRK_ROW_WALL_LO
    bcc @have                       ; above the ceiling: open
    cmp #BRK_ROW_WALL_HI
    bcs @have                       ; below the walls: the pit, open
    txa
    and #BRK_COL_HI
    beq @wall                       ; col 0  — left wall
    cmp #BRK_COL_HI
    beq @wall                       ; col 31 — right wall
    lda z:US_TMP
    cmp #BRK_ROW_BRICK_LO
    bcc @have
    cmp #BRK_ROW_BRICK_HI
    bcs @have
    sec
    sbc #BRK_ROW_BRICK_LO
    and #3
    clc
    adc #2                          ; brick tile: 2 + ((row - first) & 3)
    sta z:US_NEWX
    bra @have
@wall:
    .a16
    .i16
    lda #1
    sta z:US_NEWX
@have:
    .a16
    .i16
    ; ---- the VRAM word -----------------------------------------------------
    lda z:US_NEWX
    ora #BRK_BG1_ATTR
    sta a:$2118                     ; VMDATA, word mode; VMADD auto-advances
    ; ---- the collision mirror byte ----------------------------------------
    lda z:US_NEWX
    beq @class                      ; tile 0 -> BRK_CELL_EMPTY (A is 0)
    cmp #2
    bcc @class                      ; tile 1 -> BRK_CELL_WALL  (A is 1)
    lda #BRK_CELL_BRICK             ; tiles 2..5 -> a breakable brick
@class:
    .a16
    .i16
    sep #$20
    .a8
    sta f:ES_BRK_CELLS_LONG, x
    rep #$20
    .a16
    inx
    cpx #ES_BRK_CELLS_SIZE
    bcc @cell
    jmp brk_q_init                  ; the round starts with nothing staged

; --- brk_q_init: the break queue holds nothing ------------------------------
; In/out: A16/I16, DB=0. Three callers, one contract: BOOT (before the first
; NMI ever runs), every scene ENTER, and every scene EXIT.
;
; This is the one byte of this feature that IS zeroed up front, and the reason
; is the difference between it and brk_cells: the NMI hook calls
; brk_vblank_commit on EVERY frame of EVERY scene, so power-on garbage in the
; count byte would make the title screen's first VBlank write random words to
; random VRAM addresses. Brk_cells has no such reader — build_level writes all
; 1024 bytes before anything reads one — so zeroing it would only hide a
; "build_level stopped running" defect behind a plausible answer.
brk_q_init:
    .a16
    .i16
    sep #$20
    .a8
    lda #0                          ; (stz has no long addressing mode)
    sta f:ES_BRK_Q_LONG             ; count = 0
    rep #$20
    .a16
    rts

; --- brk_probe: is (US_PROBE_X, US_PROBE_Y) blocked? break a brick if so ----
; In: A16/I16, DB=0. US_PROBE_X / US_PROBE_Y are screen pixel coordinates. Out:
; A16 = the cell class — 0 clear, BRK_CELL_WALL, BRK_CELL_BRICK.
;  US_TMP holds the cell index. Clobbers A, X.
;
; TOTAL over the u16 input space, the same discipline col_map states at length:
; `and #31` after `lsr x3` on each axis means every input names a real cell, so
; there is no bounds check, no sentinel and no branch to get wrong. The masks
; are needed to build the index anyway, so totality is free. It differs from
; col_map only in what it reads — a 32x32 WRAM mirror of a map this game
; REWRITES, where col_map reads an immutable ROM world.
;
; A brick hit is CONSUMED here: the cell is cleared, the VRAM cell is staged
; for VBlank, and the caller gets BRK_CELL_BRICK so it can tell a break from a
; wall bounce. The scoring is the caller's, because scoring is the game's.
brk_probe:
    .a16
    .i16
    lda z:US_PROBE_Y
    lsr
    lsr
    lsr
    and #31                         ; row, wrapped onto the map
    .repeat 5
        asl
    .endrepeat
    sta z:US_TMP                    ; row * 32
    lda z:US_PROBE_X
    lsr
    lsr
    lsr
    and #31                         ; col, wrapped onto the map
    ora z:US_TMP                    ; col < 32, so OR is the sum
    sta z:US_TMP                    ; the cell index, for brk_break
    tax
    sep #$20
    .a8
    lda f:ES_BRK_CELLS_LONG, x
    rep #$20
    .a16
    and #$00FF                      ; the byte alone: B still holds old high
    cmp #BRK_CELL_BRICK
    beq @brick
    rts
@brick:
    .a16
    .i16
    jsr brk_break
    lda #BRK_CELL_BRICK
    rts

; --- brk_break: clear the cell in US_TMP and stage its VRAM word ------------
; In/out: A16/I16, DB=0. Clobbers A, X.
brk_break:
    .a16
    .i16
    ldx z:US_TMP
    sep #$20
    .a8
    lda #BRK_CELL_EMPTY             ; (stz has no long addressing mode)
    sta f:ES_BRK_CELLS_LONG, x      ; the mirror agrees immediately...
    lda f:ES_BRK_Q_LONG             ; ...the VRAM cell waits for VBlank
    cmp #BRK_Q_MAX
    bcc @stage
    rep #$20
    .a16
    rts                             ; unreachable (the .assert above), and a
                                    ; refusal rather than a wild store if the
                                    ; probe count ever grows
@stage:
    .a8
    .i16
    rep #$20
    .a16
    and #$00FF
    asl
    asl                             ; count * 4 bytes per entry
    clc
    adc #BRK_Q_HEAD
    tax                             ; X = this entry's byte offset
    lda z:US_TMP
    clc
    adc #ES_V_BRK_MAP               ; the cell's VRAM word address
    sta f:ES_BRK_Q_LONG, x
    lda #BRK_BG1_ATTR               ; tile 0 (empty) in this layer's palette
    sta f:ES_BRK_Q_LONG + 2, x
    sep #$20
    .a8
    lda f:ES_BRK_Q_LONG
    inc a
    sta f:ES_BRK_Q_LONG
    rep #$20
    .a16
    rts

; --- brk_vblank_commit: write the staged cells to VRAM (NMI hook) -----------
; In/out: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A, X, Y.
;
; Programs its own VMAIN and VMADD, so its position in sm_nmi_hook is free —
; the rule AGENTS.md states for every VBlank VRAM writer in the tree, and the
; reason the OAM DMA and the text queue ahead of it cannot reach it.
brk_vblank_commit:
    .a8
    .i16
    lda f:ES_BRK_Q_LONG             ; count
    bne @go
    rts
@go:
    .a8
    .i16
    pha
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    pla
    rep #$20
    .a16
    and #$00FF
    tay                             ; Y = cells to commit, 1..BRK_Q_MAX
    ldx #BRK_Q_HEAD
@one:
    .a16
    .i16
    lda f:ES_BRK_Q_LONG, x
    sta a:$2116                     ; VMADD = this cell
    lda f:ES_BRK_Q_LONG + 2, x
    sta a:$2118                     ; VMDATA, word mode
    inx
    inx
    inx
    inx
    dey
    bne @one
    sep #$20
    .a8
    lda #0                          ; (stz has no long addressing mode)
    sta f:ES_BRK_Q_LONG             ; drained
    rts
