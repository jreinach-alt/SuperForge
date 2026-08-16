; =============================================================================
; brawler_bg.asm — BG1: the terrain floor, tiled from the art patch
; =============================================================================
; The keystone BG pattern (scroller_bg / stomper_bg's shape) with this rail's
; axis: the world is not a per-cell blob but an 8x6 art PATCH that the build
; loop TILES — `col mod 8` across, and a chosen patch ROW down (grass tops on
; the surface row, dirt fill under it). That is what keeps the map blob at 48
; words instead of 1024.
;
; THE WHOLE MAP IS WRITTEN, not just the floor. Power-on VRAM is random (rule
; 5) and nothing clears a tilemap shadow on the way in, so the rows above and
; below the floor are written EXPLICITLY as the reserved blank tile, so the
; sky is the backdrop colour by construction rather than by whatever survived
; the boot.
;
; WHAT IS *NOT* HERE: BGMODE, TM, BG1SC, BG12NBA — this feature's
; `scene_writes` permission, written by scene-enter code where the layer
; identity of a Mode 1 BG1+BG3 scene is decided (scroller_bg's reasoning).
; BG1HOFS/BG1VOFS ARE here: the static pin is this feature's own write, once,
; under the enter forced blank — neither knight scrolls the arena.
;
; Every VRAM/CGRAM byte moves under the enter-time forced blank scene_mgr's
; switch contract guarantees, with NMI masked across it.

; The enter-time GP-DMA register file, addressed through the channel the
; `br_bg_up` dma_init claim names — a declared resource, not a hard-coded 0.
BR_BG_REGS = $4300 + ES_D_BR_BG_UP_CH * 16

; The blank tile every non-floor cell shows. Png2snes reserves blob index 0 as
; an all-transparent tile before it dedupes anything (its own "blob index 0 is
; RESERVED as the blank tile"), so this is the converter's contract, not a
; guess about what tile 0 happens to contain.
BR_BLANK_TILE = 0

; Sentinel for "this tilemap row is not floor": br_build_map keeps the patch
; row's BYTE offset into br_bg_map here, and this value means blank. It cannot
; collide with a real offset — the blob is 96 bytes.
BR_ROW_BLANK = $FFFF
.assert ES_R_BR_BG_MAP_SIZE < BR_ROW_BLANK, error, "the blank-row sentinel collides with a real patch offset"

; --- br_bg_up_dma: one VRAM upload. VMADD must already be set by the caller -
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call (scroller_bg/stomper_bg's one-arming-site shape).
br_bg_up_dma:
    .a16
    .i16
    stx a:BR_BG_REGS + 2            ; A1T
    sty a:BR_BG_REGS + 5            ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:BR_BG_REGS + 4            ; A1B — the bank byte the caller passed
    lda #ES_D_BR_BG_UP_DMAP
    sta a:BR_BG_REGS + 0            ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_BR_BG_UP_BBAD
    sta a:BR_BG_REGS + 1            ; BBAD: VMDATAL
    lda #(1 << ES_D_BR_BG_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- br_build_map: tile the floor across the whole 32x32 tilemap ------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X.
;
; One patch WORD per cell, written straight through: the patch authors palette
; group 0 and priority 0, so every attribute bit above the tile id is zero and
; the word IS the id + group (the converter bakes exactly that). VMADD
; auto-advances, so the 1,024 cells stream in row-major order with one VMADD.
br_build_map:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_BR_MAP
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    stz z:US_ROW
@row:
    .a16
    .i16
    ; ---- pick this row's patch row (or the blank sentinel) ---------------
    lda z:US_ROW
    cmp #BR_FLOOR_ROW
    bcc @blank                      ; above the floor
    cmp #BR_FLOOR_END
    bcs @blank                      ; below it
    cmp #BR_FLOOR_ROW
    bne @fill
    lda #(BR_PATCH_TOP * BR_PATCH_W * 2)
    bra @row_set
@fill:
    .a16
    .i16
    lda #(BR_PATCH_FILL * BR_PATCH_W * 2)
    bra @row_set
@blank:
    .a16
    .i16
    lda #BR_ROW_BLANK
@row_set:
    .a16
    .i16
    sta z:US_TILE                   ; the row's patch byte offset, or blank
    ; ---- 32 cells across, wrapping the 8-cell patch ----------------------
    stz z:US_COL
@cell:
    .a16
    .i16
    lda z:US_TILE
    cmp #BR_ROW_BLANK
    bne @from_patch
    lda #BR_BLANK_TILE
    bra @emit
@from_patch:
    .a16
    .i16
    lda z:US_COL
    and #(BR_PATCH_W - 1)           ; col mod 8 — the patch wraps across
    asl a                           ; -> word index -> byte index
    clc
    adc z:US_TILE
    tax
    lda f:br_bg_map_bin, x          ; the patch word: tile id + palette group
@emit:
    .a16
    .i16
    sta a:$2118                     ; VMDATA word mode; VMADD auto-advances
    lda z:US_COL
    inc a
    sta z:US_COL
    cmp #BR_MAP_W
    bcc @cell
    lda z:US_ROW
    inc a
    sta z:US_ROW
    cmp #BR_MAP_W                   ; 32 rows: the map is square
    bcc @row
    rts

; --- br_arm: CHR, palette, the map, the scroll pin (scene enter) ------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). Clobbers A, X, Y.
br_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the 49 deduped terrain tiles ---------------------------
    lda #ES_V_BR_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(br_bg_chr_bin)
    ldy #ES_R_BR_BG_CHR_SIZE
    lda #^br_bg_chr_bin
    jsr br_bg_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — the claim
    ; covers it (feature.toml). CGDATA is a byte port written
    ; low-then-high; 16 words is a few dozen cycles of forced blank.
    sep #$20
    .a8
    lda #ES_C_BR_BG_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:br_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_BR_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap, tiled from the patch --------------------------------
    jsr br_build_map
    ; ---- the scroll pin: HOFS 0, VOFS -1, written ONCE --------------------
    ; Scanline N shows tilemap line VOFS + N and the first active scanline is 1
    ; (pfs_bg's measured derivation, scroller_bg's `dec`) — so VOFS = -1 puts
    ; tilemap row 0 on the first active scanline, and tilemap row 20's top edge
    ; lands on screen y 160 = BR_SURFACE_TOP, which is what the lane band
    ; anchors the drawn feet to. The PPU keeps 10 bits; -1 reads as 1023 and
    ; scanline 1 renders line (1023 + 1) mod 256 = 0. This feature's own
    ; registers (NOT scene_writes): the write site is this file, the reg gate's
    ; feature-strict tier.
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS low (write-twice latch)
    stz a:$210D                     ; BG1HOFS high
    lda #$FF
    sta a:$210E                     ; BG1VOFS low  = -1
    sta a:$210E                     ; BG1VOFS high
    rep #$20
    .a16
    rts
