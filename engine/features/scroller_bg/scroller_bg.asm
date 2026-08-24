; =============================================================================
; scroller_bg.asm — BG1: a built checkerboard, and the camera that slides it
; =============================================================================
; The keystone BG pattern at its smallest: enter-time forced-blank CHR upload
; through the declared `scr_up` dma_init channel, a 16-word palette written
; CPU-side, a tilemap BUILT rather than uploaded, and a two-axis camera the NMI
; hook commits to BG1HOFS *and* BG1VOFS every armed frame.
;
; WHAT IS *NOT* HERE, and it is not an omission: BGMODE, TM, BG1SC and BG12NBA.
; Those are declared in this feature's `[[claims.reg]]` under `scene_writes`,
; which is a PERMISSION granted to scene-enter code — and no_literals'
; declaration-that-lies check refuses the permission if this feature's own ASM
; writes them too. So they live in game/scroller/scenes/world.asm, where the
; layer identity of a Mode 1 BG1 scene is decided, and that placement is
; enforced rather than conventional.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `scr_up` dma_init claim names — a declared resource, not a hard-coded 0.
SCR_REGS = $4300 + ES_D_SCR_UP_CH * 16

SCR_MAP_DIM = 32                ; the tilemap is 32x32 cells; 0x400 words

; The two checker cells. These are TILE IDS inside the scr_chr claim's grid,
; and they are also the tilemap words outright: the map authors palette group 0
; and priority 0, so every attribute bit above the tile id is zero and a
; tilemap word IS its tile id. That is the same property that makes the palette
; claim start at CGRAM word 0 (feature.toml), and it is why the build loop can
; toggle a single bit and be done.
SCR_TILE_EMPTY = 0              ; index 0 everywhere -> the backdrop shows
SCR_TILE_SOLID = 1              ; index 1 everywhere -> palette word 1, green

; --- scr_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call. One arming site is the only shape a caller cannot
; forget (room_bg.asm and pfs_bg.asm record the same reasoning). Arm it once
; outside a multi-slot loop and only the first transfer moves bytes.
scr_up_dma:
    .a16
    .i16
    stx a:SCR_REGS + 2              ; A1T
    sty a:SCR_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:SCR_REGS + 4              ; A1B — the bank byte the caller passed
    lda #ES_D_SCR_UP_DMAP
    sta a:SCR_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_SCR_UP_BBAD
    sta a:SCR_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_SCR_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- scr_build_map: the checkerboard, written straight to VMDATA ------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; tile = (col ^ row) & 1, for 32x32 cells, written cell by cell. Kept as a
; loop rather than baked into a ROM blob because that loop is the thing the
; rail exists to show; see scroller_rom/feature.toml.
;
; NO SCRATCH BYTE, and the reason is arithmetic rather than cleverness: (col ^
; row) & 1 == (col & 1) ^ (row & 1), so the word simply TOGGLES along a row,
; and each row starts on the opposite cell from the one above. A row is 32
; cells — an even number — so after a row the toggling has returned A to that
; row's starting value, and one more `eor` is exactly the next row's start. The
; whole map is therefore one accumulator and two counters.
scr_build_map:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_SCR_MAP
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    ldy #0                          ; row
    lda #SCR_TILE_EMPTY             ; row 0, col 0 -> (0 ^ 0) & 1 = empty
@row:
    .a16
    .i16
    ldx #0                          ; col
@col:
    .a16
    .i16
    sta a:$2118                     ; VMDATA, word mode; VMADD auto-advances
    eor #1                          ; the checker toggles every column
    inx
    cpx #SCR_MAP_DIM
    bcc @col
    eor #1                          ; ...and again at the row boundary
    iny
    cpy #SCR_MAP_DIM
    bcc @row
    rts

; --- scr_arm: CHR, palette, the map, the camera (scene enter) ---------------
; CONTRACT scr_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      CHR, palette, the tilemap and the camera
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
;
; The camera write is the `scr_cam` claim's write-before-read contract — the
; reason that claim carries no `[init] zero`. Scene_mgr holds NMI masked across
; the whole switch, so the first VBlank that can commit these words is the
; first one AFTER this routine ran; there is no frame in which the NMI hook
; could publish power-on garbage to BG1HOFS/BG1VOFS.
scr_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "scr_arm"
    stz z:ES_SCR_CAM + 0            ; cam_x, world px
    stz z:ES_SCR_CAM + 2            ; cam_y, world px
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the two checker cells -----------------------------------
    lda #ES_V_SCR_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(scr_bg_chr_bin)
    ldy #ES_R_SCR_BG_CHR_SIZE
    lda #^scr_bg_chr_bin
    jsr scr_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — one word, two
    ; meanings, which is why this feature claims it rather than composing
    ; `backdrop` (feature.toml). CGDATA is a word port written as two
    ; bytes low-then-high, so the loop is CPU-side: 16 words is a few dozen
    ; cycles of forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_SCR_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:scr_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SCR_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap -------------------------------------------------------
    jsr scr_build_map
    rts

; --- scr_bg_nmi_commit: BG1HOFS/BG1VOFS, every armed VBlank -----------------
; CONTRACT scr_bg_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      BG1HOFS and BG1VOFS committed from the camera shadow
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. The scroll registers are write-twice latches, so
;             the pair must land inside one VBlank and not straddle two
;   tail:     rts
;
; Both are write-twice 8-bit latches: low byte then high byte, and the PPU
; keeps only 10 bits. The map is 32x32 = 256 px on each axis, so the camera
; WRAPS every 256 px — a torus, since the camera is bounded nowhere at all.
; U16 wraparound at 65536 is a multiple of 256, so the picture stays
; continuous across that too.
;
; THE TWO AXES ARE NOT SYMMETRIC, and the difference is one pixel. BG1HOFS is
; exact: screen column x shows tilemap column HOFS + x. BG1VOFS is not:
; scanline N shows tilemap line VOFS + N, and the first ACTIVE scanline is 1,
; so a naive `VOFS = cam_y` puts world line cam_y + 1 at the top of the
; picture. Pfs_bg measured this on the emulator and carries the derivation
; (pfs_bg.asm:121-134); the `dec` below is the same correction, re-verified
; here by tests/test_scroller.py::test_world_origin_is_at_screen_origin, which
; reads the rendered frame at cam (0,0) and would fail by exactly one 8 px cell
; if this were dropped.
;
; cam_y = 0 is safe under it: `dec` gives $FFFF, the PPU keeps 1023, and
; scanline 1 renders line (1023 + 1) mod 256 = 0. The correction is modular, so
; it needs no clamp.
;
; WIDTH-RISK: entered A8/I16 from sm_nmi_hook and MUST return A8/I16. The block
; below toggles to A16 for the one 16-bit decrement and narrows back before the
; two byte stores; the `xba` is what reaches the high byte after the narrowing,
; since `sep #$20` parks it in B rather than discarding it.
scr_bg_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "scr_bg_nmi_commit"
    lda z:ES_SCR_CAM + 0
    sta a:$210D                     ; BG1HOFS, low
    lda z:ES_SCR_CAM + 1
    sta a:$210D                     ; BG1HOFS, high
    rep #$20
    .a16
    lda z:ES_SCR_CAM + 2
    dec a                           ; scanline N shows line VOFS + N
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rts
