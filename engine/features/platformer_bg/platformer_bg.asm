; =============================================================================
; platformer_bg.asm — the level on BG1, the parallax skyline on BG2
; =============================================================================
; The rail's BG feature. CHR, palettes, the level and the skyline come from
; the platformer_rom blobs; every register base comes from the allocator's
; emitted encoding, never from mask arithmetic here.
;
; WHAT IT TAKES FROM THE TWO PRECEDENTS: the tilemap is BUILT under the
; enter-time forced blank (breaker_bg) and MUTATES on running frames through a
; one-cell VBlank queue (breaker_bg again, for the collected coin), while the
; layer MOVES from a DP shadow the NMI hook commits (shmup_bg).
;
; WHAT IT ADDS: PARALLAX — two scanline bands of BG2HOFS at different fractions
; of the same camera x, from a THREE-ENTRY HDMA table. The design argument for
; the shape lives in feature.toml; what matters at this end is that
; plf_plx_build touches ten bytes, not 224.
;
; LAYER OWNERSHIP is asserted in platformer_bg/feature.toml, in prose, because
; layer identity is not a resource the allocator models.

; The enter-time GP-DMA register file, addressed through the channel the plf_up
; dma_init claim names — a declared resource, not a hard-coded 0.
PLF_REGS = $4300 + ES_D_PLF_UP_CH * 16

; Tilemap attr bits. The palette NUMBER is derived from the emitted CGRAM word
; index (4bpp sub-palette p occupies words 16p..16p+15), so a re-packed palette
; claim moves the attr with it instead of silently rendering in someone else's
; colours.
PLF_ATTR = (ES_C_PLF_PAL / 16) << 10

; BG1SC's size bits: 01 = 64x32, two hardware pages side by side. The emitted
; _SC_BASE carries only the base (bits 2-7), so the size is OR'd in here — a
; VALUE, not an address.
PLF_MAP_SC = ES_V_PLF_MAP_SC_BASE | 1

; plf_build_level's scratch, on enter_scr — the global companion whose whole
; purpose is enter-time scratch for routines that run under forced blank,
; write-before-read per call (enter_scr/feature.toml). Both builders are
; exactly that: they run once per scene enter, before anything can look.
; +0 is shared with plf_up's source-bank byte, which never overlaps in time
; because every upload has completed before a map is built.
PLF_S_ROW  = ES_ESCR + 2
PLF_S_COL  = ES_ESCR + 4
PLF_S_DEST = ES_ESCR + 6

; The queue's three fields (see feature.toml — NOT bg_text's queue, because a
; coin pickup dirties the COINS counter on the same frame and both would want
; the single cell bg_text holds).
PLF_Q_COUNT = ES_PLF_Q + 0
PLF_Q_VMADD = ES_PLF_Q + 2
PLF_Q_WORD  = ES_PLF_Q + 4

; --- plf_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — it is consumed by the transfer, so it is re-armed HERE,
; inside the routine, per call. One arming site, and it cannot be forgotten.
plf_up:
    .a16
    .i16
    stx a:PLF_REGS + 2              ; A1T
    sty a:PLF_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:PLF_REGS + 4              ; A1B
    lda #ES_D_PLF_UP_DMAP
    sta a:PLF_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_PLF_UP_BBAD
    sta a:PLF_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_PLF_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; --- plf_vmain: VMAIN = word access, +1 word after the high byte ------------
; In/out: A16/I16. Clobbers A.
plf_vmain:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
    rts

; --- plf_build_level: the ROM world -> the 64x32 BG1 tilemap ----------------
; In/out: A16/I16, DB=0, forced blank (scene enter). Clobbers A, X, Y.
;
; The blob is a 1:1 IMAGE of the tilemap, so this is a copy with the palette
; attribute OR'd in — except for the page split. A 64x32 BG1 map is two 32x32
; hardware pages: cols 0..31 at the base, cols 32..63 at base + 0x400. So the
; loop walks the blob in its own order and derives the destination, rather than
; streaming into a rising VMADD.
;
; It ALSO clears plf_taken here, in the same pass that establishes the coins,
; so "the map has a coin the bitmap says was already collected" is not a
; reachable state at the start of a round.
plf_build_level:
    .a16
    .i16
    jsr plf_vmain
    ; ---- every coin is uncollected: 256 bytes of bitmap ------------------
    ldx #0
    sep #$20
    .a8
    lda #0                          ; (stz has no long-indexed addressing mode)
