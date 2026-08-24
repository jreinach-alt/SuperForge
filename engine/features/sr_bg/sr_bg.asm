; =============================================================================
; sr_bg.asm — BG1: the two-page level world, and the follow camera's publisher
; =============================================================================
; The keystone BG pattern (scroller_bg's mechanics, jumper_bg's blob-built map)
; at the shape this rail exists for: a 64x32 HARDWARE tilemap — two 32x32 pages
; side by side in VRAM, page 1 at the claim base + 0x400 words — built from the
; sr_world blob at scene enter. World column c of row r lands at
;
;  page 0 (c < 32): ES_V_SR_MAP + r*32 + c
;  page 1 (c >= 32): ES_V_SR_MAP + $400 + r*32 + (c - 32)
;
; which is exactly how the PPU reads a 64x32 map back, so the page SEAM at
; world column 32 (world x 256) is this file's addressing fact and nobody
; else's: collision probes the same blob in world coordinates (col_map is total
; by mask) and never sees a page.
;
; An engine with per-layer shadow-DMA plumbing can reach the same picture by
; smuggling page 1 through the BG2 path. There is no plumbing to smuggle
; through here and no need: the claim asks for 0x800 words and the two build
; loops below write both pages under the enter forced blank.
;
; WHAT IS *NOT* HERE, and it is not an omission: BGMODE, TM, BG1SC and BG12NBA.
; Those are declared in this feature's `[[claims.reg]]` under `scene_writes`,
; so they live in game/scroll_run/scenes/run.asm where the layer identity of
; the scene is decided — no_literals' declaration-that-lies check refuses the
; split being wrong in either direction. The camera words are likewise WRITTEN
; by the scene's follow step (a pure function of the player, clamped) and only
; PUBLISHED here — cf_bg's division of labour.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `sr_up` dma_init claim names — a declared resource, not a hard-coded 0.
SR_REGS = $4300 + ES_D_SR_UP_CH * 16

SR_PAGE_DIM = 32                ; one hardware page is 32x32 cells
SR_PAGE_WORDS = SR_PAGE_DIM * SR_PAGE_DIM
SR_WORLD_COLS = 64              ; the world blob's row stride, in cells

; --- sr_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call. One arming site is the only shape a caller cannot
; forget (room_bg.asm and scroller_bg.asm record the same reasoning).
sr_up_dma:
    .a16
    .i16
    stx a:SR_REGS + 2               ; A1T
    sty a:SR_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:SR_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_SR_UP_DMAP
    sta a:SR_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_SR_UP_BBAD
    sta a:SR_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_SR_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- sr_map_page: write ONE hardware page from the world blob ---------------
; In: A16/I16, DB=0, forced blank; VMADD already set to the page's word base;
;  X = the blob offset of the page's first cell (0 for page 0, 32 for
;  page 1). Clobbers A, X, Y.
;
; 32 rows of 32 cells. The blob's row stride is 64 (the whole world), so the
; page reads 32 consecutive bytes and then skips the 32 that belong to the
; OTHER page — that skip IS the seam split. One tilemap word per world byte:
; the map authors palette group 0 and priority 0, so a tilemap word IS its tile
; id (scroller_bg's property). The A16 long-indexed read picks up TWO bytes;
; the mask keeps this cell's. (At the last cell of page 1 the high byte read is
; the byte after the blob — same window, masked off, harmless: jumper_bg's
; note.)
sr_map_page:
    .a16
    .i16
    ldy #0                          ; row counter
@row:
    .a16
    .i16
    phy
    ldy #0                          ; column-within-page counter
@cell:
    .a16
    .i16
    lda f:sr_world_bin, x
    and #$00FF                      ; this cell's byte only
    sta a:$2118                     ; VMDATA word mode; VMADD auto-advances
    inx
    iny
    cpy #SR_PAGE_DIM
    bcc @cell
    txa
    clc
    adc #SR_WORLD_COLS - SR_PAGE_DIM
    tax                             ; skip the other page's 32 columns
    ply
    iny
    cpy #SR_PAGE_DIM
    bcc @row
    rts

