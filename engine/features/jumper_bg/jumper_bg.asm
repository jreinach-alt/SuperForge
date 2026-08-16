; =============================================================================
; jumper_bg.asm — BG1: the terrain, built from the world blob
; =============================================================================
; The keystone BG pattern with this rail's one addition: the tilemap is BUILT
; from jr_world's 1,024 tile-id bytes at scene enter — the same blob col_map
; probes — so the drawn terrain and the solid terrain agree by construction
; (jumper_rom/feature.toml carries the argument).
;
; NO CAMERA. The world is one screen and nothing ever scrolls it; the
; scroll latches are pinned once, here, under the enter forced blank (HOFS 0
; exact, VOFS -1 per pfs_bg's scanline derivation), and never republished —
; nothing changes them, so there is nothing for an NMI hook to commit.
;
; WHAT IS *NOT* HERE: BGMODE, TM, BG1SC, BG12NBA — declared in this feature's
; [[claims.reg]] under scene_writes, written by scene-enter code in
; game/jumper/scenes/sky.asm, where the layer identity of a Mode 1 BG1 scene is
; decided (scroller_bg's split, unchanged).
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it.

; The enter-time GP-DMA register file, addressed through the channel the
; `jr_up` dma_init claim names — a declared resource, not a hard-coded 0.
JR_REGS = $4300 + ES_D_JR_UP_CH * 16

JR_MAP_CELLS = 32 * 32          ; the world: 32x32 cells, one byte each

; --- jr_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — armed HERE, inside the routine, once per call (room_bg /
; scroller_bg's one-arming-site shape).
jr_up_dma:
    .a16
    .i16
    stx a:JR_REGS + 2               ; A1T
    sty a:JR_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:JR_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_JR_UP_DMAP
    sta a:JR_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_JR_UP_BBAD
    sta a:JR_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_JR_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- jr_build_map: the display tilemap, read out of the world blob ----------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X.
;
; One tilemap word per world byte: the map authors palette group 0 and priority
; 0, so a tilemap word IS its tile id (scroller_bg's property). The A16
; long-indexed read picks up TWO bytes; the mask keeps this cell's. (At the
; last cell the high byte read is jr_flags' first byte — same window, masked
; off, harmless.)
jr_build_map:
    .a16
    .i16
    lda #ES_V_JR_MAP
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    ldx #0
@cell:
    .a16
    .i16
    lda f:jr_world_bin, x
    and #$00FF                      ; this cell's byte only
    sta a:$2118                     ; VMDATA word mode; VMADD auto-advances
    inx
    cpx #JR_MAP_CELLS
    bcc @cell
    rts

; --- jr_arm: CHR, palette, the built map, the pinned scroll (scene enter) ---
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). Clobbers A, X, Y.
jr_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: tiles 0/1 empty, tile 2 the terrain ---------------------
    lda #ES_V_JR_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(jr_bg_chr_bin)
    ldy #ES_R_JR_BG_CHR_SIZE
    lda #^jr_bg_chr_bin
    jsr jr_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is colour 0 and the backdrop at once (feature.toml). CGDATA
    ; is a word port written low-then-high; 16 words is a few dozen cycles of
    ; forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_JR_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:jr_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_JR_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap, from the world blob ---------------------------------
    jsr jr_build_map
    ; ---- the pinned scroll ------------------------------------------------
    ; HOFS 0 exact: screen column x shows world column x. VOFS -1: scanline N
    ; shows tilemap line VOFS + N and the first ACTIVE scanline is 1, so -1
    ; puts world row 0 on it (pfs_bg's measured derivation; scroller's NMI
    ; commit carries the same `dec`). $FF twice through the write-twice latch
    ; is $FFFF; the PPU keeps 10 bits = 1023 = -1 mod 1024. Written ONCE:
    ; nothing in this rail ever changes them, and a scene must not inherit
    ; whatever the previous one left in these latches (room_bg's note).
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS low
    stz a:$210D                     ; BG1HOFS high
    lda #255
    sta a:$210E                     ; BG1VOFS low  = $FF
    sta a:$210E                     ; BG1VOFS high = $FF
    rep #$20
    .a16
    rts