:   sta f:ES_PLF_TAKEN_LONG, x
    inx
    cpx #ES_PLF_TAKEN_SIZE
    bcc :-
    rep #$20
    .a16
    ; ---- the map ----------------------------------------------------------
    stz z:PLF_S_ROW
@row:
    .a16
    .i16
    stz z:PLF_S_COL
@col:
    .a16
    .i16
    ; dest = base + (col >= 32 ? 0x400: 0) + row * 32 + (col & 31)
    lda z:PLF_S_ROW
    .repeat 5
        asl                         ; row * 32
    .endrepeat
    clc
    adc #ES_V_PLF_MAP
    sta z:PLF_S_DEST
    lda z:PLF_S_COL
    and #(PLF_MAP_W / 2)            ; bit 5: the page selector
    .repeat 5
        asl                         ; 32 -> 0x400
    .endrepeat
    clc
    adc z:PLF_S_DEST
    sta z:PLF_S_DEST
    lda z:PLF_S_COL
    and #((PLF_MAP_W / 2) - 1)      ; the column within its page
    clc
    adc z:PLF_S_DEST
    sta a:$2116                     ; VMADD = this cell
    ; the tile: the blob byte, plus this feature's palette attribute
    lda z:PLF_S_ROW
    .repeat 6
        asl                         ; row * 64
    .endrepeat
    clc
    adc z:PLF_S_COL
    tax
    sep #$20
    .a8
    lda f:plf_level_bin, x
    rep #$20
    .a16
    and #$00FF                      ; the byte alone: B still holds the old high
    ora #PLF_ATTR
    sta a:$2118                     ; VMDATA, word mode
    ; ---- next cell --------------------------------------------------------
    inc z:PLF_S_COL
    lda z:PLF_S_COL
    cmp #PLF_MAP_W
    bcs :+
    jmp @col
:   inc z:PLF_S_ROW
    lda z:PLF_S_ROW
    cmp #PLF_MAP_H
    bcs :+
    jmp @row
:   rts

; --- plf_build_sky: the column-periodic skyline -> the 32x32 BG2 tilemap ----
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; The blob is 32 rows x 8 columns and the map is 32x32, so each row's eight
; tiles repeat four times across it. Written as ONE rising VMADD walk over the
; 1024 cells in tilemap order — unlike BG1 this map is a single page, so the
; destination needs no page split and the loop derives only the SOURCE:
;
;  cell i -> row = i >> 5, col = i & 31, blob byte = row * 8 + (col & 7)
plf_build_sky:
    .a16
    .i16
    jsr plf_vmain
    ldx #ES_V_PLF_SKY
    stx a:$2116                     ; VMADD = row 0, col 0
    stz z:PLF_S_ROW                 ; the linear cell index, 0..1023
@cell:
    .a16
    .i16
    lda z:PLF_S_ROW
    .repeat 5
        lsr                         ; the map row
    .endrepeat
    .repeat 3
        asl                         ; ...times the blob's 8-byte stride
    .endrepeat
    sta z:PLF_S_COL
    lda z:PLF_S_ROW
    and #(PLF_SKY_PERIOD - 1)       ; the column's residue -- the period
    ora z:PLF_S_COL                 ;   repeats four times across the 32 cells
    tax
    sep #$20
    .a8
    lda f:plf_sky_bin, x
    rep #$20
    .a16
    and #$00FF
    ora #PLF_ATTR
    sta a:$2118                     ; VMDATA, in tilemap order
    inc z:PLF_S_ROW
    lda z:PLF_S_ROW
    cmp #(PLF_MAP_H * 32)
    bcc @cell
    rts

; --- plf_palette: the shared BG sub-palette + the dusk backdrop -------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X. 32 bytes of CPU stores is
; not worth arming a channel, and the blob labels are link-time constants, so
; `lda f:blob, x` reaches them without a pointer.
plf_palette:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_C_PLF_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:plf_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_PLF_BG_PAL_ROM_SIZE
    bcc :-
    ; ---- CGRAM word 0: the surface the dusk ramp is painted on ------------
    ; rgb_gradient's colour math ADDs its per-scanline COLDATA to the BACKDROP,
    ; so this is most of the sky — every empty level cell and every gap between
    ; the hills shows it. BLACK, so the ramp renders at its declared
    ; intensities instead of on top of a colour that lifts them.
    sep #$20
    .a8
    lda #ES_C_DUSK
    sta a:$2121
    lda #<PLF_PLAY_SKY
    sta a:$2122
    lda #>PLF_PLAY_SKY
    sta a:$2122
    rep #$20
    .a16
    rts

