; =============================================================================
; maze_bg.asm — BG1: the walled room, rendered from col_map's own world blob
; =============================================================================
; The keystone BG pattern with this rail's one twist: the tilemap is not baked
; and not authored by an expression — it is READ out of the mz_room ROM blob,
; cell by cell, and written straight to VMDATA under the scene's enter forced
; blank. That blob is also what col_map probes (the scene binds it as
; CM_WORLD_BLOB), so the wall the PPU draws and the wall the move-check hits
; are the same byte by construction (maze_rom/feature.toml).
;
; WHAT IS *NOT* HERE, and it is not an omission: BGMODE, TM, BG1SC and BG12NBA.
; Those are opened to scene-enter code via `scene_writes` (this feature's
; mz_layers claim) and live in game/maze/scenes/room.asm, where the layer
; identity of a Mode 1 BG1 scene is decided; no_literals' declaration-that-lies
; check refuses the placement drifting either way.
;
; Every VRAM/CGRAM byte here moves under the enter-time forced blank
; scene_mgr's switch contract guarantees, with NMI masked across it — so no NMI
; can land mid-upload and re-point VMADD (CLAUDE.md: forced blank does NOT mask
; NMI; $4200 bit 7 does).

; The enter-time GP-DMA register file, addressed through the channel the
; `mz_up` dma_init claim names — a declared resource, not a hard-coded 0.
MZ_REGS = $4300 + ES_D_MZ_UP_CH * 16

MZ_MAP_DIM = 32                 ; the tilemap is 32x32 cells; 0x400 words

; --- mz_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call (room_bg / pfs_bg / scroller_bg's reasoning). Arm
; it once outside a multi-slot loop and only the first transfer moves bytes.
mz_up_dma:
    .a16
    .i16
    stx a:MZ_REGS + 2               ; A1T
    sty a:MZ_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:MZ_REGS + 4               ; A1B — the bank byte the caller passed
    lda #ES_D_MZ_UP_DMAP
    sta a:MZ_REGS + 0               ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_MZ_UP_BBAD
    sta a:MZ_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_MZ_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- mz_render_room: the room blob -> the BG1 tilemap, cell by cell ---------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X.
;
; 1024 iterations of read-byte / write-word. The A16 `lda f:` long read pulls
; TWO blob bytes (tile i in the low byte, tile i+1 in the high); the mask keeps
; the low one, and priority-0 palette-0 means the masked tile id IS the tilemap
; word (scroller_bg's property — it is what lets a test compare the VRAM word
; directly against the blob byte). The room is built cell-by-cell at enter,
; out of the same byte map the generator authored it with, so the map is the
; source and the picture is derived.
mz_render_room:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MZ_MAP
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    ldx #0
@cell:
    .a16
    .i16
    lda f:mz_room_bin, x            ; blob bytes i (lo) + i+1 (hi)...
    and #255                        ; ...keep tile i; the word IS the tile id
    sta a:$2118                     ; VMDATA word mode; VMADD auto-advances
    inx
    cpx #(MZ_MAP_DIM * MZ_MAP_DIM)
    bcc @cell
    rts

; --- mz_bg_arm: CHR, palette, the rendered room, the scroll pin (enter) -----
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). Clobbers A, X, Y.
mz_bg_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: floor, the explicit-zero spare, the wall ----------------
    lda #ES_V_MZ_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(mz_bg_chr_bin)
    ldy #ES_R_MZ_BG_CHR_SIZE
    lda #^mz_bg_chr_bin
    jsr mz_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once (feature.toml
    ; carries the argument). CGDATA is a word port written low-then-high; 16
    ; words is a few dozen cycles of forced blank and buys no DMA channel.
    sep #$20
    .a8
    lda #ES_C_MZ_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:mz_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MZ_BG_PAL_SIZE
    bcc :-
    ; ---- the room ---------------------------------------------------------
    jsr mz_render_room
    ; ---- the scroll pin ---------------------------------------------------
    ; The room is one screen and does not scroll, and a scene must not inherit
    ; whatever power-on left in these latches (room_bg's reasoning, rule 5).
    ; BG1HOFS is exact: screen column x shows tilemap column HOFS + x, so it
    ; pins to 0. BG1VOFS is not: scanline N shows tilemap line VOFS + N and the
    ; first ACTIVE scanline is 1, so the pin is -1 (pfs_bg's measured
    ; derivation, scroller_bg's per-frame `dec` made static). That one pixel is
    ; what makes world y = screen y = OAM y, so a wall-stop coordinate is the
    ; same number in the map, the picture and the OAM byte — tests/test_maze.py
    ; asserts it from the drawn frame. Write-twice 8-bit latches: low byte then
    ; high byte.
    sep #$20
    .a8
    stz a:$210D                     ; BG1HOFS = 0
    stz a:$210D
    lda #<-1
    sta a:$210E                     ; BG1VOFS = -1 ($FFFF; the PPU keeps 10
    sta a:$210E                     ;   bits, and 1023 + 1 = line 0 at the top)
    rep #$20
    .a16
    rts
