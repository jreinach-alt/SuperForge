; =============================================================================
; pfs_bg.asm — BG1 as a 64x64 streaming RING: the layer, not its contents
; =============================================================================
; The division this feature exists to draw (feature.toml states it at length):
; THIS file owns the LAYER — the CHR page, the 16-word palette that includes
; the backdrop, and the two scroll registers committed every armed VBlank —
; while `pfs_stream` owns the CONTENTS of the ring the scroll slides over.
;
; WHAT IS *NOT* HERE, and it is not an omission: BGMODE, TM, TS, BG1SC and
; BG12NBA. Those are declared in this feature's `[[claims.reg]]` under
; `scene_writes`, which is a PERMISSION granted to scene-enter code — and
; no_literals' declaration-that-lies check refuses the permission if this
; feature's own ASM writes them too. So they live in the scene's enter, where
; the layer identity of a Mode 1 BG1 scene is decided, and that placement is
; enforced rather than conventional.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `pfs_up` dma_init claim names — a declared resource, not a hard-coded 0.
PB_REGS = $4300 + ES_D_PFS_UP_CH * 16

; --- pb_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call. One arming site is the only shape that cannot be
; forgotten by a caller (room_bg.asm records the same reasoning). Arm it once
; outside a multi-slot loop and only the first transfer moves bytes.
pb_up:
    .a16
    .i16
    stx a:PB_REGS + 2               ; A1T
    sty a:PB_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:PB_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_PFS_UP_DMAP
    sta a:PB_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_PFS_UP_BBAD
    sta a:PB_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_PFS_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- pfs_arm: the layer's own state, at scene enter ------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). A = spawn camera X (world px), X = spawn camera Y. Clobbers A, X,
; Y.
;
; The camera write is the `pfs_cam` claim's write-before-read contract — the
; reason that claim carries no `[init] zero`. Scene_mgr holds NMI masked across
; the whole switch, so the first VBlank that can commit these words is the
; first one AFTER this routine ran; there is no frame in which the NMI hook
; could publish power-on garbage to BG1HOFS/BG1VOFS.
pfs_arm:
    .a16
    .i16
    sta z:ES_PFS_CAM + 0            ; cam_x, world px
    stx z:ES_PFS_CAM + 2            ; cam_y, world px
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the 25 Four Seasons tiles -------------------------------
    lda #ES_V_PFS_CHR_V
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(pfs_chr_bin)
    ldy #ES_R_PFS_CHR_SIZE
    lda #^pfs_chr_bin
    jsr pb_up
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — one word, two
    ; meanings, which is why this feature claims it rather than composing
    ; `backdrop` (feature.toml). CGDATA is a word port written as two
    ; bytes low-then-high, so the loop is CPU-side: 16 words is 64 cycles of
    ; forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_PFS_PAL_C
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:pfs_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_PFS_PAL_SIZE
    bcc :-
    rts

; --- pfs_bg_nmi_commit: BG1HOFS/BG1VOFS, every armed VBlank ----------------
; In/out: A8/I16, DB=0 — sm_nmi_hook's contract. Clobbers A.
;
; THE SCROLL AND THE RING READ ONE SOURCE. Committing here rather than in the
; tick is what keeps them from ever disagreeing about which window is on
; screen: `pfs_cam` is the same DP block the ring fill (and, from the next
; milestone, the streamer) derives its resident tile window from, so a frame
; can never scroll to a window whose tiles were not staged.
;
; Both are write-twice 8-bit latches: low byte then high byte, and the PPU
; keeps only 10 bits (the ring is 512 px on each axis, so the top bit of a
; 1024-px world coordinate is discarded by the hardware — which is exactly the
; wrap the ring is built to exploit).
;
; THE TWO AXES ARE NOT SYMMETRIC, and the difference is one pixel that would
; otherwise be inherited by every camera this rail ever grows. BG1HOFS is
; exact: screen column x shows tilemap column HOFS + x. BG1VOFS is not:
; scanline N shows tilemap line VOFS + N, and the first ACTIVE scanline is 1,
; so a naive `VOFS = cam_y` puts world line cam_y + 1 at the top of the
; picture. MEASURED, not assumed (CLAUDE.md rule 1): with cam = (144, 24) the
; plateau's grass row — world y 128, world x 240 — landed at screenshot row 110
; and ended at column 96. Column 96 is exact; row 110 is one high against the
; 111 the exact convention predicts. Hence the `dec` below, and no counterpart
; above it.
;
; cam_y = 0 is safe under it: `dec` gives $FFFF, the PPU keeps 1023, and
; scanline 1 renders line (1023 + 1) mod 512 = 0. The correction is modular, so
; it needs no clamp.
;
; WIDTH-RISK: entered A8/I16 from sm_nmi_hook and MUST return A8/I16. The block
; below toggles to A16 for the one 16-bit decrement and narrows back before the
; two byte stores; the `xba` is what reaches the high byte after the narrowing,
; since `sep #$20` parks it in B rather than discarding it.
pfs_bg_nmi_commit:
    .a8
    .i16
    lda z:ES_PFS_CAM + 0
    sta a:$210D                     ; BG1HOFS, low
    lda z:ES_PFS_CAM + 1
    sta a:$210D                     ; BG1HOFS, high
    rep #$20
    .a16
    lda z:ES_PFS_CAM + 2
    dec a                           ; scanline N shows line VOFS + N
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rts