; --- plf_arm: uploads + both maps + BG1/BG2 registers (scene enter) ---------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
plf_arm:
    .a16
    .i16
    jsr plf_vmain
    ; ---- the shared BG page: level tiles AND sky tiles ---------------------
    sep #$20
    .a8
    lda #^plf_bg_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_PLF_CHR
    sta a:$2116
    ldx #.loword(plf_bg_chr_bin)
    ldy #ES_R_PLF_BG_CHR_ROM_SIZE
    jsr plf_up
    jsr plf_palette
    jsr plf_build_level
    jsr plf_build_sky
    ; ---- BG registers -----------------------------------------------------
    sep #$20
    .a8
    lda #PLF_MAP_SC
    sta a:$2107                     ; BG1SC: 64x32 map at the claimed base
    lda #ES_V_PLF_SKY_SC_BASE
    sta a:$2108                     ; BG2SC: 32x32
    lda #(ES_V_PLF_CHR_NBA | (ES_V_PLF_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: ONE page, both nibbles (the two
                                    ;  layers share it — see feature.toml)
    ; Neither layer scrolls vertically: the world is 28 rows and the screen is
    ; 28 rows, and BG2's skyline is authored where it sits. A scene must not
    ; inherit whatever the previous one left in these.
    stz a:$210E                     ; BG1VOFS (write-twice)
    stz a:$210E
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    ; The parallax channel drives BG2HOFS from line 0 onward; this is the SEED
    ; (declared as one in feature.toml) so the layer's first frame is not
    ; whatever the previous scene left in the latch.
    stz a:$210F                     ; BG2HOFS (write-twice)
    stz a:$210F
    rep #$20
    .a16
    stz z:ES_PLF_CAM                ; the camera starts at the world's left...
    jsr plf_commit_cam              ; ...and frame 0 shows it there
    jsr plf_plx_build               ; ...with a table that agrees
    rts

; --- plf_park: leave BG1/BG2 as the next scene expects to find them ---------
; In/out: A16/I16, DB=0, forced blank (scene_mgr exit contract). Clobbers A.
; The menus run BG3 alone and never write a BG1/BG2 register, so the scroll
; latches are returned to zero here rather than left holding a camera position
; the next scene has no idea about.
plf_park:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS (write-twice)
    stz a:$210D
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    rep #$20
    .a16
    rts

; --- plf_commit_cam: the camera shadow -> BG1HOFS ---------------------------
; In/out: A16/I16, DB=0. Clobbers A. Called from plf_arm (forced blank) and
; from plf_vblank (VBlank). BG1HOFS is WRITE-TWICE: low byte then high byte,
; into one 8-bit port.
plf_commit_cam:
    .a16
    .i16
    lda z:ES_PLF_CAM
    sep #$20
    .a8
    sta a:$210D                     ; BG1HOFS low
    xba
    sta a:$210D                     ; BG1HOFS high
    rep #$20
    .a16
    rts

