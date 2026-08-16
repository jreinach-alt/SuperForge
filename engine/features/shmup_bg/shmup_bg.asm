; =============================================================================
; shmup_bg.asm — the drifting planet field on BG1, the HUD band on BG2
; =============================================================================
; The rail's BG feature, following the keystone breaker_bg. CHR and
; palettes come from the shmup_rom blobs; every register base comes from the
; allocator's emitted encoding, never from mask arithmetic here.
;
; WHAT IT TAKES FROM THE KEYSTONE: the tilemap is BUILT, not uploaded. The
; planet field is ten 4x4-tile stamps at declared origins, written cell by cell
; under the enter-time forced blank. There is no tilemap blob, because a 2 KB
; ROM map would be a second source of truth for a 2 KB expression.
;
; WHAT IT ADDS: THE LAYER MOVES. BG1VOFS advances one pixel a frame, and the
; map is 32 rows x 8 px = exactly the 256 px BG1VOFS wraps at, so the field
; loops with no seam and no streaming. The scroll register is a write-twice
; latch the PPU samples per scanline, so it is written in VBLANK from a DP
; shadow — the shape mode7_persp uses for its own origin registers.
;
; LAYER OWNERSHIP is asserted in shmup_bg/feature.toml, in prose, because layer
; identity is not a resource the allocator models.

; The enter-time GP-DMA register file, addressed through the channel the shm_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SHM_REGS = $4300 + ES_D_SHM_UP_CH * 16

; Tilemap attr bits. The palette NUMBER is derived from the emitted CGRAM word
; index (4bpp sub-palette p occupies words 16p..16p+15), so a re-packed palette
; claim moves the attr with it instead of silently rendering in someone else's
; colours. The BG-priority bit lifts the HUD band above BG1's planets.
SHM_ATTR     = (ES_C_SHM_PAL / 16) << 10
SHM_ATTR_PRI = SHM_ATTR | (1 << 13)

; shm_build_field's four scratch words, on enter_scr — the global companion
; whose whole purpose is enter-time scratch for routines that run under forced
; blank, write-before-read per call (enter_scr/feature.toml). The field builder
; is exactly that: it runs once per scene enter, before anything else can look.
; All four words INCLUDING +0, which shm_up used for its source-bank byte a
; moment earlier — the two never overlap in time, because the CHR upload has
; completed before the field is built, and enter_scr's contract is exactly
; "write before you read, per call" rather than "this byte is mine".
SHM_S_TILE   = ES_ESCR + 0
SHM_S_PLANET = ES_ESCR + 2
SHM_S_COL    = ES_ESCR + 4
SHM_S_ROW    = ES_ESCR + 6

; --- shm_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — it is consumed by the transfer, so it is re-armed HERE,
; inside the routine, per call. One arming site, and it cannot be forgotten.
shm_up:
    .a16
    .i16
    stx a:SHM_REGS + 2              ; A1T
    sty a:SHM_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:SHM_REGS + 4              ; A1B
    lda #ES_D_SHM_UP_DMAP
    sta a:SHM_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SHM_UP_BBAD
    sta a:SHM_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_SHM_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; --- shm_vmain: VMAIN = word access, +1 word after the high byte ------------
; In/out: A16/I16. Clobbers A. Four callers wanted this; one site is one place
; for it to be wrong.
shm_vmain:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115
    rep #$20
    .a16
    rts

; --- shm_fill_map: fill a whole tilemap with one word ------------------------
; In: A16/I16, DB=0, forced blank. A = tilemap word, X = VRAM word base,
;  Y = word count. Clobbers A, X, Y.
shm_fill_map:
    .a16
    .i16
    pha
    jsr shm_vmain
    stx a:$2116                     ; VMADD
    pla
:   sta a:$2118                     ; VMDATA, word mode
    dey
    bne :-
    rts

; --- shm_build_field: the BG1 planet field ----------------------------------
; In/out: A16/I16, DB=0, forced blank (scene enter). Clobbers A, X, Y.
;
; Blank the map, then stamp ten 4x4 planet blocks at the declared origins. Each
; stamp's cells are computed, not lifted out of a strip: planet p's cell (r, c)
; is tile SHM_PLANET_BASE + p*16 + r*4 + c, which is how the generator lays the
; page out. So the field's whole definition is the three tables below plus that
; one expression — nothing else can drift from it.
;
; Origins WRAP (`and #31` per axis). A stamp near the bottom of the map runs
; off the edge and reappears at the top, which is correct rather than merely
; tolerated: the map wraps under BG1VOFS anyway, so the two halves of a wrapped
; planet are adjacent on screen.
shm_build_field:
    .a16
    .i16
    lda #(SHM_TILE_BLANK | SHM_ATTR)
    ldx #ES_V_SHM_MAP
    ldy #ES_V_SHM_MAP_WORDS
    jsr shm_fill_map                ; the night sky reads through tile 0
    jsr shm_vmain
    ldy #0                          ; Y = stamp cursor, in BYTES
