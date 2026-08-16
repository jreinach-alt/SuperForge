; =============================================================================
; patrol_bg.asm — BG1: the walled level, rendered at enter from ROM
; =============================================================================
; The keystone BG pattern, seventh instance: enter-time forced-blank CHR upload
; through the declared `pat_up` dma_init channel, a 16-word palette written
; CPU-side, and a tilemap RENDERED from the pat_map blob — the same 1,024 bytes
; the play scene binds as col_map's world, so the picture and the collision
; cannot drift.
;
; WHAT IS *NOT* HERE, and it is not an omission: BGMODE, TM, BG1SC and BG12NBA.
; Those are declared in this feature's `[[claims.reg]]` under `scene_writes` —
; a PERMISSION granted to scene-enter code — and live in
; game/patrol/scenes/play.asm, where the layer identity of a Mode 1 BG1+BG3
; scene is decided. No_literals' declaration-that-lies check enforces the split
; in both directions.
;
; THE SCROLL IS PINNED HERE, ONCE, AT ENTER. The level is one
; screen and nothing ever scrolls it. BG1HOFS = 0; BG1VOFS = -1 —
; scanline N shows tilemap line VOFS + N and the first ACTIVE scanline is 1
; (pfs_bg's measured derivation, scroller_bg's per-frame `dec` made static) —
; so world y = screen y = OAM y, and a beat bound is the same number in the
; map, the picture and the OAM byte. There is NO per-frame BG commit on this
; rail: the NMI hook carries only the OAM DMA and the text queue.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `pat_up` dma_init claim names — a declared resource, not a hard-coded 0.
PAT_REGS = $4300 + ES_D_PAT_UP_CH * 16

PAT_MAP_DIM = 32                ; the tilemap is 32x32 cells; 0x400 words

; --- pat_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call (room_bg.asm's and scroller_bg.asm's shape). Arm
; it once OUTSIDE a multi-slot loop and only the first transfer moves bytes;
; every later MDMAEN in that loop finds a count of zero and silently does
; nothing.
pat_up_dma:
    .a16
    .i16
    stx a:PAT_REGS + 2              ; A1T
    sty a:PAT_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:PAT_REGS + 4              ; A1B — the bank byte the caller passed
    lda #ES_D_PAT_UP_DMAP
    sta a:PAT_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_PAT_UP_BBAD
    sta a:PAT_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_PAT_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- pat_render_map: the level blob -> the BG1 tilemap, cell by cell --------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X, Y.
;
; Each of pat_map's 1,024 bytes becomes one tilemap word verbatim: the map
; authors palette group 0 and priority 0, so every attribute bit above the tile
; id is zero and a tilemap word IS its tile id — which is also what lets
; col_map index the same bytes as tile ids. The four loops that AUTHORED these
; bytes live in tools/gen_patrol_assets.py.
pat_render_map:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_PAT_MAP_V
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    ldx #0
@cell:
    .a16
    .i16
    lda f:pat_map_bin, x            ; one level byte (high byte of A is the
    and #255                        ;   NEXT cell — mask it off)
    sta a:$2118                     ; VMDATA word write; VMADD auto-advances
    inx
    cpx #ES_R_PAT_MAP_SIZE
    bcc @cell
    rts

; --- pat_bg_arm: CHR, palette, the map, the scroll pin (scene enter) --------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). Clobbers A, X, Y.
pat_bg_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the three tiles (0/1 blank, 2 the terrain) --------------
    lda #ES_V_PAT_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(pat_bg_chr_bin)
    ldy #ES_R_PAT_BG_CHR_SIZE
    lda #^pat_bg_chr_bin
    jsr pat_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once (the
    ; feature.toml fold). CGDATA is a word port written as two bytes
    ; low-then-high, so the loop is CPU-side.
    sep #$20
    .a8
    lda #ES_C_PAT_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:pat_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_PAT_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap, rendered from the level blob ------------------------
    jsr pat_render_map
    ; ---- the scroll pin: HOFS 0, VOFS -1, written ONCE --------------------
    ; Both are write-twice 8-bit latches (low then high). The -1: scanline N
    ; shows tilemap line VOFS + N and the first active scanline is 1, so
    ; VOFS = -1 puts world line 0 on the first drawn line. $FFFF's low ten
    ; bits are what the PPU keeps; scanline 1 then renders line (1023 + 1) mod
    ; 256 = 0 — the correction is modular and needs no clamp.
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS low = 0
    stz a:$210D                     ; BG1HOFS high = 0
    lda #255                        ; VOFS = $FFFF = -1
    sta a:$210E                     ; BG1VOFS low
    sta a:$210E                     ; BG1VOFS high
    rep #$20
    .a16
    rts