; =============================================================================
; PARALLAX — three HDMA entries, ten bytes, once per VBlank
; =============================================================================
; The table the `plx` claim's channel reads. A mode-$02 entry is [count,
; hofs_lo, hofs_hi]: at the entry's first scanline the two data bytes are
; written to BG2HOFS (which is a write-twice latch, so mode 2 is exactly
; right), and then the channel IDLES for count-1 lines while the latch holds
; what it was given. So three entries paint the whole frame:
;
;  [96, clouds] scanlines 0..95 HOFS = cam >> 3
;  [128, hills ] scanlines 96..223 HOFS = (cam*3) >> 3
;  [0] terminator
;
; The bottom band is 224 - 96 = 128 = $80, the largest count a non-repeat entry
; can carry, which is why PLF_PLX_SPLIT is 96 and not less: a smaller split
; would need the bottom band cut in two.
;
; TWO ENTRIES, NOT 224. A per-scanline fill of this table would run ~16 cycles
; an entry over 225 entries — ~3,700 CPU cycles a frame for a picture that has
; two distinct values in it. What this costs instead is MEASURED, not
; estimated: 532 master cycles a frame (0.149% of the 357,368 mc NTSC frame,
; ~89 CPU cycles at mc/6), on the shipped binary, with write breakpoints on the
; table's first byte and its terminator (tests/test_platformer.py::
; test_the_parallax_rebuild_costs_what_it_claims). Forty times cheaper.
;
; --- plf_plx_build: rebuild the band table from the camera ------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Called from plf_arm (forced blank)
; and from plf_vblank (VBlank). NOT from the tick: HDMA reads this table during
; active display, so a main-thread rebuild races the read for a drift of one
; pixel a frame — invisible, which is exactly what makes it the wrong kind of
; bug.
;
; THE RATIOS ARE SHIFTS. 1/8 and 3/8 (32/256 and 96/256) need no multiply, so
; this routine takes no interest in the ALU — which a preempting NMI would
; otherwise be able to corrupt mid-operation.
plf_plx_build:
    .a16
    .i16
    ldy #0
    ; ---- entry 1: the far clouds, scanlines 0..PLF_PLX_SPLIT-1 ------------
    ; `::` because ca65 resolves a .repeat COUNT in the enclosing .scope only,
    ; and this file is included inside the play scene's -- a bare PLF_PLX_SHIFT
    ; reads as "Constant expression expected" (measured, not assumed: ca65
    ; accepts the same symbol as an operand two lines later).
    lda z:ES_PLF_CAM
    .repeat ::PLF_PLX_SHIFT
        lsr
    .endrepeat
    tax                             ; X = hofs_top
    sep #$20
    .a8
    lda #PLF_PLX_SPLIT
    sta f:ES_PLX_TAB_LONG + 0
    txa
    sta f:ES_PLX_TAB_LONG + 1       ; hofs low
    xba
    sta f:ES_PLX_TAB_LONG + 2       ; hofs high
    rep #$20
    .a16
    ; ---- entry 2: the near hills, the rest of the frame -------------------
    lda z:ES_PLF_CAM
    asl                             ; cam * 2
    clc
    adc z:ES_PLF_CAM                ; cam * 3
    .repeat ::PLF_PLX_SHIFT
        lsr
    .endrepeat
    tax                             ; X = hofs_bot
    sep #$20
    .a8
    lda #(PLF_PLX_LINES - PLF_PLX_SPLIT)
    sta f:ES_PLX_TAB_LONG + 3
    txa
    sta f:ES_PLX_TAB_LONG + 4
    xba
    sta f:ES_PLX_TAB_LONG + 5
    ; ---- the terminator ---------------------------------------------------
    lda #0
    sta f:ES_PLX_TAB_LONG + 6
    rep #$20
    .a16
    rts

; --- plf_plx_arm: the channel's shadow slots (scene enter) ------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X. The caller ORs
; ES_H_PLX_CH's bit into the HDMAEN shadow.
plf_plx_arm:
    .a16
    .i16
    sep #$20
    .a8
    ldx #(ES_H_PLX_CH * 16)
    lda #ES_H_PLX_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, mode 2 (write twice)
    lda #ES_H_PLX_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD -> BG2HOFS
    lda #<ES_PLX_TAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T low
    lda #>ES_PLX_TAB
    sta f:ES_SM_HDMA_LONG + 3, x    ; A1T high
    lda #ES_PLX_TAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: the WRAM bank the claim landed in
    rep #$20
    .a16
    rts