; --- sr_build_map: both pages of the 64x32 tilemap, from the blob -----------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; Page 0 then page 1, each a contiguous 0x400-word VMDATA run — VMADD is set
; once per page and auto-advances across it, so the two runs and the two blob
; start offsets are the entire seam mechanics.
sr_build_map:
    .a16
    .i16
    lda #ES_V_SR_MAP
    sta a:$2116                     ; VMADD = page 0's word base
    ldx #0                          ; blob offset: world column 0
    jsr sr_map_page
    lda #ES_V_SR_MAP + SR_PAGE_WORDS
    sta a:$2116                     ; VMADD = page 1's word base (+0x400)
    ldx #SR_PAGE_DIM                ; blob offset: world column 32
    jsr sr_map_page
    rts

; --- sr_arm: CHR, palette, both map pages, the camera (scene enter) ---------
; CONTRACT sr_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palette, both map pages and the camera
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
;
; The camera write is the `sr_cam` claim's write-before-read contract — the
; reason that claim carries no `[init] zero`. The boot camera is 0: the player
; spawns at world x 16, and clamp(16 - 128, 0, 256) = 0 — the scene's follow
; recomputes the same value on the first tick, so the zero here is the follow's
; own answer, not a placeholder.
sr_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sr_arm"
    stz z:ES_SR_CAM + 0             ; cam_x = 0 (the left-edge clamp)
    stz z:ES_SR_CAM + 2             ; cam_y = 0 (pinned for the rail's life)
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: tiles 0/1 empty, 2 terrain, 3 goal ----------------------
    lda #ES_V_SR_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(sr_bg_chr_bin)
    ldy #ES_R_SR_BG_CHR_SIZE
    lda #^sr_bg_chr_bin
    jsr sr_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is colour 0 and the backdrop at once (feature.toml). CGDATA
    ; is a word port written low-then-high; 16 words is a few dozen cycles of
    ; forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_SR_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:sr_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SR_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap: both hardware pages, from the world blob ------------
    jsr sr_build_map
    rts

; --- sr_bg_nmi_commit: BG1HOFS/BG1VOFS, every armed VBlank ------------------
; CONTRACT sr_bg_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      BG1HOFS and BG1VOFS committed from the camera shadow
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. The scroll registers are write-twice latches, so
;             the pair must land inside one VBlank and not straddle two
;   tail:     rts
;
; Both are write-twice 8-bit latches: low byte then high byte; the PPU keeps 10
; bits, which is what makes the 64x32 map's 512px of horizontal world
; addressable at all (a 32x32 rail only ever uses 8 of them). Cam_x is already
; clamped to 0..256 by the scene's follow, so no wrap is in play on this rail —
; the latch sees exactly the world window the follow chose.
;
; THE TWO AXES ARE NOT SYMMETRIC, and the difference is one pixel. BG1HOFS is
; exact: screen column x shows tilemap column HOFS + x. BG1VOFS is not:
; scanline N shows tilemap line VOFS + N, and the first ACTIVE scanline is 1,
; so the `dec` puts world row 0 on it (pfs_bg's measured derivation;
; scroller_bg and cf_bg carry the same correction). Cam_y = 0 is safe under it:
; `dec` gives $FFFF, the PPU keeps 1023, and scanline 1 renders line (1023 + 1)
; mod 256 = 0. The correction is modular, so it needs no clamp.
;
; WIDTH-RISK: entered A8/I16 from sm_nmi_hook and MUST return A8/I16. The block
; below toggles to A16 for the one 16-bit decrement and narrows back before the
; two byte stores; the `xba` is what reaches the high byte after the narrowing,
; since `sep #$20` parks it in B rather than discarding it.
sr_bg_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "sr_bg_nmi_commit"
    lda z:ES_SR_CAM + 0
    sta a:$210D                     ; BG1HOFS, low
    lda z:ES_SR_CAM + 1
    sta a:$210D                     ; BG1HOFS, high
    rep #$20
    .a16
    lda z:ES_SR_CAM + 2
    dec a                           ; scanline N shows line VOFS + N
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rts