@stamp:
    .a16
    .i16
    ; ---- this stamp's three numbers, read ONCE ----------------------------
    ; The tables must be reached with X: the 65816 has `lda long,x` but no
    ; `long,y` addressing mode at all, and these tables live in RODATA in a
    ; bank the code cannot assume. So the stamp cursor moves to X for three
    ; loads, and X then goes back to being the cell cursor.
    tyx
    lda f:shm_stamp_pl, x
    sta z:SHM_S_PLANET              ; the planet's tile base, already x16
    lda f:shm_stamp_x, x
    sta z:SHM_S_COL
    lda f:shm_stamp_y, x
    sta z:SHM_S_ROW
    ldx #0                          ; X = cell cursor within the block, 0..15
@cell:
    .a16
    .i16
    ; ---- the tile: base + planet*16 + cell --------------------------------
    txa
    clc
    adc z:SHM_S_PLANET
    clc
    adc #(SHM_PLANET_BASE | SHM_ATTR)
    sta z:SHM_S_TILE                ; ...parked while the address is computed
    ; ---- the destination cell: (origin + offset) wrapped onto the map ------
    txa
    .repeat 2
        lsr                         ; row within the block = cell >> 2
    .endrepeat
    clc
    adc z:SHM_S_ROW
    and #(SHM_MAP_H - 1)
    .repeat 5
        asl                         ; row * 32
    .endrepeat
    sta z:US_TMP
    txa
    and #(SHM_PLANET_SIDE - 1)      ; column within the block
    clc
    adc z:SHM_S_COL
    and #(SHM_MAP_W - 1)
    ora z:US_TMP                    ; col < 32, so OR is the sum
    clc
    adc #ES_V_SHM_MAP
    sta a:$2116                     ; VMADD = this cell
    lda z:SHM_S_TILE
    sta a:$2118                     ; VMDATA, word mode
    inx
    cpx #SHM_PLANET_TILES
    bcc @cell
    iny
    iny
    cpy #(2 * SHM_STAMPS)
    bcc @stamp
    rts

; --- shm_build_band: the BG2 HUD band ---------------------------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y. Three solid rows at
; the top, transparent everywhere else — so the SCORE and LIVES text on BG3
; stays legible when a bright planet drifts under it, and the rest of the sky
; is untouched. BG2 never scrolls, so the band stays put.
shm_build_band:
    .a16
    .i16
    lda #(SHM_TILE_BLANK | SHM_ATTR)
    ldx #ES_V_BAR_MAP
    ldy #ES_V_BAR_MAP_WORDS
    jsr shm_fill_map
    jsr shm_vmain
    ldx #ES_V_BAR_MAP
    stx a:$2116                     ; VMADD = row 0, col 0
    lda #(SHM_BAR_TILE | SHM_ATTR_PRI)
    ldy #(SHM_BAR_ROWS * SHM_MAP_W)
:   sta a:$2118                     ; the band, in tilemap order
    dey
    bne :-
    rts

; --- shm_palette: the BG sub-palette + the night sky -------------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X. 32 bytes of CPU stores is
; not worth arming a channel, and the blob labels are link-time constants, so
; `lda f:blob, x` reaches them without a pointer (the shape room_bg
; established).
shm_palette:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_C_SHM_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:shm_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SHM_BG_PAL_ROM_SIZE
    bcc :-
    ; ---- CGRAM word 0: a night sky, not a black void ----------------------
    ; Most of what the player looks at: the planet blocks are round, tile 0 is
    ; transparent, and BG2 is transparent outside the band.
    sep #$20
    .a8
    lda #ES_C_SKY
    sta a:$2121
    lda #<SHM_SKY
    sta a:$2122
    lda #>SHM_SKY
    sta a:$2122
    rep #$20
    .a16
    rts