; =============================================================================
; THE WORLD, AS A QUESTION — probes against immutable ROM
; =============================================================================
; --- plf_flags: the collision flags of the cell containing (probex, probey) --
; In: A16/I16, DB=0. US_PROBEX / US_PROBEY are WORLD pixel coordinates. Out:
; A16 = the flag byte. X = the cell index, for plf_take_coin.
;  Clobbers A, X, Y, US_TMP.
;
; TOTAL over the u16 input space, the discipline col_map states at length and
; breaker_bg follows: `and #63` on the column and `and #31` on the row after
; `lsr x3` means every input names a real cell, so there is no bounds check, no
; sentinel and no branch to get wrong. The masks are needed to build the index
; anyway, so totality is free — and it is why the level blob is 32 rows.
;
; A COLLECTED COIN READS AS SKY. The level is immutable ROM, so the pickup is
; recorded in plf_taken rather than by rewriting the map; this is the one place
; the two are joined, and it is joined in the direction that cannot desync (the
; bitmap can only ever REMOVE a coin).
plf_flags:
    .a16
    .i16
    lda z:US_PROBEY
    .repeat 3
        lsr
    .endrepeat
    and #(PLF_MAP_H - 1)
    .repeat 6
        asl                         ; row * 64
    .endrepeat
    sta z:US_TMP
    lda z:US_PROBEX
    .repeat 3
        lsr
    .endrepeat
    and #(PLF_MAP_W - 1)
    ora z:US_TMP                    ; col < 64, so OR is the sum
    tax                             ; X = the cell index
    sep #$20
    .a8
    lda f:plf_level_bin, x
    rep #$20
    .a16
    and #$00FF                      ; the tile id alone
    cmp #PLF_T_COIN
    beq @coin
@classify:
    .a16
    .i16
    phx
    tax
    sep #$20
    .a8
    lda f:plf_tile_flags, x
    rep #$20
    .a16
    plx                             ; ...before the mask, so the Z the caller
    and #$00FF                      ;   branches on is the FLAGS', not X's
    rts
@coin:
    .a16
    .i16
    jsr plf_coin_taken              ; A = 0 still there / non-zero collected
    bne @gone
    lda #PLF_T_COIN                 ; ...the taken test clobbered A, so the
    bra @classify                   ;   tile id is restated rather than held
@gone:
    .a16
    .i16
    lda #PLF_T_SKY                  ; a collected coin IS sky, and sky has no
    bra @classify                   ;   flags — one exit, one lookup

; --- plf_coin_taken: has cell X already been collected? ---------------------
; In: A16/I16, DB=0. X = the cell index. Out: A16 = 0 no / non-zero yes.
;  X preserved. Clobbers A, Y.
; One bit per cell: byte = index >> 3, bit = index & 7.
plf_coin_taken:
    .a16
    .i16
    phx
    txa
    and #7
    tay                             ; Y = the bit within the byte
    txa
    .repeat 3
        lsr
    .endrepeat
    tax                             ; X = the byte
    sep #$20
    .a8
    lda f:ES_PLF_TAKEN_LONG, x
    rep #$20
    .a16
    and #$00FF
@shift:
    .a16
    .i16
    cpy #0
    beq @done
    lsr
    dey
    bra @shift
@done:
    .a16
    .i16
    ; PLX BEFORE THE TEST, NOT AFTER. `plx` sets N and Z from the value it
    ; pulls, so an `and #1` here followed by `plx` returns the right VALUE in A
    ; and the WRONG Z to the caller's `bne` -- the cell index is never zero, so
    ; every coin read as already-collected and the rail's six coins were
    ; uncollectable. Diagnosed on the emulator by walking the hero over cell
    ; (7,23) and watching US_COINS stay 0 while the tilemap, the ROM blob and
    ; the taken bitmap all read correct.
    plx
    and #1
    rts

; --- plf_take_coin: mark cell X collected AND queue its tilemap cell --------
; In/out: A16/I16, DB=0. X = the cell index. Clobbers A, X, Y.
;
; Two halves, and both are needed: the bitmap makes the probe stop seeing it,
; and the queued cell makes the SCREEN stop showing it. The screen half has to
; happen in VBlank, because the display is active — breaker_bg's problem and
; the same answer.
plf_take_coin:
    .a16
    .i16
    phx
    ; ---- the bitmap -------------------------------------------------------
    txa
    and #7
    tay
    lda #1
@shift:
    .a16
    .i16
    cpy #0
    beq @placed
    asl
    dey
    bra @shift
