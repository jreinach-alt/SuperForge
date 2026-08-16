; =============================================================================
; stomper_bg.asm — BG1: the arena, rendered from the world blob
; =============================================================================
; The keystone BG pattern (scroller_bg's shape) with this rail's axis: the
; tilemap is BUILT from the `st_world` ROM blob at scene enter, so the bytes on
; screen and the bytes col_map probes are the same 1,024 bytes of ROM — display
; and collision cannot disagree, by construction. Unlike scroller's
; checkerboard (a taught expression), this arena is level DESIGN: data, baked
; by the generator from the four loops that describe it.
;
; WHAT IS *NOT* HERE: BGMODE, TM, BG1SC, BG12NBA — this feature's
; `scene_writes` permission, written by scene-enter code where the layer
; identity of a Mode 1 BG1+BG3 scene is decided (scroller_bg's reasoning).
; BG1HOFS/BG1VOFS ARE here: the static pin is this feature's own write, once,
; under the enter forced blank — the arena does not scroll.
;
; Every VRAM/CGRAM byte moves under the enter-time forced blank scene_mgr's
; switch contract guarantees, with NMI masked across it.

; The enter-time GP-DMA register file, addressed through the channel the
; `st_up` dma_init claim names — a declared resource, not a hard-coded 0.
ST_BG_REGS = $4300 + ES_D_ST_UP_CH * 16

; --- st_up_dma: one VRAM upload. VMADD must already be set by the caller ----
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the LOW byte. Clobbers A, X, Y.
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, inside
; the routine, once per call (scroller_bg/room_bg's one-arming-site shape).
st_up_dma:
    .a16
    .i16
    stx a:ST_BG_REGS + 2            ; A1T
    sty a:ST_BG_REGS + 5            ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:ST_BG_REGS + 4            ; A1B — the bank byte the caller passed
    lda #ES_D_ST_UP_DMAP
    sta a:ST_BG_REGS + 0            ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_ST_UP_BBAD
    sta a:ST_BG_REGS + 1            ; BBAD: VMDATAL
    lda #(1 << ES_D_ST_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- st_build_map: render the world blob to the tilemap ---------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X.
;
; One tile-id BYTE per world cell becomes one tilemap WORD: the map authors
; palette group 0 and priority 0, so every attribute bit above the id is zero
; and the word IS the id (scroller_bg's property, from a blob instead of an
; expression). Col_map reads the same blob bytes by the same index, which is
; the single-source point.
st_build_map:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_ST_MAP
    sta a:$2116                     ; VMADD = the tilemap claim's word base
    ldx #0
@cell:
    .a16
    .i16
    lda f:st_world_bin, x           ; a 16-bit load grabs id + neighbour —
    and #$00FF                      ;   mask to the one tile id
    sta a:$2118                     ; VMDATA word mode; VMADD auto-advances
    inx
    cpx #ES_R_ST_WORLD_SIZE
    bcc @cell
    rts

; --- st_arm: CHR, palette, the map, the scroll pin (scene enter) ------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr's enter
; contract). Clobbers A, X, Y.
st_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1 CHR: the three tiles (0/1 empty, 2 terrain) ------------------
    lda #ES_V_ST_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(st_bg_chr_bin)
    ldy #ES_R_ST_BG_CHR_SIZE
    lda #^st_bg_chr_bin
    jsr st_up_dma
    ; ---- the 16-word palette, INCLUDING word 0 ----------------------------
    ; Word 0 is the BG's colour 0 and the BACKDROP slot at once — the claim
    ; covers it (feature.toml). CGDATA is a byte port written
    ; low-then-high; 16 words is a few dozen cycles of forced blank.
    sep #$20
    .a8
    lda #ES_C_ST_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:st_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_ST_BG_PAL_SIZE
    bcc :-
    ; ---- the tilemap, from the world blob ---------------------------------
    jsr st_build_map
    ; ---- the scroll pin: HOFS 0, VOFS -1, written ONCE --------------------
    ; Scanline N shows tilemap line VOFS + N and the first active scanline is 1
    ; (pfs_bg's measured derivation, scroller_bg's `dec`) — so VOFS = -1 puts
    ; world row 0 on the first active scanline and world row = screen
    ; row = OAM row: the box the physics collides is the box the screen
    ; shows. The PPU keeps 10 bits; -1 reads as 1023 and scanline 1 renders
    ; line (1023 + 1) mod 256 = 0. This feature's own registers (NOT
    ; scene_writes): the write site is this file, the reg gate's feature-strict
    ; tier.
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