; --- shm_arm: uploads + the two maps + BG1/BG2 registers (scene enter) ------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
shm_arm:
    .a16
    .i16
    jsr shm_vmain
    ; ---- the BG page: blank + four planets + the band tile ----------------
    sep #$20
    .a8
    lda #^shm_bg_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_SHM_CHR
    sta a:$2116
    ldx #.loword(shm_bg_chr_bin)
    ldy #ES_R_SHM_BG_CHR_ROM_SIZE
    jsr shm_up
    jsr shm_palette
    jsr shm_build_field
    jsr shm_build_band
    ; ---- BG registers -----------------------------------------------------
    sep #$20
    .a8
    lda #ES_V_SHM_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_BAR_MAP_SC_BASE
    sta a:$2108                     ; BG2SC
    lda #(ES_V_SHM_CHR_NBA | (ES_V_SHM_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: ONE page, both nibbles (the two
                                    ;  layers share it — see feature.toml)
    ; The horizontal latches are pinned at 0 and BG2 does not move at all. A
    ; scene must not inherit whatever the previous one left in these.
    stz a:$210D                     ; BG1HOFS (write-twice)
    stz a:$210D
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    rep #$20
    .a16
    stz z:ES_SHM_SCROLL             ; the field starts at the top of the map
    jsr shm_commit_scroll           ; ...and frame 0 shows it there
    rts

; --- shm_drift: the field falls one pixel (main thread, every frame) --------
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE SIGN IS THE USER-VISIBLE INVARIANT, AND IT IS BACKWARDS FROM THE
; INSTINCT. BG1VOFS names where the VIEWPORT sits on the map, so INCREASING it
; walks the viewport down and the picture appears to rise. A vertical shmup
; needs the opposite — the world comes DOWN at a ship flying up — so the shadow
; DECREASES: a POSITIVE drift rate means the world comes down the screen, and
; the body is therefore an `sbc`. The first pass here was an `inc` and the
; planets flew upward. Tests/test_shmup.py asserts the DIRECTION on
; rendered pixels, not the register, for exactly that reason.
;
; The shadow is masked to the map's own height in pixels, so 0 - 1 wraps to 255
; rather than to $FFFF: the wrap is the game's, not a side effect of what a
; 10-bit register happens to truncate.
shm_drift:
    .a16
    .i16
    lda z:ES_SHM_SCROLL
    dec a
    and #(SHM_MAP_H * 8 - 1)
    sta z:ES_SHM_SCROLL
    rts

; --- shm_commit_scroll: the shadow -> BG1VOFS -------------------------------
; In/out: A16/I16, DB=0. Clobbers A. Called from shm_arm (forced blank) and
; from shm_vblank_scroll (VBlank). BG1VOFS is WRITE-TWICE: low byte then high
; byte, into one 8-bit port.
shm_commit_scroll:
    .a16
    .i16
    lda z:ES_SHM_SCROLL
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS low
    xba
    sta a:$210E                     ; BG1VOFS high
    rep #$20
    .a16
    rts

; --- shm_vblank_scroll: the NMI hook's half ---------------------------------
; In/out: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A.
;
; Called ONLY while the play scene is live — main.asm gates on the scene id, so
; the title (which owns no BG1 register and runs BG3 alone) never has one
; written under it, and this feature's DP shadow has no reader before its own
; enter wrote it.
shm_vblank_scroll:
    .a8
    .i16
    rep #$20
    .a16
    jsr shm_commit_scroll
    sep #$20
    .a8
    rts

; =============================================================================
; THE FIELD'S GEOMETRY — ten stamps, three parallel tables
; =============================================================================
; Origins in tilemap cells, staggered across x AND the wrapping 32-row map so
; the field reads as a scattered belt rather than a grid. Kept non-overlapping
; so no stamp clips another. The planet column is PRE-MULTIPLIED by the block
; size (p * 16), because that is the only form the build loop wants and a
; multiply it does not have to do is a multiply it cannot get wrong.
.segment "RODATA"
shm_stamp_x:
    .word  2, 20, 11, 26,  4, 17, 24,  9, 19,  6
shm_stamp_y:
    .word  1,  3,  6,  9, 12, 15, 19, 22, 26, 29
shm_stamp_pl:
    .word  0, 16, 32, 48, 16,  0, 32, 48, 16, 32
.assert (shm_stamp_y - shm_stamp_x) = SHM_STAMPS * 2, error, "shm_stamp_x is not SHM_STAMPS long"
.assert (shm_stamp_pl - shm_stamp_y) = SHM_STAMPS * 2, error, "shm_stamp_y is not SHM_STAMPS long"
.segment "CODE"