@placed:
    .a16
    .i16
    pha                             ; the positioned bit, while X is rebuilt
    txa
    .repeat 3
        lsr
    .endrepeat
    tax
    pla
    sep #$20
    .a8
    ora f:ES_PLF_TAKEN_LONG, x
    sta f:ES_PLF_TAKEN_LONG, x
    rep #$20
    .a16
    plx
    ; ---- the tilemap cell, staged for the next VBlank ---------------------
    ; index -> VRAM word: row = index >> 6, col = index & 63, and the page
    ; split is the same one plf_build_level walks.
    phx
    txa
    and #(PLF_MAP_W - 1)            ; the column
    pha
    and #(PLF_MAP_W / 2)            ; bit 5: the page selector
    .repeat 5
        asl                         ; 32 -> 0x400
    .endrepeat
    sta z:PLF_S_DEST
    pla
    and #((PLF_MAP_W / 2) - 1)      ; the column within its page
    clc
    adc z:PLF_S_DEST
    sta z:PLF_S_DEST
    plx
    txa
    .repeat 6
        lsr                         ; the row
    .endrepeat
    .repeat 5
        asl                         ; row * 32
    .endrepeat
    clc
    adc z:PLF_S_DEST
    clc
    adc #ES_V_PLF_MAP
    sta z:PLF_Q_VMADD
    lda #(PLF_T_SKY | PLF_ATTR)
    sta z:PLF_Q_WORD
    sep #$20
    .a8
    lda #1
    sta z:PLF_Q_COUNT
    rep #$20
    .a16
    rts

; --- plf_q_init: the queue's count byte, at boot ----------------------------
; In/out: A16/I16, DB=0. Clobbers A. Plf_vblank_queue runs on EVERY frame of
; EVERY scene and this byte is its only guard, so power-on garbage here would
; make the title's first VBlank write a random word to a random VRAM address.
; Plf_taken has no such reader — it is written whole by plf_build_level before
; anything can look — so it is NOT pre-zeroed, per CLAUDE.md rule 5.
plf_q_init:
    .a16
    .i16
    sep #$20
    .a8
    stz z:PLF_Q_COUNT
    rep #$20
    .a16
    rts

; --- plf_vblank_queue: write the staged cell (NMI hook, every frame) --------
; In/out: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A, X. It programs its
; OWN VMAIN and VMADD, which is what makes the hook's order free (AGENTS.md's
; established rule).
plf_vblank_queue:
    .a8
    .i16
    lda z:PLF_Q_COUNT
    beq @no_cell
    stz z:PLF_Q_COUNT
    lda #$80
    sta a:$2115                     ; VMAIN: word access, +1 after the high byte
    ldx z:PLF_Q_VMADD
    stx a:$2116
    ldx z:PLF_Q_WORD
    stx a:$2118                     ; VMDATA, word mode
@no_cell:
    .a8
    .i16
    rts

; --- plf_vblank: the camera and the sky, committed (NMI hook) ---------------
; In/out: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A, X, Y.
;
; Called ONLY while the play scene is live — main.asm gates on the scene id, so
; a menu (which runs BG3 alone and owns no BG1/BG2 register) never has one
; written under it, and this feature's DP shadow has no reader before its own
; enter wrote it (shmup_bg reaches the same conclusion).
;
; BOTH LAYERS FROM ONE SHADOW, IN ONE PLACE. The foreground's BG1HOFS and the
; two sky bands' BG2HOFS entries are derived from the same ES_PLF_CAM in the
; same VBlank, so they cannot disagree about where the camera is.
plf_vblank:
    .a8
    .i16
    rep #$20
    .a16
    jsr plf_commit_cam
    jsr plf_plx_build
    sep #$20
    .a8
    rts

; =============================================================================
; THE TILE FLAG TABLE — one byte per tile id
; =============================================================================
; Indexed by the level blob's own bytes, so a tile id is a tile NUMBER, a flag
; index and a CHR slot all at once. Five ids carry flags: the ledge is SOLID
; like the ground, the dirt interior collides exactly like the grass above it,
; and the platform is the one-way.
.segment "RODATA"
plf_tile_flags:
    .byte 0                         ; 0 sky
    .byte PLF_F_SOLID               ; 1 ground
    .byte PLF_F_SOLID               ; 2 ledge
    .byte PLF_F_PLAT                ; 3 one-way platform
    .byte PLF_F_COIN                ; 4 coin
    .byte PLF_F_SOLID               ; 5 dirt interior
    .byte 0                         ; 6 cloud   — BG2 only, never probed
    .byte 0                         ; 7 hill body
    .byte 0                         ; 8 hill crest
.assert (* - plf_tile_flags) = PLF_T_COUNT, error, "plf_tile_flags is not PLF_T_COUNT long"
.segment "CODE"
